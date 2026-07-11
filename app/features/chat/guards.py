"""Shared guards for agent replies — disclaimer and PII safety."""

DISCLAIMER = (
    "\n\n---\nThis is general financial guidance, not professional financial advice. "
    "Please consult a licensed financial advisor for decisions specific to your situation."
)


def with_disclaimer(text: str) -> str:
    return text + DISCLAIMER


def strip_pii(prompt: str) -> str:
    import re

    prompt = re.sub(r"\b\d{16}\b", "[CARD]", prompt)
    prompt = re.sub(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b", "[EMAIL]", prompt)
    prompt = re.sub(r"\b\d{10,}\b", "[PHONE]", prompt)
    return prompt
