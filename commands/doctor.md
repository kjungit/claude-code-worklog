---
description: Check whether the worklog plugin is set up correctly (data directory, pending summaries, recent errors)
allowed-tools: Bash(python3:*)
---

Run the command below and present its report to the user. If it surfaces a problem, suggest the most relevant next step (for example, pointing to /worklog:debug for more detail on a recent error).

!`python3 "${CLAUDE_PLUGIN_ROOT}/hooks/cli.py" doctor`
