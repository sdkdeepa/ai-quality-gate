"""Redacts likely credentials/secrets from log output.

Applied by `app/core/logging.py`'s `JSONFormatter` to every log message and
`extra` field value, so a stray `logger.info(f"calling provider with key
{api_key}")` (or an SDK exception message that happens to echo back a
request header) never lands in plaintext in stdout/log aggregation. This
is a defense-in-depth backstop, not a substitute for simply not logging
secrets in the first place — nothing in this codebase deliberately logs an
API key today, but a regex-based scrubber catches the case where one
leaks in incidentally (an exception message, a raw request repr, ...)
without needing every call site to remember to redact by hand.

Deliberately pattern-based rather than an exhaustive secret-name
allowlist: new provider integrations (Sprint 5-7 added three) each bring
their own credential shape, and a pattern-based approach catches a new
provider's key format without this module needing an update every time.
"""

import re

_REDACTED = "***REDACTED***"

# Each pattern replaces its ENTIRE match (not just a capture group) with
# _REDACTED, so the key/label stays absent from output entirely rather
# than leaving "sk-***REDACTED***" (which would still confirm the value
# started with "sk-", a smaller but real leak of information).
_PATTERNS: list[re.Pattern[str]] = [
    # OpenAI-style secret keys: sk-..., sk-proj-..., sk-svcacct-...
    re.compile(r"\bsk-[A-Za-z0-9_-]{10,}\b"),
    # Google/Gemini API keys
    re.compile(r"\bAIza[A-Za-z0-9_-]{20,}\b"),
    # Authorization headers / bearer tokens, however capitalized
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._-]{10,}"),
]

# key="value"/key='value'/key=value style assignments for common
# credential-shaped field names (query strings, repr()'d request objects,
# config dumps, ...). Unlike _PATTERNS above, this keeps the key name
# visible and only redacts the value — "api_key=***REDACTED***" still
# tells you a credential field was there, which is worth keeping for
# debugging, whereas hiding the key name too would cost readability for
# no extra safety (the value is what could actually be used to
# authenticate as someone).
_KEY_VALUE_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|secret|password|passwd|"
    r"authorization|client[_-]?secret)\b(\s*[:=]\s*)"
    r"(\"[^\"]*\"|'[^']*'|\S+)"
)


def _redact_key_value(match: re.Match[str]) -> str:
    key, separator, _value = match.groups()
    return f"{key}{separator}{_REDACTED}"


def redact(text: str) -> str:
    """Returns `text` with every likely-credential substring replaced by a
    fixed placeholder. Safe to call on text with nothing to redact (a very
    common case — most log lines have no secret in them at all): each
    pattern is a no-op unless it actually matches."""
    for pattern in _PATTERNS:
        text = pattern.sub(_REDACTED, text)
    return _KEY_VALUE_PATTERN.sub(_redact_key_value, text)
