"""
sample_data.py — Pre-seeded demo profiles for the Mosambi Matchmaking prototype.

These profiles give the UI a realistic candidate pool to score against out of the box.
They are intentionally varied across domains, geographies, roles, and interests so that
different seeker profiles produce interesting, differentiated scores.

Replace or extend these with real database records in phase 2.
"""
from __future__ import annotations

# ──────────────────────────────────────────────────────────────────────────────
# EVENT ATTENDEES — used by MM-EVENT-001
# Fields: id, name, professional_domain, interests, role, networking_objective,
#         skills, experience_level, event_interest
# ──────────────────────────────────────────────────────────────────────────────

EVENT_ATTENDEES: list[dict] = [
    {
        "id": "ATTENDEE-001",
        "name": "Priya Sharma",
        "professional_domain": ["Climate Technology", "Clean Energy"],
        "interests": ["battery technology", "climate finance", "energy storage"],
        "role": "Investor",
        "networking_objective": ["find climate startups", "battery investments"],
        "skills": ["investment analysis", "energy", "due diligence"],
        "experience_level": "Senior",
        "event_interest": ["climate finance", "clean energy transition"],
    },
    {
        "id": "ATTENDEE-002",
        "name": "Arjun Mehta",
        "professional_domain": ["Climate Technology", "Research"],
        "interests": ["battery recycling", "circular economy", "material science"],
        "role": "Researcher",
        "networking_objective": ["industry partnerships", "commercialise research"],
        "skills": ["materials science", "battery chemistry", "R&D"],
        "experience_level": "Mid-level",
        "event_interest": ["clean technology", "circular economy"],
    },
    {
        "id": "ATTENDEE-003",
        "name": "Maria Santos",
        "professional_domain": ["Policy", "Renewable Energy"],
        "interests": ["energy policy", "carbon markets", "regulatory frameworks"],
        "role": "Policy Lead",
        "networking_objective": ["connect with startups", "understand technology"],
        "skills": ["policy analysis", "stakeholder engagement", "regulation"],
        "experience_level": "Senior",
        "event_interest": ["energy policy", "climate regulation"],
    },
    {
        "id": "ATTENDEE-004",
        "name": "James Chen",
        "professional_domain": ["Climate Technology", "Manufacturing"],
        "interests": ["battery technology", "supply chain", "clean manufacturing"],
        "role": "Founder",
        "networking_objective": ["find investors", "manufacturing partners"],
        "skills": ["battery manufacturing", "operations", "supply chain"],
        "experience_level": "Senior",
        "event_interest": ["clean manufacturing", "climate finance"],
    },
    {
        "id": "ATTENDEE-005",
        "name": "Lisa Kim",
        "professional_domain": ["Corporate Sustainability", "ESG"],
        "interests": ["ESG investing", "net zero", "sustainability reporting"],
        "role": "Corporate Sustainability Director",
        "networking_objective": ["find green suppliers", "ESG partnerships"],
        "skills": ["ESG analysis", "sustainability strategy", "reporting"],
        "experience_level": "Senior",
        "event_interest": ["ESG", "net zero transition"],
    },
    {
        "id": "ATTENDEE-006",
        "name": "Ravi Patel",
        "professional_domain": ["Climate Technology", "Clean Energy"],
        "interests": ["solar energy", "energy storage", "climate finance"],
        "role": "Investor",
        "networking_objective": ["find climate startups", "solar investments"],
        "skills": ["venture capital", "clean energy", "deal structuring"],
        "experience_level": "Senior",
        "event_interest": ["clean energy transition", "climate finance"],
    },
]


# ──────────────────────────────────────────────────────────────────────────────
# ORGANIZATIONS — used by MM-ORG-001
# Fields align with compute_match_score() in matchers/organization/scoring.py
# ──────────────────────────────────────────────────────────────────────────────

ORGANIZATIONS: list[dict] = [
    {
        "id": "ORG-001",
        "name": "GreenBridge Capital",
        "entity_type": "ORGANIZATION",
        "stakeholder_type": "Investor",
        "domain": ["Clean Power Generation", "Energy Storage"],
        "industry": ["Finance", "Renewable Energy"],
        "city": "Mumbai",
        "country": "India",
        "operating_countries": ["India", "Singapore"],
        "supply_chain_stage": [5, 6],
        "stage_focus": ["Seed", "Series A"],
        "ticket_range": [500_000, 3_000_000],
        "support_offered": ["Funding", "Network access", "Market entry support"],
        "sdg_goals": ["SDG 7", "SDG 13"],
    },
    {
        "id": "ORG-002",
        "name": "SolarGrid Systems",
        "entity_type": "ORGANIZATION",
        "stakeholder_type": "Attendee",
        "domain": ["Clean Power Generation", "Distributed Energy"],
        "industry": ["Technology", "Energy"],
        "city": "Bengaluru",
        "country": "India",
        "operating_countries": ["India"],
        "supply_chain_stage": [3, 4],
        "stage": "Series A",
        "fundraising_toggle": True,
        "fundraising_amount": 2_000_000,
        "needs": ["Regulatory navigation", "Market expansion"],
        "sdg_goals": ["SDG 7", "SDG 11"],
    },
    {
        "id": "ORG-003",
        "name": "BlueOcean Policy Institute",
        "entity_type": "ORGANIZATION",
        "stakeholder_type": "Partner",
        "domain": ["Climate Policy", "Ocean Conservation"],
        "industry": ["Policy", "NGO"],
        "city": "Singapore",
        "country": "Singapore",
        "operating_countries": ["Singapore", "Indonesia", "Philippines"],
        "focus_geography": ["Southeast Asia"],
        "supply_chain_stage": [2],
        "support_offered": ["Policy advocacy", "Regulatory navigation", "Research"],
        "sdg_goals": ["SDG 13", "SDG 14", "SDG 17"],
    },
    {
        "id": "ORG-004",
        "name": "ClimateForge Labs",
        "entity_type": "ORGANIZATION",
        "stakeholder_type": "Partner",
        "domain": ["Carbon Capture", "Climate Technology"],
        "industry": ["Research", "Technology"],
        "city": "London",
        "country": "UK",
        "operating_countries": ["UK", "Germany", "France"],
        "focus_geography": ["Europe"],
        "supply_chain_stage": [2, 3],
        "support_offered": ["R&D partnership", "Technical expertise", "IP licensing"],
        "sdg_goals": ["SDG 9", "SDG 13"],
    },
    {
        "id": "ORG-005",
        "name": "TerraFund Impact",
        "entity_type": "ORGANIZATION",
        "stakeholder_type": "Investor",
        "domain": ["Clean Power Generation", "Sustainable Agriculture"],
        "industry": ["Finance", "Agriculture"],
        "city": "New York",
        "country": "USA",
        "operating_countries": ["USA", "India", "Kenya"],
        "supply_chain_stage": [5, 6],
        "stage_focus": ["Series A", "Series B", "Growth"],
        "ticket_range": [2_000_000, 15_000_000],
        "support_offered": ["Funding", "Advisory", "Network access"],
        "sdg_goals": ["SDG 2", "SDG 7", "SDG 13"],
    },
]
