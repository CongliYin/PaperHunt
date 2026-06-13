"""多源信息聚合：
- 从 HuggingFace Daily Papers 拉取热度信息
- 从 Semantic Scholar API 查询作者 h-index（带文件缓存，30 天有效）
- 从 comments 和 abstract 中正则提取 GitHub / project page / 代码承诺等链接
"""
import re
import time
from datetime import datetime, timedelta
from typing import List, Optional
from urllib.parse import quote

from .utils import safe_get, load_cache, save_cache


# ==================== HuggingFace Daily Papers ====================

HF_API_URL = "https://huggingface.co/api/daily_papers"


def fetch_hf_daily_papers(
    start_date: str,
    end_date: Optional[str] = None,
    *,
    verbose: bool = True,
) -> dict:
    """拉取日期范围内的 HF Daily Papers，构建 arxiv_id -> hf_info 索引。

    HF API 接口形如 https://huggingface.co/api/daily_papers?date=YYYY-MM-DD
    返回当天的 daily papers 列表。

    注意：HF Daily Papers 每天会从近期 arxiv 论文中精选一小部分（通常 10-30 篇），
    所以一篇昨天的论文可能要几天后才会上榜。我们把日期窗口适当扩大（向后 +5 天），
    抓取一段时间内的所有上榜论文，再用 arxiv_id 匹配。

    Returns:
        dict: {arxiv_id: {"upvotes": int, "title": str}, ...}
    """
    from datetime import datetime, timedelta

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    if end_date is None:
        end_dt = start_dt
    else:
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    # 把范围向后扩 5 天，捕捉延后上榜的情况
    fetch_start = start_dt
    fetch_end = end_dt + timedelta(days=5)

    # 但不能超过今天
    today = datetime.utcnow().date()
    if fetch_end.date() > today:
        fetch_end = datetime.combine(today, datetime.min.time())

    index: dict = {}

    cur = fetch_start
    while cur <= fetch_end:
        date_str = cur.strftime("%Y-%m-%d")
        if verbose:
            print(f"  [hf] fetching {date_str}...")

        data = safe_get(
            HF_API_URL,
            params={"date": date_str},
            timeout=15,
            sleep_after=0.5,
        )

        if isinstance(data, list):
            for item in data:
                # 数据结构：item 通常含 "paper" 子对象，里面有 "id"（arxiv id）和 "upvotes"
                paper_obj = item.get("paper") if isinstance(item, dict) else None
                if not paper_obj:
                    continue
                arxiv_id = paper_obj.get("id", "")
                if not arxiv_id:
                    continue
                # 标准化（去掉 v1/v2 后缀）
                arxiv_id_clean = re.sub(r"v\d+$", "", arxiv_id)
                upvotes = paper_obj.get("upvotes", 0) or 0
                title = paper_obj.get("title", "")

                # 如果一篇论文在多天上榜，取最大 upvotes
                if arxiv_id_clean in index:
                    if upvotes > index[arxiv_id_clean]["upvotes"]:
                        index[arxiv_id_clean]["upvotes"] = upvotes
                else:
                    index[arxiv_id_clean] = {
                        "upvotes": upvotes,
                        "title": title,
                        "first_seen_date": date_str,
                    }

        cur += timedelta(days=1)

    if verbose:
        print(f"  [hf] total HF Daily papers indexed: {len(index)}")
    return index


# ==================== Semantic Scholar ====================

S2_AUTHOR_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/author/search"
S2_CACHE_PATH = "cache/s2_authors.json"
S2_CACHE_TTL_DAYS = 30
S2_REQUEST_INTERVAL = 0.0  # 秒；短超时已足够保护报告生成速度


class AuthorMetricsCache:
    """作者 h-index 缓存（30 天 TTL）。"""

    def __init__(self, path: str = S2_CACHE_PATH):
        self.path = path
        self._data = load_cache(path)
        self._dirty = False

    def get(self, author_name: str) -> Optional[dict]:
        key = author_name.strip().lower()
        if key not in self._data:
            return None
        rec = self._data[key]
        # 检查 TTL
        cached_at = rec.get("cached_at")
        if not cached_at:
            return None
        try:
            cached_dt = datetime.fromisoformat(cached_at)
        except ValueError:
            return None
        if datetime.utcnow() - cached_dt > timedelta(days=S2_CACHE_TTL_DAYS):
            return None
        return rec.get("metrics")

    def set(self, author_name: str, metrics: dict) -> None:
        key = author_name.strip().lower()
        self._data[key] = {
            "metrics": metrics,
            "cached_at": datetime.utcnow().isoformat(),
        }
        self._dirty = True

    def flush(self) -> None:
        if self._dirty:
            save_cache(self.path, self._data)
            self._dirty = False


def fetch_author_metrics(author_name: str, cache: AuthorMetricsCache) -> dict:
    """查询单个作者的 h-index 与 citation 数。

    使用 Semantic Scholar Author Search API。匿名免 key，但有限流。
    返回 dict：{"h_index": int|None, "citation_count": int|None, "found": bool}
    失败时返回 {"found": False}。
    """
    cached = cache.get(author_name)
    if cached is not None:
        return cached

    # 调用 S2
    params = {
        "query": author_name,
        "limit": 1,
        "fields": "name,hIndex,citationCount,paperCount,affiliations",
    }
    data = safe_get(
        S2_AUTHOR_SEARCH_URL,
        params=params,
        timeout=1,
        max_retries=0,
        sleep_after=S2_REQUEST_INTERVAL,
    )

    if not data or not isinstance(data, dict):
        result = {"found": False}
        cache.set(author_name, result)
        return result

    items = data.get("data", [])
    if not items:
        result = {"found": False}
        cache.set(author_name, result)
        return result

    top = items[0]
    result = {
        "found": True,
        "name": top.get("name", ""),
        "h_index": top.get("hIndex"),
        "citation_count": top.get("citationCount"),
        "paper_count": top.get("paperCount"),
    }
    cache.set(author_name, result)
    return result


# ==================== 链接 / 代码承诺提取 ====================

GITHUB_RE = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",
    re.IGNORECASE,
)
PROJECT_PAGE_RE = re.compile(
    r"(?:https?://)?(?:[A-Za-z0-9_-]+\.)*(?:github\.io|gitlab\.io|netlify\.app|vercel\.app|pages\.dev)"
    r"(?:/[A-Za-z0-9_./?=&%-]*)?",
    re.IGNORECASE,
)
PROJECT_PAGE_HINT_RE = re.compile(
    r"\b(?:project[\s-]*page|project[\s-]*website|project[\s-]*site)\b\s*[:\-]?\s*"
    r"(https?://[^\s,;\)]+)",
    re.IGNORECASE,
)
CODE_PROMISE_RE = re.compile(
    r"(?:code\s+(?:will\s+be\s+|is\s+)?(?:released|available|public(?:ly)?\s+available)|"
    r"open[\s-]*sourc(?:ed?|ing)|"
    r"we\s+(?:will\s+)?release\s+(?:the\s+)?code|"
    r"source\s+code\s+(?:will\s+be\s+)?available)",
    re.IGNORECASE,
)
VIDEO_DEMO_RE = re.compile(
    r"\b(?:video|demo)\b",
    re.IGNORECASE,
)


def extract_links(comments: str, abstract: str) -> dict:
    """从 comments 和 abstract 末尾提取链接和承诺信息。

    Returns:
        {
            "github_url": str | None,
            "project_page_url": str | None,
            "code_promised": bool,
            "has_video_demo": bool,
        }
    """
    text = f"{comments or ''} \n {abstract or ''}"

    github_match = GITHUB_RE.search(text)
    github_url = None
    if github_match:
        url = github_match.group(0)
        if not url.startswith("http"):
            url = "https://" + url
        github_url = url

    # project page：先看 hint（"project page: xxx"），再看通用 .github.io 等
    project_page_url = None
    pp_hint_match = PROJECT_PAGE_HINT_RE.search(text)
    if pp_hint_match:
        project_page_url = pp_hint_match.group(1)
    else:
        pp_match = PROJECT_PAGE_RE.search(text)
        if pp_match:
            url = pp_match.group(0)
            if not url.startswith("http"):
                url = "https://" + url
            # 排除 GitHub README 中误认作 project page 的 github.com 链接（已被 GITHUB_RE 单独处理）
            project_page_url = url

    code_promised = bool(CODE_PROMISE_RE.search(text))
    has_video_demo = bool(VIDEO_DEMO_RE.search(comments or ""))

    return {
        "github_url": github_url,
        "project_page_url": project_page_url,
        "code_promised": code_promised,
        "has_video_demo": has_video_demo,
    }


# ==================== 总入口 ====================

def enrich_papers(
    papers: List[dict],
    *,
    hf_index: dict,
    cache: AuthorMetricsCache,
    verbose: bool = True,
) -> List[dict]:
    """给每篇论文附加 enrichment 信息。

    会修改 paper dict，添加 "enriched" 字段。
    """
    for i, paper in enumerate(papers):
        if verbose and (i % 10 == 0 or i == len(papers) - 1):
            print(f"  [enrich] {i+1}/{len(papers)}: {paper.get('arxiv_id', '?')}")

        enriched = {}

        # 1. 链接 / 代码承诺
        links = extract_links(paper.get("comments", ""), paper.get("abstract", ""))
        enriched.update(links)

        # 2. HF Daily Papers
        arxiv_id = paper.get("arxiv_id", "")
        # 标准化（去掉 vN 后缀）
        arxiv_id_clean = re.sub(r"v\d+$", "", arxiv_id)
        hf_info = hf_index.get(arxiv_id_clean)
        if hf_info:
            enriched["hf_listed"] = True
            enriched["hf_upvotes"] = hf_info.get("upvotes", 0)
        else:
            enriched["hf_listed"] = False
            enriched["hf_upvotes"] = 0

        # 3. 作者 metrics（首作者 + 末位作者）
        authors = paper.get("authors", [])
        first_author_metrics = None
        last_author_metrics = None

        if len(authors) >= 1:
            first_author_metrics = fetch_author_metrics(authors[0], cache)
        if len(authors) >= 2:
            last_author_metrics = fetch_author_metrics(authors[-1], cache)
        elif len(authors) == 1:
            last_author_metrics = first_author_metrics

        enriched["first_author_h_index"] = (
            first_author_metrics.get("h_index") if first_author_metrics else None
        )
        enriched["first_author_found"] = (
            first_author_metrics.get("found", False) if first_author_metrics else False
        )
        enriched["last_author_h_index"] = (
            last_author_metrics.get("h_index") if last_author_metrics else None
        )
        enriched["last_author_found"] = (
            last_author_metrics.get("found", False) if last_author_metrics else False
        )

        paper["enriched"] = enriched

    # 持久化缓存
    cache.flush()

    if verbose:
        n_hf = sum(1 for p in papers if p["enriched"].get("hf_listed"))
        n_github = sum(1 for p in papers if p["enriched"].get("github_url"))
        print(f"  [enrich] done. HF-listed={n_hf}, has-GitHub={n_github}")

    return papers
