"""Runs `claude -p` for summarization, in one of two modes (docs 23.2, 23.3, 24.1).

Subscription mode (default): no --bare, reuses the user's existing login.
Isolated mode: --bare + the anthropic_api_key userConfig value, used only
when that option is set. Both modes set WORKLOG_INTERNAL=1 so the child
session's own hooks short-circuit instead of recursing (docs 23.1), and
both disable all tools so a prompt injection in the raw material can at
worst poison the written summary, never trigger a real action (docs 22.7).
"""

import json
import os
import re
import subprocess

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


class ClaudeInvokeError(Exception):
    pass


def _isolated_mode_api_key():
    return os.environ.get("CLAUDE_PLUGIN_OPTION_ANTHROPIC_API_KEY") or None


def _configured_model():
    return os.environ.get("CLAUDE_PLUGIN_OPTION_SUMMARY_MODEL") or None


def build_command(model=None):
    cmd = ["claude", "-p", "--allowedTools", "", "--max-turns", "1", "--output-format", "json"]
    api_key = _isolated_mode_api_key()
    if api_key:
        cmd.append("--bare")
    resolved_model = model or _configured_model()
    if resolved_model:
        cmd.extend(["--model", resolved_model])
    return cmd, api_key


def invoke_claude(prompt_text, model=None, timeout=300):
    """Runs one headless summarization turn and returns the model's raw text response."""
    cmd, api_key = build_command(model=model)
    env = dict(os.environ)
    env["WORKLOG_INTERNAL"] = "1"
    if api_key:
        env["ANTHROPIC_API_KEY"] = api_key

    try:
        proc = subprocess.run(
            cmd, input=prompt_text, capture_output=True, text=True, env=env, timeout=timeout
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ClaudeInvokeError("failed to run claude -p: %r" % (exc,))

    if proc.returncode != 0:
        raise ClaudeInvokeError("claude -p exited %d: %s" % (proc.returncode, proc.stderr[:2000]))

    try:
        envelope = json.loads(proc.stdout)
    except ValueError as exc:
        raise ClaudeInvokeError("could not parse claude -p output as JSON: %r" % (exc,))

    if not isinstance(envelope, dict):
        raise ClaudeInvokeError("unexpected claude -p output shape: %r" % (envelope,))

    if envelope.get("is_error"):
        raise ClaudeInvokeError("claude -p reported an error: %s" % envelope.get("result"))

    return envelope.get("result", "")


def strip_code_fence(text):
    """The model sometimes wraps JSON answers in ```json ... ``` even when told not to."""
    text = (text or "").strip()
    match = _CODE_FENCE_RE.match(text)
    return match.group(1) if match else text
