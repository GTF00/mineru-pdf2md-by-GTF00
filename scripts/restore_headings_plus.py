#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
层级还原增强版：在 add_headings.py 的中文论文规则之上，额外兼容两类本批次出现的
真实情况：
  1. 中文编号的 OCR 痕迹：顿号被吞成空格（「一 有根的世界主义」）或包进 <sub>、</sub>
     （「一<sub>、</sub>从地方到星球的想象」）—— 标准版只认「一、」，会漏标。
  2. 德文著作的章节标记（Martin Seel《Eine Ästhetik der Natur》）：
       罗马数字 + 点  -> 部（H2）  如  I. Natur als Raum der Kontemplation
       阿拉伯 + 点    -> 章（H3）  如  1. Vorbild oder Nachbild?
       小写字母 + )   -> 节（H4）  如  a) Uninteressierte Aufmerksamkeit
       德文结构词     -> H1/H2     如  Vorwort / Einleitung / Schlußwort / Inhalt …
  仍然跳过目录项（行尾页码 / 点线），保持「宁可漏标不可错标」。

用法（与 add_headings.py 一致）：
  python3 restore_headings_plus.py <文件或目录> [--preview=N] [--dry-run]
原地修改，先写 <name>.md.orig 备份（已存在则不覆盖）。
"""
import os, re, sys, shutil

CN = "一二三四五六七八九十百千"

# ----- 一级：章 / 固定部件名 -----
P_H1 = re.compile(
    rf"^(第[{CN}]+[章篇编][^\n]*)"
    rf"|^(绪\s*论|导\s*论|引\s*言|序\s*言|前\s*言)"
    rf"|^(结\s*语|结\s*论|余\s*论|结\s*束\s*语)"
    rf"|^(参考文献|致\s*谢|后\s*记|附\s*录)"
    rf"|^(中文摘要|英文摘要|摘\s*要|Abstract|ABSTRACT|内容提要)$"
)
# ----- 二级候选：一、  /  一 (空格)  /  一<sub>、</sub>  /  （一） -----
P_H2A = re.compile(rf"^[{CN}]{{1,3}}[\s<sub>、．.][^\n]*")     # 一、 一(空格) 一<sub>、</sub>
P_H2B = re.compile(rf"^[（(][{CN}]{{1,3}}[)）][^\n]*")         # （一）
# ----- 三级：1. / （1） -----
P_H3 = re.compile(r"^(\d{1,2}[、．.](?!\d)[^\n]*)|^([（(]\d{1,2}[)）][^\n]*)")

# ----- 德文 -----
# 部级罗马数字须后接大写起始词（如 "II. Räume …"），否则会把正文里的
# 小写罗马枚举项（如 "II. die Fähigkeit …;"）误当作部标题，
# 并连带把 has_roman 判真、使 1./2. 章级被错降为三级。故加 (?=[A-ZÄÖÜ])。
P_DE_H2 = re.compile(r"^[IVXLCDM]+\.?\s+(?=[A-ZÄÖÜ])")  # 句点可选：部分德文版本书眉写作 "III DER ..."（无点）
P_DE_H3 = re.compile(r"^\d{1,2}\.(?=\d|\s)")     # 1. / 2.1 …（章或子节，后面跟数字或空格）
P_DE_H4 = re.compile(r"^[a-h]\)\s")               # a) b) c) …（节）
DE_KEYWORDS = re.compile(
    r"^(Vorbemerkung|Vorwort|Einleitung|Schlu\s*wort|Nachwort|Inhalt|Literatur|Namenregister|"
    r"Sachregister|Anmerkungen|Register|Appendix|Abk\s*urzungen)"
)
# 这些作为一级标题(H1)，其余 DE_KEYWORDS 命中项作二级
DE_H1_KEYWORDS = {"Vorbemerkung", "Vorwort", "Einleitung", "Schlußwort", "Nachwort", "Inhalt"}

# 目录项特征：点线 或 行尾页码
P_TOC = re.compile(r"(\.{3,}|…{2,}|_{3,})\s*\d*\s*$|[\s\.]\d{1,3}\s*$")
P_NOISE = re.compile(r"[<>|]|^<!--|^\s*$")


def _clean(s: str) -> str:
    # MinerU OCR 常把顿号包进 <sub>、</sub>，或把个别字母包进 <sup>、</sup>
    # （如 「第 1. Ein<sup>l</sup>eitung」），先剥掉这两类内联标签再判标题
    return re.sub(r"</?(sub|sup)>", "", s)


def is_cn_heading_candidate(line: str) -> bool:
    s = _clean(line.strip())
    if not s or len(s) > 60:
        return False
    if P_NOISE.search(s):
        return False
    if P_TOC.search(s):
        return False
    if re.search(r"[。；;，,：:]\s*$", s):
        return False
    if re.search(r"(?<!\d)\.\s*$", s):
        return False
    return True


def is_de_heading_candidate(line: str) -> bool:
    s = _clean(line.strip())
    if not s or len(s) > 90:
        return False
    if P_NOISE.search(s):
        return False
    if P_TOC.search(s):
        return False
    # 德文标题不以句末标点收尾（允许 ? 和 : ）
    if re.search(r"[。；;，,]\s*$", s):
        return False
    # 也不以句号收尾：排除正文里的编号列举项（如
    # "1. Fotografie ist ein durch und durch realistisches Bildmedium."）
    # 与文末版权出处行（"… – Originalbeitrag." / "… – zuerst erschienen in: … v."）
    if re.search(r"\.\s*$", s):
        return False
    return True


def decide_levels(lines):
    cnt = {"dun": 0, "paren": 0, "num": 0}
    for l in lines:
        s = l.strip()
        if not is_cn_heading_candidate(s):
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


def classify_cn(s, lv):
    if not is_cn_heading_candidate(s):
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


def decide_de_levels(lines):
    """德文层级策略：若正文存在罗马数字部（I. II. III.），则 1./2. 视为章(H3)，
    与罗马部(H2)构成两级；若不存在罗马部（如 Bergthaller 仅有 1./2.），
    则 1./2. 直接当作章(H2)，2.1 等子节为 H3。
    注意：这里必须与 classify 用同一套候选过滤（长度/标点），
    否则一条以 "III. …" 开头的长正文会被误判为部标题，连带把章级错降一级。"""
    has_roman = False
    for l in lines:
        s = _clean(l.strip())
        if not is_de_heading_candidate(s):
            continue
        if P_DE_H2.match(s):
            has_roman = True
            break
    return {"num": 3 if has_roman else 2}


def classify_de(s, de_lv):
    if not is_de_heading_candidate(s):
        return None
    if P_DE_H2.match(s):
        return 2
    if P_DE_H3.match(s):
        if re.match(r"^\d{1,2}\.\d", s):
            return 3  # 2.1 等子节
        return de_lv["num"]  # 1./2. 章级：有罗马则 H3，否则 H2
    if P_DE_H4.match(s):
        return 4
    if DE_KEYWORDS.match(s):
        # Vorwort/Einleitung/Vorbemerkung/Schlußwort/Inhalt 等作为一级；其余二级
        if DE_KEYWORDS.match(s).group(0) in DE_H1_KEYWORDS:
            return 1
        return 2
    return None


def classify(s, lv, de_lv):
    # 纯编号行（如单独成行的 "2." / "3." / "I."）不是标题：
    # 苏尔坎普等德文书的节内用「孤立编号」作分隔符，无标题文字；
    # 中文文献也可能出现孤立的 "1."。要求标题至少含一个字母（拉丁或中日韩），
    # 否则会经 classify_cn 的数字规则被误判为二级标题（曾见 "## 2." 噪声）。
    if not re.search(r"[^\W\d_]", s):
        return None
    # 德文优先（拉丁结构词 / 罗马 / 阿拉伯 / 字母括号）
    if re.search(r"[A-Za-z]", s) and classify_de(s, de_lv) is not None:
        return classify_de(s, de_lv)
    return classify_cn(s, lv)


def process(path: str, dry=False) -> dict:
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    lv = decide_levels(lines)
    de_lv = decide_de_levels(lines)
    out, stat = [], {"h1": 0, "h2": 0, "h3": 0, "h4": 0, "skipped_toc": 0, "dedup": 0, "style": lv["style"]}
    n = len(lines)
    last_heading = None          # 抑制「连续相同标题」：印刷书每页页眉被 MinerU 当标题块重复提取
    for i, line in enumerate(lines):
        s = line.strip()
        prev_ok = (i == 0) or (lines[i - 1].strip() == "")
        next_ok = (i == n - 1) or (lines[i + 1].strip() == "")
        lvl = None
        if s and prev_ok and next_ok:
            lvl = classify(s, lv, de_lv)
            if lvl is None and P_TOC.search(s) and not P_NOISE.search(s) and len(s) <= 90:
                stat["skipped_toc"] += 1
        if lvl:
            txt = _clean(s)
            if txt == last_heading:   # 与上一条已输出标题完全相同 -> 页眉重复，降级为普通正文
                stat["dedup"] += 1
                out.append(line)
                continue
            last_heading = txt
            out.append("#" * lvl + " " + txt)  # 标题行顺手剥掉 <sub>/<sup> OCR 痕迹
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


def preview(path: str, k: int = 40):
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    lv = decide_levels(lines)
    de_lv = decide_de_levels(lines)
    print(f"\n===== {os.path.basename(path)}  [CN层级策略: {lv['style']}] =====")
    cnt = 0
    for i, line in enumerate(lines):
        s = line.strip()
        if not s:
            continue
        prev_ok = (i == 0) or (lines[i - 1].strip() == "")
        next_ok = (i == len(lines) - 1) or (lines[i + 1].strip() == "")
        if prev_ok and next_ok:
            lvl = classify(s, lv, de_lv)
            if lvl:
                print(f"  {'#' * lvl} {s[:70]}")
                cnt += 1
                if cnt >= k:
                    print(f"  ... (仅显示前 {k} 条)")
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
    print(f"{'文件':<44}{'#':>4}{'##':>5}{'###':>5}{'####':>5}{'目录跳过':>9}{'重复':>7}  {'CN策略':<10}")
    print("-" * 98)
    for p in files:
        st = process(p, dry)
        print(f"{os.path.basename(p):<44}{st['h1']:>4}{st['h2']:>5}{st['h3']:>5}{st['h4']:>5}{st['skipped_toc']:>9}{st['dedup']:>7}  {st['style']:<10}")
    if dry:
        print("\n[dry-run] 未写入任何文件")


if __name__ == "__main__":
    main()
