"""
registry.py — Matcher registry and capability routing table.

MATCHERS          : existing singleton dict of matcher instances.
MATCHER_CAPABILITIES : maps each matcher_id to its declared goals, entity type,
                       and recommendation category. This is the routing table Mind
                       uses in plan() — adding a new matcher requires one entry here.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.context import GoalType
from core.models import RecommendationCategory
from matchers.event.matcher import EventMatchmaker
from matchers.organization.matcher import OrganizationMatchmaker


BASE = Path(__file__).resolve().parent

# ── Existing matcher instances (unchanged) ────────────────────────────────────

MATCHERS = {
    "MM-EVENT-001": EventMatchmaker(str(BASE / "matchers/event/config.json")),
    "MM-ORG-001":   OrganizationMatchmaker(),
}


def get_matchmaker(matcher_id: str):
    try:
        return MATCHERS[matcher_id]
    except KeyError as exc:
        raise ValueError(f"Unknown matcher_id: {matcher_id!r}") from exc


# ── Capability routing table ───────────────────────────────────────────────────

@dataclass(frozen=True)
class MatcherCapability:
    """Declares what a matcher can do and which goal types activate it.

    Adding a future matcher (e.g. MM-INVESTOR-001) requires only a new entry
    in MATCHER_CAPABILITIES below — no changes to Mind or the service layer.

    Attributes:
        goal_types          : set of GoalType constants that trigger this matcher.
        seeker_entity_type  : entity type string used when querying the store
                              ("USER" or "ORGANIZATION").
        category            : RecommendationCategory placed in CategorizedRecommendation.
        needs_event_context : if True, Mind will NOT invoke this matcher when no
                              EventContext is provided.
    """
    goal_types: frozenset[str]
    seeker_entity_type: str
    category: RecommendationCategory
    needs_event_context: bool = False


MATCHER_CAPABILITIES: dict[str, MatcherCapability] = {
    "MM-EVENT-001": MatcherCapability(
        goal_types=frozenset({GoalType.FIND_PEOPLE, GoalType.FIND_COLLABORATORS}),
        seeker_entity_type="USER",
        category=RecommendationCategory.PEOPLE,
        needs_event_context=True,
    ),
    "MM-ORG-001": MatcherCapability(
        goal_types=frozenset({GoalType.FIND_COMPANIES, GoalType.FIND_INVESTORS}),
        seeker_entity_type="ORGANIZATION",
        category=RecommendationCategory.COMPANIES,
        needs_event_context=False,
    ),
}


def get_matchers_for_goals(goal_types: set[str]) -> list[str]:
    """Return matcher IDs whose declared goal_types overlap the requested set.

    The returned order is stable (dict insertion order) so that Mind produces
    deterministic results.
    """
    return [
        mid for mid, cap in MATCHER_CAPABILITIES.items()
        if cap.goal_types & goal_types
    ]
