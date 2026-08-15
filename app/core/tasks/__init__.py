"""Generic async-job infrastructure: SAQ queue, in-process worker, and status route.

Owns the queue connection and the worker builder, the same way `app.core.db` owns the
engine. Feature slices define their own job functions (a `tasks.py`) and their own
submission/dedup logic (their own `service`); they never build a queue or a worker.

Submission is deliberately NOT generic here: "does this target already have work in
flight" requires knowing what a target means for a given feature's jobs, which this
package has no business knowing. Status reads are generic because SAQ's own job record
already carries everything a caller needs, regardless of which feature enqueued it.
"""
