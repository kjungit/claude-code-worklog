"""Tests for CLAUDE_PLUGIN_DATA resolution (docs 24.2), including the fallback
added after a real install showed that neither CLAUDE_PLUGIN_DATA nor
CLAUDE_PLUGIN_ROOT are actually set as environment variables for a slash
command's bash step (only for hook processes) -- ${CLAUDE_PLUGIN_ROOT} there
is apparently just text-substituted into the command line.

Run with: python3 tests/test_paths.py
"""

import importlib.util
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "hooks", "lib"))

import paths  # noqa: E402


def load_paths_module_from(plugin_root):
    """Copies paths.py into <plugin_root>/hooks/lib/ and imports it fresh from
    there, so its __file__ reflects a real plugin install layout."""
    lib_dir = os.path.join(plugin_root, "hooks", "lib")
    os.makedirs(lib_dir, exist_ok=True)
    dest = os.path.join(lib_dir, "paths.py")
    shutil.copyfile(os.path.join(REPO_ROOT, "hooks", "lib", "paths.py"), dest)
    spec = importlib.util.spec_from_file_location("paths_under_test", dest)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DataDirResolutionTest(unittest.TestCase):
    def test_uses_env_var_directly_when_set(self):
        with mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_DATA": "/tmp/explicit-data-dir"}):
            self.assertEqual(paths.data_dir(), "/tmp/explicit-data-dir")

    def test_derives_from_plugin_root_when_data_unset(self):
        env = {
            "CLAUDE_PLUGIN_ROOT": "/Users/x/.claude/plugins/cache/claude-code-worklog/worklog/1.0.1",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("CLAUDE_PLUGIN_DATA", None)
            result = paths.data_dir()
        self.assertEqual(result, os.path.expanduser("~/.claude/plugins/data/worklog-claude-code-worklog"))

    def test_env_var_takes_priority_over_derived_root(self):
        env = {
            "CLAUDE_PLUGIN_DATA": "/tmp/explicit-wins",
            "CLAUDE_PLUGIN_ROOT": "/Users/x/.claude/plugins/cache/some-marketplace/worklog/2.0.0",
        }
        with mock.patch.dict(os.environ, env):
            self.assertEqual(paths.data_dir(), "/tmp/explicit-wins")

    def test_unrecognized_root_shape_falls_through_to_last_resort(self):
        env = {"CLAUDE_PLUGIN_ROOT": "/some/other/layout/worklog"}
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("CLAUDE_PLUGIN_DATA", None)
            result = paths.data_dir()
        self.assertEqual(result, os.path.expanduser("~/.claude/plugins/data/worklog"))

    def test_nothing_set_falls_through_to_last_resort(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CLAUDE_PLUGIN_DATA", None)
            os.environ.pop("CLAUDE_PLUGIN_ROOT", None)
            result = paths.data_dir()
        self.assertEqual(result, os.path.expanduser("~/.claude/plugins/data/worklog"))


class FileLocationDerivationTest(unittest.TestCase):
    """The scenario actually observed on a real install: a slash command's
    bash step gets no relevant env vars at all, so data_dir() must still find
    the right place purely from where this file is physically installed."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="worklog-plugin-layout-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_derives_correct_dir_with_zero_env_vars(self):
        plugin_root = os.path.join(self.tmp, "cache", "claude-code-worklog", "worklog", "1.0.3")
        module = load_paths_module_from(plugin_root)

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CLAUDE_PLUGIN_DATA", None)
            os.environ.pop("CLAUDE_PLUGIN_ROOT", None)
            result = module.data_dir()

        self.assertEqual(result, os.path.expanduser("~/.claude/plugins/data/worklog-claude-code-worklog"))

    def test_env_var_still_wins_over_file_location(self):
        plugin_root = os.path.join(self.tmp, "cache", "claude-code-worklog", "worklog", "1.0.3")
        module = load_paths_module_from(plugin_root)

        with mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_DATA": "/tmp/explicit-wins"}):
            self.assertEqual(module.data_dir(), "/tmp/explicit-wins")

    def test_non_cache_layout_falls_through_to_last_resort(self):
        # e.g. running straight from a dev checkout, not an installed plugin cache
        plugin_root = os.path.join(self.tmp, "some-dev-checkout")
        module = load_paths_module_from(plugin_root)

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CLAUDE_PLUGIN_DATA", None)
            os.environ.pop("CLAUDE_PLUGIN_ROOT", None)
            result = module.data_dir()

        self.assertEqual(result, os.path.expanduser("~/.claude/plugins/data/worklog"))


if __name__ == "__main__":
    unittest.main()
