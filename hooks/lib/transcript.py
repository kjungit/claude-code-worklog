"""Parsing and DAG chain reconstruction for Claude Code session transcripts.

Only depends on `json` and `re` so it stays safe to import from on_stop.py,
which must not pull in heavier modules (see docs section 16.1).
"""

import json
import re
from datetime import datetime

SCHEMA_VERSION = 2

# Line types we ever turn into worklog raw material. Everything else
# (hook attachments, mode/permission/system bookkeeping lines, etc.) is
# dropped by design -- an unknown type should be lost, never leaked in
# as noise (docs section 22.2, 23.5).
CAPTURED_LINE_TYPES = ("user", "assistant")

FILE_TOOL_NAMES = ("Write", "Edit", "MultiEdit")

_SECRET_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    re.compile(r"gh[opsu]_[a-zA-Z0-9]{36}"),
    re.compile(r"xox[baprs]-[a-zA-Z0-9-]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
]


def redact_secrets(text):
    """Replace anything that looks like a credential with [REDACTED].

    Applied only to our own copy of the data, never to the original
    transcript file (docs section 20.2). Not a complete scanner -- just
    a best-effort net.
    """
    if not text:
        return text
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def parse_jsonl_lines(raw_lines):
    """Defensively parse raw jsonl text lines into dicts.

    A line that fails to parse is skipped rather than raising, so one
    corrupted line never takes down the whole capture (docs section 4.1,
    safeguard 3).
    """
    for raw in raw_lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            yield json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue


def _as_blocks(content):
    """Normalize a message's `content` field to a list of content blocks."""
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


def _extract_text_blocks(content):
    """Concatenate any plain-text blocks in `content` (or content itself if it's already a string)."""
    if isinstance(content, str):
        return content
    parts = [b.get("text", "") for b in _as_blocks(content) if b.get("type") == "text"]
    return "\n".join(p for p in parts if p)


def _block_text(block_content):
    """tool_result content can itself be a string or a list of blocks."""
    if isinstance(block_content, str):
        return block_content
    return _extract_text_blocks(block_content)


def _local_date(timestamp, tz=None):
    """Convert a raw (typically UTC, `Z`-suffixed) transcript timestamp into the
    calendar date it falls on in `tz` (system-local timezone when `tz` is None).

    Naive string-slicing here would take the UTC date, not the date the user
    actually experienced -- work done in the first few hours after local
    midnight would silently land in the previous day's worklog (docs 4.1).
    """
    if not timestamp:
        return None
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return timestamp[:10] or None  # malformed timestamp -- fall back rather than raise
    return dt.astimezone(tz).date().isoformat()


def _base_record(obj, record_type, content, files_changed=None, usage=None, tz=None):
    session_id = obj.get("sessionId") or obj.get("session_id")
    cwd = obj.get("cwd")
    timestamp = obj.get("timestamp")
    record = {
        "schema_version": SCHEMA_VERSION,
        "uuid": obj.get("uuid"),
        "parentUuid": obj.get("parentUuid"),
        "date": _local_date(timestamp, tz),
        "session_id": session_id,
        "project": cwd.rstrip("/").rsplit("/", 1)[-1] if cwd else None,
        "project_path": cwd,
        "git_branch": obj.get("gitBranch"),
        "timestamp": timestamp,
        "type": record_type,
        "content": redact_secrets(content),
    }
    if files_changed:
        record["files_changed"] = files_changed
    if usage:
        record["usage"] = usage
    return record


def classify_and_extract(obj, tz=None):
    """Turn one parsed transcript line into zero or more capture records.

    Only `user` prompts, `assistant` plans (ExitPlanMode) and file
    changes (Write/Edit/MultiEdit), tool-result errors, and
    compact_boundary markers are extracted -- everything else (raw
    assistant prose, hook attachments, bookkeeping line types) is
    intentionally left out of the raw material (docs section 4.1, 22.2).

    `tz` is passed through to `_local_date` for each record's `date` field
    (None means system-local timezone; tests pin a fixed tz for determinism).
    """
    line_type = obj.get("type")

    if line_type == "system" and obj.get("subtype") == "compact_boundary":
        return [_base_record(obj, "compact_boundary", "", tz=tz)]

    if line_type not in CAPTURED_LINE_TYPES:
        return []

    if obj.get("isSidechain"):
        return []

    message = obj.get("message") or {}
    content = message.get("content")
    records = []

    if line_type == "user":
        for block in _as_blocks(content):
            if block.get("type") == "tool_result" and block.get("is_error"):
                records.append(_base_record(obj, "error", _block_text(block.get("content")), tz=tz))
        prompt_text = _extract_text_blocks(content)
        if prompt_text and prompt_text.strip():
            # empty when content was tool_result-only (no plain text blocks) -- correctly not a prompt
            records.append(_base_record(obj, "prompt", prompt_text.strip(), tz=tz))

    elif line_type == "assistant":
        usage = message.get("usage")
        for block in _as_blocks(content):
            if block.get("type") != "tool_use":
                continue
            name = block.get("name")
            tool_input = block.get("input") or {}
            if name == "ExitPlanMode":
                records.append(_base_record(obj, "plan", tool_input.get("plan", ""), usage=usage, tz=tz))
            elif name in FILE_TOOL_NAMES:
                file_path = tool_input.get("file_path")
                records.append(
                    _base_record(
                        obj,
                        "file_change",
                        name,
                        files_changed=[file_path] if file_path else [],
                        usage=usage,
                        tz=tz,
                    )
                )

    return records


def reconstruct_live_chain(records):
    """Split a single session's records into the surviving branch vs. abandoned attempts.

    Session transcripts are a DAG, not a timeline: rewinds/forks/retries
    leave dead branches permanently in the file. We walk back from the
    most recent leaf via parentUuid to find what's actually live
    (docs section 22.1, 23.4).

    Records without a uuid (can't be placed in the graph) and records
    whose parentUuid points outside this record set (e.g. the parent
    was captured before this plugin was installed) are kept as live --
    when unsure, include rather than drop (docs section 23.4).
    """
    by_uuid = {r["uuid"]: r for r in records if r.get("uuid")}
    if not by_uuid:
        return list(records), []

    parent_ids = {r.get("parentUuid") for r in records if r.get("parentUuid")}
    leaf_uuids = [u for u in by_uuid if u not in parent_ids]
    if not leaf_uuids:
        return list(records), []

    leaf_uuids.sort(key=lambda u: by_uuid[u].get("timestamp") or "")
    latest_leaf = leaf_uuids[-1]

    live_ids = set()
    cur = latest_leaf
    seen = set()
    while cur and cur not in seen:
        seen.add(cur)
        live_ids.add(cur)
        node = by_uuid.get(cur)
        if not node:
            break
        cur = node.get("parentUuid")

    live_records = [r for r in records if not r.get("uuid") or r["uuid"] in live_ids]
    abandoned_records = [r for r in records if r.get("uuid") and r["uuid"] not in live_ids]

    abandoned_attempts = [
        {
            "attempt": r.get("content") or r.get("type"),
            "why_abandoned": "superseded by a later rewind/retry",
            "date": r.get("date"),
            "project": r.get("project"),
        }
        for r in abandoned_records
        if r.get("type") in ("prompt", "plan", "file_change")
    ]

    return live_records, abandoned_attempts
