# JUnit XML fixtures (M2)

These XML files are **real output** from each tool, not hand-written. The sample
tests that produced them are in `sources/`. Don't edit the XML by hand: if a tool
changes its format, regenerate the file and explain the change in the PR.

Tests that need broken input (truncated files, count mismatches, duplicates,
DOCTYPEs) build it in the test from these files, so every case starts from a
real report.

| File | Tool | What it covers |
|---|---|---|
| `pytest.xml` | pytest 9.2.0 + pytest-rerunfailures 16.7, `--reruns 1` | pass, failure, setup error, skip, xfail, a flaky test, Unicode ids, a test class. Earlier attempts appear as extra, empty `<testcase>` entries with the same id, and `tests=` counts unique tests (9 tests, 12 entries). |
| `pytest-teardown.xml` | pytest 9.2.0, no plugins | A test that fails *and* errors in teardown is written as two entries with the same id, and `tests="3"` for 2 tests. |
| `vitest.xml` | Vitest 5.1.1, `retry: 1` | pass, failure, a thrown error (Vitest reports it as a failure), skip, todo, Unicode names. A retried test keeps one `<testcase>` with one `<failure>` per attempt. A test that passes on retry looks like a plain pass. |
| `playwright.xml` | @playwright/test 1.65.1, `retries: 1` | pass, failure, timeout (reported as `<error>`), skip, fixme, Unicode names. Only the final attempt is written; a test that passes on retry looks like a plain pass. |
| `playwright-two-projects.xml` | @playwright/test 1.65.1, two projects | The same test in two projects gets the same id (the project only appears in `hostname`). Used for the duplicate-id tests. |

## Regenerating

pytest (from `sources/pytest/`, in a virtual environment with the versions above):

```
rm -f flaky-counter.txt
python -m pytest sample_suite.py --reruns 1 --junitxml=pytest.xml -p no:cacheprovider
python -m pytest sample_teardown.py --junitxml=pytest-teardown.xml -p no:cacheprovider
```

Vitest (put `sample.spec.ts` in `src/` of an empty npm project with `vitest` installed):

```
npx vitest run          # uses vitest.config.ts, writes vitest.xml
```

Playwright (put `export.spec.ts` in `e2e/` of an empty npm project with
`@playwright/test` installed; the tests don't open a browser, so none needs installing):

```
npx playwright test                                         # writes playwright.xml
npx playwright test -c playwright-two-projects.config.ts    # writes playwright-two-projects.xml
```

The `sources/` files are not collected by the gate's own test suite: their names
don't match `test_*.py`, and the `.ts` files are outside the frontend project.
