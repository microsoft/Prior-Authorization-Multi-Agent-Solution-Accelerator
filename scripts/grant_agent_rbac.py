#!/usr/bin/env python3
"""Grant Foundry User to each Hosted Agent's instance identity.

The `azd ai agent` extension provisions per-agent `instance_identity` and
`blueprint` Application identities at `create_version` time (preview April
2026+) but does NOT grant them the data-plane RBAC needed to call the
Foundry Responses API (Microsoft.CognitiveServices/accounts/AIServices/agents/*).

Without this grant, every POST /responses returns:

    HTTP 500
    {"error":{"code":"PermissionDenied",
              "message":"Principal does not have access to API/Operation."}}

This script:
  1. Reads the project endpoint + Foundry account scope from `azd env`.
  2. Lists the latest version of each hosted agent declared in azure.yaml.
  3. Grants `Foundry User` (formerly `Azure AI User`) on the Foundry account
     scope to each `instance_identity.principal_id` (idempotent — `az role
     assignment create` returns success if the assignment already exists).

Run automatically from the `postdeploy` hook in azure.yaml. Safe to re-run
manually:  python scripts/grant_agent_rbac.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Iterable

# Agent service names as they appear in azure.yaml `services:` block AND
# as the `name:` field in each agents/*/agent.yaml. Keep in sync with both.
HOSTED_AGENTS: tuple[str, ...] = (
    "clinical-reviewer-agent",
    "coverage-assessment-agent",
    "compliance-agent",
    "synthesis-agent",
)

# Data-plane role that includes Microsoft.CognitiveServices/accounts/AIServices/agents/*
# read + invoke. Project Manager is NOT needed for runtime — only for create_version().
# Referenced by role definition ID because the display name was renamed from
# "Azure AI User" to "Foundry User" and `az --role <name>` fails on updated tenants.
ROLE_ID = "53ca6127-db72-4b80-b1b0-d745d6d5456d"

# Latest stable api-version exposing instance_identity.principal_id.
AGENT_API_VERSION = "2025-11-15-preview"


def _run(cmd: list[str], *, capture: bool = True) -> str:
    """Run a shell command, return stdout (or raise)."""
    result = subprocess.run(
        cmd,
        check=True,
        text=True,
        capture_output=capture,
    )
    return result.stdout.strip() if capture else ""


def _azd_env(name: str) -> str:
    """Read a value from `azd env get-value`. Returns '' if missing."""
    try:
        return _run(["azd", "env", "get-value", name])
    except subprocess.CalledProcessError:
        return ""


def _get_token() -> str:
    """Acquire a bearer token for the ai.azure.com audience via Azure CLI."""
    return _run([
        "az", "account", "get-access-token",
        "--resource", "https://ai.azure.com",
        "--query", "accessToken",
        "-o", "tsv",
    ])


def _agent_latest_version(project_endpoint: str, agent_name: str, token: str) -> dict | None:
    """Return the latest version object for the named agent, or None if missing."""
    import urllib.request
    import urllib.error

    url = f"{project_endpoint}/agents/{agent_name}/versions?api-version={AGENT_API_VERSION}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(f"  WARN: cannot list {agent_name} versions ({exc.code} {exc.reason})", file=sys.stderr)
        return None
    versions = payload.get("data") or []
    if not versions:
        return None
    return max(versions, key=lambda v: int(v.get("version", "0")))


def _grant_role(principal_id: str, scope: str, role: str) -> bool:
    """Grant `role` to `principal_id` at `scope`. Returns True if newly created."""
    # Check existing first to provide cleaner output.
    existing = subprocess.run(
        ["az", "role", "assignment", "list",
         "--assignee-object-id", principal_id,
         "--role", role,
         "--scope", scope,
         "--query", "[].id", "-o", "tsv"],
        check=False, text=True, capture_output=True,
    )
    if existing.returncode == 0 and existing.stdout.strip():
        return False
    create = subprocess.run(
        ["az", "role", "assignment", "create",
         "--assignee-object-id", principal_id,
         "--assignee-principal-type", "ServicePrincipal",
         "--role", role,
         "--scope", scope,
         "--only-show-errors"],
        check=False, text=True, capture_output=True,
    )
    if create.returncode != 0:
        # Race-condition friendly: another concurrent run may have created it.
        if "RoleAssignmentExists" in (create.stderr or ""):
            return False
        print(f"  ERROR: role assignment failed: {create.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    return True


def main(agents: Iterable[str] = HOSTED_AGENTS) -> int:
    project_endpoint = _azd_env("AZURE_AI_PROJECT_ENDPOINT") or _azd_env("AI_FOUNDRY_PROJECT_ENDPOINT")
    sub_id = _azd_env("AZURE_SUBSCRIPTION_ID")
    rg = _azd_env("AZURE_RESOURCE_GROUP")
    foundry_account = _azd_env("AI_FOUNDRY_ACCOUNT_NAME")

    missing = [k for k, v in {
        "AZURE_AI_PROJECT_ENDPOINT": project_endpoint,
        "AZURE_SUBSCRIPTION_ID": sub_id,
        "AZURE_RESOURCE_GROUP": rg,
        "AI_FOUNDRY_ACCOUNT_NAME": foundry_account,
    }.items() if not v]
    if missing:
        print(f"ERROR: missing azd env values: {', '.join(missing)}", file=sys.stderr)
        return 1

    account_scope = (
        f"/subscriptions/{sub_id}/resourceGroups/{rg}"
        f"/providers/Microsoft.CognitiveServices/accounts/{foundry_account}"
    )

    token = _get_token()

    granted = 0
    for agent in agents:
        version = _agent_latest_version(project_endpoint, agent, token)
        if version is None:
            print(f"  - {agent:30s}  (no versions found, skipped)")
            continue
        instance = version.get("instance_identity") or {}
        principal_id = instance.get("principal_id")
        if not principal_id:
            print(f"  - {agent:30s}  v{version.get('version')}  (no instance identity, skipped)")
            continue
        is_new = _grant_role(principal_id, account_scope, ROLE_ID)
        status = "granted" if is_new else "ok"
        granted += int(is_new)
        print(f"  - {agent:30s}  v{version.get('version'):<3}  {status}")

    if granted:
        print(f"\n  {granted} new role assignment(s) created. RBAC may take ~30-60s to propagate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
