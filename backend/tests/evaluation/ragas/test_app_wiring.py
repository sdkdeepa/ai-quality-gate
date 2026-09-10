"""Sprint 5 requirement #7: `create_app()`'s evaluator wiring
(`DEFAULT_EVALUATORS + build_ragas_evaluators(settings)`) reacts correctly to
`AQG_RAGAS_ENABLED`. Uses real env vars + `get_settings.cache_clear()` since
`Settings` is process-cached via `@lru_cache` - every test clears the cache
both before (so it doesn't inherit a stale cached Settings from an earlier
test) and after (so later tests don't inherit this test's env either).
"""

import pytest

from app.core.config import get_settings
from app.evaluation.ragas.factory import RagasConfigurationError
from app.main import create_app


@pytest.fixture(autouse=True)
def _clear_settings_cache(monkeypatch):
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_ragas_disabled_by_default_yields_eight_evaluators():
    app = create_app()

    evaluators = app.state.evaluation_runner._evaluators
    assert len(evaluators) == 8
    assert not any(e.name.startswith("ragas_") for e in evaluators)


def test_ragas_enabled_with_api_key_yields_twelve_evaluators(monkeypatch):
    monkeypatch.setenv("AQG_RAGAS_ENABLED", "true")
    monkeypatch.setenv("AQG_OPENAI_API_KEY", "sk-test")

    app = create_app()

    names = {e.name for e in app.state.evaluation_runner._evaluators}
    assert len(names) == 12
    assert {
        "ragas_faithfulness",
        "ragas_answer_relevancy",
        "ragas_context_precision",
        "ragas_context_recall",
    } <= names


def test_ragas_enabled_without_api_key_fails_fast_at_startup(monkeypatch):
    monkeypatch.setenv("AQG_RAGAS_ENABLED", "true")
    monkeypatch.delenv("AQG_OPENAI_API_KEY", raising=False)

    with pytest.raises(RagasConfigurationError):
        create_app()


def test_ragas_enabled_with_selected_metrics_only(monkeypatch):
    monkeypatch.setenv("AQG_RAGAS_ENABLED", "true")
    monkeypatch.setenv("AQG_OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("AQG_RAGAS_METRICS", "faithfulness")

    app = create_app()

    names = {e.name for e in app.state.evaluation_runner._evaluators}
    assert len(names) == 9
    assert "ragas_faithfulness" in names
    assert "ragas_context_recall" not in names
