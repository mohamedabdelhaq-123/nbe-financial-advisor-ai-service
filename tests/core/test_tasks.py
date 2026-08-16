"""Unit tests: the generic job-status surface in `app.core.tasks`.

Deliberately queue-free. `derive_state()` is a pure function precisely so the whole
status decision table can be asserted without SAQ, a database, or a running worker —
SAQ's Postgres backend has no offline mode, so anything that touched a real queue would
have to be an integration test.
"""

import pytest
from saq.job import Status

from app.core.tasks import service
from app.core.tasks.queue import SWEPT_ERROR_MESSAGE
from app.core.tasks.schemas import TaskState, epoch_ms_to_datetime
from app.core.tasks.service import INTERNAL_FAILURE_MESSAGE, TaskNotFoundError, derive_state

PROCESS_RESULT = {
    "prefix": "pfm-statements-ocr/3f8a1c2e/",
    "ocr_engine": "MinerU",
    "confidence_score": 1.0,
}


class _FakeJob:
    """Stands in for saq.Job — only the fields the status surface reads."""

    def __init__(self, key="job-1", function="ingestion.process", status=Status.QUEUED, **kw):
        self.key = key
        self.function = function
        self.status = status
        self.result = kw.pop("result", None)
        self.error = kw.pop("error", None)
        self.queued = kw.pop("queued", 1_764_000_000_000)
        self.started = kw.pop("started", 0)
        self.completed = kw.pop("completed", 0)


class _FakeQueue:
    """Stands in for saq.Queue — only `.job()`, the generic status read's only dependency."""

    def __init__(self, jobs=None):
        self._jobs = jobs or {}

    async def job(self, key):
        return self._jobs.get(key)


@pytest.fixture
def fake_queue(monkeypatch):
    queue = _FakeQueue()
    monkeypatch.setattr(service, "get_queue", lambda: queue)
    return queue


# --- status derivation ------------------------------------------------------


@pytest.mark.parametrize("status", [Status.NEW, Status.QUEUED])
def test_new_and_queued_report_as_queued(status):
    assert derive_state(status, None, None) == (TaskState.QUEUED, None, None)


def test_active_reports_as_running():
    assert derive_state(Status.ACTIVE, None, None) == (TaskState.RUNNING, None, None)


def test_complete_with_ok_envelope_reports_succeeded_with_result():
    state, result, error = derive_state(
        Status.COMPLETE, {"ok": True, "result": PROCESS_RESULT}, None
    )
    assert state is TaskState.SUCCEEDED
    assert result == PROCESS_RESULT
    assert error is None


def test_complete_with_failed_envelope_preserves_pipeline_detail():
    detail = "document processing engine failed: connection refused"
    state, result, error = derive_state(Status.COMPLETE, {"ok": False, "error": detail}, None)
    assert state is TaskState.FAILED
    assert result is None
    assert error == detail


def test_complete_without_recognisable_envelope_is_a_failure_not_an_empty_success():
    state, result, error = derive_state(Status.COMPLETE, "unexpected", None)
    assert (state, result, error) == (TaskState.FAILED, None, INTERNAL_FAILURE_MESSAGE)


@pytest.mark.parametrize("status", [Status.FAILED, Status.ABORTED, Status.ABORTING])
def test_unexpected_failure_never_leaks_a_stack_trace(status):
    trace = 'Traceback (most recent call last):\n  File "x.py", line 1\nValueError: boom'
    state, result, error = derive_state(status, None, trace)
    assert state is TaskState.FAILED
    assert error == INTERNAL_FAILURE_MESSAGE
    assert "Traceback" not in (error or "")


def test_swept_job_reports_as_interrupted_rather_than_generic():
    state, _, error = derive_state(Status.ABORTED, None, SWEPT_ERROR_MESSAGE)
    assert state is TaskState.FAILED
    assert error == SWEPT_ERROR_MESSAGE


def test_epoch_ms_conversion_treats_zero_as_not_yet_happened():
    assert epoch_ms_to_datetime(0) is None
    assert epoch_ms_to_datetime(None) is None
    converted = epoch_ms_to_datetime(1_764_000_000_000)
    assert converted is not None
    assert converted.year == 2025  # milliseconds, not seconds — seconds would give 1970


# --- status reads ------------------------------------------------------------


async def test_unknown_job_reference_raises_not_found(fake_queue):
    with pytest.raises(TaskNotFoundError):
        await service.get_task_status("nope")


async def test_status_read_reports_result_and_timestamps(monkeypatch):
    job = _FakeJob(
        key="job-done",
        status=Status.COMPLETE,
        result={"ok": True, "result": PROCESS_RESULT},
        started=1_764_000_001_000,
        completed=1_764_000_500_000,
    )
    monkeypatch.setattr(service, "get_queue", lambda: _FakeQueue(jobs={"job-done": job}))

    status = await service.get_task_status("job-done")

    assert status.state == TaskState.SUCCEEDED.value
    assert status.result == PROCESS_RESULT
    assert status.function == "ingestion.process"
    assert status.started_at is not None and status.finished_at is not None
    assert status.error is None


async def test_status_read_is_repeatable(monkeypatch):
    """Reading a result does not consume or alter it."""
    job = _FakeJob(key="job-done", status=Status.COMPLETE, result={"ok": True, "result": {}})
    monkeypatch.setattr(service, "get_queue", lambda: _FakeQueue(jobs={"job-done": job}))
    first = await service.get_task_status("job-done")
    second = await service.get_task_status("job-done")

    assert first.model_dump() == second.model_dump()
