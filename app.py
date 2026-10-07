"""
Mosambi Matchmaking — Streamlit Application (Mind Orchestration)
================================================================
New flow:
  User fills ONE profile (UserContext) + picks their goals + selects an event
      ↓
  Mind.plan() decides which matchers to invoke
      ↓
  service.run_for_user() scores against the appropriate pools, persists to store
      ↓
  Mind.recommend_for_user() reads the store → categorized recommendations
      ↓
  UI renders: 👤 People · 🏢 Companies · 💰 Investors — in separate sections

The user is never asked for the same information twice.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st

from core.context import (
    UserContext, EventContext, GoalType,
    infer_goal_types, missing_fields, GOAL_LABELS,
)
from core.models import RecommendationCategory
from mind.mind import Mind, CategorizedRecommendation
from relationships.store import InMemoryRelationshipStore
from service import MatchmakingService
from sample_data import EVENT_ATTENDEES, ORGANIZATIONS

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Mosambi · Mind",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS — only for custom HTML widgets ───────────────────────────────────────

st.markdown("""
<style>
#MainMenu, footer, header { visibility: hidden; }

.rank-circle {
    display: inline-flex; align-items: center; justify-content: center;
    width: 46px; height: 46px; border-radius: 50%;
    font-size: 0.95rem; font-weight: 800; color: #fff;
}
.score-pill {
    display: inline-block; padding: 2px 10px; border-radius: 99px;
    font-size: 0.78rem; font-weight: 700; margin: 2px 4px 2px 0;
}
.matcher-chip {
    display: inline-block; padding: 1px 7px; background: #dbeafe;
    color: #1d4ed8; border-radius: 4px; font-size: 0.71rem;
    font-weight: 700; font-family: monospace; margin-right: 4px;
}
.cat-header {
    font-size: 1.1rem; font-weight: 800;
    border-left: 4px solid #15803d;
    padding-left: 10px; margin: 20px 0 4px 0;
}
</style>
""", unsafe_allow_html=True)

# ── Constants ─────────────────────────────────────────────────────────────────

SC_LABELS = {
    1: "Raw Materials", 2: "Components", 3: "Manufacturing",
    4: "Distribution",  5: "Deployment / Services",
    6: "Finance / Investment", 7: "Policy / Regulatory",
}

CAT_ICONS = {
    RecommendationCategory.PEOPLE:        "👤",
    RecommendationCategory.COMPANIES:     "🏢",
    RecommendationCategory.INVESTORS:     "💰",
    RecommendationCategory.OPPORTUNITIES: "🤝",
}

# Goals exposed in the UI multiselect
GOAL_UI_OPTIONS: dict[str, str] = {
    "👤  Meet People":              GoalType.FIND_PEOPLE,
    "🤝  Find Collaborators":       GoalType.FIND_COLLABORATORS,
    "🏢  Find Companies & Partners":GoalType.FIND_COMPANIES,
    "💰  Find Investors":           GoalType.FIND_INVESTORS,
}

# ── Session state ─────────────────────────────────────────────────────────────

def _init_state() -> None:
    if "store"   not in st.session_state:
        st.session_state.store   = InMemoryRelationshipStore()
    if "service" not in st.session_state:
        st.session_state.service = MatchmakingService(st.session_state.store)
    if "mind"    not in st.session_state:
        st.session_state.mind    = Mind(st.session_state.store)
    for k, v in {
        "user_context":   None,
        "event_context":  None,
        "categorized":    [],     # list[CategorizedRecommendation]
        "run_results":    {},     # dict[matcher_id → list[Relationship]]
        "missing_hints":  [],
    }.items():
        st.session_state.setdefault(k, v)

_init_state()
ss = st.session_state

# ── Helpers ───────────────────────────────────────────────────────────────────

def _csv(text: str) -> list[str]:
    return [x.strip() for x in text.split(",") if x.strip()]

def _score_bar(score: float, height: int = 10) -> str:
    pct   = int(score * 100)
    color = "#16a34a" if score >= 0.70 else "#d97706" if score >= 0.50 else "#dc2626"
    label = "Strong"  if score >= 0.70 else "Good"    if score >= 0.50 else "Weak"
    return (
        f'<div style="display:flex;align-items:center;gap:10px;padding:3px 0">'
        f'<div style="flex:1;background:#e5e7eb;border-radius:99px;height:{height}px;overflow:hidden">'
        f'<div style="width:{pct}%;background:{color};height:{height}px;border-radius:99px"></div></div>'
        f'<span style="font-size:0.9rem;font-weight:800;color:{color};min-width:40px">{pct}%</span>'
        f'<span style="font-size:0.71rem;color:#9ca3af;min-width:44px">{label}</span></div>'
    )

def _rank_badge(rank: int) -> str:
    color = {1: "#f59e0b", 2: "#94a3b8", 3: "#b45309"}.get(rank, "#6366f1")
    return f'<div class="rank-circle" style="background:{color}">#{rank}</div>'

def _rel_map(results: dict) -> dict:
    """Flatten run_results → relationship_id: Relationship lookup."""
    out = {}
    for rels in results.values():
        for r in rels:
            out[r.relationship_id] = r
    return out

def _meta(cid: str, pools: list[dict]) -> dict:
    return next((p for p in pools if p.get("id") == cid), {})

def _needs_org_fields(goals: list[str]) -> bool:
    gt = infer_goal_types(goals)
    return bool(gt & {GoalType.FIND_COMPANIES, GoalType.FIND_INVESTORS})


# ── SIDEBAR ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 🌿 Mosambi")
    st.caption("Climate-tech event matchmaking")
    st.divider()

    with st.form("profile_form", border=False):

        # ── Identity ─────────────────────────────────────────────────────────
        st.markdown("#### 👤 Your Profile")
        name = st.text_input("Your name *", placeholder="e.g. Aarav Kulkarni")
        uid  = st.text_input("Your ID", value="SEEKER-001")

        roles_opts = ["Founder", "Investor", "Researcher", "Policy Lead",
                      "Engineer", "Corporate Sustainability Director",
                      "Speaker", "Organiser", "Other"]
        roles = st.multiselect("Role(s)", roles_opts, default=["Founder"])
        exp   = st.selectbox("Experience level",
                             ["Junior", "Mid-level", "Senior", "Executive"], index=2)

        # ── Professional ──────────────────────────────────────────────────────
        st.markdown("**Professional background**")
        domains   = st.text_input("Climate domains",
                                  placeholder="Climate Technology, Clean Energy")
        skills    = st.text_input("Skills",
                                  placeholder="battery manufacturing, operations")
        interests = st.text_input("Interests",
                                  placeholder="battery technology, climate finance")

        # ── Goals ─────────────────────────────────────────────────────────────
        st.markdown("**What I'm looking for**")
        goal_labels = st.multiselect(
            "Select your goals",
            options=list(GOAL_UI_OPTIONS.keys()),
            default=["👤  Meet People", "💰  Find Investors"],
            help="Mind will invoke only the relevant matchers for your goals.",
        )

        # ── Event context ─────────────────────────────────────────────────────
        st.markdown("**Event context**")
        event_id     = st.text_input("Event ID", value="EVENT-2026",
                                     help="Leave blank to skip event-attendee matching")
        event_themes = st.text_input("Event themes",
                                     placeholder="clean energy, climate finance",
                                     help="Optional — enriches event-interest signal")

        # ── Org-specific extras ───────────────────────────────────────────────
        with st.expander("🏢 Organization / investor details"):
            st.caption("Fill this section when looking for companies or investors.")
            s_type  = st.selectbox("Stakeholder type",
                                   ["Attendee", "Investor", "Sponsor", "Partner",
                                    "Speaker", "Press / Media", "Organiser"])
            col_c, col_n = st.columns(2)
            with col_c:
                city    = st.text_input("City", placeholder="Mumbai")
            with col_n:
                country = st.text_input("Country", placeholder="India")
            op_ctry = st.text_input("Operating countries",
                                    placeholder="India, Singapore")
            sc_stages = st.multiselect(
                "Supply chain stage(s)",
                options=list(SC_LABELS.keys()),
                format_func=lambda x: f"{x} · {SC_LABELS[x]}",
            )
            org_stage    = st.text_input("Lifecycle stage",
                                         placeholder="Seed / Series A / Growth")
            fund_on      = st.checkbox("Actively fundraising")
            fund_amount  = None
            if fund_on:
                fund_amount = st.number_input(
                    "Fundraising ask (USD)", min_value=0,
                    value=1_000_000, step=100_000, format="%d",
                )
            sdg = st.multiselect("UN SDG Goals",
                                 [f"SDG {i}" for i in range(1, 18)])

        # ── Submit ────────────────────────────────────────────────────────────
        submitted = st.form_submit_button(
            "🧠  Find My Matches", type="primary", use_container_width=True
        )

    if submitted:
        if not name.strip():
            st.error("Please enter your name.")
        elif not goal_labels:
            st.error("Please select at least one goal.")
        else:
            selected_goals = [GOAL_UI_OPTIONS[l] for l in goal_labels]

            user_ctx = UserContext(
                user_id=uid.strip() or "SEEKER-001",
                name=name.strip(),
                roles=roles or ["Other"],
                experience_level=exp,
                domains=_csv(domains),
                skills=_csv(skills),
                interests=_csv(interests),
                goals=selected_goals,
                extra={
                    "stakeholder_type": s_type,
                    "city":             city.strip() or None,
                    "country":          country.strip() or None,
                    "operating_countries": _csv(op_ctry),
                    "supply_chain_stage":  sc_stages,
                    "stage":            org_stage.strip() or None,
                    "fundraising_toggle":  fund_on,
                    "fundraising_amount":  fund_amount,
                    "sdg_goals":        sdg,
                },
            )

            event_ctx = None
            if event_id.strip():
                event_ctx = EventContext(
                    event_id=event_id.strip(),
                    themes=_csv(event_themes),
                )

            with st.spinner("🧠 Mind is planning your recommendations…"):
                run_results = ss.service.run_for_user(
                    user_ctx, event_ctx,
                    people_pool=EVENT_ATTENDEES,
                    org_pool=ORGANIZATIONS,
                )
                cats = ss.mind.recommend_for_user(user_ctx, event_ctx, top_n=6)
                hints = missing_fields(user_ctx, infer_goal_types(selected_goals))

            ss.user_context  = user_ctx
            ss.event_context = event_ctx
            ss.categorized   = cats
            ss.run_results   = run_results
            ss.missing_hints = hints

            total = sum(len(c.items) for c in cats)
            st.success(f"✅  {total} recommendation{'s' if total != 1 else ''} across {len(cats)} categor{'ies' if len(cats) != 1 else 'y'}")

    st.divider()
    if st.button("🔄  Reset session", use_container_width=True):
        for k in list(ss.keys()):
            del ss[k]
        _init_state()
        st.rerun()


# ── MAIN TABS ─────────────────────────────────────────────────────────────────

tab_mind, tab_profile, tab_backend = st.tabs(
    ["🧠  Mind", "👤  My Profile", "⚙️  Backend"]
)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — MIND RECOMMENDATIONS
# ══════════════════════════════════════════════════════════════════════════════

with tab_mind:

    # ── Welcome state ─────────────────────────────────────────────────────────
    if not ss.user_context:
        st.markdown("## 🌿 Welcome to Mosambi Mind")
        st.write(
            "Fill in your profile once in the sidebar and click **Find My Matches**. "
            "Mind will decide which matchers are relevant for your goals and return "
            "categorized, explained recommendations — no separate questionnaires per matcher."
        )
        st.divider()
        c1, c2, c3 = st.columns(3)
        with c1:
            with st.container(border=True):
                st.markdown("**1 · Enter your profile once**")
                st.caption("Name, roles, domains, skills, interests — shared across all matchers.")
        with c2:
            with st.container(border=True):
                st.markdown("**2 · Choose your goals**")
                st.caption("Find People · Find Investors · Find Companies · Find Collaborators")
        with c3:
            with st.container(border=True):
                st.markdown("**3 · Mind does the rest**")
                st.caption("Categorized recommendations: 👤 People · 🏢 Companies · 💰 Investors")
        st.stop()

    if not ss.categorized:
        st.warning(
            "No matches found above the minimum threshold for your current goals. "
            "Try broadening your domains, interests, or adding more goals."
        )
        st.stop()

    # ── Header ────────────────────────────────────────────────────────────────
    uc = ss.user_context
    ec = ss.event_context
    st.markdown(f"## Recommendations for **{uc.name}**")

    goal_text = ", ".join(GOAL_LABELS.get(g, g) for g in uc.goals)
    ev_text   = f"  ·  Event `{ec.event_id}`" if ec else ""
    st.caption(
        f"Goals: {goal_text}{ev_text}  ·  "
        f"{sum(len(c.items) for c in ss.categorized)} total matches"
    )
    if ss.missing_hints:
        with st.expander("💡 Optional profile improvements"):
            st.caption("Filling these fields would improve your match quality:")
            for hint in ss.missing_hints:
                st.markdown(f"- {hint}")

    st.divider()

    all_pools = EVENT_ATTENDEES + ORGANIZATIONS
    lookup    = _rel_map(ss.run_results)

    # ── Categorized recommendation sections ───────────────────────────────────
    for cat in ss.categorized:
        icon = CAT_ICONS.get(cat.category, "📌")

        st.markdown(
            f'<div class="cat-header">{icon}  {cat.category.value}</div>',
            unsafe_allow_html=True,
        )
        st.caption(f"_{cat.rationale}_  ·  matcher `{cat.matcher_id}`")

        for rank_i, rec in enumerate(cat.items, start=1):
            m     = _meta(rec.candidate.id, all_pools)
            name  = m.get("name", rec.candidate.id)
            role  = m.get("role") or m.get("stakeholder_type", "")

            # Pull signals from the strongest relationship
            signals: dict = {}
            for rid in rec.relationship_ids:
                if rid in lookup:
                    signals = lookup[rid].signals
                    break

            top3 = sorted(signals.items(), key=lambda x: x[1], reverse=True)[:3]

            with st.container(border=True):
                col_badge, col_name, col_bar = st.columns([1, 5, 4])

                with col_badge:
                    st.markdown(_rank_badge(rank_i), unsafe_allow_html=True)

                with col_name:
                    st.markdown(f"### {name}")
                    if role:
                        st.caption(role)
                    chips = " ".join(
                        f'<span class="matcher-chip">{mid}</span>'
                        for mid in rec.matcher_ids
                    )
                    st.markdown(chips, unsafe_allow_html=True)

                with col_bar:
                    st.markdown("<br>", unsafe_allow_html=True)
                    st.markdown(_score_bar(rec.score), unsafe_allow_html=True)

                # Signal pills
                if top3:
                    pills = ""
                    for sname, sval in top3:
                        if sval >= 0.70:
                            bg, fg = "#dcfce7", "#15803d"
                        elif sval >= 0.40:
                            bg, fg = "#fef9c3", "#92400e"
                        else:
                            bg, fg = "#f1f5f9", "#64748b"
                        label = sname.replace("_", " ").title()
                        pills += (
                            f'<span class="score-pill" '
                            f'style="background:{bg};color:{fg};border:1px solid {fg}22">'
                            f'{label}: {sval:.0%}</span>'
                        )
                    st.markdown(pills, unsafe_allow_html=True)

                with st.expander("Full score breakdown"):
                    if signals:
                        st.table([
                            {
                                "Signal": k.replace("_", " ").title(),
                                "Score":  f"{v:.1%}",
                                "Strength": (
                                    "🟢 Strong" if v >= 0.70
                                    else "🟡 Moderate" if v >= 0.40
                                    else "⚫ Weak"
                                ),
                            }
                            for k, v in sorted(signals.items(),
                                               key=lambda x: x[1], reverse=True)
                        ])
                    else:
                        st.caption("No signal breakdown available.")
                    st.caption(
                        f"Relationship: `{'`, `'.join(rec.relationship_ids)}`  \n"
                        f"Reasons: {', '.join(rec.reasons) or '—'}"
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
        st.markdown("**Roles**");         st.write(", ".join(uc.roles) or "—")
        st.markdown("**Experience**");    st.write(uc.experience_level or "—")
        st.markdown("**Domains**");       st.write(", ".join(uc.domains) or "—")
        st.markdown("**Skills**");        st.write(", ".join(uc.skills) or "—")
        st.markdown("**Interests**");     st.write(", ".join(uc.interests) or "—")
    with col_r:
        st.markdown("**Goals**")
        for g in uc.goals:
            st.write(f"• {GOAL_LABELS.get(g, g)}")
        st.markdown("**Event**")
        if ec:
            st.write(f"`{ec.event_id}` — {ec.name or 'unnamed'}")
            if ec.themes:
                st.caption(f"Themes: {', '.join(ec.themes)}")
        else:
            st.write("No event context")
        if uc.extra.get("country"):
            st.markdown("**Country**"); st.write(uc.extra["country"])

    # Org extras summary (collapsed by default)
    x = uc.extra
    org_filled = any([
        x.get("stakeholder_type"), x.get("supply_chain_stage"),
        x.get("fundraising_toggle"), x.get("sdg_goals"),
    ])
    if org_filled:
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
                    st.write(f"Yes — ${amt:,.0f}")
                else:
                    st.write("Not actively fundraising")
                st.markdown("**SDG Goals**")
                st.write(", ".join(x.get("sdg_goals") or []) or "—")

    st.divider()

    # Metrics
    mc1, mc2, mc3 = st.columns(3)
    user_rels = ss.store.get_for_entity("USER", uc.user_id)
    org_rels  = ss.store.get_for_entity("ORGANIZATION", uc.user_id)
    mc1.metric("People relationships", len(user_rels))
    mc2.metric("Org relationships", len(org_rels))
    mc3.metric("Matchers run", len(ss.run_results))

    # Missing fields hints
    if ss.missing_hints:
        st.divider()
        st.markdown("**💡 Optional profile improvements**")
        st.caption("Filling these fields would improve match quality for your current goals:")
        for hint in ss.missing_hints:
            st.markdown(f"- {hint}")
    else:
        if ss.user_context:
            st.success("✅ Your profile is complete for your selected goals.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — BACKEND
# ══════════════════════════════════════════════════════════════════════════════

with tab_backend:
    st.markdown("## ⚙️  Backend")
    st.caption("Internal state — not shown to end users in production.")

    b1, b2, b3 = st.tabs(["Relationship Store", "Last Run", "Architecture"])

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
                        "Context":  ", ".join(
                            f"{k}={v}" for k, v in r.context.items()
                            if k not in ("minimum_score", "score_detail")
                        ) or "—",
                        "Rel ID":   r.relationship_id[:18] + "…",
                    }
                    for r in sorted(all_rels, key=lambda r: r.score, reverse=True)
                ],
                use_container_width=True, hide_index=True,
            )

            st.markdown("### Inspect a relationship")
            opts    = {r.relationship_id: f"{r.matcher_id} · {r.source.id} → {r.target.id} · {r.score:.1%}"
                       for r in all_rels}
            chosen_id = st.selectbox("Select", list(opts), format_func=lambda x: opts[x])
            chosen    = ss.store._relationships.get(chosen_id)
            if chosen:
                st.json({
                    "relationship_id": chosen.relationship_id,
                    "matcher_id":      chosen.matcher_id,
                    "source": {"type": chosen.source.type, "id": chosen.source.id},
                    "target": {"type": chosen.target.type, "id": chosen.target.id},
                    "score":  chosen.score, "signals": chosen.signals,
                    "context": {k: v for k, v in chosen.context.items()
                                if k != "score_detail"},
                })

    # ── Last Run ──────────────────────────────────────────────────────────────
    with b2:
        st.markdown("### Per-matcher · per-candidate breakdown")
        if not ss.run_results:
            st.info("Run a match from the sidebar first.")
        else:
            uc = ss.user_context
            all_pools = EVENT_ATTENDEES + ORGANIZATIONS

            for matcher_id, rels in ss.run_results.items():
                st.markdown(f"#### `{matcher_id}` — {len(rels)} candidates scored")
                seeker_id = uc.user_id if uc else ""

                for rel in rels:
                    tid   = rel.target.id if rel.source.id == seeker_id else rel.source.id
                    m     = _meta(tid, all_pools)
                    cname = m.get("name", tid)

                    with st.expander(f"{cname}  —  {rel.score:.1%}"):
                        el, er = st.columns([3, 2])
                        with el:
                            st.markdown("**Signals**")
                            for sig, val in sorted(
                                rel.signals.items(), key=lambda x: x[1], reverse=True
                            ):
                                st.caption(sig.replace("_", " ").title())
                                st.markdown(_score_bar(val, height=8),
                                            unsafe_allow_html=True)
                        with er:
                            st.json({
                                "score":   rel.score,
                                "matcher": rel.matcher_id,
                                "rel_id":  rel.relationship_id[:20] + "…",
                            })

    # ── Architecture ──────────────────────────────────────────────────────────
    with b3:
        st.markdown("### Mind orchestration flow")
        st.code("""
UserContext (enter once)
        │
        ▼
Mind.plan()                 ← Phase A: goal-aware routing
  ├── infer_goal_types()    ← keyword → GoalType constant
  └── get_matchers_for_goals()  ← MATCHER_CAPABILITIES routing table
        │
        ▼
service.run_for_user()
  ├── to_event_profile()    ← UserContext → MM-EVENT-001 dict
  ├── to_org_profile()      ← UserContext → MM-ORG-001 dict
  └── rank_pool()           ← calls each matcher, upserts to store
        │
        ▼
RelationshipStore  (InMemoryRelationshipStore — Phase 1)
        │
        ▼
Mind.recommend_for_user()   ← Phase B: categorized synthesis
  ├── reads store via existing recommend()
  ├── groups by matcher → RecommendationCategory
  └── NEVER blends scores across matcher types
        │
        ▼
list[CategorizedRecommendation]
  ├── 👤 People   (MM-EVENT-001)
  ├── 🏢 Companies (MM-ORG-001)
  └── ... future matchers added via MATCHER_CAPABILITIES only
        """, language="text")

        st.markdown("### MATCHER_CAPABILITIES routing table")
        from registry import MATCHER_CAPABILITIES
        st.json({
            mid: {
                "goal_types":         list(cap.goal_types),
                "seeker_entity_type": cap.seeker_entity_type,
                "category":           cap.category.value,
                "needs_event_context":cap.needs_event_context,
            }
            for mid, cap in MATCHER_CAPABILITIES.items()
        })

        st.markdown("### Phase-1 limitations")
        for title, desc in [
            ("In-memory store",
             "Relationships reset on page hard-refresh. Phase 2 replaces with PostgreSQL."),
            ("Keyword goal routing",
             "infer_goal_types() uses keyword stems. Phase 4 will add LLM-based routing "
             "via the plan() seam — no other code changes required."),
            ("O(n) scoring",
             "Seeker is scored against every candidate. Phase 3 adds vector pre-filtering."),
            ("Scores not blended across categories",
             "This is a deliberate design choice, not a limitation. Each category's "
             "score comes from exactly one matcher to preserve provenance."),
        ]:
            st.warning(f"**{title}:** {desc}")
