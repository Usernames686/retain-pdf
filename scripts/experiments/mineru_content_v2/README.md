# MinerU `content_list_v2` Adapter

This experimental route adapts MinerU `content_list_v2.json` into a normalized
intermediate JSON that is easier for later translation/rendering work.

It is intentionally isolated from the stable main pipeline.

Current recommendation:

- use `jsonPDF/unpacked/layout.json` as the main MinerU-to-pipeline JSON
- keep `content_list_v2.json` only for experiments around finer text/formula structure

## Input

- `output/<job-id>/jsonPDF/unpacked/content_list_v2.json`

## Output

A normalized JSON with:

- page list
- normalized blocks
- flattened text-bearing blocks with `segments`
- preserved raw MinerU block payload for non-text blocks

## Run

```bash
python scripts/experiments/mineru_content_v2/adapt_content_list_v2.py \
  --input output/<job-id>/jsonPDF/unpacked/content_list_v2.json \
  --output output/<job-id>/jsonPDF/mineru_content_v2_adapted.json
```

## Current Scope

- supports `title`, `paragraph`, `list`, `page_header`, `page_footer`, `page_number`
- preserves `image`, `table`, `equation_interline` as non-translatable blocks
- expands MinerU list items into separate normalized blocks

## Known Gaps

- no line-level geometry reconstruction
- list items reuse parent list bbox because MinerU input does not expose per-item bbox
- not recommended as the default MinerU route right now
