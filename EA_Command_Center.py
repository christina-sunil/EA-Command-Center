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

# =========================================================
# BACKLOG
# =========================================================

with tab1:

    st.subheader("EA Command Center - Backlog")

    # KPI ROW
    c1,c2,c3,c4,c5,c6,c7,c8,c9 = st.columns(9)

    c1.metric("Total", 0)
    c2.metric("Access", 0)
    c3.metric("L1", 0)
    c4.metric("L2", 0)
    c5.metric("Sys Admin", 0)
    c6.metric("Dev / Eng", 0)
    c7.metric("Unassigned", 0)
    c8.metric("Assigned", 0)
    c9.metric("Hybrid Med Age", 0)

    st.divider()

    # FILTERS
    f1, f2, f3, f4 = st.columns(4)

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

    st.divider()

    st.subheader("Team Scorecard")

    scorecard_df = pd.DataFrame()

    st.dataframe(
        scorecard_df,
        use_container_width=True
    )

    st.divider()

    st.subheader("Top 10 Investigation")

    top10_df = pd.DataFrame()

    st.dataframe(
        top10_df,
        use_container_width=True
    )

# =========================================================
# WEEK IN REVIEW
# =========================================================

with tab2:

    st.subheader("EA Command Center - Week in Review")

    st.markdown(
        "### Show me all tickets assigned to a selected Assignment Group during a selected period"
    )

    c1, c2 = st.columns(2)

    with c1:
        assignment_group = st.selectbox(
            "Assignment Group",
            []
        )

    with c2:
        period = st.selectbox(
            "Period",
            [
                "Week",
                "Month",
                "Quarter",
                "Year"
            ]
        )

    st.divider()

    m1,m2,m3,m4,m5 = st.columns(5)

    m1.metric("Assigned", 0)
    m2.metric("Closed", 0)
    m3.metric("Backlog", 0)
    m4.metric("TTR", 0)
    m5.metric("Hybrid Age", 0)

    st.divider()

    st.subheader("Themes and Trends")

    trend_df = pd.DataFrame()

    st.dataframe(
        trend_df,
        use_container_width=True
    )

    st.divider()

    st.subheader("Improvement Opportunities")

    improvement_df = pd.DataFrame()

    st.dataframe(
        improvement_df,
        use_container_width=True
    )
