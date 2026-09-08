from app.rag.prompt import build_prompt
from app.rag.types import RetrievedChunk


def test_includes_the_query():
    prompt = build_prompt("What is the warranty length?", [])

    assert "What is the warranty length?" in prompt


def test_includes_retrieved_chunk_text_and_source():
    chunk = RetrievedChunk(
        chunk_id="warranty::0", source_id="warranty_policy", text="1-year limited warranty."
    )

    prompt = build_prompt("query", [chunk])

    assert "1-year limited warranty." in prompt
    assert "warranty_policy" in prompt


def test_no_chunks_states_no_context_was_found():
    prompt = build_prompt("query", [])

    assert "no relevant context" in prompt.lower()


def test_multiple_chunks_are_all_included():
    chunks = [
        RetrievedChunk(chunk_id="a::0", source_id="a", text="Fact A."),
        RetrievedChunk(chunk_id="b::0", source_id="b", text="Fact B."),
    ]

    prompt = build_prompt("query", chunks)

    assert "Fact A." in prompt
    assert "Fact B." in prompt


def test_instructs_the_model_not_to_use_outside_knowledge():
    prompt = build_prompt("query", [])

    assert "outside knowledge" in prompt.lower() or "do not guess" in prompt.lower()
