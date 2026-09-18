"""Sprint 7: `create_app()`'s evaluator wiring reacts correctly to
`AQG_OPENAI_EVALS_ENABLED`, independently and combined with the other two
opt-in frameworks. Same env/cache-clearing pattern as the ragas/deepeval
app-wiring tests.
"""

import pytest

from app.core.config import get_settings
from app.evaluation.openai_evals.factory import OpenAIEvalsConfigurationError
from app.main import create_app


@pytest.fixture(autouse=True)
def _clear_settings_cache(monkeypatch):
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_openai_evals_disabled_by_default_yields_eight_evaluators():
    app = create_app()

    evaluators = app.state.evaluation_runner._evaluators
    assert len(evaluators) == 8
    assert not any(e.name.startswith("openai_evals_") for e in evaluators)


def test_openai_evals_enabled_alone_yields_ten_evaluators(monkeypatch):
    monkeypatch.setenv("AQG_OPENAI_EVALS_ENABLED", "true")
    monkeypatch.setenv("AQG_OPENAI_API_KEY", "sk-test")

    app = create_app()

    names = {e.name for e in app.state.evaluation_runner._evaluators}
    assert len(names) == 10
    assert "openai_evals_label_grader" in names
    assert "openai_evals_structured_correctness" in names


def test_openai_evals_enabled_without_api_key_fails_fast_at_startup(monkeypatch):
    monkeypatch.setenv("AQG_OPENAI_EVALS_ENABLED", "true")
    monkeypatch.delenv("AQG_OPENAI_API_KEY", raising=False)

    with pytest.raises(OpenAIEvalsConfigurationError):
        create_app()


def test_all_three_opt_in_frameworks_together_yield_fifteen_evaluators(monkeypatch):
    monkeypatch.setenv("AQG_RAGAS_ENABLED", "true")
    monkeypatch.setenv("AQG_DEEPEVAL_ENABLED", "true")
    monkeypatch.setenv("AQG_OPENAI_EVALS_ENABLED", "true")
    monkeypatch.setenv("AQG_OPENAI_API_KEY", "sk-test")

    app = create_app()

    evaluators = app.state.evaluation_runner._evaluators
    frameworks = {e.framework for e in evaluators}
    assert len(evaluators) == 15
    assert frameworks == {"deterministic", "ragas", "deepeval", "openai_evals"}
