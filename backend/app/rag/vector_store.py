import hashlib
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

_HASH_MARKER_FILENAME = ".corpus_hash"


def hash_chunks(chunks: list[Document]) -> str:
    """A stable fingerprint of chunk content+ids, used to decide whether the
    persisted collection is already up to date with the corpus on disk."""
    digest = hashlib.sha256()
    for chunk in sorted(chunks, key=lambda c: c.metadata["chunk_id"]):
        digest.update(chunk.metadata["chunk_id"].encode())
        digest.update(b"\0")
        digest.update(chunk.page_content.encode())
        digest.update(b"\0")
    return digest.hexdigest()


class ChromaVectorStore:
    """Thin wrapper around `langchain_chroma.Chroma`: persistence to disk,
    idempotent (re-)ingestion, and a chunk-inspection method for the
    "inspect chunks" API endpoint. This is where our abstraction ends and
    LangChain's Chroma integration takes over — everything below this class
    is `langchain_chroma`/`chromadb`.
    """

    def __init__(
        self,
        *,
        persist_directory: Path,
        collection_name: str,
        embeddings: Embeddings,
    ) -> None:
        self._persist_directory = persist_directory
        self._hash_marker_path = persist_directory / _HASH_MARKER_FILENAME
        persist_directory.mkdir(parents=True, exist_ok=True)
        self._store = Chroma(
            collection_name=collection_name,
            embedding_function=embeddings,
            persist_directory=str(persist_directory),
            collection_metadata={"hnsw:space": "cosine"},
        )

    def stored_corpus_hash(self) -> str | None:
        if not self._hash_marker_path.is_file():
            return None
        return self._hash_marker_path.read_text().strip()

    def replace_all(self, chunks: list[Document]) -> None:
        """Wipe the collection and (re-)ingest `chunks` from scratch, then
        record their fingerprint so the next startup can skip re-ingestion
        if the corpus hasn't changed."""
        self._store.reset_collection()
        if chunks:
            ids = [chunk.metadata["chunk_id"] for chunk in chunks]
            self._store.add_documents(chunks, ids=ids)
        self._hash_marker_path.write_text(hash_chunks(chunks))

    def similarity_search(self, query: str, *, k: int) -> list[tuple[Document, float]]:
        """Returns (chunk, distance) pairs — Chroma's cosine *distance*
        (0.0 = identical, larger = less similar), converted to a
        `relevance_score` (similarity, higher = more relevant) by callers."""
        return self._store.similarity_search_with_score(query, k=k)

    def get_all_chunks(self) -> list[dict]:
        data = self._store.get(include=["documents", "metadatas"])
        return [
            {"chunk_id": chunk_id, "text": text, "metadata": metadata}
            for chunk_id, text, metadata in zip(
                data["ids"], data["documents"], data["metadatas"], strict=True
            )
        ]

    def chunk_count(self) -> int:
        return len(self._store.get(include=[])["ids"])
