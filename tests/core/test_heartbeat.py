"""Unit tests: `run_with_heartbeat` keeps a job touched while its real work runs.

Runs the loop for real (short intervals) rather than mocking `asyncio.sleep`, so the
assertion is that `job.update()` actually gets called repeatedly for work that outlasts
one interval — the exact failure mode this exists to prevent (a job swept as "stuck"
despite the worker still being on it).
"""

import asyncio

import pytest

from app.core.tasks import heartbeat as heartbeat_module
from app.core.tasks.heartbeat import run_with_heartbeat


class _FakeJob:
    def __init__(self):
        self.touches = 0

    async def update(self):
        self.touches += 1


@pytest.fixture(autouse=True)
def fast_heartbeat(monkeypatch):
    monkeypatch.setattr(heartbeat_module, "HEARTBEAT_INTERVAL", 0.01)


async def test_result_of_the_wrapped_work_is_returned():
    job = _FakeJob()

    async def work():
        return "done"

    result = await run_with_heartbeat({"job": job}, work())
    assert result == "done"


async def test_long_running_work_gets_touched_more_than_once():
    job = _FakeJob()

    async def work():
        await asyncio.sleep(0.05)
        return None

    await run_with_heartbeat({"job": job}, work())
    assert job.touches >= 2


async def test_short_work_does_not_leave_the_heartbeat_loop_running():
    job = _FakeJob()

    async def work():
        return None

    await run_with_heartbeat({"job": job}, work())
    touches_at_finish = job.touches
    await asyncio.sleep(0.05)
    assert job.touches == touches_at_finish


async def test_an_exception_from_the_work_still_propagates_and_stops_the_loop():
    job = _FakeJob()

    async def work():
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        await run_with_heartbeat({"job": job}, work())
