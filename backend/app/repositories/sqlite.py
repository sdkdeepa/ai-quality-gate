"""SQLite-backed repositories (requirement #7: "persistence via SQLite for
local use behind repository interfaces").

`SQLiteRepository[T]` implements the exact same `add`/`get`/`list`/
`delete`/`count` contract as `InMemoryRepository[T]`
(`app/repositories/in_memory.py`/`app/repositories/base.py`) - a drop-in
swap for any repository consumer, not a parallel storage design. Every
item is stored as a single JSON blob column keyed by its own `id` field
rather than a normalized relational schema; this trades relational
queryability for simplicity, appropriate to "local use" (see
DECISIONS.md #29). Subclasses add narrow, purpose-built query methods
(e.g. `BaselineRepository.get_latest_for_dataset`) on top, the same way
`InMemoryCaseResultStore` adds methods beyond the base `Repository[T]`
protocol.

A short-lived connection is opened per call rather than held open across
the repository's lifetime, so instances are safe to share across FastAPI's
threadpool without needing a lock.
"""

import sqlite3
import threading
from pathlib import Path
from typing import Generic, TypeVar
from uuid import uuid4

from pydantic import BaseModel

from app.domain.baseline import Baseline
from app.domain.gate_decision import GateDecision
from app.domain.release_policy import ReleasePolicy

T = TypeVar("T", bound=BaseModel)


class SQLiteRepository(Generic[T]):
    """One connection, held open for the repository's whole lifetime, and
    a lock serializing access to it. A fresh connection per call (this
    class's first draft) breaks for `:memory:` databases specifically —
    each new `sqlite3.connect(":memory:")` call is a distinct, empty
    database, so the table created by an earlier connection simply isn't
    there for a later one. A single held-open connection is correct for
    both `:memory:` (tests) and a real file path (the app), and the lock
    is what actually makes sharing it across FastAPI's threadpool safe —
    `sqlite3` connections are not safe for concurrent use from multiple
    threads on their own, `check_same_thread=False` only disables the
    same-thread check, it doesn't add thread-safety.
    """

    def __init__(self, db_path: str, table_name: str, model_cls: type[T]) -> None:
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._table = table_name
        self._model_cls = model_cls
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        with self._lock:
            self._conn.execute(
                f"CREATE TABLE IF NOT EXISTS {self._table} "  # noqa: S608 - hardcoded constant, never user input
                "(id TEXT PRIMARY KEY, data TEXT NOT NULL)"
            )
            self._conn.commit()

    def add(self, item: T) -> T:
        with self._lock:
            self._conn.execute(
                f"INSERT OR REPLACE INTO {self._table} (id, data) VALUES (?, ?)",  # noqa: S608
                (item.id, item.model_dump_json()),
            )
            self._conn.commit()
        return item

    def get(self, item_id: str) -> T | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT data FROM {self._table} WHERE id = ?",
                (item_id,),  # noqa: S608
            ).fetchone()
        return self._model_cls.model_validate_json(row[0]) if row else None

    def list(self) -> list[T]:
        with self._lock:
            rows = self._conn.execute(f"SELECT data FROM {self._table}").fetchall()  # noqa: S608
        return [self._model_cls.model_validate_json(row[0]) for row in rows]

    def delete(self, item_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                f"DELETE FROM {self._table} WHERE id = ?",
                (item_id,),  # noqa: S608
            )
            self._conn.commit()
        return cursor.rowcount > 0

    def count(self) -> int:
        with self._lock:
            row = self._conn.execute(f"SELECT COUNT(*) FROM {self._table}").fetchone()  # noqa: S608
        return row[0]


class PolicyRepository(SQLiteRepository[ReleasePolicy]):
    def __init__(self, db_path: str) -> None:
        super().__init__(db_path, "release_policies", ReleasePolicy)

    def get_active(self) -> ReleasePolicy | None:
        """The most recently created policy, or None if none have been
        registered yet. "Active" is deliberately simple (newest wins) —
        there is no separate activate/deactivate workflow this sprint;
        registering a new policy via `POST /api/v1/gate/policies` is how
        you change what's active."""
        policies = self.list()
        if not policies:
            return None
        return max(policies, key=lambda p: p.created_at)


class GateDecisionRepository(SQLiteRepository[GateDecision]):
    def __init__(self, db_path: str) -> None:
        super().__init__(db_path, "gate_decisions", GateDecision)

    def list_for_run(self, run_id: str) -> list[GateDecision]:
        return [d for d in self.list() if d.run_id == run_id]

    def list_history(self, limit: int = 50) -> list[GateDecision]:
        decisions = sorted(self.list(), key=lambda d: d.created_at, reverse=True)
        return decisions[:limit]


class BaselineRepository(SQLiteRepository[Baseline]):
    def __init__(self, db_path: str) -> None:
        super().__init__(db_path, "baselines", Baseline)

    def approve(
        self,
        *,
        dataset_name: str,
        dataset_version: str,
        run_id: str,
        pass_rate: float,
        aggregate_metrics: dict[str, float],
        approved_by: str | None = None,
        notes: str | None = None,
    ) -> Baseline:
        """Creates the next version (1, 2, 3, ...) for `dataset_name` and
        persists it. Version assignment is the repository's job, not the
        caller's, so baseline history for a dataset is always unambiguous."""
        existing = self.list_for_dataset(dataset_name)
        next_version = max((b.version for b in existing), default=0) + 1
        baseline = Baseline(
            id=str(uuid4()),
            dataset_name=dataset_name,
            dataset_version=dataset_version,
            version=next_version,
            run_id=run_id,
            pass_rate=pass_rate,
            aggregate_metrics=aggregate_metrics,
            approved_by=approved_by,
            notes=notes,
        )
        return self.add(baseline)

    def list_for_dataset(self, dataset_name: str) -> list[Baseline]:
        return [b for b in self.list() if b.dataset_name == dataset_name]

    def get_latest_for_dataset(self, dataset_name: str) -> Baseline | None:
        candidates = self.list_for_dataset(dataset_name)
        if not candidates:
            return None
        return max(candidates, key=lambda b: b.version)
