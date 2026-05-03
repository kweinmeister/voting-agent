# Voting Agent

A marketing ad copy generator that runs three writing styles in parallel (humorous, professional, urgent), uses an LLM judge to pick the winner, and learns your preferences over time via Google ADK Memory Bank.

**How it works:**
1. You enter a product description
2. The agent generates three ad copy variants simultaneously
3. A judge picks the best one and explains why
4. You give thumbs up/down feedback — stored in Memory Bank
5. Future generations are personalized based on your preference history

## Architecture

```
frontend (Cloud Run)
  └── FastAPI + SSE streaming
      ├── local dev  → ADK Runner in-process
      └── production → Vertex AI Agent Runtime (Agent Engine)
              └── voting_agent (ADK Agent)
                      ├── PreloadMemoryTool  (reads past preferences)
                      └── after_agent_callback → Memory Bank (saves session)
```

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- [agents-cli](https://pypi.org/project/google-agents-cli/) — `uv tool install google-agents-cli`
- [Google Cloud SDK](https://cloud.google.com/sdk/docs/install) — `gcloud auth application-default login`
- A GCP project with billing enabled

## Local Development

### 1. Install dependencies

```bash
agents-cli install
# or: uv sync
```

### 2. Set environment variables

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
export GOOGLE_CLOUD_LOCATION=us-central1   # or your preferred region
```

### 3. Run the frontend locally

```bash
uv run uvicorn frontend.main:app --reload --port 8080
```

Open http://localhost:8080. The app runs the agent in-process (no Agent Runtime needed). Memory Bank is not active in local mode — `after_agent_callback` silently skips it.

### 4. (Optional) Use the ADK playground

```bash
agents-cli playground
# or: uv run adk web
```

This opens the ADK dev UI at http://localhost:8000 for direct agent interaction.

## One-Shot Deployment with Terraform

The `terraform/` directory provisions everything in one `terraform apply`: APIs, IAM, Artifact Registry, the Docker image (via Cloud Build), the Model Armor template, and the Cloud Run frontend.

### Prerequisites

- [Terraform](https://developer.hashicorp.com/terraform/install) >= 1.4
- `gcloud` authenticated (`gcloud auth application-default login`)
- `agents-cli` installed (`uv tool install google-agents-cli`)

### Steps

**1. Copy and fill in the variables file**

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars — set project_id at minimum
```

**2. Deploy everything**

```bash
terraform init
terraform apply
```

This enables APIs, builds and pushes the container via Cloud Build (~5 min), creates the Model Armor template, and deploys Cloud Run. At the end it prints a `next_steps` output telling you what to do if the Agent Runtime isn't wired up yet.

**3. Deploy the Agent Runtime (if not already done)**

```bash
cd ..               # back to project root
agents-cli deploy   # ~10 min; writes deployment_metadata.json
```

**4. Apply again to wire up the agent**

```bash
cd terraform
terraform apply     # reads deployment_metadata.json, updates Cloud Run env var
```

Terraform reads `deployment_metadata.json` automatically — no manual copy-paste required.

> **Shortcut:** Set `deploy_agent = true` in `terraform.tfvars` and Terraform runs `agents-cli deploy` for you during step 2 (adds ~10 min). After that set it back to `false`.

### Re-deploying after code changes

```bash
terraform apply   # detects changed file hashes, rebuilds image, updates Cloud Run
```

---

## Deploy the Agent to Agent Runtime

Agent Runtime (Vertex AI Agent Engine) hosts the agent as a managed cloud service.

### 1. Configure your project

```bash
gcloud config set project YOUR_PROJECT_ID
gcloud auth application-default login
```

### 2. Enable required APIs

```bash
gcloud services enable \
  aiplatform.googleapis.com \
  cloudtrace.googleapis.com \
  bigquery.googleapis.com
```

### 3. Deploy

```bash
agents-cli deploy
```

This packages the `app/` directory, uploads it to Agent Runtime, and writes `deployment_metadata.json` with the resource ID.

### 4. Note the Agent Runtime resource name

After deploy, `deployment_metadata.json` contains the resource name:

```json
{
  "remote_agent_runtime_id": "projects/PROJECT_NUMBER/locations/REGION/reasoningEngines/RESOURCE_ID",
  // ...
}
```

Set this as `AGENT_RESOURCE_NAME` when deploying the frontend (next section).

### Redeploying after changes

Always use `agents-cli deploy` for updates — **do not** use the Vertex AI SDK's `agent_engines.update()`. The agents-cli deployment format (`deployment_source`) is incompatible with the SDK update path and will error.

```bash
agents-cli deploy
```

## Deploy the Frontend to Cloud Run

### 1. Build and push the container

```bash
gcloud builds submit . \
  --tag gcr.io/YOUR_PROJECT_ID/voting-agent-frontend
```

Or with a custom Cloud Build config if you have one:

```bash
gcloud builds submit . --config=cloudbuild.yaml
```

### 2. Deploy to Cloud Run

```bash
gcloud run deploy voting-agent-frontend \
  --image gcr.io/YOUR_PROJECT_ID/voting-agent-frontend \
  --region us-central1 \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars AGENT_RESOURCE_NAME=projects/PROJECT_NUMBER/locations/REGION/reasoningEngines/RESOURCE_ID \
  --set-env-vars GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID \
  --set-env-vars GOOGLE_CLOUD_LOCATION=us-central1
```

### Environment variables

| Variable | Required | Description |
|---|---|---|
| `AGENT_RESOURCE_NAME` | Production only | Full resource name of the deployed Agent Runtime |
| `GOOGLE_CLOUD_PROJECT` | Yes | GCP project ID |
| `GOOGLE_CLOUD_LOCATION` | Yes | Region for Vertex AI calls (e.g. `us-central1`) |
| `GEMINI_MODEL` | No | Model to use (default: `gemini-3-flash-preview`) |
| `LOGS_BUCKET_NAME` | No | GCS bucket name for prompt/response audit logging. When set, content is uploaded to GCS instead of embedded in Cloud Trace events. |

If `AGENT_RESOURCE_NAME` is not set, the frontend runs the agent in-process (local dev mode).

### Required IAM roles for the Cloud Run service account

```bash
# Replace with your Cloud Run service account (default: PROJECT_NUMBER-compute@developer.gserviceaccount.com)
SA=YOUR_PROJECT_NUMBER-compute@developer.gserviceaccount.com

gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:$SA" \
  --role="roles/aiplatform.user"
```

## CI/CD with GitHub Actions

Three workflows automate the development lifecycle:

| Workflow | Trigger | What it does |
|---|---|---|
| `ci.yml` | Every push / PR | Lint (ruff, ty, codespell), unit tests, Biome (JS), Terraform validate |
| `deploy.yml` | Push to `main` / manual | Builds + deploys frontend; redeploys Agent Runtime; runs eval |
| `eval.yml` | Manual (`workflow_dispatch`) | Runs Agent Platform eval against a specified GCS bucket |

The deploy workflow detects which parts of the codebase changed (via `dorny/paths-filter`) so it only rebuilds the frontend or redeploys the agent when relevant files change. After an agent redeploy it automatically updates the `AGENT_RESOURCE_NAME` env var on the Cloud Run service — no manual wiring needed.

### Setting up WIF authentication

GitHub Actions authenticates to GCP via Workload Identity Federation — no long-lived keys stored as secrets.

**1. Provision WIF resources with Terraform**

```bash
cd terraform
terraform apply -var="github_repo=your-org/voting-agent"
```

**2. Set GitHub Actions variables in your repo settings**

| Variable | Source |
|---|---|
| `WIF_PROVIDER` | `terraform output wif_provider` |
| `GHA_SERVICE_ACCOUNT` | `terraform output gha_service_account` |
| `GCP_PROJECT_ID` | Your GCP project ID |
| `GCS_EVAL_BUCKET` | `terraform output eval_bucket` |

## Memory Bank

User preferences are stored automatically via ADK Memory Bank (backed by `VertexAiMemoryBankService` on Agent Runtime).

- After each ad generation, `after_agent_callback` calls `add_session_to_memory()` to save the session
- When the user votes 👍 or 👎, the frontend sends a follow-up message on the same session, which triggers another `add_session_to_memory()` — capturing the vote alongside the generated content
- On the next generation, `PreloadMemoryTool` retrieves consolidated memories (e.g. "User prefers HUMOROUS 8/10 times") and injects them into the agent's context
- Memory Bank uses an LLM to consolidate entries over time, so preferences become more accurate rather than noisier

Memory Bank is only active when running against Agent Runtime. It is silently skipped in local dev.

## Observability & Monitoring

### Telemetry

The agent runtime is instrumented with OpenTelemetry via `app/app_utils/telemetry.py`, which `AgentEngineApp.set_up()` calls on every cold start. The following environment variables are set automatically:

| Variable | Value | Purpose |
|---|---|---|
| `GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY` | `true` | Enables ADK traces and logs to Cloud Trace / Cloud Logging |
| `OTEL_SEMCONV_STABILITY_OPT_IN` | `gen_ai_latest_experimental` | Required for gen_ai semantic conventions used by online monitors |
| `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` | `EVENT_ONLY` | Captures prompts and responses as Cloud Trace events (needed for online monitor scoring) |
| `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS` | `false` | Keeps content in events only — prevents PII in span attributes and avoids attribute size limits |

If `LOGS_BUCKET_NAME` is set, content is instead uploaded to GCS (`NO_CONTENT` mode) rather than embedded in Cloud Trace events.

### Online Monitors

Online monitors continuously sample live production traffic (every 10 minutes) and score it with the Agent Platform eval service. Results appear in the **Evaluation** tab and in Cloud Monitoring (`aiplatform.googleapis.com/online_evaluator/scores`).

The monitor is created automatically by Terraform via `tests/eval/setup_monitor.py`. To create or verify it manually:

```bash
uv run python tests/eval/setup_monitor.py
```

Metrics configured:
- `safety_v1` — flags unsafe responses (score 0 = unsafe, 1 = safe)
- `final_response_quality_v1` — scores overall ad copy quality (0–1)

Sampling: 50% of traces, max 20 per 10-minute run.

To set up quality alerts (Slack/email notification when scores drop):

1. Agent Platform → Agents → voting-agent → Evaluation → Online monitors
2. Click ⋮ next to the monitor → **Create alerting policy**

### Application Topology

The Cloud Run frontend and Agent Engine workload are registered in App Hub (`my-app`, us-central1), enabling the [Cloud Monitoring Application Topology](https://cloud.google.com/monitoring/docs/application-topology) view.

To view the topology graph, grant yourself the `apptopology.viewer` role:

```bash
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="user:YOUR_EMAIL" \
  --role="roles/apptopology.viewer" \
  --condition=None
```

Then navigate to **Cloud Monitoring → Application Monitoring → Topology**.

The Agent Platform also has its own **Topology** tab (Agent Platform → Agents → voting-agent → Topology) which shows agent↔tool↔sub-agent connections from ADK traces — no additional setup required beyond telemetry.

## Evaluations

Agent quality is measured using the [Agent Platform eval service](https://cloud.google.com/vertex-ai/generative-ai/docs/models/evaluation-agents-client), which runs inference against the deployed Agent Runtime and scores responses for quality, hallucination, and safety. Results appear in the **Agent Platform → Deployments → Dashboard → Evaluation** tab in the Cloud console.

### Running evals locally

```bash
GCP_PROJECT_ID=your-project-id \
GCS_EVAL_BUCKET=$(cd terraform && terraform output -raw eval_bucket) \
uv run --extra eval python tests/eval/run_platform_eval.py
```

`EVAL_REGION` defaults to `us-central1` (the Vertex Evaluation Service region). The script uses `create_evaluation_run()`, which handles agent inference server-side and creates a run record visible in the Agent Platform console under **Deployments → Dashboard → Evaluation**.

### Running evals via GitHub Actions

Go to **Actions → Eval → Run workflow** and enter the GCS bucket URI. The bucket is provisioned by Terraform — get the URI from:

```bash
cd terraform && terraform output eval_bucket
```

### Metrics

| Metric | What it measures |
|---|---|
| `GENERAL_QUALITY` | Overall quality of the ad copy |
| `INSTRUCTION_FOLLOWING` | Does the agent emit the required four-section format? |
| `SAFETY` | Is the output free of harmful content? |
| `TEXT_QUALITY` | Writing clarity and effectiveness of the ad copy |

Eval output (scores, rationales, traces) is written to the GCS bucket and indexed by eval run name in the console.

## Project Structure

```
voting-agent/
├── app/
│   └── agent.py              # ADK Agent with Memory Bank
├── frontend/
│   ├── main.py               # FastAPI app — SSE streaming, feedback endpoint
│   ├── templates/
│   │   └── index.html        # UI
│   └── static/
│       ├── voting.js         # Stream consumer, feedback buttons
│       ├── stream-handler.js # SSE EventSource wrapper
│       ├── style.css
│       └── favicon.svg
├── tests/
│   ├── unit/                 # Unit tests (pytest)
│   └── eval/
│       └── run_platform_eval.py  # Agent Platform eval script
├── terraform/                # One-shot infrastructure
├── Dockerfile                # Container for Cloud Run frontend
├── pyproject.toml
├── uv.toml                   # Pins PyPI index (required for agents-cli deploy)
└── deployment_metadata.json  # Written by agents-cli deploy
```

## Security: Model Armor Prompt Screening

User prompts are screened by [Model Armor](https://cloud.google.com/security/products/model-armor) before reaching the agent. This catches prompt injection, jailbreak attempts, and harmful content. When a prompt is blocked, the frontend shows a user-friendly message and the agent is never called.

**Why ingress-only:** Model Armor response screening buffers the full response before allowing/blocking, which breaks SSE streaming. Screening only the user's prompt preserves the streaming UX with no tradeoff in the cases that matter (malicious user input is the primary threat).

### Setup

**Step 1 — Enable the Model Armor API**

```bash
gcloud services enable modelarmor.googleapis.com
```

**Step 2 — Create a template in your Agent Runtime region**

```bash
gcloud model-armor templates create voting-agent-template \
  --project=YOUR_PROJECT_ID \
  --location=us-central1 \
  --rai-settings-filters='[
    {"filterType": "HATE_SPEECH", "confidenceLevel": "MEDIUM_AND_ABOVE"},
    {"filterType": "HARASSMENT", "confidenceLevel": "MEDIUM_AND_ABOVE"},
    {"filterType": "SEXUALLY_EXPLICIT", "confidenceLevel": "MEDIUM_AND_ABOVE"},
    {"filterType": "DANGEROUS", "confidenceLevel": "MEDIUM_AND_ABOVE"}
  ]' \
  --pi-and-jailbreak-filter-settings-enforcement=enabled \
  --pi-and-jailbreak-filter-settings-confidence-level=HIGH \
  --template-metadata-log-operations
```

**Step 3 — Grant the Cloud Run service account access to call Model Armor**

```bash
SA=YOUR_PROJECT_NUMBER-compute@developer.gserviceaccount.com

gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:$SA" \
  --role="roles/modelarmor.user"
```

**Step 4 — Set environment variables when deploying Cloud Run**

```bash
gcloud run deploy voting-agent-frontend \
  ... \
  --set-env-vars MODEL_ARMOR_TEMPLATE=projects/YOUR_PROJECT_ID/locations/us-central1/templates/voting-agent-template \
  --set-env-vars MODEL_ARMOR_LOCATION=us-central1
```

### Environment variables

| Variable | Description |
|---|---|
| `MODEL_ARMOR_TEMPLATE` | Full resource name of the Model Armor template. If unset, screening is skipped. |
| `MODEL_ARMOR_LOCATION` | Region of the template (default: `us-central1`). Must match the template's region. |

### How it works

The `screen_prompt()` function in `frontend/main.py` calls `SanitizeUserPrompt` via the `google-cloud-modelarmor` client before every Agent Runtime call. If Model Armor returns `MATCH_FOUND`, the frontend receives a `{"type": "blocked"}` SSE event and displays a policy message. If the Model Armor API is unreachable, the check fails open (the prompt is allowed through) so a transient API outage doesn't break the app.

### Floor settings (Vertex AI integration)

Model Armor floor settings are enabled at the project level for `AI_PLATFORM`, screening `generateContent` calls made internally by the agent runtime. This populates the **Agent Platform → Security** tab with flagged/blocked interaction counts. Configuration is managed by Terraform via the `null_resource.model_armor_floor_settings` resource.

The Vertex AI service agent (`service-PROJECT_NUMBER@gcp-sa-aiplatform.iam.gserviceaccount.com`) requires `roles/modelarmor.user` for this integration — also managed by Terraform.

### Security posture

| Layer | What it protects |
|---|---|
| Model Armor (frontend ingress) | Blocks prompt injection and harmful content before the agent session is created |
| Model Armor (floor settings) | Screens internal Gemini `generateContent` calls inside Agent Engine; populates Security tab |
| `/feedback` endpoint screening | User-supplied `style` field is screened before being forwarded to the agent |
| Cloud Run IAM | `--no-allow-unauthenticated` + IAP for non-public deployments |
| Least-privilege service account | Scoped to `aiplatform.user` + `modelarmor.user` only |

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request. For major changes, please open an issue first to discuss what you would like to change.

## License

This project is licensed under the Apache License, Version 2.0. See the [LICENSE](LICENSE) file for details.
