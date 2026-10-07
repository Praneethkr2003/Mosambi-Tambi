from matchers.event.matcher import EventMatchmaker

def test_event_matcher_isolated():
    a={"id":"A","professional_domain":["climate"],"interests":["battery"],"skills":["python"],"role":"founder"}
    b={"id":"B","professional_domain":["climate"],"interests":["battery"],"skills":["python"],"role":"founder"}
    r=EventMatchmaker().match(a,b,{"event_id":"E1"})
    assert r.matcher_id=="MM-EVENT-001"
    assert r.relationship_type=="EVENT_ATTENDEE_MATCH"
    assert 0 <= r.score <= 1
