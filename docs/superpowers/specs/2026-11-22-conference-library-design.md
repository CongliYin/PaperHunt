# 顶会论文库设计

2026-11-22 设计，2026-11-23 实现

首页增加「顶会论文」入口，指向 `/conferences`。读者可以查“ICLR 2026 有哪些值得读的 Agent Memory 论文”，也可以查“哪些会议收录了对话导购研究”。会议库只展示有官方收录记录、通过现有领域规则和评分门槛的论文。会议名单和榜单索引独立存储，会议采集产生的记录只写入会议库。

## 会议范围与采信依据

| 首版会议 | 首选官方来源 | 收录范围 |
|---|---|---|
| NeurIPS（历史名称 NIPS） | NeurIPS Proceedings | Main Conference 和 Datasets and Benchmarks，保留官方 track |
| ICLR | 当届 OpenReview 官方 venue，接口受限时用 ICLR 官方论文集 | 已公开确认录用的主会论文，含 poster、spotlight 和 oral |
| ICML | PMLR 的当届 ICML 卷 | 主会论文 |
| ACL、EMNLP、NAACL | ACL Anthology 对应届次与卷 | 主会长短文、Findings、Industry 分别标注，可筛选 |
| SIGIR、RecSys | 当届官方 accepted papers、proceedings 或 ACM 对应卷 | 首版取研究长短文，补充电商检索和自然语言推荐 |

Workshop、Demo、Tutorial、非论文卷首内容、仅投稿、已撤回和已拒稿记录均排除。每篇记录会议、届次、track 和可点击的官方依据。会议卷和 OpenReview venue 按届配置；暂缺正式目录时保留待同步状态。SIGIR 的官方网站可能只有名单，须从官方论文页或 DOI 出版页补齐摘要；缺失摘要留待下次重试。

建议首批回填 2025、2026 两个会议年份中截至同步日已公开的卷，后续自动发现并增量处理新届次。具体的版面与条目规模以真实卷为准。四个方向之外的研究即使是大会口头报告也不能入选。

## 采集、身份与评审

1. 增量读取官方卷或录用名单，存原始快照。以会议、届次、track、官方条目 ID 标识收录记录，区分会议年份、官方发表时间与本站发现时间。
2. 论文实体支持 ACL Anthology ID、OpenReview forum ID、DOI、PMLR／NeurIPS 官方条目和可选 arXiv ID。优先使用已有标识符与官方互链合并。规范化标题、作者与年份只能用来发现待核对记录；有冲突时保留来源，不以相似标题自动覆盖。论文 PDF 从经过校验的官方链接读取。没有 arXiv ID 也能评审和打开详情。
3. 复用现有 `eligible`、模型初筛、精评和 `winner`，共用版本化的评审规则。每篇只归一个最匹配方向。页面只显示现有百分制评分；不为会议名次、oral 或 citation 额外加分。缺乏足够证据时按现有规则暂缓。复用旧评审必须同时满足正文版本、领域范围、规则版本和模型配置匹配。
4. 同一论文在 arXiv 日报和会议库各自满足条件时，日报保留原记录，会议库补充正式发表信息并可跳回日报。相同论文在会议库只展示一张卡，所有经核实的收录记录列在详情中。会议库新增一篇历史论文不会改变当日日报的排名和篇数。

## 数据、页面与调度

- 日报沿用现有索引。会议库单独写入 `web/public/conferences/`，通过独立入口文件引用不可变的列表和详情。默认按评分降序，同分按稳定标识排序，支持会议、年份、方向和 track 筛选。卡片展示会议与年份、方向、一个评分和入选理由，详情提供官方录用依据及 PDF。
- 继续使用一个 GitHub Actions 工作流和一个定时触发器。每天发布日报后检查会议来源的变化，新增及变更论文进入分批评审队列。每批设时间预算，持久化抓取游标、已评记录和待重试条目。会议同步失败保留该会议的上次有效快照，状态明确可查，已发布的日报继续可用。
- 手动运行保留原有按日期重跑日报的语义，可另选“只同步会议”并指定会议与年份。回填不要求在一次运行中完成；页面展示每届已处理数量、总数及更新时间，完整扫描成功之后再确认删除、撤回或改录。

## 验收

- 从不同官方来源抽样核对主会、Findings、Industry、Workshop、拒稿和撤回样例。正式收录证明与学术方向判断分别验证。
- 将 EMNLP 2025 Industry 的 ProductAgent 作为电商方向的正向样例，检查其官方链接、出版年份、track、入选理由与唯一方向。补测没有 arXiv ID 的论文及题名相近但作者不同的论文。
- 验证机器人、3D、世界模型等逐领域排除仍生效。会议来源与 arXiv 来源在相同证据下应得到相同判定。
- 对已有日报索引做前后哈希比对。只同步会议时日报索引不变；重复同步不会重复出卡；单源超时、分页中断、官方修订与撤稿均有回放用例。
- 前端生产构建覆盖会议空列表、部分回填、多条件筛选、详情链接和原日报入口。首批真实数据按会议列出已扫篇数、入选数与尚缺元数据的条数。

## 官方来源样例

[NeurIPS 论文集](https://proceedings.neurips.cc/) · [OpenReview 官方 venue 说明](https://docs.openreview.net/getting-started/frequently-asked-questions/how-do-i-find-a-venue-id) · [ICML 2025 论文集](https://proceedings.mlr.press/v267/) · [ACL 2025 论文集](https://aclanthology.org/events/acl-2025/) · [EMNLP Industry 的 ProductAgent](https://aclanthology.org/2025.emnlp-industry.25/) · [SIGIR 官方录用名单样例](https://sigir2025.dei.unipd.it/accepted-papers.html) · [RecSys 官方录用名单样例](https://recsys.acm.org/recsys25/accepted-contributions/)
