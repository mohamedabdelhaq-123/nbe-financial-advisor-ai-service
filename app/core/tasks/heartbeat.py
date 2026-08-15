"""Keeps a long-running job's heartbeat alive while it does real work.

SAQ's sweep aborts an active job as "stuck" once it has gone longer than its configured
`heartbeat` window without being touched — and a job is only touched when something calls
`await job.update()`. Running the job body alone never does that, so any job whose real
work outlasts its heartbeat window gets swept as "interrupted before it could finish" even
though nothing crashed and the worker is still on it. This wraps a job body in a background
loop that keeps touching the job, so the heartbeat window can stay tight enough to catch a
genuinely orphaned job quickly without also capping how long a real job may run.
"""

import asyncio
import contextlib
from collections.abc import Awaitable
from typing import TypeVar

from saq.types import Context

_T = TypeVar("_T")

HEARTBEAT_INTERVAL = 10
"""Seconds between touches. Must stay well under any caller's configured job `heartbeat`,
so a touch always lands before the sweep could consider the job stuck."""


async def run_with_heartbeat(ctx: Context, work: Awaitable[_T]) -> _T:
    """Await `work`, touching `ctx["job"]` every `HEARTBEAT_INTERVAL` seconds until it's done."""

    async def _keep_alive() -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            await ctx["job"].update()

    heartbeat = asyncio.create_task(_keep_alive())
    try:
        return await work
    finally:
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat
