"""HTTP-level tests: the generic `GET /internal/tasks/{job_id}` route."""

from app.core.tasks import router as tasks_router
from app.core.tasks.schemas import TaskStatusResponse, epoch_ms_to_datetime
from app.core.tasks.service import TaskNotFoundError


def test_read_task_401_without_token(client):
    """Stored job results carry full pipeline detail — unreachable without the shared secret."""
    assert client.get("/internal/tasks/job-1").status_code == 401


def test_read_task_404_for_unknown_reference(client, auth_headers, monkeypatch):
    async def _mock_status(job_key):
        raise TaskNotFoundError(job_key)

    monkeypatch.setattr(tasks_router, "get_task_status", _mock_status)

    resp = client.get("/internal/tasks/nope", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "job not found"


def test_failed_job_is_still_reported_with_200(client, auth_headers, monkeypatch):
    """The read succeeded; the job is what failed."""

    async def _mock_status(job_key):
        return TaskStatusResponse(
            job_id=job_key,
            function="ingestion.normalize",
            state="failed",
            submitted_at=epoch_ms_to_datetime(1_764_000_000_000),
            error="normalization engine failed: connection refused",
        )

    monkeypatch.setattr(tasks_router, "get_task_status", _mock_status)

    resp = client.get("/internal/tasks/job-9", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["state"] == "failed"
    assert "connection refused" in resp.json()["error"]
