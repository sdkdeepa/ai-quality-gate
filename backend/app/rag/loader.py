from pathlib import Path

from langchain_core.documents import Document


def load_corpus(corpus_dir: Path) -> list[Document]:
    """Load every `*.md` file in `corpus_dir` into a LangChain `Document`.

    Deliberately not a LangChain `DirectoryLoader`/`TextLoader` (both live in
    `langchain-community`, which is being sunset in favor of standalone
    integration packages) — for plain local text files, reading them
    ourselves is a few lines and keeps the loading step (our metadata
    convention: `source_id` = filename stem, `title` = first line) fully in
    our own code. LangChain's contribution starts one step later, at
    chunking (`chunking.py`) and the Chroma vector store.
    """
    documents = []
    for path in sorted(corpus_dir.glob("*.md")):
        text = path.read_text().strip()
        title = text.splitlines()[0].lstrip("#").strip() if text else path.stem
        documents.append(
            Document(
                page_content=text,
                metadata={"source_id": path.stem, "title": title},
            )
        )
    return documents
