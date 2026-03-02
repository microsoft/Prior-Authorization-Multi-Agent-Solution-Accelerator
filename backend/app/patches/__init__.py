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

Patch 3 — Model mapping:
Maps `CLAUDE_MODEL` from `.env` to `CLAUDE_AGENT_MODEL` so the SDK uses
the correct model instead of defaulting to claude-sonnet.

Patch 4 — Windows asyncio event loop (ProactorEventLoop):
On Windows, `asyncio.create_subprocess_exec()` only works with
`ProactorEventLoop`. When uvicorn runs with `--reload`, the worker process
may use `SelectorEventLoop` which raises `NotImplementedError` on subprocess
creation. This patch sets `WindowsProactorEventLoopPolicy` before the event
loop is created.

All patches are safe to apply on all platforms — they only activate when
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

    print("[patches] Applying SDK patches...")
    _patch_windows_event_loop()
    _patch_api_credentials()
    _patch_windows_cmd()
    _PATCHED = True
    print("[patches] All patches applied.")


def _patch_windows_event_loop() -> None:
    """Ensure Windows uses ProactorEventLoop for subprocess support.

    On Windows, asyncio.create_subprocess_exec() requires ProactorEventLoop.
    When uvicorn runs with --reload, the worker process may use
    SelectorEventLoop, which raises NotImplementedError when spawning
    subprocesses (needed by the Claude Agent SDK to start the CLI).

    Simply setting the policy is not enough if the event loop was already
    created (e.g., by uvicorn's reload worker). We must also replace the
    running loop if it's a SelectorEventLoop.
    """
    if os.name != "nt":
        return

    import asyncio

    # Step 1: Ensure the policy is ProactorEventLoop
    policy = asyncio.get_event_loop_policy()
    if not isinstance(policy, asyncio.WindowsProactorEventLoopPolicy):
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        print("[patches] Set WindowsProactorEventLoopPolicy (subprocess support)")
    else:
        print("[patches] Windows event loop policy: ProactorEventLoop already set")

    # Step 2: Check if the RUNNING loop is a SelectorEventLoop and replace it.
    # This handles the case where uvicorn's reload worker already created a
    # SelectorEventLoop before our patches run.
    try:
        loop = asyncio.get_running_loop()
        if isinstance(loop, asyncio.SelectorEventLoop):
            print(f"[patches] WARNING: Running loop is {type(loop).__name__}, "
                  "but subprocess support requires ProactorEventLoop.")
            print("[patches] Subprocess creation will use a new ProactorEventLoop via thread.")
            # Cannot replace a running loop, but we can install a child watcher
            # workaround. The real fix is handled in _safe_run by using a
            # ProactorEventLoop in a separate thread for subprocess creation.
    except RuntimeError:
        # No running loop yet — the policy will take effect when one is created
        print("[patches] No running event loop yet — policy will apply on loop creation")


def _patch_api_credentials() -> None:
    """Override local-proxy API credentials with real ones from .env."""
    # Support both naming conventions:
    #   Local/.env:       AZURE_FOUNDRY_API_KEY / AZURE_FOUNDRY_ENDPOINT
    #   Container Apps:   ANTHROPIC_FOUNDRY_API_KEY / ANTHROPIC_FOUNDRY_BASE_URL
    api_key = (
        os.environ.get("AZURE_FOUNDRY_API_KEY", "")
        or os.environ.get("ANTHROPIC_FOUNDRY_API_KEY", "")
    )
    base_url = (
        os.environ.get("AZURE_FOUNDRY_ENDPOINT", "")
        or os.environ.get("ANTHROPIC_FOUNDRY_BASE_URL", "")
    )
    model = os.environ.get("CLAUDE_MODEL", "")

    if not api_key:
        print("[patches] WARNING: AZURE_FOUNDRY_API_KEY not set — skipping credential patch")
        return

    os.environ["ANTHROPIC_API_KEY"] = api_key
    print(f"[patches] Set ANTHROPIC_API_KEY from AZURE_FOUNDRY_API_KEY (len={len(api_key)})")

    if base_url:
        clean_url = base_url.rstrip("/")
        os.environ["ANTHROPIC_BASE_URL"] = clean_url
        print(f"[patches] Set ANTHROPIC_BASE_URL = {clean_url}")

    if model:
        os.environ["CLAUDE_AGENT_MODEL"] = model
        print(f"[patches] Set CLAUDE_AGENT_MODEL = {model}")

    # Claude Code CLI requires Foundry-specific env vars for Azure auth
    os.environ["CLAUDE_CODE_USE_FOUNDRY"] = "true"
    os.environ["ANTHROPIC_FOUNDRY_API_KEY"] = api_key
    if base_url:
        os.environ["ANTHROPIC_FOUNDRY_BASE_URL"] = base_url.rstrip("/")
    print("[patches] Set CLAUDE_CODE_USE_FOUNDRY=true + Foundry credentials")


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
    print(
        f"[patches] Applied Windows CLI patch: {node_exe_str} {cli_js_str} (bypassing .CMD wrapper)"
    )
