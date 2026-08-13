from __future__ import annotations

import unittest

import requests

from pipeline.lib.fetcher import (
    ArxivClient,
    ArxivFetchError,
    fetch_papers_by_date,
    fetch_papers_by_date_multi_category,
)


EMPTY_FEED = b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'
ONE_PAPER_FEED = b'''<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>https://arxiv.org/abs/2608.00001v2</id>
    <title>Reliable Agents</title>
    <summary>A test paper.</summary>
    <published>2026-08-05T12:00:00Z</published>
    <author><name>Ada Lovelace</name></author>
    <arxiv:primary_category term="cs.AI" />
    <category term="cs.AI" />
    <category term="cs.CL" />
  </entry>
</feed>'''


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        content: bytes = EMPTY_FEED,
        *,
        headers: dict[str, str] | None = None,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self.text = text


class FakeSession:
    def __init__(self, outcomes: list[object], clock: FakeClock) -> None:
        self.outcomes = list(outcomes)
        self.clock = clock
        self.started_at: list[float] = []
        self.calls: list[dict] = []

    def get(self, url: str, **kwargs):
        self.started_at.append(self.clock.monotonic())
        self.calls.append({"url": url, **kwargs})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def make_client(outcomes: list[object], *, max_attempts: int = 4):
    clock = FakeClock()
    session = FakeSession(outcomes, clock)
    client = ArxivClient(
        session=session,
        min_interval_seconds=3.1,
        max_attempts=max_attempts,
        timeout_seconds=60,
        user_agent="PaperHunt-Test/1.0",
        rate_limit_backoff_seconds=60,
        transient_backoff_seconds=30,
        max_retry_delay_seconds=900,
        retry_jitter_seconds=0,
        clock=clock.monotonic,
        sleep=clock.sleep,
    )
    return client, session, clock


class ArxivClientTests(unittest.TestCase):
    def test_request_interval_cannot_be_lowered_below_safety_floor(self) -> None:
        clock = FakeClock()
        session = FakeSession([FakeResponse(200), FakeResponse(200)], clock)
        client = ArxivClient(
            session=session,
            min_interval_seconds=0,
            max_attempts=1,
            clock=clock.monotonic,
            sleep=clock.sleep,
        )

        client.fetch_feed(params={}, category="cs.AI", offset=0, verbose=False)
        client.fetch_feed(params={}, category="cs.CL", offset=0, verbose=False)

        self.assertEqual(session.started_at, [0.0, 3.1])

    def test_request_starts_are_spaced_across_categories(self) -> None:
        client, session, clock = make_client([FakeResponse(200), FakeResponse(200)])

        for category in ("cs.AI", "cs.CL"):
            client.fetch_feed(params={}, category=category, offset=0, verbose=False)

        self.assertEqual(session.started_at, [0.0, 3.1])
        self.assertEqual(clock.sleeps, [3.1])
        self.assertEqual(session.calls[0]["headers"]["User-Agent"], "PaperHunt-Test/1.0")

    def test_429_respects_numeric_retry_after(self) -> None:
        client, session, clock = make_client(
            [FakeResponse(429, headers={"Retry-After": "7"}), FakeResponse(200)]
        )

        client.fetch_feed(params={}, category="cs.AI", offset=0, verbose=False)

        self.assertEqual(len(session.calls), 2)
        self.assertEqual(clock.sleeps, [60.0])

    def test_429_retry_after_can_raise_but_not_lower_safety_backoff(self) -> None:
        client, _, clock = make_client(
            [FakeResponse(429, headers={"Retry-After": "180"}), FakeResponse(200)]
        )

        client.fetch_feed(params={}, category="cs.AI", offset=0, verbose=False)

        self.assertEqual(clock.sleeps, [180.0])

    def test_zero_retry_after_does_not_bypass_transient_safety_backoff(self) -> None:
        client, _, clock = make_client(
            [FakeResponse(503, headers={"Retry-After": "0"}), FakeResponse(200)]
        )

        client.fetch_feed(params={}, category="cs.AI", offset=0, verbose=False)

        self.assertEqual(clock.sleeps, [30.0])

    def test_429_uses_bounded_exponential_backoff(self) -> None:
        client, session, clock = make_client([FakeResponse(429)] * 4)

        with self.assertRaisesRegex(ArxivFetchError, "failed after 4 attempts: HTTP 429"):
            client.fetch_feed(params={}, category="cs.AI", offset=0, verbose=False)

        self.assertEqual(len(session.calls), 4)
        self.assertEqual(clock.sleeps, [60.0, 120.0, 240.0])

    def test_timeout_exhaustion_is_fatal(self) -> None:
        client, session, clock = make_client([requests.Timeout("slow")] * 4)

        with self.assertRaisesRegex(ArxivFetchError, "Timeout: slow"):
            client.fetch_feed(params={}, category="cs.AI", offset=0, verbose=False)

        self.assertEqual(len(session.calls), 4)
        self.assertEqual(clock.sleeps, [30.0, 60.0, 120.0])

    def test_non_retryable_http_status_fails_immediately(self) -> None:
        client, session, clock = make_client([FakeResponse(400, text="bad query")])

        with self.assertRaisesRegex(ArxivFetchError, "non-retryable HTTP 400: bad query"):
            client.fetch_feed(params={}, category="cs.AI", offset=0, verbose=False)

        self.assertEqual(len(session.calls), 1)
        self.assertEqual(clock.sleeps, [])

    def test_malformed_xml_is_retried(self) -> None:
        client, session, clock = make_client(
            [FakeResponse(200, b"not xml"), FakeResponse(200, ONE_PAPER_FEED)]
        )

        root = client.fetch_feed(params={}, category="cs.AI", offset=0, verbose=False)

        self.assertTrue(root.tag.endswith("feed"))
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(clock.sleeps, [30.0])

    def test_non_atom_success_response_is_retried(self) -> None:
        client, session, clock = make_client(
            [FakeResponse(200, b"<html><body>proxy error</body></html>"), FakeResponse(200)]
        )

        client.fetch_feed(params={}, category="cs.AI", offset=0, verbose=False)

        self.assertEqual(len(session.calls), 2)
        self.assertEqual(clock.sleeps, [30.0])

    def test_valid_empty_feed_is_a_successful_zero_paper_result(self) -> None:
        client, _, _ = make_client([FakeResponse(200, EMPTY_FEED)])

        papers = fetch_papers_by_date(
            "2026-08-05",
            category="cs.AI",
            client=client,
            verbose=False,
        )

        self.assertEqual(papers, [])

    def test_multi_category_fetch_uses_one_or_query_and_deduplicates_categories(self) -> None:
        client, session, _ = make_client([FakeResponse(200, ONE_PAPER_FEED)])

        papers = fetch_papers_by_date_multi_category(
            "2026-08-05",
            categories=["cs.CL", "cs.AI", "cs.CL"],
            client=client,
            verbose=False,
        )

        self.assertEqual(len(session.calls), 1)
        self.assertEqual([item["arxiv_id"] for item in papers], ["2608.00001"])
        self.assertEqual(
            session.calls[0]["params"]["search_query"],
            "(cat:cs.AI OR cat:cs.CL) AND "
            "submittedDate:[202608050000 TO 202608060000]",
        )


if __name__ == "__main__":
    unittest.main()
