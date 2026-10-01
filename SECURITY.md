# Security

This is a **production-oriented reference implementation**, not a
deployed production service — see "Do not claim production deployment"
below for exactly what that distinction means in practice. This document
describes what security posture exists today, what's deliberately out of
scope, and what a real deployment would need to add.

## Threat model

Assumed deployment: an internal engineering tool, reachable only inside a
trusted network boundary (a VPN, a private subnet, an internal load
balancer) — not exposed directly to the public internet. Nothing in this
document assumes otherwise, and nothing in the codebase has been
hardened against an anonymous public attacker (no WAF-equivalent
behavior, no CAPTCHA, no IP rate limiting). If you deploy this somewhere
internet-facing, treat everything in "Production gaps" below as
mandatory, not optional.

## What exists today

| Control | Where | Notes |
|---|---|---|
| **Secrets never baked into source or images** | `backend/.dockerignore`, `frontend/.dockerignore`, `.gitignore` | `.env*` is excluded from both git and Docker build contexts; every credential (`AQG_OPENAI_API_KEY`, `AQG_GEMINI_API_KEY`, `AQG_API_KEY`) is read from the environment at process start, never written into a layer or committed |
| **Secret-safe logging** | `app/core/redaction.py`, wired into `app/core/logging.py`'s `JSONFormatter` | Pattern-based redaction (OpenAI/Google key shapes, Bearer tokens, `key=value`-style credential fields) applied to every log message, every structured field, and exception tracebacks — defense-in-depth; nothing in this codebase deliberately logs a credential today |
| **Basic RBAC boundary** | `app/core/auth.py` | A single shared secret (`AQG_API_KEY`, off by default) gates all 6 mutating endpoints (`POST /evaluations/runs`, `/gate/decisions`, `/gate/baselines`, `/gate/policies`, `/rag/query`, `/rag/evaluate/{case_id}`); every GET stays open. Deliberately not per-user RBAC — see "Known limitations" |
| **Request size limiting** | `app/core/middleware.py`'s `MaxBodySizeMiddleware` | Rejects (413) a request whose declared `Content-Length` exceeds `AQG_MAX_REQUEST_BODY_BYTES` (default 2MB), before any handler reads the body |
| **Input validation** | Pydantic models throughout; `DatasetService.parse_dataset` | Every request body is schema-validated by FastAPI/Pydantic before a handler runs; a malformed golden-dataset file raises a clean `DatasetValidationError` (422) rather than an unhandled exception, and `load_all()` skips one bad file at startup rather than crashing the whole process |
| **No live path-traversal surface** | `app/services/dataset_service.py` (audited Sprint 12) | `GET /datasets/{name}/{version}` filters an in-memory list already loaded at startup — it never constructs a filesystem path from request input. `_fixture_path` derives its path from an already-validated dataset's own `name`/`version`, not fresh per-request strings |
| **Non-root, health-checked Docker images** | `backend/Dockerfile`, `frontend/Dockerfile` | Backend runs as uid 1000; frontend uses `nginxinc/nginx-unprivileged` (uid 101) by construction. Both have a `HEALTHCHECK` |
| **Dependency/security scanning** | `.github/workflows/pr.yml`'s `security-scan` job | `pip-audit --strict` (backend) and `npm audit --audit-level=high` (frontend) run as **blocking** checks on every PR — both confirmed clean against current dependencies |
| **Bounded request handling** | `app/reliability/retry.py`, `EvaluationRunner`'s evaluator timeout | Not security controls per se, but relevant: a malicious or buggy request can't cause unbounded resource consumption via an infinite retry loop or a permanently-hung evaluator thread blocking the request that triggered it |
| **Secrets-gated CI** | `.github/workflows/live-eval.yml` | The only workflow that touches a real provider key is `workflow_dispatch`-only (never automatic on a PR/push), and validates the required secret is actually set before spending anything |

## Known limitations (named, not hidden)

- **Request size limit has a chunked-transfer-encoding gap.**
  `MaxBodySizeMiddleware` checks `Content-Length`; a client omitting that
  header via chunked transfer encoding could stream an oversized body
  past it. No endpoint in this API intentionally accepts a chunked
  upload today. See `DECISIONS.md` #36.
- **Auth is a single shared secret, not per-user/per-role RBAC.** Every
  holder of the one key can perform every mutating action; there's no
  per-user audit trail beyond request logs, no key rotation mechanism,
  and no distinction between "can run evaluations" and "can register
  policies." `app/core/auth.py`'s `AuthBackend` Protocol is the
  extension point a real identity system would implement instead. See
  `DECISIONS.md` #37.
- **No TLS termination built in.** This app serves plain HTTP; a real
  deployment terminates TLS at a reverse proxy/load balancer in front of
  it (standard practice, not a gap specific to this codebase, but worth
  stating plainly since nothing here does it for you).
- **The dashboard does not yet send the `X-API-Key` header.** If
  `AQG_API_KEY` is ever enabled, every mutating action in `frontend/`
  (running an evaluation, "Run gate") would start failing with 401 until
  the dashboard is updated to send it — see `PROJECT_STATE.md`'s
  Outstanding Work.
- **SQLite policy/baseline/decision store is not encrypted at rest.**
  `AQG_POLICY_DB_PATH` writes a plain file.
- **A hung evaluator's worker thread is abandoned, not killed** (Python
  has no safe cross-platform way to forcibly terminate a thread) — it
  keeps running in the background consuming whatever resources it was
  using until it finishes on its own. The caller is never blocked
  waiting for it, which is the property that actually matters for
  availability, but repeated hangs could accumulate abandoned threads
  over time. See `DECISIONS.md` #38.
- **No rate limiting beyond the request-size cap.** Nothing throttles
  request *volume* per client/IP — relevant mainly if this were ever
  exposed beyond a trusted internal network (see "Threat model" above).
- **No audit log of *who* ran what beyond structured request logs.**
  Every evaluation run and gate decision is logged with full context
  (run_id, trace_id, dataset/policy version, provider/model — see
  `PROJECT_STATE.md`'s Sprint 12 section), but there's no persisted,
  queryable "user X ran Y at time Z" audit trail distinct from log
  lines.

## Do not claim production deployment

This codebase is built to **production-quality standards** — structured
logging, bounded retries, failure isolation, health/readiness checks,
dependency scanning, non-root containers, CI/CD — but it has never been
deployed as a production service, has no uptime history, no incident
history, no on-call rotation backing it, and no load-testing data. "I
would deploy this to production with confidence" and "this has run in
production" are different claims; only the first is true here. Treat
every number and guarantee in this document as "designed and tested for,"
not "proven in production."

## Reporting a concern

This is a portfolio/reference project, not a maintained product with a
security team or bug bounty. If you find something concerning while
reading the code, open a GitHub issue describing it — there's no formal
disclosure process beyond that.
