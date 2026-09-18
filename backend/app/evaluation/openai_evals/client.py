"""`OpenAIEvalsAdapter`: the only module allowed to build the OpenAI client
used purely for this framework's model-graded checks.

IMPORTANT — why this does NOT call OpenAI's hosted `/v1/evals` product:
OpenAI announced on 2026-06-03 that the entire Evals platform (the
`/v1/evals` API, its graders, and the dashboard) is being deprecated: it
goes read-only on 2026-10-31 and shuts down on 2026-11-30
(https://developers.openai.com/api/docs/deprecations). Building a new
adapter around an API with a ~2.5-month remaining lifespan (as of this
sprint) would mean shipping integration code that stops working before
most of this Gate's other Sprint 1-6 work is likely to be revisited.
Instead, this module reimplements the two most useful *grading concepts*
OpenAI's Evals graders offered — a closed-set label classifier ("label
grader") and a fact-checklist scorer (the "structured answer correctness"
idea from OpenAI's own Evals cookbook) — as direct, structured-output model
calls, using currently-supported, non-deprecated API surface
(`client.responses.parse`, the Responses API OpenAI recommends for all new
projects — see DECISIONS.md #26). `OpenAIEvalsAdapter` is still the name
the sprint asked for, since the *evaluation approach* (OpenAI-model-graded
checks against a rubric/checklist) is what "OpenAI Evals" refers to
conceptually; only the specific hosted product is avoided.

Mirrors `app/evaluation/ragas/client.py` and `app/evaluation/deepeval/client.py`
exactly otherwise: every SDK exception this can raise while grading is
caught here and mapped onto the same `ProviderErrorType` vocabulary already
used for provider, RAGAS, and DeepEval failures. `app/evaluation/openai_evals/evaluator.py`
never imports `openai`; it only ever sees `LabelGraderResult`/
`StructuredCorrectnessResult` (success) or `OpenAIEvalsEvaluatorError` (an
infrastructure failure) from this module.
"""

from dataclasses import dataclass
from typing import Literal

import openai
from pydantic import BaseModel, ValidationError, create_model

from app.providers.types import ProviderErrorType


@dataclass(frozen=True)
class LabelGraderResult:
    """The judge's chosen label plus its reasoning, and whether that label
    was one of the case's configured passing labels."""

    label: str
    passed: bool
    reasoning: str | None = None


@dataclass(frozen=True)
class StructuredCorrectnessResult:
    """Fraction of expected facts the judge confirmed are supported by the
    response, plus which facts were and weren't."""

    score: float
    supported_facts: list[str]
    unsupported_facts: list[str]
    reasoning: str | None = None


class OpenAIEvalsEvaluatorError(Exception):
    """Raised for any failure grading a case with this adapter.

    Always an EVALUATOR INFRASTRUCTURE failure (the grader did not run) —
    never raised, and never to be treated as, a real (e.g. low) quality
    score. Same contract as `RagasEvaluatorError`/`DeepEvalEvaluatorError`.
    """

    def __init__(self, message: str, *, error_type: ProviderErrorType) -> None:
        super().__init__(message)
        self.error_type = error_type


class _LabelJudgment(BaseModel):
    reasoning: str


class _FactJudgment(BaseModel):
    fact: str
    supported: bool


class _FactCheckJudgment(BaseModel):
    fact_checks: list[_FactJudgment]
    reasoning: str


class OpenAIEvalsAdapter:
    """Owns the OpenAI client used purely for this framework's grading
    calls, and the label-schema cache (each distinct label set needs its
    own dynamically-built Pydantic model so the judge's response is
    constrained, via Structured Outputs, to exactly one of the case's
    allowed labels — analogous to `DeepEvalClient` caching `GEval` metric
    instances per criteria signature)."""

    def __init__(self, *, api_key: str, judge_model: str, timeout_seconds: float) -> None:
        self._client = openai.OpenAI(api_key=api_key, timeout=timeout_seconds)
        self._judge_model = judge_model
        self._label_schema_cache: dict[tuple[str, ...], type[BaseModel]] = {}

    def classify_label(
        self,
        *,
        instructions: str,
        labels: list[str],
        passing_labels: list[str],
        input_text: str,
        actual_output: str,
    ) -> LabelGraderResult:
        schema = self._label_schema(tuple(labels))
        prompt = (
            f"{instructions}\n\n"
            f"Allowed labels: {', '.join(labels)}\n\n"
            f"Input:\n{input_text}\n\n"
            f"Response to classify:\n{actual_output}"
        )

        def _call():
            result = self._client.responses.parse(
                model=self._judge_model,
                instructions=(
                    "You are a strict, consistent classifier. Choose exactly one "
                    "label from the allowed set that best describes the response."
                ),
                input=prompt,
                text_format=schema,
            )
            parsed = result.output_parsed
            if parsed is None:
                raise OpenAIEvalsEvaluatorError(
                    "judge returned no parseable output (refused or incomplete)",
                    error_type=ProviderErrorType.MALFORMED_RESPONSE,
                )
            return parsed

        parsed = self._run(_call)
        label = parsed.label
        return LabelGraderResult(
            label=label, passed=label in passing_labels, reasoning=parsed.reasoning
        )

    def score_structured_facts(
        self, *, expected_facts: list[str], input_text: str, actual_output: str
    ) -> StructuredCorrectnessResult:
        facts_list = "\n".join(f"- {fact}" for fact in expected_facts)
        prompt = (
            "For each expected fact below, judge whether it is correctly and "
            "clearly supported by the response. Do not credit a fact that is "
            "merely plausible or partially implied - it must be actually stated.\n\n"
            f"Input:\n{input_text}\n\n"
            f"Response:\n{actual_output}\n\n"
            f"Expected facts:\n{facts_list}"
        )

        def _call():
            result = self._client.responses.parse(
                model=self._judge_model,
                instructions=(
                    "You are a strict fact-checker grading a response against a "
                    "checklist of expected facts."
                ),
                input=prompt,
                text_format=_FactCheckJudgment,
            )
            parsed = result.output_parsed
            if parsed is None:
                raise OpenAIEvalsEvaluatorError(
                    "judge returned no parseable output (refused or incomplete)",
                    error_type=ProviderErrorType.MALFORMED_RESPONSE,
                )
            return parsed

        parsed = self._run(_call)
        supported = [fc.fact for fc in parsed.fact_checks if fc.supported]
        unsupported = [fc.fact for fc in parsed.fact_checks if not fc.supported]
        total = len(expected_facts)
        score = len(supported) / total if total else 0.0
        return StructuredCorrectnessResult(
            score=score,
            supported_facts=supported,
            unsupported_facts=unsupported,
            reasoning=parsed.reasoning,
        )

    def _label_schema(self, labels: tuple[str, ...]) -> type[BaseModel]:
        schema = self._label_schema_cache.get(labels)
        if schema is None:
            schema = create_model(
                "LabelJudgment",
                __base__=_LabelJudgment,
                label=(Literal[labels], ...),
            )
            self._label_schema_cache[labels] = schema
        return schema

    def _run(self, call):
        try:
            return call()
        except openai.APITimeoutError as exc:
            raise OpenAIEvalsEvaluatorError(str(exc), error_type=ProviderErrorType.TIMEOUT) from exc
        except openai.AuthenticationError as exc:
            raise OpenAIEvalsEvaluatorError(
                str(exc), error_type=ProviderErrorType.AUTHENTICATION
            ) from exc
        except openai.RateLimitError as exc:
            raise OpenAIEvalsEvaluatorError(
                str(exc), error_type=ProviderErrorType.RATE_LIMIT
            ) from exc
        except openai.APIConnectionError as exc:
            raise OpenAIEvalsEvaluatorError(
                str(exc), error_type=ProviderErrorType.UNAVAILABLE
            ) from exc
        except openai.APIStatusError as exc:
            raise OpenAIEvalsEvaluatorError(
                str(exc), error_type=ProviderErrorType.UNAVAILABLE
            ) from exc
        except openai.OpenAIError as exc:
            raise OpenAIEvalsEvaluatorError(
                str(exc), error_type=ProviderErrorType.UNAVAILABLE
            ) from exc
        except ValidationError as exc:
            raise OpenAIEvalsEvaluatorError(
                f"judge response failed schema validation: {exc}",
                error_type=ProviderErrorType.MALFORMED_RESPONSE,
            ) from exc
        except OpenAIEvalsEvaluatorError:
            raise
        except Exception as exc:  # noqa: BLE001 - any other dependency failure
            raise OpenAIEvalsEvaluatorError(
                str(exc), error_type=ProviderErrorType.UNAVAILABLE
            ) from exc
