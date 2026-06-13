"""从 arXiv 官方 API 按日期范围拉取 cs.CV 论文。

使用 arXiv 的 Atom API（无需 Python `arxiv` 包，避免依赖问题）。
查询语法：cat:cs.CV AND submittedDate:[YYYYMMDDHHMM TO YYYYMMDDHHMM]
"""
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Sequence

import requests

ARXIV_API_BASE = "https://arxiv.org/api/query"

# Atom 命名空间
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}


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
    for author_el in entry.findall("atom:author", NS):
        name_el = author_el.find("atom:name", NS)
        if name_el is not None and name_el.text:
            authors.append(name_el.text.strip())

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
) -> List[dict]:
    """按日期范围拉取 arXiv 论文（基于 submittedDate）。

    Args:
        start_date: "YYYY-MM-DD"，UTC 起始（含 00:00:00）
        end_date:   "YYYY-MM-DD"，UTC 结束（含整个当天 23:59:59）。
                    None 表示与 start_date 相同（处理单日）。
        category:   arXiv 主分类，默认 cs.CV
        max_results_per_page: 单次 API 请求最多返回的条目数（arXiv 上限 2000，但建议 200 较稳）
        hard_limit: 总数上限（用于调试），None 表示不限
        sleep_between_pages: 翻页间 sleep 秒数，遵守 arXiv API 礼仪

    Returns:
        论文 dict 列表，按 submittedDate 升序。
    """
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

        if verbose:
            print(f"  [arxiv] fetching offset={start_idx}...")

        try:
            resp = requests.get(ARXIV_API_BASE, params=params, timeout=60)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"  [arxiv] ERROR: {e}")
            break

        # 解析 XML
        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as e:
            print(f"  [arxiv] XML parse error: {e}")
            break

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
        time.sleep(sleep_between_pages)

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
) -> List[dict]:
    """Fetch papers for one or more arXiv categories and de-duplicate by arXiv id."""
    if not categories:
        categories = ["cs.CV"]

    by_id: dict[str, dict] = {}
    for category in categories:
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
        )
        for paper in papers:
            arxiv_id = re.sub(r"v\d+$", "", paper.get("arxiv_id", ""))
            if arxiv_id and arxiv_id not in by_id:
                by_id[arxiv_id] = paper

    return sorted(by_id.values(), key=lambda p: p.get("published_at", ""))
