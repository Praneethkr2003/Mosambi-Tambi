"""
service.py — Matchmaking service layer.

Preserves the existing run_pair() and rank_pool() methods unchanged.

run_for_user() is now profile-driven — it does NOT require user-stated goals.
It invokes every registered matcher whose context requirements are satisfied,
converts UserContext → matcher-specific dicts via adapters, and persists
relationships to the store.

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
        user_context,                       # core.context.UserContext
        event_context=None,                 # core.context.EventContext | None
        *,
        people_pool: list[dict] | None = None,
        org_pool:    list[dict] | None = None,
    ) -> dict[str, list]:
        """Orchestrate a full scoring pass for a canonical UserContext.

        Profile-driven — does NOT require user-stated goals.
        Invokes every registered matcher whose context requirements are met.

        Steps:
          1. get_all_matchers_for_context() — context-driven capability selection.
          2. For each matched matcher, convert UserContext → matcher-specific dict
             via the appropriate adapter (matchers never see UserContext).
          3. Call rank_pool() → persists relationships to the store.
          4. Return {matcher_id: sorted_relationship_list}.

        The user's profile is reused across all matchers — never re-prompted.
        Adding a new matcher requires only a new branch in this method
        (and an entry in MATCHER_CAPABILITIES).
        """
        from core.context import to_event_profile, to_org_profile
        from registry import MATCHER_CAPABILITIES, get_all_matchers_for_context

        # Context-driven selection — no goal filtering
        matched_ids = get_all_matchers_for_context(event_context)
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
                # The rest of Mind, the store, and the UI do not need to change.
                continue

            if pool:
                results[matcher_id] = self.rank_pool(
                    matcher_id, seeker, pool, context=ctx
                )

        return results
