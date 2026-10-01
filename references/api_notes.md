# MinerU OpenAPI v4 — endpoint reference

Base URL: `https://mineru.net/api/v4`
Auth: `Authorization: Bearer <token>` on every request.

| Step | Method & path | Body / notes |
|------|---------------|--------------|
| Get upload URL | `POST /file-urls/batch` | `{"files":[{"name":<fn>,"data_id":"wb"}],"model_version":"vlm"}` -> `data.batch_id`, `data.file_urls[]` (OSS presigned PUT URLs) |
| Upload file | `PUT (presigned_url)` | Raw file bytes, **NO Content-Type header** (sends `200` on success; system auto-submits the parse) |
| Poll status | `GET /extract-results/batch/{batch_id}` | `data.extract_result[].state` -> `done` / `failed`; `data.extract_result[].full_zip_url` when done |
| (URL source) | `POST /extract/task/batch` | For already-hosted PDFs: `{"files":[{"url":...,"data_id":...}],"model_version":"vlm"}` |

### MinerU 4.0 — request-body fields (all optional, opt-in)

These were added on the cloud OpenAPI v4 and are now exposed by `mineru_convert.py`
via `--pages` / `--lang` / `--ocr`. They are omitted from the JSON body unless the
user asks, so the default request is unchanged from before.

| Field | CLI flag | Example | Effect |
|-------|----------|---------|--------|
| `page_ranges` | `--pages` | `"1-10"`, `"2,4-6"` | Partial parse; API selects the pages. When set, the script skips local pypdf auto-split. Page markers count within the chosen range. |
| `language` | `--lang` | `"ch"` (default) / `"en"` | OCR/language hint. Pass `en` for non-Chinese-only sources; the VLM stays multilingual. |
| `is_ocr` | `--ocr` | `true` | Enable OCR for scanned/bitmap PDFs (API default `false`). |
| `enable_formula` | (default on) | `true` | Formula recognition; left at API default `true`. |
| `enable_table` | (default on) | `true` | Table recognition; left at API default `true`. |
| `extra_formats` | — | `["docx","html","latex"]` | Extra export formats. Left off: this skill consumes the Markdown + `content_list.json` + `images/` from the zip. |

Notes:
- Model quality on the cloud API is still chosen by `model_version` (`vlm` =
  top quality; `pipeline` = fast). The 4.0 `flash/basic/standard/advanced` *tiers*
  are a **local-CLI** concept (`--tier` on `mineru`/`mineru-kit`) and do NOT apply
  to this cloud skill.
- The cloud API also exposes a no-token Agent lightweight API (`/api/v1/agent/...`,
  ≤10 MB / ≤20 pages, `flash` model only) — out of scope for batch/page-marker work.

Downloaded zip (`full_zip_url`) contains:
- `(id)_content_list.json` — list of blocks; each has `page_idx` (0-based) and
  `type`. `type=="page_number"` blocks carry the **real printed page number** in
  `text`. Block types include `text`, `title`, `equation`, `table` (HTML in
  `table_body`), `image`/`chart` (`img_path`), `header`, `footer`,
  `page_footnote` (the last three are excluded from the Markdown).
- `full.md` — MinerU's own Markdown (no page markers).
- `images/`, `model.json`, `layout.json`, `content_list.json`.

Page-marker grammar emitted by `reconstruct()` (a markdown HTML comment):
`第 {page_idx+1+offset} 页 [| 印刷页码: {text}]`

## Batch / verify / inventory (skill additions)

- `batch IN OUT [--model vlm] [--md-only|--full] [--workers 2] [--max-pages 180] [--force]`
  Walks IN for `*.pdf`, mirrors the tree under OUT, converts each. Auto-splits
  files over `--max-pages`. Skips existing `.md` unless `--force`. Writes
  `OUT/_batch_manifest.jsonl` (one JSON per file).
- `verify OUT [--source IN] [--report PATH]`
  Scans OUT for MinerU `.md`, checks page markers exist and every image ref
  resolves to a file in the sibling `_files/` dir. With `--source`, also compares
  the last page marker to the source PDF's real page count. Writes
  `OUT/_verify_report.md`.
- `inventory IN [--max-pages 180]`
  Lists each PDF with its page count and whether it needs splitting. No API calls.

Thread-safety: each download uses its own `tempfile.mkdtemp`, and `upload_and_parse`
reads the source file directly (read-only), so `--workers > 1` is safe.
