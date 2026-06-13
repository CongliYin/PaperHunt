"""Storage abstraction for paper figures.

Default backend is Vercel Blob. If the token or SDK is unavailable, the backend
falls back to repo-local files so local runs still complete.
"""

from __future__ import annotations

import json
import mimetypes
import os
import shutil
import time
from pathlib import Path
from typing import Iterable
from urllib.parse import urlencode

import requests


class FigureStorage:
    def __init__(
        self,
        *,
        backend: str | None = None,
        public_dir: str | Path = "web/public",
        prefix: str | None = None,
    ) -> None:
        self.requested_backend = backend or os.getenv("STORAGE_BACKEND", "blob")
        self.public_dir = Path(public_dir)
        self.prefix = (prefix or os.getenv("BLOB_BASE_PREFIX") or "figures").strip("/")
        self.token = os.getenv("BLOB_READ_WRITE_TOKEN")
        self.backend = self._resolve_backend()

    def _resolve_backend(self) -> str:
        if self.requested_backend != "blob":
            return "repo"
        if not self.token:
            print("[storage] BLOB_READ_WRITE_TOKEN missing; falling back to repo storage")
            return "repo"
        return "blob"

    def upload_file(self, local_path: str | Path, dest_path: str) -> str:
        local = Path(local_path)
        dest_path = dest_path.strip("/")
        if self.backend == "blob":
            return self._upload_blob(local, dest_path)
        return self._copy_repo(local, dest_path)

    def _upload_blob(self, local: Path, dest_path: str) -> str:
        content_type = mimetypes.guess_type(local.name)[0] or "application/octet-stream"
        pathname = f"{self.prefix}/{dest_path}".strip("/")
        url = "https://vercel.com/api/blob/?" + urlencode({"pathname": pathname})
        headers = self._blob_api_headers()
        headers.update(
            {
                "x-vercel-blob-access": "public",
                "x-content-type": content_type,
                "x-add-random-suffix": "0",
                "x-allow-overwrite": "1",
                "content-type": content_type,
            }
        )
        response = _request_with_retries(
            "PUT",
            url,
            headers=headers,
            data=local.read_bytes(),
        )
        data = response.json()
        return data.get("url") or data.get("downloadUrl") or ""

    def _copy_repo(self, local: Path, dest_path: str) -> str:
        target = self.public_dir / self.prefix / dest_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local, target)
        return f"{self.prefix}/{dest_path}".strip("/")

    def delete_older_than(self, days: int) -> None:
        if days <= 0:
            return
        if self.backend == "blob":
            self._delete_old_blob(days)
        else:
            self._delete_old_repo(days)

    def _delete_old_blob(self, days: int) -> None:
        from datetime import datetime, timedelta, timezone

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        urls: list[str] = []
        cursor = ""
        while True:
            page = self._list_blob_page(cursor=cursor or None)
            for blob in page.get("blobs", []):
                uploaded_at = blob.get("uploadedAt")
                url = blob.get("url")
                if uploaded_at and url and _to_dt(uploaded_at) < cutoff:
                    urls.append(url)
            cursor = page.get("cursor") or ""
            if not page.get("hasMore") or not cursor:
                break
        if urls:
            self._delete_blob_urls(urls)

    def _list_blob_page(self, *, cursor: str | None = None) -> dict:
        params = {"prefix": f"{self.prefix}/"}
        if cursor:
            params["cursor"] = cursor
        url = "https://vercel.com/api/blob/?" + urlencode(params)
        response = _request_with_retries("GET", url, headers=self._blob_api_headers())
        return response.json()

    def _delete_blob_urls(self, urls: list[str]) -> None:
        url = "https://vercel.com/api/blob/delete"
        headers = self._blob_api_headers()
        headers["content-type"] = "application/json"
        _request_with_retries(
            "POST",
            url,
            headers=headers,
            data=json.dumps({"urls": urls}).encode("utf-8"),
        )

    def _blob_api_headers(self) -> dict[str, str]:
        store_id = _store_id_from_token(self.token or "")
        if not store_id:
            raise RuntimeError("Invalid BLOB_READ_WRITE_TOKEN: cannot parse store id")
        return {
            "authorization": f"Bearer {self.token}",
            "x-vercel-blob-store-id": store_id,
            "x-api-version": os.getenv("VERCEL_BLOB_API_VERSION_OVERRIDE", "12"),
        }

    def _delete_old_repo(self, days: int) -> None:
        import time

        root = self.public_dir / self.prefix
        if not root.exists():
            return
        cutoff = time.time() - days * 86400
        for path in _iter_files(root):
            if path.stat().st_mtime < cutoff:
                path.unlink()


def _iter_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if path.is_file():
            yield path


def _to_dt(value):
    from datetime import datetime, timezone

    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    return datetime.fromisoformat(text)


def _store_id_from_token(token: str) -> str:
    parts = token.split("_")
    return parts[3] if len(parts) >= 4 else ""


def _request_with_retries(method: str, url: str, **kwargs) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            response = requests.request(method, url, timeout=90, **kwargs)
            if response.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(
                    f"retryable HTTP {response.status_code}: {response.text[:300]}",
                    response=response,
                )
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001 - retry wrapper
            last_error = exc
            if attempt >= 3:
                break
            time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(f"Vercel Blob request failed: {last_error}") from last_error
