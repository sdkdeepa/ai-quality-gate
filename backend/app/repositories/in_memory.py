from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class InMemoryRepository(Generic[T]):
    """Process-local, dict-backed repository. Not persistent; suitable for Sprint 1 only."""

    def __init__(self) -> None:
        self._items: dict[str, T] = {}

    def add(self, item: T) -> T:
        item_id = item.id
        self._items[item_id] = item
        return item

    def get(self, item_id: str) -> T | None:
        return self._items.get(item_id)

    def list(self) -> list[T]:
        return list(self._items.values())

    def delete(self, item_id: str) -> bool:
        return self._items.pop(item_id, None) is not None

    def count(self) -> int:
        return len(self._items)
