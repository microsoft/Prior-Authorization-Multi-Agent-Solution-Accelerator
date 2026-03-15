# Prior Authorization Multi-Agent Solution Accelerator

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
&nbsp;[![Azure](https://img.shields.io/badge/Azure-Deployable-blue?logo=microsoftazure)](https://azure.microsoft.com)
&nbsp;[![Agent Framework](https://img.shields.io/badge/Microsoft-Agent%20Framework-purple)](https://learn.microsoft.com/agent-framework/)

Built for **health plan payers** — insurers, managed care organizations, and utilization review teams — this multi-agent AI solution accelerates prior authorization (PA) intake, clinical review, coverage determination, and decision synthesis. It automates the payer-side workflow of receiving PA requests from providers, evaluating medical necessity against coverage policies, and producing auditable approve/pend recommendations with full compliance documentation.

The application is built with **Microsoft Foundry**, the **Microsoft Agent Framework (MAF)**, **Azure Container Apps**, and **MCP healthcare data servers**. Four specialized agents — Compliance, Clinical Reviewer, Coverage, and Synthesis — are each packaged as independent **Foundry Hosted Agents** using the native MAF `from_agent_framework` pattern. They work in parallel and sequence, coordinated by a FastAPI orchestrator that applies a gate-based decision rubric and produces a final recommendation with confidence scoring and an audit justification document.

The solution supports **two runtime modes**:

| Mode | How to start | What happens |
|------|-------------|--------------|
| **Foundry Hosted Agent** (recommended) | `azd up` | Agents are registered with Microsoft Foundry Hosted Agents; Foundry manages container lifecycle. Backend dispatches through the Foundry project endpoint using `agent_reference` routing and `DefaultAzureCredential`. |
| **Local / Docker Compose** | `docker compose up` | All 4 agent containers + backend + frontend run locally — no Azure deployment needed. |

Decision policy and evaluation methodology adapted from the [Anthropic prior-auth-review-skill](https://github.com/anthropics/healthcare/tree/main/prior-auth-review-skill): LENIENT mode decision policy, per-criterion MET/NOT_MET/INSUFFICIENT evaluation, confidence scoring, progressive gate evaluation, structured audit trails, NCCI bundling risk flagging, service-type classification, and provider specialty-procedure appropriateness as an auditable criterion.

<div align="center">

[**SOLUTION OVERVIEW**](#solution-overview) &nbsp;|&nbsp; [**QUICK DEPLOY**](#quick-deploy) &nbsp;|&nbsp; [**BUSINESS SCENARIO**](#business-scenario) &nbsp;|&nbsp; [**SUPPORTING DOCUMENTATION**](#supporting-documentation)

</div>

> [!CAUTION]
> This is an AI-assisted triage tool. All recommendations are drafts that require human clinical review before any authorization decision is finalized. Coverage policies reflect Medicare LCDs/NCDs only — commercial and Medicare Advantage plans may differ.

> [!IMPORTANT]
> This project is a **solution accelerator** — not a production-ready application. It is designed as a reference architecture and working prototype that customers can use as a starting point to build, customize, and extend their own prior authorization solution. Microsoft does not provide production support for this accelerator. Customers are responsible for testing, validation, regulatory compliance, and production deployment within their own environment.

> [!NOTE]
> With any AI solutions you create using these templates, you are responsible for assessing all associated risks and for complying with all applicable laws and safety standards. Learn more in the transparency documents for [Agent Service](https://learn.microsoft.com/en-us/azure/ai-foundry/responsible-ai/agents/transparency-note) and [Agent Framework](https://github.com/microsoft/agent-framework/blob/main/TRANSPARENCY_FAQ.md).

---

<a id="solution-overview"></a>
## <img src="./docs/images/readme/solution-overview.svg" width="48" /> Solution overview

This solution leverages **Microsoft Foundry**, the **Microsoft Agent Framework (MAF)**, **Azure Application Insights**, and **MCP healthcare data servers** to create an intelligent prior authorization review pipeline where four specialized AI agents work together to validate, assess, and synthesize PA decisions with full audit transparency and native OpenTelemetry tracing. Each specialist agent is independently containerized and deployed as a Foundry Hosted Agent, while the FastAPI orchestrator and Next.js frontend run in Azure Container Apps.

### Solution architecture

|![Solution Architecture](./docs/images/readme/solution-architecture.svg)|
|---|

### Agentic architecture

The orchestrator coordinates four phases with four specialized agents:

<p align="center">
  <img src="./docs/images/readme/agentic-architecture.svg" alt="Agentic Architecture" />
</p>

<br/>

### Additional resources

| Resource | Description |
|----------|-------------|
| [Azure OpenAI GPT-5.4 in Microsoft Foundry](https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/introducing-gpt-5-4-in-microsoft-foundry/4499785) | GPT-5.4 model announcement and capabilities |
| [Microsoft Agent Framework Documentation](https://learn.microsoft.com/en-us/agent-framework/) | Official MAF documentation and getting started guides |
| [Anthropic Healthcare MCP Marketplace](https://github.com/anthropics/healthcare) | MCP healthcare data tools (MCP data tools, not the AI model) |
| [Prior Auth Review Skill](https://github.com/anthropics/healthcare/tree/main/prior-auth-review-skill) | Original methodology reference for decision policy and evaluation criteria |
| [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) | MCP specification and tooling |

<br/>

### Key features

<details open>
  <summary><b>Multi-agent parallel execution</b></summary>

  - Compliance and Clinical agents run concurrently via `asyncio.gather`, reducing wall-clock time from 20+ minutes to under 2 minutes per case
  - Coverage Agent runs sequentially after clinical findings are available
  - Synthesis Agent executes the gate-based rubric to generate the final recommendation and confidence
  - Four-phase pipeline: Pre-flight → Parallel → Sequential → Synthesis → Audit
</details>

<details>
  <summary><b>Foundry Hosted Agent architecture</b></summary>

  - Each of the 4 specialist agents has its own `main.py`, `schemas.py`, `Dockerfile`, `agent.yaml`, and `skills/` directory under `agents/<name>/`
  - Agents use the native MAF `from_agent_framework` pattern with `default_options={"response_format": PydanticModel}` for token-level structured output — no JSON fence parsing
  - The FastAPI backend is a **pure HTTP dispatcher** — it has no local AI runtime; all specialist reasoning runs in the four independent agent containers
  - Each agent container exposes `POST /responses` (Foundry Responses API protocol) and is independently versioned, deployable, and scalable
  - `hosted_agents.py` is a **two-mode dispatcher**: direct HTTP to agent containers (Docker Compose), or `agent_reference` routing through `{AZURE_AI_PROJECT_ENDPOINT}/responses` with `DefaultAzureCredential` (Foundry Hosted Agents)
  - Agents are registered with Foundry via `scripts/register_agents.py` (postprovision hook in `azure.yaml`) — Foundry manages the ACA container lifecycle; no self-managed ACA modules in Bicep
</details>

<details>
  <summary><b>Skills-based architecture</b></summary>

  - Agent behaviors defined in SKILL.md files — domain experts can update clinical rules without code changes
  - SKILL.md files live alongside each agent container under `agents/<name>/skills/<skill-name>/SKILL.md`
  - Loaded at agent startup via MAF `SkillsProvider` — no backend code changes needed to update clinical rules
  - Compliance skill: 10-item checklist (NCCI bundling + service type classification added as items 9 and 10)
  - Coverage skill: Provider Specialty-Procedure Appropriateness is now a required explicit criterion (Step 1.4)
  - Clinical skill: low-confidence extraction banner when `extraction_confidence < 60%` surfaces directly in the frontend Clinical tab
  - Synthesis skill: emits `synthesis_audit_trail` (gate results + weighted confidence breakdown) visible in the frontend Synthesis tab
</details>

<details>
  <summary><b>MCP-powered data access</b></summary>

  - Five remote MCP servers: NPI Registry, ICD-10 Codes, CMS Coverage, Clinical Trials (DeepSense), PubMed (Anthropic Healthcare MCP)
  - Connections owned entirely by each agent container via `MCPStreamableHTTPTool` — no Foundry Tool MCP registration required
  - DeepSense CloudFront requires `User-Agent: claude-code/1.0` header (a routing constraint of the MCP server, not a model config) — injected via shared `httpx.AsyncClient`
  - All agents use `AzureOpenAIResponsesClient` with gpt-5.4 on Microsoft Foundry
  - MCP URLs configured via env vars in `agent.yaml` (or `.env` locally) — no code changes needed to point to different servers
</details>

<details>
  <summary><b>Gate-based decision rubric</b></summary>

  - Three sequential gates: Provider → Codes → Medical Necessity
  - LENIENT mode: only APPROVE or PEND — never DENY
  - Per-criterion MET/NOT_MET/INSUFFICIENT assessment with confidence scoring
  - Configurable: switch to STRICT mode (adds DENY) via configuration toggle
</details>

<details>
  <summary><b>Human-in-the-loop decision panel</b></summary>

  - Accept or Override the AI recommendation with documented rationale
  - Override traceability: flows to notification letters, audit PDF, and API response
  - Authorization number generation (PA-YYYYMMDD-XXXXX)
  - PDF notification letters (approval and pend) with clinical justification data
  - All four agents visible in tabbed Agent Details: Compliance checklist, Clinical extraction (with low-confidence banner), Coverage criteria (including specialty-procedure match), and **Synthesis** gate pipeline + weighted confidence breakdown + disclaimer
</details>

<details>
  <summary><b>Audit and compliance</b></summary>

  - 10-item compliance checklist with blocking/non-blocking classification; items 9 (NCCI bundling risk) and 10 (service type classification) are new domain-aware improvements over the baseline Anthropic skill
  - Provider Specialty-Procedure Appropriateness as a required, auditable `criteria_assessment` entry in the Coverage Agent — sourced from NPI Registry taxonomy
  - Per-criterion confidence scoring with weighted formula (40% criteria + 30% extraction + 20% compliance + 10% policy)
  - `synthesis_audit_trail` with `gate_results` and `confidence_components` surfaced in the frontend Synthesis tab
  - 8-section audit justification document (Markdown + color-coded PDF)
  - Diagnosis-Policy Alignment as a required auditable criterion
  - Complete data source attribution and timestamp tracking
  - Section 9 added on clinician override with full override record
</details>

<details>
  <summary><b>Real-time progress streaming</b></summary>

  - SSE (Server-Sent Events) for live progress updates
  - Phase timeline with per-agent status cards and elapsed timer
  - 9 progress events across 5 phases (preflight → phase_1 → phase_2 → phase_3 → phase_4)
</details>

<details>
  <summary><b>Observability</b></summary>

  - Azure Application Insights integration via OpenTelemetry
  - Custom phase spans with semantic attributes (recommendation, confidence, agent status)
  - Microsoft Foundry hosted agents provide native runtime and evaluation visibility when hosted mode is enabled
  - Application Map, Transaction Search, Live Metrics, and Performance views
</details>

---

<a id="quick-deploy"></a>
## <img src="./docs/images/readme/quick-deploy.svg" width="48" /> Quick deploy

### How to install or deploy

Follow the quick deploy steps on the deployment guide to deploy this solution to your own Azure subscription.

> [!IMPORTANT]
> This solution accelerator requires **Azure Developer CLI (azd) version 1.18.0 or higher** for Azure deployment. Please ensure you have the latest version installed before proceeding. [Download azd here](https://learn.microsoft.com/en-us/azure/developer/azure-developer-cli/install-azd).

[Click here to launch the deployment guide](./docs/DeploymentGuide.md)

| [![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/microsoft/Prior-Authorization-Multi-Agent-Solution-Accelerator) | [![Open in Dev Containers](https://img.shields.io/static/v1?style=for-the-badge&label=Dev%20Containers&message=Open&color=blue&logo=visualstudiocode)](https://vscode.dev/redirect?url=vscode://ms-vscode-remote.remote-containers/cloneInVolume?url=https://github.com/microsoft/Prior-Authorization-Multi-Agent-Solution-Accelerator) | [![Open in VS Code Web](https://img.shields.io/static/v1?style=for-the-badge&label=VS%20Code%20Web&message=Open&color=blue&logo=visualstudiocode&logoColor=white)](https://vscode.dev/azure/?vscode-azure-exp=foundry&agentPayload=eyJiYXNlVXJsIjogImh0dHBzOi8vcmF3LmdpdGh1YnVzZXJjb250ZW50LmNvbS9taWNyb3NvZnQvUHJpb3ItQXV0aG9yaXphdGlvbi1NdWx0aS1BZ2VudC1Tb2x1dGlvbi1BY2NlbGVyYXRvci9yZWZzL2hlYWRzL21haW4vaW5mcmEvdnNjb2RlX3dlYiIsICJpbmRleFVybCI6ICIvaW5kZXguanNvbiIsICJ2YXJpYWJsZXMiOiB7ImFnZW50SWQiOiAiIiwgImNvbm5lY3Rpb25TdHJpbmciOiAiIiwgInRocmVhZElkIjogIiIsICJ1c2VyTWVzc2FnZSI6ICIiLCAicGxheWdyb3VuZE5hbWUiOiAiIiwgImxvY2F0aW9uIjogIiIsICJzdWJzY3JpcHRpb25JZCI6ICIiLCAicmVzb3VyY2VJZCI6ICIiLCAicHJvamVjdFJlc291cmNlSWQiOiAiIiwgImVuZHBvaW50IjogIiJ9LCAiY29kZVJvdXRlIjogWyJhaS1wcm9qZWN0cy1zZGsiLCAicHl0aG9uIiwgImRlZmF1bHQtYXp1cmUtYXV0aCIsICJlbmRwb2ludCJdfQ==) |
|---|---|---|

> [!TIP]
> All buttons open the same dev environment (devcontainer) with `azd`, Azure CLI, Docker, and Node pre-installed. Once inside, you choose your runtime mode:
>
> | Goal | Command | Runtime mode |
> |------|---------|-------------|
> | **Deploy to Azure** (recommended) | `azd up` | **Foundry Hosted Agent mode** — agents run as Foundry-managed containers; only the backend + frontend land in your Azure Container Apps |
> | **Run everything locally** | `docker compose up` | **Docker Compose mode** — all 4 agent containers + backend + frontend run on your local machine; no Azure deployment needed |
>
> The **Quick Deploy** path described below uses `azd up` → Foundry Hosted Agent mode.

> [!IMPORTANT]
> **Model access required:** GPT-5.4 requires a separate access request before it can be deployed. [Apply for access here](https://aka.ms/OAI/gpt53codexaccess). Deployment will fail if access has not been granted to your subscription.

### Prerequisites and costs

To deploy this solution accelerator, ensure you have access to an [Azure subscription](https://azure.microsoft.com/free/) with the necessary permissions to create resource groups and resources. The **Microsoft Foundry Resource and Project** are automatically provisioned by `azd up`. The solution uses the **Azure OpenAI gpt-5.4** model, which is automatically deployed as part of `azd up` — see [Azure OpenAI model availability](https://learn.microsoft.com/en-us/azure/ai-services/openai/concepts/models) for details.

> [!WARNING]
> **Region and deployment type:** gpt-5.4 is available in **East US 2** (`eastus2`) and **Sweden Central** (`swedencentral`). During `azd up`, you will be prompted to choose a deployment type:
>
> | Deployment Type | Data Residency | Regions |
> |----------------|---------------|---------|
> | **GlobalStandard** (default) | No guarantee — data may be processed in any region | East US 2, Sweden Central |
> | **DataZoneStandard** | Data stays within geographic zone (US/EU) | East US 2 **only** |
>
> **Sweden Central does NOT support DataZoneStandard.** If you need data residency, select East US 2. See [Azure OpenAI model availability](https://learn.microsoft.com/en-us/azure/ai-services/openai/concepts/models) for the latest availability.

Pricing varies per region and usage, so it isn't possible to predict exact costs for your usage. The majority of the Azure resources used in this infrastructure are on usage-based pricing tiers. Use the [Azure pricing calculator](https://azure.microsoft.com/en-us/pricing/calculator) to estimate costs for your subscription.

| Azure Service | Purpose | Pricing |
|--------------|---------|---------|
| [Microsoft Foundry](https://azure.microsoft.com/en-us/pricing/details/ai-foundry/) | Foundry Resource + Project (auto-provisioned) + Azure OpenAI gpt-5.4 inference | [Pricing](https://azure.microsoft.com/en-us/pricing/details/ai-foundry/) |
| [Azure Container Apps](https://azure.microsoft.com/en-us/pricing/details/container-apps/) | Backend (2 CPU / 4Gi, min 1 replica) + frontend hosting | [Pricing](https://azure.microsoft.com/en-us/pricing/details/container-apps/) |
| [Azure Container Registry](https://azure.microsoft.com/en-us/pricing/details/container-registry/) | Docker image storage | [Pricing](https://azure.microsoft.com/en-us/pricing/details/container-registry/) |
| [Azure Application Insights](https://azure.microsoft.com/en-us/pricing/details/monitor/) | Observability and tracing (optional) | [Pricing](https://azure.microsoft.com/en-us/pricing/details/monitor/) |

> [!IMPORTANT]
> To avoid unnecessary costs, remember to take down your deployment if it's no longer in use, either by running `azd down`, deleting the resource group in the Portal, or running `docker compose down` for local deployments.

---

<a id="business-scenario"></a>
## <img src="./docs/images/readme/business-scenario.svg" width="48" /> Business Scenario

|![Prior Authorization Review — Application Interface](./docs/images/readme/interface.png)|
|---|

<br/>

Healthcare organizations processing prior authorization (PA) requests face significant challenges in coordinating complex clinical reviews across multiple departments. They must evaluate medical necessity, verify coverage policies, and produce auditable decisions — often under strict regulatory timelines. Some of the challenges they face include:

- **High volume** — U.S. providers submit ~[300 million PA requests per year](https://www.caqh.org/insights/caqh-index-report) (CAQH Index)
- **Manual, time-consuming reviews** — each request takes [15–20 minutes](https://web.archive.org/web/20240829144735/https://www.ama-assn.org/system/files/prior-authorization-survey.pdf) of clinician and staff time (AMA, 2024)
- **Slow turnaround** — average PA decision takes [5–14 business days](https://www.cms.gov/newsroom/fact-sheets/cms-interoperability-and-prior-authorization-final-rule-cms-0057-f)
- **Inconsistent assessments** — manual reviews are subject to reviewer variability
- **Regulatory pressure** — CMS mandates [electronic PA by 2026–2027](https://www.cms.gov/newsroom/fact-sheets/cms-interoperability-and-prior-authorization-final-rule-cms-0057-f) with 72-hour urgent and 7-day standard response limits (CMS-0057-F)

By using the *Prior Authorization Review — Multi-Agent Solution Accelerator*, organizations can automate these processes, ensuring that all clinical reviews are accurately coordinated, auditable, and executed efficiently.

### Business value
<details>
  <summary>Click to learn more about what value this solution provides</summary>

  - **Reduce review time from 20+ minutes to under 2 minutes** <br/>
  Compliance and Clinical agents run concurrently via parallel execution, dramatically reducing wall-clock time per case.

  - **Ensure consistency and auditability** <br/>
  Gate-based decision rubric with per-criterion MET/NOT_MET/INSUFFICIENT scoring eliminates reviewer variability and produces complete audit trails.

  - **Maintain human oversight** <br/>
  AI produces draft recommendations; human reviewers Accept or Override with documented rationale — every decision is traceable.

  - **Scale without proportional staffing** <br/>
  Stateless API design enables horizontal scaling behind a load balancer. Skills-based architecture lets domain experts update clinical rules without code changes.

  - **Meet regulatory requirements** <br/>
  Automated documentation generation (notification letters, audit PDFs) supports CMS compliance and payer reporting obligations.

</details>

### Use Case
<details>
  <summary>Click to learn more about the prior authorization use case</summary>

  | Scenario | Persona | Challenges | Solution Approach |
  |----------|---------|------------|-------------------|
  | PA intake triage | Utilization Review Nurse | Manually checking demographics, provider credentials, codes, and clinical notes quality for completeness is time-consuming and error-prone. | **Compliance Agent** validates all required documentation in seconds with a 10-item checklist: items 1-7 are blocking; item 9 flags NCCI CPT bundling risk; item 10 classifies service type (Procedure/Medication/Imaging/Device/Therapy/Facility) for downstream routing. |
  | Clinical evidence review | Medical Director | Extracting structured clinical data, validating ICD-10 codes, and searching PubMed for supporting evidence takes 15–30 minutes per case. | **Clinical Reviewer Agent** automates clinical data extraction, code validation, and literature/trial search using MCP-connected healthcare data sources. |
  | Coverage policy evaluation | PA Coordinator | Looking up Medicare NCDs/LCDs, mapping each policy criterion to clinical evidence, and documenting medical necessity assessments is manual and inconsistent. | **Coverage Agent** searches CMS coverage databases, verifies provider credentials, and produces auditable MET/NOT_MET/INSUFFICIENT criterion mappings. |
  | Final decision synthesis | Clinical Reviewer | Combining findings from multiple reviewers into a consistent, auditable recommendation with confidence scoring requires significant coordination. | **Orchestrator + Synthesis** evaluates a gate-based rubric (Provider → Codes → Medical Necessity), produces a recommendation with confidence scores, and generates notification letters and audit PDFs. |

</details>

---

<a id="supporting-documentation"></a>
## <img src="./docs/images/readme/supporting-documentation.svg" width="48" /> Supporting documentation

| Document | Description |
|----------|-------------|
| [Deployment Guide](./docs/DeploymentGuide.md) | Step-by-step deployment instructions — Docker Compose, local development, Azure Container Apps, prerequisites, environment configuration, troubleshooting |
| [Architecture](./docs/architecture.md) | Detailed hosted-agent-ready architecture, runtime modes, MCP integration, agent details, decision rubric, confidence scoring, and audit justification |
| [API Reference](./docs/api-reference.md) | Full REST API documentation — review, decision, per-agent endpoints, request/response schemas, SSE events, error codes |
| [Foundry Hosted Agents Plan](./docs/foundry-hosted-agents-plan.md) | Saved migration plan for the lower-risk Foundry hosted-agent architecture (frontend ACA + backend/orchestrator ACA + 4 hosted agents) |
| [Extending the Application](./docs/extending.md) | Step-by-step guides for adding new agents, MCP servers, changing the decision rubric, customizing notification letters |
| [Technical Notes](./docs/technical-notes.md) | Windows SDK patches, MCP header injection, hosted-agent dispatch, structured output, observability, and known limitations |
| [Troubleshooting](./docs/troubleshooting.md) | Common issues and fixes — CLI failures, hosted-agent config/auth problems, connection errors, truncated responses, and Foundry trace issues |
| [Production Migration](./docs/production-migration.md) | PostgreSQL schema, Azure Blob Storage layout, migration steps, environment variables, what not to change |

### Customization areas

This solution accelerator is designed to be extended:

| Area | What to customize | Guide |
|------|-------------------|-------|
| **Data persistence** | Replace in-memory store with PostgreSQL / Cosmos DB | [Production Migration](./docs/production-migration.md) |
| **Authentication** | Add identity management and RBAC | Custom implementation |
| **Payer-specific policies** | Extend with commercial and MA plan rules | [Extending](./docs/extending.md) |
| **EHR/EMR integration** | Connect via FHIR or HL7 interfaces | Custom implementation |
| **New agents** | Add Pharmacy Benefits, Financial Review, etc. | [Extending](./docs/extending.md) |
| **New MCP servers** | Add CPT validator, drug formulary, etc. | [Extending](./docs/extending.md) |
| **Decision rubric** | Switch from LENIENT to STRICT mode | [Extending](./docs/extending.md) |
| **Notification letters** | Match your organization's letterhead format | [Extending](./docs/extending.md) |
| **Compliance & security** | HIPAA-compliant infrastructure, encryption | Custom implementation |
| **Scalability** | Azure Container Apps, Kubernetes | [Deployment Guide](./docs/DeploymentGuide.md) |

### Security guidelines

This solution accelerator handles **Protected Health Information (PHI)** and clinical data. Security best practices are critical for any deployment.

**This project uses keyless authentication throughout — no API keys, passwords, or connection strings are stored anywhere.** All Azure resource access (Microsoft Foundry, Azure Container Registry, Azure Monitor) is authenticated via [`DefaultAzureCredential`](https://learn.microsoft.com/azure/developer/python/sdk/authentication/credential-chains#defaultazurecredential-overview):

| Environment | Credential used | How it's granted |
|---|---|---|
| Azure (production) | System-assigned [Managed Identity](https://learn.microsoft.com/entra/identity/managed-identities-azure-resources/overview) on each Container App; deployer user identity | Bicep role assignments at deploy time (`CognitiveServicesOpenAIUser` for backend, `Azure AI User` for deployer) |
| Local / Codespaces | Azure Developer CLI token (`azd auth login`) or Azure CLI token (`az login`) | Developer's own authenticated session |

Because there are no API keys, there is nothing to rotate, leak, or accidentally commit. To ensure continued best practices in your own repository, we recommend enabling [GitHub secret scanning](https://docs.github.com/code-security/secret-scanning/about-secret-scanning) to catch any credentials that might be inadvertently introduced.

You may want to consider additional security measures, such as:

* Enabling [Microsoft Defender for Cloud](https://learn.microsoft.com/azure/defender-for-cloud/) to secure your Azure resources.
* Protecting the Azure Container Apps instance with a [firewall](https://learn.microsoft.com/azure/container-apps/waf-app-gateway) and/or [Virtual Network](https://learn.microsoft.com/azure/container-apps/networking?tabs=workload-profiles-env%2Cazure-cli).
* Enabling [encryption at rest](https://learn.microsoft.com/azure/security/fundamentals/encryption-atrest) for all data stores containing PHI.
* Implementing role-based access control (RBAC) to restrict who can submit, review, and override prior authorization decisions.
* Ensuring HIPAA compliance by signing a [Business Associate Agreement (BAA)](https://learn.microsoft.com/azure/compliance/offerings/offering-hipaa-us) with Microsoft for production workloads.

<br/>

### Cross references

Check out related solution accelerators from Microsoft

| Solution Accelerator | Description |
|---|---|
| [Multi-Agent Custom Automation Engine](https://github.com/microsoft/Multi-Agent-Custom-Automation-Engine-Solution-Accelerator) | Build AI-driven orchestration systems that coordinate multiple specialized agents for complex business process automation |
| [AutoAuth](https://github.com/microsoft/autoauth) | Streamlining prior authorization with the AutoAuth Framework and Azure AI |
| [Document Knowledge Mining](https://github.com/microsoft/Document-Knowledge-Mining-Solution-Accelerator) | Extract structured information from unstructured documents using AI — applicable to clinical notes and medical records |
| [Conversation Knowledge Mining](https://github.com/microsoft/Conversation-Knowledge-Mining-Solution-Accelerator) | Derive insights from volumes of conversational data using generative AI — applicable to patient-provider interactions |

<br/>

Want to get familiar with Microsoft's AI and Data Engineering best practices? Check out our playbooks to learn more:

| Playbook | Description |
|:---|:---|
| [AI&nbsp;playbook](https://learn.microsoft.com/en-us/ai/playbook/) | The Artificial Intelligence (AI) Playbook provides enterprise software engineers with solutions, capabilities, and code developed to solve real-world AI problems. |
| [Data&nbsp;playbook](https://learn.microsoft.com/en-us/data-engineering/playbook/understanding-data-playbook) | The data playbook provides enterprise software engineers with solutions which contain code developed to solve real-world problems. |

---

## Provide feedback

Have questions, find a bug, or want to request a feature? [Submit a new issue](https://github.com/microsoft/Prior-Authorization-Multi-Agent-Solution-Accelerator/issues) on this repo and we'll connect.

<br/>

## Responsible AI Transparency FAQ
Please refer to [Transparency FAQ](./TRANSPARENCY_FAQ.md) for responsible AI transparency details of this solution accelerator.

<br/>

## Disclaimers
This release is an artificial intelligence (AI) system that generates text based on user input. The text generated by this system may include ungrounded content, meaning that it is not verified by any reliable source or based on any factual data. The data included in this release is synthetic, meaning that it is artificially created by the system and may contain factual errors or inconsistencies. Users of this release are responsible for determining the accuracy, validity, and suitability of any content generated by the system for their intended purposes. Users should not rely on the system output as a source of truth or as a substitute for human judgment or expertise.

This release only supports English language input and output. Users should not attempt to use the system with any other language or format. The system output may not be compatible with any translation tools or services, and may lose its meaning or coherence if translated.

This release does not reflect the opinions, views, or values of Microsoft Corporation or any of its affiliates, subsidiaries, or partners. The system output is solely based on the system's own logic and algorithms, and does not represent any endorsement, recommendation, or advice from Microsoft or any other entity. Microsoft disclaims any liability or responsibility for any damages, losses, or harms arising from the use of this release or its output by any user or third party.

This release does not provide any financial advice, legal advice and is not designed to replace the role of qualified client advisors in appropriately advising clients. Users should not use the system output for any financial decisions, legal guidance or transactions, and should consult with a professional financial  advisor and or legal advisor as appropriate before taking any action based on the system output. Microsoft is not a financial institution or a fiduciary, and does not offer any financial products or services through this release or its output.

This release is intended as a proof of concept only, and is not a finished or polished product. It is not intended for commercial use or distribution, and is subject to change or discontinuation without notice. Any planned deployment of this release or its output should include comprehensive testing and evaluation to ensure it is fit for purpose and meets the user's requirements and expectations. Microsoft does not guarantee the quality, performance, reliability, or availability of this release or its output, and does not provide any warranty or support for it.

This Software requires the use of third-party components which are governed by separate proprietary or open-source licenses as identified below, and you must comply with the terms of each applicable license in order to use the Software. You acknowledge and agree that this license does not grant you a license or other right to use any such third-party proprietary or open-source components.

To the extent that the Software includes components or code used in or derived from Microsoft products or services, including without limitation Microsoft Azure Services (collectively, "Microsoft Products and Services"), you must also comply with the Product Terms applicable to such Microsoft Products and Services. You acknowledge and agree that the license governing the Software does not grant you a license or other right to use Microsoft Products and Services. Nothing in the license or this ReadMe file will serve to supersede, amend, terminate or modify any terms in the Product Terms for any Microsoft Products and Services.

You must also comply with all domestic and international export laws and regulations that apply to the Software, which include restrictions on destinations, end users, and end use. For further information on export restrictions, visit https://aka.ms/exporting.

You acknowledge that the Software and Microsoft Products and Services (1) are not designed, intended or made available as a medical device(s), and (2) are not designed or intended to be a substitute for professional medical advice, diagnosis, treatment, or judgment and should not be used to replace or as a substitute for professional medical advice, diagnosis, treatment, or judgment. Customer is solely responsible for displaying and/or obtaining appropriate consents, warnings, disclaimers, and acknowledgements to end users of Customer's implementation of the Online Services.

You acknowledge the Software is not subject to SOC 1 and SOC 2 compliance audits. No Microsoft technology, nor any of its component technologies, including the Software, is intended or made available as a substitute for the professional advice, opinion, or judgment of a certified financial services professional. Do not use the Software to replace, substitute, or provide professional financial advice or judgment.

BY ACCESSING OR USING THE SOFTWARE, YOU ACKNOWLEDGE THAT THE SOFTWARE IS NOT DESIGNED OR INTENDED TO SUPPORT ANY USE IN WHICH A SERVICE INTERRUPTION, DEFECT, ERROR, OR OTHER FAILURE OF THE SOFTWARE COULD RESULT IN THE DEATH OR SERIOUS BODILY INJURY OF ANY PERSON OR IN PHYSICAL OR ENVIRONMENTAL DAMAGE (COLLECTIVELY, "HIGH-RISK USE"), AND THAT YOU WILL ENSURE THAT, IN THE EVENT OF ANY INTERRUPTION, DEFECT, ERROR, OR OTHER FAILURE OF THE SOFTWARE, THE SAFETY OF PEOPLE, PROPERTY, AND THE ENVIRONMENT ARE NOT REDUCED BELOW A LEVEL THAT IS REASONABLY, APPROPRIATE, AND LEGAL, WHETHER IN GENERAL OR IN A SPECIFIC INDUSTRY. BY ACCESSING THE SOFTWARE, YOU FURTHER ACKNOWLEDGE THAT YOUR HIGH-RISK USE OF THE SOFTWARE IS AT YOUR OWN RISK.
