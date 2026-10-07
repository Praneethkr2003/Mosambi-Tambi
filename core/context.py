"""
core/context.py — Canonical user and event context models.

UserContext is the single source of truth for a user's profile within Mosambi.
It is created once and passed through Mind into matcher-specific profile adapters.
The matchers themselves never see UserContext — they receive the dict format they
have always expected.

Design rules enforced here:
  - Fields shared across two or more matchers live on UserContext directly.
  - Matcher-specific fields live in `extra` until promoted.
  - `extra` is a compatibility bridge, not an unstructured dumping ground.
    Document every expected key in the docstring.
  - GoalType constants and keyword routing live here so the routing seam is
    in one place, replaceable by an LLM router without touching Mind or the
    service layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Goal type constants ───────────────────────────────────────────────────────

class GoalType:
    """String constants for recommendation categories.

    Kept as plain class attributes (not an Enum) so they serialize trivially
    to JSON and Streamlit session state.
    """
    FIND_PEOPLE         = "find_people"
    FIND_INVESTORS      = "find_investors"
    FIND_COMPANIES      = "find_companies"
    FIND_COLLABORATORS  = "find_collaborators"
    FIND_OPPORTUNITIES  = "find_opportunities"

    ALL: tuple[str, ...] = (
        "find_people", "find_investors", "find_companies",
        "find_collaborators", "find_opportunities",
    )


# ── Goal routing ──────────────────────────────────────────────────────────────
# This is the ONLY place that maps keyword strings → GoalType.
# Replace or augment with an LLM-based router without touching Mind or Service.

_GOAL_KEYWORDS: dict[str, list[str]] = {
    GoalType.FIND_INVESTORS:    ["invest", "investor", "funding", "capital",
                                 "fundrais", "vc", "fund"],
    GoalType.FIND_COMPANIES:    ["compan", "organizat", "corporat", "enterprise",
                                 "partner", "firm"],
    GoalType.FIND_COLLABORATORS:["collaborat", "co-found", "technical", "developer",
                                 "engineer", "team"],
    GoalType.FIND_PEOPLE:       ["people", "person", "attendee", "meet",
                                 "network", "connect"],
    GoalType.FIND_OPPORTUNITIES:["opportunit", "project", "initiative", "program"],
}

# Human-readable labels used in UI and rationale strings
GOAL_LABELS: dict[str, str] = {
    GoalType.FIND_PEOPLE:        "meet people",
    GoalType.FIND_INVESTORS:     "find investors",
    GoalType.FIND_COMPANIES:     "find companies & partners",
    GoalType.FIND_COLLABORATORS: "find collaborators",
    GoalType.FIND_OPPORTUNITIES: "find opportunities",
}


def infer_goal_types(goals: list[str]) -> set[str]:
    """Map free-text goal strings → set of GoalType constants.

    Explicit GoalType constants (e.g. from a UI multiselect that already stores
    them) pass through unchanged. Free-text strings are matched case-insensitively
    against keyword stems.

    Falls back to FIND_PEOPLE when nothing matches — ensures Mind always has
    at least one capability to invoke.
    """
    if not goals:
        return {GoalType.FIND_PEOPLE}

    inferred: set[str] = set()
    for goal in goals:
        g = goal.strip().lower()
        # Explicit GoalType constant → pass through directly
        if g in _GOAL_KEYWORDS:
            inferred.add(g)
            continue
        # Keyword matching
        for goal_type, keywords in _GOAL_KEYWORDS.items():
            if any(kw in g for kw in keywords):
                inferred.add(goal_type)

    return inferred or {GoalType.FIND_PEOPLE}


# ── Canonical models ──────────────────────────────────────────────────────────

@dataclass
class UserContext:
    """Canonical profile for a Mosambi user. Enter once, reuse everywhere.

    Top-level fields are shared across at least two matchers.
    Matcher-specific fields go in `extra` until promoted.

    Known `extra` keys (consumed by to_org_profile / MM-ORG-001):
        stakeholder_type (str)         — "Investor", "Attendee", "Partner", etc.
        country (str)                  — home country
        city (str)                     — home city
        operating_countries (list[str])— where the org operates
        industry (list[str])           — industry focus
        supply_chain_stage (list[int]) — stages 1–7
        stage (str)                    — "Seed", "Series A", etc.
        stage_focus (list[str])        — for investors: preferred stages
        fundraising_toggle (bool)      — actively fundraising?
        fundraising_amount (int|None)  — USD amount
        ticket_range (list[int]|None)  — [min, max] for investor ticket size
        support_offered (list[str])    — what this entity can offer others
        sdg_goals (list[str])          — e.g. ["SDG 7", "SDG 13"]
        needs (list[str])              — additional needs beyond goals
    """
    user_id: str
    name: str

    # Shared identity
    roles: list[str] = field(default_factory=list)
    experience_level: str = ""

    # Shared professional context
    domains: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)

    # Shared interests
    interests: list[str] = field(default_factory=list)

    # What the user wants — free-text or GoalType constants
    goals: list[str] = field(default_factory=list)

    # Compatibility bridge for matcher-specific fields
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class EventContext:
    """Temporary, session-scoped context for a specific event.

    Kept separate from UserContext because user context is persistent while
    event context is ephemeral (the user joins a different event next week).
    """
    event_id: str
    name: str = ""
    themes: list[str] = field(default_factory=list)
    location: str = ""


# ── Profile adapters ──────────────────────────────────────────────────────────
# These are the ONLY functions that translate UserContext into matcher-specific
# input dicts. The matchers never know about UserContext.

def to_event_profile(
    ctx: UserContext,
    event_ctx: EventContext | None = None,
) -> dict[str, Any]:
    """Convert UserContext → MM-EVENT-001 input dict.

    Maps to the field names that EventMatchmaker.score() reads:
        professional_domain  ← ctx.domains
        interests            ← ctx.interests
        role                 ← ctx.roles[0]  (primary role)
        networking_objective ← ctx.roles + ctx.domains  (who the user IS)
        skills               ← ctx.skills
        experience_level     ← ctx.experience_level
        event_interest       ← event_ctx.themes + top ctx.interests

    networking_objective is derived from roles and domains rather than
    user-stated goals. This means:
      - It carries signal even when goals=[] (proactive mode).
      - It reflects what the user DOES, not what they SAY they want.
      - The EventMatchmaker's Jaccard scorer handles the rest.
    These are signals, not rules — the scorer determines compatibility.
    No hard-coded role→goal mappings are applied here.
    """
    # Seed event_interest from event themes; supplement with user interests
    event_interest: list[str] = list(event_ctx.themes) if event_ctx else []
    for interest in ctx.interests[:3]:
        if interest not in event_interest:
            event_interest.append(interest)

    # networking_objective: signal about who this person is.
    # Roles and domains carry identity signal without asserting intent.
    networking_objective = list(ctx.roles) + list(ctx.domains)

    return {
        "id":                   ctx.user_id,
        "name":                 ctx.name,
        "professional_domain":  ctx.domains,
        "interests":            ctx.interests,
        "role":                 ctx.roles[0] if ctx.roles else "Other",
        "networking_objective": networking_objective,
        "skills":               ctx.skills,
        "experience_level":     ctx.experience_level or "Mid-level",
        "event_interest":       event_interest,
    }


def to_org_profile(ctx: UserContext) -> dict[str, Any]:
    """Convert UserContext → MM-ORG-001 input dict.

    Reads org-specific fields from ctx.extra; canonical fields come from ctx.
    Maps to the field names that compute_match_score() reads in scoring.py.
    """
    x = ctx.extra
    return {
        "id":                   ctx.user_id,
        "name":                 ctx.name,
        "entity_type":          "ORGANIZATION",
        "stakeholder_type":     x.get("stakeholder_type", "Attendee"),
        "domain":               ctx.domains,
        "industry":             x.get("industry", []),
        "city":                 x.get("city"),
        "country":              x.get("country"),
        "operating_countries":  x.get("operating_countries", []),
        "supply_chain_stage":   x.get("supply_chain_stage", []),
        "stage":                x.get("stage"),
        "stage_focus":          x.get("stage_focus", []),
        "fundraising_toggle":   x.get("fundraising_toggle", False),
        "fundraising_amount":   x.get("fundraising_amount"),
        "ticket_range":         x.get("ticket_range"),
        # goals become needs so existing scoring can use them
        "needs":                list(ctx.goals) + x.get("needs", []),
        "support_offered":      x.get("support_offered", []),
        "sdg_goals":            x.get("sdg_goals", []),
    }


# ── Progressive completion hints ──────────────────────────────────────────────

# Maps goal type → list of (field_key, human reason).
# field_key is checked against UserContext attributes AND ctx.extra.
_FIELD_HINTS: dict[str, list[tuple[str, str]]] = {
    GoalType.FIND_INVESTORS: [
        ("country",            "Helps match geography with investor focus regions"),
        ("supply_chain_stage", "Helps investors assess your value-chain position"),
        ("fundraising_toggle", "Signals active fundraising intent to investors"),
    ],
    GoalType.FIND_COMPANIES: [
        ("country",            "Improves geography-based company matching"),
        ("supply_chain_stage", "Identifies complementary supply-chain partners"),
        ("industry",           "Narrows company domain alignment"),
    ],
    GoalType.FIND_PEOPLE: [
        ("experience_level",   "Helps match seniority for networking"),
        ("interests",          "Core signal for interest-overlap scoring"),
    ],
    GoalType.FIND_COLLABORATORS: [
        ("skills",             "Primary signal for collaborator matching"),
        ("experience_level",   "Helps match technical seniority"),
    ],
}


def missing_fields(ctx: UserContext, goal_types: set[str]) -> list[str]:
    """Return human-readable hints for fields that would improve match quality.

    Checks only the fields that matter for the requested goal types.
    Returns an empty list when the profile is complete enough.
    """
    hints: list[str] = []
    seen: set[str] = set()

    for goal_type in goal_types:
        for field_key, reason in _FIELD_HINTS.get(goal_type, []):
            if field_key in seen:
                continue
            seen.add(field_key)
            # Check canonical attributes first, then extra
            value = getattr(ctx, field_key, None) or ctx.extra.get(field_key)
            if not value:
                label = field_key.replace("_", " ").title()
                hints.append(f"**{label}** — {reason}")

    return hints
