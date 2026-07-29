"""Ingestion service — document processing (Part 1), statement normalization (Part 2),
and asynchronous submission over both (Part 3).

Reads a statement's location via the existing read-only backend DB access,
touches object storage, and writes exactly one audit-log row per call to the
service's own database. Neither part ever writes to a backend-owned table.

Split by capability: `process.py` (MinerU extraction), `normalize.py`
(LLM-backed transaction normalization), and `jobs.py` (submission and
deduplication over the shared queue in `app.core.tasks`).
"""

from app.features.ingestion.service.normalize import normalize_statement
from app.features.ingestion.service.process import process_statement

# isort: split
# Imported after process_statement/normalize_statement are bound above: jobs.py pulls in
# app.features.ingestion.tasks, which imports those two names back from this very
# package, so they must already exist on this (still-initializing) module.
from app.features.ingestion.service.jobs import submit_extraction_job, submit_normalization_job

__all__ = [
    "normalize_statement",
    "process_statement",
    "submit_extraction_job",
    "submit_normalization_job",
]
