"""
Mosambi Matchmaking — Streamlit Application (Proactive Recommendations)
========================================================================
Product philosophy:
  User provides profile + selects an event.
  System understands who they are and what context they are in.
  System proactively discovers relevant people, organizations, and investors.
  User explores — no goal selection required.

Flow:
  UserContext (enter once)
        ↓
  Mind.plan()  [profile-driven — no goals needed]
        ↓
  service.run_for_user()  [scores against people_pool + org_pool]
        ↓
  RelationshipStore  [evidence persisted]
        ↓
  Mind.recommend_for_user()  →  RecommendationEngine
        ↓
  list[RecommendedCandidate]  [deduped, categorized, explained]
        ↓
  UI: "Recommended for You"
       ├── People you may want to meet
       ├── Organizations worth exploring
       └── Potential investors
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
import streamlit as st

from core.context import (
    UserContext, EventContext,
    GoalType, infer_goal_types, missing_fields, to_event_profile,
)
from mind.mind import Mind
from mind.recommendation import RecommendedCandidate
from relationships.store import InMemoryRelationshipStore
from service import MatchmakingService
from sample_data import EVENT_ATTENDEES, ORGANIZATIONS

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Mosambi",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ───────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
#MainMenu, footer, header { visibility: hidden; }

.rank-badge {
    display: inline-flex; align-items: center; justify-content: center;
    width: 42px; height: 42px; border-radius: 50%;
    font-size: 0.9rem; font-weight: 800; color: #fff; flex-shrink: 0;
}
.score-bar-wrap {
    display: flex; align-items: center; gap: 10px; padding: 3px 0;
}
.score-bar-track {
    flex: 1; background: #e5e7eb; border-radius: 99px; height: 9px; overflow: hidden;
}
.score-bar-fill { height: 9px; border-radius: 99px; }
.reason-tag {
    display: inline-block; padding: 3px 10px; margin: 2px 3px 2px 0;
    border-radius: 99px; font-size: 0.75rem; font-weight: 600;
    background: #f0fdf4; color: #15803d; border: 1px solid #bbf7d0;
}
.cat-section {
    font-size: 1.05rem; font-weight: 800;
    border-left: 4px solid #15803d; padding-left: 10px;
    margin: 28px 0 6px 0;
}
.matcher-chip {
    display: inline-block; padding: 1px 7px;
    background: #dbeafe; color: #1d4ed8;
    border-radius: 4px; font-size: 0.68rem;
    font-weight: 700; font-family: monospace; margin-right: 4px;
}
</style>
""", unsafe_allow_html=True)

# ── Constants ─────────────────────────────────────────────────────────────────

SC_LABELS = {
    1: "Raw Materials", 2: "Components", 3: "Manufacturing",
    4: "Distribution",  5: "Deployment / Services",
    6: "Finance / Investment", 7: "Policy / Regulatory",
}

CAT_ORDER = [
    RecommendedCandidate.CATEGORY_PEOPLE,
    RecommendedCandidate.CATEGORY_COMPANIES,
    RecommendedCandidate.CATEGORY_INVESTORS,
]

CAT_ICONS = {
    RecommendedCandidate.CATEGORY_PEOPLE:    "👤",
    RecommendedCandidate.CATEGORY_COMPANIES: "🏢",
    RecommendedCandidate.CATEGORY_INVESTORS: "💰",
}

ALL_CANDIDATES = EVENT_ATTENDEES + ORGANIZATIONS

# ── Session state ─────────────────────────────────────────────────────────────

def _init_state() -> None:
    if "store" not in st.session_state:
        st.session_state.store   = InMemoryRelationshipStore()
    if "service" not in st.session_state:
        st.session_state.service = MatchmakingService(st.session_state.store)
    if "mind" not in st.session_state:
        st.session_state.mind    = Mind(st.session_state.store)
    for k, v in {
        "user_context":  None,
        "event_context": None,
        "candidates":    [],      # list[RecommendedCandidate]
        "run_results":   {},
        "hints":         [],
        "prefill_data":  {},      # dict populated by Excel uploader
    }.items():
        st.session_state.setdefault(k, v)

_init_state()
ss = st.session_state

# ── Helpers ───────────────────────────────────────────────────────────────────

def _csv(text: str) -> list[str]:
    return [x.strip() for x in text.split(",") if x.strip()]

def _pool_lookup() -> dict[str, dict]:
    return {p.get("id", ""): p for p in ALL_CANDIDATES}

def _score_html(score: float) -> str:
    pct   = int(score * 100)
    color = "#16a34a" if score >= 0.70 else "#d97706" if score >= 0.50 else "#dc2626"
    label = "Strong" if score >= 0.70 else "Good" if score >= 0.50 else "Weak"
    return (
        f'<div class="score-bar-wrap">'
        f'<div class="score-bar-track">'
        f'<div class="score-bar-fill" style="width:{pct}%;background:{color}"></div></div>'
        f'<span style="font-size:0.9rem;font-weight:800;color:{color};min-width:38px">{pct}%</span>'
        f'<span style="font-size:0.7rem;color:#9ca3af">{label}</span></div>'
    )

def _rank_html(rank: int) -> str:
    color = {1: "#f59e0b", 2: "#94a3b8", 3: "#b45309"}.get(rank, "#6366f1")
    return f'<div class="rank-badge" style="background:{color}">#{rank}</div>'

def _reason_pills(reasons: list[str]) -> str:
    return "".join(
        f'<span class="reason-tag">✓ {r}</span>' for r in reasons
    )


# ── Excel / Demo Mode helpers ─────────────────────────────────────────────────

# Flexible column name aliases — tries each name in order, first non-blank wins.
_COL_ALIASES: dict[str, list[str]] = {
    "name":               ["name", "Name", "full_name", "Full Name", "attendee_name", "Attendee"],
    "user_id":            ["id", "ID", "user_id", "User ID", "attendee_id", "Attendee ID"],
    "roles":              ["role", "roles", "Role", "Roles", "role(s)", "Role(s)", "designation"],
    "experience_level":   ["experience_level", "experience", "Experience", "Experience Level", "seniority", "Seniority"],
    "domains":            ["domains", "domain", "Domain", "Domains", "climate_domain",
                           "Climate Domain", "professional_domain", "Professional Domain"],
    "skills":             ["skills", "Skills", "skill", "Skill", "expertise", "Expertise"],
    "interests":          ["interests", "Interests", "interest", "Interest", "focus_areas"],
    "stakeholder_type":   ["stakeholder_type", "Stakeholder Type", "stakeholder", "Stakeholder", "type", "Type"],
    "country":            ["country", "Country", "hq_country", "HQ Country"],
    "city":               ["city", "City", "hq_city", "HQ City"],
    "operating_countries":["operating_countries", "Operating Countries", "countries", "Countries"],
    "supply_chain_stage": ["supply_chain_stage", "Supply Chain Stage", "supply_chain", "sc_stage", "SC Stage"],
    "stage":              ["stage", "Stage", "lifecycle_stage", "Lifecycle Stage", "org_stage", "Company Stage"],
    "fundraising_toggle": ["fundraising_toggle", "fundraising", "Fundraising", "is_fundraising", "raising", "Raising"],
    "fundraising_amount": ["fundraising_amount", "Fundraising Amount", "ask", "Ask", "raise", "Raise", "target_raise"],
    "sdg_goals":          ["sdg_goals", "SDG Goals", "sdg", "SDG", "un_goals", "UN Goals"],
    "event_id":           ["event_id", "Event ID", "event", "Event"],
    "event_themes":       ["event_themes", "Event Themes", "themes", "Themes"],
}


def _excel_str(row: dict, field: str, default: str = "") -> str:
    """Return the first non-blank value for a field from its column aliases."""
    for col in _COL_ALIASES.get(field, [field]):
        v = row.get(col)
        if v is not None and str(v).strip() and str(v).strip().lower() != "nan":
            return str(v).strip()
    return default


def _excel_list(row: dict, field: str) -> list[str]:
    """Return a list by splitting the first non-blank value for a field."""
    raw = _excel_str(row, field)
    if not raw:
        return []
    return [x.strip() for x in raw.replace(";", ",").split(",") if x.strip()]


def _excel_bool(row: dict, field: str) -> bool:
    """Parse truthy Excel values (Yes / True / 1 / ✓) as True."""
    raw = _excel_str(row, field).lower()
    return raw in ("yes", "true", "1", "✓", "x", "on")


def _excel_int(row: dict, field: str, default: int = 0) -> int:
    try:
        return int(float(_excel_str(row, field, str(default))))
    except (ValueError, TypeError):
        return default


def _parse_excel(uploaded_file) -> pd.DataFrame | None:
    """Read .xlsx / .xls / .csv upload into a DataFrame. Returns None on error."""
    try:
        name_lower = uploaded_file.name.lower()
        if name_lower.endswith(".csv"):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)
        # Normalise column names — strip whitespace
        df.columns = [str(c).strip() for c in df.columns]
        return df
    except Exception as e:
        st.error(f"Could not parse file: {e}")
        return None


def _find_name_column(df: pd.DataFrame) -> str | None:
    """Find whichever column holds the attendee name."""
    for alias in _COL_ALIASES["name"]:
        if alias in df.columns:
            return alias
    return df.columns[0] if len(df.columns) > 0 else None


# ── SIDEBAR ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 🌿 Mosambi")
    st.caption("Proactive climate-tech matchmaking")
    st.divider()

    # ── Demo Mode — Excel Upload ───────────────────────────────────────────────
    with st.expander("📂 Demo Mode — Load from Excel", expanded=False):
        st.caption(
            "Upload an attendee list (.xlsx / .csv). "
            "Select a name and click **Fill Profile** to auto-populate the form below."
        )
        uploaded = st.file_uploader(
            "Attendee list", type=["xlsx", "xls", "csv"],
            label_visibility="collapsed",
        )

        if uploaded is not None:
            df_excel = _parse_excel(uploaded)
            if df_excel is not None and len(df_excel) > 0:
                name_col = _find_name_column(df_excel)
                if name_col:
                    names_in_sheet = df_excel[name_col].astype(str).tolist()
                    chosen_name = st.selectbox(
                        "Select attendee", names_in_sheet,
                        key="excel_name_picker",
                    )
                    if st.button("📋 Fill Profile", use_container_width=True, type="secondary"):
                        row = df_excel[df_excel[name_col].astype(str) == chosen_name].iloc[0].to_dict()
                        ss.prefill_data = row
                        st.success(f"Profile filled for **{chosen_name}** — review and submit below.")
                        st.rerun()
                else:
                    st.warning("Could not detect a name column in the sheet.")
            elif df_excel is not None:
                st.warning("The uploaded file appears to be empty.")

        if ss.prefill_data:
            p = ss.prefill_data
            filled_name = _excel_str(p, "name", "Unknown")
            st.info(f"Currently prefilled: **{filled_name}**")
            if st.button("✕ Clear prefill", use_container_width=True):
                ss.prefill_data = {}
                st.rerun()

    st.divider()

    # ── Shorthand for prefill lookup ───────────────────────────────────────────
    p = ss.prefill_data   # empty dict when nothing loaded

    # ── Roles options (shared between prefill validation and widget) ───────────
    _ROLES_OPTS = [
        "Founder", "Investor", "Researcher", "Policy Lead",
        "Engineer", "Corporate Sustainability Director",
        "Speaker", "Organiser", "Other",
    ]
    _EXP_OPTS   = ["Junior", "Mid-level", "Senior", "Executive"]
    _STYPE_OPTS = ["Attendee", "Investor", "Sponsor", "Partner",
                   "Speaker", "Press / Media", "Organiser"]

    # Pre-compute prefill values (safe — returns "" or [] when p is empty)
    _p_name     = _excel_str(p, "name")
    _p_uid      = _excel_str(p, "user_id")
    _p_roles    = [r for r in _excel_list(p, "roles") if r in _ROLES_OPTS]
    _p_exp      = _excel_str(p, "experience_level")
    _p_domains  = ", ".join(_excel_list(p, "domains"))
    _p_skills   = ", ".join(_excel_list(p, "skills"))
    _p_interests= ", ".join(_excel_list(p, "interests"))
    _p_event_id = _excel_str(p, "event_id")
    _p_evt_thm  = ", ".join(_excel_list(p, "event_themes"))
    _p_stype    = _excel_str(p, "stakeholder_type")
    _p_city     = _excel_str(p, "city")
    _p_country  = _excel_str(p, "country")
    _p_opctr    = ", ".join(_excel_list(p, "operating_countries"))
    _p_sc_raw   = _excel_list(p, "supply_chain_stage")
    _p_sc       = [int(x) for x in _p_sc_raw if x.isdigit() and int(x) in SC_LABELS]
    _p_stage    = _excel_str(p, "stage")
    _p_fund_on  = _excel_bool(p, "fundraising_toggle")
    _p_fund_amt = _excel_int(p, "fundraising_amount", 1_000_000)
    _p_sdg_raw  = _excel_list(p, "sdg_goals")
    _p_sdg      = [s for s in _p_sdg_raw if s in [f"SDG {i}" for i in range(1, 18)]]

    with st.form("profile_form", border=False):

        # ── Identity ──────────────────────────────────────────────────────────
        st.markdown("#### 👤 Your Profile")
        name = st.text_input("Your name *",
                             value=_p_name,
                             placeholder="e.g. Aarav Kulkarni")
        uid  = st.text_input("Your ID",
                             value=_p_uid or "SEEKER-001")

        roles = st.multiselect(
            "Role(s)", _ROLES_OPTS,
            default=_p_roles or ["Founder"],
        )
        _exp_idx = _EXP_OPTS.index(_p_exp) if _p_exp in _EXP_OPTS else 2
        exp = st.selectbox("Experience level", _EXP_OPTS, index=_exp_idx)

        # ── Professional ──────────────────────────────────────────────────────
        st.markdown("**Professional background**")
        domains   = st.text_input("Climate domains",
                                  value=_p_domains,
                                  placeholder="Climate Technology, Clean Energy")
        skills    = st.text_input("Skills",
                                  value=_p_skills,
                                  placeholder="battery manufacturing, operations")
        interests = st.text_input("Interests",
                                  value=_p_interests,
                                  placeholder="battery technology, climate finance")

        # ── Event ─────────────────────────────────────────────────────────────
        st.markdown("**Event context**")
        event_id     = st.text_input("Event ID",
                                     value=_p_event_id or "EVENT-2026")
        event_themes = st.text_input("Event themes",
                                     value=_p_evt_thm,
                                     placeholder="clean energy, climate finance")

        # ── Organization details ──────────────────────────────────────────────
        with st.expander("🏢 Organization details"):
            st.caption("Complete this section to improve organization & investor matching.")
            _stype_idx = _STYPE_OPTS.index(_p_stype) if _p_stype in _STYPE_OPTS else 0
            s_type  = st.selectbox("Stakeholder type", _STYPE_OPTS, index=_stype_idx)
            col_c, col_n = st.columns(2)
            with col_c:
                city    = st.text_input("City", value=_p_city, placeholder="Mumbai")
            with col_n:
                country = st.text_input("Country", value=_p_country, placeholder="India")
            op_ctry   = st.text_input("Operating countries",
                                      value=_p_opctr,
                                      placeholder="India, Singapore")
            sc_stages = st.multiselect(
                "Supply chain stage(s)",
                options=list(SC_LABELS.keys()),
                format_func=lambda x: f"{x} · {SC_LABELS[x]}",
                default=_p_sc,
            )
            org_stage = st.text_input("Lifecycle stage",
                                      value=_p_stage,
                                      placeholder="Seed / Series A / Growth")
            fund_on   = st.checkbox("Actively fundraising", value=_p_fund_on)
            fund_amt  = None
            if fund_on:
                fund_amt = st.number_input(
                    "Fundraising ask (USD)", min_value=0,
                    value=_p_fund_amt, step=100_000, format="%d",
                )
            sdg = st.multiselect("UN SDG Goals",
                                 [f"SDG {i}" for i in range(1, 18)],
                                 default=_p_sdg)

        # ── Submit ────────────────────────────────────────────────────────────
        submitted = st.form_submit_button(
            "🧠  Get My Recommendations", type="primary", use_container_width=True
        )

    if submitted:
        if not name.strip():
            st.error("Please enter your name.")
        else:
            user_ctx = UserContext(
                user_id=uid.strip() or "SEEKER-001",
                name=name.strip(),
                roles=roles or ["Other"],
                experience_level=exp,
                domains=_csv(domains),
                skills=_csv(skills),
                interests=_csv(interests),
                goals=[],   # proactive mode — no user-stated goals
                extra={
                    "stakeholder_type":    s_type,
                    "city":                city.strip() or None,
                    "country":             country.strip() or None,
                    "operating_countries": _csv(op_ctry),
                    "supply_chain_stage":  sc_stages,
                    "stage":               org_stage.strip() or None,
                    "fundraising_toggle":  fund_on,
                    "fundraising_amount":  fund_amt,
                    "sdg_goals":           sdg,
                },
            )
            event_ctx = None
            if event_id.strip():
                event_ctx = EventContext(
                    event_id=event_id.strip(),
                    themes=_csv(event_themes),
                )

            with st.spinner("🧠 Discovering your recommendations…"):
                run_results = ss.service.run_for_user(
                    user_ctx, event_ctx,
                    people_pool=EVENT_ATTENDEES, org_pool=ORGANIZATIONS,
                )
                candidates = ss.mind.recommend_for_user(
                    user_ctx, event_ctx,
                    candidate_pool=ALL_CANDIDATES, top_n=12,
                )
                # Internal goal inference for profile hints only (not shown as UI selection)
                internal_goals = infer_goal_types(user_ctx.roles + user_ctx.domains)
                hints = missing_fields(user_ctx, internal_goals)

            ss.user_context  = user_ctx
            ss.event_context = event_ctx
            ss.candidates    = candidates
            ss.run_results   = run_results
            ss.hints         = hints

            st.success(
                f"✅  {len(candidates)} recommendation{'s' if len(candidates) != 1 else ''} found"
            )

    st.divider()
    if st.button("🔄  Reset session", use_container_width=True):
        for k in list(ss.keys()):
            del ss[k]
        _init_state()
        st.rerun()


# ── MAIN TABS ─────────────────────────────────────────────────────────────────

tab_reco, tab_profile, tab_backend = st.tabs(
    ["🌿  Recommended for You", "👤  My Profile", "⚙️  Backend"]
)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — RECOMMENDED FOR YOU
# ══════════════════════════════════════════════════════════════════════════════

with tab_reco:

    if not ss.user_context:
        # ── Welcome / empty state ─────────────────────────────────────────────
        st.markdown("## 🌿 Welcome to Mosambi")
        st.write(
            "Fill in your profile in the sidebar and click **Get My Recommendations**. "
            "Mosambi will automatically discover people, organizations, and investors "
            "that are relevant to who you are and the event you are attending — "
            "no goal selection required."
        )
        st.divider()
        c1, c2, c3 = st.columns(3)
        for col, icon, title, desc in [
            (c1, "1️⃣", "Enter your profile once",
             "Name, role, domain, skills, interests — shared across all matching capabilities."),
            (c2, "2️⃣", "Select an event",
             "The event provides context. Mosambi uses it to understand who else is in the room."),
            (c3, "3️⃣", "Explore your recommendations",
             "People · Organizations · Investors — proactively surfaced, fully explained."),
        ]:
            with col:
                with st.container(border=True):
                    st.markdown(f"**{icon} {title}**")
                    st.caption(desc)
        st.stop()

    if not ss.candidates:
        st.warning(
            "No recommendations found above the minimum threshold. "
            "Try completing your organization details (country, domains, supply chain stage)."
        )
        st.stop()

    # ── Header ────────────────────────────────────────────────────────────────
    uc = ss.user_context
    ec = ss.event_context
    ev_text = f"  ·  Event `{ec.event_id}`" if ec else ""
    st.markdown(f"## Recommended for **{uc.name}**")
    st.caption(
        f"{len(ss.candidates)} recommendations{ev_text}  ·  "
        f"Profile: {', '.join(uc.roles)}  ·  {', '.join(uc.domains[:2]) or 'No domains set'}"
    )

    if ss.hints:
        with st.expander("💡 Improve your matches"):
            st.caption("Adding these details would improve match quality:")
            for hint in ss.hints:
                st.markdown(f"- {hint}")

    # ── Group candidates by category ──────────────────────────────────────────
    by_cat: dict[str, list[RecommendedCandidate]] = defaultdict(list)
    for c in ss.candidates:
        by_cat[c.category].append(c)

    for cat in CAT_ORDER:
        items = by_cat.get(cat)
        if not items:
            continue

        icon = CAT_ICONS.get(cat, "📌")
        st.markdown(
            f'<div class="cat-section">{icon}&nbsp; {cat}</div>',
            unsafe_allow_html=True,
        )

        global_rank = 0
        for cand in items:
            global_rank += 1

            with st.container(border=True):
                col_badge, col_info, col_score = st.columns([1, 5, 3])

                with col_badge:
                    st.markdown(_rank_html(global_rank), unsafe_allow_html=True)

                with col_info:
                    st.markdown(f"### {cand.candidate_name}")
                    # Matcher provenance chips
                    chips = " ".join(
                        f'<span class="matcher-chip">{m}</span>'
                        for m in cand.source_matchers
                    )
                    st.markdown(chips, unsafe_allow_html=True)

                with col_score:
                    st.markdown("<br>", unsafe_allow_html=True)
                    st.markdown(_score_html(cand.relevance_score), unsafe_allow_html=True)

                # "Why am I seeing this?" reason tags
                if cand.reasons:
                    st.markdown(
                        _reason_pills(cand.reasons),
                        unsafe_allow_html=True,
                    )

                # Expandable detail
                with st.expander("Signal breakdown & evidence"):
                    # All signals across all evidence
                    all_signals: dict[str, float] = {}
                    for ev in cand.evidence:
                        for k, v in ev.signals.items():
                            try:
                                all_signals[k] = max(all_signals.get(k, 0.0), float(v))
                            except (TypeError, ValueError):
                                pass

                    if all_signals:
                        rows = [
                            {
                                "Signal": k.replace("_", " ").title(),
                                "Score":  f"{v:.1%}",
                                "Strength": (
                                    "🟢 Strong" if v >= 0.70
                                    else "🟡 Moderate" if v >= 0.40
                                    else "⚫ Weak"
                                ),
                            }
                            for k, v in sorted(all_signals.items(),
                                               key=lambda x: x[1], reverse=True)
                        ]
                        st.table(rows)

                    # Evidence per matcher
                    for ev in cand.evidence:
                        st.caption(
                            f"`{ev.matcher_id}` — score: {ev.score:.1%}  ·  "
                            f"rel: `{ev.relationship_id[:20]}…`"
                        )

        st.markdown("")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — MY PROFILE
# ══════════════════════════════════════════════════════════════════════════════

with tab_profile:
    if not ss.user_context:
        st.info("Fill in your profile in the sidebar to see your summary here.")
        st.stop()

    uc = ss.user_context
    ec = ss.event_context

    st.markdown(f"## {uc.name}")
    st.caption(f"ID: `{uc.user_id}`")
    st.divider()

    col_l, col_r = st.columns(2)
    with col_l:
        for label, value in [
            ("Roles",      ", ".join(uc.roles) or "—"),
            ("Experience", uc.experience_level or "—"),
            ("Domains",    ", ".join(uc.domains) or "—"),
            ("Skills",     ", ".join(uc.skills) or "—"),
            ("Interests",  ", ".join(uc.interests) or "—"),
        ]:
            st.markdown(f"**{label}**")
            st.write(value)

    with col_r:
        st.markdown("**Event**")
        if ec:
            st.write(f"`{ec.event_id}`")
            if ec.themes:
                st.caption(f"Themes: {', '.join(ec.themes)}")
        else:
            st.write("No event selected")

        if uc.extra.get("country"):
            st.markdown("**Country**")
            st.write(uc.extra["country"])

        st.markdown("**Recommendation mode**")
        st.write("🤖 Proactive — system discovers opportunities from your profile")

    # Org extras summary
    x = uc.extra
    if any([x.get("stakeholder_type"), x.get("supply_chain_stage"),
            x.get("fundraising_toggle"), x.get("sdg_goals")]):
        with st.expander("Organization details"):
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Stakeholder type**")
                st.write(x.get("stakeholder_type") or "—")
                st.markdown("**Supply chain stage(s)**")
                stages = [f"{s} · {SC_LABELS.get(s, s)}"
                          for s in (x.get("supply_chain_stage") or [])]
                st.write(", ".join(stages) or "—")
            with c2:
                st.markdown("**Fundraising**")
                if x.get("fundraising_toggle"):
                    amt = x.get("fundraising_amount") or 0
                    st.write(f"Yes — \${amt:,.0f}")
                else:
                    st.write("Not actively fundraising")
                st.markdown("**SDG Goals**")
                st.write(", ".join(x.get("sdg_goals") or []) or "—")

    st.divider()

    mc1, mc2, mc3 = st.columns(3)
    user_rels = ss.store.get_for_entity("USER", uc.user_id)
    org_rels  = ss.store.get_for_entity("ORGANIZATION", uc.user_id)
    mc1.metric("People scored", len(user_rels))
    mc2.metric("Orgs scored", len(org_rels))
    mc3.metric("Recommendations surfaced", len(ss.candidates))

    if ss.hints:
        st.divider()
        st.markdown("**💡 Profile improvements**")
        for hint in ss.hints:
            st.markdown(f"- {hint}")
    elif ss.user_context:
        st.success("✅ Your profile is complete for the current matching context.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — BACKEND
# ══════════════════════════════════════════════════════════════════════════════

with tab_backend:
    st.markdown("## ⚙️  Backend")
    st.caption("Internal state — for development visibility only.")

    b1, b2, b3 = st.tabs(["Relationship Store", "Scoring Breakdown", "Architecture"])

    # ── Relationship Store ────────────────────────────────────────────────────
    with b1:
        all_rels = list(ss.store._relationships.values())
        st.markdown(f"### {len(all_rels)} relationship(s) in store")
        if not all_rels:
            st.info("Run a match from the sidebar first.")
        else:
            st.dataframe(
                [
                    {
                        "Matcher":  r.matcher_id,
                        "Type":     r.relationship_type,
                        "Source":   f"{r.source.type}:{r.source.id}",
                        "Target":   f"{r.target.type}:{r.target.id}",
                        "Score":    round(r.score, 4),
                        "Rel ID":   r.relationship_id[:20] + "…",
                    }
                    for r in sorted(all_rels, key=lambda r: r.score, reverse=True)
                ],
                use_container_width=True, hide_index=True,
            )

    # ── Scoring Breakdown ─────────────────────────────────────────────────────
    with b2:
        if not ss.run_results:
            st.info("Run a match from the sidebar first.")
        else:
            uc = ss.user_context
            pool_map = _pool_lookup()
            for matcher_id, rels in ss.run_results.items():
                st.markdown(f"#### `{matcher_id}` — {len(rels)} candidates scored")
                seeker_id = uc.user_id if uc else ""
                for rel in rels:
                    tid   = rel.target.id if rel.source.id == seeker_id else rel.source.id
                    cname = pool_map.get(tid, {}).get("name", tid)
                    with st.expander(f"{cname}  —  {rel.score:.1%}"):
                        if rel.signals:
                            st.table([
                                {
                                    "Signal": k.replace("_", " ").title(),
                                    "Score":  f"{v:.1%}",
                                }
                                for k, v in sorted(
                                    rel.signals.items(), key=lambda x: x[1], reverse=True
                                )
                            ])
                        st.caption(f"Rel ID: `{rel.relationship_id[:24]}…`")

    # ── Architecture ──────────────────────────────────────────────────────────
    with b3:
        st.markdown("### Proactive recommendation flow")
        st.code("""
UserContext (enter once — no goal selection)
        │
        ▼
Mind.plan()                         ← profile-driven, context-aware
  └── get_all_matchers_for_context()
        │  Returns every matcher whose context requirements are met.
        │  No user-stated goals required.
        │
        ▼
service.run_for_user()
  ├── to_event_profile()  → MM-EVENT-001  (if event provided)
  ├── to_org_profile()    → MM-ORG-001    (always)
  └── rank_pool()         → upserts to RelationshipStore
        │
        ▼
RelationshipStore  (evidence / memory)
        │
        ▼
Mind.recommend_for_user()
  └── RecommendationEngine.build()
        ├── Collect evidence per unique candidate
        ├── Deduplicate (same candidate from multiple matchers → merge)
        ├── Categorize from candidate metadata (stakeholder_type)
        │     USER       → "People you may want to meet"
        │     Investor   → "Potential investors"
        │     Other Org  → "Organizations worth exploring"
        ├── Explain from actual signal scores (no hallucination)
        └── relevance_score = max(evidence.score)  ← never blended
        │
        ▼
list[RecommendedCandidate]
  ├── 👤 People you may want to meet
  ├── 🏢 Organizations worth exploring
  └── 💰 Potential investors
        """, language="text")

        st.markdown("### MATCHER_CAPABILITIES")
        from registry import MATCHER_CAPABILITIES
        st.json({
            mid: {
                "capabilities":       list(cap.capabilities),
                "seeker_entity_type": cap.seeker_entity_type,
                "needs_event_context":cap.needs_event_context,
            }
            for mid, cap in MATCHER_CAPABILITIES.items()
        })

        st.markdown("### Phase-1 architectural notes")
        for title, desc in [
            ("Profile-driven routing",
             "plan() invokes all registered matchers whose context requirements are met. "
             "No user goal selection. LLM seam: replace get_all_matchers_for_context() body."),
            ("networking_objective",
             "Derived from roles+domains — who the user IS. No hard-coded role→goal rules. "
             "The EventMatchmaker's Jaccard scorer determines compatibility from these signals."),
            ("Score non-blending",
             "relevance_score = max(evidence.score). Matcher provenance always preserved. "
             "Scores from MM-EVENT-001 and MM-ORG-001 are never averaged together."),
            ("In-memory store",
             "Relationships reset on page refresh. Phase 2 replaces with PostgreSQL."),
        ]:
            st.info(f"**{title}**: {desc}")
