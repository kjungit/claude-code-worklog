"""Path resolution shared by both hooks.

Only uses `os`, so it stays safe to import from on_stop.py (docs 16.1).
"""

import os

_FALLBACK_DATA_DIR = os.path.expanduser("~/.claude/plugins/data/worklog")


def data_dir():
    """${CLAUDE_PLUGIN_DATA}, with a fallback for the intermittent-unset bug (docs 24.2)."""
    return os.environ.get("CLAUDE_PLUGIN_DATA") or _FALLBACK_DATA_DIR


def cursors_dir():
    return os.path.join(data_dir(), ".cursors")


def cursor_path(session_id):
    return os.path.join(cursors_dir(), "%s.json" % session_id)


def raw_session_dir(date_str):
    return os.path.join(data_dir(), "data", date_str)


def raw_session_path(date_str, session_id):
    return os.path.join(raw_session_dir(date_str), "%s.jsonl" % session_id)


def notes_dir():
    """Honors the notes_path userConfig option when set (docs 24.1)."""
    override = os.environ.get("CLAUDE_PLUGIN_OPTION_NOTES_PATH")
    if override:
        return override
    return os.path.join(data_dir(), "notes")


def note_path(date_str):
    return os.path.join(notes_dir(), "%s.md" % date_str)


def debug_log_path():
    return os.path.join(data_dir(), ".debug.log")


def lock_path():
    return os.path.join(data_dir(), ".lock")
