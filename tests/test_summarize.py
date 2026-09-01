"""Unit tests for the Map-Reduce summarization pipeline.

`claude -p` itself is always mocked here (it's slow, costs money, and
non-deterministic) -- these tests check the plumbing around it: caching,
retry-then-give-up, dual-mode command building, envelope parsing, and
the git commit lookup's fallback behavior.

Run with: python3 tests/test_summarize.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "hooks", "lib"))

import claude_invoke  # noqa: E402
import git_info  # noqa: E402
import paths  # noqa: E402
import summarize  # noqa: E402


class TempDataDir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="worklog-summarize-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self._env_patch = mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_DATA": self.tmp}, clear=False)
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)

    def write_capture_record(self, date, session_id, record):
        raw_dir = paths.raw_session_dir(date)
        os.makedirs(raw_dir, exist_ok=True)
        path = os.path.join(raw_dir, "%s.jsonl" % session_id)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def prompt_record(session_id, date, project="my-app", uuid_="u1", content="fix the bug"):
    return {
        "schema_version": 2,
        "uuid": uuid_,
        "parentUuid": None,
        "date": date,
        "session_id": session_id,
        "project": project,
        "project_path": "/tmp/does-not-need-to-exist",
        "git_branch": "main",
        "timestamp": "%sT10:00:00+09:00" % date,
        "type": "prompt",
        "content": content,
    }


VALID_MAP_JSON = json.dumps(
    {
        "title": "Fixed the bug",
        "questions_asked": ["fix the bug"],
        "plans": [],
        "problems": [],
        "decisions": [],
        "files_changed": [],
        "tags": ["bugfix"],
        "data_gaps": [],
    }
)


class ParseMapOutputTest(unittest.TestCase):
    def test_strips_code_fence(self):
        fenced = "```json\n%s\n```" % VALID_MAP_JSON
        parsed = summarize.parse_map_output(fenced)
        self.assertEqual(parsed["title"], "Fixed the bug")

    def test_missing_keys_filled_with_defaults(self):
        parsed = summarize.parse_map_output('{"title": "x"}')
        for key in summarize.REQUIRED_MAP_KEYS:
            self.assertIn(key, parsed)

    def test_non_object_raises(self):
        with self.assertRaises(ValueError):
            summarize.parse_map_output("[1, 2, 3]")


class SummarizeSessionCacheTest(TempDataDir):
    def test_uses_cache_without_calling_claude(self):
        self.write_capture_record("2026-08-29", "sess-1", prompt_record("sess-1", "2026-08-29"))
        summary_path = os.path.join(paths.raw_session_dir("2026-08-29"), "sess-1.summary.json")
        with open(summary_path, "w", encoding="utf-8") as fh:
            json.dump({"title": "cached"}, fh)
        # make sure the cache is newer than the jsonl
        os.utime(summary_path, None)

        with mock.patch("summarize.invoke_claude", side_effect=AssertionError("should not be called")):
            result = summarize.summarize_session("2026-08-29", "sess-1")
        self.assertEqual(result["title"], "cached")

    def test_stale_cache_is_regenerated(self):
        self.write_capture_record("2026-08-29", "sess-1", prompt_record("sess-1", "2026-08-29"))
        raw_dir = paths.raw_session_dir("2026-08-29")
        summary_path = os.path.join(raw_dir, "sess-1.summary.json")
        with open(summary_path, "w", encoding="utf-8") as fh:
            json.dump({"title": "stale"}, fh)
        old_time = os.path.getmtime(summary_path) - 3600
        os.utime(summary_path, (old_time, old_time))  # older than the jsonl

        with mock.patch("summarize.invoke_claude", return_value=VALID_MAP_JSON):
            result = summarize.summarize_session("2026-08-29", "sess-1")
        self.assertEqual(result["title"], "Fixed the bug")


class SummarizeSessionMapTest(TempDataDir):
    def test_successful_map_writes_cache_with_metrics_and_commits(self):
        self.write_capture_record("2026-08-29", "sess-1", prompt_record("sess-1", "2026-08-29"))

        with mock.patch("summarize.invoke_claude", return_value=VALID_MAP_JSON), mock.patch(
            "summarize.get_commits_for_date", return_value=(["abc123 fix bug"], [])
        ):
            result = summarize.summarize_session("2026-08-29", "sess-1")

        self.assertEqual(result["project"], "my-app")
        self.assertEqual(result["git_commits"], ["abc123 fix bug"])
        self.assertIn("metrics", result)

        cache_path = os.path.join(paths.raw_session_dir("2026-08-29"), "sess-1.summary.json")
        self.assertTrue(os.path.exists(cache_path))

    def test_git_gap_is_folded_into_data_gaps(self):
        self.write_capture_record("2026-08-29", "sess-1", prompt_record("sess-1", "2026-08-29"))
        with mock.patch("summarize.invoke_claude", return_value=VALID_MAP_JSON), mock.patch(
            "summarize.get_commits_for_date", return_value=([], ["git 저장소 아님 — 커밋 이력 확인 불가"])
        ):
            result = summarize.summarize_session("2026-08-29", "sess-1")
        self.assertIn("git 저장소 아님 — 커밋 이력 확인 불가", result["data_gaps"])

    def test_no_live_records_for_date_returns_none(self):
        # nothing captured for this date at all
        result = summarize.summarize_session("2026-08-29", "sess-missing")
        self.assertIsNone(result)

    def test_retries_once_then_gives_up_on_bad_json(self):
        self.write_capture_record("2026-08-29", "sess-1", prompt_record("sess-1", "2026-08-29"))
        with mock.patch("summarize.invoke_claude", return_value="not json at all") as invoke:
            result = summarize.summarize_session("2026-08-29", "sess-1")
        self.assertIsNone(result)
        self.assertEqual(invoke.call_count, 2)  # one try, one retry, then give up


class SummarizeDateTest(TempDataDir):
    def test_all_sessions_succeed_writes_notes_with_frontmatter(self):
        self.write_capture_record("2026-08-29", "sess-1", prompt_record("sess-1", "2026-08-29"))
        self.write_capture_record("2026-08-29", "sess-2", prompt_record("sess-2", "2026-08-29", project="other-app"))

        def fake_invoke(prompt, *args, **kwargs):
            if "raw material captured from one Claude Code work session" in prompt:
                return VALID_MAP_JSON
            return "## my-app -- Fixed the bug\n- did the thing\n"

        with mock.patch("summarize.invoke_claude", side_effect=fake_invoke), mock.patch(
            "summarize.get_commits_for_date", return_value=([], [])
        ):
            written = summarize.summarize_date("2026-08-29")

        self.assertTrue(written)
        with open(paths.note_path("2026-08-29"), encoding="utf-8") as fh:
            content = fh.read()
        self.assertTrue(content.startswith("---\n"))
        self.assertIn("date: 2026-08-29", content)
        self.assertIn("my-app -- Fixed the bug", content)
        self.assertIn("2 sessions", content)

    def test_one_session_failing_leaves_date_pending_but_keeps_other_cache(self):
        self.write_capture_record("2026-08-29", "sess-good", prompt_record("sess-good", "2026-08-29"))
        self.write_capture_record("2026-08-29", "sess-bad", prompt_record("sess-bad", "2026-08-29"))

        def fake_invoke(prompt, *args, **kwargs):
            if "sess-good" in prompt:
                return VALID_MAP_JSON
            return "not json"

        with mock.patch("summarize.invoke_claude", side_effect=fake_invoke), mock.patch(
            "summarize.get_commits_for_date", return_value=([], [])
        ):
            written = summarize.summarize_date("2026-08-29")

        self.assertFalse(written)
        self.assertFalse(os.path.exists(paths.note_path("2026-08-29")))
        good_cache = os.path.join(paths.raw_session_dir("2026-08-29"), "sess-good.summary.json")
        self.assertTrue(os.path.exists(good_cache))  # the one that succeeded doesn't get redone next time

    def test_no_sessions_returns_false(self):
        self.assertFalse(summarize.summarize_date("2026-08-29"))


class ClaudeInvokeCommandTest(unittest.TestCase):
    def test_subscription_mode_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CLAUDE_PLUGIN_OPTION_ANTHROPIC_API_KEY", None)
            cmd, api_key = claude_invoke.build_command()
        self.assertNotIn("--bare", cmd)
        self.assertIsNone(api_key)

    def test_isolated_mode_when_api_key_configured(self):
        with mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_OPTION_ANTHROPIC_API_KEY": "sk-test-key"}):
            cmd, api_key = claude_invoke.build_command()
        self.assertIn("--bare", cmd)
        self.assertEqual(api_key, "sk-test-key")

    def test_model_option_is_appended(self):
        cmd, _ = claude_invoke.build_command(model="claude-haiku-4-5-20251001")
        self.assertIn("--model", cmd)
        self.assertIn("claude-haiku-4-5-20251001", cmd)


class ClaudeInvokeEnvelopeTest(unittest.TestCase):
    def _fake_completed_process(self, stdout, returncode=0):
        return subprocess.CompletedProcess(args=["claude"], returncode=returncode, stdout=stdout, stderr="")

    def test_extracts_result_field(self):
        envelope = json.dumps({"type": "result", "is_error": False, "result": "hello"})
        with mock.patch("claude_invoke.subprocess.run", return_value=self._fake_completed_process(envelope)):
            text = claude_invoke.invoke_claude("prompt")
        self.assertEqual(text, "hello")

    def test_is_error_flag_raises(self):
        envelope = json.dumps({"type": "result", "is_error": True, "result": "boom"})
        with mock.patch("claude_invoke.subprocess.run", return_value=self._fake_completed_process(envelope)):
            with self.assertRaises(claude_invoke.ClaudeInvokeError):
                claude_invoke.invoke_claude("prompt")

    def test_nonzero_exit_raises(self):
        with mock.patch(
            "claude_invoke.subprocess.run",
            return_value=self._fake_completed_process("", returncode=1),
        ):
            with self.assertRaises(claude_invoke.ClaudeInvokeError):
                claude_invoke.invoke_claude("prompt")

    def test_strip_code_fence(self):
        self.assertEqual(claude_invoke.strip_code_fence('```json\n{"a": 1}\n```'), '{"a": 1}')
        self.assertEqual(claude_invoke.strip_code_fence('{"a": 1}'), '{"a": 1}')


class GitInfoTest(unittest.TestCase):
    def test_non_git_directory_reports_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            commits, gaps = git_info.get_commits_for_date(tmp, "2026-08-29")
        self.assertEqual(commits, [])
        self.assertTrue(any("git 저장소 아님" in g for g in gaps))

    def test_real_repo_finds_commit_on_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ)
            env["GIT_AUTHOR_DATE"] = "2026-08-29T12:00:00"
            env["GIT_COMMITTER_DATE"] = "2026-08-29T12:00:00"
            subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
            subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=tmp, check=True)
            subprocess.run(["git", "config", "user.name", "Tester"], cwd=tmp, check=True)
            subprocess.run(
                ["git", "commit", "--allow-empty", "-q", "-m", "did the thing"],
                cwd=tmp,
                env=env,
                check=True,
            )
            commits, gaps = git_info.get_commits_for_date(tmp, "2026-08-29")
        self.assertEqual(gaps, [])
        self.assertTrue(any("did the thing" in c for c in commits))


if __name__ == "__main__":
    unittest.main()
