"""Synthesis Decision Hosted Agent — MAF entry point.

Synthesizes outputs from Compliance, Clinical, and Coverage agents into
a final APPROVE or PEND recommendation using gate-based evaluation,
weighted confidence scoring, and a structured audit trail.

Deployed as a Foundry Hosted Agent via azure.ai.agentserver.
No MCP connections required — synthesis is pure reasoning over agent outputs.
Structured output enforced via default_options={"response_format": SynthesisOutput},
which from_agent_framework passes through to every agent.run() call.
"""
import os
from pathlib import Path

from agent_framework import SkillsProvider
from agent_framework.azure import AzureOpenAIResponsesClient
from azure.ai.agentserver.agentframework import from_agent_framework
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

from schemas import SynthesisOutput

load_dotenv(override=True)  # override=True required for Foundry-deployed env vars


def _patch_trace_agent_id(app, agent_name: str) -> None:
    """Patch the adapter to populate trace span attributes for Foundry correlation.

    The agentserver adapter (v1.0.0b17) populates agent identity attributes
    on log records (via CustomDimensionsFilter/get_dimensions) but NOT on
    OTel spans. The Foundry Traces tab reads from spans, so it can't
    correlate traces to agents.

    This patch wraps AgentRunContextMiddleware.set_run_context_to_context_var
    to inject both gen_ai.agent.id and the Foundry-injected env var
    dimensions (AGENT_ID, AGENT_NAME, AGENT_PROJECT_NAME) into the span
    context so they appear on all spans, not just log records.
    """
    from azure.ai.agentserver.core.server.base import (
        AgentRunContextMiddleware,
        request_context,
    )
    from azure.ai.agentserver.core.logger import get_dimensions

    _original = AgentRunContextMiddleware.set_run_context_to_context_var

    def _patched(self, run_context):
        _original(self, run_context)
        ctx = request_context.get() or {}
        if not ctx.get("gen_ai.agent.id"):
            ctx["gen_ai.agent.id"] = agent_name
            ctx["gen_ai.agent.name"] = agent_name
        # Inject Foundry-injected env var dimensions into span context
        # so they appear on OTel spans (not just log records)
        dims = get_dimensions()
        for k, v in dims.items():
            if k not in ctx:
                ctx[k] = v
        request_context.set(ctx)

    AgentRunContextMiddleware.set_run_context_to_context_var = _patched


def main() -> None:
    # --- Observability: env var setup for Foundry agentserver adapter ---
    _ai_conn = os.environ.get("APPLICATION_INSIGHTS_CONNECTION_STRING")
    if _ai_conn:
        os.environ.setdefault("APPLICATIONINSIGHTS_CONNECTION_STRING", _ai_conn)
        print("[observability] App Insights connection string set for agent-synthesis")
    else:
        print("[observability] APPLICATION_INSIGHTS_CONNECTION_STRING not set — telemetry disabled")
    os.environ.setdefault("OTEL_SERVICE_NAME", "agent-synthesis")

    # --- No MCP tools — synthesis is pure reasoning over agent outputs ---

    # --- Skills from local directory ---
    skills_provider = SkillsProvider(
        skill_paths=str(Path(__file__).parent / "skills")
    )

    # --- Agent using Responses API on Microsoft Foundry ---
    # default_options enforces SynthesisOutput schema on every agent.run() call
    # made by from_agent_framework — token-level JSON constraint, no fence parsing.
    agent = AzureOpenAIResponsesClient(
        project_endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
        deployment_name=os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"],
        credential=DefaultAzureCredential(),
    ).as_agent(
        name="synthesis-agent",
        id="synthesis-agent",  # Must match registered agent name for Foundry Traces correlation
        instructions=(
            "You are the Synthesis Agent for prior authorization review. "
            "Use your synthesis-decision skill to evaluate the outputs from the "
            "Compliance, Clinical Reviewer, and Coverage agents through a strict "
            "3-gate pipeline (Provider → Codes → Medical Necessity) and produce "
            "a single APPROVE or PEND recommendation with weighted confidence scoring "
            "and a complete audit trail."
        ),
        tools=[],
        context_providers=[skills_provider],
        default_options={"response_format": SynthesisOutput},
    )

    # --- Serve as HTTP endpoint for Foundry hosting ---
    # Default port is 8088 (the Foundry Hosted Agent convention via DEFAULT_AD_PORT).
    app = from_agent_framework(agent)
    _patch_trace_agent_id(app, "synthesis-agent")
    app.run()


if __name__ == "__main__":
    main()
