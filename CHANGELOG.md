# Changelog

Versions are semver (`plugin.json`'s `version`), independent of `schema_version` (the data record format, currently `2`). A migration note is called out explicitly whenever a release changes `schema_version` in a way that isn't purely additive.

## 1.0.0

Initial release. Migration needed: no (nothing to migrate from).

- Automatic capture via a Stop hook, with a crash-safe byte-offset cursor and no LLM calls on the hot path
- Background Map-Reduce summarization on session start, producing `notes/{date}.md`
- DAG-aware capture: rewound/abandoned attempts are kept out of the "completed work" narrative
- Reentry guard preventing the summarization subprocess from recursing into its own hooks
- Dual summarization modes: subscription (default) and isolated (`--bare` + your own API key)
- Prompt-injection defenses: tools disabled during summarization, raw material passed as clearly-delimited data
- SQLite FTS5 search index, rebuildable at any time from the underlying summary files
- `/worklog`, `/worklog-search`, `/worklog-archive`, `/worklog-debug`, `/worklog-doctor`, and the `worklog-query` skill
- Archiving compresses old raw logs into `archive/*.tar.gz`; there is no delete path anywhere in the plugin
