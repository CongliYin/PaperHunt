"""从 arXiv 官方 API 按日期范围拉取 cs.CV 论文。

使用 arXiv 的 Atom API（无需 Python `arxiv` 包，避免依赖问题）。
查询语法：cat:cs.CV AND submittedDate:[YYYYMMDDHHMM TO YYYYMMDDHHMM]
"""
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional, Sequence

import requests

ARXIV_API_BASE = "https://export.arxiv.org/api/query"
ARXIV_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
DEFAULT_REQUEST_INTERVAL_SECONDS = 3.1
DEFAULT_MAX_ATTEMPTS = 4
DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_USER_AGENT = "PaperHunt/1.0 (+https://github.com/CongliYin/PaperHunt)"

# Atom 命名空间
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}


class ArxivFetchError(RuntimeError):
    """Raised when a required arXiv request cannot be completed safely."""


class ArxivClient:
    """Sequential, rate-limited client for the legacy arXiv Atom API."""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        min_interval_seconds: float | None = None,
        max_attempts: int | None = None,
        timeout_seconds: int | None = None,
        user_agent: str | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.session = session or requests.Session()
        configured_interval = (
            float(os.getenv("ARXIV_REQUEST_INTERVAL_SECONDS", str(DEFAULT_REQUEST_INTERVAL_SECONDS)))
            if min_interval_seconds is None
            else float(min_interval_seconds)
        )
        if configured_interval < 0:
            raise ValueError("min_interval_seconds must be non-negative")
        self.min_interval_seconds = max(configured_interval, DEFAULT_REQUEST_INTERVAL_SECONDS)
        self.max_attempts = (
            int(os.getenv("ARXIV_MAX_ATTEMPTS", str(DEFAULT_MAX_ATTEMPTS)))
            if max_attempts is None
            else int(max_attempts)
        )
        self.timeout_seconds = (
            int(os.getenv("ARXIV_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)))
            if timeout_seconds is None
            else int(timeout_seconds)
        )
        self.user_agent = user_agent or os.getenv("ARXIV_USER_AGENT") or DEFAULT_USER_AGENT
        self._clock = clock
        self._sleep = sleep
        self._last_request_started_at: float | None = None

        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.timeout_seconds < 1:
            raise ValueError("timeout_seconds must be at least 1")

    def fetch_feed(
        self,
        *,
        params: dict,
        category: str,
        offset: int,
        verbose: bool = True,
    ) -> ET.Element:
        """Fetch and parse one Atom page, retrying only transient failures."""
        last_reason = "unknown error"

        for attempt in range(1, self.max_attempts + 1):
            self._wait_for_request_slot()
            if verbose:
                print(
                    f"  [arxiv] fetching category={category} offset={offset} "
                    f"attempt={attempt}/{self.max_attempts}..."
                )

            response = None
            status_code: int | None = None
            try:
                response = self.session.get(
                    ARXIV_API_BASE,
                    params=params,
                    headers={"User-Agent": self.user_agent},
                    timeout=self.timeout_seconds,
                )
                status_code = int(response.status_code)
            except requests.RequestException as exc:
                last_reason = f"{type(exc).__name__}: {exc}"
            else:
                if status_code == 200:
                    try:
                        root = ET.fromstring(response.content)
                    except ET.ParseError as exc:
                        last_reason = f"malformed Atom XML: {exc}"
                    else:
                        expected_root = f"{{{NS['atom']}}}feed"
                        if root.tag != expected_root:
                            last_reason = f"unexpected XML root: {root.tag}"
                        else:
                            if verbose and attempt > 1:
                                print(
                                    f"  [arxiv] recovered category={category} offset={offset} "
                                    f"on attempt={attempt}/{self.max_attempts}"
                                )
                            return root
                elif status_code in ARXIV_RETRYABLE_STATUS_CODES:
                    last_reason = f"HTTP {status_code}"
                else:
                    detail = _response_detail(response)
                    raise ArxivFetchError(
                        f"arXiv category={category} offset={offset} failed with "
                        f"non-retryable HTTP {status_code}{detail}"
                    )

            if attempt >= self.max_attempts:
                raise ArxivFetchError(
                    f"arXiv category={category} offset={offset} failed after "
                    f"{self.max_attempts} attempts: {last_reason}"
                )

            delay = self._retry_delay(response, status_code, attempt)
            if verbose:
                print(
                    f"  [arxiv] retry category={category} offset={offset} "
                    f"after {last_reason}; waiting {delay:.1f}s"
                )
            self._sleep(delay)

        raise AssertionError("unreachable")

    def _wait_for_request_slot(self) -> None:
        now = self._clock()
        if self._last_request_started_at is not None:
            remaining = self.min_interval_seconds - (now - self._last_request_started_at)
            if remaining > 0:
                self._sleep(remaining)
                now = self._clock()
        self._last_request_started_at = now

    @staticmethod
    def _retry_delay(response, status_code: int | None, attempt: int) -> float:
        if response is not None:
            raw_retry_after = (getattr(response, "headers", {}) or {}).get("Retry-After")
            if raw_retry_after:
                try:
                    return min(max(float(raw_retry_after), 0.0), 300.0)
                except (TypeError, ValueError):
                    pass

        base = 10.0 if status_code == 429 else 5.0
        return min(base * (2 ** (attempt - 1)), 300.0)


def _response_detail(response) -> str:
    text = str(getattr(response, "text", "") or "").strip().replace("\n", " ")
    return f": {text[:200]}" if text else ""


def _parse_entry(entry: ET.Element) -> dict:
    """解析单个 Atom entry 元素为标准化的 paper dict。"""
    def _text(el, tag, ns="atom"):
        node = el.find(f"{ns}:{tag}", NS)
        return (node.text or "").strip() if node is not None and node.text else ""

    # arxiv id：从 <id> 中取，形如 http://arxiv.org/abs/2604.12345v1
    id_url = _text(entry, "id")
    arxiv_id_match = re.search(r"abs/([^/]+?)(v\d+)?$", id_url)
    arxiv_id = arxiv_id_match.group(1) if arxiv_id_match else id_url

    title = _text(entry, "title").replace("\n", " ").strip()
    title = re.sub(r"\s+", " ", title)

    abstract = _text(entry, "summary").strip()
    abstract = re.sub(r"\s+", " ", abstract)

    published = _text(entry, "published")  # ISO 8601

    # 作者
    authors = []
    author_affiliations = []
    for author_el in entry.findall("atom:author", NS):
        name_el = author_el.find("atom:name", NS)
        if name_el is not None and name_el.text:
            name = name_el.text.strip()
            authors.append(name)
            affiliations = [
                (node.text or "").strip()
                for node in author_el.findall("arxiv:affiliation", NS)
                if node is not None and node.text and node.text.strip()
            ]
            author_affiliations.append({"name": name, "affiliations": affiliations})

    # comments（arxiv 命名空间）
    comments_el = entry.find("arxiv:comment", NS)
    comments = (comments_el.text or "").strip() if comments_el is not None and comments_el.text else ""
    comments = re.sub(r"\s+", " ", comments)

    # primary category
    primary_cat_el = entry.find("arxiv:primary_category", NS)
    primary_category = (
        primary_cat_el.attrib.get("term", "") if primary_cat_el is not None else ""
    )

    # 所有 categories
    categories = [
        c.attrib.get("term", "") for c in entry.findall("atom:category", NS)
    ]

    # abs page URL
    abs_url = ""
    for link in entry.findall("atom:link", NS):
        if link.attrib.get("rel") == "alternate" and link.attrib.get("type") == "text/html":
            abs_url = link.attrib.get("href", "")
            break
    if not abs_url:
        abs_url = f"https://arxiv.org/abs/{arxiv_id}"

    return {
        "arxiv_id": arxiv_id,
        "title": title,
        "abstract": abstract,
        "authors": authors,
        "author_affiliations": author_affiliations,
        "comments": comments,
        "primary_category": primary_category,
        "categories": categories,
        "published_at": published,
        "abs_url": abs_url,
    }


def fetch_papers_by_date(
    start_date: str,
    end_date: Optional[str] = None,
    *,
    category: str = "cs.CV",
    max_results_per_page: int = 200,
    hard_limit: Optional[int] = None,
    sleep_between_pages: float = 3.0,
    verbose: bool = True,
    client: ArxivClient | None = None,
) -> List[dict]:
    """按日期范围拉取 arXiv 论文（基于 submittedDate）。

    Args:
        start_date: "YYYY-MM-DD"，UTC 起始（含 00:00:00）
        end_date:   "YYYY-MM-DD"，UTC 结束（含整个当天 23:59:59）。
                    None 表示与 start_date 相同（处理单日）。
        category:   arXiv 主分类，默认 cs.CV
        max_results_per_page: 单次 API 请求最多返回的条目数（arXiv 上限 2000，但建议 200 较稳）
        hard_limit: 总数上限（用于调试），None 表示不限
        sleep_between_pages: 兼容参数；新客户端会取它与 3.1 秒中的较大值
        client: 可复用的严格限速客户端；多分类抓取必须共享同一实例

    Returns:
        论文 dict 列表，按 submittedDate 升序。
    """
    client = client or ArxivClient(
        min_interval_seconds=max(float(sleep_between_pages), DEFAULT_REQUEST_INTERVAL_SECONDS)
    )

    # 解析日期
    start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if end_date is None:
        end_dt = start_dt + timedelta(days=1)
    else:
        end_dt = (
            datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            + timedelta(days=1)
        )

    start_str = start_dt.strftime("%Y%m%d%H%M")
    end_str = end_dt.strftime("%Y%m%d%H%M")

    search_query = (
        f"cat:{category} AND submittedDate:[{start_str} TO {end_str}]"
    )

    all_papers: List[dict] = []
    start_idx = 0

    while True:
        params = {
            "search_query": search_query,
            "start": start_idx,
            "max_results": max_results_per_page,
            "sortBy": "submittedDate",
            "sortOrder": "ascending",
        }

        root = client.fetch_feed(
            params=params,
            category=category,
            offset=start_idx,
            verbose=verbose,
        )

        entries = root.findall("atom:entry", NS)
        if not entries:
            if verbose:
                print(f"  [arxiv] no more entries.")
            break

        for entry in entries:
            paper = _parse_entry(entry)
            # 二次保险：如果 primary_category 不是目标 cat，可能是某些 entry 含跨类
            # 但 search_query 已经过滤过，这里不再剔除
            all_papers.append(paper)
            if hard_limit is not None and len(all_papers) >= hard_limit:
                if verbose:
                    print(f"  [arxiv] hit hard_limit={hard_limit}")
                return all_papers

        if len(entries) < max_results_per_page:
            # 已经是最后一页
            break

        start_idx += max_results_per_page

    if verbose:
        print(f"  [arxiv] total fetched: {len(all_papers)}")
    return all_papers


def fetch_papers_by_date_multi_category(
    start_date: str,
    end_date: Optional[str] = None,
    *,
    categories: Sequence[str],
    max_results_per_page: int = 200,
    hard_limit: Optional[int] = None,
    sleep_between_pages: float = 3.0,
    verbose: bool = True,
    client: ArxivClient | None = None,
) -> List[dict]:
    """Fetch papers for one or more arXiv categories and de-duplicate by arXiv id."""
    if not categories:
        categories = ["cs.CV"]

    client = client or ArxivClient(
        min_interval_seconds=max(float(sleep_between_pages), DEFAULT_REQUEST_INTERVAL_SECONDS)
    )

    by_id: dict[str, dict] = {}
    seen_categories: set[str] = set()
    for category in categories:
        category = str(category).strip()
        if not category or category in seen_categories:
            continue
        seen_categories.add(category)
        if verbose:
            print(f"  [arxiv] category={category}")
        remaining = None if hard_limit is None else max(hard_limit - len(by_id), 0)
        if remaining == 0:
            break
        papers = fetch_papers_by_date(
            start_date,
            end_date,
            category=category,
            max_results_per_page=max_results_per_page,
            hard_limit=remaining,
            sleep_between_pages=sleep_between_pages,
            verbose=verbose,
            client=client,
        )
        for paper in papers:
            arxiv_id = re.sub(r"v\d+$", "", paper.get("arxiv_id", ""))
            if arxiv_id and arxiv_id not in by_id:
                by_id[arxiv_id] = paper

    return sorted(by_id.values(), key=lambda p: p.get("published_at", ""))
