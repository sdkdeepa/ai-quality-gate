"""Sprint 9: trace propagation through the actually-instrumented components
(`EvaluationRunner`, `Retriever`) - not just `configure_tracing` in
isolation (see `test_tracing.py`). Uses a plain OpenTelemetry
`TracerProvider` + `InMemorySpanExporter` (no Phoenix, no network) so
spans can be inspected directly and synchronously.
"""

from datetime import UTC, datetime

from langchain_core.documents import Document
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Tracer

from app.domain.evaluation_case import EvaluationCase
from app.domain.golden_dataset import GoldenDataset
from app.evaluation.deterministic import DEFAULT_EVALUATORS
from app.evaluation.runner import EvaluationRunner
from app.evaluation.types import FixtureResponse
from app.providers.types import ProviderRequest, ProviderResponse
from app.rag.embeddings import DeterministicEmbeddings
from app.rag.provider_adapter import RAGProvider
from app.rag.retriever import Retriever
from app.rag.vector_store import ChromaVectorStore


def _tracer_with_exporter() -> tuple[Tracer, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer("test"), exporter


def _dataset(cases: list[EvaluationCase]) -> GoldenDataset:
    return GoldenDataset(
        name="test_dataset",
        version="1.0.0",
        created_at=datetime.now(UTC),
        description="A test dataset.",
        cases=cases,
    )


def _span(exporter: InMemorySpanExporter, name: str):
    matches = [s for s in exporter.get_finished_spans() if s.name == name]
    assert matches, (
        f"no span named {name!r} among {[s.name for s in exporter.get_finished_spans()]}"
    )
    return matches[0]


class TestEvaluationRunSpanHierarchy:
    def test_run_produces_evaluation_run_case_and_provider_call_spans(self):
        tracer, exporter = _tracer_with_exporter()
        case = EvaluationCase(
            id="c1",
            name="n",
            category="answer",
            query="2+2?",
            expected_answer="4",
            metadata={"match_mode": "exact"},
        )
        fixtures = {
            "c1": FixtureResponse(
                response="4", latency_ms=42.0, input_tokens=3, output_tokens=1, estimated_cost=0.002
            )
        }
        runner = EvaluationRunner(evaluators=list(DEFAULT_EVALUATORS), tracer=tracer)

        run, _ = runner.run(_dataset([case]), fixtures)

        names = [s.name for s in exporter.get_finished_spans()]
        assert "evaluation_run" in names
        assert "case" in names
        assert "provider_call" in names
        # One span per applicable deterministic evaluator (exact_match here).
        assert "exact_match" in names

    def test_case_span_is_a_child_of_the_evaluation_run_span(self):
        tracer, exporter = _tracer_with_exporter()
        case = EvaluationCase(
            id="c1",
            name="n",
            category="answer",
            query="hi",
            metadata={},
        )
        fixtures = {
            "c1": FixtureResponse(
                response="hi", latency_ms=1.0, input_tokens=1, output_tokens=1, estimated_cost=0.0
            )
        }
        runner = EvaluationRunner(evaluators=[], tracer=tracer)

        runner.run(_dataset([case]), fixtures)

        run_span = _span(exporter, "evaluation_run")
        case_span = _span(exporter, "case")
        assert case_span.parent.span_id == run_span.context.span_id

    def test_provider_call_and_evaluator_spans_are_children_of_the_case_span(self):
        tracer, exporter = _tracer_with_exporter()
        case = EvaluationCase(
            id="c1",
            name="n",
            category="answer",
            query="2+2?",
            expected_answer="4",
            metadata={"match_mode": "exact"},
        )
        fixtures = {
            "c1": FixtureResponse(
                response="4", latency_ms=1.0, input_tokens=1, output_tokens=1, estimated_cost=0.0
            )
        }
        runner = EvaluationRunner(evaluators=list(DEFAULT_EVALUATORS), tracer=tracer)

        runner.run(_dataset([case]), fixtures)

        case_span = _span(exporter, "case")
        provider_span = _span(exporter, "provider_call")
        evaluator_span = _span(exporter, "exact_match")
        assert provider_span.parent.span_id == case_span.context.span_id
        assert evaluator_span.parent.span_id == case_span.context.span_id


class TestSpanAttributes:
    def test_evaluation_run_span_carries_dataset_and_provider_metadata(self):
        tracer, exporter = _tracer_with_exporter()
        case = EvaluationCase(id="c1", name="n", category="answer", query="hi", metadata={})
        fixtures = {
            "c1": FixtureResponse(
                response="hi", latency_ms=1.0, input_tokens=1, output_tokens=1, estimated_cost=0.0
            )
        }
        runner = EvaluationRunner(evaluators=[], tracer=tracer)

        runner.run(_dataset([case]), fixtures, provider="deterministic", model="fixture-v1")

        run_span = _span(exporter, "evaluation_run")
        assert run_span.attributes["dataset.name"] == "test_dataset"
        assert run_span.attributes["dataset.version"] == "1.0.0"
        assert run_span.attributes["provider.name"] == "deterministic"
        assert run_span.attributes["llm.model_name"] == "fixture-v1"
        assert run_span.attributes["case.count"] == 1

    def test_case_span_carries_case_metadata(self):
        tracer, exporter = _tracer_with_exporter()
        case = EvaluationCase(
            id="c1",
            name="n",
            category="answer",
            query="hi",
            critical=True,
            metadata={},
        )
        fixtures = {
            "c1": FixtureResponse(
                response="hi", latency_ms=1.0, input_tokens=1, output_tokens=1, estimated_cost=0.0
            )
        }
        runner = EvaluationRunner(evaluators=[], tracer=tracer)

        runner.run(_dataset([case]), fixtures)

        case_span = _span(exporter, "case")
        assert case_span.attributes["case.id"] == "c1"
        assert case_span.attributes["case.category"] == "answer"
        assert case_span.attributes["case.critical"] is True

    def test_provider_call_span_carries_latency_tokens_and_cost(self):
        tracer, exporter = _tracer_with_exporter()
        case = EvaluationCase(id="c1", name="n", category="answer", query="hi", metadata={})
        fixtures = {
            "c1": FixtureResponse(
                response="hi",
                latency_ms=250.0,
                input_tokens=10,
                output_tokens=5,
                estimated_cost=0.01,
            )
        }
        runner = EvaluationRunner(evaluators=[], tracer=tracer)

        runner.run(_dataset([case]), fixtures)

        provider_span = _span(exporter, "provider_call")
        assert provider_span.attributes["llm.latency_ms"] == 250.0
        assert provider_span.attributes["llm.token_count.prompt"] == 10
        assert provider_span.attributes["llm.token_count.completion"] == 5
        assert provider_span.attributes["llm.cost.total"] == 0.01

    def test_evaluator_span_carries_metric_name_score_and_passed(self):
        tracer, exporter = _tracer_with_exporter()
        case = EvaluationCase(
            id="c1",
            name="n",
            category="answer",
            query="2+2?",
            expected_answer="4",
            metadata={"match_mode": "exact"},
        )
        fixtures = {
            "c1": FixtureResponse(
                response="4", latency_ms=1.0, input_tokens=1, output_tokens=1, estimated_cost=0.0
            )
        }
        runner = EvaluationRunner(evaluators=list(DEFAULT_EVALUATORS), tracer=tracer)

        runner.run(_dataset([case]), fixtures)

        evaluator_span = _span(exporter, "exact_match")
        assert evaluator_span.attributes["evaluator.framework"] == "deterministic"
        assert evaluator_span.attributes["evaluator.metric_name"] == "exact_match"
        assert evaluator_span.attributes["evaluator.passed"] is True


class TestTraceIdPersistedOnRun:
    def test_run_trace_id_matches_the_root_span(self):
        tracer, exporter = _tracer_with_exporter()
        case = EvaluationCase(id="c1", name="n", category="answer", query="hi", metadata={})
        fixtures = {
            "c1": FixtureResponse(
                response="hi", latency_ms=1.0, input_tokens=1, output_tokens=1, estimated_cost=0.0
            )
        }
        runner = EvaluationRunner(evaluators=[], tracer=tracer)

        run, _ = runner.run(_dataset([case]), fixtures)

        run_span = _span(exporter, "evaluation_run")
        assert run.trace_id == format(run_span.context.trace_id, "032x")

    def test_no_tracer_means_no_trace_id(self):
        """Omitting `tracer=` entirely (Sprint 1-8 callers) falls back to
        OpenTelemetry's own no-op tracer - the run still completes
        correctly, just with no trace id, exactly like tracing being
        explicitly disabled."""
        case = EvaluationCase(id="c1", name="n", category="answer", query="hi", metadata={})
        fixtures = {
            "c1": FixtureResponse(
                response="hi", latency_ms=1.0, input_tokens=1, output_tokens=1, estimated_cost=0.0
            )
        }
        runner = EvaluationRunner(evaluators=[])

        run, results = runner.run(_dataset([case]), fixtures)

        assert run.trace_id is None
        assert results[0].passed is True  # instrumentation never changes behavior


class TestRetrievalAndGenerationVisibleSeparately:
    """Requirement: "retrieval and generation visible separately"."""

    def _rag_provider(self, tmp_path, tracer, generation_response: ProviderResponse) -> RAGProvider:
        store = ChromaVectorStore(
            persist_directory=tmp_path / "chroma",
            collection_name="rag-corpus",
            embeddings=DeterministicEmbeddings(),
        )
        store.replace_all(
            [
                Document(
                    page_content="Electronics come with a 1-year limited warranty.",
                    metadata={"chunk_id": "warranty::0", "source_id": "warranty", "chunk_index": 0},
                )
            ]
        )
        retriever = Retriever(store, tracer=tracer)

        class _FakeGenerationProvider:
            name = "fake-generation"
            model = "fixture-v1"

            def generate(self, request: ProviderRequest) -> ProviderResponse:
                return generation_response

        return RAGProvider(retriever, _FakeGenerationProvider())

    def test_retrieval_span_and_provider_call_span_both_exist(self, tmp_path):
        tracer, exporter = _tracer_with_exporter()
        response = ProviderResponse(
            provider="fake-generation",
            model="fixture-v1",
            text="1-year warranty.",
            latency_ms=5.0,
            input_tokens=1,
            output_tokens=1,
            estimated_cost=0.0,
        )
        rag_provider = self._rag_provider(tmp_path, tracer, response)
        case = EvaluationCase(
            id="rag-1", name="n", category="rag", query="warranty length?", metadata={}
        )
        runner = EvaluationRunner(evaluators=[], tracer=tracer)

        runner.evaluate_case(case, rag_provider)

        names = [s.name for s in exporter.get_finished_spans()]
        assert "retrieval" in names
        assert "provider_call" in names

    def test_retrieval_span_is_distinct_from_and_nested_under_provider_call(self, tmp_path):
        tracer, exporter = _tracer_with_exporter()
        response = ProviderResponse(
            provider="fake-generation",
            model="fixture-v1",
            text="1-year warranty.",
            latency_ms=5.0,
            input_tokens=1,
            output_tokens=1,
            estimated_cost=0.0,
        )
        rag_provider = self._rag_provider(tmp_path, tracer, response)
        case = EvaluationCase(
            id="rag-1", name="n", category="rag", query="warranty length?", metadata={}
        )
        runner = EvaluationRunner(evaluators=[], tracer=tracer)

        runner.evaluate_case(case, rag_provider)

        provider_span = _span(exporter, "provider_call")
        retrieval_span = _span(exporter, "retrieval")
        # Distinct spans (different span ids) ...
        assert retrieval_span.context.span_id != provider_span.context.span_id
        # ... nested under the provider call, not siblings floating loose.
        assert retrieval_span.parent.span_id == provider_span.context.span_id

    def test_retrieval_span_carries_query_and_document_attributes(self, tmp_path):
        tracer, exporter = _tracer_with_exporter()
        response = ProviderResponse(
            provider="fake-generation",
            model="fixture-v1",
            text="1-year warranty.",
            latency_ms=5.0,
            input_tokens=1,
            output_tokens=1,
            estimated_cost=0.0,
        )
        rag_provider = self._rag_provider(tmp_path, tracer, response)
        case = EvaluationCase(
            id="rag-1", name="n", category="rag", query="warranty length?", metadata={}
        )
        runner = EvaluationRunner(evaluators=[], tracer=tracer)

        runner.evaluate_case(case, rag_provider)

        retrieval_span = _span(exporter, "retrieval")
        assert retrieval_span.attributes["input.value"] == "warranty length?"
        assert retrieval_span.attributes["retrieval.chunk_count"] >= 1
        assert "retrieval.documents.0.document.id" in retrieval_span.attributes
