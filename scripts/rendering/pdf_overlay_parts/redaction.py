from __future__ import annotations

import fitz

from rendering.pdf_overlay_parts.redaction_analysis import (
    collect_page_drawing_rects,
    item_has_removable_text,
    page_has_large_background_image,
    item_should_use_cover_only,
    page_is_vector_heavy,
    page_should_use_cover_only,
)
from rendering.pdf_overlay_parts.redaction_fill import (
    apply_prepared_background_covers,
    draw_background_covers,
    prepare_background_covers,
    draw_white_covers,
    resolved_fill_color,
)
from rendering.pdf_overlay_parts.shared import iter_valid_translated_items


def redact_translated_text_areas(
    page: fitz.Page,
    translated_items: list[dict],
    fill_background: bool | None = None,
    cover_only: bool = False,
) -> None:
    valid_items = iter_valid_translated_items(translated_items)
    if not valid_items:
        return

    if cover_only:
        draw_white_covers(page, [rect for rect, _item, _translated_text in valid_items])
        return

    if page_has_large_background_image(page):
        rects = [rect for rect, _item, _translated_text in valid_items]
        prepared_covers = prepare_background_covers(page, rects)
        for rect in rects:
            page.add_redact_annot(rect, fill=False)
        page.apply_redactions(
            images=fitz.PDF_REDACT_IMAGE_PIXELS,
            graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED,
            text=fitz.PDF_REDACT_TEXT_REMOVE,
        )
        apply_prepared_background_covers(page, prepared_covers)
        return

    drawing_rects = collect_page_drawing_rects(page)
    if fill_background is None and page_is_vector_heavy(drawing_rects):
        rects = [rect for rect, _item, _translated_text in valid_items]
        draw_white_covers(page, rects)
        for rect in rects:
            page.add_redact_annot(rect, fill=False)
        page.apply_redactions(
            images=fitz.PDF_REDACT_IMAGE_PIXELS,
            graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED,
            text=fitz.PDF_REDACT_TEXT_REMOVE,
        )
        return

    if fill_background is None and page_should_use_cover_only(drawing_rects):
        draw_white_covers(page, [rect for rect, _item, _translated_text in valid_items])
        return

    redactions: list[tuple[fitz.Rect, tuple[float, float, float] | None]] = []
    cover_rects: list[fitz.Rect] = []
    for rect, item, _translated_text in valid_items:
        if fill_background is None:
            if item_should_use_cover_only(rect, drawing_rects):
                cover_rects.append(rect)
                continue
            fill = None if item_has_removable_text(page, item, rect) else (1, 1, 1)
        else:
            fill = (1, 1, 1) if fill_background else None
        redactions.append((rect, fill))

    draw_white_covers(page, cover_rects)

    for rect, fill in redactions:
        page.add_redact_annot(rect, fill=resolved_fill_color(page, rect, fill))
    if redactions:
        page.apply_redactions(
            images=fitz.PDF_REDACT_IMAGE_NONE,
            graphics=fitz.PDF_REDACT_LINE_ART_NONE,
            text=fitz.PDF_REDACT_TEXT_REMOVE,
        )


__all__ = [
    "item_has_removable_text",
    "redact_translated_text_areas",
]
