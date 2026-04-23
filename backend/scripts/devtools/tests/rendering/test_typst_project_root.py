import sys
from pathlib import Path


REPO_SCRIPTS_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_SCRIPTS_ROOT))


from services.rendering.typst.compiler import _typst_project_root


def test_typst_project_root_uses_common_ancestor_for_render_job_files() -> None:
    root = Path("/data/jobs/job-123")
    work_dir = root / "rendered" / "typst"
    typ_path = work_dir / "book-background-overlay.typ"
    pdf_path = work_dir / "book-background-overlay.pdf"
    source_pdf_path = root / "source.pdf"

    project_root = _typst_project_root(work_dir, typ_path, pdf_path, source_pdf_path)

    assert project_root == root


def test_typst_project_root_keeps_background_workdir_when_assets_are_local() -> None:
    work_dir = Path("/data/jobs/job-456/rendered/typst")
    typ_path = work_dir / "book.typ"
    pdf_path = work_dir / "book.pdf"
    background_pdf_path = work_dir / "book-background-cleaned.pdf"

    project_root = _typst_project_root(work_dir, typ_path, pdf_path, background_pdf_path)

    assert project_root == work_dir
