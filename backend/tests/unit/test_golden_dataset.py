from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.domain import EvaluationCase, GoldenDataset
from app.domain.golden_dataset import semver_key


def _case(case_id: str = "case-1") -> EvaluationCase:
    return EvaluationCase(id=case_id, name="n", category="c", query="q")


def test_creates_valid_dataset():
    dataset = GoldenDataset(
        name="support_bot",
        version="1.0.0",
        created_at=datetime.now(UTC),
        description="A golden dataset.",
        cases=[_case()],
    )

    assert dataset.id == "support_bot@1.0.0"


@pytest.mark.parametrize("version", ["1.0", "v1.0.0", "1.0.0-beta", "latest", ""])
def test_rejects_non_semver_version(version):
    with pytest.raises(ValidationError):
        GoldenDataset(
            name="support_bot",
            version=version,
            created_at=datetime.now(UTC),
            description="A golden dataset.",
            cases=[_case()],
        )


def test_rejects_empty_cases():
    with pytest.raises(ValidationError):
        GoldenDataset(
            name="support_bot",
            version="1.0.0",
            created_at=datetime.now(UTC),
            description="A golden dataset.",
            cases=[],
        )


def test_rejects_duplicate_case_ids():
    with pytest.raises(ValidationError):
        GoldenDataset(
            name="support_bot",
            version="1.0.0",
            created_at=datetime.now(UTC),
            description="A golden dataset.",
            cases=[_case("dup"), _case("dup")],
        )


@pytest.mark.parametrize("field", ["name", "description"])
def test_rejects_blank_name_or_description(field):
    payload = {
        "name": "support_bot",
        "version": "1.0.0",
        "created_at": datetime.now(UTC),
        "description": "A golden dataset.",
        "cases": [_case()],
    }
    payload[field] = "   "

    with pytest.raises(ValidationError):
        GoldenDataset(**payload)


def test_semver_key_orders_numerically_not_lexically():
    versions = ["1.9.0", "1.10.0", "1.2.0"]

    assert sorted(versions, key=semver_key) == ["1.2.0", "1.9.0", "1.10.0"]
