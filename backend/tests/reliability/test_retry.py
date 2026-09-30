from app.providers.types import ProviderError, ProviderErrorType, ProviderResponse
from app.reliability.retry import retry_provider_call


def _ok(text: str = "ok") -> ProviderResponse:
    return ProviderResponse(provider="p", model="m", latency_ms=1.0, text=text)


def _error(error_type: ProviderErrorType, message: str = "failed") -> ProviderResponse:
    return ProviderResponse(
        provider="p",
        model="m",
        latency_ms=1.0,
        error=ProviderError(error_type=error_type, message=message),
    )


class TestRetryProviderCall:
    def test_returns_immediately_on_first_success(self):
        calls = []

        def call():
            calls.append(1)
            return _ok()

        result = retry_provider_call(call, max_attempts=3, base_delay_seconds=0.001)

        assert len(calls) == 1
        assert result.ok

    def test_retries_a_retryable_failure_and_returns_the_eventual_success(self):
        calls = []

        def call():
            calls.append(1)
            if len(calls) < 3:
                return _error(ProviderErrorType.RATE_LIMIT)
            return _ok("finally")

        result = retry_provider_call(call, max_attempts=5, base_delay_seconds=0.001)

        assert len(calls) == 3
        assert result.ok
        assert result.text == "finally"

    def test_never_retries_authentication_failures(self):
        calls = []

        def call():
            calls.append(1)
            return _error(ProviderErrorType.AUTHENTICATION, "bad key")

        result = retry_provider_call(call, max_attempts=5, base_delay_seconds=0.001)

        assert len(calls) == 1
        assert not result.ok
        assert result.error.error_type == ProviderErrorType.AUTHENTICATION

    def test_never_retries_malformed_response_failures(self):
        calls = []

        def call():
            calls.append(1)
            return _error(ProviderErrorType.MALFORMED_RESPONSE)

        retry_provider_call(call, max_attempts=5, base_delay_seconds=0.001)

        assert len(calls) == 1

    def test_stops_after_max_attempts_and_returns_the_last_failure(self):
        calls = []

        def call():
            calls.append(1)
            return _error(ProviderErrorType.UNAVAILABLE, "still down")

        result = retry_provider_call(call, max_attempts=3, base_delay_seconds=0.001)

        assert len(calls) == 3
        assert not result.ok
        assert result.error.message == "still down"

    def test_max_attempts_of_one_means_no_retries(self):
        calls = []

        def call():
            calls.append(1)
            return _error(ProviderErrorType.TIMEOUT)

        retry_provider_call(call, max_attempts=1, base_delay_seconds=0.001)

        assert len(calls) == 1

    def test_backoff_delay_grows_between_attempts(self, monkeypatch):
        sleeps = []
        monkeypatch.setattr("app.reliability.retry.time.sleep", lambda s: sleeps.append(s))
        monkeypatch.setattr("app.reliability.retry.random.uniform", lambda a, b: 0.0)

        calls = []

        def call():
            calls.append(1)
            return _error(ProviderErrorType.RATE_LIMIT)

        retry_provider_call(call, max_attempts=4, base_delay_seconds=1.0)

        assert sleeps == [1.0, 2.0, 4.0]
