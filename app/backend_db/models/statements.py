"""Bank statement ingestion and transaction models — friendly re-exports of the generated mirror."""

from app.backend_db._generated_models import BankStatementTemplates as BankStatementTemplate
from app.backend_db._generated_models import StatementFiles as StatementFile
from app.backend_db._generated_models import StatementNormalized as StatementNormalized
from app.backend_db._generated_models import StatementOcrResults as StatementOcrResult
from app.backend_db._generated_models import Transactions as Transaction

TRANSACTION_EMBEDDING_DIM: int = Transaction.__table__.c.embedding.type.dim

__all__ = [
    "BankStatementTemplate",
    "StatementFile",
    "StatementNormalized",
    "StatementOcrResult",
    "Transaction",
    "TRANSACTION_EMBEDDING_DIM",
]
