import os
import math
from datetime import timedelta

import numpy as np
import pandas as pd
import requests
import streamlit as st


# =====================================================
# PAGE CONFIGURATION
# =====================================================

st.set_page_config(
    page_title="EA Command Center",
    page_icon="📊",
    layout="wide",
)


# =====================================================
# SERVICE NOW CONFIGURATION
# Credentials must be stored in Streamlit Secrets.
# Do not paste passwords into this file.
# =====================================================

INSTANCE_URL = "https://progress1.service-now.com"

USERNAME = "github_servicenow_api"
PASSWORD = "wL<c&sLHGso(mH3mIRs=byF5C%97o>P3z[K+QZSD"

# =====================================================
# ASSIGNMENT GROUP CONFIGURATION
# =====================================================

EA_GROUPS = [
    "IT Supp: EAST - Delivery",
    "IT Supp: EAST - Leads",
    "IT Supp: System Access Requests",
    "IT Supp: System Admins",
    "IT Supp: ShareFile - CPQ",
    "IT Supp: Quote to Invoice",
    "IT Supp: Lead to Opp",
    "IT Supp: Mulesoft Product Support",
    "IT Supp: EA Shared Services",
    "IT Supp: CS/TS",
]

GROUP_QUERY = ",".join(EA_GROUPS)


# =====================================================
# HELPER FUNCTIONS
# =====================================================

def clean_display(value):
    if isinstance(value, dict):
        return (
            value.get("display_value", "")
            or value.get("value", "")
            or ""
        )

    if value is None:
        return ""

    return str(value).strip()


def map_priority(priority):
    value = str(priority).lower().strip()

    if value.startswith("1") or "critical" in value:
        return "Critical"

    if value.startswith("2") or "high" in value:
        return "High"

    if (
        value.startswith("3")
        or "moderate" in value
        or "medium" in value
    ):
        return "Medium"

    if value.startswith("4") or "low" in value:
        return "Low"

    return "Other"


def level_from_group(group_name):
    group_name = str(group_name)

    if "System Access Requests" in group_name:
        return "Access"

    if "EAST - Delivery" in group_name:
        return "L1"

    if "EAST - Leads" in group_name:
        return "L2"

    if "System Admins" in group_name:
        return "Sys Admin"

    if (
        "ShareFile - CPQ" in group_name
        or "Quote to Invoice" in group_name
        or "Lead to Opp" in group_name
        or "Mulesoft Product Support" in group_name
        or "EA Shared Services" in group_name
        or "CS/TS" in group_name
    ):
        return "Dev / Eng"

    return "Other"


def business_days_between(start_timestamp, end_timestamp):
    if pd.isna(start_timestamp) or pd.isna(end_timestamp):
        return np.nan

    start_date = pd.Timestamp(start_timestamp).date()
    end_date = pd.Timestamp(end_timestamp).date()

    if end_date <= start_date:
        return 0.0

    return float(np.busday_count(start_date, end_date))


def period_start(period_name):
    today = pd.Timestamp.now().normalize()

    if period_name == "Week":
        return today - pd.Timedelta(days=today.weekday())

    if period_name == "Month":
        return today.replace(day=1)

    if period_name == "Quarter":
        quarter_month = ((today.month - 1) // 3) * 3 + 1
        return today.replace(month=quarter_month, day=1)

    return today.replace(month=1, day=1)


def interval_to_days(interval_name):
    interval_map = {
        "24hr": 1,
        "48hr": 2,
        "72hr": 3,
        "120hr": 5,
    }

    return interval_map.get(interval_name, 5)


def priority_score(priority):
    score_map = {
        "Critical": 10,
        "High": 8,
        "Medium": 5,
        "Low": 2,
        "Other": 1,
    }

    return score_map.get(priority, 1)


def threshold_score(value, thresholds):
    if pd.isna(value):
        return 0

    result = 1

    for minimum, score in thresholds:
        if value >= minimum:
            result = score
        else:
            break

    return result


AGE_THRESHOLDS = [
    (0, 1),
    (3, 2),
    (7, 4),
    (14, 6),
    (30, 8),
    (60, 9),
    (90, 10),
]

INACTIVITY_THRESHOLDS = [
    (0, 1),
    (2, 3),
    (5, 5),
    (10, 7),
    (20, 9),
    (30, 10),
]

REASSIGNMENT_THRESHOLDS = [
    (0, 1),
    (1, 3),
    (2, 5),
    (4, 7),
    (6, 9),
    (8, 10),
]


# =====================================================
# SERVICE NOW DATA RETRIEVAL
# =====================================================

@st.cache_data(show_spinner="Loading Progress tickets...")
def load_table(table_name, query, fields, max_rows=10000):
    if not USERNAME or not PASSWORD:
        raise RuntimeError(
            "ServiceNow credentials are missing. "
            "Add SERVICENOW_USERNAME and SERVICENOW_PASSWORD "
            "in Streamlit Secrets."
        )

    url = f"{INSTANCE_URL}/api/now/table/{table_name}"

    page_size = 2000
    pages = max(1, math.ceil(max_rows / page_size))
    all_rows = []

    for page_number in range(pages):
        offset = page_number * page_size
        remaining_rows = max_rows - offset

        if remaining_rows <= 0:
            break

        params = {
            "sysparm_query": query,
            "sysparm_display_value": "true",
            "sysparm_exclude_reference_link": "true",
            "sysparm_limit": str(min(page_size, remaining_rows)),
            "sysparm_offset": str(offset),
            "sysparm_fields": fields,
        }

        response = requests.get(
            url,
            params=params,
            auth=(USERNAME, PASSWORD),
            headers={"Accept": "application/json"},
            timeout=60,
        )

        if response.status_code >= 400:
            try:
                error_details = response.json()
            except Exception:
                error_details = response.text

            raise RuntimeError(
                f"ServiceNow API error for {table_name}: "
                f"{response.status_code} - {error_details}"
            )

        result = response.json().get("result", [])

        if not result:
            break

        all_rows.extend(result)

        if len(result) < page_size:
            break

    return pd.DataFrame(all_rows)


def prepare_dataframe(dataframe, ticket_type):
    if dataframe.empty:
        return dataframe

    work = dataframe.copy()
    work["ticket_type"] = ticket_type

    required_columns = [
        "number",
        "short_description",
        "assignment_group",
        "assigned_to",
        "priority",
        "state",
        "sys_created_on",
        "sys_updated_on",
        "closed_at",
        "reassignment_count",
    ]

    for column in required_columns:
        if column not in work.columns:
            work[column] = ""

    work["assignment_group"] = work["assignment_group"].apply(
        clean_display
    )
    work["assigned_to"] = work["assigned_to"].apply(clean_display)
    work["state"] = work["state"].apply(clean_display)
    work["priority"] = work["priority"].apply(map_priority)
    work["short_description"] = work["short_description"].apply(
        clean_display
    )

    work["open_date"] = pd.to_datetime(
        work["sys_created_on"],
        errors="coerce",
    )
    work["updated_date"] = pd.to_datetime(
        work["sys_updated_on"],
        errors="coerce",
    )
    work["closed_date"] = pd.to_datetime(
        work["closed_at"],
        errors="coerce",
    )

    work["reassignment_count"] = pd.to_numeric(
        work["reassignment_count"],
        errors="coerce",
    ).fillna(0)

    work["level"] = work["assignment_group"].apply(level_from_group)

    return work


@st.cache_data(show_spinner="Preparing EA Command Center data...")
def get_command_center_data(max_rows=10000):
    fields = (
        "number,short_description,assignment_group,assigned_to,"
        "priority,state,active,sys_created_on,sys_updated_on,"
        "closed_at,reassignment_count"
    )

    open_query = (
        f"active=true^assignment_group.nameIN{GROUP_QUERY}"
    )

    current_year = pd.Timestamp.now().year
    review_start = f"{current_year}-01-01 00:00:00"

    review_query = (
        f"assignment_group.nameIN{GROUP_QUERY}"
        f"^sys_created_on>={review_start}"
    )

    open_ritm = load_table(
        "sc_req_item",
        open_query,
        fields,
        max_rows,
    )
    open_incident = load_table(
        "incident",
        open_query,
        fields,
        max_rows,
    )

    review_ritm = load_table(
        "sc_req_item",
        review_query,
        fields,
        max_rows,
    )
    review_incident = load_table(
        "incident",
        review_query,
        fields,
        max_rows,
    )

    open_ritm = prepare_dataframe(open_ritm, "RITM")
    open_incident = prepare_dataframe(open_incident, "INC")

    review_ritm = prepare_dataframe(review_ritm, "RITM")
    review_incident = prepare_dataframe(review_incident, "INC")

    backlog = pd.concat(
        [open_ritm, open_incident],
        ignore_index=True,
    )

    review = pd.concat(
        [review_ritm, review_incident],
        ignore_index=True,
    )

    now = pd.Timestamp.now()

    if not backlog.empty:
        backlog["ticket_age_days"] = backlog["open_date"].apply(
            lambda value: business_days_between(value, now)
        )

        backlog["inactivity_days"] = backlog["updated_date"].apply(
            lambda value: business_days_between(value, now)
        )

        backlog["age_score"] = backlog["ticket_age_days"].apply(
            lambda value: threshold_score(
                value,
                AGE_THRESHOLDS,
            )
        )

        backlog["inactivity_score"] = backlog[
            "inactivity_days"
        ].apply(
            lambda value: threshold_score(
                value,
                INACTIVITY_THRESHOLDS,
            )
        )

        backlog["priority_score"] = backlog["priority"].apply(
            priority_score
        )

        backlog["reassignment_score"] = backlog[
            "reassignment_count"
        ].apply(
            lambda value: threshold_score(
                value,
                REASSIGNMENT_THRESHOLDS,
            )
        )

        backlog["intervention_score"] = (
            backlog["age_score"] * 0.35
            + backlog["inactivity_score"] * 0.30
            + backlog["priority_score"] * 0.20
            + backlog["reassignment_score"] * 0.15
        ).round(2)

    if not review.empty:
        review["ticket_age_days"] = review.apply(
            lambda row: business_days_between(
                row["open_date"],
                row["closed_date"]
                if pd.notna(row["closed_date"])
                else now,
            ),
            axis=1,
        )

        review["ttr_days"] = review.apply(
            lambda row: business_days_between(
                row["open_date"],
                row["closed_date"],
            )
            if pd.notna(row["closed_date"])
            else np.nan,
            axis=1,
        )

    return backlog, review


# =====================================================
# LOAD DATA
# =====================================================

st.title("Enterprise Applications Command Center")
st.caption(
    "Progress ticket operational scorecard. "
    "Age calculations exclude Saturday and Sunday."
)

control_col1, control_col2 = st.columns([3, 1])

with control_col1:
    max_to_load = st.selectbox(
        "Maximum records to load per table",
        [2000, 5000, 10000, 20000],
        index=2,
    )

with control_col2:
    st.write("")
    st.write("")

    if st.button("Refresh data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

try:
    df_backlog, df_review = get_command_center_data(max_to_load)
except Exception as error:
    st.error(str(error))
    st.info(
        "Add the ServiceNow username and password in "
        "Streamlit Secrets before running the dashboard."
    )
    st.stop()


tab1, tab2 = st.tabs(
    [
        "Backlog",
        "Week in Review",
    ]
)


# =====================================================
# BACKLOG TAB
# =====================================================

with tab1:
    st.header("Backlog")

    if df_backlog.empty:
        st.warning("No active Progress tickets were returned.")
    else:
        filter_col1, filter_col2 = st.columns(2)

        with filter_col1:
            selected_groups = st.multiselect(
                "Assignment Group",
                sorted(
                    df_backlog["assignment_group"]
                    .dropna()
                    .unique()
                    .tolist()
                ),
            )

        with filter_col2:
            selected_providers = st.multiselect(
                "Provider / Assigned To",
                sorted(
                    [
                        value
                        for value in df_backlog[
                            "assigned_to"
                        ].dropna().unique().tolist()
                        if value
                    ]
                ),
            )

        filtered_backlog = df_backlog.copy()

        if selected_groups:
            filtered_backlog = filtered_backlog[
                filtered_backlog["assignment_group"].isin(
                    selected_groups
                )
            ]

        if selected_providers:
            filtered_backlog = filtered_backlog[
                filtered_backlog["assigned_to"].isin(
                    selected_providers
                )
            ]

        total = len(filtered_backlog)

        access = int(
            (filtered_backlog["level"] == "Access").sum()
        )
        l1 = int((filtered_backlog["level"] == "L1").sum())
        l2 = int((filtered_backlog["level"] == "L2").sum())
        sys_admin = int(
            (filtered_backlog["level"] == "Sys Admin").sum()
        )
        dev_eng = int(
            (filtered_backlog["level"] == "Dev / Eng").sum()
        )

        assigned = int(
            filtered_backlog["assigned_to"]
            .fillna("")
            .str.strip()
            .ne("")
            .sum()
        )

        unassigned = total - assigned

        hybrid_median_age = (
            round(
                filtered_backlog["ticket_age_days"].median(),
                1,
            )
            if total
            else 0
        )

        metric_columns = st.columns(8)

        metric_columns[0].metric("Total", total)
        metric_columns[1].metric("Access", access)
        metric_columns[2].metric("L1", l1)
        metric_columns[3].metric("L2", l2)
        metric_columns[4].metric("Sys Admin", sys_admin)
        metric_columns[5].metric("Dev / Eng", dev_eng)
        metric_columns[6].metric("Unassigned", unassigned)
        metric_columns[7].metric(
            "Hybrid Median Age",
            hybrid_median_age,
        )

        st.divider()

        st.subheader("Assignment Group Scorecard")

        scorecard_rows = []

        for group_name, group_data in filtered_backlog.groupby(
            "assignment_group"
        ):
            group_total = len(group_data)

            group_assigned = int(
                group_data["assigned_to"]
                .fillna("")
                .str.strip()
                .ne("")
                .sum()
            )

            scorecard_rows.append(
                {
                    "Assignment Group": group_name,
                    "Total": group_total,
                    "Access": int(
                        (group_data["level"] == "Access").sum()
                    ),
                    "L1": int(
                        (group_data["level"] == "L1").sum()
                    ),
                    "L2": int(
                        (group_data["level"] == "L2").sum()
                    ),
                    "Sys Admin": int(
                        (
                            group_data["level"] == "Sys Admin"
                        ).sum()
                    ),
                    "Dev / Eng": int(
                        (
                            group_data["level"] == "Dev / Eng"
                        ).sum()
                    ),
                    "Assigned": group_assigned,
                    "Unassigned": group_total - group_assigned,
                    "Hybrid Median Age": round(
                        group_data["ticket_age_days"].median(),
                        1,
                    ),
                }
            )

        scorecard_df = pd.DataFrame(scorecard_rows)

        if not scorecard_df.empty:
            scorecard_df = scorecard_df.sort_values(
                "Total",
                ascending=False,
            )

        st.dataframe(
            scorecard_df,
            use_container_width=True,
            hide_index=True,
        )

        st.divider()

        st.subheader("Top 10 Ticket Investigation")

        investigation_col1, investigation_col2 = st.columns(2)

        with investigation_col1:
            view_option = st.selectbox(
                "View",
                [
                    "Oldest",
                    "Newest",
                    "Last Updated",
                    "Highest Intervention Score",
                ],
            )

        with investigation_col2:
            interval_warning = st.selectbox(
                "Age Warning",
                [
                    "All",
                    "24hr",
                    "48hr",
                    "72hr",
                    "120hr",
                ],
                index=4,
            )

        investigation_data = filtered_backlog.copy()

        if interval_warning != "All":
            minimum_days = interval_to_days(interval_warning)

            investigation_data = investigation_data[
                investigation_data["ticket_age_days"]
                >= minimum_days
            ]

        if view_option == "Oldest":
            investigation_data = investigation_data.sort_values(
                "ticket_age_days",
                ascending=False,
            )

        elif view_option == "Newest":
            investigation_data = investigation_data.sort_values(
                "open_date",
                ascending=False,
            )

        elif view_option == "Last Updated":
            investigation_data = investigation_data.sort_values(
                "updated_date",
                ascending=True,
            )

        else:
            investigation_data = investigation_data.sort_values(
                "intervention_score",
                ascending=False,
            )

        top_ten = investigation_data.head(10).copy()

        display_columns = [
            "number",
            "ticket_type",
            "short_description",
            "assignment_group",
            "assigned_to",
            "priority",
            "level",
            "ticket_age_days",
            "inactivity_days",
            "updated_date",
            "intervention_score",
        ]

        top_ten = top_ten[display_columns].rename(
            columns={
                "number": "Ticket",
                "ticket_type": "Type",
                "short_description": "Short Description",
                "assignment_group": "Assignment Group",
                "assigned_to": "Assigned To",
                "priority": "Priority",
                "level": "Work Type",
                "ticket_age_days": "Hybrid Age",
                "inactivity_days": "Business Days Since Update",
                "updated_date": "Last Updated",
                "intervention_score": "Intervention Score",
            }
        )

        st.dataframe(
            top_ten,
            use_container_width=True,
            hide_index=True,
        )


# =====================================================
# WEEK IN REVIEW TAB
# =====================================================

with tab2:
    st.header("Week in Review")

    if df_review.empty:
        st.warning(
            "No Progress tickets were returned for the review period."
        )
    else:
        review_col1, review_col2 = st.columns(2)

        with review_col1:
            assignment_group = st.selectbox(
                "Assignment Group",
                ["All Assignment Groups"]
                + sorted(
                    df_review["assignment_group"]
                    .dropna()
                    .unique()
                    .tolist()
                ),
            )

        with review_col2:
            period = st.selectbox(
                "Period",
                [
                    "Week",
                    "Month",
                    "Quarter",
                    "Year",
                ],
            )

        selected_period_start = period_start(period)

        review_data = df_review[
            df_review["open_date"] >= selected_period_start
        ].copy()

        if assignment_group != "All Assignment Groups":
            review_data = review_data[
                review_data["assignment_group"]
                == assignment_group
            ]

        assigned_count = int(
            review_data["assigned_to"]
            .fillna("")
            .str.strip()
            .ne("")
            .sum()
        )

        closed_count = int(
            review_data["closed_date"].notna().sum()
        )

        backlog_count = int(
            review_data["closed_date"].isna().sum()
        )

        average_ttr = (
            round(review_data["ttr_days"].dropna().mean(), 1)
            if review_data["ttr_days"].notna().any()
            else 0
        )

        average_hybrid_age = (
            round(review_data["ticket_age_days"].mean(), 1)
            if not review_data.empty
            else 0
        )

        review_metrics = st.columns(5)

        review_metrics[0].metric("Assigned", assigned_count)
        review_metrics[1].metric("Closed", closed_count)
        review_metrics[2].metric("Backlog", backlog_count)
        review_metrics[3].metric(
            "Average TTR",
            average_ttr,
        )
        review_metrics[4].metric(
            "Average Hybrid Age",
            average_hybrid_age,
        )

        st.divider()

        st.subheader("Ticket Set")

        review_display = review_data[
            [
                "number",
                "ticket_type",
                "short_description",
                "assignment_group",
                "assigned_to",
                "priority",
                "state",
                "open_date",
                "closed_date",
                "ticket_age_days",
                "ttr_days",
            ]
        ].copy()

        review_display = review_display.rename(
            columns={
                "number": "Ticket",
                "ticket_type": "Type",
                "short_description": "Short Description",
                "assignment_group": "Assignment Group",
                "assigned_to": "Assigned To",
                "priority": "Priority",
                "state": "State",
                "open_date": "Opened",
                "closed_date": "Closed",
                "ticket_age_days": "Hybrid Age",
                "ttr_days": "TTR",
            }
        )

        st.dataframe(
    review_display,
    use_container_width=True,
    hide_index=True,
)

