# Paper Hunt 升级执行清单（交付 Codex）

> 目标：把现有的「半自动 Claude Code skill」升级为一个**每天自动运行、可按领域/日期筛选、每篇论文有中文精华详情页（含关键图片）、部署在 Vercel 上的网站**。
>
> **总架构（已定）**：GitHub Actions（每日 cron 跑重管线，产出结构化 JSON + 图片）+ Vercel（Next.js 前端，只读产物渲染）。
>
> **LLM 接入（已定）**：配置驱动，OpenAI 兼容协议，base_url / api_key / 模型名全部走环境变量，由用户自行配置。
>
> **抽图（已定）**：使用 DocLayout-YOLO（opendatalab）做版面检测，裁出关键图。

---

## 0. 现状基线（Codex 必读，避免重复造轮子）

现有 skill 位于 `paper-rank/`，关键事实：

- 管线 `rank_pipeline.py` 分三段：
  1. `--phase1-only`：`fetcher` 抓 arXiv → `filter` 关键词过滤 → `enricher` 补充（HF 点赞 / Semantic Scholar 作者 h-index / 正则抽 GitHub·项目页·代码承诺）→ 自动打分 → 写 `tmp/phase1.json`。
  2. **LLM 评估**：当前靠 Claude Code 的 haiku agent 读 `phase1.json`，对 top-N 打 5 维分（novelty / problem_significance / potential_impact / paradigm_shift / lasting_value）+ 一句 comment，写 `tmp/llm_scores.json`。**这一步是本次改造的最大改动点 —— 必须替换为直接调用大模型 API。**
  3. `--finalize`：合并分数 → 生成单个静态 HTML → **删除整个 `tmp/`**。
- 领域配置在 `paper-rank/domains/{domain}/`：`domain.yaml` + `filter_keywords.yaml` + `topic_keywords.yaml` + `scoring_criteria.md`。现有 4 个：`3d-vision / agent-evolution / agent-harness / agent-multimodal`。
- 每篇论文已有字段：`arxiv_id, title, abstract, authors, comments, primary_category, categories, published_at, abs_url, enriched{...}, scores{...}, llm_assessment{...}`。
- **当前无任何 PDF / 图片 / 翻译能力。**

改造原则：**复用** fetcher / filter / enricher / 打分逻辑；**替换** LLM 评估的调用方式；**新增** 翻译、精华提取、抽图、结构化产物输出、编排器；**重写** 输出层（不再产 HTML，改产 JSON 给前端）。

---

## 1. 仓库结构（目标 monorepo）

```
repo/
├── pipeline/                      # 原 paper-rank/ 迁移过来（Python 重活）
│   ├── rank_pipeline.py           # 改造：去掉删 tmp、新增 JSON 产物
│   ├── lib/
│   │   ├── fetcher.py             # 复用
│   │   ├── filter.py              # 复用
│   │   ├── enricher.py            # 复用
│   │   ├── utils.py               # 复用
│   │   ├── llm_client.py          # 新增：OpenAI 兼容 LLM 客户端（配置驱动）
│   │   ├── scorer.py              # 新增：用 LLM 给 top-N 打分（替代 haiku agent）
│   │   ├── translator.py          # 新增：摘要翻译 + 核心技术点提取（中文）
│   │   └── figures.py             # 新增：DocLayout-YOLO 抽关键图
│   ├── run_daily.py               # 新增：编排器（跑所有领域 × 昨日）
│   ├── domains/                   # 复用现有 4 个领域配置
│   ├── requirements.txt           # 新增/更新依赖
│   └── models/                    # DocLayout-YOLO 权重缓存（gitignore，CI 下载）
├── web/                           # 新增：Next.js 前端（部署到 Vercel）
│   ├── app/ 或 pages/
│   ├── public/data/               # 由管线产出的 JSON（见 §2），前端读取
│   ├── public/figures/            # repo 存储模式的本地/兜底图片目录（默认不用）
│   ├── package.json
│   └── next.config.js
├── .github/workflows/daily.yml    # 新增：每日 cron
└── README.md
```

> 注：默认图片走 Vercel Blob，仓库只提交 `web/public/data` 下的 JSON；`web/public/figures` 仅用于 `STORAGE_BACKEND=repo` 的本地调试/兜底模式。

---

## 2. 数据契约（管线 → 前端的接口，先定死）

这是整个项目的核心接口，**先实现这个 schema，前后端并行开发**。所有产物放 `web/public/data/`。

### 2.1 索引文件 `web/public/data/index.json`

全站可用的「领域 × 日期」清单，供前端筛选器使用。

```json
{
  "generated_at": "2026-06-13T20:05:00Z",
  "domains": [
    { "id": "3d-vision", "display_name": "3D Vision" },
    { "id": "agent-harness", "display_name": "Agent Harness" }
  ],
  "entries": [
    { "domain": "3d-vision", "date": "2026-06-12", "paper_count": 18, "file": "3d-vision/2026-06-12.json" }
  ]
}
```

### 2.2 列表文件 `web/public/data/{domain}/{date}.json`

某领域某天的论文列表（用于列表页）。

```json
{
  "domain": "3d-vision",
  "display_name": "3D Vision",
  "date": "2026-06-12",
  "generated_at": "2026-06-13T20:05:00Z",
  "papers": [
    {
      "arxiv_id": "2606.12072",
      "title": "World Model Self-Distillation ...",
      "title_zh": "世界模型自蒸馏……",
      "authors": ["A. Author", "B. Author"],
      "total_score": 0.71,
      "scores": { "topic_relevance": 0.84, "llm_assessment": 0.61, "other": 0.37 },
      "tags": ["HF Daily ★42", "GitHub", "world model"],
      "tldr_zh": "一句话中文速览（用于列表卡片）",
      "detail_file": "3d-vision/2026-06-12/2606.12072.json",
      "thumb": "figures/2606.12072/thumb.webp"
    }
  ]
}
```

### 2.3 详情文件 `web/public/data/{domain}/{date}/{arxiv_id}.json`

单篇精华页全部数据。

```json
{
  "arxiv_id": "2606.12072",
  "title": "World Model Self-Distillation ...",
  "title_zh": "世界模型自蒸馏……",
  "authors": ["..."],
  "published_at": "2026-06-12T...",
  "abs_url": "https://arxiv.org/abs/2606.12072",
  "pdf_url": "https://arxiv.org/pdf/2606.12072",
  "links": { "github": "...", "project_page": "..." },
  "abstract_en": "原文摘要……",
  "abstract_zh": "中文翻译摘要……",
  "key_points_zh": [
    "核心技术点1（中文）",
    "核心技术点2（中文）",
    "核心技术点3（中文）"
  ],
  "llm_assessment": {
    "novelty": 0.7, "problem_significance": 0.6, "potential_impact": 0.8,
    "paradigm_shift": 0.4, "lasting_value": 0.7, "llm_avg": 0.64,
    "comment_zh": "中文一句点评"
  },
  "scores": { "...完整打分..." },
  "enriched": { "...原 enriched 字段..." },
  "figures": [
    {
      "src": "figures/2606.12072/fig1.webp",
      "page": 1, "kind": "figure", "confidence": 0.93,
      "caption_zh": "图1 中文说明（可选，能抽到则填）"
    }
  ]
}
```

> 文件路径全部相对 `web/public/`，前端用 `/data/...`、`/figures/...` 直接 fetch（静态资源）。

---

## 3. Python 管线改造

### 任务 3.1 — 新增配置驱动的 LLM 客户端 `pipeline/lib/llm_client.py`

- 读取环境变量：`LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL_SCORING`、`LLM_MODEL_TRANSLATION`（后两者各自默认值可相同）。
- 实现一个 `chat(messages, model, *, temperature=0, max_tokens, json_mode=False)` 方法，走 **OpenAI 兼容** `POST {base_url}/chat/completions`，`Authorization: Bearer {api_key}`。
- 必备：超时、指数退避重试（429/5xx）、并发限流（如信号量，默认 4）、`response_format={"type":"json_object"}`（当 `json_mode`）。
- 提供 `chat_json()` 包装：解析返回、剥离 ```json 围栏、`json.loads`，失败重试 1 次。
- **验收**：`python -c "from lib.llm_client import LLMClient; print(LLMClient().chat('ping'))"` 在配齐 env 时能返回文本。

### 任务 3.2 — LLM 打分模块 `pipeline/lib/scorer.py`（替换 haiku agent）

- 输入：`phase1.json` 里 top-N 论文 + 领域的 `scoring_criteria.md` 文本。
- 把现有 SKILL.md 里给 agent 的 prompt 模板搬过来：system 用 `scoring_criteria.md`，user 传 `arxiv_id/title/abstract`，要求输出 `{arxiv_id: {5维分 + comment}}` 的 JSON。
- 分批（每批 ~16 篇）并发调用 `LLM_MODEL_SCORING`，合并结果，计算 `llm_avg`，写出与原 `llm_scores.json` **完全相同**的结构（这样 `--finalize` 的合并逻辑可复用）。
- 同时让模型产出 `comment_zh`（中文点评），或对英文 comment 走 translator 翻译。
- **验收**：对一份样例 `phase1.json` 跑通，产出 `llm_scores.json`，字段与现有 finalize 兼容。

### 任务 3.3 — 翻译 + 核心技术点提取 `pipeline/lib/translator.py`

- 函数 `enrich_zh(paper) -> dict`，调用 `LLM_MODEL_TRANSLATION`，**一次调用**同时产出：
  - `title_zh`：标题翻译
  - `abstract_zh`：摘要翻译（忠实、术语保留英文原词括注）
  - `tldr_zh`：一句话速览（≤40 字，列表卡片用）
  - `key_points_zh`：3–5 条核心技术点（中文，要点式）
- 用 `json_mode`，prompt 明确「保留专有名词/模型名/数据集名英文，输出 JSON」。
- 仅对**进入详情页的论文**（即 LLM 已打分的 top-N）做翻译，控制成本。
- **验收**：给定一篇英文 abstract，返回结构完整的中文 JSON。

### 任务 3.4 — 关键图提取 `pipeline/lib/figures.py`（DocLayout-YOLO）

依赖：`pip install doclayout-yolo pymupdf pillow huggingface_hub`。

流程（函数 `extract_figures(arxiv_id, out_dir, max_figures=4) -> list[figure_dict]`）：
1. 下载 PDF：`https://arxiv.org/pdf/{arxiv_id}`（遵守 arXiv 礼仪：加 UA、限速、失败重试；可优先尝试 e-print 源码包，PDF 作兜底）。
2. 用 PyMuPDF 把前 N 页（建议前 6 页，够覆盖 teaser + 方法图）渲染成 ~150–200 DPI 的 PNG。
3. 加载 DocLayout-YOLO 权重（`YOLOv10.from_pretrained("juliozhao/DocLayout-YOLO-DocStructBench")`，权重缓存到 `pipeline/models/`，CI 首次下载后缓存）。
4. `model.predict(page_img, imgsz=1024, conf=0.25, device="cpu")`，取 `figure` 类（必要时含 `table`）的 bbox。
5. 按页码 + 置信度排序，裁剪 bbox 区域，存为 WebP（质量 ~80，限制最大边 ~1200px 控制体积）。第 1 张额外生成 `thumb.webp`（列表缩略图）。
6. 选「关键图」启发式：优先第 1 页的最大图（通常是 teaser/pipeline 图）+ 后续高置信度图，去重，最多 `max_figures` 张。
7. 返回 figure 列表（src 相对路径、page、kind、confidence）。
8. 失败兜底：抽不到图就返回空列表，不阻断流程。

> **可选增强**：把每张图的 caption（可由 DocLayout-YOLO 的 `figure_caption` 区域 OCR 或从 PDF 文本层提取）交给 translator 产 `caption_zh`。第一版可先跳过 caption。

- **验收**：给一个真实 arxiv_id，能在 `out_dir/{arxiv_id}/` 下产出 ≥1 张 WebP + thumb，并返回正确元数据。

> ⚠️ **AGPL-3.0 提醒**（写进 README）：DocLayout-YOLO 是 AGPL-3.0。本项目仅在**离线 CI 批处理**中调用它生成静态图片，模型**不通过网络对终端用户提供服务**，因此前端（Vercel）不构成 AGPL 网络分发触发点。但 `pipeline/` 这部分调用代码处于 AGPL 影响范围，若日后要闭源/商用需复核。如想彻底规避，可改用 PyMuPDF 直接抽嵌入图（`page.get_images()`）作为备选方案——质量与「选关键图」能力会下降。建议两种都实现，用 env `FIGURE_BACKEND=yolo|pymupdf` 切换。

### 任务 3.5 — 改造 `rank_pipeline.py` 输出层

- 新增 `--emit-json` 模式（或在 finalize 内）：把合并后的论文写成 §2 的三种 JSON（列表 + 每篇详情），输出到 `--data-dir`（默认 `web/public/data`）。
- 详情 JSON 里串入 translator（3.3）与 figures（3.4）的结果。
- **不要删 tmp**，或把删除改成可选 `--keep-tmp`；缓存（S2 作者）建议跨天保留以省请求。
- 保留/可选保留原 HTML 产出（调试用），但前端不依赖它。
- 生成/更新 `index.json`（合并已有 entries，按 domain+date 去重）。
- **验收**：跑完一个领域一天，`web/public/data/` 下出现 index + 列表 + 详情 JSON，结构符合 §2。

### 任务 3.6 — 每日编排器 `pipeline/run_daily.py`

- 计算「昨天」：**显式用环境变量 `RUN_TZ`（默认 `Asia/Tokyo`）确定本地日期**，再换算成 arXiv 的 UTC 提交日窗口（注意 arXiv 用 UTC，「昨天」需明确定义，见 §9 时区）。也支持 `--date YYYY-MM-DD` 手动覆盖、`--domains a,b,c` 限定领域。
- 对每个领域依次执行：phase1 → scorer（3.2）→ translator（3.3）→ figures（3.4）→ emit-json（3.5）。
- 健壮性：单领域失败不影响其他领域（try/except + 汇总日志）；可重入（重复跑同一天覆盖产物）。
- 退出码：全部失败返回非 0，便于 CI 报警。
- **验收**：`RUN_TZ=Asia/Tokyo python run_daily.py --date 2026-06-12` 能把所有领域跑完并产出全部 JSON + 图片。

### 任务 3.7 — `pipeline/requirements.txt`

至少包含：`requests, PyYAML, doclayout-yolo, pymupdf, pillow, huggingface_hub`（torch 通常随 doclayout-yolo 拉入；如需 CPU 版需在 CI 里指定 `--index-url` 装 cpu wheel 以减小体积/加速）。

---

## 4. GitHub Actions 每日 cron `.github/workflows/daily.yml`

- 触发：`schedule: cron`（注意 cron 是 **UTC**；凌晨 5 点 JST = 前一日 20:00 UTC，即 `0 20 * * *`）+ `workflow_dispatch`（手动，带可选 date 输入）。
- 步骤：
  1. checkout（需要写权限 commit 回仓：`permissions: contents: write`）。
  2. setup-python 3.10/3.11。
  3. 缓存 pip + DocLayout-YOLO 权重（`actions/cache`，key 含权重文件名）。
  4. `pip install -r pipeline/requirements.txt`。
  5. 跑 `python pipeline/run_daily.py`，注入 secrets：`LLM_BASE_URL / LLM_API_KEY / LLM_MODEL_SCORING / LLM_MODEL_TRANSLATION / BLOB_READ_WRITE_TOKEN`，env `RUN_TZ=Asia/Tokyo`、`FIGURE_BACKEND=yolo`、`STORAGE_BACKEND=blob`。
  6. commit `web/public/data` 回仓（用 `git add` + 自动提交 action，或 `git commit -m "data: {date}" && git push`）；默认不 commit 图片。
- **图片存储默认方案：Vercel Blob**
  - **A. Vercel Blob / 对象存储**（默认）：图片上传到 Blob，JSON 里写绝对 URL；仓库只提交 JSON。需在管线加上传逻辑 + `BLOB_*` token。
  - **B. repo 模式**（本地调试/兜底）：图片+JSON 直接 commit，push 后 Vercel 自动部署。配套 §9 的仓库膨胀治理。
- 超时设置 `timeout-minutes: 120`。
- **验收**：手动 `workflow_dispatch` 触发能跑完并 push，Vercel 随后出现新部署。

---

## 5. 前端 Next.js（`web/`，部署 Vercel）

技术建议：Next.js App Router + 静态生成（SSG/ISR）。数据来自 `public/data/*.json`，纯静态读取，无需后端 API。

### 任务 5.1 — 列表/首页 `/`（或 `/[domain]/[date]`）

- 顶部筛选器：**领域下拉**（来自 `index.json.domains`）+ **日期选择**（来自该领域可用日期）。默认展示「最新一天 + 默认领域」。
- 论文列表卡片：标题（中英）、`tldr_zh`、`total_score`、tags、缩略图 `thumb`、跳转详情页链接。
- 支持按分数排序（复用原 HTML 的排序交互思路）。
- 数据获取：构建时读 `index.json` 生成静态路径；列表数据按需读对应 `{domain}/{date}.json`。
- **验收**：能切领域、切日期，列表正确刷新，点卡片进详情。

### 任务 5.2 — 详情/精华页 `/[domain]/[date]/[arxiv_id]`

- 渲染：中文标题 + 英文原标题、作者、arXiv/PDF/GitHub/项目页链接。
- **中文摘要**（`abstract_zh`）+ 可折叠英文原文（`abstract_en`）。
- **核心技术点**（`key_points_zh`，要点列表）。
- **关键图片画廊**（`figures[]`，懒加载、点击放大；有 `caption_zh` 则显示）。
- LLM 评估：5 维雷达/条形 + `comment_zh`、各维分数。
- 数据获取：`generateStaticParams` 遍历所有详情 JSON 生成静态页（或 ISR）。
- **验收**：随机一篇论文详情页中文精华、图片、评分全部正确渲染；图片路径解析正常。

### 任务 5.3 — 样式与可用性

- 复用原报告的视觉风格（配色、tag 颜色），做成响应式（移动端可读）。
- 空状态：某天无论文时给友好提示。
- 中文字体与排版（行高、术语英文括注的样式）。

---

## 6. Vercel 部署配置

- 在 Vercel 新建项目，**Root Directory 指向 `web/`**。
- 构建命令 `next build`，输出默认。
- 因为 JSON 数据是 commit 进 `web/public/data/`，每次管线 push 都会触发 Vercel 自动重新部署（Git 集成默认开启）。
- 默认使用 Vercel Blob 存图：在 Vercel 项目与 GitHub Actions secrets 配 `BLOB_READ_WRITE_TOKEN`，前端按 JSON 中的绝对 URL 读图。
- 若切到 `STORAGE_BACKEND=repo`，图片会写入 `web/public/figures/` 并随仓库提交。
- **验收**：push 后 Vercel 自动部署，线上能访问列表 + 详情。

---

## 7. 环境变量 / Secrets 清单

| 变量 | 用途 | 配置位置 |
|---|---|---|
| `LLM_BASE_URL` | 大模型 OpenAI 兼容 base url | GitHub Actions secret |
| `LLM_API_KEY` | 大模型 key | GitHub Actions secret |
| `LLM_MODEL_SCORING` | 打分用模型名 | secret / env |
| `LLM_MODEL_TRANSLATION` | 翻译+精华用模型名 | secret / env |
| `RUN_TZ` | 「昨天」按哪个时区（默认 Asia/Tokyo） | workflow env |
| `FIGURE_BACKEND` | `yolo` 或 `pymupdf` | workflow env |
| `STORAGE_BACKEND` | `blob`（默认）或 `repo` | workflow env |
| `BLOB_READ_WRITE_TOKEN` | Vercel Blob 读写 token（图片存储，**默认方案**） | Actions secret + Vercel |
| `BLOB_BASE_PREFIX` | Blob 内路径前缀（如 `figures/`） | workflow env（可选） |

---

## 8. 实施顺序与里程碑（建议）

1. **M1 数据契约打底**：定 §2 schema + 用现有一份样例数据手搓几个 JSON，先把前端 §5 跑通（前端可独立开发）。
2. **M2 LLM 解耦**：完成 3.1 + 3.2，让打分脱离 Claude Code，单领域跑通。
3. **M3 中文精华**：完成 3.3，详情 JSON 带中文。
4. **M4 抽图**：完成 3.4（先 pymupdf 兜底，再接 YOLO）。
5. **M5 编排 + 输出**：完成 3.5 + 3.6，一条命令跑完一天全领域。
6. **M6 自动化**：完成 §4 cron + §6 Vercel，端到端无人值守。
7. **M7 打磨**：caption 翻译、仓库膨胀治理、错误告警。

每个里程碑都要能独立验收（见各任务「验收」）。

---

## 9. 风险与必须注意的坑（Codex 重点防御）

1. **时区/「昨天」定义**：arXiv 用 UTC，且有公告节奏（周末/节假日无新公告）。务必把「按 `RUN_TZ` 算本地昨天 → 映射到 arXiv UTC 提交窗口」写清楚，并允许手动指定日期补跑。注意周末跑可能 0 篇，要优雅处理。
2. **arXiv 礼仪**：抓 PDF/源码包要限速 + 自定义 UADescent + 重试，避免被封。批量下载前 N 页即可，别整本渲染。
3. **DocLayout-YOLO 体积与速度**：权重数百 MB，CI 要缓存；CPU 推理慢，控制每篇渲染页数（前 6 页）和图片数（≤4）。AGPL 许可证见 3.4 提醒。
4. **大模型成本**：每天 4 领域 × top-N 篇 × (打分 + 翻译)。翻译只对进详情页的论文做；打分分批并发但加限流。把 N、批大小、并发都做成可配置。
5. **仓库膨胀（方案 A）**：图片天天 commit 会让 `.git` 变大。治理：图片转 WebP 压缩 + 限尺寸；只保留近 N 天图片（老数据图片删除或迁出，JSON 可保留指向占位）；或直接上 Blob（方案 B）。CI 加一步「清理 X 天前的 figures」。
6. **幂等/重跑**：同一天重复跑要覆盖而非重复追加；`index.json` 合并要去重。
7. **失败隔离**：单篇抽图失败、单领域 LLM 失败都不能拖垮整批；汇总日志 + 非零退出便于告警。
8. **JSON 体积**：列表 JSON 别把 abstract 全文塞进去（详情页再读），控制首屏加载。
9. **前端静态生成数量**：随天数累积详情页会很多，`generateStaticParams` 全量生成可能拖慢构建——考虑只对近 N 天 SSG、更老的走 ISR/按需。
10. **现有 HTML 报告**：finalize 删 tmp 的行为要改掉（否则缓存/中间产物丢失）；旧报告目录结构与新 `web/public/data` 不要混。

---

## 11. 图片存储：Vercel Blob 接入（默认方案）

### 11.1 Vercel Blob 工作原理（背景）

- 对象存储服务（类 S3），存图片/视频/PDF 等二进制，与 Vercel 项目打通。
- 先建一个 **store**（`vercel blob create-store <name> --access public`），拿到 `BLOB_READ_WRITE_TOKEN`。公开 store 的文件任何人凭 URL 可读，并走 Vercel CDN 缓存（默认约一个月）。
- **可在 Vercel 之外运行**（如 GitHub Actions），只要带 RW token；`put(pathname, data, {access:'public'})` 返回稳定公开 URL。
- 适配本项目：管线在 Actions 里把抽出的图 `put()` 上传，拿回绝对 URL 写进详情 JSON 的 `figures[].src` / `thumb`；**仓库只 commit JSON、不 commit 图片**，彻底避免仓库膨胀；删旧图用 `del(url)` 一行。

### 任务 11.2 — 图片上传抽象 `pipeline/lib/blob_uploader.py`

- 读 `STORAGE_BACKEND`（`blob` 默认 / `repo` 兜底）。
- `blob` 后端：用 Vercel Python SDK 或直接 HTTP `PUT` 到 Blob API（`Authorization: Bearer $BLOB_READ_WRITE_TOKEN`），上传 `figures/{arxiv_id}/{name}.webp`，返回公开 URL。带重试、并发限流。
- `repo` 后端：写到 `web/public/figures/...`，返回相对路径 `figures/...`（保留原「提交进仓库」能力，便于本地调试/离线）。
- `figures.py`（任务 3.4）产出图片后调用本模块，**详情 JSON 里始终存最终可访问的 URL/路径**，前端无需关心后端是哪种。
- 提供 `delete_older_than(days)`：`blob` 后端用 `list()`+`del()` 清理 N 天前的图片；`repo` 后端删本地文件。在 `run_daily.py` 末尾或单独的清理 workflow 调用。
- **验收**：`blob` 模式上传一张图返回可在浏览器打开的 URL；`repo` 模式落地到 `web/public/figures`；切换仅靠改 `STORAGE_BACKEND`。

### 11.3 对 §4 / §6 的影响

- §4 cron：注入 `BLOB_READ_WRITE_TOKEN`，`STORAGE_BACKEND=blob`；此时 commit 回仓只含 `web/public/data/*.json`（图片不进仓库），仓库保持精简。
- §6 Vercel：前端用绝对 URL 读图，无需特殊配置；若日后改私有 store 再处理鉴权。
- 仍保留 `repo` 模式作为兜底（无 token 时自动降级），保证本地能跑通。

---

## 12. 加领域便捷路径（零改代码扩展）

目标：新增一个研究领域，不改任何 Python/前端代码，只跑脚手架 + 填关键词。

### 任务 12.1 — 模板目录 `pipeline/domains/_template/`

- 含 4 个带**详细中文注释**的模板：`domain.yaml`（display_name / arxiv_categories / output_suffix / default_top_pct）、`filter_keywords.yaml`（positive / negative_strong / weak_only_positive / strong_signals 各字段含义）、`topic_keywords.yaml`（tiers 系数规则、generality、domain_penalties）、`scoring_criteria.md`（LLM 打分 rubric，给出可直接改写的样例）。
- 目录以 `_` 开头，确保被自动发现逻辑跳过。

### 任务 12.2 — 脚手架 `pipeline/add_domain.py <domain-id>`

- 从 `_template/` 复制出 `domains/<domain-id>/` 的 4 个文件，替换占位符（如 display_name 默认按 id 美化）。
- 已存在则报错退出，避免覆盖。
- 打印「下一步：编辑这些文件填关键词，然后跑 validate_domain.py」。

### 任务 12.3 — 校验 `pipeline/validate_domain.py <domain-id>`

- 检查 4 文件齐全、YAML 可解析、必填字段存在、`arxiv_categories` 为非空列表、tiers 系数为数字、`scoring_criteria.md` 非空。
- 任何问题打印明确错误并非零退出；通过则打印 OK。

### 任务 12.4 — 自动发现

- `run_daily.py` 默认遍历 `domains/` 下所有目录，**跳过 `_`/`.` 开头**的目录；新领域有配置即自动纳入每日运行。
- 仍支持 `--domains a,b,c` 限定子集。

### 任务 12.5 — 前端自动接入

- 领域筛选器只读 `index.json.domains`；新领域一旦产出数据，自动出现在前端，无需改前端代码。
- **验收**：`add_domain.py robotics` → 填关键词 → `validate_domain.py robotics` 通过 → `run_daily.py --domains robotics --date <某天>` 产出数据 → 前端筛选器出现 Robotics 且可进详情页。全程未改任何既有代码。

---

## 13. 人工部署步骤（Runbook）

> 说明：Codex 负责产出全部**代码与配置文件**（含 `.github/workflows/daily.yml`、`web/` 前端、`pipeline/`）。但以下步骤涉及账号、密钥、控制台授权与首次触发，**必须人工操作**。预计一次性 30–45 分钟。
>
> 标注：🧑 = 人工必做；🤖 = Codex 已写好、人工只需确认。

### Phase 0 — 前置准备（🧑 先把这些准备齐）

- 一个 GitHub 账号，且本项目代码已在一个 GitHub 仓库里（私有/公开均可）。
- 一个 Vercel 账号（用 GitHub 登录最省事）。
- 大模型凭据：`LLM_BASE_URL`、`LLM_API_KEY`、要用的模型名（打分模型、翻译模型）。
- 本机装好 `git`；可选装 Vercel CLI（`npm i -g vercel`）便于命令行操作。

### Phase 1 — 代码入库（🧑）

1. 把 Codex 产出的代码推到 GitHub 仓库的 **main** 分支（生产分支）。
2. 确认目录结构符合手册 §1：根目录有 `web/`、`pipeline/`、`.github/workflows/daily.yml`。

### Phase 2 — 创建 Vercel Blob Store 并拿 Token（🧑，图片存储用）

> 对应手册 §11，默认 `STORAGE_BACKEND=blob`。若你执意用 `repo` 模式可跳过本 Phase，但不推荐。

方式一（控制台）：
1. 进 Vercel → 选中/新建项目 → 顶部 **Storage** 标签。
2. **Create Database** → 选 **Blob** → **Continue** → access 选 **Public** → 命名 → **Create**。
3. 勾选要注入该 store 读写 token 的环境（至少 Production）。创建后 Vercel 会在项目里自动加上 `BLOB_READ_WRITE_TOKEN`。
4. **关键**：因为我们的管线在 GitHub Actions（Vercel 之外）上传图片，需要把这个 token 的值**复制出来**，留到 Phase 4 填进 GitHub Secrets。可在 Storage → 该 store → `.env.local` / Tokens 处查看。

方式二（CLI，等价）：
```bash
vercel link            # 在仓库目录关联项目
vercel blob create-store paper-figures --access public
# 按提示连接到项目；token 会写进项目环境，同样复制出来备用
```

### Phase 3 — 连接 Vercel 项目并设 Root Directory（🧑，前端托管）

1. Vercel → **Add New → Project** → 导入你的 GitHub 仓库（首次需授权 Vercel 访问该仓库）。
2. 在配置页把 **Root Directory** 设为 **`web/`**（这是前端所在目录，务必改对，否则构建失败）。
3. Framework 选 **Next.js**（一般自动识别），构建命令保持默认 `next build`。
4. （若前端运行时需要读 Blob 私有资源才需配 env；公开 store 通常无需前端 env。）点 **Deploy** 完成首次部署（此时还没数据，页面应显示空状态，正常）。
5. 确认 Vercel 的 **Git 集成已开启**（默认开）：之后任何 push 到 main 都会自动重新部署——这正是管线 commit JSON 后自动上线的机制。

### Phase 4 — 配置 GitHub Actions Secrets 与权限（🧑，让管线能跑）

1. GitHub 仓库 → **Settings → Secrets and variables → Actions → New repository secret**，逐个添加：
   - `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL_SCORING`、`LLM_MODEL_TRANSLATION`
   - `BLOB_READ_WRITE_TOKEN`（Phase 2 复制的那个）
2. 如手册把 `RUN_TZ`、`FIGURE_BACKEND`、`STORAGE_BACKEND` 作为非敏感变量，可在同页 **Variables** 标签加（或直接写死在 `daily.yml` 的 `env:` 里，🤖 Codex 应已写好）。
3. **开放写权限**（让 Action 能 commit JSON 回仓）：**Settings → Actions → General → Workflow permissions** → 选 **Read and write permissions** → 保存。
4. 确认 **Actions 已启用**（同页或 Actions 标签；私有仓库默认开）。

### Phase 5 — 首次手动跑数据（🧑 触发，🤖 执行）

1. GitHub 仓库 → **Actions** 标签 → 选中 **daily** 工作流 → **Run workflow**（`workflow_dispatch`）。
2. 如手册支持手动指定日期，填一个**确定有论文的工作日**（如某个周二），避免周末空跑。
3. 等待执行（首次因下载 DocLayout-YOLO 权重会偏慢，数分钟～十几分钟正常）。
4. 成功后：管线会上传图片到 Blob、把 `web/public/data/*.json` commit 回 main。
5. 这个 push 会**自动触发 Vercel 重新部署**——无需人工再点。

### Phase 6 — 端到端验证（🧑）

- GitHub：Actions 运行绿色通过；仓库里出现 `web/public/data/index.json` 及对应日期的 JSON。
- Vercel：Deployments 里出现一次由该 push 触发的新部署且成功。
- 线上站点：打开 Vercel 域名 → 列表页能选领域/日期、出现论文卡片 → 点进详情页 → 中文摘要、核心技术点、关键图片、评分都正常；**图片能正常加载**（说明 Blob URL 通）。
- 若图片裂图：检查 `BLOB_READ_WRITE_TOKEN` 是否正确、store 是否 Public、详情 JSON 里 `figures[].src` 是否为可访问绝对 URL。

### Phase 7 — 确认每日定时生效（🧑 确认一次即可）

- `daily.yml` 的 cron 是 `0 20 * * *`（UTC）= **JST 次日 05:00**（🤖 已写好）。
- GitHub 计划任务可能有几分钟～十几分钟延迟，属正常。
- 隔天早上确认 Actions 自动跑了一次、且站点出现前一天的数据，即代表全自动闭环成立。
- 注意：GitHub 对**长期无活动**的仓库会暂停 schedule 触发；若仓库长期没人提交，cron 可能被自动停用，需到 Actions 页面重新启用。

### 日常运维（🧑 偶尔）

- **补跑某天**：到 Actions 手动 `Run workflow` 指定日期即可（幂等覆盖）。
- **加领域**：见手册 §12，`add_domain.py` → 填关键词 → `validate_domain.py` → 手动跑一次或等当晚 cron。无需改部署。
- **清理旧图**：手册 §11.2 的 `delete_older_than(days)` 应被定时调用（在 `run_daily.py` 末尾或单独 workflow）；确认其按预期回收 Blob，控制存储成本。
- **换模型/换 LLM 供应商**：只改 GitHub Secrets 里的 `LLM_*`，无需改代码、无需重新部署前端。

### 常见排错（🧑）

- Action 失败「permission denied」push 不上去 → Phase 4.3 写权限没开。
- Vercel 构建失败 → Root Directory 没设成 `web/`（Phase 3.2）。
- 图片 403/裂图 → Blob token 错、或 store 不是 Public（Phase 2）。
- LLM 步骤报错 → `LLM_BASE_URL`/`LLM_API_KEY`/模型名有误，或供应商不兼容 OpenAI 协议（手册 §3.1）。
- 周末跑出来 0 篇 → 正常（arXiv 周末无公告），改跑工作日。

---

## 14. 给 Codex 的一句话总览

> 复用 `paper-rank` 的抓取/过滤/enrich/打分逻辑；新增 `llm_client`（OpenAI 兼容、env 驱动）替换 Claude Code agent 打分；新增 `translator`（中文摘要+核心技术点）与 `figures`（DocLayout-YOLO 抽关键图）；图片经 `blob_uploader` 默认上传 Vercel Blob（仓库只存 JSON，可降级 repo 模式）；改输出层产出 §2 的结构化 JSON 到 `web/public/data`；写 `run_daily.py` 编排「按时区算昨天 × 自动发现的全领域」；加领域只靠 `add_domain.py`+`validate_domain.py` 零改代码；用 GitHub Actions 每日 cron（`0 20 * * *` UTC = JST 5:00）跑管线、上传图片、commit JSON；Vercel 托管 `web/` 的 Next.js 前端（列表页带领域/日期筛选 + 单篇中文精华详情页，图片走 Blob 绝对 URL）。
