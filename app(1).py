import streamlit as st

from registry import get_matchmaker
from service import MatchmakingService
from relationships.store import InMemoryRelationshipStore
from mind.mind import Mind


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="Mosambi Matchmaking",
    page_icon="🤝",
    layout="wide",
)

st.title("🤝 Mosambi Matchmaking")
st.caption(
    "Independent Matchmakers → Relationship Store → Mind → Recommendations"
)


# ============================================================
# CORE SERVICES
# ============================================================

# Concrete implementation of the RelationshipStore interface.
store = InMemoryRelationshipStore()

# Service responsible for running matchmakers and persisting
# their results as relationships.
service = MatchmakingService(store)

# Mind consumes persisted relationships and produces recommendations.
mind = Mind(store)


# ============================================================
# SIDEBAR
# ============================================================

st.sidebar.title("Matchmaker")

matcher_id = st.sidebar.selectbox(
    "Select matchmaking system",
    [
        "MM-EVENT-001",
        "MM-ORG-001",
    ],
)

if matcher_id == "MM-EVENT-001":
    st.sidebar.info(
        "Event attendee matcher\n\n"
        "Finds attendees with similar interests, "
        "professional domains, roles, skills and "
        "networking objectives."
    )

elif matcher_id == "MM-ORG-001":
    st.sidebar.info(
        "Organization matcher\n\n"
        "Uses the organization's 9-dimensional "
        "compatibility scoring system."
    )


# ============================================================
# EVENT MATCHMAKER
# ============================================================

if matcher_id == "MM-EVENT-001":

    st.header("👥 Event Attendee Matchmaking")

    st.write(
        "Compare two attendees inside an event and create a "
        "typed matchmaking relationship."
    )

    st.divider()

    col_a, col_b = st.columns(2)

    # --------------------------------------------------------
    # ATTENDEE A
    # --------------------------------------------------------

    with col_a:

        st.subheader("Attendee A")

        id_a = st.text_input(
            "User ID",
            value="USER-A",
            key="event_id_a",
        )

        domain_a = st.text_input(
            "Professional domain",
            value="Climate Technology",
            key="event_domain_a",
        )

        interests_a = st.text_input(
            "Interests",
            value="battery recycling, climate finance, circular economy",
            key="event_interests_a",
        )

        role_a = st.text_input(
            "Role",
            value="Founder",
            key="event_role_a",
        )

        objective_a = st.text_input(
            "Networking objective",
            value="Find investors",
            key="event_objective_a",
        )

        skills_a = st.text_input(
            "Skills",
            value="AI, batteries, sustainability",
            key="event_skills_a",
        )

        experience_a = st.text_input(
            "Experience level",
            value="Senior",
            key="event_experience_a",
        )

        event_interest_a = st.text_input(
            "Event-specific interest",
            value="Climate finance",
            key="event_interest_a",
        )

    # --------------------------------------------------------
    # ATTENDEE B
    # --------------------------------------------------------

    with col_b:

        st.subheader("Attendee B")

        id_b = st.text_input(
            "User ID",
            value="USER-B",
            key="event_id_b",
        )

        domain_b = st.text_input(
            "Professional domain",
            value="Climate Technology",
            key="event_domain_b",
        )

        interests_b = st.text_input(
            "Interests",
            value="battery technology, climate finance, energy storage",
            key="event_interests_b",
        )

        role_b = st.text_input(
            "Role",
            value="Investor",
            key="event_role_b",
        )

        objective_b = st.text_input(
            "Networking objective",
            value="Find climate startups",
            key="event_objective_b",
        )

        skills_b = st.text_input(
            "Skills",
            value="Investment, energy, batteries",
            key="event_skills_b",
        )

        experience_b = st.text_input(
            "Experience level",
            value="Senior",
            key="event_experience_b",
        )

        event_interest_b = st.text_input(
            "Event-specific interest",
            value="Climate finance",
            key="event_interest_b",
        )

    st.divider()

    event_id = st.text_input(
        "Event ID",
        value="EVENT-2026",
        key="event_id",
    )

    # --------------------------------------------------------
    # CREATE MATCH
    # --------------------------------------------------------

    if st.button(
        "🤝 Find Match",
        type="primary",
        key="event_match_button",
    ):

        if not id_a or not id_b:

            st.error("Both attendees need a User ID.")

        elif id_a == id_b:

            st.error("Attendee A and Attendee B must be different users.")

        else:

            profile_a = {
                "id": id_a,
                "professional_domain": [
                    x.strip()
                    for x in domain_a.split(",")
                    if x.strip()
                ],
                "interests": [
                    x.strip()
                    for x in interests_a.split(",")
                    if x.strip()
                ],
                "role": role_a,
                "networking_objective": [
                    x.strip()
                    for x in objective_a.split(",")
                    if x.strip()
                ],
                "skills": [
                    x.strip()
                    for x in skills_a.split(",")
                    if x.strip()
                ],
                "experience_level": experience_a,
                "event_interest": [
                    x.strip()
                    for x in event_interest_a.split(",")
                    if x.strip()
                ],
            }

            profile_b = {
                "id": id_b,
                "professional_domain": [
                    x.strip()
                    for x in domain_b.split(",")
                    if x.strip()
                ],
                "interests": [
                    x.strip()
                    for x in interests_b.split(",")
                    if x.strip()
                ],
                "role": role_b,
                "networking_objective": [
                    x.strip()
                    for x in objective_b.split(",")
                    if x.strip()
                ],
                "skills": [
                    x.strip()
                    for x in skills_b.split(",")
                    if x.strip()
                ],
                "experience_level": experience_b,
                "event_interest": [
                    x.strip()
                    for x in event_interest_b.split(",")
                    if x.strip()
                ],
            }

            # ------------------------------------------------
            # RUN MATCHMAKER THROUGH SERVICE
            # ------------------------------------------------

            relationship = service.run_pair(
                matcher_id,
                profile_a,
                profile_b,
                context={
                    "event_id": event_id,
                },
            )

            # ------------------------------------------------
            # DISPLAY RESULT
            # ------------------------------------------------

            st.success("Match calculated and relationship stored.")

            score = relationship.score

            st.metric(
                "Compatibility Score",
                f"{score:.0%}",
            )

            st.subheader("Relationship")

            st.json(
                {
                    "relationship_id": relationship.relationship_id,
                    "matcher_id": relationship.matcher_id,
                    "relationship_type": relationship.relationship_type,
                    "source": {
                        "type": relationship.source.type,
                        "id": relationship.source.id,
                    },
                    "target": {
                        "type": relationship.target.type,
                        "id": relationship.target.id,
                    },
                    "score": relationship.score,
                    "signals": relationship.signals,
                    "context": relationship.context,
                }
            )

            st.subheader("Match Signals")

            signal_rows = []

            for name, value in relationship.signals.items():

                signal_rows.append(
                    {
                        "Parameter": name.replace("_", " ").title(),
                        "Score": f"{value:.0%}",
                    }
                )

            st.table(signal_rows)


# ============================================================
# ORGANIZATION MATCHMAKER
# ============================================================

elif matcher_id == "MM-ORG-001":

    st.header("🏢 Organization Matchmaking")

    st.write(
        "Run the organization matchmaking engine using "
        "the configured organization scoring system."
    )

    st.info(
        "The organization matcher is independent from the "
        "event attendee matcher."
    )

    st.markdown(
        """
### Organization Matcher

The organization matcher is identified as:

`MM-ORG-001`

It handles the organization-specific compatibility dimensions,
including:

- Climate Domain overlap
- Industry overlap
- Supply Chain Position
- Geography fit
- Stage / Lifecycle fit
- Ticket / Deal Size
- Non-capital support
- Stakeholder pairwise prior
- SDG alignment

The event matcher does **not** use these parameters.
"""
    )


# ============================================================
# MIND / RECOMMENDATIONS
# ============================================================

st.divider()

st.header("🧠 Mind")

st.write(
    "Mind does not calculate matchmaking scores. "
    "It consumes relationships produced by matchmakers."
)

mind_entity_id = st.text_input(
    "User ID to get recommendations for",
    value="USER-A",
    key="mind_user_id",
)

mind_event_id = st.text_input(
    "Event ID",
    value="EVENT-2026",
    key="mind_event_id",
)

if st.button(
    "🎯 Get Recommendations",
    key="recommend_button",
):

    recommendations = mind.recommend(
        "USER",
        mind_entity_id,
        context={
            "event_id": mind_event_id,
        },
        matcher_ids={
            "MM-EVENT-001",
        },
        top_n=10,
    )

    if not recommendations:

        st.info(
            "No relationships found for this user and event."
        )

    else:

        st.subheader(
            f"Recommendations for {mind_entity_id}"
        )

        for index, recommendation in enumerate(
            recommendations,
            start=1,
        ):

            with st.expander(
                f"#{index} — "
                f"{recommendation.candidate.type}:"
                f"{recommendation.candidate.id} "
                f"({recommendation.score:.0%})"
            ):

                st.write(
                    f"**Score:** {recommendation.score:.0%}"
                )

                st.write(
                    f"**Matchers:** "
                    f"{', '.join(recommendation.matcher_ids)}"
                )

                st.write(
                    f"**Relationships:** "
                    f"{', '.join(recommendation.relationship_ids)}"
                )

                st.write(
                    f"**Evidence count:** "
                    f"{recommendation.context.get('evidence_count', 0)}"
                )


# ============================================================
# ARCHITECTURE
# ============================================================

st.divider()

st.header("🏗️ Current Architecture")

st.code(
    """
                    USERS / ORGANIZATIONS
                            │
                            ▼
                  ┌───────────────────┐
                  │    MATCHMAKERS     │
                  │                   │
                  │ MM-EVENT-001      │
                  │ MM-ORG-001        │
                  │ Future Matchers   │
                  └─────────┬─────────┘
                            │
                            ▼
                  ┌───────────────────┐
                  │ RelationshipStore │
                  │                   │
                  │ Typed relationships
                  │ Score + signals   │
                  │ Context + reasons │
                  └─────────┬─────────┘
                            │
                            ▼
                  ┌───────────────────┐
                  │       MIND        │
                  │                   │
                  │ Context filtering │
                  │ Evidence grouping │
                  │ Recommendation    │
                  └─────────┬─────────┘
                            │
                            ▼
                    RECOMMENDATIONS
""",
    language="text",
)


# ============================================================
# DEBUG / MATCHER INFO
# ============================================================

with st.expander("🔧 Matcher Information"):

    matcher = get_matchmaker(matcher_id)

    st.write(
        "**Matcher ID:**",
        matcher.matcher_id,
    )

    st.write(
        "**Relationship Type:**",
        matcher.relationship_type,
    )

    if hasattr(matcher, "weights"):

        st.write(
            "**Configured Parameters:**"
        )

        st.json(matcher.weights)