"""T052 Unit test: Disclaimer and PII guards."""

from app.features.chat.guards import DISCLAIMER, strip_pii, with_disclaimer


def test_with_disclaimer_appends_text():
    result = with_disclaimer("You should save 20%.")
    assert DISCLAIMER in result
    assert "You should save 20%." in result
    assert "financial advice" in result.lower()


def test_strip_pii_removes_card():
    result = strip_pii("My card is 1234567890123456 end")
    assert "1234567890123456" not in result
    assert "[CARD]" in result


def test_strip_pii_removes_email():
    result = strip_pii("Contact user@example.com please")
    assert "user@example.com" not in result
    assert "[EMAIL]" in result


def test_strip_pii_removes_phone():
    result = strip_pii("Call me at 201234567890")
    assert "201234567890" not in result
    assert "[PHONE]" in result
