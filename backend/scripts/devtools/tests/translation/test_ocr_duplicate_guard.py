import sys
from pathlib import Path


REPO_SCRIPTS_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_SCRIPTS_ROOT))


from services.translation.llm.fallbacks import _normalized_ocr_duplicate_source_text
from services.translation.llm.placeholder_guard import _collapse_adjacent_duplicate_clauses
from services.translation.llm.placeholder_guard import _collapse_adjacent_duplicate_token_runs
from services.translation.llm.placeholder_guard import canonicalize_batch_result
from services.translation.llm.placeholder_guard import result_entry
from services.translation.llm.placeholder_guard import looks_like_untranslated_english_output


def test_normalized_ocr_duplicate_source_text_collapses_adjacent_repetition() -> None:
    source = (
        "Data Science and ML teams use repeated OCR text "
        "Data Science and ML teams use repeated OCR text "
        "to describe dashboards and long-running model evaluations."
    )

    normalized = _normalized_ocr_duplicate_source_text(source)

    assert "Data Science and ML Data Science and ML" not in normalized
    assert "Engineering teams need Engineering teams need" not in normalized
    assert "sophisticated visualization sophisticated visualization" not in normalized


def test_looks_like_untranslated_english_output_rejects_long_english_prefix() -> None:
    item = {
        "item_id": "p011-b008",
        "block_type": "text",
        "metadata": {"structure_role": "body"},
        "translation_unit_protected_source_text": (
            "Instead of building one-off Jupyter notebooks that get discarded, "
            "the team now has Claude build permanent React dashboards."
        ),
    }
    translated_text = (
        "Instead of building one-off Jupyter notebooks that get discarded, the team now has Claude "
        "build permanent React dashboards that can be reused across future model evaluations. "
        "这很重要，因为团队需要持续理解模型在评估期间的表现。"
    )

    assert looks_like_untranslated_english_output(item, translated_text) is True


def test_collapse_adjacent_duplicate_token_runs_collapses_spaced_duplicate_titles() -> None:
    text = "\u8d22\u52a1\u56e2\u961f\u7684\u7eaf\u6587\u672c\u5de5\u4f5c\u6d41 \u8d22\u52a1\u56e2\u961f\u7684\u7eaf\u6587\u672c\u5de5\u4f5c\u6d41"

    collapsed = _collapse_adjacent_duplicate_token_runs(text)

    assert collapsed == "\u8d22\u52a1\u56e2\u961f\u7684\u7eaf\u6587\u672c\u5de5\u4f5c\u6d41"


def test_collapse_adjacent_duplicate_token_runs_handles_short_meta_gap() -> None:
    text = (
        "\u7ed3\u5408\u622a\u56fe\u7684 Kubernetes \u8c03\u8bd5"
        "\" to keep it.\\n\\n"
        "\u7ed3\u5408\u622a\u56fe\u7684 Kubernetes \u8c03\u8bd5"
    )

    collapsed = _collapse_adjacent_duplicate_token_runs(text)

    assert collapsed == "\u7ed3\u5408\u622a\u56fe\u7684 Kubernetes \u8c03\u8bd5"


def test_collapse_adjacent_duplicate_clauses_handles_cjk_sentence_punctuation() -> None:
    collapsed = _collapse_adjacent_duplicate_clauses("\u64cd\u4f5c\u6570\u636e\u3002\u64cd\u4f5c\u6570\u636e\u3002")

    assert collapsed == "\u64cd\u4f5c\u6570\u636e\u3002"


def test_canonicalize_batch_result_recovers_title_from_meta_reasoning_suffix() -> None:
    item = {
        "item_id": "p003-b009",
        "block_type": "title",
        "metadata": {"structure_role": "title"},
        "protected_source_text": "End-of-session documentation updates",
        "translation_unit_protected_source_text": "End-of-session documentation updates",
    }
    result = {
        "p003-b009": result_entry(
            "translate",
            "**Translating the title** I need to provide a concise translation while keeping duplicated title text faithful. "
            "Maybe it looks odd, but I should mirror the source when needed. "
            "\u4f1a\u8bdd\u7ed3\u675f\u65f6\u7684\u6587\u6863\u66f4\u65b0",
        )
    }

    translated = canonicalize_batch_result([item], result)["p003-b009"]["translated_text"]

    assert translated == "\u4f1a\u8bdd\u7ed3\u675f\u65f6\u7684\u6587\u6863\u66f4\u65b0"


def test_canonicalize_batch_result_recovers_title_from_quoted_meta_reasoning() -> None:
    item = {
        "item_id": "p003-b007",
        "block_type": "title",
        "metadata": {"structure_role": "title"},
        "protected_source_text": "Codebase navigation for new hires",
        "translation_unit_protected_source_text": "Codebase navigation for new hires",
    }
    result = {
        "p003-b007": result_entry(
            "translate",
            "\u65b0\u5458\u5de5\u7684\u4ee3\u7801\u5e93\u5bfc\u822a\" sounds awkward. Maybe I could infer it\u2019s an OCR issue? "
            "Still, it doesn\u2019t seem right to remove it completely. So, I\u2019ll think about phrasing it like "
            "\"\u65b0\u5458\u5de5\u4ee3\u7801\u5e93\u5bfc\u822a",
        )
    }

    translated = canonicalize_batch_result([item], result)["p003-b007"]["translated_text"]

    assert "sounds awkward" not in translated
    assert "Maybe I could infer" not in translated
    assert translated in {
        "\u65b0\u5458\u5de5\u7684\u4ee3\u7801\u5e93\u5bfc\u822a",
        "\u65b0\u5458\u5de5\u4ee3\u7801\u5e93\u5bfc\u822a",
    }


def test_canonicalize_batch_result_prepends_missing_title_source_context() -> None:
    item = {
        "item_id": "p003-b002",
        "block_type": "title",
        "metadata": {"structure_role": "title"},
        "protected_source_text": "Main Claude Code use cases Main Claude Code use cases",
        "translation_unit_protected_source_text": "Main Claude Code use cases Main Claude Code use cases",
    }
    result = {
        "p003-b002": result_entry(
            "translate",
            "**Considering translation options** I should preserve repeated titles carefully. \u7684\u4e3b\u8981\u7528\u4f8b",
        )
    }

    translated = canonicalize_batch_result([item], result)["p003-b002"]["translated_text"]

    assert translated == "Claude Code \u7684\u4e3b\u8981\u7528\u4f8b"


def test_canonicalize_batch_result_recovers_title_when_reasoning_is_appended_after_title() -> None:
    item = {
        "item_id": "p003-b000",
        "block_type": "title",
        "metadata": {"structure_role": "title"},
        "protected_source_text": "Claude Code for data infrastructure",
        "translation_unit_protected_source_text": "Claude Code for data infrastructure",
    }
    result = {
        "p003-b000": result_entry(
            "translate",
            "\u7528\u4e8e\u6570\u636e\u57fa\u7840\u8bbe\u65bd\u7684 Claude Code, and I'll ensure it reflects that without duplication.\n\n"
            "\u9762\u5411\u6570\u636e\u57fa\u7840\u8bbe\u65bd\u7684 Claude Code",
        )
    }

    translated = canonicalize_batch_result([item], result)["p003-b000"]["translated_text"]

    assert "without duplication" not in translated
    assert translated.endswith("Claude Code")
    assert translated in {
        "\u7528\u4e8e\u6570\u636e\u57fa\u7840\u8bbe\u65bd\u7684 Claude Code",
        "\u9762\u5411\u6570\u636e\u57fa\u7840\u8bbe\u65bd\u7684 Claude Code",
    }


def test_canonicalize_batch_result_recovers_short_toc_entry_from_meta_reasoning() -> None:
    item = {
        "item_id": "p002-b003",
        "block_type": "text",
        "metadata": {"structure_role": "body"},
        "protected_source_text": "1.1 Exponential Change and the Human-AI Partnership . . 3",
        "translation_unit_protected_source_text": "1.1 Exponential Change and the Human-AI Partnership . . 3",
    }
    result = {
        "p002-b003": result_entry(
            "translate",
            "\u6307\u6570\u7ea7\u53d8\u5316\u4e0e\u4eba\u7c7b\u2013AI\u4f19\u4f34\u5173\u7cfb . . 3.\" I wonder if it's better to keep "
            "\"\u4eba\u7c7b\u2013AI\u4f19\u4f34\u5173\u7cfb\" for consistency, so I'll keep the numbering and dots as is.\n\n"
            "1.1 \u6307\u6570\u7ea7\u53d8\u5316\u4e0e\u4eba\u7c7b\u2013AI\u4f19\u4f34\u5173\u7cfb . . 3",
        )
    }

    translated = canonicalize_batch_result([item], result)["p002-b003"]["translated_text"]

    assert translated == "1.1 \u6307\u6570\u7ea7\u53d8\u5316\u4e0e\u4eba\u7c7b\u2013AI\u4f19\u4f34\u5173\u7cfb . . 3"


def test_canonicalize_batch_result_strips_leading_short_entry_garbage() -> None:
    item = {
        "item_id": "p002-b001",
        "block_type": "title",
        "metadata": {"structure_role": "title"},
        "protected_source_text": "1 Introduction: The Imperative for a New Educational Paradigm 3",
        "translation_unit_protected_source_text": "1 Introduction: The Imperative for a New Educational Paradigm 3",
    }
    result = {
        "p002-b001": result_entry(
            "translate",
            "structure!1 \u5f15\u8a00\uff1a\u65b0\u6559\u80b2\u8303\u5f0f\u7684\u5fc5\u8981\u6027 3",
        )
    }

    translated = canonicalize_batch_result([item], result)["p002-b001"]["translated_text"]

    assert translated == "1 \u5f15\u8a00\uff1a\u65b0\u6559\u80b2\u8303\u5f0f\u7684\u5fc5\u8981\u6027 3"


def test_canonicalize_batch_result_recovers_inline_short_entry_from_quoted_reasoning() -> None:
    item = {
        "item_id": "p002-b026",
        "block_type": "text",
        "metadata": {"structure_role": "body"},
        "protected_source_text": "6 Enabling Infrastructure and Standardization 23",
        "translation_unit_protected_source_text": "6 Enabling Infrastructure and Standardization 23",
    }
    result = {
        "p002-b026": result_entry(
            "translate",
            "\u652f\u6491\u6027\u57fa\u7840\u8bbe\u65bd\u4e0e\u6807\u51c6\u5316\" could also work. However, for a policy context, "
            "\"\u652f\u6491\u6027\u57fa\u7840\u8bbe\u65bd\u4e0e\u6807\u51c6\u5316 23",
        )
    }

    translated = canonicalize_batch_result([item], result)["p002-b026"]["translated_text"]

    assert translated == "\u652f\u6491\u6027\u57fa\u7840\u8bbe\u65bd\u4e0e\u6807\u51c6\u5316 23"


def test_canonicalize_batch_result_recovers_title_from_inline_explanation_suffix() -> None:
    item = {
        "item_id": "p003-b005",
        "block_type": "title",
        "metadata": {"structure_role": "title"},
        "protected_source_text": "Plain-text workflows for finance teams",
        "translation_unit_protected_source_text": "Plain-text workflows for finance teams",
    }
    result = {
        "p003-b005": result_entry(
            "translate",
            "\u7eaf\u6587\u672c\u5de5\u4f5c\u6d41, which gives the title: \u8d22\u52a1\u56e2\u961f\u7684\u7eaf\u6587\u672c\u5de5\u4f5c\u6d41",
        )
    }

    translated = canonicalize_batch_result([item], result)["p003-b005"]["translated_text"]

    assert translated == "\u8d22\u52a1\u56e2\u961f\u7684\u7eaf\u6587\u672c\u5de5\u4f5c\u6d41"


def test_canonicalize_batch_result_prepends_missing_context_for_short_generic_title() -> None:
    item = {
        "item_id": "p003-b002",
        "block_type": "title",
        "metadata": {"structure_role": "title"},
        "protected_source_text": "Main Claude Code use cases Main Claude Code use cases",
        "translation_unit_protected_source_text": "Main Claude Code use cases Main Claude Code use cases",
    }
    result = {
        "p003-b002": result_entry(
            "translate",
            "\u4e3b\u8981\u7528\u4f8b",
        )
    }

    translated = canonicalize_batch_result([item], result)["p003-b002"]["translated_text"]

    assert translated == "Claude Code \u4e3b\u8981\u7528\u4f8b"


def test_canonicalize_batch_result_does_not_prepend_single_word_source_term() -> None:
    item = {
        "item_id": "p003-b007",
        "block_type": "title",
        "metadata": {"structure_role": "title"},
        "protected_source_text": "Codebase navigation for new hires",
        "translation_unit_protected_source_text": "Codebase navigation for new hires",
    }
    result = {
        "p003-b007": result_entry(
            "translate",
            "\u65b0\u5458\u5de5\u4ee3\u7801\u5e93\u5bfc\u822a",
        )
    }

    translated = canonicalize_batch_result([item], result)["p003-b007"]["translated_text"]

    assert translated == "\u65b0\u5458\u5de5\u4ee3\u7801\u5e93\u5bfc\u822a"
