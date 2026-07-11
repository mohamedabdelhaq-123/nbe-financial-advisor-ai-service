"""US4 Integration test: Chat recommendation node wiring."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.features.chat.agents.recommendation import recommendation_node


@pytest.mark.asyncio
async def test_recommendation_node_returns_products(monkeypatch, mock_embedder):

    from app.features.recommendations.schemas import ProductMatch

    async def _mock_match(*args, **kwargs):
        return [
            ProductMatch(product_id=1, product_name="Savings Account", similarity=0.9),
            ProductMatch(product_id=2, product_name="Credit Card", similarity=0.7),
        ]

    monkeypatch.setattr("app.features.recommendations.service.match", _mock_match)

    state = {
        "messages": [HumanMessage(content="I need a savings account")],
        "user_context": {"user_id": 10},
        "intent": "recommendation",
        "stage": "recommendation",
        "planner_answers": {},
        "questions_asked": 0,
        "message_references": [],
    }

    result = await recommendation_node(state)
    assert "messages" in result
    assert len(result["messages"]) > 0
    msg = result["messages"][0]
    assert isinstance(msg, AIMessage)
    assert "product" in msg.content.lower() or "savings" in msg.content.lower()
    assert len(result["message_references"]) > 0
