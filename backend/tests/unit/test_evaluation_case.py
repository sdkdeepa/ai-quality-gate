import pytest
from pydantic import ValidationError

from app.domain import EvaluationCase, ExpectedBehavior


def test_creates_case_with_defaults():
    case = EvaluationCase(
        name="Refund policy", category="policy", query="What is the refund window?"
    )

    assert case.id
    assert case.expected_behavior == ExpectedBehavior.ANSWER
    assert case.critical is False
    assert case.tags == []
    assert case.reference_context == []
    assert case.metadata == {}


@pytest.mark.parametrize("field", ["name", "category", "query"])
def test_rejects_blank_required_fields(field):
    payload = {"name": "n", "category": "c", "query": "q"}
    payload[field] = "   "

    with pytest.raises(ValidationError):
        EvaluationCase(**payload)


def test_rejects_blank_tags():
    with pytest.raises(ValidationError):
        EvaluationCase(name="n", category="c", query="q", tags=["ok", "  "])


def test_strips_whitespace_from_required_fields():
    case = EvaluationCase(name="  Refund policy  ", category="policy", query="q")

    assert case.name == "Refund policy"


def test_critical_case_with_expected_behavior_unsupported():
    case = EvaluationCase(
        name="Out of scope query",
        category="unsupported",
        query="What's the weather tomorrow?",
        expected_behavior=ExpectedBehavior.UNSUPPORTED,
        critical=True,
    )

    assert case.critical is True
    assert case.expected_behavior == ExpectedBehavior.UNSUPPORTED
