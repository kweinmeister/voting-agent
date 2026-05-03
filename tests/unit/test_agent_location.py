"""Unit tests for _agent_location — no GCP credentials needed."""

import pytest

from frontend import main


@pytest.fixture(autouse=True)
def reset_agent_resource_name(monkeypatch) -> None:
    monkeypatch.setattr(main, "AGENT_RESOURCE_NAME", None)
    monkeypatch.setattr(main, "GCP_LOCATION", "us-central1")


def test_extracts_region_from_valid_resource_name(monkeypatch) -> None:
    monkeypatch.setattr(
        main,
        "AGENT_RESOURCE_NAME",
        "projects/123/locations/us-east1/reasoningEngines/456",
    )
    assert main._agent_location() == "us-east1"


def test_extracts_different_region(monkeypatch) -> None:
    monkeypatch.setattr(
        main,
        "AGENT_RESOURCE_NAME",
        "projects/123/locations/europe-west4/reasoningEngines/789",
    )
    assert main._agent_location() == "europe-west4"


def test_falls_back_to_gcp_location_when_unset() -> None:
    assert main._agent_location() == "us-central1"


def test_falls_back_to_gcp_location_on_malformed_name(monkeypatch) -> None:
    monkeypatch.setattr(main, "AGENT_RESOURCE_NAME", "not-a-valid-resource-name")
    assert main._agent_location() == "us-central1"


def test_falls_back_to_gcp_location_when_locations_segment_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        main,
        "AGENT_RESOURCE_NAME",
        "projects/123/reasoningEngines/456",
    )
    assert main._agent_location() == "us-central1"
