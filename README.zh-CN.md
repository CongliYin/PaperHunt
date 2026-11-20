# Paper Hunt

[English](README.md) · 简体中文

Paper Hunt 每天从 arXiv 和 Hugging Face Daily Papers 筛选论文，按研究方向生成中文日报。读者可以按领域和日期浏览，点开一篇论文查看中文摘要、关键图表和入选依据。

| 研究方向 | 关注的问题 |
| --- | --- |
| Agent 演化 | Agent 如何根据经验、环境反馈或验证结果改进 harness、工具、工作流或模型参数。递归自我改进（RSI）还关注产生和选择下一轮改进的机制。 |
| Agent 记忆 | Agent 如何存取、更新和遗忘经验，以及这些经验如何影响后续行为。涵盖参数化记忆、外部记忆、混合记忆、记忆自进化和持续学习。 |
| 电商交互导购 | 用户表达的需求、预算或偏好，如何改变商品检索、候选排序、个性化推荐或下一轮追问。 |
| 全模态与多模态 Agent | 语音或视频如何参与记忆、harness 设计和策略演化，例如在后续任务中找回先前看过或听过的事件。 |

**截至 2026 年 11 月 20 日，公开网站仍由旧版工作流发布。** 新版已配置为影子运行，结果写入独立目录供比较。四篇代表论文的真实模型回归已通过，连续七天的影子运行验收和独立人工标注集评估仍待完成。[架构设计与验收标准](docs/superpowers/specs/2026-11-20-four-domain-paper-selection-design.md) · [真实模型回归记录](https://github.com/CongliYin/PaperHunt/actions/runs/44715445398)

## 一篇论文怎样入选

新版入口 `pipeline/run_daily.py` 先对 arXiv 各分类的论文去重，按标题和摘要筛出候选及存疑论文。随后读取同一刊期的完整 HF 清单。凡是出现在 HF 清单里、尚无有效精评结果的论文，都会进入精评，包括 arXiv 初筛漏掉的论文。两路同时发现一篇论文时可以复用评审。

四个方向分别打分。一篇论文要在某个方向入选，必须同时满足以下条件。

| 指标 | 试行门槛 |
| --- | --- |
| 方向相关度 F | 至少 3/4，即论文至少有一项明确贡献直接回答该方向的问题。 |
| 阅读价值 V | 方法具体性 M、论据支持程度 E、研究启发 U 各占 0 至 2 分，三项合计至少 4/6，且 M 和 E 各至少 1 分。 |

每个入选方向都有理由和原文摘录。同一篇论文可以出现在多个栏目，共用详情页、译文和图片。`web/` 通过公共索引读取列表与详情，整期生成成功后才切换索引。列表和详情只显示一个百分制评分，列表按评分降序排列。新版将六分制阅读价值换算为百分制，历史论文使用已保存的综合分。

## 本地运行

使用 Python 3.11 或更高版本，从仓库根目录安装依赖。

```bash
pip install -r pipeline/requirements.txt
```

首次运行可以先用真实数据检查两路采集和 HF 分页。下面的命令跳过模型调用，采集结束后可以在日志中看到两个来源的论文数量。

```bash
python pipeline/run_daily.py --date 2026-06-12 --domains agent-memory --skip-llm --output tmp/source-check/data
```

配置下文的模型环境变量后，可以完整回放一期日报。这个例子将结果写到 `tmp/shadow/data`，状态保存在 `tmp/shadow/state`。`--domains` 控制要发布的栏目，采集和评审仍覆盖所有已配置方向。

```bash
STORAGE_BACKEND=repo FIGURE_BACKEND=pymupdf \
python pipeline/run_daily.py --date 2026-06-12 --domains agent-memory \
  --output tmp/shadow/data --state-dir tmp/shadow/state
```

指定日期回放时，可复用同一查询窗口的 arXiv 原始分类缓存，也可以用 `--refresh-arxiv` 重新抓取。下面的命令使用默认网站数据目录 `web/public/data`。

```bash
python pipeline/run_daily.py --date 2026-06-12 --refresh-arxiv
```

启动本地前端即可浏览 `web/public/data` 中的日报。

```bash
cd web
npm install
npm run dev
```

## 环境配置

本地通过环境变量配置模型，GitHub Actions 从仓库 Secrets 读取对应值。

| 名称 | 用途 |
| --- | --- |
| `LLM_BASE_URL` | 兼容 OpenAI 的服务地址，填写到基础路径，省略末尾的 `/chat/completions`。 |
| `LLM_API_KEY` | 模型服务密钥。 |
| `LLM_MODEL_SCORING` | 用于标题与摘要初筛、四方向精评的模型。 |
| `LLM_MODEL_TRANSLATION` | 用于生成中文标题、摘要和要点的模型。 |
| `BLOB_READ_WRITE_TOKEN` | 使用 Vercel Blob 发布图片时所需的读写令牌。 |

| 运行参数 | 默认值 | 用途 |
| --- | --- | --- |
| `FIGURE_BACKEND` | CI 使用 `yolo` | 提图后端，可选 `yolo` 或 `pymupdf`。 |
| `FIGURE_MAX_COUNT` | `4`，CI 使用 `2` | 每篇论文详情页的图片数上限，调低可减少 Blob 操作。 |
| `STORAGE_BACKEND` | `blob` | 图片存储位置，可选 `blob` 或 `repo`。 |
| `ARXIV_REQUEST_INTERVAL_SECONDS` | `3.1` | 相邻 arXiv 请求开始时间的最小间隔，单位为秒。 |
| `ARXIV_MAX_ATTEMPTS` | `6` | 遇到暂时性故障时，每个请求最多尝试的次数。 |
| `ARXIV_TIMEOUT_SECONDS` | `120` | 单次请求的超时秒数。 |
| `ARXIV_429_BACKOFF_SECONDS` | `60` | HTTP 429 限流后的初始等待秒数，随后逐次翻倍。 |
| `ARXIV_TRANSIENT_BACKOFF_SECONDS` | `30` | 超时、5xx 等暂时性故障后的初始等待秒数。 |
| `ARXIV_MAX_RETRY_DELAY_SECONDS` | `900` | 指数退避的等待上限，尚未计入随机延迟。 |
| `ARXIV_RETRY_JITTER_SECONDS` | `5` | 重试前附加随机延迟的最大秒数。 |
| `ARXIV_USER_AGENT` | 含项目仓库地址的标识 | 随请求发送给 arXiv。 |

新版用 `--arxiv-raw-cache-dir` 设置原始分类缓存目录，默认路径为 `tmp/arxiv-raw`。旧版命令行另支持 `ARXIV_RAW_CACHE_DIR`、`ARXIV_REFRESH` 和 `RUN_TZ`。

## 定时运行与发布切换

**Four-domain daily** 每天北京时间 14 时（UTC 6 时）处理前一自然日的刊期，回查最近七天并补跑遗漏日期。手动运行可填写 `date` 和 `domains`。指定日期会刷新 arXiv，勾选 `seeds_only` 则只运行代表论文回归。影子运行跳过图片上传。[新版工作流](.github/workflows/four-domain.yml)

**daily** 是旧版工作流，每天北京时间 4 时运行，手动刷新参数为 `refresh_arxiv`。完成至少七天的对照运行和人工留出集验收后，将仓库变量 `PAPER_HUNT_V2_PUBLISH` 设为 `true`，即可由新版向 `main` 发布。需要恢复旧发布流程时可将变量改回 `false`。如需一并回滚已发布的内容，还要恢复此前的数据版本。[旧版工作流](.github/workflows/daily.yml)

Actions 将来源快照、初筛与精评缓存、运行清单、素材元数据及影子索引保存为加密的 `edition-state` 制品，保留期为 90 天，后续运行滚动保存。可在 Secrets 中设置专用的 `EDITION_STATE_KEY`，默认使用 `LLM_API_KEY` 加密。更换加密密钥时须迁移已有检查点，或让旧检查点失效。已发布的历史数据保存在 Git 中。

## 新增研究方向

以 `robotics` 为例，从模板创建配置，编辑后校验，再按日期试跑。

```bash
python pipeline/add_domain.py robotics
# 编辑 pipeline/domains/robotics/ 下的 YAML 文件及 scoring_criteria.md
python pipeline/validate_domain.py robotics
python pipeline/run_daily.py --domains robotics --date 2026-06-12
```

`domain.yaml` 定义要抓取的 arXiv 分类。新版的 `pipeline/domains/<domain>/review.yaml` 定义研究范围、容易误收的相邻主题和帮助发现候选的短语。试跑时可添加 `--output tmp/shadow/data --state-dir tmp/shadow/state` 将结果写入独立目录。

旧版入口为 `pipeline/legacy_daily.py`，读取 `selection_policy.yaml`、`topic_keywords.yaml` 和 `scoring_criteria.md`。历史对照评估还会读取 `filter_keywords.yaml`。

## 测试与选题质量评估

在仓库根目录依次运行单元测试、旧版选题回归和前端生产构建。

```bash
python -m unittest discover -s tests
python pipeline/evaluate_selection_quality.py
cd web && npm ci && npm run build
```

新版的真实模型回归使用四篇已知论文，检查它们能否进入预期栏目。配置好评分模型后，在仓库根目录运行 `python pipeline/check_edition_seeds.py`，或在 **Four-domain daily** 工作流中选择 `seeds_only`。

评估新版推荐质量时，从已入选和被拒绝的论文中抽样，按“论文与方向”制作 `labels.json`。文件使用 JSON 数组，每项包含 `date`、`arxiv_id`、`domain`，以及两个布尔值 `relevant`（是否相关）和 `recommend`（是否值得推荐）。在仓库根目录运行以下命令，确保每个评估日期只提供一份完整的四方向运行清单。

```bash
python pipeline/evaluate_editions.py labels.json tmp/edition-state/runs/*.json
```

开发集可加 `--grid` 比较不同阈值。正式验收使用未参与调参的日期，同时报告各方向的精确率、召回率和样本数。旧版标注集回归衡量的是旧版筛选器。

## 部署与运维

在 Vercel 创建项目时，将根目录设为 `web/`。前端直接读取 Git 中 `web/public/data` 的 JSON 文件。生产环境默认将图片上传至公开的 Vercel Blob 存储，并在详情页使用绝对 URL。创建存储后，把 `BLOB_READ_WRITE_TOKEN` 加入 GitHub Actions Secrets。本地调试可设 `STORAGE_BACKEND=repo`，默认发布目录下的图片会写到 `web/public/figures`。

- **arXiv 抓取**按顺序发起请求。遇到 HTTP 429、5xx、超时、连接错误或 XML 格式异常时，按退避策略重试。查询窗口内部分分类可以为空，所有分类都为空时会报错，保留上一次成功发布的索引。
- **缓存与中间文件**方面，定时运行的新版会刷新 arXiv，跨运行恢复规范化后的来源快照及评审结果。旧工作流单独缓存原始分类数据。`tmp/`、模型缓存及旧版 `reports/*/*/tmp/` 中的运行文件均已加入 Git 忽略规则。
- **论文图片**由离线批处理生成。DocLayout-YOLO 使用 AGPL-3.0 许可证，闭源或商业使用相关流水线前应核对许可要求。清理旧图可调用 `FigureStorage.delete_older_than(days)`，按配置的 Blob 前缀列出并删除超过指定天数的文件。
