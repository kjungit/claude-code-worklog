"""Crash-safe file helpers (docs 4.1 safeguard 4).

Only uses `os` and `json`, so it stays safe to import from on_stop.py.
"""

import json
import os


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, ValueError):
        return default


def write_json_atomic(path, data):
    """Write via a temp file + os.replace so a crash mid-write never leaves a corrupt file."""
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    tmp_path = "%s.tmp-%d" % (path, os.getpid())
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp_path, path)


def append_lines(path, lines):
    """Append raw text lines to a file, creating parent directories as needed.

    Data is appended before any cursor is advanced by the caller -- append
    first, commit position second (at-least-once, never data loss).
    """
    if not lines:
        return
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        for line in lines:
            fh.write(line)
            fh.write("\n")
