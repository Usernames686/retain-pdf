import sys
from pathlib import Path


REPO_SCRIPTS_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_SCRIPTS_ROOT))


from services.translation.llm import placeholder_guard as guard


def test_canonicalize_batch_result_strips_translation_commentary_fragments() -> None:
    item = {
        "item_id": "p001-b001",
        "block_type": "text",
        "metadata": {"structure_role": "body"},
        "protected_source_text": "Human-computer symbiosis",
        "translation_unit_protected_source_text": "Human-computer symbiosis",
    }
    result = {
        "p001-b001": guard.result_entry(
            "translate",
            "共生愿景。This feels like a good translation, reflecting the essential ideas while keeping it succinct. "
            "I'm wondering if \"Licklider\" should be translated as 利克莱德。"
            "现代人机协作的概念源头可追溯至 J.C.R. Licklider 1960 年的奠基性论文。",
        )
    }

    translated = guard.canonicalize_batch_result([item], result)["p001-b001"]["translated_text"]

    assert "This feels like a good translation" not in translated
    assert "I'm wondering if" not in translated
    assert "should be translated as" not in translated
    assert translated == "共生愿景。现代人机协作的概念源头可追溯至 J.C.R. Licklider 1960 年的奠基性论文。"
