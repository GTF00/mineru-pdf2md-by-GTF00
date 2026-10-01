---
name: mineru-pdf2md
description: |-
  Convert a local PDF (or a whole folder of PDFs) into Markdown documents with
  printed page-number markers, using the MinerU OpenAPI v4 (mineru.net). Use when
  the user hands over a PDF file or a directory of PDFs and wants them parsed into
  Markdown, especially with per-page markers that keep the real printed page
  numbers (not just sequential order) and a choice of whether to keep extracted
  images. Also supports batch processing of directories, batch verification of
  outputs, and a no-API inventory helper. Triggers: "用 mineru 转 PDF", "把这份 PDF
  转成带页码的 md", "MinerU 解析", "批量转 PDF", "批量核验", or any request to
  convert PDF(s) to Markdown with page markers.
agent_created: true
---

# MinerU PDF -> Markdown (with printed page-number markers)

Turn a local PDF (or an entire folder of PDFs) into clean Markdown where every
page begins with a comment marker like "第 12 页 | 印刷页码: 354". The "印刷页码"
(published page number) is read from MinerU's own `page_number` blocks, so it
reflects the real number printed on the paper (front matter that isn't numbered
is left blank), not a 1-based sequence.

The skill wraps the MinerU OpenAPI v4 (`https://mineru.net/api/v4`) with a
Bearer token stored locally. The converter logic lives in
`scripts/mineru_convert.py` — do **not** re-implement it; invoke the script.

> **MinerU 4.0 — this skill uses the cloud API, not the local CLI.** The upstream
> `opendatalab/mineru` repo now ships its own `skills/mineru`, but that one drives
> the **local** MinerU 4.0 CLI/SDK (`mineru parse`, `mineru read`, `mineru-kit`, a
> local doc library, and `flash/basic/standard/advanced` tiers that need
> locally-installed models + GPU/RAM). This skill instead uses the **cloud
> OpenAPI v4** (`mineru.net`), which needs no local GPU and — crucially — returns
> MinerU's own `page_number` blocks, the source of the printed-page markers this
> skill is built around. So we did **not** replace the architecture; we ported the
> genuinely new *cloud-API* capabilities (see "MinerU 4.0" below) into it and kept
> every special feature (auto split/merge, printed-page markers, batch, heading
> restoration, page audit/repair, decorative-image filtering, char-spacing cleanup).

## Inputs the skill needs

- **PDF path or directory** (required): a local file or folder the user provides.
- **Output directory** (guided): where to write `stem.md` and `stem_files/`.
- **Save mode** (guided): `full` (Markdown + extracted image folder) or `md-only`
  (Markdown only, image blocks dropped). In `full` mode, decorative images
  (logos, borders, dividers, unlabeled icons) are auto-dropped — only meaningful,
  captioned figures/charts are kept; see "Decorative image filtering" below.
- **For a directory**: also confirm **scope** (whole tree vs. specific subfolder)
  and optionally **concurrency** (`--workers`).

## Guided interaction (ALWAYS do this before converting)

When the user gives a path and invokes this skill, **do not assume** output
location or save mode. Use `AskUserQuestion` to confirm:

If the path is a **single PDF**:
1. **Output directory** — default to the PDF's own directory (source dir).
   Offer: source directory (recommended) / a custom path / Desktop / Downloads.
2. **Save mode** — `Markdown + images` (recommended) or `Markdown only`.

If the path is a **directory of PDFs** (batch):
1. **Scope** — whole tree (recommended) or just one subfolder they name.
2. **Output directory** — default: a new sibling folder next to the source
   (e.g. source dir named `3 代表理论家与学说` -> output `3 代表理论家与学说_md`)
   so the mirrored subfolder structure stays obvious. Offer a custom path too.
3. **Save mode** — `Markdown + images` (recommended) or `Markdown only`.
4. **Concurrency** — default 2 workers; raise only if the user wants speed and
   accepts possible API rate-limiting. Mention it.

Keep questions short, e.g. "整目录还是某个子文件夹？输出到哪？连图片一起吗？"

**Before launching a large batch** (dozens+ of PDFs), run `inventory` first so
the user sees the file count, total pages, and how many exceed 200 pages. This
costs no API calls and prevents surprises.

## Running the conversion

Use the managed Python venv (it already has `pypdf` for over-200-page auto-split
and for inventory/verify page counts):
`/Users/yu/.workbuddy/binaries/python/envs/default/bin/python3`.
If that venv lacks `pypdf`, install it first with that venv's `pip install pypdf`.

Map the user's choices to arguments:
- Save mode `full`    -> omit (default) or pass `--full`
- Save mode `md-only` -> pass `--md-only`

### Single file
```bash
# Single file (auto-splits if over --max-pages, default 180), full mode:
(VENV_PY) scripts/mineru_convert.py convert "(PDF)" "(OUT_DIR)" --model vlm

# Single file, md-only:
(VENV_PY) scripts/mineru_convert.py convert "(PDF)" "(OUT_DIR)" --md-only

# Partial parse of pages 1-10 (MinerU 4.0 page_ranges; skips local auto-split):
(VENV_PY) scripts/mineru_convert.py convert "(PDF)" "(OUT_DIR)" --pages "1-10"

# Scanned/bitmap PDF -> enable OCR; non-Chinese-only book -> --lang en:
(VENV_PY) scripts/mineru_convert.py convert "(PDF)" "(OUT_DIR)" --ocr --lang en
```

### Batch (whole directory)
```bash
# Mirror the folder tree under OUT_DIR, full mode, 2 workers, resume skipped:
(VENV_PY) scripts/mineru_convert.py batch "(IN_DIR)" "(OUT_DIR)" --model vlm

# md-only, 4 workers, re-run even existing md (--force):
(VENV_PY) scripts/mineru_convert.py batch "(IN_DIR)" "(OUT_DIR)" --md-only --workers 4 --force

# Whole batch with OCR on + English OCR hint (4.0 flags apply to every file):
(VENV_PY) scripts/mineru_convert.py batch "(IN_DIR)" "(OUT_DIR)" --ocr --lang en --workers 4

# Whole batch, only the intro + first chapters of every PDF (4.0 page_ranges):
(VENV_PY) scripts/mineru_convert.py batch "(IN_DIR)" "(OUT_DIR)" --pages "1-30"
```
- The folder structure under `IN_DIR` is mirrored under `OUT_DIR` by default, so
  each source PDF `IN_DIR/A/x.pdf` becomes `OUT_DIR/A/x.md` (+ `x_files/`).
- **Auto place in corresponding subdir**: if `OUT_DIR` already contains
  subfolders whose names match the *tail* of a source file's relative path (i.e.
  the output hierarchy is already similar to the source), each result is written
  into that matching subfolder instead of re-creating the full mirror from the
  root. Example: source `IN/theorists/Alexa/x.pdf` with an existing `OUT/Alexa/`
  lands at `OUT/Alexa/x.md`. If `OUT_DIR` is empty or unrelated, it mirrors the
  full structure from the root (current behavior). This means you can point the
  batch at an already-organized output tree and results drop into the right
  places automatically — no need to specify subfolders per file.
  - **HAZARD — auto-placement can FLATTEN the tree.** If a source file's *parent*
    directory name happens to equal the name of a directory that already exists
    at the **top level of OUT_DIR**, the tail-match fires and the file is written
    flat into that top-level dir, losing its real intermediate path — and worse,
    if the flattened path differs from where an already-converted copy lives, the
    file looks "missing" and gets **re-converted**. Real case: source
    `…/4 Heimat/论文/x.pdf` with an existing top-level `OUT/论文/` produced
    `OUT/论文/x.md`, silently dropping the `4 Heimat/` level (40 files affected).
    **Guard before a big batch**: list the top-level dirs of OUT_DIR, list all
    *nested* dir names of IN_DIR, and check for collisions. If a colliding
    top-level OUT dir is an **empty placeholder**, delete it — auto-placement
    then falls back to a full mirror, which is correct. Verify afterwards by
    confirming no unexpected `.md` sits directly at the OUT_DIR root.
- Files whose `.md` already exists are **skipped** (resume). Use `--force` to redo.
- A `_batch_manifest.jsonl` is written (one JSON line per file: source, md,
  status, pages, chunks, images, error) — feed it to `verify` planning.

### Verify (batch check of outputs)
```bash
# Check all generated md under OUT_DIR (page markers + image refs resolve):
(VENV_PY) scripts/mineru_convert.py verify "(OUT_DIR)"

# Also cross-check the last page marker against each source PDF's real page count:
(VENV_PY) scripts/mineru_convert.py verify "(OUT_DIR)" --source "(IN_DIR)"
```
- Writes `_verify_report.md` (a table: status / last page / image refs / missing /
  note / file). Status values: `OK`, `WARN(有跳过页)`, `WARN(页码不符)`,
  `缺图N` (N missing image files).
- Non-MinerU `.md` files in the tree are skipped automatically.

### Inventory (planning, no API cost)
```bash
(VENV_PY) scripts/mineru_convert.py inventory "(IN_DIR)"
```
Lists every PDF with its page count and whether it needs splitting (> `--max-pages`,
default 180; MinerU hard limit is 200). Prints totals at the end.

Notes:
- `model_version` is `vlm` by default; `auto` is the lighter/faster alternative.
- Large/long PDFs take minutes — run `batch` in the background and report when it
  finishes. The script prints `BATCH DONE: ok=.. skipped=.. failed=..` at the end.

## Post-processing: restore Markdown heading levels

MinerU emits chapter/section titles as **plain bare lines** — a whole thesis can come
back with zero `#` marks, so there is no outline to navigate and no way to split by
section. `scripts/add_headings.py` rebuilds the hierarchy from Chinese academic
numbering conventions:

```bash
# preview only (never writes) — ALWAYS do this first
(VENV_PY) scripts/add_headings.py "(OUT_DIR)" 相对/文件.md --preview=30

# apply to specific files (recommended: name them, don't point at a tree)
(VENV_PY) scripts/add_headings.py "(OUT_DIR)" a.md "sub/b.md"
```
- Writes in place; a `.md.orig` backup is created **once** (not overwritten on re-run).
- Rules: line must be standalone (blank line above & below), ≤60 chars, no HTML/table
  chars, and **must not end in 。；，：or a non-numeric period** (that last rule is what
  keeps numbered list *sentences* from being promoted to headings).
- **TOC lines are skipped**: a line with dot leaders (`......`) or a trailing page
  number is a table-of-contents entry, not a real heading — otherwise the TOC pages
  would turn into a second copy of the outline.
- **Per-document level adaptation** (`decide_levels`): counts which numbering style the
  file actually uses, so one script handles all three conventions seen in CN theses:
  - `一、` dominant → `一、`=H2, `（一）`=H3, `1.`=H3
  - only `（一）` → `（一）`=H2
  - numeric-only (e.g. 胡志红《西方生态批评研究》uses `1. 2.` throughout) → `1.`=H2,
    otherwise the file would have **no H2 at all**
- H1 = `第X章` / 绪论 / 导论 / 结论 / 结语 / 参考文献 / 致谢 / 附录 / 摘要 / Abstract.
- **German books** (a sibling script `restore_headings_plus.py` handles these too — it
  is the drop-in superset of `add_headings.py`): 部 `I./II.`=H2, 章 `1.`=H3（有罗马部时）
  或 H2（无罗马部，如 Bergthaller 式）, 子节 `2.1`=H3, 节 `a)`=H4, 结构词
  `Vorwort/Einleitung/Vorbemerkung/Inhalt/…`=H1. Four hardening rules learned on
  Seel《Die Macht des Erscheinens》(2007, stw 1867):
  - **Standalone bare numbers are NOT headings** (`2.`, `3.`, `I.` on their own line).
    Suhrkamp-style books use isolated numbers as in-essay section markers; without a
    letter in the line the CN numeric rule would promote them to `## 2.` noise.
  - **A Roman "part" must be followed by a CAPITAL** (`II. Räume …`, not `II. die …`).
    Otherwise lowercase Roman list items flip `has_roman` true and wrongly demote every
    `1./2.` from H2 to H3.
  - `decide_de_levels` must apply the SAME candidate filter (length/punctuation) as
    `classify` when scanning for `has_roman` — a long body line starting `III. Ich …`
    otherwise counts as a part.
  - German headings don't end with a bare `.`; reject trailing `\.` (mirrors the CN
    rule) — kills list items (`1. Fotografie ist … Bildmedium.`) and the end-of-book
    Erstdrucke/copyright lines (`… – Originalbeitrag.`, `… – zuerst erschienen in: … v.`).
  - Practical limit: in collections where essays and their internal sub-sections BOTH use
    `N.` , the two levels are numerically ambiguous (essay 1 §2 vs essay 2). They will be
    merged at one level; also fix obvious `II.`→`11.` OCR misreads of essay numbers
    *before* running, so the level decision is right.
- Safe to re-run; verify afterwards with `verify` (page markers are untouched) and
  spot-check one file with `--preview`.
- Note: MinerU sometimes omits the `<!-- 第 N 页 -->` marker for blank or pure-image
  pages (seen: 2–3 pages missing per book). This predates this script — compare against
  `.md.orig` before blaming post-processing.

## Post-conversion page-number audit & repair

After a batch — or any time you doubt a tree of `.md` — audit and repair the printed
page numbers **locally with no MinerU API call** (free and instant). Two helpers live
in `scripts/`:

### `check_pages.py` — audit (read-only)
```bash
(VENV_PY) scripts/check_pages.py "(OUT_DIR)"     # or omit OUT_DIR to scan cwd
```
Walks OUT_DIR for MinerU `.md`, extracts every `印刷页码:` marker in document order,
and cross-checks the sequence (前后两到三页相互佐证). It prints three tiers:
- **第一层 疑似 OCR 误读** — isolated outliers where the neighbours rejoin a +1 run
  (e.g. `251, 26, 253` → `252`); these are the high-value corrections.
- **第二层 非错误** — recto-only numbering (recorded step 2, normal), section/extract
  starts that resume +1 (normal), chapter-internal renumbering (正常), duplicated
  pages, gaps (possibly missing pages, 需人工核对), and unnumbered (cover/blank) pages.
Run it to decide whether to run `fix_pages.py`.

### `fix_pages.py` — repair (in-place, idempotent)
```bash
(VENV_PY) scripts/fix_pages.py "(OUT_DIR)" --dry-run   # preview changes
(VENV_PY) scripts/fix_pages.py "(OUT_DIR)"             # rewrite 印刷页码: markers
```
Reuses the skill's `_norm_printed` (`I/l/|→1`, `O→0`, roman numerals preserved) and
`_verify_page_sequence` (smart cross-page correction) to rewrite ONLY the
`印刷页码:` markers in place; body text and images are untouched. **Idempotent**: a
second run is a no-op. Always `--dry-run` first to preview the change count.

**Note**: `reconstruct()` already applies the same normalization + cross-page
correction when it builds each `.md`, so fresh conversions are correct by
construction. Use `check_pages.py`/`fix_pages.py` only for trees produced by older
code, or as a routine sanity check on any converted tree.

### Back-filling 印刷页码 into `.md` that never had it

`check_pages.py` can only *repair* a `印刷页码:` marker that already exists. When a
`.md` has **zero** page markers, you must decide between three cases — never guess:

1. **No markers at all → re-convert the source PDF** (do NOT try to inject by hand).
   Tell-tale: filename `MinerU_markdown_<name>_<19-digit id>.md` (a MinerU *web-UI*
   export) — one book often arrives as N jumbled fragments (a 422-page book as 3
   chunks, contents in **reverse** id order). These fragments carry no page info and
   their split points are arbitrary, so page numbers are **not** recoverable per
   fragment. Re-convert the source PDF with this script; the result is one ordered,
   fully page-marked `.md` (verify the byte size ≈ the sum of the fragments). Then
   archive the fragments into a `_旧碎片_*` subdir (reversible) rather than deleting.
2. **A custom marker convention → map and inject.** Seen in this library: a
   hand-assembled `…_合并完整版_含页码.md` using `<!-- citation-page: unpaginated -->`
   + `<!-- source-pdf-page: N -->` pairs (N = PDF page) and declaring "cite
   citation-page only". Build a `pdf_page → printed_page` map, then rewrite the pair
   to `<!-- citation-page: M -->` / `<!-- source-pdf-page: N | 印刷页码: M -->`
   (leaving genuinely unnumbered pages as `unpaginated`). Two independent sources for
   the map, **cross-validate and union them**:
   - a **sibling MinerU `.md`** of the same book (`第 N 页 | 印刷页码: M`);
   - the **PDF text layer** itself — e.g. the De Gruyter layout appends the printed
     number to the running head (`2 Ökokosmopolitismus22`, `15 Bukolik …188`) or
     prints it as a standalone first line (`81`, `302`); regex the first non-empty
     line for trailing digits.
   Measured on Dürbeck/Stobbe *Ecocriticism* (311 pp): the two sources **never
   conflicted** (279/279 agree); the text-layer route merely missed verso pages the
   sibling had, and covered 17 pages the sibling lacked → union gave 296/311.
3. **The source genuinely has no printed page numbers → say so, do not fabricate.**
   An unpublished manuscript PDF ("初稿合成版") may show no folio anywhere; the
   standalone numbers in it are **continuous footnote numbers** (e.g. `78`/`79`
   repeated in text and at the page foot), not pages. MinerU agrees — it emits no
   `page_number` block, so the converted `.md` legitimately gets `<!-- 第 N 页 -->`
   with **no** `印刷页码:`. Report this instead of inventing numbers.

**A gap is not always a bug.** De Gruyter eBook PDFs **drop** print pages, so the
printed sequence can jump (…184, then 187, 188…) while the PDF pages are continuous;
and every **chapter-opening page plus the colophon** is unnumbered. Verify a
suspicious value by reading that page's own text layer before "fixing" it.

## MinerU 4.0: new cloud-API capabilities (added in this version)

The upstream MinerU 4.0 (Sept 2026) changed a lot; we folded in the parts that
apply to the **cloud OpenAPI v4** this skill uses, and explicitly did **not**
adopt the parts that belong to the local CLI only.

### Adopted (cloud API v4 request-body fields — all opt-in, safe defaults)
- **`--pages RANGES`** → cloud `page_ranges` (e.g. `"1-10"`, `"2,4-6"`). Partial
  parse; the API selects the pages, so local pypdf auto-split is skipped and the
  page markers count within the chosen range. Great for "just the intro + ch.1".
- **`--lang ch|en`** → cloud `language` OCR hint. Default is the API's `"ch"`;
  pass `en` for non-Chinese-only sources (the VLM still reads multilingual text).
  For German academic books `en` usually beats `ch`; try both and spot-check.
- **`--ocr`** → cloud `is_ocr`. Off by default; turn on for scanned/bitmap PDFs
  that otherwise come back empty.
- The result zip still delivers `full.md` + `content_list.json` + `images/` — the
  inputs your printed-page markers, heading restoration, and page audit rely on.
  The API's `extra_formats` (docx/html/latex) is left off on purpose.

### NOT adopted (local-CLI-only in 4.0 — would break the cloud skill)
- The `flash/basic/standard/advanced` **tier** flags: those are `--tier` on the
  local `mineru`/`mineru-kit` CLI. The cloud API v4 still selects quality via
  `model_version` (`vlm` = top quality ≈ the local `advanced/standard`;
  `pipeline` = fast ≈ local `basic`). The cloud "flash" tier exists only via the
  no-token Agent lightweight API (≤10 MB / ≤20 pages) — out of scope here.
- The local **doc library** (`mineru server start`, `DoclibClient`,
  `doc:{short_id}/tier:.../page:...` locators) and `mineru read` — the cloud
  workflow has no persistent server to query.
- Local parsing of **doc/docx/ppt/xls/images/epub/ofd/html** via the CLI: the
  cloud API v4 accepts some of these, but your page-marker reconstruction reads
  `page_number` blocks that only come from PDF/paged sources, so keep PDF as the
  front door (use the separate python-docx path for `.docx`, as before).

### Official 4.0 Python SDK (alternative, not required)
MinerU 4.0 published `mineru-open-sdk` (`pip install mineru-open-sdk`, needs only
`httpx`, Python ≥3.10) wrapping the same cloud API:
`MinerU(token).extract(path, pages=..., ocr=..., language=..., model=...,
extra_formats=[...])`. Handy for a quick one-off inside another script, but it
does **not** do your printed-page markers, auto split/merge, decorative-image
filtering, char-spacing cleanup, heading restoration, or batch manifest — so the
bundled `mineru_convert.py` remains the recommended path for this skill's whole
workflow.

## Critical gotchas (learned the hard way)

- **Token**: read from `$MINERU_API_TOKEN_FILE`; the fallback local path is
  `/Users/yu/Documents/Codex/2026-08-27/ban/work/secrets/mineru_api_token`.
- **OSS upload 403**: when PUT-ing the file bytes to the presigned URL, send
  **no `Content-Type` header at all** (MinerU's docs confirm this). Python's
  `urllib`/`requests` sneak in `application/x-www-form-urlencoded`, which breaks
  the OSS signature -> `403 SignatureDoesNotMatch`. The bundled script already
  uses raw `http.client` PUT to avoid this. Don't "fix" it by adding Content-Type.
- **Query endpoint**: poll with `GET /v4/extract-results/batch/{batch_id}`
  (NOT `/v4/extract/task/batch/...`, which 404s).
- **200-page limit**: a single call rejects PDFs over 200 pages — `batch` and
  `convert` auto-split such files with `pypdf` (default chunk size 180, leaving
  headroom). The page markers are re-numbered to global order; printed page
  numbers are preserved from the real `page_number` blocks.
- **Chunk-size failure (learned the hard way)**: at the default `chunk size 180`,
  MinerU's backend **intermittently fails to parse the first chunk (pages 1–180)**
  of large PDFs with `parsing failed, please try again later`, while smaller later
  chunks succeed. The batch then writes a `<!-- 第 N 页起解析失败，跳过 -->` comment
  and **still reports the file as `ok` in `BATCH DONE`** — so the `ok` count is
  **misleading**; a file can be e.g. 60% complete and still counted `ok`. Always
  post-check after a batch: `grep -l '解析失败' OUT_DIR/*.md` (any hit = partial),
  and compare each file's `印刷页码` marker count against `inventory` page counts
  (a big gap = dropped chunk). If chunk 1 keeps failing, **re-run the affected
  files with `--max-pages 100`** — every chunk ≤100pp parses reliably. Before
  re-running, rename the partial `.md` to `.md.failed` so resume skips the good
  files and re-converts only the broken ones (a partial `.md` that already exists
  would otherwise be skipped as "done").
- **Mixed PDF + DOCX dirs (real-world manuscript folders)**: this skill only
  handles `.pdf`. A book-manuscript folder often mixes `.pdf` AND `.docx`
  (drafts, translations, articles) plus Office lock files (`~$*.docx`). Convert
  the `.docx` separately with a **local** `python-docx` → Markdown script
  (no API, fast, writes `.md` next to each source) while the PDF batch runs —
  pandoc is usually not installed here. Skip `~$*.docx` lock files. Then run the
  PDF `batch` as normal. **Same-stem collision trap**: if a document exists as
  BOTH `x.pdf` and `x.docx`, the docx→md step writes `x.md` first; MinerU's
  resume logic then sees `x.md` already exists and **silently skips the PDF**,
  losing the page-marked version. Filenames with accented Latin text also hit
  NFC/NFD normalization mismatches that make naive `[ -e x.md ]` checks miss the
  collision. Fix: before launching the PDF batch, rename any docx-derived
  `x.md` to `x._docx.md` (keep both, user deletes later) so the PDF batch writes
  the canonical page-marked `x.md`. Detect collisions with a Python NFC compare,
  not shell globs.
- **Image folder**: in split mode each chunk's images are copied into the final
  `stem_files/` dir *immediately* after that chunk parses, because each download
  uses its own unique temp dir (thread-safe for concurrent batches). Don't change
  this to a post-loop collection.
- **Char-spacing cleanup**: MinerU sometimes emits the OCR artifact where a word
  has a space after every letter (e.g. "m e a n i n g"). `reconstruct` runs a
  `_fix_char_spacing` pass that collapses any run of >=4 single-letter ASCII
  tokens back into one word ("m e a n i n g" -> "meaning"), while leaving normal
  prose, numbers, punctuation and Chinese text untouched. Only single-letter
  tokens count as run members, so legitimate 2-letter words (of, in, is, to) are
  never swallowed. It is applied to text/title/caption blocks but deliberately
  NOT to equation blocks or table HTML, so LaTeX spacing is preserved. If a real
  isolated-letter sequence gets over-merged, raise `min_run` in `mineru_convert.py`.
- **Decorative image filtering**: in `full` mode, image/chart blocks that look
  decorative are dropped automatically so the `stem_files/` folder stays free of
  logos, rules, dividers and unlabeled icons. A block is dropped only when it has
  **no caption** AND its `bbox` (MinerU's 0–1000 normalized geometry) is either
  tiny (`max side < _DECO_TINY=60`, an icon/logo) or extreme-aspect
  (`max/min side ratio > _DECO_ASPECT=12`, a border/rule/divider). Any block with
  a caption (`image_caption`/`image_footnote`/`chart_caption`/`chart_footnote`)
  is always kept as a real figure. Geometry alone is used (no image decoding), so
  no Pillow dependency. To keep ALL images, re-run with `drop_decorative=False`
  (expose it as a `--keep-decorative` flag if you want a CLI toggle).
- **Printed page-number verification (smart, 前后两到三页佐证)**: MinerU
  frequently misreads digit `1` as `I`/`l`/`|` and `0` as `O` in printed page
  numbers (e.g. `14`→`I4`, `120`→`I2O`). `reconstruct` normalizes these (only the
  unambiguous UPPERCASE confusions; genuine roman front-matter numerals like
  `xii`/`II` are preserved). It then cross-verifies the whole page sequence:
  a page is auto-corrected only when its printed number breaks an otherwise +1
  run AND BOTH adjacent steps are broken (the page is an isolated outlier with
  the 2-page-out neighbours clean +1) — e.g. `251, 26, 253` → `252`. A section/
  extract start (number drops then resumes +1) or chapter-internal renumbering
  (a long run of low numbers 1,2,3…) is NOT changed. To audit and fix an
  already-converted tree WITHOUT re-calling MinerU, run the helper
  `fix_pages.py` (local, idempotent) — it rewrites only the `印刷页码:` markers
  in place, leaving body text and images untouched.
- **Concurrency**: `--workers` defaults to 2. Raising it speeds big batches but
  may trip MinerU rate limits — if you see repeated `FAILED`/`403`, lower it or
  re-run with `--force` (resume skips the ones that already succeeded).
- **Batch is resumable**: interrupted runs leave partial outputs; re-run the same
  `batch` command and existing `.md` files are skipped automatically.

### Operational pitfalls (this machine / long runs)

- **Image folder is named `<stem>_files`, NOT `_files`**: e.g.
  `2026 The-Futures-We-Tell_Springs-10_2026_files/`. To monitor batch progress,
  count `*.jpg`/`*.png` under OUT_DIR or match the `*_files` suffix — `find -name
  '_files'` (exact basename) and `os.walk` with `d == '_files'` match **nothing**
  and will falsely report zero images. Don't be fooled into thinking images are
  missing.
- **Encrypted PDFs need a crypto backend — install `pycryptodome`, NOT
  `cryptography`**: most Chinese academic PDFs (CNKI / 万方 / 高校学位论文库) are
  AES-encrypted with an empty user password. `pypdf` reads their page count fine
  but fails when *splitting* (>180 pages), logging
  `WROTE: ….md | failed DependencyError('cryptography>=3.1 is required for AES
  algorithm')` — the whole batch then "finishes" in seconds with error stubs
  instead of content. `pypdf._crypt_providers` accepts **either** `cryptography`
  **or** `pycryptodome`; on this machine `pip install cryptography` **fails**
  (`metadata-generation-failed`, needs Rust + disk headroom) after ~6 min. Use
  the pure-wheel alternative instead (installs in ~46 s):
  ```bash
  (VENV_PY) -m pip install --no-cache-dir --only-binary :all: pycryptodome
  (VENV_PY) -c "import pypdf._crypt_providers as cp; print(cp.crypt_provider)"
  # -> ('pycryptodome', '3.23.0')   <-- fix confirmed
  ```
  **Symptom check**: if a batch of 200+ page PDFs reports DONE in under a minute,
  it failed this way. Always open one `.md` and eyeball the body before trusting
  any "DONE"/"7/7" line — the resume logic below treats a stub as "already done"
  only if it exceeds ~20 KB, so verify by content, not by count.
- **Long batches in the sandbox: launch with the Bash tool's
  `run_in_background=true`**: the sandbox kills a background task by its whole
  process *tree* (cgroup) **as soon as the Bash tool call that spawned it
  returns** — `nohup … &`, plain `&`, and `disown` are all dead on arrival, and
  macOS has no `setsid` binary anyway. Empirically: a `nohup`-launched runner was
  alive *during* the call that launched it (BEGIN log lines appeared) but `pgrep`
  returned 0 on every later call; the only trace left was orphaned
  `mineru_chunk_*.pdf` files in TMPDIR. The **only** thing that survives across
  turns here is starting the script through the Bash tool with
  `run_in_background=true` (verified: a 5 m 50 s `pip install` and a 4 m 56 s
  7-PDF / 1670-page batch both ran to completion that way), then collecting
  output with `TaskOutput` (it notifies on finish; poll with timeout ≤ 10 min).
  Keep the `while true` self-restart wrapper (`run_parent_batch.sh`) as a
  *secondary* net — it heals crashes *inside* a run (and is still the right shape
  for 100+ PDF / multi-hour jobs launched from the user's own terminal), but it
  cannot survive the cgroup kill, because the wrapper dies with the tree.
  **`ps` is blocked in the sandbox** ("operation not permitted") — use
  `pgrep -fl <pattern>` for liveness checks.
  **A background task can come back `failed` even though the batch succeeded**:
  at exit the sandbox may refuse the unlink of its own toybox temp files
  (`file-write-unlink` in Stderr) and that alone flips the status to failed.
  Always read the log / the `BATCH DONE: ok=… failed=…` line before believing the
  status. Same for `open(..., "w")` on a file the sandbox already indexed:
  `Brokered file token refused: modify backup failed` / `path index collision` —
  writing to a *new* filename in the same dir always works (used that to write
  `_manifest_20260921.jsonl` when `_batch_manifest.jsonl` was locked).
- **DISK SPACE — the #1 cause of mid-batch failure on big runs**: every PDF is
  downloaded as a zip and extracted to a temp dir (`mineru_extract_*`). With high
  concurrency and large books this can exhaust the disk, after which `tempfile`
  fails with `No usable temporary directory` and the whole batch collapses.
  Before a 100+ PDF run: check `df -h`, and **redirect the temp dir to the
  largest volume** — `export TMPDIR="/Volumes/<big drive>/.mineru_tmp"` (create it
  and clean `mineru_*` leftovers at start). Python's `tempfile` honours `TMPDIR`.
  Real case: system disk hit 100% (20 MiB free); moving temp to the external drive
  (171 GiB free) not only fixed it but *raised* throughput to 7.6 files/min.
- **Clean up your own `mineru_extract_*` leftovers**: when a batch is killed the
  temp dirs survive and accumulate fast (one case: 577 dirs / 5.86 GiB). They are
  safe to delete — they are created by this script, matched by the exact
  `mineru_extract_` prefix. Never blanket-delete anything outside this prefix.
  **Since 2026-09-21 the script self-cleans**: `process_file()` removes the
  extraction dir in a `finally` block (both the split and no-split paths), deletes
  the result zip right after extraction (halves peak usage), and removes the
  `mineru_chunk_*.pdf` splits it created. So accumulation now only happens if the
  process is SIGKILLed — verified on a 2611-page / 3-PDF run: temp dir stayed at
  ~420 K and ended with 0 leftover dirs.
- **Tune `--workers` — 4 is the safe ceiling here, NOT 6–8**: measured on this
  corpus 2 workers ≈ 0.55, 4 ≈ 2.0 files/min. Pushing to 8 hit MinerU's *concurrent
  queue* limit and returned `429 queue.full` / `queue.waiting` (the job is rejected
  before parsing, not a daily-quota error). Stay at **4**; the `http()` retry added
  for 429 will self-heal the occasional transient 429 but cannot beat a sustained
  queue-full from over-concurrency. Measure with a long window (several min) — a
  short 95 s window is pure noise because >180-page books pause output while being
  split into chunks.

- **Rate limit (429)**: two flavours. (a) *Daily-quota* 429 from the model gateway
  — resets ≈ next day UTC+8; on this, stop and wait, don't tight-loop. (b) *Queue-full*
  429 (`queue.full` / `queue.waiting`) from too many concurrent jobs — raised at
  8 workers here. `http()` now catches 429 and backs off (up to 90 s, 5 tries)
  before retrying, so a transient queue-full heals itself; but a sustained one means
  you're over-concurrent — drop `--workers` to 4. Never tight-loop manual retries.
- **Do NOT regress two fixed bugs**: (1) `_finalize` MUST copy referenced images into
  the `<stem>_files` dir — images only exist in the temp extraction dir, so a
  single-file branch that skips the copy produces `md` with broken image links.
  (2) argparse subparsers the dispatcher reads (e.g. `args.save`) must set a default;
  omitting it crashes `inventory`/`verify`/`batch` with `AttributeError`.

## Deliverable & reporting

After a single-file convert, tell the user:
- The `.md` path and (if full mode) the sibling `_files/` folder.
- Total pages / number of page markers.
- That `印刷页码` reflects the real printed number when available.

After a **batch**, tell the user:
- The output directory and that the source tree was mirrored.
- `ok / skipped / failed` counts from the final `BATCH DONE` line.
- The `_batch_manifest.jsonl` path (for re-runs / auditing).
- Run `verify` and point them to `_verify_report.md`; call out any `WARN`/`缺图`.
Then use `present_files` to surface the `_verify_report.md` (and a sample `.md` or
one or two images if full mode). If any chunk reported `PARSE FAILED`, say which
page range was skipped (it appears as a "解析失败，跳过" comment in the md).
