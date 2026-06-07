# Project Status: NCSA / Illinois Research Citation Tracker

## v2.0 — multi-system expansion + integrations

- [x] **Configurable systems registry** (`systems.py`): Delta, DeltaAI, Illinois
      Campus Cluster, Nightingale, Radiant, Taiga, Granite, ICRN, Illinois
      Computes — each with awards, aliases, scoped search queries, and
      false-positive guards. Overridable via `SYSTEMS_FILE`.
- [x] **DB is multi-system aware**: dropped the legacy `system` CHECK (table
      rebuild migration), added `systems` (comma-separated) + `zotero_key`.
- [x] **LLM eval recognizes all systems** and returns a multi-system list;
      verified live (Delta+Taiga+Granite detected together; granite rock
      rejected). Decisions are made by **Lumen nemotron** (confirmed).
- [x] **Recall fix**: acknowledgement/funding full-text extraction fed to the
      evaluator; uncertain "not used" verdicts route to Pending, not Rejected.
- [x] **Discovery queries** derived from the registry (NCSA/Illinois-scoped).
- [x] **Chat fixed**: root cause was the missing `reasoning` field in context;
      now answers "why rejected", counts per system, declines off-topic.
      Default model `gemma-4-31b-it` (qwen3.6 is unreliable on Lumen → 500s).
- [x] **Lumen branding**: "Powered by NCSA Lumen LLM" sticker on the front page;
      About page documents lumen.ncsa.illinois.edu and the models used.
- [x] **Integrations**: Google Scholar Alert IMAP poller (`poll-email`), Zotero
      sync (`zotero-sync`), Semantic Scholar API key, DB `backup` command.
- [x] Tests: 38 passing (systems, discovery [mocked], routing, multi-system).

## v1.x (earlier)

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
