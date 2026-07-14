"""Unit test: ingestion router — auth guard and happy-path wiring."""

from app.features.ingestion.schemas import NormalizeStatementResult, ProcessStatementResult


def test_process_401_without_token(client):
    resp = client.post(
        "/internal/ingestion/process",
        json={"statement_id": "3f8a1c2e-0000-4000-8000-000000000000"},
    )
    assert resp.status_code == 401


def test_process_200_with_token(client, auth_headers, monkeypatch):
    statement_id = "3f8a1c2e-0000-4000-8000-000000000000"

    async def _mock_process_statement(session_gen, own_session_gen, statement_id):
        return ProcessStatementResult(
            prefix=f"pfm-statements-ocr/{statement_id}/",
            ocr_engine="MinerU",
            confidence_score=1.0,
        )

    monkeypatch.setattr("app.features.ingestion.router.process_statement", _mock_process_statement)

    resp = client.post(
        "/internal/ingestion/process",
        json={"statement_id": statement_id},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ocr_engine"] == "MinerU"
    assert data["prefix"] == f"pfm-statements-ocr/{statement_id}/"
    assert data["confidence_score"] == 1.0


def test_process_422_on_malformed_statement_id(client, auth_headers):
    resp = client.post(
        "/internal/ingestion/process",
        json={"statement_id": "not-a-uuid"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_normalize_401_without_token(client):
    resp = client.post(
        "/internal/ingestion/normalize",
        json={"ocr_result_id": "3f8a1c2e-0000-4000-8000-000000000000"},
    )
    assert resp.status_code == 401


def test_normalize_200_with_token(client, auth_headers, monkeypatch):
    ocr_result_id = "3f8a1c2e-0000-4000-8000-000000000000"

    async def _mock_normalize_statement(session_gen, own_session_gen, ocr_result_id):
        return NormalizeStatementResult(
            normalized_json={"bank_name": None, "account_hint": None, "transactions": []},
            model_used="gpt-4o-mini",
        )

    monkeypatch.setattr(
        "app.features.ingestion.router.normalize_statement", _mock_normalize_statement
    )

    resp = client.post(
        "/internal/ingestion/normalize",
        json={"ocr_result_id": ocr_result_id},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["model_used"] == "gpt-4o-mini"
    assert data["normalized_json"]["transactions"] == []


def test_normalize_422_on_malformed_ocr_result_id(client, auth_headers):
    resp = client.post(
        "/internal/ingestion/normalize",
        json={"ocr_result_id": "not-a-uuid"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
