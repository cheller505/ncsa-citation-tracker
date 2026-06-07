# Project Status: NCSA Delta/DeltaAI Citation Tracker

## v1.0 — RSE hardening pass (handoff-ready)

Refactored from the original single-file prototype into a deployable package.

### Accuracy
- [x] **Real LLM evaluation** (`citation_tracker/llm.py`) — NCSA Lumen
      `nemotron-3-super-120b-a12b`, strict JSON output, graceful fallback to a
      transparent keyword heuristic.
- [x] **OpenAlex primary source** — structured authors, ROR-based UIUC
      affiliation, and grant/award extraction (replaces PDF string-scraping).
- [x] **Title-similarity gating** on every source — no more wrong-paper DOIs.
- [x] **DOI + near-title de-duplication**; human triage never auto-overridden.
- [x] **Timeouts + retry/backoff + polite User-Agent** on all HTTP calls.
- [x] Crossref polite pool + working Unpaywall (real `CONTACT_EMAIL`).

### Reliability / deployment
- [x] Environment-driven config (`.env`), absolute DB path support.
- [x] SQLite WAL + busy-timeout (safe concurrent ingest + UI).
- [x] Real logging, schema auto-migration from the original DB.
- [x] `requirements.txt`, `pyproject.toml`, pinned dev deps.
- [x] Dockerfile + docker-compose, systemd service + timer in `deploy/`.
- [x] pytest suite (21 tests, offline), README, seed script.

### Usability / features
- [x] Dashboard ingestion tab (paste Scholar-alert titles).
- [x] CSV + BibTeX export for NSF reporting.
- [x] Non-destructive rejection log with restore-to-queue.
- [x] CLI: `init` / `ingest` / `bulk` / `export` / `stats`.

## Backlog (Tier 3 — not yet implemented)
- [ ] Mailbox poller to auto-ingest Scholar alert emails.
- [ ] Zotero API sync.
- [ ] Reverse-proxy auth recipe for multi-user access.
