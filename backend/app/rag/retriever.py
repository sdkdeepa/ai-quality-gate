from app.rag.types import RetrievedChunk
from app.rag.vector_store import ChromaVectorStore

DEFAULT_TOP_K = 4
DEFAULT_RELEVANCE_THRESHOLD = 0.08
"""Below this cosine similarity, a chunk is dropped rather than returned.

Chroma always returns up to `k` nearest neighbors regardless of how
dissimilar they are, so without a floor a query with no relevant chunk in
the corpus would still retrieve *something* and never distinguish
"nothing relevant found" from a genuine (if weak) match. The threshold is
tuned against this corpus's DeterministicEmbeddings similarity scores: an
on-topic query scores at least ~0.15-0.7 (shares corpus-domain vocabulary),
while an off-topic query scores ~0.0-0.06 (empirically, exactly 0.0 for
most; see `tests/rag/test_retriever.py`).
"""


class Retriever:
    """query -> ranked, relevance-filtered `RetrievedChunk`s.

    This is our own code end to end, not a LangChain `Retriever` — a
    ~15-line method wrapping `ChromaVectorStore.similarity_search` plus a
    relevance floor isn't worth adopting `BaseRetriever`'s interface for.
    """

    def __init__(
        self,
        vector_store: ChromaVectorStore,
        *,
        top_k: int = DEFAULT_TOP_K,
        relevance_threshold: float = DEFAULT_RELEVANCE_THRESHOLD,
    ) -> None:
        self._vector_store = vector_store
        self._top_k = top_k
        self._relevance_threshold = relevance_threshold

    def retrieve(self, query: str, *, k: int | None = None) -> list[RetrievedChunk]:
        results = self._vector_store.similarity_search(query, k=k or self._top_k)
        chunks = []
        for document, distance in results:
            relevance_score = 1.0 - distance
            if relevance_score < self._relevance_threshold:
                continue
            chunks.append(
                RetrievedChunk(
                    chunk_id=document.metadata["chunk_id"],
                    source_id=document.metadata["source_id"],
                    text=document.page_content,
                    relevance_score=relevance_score,
                    metadata=document.metadata,
                )
            )
        return chunks
