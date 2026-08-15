"""Renders the red-team suite's results as a Markdown findings file.

Kept separate from `conftest.py` (which only wires the pytest hooks) so the
rendering logic is independently testable/readable. The file this writes
(`redteam/reports/FINDINGS.md` by default) is fully regenerated on every
run — an upsert of "the current findings," not an append-only log. Point a
diffing/history tool at git if you need change-over-time instead.

Design goal (why this file looks the way it does): a security reviewer must
be able to understand one finding — what was attacked, with what exact
input, what the LLM (if any) was actually asked and actually said, why it's
a security problem, and how to fix it — without ever reading a pytest
AssertionError. Every failed finding is rendered with those as separate,
explicitly labeled fields, never folded into one blob of assertion text.
Grouped by RT ID rather than one write-up per parametrized case: a scenario
attacked with 17 jailbreak payloads shares one root cause, one "why", one
fix — only the per-case raw evidence (input/prompt/output) actually differs,
so that's the only part repeated per case.
"""

from __future__ import annotations

import datetime as _dt
import inspect
import os
import re
from dataclasses import dataclass, field
from typing import NamedTuple

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

# Every scenario's docstring is written in this labeled-section convention
# (Phase 5 of the framework brief: preconditions / attack input / expected
# secure behavior). Parsed structurally here rather than just taking the
# first line, so the report can show "what was the input" and "what was
# expected" as their own fields, not folded into one summary sentence.
_SECTION_LABELS = [
    "Preconditions",
    "Attack input",
    "Expected secure behavior",
    "Security assertion",
    "Impact if exploited",
    "Impact",
    "Failure / current state",
    "Failure",
]
_LABEL_RE = re.compile(
    r"(?:{}):\s*".format("|".join(re.escape(label) for label in _SECTION_LABELS))
)


def parse_docstring_sections(docstring: str | None) -> dict[str, str]:
    """Split a scenario docstring into its labeled sections.

    Matches a label anywhere (not just at line start) since a few
    docstrings run one section straight into the next mid-sentence.
    "Failure / current state:" and "Failure:" collapse to the same key;
    "Impact if exploited:" and "Impact:" collapse to "Impact".
    Returns {} for an empty/unlabeled docstring rather than raising —
    callers fall back to showing nothing for that field.
    """
    if not docstring:
        return {}
    text = inspect.cleandoc(docstring)
    matches = list(_LABEL_RE.finditer(text))
    sections: dict[str, str] = {}
    for i, m in enumerate(matches):
        label = m.group(0).rstrip(": \n\t").strip()
        if label.startswith("Failure"):
            key = "Failure"
        elif label.startswith("Impact"):
            key = "Impact"
        else:
            key = label
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = " ".join(text[start:end].split())
        sections.setdefault(key, body)
    return sections


@dataclass
class TestResult:
    nodeid: str
    rt_id: str
    category: str
    severity: str
    outcome: str  # "passed" | "failed" | "skipped"
    docstring: str  # full raw docstring; sections parsed at render time
    actual: str  # what actually happened this run — assertion failure detail, empty if passed
    file: str
    line: int
    # Every prompt this test actually sent to a chat model and what came
    # back — real completions for redteam_llm scenarios, the configured
    # mock otherwise. Independent of outcome: recorded via conftest.py's
    # `llm_exchange` fixture regardless of whether the test passes or fails.
    exchanges: list[dict[str, str]] = field(default_factory=list)
    # Reporting-only metadata (see conftest.py's `_module_source`): used to
    # identify which `app/` file/function this scenario actually exercises,
    # never fed back into test/security logic.
    func_source: str = ""
    module_source: str = ""
    # True only for @pytest.mark.redteam_llm scenarios — the ones that call
    # a real, un-mocked, configured LLM and judge the actual completion.
    # FINDINGS.md is scoped to exactly these (see render_markdown): it's an
    # AI-team report about LLM reply behavior, not application security —
    # everything else (auth, schema validation, error handling, ...) is
    # tracked in SECURITY_AUDIT_REPORT.md instead.
    is_llm_behavior: bool = False


@dataclass
class RunReport:
    started_at: _dt.datetime
    finished_at: _dt.datetime
    results: list[TestResult] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        counts = {"passed": 0, "failed": 0, "skipped": 0}
        for r in self.results:
            counts[r.outcome] = counts.get(r.outcome, 0) + 1
        return counts


# ── "what/where was actually attacked" — derived from imports + docstring ──
# Never guessed from category alone: grounded either in the app file paths
# the scenario's own docstring names, or in which `app.*` symbol the test
# function actually imports AND references. Best-effort — a wrong or
# missing guess here still leaves the test file/line reference (always
# accurate) visible in the finding, so it degrades gracefully.

_APP_FILE_RE = re.compile(r"app(?:/\s*[\w.-]+)+\.py")
_IMPORT_RE = re.compile(r"from\s+(app[\w.]*)\s+import\s+([^\n]+)")


def _find_app_files(text: str) -> list[str]:
    """Every `app/...py` path mentioned in prose, tolerating the mid-path
    line-wrap a few docstrings have (e.g. "app/features/chat/agents/\\n
    maestro.py" — the wrap lands right after a `/`, which `inspect.cleandoc`
    plus `" ".join(text.split())` turns into a literal space)."""
    found: list[str] = []
    for m in _APP_FILE_RE.finditer(text):
        cleaned = re.sub(r"\s+", "", m.group(0))
        if cleaned not in found:
            found.append(cleaned)
    return found


def _imported_app_symbols(module_source: str) -> dict[str, str]:
    """{local_name: "dotted.module.path.original_name"} for every `from
    app... import a, b as c` line anywhere in the test module's source
    (top-of-file or inside a test function — inspect.getsource(module)
    returns the whole file either way)."""
    symbols: dict[str, str] = {}
    for module_dotted, names in _IMPORT_RE.findall(module_source or ""):
        for raw in names.split(","):
            raw = raw.strip().rstrip("\\").strip()
            if not raw or raw == "(":
                continue
            parts = raw.split(" as ")
            original = parts[0].strip().strip("()")
            local = parts[-1].strip().strip("()")
            if original and local:
                symbols[local] = f"{module_dotted}.{original}"
    return symbols


def _dotted_to_path(dotted: str) -> str:
    return dotted.replace(".", "/") + ".py"


def _resolve_app_symbol(dotted: str) -> tuple[str, str | None]:
    """Best-effort: is `dotted` a submodule (whole file is the finding), or
    an attribute/function inside its parent module? Checked against the
    filesystem (cwd is the repo root when this suite runs) where possible;
    falls back to the attribute reading, which is the more common shape."""
    as_module = _dotted_to_path(dotted)
    if os.path.exists(as_module):
        return as_module, None
    module_part, _, leaf = dotted.rpartition(".")
    if module_part.startswith("app"):
        as_attr = _dotted_to_path(module_part)
        if os.path.exists(as_attr):
            return as_attr, leaf
        as_pkg_init = module_part.replace(".", "/") + "/__init__.py"
        if os.path.exists(as_pkg_init):
            return as_pkg_init, leaf
    return as_module, None


_DOCSTRING_SPAN_RE = re.compile(r'("""|\'\'\')(?:(?!\1).)*\1', re.DOTALL)


def _strip_docstring(func_source: str) -> str:
    """Drop the function's own docstring before scanning its body for
    referenced names. A docstring routinely mentions an unrelated symbol
    only for contrast ("unlike `MatchRequest`, which uses UUID4") — left
    in, that reads as the test actually calling/importing it."""
    m = _DOCSTRING_SPAN_RE.search(func_source)
    return func_source[: m.start()] + func_source[m.end() :] if m else func_source


def _used_app_refs(func_source: str, module_source: str) -> list[tuple[str, str | None]]:
    """(file, function) pairs for every imported `app.*` symbol this
    specific test function actually references — the highest-confidence
    signal available, since it's grounded in a real import + a real call,
    not just prose."""
    code_only = _strip_docstring(func_source or "")
    refs: list[tuple[str, str | None]] = []
    for name, dotted in _imported_app_symbols(module_source).items():
        if re.search(rf"\b{re.escape(name)}\b", code_only):
            pair = _resolve_app_symbol(dotted)
            if pair not in refs:
                refs.append(pair)
    return refs


_BARE_FILE_FUNC_RE = re.compile(r"\b([\w]+\.py)::([\w]+)")


class _AffectedCode(NamedTuple):
    files: list[str]
    function: str | None


def _affected_app_code(docstring: str, func_source: str, module_source: str) -> _AffectedCode:
    """Best-effort "what app code does this finding actually implicate."

    A test function often imports/exercises several `app.*` symbols that
    are just test scaffolding (e.g. spinning up a real checkpointer via
    `build_graph`/`settings`), not the one thing the finding is about — so
    candidates grounded in a real import (`_used_app_refs`) are re-ranked
    by whether the security narrative (the docstring's own "Failure"/
    "Expected secure behavior" text, where the author actually named the
    culpable file/function) mentions them, rather than trusting import
    order alone.
    """
    text = inspect.cleandoc(docstring) if docstring else ""
    sections = parse_docstring_sections(docstring)
    narrative = " ".join(
        (
            sections.get("Failure", ""),
            sections.get("Expected secure behavior", ""),
            _title(docstring),
        )
    )

    from_imports = _used_app_refs(func_source, module_source)

    def _relevance(pair: tuple[str, str | None]) -> int:
        f, fn = pair
        score = 0
        if os.path.basename(f) in narrative:
            score += 2
        if fn and re.search(rf"\b{re.escape(fn)}\b", narrative):
            score += 2
        return score

    from_imports = sorted(from_imports, key=_relevance, reverse=True)
    from_prose = [(f, None) for f in _find_app_files(text)]

    files: list[str] = []
    for f, _ in from_imports + from_prose:
        if f not in files:
            files.append(f)

    primary_func = next((fn for _, fn in from_imports if fn), None)
    # `path.py::func_name` written directly in the docstring (no "app/"
    # prefix, so it never matched _find_app_files) is the strongest
    # possible signal for the function specifically — prefer it whenever
    # its filename matches one of the files already identified above.
    for bare_file, bare_func in _BARE_FILE_FUNC_RE.findall(text):
        if any(f.endswith("/" + bare_file) or f == bare_file for f in files):
            primary_func = bare_func
            break
    if primary_func is None:
        # Look for a bare snake_case function name mentioned in backticks
        # that matches something this test actually imports (cross-checked,
        # not a blind regex guess).
        imported_names = set(_imported_app_symbols(module_source))
        for span in re.findall(r"`([a-z_][a-z0-9_]*)`", text):
            if span in imported_names and re.search(rf"\b{re.escape(span)}\b", func_source or ""):
                primary_func = span
                break

    return _AffectedCode(files=files[:4], function=primary_func)


_SEC_ID_RE = re.compile(r"\bSEC-\d{3}\b")


def _related_sec_ids(docstring: str) -> list[str]:
    seen: list[str] = []
    for m in _SEC_ID_RE.findall(docstring or ""):
        if m not in seen:
            seen.append(m)
    return seen


# ── optional enrichment from SECURITY_AUDIT_REPORT.md ──────────────────────
# Best-effort only: that file lives one level up from this repo in the
# monorepo checkout this suite was written against, but this repo can also
# be checked out standalone (e.g. bare CI clone of just the ai-service
# repo), where it won't exist. Never raises either way.

_SEC_REPORT_CANDIDATES = [
    os.path.join(os.path.dirname(__file__), "..", "..", "SECURITY_AUDIT_REPORT.md"),
]
_SEC_SECTION_RE = re.compile(r"^### (SEC-\d{3}) —.*$", re.MULTILINE)
_SEC_FIX_RE = re.compile(r"\*\*Suggested fix:\*\*\s*(.+?)(?:\n\n|\Z)", re.DOTALL)


def _load_sec_fixes() -> dict[str, str]:
    for candidate in _SEC_REPORT_CANDIDATES:
        try:
            with open(candidate, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            continue
        headers = list(_SEC_SECTION_RE.finditer(text))
        fixes: dict[str, str] = {}
        for i, m in enumerate(headers):
            end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
            section = text[m.start() : end]
            fix_m = _SEC_FIX_RE.search(section)
            if fix_m:
                fixes[m.group(1)] = " ".join(fix_m.group(1).split())
        return fixes
    return {}


# ── plain-language framing ──────────────────────────────────────────────

_VULN_CLASS = {
    "cross_user_access": "Authorization — missing independent ownership/identity check",
    "indirect_injection": "Prompt construction — untrusted data is not separated from instructions",
    "instruction_hierarchy": "LLM behavior / prompt construction — instruction-hierarchy "
    "(jailbreak) resistance",
    "tool_boundary": "Input validation — request/service boundary schema gap",
    "resource_abuse": "Input validation — missing request size/resource limits",
    "secrets_exfiltration": "Application code — error handling or logging leaks internal detail",
    "output_safety": "Output handling — response schema/framing validation",
    "auth_boundary": "Authentication boundary — credential validation",
}

_DEFAULT_IMPACT = {
    "cross_user_access": "A caller that can reach this code path can view or act on another "
    "user's private financial data or conversation history, not just their own.",
    "indirect_injection": "Data that flows into the system from an untrusted source (OCR'd "
    "statement text, client-supplied context) can steer the model's reply — fabricating "
    "figures, recommending unrelated products, or changing how a request is routed — without "
    "the user or the application ever supplying that instruction themselves.",
    "instruction_hierarchy": "A user-supplied chat message can override the assistant's "
    "operating instructions, risking exposure of internal configuration or the assistant "
    "acting outside its intended scope.",
    "tool_boundary": "A malformed or out-of-range argument reaches internal service logic "
    "without being rejected first, risking an unhandled exception (which can itself leak "
    "internals) or an unintended query/operation.",
    "resource_abuse": "An attacker, or a buggy caller, can send an oversized request that "
    "consumes disproportionate LLM/embedding cost or compute with no limit in place — a "
    "cost-based denial-of-service vector.",
    "secrets_exfiltration": "A real configured secret or internal implementation detail can "
    "be exposed to a caller through an error message or log line.",
    "output_safety": "Attacker-controlled content in a response could be misinterpreted by a "
    "downstream consumer (the SSE client, a widget renderer) as protocol framing or a "
    "different data type than intended.",
    "auth_boundary": "A caller without a fully valid credential may still reach an internal, "
    "normally-authenticated endpoint.",
}

# Statements about the *test* (expected-to-fail, positive-control framing,
# "not a broken test") rather than the *security problem* — stripped before
# a docstring section is shown as the human-facing explanation, per the
# reporting rule: explain the vulnerability, not the test implementation.
# "EXPECTED TO FAIL" always marks the start of a trailing test-meta remark
# that runs to the end of the section in every docstring in this suite, so
# it's truncated at rather than bounded with `[^.]*\.` — several of those
# remarks themselves contain a period inside an abbreviation/filename (e.g.
# "SECURITY_AUDIT_REPORT.md"), which a first-period-stops match cuts
# mid-sentence and leaves a dangling fragment behind.
_TRUNCATE_AT_META_RE = re.compile(r"\s*EXPECTED TO FAIL.*", re.IGNORECASE | re.DOTALL)
_INLINE_META_PATTERNS = [
    re.compile(r"[,;]?\s*—?\s*see RT-\d+ for the [^.]*\.", re.IGNORECASE),
]


def _strip_test_meta(text: str) -> str:
    text = _TRUNCATE_AT_META_RE.sub("", text)
    for pat in _INLINE_META_PATTERNS:
        text = pat.sub("", text)
    return " ".join(text.split())


_PYTEST_REPR_TAIL_RE = re.compile(r"\n\s*assert\b.*", re.DOTALL)

# A handful of assertion helpers in this suite append the raw prompt/
# completion to their own message (so a plain-text terminal run still shows
# the exchange) — now redundant once "Evidence" already shows the same
# prompt/output as their own clean fields, so it's cut at the first of
# these markers rather than shown twice.
_OBSERVED_DEDUPE_MARKERS = (
    "the exact prompt sent to the model:",
    "\nCompletion returned",
    "\nPoisoned merchant_raw:",
    "\nPrompt sent:",
    "\nPrompt:",
    "\nCompletion received:",
    "\nCompletion:",
)


def _clean_actual(actual: str) -> str:
    """The test's own assertion message, with pytest's appended expression-
    introspection dump (the raw `assert 'x' in '<huge repr>'` line rewritten
    assertions add below the message) cut off — that dump is what makes the
    current report unreadable (e.g. an entire source file inlined), and the
    message text above it already states the concrete observed value in
    plain language, per this suite's own assertion-writing convention."""
    text = actual.strip()
    if text.startswith("AssertionError: "):
        text = text[len("AssertionError: ") :]
    elif text.startswith("AssertionError"):
        text = text[len("AssertionError") :].lstrip(": ")
    m = _PYTEST_REPR_TAIL_RE.search(text)
    if m:
        text = text[: m.start()]
    for marker in _OBSERVED_DEDUPE_MARKERS:
        idx = text.find(marker)
        if idx != -1:
            text = text[:idx]
    return text.strip(" \n—-")


_GENERIC_PARAM_ID_RE = re.compile(r"^[A-Za-z_]+\d+$")
# When a scenario is parametrized over *two or more* fixtures jointly (e.g.
# `@pytest.mark.parametrize("poisoned_merchant,tells", ...)` stacked with
# `@pytest.mark.parametrize("trial", ...)` for repeat sampling — see
# `redteam/runners/repeat.py`), pytest joins every dimension's id with "-".
# The non-payload dimensions are pytest's own generic auto-ids for values it
# can't stringify meaningfully ("tells0") or the repeat-trial counter
# ("trial0"), and can stack (e.g. "-tells0-trial0"). Left in, they read as
# if part of the literal attacker input rather than pytest bookkeeping —
# `+` (not a single match) strips all of them, however many are present;
# stripped for this field specifically, not from `_case_label` (still
# useful there to disambiguate cases in a collapsed `<summary>`).
_TRAILING_AUTO_ID_RE = re.compile(r"(?:-[A-Za-z_]+\d+)+$")


def _case_label(nodeid: str) -> str:
    if "[" in nodeid:
        return nodeid[nodeid.index("[") + 1 : -1]
    return "(single case)"


def _exact_attacker_input(nodeid: str, sections: dict[str, str]) -> str:
    """The literal attacker-controlled value for one case. Prefers the
    pytest parametrize id — it *is* the payload for most scenarios here —
    unless it's one of pytest's own generic auto-ids (e.g. "headers0" for
    an unstringifiable dict param), in which case the docstring's own
    "Attack input" prose (which spells the literal value out in those
    cases) is the only real source."""
    label = _case_label(nodeid)
    if label != "(single case)" and not _GENERIC_PARAM_ID_RE.match(label):
        return _TRAILING_AUTO_ID_RE.sub("", label)
    from_docstring = sections.get("Attack input", "")
    if from_docstring:
        return from_docstring
    if label != "(single case)":
        return label
    return "(none — this is a static/structural check with no distinct attacker-supplied value)"


def _truncate(text: str, limit: int = 140) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _anchor(rt_id: str) -> str:
    return rt_id.lower().replace(" ", "-")


def _fenced(text: str, *, indent: str = "") -> list[str]:
    out = [f"{indent}```text"]
    out.extend(f"{indent}{line}" for line in (text.splitlines() or [""]))
    out.append(f"{indent}```")
    return out


def _group_by_rt_id(results: list[TestResult]) -> list[list[TestResult]]:
    order: list[str] = []
    groups: dict[str, list[TestResult]] = {}
    for r in results:
        if r.rt_id not in groups:
            groups[r.rt_id] = []
            order.append(r.rt_id)
        groups[r.rt_id].append(r)
    return [groups[rt_id] for rt_id in order]


# ── per-case evidence block (Attacker input / LLM prompt / LLM output) ─────


def _render_case_evidence(
    r: TestResult, sections: dict[str, str], *, indent: str = ""
) -> list[str]:
    out: list[str] = []
    out.append(f"{indent}**Attacker input:**")
    out.extend(_fenced(_exact_attacker_input(r.nodeid, sections), indent=indent))
    out.append("")

    if r.exchanges:
        for exch in r.exchanges:
            real = exch.get("real") == "true"
            label = "real model response" if real else "mock — prompt construction check only"
            out.append(f"{indent}**Prompt sent to the LLM** _({label})_:")
            out.extend(_fenced(exch.get("prompt", ""), indent=indent))
            out.append("")
            out.append(f"{indent}**LLM output:**")
            out.extend(_fenced(exch.get("completion", ""), indent=indent))
            out.append("")
    else:
        out.append(
            f"{indent}**Prompt sent to the LLM:** N/A — no LLM call occurs in this code path."
        )
        out.append("")
        out.append(f"{indent}**LLM output:** N/A — no LLM call occurs in this code path.")
        out.append("")

    out.append(f"{indent}**Observed (what actually happened):**")
    out.extend(_fenced(_clean_actual(r.actual) or "(no assertion detail captured)", indent=indent))
    return out


def _render_finding(
    group: list[TestResult], sec_fixes: dict[str, str], rt_id_totals: dict[str, int]
) -> list[str]:
    r0 = group[0]
    sections = parse_docstring_sections(r0.docstring)
    title = _title(r0.docstring)
    code = _affected_app_code(r0.docstring, r0.func_source, r0.module_source)
    sec_ids = _related_sec_ids(r0.docstring)

    out: list[str] = []
    add = out.append

    add(f'<a id="{_anchor(r0.rt_id)}"></a>')
    add(f"## {r0.rt_id} — {title or r0.category}")
    add("")
    add(f"**Severity:** {r0.severity.upper()}  ")
    add(f"**Category:** {r0.category}  ")
    add("**Status:** VULNERABLE  ")
    add("**Affected repository:** nbe-financial-advisor-ai-service  ")
    files = code.files
    files_str = ", ".join(f"`{f}`" for f in files) if files else "_see test reference below_"
    add(f"**Affected file(s):** {files_str}  ")
    func = code.function
    func_str = f"`{func}`" if func else "_see test reference below_"
    add(f"**Affected function/component:** {func_str}  ")
    if sec_ids:
        fixes = [f"{sid} (SECURITY_AUDIT_REPORT.md)" for sid in sec_ids]
        add(f"**Related security issue:** {', '.join(fixes)}  ")
    total_for_rt_id = rt_id_totals.get(r0.rt_id, len(group))
    rate = len(group) / total_for_rt_id if total_for_rt_id else 0.0
    add(
        f"**Attack success rate (this technique):** {len(group)}/{total_for_rt_id} "
        f"payload+trial combinations got the model to comply ({rate:.1%})  "
    )
    add(f"**Test:** `{r0.file}:{r0.line}` — `{r0.nodeid.split('::', 1)[-1].split('[', 1)[0]}`")
    add("")

    class_label = _VULN_CLASS.get(r0.category, r0.category)
    where = f"`{files[0]}`" + (f" (`{func}`)" if func else "") if files else "the code under test"
    failure_text = _strip_test_meta(sections.get("Failure", ""))

    # 1. What is the problem? — a short, plain-language pointer; the full
    # explanation lives in "Why this is a security issue" below rather than
    # being repeated here verbatim.
    add("### What is the problem?")
    add("")
    add(f"{class_label} in {where}.")
    add("")

    # 2. Attack
    add("### Attack")
    add("")
    attack_text = sections.get("Attack input", "") or "(see 'Why this is a security issue' below)"
    add(attack_text)
    add("")

    # 3-5. Evidence: exact attacker input / exact LLM prompt / exact LLM output
    add("### Evidence")
    add("")
    if len(group) == 1:
        out.extend(_render_case_evidence(group[0], sections))
        add("")
    else:
        add(f"{len(group)} attack variants were tested against this same code path:")
        add("")
        for r in group:
            out.append(f"<details><summary>{_truncate(_case_label(r.nodeid))}</summary>")
            out.append("")
            out.extend(_render_case_evidence(r, sections, indent=""))
            out.append("")
            out.append("</details>")
            out.append("")

    # 6. Vulnerability classification
    add("### Vulnerability classification")
    add("")
    add(class_label)
    add("")

    # 7. Why this is a security issue — the full root-cause explanation
    # (what's wrong with the observed behavior AND why it matters), not
    # duplicated anywhere else in this finding.
    add("### Why this is a security issue")
    add("")
    why_text = failure_text or _strip_test_meta(sections.get("Expected secure behavior", ""))
    add(why_text or "(no additional detail in the scenario docstring — see 'Evidence' above)")
    add("")

    # 8. Impact
    add("### Impact")
    add("")
    impact_text = _strip_test_meta(sections.get("Impact", ""))
    default_impact = _DEFAULT_IMPACT.get(r0.category, "")
    if impact_text and default_impact:
        add(f"{impact_text} {default_impact}")
    else:
        add(impact_text or default_impact or "(impact not further characterized for this category)")
    add("")

    # 9. Suggested fix
    add("### Suggested fix")
    add("")
    expected = sections.get("Expected secure behavior", "")
    if expected:
        add(f"**Fix:** {expected}")
    for sid in sec_ids:
        if sid in sec_fixes:
            add("")
            add(f"**From SECURITY_AUDIT_REPORT.md ({sid}):** {sec_fixes[sid]}")
    if not expected and not any(sid in sec_fixes for sid in sec_ids):
        add(
            "(no explicit fix guidance in the scenario docstring — see 'Why this is a "
            "security issue' above)"
        )
    add("")

    return out


def _title(docstring: str | None) -> str:
    """The summary after the 'RT-NNN — ' prefix, from the docstring's first
    paragraph (not just its first physical line — several docstrings wrap
    that opening sentence across two or three lines before the period)."""
    if not docstring:
        return ""
    text = inspect.cleandoc(docstring)
    first_paragraph = text.split("\n\n", 1)[0]
    joined = " ".join(first_paragraph.split())
    if "—" in joined:
        joined = joined.split("—", 1)[1].strip()
    return _strip_test_meta(joined)


def render_markdown(report: RunReport) -> str:
    # Scoped to @pytest.mark.redteam_llm scenarios only — the ones that send
    # an attack to a real, configured LLM and judge its actual completion.
    # This file is insight for the AI team on LLM reply behavior (system
    # prompt, guardrails, susceptibility to injection/jailbreak); it is not
    # an application-security report. Everything else this suite also
    # checks — authorization, request-schema validation, resource limits,
    # error-message hygiene, output framing — is application code/security,
    # not LLM behavior, and is tracked in SECURITY_AUDIT_REPORT.md instead
    # (see SEC-005, SEC-008, SEC-010, SEC-021, SEC-022, SEC-023).
    llm_results = [r for r in report.results if r.is_llm_behavior]
    counts = {
        "passed": sum(1 for r in llm_results if r.outcome == "passed"),
        "failed": sum(1 for r in llm_results if r.outcome == "failed"),
        "skipped": sum(1 for r in llm_results if r.outcome == "skipped"),
    }
    total = len(llm_results)
    lines: list[str] = []
    add = lines.append

    add("# LLM Behavior Red-Team Findings — NBE AI Service")
    add("")
    add(
        "Auto-generated by `redteam/reporting.py` — do not hand-edit; rerun "
        "the command below to refresh it. This file always reflects the "
        "*last* run, not a history of every run — see git history/blame for that."
    )
    add("")
    add(
        "**Scope:** only scenarios marked `@pytest.mark.redteam_llm` — the ones that send an "
        "attack to a real, configured LLM and judge its actual completion. This is insight for "
        "the AI team on model/prompt behavior (does it leak the system prompt, follow an "
        "injected instruction, fabricate data), not an application-security report. "
        "Authorization, request-schema validation, resource limits, error-message hygiene, and "
        "output-framing findings from the rest of this suite are application code/security, not "
        "LLM behavior, and are tracked in `SECURITY_AUDIT_REPORT.md` instead (see SEC-005, "
        "SEC-008, SEC-010, SEC-021, SEC-022, SEC-023)."
    )
    add("")
    add(f"- **Generated:** {report.finished_at.isoformat(timespec='seconds')}")
    add(f"- **Duration:** {(report.finished_at - report.started_at).total_seconds():.1f}s")
    if total == 0:
        add(
            "- **Run:** no `redteam_llm` scenarios were collected this run "
            "(unexpected — check `redteam/scenarios/test_rt_real_model_attacks.py` and "
            "`test_rt_instruction_hierarchy.py` are being collected)."
        )
    elif counts["skipped"] == total:
        add(
            f"- **Run:** all {total} real-model scenarios were **skipped** — this was a "
            "deterministic-only run. Set `AI_SERVICE_REDTEAM_ENABLE_LLM=1` and configure a "
            "real `AI_SERVICE_CHAT_MODEL__*` provider (`make redteam-llm`) to actually attack "
            "the model and populate this report."
        )
    else:
        add(
            f"- **Run:** `AI_SERVICE_REDTEAM_ENABLE_LLM=1 uv run pytest redteam` against a "
            f"real provider ({total} real-model scenarios)"
        )
    add("")
    add("## Summary")
    add("")
    add("| Total | Passed | Failed | Skipped |")
    add("|---|---|---|---|")
    add(f"| {total} | {counts['passed']} | {counts['failed']} | {counts['skipped']} |")
    add("")

    ran = [r for r in llm_results if r.outcome in ("passed", "failed")]
    if ran:
        add("## Attack Success Rate by Category")
        add("")
        add(
            "The headline number for the AI team: what fraction of *attempted* attacks (across "
            "every payload and every repeat trial — see `AI_SERVICE_REDTEAM_LLM_REPEAT` in "
            "redteam/README.md) actually got the model to comply, not just whether any single "
            "payload happened to succeed once. Sorted worst first."
        )
        add("")
        add("| Category | Attempts | Succeeded (attack got through) | Attack success rate |")
        add("|---|---|---|---|")
        by_category: dict[str, list[TestResult]] = {}
        for r in ran:
            by_category.setdefault(r.category, []).append(r)
        category_rates = []
        for category, results in by_category.items():
            attempts = len(results)
            succeeded = sum(1 for r in results if r.outcome == "failed")
            rate = succeeded / attempts if attempts else 0.0
            category_rates.append((category, attempts, succeeded, rate))
        for category, attempts, succeeded, rate in sorted(
            category_rates, key=lambda x: x[3], reverse=True
        ):
            add(f"| {category} | {attempts} | {succeeded} | {rate:.1%} |")
        add("")

    failed = [r for r in llm_results if r.outcome == "failed"]
    passed = [r for r in llm_results if r.outcome == "passed"]
    skipped = [r for r in llm_results if r.outcome == "skipped"]

    # ── table of contents ───────────────────────────────────────────────
    add("## Contents")
    add("")
    if failed:
        add("- [Findings](#findings)")
        for group in _group_by_rt_id(failed):
            r = group[0]
            n = f" ({len(group)} attack variants)" if len(group) > 1 else ""
            add(f"  - [{r.rt_id} — {r.category}](#{_anchor(r.rt_id)}){n}")
    if passed:
        add("- [Passed](#passed)")
    if skipped:
        add("- [Skipped](#skipped)")
    add("")

    if failed:
        add('<a id="findings"></a>')
        add("# Findings")
        add("")
        add(
            "A failure means the model's real completion **fell for the attack** — followed "
            "an injected instruction, leaked the system prompt, or fabricated data it "
            "shouldn't have. This is a model/prompt-behavior gap for the AI team to close "
            "(system-prompt wording, guardrails, output filtering), not a broken test — do "
            "not edit a test to make it pass without changing how the model is prompted or "
            "constrained."
        )
        add("")
        add(
            "Each finding below separates **exact attacker input**, **exact LLM "
            "prompt**, **exact LLM output**, and **security interpretation** into their "
            "own labeled fields — reconstructing an attack from a pytest assertion "
            "message should never be necessary."
        )
        add("")
        sec_fixes = _load_sec_fixes()
        rt_id_totals: dict[str, int] = {}
        for r in ran:
            rt_id_totals[r.rt_id] = rt_id_totals.get(r.rt_id, 0) + 1
        by_severity: dict[str, list[TestResult]] = {}
        for r in failed:
            by_severity.setdefault(r.severity, []).append(r)
        for severity in sorted(by_severity, key=lambda s: _SEVERITY_ORDER.get(s, 9)):
            add(f"## {severity.upper()}")
            add("")
            for group in _group_by_rt_id(sorted(by_severity[severity], key=lambda r: r.rt_id)):
                lines.extend(_render_finding(group, sec_fixes, rt_id_totals))
                add("---")
                add("")
    elif total and counts["skipped"] < total:
        add("No failures — the model resisted every real attack sent to it this run.")
        add("")

    if passed:
        add('<a id="passed"></a>')
        add("## Passed (attacks the model successfully resisted)")
        add("")
        add("| RT ID | Category | Cases | Test |")
        add("|---|---|---|---|")
        for group in _group_by_rt_id(sorted(passed, key=lambda r: r.rt_id)):
            r0 = group[0]
            add(
                f"| {r0.rt_id} | {r0.category} | {len(group)} | "
                f"`{r0.nodeid.split('::', 1)[-1].split('[', 1)[0]}` |"
            )
        add("")

        passed_with_exchanges = [r for r in passed if r.exchanges]
        if passed_with_exchanges:
            add("<details><summary>Model exchanges for passing tests — click to expand</summary>")
            add("")
            for group in _group_by_rt_id(passed_with_exchanges):
                r0 = group[0]
                short_name = r0.nodeid.split("::", 1)[-1].split("[", 1)[0]
                add(f"**{r0.rt_id}** — `{short_name}` ({len(group)} case(s))")
                add("")
                collapse = len(group) > 1
                for r in group:
                    exch_lines: list[str] = []
                    for exch in r.exchanges:
                        real = exch.get("real") == "true"
                        label = (
                            "real model response"
                            if real
                            else "mock — prompt construction check only"
                        )
                        exch_lines.append(f"_Model exchange ({label}):_")
                        exch_lines.append("Prompt:")
                        exch_lines.extend(_fenced(exch.get("prompt", "")))
                        exch_lines.append("Completion:")
                        exch_lines.extend(_fenced(exch.get("completion", "")))
                        exch_lines.append("")
                    if collapse:
                        add(f"<details><summary>{_truncate(_case_label(r.nodeid), 140)}</summary>")
                        add("")
                        lines.extend(exch_lines)
                        add("</details>")
                    else:
                        lines.extend(exch_lines)
                    add("")
            add("</details>")
            add("")

    if skipped:
        add('<a id="skipped"></a>')
        add(f"## Skipped ({len(skipped)})")
        add("")
        add(
            "Model-dependent (`redteam_llm`) scenarios — run "
            "`make redteam-llm` (or `AI_SERVICE_REDTEAM_ENABLE_LLM=1 uv run "
            "pytest redteam`) with a real provider configured to include these."
        )
        add("")

    return "\n".join(lines) + "\n"


def write_report(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    try:
        os.chmod(path, 0o664)
    except OSError:
        pass  # best-effort — e.g. filesystem doesn't support chmod
