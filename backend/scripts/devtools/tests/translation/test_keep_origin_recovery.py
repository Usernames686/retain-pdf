import sys
from pathlib import Path
from unittest import mock


REPO_SCRIPTS_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_SCRIPTS_ROOT))


from services.translation.llm.control_context import build_translation_control_context
from services.translation.llm.fallbacks import translate_items_plain_text
from services.translation.llm.fallbacks import translate_single_item_plain_text_with_retries
from services.translation.llm.placeholder_guard import EnglishResidueError
from services.translation.llm.placeholder_guard import result_entry
from services.translation.llm.placeholder_guard import SuspiciousKeepOriginError


def test_plain_text_retry_recovers_after_suspicious_keep_origin_from_structured_fallback() -> None:
    item = {
        "item_id": "p002-b003",
        "block_type": "text",
        "protected_source_text": "This paragraph contains enough English prose to require translation into Chinese for the user.",
        "translation_unit_protected_source_text": "This paragraph contains enough English prose to require translation into Chinese for the user.",
        "metadata": {"structure_role": "body"},
    }
    calls: list[str] = []

    def fake_plain(*args, **kwargs):
        calls.append("plain")
        raise EnglishResidueError(item["item_id"])

    def fake_structured(*args, **kwargs):
        calls.append("structured")
        raise SuspiciousKeepOriginError(item["item_id"], {item["item_id"]: result_entry("keep_origin", "")})

    def fake_raw(*args, **kwargs):
        calls.append("raw")
        return {item["item_id"]: result_entry("translate", "raw fallback translated body text")}

    with mock.patch(
        "services.translation.llm.fallbacks.translate_single_item_plain_text",
        side_effect=fake_plain,
    ), mock.patch(
        "services.translation.llm.fallbacks.translate_single_item_with_decision",
        side_effect=fake_structured,
    ), mock.patch(
        "services.translation.llm.fallbacks.translate_single_item_plain_text_unstructured",
        side_effect=fake_raw,
    ):
        result = translate_single_item_plain_text_with_retries(
            item,
            api_key="",
            model="gpt-5.4",
            base_url="https://lll.dpdns.org/v1",
            request_label="unit",
            context=build_translation_control_context(mode="fast"),
            diagnostics=None,
        )

    assert calls[:4] == ["plain", "plain", "plain", "plain"]
    assert calls[-2:] == ["structured", "raw"]
    assert result[item["item_id"]]["translated_text"] == "raw fallback translated body text"


def test_plain_text_retry_degrades_to_internal_keep_origin_after_repeated_english_residue() -> None:
    item = {
        "item_id": "p008-b017",
        "block_type": "text",
        "protected_source_text": "This work is the result of years of collaboration between teams in Google Core Systems and Google DeepMind.",
        "translation_unit_protected_source_text": "This work is the result of years of collaboration between teams in Google Core Systems and Google DeepMind.",
        "metadata": {"structure_role": "body"},
        "page_idx": 7,
    }

    def raise_residue(*args, **kwargs):
        raise EnglishResidueError(
            item["item_id"],
            source_text=item["protected_source_text"],
            translated_text="Translated text still contains too much English residue.",
        )

    with mock.patch(
        "services.translation.llm.fallbacks.translate_single_item_plain_text",
        side_effect=raise_residue,
    ), mock.patch(
        "services.translation.llm.fallbacks.translate_single_item_with_decision",
        side_effect=raise_residue,
    ), mock.patch(
        "services.translation.llm.fallbacks.translate_single_item_plain_text_unstructured",
        side_effect=raise_residue,
    ), mock.patch(
        "services.translation.llm.fallbacks._sentence_level_fallback",
        side_effect=raise_residue,
    ):
        result = translate_single_item_plain_text_with_retries(
            item,
            api_key="",
            model="gpt-5.4",
            base_url="https://lll.dpdns.org/v1",
            request_label="unit",
            context=build_translation_control_context(mode="fast"),
            diagnostics=None,
        )

    payload = result[item["item_id"]]
    assert payload["decision"] == "keep_origin"
    assert payload["_internal_reason"] == "english_residue_repeated"


def test_translate_items_plain_text_degrades_single_bad_item_without_aborting_batch() -> None:
    good_item = {
        "item_id": "p001-b001",
        "block_type": "text",
        "protected_source_text": "Short heading.",
        "translation_unit_protected_source_text": "Short heading.",
        "metadata": {"structure_role": "title"},
        "page_idx": 0,
    }
    bad_item = {
        "item_id": "p001-b002",
        "block_type": "text",
        "protected_source_text": "This paragraph still looks too English after translation.",
        "translation_unit_protected_source_text": "This paragraph still looks too English after translation.",
        "metadata": {"structure_role": "body"},
        "page_idx": 0,
    }

    def fake_translate(item, **kwargs):
        if item["item_id"] == bad_item["item_id"]:
            raise EnglishResidueError(item["item_id"])
        return {item["item_id"]: result_entry("translate", "已翻译")}

    with mock.patch(
        "services.translation.llm.fallbacks.translate_single_item_plain_text_with_retries",
        side_effect=fake_translate,
    ):
        result = translate_items_plain_text(
            [good_item, bad_item],
            api_key="",
            model="gpt-5.4",
            base_url="https://lll.dpdns.org/v1",
            request_label="batch",
            context=build_translation_control_context(mode="fast"),
            diagnostics=None,
        )

    assert result[good_item["item_id"]]["decision"] == "translate"
    assert result[good_item["item_id"]]["translated_text"] == "已翻译"
    assert result[bad_item["item_id"]]["decision"] == "keep_origin"
    assert result[bad_item["item_id"]]["_internal_reason"] == "single_item_validation_failed"
