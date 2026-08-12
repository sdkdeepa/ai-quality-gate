from app.domain import EvaluationCase
from app.repositories.in_memory import InMemoryRepository


def test_add_and_get():
    repo = InMemoryRepository[EvaluationCase]()
    case = EvaluationCase(name="n", category="c", query="q")

    repo.add(case)

    assert repo.get(case.id) == case
    assert repo.count() == 1


def test_list_returns_all_items():
    repo = InMemoryRepository[EvaluationCase]()
    case_a = EvaluationCase(name="a", category="c", query="q")
    case_b = EvaluationCase(name="b", category="c", query="q")

    repo.add(case_a)
    repo.add(case_b)

    assert {c.id for c in repo.list()} == {case_a.id, case_b.id}


def test_delete_removes_item():
    repo = InMemoryRepository[EvaluationCase]()
    case = EvaluationCase(name="n", category="c", query="q")
    repo.add(case)

    assert repo.delete(case.id) is True
    assert repo.get(case.id) is None
    assert repo.delete(case.id) is False


def test_get_missing_returns_none():
    repo = InMemoryRepository[EvaluationCase]()

    assert repo.get("missing") is None
