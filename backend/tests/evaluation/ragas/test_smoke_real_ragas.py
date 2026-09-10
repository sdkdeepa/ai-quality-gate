"""Optional smoke test that makes ONE real RAGAS judge call (faithfulness).

Skipped entirely unless AQG_OPENAI_API_KEY is present - never runs in
ordinary `pytest` / CI unless a developer explicitly sets it (which will
incur real OpenAI API cost: one chat-completion call for the judge, one
embedding call for the judge's own internal statement-generation step).
"""

import os

import pytest

from app.core.config import Settings
from app.domain.evaluation_case import EvaluationCase
from app.evaluation.ragas.factory import build_ragas_evaluators
from app.evaluation.types import EvaluationInput


@pytest.mark.smoke
@pytest.mark.skipif(not os.environ.get("AQG_OPENAI_API_KEY"), reason="requires AQG_OPENAI_API_KEY")
def test_ragas_faithfulness_smoke_real_judge_call():
    settings = Settings(
        ragas_enabled=True,
        openai_api_key=os.environ["AQG_OPENAI_API_KEY"],
        openai_model=os.environ.get("AQG_OPENAI_MODEL", "gpt-4o-mini"),
        ragas_metrics="faithfulness",
    )
    [faithfulness_evaluator] = build_ragas_evaluators(settings)

    case = EvaluationCase(
        id="smoke-ragas-1",
        name="smoke",
        category="rag",
        query="What is the warranty length on electronics?",
    )
    evaluation_input = EvaluationInput(
        case=case,
        response="Electronics come with a 1-year limited warranty from the purchase date.",
        retrieved_context=[
            "All electronics purchased are covered by a 1-year limited "
            "warranty from the date of purchase."
        ],
        latency_ms=1.0,
        input_tokens=1,
        output_tokens=1,
        estimated_cost=0.0,
    )

    result = faithfulness_evaluator.evaluate(evaluation_input)

    assert result.metadata["ragas_status"] == "scored", result.explanation
    assert 0.0 <= result.score <= 1.0
    # A faithful answer, grounded in its retrieved context, should score high.
    assert result.score >= 0.5
