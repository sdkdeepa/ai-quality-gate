"""M1 acceptance: `import aqg` loads no server, tracing, LangChain, SQLite or AI SDK module.

Runs in a fresh interpreter, because this pytest process has already imported
FastAPI and friends through the server tests.
"""

import json
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]

FORBIDDEN_PREFIXES = (
    "app",
    "fastapi",
    "starlette",
    "uvicorn",
    "sqlite3",
    "_sqlite3",
    "opentelemetry",
    "openinference",
    "phoenix",
    "langchain",
    "langchain_core",
    "langchain_community",
    "langchain_openai",
    "langchain_chroma",
    "langchain_text_splitters",
    "chromadb",
    "ragas",
    "deepeval",
    "openai",
    "google.genai",
)

PROBE = """
import json, sys
import aqg
import aqg.evidence
import aqg.evidence.models
print(json.dumps(sorted(sys.modules)))
"""


def _is_forbidden(module: str) -> bool:
    return any(module == p or module.startswith(p + ".") for p in FORBIDDEN_PREFIXES)


def test_importing_aqg_loads_no_heavy_modules():
    result = subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    loaded = json.loads(result.stdout)
    assert "aqg.evidence.models" in loaded
    forbidden = sorted(m for m in loaded if _is_forbidden(m))
    assert forbidden == [], f"import aqg pulled in: {forbidden}"


def test_forbidden_check_catches_a_real_import():
    # Guard against the test above passing because of a broken matcher.
    assert _is_forbidden("fastapi")
    assert _is_forbidden("sqlite3")
    assert _is_forbidden("langchain_core.messages")
    assert _is_forbidden("app.main")
    assert not _is_forbidden("application")
    assert not _is_forbidden("pydantic")
