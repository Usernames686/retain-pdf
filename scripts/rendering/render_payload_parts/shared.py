from __future__ import annotations

import re

from rendering.formula_normalizer import aggressively_simplify_formula_for_latex_math
from rendering.math_utils import build_plain_text


TOKEN_RE = re.compile(r"(\[\[FORMULA_\d+]]|\s+|[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*|[\u4e00-\u9fff]|.)")
WORD_RE = re.compile(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*")
ZH_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")
SPLIT_PUNCTUATION = (".", "。", "!", "！", "?", "？", ";", "；", ":", "：", ",", "，")
STYLE_ONLY_LATEX_COMMAND_RE = re.compile(
    r"\\(?:left|right|mathrm|mathbf|mathit|mathsf|mathtt|text|operatorname|displaystyle|textstyle|scriptstyle|scriptscriptstyle)\b"
)
GENERIC_LATEX_COMMAND_RE = re.compile(r"\\[A-Za-z]+")
COMPACT_TRIGGER_RATIO = 0.9
COMPACT_SCALE = 0.9
HEAVY_COMPACT_RATIO = 1.0
LAYOUT_COMPACT_TRIGGER_RATIO = 0.9
LAYOUT_HEAVY_COMPACT_RATIO = 1.04
CONTINUATION_REBALANCE_MAX_PASSES = 3
CONTINUATION_REBALANCE_TOKEN_WINDOW = 80
CONTINUATION_REBALANCE_TARGET_TOLERANCE = 3.5
CONTINUATION_REBALANCE_IMBALANCE_TRIGGER = 12.0
CONTINUATION_REBALANCE_PUNCTUATION_PENALTY = 1.75
CONTINUATION_REBALANCE_NON_PUNCT_MIN_MOVE_UNITS = 18.0


def is_flag_like_plain_text_block(item: dict) -> bool:
    text = build_plain_text(item)
    if not text:
        return False
    if len(item.get("formula_map", [])) > 0:
        return False
    line_count = len(item.get("lines", []))
    if line_count > 2:
        return False
    if not text.startswith("-"):
        return False
    if len(text) > 64:
        return False
    return True


def tokenize_protected_text(text: str) -> list[str]:
    return TOKEN_RE.findall(text or "")


def strip_formula_placeholders(text: str) -> str:
    return re.sub(r"\[\[FORMULA_\d+]]", " ", text or "")


def normalize_render_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def same_meaningful_render_text(source_text: str, translated_text: str) -> bool:
    return normalize_render_text(source_text) == normalize_render_text(translated_text)


def get_render_protected_text(item: dict) -> str:
    if "render_protected_text" in item:
        return str(item.get("render_protected_text", "") or "").strip()
    return str(
        item.get("translation_unit_protected_translated_text")
        or item.get("protected_translated_text")
        or ""
    ).strip()


def source_word_count(item: dict) -> int:
    source_text = (
        item.get("render_source_text")
        or item.get("protected_source_text")
        or item.get("source_text")
        or ""
    )
    plain = strip_formula_placeholders(source_text)
    return len(WORD_RE.findall(plain))


def translated_zh_char_count(protected_text: str) -> int:
    plain = strip_formula_placeholders(protected_text)
    return len(ZH_CHAR_RE.findall(plain))


def translation_density_ratio(item: dict, protected_text: str) -> float:
    source_words = source_word_count(item)
    if source_words <= 0:
        return 0.0
    zh_chars = translated_zh_char_count(protected_text)
    if zh_chars <= 0:
        return 0.0
    return zh_chars / source_words


def layout_density_ratio(
    inner: list[float],
    protected_text: str,
    *,
    font_size_pt: float,
    line_step_pt: float,
) -> float:
    if len(inner) != 4 or font_size_pt <= 0 or line_step_pt <= 0:
        return 0.0
    width = max(8.0, inner[2] - inner[0])
    height = max(8.0, inner[3] - inner[1])
    zh_chars = translated_zh_char_count(protected_text)
    if zh_chars <= 0:
        return 0.0
    approx_char_width = max(font_size_pt * 0.92, 1.0)
    chars_per_line = max(4.0, width / approx_char_width)
    required_lines = max(1.0, zh_chars / chars_per_line)
    occupied_height = required_lines * line_step_pt
    return occupied_height / height


def _approx_formula_visible_text(formula_text: str) -> str:
    expr = aggressively_simplify_formula_for_latex_math(formula_text or "")
    if not expr:
        return ""
    expr = STYLE_ONLY_LATEX_COMMAND_RE.sub("", expr)
    expr = GENERIC_LATEX_COMMAND_RE.sub("x", expr)
    expr = re.sub(r"[{}]", "", expr)
    expr = expr.replace("~", "")
    expr = re.sub(r"\s+", "", expr)
    return expr


def token_units(token: str, formula_lookup: dict[str, str]) -> float:
    if not token:
        return 0.0
    if token.isspace():
        return max(0.2, len(token) * 0.25)
    if token.startswith("[[FORMULA_"):
        formula_text = formula_lookup.get(token, token)
        normalized = _approx_formula_visible_text(formula_text)
        if not normalized:
            normalized = re.sub(r"\s+", "", formula_text)
        return max(1.35, len(normalized) * 0.42)
    if re.fullmatch(r"[\u4e00-\u9fff]", token):
        return 1.0
    if re.fullmatch(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*", token):
        return max(1.0, len(token) * 0.55)
    return 0.45


def trim_joined_tokens(tokens: list[str]) -> str:
    return "".join(tokens).strip()


def _is_good_split_candidate(text: str) -> bool:
    return text.endswith(SPLIT_PUNCTUATION)


def _range_cost(prefix_costs: list[float], start: int, end: int) -> float:
    return prefix_costs[end] - prefix_costs[start]


def _probe_has_split_punctuation(tokens: list[str], start: int, end: int) -> bool:
    probe = end - 1
    while probe >= start and tokens[probe].isspace():
        probe -= 1
    if probe < start:
        return False
    return tokens[probe].endswith(SPLIT_PUNCTUATION)


def _trim_range_edges(tokens: list[str], start: int, end: int) -> tuple[int, int]:
    while start < end and tokens[start].isspace():
        start += 1
    while end > start and tokens[end - 1].isspace():
        end -= 1
    return start, end


def _range_text(tokens: list[str], start: int, end: int) -> str:
    start, end = _trim_range_edges(tokens, start, end)
    return trim_joined_tokens(tokens[start:end])


def _candidate_rebalance_positions(
    tokens: list[str],
    prefix_costs: list[float],
    *,
    start: int,
    end: int,
    ideal_end: int,
) -> list[int]:
    positions: set[int] = set()
    left = max(start + 1, ideal_end - CONTINUATION_REBALANCE_TOKEN_WINDOW)
    right = min(end - 1, ideal_end + CONTINUATION_REBALANCE_TOKEN_WINDOW)
    for probe in range(left, right + 1):
        positions.add(probe)
    for probe in range(start + 1, end):
        if _probe_has_split_punctuation(tokens, start, probe):
            positions.add(probe)
    positions.add(start + 1)
    positions.add(end - 1)
    return sorted(position for position in positions if start < position < end)


def _rebalance_chunk_ranges(
    tokens: list[str],
    prefix_costs: list[float],
    capacities: list[float],
    ranges: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    if len(ranges) <= 1:
        return ranges

    normalized_capacities = [max(1.0, value) for value in capacities]
    rebalanced = list(ranges)
    for _ in range(CONTINUATION_REBALANCE_MAX_PASSES):
        changed = False
        for index in range(len(rebalanced) - 1):
            left_start, left_end = rebalanced[index]
            right_start, right_end = rebalanced[index + 1]
            if left_start >= left_end or right_start >= right_end:
                continue

            left_cost = _range_cost(prefix_costs, left_start, left_end)
            right_cost = _range_cost(prefix_costs, right_start, right_end)
            combined_cost = left_cost + right_cost
            if combined_cost <= 0:
                continue

            left_target = combined_cost * normalized_capacities[index] / (
                normalized_capacities[index] + normalized_capacities[index + 1]
            )
            imbalance = left_cost - left_target
            if imbalance <= CONTINUATION_REBALANCE_IMBALANCE_TRIGGER:
                continue

            left_ratio = left_cost / normalized_capacities[index]
            right_ratio = right_cost / normalized_capacities[index + 1]
            if left_ratio <= right_ratio + 0.08:
                continue

            cumulative = 0.0
            ideal_probe = left_end - 1
            for probe in range(left_end - 1, left_start, -1):
                cumulative += token_units(tokens[probe], {})
                if cumulative >= imbalance:
                    ideal_probe = probe
                    break

            best_probe = None
            best_score = None
            for probe in _candidate_rebalance_positions(
                tokens,
                prefix_costs,
                start=left_start,
                end=left_end,
                ideal_end=ideal_probe,
            ):
                moved_cost = _range_cost(prefix_costs, probe, left_end)
                if moved_cost <= 0:
                    continue
                if (
                    moved_cost < CONTINUATION_REBALANCE_NON_PUNCT_MIN_MOVE_UNITS
                    and not _probe_has_split_punctuation(tokens, left_start, probe)
                ):
                    continue

                next_left_cost = _range_cost(prefix_costs, left_start, probe)
                next_right_cost = _range_cost(prefix_costs, probe, left_end) + right_cost
                target_delta = abs(next_left_cost - left_target)
                ratio_delta = abs(
                    (next_left_cost / normalized_capacities[index])
                    - (next_right_cost / normalized_capacities[index + 1])
                )
                punctuation_penalty = (
                    0.0 if _probe_has_split_punctuation(tokens, left_start, probe) else CONTINUATION_REBALANCE_PUNCTUATION_PENALTY
                )
                score = target_delta + ratio_delta * 6.0 + punctuation_penalty
                if best_score is None or score < best_score:
                    best_score = score
                    best_probe = probe

            if best_probe is None:
                continue

            next_left_cost = _range_cost(prefix_costs, left_start, best_probe)
            if abs(next_left_cost - left_cost) <= CONTINUATION_REBALANCE_TARGET_TOLERANCE:
                continue

            rebalanced[index] = (left_start, best_probe)
            rebalanced[index + 1] = (best_probe, right_end)
            changed = True
        if not changed:
            break
    return rebalanced


def split_protected_text_for_boxes(
    protected_text: str,
    formula_map: list[dict],
    capacities: list[float],
    *,
    preferred_weights: list[float] | None = None,
) -> list[str]:
    if len(capacities) <= 1:
        return [protected_text.strip()]
    tokens = tokenize_protected_text(protected_text)
    if not tokens:
        return [""] * len(capacities)
    formula_lookup = {entry["placeholder"]: entry["formula_text"] for entry in formula_map}
    token_costs = [token_units(token, formula_lookup) for token in tokens]
    prefix_costs = [0.0]
    for cost in token_costs:
        prefix_costs.append(prefix_costs[-1] + cost)
    remaining_cost = sum(token_costs)
    if remaining_cost <= 0:
        return [trim_joined_tokens(tokens)] + [""] * (len(capacities) - 1)

    ranges: list[tuple[int, int]] = []
    cursor = 0
    capacity_weights = [max(1.0, capacity) for capacity in capacities]
    total_capacity = sum(capacity_weights)
    preferred_costs = [max(1.0, value) for value in preferred_weights] if preferred_weights else capacity_weights[:]
    total_preferred = sum(preferred_costs)

    for box_index, capacity in enumerate(capacities):
        current_capacity = max(1.0, capacity)
        if box_index == len(capacities) - 1:
            ranges.append((cursor, len(tokens)))
            break

        remaining_boxes = len(capacities) - box_index - 1
        max_end = len(tokens) - remaining_boxes
        share = preferred_costs[box_index] / max(1.0, total_preferred)
        share_target = remaining_cost * share
        soft_target = min(share_target, current_capacity * 0.98)

        anchor = cursor + 1
        while anchor < max_end and _range_cost(prefix_costs, cursor, anchor) < soft_target:
            anchor += 1

        candidate_positions = set(range(max(cursor + 1, anchor - 24), min(max_end, anchor + 24) + 1))
        for probe in range(cursor + 1, max_end + 1):
            if _probe_has_split_punctuation(tokens, cursor, probe):
                candidate_positions.add(probe)
        candidate_positions.add(cursor + 1)
        candidate_positions.add(max_end)

        remaining_capacity_after = sum(capacity_weights[box_index + 1 :])
        best_end = cursor + 1
        best_score = None
        if remaining_capacity_after > 0 and current_capacity >= remaining_capacity_after * 2.0:
            current_overflow_weight = 28.0
            future_overflow_weight = 140.0
        else:
            current_overflow_weight = 72.0
            future_overflow_weight = 108.0
        for probe in sorted(candidate_positions):
            if probe <= cursor or probe > max_end:
                continue
            current_cost = _range_cost(prefix_costs, cursor, probe)
            future_cost = remaining_cost - current_cost
            current_overflow = max(0.0, current_cost - current_capacity * 1.01)
            future_overflow = max(0.0, future_cost - remaining_capacity_after * 1.03) if remaining_boxes else 0.0
            target_delta = abs(current_cost - share_target)
            underfill = max(0.0, current_capacity * 0.55 - current_cost)
            punctuation_penalty = 0.0 if _probe_has_split_punctuation(tokens, cursor, probe) else 1.25
            score = (
                current_overflow * current_overflow_weight
                + future_overflow * future_overflow_weight
                + target_delta
                + underfill * 0.1
                + punctuation_penalty
            )
            if best_score is None or score < best_score:
                best_score = score
                best_end = probe

        ranges.append((cursor, best_end))
        remaining_cost = max(0.0, remaining_cost - _range_cost(prefix_costs, cursor, best_end))
        total_capacity = max(1.0, total_capacity - current_capacity)
        total_preferred = max(1.0, total_preferred - preferred_costs[box_index])
        cursor = best_end

    while len(ranges) < len(capacities):
        ranges.append((len(tokens), len(tokens)))

    ranges = _rebalance_chunk_ranges(tokens, prefix_costs, capacities, ranges[: len(capacities)])
    chunks = [_range_text(tokens, start, end) for start, end in ranges[: len(capacities)]]
    while len(chunks) < len(capacities):
        chunks.append("")
    return chunks[: len(capacities)]
