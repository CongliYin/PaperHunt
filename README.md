# Paper Hunt

English · [简体中文](README.zh-CN.md)

Paper Hunt publishes a Chinese research briefing on Agent Evolution (harness, parameters and RSI), Agent Memory, conversational shopping, and audio/video agent memory, harnesses and evolution.

**Rollout as of 2026-11-20.** The public site uses the legacy edition. The four-domain workflow is configured to run in shadow at 14:00 Shanghai time, combining arXiv screening and the preceding date's Hugging Face Daily Papers list. The live-model seed regression passed. The seven-day shadow evaluation and human-labelled holdout are pending. [Architecture and acceptance criteria](docs/superpowers/specs/2026-11-20-four-domain-paper-selection-design.md) · [Seed regression run](https://github.com/CongliYin/PaperHunt/actions/runs/44715445398)

## Architecture

- `pipeline/run_daily.py` builds a dated edition from arXiv and the **complete HF Daily Papers list**. It screens titles and abstracts, reviews all candidate/uncertain papers and every HF entry, then evaluates each domain independently. An arXiv screening rejection can be rescued by HF.
- Papers qualify per domain at F ≥ 3/4 and M + E + U ≥ 4/6, with method and evidence each ≥ 1. Each chosen domain includes a reason and a source quote. Scores and assets are shared across sources. The website shows one score out of 100 and sorts by it in descending order. New editions scale reading value (M + E + U) from six points, and historical listings use their saved overall score.
- `web/` reads immutable lists and shared details via the public index. A failed run leaves the last index in place.
- `four-domain.yml` runs at 06:00 UTC (14:00 Shanghai) for the previous calendar date and revisits the recent seven-day window, catching up after missed runs. Shadow runs write to an isolated archive and skip figure uploads. The legacy daily workflow runs at 04:00 Shanghai time and serves v1 until the repository variable `PAPER_HUNT_V2_PUBLISH=true` selects v2. Compare at least seven days and human-labelled holdouts before cutover. Once active, reverse that switch to resume the legacy writer; restore the previous data commit if rolling back published editions.
- The encrypted Actions checkpoint includes source snapshots, per-paper review/screen caches, run manifests and the shadow index. A 90-day artifact is rolled forward after each run. `EDITION_STATE_KEY` can be set as a dedicated secret. Otherwise the workflow uses `LLM_API_KEY` for checkpoint encryption; changing that key requires migrating or expiring the previous checkpoint. Production public history is retained in Git.

## Environment

GitHub Actions uses the following secrets. Figure uploads require the Blob token when publishing with Blob storage.

| Name | Purpose |
| --- | --- |
| `LLM_BASE_URL` | OpenAI-compatible base URL, without trailing `/chat/completions` |
| `LLM_API_KEY` | LLM API key |
| `LLM_MODEL_SCORING` | model for title/abstract screening and independent four-domain review |
| `LLM_MODEL_TRANSLATION` | model used for Chinese summaries |
| `BLOB_READ_WRITE_TOKEN` | Vercel Blob token for figure uploads |

Shared runtime settings

| Name | Default | Purpose |
| --- | --- | --- |
| `FIGURE_BACKEND` | `yolo` in CI | `yolo` or `pymupdf` |
| `FIGURE_MAX_COUNT` | `4` (`2` in CI) | max detail figures per paper; lower values reduce Blob advanced operations |
| `STORAGE_BACKEND` | `blob` | `blob` or `repo` |
| `ARXIV_REQUEST_INTERVAL_SECONDS` | `3.1` | minimum interval between arXiv request starts |
| `ARXIV_MAX_ATTEMPTS` | `6` | maximum attempts for transient arXiv failures |
| `ARXIV_TIMEOUT_SECONDS` | `120` | timeout for each arXiv request |
| `ARXIV_429_BACKOFF_SECONDS` | `60` | initial HTTP 429 retry delay; doubles per attempt |
| `ARXIV_TRANSIENT_BACKOFF_SECONDS` | `30` | initial timeout, 5xx, or malformed-response retry delay |
| `ARXIV_MAX_RETRY_DELAY_SECONDS` | `900` | maximum exponential retry delay before jitter |
| `ARXIV_RETRY_JITTER_SECONDS` | `5` | random delay added to each retry |
| `ARXIV_USER_AGENT` | PaperHunt repository URL | identifiable user agent sent to arXiv |

For the four-domain CLI, use `--arxiv-raw-cache-dir` (default `tmp/arxiv-raw`) and `--refresh-arxiv`. The legacy CLI also accepts `ARXIV_RAW_CACHE_DIR`, `ARXIV_REFRESH` and `RUN_TZ`. In Actions, **Four-domain daily** accepts `date`, `domains` and `seeds_only`. A dated replay automatically refreshes arXiv. The **daily** legacy workflow has its own `refresh_arxiv` input. [Four-domain workflow](.github/workflows/four-domain.yml) · [Legacy workflow](.github/workflows/daily.yml)

## Local Usage

Use Python 3.11 or later. From the repository root, install the pipeline dependencies.

```bash
pip install -r pipeline/requirements.txt
```

Replay one issue into an isolated directory. The pipeline fetches across all configured categories and reviews all domains. `--domains` selects the columns to publish.

```bash
STORAGE_BACKEND=repo FIGURE_BACKEND=pymupdf \
python pipeline/run_daily.py --date 2026-06-12 --domains agent-memory \
  --output tmp/shadow/data --state-dir tmp/shadow/state
```

For a real-source smoke test without LLM calls:

```bash
python pipeline/run_daily.py --date 2026-06-12 --domains agent-memory --skip-llm --output tmp/source-check/data
```

Force a fresh arXiv fetch for a specific edition:

```bash
python pipeline/run_daily.py --date 2026-06-12 --refresh-arxiv
```

Run the frontend:

```bash
cd web
npm install
npm run dev
```

## Add A Domain

```bash
python pipeline/add_domain.py robotics
# edit pipeline/domains/robotics/*.yaml and scoring_criteria.md
python pipeline/validate_domain.py robotics
python pipeline/run_daily.py --domains robotics --date 2026-06-12
```

Set the arXiv categories in `domain.yaml`. Domain definitions for the new edition live in `pipeline/domains/<domain>/review.yaml`. Each contains a scope, near negatives and recall phrases. The legacy publisher reads `selection_policy.yaml`, `topic_keywords.yaml` and `scoring_criteria.md`. Its entry point is `pipeline/legacy_daily.py`. The historical comparison also reads `filter_keywords.yaml`. To run locally without changing public results, use `--output tmp/shadow/data --state-dir tmp/shadow/state`; use `--date` for an isolated replay.

## Validation

```bash
python -m unittest discover -s tests
python pipeline/evaluate_selection_quality.py
cd web && npm ci && npm run build
```

To measure the new recommender, label sampled pairs as JSON objects in an array with `date`, `arxiv_id`, `domain`, boolean `relevant` and boolean `recommend`. Run `python pipeline/evaluate_editions.py labels.json tmp/edition-state/runs/*.json` with one complete manifest for each date. Use `--grid` on development dates only. Report precision, recall and denominators on untouched dates; include rejected candidates in sampling. Legacy gold regression results measure the legacy selector only. With configured scoring credentials run `python pipeline/check_edition_seeds.py` (or select `seeds_only` in Four-domain daily) to check four real papers against the new domain scopes.

## Vercel Deployment

Create a Vercel project with root directory set to `web/`. The site needs no backend API. Generated JSON is committed under `web/public/data`; figure URLs are absolute Vercel Blob URLs by default.

Create a public Vercel Blob store and copy its `BLOB_READ_WRITE_TOKEN` into GitHub Actions secrets. The Python pipeline uploads figures through Vercel Blob's HTTP API. If you set `STORAGE_BACKEND=repo`, figures are written to `web/public/figures` instead, which is useful for local/offline debugging but not recommended for daily production use.

## Notes

- Local v2 replays can reuse complete raw category files for the same query window. Scheduled v2 runs refresh arXiv. Across Actions runs the encrypted v2 checkpoint restores normalized source snapshots, screening and review decisions, and asset metadata. The separate raw-category Actions cache belongs to the legacy workflow.
- Requests are sequential and start at least 3.1 seconds apart. HTTP 429/5xx responses, timeouts, connection errors, and malformed XML are retried with minute-scale bounded backoff. If the fetch still fails, the whole job exits non-zero before domain processing, so incomplete data is never committed. An empty individual category is valid when the daily response contains papers elsewhere; an all-category empty response is treated as unreliable and is neither published nor cached.
- DocLayout-YOLO is AGPL-3.0. This project uses it in an offline CI batch pipeline to generate static images. The Vercel frontend does not serve the model or expose model inference. Re-check licensing before closed-source or commercial use of the pipeline code.
- `tmp/` and model caches are intentionally ignored. Legacy phase intermediates under `reports/*/*/tmp/` are kept during runs for re-runs and debugging but should not be committed.
- Blob cleanup is available through `FigureStorage.delete_older_than(days)`, which lists blobs under the configured prefix and deletes older URLs through the Vercel Blob HTTP API.
