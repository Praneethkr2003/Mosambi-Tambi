from pathlib import Path

from matchers.event.matcher import EventMatchmaker
from core.relationship import to_relationship


CONFIG = Path(__file__).parents[2] / "matchers" / "event" / "config.json"


def test_event_matcher_scores_similarity():
    matcher = EventMatchmaker(str(CONFIG))
    a = {
        "id": "A",
        "professional_domain": ["Climate Tech", "Energy"],
        "interests": ["Batteries", "Circular Economy"],
        "role": "Founder",
        "networking_objective": ["Investors"],
        "skills": ["Python", "ML"],
        "experience_level": "Senior",
        "event_interest": ["Climate Finance"],
    }
    b = {**a, "id": "B"}
    result = matcher.score(a, b, context={"event_id": "EVENT-1"})
    assert result.matcher_id == "MM-EVENT-001"
    assert result.relationship_type == "EVENT_ATTENDEE_MATCH"
    assert result.score == 1.0
    assert to_relationship(result).relationship_id.startswith("REL-")
