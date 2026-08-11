"""Clinical Reviewer Hosted Agent — refreshed Foundry Hosted Agents preview.

Validates ICD-10 codes, extracts clinical indicators with confidence
scoring, searches PubMed literature and ClinicalTrials.gov, and returns
a structured clinical profile for downstream coverage assessment.

Deployed as a Foundry Hosted Agent using the refreshed preview stack:
  - FoundryChatClient (agent-framework-foundry) — model bridge
  - Agent (agent-framework-core)                — agent definition + tools
  - ResponsesHostServer (agent-framework-foundry-hosting) — HTTP host

MCP wiring (all in-container):
  - ICD-10 codes  : MCPStreamableHTTPTool, URL from MCP_ICD10_CODES env var
  - Clinical Trials: MCPStreamableHTTPTool, URL from MCP_CLINICAL_TRIALS env var
  - PubMed        : MCPStreamableHTTPTool, URL from MCP_PUBMED env var

All three MCPs are stateless HTTPS endpoints on Anthropic's healthcare
gateway and can be swapped via env var without code changes. See
docs/architecture.md § "MCP Integration" for the rationale on the
in-container wiring choice (vs. the Foundry-managed Toolbox model).

Structured output is enforced via default_options={"response_format": ClinicalResult},
which the host passes through to every agent.run() call. The `store: False`
option is required by the refreshed preview because the platform now manages
conversation history.

Migration ref: https://learn.microsoft.com/azure/foundry/agents/how-to/migrate-hosted-agent-preview
"""
import os
from pathlib import Path

import httpx
from agent_framework import Agent, MCPStreamableHTTPTool, SkillsProvider
from agent_framework.foundry import FoundryChatClient
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.identity import (
    AzureDeveloperCliCredential,
    ChainedTokenCredential,
    DefaultAzureCredential,
    ManagedIdentityCredential,
)
from dotenv import load_dotenv

from schemas import ClinicalResult

load_dotenv(override=True)  # override=True required for Foundry-deployed env vars


# Shared httpx client for the in-container MCP tools. The explicit
# `User-Agent: claude-code/1.0` header is defensive insurance: Cloudflare
# (the gateway in front of hcls.mcp.claude.com) blocks the default
# `Python-urllib/*` UA but accepts any other identifier.
_MCP_HTTP_CLIENT = httpx.AsyncClient(
    headers={"User-Agent": "claude-code/1.0"},
    timeout=httpx.Timeout(60.0),
)


def main() -> None:
    # --- Observability ---
    # Bridge legacy APPLICATION_INSIGHTS_CONNECTION_STRING (underscore form,
    # used by docker-compose .env) to the canonical APPLICATIONINSIGHTS_CONNECTION_STRING
    # name. In Foundry the platform injects the canonical name directly when
    # the project has an App Insights connection.
    #
    # CAVEAT (current preview): the platform's auto-injection of
    # APPLICATIONINSIGHTS_CONNECTION_STRING produces a malformed value that
    # crashes `azure.ai.agentserver.core._tracing` at startup before /readiness
    # can return 200 (→ 424 session_not_ready). We work around this by reading
    # our explicit OTEL_CONNECTION_STRING (set in agent.yaml) and overwriting
    # the broken platform value before the host server is constructed. If the
    # platform-injected value is well-formed, we leave it alone.
    _explicit_conn = os.environ.get("OTEL_CONNECTION_STRING") or os.environ.get(
        "APPLICATION_INSIGHTS_CONNECTION_STRING"
    )
    _platform_conn = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING", "")
    if "InstrumentationKey=" not in _platform_conn:
        if _explicit_conn:
            os.environ["APPLICATIONINSIGHTS_CONNECTION_STRING"] = _explicit_conn
        else:
            os.environ.pop("APPLICATIONINSIGHTS_CONNECTION_STRING", None)
    _ai_conn = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if _ai_conn:
        # Wire MAF OTel instrumentation BEFORE Agent / ResponsesHostServer
        # construction so all gen_ai.* spans, W3C trace context, and the
        # agent_name resource attribute (from FOUNDRY_AGENT_NAME) are captured
        # and exported to App Insights via ResponsesHostServer.
        # `enable_sensitive_data` attaches prompts, completions, and tool-call
        # arguments to spans — keep OFF in any shared environment (PHI risk).
        # Toggle via ENABLE_OTEL_SENSITIVE_DATA=true for local debugging only.
        from agent_framework.observability import enable_instrumentation
        enable_instrumentation(
            enable_sensitive_data=os.environ.get(
                "ENABLE_OTEL_SENSITIVE_DATA", "false"
            ).lower() == "true",
        )

    # --- MCP tools (all in-container) ---
    # ICD-10, Clinical Trials, and PubMed are wired here from MCP_* env vars
    # set by agents/clinical/agent.yaml (Foundry) or docker-compose.yml (local).
    tools = []
    if os.environ.get("MCP_ICD10_CODES"):
        tools.append(MCPStreamableHTTPTool(
            name="icd10-codes",
            description="Validate and look up ICD-10 diagnosis and procedure codes",
            url=os.environ["MCP_ICD10_CODES"],
            http_client=_MCP_HTTP_CLIENT,
            load_prompts=False,
        ))
    if os.environ.get("MCP_PUBMED"):
        tools.append(MCPStreamableHTTPTool(
            name="pubmed",
            description="Search biomedical literature on PubMed",
            url=os.environ["MCP_PUBMED"],
            http_client=_MCP_HTTP_CLIENT,
            load_prompts=False,
        ))
    if os.environ.get("MCP_CLINICAL_TRIALS"):
        tools.append(MCPStreamableHTTPTool(
            name="clinical-trials",
            description="Search ClinicalTrials.gov for relevant trials",
            url=os.environ["MCP_CLINICAL_TRIALS"],
            http_client=_MCP_HTTP_CLIENT,
            load_prompts=False,
        ))

    # --- Skills from local directory ---
    # SkillsProvider was refactored in agent-framework-core 1.2.0: file-based
    # construction moved from `SkillsProvider(skill_paths=...)` (initial preview)
    # to the `SkillsProvider.from_paths(...)` factory. Using the old kwarg form
    # crashes the agent on import — /readiness never returns 200, so Foundry
    # raises HTTP 424 session_not_ready.
    # agent-framework-core registers skill tools with approval_mode
    # "always_require" by default, which makes the agent emit an
    # mcp_approval_request and stop instead of returning a result. These skills
    # are first-party files baked into the image, so opt the read-only tools out
    # (run_skill_script still requires approval; no skill here ships a script).
    skills_provider = SkillsProvider.from_paths(
        str(Path(__file__).parent / "skills"),
        disable_load_skill_approval=True,
        disable_read_skill_resource_approval=True,
    )

    # --- Foundry chat client + Agent (refreshed preview) ---
    # Platform-injected env vars FOUNDRY_PROJECT_ENDPOINT / MODEL_DEPLOYMENT_NAME
    # are preferred; fall back to legacy AZURE_* names for docker-compose local dev.
    project_endpoint = os.environ.get(
        "FOUNDRY_PROJECT_ENDPOINT"
    ) or os.environ["AZURE_AI_PROJECT_ENDPOINT"]
    model = os.environ.get(
        "MODEL_DEPLOYMENT_NAME"
    ) or os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"]

    # Credential resolution matches Azure-Samples foundry hosted-agent pattern.
    # See compliance/main.py for the full rationale.
    _client_id = os.environ.get("AZURE_CLIENT_ID")
    if _client_id:
        credential = ChainedTokenCredential(
            ManagedIdentityCredential(client_id=_client_id),
            AzureDeveloperCliCredential(
                tenant_id=os.environ.get("AZURE_TENANT_ID"),
                process_timeout=60,
            ),
        )
    else:
        credential = DefaultAzureCredential()

    chat_client = FoundryChatClient(
        project_endpoint=project_endpoint,
        model=model,
        credential=credential,
        allow_preview=True,
    )

    # default_options enforces ClinicalResult schema on every agent.run() call
    # (token-level JSON constraint, no fence parsing). `store: False` is mandatory
    # in the refreshed preview because the platform manages conversation history.
    agent = Agent(
        client=chat_client,
        name="clinical-reviewer-agent",
        id="clinical-reviewer-agent",  # Must match registered agent name for Foundry Traces correlation
        instructions=(
            "You are a Clinical Reviewer Agent for prior authorization requests. "
            "Use your clinical-review skill to validate ICD-10 codes, extract clinical "
            "indicators with confidence scoring, search supporting literature, and "
            "check for relevant clinical trials."
        ),
        tools=tools,
        context_providers=[skills_provider],
        default_options={"response_format": ClinicalResult, "store": False},
    )

    # --- Serve as HTTP endpoint via the refreshed Hosted Agents host ---
    # ResponsesHostServer exposes POST /responses and GET /readiness on port 8088.
    ResponsesHostServer(agent).run()


if __name__ == "__main__":
    main()
