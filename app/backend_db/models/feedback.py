"""User feedback models — friendly re-exports of the generated mirror."""

from app.backend_db._generated_models import Reactions as Reaction
from app.backend_db._generated_models import ReportedIssues as ReportedIssue

__all__ = [
    "Reaction",
    "ReportedIssue",
]
