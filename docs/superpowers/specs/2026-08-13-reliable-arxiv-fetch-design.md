# Reliable arXiv Fetch Design

## Goal

Make scheduled and manual paper collection reliable when arXiv throttles GitHub-hosted runners, while preserving reusable per-date, per-category raw caches.

## Selected approach

Fetch all missing categories with one OR query instead of issuing one query per category. Parse the combined Atom feed once, de-duplicate papers by arXiv ID, and partition the result locally into the existing per-category cache files. Existing valid per-category cache files remain compatible and are reused.

## Retry behavior

- Keep requests sequential and at least 3.1 seconds apart.
- Use six attempts by default and a 120-second request timeout.
- For HTTP 429, wait at least 60, 120, 240, 480, and 900 seconds.
- For HTTP 5xx, timeouts, connection failures, or malformed responses, wait at least 30, 60, 120, 240, and 480 seconds.
- Apply small random jitter in production to prevent synchronized retries from GitHub runners.
- Treat `Retry-After` as an additional lower bound. A zero or undersized value must not bypass the client safety floor.
- Expose retry settings through environment variables so tests and operations can tune them without code changes.

## Empty-result protection

An empty result for one category can be valid. An empty result across every required category is treated as "source data not ready or unreliable":

- do not publish the daily bundle;
- do not write new empty raw cache files;
- raise a clear error so a later run retries arXiv;
- if an older run already stored all-empty raw caches, ignore them as a completed snapshot and refetch.

If at least one category has papers, empty categories are valid and are cached normally.

## Compatibility

- Explicit `--date` behavior and the current two-day automatic offset remain unchanged.
- The bundle schema and per-category cache paths remain unchanged.
- Domain selection, LLM scoring, output JSON, and frontend behavior remain unchanged.
- Direct multi-category fetching used outside the daily cache also switches to one combined query.

## Verification

Unit tests cover combined query construction, de-duplication, long retry floors, `Retry-After: 0`, timeout backoff, cache reuse, partitioning, stale all-empty cache recovery, and rejection of newly fetched all-empty results. The complete test suite and historical selection-quality evaluation must pass before push.
