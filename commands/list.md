---
description: List worklog dates, most recent 14 by default
argument-hint: "[--all]"
allowed-tools: Bash(python3:*)
---

Run the command below and show its output to the user as-is. If it mentions more dates exist, you don't need to repeat that -- the message already tells the user how to see them.

!`python3 "${CLAUDE_PLUGIN_ROOT}/hooks/cli.py" list $ARGUMENTS`
