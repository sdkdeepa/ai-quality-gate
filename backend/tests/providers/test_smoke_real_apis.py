"""Optional smoke tests that make ONE real request per provider.

These are skipped entirely unless the matching API key env var is present —
they never run in ordinary `pytest` / CI unless a developer explicitly sets
AQG_OPENAI_API_KEY / AQG_GEMINI_API_KEY (which will incur real API cost).
"""

import os

import pytest

from app.providers.gemini_provider import GeminiProvider
from app.providers.openai_provider import OpenAIProvider
from app.providers.types import ProviderRequest

PROMPT = "Reply with exactly one word: pong"


@pytest.mark.smoke
@pytest.mark.skipif(not os.environ.get("AQG_OPENAI_API_KEY"), reason="requires AQG_OPENAI_API_KEY")
def test_openai_smoke_real_request():
    provider = OpenAIProvider(
        os.environ["AQG_OPENAI_API_KEY"],
        model=os.environ.get("AQG_OPENAI_MODEL", "gpt-4o-mini"),
    )

    response = provider.generate(ProviderRequest(case_id="smoke-openai", prompt=PROMPT))

    assert response.error is None, response.error
    assert response.provider == "openai"
    assert response.text
    assert response.latency_ms > 0


@pytest.mark.smoke
@pytest.mark.skipif(not os.environ.get("AQG_GEMINI_API_KEY"), reason="requires AQG_GEMINI_API_KEY")
def test_gemini_smoke_real_request():
    provider = GeminiProvider(
        os.environ["AQG_GEMINI_API_KEY"],
        model=os.environ.get("AQG_GEMINI_MODEL", "gemini-2.5-flash"),
    )

    response = provider.generate(ProviderRequest(case_id="smoke-gemini", prompt=PROMPT))

    assert response.error is None, response.error
    assert response.provider == "gemini"
    assert response.text
    assert response.latency_ms > 0
