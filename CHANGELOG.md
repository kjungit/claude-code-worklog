# Changelog

Versions are semver (`plugin.json`'s `version`), independent of `schema_version` (the data record format, currently `2`). A migration note is called out explicitly whenever a release changes `schema_version` in a way that isn't purely additive.

## 1.0.8

Migration needed: no.

- Summaries were always written in English regardless of the language a session was actually conducted in, because the Map/Reduce prompts gave no language instruction at all. Both prompts now ask the model to write in whichever language predominantly appears in the material (the user's own captured prompts, mainly) instead of defaulting to English. `tags` are deliberately kept in English/lowercase/kebab-case regardless, so tag-based search and grouping stays consistent across days written in different languages

## 1.0.7

Migration needed: no.

- Added `/worklog:list` to show which dates have a worklog at a glance (most recent 14 by default, `--all` for full history), so you don't have to guess a date for `/worklog:show` or reach for `/worklog:search` just to see what's there. When more dates exist than are shown, the output points to `--all` or `/worklog:search` to find them

## 1.0.6

Migration needed: no.

- Fixed a real timezone bug found in review: a record's `date` was derived by naively slicing the first 10 characters of Claude Code's raw (UTC) timestamp, never converting to local time, contrary to docs 4.1's "local-timezone-based date" rule. Work done in the first few hours after local midnight was silently filed under the previous day. Now converts properly via `datetime.astimezone()` (system-local timezone by default). Code-only fix -- already-captured data on disk keeps whatever date it was originally filed under, nothing is migrated
- Fixed a real capture stall found in review: if a session's transcript file ever became smaller than the stored byte-offset cursor (truncated/recreated for any reason), `read_new_lines()` would seek past EOF, read nothing, and never advance the cursor -- capture for that session id was silently and permanently stuck. The cursor now resets to 0 when the file has shrunk below it
- Strengthened `RecursionGuardTest`, which previously only proved the hooks exit early when `WORKLOG_INTERNAL` is pre-set by the test itself, with an end-to-end test using a fake `claude` binary that itself tries to re-fire the Stop hook the way a child Claude Code session's own hooks would -- verifying the real env var propagation path, not just the short-circuit given the var is already set
- Documented how to run the test suite in the README

## 1.0.5

Migration needed: no.

- Added `--now` to `/worklog:show` to force an immediate summary of a date (today by default) instead of waiting for the next `SessionStart`. `SessionEnd` was considered as an automatic trigger for this instead, but was rejected again for the same reason it was rejected for capture (docs `claude-code-worklog-design.md` §2, §10): it doesn't fire on `Ctrl+C`-twice suspends or long-lived sessions, so it can't be relied on. `--now` reuses the existing staleness-aware `summarize_date()` and the existing summarization lock, so it's safe to run even while a background pass from another terminal is in flight

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
