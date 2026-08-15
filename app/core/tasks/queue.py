"""The process-wide SAQ queue — connection and singleton.

Infrastructure, not a feature: this module owns the connection and the singleton, the
same way `app.core.db` owns the engine and `app.core.storage` owns the S3 client. Feature
slices supply job functions and enqueue work; they do not build queues.

The queue runs on the service's OWN database (SAQ's Postgres backend), so async jobs add
no broker and no second container. SAQ creates and migrates its own tables (`saq_jobs`,
`saq_stats`, `saq_versions`) when the queue connects — the same arrangement the LangGraph
checkpointer already has for its tables, and deliberately outside Alembic, whose target
stays `OwnBase.metadata` only.
"""

from saq import Queue

from app.core.db import psycopg_conn_string

QUEUE_NAME = "ingestion"
"""Single named queue. A second queue would need its own worker; there is no reason yet.

The name predates this module's extraction out of the ingestion slice — it is free to be
revisited if a second feature ever needs its own queue, but renaming a live queue is a
behavior change, not a cosmetic one, so it stays as-is here.
"""

SWEPT_ERROR_MESSAGE = "job was interrupted before it could finish; resubmit to retry"
"""Failure reason recorded for a job the sweep reclaims (SAQ default: "swept").

Worded for the caller, because unlike every other failure this one is surfaced verbatim:
it is the only `error` SAQ writes that isn't a stack trace, and matching against it is how
a status surface tells "interrupted by a restart" apart from "crashed".
"""


def build_queue(url: str | None = None) -> Queue:
    """Construct (but do not connect) the job queue."""
    return Queue.from_url(
        url or psycopg_conn_string(),
        name=QUEUE_NAME,
        swept_error_message=SWEPT_ERROR_MESSAGE,
    )


_queue: Queue | None = None


def set_queue(queue: Queue | None) -> None:
    """Install the process-wide queue (called from the app lifespan, and by tests)."""
    global _queue
    _queue = queue


def get_queue() -> Queue:
    """Return the connected queue, or fail loudly if the lifespan never ran."""
    if _queue is None:
        raise RuntimeError(
            "job queue is not initialised — app lifespan did not run, "
            "or set_queue() was never called"
        )
    return _queue
