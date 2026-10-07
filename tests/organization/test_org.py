from matchers.organization.matcher import OrganizationMatchmaker

def test_org_matcher_preserves_existing_score_contract():
    a={"id":"A","domain":["Clean Power Generation"],"industry":["Automotive"],"city":"Bengaluru","country":"India","operating_countries":["India"],"supply_chain_stage":[4],"stage":"Growth","fundraising_toggle":True,"fundraising_amount":1000000,"needs":["Regulatory navigation"],"stakeholder_type":"Attendee","sdg_goals":["SDG 7"]}
    b={"id":"B","domain":["Clean Power Generation"],"industry":["Automotive"],"city":"San Francisco","country":"USA","focus_geography":["India"],"supply_chain_stage":[5],"stage_focus":["Growth"],"ticket_range":[500000,2000000],"support_offered":["Regulatory navigation"],"stakeholder_type":"Investor","sdg_goals":["SDG 7"]}
    r=OrganizationMatchmaker().match(a,b)
    assert r.matcher_id=="MM-ORG-001"
    assert r.relationship_type=="ORGANIZATION_MATCH"
    assert 0 <= r.score <= 1
