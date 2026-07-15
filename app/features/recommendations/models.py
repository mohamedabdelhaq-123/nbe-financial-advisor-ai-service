"""Service-owned recommendation models (Alembic-managed).

Tables:
  - ai_problem_statements: curated need descriptions with embeddings for RAG
  - ai_recommendation_logs: records of each recommendation shown to a user
"""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Float, Integer, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import OwnBase


class AiProblemStatement(OwnBase):
    __tablename__ = "ai_problem_statements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    statement_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768), nullable=True)


class AiRecommendationLog(OwnBase):
    __tablename__ = "ai_recommendation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    matched_query: Mapped[str] = mapped_column(Text, nullable=False)
    similarity_score: Mapped[float] = mapped_column(Float, nullable=False)
    shown_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
