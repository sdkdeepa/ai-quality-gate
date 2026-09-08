import math
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.rag.embeddings import DeterministicEmbeddings, OpenAIEmbeddings


class TestDeterministicEmbeddings:
    def test_same_text_yields_same_vector(self):
        embeddings = DeterministicEmbeddings()

        first = embeddings.embed_query("What is the warranty length?")
        second = embeddings.embed_query("What is the warranty length?")

        assert first == second

    def test_different_text_yields_different_vector(self):
        embeddings = DeterministicEmbeddings()

        warranty = embeddings.embed_query("electronics warranty length")
        shipping = embeddings.embed_query("standard shipping cost")

        assert warranty != shipping

    def test_vector_has_configured_dimensions(self):
        embeddings = DeterministicEmbeddings(dimensions=64)

        vector = embeddings.embed_query("hello world")

        assert len(vector) == 64

    def test_vector_is_l2_normalized(self):
        embeddings = DeterministicEmbeddings()

        vector = embeddings.embed_query("electronics warranty policy details")
        norm = math.sqrt(sum(v * v for v in vector))

        assert norm == 1.0 or abs(norm) < 1e-6

    def test_embed_documents_matches_embed_query_per_text(self):
        embeddings = DeterministicEmbeddings()
        texts = ["electronics warranty", "shipping cost"]

        batch = embeddings.embed_documents(texts)

        assert batch == [embeddings.embed_query(t) for t in texts]

    def test_empty_text_yields_zero_vector_not_an_error(self):
        embeddings = DeterministicEmbeddings(dimensions=32)

        vector = embeddings.embed_query("")

        assert vector == [0.0] * 32

    def test_stopword_only_query_yields_zero_vector(self):
        embeddings = DeterministicEmbeddings(dimensions=32)

        vector = embeddings.embed_query("the a an of to")

        assert vector == [0.0] * 32


class TestOpenAIEmbeddings:
    def test_embed_documents_calls_the_embeddings_endpoint(self):
        client = MagicMock()
        client.embeddings.create.return_value = SimpleNamespace(
            data=[SimpleNamespace(embedding=[0.1, 0.2]), SimpleNamespace(embedding=[0.3, 0.4])]
        )
        embeddings = OpenAIEmbeddings(client, model="text-embedding-3-small")

        result = embeddings.embed_documents(["a", "b"])

        assert result == [[0.1, 0.2], [0.3, 0.4]]
        client.embeddings.create.assert_called_once_with(
            model="text-embedding-3-small", input=["a", "b"]
        )

    def test_embed_query_returns_single_vector(self):
        client = MagicMock()
        client.embeddings.create.return_value = SimpleNamespace(
            data=[SimpleNamespace(embedding=[0.5, 0.6])]
        )
        embeddings = OpenAIEmbeddings(client)

        result = embeddings.embed_query("hello")

        assert result == [0.5, 0.6]
