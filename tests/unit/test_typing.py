"""Unit tests for the Feedback Pydantic model."""

import typing

import pytest
from pydantic import ValidationError

from app.app_utils.typing import Feedback


def test_required_score() -> None:
    with pytest.raises(ValidationError):
        Feedback.model_validate({})


def test_int_score() -> None:
    f = Feedback(score=1)
    assert f.score == 1


def test_float_score() -> None:
    f = Feedback(score=0.75)
    assert f.score == 0.75


def test_defaults() -> None:
    f = Feedback(score=1)
    assert f.text == ""
    assert f.log_type == "feedback"
    assert f.service_name == "voting-agent"


def test_user_id_and_session_id_are_unique() -> None:
    f1 = Feedback(score=1)
    f2 = Feedback(score=1)
    assert f1.user_id != f2.user_id
    assert f1.session_id != f2.session_id


def test_user_id_and_session_id_are_valid_uuids() -> None:
    import uuid

    f = Feedback(score=1)
    uuid.UUID(f.user_id)
    uuid.UUID(f.session_id)


def test_explicit_user_and_session_ids() -> None:
    f = Feedback(score=1, user_id="user-abc", session_id="sess-xyz")
    assert f.user_id == "user-abc"
    assert f.session_id == "sess-xyz"


def test_text_accepts_none() -> None:
    f = Feedback(score=1, text=None)
    assert f.text is None


def test_invalid_log_type() -> None:
    with pytest.raises(ValidationError):
        kwargs = {"score": 1, "log_type": "invalid"}
        Feedback(**typing.cast("typing.Any", kwargs))


def test_invalid_service_name() -> None:
    with pytest.raises(ValidationError):
        kwargs = {"score": 1, "service_name": "wrong-service"}
        Feedback(**typing.cast("typing.Any", kwargs))


def test_model_validate() -> None:
    f = Feedback.model_validate({"score": 2, "user_id": "u1", "session_id": "s1"})
    assert f.score == 2
    assert f.user_id == "u1"


def test_model_dump_includes_all_fields() -> None:
    f = Feedback(score=1, text="good", user_id="u", session_id="s")
    d = f.model_dump()
    assert d["score"] == 1
    assert d["text"] == "good"
    assert d["log_type"] == "feedback"
    assert d["service_name"] == "voting-agent"
