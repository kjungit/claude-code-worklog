"""Path resolution shared by both hooks and the CLI (docs 16.1, 24.2).

Only uses `os`, so it stays safe to import from on_stop.py (docs 16.1).
"""

import os

_LAST_RESORT_DATA_DIR = os.path.expanduser("~/.claude/plugins/data/worklog")


def _data_dir_from_plugin_root(root):
    """CLAUDE_PLUGIN_ROOT (when available) looks like
    .../cache/<marketplace>/<plugin>/<version>, and the hook-assigned data
    directory observed on disk was ~/.claude/plugins/data/<plugin>-<marketplace>
    -- so reconstruct that instead of guessing a plugin-name-only path.
    """
    if not root:
        return None
    parts = os.path.normpath(root).split(os.sep)
    if len(parts) < 4 or parts[-4] != "cache":
        return None
    marketplace, plugin = parts[-3], parts[-2]
    return os.path.expanduser("~/.claude/plugins/data/%s-%s" % (plugin, marketplace))


def _plugin_root_from_file_location():
    """This file lives at <plugin_root>/hooks/lib/paths.py. Verified against a
    real install: a slash command's bash step gets neither CLAUDE_PLUGIN_DATA
    nor CLAUDE_PLUGIN_ROOT as actual environment variables (only hook
    processes do) -- ${CLAUDE_PLUGIN_ROOT} is apparently just text-substituted
    into the command line used to launch the script. This derivation needs no
    env var at all, since it only depends on where this file physically is.
    """
    hooks_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../<plugin_root>/hooks
    return os.path.dirname(hooks_dir)  # .../<plugin_root>


def data_dir():
    """${CLAUDE_PLUGIN_DATA}, then a path derived from ${CLAUDE_PLUGIN_ROOT} if
    that's set, then the same derivation from this file's own location (which
    works even with no relevant env vars at all), then a hardcoded guess.
    """
    return (
        os.environ.get("CLAUDE_PLUGIN_DATA")
        or _data_dir_from_plugin_root(os.environ.get("CLAUDE_PLUGIN_ROOT"))
        or _data_dir_from_plugin_root(_plugin_root_from_file_location())
        or _LAST_RESORT_DATA_DIR
    )


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
