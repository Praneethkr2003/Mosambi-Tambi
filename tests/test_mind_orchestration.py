"""
tests/test_mind_orchestration.py
=================================
Tests for the upgraded Mind orchestration layer.

Covers (as specified):
  1. UserContext — enter-once canonical profile
  2. EventContext — event filtering in plan()
  3. Goal inference and routing
  4. Profile adapters (shared domains, no re-prompting)
  5. Mind.plan()
  6. Mind.recommend_for_user() — categorized output + no score blending
  7. service.run_for_user() — persistence + correct matcher routing
  8. missing_fields() — progressive completion hints

The 6 existing tests in test_mind.py, test_service.py, and test_event*.py
are NOT modified — they continue to pass against the unchanged recommend() API.
"""
import pytest

from core.context import (
    UserContext, EventContext, GoalType,
    infer_goal_types, to_event_profile, to_org_profile, missing_fields,
)
from core.models import RecommendationCategory
from mind.mind import Mind, CategorizedRecommendation
from relationships.store import InMemoryRelationshipStore
from service import MatchmakingService
from sample_data import EVENT_ATTENDEES, ORGANIZATIONS


# ── Shared fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def full_seeker() -> UserContext:
    """A seeker with both people and investor goals and all relevant fields set."""
    return UserContext(
        user_id="U-TEST",
        name="Test Seeker",
        roles=["Founder"],
        experience_level="Senior",
        domains=["Climate Technology", "Clean Energy"],
        skills=["battery manufacturing", "operations"],
        interests=["battery technology", "climate finance"],
        goals=[GoalType.FIND_PEOPLE, GoalType.FIND_INVESTORS],
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
# 1. UserContext — enter-once canonical profile
# ─────────────────────────────────────────────────────────────────────────────

def test_user_context_stores_shared_and_extra_fields(full_seeker):
    """Canonical fields are on the object; org-specific fields are in extra."""
    assert full_seeker.user_id == "U-TEST"
    assert "Founder" in full_seeker.roles
    assert "Climate Technology" in full_seeker.domains
    # Org-specific fields are accessible via extra, not as top-level attrs
    assert full_seeker.extra["country"] == "India"
    assert full_seeker.extra["fundraising_toggle"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 2. EventContext — event filtering in plan()
# ─────────────────────────────────────────────────────────────────────────────

def test_plan_excludes_event_matcher_when_no_event_context(full_seeker):
    """MM-EVENT-001 must not appear in plan() output when EventContext is None."""
    mind = Mind(InMemoryRelationshipStore())
    plan = mind.plan(full_seeker, event_context=None)
    assert "MM-EVENT-001" not in plan


def test_plan_includes_event_matcher_with_event_context(full_seeker, event_ctx):
    """MM-EVENT-001 must appear when EventContext is supplied and goal is FIND_PEOPLE."""
    mind = Mind(InMemoryRelationshipStore())
    plan = mind.plan(full_seeker, event_ctx)
    assert "MM-EVENT-001" in plan


# ─────────────────────────────────────────────────────────────────────────────
# 3. Goal inference and routing
# ─────────────────────────────────────────────────────────────────────────────

def test_infer_free_text_investor_goal():
    gt = infer_goal_types(["I'm looking for investors and funding"])
    assert GoalType.FIND_INVESTORS in gt


def test_infer_explicit_goal_type_constants_pass_through():
    """GoalType constants (from a UI multiselect) must pass through unchanged."""
    gt = infer_goal_types([GoalType.FIND_COMPANIES, GoalType.FIND_COLLABORATORS])
    assert GoalType.FIND_COMPANIES in gt
    assert GoalType.FIND_COLLABORATORS in gt


def test_infer_empty_goals_defaults_to_find_people():
    """Empty goals list must not break routing — fall back to FIND_PEOPLE."""
    gt = infer_goal_types([])
    assert GoalType.FIND_PEOPLE in gt


# ─────────────────────────────────────────────────────────────────────────────
# 4. Profile adapters — shared canonical profile, no re-prompting
# ─────────────────────────────────────────────────────────────────────────────

def test_adapters_share_user_id_and_domains(full_seeker, event_ctx):
    """Both adapters must produce the same user_id and domain set — proving
    the same UserContext drives both matchers without any re-prompting."""
    ep = to_event_profile(full_seeker, event_ctx)
    op = to_org_profile(full_seeker)

    assert ep["id"] == op["id"] == full_seeker.user_id
    assert set(ep["professional_domain"]) == set(op["domain"])


def test_event_adapter_enriches_event_interest_from_themes(full_seeker, event_ctx):
    ep = to_event_profile(full_seeker, event_ctx)
    assert "clean energy" in ep["event_interest"]   # from event themes
    assert "battery technology" in ep["event_interest"]  # from user interests


def test_org_adapter_reads_extra_fields(full_seeker):
    op = to_org_profile(full_seeker)
    assert op["country"] == "India"
    assert op["supply_chain_stage"] == [3, 4]
    assert op["fundraising_toggle"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 5. Mind.plan()
# ─────────────────────────────────────────────────────────────────────────────

def test_plan_routes_investor_goal_only_to_org_matcher(event_ctx):
    ctx  = UserContext(user_id="U-P1", name="P1", goals=[GoalType.FIND_INVESTORS])
    plan = Mind(InMemoryRelationshipStore()).plan(ctx, event_ctx)
    assert "MM-ORG-001" in plan
    # FIND_INVESTORS does not activate MM-EVENT-001
    assert "MM-EVENT-001" not in plan


def test_plan_routes_mixed_goals_to_both_matchers(full_seeker, event_ctx):
    plan = Mind(InMemoryRelationshipStore()).plan(full_seeker, event_ctx)
    assert "MM-EVENT-001" in plan
    assert "MM-ORG-001" in plan


# ─────────────────────────────────────────────────────────────────────────────
# 6. Mind.recommend_for_user()
# ─────────────────────────────────────────────────────────────────────────────

def test_recommend_for_user_returns_categorized_results(
    full_seeker, event_ctx, store_svc
):
    store, svc = store_svc
    svc.run_for_user(
        full_seeker, event_ctx,
        people_pool=EVENT_ATTENDEES,
        org_pool=ORGANIZATIONS,
    )
    cats = Mind(store).recommend_for_user(full_seeker, event_ctx, top_n=5)

    assert len(cats) >= 1
    categories = {c.category for c in cats}
    # FIND_PEOPLE → PEOPLE category
    assert RecommendationCategory.PEOPLE in categories
    # FIND_INVESTORS → COMPANIES category (org matcher)
    assert RecommendationCategory.COMPANIES in categories


def test_recommend_for_user_does_not_blend_scores(
    full_seeker, event_ctx, store_svc
):
    """Each CategorizedRecommendation must contain items from exactly one matcher.
    Scores from MM-EVENT-001 and MM-ORG-001 must never be mixed in the same group."""
    store, svc = store_svc
    svc.run_for_user(
        full_seeker, event_ctx,
        people_pool=EVENT_ATTENDEES,
        org_pool=ORGANIZATIONS,
    )
    cats = Mind(store).recommend_for_user(full_seeker, event_ctx, top_n=5)

    for cat in cats:
        # cat.matcher_id is the declared single source for this category
        assert cat.matcher_id in ("MM-EVENT-001", "MM-ORG-001")
        for item in cat.items:
            # All evidence in a category comes only from that category's matcher
            assert cat.matcher_id in item.matcher_ids, (
                f"Category {cat.category} has item from unexpected matcher: "
                f"{item.matcher_ids}"
            )
            assert 0 <= item.score <= 1
            assert len(item.relationship_ids) >= 1


# ─────────────────────────────────────────────────────────────────────────────
# 7. service.run_for_user()
# ─────────────────────────────────────────────────────────────────────────────

def test_run_for_user_invokes_both_matchers_for_mixed_goals(
    full_seeker, event_ctx, store_svc
):
    _, svc = store_svc
    results = svc.run_for_user(
        full_seeker, event_ctx,
        people_pool=EVENT_ATTENDEES,
        org_pool=ORGANIZATIONS,
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
        people_pool=EVENT_ATTENDEES,
        org_pool=ORGANIZATIONS,
    )
    # USER relationships stored by event matcher
    event_rels = store.get_for_entity("USER", full_seeker.user_id)
    assert len(event_rels) >= 1


def test_run_for_user_skips_event_matcher_without_event_context(
    full_seeker, store_svc
):
    _, svc = store_svc
    results = svc.run_for_user(
        full_seeker,
        event_context=None,
        people_pool=EVENT_ATTENDEES,
        org_pool=ORGANIZATIONS,
    )
    assert "MM-EVENT-001" not in results
    assert "MM-ORG-001" in results  # investor goal still active


# ─────────────────────────────────────────────────────────────────────────────
# 8. missing_fields() — progressive completion hints
# ─────────────────────────────────────────────────────────────────────────────

def test_missing_fields_flagged_when_country_absent():
    sparse = UserContext(
        user_id="U-SPARSE", name="Sparse",
        goals=[GoalType.FIND_INVESTORS],
        # country and supply_chain_stage intentionally absent
    )
    hints = missing_fields(sparse, {GoalType.FIND_INVESTORS})
    field_names = [h.lower() for h in hints]
    assert any("country" in f for f in field_names)
    assert any("supply chain" in f for f in field_names)


def test_no_missing_fields_when_profile_complete(full_seeker):
    """full_seeker fixture has all required fields — no hints expected."""
    hints = missing_fields(full_seeker, {GoalType.FIND_INVESTORS})
    # country, supply_chain_stage, fundraising_toggle are all set
    remaining_field_names = [h.lower() for h in hints]
    assert not any("country" in f for f in remaining_field_names)
    assert not any("supply chain" in f for f in remaining_field_names)
    assert not any("fundraising" in f for f in remaining_field_names)
