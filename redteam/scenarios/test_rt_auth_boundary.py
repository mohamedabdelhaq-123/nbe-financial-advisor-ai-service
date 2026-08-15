"""Unauthorized invocation via malformed/partial credentials.

Complements `tests/features/test_auth_matrix.py` (which already asserts
"every /internal/* route 401s with zero token") with a few specific
malformed-credential shapes an attacker might realistically try — not a
duplicate of that matrix.
"""

import pytest


@pytest.mark.redteam(id="RT-026", category="auth_boundary", severity="medium")
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": ""},
        {"Authorization": "not-even-bearer-shaped"},
        {"Authorization": "Bearer redteam-test-token-not-a-real-secre"},  # truncated by one char
        {"Authorization": "Bearer redteam-test-token-not-a-real-secretX"},  # one extra char
    ],
)
def test_chat_endpoint_rejects_malformed_credentials(client, headers: dict[str, str]):
    """RT-026 — malformed/partial-credential invocation attempts.

    Expected secure behavior: every shape here is rejected with 401. Note
    the truncated/extended-token cases specifically — `require_token`
    (app/core/security.py) does an exact string comparison, so an
    off-by-one token must not authenticate. (A lowercase `bearer` scheme is
    deliberately not tested here: RFC 7235 auth-schemes are case-insensitive
    and FastAPI's `HTTPBearer` correctly accepts it — that's compliant
    behavior, not a finding.)
    """
    response = client.post(
        "/internal/chat",
        json={
            "conversation_id": "c-auth-test",
            "user_id": "00000000-0000-4000-8000-0000000000aa",
            "message": "hi",
        },
        headers=headers,
    )
    assert response.status_code == 401
