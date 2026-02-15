"""Windows-specific patches for Claude Agent SDK subprocess transport.

Patch 1 — .CMD bypass:
On Windows, the Claude Code CLI is installed as a `.CMD` batch file wrapper
(e.g., `claude.CMD`). When Python's `subprocess` module runs a `.CMD` file,
it routes through `cmd.exe /c`, which incorrectly interprets newlines and
special characters (|, &, <, >) inside `--system-prompt` arguments as
command separators — breaking the CLI invocation.

This module patches `SubprocessCLITransport._build_command` to replace the
`.CMD` wrapper with a direct `node.exe cli.js` invocation, bypassing
`cmd.exe` argument parsing entirely.

Patch 2 — API credentials:
When running inside a Claude Code editor session, the environment contains
a local-proxy `ANTHROPIC_API_KEY` and `ANTHROPIC_BASE_URL` that only work
for the parent process. The SDK subprocess inherits these but cannot use
them. This patch overrides them with the real Azure Foundry credentials
from the `.env` file (`AZURE_FOUNDRY_API_KEY` / `AZURE_FOUNDRY_ENDPOINT`).

The Claude Code CLI also requires Foundry-specific env vars for Azure
authentication: `CLAUDE_CODE_USE_FOUNDRY=true`,
`ANTHROPIC_FOUNDRY_API_KEY`, and `ANTHROPIC_FOUNDRY_BASE_URL`.

Both patches are safe to apply on all platforms — they only activate when
the relevant conditions are detected.
"""

import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

_PATCHED = False


def apply() -> None:
    """Apply all SDK patches (idempotent)."""
    global _PATCHED
    if _PATCHED:
        return

    _patch_api_credentials()
    _patch_windows_cmd()
    _PATCHED = True


def _patch_api_credentials() -> None:
    """Override local-proxy API credentials with real ones from .env."""
    api_key = os.environ.get("AZURE_FOUNDRY_API_KEY", "")
    base_url = os.environ.get("AZURE_FOUNDRY_ENDPOINT", "")
    model = os.environ.get("CLAUDE_MODEL", "")

    if not api_key:
        return

    os.environ["ANTHROPIC_API_KEY"] = api_key
    logger.info("Set ANTHROPIC_API_KEY from AZURE_FOUNDRY_API_KEY")

    if base_url:
        clean_url = base_url.rstrip("/")
        os.environ["ANTHROPIC_BASE_URL"] = clean_url
        logger.info("Set ANTHROPIC_BASE_URL from AZURE_FOUNDRY_ENDPOINT")

    if model:
        # ClaudeAgentSettings loads model from CLAUDE_AGENT_MODEL env var
        os.environ["CLAUDE_AGENT_MODEL"] = model
        logger.info("Set CLAUDE_AGENT_MODEL=%s from CLAUDE_MODEL", model)

    # Claude Code CLI requires Foundry-specific env vars for Azure auth
    os.environ["CLAUDE_CODE_USE_FOUNDRY"] = "true"
    os.environ["ANTHROPIC_FOUNDRY_API_KEY"] = api_key
    if base_url:
        os.environ["ANTHROPIC_FOUNDRY_BASE_URL"] = base_url.rstrip("/")
    logger.info("Set CLAUDE_CODE_USE_FOUNDRY=true + Foundry credentials")


def _patch_windows_cmd() -> None:
    """Replace .CMD wrapper with direct node.exe + cli.js invocation."""
    if os.name != "nt":
        return

    from claude_agent_sdk._internal.transport.subprocess_cli import (
        SubprocessCLITransport,
    )

    node_exe = shutil.which("node")
    if not node_exe:
        logger.warning("node.exe not found on PATH; skipping Windows CLI patch")
        return

    claude_cmd = shutil.which("claude")
    if not claude_cmd or not claude_cmd.lower().endswith(".cmd"):
        return

    npm_prefix = Path(claude_cmd).parent
    cli_js = npm_prefix / "node_modules" / "@anthropic-ai" / "claude-code" / "cli.js"

    if not cli_js.exists():
        logger.warning("cli.js not found at %s; skipping Windows CLI patch", cli_js)
        return

    node_exe_str = str(node_exe)
    cli_js_str = str(cli_js)

    _orig_build = SubprocessCLITransport._build_command

    def _patched_build_command(self: SubprocessCLITransport) -> list[str]:
        cmd = _orig_build(self)
        if cmd and cmd[0].lower().endswith(".cmd"):
            cmd = [node_exe_str, cli_js_str] + cmd[1:]
        return cmd

    SubprocessCLITransport._build_command = _patched_build_command  # type: ignore[assignment]
    logger.info(
        "Applied Windows CLI patch: %s %s (bypassing .CMD wrapper)",
        node_exe_str,
        cli_js_str,
    )
