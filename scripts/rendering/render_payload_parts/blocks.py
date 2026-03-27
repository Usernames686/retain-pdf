from __future__ import annotations

from math import ceil
from statistics import median

from rendering.font_fit import bbox_width
from rendering.font_fit import estimate_font_size_pt
from rendering.font_fit import estimate_leading_em
from rendering.font_fit import inner_bbox
from rendering.font_fit import is_body_text_candidate
from rendering.font_fit import normalize_leading_em_for_font_size
from rendering.font_fit import NON_BODY_LEADING_FLOOR_MIN
from rendering.font_fit import NON_BODY_LEADING_MAX
from rendering.font_fit import NON_BODY_LEADING_MIN
from rendering.font_fit import page_baseline_font_size
from rendering.font_fit import BODY_LEADING_FLOOR_MIN
from rendering.font_fit import BODY_LEADING_MAX
from rendering.font_fit import BODY_LEADING_MIN
from rendering.font_fit import BODY_LEADING_SIZE_ADJUST
from rendering.font_fit import NON_BODY_LEADING_SIZE_ADJUST
from rendering.math_utils import build_markdown_from_parts
from rendering.math_utils import build_plain_text_from_text
from rendering.models import RenderBlock
from rendering.render_payload_parts.metrics import estimated_render_height_pt
from rendering.render_payload_parts.metrics import fit_block_to_vertical_limit
from rendering.render_payload_parts.metrics import fit_translated_block_metrics
from rendering.render_payload_parts.metrics import LAYOUT_DENSITY_SAFE_MAX
from rendering.render_payload_parts.metrics import LAYOUT_DENSITY_SAFE_MIN
from rendering.render_payload_parts.metrics import VERTICAL_COLLISION_GAP_PT
from rendering.render_payload_parts.metrics import text_demand_units
from rendering.render_payload_parts.shared import COMPACT_SCALE
from rendering.render_payload_parts.shared import COMPACT_TRIGGER_RATIO
from rendering.render_payload_parts.shared import get_render_protected_text
from rendering.render_payload_parts.shared import HEAVY_COMPACT_RATIO
from rendering.render_payload_parts.shared import is_flag_like_plain_text_block
from rendering.render_payload_parts.shared import translation_density_ratio

BODY_DENSITY_TARGET_MIN = 0.82
BODY_DENSITY_TARGET_MAX = 0.92
BODY_PRESSURE_TIGHTEN_TRIGGER = 1.18
BODY_PRESSURE_TIGHTEN_TRIGGER_HIGH = 1.1
BODY_FINAL_FORCE_FIT_DENSITY = 1.03
BODY_FINAL_FORCE_FIT_NON_HEAVY_EXTRA_MARGIN = 0.04
BODY_FINAL_VERTICAL_TARGET_RATIO = 0.9
SMALL_PAGE_BOX_RATIO = 0.06
ULTRA_SMALL_PAGE_BOX_RATIO = 0.04
SMALL_BOX_GROW_DENSITY_TRIGGER = 0.88
SMALL_BOX_GROW_FONT_GAP = 0.12
SMALL_BOX_GROW_STEP = 0.22
SMALL_BOX_GROW_ELIGIBLE_MAX_DENSITY = 1.02
SMALL_BOX_GROW_MAX_DENSITY = 1.03
VERTICAL_COLLISION_MIN_WIDTH_OVERLAP_RATIO = 0.6
VERTICAL_COLLISION_SOURCE_GAP_TRIGGER_PT = 5.0
VERTICAL_COLLISION_DENSITY_TRIGGER = 0.96
VERTICAL_COLLISION_OVERFLOW_TRIGGER = 1.08


def _page_box_area_ratio(bbox: list[float], page_width: float | None, page_height: float | None) -> float:
    if len(bbox) != 4 or not page_width or not page_height or page_width <= 0 or page_height <= 0:
        return 0.0
    width = max(0.0, bbox[2] - bbox[0])
    height = max(0.0, bbox[3] - bbox[1])
    if width <= 0 or height <= 0:
        return 0.0
    return (width * height) / (page_width * page_height)


def build_render_blocks(
    translated_items: list[dict],
    *,
    page_width: float | None = None,
    page_height: float | None = None,
) -> list[RenderBlock]:
    blocks: list[RenderBlock] = []
    page_font_size, page_line_pitch, page_line_height, density_baseline = page_baseline_font_size(translated_items)
    text_widths = [bbox_width(item) for item in translated_items if item.get("block_type") == "text"]
    page_text_width_med = median(text_widths) if text_widths else 0.0
    body_base_sizes: list[float] = []
    body_flags: dict[int, bool] = {}
    base_metrics: dict[int, tuple[float, float]] = {}

    for index, item in enumerate(translated_items):
        item_with_flag = dict(item)
        item_with_flag["_is_body_text_candidate"] = is_body_text_candidate(item, page_text_width_med)
        body_flags[index] = item_with_flag["_is_body_text_candidate"]
        font_size_pt = estimate_font_size_pt(
            item_with_flag,
            page_font_size,
            page_line_pitch,
            page_line_height,
            density_baseline,
        )
        leading_em = estimate_leading_em(item_with_flag, page_line_pitch, font_size_pt)
        base_metrics[index] = (font_size_pt, leading_em)
        if item_with_flag["_is_body_text_candidate"]:
            body_base_sizes.append(font_size_pt)

    page_body_font_size_pt = round(median(body_base_sizes), 2) if body_base_sizes else None

    block_payloads: list[dict] = []

    for index, item in enumerate(translated_items):
        translated_text = get_render_protected_text(item)
        bbox = item.get("bbox", [])
        if len(bbox) != 4 or not translated_text:
            continue
        font_size_pt, leading_em = base_metrics[index]
        formula_map = item.get("render_formula_map") or item.get("translation_unit_formula_map") or item.get("formula_map", [])
        density_ratio = translation_density_ratio(item, translated_text)
        is_dense_block = density_ratio >= COMPACT_TRIGGER_RATIO
        is_heavy_dense_block = density_ratio >= HEAVY_COMPACT_RATIO
        page_box_area_ratio = _page_box_area_ratio(bbox, page_width, page_height)
        dense_small_box = density_ratio >= 0.9 and 0 < page_box_area_ratio <= SMALL_PAGE_BOX_RATIO
        heavy_dense_small_box = density_ratio >= 1.0 and 0 < page_box_area_ratio <= ULTRA_SMALL_PAGE_BOX_RATIO
        if body_flags.get(index) and page_body_font_size_pt is not None:
            down_band = 0.62 if heavy_dense_small_box else (0.42 if dense_small_box else 0.18)
            up_band = 0.22 if dense_small_box else 0.34
            font_size_pt = round(min(max(font_size_pt, page_body_font_size_pt - down_band), page_body_font_size_pt + up_band), 2)
        if dense_small_box and not body_flags.get(index):
            font_size_pt = round(font_size_pt * COMPACT_SCALE, 2)
            leading_em = round(leading_em * COMPACT_SCALE, 2)
        font_size_pt, leading_em = fit_translated_block_metrics(
            {
                **item,
                "_is_body_text_candidate": body_flags.get(index, False),
                "_page_box_area_ratio": page_box_area_ratio,
                "_dense_small_box": dense_small_box,
                "_heavy_dense_small_box": heavy_dense_small_box,
            },
            translated_text,
            formula_map,
            font_size_pt,
            leading_em,
            page_body_font_size_pt=page_body_font_size_pt if body_flags.get(index) else None,
        )
        if body_flags.get(index):
            leading_em = normalize_leading_em_for_font_size(
                font_size_pt,
                leading_em,
                reference_font_size_pt=page_body_font_size_pt or page_font_size,
                min_leading_em=BODY_LEADING_MIN,
                max_leading_em=BODY_LEADING_MAX,
                strength=BODY_LEADING_SIZE_ADJUST,
                floor_min_leading_em=BODY_LEADING_FLOOR_MIN,
            )
        else:
            leading_em = normalize_leading_em_for_font_size(
                font_size_pt,
                leading_em,
                reference_font_size_pt=page_font_size,
                min_leading_em=NON_BODY_LEADING_MIN,
                max_leading_em=NON_BODY_LEADING_MAX,
                strength=NON_BODY_LEADING_SIZE_ADJUST,
                floor_min_leading_em=NON_BODY_LEADING_FLOOR_MIN,
            )
        block_payloads.append(
            {
                "index": index,
                "item": item,
                "bbox": bbox,
                "inner_bbox": inner_bbox(item),
                "translated_text": translated_text,
                "formula_map": formula_map,
                "render_kind": "plain_line" if item.get("_force_plain_line") or is_flag_like_plain_text_block(item) else "markdown",
                "font_size_pt": font_size_pt,
                "leading_em": leading_em,
                "page_body_font_size_pt": page_body_font_size_pt if body_flags.get(index) else None,
                "is_body": body_flags.get(index, False),
                "page_box_area_ratio": page_box_area_ratio,
                "dense_small_box": dense_small_box,
                "heavy_dense_small_box": heavy_dense_small_box,
            }
        )

    ordered_payloads = sorted(block_payloads, key=lambda payload: (payload["inner_bbox"][1], payload["inner_bbox"][0]))
    body_payloads = [payload for payload in ordered_payloads if payload["is_body"]]
    if body_payloads:
        body_font_median = median(payload["font_size_pt"] for payload in body_payloads)
        for payload in body_payloads:
            payload["page_body_font_size_pt"] = round(body_font_median, 2)
        body_density_values = []
        body_pressure_values = []
        for payload in body_payloads:
            inner_height = max(8.0, payload["inner_bbox"][3] - payload["inner_bbox"][1])
            inner_width = max(8.0, payload["inner_bbox"][2] - payload["inner_bbox"][0])
            demand = text_demand_units(payload["translated_text"], payload["formula_map"])
            estimated_height = estimated_render_height_pt(
                payload["inner_bbox"],
                payload["translated_text"],
                payload["formula_map"],
                payload["font_size_pt"],
                payload["leading_em"],
            )
            body_density_values.append(estimated_height / inner_height)
            body_pressure_values.append(demand / max(1.0, inner_width * inner_height))
        body_density_target = median(body_density_values) if body_density_values else 0.72
        body_density_target = max(BODY_DENSITY_TARGET_MIN, min(BODY_DENSITY_TARGET_MAX, body_density_target))
        body_pressure_median = median(body_pressure_values) if body_pressure_values else 0.0

        for payload in body_payloads:
            payload["font_size_pt"] = round(min(max(payload["font_size_pt"], body_font_median - 0.18), body_font_median + 0.18), 2)
            inner_height = max(8.0, payload["inner_bbox"][3] - payload["inner_bbox"][1])
            inner_width = max(8.0, payload["inner_bbox"][2] - payload["inner_bbox"][0])
            demand = text_demand_units(payload["translated_text"], payload["formula_map"])
            pressure = demand / max(1.0, inner_width * inner_height)
            pressure_ratio = pressure / max(body_pressure_median, 1e-6) if body_pressure_median > 0 else 1.0
            estimated_height = estimated_render_height_pt(
                payload["inner_bbox"],
                payload["translated_text"],
                payload["formula_map"],
                payload["font_size_pt"],
                payload["leading_em"],
            )
            density = estimated_height / inner_height
            pressure_trigger = BODY_PRESSURE_TIGHTEN_TRIGGER_HIGH if density > body_density_target + 0.03 else BODY_PRESSURE_TIGHTEN_TRIGGER
            if pressure_ratio > pressure_trigger and (payload["dense_small_box"] or density > body_density_target + 0.03):
                steps = min(4, max(1, ceil((pressure_ratio - pressure_trigger) / 0.22)))
                payload["font_size_pt"] = round(max(body_font_median - 0.48, payload["font_size_pt"] - steps * 0.1), 2)
                payload["leading_em"] = round(min(BODY_LEADING_MAX, payload["leading_em"] + 0.015 * min(steps, 3)), 2)
                estimated_height = estimated_render_height_pt(
                    payload["inner_bbox"],
                    payload["translated_text"],
                    payload["formula_map"],
                    payload["font_size_pt"],
                    payload["leading_em"],
                )
                density = estimated_height / inner_height
            if (payload["heavy_dense_small_box"] and density > body_density_target + 0.02) or density > body_density_target + 0.08 or (
                density > body_density_target + 0.04 and pressure_ratio > BODY_PRESSURE_TIGHTEN_TRIGGER_HIGH
            ):
                font_size_pt, leading_em = fit_block_to_vertical_limit(
                    {**payload["item"], "_is_body_text_candidate": True},
                    payload["translated_text"],
                    payload["formula_map"],
                    payload["font_size_pt"],
                    payload["leading_em"],
                    inner_height * body_density_target,
                    page_body_font_size_pt=payload["page_body_font_size_pt"],
                )
                payload["font_size_pt"] = font_size_pt
                payload["leading_em"] = leading_em
            elif density < body_density_target - 0.12 and pressure_ratio < 0.96:
                steps = min(2, max(1, ceil((body_density_target - density) / 0.12)))
                payload["font_size_pt"] = round(min(body_font_median + 0.12, payload["font_size_pt"] + steps * 0.06), 2)

        # Final page-level correction: force dense outliers down, then pull obviously small blocks back toward the page band.
        body_font_median = median(payload["font_size_pt"] for payload in body_payloads)
        for payload in body_payloads:
            inner_height = max(8.0, payload["inner_bbox"][3] - payload["inner_bbox"][1])
            estimated_height = estimated_render_height_pt(
                payload["inner_bbox"],
                payload["translated_text"],
                payload["formula_map"],
                payload["font_size_pt"],
                payload["leading_em"],
            )
            density = estimated_height / inner_height
            if (
                (payload["heavy_dense_small_box"] and density > BODY_FINAL_FORCE_FIT_DENSITY)
                or (
                    payload["dense_small_box"]
                    and density > BODY_FINAL_FORCE_FIT_DENSITY + BODY_FINAL_FORCE_FIT_NON_HEAVY_EXTRA_MARGIN
                )
            ):
                font_size_pt, leading_em = fit_block_to_vertical_limit(
                    {**payload["item"], "_is_body_text_candidate": True},
                    payload["translated_text"],
                    payload["formula_map"],
                    payload["font_size_pt"],
                    payload["leading_em"],
                    inner_height * BODY_FINAL_VERTICAL_TARGET_RATIO,
                    page_body_font_size_pt=body_font_median,
                )
                payload["font_size_pt"] = font_size_pt
                payload["leading_em"] = leading_em

        body_font_median = median(payload["font_size_pt"] for payload in body_payloads)
        for payload in body_payloads:
            inner_height = max(8.0, payload["inner_bbox"][3] - payload["inner_bbox"][1])
            estimated_height = estimated_render_height_pt(
                payload["inner_bbox"],
                payload["translated_text"],
                payload["formula_map"],
                payload["font_size_pt"],
                payload["leading_em"],
            )
            density = estimated_height / inner_height
            eligible_max_density = SMALL_BOX_GROW_ELIGIBLE_MAX_DENSITY if payload["dense_small_box"] else 0.9
            if density >= eligible_max_density:
                continue
            grow_font_gap = SMALL_BOX_GROW_FONT_GAP if payload["dense_small_box"] else 0.28
            if payload["font_size_pt"] >= body_font_median - grow_font_gap:
                continue
            candidate_step = SMALL_BOX_GROW_STEP if payload["dense_small_box"] and density <= SMALL_BOX_GROW_DENSITY_TRIGGER else 0.18
            candidate_cap = body_font_median - 0.18
            candidate_font = round(min(candidate_cap, payload["font_size_pt"] + candidate_step), 2)
            candidate_height = estimated_render_height_pt(
                payload["inner_bbox"],
                payload["translated_text"],
                payload["formula_map"],
                candidate_font,
                payload["leading_em"],
            )
            candidate_density = candidate_height / inner_height
            max_candidate_density = SMALL_BOX_GROW_MAX_DENSITY if payload["dense_small_box"] else 0.94
            if candidate_density <= max_candidate_density:
                payload["font_size_pt"] = candidate_font

        # Harmonize adjacent long body paragraphs on the same page so font size / leading does not drift too far.
        long_body_payloads = []
        for payload in body_payloads:
            inner_width = max(8.0, payload["inner_bbox"][2] - payload["inner_bbox"][0])
            inner_height = max(8.0, payload["inner_bbox"][3] - payload["inner_bbox"][1])
            estimated_height = estimated_render_height_pt(
                payload["inner_bbox"],
                payload["translated_text"],
                payload["formula_map"],
                payload["font_size_pt"],
                payload["leading_em"],
            )
            density = estimated_height / inner_height
            if inner_height < 90 or inner_width < page_text_width_med * 0.72:
                continue
            if density > 0.98:
                continue
            long_body_payloads.append(payload)

        if len(long_body_payloads) >= 2:
            long_body_font_median = median(payload["font_size_pt"] for payload in long_body_payloads)
            long_body_leading_median = median(payload["leading_em"] for payload in long_body_payloads)
            for payload in long_body_payloads:
                payload["font_size_pt"] = round(
                    min(max(payload["font_size_pt"], long_body_font_median - 0.14), long_body_font_median + 0.14),
                    2,
                )
                payload["leading_em"] = round(
                    min(max(payload["leading_em"], long_body_leading_median - 0.05), long_body_leading_median + 0.05),
                    2,
                )

        # Smooth adjacent long body blocks in the same column to avoid obvious font/leading jumps on pages like the abstract page.
        for prev_payload, next_payload in zip(ordered_payloads, ordered_payloads[1:]):
            if prev_payload["item"].get("block_type") != "text" or next_payload["item"].get("block_type") != "text":
                continue
            prev_h = max(8.0, prev_payload["inner_bbox"][3] - prev_payload["inner_bbox"][1])
            next_h = max(8.0, next_payload["inner_bbox"][3] - next_payload["inner_bbox"][1])
            prev_w = max(8.0, prev_payload["inner_bbox"][2] - prev_payload["inner_bbox"][0])
            next_w = max(8.0, next_payload["inner_bbox"][2] - next_payload["inner_bbox"][0])
            if prev_h < 90 or next_h < 90:
                continue
            if min(prev_w, next_w) / max(prev_w, next_w) < 0.88:
                continue
            if abs(prev_payload["inner_bbox"][0] - next_payload["inner_bbox"][0]) > 14:
                continue
            prev_density = estimated_render_height_pt(
                prev_payload["inner_bbox"],
                prev_payload["translated_text"],
                prev_payload["formula_map"],
                prev_payload["font_size_pt"],
                prev_payload["leading_em"],
            ) / prev_h
            next_density = estimated_render_height_pt(
                next_payload["inner_bbox"],
                next_payload["translated_text"],
                next_payload["formula_map"],
                next_payload["font_size_pt"],
                next_payload["leading_em"],
            ) / next_h
            if prev_density > 1.0 or next_density > 1.0:
                continue
            shared_font = round((prev_payload["font_size_pt"] + next_payload["font_size_pt"]) / 2.0, 2)
            shared_leading = round((prev_payload["leading_em"] + next_payload["leading_em"]) / 2.0, 2)
            for payload in (prev_payload, next_payload):
                payload["font_size_pt"] = round(
                    min(max(payload["font_size_pt"], shared_font - 0.12), shared_font + 0.12),
                    2,
                )
                payload["leading_em"] = round(
                    min(max(payload["leading_em"], shared_leading - 0.04), shared_leading + 0.04),
                    2,
                )

    for current, nxt in zip(ordered_payloads, ordered_payloads[1:]):
        current_left, current_top_y, current_right, _ = current["inner_bbox"]
        next_left, next_top, next_right, _ = nxt["inner_bbox"]
        overlap_width = max(0.0, min(current_right, next_right) - max(current_left, next_left))
        min_width = max(1.0, min(current_right - current_left, next_right - next_left))
        if overlap_width / min_width < VERTICAL_COLLISION_MIN_WIDTH_OVERLAP_RATIO:
            continue
        current_bottom = current["inner_bbox"][3]
        source_gap = next_top - current_bottom
        if source_gap > VERTICAL_COLLISION_SOURCE_GAP_TRIGGER_PT:
            continue
        current_top = current_top_y
        max_height_pt = next_top - current_top - VERTICAL_COLLISION_GAP_PT
        if max_height_pt <= 0:
            continue
        estimated_height = estimated_render_height_pt(
            current["inner_bbox"],
            current["translated_text"],
            current["formula_map"],
            current["font_size_pt"],
            current["leading_em"],
        )
        current_inner_height = max(8.0, current_bottom - current_top)
        current_density = estimated_height / current_inner_height
        # Only use this pass as a last-resort guard when source boxes are already
        # nearly touching and the current block is visually dense. Otherwise it
        # causes unnecessary page-local font drift.
        if source_gap > 0 and current_density < VERTICAL_COLLISION_DENSITY_TRIGGER:
            continue
        if estimated_height <= max_height_pt * VERTICAL_COLLISION_OVERFLOW_TRIGGER:
            continue
        font_size_pt, leading_em = fit_block_to_vertical_limit(
            {**current["item"], "_is_body_text_candidate": current["is_body"]},
            current["translated_text"],
            current["formula_map"],
            current["font_size_pt"],
            current["leading_em"],
            max_height_pt,
            page_body_font_size_pt=current["page_body_font_size_pt"],
        )
        current["font_size_pt"] = font_size_pt
        current["leading_em"] = leading_em

    for payload in sorted(block_payloads, key=lambda payload: payload["index"]):
        blocks.append(
            RenderBlock(
                block_id=f"item-{payload['index']}",
                bbox=payload["bbox"],
                inner_bbox=payload["inner_bbox"],
                markdown_text=build_markdown_from_parts(payload["translated_text"], payload["formula_map"]),
                plain_text=build_plain_text_from_text(payload["translated_text"]),
                render_kind=payload["render_kind"],
                font_size_pt=payload["font_size_pt"],
                leading_em=payload["leading_em"],
            )
        )
    return blocks
