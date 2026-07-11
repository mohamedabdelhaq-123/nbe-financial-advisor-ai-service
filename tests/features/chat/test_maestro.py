"""US1 Unit test: Maestro intent classification (mock mode)."""

import pytest

from app.features.chat.agents.maestro import classify_intent


@pytest.mark.parametrize(
    "message,expected",
    [
        ("how much did I spend on food last month", "analysis"),
        ("show me my transactions", "analysis"),
        ("what were my expenses", "analysis"),
        ("help me budget for next month", "planning"),
        ("I want to plan my spending", "planning"),
        ("create a budget for me", "planning"),
        ("which credit card should I get", "recommendation"),
        ("what savings account is best", "recommendation"),
        ("recommend a product for me", "recommendation"),
        ("hello there", "general"),
        ("what can you do", "general"),
        ("thank you", "general"),
    ],
)
def test_classify_intent(message: str, expected: str):
    result = classify_intent(message)
    assert result == expected
