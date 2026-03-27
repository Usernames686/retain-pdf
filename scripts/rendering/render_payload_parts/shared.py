from __future__ import annotations

import re

from rendering.math_utils import build_plain_text


TOKEN_RE = re.compile(r"(\[\[FORMULA_\d+]]|\s+|[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*|[\u4e00-\u9fff]|.)")
WORD_RE = re.compile(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*")
ZH_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")
COMPACT_TRIGGER_RATIO = 0.9
COMPACT_SCALE = 0.9
HEAVY_COMPACT_RATIO = 1.0
LAYOUT_COMPACT_TRIGGER_RATIO = 0.9
LAYOUT_HEAVY_COMPACT_RATIO = 1.04


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
    source_text = item.get("protected_source_text") or item.get("source_text") or ""
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


def token_units(token: str, formula_lookup: dict[str, str]) -> float:
    if not token:
        return 0.0
    if token.isspace():
        return max(0.2, len(token) * 0.25)
    if token.startswith("[[FORMULA_"):
        formula_text = formula_lookup.get(token, token)
        normalized = re.sub(r"\s+", "", formula_text)
        return max(1.5, len(normalized) * 0.48)
    if re.fullmatch(r"[\u4e00-\u9fff]", token):
        return 1.0
    if re.fullmatch(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*", token):
        return max(1.0, len(token) * 0.55)
    return 0.45


def trim_joined_tokens(tokens: list[str]) -> str:
    return "".join(tokens).strip()


def _is_good_split_candidate(text: str) -> bool:
    return text.endswith((".", "。", "!", "！", "?", "？", ";", "；", ":", "：", ",", "，"))


def split_protected_text_for_boxes(protected_text: str, formula_map: list[dict], capacities: list[float]) -> list[str]:
    if len(capacities) <= 1:
        return [protected_text.strip()]
    tokens = tokenize_protected_text(protected_text)
    if not tokens:
        return [""] * len(capacities)
    formula_lookup = {entry["placeholder"]: entry["formula_text"] for entry in formula_map}
    token_costs = [token_units(token, formula_lookup) for token in tokens]
    remaining_cost = sum(token_costs)
    if remaining_cost <= 0:
        return [trim_joined_tokens(tokens)] + [""] * (len(capacities) - 1)

    chunks: list[str] = []
    cursor = 0
    total_capacity = sum(max(1.0, capacity) for capacity in capacities)

    for box_index, capacity in enumerate(capacities):
        if box_index == len(capacities) - 1:
            chunks.append(trim_joined_tokens(tokens[cursor:]))
            break

        share = max(1.0, capacity) / max(1.0, total_capacity)
        target_cost = remaining_cost * share
        running_cost = 0.0
        end = cursor
        best_end = cursor
        while end < len(tokens):
            running_cost += token_costs[end]
            end += 1
            if running_cost >= target_cost:
                best_end = end
                backward_start = max(cursor + 1, end - 12)
                backward_candidate = None
                backward_cost = None
                for probe in range(end, backward_start - 1, -1):
                    candidate = trim_joined_tokens(tokens[cursor:probe])
                    if _is_good_split_candidate(candidate):
                        backward_candidate = probe
                        backward_cost = sum(token_costs[cursor:probe])
                        break

                forward_candidate = None
                forward_cost = None
                lookahead = min(len(tokens), end + 12)
                for probe in range(end + 1, lookahead + 1):
                    candidate = trim_joined_tokens(tokens[cursor:probe])
                    if _is_good_split_candidate(candidate):
                        forward_candidate = probe
                        forward_cost = sum(token_costs[cursor:probe])
                        break

                if backward_candidate is not None and forward_candidate is not None:
                    if abs(backward_cost - target_cost) <= abs(forward_cost - target_cost):
                        best_end = backward_candidate
                    else:
                        best_end = forward_candidate
                elif backward_candidate is not None:
                    best_end = backward_candidate
                elif forward_candidate is not None:
                    best_end = forward_candidate
                break
        if best_end == cursor:
            best_end = min(len(tokens), max(cursor + 1, end))

        remaining_boxes = len(capacities) - box_index - 1
        if len(tokens) - best_end < remaining_boxes:
            best_end = max(cursor + 1, len(tokens) - remaining_boxes)

        chunks.append(trim_joined_tokens(tokens[cursor:best_end]))
        remaining_cost = max(0.0, remaining_cost - sum(token_costs[cursor:best_end]))
        total_capacity = max(1.0, total_capacity - max(1.0, capacity))
        cursor = best_end

    while len(chunks) < len(capacities):
        chunks.append("")
    return chunks[: len(capacities)]
