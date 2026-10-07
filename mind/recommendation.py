"""
mind/recommendation.py — Recommendation Engine layer.

Responsibility: transform raw relationship evidence from the store into
user-facing, categorized, explained recommendations.

The pipeline:
    Relationships (from store)
           ↓
    Collect evidence per unique candidate
           ↓
    Deduplicate (same candidate from multiple matchers → merge evidence)
           ↓
    Categorize by candidate type and stakeholder metadata
           ↓
    Generate evidence-based explanations ("Why am I seeing this?")
           ↓
    Rank by relevance_score (max single-matcher score — never blended average)
           ↓
    list[RecommendedCandidate]

Design rules:
  - Scores from different matchers are NEVER averaged or blended.
    relevance_score = max(evidence.score for evidence in candidate.evidence).
  - Categorization is system-generated from candidate metadata (stakeholder_type,
    entity_type) — NOT from user-stated goals.
  - Explanations are derived from actual signal scores. Nothing is hallucinated.
  - This layer is stateless and deterministic. It can be replaced by an LLM
    reasoning layer in future without changing Mind or the service layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.models import Relationship


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class MatchEvidence:
    """Provenance record for one matcher's contribution to a recommendation.

    Preserves the full chain: which matcher, what score, which signals,
    which relationship ID. Nothing is lost or averaged.
    """
    matcher_id: str
    score: float
    signals: dict[str, float]
    relationship_id: str


@dataclass
class RecommendedCandidate:
    """A recommended person, organization, or investor — fully explained.

    Attributes:
        candidate_id      : ID of the recommended entity.
        candidate_type    : entity type string ("USER" or "ORGANIZATION").
        candidate_name    : display name from the candidate pool.
        category          : system-generated section label for the UI.
                            One of:
                              "People you may want to meet"
                              "Organizations worth exploring"
                              "Potential investors"
        relevance_score   : max score across all evidence — NOT an average.
        reasons           : human-readable, evidence-based explanation list.
        evidence          : full provenance per matcher.
        source_matchers   : ordered list of matcher IDs that contributed evidence.
    """
    candidate_id: str
    candidate_type: str
    candidate_name: str
    category: str
    relevance_score: float
    reasons: list[str]
    evidence: list[MatchEvidence]
    source_matchers: list[str]

    # Category constants (as class attributes for tests/comparisons)
    CATEGORY_PEOPLE    = "People you may want to meet"
    CATEGORY_COMPANIES = "Organizations worth exploring"
    CATEGORY_INVESTORS = "Potential investors"


# ── Recommendation Engine ─────────────────────────────────────────────────────

class RecommendationEngine:
    """Transform relationship evidence into categorized, explained recommendations.

    Stateless — create one per recommendation request.
    Future extension point: pass LLM client here to enable narrative synthesis.
    """

    def build(
        self,
        relationships: list[Relationship],
        seeker_context: Any,          # core.context.UserContext
        candidate_pool: list[dict],
    ) -> list[RecommendedCandidate]:
        """Build a sorted list of RecommendedCandidates from relationship evidence.

        Steps:
          1. Group relationships by (candidate_type, candidate_id).
          2. Merge evidence from all matchers per candidate (deduplication).
          3. Categorize each candidate from its metadata.
          4. Generate evidence-based explanation reasons.
          5. Sort by relevance_score descending.

        Args:
            relationships : all persisted relationships involving the seeker.
            seeker_context: the UserContext of the person receiving recommendations.
            candidate_pool: all candidate profiles (EVENT_ATTENDEES + ORGANIZATIONS).
                            Used only for metadata lookup (name, stakeholder_type).
        """
        pool_by_id: dict[str, dict] = {p.get("id", ""): p for p in candidate_pool}
        seeker_id = seeker_context.user_id

        # Group relationships by the other entity
        grouped: dict[tuple[str, str], list[Relationship]] = {}
        for rel in relationships:
            if rel.source.id == seeker_id:
                other = rel.target
            elif rel.target.id == seeker_id:
                other = rel.source
            else:
                continue
            key = (other.type, other.id)
            grouped.setdefault(key, []).append(rel)

        candidates: list[RecommendedCandidate] = []
        for (ctype, cid), rels in grouped.items():
            cand_profile = pool_by_id.get(cid, {})

            # Build evidence list sorted best-first
            evidence = [
                MatchEvidence(
                    matcher_id=r.matcher_id,
                    score=r.score,
                    signals={k: v for k, v in r.signals.items() if v is not None},
                    relationship_id=r.relationship_id,
                )
                for r in sorted(rels, key=lambda r: r.score, reverse=True)
            ]

            # relevance_score = max single-matcher score (never averaged across matchers)
            relevance = max(ev.score for ev in evidence)

            # Categorize from candidate metadata — system-generated, not user-chosen
            category = self._categorize(ctype, cand_profile)

            # Generate evidence-based explanations
            reasons = self._explain(seeker_context, cand_profile, evidence)

            candidates.append(RecommendedCandidate(
                candidate_id=cid,
                candidate_type=ctype,
                candidate_name=cand_profile.get("name", cid),
                category=category,
                relevance_score=relevance,
                reasons=reasons,
                evidence=evidence,
                source_matchers=list(dict.fromkeys(ev.matcher_id for ev in evidence)),
            ))

        return sorted(candidates, key=lambda c: c.relevance_score, reverse=True)

    # ── Categorization ────────────────────────────────────────────────────────

    def _categorize(self, candidate_type: str, candidate_profile: dict) -> str:
        """System-generated category based on who the candidate IS.

        Rules (in priority order):
          1. If entity is a USER → "People you may want to meet"
          2. If entity is an ORGANIZATION with stakeholder_type "Investor" →
             "Potential investors"
          3. Otherwise (Partner, Sponsor, Attendee org, etc.) →
             "Organizations worth exploring"

        No user-stated goals are consulted. The category reflects the candidate's
        actual nature and registration data.
        """
        if candidate_type == "USER":
            return RecommendedCandidate.CATEGORY_PEOPLE

        # ORGANIZATION — inspect stakeholder type
        s_type = candidate_profile.get("stakeholder_type", "").strip().lower()
        if "investor" in s_type:
            return RecommendedCandidate.CATEGORY_INVESTORS

        return RecommendedCandidate.CATEGORY_COMPANIES

    # ── Explanation generation ────────────────────────────────────────────────

    def _explain(
        self,
        seeker_context: Any,
        candidate_profile: dict,
        evidence_list: list[MatchEvidence],
    ) -> list[str]:
        """Generate human-readable, evidence-based reasons for this recommendation.

        Rules:
          - Only facts supported by actual signal scores are stated.
          - Nothing is hallucinated.
          - Each reason maps to a specific signal above its threshold.
          - Capped at 4 reasons for UI clarity.
        """
        # Collect max signal value across all evidence (per signal name)
        all_signals: dict[str, float] = {}
        has_event_matcher = False
        for ev in evidence_list:
            if ev.matcher_id == "MM-EVENT-001":
                has_event_matcher = True
            for k, v in ev.signals.items():
                try:
                    fv = float(v)
                    all_signals[k] = max(all_signals.get(k, 0.0), fv)
                except (TypeError, ValueError):
                    pass

        reasons: list[str] = []

        # ── Domain / climate domain overlap ───────────────────────────────────
        domain_score = max(
            all_signals.get("professional_domain", 0.0),
            all_signals.get("climate_domain_overlap", 0.0),
        )
        if domain_score > 0.25:
            seeker_domains = {d.lower().strip() for d in seeker_context.domains}
            cand_domains = {
                d.lower().strip()
                for d in (
                    candidate_profile.get("domain")
                    or candidate_profile.get("professional_domain")
                    or []
                )
            }
            shared = seeker_domains & cand_domains
            if shared:
                sample = sorted(shared)[:2]
                reasons.append(
                    f"Shared climate focus: {' & '.join(d.title() for d in sample)}"
                )
            else:
                reasons.append("Active in a related climate domain")

        # ── Skills ────────────────────────────────────────────────────────────
        if all_signals.get("skills", 0.0) > 0.30:
            reasons.append("Complementary skills and expertise")

        # ── Interests ─────────────────────────────────────────────────────────
        elif all_signals.get("interests", 0.0) > 0.30:
            reasons.append("Overlapping professional interests")

        # ── Geography fit ─────────────────────────────────────────────────────
        if all_signals.get("geography_fit", 0.0) > 0.40:
            c_country = candidate_profile.get("country", "")
            seeker_countries: set[str] = {
                c.lower()
                for c in (
                    seeker_context.extra.get("operating_countries", [])
                    + ([seeker_context.extra.get("country")] if seeker_context.extra.get("country") else [])
                )
            }
            if c_country and c_country.lower() in seeker_countries:
                reasons.append(f"Both operating in {c_country}")
            elif c_country:
                reasons.append(f"Geographic focus includes {c_country}")
            else:
                reasons.append("Relevant geographic overlap")

        # ── Stage / lifecycle fit ─────────────────────────────────────────────
        if all_signals.get("stage_lifecycle_fit", 0.0) > 0.40:
            reasons.append("Organization stage aligns with your profile")

        # ── Investor / stakeholder fit ────────────────────────────────────────
        s_type = candidate_profile.get("stakeholder_type", "").lower()
        if "investor" in s_type and all_signals.get("stakeholder_pairwise_prior", 0.0) > 0.50:
            reasons.append("Investor aligned with your domain and stage")

        # ── Non-capital support ───────────────────────────────────────────────
        if all_signals.get("non_capital_support_fit", 0.0) > 0.25:
            reasons.append("Offers support relevant to your needs")

        # ── SDG alignment ─────────────────────────────────────────────────────
        if all_signals.get("sdg_alignment", 0.0) > 0.25:
            reasons.append("Shared sustainability goals (SDGs)")

        # ── Event context ─────────────────────────────────────────────────────
        if has_event_matcher:
            reasons.append("Both attending this event")

        # ── Industry overlap ──────────────────────────────────────────────────
        if not reasons and all_signals.get("industry_overlap", 0.0) > 0.20:
            reasons.append("Overlapping industry focus")

        # ── Fallback (always show something) ─────────────────────────────────
        if not reasons:
            reasons.append("Relevant match based on your profile and context")

        # Cap at 4 reasons for UI clarity
        return reasons[:4]
