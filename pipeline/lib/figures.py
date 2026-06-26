"""Extract key figures from arXiv PDFs."""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any

import requests

from .blob_uploader import FigureStorage

ARXIV_UA = "paper-hunt/1.0 (offline figure extraction; contact: local-run)"
FIGURE_RENDER_SCALE = float(os.getenv("FIGURE_RENDER_SCALE", "4"))
FIGURE_DETECT_IMGSZ = int(os.getenv("FIGURE_DETECT_IMGSZ", "1280"))
FIGURE_MAX_DIM = int(os.getenv("FIGURE_MAX_DIM", "2400"))
FIGURE_WEBP_QUALITY = int(os.getenv("FIGURE_WEBP_QUALITY", "94"))
THUMB_MAX_SIZE = (
    int(os.getenv("FIGURE_THUMB_MAX_WIDTH", "720")),
    int(os.getenv("FIGURE_THUMB_MAX_HEIGHT", "480")),
)
THUMB_WEBP_QUALITY = int(os.getenv("FIGURE_THUMB_WEBP_QUALITY", "88"))


def configure_figure_runtime_cache(root: str | Path | None = None) -> None:
    """Point third-party model/plot caches at a writable project directory."""
    cache_root = Path(root or os.getenv("FIGURE_CACHE_DIR") or "tmp/figure-cache")
    cache_root.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache_root / "matplotlib"))
    os.environ.setdefault("YOLO_CONFIG_DIR", str(cache_root / "ultralytics"))
    os.environ.setdefault("HF_HOME", str(cache_root / "huggingface"))
    for value in ("MPLCONFIGDIR", "YOLO_CONFIG_DIR", "HF_HOME"):
        Path(os.environ[value]).mkdir(parents=True, exist_ok=True)


def extract_figures(
    arxiv_id: str,
    out_dir: str | Path,
    *,
    storage: FigureStorage | None = None,
    max_figures: int | None = None,
    max_pages: int = 6,
) -> dict[str, Any]:
    """Download a paper PDF, crop key figures, upload/copy them, return metadata."""
    configure_figure_runtime_cache()
    storage = storage or FigureStorage()
    backend = os.getenv("FIGURE_BACKEND", "pymupdf")
    if max_figures is None:
        max_figures = int(os.getenv("FIGURE_MAX_COUNT", "4"))
    work_dir = Path(out_dir) / _clean_id(arxiv_id)
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        pdf_path = _download_pdf(arxiv_id, work_dir)
        if backend == "yolo":
            crops = _extract_with_yolo(pdf_path, work_dir, max_figures=max_figures, max_pages=max_pages)
            if not crops:
                crops = _extract_with_pymupdf(pdf_path, work_dir, max_figures=max_figures, max_pages=max_pages)
        else:
            crops = _extract_with_pymupdf(pdf_path, work_dir, max_figures=max_figures, max_pages=max_pages)
        return _publish_crops(arxiv_id, crops, storage)
    except Exception as exc:  # noqa: BLE001 - figures must not block a run
        print(f"[figures] {arxiv_id}: skipped ({exc})")
        return {"figures": [], "thumb": ""}


def _download_pdf(arxiv_id: str, work_dir: Path) -> Path:
    clean_id = _clean_id(arxiv_id)
    target = work_dir / f"{clean_id}.pdf"
    if target.exists() and target.stat().st_size > 0:
        return target
    url = f"https://arxiv.org/pdf/{clean_id}"
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            resp = requests.get(url, headers={"User-Agent": ARXIV_UA}, timeout=60)
            resp.raise_for_status()
            target.write_bytes(resp.content)
            time.sleep(1.0)
            return target
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(2 + attempt)
    raise RuntimeError(f"PDF download failed: {last_error}") from last_error


def _extract_with_pymupdf(
    pdf_path: Path,
    work_dir: Path,
    *,
    max_figures: int,
    max_pages: int,
) -> list[dict[str, Any]]:
    import fitz

    doc = fitz.open(pdf_path)
    crops: list[dict[str, Any]] = []
    seen: set[int] = set()
    for page_index in range(min(max_pages, len(doc))):
        page = doc[page_index]
        images = page.get_images(full=True)
        candidates = []
        for img in images:
            xref = img[0]
            if xref in seen:
                continue
            rects = page.get_image_rects(xref)
            if not rects:
                continue
            rect = max(rects, key=lambda r: r.width * r.height)
            area = rect.width * rect.height
            if area < 10_000:
                continue
            candidates.append((area, xref, rect))
        candidates.sort(reverse=True, key=lambda item: item[0])
        for _, xref, rect in candidates[:2]:
            seen.add(xref)
            pix = page.get_pixmap(matrix=fitz.Matrix(FIGURE_RENDER_SCALE, FIGURE_RENDER_SCALE), clip=rect, alpha=False)
            png_path = work_dir / f"p{page_index + 1}_{len(crops) + 1}.png"
            pix.save(png_path)
            webp_path = _to_webp(png_path)
            crops.append(
                {
                    "path": webp_path,
                    "page": page_index + 1,
                    "kind": "figure",
                    "confidence": 0.5,
                    "area": float(area),
                    "width": float(rect.width),
                    "height": float(rect.height),
                }
            )
    return _rank_overview_candidates(crops)[:max_figures]


def _extract_with_yolo(
    pdf_path: Path,
    work_dir: Path,
    *,
    max_figures: int,
    max_pages: int,
) -> list[dict[str, Any]]:
    import fitz
    from PIL import Image

    try:
        from doclayout_yolo import YOLOv10
        from huggingface_hub import hf_hub_download
    except Exception as exc:
        raise RuntimeError("doclayout-yolo and huggingface_hub are required") from exc

    model_path = hf_hub_download(
        repo_id="juliozhao/DocLayout-YOLO-DocStructBench",
        filename="doclayout_yolo_docstructbench_imgsz1024.pt",
    )
    model = YOLOv10(model_path)
    doc = fitz.open(pdf_path)
    candidates: list[dict[str, Any]] = []
    for page_index in range(min(max_pages, len(doc))):
        page = doc[page_index]
        pix = page.get_pixmap(matrix=fitz.Matrix(FIGURE_RENDER_SCALE, FIGURE_RENDER_SCALE), alpha=False)
        page_img = work_dir / f"page_{page_index + 1}.png"
        pix.save(page_img)
        results = model.predict(str(page_img), imgsz=FIGURE_DETECT_IMGSZ, conf=0.25, device="cpu")
        image = Image.open(page_img).convert("RGB")
        for result in results:
            names = getattr(result, "names", {})
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue
            for box in boxes:
                cls_id = int(box.cls[0])
                kind = str(names.get(cls_id, cls_id)).lower()
                if kind not in {"figure", "table"}:
                    continue
                conf = float(box.conf[0])
                x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].tolist()]
                width = max(0, x2 - x1)
                height = max(0, y2 - y1)
                area = width * height
                crop_path = work_dir / f"p{page_index + 1}_{len(candidates) + 1}.webp"
                _save_webp(image.crop((x1, y1, x2, y2)), crop_path, max_dim=FIGURE_MAX_DIM, quality=FIGURE_WEBP_QUALITY)
                candidates.append(
                    {
                        "path": crop_path,
                        "page": page_index + 1,
                        "kind": kind,
                        "confidence": conf,
                        "area": area,
                        "width": width,
                        "height": height,
                    }
                )
    return _rank_overview_candidates(candidates)[:max_figures]


def _rank_overview_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prefer overview/pipeline-like figures over first-page or table crops."""
    if not candidates:
        return []
    max_area = max(float(c.get("area", 0) or 0) for c in candidates) or 1.0

    def score(candidate: dict[str, Any]) -> float:
        page = int(candidate.get("page", 99) or 99)
        kind = str(candidate.get("kind", "")).lower()
        area = float(candidate.get("area", 0) or 0)
        width = float(candidate.get("width", 0) or 0)
        height = float(candidate.get("height", 0) or 0)
        aspect = width / height if height > 0 else 1.0

        value = 0.0
        value += 2.0 if kind == "figure" else -1.6
        value += min(area / max_area, 1.0) * 1.5
        value += float(candidate.get("confidence", 0) or 0) * 0.5

        if page == 1:
            value += 0.2
        elif 2 <= page <= 4:
            value += 1.2
        elif page <= 6:
            value += 0.6

        if 1.25 <= aspect <= 3.8:
            value += 1.0
        elif 0.9 <= aspect < 1.25:
            value += 0.25
        elif aspect > 4.5 or aspect < 0.55:
            value -= 0.6

        return value

    return sorted(
        candidates,
        key=lambda c: (-score(c), int(c.get("page", 99) or 99), -float(c.get("area", 0) or 0)),
    )


def _publish_crops(
    arxiv_id: str,
    crops: list[dict[str, Any]],
    storage: FigureStorage,
) -> dict[str, Any]:
    from PIL import Image

    clean_id = _clean_id(arxiv_id)
    figures: list[dict[str, Any]] = []
    thumb = ""
    for i, crop in enumerate(crops, start=1):
        path = Path(crop["path"])
        src = storage.upload_file(path, f"{clean_id}/fig{i}.webp")
        if i == 1:
            thumb_path = path.parent / "thumb.webp"
            image = Image.open(path).convert("RGB")
            image.thumbnail(THUMB_MAX_SIZE, Image.Resampling.LANCZOS)
            image.save(thumb_path, "WEBP", quality=THUMB_WEBP_QUALITY, method=6)
            thumb = storage.upload_file(thumb_path, f"{clean_id}/thumb.webp")
        figures.append(
            {
                "src": src,
                "page": crop["page"],
                "kind": crop["kind"],
                "confidence": round(float(crop.get("confidence", 0)), 3),
            }
        )
    return {"figures": figures, "thumb": thumb}


def _to_webp(path: Path) -> Path:
    from PIL import Image

    image = Image.open(path).convert("RGB")
    target = path.with_suffix(".webp")
    _save_webp(image, target, max_dim=FIGURE_MAX_DIM, quality=FIGURE_WEBP_QUALITY)
    return target


def _save_webp(image: Any, target: Path, *, max_dim: int, quality: int) -> None:
    from PIL import Image

    image = image.convert("RGB")
    image.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
    image.save(target, "WEBP", quality=quality, method=6)


def _clean_id(arxiv_id: str) -> str:
    return re.sub(r"v\d+$", "", str(arxiv_id).strip().removesuffix(".pdf"))
