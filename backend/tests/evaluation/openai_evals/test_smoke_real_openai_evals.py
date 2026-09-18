"""Optional smoke test that makes real OpenAI Responses API grading calls
(one label classification, one fact-checklist score). Skipped entirely
unless AQG_OPENAI_API_KEY is present - never runs in ordinary `pytest` / CI
unless a developer explicitly sets it (incurs real OpenAI API cost).
"""

import os

import pytest

from app.core.config import Settings
from app.domain.evaluation_case import EvaluationCase
from app.evaluation.openai_evals.evaluator import (
    OpenAILabelGraderEvaluator,
    OpenAIStructuredCorrectnessEvaluator,
)
from app.evaluation.openai_evals.factory import build_openai_evals_evaluators
from app.evaluation.types import EvaluationInput


@pytest.mark.smoke
@pytest.mark.skipif(not os.environ.get("AQG_OPENAI_API_KEY"), reason="requires AQG_OPENAI_API_KEY")
def test_openai_evals_smoke_real_grading_calls():
    settings = Settings(
        openai_evals_enabled=True,
        openai_api_key=os.environ["AQG_OPENAI_API_KEY"],
        openai_model=os.environ.get("AQG_OPENAI_MODEL", "gpt-4o-mini"),
    )
    evaluators = build_openai_evals_evaluators(settings)
    [label_grader] = [e for e in evaluators if isinstance(e, OpenAILabelGraderEvaluator)]
    [structured] = [e for e in evaluators if isinstance(e, OpenAIStructuredCorrectnessEvaluator)]

    label_case = EvaluationCase(
        id="smoke-openai-evals-label",
        name="smoke",
        category="answer",
        query="A customer's order arrived damaged. What should we do?",
        metadata={
            "openai_grader_labels": ["compliant", "non_compliant"],
            "openai_grader_passing_labels": ["compliant"],
            "openai_grader_instructions": (
                "Policy: damaged orders must be offered a free replacement or full "
                "refund. Classify the response as 'compliant' if it offers one of "
                "these, otherwise 'non_compliant'."
            ),
        },
    )
    label_input = EvaluationInput(
        case=label_case,
        response="I'm sorry about that - I've sent a free replacement, no cost to you.",
        latency_ms=1.0,
        input_tokens=1,
        output_tokens=1,
        estimated_cost=0.0,
    )
    label_result = label_grader.evaluate(label_input)
    assert label_result.metadata["openai_evals_status"] == "scored", label_result.explanation
    assert label_result.passed is True

    structured_case = EvaluationCase(
        id="smoke-openai-evals-structured",
        name="smoke",
        category="answer",
        query="What's your return policy?",
        metadata={
            "openai_grader_expected_facts": [
                "returns are accepted within 30 days",
                "return shipping is free",
            ]
        },
    )
    structured_input = EvaluationInput(
        case=structured_case,
        response="You can return any item within 30 days for a full refund, "
        "and we cover return shipping.",
        latency_ms=1.0,
        input_tokens=1,
        output_tokens=1,
        estimated_cost=0.0,
    )
    structured_result = structured.evaluate(structured_input)
    assert structured_result.metadata["openai_evals_status"] == "scored", (
        structured_result.explanation
    )
    assert structured_result.score >= 0.5
