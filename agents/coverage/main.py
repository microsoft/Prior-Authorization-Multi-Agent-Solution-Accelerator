"""Coverage Assessment Hosted Agent — MAF entry point.

Verifies provider NPI, searches Medicare coverage policies via CMS MCP,
maps clinical findings to policy criteria with MET/NOT_MET/INSUFFICIENT
assessment, and returns a structured coverage evaluation.

Deployed as a Foundry Hosted Agent via azure.ai.agentserver.
MCP tools are wired via MCPStreamableHTTPTool in this container, with Foundry
MCPTool connections registered for proxy routing (see scripts/register_agents.py).
Structured output enforced via default_options={"response_format": CoverageResult},
which from_agent_framework passes through to every agent.run() call.
"""
import os
from pathlib import Path

import httpx
from agent_framework import MCPStreamableHTTPTool, SkillsProvider
from agent_framework.azure import AzureOpenAIResponsesClient
from azure.ai.agentserver.agentframework import from_agent_framework
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

from schemas import CoverageResult

load_dotenv(override=True)  # override=True required for Foundry-deployed env vars

# DeepSense CloudFront routes on User-Agent — without this header the server
# returns a 301 redirect to the docs site instead of handling MCP messages.
_MCP_HTTP_CLIENT = httpx.AsyncClient(
    headers={"User-Agent": "claude-code/1.0"},
    timeout=httpx.Timeout(60.0),
)


def main() -> None:
    # --- Observability: export MAF spans to App Insights / Foundry portal traces ---
    _ai_conn = os.environ.get("APPLICATION_INSIGHTS_CONNECTION_STRING")
    if _ai_conn:
        try:
            from azure.monitor.opentelemetry import configure_azure_monitor
            from agent_framework.observability import (
                create_resource,
                create_metric_views,
                enable_instrumentation,
            )
            # Sets the cloud role name shown on the Application Map node.
            # Use setdefault so an explicit OTEL_SERVICE_NAME env var always wins.
            os.environ.setdefault("OTEL_SERVICE_NAME", "agent-coverage")
            configure_azure_monitor(
                connection_string=_ai_conn,
                resource=create_resource(),
                views=create_metric_views(),
                enable_live_metrics=True,
                enable_performance_counters=False,
            )
            enable_instrumentation(
                enable_sensitive_data=os.environ.get("OTEL_RECORD_CONTENT", "").lower() == "true",
            )
            print("[observability] Azure Monitor + MAF instrumentation enabled for agent-coverage")
        except Exception as _obs_err:  # best-effort — never crash the agent
            print(f"[observability] WARNING: failed to initialize — {_obs_err}")
    else:
        print("[observability] APPLICATION_INSIGHTS_CONNECTION_STRING not set — telemetry disabled")

    # --- MCP tool connections ---
    # MCPStreamableHTTPTool wires tools into the agent container. Foundry also
    # has MCPTool connections registered (see register_agents.py) for proxy routing.
    npi_tool = MCPStreamableHTTPTool(
        name="npi-registry",
        description="Validate and look up provider NPI numbers from CMS NPPES",
        url=os.environ["MCP_NPI_REGISTRY"],
        http_client=_MCP_HTTP_CLIENT,
        load_prompts=False,
    )
    cms_tool = MCPStreamableHTTPTool(
        name="cms-coverage",
        description="Search Medicare NCDs, LCDs and coverage policy documents",
        url=os.environ["MCP_CMS_COVERAGE"],
        http_client=_MCP_HTTP_CLIENT,
        load_prompts=False,
    )

    # --- Skills from local directory ---
    skills_provider = SkillsProvider(
        skill_paths=str(Path(__file__).parent / "skills")
    )

    # --- Agent using Responses API on Microsoft Foundry ---
    # default_options enforces CoverageResult schema on every agent.run() call
    # made by from_agent_framework — token-level JSON constraint, no fence parsing.
    agent = AzureOpenAIResponsesClient(
        project_endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
        deployment_name=os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"],
        credential=DefaultAzureCredential(),
    ).as_agent(
        name="coverage-assessment-agent",
        instructions=(
            "You are a Coverage Assessment Agent for prior authorization requests. "
            "Use your coverage-assessment skill to verify provider credentials, search "
            "coverage policies, and map clinical evidence to policy criteria with "
            "MET/NOT_MET/INSUFFICIENT assessment and per-criterion confidence scoring."
        ),
        tools=[npi_tool, cms_tool],
        context_providers=[skills_provider],
        default_options={"response_format": CoverageResult},
    )

    # --- Serve as HTTP endpoint for Foundry hosting ---
    # Default port is 8088 (the Foundry Hosted Agent convention via DEFAULT_AD_PORT).
    from_agent_framework(agent).run()


if __name__ == "__main__":
    main()
