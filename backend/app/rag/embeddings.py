import hashlib
import math
import re

from langchain_core.embeddings import Embeddings

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")

# Common English function words, filtered out before hashing so they don't
# dominate similarity scores between otherwise-unrelated short texts — every
# query and every corpus document shares most of these, so leaving them in
# swamps the signal from the content words that actually indicate relevance.
_STOPWORDS = frozenset(
    """
    a an and are as at be by can do does did for from had has have how i if
    in into is it its me my of on or our so than that the their them then
    there these they this to was we were what when where which who will
    with would you your yours am been being both but each few he her hers
    him his i'm i've it's let me more most no not now off once only other
    out over own s same should some such t too under until up very
    """.split()
)


class DeterministicEmbeddings(Embeddings):
    """Offline, dependency-free embeddings for tests/CI/local ingestion.

    Uses the hashing trick (a signed bag-of-words, each token hashed into one
    of `dimensions` buckets and L2-normalized) rather than a real embedding
    model. This makes retrieval deterministic and available with no network
    call or API key, mirroring `DeterministicProvider` from Sprint 3: the
    default path through ingestion/retrieval never depends on a live
    provider. Because it's lexical (token-overlap-based) rather than
    semantic, it retrieves well for this corpus's short, keyword-distinct
    policy documents, but should not be mistaken for a production-quality
    embedding model.
    """

    def __init__(self, dimensions: int = 1024) -> None:
        self.dimensions = dimensions

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = [t for t in _TOKEN_PATTERN.findall(text.lower()) if t not in _STOPWORDS]
        for token in tokens:
            digest = int(hashlib.sha256(token.encode()).hexdigest(), 16)
            index = digest % self.dimensions
            sign = 1.0 if (digest // self.dimensions) % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]


class OpenAIEmbeddings(Embeddings):
    """Real embeddings via the OpenAI embeddings endpoint.

    A thin wrapper — not `langchain_openai.OpenAIEmbeddings` — so the only
    new dependency is the `openai` SDK Sprint 3 already added, kept
    consistent with `OpenAIProvider` being the sole importer of `openai`
    elsewhere in the codebase. Opt-in via `EmbeddingsFactory`; never used by
    default so ingestion/tests never require an API key.
    """

    def __init__(self, client, *, model: str = "text-embedding-3-small") -> None:
        self._client = client
        self._model = model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        response = self._client.embeddings.create(model=self._model, input=texts)
        return [item.embedding for item in response.data]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]
