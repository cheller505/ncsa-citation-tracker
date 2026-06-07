# NCSA Research Computing Citation Tracker

A small, self-contained pipeline + web dashboard for discovering, evaluating,
and curating research papers that used NCSA and University of Illinois research
computing & data resources — **Delta**, **DeltaAI**, the **Illinois Campus
Cluster**, **Nightingale**, **Radiant**, **Taiga**, **Granite**, **ICRN**, and
the **Illinois Computes** program (all configurable in
`citation_tracker/systems.py`). It replaces the legacy
Google-Scholar-Alert-to-spreadsheet workflow with a reproducible, deployable
service.

- **Discovery** — resolve a paper title to structured metadata (OpenAlex first,
  then Crossref / Semantic Scholar / arXiv / Unpaywall).
- **Evaluation** — an LLM (default: NCSA Lumen `nemotron-3-super-120b-a12b`)
  decides whether the paper actually *used* Delta/DeltaAI, extracts a usage
  snippet, and reports a confidence score. Falls back to a transparent keyword
  heuristic if no LLM is configured.
- **Curation** — a Streamlit dashboard (NCSA/UIUC themed) for human triage, a
  searchable verified inventory, a non-destructive rejection audit log, and
  CSV/BibTeX export.
- **Automatic discovery** — a scheduled job searches OpenAlex + Crossref for the
  configured queries, skips already-tracked papers, and records every run so the
  **About** page can show which sources were checked and when.
- **Ask** — a scope-limited chat assistant (cheaper Lumen model, default
  `gemma-4-31b-it`) that answers questions grounded *only* in the tracked data.

---

## Architecture

```
                ┌─────────────────────────────────────────────┐
  title /       │  pipeline.ingest()                          │
  Scholar  ───► │   1. sources.py   (OpenAlex→Crossref→SS→arXiv→Unpaywall)
  alert         │   2. pdf.py       (safe OA-PDF fetch + extract)
                │   3. llm.py       (nemotron eval) ── fallback ─► heuristic
                │   4. db.upsert    (dedup by DOI / similar title)
                └───────────────┬─────────────────────────────┘
                                │
                       citations.db (SQLite, WAL)
                                │
        ┌───────────────────────┴───────────────────────┐
   app.py (Streamlit dashboard)              cli.py (init/ingest/bulk/export/stats)
```

Everything is configured from the environment (`.env`); nothing host-specific
is hardcoded. See `citation_tracker/config.py` for every tunable.

---

## Quick start (local)

```bash
cd /path/to/project
python3 -m venv venv
./venv/bin/pip install -r requirements.txt

cp .env.example .env          # then edit: set CONTACT_EMAIL and LLM_API_KEY
./venv/bin/python -m citation_tracker.cli init
./venv/bin/streamlit run app.py
```

Open http://localhost:8501.

### Optional: load demo data
```bash
./venv/bin/python scripts/seed_sample_data.py
```

---

## Configuration

Copy `.env.example` to `.env` and edit. The two values you **must** set:

| Variable        | Why it matters                                                        |
|-----------------|-----------------------------------------------------------------------|
| `CONTACT_EMAIL` | Required by Unpaywall and the Crossref polite pool. Use a real address. |
| `LLM_API_KEY`   | API key for the OpenAI-compatible evaluation endpoint.                |

Other useful ones: `CITATION_DB_PATH` (absolute path for services),
`LLM_ENABLED=false` (heuristic-only mode), `LLM_BASE_URL` / `LLM_MODEL`,
`TARGET_AWARDS`, `INSTITUTION_ROR`. Full list in `.env.example`.

---

## Command-line usage

```bash
# Initialize / migrate the database
python -m citation_tracker.cli init

# Ingest a single paper (e.g. from a Scholar alert)
python -m citation_tracker.cli ingest "Scalable AI on the NCSA Delta GPU" -t "NCSA Delta"

# Run one automatic discovery pass over the configured DISCOVERY_QUERIES
python -m citation_tracker.cli discover

# Run discovery continuously on an interval (the automatic-ingest daemon)
python -m citation_tracker.cli serve-ingest            # loops every INGEST_INTERVAL_HOURS
python -m citation_tracker.cli serve-ingest --once     # single pass then exit

# Ad-hoc bulk discovery for a single query
python -m citation_tracker.cli bulk "NCSA Delta supercomputer" --limit 15

# Export the verified inventory for an NSF report
python -m citation_tracker.cli export --status Verified --format csv  -o report.csv
python -m citation_tracker.cli export --status Verified --format bibtex -o report.bib

# Quick counts
python -m citation_tracker.cli stats
```

The original `init_db.py`, `ingest_alert.py`, and `bulk_search.py` still work as
thin compatibility shims.

---

## Deployment

### Docker (recommended)
```bash
cp .env.example .env   # edit it
docker compose up -d --build
```
The `web` service serves the dashboard on port 8501; the optional `ingest`
service runs daily bulk discovery. The SQLite DB lives in the `citation-data`
volume.

### systemd (bare VM)
1. Deploy the code to `/opt/citation-tracker`, create a venv, install
   `requirements.txt`, and create `.env` (set `CITATION_DB_PATH` to e.g.
   `/var/lib/citation-tracker/citations.db`).
2. Create the `citation` service user and the DB directory.
3. Copy the units from `deploy/` to `/etc/systemd/system/`, then:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now citation-tracker-web.service
   sudo systemctl enable --now citation-ingest.timer   # daily discovery
   ```

### HTTPS (Caddy reverse proxy)

`deploy/Caddyfile` serves `https://warspite.ncsa.illinois.edu:8501` and proxies
to the local Streamlit app (private on `localhost:8601`), handling Streamlit's
websocket. It uses a free Let's Encrypt certificate and serves on **port 8501**
(not 80/443).

> Cert note: the LE cert was originally obtained while Caddy briefly ran on
> 80/443 (ACME challenges only happen on those ports). Serving on 8501 reuses
> that cached cert. Because we're off 80/443, Caddy can't auto-renew — before
> the cert expires (~90 days) either re-run Caddy on 80/443 once to renew, or
> switch to a DNS-01 ACME challenge (needs DNS API credentials).

```bash
# Quick start:
sudo /usr/local/bin/caddy start --config deploy/Caddyfile

# Or as a durable systemd service (dedicated config path — this host's
# /etc/caddy/Caddyfile is the separate Boneyard portal; don't overwrite it):
sudo cp deploy/Caddyfile /etc/caddy/citation-tracker.Caddyfile
sudo cp deploy/citation-tracker-caddy.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now citation-tracker-caddy
```

If ports 80/443 aren't open to the public internet, use the `tls internal`
fallback block in the `Caddyfile` (self-signed, on port 8443).

---

## How evaluation works

`llm.py` sends the title + abstract/excerpt to the model with a strict
JSON-output contract and `response_format=json_object` (with a graceful retry
for endpoints that don't support it). The model returns
`{uses_system, system, confidence, usage_context, reasoning}`. New records land
as **Pending** (used) or **Rejected** (not used) — a human makes the final call
in the dashboard. The automated pipeline never overrides a record a human has
already Verified or Rejected.

If `LLM_ENABLED=false` or the endpoint is unreachable, a transparent keyword
heuristic is used instead (low confidence, flagged `via=heuristic`).

**Known limitation:** evaluation sees the title + abstract (and an open-access
PDF when one is found). Papers whose Delta/DeltaAI usage appears *only* in an
acknowledgements section that isn't in the abstract may be rejected. Such
rejections are kept in the audit log and can be restored to the queue; see the
suggestions in `project_status.md` for full-text acknowledgement parsing.

## Automatic discovery & the Ask assistant

- **Discovery** runs `DISCOVERY_QUERIES` against OpenAlex + Crossref. Deploy it
  as the `serve-ingest` daemon (docker-compose `ingest` service) or the
  `citation-ingest.timer` systemd unit. The **About** tab shows last-checked
  times per source.
- **Ask** is grounded only in the DB via a strict system prompt and a cheaper
  model (`CHAT_MODEL`, default `gemma-4-31b-it`). Set `CHAT_ENABLED=false` to
  hide it. It declines anything outside the citation data.

---

## Development

```bash
./venv/bin/pip install -r requirements-dev.txt
./venv/bin/python -m pytest -q
```

Tests are offline (no network calls). Layout:

```
citation_tracker/      # the package
  config.py  db.py  http.py  matching.py  sources.py  pdf.py  llm.py  pipeline.py  export.py  cli.py
app.py                 # Streamlit dashboard
scripts/               # seed data
deploy/                # systemd units
tests/                 # pytest suite
```

---

## Troubleshooting

- **"Unpaywall skipped" in logs** — set a real `CONTACT_EMAIL`.
- **Everything classified by heuristic** — check `LLM_API_KEY`/`LLM_BASE_URL`;
  the log will show the LLM error that triggered the fallback.
- **`database is locked`** — WAL + a busy timeout are enabled; ensure all
  writers point at the *same* `CITATION_DB_PATH` (absolute paths avoid this).
