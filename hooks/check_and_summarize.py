#!/usr/bin/env python3
import os
import sys

# Same reentry guard as on_stop.py, and for the same reason (docs 23.1):
# `claude -p` calls made by the summarization pipeline reload this hook
# in the child session, which must do nothing at all.
if os.environ.get("WORKLOG_INTERNAL"):
    sys.exit(0)

import datetime  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import debug_log  # noqa: E402
from paths import data_dir, lock_path, note_path  # noqa: E402

STALE_LOCK_SECONDS = 30 * 60


def today_str():
    return datetime.date.today().isoformat()


def _is_up_to_date(date_name, date_dir):
    """A date counts as done only if notes/{date}.md exists AND is at least as
    new as every session file in that date's folder. A session that stays
    open across midnight keeps appending to yesterday's folder for any turn
    still timestamped before midnight (docs 23.4) -- if one of those turns
    lands after the day was already summarized, the note is now stale and
    needs to be regenerated, the same way a session's own *.summary.json
    cache is invalidated by a newer jsonl (see summarize._cache_valid).
    """
    note = note_path(date_name)
    if not os.path.exists(note):
        return False
    note_mtime = os.path.getmtime(note)
    for name in os.listdir(date_dir):
        if not name.endswith(".jsonl"):
            continue
        session_path = os.path.join(date_dir, name)
        try:
            if os.path.getmtime(session_path) > note_mtime:
                return False
        except OSError:
            continue
    return True


def find_unsummarized_dates():
    """Date folders under data/ that are missing a notes/{date}.md, or whose
    notes/{date}.md is now stale relative to new session data. Today is
    excluded -- it's still in progress.
    """
    root = os.path.join(data_dir(), "data")
    if not os.path.isdir(root):
        return []
    today = today_str()
    dates = []
    for name in sorted(os.listdir(root)):
        if name == today:
            continue
        date_dir = os.path.join(root, name)
        if not os.path.isdir(date_dir):
            continue
        if not _is_up_to_date(name, date_dir):
            dates.append(name)
    return dates


def acquire_lock():
    """A second SessionStart in another terminal must not summarize the same day twice."""
    path = lock_path()
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                info = json.load(fh)
            age = time.time() - info.get("started_at", 0)
            if age < STALE_LOCK_SECONDS:
                return False
        except (ValueError, OSError):
            pass  # unreadable lock -- treat it as stale and take over
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"pid": os.getpid(), "started_at": time.time()}, fh)
    return True


def release_lock():
    try:
        os.remove(lock_path())
    except OSError:
        pass


def run_summarization(dates):
    """Runs Map/Reduce for each pending date. A date that fails is simply left
    unsummarized -- it will be picked up again on the next SessionStart
    (docs 4.2 step 4), and any sessions that already succeeded stay cached.
    """
    from summarize import summarize_date

    for date in dates:
        try:
            summarize_date(date)
        except Exception as exc:  # one bad date must not stop the rest
            debug_log.log("worklog: summarizing %s raised: %r" % (date, exc))


def main():
    try:
        json.load(sys.stdin)
    except (ValueError, OSError):
        pass

    try:
        dates = find_unsummarized_dates()
        if dates and acquire_lock():
            try:
                run_summarization(dates)
            finally:
                release_lock()
    except Exception as exc:  # a detection failure must never block session start
        debug_log.log("check_and_summarize.py failed: %r" % (exc,))

    sys.exit(0)


if __name__ == "__main__":
    main()
