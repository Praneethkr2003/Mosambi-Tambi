from core.models import EntityRef, Relationship
from mind.mind import Mind
from relationships.store import InMemoryRelationshipStore


def rel(rid, matcher, source, target, score, event, reasons):
    return Relationship(
        relationship_id=rid,
        matcher_id=matcher,
        relationship_type="EVENT_ATTENDEE_MATCH" if matcher == "MM-EVENT-001" else "ORGANIZATION_MATCH",
        source=EntityRef(*source),
        target=EntityRef(*target),
        score=score,
        signals={},
        explanation=reasons,
        context={"event_id": event},
    )


def test_mind_filters_by_event_and_returns_other_side():
    store = InMemoryRelationshipStore()
    store.upsert(rel("R1", "MM-EVENT-001", ("USER", "A"), ("USER", "B"), .90, "E1", ["Shared batteries"]))
    store.upsert(rel("R2", "MM-EVENT-001", ("USER", "A"), ("USER", "C"), .95, "E2", ["Other event"]))

    results = Mind(store).recommend("USER", "A", context={"event_id": "E1"})
    assert len(results) == 1
    assert results[0].candidate == EntityRef("USER", "B")
    assert results[0].score == .90


def test_mind_groups_multiple_matchers_without_re_scoring():
    store = InMemoryRelationshipStore()
    store.upsert(rel("R1", "MM-EVENT-001", ("USER", "A"), ("ORG", "X"), .80, "E1", ["Shared interest"]))
    store.upsert(rel("R2", "MM-ORG-001", ("USER", "A"), ("ORG", "X"), .70, "E1", ["Strong domain fit"]))

    results = Mind(store).recommend("USER", "A", context={"event_id": "E1"})
    assert len(results) == 1
    assert results[0].candidate == EntityRef("ORG", "X")
    assert results[0].score == .80
    assert results[0].matcher_ids == ("MM-EVENT-001", "MM-ORG-001")
    assert results[0].relationship_ids == ("R1", "R2")
