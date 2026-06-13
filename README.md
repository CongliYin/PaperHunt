# Paper Hunt

Paper Hunt ranks recent arXiv papers for configured research domains and serves a static website with Chinese summaries, LLM assessments, and key figures.

## Architecture

- `pipeline/`: Python pipeline. It fetches arXiv papers, filters by domain keywords, enriches metadata, scores candidates, calls an OpenAI-compatible LLM, translates summaries to Chinese, extracts figures, and emits JSON.
- `web/`: Next.js App Router frontend. It reads static JSON from `web/public/data` and renders the list/detail pages.
- `.github/workflows/daily.yml`: daily GitHub Actions workflow. It runs the pipeline at `0 20 * * *` UTC, uploads images to Vercel Blob by default, commits JSON, and lets Vercel redeploy the `web/` project.

## Environment

Required GitHub Actions secrets:

| Name | Purpose |
| --- | --- |
| `LLM_BASE_URL` | OpenAI-compatible base URL, without trailing `/chat/completions` |
| `LLM_API_KEY` | LLM API key |
| `LLM_MODEL_SCORING` | model used for five-dimension paper scoring |
| `LLM_MODEL_TRANSLATION` | model used for Chinese summaries |
| `BLOB_READ_WRITE_TOKEN` | Vercel Blob token for figure uploads |

Non-secret runtime env:

| Name | Default | Purpose |
| --- | --- | --- |
| `RUN_TZ` | `Asia/Tokyo` | timezone used to define "yesterday" |
| `FIGURE_BACKEND` | `yolo` in CI | `yolo` or `pymupdf` |
| `STORAGE_BACKEND` | `blob` | `blob` or `repo` |

## Local Usage

Install pipeline dependencies:

```bash
pip install -r pipeline/requirements.txt
```

Run one domain for one day:

```bash
STORAGE_BACKEND=repo FIGURE_BACKEND=pymupdf \
python pipeline/run_daily.py --date 2026-06-12 --domains 3d-vision
```

For a quick phase-1-only smoke test without LLM calls:

```bash
python pipeline/run_daily.py --date 2026-06-12 --domains 3d-vision --skip-llm --limit 20
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

`run_daily.py` automatically discovers all directories under `pipeline/domains/` except names starting with `_` or `.`.

## Vercel Deployment

Create a Vercel project with root directory set to `web/`. The site needs no backend API. Generated JSON is committed under `web/public/data`; figure URLs are absolute Vercel Blob URLs by default.

Create a public Vercel Blob store and copy its `BLOB_READ_WRITE_TOKEN` into GitHub Actions secrets. The Python pipeline uploads figures through Vercel Blob's HTTP API. If you set `STORAGE_BACKEND=repo`, figures are written to `web/public/figures` instead, which is useful for local/offline debugging but not recommended for daily production use.

## Notes

- arXiv fetches are rate-limited and use retries where practical. Weekend/holiday runs may produce zero papers.
- DocLayout-YOLO is AGPL-3.0. This project uses it in an offline CI batch pipeline to generate static images. The Vercel frontend does not serve the model or expose model inference. Re-check licensing before closed-source or commercial use of the pipeline code.
- `tmp/` and model caches are intentionally ignored. Phase intermediates under `reports/*/*/tmp/` are kept during runs for re-runs and debugging but should not be committed.
- Blob cleanup is available through `FigureStorage.delete_older_than(days)`, which lists blobs under the configured prefix and deletes older URLs through the Vercel Blob HTTP API.
