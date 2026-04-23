from __future__ import annotations

from collections import Counter
import re

from services.document_schema.semantics import is_body_structure_role
from services.translation.diagnostics import TranslationDiagnosticsCollector
from services.translation.llm.deepseek_client import unwrap_translation_shell
from services.translation.payload.formula_protection import protected_map_from_formula_map
from services.translation.payload.formula_protection import protect_glossary_terms
from services.translation.payload.formula_protection import PROTECTED_TOKEN_RE
from services.translation.policy.metadata_filter import looks_like_url_fragment
from services.translation.policy.reference_section import looks_like_reference_entry_text
from services.translation.policy.soft_hints import looks_like_code_literal_text_value


FORMAL_PLACEHOLDER_RE = re.compile(r"<f\d+-[0-9a-z]{3}/>|<t\d+-[0-9a-z]{3}/>|\[\[FORMULA_\d+]]")
ALIAS_PLACEHOLDER_RE = re.compile(r"@@P\d+@@")
PLACEHOLDER_RE = re.compile(rf"{PROTECTED_TOKEN_RE.pattern}|@@P\d+@@")
FORMULA_TOKEN_RE = re.compile(r"<f\d+-[0-9a-z]{3}/>|\[\[FORMULA_\d+]]|@@P\d+@@")
EN_WORD_RE = re.compile(r"[A-Za-z]+(?:[-'][A-Za-z]+)?")
KEEP_ORIGIN_LABEL = "keep_origin"
INTERNAL_PLACEHOLDER_DEGRADED_REASON = "placeholder_unstable"
SHORT_FRAGMENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._/-]{0,7}$")
CLAUSE_SPLIT_RE = re.compile(r"[^。！？；.!?;\n]+[。！？；.!?;\n]?")
DEDUP_TOKEN_RE = re.compile(f"{PLACEHOLDER_RE.pattern}|[A-Za-z]+(?:[-'][A-Za-z]+)?|\\d+|[\\u4e00-\\u9fff]")
META_TRANSLATION_PHRASES = (
    "translating ocr text",
    "i need to translate",
    "should i translate",
    "it's best to translate",
    "i'll aim to",
    "i will aim to",
    "the source repeats due to ocr",
    "likely with repeated clauses",
)
META_TRANSLATION_COMMENTARY_PHRASES = (
    "this feels like a good translation",
    "this is a good translation",
    "i'm wondering if",
    "i am wondering if",
    "should be translated to",
    "should be translated as",
    "keeping it succinct",
    "keeping it concise",
    "keeping the original meaning",
    "reflecting the essential ideas",
    "reflecting the original meaning",
    "the original meaning while making it clear",
    "to keep it",
    "should translate both",
    "i think it should",
    "evaluating ocr translation",
    "crafting readable duplication",
    "my focus is on getting",
    "conveys the meaning clearly",
    "practical translation",
    "despite the ocr mess",
    "balancing this with",
    "the instruction indicates",
    "for example, i might phrase it as",
    "i need to consider how to",
    "should i preserve this duplication",
    "which means",
    "without duplication",
    "it likely duplicates",
    "could also work",
    "for a policy context",
    "for consistency in publication style",
    "page number in the source",
    "translate only the heading",
    "which gives the title",
    "gives the title",
)
ADJACENT_DUPLICATE_MIN_CHARS = 12
ADJACENT_DUPLICATE_MAX_CHARS = 120
ADJACENT_DUPLICATE_MIN_TOKENS = 2
ADJACENT_DUPLICATE_MAX_TOKENS = 40
ADJACENT_DUPLICATE_TOKEN_MIN_CHARS = 4
ADJACENT_DUPLICATE_CLAUSE_MIN_CHARS = 4
ADJACENT_DUPLICATE_NOISE_GAP_MAX_CHARS = 48
ADJACENT_DUPLICATE_NOISE_GAP_MAX_TOKENS = 6
CLAUSE_SPLIT_RE = re.compile(r"[^\u3002\uff01\uff1f\uff1b.!?;\n]+[\u3002\uff01\uff1f\uff1b.!?;\n]?")
TITLE_META_REASONING_PHRASES = (
    "considering translation",
    "considering translation duplicates",
    "considering translation options",
    "evaluating translation options",
    "translating the title",
    "i need to consider",
    "i need to decide",
    "i should only translate",
    "i think i'll",
    "i think i will",
    "i'll think about",
    "i will think about",
    "sounds awkward",
    "it seems like",
    "it seems there",
    "it doesn't seem right",
    "preserve the duplication",
    "reflect the original text",
    "maintaining clarity",
    "faithful translation",
)
TITLE_SPLIT_RE = re.compile(r"(?:\r?\n)+|(?<=[.!?;:\u3002\uff01\uff1f\uff1b\uff1a])\s+|\*{2,}|[\"“”'‘’]+")
TITLE_TRAILING_CJK_RE = re.compile(r"([\u4e00-\u9fffA-Za-z0-9][\u4e00-\u9fffA-Za-z0-9 \-–—·:&/()]{1,80})\s*$")
TITLE_CJK_FRAGMENT_RE = re.compile(r"[\u4e00-\u9fff][\u4e00-\u9fffA-Za-z0-9 \-–—·:&/()]{1,80}")
TITLE_SOURCE_TERM_RE = re.compile(r"\b(?:[A-Z][A-Za-z0-9+-]*)(?:\s+[A-Z][A-Za-z0-9+-]*)*")
TITLE_MAX_CANDIDATE_CHARS = 96
SHORT_ENTRY_MAX_SOURCE_CHARS = 160
SHORT_ENTRY_MAX_CANDIDATE_CHARS = 160
SHORT_ENTRY_SPLIT_RE = re.compile(r"(?:\r?\n){2,}|[\"“”'‘’]")
SHORT_ENTRY_TRAILING_HEADING_RE = re.compile(
    r"((?:\d+(?:\.\d+)*\s+)?(?:L\d[:：]\s*)?[\u4e00-\u9fffA-Za-z][^\n]{0,140}? ?(?:\.\s*\.\s*\d+|\d)?)\s*$"
)


class SuspiciousKeepOriginError(ValueError):
    def __init__(self, item_id: str, result: dict[str, dict[str, str]]) -> None:
        super().__init__(f"{item_id}: suspicious keep_origin for long English body text")
        self.item_id = item_id
        self.result = result


class UnexpectedPlaceholderError(ValueError):
    def __init__(
        self,
        item_id: str,
        unexpected: list[str],
        *,
        source_text: str = "",
        translated_text: str = "",
    ) -> None:
        super().__init__(f"{item_id}: unexpected placeholders in translation: {unexpected}")
        self.item_id = item_id
        self.unexpected = unexpected
        self.source_text = source_text
        self.translated_text = translated_text


class PlaceholderInventoryError(ValueError):
    def __init__(
        self,
        item_id: str,
        source_sequence: list[str],
        translated_sequence: list[str],
        *,
        source_text: str = "",
        translated_text: str = "",
    ) -> None:
        super().__init__(
            f"{item_id}: placeholder inventory mismatch: source={source_sequence} translated={translated_sequence}"
        )
        self.item_id = item_id
        self.source_sequence = source_sequence
        self.translated_sequence = translated_sequence
        self.source_text = source_text
        self.translated_text = translated_text


class EmptyTranslationError(ValueError):
    def __init__(self, item_id: str) -> None:
        super().__init__(f"{item_id}: empty translation output")
        self.item_id = item_id


class EnglishResidueError(ValueError):
    def __init__(
        self,
        item_id: str,
        *,
        source_text: str = "",
        translated_text: str = "",
    ) -> None:
        super().__init__(f"{item_id}: translated output still looks predominantly English")
        self.item_id = item_id
        self.source_text = source_text
        self.translated_text = translated_text


class TranslationProtocolError(ValueError):
    def __init__(
        self,
        item_id: str,
        *,
        source_text: str = "",
        translated_text: str = "",
    ) -> None:
        super().__init__(f"{item_id}: translated output still contains protocol/json shell")
        self.item_id = item_id
        self.source_text = source_text
        self.translated_text = translated_text


def normalize_decision(value: str) -> str:
    normalized = (value or "translate").strip().lower().replace("-", "_")
    if normalized in {"keep", "skip", "no_translate", "keeporigin"}:
        return KEEP_ORIGIN_LABEL
    if normalized == KEEP_ORIGIN_LABEL:
        return KEEP_ORIGIN_LABEL
    return "translate"


def result_entry(decision: str, translated_text: str) -> dict[str, str]:
    normalized_decision = normalize_decision(decision)
    payload = {
        "decision": normalized_decision,
        "translated_text": "" if normalized_decision == KEEP_ORIGIN_LABEL else (translated_text or "").strip(),
    }
    payload["final_status"] = "kept_origin" if normalized_decision == KEEP_ORIGIN_LABEL else "translated"
    return payload


def internal_keep_origin_result(reason: str) -> dict[str, str]:
    result = result_entry(KEEP_ORIGIN_LABEL, "")
    result["_internal_reason"] = reason
    return result


def is_internal_keep_origin_degraded(payload: dict[str, str]) -> bool:
    return bool(str(payload.get("_internal_reason", "") or "").strip())


def is_internal_placeholder_degraded(payload: dict[str, str]) -> bool:
    return str(payload.get("_internal_reason", "") or "") == INTERNAL_PLACEHOLDER_DEGRADED_REASON


def normalize_inline_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def text_preview(text: str, *, limit: int = 220) -> str:
    normalized = normalize_inline_whitespace(text)
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: max(0, limit - 1)].rstrip()}…"


def unit_source_text(item: dict) -> str:
    return (
        item.get("translation_unit_protected_source_text")
        or item.get("group_protected_source_text")
        or item.get("protected_source_text")
        or item.get("source_text")
        or ""
    )


def strip_placeholders(text: str) -> str:
    return PLACEHOLDER_RE.sub(" ", text or "")


def placeholders(text: str) -> set[str]:
    return set(PLACEHOLDER_RE.findall(text or ""))


def placeholder_sequence(text: str) -> list[str]:
    return PLACEHOLDER_RE.findall(text or "")


def repair_safe_duplicate_placeholders(source_text: str, translated_text: str) -> str | None:
    source_sequence = placeholder_sequence(source_text)
    if not source_sequence:
        return None
    matches = list(PLACEHOLDER_RE.finditer(translated_text or ""))
    if not matches:
        return None
    translated_sequence = [match.group(0) for match in matches]
    if translated_sequence == source_sequence or len(translated_sequence) <= len(source_sequence):
        return None
    source_inventory = Counter(source_sequence)
    translated_inventory = Counter(translated_sequence)
    for placeholder, count in translated_inventory.items():
        if count < source_inventory.get(placeholder, 0):
            return None
    if any(placeholder not in source_inventory for placeholder in translated_inventory):
        return None

    kept_match_indexes: list[int] = []
    cursor = 0
    for placeholder in source_sequence:
        while cursor < len(translated_sequence) and translated_sequence[cursor] != placeholder:
            cursor += 1
        if cursor >= len(translated_sequence):
            return None
        kept_match_indexes.append(cursor)
        cursor += 1

    if len(kept_match_indexes) == len(matches):
        return None

    keep_set = set(kept_match_indexes)
    rebuilt_parts: list[str] = []
    prev_end = 0
    for index, match in enumerate(matches):
        rebuilt_parts.append(translated_text[prev_end:match.start()])
        if index in keep_set:
            rebuilt_parts.append(match.group(0))
        prev_end = match.end()
    rebuilt_parts.append(translated_text[prev_end:])

    repaired_text = "".join(rebuilt_parts)
    repaired_text = re.sub(r"[ \t]{2,}", " ", repaired_text)
    repaired_text = re.sub(r"\s+([,.;:!?])", r"\1", repaired_text)
    if placeholder_sequence(repaired_text) != source_sequence:
        return None
    return repaired_text.strip()


def has_formula_placeholders(item: dict) -> bool:
    return bool(FORMULA_TOKEN_RE.findall(unit_source_text(item)))


def placeholder_alias_maps(item: dict) -> tuple[dict[str, str], dict[str, str]]:
    source_sequence = placeholder_sequence(unit_source_text(item))
    source_set = set(source_sequence)
    original_to_alias: dict[str, str] = {}
    alias_to_original: dict[str, str] = {}
    next_alias_id = 1
    for placeholder in dict.fromkeys(source_sequence):
        alias = f"@@P{next_alias_id}@@"
        while alias in source_set or alias in alias_to_original:
            next_alias_id += 1
            alias = f"@@P{next_alias_id}@@"
        original_to_alias[placeholder] = alias
        alias_to_original[alias] = placeholder
        next_alias_id += 1
    return original_to_alias, alias_to_original


def item_with_runtime_hard_glossary(item: dict, glossary_entries: list[dict] | list[object] | None) -> dict:
    normalized_map = list(item.get("translation_unit_protected_map") or item.get("protected_map") or [])
    if not normalized_map and item.get("translation_unit_formula_map"):
        normalized_map = protected_map_from_formula_map(item.get("translation_unit_formula_map") or [])
    elif not normalized_map and item.get("formula_map"):
        normalized_map = protected_map_from_formula_map(item.get("formula_map") or [])
    protected_text, protected_map = protect_glossary_terms(
        unit_source_text(item),
        glossary_entries=glossary_entries,
        existing_map=normalized_map,
    )
    if protected_text == unit_source_text(item) and protected_map == normalized_map:
        return dict(item)
    updated = dict(item)
    updated["translation_unit_protected_source_text"] = protected_text
    updated["protected_source_text"] = protected_text
    updated["translation_unit_protected_map"] = protected_map
    updated["protected_map"] = protected_map
    return updated


def replace_placeholders(text: str, mapping: dict[str, str]) -> str:
    replaced = text or ""
    for source, target in mapping.items():
        replaced = replaced.replace(source, target)
    return replaced


def item_with_placeholder_aliases(item: dict, mapping: dict[str, str]) -> dict:
    aliased = dict(item)
    for key in (
        "source_text",
        "protected_source_text",
        "mixed_original_protected_source_text",
        "translation_unit_protected_source_text",
        "group_protected_source_text",
    ):
        if key in aliased and aliased.get(key):
            aliased[key] = replace_placeholders(str(aliased.get(key) or ""), mapping)
    return aliased


def restore_placeholder_aliases(
    result: dict[str, dict[str, str]],
    mapping: dict[str, str],
) -> dict[str, dict[str, str]]:
    restored: dict[str, dict[str, str]] = {}
    for item_id, payload in result.items():
        translated_text = replace_placeholders(str(payload.get("translated_text", "") or ""), mapping)
        restored_payload = result_entry(str(payload.get("decision", "translate") or "translate"), translated_text)
        if payload.get("final_status"):
            restored_payload["final_status"] = str(payload.get("final_status", "") or restored_payload["final_status"])
        restored[item_id] = restored_payload
    return restored


def placeholder_stability_guidance(item: dict, source_sequence: list[str]) -> str:
    if not source_sequence:
        return ""
    return (
        "Placeholder safety rules for this item:\n"
        f"- Allowed placeholders exactly: {', '.join(source_sequence)}\n"
        f"- Placeholder sequence in source_text: {' -> '.join(source_sequence)}\n"
        "- Keep placeholders as atomic tokens.\n"
        "- Do not invent, renumber, duplicate, omit, split, or reorder placeholders.\n"
        "- If a placeholder stands for a whole formula or expression, keep that placeholder as one unit."
    )


def looks_like_english_prose(text: str) -> bool:
    cleaned = strip_placeholders(text).strip()
    if not cleaned:
        return False
    if looks_like_code_literal_text_value(cleaned):
        return False
    if "@" in cleaned or "http://" in cleaned or "https://" in cleaned or looks_like_url_fragment(cleaned):
        return False
    if looks_like_reference_entry_text(cleaned):
        return False
    words = EN_WORD_RE.findall(cleaned)
    if len(words) < 8:
        return False
    alpha_chars = sum(ch.isalpha() for ch in cleaned)
    if alpha_chars < 30:
        return False
    return True


def _english_word_count(text: str) -> int:
    return len(EN_WORD_RE.findall(strip_placeholders(text)))


def _zh_char_count(text: str) -> int:
    return sum(1 for ch in strip_placeholders(text) if "\u4e00" <= ch <= "\u9fff")


def _strip_translation_meta_preamble(text: str) -> str:
    translated = str(text or "").strip()
    if not translated:
        return translated
    first_zh_index = next((idx for idx, ch in enumerate(translated) if "\u4e00" <= ch <= "\u9fff"), -1)
    if first_zh_index <= 0:
        return translated
    prefix = normalize_inline_whitespace(translated[:first_zh_index]).lower()
    if not prefix:
        return translated
    if not any(phrase in prefix for phrase in META_TRANSLATION_PHRASES):
        return translated
    stripped = translated[first_zh_index:].lstrip()
    return stripped or translated


def _looks_like_translation_commentary_fragment(text: str) -> bool:
    normalized = normalize_inline_whitespace(str(text or "")).strip()
    if not normalized:
        return False
    lowered = normalized.lower()
    if not any(
        phrase in lowered
        for phrase in META_TRANSLATION_PHRASES + META_TRANSLATION_COMMENTARY_PHRASES
    ):
        return False
    english_words = re.findall(r"[A-Za-z]{2,}", normalized)
    if len(english_words) < 4:
        return False
    chinese_chars = sum(1 for ch in normalized if "\u4e00" <= ch <= "\u9fff")
    return len(english_words) >= max(4, chinese_chars)


def _contains_meta_reasoning_signal(text: str) -> bool:
    normalized = normalize_inline_whitespace(str(text or "")).strip()
    if not normalized:
        return False
    lowered = normalized.lower()
    if any(
        phrase in lowered
        for phrase in META_TRANSLATION_PHRASES + META_TRANSLATION_COMMENTARY_PHRASES + TITLE_META_REASONING_PHRASES
    ):
        return True
    if not re.search(r"\b(i|maybe|perhaps|still|sounds)\b|i'll|i'm|i am|i will|which means|it likely", lowered):
        return False
    return bool(
        re.search(
            r"\b(translate|translation|title|phrasing|ocr|duplicate|duplicated|preserve|reflect|clarity|awkward|decide|consider)\b",
            lowered,
        )
    )


def _strip_translation_commentary_fragments(text: str) -> str:
    raw = str(text or "")
    if not raw.strip():
        return raw

    fragments = CLAUSE_SPLIT_RE.findall(raw)
    if not fragments:
        return raw

    kept: list[str] = []
    removed = False
    for fragment in fragments:
        if _looks_like_translation_commentary_fragment(fragment):
            removed = True
            continue
        kept.append(fragment)

    if not removed:
        return raw

    cleaned = "".join(kept).strip()
    return cleaned or raw


def _is_title_structure_role(item: dict) -> bool:
    return str((item.get("metadata", {}) or {}).get("structure_role", "") or "").strip().lower() == "title"


def _clean_title_recovery_candidate(text: str) -> str:
    cleaned = normalize_inline_whitespace(str(text or "")).strip(" \t\r\n\"'“”‘’`*_#:-–—;,.!?")
    for _ in range(3):
        if not cleaned or not re.search(r"[\u4e00-\u9fff]", cleaned):
            break
        match = re.match(r"^(?P<prefix>[A-Za-z]+(?:\s+[A-Za-z]+){0,8})\s+(?=.*[\u4e00-\u9fff])", cleaned)
        if not match:
            break
        prefix = (match.group("prefix") or "").strip().lower()
        if not re.match(
            r"^(considering|evaluating|translating|keeping|preserving|reflecting|maintaining|thinking|sounds|maybe|still|so|i|it|this|that|the|should|need)\b",
            prefix,
        ):
            break
        cleaned = cleaned[match.end("prefix") :].lstrip(" \t\r\n\"'“”‘’`*_#:-–—;,.!?")
    cleaned = re.sub(r"^[\"“”'‘’]+\s*", "", cleaned)
    cleaned = re.sub(r"\s*[\"“”'‘’]+$", "", cleaned)
    return cleaned.strip(" \t\r\n\"'“”‘’`*_#:-–—;,.!?")


def _is_short_translation_unit(item: dict) -> bool:
    source = normalize_inline_whitespace(unit_source_text(item))
    return bool(source) and len(source) <= SHORT_ENTRY_MAX_SOURCE_CHARS


def _clean_short_entry_candidate(text: str) -> str:
    cleaned = normalize_inline_whitespace(str(text or ""))
    cleaned = re.sub(r"^[A-Za-z][A-Za-z .!?:;-]{0,24}(?=\d)", "", cleaned)
    cleaned = re.sub(r"^[A-Za-z][A-Za-z .!?:;-]{0,24}(?=[\u4e00-\u9fff])", "", cleaned)
    return cleaned.strip(" \t\r\n\"'“”‘’`*_#:-–—;,.!?")


def _short_entry_candidate_score(source_text: str, text: str) -> int:
    normalized = normalize_inline_whitespace(text)
    if not normalized or len(normalized) > SHORT_ENTRY_MAX_CANDIDATE_CHARS:
        return -10_000
    zh_chars = _zh_char_count(normalized)
    english_words = _english_word_count(normalized)
    digits = sum(ch.isdigit() for ch in normalized)
    if zh_chars == 0 and digits == 0:
        return -10_000
    if _contains_meta_reasoning_signal(normalized) and english_words >= 4:
        return -8_000
    if zh_chars >= 4 and english_words >= 5 and len(normalized) > len(source_text) + 8:
        return -7_000
    score = zh_chars * 8 + digits * 2 - english_words * 3 - max(0, len(normalized) - len(source_text) - 16)
    source_prefix = re.match(r"^\d+(?:\.\d+)*", source_text)
    if source_prefix and normalized.startswith(source_prefix.group(0)):
        score += 40
    if ". ." in normalized or re.search(r"\.\s*\.\s*\d+$", normalized):
        score += 10
    return score


def _recover_short_entry_from_meta_reasoning(item: dict, text: str) -> str:
    raw = str(text or "").strip()
    source = normalize_inline_whitespace(unit_source_text(item))
    if not raw or not source or not _is_short_translation_unit(item):
        return raw
    if _zh_char_count(raw) == 0:
        return raw
    if not (_contains_meta_reasoning_signal(raw) or (_english_word_count(raw) >= 10 and len(raw) > len(source) + 24)):
        return raw

    candidates = [raw]
    candidates.extend(part for part in SHORT_ENTRY_SPLIT_RE.split(raw) if part and part.strip())
    candidates.extend(
        match.group(0)
        for match in re.finditer(
            r"(?:(?<=^)|(?<=[\"'“”‘’]))((?:\d+(?:\.\d+)*\s+)?(?:L\d[:ㄩ]\s*)?[\u4e00-\u9fffA-Za-z][^\n\"'“”‘’]{0,140}?(?:\.\s*\.\s*\d+|\d)?)(?=$|(?=[\"'“”‘’]))",
            raw,
        )
    )
    clean_split_candidates = []
    for candidate in candidates[1:]:
        cleaned = _clean_short_entry_candidate(candidate)
        if (
            _zh_char_count(cleaned) >= 2
            and _english_word_count(cleaned) <= 3
            and not _contains_meta_reasoning_signal(cleaned)
        ):
            clean_split_candidates.append(cleaned)
    if clean_split_candidates:
        best_clean = max(clean_split_candidates, key=lambda value: _short_entry_candidate_score(source, value))
        if _short_entry_candidate_score(source, best_clean) > -500:
            return best_clean
    trailing = SHORT_ENTRY_TRAILING_HEADING_RE.search(raw)
    if trailing:
        candidates.append(trailing.group(1))

    best = raw
    best_score = -10_000
    for candidate in candidates:
        cleaned = _clean_short_entry_candidate(candidate)
        score = _short_entry_candidate_score(source, cleaned)
        if score > best_score:
            best = cleaned
            best_score = score
    return best if best_score > -1_000 else raw


def _title_candidate_score(text: str) -> int:
    normalized = normalize_inline_whitespace(text)
    if not normalized:
        return -10_000
    zh_chars = _zh_char_count(normalized)
    english_words = _english_word_count(normalized)
    if zh_chars < 2 or len(normalized) > TITLE_MAX_CANDIDATE_CHARS:
        return -10_000
    if _contains_meta_reasoning_signal(normalized) and english_words > 4:
        return -5_000
    return zh_chars * 10 - english_words * 4 - max(0, len(normalized) - 40)


def _recover_title_from_meta_reasoning(text: str) -> str:
    raw = str(text or "").strip()
    if not raw or _zh_char_count(raw) == 0:
        return raw
    if not (_contains_meta_reasoning_signal(raw) or _english_word_count(raw) >= 6):
        return raw

    candidates = [raw]
    candidates.extend(TITLE_SPLIT_RE.split(raw))
    candidates.extend(match.group(0) for match in TITLE_CJK_FRAGMENT_RE.finditer(raw))
    clean_split_candidates = []
    for candidate in candidates[1:]:
        cleaned = _clean_title_recovery_candidate(candidate)
        if (
            _zh_char_count(cleaned) >= 2
            and _english_word_count(cleaned) <= 3
            and not _contains_meta_reasoning_signal(cleaned)
        ):
            clean_split_candidates.append(cleaned)
    if clean_split_candidates:
        best_clean = max(clean_split_candidates, key=_title_candidate_score)
        if _title_candidate_score(best_clean) > -500:
            return best_clean
    trailing = TITLE_TRAILING_CJK_RE.search(raw)
    if trailing:
        candidates.append(trailing.group(1))

    best = raw
    best_score = -10_000
    for candidate in candidates:
        cleaned = _clean_title_recovery_candidate(candidate)
        score = _title_candidate_score(cleaned)
        if score > best_score:
            best = cleaned
            best_score = score
    return best if best_score > -1_000 else raw


def _prepend_missing_title_source_context(item: dict, translated_text: str) -> str:
    title = normalize_inline_whitespace(translated_text)
    if not title.startswith(("的", "与", "及", "和")):
        return translated_text

    source = normalize_inline_whitespace(unit_source_text(item))
    if not source:
        return translated_text

    candidates: list[str] = []
    for match in TITLE_SOURCE_TERM_RE.finditer(source):
        candidate = re.sub(r"^(?:Main|The|A|An)\s+", "", match.group(0)).strip()
        if not candidate:
            continue
        if candidate.lower() in {"main", "the", "a", "an"}:
            continue
        if candidate in title:
            continue
        candidates.append(candidate)

    if not candidates:
        return translated_text

    best = max(candidates, key=lambda value: (len(value.split()), len(value)))
    return f"{best} {title}".strip()


def _strip_leading_short_entry_garbage(item: dict, translated_text: str) -> str:
    if not (_is_title_structure_role(item) or _is_short_translation_unit(item)):
        return translated_text
    cleaned = normalize_inline_whitespace(translated_text)
    source = normalize_inline_whitespace(unit_source_text(item))
    source_prefix = re.match(r"^\d+(?:\.\d+)*", source)
    if source_prefix:
        index = cleaned.find(source_prefix.group(0))
        if 0 < index <= 24 and re.fullmatch(r"[A-Za-z .!?:;\-]+", cleaned[:index]):
            cleaned = cleaned[index:]
    first_cjk = next((idx for idx, ch in enumerate(cleaned) if "\u4e00" <= ch <= "\u9fff"), -1)
    if 0 < first_cjk <= 24 and re.fullmatch(r"[A-Za-z .!?:;\-0-9]+", cleaned[:first_cjk]):
        cleaned = cleaned[first_cjk:]
    return cleaned.strip()


def _prepend_missing_title_source_context(item: dict, translated_text: str) -> str:
    title = normalize_inline_whitespace(translated_text)
    source = normalize_inline_whitespace(unit_source_text(item))
    if not source or not title:
        return translated_text

    should_prepend = title.startswith(("\u7684", "\u4e0e", "\u53ca", "\u548c"))

    candidates: list[str] = []
    for match in TITLE_SOURCE_TERM_RE.finditer(source):
        candidate = re.sub(r"^(?:Main|The|A|An)\s+", "", match.group(0)).strip()
        if not candidate:
            continue
        if candidate.lower() in {"main", "the", "a", "an"}:
            continue
        if candidate in title:
            continue
        candidates.append(candidate)

    if not candidates:
        return translated_text

    best = max(candidates, key=lambda value: (len(value.split()), len(value)))
    if not should_prepend:
        should_prepend = (
            _zh_char_count(title) >= 2
            and _zh_char_count(title) <= 8
            and _english_word_count(title) <= 3
            and len(title) <= 16
            and len(best.split()) >= 2
        )
    if not should_prepend:
        return translated_text
    return f"{best} {title}".strip()


def _strip_leading_short_entry_garbage(item: dict, translated_text: str) -> str:
    if not (_is_title_structure_role(item) or _is_short_translation_unit(item)):
        return translated_text
    cleaned = normalize_inline_whitespace(translated_text)
    source = normalize_inline_whitespace(unit_source_text(item))
    source_prefix = re.match(r"^\d+(?:\.\d+)*", source)
    if source_prefix:
        index = cleaned.find(source_prefix.group(0))
        if 0 < index <= 24 and re.fullmatch(r"[A-Za-z .!?:;\-]+", cleaned[:index]):
            cleaned = cleaned[index:]
    first_cjk = next((idx for idx, ch in enumerate(cleaned) if "\u4e00" <= ch <= "\u9fff"), -1)
    if (
        source_prefix is None
        and 0 < first_cjk <= 24
        and re.fullmatch(r"[a-z .!?:;\-0-9]+", cleaned[:first_cjk])
    ):
        cleaned = cleaned[first_cjk:]
    return cleaned.strip()


def _collapse_adjacent_duplicate_clauses(text: str) -> str:
    translated = str(text or "").strip()
    if not translated:
        return translated
    clauses = [clause for clause in CLAUSE_SPLIT_RE.findall(translated) if clause.strip()]
    if len(clauses) < 2:
        return translated

    collapsed = list(clauses)
    changed = True
    while changed:
        changed = False
        next_clauses: list[str] = []
        index = 0
        while index < len(collapsed):
            current = collapsed[index]
            current_key = normalize_inline_whitespace(current)
            if (
                index + 1 < len(collapsed)
                and len(strip_placeholders(current_key)) >= ADJACENT_DUPLICATE_CLAUSE_MIN_CHARS
                and current_key
                and current_key == normalize_inline_whitespace(collapsed[index + 1])
            ):
                next_clauses.append(current)
                index += 2
                changed = True
                continue
            next_clauses.append(current)
            index += 1
        collapsed = next_clauses
    if len(collapsed) == len(clauses):
        return translated
    return "".join(collapsed).strip()


def _collapse_adjacent_duplicate_spans(text: str) -> str:
    translated = str(text or "").strip()
    if not translated:
        return translated
    collapsed = translated
    changed = True
    while changed:
        changed = False
        index = 0
        pieces: list[str] = []
        while index < len(collapsed):
            matched = False
            max_window = min(ADJACENT_DUPLICATE_MAX_CHARS, (len(collapsed) - index) // 2)
            for window in range(max_window, ADJACENT_DUPLICATE_MIN_CHARS - 1, -1):
                left = collapsed[index : index + window]
                if not left.strip():
                    continue
                join = index + window
                while join < len(collapsed) and collapsed[join].isspace():
                    join += 1
                right = collapsed[join : join + window]
                if normalize_inline_whitespace(left) != normalize_inline_whitespace(right):
                    continue
                pieces.append(left)
                index = join + window
                changed = True
                matched = True
                break
            if matched:
                continue
            pieces.append(collapsed[index])
            index += 1
        collapsed = "".join(pieces)
    return collapsed.strip()


def _dedup_token_key(token: str) -> str:
    return token.lower() if EN_WORD_RE.fullmatch(token or "") else token


def _looks_like_duplicate_noise_gap(text: str) -> bool:
    normalized = normalize_inline_whitespace(text)
    if not normalized:
        return True
    if len(normalized) > ADJACENT_DUPLICATE_NOISE_GAP_MAX_CHARS:
        return False
    lowered = normalized.lower()
    if any(
        phrase in lowered
        for phrase in META_TRANSLATION_PHRASES + META_TRANSLATION_COMMENTARY_PHRASES
    ):
        return True
    if re.fullmatch(r"[\s\"'“”‘’`~.,;:!?()\[\]{}<>/\\|_-]+", normalized):
        return True
    english_words = EN_WORD_RE.findall(normalized)
    if not english_words:
        return False
    return len(english_words) <= 6 and len(re.sub(r"[A-Za-z\s]", "", normalized)) <= 8


def _collapse_adjacent_duplicate_token_runs(text: str) -> str:
    collapsed = str(text or "").strip()
    if not collapsed:
        return collapsed

    changed = True
    while changed:
        changed = False
        tokens = [
            (match.start(), match.end(), _dedup_token_key(match.group(0)))
            for match in DEDUP_TOKEN_RE.finditer(collapsed)
        ]
        if len(tokens) < ADJACENT_DUPLICATE_MIN_TOKENS * 2:
            break

        pieces: list[str] = []
        char_cursor = 0
        index = 0
        while index < len(tokens):
            matched = False
            max_window = min(ADJACENT_DUPLICATE_MAX_TOKENS, (len(tokens) - index) // 2)
            for window in range(max_window, ADJACENT_DUPLICATE_MIN_TOKENS - 1, -1):
                left = tokens[index : index + window]
                duplicated_chars = sum(end - start for start, end, _token in left)
                if duplicated_chars < ADJACENT_DUPLICATE_TOKEN_MIN_CHARS:
                    continue
                max_gap_tokens = min(
                    ADJACENT_DUPLICATE_NOISE_GAP_MAX_TOKENS,
                    len(tokens) - index - window * 2,
                )
                for gap_tokens in range(0, max_gap_tokens + 1):
                    right_start_index = index + window + gap_tokens
                    right_end_index = right_start_index + window
                    right = tokens[right_start_index:right_end_index]
                    if len(right) != window:
                        continue
                    if [token for _start, _end, token in left] != [token for _start, _end, token in right]:
                        continue
                    left_end = left[-1][1]
                    right_start = right[0][0]
                    gap = collapsed[left_end:right_start]
                    if gap and not _looks_like_duplicate_noise_gap(gap):
                        continue
                    pieces.append(collapsed[char_cursor:left_end])
                    char_cursor = right[-1][1]
                    index = right_end_index
                    matched = True
                    changed = True
                    break
                if matched:
                    break
            if matched:
                continue
            index += 1

        if changed:
            pieces.append(collapsed[char_cursor:])
            collapsed = "".join(pieces).strip()
    return collapsed


def _leading_english_word_count(text: str) -> int:
    cleaned = strip_placeholders(text or "")
    if not cleaned.strip():
        return 0
    count = 0
    for token in re.findall(r"[A-Za-z]+(?:[-'][A-Za-z]+)?|[\u4e00-\u9fff]+|[^\s]", cleaned):
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            break
        if EN_WORD_RE.fullmatch(token):
            count += 1
            continue
        if token.isspace():
            continue
        if token in {'"', "'", "(", ")", "[", "]", "{", "}", ",", ".", ";", ":", "!", "?", "-", "/"}:
            continue
        if count > 0:
            break
    return count


def looks_like_untranslated_english_output(item: dict, translated_text: str) -> bool:
    source_text = unit_source_text(item).strip()
    translated = str(translated_text or "").strip()
    if not translated:
        return False
    if not should_force_translate_body_text(item):
        return False
    if not looks_like_english_prose(source_text):
        return False
    english_words = _english_word_count(translated)
    zh_chars = _zh_char_count(translated)
    leading_english_words = _leading_english_word_count(translated)
    if english_words < 12:
        return leading_english_words >= 12 and zh_chars > 0
    if zh_chars == 0:
        return True
    if leading_english_words >= 12:
        return True
    return english_words >= max(12, zh_chars // 2)


def looks_like_short_fragment(text: str) -> bool:
    stripped = text.strip()
    if not stripped or " " in stripped:
        return False
    return bool(SHORT_FRAGMENT_RE.fullmatch(stripped))


def looks_like_garbled_fragment(text: str) -> bool:
    cleaned = strip_placeholders(text).strip()
    if not cleaned:
        return True
    if "\ufffd" in cleaned:
        return True
    visible = [ch for ch in cleaned if not ch.isspace()]
    if not visible:
        return True
    weird = sum(1 for ch in visible if not (ch.isalnum() or ch in ".,;:!?()[]{}'\"-_/+*&%$#=@"))
    return weird / max(1, len(visible)) > 0.35


def should_force_translate_body_text(item: dict) -> bool:
    source_text = unit_source_text(item).strip()
    if not source_text:
        return False
    if looks_like_code_literal_text_value(source_text):
        return False
    if looks_like_reference_entry_text(source_text):
        return False
    if looks_like_garbled_fragment(source_text):
        return False
    if looks_like_short_fragment(source_text):
        return False
    if str(item.get("block_type", "") or "") != "text":
        return False
    if not is_body_structure_role(item.get("metadata", {}) or {}):
        return False
    words = EN_WORD_RE.findall(strip_placeholders(source_text))
    if item.get("continuation_group"):
        return len(words) >= 6 and looks_like_english_prose(source_text)
    if item.get("block_type") == "text" and bool(item.get("formula_map") or item.get("translation_unit_formula_map")):
        return len(words) >= 5 and looks_like_english_prose(source_text)
    return looks_like_english_prose(source_text) and len(words) >= 8


def should_reject_keep_origin(item: dict, decision: str, payload: dict[str, str] | None = None) -> bool:
    if decision != KEEP_ORIGIN_LABEL:
        return False
    if payload and is_internal_keep_origin_degraded(payload):
        return False
    block_type = item.get("block_type")
    if block_type not in {"", None, "text"}:
        return False
    return should_force_translate_body_text(item)


def canonicalize_batch_result(batch: list[dict], result: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    batch_items = {str(item.get("item_id", "") or ""): item for item in batch}
    canonical: dict[str, dict[str, str]] = {}
    for item_id, payload in result.items():
        item = batch_items.get(item_id)
        decision = normalize_decision(str(payload.get("decision", "translate") or "translate"))
        translated_text = unwrap_translation_shell(str(payload.get("translated_text", "") or "").strip(), item_id=item_id)
        if item is not None:
            source_text = unit_source_text(item).strip()
            if decision != KEEP_ORIGIN_LABEL and translated_text:
                translated_text = _strip_translation_meta_preamble(translated_text)
                translated_text = _strip_translation_commentary_fragments(translated_text)
                repaired_text = repair_safe_duplicate_placeholders(source_text, translated_text)
                if repaired_text is not None:
                    translated_text = repaired_text
                translated_text = _collapse_adjacent_duplicate_spans(translated_text)
                translated_text = _collapse_adjacent_duplicate_token_runs(translated_text)
                translated_text = _collapse_adjacent_duplicate_clauses(translated_text)
                translated_text = _recover_short_entry_from_meta_reasoning(item, translated_text)
                if _is_title_structure_role(item):
                    translated_text = _recover_title_from_meta_reasoning(translated_text)
                    translated_text = _prepend_missing_title_source_context(item, translated_text)
                translated_text = _strip_leading_short_entry_garbage(item, translated_text)
            if (
                decision != KEEP_ORIGIN_LABEL
                and translated_text
                and translated_text == source_text
                and not should_force_translate_body_text(item)
            ):
                decision = KEEP_ORIGIN_LABEL
                translated_text = ""
        canonical[item_id] = result_entry(decision, translated_text)
        if isinstance(payload, dict) and payload.get("final_status"):
            canonical[item_id]["final_status"] = str(payload.get("final_status", "") or canonical[item_id]["final_status"])
    return canonical


def looks_like_protocol_shell_output(translated_text: str) -> bool:
    text = str(translated_text or "").strip()
    if not text or not text.startswith("{"):
        return False
    return (
        '"translated_text"' in text
        or '"translations"' in text
        or "“translated_text”" in text
        or "“translations”" in text
    )


def validate_batch_result(
    batch: list[dict],
    result: dict[str, dict[str, str]],
    *,
    diagnostics: TranslationDiagnosticsCollector | None = None,
) -> None:
    expected_ids = {item["item_id"] for item in batch}
    actual_ids = set(result)
    if actual_ids != expected_ids:
        missing = sorted(expected_ids - actual_ids)
        extra = sorted(actual_ids - expected_ids)
        raise ValueError(f"translation item_id mismatch: missing={missing} extra={extra}")

    for item in batch:
        item_id = item["item_id"]
        source_text = unit_source_text(item)
        translated_result = result.get(item_id, {})
        translated_text = translated_result.get("translated_text", "")
        decision = normalize_decision(translated_result.get("decision", "translate"))
        if should_reject_keep_origin(item, decision, translated_result):
            if diagnostics is not None:
                diagnostics.emit(
                    kind="keep_origin_degraded",
                    item_id=item_id,
                    page_idx=item.get("page_idx"),
                    severity="warning",
                    message="Suspicious keep_origin for long English body text",
                    retryable=True,
                )
            raise SuspiciousKeepOriginError(item_id, result)
        if decision == KEEP_ORIGIN_LABEL:
            continue
        if not translated_text.strip():
            if diagnostics is not None:
                diagnostics.emit(
                    kind="empty_translation",
                    item_id=item_id,
                    page_idx=item.get("page_idx"),
                    severity="error",
                    message="Empty translation output",
                    retryable=True,
                )
            raise EmptyTranslationError(item_id)
        if looks_like_protocol_shell_output(translated_text):
            if diagnostics is not None:
                diagnostics.emit(
                    kind="protocol_shell_output",
                    item_id=item_id,
                    page_idx=item.get("page_idx"),
                    severity="error",
                    message="Translated output still contains JSON/protocol shell",
                    retryable=True,
                )
            raise TranslationProtocolError(
                item_id,
                source_text=source_text,
                translated_text=translated_text,
            )
        if looks_like_untranslated_english_output(item, translated_text):
            if diagnostics is not None:
                diagnostics.emit(
                    kind="english_residue",
                    item_id=item_id,
                    page_idx=item.get("page_idx"),
                    severity="error",
                    message="Translated output still looks predominantly English",
                    retryable=True,
                )
            raise EnglishResidueError(
                item_id,
                source_text=source_text,
                translated_text=translated_text,
            )
        source_placeholders = placeholders(source_text)
        translated_placeholders = placeholders(translated_text)
        if not translated_placeholders.issubset(source_placeholders):
            unexpected = sorted(translated_placeholders - source_placeholders)
            if diagnostics is not None:
                diagnostics.emit(
                    kind="unexpected_placeholder",
                    item_id=item_id,
                    page_idx=item.get("page_idx"),
                    severity="error",
                    message=f"Unexpected placeholders: {unexpected}",
                    retryable=True,
                    details={"unexpected": unexpected},
                )
            raise UnexpectedPlaceholderError(
                item_id,
                unexpected,
                source_text=source_text,
                translated_text=translated_text,
            )
        source_sequence = placeholder_sequence(source_text)
        translated_sequence = placeholder_sequence(translated_text)
        if Counter(translated_sequence) != Counter(source_sequence):
            if diagnostics is not None:
                diagnostics.emit(
                    kind="placeholder_inventory_mismatch",
                    item_id=item_id,
                    page_idx=item.get("page_idx"),
                    severity="error",
                    message="Placeholder inventory mismatch",
                    retryable=True,
                    details={
                        "source_sequence": source_sequence,
                        "translated_sequence": translated_sequence,
                    },
                )
            raise PlaceholderInventoryError(
                item_id,
                source_sequence,
                translated_sequence,
                source_text=source_text,
                translated_text=translated_text,
            )
        if translated_sequence != source_sequence and diagnostics is not None:
            diagnostics.emit(
                kind="placeholder_order_changed",
                item_id=item_id,
                page_idx=item.get("page_idx"),
                severity="warning",
                message="Protected token order changed but inventory is preserved",
                retryable=False,
                details={
                    "source_sequence": source_sequence,
                    "translated_sequence": translated_sequence,
                },
            )
        if translated_text.strip() == source_text.strip():
            if looks_like_url_fragment(source_text):
                continue
            if looks_like_reference_entry_text(source_text):
                continue
            if looks_like_code_literal_text_value(source_text):
                continue
            if looks_like_english_prose(source_text):
                continue


def log_placeholder_failure(
    request_label: str,
    item: dict,
    exc: Exception,
    *,
    diagnostics: TranslationDiagnosticsCollector | None = None,
) -> None:
    source_text = getattr(exc, "source_text", "") or unit_source_text(item)
    translated_text = getattr(exc, "translated_text", "") or ""
    source_seq = getattr(exc, "source_sequence", None)
    translated_seq = getattr(exc, "translated_sequence", None)
    unexpected = getattr(exc, "unexpected", None)
    if diagnostics is not None:
        kind = "placeholder_unstable"
        if isinstance(exc, UnexpectedPlaceholderError):
            kind = "unexpected_placeholder"
        elif isinstance(exc, PlaceholderInventoryError):
            kind = "placeholder_inventory_mismatch"
        diagnostics.emit(
            kind=kind,
            item_id=str(item.get("item_id", "") or ""),
            page_idx=item.get("page_idx"),
            severity="error",
            message=str(exc),
            retryable=True,
            details={
                "source_sequence": source_seq or [],
                "translated_sequence": translated_seq or [],
                "unexpected": unexpected or [],
            },
        )
    print(
        f"{request_label}: placeholder diagnostic item={item.get('item_id','')} block_type={item.get('block_type','')}",
        flush=True,
    )
    print(f"{request_label}: source preview: {text_preview(source_text)}", flush=True)
    if translated_text:
        print(f"{request_label}: translated preview: {text_preview(translated_text)}", flush=True)
    if unexpected:
        print(f"{request_label}: unexpected placeholders: {unexpected}", flush=True)
    if source_seq is not None or translated_seq is not None:
        print(
            f"{request_label}: placeholder seq source={source_seq or []} translated={translated_seq or []}",
            flush=True,
        )
