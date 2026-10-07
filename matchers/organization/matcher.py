from __future__ import annotations
from typing import Any
from core.matcher import Matchmaker
from core.models import EntityRef, MatchResult
from .scoring import compute_match_score, rank_candidates

class OrganizationMatchmaker(Matchmaker):
    matcher_id = "MM-ORG-001"
    relationship_type = "ORGANIZATION_MATCH"

    def score(self, source: dict[str, Any], target: dict[str, Any], *, context: dict[str, Any] | None = None) -> MatchResult:
        result = compute_match_score(source, target)
        return MatchResult(
            matcher_id=self.matcher_id,
            relationship_type=self.relationship_type,
            source=EntityRef(source.get("entity_type", "ORGANIZATION"), str(source["id"])),
            target=EntityRef(target.get("entity_type", "ORGANIZATION"), str(target["id"])),
            score=result["total"],
            breakdown=result["breakdown"],
            explanation=[],
            context={**(context or {}), "score_detail": result},
        )

    def match(self, source, target, context=None):
        return self.score(source, target, context=context or {})
