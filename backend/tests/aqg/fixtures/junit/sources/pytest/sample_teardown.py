"""Sample tests used only to produce the pytest teardown-error JUnit fixture."""

import pytest


@pytest.fixture
def bad_teardown():
    yield
    raise RuntimeError("teardown boom")


def test_fail_and_teardown_error(bad_teardown):
    assert False  # noqa: B011 (sample test that must fail)


def test_pass_and_teardown_error(bad_teardown):
    assert True
