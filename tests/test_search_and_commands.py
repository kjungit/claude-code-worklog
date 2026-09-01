"""Tests for the search index, archive command, debug log rotation, and the /worklog-* CLI.

Run with: python3 tests/test_search_and_commands.py
"""

import datetime
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(REPO_ROOT, "hooks", "cli.py")
sys.path.insert(0, os.path.join(REPO_ROOT, "hooks", "lib"))

import archive as archive_module  # noqa: E402
import debug_log  # noqa: E402
import paths  # noqa: E402
import search_index  # noqa: E402


class TempDataDir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="worklog-fb4-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        patcher = mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_DATA": self.tmp})
        patcher.start()
        self.addCleanup(patcher.stop)


SAMPLE_SUMMARY = {
    "session_id": "sess-1",
    "project": "my-app",
    "title": "Fixed the redirect URI bug",
    "questions_asked": ["why is the oauth redirect failing"],
    "problems": [{"problem": "redirect_uri_mismatch", "solution": "fixed the callback URL"}],
    "decisions": [],
    "tags": ["auth", "bugfix"],
    "abandoned_attempts": [],
}


class SearchIndexTest(TempDataDir):
    def test_upsert_then_search_finds_it(self):
        search_index.upsert_summary("2026-08-29", "sess-1", SAMPLE_SUMMARY)
        results = search_index.search("redirect")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["date"], "2026-08-29")
        self.assertEqual(results[0]["project"], "my-app")

    def test_search_no_match(self):
        search_index.upsert_summary("2026-08-29", "sess-1", SAMPLE_SUMMARY)
        self.assertEqual(search_index.search("kubernetes"), [])

    def test_upsert_is_idempotent_for_same_session(self):
        search_index.upsert_summary("2026-08-29", "sess-1", SAMPLE_SUMMARY)
        search_index.upsert_summary("2026-08-29", "sess-1", SAMPLE_SUMMARY)
        self.assertEqual(len(search_index.search("redirect")), 1)

    def test_rebuild_from_summary_files_on_disk(self):
        raw_dir = paths.raw_session_dir("2026-08-29")
        os.makedirs(raw_dir, exist_ok=True)
        with open(os.path.join(raw_dir, "sess-1.summary.json"), "w", encoding="utf-8") as fh:
            json.dump(SAMPLE_SUMMARY, fh)

        count = search_index.rebuild()
        self.assertEqual(count, 1)
        self.assertEqual(len(search_index.search("redirect")), 1)

    def test_rebuild_is_safe_with_no_data_at_all(self):
        self.assertEqual(search_index.rebuild(), 0)


class ArchiveTest(TempDataDir):
    def _make_date_dir(self, date_str):
        d = paths.raw_session_dir(date_str)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "sess.jsonl"), "w", encoding="utf-8") as fh:
            fh.write('{"type": "prompt"}\n')
        return d

    def test_old_date_is_archived_without_deleting_original(self):
        old_date = (datetime.date.today() - datetime.timedelta(days=200)).isoformat()
        original_dir = self._make_date_dir(old_date)

        archived = archive_module.archive_older_than(180)

        self.assertEqual(archived, [old_date])
        self.assertTrue(os.path.isdir(original_dir))  # never deleted
        self.assertTrue(os.path.exists(os.path.join(original_dir, "sess.jsonl")))  # untouched
        tar_path = os.path.join(self.tmp, "archive", "%s.tar.gz" % old_date)
        self.assertTrue(os.path.exists(tar_path))
        with tarfile.open(tar_path) as tar:
            self.assertIn("%s/sess.jsonl" % old_date, tar.getnames())

    def test_recent_date_is_not_archived(self):
        recent_date = (datetime.date.today() - datetime.timedelta(days=5)).isoformat()
        self._make_date_dir(recent_date)
        self.assertEqual(archive_module.archive_older_than(180), [])

    def test_already_archived_date_is_skipped_on_second_run(self):
        old_date = (datetime.date.today() - datetime.timedelta(days=200)).isoformat()
        self._make_date_dir(old_date)
        first = archive_module.archive_older_than(180)
        second = archive_module.archive_older_than(180)
        self.assertEqual(first, [old_date])
        self.assertEqual(second, [])

    def test_configured_days_env_var_used_when_no_explicit_arg(self):
        recent_date = (datetime.date.today() - datetime.timedelta(days=10)).isoformat()
        self._make_date_dir(recent_date)
        with mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_OPTION_ARCHIVE_AFTER_DAYS": "5"}):
            archived = archive_module.archive_older_than(None)
        self.assertEqual(archived, [recent_date])


class DebugLogRotationTest(TempDataDir):
    def test_rotates_to_max_lines(self):
        for i in range(debug_log.MAX_LINES + 50):
            debug_log.log("line %d" % i)
        with open(paths.debug_log_path(), encoding="utf-8") as fh:
            lines = fh.readlines()
        self.assertEqual(len(lines), debug_log.MAX_LINES)
        self.assertIn("line %d" % (debug_log.MAX_LINES + 49), lines[-1])

    def test_tail_returns_empty_list_when_no_log(self):
        self.assertEqual(debug_log.tail(10), [])


def run_cli(args, env_overrides):
    env = dict(os.environ)
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, CLI] + args, capture_output=True, text=True, env=env, timeout=15
    )


class CliSmokeTest(TempDataDir):
    def test_show_with_no_data_reports_absence(self):
        proc = run_cli(["show", "2026-08-29"], {"CLAUDE_PLUGIN_DATA": self.tmp})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("No worklog for 2026-08-29", proc.stdout)

    def test_show_with_data_prints_note(self):
        os.makedirs(paths.notes_dir(), exist_ok=True)
        with open(paths.note_path("2026-08-29"), "w", encoding="utf-8") as fh:
            fh.write("---\ndate: 2026-08-29\n---\n\nhello\n")
        proc = run_cli(["show", "2026-08-29"], {"CLAUDE_PLUGIN_DATA": self.tmp})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("hello", proc.stdout)

    def test_search_with_no_index_reports_no_matches(self):
        proc = run_cli(["search", "nothing", "here"], {"CLAUDE_PLUGIN_DATA": self.tmp})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("No matches", proc.stdout)

    def test_archive_with_nothing_to_archive(self):
        proc = run_cli(["archive", "180"], {"CLAUDE_PLUGIN_DATA": self.tmp})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Nothing to archive", proc.stdout)

    def test_debug_with_no_log(self):
        proc = run_cli(["debug"], {"CLAUDE_PLUGIN_DATA": self.tmp})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("No errors logged", proc.stdout)

    def test_doctor_reports_writable_and_no_pending(self):
        proc = run_cli(["doctor"], {"CLAUDE_PLUGIN_DATA": self.tmp})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("writable: yes", proc.stdout)
        self.assertIn("Pending: none", proc.stdout)


if __name__ == "__main__":
    unittest.main()
