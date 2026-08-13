import json

import pytest

from app.core.exceptions import DatasetValidationError, FixtureValidationError, NotFoundError
from app.domain.golden_dataset import GoldenDataset
from app.repositories.in_memory import InMemoryRepository
from app.services.dataset_service import DatasetService, parse_dataset

VALID_DATASET = {
    "name": "sample",
    "version": "1.0.0",
    "created_at": "2026-01-01T00:00:00Z",
    "description": "A sample dataset.",
    "cases": [{"id": "c1", "name": "Case one", "category": "answerable", "query": "What is up?"}],
}

VALID_FIXTURES = {
    "c1": {
        "response": "not much",
        "latency_ms": 100.0,
        "input_tokens": 5,
        "output_tokens": 5,
        "estimated_cost": 0.001,
    }
}


def _service(tmp_path) -> DatasetService:
    return DatasetService(tmp_path, InMemoryRepository[GoldenDataset]())


def _write(tmp_path, name: str, payload) -> None:
    (tmp_path / name).write_text(json.dumps(payload))


class TestParseDataset:
    def test_parses_valid_json(self):
        dataset = parse_dataset(json.dumps(VALID_DATASET))

        assert dataset.name == "sample"
        assert len(dataset.cases) == 1

    def test_rejects_malformed_json(self):
        with pytest.raises(DatasetValidationError):
            parse_dataset("{not valid json")

    def test_rejects_schema_violation(self):
        broken = {**VALID_DATASET, "version": "not-a-semver"}

        with pytest.raises(DatasetValidationError):
            parse_dataset(json.dumps(broken))

    def test_rejects_missing_required_field(self):
        broken = dict(VALID_DATASET)
        del broken["description"]

        with pytest.raises(DatasetValidationError):
            parse_dataset(json.dumps(broken))


class TestDatasetServiceLoadAll:
    def test_loads_valid_dataset_files(self, tmp_path):
        _write(tmp_path, "sample.v1.0.0.json", VALID_DATASET)
        service = _service(tmp_path)

        service.load_all()

        datasets = service.list_datasets()
        assert len(datasets) == 1
        assert datasets[0].id == "sample@1.0.0"

    def test_skips_fixtures_files(self, tmp_path):
        _write(tmp_path, "sample.v1.0.0.json", VALID_DATASET)
        _write(tmp_path, "sample.v1.0.0.fixtures.json", VALID_FIXTURES)
        service = _service(tmp_path)

        service.load_all()

        assert len(service.list_datasets()) == 1

    def test_raises_on_malformed_dataset_file(self, tmp_path):
        (tmp_path / "broken.json").write_text("{not valid json")
        service = _service(tmp_path)

        with pytest.raises(DatasetValidationError) as exc_info:
            service.load_all()
        assert "broken.json" in str(exc_info.value)

    def test_missing_directory_loads_nothing(self, tmp_path):
        service = _service(tmp_path / "does-not-exist")

        service.load_all()

        assert service.list_datasets() == []


class TestDatasetServiceGetDataset:
    def test_get_dataset_latest_resolves_highest_semver(self, tmp_path):
        _write(tmp_path, "sample.v1.0.0.json", VALID_DATASET)
        _write(tmp_path, "sample.v1.2.0.json", {**VALID_DATASET, "version": "1.2.0"})
        service = _service(tmp_path)
        service.load_all()

        dataset = service.get_dataset("sample", "latest")

        assert dataset.version == "1.2.0"

    def test_get_dataset_specific_version(self, tmp_path):
        _write(tmp_path, "sample.v1.0.0.json", VALID_DATASET)
        service = _service(tmp_path)
        service.load_all()

        dataset = service.get_dataset("sample", "1.0.0")

        assert dataset.version == "1.0.0"

    def test_get_dataset_unknown_name_raises_not_found(self, tmp_path):
        service = _service(tmp_path)

        with pytest.raises(NotFoundError):
            service.get_dataset("missing")

    def test_get_dataset_unknown_version_raises_not_found(self, tmp_path):
        _write(tmp_path, "sample.v1.0.0.json", VALID_DATASET)
        service = _service(tmp_path)
        service.load_all()

        with pytest.raises(NotFoundError):
            service.get_dataset("sample", "9.9.9")


class TestDatasetServiceGetFixtures:
    def test_loads_valid_fixtures(self, tmp_path):
        _write(tmp_path, "sample.v1.0.0.json", VALID_DATASET)
        _write(tmp_path, "sample.v1.0.0.fixtures.json", VALID_FIXTURES)
        service = _service(tmp_path)
        service.load_all()
        dataset = service.get_dataset("sample", "1.0.0")

        fixtures = service.get_fixtures(dataset)

        assert fixtures["c1"].response == "not much"

    def test_missing_fixtures_file_raises(self, tmp_path):
        _write(tmp_path, "sample.v1.0.0.json", VALID_DATASET)
        service = _service(tmp_path)
        service.load_all()
        dataset = service.get_dataset("sample", "1.0.0")

        with pytest.raises(FixtureValidationError):
            service.get_fixtures(dataset)

    def test_malformed_fixtures_json_raises(self, tmp_path):
        _write(tmp_path, "sample.v1.0.0.json", VALID_DATASET)
        (tmp_path / "sample.v1.0.0.fixtures.json").write_text("{not valid json")
        service = _service(tmp_path)
        service.load_all()
        dataset = service.get_dataset("sample", "1.0.0")

        with pytest.raises(FixtureValidationError):
            service.get_fixtures(dataset)

    def test_fixtures_missing_required_field_raises(self, tmp_path):
        _write(tmp_path, "sample.v1.0.0.json", VALID_DATASET)
        _write(tmp_path, "sample.v1.0.0.fixtures.json", {"c1": {"response": "hi"}})
        service = _service(tmp_path)
        service.load_all()
        dataset = service.get_dataset("sample", "1.0.0")

        with pytest.raises(FixtureValidationError):
            service.get_fixtures(dataset)
