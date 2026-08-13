import json
import logging
from pathlib import Path

from pydantic import ValidationError

from app.core.exceptions import DatasetValidationError, FixtureValidationError, NotFoundError
from app.domain.golden_dataset import GoldenDataset, semver_key
from app.evaluation.types import FixtureResponse
from app.repositories.in_memory import InMemoryRepository

logger = logging.getLogger("app.dataset")


def parse_dataset(raw_text: str, *, source: str = "<unknown>") -> GoldenDataset:
    """Parse and validate raw dataset JSON text into a GoldenDataset.

    Raises DatasetValidationError (never a raw json/pydantic exception) so
    callers — API handlers or tests — get a single, well-known error type
    for both malformed JSON and semantic validation failures.
    """
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise DatasetValidationError(f"{source}: invalid JSON ({exc})") from exc
    try:
        return GoldenDataset.model_validate(raw)
    except ValidationError as exc:
        raise DatasetValidationError(f"{source}: {exc}") from exc


class DatasetService:
    """Loads, validates, and serves versioned golden datasets from a directory of JSON files.

    Dataset file naming convention: `{name}.v{version}.json`. A dataset may
    have a matching `{name}.v{version}.fixtures.json` file mapping case id
    to a deterministic FixtureResponse, used by the evaluation runner.
    """

    def __init__(self, dataset_dir: Path, repository: InMemoryRepository[GoldenDataset]) -> None:
        self._dataset_dir = dataset_dir
        self._repository = repository

    def load_all(self) -> None:
        if not self._dataset_dir.is_dir():
            logger.warning(
                "dataset directory %s does not exist; no datasets loaded", self._dataset_dir
            )
            return
        for path in sorted(self._dataset_dir.glob("*.json")):
            if path.name.endswith(".fixtures.json"):
                continue
            dataset = parse_dataset(path.read_text(), source=path.name)
            self._repository.add(dataset)
            logger.info("loaded dataset %s", dataset.id)

    def list_datasets(self) -> list[GoldenDataset]:
        return sorted(self._repository.list(), key=lambda d: (d.name, semver_key(d.version)))

    def get_dataset(self, name: str, version: str | None = None) -> GoldenDataset:
        candidates = [d for d in self._repository.list() if d.name == name]
        if not candidates:
            raise NotFoundError(f"no dataset named {name!r}")
        if version is None or version == "latest":
            return max(candidates, key=lambda d: semver_key(d.version))
        for dataset in candidates:
            if dataset.version == version:
                return dataset
        raise NotFoundError(f"dataset {name!r} has no version {version!r}")

    def get_fixtures(self, dataset: GoldenDataset) -> dict[str, FixtureResponse]:
        fixture_path = self._fixture_path(dataset)
        if not fixture_path.is_file():
            raise FixtureValidationError(
                f"no fixtures file found at {fixture_path.name} for dataset {dataset.id}"
            )
        try:
            raw = json.loads(fixture_path.read_text())
        except json.JSONDecodeError as exc:
            raise FixtureValidationError(f"{fixture_path.name}: invalid JSON ({exc})") from exc
        try:
            return {
                case_id: FixtureResponse.model_validate(payload) for case_id, payload in raw.items()
            }
        except ValidationError as exc:
            raise FixtureValidationError(f"{fixture_path.name}: {exc}") from exc

    def _fixture_path(self, dataset: GoldenDataset) -> Path:
        return self._dataset_dir / f"{dataset.name}.v{dataset.version}.fixtures.json"
