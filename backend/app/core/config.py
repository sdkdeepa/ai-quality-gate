from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration, sourced from environment variables (prefix AQG_)."""

    model_config = SettingsConfigDict(env_prefix="AQG_", env_file=".env", extra="ignore")

    app_name: str = "AI Quality Gate"
    version: str = "0.1.0"
    environment: str = "development"
    log_level: str = "INFO"
    api_v1_prefix: str = "/api/v1"
    dataset_dir: str = "datasets"

    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    provider_timeout_seconds: float = 30.0

    rag_corpus_dir: str = "rag_corpus"
    rag_chroma_dir: str = "chroma_store"
    rag_collection_name: str = "rag-corpus"
    rag_embeddings_provider: str = "deterministic"
    rag_top_k: int = 4
    rag_relevance_threshold: float = 0.08
    rag_dataset_name: str = "customer_support_bot"

    # Sprint 5 — RAGAS integration. Disabled by default: the Gate's default
    # (fixture-driven, no-API-key) behavior is unchanged unless explicitly
    # opted in. RAGAS's LLM judge/embeddings currently reuse the OpenAI
    # provider's key/timeout (AQG_OPENAI_API_KEY, AQG_PROVIDER_TIMEOUT_SECONDS)
    # rather than introducing a second credential to manage; see DECISIONS.md #21.
    ragas_enabled: bool = False
    # Comma-separated subset of KNOWN_RAGAS_METRICS (app/evaluation/ragas/factory.py).
    ragas_metrics: str = "faithfulness,answer_relevancy,context_precision,context_recall"
    ragas_llm_model: str | None = None  # falls back to openai_model when unset
    ragas_embedding_model: str = "text-embedding-3-small"
    ragas_faithfulness_threshold: float = 0.80
    ragas_answer_relevancy_threshold: float = 0.70
    ragas_context_precision_threshold: float = 0.70
    ragas_context_recall_threshold: float = 0.70

    @property
    def ragas_metrics_list(self) -> list[str]:
        return [m.strip() for m in self.ragas_metrics.split(",") if m.strip()]

    # Sprint 6 — DeepEval integration. Disabled by default, same rationale
    # as RAGAS. Only one DeepEval evaluator ships this sprint (a G-Eval
    # custom-criteria check), so there is no AQG_DEEPEVAL_METRICS selector
    # yet the way AQG_RAGAS_METRICS exists — see DECISIONS.md #23 for why.
    # The judge model reuses AQG_OPENAI_API_KEY, same as RAGAS.
    deepeval_enabled: bool = False
    deepeval_llm_model: str | None = None  # falls back to openai_model when unset
    deepeval_criteria_threshold: float = 0.70


@lru_cache
def get_settings() -> Settings:
    return Settings()
