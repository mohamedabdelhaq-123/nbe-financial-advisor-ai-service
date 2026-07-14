"""Product recommendation models — friendly re-exports of the generated mirror."""

from pgvector.sqlalchemy import VECTOR

from app.backend_db._generated_models import ProblemStatements as ProblemStatement
from app.backend_db._generated_models import Products as Product
from app.backend_db._generated_models import RecommendationLogs as RecommendationLog

_embedding_type = ProblemStatement.__table__.c.embedding.type
assert isinstance(_embedding_type, VECTOR)
assert _embedding_type.dim is not None, "problem_statements.embedding must be a fixed-size vector"
PROBLEM_STATEMENT_EMBEDDING_DIM: int = _embedding_type.dim

__all__ = [
    "Product",
    "ProblemStatement",
    "RecommendationLog",
    "PROBLEM_STATEMENT_EMBEDDING_DIM",
]
