"""Capture a complete, dated Hugging Face feed before using it for reconciliation."""

import hashlib
import json
import os
import re
import tempfile
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .enricher import HF_API_URL
from .fetcher import NS, ArxivClient, _parse_entry


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=path.parent, delete=False, encoding="utf-8"
    ) as stream:
        json.dump(
            value, stream, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        )
    os.replace(stream.name, path)


def paper_id(raw):
    match = re.fullmatch(r"(\d{4}\.\d{4,5}|[a-z][a-z0-9.-]*/\d{7})(v\d+)?", raw or "")
    if not match:
        raise ValueError(f"Invalid arXiv identifier: {raw!r}")
    return match[1]


def fetch_hf(day, session=None):
    date.fromisoformat(day)
    if session is None:
        with requests.Session() as client:
            retry = Retry(
                total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504]
            )
            client.mount("https://", HTTPAdapter(max_retries=retry))
            return fetch_hf(day, client)
    url = f"{HF_API_URL}?date={day}&limit=100"
    visited = set()
    result = {}
    while url:
        parts = urlsplit(url)
        if (parts.scheme, parts.netloc, parts.path) != (
            "https",
            "huggingface.co",
            "/api/daily_papers",
        ):
            raise ValueError("Invalid HF pagination URL")
        if parse_qs(parts.query).get("date") != [day] or url in visited:
            raise ValueError("HF pagination changed date or repeated a page")
        visited.add(url)
        response = session.get(url, timeout=30)
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list):
            raise TypeError("Invalid HF daily response")
        for row in rows:
            p = row["paper"]
            key = paper_id(p["id"])
            result[key] = {
                "arxiv_id": key,
                "version": p["id"],
                "title": p.get("title"),
                "abstract": p.get("summary"),
                "published_at": p.get("publishedAt"),
                "authors": [a["name"] for a in p.get("authors", [])],
                "hf_record": row,
                "hf_date": day,
                "upvotes": p.get("upvotes", 0),
                "abs_url": f"https://arxiv.org/abs/{key}",
            }
            if not all(result[key][k] for k in ("title", "abstract", "published_at")):
                feed = ArxivClient().fetch_feed(
                    params={"id_list": key, "max_results": 1},
                    category="HF metadata",
                    offset=0,
                )
                entry = feed.find("atom:entry", NS)
                if entry is None:
                    raise ValueError(f"Missing arXiv metadata for {key}")
                metadata = _parse_entry(entry)
                if metadata["arxiv_id"] != key or not all(
                    metadata[k] for k in ("title", "abstract", "published_at")
                ):
                    raise ValueError(f"Incomplete arXiv metadata for {key}")
                result[key].update(metadata)
        url = response.links.get("next", {}).get("url")
    return result
