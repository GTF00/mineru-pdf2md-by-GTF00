# mineru-pdf2md

WorkBuddy 技能：把本地 PDF（单文件或整个目录）转换为带**印刷页码标记**的 Markdown，
基于 MinerU OpenAPI v4（`mineru.net`）。

## 它做什么

- 每个页面以注释标记开头，例如 `<!-- 第 12 页 | 印刷页码: 354 -->`。
  “印刷页码”取自 MinerU 自身的 `page_number` 块，反映纸上真实印刷的页码
  （未编号的封面/空白页留空），而不是 1 起始的序号。
- 单文件与整目录批量转换，目录会镜像源文件夹结构。
- `full` 模式（Markdown + 提取的图片）或 `md-only` 模式（仅 Markdown，丢弃图片块）。
- 自动拆分超过 200 页（MinerU 硬上限）的 PDF。
- 批量可断点续跑（已存在的 `.md` 自动跳过，`--force` 重跑）。
- 配套后处理脚本：标题层级重建、页码审计与修复。

## 目录结构

```
mineru-pdf2md/
├── SKILL.md                  # 技能说明（Agent 入口）
├── references/
│   └── api_notes.md          # MinerU v4 端点参考
└── scripts/
    ├── mineru_convert.py     # 核心转换（convert / batch / verify / inventory）
    ├── add_headings.py       # 中文学术编号 → 标题层级
    ├── restore_headings_plus.py  # 德语书标题层级重建（add_headings 超集）
    ├── check_pages.py        # 印刷页码审计（只读）
    └── fix_pages.py          # 印刷页码修复（就地、幂等）
```

## 前置条件

- 一个 MinerU API token（`https://mineru.net`）。
- 通过环境变量 `MINERU_API_TOKEN_FILE` 指向存放 token 的文件路径
  （脚本也支持一个本地回退路径，可改）。
- Python 3.11+，需要 `pypdf`（大文件自动拆分、inventory/verify 页数统计）。
  加密 PDF 拆分还需 `pycryptodome`（不要装 `cryptography`，本机编不过）。

```bash
python -m venv venv && . venv/bin/activate
pip install pypdf pycryptodome
export MINERU_API_TOKEN_FILE=/path/to/your/mineru_api_token
```

## 快速开始

```bash
# 单文件，full 模式（默认 vlm 模型，超 180 页自动拆分）
python scripts/mineru_convert.py convert "book.pdf" "out_dir" --model vlm

# 整目录批量，镜像结构，2 并发（可续跑）
python scripts/mineru_convert.py batch "in_dir" "out_dir" --model vlm

# 批量校验输出（页码标记 + 图片引用是否可解析）
python scripts/mineru_convert.py verify "out_dir" --source "in_dir"
```

完整参数与大量实战坑点见 [`SKILL.md`](./SKILL.md)。

## 许可证

MIT
