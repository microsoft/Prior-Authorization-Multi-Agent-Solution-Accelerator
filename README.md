# Prior Authorization Review — Multi-Agent Solution Accelerator

A **multi-agent** AI-assisted prior authorization (PA) review application built
with the **Microsoft Agent Framework**, **Claude Agent SDK**, and **Anthropic
& DeepSense Healthcare MCP Servers**. Three specialized agents — Compliance, Clinical
Reviewer, and Coverage — work in parallel and sequence, coordinated by an
orchestrator that applies a gate-based decision rubric and produces a final
recommendation with confidence scoring and an audit justification document.

Incorporates best practices from the
[Anthropic prior-auth-review-skill](https://github.com/anthropics/healthcare/tree/main/prior-auth-review-skill):
LENIENT mode decision policy, per-criterion MET/NOT_MET/INSUFFICIENT evaluation,
confidence scoring, progressive gate evaluation, and structured audit trails.

<div align="center">

[**SOLUTION OVERVIEW**](#solution-overview) \| [**QUICK DEPLOY**](#quick-deploy) \| [**BUSINESS SCENARIO**](#business-scenario) \| [**SUPPORTING DOCUMENTATION**](#supporting-documentation)

</div>

> **Disclaimer:** This is an AI-assisted triage tool. All recommendations are
> drafts that require human clinical review before any authorization decision
> is finalized. Coverage policies reflect Medicare LCDs/NCDs only — commercial
> and Medicare Advantage plans may differ.

> **Solution Accelerator Notice:** This project is a **solution accelerator** —
> not a production-ready application. It is designed as a reference architecture
> and working prototype that customers can use as a starting point to build,
> customize, and extend their own prior authorization solution based on their
> specific requirements. Microsoft does not provide production support for this
> accelerator. Customers are responsible for testing, validation, regulatory
> compliance, and production deployment within their own environment.

> **Note:** With any AI solutions you create using these templates, you are
> responsible for assessing all associated risks and for complying with all
> applicable laws and safety standards. Learn more in the transparency documents
> for [Agent Service](https://learn.microsoft.com/en-us/azure/ai-foundry/responsible-ai/agents/transparency-note)
> and [Agent Framework](https://github.com/microsoft/agent-framework/blob/main/TRANSPARENCY_FAQ.md).

---

<a id="solution-overview"></a>
## <img src="./docs/images/readme/solution-overview.svg" width="48" /> Solution overview

This solution leverages **Microsoft Foundry**, **Microsoft Agent Framework**,
**Claude Agent SDK**, **Azure Application Insights**, and **Anthropic &
DeepSense Healthcare MCP Servers** to create an intelligent prior authorization review pipeline where
specialized AI agents work together to validate, assess, and synthesize PA
decisions with full audit transparency.

### Solution architecture

|![Solution Architecture](./docs/images/readme/solution-architecture.png)|
|---|

### Agentic architecture

The orchestrator coordinates four phases with three specialized agents:

|![Agentic Architecture](./docs/images/readme/agentic-architecture.png)|
|---|

<br/>

### Additional resources

- [Anthropic Healthcare MCP Marketplace](https://github.com/anthropics/healthcare)
- [Prior Auth Review Skill](https://github.com/anthropics/healthcare/tree/main/prior-auth-review-skill)
- [Build AI Agents with Claude Agent SDK and Microsoft Agent Framework](https://devblogs.microsoft.com/semantic-kernel/build-ai-agents-with-claude-agent-sdk-and-microsoft-agent-framework/)
- [Microsoft Agent Framework — Claude Agent](https://learn.microsoft.com/en-us/agent-framework/user-guide/agents/agent-types/anthropic-agent)
- [Microsoft Foundry Claude Models](https://learn.microsoft.com/en-us/azure/ai-foundry/foundry-models/how-to/use-foundry-models-claude)
- [Claude Prior Auth Review Tutorial](https://claude.com/resources/tutorials/how-to-use-the-prior-auth-review-sample-skill-with-claude-2ggy8)
- [Model Context Protocol (MCP)](https://modelcontextprotocol.io/)
- [Claude Agent SDK](https://platform.claude.com/docs/en/agent-sdk/overview)
- [Anthropic Agent Skills](https://platform.claude.com/docs/en/docs/agents-and-tools/agent-skills/overview)

<br/>

### Key features

<details open>
  <summary><b>Multi-agent parallel execution</b></summary>

  - Compliance and Clinical agents run concurrently via `asyncio.gather`, reducing wall-clock time from 20+ minutes to under 2 minutes per case
  - Coverage Agent runs sequentially after clinical findings are available
  - Four-phase pipeline: Pre-flight → Parallel → Sequential → Synthesis → Audit
</details>

<details>
  <summary><b>Skills-based architecture</b></summary>

  - Agent behaviors defined in SKILL.md files — domain experts can update clinical rules without code changes
  - Dual-mode support: skills-based (default) or prompt-based (fallback), controlled by `USE_SKILLS` env var
  - Shared reference files for decision policy rubric and JSON output schemas
</details>

<details>
  <summary><b>MCP-powered data access</b></summary>

  - Five remote MCP servers: NPI Registry, ICD-10 Codes, CMS Coverage, Clinical Trials (DeepSense), PubMed (Anthropic)
  - No custom MCP client needed — Microsoft Agent Framework's Claude SDK handles it natively
  - Model-agnostic: `MCPStreamableHTTPTool` enables MCP access from any LLM
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
</details>

<details>
  <summary><b>Audit and compliance</b></summary>

  - 8-section audit justification document (Markdown + color-coded PDF)
  - Per-criterion confidence scoring with weighted formula
  - Complete data source attribution and timestamp tracking
  - Diagnosis-Policy Alignment as a required auditable criterion
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
  - Foundry agent registration for centralized fleet management
  - Application Map, Transaction Search, Live Metrics, and Performance views
</details>

---

<a id="quick-deploy"></a>
## <img src="./docs/images/readme/quick-deploy.svg" width="48" /> Quick deploy

### How to install or deploy

Follow the quick deploy steps on the deployment guide to deploy this solution to your own Azure subscription.

> **Note:** This solution accelerator requires **Azure Developer CLI (azd) version 1.18.0 or higher** for Azure deployment. Please ensure you have the latest version installed before proceeding. [Download azd here](https://learn.microsoft.com/en-us/azure/developer/azure-developer-cli/install-azd).

[Click here to launch the deployment guide](./docs/DeploymentGuide.md)

| [![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/amitmukh/prior-auth-maf) | [![Open in Dev Containers](https://img.shields.io/static/v1?style=for-the-badge&label=Dev%20Containers&message=Open&color=blue&logo=visualstudiocode)](https://vscode.dev/redirect?url=vscode://ms-vscode-remote.remote-containers/cloneInVolume?url=https://github.com/amitmukh/prior-auth-maf) | [![Open in Visual Studio Code Web](https://img.shields.io/static/v1?style=for-the-badge&label=Visual%20Studio%20Code%20(Web)&message=Open&color=blue&logo=visualstudiocode&logoColor=white)](https://vscode.dev/azure/?vscode-azure-exp=foundry&agentPayload=eyJiYXNlVXJsIjogImh0dHBzOi8vcmF3LmdpdGh1YnVzZXJjb250ZW50LmNvbS9hbWl0bXVraC9wcmlvci1hdXRoLW1hZi9yZWZzL2hlYWRzL21haW4vaW5mcmEvdnNjb2RlX3dlYiIsICJpbmRleFVybCI6ICIvaW5kZXguanNvbiIsICJ2YXJpYWJsZXMiOiB7ImFnZW50SWQiOiAiIiwgImNvbm5lY3Rpb25TdHJpbmciOiAiIiwgInRocmVhZElkIjogIiIsICJ1c2VyTWVzc2FnZSI6ICIiLCAicGxheWdyb3VuZE5hbWUiOiAiIiwgImxvY2F0aW9uIjogIiIsICJzdWJzY3JpcHRpb25JZCI6ICIiLCAicmVzb3VyY2VJZCI6ICIiLCAicHJvamVjdFJlc291cmNlSWQiOiAiIiwgImVuZHBvaW50IjogIiJ9LCAiY29kZVJvdXRlIjogWyJhaS1wcm9qZWN0cy1zZGsiLCAicHl0aG9uIiwgImRlZmF1bHQtYXp1cmUtYXV0aCIsICJlbmRwb2ludCJdfQ==) |
|---|---|---|

> ⚠️ **Important: Check Microsoft Foundry Quota Availability**
> <br/>To ensure Claude models are available in your target region, please check the [model availability instructions](./docs/DeploymentGuide.md#13-claude-model-access-pre-check) before you deploy the solution.

### Prerequisites & Costs

To deploy this solution accelerator, ensure you have access to an [Azure subscription](https://azure.microsoft.com/free/) with the necessary permissions to create resource groups and resources. The **AI Foundry Hub and Project** are automatically provisioned by `azd up`. After deployment, you will deploy the **Claude model** from the model catalog — see [Use Foundry Models Claude](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/how-to/use-foundry-models-claude) for details.

> ⚠️ **Region requirement:** Claude models on Microsoft Foundry are currently available only in **East US 2** and **Sweden Central**. You must deploy to one of these regions. See [Use Foundry Models Claude](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/how-to/use-foundry-models-claude) for the latest region availability.

Pricing varies per region and usage, so it isn't possible to predict exact costs for your usage. The majority of the Azure resources used in this infrastructure are on usage-based pricing tiers. Use the [Azure pricing calculator](https://azure.microsoft.com/en-us/pricing/calculator) to estimate costs for your subscription.

| Azure Service | Purpose | Pricing |
|--------------|---------|---------|
| [Microsoft Foundry](https://azure.microsoft.com/en-us/pricing/details/ai-foundry/) | AI Foundry Hub + Project (auto-provisioned) + Claude model inference | [Pricing](https://azure.microsoft.com/en-us/pricing/details/ai-foundry/) |
| [Azure Container Apps](https://azure.microsoft.com/en-us/pricing/details/container-apps/) | Backend + frontend hosting | [Pricing](https://azure.microsoft.com/en-us/pricing/details/container-apps/) |
| [Azure Container Registry](https://azure.microsoft.com/en-us/pricing/details/container-registry/) | Docker image storage | [Pricing](https://azure.microsoft.com/en-us/pricing/details/container-registry/) |
| [Azure Application Insights](https://azure.microsoft.com/en-us/pricing/details/monitor/) | Observability and tracing (optional) | [Pricing](https://azure.microsoft.com/en-us/pricing/details/monitor/) |

> ⚠️ **Important:** To avoid unnecessary costs, remember to take down your deployment if it's no longer in use, either by running `azd down`, deleting the resource group in the Portal, or running `docker compose down` for local deployments.

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
  | PA intake triage | Utilization Review Nurse | Manually checking demographics, provider credentials, codes, and clinical notes quality for completeness is time-consuming and error-prone. | **Compliance Agent** validates all required documentation in seconds, flagging missing or insufficient fields before clinical review begins. |
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
| [Architecture](./docs/architecture.md) | Detailed multi-agent architecture, MCP integration, agent details, decision rubric, confidence scoring, audit justification, skills-based architecture |
| [API Reference](./docs/api-reference.md) | Full REST API documentation — review, decision, per-agent endpoints, request/response schemas, SSE events, error codes |
| [Extending the Application](./docs/extending.md) | Step-by-step guides for adding new agents, MCP servers, changing the decision rubric, customizing notification letters |
| [Technical Notes](./docs/technical-notes.md) | Windows SDK patches, MCP header injection, structured output, prompt caching, observability, Foundry agent registration, known limitations |
| [Troubleshooting](./docs/troubleshooting.md) | Common issues and fixes — CLI failures, empty responses, connection errors, truncated responses, Foundry trace issues |
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

All API keys and connection strings are stored in a local `.env` file that is excluded from source control via `.gitignore`. For Azure deployments, we recommend using [Azure Key Vault](https://learn.microsoft.com/azure/key-vault/general/overview) to manage secrets and [Managed Identity](https://learn.microsoft.com/entra/identity/managed-identities-azure-resources/overview) to authenticate between Azure resources without storing credentials in code.

To ensure continued best practices in your own repository, we recommend that anyone creating solutions based on our templates ensure that the [GitHub secret scanning](https://docs.github.com/code-security/secret-scanning/about-secret-scanning) setting is enabled.

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
| [Document Knowledge Mining](https://github.com/microsoft/Document-Knowledge-Mining-Solution-Accelerator) | Extract structured information from unstructured documents using AI — applicable to clinical notes and medical records |
| [Conversation Knowledge Mining](https://github.com/microsoft/Conversation-Knowledge-Mining-Solution-Accelerator) | Derive insights from volumes of conversational data using generative AI — applicable to patient-provider interactions |

<br/>

💡 Want to get familiar with Microsoft's AI and Data Engineering best practices? Check out our playbooks to learn more

| Playbook | Description |
|:---|:---|
| [AI&nbsp;playbook](https://learn.microsoft.com/en-us/ai/playbook/) | The Artificial Intelligence (AI) Playbook provides enterprise software engineers with solutions, capabilities, and code developed to solve real-world AI problems. |
| [Data&nbsp;playbook](https://learn.microsoft.com/en-us/data-engineering/playbook/understanding-data-playbook) | The data playbook provides enterprise software engineers with solutions which contain code developed to solve real-world problems. |

---

## Provide feedback

Have questions, find a bug, or want to request a feature? [Submit a new issue](https://github.com/amitmukh/prior-auth-maf/issues) on this repo and we'll connect.

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
