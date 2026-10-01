#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
给 MinerU 输出的纯文本 md 补上 markdown 标题层级。

MinerU 把章节标题输出为独立成行的纯文本（如「第一章 审美价值与伦理价值关系之辨」），
整篇没有任何 # 标记，无法大纲浏览。本脚本按中文学位论文的编号惯例还原层级。

判据（保守，宁可漏标不可错标）：
  1. 行必须独立成行（前后为空行）、长度 <= 60、不含 HTML/表格字符
  2. 目录项跳过：行内含点线（......）或行尾是页码数字 —— 目录页的「第一章 xxx ... 1」
  3. 层级：第X章/绪论/结论/参考文献/致谢/附录/摘要 -> #
           一、 / （一）                          -> ##
           1. / （1）                             -> ###
用法：
  python3 add_headings.py <md文件或目录> [--dry-run]
原地修改，先写 <name>.md.orig 备份（已存在则覆盖一次）。
"""
import os, re, sys, shutil

CN = "一二三四五六七八九十百"

# 一级：章 / 固定部件名
P_H1 = re.compile(
    rf"^(第[{CN}]+[章篇编][^\n]*)"
    rf"|^(绪\s*论|导\s*论|引\s*言|序\s*言|前\s*言)"
    rf"|^(结\s*语|结\s*论|余\s*论|结\s*束\s*语)"
    rf"|^(参考文献|致\s*谢|后\s*记|附\s*录)"
    rf"|^(中文摘要|英文摘要|摘\s*要|Abstract|ABSTRACT|内容提要)$"
)
# 二级候选：一、  与  （一）—— 分开放，好判断谁是谁的上级
P_H2A = re.compile(rf"^[{CN}]{{1,3}}[、．.][^\n]*")          # 一、
P_H2B = re.compile(rf"^[（(][{CN}]{{1,3}}[)）][^\n]*")       # （一）
# 三级：1. 或 （1）
P_H3 = re.compile(r"^(\d{1,2}[、．.](?!\d)[^\n]*)|^([（(]\d{1,2}[)）][^\n]*)")

# 目录项特征：点线 或 行尾页码
P_TOC = re.compile(r"(\.{3,}|…{2,}|_{3,})\s*\d*\s*$|[\s\.]\d{1,3}\s*$")
# 不像标题：HTML/表格/注释
P_NOISE = re.compile(r"[<>|]|^<!--|^\s*$")


def is_heading_candidate(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 60:
        return False
    if P_NOISE.search(s):
        return False
    if P_TOC.search(s):
        return False
    # 标题几乎不以句末标点收尾 —— 用来剔除正文里独立成行的编号列表句
    if re.search(r"[。；;，,：:]\s*$", s):
        return False
    if re.search(r"(?<!\d)\.\s*$", s):
        return False
    return True


def decide_levels(lines):
    """按本篇实际的编号习惯决定各类编号的层级。

    中文论文三种流派：
      ① 「一、」为主（最常见）        -> 一、=2, （一）=3, 1.=3
      ② 只有「（一）」没有「一、」    -> （一）=2, 1.=3
      ③ 通篇数字编号（如胡志红那篇）  -> 1.=2，否则整篇没有二级
    """
    cnt = {"dun": 0, "paren": 0, "num": 0}
    for l in lines:
        s = l.strip()
        if not is_heading_candidate(s):
            continue
        if P_H2A.match(s):
            cnt["dun"] += 1
        elif P_H2B.match(s):
            cnt["paren"] += 1
        elif len(s) <= 30 and P_H3.match(s):
            cnt["num"] += 1
    if cnt["dun"] >= 3:
        return {"dun": 2, "paren": 3, "num": 3, "style": "一、=二级"}
    if cnt["paren"] >= 3:
        return {"dun": 2, "paren": 2, "num": 3, "style": "（一）=二级"}
    return {"dun": 2, "paren": 3, "num": 2, "style": "数字=二级"}


def classify(line: str, lv=None):
    """返回层级 1/2/3 或 None。lv 为 decide_levels() 的输出。"""
    lv = lv or {"dun": 2, "paren": 3, "num": 3}
    s = line.strip()
    if not is_heading_candidate(s):
        return None
    if P_H1.match(s):
        return 1
    if P_H2A.match(s):
        return lv["dun"]
    if P_H2B.match(s):
        return lv["paren"]
    if len(s) <= 30 and P_H3.match(s):
        return lv["num"]
    return None


def process(path: str, dry=False) -> dict:
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    # 预扫：判断本篇的编号习惯，决定层级映射
    lv = decide_levels(lines)
    out, stat = [], {"h1": 0, "h2": 0, "h3": 0, "skipped_toc": 0, "style": lv["style"]}
    n = len(lines)
    for i, line in enumerate(lines):
        s = line.strip()
        prev_ok = (i == 0) or (lines[i - 1].strip() == "")
        next_ok = (i == n - 1) or (lines[i + 1].strip() == "")
        lvl = None
        if s and prev_ok and next_ok:
            lvl = classify(s, lv)
            if lvl is None and P_TOC.search(s) and not P_NOISE.search(s) and len(s) <= 60:
                stat["skipped_toc"] += 1
        if lvl:
            out.append("#" * lvl + " " + s)
            stat[f"h{lvl}"] += 1
        else:
            out.append(line)
    if not dry:
        bak = path + ".orig"
        if not os.path.exists(bak):
            shutil.copy2(path, bak)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(out))
    return stat


def preview(path: str, n: int = 40):
    """打印该文件将被标成标题的行，供人工核对"""
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    lv = decide_levels(lines)
    print(f"\n===== {os.path.basename(path)}  [层级策略: {lv['style']}] =====")
    cnt = 0
    for i, line in enumerate(lines):
        s = line.strip()
        if not s:
            continue
        prev_ok = (i == 0) or (lines[i - 1].strip() == "")
        next_ok = (i == len(lines) - 1) or (lines[i + 1].strip() == "")
        if prev_ok and next_ok:
            lvl = classify(s, lv)
            if lvl:
                print(f"  {'#' * lvl} {s[:60]}")
                cnt += 1
                if cnt >= n:
                    print(f"  ... (仅显示前 {n} 条)")
                    break


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv
    pv = 0
    for a in sys.argv[1:]:
        if a.startswith("--preview"):
            pv = int(a.split("=")[1]) if "=" in a else 40
    target = args[0]
    if len(args) > 1:
        # 显式文件列表（相对 target 目录 或 绝对路径）
        files = []
        for a in args[1:]:
            p = a if os.path.isabs(a) else os.path.join(target, a)
            files.append(p)
    elif os.path.isdir(target):
        files = []
        for r, d, fs in os.walk(target):
            for f in fs:
                if f.endswith(".md") and not f.endswith(".orig") and not f.endswith(".bak"):
                    files.append(os.path.join(r, f))
        files.sort()
    else:
        files = [target]
    if pv:
        for p in files:
            preview(p, pv)
        return
    print(f"{'文件':<44}{'#':>5}{'##':>5}{'###':>5}{'目录项跳过':>10}  {'层级策略':<10}")
    print("-" * 84)
    for p in files:
        st = process(p, dry)
        print(f"{os.path.basename(p):<44}"
              f"{st['h1']:>5}{st['h2']:>5}{st['h3']:>5}{st['skipped_toc']:>10}  {st['style']:<10}")
    if dry:
        print("\n[dry-run] 未写入任何文件")


if __name__ == "__main__":
    main()
