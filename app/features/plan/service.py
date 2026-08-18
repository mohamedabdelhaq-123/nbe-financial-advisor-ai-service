"""Budget planning service — question generation, answer validation, and plan creation."""

import re
from decimal import Decimal

from app.core.config import settings
from app.core.logging import get_logger
from app.features.plan.context import PlannerContext
from app.features.plan.schemas import AnswerValidation, BudgetAllocation, PlanQuestion

logger = get_logger(__name__)

MAX_QUESTIONS = 7

QUESTIONS = [
    PlanQuestion(
        id="income_stability",
        text="Is your monthly income consistent or variable?",
        kind="enum",
        choices=["consistent", "variable"],
        default="variable",
    ),
    PlanQuestion(
        id="fixed_expenses",
        text="What are your fixed monthly obligations (rent, loans, subscriptions)?",
        kind="free_text",
    ),
    PlanQuestion(
        id="savings_goal",
        text="Do you have a specific savings goal or target amount?",
        kind="free_text",
    ),
    PlanQuestion(
        id="dependents",
        text="How many dependents do you financially support?",
        kind="numeric",
        min_value=0,
        max_value=20,
        default="0",
    ),
    PlanQuestion(
        id="risk_tolerance",
        text="How comfortable are you with financial risk (low/medium/high)?",
        kind="enum",
        choices=["low", "medium", "high"],
        default="medium",
    ),
    PlanQuestion(
        id="debt",
        text="Do you have any outstanding debts beyond fixed obligations?",
        kind="yes_no",
        default="no",
    ),
    PlanQuestion(
        id="lifestyle",
        text="How would you describe your spending lifestyle (frugal/moderate/generous)?",
        kind="enum",
        choices=["frugal", "moderate", "generous"],
        default="moderate",
    ),
]

QUESTIONS_BY_ID: dict[str, PlanQuestion] = {q.id: q for q in QUESTIONS}

# Income coefficient-of-variation thresholds used to (conservatively) infer
# income_stability from real transaction data instead of asking. Starting
# points, not calibrated against real usage yet — see plan notes.
_INCOME_CV_CONSISTENT = 0.10
_INCOME_CV_VARIABLE = 0.35

_YES_WORDS = {"yes", "y", "yeah", "yep", "sure", "definitely"}
_NO_WORDS = {"no", "n", "nope", "not really", "none"}


def _personalize(question: PlanQuestion, context: PlannerContext) -> PlanQuestion:
    """Deterministic (no LLM) question-text rewriting from real per-user
    signal. F-string templates, not an LLM call — the configured free model
    has already proven unreliable at strict structured output this session,
    and this is user-facing numeric phrasing, not worth that risk for a
    cosmetic enhancement."""
    currency = context.get("currency") or ""

    if question.id == "income_stability" and context.get("avg_monthly_income") is not None:
        text = (
            f"I can see your average monthly income is around "
            f"{context['avg_monthly_income']:.0f} {currency}. Does that feel consistent "
            f"month to month, or does it vary a lot?"
        )
        return question.model_copy(update={"text": text})

    if question.id == "fixed_expenses" and context.get("avg_monthly_recurring_expense"):
        text = (
            f"I can see roughly {context['avg_monthly_recurring_expense']:.0f} {currency}/month "
            f"in recurring charges. What are your fixed monthly obligations (rent, loans, "
            f"subscriptions)?"
        )
        return question.model_copy(update={"text": text})

    if question.id == "dependents" and context.get("dependents_count") is not None:
        text = (
            f"I have you down for {context['dependents_count']} dependents from your "
            f"profile — is that still accurate?"
        )
        return question.model_copy(update={"text": text})

    if question.id == "savings_goal" and context.get("savings_goal_name"):
        goal_desc = _format_goal(context)
        text = (
            f"I see you set a goal of saving for '{goal_desc}' — is that still your "
            f"goal, or has it changed?"
        )
        return question.model_copy(update={"text": text})

    return question


def _format_goal(context: PlannerContext) -> str | None:
    name = context.get("savings_goal_name")
    if not name:
        return None
    parts = [name]
    if context.get("savings_goal_target_amount"):
        amount = f"{context['savings_goal_target_amount']:.0f}"
        if context.get("currency"):
            amount += f" {context['currency']}"
        parts.append(amount)
    if context.get("savings_goal_timeline_months"):
        parts.append(f"within {context['savings_goal_timeline_months']} months")
    return ", ".join(parts)


_CONFIRMABLE_CONTEXT_FIELDS = {
    "dependents": lambda ctx: (
        str(ctx["dependents_count"]) if ctx.get("dependents_count") is not None else None
    ),
    "savings_goal": _format_goal,
}


def resolve_confirmation(
    question_id: str, raw: str, context: PlannerContext
) -> AnswerValidation | None:
    """If `raw` is a bare confirmation word ('yes') and this question was
    personalized from a known context value, resolve directly to that
    value instead of running kind-specific validation. Without this, a bare
    "yes" confirming a personalized `dependents` question would get
    rejected outright by the numeric validator (no digits in "yes"), and a
    "yes" confirming `savings_goal` would store the literal word "yes"
    instead of the actual goal description.

    A correction ("actually 3 now", "no, saving for a car instead") is not
    a bare yes-word, so it isn't intercepted here — it falls through to
    normal kind-specific validation unchanged."""
    resolver = _CONFIRMABLE_CONTEXT_FIELDS.get(question_id)
    if resolver is None or raw.strip().lower() not in _YES_WORDS:
        return None
    resolved = resolver(context)
    return AnswerValidation(valid=True, normalized_value=resolved) if resolved is not None else None


def infer_answers_from_context(context: PlannerContext) -> dict[str, str]:
    """Deterministic, rule-based auto-fill for topics confidently answerable
    from real transaction signals. Only ever returns entries for topics with
    a *clear* signal — ambiguous cases are omitted so the topic still gets
    asked normally.

    Only income_stability is ever silently skipped. fixed_expenses gets
    personalized wording only (see _personalize), never a silent skip — a
    wrong number silently baked into a budget-plan input is worse than one
    extra question. This is a deliberate policy difference, not an
    oversight.
    """
    inferred: dict[str, str] = {}
    cv = context.get("income_variance_ratio")
    if cv is not None:
        if cv < _INCOME_CV_CONSISTENT:
            inferred["income_stability"] = "consistent"
        elif cv > _INCOME_CV_VARIABLE:
            inferred["income_stability"] = "variable"
    return inferred


async def next_question(
    context: PlannerContext,
    answers: dict,
    questions_asked: int,
) -> PlanQuestion | None:
    if questions_asked >= MAX_QUESTIONS:
        return None

    answered = set(answers.keys())
    for q in QUESTIONS:
        if q.id not in answered:
            return _personalize(q, context)
    return None


# A closed set of question-starter markers — same style as scope_guard.py's
# _CAPABILITY_PHRASES: small, curated, deterministic, not an attempt to
# detect every possible question.
_QUESTION_MARKERS = (
    "what",
    "why",
    "how",
    "who",
    "which",
    "when",
    "where",
    "do you",
    "does it",
    "is it",
    "are you",
    "can you",
    "could you",
    "would you",
)


def _looks_like_a_question(text: str) -> bool:
    """A reply containing a choice word is still not an answer if it's
    asking about that word rather than selecting it — "what does frugal
    even mean" contains "frugal" as an ordinary substring/word, which the
    enum matcher below would otherwise happily accept as a selection of
    "frugal". Regression coverage for a real bug: this exact reply silently
    completed the questionnaire with a lifestyle the user never chose."""
    stripped = text.strip().lower()
    if stripped.endswith("?"):
        return True
    return any(stripped.startswith(marker) for marker in _QUESTION_MARKERS)


def validate_answer_deterministic(question: PlanQuestion, raw: str) -> AnswerValidation | None:
    """Returns a verdict for every kind except an inconclusive `free_text`
    answer, where `None` signals the caller to fall back to an LLM check.
    numeric/enum/yes_no are always fully deterministic — never ambiguous,
    never need the LLM."""
    text = raw.strip()

    if question.kind == "yes_no":
        low = text.lower()
        if low in _YES_WORDS:
            return AnswerValidation(valid=True, normalized_value="yes")
        if low in _NO_WORDS:
            return AnswerValidation(valid=True, normalized_value="no")
        return AnswerValidation(valid=False, reason="Please answer yes or no.")

    if question.kind == "enum":
        low = text.lower()
        if not _looks_like_a_question(text):
            for choice in question.choices or []:
                if choice in low or low in choice:
                    return AnswerValidation(valid=True, normalized_value=choice)
        return AnswerValidation(
            valid=False,
            reason=f"Please choose one of: {', '.join(question.choices or [])}.",
        )

    if question.kind == "numeric":
        match = re.search(r"-?[\d,]+(?:\.\d+)?", text)
        if not match:
            return AnswerValidation(valid=False, reason="Please answer with a number.")
        value = float(match.group().replace(",", ""))
        if question.min_value is not None and value < question.min_value:
            return AnswerValidation(
                valid=False,
                reason=f"Please enter a number of at least {question.min_value:g}.",
            )
        if question.max_value is not None and value > question.max_value:
            return AnswerValidation(
                valid=False,
                reason=f"Please enter a number no more than {question.max_value:g}.",
            )
        return AnswerValidation(valid=True, normalized_value=str(value))

    # free_text: only a truly degenerate answer (empty, no real content at
    # all) is deterministically rejected. Length alone is not a usable proxy
    # for "is this a real answer" — "what do you mean?" is 19 characters and
    # full of real words, but it's a question back, not an answer. Every
    # non-degenerate free_text reply defers to the LLM, which actually
    # judges intent rather than just checking length.
    if len(text) < 2 or not any(c.isalnum() for c in text):
        return AnswerValidation(valid=False, reason="Could you say a bit more?")
    return None


async def validate_answer_llm(question: PlanQuestion, raw: str) -> AnswerValidation:
    """Only called when validate_answer_deterministic returns None (an
    ambiguous free_text answer). Parses the small model's reply the same
    defensive way maestro.py's _parse_llm_intent does — an unparseable
    reply is treated as valid rather than reprompting forever on a model
    hiccup."""
    if settings.chat_model.use_mock:
        return AnswerValidation(valid=True, normalized_value=raw.strip())

    from langchain_core.messages import HumanMessage, SystemMessage

    from app.core.llm import get_chat_model
    from app.features.plan.prompts import (
        get_answer_validation_prompt,
        get_answer_validation_system_prompt,
    )

    system_prompt = get_answer_validation_system_prompt().render()
    prompt = get_answer_validation_prompt().render(question_text=question.text, raw=raw)
    try:
        result = await get_chat_model().ainvoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=prompt)]
        )
        content = result.content if isinstance(result.content, str) else str(result.content)
    except Exception:
        logger.exception("validate_answer_llm_failed", question_id=question.id)
        return AnswerValidation(valid=True, normalized_value=raw.strip())

    cleaned = content.strip().strip(".!?\"'").lower()
    if cleaned.startswith("valid"):
        return AnswerValidation(valid=True, normalized_value=raw.strip())
    if cleaned.startswith("invalid"):
        reason = content.split(":", 1)[1].strip() if ":" in content else "Could you rephrase that?"
        return AnswerValidation(valid=False, reason=reason)

    logger.warning("validate_answer_llm_unparsed", raw=content, question_id=question.id)
    return AnswerValidation(valid=True, normalized_value=raw.strip())


async def validate_answer(
    question: PlanQuestion, raw: str, context: PlannerContext
) -> AnswerValidation:
    """Combines resolve_confirmation + validate_answer_deterministic +, for a
    rejected constrained (non-free_text) answer in real (non-mock) mode, an
    LLM call purely to improve the rejection wording — never to override
    validity. Constrained kinds (enum/numeric/yes_no) remain fully
    deterministic for accept/reject (e.g. "kinda risky I guess" for
    risk_tolerance is always rejected, never LLM-coerced onto a choice);
    only the user-facing reason text for a rejection can come from the LLM,
    which already knows how to tell a clarifying question ("what do you
    mean?") apart from plain gibberish (see validate_answer_system.jinja2)
    but was previously only ever invoked for free_text answers."""
    result = resolve_confirmation(question.id, raw, context)
    if result is not None:
        return result

    result = validate_answer_deterministic(question, raw)
    if result is None:
        return await validate_answer_llm(question, raw)  # free_text ambiguous case, unchanged

    if result.valid or settings.chat_model.use_mock:
        return result

    try:
        llm_opinion = await validate_answer_llm(question, raw)
    except Exception:
        logger.exception("validate_answer_reason_enrichment_failed", question_id=question.id)
        return result
    if not llm_opinion.valid and llm_opinion.reason:
        return AnswerValidation(valid=False, reason=llm_opinion.reason)
    return result  # LLM disagreed, errored, or gave no reason — keep deterministic verdict


async def extract_stated_goal(message: str) -> str | None:
    """Checks whether the message that triggered planning already states a
    savings goal (e.g. "help me plan for a bike"), so planner_ask_node can
    skip asking savings_goal from scratch — and, just as importantly, skip
    personalizing it with a stale stored goal that ignores what the user
    just said this turn. Mock mode never calls the real LLM, matching
    validate_answer_llm's offline-deterministic behavior — this feature is
    simply inert (no extraction) in mock mode/tests."""
    if settings.chat_model.use_mock:
        return None

    from langchain_core.messages import HumanMessage, SystemMessage

    from app.core.llm import get_chat_model
    from app.features.plan.prompts import get_goal_extraction_system_prompt

    system_prompt = get_goal_extraction_system_prompt().render()
    try:
        result = await get_chat_model().ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=message),
            ]
        )
        content = result.content if isinstance(result.content, str) else str(result.content)
    except Exception:
        logger.exception("extract_stated_goal_failed")
        return None

    cleaned = content.strip().strip(".!?\"'")
    return None if not cleaned or cleaned.lower() == "none" else cleaned


async def generate_plan(
    context: PlannerContext,
    answers: dict,
) -> list[BudgetAllocation]:
    if settings.chat_model.use_mock:
        return _mock_plan(answers)

    from langchain_core.messages import HumanMessage, SystemMessage
    from sqlalchemy import select

    from app.backend_db import get_backend_session
    from app.backend_db.models import Category
    from app.core.llm import get_chat_model
    from app.features.plan.prompts import (
        get_budget_allocation_prompt,
        get_budget_allocation_system_prompt,
    )

    # The confirming Django endpoint (PATCH /budget -> AllocationInputSerializer)
    # validates `category` against real backend Category rows by exact name, not
    # free text (SlugRelatedField, filtered to category_type="expense") — so the
    # prompt is built from the live table instead of a hardcoded list that could
    # drift from it, and _parse_and_normalize snaps the LLM's output onto it too.
    async for backend_session in get_backend_session():
        known_categories = (
            (
                await backend_session.execute(
                    select(Category.name).where(Category.category_type == "expense")
                )
            )
            .scalars()
            .all()
        )

        llm = get_chat_model()
        example_categories = ", ".join(f"{c!r}: 10" for c in known_categories)
        system_prompt = get_budget_allocation_system_prompt().render(
            known_categories=known_categories,
            example_categories=example_categories,
        )
        prompt = get_budget_allocation_prompt().render(
            avg_monthly_income=context.get("avg_monthly_income"),
            avg_monthly_recurring_expense=context.get("avg_monthly_recurring_expense"),
            savings_goal_name=context.get("savings_goal_name"),
            savings_goal_target_amount=context.get("savings_goal_target_amount"),
            savings_goal_timeline_months=context.get("savings_goal_timeline_months"),
            savings_goal_answer=answers.get("savings_goal"),
            answers=answers,
        )
        response = await llm.ainvoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=prompt)]
        )
        raw = str(response.content).strip()

        return await _parse_and_normalize(raw, backend_session)

    # get_backend_session always yields exactly one session; unreachable.
    return _mock_plan(answers)


def _mock_plan(answers: dict) -> list[BudgetAllocation]:
    savings_pct = 20
    if answers.get("savings_goal", "").lower() in ("yes", "aggressive"):
        savings_pct = 30
    elif answers.get("dependents", ""):
        savings_pct = 15

    housing = 30
    if answers.get("fixed_expenses", ""):
        housing = 35

    remaining = 100 - savings_pct - housing

    # "utilities" and "entertainment" aren't real category names in the
    # backend's `categories` table (only their bucket-mates "housing" and
    # "lifestyle" are — see core/models/categories/resolution.py's alias map
    # on the Django side), so those points are folded straight into the
    # buckets they'd alias to rather than kept as their own line.
    allocations = [
        BudgetAllocation(category="housing", percentage=Decimal(str(housing + 5))),
        BudgetAllocation(category="food", percentage=Decimal("15")),
        BudgetAllocation(category="transport", percentage=Decimal("10")),
        BudgetAllocation(category="savings", percentage=Decimal(str(savings_pct))),
        BudgetAllocation(category="other", percentage=Decimal("5")),
    ]

    leftover = remaining - 15 - 10 - 5
    if leftover > 0:
        allocations.append(
            BudgetAllocation(category="lifestyle", percentage=Decimal(str(leftover)))
        )

    total = sum(a.percentage for a in allocations)
    if total != 100:
        diff = Decimal("100") - total
        allocations[0] = BudgetAllocation(
            category=allocations[0].category,
            percentage=allocations[0].percentage + diff,
        )

    total = sum(a.percentage for a in allocations)
    assert total == 100, f"Mock plan must sum to 100, got {total}"
    return allocations


async def _parse_and_normalize(raw: str, backend_session) -> list[BudgetAllocation]:
    import json

    from app.features.ingestion.categories import resolve_category

    json_match = re.search(r"\{[^}]+\}", raw)
    if not json_match:
        return _mock_plan({})

    try:
        data = json.loads(json_match.group())
    except json.JSONDecodeError:
        return _mock_plan({})

    # Snap each LLM-produced name onto the backend's real category vocabulary
    # (case-insensitive exact match, falling back to the expense "other"
    # bucket) — the LLM is prompted with the known names but isn't guaranteed
    # to stick to them, and a name the backend doesn't recognise 400s the
    # budget PATCH downstream. Two raw names resolving to the same bucket
    # (e.g. both falling back to "other") are merged rather than kept as
    # separate lines with the same category.
    merged: dict[str, Decimal] = {}
    order: list[str] = []
    for category, pct in data.items():
        try:
            percentage = Decimal(str(int(pct)))
        except (ValueError, TypeError):
            return _mock_plan({})
        resolved = await resolve_category(backend_session, str(category))
        if resolved not in merged:
            order.append(resolved)
            merged[resolved] = Decimal("0")
        merged[resolved] += percentage

    allocations = [BudgetAllocation(category=name, percentage=merged[name]) for name in order]

    total = sum(a.percentage for a in allocations)
    if total != 100:
        diff = Decimal("100") - total
        if allocations:
            allocations[0] = BudgetAllocation(
                category=allocations[0].category,
                percentage=allocations[0].percentage + diff,
            )

    final_total = sum(a.percentage for a in allocations)
    assert final_total == 100, f"Plan must sum to 100, got {final_total}"
    return allocations
