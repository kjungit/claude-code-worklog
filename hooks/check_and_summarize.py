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


def find_unsummarized_dates():
    """Date folders under data/ that have no notes/{date}.md yet. Today is excluded -- it's still in progress."""
    root = os.path.join(data_dir(), "data")
    if not os.path.isdir(root):
        return []
    today = today_str()
    dates = []
    for name in sorted(os.listdir(root)):
        if name == today:
            continue
        if not os.path.isdir(os.path.join(root, name)):
            continue
        if not os.path.exists(note_path(name)):
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
    """Detection + locking lands here; the Map/Reduce pipeline itself is a follow-up change.

    For now this just records what's waiting, so the plumbing (hook
    registration, lock, reentry guard) can be exercised end to end before
    the `claude -p` calls exist.
    """
    for date in dates:
        debug_log.log("worklog: %s is unsummarized (summarization pipeline not yet implemented)" % date)


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
