"""Agent Platform evaluation script — runs eval against the deployed Agent Runtime.

Usage:
    uv run --extra eval python tests/eval/run_platform_eval.py

Required env vars:
    GCP_PROJECT_ID       — GCP project ID
    GCS_EVAL_BUCKET      — GCS bucket URI for eval output, e.g. gs://my-bucket/evals

Optional env vars:
    AGENT_RESOURCE_NAME  — full resource name; falls back to deployment_metadata.json
    EVAL_REGION          — scoring region; must be supported by the Vertex Evaluation
                           Service (e.g. us-central1). Defaults to us-central1.
"""

import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
import vertexai
from google.cloud import storage as gcs
from google.genai import types as genai_types
from vertexai import Client, types

PROMPTS = [
    "A smart coffee mug that keeps your drink hot for hours and connects to your phone.",
    "Noise-cancelling wireless headphones with 30-hour battery life and foldable design.",
    "An AI-powered personal finance app that automatically tracks spending and suggests savings.",
    "Eco-friendly reusable water bottle with built-in temperature display and UV purification.",
    "A standing desk converter that adjusts height with one hand and fits any surface.",
    "A project management platform for remote engineering teams with built-in time tracking and GitHub integration.",
    "Cold-brew coffee concentrate made from single-origin beans, ready in 60 seconds.",
    "A handcrafted leather wallet with RFID blocking and a ten-year craftsmanship guarantee.",
    "A same-day home cleaning service that uses only non-toxic, eco-certified products.",
    "A blender.",
]

METRICS = [
    types.RubricMetric.GENERAL_QUALITY,
    types.RubricMetric.INSTRUCTION_FOLLOWING,
    types.RubricMetric.SAFETY,
    types.RubricMetric.TEXT_QUALITY,
]

_TERMINAL_STATES = {
    types.EvaluationRunState.SUCCEEDED,
    types.EvaluationRunState.FAILED,
    types.EvaluationRunState.CANCELLED,
}
_POLL_INTERVAL_SECONDS = 30


def load_agent_resource_name() -> str:
    name = os.environ.get("AGENT_RESOURCE_NAME", "")
    if name:
        return name
    metadata_path = Path(__file__).parents[2] / "deployment_metadata.json"
    if metadata_path.exists():
        data = json.loads(metadata_path.read_text())
        name = data.get("remote_agent_runtime_id", "")
    if not name:
        sys.exit(
            "ERROR: Set AGENT_RESOURCE_NAME or ensure deployment_metadata.json exists.",
        )
    return name


def _print_per_prompt_results(gcs_dest: str, run_name: str) -> None:
    """Read GCS result files directly, bypassing the broken SDK Pydantic deserialization.

    Workaround for: SDK `EvaluationItemResult` model rejects `candidateResponses[].error`
    field written by the server (extra_forbidden). This reads the raw JSON instead.
    """
    # Parse gs://bucket/prefix/... into components
    path = gcs_dest.removeprefix("gs://")
    bucket_name, _, prefix = path.partition("/")
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    run_id = run_name.split("/")[-1]

    storage_client = gcs.Client()
    bucket = storage_client.bucket(bucket_name)

    items: list[dict] = []
    for blob in bucket.list_blobs(prefix=prefix):
        filename = blob.name.split("/")[-1]
        if not filename.startswith("result_") or not filename.endswith(".json"):
            continue
        try:
            data = json.loads(blob.download_as_text())
        except Exception:
            continue
        if run_id in data.get("evaluationRun", ""):
            items.append(data)

    if not items:
        return

    # Sort by prompt text for stable output order
    items.sort(key=lambda r: r.get("request", {}).get("prompt", {}).get("text", ""))

    for item in items:
        item.get("request", {}).get("prompt", {}).get("text", "?")
        for candidate in item.get("request", {}).get("candidateResponses", []):
            candidate.get("candidate", "?")
            if "error" in candidate:
                candidate["error"].get("code", "?")
                msg = candidate["error"].get("message", "")
                msg.split(";")[0] if ";" in msg else msg
            else:
                candidate.get("text", "")
                for result in candidate.get("metricResults", {}).values():
                    score = result.get("score")
                    result.get("verdict", "")
                    (
                        f"{score:.3f}" if isinstance(score, float) else str(score)
                    )


def main() -> None:
    project = os.environ.get("GCP_PROJECT_ID")
    if not project:
        sys.exit("ERROR: GCP_PROJECT_ID env var is required.")

    gcs_dest = os.environ.get("GCS_EVAL_BUCKET")
    if not gcs_dest:
        sys.exit(
            "ERROR: GCS_EVAL_BUCKET env var is required (e.g. gs://my-bucket/evals).",
        )

    eval_location = os.environ.get("EVAL_REGION", "us-central1")
    agent_resource_name = load_agent_resource_name()

    vertexai.init(project=project, location=eval_location)
    client = Client(
        project=project,
        location=eval_location,
        http_options=genai_types.HttpOptions(api_version="v1beta1"),
    )

    dataset = types.EvaluationDataset(
        eval_dataset_df=pd.DataFrame({"prompt": PROMPTS}),
    )
    inference_configs = {
        "candidate-1": types.EvaluationRunInferenceConfig(
            agent_run_config=types.AgentRunConfig(agent_engine=agent_resource_name),
        ),
    }

    eval_run = client.evals.create_evaluation_run(
        dataset=dataset,
        dest=gcs_dest,
        metrics=METRICS,
        inference_configs=inference_configs,
    )
    run_name = eval_run.name

    while eval_run.state not in _TERMINAL_STATES:
        time.sleep(_POLL_INTERVAL_SECONDS)
        eval_run = client.evals.get_evaluation_run(name=run_name)

    if eval_run.state != types.EvaluationRunState.SUCCEEDED:
        sys.exit(
            f"ERROR: Evaluation run ended with state {eval_run.state}: {eval_run.error}",
        )

    run_results = eval_run.evaluation_run_results
    run_name.split("/")[-1]
    if (
        run_results
        and run_results.summary_metrics
        and run_results.summary_metrics.metrics
    ):
        for _metric_name, _value in sorted(run_results.summary_metrics.metrics.items()):
            pass
        if run_results.summary_metrics.total_items is not None:
            pass
        if run_results.summary_metrics.failed_items:
            pass


    _print_per_prompt_results(gcs_dest, run_name)


if __name__ == "__main__":
    main()
