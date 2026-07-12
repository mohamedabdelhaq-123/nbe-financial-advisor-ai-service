"""Planner agent — budget questionnaire and plan generation."""

from langchain_core.messages import AIMessage

from app.features.chat.guards import with_disclaimer
from app.features.chat.state import ConversationState


async def planner_node(state: ConversationState) -> dict:
    try:
        from app.features.plan.service import generate_plan, next_question

        user_context = state["user_context"]
        answers = state["planner_answers"]
        questions_asked = state["questions_asked"]

        question = await next_question(user_context, answers, questions_asked)
        if question is not None:
            new_count = questions_asked + 1
            return {
                "messages": [AIMessage(content=question.text)],
                "questions_asked": new_count,
            }

        allocations = await generate_plan(user_context, answers)
        alloc_lines = "\n".join(f"- {a.category}: {a.percentage}%" for a in allocations)
        reply = f"Here is your suggested budget plan:\n{alloc_lines}"
        return {
            "messages": [AIMessage(content=with_disclaimer(reply))],
            "stage": "plan_complete",
        }
    except ImportError:
        return {
            "messages": [AIMessage(content="Budget planning is being set up.")],
        }
