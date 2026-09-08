from app.providers.types import ProviderError, ProviderErrorType, ProviderRequest, ProviderResponse
from app.rag.pipeline import RAGPipeline
from app.rag.types import RetrievedChunk


class FakeRetriever:
    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self._chunks = chunks
        self.last_query: str | None = None
        self.last_k: int | None = None

    def retrieve(self, query: str, *, k: int | None = None) -> list[RetrievedChunk]:
        self.last_query = query
        self.last_k = k
        return self._chunks


class FakeProvider:
    def __init__(self, response: ProviderResponse) -> None:
        self.name = response.provider
        self.model = response.model
        self._response = response
        self.last_request: ProviderRequest | None = None

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        self.last_request = request
        return self._response


def _response(**overrides) -> ProviderResponse:
    defaults = {"provider": "fake", "model": "fake-model", "text": "the answer", "latency_ms": 5.0}
    defaults.update(overrides)
    return ProviderResponse(**defaults)


class TestRAGPipeline:
    def test_answer_retrieves_then_generates(self):
        chunk = RetrievedChunk(chunk_id="a::0", source_id="a", text="1-year warranty.")
        retriever = FakeRetriever([chunk])
        provider = FakeProvider(_response(text="Electronics get a 1-year warranty."))
        pipeline = RAGPipeline(retriever, provider)

        answer = pipeline.answer("What is the warranty?")

        assert answer.query == "What is the warranty?"
        assert answer.answer == "Electronics get a 1-year warranty."
        assert answer.retrieved_chunks == [chunk]
        assert answer.provider == "fake"
        assert answer.model == "fake-model"

    def test_prompt_sent_to_provider_includes_retrieved_context(self):
        chunk = RetrievedChunk(
            chunk_id="a::0", source_id="a", text="1-year warranty on electronics."
        )
        retriever = FakeRetriever([chunk])
        provider = FakeProvider(_response())
        pipeline = RAGPipeline(retriever, provider)

        pipeline.answer("What is the warranty?")

        assert "1-year warranty on electronics." in provider.last_request.prompt
        assert "What is the warranty?" in provider.last_request.prompt

    def test_case_id_is_forwarded_to_the_provider_request(self):
        provider = FakeProvider(_response())
        pipeline = RAGPipeline(FakeRetriever([]), provider)

        pipeline.answer("query", case_id="rag-001")

        assert provider.last_request.case_id == "rag-001"

    def test_top_k_is_forwarded_to_the_retriever(self):
        retriever = FakeRetriever([])
        pipeline = RAGPipeline(retriever, FakeProvider(_response()))

        pipeline.answer("query", top_k=2)

        assert retriever.last_k == 2

    def test_latency_combines_retrieval_and_generation(self):
        pipeline = RAGPipeline(FakeRetriever([]), FakeProvider(_response(latency_ms=100.0)))

        answer = pipeline.answer("query")

        assert answer.generation_latency_ms == 100.0
        assert answer.latency_ms >= 100.0
        assert answer.retrieval_latency_ms >= 0

    def test_tokens_and_cost_pass_through_from_provider_response(self):
        response = _response(input_tokens=10, output_tokens=5, estimated_cost=0.02)
        pipeline = RAGPipeline(FakeRetriever([]), FakeProvider(response))

        answer = pipeline.answer("query")

        assert answer.input_tokens == 10
        assert answer.output_tokens == 5
        assert answer.estimated_cost == 0.02

    def test_provider_error_is_captured_on_the_answer(self):
        response = _response(
            text="",
            error=ProviderError(error_type=ProviderErrorType.TIMEOUT, message="took too long"),
        )
        pipeline = RAGPipeline(FakeRetriever([]), FakeProvider(response))

        answer = pipeline.answer("query")

        assert answer.error == {"error_type": "timeout", "message": "took too long"}
        assert answer.answer == ""

    def test_no_retrieved_chunks_still_produces_an_answer(self):
        pipeline = RAGPipeline(FakeRetriever([]), FakeProvider(_response(text="I don't know.")))

        answer = pipeline.answer("something off-topic")

        assert answer.retrieved_chunks == []
        assert answer.answer == "I don't know."
