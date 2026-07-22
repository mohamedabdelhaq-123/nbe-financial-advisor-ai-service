"""US2/US3 unit tests: Embeddings router — auth guard, OpenAI-shaped contract, determinism."""

from app.core.config import settings


def test_embeddings_401_without_token(client):
    resp = client.post("/internal/embeddings", json={"input": "hello"})
    assert resp.status_code == 401


def test_embeddings_200_single_input(client, auth_headers):
    resp = client.post("/internal/embeddings", json={"input": "hello world"}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 1
    datum = body["data"][0]
    assert datum["object"] == "embedding"
    assert datum["index"] == 0
    assert len(datum["embedding"]) == 768
    assert body["model"] == settings.embeddings.model_name
    assert body["object"] == "list"
    assert body["usage"]["prompt_tokens"] > 0
    assert body["usage"]["total_tokens"] == body["usage"]["prompt_tokens"]


def test_embeddings_200_batch_input_preserves_order(client, auth_headers):
    resp = client.post("/internal/embeddings", json={"input": ["a", "b"]}, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert [d["index"] for d in data] == [0, 1]


def test_embeddings_422_empty_input_list(client, auth_headers):
    resp = client.post("/internal/embeddings", json={"input": []}, headers=auth_headers)
    assert resp.status_code == 422


def test_embeddings_422_blank_input(client, auth_headers):
    resp = client.post("/internal/embeddings", json={"input": ["   "]}, headers=auth_headers)
    assert resp.status_code == 422


def test_embeddings_422_non_positive_dimensions(client, auth_headers):
    resp = client.post(
        "/internal/embeddings", json={"input": "x", "dimensions": 0}, headers=auth_headers
    )
    assert resp.status_code == 422


def test_embeddings_200_custom_dimensions(client, auth_headers):
    resp = client.post(
        "/internal/embeddings", json={"input": "x", "dimensions": 256}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert len(resp.json()["data"][0]["embedding"]) == 256


def test_embeddings_502_on_provider_failure(client, auth_headers, monkeypatch):
    async def _raise(*args, **kwargs):
        raise RuntimeError("provider unreachable")

    monkeypatch.setattr("app.features.embed.router.embed_texts", _raise)

    resp = client.post("/internal/embeddings", json={"input": "hello"}, headers=auth_headers)
    assert resp.status_code == 502


def test_embeddings_deterministic_across_requests(client, auth_headers):
    resp1 = client.post("/internal/embeddings", json={"input": "same text"}, headers=auth_headers)
    resp2 = client.post("/internal/embeddings", json={"input": "same text"}, headers=auth_headers)
    resp3 = client.post(
        "/internal/embeddings", json={"input": "different text"}, headers=auth_headers
    )

    v1 = resp1.json()["data"][0]["embedding"]
    v2 = resp2.json()["data"][0]["embedding"]
    v3 = resp3.json()["data"][0]["embedding"]

    assert v1 == v2
    assert v1 != v3
