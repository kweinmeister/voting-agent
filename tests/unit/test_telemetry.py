"""Unit tests for setup_telemetry — no GCP credentials needed."""

import os

import pytest

from app.app_utils.telemetry import setup_telemetry

OTEL_VARS = [
    "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY",
    "LOGS_BUCKET_NAME",
    "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT",
    "OTEL_INSTRUMENTATION_GENAI_UPLOAD_FORMAT",
    "OTEL_INSTRUMENTATION_GENAI_COMPLETION_HOOK",
    "OTEL_SEMCONV_STABILITY_OPT_IN",
    "OTEL_RESOURCE_ATTRIBUTES",
    "OTEL_INSTRUMENTATION_GENAI_UPLOAD_BASE_PATH",
    "COMMIT_SHA",
    "GENAI_TELEMETRY_PATH",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch) -> None:
    for var in OTEL_VARS:
        monkeypatch.delenv(var, raising=False)


def test_no_bucket_returns_none() -> None:
    result = setup_telemetry()
    assert result is None


def test_no_bucket_disables_upload(monkeypatch) -> None:
    setup_telemetry()
    assert "OTEL_INSTRUMENTATION_GENAI_UPLOAD_BASE_PATH" not in os.environ


def test_bucket_with_capture_false_disables_upload(monkeypatch) -> None:
    monkeypatch.setenv("LOGS_BUCKET_NAME", "my-bucket")
    monkeypatch.setenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "false")
    result = setup_telemetry()
    assert result == "my-bucket"
    assert "OTEL_INSTRUMENTATION_GENAI_UPLOAD_BASE_PATH" not in os.environ


def test_bucket_with_capture_enabled_configures_upload(monkeypatch) -> None:
    monkeypatch.setenv("LOGS_BUCKET_NAME", "my-bucket")
    monkeypatch.setenv(
        "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT",
        "NO_CONTENT",
    )
    result = setup_telemetry()
    assert result == "my-bucket"
    assert (
        os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] == "NO_CONTENT"
    )
    assert (
        os.environ["OTEL_INSTRUMENTATION_GENAI_UPLOAD_BASE_PATH"]
        == "gs://my-bucket/completions"
    )
    assert os.environ["OTEL_INSTRUMENTATION_GENAI_UPLOAD_FORMAT"] == "jsonl"
    assert os.environ["OTEL_INSTRUMENTATION_GENAI_COMPLETION_HOOK"] == "upload"


def test_upload_path_uses_custom_genai_telemetry_path(monkeypatch) -> None:
    monkeypatch.setenv("LOGS_BUCKET_NAME", "my-bucket")
    monkeypatch.setenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "true")
    monkeypatch.setenv("GENAI_TELEMETRY_PATH", "custom/path")
    setup_telemetry()
    assert (
        os.environ["OTEL_INSTRUMENTATION_GENAI_UPLOAD_BASE_PATH"]
        == "gs://my-bucket/custom/path"
    )


def test_commit_sha_included_in_resource_attributes(monkeypatch) -> None:
    monkeypatch.setenv("LOGS_BUCKET_NAME", "my-bucket")
    monkeypatch.setenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "true")
    monkeypatch.setenv("COMMIT_SHA", "abc123")
    setup_telemetry()
    assert "abc123" in os.environ["OTEL_RESOURCE_ATTRIBUTES"]


def test_commit_sha_defaults_to_dev(monkeypatch) -> None:
    monkeypatch.setenv("LOGS_BUCKET_NAME", "my-bucket")
    monkeypatch.setenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "true")
    setup_telemetry()
    assert "dev" in os.environ["OTEL_RESOURCE_ATTRIBUTES"]


def test_telemetry_always_enabled(monkeypatch) -> None:
    setup_telemetry()
    assert os.environ["GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY"] == "true"


def test_semconv_always_set_without_bucket(monkeypatch) -> None:
    setup_telemetry()
    assert os.environ["OTEL_SEMCONV_STABILITY_OPT_IN"] == "gen_ai_latest_experimental"


def test_semconv_always_set_with_bucket(monkeypatch) -> None:
    monkeypatch.setenv("LOGS_BUCKET_NAME", "my-bucket")
    monkeypatch.setenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "true")
    setup_telemetry()
    assert os.environ["OTEL_SEMCONV_STABILITY_OPT_IN"] == "gen_ai_latest_experimental"


def test_no_bucket_sets_event_only_capture(monkeypatch) -> None:
    setup_telemetry()
    assert (
        os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] == "EVENT_ONLY"
    )


def test_no_bucket_always_forces_event_only(monkeypatch) -> None:
    # Platform may pre-set this to an invalid value ("true"); we must override it.
    monkeypatch.setenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "true")
    setup_telemetry()
    assert (
        os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] == "EVENT_ONLY"
    )


def test_setdefault_does_not_overwrite_existing_upload_path(monkeypatch) -> None:
    monkeypatch.setenv("LOGS_BUCKET_NAME", "my-bucket")
    monkeypatch.setenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "true")
    monkeypatch.setenv(
        "OTEL_INSTRUMENTATION_GENAI_UPLOAD_BASE_PATH",
        "gs://existing/path",
    )
    setup_telemetry()
    assert (
        os.environ["OTEL_INSTRUMENTATION_GENAI_UPLOAD_BASE_PATH"]
        == "gs://existing/path"
    )
