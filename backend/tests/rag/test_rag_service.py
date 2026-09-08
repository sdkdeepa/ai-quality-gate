import json
from datetime import UTC, datetime

import pytest
from langchain_core.documents import Document

from app.core.config import Settings
from app.core.exceptions import NotFoundError, ProviderConfigurationError
from app.domain.golden_dataset import GoldenDataset
from app.evaluation.runner import EvaluationRunner
from app.providers.factory import ProviderFactory
from app.rag.embeddings import DeterministicEmbeddings
from app.rag.retriever import Retriever
from app.rag.vector_store import ChromaVectorStore
from app.repositories.in_memory import InMemoryRepository
from app.services.dataset_service import DatasetService
from app.services.rag_service import RAGService

DATASET_NAME = "rag_test_dataset"


def _dataset_service(tmp_path) -> DatasetService:
    dataset = {
        "name": DATASET_NAME,
        "version": "1.0.0",
        "created_at": datetime.now(UTC).isoformat(),
        "description": "test dataset",
        "cases": [
            {
                "id": "rag-c1",
                "name": "Warranty question",
                "category": "rag",
                "query": "What is the warranty length on electronics?",
                "expected_behavior": "answer",
                "metadata": {"required_phrases": ["1-year"]},
            },
            {
                "id": "rag-c2",
                "name": "Off-topic question",
                "category": "rag",
                "query": "Can you help me pick a birthday gift for my mom?",
                "expected_behavior": "unsupported",
            },
        ],
    }
    fixtures = {
        "rag-c1": {
            "response": "Electronics come with a 1-year warranty.",
            "latency_ms": 10.0,
            "input_tokens": 5,
            "output_tokens": 5,
            "estimated_cost": 0.001,
        },
        "rag-c2": {
            "response": "I don't have that information.",
            "latency_ms": 10.0,
            "input_tokens": 5,
            "output_tokens": 5,
            "estimated_cost": 0.001,
        },
    }
    (tmp_path / f"{DATASET_NAME}.v1.0.0.json").write_text(json.dumps(dataset))
    (tmp_path / f"{DATASET_NAME}.v1.0.0.fixtures.json").write_text(json.dumps(fixtures))
    service = DatasetService(tmp_path, InMemoryRepository[GoldenDataset]())
    service.load_all()
    return service


def _retriever(tmp_path) -> tuple[ChromaVectorStore, Retriever]:
    store = ChromaVectorStore(
        persist_directory=tmp_path / "chroma",
        collection_name="rag-corpus",
        embeddings=DeterministicEmbeddings(),
    )
    store.replace_all(
        [
            Document(
                page_content="Electronics come with a 1-year limited warranty from purchase.",
                metadata={"chunk_id": "warranty::0", "source_id": "warranty", "chunk_index": 0},
            )
        ]
    )
    return store, Retriever(store, top_k=4, relevance_threshold=0.08)


def _service(tmp_path) -> RAGService:
    dataset_dir = tmp_path / "datasets"
    dataset_dir.mkdir()
    dataset_service = _dataset_service(dataset_dir)
    vector_store, retriever = _retriever(tmp_path)
    provider_factory = ProviderFactory(Settings(), dataset_service)
    runner = EvaluationRunner()
    return RAGService(
        retriever=retriever,
        vector_store=vector_store,
        provider_factory=provider_factory,
        dataset_service=dataset_service,
        runner=runner,
        rag_dataset_name=DATASET_NAME,
    )


class TestRAGServiceQuery:
    def test_query_retrieves_real_context_even_when_generation_has_no_fixture(self, tmp_path):
        # An ad-hoc query has no case_id, so DeterministicProvider can't find a
        # canned answer for it — this exercises the same normalized-failure path
        # a real API outage would (RAGAnswer.error set, no exception raised),
        # while proving retrieval genuinely ran against the real corpus.
        service = _service(tmp_path)

        answer = service.query(
            "What is the warranty length on electronics?", provider_name="deterministic"
        )

        assert answer.query == "What is the warranty length on electronics?"
        assert len(answer.retrieved_chunks) == 1
        assert answer.retrieved_chunks[0].source_id == "warranty"
        assert answer.error is not None
        assert answer.error["error_type"] == "malformed_response"

    def test_query_configuration_error_propagates_for_unconfigured_provider(self, tmp_path):
        service = _service(tmp_path)

        with pytest.raises(ProviderConfigurationError):
            service.query("What is the warranty length?", provider_name="openai")


class TestRAGServiceInspectChunks:
    def test_no_query_lists_full_corpus(self, tmp_path):
        service = _service(tmp_path)

        chunks = service.inspect_chunks()

        assert len(chunks) == 1
        assert chunks[0].source_id == "warranty"

    def test_with_query_returns_ranked_matches(self, tmp_path):
        service = _service(tmp_path)

        chunks = service.inspect_chunks(query="electronics warranty length")

        assert len(chunks) == 1
        assert chunks[0].relevance_score is not None

    def test_off_topic_query_returns_no_chunks(self, tmp_path):
        service = _service(tmp_path)

        chunks = service.inspect_chunks(query="Can you help me pick a birthday gift?")

        assert chunks == []


class TestRAGServiceEvaluateCase:
    def test_evaluates_a_passing_case(self, tmp_path):
        service = _service(tmp_path)

        case_result, retrieved_chunks = service.evaluate_case(
            "rag-c1", provider_name="deterministic"
        )

        assert case_result.case_id == "rag-c1"
        assert case_result.passed is True
        assert len(retrieved_chunks) == 1

    def test_evaluates_an_unsupported_case(self, tmp_path):
        service = _service(tmp_path)

        case_result, retrieved_chunks = service.evaluate_case(
            "rag-c2", provider_name="deterministic"
        )

        assert case_result.case_id == "rag-c2"
        assert retrieved_chunks == []

    def test_unknown_case_id_raises_not_found(self, tmp_path):
        service = _service(tmp_path)

        with pytest.raises(NotFoundError):
            service.evaluate_case("does-not-exist")
