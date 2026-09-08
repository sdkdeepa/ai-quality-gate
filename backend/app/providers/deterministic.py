import json

from app.evaluation.types import FixtureResponse
from app.providers.types import (
    ProviderError,
    ProviderErrorType,
    ProviderRequest,
    ProviderResponse,
)


class DeterministicProvider:
    """A Provider backed by pre-recorded FixtureResponses, for tests and CI.

    Reuses the Sprint 2 fixture files as-is: this is that same fixture map
    wearing the Provider contract, so a run against it is byte-for-byte
    identical to the pre-provider fixture-driven runner.
    """

    def __init__(
        self,
        fixtures: dict[str, FixtureResponse],
        *,
        model: str = "fixture-v1",
        name: str = "deterministic",
    ) -> None:
        self.name = name
        self.model = model
        self._fixtures = fixtures

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        fixture = self._fixtures.get(request.case_id)
        if fixture is None:
            return ProviderResponse(
                provider=self.name,
                model=self.model,
                latency_ms=0.0,
                error=ProviderError(
                    error_type=ProviderErrorType.MALFORMED_RESPONSE,
                    message=f"no fixture response for case_id={request.case_id!r}",
                ),
            )

        structured_output = None
        if request.json_schema is not None:
            try:
                structured_output = json.loads(fixture.response)
            except json.JSONDecodeError:
                structured_output = None

        return ProviderResponse(
            provider=self.name,
            model=self.model,
            text=fixture.response,
            structured_output=structured_output,
            retrieved_context=fixture.retrieved_context,
            latency_ms=fixture.latency_ms,
            input_tokens=fixture.input_tokens,
            output_tokens=fixture.output_tokens,
            estimated_cost=fixture.estimated_cost,
            request_id=f"fixture:{request.case_id}",
        )
