# arXiv Fetch Reliability Design

Date: 2026-08-06

## Context

The daily workflow queries the legacy arXiv API independently for every domain and category. Shared categories such as `cs.AI` and `cs.CL` are fetched repeatedly, and the current implementation does not enforce arXiv's minimum three-second interval between every request. When arXiv returns HTTP 429 or a timeout, `fetch_papers_by_date` logs the exception, returns an empty list, and the orchestrator reports a successful "no papers" run. This produces green GitHub Actions runs with incomplete or missing data.

## Goals

- Run one fetch sequence per unique arXiv category per daily run, shared by every domain.
- Start arXiv requests at least 3.1 seconds apart, using one sequential connection path.
- Retry transient failures with bounded backoff and honor `Retry-After`.
- Fail the whole daily run if any required category cannot be fetched completely.
- Treat an empty successful Atom feed as a legitimate no-paper result.
- Ensure failed or partial fetches are never exposed as a complete cache and never reach LLM, figure, or commit stages.
- Add deterministic tests that do not call the live arXiv service.

## Non-goals

- Automating the historical July/August backfill.
- Migrating to OAI-PMH or another metadata provider.
- Parallel arXiv fetching; the legacy API requires a single connection path.
- Changing LLM scoring, translation, figure extraction, or ranking behavior.
- Allowing partial daily datasets when one category fails.

## Considered Approaches

### 1. Central daily prefetch bundle (selected)

`run_daily.py` gathers the union of categories required by the selected domains, fetches them sequentially once, writes a complete cache bundle atomically, and passes that bundle to every phase-one subprocess.

Advantages:

- One explicit place controls rate limiting and completeness.
- No cross-process locks or hidden coordination.
- A category failure occurs before any domain processing or generated output.
- Repeated categories are naturally reused.

Cost: `run_daily.py` and the phase-one CLI gain a small cache handoff interface.

### 2. Transparent fetcher cache with a cross-process lock

Each domain subprocess would keep the current fetch flow but coordinate through cache and timestamp files.

Advantages: fewer CLI changes.

Disadvantages: hidden shared state, POSIX locking, harder tests, and more failure modes around stale locks and partially written files.

### 3. Per-domain retry and delay only

Keep the existing architecture and add sleeps and retries inside each subprocess.

Advantages: smallest patch.

Disadvantages: shared categories are still queried repeatedly, the run is slower, and rate-limit pressure remains unnecessarily high.

## Architecture

### Retrying arXiv client

`pipeline/lib/fetcher.py` will expose an `ArxivFetchError` and use one reusable client for all requests in a prefetch operation. The client will:

- use a `requests.Session`;
- send an identifiable `User-Agent`, configurable through `ARXIV_USER_AGENT` and defaulting to the PaperHunt repository URL;
- enforce at least 3.1 seconds between request start times;
- make at most four attempts per page;
- retry HTTP 429, 500, 502, 503, and 504, connection errors, read timeouts, and malformed XML responses;
- honor a numeric `Retry-After` header when present;
- otherwise use bounded exponential delays: 10/20/40 seconds for 429 and 5/10/20 seconds for other transient failures;
- cap one retry delay at 300 seconds;
- immediately fail on non-retryable HTTP errors.

Clock and sleep functions, as well as the HTTP session, will be injectable so unit tests never wait or access the network.

### Daily cache bundle

A focused cache helper will write `tmp/arxiv-cache/<date>.json` with this versioned shape:

```json
{
  "schema_version": 1,
  "start_date": "2026-08-05",
  "end_date": "2026-08-05",
  "generated_at": "2026-08-06T02:00:00Z",
  "categories": {
    "cs.AI": [],
    "cs.CL": [
      {
        "arxiv_id": "2608.00001",
        "title": "Example paper"
      }
    ]
  }
}
```

The cache is valid only when its schema and date range match and it contains every required category. Empty category arrays are valid successful results. The file is written to a sibling temporary file and moved into place only after every category succeeds. An exception leaves no complete cache behind.

An already valid local cache may be reused for the same date and category set. GitHub-hosted runners remain fresh between jobs, so this primarily helps local reruns while still guaranteeing within-run reuse.

### Daily orchestration

Before starting domain subprocesses, `pipeline/run_daily.py` will:

1. Read each selected domain's `domain.yaml`.
2. Build a deterministic de-duplicated category list.
3. Build or load the complete daily arXiv cache.
4. Abort with exit code 1 if prefetch raises `ArxivFetchError` or cache validation fails.
5. Pass `--arxiv-cache <path>` to every phase-one subprocess.

No LLM, output generation, figure work, or Git commit step can run after a prefetch failure.

### Phase-one cache consumption

`pipeline/rank_pipeline.py` will accept optional `--arxiv-cache`. When present, phase one will load only the category lists configured for that domain and de-duplicate papers by normalized arXiv ID. A missing or invalid required category is fatal.

Direct `rank_pipeline.py --phase1-only` use without a cache remains supported and uses the same strict retrying client. That compatibility path makes one sequential multi-category fetch but does not provide cross-domain reuse.

## Error Semantics

- HTTP 200 with a well-formed Atom feed containing zero entries: success with zero papers.
- Retryable failure followed by success: continue and log the recovered attempt.
- Retry exhaustion for any page or category: raise `ArxivFetchError` and fail the entire daily run.
- Malformed cache, wrong date, or missing category: fail the entire daily run.
- No domain-filter matches after a complete fetch: successful no-paper domain result.
- Partial results accumulated before a later page failure are discarded and never cached.

Logs will identify the category, page offset, attempt number, failure type, retry delay, cache hit/miss, and final cache path without printing secrets.

## Testing

Tests will use the standard-library `unittest` framework and fake HTTP responses, clocks, and sleepers. Coverage will include:

- the 3.1-second minimum interval between request starts;
- `Retry-After` handling and exponential fallback for HTTP 429;
- retries for timeout, 5xx, and malformed XML;
- immediate failure for non-retryable HTTP responses;
- strict failure after retry exhaustion;
- successful empty feeds remaining distinguishable from request failures;
- atomic cache creation only after all categories succeed;
- cache validation and reuse;
- category de-duplication across domains;
- domain-specific cache selection and paper de-duplication;
- orchestration stopping before domain subprocesses after prefetch failure.

The daily workflow will run:

```bash
python -m unittest discover -s tests -p 'test_*.py'
```

after dependency installation and before the live pipeline.

## Rollout

1. Run the unit suite locally.
2. Run a phase-one smoke test against one recent date and verify request spacing in logs.
3. Manually dispatch one complete daily date and confirm that generated JSON is committed.
4. Backfill missing dates separately and sequentially after the production path is stable.

## Success Criteria

- No live run starts arXiv requests less than 3.1 seconds apart.
- A required category returning persistent 429 or timing out makes GitHub Actions red.
- A legitimate empty day remains green without generated paper data.
- Each unique category has one paginated fetch sequence per daily cache build, regardless of how many domains use it; extra requests occur only for pagination or retries.
- Tests reproduce the former false-success behavior and prove it is eliminated.
