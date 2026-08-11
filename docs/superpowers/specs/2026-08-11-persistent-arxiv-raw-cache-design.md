# Persistent arXiv Raw Cache Design

Date: 2026-08-11

## Context

The daily pipeline currently builds one complete `tmp/arxiv-cache/<date>.json` bundle and shares it across domains. That removes duplicate requests inside one run, but GitHub-hosted runners are ephemeral, so a later run for the same date starts with no cache and queries every category again. This makes manual reruns vulnerable to the same arXiv 429 or 503 response even when an earlier run already fetched the required metadata successfully.

The cache must remain independent of PaperHunt's selection rules. Changes to keyword filters, inclusion and exclusion examples, primary-domain ownership, scoring weights, or LLM prompts must rerun selection against the same raw arXiv snapshot rather than force another network fetch.

## Goals

- Persist complete raw arXiv metadata across GitHub Actions runs.
- Store each date range and arXiv category independently.
- Reuse raw metadata when only downstream selection or ranking logic changes.
- Fetch only missing or invalid categories when a domain adds coverage.
- Invalidate a category when the raw cache schema or fetch protocol changes.
- Allow an explicit manual run to refresh every required category.
- Preserve the existing complete daily bundle interface consumed by phase one.
- Persist successfully completed categories even if a later category or pipeline stage fails.

## Non-goals

- Caching final domain selections, LLM scores, translations, figures, or published JSON.
- Mirroring every arXiv category; only the union required by selected PaperHunt domains is fetched.
- Replacing the legacy arXiv API or changing its rate-limit retry policy.
- Treating an incomplete category response as usable data.

## Considered Approaches

### 1. Per-category persistent raw cache plus runtime bundle (selected)

Each successfully fetched category is written atomically beneath a versioned raw-cache directory. The orchestrator assembles the required category files into the existing daily bundle before starting domain processing. GitHub Actions restores the raw-cache directory at job start and saves it under a unique cache key at job end, including after a pipeline failure.

This isolates invalidation and allows an added category to be fetched without refetching existing categories. It also keeps `rank_pipeline.py` unchanged.

### 2. One persistent bundle keyed only by date

This is simpler, but adding a category makes the bundle incomplete and either fails the run or forces every category to be fetched again. A date-only key also fails to represent fetch-protocol changes safely.

### 3. Commit raw metadata to the repository or blob storage

This provides durable history but adds repository churn or another storage dependency and credential path. GitHub Actions cache is sufficient for short-lived rerun reuse and can be introduced without changing the published data contract.

## Cache Layout and Contract

The persistent cache root defaults to `tmp/arxiv-raw`. A category is stored at:

```text
tmp/arxiv-raw/<fetch-profile>/<start-date>__<end-date>/<category>.json
```

For a single-day run, an example is:

```text
tmp/arxiv-raw/legacy-submitted-date-v1/2026-08-10__2026-08-10/cs.AI.json
```

Each category file has this shape:

```json
{
  "schema_version": 1,
  "fetch_profile": "legacy-submitted-date-v1",
  "query_fingerprint": "<sha256>",
  "start_date": "2026-08-10",
  "end_date": "2026-08-10",
  "category": "cs.AI",
  "complete": true,
  "generated_at": "2026-08-11T01:00:00Z",
  "papers": []
}
```

The fingerprint covers the source endpoint, date field, page size, ordering, and parser/fetch profile. Selection policies are intentionally excluded. A file is reusable only when its schema, profile, fingerprint, dates, category, completeness marker, and paper list validate.

Category files are written through a sibling temporary file and renamed only after the full paginated fetch succeeds. A failed page therefore cannot publish a partial category. Categories completed before a later failure remain valid and can be reused by the next run.

After all required categories are available, the orchestrator writes the existing `tmp/arxiv-cache/<date>.json` bundle atomically. Domain phase-one processes continue to receive this bundle through `--arxiv-cache`.

## Invalidation Rules

- Keyword, sample, ownership, ranking, threshold, or prompt changes: reuse raw category files and rerun all downstream processing.
- Added category: fetch only the missing category.
- Removed category: ignore its retained raw file.
- Date-range change: use a different date-range directory.
- Fetch profile, page size, query semantics, or parsed metadata change: change the fingerprint/profile and refetch affected categories.
- Explicit `--refresh-arxiv`: bypass reusable files for all required categories and atomically replace each successful fetch.

Malformed or stale raw files are cache misses, not fatal configuration errors. The pipeline attempts a clean fetch; if that fetch fails, the daily run remains fatal as before.

## Workflow Integration

The workflow will restore `tmp/arxiv-raw` before running tests and the daily pipeline. Every run uses a unique save key and a stable restore prefix so the newest available cache becomes the base for the next run. A final cache-save step runs with `if: always()` so categories completed before an arXiv, LLM, or output failure are not discarded.

`workflow_dispatch` gains a boolean `refresh_arxiv` input. When true, `run_daily.py` receives `--refresh-arxiv`; scheduled runs and ordinary manual reruns reuse valid raw files.

The cache contains public arXiv metadata only. It contains no API keys, model outputs, private data, or credentials.

## Error Semantics

- Valid category hit: no arXiv request for that category.
- Missing, stale, or malformed category file: fetch and replace it atomically.
- Successful empty Atom feed: cache a complete empty `papers` list.
- Category fetch failure: do not replace that category file and do not create the daily bundle.
- Later pipeline failure: retain and save all already complete raw category files.
- Forced refresh failure: fail the run; never present an incomplete refreshed category as complete.

## Testing

Unit tests will verify:

- raw files are created once per unique category;
- a second build uses raw files without network calls;
- adding one category fetches only that category;
- a stale fingerprint refetches only the affected category;
- forced refresh refetches every required category;
- a failure leaves no daily bundle but preserves earlier complete category files;
- malformed category files are repaired by refetching;
- selected categories still assemble into a valid daily bundle and de-duplicate downstream papers;
- the orchestrator forwards the refresh option and raw-cache directory correctly.

The complete unit suite and selection-quality evaluation must pass before push.

## Success Criteria

- An ordinary same-date rerun with unchanged fetch scope makes zero arXiv metadata requests.
- Adding one category makes requests only for that category.
- Changing PaperHunt selection logic changes results without invalidating raw metadata.
- A query/profile change or explicit refresh cannot silently reuse an incompatible category file.
- A failed category never produces a complete daily bundle.
- GitHub Actions saves complete category files even when the pipeline later exits non-zero.
