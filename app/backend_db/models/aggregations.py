"""Computed spending/insight models — friendly re-exports of the generated mirror."""

from app.backend_db._generated_models import AnomalyFlags as AnomalyFlag
from app.backend_db._generated_models import MonthlySummaries as MonthlySummary
from app.backend_db._generated_models import NetWorthSnapshots as NetWorthSnapshot
from app.backend_db._generated_models import RecurringCharges as RecurringCharge
from app.backend_db._generated_models import SpendingPatternInsights as SpendingPatternInsight

__all__ = [
    "MonthlySummary",
    "SpendingPatternInsight",
    "NetWorthSnapshot",
    "RecurringCharge",
    "AnomalyFlag",
]
