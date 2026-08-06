# Paper Hunt

Paper Hunt ranks recent arXiv papers for configured research domains and serves a static website with Chinese summaries, LLM assessments, and key figures.

## Architecture

- `pipeline/`: Python pipeline. It fetches arXiv papers, assigns one deterministic primary domain, enriches and scores candidates, applies an LLM domain-fit gate, translates summaries to Chinese, extracts figures, and emits JSON.
- `web/`: Next.js App Router frontend. It reads static JSON from `web/public/data` and renders the list/detail pages.
- `.github/workflows/daily.yml`: daily GitHub Actions workflow. It runs the pipeline at `0 20 * * *` UTC, uploads images to Vercel Blob by default, commits JSON, and lets Vercel redeploy the `web/` project.

## Environment

Required GitHub Actions secrets:

| Name | Purpose |
| --- | --- |
| `LLM_BASE_URL` | OpenAI-compatible base URL, without trailing `/chat/completions` |
| `LLM_API_KEY` | LLM API key |
| `LLM_MODEL_SCORING` | model used for domain-fit classification and five-dimension paper scoring |
| `LLM_MODEL_TRANSLATION` | model used for Chinese summaries |
| `BLOB_READ_WRITE_TOKEN` | Vercel Blob token for figure uploads |

Non-secret runtime env:

| Name | Default | Purpose |
| --- | --- | --- |
| `RUN_TZ` | `Asia/Tokyo` | timezone used to define "yesterday" |
| `FIGURE_BACKEND` | `yolo` in CI | `yolo` or `pymupdf` |
| `FIGURE_MAX_COUNT` | `4` (`2` in CI) | max detail figures per paper; lower values reduce Blob advanced operations |
| `STORAGE_BACKEND` | `blob` | `blob` or `repo` |
| `ARXIV_REQUEST_INTERVAL_SECONDS` | `3.1` | minimum interval between arXiv request starts |
| `ARXIV_MAX_ATTEMPTS` | `4` | maximum attempts for transient arXiv failures |
| `ARXIV_TIMEOUT_SECONDS` | `60` | timeout for each arXiv request |
| `ARXIV_USER_AGENT` | PaperHunt repository URL | identifiable user agent sent to arXiv |

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

Every domain must define `selection_policy.yaml`. A paper qualifies through either a high-precision standalone phrase or all configured contextual signal groups, unless an exclusion matches. The selector compares every qualifying policy and assigns exactly one primary domain. The LLM then independently scores `domain_fit`; papers below the policy's `minimum_llm_domain_fit` are not published.

Run the offline selection regression before changing domain boundaries:

```bash
python pipeline/evaluate_selection_quality.py
```

The report compares the legacy filters and current selector on the user-approved gold set and checked-in historical output.

## Vercel Deployment

Create a Vercel project with root directory set to `web/`. The site needs no backend API. Generated JSON is committed under `web/public/data`; figure URLs are absolute Vercel Blob URLs by default.

Create a public Vercel Blob store and copy its `BLOB_READ_WRITE_TOKEN` into GitHub Actions secrets. The Python pipeline uploads figures through Vercel Blob's HTTP API. If you set `STORAGE_BACKEND=repo`, figures are written to `web/public/figures` instead, which is useful for local/offline debugging but not recommended for daily production use.

## Notes

- Each daily run fetches every unique arXiv category once into an atomic cache shared by all domains. Requests are sequential and start at least 3.1 seconds apart. HTTP 429/5xx responses, timeouts, connection errors, and malformed XML are retried with bounded backoff. If any required category still fails, the whole job exits non-zero before domain processing, so incomplete data is never committed. A valid HTTP 200 response with no entries remains a successful zero-paper day.
- DocLayout-YOLO is AGPL-3.0. This project uses it in an offline CI batch pipeline to generate static images. The Vercel frontend does not serve the model or expose model inference. Re-check licensing before closed-source or commercial use of the pipeline code.
- `tmp/` and model caches are intentionally ignored. Phase intermediates under `reports/*/*/tmp/` are kept during runs for re-runs and debugging but should not be committed.
- Blob cleanup is available through `FigureStorage.delete_older_than(days)`, which lists blobs under the configured prefix and deletes older URLs through the Vercel Blob HTTP API.
