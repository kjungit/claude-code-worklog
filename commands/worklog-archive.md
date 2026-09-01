---
description: Gzip-compress raw session logs older than N days into archive/ (never deletes or modifies originals)
argument-hint: "[days, default 180]"
allowed-tools: Bash(python3:*)
---

Run the command below and report the result to the user in one or two sentences. Make it clear that this only writes a compressed copy under archive/ -- it never deletes or touches anything under data/.

!`python3 "${CLAUDE_PLUGIN_ROOT}/hooks/cli.py" archive $ARGUMENTS`
