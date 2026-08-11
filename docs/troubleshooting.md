# Troubleshooting

## `POST /api/review` returns `422 Unprocessable Entity`

The API rejected the request before the multi-agent pipeline ran (issue #28).
This is the canonical FastAPI/Pydantic validation envelope and means **no
Hosted Agent V2 capacity was consumed** — the request never reached the
orchestrator.

**Response body shape:**

```json
{
  "detail": [
    {
      "type": "value_error",
      "loc": ["body", "<field>"],
      "msg": "Value error, <human-readable reason>",
      "input": "<offending value>"
    }
  ]
}
```

**Common causes and fixes:**

| `loc` field | Likely `msg` | Fix |
|---|---|---|
| `body.patient_dob` | `must be a valid past date in YYYY-MM-DD format` | Send DOB as ISO date, e.g. `1958-03-15`. Free-text and `MM-DD-YYYY` are rejected. |
| `body.patient_dob` | `must not be in the future` | DOB cannot be later than today. |
| `body.diagnosis_codes` | `at least one diagnosis_code is required` | Send a non-empty array; entries that are blank/whitespace-only are dropped before the count check. |
| `body.diagnosis_codes` | `invalid ICD-10 diagnosis code: '<code>'` | Use ICD-10 format, e.g. `R91.1`, `M17.11`, `J18.9`. U-prefix codes (e.g. `U07.1`) are reserved by WHO and rejected. |
| `body.procedure_codes` | `at least one procedure_code is required` | Send a non-empty array. |
| `body.procedure_codes` | `invalid CPT/HCPCS procedure code: '<code>'` | Use 5-digit CPT (`27447`, `31628`), CPT Cat-III (`0028T`), or HCPCS Level II (`J3490`). |

The same rules apply to `POST /api/review/stream` and the four
`POST /api/agents/*` endpoints (which nest `PriorAuthRequest`).

The frontend `UploadForm` mirrors these rules with HTML5 `pattern`/`max`
attributes and a pre-submit guard, then renders the backend's
`detail[].msg` strings in the destructive `<Alert>` banner. If you see a
422 in the browser console but no banner update, check that
`frontend/lib/api.ts` is on the version that includes the `formatApiError`
helper.

---

## Hosted agent returns `424 session_not_ready`

The backend logs an error like:

```
Foundry Hosted Agent <name> call failed: Error code: 424 - {'error': {
  'code': 'session_not_ready',
  'message': "Session '...' did not become ready within the expected timeout.
              Please check your application logs and verify the /readiness
              endpoint returns HTTP 200. ..."
}}
```

This means the per-session agent container started but its `/readiness`
probe never returned HTTP 200 within the bootstrap window, so Foundry
cancelled the session. The agent process almost always crashed during
import or `main()` setup before `ResponsesHostServer(...).run()` could
bind to port 8088.

**Step 1 — stream the failed session's container logs:**

```bash
# 1. Trigger a fresh session and capture its ID
azd ai agent invoke <agent-name> --new-session --no-prompt "ping"

# 2. Stream the per-session logs (max --tail 300)
azd ai agent monitor <agent-name> --no-prompt \
    --session-id <session-id-from-step-1> --tail 300
```

The stderr lines reveal the import-time exception. Common causes:

| Stderr signature | Root cause | Fix |
|---|---|---|
| `PermissionError: [Errno 13] Permission denied: '/home/session/.sessions'` | Foundry injects `HOME=/home/session` and mounts the per-session state volume there as root. `ResponsesHostServer` creates `$HOME/.sessions` during startup, so a non-root `USER` in the Dockerfile gets `EACCES` and exits. Creating and `chown`-ing the directory at build time does **not** help — the runtime mount replaces it. | Remove the `USER` directive so the agent container runs as root (see all 4 `agents/*/Dockerfile`). |
| `TypeError: SkillsProvider.__init__() got an unexpected keyword argument 'skill_paths'` | `agent-framework-core` 1.2.0 moved file-based construction to `SkillsProvider.from_paths(...)`; the old kwarg form is rejected. | Use `SkillsProvider.from_paths("./skills")` (see all 4 `agents/*/main.py`). |
| `... azure.ai.agentserver.core._tracing ... InstrumentationKey` parse error | Platform-injected `APPLICATIONINSIGHTS_CONNECTION_STRING` is malformed in the current preview. | Set `OTEL_CONNECTION_STRING` in `agent.yaml` and have `main.py` overwrite the broken value (already wired in this repo). |
| `azure.identity ... DefaultAzureCredential failed to retrieve a token` | `DefaultAzureCredential` is too slow on the Foundry IMDS endpoint without a `client_id` hint. | Bind `ManagedIdentityCredential(client_id=os.environ["AZURE_CLIENT_ID"])` first via `ChainedTokenCredential` (already wired). |
| Import error from a transitive `agent-framework-*` package | Pinned package set drifted from the refreshed preview SDK. | Confirm pins: `agent-framework-core>=1.13.0,<2`, `agent-framework-foundry>=1.10.4,<2`, `agent-framework-foundry-hosting>=1.0.0b260730,<2`, `azure-ai-agentserver-core>=2.0.0,<3`, then `azd deploy <agent-name>`. |

**Step 2 — redeploy and verify:**

```bash
azd deploy <agent-name> --no-prompt
azd ai agent invoke <agent-name> --new-session --no-prompt "ping"
```

A healthy agent returns its structured `response_format` JSON. If you
still see 424 after the redeploy, capture a fresh session log
(`azd ai agent monitor`) — the platform always cleans up the failing
session after the timeout, so you must re-invoke to get a usable session
ID for log streaming.

---

## Agent returns "An internal server error occurred" (protocol version mismatch)

`azd ai agent invoke` gets past readiness but fails, and the session log shows:

```
RuntimeError: The hosted environment is running on protocol 1.0.0, but the agent
requires protocol 2.0.0. Please upgrade your agent protocol to 2.0.0 in
`agent.manifest.yaml` or `agent.yaml`, or downgrade the
`agent-framework-foundry-hosting` package to `1.0.0a260625` or before.
```

**Cause:** `agent-framework-foundry-hosting` `1.0.0b260730` and later require
responses protocol 2.0.0, but the agent manifest still declares 1.0.0.

**Fix:** set the protocol version in every `agents/*/agent.yaml`, then redeploy:

```yaml
protocols:
  - protocol: responses
    version: "2.0.0"
```

```bash
azd deploy --all --no-prompt
```

---

## Backend reports "Agent &lt;name&gt; returned empty output"

The review completes but every agent section is filled with
`"Not evaluated by agent"` placeholders, and `agent_results.<agent>.error`
reads `Agent <name> returned empty output`. Invoking the agent directly shows
the response ending in an `mcp_approval_request` item with no final message.

**Cause:** `agent-framework-core` registers `SkillsProvider` tools with
`approval_mode="always_require"` by default. The agent asks for approval to run
`load_skill` and stops; nothing approves it in an unattended server flow, so no
text is ever produced.

**Fix:** opt the read-only skill tools out of approval in each
`agents/*/main.py`:

```python
skills_provider = SkillsProvider.from_paths(
    str(Path(__file__).parent / "skills"),
    disable_load_skill_approval=True,
    disable_read_skill_resource_approval=True,
)
```

`run_skill_script` intentionally still requires approval — none of the skills in
this accelerator ship a script. Redeploy with `azd deploy --all --no-prompt`.

---

## MAF Agent Fails to Start / "Failed to acquire Foundry auth token"

The backend logs show an auth error when trying to invoke a hosted agent.

**Cause:** `DefaultAzureCredential` cannot acquire a token for the Foundry Responses API.

**Fix:**

1. **Local dev (Docker Compose):** Ensure you are logged in to Azure CLI:
   ```bash
   az login
   az account set --subscription <your-subscription-id>
   ```

2. **Azure (production):** Verify the backend Container App's managed identity has the `CognitiveServicesOpenAIUser` role on the Foundry account, and the Foundry project's managed identity has `Cognitive Services OpenAI Contributor` and `Foundry User` (formerly `Azure AI User`) roles on the Foundry account:
   - Check `infra/modules/role-assignments.bicep`
   - Re-run `azd provision` to reapply role assignments if missing

3. **Both:** Confirm `AZURE_AI_PROJECT_ENDPOINT` is set correctly:
   ```
   https://<account>.services.ai.azure.com/api/projects/<project-name>
   ```
   The `/api/projects/<project-name>` segment is required — the bare account endpoint will not work.

---

## Agent Returns "ID cannot be null or empty" / status: "failed"

All agent calls fail with `400 - ID cannot be null or empty` or return
`status: "failed"` with empty output.

**Cause (initial preview, now resolved):** In the initial Hosted Agents preview,
`MCPTool` entries in `HostedAgentDefinition.tools` triggered a
`UserInfoContextMiddleware` that called `/agents/{name}/tools/resolve`, which
failed in regions where the API was unavailable.

**Fix (current):** This accelerator wires all five MCP servers **in-container**
via `MCPStreamableHTTPTool` (read from `MCP_*` env vars in each
`agents/<name>/agent.yaml`), so the platform `tools/resolve` flow is no longer
on the hot path. If you still hit this error, confirm you are on the new
package set (`agent-framework-foundry-hosting>=1.0.0b260730,<2`,
`azure-ai-agentserver-core>=2.0.0,<3`, `azure-ai-projects>=2.4.0,<3`) and that
`azd deploy` ran cleanly to redeploy the agent images.

---

## Agents Return Empty or Error Responses

Agents connect but return `{"error": "...", "tool_results": []}` instead of structured output.

**Cause 1 — Wrong project endpoint:** `AZURE_AI_PROJECT_ENDPOINT` points to the bare account endpoint instead of the project endpoint.

**Cause 2 — Agent not registered:** The hosted agent was not successfully deployed/registered with Foundry Agent Service.

**Cause 3 — Model deployment missing:** The `AZURE_OPENAI_DEPLOYMENT_NAME` (e.g., `gpt-5.4`) doesn't exist in the Foundry project.

**Fix:**

1. Verify agents are registered:
   ```bash
   azd ai agent list
   # or run the pre-flight health check:
   python scripts/check_agents.py
   ```

2. Confirm the endpoint format in `AZURE_AI_PROJECT_ENDPOINT` includes `/api/projects/<project>`.

3. In the Foundry portal under **Build** → **Deployments**, confirm the gpt-5.4 deployment exists and its name matches `AZURE_OPENAI_DEPLOYMENT_NAME` declared in each `agents/<name>/agent.yaml`.

---

## "Failed to proxy" / ECONNREFUSED / "Review failed"

The frontend shows an error when submitting a review.

**Cause:** The backend server is not running, or the frontend is not
configured to reach it.

**Fix:**

1. Ensure the backend is running:
   ```bash
   cd backend
   uvicorn app.main:app --reload
   ```

2. Ensure `frontend/.env.local` has the correct backend URL:
   ```
   NEXT_PUBLIC_API_BASE=http://localhost:8000/api
   ```

3. Restart the frontend dev server after changing `.env.local`:
   ```bash
   cd frontend
   npm run dev
   ```

---

## Agent phase fails immediately

The review fails as soon as a specialist phase starts.

**Cause:** One or more hosted agent endpoint URLs are missing or unreachable.

**Fix:** Check which dispatch mode is active:

**Docker Compose (local dev):** Verify all URL variables are set in `backend/.env` or `docker-compose.yml`:

- `HOSTED_AGENT_COMPLIANCE_URL`
- `HOSTED_AGENT_CLINICAL_URL`
- `HOSTED_AGENT_COVERAGE_URL`
- `HOSTED_AGENT_SYNTHESIS_URL`

Make sure `docker-compose.yml` is running all four agent containers and that their ports match the URLs above.

**Foundry Hosted Agents (production / `azd up`):** Verify these variables are set (injected automatically by Bicep):

- `AZURE_AI_PROJECT_ENDPOINT`
- `HOSTED_AGENT_CLINICAL_NAME`
- `HOSTED_AGENT_COMPLIANCE_NAME`
- `HOSTED_AGENT_COVERAGE_NAME`
- `HOSTED_AGENT_SYNTHESIS_NAME`

If set manually, confirm the project endpoint format:
`https://<account>.services.ai.azure.com/api/projects/<project-name>`

Also confirm the agents were successfully deployed by `azd deploy` (which
invokes the `azd ai agent` extension's `create_version()` flow) — check the
`azd deploy` output for registration errors, or run `azd ai agent list`.

You can verify all deployment health at any time with:

```bash
python scripts/check_agents.py
```

This checks agent registration, App Insights connectivity, MCP tool connections,
backend health, and frontend availability.

---

## Hosted-agent authentication returns 401 or 403

The backend reaches the hosted endpoint but receives an authorization failure.

**Cause:** The outbound auth header configuration does not match the hosted
agent deployment.

**Fix:** Depends on the dispatch mode:

**Docker Compose:** Direct HTTP to containers — no auth configured by default. If containers are behind a proxy requiring auth, set `HOSTED_AGENT_AUTH_HEADER`, `HOSTED_AGENT_AUTH_SCHEME`, and `HOSTED_AGENT_AUTH_TOKEN` in `.env`.

**Foundry Hosted Agents (production):** Credentials come from `DefaultAzureCredential`. Common causes:

- The backend ACA managed identity is missing the `CognitiveServicesOpenAIUser` role on the Foundry account — check `infra/modules/role-assignments.bicep` and re-run `azd provision`
- The Foundry project managed identity is missing `Cognitive Services OpenAI Contributor` or `Foundry User` on the Foundry account — these roles are required for hosted agent containers to call gpt-5.4 and use Agent Service data actions
- The deployer user is missing the `Foundry User` role on the Foundry project (required by the `azd ai agent` extension to call `create_version()`) — this role is auto-assigned by `az role assignment create` in the postprovision hook; re-run `azd up` to fix
- `AZURE_AI_PROJECT_ENDPOINT` is pointing to the wrong project or account
- One or more per-agent instance identities are missing `Foundry User` on the Foundry account — the postdeploy hook (`scripts/grant_agent_rbac.py`) grants this; re-run `azd hooks run postdeploy` to retry
- The agents were not successfully deployed — check the `azd deploy` output for `create_version` errors

---

## Agent Registration Fails with PermissionDenied on First Run

`azd deploy` (or `azd ai agent` directly) fails with:
```
ERROR: (PermissionDenied) The principal ... lacks the required data action
Microsoft.CognitiveServices/accounts/AIServices/agents/write
```
or
```
ERROR: (AuthorizationFailed) ... does not have authorization to perform action
'Microsoft.CognitiveServices/accounts/AIServices/projects/agents/deployments/write'
```

**Cause:** Either RBAC propagation delay, or the deployer is missing the
**Foundry Project Manager** role (formerly named `Azure AI Project Manager`).
The refreshed Hosted Agents preview
(Apr 2026) requires Project Manager at the project scope to call
`create_version()` on `HostedAgentDefinition` / `PromptAgentDefinition` —
`Foundry User` only covers invoking an existing agent, not deploying one.
See the [official permissions reference](https://learn.microsoft.com/azure/foundry/agents/how-to/deploy-hosted-agent#required-permissions).

**Automatic handling:** The postprovision hook assigns both `Foundry User`
and `Foundry Project Manager` to the deployer at the project scope before
`azd deploy` runs the `azd ai agent` create_version flow, so RBAC is in place
by the time agents are registered. The postdeploy hook
(`scripts/grant_agent_rbac.py`) then grants `Foundry User` to each per-agent
instance identity on the Foundry account. On first deployment, ~60 seconds of
RBAC propagation may be needed before the first runtime call succeeds — if you
see a 403 from a hosted agent immediately after deploy, wait ~60s and retry.

**If retries fail:** Simply re-run `azd up` (or `azd deploy && azd hooks run
postdeploy`) — the roles already exist so subsequent runs proceed without
additional propagation delay. If failures persist, manually verify the
assignments:
```bash
az role assignment list \
  --assignee "$(az ad signed-in-user show --query id -o tsv)" \
  --scope "/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.CognitiveServices/accounts/<foundry>/projects/<project>" \
  --query "[].roleDefinitionName" -o tsv
```
Both `Foundry User` and `Foundry Project Manager` should appear (older tenants
may still display them as `Azure AI User` / `Azure AI Project Manager` — the
underlying role definition IDs are identical).

---

## postprovision hook exits with code 1 right after "Granting deployer + backend RBAC on Foundry"

`azd up` provisions every resource successfully, then fails with:
```
ERROR: step "cmdhook-postprovision" failed: 'postprovision' hook failed with exit code: '1'
```
and the last line of hook output is `Granting deployer + backend RBAC on Foundry...`
with no further detail.

**Cause:** The hook looked up the role by **display name** and Azure renamed the
built-in roles (`Azure AI User` → `Foundry User`, `Azure AI Project Manager` →
`Foundry Project Manager`). `az role assignment list --role "Azure AI User"`
then returns `Role 'Azure AI User' doesn't exist.` and exits 1. The hook routed
stderr to `/dev/null`, which is why the failure looked silent.

**Fix:** Already applied — the postprovision hook and
`scripts/grant_agent_rbac.py` now reference roles by **role definition ID**
(`53ca6127-db72-4b80-b1b0-d745d6d5456d` for Foundry User,
`eadc314b-1a2d-4efa-be10-5d325db5065e` for Foundry Project Manager), which is
stable across the rename. If you are on an older clone, pull the latest `main`
and re-run `azd up`. To confirm which name your tenant uses:
```bash
az role definition list --name 53ca6127-db72-4b80-b1b0-d745d6d5456d --query "[].roleName" -o tsv
```

---

## Agent deploy fails with "FOUNDRY_PROJECT_ENDPOINT is required"

All four agent services fail during the **Publishing** step:
```
ERROR: FOUNDRY_PROJECT_ENDPOINT is required: environment variable was not found in the current azd environment

Suggestion: run 'azd provision' or connect to an existing project via 'azd ai agent init --project-id <resource-id>'
```

**Cause:** The `azd ai agent` extension resolves the target Foundry project
from the azd environment using that exact variable name. The aliases this repo
uses elsewhere (`AI_FOUNDRY_PROJECT_ENDPOINT`, `AZURE_AI_PROJECT_ENDPOINT`) are
not read by the extension. The variable is commonly missing when `azd up`
reports `(-) Skipped: Didn't find new changes.` — a skipped provision does not
repopulate the environment from template outputs.

**Fix:** `infra/main.bicep` emits `FOUNDRY_PROJECT_ENDPOINT` and the
postprovision hook also sets it explicitly, so a normal `azd up` handles this.
To repair an existing environment without re-provisioning:
```bash
azd env set FOUNDRY_PROJECT_ENDPOINT "$(azd env get-value AI_FOUNDRY_PROJECT_ENDPOINT)"
azd env get-value FOUNDRY_PROJECT_ENDPOINT   # verify
azd up
```
The value must include the `/api/projects/<project>` segment:
`https://<account>.services.ai.azure.com/api/projects/<project>`.

---

## Hosted agent returns an unexpected payload shape

The backend reaches the hosted agent, but parsing or downstream validation
fails.

**Expected payload (Foundry Responses API envelope):**

```json
{
  "output": [{"content": [{"text": "{\"field\": \"value\", ...}"}]}]
}
```

The backend uses `response.output_text` from the OpenAI SDK and parses the JSON result directly.

**Fix:** Confirm the agent container is returning the standard Foundry Responses
API envelope. The Microsoft Agent Framework `ResponsesHostServer(agent).run()`
produces this format automatically.

---

## Port Stuck After Killing Server (Windows)

After killing a server process, the port remains in LISTENING state.

**Cause:** Windows TCP socket lingering.

**Fix:** Wait 2-4 minutes for the socket to clear, or use a different port.

---

## Agent Returns Truncated/Incomplete Response

One or more agents return partial data with missing top-level keys.

**Cause:** The agent's `response_format` structured output was not fully populated by the model response, typically due to token limits or a model timeout.

**Symptoms in server logs:**

```
WARNING app.agents.orchestrator: Clinical Reviewer Agent returned incomplete result (attempt 1/2). Missing keys: clinical_extraction, clinical_summary. Retrying...
INFO app.agents.orchestrator: Clinical Reviewer Agent succeeded on retry (attempt 2/2)
```

A normal Clinical result has 3 expected top-level keys (`diagnosis_validation`, `clinical_extraction`, `clinical_summary`). Additional fields like `procedure_validation`, `tool_results`, and `clinical_trials` are also present but not checked by the validation gate.

**Mitigations (in place):**

1. **Result validation** — checks for expected top-level keys via `_EXPECTED_KEYS` in `orchestrator.py`
2. **Automatic retry** — retries once (`_MAX_AGENT_RETRIES = 1`) if validation fails
3. **SSE warnings** — surfaces validation warnings to the frontend

**If retries consistently fail:**
- The agent's `HOSTED_AGENT_TIMEOUT_SECONDS` (default `180`) may be too low — increase it in `backend/.env`
- Check the agent container logs in Foundry portal for model errors or context overflow

---

## Troubleshooting Foundry Traces

If traces don't appear in Foundry (Trace ID = "--", Duration = "--", Tokens = "--"):

- Verify the Foundry project has Application Insights configured
- If App Insights was added after agent registration, unregister and re-register
- Verify your backend sends traces to the **same** Application Insights resource
- **Verify `gen_ai.agent.id` is populated in spans.** The refreshed Hosted
  Agents preview populates `gen_ai.agent.id` and `gen_ai.agent.name` natively
  from the platform-injected `FOUNDRY_AGENT_NAME` env var — the previous
  `_patch_trace_agent_id()` monkey-patch is no longer needed and has been
  removed from all four agents.
  You can verify by querying App Insights:
  ```kql
  traces
  | where cloud_RoleName == 'azure.ai.agentserver'
  | where message has 'agent_run'
  | extend agentId = tostring(parse_json(customDimensions)['gen_ai.agent.id'])
  | project timestamp, agentId
  ```
  If `agentId` is empty, confirm `FOUNDRY_AGENT_NAME` is set in the agent
  container env (it is injected automatically by the Foundry runtime).
- **Check the env var name:** The Foundry agentserver adapter expects
  `APPLICATIONINSIGHTS_CONNECTION_STRING` (no underscore between APPLICATION
  and INSIGHTS). This is different from `APPLICATION_INSIGHTS_CONNECTION_STRING`
  used by the `azure-monitor-opentelemetry` SDK. Both must be set. See
  [technical-notes.md](technical-notes.md#enabling-observability) for details.
- If the Foundry Operate tab shows "0/3 monitoring features enabled," the
  adapter-expected env var is missing or empty
