"""Standalone parser tests -- no Claude Code, no hooks registered.

Run with: python3 tests/test_parser.py
(matches docs/claude-code-worklog-design.md section 25.1, stage 1)
"""

import os
import sys
import unittest
from datetime import timedelta, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "hooks", "lib"))
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")

import transcript  # noqa: E402

# Fixtures embed +09:00-offset timestamps. Date derivation now converts to a
# timezone (system-local in production), so tests pin a fixed tz instead of
# depending on whichever machine happens to run them.
FIXED_TZ = timezone(timedelta(hours=9))


def load_fixture(name):
    path = os.path.join(FIXTURES, name)
    with open(path, encoding="utf-8") as fh:
        return list(fh)


def records_for(name, tz=FIXED_TZ):
    out = []
    for obj in transcript.parse_jsonl_lines(load_fixture(name)):
        out.extend(transcript.classify_and_extract(obj, tz=tz))
    return out


class CorruptedLinesTest(unittest.TestCase):
    def test_broken_line_is_skipped_not_fatal(self):
        records = records_for("corrupted_lines.jsonl")
        types = [r["type"] for r in records]
        # the prompt, the file_change, and the error should all still come through
        self.assertIn("prompt", types)
        self.assertIn("file_change", types)
        self.assertIn("error", types)


class WhitelistTest(unittest.TestCase):
    def test_unwhitelisted_types_produce_nothing(self):
        raw_objs = list(transcript.parse_jsonl_lines(load_fixture("noise_types.jsonl")))
        noise_types = {
            "mode", "permission-mode", "atis-latch", "bridge-session",
            "file-history-snapshot", "ai-title", "attachment", "last-prompt",
        }
        for obj in raw_objs:
            if obj.get("type") in noise_types:
                self.assertEqual(transcript.classify_and_extract(obj), [])

    def test_whitelisted_lines_still_extracted_among_noise(self):
        records = records_for("noise_types.jsonl")
        types = [r["type"] for r in records]
        self.assertIn("prompt", types)
        self.assertIn("plan", types)


class ClassificationTest(unittest.TestCase):
    def setUp(self):
        self.records = records_for("normal_session.jsonl")
        self.by_type = {}
        for r in self.records:
            self.by_type.setdefault(r["type"], []).append(r)

    def test_prompt_extracted(self):
        self.assertEqual(len(self.by_type.get("prompt", [])), 1)
        self.assertEqual(self.by_type["prompt"][0]["content"], "add a login button")

    def test_file_change_extracted_with_path(self):
        changes = self.by_type.get("file_change", [])
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["files_changed"], ["src/LoginButton.tsx"])

    def test_successful_tool_result_is_not_an_error(self):
        self.assertNotIn("error", self.by_type)

    def test_metadata_preserved(self):
        r = self.by_type["prompt"][0]
        self.assertEqual(r["session_id"], "sess-normal")
        self.assertEqual(r["project"], "my-app")
        self.assertEqual(r["git_branch"], "main")
        self.assertEqual(r["schema_version"], transcript.SCHEMA_VERSION)
        self.assertEqual(r["uuid"], "uuid-1")


class SecretRedactionTest(unittest.TestCase):
    def test_aws_key_redacted(self):
        text = "tried AKIAABCDEFGHIJKLMNOP and it didn't work"
        self.assertNotIn("AKIA", transcript.redact_secrets(text))
        self.assertIn("[REDACTED]", transcript.redact_secrets(text))

    def test_generic_api_key_redacted(self):
        text = "API_KEY=sk-abcdefghijklmnopqrstuvwxyz"
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz", transcript.redact_secrets(text))

    def test_private_key_block_redacted(self):
        text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow==\n-----END RSA PRIVATE KEY-----"
        result = transcript.redact_secrets(text)
        self.assertNotIn("MIIEow==", result)

    def test_plain_text_untouched(self):
        text = "just a normal prompt about login buttons"
        self.assertEqual(transcript.redact_secrets(text), text)


class DagReconstructionTest(unittest.TestCase):
    def test_dead_branch_moved_to_abandoned(self):
        records = records_for("rewind_session.jsonl")
        live, abandoned = transcript.reconstruct_live_chain(records)

        abandoned_texts = [a["attempt"] for a in abandoned]

        self.assertEqual(len(live), 2)  # prompt + the surviving file_change
        self.assertEqual(len(abandoned), 1)
        self.assertEqual(abandoned_texts[0], "Write")
        # the surviving branch is the later one (approach B / uuid r3), not r2
        self.assertTrue(all(r["uuid"] != "r2" for r in live))

    def test_linear_chain_all_live(self):
        records = records_for("normal_session.jsonl")
        live, abandoned = transcript.reconstruct_live_chain(records)
        self.assertEqual(len(live), len(records))
        self.assertEqual(abandoned, [])

    def test_missing_uuid_kept_as_live(self):
        records = [{"type": "prompt", "content": "x", "uuid": None, "parentUuid": None}]
        live, abandoned = transcript.reconstruct_live_chain(records)
        self.assertEqual(live, records)
        self.assertEqual(abandoned, [])

    def test_crosses_midnight_without_breaking_chain(self):
        records = records_for("midnight_session.jsonl")
        live, abandoned = transcript.reconstruct_live_chain(records)
        self.assertEqual(len(live), 2)
        self.assertEqual(abandoned, [])
        dates = {r["date"] for r in live}
        self.assertEqual(dates, {"2026-08-29", "2026-08-30"})


class TimezoneTest(unittest.TestCase):
    def _prompt_obj(self, timestamp):
        return {
            "type": "user",
            "uuid": "u1",
            "parentUuid": None,
            "timestamp": timestamp,
            "cwd": "/tmp/my-app",
            "message": {"content": "hi"},
        }

    def test_utc_timestamp_converted_to_local_date_not_sliced(self):
        # 23:30 UTC on 8/30 is 08:30 KST on 8/31 -- a naive [:10] slice would
        # wrongly keep it on 8/30.
        obj = self._prompt_obj("2026-08-30T23:30:00Z")
        records = transcript.classify_and_extract(obj, tz=FIXED_TZ)
        self.assertEqual(records[0]["date"], "2026-08-31")

    def test_already_local_offset_timestamp_unchanged(self):
        obj = self._prompt_obj("2026-08-30T10:00:00+09:00")
        records = transcript.classify_and_extract(obj, tz=FIXED_TZ)
        self.assertEqual(records[0]["date"], "2026-08-30")

    def test_malformed_timestamp_falls_back_without_raising(self):
        obj = self._prompt_obj("not-a-timestamp")
        records = transcript.classify_and_extract(obj, tz=FIXED_TZ)
        self.assertEqual(records[0]["date"], "not-a-time")  # defensive fallback, docs 4.1 safeguard 3

    def test_missing_timestamp_is_none(self):
        obj = self._prompt_obj(None)
        records = transcript.classify_and_extract(obj, tz=FIXED_TZ)
        self.assertIsNone(records[0]["date"])


if __name__ == "__main__":
    unittest.main()
