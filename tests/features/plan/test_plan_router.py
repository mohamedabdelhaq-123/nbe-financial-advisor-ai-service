"""US3 Unit tests: Budget plan router."""


def test_plan_question_401_without_token(client):
    resp = client.post(
        "/internal/plan/question",
        json={
            "user_context": {},
            "answers": {},
            "questions_asked": 0,
        },
    )
    assert resp.status_code == 401


def test_plan_question_200_with_token(client, auth_headers):
    resp = client.post(
        "/internal/plan/question",
        json={
            "user_context": {},
            "answers": {},
            "questions_asked": 0,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "question" in data
    assert data["question"]["id"] is not None


def test_plan_generate_401_without_token(client):
    resp = client.post(
        "/internal/plan/generate",
        json={"user_context": {}, "answers": {}},
    )
    assert resp.status_code == 401


def test_plan_generate_200_sums_to_100(client, auth_headers):
    resp = client.post(
        "/internal/plan/generate",
        json={
            "user_context": {"monthly_income": 5000},
            "answers": {"savings_goal": "yes"},
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    allocations = data["allocations"]
    total = sum(int(a["percentage"]) for a in allocations)
    assert total == 100
