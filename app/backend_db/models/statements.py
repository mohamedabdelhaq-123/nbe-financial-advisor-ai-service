"""Bank statement ingestion and transaction models — friendly re-exports of the generated mirror."""

from pgvector.sqlalchemy import VECTOR

from app.backend_db._generated_models import BankStatementTemplates as BankStatementTemplate
from app.backend_db._generated_models import StatementFiles as StatementFile
from app.backend_db._generated_models import StatementNormalized as StatementNormalized
from app.backend_db._generated_models import StatementOcrResults as StatementOcrResult
from app.backend_db._generated_models import Transactions as Transaction

_embedding_type = Transaction.__table__.c.embedding.type
assert isinstance(_embedding_type, VECTOR)
assert _embedding_type.dim is not None, "transactions.embedding must be a fixed-size vector"
TRANSACTION_EMBEDDING_DIM: int = _embedding_type.dim

__all__ = [
    "BankStatementTemplate",
    "StatementFile",
    "StatementNormalized",
    "StatementOcrResult",
    "Transaction",
    "TRANSACTION_EMBEDDING_DIM",
]
