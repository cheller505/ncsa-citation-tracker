"""Streamlit dashboard for the NCSA Delta/DeltaAI Citation Tracker.

Run with:  streamlit run app.py
Configuration comes entirely from the environment / .env (see config.py).
"""
from __future__ import annotations

import re

import pandas as pd
import streamlit as st

from citation_tracker import chat, db, export, systems, theme
from citation_tracker.config import get_config
from citation_tracker.pipeline import ingest

st.set_page_config(page_title="NCSA Research Computing Citation Tracker", layout="wide", page_icon="🎓")

cfg = get_config()
db.init_db()  # ensure schema exists; safe + idempotent

SYSTEM_NAMES = systems.system_names()

theme.apply(st)
theme.banner(st)
theme.lumen_sticker(st)


def _df(status: str) -> pd.DataFrame:
    rows = db.fetch_by_status(status)
    return pd.DataFrame([dict(r) for r in rows])


counts = db.counts_by_status()
c1, c2, c3 = st.columns(3)
c1.metric("Pending", counts.get("Pending", 0))
c2.metric("Verified", counts.get("Verified", 0))
c3.metric("Rejected", counts.get("Rejected", 0))

_last_batch = db.latest_batch("discovery")
if _last_batch:
    st.caption(
        f"🌙 **Last batch reviewed:** {_last_batch['finished_at']} UTC — "
        f"{_last_batch['candidates']} candidates checked · {_last_batch['new_records']} new · "
        f"{_last_batch['updated_records']} updated · {_last_batch['skipped']} already tracked"
        + (f" · {_last_batch['errors']} errors" if _last_batch['errors'] else "")
        + " (automated nightly run at 01:00)"
    )
else:
    st.caption("🌙 No automated batch has run yet — the nightly discovery run is scheduled for 01:00.")

tab_triage, tab_verified, tab_rejected, tab_stats, tab_ask, tab_about, tab_add = st.tabs(
    ["📥 Triage Queue", "✅ Verified Inventory", "📋 Rejection Log",
     "📊 Stats", "💬 Ask", "ℹ️ About", "➕ Manual Add"]
)

# --------------------------------------------------------------------------- #
# Triage tab                                                                   #
# --------------------------------------------------------------------------- #
with tab_triage:
    st.header("Pending triage")
    pending = db.fetch_by_status("Pending")

    # Confidence filter — default view shows only confident finds (>= 0.9).
    fcol1, fcol2 = st.columns([3, 2])
    with fcol1:
        min_conf = st.slider(
            "Minimum confidence to show", 0.0, 1.0, value=0.9, step=0.05,
            help="Confirmed finds are ≥ 0.90. Lower this to review less-certain "
                 "candidates; they are not flagged for review automatically.",
        )
    with fcol2:
        show_unscored = st.checkbox("Also show items with no confidence score", value=True)

    def _visible(r) -> bool:
        c = r["confidence"]
        if c is None:
            return show_unscored
        return c >= min_conf

    visible = [r for r in pending if _visible(r)]
    hidden = len(pending) - len(visible)
    if hidden:
        st.caption(f"🔽 {hidden} lower-confidence item(s) hidden — lower the threshold to review them.")
    if not visible:
        st.info("No pending citations at this confidence threshold. 🎉")
    for row in visible:
        conf = row["confidence"]
        conf_str = f" — confidence {conf:.2f}" if conf is not None else ""
        with st.expander(f"{row['title']}{conf_str}"):
            col1, col2 = st.columns([2, 1])
            with col1:
                with st.form(key=f"form_{row['id']}"):
                    title = st.text_input("Title", row["title"])
                    current = [s.strip() for s in ((row["systems"] or row["system"] or "").split(","))
                               if s.strip() and s.strip() in SYSTEM_NAMES]
                    chosen = st.multiselect("System(s) used", SYSTEM_NAMES, default=current)
                    usage = st.text_area("Usage context", row["usage_context"] or "")
                    authors = st.text_area("Authors / affiliations", row["uiuc_authors_depts"] or "")
                    award = st.text_input("Award number", row["award_number"] or "")
                    doi = st.text_input("DOI / URL", row["doi_or_url"] or "")
                    reasoning = st.text_area("Evaluator reasoning", row["reasoning"] or "")
                    if st.form_submit_button("Save changes"):
                        db.update_fields(row["id"], {
                            "title": title,
                            "system": chosen[0] if chosen else "Unknown",
                            "systems": ", ".join(chosen),
                            "usage_context": usage,
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
        verified["systems"] = verified["systems"].fillna("").replace("", None)
        verified["systems"] = verified["systems"].fillna(verified["system"])
        fc1, fc2 = st.columns(2)
        with fc1:
            sys_filter = st.multiselect("Filter by system", SYSTEM_NAMES, default=SYSTEM_NAMES)
        with fc2:
            query = st.text_input("Search title / author / award", "")

        if sys_filter:
            pattern = "|".join(re.escape(s) for s in sys_filter)
            view = verified[verified["systems"].str.contains(pattern, case=False, na=False)]
        else:
            view = verified
        if query:
            mask = (
                view["title"].str.contains(query, case=False, na=False)
                | view["uiuc_authors_depts"].str.contains(query, case=False, na=False)
                | view["award_number"].str.contains(query, case=False, na=False)
            )
            view = view[mask]

        display_cols = ["title", "systems", "award_number", "uiuc_affiliated",
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
        st.caption("Rejections are kept as an audit trail. Use the confidence range to surface "
                   "borderline rejections (the model was unsure) for a second look, then restore "
                   "any false rejection to the queue.")
        rc1, rc2 = st.columns([3, 2])
        with rc1:
            lo, hi = st.slider("Confidence range to show", 0.0, 1.0, value=(0.0, 1.0), step=0.05,
                               help="Narrow to e.g. 0.0–0.85 to review rejections the model was "
                                    "least confident about (recall safety net).")
        with rc2:
            show_unscored_rej = st.checkbox("Include items with no confidence score", value=True,
                                            key="rej_unscored")

        def _rej_visible(r) -> bool:
            c = r["confidence"]
            if c is None:
                return show_unscored_rej
            return lo <= c <= hi

        rej_visible = [r for r in rejected if _rej_visible(r)]
        rej_hidden = len(rejected) - len(rej_visible)
        if rej_hidden:
            st.caption(f"🔽 {rej_hidden} rejection(s) outside the selected confidence range.")
        for row in rej_visible:
            conf = row["confidence"]
            conf_badge = f"`{conf:.2f}`" if conf is not None else "`—`"
            cols = st.columns([4, 2, 1])
            cols[0].markdown(f"**{row['title']}**  \nconfidence {conf_badge} · _{row['reasoning'] or ''}_")
            cols[1].write(f"trigger: {row['alert_trigger'] or '—'}")
            if cols[2].button("↩ Restore", key=f"restore_{row['id']}"):
                db.set_status(row["id"], "Pending")
                st.rerun()
        st.download_button("⬇ Export rejection log (CSV)", export.to_csv("Rejected"),
                           file_name="rejected_citations.csv", mime="text/csv")

# --------------------------------------------------------------------------- #
# Stats tab — reporting view (per system, per award, by status)                #
# --------------------------------------------------------------------------- #
with tab_stats:
    st.header("Citations at a glance")
    all_rows = [dict(r) for r in db.fetch_all()]
    if not all_rows:
        st.info("No citations yet.")
    else:
        adf = pd.DataFrame(all_rows)
        adf["systems"] = adf["systems"].fillna("").replace("", None).fillna(adf["system"]).fillna("Unknown")

        def _explode_systems(frame: pd.DataFrame) -> pd.Series:
            names = []
            for val in frame["systems"]:
                parts = [p.strip() for p in str(val).split(",") if p.strip()]
                names.extend(parts or ["Unknown"])
            return pd.Series(names, dtype="object")

        st.subheader("By status")
        status_counts = adf["status"].value_counts()
        sc1, sc2, sc3 = st.columns(3)
        sc1.metric("Verified", int(status_counts.get("Verified", 0)))
        sc2.metric("Pending", int(status_counts.get("Pending", 0)))
        sc3.metric("Rejected", int(status_counts.get("Rejected", 0)))

        st.subheader("Verified citations per system")
        verified_df = adf[adf["status"] == "Verified"]
        if verified_df.empty:
            st.caption("No verified citations yet.")
        else:
            per_system = _explode_systems(verified_df).value_counts()
            per_system = per_system.reindex(SYSTEM_NAMES).dropna().astype(int)
            if not per_system.empty:
                st.bar_chart(per_system)
            st.dataframe(per_system.rename("verified papers").reset_index().rename(
                columns={"index": "system"}), use_container_width=True, hide_index=True)

        st.subheader("Verified citations per NSF award")
        award_rows = verified_df[verified_df["award_number"].fillna("") != ""]
        if award_rows.empty:
            st.caption("No verified citations with an extracted NSF award yet.")
        else:
            awards = []
            for val in award_rows["award_number"]:
                awards.extend([a.strip() for a in str(val).split(",") if a.strip()])
            aser = pd.Series(awards).value_counts().rename("verified papers")
            st.dataframe(aser.reset_index().rename(columns={"index": "award"}),
                         use_container_width=True, hide_index=True)

        st.subheader("UIUC-affiliated (verified)")
        uiuc_n = int(verified_df["uiuc_affiliated"].fillna(0).astype(int).sum()) if not verified_df.empty else 0
        st.metric("Verified papers with a UIUC author", uiuc_n)

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
        "Tracks research papers that used **NCSA and University of Illinois "
        "computing & data resources**. Candidate papers are discovered "
        "automatically, evaluated by an LLM, and confirmed by a human in the "
        "Triage Queue."
    )

    st.subheader("⚡ Powered by the NCSA Lumen LLM service")
    st.markdown(
        "Accept/reject decisions and the **Ask** assistant are powered by "
        "**[lumen.ncsa.illinois.edu](https://lumen.ncsa.illinois.edu/)**, NCSA's "
        "OpenAI-compatible large-language-model service hosting open models on "
        "NCSA hardware.\n\n"
        f"- **Evaluation model:** `{cfg.llm_model}`"
        f"{' *(LLM disabled — using keyword heuristic)*' if not cfg.llm_enabled else ''}\n"
        f"- **Ask assistant model:** `{cfg.chat_model}`\n\n"
        "Every paper's accept/reject verdict, confidence score, and reasoning in "
        "this tracker comes from that service; a transparent keyword heuristic is "
        "used only if Lumen is unreachable."
    )

    st.subheader("Resources tracked")
    st.markdown("\n".join(
        f"- **{s.name}** ({s.category})"
        + (f" — NSF {', '.join(s.awards)}" if s.awards else "")
        + f": {s.description}"
        for s in systems.get_systems()
    ))

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
