# 新闻智能分类、摘要、排序与飞书推送低层设计 v1

状态：**LLD 已确认；M0-1/M0-2/M0-3 已完成，冻结模型运行时已在 Prod HDD 隔离安装并完成 CPU 单模型基准；整窗 60 分钟与业务质量门禁仍须 M1 回放验证，尚未开发、迁移、部署常驻服务或发送飞书消息。**

创建日期：2026-09-21。

上位方案：[新闻智能分类、摘要、排序与飞书推送方案 v1](/Users/congming/github/goldenshare/docs/architecture/news-intelligence-digest-feishu-plan-v1.md)。本文把已确认的 D1–D17 转成代码、表、API、页面、状态机、测试与阶段门禁。所有依赖真实数据或模型基准的数值均标为 M0/M1 输出，不在 LLD 中猜测。

---

## 1. 开发目标、依据与边界

### 1.1 目标

1. 只处理三个来源各自上次成功 Raw `id` 水位之后的新身份。
2. 将全候选、事件、分类、重要度、摘要、Top 30、Top 15、影子观察和投递结果持久化到 HDD。
3. 在现有 `frontend/` 运营后台“审查中心 → 新闻智能”提供桌面端 Debug 与人工反馈。
4. 为飞书每条事件生成不可枚举的免登录 Wealth 原文详情链接；公开页不显示任何模型或系统字段。
5. 使用新闻简报专用飞书机器人；任一来源发现不完整或排序未完成时整次不发送。

### 1.2 非目标

- 不读取 `news.score`，不修改三个来源表，不复制完整原文。
- 不恢复 legacy 目录，不让 Biz 依赖 Ops，不让 Ops 依赖 Biz。
- 不建设移动端 Debug、模型训练平台、即时飞书告警或个性化推荐。
- 本文不授权安装依赖、下载模型、迁移数据库、写 Prod、创建 systemd 或发送真实消息。

### 1.3 当前证据

- Raw 三表均有稳定自增 `id` 和唯一 `row_key_hash`；重复 upsert 不产生新 `id`。
- Raw 三表没有 `created_at/first_seen_at`，且 `fetched_at` 会被 upsert 覆盖；旧数据不能精确复原历史净新增窗口或真实首见延迟。
- Serving Light 三表是 view，提供业务展示事实；`cctv_news` 只有内容日期，没有日内发布时间。
- 现有 Reader API 为 `/api/v1/wealth/market/news/items/{content_source}/{news_id}`，带 `require_quote_access`，只支持 `news/major_news`。
- 现有 Wealth Reader 已有 `URL/HTML/TEXT` 互斥合同和 HTML sanitizer。
- `wealth/src/app/routes/WealthRouter.tsx` 当前在所有业务路由之前执行登录守卫；公开详情必须在该守卫之前做唯一、显式分流。
- `frontend/` 是现行“财势乾坤数据运营管理综合平台”，已有“审查中心”；`wealth/` 是独立用户行情产品，二者不共享 Shell。
- Prod 默认 `pg_default` 在 SSD；HDD tablespace 为 `gs_raw_cold_hdd`。
- 2026-09-24 首次 M0 观测到 `cctv_news` 最新业务日期停在 2026-08-19；用户手动补数后，18:32 只读复核确认已连续补到 2026-09-23，Raw/Serving 双向对账为 0 差异。当前内容完整性已恢复，但自动更新、失败告警和持续 freshness 尚未验收。
- Prod 为 8 vCPU/15 GiB 内存、无 GPU 的 CPU-only 环境；HDD 余 264 GiB，项目环境未安装目标模型栈，也未发现 Hugging Face 模型缓存。

---

## 2. 架构与依赖

```text
Raw id discovery + Serving facts
             │
             ▼
src/biz/news_intelligence
  domain / repositories / pipeline / policies / queries
             │ ports
             ▼
src/app/runtime/news_intelligence
  scheduler / worker / model adapters / Feishu adapter
             │
       ┌─────┴───────────────┐
       ▼                     ▼
frontend Ops Debug       wealth Public Detail
authenticated            anonymous, field-minimized
```

依赖保持 `App → Biz → Foundation`。模型和飞书是 Biz 定义的端口、App 提供的适配器。Ops 只可接收 App 写入的 TaskRun 观测投影；新闻业务表、评分和投递合同不进入 `src/ops`。

### 2.1 目标目录

```text
src/biz/models/wealth/news_intelligence/
  policy.py run.py candidate.py event.py analysis.py delivery.py feedback.py
src/biz/services/wealth/news_intelligence/
  canonical_reader.py discovery_service.py clustering_service.py
  classification_service.py scoring_service.py summary_service.py
  ranking_service.py delivery_builder.py public_detail_service.py
src/biz/queries/wealth/news_intelligence/
  debug_query_service.py public_detail_query_service.py
src/biz/schemas/wealth/news_intelligence/
  debug.py public_detail.py delivery.py
src/app/runtime/news_intelligence/
  scheduler.py worker.py model_adapters.py feishu_adapter.py lifespan.py
src/app/api/v1/
  news_intelligence_debug.py news_public_detail.py
frontend/src/pages/
  ops-news-intelligence-page.tsx
frontend/src/features/news-intelligence/
wealth/src/pages/news-detail/
wealth/src/features/news-detail/
```

`src/app/api/v1` 仅做认证/匿名入口、依赖注入和异常映射，业务查询全部委托 Biz；不得在路由中计算排名、拼 DTO 或读取 ORM。

---

## 3. 数据库低层设计

### 3.1 共同规则

- schema：`app`；前缀：`wealth_news_digest_`。
- 所有表、TOAST、主键/唯一/普通索引：`gs_raw_cold_hdd`。
- 迁移先断言 tablespace 存在；缺失时失败，禁止 SSD fallback。
- JSON 使用 `JSONB`，只存 schema 校验后的有界结构；正文仍从 Serving Light 读取。
- 所有时间为 `timestamptz`，业务窗口时区固定 `Asia/Shanghai`。
- 禁止自动 downgrade 删除数据；修订迁移采用前向补偿。

### 3.2 表与关键约束

| 表 | 主键/唯一键 | 关键字段与职责 |
|---|---|---|
| `wealth_news_digest_policy` | `policy_id`; `name` unique | enabled、五时点、timezone、delivery/debug 上限、激活版本、专用凭据引用 |
| `wealth_news_digest_run` | `run_id`; `(policy_id, scheduled_at)` unique | 展示窗口、冻结时点、版本快照、阶段、单调进度、终态、结果计数 |
| `wealth_news_digest_source_cursor` | `(policy_id, source_type, cursor_kind)` | `last_raw_id`、`frozen_max_raw_id`、成功 Run；FIXED/SHADOW 分离 |
| `wealth_news_digest_candidate` | `candidate_id`; `(run_id, source_type, source_key)` unique | source_sequence、hash、业务时间、不可变 discovered_at、stage、reason、event、初/终分与排名；不存正文 |
| `wealth_news_digest_event` | `event_id`; `event_fingerprint` index | 代表来源、首末观察时间、embedding bytes/dim/model、状态 |
| `wealth_news_digest_event_member` | `(event_id, source_type, source_key)` | 事件成员及新增事实标记；禁止重复来源成员 |
| `wealth_news_digest_analysis` | `analysis_id`; `(event_id, analysis_version)` unique | 标签、七维评分、证据、摘要、核验、所有版本与输入/输出 hash |
| `wealth_news_digest_delivery` | `delivery_id`; `(run_id, target_ref, payload_hash)` unique | Top 15 冻结序列、payload、状态、attempt、响应与时间 |
| `wealth_news_digest_public_detail` | `public_id` unique; `(delivery_id, event_id)` unique | 随机公开 ID、代表 source_type/source_key、created/revoked；只为正式 delivery 建立 |
| `wealth_news_digest_shadow_observation` | `observation_id` | 触发、延迟、would-send、复核与后续固定窗口结果；无即时 delivery |
| `wealth_news_digest_feedback` | `feedback_id`; `(event_id, reviewer_id, feedback_type, created_at)` index | 运营人工标记、可选备注、关联版本；不覆盖冻结分析 |

### 3.3 状态与检查约束

- Run：`DISCOVERING → ENRICHING → RANKING → READY → DELIVERING → SUCCEEDED`；允许 `PARTIAL/FAILED/CANCELLED` 终态。
- Candidate stage：`DISCOVERED/CLEANED/CLUSTERED/CLASSIFIED/DEEP_ANALYZED/RANKED/EXCLUDED/FAILED`。
- Delivery：`DRAFT/READY/SENDING/SUCCEEDED/RETRYABLE_FAILED/FINAL_FAILED/SUPPRESSED`。
- `source_type ∈ {NEWS, MAJOR_NEWS, CCTV_NEWS}`；`cursor_kind ∈ {FIXED, SHADOW}`。
- 进度字段非负、done 不大于 total；final_rank 必须大于 0；公开详情被撤回后仍统一返回 404。

### 3.4 索引

至少建立：

- Run：`(scheduled_at DESC)`、`(status, scheduled_at)`；
- Candidate：`(run_id, final_rank)`、`(run_id, stage)`、`(source_type, source_key)`；
- Event member：`(source_type, source_key)`；
- Analysis：`(event_id, created_at DESC)`；
- Delivery：`(status, updated_at)`；
- Feedback：`(event_id, created_at DESC)`；
- Public detail 只按 `public_id` 精确查询，不建立可浏览时间索引。

迁移测试必须枚举新 schema 的每个 relation，并核验有效 tablespace；只检查 table 不足以通过。

---

## 4. 增量发现、事务与续跑

### 4.1 Run 冻结

每个计划时点以 `(policy_id, scheduled_at)` 幂等创建 Run。在同一短事务中读取三个 FIXED cursor，分别查询 Raw `max(id)` 并写入冻结上界。后续条件固定为：

```text
last_success_raw_id < raw.id <= frozen_max_raw_id
```

Raw 只提供身份序列；按 `row_key_hash` 批量读取 Serving Light 事实。任何来源冻结或读取失败，Run 不进入 READY，三个来源 cursor 均不推进，delivery 记 `SUPPRESSED`。

### 4.2 执行 unit

- discovery unit：一个来源最多 500 个 Raw 身份，候选写入即提交；
- embedding/classification unit：一个有界事件批次；
- deep-analysis unit：单事件；
- ranking unit：冻结事件集合的一次确定性排序；
- delivery unit：一个不可变 payload 的一次发送尝试。

每个 unit 前后检查取消。业务写入与观测写入分事务；观测失败不回滚已提交候选/分析。恢复时从持久化 stage 继续，不重新扩大冻结范围。

### 4.3 Cursor 推进

只有三个来源在冻结范围内都达到允许终态且排名成功，才在一个事务中把三个 FIXED cursor 推进到各自 frozen max。飞书失败不回退 cursor。SHADOW cursor 独立推进，永不改变 FIXED cursor。

---

## 5. 模型与策略端口

Biz 只依赖以下端口：`EmbeddingPort.embed()`、`NliClassifierPort.classify()/verify()`、`GenerativeAnalysisPort.analyze()/summarize()`。App 适配器固定 model id、revision、量化格式和预算。

处理顺序：确定性清洗 → 精确去重 → embedding/事件聚类 → mDeBERTa 多标签与初排 → 有界 Qwen → NLI 摘要核验 → 最终排序。

禁止让模型直接写 0–100 分；它只返回 schema 固定的档位、证据和置信度。任意非法 JSON、超长输出、证据越界或 Prompt 注入迹象都转 reason code。

M0 已冻结 discovery batch 为 500、摘要资格默认阈值为正文 800 字、HDD 一期容量预算为 10 GiB/年。800 字只是进入摘要候选的必要条件，仍须先通过事件选择和重分析预算；不得把全部长文直接交给生成模型。

M0 同时冻结首轮 benchmark 制品：Embedding 使用 `Qwen/Qwen3-Embedding-0.6B@97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3` 的 `model.safetensors`；分类/NLI 使用 `MoritzLaurer/mDeBERTa-v3-base-mnli-xnli@8adb042d524ecd5c26d3e3ba0e3fbcf7e2d0864c` 的原仓库量化 ONNX；生成使用 `Qwen/Qwen3-4B-GGUF@bc640142c66e1fdd12af0bd68f40445458f3869b` 的官方 `Q4_K_M` 作为有条件 CPU 候选。逐文件大小、SHA-256、许可证和准入说明见 M0 报告 §6.1。该生成候选不是 `Qwen3-4B-Instruct-2507` 同权重量化，必须通过 M1 质量门禁后才可进入一期模型策略。

M0-2 冻结的 `/data/disk/goldenshare/news-intelligence` 专用 HDD 根、Python 3.13 独立 venv、44 个带哈希 CPU wheel、llama.cpp b11146、模型白名单文件和 4,400,018,597 bytes 下载量，已在 M0-3 按原合同安装和复核，见 M0 报告 §6.2–§6.3。项目 `.venv` 未修改；模型、wheelhouse、venv、cache、staging 和 tmp 均位于 HDD。

M0-3 冻结 M1 安全上限：Embedding `batch=1/max_tokens=512`；mDeBERTa `batch=16/max_tokens=512`；Qwen `threads=4/parallel=1/ctx=2048/deep_analysis_limit=30`。三模型必须按阶段串行、单实例驻留；独立 App-owned 模型 Worker 负责拉起和回收子进程，Qwen 仅绑定 loopback llama-server，必须做 singleton 断言和进程组级超时/取消清理。M0-3 没有部署该 Worker、systemd 或配置。

单模型可运行不等于整窗准入：以 790 个规范化标题组保守组合测算，128-token Embedding、39 个平铺 NLI 假设和 30 个 1,400 字 Qwen 调用约 84.7 分钟，超过 60 分钟。M1 必须用真实 replay 冻结短代表文本、分层标签候选和实际事件数；禁止全量平铺标签或把触达上界直接交给模型。最终生成模型业务准入、embedding/分类阈值、端到端 RSS/CPU/wall-clock、核心标签阈值和 Precision@15 仍由 M1 回填。

---

## 6. 排名、失败与投递

1. 原始总分、门禁结果、多样性调整和最终排名分别保存，前端不得重算。
2. Top 15 是上限，不足不补齐；Top 30 和全部候选均可审查。
3. 任一来源发现不完整、冻结集合不完整、ranking 未成功或 payload 校验失败：Feishu adapter 调用次数必须为 0。
4. 单条 Qwen 摘要失败但来源正文有效、可信度合格时，可用抽取式精简句并标记“摘要降级”；分类/聚类/可信度失败不能借此放行。
5. payload 生成后不可变；重试只发送相同 payload/hash，不重跑模型。
6. 专用凭据键建议 `NEWS_DIGEST_FEISHU_WEBHOOK_URL/SECRET`，最终命名在实现前配置审计冻结；禁止回退到 `GOLDENSHARE_FEISHU_*`。

---

## 7. API 合同

### 7.1 运营 Debug（需运营登录）

建议入口由 App 做权限装配，Biz 查询返回事实：

- `GET /api/v1/wealth/news-intelligence/debug/runs`
- `GET /api/v1/wealth/news-intelligence/debug/runs/{run_id}`
- `GET /api/v1/wealth/news-intelligence/debug/runs/{run_id}/candidates`
- `GET /api/v1/wealth/news-intelligence/debug/events/{event_id}`
- `POST /api/v1/wealth/news-intelligence/debug/events/{event_id}/feedback`

列表必须服务端分页，默认 Top 30；“全部候选”仍分页，禁止整窗一次返回。反馈枚举：`CLASSIFICATION_WRONG/IMPORTANCE_WRONG/CLUSTER_WRONG/SUMMARY_FACT_WRONG/SHOULD_TOP15/SHOULD_NOT_TOP15`。写反馈不修改分析、排名或历史 delivery。

### 7.2 公开原文详情（匿名）

- 页面：`GET /wealth/market/news/detail/{public_id}`；
- API：`GET /api/v1/public/news-details/{public_id}`；
- `public_id` 为至少 128 bit CSPRNG 生成的 URL-safe 标识，无顺序、无业务语义、不可由 source key 推导；
- DTO 仅含 `title/source/publishTime/contentDate/readerMode/url/html/content/originalUrl`；payload 仍保持 `URL/HTML/TEXT` 互斥；
- 不返回 source type/key、Run/event/delivery、分类、摘要、评分、版本、错误内部原因；
- 无效、撤回、内容不可用统一 404；超大内容使用同一用户文案，不泄露存在性；
- 响应设置 CSP、`X-Content-Type-Options: nosniff`、`Referrer-Policy`、`X-Robots-Tag: noindex, nofollow, noarchive`，并按 public_id/IP 做有界限流；精确数值由 M0/部署容量确定。

现有鉴权 Reader API 不改权限、不改路径。公开 API 复用 Biz 内容解析器，但使用独立 DTO 和查询入口。

---

## 8. 前端低层设计

### 8.1 运营平台

目标平台是 `frontend/`，不是 Wealth，也不是已退役的 Lake Console UI。导航在现有 `OpsShell` 的“审查中心”下新增“新闻智能”，路由 `/ops/v21/review/news-intelligence`。

桌面页面分为：Run 选择与状态、Top 30、全部候选、单事件抽屉、实际/拟投递、Shadow、人工反馈。使用现有 Mantine、DataTable、SectionCard、StatusBadge；分页和筛选由后端负责。响应式只要求现有运营后台支持范围，不设计移动端 Debug。

### 8.2 公开 Wealth 详情

`WealthRouter` 必须先识别严格正则的公开详情路径，再执行现有登录守卫；其他所有 Wealth 路由行为保持不变。页面无顶层行情导航、账户入口、Debug 信息或后台链接，只展示品牌、原文标题/来源/时间/正文和可选外部来源按钮。

四态：loading、ready、not-found、error。HTML 只能通过现有 `SanitizedHtmlContent`；URL iframe 如受外站策略阻止，显示外部打开动作和明确状态。桌面与移动端都必须完成正文换行、表格横向滚动和长 URL 验收。

---

## 9. 调度、进程与配置

五个固定时点为 `08:00/12:00/16:00/20:00/22:00 Asia/Shanghai`。LLD 不预设复用现有 Ops scheduler 或新建 systemd；当前只设计 App-owned scheduler/worker 接口。最终进程入口必须在获批的模型实机 benchmark 后根据单窗口耗时与内存决定，并另获部署批准。

配置分层：业务偏好和版本策略进 policy DB；模型路径/资源、公开 origin、专用飞书凭据进部署 Settings。所有配置在实现前形成“名称、默认、来源、消费者、生效、运维可见性、测试”的最终表，不允许页面常量。

---

## 10. M0 与 M1 合同

### 10.1 M0（M0-1/M0-2/M0-3 已完成）

完整证据见 [M0 测量与实机验证报告（2026-09-24—2026-09-28）](/Users/congming/github/goldenshare/docs/architecture/news-intelligence-digest-feishu-m0-readonly-validation-2026-09-24.md)。已完成 30 个代表窗口、两个极端窗口、字符分布、空值、规范化标题重复代理、延迟代理、事件代理、HDD 增长、Prod 资源盘点、隔离安装和单模型基准；没有写正式业务表。

M0 的硬结论：

1. 08:00 为绝对峰值；抓取触达上界最高为 7,827 条，历史 `id` 净新增只能得到约 900 条的下界代理，正式 shadow cursor 才能产出可信分布。
2. `news` 只有 48/27,566 条达到 800 字，`major_news` 有 9,764/9,889 条达到 800 字；默认摘要资格阈值冻结为 800 字。
3. `cctv_news` 首次观测时中断约 36 天；手动补数后当前数据完整性通过。自动更新由用户另行处理，仍须在正式投递前验收，但不计入 M0 剩余任务。
4. 新库按 10 GiB/年在 `gs_raw_cold_hdd` 预留；Prod HDD 容量满足一期。
5. 三个首轮模型制品、44 个 Python wheel 和 llama.cpp 已在 Prod HDD 隔离安装并通过哈希、离线依赖和 smoke 验收；Embedding/mDeBERTa/Qwen 单模型峰值 RSS 分别约 1.78/1.49/4.35 GiB，现有 Web/Ops 服务保持 active。
6. 单模型基准通过，但保守整窗组合约 84.7 分钟，60 分钟门禁未通过；M1 必须收缩模型入口并做真实端到端回放，不能以增加并发解决。

### 10.2 M1（第一开发切片）

实现离线 replay/标注能力，只读旧日期事实并写隔离输出，不写正式 Run/cursor/delivery。标注工具首轮默认在本地私有部署 Argilla；它只通过稳定 `sample_id` 导入样本、导出版本化标注，不成为生产运行时依赖，也不直接写正式业务表。先完成 100–150 条 taxonomy 定义试标并修订标签边界，再冻结 600–1000 条正式样本，产出人工一致性、分类、聚类、摘要、Top15/30 和资源报告。M1 后回写 taxonomy/scoring/summary/model policy；未过门槛不得进入 Prod 持久化切片。

---

## 11. 编码门禁矩阵

| 门禁 | 落点 | 正向测试 | 负向测试 |
|---|---|---|---|
| 禁用 `news.score` | Canonical reader 字段白名单 | 三来源映射 | 静态扫描/spy 证明未读取 |
| 仅增量 | Raw id cursor | 冻结范围无漏 | 重复 upsert、迟到、同时间不重复 |
| HDD | migration | 每 relation 有效 tablespace | 缺 tablespace 或任一 SSD relation 失败 |
| 有界模型 | selector/budget | 选中集合运行 | 预算耗尽不扩大、不 Full |
| 事实摘要 | verifier | 数字/实体支持 | 幻觉降级且不伪装成功 |
| 失败不发送 | delivery gate | 完整 Run 可 READY | 任一来源/排序失败 Feishu 零调用 |
| 专用机器人 | Settings/adapter | 专用凭据成功 | Ops 凭据串用拒绝 |
| 公开最小化 | Public DTO | 三来源原文可读 | Debug 字段、枚举 ID、列表/搜索不存在 |
| 公开安全 | route/sanitizer/headers | 移动/桌面正常 | XSS、危险协议、无效 ID、限流 |
| Debug 归属 | frontend Ops | Top30/全部/反馈 | Wealth 和移动端无 Debug |
| 留档 | schema/runtime | 90 天容量报告 | 无自动 delete/archive job |
| 续跑幂等 | unit 状态/唯一键 | 退出后续跑 | 不重复候选、分析、发送 |
| 分层 | 架构护栏 | App→Biz→Foundation | Biz↔Ops、下层→App/QTF 零新增 |

Wealth 通用清单中图表、涨跌色、累计坐标等条目不适用，因为公开详情无图表或行情计算；真实 API、契约冻结、状态机、安全、性能、响应式和端到端测试适用。无其他例外白名单。

---

## 12. 验证命令与验收证据

计划命令（实现后按切片执行）：

```text
pytest tests/news_intelligence tests/web/test_news_intelligence_*.py
pytest tests/architecture/test_subsystem_dependency_matrix.py
npm --prefix frontend run typecheck
npm --prefix frontend run test -- news-intelligence
npm --prefix frontend run build
npm --prefix wealth run typecheck
npm --prefix wealth run test -- news-detail
npm --prefix wealth run build
python3 scripts/check_docs_integrity.py
```

页面改动必须浏览器验证运营桌面端、Wealth 桌面/移动端、console/network、XSS 样本和匿名访问。Prod 写入前另做迁移 Preview、HDD relation 清单和最小真实运行—取消—续跑—读回；飞书启用前先测试群。

---

## 13. 建议实施切片

1. L0：评审本文；**已完成**。
2. L1：执行 M0 并回写本文参数、容量和进程决定；**已完成**。
3. L2：实现并运行 M1 离线 replay/反馈样本，冻结策略版本。
4. L3：HDD migration、ORM/repository、增量 cursor、Run 状态机。
5. L4：模型端口/适配器、有界 pipeline、排名与 Debug API。
6. L5：`frontend/` 新闻智能 Debug/反馈页面；固定窗口 shadow delivery。
7. L6：公开详情表/API、Wealth 免登录页和安全验收。
8. L7：专用飞书测试群投递；观察通过后再单独批准正式目标。
9. L8：重大新闻 Shadow，仅观察，不即时发送。

每个切片独立评审与验收，前一切片未通过不自动进入下一切片。

---

## 14. LLD 评审后仍需由证据决定的事项

以下不是当前要求用户凭偏好拍板的产品项：最终生成模型业务准入、聚类与分类阈值、端到端资源上限、公开限流数值、Precision@15 门槛。它们由 M1 或对应实施验证给出证据并回写本文。三个首轮候选制品的 revision/格式、Raw discovery batch、摘要资格默认阈值、HDD 容量预算及 M1 模型安全上限已由 M0 回填。

用户已确认：运营 Debug 使用现有运营平台；详情免登录且不展示系统信息；移动端不做 Debug；部分失败不推送；候选/分析一期不自动删除；使用专用飞书机器人并由用户后续提供地址和密钥；Argilla 可部署本地或 Prod，首轮默认本地，后续仅在多人持续协作或远程访问需求明确时评估 Prod。

---

## 15. 版本记录

| 版本 | 日期 | 说明 |
|---|---|---|
| v1 | 2026-09-21 | 首版编码前 LLD；冻结已确认产品边界，保留 M0/M1 实测槽位 |
| v1.1 | 2026-09-24 | 同步 taxonomy v2 两阶段标注合同与 Argilla 首轮本地部署边界 |
| v1.2 | 2026-09-24 | 回写 M0 30 窗口、800 字摘要门槛、500 行 discovery batch、HDD/硬件与来源完整性门禁；并补记手动补数后的 Raw/Serving 复核；模型基准仍待授权 |
| v1.3 | 2026-09-24 | 冻结三个首轮模型候选的官方 revision/文件/SHA-256；纠正 Instruct-2507 无官方 4-bit GGUF 的制品事实，改以官方 Qwen3-4B Q4_K_M 作为有条件 CPU benchmark 候选 |
| v1.4 | 2026-09-24 | 完成 M0-2：冻结 Prod 目标平台、HDD 安装边界、44 个 Python wheel、llama.cpp b11146、模型白名单和 4.40 GB 完整下载量；安装下载仍待单独授权 |
| v1.5 | 2026-09-28 | 完成 M0-3：Prod HDD 隔离安装和三模型 CPU 基准；冻结串行进程形态与 M1 安全上限，并记录整窗 60 分钟门禁尚未通过 |
