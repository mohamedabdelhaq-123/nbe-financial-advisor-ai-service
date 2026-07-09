"""
Hand-written, read-only typed models for backend-owned tables.

These mirror only the columns this service needs from specific Django-owned
tables. They inherit from `BackendBase` (excluded from Alembic) and are never
written to.

No concrete models are defined yet — each is added when a feature spec names the
backend table(s) it reads. A schema-drift check (integration test) will be added
alongside the first concrete model to flag divergence from the real backend
schema.
"""
