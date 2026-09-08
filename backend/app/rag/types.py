from typing import Any

from pydantic import BaseModel, Field


class RetrievedChunk(BaseModel):
    """One chunk returned by the retriever for a query."""

    chunk_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    text: str
    relevance_score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RAGAnswer(BaseModel):
    """The full result of running one query through the RAG pipeline:
    query -> retrieve -> prompt -> provider -> answer."""

    query: str
    answer: str
    retrieved_chunks: list[RetrievedChunk]
    provider: str
    model: str
    retrieval_latency_ms: float = Field(ge=0)
    generation_latency_ms: float = Field(ge=0)
    latency_ms: float = Field(ge=0)
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost: float | None = None
    error: dict[str, Any] | None = None
