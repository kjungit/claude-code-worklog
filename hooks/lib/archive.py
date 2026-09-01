"""Compresses old raw session logs into archive/{date}.tar.gz (docs 12.2).

Deliberately has no delete path at all -- not "delete after archiving",
not even behind a flag. The originals under data/ are left exactly as
they are; this only adds a compact copy under archive/. See docs section
14 (least-privilege): "no code path with permission to delete originals
should exist in the first place."
"""

import datetime
import os
import tarfile

from paths import data_dir

DEFAULT_ARCHIVE_AFTER_DAYS = 180


def _configured_days():
    raw = os.environ.get("CLAUDE_PLUGIN_OPTION_ARCHIVE_AFTER_DAYS")
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return DEFAULT_ARCHIVE_AFTER_DAYS


def archive_older_than(days=None):
    """Returns the list of date folders newly archived."""
    days = days if days is not None else _configured_days()
    root = os.path.join(data_dir(), "data")
    if not os.path.isdir(root):
        return []

    cutoff = datetime.date.today() - datetime.timedelta(days=days)
    archive_root = os.path.join(data_dir(), "archive")
    archived = []

    for name in sorted(os.listdir(root)):
        date_dir = os.path.join(root, name)
        if not os.path.isdir(date_dir):
            continue
        try:
            folder_date = datetime.date.fromisoformat(name)
        except ValueError:
            continue
        if folder_date >= cutoff:
            continue

        tar_path = os.path.join(archive_root, "%s.tar.gz" % name)
        if os.path.exists(tar_path):
            continue

        os.makedirs(archive_root, exist_ok=True)
        with tarfile.open(tar_path, "w:gz") as tar:
            tar.add(date_dir, arcname=name)
        archived.append(name)

    return archived
