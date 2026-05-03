"""Create or update the Agent Platform online monitor for the deployed agent.

Usage:
    uv run python tests/eval/setup_monitor.py

The monitor samples 50% of live production traces every 10 minutes and scores
them with Safety and Final Response Quality. Results appear in:
  - Agent Platform > Agents > voting-agent > Dashboard > Evaluation
  - Agent Platform > Agents > voting-agent > Traces (per-trace Evaluation tab)
  - Cloud Monitoring metric: aiplatform.googleapis.com/online_evaluator/scores
"""

import json
import os
import sys
import time
from pathlib import Path

import google.auth
import google.auth.transport.requests
import requests

_METADATA_FILE = Path(__file__).parents[2] / "deployment_metadata.json"

_METRICS = [
    "safety_v1",
    "final_response_quality_v1",
]

_SAMPLING_PCT = 50
_MAX_SAMPLES = 20


def _token() -> str:
    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


def _agent_resource() -> str:
    meta = json.loads(_METADATA_FILE.read_text())
    name = meta.get("remote_agent_runtime_id", "")
    if not name:
        sys.exit(
            "deployment_metadata.json has no remote_agent_runtime_id — deploy the agent first.",
        )
    return name


def _list_monitors(token: str, project_id: str, location: str) -> list[dict]:
    url = f"https://{location}-aiplatform.googleapis.com/v1beta1/projects/{project_id}/locations/{location}/onlineEvaluators"
    r = requests.get(url, headers={"Authorization": f"Bearer {token}"})
    r.raise_for_status()
    return r.json().get("onlineEvaluators", [])


def _create_monitor(
    token: str, agent_resource: str, project_id: str, location: str,
) -> dict:
    url = f"https://{location}-aiplatform.googleapis.com/v1beta1/projects/{project_id}/locations/{location}/onlineEvaluators"
    body = {
        "displayName": "Voting Agent Production Monitor",
        "agentResource": agent_resource,
        "cloudObservability": {
            "traceScope": {},
            "openTelemetry": {"semconvVersion": "1.39.0"},
        },
        "config": {
            "maxEvaluatedSamplesPerRun": str(_MAX_SAMPLES),
            "randomSampling": {"percentage": _SAMPLING_PCT},
        },
        "metricSources": [
            {"metric": {"predefinedMetricSpec": {"metricSpecName": m}}}
            for m in _METRICS
        ],
    }
    r = requests.post(
        url,
        json=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    r.raise_for_status()
    op = r.json()
    op_name = op["name"]

    op_url = f"https://{location}-aiplatform.googleapis.com/v1beta1/{op_name}"
    for _ in range(20):
        time.sleep(3)
        r = requests.get(op_url, headers={"Authorization": f"Bearer {token}"})
        r.raise_for_status()
        result = r.json()
        if result.get("done"):
            return result.get("response", {})
    sys.exit("Timed out waiting for monitor creation.")


def main() -> None:
    token = _token()
    agent = _agent_resource()

    project_id = os.environ.get("GCP_PROJECT_ID")
    if not project_id:
        sys.exit("ERROR: GCP_PROJECT_ID env var is required.")

    location = os.environ.get("EVAL_REGION", "us-central1")

    existing = _list_monitors(token, project_id, location)
    for m in existing:
        if m.get("agentResource") == agent:
            return

    _create_monitor(token, agent, project_id, location)


if __name__ == "__main__":
    main()
