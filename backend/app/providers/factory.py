from app.core.config import Settings
from app.core.exceptions import ProviderConfigurationError
from app.domain.golden_dataset import GoldenDataset
from app.providers.base import Provider
from app.providers.deterministic import DeterministicProvider
from app.providers.gemini_provider import GeminiProvider
from app.providers.openai_provider import OpenAIProvider
from app.services.dataset_service import DatasetService

KNOWN_PROVIDERS = ("deterministic", "openai", "gemini")


class ProviderFactory:
    """Builds a Provider by name, resolving API keys/models from Settings.

    The only place (besides the provider modules themselves) that knows the
    set of available provider names — evaluation_service and the API layer
    just pass a name through.
    """

    def __init__(self, settings: Settings, dataset_service: DatasetService) -> None:
        self._settings = settings
        self._dataset_service = dataset_service

    def create(self, provider_name: str, *, dataset: GoldenDataset) -> Provider:
        if provider_name == "deterministic":
            fixtures = self._dataset_service.get_fixtures(dataset)
            return DeterministicProvider(fixtures)

        if provider_name == "openai":
            if not self._settings.openai_api_key:
                raise ProviderConfigurationError(
                    "AQG_OPENAI_API_KEY is not set; cannot use provider 'openai'"
                )
            return OpenAIProvider(
                self._settings.openai_api_key,
                model=self._settings.openai_model,
                timeout_seconds=self._settings.provider_timeout_seconds,
            )

        if provider_name == "gemini":
            if not self._settings.gemini_api_key:
                raise ProviderConfigurationError(
                    "AQG_GEMINI_API_KEY is not set; cannot use provider 'gemini'"
                )
            return GeminiProvider(
                self._settings.gemini_api_key,
                model=self._settings.gemini_model,
                timeout_seconds=self._settings.provider_timeout_seconds,
            )

        raise ProviderConfigurationError(
            f"unknown provider {provider_name!r}; expected one of {KNOWN_PROVIDERS}"
        )
