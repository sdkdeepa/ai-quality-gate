from langchain_core.documents import Document

from app.rag.embeddings import DeterministicEmbeddings
from app.rag.retriever import Retriever
from app.rag.vector_store import ChromaVectorStore


def _chunk(chunk_id: str, source_id: str, text: str) -> Document:
    return Document(
        page_content=text, metadata={"chunk_id": chunk_id, "source_id": source_id, "chunk_index": 0}
    )


def _retriever(tmp_path, *, relevance_threshold: float = 0.08, top_k: int = 4) -> Retriever:
    store = ChromaVectorStore(
        persist_directory=tmp_path / "chroma",
        collection_name="rag-corpus",
        embeddings=DeterministicEmbeddings(),
    )
    store.replace_all(
        [
            _chunk(
                "warranty::0",
                "warranty",
                "Electronics come with a 1-year limited warranty from the purchase date.",
            ),
            _chunk(
                "shipping::0",
                "shipping",
                "Standard shipping costs 4.99 dollars and takes 3 to 5 business days.",
            ),
        ]
    )
    return Retriever(store, top_k=top_k, relevance_threshold=relevance_threshold)


class TestRetriever:
    def test_on_topic_query_returns_relevant_chunk_first(self, tmp_path):
        retriever = _retriever(tmp_path)

        results = retriever.retrieve("What is the warranty length on electronics?")

        assert results[0].chunk_id == "warranty::0"
        assert results[0].source_id == "warranty"
        assert "1-year" in results[0].text

    def test_relevance_score_is_populated(self, tmp_path):
        retriever = _retriever(tmp_path)

        [chunk] = retriever.retrieve("electronics warranty length", k=1)

        assert chunk.relevance_score is not None
        assert chunk.relevance_score > 0

    def test_off_topic_query_is_filtered_out_by_relevance_threshold(self, tmp_path):
        retriever = _retriever(tmp_path)

        results = retriever.retrieve("Can you help me pick a birthday gift for my mom?")

        assert results == []

    def test_zero_threshold_returns_up_to_k_results_regardless_of_relevance(self, tmp_path):
        retriever = _retriever(tmp_path, relevance_threshold=0.0)

        results = retriever.retrieve("Can you help me pick a birthday gift for my mom?", k=2)

        assert len(results) == 2

    def test_k_limits_number_of_results(self, tmp_path):
        retriever = _retriever(tmp_path, relevance_threshold=0.0)

        results = retriever.retrieve("warranty and shipping", k=1)

        assert len(results) == 1

    def test_metadata_is_carried_through(self, tmp_path):
        retriever = _retriever(tmp_path)

        [chunk] = retriever.retrieve("electronics warranty length", k=1)

        assert chunk.metadata["chunk_id"] == "warranty::0"
