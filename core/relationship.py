from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any

from .models import MatchResult, Relationship


def relationship_id(result: MatchResult) -> str:
    """Stable ID for the same logical relationship, independent of score changes."""
    payload = {
        "matcher_id": result.matcher_id,
        "relationship_type": result.relationship_type,
        "source": asdict(result.source),
        "target": asdict(result.target),
        "context": result.context,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return f"REL-{digest[:20]}"


def to_relationship(result: MatchResult) -> Relationship:
    return Relationship(
        relationship_id=relationship_id(result),
        matcher_id=result.matcher_id,
        relationship_type=result.relationship_type,
        source=result.source,
        target=result.target,
        score=result.score,
        signals=result.breakdown,
        explanation=result.explanation,
        context=result.context,
    )
