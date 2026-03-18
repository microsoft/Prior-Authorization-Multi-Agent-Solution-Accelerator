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
            os.environ.setdefault("OTEL_SERVICE_NAME", "agent-synthesis")
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
            print("[observability] Azure Monitor + MAF instrumentation enabled for agent-synthesis")
        except Exception as _obs_err:  # best-effort — never crash the agent
            print(f"[observability] WARNING: failed to initialize — {_obs_err}")
    else:
        print("[observability] APPLICATION_INSIGHTS_CONNECTION_STRING not set — telemetry disabled")

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
    from_agent_framework(agent).run()


if __name__ == "__main__":
    main()
