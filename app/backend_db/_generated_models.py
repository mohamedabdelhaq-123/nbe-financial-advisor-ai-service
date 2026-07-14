"""
GENERATED FILE — DO NOT EDIT BY HAND.

Read-only mirror of backend (Django-owned) tables, generated directly from the
live read-only backend database by scripts/gen_backend_models.py (sqlacodegen).
Regenerate and commit rather than editing; see Constitution Principle IV.

These models bind to `BackendBase` (excluded from Alembic) and are never written.
"""

import datetime
import decimal
import uuid
from typing import Any, Optional

from pgvector.sqlalchemy.vector import VECTOR
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.backend_db import BackendBase


class AdminUsers(BackendBase):
    __tablename__ = "admin_users"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="admin_users_pkey"),
        UniqueConstraint("email", name="admin_users_email_key"),
        Index(
            "admin_users_email_715035b0_like",
            "email",
            postgresql_ops={"email": "varchar_pattern_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)


class AuthGroup(BackendBase):
    __tablename__ = "auth_group"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="auth_group_pkey"),
        UniqueConstraint("name", name="auth_group_name_key"),
        Index(
            "auth_group_name_a6ea08ec_like", "name", postgresql_ops={"name": "varchar_pattern_ops"}
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        Identity(start=1, increment=1, minvalue=1, maxvalue=2147483647, cycle=False, cache=1),
        primary_key=True,
        autoincrement=True,
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)

    users_groups: Mapped[list["UsersGroups"]] = relationship("UsersGroups", back_populates="group")


class BankStatementTemplates(BackendBase):
    __tablename__ = "bank_statement_templates"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="bank_statement_templates_pkey"),
        UniqueConstraint("bank_name", "layout_signature", name="unique_bank_layout_signature"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    bank_name: Mapped[str] = mapped_column(String(255), nullable=False)
    layout_signature: Mapped[str] = mapped_column(String(255), nullable=False)
    column_mapping_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    date_format: Mapped[Optional[str]] = mapped_column(String(20))

    statement_files: Mapped[list["StatementFiles"]] = relationship(
        "StatementFiles", back_populates="template"
    )


class CorePing(BackendBase):
    __tablename__ = "core_ping"
    __table_args__ = (PrimaryKeyConstraint("id", name="core_ping_pkey"),)

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(
            start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1
        ),
        primary_key=True,
        autoincrement=True,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)


class DjangoContentType(BackendBase):
    __tablename__ = "django_content_type"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="django_content_type_pkey"),
        UniqueConstraint(
            "app_label", "model", name="django_content_type_app_label_model_76bd3d3b_uniq"
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        Identity(start=1, increment=1, minvalue=1, maxvalue=2147483647, cycle=False, cache=1),
        primary_key=True,
        autoincrement=True,
    )
    app_label: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)

    auth_permission: Mapped[list["AuthPermission"]] = relationship(
        "AuthPermission", back_populates="content_type"
    )


class Products(BackendBase):
    __tablename__ = "products"
    __table_args__ = (PrimaryKeyConstraint("id", name="products_pkey"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    categories: Mapped[list[str]] = mapped_column(ARRAY(Text()), nullable=False)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text()), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    features: Mapped[Optional[dict]] = mapped_column(JSONB)
    external_link: Mapped[Optional[str]] = mapped_column(String(500))

    problem_statements: Mapped[list["ProblemStatements"]] = relationship(
        "ProblemStatements", back_populates="product"
    )
    recommendation_logs: Mapped[list["RecommendationLogs"]] = relationship(
        "RecommendationLogs", back_populates="product"
    )


class Users(BackendBase):
    __tablename__ = "users"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="users_pkey"),
        UniqueConstraint("email", name="users_email_key"),
        Index(
            "users_email_0ea73cca_like", "email", postgresql_ops={"email": "varchar_pattern_ops"}
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    dependents_count: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    is_staff: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, nullable=False)
    password: Mapped[str] = mapped_column(String(128), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(50))
    employment_status: Mapped[Optional[str]] = mapped_column(String(50))
    income_bracket: Mapped[Optional[str]] = mapped_column(String(50))
    monthly_income: Mapped[Optional[decimal.Decimal]] = mapped_column(Numeric(14, 2))
    income_steadiness: Mapped[Optional[str]] = mapped_column(String(20))
    onboarding_date: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))
    last_login: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))

    bank_accounts: Mapped[list["BankAccounts"]] = relationship(
        "BankAccounts", back_populates="user"
    )
    budgets: Mapped["Budgets"] = relationship("Budgets", uselist=False, back_populates="user")
    consent_records: Mapped[list["ConsentRecords"]] = relationship(
        "ConsentRecords", back_populates="user"
    )
    conversations: Mapped[list["Conversations"]] = relationship(
        "Conversations", back_populates="user"
    )
    goals: Mapped["Goals"] = relationship("Goals", uselist=False, back_populates="user")
    net_worth_snapshots: Mapped[list["NetWorthSnapshots"]] = relationship(
        "NetWorthSnapshots", back_populates="user"
    )
    reactions: Mapped[list["Reactions"]] = relationship("Reactions", back_populates="user")
    recommendation_logs: Mapped[list["RecommendationLogs"]] = relationship(
        "RecommendationLogs", back_populates="user"
    )
    reported_issues: Mapped[list["ReportedIssues"]] = relationship(
        "ReportedIssues", back_populates="user"
    )
    spending_pattern_insights: Mapped[list["SpendingPatternInsights"]] = relationship(
        "SpendingPatternInsights", back_populates="user"
    )
    token_blacklist_outstandingtoken: Mapped[list["TokenBlacklistOutstandingtoken"]] = relationship(
        "TokenBlacklistOutstandingtoken", back_populates="user"
    )
    user_preferences: Mapped["UserPreferences"] = relationship(
        "UserPreferences", uselist=False, back_populates="user"
    )
    users_groups: Mapped[list["UsersGroups"]] = relationship("UsersGroups", back_populates="user")
    monthly_summaries: Mapped[list["MonthlySummaries"]] = relationship(
        "MonthlySummaries", back_populates="user"
    )
    recurring_charges: Mapped[list["RecurringCharges"]] = relationship(
        "RecurringCharges", back_populates="user"
    )
    statement_files: Mapped[list["StatementFiles"]] = relationship(
        "StatementFiles", back_populates="user"
    )
    users_user_permissions: Mapped[list["UsersUserPermissions"]] = relationship(
        "UsersUserPermissions", back_populates="user"
    )
    transactions: Mapped[list["Transactions"]] = relationship("Transactions", back_populates="user")


class AuthPermission(BackendBase):
    __tablename__ = "auth_permission"
    __table_args__ = (
        ForeignKeyConstraint(
            ["content_type_id"],
            ["django_content_type.id"],
            deferrable=True,
            initially="DEFERRED",
            name="auth_permission_content_type_id_2f476e4b_fk_django_co",
        ),
        PrimaryKeyConstraint("id", name="auth_permission_pkey"),
        UniqueConstraint(
            "content_type_id",
            "codename",
            name="auth_permission_content_type_id_codename_01ab375a_uniq",
        ),
        Index("auth_permission_content_type_id_2f476e4b", "content_type_id"),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        Identity(start=1, increment=1, minvalue=1, maxvalue=2147483647, cycle=False, cache=1),
        primary_key=True,
        autoincrement=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type_id: Mapped[int] = mapped_column(Integer, nullable=False)
    codename: Mapped[str] = mapped_column(String(100), nullable=False)

    content_type: Mapped["DjangoContentType"] = relationship(
        "DjangoContentType", back_populates="auth_permission"
    )
    users_user_permissions: Mapped[list["UsersUserPermissions"]] = relationship(
        "UsersUserPermissions", back_populates="permission"
    )


class BankAccounts(BackendBase):
    __tablename__ = "bank_accounts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            deferrable=True,
            initially="DEFERRED",
            name="bank_accounts_user_id_c753e843_fk_users_id",
        ),
        PrimaryKeyConstraint("id", name="bank_accounts_pkey"),
        Index("bank_accounts_user_id_c753e843", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    bank_name: Mapped[str] = mapped_column(String(255), nullable=False)
    masked_account_number: Mapped[str] = mapped_column(String(50), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    account_type: Mapped[Optional[str]] = mapped_column(String(50))

    user: Mapped["Users"] = relationship("Users", back_populates="bank_accounts")
    monthly_summaries: Mapped[list["MonthlySummaries"]] = relationship(
        "MonthlySummaries", back_populates="account"
    )
    recurring_charges: Mapped[list["RecurringCharges"]] = relationship(
        "RecurringCharges", back_populates="account"
    )
    statement_files: Mapped[list["StatementFiles"]] = relationship(
        "StatementFiles", back_populates="account"
    )
    transactions: Mapped[list["Transactions"]] = relationship(
        "Transactions", back_populates="account"
    )


class Budgets(BackendBase):
    __tablename__ = "budgets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            deferrable=True,
            initially="DEFERRED",
            name="budgets_user_id_d4bb9f71_fk_users_id",
        ),
        PrimaryKeyConstraint("id", name="budgets_pkey"),
        UniqueConstraint("user_id", name="budgets_user_id_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    period_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    selected_template_key: Mapped[Optional[str]] = mapped_column(String(50))

    user: Mapped["Users"] = relationship("Users", back_populates="budgets")
    budget_allocations: Mapped[list["BudgetAllocations"]] = relationship(
        "BudgetAllocations", back_populates="budget"
    )
    budget_history: Mapped[list["BudgetHistory"]] = relationship(
        "BudgetHistory", back_populates="budget"
    )


class ConsentRecords(BackendBase):
    __tablename__ = "consent_records"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            deferrable=True,
            initially="DEFERRED",
            name="consent_records_user_id_84cae78d_fk_users_id",
        ),
        PrimaryKeyConstraint("id", name="consent_records_pkey"),
        Index("consent_records_user_id_84cae78d", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    consent_type: Mapped[str] = mapped_column(String(50), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    granted_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))
    revoked_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))

    user: Mapped["Users"] = relationship("Users", back_populates="consent_records")


class Conversations(BackendBase):
    __tablename__ = "conversations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            deferrable=True,
            initially="DEFERRED",
            name="conversations_user_id_e9bb86a0_fk_users_id",
        ),
        PrimaryKeyConstraint("id", name="conversations_pkey"),
        Index("conversations_user_id_e9bb86a0", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    started_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    last_message_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)

    user: Mapped["Users"] = relationship("Users", back_populates="conversations")
    messages: Mapped[list["Messages"]] = relationship("Messages", back_populates="conversation")


class Goals(BackendBase):
    __tablename__ = "goals"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            deferrable=True,
            initially="DEFERRED",
            name="goals_user_id_7678e2da_fk_users_id",
        ),
        PrimaryKeyConstraint("id", name="goals_pkey"),
        UniqueConstraint("user_id", name="goals_user_id_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    target_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    timeline_months: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)

    user: Mapped["Users"] = relationship("Users", back_populates="goals")


class NetWorthSnapshots(BackendBase):
    __tablename__ = "net_worth_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            deferrable=True,
            initially="DEFERRED",
            name="net_worth_snapshots_user_id_7455ec6d_fk_users_id",
        ),
        PrimaryKeyConstraint("id", name="net_worth_snapshots_pkey"),
        UniqueConstraint("user_id", "as_of_date", name="unique_user_net_worth_date"),
        Index("net_worth_snapshots_user_id_7455ec6d", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    as_of_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    total_across_accounts: Mapped[decimal.Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    per_account_breakdown_json: Mapped[Optional[dict]] = mapped_column(JSONB)

    user: Mapped["Users"] = relationship("Users", back_populates="net_worth_snapshots")


class ProblemStatements(BackendBase):
    __tablename__ = "problem_statements"
    __table_args__ = (
        ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            deferrable=True,
            initially="DEFERRED",
            name="problem_statements_product_id_0e8b8bc5_fk_products_id",
        ),
        PrimaryKeyConstraint("id", name="problem_statements_pkey"),
        Index(
            "idx_problem_embedding",
            "embedding",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_using="hnsw",
        ),
        Index("problem_statements_product_id_0e8b8bc5", "product_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    statement_text: Mapped[str] = mapped_column(Text, nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    embedding: Mapped[Optional[Any]] = mapped_column(VECTOR(1024))

    product: Mapped["Products"] = relationship("Products", back_populates="problem_statements")


class Reactions(BackendBase):
    __tablename__ = "reactions"
    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 5", name="chk_reaction_rating_range"),
        ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            deferrable=True,
            initially="DEFERRED",
            name="reactions_user_id_cc1df63a_fk_users_id",
        ),
        PrimaryKeyConstraint("id", name="reactions_pkey"),
        Index("idx_reactions_target", "target_type", "target_id"),
        Index("reactions_user_id_cc1df63a", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    rating: Mapped[Optional[int]] = mapped_column(SmallInteger)
    comment: Mapped[Optional[str]] = mapped_column(Text)

    user: Mapped["Users"] = relationship("Users", back_populates="reactions")


class RecommendationLogs(BackendBase):
    __tablename__ = "recommendation_logs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            deferrable=True,
            initially="DEFERRED",
            name="recommendation_logs_product_id_737c1824_fk_products_id",
        ),
        ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            deferrable=True,
            initially="DEFERRED",
            name="recommendation_logs_user_id_e3a9b6a4_fk_users_id",
        ),
        PrimaryKeyConstraint("id", name="recommendation_logs_pkey"),
        Index("idx_recommendation_logs_user", "user_id", "shown_at"),
        Index("recommendation_logs_product_id_737c1824", "product_id"),
        Index("recommendation_logs_user_id_e3a9b6a4", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    shown_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    matched_query: Mapped[Optional[str]] = mapped_column(Text)
    similarity_score: Mapped[Optional[decimal.Decimal]] = mapped_column(Numeric(5, 4))

    product: Mapped["Products"] = relationship("Products", back_populates="recommendation_logs")
    user: Mapped["Users"] = relationship("Users", back_populates="recommendation_logs")


class ReportedIssues(BackendBase):
    __tablename__ = "reported_issues"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            deferrable=True,
            initially="DEFERRED",
            name="reported_issues_user_id_64e733fd_fk_users_id",
        ),
        PrimaryKeyConstraint("id", name="reported_issues_pkey"),
        Index("reported_issues_user_id_64e733fd", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    resolved_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))

    user: Mapped["Users"] = relationship("Users", back_populates="reported_issues")


class SpendingPatternInsights(BackendBase):
    __tablename__ = "spending_pattern_insights"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            deferrable=True,
            initially="DEFERRED",
            name="spending_pattern_insights_user_id_ff560780_fk_users_id",
        ),
        PrimaryKeyConstraint("id", name="spending_pattern_insights_pkey"),
        Index("idx_user_spending_type", "user_id", "insight_type"),
        Index("spending_pattern_insights_user_id_ff560780", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    insight_type: Mapped[str] = mapped_column(String(50), nullable=False)
    value_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    period: Mapped[Optional[str]] = mapped_column(String(20))

    user: Mapped["Users"] = relationship("Users", back_populates="spending_pattern_insights")


class TokenBlacklistOutstandingtoken(BackendBase):
    __tablename__ = "token_blacklist_outstandingtoken"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            deferrable=True,
            initially="DEFERRED",
            name="token_blacklist_outstandingtoken_user_id_83bc629a_fk_users_id",
        ),
        PrimaryKeyConstraint("id", name="token_blacklist_outstandingtoken_pkey"),
        UniqueConstraint("jti", name="token_blacklist_outstandingtoken_jti_hex_d9bdf6f7_uniq"),
        Index(
            "token_blacklist_outstandingtoken_jti_hex_d9bdf6f7_like",
            "jti",
            postgresql_ops={"jti": "varchar_pattern_ops"},
        ),
        Index("token_blacklist_outstandingtoken_user_id_83bc629a", "user_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(
            start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1
        ),
        primary_key=True,
        autoincrement=True,
    )
    token: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    jti: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)

    user: Mapped[Optional["Users"]] = relationship(
        "Users", back_populates="token_blacklist_outstandingtoken"
    )
    token_blacklist_blacklistedtoken: Mapped["TokenBlacklistBlacklistedtoken"] = relationship(
        "TokenBlacklistBlacklistedtoken", uselist=False, back_populates="token"
    )


class UserPreferences(BackendBase):
    __tablename__ = "user_preferences"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            deferrable=True,
            initially="DEFERRED",
            name="user_preferences_user_id_7d5d22f7_fk_users_id",
        ),
        PrimaryKeyConstraint("id", name="user_preferences_pkey"),
        UniqueConstraint("user_id", name="user_preferences_user_id_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    language: Mapped[str] = mapped_column(String(10), nullable=False)
    currency_display_format: Mapped[str] = mapped_column(String(20), nullable=False)
    date_format: Mapped[str] = mapped_column(String(20), nullable=False)
    budget_cycle_start_day: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    default_view: Mapped[str] = mapped_column(String(20), nullable=False)
    retain_raw_documents: Mapped[bool] = mapped_column(Boolean, nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)

    user: Mapped["Users"] = relationship("Users", back_populates="user_preferences")


class UsersGroups(BackendBase):
    __tablename__ = "users_groups"
    __table_args__ = (
        ForeignKeyConstraint(
            ["group_id"],
            ["auth_group.id"],
            deferrable=True,
            initially="DEFERRED",
            name="users_groups_group_id_2f3517aa_fk_auth_group_id",
        ),
        ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            deferrable=True,
            initially="DEFERRED",
            name="users_groups_user_id_f500bee5_fk_users_id",
        ),
        PrimaryKeyConstraint("id", name="users_groups_pkey"),
        UniqueConstraint("user_id", "group_id", name="users_groups_user_id_group_id_fc7788e8_uniq"),
        Index("users_groups_group_id_2f3517aa", "group_id"),
        Index("users_groups_user_id_f500bee5", "user_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(
            start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1
        ),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    group_id: Mapped[int] = mapped_column(Integer, nullable=False)

    group: Mapped["AuthGroup"] = relationship("AuthGroup", back_populates="users_groups")
    user: Mapped["Users"] = relationship("Users", back_populates="users_groups")


class BudgetAllocations(BackendBase):
    __tablename__ = "budget_allocations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["budget_id"],
            ["budgets.id"],
            deferrable=True,
            initially="DEFERRED",
            name="budget_allocations_budget_id_a525dbd2_fk_budgets_id",
        ),
        PrimaryKeyConstraint("id", name="budget_allocations_pkey"),
        UniqueConstraint("budget_id", "category", name="unique_budget_category"),
        Index("budget_allocations_budget_id_a525dbd2", "budget_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    allocated_percentage: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    allocated_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    budget_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)

    budget: Mapped["Budgets"] = relationship("Budgets", back_populates="budget_allocations")


class BudgetHistory(BackendBase):
    __tablename__ = "budget_history"
    __table_args__ = (
        ForeignKeyConstraint(
            ["budget_id"],
            ["budgets.id"],
            deferrable=True,
            initially="DEFERRED",
            name="budget_history_budget_id_8de3f158_fk_budgets_id",
        ),
        PrimaryKeyConstraint("id", name="budget_history_pkey"),
        Index("budget_history_budget_id_8de3f158", "budget_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    previous_values: Mapped[dict] = mapped_column(JSONB, nullable=False)
    changed_via: Mapped[str] = mapped_column(String(20), nullable=False)
    changed_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    budget_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)

    budget: Mapped["Budgets"] = relationship("Budgets", back_populates="budget_history")


class Messages(BackendBase):
    __tablename__ = "messages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            deferrable=True,
            initially="DEFERRED",
            name="messages_conversation_id_5ef638db_fk_conversations_id",
        ),
        PrimaryKeyConstraint("id", name="messages_pkey"),
        Index("idx_messages_conversation", "conversation_id", "created_at"),
        Index("messages_conversation_id_5ef638db", "conversation_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    sender: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    stage: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    conversation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    widget_json: Mapped[Optional[dict]] = mapped_column(JSONB)

    conversation: Mapped["Conversations"] = relationship("Conversations", back_populates="messages")
    message_references: Mapped[list["MessageReferences"]] = relationship(
        "MessageReferences", back_populates="message"
    )


class MonthlySummaries(BackendBase):
    __tablename__ = "monthly_summaries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["account_id"],
            ["bank_accounts.id"],
            deferrable=True,
            initially="DEFERRED",
            name="monthly_summaries_account_id_4530ebab_fk_bank_accounts_id",
        ),
        ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            deferrable=True,
            initially="DEFERRED",
            name="monthly_summaries_user_id_9a827774_fk_users_id",
        ),
        PrimaryKeyConstraint("id", name="monthly_summaries_pkey"),
        UniqueConstraint("user_id", "account_id", "month", name="unique_user_month_summary"),
        Index(
            "idx_summaries_embedding",
            "embedding",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_using="hnsw",
        ),
        Index("monthly_summaries_account_id_4530ebab", "account_id"),
        Index("monthly_summaries_user_id_9a827774", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    month: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    total_spend: Mapped[Optional[decimal.Decimal]] = mapped_column(Numeric(14, 2))
    total_inflow: Mapped[Optional[decimal.Decimal]] = mapped_column(Numeric(14, 2))
    category_breakdown_json: Mapped[Optional[dict]] = mapped_column(JSONB)
    top_merchants_json: Mapped[Optional[dict]] = mapped_column(JSONB)
    embedding: Mapped[Optional[Any]] = mapped_column(VECTOR(1536))
    account_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)

    account: Mapped[Optional["BankAccounts"]] = relationship(
        "BankAccounts", back_populates="monthly_summaries"
    )
    user: Mapped["Users"] = relationship("Users", back_populates="monthly_summaries")


class RecurringCharges(BackendBase):
    __tablename__ = "recurring_charges"
    __table_args__ = (
        ForeignKeyConstraint(
            ["account_id"],
            ["bank_accounts.id"],
            deferrable=True,
            initially="DEFERRED",
            name="recurring_charges_account_id_e092b0c1_fk_bank_accounts_id",
        ),
        ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            deferrable=True,
            initially="DEFERRED",
            name="recurring_charges_user_id_b31cecda_fk_users_id",
        ),
        PrimaryKeyConstraint("id", name="recurring_charges_pkey"),
        Index("recurring_charges_account_id_e092b0c1", "account_id"),
        Index("recurring_charges_user_id_b31cecda", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    merchant_normalized: Mapped[str] = mapped_column(String(255), nullable=False)
    frequency: Mapped[str] = mapped_column(String(20), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    avg_amount: Mapped[Optional[decimal.Decimal]] = mapped_column(Numeric(14, 2))
    last_occurrence_date: Mapped[Optional[datetime.date]] = mapped_column(Date)
    next_expected_date: Mapped[Optional[datetime.date]] = mapped_column(Date)
    account_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)

    account: Mapped[Optional["BankAccounts"]] = relationship(
        "BankAccounts", back_populates="recurring_charges"
    )
    user: Mapped["Users"] = relationship("Users", back_populates="recurring_charges")


class StatementFiles(BackendBase):
    __tablename__ = "statement_files"
    __table_args__ = (
        CheckConstraint("file_size >= 0", name="statement_files_file_size_check"),
        ForeignKeyConstraint(
            ["account_id"],
            ["bank_accounts.id"],
            deferrable=True,
            initially="DEFERRED",
            name="statement_files_account_id_9f880367_fk_bank_accounts_id",
        ),
        ForeignKeyConstraint(
            ["template_id"],
            ["bank_statement_templates.id"],
            deferrable=True,
            initially="DEFERRED",
            name="statement_files_template_id_c7e66aae_fk_bank_stat",
        ),
        ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            deferrable=True,
            initially="DEFERRED",
            name="statement_files_user_id_486136e2_fk_users_id",
        ),
        PrimaryKeyConstraint("id", name="statement_files_pkey"),
        UniqueConstraint("user_id", "checksum", name="unique_user_statement_checksum"),
        Index("idx_statement_user_status", "user_id", "status"),
        Index("statement_files_account_id_9f880367", "account_id"),
        Index("statement_files_template_id_c7e66aae", "template_id"),
        Index("statement_files_user_id_486136e2", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    seaweed_file_id: Mapped[str] = mapped_column(String(255), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    upload_date: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    is_processing: Mapped[bool] = mapped_column(Boolean, nullable=False)
    start_transaction_date: Mapped[Optional[datetime.date]] = mapped_column(Date)
    last_transaction_date: Mapped[Optional[datetime.date]] = mapped_column(Date)
    account_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    template_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    failed_phase: Mapped[Optional[str]] = mapped_column(String(20))
    failure_reason: Mapped[Optional[str]] = mapped_column(Text)
    file_size: Mapped[Optional[int]] = mapped_column(BigInteger)
    file_type: Mapped[Optional[str]] = mapped_column(String(20))

    account: Mapped[Optional["BankAccounts"]] = relationship(
        "BankAccounts", back_populates="statement_files"
    )
    template: Mapped[Optional["BankStatementTemplates"]] = relationship(
        "BankStatementTemplates", back_populates="statement_files"
    )
    user: Mapped["Users"] = relationship("Users", back_populates="statement_files")
    statement_normalized: Mapped[list["StatementNormalized"]] = relationship(
        "StatementNormalized", back_populates="statement"
    )
    statement_ocr_results: Mapped[list["StatementOcrResults"]] = relationship(
        "StatementOcrResults", back_populates="statement"
    )
    transactions: Mapped[list["Transactions"]] = relationship(
        "Transactions", back_populates="statement"
    )


class TokenBlacklistBlacklistedtoken(BackendBase):
    __tablename__ = "token_blacklist_blacklistedtoken"
    __table_args__ = (
        ForeignKeyConstraint(
            ["token_id"],
            ["token_blacklist_outstandingtoken.id"],
            deferrable=True,
            initially="DEFERRED",
            name="token_blacklist_blacklistedtoken_token_id_3cc7fe56_fk",
        ),
        PrimaryKeyConstraint("id", name="token_blacklist_blacklistedtoken_pkey"),
        UniqueConstraint("token_id", name="token_blacklist_blacklistedtoken_token_id_key"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(
            start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1
        ),
        primary_key=True,
        autoincrement=True,
    )
    blacklisted_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    token_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    token: Mapped["TokenBlacklistOutstandingtoken"] = relationship(
        "TokenBlacklistOutstandingtoken", back_populates="token_blacklist_blacklistedtoken"
    )


class UsersUserPermissions(BackendBase):
    __tablename__ = "users_user_permissions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["permission_id"],
            ["auth_permission.id"],
            deferrable=True,
            initially="DEFERRED",
            name="users_user_permissio_permission_id_6d08dcd2_fk_auth_perm",
        ),
        ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            deferrable=True,
            initially="DEFERRED",
            name="users_user_permissions_user_id_92473840_fk_users_id",
        ),
        PrimaryKeyConstraint("id", name="users_user_permissions_pkey"),
        UniqueConstraint(
            "user_id",
            "permission_id",
            name="users_user_permissions_user_id_permission_id_3b86cbdf_uniq",
        ),
        Index("users_user_permissions_permission_id_6d08dcd2", "permission_id"),
        Index("users_user_permissions_user_id_92473840", "user_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(
            start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1
        ),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    permission_id: Mapped[int] = mapped_column(Integer, nullable=False)

    permission: Mapped["AuthPermission"] = relationship(
        "AuthPermission", back_populates="users_user_permissions"
    )
    user: Mapped["Users"] = relationship("Users", back_populates="users_user_permissions")


class MessageReferences(BackendBase):
    __tablename__ = "message_references"
    __table_args__ = (
        ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
            deferrable=True,
            initially="DEFERRED",
            name="message_references_message_id_3c73af41_fk_messages_id",
        ),
        PrimaryKeyConstraint("id", name="message_references_pkey"),
        Index("idx_message_references_target", "target_type", "target_id"),
        Index("message_references_message_id_3c73af41", "message_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    message_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)

    message: Mapped["Messages"] = relationship("Messages", back_populates="message_references")


class StatementNormalized(BackendBase):
    __tablename__ = "statement_normalized"
    __table_args__ = (
        ForeignKeyConstraint(
            ["statement_id"],
            ["statement_files.id"],
            deferrable=True,
            initially="DEFERRED",
            name="statement_normalized_statement_id_2aabb8b4_fk_statement",
        ),
        PrimaryKeyConstraint("id", name="statement_normalized_pkey"),
        Index("statement_normalized_statement_id_2aabb8b4", "statement_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    normalized_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    adjusted_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    statement_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    model_used: Mapped[Optional[str]] = mapped_column(String(100))

    statement: Mapped["StatementFiles"] = relationship(
        "StatementFiles", back_populates="statement_normalized"
    )


class StatementOcrResults(BackendBase):
    __tablename__ = "statement_ocr_results"
    __table_args__ = (
        ForeignKeyConstraint(
            ["statement_id"],
            ["statement_files.id"],
            deferrable=True,
            initially="DEFERRED",
            name="statement_ocr_result_statement_id_e6ef09c4_fk_statement",
        ),
        PrimaryKeyConstraint("id", name="statement_ocr_results_pkey"),
        Index("statement_ocr_results_statement_id_e6ef09c4", "statement_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    seaweed_file_id: Mapped[str] = mapped_column(String(255), nullable=False)
    ocr_engine: Mapped[str] = mapped_column(String(50), nullable=False)
    processed_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    statement_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    confidence_score: Mapped[Optional[decimal.Decimal]] = mapped_column(Numeric(4, 3))

    statement: Mapped["StatementFiles"] = relationship(
        "StatementFiles", back_populates="statement_ocr_results"
    )


class Transactions(BackendBase):
    __tablename__ = "transactions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["account_id"],
            ["bank_accounts.id"],
            deferrable=True,
            initially="DEFERRED",
            name="transactions_account_id_d92b47af_fk_bank_accounts_id",
        ),
        ForeignKeyConstraint(
            ["statement_id"],
            ["statement_files.id"],
            deferrable=True,
            initially="DEFERRED",
            name="transactions_statement_id_5529ab7a_fk_statement_files_id",
        ),
        ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            deferrable=True,
            initially="DEFERRED",
            name="transactions_user_id_766cc893_fk_users_id",
        ),
        PrimaryKeyConstraint("id", name="transactions_pkey"),
        UniqueConstraint(
            "user_id",
            "account_id",
            "transaction_date",
            "amount",
            "merchant_raw",
            name="unique_ledger_transaction_match",
        ),
        Index("idx_transactions_account", "account_id"),
        Index(
            "idx_transactions_embedding",
            "embedding",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_using="hnsw",
        ),
        Index("idx_transactions_user_category", "user_id", "category"),
        Index("idx_transactions_user_date", "user_id", "transaction_date"),
        Index("transactions_account_id_d92b47af", "account_id"),
        Index("transactions_statement_id_5529ab7a", "statement_id"),
        Index("transactions_user_id_766cc893", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    transaction_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    amount: Mapped[decimal.Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    is_recurring: Mapped[bool] = mapped_column(Boolean, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    merchant_raw: Mapped[Optional[str]] = mapped_column(String(500))
    merchant_normalized: Mapped[Optional[str]] = mapped_column(String(255))
    category: Mapped[Optional[str]] = mapped_column(String(100))
    confidence_score: Mapped[Optional[decimal.Decimal]] = mapped_column(Numeric(4, 3))
    balance: Mapped[Optional[decimal.Decimal]] = mapped_column(Numeric(14, 2))
    transaction_type: Mapped[Optional[str]] = mapped_column(String(20))
    extra_fields: Mapped[Optional[dict]] = mapped_column(JSONB)
    embedding: Mapped[Optional[Any]] = mapped_column(VECTOR(1536))
    statement_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)

    account: Mapped["BankAccounts"] = relationship("BankAccounts", back_populates="transactions")
    statement: Mapped[Optional["StatementFiles"]] = relationship(
        "StatementFiles", back_populates="transactions"
    )
    user: Mapped["Users"] = relationship("Users", back_populates="transactions")
    anomaly_flags: Mapped[list["AnomalyFlags"]] = relationship(
        "AnomalyFlags", back_populates="transaction"
    )


class AnomalyFlags(BackendBase):
    __tablename__ = "anomaly_flags"
    __table_args__ = (
        ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
            deferrable=True,
            initially="DEFERRED",
            name="anomaly_flags_transaction_id_c2714b47_fk_transactions_id",
        ),
        PrimaryKeyConstraint("id", name="anomaly_flags_pkey"),
        Index("anomaly_flags_transaction_id_c2714b47", "transaction_id"),
        Index("idx_anomaly_flags_severity", "severity", "resolved"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False)
    detected_at: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    transaction_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)

    transaction: Mapped["Transactions"] = relationship(
        "Transactions", back_populates="anomaly_flags"
    )
