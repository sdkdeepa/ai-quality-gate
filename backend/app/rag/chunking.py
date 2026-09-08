from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

DEFAULT_CHUNK_SIZE = 400
DEFAULT_CHUNK_OVERLAP = 40


def chunk_documents(
    documents: list[Document],
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[Document]:
    """Split loaded documents into chunks using LangChain's
    `RecursiveCharacterTextSplitter`, stamping each chunk with a stable,
    deterministic `chunk_id` (`{source_id}::chunk-{index}`) alongside the
    `source_id`/`title` metadata carried over from the source document.

    This is the one step ingestion leans on LangChain for by design: a
    hand-rolled splitter would just be reimplementing
    `RecursiveCharacterTextSplitter`'s separator-aware, overlap-aware
    algorithm, which is exactly the kind of well-tested, undifferentiated
    logic worth reusing rather than owning.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks: list[Document] = []
    for document in documents:
        source_id = document.metadata["source_id"]
        for index, chunk in enumerate(splitter.split_documents([document])):
            chunk.metadata["chunk_id"] = f"{source_id}::chunk-{index}"
            chunk.metadata["chunk_index"] = index
            chunks.append(chunk)
    return chunks
