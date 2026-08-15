"""The in-process SAQ worker.

Takes an explicit list of job functions rather than discovering them, the same way
`app.main.create_app()` mounts an explicit list of feature routers rather than walking
`app/features/`. Wiring in a new feature's async jobs means adding one import and one
list entry in `app/main.py`'s lifespan — this module never imports a feature.
"""

from typing import cast

from saq import Queue, Worker
from saq.types import Context, FunctionsType, PartialTimersDict

WORKER_CONCURRENCY = 4
"""Jobs executed simultaneously by the in-process worker (SAQ default: 10).

Bounds concurrent heavyweight work — OCR and model calls — rather than short tasks, which
is what SAQ's higher default assumes.
"""

SWEEP_INTERVAL = 30
"""Seconds between sweeps, which bounds how quickly a job orphaned by a crash becomes
terminal instead of reading as running forever."""


def build_worker(queue: Queue, functions: FunctionsType[Context]) -> Worker[Context]:
    """Construct the in-process worker for `queue` over the given job functions.

    `functions` comes from the feature slices that own the work — this module never
    imports them, which is what keeps the dependency pointing one way.

    `SIGNALS` is emptied deliberately. `Worker.start()` otherwise calls
    `loop.add_signal_handler()` for SIGINT/SIGTERM, and that *replaces* any existing
    handler rather than chaining — inside the API process it would displace uvicorn's own
    handlers and break graceful shutdown. With no signals registered, the worker runs
    until the lifespan cancels its task, which is where shutdown belongs.
    """
    # SAQ declares PartialTimersDict as `TimersDict, total=False`, but inheriting with
    # total=False only relaxes newly-declared keys — the inherited ones stay required as
    # far as a type checker is concerned, so a partial literal needs a cast.
    timers = cast(PartialTimersDict, {"sweep": SWEEP_INTERVAL})
    worker: Worker[Context] = Worker(
        queue,
        functions=functions,
        concurrency=WORKER_CONCURRENCY,
        timers=timers,
    )
    worker.SIGNALS = []
    return worker
