"""Keyword-based paper filtering for a configured research domain.

判定规则：
1. 标题或摘要中命中至少一个 positive 关键词 → 进入候选；
2. 命中 hard_negative 中任一词 → 剔除（即使命中强正向词）；
3. 命中 negative_strong 中任一词，且没有 strong_signals → 剔除；
4. 弱信号守门：如果 positive 命中的全部都是 weak_only_positive 中的词，
   且摘要里没有任何 strong_signals，则剔除。
"""
import re
from typing import List


def _normalize_kw_to_regex(kw: str) -> str:
    r"""把单个关键词转为正则片段，逐字符处理：
    - 空白 / 连字符 → [\s\-]+ （互换）
    - 字母数字 → 原样
    - 其他特殊字符 → re.escape 该字符
    并加上词边界。
    """
    chunks = []
    i = 0
    while i < len(kw):
        ch = kw[i]
        if ch.isspace() or ch == "-":
            # 把连续的空白/连字符合并为单个 [\s\-]+
            chunks.append(r"[\s\-]+")
            while i < len(kw) and (kw[i].isspace() or kw[i] == "-"):
                i += 1
            continue
        if ch.isalnum():
            chunks.append(ch)
        else:
            chunks.append(re.escape(ch))
        i += 1
    body = "".join(chunks)
    return rf"(?<![A-Za-z0-9])(?:{body})(?![A-Za-z0-9])"


def _build_pattern(keywords: List[str]) -> re.Pattern:
    """构建一个忽略大小写、按词边界匹配的正则。
    对带空格 / 连字符的多词短语，做宽松一些的匹配（连字符和空格互通）。
    """
    parts = []
    for kw in keywords:
        kw_str = kw.strip()
        if not kw_str:
            continue
        parts.append(_normalize_kw_to_regex(kw_str))
    if not parts:
        # 不可能匹配的模式
        return re.compile(r"$^")
    return re.compile("|".join(parts), re.IGNORECASE)


def _find_matches(text: str, pattern: re.Pattern) -> List[str]:
    """返回所有命中的关键词（去重，小写）。"""
    if not text:
        return []
    matches = pattern.findall(text)
    # findall 返回 group(0) 字符串列表
    seen = set()
    out = []
    for m in matches:
        # m 可能是 tuple（多 group），但我们没用 group，会直接是 str
        key = m.lower() if isinstance(m, str) else str(m).lower()
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def filter_papers_by_keywords(papers: List[dict], filter_config: dict, *, verbose: bool = True) -> List[dict]:
    """Filter papers with domain-specific positive/negative keyword rules.

    Args:
        papers: arxiv fetcher 返回的论文列表
        filter_config: 从 filter_keywords.yaml 加载的 dict

    Returns:
        通过筛选的论文列表（顺序保留）
    """
    positive = filter_config.get("positive", [])
    hard_negative = filter_config.get("hard_negative", [])
    negative_strong = filter_config.get("negative_strong", [])
    weak_only = filter_config.get("weak_only_positive", [])
    strong_signals = filter_config.get("strong_signals", [])

    pos_pat = _build_pattern(positive)
    hard_neg_pat = _build_pattern(hard_negative) if hard_negative else None
    neg_pat = _build_pattern(negative_strong) if negative_strong else None
    weak_pat = _build_pattern(weak_only)
    strong_pat = _build_pattern(strong_signals)

    kept = []
    rejected_count = {"no_positive": 0, "hard_negative": 0, "negative": 0, "weak_only": 0}

    for paper in papers:
        text = f"{paper.get('title', '')} \n {paper.get('abstract', '')}"

        if hard_neg_pat:
            hard_neg_hits = _find_matches(text, hard_neg_pat)
            if hard_neg_hits:
                rejected_count["hard_negative"] += 1
                continue

        pos_hits = _find_matches(text, pos_pat)
        if not pos_hits:
            rejected_count["no_positive"] += 1
            continue

        # Strong domain signals can override broad negative matches.
        strong_hits = _find_matches(text, strong_pat)

        if neg_pat:
            neg_hits = _find_matches(text, neg_pat)
            if neg_hits and not strong_hits:
                rejected_count["negative"] += 1
                continue

        # 弱信号守门
        weak_hits = set(_find_matches(text, weak_pat))
        # 如果 positive 命中的全部都是弱信号
        if set(pos_hits).issubset(weak_hits):
            if not strong_hits:
                rejected_count["weak_only"] += 1
                continue

        # 通过
        paper["filter_hits"] = pos_hits  # 保留命中信息便于调试
        kept.append(paper)

    if verbose:
        print(
            f"  [filter] kept={len(kept)} / total={len(papers)} "
            f"(rejected: no_positive={rejected_count['no_positive']}, "
            f"hard_negative={rejected_count['hard_negative']}, "
            f"negative={rejected_count['negative']}, "
            f"weak_only={rejected_count['weak_only']})"
        )

    return kept
