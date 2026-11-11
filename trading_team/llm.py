"""LLM access. Agents depend on the small `LLM` protocol so tests can use a fake."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from typing import Protocol


class LLMFormatError(ValueError):
    """Raised when a model reply does not contain the JSON object we asked for."""


class LLM(Protocol):
    def complete(self, system: str, user: str, max_tokens: int = 1200) -> str: ...


class AnthropicLLM:
    """Calls the Anthropic Messages API. Reads ANTHROPIC_API_KEY from the environment."""

    def __init__(self, model: str, client=None):
        if client is None:
            import anthropic
            client = anthropic.Anthropic()
        self.model = model
        self._client = client

    def complete(self, system: str, user: str, max_tokens: int = 1200) -> str:
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(
            block.text for block in resp.content if getattr(block, "type", "") == "text")


class ClaudeCLILLM:
    """Runs each agent through the Claude Code CLI (`claude -p`), which uses the
    logged-in Claude subscription. No API key and no separate bill; calls count
    against the subscription's usage limits."""

    def __init__(self, model: str | None = None, timeout: int = 300):
        if shutil.which("claude") is None:
            raise RuntimeError("the `claude` command was not found on this machine")
        self.model = model
        self.timeout = timeout
        self._cwd = tempfile.mkdtemp(prefix="trading_team_")  # no project files

    def complete(self, system: str, user: str, max_tokens: int = 1200) -> str:
        cmd = ["claude", "-p", "--system-prompt", system, "--max-turns", "1"]
        if self.model:
            cmd += ["--model", self.model]
        last = ""
        for _ in range(2):  # one retry on a failed or empty reply
            proc = subprocess.run(cmd, input=user, capture_output=True, text=True,
                                  timeout=self.timeout, cwd=self._cwd)
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout
            last = (proc.stderr or proc.stdout).strip()[:300]
        raise RuntimeError(f"claude CLI call failed: {last}")


def parse_json_object(text: str) -> dict:
    """Extracts the first top-level JSON object from a model reply."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise LLMFormatError("no JSON object in reply")
    try:
        obj = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise LLMFormatError(str(exc)) from exc
    if not isinstance(obj, dict):
        raise LLMFormatError("JSON root is not an object")
    return obj
