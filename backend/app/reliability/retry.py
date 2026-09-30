"""Bounded retries for live provider calls (Sprint 12 requirement: "bounded
retries"). This is the only retry logic in the codebase — evaluators
(RAGAS/DeepEval/OpenAI-Evals judge clients) are deliberately NOT retried
here or anywhere else; see this module's docstring further down for why.
"""

import logging
import random
import time
from collections.abc import Callable

from app.providers.types import ProviderResponse

logger = logging.getLogger("app.reliability")


def retry_provider_call(
    call: Callable[[], ProviderResponse],
    *,
    max_attempts: int,
    base_delay_seconds: float,
) -> ProviderResponse:
    """Calls `call()` up to `max_attempts` times, retrying only when the
    returned `ProviderResponse.error.retryable` is True (TIMEOUT/
    RATE_LIMIT/UNAVAILABLE — see `ProviderError.retryable`). Returns the
    first successful response, or the LAST failed response once attempts
    are exhausted — never raises (matches every Provider's own contract:
    `generate()` never raises, it returns an error).

    `max_attempts=1` (or less) means exactly one attempt, no retries — the
    default the whole codebase used through Sprint 11, still available by
    setting `AQG_PROVIDER_RETRY_MAX_ATTEMPTS=1`.

    Backoff is exponential with jitter: `base_delay_seconds * 2**(attempt-1)`,
    plus up to 25% random jitter so many concurrent callers retrying the
    same rate-limited provider don't all retry in lockstep.
    """
    response = call()
    attempt = 1
    while response.error is not None and response.error.retryable and attempt < max_attempts:
        delay = base_delay_seconds * (2 ** (attempt - 1))
        delay += random.uniform(0, delay * 0.25)  # noqa: S311 - jitter, not a security use
        logger.warning(
            "retrying provider call after %s failure (attempt %s/%s, waiting %.2fs)",
            response.error.error_type.value,
            attempt,
            max_attempts,
            delay,
            extra={
                "error_type": response.error.error_type.value,
                "attempt": attempt,
                "max_attempts": max_attempts,
            },
        )
        time.sleep(delay)
        response = call()
        attempt += 1
    return response
