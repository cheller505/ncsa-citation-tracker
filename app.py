"""Streamlit dashboard for the NCSA Delta/DeltaAI Citation Tracker.

Run with:  streamlit run app.py
Configuration comes entirely from the environment / .env (see config.py).
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from citation_tracker import chat, db, export, theme
from citation_tracker.config import get_config
from citation_tracker.pipeline import ingest

st.set_page_config(page_title="NCSA Delta/DeltaAI Citation Tracker", layout="wide", page_icon="🎓")

cfg = get_config()
db.init_db()  # ensure schema exists; safe + idempotent

theme.apply(st)
theme.banner(st)


def _df(status: str) -> pd.DataFrame:
    rows = db.fetch_by_status(status)
    return pd.DataFrame([dict(r) for r in rows])


counts = db.counts_by_status()
c1, c2, c3 = st.columns(3)
c1.metric("Pending", counts.get("Pending", 0))
c2.metric("Verified", counts.get("Verified", 0))
c3.metric("Rejected", counts.get("Rejected", 0))

tab_triage, tab_verified, tab_rejected, tab_ask, tab_about, tab_add = st.tabs(
    ["📥 Triage Queue", "✅ Verified Inventory", "📋 Rejection Log",
     "💬 Ask", "ℹ️ About", "➕ Manual Add"]
)

# --------------------------------------------------------------------------- #
# Triage tab                                                                   #
# --------------------------------------------------------------------------- #
with tab_triage:
    st.header("Pending triage")
    pending = db.fetch_by_status("Pending")
    if not pending:
        st.info("No pending citations to triage. 🎉")
    for row in pending:
        conf = row["confidence"]
        conf_str = f" — confidence {conf:.2f}" if conf is not None else ""
        with st.expander(f"{row['title']}{conf_str}"):
            col1, col2 = st.columns([2, 1])
            with col1:
                with st.form(key=f"form_{row['id']}"):
                    title = st.text_input("Title", row["title"])
                    system = st.selectbox(
                        "System", ["Delta", "DeltaAI", "Unknown"],
                        index=["Delta", "DeltaAI", "Unknown"].index(row["system"] or "Unknown"),
                    )
                    usage = st.text_area("Usage context", row["usage_context"] or "")
                    authors = st.text_area("Authors / affiliations", row["uiuc_authors_depts"] or "")
                    award = st.text_input("Award number", row["award_number"] or "")
                    doi = st.text_input("DOI / URL", row["doi_or_url"] or "")
                    reasoning = st.text_area("Evaluator reasoning", row["reasoning"] or "")
                    if st.form_submit_button("Save changes"):
                        db.update_fields(row["id"], {
                            "title": title, "system": system, "usage_context": usage,
                            "uiuc_authors_depts": authors, "award_number": award,
                            "doi_or_url": doi, "reasoning": reasoning,
                            "uiuc_affiliated": 1 if authors.strip() else 0,
                        })
                        st.success("Saved.")
                        st.rerun()
            with col2:
                st.write(f"**UIUC affiliated:** {'Yes' if row['uiuc_affiliated'] else 'No'}")
                st.write(f"**Evaluator:** {row['source'] or 'n/a'}")
                st.write(f"**Trigger:** {row['alert_trigger'] or '—'}")
                if st.button("✅ Verify", key=f"verify_{row['id']}", type="primary"):
                    db.set_status(row["id"], "Verified")
                    st.rerun()
                if st.button("❌ Reject", key=f"reject_{row['id']}"):
                    db.set_status(row["id"], "Rejected")
                    st.rerun()

# --------------------------------------------------------------------------- #
# Verified tab — searchable + export                                           #
# --------------------------------------------------------------------------- #
with tab_verified:
    st.header("Verified citations")
    verified = _df("Verified")
    if verified.empty:
        st.info("No verified citations yet.")
    else:
        fc1, fc2 = st.columns(2)
        with fc1:
            sys_filter = st.multiselect("Filter by system", ["Delta", "DeltaAI", "Unknown"],
                                        default=["Delta", "DeltaAI"])
        with fc2:
            query = st.text_input("Search title / author / award", "")

        view = verified[verified["system"].isin(sys_filter)]
        if query:
            mask = (
                view["title"].str.contains(query, case=False, na=False)
                | view["uiuc_authors_depts"].str.contains(query, case=False, na=False)
                | view["award_number"].str.contains(query, case=False, na=False)
            )
            view = view[mask]

        display_cols = ["title", "system", "award_number", "uiuc_affiliated",
                        "usage_context", "doi_or_url"]
        st.dataframe(view[display_cols], use_container_width=True)

        ec1, ec2 = st.columns(2)
        ec1.download_button("⬇ Export CSV", export.to_csv("Verified"),
                            file_name="verified_citations.csv", mime="text/csv")
        ec2.download_button("⬇ Export BibTeX", export.to_bibtex("Verified"),
                            file_name="verified_citations.bib", mime="text/plain")

# --------------------------------------------------------------------------- #
# Rejection tab — audit trail, non-destructive                                 #
# --------------------------------------------------------------------------- #
with tab_rejected:
    st.header("Rejection log (audit trail)")
    rejected = db.fetch_by_status("Rejected")
    if not rejected:
        st.info("No rejected citations.")
    else:
        st.caption("Rejections are kept as an audit trail. Restore any false rejection to the queue.")
        for row in rejected:
            cols = st.columns([4, 2, 1])
            cols[0].markdown(f"**{row['title']}**  \n_{row['reasoning'] or ''}_")
            cols[1].write(f"trigger: {row['alert_trigger'] or '—'}")
            if cols[2].button("↩ Restore", key=f"restore_{row['id']}"):
                db.set_status(row["id"], "Pending")
                st.rerun()
        st.download_button("⬇ Export rejection log (CSV)", export.to_csv("Rejected"),
                           file_name="rejected_citations.csv", mime="text/csv")

# --------------------------------------------------------------------------- #
# Ask tab — scope-limited chat over the tracked data                           #
# --------------------------------------------------------------------------- #
with tab_ask:
    st.header("Ask about the tracked citations")
    if not chat.is_configured():
        st.warning("Chat is disabled or no LLM key is configured (CHAT_ENABLED / LLM_API_KEY).")
    else:
        st.caption(
            f"Grounded only in this project's data using **{cfg.chat_model}**. "
            "It will decline anything outside the citation records."
        )
        if "chat_history" not in st.session_state:
            st.session_state.chat_history = []

        col_a, col_b = st.columns([6, 1])
        with col_b:
            if st.button("Clear", key="clear_chat"):
                st.session_state.chat_history = []
                st.rerun()

        for turn in st.session_state.chat_history:
            with st.chat_message(turn["role"]):
                st.markdown(turn["content"])

        prompt = st.chat_input("e.g. Which verified papers used DeltaAI?")
        if prompt:
            st.session_state.chat_history.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)
            with st.chat_message("assistant"):
                with st.spinner("Thinking…"):
                    try:
                        answer = chat.ask(prompt, history=st.session_state.chat_history[:-1])
                    except chat.ChatError as exc:
                        answer = f"⚠️ {exc}"
                st.markdown(answer)
            st.session_state.chat_history.append({"role": "assistant", "content": answer})

        with st.expander("Example questions"):
            st.markdown(
                "- How many verified papers are there per system?\n"
                "- List the papers associated with award OAC-2320345.\n"
                "- Which pending papers have UIUC authors?\n"
                "- Why was a given paper rejected?"
            )

# --------------------------------------------------------------------------- #
# About tab — what's tracked, which sources, when last checked                 #
# --------------------------------------------------------------------------- #
with tab_about:
    st.header("About this tracker")
    st.markdown(
        "Tracks research papers that used the NCSA **Delta** "
        f"(NSF {cfg.target_awards[0] if cfg.target_awards else 'OAC-2005572'}) and "
        "**DeltaAI** "
        f"({cfg.target_awards[1] if len(cfg.target_awards) > 1 else 'OAC-2320345'}) "
        "supercomputers. Candidate papers are discovered automatically, evaluated "
        f"by an LLM (**{cfg.llm_model if cfg.llm_enabled else 'heuristic (LLM disabled)'}**), "
        "and confirmed by a human in the Triage Queue."
    )

    st.subheader("Data sources checked")
    st.markdown(
        "- **OpenAlex** — primary discovery + structured authors, institution "
        "(ROR) affiliation, and grant/award metadata.\n"
        "- **Crossref** — discovery + DOI resolution (polite pool).\n"
        "- **Semantic Scholar** — abstracts and open-access PDF links.\n"
        "- **arXiv** — preprint matching.\n"
        "- **Unpaywall** — best open-access PDF for a DOI."
    )

    st.subheader("Automatic discovery status")
    latest = db.latest_run_per_source()
    if not latest:
        st.info("No automatic discovery has run yet. Start it with "
                "`python -m citation_tracker.cli serve-ingest` (or the systemd timer).")
    else:
        st.dataframe(
            pd.DataFrame([{
                "Source": r["source"],
                "Last checked": r["finished_at"] or r["started_at"],
                "Last query": r["query"],
                "Status": r["status"],
            } for r in latest]),
            use_container_width=True,
        )

    st.markdown("**Configured discovery queries:**")
    st.code("\n".join(cfg.discovery_queries) or "(none)")
    st.caption(f"Discovery interval: every {cfg.ingest_interval_hours:g} h "
               f"· up to {cfg.discovery_limit} candidates per source per query.")

    with st.expander("Recent discovery runs"):
        runs = db.recent_runs(limit=25)
        if runs:
            st.dataframe(
                pd.DataFrame([{
                    "Started": r["started_at"], "Source": r["source"], "Query": r["query"],
                    "Found": r["candidates_found"], "New": r["new_records"],
                    "Updated": r["updated_records"], "Status": r["status"],
                } for r in runs]),
                use_container_width=True,
            )
        else:
            st.write("No runs recorded yet.")

# --------------------------------------------------------------------------- #
# Manual add tab (optional — kept for ad-hoc entries)                          #
# --------------------------------------------------------------------------- #
with tab_add:
    st.header("Manually ingest a paper")
    st.caption(
        "Discovery runs automatically; this is for ad-hoc one-off entries "
        "(e.g. a paper someone forwards you). Paste one title per line."
    )
    titles_text = st.text_area("Titles (one per line)", height=140, key="ingest_titles")
    trigger = st.text_input("Trigger / note (optional)", value="manual", key="ingest_trigger")
    if st.button("Run ingestion", type="primary"):
        titles = [t.strip() for t in titles_text.splitlines() if t.strip()]
        if not titles:
            st.warning("Enter at least one title.")
        else:
            progress = st.progress(0.0)
            results = []
            for i, title in enumerate(titles, start=1):
                try:
                    r = ingest(title, trigger=trigger)
                    results.append({"Title": title, "Status": r.status, "System": r.system,
                                    "Confidence": round(r.confidence, 2), "Via": r.evaluator,
                                    "Action": r.action})
                except Exception as exc:  # noqa: BLE001
                    results.append({"Title": title, "Status": "ERROR", "System": "",
                                    "Confidence": 0, "Via": str(exc)[:60], "Action": ""})
                progress.progress(i / len(titles))
            st.success(f"Processed {len(results)} title(s).")
            st.dataframe(pd.DataFrame(results), use_container_width=True)
