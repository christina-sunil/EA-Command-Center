import streamlit as st

st.set_page_config(
    page_title="EA Command Center",
    layout="wide"
)

st.title("Enterprise Applications Command Center")

tab1, tab2 = st.tabs([
    "Backlog",
    "Week in Review"
])

with tab1:
    st.header("Backlog")

with tab2:
    st.header("Week in Review")
