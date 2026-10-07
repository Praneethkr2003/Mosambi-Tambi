from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterable

from .models import MatchResult


class Matchmaker(ABC):
    """Contract shared by every matchmaking system."""

    matcher_id: str
    relationship_type: str

    @abstractmethod
    def score(self, source: Any, target: Any, *, context: dict[str, Any] | None = None) -> MatchResult:
        raise NotImplementedError

    def rank(self, source: Any, candidates: Iterable[Any], *, context: dict[str, Any] | None = None) -> list[MatchResult]:
        results = [self.score(source, candidate, context=context or {}) for candidate in candidates]
        return sorted(results, key=lambda result: result.score, reverse=True)
