"""Non-determinism sampling for real-model (`redteam_llm`) scenarios.

A single sample says little about a non-deterministic model: the same
payload can be resisted on one call and complied with on the next (this is
exactly what happened between two consecutive real runs of RT-027 in this
suite — a different payload in the same parametrized list failed each
time). Every `redteam_llm` scenario stacks a `trial` parametrize dimension
on top of its payload list (see `llm_trial_ids()`) so each attack is sent
`AI_SERVICE_REDTEAM_LLM_REPEAT` times per run, and `redteam/reporting.py`
aggregates pass/fail across all trials into a per-category attack-success
percentage — the actual statistic an AI team can act on, instead of one
anecdote per payload.

Defaults to 1 (fast/cheap default run); set
`AI_SERVICE_REDTEAM_LLM_REPEAT=N` for a proper sampling run (e.g. a nightly
CI job) — each extra repeat multiplies real provider calls (and cost/time)
by the number of `redteam_llm` payloads across all four scenarios, so raise
it deliberately, not by default.
"""

import os


def llm_repeat_count() -> int:
    try:
        n = int(os.environ.get("AI_SERVICE_REDTEAM_LLM_REPEAT", "1"))
    except ValueError:
        n = 1
    return max(1, n)


def llm_trial_ids() -> list[str]:
    """`ids=` for the `trial` parametrize dimension — stacked as a
    *separate* `@pytest.mark.parametrize("trial", range(...), ids=...)`
    decorator above the payload one, not folded into the payload's own id,
    so the nodeid stays `[payload text-trialN]`: reporting.py's
    `_TRAILING_AUTO_ID_RE` already strips exactly that `-trialN` suffix to
    recover the literal attacker input, and pytest's own duplicate-id
    disambiguation (appending a bare digit with no separator, e.g.
    `...verbatim.0`) never kicks in because the ids are unique per trial."""
    return [f"trial{i}" for i in range(llm_repeat_count())]
