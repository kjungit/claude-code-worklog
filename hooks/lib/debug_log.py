"""Debug logging for hook failures (docs 17.3).

Exceptions in a hook must never surface to the user or change the exit
code -- they go here instead, silently. Rotated to the most recent
MAX_LINES lines so it never grows unbounded; /worklog:debug reads the tail.
"""

import os
import time

from paths import debug_log_path

MAX_LINES = 1000


def log(message):
    try:
        path = debug_log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("[%s] %s\n" % (timestamp, message))
        _rotate(path)
    except OSError:
        pass  # logging must never be the reason a hook fails


def _rotate(path):
    with open(path, encoding="utf-8") as fh:
        lines = fh.readlines()
    if len(lines) > MAX_LINES:
        with open(path, "w", encoding="utf-8") as fh:
            fh.writelines(lines[-MAX_LINES:])


def tail(n=50):
    path = debug_log_path()
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        lines = fh.readlines()
    return lines[-n:]
