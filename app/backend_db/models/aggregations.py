"""Computed spending/insight models — friendly re-exports of the generated mirror."""

from pgvector.sqlalchemy import VECTOR

from app.backend_db._generated_models import AnomalyFlags as AnomalyFlag
from app.backend_db._generated_models import MonthlySummaries as MonthlySummary
from app.backend_db._generated_models import NetWorthSnapshots as NetWorthSnapshot
from app.backend_db._generated_models import RecurringCharges as RecurringCharge
from app.backend_db._generated_models import SpendingPatternInsights as SpendingPatternInsight

_embedding_type = MonthlySummary.__table__.c.embedding.type
assert isinstance(_embedding_type, VECTOR)
assert _embedding_type.dim is not None, "monthly_summaries.embedding must be a fixed-size vector"
MONTHLY_SUMMARY_EMBEDDING_DIM: int = _embedding_type.dim

__all__ = [
    "MonthlySummary",
    "SpendingPatternInsight",
    "NetWorthSnapshot",
    "RecurringCharge",
    "AnomalyFlag",
    "MONTHLY_SUMMARY_EMBEDDING_DIM",
]
