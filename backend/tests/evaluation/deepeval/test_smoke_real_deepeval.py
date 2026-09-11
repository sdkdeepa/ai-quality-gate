"""Optional smoke test that makes ONE real DeepEval G-Eval judge call.

Skipped entirely unless AQG_OPENAI_API_KEY is present - never runs in
ordinary `pytest` / CI unless a developer explicitly sets it (incurs real
OpenAI API cost: one chat-completion call for the judge).
"""

import os

import pytest

from app.core.config import Settings
from app.domain.evaluation_case import EvaluationCase
from app.evaluation.deepeval.factory import build_deepeval_evaluators
from app.evaluation.types import EvaluationInput


@pytest.mark.smoke
@pytest.mark.skipif(not os.environ.get("AQG_OPENAI_API_KEY"), reason="requires AQG_OPENAI_API_KEY")
def test_deepeval_criteria_smoke_real_judge_call():
    settings = Settings(
        deepeval_enabled=True,
        openai_api_key=os.environ["AQG_OPENAI_API_KEY"],
        openai_model=os.environ.get("AQG_OPENAI_MODEL", "gpt-4o-mini"),
    )
    [criteria_evaluator] = build_deepeval_evaluators(settings)

    case = EvaluationCase(
        id="smoke-deepeval-1",
        name="smoke",
        category="answer",
        query="My order arrived damaged, what can I do?",
        metadata={
            "deepeval_criteria": "Is the response empathetic and does it offer a resolution?"
        },
    )
    evaluation_input = EvaluationInput(
        case=case,
        response=(
            "I'm really sorry to hear your order arrived damaged. I've started "
            "a replacement for you at no extra cost - it should arrive within 3-5 days."
        ),
        latency_ms=1.0,
        input_tokens=1,
        output_tokens=1,
        estimated_cost=0.0,
    )

    result = criteria_evaluator.evaluate(evaluation_input)

    assert result.metadata["deepeval_status"] == "scored", result.explanation
    assert 0.0 <= result.score <= 1.0
    # An empathetic, resolution-offering answer should score high.
    assert result.score >= 0.5
