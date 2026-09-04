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


class RecursionGuardEndToEndTest(TempDataDir):
    """Strengthens RecursionGuardTest: that one only proves the hooks exit
    early when WORKLOG_INTERNAL is pre-set by the test itself. This exercises
    the real path -- a fake `claude` binary standing in for `claude -p`,
    which itself tries to re-fire the Stop hook the way a child Claude Code
    session's own hooks would if it reloaded this plugin (docs 23.1). If the
    WORKLOG_INTERNAL env var claude_invoke.py sets ever stopped propagating,
    this is what would actually catch it: the nested on_stop.py call would
    capture real data instead of no-op'ing."""

    def _write_pending_session(self, date, session_id):
        record = {
            "schema_version": 2,
            "uuid": "u1",
            "parentUuid": None,
            "date": date,
            "session_id": session_id,
            "project": "my-app",
            "project_path": "/tmp/does-not-need-to-exist",
            "git_branch": "main",
            "timestamp": "%sT10:00:00+09:00" % date,
            "type": "prompt",
            "content": "fix the bug",
        }
        date_dir = os.path.join(self.tmp, "data", date)
        os.makedirs(date_dir, exist_ok=True)
        with open(os.path.join(date_dir, "%s.jsonl" % session_id), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _write_fake_claude(self, bin_dir, calls_log, nested_transcript, nested_session_id):
        script_path = os.path.join(bin_dir, "claude")
        body = (
            "#!/usr/bin/env python3\n"
            "import json, subprocess, sys\n"
            "with open(%r, 'a', encoding='utf-8') as fh:\n"
            "    fh.write('call\\n')\n"
            "prompt = sys.stdin.read()\n"
            "# Simulate a child Claude Code session reloading this plugin's own hooks --\n"
            "# this must inherit WORKLOG_INTERNAL from our own environment unchanged.\n"
            "payload = json.dumps({'session_id': %r, 'transcript_path': %r})\n"
            "subprocess.run([%r, %r], input=payload, capture_output=True, text=True)\n"
            "if 'raw material captured from one Claude Code work session' in prompt:\n"
            "    result = json.dumps({'title': 'Fixed the bug', 'questions_asked': [], 'plans': [],\n"
            "        'problems': [], 'decisions': [], 'files_changed': [], 'tags': [], 'data_gaps': []})\n"
            "else:\n"
            "    result = '## my-app -- Fixed the bug\\n- did the thing\\n'\n"
            "print(json.dumps({'type': 'result', 'is_error': False, 'result': result}))\n"
        ) % (calls_log, nested_session_id, nested_transcript, sys.executable, ON_STOP)
        with open(script_path, "w", encoding="utf-8") as fh:
            fh.write(body)
        os.chmod(script_path, 0o755)

    def test_child_claude_process_cannot_recapture_via_its_own_hooks(self):
        self._write_pending_session("2026-08-27", "sess-1")

        bin_dir = os.path.join(self.tmp, "bin")
        os.makedirs(bin_dir)
        calls_log = os.path.join(self.tmp, "claude_calls.log")

        nested_transcript = os.path.join(self.tmp, "nested_transcript.jsonl")
        with open(nested_transcript, "w", encoding="utf-8") as fh:
            fh.write(
                '{"type": "user", "uuid": "n1", "parentUuid": null, '
                '"timestamp": "2026-08-27T12:00:00+09:00", "cwd": "/tmp/my-app", '
                '"message": {"content": "a prompt from inside the child session"}}\n'
            )
        nested_session_id = "nested-child-session"
        self._write_fake_claude(bin_dir, calls_log, nested_transcript, nested_session_id)

        overrides = self.data_env()
        overrides["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
        proc = run_hook(CHECK_AND_SUMMARIZE, {}, overrides)
        self.assertEqual(proc.returncode, 0, proc.stderr)

        with open(calls_log, encoding="utf-8") as fh:
            call_count = len(fh.readlines())
        self.assertEqual(call_count, 2)  # one map call, one reduce call -- not more

        self.assertTrue(os.path.exists(os.path.join(self.tmp, "notes", "2026-08-27.md")))

        # the nested on_stop.py invocation must not have captured anything --
        # WORKLOG_INTERNAL, inherited unchanged from claude_invoke.py's env,
        # must have short-circuited it before it ever touched the data dir.
        for date_name in os.listdir(os.path.join(self.tmp, "data")):
            nested_path = os.path.join(self.tmp, "data", date_name, "%s.jsonl" % nested_session_id)
            self.assertFalse(os.path.exists(nested_path))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, ".cursors", "%s.json" % nested_session_id)))


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

    def test_shrunk_transcript_recovers_instead_of_stalling_forever(self):
        """If the transcript file ever becomes smaller than the stored cursor
        (truncated/recreated for any reason), the old cursor is stale. Without
        a reset, seeking to it lands past EOF and capture silently never
        advances again for that session id."""
        transcript_path = os.path.join(self.tmp, "live_session.jsonl")
        shutil.copy(os.path.join(FIXTURES, "normal_session.jsonl"), transcript_path)

        payload = {"session_id": "sess-live", "transcript_path": transcript_path}
        proc = run_hook(ON_STOP, payload, self.data_env())
        self.assertEqual(proc.returncode, 0, proc.stderr)

        cursor_path = os.path.join(self.tmp, ".cursors", "sess-live.json")
        with open(cursor_path, encoding="utf-8") as fh:
            cursor_before = json.load(fh)["last_byte_offset"]
        self.assertGreater(cursor_before, 0)

        # simulate the transcript shrinking below the stored cursor, then
        # gaining fresh (different) content
        new_line = (
            '{"type": "user", "uuid": "u-new", "parentUuid": null, '
            '"timestamp": "2026-08-29T11:00:00+09:00", "cwd": "/tmp/my-app", '
            '"message": {"content": "a brand new prompt after the shrink"}}\n'
        )
        with open(transcript_path, "w", encoding="utf-8") as fh:
            fh.write(new_line)
        self.assertLess(os.path.getsize(transcript_path), cursor_before)

        proc = run_hook(ON_STOP, payload, self.data_env())
        self.assertEqual(proc.returncode, 0, proc.stderr)

        records = self._read_captured("2026-08-29", "sess-live")
        prompts = [r["content"] for r in records if r["type"] == "prompt"]
        self.assertIn("a brand new prompt after the shrink", prompts)

        with open(cursor_path, encoding="utf-8") as fh:
            cursor_after = json.load(fh)["last_byte_offset"]
        self.assertEqual(cursor_after, os.path.getsize(transcript_path))


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

    def test_summarized_date_with_newer_session_data_is_reconsidered(self):
        """A session held open across midnight keeps appending to yesterday's
        folder for any turn still timestamped before midnight. If that lands
        after the day was already summarized, the note is now stale."""
        data_root = os.path.join(self.tmp, "data")
        date_dir = os.path.join(data_root, "2026-08-27")
        os.makedirs(date_dir)
        os.makedirs(os.path.join(self.tmp, "notes"))
        note = os.path.join(self.tmp, "notes", "2026-08-27.md")
        with open(note, "w", encoding="utf-8") as fh:
            fh.write("already done")

        # a session appends more data to the same date folder *after* that
        old_mtime = os.path.getmtime(note)
        session_file = os.path.join(date_dir, "sess-late.jsonl")
        with open(session_file, "w", encoding="utf-8") as fh:
            fh.write('{"type": "prompt"}\n')
        os.utime(session_file, (old_mtime + 10, old_mtime + 10))

        self.assertEqual(check_and_summarize.find_unsummarized_dates(), ["2026-08-27"])

    def test_summarized_date_with_only_older_session_data_stays_excluded(self):
        data_root = os.path.join(self.tmp, "data")
        date_dir = os.path.join(data_root, "2026-08-27")
        os.makedirs(date_dir)
        session_file = os.path.join(date_dir, "sess-early.jsonl")
        with open(session_file, "w", encoding="utf-8") as fh:
            fh.write('{"type": "prompt"}\n')

        os.makedirs(os.path.join(self.tmp, "notes"))
        note = os.path.join(self.tmp, "notes", "2026-08-27.md")
        with open(note, "w", encoding="utf-8") as fh:
            fh.write("already done")
        new_mtime = os.path.getmtime(session_file) + 10
        os.utime(note, (new_mtime, new_mtime))

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
