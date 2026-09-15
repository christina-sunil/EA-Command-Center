import math
import re

import numpy as np
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="EA Command Center", page_icon="📊", layout="wide")

INSTANCE_URL = "https://progress1.service-now.com"
USERNAME = st.secrets.get("SERVICENOW_USERNAME", "github_servicenow_api")
PASSWORD = st.secrets.get("SERVICENOW_PASSWORD", "wL<c&sLHGso(mH3mIRs=byF5C%97o>P3z[K+QZSD")

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
    "Access / Permissions / User Setup": [
        "access", "permission", "profile", "role", "login", "activation",
        "progress id", "case team", "termination",
    ],
    "Quote / Opportunity / Renewal": [
        "quote", "quoting", "opportunity", "oppty", "renewal", "cpq", "ocpq",
    ],
    "Account / Contact / Asset / Entitlement": [
        "account merge", "duplicate account", "contact", "asset", "entitle",
        "re-entitle", "serial number",
    ],
    "Lead / Campaign / Enrichment": [
        "lead", "campaign", "leadspace", "enrichment", "suspect",
    ],
    "Integration / Automation / API": [
        "integration", "api", "flow", "sync", "automation", "mulesoft", "qualtrics",
    ],
    "Reporting / Data / Upload": [
        "report", "dashboard", "data", "upload", "extract", "spreadsheet",
    ],
    "SupportLink / Customer Portal": [
        "supportlink", "support link", "portal", "support case",
    ],
}


def clean_display(value):
    if isinstance(value, dict):
        return value.get("display_value", "") or value.get("value", "") or ""
    return "" if value is None else str(value).strip()


def map_priority(value):
    value = str(value).lower().strip()
    if value.startswith("1") or "critical" in value:
        return "Critical"
    if value.startswith("2") or "high" in value:
        return "High"
    if value.startswith("3") or "moderate" in value or "medium" in value:
        return "Medium"
    if value.startswith("4") or "low" in value:
        return "Low"
    return "Other"


def map_urgency(value):
    value = str(value).lower().strip()
    if value.startswith("1") or "high" in value:
        return "High"
    if value.startswith("2") or "medium" in value:
        return "Medium"
    if value.startswith("3") or "low" in value:
        return "Low"
    return "Other"


def support_level(group_name):
    group_name = str(group_name)
    if group_name in {"IT Supp: EAST - Delivery", "IT Supp: System Access Requests"}:
        return "L1"
    if group_name == "IT Supp: EAST - Leads":
        return "L2"
    return "L3"


def work_type(group_name):
    group_name = str(group_name)
    if "System Access Requests" in group_name:
        return "Access"
    if "EAST - Delivery" in group_name:
        return "L1"
    if "EAST - Leads" in group_name:
        return "L2"
    if "System Admins" in group_name:
        return "Sys Admin"
    return "L3"


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


def add_theme(dataframe):
    result = dataframe.copy()
    text = result["short_description"].fillna("") + " " + result["description"].fillna("")
    result["theme"] = text.apply(identify_theme)
    return result


def theme_summary(dataframe):
    if dataframe.empty:
        return pd.DataFrame(columns=["Theme", "Tickets", "Share %"])
    themed = add_theme(dataframe)
    summary = themed["theme"].value_counts().rename_axis("Theme").reset_index(name="Tickets")
    summary["Share %"] = (summary["Tickets"] / summary["Tickets"].sum() * 100).round(1)
    return summary


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
            url,
            params=params,
            auth=(USERNAME, PASSWORD),
            headers={"Accept": "application/json"},
            timeout=60,
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"ServiceNow API error for {table_name}: "
                f"{response.status_code} - {response.text[:1000]}"
            )
        rows = response.json().get("result", [])
        if not rows:
            break
        all_rows.extend(rows)
        if len(rows) < page_size:
            break

    return pd.DataFrame(all_rows)


def prepare_dataframe(dataframe, ticket_type):
    required = [
        "sys_id", "number", "short_description", "description", "work_notes", "cmdb_ci",
        "assignment_group", "assigned_to", "priority", "urgency", "state", "active",
        "sys_created_on", "sys_updated_on", "closed_at", "reassignment_count",
    ]

    if dataframe.empty:
        return pd.DataFrame(columns=required + [
            "ticket_type", "configuration_item", "open_date", "updated_date", "closed_date",
            "support_level", "work_type", "ticket_url",
        ])

    work = dataframe.copy()
    for column in required:
        if column not in work.columns:
            work[column] = ""

    work["ticket_type"] = ticket_type
    for column in [
        "short_description", "description", "work_notes", "cmdb_ci",
        "assignment_group", "assigned_to", "state",
    ]:
        work[column] = work[column].apply(clean_display)

    work["configuration_item"] = work["cmdb_ci"]
    work["priority"] = work["priority"].apply(map_priority)
    work["urgency"] = work["urgency"].apply(map_urgency)
    work["open_date"] = pd.to_datetime(work["sys_created_on"], errors="coerce")
    work["updated_date"] = pd.to_datetime(work["sys_updated_on"], errors="coerce")
    work["closed_date"] = pd.to_datetime(work["closed_at"], errors="coerce")
    work["reassignment_count"] = pd.to_numeric(
        work["reassignment_count"], errors="coerce"
    ).fillna(0)
    work["support_level"] = work["assignment_group"].apply(support_level)
    work["work_type"] = work["assignment_group"].apply(work_type)
    work["ticket_url"] = work.apply(
        lambda row: f"{INSTANCE_URL}/task.do?sys_id={row['sys_id']}&number={row['number']}",
        axis=1,
    )
    return work


@st.cache_data(show_spinner="Preparing EA Command Center data...")
def get_command_center_data(max_rows):
    fields = (
        "sys_id,number,short_description,description,work_notes,cmdb_ci,assignment_group,"
        "assigned_to,priority,urgency,state,active,sys_created_on,sys_updated_on,"
        "closed_at,reassignment_count"
    )
    current_year = pd.Timestamp.now().year
    open_query = f"active=true^assignment_group.nameIN{GROUP_QUERY}"
    created_query = (
        f"assignment_group.nameIN{GROUP_QUERY}^sys_created_on>={current_year}-01-01 00:00:00"
    )
    closed_query = (
        f"assignment_group.nameIN{GROUP_QUERY}^closed_at>={current_year}-01-01 00:00:00"
    )

    def combine(query):
        return pd.concat(
            [
                prepare_dataframe(load_table("sc_req_item", query, fields, max_rows), "RITM"),
                prepare_dataframe(load_table("incident", query, fields, max_rows), "INC"),
            ],
            ignore_index=True,
        ).drop_duplicates(subset=["ticket_type", "sys_id"], keep="first")

    backlog = combine(open_query)
    created = combine(created_query)
    closed = combine(closed_query)
    now = pd.Timestamp.now()

    if not backlog.empty:
        backlog["ticket_age_days"] = backlog["open_date"].apply(
            lambda value: business_days_between(value, now)
        )
        backlog["inactivity_days"] = backlog["updated_date"].apply(
            lambda value: business_days_between(value, now)
        )
        backlog["intervention_score"] = (
            backlog["ticket_age_days"].apply(
                lambda value: threshold_score(value, AGE_THRESHOLDS)
            ) * 0.35
            + backlog["inactivity_days"].apply(
                lambda value: threshold_score(value, INACTIVITY_THRESHOLDS)
            ) * 0.30
            + backlog["priority"].apply(priority_score) * 0.20
            + backlog["reassignment_count"].apply(
                lambda value: threshold_score(value, REASSIGNMENT_THRESHOLDS)
            ) * 0.15
        ).round(2)

    for data in [created, closed]:
        if not data.empty:
            data["ticket_age_days"] = data.apply(
                lambda row: business_days_between(
                    row["open_date"],
                    row["closed_date"] if pd.notna(row["closed_date"]) else now,
                ),
                axis=1,
            )
            data["ttr_days"] = data.apply(
                lambda row: business_days_between(row["open_date"], row["closed_date"])
                if pd.notna(row["closed_date"])
                else np.nan,
                axis=1,
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


def group_options(dataframe):
    if dataframe.empty:
        return []
    values = dataframe["assignment_group"].dropna().astype(str)
    return sorted(values[values.str.strip().ne("")].unique().tolist())


st.title("Enterprise Applications Command Center")
st.caption(
    "Live ServiceNow operational view. Hybrid Age and TTR exclude Saturday and Sunday."
)

control_col1, control_col2 = st.columns([3, 1])
with control_col1:
    max_rows = st.selectbox(
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
    df_backlog, df_created, df_closed = get_command_center_data(max_rows)
except Exception as error:
    st.error(str(error))
    st.stop()

tab1, tab2, tab3 = st.tabs(["Backlog", "Week in Review", "Executive Insights"])

with tab1:
    st.header("Backlog")
    if df_backlog.empty:
        st.warning("No active Progress tickets were returned.")
    else:
        filter_col1, filter_col2 = st.columns(2)
        with filter_col1:
            selected_groups = st.multiselect("Assignment Group", group_options(df_backlog))
        with filter_col2:
            selected_owners = st.multiselect(
                "Provider / Assigned To",
                sorted(value for value in df_backlog["assigned_to"].dropna().unique() if value),
            )

        backlog_view = df_backlog.copy()
        if selected_groups:
            backlog_view = backlog_view[backlog_view["assignment_group"].isin(selected_groups)]
        if selected_owners:
            backlog_view = backlog_view[backlog_view["assigned_to"].isin(selected_owners)]

        assigned = int(backlog_view["assigned_to"].fillna("").str.strip().ne("").sum())
        values = [
            len(backlog_view),
            int((backlog_view["work_type"] == "Access").sum()),
            int((backlog_view["work_type"] == "L1").sum()),
            int((backlog_view["work_type"] == "L2").sum()),
            int((backlog_view["work_type"] == "L3").sum()),
            int((backlog_view["work_type"] == "Sys Admin").sum()),
            assigned,
            len(backlog_view) - assigned,
            round(backlog_view["ticket_age_days"].mean(), 1),
        ]
        labels = [
            "Total", "Access", "L1", "L2", "L3", "Sys Admin",
            "Assigned", "Unassigned", "Avg Hybrid Age",
        ]
        for column, label, value in zip(st.columns(9), labels, values):
            column.metric(label, value)

        st.divider()
        st.subheader("Assignment Group Open Backlog Scorecard")
        rows = []
        for group_name, group_data in backlog_view.groupby("assignment_group"):
            rows.append(
                {
                    "Assignment Group": group_name,
                    "Open": len(group_data),
                    "Access": int((group_data["work_type"] == "Access").sum()),
                    "L1": int((group_data["work_type"] == "L1").sum()),
                    "L2": int((group_data["work_type"] == "L2").sum()),
                    "L3": int((group_data["work_type"] == "L3").sum()),
                    "Sys Admin": int((group_data["work_type"] == "Sys Admin").sum()),
                    "Unassigned": int(
                        group_data["assigned_to"].fillna("").str.strip().eq("").sum()
                    ),
                    "Avg Hybrid Age": round(group_data["ticket_age_days"].mean(), 1),
                }
            )
        scorecard = pd.DataFrame(rows)
        if not scorecard.empty:
            st.dataframe(
                scorecard.sort_values("Open", ascending=False),
                use_container_width=True,
                hide_index=True,
            )

        st.divider()
        st.subheader("Top 10 Ticket Investigation")
        investigation_col1, investigation_col2 = st.columns(2)
        with investigation_col1:
            selected_view = st.selectbox(
                "View",
                ["Oldest", "Newest", "Last Updated", "Highest Intervention Score"],
            )
        with investigation_col2:
            minimum_age = st.selectbox(
                "Age Filter",
                [0, 5, 10, 20],
                format_func=lambda value: "All" if value == 0 else f">={value} Business Days",
            )

        investigation = backlog_view.copy()
        if minimum_age:
            investigation = investigation[investigation["ticket_age_days"] >= minimum_age]
        sort_column, ascending = {
            "Oldest": ("ticket_age_days", False),
            "Newest": ("open_date", False),
            "Last Updated": ("updated_date", True),
            "Highest Intervention Score": ("intervention_score", False),
        }[selected_view]
        investigation = investigation.sort_values(
            sort_column, ascending=ascending, na_position="last"
        ).head(10)
        investigation_display = investigation[
            [
                "ticket_url", "ticket_type", "short_description", "assignment_group",
                "assigned_to", "priority", "urgency", "work_type", "ticket_age_days",
                "inactivity_days", "updated_date", "intervention_score",
            ]
        ].copy()
        investigation_display.columns = [
            "Ticket", "Type", "Short Description", "Assignment Group", "Assigned To",
            "Priority", "Urgency", "Work Type", "Hybrid Age", "Days Since Update",
            "Last Updated", "Intervention Score",
        ]
        show_link_table(investigation_display)

with tab2:
    st.header("Week in Review")
    all_groups = sorted(
        set(group_options(df_created) + group_options(df_closed) + group_options(df_backlog))
    )
    review_col1, review_col2 = st.columns(2)
    with review_col1:
        review_group = st.selectbox(
            "Assignment Group", ["All Assignment Groups"] + all_groups, key="review_group"
        )
    with review_col2:
        review_period = st.selectbox(
            "Period", ["Week", "Month", "Quarter", "Year"], key="review_period"
        )

    review_start = period_start(review_period)
    now = pd.Timestamp.now()
    new_data = df_created[
        (df_created["open_date"] >= review_start) & (df_created["open_date"] <= now)
    ].copy()
    closed_data = df_closed[
        (df_closed["closed_date"] >= review_start) & (df_closed["closed_date"] <= now)
    ].copy()
    current_backlog = df_backlog.copy()
    if review_group != "All Assignment Groups":
        new_data = new_data[new_data["assignment_group"] == review_group]
        closed_data = closed_data[closed_data["assignment_group"] == review_group]
        current_backlog = current_backlog[current_backlog["assignment_group"] == review_group]

    assigned = int(new_data["assigned_to"].fillna("").str.strip().ne("").sum())
    review_values = [
        len(new_data),
        assigned,
        len(closed_data),
        len(current_backlog),
        round(closed_data["ttr_days"].mean(), 1) if not closed_data.empty else 0,
        round(new_data["ticket_age_days"].mean(), 1) if not new_data.empty else 0,
    ]
    for column, label, value in zip(
        st.columns(6),
        ["New", "Assigned", "Closed", "Open / Backlog", "Average TTR", "Average Hybrid Age"],
        review_values,
    ):
        column.metric(label, value)

    st.divider()
    st.subheader("Priority, Urgency, and Age Analysis")
    priority_summary = (
        current_backlog.groupby(["priority", "urgency"])
        .agg(
            Open_Tickets=("number", "count"),
            Avg_Hybrid_Age=("ticket_age_days", "mean"),
            Avg_Days_Since_Update=("inactivity_days", "mean"),
        )
        .reset_index()
    )
    priority_summary.columns = [
        "Priority", "Urgency", "Open Tickets", "Avg Hybrid Age", "Avg Days Since Update"
    ]
    if not priority_summary.empty:
        priority_summary[["Avg Hybrid Age", "Avg Days Since Update"]] = priority_summary[
            ["Avg Hybrid Age", "Avg Days Since Update"]
        ].round(1)
        st.dataframe(priority_summary, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Theme Analysis")
    weekly_themes = theme_summary(new_data)
    if weekly_themes.empty:
        st.info("No new tickets are available for theme analysis.")
    else:
        st.bar_chart(weekly_themes.set_index("Theme")[["Tickets"]])
        st.dataframe(weekly_themes, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Improvement Opportunities")
    current_inactivity = current_backlog["updated_date"].apply(
        lambda value: business_days_between(value, pd.Timestamp.now())
    )
    opportunities = pd.DataFrame(
        [
            {
                "Opportunity": "Review tickets at or above 120 business hours",
                "Ticket Count": int((current_backlog["ticket_age_days"] >= 5).sum()),
            },
            {
                "Opportunity": "Assign unassigned tickets",
                "Ticket Count": int(
                    current_backlog["assigned_to"].fillna("").str.strip().eq("").sum()
                ),
            },
            {
                "Opportunity": "Review open high-priority tickets",
                "Ticket Count": int(
                    current_backlog["priority"].isin(["Critical", "High"]).sum()
                ),
            },
            {
                "Opportunity": "Review tickets not updated for at least 5 business days",
                "Ticket Count": int((current_inactivity >= 5).sum()),
            },
        ]
    )
    st.dataframe(opportunities, use_container_width=True, hide_index=True)

with tab3:
    st.header("Executive Insights")
    st.caption(
        "Current-open view of volume drivers, repeated demand, open critical tickets, "
        "potential L2-to-L3 escalation indicators, Problem candidates, MMTA and MMTR."
    )

    # CRITICAL FIX: Executive Insights uses current open backlog only.
    executive_source = df_backlog.copy()

    executive_filter1, executive_filter2 = st.columns(2)
    with executive_filter1:
        executive_level = st.selectbox(
            "Support Level", ["All Levels", "L1", "L2", "L3"], key="executive_level"
        )
    with executive_filter2:
        executive_group = st.selectbox(
            "Assignment Group",
            ["All Assignment Groups"] + group_options(executive_source),
            key="executive_group",
        )

    executive_view = executive_source.copy()
    if executive_level != "All Levels":
        executive_view = executive_view[executive_view["support_level"] == executive_level]
    if executive_group != "All Assignment Groups":
        executive_view = executive_view[executive_view["assignment_group"] == executive_group]

    executive_view = add_theme(executive_view)

    st.divider()
    st.subheader("Volume Drivers - Current Open Backlog")
    volume_drivers = (
        executive_view.groupby(["support_level", "theme"])
        .size()
        .reset_index(name="Open Tickets")
        .rename(columns={"support_level": "Support Level", "theme": "Theme"})
        .sort_values("Open Tickets", ascending=False)
    )
    configuration_drivers = (
        executive_view[executive_view["configuration_item"].ne("")]
        ["configuration_item"]
        .value_counts()
        .head(15)
        .rename_axis("Configuration Item")
        .reset_index(name="Open Tickets")
    )
    volume_col1, volume_col2 = st.columns(2)
    with volume_col1:
        st.dataframe(volume_drivers, use_container_width=True, hide_index=True)
    with volume_col2:
        if configuration_drivers.empty:
            st.info("No Configuration Item values were returned by the live ServiceNow feed.")
        else:
            st.dataframe(configuration_drivers, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Repeated Open Ticket Patterns")
    repeated_patterns = (
        executive_view[executive_view["theme"] != "Other"]
        .groupby(["theme", "support_level"])
        .agg(
            Open_Tickets=("number", "count"),
            Critical_High=("priority", lambda values: int(values.isin(["Critical", "High"]).sum())),
            Avg_Hybrid_Age=("ticket_age_days", "mean"),
        )
        .reset_index()
        .rename(
            columns={
                "theme": "Theme",
                "support_level": "Support Level",
                "Open_Tickets": "Open Tickets",
                "Critical_High": "Critical / High",
                "Avg_Hybrid_Age": "Avg Hybrid Age",
            }
        )
        .sort_values("Open Tickets", ascending=False)
    )
    if not repeated_patterns.empty:
        repeated_patterns["Avg Hybrid Age"] = repeated_patterns["Avg Hybrid Age"].round(1)
    st.dataframe(repeated_patterns, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Open Critical Tickets")
    critical = executive_view[executive_view["priority"] == "Critical"]
    critical_display = critical[
        [
            "ticket_url", "short_description", "state", "assignment_group", "assigned_to",
            "support_level", "open_date", "updated_date",
        ]
    ].copy()
    critical_display.columns = [
        "Ticket", "Short Description", "State", "Assignment Group", "Assigned To",
        "Support Level", "Opened", "Last Updated",
    ]
    show_link_table(critical_display)

    st.divider()
    st.subheader("Potential L2-to-L3 Escalations - Current Open Backlog")
    escalation_text = (
        executive_view["short_description"].fillna("")
        + " "
        + executive_view["description"].fillna("")
        + " "
        + executive_view["work_notes"].fillna("")
    ).str.lower()
    escalation_pattern = re.compile(
        r"moving|moved|routing|routed|escalat|further analysis|"
        r"further investigation|created jira story",
        re.IGNORECASE,
    )
    escalation_candidates = executive_view[
        (executive_view["support_level"] == "L3")
        & escalation_text.apply(lambda text: bool(escalation_pattern.search(text)))
    ].copy()
    candidate_text = escalation_text.loc[escalation_candidates.index]
    escalation_candidates["Escalation Reason"] = np.select(
        [
            candidate_text.str.contains("jira", na=False),
            candidate_text.str.contains("integration|api|mulesoft|sync", regex=True, na=False),
            candidate_text.str.contains("quote|cpq|ocpq|opportunity", regex=True, na=False),
            candidate_text.str.contains("leadspace|enrichment|lead to opp", regex=True, na=False),
        ],
        [
            "Development or Jira work",
            "Integration expertise",
            "Quote or opportunity expertise",
            "Lead or enrichment expertise",
        ],
        default="Specialized analysis or ownership",
    )
    escalation_display = escalation_candidates[
        ["ticket_url", "short_description", "assignment_group", "priority", "state", "Escalation Reason"]
    ].copy()
    escalation_display.columns = [
        "Ticket", "Short Description", "Current L3 Group", "Priority", "State", "Escalation Reason"
    ]
    st.metric("Text-indicated open escalation candidates", len(escalation_candidates))
    show_link_table(escalation_display)
    st.warning(
        "This is a text-based indicator, not an exact transfer count. Exact L2-to-L3 reporting "
        "requires ServiceNow assignment audit/history."
    )

    st.divider()
    st.subheader("Potential Problem Candidates - Current Open Backlog")
    jira_pattern = re.compile(r"\b[A-Z]{2,10}-\d+\b")
    problem_rows = []
    for theme_name, records in executive_view[executive_view["theme"] != "Other"].groupby("theme"):
        if len(records) < 3:
            continue
        jira_references = sorted(
            set(jira_pattern.findall(" ".join(records["work_notes"].fillna("").astype(str))))
        )
        problem_rows.append(
            {
                "Candidate Theme": theme_name,
                "Related Open Tickets": len(records),
                "Critical / High": int(records["priority"].isin(["Critical", "High"]).sum()),
                "L3 Open Tickets": int((records["support_level"] == "L3").sum()),
                "Jira References": ", ".join(jira_references[:5]) if jira_references else "None found",
                "Recommendation": "Review common root cause and consider a Problem Record.",
            }
        )
    problem_candidates = pd.DataFrame(problem_rows)
    if problem_candidates.empty:
        st.info("No repeated open themes met the current Problem-candidate threshold.")
    else:
        st.dataframe(
            problem_candidates.sort_values("Related Open Tickets", ascending=False),
            use_container_width=True,
            hide_index=True,
        )
    st.caption(
        "These are candidates, not confirmed PRB records. Confirmed Problem reporting requires "
        "the ServiceNow Problem field or Problem table."
    )

    st.divider()
    st.subheader("MMTA and MMTR")
    mmta_col, mmtr_col = st.columns(2)
    with mmta_col:
        st.metric("MMTA", "Not available")
        st.caption("Requires first-assignment timestamp or assignment audit history.")
    with mmtr_col:
        mmtr_value = round(df_closed["ttr_days"].dropna().mean(), 1) if df_closed["ttr_days"].notna().any() else "Not available"
        st.metric("MMTR", mmtr_value)
        st.caption("Current-year business days from Opened to Closed when timestamps are available.")

st.divider()
st.caption(
    "EA Command Center | Live ServiceNow data | Hybrid Age and TTR use Monday-Friday business days; "
    "holidays are not excluded."
)
