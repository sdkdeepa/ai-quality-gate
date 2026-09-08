import time

from app.providers.base import Provider
from app.providers.types import ProviderRequest
from app.rag.prompt import build_prompt
from app.rag.retriever import Retriever
from app.rag.types import RAGAnswer


class RAGPipeline:
    """query -> retrieve -> prompt -> provider -> answer.

    The generation step is any Sprint 3 `Provider` (`DeterministicProvider`,
    `OpenAIProvider`, `GeminiProvider`, ...) — the pipeline knows nothing
    about which one it was handed, so evaluating this RAG system against a
    live model vs. a deterministic fixture is a config choice, not a code
    change.
    """

    def __init__(self, retriever: Retriever, provider: Provider) -> None:
        self._retriever = retriever
        self._provider = provider

    def answer(
        self, query: str, *, case_id: str = "rag-query", top_k: int | None = None
    ) -> RAGAnswer:
        retrieval_start = time.perf_counter()
        chunks = self._retriever.retrieve(query, k=top_k)
        retrieval_latency_ms = (time.perf_counter() - retrieval_start) * 1000

        prompt = build_prompt(query, chunks)
        response = self._provider.generate(ProviderRequest(case_id=case_id, prompt=prompt))

        return RAGAnswer(
            query=query,
            answer=response.text,
            retrieved_chunks=chunks,
            provider=response.provider,
            model=response.model,
            retrieval_latency_ms=retrieval_latency_ms,
            generation_latency_ms=response.latency_ms,
            latency_ms=retrieval_latency_ms + response.latency_ms,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            estimated_cost=response.estimated_cost,
            error=(
                {"error_type": response.error.error_type.value, "message": response.error.message}
                if response.error is not None
                else None
            ),
        )
