---
description: "Phase 2 task list — Agentic Pipelines, Analytics & Integration"
---

# Tasks: Agentic Pipelines, Analytics & Integration (Phase 2)

**Feature dir**: `specs/002-phase2-agentic-pipelines/`
**Spec**: `specs/002-phase2-agentic-pipelines/spec.md`
**Source plan**: `specs/001-ai-service-scaffolding/plan.md` (sections 2.1–2.6)
**Constitution**: `.specify/memory/constitution.md` (v1.0.0)

## ⚠️ READ THIS FIRST — Executor Contract

You are implementing this WITHOUT prior project knowledge. Obey these rules exactly:

1. **Language/stack**: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0 async (`asyncpg`), LangGraph/LangChain. Package manager is **`uv`** (never `pip install`; use `uv add` / `uv sync` / `uv run`).
2. **Slice layout is under `app/features/<slice>/`** (NOT top-level `app/<slice>/`). Core shared code is under `app/core/`. Backend read-only models are in `app/backend_db/`.
3. **Two databases, hard boundary** (Constitution IV — NON-NEGOTIABLE):
   - **Own DB** (READ-WRITE): `app/core/db.py` → `OwnBase`, `own_engine`, `OwnSession`, `get_own_session()`. Alembic migrates ONLY this DB.
   - **Backend DB** (READ-ONLY): `app/backend_db/__init__.py` → `BackendBase`, `get_backend_session()`. **NEVER** write it. **NEVER** import `BackendBase` into `migrations/env.py`.
   - Analytics results and embeddings are **RETURNED** to the caller (Django persists them). Do **not** write backend tables or embedding columns.
4. **Auth**: every new endpoint mounts under prefix `/internal` and requires `Depends(require_token)` from `app/core/security.py`. Only `/health` and `/ready` are unauthenticated.
5. **Mock-first LLM & embedder**: no test may make a real model/network call. Every agent/service MUST branch on `settings.use_mock_llm` (from `app/core/config.py`) and return a deterministic canned result of the exact same shape in mock mode. Embedding calls go through the injected embed function so tests can monkeypatch it.
6. **Quality gates that MUST pass before a task is "done"** (run from repo root):
   - `uv run ruff check .`
   - `uv run black --check .` (line length 100)
   - `uv run mypy app`
   - `uv run pytest tests -q --ignore=tests/integration`
7. **Every task below lists its exact file path(s), the symbols to create with signatures, its dependencies (task IDs), and an acceptance check.** Do not invent additional files. Commit after each task.

## Phase 1 Interfaces Consumed (built by Phase 1 — DO NOT build here; import as-is)

If any of these is missing at execution time, STOP and flag it — it is a Phase 1 (sections 1.1–1.4) deliverable, out of scope for this task list.

| Symbol | Import path | Shape |
|---|---|---|
| `settings` | `app.core.config` | pydantic-settings; has `use_mock_llm: bool`, `openai_base_url`, `model_name`, `openai_api_key`, `ai_service_token`, `postgres_host/port/db/user/password`, `own_database_url` (property), `backend_database_url` (property) |
| `OwnBase`, `own_engine`, `OwnSession`, `get_own_session` | `app.core.db` | Own DB (read-write). `get_own_session()` is an async generator dependency yielding `AsyncSession` |
| `BackendBase`, `get_backend_session` | `app.backend_db` | Backend DB (read-only). `get_backend_session()` yields a read-only `AsyncSession` |
| `require_token` | `app.core.security` | FastAPI dependency; 401s on bad/missing Bearer token |
| `get_chat_model` | `app.core.llm` | `() -> ChatOpenAI`; never called in mock mode |
| `embed_texts` | `app.features.embed.service` | `async def embed_texts(texts: list[str]) -> list[list[float]]`; returns 768-dim vectors. **If Phase 1 named it differently, adapt imports and note it.** |
| `AiProblemStatement`, `AiRecommendationLog` | `app.features.recommendations.models` | Own tables. `AiProblemStatement(id, product_id, statement_text, embedding vector(768))`; `AiRecommendationLog(id, user_id, product_id, matched_query, similarity_score, shown_at)` |
| `AiAuditLog` | `app.features.audit.models` | Own table `(id, user_id, action, detail_json, created_at)` |

**Tests are REQUIRED** (Constitution I; spec FR-026/027 and User Story 5). Each story includes unit tests (mock LLM/embedder) and, where DB behavior matters, Testcontainers integration tests.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add Phase 2 dependencies and slice directories. No behavior yet.

[-] [X] T001 Add Phase 2 runtime dependencies via `uv`: run `uv add "langgraph>=0.2" "langgraph-checkpoint-postgres>=2.0" "psycopg[binary,pool]>=3.2" "pgvector>=0.3" "numpy>=2.0"` from repo root. This edits `pyproject.toml` `[project].dependencies` and refreshes `uv.lock`. **Acceptance**: `uv sync --frozen` succeeds and `uv run python -c "import langgraph, langgraph.checkpoint.postgres, psycopg_pool, pgvector, numpy"` exits 0.
[-] [X] T002 [P] Create empty slice packages with `__init__.py` files: `app/features/plan/__init__.py`, `app/features/recommendations/__init__.py`, `app/features/analytics/__init__.py`, `app/features/analytics/jobs/__init__.py`. (`app/features/chat/` and `app/features/audit/` already exist or are Phase 1.) **Acceptance**: `uv run python -c "import app.features.plan, app.features.recommendations, app.features.analytics, app.features.analytics.jobs"` exits 0.
[-] [X] T003 [P] Create test package dirs with empty `__init__.py`: `tests/features/plan/__init__.py`, `tests/features/recommendations/__init__.py`, `tests/features/analytics/__init__.py`. **Acceptance**: directories exist and pytest collects with no import errors.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared building blocks every story needs. **⚠️ No user story may start until this phase is complete.**

[-] [X] T004 [P] Add hand-written **read-only** backend models in `app/backend_db/models.py` (currently empty). Each inherits `BackendBase` (imported from `app.backend_db`), maps only the columns Phase 2 reads, and is NEVER written. Define these classes with `__tablename__` and typed `Mapped[...]` columns:
  - `Transaction` (`transactions`): `id`, `user_id`, `account_id`, `txn_date` (date), `amount` (Numeric), `description` (str), `category` (str), `direction` (str; e.g. debit/credit).
  - `MonthlySummary` (`monthly_summaries`): `id`, `user_id`, `account_id`, `month` (str `YYYY-MM` or date), `total_income` (Numeric), `total_expense` (Numeric), `net` (Numeric), `by_category` (JSON).
  - `BankAccount` (`bank_accounts`): `id`, `user_id`, `bank_name`, `account_name`.
  - `Budget` (`budgets`): `id`, `user_id`, `name`, `period`.
  - `BudgetAllocation` (`budget_allocations`): `id`, `budget_id`, `category`, `percentage` (Numeric).
  - `Product` (`products`): `id`, `name`, `description`, `category`.
  - `User` (`users`): `id`, `email`, `full_name`.
  - `RecurringCharge` (`recurring_charges`): `id`, `user_id`, `account_id`, `merchant`, `amount` (Numeric), `cadence_days` (int).
  - `AnomalyFlag` (`anomaly_flags`): `id`, `user_id`, `account_id`, `category`, `month`, `amount` (Numeric), `reason` (str).
  Add a module docstring line: "READ-ONLY. Never written. Column set is the minimal contract Phase 2 reads." **Dependency**: none. **Acceptance**: `uv run python -c "from app.backend_db.models import Transaction, MonthlySummary, BankAccount, Budget, BudgetAllocation, Product, User, RecurringCharge, AnomalyFlag"` exits 0; `uv run mypy app` passes. NOTE: If Phase 1 already added some of these, extend/verify instead of duplicating (no duplicate `__tablename__`).
[-] [X] T005 [P] Create audit helper `app/core/audit.py` with `async def record_audit(session: AsyncSession, *, user_id: int | None, action: str, detail: dict) -> None` that inserts an `AiAuditLog` row (import `AiAuditLog` from `app.features.audit.models`), serializing `detail` into `detail_json`, and flushes. Add module docstring citing Constitution III (audit every privileged action). **Dependency**: Phase 1 `AiAuditLog`. **Acceptance**: `uv run python -c "from app.core.audit import record_audit"` exits 0; mypy passes.
[-] [X] T006 Create LangGraph checkpointer infra `app/features/chat/checkpointer.py`:
  - `def _psycopg_conn_string() -> str`: build `postgresql://{user}:{password}@{host}:{port}/{db}` from `settings.postgres_*` (psycopg v3 form — NO `+asyncpg`).
  - `async def build_checkpointer() -> AsyncPostgresSaver`: create an `AsyncPostgresSaver` backed by a `psycopg_pool.AsyncConnectionPool` over `_psycopg_conn_string()`; return it (do not call setup here).
  - `async def setup_checkpointer(saver: AsyncPostgresSaver) -> None`: `await saver.setup()` (creates `checkpoints`, `checkpoint_blobs`, `checkpoint_writes` tables — these are AI-owned, auto-created).
  Add module docstring: checkpointer tables live in the OWN DB and are set up at startup. **Dependency**: T001. **Acceptance**: imports resolve; `uv run mypy app` passes. (Live setup is exercised by T00-integration in US1.)
[-] [X] T007 Wire application lifespan in `app/main.py`. Convert `create_app()` to attach a `lifespan` async context manager to `FastAPI(...)` that: on startup calls `build_checkpointer()` + `setup_checkpointer(...)` and stores the saver on `app.state.checkpointer`; on shutdown closes the pool. Import lazily inside the lifespan to avoid import cycles. Preserve existing router includes (`system.router`, `chat.router`). **Dependency**: T006. **Acceptance**: `uv run python -c "from app.main import app"` exits 0; existing `tests/features/system/test_probes.py` still passes.
[-] [X] T008 [P] Add a Testcontainers own-DB fixture and mock fixtures in `tests/conftest.py` (extend, do not break existing `client`/`auth_headers`):
  - `own_pg` (session-scoped): spins `PostgresContainer("postgres:16-alpine")`, runs `alembic upgrade head` against it (reuse the env-var pattern from `tests/integration/test_migrations.py`), yields an async engine/sessionmaker bound to it. Skips when Docker is unavailable (`pytest.importorskip` + `which("docker")`).
  - `mock_embedder` (fixture): monkeypatches `app.features.embed.service.embed_texts` to return a deterministic 768-length vector per input (e.g. hash-seeded), no network.
  - `mock_backend_session` (fixture): an in-memory/SQLite-or-Testcontainers `AsyncSession` seeded from `BackendBase.metadata` for read tests, OR a factory to insert fixture rows. Prefer the `own_pg` container with `BackendBase.metadata.create_all` for realism.
  Add a comment that no fixture performs real LLM/embedder calls. **Dependency**: T004. **Acceptance**: `uv run pytest tests -q --ignore=tests/integration` still passes (new fixtures unused yet).

**Checkpoint**: Foundation ready — user stories can now proceed.

---

## Phase 3: User Story 1 — Conversational financial assistant (Priority: P1) 🎯 MVP

**Goal**: A single `/internal/chat` SSE endpoint where a Maestro orchestrator classifies intent and routes to analysis / planning / recommendation / general, with persistent per-conversation memory, streaming replies, grounded (no-fabrication) analysis, and bounded context.

**Independent Test**: First-turn request (with `initial_context` + a spending question) streams a grounded reply citing the user's rows; a context-free follow-up on the same `conversation_id` is answered using remembered history — all with `USE_MOCK_LLM=1`.

**Cross-story note**: the planner and recommendation nodes call `app.features.plan.service` (US3) and `app.features.recommendations.service` (US4). Implement those nodes with a guarded `try/except ImportError` that returns a graceful "capability not yet available" message, so US1 is independently runnable/testable before US3/US4 land. US3/US4 include a task to verify the live wiring.

### Tests for User Story 1 (write FIRST, ensure they FAIL before implementation)

[-] [X] T009 [P] [US1] Unit test `tests/features/chat/test_maestro.py`: assert `classify_intent` (mock mode) maps sample messages to the correct literal intent (`"analysis" | "planning" | "recommendation" | "general"`) — e.g. "how much did I spend on food" → `"analysis"`, "help me budget" → `"planning"`, "which card should I get" → `"recommendation"`.
- [X] T010 [P] [US1] Unit test `tests/features/chat/test_analysis_agent.py`: given a seeded `mock_backend_session` with 3 transactions, assert the analysis node's reply (mock mode) references those rows in `state["message_references"]` and states no data when the session is empty (never invents a number).
- [X] T011 [P] [US1] Unit test `tests/features/chat/test_summarize.py`: build a state with 41 messages and assert `summarize_node` compresses the oldest into a single `SystemMessage` summary and that the trim wrapper keeps ≤ 20 messages in the LLM window.
- [X] T012 [P] [US1] Integration test `tests/integration/test_chat_memory.py` (Testcontainers, uses `own_pg`): POST first turn to `/internal/chat`, then POST a context-free follow-up with the same `conversation_id`; assert the second response reflects remembered state (checkpointer persisted the thread). Update the existing `tests/features/chat/test_chat.py` to the new `/internal/chat` contract (auth 401 without token; 200 + streamed body with token).

### Implementation for User Story 1

- [X] T013 [P] [US1] `app/features/chat/state.py`: define `ConversationState(TypedDict)` with keys `messages: Annotated[list[AnyMessage], add_messages]`, `user_context: dict`, `stage: str`, `intent: str`, `planner_answers: dict`, `questions_asked: int`, `message_references: list[dict]`. Import `add_messages` from `langgraph.graph.message`. **Acceptance**: imports resolve; mypy passes.
- [X] T014 [P] [US1] `app/features/chat/summarize.py`: `SUMMARY_THRESHOLD = 40`, `TRIM_LIMIT = 20`. `def needs_summary(state) -> bool` (`len(state["messages"]) > SUMMARY_THRESHOLD`); `async def summarize_node(state) -> dict` compressing oldest messages into one `SystemMessage` (mock mode: deterministic concatenation; real mode: LLM summarize via `get_chat_model`); `def trim_for_llm(messages) -> list` wrapping LangChain `trim_messages` to keep the last `TRIM_LIMIT`. **Dependency**: T013. **Acceptance**: T011 passes.
- [X] T015 [US1] `app/features/chat/agents/__init__.py` (empty) and `app/features/chat/agents/maestro.py`: `async def classify_intent(state: ConversationState) -> str` returning one of `"analysis"|"planning"|"recommendation"|"general"` (mock mode: keyword rules; real mode: single LLM classify call with trimmed context) and `async def maestro_node(state) -> dict` setting `state["intent"]`. **Dependency**: T013. **Acceptance**: T009 passes.
- [X] T016 [US1] `app/features/chat/agents/analysis.py`: `async def analysis_node(state) -> dict`. Reads backend via `get_backend_session` (query `Transaction`, `MonthlySummary`, `AnomalyFlag` for `state["user_context"]["user_id"]`), builds a grounded answer that cites the source rows into `state["message_references"]` (list of `{table, id}` dicts), appends an `AIMessage`, and NEVER fabricates figures (if no rows: reply "I don't have that data yet"). Mock mode returns a canned but data-derived reply. Prompts must exclude PII beyond supplied context. **Dependency**: T004, T013. **Acceptance**: T010 passes.
- [X] T017 [US1] `app/features/chat/agents/planner.py`: `async def planner_node(state) -> dict` that guards `from app.features.plan.service import next_question, generate_plan` in a `try/except ImportError`; drives the questionnaire (increment `state["questions_asked"]`, cap at 7), and on completion attaches a validated 100% allocation to the reply. On `ImportError` append an `AIMessage` "Budget planning is being set up." **Dependency**: T013. **Acceptance**: node importable; unit-tested via mock in T009 routing (full path validated in US3 T036).
- [X] T018 [US1] `app/features/chat/agents/recommendation.py`: `async def recommendation_node(state) -> dict` that guards `from app.features.recommendations.service import match` in `try/except ImportError`; calls `match(...)` with `get_own_session`, formats top-k products into the reply and `message_references`. On `ImportError` append "Recommendations are being set up." **Dependency**: T013. **Acceptance**: node importable (full path validated in US4 T045).
- [X] T019 [US1] `app/features/chat/graph.py`: `def build_graph(checkpointer)` building a `StateGraph(ConversationState)` with nodes `maestro`, `analysis`, `planner`, `recommendation`, `general` (general = plain LLM reply), plus a conditional summarize gate (route through `summarize_node` when `needs_summary`). Entry → (summarize?) → maestro → conditional edge on `state["intent"]` → the matching agent → END. Compile with `checkpointer=checkpointer`. **Dependency**: T014–T018. **Acceptance**: `build_graph(None)` compiles (or compiles with an in-memory saver); mypy passes.
- [X] T020 [US1] `app/features/chat/schemas.py`: REPLACE the stub schemas with internal-chat contracts: `ChatTurnRequest(conversation_id: str, user_id: int, message: str, is_first_turn: bool = False, initial_context: dict | None = None, refresh_context: bool = False)`. Keep a response note that the endpoint streams SSE (no JSON body model needed). **Dependency**: none. **Acceptance**: import resolves; mypy passes.
- [X] T021 [US1] `app/features/chat/service.py`: REPLACE `generate_reply` with `async def stream_chat(app, request: ChatTurnRequest) -> AsyncIterator[str]`. Loads/creates thread state keyed by `thread_id = request.conversation_id` (checkpointer from `app.state.checkpointer`); on `is_first_turn` seeds `user_context` from `initial_context`; on `refresh_context` reloads user context; invokes the compiled graph and yields SSE frames `f"data: {json}\n\n"` (token deltas + a terminal `data: [DONE]\n\n`). Mock mode yields a deterministic canned stream. Record a `record_audit(...)` entry per turn. **Dependency**: T005, T007, T019, T020. **Acceptance**: unit test streams frames without a real LLM call.
- [X] T022 [US1] `app/features/chat/router.py`: mount `router = APIRouter(prefix="/internal", tags=["chat"], dependencies=[Depends(require_token)])`; `@router.post("/chat")` returns `StreamingResponse(stream_chat(request.app, body), media_type="text/event-stream")`. Remove the old `/chat` JSON stub. **Dependency**: T021. **Acceptance**: T012 passes; app boots.
- [X] T023 [US1] Verify `app/main.py` still includes `chat.router` (now `/internal/chat`) after T007; adjust the include if the router symbol/path changed. **Dependency**: T022. **Acceptance**: `uv run pytest tests/features/chat -q` passes; `/internal/chat` 401s without a token.

**Checkpoint**: US1 is independently functional — analysis + memory + streaming + routing work; planner/recommendation degrade gracefully.

---

## Phase 4: User Story 2 — Automated financial insight pipelines (Priority: P2)

**Goal**: Deterministic, LLM-free analytics endpoints that COMPUTE and RETURN monthly summaries (with embedding), recurring charges, and anomaly flags for Django to persist. No backend writes.

**Independent Test**: Feed fixed transactions for a `(user_id, account_id, month)` and assert the returned summary, recurring charges, and anomaly flags are correct and byte-identical on repeat runs.

### Tests for User Story 2 (write FIRST)

- [X] T024 [P] [US2] `tests/features/analytics/test_monthly_summary.py`: seed fixture transactions in a backend session; assert totals/net/by-category are correct and that calling the job twice yields identical results; assert the embedding is produced via the injected `mock_embedder` (no network).
- [X] T025 [P] [US2] `tests/features/analytics/test_recurring_charges.py`: seed a merchant charge repeating monthly + several one-offs; assert only the recurring one is returned.
- [X] T026 [P] [US2] `tests/features/analytics/test_anomaly_detection.py`: seed one clear per-category outlier among normal values; assert exactly that flag is returned and normal spend is not flagged.

### Implementation for User Story 2

- [X] T027 [P] [US2] `app/features/analytics/schemas.py`: Pydantic result models `MonthlySummaryResult(user_id, account_id, month, total_income, total_expense, net, by_category: dict, embedding: list[float])`, `RecurringChargeResult(user_id, account_id, merchant, amount, cadence_days)`, `AnomalyFlagResult(user_id, account_id, category, month, amount, reason)`, plus request models `MonthlySummaryRequest(user_id, account_id, month)`, `AnomalyCheckRequest(user_id, account_id, month)`, `PostIngestionRequest(user_id, account_id, month)`. **Acceptance**: imports resolve; mypy passes.
- [X] T028 [P] [US2] `app/features/analytics/jobs/monthly_summary.py`: `async def compute_monthly_summary(session: AsyncSession, embed_fn, user_id: int, account_id: int, month: str) -> MonthlySummaryResult`. Deterministic SQL aggregation over `Transaction` (group by category, sum debits/credits) — NO LLM. Build a short summary text and set `embedding = (await embed_fn([text]))[0]`. `embed_fn` defaults to `embed_texts` but is injectable for tests. **Dependency**: T004, T027. **Acceptance**: T024 passes.
- [X] T029 [P] [US2] `app/features/analytics/jobs/recurring_charges.py`: `async def detect_recurring_charges(session, user_id, account_id) -> list[RecurringChargeResult]` — group `Transaction` by normalized merchant/description+amount, detect a regular cadence (e.g. ≥3 occurrences at ~constant day-gap), compute `cadence_days`. Deterministic. **Dependency**: T004, T027. **Acceptance**: T025 passes.
- [X] T030 [P] [US2] `app/features/analytics/jobs/anomaly_detection.py`: `async def detect_anomalies(session, user_id, account_id, month) -> list[AnomalyFlagResult]` — per-category outlier detection using `numpy` (e.g. z-score > 3 or IQR rule); `reason` explains the rule. Deterministic; returns `[]` for tiny samples. **Dependency**: T001, T004, T027. **Acceptance**: T026 passes.
- [X] T031 [US2] `app/features/analytics/service.py`: `async def run_post_ingestion(session, embed_fn, req: PostIngestionRequest) -> dict` orchestrating all three jobs and returning `{summary, recurring_charges, anomalies}`. **Dependency**: T028–T030. **Acceptance**: unit test returns all three sections.
- [X] T032 [US2] `app/features/analytics/router.py`: `router = APIRouter(prefix="/internal/analyze", tags=["analytics"], dependencies=[Depends(require_token)])` with `POST /post-ingestion`, `POST /monthly-summary`, `POST /anomaly-check`, each using `Depends(get_backend_session)` (read-only) and RETURNING results (writes nothing to backend). **Dependency**: T031. **Acceptance**: endpoints 401 without token; return 200 with computed payloads.
- [X] T033 [US2] Register the analytics router in `app/main.py` `create_app()` (`app.include_router(analytics_router)`). **Dependency**: T032. **Acceptance**: `uv run pytest tests/features/analytics -q` passes; `/internal/analyze/*` reachable.

**Checkpoint**: US1 and US2 both independently functional.

---

## Phase 5: User Story 3 — Guided budget planning (Priority: P2)

**Goal**: A stateless question generator and a plan generator (allocations summing to exactly 100%, validated), reachable via dedicated endpoints and via the chat planner node.

**Independent Test**: Call the question endpoint with partial context → get the next unanswered question; submit full answers to generate → allocations sum to exactly 100%.

### Tests for User Story 3 (write FIRST)

- [X] T034 [P] [US3] `tests/features/plan/test_plan_service.py`: assert `next_question` returns the next unanswered question and returns `None` once `questions_asked >= MAX_QUESTIONS (7)`; assert `generate_plan` output allocations sum to exactly `100` (use `Decimal`), and that generation is deterministic in mock mode.
- [X] T035 [P] [US3] `tests/features/plan/test_plan_router.py`: POST `/internal/plan/question` and `/internal/plan/generate` — assert 401 without token, 200 with token, and the 100%-sum invariant on the generate response.

### Implementation for User Story 3

- [X] T036 [P] [US3] `app/features/plan/schemas.py`: `PlanQuestion(id: str, text: str)`, `BudgetAllocation(category: str, percentage: Decimal)`, `NextQuestionRequest(user_context: dict, answers: dict, questions_asked: int)`, `GeneratePlanRequest(user_context: dict, answers: dict)`, `GeneratePlanResponse(allocations: list[BudgetAllocation])`. **Acceptance**: imports resolve; mypy passes.
- [X] T037 [US3] `app/features/plan/service.py`: `MAX_QUESTIONS = 7`; `async def next_question(user_context, answers, questions_asked) -> PlanQuestion | None` (returns the most relevant unanswered question, or `None` when complete or at the cap); `async def generate_plan(user_context, answers) -> list[BudgetAllocation]` producing allocations that MUST sum to exactly 100 — implement a normalization/validation step that asserts the sum before returning (raise if off). Mock mode: deterministic rule-based plan; real mode: LLM-assisted then re-normalized. **Dependency**: T036. **Acceptance**: T034 passes.
- [X] T038 [US3] `app/features/plan/router.py`: `router = APIRouter(prefix="/internal/plan", tags=["plan"], dependencies=[Depends(require_token)])`; `POST /question` → `next_question(...)`; `POST /generate` → `generate_plan(...)`. **Dependency**: T037. **Acceptance**: T035 passes.
- [X] T039 [US3] Register the plan router in `app/main.py`. **Dependency**: T038. **Acceptance**: `/internal/plan/*` reachable and token-guarded.
- [X] T040 [US3] Wire the chat planner node to the live service: confirm `app/features/chat/agents/planner.py` (T017) imports `next_question`/`generate_plan` successfully and the questionnaire path produces a validated 100% plan end-to-end. Add `tests/features/chat/test_planner_integration.py` asserting the routed planner path yields a 100%-sum plan in mock mode. **Dependency**: T017, T037. **Acceptance**: new test passes.

**Checkpoint**: US1–US3 independently functional.

---

## Phase 6: User Story 4 — Personalised product recommendations (Priority: P3)

**Goal**: RAG match over the own-DB `AiProblemStatement` knowledge base (pgvector cosine), returning top-k products with scores, logging each shown recommendation, with an admin seed utility. Reachable via endpoint and the chat recommendation node.

**Independent Test**: Query the match endpoint with a need → top-k products ranked by similarity; a log row is written per recommendation; empty result (not error) when nothing clears the threshold.

### Tests for User Story 4 (write FIRST)

- [X] T041 [P] [US4] `tests/integration/test_recommendations.py` (Testcontainers `own_pg`): seed a few `AiProblemStatement` rows with `mock_embedder` vectors; call `match(...)`; assert top-k ordering by similarity, that a `AiRecommendationLog` row is written per result, and that a no-match query returns `[]`.

### Implementation for User Story 4

- [X] T042 [P] [US4] `app/features/recommendations/schemas.py`: `MatchRequest(user_id: int, query: str, top_k: int = 5)`, `ProductMatch(product_id: int, product_name: str, similarity: float)`, `MatchResponse(matches: list[ProductMatch])`. **Acceptance**: imports resolve; mypy passes.
- [X] T043 [US4] `app/features/recommendations/service.py`: `SIMILARITY_THRESHOLD` const; `async def match(session: AsyncSession, embed_fn, user_id: int, query: str, top_k: int = 5) -> list[ProductMatch]` — embed the query via `embed_fn`, run pgvector cosine similarity on `AiProblemStatement.embedding` (`.cosine_distance(vec)`), join `Product` (read-only backend) for names, filter by threshold, and write one `AiRecommendationLog` per returned match (own DB, via `session`). `embed_fn` defaults to `embed_texts`, injectable for tests. **Dependency**: Phase 1 models, T004, T042. **Acceptance**: T041 passes.
- [X] T044 [US4] `app/features/recommendations/router.py`: `router = APIRouter(prefix="/internal/recommendations", tags=["recommendations"], dependencies=[Depends(require_token)])`; `POST /match` using `Depends(get_own_session)` → `match(...)`. Register the router in `app/main.py`. **Dependency**: T043. **Acceptance**: `/internal/recommendations/match` 401s without token, 200 with token.
- [X] T045 [US4] Wire the chat recommendation node to the live service: confirm `app/features/chat/agents/recommendation.py` (T018) imports and calls `match(...)`; add `tests/features/chat/test_recommendation_integration.py` (uses `own_pg`) asserting the routed path returns products. **Dependency**: T018, T043. **Acceptance**: new test passes.
- [X] T046 [US4] `app/features/recommendations/seed.py`: an **admin CLI** (not a route) — `async def seed(statements: list[dict]) -> int` and a `if __name__ == "__main__":` entry (`uv run python -m app.features.recommendations.seed <path.json>`) that reads problem statements, computes embeddings via `embed_texts`, and inserts `AiProblemStatement` rows into the own DB. **Dependency**: T043. **Acceptance**: running against `own_pg` inserts rows; a small unit test with `mock_embedder` asserts insert count.

**Checkpoint**: US1–US4 independently functional.

---

## Phase 7: User Story 5 — Integration & operational readiness (Priority: P3)

**Goal**: Deterministic, offline, mock-first test coverage against real Postgres, and CI gates enforcing security/quality. **Reconciliation note**: CI already runs mypy, TruffleHog secret scan (`--only-verified`), `pip-audit`, and Docker image build in `.github/workflows/ci.yml` — VERIFY and extend, do not re-add from scratch.

### Implementation for User Story 5

- [X] T047 [P] [US5] Verify `.github/workflows/ci.yml` runs, for the Phase 2 code: Ruff, Black `--check`, `mypy app`, unit tests (`pytest tests --ignore=tests/integration`), integration tests (`pytest tests/integration`), TruffleHog, `pip-audit`, and Docker build. Add any missing coverage (e.g. ensure the new `tests/integration/*` files run). Do not weaken existing gates. **Acceptance**: CI config includes all eight gates; a dry `uv run mypy app && uv run ruff check . && uv run black --check .` passes locally.
- [X] T048 [P] [US5] Confirm every Phase 2 endpoint is token-guarded: add `tests/features/test_auth_matrix.py` asserting 401 (no token) for `/internal/chat`, `/internal/plan/question`, `/internal/plan/generate`, `/internal/recommendations/match`, `/internal/analyze/post-ingestion`, `/internal/analyze/monthly-summary`, `/internal/analyze/anomaly-check`, and 200/normal for `/health`, `/ready`. **Dependency**: US1–US4 routers. **Acceptance**: test passes (SC-008).
- [X] T049 [P] [US5] Add a backend-DB Testcontainers stand-in helper to `tests/conftest.py` if not already covered by T008 (`BackendBase.metadata.create_all` on the `own_pg` container or a second container), used by analytics/analysis/recommendation integration tests. Ensure it is exercised READ-ONLY (no writes asserted). **Dependency**: T008. **Acceptance**: analytics/recommendation integration tests use it and pass.
- [X] T050 [P] [US5] Verify pre-existing tests still pass after the refactor: `tests/features/system/test_probes.py`, `tests/core/test_config.py`, `tests/integration/test_migrations.py`, and the updated `tests/features/chat/test_chat.py`. Fix any breakage caused by the `/chat` → `/internal/chat` move or the lifespan change. **Acceptance**: `uv run pytest tests -q` green (Docker-gated tests skip cleanly without Docker). (FR-029)
- [X] T051 [US5] Update `.env.example` and `docker-compose.yml` if Phase 1 embedding settings (`OLLAMA_BASE_URL`, `EMBEDDING_MODEL`) are referenced but absent; Phase 2 itself adds NO new env vars (checkpointer reuses `POSTGRES_*`). Update `Dockerfile` only if a new system dependency is required (none expected — `psycopg[binary]` ships wheels). **Acceptance**: `docker compose config` is valid; `.env.example` documents all vars read by `app/core/config.py`.

**Checkpoint**: Full suite green offline; CI gates enforced.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [X] T052 [P] Add advice-disclaimer + PII-safety guard shared helper used by analysis/planner/recommendation replies (`app/features/chat/guards.py`: `def with_disclaimer(text) -> str`, `def strip_pii(prompt) -> str`); apply in the agent nodes. **Acceptance**: unit test asserts financial-advice replies carry a disclaimer (FR-009) and prompts contain no injected PII.
- [X] T053 [P] Docstring/README pass: document the `/internal/*` surface and the read-only/return-to-Django contract in `README.md`. **Acceptance**: README lists all Phase 2 endpoints and the "service never writes backend tables" rule.
- [X] T054 Run the full quality gate set and fix residuals: `uv run ruff check . && uv run black --check . && uv run mypy app && uv run pytest tests -q`. **Acceptance**: all green.
- [X] T055 Cross-check spec Success Criteria SC-001…SC-011 against implemented behavior; note any gaps in `specs/002-phase2-agentic-pipelines/spec.md` "Notes". **Acceptance**: each SC maps to a passing test or documented follow-up.

---

## Dependencies & Execution Order

### Phase order
- **Setup (P1: T001–T003)** → **Foundational (P2: T004–T008)** → then user stories.
- **Foundational BLOCKS all user stories.**
- **US1 (T009–T023)**, **US2 (T024–T033)**, **US3 (T034–T040)**, **US4 (T041–T046)** can proceed in parallel by different developers after Foundational, EXCEPT the cross-story wiring tasks: **T040 needs T037**, **T045 needs T043**, and the planner/recommendation *nodes* (T017/T018) are written in US1 with graceful `ImportError` guards so US1 does not block on US3/US4.
- **US5 (T047–T051)** after the routers it asserts exist (US1–US4).
- **Polish (T052–T055)** last.

### User Story independence
- **US2 (analytics)** is fully standalone (no LLM, no chat) — best first parallel track.
- **US3 (plan)** and **US4 (recommendations)** are standalone services + endpoints; they additionally light up the US1 chat nodes via T040/T045.
- **US1 (chat)** is the P1 MVP; analysis + memory + streaming + routing are independent of US3/US4.

### Within each story
Tests first (must fail) → schemas/models → services/jobs → routers → main.py registration → integration.

## Parallel Execution Examples

```bash
# After Foundational (T004–T008), start three tracks in parallel:
# Track A (US1 chat):        T009,T010,T011 (tests) → T013,T014 → T015..T023
# Track B (US2 analytics):   T024,T025,T026 (tests) → T027 → T028,T029,T030 → T031..T033
# Track C (US3 plan):        T034,T035 (tests) → T036 → T037 → T038,T039

# Within US2, these are independent files → run in parallel:
Task: "T028 monthly_summary.py"
Task: "T029 recurring_charges.py"
Task: "T030 anomaly_detection.py"
```

## Implementation Strategy

- **MVP = Setup + Foundational + US1** → demo the conversational assistant (analysis path) with persistent memory and streaming.
- **Increment 2**: add US2 (analytics) — powers dashboards and enriches the analysis agent's grounding.
- **Increment 3**: add US3 (planner) and US4 (recommendations) — lights up the remaining Maestro routes.
- **Increment 4**: US5 hardening + Polish.

## Notes

- `[P]` = different files, no incomplete-task dependency → safe to parallelize.
- Backend DB is **read-only**; analytics/embeddings are **returned**, never written (Constitution IV; spec FR-024/030/031, SC-011).
- Every agent/service branches on `settings.use_mock_llm`; no test hits a real model/embedder/network.
- Commit after each task; keep each task's change scoped to its listed file(s).
