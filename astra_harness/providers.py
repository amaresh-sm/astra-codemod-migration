"""Provider-specific command builders for candidate generation."""

from __future__ import annotations

import shlex
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderCommand:
    """A command and the credential variables it may receive."""

    command: str
    credential_env: tuple[str, ...]


def build_provider_command(provider: str, model: str, reasoning: str) -> ProviderCommand:
    """Translate the common provider request into a CLI command."""
    model_arg = shlex.quote(model)
    if provider == "codex":
        return ProviderCommand(
            f"codex exec --json --color never --ephemeral --ignore-user-config --ignore-rules "
            f"--skip-git-repo-check --dangerously-bypass-approvals-and-sandbox --cd /workspace "
            f"-m {model_arg} -c model_reasoning_effort={shlex.quote(reasoning)} -",
            ("CODEX_API_KEY", "OPENAI_API_KEY"),
        )
    if provider == "openai-compatible":
        return ProviderCommand(
            f"codex exec --json --color never --ephemeral --ignore-user-config --ignore-rules "
            f"--skip-git-repo-check --dangerously-bypass-approvals-and-sandbox --cd /workspace "
            f"-m {model_arg} -c model_reasoning_effort={shlex.quote(reasoning)} -",
            ("OPENAI_API_KEY", "OPENAI_BASE_URL", "PORTKEY_API_KEY"),
        )
    if provider == "claude-code":
        return ProviderCommand(
            f"claude -p --model {model_arg} --effort {shlex.quote(reasoning)} "
            "--dangerously-skip-permissions --output-format stream-json --verbose",
            ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"),
        )
    if provider == "openhands":
        # Use the reusable HackerRank/OpenHands package.  It owns the SDK
        # setup, Gateway compatibility fixes, response capture, and complete
        # telemetry/trajectory artifacts.
        return ProviderCommand(
            "hackerrank-openhands run "
            f"--workspace /workspace --instruction /workspace/INSTRUCTION.md "
            f"--model {model_arg} --reasoning {shlex.quote(reasoning)} "
            "--output /output --redact",
            ("ASTRA_GATEWAY_API_KEY", "ASTRA_GATEWAY_BASE_URL", "LLM_API_KEY", "LLM_BASE_URL"),
        )
    raise ValueError("provider must be codex, openai-compatible, claude-code, or openhands")
