from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class EntityRef:
    type: str
    id: str


@dataclass
class MatchResult:
    matcher_id: str
    relationship_type: str
    source: EntityRef
    target: EntityRef
    score: float
    breakdown: dict[str, float] = field(default_factory=dict)
    explanation: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class Relationship:
    relationship_id: str
    matcher_id: str
    relationship_type: str
    source: EntityRef
    target: EntityRef
    score: float
    signals: dict[str, float]
    explanation: list[str]
    context: dict[str, Any]
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


class RecommendationCategory(str, Enum):
    """Category labels for groups of recommendations produced by Mind.

    Extends str so values can be compared to plain strings and serialized
    without special handling.
    """
    PEOPLE        = "People"
    COMPANIES     = "Companies"
    INVESTORS     = "Investors"
    OPPORTUNITIES = "Opportunities"

