from datetime import UTC, datetime, timedelta

from app.domain.enums import GateStatus
from app.domain.gate_decision import GateDecision
from app.domain.release_policy import ReleasePolicy, default_policy
from app.repositories.sqlite import (
    BaselineRepository,
    GateDecisionRepository,
    PolicyRepository,
    SQLiteRepository,
)


class TestSQLiteRepositoryGeneric:
    def test_add_and_get_round_trips(self):
        repo = SQLiteRepository(":memory:", "policies", ReleasePolicy)
        policy = default_policy()

        repo.add(policy)

        assert repo.get(policy.id) == policy
        assert repo.count() == 1

    def test_list_returns_all_items(self):
        repo = SQLiteRepository(":memory:", "policies", ReleasePolicy)
        a = ReleasePolicy(name="a", version="1.0.0")
        b = ReleasePolicy(name="b", version="1.0.0")

        repo.add(a)
        repo.add(b)

        assert {p.id for p in repo.list()} == {a.id, b.id}

    def test_delete_removes_item(self):
        repo = SQLiteRepository(":memory:", "policies", ReleasePolicy)
        policy = default_policy()
        repo.add(policy)

        assert repo.delete(policy.id) is True
        assert repo.get(policy.id) is None
        assert repo.delete(policy.id) is False

    def test_get_missing_returns_none(self):
        repo = SQLiteRepository(":memory:", "policies", ReleasePolicy)

        assert repo.get("missing") is None

    def test_add_with_same_id_replaces(self):
        repo = SQLiteRepository(":memory:", "policies", ReleasePolicy)
        policy = default_policy()
        repo.add(policy)
        updated = policy.model_copy(update={"min_pass_rate": 0.5})

        repo.add(updated)

        assert repo.count() == 1
        assert repo.get(policy.id).min_pass_rate == 0.5

    def test_file_backed_persists_across_repository_instances(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        policy = default_policy()
        SQLiteRepository(db_path, "policies", ReleasePolicy).add(policy)

        reopened = SQLiteRepository(db_path, "policies", ReleasePolicy)

        assert reopened.get(policy.id) == policy

    def test_memory_databases_are_isolated_per_repository_instance(self):
        repo_a = SQLiteRepository(":memory:", "policies", ReleasePolicy)
        repo_b = SQLiteRepository(":memory:", "policies", ReleasePolicy)
        repo_a.add(default_policy())

        assert repo_a.count() == 1
        assert repo_b.count() == 0


class TestPolicyRepository:
    def test_get_active_returns_none_when_empty(self):
        repo = PolicyRepository(":memory:")

        assert repo.get_active() is None

    def test_get_active_returns_most_recently_created(self):
        repo = PolicyRepository(":memory:")
        older = ReleasePolicy(
            name="older", version="1.0.0", created_at=datetime.now(UTC) - timedelta(hours=1)
        )
        newer = ReleasePolicy(name="newer", version="1.0.0", created_at=datetime.now(UTC))

        repo.add(older)
        repo.add(newer)

        assert repo.get_active().name == "newer"


class TestBaselineRepository:
    def test_approve_assigns_version_one_for_first_baseline(self):
        repo = BaselineRepository(":memory:")

        baseline = repo.approve(
            dataset_name="support_bot",
            dataset_version="1.0.0",
            run_id="run-1",
            pass_rate=0.9,
            aggregate_metrics={"exact_match": 0.9},
        )

        assert baseline.version == 1

    def test_approve_increments_version_per_dataset(self):
        repo = BaselineRepository(":memory:")
        repo.approve(
            dataset_name="support_bot",
            dataset_version="1.0.0",
            run_id="run-1",
            pass_rate=0.9,
            aggregate_metrics={},
        )

        second = repo.approve(
            dataset_name="support_bot",
            dataset_version="1.1.0",
            run_id="run-2",
            pass_rate=0.95,
            aggregate_metrics={},
        )

        assert second.version == 2

    def test_versioning_is_scoped_per_dataset_name(self):
        repo = BaselineRepository(":memory:")
        repo.approve(
            dataset_name="dataset_a",
            dataset_version="1.0.0",
            run_id="run-1",
            pass_rate=1.0,
            aggregate_metrics={},
        )

        first_for_b = repo.approve(
            dataset_name="dataset_b",
            dataset_version="1.0.0",
            run_id="run-2",
            pass_rate=1.0,
            aggregate_metrics={},
        )

        assert first_for_b.version == 1

    def test_get_latest_for_dataset_returns_none_when_no_baselines(self):
        repo = BaselineRepository(":memory:")

        assert repo.get_latest_for_dataset("support_bot") is None

    def test_get_latest_for_dataset_returns_highest_version(self):
        repo = BaselineRepository(":memory:")
        repo.approve(
            dataset_name="support_bot",
            dataset_version="1.0.0",
            run_id="run-1",
            pass_rate=0.8,
            aggregate_metrics={},
        )
        repo.approve(
            dataset_name="support_bot",
            dataset_version="1.1.0",
            run_id="run-2",
            pass_rate=0.9,
            aggregate_metrics={},
        )

        latest = repo.get_latest_for_dataset("support_bot")

        assert latest.version == 2
        assert latest.run_id == "run-2"

    def test_list_for_dataset_filters_by_name(self):
        repo = BaselineRepository(":memory:")
        repo.approve(
            dataset_name="dataset_a",
            dataset_version="1.0.0",
            run_id="run-1",
            pass_rate=1.0,
            aggregate_metrics={},
        )
        repo.approve(
            dataset_name="dataset_b",
            dataset_version="1.0.0",
            run_id="run-2",
            pass_rate=1.0,
            aggregate_metrics={},
        )

        assert len(repo.list_for_dataset("dataset_a")) == 1
        assert len(repo.list_for_dataset("dataset_b")) == 1


class TestGateDecisionRepository:
    def _decision(self, **overrides) -> GateDecision:
        defaults = {
            "run_id": "run-1",
            "dataset_version": "1.0.0",
            "provider": "deterministic",
            "model": "fixture-v1",
            "policy_id": "policy-1",
            "policy_version": "1.0.0",
            "status": GateStatus.PASS,
        }
        defaults.update(overrides)
        return GateDecision(**defaults)

    def test_list_for_run_filters_by_run_id(self):
        repo = GateDecisionRepository(":memory:")
        repo.add(self._decision(run_id="run-1"))
        repo.add(self._decision(run_id="run-2"))

        results = repo.list_for_run("run-1")

        assert len(results) == 1
        assert results[0].run_id == "run-1"

    def test_list_history_orders_newest_first(self):
        repo = GateDecisionRepository(":memory:")
        older = self._decision(created_at=datetime.now(UTC) - timedelta(hours=1))
        newer = self._decision(created_at=datetime.now(UTC))
        repo.add(older)
        repo.add(newer)

        history = repo.list_history()

        assert history[0].id == newer.id
        assert history[1].id == older.id

    def test_list_history_respects_limit(self):
        repo = GateDecisionRepository(":memory:")
        for _ in range(5):
            repo.add(self._decision())

        assert len(repo.list_history(limit=2)) == 2
