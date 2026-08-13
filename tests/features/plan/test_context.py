"""Unit tests for app.features.plan.context.derive_planner_context.

derive_planner_context calls compute_aggregate twice, in order: income
(group_by=month) first, then recurring expense (group_by=month) second.
The fake backend session below returns canned rows keyed off that call
order, since the mocked session.execute doesn't actually filter by the
compiled statement.
"""

import datetime
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.features.plan.context import derive_planner_context


def _make_fake_session(income_rows: list[tuple], recurring_rows: list[tuple]):
    call_count = {"n": 0}

    async def _fake_get_backend_session():
        async def _execute(stmt):
            call_count["n"] += 1
            result = MagicMock()
            rows = income_rows if call_count["n"] == 1 else recurring_rows
            # compute_aggregate's group_by="month" query selects
            # (currency, month, value) — real Postgres date_trunc() returns
            # a date/datetime, not a string, so the month dimension here
            # must match that shape.
            result.all.return_value = [("EGP", month, value) for month, value in rows]
            return result

        session = MagicMock()
        session.execute = _execute
        yield session

    return _fake_get_backend_session


def _d(month_str: str) -> datetime.date:
    year, month = month_str.split("-")
    return datetime.date(int(year), int(month), 1)


@pytest.mark.asyncio
async def test_low_variance_income(monkeypatch):
    monkeypatch.setattr(
        "app.backend_db.get_backend_session",
        _make_fake_session(
            income_rows=[(_d("2026-05"), 5000.0), (_d("2026-06"), 5050.0), (_d("2026-07"), 4980.0)],
            recurring_rows=[],
        ),
    )
    context = await derive_planner_context(uuid.uuid4())
    assert context["months_of_income_data"] == 3
    assert context["income_variance_ratio"] is not None
    assert context["income_variance_ratio"] < 0.10


@pytest.mark.asyncio
async def test_high_variance_income(monkeypatch):
    monkeypatch.setattr(
        "app.backend_db.get_backend_session",
        _make_fake_session(
            income_rows=[(_d("2026-05"), 2000.0), (_d("2026-06"), 9000.0), (_d("2026-07"), 3000.0)],
            recurring_rows=[],
        ),
    )
    context = await derive_planner_context(uuid.uuid4())
    assert context["income_variance_ratio"] is not None
    assert context["income_variance_ratio"] > 0.35


@pytest.mark.asyncio
async def test_single_month_has_no_variance_signal(monkeypatch):
    monkeypatch.setattr(
        "app.backend_db.get_backend_session",
        _make_fake_session(income_rows=[(_d("2026-07"), 5000.0)], recurring_rows=[]),
    )
    context = await derive_planner_context(uuid.uuid4())
    assert context["months_of_income_data"] == 1
    assert context["income_variance_ratio"] is None
    assert context["avg_monthly_income"] == 5000.0


@pytest.mark.asyncio
async def test_zero_transactions_returns_neutral_context(monkeypatch):
    monkeypatch.setattr(
        "app.backend_db.get_backend_session",
        _make_fake_session(income_rows=[], recurring_rows=[]),
    )
    context = await derive_planner_context(uuid.uuid4())
    assert context["avg_monthly_income"] is None
    assert context["income_variance_ratio"] is None
    assert context["months_of_income_data"] == 0
    assert context["avg_monthly_recurring_expense"] is None


@pytest.mark.asyncio
async def test_backend_unavailable_returns_neutral_context_without_raising(monkeypatch):
    async def _raising_get_backend_session():
        raise RuntimeError("simulated backend outage")
        yield  # pragma: no cover - unreachable, keeps this an async generator

    monkeypatch.setattr("app.backend_db.get_backend_session", _raising_get_backend_session)

    context = await derive_planner_context(uuid.uuid4())
    assert context["avg_monthly_income"] is None
    assert context["months_of_income_data"] == 0


# --- profile/goal signal (dependents_count, savings_goal_*) ----------------


def _make_fake_profile_session(
    income_rows: list[tuple] | None = None,
    user_row=None,
    goal_row=None,
    get_raises: bool = False,
):
    call_count = {"n": 0}

    async def _fake_get_backend_session():
        async def _execute(stmt):
            call_count["n"] += 1
            result = MagicMock()
            if call_count["n"] <= 2:
                # 1st call = income aggregate, 2nd = recurring-expense aggregate.
                rows = (income_rows or []) if call_count["n"] == 1 else []
                result.all.return_value = [("EGP", month, value) for month, value in rows]
            else:
                # 3rd call = the Goal lookup in _derive_profile_signal.
                result.scalar_one_or_none.return_value = goal_row
            return result

        async def _get(model, pk):
            if get_raises:
                raise RuntimeError("simulated DB error fetching User")
            return user_row

        session = MagicMock()
        session.execute = _execute
        session.get = _get
        yield session

    return _fake_get_backend_session


@pytest.mark.asyncio
async def test_onboarding_completed_and_goal_set_populate_both(monkeypatch):
    user_row = SimpleNamespace(onboarding_date=datetime.datetime(2026, 1, 1), dependents_count=2)
    goal_row = SimpleNamespace(name="a bike", target_amount=5000, timeline_months=6)
    monkeypatch.setattr(
        "app.backend_db.get_backend_session",
        _make_fake_profile_session(user_row=user_row, goal_row=goal_row),
    )
    context = await derive_planner_context(uuid.uuid4())
    assert context["dependents_count"] == 2
    assert context["savings_goal_name"] == "a bike"
    assert context["savings_goal_target_amount"] == 5000.0
    assert context["savings_goal_timeline_months"] == 6


@pytest.mark.asyncio
async def test_onboarding_not_completed_ignores_dependents_default(monkeypatch):
    # dependents_count defaults to 0 in the DB regardless of whether the
    # user ever touched this onboarding step — onboarding_date is None
    # here specifically to simulate that, and the 0 must NOT be trusted.
    user_row = SimpleNamespace(onboarding_date=None, dependents_count=0)
    monkeypatch.setattr(
        "app.backend_db.get_backend_session",
        _make_fake_profile_session(user_row=user_row, goal_row=None),
    )
    context = await derive_planner_context(uuid.uuid4())
    assert context["dependents_count"] is None


@pytest.mark.asyncio
async def test_no_goal_row_leaves_savings_goal_fields_none(monkeypatch):
    user_row = SimpleNamespace(onboarding_date=datetime.datetime(2026, 1, 1), dependents_count=1)
    monkeypatch.setattr(
        "app.backend_db.get_backend_session",
        _make_fake_profile_session(user_row=user_row, goal_row=None),
    )
    context = await derive_planner_context(uuid.uuid4())
    assert context["dependents_count"] == 1
    assert context["savings_goal_name"] is None
    assert context["savings_goal_target_amount"] is None
    assert context["savings_goal_timeline_months"] is None


@pytest.mark.asyncio
async def test_profile_lookup_failure_does_not_blank_out_income_signal(monkeypatch):
    # Independence check: the income try/except and the profile try/except
    # are separate — a failure in one must not wipe out a result the other
    # already derived successfully.
    monkeypatch.setattr(
        "app.backend_db.get_backend_session",
        _make_fake_profile_session(
            income_rows=[(_d("2026-05"), 5000.0), (_d("2026-06"), 5050.0)],
            get_raises=True,
        ),
    )
    context = await derive_planner_context(uuid.uuid4())
    assert context["avg_monthly_income"] is not None
    assert context["months_of_income_data"] == 2
    assert context["dependents_count"] is None
    assert context["savings_goal_name"] is None
