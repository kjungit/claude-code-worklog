# claude-code-worklog

Automatically captures what you do in Claude Code and turns it into a daily worklog, without you having to ask for it.

Every turn is captured silently by a hook (no LLM call, no cost). Once a day has passed, the next time you start a session it gets summarized in the background into a plain markdown file. Ask for it whenever you want with `/worklog:show`.

## Install

```
/plugin marketplace add kjungit/claude-code-worklog
/plugin install worklog@claude-code-worklog
```

You'll be asked for a few optional settings on install (see [Configuration](#configuration) below) -- all of them can be left blank.

## Commands

Plugin commands are namespaced as `/<plugin-name>:<command>`, so these show up as:

| Command | What it does |
|---|---|
| `/worklog:show [date] [--now]` | Show a day's worklog (today by default). Pass `--now` to force an immediate summary of that date instead of waiting for the next session start |
| `/worklog:search <keyword>` | Full-text search across every past worklog entry |
| `/worklog:archive [days]` | Gzip-compress raw session logs older than N days into `archive/` (default 180 days). Never deletes anything |
| `/worklog:debug` | Show recent plugin errors |
| `/worklog:doctor` | Check that the plugin is set up correctly: data directory, pending summaries, recent errors |

Ask naturally, too -- "what did I work on last week", "compare Tuesday and Thursday", "find that redirect URI bug" -- the `worklog-query` skill handles anything beyond a single day.

## What this plugin touches

| Component | Reads | Writes | Runs |
|---|---|---|---|
| Stop hook (`on_stop.py`) | The current session's own transcript file only | `${CLAUDE_PLUGIN_DATA}/data/`, `.cursors/` | nothing external |
| SessionStart hook (`check_and_summarize.py`) | `${CLAUDE_PLUGIN_DATA}/data/` | `notes/`, `*.summary.json`, `index.sqlite` | `claude -p` (headless), `git log` (in the project directory only) |
| `worklog-query` skill | `${CLAUDE_PLUGIN_DATA}` (read-only) | nothing | nothing |
| `/worklog:archive` | `data/{date}/` | `archive/*.tar.gz` only | nothing |

Principles this is built around:
- **No code path can delete your raw logs.** Archiving only ever compresses a copy into `archive/`; there is no delete function anywhere in this plugin.
- **git commands never leave the current project directory.**
- **This plugin stores no credentials of its own.** See [Credentials](#credentials) below.

## Dual summarization modes

Summarization runs `claude -p` in one of two modes:

- **Subscription mode (default)** -- reuses your existing Claude Code login. No extra setup, no separate billing. The child process reloads this same plugin's hooks, so a reentry guard (`WORKLOG_INTERNAL=1`) makes sure it does nothing rather than recursing.
- **Isolated mode** -- used automatically if you set the `anthropic_api_key` option (see below). Runs with `--bare`, which skips loading your CLAUDE.md, MCP servers, and any other plugins/hooks entirely. Slower to set up (needs its own API key, billed separately) but fully isolated from anything else in your environment. Recommended if you frequently work in repositories you don't fully trust, since a prompt injection hidden in a file or commit message can then only ever affect the written summary text, never anything else in your setup.

In both modes, all tools are disabled during summarization (`--allowedTools ""`) -- a successful prompt injection in the raw material can at worst make a summary say something wrong, never take a real action.

## Configuration

All of these are optional and can be set (or changed) via `/plugin` after install:

| Option | Default | Effect |
|---|---|---|
| `notes_path` | `${CLAUDE_PLUGIN_DATA}/notes` | Where daily worklog `.md` files are written. Point this at an Obsidian vault to keep them there instead |
| `archive_after_days` | `180` | How old a day's raw logs need to be before `/worklog:archive` will compress them |
| `anthropic_api_key` | (unset) | If set, switches summarization to isolated mode. Stored in your OS keychain, never in a plain file |
| `summary_model` | (unset, uses your default model) | Model used for the two `claude -p` summarization calls |

## Credentials

This plugin does not store any credentials of its own by default. It reuses your existing Claude Code login for summarization, and your existing git/GitHub authentication for commit lookups. The one exception is the optional `anthropic_api_key` setting above, which -- if you choose to set it -- is stored in your OS keychain (not a plain file) and used only for isolated-mode summarization calls.

## Known limitations

- Raw session transcripts are a DAG, not a strict timeline -- rewinding to try a different approach leaves the abandoned attempt in the file forever. This plugin reconstructs the live branch and keeps abandoned attempts in a separate `abandoned_attempts` field rather than reporting them as completed work, but this depends on `uuid`/`parentUuid` being present and consistent in your Claude Code version.
- Prompt injection defenses (disabled tools, data/instruction separation in the summarization prompt) reduce but don't eliminate the risk of a hostile file or commit message influencing summary *text*. Isolated mode narrows this further by not loading MCP servers at all. If a summary says something that looks out of place, check the original session.
- Two terminals writing to the search index at the same moment are handled with SQLite's WAL mode and retries, but very heavy concurrent write load (many terminals finishing sessions at once) hasn't been load-tested.
- `Ctrl+C` twice suspends a session rather than ending it, so `SessionEnd` never fires for it -- this plugin doesn't rely on `SessionEnd` at all, so it isn't affected, but it's worth knowing if you're debugging hook behavior yourself.

## Development

Run the test suite with `python3 -m unittest discover -s tests`.
