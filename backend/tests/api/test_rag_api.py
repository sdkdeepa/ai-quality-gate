def test_query_requires_a_provider(client):
    response = client.post("/api/v1/rag/query", json={"query": "What is the warranty length?"})

    assert response.status_code == 422


def test_query_rejects_deterministic_provider(client):
    response = client.post(
        "/api/v1/rag/query",
        json={"query": "What is the warranty length?", "provider": "deterministic"},
    )

    assert response.status_code == 422


def test_query_with_openai_but_no_api_key_returns_400(client):
    response = client.post(
        "/api/v1/rag/query",
        json={"query": "What is the warranty length on electronics?", "provider": "openai"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "provider_not_configured"


def test_inspect_chunks_lists_the_full_corpus_by_default(client):
    response = client.get("/api/v1/rag/chunks")

    assert response.status_code == 200
    body = response.json()
    assert body["query"] is None
    assert body["chunk_count"] == 9
    assert {c["source_id"] for c in body["chunks"]} == {
        "return_policy",
        "warranty_policy",
        "shipping_policy",
        "shipping_policy_archive_2023",
        "loyalty_program",
        "data_retention_policy",
        "account_security",
        "subscription_management",
        "support_hours",
    }


def test_inspect_chunks_with_query_returns_ranked_matches(client):
    response = client.get("/api/v1/rag/chunks", params={"query": "electronics warranty length"})

    assert response.status_code == 200
    body = response.json()
    assert body["chunk_count"] >= 1
    assert body["chunks"][0]["source_id"] == "warranty_policy"
    assert body["chunks"][0]["relevance_score"] is not None


def test_inspect_chunks_with_off_topic_query_returns_no_matches(client):
    response = client.get(
        "/api/v1/rag/chunks", params={"query": "Can you help me pick a birthday gift for my mom?"}
    )

    assert response.status_code == 200
    assert response.json()["chunk_count"] == 0


def test_evaluate_rag_case_defaults_to_deterministic(client):
    response = client.post("/api/v1/rag/evaluate/rag-001", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["case_result"]["case_id"] == "rag-001"
    assert body["case_result"]["passed"] is True
    assert len(body["retrieved_chunks"]) >= 1
    assert body["retrieved_chunks"][0]["source_id"] == "warranty_policy"


def test_evaluate_rag_case_exposes_metrics_grouped_by_framework(client):
    """Sprint 5 requirement #8: deterministic vs. RAGAS metrics for the same
    case, inspectable side by side. RAGAS is disabled by default (no API
    key in this test environment), so only 'deterministic' shows up here -
    the key itself, and its grouping behavior, is what's under test."""
    response = client.post("/api/v1/rag/evaluate/rag-001", json={})

    assert response.status_code == 200
    body = response.json()
    assert "metrics_by_framework" in body
    assert set(body["metrics_by_framework"].keys()) == {"deterministic"}
    grouped_names = {m["metric_name"] for m in body["metrics_by_framework"]["deterministic"]}
    case_names = {m["metric_name"] for m in body["case_result"]["metric_results"]}
    assert grouped_names == case_names


def test_evaluate_rag_case_with_frameworks_filter_restricts_metrics(client):
    """Sprint 6 requirement #4, single-case path."""
    response = client.post(
        "/api/v1/rag/evaluate/rag-001",
        json={"frameworks": ["deterministic"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body["metrics_by_framework"].keys()) <= {"deterministic"}


def test_evaluate_rag_case_conflicting_scenario_fails_critically(client):
    response = client.post("/api/v1/rag/evaluate/rag-013", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["case_result"]["passed"] is False
    assert body["case_result"]["critical_failure"] is True
    failing = {m["metric_name"] for m in body["case_result"]["metric_results"] if not m["passed"]}
    assert "forbidden_phrases" in failing
    # retrieval genuinely surfaces both conflicting shipping documents
    retrieved_sources = {c["source_id"] for c in body["retrieved_chunks"]}
    assert {"shipping_policy", "shipping_policy_archive_2023"} <= retrieved_sources


def test_evaluate_rag_case_irrelevant_query_retrieves_nothing(client):
    response = client.post("/api/v1/rag/evaluate/rag-008", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["retrieved_chunks"] == []
    assert body["case_result"]["passed"] is True


def test_evaluate_rag_case_deliberate_refusal_failure(client):
    response = client.post("/api/v1/rag/evaluate/rag-009", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["case_result"]["passed"] is False
    failing = {m["metric_name"] for m in body["case_result"]["metric_results"] if not m["passed"]}
    assert "expected_refusal" in failing


def test_evaluate_rag_case_multi_chunk_scenario_retrieves_both_sources(client):
    response = client.post("/api/v1/rag/evaluate/rag-017", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["case_result"]["passed"] is True
    retrieved_sources = {c["source_id"] for c in body["retrieved_chunks"]}
    assert {"subscription_management", "return_policy"} <= retrieved_sources


def test_evaluate_unknown_case_returns_404(client):
    response = client.post("/api/v1/rag/evaluate/does-not-exist", json={})

    assert response.status_code == 404


def test_evaluate_rag_case_with_openai_but_no_api_key_returns_400(client):
    response = client.post("/api/v1/rag/evaluate/rag-001", json={"provider": "openai"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "provider_not_configured"
