from app.domain.enums import ExpectedBehavior
from app.domain.evaluation_case import EvaluationCase
from app.evaluation.deterministic import (
    CitationPresenceEvaluator,
    CostThresholdEvaluator,
    ExactMatchEvaluator,
    ExpectedRefusalEvaluator,
    ForbiddenPhraseEvaluator,
    JSONSchemaEvaluator,
    LatencyThresholdEvaluator,
    RequiredPhraseEvaluator,
)
from app.evaluation.types import EvaluationInput


def _case(**overrides) -> EvaluationCase:
    defaults = {"id": "c1", "name": "n", "category": "c", "query": "q"}
    defaults.update(overrides)
    return EvaluationCase(**defaults)


def _input(case: EvaluationCase, **overrides) -> EvaluationInput:
    defaults = {
        "case": case,
        "response": "",
        "retrieved_context": [],
        "latency_ms": 500.0,
        "input_tokens": 10,
        "output_tokens": 10,
        "estimated_cost": 0.01,
    }
    defaults.update(overrides)
    return EvaluationInput(**defaults)


class TestExactMatchEvaluator:
    evaluator = ExactMatchEvaluator()

    def test_applies_only_with_exact_match_mode(self):
        case = _case(expected_answer="Hello.", metadata={"match_mode": "exact"})
        assert self.evaluator.applies_to(case) is True

        case_no_flag = _case(expected_answer="Hello.")
        assert self.evaluator.applies_to(case_no_flag) is False

        case_no_answer = _case(metadata={"match_mode": "exact"})
        assert self.evaluator.applies_to(case_no_answer) is False

    def test_passes_on_normalized_match(self):
        case = _case(expected_answer="  Hello   World  ", metadata={"match_mode": "exact"})
        result = self.evaluator.evaluate(_input(case, response="hello world"))

        assert result.passed is True
        assert result.score == 1.0

    def test_fails_on_mismatch(self):
        case = _case(expected_answer="Hello World", metadata={"match_mode": "exact"})
        result = self.evaluator.evaluate(_input(case, response="Goodbye World"))

        assert result.passed is False
        assert result.score == 0.0
        assert result.explanation is not None


class TestRequiredPhraseEvaluator:
    evaluator = RequiredPhraseEvaluator()

    def test_applies_only_when_required_phrases_present(self):
        assert self.evaluator.applies_to(_case(metadata={"required_phrases": ["x"]})) is True
        assert self.evaluator.applies_to(_case()) is False

    def test_passes_when_all_phrases_present(self):
        case = _case(metadata={"required_phrases": ["30 days", "refund"]})
        result = self.evaluator.evaluate(_input(case, response="You get a REFUND within 30 days."))

        assert result.passed is True
        assert result.score == 1.0

    def test_fails_when_a_phrase_is_missing(self):
        case = _case(metadata={"required_phrases": ["30 days", "refund"]})
        result = self.evaluator.evaluate(_input(case, response="You get a refund."))

        assert result.passed is False
        assert result.score == 0.5
        assert "30 days" in result.explanation


class TestForbiddenPhraseEvaluator:
    evaluator = ForbiddenPhraseEvaluator()

    def test_applies_only_when_forbidden_phrases_present(self):
        assert self.evaluator.applies_to(_case(metadata={"forbidden_phrases": ["x"]})) is True
        assert self.evaluator.applies_to(_case()) is False

    def test_passes_when_no_forbidden_phrase_present(self):
        case = _case(metadata={"forbidden_phrases": ["password is"]})
        result = self.evaluator.evaluate(_input(case, response="I can't share that."))

        assert result.passed is True

    def test_fails_when_forbidden_phrase_present(self):
        case = _case(metadata={"forbidden_phrases": ["password is"]})
        result = self.evaluator.evaluate(_input(case, response="The password is hunter2."))

        assert result.passed is False
        assert result.score == 0.0


class TestJSONSchemaEvaluator:
    evaluator = JSONSchemaEvaluator()
    schema = {
        "type": "object",
        "properties": {"status": {"type": "string"}},
        "required": ["status"],
    }

    def test_applies_only_when_schema_present(self):
        assert self.evaluator.applies_to(_case(metadata={"json_schema": self.schema})) is True
        assert self.evaluator.applies_to(_case()) is False

    def test_passes_on_valid_json_matching_schema(self):
        case = _case(metadata={"json_schema": self.schema})
        result = self.evaluator.evaluate(_input(case, response='{"status": "shipped"}'))

        assert result.passed is True

    def test_fails_on_invalid_json(self):
        case = _case(metadata={"json_schema": self.schema})
        result = self.evaluator.evaluate(_input(case, response="not json"))

        assert result.passed is False

    def test_fails_on_schema_violation(self):
        case = _case(metadata={"json_schema": self.schema})
        result = self.evaluator.evaluate(_input(case, response='{"other": 1}'))

        assert result.passed is False


class TestExpectedRefusalEvaluator:
    evaluator = ExpectedRefusalEvaluator()

    def test_applies_only_to_refuse_or_unsupported_behavior(self):
        assert self.evaluator.applies_to(_case(expected_behavior=ExpectedBehavior.REFUSE)) is True
        assert (
            self.evaluator.applies_to(_case(expected_behavior=ExpectedBehavior.UNSUPPORTED)) is True
        )
        assert self.evaluator.applies_to(_case(expected_behavior=ExpectedBehavior.ANSWER)) is False

    def test_passes_on_refusal_language(self):
        case = _case(expected_behavior=ExpectedBehavior.REFUSE)
        result = self.evaluator.evaluate(_input(case, response="I can't help with that."))

        assert result.passed is True

    def test_fails_when_no_refusal_language(self):
        case = _case(expected_behavior=ExpectedBehavior.UNSUPPORTED)
        result = self.evaluator.evaluate(_input(case, response="Sure, here's the answer: 42."))

        assert result.passed is False

    def test_custom_refusal_phrases_override_default(self):
        case = _case(
            expected_behavior=ExpectedBehavior.REFUSE,
            metadata={"refusal_phrases": ["nope"]},
        )
        result = self.evaluator.evaluate(_input(case, response="Nope, not doing that."))

        assert result.passed is True


class TestCitationPresenceEvaluator:
    evaluator = CitationPresenceEvaluator()

    def test_applies_when_reference_context_or_flag_present(self):
        assert self.evaluator.applies_to(_case(reference_context=["doc"])) is True
        assert self.evaluator.applies_to(_case(metadata={"requires_citation": True})) is True
        assert self.evaluator.applies_to(_case()) is False

    def test_passes_when_retrieved_context_present(self):
        case = _case(reference_context=["doc"])
        result = self.evaluator.evaluate(_input(case, retrieved_context=["doc"]))

        assert result.passed is True

    def test_fails_when_retrieved_context_empty(self):
        case = _case(reference_context=["doc"])
        result = self.evaluator.evaluate(_input(case, retrieved_context=[]))

        assert result.passed is False


class TestLatencyThresholdEvaluator:
    evaluator = LatencyThresholdEvaluator()

    def test_applies_to_every_case(self):
        assert self.evaluator.applies_to(_case()) is True

    def test_passes_under_default_threshold(self):
        result = self.evaluator.evaluate(_input(_case(), latency_ms=1000.0))

        assert result.passed is True

    def test_fails_over_default_threshold(self):
        result = self.evaluator.evaluate(_input(_case(), latency_ms=5000.0))

        assert result.passed is False

    def test_respects_metadata_override(self):
        case = _case(metadata={"max_latency_ms": 100.0})
        result = self.evaluator.evaluate(_input(case, latency_ms=200.0))

        assert result.passed is False
        assert result.threshold == 100.0


class TestCostThresholdEvaluator:
    evaluator = CostThresholdEvaluator()

    def test_passes_under_default_threshold(self):
        result = self.evaluator.evaluate(_input(_case(), estimated_cost=0.01))

        assert result.passed is True

    def test_fails_over_default_threshold(self):
        result = self.evaluator.evaluate(_input(_case(), estimated_cost=1.0))

        assert result.passed is False

    def test_respects_metadata_override(self):
        case = _case(metadata={"max_cost_usd": 0.001})
        result = self.evaluator.evaluate(_input(case, estimated_cost=0.01))

        assert result.passed is False
        assert result.threshold == 0.001
