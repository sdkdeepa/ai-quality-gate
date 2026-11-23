"""Sample tests used only to produce the pytest JUnit fixture. Not part of the gate's suite."""

import os
from pathlib import Path

import pytest

COUNTER = Path(os.environ.get("AQG_FLAKY_COUNTER", "flaky-counter.txt"))


@pytest.fixture
def broken_setup():
    raise RuntimeError("database not reachable")


def test_passes():
    assert 1 + 1 == 2


def test_fails():
    assert "export" == "exports"


def test_errors_in_setup(broken_setup):
    assert True


@pytest.mark.skip(reason="not supported on CI")
def test_skipped():
    pass


@pytest.mark.xfail(reason="known bug #12")
def test_expected_failure():
    assert False  # noqa: B011 (sample test that must fail)


def test_flaky_passes_on_retry():
    count = int(COUNTER.read_text()) if COUNTER.exists() else 0
    COUNTER.write_text(str(count + 1))
    assert count >= 1, "first attempt fails"


@pytest.mark.parametrize("title", ["café", "日本語"])
def test_unicode_titles(title):
    assert title


class TestExport:
    def test_downloads_html(self):
        assert True
