# Troubleshooting

## MAF Agent Fails to Start / "Failed to acquire Foundry auth token"

The backend logs show an auth error when trying to invoke a hosted agent.

**Cause:** `DefaultAzureCredential` cannot acquire a token for the Foundry Responses API.

**Fix:**

1. **Local dev (Docker Compose):** Ensure you are logged in to Azure CLI:
   ```bash
   az login
   az account set --subscription <your-subscription-id>
   ```

2. **Azure (production):** Verify the backend Container App's managed identity has the `CognitiveServicesOpenAIUser` role on the Foundry account:
   - Check `infra/modules/role-assignments.bicep`
   - Re-run `azd provision` to reapply role assignments if missing

3. **Both:** Confirm `AZURE_AI_PROJECT_ENDPOINT` is set correctly:
   ```
   https://<account>.services.ai.azure.com/api/projects/<project-name>
   ```
   The `/api/projects/<project-name>` segment is required — the bare account endpoint will not work.

---

## Agents Return Empty or Error Responses

Agents connect but return `{"error": "...", "tool_results": []}` instead of structured output.

**Cause 1 — Wrong project endpoint:** `AZURE_AI_PROJECT_ENDPOINT` points to the bare account endpoint instead of the project endpoint.

**Cause 2 — Agent not registered:** The hosted agent was not successfully deployed/registered with Foundry Agent Service.

**Cause 3 — Model deployment missing:** The `AZURE_OPENAI_DEPLOYMENT_NAME` (e.g., `gpt-5.4`) doesn't exist in the Foundry project.

**Fix:**

1. Verify agents are registered:
   ```bash
   python scripts/register_agents.py --list
   ```

2. Confirm the endpoint format in `AZURE_AI_PROJECT_ENDPOINT` includes `/api/projects/<project>`.

3. In the Foundry portal under **Build** → **Deployments**, confirm the gpt-5.4 deployment exists and its name matches `AZURE_OPENAI_DEPLOYMENT_NAME` in each `agent.yaml`.

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

Also confirm the agents were successfully registered by `scripts/register_agents.py`
in the postprovision hook (check `azd provision` output for registration errors).

---

## Hosted-agent authentication returns 401 or 403

The backend reaches the hosted endpoint but receives an authorization failure.

**Cause:** The outbound auth header configuration does not match the hosted
agent deployment.

**Fix:** Depends on the dispatch mode:

**Docker Compose:** Direct HTTP to containers — no auth configured by default. If containers are behind a proxy requiring auth, set `HOSTED_AGENT_AUTH_HEADER`, `HOSTED_AGENT_AUTH_SCHEME`, and `HOSTED_AGENT_AUTH_TOKEN` in `.env`.

**Foundry Hosted Agents (production):** Credentials come from `DefaultAzureCredential`. Common causes:

- The backend ACA managed identity is missing the `CognitiveServicesOpenAIUser` role on the Foundry account — check `infra/modules/role-assignments.bicep` and re-run `azd provision`
- The deployer user is missing the `Azure AI Developer` role on the Foundry account (required by `scripts/register_agents.py` to register agents) — this role is auto-assigned by `az role assignment create` in the postprovision hook; re-run `azd up` to fix
- `AZURE_AI_PROJECT_ENDPOINT` is pointing to the wrong project or account
- The agents were not successfully registered — check `scripts/register_agents.py` output in the postprovision hook logs

---

## Agent Registration Fails with PermissionDenied on First Run

`register_agents.py` fails with:
```
ERROR: (PermissionDenied) The principal ... lacks the required data action
Microsoft.CognitiveServices/accounts/AIServices/agents/write
```

**Cause:** Azure RBAC propagation delay. The postprovision hook assigns the Azure AI Developer role immediately before running `register_agents.py`, but Azure's role cache can take up to several minutes to update.

**Automatic handling:** The hook automatically detects newly assigned roles and retries `register_agents.py` every 10 seconds (up to 12 attempts / ~2 minutes). You'll see "Waiting for RBAC propagation (attempt N/12)..." messages in the output — this is expected on first deployment.

**If all 12 retries fail:** RBAC propagation took unusually long. Simply re-run `azd up` — the role already exists so registration will proceed without retries.

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

The backend reads `output[0].content[0].text` and `json.loads()` the result.

**Fix:** Confirm the agent container is returning the standard Foundry Responses
API envelope. MAF's `from_agent_framework(agent).run()` produces this format
automatically.

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

A normal Clinical result has 4 expected top-level keys (`diagnosis_validation`, `clinical_extraction`, `clinical_summary`, `tool_results`).

**Mitigations (in place):**

1. **Result validation** — checks for expected top-level keys via `_EXPECTED_KEYS` in `orchestrator.py`
2. **Automatic retry** — retries once (`_MAX_AGENT_RETRIES = 1`) if validation fails
3. **SSE warnings** — surfaces validation warnings to the frontend

**If retries consistently fail:**
- The agent's `HOSTED_AGENT_TIMEOUT_SECONDS` (default `180`) may be too low — increase it in `backend/.env`
- Check the agent container logs in Foundry portal for model errors or context overflow

---

## Troubleshooting Foundry Traces

If traces don't appear in Foundry:

- Verify the Foundry project has Application Insights configured
- If App Insights was added after agent registration, unregister and re-register
- Verify your backend sends traces to the **same** Application Insights resource
- Verify spans include `gen_ai.agent.id` matching the registered agent ID
