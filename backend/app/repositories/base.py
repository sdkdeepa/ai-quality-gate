from typing import Protocol, TypeVar

T = TypeVar("T")


class Repository(Protocol[T]):
    """Minimal storage contract. Concrete backends (in-memory, DB, ...) implement this."""

    def add(self, item: T) -> T: ...

    def get(self, item_id: str) -> T | None: ...

    def list(self) -> list[T]: ...

    def delete(self, item_id: str) -> bool: ...

    def count(self) -> int: ...
