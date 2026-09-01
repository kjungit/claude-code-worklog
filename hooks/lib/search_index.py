"""Lightweight SQLite FTS5 search index over session summaries (docs 12.3, 16.2).

index.sqlite is derived data, never a primary source -- it can be deleted
and rebuilt from *.summary.json at any time. WAL + busy_timeout + BEGIN
IMMEDIATE + retry covers multiple terminals writing at once.
"""

import json
import os
import sqlite3
import time

from paths import data_dir

RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY = 0.2


def _index_path():
    return os.path.join(data_dir(), "index.sqlite")


def _connect():
    os.makedirs(data_dir(), exist_ok=True)
    conn = sqlite3.connect(_index_path(), timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _ensure_schema(conn):
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS summaries USING fts5("
        "date UNINDEXED, project UNINDEXED, session_id UNINDEXED, title, body"
        ")"
    )


def _with_retry(fn):
    delay = RETRY_BASE_DELAY
    last_exc = None
    for _ in range(RETRY_ATTEMPTS):
        try:
            return fn()
        except sqlite3.OperationalError as exc:
            last_exc = exc
            time.sleep(delay)
            delay *= 2
    raise last_exc


def _searchable_body(summary):
    parts = [summary.get("title") or ""]
    parts.extend(summary.get("questions_asked") or [])
    parts.extend(summary.get("tags") or [])
    for p in summary.get("problems") or []:
        parts.append("%s %s" % (p.get("problem", ""), p.get("solution", "")))
    for d in summary.get("decisions") or []:
        parts.append("%s %s" % (d.get("decision", ""), d.get("reason", "")))
    for a in summary.get("abandoned_attempts") or []:
        parts.append(a.get("attempt", "") if isinstance(a, dict) else str(a))
    return "\n".join(p for p in parts if p)


def upsert_summary(date, session_id, summary):
    def _do():
        conn = _connect()
        try:
            _ensure_schema(conn)
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM summaries WHERE date = ? AND session_id = ?", (date, session_id))
            conn.execute(
                "INSERT INTO summaries (date, project, session_id, title, body) VALUES (?, ?, ?, ?, ?)",
                (date, summary.get("project") or "", session_id, summary.get("title") or "", _searchable_body(summary)),
            )
            conn.commit()
        finally:
            conn.close()

    _with_retry(_do)


def search(query, limit=10):
    def _do():
        conn = _connect()
        try:
            _ensure_schema(conn)
            cur = conn.execute(
                "SELECT date, project, title, snippet(summaries, 4, '[', ']', '...', 12) "
                "FROM summaries WHERE summaries MATCH ? ORDER BY date DESC LIMIT ?",
                (query, limit),
            )
            return [
                {"date": row[0], "project": row[1], "title": row[2], "snippet": row[3]}
                for row in cur.fetchall()
            ]
        finally:
            conn.close()

    return _with_retry(_do)


def rebuild():
    """Deletes and rebuilds the index from every data/*/*.summary.json on disk. Returns the count indexed."""
    path = _index_path()
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(path + suffix)
        except OSError:
            pass

    root = os.path.join(data_dir(), "data")
    count = 0
    if not os.path.isdir(root):
        return count

    for date_name in sorted(os.listdir(root)):
        date_dir = os.path.join(root, date_name)
        if not os.path.isdir(date_dir):
            continue
        for name in os.listdir(date_dir):
            if not name.endswith(".summary.json"):
                continue
            session_id = name[: -len(".summary.json")]
            try:
                with open(os.path.join(date_dir, name), encoding="utf-8") as fh:
                    summary = json.load(fh)
            except (OSError, ValueError):
                continue
            upsert_summary(date_name, session_id, summary)
            count += 1
    return count
