import random
import string
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from foundation.config.output_layout import LEGACY_OCR_DIR_NAME
from foundation.config.output_layout import LEGACY_SOURCE_DIR_NAME
from foundation.config.output_layout import LEGACY_TRANSLATED_DIR_NAME
from foundation.config.output_layout import LEGACY_TYPST_DIR_NAME
from foundation.config.output_layout import OCR_DIR_NAME
from foundation.config.output_layout import SOURCE_DIR_NAME
from foundation.config.output_layout import TRANSLATED_DIR_NAME
from foundation.config.output_layout import TYPST_DIR_NAME


def build_job_id(now: datetime | None = None, random_length: int = 6) -> str:
    current = now or datetime.now()
    stamp = current.strftime("%Y%m%d%H%M%S")
    alphabet = string.ascii_lowercase + string.digits
    suffix = "".join(random.choice(alphabet) for _ in range(max(4, random_length)))
    return f"{stamp}-{suffix}"


@dataclass(frozen=True)
class JobDirs:
    root: Path
    source_dir: Path
    ocr_dir: Path
    translated_dir: Path
    typst_dir: Path

    @property
    def origin_pdf_dir(self) -> Path:
        return self.source_dir

    @property
    def json_pdf_dir(self) -> Path:
        return self.ocr_dir

    @property
    def trans_pdf_dir(self) -> Path:
        return self.translated_dir


def _preferred_or_legacy(root: Path, preferred: str, legacy: str) -> Path:
    preferred_path = root / preferred
    legacy_path = root / legacy
    if preferred_path.exists():
        return preferred_path
    if legacy_path.exists():
        return legacy_path
    return preferred_path


def locate_source_dir(root: Path) -> Path:
    return _preferred_or_legacy(root, SOURCE_DIR_NAME, LEGACY_SOURCE_DIR_NAME)


def locate_ocr_dir(root: Path) -> Path:
    return _preferred_or_legacy(root, OCR_DIR_NAME, LEGACY_OCR_DIR_NAME)


def locate_translated_dir(root: Path) -> Path:
    return _preferred_or_legacy(root, TRANSLATED_DIR_NAME, LEGACY_TRANSLATED_DIR_NAME)


def locate_typst_dir(root: Path) -> Path:
    return _preferred_or_legacy(root, TYPST_DIR_NAME, LEGACY_TYPST_DIR_NAME)


def create_job_dirs(output_root: Path, job_id: str | None = None) -> JobDirs:
    root = output_root / (job_id or build_job_id())
    source_dir = root / SOURCE_DIR_NAME
    ocr_dir = root / OCR_DIR_NAME
    translated_dir = root / TRANSLATED_DIR_NAME
    typst_dir = root / TYPST_DIR_NAME
    for path in (root, source_dir, ocr_dir, translated_dir, typst_dir):
        path.mkdir(parents=True, exist_ok=True)
    return JobDirs(
        root=root,
        source_dir=source_dir,
        ocr_dir=ocr_dir,
        translated_dir=translated_dir,
        typst_dir=typst_dir,
    )
