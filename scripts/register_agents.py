#!/usr/bin/env python3
"""Register and start the 4 prior-auth agents as Foundry Hosted Agents.

This script is called by the azure.yaml postprovision hook after agent images
have been built and pushed to ACR. It registers each agent with Foundry Agent
Service (creating a new version for each deploy) and then starts the deployments.

Requirements:
  pip install "azure-ai-projects>=2.0.0"

Required environment variables (set automatically by the postprovision hook):
  AZURE_AI_PROJECT_ENDPOINT          — Foundry project endpoint
  AZURE_CONTAINER_REGISTRY_ENDPOINT  — ACR login server (e.g. myacr.azurecr.io)
  AI_FOUNDRY_ACCOUNT_NAME            — Foundry account name
  AI_FOUNDRY_PROJECT_NAME            — Foundry project name
  AZURE_OPENAI_DEPLOYMENT_NAME       — Model deployment name (default: gpt-5.4)

Optional environment variables:
  APPLICATION_INSIGHTS_CONNECTION_STRING — For agent observability (passed to agents)
  MCP_ICD10_CODES, MCP_PUBMED, MCP_CLINICAL_TRIALS  — Override MCP URLs for clinical agent
  MCP_NPI_REGISTRY, MCP_CMS_COVERAGE                — Override MCP URLs for coverage agent
"""

import os
import subprocess
import sys


def run() -> None:
    project_endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT", "").rstrip("/")
    acr_endpoint = os.environ.get("AZURE_CONTAINER_REGISTRY_ENDPOINT", "").rstrip("/")
    account_name = os.environ.get("AI_FOUNDRY_ACCOUNT_NAME", "")
    project_name = os.environ.get("AI_FOUNDRY_PROJECT_NAME", "")
    model_name = os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-5.4")
    app_insights_cs = os.environ.get("APPLICATION_INSIGHTS_CONNECTION_STRING", "")

    if not project_endpoint:
        print("ERROR: AZURE_AI_PROJECT_ENDPOINT is not set.", file=sys.stderr)
        sys.exit(1)
    if not acr_endpoint:
        print("ERROR: AZURE_CONTAINER_REGISTRY_ENDPOINT is not set.", file=sys.stderr)
        sys.exit(1)
    if not account_name or not project_name:
        print(
            "ERROR: AI_FOUNDRY_ACCOUNT_NAME and AI_FOUNDRY_PROJECT_NAME must be set.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        from azure.ai.projects import AIProjectClient
        from azure.ai.projects.models import (
            AgentProtocol,
            HostedAgentDefinition,
            ProtocolVersionRecord,
        )
        from azure.identity import DefaultAzureCredential
    except ImportError:
        print(
            "ERROR: azure-ai-projects is not installed. Run:\n"
            "  pip install 'azure-ai-projects>=2.0.0'",
            file=sys.stderr,
        )
        sys.exit(1)

    client = AIProjectClient(
        endpoint=project_endpoint,
        credential=DefaultAzureCredential(),
        allow_preview=True,
    )

    # MCP defaults (can be overridden via env vars in agent.yaml or here)
    mcp_icd10 = os.environ.get("MCP_ICD10_CODES", "https://mcp.deepsense.ai/icd10_codes/mcp")
    mcp_pubmed = os.environ.get("MCP_PUBMED", "https://pubmed.mcp.claude.com/mcp")
    mcp_trials = os.environ.get(
        "MCP_CLINICAL_TRIALS", "https://mcp.deepsense.ai/clinical_trials/mcp"
    )
    mcp_npi = os.environ.get("MCP_NPI_REGISTRY", "https://mcp.deepsense.ai/npi_registry/mcp")
    mcp_cms = os.environ.get("MCP_CMS_COVERAGE", "https://mcp.deepsense.ai/cms_coverage/mcp")

    agents = [
        {
            "name": "clinical-reviewer-agent",
            "image": f"{acr_endpoint}/agent-clinical:latest",
            "cpu": "1",
            "memory": "2Gi",
            "env": {
                "AZURE_AI_PROJECT_ENDPOINT": project_endpoint,
                "AZURE_OPENAI_DEPLOYMENT_NAME": model_name,
                "MCP_ICD10_CODES": mcp_icd10,
                "MCP_PUBMED": mcp_pubmed,
                "MCP_CLINICAL_TRIALS": mcp_trials,
                "APPLICATION_INSIGHTS_CONNECTION_STRING": app_insights_cs,
            },
        },
        {
            "name": "coverage-assessment-agent",
            "image": f"{acr_endpoint}/agent-coverage:latest",
            "cpu": "1",
            "memory": "2Gi",
            "env": {
                "AZURE_AI_PROJECT_ENDPOINT": project_endpoint,
                "AZURE_OPENAI_DEPLOYMENT_NAME": model_name,
                "MCP_NPI_REGISTRY": mcp_npi,
                "MCP_CMS_COVERAGE": mcp_cms,
                "APPLICATION_INSIGHTS_CONNECTION_STRING": app_insights_cs,
            },
        },
        {
            "name": "compliance-agent",
            "image": f"{acr_endpoint}/agent-compliance:latest",
            "cpu": "0.5",
            "memory": "1Gi",
            "env": {
                "AZURE_AI_PROJECT_ENDPOINT": project_endpoint,
                # Compliance uses gpt-5.4 for consistency with all other agents
                "AZURE_OPENAI_DEPLOYMENT_NAME": os.environ.get(
                    "AZURE_OPENAI_COMPLIANCE_DEPLOYMENT_NAME", "gpt-5.4"
                ),
                "APPLICATION_INSIGHTS_CONNECTION_STRING": app_insights_cs,
            },
        },
        {
            "name": "synthesis-agent",
            "image": f"{acr_endpoint}/agent-synthesis:latest",
            "cpu": "1",
            "memory": "2Gi",
            "env": {
                "AZURE_AI_PROJECT_ENDPOINT": project_endpoint,
                "AZURE_OPENAI_DEPLOYMENT_NAME": model_name,
                "APPLICATION_INSIGHTS_CONNECTION_STRING": app_insights_cs,
            },
        },
    ]

    print()
    for agent_def in agents:
        name = agent_def["name"]
        print(f"  Registering {name}...", end="", flush=True)
        try:
            agent_version = client.agents.create_version(
                agent_name=name,
                definition=HostedAgentDefinition(
                    container_protocol_versions=[
                        ProtocolVersionRecord(
                            protocol=AgentProtocol.RESPONSES, version="v1"
                        )
                    ],
                    cpu=agent_def["cpu"],
                    memory=agent_def["memory"],
                    image=agent_def["image"],
                    environment_variables=agent_def["env"],
                ),
            )
            version_num = agent_version.version
            print(f" version {version_num} created")
        except Exception as exc:
            print(f" FAILED\nERROR: {exc}", file=sys.stderr)
            sys.exit(1)

        # Start the new deployment via az CLI
        print(f"  Starting {name} (version {version_num})...", end="", flush=True)
        try:
            result = subprocess.run(
                [
                    "az",
                    "cognitiveservices",
                    "agent",
                    "start",
                    "--account-name",
                    account_name,
                    "--project-name",
                    project_name,
                    "--name",
                    name,
                    "--agent-version",
                    str(version_num),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            print(" started")
        except subprocess.CalledProcessError as exc:
            # "conflict" means the agent is already running — treat as success
            if "already exists with status Running" in (exc.stderr or ""):
                print(" already running")
            else:
                print(
                    f" WARNING: could not auto-start via CLI ({exc.returncode}).\n"
                    f"  Manually start from Foundry portal: Agents → {name} → Start",
                )
        except FileNotFoundError:
            print(
                " WARNING: 'az' CLI not found — start the agent from Foundry portal:\n"
                f"  Agents → {name} → Start"
            )

    print()
    print("  All 4 agents registered successfully.")
    print(
        "  Note: if auto-start failed, start each agent from the Foundry portal:\n"
        "  Microsoft Foundry portal → your project → Agents → select agent → Start"
    )


if __name__ == "__main__":
    run()
