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
- **Evaluation** — a multi-model **review board** on a locally-hosted NCSA LLM
  service (default: `nemotron-3-super-120b-a12b` + `gemma-4-31b-it` +
  `qwen3-coder-next`) judges
  whether the paper actually *used* a tracked resource. Each model votes
  independently; a 2-of-3 quorum decides, and **confidence = the models'
  agreement** (not a single model's self-score). Falls back to a single model,
  then to a transparent keyword heuristic, if the LLM service is unavailable.
- **Curation** — a Streamlit dashboard (NCSA/UIUC themed) for human triage, a
  searchable verified inventory, a non-destructive rejection audit log, and
  CSV/BibTeX export.
- **Automatic discovery** — a scheduled job searches OpenAlex + Crossref for the
  configured queries, skips already-tracked papers, and records every run so the
  **About** page can show which sources were checked and when.
- **Ask** — a scope-limited chat assistant (cheaper model, default
  `gemma-4-31b-it`) that answers questions grounded *only* in the tracked data.

---

## Architecture

```
                ┌─────────────────────────────────────────────┐
  title /       │  pipeline.ingest()                          │
  Scholar  ───► │   1. sources.py   (OpenAlex + full-text → Crossref → SS → arXiv → Unpaywall)
  alert         │   2. pdf.py       (OA-PDF fetch + acknowledgements extract)
                │   3. llm.py       (3-model review board, 2/3 quorum) ─► heuristic fallback
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

## How evaluation works — the LLM review board

Each candidate paper is judged by a **board of three diverse LLMs** running on a
locally-hosted NCSA LLM service, not a single model. The board is the core of
the tracker's accuracy.

**What each model sees.** For every paper, `pipeline._evaluate_title()` assembles
the strongest evidence it can: the title, the abstract, and — when an open-access
PDF is found — the extracted **acknowledgements / funding text** (where compute
allocations are usually disclosed). All three models receive the same evidence.

**The vote.** `llm.evaluate_quorum()` calls the models **in parallel** (default
`nemotron-3-super-120b-a12b`, `gemma-4-31b-it`, `qwen3-coder-next` — chosen for
being different model families *and* reliable on the NCSA host). Each is given a strict
JSON contract (`response_format=json_object`) and returns, independently:

```json
{ "uses_system": true, "systems": ["Delta"], "confidence": 0.95,
  "usage_context": "…", "reasoning": "…" }
```

**Consensus.** A paper is accepted only if a **majority (2 of 3)** agree it used a
tracked resource. Two things make this better than a single model:

1. **Agreement-based confidence.** The stored `confidence` is the *fraction of the
   board that agrees* with the decision — `1.0` unanimous, `~0.67` for 2-of-3 —
   not a single model's (notoriously uncalibrated) self-report. The Triage Queue
   defaults to showing only unanimous finds; split (2/3) decisions are hidden
   until you lower the confidence slider, so disagreement automatically routes a
   paper to human review.
2. **Transparency.** Every model's individual verdict is stored (`model_votes`)
   and shown in the dashboard — e.g. `🧑‍⚖️ nemotron ✅ · gemma ✅ · qwen3 ❌`.

The merged result sets the record's systems (union of the yes-voters'), status,
confidence, and reasoning. New records land as **Pending** (used) or **Rejected**
(not used); a human makes the final call. The automated pipeline never overrides
a record a human has already Verified or Rejected.

**Graceful degradation.** If some board models error or time out, the decision is
made from whoever responded (down to `EVAL_MIN_RESPONDERS`). Below that it falls
back to a single model, and if the LLM service is entirely unreachable, to a transparent
keyword heuristic (flagged `via=heuristic`, low confidence).

**Configuration** (see `.env.example`):

| Variable | Default | Meaning |
|----------|---------|---------|
| `EVAL_MODE` | `quorum` | `quorum` (board) or `single` (one model) |
| `EVAL_MODELS` | nemotron, gemma, qwen3-coder | the board roster (comma-separated) |
| `EVAL_QUORUM` | `2` | votes required to accept |
| `EVAL_MIN_RESPONDERS` | `2` | min models that must respond to trust the vote |

> **Why three, and why these three?** A reliability test across all available
> NCSA-hosted models showed `qwen3.6-35b-a3b` failing under load (HTTP 500s), so
> it's excluded;
> Nemotron, Gemma, and Qwen-coder are reliable and from three different model
> families, which is the condition under which an ensemble actually reduces error
> rather than just echoing one model thrice. Local inference on NCSA hardware is
> free, so the 3× cost is a non-issue.

**Recall note.** Because models can only judge the evidence they're given, the
biggest remaining error source is *missing* evidence — a paper whose only mention
of a system is in an acknowledgements section not present in the abstract or
fetched full text. The OpenAlex **full-text discovery source** and Google Scholar
alert ingestion (`poll-email`) are the levers that surface those papers.

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
