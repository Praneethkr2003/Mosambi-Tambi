"""
tests/test_mind_orchestration.py
=================================
Updated for profile-driven routing (no longer goal-driven).

Changes from previous version:
  - plan() now invokes all contextually-available matchers; goal-routing tests
    replaced with profile-driven equivalents.
  - recommend_for_user() now returns list[RecommendedCandidate] (not
    CategorizedRecommendation). Assertions updated accordingly.
  - Added regression tests proving recommendations work with:
      goals=[]  /  goals omitted  /  roles+domains only (no user-stated intent)
  - GoalType / infer_goal_types tests KEPT — those functions still exist
    and are valid for internal use.
  - Adapter tests KEPT — networking_objective now comes from roles+domains.
  - 6 original tests in test_mind.py / test_service.py / test_event* / test_org
    remain untouched.
"""
import pytest

from core.context import (
    UserContext, EventContext, GoalType,
    infer_goal_types, to_event_profile, to_org_profile, missing_fields,
)
from mind.mind import Mind
from mind.recommendation import RecommendedCandidate
from relationships.store import InMemoryRelationshipStore
from service import MatchmakingService
from sample_data import EVENT_ATTENDEES, ORGANIZATIONS


# ── Shared fixtures ───────────────────────────────────────────────────────────

ALL_CANDIDATES = EVENT_ATTENDEES + ORGANIZATIONS


@pytest.fixture
def full_seeker() -> UserContext:
    """A seeker with all org-relevant fields set. Goals intentionally present
    to confirm they do NOT prevent or restrict recommendations."""
    return UserContext(
        user_id="U-TEST",
        name="Test Seeker",
        roles=["Founder"],
        experience_level="Senior",
        domains=["Climate Technology", "Clean Energy"],
        skills=["battery manufacturing", "operations"],
        interests=["battery technology", "climate finance"],
        goals=[GoalType.FIND_PEOPLE, GoalType.FIND_INVESTORS],  # present but not required
        extra={
            "stakeholder_type": "Attendee",
            "country": "India",
            "city": "Bengaluru",
            "operating_countries": ["India"],
            "supply_chain_stage": [3, 4],
            "stage": "Series A",
            "fundraising_toggle": True,
            "fundraising_amount": 2_000_000,
            "sdg_goals": ["SDG 7", "SDG 13"],
        },
    )


@pytest.fixture
def minimal_seeker() -> UserContext:
    """A seeker with roles and domains but NO goals — the proactive-mode baseline."""
    return UserContext(
        user_id="U-MINIMAL",
        name="Minimal Seeker",
        roles=["Researcher"],
        domains=["Climate Technology"],
        extra={"country": "Germany"},
    )


@pytest.fixture
def event_ctx() -> EventContext:
    return EventContext(
        event_id="EVENT-2026",
        name="ClimateTech Summit 2026",
        themes=["clean energy", "climate finance"],
    )


@pytest.fixture
def store_svc():
    store = InMemoryRelationshipStore()
    return store, MatchmakingService(store)


# ─────────────────────────────────────────────────────────────────────────────
# 1. UserContext — canonical profile
# ─────────────────────────────────────────────────────────────────────────────

def test_user_context_stores_shared_and_extra_fields(full_seeker):
    """Canonical fields on object; org-specific fields in extra."""
    assert full_seeker.user_id == "U-TEST"
    assert "Founder" in full_seeker.roles
    assert "Climate Technology" in full_seeker.domains
    assert full_seeker.extra["country"] == "India"
    assert full_seeker.extra["fundraising_toggle"] is True


def test_user_context_goals_are_optional():
    """UserContext must be constructable without goals — proactive mode."""
    ctx = UserContext(user_id="U-NO-GOALS", name="No Goals")
    assert ctx.goals == []


# ─────────────────────────────────────────────────────────────────────────────
# 2. Mind.plan() — profile-driven, not goal-driven
# ─────────────────────────────────────────────────────────────────────────────

def test_plan_excludes_event_matcher_when_no_event_context(full_seeker):
    """MM-EVENT-001 must be excluded when no EventContext is provided."""
    plan = Mind(InMemoryRelationshipStore()).plan(full_seeker, event_context=None)
    assert "MM-EVENT-001" not in plan


def test_plan_includes_event_matcher_with_event_context(full_seeker, event_ctx):
    """MM-EVENT-001 must appear when EventContext is supplied."""
    plan = Mind(InMemoryRelationshipStore()).plan(full_seeker, event_ctx)
    assert "MM-EVENT-001" in plan


def test_plan_always_includes_org_matcher(full_seeker, event_ctx):
    """MM-ORG-001 must appear regardless of event context."""
    plan_with = Mind(InMemoryRelationshipStore()).plan(full_seeker, event_ctx)
    plan_without = Mind(InMemoryRelationshipStore()).plan(full_seeker, None)
    assert "MM-ORG-001" in plan_with
    assert "MM-ORG-001" in plan_without


def test_plan_works_with_empty_goals(event_ctx):
    """plan() must return matchers even when goals=[]."""
    ctx = UserContext(user_id="U-EG", name="Empty Goals", goals=[])
    plan = Mind(InMemoryRelationshipStore()).plan(ctx, event_ctx)
    assert "MM-EVENT-001" in plan
    assert "MM-ORG-001" in plan


def test_plan_works_with_roles_and_domains_only(event_ctx):
    """plan() must return matchers for a seeker with only roles and domains."""
    ctx = UserContext(
        user_id="U-RD", name="Roles Domains Only",
        roles=["Researcher"], domains=["Clean Energy"],
    )
    plan = Mind(InMemoryRelationshipStore()).plan(ctx, event_ctx)
    assert len(plan) >= 1


# ─────────────────────────────────────────────────────────────────────────────
# 3. GoalType / infer_goal_types — internal utility (still valid, not removed)
# ─────────────────────────────────────────────────────────────────────────────

def test_infer_free_text_investor_goal():
    gt = infer_goal_types(["I'm looking for investors and funding"])
    assert GoalType.FIND_INVESTORS in gt


def test_infer_explicit_goal_type_constants_pass_through():
    gt = infer_goal_types([GoalType.FIND_COMPANIES, GoalType.FIND_COLLABORATORS])
    assert GoalType.FIND_COMPANIES in gt
    assert GoalType.FIND_COLLABORATORS in gt


def test_infer_empty_goals_defaults_to_find_people():
    gt = infer_goal_types([])
    assert GoalType.FIND_PEOPLE in gt


# ─────────────────────────────────────────────────────────────────────────────
# 4. Profile adapters — shared canonical profile, no re-prompting
# ─────────────────────────────────────────────────────────────────────────────

def test_adapters_share_user_id_and_domains(full_seeker, event_ctx):
    """Both adapters produce the same user_id and domain set."""
    ep = to_event_profile(full_seeker, event_ctx)
    op = to_org_profile(full_seeker)
    assert ep["id"] == op["id"] == full_seeker.user_id
    assert set(ep["professional_domain"]) == set(op["domain"])


def test_event_adapter_networking_objective_from_roles_and_domains(full_seeker, event_ctx):
    """networking_objective must be derived from roles+domains, not goals."""
    ep = to_event_profile(full_seeker, event_ctx)
    nobj = ep["networking_objective"]
    # Roles and domains are present as signals
    assert "Founder" in nobj
    assert "Climate Technology" in nobj
    # Goal strings must NOT appear — they are not identity signals
    for goal in full_seeker.goals:
        assert goal not in nobj, (
            f"Goal string {goal!r} appeared in networking_objective — "
            "it should not. networking_objective is who the user IS, not what they want."
        )


def test_event_adapter_works_with_empty_goals(event_ctx):
    """to_event_profile must work when goals=[] — networking_objective still populated."""
    ctx = UserContext(
        user_id="U-EG2", name="No Goals",
        roles=["Engineer"], domains=["Clean Energy"], goals=[],
    )
    ep = to_event_profile(ctx, event_ctx)
    assert "Engineer" in ep["networking_objective"]
    assert "Clean Energy" in ep["networking_objective"]


def test_event_adapter_enriches_event_interest_from_themes(full_seeker, event_ctx):
    ep = to_event_profile(full_seeker, event_ctx)
    assert "clean energy" in ep["event_interest"]       # from event themes
    assert "battery technology" in ep["event_interest"] # from user interests


def test_org_adapter_reads_extra_fields(full_seeker):
    op = to_org_profile(full_seeker)
    assert op["country"] == "India"
    assert op["supply_chain_stage"] == [3, 4]
    assert op["fundraising_toggle"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 5. Mind.recommend_for_user() — proactive, no goals required
# ─────────────────────────────────────────────────────────────────────────────

def test_recommend_for_user_returns_recommended_candidates(
    full_seeker, event_ctx, store_svc
):
    """recommend_for_user() must return RecommendedCandidates with categories."""
    store, svc = store_svc
    svc.run_for_user(full_seeker, event_ctx,
                     people_pool=EVENT_ATTENDEES, org_pool=ORGANIZATIONS)
    candidates = Mind(store).recommend_for_user(
        full_seeker, event_ctx, candidate_pool=ALL_CANDIDATES, top_n=10
    )
    assert len(candidates) >= 1
    for c in candidates:
        assert isinstance(c, RecommendedCandidate)
        assert c.category in (
            RecommendedCandidate.CATEGORY_PEOPLE,
            RecommendedCandidate.CATEGORY_COMPANIES,
            RecommendedCandidate.CATEGORY_INVESTORS,
        )


def test_recommend_for_user_no_goals_required(event_ctx, store_svc):
    """KEY PRODUCT REQUIREMENT: recommendations must be generated when goals=[]."""
    store, svc = store_svc
    ctx = UserContext(
        user_id="U-NG", name="No Goals User",
        roles=["Founder"], domains=["Climate Technology"], goals=[],
        extra={"country": "India", "supply_chain_stage": [3], "fundraising_toggle": True},
    )
    svc.run_for_user(ctx, event_ctx,
                     people_pool=EVENT_ATTENDEES, org_pool=ORGANIZATIONS)
    candidates = Mind(store).recommend_for_user(
        ctx, event_ctx, candidate_pool=ALL_CANDIDATES, top_n=10
    )
    assert len(candidates) >= 1, (
        "Recommendations must be generated even when goals=[] — "
        "user-stated goals are NOT required for the recommendation pipeline."
    )


def test_recommend_for_user_goals_none_equivalent(event_ctx, store_svc):
    """UserContext with no goals (default) → recommendations still generated."""
    store, svc = store_svc
    ctx = UserContext(
        user_id="U-DEF", name="Default Goals",
        roles=["Researcher"], domains=["Clean Energy"],
        extra={"country": "Germany"},
    )
    # goals field defaults to [] — never set by the caller
    assert ctx.goals == []
    svc.run_for_user(ctx, event_ctx,
                     people_pool=EVENT_ATTENDEES, org_pool=ORGANIZATIONS)
    candidates = Mind(store).recommend_for_user(
        ctx, event_ctx, candidate_pool=ALL_CANDIDATES, top_n=10
    )
    assert len(candidates) >= 1


def test_recommend_for_user_score_not_blended(full_seeker, event_ctx, store_svc):
    """relevance_score must equal max(evidence.score) — never an averaged blend."""
    store, svc = store_svc
    svc.run_for_user(full_seeker, event_ctx,
                     people_pool=EVENT_ATTENDEES, org_pool=ORGANIZATIONS)
    candidates = Mind(store).recommend_for_user(
        full_seeker, event_ctx, candidate_pool=ALL_CANDIDATES, top_n=10
    )
    for cand in candidates:
        max_evidence_score = max(ev.score for ev in cand.evidence)
        assert abs(cand.relevance_score - max_evidence_score) < 1e-9, (
            f"relevance_score {cand.relevance_score} ≠ max evidence score "
            f"{max_evidence_score} — scores must not be blended across matchers."
        )


def test_recommend_for_user_provenance_preserved(full_seeker, event_ctx, store_svc):
    """Every RecommendedCandidate must carry full provenance."""
    store, svc = store_svc
    svc.run_for_user(full_seeker, event_ctx,
                     people_pool=EVENT_ATTENDEES, org_pool=ORGANIZATIONS)
    candidates = Mind(store).recommend_for_user(
        full_seeker, event_ctx, candidate_pool=ALL_CANDIDATES, top_n=10
    )
    for cand in candidates:
        assert cand.source_matchers, "source_matchers must not be empty"
        for ev in cand.evidence:
            assert ev.matcher_id in ("MM-EVENT-001", "MM-ORG-001")
            assert 0.0 <= ev.score <= 1.0
            assert ev.relationship_id, "relationship_id must be set"


# ─────────────────────────────────────────────────────────────────────────────
# 6. service.run_for_user() — profile-driven, no goals needed
# ─────────────────────────────────────────────────────────────────────────────

def test_run_for_user_invokes_both_matchers_when_event_provided(
    full_seeker, event_ctx, store_svc
):
    """With event context present, both matchers must be invoked."""
    _, svc = store_svc
    results = svc.run_for_user(
        full_seeker, event_ctx,
        people_pool=EVENT_ATTENDEES, org_pool=ORGANIZATIONS,
    )
    assert "MM-EVENT-001" in results
    assert "MM-ORG-001" in results
    assert all(len(v) > 0 for v in results.values())


def test_run_for_user_persists_relationships_to_store(
    full_seeker, event_ctx, store_svc
):
    store, svc = store_svc
    svc.run_for_user(
        full_seeker, event_ctx,
        people_pool=EVENT_ATTENDEES, org_pool=ORGANIZATIONS,
    )
    event_rels = store.get_for_entity("USER", full_seeker.user_id)
    assert len(event_rels) >= 1


def test_run_for_user_skips_event_matcher_without_event_context(
    full_seeker, store_svc
):
    """Without EventContext, MM-EVENT-001 must be skipped. MM-ORG-001 still runs."""
    _, svc = store_svc
    results = svc.run_for_user(
        full_seeker,
        event_context=None,
        people_pool=EVENT_ATTENDEES,
        org_pool=ORGANIZATIONS,
    )
    assert "MM-EVENT-001" not in results
    assert "MM-ORG-001" in results


def test_run_for_user_works_with_empty_goals(event_ctx, store_svc):
    """run_for_user must invoke both matchers even when goals=[]."""
    _, svc = store_svc
    ctx = UserContext(
        user_id="U-EG3", name="Empty Goals",
        roles=["Policy Lead"], domains=["Climate Technology"], goals=[],
        extra={"country": "Kenya"},
    )
    results = svc.run_for_user(
        ctx, event_ctx,
        people_pool=EVENT_ATTENDEES, org_pool=ORGANIZATIONS,
    )
    assert "MM-EVENT-001" in results
    assert "MM-ORG-001" in results


# ─────────────────────────────────────────────────────────────────────────────
# 7. missing_fields() — progressive completion hints
# ─────────────────────────────────────────────────────────────────────────────

def test_missing_fields_flagged_when_country_absent():
    sparse = UserContext(
        user_id="U-SPARSE", name="Sparse",
        goals=[GoalType.FIND_INVESTORS],
    )
    hints = missing_fields(sparse, {GoalType.FIND_INVESTORS})
    field_names = [h.lower() for h in hints]
    assert any("country" in f for f in field_names)
    assert any("supply chain" in f for f in field_names)


def test_no_missing_fields_when_profile_complete(full_seeker):
    hints = missing_fields(full_seeker, {GoalType.FIND_INVESTORS})
    remaining = [h.lower() for h in hints]
    assert not any("country" in f for f in remaining)
    assert not any("supply chain" in f for f in remaining)
    assert not any("fundraising" in f for f in remaining)
