"""Helpers for invoking Foundry Hosted Agent runtimes.

Supports two invocation modes, selected automatically based on configuration:

Direct HTTP mode (Docker Compose / local dev):
  Triggered when HOSTED_AGENT_*_URL is set (e.g. http://agent-clinical:8000).
  Calls POST {url}/responses using the Foundry Responses API envelope.
  Used by docker-compose where each agent runs as a local container.

Foundry Hosted Agents mode — refreshed preview (Azure deployment via azd up):
  Triggered when HOSTED_AGENT_*_URL is empty and AZURE_AI_PROJECT_ENDPOINT is set.
  Uses AIProjectClient(allow_preview=True).get_openai_client(agent_name=...) which
  returns a client pre-bound to the agent's dedicated endpoint. No extra_body and
  no agent_reference are needed — each agent has its own URL of the form
  {project_endpoint}/agents/{name}/endpoint/protocols/openai/v1/responses.
  Auth uses DefaultAzureCredential — resolves to the backend ACA managed identity.

  Migration ref:
  https://learn.microsoft.com/azure/foundry/agents/how-to/migrate-hosted-agent-preview#agent-invocation-changes
"""

import asyncio
import json
import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# ── Per-agent OpenAI clients (lazy-initialised, cached by agent name) ────────
# In the refreshed preview each Foundry agent has a dedicated endpoint and the
# SDK binds a client per-agent. We cache one client per foundry_agent_name.
_openai_clients: dict[str, Any] = {}
_project_client: Any = None


def _get_openai_client(foundry_agent_name: str) -> Any:
    """Get or create a cached OpenAI client bound to a specific Foundry agent."""
    cached = _openai_clients.get(foundry_agent_name)
    if cached is not None:
        return cached

    try:
        from azure.ai.projects import AIProjectClient
        from azure.identity import DefaultAzureCredential
    except ImportError:
        raise RuntimeError(
            "azure-ai-projects>=2.4.0 and azure-identity are required for Foundry "
            "Hosted Agents mode. Install with: pip install 'azure-ai-projects>=2.4.0' "
            "azure-identity"
        )

    global _project_client
    if _project_client is None:
        project_endpoint = settings.AZURE_AI_PROJECT_ENDPOINT.rstrip("/")
        # allow_preview=True is required for the agent_name parameter on
        # get_openai_client() (refreshed preview surface).
        _project_client = AIProjectClient(
            endpoint=project_endpoint,
            credential=DefaultAzureCredential(),
            allow_preview=True,
        )

    client = _project_client.get_openai_client(agent_name=foundry_agent_name)
    _openai_clients[foundry_agent_name] = client
    return client


def _build_direct_headers() -> dict[str, str]:
    """Build headers for direct HTTP mode (docker-compose). Supports optional token."""
    headers = {"Content-Type": "application/json"}
    if settings.HOSTED_AGENT_AUTH_TOKEN:
        value = settings.HOSTED_AGENT_AUTH_TOKEN
        if settings.HOSTED_AGENT_AUTH_SCHEME:
            value = f"{settings.HOSTED_AGENT_AUTH_SCHEME} {value}"
        headers[settings.HOSTED_AGENT_AUTH_HEADER] = value
    return headers


def _extract_result(data: Any) -> dict:
    """Parse a Foundry Responses API reply into a plain result dict.

    Expected shape:
        {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "text", "text": "<json string>"}]
                }
            ]
        }

    The agent emits structured output (MAF default_options response_format),
    so `text` is already a JSON-serialised Pydantic model — parse it directly.
    Falls back gracefully if the shape is unexpected.
    """
    if not isinstance(data, dict):
        return {"error": "Agent returned a non-object response", "tool_results": []}

    status = data.get("status", "")
    if status not in ("completed", ""):  # empty string = local test adapter
        # Extract error details from Foundry response (OpenAI Responses API
        # includes an "error" object when status is "failed")
        error_obj = data.get("error", {})
        if isinstance(error_obj, dict) and error_obj.get("message"):
            error_detail = f"Agent returned status={status!r}: {error_obj['message']}"
        else:
            error_detail = f"Agent returned status={status!r}"
        logger.warning(
            "Agent response status=%r (not 'completed'). "
            "Error: %s. Response keys: %s. Full response (truncated): %s",
            status,
            error_obj,
            list(data.keys()) if isinstance(data, dict) else "N/A",
            str(data)[:2000],
        )
        return {"error": error_detail, "tool_results": []}

    output = data.get("output", [])
    for item in output if isinstance(output, list) else []:
        if not isinstance(item, dict):
            continue
        for block in item.get("content", []) if isinstance(item.get("content"), list) else []:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                try:
                    return json.loads(text)
                except (json.JSONDecodeError, TypeError):
                    return {"error": f"Agent text was not valid JSON: {text[:200]}"}

    # Fallback: some adapters return the result directly under known keys
    for key in ("result", "data"):
        value = data.get(key)
        if isinstance(value, dict):
            return value

    return {"error": f"Could not extract result from agent response: {str(data)[:300]}"}


async def _invoke_direct_http(agent_name: str, url: str, payload: dict) -> dict:
    """Invoke agent via direct HTTP — Docker Compose / local dev mode.

    Uses the Foundry Responses API envelope expected by ResponsesHostServer.
    Input must be a flat array of message objects, not wrapped in a {messages: []} dict.
    """
    request_body = {
        "input": [{"type": "message", "role": "user", "content": json.dumps(payload)}]
    }
    responses_url = url.rstrip("/") + "/responses"

    try:
        timeout = httpx.Timeout(settings.HOSTED_AGENT_TIMEOUT_SECONDS)
        async with httpx.AsyncClient(
            timeout=timeout, headers=_build_direct_headers()
        ) as client:
            response = await client.post(responses_url, json=request_body)
            response.raise_for_status()
            data = response.json()
            result = _extract_result(data)
            logger.info(
                "Hosted %s invocation succeeded via %s", agent_name, responses_url
            )
            return result
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500] if exc.response is not None else str(exc)
        logger.warning("Hosted %s invocation failed: %s", agent_name, detail)
        return {
            "error": f"Hosted {agent_name} call failed ({exc.response.status_code}): {detail}",
            "tool_results": [],
        }
    except Exception as exc:
        logger.warning("Hosted %s invocation failed: %s", agent_name, exc)
        return {
            "error": f"Hosted {agent_name} call failed: {exc}",
            "tool_results": [],
        }


async def _invoke_foundry_agent(
    agent_name: str, foundry_agent_name: str, payload: dict
) -> dict:
    """Invoke a Foundry Hosted Agent via the refreshed-preview Responses API.

    Uses AIProjectClient(allow_preview=True).get_openai_client(agent_name=...)
    which returns a client pre-bound to the agent's dedicated endpoint, so we
    pass `input` directly with no `extra_body` or `agent_reference` wrapper.
    Authentication uses DefaultAzureCredential which resolves to the backend
    ACA managed identity on Azure (no secrets required).
    """
    try:
        openai_client = _get_openai_client(foundry_agent_name)
    except Exception as exc:
        return {
            "error": f"Failed to initialise Foundry client for {agent_name}: {exc}",
            "tool_results": [],
        }

    try:
        # Send the prior-auth payload as a single user message. The agent's
        # default_options enforces a Pydantic response_format, so the assistant
        # turn returns a JSON-serialised model that we parse below.
        response = await asyncio.to_thread(
            openai_client.responses.create,
            input=[{"type": "message", "role": "user", "content": json.dumps(payload)}],
        )

        # Use output_text for reliable text extraction, then parse as JSON
        output_text = response.output_text
        logger.info(
            "Foundry Hosted Agent %s (%s) response status=%s",
            agent_name, foundry_agent_name, response.status,
        )

        if not output_text:
            return {"error": f"Agent {agent_name} returned empty output", "tool_results": []}

        try:
            result = json.loads(output_text)
        except (json.JSONDecodeError, TypeError):
            result = {"error": f"Agent text was not valid JSON: {output_text[:200]}"}

        if isinstance(result, dict) and result.get("error"):
            logger.warning(
                "Foundry Hosted Agent %s (%s) extraction error: %s",
                agent_name, foundry_agent_name, result["error"],
            )
        else:
            logger.info(
                "Foundry Hosted Agent %s (%s) invocation succeeded",
                agent_name, foundry_agent_name,
            )
        return result
    except Exception as exc:
        detail = str(exc)[:500]
        logger.warning("Foundry %s invocation failed: %s", agent_name, detail)
        return {
            "error": f"Foundry Hosted Agent {agent_name} call failed: {detail}",
            "tool_results": [],
        }


async def invoke_hosted_agent(
    agent_name: str,
    url: str,
    payload: dict,
    foundry_agent_name: str = "",
) -> dict:
    """Invoke a hosted MAF agent — dispatches between Docker Compose and Foundry modes.

    Args:
        agent_name:         Display name for logging (e.g. "clinical-reviewer-agent").
        url:                Direct HTTP URL set by docker-compose. Empty string for
                            Foundry Hosted Agents mode.
        payload:            Request data dict forwarded to the agent.
        foundry_agent_name: Foundry Hosted Agent name (matches `name:` in agents/<dir>/agent.yaml,
            registered by `azd deploy` via the `services:` block in azure.yaml)
                            (e.g. "clinical-reviewer-agent"). Required when url
                            is empty and Foundry mode is active.

    Mode selection (automatic):
        url is set       → Direct HTTP (Docker Compose / local dev)
        url is empty     → Foundry Hosted Agents mode (requires AZURE_AI_PROJECT_ENDPOINT)
    """
    if url:
        return await _invoke_direct_http(agent_name, url, payload)

    if settings.AZURE_AI_PROJECT_ENDPOINT and foundry_agent_name:
        return await _invoke_foundry_agent(agent_name, foundry_agent_name, payload)

    return {
        "error": (
            f"{agent_name} is not reachable: set either HOSTED_AGENT_*_URL "
            "(Docker Compose) or AZURE_AI_PROJECT_ENDPOINT (Foundry Hosted Agents)."
        ),
        "tool_results": [],
    }