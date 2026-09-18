def _create_employee(client, auth_headers, emp_no: str, name: str) -> int:
    resp = client.post(
        "/api/v1/employees",
        json={"emp_no": emp_no, "name_ko": name, "hire_date": "2021-01-01"},
        headers=auth_headers,
    )
    return resp.json()["id"]


def _create_round(client, auth_headers) -> int:
    resp = client.post(
        "/api/v1/eval/rounds",
        json={"year": 2026, "name": "2026"},
        headers=auth_headers,
    )
    return resp.json()["id"]


def test_bulk_upsert_approvers(client, auth_headers):
    round_id = _create_round(client, auth_headers)
    evaluatee = _create_employee(client, auth_headers, "30000001", "피평가자")
    evaluator = _create_employee(client, auth_headers, "30000002", "평가자")

    resp = client.post(
        "/api/v1/eval/approvers",
        json={
            "round_id": round_id,
            "items": [
                {
                    "evaluatee_id": evaluatee,
                    "evaluator_id": evaluator,
                    "eval_type": "PERF",
                }
            ],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert len(data) == 1
    assert data[0]["eval_type"] == "PERF"


def test_bulk_upsert_duplicate_ignored(client, auth_headers):
    round_id = _create_round(client, auth_headers)
    e1 = _create_employee(client, auth_headers, "30000003", "E1")
    e2 = _create_employee(client, auth_headers, "30000004", "E2")

    payload = {
        "round_id": round_id,
        "items": [
            {"evaluatee_id": e1, "evaluator_id": e2, "eval_type": "COMP"},
            {"evaluatee_id": e1, "evaluator_id": e2, "eval_type": "COMP"},  # duplicate
        ],
    }
    resp = client.post("/api/v1/eval/approvers", json=payload, headers=auth_headers)
    assert resp.status_code == 201

    listed = client.get(
        f"/api/v1/eval/approvers?round_id={round_id}&eval_type=COMP",
        headers=auth_headers,
    )
    assert len(listed.json()) == 1


def test_multi_requires_rater_type(client, auth_headers):
    round_id = _create_round(client, auth_headers)
    e1 = _create_employee(client, auth_headers, "30000005", "E1")
    e2 = _create_employee(client, auth_headers, "30000006", "E2")

    resp = client.post(
        "/api/v1/eval/approvers",
        json={
            "round_id": round_id,
            "items": [{"evaluatee_id": e1, "evaluator_id": e2, "eval_type": "MULTI"}],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_delete_approver(client, auth_headers):
    round_id = _create_round(client, auth_headers)
    e1 = _create_employee(client, auth_headers, "30000007", "E1")
    e2 = _create_employee(client, auth_headers, "30000008", "E2")

    created = client.post(
        "/api/v1/eval/approvers",
        json={
            "round_id": round_id,
            "items": [{"evaluatee_id": e1, "evaluator_id": e2, "eval_type": "PERF"}],
        },
        headers=auth_headers,
    )
    approver_id = created.json()[0]["id"]

    resp = client.delete(f"/api/v1/eval/approvers/{approver_id}", headers=auth_headers)
    assert resp.status_code == 204

    listed = client.get(f"/api/v1/eval/approvers?round_id={round_id}", headers=auth_headers)
    assert len(listed.json()) == 0


def test_unknown_employee_returns_400(client, auth_headers):
    round_id = _create_round(client, auth_headers)

    resp = client.post(
        "/api/v1/eval/approvers",
        json={
            "round_id": round_id,
            "items": [{"evaluatee_id": 99998, "evaluator_id": 99999, "eval_type": "PERF"}],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_filter_by_eval_type(client, auth_headers):
    round_id = _create_round(client, auth_headers)
    a = _create_employee(client, auth_headers, "30000010", "A")
    b = _create_employee(client, auth_headers, "30000011", "B")

    client.post(
        "/api/v1/eval/approvers",
        json={
            "round_id": round_id,
            "items": [
                {"evaluatee_id": a, "evaluator_id": b, "eval_type": "PERF"},
                {"evaluatee_id": a, "evaluator_id": b, "eval_type": "COMP"},
            ],
        },
        headers=auth_headers,
    )

    perf_only = client.get(
        f"/api/v1/eval/approvers?round_id={round_id}&eval_type=PERF",
        headers=auth_headers,
    ).json()
    assert len(perf_only) == 1
    assert perf_only[0]["eval_type"] == "PERF"
