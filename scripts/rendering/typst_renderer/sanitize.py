from __future__ import annotations

import json
import os
from pathlib import Path

from config import fonts
from rendering.typst_renderer.compiler import compile_typst_overlay_pdf
from rendering.typst_renderer.shared import TYPST_OVERLAY_DIR
from rendering.typst_renderer.shared import force_plain_text_item_at_index
from rendering.typst_renderer.shared import force_plain_text_items
from rendering.typst_renderer.shared import strip_formula_commands_for_item_at_index
from translation.llm.deepseek_client import DEFAULT_BASE_URL
from translation.llm.deepseek_client import extract_json_text
from translation.llm.deepseek_client import get_api_key
from translation.llm.deepseek_client import request_chat_content


TYPST_REPAIR_MODEL_ENV = "TYPST_REPAIR_MODEL"
TYPST_REPAIR_BASE_URL_ENV = "TYPST_REPAIR_BASE_URL"
TYPST_REPAIR_ENABLED_ENV = "TYPST_REPAIR_LLM_ENABLED"


def _typst_repair_enabled() -> bool:
    value = os.environ.get(TYPST_REPAIR_ENABLED_ENV, "1")
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _item_formula_map(item: dict) -> list[dict]:
    formula_map = item.get("render_formula_map") or item.get("translation_unit_formula_map") or item.get("formula_map", [])
    normalized: list[dict] = []
    for entry in formula_map:
        placeholder = str(entry.get("placeholder", "") or "").strip()
        formula_text = str(entry.get("formula_text", "") or "").strip()
        if not placeholder:
            continue
        normalized.append({"placeholder": placeholder, "formula_text": formula_text})
    return normalized


def _item_render_text(item: dict) -> str:
    return str(
        item.get("render_protected_text")
        or item.get("translation_unit_protected_translated_text")
        or item.get("protected_translated_text")
        or ""
    ).strip()


def _apply_formula_map(item: dict, formula_map: list[dict]) -> dict:
    cloned = dict(item)
    if "render_formula_map" in cloned:
        cloned["render_formula_map"] = formula_map
    if "translation_unit_formula_map" in cloned:
        cloned["translation_unit_formula_map"] = formula_map
    cloned["formula_map"] = formula_map
    return cloned


def _repair_item_with_llm_for_typst(item: dict, *, request_label: str) -> dict:
    api_key = get_api_key(required=False)
    if not api_key or not _typst_repair_enabled():
        return item

    protected_text = _item_render_text(item)
    formula_map = _item_formula_map(item)
    if not protected_text and not formula_map:
        return item

    messages = [
        {
            "role": "system",
            "content": (
                "You repair translated scientific text so it compiles in Typst/mitex.\n"
                "Keep meaning unchanged.\n"
                "Preserve Chinese wording unless needed for syntax repair.\n"
                "Do not translate, summarize, or explain.\n"
                "Keep every formula placeholder exactly unchanged.\n"
                "Only simplify broken or legacy LaTeX style commands inside formula_text, such as "
                "\\bf, \\rm, \\it, \\pmb, \\textcircled wrappers, redundant style wrappers, "
                "and other purely stylistic commands that often break Typst.\n"
                "Do not drop structural math commands like \\frac, \\sqrt, \\left, \\right, subscripts, superscripts.\n"
                "Return one JSON object with keys protected_text and formula_map."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "Repair this translated block for Typst rendering while preserving placeholders.",
                    "item_id": item.get("item_id", ""),
                    "protected_text": protected_text,
                    "formula_map": formula_map,
                },
                ensure_ascii=False,
            ),
        },
    ]
    try:
        content = request_chat_content(
            messages,
            api_key=api_key,
            model=os.environ.get(TYPST_REPAIR_MODEL_ENV, "deepseek-chat").strip() or "deepseek-chat",
            base_url=os.environ.get(TYPST_REPAIR_BASE_URL_ENV, DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL,
            temperature=0.0,
            response_format={"type": "json_object"},
            timeout=60,
            request_label=request_label,
        )
        payload = json.loads(extract_json_text(content))
    except Exception as exc:
        print(f"{request_label}: llm repair skipped: {type(exc).__name__}: {exc}", flush=True)
        return item

    repaired_text = str(payload.get("protected_text", "") or "").strip() or protected_text
    repaired_formula_map_raw = payload.get("formula_map", formula_map)
    if not isinstance(repaired_formula_map_raw, list):
        repaired_formula_map_raw = formula_map

    original_placeholders = [entry["placeholder"] for entry in formula_map]
    repaired_lookup: dict[str, str] = {}
    for entry in repaired_formula_map_raw:
        if not isinstance(entry, dict):
            continue
        placeholder = str(entry.get("placeholder", "") or "").strip()
        formula_text = str(entry.get("formula_text", "") or "").strip()
        if placeholder and formula_text:
            repaired_lookup[placeholder] = formula_text

    repaired_formula_map: list[dict] = []
    for entry in formula_map:
        placeholder = entry["placeholder"]
        repaired_formula_map.append(
            {
                "placeholder": placeholder,
                "formula_text": repaired_lookup.get(placeholder, entry["formula_text"]),
            }
        )

    # If the model damages placeholders in body text, keep the original protected text.
    if sorted(original_placeholders) != sorted(placeholder for placeholder in original_placeholders if placeholder in repaired_text):
        repaired_text = protected_text

    cloned = _apply_formula_map(item, repaired_formula_map)
    if "render_protected_text" in cloned:
        cloned["render_protected_text"] = repaired_text
    if "translation_unit_protected_translated_text" in cloned:
        cloned["translation_unit_protected_translated_text"] = repaired_text
    if "protected_translated_text" in cloned:
        cloned["protected_translated_text"] = repaired_text
    return cloned


def _repair_items_with_llm_for_typst(
    translated_items: list[dict],
    bad_indices: list[int],
    *,
    stem: str,
) -> list[dict]:
    patched: list[dict] = []
    bad_index_set = set(bad_indices)
    for index, item in enumerate(translated_items):
        if index not in bad_index_set:
            patched.append(item)
            continue
        patched.append(
            _repair_item_with_llm_for_typst(
                item,
                request_label=f"typst-llm-repair {stem} {item.get('item_id', index)}",
            )
        )
    return patched


def sanitize_items_for_typst_compile(
    page_width: float,
    page_height: float,
    translated_items: list[dict],
    stem: str,
    font_family: str = fonts.TYPST_DEFAULT_FONT_FAMILY,
    font_paths: list[Path] | None = None,
    work_dir: Path | None = None,
) -> list[dict]:
    work_dir = work_dir or TYPST_OVERLAY_DIR
    try:
        compile_typst_overlay_pdf(
            page_width,
            page_height,
            translated_items,
            stem=stem,
            font_family=font_family,
            font_paths=font_paths,
            work_dir=work_dir,
        )
        return translated_items
    except RuntimeError as page_error:
        bad_indices: list[int] = []
        for index in range(len(translated_items)):
            try:
                compile_typst_overlay_pdf(
                    page_width,
                    page_height,
                    [translated_items[index]],
                    stem=f"{stem}-probe-{index:03d}",
                    font_family=font_family,
                    font_paths=font_paths,
                    work_dir=work_dir,
                )
            except RuntimeError:
                bad_indices.append(index)

        if bad_indices:
            print(f"typst selective fallback: {stem} block_indices={bad_indices}", flush=True)
            patched_items = translated_items
            for index in bad_indices:
                patched_items = strip_formula_commands_for_item_at_index(patched_items, index)
            try:
                compile_typst_overlay_pdf(
                    page_width,
                    page_height,
                    patched_items,
                    stem=f"{stem}-selective-strip",
                    font_family=font_family,
                    font_paths=font_paths,
                    work_dir=work_dir,
                )
                return patched_items
            except RuntimeError:
                pass

            llm_patched_items = _repair_items_with_llm_for_typst(
                patched_items,
                bad_indices,
                stem=stem,
            )
            if llm_patched_items != patched_items:
                try:
                    compile_typst_overlay_pdf(
                        page_width,
                        page_height,
                        llm_patched_items,
                        stem=f"{stem}-selective-llm",
                        font_family=font_family,
                        font_paths=font_paths,
                        work_dir=work_dir,
                    )
                    return llm_patched_items
                except RuntimeError:
                    pass

            patched_items = translated_items
            for index in bad_indices:
                patched_items = force_plain_text_item_at_index(patched_items, index)
            try:
                compile_typst_overlay_pdf(
                    page_width,
                    page_height,
                    patched_items,
                    stem=f"{stem}-selective-plain",
                    font_family=font_family,
                    font_paths=font_paths,
                    work_dir=work_dir,
                )
                return patched_items
            except RuntimeError:
                pass

        print(f"typst page fallback to plain text: {stem}", flush=True)
        print(str(page_error), flush=True)
        patched_items = force_plain_text_items(translated_items)
        compile_typst_overlay_pdf(
            page_width,
            page_height,
            patched_items,
            stem=f"{stem}-plain",
            font_family=font_family,
            font_paths=font_paths,
            work_dir=work_dir,
        )
        return patched_items


def compile_overlay_pdf_resilient(
    page_width: float,
    page_height: float,
    translated_items: list[dict],
    stem: str,
    font_family: str = fonts.TYPST_DEFAULT_FONT_FAMILY,
    font_paths: list[Path] | None = None,
    work_dir: Path | None = None,
) -> Path:
    work_dir = work_dir or TYPST_OVERLAY_DIR
    sanitized_items = sanitize_items_for_typst_compile(
        page_width,
        page_height,
        translated_items,
        stem=stem,
        font_family=font_family,
        font_paths=font_paths,
        work_dir=work_dir,
    )
    return compile_typst_overlay_pdf(
        page_width,
        page_height,
        sanitized_items,
        stem=f"{stem}-final",
        font_family=font_family,
        font_paths=font_paths,
        work_dir=work_dir,
    )


def sanitize_page_specs_for_typst_book_background(
    page_specs: list[tuple[int, float, float, list[dict]]],
    stem: str,
    font_family: str = fonts.TYPST_DEFAULT_FONT_FAMILY,
    font_paths: list[Path] | None = None,
    work_dir: Path | None = None,
) -> list[tuple[int, float, float, list[dict]]]:
    work_dir = work_dir or TYPST_OVERLAY_DIR
    sanitized_specs: list[tuple[int, float, float, list[dict]]] = []
    for page_index, (source_page_idx, page_width, page_height, translated_items) in enumerate(page_specs):
        sanitized_items = sanitize_items_for_typst_compile(
            page_width,
            page_height,
            translated_items,
            stem=f"{stem}-page-{page_index:03d}",
            font_family=font_family,
            font_paths=font_paths,
            work_dir=work_dir,
        )
        sanitized_specs.append((source_page_idx, page_width, page_height, sanitized_items))
    return sanitized_specs


def sanitize_page_specs_for_typst_book_overlay(
    page_specs: list[tuple[int, float, float, list[dict], str]],
    font_family: str = fonts.TYPST_DEFAULT_FONT_FAMILY,
    font_paths: list[Path] | None = None,
    work_dir: Path | None = None,
) -> list[tuple[int, float, float, list[dict], str]]:
    work_dir = work_dir or TYPST_OVERLAY_DIR
    sanitized_specs: list[tuple[int, float, float, list[dict], str]] = []
    for page_idx, page_width, page_height, translated_items, page_stem in page_specs:
        sanitized_items = sanitize_items_for_typst_compile(
            page_width,
            page_height,
            translated_items,
            stem=page_stem,
            font_family=font_family,
            font_paths=font_paths,
            work_dir=work_dir / "page-overlays" / page_stem,
        )
        sanitized_specs.append((page_idx, page_width, page_height, sanitized_items, page_stem))
    return sanitized_specs
