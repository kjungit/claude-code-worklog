#!/usr/bin/env python3
import os
import sys

# Reentry guard first, before any other import: a summarization call spawns
# a child `claude -p` session that reloads this same hook. Without this the
# child's own turns would recapture themselves into the worklog (docs 23.1).
if os.environ.get("WORKLOG_INTERNAL"):
    sys.exit(0)

import json  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from atomic import append_lines, read_json, write_json_atomic  # noqa: E402
from paths import cursor_path, raw_session_path  # noqa: E402
from transcript import classify_and_extract, parse_jsonl_lines  # noqa: E402

try:
    import debug_log
except Exception:
    debug_log = None


def _log(message):
    if debug_log is not None:
        debug_log.log(message)


def read_new_lines(transcript_path, offset):
    """Read only complete lines added since `offset`.

    A trailing partial line (transcript_path is written asynchronously --
    docs 4.1 safeguard 2) is left unconsumed; it will be picked up whole
    on the next Stop hook once it's finished being written.
    """
    with open(transcript_path, "rb") as fh:
        fh.seek(offset)
        chunk = fh.read()
    last_newline = chunk.rfind(b"\n")
    if last_newline == -1:
        return [], offset
    complete = chunk[: last_newline + 1]
    new_offset = offset + len(complete)
    lines = complete.decode("utf-8", errors="replace").splitlines()
    return lines, new_offset


def capture(session_id, transcript_path):
    cursor = read_json(cursor_path(session_id), default={"last_byte_offset": 0})
    offset = cursor.get("last_byte_offset", 0)

    raw_lines, new_offset = read_new_lines(transcript_path, offset)
    if not raw_lines:
        return

    by_date = {}
    for obj in parse_jsonl_lines(raw_lines):
        for record in classify_and_extract(obj):
            date = record.get("date") or "unknown-date"
            by_date.setdefault(date, []).append(json.dumps(record, ensure_ascii=False))

    for date, json_lines in by_date.items():
        append_lines(raw_session_path(date, session_id), json_lines)

    # Cursor only advances after the data is safely on disk (docs safeguard 4).
    write_json_atomic(cursor_path(session_id), {"last_byte_offset": new_offset})


def main():
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        payload = {}

    session_id = payload.get("session_id")
    transcript_path = payload.get("transcript_path")

    try:
        if session_id and transcript_path and os.path.exists(transcript_path):
            capture(session_id, transcript_path)
    except Exception as exc:  # a capture failure must never block the user
        _log("on_stop.py failed: %r" % (exc,))

    print(json.dumps({"suppressOutput": True}))
    sys.exit(0)


if __name__ == "__main__":
    main()
