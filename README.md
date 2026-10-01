# mineru-pdf2md

WorkBuddy 技能：把本地 PDF（单文件或整个目录）转换为带**印刷页码标记**的 Markdown，
基于 MinerU OpenAPI v4（`mineru.net`）。

> **MinerU 4.0 已对齐（2026-09 升级）**：本技能使用云端 OpenAPI v4，而非上游
> `opendatalab/mineru` 自带的 *本地* CLI/SDK（`mineru parse` / `mineru-kit` 需要本机
> 装模型 + GPU/RAM）。云端路径无需本机显卡，且能返回 `page_number` 块——这正是本技能
> “印刷页码标记”的数据来源。我们移植了云端 API 在 4.0 新增的能力（`--pages` / `--lang`
> / `--ocr`），并完整保留了自动拆分合并、批处理、标题重建、页码审计修复等特色功能。

## 它做什么

- 每个页面以注释标记开头，例如 `<!-- 第 12 页 | 印刷页码: 354 -->`。
  “印刷页码”取自 MinerU 自身的 `page_number` 块，反映纸上真实印刷的页码
  （未编号的封面/空白页留空），而不是 1 起始的序号。
- 单文件与整目录批量转换，目录会镜像源文件夹结构。
- `full` 模式（Markdown + 提取的图片）或 `md-only` 模式（仅 Markdown，丢弃图片块）。
- 自动拆分超过 200 页（MinerU 硬上限）的 PDF。
- 批量可断点续跑（已存在的 `.md` 自动跳过，`--force` 重跑）。
- 配套后处理脚本：标题层级重建、页码审计与修复。
- **4.0 新增（云端 API 能力）**：
  - `--pages "1-10"` / `"2,4-6"`：只解析指定页范围（API 选页，跳过本地拆分）。
  - `--lang ch|en`：OCR 语言提示（默认 `ch`；非纯中文书用 `en`）。
  - `--ocr`：对扫描件/位图 PDF 开启 OCR。

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

# 只解析前 10 页（MinerU 4.0 page_ranges，跳过本地拆分）
python scripts/mineru_convert.py convert "book.pdf" "out_dir" --pages "1-10"

# 扫描件 / 非纯中文书：开 OCR + 英文 OCR 提示
python scripts/mineru_convert.py convert "book.pdf" "out_dir" --ocr --lang en

# 整目录批量，镜像结构，2 并发（可续跑）
python scripts/mineru_convert.py batch "in_dir" "out_dir" --model vlm

# 批量校验输出（页码标记 + 图片引用是否可解析）
python scripts/mineru_convert.py verify "out_dir" --source "in_dir"
```

完整参数与大量实战坑点见 [`SKILL.md`](./SKILL.md)。

## 与上游 `opendatalab/mineru` 的区别

上游仓库在 4.0 自带一个 `skills/mineru` 技能，但它是**本地**方案（`mineru parse` /
`mineru-kit`，需本机安装模型、GPU/RAM，`flash/basic/standard/advanced` 四级 tier）。
本技能走**云端 OpenAPI v4**（`mineru.net`），区别在于：

| 维度 | 上游 `skills/mineru`（本地） | 本技能（云端 API） |
|------|------------------------------|--------------------|
| 运行方式 | 本机装模型 + GPU/RAM | 仅 Bearer Token，无本机显卡 |
| 印刷页码标记 | 无 | ✅ 来自 `page_number` 块 |
| 自动拆分/合并 >200 页 | 无 | ✅ |
| 整目录批量 + 续跑 + manifest | 无 | ✅ |
| 标题层级重建 / 页码审计修复 | 无 | ✅ |
| 装饰图过滤 / 字符间距清理 | 无 | ✅ |
| 4.0 页范围 / 语言 / OCR 参数 | 不适用 | ✅ `--pages`/`--lang`/`--ocr` |
| 本地文档库 / `doc:{id}` 定位符 | ✅ | ❌（云端无持久服务） |

本技能刻意**未**采用上游的本地 tier 体系与本地文档库——那会破坏云端架构与页码标记链路。
如需最简单的单文件试用，官方 `mineru-open-sdk`（`pip install mineru-open-sdk`）也可直接调
同一云端 API，但它不带本技能的任何后处理。

## 更新日志

- **2026-09（MinerU 4.0 对齐）**
  - 新增 `--pages`（页面范围 `page_ranges`）、`--lang`（OCR 语言提示）、`--ocr`（扫描件 OCR）
    三个云端 API 参数，全部 opt-in，默认请求体不变。
  - SKILL.md / api_notes.md / README.md 增加 MinerU 4.0 说明与“上游本地 CLI vs 本技能云端 API”
    对照，明确保留全部特色功能。
  - 沿用既有核心：印刷页码标记、>200 页自动拆分合并、整目录批量续跑、标题层级重建、
    页码审计修复、装饰图过滤、字符间距清理。

## 许可证

MIT
