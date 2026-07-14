"""US1/US3 unit tests: transaction embedding router — auth guard, validation, error mapping."""

import uuid

from app.features.transactions.service import TransactionsNotFoundError


def _uuid(n: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"router-{n}"))


def test_embed_401_without_token(client):
    resp = client.post("/internal/transactions/embed", json={"transaction_ids": [_uuid(1)]})
    assert resp.status_code == 401


def test_embed_200_with_mocked_service(client, auth_headers, monkeypatch):
    tid = _uuid(2)

    async def _mock_embed_transactions(
        session_gen, own_session_gen, transaction_ids, embed_fn=None
    ):
        return transaction_ids

    monkeypatch.setattr(
        "app.features.transactions.router.embed_transactions", _mock_embed_transactions
    )

    resp = client.post(
        "/internal/transactions/embed",
        json={"transaction_ids": [tid]},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["results"] == [{"transaction_id": tid, "status": "embedded"}]


def test_embed_422_empty_transaction_ids(client, auth_headers):
    resp = client.post(
        "/internal/transactions/embed", json={"transaction_ids": []}, headers=auth_headers
    )
    assert resp.status_code == 422


def test_embed_422_over_max_batch_size(client, auth_headers):
    ids = [str(uuid.uuid4()) for _ in range(501)]
    resp = client.post(
        "/internal/transactions/embed", json={"transaction_ids": ids}, headers=auth_headers
    )
    assert resp.status_code == 422


def test_embed_200_at_max_batch_size_boundary(client, auth_headers, monkeypatch):
    ids = [str(uuid.uuid4()) for _ in range(500)]

    async def _mock_embed_transactions(
        session_gen, own_session_gen, transaction_ids, embed_fn=None
    ):
        return transaction_ids

    monkeypatch.setattr(
        "app.features.transactions.router.embed_transactions", _mock_embed_transactions
    )

    resp = client.post(
        "/internal/transactions/embed", json={"transaction_ids": ids}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert len(resp.json()["results"]) == 500


def test_embed_404_on_transactions_not_found(client, auth_headers, monkeypatch):
    missing = _uuid(3)

    async def _mock_raise_not_found(session_gen, own_session_gen, transaction_ids, embed_fn=None):
        raise TransactionsNotFoundError([uuid.UUID(missing)])

    monkeypatch.setattr(
        "app.features.transactions.router.embed_transactions", _mock_raise_not_found
    )

    resp = client.post(
        "/internal/transactions/embed",
        json={"transaction_ids": [missing]},
        headers=auth_headers,
    )
    assert resp.status_code == 404
    assert resp.json() == {
        "detail": {
            "message": "One or more transaction IDs were not found",
            "invalid_transaction_ids": [missing],
        }
    }


def test_embed_502_on_provider_failure(client, auth_headers, monkeypatch):
    async def _mock_raise_generic(session_gen, own_session_gen, transaction_ids, embed_fn=None):
        raise RuntimeError("provider unreachable")

    monkeypatch.setattr("app.features.transactions.router.embed_transactions", _mock_raise_generic)

    resp = client.post(
        "/internal/transactions/embed",
        json={"transaction_ids": [_uuid(4)]},
        headers=auth_headers,
    )
    assert resp.status_code == 502
