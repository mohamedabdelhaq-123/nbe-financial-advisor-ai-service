"""US4 Integration test: Chat recommendation node wiring."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.features.chat.agents.recommendation import recommendation_node
from app.features.chat.schemas import ProductCardWidget


@pytest.mark.asyncio
async def test_recommendation_node_returns_products(monkeypatch):

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
        "widget": None,
    }

    result = await recommendation_node(state)
    assert "messages" in result
    assert len(result["messages"]) > 0
    msg = result["messages"][0]
    assert isinstance(msg, AIMessage)
    assert "product" in msg.content.lower() or "savings" in msg.content.lower()

    # FR-005: products live in the product_card widget payload, not in references.
    widget = result.get("widget")
    assert isinstance(widget, ProductCardWidget)
    assert widget.type == "product_card"
    assert len(widget.payload.products) == 2
    assert widget.payload.products[0].product_name == "Savings Account"
    assert widget.payload.products[0].product_id == "1"
    # References are empty — products are no longer duplicated as references.
    assert result["message_references"] == []
