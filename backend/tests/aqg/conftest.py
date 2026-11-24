"""Lets tests/aqg run in a core-only install (M7).

Two modules compare aqg with the server (the M3 adapter tests and the M4
parity tests), so they need the server extra. In a core-only environment
they are left out; everything else here needs only the core.

Run in a core-only environment with ``--confcutdir=tests/aqg``, so the
server's own tests/conftest.py (which imports FastAPI) isn't loaded.
"""

from importlib.util import find_spec

NEEDS_SERVER = ["test_llm_adapter.py", "test_policy_parity.py"]

collect_ignore = [] if find_spec("fastapi") is not None else NEEDS_SERVER
