"""Red-team suite setup: offline env defaults, shared fixtures, marker
registration, and the Phase-12-style terminal summary.

Self-contained on purpose — this conftest does not import `tests/conftest.py`
so `pytest redteam` never depends on the production test tree being
collected first. Every credential below is a fabricated placeholder; the
suite runs fully offline (`AI_SERVICE_CHAT_MODEL__USE_MOCK=1`) unless a
scenario explicitly forces the real-LLM code path against the recording
double in `redteam/runners/fake_llm.py` (still no network call) or is marked
`redteam_llm` (skipped unless `AI_SERVICE_REDTEAM_ENABLE_LLM=1`, see below).

IMPORTANT: this suite is routinely run inside the same dev containers that
carry *real* provider credentials as process env vars (e.g. this repo's
`docker-compose.dev.yml` `env_file:`s — confirmed to include a live
`AI_SERVICE_SCOPE_GUARD__HOSTED_API_KEY` and `AI_SERVICE_CHAT_MODEL__USE_MOCK=0`
in that setup). `os.environ.setdefault(...)` does NOT override an
already-set var, so the safety/determinism-critical flags below are force-set
with plain assignment instead — the one deliberate exception to "never
override the ambient environment" in this file, because getting this
particular set wrong means real network calls / real spend, not just a
wrong test result.
"""

import datetime as _dt
import inspect
import os
from shutil import which
from types import ModuleType

# Force-set (not setdefault): must win over any real value already exported
# by the ambient environment (a docker-compose env_file, a developer's
# shell, etc.) — see the module docstring above. Getting any of these wrong
# means a real LLM/embedding/OCR/HF/Langfuse call, not just a wrong result.
os.environ["AI_SERVICE_CHAT_MODEL__USE_MOCK"] = "1"
os.environ["AI_SERVICE_MINERU__USE_MOCK"] = "1"
os.environ["AI_SERVICE_SCOPE_GUARD__ENABLED"] = "0"
os.environ["AI_SERVICE_LANGFUSE__ENABLED"] = "0"

os.environ.setdefault("AI_SERVICE_CHAT_MODEL__OPENAI_BASE_URL", "https://api.openai.com/v1")
os.environ.setdefault("AI_SERVICE_CHAT_MODEL__OPENAI_API_KEY", "__mock__")
os.environ.setdefault("AI_SERVICE_CHAT_MODEL__MODEL_NAME", "gpt-4o-mini")
os.environ.setdefault("AI_SERVICE_TOKEN", "redteam-test-token-not-a-real-secret")
os.environ.setdefault("AI_SERVICE_STORAGE__S3_BUCKET", "pfm-statements-ocr")
os.environ.setdefault("AI_SERVICE_STORAGE__S3_ACCESS_KEY", "dev-seaweed-key")
os.environ.setdefault("AI_SERVICE_STORAGE__S3_SECRET_KEY", "dev-seaweed-secret")
os.environ.setdefault("AI_SERVICE_OWN_DB__POSTGRES_DB", "test-ai-appdb")
os.environ.setdefault("AI_SERVICE_OWN_DB__POSTGRES_USER", "test-ai-user")
os.environ.setdefault("AI_SERVICE_OWN_DB__POSTGRES_PASSWORD", "test-ai-pass")
os.environ.setdefault("AI_SERVICE_BACKEND_DB__HOST", "test-backend-db")
os.environ.setdefault("AI_SERVICE_BACKEND_DB__NAME", "test-backend-appdb")
os.environ.setdefault("AI_SERVICE_BACKEND_DB__USER", "test-backend-role")
os.environ.setdefault("AI_SERVICE_BACKEND_DB__PASSWORD", "test-backend-pass")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

TOKEN = os.environ["AI_SERVICE_TOKEN"]


def docker_available() -> bool:
    return which("docker") is not None


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def wrong_auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer not-the-real-token"}


@pytest.fixture(autouse=True)
def authorized_conversation_for_unrelated_scenarios(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep each scenario focused on the security boundary it targets.

    Conversation ownership has dedicated behavioral and static coverage in
    ``test_rt_cross_user_access.py``. Other scenarios assume an already
    authorized conversation so they can reach the output, error, and prompt
    paths they are designed to attack without requiring a backend database.
    """
    if request.node.path.name == "test_rt_cross_user_access.py":
        return

    async def _authorized(*args: object, **kwargs: object) -> bool:
        return True

    monkeypatch.setattr(
        "app.features.chat.service._conversation_belongs_to_user",
        _authorized,
    )


# ── model input/output capture ────────────────────────────────────────────
# Every scenario that talks to a chat model — real or the fake double in
# redteam/runners/fake_llm.py — calls this to record exactly what it sent
# and what came back. Independent of pass/fail (unlike the assertion
# message, which only exists on failure): this is how the findings report
# shows "the actual prompt input and completion output" as its own section
# for both a confirmed-safe positive control and a real finding.

_LLM_EXCHANGES: dict[str, list[dict[str, str]]] = {}


@pytest.fixture
def llm_exchange(request: pytest.FixtureRequest):
    nodeid = request.node.nodeid

    def _record(*, prompt: str, completion: str, real: bool = False) -> None:
        _LLM_EXCHANGES.setdefault(nodeid, []).append(
            {"prompt": prompt, "completion": completion, "real": "true" if real else "false"}
        )

    return _record


# ── marker registration + redteam_llm auto-skip ──────────────────────────

_REDTEAM_METADATA: dict[str, dict[str, object]] = {}
_RUN_STARTED_AT: _dt.datetime | None = None

# Source text, cached per module (not per test) since many parametrized cases
# share one module and inspect.getsource() re-reads the file each call.
# Used only by redteam/reporting.py to identify which `app/` file/function a
# given scenario actually exercises (import statements + which imported name
# the test body references) — reporting metadata, not test/security logic.
_MODULE_SOURCE_CACHE: dict[str, str] = {}


def _module_source(module: object) -> str:
    if not isinstance(module, ModuleType):
        return ""
    name = module.__name__
    if name not in _MODULE_SOURCE_CACHE:
        try:
            _MODULE_SOURCE_CACHE[name] = inspect.getsource(module)
        except (OSError, TypeError):
            _MODULE_SOURCE_CACHE[name] = ""
    return _MODULE_SOURCE_CACHE[name]


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "redteam(id, category, severity): red-team scenario metadata "
        "(RT id, attack category, severity if the attack succeeds).",
    )
    config.addinivalue_line(
        "markers",
        "redteam_llm: requires a real LLM provider; skipped unless "
        "AI_SERVICE_REDTEAM_ENABLE_LLM=1 is set (see redteam/README.md).",
    )
    global _RUN_STARTED_AT
    _RUN_STARTED_AT = _dt.datetime.now(_dt.timezone.utc)


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("redteam")
    group.addoption(
        "--redteam-report-path",
        default=os.path.join(os.path.dirname(__file__), "reports", "FINDINGS.md"),
        help="Where to (re)write the Markdown findings report. "
        "Default: redteam/reports/FINDINGS.md",
    )
    group.addoption(
        "--no-redteam-report",
        action="store_true",
        default=False,
        help="Skip writing the Markdown findings report (still prints the terminal summary).",
    )


def pytest_collection_modifyitems(
    session: pytest.Session, config: pytest.Config, items: list[pytest.Item]
) -> None:
    llm_enabled = os.environ.get("AI_SERVICE_REDTEAM_ENABLE_LLM") == "1"
    skip_llm = pytest.mark.skip(
        reason=(
            "model-dependent red-team test — set AI_SERVICE_REDTEAM_ENABLE_LLM=1 "
            "and configure a real AI_SERVICE_CHAT_MODEL__* provider to run it"
        )
    )
    for item in items:
        marker = item.get_closest_marker("redteam")
        if marker is not None:
            file_path, lineno, _ = item.location
            func = getattr(item, "function", None)
            func_source = ""
            if func is not None:
                try:
                    func_source = inspect.getsource(func)
                except (OSError, TypeError):
                    func_source = ""
            _REDTEAM_METADATA[item.nodeid] = {
                "id": str(marker.kwargs.get("id", "RT-???")),
                "category": str(marker.kwargs.get("category", "uncategorized")),
                "severity": str(marker.kwargs.get("severity", "info")),
                "docstring": func and (func.__doc__ or ""),
                "file": file_path,
                "line": lineno + 1,
                "func_source": func_source,
                "module_source": _module_source(inspect.getmodule(func)) if func else "",
                # Real-model-only vs. deterministic/mock — see reporting.py:
                # only redteam_llm-marked scenarios call an actual configured
                # LLM and judge its real completion; FINDINGS.md is scoped to
                # exactly those (app-level/structural findings belong in
                # SECURITY_AUDIT_REPORT.md instead, not in an AI-team report).
                "is_llm_behavior": item.get_closest_marker("redteam_llm") is not None,
            }
        if item.get_closest_marker("redteam_llm") is not None and not llm_enabled:
            item.add_marker(skip_llm)


_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def _collect_reports(terminalreporter: object) -> tuple[list, list, list]:
    stats = getattr(terminalreporter, "stats", {})
    failed = [r for r in stats.get("failed", []) if getattr(r, "when", "call") == "call"]
    passed = [r for r in stats.get("passed", []) if getattr(r, "when", "call") == "call"]
    skipped = list(stats.get("skipped", []))
    return failed, passed, skipped


def pytest_terminal_summary(
    terminalreporter: object, exitstatus: int, config: pytest.Config
) -> None:
    failed, passed, skipped = _collect_reports(terminalreporter)
    if not failed and not passed and not skipped:
        return  # nothing red-team-shaped ran (e.g. collection error, or -k excluded everything)

    write = terminalreporter.write_line
    write("")
    write("=" * 70)
    write("Red Team Results")
    write("=" * 70)
    write(
        f"Total: {len(failed) + len(passed)}   Passed: {len(passed)}   "
        f"Failed: {len(failed)}   Skipped: {len(skipped)}"
    )

    if failed:
        by_severity: dict[str, list] = {}
        for report in failed:
            meta = _REDTEAM_METADATA.get(report.nodeid)
            severity = meta["severity"] if meta else "info"
            by_severity.setdefault(severity, []).append((report, meta))

        for severity in sorted(by_severity, key=lambda s: _SEVERITY_ORDER.get(s, 9)):
            write("")
            write(f"{severity.upper()}:")
            for report, meta in by_severity[severity]:
                rt_id = meta["id"] if meta else "RT-???"
                category = meta["category"] if meta else "uncategorized"
                short_name = report.nodeid.split("::")[-1]
                write(f"  {rt_id} [{category}] {short_name}")
                write(f"      {report.nodeid}")
    write("")
    write("=" * 70)

    if config.getoption("--no-redteam-report"):
        return

    from redteam.reporting import RunReport, TestResult, render_markdown, write_report

    def _actual_result(report: object) -> str:
        """What actually happened, in the assertion's own words. Every
        scenario in this suite writes an assertion message that states the
        concrete observed value (the leaked dict, the accepted-when-it-
        shouldn't-have-been object, the raw prompt sent) rather than a bare
        `assert x == y` — see redteam/README.md's "How assertions work".
        This pulls that message out; `reprcrash.message` is pytest's own
        one-line "AssertionError: <your message>" summary, the most direct
        source. Falls back to the last line of the full traceback if a
        failure has no reprcrash (e.g. an error outside an assert)."""
        longrepr = getattr(report, "longrepr", None)
        crash = getattr(longrepr, "reprcrash", None)
        if crash is not None:
            return str(crash.message).strip()
        return str(longrepr).strip().splitlines()[-1][:500] if longrepr else ""

    results: list[TestResult] = []
    for outcome, reports in (("failed", failed), ("passed", passed), ("skipped", skipped)):
        for report in reports:
            meta = _REDTEAM_METADATA.get(report.nodeid, {})
            results.append(
                TestResult(
                    nodeid=report.nodeid,
                    rt_id=str(meta.get("id", "RT-???")),
                    category=str(meta.get("category", "uncategorized")),
                    severity=str(meta.get("severity", "info")),
                    outcome=outcome,
                    docstring=str(meta.get("docstring", "") or ""),
                    actual=_actual_result(report) if outcome == "failed" else "",
                    exchanges=list(_LLM_EXCHANGES.get(report.nodeid, [])),
                    file=str(meta.get("file", "")),
                    line=int(meta.get("line", 0) or 0),
                    func_source=str(meta.get("func_source", "") or ""),
                    module_source=str(meta.get("module_source", "") or ""),
                    is_llm_behavior=bool(meta.get("is_llm_behavior", False)),
                )
            )

    run_report = RunReport(
        started_at=_RUN_STARTED_AT or _dt.datetime.now(_dt.timezone.utc),
        finished_at=_dt.datetime.now(_dt.timezone.utc),
        results=results,
    )
    report_path = config.getoption("--redteam-report-path")
    write_report(report_path, render_markdown(run_report))
    write("")
    write(f"Findings report written to {report_path}")
