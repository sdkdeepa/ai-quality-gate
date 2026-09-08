from app.rag.corpus_service import RAGCorpusService
from app.rag.embeddings import DeterministicEmbeddings
from app.rag.vector_store import ChromaVectorStore


def _corpus_service(tmp_path) -> tuple[RAGCorpusService, ChromaVectorStore]:
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    vector_store = ChromaVectorStore(
        persist_directory=tmp_path / "chroma",
        collection_name="rag-corpus",
        embeddings=DeterministicEmbeddings(),
    )
    return RAGCorpusService(corpus_dir, vector_store), vector_store


class TestRAGCorpusService:
    def test_ingests_corpus_on_first_run(self, tmp_path):
        service, vector_store = _corpus_service(tmp_path)
        (tmp_path / "corpus" / "warranty.md").write_text(
            "# Warranty\n\n1-year warranty on electronics."
        )

        service.ingest_if_needed()

        assert vector_store.chunk_count() == 1

    def test_second_call_with_unchanged_corpus_does_not_reingest(self, tmp_path):
        service, vector_store = _corpus_service(tmp_path)
        (tmp_path / "corpus" / "warranty.md").write_text(
            "# Warranty\n\n1-year warranty on electronics."
        )
        service.ingest_if_needed()
        stored_hash_after_first = vector_store.stored_corpus_hash()

        service.ingest_if_needed()

        assert vector_store.stored_corpus_hash() == stored_hash_after_first
        assert vector_store.chunk_count() == 1

    def test_corpus_change_triggers_reingestion(self, tmp_path):
        service, vector_store = _corpus_service(tmp_path)
        (tmp_path / "corpus" / "warranty.md").write_text(
            "# Warranty\n\n1-year warranty on electronics."
        )
        service.ingest_if_needed()
        first_hash = vector_store.stored_corpus_hash()

        (tmp_path / "corpus" / "shipping.md").write_text("# Shipping\n\nStandard shipping is 4.99.")
        service.ingest_if_needed()

        assert vector_store.stored_corpus_hash() != first_hash
        assert vector_store.chunk_count() == 2

    def test_empty_corpus_directory_ingests_zero_chunks(self, tmp_path):
        service, vector_store = _corpus_service(tmp_path)

        service.ingest_if_needed()

        assert vector_store.chunk_count() == 0
        assert vector_store.stored_corpus_hash() is not None
