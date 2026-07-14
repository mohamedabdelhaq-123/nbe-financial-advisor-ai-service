"""Product recommendation models — friendly re-exports of the generated mirror."""

from app.backend_db._generated_models import ProblemStatements as ProblemStatement
from app.backend_db._generated_models import Products as Product
from app.backend_db._generated_models import RecommendationLogs as RecommendationLog

PROBLEM_STATEMENT_EMBEDDING_DIM: int = ProblemStatement.__table__.c.embedding.type.dim

__all__ = [
    "Product",
    "ProblemStatement",
    "RecommendationLog",
    "PROBLEM_STATEMENT_EMBEDDING_DIM",
]
