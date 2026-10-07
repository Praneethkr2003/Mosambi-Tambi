from service import MatchmakingService
from relationships.store import InMemoryRelationshipStore

def test_service_persists_typed_relationship():
    a={"id":"A","professional_domain":["climate"],"interests":["battery"],"skills":["python"],"role":"founder"}
    b={"id":"B","professional_domain":["climate"],"interests":["battery"],"skills":["python"],"role":"founder"}
    store=InMemoryRelationshipStore()
    rel=MatchmakingService(store).run_pair("MM-EVENT-001",a,b,context={"event_id":"E1"})
    assert rel.matcher_id == "MM-EVENT-001"
    assert store.get_for_entity("USER","A")[0].relationship_type == "EVENT_ATTENDEE_MATCH"
