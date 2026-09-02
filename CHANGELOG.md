# Changelog

Versions are semver (`plugin.json`'s `version`), independent of `schema_version` (the data record format, currently `2`). A migration note is called out explicitly whenever a release changes `schema_version` in a way that isn't purely additive.

## 1.0.4

Migration needed: no.

- Fixed a real gap found while dogfooding: once `notes/{date}.md` existed, that date was permanently treated as done, even if a session held open across midnight kept appending more turns (still timestamped before midnight) to that same date's folder afterward. `find_unsummarized_dates()` now also re-flags a date if any of its session `.jsonl` files are newer than its `notes/{date}.md`, the same mtime-based invalidation already used for the per-session summary cache. Already-cached session summaries aren't redone -- only the date's Reduce step reruns to fold in the new session

## 1.0.3

Migration needed: no.

- The 1.0.2 fix wasn't enough: verified against the real install that a slash command's bash step gets neither `CLAUDE_PLUGIN_DATA` nor `CLAUDE_PLUGIN_ROOT` as actual environment variables (only hook processes get them) -- `${CLAUDE_PLUGIN_ROOT}` in a command file is apparently just text-substituted into the invoked command line, not exported into the subprocess environment. `data_dir()` now also derives the plugin's cache path from `paths.py`'s own file location as a further fallback, which needs no environment variable at all. Confirmed against the real install with a completely empty environment
- `/worklog:doctor` now reports both `CLAUDE_PLUGIN_DATA` and `CLAUDE_PLUGIN_ROOT` raw env state

## 1.0.2

Migration needed: no.

- Fixed a real bug found on first install: `CLAUDE_PLUGIN_DATA` is set for hook processes (`on_stop.py`, `check_and_summarize.py`) but was not set for a slash command's bash step, so `/worklog:doctor`, `/worklog:show`, and `/worklog:search` were silently reading from the wrong directory (a plugin-name-only fallback) while capture was correctly writing to `~/.claude/plugins/data/<plugin>-<marketplace>/`. `data_dir()` now derives that same path from `CLAUDE_PLUGIN_ROOT` (`.../cache/<marketplace>/<plugin>/<version>`) when `CLAUDE_PLUGIN_DATA` isn't set, before falling back further
- `/worklog:doctor` now reports the raw `CLAUDE_PLUGIN_DATA` env var state so this class of mismatch is visible instead of silent

## 1.0.1

Migration needed: no.

- Renamed command files (`worklog.md` -> `show.md`, `worklog-search.md` -> `search.md`, etc.) so the plugin-namespaced invocation reads as `/worklog:show`, `/worklog:search`, `/worklog:archive`, `/worklog:debug`, `/worklog:doctor` instead of the redundant `/worklog:worklog-doctor` style. Confirmed against a real install that Claude Code always namespaces plugin commands as `<plugin>:<command-file>` -- the flat `/worklog-doctor` names in the 1.0.0 docs never actually worked, so this is a documentation/naming correction, not a behavior change for existing users

## 1.0.0

Initial release. Migration needed: no (nothing to migrate from).

- Automatic capture via a Stop hook, with a crash-safe byte-offset cursor and no LLM calls on the hot path
- Background Map-Reduce summarization on session start, producing `notes/{date}.md`
- DAG-aware capture: rewound/abandoned attempts are kept out of the "completed work" narrative
- Reentry guard preventing the summarization subprocess from recursing into its own hooks
- Dual summarization modes: subscription (default) and isolated (`--bare` + your own API key)
- Prompt-injection defenses: tools disabled during summarization, raw material passed as clearly-delimited data
- SQLite FTS5 search index, rebuildable at any time from the underlying summary files
- `/worklog:show`, `/worklog:search`, `/worklog:archive`, `/worklog:debug`, `/worklog:doctor`, and the `worklog-query` skill
- Archiving compresses old raw logs into `archive/*.tar.gz`; there is no delete path anywhere in the plugin
