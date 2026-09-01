#!/usr/bin/env python3
"""Sanity-checks plugin.json's version before a release (docs 19.1, 19.2).

- plugin.json's version must be valid semver.
- If marketplace.json's plugin entry ever gains its own "version" field
  (some marketplace schemas pin one, some just point at the plugin
  directory and always read its current plugin.json), it must match
  plugin.json's -- so this stays correct either way instead of assuming
  a field that may not exist.

Run manually before tagging a release: python3 scripts/check_version.py
"""

import json
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main():
    plugin = load(os.path.join(REPO_ROOT, ".claude-plugin", "plugin.json"))
    version = plugin.get("version", "")
    if not SEMVER_RE.match(version):
        print("plugin.json version %r is not valid semver (expected X.Y.Z)" % version)
        return 1

    marketplace = load(os.path.join(REPO_ROOT, ".claude-plugin", "marketplace.json"))
    mismatches = []
    for entry in marketplace.get("plugins", []):
        entry_version = entry.get("version")
        if entry_version and entry_version != version:
            mismatches.append((entry.get("name"), entry_version))

    if mismatches:
        for name, entry_version in mismatches:
            print("marketplace.json entry %r has version %r, plugin.json has %r" % (name, entry_version, version))
        return 1

    print("OK: plugin.json version %s" % version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
