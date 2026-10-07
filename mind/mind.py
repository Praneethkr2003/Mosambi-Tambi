"""
mind/mind.py — Central intelligence and orchestration layer.

Mind operates in two logical phases:

  Phase A — plan()
      Understand the user context and goals; decide which matchers are relevant.
      This is the seam where keyword routing can later be replaced by an LLM router
      without touching the service layer or UI.

  Phase B — recommend_for_user()
      Read persisted relationships from the store (via the existing recommend() method),
      group results by capability/category, and return CategorizedRecommendations.

Critical guarantees:
  - Mind never computes matchmaking scores. It only reads the store.
  - Scores from different matchers are NEVER blended. Each CategorizedRecommendation
    carries evidence from exactly one matcher.
  - All provenance (matcher_id, relationship_ids, score, signals) is preserved in the
    Recommendation objects inside each category.
  - The existing recommend() method is unchanged; all existing tests continue to pass.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.models import EntityRef, Relationship, RecommendationCategory
from relationships.store import RelationshipStore


# ── Public data models ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Recommendation:
    """Single candidate recommendation produced from persisted relationship evidence.

    All provenance is preserved: matcher_id(s), relationship_id(s), score,
    and per-signal breakdown are accessible via the relationship store.
    """
    candidate: EntityRef
    score: float
    relationship_ids: tuple[str, ...]
    matcher_ids: tuple[str, ...]
    reasons: tuple[str, ...] = ()
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class CategorizedRecommendation:
    """A group of recommendations from one matcher / capability category.

    Scores within a category come from a single matcher. Mind never blends
    scores across categories — preserving matcher provenance is a hard requirement.
    """
    category: RecommendationCategory
    matcher_id: str
    items: list[Recommendation]
    rationale: str = ""


# ── Mind ──────────────────────────────────────────────────────────────────────

class Mind:
    """Reasoning and orchestration layer over persisted typed relationships.

    Mind does NOT calculate matchmaking scores.
    Mind DOES decide which matchers are relevant, read evidence from the store,
    and synthesize structured recommendations.
    """

    def __init__(self, relationship_store: RelationshipStore) -> None:
        self.relationship_store = relationship_store

    # ── Existing public API (unchanged) ───────────────────────────────────────

    def relationships_for(self, entity_type: str, entity_id: str) -> list[Relationship]:
        return self.relationship_store.get_for_entity(entity_type, entity_id)

    def recommend(
        self,
        entity_type: str,
        entity_id: str,
        *,
        context: dict[str, Any] | None = None,
        matcher_ids: set[str] | None = None,
        relationship_types: set[str] | None = None,
        top_n: int | None = 10,
    ) -> list[Recommendation]:
        """Return candidates supported by persisted relationships.

        The score used for ordering is the strongest persisted relationship score
        for that candidate. Mind does not invent a new weighted score across
        matchers. If multiple matchers support the same candidate, their evidence
        is retained in the recommendation.
        """
        requested_context = context or {}
        relationships = self.relationships_for(entity_type, entity_id)

        filtered = [
            r
            for r in relationships
            if self._matches_context(r, requested_context)
            and (matcher_ids is None or r.matcher_id in matcher_ids)
            and (relationship_types is None or r.relationship_type in relationship_types)
        ]

        grouped: dict[tuple[str, str], list[Relationship]] = {}
        for rel in filtered:
            candidate = self._other_entity(rel, entity_type, entity_id)
            if candidate is None:
                continue
            grouped.setdefault((candidate.type, candidate.id), []).append(rel)

        recommendations: list[Recommendation] = []
        for _, evidence in grouped.items():
            evidence.sort(key=lambda r: r.score, reverse=True)
            candidate = self._other_entity(evidence[0], entity_type, entity_id)
            if candidate is None:
                continue

            reasons = tuple(dict.fromkeys(
                reason for rel in evidence for reason in rel.explanation
            ))
            recommendations.append(
                Recommendation(
                    candidate=candidate,
                    score=evidence[0].score,
                    relationship_ids=tuple(r.relationship_id for r in evidence),
                    matcher_ids=tuple(dict.fromkeys(r.matcher_id for r in evidence)),
                    reasons=reasons,
                    context={"evidence_count": len(evidence)},
                )
            )

        recommendations.sort(key=lambda r: r.score, reverse=True)
        return recommendations if top_n is None else recommendations[:top_n]

    # ── Phase A — Plan ────────────────────────────────────────────────────────

    def plan(
        self,
        user_context: Any,          # UserContext — typed loosely to avoid circular import
        event_context: Any = None,  # EventContext | None
    ) -> list[str]:
        """Decide which matcher IDs are relevant for this user's goals.

        Returns a stable, ordered list of matcher IDs. This method is the seam
        where an LLM-based router can replace or augment keyword routing in a
        future phase — the service layer and UI do not need to change.

        Rules:
          - Only matchers whose declared goal_types overlap the user's inferred
            goals are included.
          - Matchers that require event context are excluded when none is provided.
        """
        from core.context import infer_goal_types
        from registry import MATCHER_CAPABILITIES, get_matchers_for_goals

        goal_types = infer_goal_types(user_context.goals)
        candidates = get_matchers_for_goals(goal_types)

        return [
            mid for mid in candidates
            if not (MATCHER_CAPABILITIES[mid].needs_event_context and event_context is None)
        ]

    # ── Phase B — Synthesize ──────────────────────────────────────────────────

    def recommend_for_user(
        self,
        user_context: Any,          # UserContext
        event_context: Any = None,  # EventContext | None
        *,
        top_n: int = 5,
    ) -> list[CategorizedRecommendation]:
        """Synthesize categorized recommendations from persisted relationship evidence.

        For each matcher selected by plan(), reads the store via the existing
        recommend() method and wraps results in a CategorizedRecommendation.

        Guarantees:
          - Scores from different matchers are NEVER blended — each category
            contains evidence from exactly one matcher.
          - Matcher provenance (matcher_id, relationship_ids, score) is fully
            preserved in every Recommendation inside each category.
          - If a matcher found no results above threshold, its category is omitted.
        """
        from core.context import infer_goal_types, GOAL_LABELS
        from registry import MATCHER_CAPABILITIES

        matched_ids = self.plan(user_context, event_context)
        goal_types  = infer_goal_types(user_context.goals)
        results: list[CategorizedRecommendation] = []

        for matcher_id in matched_ids:
            cap = MATCHER_CAPABILITIES[matcher_id]

            # Build the context filter for the store query
            ctx_filter: dict[str, Any] = {}
            if event_context and cap.needs_event_context:
                ctx_filter = {"event_id": event_context.event_id}

            recs = self.recommend(
                cap.seeker_entity_type,
                user_context.user_id,
                context=ctx_filter,
                matcher_ids={matcher_id},
                top_n=top_n,
            )
            if not recs:
                continue

            # Build a deterministic rationale string from overlapping goals
            active_goal_labels = [
                GOAL_LABELS[gt] for gt in cap.goal_types if gt in goal_types
            ]
            if active_goal_labels:
                rationale = "Based on your goal to " + " and ".join(active_goal_labels)
            elif user_context.domains:
                rationale = f"Relevant to your work in {', '.join(user_context.domains[:2])}"
            else:
                rationale = "Relevant to your profile"

            results.append(CategorizedRecommendation(
                category=cap.category,
                matcher_id=matcher_id,
                items=recs,
                rationale=rationale,
            ))

        return results

    # ── Private helpers (unchanged) ───────────────────────────────────────────

    @staticmethod
    def _other_entity(
        relationship: Relationship, entity_type: str, entity_id: str
    ) -> EntityRef | None:
        current = (entity_type, entity_id)
        source  = (relationship.source.type, relationship.source.id)
        target  = (relationship.target.type, relationship.target.id)
        if source == current:
            return relationship.target
        if target == current:
            return relationship.source
        return None

    @staticmethod
    def _matches_context(relationship: Relationship, requested: dict[str, Any]) -> bool:
        """Require every requested context key to match the relationship context.

        Intentionally exact and predictable. Context keys can be extended with
        event/session/organization scope without changing Mind's public API.
        """
        return all(
            relationship.context.get(key) == value
            for key, value in requested.items()
        )
