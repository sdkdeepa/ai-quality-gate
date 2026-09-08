import json
import time
from typing import Any

import openai
from openai import OpenAI

from app.providers.cost import OPENAI_PRICING, CostCalculator, TableCostCalculator
from app.providers.types import (
    ProviderError,
    ProviderErrorType,
    ProviderRequest,
    ProviderResponse,
)

DEFAULT_MODEL = "gpt-4o-mini"


class OpenAIProvider:
    """Provider backed by the OpenAI Chat Completions API.

    This is the only module in the codebase allowed to import `openai` — evaluation
    logic and the runner only ever see the normalized Provider contract. Every
    OpenAI SDK exception this client can raise is caught here and mapped onto a
    ProviderErrorType, so a single case failing (rate limit, timeout, bad key, ...)
    never raises out of `generate()`.

    For cases that ask for structured output (`json_schema` set), the model is
    asked for a JSON object; the raw text is always returned, and `structured_output`
    is a best-effort `json.loads` of it. Whether the JSON actually matches the
    requested schema is left to the downstream JSONSchemaEvaluator — that's a
    response-quality question the evaluator already answers, not a provider concern.
    """

    def __init__(
        self,
        api_key: str,
        *,
        model: str = DEFAULT_MODEL,
        timeout_seconds: float = 30.0,
        cost_calculator: CostCalculator | None = None,
        client: OpenAI | None = None,
    ) -> None:
        self.name = "openai"
        self.model = model
        self._client = client or OpenAI(api_key=api_key, timeout=timeout_seconds)
        self._cost_calculator = cost_calculator or TableCostCalculator(OPENAI_PRICING)

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        messages: list[dict[str, str]] = []
        if request.json_schema is not None:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Respond with JSON only, matching this schema: "
                        f"{json.dumps(request.json_schema)}"
                    ),
                }
            )
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.prompt})

        kwargs: dict[str, Any] = {"model": self.model, "messages": messages}
        if request.max_output_tokens is not None:
            kwargs["max_completion_tokens"] = request.max_output_tokens
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.json_schema is not None:
            kwargs["response_format"] = {"type": "json_object"}

        start = time.perf_counter()
        try:
            completion = self._client.chat.completions.create(**kwargs)
        except openai.APITimeoutError as exc:
            return self._error(start, ProviderErrorType.TIMEOUT, str(exc))
        except openai.AuthenticationError as exc:
            return self._error(start, ProviderErrorType.AUTHENTICATION, str(exc))
        except openai.RateLimitError as exc:
            return self._error(start, ProviderErrorType.RATE_LIMIT, str(exc))
        except openai.APIConnectionError as exc:
            return self._error(start, ProviderErrorType.UNAVAILABLE, str(exc))
        except openai.APIStatusError as exc:
            return self._error(start, ProviderErrorType.UNAVAILABLE, str(exc))
        except openai.OpenAIError as exc:
            return self._error(start, ProviderErrorType.UNAVAILABLE, str(exc))

        latency_ms = (time.perf_counter() - start) * 1000

        try:
            text = completion.choices[0].message.content or ""
            request_id = completion.id
        except (IndexError, AttributeError) as exc:
            return self._error(start, ProviderErrorType.MALFORMED_RESPONSE, str(exc))

        structured_output = None
        if request.json_schema is not None:
            try:
                structured_output = json.loads(text)
            except json.JSONDecodeError:
                structured_output = None

        usage = completion.usage
        input_tokens = usage.prompt_tokens if usage else None
        output_tokens = usage.completion_tokens if usage else None
        estimated_cost = (
            self._cost_calculator.estimate(self.model, input_tokens, output_tokens)
            if input_tokens is not None and output_tokens is not None
            else None
        )

        return ProviderResponse(
            provider=self.name,
            model=self.model,
            text=text,
            structured_output=structured_output,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost=estimated_cost,
            request_id=request_id,
        )

    def _error(self, start: float, error_type: ProviderErrorType, message: str) -> ProviderResponse:
        return ProviderResponse(
            provider=self.name,
            model=self.model,
            latency_ms=(time.perf_counter() - start) * 1000,
            error=ProviderError(error_type=error_type, message=message),
        )
