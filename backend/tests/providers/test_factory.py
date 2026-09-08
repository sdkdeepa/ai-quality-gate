from datetime import UTC, datetime

import pytest

from app.core.config import Settings
from app.core.exceptions import ProviderConfigurationError
from app.domain.evaluation_case import EvaluationCase
from app.domain.golden_dataset import GoldenDataset
from app.providers.deterministic import DeterministicProvider
from app.providers.factory import ProviderFactory
from app.providers.gemini_provider import GeminiProvider
from app.providers.openai_provider import OpenAIProvider
from app.repositories.in_memory import InMemoryRepository
from app.services.dataset_service import DatasetService


def _dataset() -> GoldenDataset:
    return GoldenDataset(
        name="test_dataset",
        version="1.0.0",
        created_at=datetime.now(UTC),
        description="A test dataset.",
        cases=[EvaluationCase(id="c1", name="n", category="c", query="q")],
    )


def _dataset_service(tmp_path) -> DatasetService:
    dataset = _dataset()
    (tmp_path / "test_dataset.v1.0.0.json").write_text(dataset.model_dump_json())
    (tmp_path / "test_dataset.v1.0.0.fixtures.json").write_text(
        '{"c1": {"response": "ok", "latency_ms": 1.0, "input_tokens": 1, '
        '"output_tokens": 1, "estimated_cost": 0.0}}'
    )
    service = DatasetService(tmp_path, InMemoryRepository[GoldenDataset]())
    service.load_all()
    return service


class TestProviderFactory:
    def test_creates_deterministic_provider_from_fixtures(self, tmp_path):
        service = _dataset_service(tmp_path)
        factory = ProviderFactory(Settings(), service)

        provider = factory.create("deterministic", dataset=_dataset())

        assert isinstance(provider, DeterministicProvider)

    def test_creates_openai_provider_when_api_key_configured(self, tmp_path):
        service = _dataset_service(tmp_path)
        factory = ProviderFactory(Settings(openai_api_key="sk-test"), service)

        provider = factory.create("openai", dataset=_dataset())

        assert isinstance(provider, OpenAIProvider)

    def test_openai_without_api_key_raises_configuration_error(self, tmp_path):
        service = _dataset_service(tmp_path)
        factory = ProviderFactory(Settings(openai_api_key=None), service)

        with pytest.raises(ProviderConfigurationError):
            factory.create("openai", dataset=_dataset())

    def test_creates_gemini_provider_when_api_key_configured(self, tmp_path):
        service = _dataset_service(tmp_path)
        factory = ProviderFactory(Settings(gemini_api_key="test-key"), service)

        provider = factory.create("gemini", dataset=_dataset())

        assert isinstance(provider, GeminiProvider)

    def test_gemini_without_api_key_raises_configuration_error(self, tmp_path):
        service = _dataset_service(tmp_path)
        factory = ProviderFactory(Settings(gemini_api_key=None), service)

        with pytest.raises(ProviderConfigurationError):
            factory.create("gemini", dataset=_dataset())

    def test_unknown_provider_raises_configuration_error(self, tmp_path):
        service = _dataset_service(tmp_path)
        factory = ProviderFactory(Settings(), service)

        with pytest.raises(ProviderConfigurationError):
            factory.create("not-a-real-provider", dataset=_dataset())
