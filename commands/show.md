---
description: Show a day's captured worklog (today by default)
argument-hint: "[YYYY-MM-DD] [--now]"
allowed-tools: Bash(python3:*)
---

Run the command below and show its output to the user as-is -- it's already formatted as the worklog entry. Add at most one short sentence of your own only if the output says no worklog exists yet for that date. Pass `--now` to force an immediate summary of that date (today by default) instead of waiting for the next session start.

!`python3 "${CLAUDE_PLUGIN_ROOT}/hooks/cli.py" show $ARGUMENTS`
