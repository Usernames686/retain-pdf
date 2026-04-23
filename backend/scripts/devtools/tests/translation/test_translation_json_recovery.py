import json
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


REPO_SCRIPTS_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_SCRIPTS_ROOT))


def _ensure_package_stubs() -> None:
    package_paths = {
        "services": REPO_SCRIPTS_ROOT / "services",
        "services.translation": REPO_SCRIPTS_ROOT / "services" / "translation",
        "services.translation.llm": REPO_SCRIPTS_ROOT / "services" / "translation" / "llm",
    }
    for name, path in package_paths.items():
        module = sys.modules.get(name)
        if module is None:
            module = types.ModuleType(name)
            module.__path__ = [str(path)]
            sys.modules[name] = module


def _load_module(name: str, path: Path):
    _ensure_package_stubs()
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TranslationJsonRecoveryTests(unittest.TestCase):
    def test_extract_json_text_ignores_trailing_json_object(self) -> None:
        module = _load_module(
            "services.translation.llm.deepseek_client",
            REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "deepseek_client.py",
        )
        content = '{"decision":"translate","translated_text":"测试"}{"trace":"extra"}'

        payload = json.loads(module.extract_json_text(content))

        self.assertEqual(payload["decision"], "translate")
        self.assertEqual(payload["translated_text"], "测试")

    def test_parse_translation_payload_ignores_trailing_json_object(self) -> None:
        module = _load_module(
            "services.translation.llm.translation_client",
            REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "translation_client.py",
        )
        content = (
            '{"translations":[{"item_id":"p022-b019","translated_text":"处理后的文本","decision":"translate"}]}'
            '{"trace":"extra"}'
        )

        result = module.parse_translation_payload(content)

        self.assertEqual(result["p022-b019"]["decision"], "translate")
        self.assertEqual(result["p022-b019"]["translated_text"], "处理后的文本")

    def test_translate_single_item_with_decision_accepts_plain_text_when_json_is_missing(self) -> None:
        module = _load_module(
            "services.translation.llm.translation_client",
            REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "translation_client.py",
        )
        item = {
            "item_id": "p011-b008",
            "protected_source_text": "This paragraph contains enough English prose to require translation into Chinese for the user.",
            "translation_unit_protected_source_text": "This paragraph contains enough English prose to require translation into Chinese for the user.",
            "block_type": "text",
            "metadata": {"structure_role": "body"},
        }
        captured: dict[str, object] = {}

        def _fake_messages(*args, **kwargs):
            captured["response_style"] = kwargs.get("response_style")
            return [{"role": "system", "content": "stub"}]

        def _fake_request(messages, **kwargs):
            captured["response_format"] = kwargs.get("response_format")
            return "这里是修复后的中文译文。"

        with mock.patch.object(module, "build_single_item_fallback_messages", side_effect=_fake_messages), mock.patch.object(
            module, "request_chat_content", side_effect=_fake_request
        ):
            result = module.translate_single_item_with_decision(item)

        self.assertEqual(captured["response_style"], "json")
        self.assertIsNotNone(captured["response_format"])
        self.assertEqual(result["p011-b008"]["translated_text"], "这里是修复后的中文译文。")

    def test_plain_text_retry_recovers_after_non_json_structured_fallback(self) -> None:
        control_context = _load_module(
            "services.translation.llm.control_context",
            REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "control_context.py",
        )
        placeholder_guard = _load_module(
            "services.translation.llm.placeholder_guard",
            REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "placeholder_guard.py",
        )
        fallbacks = _load_module(
            "services.translation.llm.fallbacks",
            REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "fallbacks.py",
        )
        item = {
            "item_id": "p011-b008",
            "block_type": "text",
            "protected_source_text": "This paragraph contains enough English prose to require translation into Chinese for the user.",
            "translation_unit_protected_source_text": "This paragraph contains enough English prose to require translation into Chinese for the user.",
            "metadata": {"structure_role": "body"},
        }
        calls: list[str] = []

        def fake_plain(*args, **kwargs):
            calls.append("plain")
            raise placeholder_guard.EnglishResidueError(item["item_id"])

        def fake_structured(*args, **kwargs):
            calls.append("structured")
            raise ValueError("Model response does not contain a JSON object.")

        def fake_raw(*args, **kwargs):
            calls.append("raw")
            return {item["item_id"]: placeholder_guard.result_entry("translate", "raw fallback translated body text")}

        with mock.patch.object(fallbacks, "translate_single_item_plain_text", side_effect=fake_plain), mock.patch.object(
            fallbacks, "translate_single_item_with_decision", side_effect=fake_structured
        ), mock.patch.object(fallbacks, "translate_single_item_plain_text_unstructured", side_effect=fake_raw):
            result = fallbacks.translate_single_item_plain_text_with_retries(
                item,
                api_key="",
                model="gpt-5.4",
                base_url="https://lll.dpdns.org/v1",
                request_label="unit",
                context=control_context.build_translation_control_context(mode="fast"),
                diagnostics=None,
            )

        self.assertEqual(calls, ["plain", "plain", "plain", "plain", "structured", "raw"])
        self.assertEqual(result[item["item_id"]]["translated_text"], "raw fallback translated body text")

    def test_canonicalize_batch_result_strips_meta_preamble_and_duplicate_clauses(self) -> None:
        module = _load_module(
            "services.translation.llm.placeholder_guard",
            REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "placeholder_guard.py",
        )
        item = {
            "item_id": "p003-b008",
            "block_type": "text",
            "metadata": {"structure_role": "body"},
            "translation_unit_protected_source_text": (
                "When new data scientists join the team, they are directed to use Claude Code to navigate their codebase."
            ),
        }
        result = module.canonicalize_batch_result(
            [item],
            {
                "p003-b008": {
                    "decision": "translate",
                    "translated_text": (
                        "**Translating OCR text**\n\n"
                        "I need to translate duplicated OCR text, likely with repeated clauses.\n\n"
                        "当新的数据科学家加入团队时，他们会被要求使用 Claude Code 浏览代码库。"
                        "当新的数据科学家加入团队时，他们会被要求使用 Claude Code 浏览代码库。"
                    ),
                }
            },
        )

        self.assertEqual(
            result["p003-b008"]["translated_text"],
            "当新的数据科学家加入团队时，他们会被要求使用 Claude Code 浏览代码库。",
        )

    def test_canonicalize_batch_result_collapses_adjacent_duplicate_spans(self) -> None:
        module = _load_module(
            "services.translation.llm.placeholder_guard",
            REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "placeholder_guard.py",
        )
        item = {
            "item_id": "p003-b008",
            "block_type": "text",
            "metadata": {"structure_role": "body"},
            "translation_unit_protected_source_text": "When new data scientists join the team, they are directed to use Claude Code to navigate their codebase.",
        }
        result = module.canonicalize_batch_result(
            [item],
            {
                "p003-b008": {
                    "decision": "translate",
                    "translated_text": (
                        "当新的数据科学家加入团队时，他们会被要求使用 Claude"
                        "当新的数据科学家加入团队时，他们会被要求使用 Claude Code 来浏览其庞大的代码库。"
                    ),
                }
            },
        )

        self.assertEqual(
            result["p003-b008"]["translated_text"],
            "当新的数据科学家加入团队时，他们会被要求使用 Claude Code 来浏览其庞大的代码库。",
        )


if __name__ == "__main__":
    unittest.main()
