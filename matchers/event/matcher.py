from __future__ import annotations

from typing import Any

from core.config import load_json_config
from core.matcher import Matchmaker
from core.models import EntityRef, MatchResult


def jaccard(a: Any, b: Any) -> float:
    left = {str(x).strip().lower() for x in (a or []) if str(x).strip()}
    right = {str(x).strip().lower() for x in (b or []) if str(x).strip()}
    if not left and not right:
        return 0.0
    return len(left & right) / len(left | right)


def categorical(a: Any, b: Any) -> float:
    if not a or not b:
        return 0.0
    return 1.0 if str(a).strip().lower() == str(b).strip().lower() else 0.0


class EventMatchmaker(Matchmaker):
    """Similarity matcher for attendees inside one event.

    The parameters are deliberately configuration-driven placeholders until
    the client finalizes event-matching requirements.
    """

    def __init__(self, config_path: str | None = None) -> None:
        if config_path is None:
            from pathlib import Path
            config_path = str(Path(__file__).with_name("config.json"))
        config = load_json_config(config_path)
        self.matcher_id = config["matcher_id"]
        self.relationship_type = config["relationship_type"]
        self.weights = config["weights"]
        self.minimum_score = config.get("minimum_score", 0.0)

    def match(self, source, target, context=None):
        return self.score(source, target, context=context or {})

    def score(self, source: dict[str, Any], target: dict[str, Any], *, context: dict[str, Any] | None = None) -> MatchResult:
        context = context or {}
        breakdown = {
            "professional_domain": jaccard(source.get("professional_domain"), target.get("professional_domain")),
            "interests": jaccard(source.get("interests"), target.get("interests")),
            "role": categorical(source.get("role"), target.get("role")),
            "networking_objective": jaccard(source.get("networking_objective"), target.get("networking_objective")),
            "skills": jaccard(source.get("skills"), target.get("skills")),
            "experience_level": categorical(source.get("experience_level"), target.get("experience_level")),
            "event_interest": jaccard(source.get("event_interest"), target.get("event_interest")),
        }
        total_weight = sum(self.weights.values())
        score = sum(breakdown[k] * w for k, w in self.weights.items()) / total_weight

        return MatchResult(
            matcher_id=self.matcher_id,
            relationship_type=self.relationship_type,
            source=EntityRef("USER", str(source["id"])),
            target=EntityRef("USER", str(target["id"])),
            score=round(score, 6),
            breakdown=breakdown,
            explanation=[],
            context={**context, "minimum_score": self.minimum_score},
        )
