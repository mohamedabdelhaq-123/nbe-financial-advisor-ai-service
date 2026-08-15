"""Reusable security assertions.

Phase 7's rule in practice: prefer asserting a structural/application-layer
property (a SQL WHERE clause, a message's role, a set of returned IDs) over
asserting something about natural-language wording, which is the weakest
and least reliable signal a red-team test can depend on.
"""
