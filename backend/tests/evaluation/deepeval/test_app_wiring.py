"""Sprint 6: `create_app()`'s evaluator wiring
(`DEFAULT_EVALUATORS + build_ragas_evaluators(settings) + build_deepeval_evaluators(settings)`)
reacts correctly to `AQG_DEEPEVAL_ENABLED`, independently and combined with
`AQG_RAGAS_ENABLED`. Same env/cache-clearing pattern as
`tests/evaluation/ragas/test_app_wiring.py`.
"""

import pytest

from app.core.config import get_settings
from app.evaluation.deepeval.factory import DeepEvalConfigurationError
from app.main import create_app


@pytest.fixture(autouse=True)
def _clear_settings_cache(monkeypatch):
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_deepeval_disabled_by_default_yields_eight_evaluators():
    app = create_app()

    evaluators = app.state.evaluation_runner._evaluators
    assert len(evaluators) == 8
    assert not any(e.name.startswith("deepeval_") for e in evaluators)


def test_deepeval_enabled_alone_yields_nine_evaluators(monkeypatch):
    monkeypatch.setenv("AQG_DEEPEVAL_ENABLED", "true")
    monkeypatch.setenv("AQG_OPENAI_API_KEY", "sk-test")

    app = create_app()

    names = {e.name for e in app.state.evaluation_runner._evaluators}
    assert len(names) == 9
    assert "deepeval_criteria" in names


def test_deepeval_enabled_without_api_key_fails_fast_at_startup(monkeypatch):
    monkeypatch.setenv("AQG_DEEPEVAL_ENABLED", "true")
    monkeypatch.delenv("AQG_OPENAI_API_KEY", raising=False)

    with pytest.raises(DeepEvalConfigurationError):
        create_app()


def test_ragas_and_deepeval_together_yield_thirteen_evaluators(monkeypatch):
    monkeypatch.setenv("AQG_RAGAS_ENABLED", "true")
    monkeypatch.setenv("AQG_DEEPEVAL_ENABLED", "true")
    monkeypatch.setenv("AQG_OPENAI_API_KEY", "sk-test")

    app = create_app()

    evaluators = app.state.evaluation_runner._evaluators
    frameworks = {e.framework for e in evaluators}
    assert len(evaluators) == 13
    assert frameworks == {"deterministic", "ragas", "deepeval"}
