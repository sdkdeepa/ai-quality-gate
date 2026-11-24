"""M7: importing the server without its packages gives a clear install message."""

import subprocess
import sys
from pathlib import Path

import app

BACKEND_DIR = Path(__file__).resolve().parents[2]

# In a fresh interpreter, report FastAPI and Chroma as not installed (as in a
# core-only install), then import the server package. The CI core-only job
# checks the same message with the packages really absent.
PROBE = """
import importlib.util

real_find_spec = importlib.util.find_spec

def find_spec(name, *args, **kwargs):
    if name.split(".")[0] in {"fastapi", "chromadb"}:
        return None
    return real_find_spec(name, *args, **kwargs)

importlib.util.find_spec = find_spec
try:
    import app
except ImportError as exc:
    print(exc)
"""


def test_nothing_is_missing_in_a_full_install():
    assert app.missing_server_packages() == []


def test_missing_server_packages_name_the_extra_to_install():
    result = subprocess.run(
        [sys.executable, "-c", PROBE], cwd=BACKEND_DIR, capture_output=True, text=True, timeout=60
    )
    message = result.stdout.strip()
    assert "needs packages that aren't installed: fastapi, chromadb" in message
    assert "pip install 'ai-quality-gate[server]'" in message
    assert "The aqg CLI doesn't need them." in message
