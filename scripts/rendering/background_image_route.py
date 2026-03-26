from __future__ import annotations

from io import BytesIO

import fitz
from PIL import Image

from rendering.pdf_overlay_parts.redaction_analysis import page_has_large_background_image
from rendering.pdf_overlay_parts.redaction_fill import quantile
from rendering.pdf_overlay_parts.redaction_geometry import rect_area
from rendering.pdf_overlay_parts.shared import iter_valid_translated_items


def _pick_primary_background_image(
    page: fitz.Page,
    *,
    coverage_ratio_threshold: float = 0.75,
) -> tuple[int, fitz.Rect] | None:
    page_area = max(rect_area(page.rect), 1.0)
    best: tuple[float, int, fitz.Rect] | None = None
    try:
        images = page.get_images(full=True)
    except Exception:
        return None

    for image in images:
        if not image:
            continue
        xref = image[0]
        try:
            rects = page.get_image_rects(xref)
        except Exception:
            continue
        for rect in rects:
            if rect.is_empty:
                continue
            coverage_ratio = rect_area(rect & page.rect) / page_area
            if coverage_ratio < coverage_ratio_threshold:
                continue
            candidate = (coverage_ratio, xref, rect)
            if best is None or candidate[0] > best[0]:
                best = candidate
    if best is None:
        return None
    return best[1], best[2]


def _extract_image_rgb(doc: fitz.Document, xref: int) -> Image.Image | None:
    try:
        payload = doc.extract_image(xref)
    except Exception:
        payload = None
    if payload and payload.get("image"):
        try:
            image = Image.open(BytesIO(payload["image"]))
            return image.convert("RGB")
        except Exception:
            pass
    try:
        pix = fitz.Pixmap(doc, xref)
        image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        return image
    except Exception:
        return None


def _brightness_spread(pixels: list[tuple[int, int, int]]) -> int:
    if not pixels:
        return 255
    brightness = sorted(int((r + g + b) / 3) for r, g, b in pixels)
    return quantile(brightness, 9, 10) - quantile(brightness, 1, 10)


def _map_rect_to_image(image_rect: fitz.Rect, image_size: tuple[int, int], rect: fitz.Rect) -> tuple[int, int, int, int] | None:
    width, height = image_size
    if width <= 0 or height <= 0:
        return None
    inter = rect & image_rect
    if inter.is_empty:
        return None
    sx = width / max(image_rect.width, 1e-6)
    sy = height / max(image_rect.height, 1e-6)
    x0 = max(0, min(width, int((inter.x0 - image_rect.x0) * sx)))
    y0 = max(0, min(height, int((inter.y0 - image_rect.y0) * sy)))
    x1 = max(0, min(width, int((inter.x1 - image_rect.x0) * sx)))
    y1 = max(0, min(height, int((inter.y1 - image_rect.y0) * sy)))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    return x0, y0, x1, y1


def _candidate_strips(width: int, height: int, box: tuple[int, int, int, int]) -> list[tuple[int, int, int, int]]:
    x0, y0, x1, y1 = box
    margin = max(6, min(24, int(min(x1 - x0, y1 - y0) * 0.35)))
    candidates = [
        (max(0, x0 - margin), y0, x0, y1),
        (x1, y0, min(width, x1 + margin), y1),
        (x0, max(0, y0 - margin), x1, y0),
        (x0, y1, x1, min(height, y1 + margin)),
    ]
    return [candidate for candidate in candidates if candidate[2] - candidate[0] >= 2 and candidate[3] - candidate[1] >= 2]


def _pick_background_patch(image: Image.Image, box: tuple[int, int, int, int]) -> Image.Image | None:
    width, height = image.size
    best_patch: Image.Image | None = None
    best_score: tuple[int, int, int] | None = None
    for candidate in _candidate_strips(width, height, box):
        patch = image.crop(candidate)
        pixels = list(patch.getdata())
        if len(pixels) < 32:
            continue
        spread = _brightness_spread(pixels)
        complexity_bucket = 0 if spread <= 18 else 1
        area = (candidate[2] - candidate[0]) * (candidate[3] - candidate[1])
        score = (complexity_bucket, spread, -area)
        if best_score is None or score < best_score:
            best_score = score
            best_patch = patch
    if best_score is None or best_score[0] > 0 or best_patch is None:
        return None
    x0, y0, x1, y1 = box
    return best_patch.resize((x1 - x0, y1 - y0))


def _sample_background_color(image: Image.Image, box: tuple[int, int, int, int]) -> tuple[int, int, int]:
    width, height = image.size
    x0, y0, x1, y1 = box
    margin = max(8, min(28, int(min(x1 - x0, y1 - y0) * 0.4)))
    outer = (
        max(0, x0 - margin),
        max(0, y0 - margin),
        min(width, x1 + margin),
        min(height, y1 + margin),
    )
    sample = image.crop(outer)
    inner_x0 = x0 - outer[0]
    inner_y0 = y0 - outer[1]
    inner_x1 = x1 - outer[0]
    inner_y1 = y1 - outer[1]
    pixels: list[tuple[int, int, int]] = []
    for yy in range(sample.height):
        inside_y = inner_y0 <= yy < inner_y1
        for xx in range(sample.width):
            if inside_y and inner_x0 <= xx < inner_x1:
                continue
            pixels.append(sample.getpixel((xx, yy)))
    if not pixels:
        return (255, 255, 255)
    rs = sorted(pixel[0] for pixel in pixels)
    gs = sorted(pixel[1] for pixel in pixels)
    bs = sorted(pixel[2] for pixel in pixels)
    return (
        quantile(rs, 1, 2),
        quantile(gs, 1, 2),
        quantile(bs, 1, 2),
    )


def _rewrite_background_image(
    image: Image.Image,
    image_rect: fitz.Rect,
    rects: list[fitz.Rect],
) -> Image.Image:
    updated = image.copy()
    for rect in rects:
        mapped = _map_rect_to_image(image_rect, updated.size, rect)
        if mapped is None:
            continue
        patch = _pick_background_patch(updated, mapped)
        if patch is not None:
            updated.paste(patch, (mapped[0], mapped[1]))
            continue
        updated.paste(_sample_background_color(updated, mapped), mapped)
    return updated


def replace_background_image_page(
    page: fitz.Page,
    translated_items: list[dict],
) -> bool:
    if not page_has_large_background_image(page):
        return False
    primary = _pick_primary_background_image(page)
    if primary is None:
        return False

    xref, image_rect = primary
    doc = page.parent
    image = _extract_image_rgb(doc, xref)
    if image is None:
        return False

    rects = [rect for rect, _item, _translated_text in iter_valid_translated_items(translated_items)]
    if not rects:
        return False

    rebuilt = _rewrite_background_image(image, image_rect, rects)
    buffer = BytesIO()
    rebuilt.save(buffer, format="PNG")
    image_bytes = buffer.getvalue()

    page.add_redact_annot(page.rect, fill=False)
    page.apply_redactions(
        images=fitz.PDF_REDACT_IMAGE_REMOVE,
        graphics=fitz.PDF_REDACT_LINE_ART_NONE,
        text=fitz.PDF_REDACT_TEXT_REMOVE,
    )
    page.insert_image(image_rect, stream=image_bytes, keep_proportion=False, overlay=True)
    return True


__all__ = ["replace_background_image_page"]
