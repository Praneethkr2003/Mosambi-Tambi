"""
tests/test_recommendation_engine.py
=====================================
Tests for the new RecommendationEngine layer (mind/recommendation.py).

Covers:
  1. Engine builds candidates from relationships
  2. Deduplication — same candidate from multiple matchers → one record
  3. Categorization — "Potential investors" for investor stakeholder_type
  4. Categorization — "People you may want to meet" for USER entity_type
  5. Categorization — "Organizations worth exploring" for non-investor orgs
  6. Explanations — reasons are non-empty and evidence-based
  7. Provenance — matcher_id, signals, relationship_id all preserved
  8. Score non-blending — relevance_score = max(evidence.score), not average
  9. End-to-end — full service + engine flow, no goals required
"""
import pytest

from core.context import UserContext, EventContext
from mind.recommendation import RecommendationEngine, RecommendedCandidate, MatchEvidence
from mind.mind import Mind
from relationships.store import InMemoryRelationshipStore
from service import MatchmakingService
from sample_data import EVENT_ATTENDEES, ORGANIZATIONS


ALL_CANDIDATES = EVENT_ATTENDEES + ORGANIZATIONS


# ── Shared fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def seeker() -> UserContext:
    return UserContext(
        user_id="U-E2E",
        name="E2E Seeker",
        roles=["Founder"],
        domains=["Climate Technology", "Clean Energy"],
        skills=["operations"],
        interests=["climate finance"],
        # goals intentionally empty — proactive mode
        extra={
            "stakeholder_type": "Attendee",
            "country": "India",
            "operating_countries": ["India"],
            "supply_chain_stage": [3],
            "stage": "Series A",
            "fundraising_toggle": True,
            "fundraising_amount": 1_500_000,
            "sdg_goals": ["SDG 7"],
        },
    )


@pytest.fixture
def event_ctx() -> EventContext:
    return EventContext(event_id="EVENT-2026", themes=["climate finance"])


@pytest.fixture
def populated_store(seeker, event_ctx):
    """A store + service that has already run scoring for the seeker."""
    store = InMemoryRelationshipStore()
    svc   = MatchmakingService(store)
    svc.run_for_user(seeker, event_ctx,
                     people_pool=EVENT_ATTENDEES, org_pool=ORGANIZATIONS)
    return store


# ── 1. Engine builds candidates ───────────────────────────────────────────────

def test_recommendation_engine_builds_candidates(seeker, populated_store):
    """Engine.build() must return at least one RecommendedCandidate."""
    all_rels = (
        populated_store.get_for_entity("USER", seeker.user_id) +
        populated_store.get_for_entity("ORGANIZATION", seeker.user_id)
    )
    engine = RecommendationEngine()
    candidates = engine.build(all_rels, seeker, ALL_CANDIDATES)
    assert len(candidates) >= 1
    assert all(isinstance(c, RecommendedCandidate) for c in candidates)


# ── 2. Deduplication ──────────────────────────────────────────────────────────

def test_deduplication_same_candidate_appears_once(seeker, event_ctx):
    """If both matchers score the same candidate, only one record is returned."""
    store = InMemoryRelationshipStore()
    svc   = MatchmakingService(store)

    # Ensure both matchers run (one candidate overlaps if any attendee is also in org pool)
    svc.run_for_user(seeker, event_ctx,
                     people_pool=EVENT_ATTENDEES, org_pool=ORGANIZATIONS)

    all_rels = (
        store.get_for_entity("USER", seeker.user_id) +
        store.get_for_entity("ORGANIZATION", seeker.user_id)
    )
    engine = RecommendationEngine()
    candidates = engine.build(all_rels, seeker, ALL_CANDIDATES)

    # candidate_id values must be unique — no duplicate entries
    candidate_ids = [c.candidate_id for c in candidates]
    assert len(candidate_ids) == len(set(candidate_ids)), (
        "Duplicate candidate_id detected — deduplication failed."
    )


# ── 3. Categorization — investors ─────────────────────────────────────────────

def test_categorization_investor_stakeholder_type():
    """A candidate with stakeholder_type='Investor' must map to CATEGORY_INVESTORS."""
    engine = RecommendationEngine()
    result = engine._categorize("ORGANIZATION", {"stakeholder_type": "Investor"})
    assert result == RecommendedCandidate.CATEGORY_INVESTORS


def test_categorization_active_investor_variant():
    """stakeholder_type containing 'investor' (case-insensitive) → CATEGORY_INVESTORS."""
    engine = RecommendationEngine()
    result = engine._categorize("ORGANIZATION", {"stakeholder_type": "Active Investor"})
    assert result == RecommendedCandidate.CATEGORY_INVESTORS


# ── 4. Categorization — people ────────────────────────────────────────────────

def test_categorization_user_entity_type():
    """A USER entity type must always map to CATEGORY_PEOPLE."""
    engine = RecommendationEngine()
    result = engine._categorize("USER", {"role": "Researcher"})
    assert result == RecommendedCandidate.CATEGORY_PEOPLE


# ── 5. Categorization — organizations ────────────────────────────────────────

def test_categorization_non_investor_organization():
    """A Partner or Sponsor organization must map to CATEGORY_COMPANIES."""
    engine = RecommendationEngine()
    for s_type in ("Partner", "Sponsor", "Attendee", "Corporate"):
        result = engine._categorize("ORGANIZATION", {"stakeholder_type": s_type})
        assert result == RecommendedCandidate.CATEGORY_COMPANIES, (
            f"stakeholder_type={s_type!r} should map to CATEGORY_COMPANIES"
        )


# ── 6. Explanation — evidence-based reasons ───────────────────────────────────

def test_explanation_returns_non_empty_reasons(seeker, populated_store):
    """Every RecommendedCandidate must have at least one reason."""
    all_rels = (
        populated_store.get_for_entity("USER", seeker.user_id) +
        populated_store.get_for_entity("ORGANIZATION", seeker.user_id)
    )
    engine = RecommendationEngine()
    candidates = engine.build(all_rels, seeker, ALL_CANDIDATES)
    for cand in candidates:
        assert len(cand.reasons) >= 1, (
            f"Candidate {cand.candidate_id} has no reasons — explanations must always be present."
        )


def test_explanation_reasons_are_strings(seeker, populated_store):
    """All reasons must be non-empty strings."""
    all_rels = (
        populated_store.get_for_entity("USER", seeker.user_id) +
        populated_store.get_for_entity("ORGANIZATION", seeker.user_id)
    )
    engine = RecommendationEngine()
    candidates = engine.build(all_rels, seeker, ALL_CANDIDATES)
    for cand in candidates:
        for reason in cand.reasons:
            assert isinstance(reason, str) and reason.strip(), (
                f"Blank or non-string reason found: {reason!r}"
            )


# ── 7. Provenance preserved ───────────────────────────────────────────────────

def test_provenance_fully_preserved(seeker, populated_store):
    """matcher_id, score, signals, relationship_id must all be present on each evidence item."""
    all_rels = (
        populated_store.get_for_entity("USER", seeker.user_id) +
        populated_store.get_for_entity("ORGANIZATION", seeker.user_id)
    )
    engine = RecommendationEngine()
    candidates = engine.build(all_rels, seeker, ALL_CANDIDATES)
    for cand in candidates:
        assert cand.source_matchers, "source_matchers must not be empty"
        for ev in cand.evidence:
            assert isinstance(ev, MatchEvidence)
            assert ev.matcher_id in ("MM-EVENT-001", "MM-ORG-001")
            assert 0.0 <= ev.score <= 1.0
            assert isinstance(ev.signals, dict)
            assert ev.relationship_id, "relationship_id must be a non-empty string"


# ── 8. Score non-blending ─────────────────────────────────────────────────────

def test_relevance_score_is_max_not_average(seeker, event_ctx):
    """relevance_score must equal max(evidence.score) — never an average."""
    store = InMemoryRelationshipStore()
    svc   = MatchmakingService(store)
    svc.run_for_user(seeker, event_ctx,
                     people_pool=EVENT_ATTENDEES, org_pool=ORGANIZATIONS)

    all_rels = (
        store.get_for_entity("USER", seeker.user_id) +
        store.get_for_entity("ORGANIZATION", seeker.user_id)
    )
    engine = RecommendationEngine()
    candidates = engine.build(all_rels, seeker, ALL_CANDIDATES)
    for cand in candidates:
        expected = max(ev.score for ev in cand.evidence)
        assert abs(cand.relevance_score - expected) < 1e-9, (
            f"{cand.candidate_id}: relevance_score={cand.relevance_score} "
            f"but max evidence score={expected} — scores must not be blended."
        )


# ── 9. End-to-end — no goals required ────────────────────────────────────────

def test_end_to_end_no_goals_required(event_ctx):
    """Complete pipeline — from empty goals to recommendations — must work."""
    store = InMemoryRelationshipStore()
    svc   = MatchmakingService(store)

    # Seeker has ZERO goals — proactive mode
    ctx = UserContext(
        user_id="U-E2E-NG", name="No Goals Seeker",
        roles=["Corporate Sustainability Director"],
        domains=["Climate Technology"],
        interests=["supply chain decarbonization"],
        goals=[],   # explicitly empty
        extra={"country": "Singapore", "supply_chain_stage": [4, 5]},
    )

    # Run scoring — must not raise even with empty goals
    results = svc.run_for_user(
        ctx, event_ctx,
        people_pool=EVENT_ATTENDEES, org_pool=ORGANIZATIONS,
    )
    assert len(results) >= 1, "At least one matcher must run even with goals=[]"

    # Mind synthesize — must return recommendations
    mind = Mind(store)
    candidates = mind.recommend_for_user(
        ctx, event_ctx, candidate_pool=ALL_CANDIDATES, top_n=10
    )
    assert len(candidates) >= 1, (
        "Recommendations must be generated even when goals=[]. "
        "User-stated goals are NOT required for the recommendation pipeline."
    )

    # All system-generated categories must be valid
    valid_cats = {
        RecommendedCandidate.CATEGORY_PEOPLE,
        RecommendedCandidate.CATEGORY_COMPANIES,
        RecommendedCandidate.CATEGORY_INVESTORS,
    }
    for cand in candidates:
        assert cand.category in valid_cats, (
            f"Unexpected category: {cand.category!r}"
        )
