#!/usr/bin/env python3
"""MinerU PDF -> Markdown with printed page-number markers.

Modes (run `python3 mineru_convert.py <mode> ...`):

  reconstruct (extracted_dir) (out_md) [--offset 0] [--md-only]
      Rebuild a page-marked .md from an already-extracted MinerU result dir
      (must contain *content_list.json and images/). --offset shifts the
      "第 N 页" marker so merged chunks keep global page order.

  convert (input_pdf) (output_dir) [--model vlm] [--md-only|--full]
          [--pages RANGES] [--lang ch|en] [--ocr] [--max-pages 180]
      Single-file pipeline: upload -> poll -> download -> reconstruct -> write.
      Files over --max-pages (default 180; MinerU hard limit 200) auto-split.
      New in MinerU 4.0 (cloud OpenAPI v4):
        --pages RANGES  Partial parse, e.g. "1-10" or "2,4-6". The API selects
                        the pages and local auto-split is skipped; page markers
                        count within the chosen range.
        --lang ch|en    OCR/language hint (default: API default "ch"). Pass "en"
                        for non-Chinese-only sources; the VLM stays multilingual.
        --ocr           Enable OCR for scanned/bitmap PDFs (default off).

  split_convert (input_pdf) (output_dir) [--model vlm] [--max-pages 180] [--md-only|--full]
          [--pages RANGES] [--lang ch|en] [--ocr]
      Alias of convert (auto-split is now built into convert). Kept for CLI compat.

  batch (input_dir) (output_dir) [--model vlm] [--md-only|--full]
        [--workers 2] [--max-pages 180] [--force] [--pages RANGES] [--lang ch|en] [--ocr]
      Walk input_dir for *.pdf, mirror the folder structure under output_dir,
      convert each (auto-splitting >max-pages unless --pages is given). Skips
      files whose .md already exists unless --force. Writes _batch_manifest.jsonl
      (one JSON per file). The 4.0 page/lang/ocr flags apply uniformly to the
      whole batch.

  verify (output_dir) [--source (src_dir)] [--report (path)]
      Scan output_dir for MinerU-generated .md, verify page markers are present
      and every image reference resolves to a real file in the sibling _files/
      dir. With --source, also cross-checks the last page marker against the
      source PDF's real page count. Writes _verify_report.md.

  inventory (input_dir) [--max-pages 180]
      List every PDF under input_dir with its page count and whether it needs
      splitting (>max-pages). No API calls. Useful for planning a batch.

save_images (full mode):
  writes the .md AND a sibling "<stem>_files/" image folder, rewriting image
  links to point at it.
md-only mode:
  writes the .md only and drops image-block lines (captions kept).

Token is read from $MINERU_API_TOKEN_FILE, falling back to the known local path.
Only the Python standard library is required except batch/inventory (need pypdf).
"""
import sys, os, json, glob, zipfile, shutil, re, time, tempfile, random, socket
import urllib.request, urllib.parse, urllib.error
import http.client as httplib

TOKEN_FILE = os.environ.get(
    "MINERU_API_TOKEN_FILE",
    "/Users/yu/Documents/Codex/2026-08-27/ban/work/secrets/mineru_api_token",
)
BASE = "https://mineru.net/api/v4"
UA = {"User-Agent": "workbuddy-mineru/1.0"}


def load_token():
    with open(TOKEN_FILE) as f:
        return f.read().strip()


def http(method, url, token=None, data=None, headers=None, timeout=120, max_retries=5):
    """HTTP GET/POST with retry on 429 (MinerU queue full) and transient
    network errors. Without this, a 429 raised straight out of upload_and_parse
    and got recorded as a per-file failure; under high concurrency it floods the
    batch with avoidable failures. Now we back off and retry instead."""
    h = dict(UA)
    if headers:
        h.update(headers)
    if token and "Authorization" not in h:
        h["Authorization"] = f"Bearer {token}"
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            req = urllib.request.Request(url, data=data, method=method, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < max_retries:
                wait = min(90, (2 ** attempt) * 5 + random.uniform(0, 4))
                print(f"[429 限流重试 {attempt + 1}/{max_retries}] {method} "
                      f"{url[:55]}… 休眠 {wait:.1f}s")
                time.sleep(wait)
                last_err = e
                continue
            # surface other HTTP errors to the caller (caller decides failed/skip)
            body = ""
            try:
                body = e.read().decode("utf-8", "ignore")
            except Exception:
                pass
            raise RuntimeError(
                f"HTTP {e.code} {e.reason} {method} {url}: {body[:300]}"
            ) from e
        except (urllib.error.URLError, socket.timeout, ConnectionError, TimeoutError) as e:
            if attempt < max_retries:
                wait = min(90, (2 ** attempt) * 5 + random.uniform(0, 4))
                print(f"[网络重试 {attempt + 1}/{max_retries}] {method} "
                      f"{url[:55]}… 休眠 {wait:.1f}s")
                time.sleep(wait)
                last_err = e
                continue
            raise
    if last_err:
        raise last_err
    raise RuntimeError(f"http retry exhausted: {method} {url}")


def http_bytes(url, timeout=600, max_retries=5):
    """Download a binary response body with retry on truncated/transient
    network errors. Without this, a single cut-off download (http.client
    .IncompleteRead when MinerU's result zip is truncated mid-stream) aborts the
    whole convert as 'failed' even though the backend parse already succeeded and
    the .md was never written — forcing a full re-upload + re-parse. Now we back
    off and retry the download instead."""
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            req = urllib.request.Request(url, method="GET", headers=dict(UA))
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except (urllib.error.URLError, socket.timeout, ConnectionError,
                TimeoutError, httplib.IncompleteRead) as e:
            last_err = e
            if attempt < max_retries:
                wait = min(60, (2 ** attempt) * 3 + random.uniform(0, 2))
                print(f"[下载重试 {attempt + 1}/{max_retries}] {url[:55]}… "
                      f"休眠 {wait:.1f}s ({type(e).__name__})")
                time.sleep(wait)
                continue
            raise
    if last_err:
        raise last_err
    raise RuntimeError(f"http_bytes retry exhausted: {url}")


def upload_and_parse(local_pdf, model_version, token, page_ranges=None, language=None, is_ocr=False):
    """Apply upload URL, PUT file bytes (NO Content-Type -> OSS presign match).

    MinerU 4.0 (cloud OpenAPI v4) extras — all opt-in so the default request body
    is unchanged from before:
      page_ranges : cloud 'page_ranges' (e.g. "1-10" or "2,4-6") — partial parse.
                    Caller must skip local pypdf auto-split when this is set.
      language    : "ch" (default) or "en"; for non-Chinese-only source pass "en"
                    (the VLM still handles multilingual text). Omitted when None.
      is_ocr      : enable OCR for scanned/bitmap PDFs (API default False).
                    Omitted unless explicitly requested.
    """
    name = os.path.basename(local_pdf)
    payload = {"files": [{"name": name, "data_id": "wb"}], "model_version": model_version}
    if page_ranges:
        payload["page_ranges"] = page_ranges
    if language:
        payload["language"] = language
    if is_ocr:
        payload["is_ocr"] = True
    body = json.dumps(payload).encode()
    resp = json.loads(
        http("POST", f"{BASE}/file-urls/batch", token=token, data=body,
             headers={"Content-Type": "application/json"})
    )
    print("get-upload-url:", resp.get("code"), resp.get("msg"))
    batch_id = resp["data"]["batch_id"]
    file_urls = resp["data"]["file_urls"]
    with open(local_pdf, "rb") as f:          # read the original directly (read-only, thread-safe)
        data = f.read()
    for u in file_urls:
        parsed = urllib.parse.urlparse(u)
        path = parsed.path + (("?" + parsed.query) if parsed.query else "")
        conn = httplib.HTTPSConnection(parsed.netloc, timeout=300)
        conn.request("PUT", path, body=data)
        r = conn.getresponse()
        print("PUT status:", r.status, "(read %d bytes)" % len(r.read()))
        conn.close()
    return batch_id


def poll(batch_id, token, max_iter=120, sleep_s=10):
    for i in range(max_iter):
        resp = json.loads(http("GET", f"{BASE}/extract-results/batch/{batch_id}", token=token))
        d = resp.get("data", {})
        results = d.get("extract_result")
        if results:
            states = [r.get("state") for r in results]
            print(f"poll {i}: {states}")
            if all(s == "done" for s in states):
                return [r.get("full_zip_url") for r in results]
            if any(s == "failed" for s in states):
                for r in results:
                    if r.get("state") == "failed":
                        print("FAILED:", r.get("err_msg"))
                return None
        elif d.get("state") == "done":
            return [d.get("full_zip_url")]
        elif d.get("state") == "failed":
            print("FAILED:", d.get("err_msg"))
            return None
        time.sleep(sleep_s)
    print("TIMEOUT waiting for parse")
    return None


# Common real 2-letter English words that must NOT be absorbed into a collapsed
# artifact run (e.g. "m e a n i ng of" -> "meaning of", not "meaningof").
_COMMON2 = {
    "of", "in", "is", "to", "on", "at", "by", "an", "or", "as", "be", "he",
    "we", "me", "it", "so", "no", "my", "do", "go", "up", "if", "us", "am",
    "ex", "ah", "oh", "hi", "ya", "lo", "yo", "id", "ok", "tv", "bi", "mr",
    "ms", "dr", "st", "nd", "rd", "ha", "ho", "bo", "da", "fa", "la", "ma",
}


def _is_tiny_word(tok):
    """A short (<=2 char) pure-ASCII-letter token that may belong to the
    'm e a n i ng' spacing artifact. Real 2-letter words (of, in, is, to...) are
    excluded so they are never swallowed. Digits, punctuation and non-ASCII
    (e.g. Chinese) tokens return False and break the run."""
    if len(tok) == 0 or len(tok) > 2:
        return False
    if not (tok.isascii() and tok.isalpha()):
        return False
    if len(tok) == 2 and tok.lower() in _COMMON2:
        return False
    return True


def _fix_char_spacing(text, min_run=4):
    """Collapse the OCR/extract artifact 'm e a n i ng' -> 'meaning'.

    A run of tiny ASCII-letter tokens is collapsed into one word only when it is
    long enough (>= min_run) to be an artifact rather than genuine isolated
    letters (e.g. 'a to b' stays 'a to b'). A trailing 2-letter non-word fragment
    like the user-typed 'ng' is kept inside the run, so 'm e a n i ng' -> 'meaning'.
    Common 2-letter words (of/in/is/to...) break the run, so 'm e a n i ng of' ->
    'meaning of'. Chinese text, numbers and punctuation all break the run and are
    left untouched. Equation blocks are NOT passed here (handled separately so
    LaTeX spacing is preserved); table HTML is skipped too. If a real short-word
    sequence still gets over-merged, raise min_run in mineru_convert.py.
    """
    toks = text.split()
    out, run = [], []

    def flush():
        if not run:
            return
        out.append("".join(run) if len(run) >= min_run else " ".join(run))
        run.clear()

    for t in toks:
        if _is_tiny_word(t):
            run.append(t)
        else:
            flush()
            out.append(t)
    flush()
    return " ".join(out)


# Decorative-image filtering ------------------------------------------------
# MinerU content_list.json image/chart blocks carry a normalized bbox
# [x0, y0, x1, y1] in a 0-1000 coordinate space plus caption fields
# (image_caption / image_footnote for images, chart_caption / chart_footnote
# for charts). A block that has a caption is a real, labeled figure and is
# always kept. Blocks without a caption but with tiny/extreme-aspect geometry
# are decorative (icons, logos, borders, dividers) and are dropped. Geometry
# comes from bbox, so no image-decoding dependency (Pillow) is needed.
_DECO_TINY = 60       # max bbox side < 60/1000 of page  => icon / logo
_DECO_ASPECT = 12     # max/min side ratio > 12          => border / rule / divider

def _block_captions(b):
    caps = []
    for k in ("image_caption", "image_footnote", "chart_caption",
              "chart_footnote", "img_caption", "img_footnote"):
        v = b.get(k)
        if v:
            caps.extend(v if isinstance(v, list) else [v])
    return [c for c in caps if str(c).strip()]


def _is_decorative(b):
    """True if an image/chart block looks decorative (icon/border/divider)
    rather than a content figure. Labeled figures (caption present) are kept."""
    if _block_captions(b):
        return False
    bb = b.get("bbox")
    if not isinstance(bb, (list, tuple)) or len(bb) != 4:
        return False                      # no geometry -> keep (safe)
    x0, y0, x1, y1 = bb
    w, h = abs(x1 - x0), abs(y1 - y0)
    if max(w, h) < _DECO_TINY:
        return True
    if max(w, h) / max(1, min(w, h)) > _DECO_ASPECT:
        return True
    return False


def _norm_printed(raw):
    """MinerU frequently misreads digit '1' as 'I'/'l'/'|' and '0' as 'O' in
    printed page numbers (e.g. '14' -> 'I4', '120' -> 'I2O'). Normalize only the
    unambiguous UPPERCASE confusions; a string that is a pure roman numeral
    (any case) is left intact so genuine front-matter numerals survive."""
    import re as _re
    s = str(raw).strip()
    if s and _re.fullmatch(r'[ivxlcdm]+', s, _re.I):
        return s
    return s.replace('I', '1').replace('O', '0').replace('|', '1')


def _parse_page_num(s):
    """int if s is a plain (normalized) arabic page number, else None. Roman
    and unparseable values are not auto-corrected by the sequence checker."""
    import re as _re
    if _re.fullmatch(r'\d+', s):
        return int(s)
    return None


def _verify_page_sequence(printed):
    """Smart cross-page verification of printed page numbers (前后2-3页佐证).

    Only *isolated* OCR misreads are auto-corrected: a page whose value breaks an
    otherwise +1 sequence, while BOTH neighbours' sides are a clean +1 run
    (i-2,i-1,i,i+1,i+2). This avoids false positives from leading-digit drops on
    the neighbours (e.g. 11,2,13,4,15 where 13 is actually correct). Roman /
    unparseable pages are left untouched. Returns pidx -> (possibly corrected)
    page-number string."""
    order = sorted(printed.keys())
    seq = [(p, _parse_page_num(_norm_printed(printed[p]))) for p in order]
    out = {p: _norm_printed(printed[p]) for p in order}
    n = len(seq)
    for i in range(n):
        if seq[i][1] is None:
            continue
        if 2 <= i <= n - 3 and all(seq[j][1] is not None
                                  for j in (i - 2, i - 1, i + 1, i + 2)):
            a, b, c, d, e = (seq[i - 2][1], seq[i - 1][1], seq[i][1],
                             seq[i + 1][1], seq[i + 2][1])
            # The page is an isolated misread only if BOTH adjacent steps break
            # the +1 run (c-b != 1 and d-c != 1) while the 2-page-out neighbours
            # are clean +1 (b-a==1 and e-d==1). A section/extract start (e.g.
            # 15,249,250) breaks only ONE side and must NOT be "corrected".
            if (b - a == 1 and e - d == 1 and c != b + 1
                    and c - b != 1 and d - c != 1):
                out[seq[i][0]] = str(b + 1)
        # Fallback for short runs (n==3 or n==4) where the 5-window above can't
        # apply: if the immediate neighbours are clean and exactly 2 apart
        # (e.g. 251,?,253 -> ? must be 252), the middle is an isolated outlier.
        # A section/extract start (15,249,250) fails this because 250 != 15+2.
        elif i - 1 >= 0 and i + 1 < n and seq[i - 1][1] is not None \
                and seq[i + 1][1] is not None:
            a = seq[i - 1][1]
            c = seq[i][1]
            d = seq[i + 1][1]
            if d == a + 2 and c != a + 1 and c != d - 1:
                out[seq[i][0]] = str(a + 1)
    return out


def reconstruct(extracted_dir, page_offset=0, drop_decorative=True):
    cls = glob.glob(os.path.join(extracted_dir, "*content_list.json")) or \
          glob.glob(os.path.join(extracted_dir, "content_list.json"))
    if not cls:
        raise SystemExit(f"no content_list.json in {extracted_dir}")
    data = json.load(open(cls[0], encoding="utf-8"))

    printed = {}
    for b in data:
        if b.get("type") == "page_number" and b.get("text"):
            printed.setdefault(b["page_idx"], _norm_printed(b["text"]))
    corrected = _verify_page_sequence(printed)

    SKIP = {"header", "footer", "page_footnote", "page_number"}
    out = []
    cur = None
    for b in data:
        t = b.get("type")
        pidx = b.get("page_idx")
        if t in SKIP:
            continue
        if pidx is not None and pidx != cur:
            cur = pidx
            mk = f"<!-- 第 {pidx + 1 + page_offset} 页"
            if pidx in corrected:
                mk += f" | 印刷页码: {corrected[pidx]}"
            mk += " -->"
            out.append(mk)
        if t in ("text", "title", "ref_text"):
            txt = b.get("text")
            if txt and txt.strip():
                out.append(_fix_char_spacing(txt.strip()))
        elif t == "equation":
            txt = b.get("text")
            if txt and txt.strip():
                out.append(txt.strip())
        elif t in ("chart", "image"):
            if drop_decorative and _is_decorative(b):
                continue            # 装饰性图标/边框/分隔线：丢弃，不进 md
            ip = b.get("img_path")
            if ip:
                out.append(f"![]({ip})")
            caps = _block_captions(b)
            if caps:
                out.append(_fix_char_spacing(" ".join(caps).strip()))
        elif t == "table":
            body = b.get("table_body")
            if body:
                out.append(body)
            caps = []
            for k in ("table_caption", "table_footnote"):
                v = b.get(k)
                if v:
                    caps.extend(v if isinstance(v, list) else [v])
            if caps:
                out.append(_fix_char_spacing(" ".join(caps).strip()))
    return "\n\n".join(out) + "\n"


def _stream_download(url, dest, timeout=90, max_retries=12, chunk=65536):
    """Stream `url` to `dest` in 64 KB chunks with resume-on-timeout.

    A flaky CDN link (MinerU result zips have truncated / stalled mid-download
    from this sandbox) would otherwise waste a backend parse that already
    succeeded. We send a `Range` header to resume from bytes already on disk, so
    a single stalled recv only costs the last partial chunk, not the whole file.
    Returns the final byte count. Raises after `max_retries` exhausted."""
    parsed = urllib.parse.urlparse(url)
    host, path = parsed.netloc, parsed.path + (("?" + parsed.query) if parsed.query else "")
    has = os.path.getsize(dest) if os.path.exists(dest) else 0
    last_err = None
    for attempt in range(max_retries):
        conn = None
        try:
            conn = httplib.HTTPSConnection(host, timeout=timeout)
            hdr = dict(UA)
            if has > 0:
                hdr["Range"] = f"bytes={has}-"
            conn.request("GET", path, headers=hdr)
            resp = conn.getresponse()
            if resp.status == 200 and has > 0:      # server ignored Range -> restart fresh
                has = 0
                open(dest, "wb").close()
            elif resp.status not in (200, 206):
                raise RuntimeError(f"HTTP {resp.status} {resp.reason} for {url[:60]}")
            cl = resp.getheader("Content-Length")
            total = (has + int(cl)) if cl else None
            with open(dest, "ab" if has > 0 else "wb") as f:
                while True:
                    data = resp.read(chunk)
                    if not data:
                        break
                    f.write(data)
                    has += len(data)
            if total is not None and has < total:
                raise IOError(f"short read {has}/{total}")
            return has
        except Exception as e:
            last_err = e
            print(f"[下载重试 {attempt + 1}/{max_retries}] {type(e).__name__}: "
                  f"{str(e)[:80]} (已下 {has}B)")
            time.sleep(min(30, (2 ** attempt) * 2 + random.uniform(0, 2)))
            continue
        finally:
            if conn:
                conn.close()
    if last_err:
        raise last_err
    raise RuntimeError(f"stream download failed: {url}")


def _download_extract(zip_url):
    """Fresh unique temp dir per call (thread-safe for concurrent batches).
    Streams the result zip to disk with resume-on-timeout so a flaky CDN link
    doesn't waste a completed backend parse."""
    ext = tempfile.mkdtemp(prefix="mineru_extract_")
    zpath = os.path.join(ext, "result.zip")
    _stream_download(zip_url, zpath)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(ext)
    try:                      # 解压后立刻删掉 zip，峰值占用减半
        os.remove(zpath)
    except OSError:
        pass
    return ext


def _safe_stem(path):
    # Strip chars that break both filenames and (more importantly) Markdown
    # image links: a folder/path containing '(' or ')' makes '![](...)' close
    # early and the image fail to render. Brackets, angle brackets, pipe and
    # quotes are likewise unsafe inside link targets.
    return re.sub(r'[:/\\()\[\]<>|"\']', '_',
                  os.path.splitext(os.path.basename(path))[0])


def _smart_out_path(in_root, out_root, pdf):
    """Map a source PDF to its output .md path.

    If out_root already contains a subfolder whose name matches the *tail* of
    the source's relative path (i.e. the output hierarchy is similar to the
    source), the file is placed inside that corresponding subfolder. Otherwise
    the full source structure is mirrored from the root (default behavior).
    """
    rel = os.path.relpath(pdf, in_root)
    rel_noext = os.path.splitext(rel)[0]
    rel_dir = os.path.dirname(rel)
    parts = rel_dir.split(os.sep) if rel_dir else []
    for i in range(len(parts) - 1, -1, -1):        # only real subdirs, longest tail first
        sub = parts[i:]
        cand = os.path.join(out_root, *sub)
        if os.path.isdir(cand):
            return os.path.join(cand, _safe_stem(pdf) + ".md")
    return os.path.join(out_root, rel_noext + ".md")   # no match -> mirror from root


def _drop_image_lines(md):
    return "\n".join(
        ln for ln in md.split("\n") if not ln.strip().startswith("![](")
    )


def page_count(pdf):
    from pypdf import PdfReader
    return len(PdfReader(pdf).pages)


def _finalize(md, out_md, save_images, stem, total, chunks, split, ext_dir=None):
    """Write out_md (page-marked). When save_images, rewrite image refs to
    stem_files/ and copy only the referenced images from ext_dir (a temp
    extraction dir, or a list of them for split docs) into that _files dir.
    Decorative images were already dropped by reconstruct (no md reference) so
    they are never copied. ext_dir is the temp extraction dir returned by
    _download_extract; if omitted (md-only or no images) only the rewrite/drop
    happens."""
    img_dir = out_md[:-3] + "_files"
    if save_images:
        md = md.replace("images/", stem + "_files/")
        refs = set(re.findall(re.escape(stem) + r"_files/([^)\s]+)", md))
        exts = ext_dir if isinstance(ext_dir, (list, tuple)) else ([ext_dir] if ext_dir else [])
        for ext in exts:
            if not ext:
                continue
            src = os.path.join(ext, "images")
            if not (os.path.isdir(src) and os.listdir(src)):
                continue
            if refs:
                os.makedirs(img_dir, exist_ok=True)
                for fn in refs:
                    sp = os.path.join(src, fn)
                    if os.path.isfile(sp):
                        shutil.copy(sp, os.path.join(img_dir, fn))
    else:
        md = _drop_image_lines(md)
        shutil.rmtree(img_dir, ignore_errors=True)
    head = "<!-- 由 MinerU 解析生成，含印刷页码标记"
    if split:
        head += f" | 原文档 {total} 页，已拆 {chunks} 份解析后合并"
    head += " -->\n\n"
    os.makedirs(os.path.dirname(out_md), exist_ok=True)
    with open(out_md, "w", encoding="utf-8") as f:
        f.write(head + md + "\n")
    return img_dir


def _images_broken(out_md):
    """True only when an existing .md declares images (references *_files/)
    but the corresponding _files dir is missing/empty — i.e. a broken or
    interrupted full-mode result that must be re-done rather than skipped."""
    try:
        text = open(out_md, encoding="utf-8").read()
    except Exception:
        return False
    if "_files/" not in text:
        return False  # pure-text doc: no images expected, skip is fine
    img_dir = out_md[:-3] + "_files"
    return not (os.path.isdir(img_dir) and os.listdir(img_dir))


def process_file(pdf, out_md, save_images, model, max_pages, token, force=False, drop_decorative=True, pages=None, lang=None, ocr=False):
    """Convert one PDF to out_md. Returns a result dict for the manifest.

    pages/lang/ocr are the MinerU 4.0 cloud-API extras (see upload_and_parse).
    When `pages` is set, local pypdf auto-split is skipped and the API selects
    the requested page range.
    """
    if os.path.exists(out_md) and not force:
        # 断点续跑：默认跳过已存在的 .md；但 full 模式下若 md 声明了图片而
        # _files 缺失/为空（被中断或旧 bug 产物），视为未完成、自动重做。
        if not (save_images and _images_broken(out_md)):
            return {"status": "skipped", "pages": None, "chunks": None,
                    "images": None, "error": "已存在"}
    try:
        total = page_count(pdf)
    except Exception:
        total = None
    stem = _safe_stem(pdf)

    if pages or total is None or total <= max_pages:
        # ----- single (no split) OR page-range partial parse (--pages) -----
        ext = None
        try:
            bid = upload_and_parse(pdf, model, token, page_ranges=pages,
                                   language=lang, is_ocr=ocr)
            zips = poll(bid, token)
            if not zips:
                return {"status": "failed", "pages": total, "chunks": 1,
                        "images": 0, "error": "parse failed"}
            ext = _download_extract(zips[0])
            md = reconstruct(ext, drop_decorative=drop_decorative)
            img_dir = _finalize(md, out_md, save_images, stem, total or 0, 1, split=False, ext_dir=ext)
            nimg = len(os.listdir(img_dir)) if (save_images and os.path.isdir(img_dir)) else 0
            return {"status": "ok", "pages": total, "chunks": 1, "images": nimg, "error": ""}
        except Exception as e:
            return {"status": "failed", "pages": total, "chunks": 1,
                    "images": 0, "error": repr(e)[:200]}
        finally:
            # 临时解压目录必须回收：批量跑大书时它们会堆满磁盘（ENOSPC）
            if ext:
                shutil.rmtree(ext, ignore_errors=True)

    # ----- split (> max_pages) -----
    chunks_local, ext_dirs_local = [], []
    try:
        from pypdf import PdfReader, PdfWriter
        reader = PdfReader(pdf)
        chunks = chunks_local
        for start in range(0, total, max_pages):
            end = min(start + max_pages, total)
            cpath = tempfile.mktemp(suffix=".pdf", prefix="mineru_chunk_")
            w = PdfWriter()
            for p in range(start, end):
                w.add_page(reader.pages[p])
            with open(cpath, "wb") as f:
                w.write(f)
            chunks.append((cpath, start))
        img_dir = out_md[:-3] + "_files"
        shutil.rmtree(img_dir, ignore_errors=True)
        parts, ext_dirs = [], []
        ext_dirs_local = ext_dirs
        for (cpath, offset) in chunks:
            bid = upload_and_parse(cpath, model, token, language=lang, is_ocr=ocr)
            zips = poll(bid, token)
            if not zips:
                parts.append(f"<!-- 第 {offset + 1} 页起解析失败，跳过 -->")
                continue
            ext = _download_extract(zips[0])
            parts.append(reconstruct(ext, page_offset=offset, drop_decorative=drop_decorative))
            ext_dirs.append(ext)
            os.remove(cpath)
        md = "\n\n".join(parts)
        _finalize(md, out_md, save_images, stem, total, len(chunks), split=True, ext_dir=ext_dirs)
        nimg = len(os.listdir(img_dir)) if (save_images and os.path.isdir(img_dir)) else 0
        return {"status": "ok", "pages": total, "chunks": len(chunks),
                "images": nimg, "error": ""}
    except Exception as e:
        return {"status": "failed", "pages": total, "chunks": None,
                "images": 0, "error": repr(e)[:200]}
    finally:
        # 回收所有中间产物：解压目录 + 拆分出的临时 PDF 分片
        for d in ext_dirs_local:
            shutil.rmtree(d, ignore_errors=True)
        for (cpath, _off) in chunks_local:
            try:
                if os.path.exists(cpath):
                    os.remove(cpath)
            except OSError:
                pass


def convert(input_pdf, output_dir, model_version="vlm", save_images=True, max_pages=180, drop_decorative=True, pages=None, lang=None, ocr=False):
    os.makedirs(output_dir, exist_ok=True)
    token = load_token()
    out_md = os.path.join(output_dir, _safe_stem(input_pdf) + ".md")
    r = process_file(input_pdf, out_md, save_images, model_version, max_pages, token,
                     force=False, drop_decorative=drop_decorative, pages=pages, lang=lang, ocr=ocr)
    print("WROTE:", out_md, "|", r["status"], r["error"])
    return r


def split_convert(input_pdf, output_dir, model_version="vlm", max_pages=180, save_images=True, drop_decorative=True, pages=None, lang=None, ocr=False):
    # auto-split is now inside convert/process_file; this is a thin alias
    return convert(input_pdf, output_dir, model_version, save_images, max_pages, drop_decorative, pages, lang, ocr)


def batch(in_dir, out_dir, model="vlm", save_images=True, max_pages=180,
          workers=2, force=False, drop_decorative=True, pages=None, lang=None, ocr=False):
    os.makedirs(out_dir, exist_ok=True)
    token = load_token()
    jobs = []
    for dp, _, fs in os.walk(in_dir):
        for f in fs:
            if f.lower().endswith(".pdf"):
                pdf = os.path.join(dp, f)
                out_md = _smart_out_path(in_dir, out_dir, pdf)
                jobs.append((pdf, out_md))
    print(f"BATCH: found {len(jobs)} PDFs under {in_dir}")
    results = []

    def work(j):
        pdf, out_md = j
        return process_file(pdf, out_md, save_images, model, max_pages, token,
                             force, drop_decorative, pages, lang, ocr)

    if workers <= 1:
        for pdf, out_md in jobs:
            print(f"-> {os.path.basename(pdf)}")
            r = work((pdf, out_md))
            r["source"], r["md"] = pdf, out_md
            results.append(r)
            print(f"   {r['status']} pages={r['pages']} chunks={r['chunks']} "
                  f"images={r['images']} {r['error']}")
    else:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for (pdf, out_md), r in zip(jobs, ex.map(work, jobs)):
                r["source"], r["md"] = pdf, out_md
                results.append(r)
                print(f"-> {os.path.basename(pdf)}: {r['status']} {r['error']}")

    man = os.path.join(out_dir, "_batch_manifest.jsonl")
    try:
        with open(man, "w", encoding="utf-8") as f:
            for r in results:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    except OSError as e:      # 磁盘满时不要把已完成的转换结果一起丢掉
        print(f"[warn] manifest 写入失败（{e}），结果仅打印于上方")
    ok = sum(1 for r in results if r["status"] == "ok")
    skip = sum(1 for r in results if r["status"] == "skipped")
    fail = sum(1 for r in results if r["status"] == "failed")
    print(f"\nBATCH DONE: ok={ok} skipped={skip} failed={fail} total={len(results)}")
    print("MANIFEST:", man)
    return results


def verify(out_dir, source_dir=None, report_path=None):
    mds = []
    for dp, _, fs in os.walk(out_dir):
        for f in fs:
            if f.lower().endswith(".md"):
                mds.append(os.path.join(dp, f))
    rows = []
    for md in sorted(mds):
        text = open(md, encoding="utf-8", errors="replace").read()
        if "由 MinerU 解析生成" not in text:
            continue
        stem = os.path.splitext(md)[0]
        img_dir = stem + "_files"
        markers = [int(x) for x in re.findall(r'第\s*(\d+)\s*页', text)]
        last_page = max(markers) if markers else 0
        refs = set(os.path.basename(r) for r in
                   re.findall(r'!\[[^\]]*\]\(([^)]+)\)', text))
        missing = [r for r in refs if not os.path.exists(os.path.join(img_dir, r))]
        skipped = "解析失败，跳过" in text
        if skipped:
            status = "WARN(有跳过页)"
        elif refs and missing:
            status = f"缺图{len(missing)}"
        else:
            status = "OK"
        src_pages, page_note = None, ""
        if source_dir:
            rel = os.path.relpath(md, out_dir)[:-3] + ".pdf"
            cand = os.path.join(source_dir, rel)
            if os.path.exists(cand):
                try:
                    src_pages = page_count(cand)
                except Exception:
                    src_pages = None
                if src_pages and last_page and src_pages != last_page:
                    page_note = f"页码{last_page}≠源{src_pages}"
                    if status == "OK":
                        status = "WARN(页码不符)"
        rows.append({
            "md": md, "last_page": last_page, "imgs": len(refs),
            "missing": len(missing), "status": status, "note": page_note,
        })

    ok = sum(1 for r in rows if r["status"] == "OK")
    warn = sum(1 for r in rows if r["status"].startswith("WARN"))
    fail = sum(1 for r in rows if r["status"].startswith("缺图"))
    lines = ["# MinerU 批量核验报告", "",
             f"- 核验目录：`{out_dir}`",
             f"- 源目录：`{source_dir or '（未提供）'}`",
             f"- 文件总数：{len(rows)} | OK：{ok} | 警告：{warn} | 缺图：{fail}",
             "", "| 状态 | 末页 | 图引用 | 缺失 | 说明 | 文件 |",
             "|------|------|--------|------|------|------|"]
    for r in rows:
        rel = os.path.relpath(r["md"], out_dir)
        lines.append(f"| {r['status']} | {r['last_page']} | {r['imgs']} | "
                     f"{r['missing']} | {r['note']} | {rel} |")
    report = os.path.join(out_dir, "_verify_report.md") if report_path is None else report_path
    with open(report, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nVERIFY DONE: ok={ok} warn={warn} 缺图={fail} | REPORT: {report}")
    return rows


def inventory(in_dir, max_pages=180):
    rows = []
    for dp, _, fs in os.walk(in_dir):
        for f in fs:
            if f.lower().endswith(".pdf"):
                pdf = os.path.join(dp, f)
                try:
                    n = page_count(pdf)
                except Exception as e:
                    n = -1
                rel = os.path.relpath(pdf, in_dir)
                rows.append((rel, n, n > max_pages))
    rows.sort()
    print(f"INVENTORY: {len(rows)} PDFs under {in_dir} (max_pages={max_pages})")
    print(f"{'pages':>6}  split?  path")
    tot = 0
    for rel, n, need in rows:
        tot += max(n, 0)
        flag = "YES" if need else ""
        print(f"{n:>6}  {flag:5}  {rel}")
    big = sum(1 for _, n, need in rows if need)
    print(f"\n总计: {len(rows)} 个 PDF, {tot} 页; 需拆分的(>{max_pages}页): {big} 个")
    return rows


def _bool(v):
    return str(v).strip().lower() not in ("0", "false", "no", "off", "md-only")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="MinerU PDF -> Markdown (page markers)")
    sub = ap.add_subparsers(dest="mode", required=True)

    p_r = sub.add_parser("reconstruct")
    p_r.add_argument("extracted_dir"); p_r.add_argument("out_md")
    p_r.add_argument("--offset", type=int, default=0)
    p_r.add_argument("--md-only", dest="save", action="store_false", default=None)
    p_r.add_argument("--full", dest="save", action="store_true")

    p_c = sub.add_parser("convert")
    p_c.add_argument("input_pdf"); p_c.add_argument("output_dir")
    p_c.add_argument("--model", default="vlm")
    p_c.add_argument("--max-pages", type=int, default=180)
    p_c.add_argument("--pages", default=None, help='page range, e.g. "1-10" or "2,4-6" (MinerU 4.0)')
    p_c.add_argument("--lang", default=None, choices=["ch", "en"], help='OCR/language hint (API default "ch")')
    p_c.add_argument("--ocr", action="store_true", help="enable OCR for scanned/bitmap PDFs")
    p_c.add_argument("--md-only", dest="save", action="store_false", default=None)
    p_c.add_argument("--full", dest="save", action="store_true")

    p_s = sub.add_parser("split_convert")
    p_s.add_argument("input_pdf"); p_s.add_argument("output_dir")
    p_s.add_argument("--model", default="vlm")
    p_s.add_argument("--max-pages", type=int, default=180)
    p_s.add_argument("--pages", default=None, help='page range, e.g. "1-10" or "2,4-6" (MinerU 4.0)')
    p_s.add_argument("--lang", default=None, choices=["ch", "en"], help='OCR/language hint (API default "ch")')
    p_s.add_argument("--ocr", action="store_true", help="enable OCR for scanned/bitmap PDFs")
    p_s.add_argument("--md-only", dest="save", action="store_false", default=None)
    p_s.add_argument("--full", dest="save", action="store_true")

    p_b = sub.add_parser("batch")
    p_b.add_argument("input_dir"); p_b.add_argument("output_dir")
    p_b.add_argument("--model", default="vlm")
    p_b.add_argument("--workers", type=int, default=2)
    p_b.add_argument("--max-pages", type=int, default=180)
    p_b.add_argument("--force", action="store_true")
    p_b.add_argument("--pages", default=None, help='page range for the whole batch, e.g. "1-10" (MinerU 4.0)')
    p_b.add_argument("--lang", default=None, choices=["ch", "en"], help='OCR/language hint (API default "ch")')
    p_b.add_argument("--ocr", action="store_true", help="enable OCR for scanned/bitmap PDFs")
    p_b.add_argument("--md-only", dest="save", action="store_false", default=None)
    p_b.add_argument("--full", dest="save", action="store_true")

    p_v = sub.add_parser("verify")
    p_v.add_argument("output_dir")
    p_v.add_argument("--source", default=None)
    p_v.add_argument("--report", default=None)

    p_i = sub.add_parser("inventory")
    p_i.add_argument("input_dir")
    p_i.add_argument("--max-pages", type=int, default=180)

    args = ap.parse_args()
    save = True if getattr(args, "save", None) is None else args.save

    if args.mode == "reconstruct":
        out = reconstruct(args.extracted_dir, page_offset=args.offset)
        out = out if (args.save is None or args.save) else _drop_image_lines(out)
        open(args.out_md, "w", encoding="utf-8").write(out)
        print("WROTE", args.out_md)
    elif args.mode == "convert":
        convert(args.input_pdf, args.output_dir, args.model, save, args.max_pages,
                pages=args.pages, lang=args.lang, ocr=args.ocr)
    elif args.mode == "split_convert":
        split_convert(args.input_pdf, args.output_dir, args.model, args.max_pages, save,
                      pages=args.pages, lang=args.lang, ocr=args.ocr)
    elif args.mode == "batch":
        batch(args.input_dir, args.output_dir, args.model, save,
              args.max_pages, args.workers, args.force,
              pages=args.pages, lang=args.lang, ocr=args.ocr)
    elif args.mode == "verify":
        verify(args.output_dir, args.source, args.report)
    elif args.mode == "inventory":
        inventory(args.input_dir, args.max_pages)
