"""Single source of truth for Maestro routes and structured decisions."""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


@dataclass(frozen=True)
class RouteSpec:
    """One user-facing capability and its graph destination.

    Route descriptions live here instead of being repeated inside a prompt,
    parser, and graph mapping. Adding or changing a capability therefore has
    one catalogue entry plus the node implementation itself.
    """

    name: str
    graph_node: str
    description: str
    mock_phrases: tuple[str, ...] = ()


ROUTE_SPECS = (
    RouteSpec(
        name="analysis",
        graph_node="analysis",
        description=(
            "Questions answered from the user's existing financial data, such as spending, "
            "income, balances, transactions, breakdowns, and savings capacity."
        ),
        mock_phrases=(
            "spend",
            "spent",
            "expense",
            "transaction",
            "how much",
            "income",
            "salary",
            "balance",
            "statement",
            "save per month",
            "saving per month",
            "savings projection",
        ),
    ),
    RouteSpec(
        name="planning",
        graph_node="planner_ask",
        description=(
            "Building a new household budget or spending plan through the budget questionnaire."
        ),
        mock_phrases=("budget", "plan", "spending plan", "allocate", "allocation", "planning"),
    ),
    RouteSpec(
        name="investment_planning",
        graph_node="investment_plan",
        description=(
            "Planning how to invest remaining money using curated gold, funds, and currencies, "
            "including current price checks and illustrative allocations."
        ),
        mock_phrases=(
            "invest",
            "remaining money",
            "investable amount",
            "buy gold",
            "gold price",
            "fund price",
            "fund nav",
            "exchange rate",
            "currency price",
        ),
    ),
    RouteSpec(
        name="recommendation",
        graph_node="recommendation",
        description=("Comparing or choosing curated banking products such as accounts and cards."),
        mock_phrases=(
            "recommend",
            "product",
            "card",
            "which account",
            "best account",
            "savings account",
        ),
    ),
    RouteSpec(
        name="general",
        graph_node="general",
        description=(
            "Greetings, capability questions, and personal-finance conversation that does not "
            "need a specialist workflow or the user's stored data."
        ),
    ),
)

ROUTES_BY_NAME = {spec.name: spec for spec in ROUTE_SPECS}
_MOCK_ROUTE_PRIORITY = (
    "investment_planning",
    "analysis",
    "recommendation",
    "planning",
    "general",
)


def route_catalogue() -> str:
    """Render the active capability catalogue for the Maestro system prompt."""

    return "\n".join(f"- {spec.name}: {spec.description}" for spec in ROUTE_SPECS)


class MaestroRoutingDecision(BaseModel):
    """Validated routing and scope decision returned by Maestro."""

    model_config = ConfigDict(extra="forbid")

    outcome: Literal["route", "clarify", "refuse"] = Field(
        description=(
            "route for a clear supported request, clarify for an ambiguous supported request, "
            "or refuse for an out-of-scope, illegal, or harmful request"
        )
    )
    route: str | None = Field(
        default=None,
        description="Exactly one route name from the supplied capability catalogue",
        json_schema_extra={"enum": [*ROUTES_BY_NAME, None]},
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence that the outcome and route fit the latest message in context",
    )
    clarification_question: str | None = Field(
        default=None,
        max_length=180,
        description=(
            "One short natural question when outcome is clarify; do not expose internal route names"
        ),
    )

    @model_validator(mode="after")
    def _validate_outcome_fields(self) -> "MaestroRoutingDecision":
        if self.outcome != "route":
            # Some OpenAI-compatible providers populate every schema field.
            # A route on clarify/refuse is irrelevant, so discard it instead
            # of losing the useful outcome and question to a parse failure.
            self.route = None
        if self.outcome == "route" and not self.route:
            raise ValueError("route is required when outcome is route")
        if self.outcome == "route" and self.route not in ROUTES_BY_NAME:
            raise ValueError("route must come from the configured capability catalogue")
        if self.outcome == "clarify" and not self.clarification_question:
            raise ValueError("clarification_question is required when outcome is clarify")
        if self.outcome != "clarify":
            self.clarification_question = None
        return self


DEFAULT_CLARIFICATION = (
    "Do you want to check your spending, build a budget, compare bank products, "
    "or plan an investment?"
)


def mock_routing_decision(message: str, history: str = "") -> MaestroRoutingDecision:
    """Deterministic offline substitute; never used when a real LLM is enabled.

    Mock mode needs enough routing behavior to exercise each graph branch in
    CI without network access. These phrases are test-fixture behavior, not a
    production fallback: an invalid or unavailable live Maestro asks for
    clarification instead of scanning hardcoded user words.
    """

    lower = message.casefold()
    for name in _MOCK_ROUTE_PRIORITY:
        spec = ROUTES_BY_NAME[name]
        if any(phrase in lower for phrase in spec.mock_phrases):
            return MaestroRoutingDecision(outcome="route", route=spec.name, confidence=1.0)

    if history:
        lower_history = history.casefold()
        for name in _MOCK_ROUTE_PRIORITY:
            spec = ROUTES_BY_NAME[name]
            if any(phrase in lower_history for phrase in spec.mock_phrases):
                return MaestroRoutingDecision(outcome="route", route=spec.name, confidence=0.8)

    return MaestroRoutingDecision(outcome="route", route="general", confidence=1.0)
