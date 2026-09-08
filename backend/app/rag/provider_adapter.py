from app.providers.base import Provider
from app.providers.types import ProviderError, ProviderErrorType, ProviderRequest, ProviderResponse
from app.rag.pipeline import RAGPipeline
from app.rag.retriever import Retriever


class RAGProvider:
    """Adapts a RAGPipeline to the Provider contract.

    This is the one place `app/rag` and `app/providers` meet in both
    directions: `RAGPipeline` already *consumes* a `Provider` for
    generation; `RAGProvider` makes the whole retrieve-then-generate
    pipeline *look like* a `Provider` too, so `EvaluationRunner` (Sprint 3)
    can grade a RAG case exactly like a plain-provider case — same
    `evaluate_case`, same evaluators, no RAG-specific branch in the runner.
    `ProviderResponse.retrieved_context` is what makes `CitationPresenceEvaluator`
    meaningful for RAG cases: it's the actual chunk text this run retrieved,
    not a pre-recorded fixture value.
    """

    def __init__(
        self, retriever: Retriever, generation_provider: Provider, *, name: str = "rag"
    ) -> None:
        self.name = name
        self.model = generation_provider.model
        self._pipeline = RAGPipeline(retriever, generation_provider)

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        answer = self._pipeline.answer(request.prompt, case_id=request.case_id)

        error = None
        if answer.error is not None:
            error = ProviderError(
                error_type=ProviderErrorType(answer.error["error_type"]),
                message=answer.error["message"],
            )

        return ProviderResponse(
            provider=self.name,
            model=self.model,
            text=answer.answer,
            retrieved_context=[chunk.text for chunk in answer.retrieved_chunks],
            latency_ms=answer.latency_ms,
            input_tokens=answer.input_tokens,
            output_tokens=answer.output_tokens,
            estimated_cost=answer.estimated_cost,
            error=error,
        )
