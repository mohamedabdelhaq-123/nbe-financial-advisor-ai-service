"""Ingestion service — document processing (Part 1) and statement normalization (Part 2).

Reads a statement's location via the existing read-only backend DB access,
touches object storage, and writes exactly one audit-log row per call to the
service's own database. Neither part ever writes to a backend-owned table.

Split by capability: `process.py` (MinerU extraction) and `normalize.py`
(LLM-backed transaction normalization).
"""

from app.features.ingestion.service.normalize import normalize_statement
from app.features.ingestion.service.process import process_statement

__all__ = ["normalize_statement", "process_statement"]
