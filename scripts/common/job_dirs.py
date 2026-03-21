import random
import string
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


def build_job_id(now: datetime | None = None, random_length: int = 6) -> str:
    current = now or datetime.now()
    stamp = current.strftime("%Y%m%d%H%M")
    alphabet = string.ascii_lowercase + string.digits
    suffix = "".join(random.choice(alphabet) for _ in range(max(4, random_length)))
    return f"{stamp}-{suffix}"


@dataclass(frozen=True)
class JobDirs:
    root: Path
    origin_pdf_dir: Path
    trans_pdf_dir: Path
    json_pdf_dir: Path


def create_job_dirs(output_root: Path, job_id: str | None = None) -> JobDirs:
    root = output_root / (job_id or build_job_id())
    origin_pdf_dir = root / "originPDF"
    trans_pdf_dir = root / "transPDF"
    json_pdf_dir = root / "jsonPDF"
    for path in (root, origin_pdf_dir, trans_pdf_dir, json_pdf_dir):
        path.mkdir(parents=True, exist_ok=True)
    return JobDirs(
        root=root,
        origin_pdf_dir=origin_pdf_dir,
        trans_pdf_dir=trans_pdf_dir,
        json_pdf_dir=json_pdf_dir,
    )
