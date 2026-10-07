import json
import os
import sys
try:
    from langchain_groq import ChatGroq
    from dotenv import load_dotenv
    load_dotenv()
    llm = ChatGroq(model="llama-3.3-70b-versatile", max_tokens=1500)
except ImportError:
    llm = None

# Fields intentionally excluded from matching input: payment history, login
# history, phone number, email addresses. None are matching signals, and
# sending them to the model is unnecessary PII exposure.
MATCH_FIELDS = ("name", "bio", "interests", "social_links")

# All tunable numbers for the scoring model live here, not scattered through the scorer
# functions. Override any of them without touching code by dropping a match_config.json next
# to this file with the keys you want to change — see DEFAULT_MATCH_CONFIG below for the shape.
DEFAULT_MATCH_CONFIG = {
    # Per-parameter weight, must sum to 1.0 across all entries in SCORED_PARAMETERS.
    "weights": {
        "climate_domain_overlap": 0.25,
        "industry_overlap": 0.15,
        "supply_chain_position": 0.10,
        "geography_fit": 0.15,
        "stage_lifecycle_fit": 0.10,
        "ticket_size_fit": 0.08,
        "non_capital_support_fit": 0.07,
        "stakeholder_pairwise_prior": 0.08,
        "sdg_alignment": 0.02,
    },
    # Multiplier applied to climate_domain_overlap / industry_overlap based on geographic
    # distance between the pair (see MODULATED_BY_GEOGRAPHY below). Placeholder values —
    # the Notion spec only specifies direction (up cross-country, down same-city), not magnitude.
    "geo_modulation": {
        "same_city": 0.85,
        "same_country": 1.0,
        "different_country": 1.15,
    },
    # Baseline "does type X typically want to meet type Y" prior. Keys are "TypeA|TypeB"
    # (order doesn't matter, both orderings are checked). Types match the platform's real
    # event-registration taxonomy (mosambi frontend/src/lib/mosambi.ts STAKEHOLDER_TYPES):
    # Attendee, Speaker, Sponsor, Press / Media, Investor, Partner, Organiser.
    # Values are still placeholder — replace with the real Stakeholder Pair Matrix.
    "stakeholder_pair_prior_default": 0.5,
    "stakeholder_pair_prior": {
        "Attendee|Investor": 0.9,
        "Attendee|Sponsor": 0.7,
        "Attendee|Partner": 0.7,
        "Attendee|Speaker": 0.6,
        "Attendee|Press / Media": 0.3,
        "Attendee|Organiser": 0.2,
        "Investor|Sponsor": 0.7,
        "Investor|Partner": 0.6,
        "Investor|Investor": 0.3,
        "Sponsor|Partner": 0.6,
        "Press / Media|Speaker": 0.6,
        "Press / Media|Sponsor": 0.5,
        "Organiser|Organiser": 0.2,
    },
}

MATCH_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "match_config.json")


def load_match_config(path: str = MATCH_CONFIG_PATH) -> dict:
    """Start from DEFAULT_MATCH_CONFIG, shallow-merge in match_config.json if present."""
    config = {k: dict(v) if isinstance(v, dict) else v for k, v in DEFAULT_MATCH_CONFIG.items()}
    if os.path.exists(path):
        with open(path) as f:
            overrides = json.load(f)
        for key, value in overrides.items():
            if isinstance(value, dict) and isinstance(config.get(key), dict):
                config[key].update(value)
            else:
                config[key] = value
    return config


MATCH_CONFIG = load_match_config()


def jaccard_overlap(tags_a, tags_b) -> float:
    set_a, set_b = set(tags_a or []), set(tags_b or [])
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def score_climate_domain_overlap(profile_a: dict, profile_b: dict) -> float:
    """Jaccard overlap of climate-tech domain tags (CCF Taxonomy). Soft signal, 25% weight."""
    return jaccard_overlap(profile_a.get("domain"), profile_b.get("domain"))


def score_industry_overlap(profile_a: dict, profile_b: dict) -> float:
    """Jaccard overlap of Industry Focus Area tags, independent of climate domain. Soft, 15% weight."""
    return jaccard_overlap(profile_a.get("industry"), profile_b.get("industry"))


def geo_category(profile_a: dict, profile_b: dict):
    """'same_city' / 'same_country' / 'different_country', or None if location unknown on either side."""
    city_a, country_a = profile_a.get("city"), profile_a.get("country")
    city_b, country_b = profile_b.get("city"), profile_b.get("country")
    if not country_a or not country_b:
        return None
    if city_a and city_b and city_a == city_b:
        return "same_city"
    if country_a == country_b:
        return "same_country"
    return "different_country"


def geo_proximity_weight(profile_a: dict, profile_b: dict) -> float:
    """1.0 same city, 0.5 same country, 0.0 different country / unknown location. Used by Supply Chain Position."""
    return {"same_city": 1.0, "same_country": 0.5}.get(geo_category(profile_a, profile_b), 0.0)


# The platform's value is connecting orgs that wouldn't meet organically: a Domain/Industry
# match between orgs in different countries is worth more, the same match same-city is worth
# less (organic local discovery likely covers it already). Neutral (1.0) when location unknown.
# Values come from MATCH_CONFIG["geo_modulation"] — see load_match_config() above to override.
GEO_MODULATION = MATCH_CONFIG["geo_modulation"]


def geography_modulation_factor(profile_a: dict, profile_b: dict) -> float:
    return GEO_MODULATION.get(geo_category(profile_a, profile_b), 1.0)


def geography_match_one_direction(seeker: dict, candidate: dict):
    """Seeker's HQ/operating countries against candidate's stated FOCUS geography (not candidate's own HQ)."""
    seeker_countries = seeker.get("operating_countries") or ([seeker["country"]] if seeker.get("country") else [])
    if not seeker_countries:
        return None
    candidate_focus = candidate.get("focus_geography")
    if candidate_focus:
        # Hard filter: candidate has a stated focus geography.
        return 1.0 if set(seeker_countries) & set(candidate_focus) else 0.0
    # Soft: no stated focus, fall back to comparing operating countries directly.
    candidate_countries = candidate.get("operating_countries") or ([candidate["country"]] if candidate.get("country") else [])
    if not candidate_countries:
        return None
    return jaccard_overlap(seeker_countries, candidate_countries)


def score_geography_fit(profile_a: dict, profile_b: dict):
    """Bidirectional geography fit. None (not applicable) if neither side has location data. 15% weight."""
    scores = [
        s for s in (
            geography_match_one_direction(profile_a, profile_b),
            geography_match_one_direction(profile_b, profile_a),
        )
        if s is not None
    ]
    if not scores:
        return None
    return sum(scores) / len(scores)


def stage_distance(stages_a, stages_b):
    """Min absolute distance between any pair of supply-chain stages (multi-select). None if either side is empty."""
    set_a, set_b = set(stages_a or []), set(stages_b or [])
    if not set_a or not set_b:
        return None
    return min(abs(a - b) for a in set_a for b in set_b)


def score_supply_chain_position(profile_a: dict, profile_b: dict):
    """Blend of adjacency (distance=1) and similarity (distance=0), weighted by geographic proximity.
    Close (same city): reward adjacency — practical local supply relationship.
    Far (different country): reward same-stage similarity instead. Soft, 10% weight."""
    distance = stage_distance(profile_a.get("supply_chain_stage"), profile_b.get("supply_chain_stage"))
    if distance is None:
        return None
    adjacency_score = max(0.0, 1 - abs(distance - 1))
    similarity_score = max(0.0, 1 - distance)
    proximity_weight = geo_proximity_weight(profile_a, profile_b)
    return proximity_weight * adjacency_score + (1 - proximity_weight) * similarity_score


def stage_fit_one_direction(seeker: dict, candidate: dict):
    """Seeker's own lifecycle stage against candidate's stated stage focus (e.g. investment thesis)."""
    seeker_stage = seeker.get("stage")
    candidate_focus = candidate.get("stage_focus")
    if not seeker_stage or not candidate_focus:
        return None
    return 1.0 if seeker_stage in candidate_focus else 0.0


def score_stage_lifecycle_fit(profile_a: dict, profile_b: dict):
    """Bidirectional. Hard for Investor/Active Fund (structured field); approximate elsewhere. 10% weight."""
    scores = [
        s for s in (
            stage_fit_one_direction(profile_a, profile_b),
            stage_fit_one_direction(profile_b, profile_a),
        )
        if s is not None
    ]
    if not scores:
        return None
    return sum(scores) / len(scores)


def ticket_size_fit_one_direction(seeker: dict, candidate: dict):
    """Funding ask (seeker) against ticket range (candidate). Only applies when seeker is fundraising."""
    if not seeker.get("fundraising_toggle"):
        return None
    ask = seeker.get("fundraising_amount")
    ticket_range = candidate.get("ticket_range")
    if ask is None or not ticket_range:
        return None
    lo, hi = ticket_range
    if lo <= ask <= hi:
        return 1.0
    gap = (lo - ask) / lo if ask < lo else (ask - hi) / hi
    return max(0.0, 1 - gap)


def score_ticket_size_fit(profile_a: dict, profile_b: dict):
    """Only evaluated when a side has Fundraising Toggle = ON; otherwise not applicable. Hard, 8% weight."""
    scores = [
        s for s in (
            ticket_size_fit_one_direction(profile_a, profile_b),
            ticket_size_fit_one_direction(profile_b, profile_a),
        )
        if s is not None
    ]
    if not scores:
        return None
    return sum(scores) / len(scores)


def support_fit_one_direction(seeker: dict, candidate: dict):
    """Fraction of the seeker's stated needs covered by the candidate's stated support offerings."""
    needs = seeker.get("needs")
    offered = candidate.get("support_offered")
    if not needs or not offered:
        return None
    return len(set(needs) & set(offered)) / len(set(needs))


def score_non_capital_support_fit(profile_a: dict, profile_b: dict):
    """Startup's operational needs vs institution's non-capital support offerings. Soft, 7% weight.
    Placeholder tag-overlap logic until NLP extraction exists on the startup's free-text needs."""
    scores = [
        s for s in (
            support_fit_one_direction(profile_a, profile_b),
            support_fit_one_direction(profile_b, profile_a),
        )
        if s is not None
    ]
    if not scores:
        return None
    return sum(scores) / len(scores)


# Baseline "does type X typically want to meet type Y" prior. Placeholder values — replace with
# the real Stakeholder Pair Matrix from the Notion spec (and the platform's real role taxonomy,
# once wired in) once available. Unlisted/unknown pairs fall back to STAKEHOLDER_PAIR_PRIOR_DEFAULT.
# Sourced from MATCH_CONFIG["stakeholder_pair_prior"] — "TypeA|TypeB" string keys there (order
# doesn't matter) get turned into frozenset keys here so pair lookup is order-independent.
STAKEHOLDER_PAIR_PRIOR_DEFAULT = MATCH_CONFIG["stakeholder_pair_prior_default"]
STAKEHOLDER_PAIR_PRIOR = {
    frozenset(pair.split("|")): value
    for pair, value in MATCH_CONFIG["stakeholder_pair_prior"].items()
}


def score_stakeholder_pairwise_prior(profile_a: dict, profile_b: dict):
    """Floor/ceiling under the other dimensions so type-pair baseline can't be swamped by a
    strong Domain/Industry match between two orgs that don't typically seek each other out.
    Soft, 8% weight."""
    type_a, type_b = profile_a.get("stakeholder_type"), profile_b.get("stakeholder_type")
    if not type_a or not type_b:
        return None
    return STAKEHOLDER_PAIR_PRIOR.get(frozenset({type_a, type_b}), STAKEHOLDER_PAIR_PRIOR_DEFAULT)


def score_sdg_alignment(profile_a: dict, profile_b: dict) -> float:
    """Jaccard overlap of UN SDG goal tags. Soft, optional (v2), 2% weight — small differentiator only."""
    return jaccard_overlap(profile_a.get("sdg_goals"), profile_b.get("sdg_goals"))


# Scored parameters registry — each entry: (name, weight, scorer(profile_a, profile_b) -> float|None 0..1).
# A scorer returns None when the dimension doesn't apply to this pair (missing data, or a
# precondition like Fundraising Toggle isn't met); that parameter's weight is then redistributed
# proportionally across the parameters that did apply, rather than penalizing the pair.
PARAMETER_SCORERS = {
    "climate_domain_overlap": score_climate_domain_overlap,
    "industry_overlap": score_industry_overlap,
    "supply_chain_position": score_supply_chain_position,
    "geography_fit": score_geography_fit,
    "stage_lifecycle_fit": score_stage_lifecycle_fit,
    "ticket_size_fit": score_ticket_size_fit,
    "non_capital_support_fit": score_non_capital_support_fit,
    "stakeholder_pairwise_prior": score_stakeholder_pairwise_prior,
    "sdg_alignment": score_sdg_alignment,
}

# Weights come from MATCH_CONFIG["weights"] — override via match_config.json without touching code.
SCORED_PARAMETERS = [
    (name, weight, PARAMETER_SCORERS[name])
    for name, weight in MATCH_CONFIG["weights"].items()
]

# Dimensions whose raw score gets scaled by geography_modulation_factor before weighting: the
# platform's value is connecting orgs that wouldn't meet organically, so a Domain/Industry match
# is worth more across countries and less within the same city.
MODULATED_BY_GEOGRAPHY = {"climate_domain_overlap", "industry_overlap"}

# Human-readable explainer per parameter, for surfacing "how was this calculated" in the UI.
# `fields` lists the profile keys the scorer actually reads, so the UI can show the raw inputs
# behind each number without duplicating the scoring logic.
PARAMETER_INFO = {
    "climate_domain_overlap": {
        "label": "Climate Domain overlap",
        "description": (
            "Jaccard overlap of shared climate-tech domain tags (CCF Taxonomy). A shared "
            "granular sub-tag (e.g. both 'Clean Power Generation') counts the same as any "
            "other shared tag — overlap is size-of-intersection over size-of-union."
        ),
        "fields": ("domain",),
    },
    "industry_overlap": {
        "label": "Industry overlap",
        "description": (
            "Jaccard overlap of cross-sector Industry Focus Area tags, independent of climate "
            "domain — two orgs can share a domain but serve different industries, or vice versa."
        ),
        "fields": ("industry",),
    },
    "supply_chain_position": {
        "label": "Supply Chain Position",
        "description": (
            "Blends an adjacency score (stage distance = 1) and a similarity score (stage "
            "distance = 0), weighted by geographic proximity. Same city leans toward rewarding "
            "adjacency (a practical local supply relationship); different country leans toward "
            "rewarding same-stage peers instead (knowledge-sharing, licensing)."
        ),
        "fields": ("supply_chain_stage", "city", "country"),
    },
    "geography_fit": {
        "label": "Geography fit (role-aware)",
        "description": (
            "Seeker's HQ/operating countries checked against the candidate's stated FOCUS "
            "geography (hard filter) when the candidate has one, otherwise falls back to "
            "comparing operating countries directly (soft). Also modulates Domain/Industry "
            "overlap below: a match across countries is weighted up, a match within the same "
            "city is weighted down, since organic local discovery likely covers that already."
        ),
        "fields": ("operating_countries", "focus_geography", "country", "city"),
    },
    "stage_lifecycle_fit": {
        "label": "Stage / lifecycle fit",
        "description": (
            "Seeker's own lifecycle stage checked against the candidate's stated stage focus "
            "(e.g. an investor's thesis). Hard where the candidate has a structured stage-focus "
            "field, approximate elsewhere."
        ),
        "fields": ("stage", "stage_focus"),
    },
    "ticket_size_fit": {
        "label": "Ticket / deal size fit",
        "description": (
            "Seeker's funding ask checked against the candidate's ticket range — full credit "
            "inside the range, decaying the further outside it. Only evaluated when the seeker "
            "has Fundraising Toggle on; otherwise this dimension doesn't apply and its weight "
            "is redistributed to the others."
        ),
        "fields": ("fundraising_toggle", "fundraising_amount", "ticket_range"),
    },
    "non_capital_support_fit": {
        "label": "Non-capital support fit",
        "description": (
            "Fraction of the seeker's stated needs that the candidate's stated non-capital "
            "support offerings cover (e.g. regulatory help, networking). Placeholder tag-overlap "
            "logic until NLP extraction exists on the startup's free-text needs."
        ),
        "fields": ("needs", "support_offered"),
    },
    "stakeholder_pairwise_prior": {
        "label": "Stakeholder-type pairwise prior",
        "description": (
            "Baseline 'does type X typically want to meet type Y' prior, looked up from a "
            "placeholder Stakeholder Pair Matrix. Acts as a floor/ceiling under the other "
            "dimensions so a perfect Domain match between two unlikely-to-meet types can't "
            "outrank a mediocre match between two types that usually do want to meet."
        ),
        "fields": ("stakeholder_type",),
    },
    "sdg_alignment": {
        "label": "SDG / values alignment",
        "description": (
            "Jaccard overlap of UN SDG goal tags. A nice-to-have differentiator (v2, optional), "
            "not a primary signal — smallest weight in the model."
        ),
        "fields": ("sdg_goals",),
    },
}


def compute_match_score(profile_a: dict, profile_b: dict) -> dict:
    """Run all registered scorers and return per-parameter scores plus a weighted total.

    Scorers that return None are not applicable to this pair (missing data, or an unmet
    precondition like Fundraising Toggle) and are excluded from both the breakdown and the
    total — their weight is redistributed proportionally across the parameters that did apply.

    The returned dict also carries enough detail for a UI to explain each number:
    - "applicable_weights": the weight actually used per parameter (weight / applicable_weight)
    - "contributions": each parameter's share of the final total
    - "geography_modulation": category/factor applied to MODULATED_BY_GEOGRAPHY dimensions
    - "inputs": the raw field values each scorer read from profile_a / profile_b
    """
    category = geo_category(profile_a, profile_b)
    modulation = GEO_MODULATION.get(category, 1.0)
    breakdown = {}
    applicable_weights = {}
    contributions = {}
    applicable_weight = 0.0
    weighted_sum = 0.0
    for name, weight, scorer in SCORED_PARAMETERS:
        value = scorer(profile_a, profile_b)
        if value is None:
            continue
        if name in MODULATED_BY_GEOGRAPHY:
            value = min(1.0, value * modulation)
        breakdown[name] = value
        applicable_weight += weight
        weighted_sum += weight * value
    total = weighted_sum / applicable_weight if applicable_weight else 0.0
    for name, weight, _ in SCORED_PARAMETERS:
        if name not in breakdown:
            continue
        normalized_weight = weight / applicable_weight if applicable_weight else 0.0
        applicable_weights[name] = normalized_weight
        contributions[name] = normalized_weight * breakdown[name]

    inputs = {
        name: {
            "a": {f: profile_a.get(f) for f in info["fields"]},
            "b": {f: profile_b.get(f) for f in info["fields"]},
        }
        for name, info in PARAMETER_INFO.items()
    }

    return {
        "breakdown": breakdown,
        "total": total,
        "applicable_weights": applicable_weights,
        "contributions": contributions,
        "geography_modulation": {"category": category, "factor": modulation},
        "inputs": inputs,
    }


def rank_candidates(seeker: dict, candidates: list, top_n: int | None = None) -> list:
    """Score `seeker` against every profile in `candidates` and return them sorted best-first.

    Each result is {"candidate": profile, "score": <compute_match_score(seeker, candidate) dict>}.
    Does not call the LLM — this is the ranking pass; generate a narrative report separately
    (via match_profiles) only for whichever top candidates get shown to the user.
    """
    results = [
        {"candidate": candidate, "score": compute_match_score(seeker, candidate)}
        for candidate in candidates
    ]
    results.sort(key=lambda r: r["score"]["total"], reverse=True)
    if top_n is not None:
        results = results[:top_n]
    return results


def profile_to_text(profile: dict) -> str:
    lines = []
    for field in MATCH_FIELDS:
        value = profile.get(field)
        if not value:
            continue
        if isinstance(value, (list, tuple)):
            value = ", ".join(value)
        lines.append(f"{field.replace('_', ' ').title()}: {value}")
    return "\n".join(lines)


def match_profiles(profile_a: dict, profile_b: dict, shared_event: str | None = None) -> str:
    """Compare two attendee profiles and return a Markdown compatibility report."""
    text_a = profile_to_text(profile_a)
    text_b = profile_to_text(profile_b)

    event_context = f"Both are attending: {shared_event}\n\n" if shared_event else ""

    system_prompt = (
        "You are a matchmaking assistant for a climate-tech events platform. "
        "Compare the two attendee profiles below and assess networking/social compatibility.\n\n"
        f"{event_context}"
        "ATTENDEE A:\n"
        f"{text_a}\n\n"
        "ATTENDEE B:\n"
        f"{text_b}\n\n"
        "INSTRUCTIONS:\n"
        "Only use what is explicitly stated in the profiles above. Never invent shared "
        "interests, background, or affiliations that aren't stated.\n"
        "Generate a Markdown table of comparison points. Every row must contain:\n"
        "- Dimension (e.g. shared interest, complementary goal, industry overlap)\n"
        "- Status: Choose only [STRONG MATCH], [PARTIAL MATCH], or [NO OVERLAP]\n"
        "- Basis: What in each profile supports this row\n\n"
        "After the table, add a one-paragraph 'Suggested icebreaker' based only on stated overlap. "
        "If there is no meaningful overlap, say so plainly instead of forcing one."
    )

    if llm is None:
        raise RuntimeError("LLM explanation requires langchain-groq and python-dotenv")
    response = llm.invoke([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "Generate the compatibility report."},
    ])

    content = response.content
    if isinstance(content, str):
        return content
    return "".join(
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )


