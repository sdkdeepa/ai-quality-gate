import json
import time

import httpx
from google import genai
from google.genai import errors, types

from app.providers.cost import GEMINI_PRICING, CostCalculator, TableCostCalculator
from app.providers.types import (
    ProviderError,
    ProviderErrorType,
    ProviderRequest,
    ProviderResponse,
)

DEFAULT_MODEL = "gemini-2.5-flash"


class GeminiProvider:
    """Provider backed by the Gemini API via `google-genai`.

    This is the only module in the codebase allowed to import `google.genai` —
    evaluation logic and the runner only ever see the normalized Provider
    contract. Every SDK exception this client can raise is caught here and
    mapped onto a ProviderErrorType, so a single case failing never raises out
    of `generate()`.

    Unlike OpenAI's chat-completions JSON mode, Gemini's `response_json_schema`
    accepts the requested schema directly (including a top-level array, which
    the seed dataset's `str-002` case uses), so structured-output requests pass
    the schema straight through instead of only steering via prompt text.
    """

    def __init__(
        self,
        api_key: str,
        *,
        model: str = DEFAULT_MODEL,
        timeout_seconds: float = 30.0,
        cost_calculator: CostCalculator | None = None,
        client: genai.Client | None = None,
    ) -> None:
        self.name = "gemini"
        self.model = model
        self._timeout_ms = timeout_seconds * 1000
        self._client = client or genai.Client(api_key=api_key)
        self._cost_calculator = cost_calculator or TableCostCalculator(GEMINI_PRICING)

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        config_kwargs: dict = {"http_options": types.HttpOptions(timeout=self._timeout_ms)}
        if request.system_prompt:
            config_kwargs["system_instruction"] = request.system_prompt
        if request.temperature is not None:
            config_kwargs["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            config_kwargs["max_output_tokens"] = request.max_output_tokens
        if request.json_schema is not None:
            config_kwargs["response_mime_type"] = "application/json"
            config_kwargs["response_json_schema"] = request.json_schema
        config = types.GenerateContentConfig(**config_kwargs)

        start = time.perf_counter()
        try:
            response = self._client.models.generate_content(
                model=self.model, contents=request.prompt, config=config
            )
        except (httpx.TimeoutException, TimeoutError) as exc:
            return self._error(start, ProviderErrorType.TIMEOUT, str(exc))
        except errors.ClientError as exc:
            return self._error(start, self._classify_client_error(exc), str(exc))
        except errors.ServerError as exc:
            return self._error(start, ProviderErrorType.UNAVAILABLE, str(exc))
        except errors.APIError as exc:
            return self._error(start, ProviderErrorType.UNAVAILABLE, str(exc))

        latency_ms = (time.perf_counter() - start) * 1000

        try:
            text = response.text or ""
        except (AttributeError, ValueError) as exc:
            return self._error(start, ProviderErrorType.MALFORMED_RESPONSE, str(exc))

        structured_output = None
        if request.json_schema is not None:
            try:
                structured_output = json.loads(text)
            except json.JSONDecodeError:
                structured_output = None

        usage = response.usage_metadata
        input_tokens = usage.prompt_token_count if usage else None
        output_tokens = usage.candidates_token_count if usage else None
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
            request_id=response.response_id,
        )

    @staticmethod
    def _classify_client_error(exc: "errors.ClientError") -> ProviderErrorType:
        if exc.code in (401, 403):
            return ProviderErrorType.AUTHENTICATION
        if exc.code == 429:
            return ProviderErrorType.RATE_LIMIT
        message = (exc.message or "").lower()
        if "api key" in message or "api_key" in message or "permission" in message:
            return ProviderErrorType.AUTHENTICATION
        return ProviderErrorType.UNAVAILABLE

    def _error(self, start: float, error_type: ProviderErrorType, message: str) -> ProviderResponse:
        return ProviderResponse(
            provider=self.name,
            model=self.model,
            latency_ms=(time.perf_counter() - start) * 1000,
            error=ProviderError(error_type=error_type, message=message),
        )
