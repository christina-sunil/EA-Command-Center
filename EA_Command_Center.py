import math

import numpy as np
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="EA Command Center", page_icon="📊", layout="wide")

INSTANCE_URL = "https://progress1.service-now.com"
USERNAME = st.secrets.get("SERVICENOW_USERNAME", "")
PASSWORD = st.secrets.get("SERVICENOW_PASSWORD", "")

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

AGE_THRESHOLDS = [(0, 1), (3, 2), (7, 4), (14, 6), (30, 8), (60, 9), (90, 10)]
INACTIVITY_THRESHOLDS = [(0, 1), (2, 3), (5, 5), (10, 7), (20, 9), (30, 10)]
REASSIGNMENT_THRESHOLDS = [(0, 1), (1, 3), (2, 5), (4, 7), (6, 9), (8, 10)]

THEME_KEYWORDS = {
    "Access / Permissions": ["access", "permission", "login", "password", "role", "security"],
    "License / Renewal": ["license", "licence", "renewal", "renew", "subscription", "entitlement"],
    "Salesforce / CRM": ["salesforce", "sfdc", "crm", "opportunity", "lead", "contact"],
    "Integration": ["integration", "mulesoft", "api", "interface", "sync", "job", "failure"],
    "ShareFile / CPQ": ["sharefile", "cpq", "quote", "quoting", "order", "invoice"],
    "Data / Reporting": ["report", "reporting", "tableau", "dashboard", "data", "upload", "extract"],
}


def clean_display(value):
    if isinstance(value, dict):
        return value.get("display_value", "") or value.get("value", "") or ""
    return "" if value is None else str(value).strip()


def map_priority(value):
    priority = str(value).lower().strip()
    if priority.startswith("1") or "critical" in priority:
        return "Critical"
    if priority.startswith("2") or "high" in priority:
        return "High"
    if priority.startswith("3") or "moderate" in priority or "medium" in priority:
        return "Medium"
    if priority.startswith("4") or "low" in priority:
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
    if any(name in group_name for name in [
        "ShareFile - CPQ", "Quote to Invoice", "Lead to Opp",
        "Mulesoft Product Support", "EA Shared Services", "CS/TS",
    ]):
        return "L3"
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
        return today.replace(month=((today.month - 1) // 3) * 3 + 1, day=1)
    return today.replace(month=1, day=1)


def previous_period_range(period_name):
    current_start = period_start(period_name)
    if period_name == "Week":
        previous_start = current_start - pd.Timedelta(days=7)
    elif period_name == "Month":
        previous_start = current_start - pd.DateOffset(months=1)
    elif period_name == "Quarter":
        previous_start = current_start - pd.DateOffset(months=3)
    else:
        previous_start = current_start - pd.DateOffset(years=1)
    return previous_start, current_start


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


def priority_score(priority):
    return {"Critical": 10, "High": 8, "Medium": 5, "Low": 2, "Other": 1}.get(priority, 1)


def identify_theme(text):
    text = str(text).lower()
    for theme, words in THEME_KEYWORDS.items():
        if any(word in text for word in words):
            return theme
    return "Other"


def theme_summary(dataframe):
    if dataframe.empty:
        return pd.DataFrame(columns=["Theme", "Tickets", "Share %"])
    themes = dataframe["short_description"].apply(identify_theme)
    summary = themes.value_counts().rename_axis("Theme").reset_index(name="Tickets")
    summary["Share %"] = (summary["Tickets"] / summary["Tickets"].sum() * 100).round(1)
    return summary


def pct_change(current_value, previous_value):
    if previous_value == 0:
        return np.nan
    return round((current_value - previous_value) / previous_value * 100, 1)


@st.cache_data(show_spinner="Loading Progress tickets...")
def load_table(table_name, query, fields, max_rows):
    if not USERNAME or not PASSWORD:
        raise RuntimeError(
            "ServiceNow credentials are missing. Add SERVICENOW_USERNAME and "
            "SERVICENOW_PASSWORD in Streamlit Secrets."
        )
    url = f"{INSTANCE_URL}/api/now/table/{table_name}"
    page_size = 2000
    all_rows = []
    for offset in range(0, max_rows, page_size):
        params = {
            "sysparm_query": query,
            "sysparm_display_value": "true",
            "sysparm_exclude_reference_link": "true",
            "sysparm_limit": str(min(page_size, max_rows - offset)),
            "sysparm_offset": str(offset),
            "sysparm_fields": fields,
        }
        response = requests.get(
            url, params=params, auth=(USERNAME, PASSWORD),
            headers={"Accept": "application/json"}, timeout=60,
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"ServiceNow API error for {table_name}: "
                f"{response.status_code} - {response.text[:1000]}"
            )
        result = response.json().get("result", [])
        if not result:
            break
        all_rows.extend(result)
        if len(result) < page_size:
            break
    return pd.DataFrame(all_rows)


def prepare_dataframe(dataframe, ticket_type):
    required = [
        "sys_id", "number", "short_description", "assignment_group", "assigned_to",
        "priority", "state", "active", "sys_created_on", "sys_updated_on",
        "closed_at", "reassignment_count",
    ]
    if dataframe.empty:
        return pd.DataFrame(columns=required + [
            "ticket_type", "open_date", "updated_date", "closed_date", "level", "ticket_url"
        ])
    work = dataframe.copy()
    for column in required:
        if column not in work.columns:
            work[column] = ""
    work["ticket_type"] = ticket_type
    for column in ["assignment_group", "assigned_to", "state", "short_description"]:
        work[column] = work[column].apply(clean_display)
    work["priority"] = work["priority"].apply(map_priority)
    work["open_date"] = pd.to_datetime(work["sys_created_on"], errors="coerce")
    work["updated_date"] = pd.to_datetime(work["sys_updated_on"], errors="coerce")
    work["closed_date"] = pd.to_datetime(work["closed_at"], errors="coerce")
    work["reassignment_count"] = pd.to_numeric(work["reassignment_count"], errors="coerce").fillna(0)
    work["level"] = work["assignment_group"].apply(level_from_group)
    work["ticket_url"] = work.apply(
        lambda row: f"{INSTANCE_URL}/task.do?sys_id={row['sys_id']}&number={row['number']}", axis=1
    )
    return work


@st.cache_data(show_spinner="Preparing EA Command Center data...")
def get_command_center_data(max_rows):
    fields = (
        "sys_id,number,short_description,assignment_group,assigned_to,priority,state,active,"
        "sys_created_on,sys_updated_on,closed_at,reassignment_count"
    )
    open_query = f"active=true^assignment_group.nameIN{GROUP_QUERY}"
    current_year = pd.Timestamp.now().year
    year_start = f"{current_year}-01-01 00:00:00"
    created_query = f"assignment_group.nameIN{GROUP_QUERY}^sys_created_on>={year_start}"
    closed_query = f"assignment_group.nameIN{GROUP_QUERY}^closed_at>={year_start}"

    backlog = pd.concat([
        prepare_dataframe(load_table("sc_req_item", open_query, fields, max_rows), "RITM"),
        prepare_dataframe(load_table("incident", open_query, fields, max_rows), "INC"),
    ], ignore_index=True)
    created = pd.concat([
        prepare_dataframe(load_table("sc_req_item", created_query, fields, max_rows), "RITM"),
        prepare_dataframe(load_table("incident", created_query, fields, max_rows), "INC"),
    ], ignore_index=True).drop_duplicates(subset=["ticket_type", "sys_id"])
    closed = pd.concat([
        prepare_dataframe(load_table("sc_req_item", closed_query, fields, max_rows), "RITM"),
        prepare_dataframe(load_table("incident", closed_query, fields, max_rows), "INC"),
    ], ignore_index=True).drop_duplicates(subset=["ticket_type", "sys_id"])

    now = pd.Timestamp.now()
    if not backlog.empty:
        backlog["ticket_age_days"] = backlog["open_date"].apply(lambda x: business_days_between(x, now))
        backlog["inactivity_days"] = backlog["updated_date"].apply(lambda x: business_days_between(x, now))
        backlog["intervention_score"] = (
            backlog["ticket_age_days"].apply(lambda x: threshold_score(x, AGE_THRESHOLDS)) * 0.35
            + backlog["inactivity_days"].apply(lambda x: threshold_score(x, INACTIVITY_THRESHOLDS)) * 0.30
            + backlog["priority"].apply(priority_score) * 0.20
            + backlog["reassignment_count"].apply(lambda x: threshold_score(x, REASSIGNMENT_THRESHOLDS)) * 0.15
        ).round(2)
    for data in [created, closed]:
        if not data.empty:
            data["ticket_age_days"] = data.apply(
                lambda row: business_days_between(
                    row["open_date"], row["closed_date"] if pd.notna(row["closed_date"]) else now
                ), axis=1,
            )
            data["ttr_days"] = data.apply(
                lambda row: business_days_between(row["open_date"], row["closed_date"])
                if pd.notna(row["closed_date"]) else np.nan, axis=1,
            )
    return backlog, created, closed


def show_link_table(dataframe):
    if dataframe.empty:
        st.info("No tickets match the selected criteria.")
        return
    st.dataframe(
        dataframe,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Ticket": st.column_config.LinkColumn(
                "Ticket",
                help="Select the ticket number to open it in ServiceNow",
                display_text=r"number=([^&]+)$",
            )
        },
    )


def assignment_group_options(dataframe):
    if dataframe.empty or "assignment_group" not in dataframe.columns:
        return []
    values = dataframe["assignment_group"].dropna().astype(str)
    return sorted(values[values.str.strip().ne("")].unique().tolist())


st.title("Enterprise Applications Command Center")
st.caption("Progress ticket operational scorecard. Hybrid Age and TTR exclude Saturday and Sunday.")
control_col1, control_col2 = st.columns([3, 1])
with control_col1:
    max_to_load = st.selectbox("Maximum records to load per table", [2000, 5000, 10000, 20000], index=2)
with control_col2:
    st.write("")
    st.write("")
    if st.button("Refresh data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

try:
    df_backlog, df_created, df_closed = get_command_center_data(max_to_load)
except Exception as error:
    st.error(str(error))
    st.info("Add SERVICENOW_USERNAME and SERVICENOW_PASSWORD in Streamlit Secrets.")
    st.stop()

tab1, tab2 = st.tabs(["Backlog", "Week in Review"])

with tab1:
    st.header("Backlog")
    if df_backlog.empty:
        st.warning("No active Progress tickets were returned.")
    else:
        filter_col1, filter_col2 = st.columns(2)
        with filter_col1:
            selected_groups = st.multiselect("Assignment Group", assignment_group_options(df_backlog))
        with filter_col2:
            selected_providers = st.multiselect(
                "Provider / Assigned To",
                sorted([v for v in df_backlog["assigned_to"].dropna().astype(str).unique().tolist() if v.strip()]),
            )
        filtered = df_backlog.copy()
        if selected_groups:
            filtered = filtered[filtered["assignment_group"].isin(selected_groups)]
        if selected_providers:
            filtered = filtered[filtered["assigned_to"].isin(selected_providers)]

        total = len(filtered)
        assigned = int(filtered["assigned_to"].fillna("").astype(str).str.strip().ne("").sum())
        levels = {name: int((filtered["level"] == name).sum()) for name in ["Access", "L1", "L2", "L3", "Sys Admin"]}
        metric_values = [
            total, levels["Access"], levels["L1"], levels["L2"], levels["L3"], levels["Sys Admin"],
            assigned, total - assigned, round(filtered["ticket_age_days"].mean(), 1) if total else 0,
        ]
        for column, label, value in zip(
            st.columns(9),
            ["Total", "Access", "L1", "L2", "L3", "Sys Admin", "Assigned", "Unassigned", "Avg Hybrid Age"],
            metric_values,
        ):
            column.metric(label, value)
        median_age = round(filtered["ticket_age_days"].median(), 1) if total else 0
        st.caption(f"Median Hybrid Age: {median_age} business days")

        st.divider()
        st.subheader("Assignment Group Scorecard")
        closed_period = st.selectbox("Closed Ticket Period", ["Week", "Month", "Quarter", "Year"])
        closed_for_period = df_closed[
            df_closed["closed_date"].notna() & (df_closed["closed_date"] >= period_start(closed_period))
        ].copy()
        scorecard_rows = []
        for group_name, group_data in filtered.groupby("assignment_group"):
            group_assigned = int(group_data["assigned_to"].fillna("").astype(str).str.strip().ne("").sum())
            scorecard_rows.append({
                "Assignment Group": group_name,
                "Backlog": len(group_data),
                "Access": int((group_data["level"] == "Access").sum()),
                "L1": int((group_data["level"] == "L1").sum()),
                "L2": int((group_data["level"] == "L2").sum()),
                "L3": int((group_data["level"] == "L3").sum()),
                "Sys Admin": int((group_data["level"] == "Sys Admin").sum()),
                "Closed": int((closed_for_period["assignment_group"] == group_name).sum()),
                "Assigned": group_assigned,
                "Unassigned": len(group_data) - group_assigned,
                "Avg Hybrid Age": round(group_data["ticket_age_days"].mean(), 1),
            })
        scorecard = pd.DataFrame(scorecard_rows)
        if scorecard.empty:
            st.info("No assignment group data is available.")
        else:
            st.dataframe(scorecard.sort_values("Backlog", ascending=False), use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("Top 10 Ticket Investigation")
        investigation_col1, investigation_col2 = st.columns(2)
        with investigation_col1:
            view_option = st.selectbox(
                "View", ["Oldest", "Newest", "Last Updated", "Highest Intervention Score"]
            )
        with investigation_col2:
            age_filter = st.selectbox(
                "Age Filter", ["All", ">=5 Business Days", ">=10 Business Days", ">=20 Business Days"]
            )
        investigation = filtered.copy()
        minimum_age = {"All": 0, ">=5 Business Days": 5, ">=10 Business Days": 10, ">=20 Business Days": 20}[age_filter]
        if age_filter != "All":
            investigation = investigation[investigation["ticket_age_days"] >= minimum_age]
        sort_column, ascending = {
            "Oldest": ("ticket_age_days", False),
            "Newest": ("open_date", False),
            "Last Updated": ("updated_date", True),
            "Highest Intervention Score": ("intervention_score", False),
        }[view_option]
        investigation = investigation.sort_values(sort_column, ascending=ascending, na_position="last").head(10)
        display = investigation[[
            "ticket_url", "ticket_type", "short_description", "assignment_group", "assigned_to",
            "priority", "level", "ticket_age_days", "inactivity_days", "updated_date", "intervention_score",
        ]].copy()
        display.columns = [
            "Ticket", "Type", "Short Description", "Assignment Group", "Assigned To", "Priority",
            "Work Type", "Hybrid Age", "Business Days Since Update", "Last Updated", "Intervention Score",
        ]
        show_link_table(display)

with tab2:
    st.header("Week in Review")
    if df_created.empty and df_closed.empty:
        st.warning("No Progress tickets were returned for the review period.")
    else:
        review_col1, review_col2 = st.columns(2)
        all_groups = sorted(set(assignment_group_options(df_created) + assignment_group_options(df_closed)))
        with review_col1:
            selected_group = st.selectbox("Assignment Group", ["All Assignment Groups"] + all_groups)
        with review_col2:
            selected_period = st.selectbox("Period", ["Week", "Month", "Quarter", "Year"])

        current_start = period_start(selected_period)
        current_end = pd.Timestamp.now()
        new_data = df_created[
            (df_created["open_date"] >= current_start) & (df_created["open_date"] <= current_end)
        ].copy()
        closed_data = df_closed[
            (df_closed["closed_date"] >= current_start) & (df_closed["closed_date"] <= current_end)
        ].copy()
        current_backlog = df_backlog.copy()
        if selected_group != "All Assignment Groups":
            new_data = new_data[new_data["assignment_group"] == selected_group]
            closed_data = closed_data[closed_data["assignment_group"] == selected_group]
            current_backlog = current_backlog[current_backlog["assignment_group"] == selected_group]

        new_count = len(new_data)
        assigned_count = int(new_data["assigned_to"].fillna("").astype(str).str.strip().ne("").sum())
        closed_count = len(closed_data)
        backlog_count = len(current_backlog)
        average_ttr = round(closed_data["ttr_days"].dropna().mean(), 1) if closed_data["ttr_days"].notna().any() else 0
        average_age = round(new_data["ticket_age_days"].mean(), 1) if not new_data.empty else 0
        for column, label, value in zip(
            st.columns(6),
            ["New", "Assigned", "Closed", "Open / Backlog", "Average TTR", "Average Hybrid Age"],
            [new_count, assigned_count, closed_count, backlog_count, average_ttr, average_age],
        ):
            column.metric(label, value)
        st.caption(
            "Assigned counts selected-period tickets that currently have an Assigned To value. "
            "Open / Backlog is the current active backlog for the selected assignment group."
        )

        st.divider()
        st.subheader("Theme & Trend Analysis")
        themes = theme_summary(new_data)
        if themes.empty:
            st.info("No new tickets are available for theme analysis.")
        else:
            chart_col, table_col = st.columns([2, 1])
            with chart_col:
                st.bar_chart(themes.set_index("Theme")[["Tickets"]])
            with table_col:
                st.dataframe(themes, use_container_width=True, hide_index=True)
            top_theme = themes.iloc[0]
            st.info(
                f"Top new-ticket theme: {top_theme['Theme']} "
                f"({int(top_theme['Tickets'])} tickets, {top_theme['Share %']}%)."
            )

        previous_start, previous_end = previous_period_range(selected_period)
        previous_new = df_created[
            (df_created["open_date"] >= previous_start) & (df_created["open_date"] < previous_end)
        ].copy()
        previous_closed = df_closed[
            (df_closed["closed_date"] >= previous_start) & (df_closed["closed_date"] < previous_end)
        ].copy()
        if selected_group != "All Assignment Groups":
            previous_new = previous_new[previous_new["assignment_group"] == selected_group]
            previous_closed = previous_closed[previous_closed["assignment_group"] == selected_group]
        trend = pd.DataFrame([
            {
                "Metric": "New", "Current Period": new_count, "Previous Period": len(previous_new),
                "Change": new_count - len(previous_new), "Change %": pct_change(new_count, len(previous_new)),
            },
            {
                "Metric": "Closed", "Current Period": closed_count, "Previous Period": len(previous_closed),
                "Change": closed_count - len(previous_closed), "Change %": pct_change(closed_count, len(previous_closed)),
            },
        ])
        st.write("Period-over-Period Trend")
        st.dataframe(trend, use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("Improvement Opportunities")
        inactivity = current_backlog["updated_date"].apply(
            lambda value: business_days_between(value, pd.Timestamp.now())
        )
        opportunities = pd.DataFrame([
            {
                "Opportunity": "Review tickets at or above 120 business hours",
                "Ticket Count": int((current_backlog["ticket_age_days"] >= 5).sum()),
                "Suggested Focus": "Confirm owner, blocker, and next action.",
            },
            {
                "Opportunity": "Assign unassigned tickets",
                "Ticket Count": int(current_backlog["assigned_to"].fillna("").astype(str).str.strip().eq("").sum()),
                "Suggested Focus": "Confirm assignment group and provider.",
            },
            {
                "Opportunity": "Review open high-priority tickets",
                "Ticket Count": int(current_backlog["priority"].isin(["Critical", "High"]).sum()),
                "Suggested Focus": "Confirm priority, owner, and resolution plan.",
            },
            {
                "Opportunity": "Review tickets not updated for at least 5 business days",
                "Ticket Count": int((inactivity >= 5).sum()),
                "Suggested Focus": "Request status and a documented next step.",
            },
        ])
        st.dataframe(opportunities, use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("Ticket Set")
        ticket_set = pd.concat([
            new_data.assign(review_status="New / Created"),
            closed_data.assign(review_status="Closed"),
        ], ignore_index=True).drop_duplicates(subset=["ticket_type", "sys_id"])
        if ticket_set.empty:
            st.info("No tickets match the selected period and group.")
        else:
            display = ticket_set[[
                "ticket_url", "ticket_type", "short_description", "assignment_group", "assigned_to",
                "priority", "level", "state", "open_date", "closed_date", "ticket_age_days",
                "ttr_days", "review_status",
            ]].copy()
            display.columns = [
                "Ticket", "Type", "Short Description", "Assignment Group", "Assigned To", "Priority",
                "Work Type", "State", "Opened", "Closed", "Hybrid Age", "TTR", "Review Status",
            ]
            show_link_table(display)

st.divider()
st.caption(
    "EA Command Center | Progress operational metrics | Hybrid Age and TTR use business days only "
    "(Monday-Friday; holidays are not excluded)."
)
