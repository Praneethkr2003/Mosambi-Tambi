"""
service.py — Matchmaking service layer.

Preserves the existing run_pair() and rank_pool() methods unchanged.
Adds run_for_user() which orchestrates the full scoring pass for a UserContext:
  1. Asks Mind.plan() which matchers are relevant.
  2. Converts UserContext → matcher-specific profile dicts via adapters.
  3. Calls rank_pool() for each relevant matcher (matchers unchanged).
  4. Returns results keyed by matcher_id.

The matchers never see UserContext. The adapters are the only translation layer.
"""
from __future__ import annotations

from core.relationship import to_relationship
from relationships.store import RelationshipStore
from registry import get_matchmaker


class MatchmakingService:
    def __init__(self, relationship_store: RelationshipStore) -> None:
        self.relationship_store = relationship_store

    def run_pair(
        self,
        matcher_id: str,
        source: dict,
        target: dict,
        *,
        context: dict | None = None,
    ):
        """Score one source/target pair, persist the relationship, and return it."""
        matcher      = get_matchmaker(matcher_id)
        result       = matcher.score(source, target, context=context or {})
        relationship = to_relationship(result)
        self.relationship_store.upsert(relationship)
        return relationship

    def rank_pool(
        self,
        matcher_id: str,
        seeker: dict,
        candidates: list[dict],
        *,
        context: dict | None = None,
    ) -> list:
        """Score seeker against every candidate, persist each relationship,
        and return relationships sorted best-first."""
        context = context or {}
        relationships = [
            self.run_pair(matcher_id, seeker, candidate, context=context)
            for candidate in candidates
        ]
        return sorted(relationships, key=lambda r: r.score, reverse=True)

    def run_for_user(
        self,
        user_context,                    # core.context.UserContext
        event_context=None,              # core.context.EventContext | None
        *,
        people_pool: list[dict] | None = None,
        org_pool:    list[dict] | None = None,
    ) -> dict[str, list]:
        """Orchestrate the full scoring pass for a canonical UserContext.

        Steps:
          1. Infers goal types from user_context.goals.
          2. Asks the capability registry which matchers are relevant.
          3. Converts UserContext → the profile dict each matcher expects
             (using adapters from core.context — matchers never see UserContext).
          4. Calls rank_pool() for each relevant matcher.
          5. Returns {matcher_id: sorted_relationship_list}.

        The user's profile information is reused across all matchers — it is
        never reconstructed or re-prompted.
        """
        from core.context import (
            infer_goal_types,
            to_event_profile,
            to_org_profile,
        )
        from registry import MATCHER_CAPABILITIES, get_matchers_for_goals
        from mind.mind import Mind

        goal_types  = infer_goal_types(user_context.goals)
        matched_ids = get_matchers_for_goals(goal_types)

        # Respect event context requirement
        if event_context is None:
            matched_ids = [
                mid for mid in matched_ids
                if not MATCHER_CAPABILITIES[mid].needs_event_context
            ]

        results: dict[str, list] = {}

        for matcher_id in matched_ids:
            if matcher_id == "MM-EVENT-001":
                seeker = to_event_profile(user_context, event_context)
                pool   = [p for p in (people_pool or [])
                          if p.get("id") != user_context.user_id]
                ctx    = {"event_id": event_context.event_id} if event_context else {}

            elif matcher_id == "MM-ORG-001":
                seeker = to_org_profile(user_context)
                pool   = [p for p in (org_pool or [])
                          if p.get("id") != user_context.user_id]
                ctx    = {}

            else:
                # Future matchers: add their profile adapter branch here.
                continue

            if pool:
                results[matcher_id] = self.rank_pool(
                    matcher_id, seeker, pool, context=ctx
                )

        return results
