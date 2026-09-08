"""End-to-end tests for the RAG system's handling of queries it should NOT
confidently answer — irrelevant (off-corpus), missing (on-topic but the
specific fact isn't documented), and unsupported (out of scope entirely)
scenarios from the real v1.1.0 seed dataset. Runs the actual corpus through
loading -> chunking -> embedding -> Chroma -> retrieval (no mocks), so these
tests double as regression coverage for the DEFAULT_RELEVANCE_THRESHOLD
tuning in `app/rag/retriever.py`.
"""

from pathlib import Path

import pytest

from app.domain.golden_dataset import GoldenDataset
from app.evaluation.runner import EvaluationRunner
from app.providers.deterministic import DeterministicProvider
from app.rag.chunking import chunk_documents
from app.rag.embeddings import DeterministicEmbeddings
from app.rag.loader import load_corpus
from app.rag.retriever import Retriever
from app.rag.vector_store import ChromaVectorStore
from app.repositories.in_memory import InMemoryRepository
from app.services.dataset_service import DatasetService

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = BACKEND_ROOT / "datasets"
CORPUS_DIR = BACKEND_ROOT / "rag_corpus"

IRRELEVANT_CASE_IDS = {"rag-008", "rag-009"}
MISSING_CASE_IDS = {"rag-010", "rag-011", "rag-012"}
UNSUPPORTED_CASE_IDS = {"rag-015", "rag-016"}
DELIBERATE_REFUSAL_FAILURE = "rag-009"


@pytest.fixture(scope="module")
def rag_dataset():
    service = DatasetService(DATASET_DIR, InMemoryRepository[GoldenDataset]())
    service.load_all()
    return service.get_dataset("customer_support_bot", "1.1.0")


@pytest.fixture(scope="module")
def retriever(tmp_path_factory):
    persist_dir = tmp_path_factory.mktemp("chroma")
    documents = load_corpus(CORPUS_DIR)
    chunks = chunk_documents(documents)
    store = ChromaVectorStore(
        persist_directory=persist_dir,
        collection_name="rag-corpus",
        embeddings=DeterministicEmbeddings(),
    )
    store.replace_all(chunks)
    return Retriever(store, top_k=4, relevance_threshold=0.08)


def _case(rag_dataset, case_id):
    return next(c for c in rag_dataset.cases if c.id == case_id)


class TestIrrelevantQueriesRetrieveNothing:
    """Queries with no relevant chunk in the corpus at all must retrieve
    zero chunks — the relevance threshold, not just the LLM, is what
    prevents the system from grounding an answer in unrelated content."""

    @pytest.mark.parametrize("case_id", sorted(IRRELEVANT_CASE_IDS))
    def test_retrieves_no_chunks(self, rag_dataset, retriever, case_id):
        case = _case(rag_dataset, case_id)

        chunks = retriever.retrieve(case.query)

        assert chunks == []

    @pytest.mark.parametrize("case_id", sorted(IRRELEVANT_CASE_IDS))
    def test_expects_unsupported_behavior(self, rag_dataset, case_id):
        case = _case(rag_dataset, case_id)

        assert case.expected_behavior == "unsupported"


class TestMissingFactsStillRetrieveOnTopicContext:
    """The specific fact isn't documented, but the query IS on-topic — the
    retriever should still surface the on-topic (if unhelpful) chunk, since
    a real system needs that context to correctly say "not specified"
    rather than treating it as fully out of scope."""

    @pytest.mark.parametrize("case_id", sorted(MISSING_CASE_IDS))
    def test_retrieves_at_least_one_on_topic_chunk(self, rag_dataset, retriever, case_id):
        case = _case(rag_dataset, case_id)

        chunks = retriever.retrieve(case.query)

        assert len(chunks) >= 1

    @pytest.mark.parametrize("case_id", sorted(MISSING_CASE_IDS))
    def test_expects_unsupported_behavior(self, rag_dataset, case_id):
        case = _case(rag_dataset, case_id)

        assert case.expected_behavior == "unsupported"


class TestUnsupportedQueriesAreGradedByRefusalLanguage:
    @pytest.mark.parametrize("case_id", sorted(UNSUPPORTED_CASE_IDS))
    def test_expects_unsupported_behavior(self, rag_dataset, case_id):
        case = _case(rag_dataset, case_id)

        assert case.expected_behavior == "unsupported"


@pytest.fixture(scope="module")
def results_by_id():
    service = DatasetService(DATASET_DIR, InMemoryRepository[GoldenDataset]())
    service.load_all()
    dataset = service.get_dataset("customer_support_bot", "1.1.0")
    fixtures = service.get_fixtures(dataset)
    provider = DeterministicProvider(fixtures)
    _, results = EvaluationRunner().run_with_provider(dataset, provider)
    return {r.case_id: r for r in results}


class TestFullRunGradesUnsupportedScenariosCorrectly:
    """Runs every irrelevant/missing/unsupported RAG case through the real
    deterministic-fixture-backed pipeline (retrieval + evaluators) and
    checks the pass/fail outcome matches what each fixture was authored to
    demonstrate — including the one deliberate refusal-detection failure.
    """

    @pytest.mark.parametrize(
        "case_id",
        sorted(
            (IRRELEVANT_CASE_IDS | MISSING_CASE_IDS | UNSUPPORTED_CASE_IDS)
            - {DELIBERATE_REFUSAL_FAILURE}
        ),
    )
    def test_well_behaved_refusal_passes(self, results_by_id, case_id):
        assert results_by_id[case_id].passed is True

    def test_deliberate_non_refusal_fails_on_expected_refusal(self, results_by_id):
        result = results_by_id[DELIBERATE_REFUSAL_FAILURE]

        assert result.passed is False
        failing_metrics = {m.metric_name for m in result.metric_results if not m.passed}
        assert "expected_refusal" in failing_metrics
