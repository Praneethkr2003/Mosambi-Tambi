"""
mind/mind.py — Central intelligence and orchestration layer.

Mind operates in two phases:

  Phase A — plan()
      Profile-driven capability selection. Invokes every registered matcher
      whose context requirements are satisfied. Does NOT require user-stated
      goals. This is the seam where an LLM-based selective router can replace
      the deterministic logic without touching the service layer or UI.

  Phase B — recommend_for_user()
      Gathers relationship evidence from the store, delegates to
      RecommendationEngine for categorization and explanation, and returns
      a ranked list of RecommendedCandidates.

Critical guarantees (unchanged):
  - Mind never computes matchmaking scores.
  - Scores from different matchers are NEVER blended.
    relevance_score = max(evidence.score) per candidate.
  - All provenance is preserved: matcher_id, relationship_id, signals.
  - The existing recommend() method is byte-for-byte unchanged.
    All 6 original tests continue to pass.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.models import EntityRef, Relationship, RecommendationCategory
from relationships.store import RelationshipStore


# ── Legacy public models (unchanged — existing tests import these) ─────────────

@dataclass(frozen=True)
class Recommendation:
    """Single candidate recommendation from persisted relationship evidence.
    Used by the existing recommend() method and its tests.
    """
    candidate: EntityRef
    score: float
    relationship_ids: tuple[str, ...]
    matcher_ids: tuple[str, ...]
    reasons: tuple[str, ...] = ()
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class CategorizedRecommendation:
    """Legacy grouped recommendation model — retained for backward compatibility.
    New code should use RecommendedCandidate from mind.recommendation instead.
    """
    category: RecommendationCategory
    matcher_id: str
    items: list[Recommendation]
    rationale: str = ""


# ── Mind ──────────────────────────────────────────────────────────────────────

class Mind:
    """Central intelligence and orchestration layer.

    Mind does NOT calculate matchmaking scores.
    Mind DOES select capabilities, gather evidence, and synthesize
    structured, explained recommendations.
    """

    def __init__(self, relationship_store: RelationshipStore) -> None:
        self.relationship_store = relationship_store

    # ── Existing public API — byte-for-byte unchanged ─────────────────────────

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

        The score used for ordering is the strongest persisted relationship
        score for that candidate. Mind does not invent a new weighted score
        across matchers. If multiple matchers support the same candidate,
        their evidence is retained in the recommendation.
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
        user_context: Any,          # UserContext
        event_context: Any = None,  # EventContext | None
    ) -> list[str]:
        """Select which matcher IDs to invoke for this user and context.

        Profile-driven — does NOT require user-stated goals.
        Returns every registered matcher whose context requirements are met.

        Rules:
          - If event_context is None, matchers that need_event_context are excluded.
          - All other matchers are always included.
          - User goals (if present) are ignored here — they are an optional
            internal signal only, not a routing gate.

        LLM seam: replace this method body with an LLM call to enable
        selective, reasoning-based capability routing without changing callers.
        """
        from registry import get_all_matchers_for_context
        return get_all_matchers_for_context(event_context)

    # ── Phase B — Synthesize ──────────────────────────────────────────────────

    def recommend_for_user(
        self,
        user_context: Any,              # UserContext
        event_context: Any = None,      # EventContext | None
        *,
        candidate_pool: list[dict] | None = None,
        top_n: int = 10,
    ) -> list:  # list[RecommendedCandidate]
        """Synthesize proactive, categorized recommendations from persisted evidence.

        Does NOT require user-stated goals. Mind determines which matchers to
        invoke purely from the user's profile and the available context.

        Steps:
          1. plan() — select relevant matchers (profile-driven).
          2. Gather relationship evidence from the store for each matcher.
          3. Delegate to RecommendationEngine for dedup, categorization,
             explanation, and ranking.
          4. Return top_n RecommendedCandidates sorted by relevance_score desc.

        Guarantees:
          - relevance_score = max(single-matcher score) — never blended.
          - All provenance (matcher_id, signals, relationship_id) preserved.
          - Categories are system-generated from candidate metadata.
          - Explanations are evidence-based — nothing hallucinated.

        Args:
            user_context   : canonical UserContext (goals field optional / may be empty).
            event_context  : EventContext if the user is currently in an event.
            candidate_pool : all candidate profiles for metadata lookup.
                             Typically EVENT_ATTENDEES + ORGANIZATIONS.
            top_n          : maximum number of candidates to return.
        """
        from registry import MATCHER_CAPABILITIES
        from mind.recommendation import RecommendationEngine

        matched_ids = self.plan(user_context, event_context)

        # Gather all relevant relationship evidence from the store
        all_rels: list[Relationship] = []
        for matcher_id in matched_ids:
            cap = MATCHER_CAPABILITIES[matcher_id]

            # Context filter for the store query
            ctx_filter: dict[str, Any] = {}
            if event_context and cap.needs_event_context:
                ctx_filter = {"event_id": event_context.event_id}

            rels = self.relationships_for(cap.seeker_entity_type, user_context.user_id)
            filtered = [
                r for r in rels
                if r.matcher_id == matcher_id
                and self._matches_context(r, ctx_filter)
            ]
            all_rels.extend(filtered)

        if not all_rels:
            return []

        # Delegate to RecommendationEngine — stateless, replaceable
        engine = RecommendationEngine()
        candidates = engine.build(all_rels, user_context, candidate_pool or [])
        return candidates[:top_n]

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
        """Require every requested context key to match the relationship context."""
        return all(
            relationship.context.get(key) == value
            for key, value in requested.items()
        )
