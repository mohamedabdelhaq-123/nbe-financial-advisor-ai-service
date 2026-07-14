"""
Domain-organized, friendly re-exports of `app.backend_db._generated_models`.

Each submodule groups the generated (sqlacodegen) model classes for one domain
and re-exports them under a cleaner alias, e.g. `administration.AdminUser` for
the generated `AdminUsers`. Application code should import from here (or a
specific domain submodule) rather than from `_generated_models` directly.
"""

from app.backend_db.models.administration import (
    AdminUser,
    AuthGroup,
    AuthPermission,
    BlacklistedToken,
    DjangoContentType,
    OutstandingToken,
    UserGroup,
    UserPermission,
)
from app.backend_db.models.aggregations import (
    MONTHLY_SUMMARY_EMBEDDING_DIM,
    AnomalyFlag,
    MonthlySummary,
    NetWorthSnapshot,
    RecurringCharge,
    SpendingPatternInsight,
)
from app.backend_db.models.budgets import Budget, BudgetAllocation, BudgetHistory
from app.backend_db.models.conversations import Conversation, Message, MessageReference
from app.backend_db.models.feedback import Reaction, ReportedIssue
from app.backend_db.models.ping import Ping
from app.backend_db.models.profile import BankAccount, ConsentRecord, User, UserPreference
from app.backend_db.models.recommendation import (
    PROBLEM_STATEMENT_EMBEDDING_DIM,
    ProblemStatement,
    Product,
    RecommendationLog,
)
from app.backend_db.models.statements import (
    TRANSACTION_EMBEDDING_DIM,
    BankStatementTemplate,
    StatementFile,
    StatementNormalized,
    StatementOcrResult,
    Transaction,
)

__all__ = [
    # administration
    "AdminUser",
    "AuthGroup",
    "AuthPermission",
    "DjangoContentType",
    "UserGroup",
    "UserPermission",
    "OutstandingToken",
    "BlacklistedToken",
    # aggregations
    "MonthlySummary",
    "SpendingPatternInsight",
    "NetWorthSnapshot",
    "RecurringCharge",
    "AnomalyFlag",
    "MONTHLY_SUMMARY_EMBEDDING_DIM",
    # budgets
    "Budget",
    "BudgetAllocation",
    "BudgetHistory",
    # conversations
    "Conversation",
    "Message",
    "MessageReference",
    # feedback
    "Reaction",
    "ReportedIssue",
    # ping
    "Ping",
    # profile
    "User",
    "UserPreference",
    "ConsentRecord",
    "BankAccount",
    # recommendation
    "Product",
    "ProblemStatement",
    "RecommendationLog",
    "PROBLEM_STATEMENT_EMBEDDING_DIM",
    # statements
    "BankStatementTemplate",
    "StatementFile",
    "StatementNormalized",
    "StatementOcrResult",
    "Transaction",
    "TRANSACTION_EMBEDDING_DIM",
]
