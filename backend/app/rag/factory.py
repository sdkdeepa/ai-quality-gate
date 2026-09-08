from pathlib import Path

from openai import OpenAI

from app.core.config import Settings
from app.core.exceptions import ProviderConfigurationError
from app.rag.corpus_service import RAGCorpusService
from app.rag.embeddings import DeterministicEmbeddings, OpenAIEmbeddings
from app.rag.retriever import Retriever
from app.rag.vector_store import ChromaVectorStore


def build_retriever(settings: Settings, backend_root: Path) -> tuple[ChromaVectorStore, Retriever]:
    """Wires embeddings -> ChromaVectorStore -> ingestion -> Retriever from Settings.

    Called once at `create_app()` time, mirroring `DatasetService.load_all()`:
    the corpus on disk is the source of truth, and ingestion is idempotent
    (`RAGCorpusService.ingest_if_needed`), so a normal restart with an
    unchanged corpus does no re-embedding work.
    """
    embeddings = _build_embeddings(settings)
    persist_dir = _resolve_path(settings.rag_chroma_dir, backend_root)
    vector_store = ChromaVectorStore(
        persist_directory=persist_dir,
        collection_name=settings.rag_collection_name,
        embeddings=embeddings,
    )
    corpus_dir = _resolve_path(settings.rag_corpus_dir, backend_root)
    RAGCorpusService(corpus_dir, vector_store).ingest_if_needed()

    retriever = Retriever(
        vector_store,
        top_k=settings.rag_top_k,
        relevance_threshold=settings.rag_relevance_threshold,
    )
    return vector_store, retriever


def _build_embeddings(settings: Settings) -> DeterministicEmbeddings | OpenAIEmbeddings:
    if settings.rag_embeddings_provider == "openai":
        if not settings.openai_api_key:
            raise ProviderConfigurationError(
                "AQG_OPENAI_API_KEY is not set; cannot use AQG_RAG_EMBEDDINGS_PROVIDER='openai'"
            )
        return OpenAIEmbeddings(OpenAI(api_key=settings.openai_api_key))
    return DeterministicEmbeddings()


def _resolve_path(path_str: str, backend_root: Path) -> Path:
    path = Path(path_str)
    return path if path.is_absolute() else backend_root / path
