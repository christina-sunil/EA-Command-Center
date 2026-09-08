import math
import numpy as np
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="EA Command Center", page_icon="📊", layout="wide")
INSTANCE_URL = "https://progress1.service-now.com"
USERNAME = st.secrets.get("SERVICENOW_USERNAME", "github_servicenow_api")
PASSWORD = st.secrets.get("SERVICENOW_PASSWORD", "wL<c&sLHGso(mH3mIRs=byF5C%97o>P3z[K+QZSD")

EA_GROUPS = [
    "IT Supp: EAST - Delivery", "IT Supp: EAST - Leads",
    "IT Supp: System Access Requests", "IT Supp: System Admins",
    "IT Supp: ShareFile - CPQ", "IT Supp: Quote to Invoice",
    "IT Supp: Lead to Opp", "IT Supp: Mulesoft Product Support",
    "IT Supp: EA Shared Services", "IT Supp: CS/TS",
]
GROUP_QUERY = ",".join(EA_GROUPS)
AGE_THRESHOLDS = [(0,1),(3,2),(7,4),(14,6),(30,8),(60,9),(90,10)]
INACTIVITY_THRESHOLDS = [(0,1),(2,3),(5,5),(10,7),(20,9),(30,10)]
REASSIGNMENT_THRESHOLDS = [(0,1),(1,3),(2,5),(4,7),(6,9),(8,10)]
THEME_KEYWORDS = {
    "Access / Permissions": ["access","permission","login","password","role","security"],
    "License / Renewal": ["license","licence","renewal","renew","subscription","entitlement"],
    "Salesforce / CRM": ["salesforce","sfdc","crm","opportunity","lead","contact"],
    "Integration": ["integration","mulesoft","api","interface","sync","job","failure"],
    "ShareFile / CPQ": ["sharefile","cpq","quote","quoting","order","invoice"],
    "Data / Reporting": ["report","reporting","tableau","dashboard","data","upload","extract"],
}

def clean_display(v):
    if isinstance(v, dict): return v.get("display_value", "") or v.get("value", "") or ""
    return "" if v is None else str(v).strip()

def map_priority(v):
    p = str(v).lower().strip()
    if p.startswith("1") or "critical" in p: return "Critical"
    if p.startswith("2") or "high" in p: return "High"
    if p.startswith("3") or "moderate" in p or "medium" in p: return "Medium"
    if p.startswith("4") or "low" in p: return "Low"
    return "Other"

def level_from_group(g):
    g = str(g)
    if "System Access Requests" in g: return "Access"
    if "EAST - Delivery" in g: return "L1"
    if "EAST - Leads" in g: return "L2"
    if "System Admins" in g: return "Sys Admin"
    if any(x in g for x in ["ShareFile - CPQ","Quote to Invoice","Lead to Opp","Mulesoft Product Support","EA Shared Services","CS/TS"]): return "Dev / Eng"
    return "Other"

def business_days_between(start, end):
    if pd.isna(start) or pd.isna(end): return np.nan
    start, end = pd.Timestamp(start).date(), pd.Timestamp(end).date()
    return 0.0 if end <= start else float(np.busday_count(start, end))

def period_start(name):
    today = pd.Timestamp.now().normalize()
    if name == "Week": return today - pd.Timedelta(days=today.weekday())
    if name == "Month": return today.replace(day=1)
    if name == "Quarter": return today.replace(month=((today.month-1)//3)*3+1, day=1)
    return today.replace(month=1, day=1)

def previous_period_range(name):
    current = period_start(name)
    delta = {"Week": pd.Timedelta(days=7), "Month": pd.DateOffset(months=1), "Quarter": pd.DateOffset(months=3), "Year": pd.DateOffset(years=1)}[name]
    return current - delta, current

def threshold_score(value, thresholds):
    if pd.isna(value): return 0
    result = 1
    for minimum, score in thresholds:
        if value >= minimum: result = score
        else: break
    return result

def priority_score(p): return {"Critical":10,"High":8,"Medium":5,"Low":2,"Other":1}.get(p,1)

def identify_theme(text):
    text = str(text).lower()
    for theme, words in THEME_KEYWORDS.items():
        if any(w in text for w in words): return theme
    return "Other"

def theme_summary(data):
    if data.empty: return pd.DataFrame(columns=["Theme","Tickets","Share %"])
    s = data["short_description"].apply(identify_theme).value_counts().rename_axis("Theme").reset_index(name="Tickets")
    s["Share %"] = (s["Tickets"] / s["Tickets"].sum() * 100).round(1)
    return s

@st.cache_data(show_spinner="Loading Progress tickets...")
def load_table(table, query, fields, max_rows):
    if not USERNAME or not PASSWORD:
        raise RuntimeError("Add SERVICENOW_USERNAME and SERVICENOW_PASSWORD in Streamlit Secrets.")
    url, rows, page_size = f"{INSTANCE_URL}/api/now/table/{table}", [], 2000
    for offset in range(0, max_rows, page_size):
        params = {"sysparm_query":query,"sysparm_display_value":"true","sysparm_exclude_reference_link":"true","sysparm_limit":str(min(page_size,max_rows-offset)),"sysparm_offset":str(offset),"sysparm_fields":fields}
        r = requests.get(url, params=params, auth=(USERNAME,PASSWORD), headers={"Accept":"application/json"}, timeout=60)
        if r.status_code >= 400: raise RuntimeError(f"ServiceNow API error for {table}: {r.status_code} - {r.text[:500]}")
        batch = r.json().get("result", [])
        if not batch: break
        rows.extend(batch)
        if len(batch) < page_size: break
    return pd.DataFrame(rows)

def prepare(df, ticket_type):
    required = ["sys_id","number","short_description","assignment_group","assigned_to","priority","state","active","sys_created_on","sys_updated_on","closed_at","reassignment_count"]
    if df.empty: return pd.DataFrame(columns=required+["ticket_type","open_date","updated_date","closed_date","level"])
    df = df.copy()
    for c in required:
        if c not in df.columns: df[c] = ""
    df["ticket_type"] = ticket_type
    for c in ["assignment_group","assigned_to","state","short_description"]: df[c] = df[c].apply(clean_display)
    df["priority"] = df["priority"].apply(map_priority)
    df["open_date"] = pd.to_datetime(df["sys_created_on"], errors="coerce")
    df["updated_date"] = pd.to_datetime(df["sys_updated_on"], errors="coerce")
    df["closed_date"] = pd.to_datetime(df["closed_at"], errors="coerce")
    df["reassignment_count"] = pd.to_numeric(df["reassignment_count"], errors="coerce").fillna(0)
    df["level"] = df["assignment_group"].apply(level_from_group)
    df["ticket_url"] = df.apply(lambda r: f"{INSTANCE_URL}/task.do?sys_id={r['sys_id']}&number={r['number']}", axis=1)
    return df

@st.cache_data(show_spinner="Preparing EA Command Center data...")
def get_data(max_rows):
    fields = "sys_id,number,short_description,assignment_group,assigned_to,priority,state,active,sys_created_on,sys_updated_on,closed_at,reassignment_count"
    open_q = f"active=true^assignment_group.nameIN{GROUP_QUERY}"
    year = pd.Timestamp.now().year
    review_q = f"assignment_group.nameIN{GROUP_QUERY}^sys_created_on>={year}-01-01 00:00:00"
    backlog = pd.concat([prepare(load_table("sc_req_item",open_q,fields,max_rows),"RITM"),prepare(load_table("incident",open_q,fields,max_rows),"INC")], ignore_index=True)
    review = pd.concat([prepare(load_table("sc_req_item",review_q,fields,max_rows),"RITM"),prepare(load_table("incident",review_q,fields,max_rows),"INC")], ignore_index=True)
    now = pd.Timestamp.now()
    if not backlog.empty:
        backlog["ticket_age_days"] = backlog["open_date"].apply(lambda x: business_days_between(x,now))
        backlog["inactivity_days"] = backlog["updated_date"].apply(lambda x: business_days_between(x,now))
        backlog["intervention_score"] = (backlog["ticket_age_days"].apply(lambda x: threshold_score(x,AGE_THRESHOLDS))*0.35 + backlog["inactivity_days"].apply(lambda x: threshold_score(x,INACTIVITY_THRESHOLDS))*0.30 + backlog["priority"].apply(priority_score)*0.20 + backlog["reassignment_count"].apply(lambda x: threshold_score(x,REASSIGNMENT_THRESHOLDS))*0.15).round(2)
    if not review.empty:
        review["ticket_age_days"] = review.apply(lambda r: business_days_between(r["open_date"], r["closed_date"] if pd.notna(r["closed_date"]) else now), axis=1)
        review["ttr_days"] = review.apply(lambda r: business_days_between(r["open_date"],r["closed_date"]) if pd.notna(r["closed_date"]) else np.nan, axis=1)
    return backlog, review

def show_link_table(df):
    st.dataframe(df, use_container_width=True, hide_index=True, column_config={"Ticket": st.column_config.LinkColumn("Ticket", display_text=r"number=([^&]+)$")})

st.title("Enterprise Applications Command Center")
st.caption("Progress ticket operational scorecard. Hybrid Age and TTR exclude Saturday and Sunday.")
c1,c2 = st.columns([3,1])
with c1: max_rows = st.selectbox("Maximum records to load per table",[2000,5000,10000,20000],index=2)
with c2:
    st.write(""); st.write("")
    if st.button("Refresh data",use_container_width=True): st.cache_data.clear(); st.rerun()
try: backlog, review = get_data(max_rows)
except Exception as e: st.error(str(e)); st.stop()

tab1,tab2 = st.tabs(["Backlog","Week in Review"])
with tab1:
    st.header("Backlog")
    if backlog.empty: st.warning("No active Progress tickets were returned.")
    else:
        f1,f2 = st.columns(2)
        with f1: groups = st.multiselect("Assignment Group",sorted(backlog["assignment_group"].dropna().unique()))
        with f2: owners = st.multiselect("Provider / Assigned To",sorted(x for x in backlog["assigned_to"].dropna().unique() if x))
        data = backlog.copy()
        if groups: data = data[data["assignment_group"].isin(groups)]
        if owners: data = data[data["assigned_to"].isin(owners)]
        total, assigned = len(data), int(data["assigned_to"].fillna("").str.strip().ne("").sum())
        cols = st.columns(9)
        for col,label,value in zip(cols,["Total","Access","L1","L2","Sys Admin","Dev / Eng","Assigned","Unassigned","Avg Hybrid Age"],[total,*[int((data["level"]==x).sum()) for x in ["Access","L1","L2","Sys Admin","Dev / Eng"]],assigned,total-assigned,round(data["ticket_age_days"].mean(),1) if total else 0]): col.metric(label,value)
        st.divider(); st.subheader("Assignment Group Scorecard")
        closed_period = st.selectbox("Closed Ticket Period",["Week","Month","Quarter","Year"])
        closed = review[review["closed_date"].notna() & (review["closed_date"] >= period_start(closed_period))]
        rows=[]
        for group,g in data.groupby("assignment_group"):
            ga=int(g["assigned_to"].fillna("").str.strip().ne("").sum())
            rows.append({"Assignment Group":group,"Backlog":len(g),**{x:int((g["level"]==x).sum()) for x in ["Access","L1","L2","Sys Admin","Dev / Eng"]},"Closed":int((closed["assignment_group"]==group).sum()),"Assigned":ga,"Unassigned":len(g)-ga,"Avg Hybrid Age":round(g["ticket_age_days"].mean(),1)})
        st.dataframe(pd.DataFrame(rows).sort_values("Backlog",ascending=False),use_container_width=True,hide_index=True)
        st.divider(); st.subheader("Top 10 Ticket Investigation")
        i1,i2=st.columns(2)
        with i1: view=st.selectbox("View",["Oldest","Newest","Last Updated","Highest Intervention Score"])
        with i2: age=st.selectbox("Age Filter",["All",">5 Business Days"])
        inv=data.copy()
        if age==">5 Business Days": inv=inv[inv["ticket_age_days"]>5]
        key,asc={"Oldest":("ticket_age_days",False),"Newest":("open_date",False),"Last Updated":("updated_date",True),"Highest Intervention Score":("intervention_score",False)}[view]
        inv=inv.sort_values(key,ascending=asc).head(10)[["ticket_url","ticket_type","short_description","assignment_group","assigned_to","priority","level","ticket_age_days","inactivity_days","updated_date","intervention_score"]]
        inv.columns=["Ticket","Type","Short Description","Assignment Group","Assigned To","Priority","Work Type","Hybrid Age","Business Days Since Update","Last Updated","Intervention Score"]
        show_link_table(inv)

with tab2:
    st.header("Week in Review")
    if review.empty: st.warning("No Progress tickets were returned for the review period.")
    else:
        r1,r2=st.columns(2)
        with r1: group=st.selectbox("Assignment Group",["All Assignment Groups"]+sorted(review["assignment_group"].dropna().unique()))
        with r2: period=st.selectbox("Period",["Week","Month","Quarter","Year"])
        data=review[review["open_date"]>=period_start(period)].copy()
        if group!="All Assignment Groups": data=data[data["assignment_group"]==group]
        assigned=int(data["assigned_to"].fillna("").str.strip().ne("").sum()); closed=int(data["closed_date"].notna().sum())
        values=[len(data),assigned,closed,int(data["closed_date"].isna().sum()),round(data["ttr_days"].dropna().mean(),1) if data["ttr_days"].notna().any() else 0,round(data["ticket_age_days"].mean(),1) if len(data) else 0]
        for c,l,v in zip(st.columns(6),["New","Assigned","Closed","Open / Backlog","Average TTR","Average Hybrid Age"],values): c.metric(l,v)
        st.divider(); st.subheader("Theme & Trend Analysis")
        themes=theme_summary(data)
        if themes.empty: st.info("No tickets are available for theme analysis.")
        else: st.dataframe(themes,use_container_width=True,hide_index=True)
        ps,pe=previous_period_range(period); previous=review[(review["open_date"]>=ps)&(review["open_date"]<pe)]
        if group!="All Assignment Groups": previous=previous[previous["assignment_group"]==group]
        if len(previous): st.metric("Change vs Previous Period",f"{round((len(data)-len(previous))/len(previous)*100,1)}%",f"{len(data)-len(previous):+d} tickets")
        else: st.info("No previous-period data is available for comparison.")
        st.divider(); st.subheader("Improvement Opportunities")
        inactivity=data["updated_date"].apply(lambda x: business_days_between(x,pd.Timestamp.now()))
        opportunities=pd.DataFrame([
            {"Opportunity":"Review tickets over 120 business hours","Ticket Count":int((data["ticket_age_days"]>5).sum()),"Suggested Focus":"Confirm owner, blocker, and next action."},
            {"Opportunity":"Assign unassigned tickets","Ticket Count":int(data["assigned_to"].fillna("").str.strip().eq("").sum()),"Suggested Focus":"Confirm assignment group and provider."},
            {"Opportunity":"Review open high-priority tickets","Ticket Count":int((data["priority"].isin(["Critical","High"])&data["closed_date"].isna()).sum()),"Suggested Focus":"Confirm priority, owner, and resolution plan."},
            {"Opportunity":"Review tickets not updated over 5 business days","Ticket Count":int((inactivity>5).sum()),"Suggested Focus":"Request status and documented next step."},
        ])
        st.dataframe(opportunities,use_container_width=True,hide_index=True)
        st.divider(); st.subheader("Ticket Set")
        display=data[["ticket_url","ticket_type","short_description","assignment_group","assigned_to","priority","level","state","open_date","closed_date","ticket_age_days","ttr_days"]].copy()
        display.columns=["Ticket","Type","Short Description","Assignment Group","Assigned To","Priority","Work Type","State","Opened","Closed","Hybrid Age","TTR"]
        show_link_table(display)

st.divider(); st.caption("EA Command Center | Progress operational metrics | Hybrid Age uses business days only.")
