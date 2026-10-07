"""
registry.py — Matcher registry and capability routing table.

MATCHERS                    : existing singleton matcher instances (unchanged).
MATCHER_CAPABILITIES        : maps each matcher_id to its declared capabilities,
                              entity type, category, and context requirements.
get_all_matchers_for_context: returns all matchers whose context needs are met.

The routing table is now purely context-driven — not goal-driven.
Mind invokes every registered matcher whose requirements are satisfied.
Adding a new matcher requires only one entry in MATCHER_CAPABILITIES;
no changes to Mind, the service layer, or the UI.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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


# ── Capability routing table ──────────────────────────────────────────────────

@dataclass(frozen=True)
class MatcherCapability:
    """Declares what a matcher can do and what context it requires.

    The `capabilities` list is a human-readable registry of what this matcher
    contributes to recommendation. It is NOT a filter on user-stated goals.

    Attributes:
        capabilities        : list of capability strings this matcher provides.
                              Used for documentation and future routing logic.
                              Example: ["people_discovery", "event_attendee_matching"]
        seeker_entity_type  : entity type string used when querying the store
                              ("USER" or "ORGANIZATION").
        category            : RecommendationCategory default for this matcher.
                              The RecommendationEngine may further refine this.
        needs_event_context : if True, this matcher is only invoked when an
                              EventContext is provided.
    """
    capabilities: tuple[str, ...]
    seeker_entity_type: str
    category: RecommendationCategory
    needs_event_context: bool = False


MATCHER_CAPABILITIES: dict[str, MatcherCapability] = {
    "MM-EVENT-001": MatcherCapability(
        capabilities=("people_discovery", "event_attendee_matching"),
        seeker_entity_type="USER",
        category=RecommendationCategory.PEOPLE,
        needs_event_context=True,
    ),
    "MM-ORG-001": MatcherCapability(
        capabilities=("organization_relevance", "company_matching", "investor_relevance"),
        seeker_entity_type="ORGANIZATION",
        category=RecommendationCategory.COMPANIES,
        needs_event_context=False,
    ),
}


def get_all_matchers_for_context(event_context: Any = None) -> list[str]:
    """Return all registered matcher IDs whose context requirements are satisfied.

    This is the primary routing function used by Mind.plan() and service.run_for_user().
    It is profile-driven — not goal-driven. Every matcher whose requirements are met
    is included, regardless of any user-stated objectives.

    The seam for future LLM-based selective routing: replace this function body
    with an LLM call. The callers (Mind, service) do not need to change.
    """
    return [
        mid for mid, cap in MATCHER_CAPABILITIES.items()
        if not (cap.needs_event_context and event_context is None)
    ]


# ── Backward compatibility ────────────────────────────────────────────────────
# kept for any code or tests that still reference get_matchers_for_goals.
# GoalType and infer_goal_types remain available in core.context for internal use.

def get_matchers_for_goals(goal_types: set[str]) -> list[str]:
    """Legacy helper: returns matchers by goal type overlap.

    Retained for backward compatibility and internal use.
    The primary orchestration path uses get_all_matchers_for_context() instead.
    Goal types no longer drive the primary recommendation flow.
    """
    from core.context import GoalType
    _GOAL_TO_CAPABILITY: dict[str, set[str]] = {
        GoalType.FIND_PEOPLE:        {"people_discovery", "event_attendee_matching"},
        GoalType.FIND_COLLABORATORS: {"people_discovery", "event_attendee_matching"},
        GoalType.FIND_COMPANIES:     {"organization_relevance", "company_matching"},
        GoalType.FIND_INVESTORS:     {"organization_relevance", "investor_relevance"},
        GoalType.FIND_OPPORTUNITIES: {"organization_relevance", "company_matching"},
    }
    wanted: set[str] = set()
    for gt in goal_types:
        wanted |= _GOAL_TO_CAPABILITY.get(gt, set())

    return [
        mid for mid, cap in MATCHER_CAPABILITIES.items()
        if wanted & set(cap.capabilities)
    ]
