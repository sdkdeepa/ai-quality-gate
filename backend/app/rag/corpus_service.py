import logging
from pathlib import Path

from app.rag.chunking import chunk_documents
from app.rag.loader import load_corpus
from app.rag.vector_store import ChromaVectorStore, hash_chunks

logger = logging.getLogger("app.rag")


class RAGCorpusService:
    """Ingestion entry point: corpus directory -> loaded documents -> chunks
    -> ChromaDB. Idempotent — re-ingests only if the corpus content has
    changed since the vector store was last built, so a normal app restart
    with an unchanged corpus does no embedding work.
    """

    def __init__(self, corpus_dir: Path, vector_store: ChromaVectorStore) -> None:
        self._corpus_dir = corpus_dir
        self._vector_store = vector_store

    def ingest_if_needed(self) -> None:
        documents = load_corpus(self._corpus_dir)
        chunks = chunk_documents(documents)
        current_hash = hash_chunks(chunks)

        if self._vector_store.stored_corpus_hash() == current_hash:
            logger.info(
                "RAG corpus unchanged (%d chunks from %d documents); skipping ingestion",
                len(chunks),
                len(documents),
            )
            return

        self._vector_store.replace_all(chunks)
        logger.info("ingested RAG corpus: %d chunks from %d documents", len(chunks), len(documents))
