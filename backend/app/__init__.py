"""AI Quality Gate API server.

Since M7 the server's packages are an optional extra: a plain
``pip install ai-quality-gate`` installs only the aqg CLI's core. If the
server is imported without them, say exactly what to install instead of
failing later with a bare ModuleNotFoundError. ``find_spec`` only looks the
packages up; nothing is imported here.
"""

from importlib.util import find_spec

_SERVER_PACKAGES = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "pydantic_settings": "pydantic-settings",
    "langchain_core": "langchain-core",
    "chromadb": "chromadb",
    "openai": "openai",
    "opentelemetry": "arize-phoenix-otel",
}


def missing_server_packages() -> list[str]:
    return [dist for module, dist in _SERVER_PACKAGES.items() if find_spec(module) is None]


_missing = missing_server_packages()
if _missing:
    raise ImportError(
        "The AI Quality Gate server needs packages that aren't installed: "
        f"{', '.join(_missing)}. Install them with: pip install 'ai-quality-gate[server]' "
        "(in a checkout of the repo: uv sync). The aqg CLI doesn't need them."
    )
