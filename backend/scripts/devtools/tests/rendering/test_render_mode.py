import sys
from pathlib import Path
from unittest import mock

import fitz


REPO_SCRIPTS_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_SCRIPTS_ROOT))


from runtime.pipeline.render_mode import resolve_effective_render_mode


class _FakePage:
    pass


class _FakeDoc:
    def __init__(self, page_count: int) -> None:
        self._pages = [_FakePage() for _ in range(page_count)]

    def __len__(self) -> int:
        return len(self._pages)

    def __getitem__(self, index: int) -> _FakePage:
        return self._pages[index]

    def close(self) -> None:
        return None


def _probe_item(idx: int) -> tuple[fitz.Rect, dict, str]:
    return (
        fitz.Rect(10 + idx, 20 + idx, 110 + idx, 70 + idx),
        {
            "bbox": [10 + idx, 20 + idx, 110 + idx, 70 + idx],
            "source_text": f"This is a sufficiently long source sentence number {idx} for probing.",
            "translated_text": f"第 {idx} 条翻译文本",
        },
        f"第 {idx} 条翻译文本",
    )


def test_auto_render_mode_falls_back_to_typst_when_vector_text_risk_is_detected() -> None:
    fake_doc = _FakeDoc(1)
    translated_pages_map = {0: [{} for _ in range(6)]}
    probe_items = [_probe_item(idx) for idx in range(6)]

    with mock.patch("runtime.pipeline.render_mode.fitz.open", return_value=fake_doc), mock.patch(
        "runtime.pipeline.render_mode.is_editable_pdf",
        return_value=True,
    ), mock.patch(
        "runtime.pipeline.render_mode.source_pdf_has_vector_graphics",
        return_value=False,
    ), mock.patch(
        "runtime.pipeline.render_mode.iter_valid_translated_items",
        return_value=probe_items,
    ), mock.patch(
        "runtime.pipeline.render_mode.item_has_removable_text",
        return_value=True,
    ), mock.patch(
        "runtime.pipeline.render_mode.collect_page_drawing_rects",
        return_value=[fitz.Rect(0, 0, 200, 200)],
    ), mock.patch(
        "runtime.pipeline.render_mode.item_vector_overlap_stats",
        side_effect=[(24, 0.12), (18, 0.08), (16, 0.05), (0, 0.0), (0, 0.0), (0, 0.0)],
    ):
        result = resolve_effective_render_mode(
            render_mode="auto",
            source_pdf_path=Path("dummy.pdf"),
            start_page=0,
            end_page=-1,
            translated_pages_map=translated_pages_map,
        )

    assert result == "typst"


def test_auto_render_mode_keeps_overlay_when_probe_text_is_removable_without_vector_risk() -> None:
    fake_doc = _FakeDoc(1)
    translated_pages_map = {0: [{} for _ in range(6)]}
    probe_items = [_probe_item(idx) for idx in range(6)]

    with mock.patch("runtime.pipeline.render_mode.fitz.open", return_value=fake_doc), mock.patch(
        "runtime.pipeline.render_mode.is_editable_pdf",
        return_value=True,
    ), mock.patch(
        "runtime.pipeline.render_mode.source_pdf_has_vector_graphics",
        return_value=False,
    ), mock.patch(
        "runtime.pipeline.render_mode.iter_valid_translated_items",
        return_value=probe_items,
    ), mock.patch(
        "runtime.pipeline.render_mode.item_has_removable_text",
        return_value=True,
    ), mock.patch(
        "runtime.pipeline.render_mode.collect_page_drawing_rects",
        return_value=[],
    ):
        result = resolve_effective_render_mode(
            render_mode="auto",
            source_pdf_path=Path("dummy.pdf"),
            start_page=0,
            end_page=-1,
            translated_pages_map=translated_pages_map,
        )

    assert result == "overlay"
