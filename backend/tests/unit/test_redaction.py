import json
import logging

from app.core.logging import JSONFormatter
from app.core.redaction import redact


class TestRedact:
    def test_redacts_openai_style_key(self):
        assert redact("key sk-abcdefghijklmnopqrst used") == "key ***REDACTED*** used"

    def test_redacts_google_style_key(self):
        text = redact("AIzaSyD1234567890abcdefghijklmnopqrs found")
        assert "AIzaSy" not in text
        assert "***REDACTED***" in text

    def test_redacts_bearer_token(self):
        assert redact("Authorization: Bearer abc123def456ghi789") == "Authorization: ***REDACTED***"

    def test_redacts_key_value_pairs_but_keeps_the_key_name(self):
        result = redact('api_key="sk-test-1234567890"')
        assert result == "api_key=***REDACTED***"

    def test_redacts_password_field(self):
        assert redact("password: hunter22222") == "password: ***REDACTED***"

    def test_redacts_client_secret_field(self):
        assert redact("client_secret=verysecretvalue123") == "client_secret=***REDACTED***"

    def test_leaves_ordinary_text_untouched(self):
        text = "this is a totally normal log line with no secrets in it at all"
        assert redact(text) == text

    def test_leaves_short_strings_that_merely_start_with_sk_dash_alone(self):
        # "sk-" alone isn't a credential; the pattern requires 10+ chars
        # after it to avoid false-positiving on e.g. a case id "sk-01".
        assert redact("sk-01") == "sk-01"


class TestJSONFormatterRedaction:
    def _format(self, message: str, extra: dict | None = None) -> dict:
        logger = logging.getLogger("test.redaction")
        logger.setLevel(logging.INFO)
        record = logger.makeRecord(
            logger.name, logging.INFO, __file__, 0, message, (), None, extra=extra
        )
        return json.loads(JSONFormatter().format(record))

    def test_redacts_a_secret_in_the_message_itself(self):
        payload = self._format("leaked key sk-abcdefghijklmnopqrst here")
        assert "sk-abcdefghijklmnopqrst" not in payload["message"]
        assert "***REDACTED***" in payload["message"]

    def test_redacts_a_secret_in_an_extra_field(self):
        payload = self._format("provider error", extra={"detail": "key sk-abcdefghijklmnopqrst"})
        assert "sk-abcdefghijklmnopqrst" not in payload["detail"]

    def test_non_string_extra_fields_pass_through_unredacted(self):
        payload = self._format("run completed", extra={"case_count": 40, "passed": True})
        assert payload["case_count"] == 40
        assert payload["passed"] is True

    def test_extra_fields_are_included_in_the_payload(self):
        """Regression test for the Sprint 12 bug: JSONFormatter previously
        built a fixed payload and silently dropped every `extra=` field -
        meaning RequestIDMiddleware's own path/method/status_code/
        duration_ms never once appeared in a log line."""
        payload = self._format(
            "request completed",
            extra={"path": "/api/v1/status", "method": "GET", "status_code": 200},
        )
        assert payload["path"] == "/api/v1/status"
        assert payload["method"] == "GET"
        assert payload["status_code"] == 200

    def test_standard_record_attributes_are_not_leaked_as_extra_fields(self):
        payload = self._format("hello")
        # Only the fixed, documented keys should appear - not internal
        # LogRecord attributes like "filename", "lineno", "funcName", etc.
        assert set(payload.keys()) <= {"timestamp", "level", "logger", "message", "request_id"}
