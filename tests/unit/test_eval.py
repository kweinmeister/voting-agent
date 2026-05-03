"""Unit tests for tests/eval/run_platform_eval.py — no GCP calls, all mocked."""

import json
from unittest.mock import MagicMock

import pytest

import tests.eval.run_platform_eval as eval_module
from tests.eval.run_platform_eval import (
    _TERMINAL_STATES,
    METRICS,
    PROMPTS,
    _print_per_prompt_results,
    load_agent_resource_name,
    main,
)

# ── Constants ─────────────────────────────────────────────────────────────────


class TestConstants:
    def test_prompt_count(self) -> None:
        assert len(PROMPTS) == 10

    def test_prompts_are_nonempty_strings(self) -> None:
        assert all(isinstance(p, str) and p.strip() for p in PROMPTS)

    def test_prompts_are_unique(self) -> None:
        assert len(set(PROMPTS)) == len(PROMPTS)

    def test_blender_prompt_present(self) -> None:
        # Edge-case prompt that exercises minimal input handling
        assert "A blender." in PROMPTS

    def test_metric_count(self) -> None:
        assert len(METRICS) == 4

    def test_terminal_states_include_succeeded_failed_cancelled(self) -> None:
        from vertexai import types

        assert types.EvaluationRunState.SUCCEEDED in _TERMINAL_STATES
        assert types.EvaluationRunState.FAILED in _TERMINAL_STATES
        assert types.EvaluationRunState.CANCELLED in _TERMINAL_STATES


# ── load_agent_resource_name ──────────────────────────────────────────────────


class TestLoadAgentResourceName:
    def test_returns_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        resource = "projects/123/locations/us-east1/reasoningEngines/456"
        monkeypatch.setenv("AGENT_RESOURCE_NAME", resource)
        assert load_agent_resource_name() == resource

    def test_env_var_takes_priority_over_file(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        monkeypatch.setenv("AGENT_RESOURCE_NAME", "from-env")
        (tmp_path / "deployment_metadata.json").write_text(  # type: ignore[operator]
            json.dumps({"remote_agent_runtime_id": "from-file"}),
        )
        assert load_agent_resource_name() == "from-env"

    def test_falls_back_to_metadata_file(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        monkeypatch.delenv("AGENT_RESOURCE_NAME", raising=False)
        (tmp_path / "deployment_metadata.json").write_text(  # type: ignore[operator]
            json.dumps(
                {
                    "remote_agent_runtime_id": "projects/p/locations/l/reasoningEngines/r",
                },
            ),
        )

        class _FakeParents:
            def __getitem__(self, _: int) -> pytest.TempPathFactory:
                return tmp_path

        class _FakePath:
            def __init__(self, *_: object) -> None:
                pass

            @property
            def parents(self) -> _FakeParents:
                return _FakeParents()

        monkeypatch.setattr(eval_module, "Path", _FakePath)
        assert load_agent_resource_name() == "projects/p/locations/l/reasoningEngines/r"

    def test_exits_when_no_source_available(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        monkeypatch.delenv("AGENT_RESOURCE_NAME", raising=False)

        class _FakeParents:
            def __getitem__(self, _: int) -> pytest.TempPathFactory:
                return tmp_path

        class _FakePath:
            def __init__(self, *_: object) -> None:
                pass

            @property
            def parents(self) -> _FakeParents:
                return _FakeParents()

        monkeypatch.setattr(eval_module, "Path", _FakePath)
        with pytest.raises(SystemExit):
            load_agent_resource_name()

    def test_exits_when_metadata_missing_key(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        monkeypatch.delenv("AGENT_RESOURCE_NAME", raising=False)
        (tmp_path / "deployment_metadata.json").write_text(  # type: ignore[operator]
            json.dumps({"other_key": "value"}),
        )

        class _FakeParents:
            def __getitem__(self, _: int) -> pytest.TempPathFactory:
                return tmp_path

        class _FakePath:
            def __init__(self, *_: object) -> None:
                pass

            @property
            def parents(self) -> _FakeParents:
                return _FakeParents()

        monkeypatch.setattr(eval_module, "Path", _FakePath)
        with pytest.raises(SystemExit):
            load_agent_resource_name()


# ── main() — env-var validation ───────────────────────────────────────────────


class TestMainEnvVarValidation:
    def test_exits_without_gcp_project_id(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
        with pytest.raises(SystemExit):
            main()

    def test_exits_without_gcs_eval_bucket(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("GCP_PROJECT_ID", "my-project")
        monkeypatch.delenv("GCS_EVAL_BUCKET", raising=False)
        with pytest.raises(SystemExit):
            main()


# ── _print_per_prompt_results ─────────────────────────────────────────────────


def _make_blob(name: str, data: dict) -> MagicMock:
    blob = MagicMock()
    blob.name = name
    blob.download_as_text.return_value = json.dumps(data)
    return blob


def _make_result_payload(
    run_id: str,
    prompt: str,
    *,
    error: dict | None = None,
    response_text: str | None = None,
    metric_results: dict | None = None,
) -> dict:
    candidate: dict = {"candidate": "candidate-1"}
    if error:
        candidate["error"] = error
    else:
        candidate["text"] = response_text or ""
        if metric_results:
            candidate["metricResults"] = metric_results
    return {
        "evaluationRun": f"projects/p/locations/us-central1/evaluationRuns/{run_id}",
        "request": {
            "prompt": {"text": prompt},
            "candidateResponses": [candidate],
        },
    }


@pytest.fixture
def mock_gcs(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Returns a factory for controlling what blobs list_blobs yields."""
    mock_client_instance = MagicMock()
    mock_gcs_class = MagicMock(return_value=mock_client_instance)
    monkeypatch.setattr(eval_module, "gcs", MagicMock(Client=mock_gcs_class))
    return mock_client_instance


class TestPrintPerPromptResults:
    def test_prints_error_case(
        self,
        mock_gcs: MagicMock,
        capsys: pytest.CaptureFixture,
    ) -> None:
        payload = _make_result_payload(
            "42",
            "A blender.",
            error={"code": 3, "message": "region mismatch;detail"},
        )
        mock_gcs.bucket.return_value.list_blobs.return_value = [
            _make_blob("evals/result_1.json", payload),
        ]
        _print_per_prompt_results(
            "gs://bucket/evals",
            "projects/p/locations/x/evaluationRuns/42",
        )
        out = capsys.readouterr().out
        assert "A blender." in out
        assert "ERROR" in out
        assert "region mismatch" in out

    def test_prints_success_case_with_metrics(
        self,
        mock_gcs: MagicMock,
        capsys: pytest.CaptureFixture,
    ) -> None:
        payload = _make_result_payload(
            "42",
            "A blender.",
            response_text="Buy the BlendMaster 3000!",
            metric_results={"safety_v1": {"score": 1.0, "verdict": "PASS"}},
        )
        mock_gcs.bucket.return_value.list_blobs.return_value = [
            _make_blob("evals/result_1.json", payload),
        ]
        _print_per_prompt_results(
            "gs://bucket/evals",
            "projects/p/locations/x/evaluationRuns/42",
        )
        out = capsys.readouterr().out
        assert "BlendMaster" in out
        assert "safety_v1" in out
        assert "1.000" in out
        assert "(PASS)" in out

    def test_skips_blobs_from_other_runs(
        self,
        mock_gcs: MagicMock,
        capsys: pytest.CaptureFixture,
    ) -> None:
        other_run_payload = _make_result_payload("99", "Other prompt.")
        mock_gcs.bucket.return_value.list_blobs.return_value = [
            _make_blob("evals/result_1.json", other_run_payload),
        ]
        _print_per_prompt_results(
            "gs://bucket/evals",
            "projects/p/locations/x/evaluationRuns/42",
        )
        out = capsys.readouterr().out
        assert "no per-prompt result files found" in out

    def test_skips_non_result_blobs(
        self,
        mock_gcs: MagicMock,
        capsys: pytest.CaptureFixture,
    ) -> None:
        mock_gcs.bucket.return_value.list_blobs.return_value = [
            _make_blob("evals/request_abc.json", {}),
            _make_blob("evals/metadata.json", {}),
        ]
        _print_per_prompt_results(
            "gs://bucket/evals",
            "projects/p/locations/x/evaluationRuns/42",
        )
        out = capsys.readouterr().out
        assert "no per-prompt result files found" in out

    def test_handles_malformed_blob_gracefully(
        self,
        mock_gcs: MagicMock,
        capsys: pytest.CaptureFixture,
    ) -> None:
        bad_blob = MagicMock()
        bad_blob.name = "evals/result_bad.json"
        bad_blob.download_as_text.return_value = "not json {"
        mock_gcs.bucket.return_value.list_blobs.return_value = [bad_blob]
        _print_per_prompt_results(
            "gs://bucket/evals",
            "projects/p/locations/x/evaluationRuns/42",
        )
        # must not raise

    def test_truncates_long_error_message(
        self,
        mock_gcs: MagicMock,
        capsys: pytest.CaptureFixture,
    ) -> None:
        long_msg = "first part;" + "x" * 200
        payload = _make_result_payload(
            "42",
            "A blender.",
            error={"code": 3, "message": long_msg},
        )
        mock_gcs.bucket.return_value.list_blobs.return_value = [
            _make_blob("evals/result_1.json", payload),
        ]
        _print_per_prompt_results(
            "gs://bucket/evals",
            "projects/p/locations/x/evaluationRuns/42",
        )
        out = capsys.readouterr().out
        # Should show only the part before the semicolon, not the full 200-char tail
        assert "first part" in out
        assert "x" * 200 not in out


# ── main() — happy path ───────────────────────────────────────────────────────


def _make_succeeded_run(metrics: dict | None = None) -> MagicMock:
    from vertexai import types

    summary_metrics = MagicMock()
    summary_metrics.metrics = metrics if metrics is not None else {"safety_v1": 1.0}
    summary_metrics.total_items = 10
    summary_metrics.failed_items = None

    run_results = MagicMock()
    run_results.summary_metrics = summary_metrics

    run = MagicMock()
    run.name = "projects/p/locations/us-central1/evaluationRuns/123"
    run.state = types.EvaluationRunState.SUCCEEDED
    run.evaluation_run_results = run_results
    return run


@pytest.fixture
def mock_gcp(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Patches vertexai.init, Client, gcs, and time; returns mock handles."""
    succeeded_run = _make_succeeded_run()

    mock_client = MagicMock()
    mock_client.evals.create_evaluation_run.return_value = succeeded_run
    mock_client.evals.get_evaluation_run.return_value = succeeded_run
    mock_Client = MagicMock(return_value=mock_client)

    # Mock GCS so _print_per_prompt_results returns immediately with no items
    mock_gcs_instance = MagicMock()
    mock_gcs_instance.bucket.return_value.list_blobs.return_value = []

    monkeypatch.setenv("GCP_PROJECT_ID", "my-project")
    monkeypatch.setenv("GCS_EVAL_BUCKET", "gs://bucket/evals")
    monkeypatch.setenv(
        "AGENT_RESOURCE_NAME",
        "projects/p/locations/us-east1/reasoningEngines/r",
    )
    monkeypatch.setattr(eval_module, "vertexai", MagicMock())
    monkeypatch.setattr(eval_module, "Client", mock_Client)
    monkeypatch.setattr(
        eval_module,
        "gcs",
        MagicMock(Client=MagicMock(return_value=mock_gcs_instance)),
    )
    monkeypatch.setattr(eval_module, "time", MagicMock())

    return {
        "client": mock_client,
        "Client": mock_Client,
        "succeeded_run": succeeded_run,
    }


class TestMainHappyPath:
    def test_creates_evaluation_run_once(self, mock_gcp: dict) -> None:
        main()
        mock_gcp["client"].evals.create_evaluation_run.assert_called_once()

    def test_does_not_poll_when_already_succeeded(self, mock_gcp: dict) -> None:
        main()
        mock_gcp["client"].evals.get_evaluation_run.assert_not_called()

    def test_dataset_contains_all_prompts(self, mock_gcp: dict) -> None:
        main()
        call_kwargs = mock_gcp["client"].evals.create_evaluation_run.call_args
        dataset = call_kwargs.kwargs["dataset"]
        assert list(dataset.eval_dataset_df["prompt"]) == PROMPTS

    def test_passes_agent_resource_name_in_inference_config(
        self,
        mock_gcp: dict,
    ) -> None:
        main()
        call_kwargs = mock_gcp["client"].evals.create_evaluation_run.call_args
        inference_configs = call_kwargs.kwargs["inference_configs"]
        candidate = next(iter(inference_configs.values()))
        assert candidate.agent_run_config.agent_engine == (
            "projects/p/locations/us-east1/reasoningEngines/r"
        )

    def test_uses_default_eval_region(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_gcp: dict,
    ) -> None:
        monkeypatch.delenv("EVAL_REGION", raising=False)
        main()
        assert mock_gcp["Client"].call_args_list[0].kwargs["location"] == "us-central1"

    def test_respects_custom_eval_region(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_gcp: dict,
    ) -> None:
        monkeypatch.setenv("EVAL_REGION", "us-east4")
        main()
        assert mock_gcp["Client"].call_args_list[0].kwargs["location"] == "us-east4"

    def test_polls_until_terminal_state(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_gcp: dict,
    ) -> None:
        from vertexai import types

        running_run = MagicMock()
        running_run.state = types.EvaluationRunState.RUNNING
        succeeded_run = mock_gcp["succeeded_run"]

        mock_gcp["client"].evals.create_evaluation_run.return_value = running_run
        mock_gcp["client"].evals.get_evaluation_run.side_effect = [
            running_run,
            succeeded_run,
        ]
        main()
        assert mock_gcp["client"].evals.get_evaluation_run.call_count == 2

    def test_exits_on_failed_state(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_gcp: dict,
    ) -> None:
        from vertexai import types

        failed_run = MagicMock()
        failed_run.state = types.EvaluationRunState.FAILED
        failed_run.error = "some error"

        mock_gcp["client"].evals.create_evaluation_run.return_value = failed_run
        with pytest.raises(SystemExit):
            main()

    def test_prints_summary_metrics(
        self,
        mock_gcp: dict,
        capsys: pytest.CaptureFixture,
    ) -> None:
        main()
        out = capsys.readouterr().out
        assert "safety_v1" in out
        assert "1.0" in out

    def test_prints_console_link(
        self,
        mock_gcp: dict,
        capsys: pytest.CaptureFixture,
    ) -> None:
        main()
        out = capsys.readouterr().out
        assert "console.cloud.google.com" in out
        assert "123" in out

    def test_handles_empty_metrics_without_raising(self, mock_gcp: dict) -> None:
        mock_gcp["succeeded_run"].evaluation_run_results.summary_metrics.metrics = {}
        main()

    def test_handles_none_run_results_without_raising(self, mock_gcp: dict) -> None:
        mock_gcp["succeeded_run"].evaluation_run_results = None
        main()
