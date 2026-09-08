from langchain_core.documents import Document

from app.rag.chunking import chunk_documents


def _doc(source_id: str, text: str) -> Document:
    return Document(page_content=text, metadata={"source_id": source_id, "title": source_id})


class TestChunkDocuments:
    def test_short_document_produces_one_chunk(self):
        chunks = chunk_documents([_doc("a", "A short document.")])

        assert len(chunks) == 1
        assert chunks[0].metadata["chunk_id"] == "a::chunk-0"
        assert chunks[0].metadata["chunk_index"] == 0

    def test_long_document_is_split_into_multiple_chunks(self):
        long_text = "Sentence about policy details. " * 60  # well over chunk_size

        chunks = chunk_documents([_doc("long", long_text)], chunk_size=200, chunk_overlap=20)

        assert len(chunks) > 1
        assert [c.metadata["chunk_index"] for c in chunks] == list(range(len(chunks)))
        assert all(c.metadata["source_id"] == "long" for c in chunks)

    def test_chunk_ids_are_stable_and_source_scoped(self):
        chunks = chunk_documents(
            [_doc("return_policy", "Returns within 30 days."), _doc("warranty", "1-year warranty.")]
        )

        ids = {c.metadata["chunk_id"] for c in chunks}
        assert ids == {"return_policy::chunk-0", "warranty::chunk-0"}

    def test_no_documents_produces_no_chunks(self):
        assert chunk_documents([]) == []

    def test_chunking_is_deterministic(self):
        doc = _doc("a", "Sentence one. Sentence two. Sentence three. " * 20)

        first = chunk_documents([doc], chunk_size=100, chunk_overlap=10)
        second = chunk_documents([doc], chunk_size=100, chunk_overlap=10)

        assert [c.page_content for c in first] == [c.page_content for c in second]
        assert [c.metadata["chunk_id"] for c in first] == [c.metadata["chunk_id"] for c in second]
