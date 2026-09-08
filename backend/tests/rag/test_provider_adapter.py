from app.providers.types import ProviderError, ProviderErrorType, ProviderRequest, ProviderResponse
from app.rag.provider_adapter import RAGProvider
from app.rag.types import RetrievedChunk


class FakeRetriever:
    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self._chunks = chunks

    def retrieve(self, query: str, *, k: int | None = None) -> list[RetrievedChunk]:
        return self._chunks


class FakeGenerationProvider:
    def __init__(self, response: ProviderResponse, *, model: str = "fixture-v1") -> None:
        self.name = "fake-generation"
        self.model = model
        self._response = response
        self.last_request: ProviderRequest | None = None

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        self.last_request = request
        return self._response


def _response(**overrides) -> ProviderResponse:
    defaults = {
        "provider": "fake-generation",
        "model": "fixture-v1",
        "text": "the answer",
        "latency_ms": 5.0,
    }
    defaults.update(overrides)
    return ProviderResponse(**defaults)


class TestRAGProvider:
    def test_satisfies_provider_contract_shape(self):
        rag_provider = RAGProvider(FakeRetriever([]), FakeGenerationProvider(_response()))

        assert rag_provider.name == "rag"
        assert rag_provider.model == "fixture-v1"

    def test_generate_returns_normalized_provider_response(self):
        chunk = RetrievedChunk(chunk_id="a::0", source_id="a", text="1-year warranty.")
        rag_provider = RAGProvider(
            FakeRetriever([chunk]), FakeGenerationProvider(_response(text="1-year."))
        )

        response = rag_provider.generate(
            ProviderRequest(case_id="rag-001", prompt="What is the warranty?")
        )

        assert response.provider == "rag"
        assert response.text == "1-year."
        assert response.retrieved_context == ["1-year warranty."]
        assert response.error is None

    def test_case_id_reaches_the_generation_provider(self):
        generation_provider = FakeGenerationProvider(_response())
        rag_provider = RAGProvider(FakeRetriever([]), generation_provider)

        rag_provider.generate(ProviderRequest(case_id="rag-007", prompt="query"))

        assert generation_provider.last_request.case_id == "rag-007"

    def test_generation_provider_error_is_normalized_on_the_response(self):
        response = _response(
            error=ProviderError(error_type=ProviderErrorType.AUTHENTICATION, message="bad key")
        )
        rag_provider = RAGProvider(FakeRetriever([]), FakeGenerationProvider(response))

        result = rag_provider.generate(ProviderRequest(case_id="c1", prompt="q"))

        assert result.error is not None
        assert result.error.error_type == ProviderErrorType.AUTHENTICATION
        assert result.error.message == "bad key"

    def test_no_retrieved_chunks_yields_empty_retrieved_context(self):
        rag_provider = RAGProvider(FakeRetriever([]), FakeGenerationProvider(_response()))

        response = rag_provider.generate(ProviderRequest(case_id="c1", prompt="q"))

        assert response.retrieved_context == []

    def test_custom_name_is_reported(self):
        rag_provider = RAGProvider(
            FakeRetriever([]), FakeGenerationProvider(_response()), name="rag-custom"
        )

        assert rag_provider.name == "rag-custom"
