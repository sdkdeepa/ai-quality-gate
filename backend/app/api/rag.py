from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api._view import metrics_by_framework
from app.api.deps import get_rag_service
from app.rag.types import RAGAnswer
from app.services.rag_service import RAGService

router = APIRouter(prefix="/rag", tags=["rag"])

ProviderName = Literal["deterministic", "openai", "gemini"]


class RAGQueryRequest(BaseModel):
    query: str
    # No default: unlike a dataset case, an ad-hoc query has no case_id for
    # DeterministicProvider to look a canned answer up by, so "deterministic"
    # here would always fail with a normalized malformed_response error —
    # ad-hoc exploration needs a real generation provider.
    provider: Literal["openai", "gemini"]
    top_k: int | None = None


class EvaluateRAGCaseRequest(BaseModel):
    provider: ProviderName = "deterministic"


@router.post("/query")
def query_rag(
    request: RAGQueryRequest,
    rag_service: Annotated[RAGService, Depends(get_rag_service)],
) -> RAGAnswer:
    """Ask the sample RAG system a question directly — for manually
    exploring/validating the RAG pipeline (query -> retrieve -> prompt ->
    provider -> answer). This is a debugging tool for the system under
    test, not a chat endpoint: it is not wired to any dataset case or
    grading, and the Quality Gate does not depend on it for anything.
    Requires `provider: "openai"|"gemini"` (with the matching API key
    configured) — an ad-hoc query has no case_id, so there is no canned
    fixture for `DeterministicProvider` to return; use
    `POST /rag/evaluate/{case_id}` for the deterministic, no-API-key path.
    """
    return rag_service.query(request.query, provider_name=request.provider, top_k=request.top_k)


@router.get("/chunks")
def inspect_chunks(
    rag_service: Annotated[RAGService, Depends(get_rag_service)],
    query: str | None = None,
    k: int | None = None,
) -> dict:
    """Inspect the ingested corpus. With no `query`, lists every chunk
    ChromaDB holds (id, source, text, metadata). With `query`, returns what
    the retriever would return for it — ranked, with relevance scores —
    without running generation at all.
    """
    chunks = rag_service.inspect_chunks(query=query, k=k)
    return {"query": query, "chunk_count": len(chunks), "chunks": chunks}


@router.post("/evaluate/{case_id}")
def evaluate_rag_case(
    case_id: str,
    request: EvaluateRAGCaseRequest,
    rag_service: Annotated[RAGService, Depends(get_rag_service)],
) -> dict:
    """Run one RAG dataset case through the real RAG pipeline — actual
    ChromaDB retrieval plus the selected generation provider — and grade it
    with the same deterministic evaluators the rest of the Quality Gate
    uses. Distinct from `POST /evaluations/runs`, which runs a whole
    dataset against a provider without retrieval.
    """
    case_result, retrieved_chunks = rag_service.evaluate_case(
        case_id, provider_name=request.provider
    )
    return {
        "case_result": case_result,
        "retrieved_chunks": retrieved_chunks,
        # Sprint 5 requirement #8: deterministic vs. RAGAS metrics for this
        # one case, side by side (framework -> that framework's MetricResults).
        "metrics_by_framework": metrics_by_framework(case_result),
    }
