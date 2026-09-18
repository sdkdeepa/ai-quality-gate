from openinference.semconv.trace import (
    DocumentAttributes,
    OpenInferenceSpanKindValues,
    SpanAttributes,
)
from opentelemetry import trace
from opentelemetry.trace import Tracer

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
        tracer: Tracer | None = None,
    ) -> None:
        self._vector_store = vector_store
        self._top_k = top_k
        self._relevance_threshold = relevance_threshold
        # Sprint 9: defaults to OpenTelemetry's own no-op tracer when not
        # given one, so every existing caller (tests included) that
        # constructs a Retriever without a `tracer` keeps working exactly
        # as before — see `app/observability/tracing.py`.
        self._tracer = tracer or trace.get_tracer(__name__)

    def retrieve(self, query: str, *, k: int | None = None) -> list[RetrievedChunk]:
        with self._tracer.start_as_current_span(
            "retrieval",
            attributes={
                SpanAttributes.OPENINFERENCE_SPAN_KIND: OpenInferenceSpanKindValues.RETRIEVER.value,
                SpanAttributes.INPUT_VALUE: query,
            },
        ) as span:
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

            # Requirement: "RAG retrieval" visible with its own metadata,
            # distinct from generation - every retrieved (post-filter)
            # chunk as an OpenInference retrieval.documents.N.* attribute,
            # so Phoenix's retrieval-aware UI can render them per-document.
            for i, chunk in enumerate(chunks):
                prefix = f"{SpanAttributes.RETRIEVAL_DOCUMENTS}.{i}."
                span.set_attribute(f"{prefix}{DocumentAttributes.DOCUMENT_ID}", chunk.chunk_id)
                span.set_attribute(f"{prefix}{DocumentAttributes.DOCUMENT_CONTENT}", chunk.text)
                span.set_attribute(
                    f"{prefix}{DocumentAttributes.DOCUMENT_SCORE}", chunk.relevance_score
                )
            span.set_attribute("retrieval.chunk_count", len(chunks))

            return chunks
