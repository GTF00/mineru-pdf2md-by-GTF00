#!/usr/bin/env python3
"""Quick check of printed page-number sequences in already-converted .md files.

Cross-page corroboration: a page is flagged as a *likely OCR misread* only when
its neighbours rejoin the +1 sequence around it (前后两到三页相互佐证). Genuine
section/extract starts (number jumps then resumes +1), uniform skip patterns
(page numbers printed only on recto/odd pages -> recorded seq steps by 2), and
unnumbered pages are reported as non-errors.

Usage:  python3 check_pages.py [OUT_DIR]
OUT_DIR defaults to the current directory.
"""
import os, re, sys
from collections import Counter

OUT = sys.argv[1] if len(sys.argv) > 1 else "."

ROMAN = {'i': 1, 'v': 5, 'x': 10, 'l': 50, 'c': 100, 'd': 500, 'm': 1000}

def parse_roman(s):
    s = s.lower()
    if not s or not all(c in ROMAN for c in s):
        return None
    t = prev = 0
    for c in reversed(s):
        v = ROMAN[c]
        t += -v if v < prev else v
        prev = v
    return t

def norm_printed(raw):
    """MinerU frequently misreads digit '1' as 'I'/'l'/'|' and '0' as 'O' in
    printed page numbers (e.g. '14' -> 'I4', '120' -> 'I2O'). Normalize only the
    unambiguous UPPERCASE confusions; lowercase roman letters (i/v/x/l/c/d/m)
    are left intact so genuine roman front-matter numerals survive."""
    s = raw.strip()
    return s.replace('I', '1').replace('O', '0').replace('|', '1')

def parse_printed(raw):
    r0 = raw.strip()
    s = norm_printed(r0)
    if re.fullmatch(r'\d+', s):
        return ('arabic', int(s))
    if 1 <= len(s) <= 8 and re.fullmatch(r'[ivxlcdm]+', s, re.I):
        return ('roman', parse_roman(s))
    m = re.search(r'\d+', s)
    if m:
        return ('arabic', int(m.group()))
    return ('other', raw)

MARK_RE = re.compile(r'第\s*(\d+)\s*页(?:\s*\|\s*印刷页码:\s*([^>]*?))?\s*-->')

def analyze_arabic(seq):
    """seq: list of (doc_page, value).
    Returns (issues, info) where issues are anomalous positions and info holds
    per-file non-error notes (uniform skip, section-start count)."""
    n = len(seq)
    issues = []
    info = {'skip': None, 'section_starts': 0}
    if n < 2:
        return issues, info
    steps = [seq[i + 1][1] - seq[i][1] for i in range(n - 1)]
    modal, modal_n = Counter(steps).most_common(1)[0]
    uniform_skip = (modal > 1 and modal_n >= 0.6 * (n - 1))
    if uniform_skip:
        info['skip'] = modal

    for i in range(1, n):
        prev = seq[i - 1][1]
        cur = seq[i][1]
        dp = seq[i][0]
        diff = cur - prev
        if diff == 1:
            continue
        # Rule A2 (smart, 前后各2页佐证): the page is a misread only if BOTH
        # adjacent steps break the +1 run (it is an isolated outlier) while the
        # 2-page-out neighbours are clean +1. A section/extract start (e.g.
        # 15,249,250) breaks only one side and is NOT flagged as an error.
        if 2 <= i <= n - 3 and seq[i - 1][1] - seq[i - 2][1] == 1 \
                and seq[i + 2][1] - seq[i + 1][1] == 1 \
                and cur - seq[i - 1][1] != 1 and seq[i + 1][1] - cur != 1:
            expected = seq[i - 1][1] + 1
            if seq[i][1] != expected:
                issues.append((dp, cur, 'OCR误读',
                               f'前后页为 {seq[i-1][1]} 与 {seq[i+1][1]}，应补 {expected}，当前误读为 {cur}'))
                continue
        # fallback Rule A for boundary positions (less strict)
        if i + 1 < n and seq[i + 1][1] == prev + 2 \
                and cur - prev != 1 and seq[i + 1][1] - cur != 1:
            issues.append((dp, cur, 'OCR误读', f'前后页为 {prev} 与 {seq[i+1][1]}，中间应补 {prev+1}，当前误读为 {cur}'))
            continue
        if diff == 0:
            issues.append((dp, cur, '重复页码', f'与前一页印刷页码相同({prev})'))
            continue
        if diff < 0:
            j = i
            run = 1
            while j + 1 < n and 1 <= seq[j + 1][1] - seq[j][1] <= 1:
                j += 1
                run += 1
            if run >= 2:
                issues.append((dp, cur, '分节重编号', f'页码由 {prev} 回落至 {cur} 且其后连续递增，属正常重编号'))
            else:
                issues.append((dp, cur, '回落可疑', f'页码由 {prev} 回落至 {cur} 且无递增延续'))
            continue
        # diff > 1
        if uniform_skip and diff == modal:
            continue  # normal recto/uniform skip, not an error
        if i + 1 < n and seq[i + 1][1] == cur + 1:
            info['section_starts'] += 1  # excerpt/section start, resumes +1 -> not error
            continue
        issues.append((dp, cur, '跳号待确认', f'{prev} → {cur} 跳跃 {diff} 页，可能漏页或原书缺页'))
    return issues, info

results = []
total_files = 0
for r, ds, fs in os.walk(OUT):
    for fn in fs:
        if not fn.endswith('.md'):
            continue
        total_files += 1
        p = os.path.join(r, fn)
        txt = open(p, encoding='utf-8', errors='ignore').read()
        marks = MARK_RE.findall(txt)
        if not marks:
            continue
        seq = []
        others = unnumbered = 0
        for dp_str, pr in marks:
            dp = int(dp_str)
            if pr is None or pr.strip() == '':
                unnumbered += 1
                continue
            kind, val = parse_printed(pr.strip())
            if kind == 'arabic':
                seq.append((dp, val))
            elif kind == 'roman':
                pass
            else:
                others += 1
        issues, info = analyze_arabic(seq)
        if issues or others > 0 or unnumbered > 0 or info['section_starts'] or info['skip']:
            rel = os.path.relpath(p, OUT)
            results.append((rel, len(marks), len(seq), issues, others, unnumbered, info))

ocr_n = sum(1 for _, _, _, iss, *_ in results for it in iss if it[2] == 'OCR误读')
print(f"扫描 .md 文件总数: {total_files}")
print(f"存在异常/特殊情况的文件: {len(results)}  (其中含「OCR误读」的文件: "
      f"{sum(1 for x in results if any(i[2]=='OCR误读' for i in x[3]))})")
print("=" * 72)
print("【第一层】疑似 OCR 误读（建议校正，最值得关注）")
print("=" * 72)
any_ocr = False
for rel, nm, ns, iss, oth, un, info in results:
    ocr = [i for i in iss if i[2] == 'OCR误读']
    if not ocr:
        continue
    any_ocr = True
    print(f"\n■ {rel}")
    for dp, cur, kind, desc in ocr:
        print(f"   第{dp}页 印刷页码={cur} → 建议校正为 {desc.split('应补 ')[1].split('，')[0]}")
if not any_ocr:
    print("   （无）")

print("\n" + "=" * 72)
print("【第二层】非错误类 / 需人工确认的统计")
print("=" * 72)
c_restart = c_section = c_dup = c_gap = c_other = 0
skip_files = uniform_skip_files = 0
for rel, nm, ns, iss, oth, un, info in results:
    if info['skip']:
        uniform_skip_files += 1
    if info['section_starts']:
        c_section += info['section_starts']
    for dp, cur, kind, desc in iss:
        if kind == '分节重编号':
            c_restart += 1
        elif kind == '重复页码':
            c_dup += 1
        elif kind == '跳号待确认':
            c_gap += 1
        elif kind == '回落可疑':
            c_other += 1
    if oth:
        c_other += oth
print(f"  仅单面印页码(记录间隔为2，正常): {uniform_skip_files} 个文件")
print(f"  分节/摘录起始(页码段跳变后恢复+1，正常): {c_section} 处")
print(f"  分节重编号(回落后续递增，正常): {c_restart} 处")
print(f"  重复页码(需确认): {c_dup} 处")
print(f"  跳号待确认(可能漏页，需人工核对): {c_gap} 处")
print(f"  其他(回落可疑/无法解析页码): {c_other} 处")
print(f"  无页码页(封面/留白，正常): 见各文件明细")

# Detailed dump for the "needs human confirm" + restart categories (compact)
print("\n" + "=" * 72)
print("【明细】跳号待确认 / 分节重编号 / 回落可疑（供人工抽查）")
print("=" * 72)
shown = 0
for rel, nm, ns, iss, oth, un, info in results:
    noteworthy = [i for i in iss if i[2] in ('跳号待确认', '分节重编号', '回落可疑')]
    if not noteworthy and oth == 0:
        continue
    shown += 1
    print(f"\n■ {rel}")
    for dp, cur, kind, desc in noteworthy:
        print(f"   [{kind}] 第{dp}页 印刷页码={cur} — {desc}")
    if oth:
        print(f"   [无法解析] {oth} 处印刷页码无法识别")
print(f"\n(共 {shown} 个文件含上述待确认项)")
