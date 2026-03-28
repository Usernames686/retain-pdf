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
from rendering.render_payload_parts.metrics import fit_translated_block_metrics
from rendering.render_payload_parts.metrics import LAYOUT_DENSITY_SAFE_MAX
from rendering.render_payload_parts.metrics import LAYOUT_DENSITY_SAFE_MIN
from rendering.render_payload_parts.metrics import resolve_typst_binary_fit
from rendering.render_payload_parts.metrics import VERTICAL_COLLISION_GAP_PT
from rendering.render_payload_parts.metrics import text_demand_units
from rendering.render_payload_parts.shared import COMPACT_SCALE
from rendering.render_payload_parts.shared import COMPACT_TRIGGER_RATIO
from rendering.render_payload_parts.shared import get_render_protected_text
from rendering.render_payload_parts.shared import HEAVY_COMPACT_RATIO
from rendering.render_payload_parts.shared import is_flag_like_plain_text_block
from rendering.render_payload_parts.shared import source_word_count
from rendering.render_payload_parts.shared import translation_density_ratio
from rendering.render_payload_parts.shared import translated_zh_char_count

BODY_DENSITY_TARGET_MIN = 0.82
BODY_DENSITY_TARGET_MAX = 0.92
BODY_PRESSURE_TIGHTEN_TRIGGER = 1.38
BODY_PRESSURE_TIGHTEN_TRIGGER_HIGH = 1.30
BODY_FINAL_FORCE_FIT_DENSITY = 1.12
BODY_FINAL_FORCE_FIT_NON_HEAVY_EXTRA_MARGIN = 0.08
BODY_FINAL_VERTICAL_TARGET_RATIO = 0.96
SMALL_PAGE_BOX_RATIO = 0.06
ULTRA_SMALL_PAGE_BOX_RATIO = 0.04
SMALL_BOX_GROW_DENSITY_TRIGGER = 0.88
SMALL_BOX_GROW_FONT_GAP = 0.1
SMALL_BOX_GROW_STEP = 0.22
SMALL_BOX_GROW_ELIGIBLE_MAX_DENSITY = 1.02
SMALL_BOX_GROW_MAX_DENSITY = 1.03
VERTICAL_COLLISION_MIN_WIDTH_OVERLAP_RATIO = 0.6
VERTICAL_COLLISION_SOURCE_GAP_TRIGGER_PT = 3.0
VERTICAL_COLLISION_TRIGGER_RATIO = 0.98
ADJACENT_BODY_SMOOTH_MAX_GAP_PT = 42.0
ADJACENT_BODY_SMOOTH_MIN_WIDTH_RATIO = 0.72
ADJACENT_BODY_SMOOTH_MIN_WIDTH_OVERLAP_RATIO = 0.64
ADJACENT_BODY_SMOOTH_MAX_LEFT_DELTA_PT = 18.0
ADJACENT_BODY_SMOOTH_MAX_CENTER_DELTA_PT = 22.0
ADJACENT_BODY_SMOOTH_MIN_BOX_HEIGHT_PT = 36.0
ADJACENT_BODY_SMOOTH_MIN_WIDTH_PT = 64.0
ADJACENT_BODY_SMOOTH_MIN_PAGE_WIDTH_RATIO = 0.38
ADJACENT_BODY_SMOOTH_MIN_SOURCE_WORDS = 10
ADJACENT_BODY_SMOOTH_MIN_TRANSLATED_ZH_CHARS = 18
ADJACENT_BODY_SMOOTH_MAX_FONT_DELTA_PT = 0.24
ADJACENT_BODY_SMOOTH_RELAXED_FONT_DELTA_PT = 0.34
ADJACENT_BODY_SMOOTH_MAX_LEADING_DELTA_EM = 0.06
ADJACENT_BODY_SMOOTH_RELAXED_LEADING_DELTA_EM = 0.09
ADJACENT_BODY_SMOOTH_GROW_DENSITY_MAX = 0.95
ADJACENT_BODY_SMOOTH_RELAXED_GROW_DENSITY_MAX = 0.99


def _page_box_area_ratio(bbox: list[float], page_width: float | None, page_height: float | None) -> float:
    if len(bbox) != 4 or not page_width or not page_height or page_width <= 0 or page_height <= 0:
        return 0.0
    width = max(0.0, bbox[2] - bbox[0])
    height = max(0.0, bbox[3] - bbox[1])
    if width <= 0 or height <= 0:
        return 0.0
    return (width * height) / (page_width * page_height)


def _payload_inner_width(payload: dict) -> float:
    return max(8.0, payload["inner_bbox"][2] - payload["inner_bbox"][0])


def _payload_inner_height(payload: dict) -> float:
    return max(8.0, payload["inner_bbox"][3] - payload["inner_bbox"][1])


def _payload_inner_top(payload: dict) -> float:
    return payload["inner_bbox"][1]


def _payload_inner_bottom(payload: dict) -> float:
    return payload["inner_bbox"][3]


def _payload_center_x(payload: dict) -> float:
    return (payload["inner_bbox"][0] + payload["inner_bbox"][2]) / 2.0


def _payload_estimated_density(
    payload: dict,
    *,
    font_size_pt: float | None = None,
    leading_em: float | None = None,
) -> float:
    inner_height = _payload_inner_height(payload)
    estimated_height = estimated_render_height_pt(
        payload["inner_bbox"],
        payload["translated_text"],
        payload["formula_map"],
        font_size_pt if font_size_pt is not None else payload["font_size_pt"],
        leading_em if leading_em is not None else payload["leading_em"],
    )
    return estimated_height / inner_height


def _payload_has_enough_text_for_smoothing(payload: dict) -> bool:
    item = payload["item"]
    source_words = source_word_count(item)
    translated_zh_chars = translated_zh_char_count(payload["translated_text"])
    return source_words >= ADJACENT_BODY_SMOOTH_MIN_SOURCE_WORDS or translated_zh_chars >= ADJACENT_BODY_SMOOTH_MIN_TRANSLATED_ZH_CHARS


def _is_adjacent_body_smoothing_candidate(payload: dict, *, page_text_width_med: float) -> bool:
    if not payload["is_body"] or payload["render_kind"] != "markdown":
        return False
    if payload["heavy_dense_small_box"]:
        return False
    if _payload_inner_height(payload) < ADJACENT_BODY_SMOOTH_MIN_BOX_HEIGHT_PT:
        return False
    width = _payload_inner_width(payload)
    min_width = ADJACENT_BODY_SMOOTH_MIN_WIDTH_PT
    if page_text_width_med > 0:
        min_width = max(min_width, page_text_width_med * ADJACENT_BODY_SMOOTH_MIN_PAGE_WIDTH_RATIO)
    if width < min_width:
        return False
    if not _payload_has_enough_text_for_smoothing(payload):
        return False
    return True


def _is_same_column_adjacent_body_pair(current: dict, nxt: dict, *, page_text_width_med: float) -> bool:
    if not _is_adjacent_body_smoothing_candidate(current, page_text_width_med=page_text_width_med):
        return False
    if not _is_adjacent_body_smoothing_candidate(nxt, page_text_width_med=page_text_width_med):
        return False
    if _payload_inner_top(nxt) < _payload_inner_top(current):
        return False

    current_width = _payload_inner_width(current)
    next_width = _payload_inner_width(nxt)
    width_ratio = min(current_width, next_width) / max(current_width, next_width)
    if width_ratio < ADJACENT_BODY_SMOOTH_MIN_WIDTH_RATIO:
        return False

    overlap_width = max(0.0, min(current["inner_bbox"][2], nxt["inner_bbox"][2]) - max(current["inner_bbox"][0], nxt["inner_bbox"][0]))
    if overlap_width / min(current_width, next_width) < ADJACENT_BODY_SMOOTH_MIN_WIDTH_OVERLAP_RATIO:
        return False

    gap = _payload_inner_top(nxt) - _payload_inner_bottom(current)
    max_gap = max(ADJACENT_BODY_SMOOTH_MAX_GAP_PT, min(_payload_inner_height(current), _payload_inner_height(nxt)) * 0.45)
    if gap < -4.0 or gap > max_gap:
        return False

    left_delta = abs(current["inner_bbox"][0] - nxt["inner_bbox"][0])
    center_delta = abs(_payload_center_x(current) - _payload_center_x(nxt))
    left_limit = max(ADJACENT_BODY_SMOOTH_MAX_LEFT_DELTA_PT, max(current_width, next_width) * 0.06)
    center_limit = max(ADJACENT_BODY_SMOOTH_MAX_CENTER_DELTA_PT, max(current_width, next_width) * 0.08)
    if left_delta > left_limit and center_delta > center_limit:
        return False
    return True


def _cap_font_growth_by_density(payload: dict, target_font_size_pt: float, *, density_limit: float) -> float:
    current_font_size = payload["font_size_pt"]
    if target_font_size_pt <= current_font_size:
        return round(target_font_size_pt, 2)

    low = current_font_size
    high = target_font_size_pt
    best = current_font_size
    for _ in range(8):
        mid = (low + high) / 2.0
        if _payload_estimated_density(payload, font_size_pt=mid) <= density_limit:
            best = mid
            low = mid
        else:
            high = mid
    return round(best, 2)


def _cap_leading_growth_by_density(payload: dict, target_leading_em: float, *, density_limit: float) -> float:
    current_leading = payload["leading_em"]
    if target_leading_em <= current_leading:
        return round(target_leading_em, 2)

    low = current_leading
    high = target_leading_em
    best = current_leading
    for _ in range(8):
        mid = (low + high) / 2.0
        if _payload_estimated_density(payload, leading_em=mid) <= density_limit:
            best = mid
            low = mid
        else:
            high = mid
    return round(best, 2)


def _normalize_body_payload_leading(payload: dict) -> None:
    reference_font_size_pt = payload.get("page_body_font_size_pt") or payload["font_size_pt"]
    payload["leading_em"] = normalize_leading_em_for_font_size(
        payload["font_size_pt"],
        payload["leading_em"],
        reference_font_size_pt=reference_font_size_pt,
        min_leading_em=BODY_LEADING_MIN,
        max_leading_em=BODY_LEADING_MAX,
        strength=BODY_LEADING_SIZE_ADJUST,
        floor_min_leading_em=BODY_LEADING_FLOOR_MIN,
    )


def _smooth_adjacent_body_pair(current: dict, nxt: dict) -> None:
    current_density = _payload_estimated_density(current)
    next_density = _payload_estimated_density(nxt)
    relaxed = (
        max(current_density, next_density) > 0.92
        or current["dense_small_box"]
        or nxt["dense_small_box"]
        or current["prefer_typst_fit"]
        or nxt["prefer_typst_fit"]
    )
    max_font_delta = ADJACENT_BODY_SMOOTH_RELAXED_FONT_DELTA_PT if relaxed else ADJACENT_BODY_SMOOTH_MAX_FONT_DELTA_PT
    max_leading_delta = ADJACENT_BODY_SMOOTH_RELAXED_LEADING_DELTA_EM if relaxed else ADJACENT_BODY_SMOOTH_MAX_LEADING_DELTA_EM
    density_limit = ADJACENT_BODY_SMOOTH_RELAXED_GROW_DENSITY_MAX if relaxed else ADJACENT_BODY_SMOOTH_GROW_DENSITY_MAX

    if current["font_size_pt"] <= nxt["font_size_pt"]:
        smaller_font_payload = current
        larger_font_payload = nxt
    else:
        smaller_font_payload = nxt
        larger_font_payload = current

    font_delta = larger_font_payload["font_size_pt"] - smaller_font_payload["font_size_pt"]
    if font_delta > max_font_delta:
        excess = font_delta - max_font_delta
        grow_allowed = (
            not smaller_font_payload["prefer_typst_fit"]
            and not smaller_font_payload["heavy_dense_small_box"]
            and _payload_estimated_density(smaller_font_payload) <= density_limit
        )
        grown = 0.0
        if grow_allowed:
            desired_font_size = smaller_font_payload["font_size_pt"] + excess * 0.6
            bounded_font_size = _cap_font_growth_by_density(
                smaller_font_payload,
                desired_font_size,
                density_limit=density_limit,
            )
            grown = max(0.0, bounded_font_size - smaller_font_payload["font_size_pt"])
            smaller_font_payload["font_size_pt"] = bounded_font_size
        larger_font_payload["font_size_pt"] = round(max(6.4, larger_font_payload["font_size_pt"] - max(0.0, excess - grown)), 2)

    if current["leading_em"] <= nxt["leading_em"]:
        smaller_leading_payload = current
        larger_leading_payload = nxt
    else:
        smaller_leading_payload = nxt
        larger_leading_payload = current

    leading_delta = larger_leading_payload["leading_em"] - smaller_leading_payload["leading_em"]
    if leading_delta > max_leading_delta:
        excess = leading_delta - max_leading_delta
        grow_allowed = (
            not smaller_leading_payload["prefer_typst_fit"]
            and _payload_estimated_density(smaller_leading_payload) <= max(BODY_DENSITY_TARGET_MAX, density_limit - 0.02)
        )
        grown = 0.0
        if grow_allowed:
            desired_leading = smaller_leading_payload["leading_em"] + excess * 0.35
            bounded_leading = _cap_leading_growth_by_density(
                smaller_leading_payload,
                desired_leading,
                density_limit=max(BODY_DENSITY_TARGET_MAX, density_limit - 0.02),
            )
            grown = max(0.0, bounded_leading - smaller_leading_payload["leading_em"])
            smaller_leading_payload["leading_em"] = bounded_leading
        larger_leading_payload["leading_em"] = round(max(0.18, larger_leading_payload["leading_em"] - max(0.0, excess - grown)), 2)

    _normalize_body_payload_leading(current)
    _normalize_body_payload_leading(nxt)


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
            down_band = 0.34 if heavy_dense_small_box else (0.2 if dense_small_box else 0.06)
            up_band = 0.18 if dense_small_box else 0.24
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
                "prefer_typst_fit": bool(body_flags.get(index, False) and dense_small_box),
                "adjacent_collision_risk": False,
                "adjacent_available_height_pt": None,
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
            payload["font_size_pt"] = round(min(max(payload["font_size_pt"], body_font_median - 0.10), body_font_median + 0.14), 2)
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
            if pressure_ratio > pressure_trigger and payload["dense_small_box"] and density > body_density_target + 0.04:
                steps = min(3, max(1, ceil((pressure_ratio - pressure_trigger) / 0.26)))
                payload["font_size_pt"] = round(max(body_font_median - 0.34, payload["font_size_pt"] - steps * 0.08), 2)
                payload["leading_em"] = round(min(BODY_LEADING_MAX, payload["leading_em"] + 0.01 * min(steps, 2)), 2)
                payload["prefer_typst_fit"] = True
                estimated_height = estimated_render_height_pt(
                    payload["inner_bbox"],
                    payload["translated_text"],
                    payload["formula_map"],
                    payload["font_size_pt"],
                    payload["leading_em"],
                )
                density = estimated_height / inner_height
            if density > body_density_target + 0.06 and payload["dense_small_box"] and pressure_ratio > BODY_PRESSURE_TIGHTEN_TRIGGER_HIGH:
                payload["prefer_typst_fit"] = True
            elif density < body_density_target - 0.12 and pressure_ratio < 0.94:
                steps = min(2, max(1, ceil((body_density_target - density) / 0.12)))
                payload["font_size_pt"] = round(min(body_font_median + 0.08, payload["font_size_pt"] + steps * 0.04), 2)

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
            if payload["heavy_dense_small_box"] and density > BODY_FINAL_FORCE_FIT_DENSITY:
                payload["prefer_typst_fit"] = True

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
            grow_font_gap = SMALL_BOX_GROW_FONT_GAP if payload["dense_small_box"] else 0.2
            if payload["font_size_pt"] >= body_font_median - grow_font_gap:
                continue
            candidate_step = SMALL_BOX_GROW_STEP if payload["dense_small_box"] and density <= SMALL_BOX_GROW_DENSITY_TRIGGER else 0.12
            candidate_cap = body_font_median - 0.12
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

        # Smooth body text with its true nearest vertical neighbor in the same column.
        # This avoids obvious within-page jumps without forcing dense / extreme blocks
        # back into an unsafe size band.
        body_payloads_by_top = sorted(body_payloads, key=lambda payload: (payload["inner_bbox"][1], payload["inner_bbox"][0]))
        smoothed_pairs: set[tuple[int, int]] = set()
        for index, current in enumerate(body_payloads_by_top):
            best_next = None
            best_key = None
            for nxt in body_payloads_by_top[index + 1 :]:
                if not _is_same_column_adjacent_body_pair(current, nxt, page_text_width_med=page_text_width_med):
                    continue
                gap = max(-4.0, _payload_inner_top(nxt) - _payload_inner_bottom(current))
                center_delta = abs(_payload_center_x(current) - _payload_center_x(nxt))
                key = (gap, center_delta)
                if best_key is None or key < best_key:
                    best_key = key
                    best_next = nxt
            if best_next is None:
                continue
            pair_key = (id(current), id(best_next))
            if pair_key in smoothed_pairs:
                continue
            _smooth_adjacent_body_pair(current, best_next)
            smoothed_pairs.add(pair_key)

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
        if estimated_height <= max_height_pt * VERTICAL_COLLISION_TRIGGER_RATIO:
            continue
        current["adjacent_collision_risk"] = True
        previous_limit = current.get("adjacent_available_height_pt")
        if previous_limit is None or max_height_pt < previous_limit:
            current["adjacent_available_height_pt"] = max_height_pt

    for payload in sorted(block_payloads, key=lambda payload: payload["index"]):
        fit_to_box, fit_min_font_size_pt, fit_min_leading_em = resolve_typst_binary_fit(
            {
                **payload["item"],
                "_is_body_text_candidate": payload["is_body"],
                "_dense_small_box": payload["dense_small_box"],
                "_heavy_dense_small_box": payload["heavy_dense_small_box"],
            },
            payload["translated_text"],
            payload["formula_map"],
            payload["font_size_pt"],
            payload["leading_em"],
            page_body_font_size_pt=payload["page_body_font_size_pt"],
            prefer_typst_fit=payload["prefer_typst_fit"],
            adjacent_collision_risk=payload["adjacent_collision_risk"],
            adjacent_available_height_pt=payload["adjacent_available_height_pt"],
        )
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
                fit_to_box=fit_to_box and payload["render_kind"] == "markdown" and payload["is_body"],
                fit_min_font_size_pt=fit_min_font_size_pt,
                fit_min_leading_em=fit_min_leading_em,
            )
        )
    return blocks
