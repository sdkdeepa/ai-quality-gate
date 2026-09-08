from typing import Protocol


class CostCalculator(Protocol):
    """Turns token counts into an estimated USD cost. Kept separate from any
    provider so pricing can be updated (or swapped for a real billing-API
    lookup later) without touching provider request/response handling.
    """

    def estimate(self, model: str, input_tokens: int, output_tokens: int) -> float: ...


class TableCostCalculator:
    """Estimates cost from a static $/1M-token pricing table, keyed by model name.

    An unrecognized model name falls back to `default_price` (0.0, 0.0) rather
    than raising — a missing price should degrade to "cost unknown" (surfaced
    as 0.0), not break an evaluation run over a pricing-table gap.
    """

    def __init__(
        self,
        pricing: dict[str, tuple[float, float]],
        *,
        default_price: tuple[float, float] = (0.0, 0.0),
    ) -> None:
        self._pricing = pricing
        self._default_price = default_price

    def estimate(self, model: str, input_tokens: int, output_tokens: int) -> float:
        input_price_per_1m, output_price_per_1m = self._pricing.get(model, self._default_price)
        cost = (input_tokens / 1_000_000) * input_price_per_1m + (
            output_tokens / 1_000_000
        ) * output_price_per_1m
        return round(cost, 8)


# Approximate list prices in USD per 1M tokens (input, output). These are
# maintained by hand and will drift as providers change pricing — treat them
# as estimates for release-gate budgeting, not a billing source of truth.
# Unknown/future model names fall back to (0.0, 0.0) via `default_price` above.
OPENAI_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "o3-mini": (1.10, 4.40),
}

GEMINI_PRICING: dict[str, tuple[float, float]] = {
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-1.5-pro": (1.25, 5.00),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),
}
