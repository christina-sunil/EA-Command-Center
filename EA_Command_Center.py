import streamlit as st
import pandas as pd

st.set_page_config(
    page_title="EA Command Center",
    page_icon="📊",
    layout="wide"
)

st.title("Enterprise Applications Command Center")

tab1, tab2 = st.tabs([
    "Backlog",
    "Week in Review"
])

# =====================================================
# BACKLOG
# =====================================================

with tab1:

    st.header("Backlog")

    # KPI ROW

    c1,c2,c3,c4,c5,c6,c7,c8 = st.columns(8)

    c1.metric("Total", "Loading...")
    c2.metric("Access", "Loading...")
    c3.metric("L1", "Loading...")
    c4.metric("L2", "Loading...")
    c5.metric("L3", "Loading...")
    c6.metric("Assigned", "Loading...")
    c7.metric("Unassigned", "Loading...")
    c8.metric("Hybrid Med Age", "Loading...")

    st.markdown("---")

    # FILTERS

    f1,f2,f3,f4 = st.columns(4)

    with f1:
        team = st.multiselect(
            "Team",
            []
        )

    with f2:
        provider = st.multiselect(
            "Provider",
            []
        )

    with f3:
        view_option = st.selectbox(
            "View (Top10)",
            [
                "Oldest",
                "Newest",
                "Last Updated",
                "Highest Intervention Score"
            ]
        )

    with f4:
        interval_warning = st.selectbox(
            "Interval Warning",
            [
                "24hr",
                "48hr",
                "72hr",
                "120hr"
            ]
        )

    st.markdown("---")

    st.subheader("Team Scorecard")

    scorecard_df = pd.DataFrame(
        columns=[
            "Team",
            "Access",
            "L1",
            "L2",
            "L3",
            "Assigned",
            "Unassigned",
            "Hybrid Med Age"
        ]
    )

    st.dataframe(
        scorecard_df,
        use_container_width=True,
        hide_index=True
    )

    st.markdown("---")

    st.subheader("Top 10 Investigation")

    top10_df = pd.DataFrame(
        columns=[
            "Ticket",
            "Assigned To",
            "Assignment Group",
            "Priority",
            "Hybrid Age"
        ]
    )

    st.dataframe(
        top10_df,
        use_container_width=True,
        hide_index=True
    )

# =====================================================
# WEEK IN REVIEW
# =====================================================

with tab2:

    st.header("Week in Review")

    st.markdown(
        "Show me all tickets assigned to a selected Assignment Group during a selected period."
    )

    f1,f2 = st.columns(2)

    with f1:
        assignment_group = st.selectbox(
            "Assignment Group",
            []
        )

    with f2:
        period = st.selectbox(
            "Period",
            [
                "Week",
                "Month",
                "Quarter",
                "Year"
            ]
        )

    st.markdown("---")

    c1,c2,c3,c4,c5 = st.columns(5)

    c1.metric("Assigned", 0)
    c2.metric("Closed", 0)
    c3.metric("Backlog", 0)
    c4.metric("TTR", 0)
    c5.metric("Hybrid Age", 0)

    st.markdown("---")

    st.subheader("Themes and Trends")

    themes_df = pd.DataFrame(
        columns=[
            "Theme",
            "Count"
        ]
    )

    st.dataframe(
        themes_df,
        use_container_width=True,
        hide_index=True
    )

    st.markdown("---")

    st.subheader("Improvement Opportunities")

    opportunities_df = pd.DataFrame(
        columns=[
            "Opportunity",
            "Description"
        ]
    )

    st.dataframe(
        opportunities_df,
        use_container_width=True,
        hide_index=True
    )
