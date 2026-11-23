# Paper Hunt

English · [简体中文](README.zh-CN.md)

Paper Hunt publishes a Chinese research briefing on Agent Evolution (harness, parameters and RSI), Agent Memory, conversational shopping, and audio/video agent memory, harnesses and evolution.

**Production since 2026-11-20.** The Four-domain daily workflow publishes scheduled editions and manual replays from main. It combines arXiv screening and the preceding date's Hugging Face Daily Papers list. The live-model seed regression passed; independent human-labelled evaluation is ongoing. [Architecture and acceptance criteria](docs/superpowers/specs/2026-11-20-four-domain-paper-selection-design.md) · [Seed regression run](https://github.com/CongliYin/PaperHunt/actions/runs/44715445398)

## Architecture

- arXiv and the complete HF Daily Papers feed share the same title/abstract rules, exclusions, screening and evidence-based review. Being listed on HF neither bypasses screening nor adds points. Each accepted paper belongs to one column.
- Evolution and Memory focus on text/software agents and exclude embodied systems, robots, 3D, world models and multimodal/omni work. The multimodal column includes image, voice, video and omni agents but excludes robots, embodied systems, 3D, autonomous driving and cameras. Shopping requires buyer context or interaction that changes product discovery or recommendation.
- Central contribution (F = 4), distinct verbatim contribution and result evidence, M ≥ 2 and E ≥ 2 are required. Method (M), evidence (E) and utility (U) are graded 0–5. The score is **6M + 9E + 5U**, minimum 60/100. Evidence above 3 requires an excerpt from supplementary PDF text outside the abstract. Of qualifying domains the highest score wins; ties prefer shopping, multimodal, memory, then evolution. Historical cards keep their original scales until replayed.
- `web/` reads immutable lists and shared details via the public index. A failed run leaves the last index in place.
- `four-domain.yml` runs at 06:00 UTC (14:00 Shanghai) for the previous calendar date and revisits the recent seven-day window, catching up after missed runs. For a manual edition, open Actions → Four-domain daily → Run workflow, select main, enter the issue date (YYYY-MM-DD) and leave domains empty to publish all four columns.
- The encrypted Actions checkpoint includes source snapshots, per-paper review/screen caches, and run manifests. A 90-day artifact is rolled forward after each run. `EDITION_STATE_KEY` can be set as a dedicated secret. Otherwise the workflow uses `LLM_API_KEY` for checkpoint encryption; changing that key requires migrating or expiring the previous checkpoint. Production public history is retained in Git.

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

For the four-domain CLI, use `--arxiv-raw-cache-dir` (default `tmp/arxiv-raw`) and `--refresh-arxiv`. The legacy CLI also accepts `ARXIV_RAW_CACHE_DIR`, `ARXIV_REFRESH` and `RUN_TZ`. In Actions, **Four-domain daily** accepts the optional inputs `date` and `domains`. Select `reuse_snapshot` with a date to re-evaluate the saved arXiv and HF inputs. By default a dated replay refreshes arXiv and publishes to the same index as a scheduled run. [Daily workflow](.github/workflows/four-domain.yml)

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

To measure the new recommender, label sampled pairs as JSON objects in an array with `date`, `arxiv_id`, `domain`, boolean `relevant` and boolean `recommend`. Run `python pipeline/evaluate_editions.py labels.json tmp/edition-state/runs/*.json` with one complete manifest for each date. Use `--grid` on development dates only. Report precision, recall and denominators on untouched dates; include rejected candidates in sampling. Legacy gold regression results measure the legacy selector only. With configured scoring credentials run `python pipeline/check_edition_seeds.py` to check four real papers against the new domain scopes.

## Vercel Deployment

Create a Vercel project with root directory set to `web/`. The site needs no backend API. Generated JSON is committed under `web/public/data`; figure URLs are absolute Vercel Blob URLs by default.

Create a public Vercel Blob store and copy its `BLOB_READ_WRITE_TOKEN` into GitHub Actions secrets. The Python pipeline uploads figures through Vercel Blob's HTTP API. If you set `STORAGE_BACKEND=repo`, figures are written to `web/public/figures` instead, which is useful for local/offline debugging but not recommended for daily production use.

## Notes

- Local v2 replays can reuse complete raw category files for the same query window. Scheduled v2 runs refresh arXiv. Across Actions runs the encrypted v2 checkpoint restores normalized source snapshots, screening and review decisions, and asset metadata.
- Requests are sequential and start at least 3.1 seconds apart. HTTP 429/5xx responses, timeouts, connection errors, and malformed XML are retried with minute-scale bounded backoff. If the fetch still fails, the whole job exits non-zero before domain processing, so incomplete data is never committed. An empty individual category is valid when the daily response contains papers elsewhere; an all-category empty response is treated as unreliable and is neither published nor cached.
- DocLayout-YOLO is AGPL-3.0. This project uses it in an offline CI batch pipeline to generate static images. The Vercel frontend does not serve the model or expose model inference. Re-check licensing before closed-source or commercial use of the pipeline code.
- `tmp/` and model caches are intentionally ignored. Legacy phase intermediates under `reports/*/*/tmp/` are kept during runs for re-runs and debugging but should not be committed.
- Blob cleanup is available through `FigureStorage.delete_older_than(days)`, which lists blobs under the configured prefix and deletes older URLs through the Vercel Blob HTTP API.

## Conference library

Open **顶会论文** on the homepage to browse reviewed proceedings by venue, year, research domain and track. The separate library at `/conferences` covers NeurIPS, ICLR, ICML, ACL, EMNLP, NAACL, SIGIR and RecSys, starting in 2025. Acceptance is verified against official volumes or accepted-paper lists. Findings and Industry have their own labels. Each paper uses the daily relevance and evidence rubric, receives one domain and one score, and links to its official record. A paper can appear in both channels when independently eligible.

The existing scheduled job syncs conference changes after publishing the daily edition. In **Four-domain daily → Run workflow**, select `conferences_only` to advance the backfill without changing the daily index. Optionally choose a venue and year. The library shows processed/total, accepted and missing-abstract counts per edition. A bounded run can finish with a partial backfill; subsequent runs resume from the encrypted checkpoint. Unavailable catalogues are retried on future runs.

```bash
python pipeline/sync_conferences.py --venue EMNLP --year 2025 --batch 32
```

For an isolated replay, specify both `--state tmp/conf-test/state` and `--output tmp/conf-test/public`. Official source availability, limited publisher abstracts and PDF access can delay individual records.
