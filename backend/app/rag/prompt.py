from app.rag.types import RetrievedChunk

SYSTEM_INSTRUCTIONS = (
    "You are a customer support assistant. Answer the question using ONLY "
    "the information in the provided context. If the context does not "
    "contain the answer, say you don't have that information — do not "
    "guess, and do not use outside knowledge. If the context contains "
    "conflicting information, prefer the most current/authoritative source "
    "and note the discrepancy."
)


def build_prompt(query: str, chunks: list[RetrievedChunk]) -> str:
    """Combine retrieved chunks and the query into the single prompt string
    sent to a Provider's `generate()`. Deliberately plain string
    concatenation rather than a LangChain `PromptTemplate` — with one fixed
    template and no partials/variables to manage beyond simple substitution,
    a template abstraction wouldn't earn its keep here.
    """
    if not chunks:
        context_block = "(no relevant context was found in the knowledge base)"
    else:
        context_block = "\n\n".join(
            f"[Source: {chunk.source_id}]\n{chunk.text}" for chunk in chunks
        )

    return f"{SYSTEM_INSTRUCTIONS}\n\nContext:\n{context_block}\n\nQuestion: {query}\nAnswer:"
