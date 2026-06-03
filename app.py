import streamlit as st
import sqlite3
import pandas as pd

st.set_page_config(page_title="NCSA Delta/DeltaAI Citation Tracker", layout="wide")

def get_db_connection():
    conn = sqlite3.connect('citations.db')
    conn.row_factory = sqlite3.Row
    return conn

def update_status(citation_id, new_status):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE citations SET status = ? WHERE id = ?", (new_status, citation_id))
    conn.commit()
    conn.close()

def update_citation(citation_id, data):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
    UPDATE citations SET 
        title = ?, system = ?, alert_trigger = ?, reasoning = ?, usage_context = ?,
        uiuc_affiliated = ?, uiuc_authors_depts = ?, award_number = ?, doi_or_url = ?
    WHERE id = ?
    ''', (
        data['title'], data['system'], data['alert_trigger'], data['reasoning'], 
        data['usage_context'], data['uiuc_affiliated'], data['uiuc_authors_depts'], 
        data['award_number'], data['doi_or_url'], citation_id
    ))
    conn.commit()
    conn.close()

st.title("🚀 NCSA Delta/DeltaAI Citation Tracker")

tab1, tab2, tab3 = st.tabs(["📥 Triage Queue", "✅ Verified Inventory", "📋 Rejection Log"])

with tab1:
    st.header("Pending Triage")
    conn = get_db_connection()
    pending = pd.read_sql_query("SELECT * FROM citations WHERE status = 'Pending'", conn)
    conn.close()

    if pending.empty:
        st.info("No pending citations to triage.")
    else:
        for index, row in pending.iterrows():
            with st.expander(f"Title: {row['title']}"):
                col1, col2 = st.columns([2, 1])
                
                with col1:
                    with st.form(key=f"form_{row['id']}"):
                        title = st.text_input("Title", row['title'])
                        system = st.selectbox("System", ['Delta', 'DeltaAI', 'Unknown'], index=['Delta', 'DeltaAI', 'Unknown'].index(row['system']))
                        trigger = st.text_input("Alert Trigger", row['alert_trigger'])
                        usage = st.text_area("Usage Context", row['usage_context'])
                        authors = st.text_area("UIUC Authors/Depts", row['uiuc_authors_depts'])
                        award = st.text_input("Award Number", row['award_number'])
                        doi = st.text_input("DOI/URL", row['doi_or_url'])
                        reasoning = st.text_area("LLM Reasoning", row['reasoning'])
                        
                        submitted = st.form_submit_button("Save Changes")
                        if submitted:
                            update_citation(row['id'], {
                                'title': title, 'system': system, 'alert_trigger': trigger,
                                'usage_context': usage, 'uiuc_authors_depts': authors,
                                'award_number': award, 'doi_or_url': doi, 'reasoning': reasoning,
                                'uiuc_affiliated': 1 if authors else 0
                            })
                            st.success("Citation updated!")
                            st.rerun()

                with col2:
                    st.write("**Actions**")
                    if st.button("Verify Citation", key=f"verify_{row['id']}", type="primary"):
                        update_status(row['id'], 'Verified')
                        st.success("Citation verified!")
                        st.rerun()
                    
                    if st.button("Reject Citation", key=f"reject_{row['id']}", type="secondary"):
                        update_status(row['id'], 'Rejected')
                        st.warning("Citation rejected.")
                        st.rerun()

with tab2:
    st.header("Verified Citations")
    conn = get_db_connection()
    verified = pd.read_sql_query("SELECT * FROM citations WHERE status = 'Verified'", conn)
    conn.close()

    if verified.empty:
        st.info("No verified citations yet.")
    else:
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            system_filter = st.multiselect("Filter by System", ['Delta', 'DeltaAI', 'Unknown'], default=['Delta', 'DeltaAI'])
        with col_f2:
            search_query = st.text_input("Search (Title, Author, Award, etc.)", "")

        filtered_df = verified[verified['system'].isin(system_filter)]
        if search_query:
            filtered_df = filtered_df[
                filtered_df['title'].str.contains(search_query, case=False) |
                filtered_df['uiuc_authors_depts'].str.contains(search_query, case=False) |
                filtered_df['award_number'].str.contains(search_query, case=False)
            ]

        st.dataframe(filtered_df, use_container_width=True)

with tab3:
    st.header("Rejection Log")
    conn = get_db_connection()
    rejected = pd.read_sql_query("SELECT * FROM citations WHERE status = 'Rejected'", conn)
    conn.close()

    if rejected.empty:
        st.info("No rejected citations found.")
    else:
        st.table(rejected[['title', 'alert_trigger', 'reasoning', 'created_at']])
        
        if st.button("Clear Rejection Log"):
            conn = get_db_connection()
            conn.execute("DELETE FROM citations WHERE status = 'Rejected'")
            conn.commit()
            conn.close()
            st.rerun()
