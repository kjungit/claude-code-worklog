"""Integration tests for the hooks (docs 25.1, stage 2 -- the three critical defects).

Run with: python3 tests/test_hooks.py
"""

import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
ON_STOP = os.path.join(REPO_ROOT, "hooks", "on_stop.py")
CHECK_AND_SUMMARIZE = os.path.join(REPO_ROOT, "hooks", "check_and_summarize.py")

# Detection/locking is also exercised in-process (not just via subprocess) so these
# tests don't need to spin up a real `claude -p` call to have something to observe.
sys.path.insert(0, os.path.join(REPO_ROOT, "hooks"))
import check_and_summarize  # noqa: E402


def run_hook(script, payload, env_overrides):
    env = dict(os.environ)
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, script],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )


class TempDataDir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="worklog-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def data_env(self, **extra):
        env = {"CLAUDE_PLUGIN_DATA": self.tmp}
        env.update(extra)
        return env


class RecursionGuardTest(TempDataDir):
    """Defect 3 (docs 23.1): claude -p summarization must not re-trigger these hooks."""

    def test_on_stop_does_nothing_when_internal(self):
        transcript = os.path.join(FIXTURES, "normal_session.jsonl")
        payload = {"session_id": "sess-normal", "transcript_path": transcript}
        proc = run_hook(ON_STOP, payload, self.data_env(WORKLOG_INTERNAL="1"))
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(os.listdir(self.tmp), [])

    def test_check_and_summarize_does_nothing_when_internal(self):
        proc = run_hook(CHECK_AND_SUMMARIZE, {}, self.data_env(WORKLOG_INTERNAL="1"))
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(os.listdir(self.tmp), [])


class OnStopCaptureTest(TempDataDir):
    def _capture(self, fixture_name, session_id):
        transcript = os.path.join(FIXTURES, fixture_name)
        payload = {"session_id": session_id, "transcript_path": transcript}
        proc = run_hook(ON_STOP, payload, self.data_env())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc

    def _read_captured(self, date, session_id):
        path = os.path.join(self.tmp, "data", date, "%s.jsonl" % session_id)
        with open(path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def test_normal_session_captured_and_cursor_advances_to_eof(self):
        self._capture("normal_session.jsonl", "sess-normal")
        records = self._read_captured("2026-08-29", "sess-normal")
        types = [r["type"] for r in records]
        self.assertIn("prompt", types)
        self.assertIn("file_change", types)

        cursor_path = os.path.join(self.tmp, ".cursors", "sess-normal.json")
        with open(cursor_path, encoding="utf-8") as fh:
            cursor = json.load(fh)
        transcript_size = os.path.getsize(os.path.join(FIXTURES, "normal_session.jsonl"))
        self.assertEqual(cursor["last_byte_offset"], transcript_size)

    def test_second_run_is_incremental_no_duplicates(self):
        self._capture("normal_session.jsonl", "sess-normal")
        self._capture("normal_session.jsonl", "sess-normal")  # cursor already at EOF, nothing new
        records = self._read_captured("2026-08-29", "sess-normal")
        self.assertEqual([r["type"] for r in records].count("prompt"), 1)

    def test_capture_does_not_filter_dead_branches_that_is_deferred_to_map_stage(self):
        """Defect 1 (docs 22.1): Stop hook must capture everything; DAG filtering happens later."""
        self._capture("rewind_session.jsonl", "sess-rewind")
        records = self._read_captured("2026-08-29", "sess-rewind")
        uuids = {r["uuid"] for r in records}
        self.assertEqual(uuids, {"r1", "r2", "r3"})


class HookFeedbackLoopTest(TempDataDir):
    """Defect 2 (docs 22.2): non-whitelisted line types (hook attachments, bookkeeping) must never
    become raw material, or the hook would end up re-reading its own output next turn."""

    def test_attachment_and_bookkeeping_lines_never_become_raw_material(self):
        transcript = os.path.join(FIXTURES, "noise_types.jsonl")
        payload = {"session_id": "sess-noise", "transcript_path": transcript}
        proc = run_hook(ON_STOP, payload, self.data_env())
        self.assertEqual(proc.returncode, 0, proc.stderr)

        path = os.path.join(self.tmp, "data", "2026-08-29", "sess-noise.jsonl")
        with open(path, encoding="utf-8") as fh:
            records = [json.loads(line) for line in fh if line.strip()]

        self.assertEqual(len(records), 2)
        self.assertEqual({r["type"] for r in records}, {"prompt", "plan"})


class CheckAndSummarizeTest(TempDataDir):
    """The end-to-end subprocess path, for cases with nothing to summarize
    (so no real `claude -p` call happens)."""

    def test_already_summarized_date_is_left_alone(self):
        data_root = os.path.join(self.tmp, "data")
        os.makedirs(os.path.join(data_root, "2026-08-27"))
        os.makedirs(os.path.join(self.tmp, "notes"))
        with open(os.path.join(self.tmp, "notes", "2026-08-27.md"), "w", encoding="utf-8") as fh:
            fh.write("already done")

        proc = run_hook(CHECK_AND_SUMMARIZE, {}, self.data_env())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, ".debug.log")))

    def test_empty_pending_date_is_a_silent_no_op(self):
        # a date folder with no captured sessions in it (nothing ever happened that day)
        os.makedirs(os.path.join(self.tmp, "data", "2026-08-27"))
        proc = run_hook(CHECK_AND_SUMMARIZE, {}, self.data_env())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, ".debug.log")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, ".lock")))  # released, or never truly needed


class CheckAndSummarizeUnitTest(TempDataDir):
    """Direct tests of the detection/locking logic -- no subprocess, no `claude -p` call."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_DATA": self.tmp})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_detects_unsummarized_past_dates_and_skips_today(self):
        data_root = os.path.join(self.tmp, "data")
        os.makedirs(os.path.join(data_root, "2026-08-27"))
        os.makedirs(os.path.join(data_root, "2026-08-28"))
        today = datetime.date.today().isoformat()
        os.makedirs(os.path.join(data_root, today))

        self.assertEqual(check_and_summarize.find_unsummarized_dates(), ["2026-08-27", "2026-08-28"])

    def test_already_summarized_date_is_excluded(self):
        data_root = os.path.join(self.tmp, "data")
        os.makedirs(os.path.join(data_root, "2026-08-27"))
        os.makedirs(os.path.join(self.tmp, "notes"))
        with open(os.path.join(self.tmp, "notes", "2026-08-27.md"), "w", encoding="utf-8") as fh:
            fh.write("already done")

        self.assertEqual(check_and_summarize.find_unsummarized_dates(), [])

    def test_stale_lock_is_overridden(self):
        with open(os.path.join(self.tmp, ".lock"), "w", encoding="utf-8") as fh:
            json.dump({"pid": 999999, "started_at": 0}, fh)  # epoch -- ancient, must be treated as stale
        self.assertTrue(check_and_summarize.acquire_lock())

    def test_fresh_lock_blocks_a_second_instance(self):
        self.assertTrue(check_and_summarize.acquire_lock())
        self.assertFalse(check_and_summarize.acquire_lock())
        check_and_summarize.release_lock()
        self.assertTrue(check_and_summarize.acquire_lock())


if __name__ == "__main__":
    unittest.main()
