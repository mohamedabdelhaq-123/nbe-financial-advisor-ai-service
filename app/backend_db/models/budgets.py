"""Budgeting models — friendly re-exports of the generated mirror."""

from app.backend_db._generated_models import BudgetAllocations as BudgetAllocation
from app.backend_db._generated_models import BudgetHistory as BudgetHistory
from app.backend_db._generated_models import Budgets as Budget

__all__ = [
    "Budget",
    "BudgetAllocation",
    "BudgetHistory",
]
