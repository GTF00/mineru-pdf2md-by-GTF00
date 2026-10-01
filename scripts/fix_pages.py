#!/usr/bin/env python3
"""In-place fix of printed page numbers in already-converted .md files.

Reuses the skill's _norm_printed (I/l/| -> 1, O -> 0, roman preserved) and
_verify_page_sequence (smart cross-page OCR correction) to rewrite the
`印刷页码:` markers in existing markdown. No MinerU API call — body text and
images are untouched. Idempotent: running twice is a no-op.

Usage:  python3 fix_pages.py [OUT_DIR] [--dry-run]
OUT_DIR defaults to the current directory.
"""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mineru_convert import _norm_printed, _verify_page_sequence

DRY = "--dry-run" in sys.argv
_args = [a for a in sys.argv[1:] if not a.startswith("--")]
OUT = _args[0] if _args else "."

MARK = re.compile(r'<!-- 第 (\d+) 页(?: \| 印刷页码: ([^>]*?))? -->')

def fix_text(txt):
    matches = list(MARK.finditer(txt))
    if not matches:
        return txt, 0
    printed = {}
    for m in matches:
        dp = int(m.group(1))
        raw = m.group(2)
        if raw is None:
            continue  # unnumbered page -> cannot correct
        printed[dp - 1] = raw
    corrected = _verify_page_sequence(printed)

    def repl(m):
        dp = int(m.group(1))
        raw = m.group(2)
        if raw is None:
            return m.group(0)  # unnumbered -> unchanged
        corr = corrected.get(dp - 1, _norm_printed(raw))
        if corr == raw:
            return m.group(0)
        return f"<!-- 第 {dp} 页 | 印刷页码: {corr} -->"

    new = MARK.sub(repl, txt)
    changed = sum(1 for m in matches
                  if m.group(2) is not None
                  and corrected.get(int(m.group(1)) - 1, _norm_printed(m.group(2))) != m.group(2))
    return new, changed

total = changed_files = total_changes = 0
for r, ds, fs in os.walk(OUT):
    for fn in fs:
        if not fn.endswith('.md'):
            continue
        total += 1
        p = os.path.join(r, fn)
        txt = open(p, encoding='utf-8', errors='ignore').read()
        new, n = fix_text(txt)
        if n:
            changed_files += 1
            total_changes += n
            if not DRY:
                open(p, "w", encoding='utf-8').write(new)
            print(f"  {'[dry] ' if DRY else ''}{os.path.relpath(p, OUT)}  ({n} 处页码修正)")

print(f"\n扫描 {total} 个 .md；需修正 {changed_files} 个文件，共 {total_changes} 处页码"
      f"{'（dry-run 未写入）' if DRY else '（已写入）'}")
