"""User profile and account models — friendly re-exports of the generated mirror."""

from app.backend_db._generated_models import BankAccounts as BankAccount
from app.backend_db._generated_models import ConsentRecords as ConsentRecord
from app.backend_db._generated_models import UserPreferences as UserPreference
from app.backend_db._generated_models import Users as User

__all__ = [
    "User",
    "UserPreference",
    "ConsentRecord",
    "BankAccount",
]
