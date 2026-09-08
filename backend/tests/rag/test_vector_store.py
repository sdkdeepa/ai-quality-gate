from langchain_core.documents import Document

from app.rag.embeddings import DeterministicEmbeddings
from app.rag.vector_store import ChromaVectorStore, hash_chunks


def _chunk(chunk_id: str, source_id: str, text: str) -> Document:
    return Document(
        page_content=text,
        metadata={
            "chunk_id": chunk_id,
            "source_id": source_id,
            "chunk_index": 0,
            "title": source_id,
        },
    )


def _store(tmp_path, name: str = "rag-corpus") -> ChromaVectorStore:
    return ChromaVectorStore(
        persist_directory=tmp_path / "chroma",
        collection_name=name,
        embeddings=DeterministicEmbeddings(),
    )


class TestHashChunks:
    def test_same_chunks_hash_the_same_regardless_of_order(self):
        a = _chunk("x::0", "x", "hello")
        b = _chunk("y::0", "y", "world")

        assert hash_chunks([a, b]) == hash_chunks([b, a])

    def test_different_content_hashes_differently(self):
        a = _chunk("x::0", "x", "hello")
        b = _chunk("x::0", "x", "goodbye")

        assert hash_chunks([a]) != hash_chunks([b])

    def test_empty_list_has_a_stable_hash(self):
        assert hash_chunks([]) == hash_chunks([])


class TestChromaVectorStore:
    def test_new_store_has_no_stored_hash(self, tmp_path):
        store = _store(tmp_path)

        assert store.stored_corpus_hash() is None
        assert store.chunk_count() == 0

    def test_replace_all_adds_chunks_and_records_hash(self, tmp_path):
        store = _store(tmp_path)
        chunks = [_chunk("a::0", "a", "Electronics get a 1-year warranty.")]

        store.replace_all(chunks)

        assert store.chunk_count() == 1
        assert store.stored_corpus_hash() == hash_chunks(chunks)

    def test_replace_all_wipes_previous_content(self, tmp_path):
        store = _store(tmp_path)
        store.replace_all([_chunk("a::0", "a", "first version")])

        store.replace_all([_chunk("b::0", "b", "second version")])

        assert store.chunk_count() == 1
        assert store.get_all_chunks()[0]["chunk_id"] == "b::0"

    def test_persists_across_separate_instances(self, tmp_path):
        chunks = [_chunk("a::0", "a", "Electronics get a 1-year warranty.")]
        _store(tmp_path).replace_all(chunks)

        reloaded = _store(tmp_path)

        assert reloaded.chunk_count() == 1
        assert reloaded.stored_corpus_hash() == hash_chunks(chunks)

    def test_similarity_search_returns_document_and_distance(self, tmp_path):
        store = _store(tmp_path)
        store.replace_all(
            [
                _chunk("warranty::0", "warranty", "Electronics get a 1-year warranty."),
                _chunk("shipping::0", "shipping", "Standard shipping costs 4.99 dollars."),
            ]
        )

        results = store.similarity_search("electronics warranty", k=2)

        assert len(results) == 2
        top_doc, top_score = results[0]
        assert top_doc.metadata["chunk_id"] == "warranty::0"
        assert isinstance(top_score, float)

    def test_get_all_chunks_includes_text_and_metadata(self, tmp_path):
        store = _store(tmp_path)
        store.replace_all([_chunk("a::0", "a", "some text")])

        [chunk] = store.get_all_chunks()

        assert chunk["chunk_id"] == "a::0"
        assert chunk["text"] == "some text"
        assert chunk["metadata"]["source_id"] == "a"
