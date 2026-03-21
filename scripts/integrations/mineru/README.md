# MinerU Integration

Recommended entry points:

- `mineru_pipeline.py`
  Full end-to-end flow. Parse with MinerU, then translate from `layout.json`, then render into `transPDF`.
- `mineru_job.py`
  Parse only. Download and unpack MinerU outputs into a structured job directory.
- `migrate_legacy_output.py`
  Move old `output/mineru/<case>` experiments into the new structured job layout.
- `mineru_api.py`
  Low-level API caller. Use this only when you want raw MinerU API interaction.

Structured job layout:

- `output/<job-id>/originPDF`
- `output/<job-id>/jsonPDF`
- `output/<job-id>/transPDF`

Main rule:

- use `jsonPDF/unpacked/layout.json` as the default MinerU OCR JSON for the translation pipeline
- keep `content_list_v2.json` for experiments only
