"""Planner agent — context-aware budget questionnaire (interrupt-based) and plan generation.

Two nodes form a cycle: planner_ask asks the next question (skipping/
personalizing from planner_context, assembled once by maestro_node) and
pauses on interrupt() until the user answers; validate_answer checks that
answer (deterministic for constrained kinds — enum/numeric/yes_no — with an
LLM only ever improving the rejection wording, never overriding validity;
deterministic-then-LLM for ambiguous free text) and loops back to
planner_ask either way — advancing on a valid answer, or reprompting the
same question with a reason on an invalid one, up to MAX_VALIDATION_ATTEMPTS
before falling back to a per-question default (raw text for free_text) so a
user can never get stuck. See app/features/chat/agents/maestro.py's
_planner_context_update for why context derivation lives there, not here:
interrupt() re-executes this node's own code from the top on every resume,
so anything before the interrupt() call here would otherwise re-run (and
re-hit the DB) on every single answer.
"""

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import interrupt

from app.features.chat.guards import with_disclaimer
from app.features.chat.schemas import (
    Allocation,
    AllocationSliderPayload,
    AllocationSliderWidget,
)
from app.features.chat.state import ConversationState
from app.features.plan.schemas import PlanQuestion

MAX_VALIDATION_ATTEMPTS = 3


async def planner_ask_node(state: ConversationState) -> dict:
    try:
        from app.features.plan.context import PlannerContext
        from app.features.plan.service import (
            generate_plan,
            infer_answers_from_context,
            next_question,
        )

        context: PlannerContext = state.get("planner_context") or {}  # type: ignore[assignment]
        answers = dict(state.get("planner_answers") or {})
        # Idempotent (setdefault-only) — safe to re-merge every time this
        # node runs, including on every interrupt resume.
        for topic_id, value in infer_answers_from_context(context).items():
            answers.setdefault(topic_id, value)
        # A goal stated in the message that triggered planning ("help me
        # plan for a bike") takes priority over asking savings_goal from
        # scratch — and, since it's never asked, it also never gets
        # personalized with a stale stored goal that ignores what the user
        # just said this turn.
        if state.get("stated_savings_goal"):
            answers.setdefault("savings_goal", state["stated_savings_goal"])

        questions_asked = state.get("questions_asked", 0)
        reason = state.get("pending_validation_reason")

        question = await next_question(context, answers, questions_asked)
        if question is None:
            allocations = await generate_plan(context, answers)
            alloc_lines = "\n".join(f"- {a.category}: {a.percentage}%" for a in allocations)
            reply = f"Here is your suggested budget plan:\n{alloc_lines}"
            widget = AllocationSliderWidget(
                payload=AllocationSliderPayload(
                    allocations=[
                        Allocation(category=a.category, percentage=float(a.percentage))
                        for a in allocations
                    ]
                )
            )
            return {
                "messages": [AIMessage(content=with_disclaimer(reply))],
                "planner_answers": answers,
                "last_question_id": None,
                "planner_validation_attempts": 0,
                "pending_validation_reason": None,
                "stage": "plan_complete",
                "widget": widget,
            }

        text = f"{reason} {question.text}" if reason else question.text
        raw = interrupt({"question_id": question.id, "text": text})

        # Only reached once Command(resume=raw) is supplied — everything
        # above re-runs first, per interrupt()'s documented resume semantics.
        return {
            # Command(resume=...) carries only the resume value, not a fresh
            # messages list — the user's turn has to be added explicitly.
            "messages": [HumanMessage(content=raw)],
            "planner_answers": answers,
            "pending_answer": raw,
            "last_question_id": question.id,
            "questions_asked": questions_asked + 1,
            "pending_validation_reason": None,
            "stage": "planning",
        }
    except ImportError:
        return {
            "messages": [AIMessage(content="Budget planning is being set up.")],
        }


def _hardcoded_fallback(question: PlanQuestion) -> str:
    """Safety net only — QUESTIONS below sets `default` on every constrained
    question today, so this only matters if a future question is added
    without one."""
    if question.kind == "enum":
        return (question.choices or ["unknown"])[0]
    if question.kind == "yes_no":
        return "no"
    if question.kind == "numeric":
        return str(question.min_value if question.min_value is not None else 0)
    return ""


async def validate_answer_node(state: ConversationState) -> dict:
    from app.features.plan.context import PlannerContext
    from app.features.plan.service import QUESTIONS_BY_ID, validate_answer

    last_question_id = state["last_question_id"]
    assert last_question_id is not None, "validate_answer_node reached with no pending question"
    question = QUESTIONS_BY_ID[last_question_id]
    raw = state.get("pending_answer") or ""
    answers = dict(state.get("planner_answers") or {})
    attempts = state.get("planner_validation_attempts", 0)
    context: PlannerContext = state.get("planner_context") or {}  # type: ignore[assignment]

    result = await validate_answer(question, raw, context)

    if result.valid:
        answers[question.id] = result.normalized_value
        return {
            "planner_answers": answers,
            "planner_validation_attempts": 0,
            # A stale reason from an earlier invalid attempt on THIS
            # question must not leak into the next, unrelated question's
            # prompt — planner_ask_node only clears this itself on the
            # ask-path return, which an in-progress reprompt cycle never
            # reaches (it re-hits interrupt() before getting there).
            "pending_validation_reason": None,
        }

    attempts += 1
    if attempts >= MAX_VALIDATION_ATTEMPTS:
        # Safe fallback — never trap the user in an infinite reprompt loop.
        # free_text has no fixed shape, so the raw text itself is a
        # legitimate answer, not garbage needing correction. Constrained
        # kinds (enum/numeric/yes_no) get a neutral default instead of the
        # rejected raw text, since that text failed validation for THIS
        # question's shape and would otherwise flow ungrounded into
        # generate_plan's prompt — with an acknowledgment so the user knows.
        if question.kind == "free_text":
            answers[question.id] = raw
            return {
                "planner_answers": answers,
                "planner_validation_attempts": 0,
                "pending_validation_reason": None,
            }
        fallback_value = question.default or _hardcoded_fallback(question)
        answers[question.id] = fallback_value
        ack = AIMessage(
            content=f'No worries — I\'ll assume "{fallback_value}" for now; '
            "you can adjust the plan later."
        )
        return {
            "messages": [ack],
            "planner_answers": answers,
            "planner_validation_attempts": 0,
            "pending_validation_reason": None,
        }

    return {
        "planner_validation_attempts": attempts,
        "pending_validation_reason": result.reason,
        # The reprompt doesn't count as a new question — undo the increment
        # planner_ask_node made when it originally asked this question.
        "questions_asked": state.get("questions_asked", 0) - 1,
    }
