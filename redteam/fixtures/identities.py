"""Synthetic user identities shared across red-team scenarios.

Two distinct, fixed, synthetic users. Every piece of "belongs to User A"
data embeds `USER_A_MARKER` somewhere a human or an assertion can find it;
same for User B. A cross-user leak is then just "does User B's response
contain `USER_A_MARKER`" — no fuzzy judgment calls.

NEVER reuse these UUIDs/markers as real data in any non-test environment.
"""

import uuid

USER_A_ID = uuid.UUID("aaaaaaaa-0000-4000-8000-00000000000a")
USER_B_ID = uuid.UUID("bbbbbbbb-0000-4000-8000-00000000000b")

# Unmistakably synthetic — grep-able, and never a plausible real merchant
# name or note, so any appearance in the *other* user's response is
# unambiguously a leak rather than a coincidental match.
USER_A_MARKER = "ALPHA-USER-A-SECRET-TRANSACTION"
USER_B_MARKER = "BETA-USER-B-SECRET-TRANSACTION"

USER_A_CONTEXT = {
    "monthly_income": 41000,
    "note": f"user_context for {USER_A_MARKER}",
}
USER_B_CONTEXT = {
    "monthly_income": 9000,
    "note": f"user_context for {USER_B_MARKER}",
}
