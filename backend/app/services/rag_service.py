from app.core.exceptions import NotFoundError
from app.domain.case_result import CaseResult
from app.evaluation.runner import EvaluationRunner
from app.providers.base import Provider
from app.providers.factory import ProviderFactory
from app.rag.pipeline import RAGPipeline
from app.rag.provider_adapter import RAGProvider
from app.rag.retriever import Retriever
from app.rag.types import RAGAnswer, RetrievedChunk
from app.rag.vector_store import ChromaVectorStore
from app.services.dataset_service import DatasetService


class RAGService:
    """Orchestrates the sample RAG system-under-test: ad-hoc queries, chunk
    inspection, and grading one RAG dataset case through the same
    evaluators the rest of the Quality Gate uses.

    This service is deliberately separate from `EvaluationService` — the RAG
    system is a system *under test*, not part of the Gate's own evaluation
    surface (see `PROJECT_STATE.md`/`DECISIONS.md`: "the Quality Gate is not
    becoming a chatbot"). It reuses `ProviderFactory` for the generation step
    and `EvaluationRunner.evaluate_case` for grading, but owns no policy of
    its own.
    """

    def __init__(
        self,
        retriever: Retriever,
        vector_store: ChromaVectorStore,
        provider_factory: ProviderFactory,
        dataset_service: DatasetService,
        runner: EvaluationRunner,
        *,
        rag_dataset_name: str,
    ) -> None:
        self._retriever = retriever
        self._vector_store = vector_store
        self._provider_factory = provider_factory
        self._dataset_service = dataset_service
        self._runner = runner
        self._rag_dataset_name = rag_dataset_name

    def query(
        self, query: str, *, provider_name: str = "deterministic", top_k: int | None = None
    ) -> RAGAnswer:
        generation_provider = self._build_generation_provider(provider_name)
        pipeline = RAGPipeline(self._retriever, generation_provider)
        return pipeline.answer(query, case_id="rag-adhoc-query", top_k=top_k)

    def inspect_chunks(
        self, *, query: str | None = None, k: int | None = None
    ) -> list[RetrievedChunk]:
        if query is not None:
            return self._retriever.retrieve(query, k=k)
        return [
            RetrievedChunk(
                chunk_id=chunk["chunk_id"],
                source_id=chunk["metadata"]["source_id"],
                text=chunk["text"],
                metadata=chunk["metadata"],
            )
            for chunk in self._vector_store.get_all_chunks()
        ]

    def evaluate_case(
        self, case_id: str, *, provider_name: str = "deterministic"
    ) -> tuple[CaseResult, list[RetrievedChunk]]:
        dataset = self._dataset_service.get_dataset(self._rag_dataset_name, "latest")
        case = next((c for c in dataset.cases if c.id == case_id), None)
        if case is None:
            raise NotFoundError(f"no case {case_id!r} in dataset {dataset.id}")

        generation_provider = self._build_generation_provider(provider_name)
        rag_provider = RAGProvider(self._retriever, generation_provider)
        case_result = self._runner.evaluate_case(case, rag_provider)
        retrieved_chunks = self._retriever.retrieve(case.query)
        return case_result, retrieved_chunks

    def _build_generation_provider(self, provider_name: str) -> Provider:
        dataset = self._dataset_service.get_dataset(self._rag_dataset_name, "latest")
        return self._provider_factory.create(provider_name, dataset=dataset)
