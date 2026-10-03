# 新闻智能分类、摘要、排序与飞书推送方案 v1

状态：**方案与 LLD 已确认；M0及M1-0/1/2已完成。2026-10-03用户批准v3机器辅助审核，旧120条表单暂停，旧20条教学标注保留。新版审核工具及10条真实预标注已实现，Argilla新版教学集已导入10条，待用户试审；75项测试通过。M1-3、业务质量和最大整窗60分钟门禁仍未完成。没有数据库迁移、常驻生产服务或飞书发送。**

创建日期：2026-09-21。

本文定义 `news` 新闻快讯、`major_news` 新闻通讯与 `cctv_news` 新闻联播的增量智能处理、调试分析、定时飞书推送和重大新闻影子观察目标。现行新闻采集仍以 [Ops 新闻日内高频自动任务方案](/Users/congming/github/goldenshare/docs/ops/ops-intraday-news-high-frequency-schedule-plan-v1.md)及三个数据集合同为准；股票关联与页面事件合并仍以[新闻关联与股票详情事件展示维护说明](/Users/congming/github/goldenshare/docs/architecture/news-stock-linking-low-level-design-v1.md)为准。本文不重新定义源接口、DatasetDefinition、采集调度、股票新闻关联或现行 Wealth 新闻 API。

---

## 1. 目标与非目标

### 1.1 目标

1. 每天北京时间 `08:00 / 12:00 / 16:00 / 20:00 / 22:00`，只处理上次成功截止点之后新入库的新闻。
2. 统一读取快讯、通讯和新闻联播，但不复制、不覆盖三个来源的原始正文。
3. 对本窗口新增新闻完成确定性清洗、语义去重、事件聚类、多标签分类、重要度初排和可解释证据留档。
4. 只对有价值的有限候选调用生成式模型；不让 Qwen 对全部历史或本窗口所有文章无边界推理。
5. 正式飞书消息最多推送 15 个事件；每条事件附带可点击的站内详情链接；调试视图至少保留最终 Top 30，并可查看本窗口全部候选及各阶段去向。
6. 重大新闻即时能力一期运行在影子模式：识别、复核、保存拟发送结果，但不调用飞书。
7. 使用旧日期的有界样本做分类体系、摘要、聚类和排序校准；不建设大模型训练平台，不把模型微调作为一期前提。

### 1.2 非目标

1. 不读取、映射、展示或训练现有 `news.score`，它不参与任何分类、摘要、重要度或排序。
2. 不对全历史新闻执行生产模型任务，不做启动时 Full，不在失败后静默回放全部历史。
3. 不修改 `raw_tushare`、`core_serving_light` 的新闻事实，不将模型结果写回源表。
4. 不把新闻业务塞入现有 `FeishuTaskNotificationService`；该服务继续只负责 Ops TaskRun 完成通知。
5. 不新增 Foundation → Biz/Ops/App、Biz → Ops 或 Ops → Biz 反向依赖。
6. 不在一期做个性化大模型微调、在线学习、自动交易、投资建议或即时飞书告警。
7. 不因本文批准模型下载、依赖安装、数据库迁移、Prod 写入、systemd 变更或生产部署；每项仍需独立实施授权。
8. 不把原始 HTML、正文 JSON 或数据库查询结果直接暴露给飞书；飞书链接只进入字段最小化的公开 Wealth 详情页，Debug 与系统字段仍只在运营后台展示。

---

## 2. 已确认硬口径

| 编号 | 口径 | 设计约束 |
| --- | --- | --- |
| D1 | 三个来源 | `news / major_news / cctv_news` 均进入统一候选读取层 |
| D2 | 禁用旧分数 | `news.score` 永远不进入本能力 |
| D3 | 增量生产 | 只处理上次成功水位之后新入库记录；无生产 Full |
| D4 | 固定推送时点 | 北京时间 08、12、16、20、22 点 |
| D5 | 推送数量 | 每次最多 15 个事件，不为凑数降低门槛 |
| D6 | 调试范围 | 默认查看 Top 30；本窗口全部候选、排除原因和阶段结果均留档 |
| D7 | 重要度视角 | 中国资本市场与投资研究价值优先；宏观政策、科技与人工智能重点关注 |
| D8 | 多标签分类 | 首版分类先运行，再用真实旧日期样本验证并版本化调整 |
| D9 | 短文不摘要 | 一句话快讯等短文本不做生成式摘要 |
| D10 | 即时能力 | 一期只做重大新闻影子观察，不做即时飞书发送 |
| D11 | 不要求微调 | 使用冻结开源模型、Prompt、规则和阈值校准；一期不训练大模型 |
| D12 | Prod 部署 | 模型最终部署到 Prod，但必须先通过 CPU、内存、耗时和业务服务影响门禁 |
| D13 | HDD 存储 | 新闻 Digest 新表、主键/唯一/普通索引必须显式落到 Prod HDD tablespace，禁止回退 SSD |
| D14 | 原文详情 | 飞书每条新闻附免登录的站内 HTTPS 详情链接；公开页只显示新闻原始信息，不直链数据库 HTML/JSON，不展示 Debug/系统字段 |
| D15 | 失败发送 | 任一来源发现不完整或排序未完成时整次不推送；单条摘要失败但原文有效时允许明确标记后降级发送 |
| D16 | 留档周期 | 一期候选引用与结构化分析不自动删除，保存在 HDD；运行 90 天后只评估容量，不未经批准清理 |
| D17 | 飞书隔离 | 使用新闻简报专用机器人/Webhook，不复用 Ops 任务通知机器人；凭据由用户在实施阶段提供 |

计划对账要求：后续每个里程碑必须逐项说明 D1–D17 落在哪个代码、迁移、测试和验收证据中；未实现项不得默认算完成。

---

## 3. 当前事实与目标差距

### 3.1 当前数据与消费事实

| 能力 | 当前事实 | 本方案关系 |
| --- | --- | --- |
| 快讯事实 | Raw 有稳定自增 `id` 和 `row_key_hash`；`core_serving_light.news` 提供 `row_key_hash/src/news_time/title/content/channels/fetched_at` | Raw `id` 只用于新增身份发现；Serving 提供业务事实 |
| 通讯事实 | Raw 有稳定自增 `id` 和 `row_key_hash`；`core_serving_light.major_news` 提供 `row_key_hash/src/pub_time/title/content/url/fetched_at` | Raw `id` 只用于新增身份发现；Serving 提供业务事实 |
| 新闻联播事实 | Raw 有稳定自增 `id` 和 `row_key_hash`；`core_serving_light.cctv_news` 提供 `row_key_hash/date/title/content/source/fetched_at` | Raw `id` 只用于新增身份发现；源端没有日内发布时间 |
| 市场新闻 API | Biz 已分别读取快讯与通讯，提供 `/briefs`、`/communications` | 现行页面合同，不直接改造成 Digest API |
| 新闻正文阅读 | Biz 已提供鉴权 JSON API `/api/v1/wealth/market/news/items/{content_source}/{news_id}`，前端按 `URL/HTML/TEXT` 展示并对 HTML 做清洗；目前只支持 `news/major_news` | 可复用解析和安全渲染逻辑，但不能直接取消现有鉴权；必须另建最小公开合同、补 `cctv_news` 和独立可深链页面 |
| 新闻采集 | `news`、`major_news` 已支持日内高频 DatasetDefinition/TaskRun 维护 | 上游事实供应，不负责模型处理 |
| 股票新闻关联 | 已按新闻时间做股票关联与请求内事件合并 | 规则与身份可参考，但不等于本方案跨来源语义事件簇 |
| 飞书任务通知 | Ops 已有带签名 Webhook 发送、超时和错误检查 | 只审计低层能力，不复用其 TaskRun 专用消息合同 |

2026-09-21 对 Prod PostgreSQL 系统目录做了只读核验：数据库 `goldenshare` 的默认 tablespace 是 SSD 上的 `pg_default`，现有 `app` 关系也使用 `pg_default`；HDD tablespace `gs_raw_cold_hdd` 位于 `/data/disk/postgresql/tablespaces/gs_stk_mins_hdd`。因此仅把表建在 `app` schema 并不能满足 HDD 约束，迁移必须显式指定 tablespace。

`cctv_news` 当前只有节目日期，没有精确播出时刻。本方案以 Raw 自增 `id` 是否在本次冻结增量范围内决定它进入哪个处理 Run，以 `date` 作为内容日期；禁止伪造日内发布时间。

当前三个 Raw DAO 的 upsert 会更新除冲突键、主键和 `created_at` 外的可变列，重复采集可能刷新 `fetched_at`。因此 `fetched_at` 不是可靠的“首次发现时间”，不能用于成功游标；使用它会让同一来源身份在高频采集后反复进入模型。Raw 自增 `id` 在 `row_key_hash` 冲突更新时保持不变，才是当前代码下可用的新增身份序列。

### 3.2 目标差距

当前没有以下能力：

1. 三来源统一候选身份和 per-source 成功水位；
2. 模型版本化分类、摘要、重要度证据；
3. 跨来源持久化事件簇；
4. 全候选调试账本和 Top 30 排名解释；
5. 业务新闻 Digest 运行、投递和重试事实；
6. 重大新闻影子观察账本；
7. 面向该业务的模型 Worker、资源门禁与运行指标。
8. 可从飞书直接打开、覆盖三个来源且字段最小化的免登录新闻详情深链页。

这些均是本文的目标设计，不能表述为当前已实现。

---

## 4. 分层与目标架构

```text
core_serving_light.news / major_news / cctv_news
                        │
                        ▼
Biz CanonicalNewsReader（只读统一适配）
  ├─ per-source Raw id 增量水位
  ├─ 确定性文本清洗
  └─ 统一 CanonicalNewsItem（内存对象，不建统一原文表）
                        │
                        ▼
Biz News Intelligence Pipeline
  ├─ 精确去重
  ├─ Embedding 与语义事件聚类
  ├─ 多标签分类
  ├─ 重要度初排
  ├─ 有界 Qwen 深度分析/摘要
  ├─ 最终排序与多样性控制
  └─ Top 30 debug / Top 15 delivery / shadow observation
                        │
                        ▼
App Runtime Composition
  ├─ 调度 Biz 运行
  ├─ 装配模型端口
  ├─ 装配 Feishu transport
  └─ 隔离业务提交与观测/投递失败
                        │
                        ▼
Wealth 新闻详情页（公开 HTTPS 深链）
  ├─ 飞书富文本链接进入稳定路由
  ├─ 调用字段最小化的 Public News Detail API
  └─ 按 URL / sanitized HTML / TEXT 安全展示原文
```

### 4.1 目录职责

| 层 | 负责 | 不负责 |
| --- | --- | --- |
| Foundation | 现有新闻事实、底层模型推理客户端的纯技术合同（若后续全仓复用且经审计批准） | 新闻分类口径、重要度和飞书卡片 |
| Biz | 统一读取、分类体系、事件聚类、摘要政策、重要度、候选/事件/运行/投递业务事实、Debug 查询 | Ops TaskRun 规则、应用进程装配 |
| Ops | 可选的通用运行观测，不包含新闻业务评分和消息内容 | 导入 Biz、直接执行新闻业务 |
| App | 组合 Biz、模型适配器、飞书传输与 Worker；进程入口和依赖注入 | 重新实现分类、评分和摘要规则 |
| `frontend/` 运营后台 | 在“审查中心”新增“新闻智能”入口，消费 Debug/人工反馈 API，不重算排名和重要度 | 自行拼接事实、保存模型密钥或向移动端提供 Debug 功能 |
| `wealth/` 用户前端 | 提供免登录新闻原文详情页，只展示公开 DTO 中的新闻原始信息 | 展示模型评分、Prompt、reason code、运行状态或其他 Debug/系统字段 |

如果后续让 Ops TaskRun 观测本流程，必须由 App 组合调用 Ops 与 Biz；Biz 和 Ops 彼此不能反向导入。业务完成事实仍以 Digest Run 表为准，TaskRun 只能作为运行观测投影。

---

## 5. 时间窗口与增量水位

### 5.1 计划窗口

| 计划时点 | 内容展示窗口 |
| --- | --- |
| 08:00 | 前一日 22:00 至当日 08:00 |
| 12:00 | 当日 08:00 至 12:00 |
| 16:00 | 当日 12:00 至 16:00 |
| 20:00 | 当日 16:00 至 20:00 |
| 22:00 | 当日 20:00 至 22:00 |

调度时区固定为 `Asia/Shanghai`。展示窗口表达用户看到的时段；真实增量选择必须使用 Raw 新增身份水位，不能只按业务发布时间或会被重复刷新 `fetched_at`。

### 5.2 每来源独立水位

每个来源维护独立 Raw 序列水位：

```text
last_raw_id
```

读取条件：

```text
last_success_raw_id < raw.id <= frozen_max_raw_id
```

其中：

- `frozen_max_raw_id` 在 Run 创建时按来源冻结，不随模型执行耗时变化；
- Raw `id` 只用于发现新来源身份，业务内容仍按同一 `row_key_hash` 读取 Serving 事实；
- `source_key` 仍是跨层稳定身份 `row_key_hash`，不能把 Raw `id` 暴露为业务新闻 ID；
- 三个来源分别推进水位，禁止一个来源失败却推进全部来源；
- 业务发布时间只用于展示、时效判断和事件顺序，不用于证明记录已经被处理；
- 迟到的旧日期新闻只要形成新的 Raw 身份和更大的 `id`，就会在后续 Run 被发现；
- 重复抓取同一 `row_key_hash` 只更新原 Raw 行，不产生更大的 `id`，不会反复进入模型；
- 如果未来 Raw 身份或 upsert 语义改变，必须先重审该游标合同，不能继续沿用本文结论。

### 5.3 成功与失败推进

1. Run 候选发现完成后先持久化候选事实和冻结游标上界。
2. 单候选、单事件分批提交；进程退出后从持久化阶段继续。
3. 模型部分失败不能删除已完成候选；失败项记录 reason code。
4. 只有来源候选均完成到允许终态后，才推进该来源成功水位。
5. 飞书失败不回滚分类、摘要和排名结果，也不回退来源水位；投递按同一个 payload hash 幂等重试。
6. 空窗口保存成功 Run 和水位证据，但不发送“无重要新闻”消息。

---

## 6. 统一输入对象与持久化设计

### 6.1 CanonicalNewsItem

统一结构首先是 Biz 内的只读内存对象，不是新的原文事实表：

```text
source_type       FLASH | COMMUNICATION | CCTV
source_sequence   Raw 自增 id，仅用于增量发现和审计
source_key        row_key_hash
source_name
fetched_at
published_at      CCTV 可空；使用 date 单独表达内容日期
content_date
title
content
url
content_hash
normalized_char_count
```

进入该对象前只允许非语义清洗：HTML/空白规范化、固定尾注剥离、时间标准化、内容哈希。不得在此阶段改写事实、摘要或重排段落。

### 6.2 目标业务表

不新增独立 PostgreSQL database，物理 schema 沿用现有数据库的 Biz `app` schema，表名前缀使用 `wealth_news_digest_`。但所有本节新表必须显式使用 HDD tablespace `gs_raw_cold_hdd`，不能继承数据库默认的 SSD `pg_default`。迁移文件和真实 `down_revision` 必须在实施日检查 Alembic head 后生成，本文不提前写死 revision。

迁移门禁：

1. 升级前检查 `gs_raw_cold_hdd` 存在；不存在立即失败，禁止自动回退 SSD。
2. 每个 `CREATE TABLE` 显式设置 `postgresql_tablespace="gs_raw_cold_hdd"`；表的 TOAST 数据随表落入该 tablespace。
3. PostgreSQL 会把索引放入数据库默认 tablespace，因此主键、唯一约束生成的索引必须在建表后显式 `ALTER INDEX ... SET TABLESPACE gs_raw_cold_hdd`，普通索引创建时显式附加 `TABLESPACE gs_raw_cold_hdd`。
4. 上线验收从 `pg_class/pg_namespace/pg_tablespace` 只读核对每一张新表、TOAST 表和索引的有效 tablespace；任一对象落到 `pg_default` 即阻断上线。
5. 若将来改为独立 database，创建时也必须指定 HDD 默认 tablespace；这不是一期推荐方案，不能与本方案的“现有 database + 新表”混为一谈。

#### `app.wealth_news_digest_policy`

保存启用状态、五个时点、时区、推送上限、Debug 上限、激活的 taxonomy/scoring/summary/model policy 版本和飞书凭据引用。业务配置只保存凭据引用，不保存明文 Webhook/secret。

#### `app.wealth_news_digest_run`

| 字段组 | 内容 |
| --- | --- |
| 身份 | `run_id/policy_id/scheduled_at/frozen_cutoff` |
| 窗口 | `display_window_start/display_window_end/timezone` |
| 版本 | taxonomy、scoring、summary、model policy 版本 |
| 状态 | DISCOVERING/ENRICHING/RANKING/READY/DELIVERING/SUCCEEDED/PARTIAL/FAILED/CANCELLED |
| 进度 | candidate/event/deep-analysis/delivery done 与 total、当前阶段、更新时间 |
| 结果 | pushed_count、debug_count、shadow_count、问题摘要 |

同一 `(policy_id, scheduled_at)` 只能有一个有效 Run；重试复用原 Run，不重复创建业务结果。

#### `app.wealth_news_digest_source_cursor`

每个 `policy_id + source_type` 一行，保存最后成功 `last_raw_id`、对应 Run、更新时间。更新游标与该来源完成标记同事务提交。影子观察使用独立 shadow cursor，不能推进固定窗口 cursor。

#### `app.wealth_news_digest_candidate`

保存本 Run 的全部新增来源记录引用，不复制完整原文：

- `run_id/source_type/source_sequence/source_key/content_hash/fetched_at/published_at/content_date`；
- `normalized_char_count/stage/exclusion_code/exclusion_detail`；
- `event_id/preliminary_score/final_score/final_rank`；
- 分类模型状态、深度分析状态、摘要状态；
- 唯一键 `(run_id, source_type, source_key)`。

候选行一期不自动删除，用于窗口完整性、漏选分析和版本回放；大体量 prompt、token 流和框架日志不进入该表。上线满 90 天只做容量、增长率和查询性能审计；任何归档、压缩或清理策略必须另行评审，不能由定时任务自行启用。

#### `app.wealth_news_digest_event` 与 `event_member`

`event` 保存跨来源事件身份、代表来源、首次/最近观察时间、事件指纹、embedding 模型版本、embedding 二进制及维度；`event_member` 保存 `(event_id, source_type, source_key)`。不假定 Prod 已安装 pgvector，一期可用固定长度 float32 bytes 持久化并由 Biz 计算余弦相似度；是否引入扩展必须另行审批。

#### `app.wealth_news_digest_analysis`

每个 `event_id + analysis_version` 一条，保存：

- 多标签分类、事件类型、影响对象和置信度；
- 七个重要度维度、档位、分数、原因和有界证据片段；
- 初排、深度复核与最终分；
- 一句话结论、要点、不确定性、摘要核验状态；
- model id/revision、prompt version、taxonomy/scoring/summary policy version；
- 输入 content hash 集合与输出 hash。

模型原始输出只允许保存经过 schema 校验、长度限制和敏感字段过滤的结构化 JSON；非法输出保存错误码，不把任意文本直接写入用户可见字段。

#### `app.wealth_news_digest_delivery`

保存 Run、目标、最终 Top 15 事件序列、payload hash、状态、尝试次数、HTTP/飞书业务结果、最近错误和发送时间。唯一约束保证同一 Run、目标和 payload hash 不重复发送。

#### `app.wealth_news_digest_public_detail`

只为正式 delivery 中的代表来源建立随机、不可枚举的 `public_id`，映射 `delivery_id/event_id/source_type/source_key` 并支持显式撤回。公开 URL 不暴露 Raw/Serving 主键、`row_key_hash` 或可推导顺序；该表不复制正文，不提供公开列表或搜索。

#### `app.wealth_news_digest_shadow_observation`

保存疑似重大事件的首次发现时间、源发布时间、识别延迟、当时各维度、触发规则、Qwen 复核、拟发送摘要、后续固定窗口排名和最终人工结论。一期没有 delivery 外键，因为影子模式不发送。

---

## 7. 有界处理管线

### 7.1 Stage A：发现与确定性清洗

1. 按三个 Raw 表的 `id` 成功水位和冻结上界分批 keyset 发现身份，默认每批 200，再以 `row_key_hash` 读取 Serving 事实；不一次把整窗长期放在内存，也不把 Raw 当成最终业务展示事实。
2. 写入全部 candidate；重复唯一键幂等跳过。
3. 空标题/正文、无法解析内容等情况不丢行，记录明确 `exclusion_code`。
4. 绝不读取 `news.score`。

### 7.2 Stage B：精确去重与 Embedding

1. 同来源 key/hash 精确去重。
2. 为有效文本生成 Qwen3 Embedding，批量处理并持久化版本和结果状态。
3. 先在本窗口聚类，再与近 72 小时活动事件比较；时间、实体和数字冲突可否决语义相似合并。
4. 误合并风险高于漏合并：低置信度时保留独立事件。

### 7.3 Stage C：全事件轻量分类与初排

每个事件代表文本先由确定性规则抽取来源类型、发布时间、机构/公司/行业/关键词和明确生效时间，再由分层候选器选择少量相关主题/事件类型交给 mDeBERTa 做零样本判断；禁止对 17 个一级主题、重点二级主题和 22 个事件类型做全量笛卡尔平铺。所有事件计算初步重要度，形成完整候选排名；分层候选召回率由 M1 人工样本验收。

### 7.4 Stage D：有限深度分析

以下事件进入 Qwen 候选池：

1. 初排前 `deep_analysis_limit` 个事件；M0-3 将 M1 回放安全上限冻结为 30，M1 可按质量与整窗性能调低，调高必须重新通过 60 分钟与不依赖 swap 门禁；
2. 命中重大政策、系统性风险、重大科技/AI 等硬触发规则的事件；
3. 最终可能进入 Top 30 且需要摘要的长文；
4. 影子观察待复核事件。

候选池按硬触发、初排和摘要必要性确定优先级后，实际 Qwen 调用总数仍不得超过 `deep_analysis_limit`；硬触发不会绕过总预算，只在预算内抢占普通候选。Qwen 不处理被明确排除、无有效文本、纯重复且无新增事实的候选。单 Run 还必须有 token、事件数和 wall-clock 总预算；预算耗尽时记录 `DEEP_ANALYSIS_BUDGET_EXHAUSTED`，不能静默扩大资源或 Full 回放。

### 7.5 Stage E：最终排序与多样性

1. 合并规则分、Embedding 用户相关度、mDeBERTa 分类、Qwen 档位与证据。
2. 先过可信度/事实完整性门禁，再计算总分；“重大但低可信”不能自动置顶。
3. 同一事件只保留一条代表项，多来源作为佐证。
4. 对类别和单一实体做多样性约束，避免 Top 15 被一个主题占满；该约束必须保留原始分和调整后排名。
5. 最终 Top 30 写入 Debug；达到最低门槛的前 15 写入 delivery。

---

## 8. 分类体系 v3、机器预标注与人工审核

### 8.1 设计依据与边界

主题骨架参考 [IPTC Media Topics](https://iptc.org/standards/media-topics/)：该体系以 17 个一级主题组织新闻文本，并继续向下形成层级主题。本文只继承其“新闻在讲什么”的主题轴和一级主题语义，不复制全部 1200 多个概念；中国资本市场、宏观政策、科技与 AI 的产品重点通过重点二级主题和第 10 节重要度体现。

经济事件标注参考 [SENTiVENT Economic Event Annotation Guidelines](https://github.com/GillesJ/sentivent-event-annotation-guidelines) 将事件类型、事件主体、事件参数和同一事件关系分开表达的原则。外部体系是设计依据，不是可直接投入中文生产的现成事实源或模型合同。

主题、行业和关注标签独立表达，原有五轴扩展如下：

| 轴 | 回答的问题 | 约束 |
| --- | --- | --- |
| 主题 | 新闻主要在讲什么 | 一个主主题；零到两个副主题 |
| 行业 | 涉及哪些经济活动领域 | 独立多选，不按用户偏好省略行业 |
| 关注标签 | 是否涉及重点研究方向 | 独立多选，必须有原文依据 |
| 事件类型 | 具体发生了什么 | 适用时一个主事件类型；零到两个关联事件类型 |
| 主体与对象 | 谁发起、谁受影响 | 可多值，必须带原文证据 |
| 地域与市场 | 在哪里、影响什么市场 | 可多值，不与主题混成同级标签 |
| 重要度 | 是否值得研究和推送 | 只由第 10 节评分决定，不反向改变分类 |

硬边界：

1. `FINANCIAL_INSTITUTION` 一类主体、`GLOBAL_MARKET` 一类地域/市场、`COMPANY_EVENT` 一类事件/对象不得再与宏观、科技等纯主题并列。
2. 一条体育新闻仍应正确归入体育；它是否低优先级由重要度判断，不能通过错误分类过滤。
3. 模型置信度不是人工真值；人工不一致先修订定义，不以微调掩盖 taxonomy 问题。
4. 同一事件聚类与主题分类是两个任务：同一主题不代表同一事件，同一事件的多来源稿件只形成一个事件簇。

### 8.2 IPTC 派生一级主题

一级主题语义映射 IPTC；下表 code 是本系统稳定别名，不冒充 IPTC 官方 QCode。每个 taxonomy 版本必须同时保存所参考的 IPTC 发布版本和对应 concept URI；中文显示名可修订，内部 code 不因文案调整而变化。

| code | 中文名 | 本方案解释 |
| --- | --- | --- |
| `DISASTER_ACCIDENT_EMERGENCY` | 灾害、事故与紧急事件 | 自然灾害、工业事故、交通事故、应急处置及造成伤亡或损失的突发事件 |
| `HUMAN_INTEREST` | 人物与人情故事 | 人物经历、纪念、仪式、奖项及不以公共政策或商业事实为中心的人情内容 |
| `POLITICS` | 政治 | 政府治理、权力运行、选举、公共政策、非暴力国际关系 |
| `EDUCATION` | 教育 | 学校、教育制度、课程、教师、学生与教育政策 |
| `CRIME_LAW_JUSTICE` | 犯罪、法律与司法 | 犯罪、执法、法院、审判和司法体系；证券监管规则优先经济金融分支 |
| `ECONOMY_BUSINESS_FINANCE` | 经济、商业与金融 | 宏观经济、公司、行业、贸易、金融机构、金融市场和商品市场 |
| `CONFLICT_WAR_PEACE` | 冲突、战争与和平 | 战争、恐怖活动、制裁、社会动荡、和平谈判等强制性冲突事件 |
| `ARTS_CULTURE_ENTERTAINMENT_MEDIA` | 艺术、文化、娱乐与媒体 | 文化艺术、影视、出版、新闻媒体、社交媒体与传播活动 |
| `LABOUR` | 劳动与就业 | 就业、工资、劳动关系、社保、工会和退休；宏观就业数据可将其作为副主题 |
| `WEATHER` | 天气 | 天气现象、预报和气象预警；已造成实际损失时可将灾害作为主主题 |
| `RELIGION` | 宗教 | 宗教组织、活动、人物、仪式及政教关系 |
| `SOCIETY` | 社会 | 人口、社区、移民、贫困、公益、家庭和社会问题 |
| `HEALTH` | 健康 | 疾病、医疗、药品、医院、公共卫生和医疗保障 |
| `ENVIRONMENT` | 环境 | 气候、污染、生态、自然资源和环境治理 |
| `LIFESTYLE_LEISURE` | 生活方式与休闲 | 旅游、餐饮、兴趣、休闲活动和个人生活方式 |
| `SCIENCE_TECHNOLOGY` | 科学与技术 | 科学研究、工程技术、数字技术和创新 |
| `SPORT` | 体育 | 体育比赛、组织、人物、设施和竞赛活动 |

不再设置语义上的 `OTHER` 主题。无法可靠分类时使用 8.7 的处理状态，避免 `OTHER` 成为模型默认答案。

### 8.3 分类体系 v3：主题、行业与重点关注标签分离

2026-10-03 根据20条教学试标和用户反馈，批准采用 v3 修订。旧 v2 的33个重点二级主题不再作为新任务的主二级主题清单；旧标注、模型结果和版本留档，不原地改写。v3审核工具及10条真实预标注已导入新版教学集，等待用户验证表单；历史140条模型回放仍为v2，不改名为新版结果。

#### 8.3.1 主题层级

保留8.2的17个一级主题。二级主题只回答“主要叙事在讲什么”，不放入具体行业、技术产品或用户关注方向。一个二级 code 只能属于一个一级；一级已能准确表达时允许只选一级。没有合适二级不等于信息不足，记录“仅一级”即可；缺项另行记录，不能强塞最近选项。

首轮只细化经济金融和科学技术，其他一级停留在一级。以下是本系统自定义的候选层级，不声称复制了 IPTC 的完整二级概念：

| 一级 | 二级 code | 中文名与边界 |
| --- | --- | --- |
| 经济、商业与金融 | `ECONOMY.ECONOMIC_CONDITIONS` | 经济运行与统计：经济总量、周期、供需和统计数据；政策措施归经济政策 |
| 经济、商业与金融 | `ECONOMY.ECONOMIC_POLICY` | 经济政策与制度：货币、财政、产业及金融监管政策；具体方向由关注标签补充 |
| 经济、商业与金融 | `ECONOMY.MARKET_ACTIVITY` | 市场交易与价格：证券、商品、外汇的交易、价格与资金流；公司业绩归公司经营 |
| 经济、商业与金融 | `ECONOMY.BUSINESS_OPERATIONS` | 公司与机构经营：业绩、订单、融资、并购、治理、生产与经营风险；不因公司行业改变主题 |
| 经济、商业与金融 | `ECONOMY.INDUSTRY_STRUCTURE` | 行业与产业链运行：行业格局、行业供需与产业链趋势；正式政策措施归经济政策 |
| 经济、商业与金融 | `ECONOMY.TRADE_RELATIONS` | 贸易与跨境商业：贸易关系、跨境供应链和商业活动；统计发布归经济运行，制裁中心归冲突 |
| 科学与技术 | `SCIENCE.RESEARCH` | 科学研究与发现：基础研究、实验和科学发现；产品与工程应用归技术开发 |
| 科学与技术 | `SCIENCE.TECHNOLOGY_DEVELOPMENT` | 技术研发与应用：技术突破、产品技术发布和工程应用；公司销售或财报归公司经营 |

一级、二级均提供中文定义、包含/排除示例。审核界面必须限制父子关系；若 Argilla 原生问题不能实现动态联动，采用带完整父路径的单一主题选择器，例如“经济金融 → 公司与机构经营”，从所选叶节点确定性导出一级与二级。选择器同时提供“经济金融（仅一级）”等父级停留项，不允许两个独立下拉框拼出错误父子关系。技术可行性通过10条演示验证，不承诺尚未核验的动态组件能力。

#### 8.3.2 独立行业轴

行业回答“涉及哪个经济活动领域”，与主题、事件类型和关注标签独立，可多选。所有行业使用同一版本化骨架，不能只为房地产单列行业却遗漏汽车、消费或农业。行业可为空；跨行业、无具体行业和无法判断必须分别表达，不能混入行业 code。

M1 行业骨架先完整覆盖以下产品级领域：农业与食品、采掘与资源、能源与公用事业、基础化工、材料、工业与装备、汽车与交通设备、电子与半导体、信息技术与通信、消费品与零售、医药与医疗、金融、房地产与建筑、运输与物流、文化传媒与娱乐、教育与专业服务、旅游餐饮与生活服务。每个领域配置定义、包含/排除项和常见行业名映射；“航空航天”“汽车”“半导体”等细分名称可以作为原文实体保留。无法映射时记录缺项，不静默归入兜底类别。

这是一套用于新闻审核的产品领域候选表，不冒充官方证券行业标准，也不负责证券代码匹配。版本冻结前必须用真实样本检验覆盖及交叉边界；如后续用于正式证券行业分析，再单独确定外部标准及映射合同。

#### 8.3.3 独立重点关注标签

关注标签回答“是否涉及重点研究方向”，可多选，不承担主题父子关系。初始标签为：宏观经济、货币政策、财政政策、资本市场监管、金融市场、人工智能、半导体、算力与通信、软件与网络安全、机器人、新能源技术、生物医疗科技、航空航天、重大公司风险、国际贸易与制裁。

每个标签必须有原文依据；命中关注标签不能反向强制改变主主题或自动提高重要度。旧 v2 二级 code 到新主题/行业/关注标签的映射只能形成迁移建议，不能当作人工已接受的新标注。

### 8.4 主主题与交叉边界

主主题按标题和正文的主要叙事中心判断，一个主主题、零到两个副主题。副主题也使用带父路径的主题选项，不混入行业或关注标签，不重复主主题及其祖先/子节点。新闻涉及多个方向时，优先使用独立轴表达，不为扩大覆盖机械增加副主题。

| 新闻场景 | 主主题 | 行业或关注标签 | 事件类型 |
| --- | --- | --- | --- |
| 芯片公司公布财报 | 经济金融 → 公司与机构经营 | 电子与半导体；半导体 | 财报与业绩指引 |
| 央行宣布降准 | 经济金融 → 经济政策与制度 | 货币政策 | 政策调整与执行 |
| AI模型技术发布 | 科学技术 → 技术研发与应用 | 信息技术与通信；人工智能 | 产品与技术发布 |
| 汽车行业供需变化 | 经济金融 → 行业与产业链运行 | 汽车与交通设备 | 根据正文判断，不能仅由行业决定 |
| AI芯片出口制裁 | 冲突、战争与和平（仅一级） | 电子与半导体；半导体、国际贸易与制裁 | 制裁与贸易管制 |
| 创新药关键试验结果 | 健康（仅一级）或科学技术 → 科学研究与发现，由叙事中心裁决 | 医药与医疗；生物医疗科技 | 根据正文判断 |

行业、主题和事件类型都不能仅凭标题中的公司或产品名称裁决。机器建议必须能回指正文；证据不足时允许人工选择无法判断。
### 8.5 金融新闻事件类型

事件类型与主题正交。事件 ontology 适用时，每个事件簇保存一个 `primary_event_type`，只有正文中存在独立且相关的次要事件时才允许最多两个 `related_event_types`。对体育、生活方式等主题中不属于一期事件 ontology 的有效新闻，使用 `event_type_status=NOT_APPLICABLE`，不能误记为 `UNRESOLVED`，也不能强塞进最相近的金融事件类型。

`event_type_status` 只允许 `CLASSIFIED/NOT_APPLICABLE/UNRESOLVED`：前者必须有主事件类型，中者必须没有事件类型，后者表示按内容本应存在事件类型但证据不足。

| code | 中文名 | 典型内容 |
| --- | --- | --- |
| `POLICY_RELEASE` | 政策发布 | 新政策、规划、指导意见首次发布 |
| `POLICY_ADJUSTMENT` | 政策调整与执行 | 降准、降息、税率调整、补贴落地、政策延期或退出 |
| `LAW_REGULATION_RELEASE` | 法律与监管规则 | 法律法规、交易所规则、监管制度发布或修订 |
| `MACRO_DATA_RELEASE` | 宏观与行业数据 | GDP、CPI、PMI、就业、贸易及权威行业数据发布 |
| `EARNINGS_GUIDANCE` | 财报与业绩指引 | 定期报告、业绩预告、盈利修正 |
| `CORPORATE_FINANCE` | 公司融资与股东回报 | 增发、发债、回购、分红、增减持 |
| `MERGER_ACQUISITION_RESTRUCTURING` | 并购与重组 | 收购、合并、资产出售、重大资产重组 |
| `CONTRACT_PROJECT_INVESTMENT` | 订单、项目与投资 | 重大合同、资本开支、项目开工和对外投资 |
| `PRODUCTION_OPERATION_CHANGE` | 生产经营变化 | 扩产、减产、停产、涨价、供应中断和经营调整 |
| `GOVERNANCE_PERSONNEL_CHANGE` | 治理与人事变化 | 控制权、董事高管、组织架构和公司治理变化 |
| `INVESTIGATION_PENALTY_LITIGATION` | 调查、处罚与诉讼 | 监管调查、行政处罚、司法诉讼和仲裁 |
| `DEFAULT_DISTRESS` | 违约与财务困境 | 债务违约、流动性危机、破产重整和退市风险 |
| `MARKET_PRICE_MOVE` | 市场价格异动 | 指数、证券、商品、汇率的显著价格变化 |
| `CAPITAL_FLOW_CHANGE` | 资金流变化 | 跨境资金、机构资金、融资余额和申赎显著变化 |
| `PRODUCT_TECH_RELEASE` | 产品与技术发布 | 产品发布、模型发布、技术突破和研发里程碑 |
| `ACCIDENT_DISASTER` | 事故与灾害 | 工业事故、自然灾害、公共安全和公共卫生突发事件 |
| `DIPLOMATIC_ACTION` | 外交行动 | 建交、断交、召回使节、谈判和正式外交表态 |
| `SANCTION_TRADE_CONTROL` | 制裁与贸易管制 | 经济制裁、出口管制、实体清单和反制措施 |
| `ARMED_CONFLICT_CHANGE` | 武装冲突变化 | 军事行动、冲突升级或降级、停火和撤军 |
| `SPEECH_STATEMENT` | 讲话与正式表态 | 机构或关键人物的正式讲话、答记者问和声明 |
| `FORECAST_OPINION` | 预测与观点 | 研究判断、机构预测、评论和非事实性分析 |
| `RUMOR_UNCONFIRMED` | 传闻与未确认信息 | 尚无可靠一手来源确认的市场传闻 |

一篇新闻只是“公司公告”不是事件类型；必须继续判断公告是在披露业绩、融资、并购、订单、处罚还是其他具体事实。

### 8.6 主体、地域、市场与影响对象

结构化分类至少包含：

| 字段 | 含义 | 示例 |
| --- | --- | --- |
| `actors` | 发起或直接发生事件的主体 | 国务院、人民银行、证监会、上市公司 |
| `affected_entities` | 直接受到影响的公司、机构或组织 | 某上市公司、银行、供应商 |
| `industries` | 涉及行业和产业链 | 半导体、银行、房地产、医药 |
| `instruments` | 涉及资产或金融工具 | 股票、债券、基金、期货、外汇 |
| `regions` | 涉及国家和地区 | 中国内地、中国香港、美国、欧洲、全球 |
| `markets` | 涉及交易市场 | A 股、港股、美股、债券、商品、外汇 |
| `impact_scope` | 影响范围 | 全国/系统性、跨市场、全市场、多行业、单行业、单公司、局部、不明 |

主体和影响对象必须来自原文、确定性映射或可回查证据；模型不能仅根据常识补出未出现的公司、行业或市场。行业映射和证券代码匹配属于后续独立合同，不在 taxonomy 中硬编码股票推荐。

### 8.7 无法分类与异常内容状态

以下值属于 `classification_status`，不是主题：

| code | 使用条件 | 后续处理 |
| --- | --- | --- |
| `CLASSIFIED` | 主主题可可靠判断，事件类型已分类或明确为不适用 | 进入正常评分 |
| `UNRESOLVED` | 信息不足，无法选择可靠主主题，或应有事件类型但无法判断 | 留在 Debug，不正式推送 |
| `AMBIGUOUS` | 两个以上叙事中心同等突出，现有规则无法裁决 | 人工复核并记录分歧原因 |
| `NOT_NEWS` | 广告、导航、空泛宣传等非新闻内容 | 排除并留档 |
| `MIXED_CONTENT` | 单条记录拼接多条互不相关新闻 | 不强行分类；进入清洗/拆分问题队列 |
| `INVALID_CONTENT` | 空正文、乱码、解析失败或内容不可用 | 排除并记录原因 |

标注者可以选择“分类体系没有合适答案”并填写备注；它先记为 `UNRESOLVED`，不能在标注过程中临时创建新 code。

### 8.8 机器预标注与人工审核合同

采用本机私有 Argilla。机器先给建议和证据，人工以“接受、修改、无法判断”审核；不再要求逐条从零填写21个字段。机器建议是待审答案，未审核不能标记为 gold label。

辅助审核任务只保留以下核心操作：

1. 阅读标题、正文、来源及时间，并查看机器建议和原文证据。
2. 接受整条建议，或只修改有问题的内容状态、主题、行业、关注标签、事件类型和重要度。
3. 无法判断时选择原因：原文不足、候选缺项、定义冲突、机器输出无效；候选缺项不能伪装成原文不足。
4. 备注默认可选；选择候选缺项或定义冲突时，填写简短原因，避免再次把所有解释工作交给审核者。

右侧问题通过Argilla原生Suggestions预填已有机器答案，左侧证据文字保留；不创建人工response，也不预填“审核动作”。空多选和没有答案的主主题/事件类型保持未选，不能补造标签。人工接受可提交未改动的完整预填值；修改时仅记录与机器答案真正不同的字段。已有人工草稿或已提交记录不自动更新建议；独立盲标仍完全无建议。预填用于单条Focus审核，Argilla批量视图不显示这类Suggestions，见[官方审核指南](https://docs.argilla.io/latest/how_to_guides/annotate/#suggestions)。

主体、受影响对象、地域、市场和影响范围默认作为机器提取结果展示，可展开纠正，不设为每条人工必填题。重要度提供档位和依据，允许无法判断。没有完整窗口候选时不询问 Top15；没有候选对照时不出现同事件问题；没有生成摘要时不出现摘要核验问题。聚类、摘要和窗口排名使用独立审核任务，并展示所需参考材料。

模型分工：确定性清洗与提取优先，Embedding 提供疑似同事件候选，规则缩小候选后由 mDeBERTa 给出分类建议，Qwen 只用于预算内的疑难分析和长文摘要。每批最多30个事件进入 Qwen，模型阶段串行；失败或超时必须可见，不把机器失败变成人工默认接受的答案。规则提取结果必须标记为规则来源，不能伪称模型结果。

导出区分原始机器建议、原始人工提交和最终审核结果，至少包含：

- 身份与版本：`sample_id/input_hash/taxonomy_version/industry_version/interest_version/scoring_version/summary_version/annotation_schema_version`。
- 机器建议：`prediction_id/model_revision/prompt_version/suggested_values/evidence/preannotation_status`。
- 人工审核：`reviewer_id/annotation_round/review_action/changed_fields/final_values/issue_reason/note/submitted_at`。
- 评估分组：`evaluation_role` 为 `TUTORIAL/ASSISTED_CALIBRATION/BLIND_VALIDATION/BLIND_REPEAT`，并记录是否已看过机器建议。

接受动作必须固定当时的 prediction 版本；修改动作保留前后差异；无法判断不生成已接受答案。正文变化产生新 input_hash，版本变化创建新任务，不覆盖旧标注。Argilla 仅为临时工作台，正式导出按 manifest 和 SHA-256 冻结在 Prod HDD，不直接写生产业务表。

审核任务优先展示不确定、规则冲突、重点方向和缺项样本，同时保留随机检查样本，防止只审查机器自己识别的困难项。模型置信度未校准前只作为队列排序信息，不能替代质量门禁或自动免审。

### 8.9 两阶段校准流程

#### 8.9.1 第一阶段：10条演示与 taxonomy 试审

1. 已完成的20条 v2 教学标注保留为历史证据。旧120条盲标集暂停，不要求继续旧表单。
2. 从教学集选择10条覆盖不同来源和争议边界的新闻，创建 v3 演示任务，机器预标注后人工审核。该批不计入独立准确率。
3. 演示必须核验：主题父子关系、行业覆盖、选项定义、原文证据、接受/修改/无法判断操作，以及缺少参考材料的问题确实不出现。
4. 记录每条审核耗时、修改字段数、缺项与无法判断原因；通过实际体验确认工作量下降后，再扩展到120条试审。不能仅以成功导入证明流程可用。
5. 试审以机器辅助为主，保留少量独立盲标；来源分层和随机顺序写入 manifest。已看过建议的样本不得重新标为未受提示的盲标。
6. 用户审查争议与定义修订后，从试审样本抽30条，间隔至少72小时，以隐藏建议和首次答案的简化表单盲复标。它衡量单人自一致性，并不消除第一次看过建议造成的影响；报告必须明确这一局限。未完成此门禁不得冻结 taxonomy 或生成800条正式任务。

#### 8.9.2 第二阶段：800条校准与独立验收

正式样本仍为800条：news 320、major_news 320、cctv_news 160；原70%分层随机、30%重点过采样口径保留，记录抽样概率，排除教学与试审样本。

在任何调参前冻结分组：

- 600条辅助校准：news 240、major_news 240、cctv_news 120。显示机器建议，由人工接受或纠正，可用于候选规则、模板和阈值调整。
- 200条独立验收：news 80、major_news 80、cctv_news 40。从未显示机器建议，先用简化表单填写内容状态、主题、关注标签及事件类型；人工答案冻结后才揭示机器结果。这是正式分类门禁的数据来源，不能用于同一版本调参。

两个分组均保留70%随机/30%重点抽样及权重记录；关联事件的稿件必须按事件组分配，不能把近重复稿分到校准和验收两边。实际 gold label 覆盖不足时报告每标签样本数，不以少数样本的高召回率宣称准入；需要增加证据时提交扩充建议。

聚类使用疑似同事件对和困难负例的专门任务；摘要审核展示原文与摘要；排名审核展示完整窗口候选和排名。当前主题试审不能兼作这三项验收证据。

辅助审核修改率、接受率和耗时单列为运营指标，不称为模型独立准确率。独立集一旦用于挑选规则、模板或阈值，就转为校准数据；后续验收须补充未参与调参的新样本。800条是初始冻结规模，不保证无需追加样本就能通过所有门禁。

taxonomy、行业、关注标签或表单变更均发布新版本；历史结果保留，不用旧二级答案自动充当新轴的人工真值。
### 8.10 一致性与分类验收

人工一致性使用 Krippendorff's Alpha 或等价的可复现指标，并同时输出原始一致率和分歧样本：

- `< 0.667`：定义不可用，阻断模型验收并返工 taxonomy；
- `0.667–0.80`：基本可用，但必须处理高频混淆后才能冻结；
- `>= 0.80`：作为重点轴的目标，不代表模型已经达标。

模型分类验收要求：

1. 主一级主题、适用的主二级主题、行业、关注标签和主事件类型分别输出 Precision/Recall/F1、Macro-F1、Micro-F1；不能混成一个总分。正式门禁仅使用8.9.2中预先冻结的独立验收集；辅助审核结果另列诊断指标。
2. 单列宏观经济、货币政策、资本市场制度与监管、人工智能、半导体、制裁与反制的召回率和混淆样本。
3. 统计 `UNRESOLVED/AMBIGUOUS/MIXED_CONTENT` 占比、平均副主题数、常见共现、混淆矩阵和 taxonomy 缺项原因；这些比例先由第一阶段形成基线，不预设无证据常量。
4. 分快讯/通讯/新闻联播、短/长文本、主主题/副主题分别报告；不能以长文总体表现掩盖一句话快讯错误。
5. 一期建议门槛保持为核心重点标签 Recall 不低于 0.85、主主题整体 Macro-F1 不低于 0.75；主事件类型门槛由第一阶段人工一致性和第二阶段真实基线回写。
6. 阈值若被真实基线证明不合理，必须回到本文说明数据、错误类型和调整原因，不能为通过门禁只改统计口径。

---

## 9. 摘要规则与事实门禁

长度按去 HTML、空白和固定尾注后的中文字符数计算：

| 长度 | 规则 |
| --- | --- |
| `< 800` | 不生成式摘要，使用原始精简文本或确定性抽取句 |
| `>= 800` | 进入摘要资格；仅对通过事件选择和深分析预算的候选生成一句话结论和 2–3 个要点 |
| `> 12000` | 分块抽取事实，再对事实集合二次汇总；禁止直接截断后假装覆盖全文 |

即使达到 800 字，正文只有一个完整句子也不摘要。快讯默认不摘要；通讯和新闻联播是主要摘要对象。M0 六天样本中，`news` 仅 48/27,566 条达到 800 字，`major_news` 有 9,764/9,889 条达到 800 字，因此该默认值能把短快讯排除在生成模型之外；后续调整必须发布新 summary policy 版本。

结构化输出至少包含：`one_sentence/facts/impact/uncertainties/entities/evidence`。数字、比例、日期、公司、机构和政策名必须回查原文；mDeBERTa 对摘要句做 NLI 支持度核验。任何一句不通过时整条摘要不能直接推送：先重试一次约束式生成，仍失败则降级为抽取式要点或原文，不允许编造补全。

新闻正文视为不可信数据，模型 Prompt 必须明确忽略其中的指令；模型不获得网络、数据库写入、文件、命令或飞书工具权限。

---

## 10. 重要度计算

模型不直接自由给 0–100 分。它只选择有锚点的档位并返回证据，程序映射为分数。

| 维度 | 上限 | 判断来源 | 档位示例 |
| --- | ---: | --- | --- |
| 潜在影响程度 | 30 | 事件类型、政策层级、Qwen 证据 | 30 国家级/系统性；20 重要市场或行业；10 局部；0 无明确影响 |
| 影响范围 | 15 | 实体和影响对象规则 | 15 全国/全市场；10 重要行业；5 单公司；0 不明 |
| 时效与紧迫性 | 15 | 日期/生效时间抽取 | 15 已发生或 24h；10 七日；5 中长期/不明；0 纯历史 |
| 用户相关度 | 15 | Embedding 与关注画像 | 中国资本市场为基线；宏观、科技、AI 提权；用户配置可动态调整 |
| 新颖性 | 10 | 当前/近 72h 事件簇差异 | 10 新事件；6 重大新进展；2 补充；0 无新增 |
| 多来源佐证 | 10 | 独立来源成员 | 10 多个独立可信源；6 两个；3 单一权威源；0 单一不明源 |
| 来源可信度 | 5 | 版本化来源等级 | 5 官方一手；4 权威媒体；2–3 专业媒体；0–1 不明 |

### 10.1 硬门禁

1. 无有效原文、时间不可解释或结构化输出失败，不进入正式 Top 15。
2. 低可信度重大传闻可进入 Debug/Shadow，但不能自动排到正式第一档。
3. 摘要事实核验失败时只能使用降级文本。
4. 同一事件重复稿件不能通过来源数量重复加分。
5. 评分结果保存每维 `bucket/score/reason/evidence`，不得只存总分。

### 10.2 排名评估

人工在冻结历史窗口评审：是否应进 Top 15、相对顺序是否合理、是否遗漏关键事件。主要指标使用 Precision@15、Recall@30、NDCG@15、重点事件漏报数和重复事件率；不把模型自评分当作验收答案。

---

## 11. 模型方案与降级

### 11.1 一期模型

| 模型 | 固定职责 | 不负责 |
| --- | --- | --- |
| `Qwen/Qwen3-Embedding-0.6B`，revision `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3` | Embedding、相似度、事件聚类、关注度 | 生成摘要或直接决定总分 |
| `MoritzLaurer/mDeBERTa-v3-base-mnli-xnli`，revision `8adb042d524ecd5c26d3e3ba0e3fbcf7e2d0864c`，原仓库量化 ONNX | 零样本多标签分类、摘要句 NLI 核验 | 长文生成 |
| `Qwen/Qwen3-4B-GGUF`，revision `bc640142c66e1fdd12af0bd68f40445458f3869b`，官方 `Q4_K_M` | CPU benchmark 候选；有界深度事实抽取、档位判断、长文摘要、影子复核 | 未通过 M1 前不得视为最终一期生成模型；不得对全候选无边界推理 |

精确文件、大小、SHA-256、许可证和准入状态见 [M0 只读测量报告 §6.1](/Users/congming/github/goldenshare/docs/architecture/news-intelligence-digest-feishu-m0-readonly-validation-2026-09-24.md)。`Qwen/Qwen3-4B-Instruct-2507` 官方仓库没有 4-bit GGUF，约 8.0 GB 的 BF16 权重只保留为语义质量参考，不列入首轮 Prod 下载清单；社区转换的 GGUF 未经独立溯源与质量验证不得准入。官方 `Qwen3-4B-GGUF` 来自原始 `Qwen3-4B` 而非 `Instruct-2507`，因此它只冻结为 CPU benchmark 候选，M1 不通过则停止准入，不能把这次候选冻结解释为自动换模。

一期不启用 Reranker；只有固定模型组合在历史集上的 Top 15 排名不足，才评估 `Qwen3-Reranker-0.6B` 或 `bge-reranker-v2-m3`。模型 revision 必须锁定，不能用浮动 `main` 作为可复现生产版本。

### 11.2 不做微调

一期不训练模型权重。优先通过 taxonomy 定义、正反例、Prompt、规则、阈值和人工评测校准。未来积累足够人工反馈后，可以在冻结 Embedding 上训练逻辑回归、LightGBM 或轻量排序器；它不是一期依赖，也不能未经新方案自动上线。

### 11.3 Prod 资源事实与门禁

2026-09-21 只读核验的当前 Prod：8 vCPU Intel Xeon Platinum 8255C、15 GiB 内存、约 9.4 GiB available、约 9.9 GiB swap、无 `nvidia-smi`/NVIDIA GPU。该快照部署前必须重查，不能视为永久规格。

因此：

1. 模型 Worker 与 Web/Ops Worker 分进程，单并发起步；
2. 三个模型分阶段使用，禁止默认全部常驻造成内存竞争；
3. M0-3 已证明冻结的官方 `Q4_K_M` CPU 制品可在有限上下文运行；只有 M1 业务质量与整窗资源门禁同时通过才能进入一期模型策略；
4. 候选批次、深度分析数、token 和总运行时间均有硬上限；
5. 不允许依赖 swap 完成正常窗口，不得使现有 Web/Ops 服务出现可测退化；
6. M0-3 已按管理员授权完成 HDD 隔离安装；任何新增/升级依赖、变更模型 revision 或部署常驻服务仍须另行评审；
7. 若代表性最大窗口不能在 60 分钟内完成，或最短 2 小时间隔没有充足余量，停止 Prod 启用并收缩模型/范围，不能靠增加并发硬顶。

M0-2 冻结的专用 HDD 根目录 `/data/disk/goldenshare/news-intelligence`、Python 3.13 独立 venv、44 个带哈希 CPU wheel、llama.cpp b11146、模型白名单文件及 4,400,018,597 bytes 下载清单，已在 M0-3 按原合同安装和复核；详细证据见 [M0 报告 §6.2–§6.3](/Users/congming/github/goldenshare/docs/architecture/news-intelligence-digest-feishu-m0-readonly-validation-2026-09-24.md)。项目 `.venv` 未修改，模型缓存/venv/tmp 未写入 SSD，也未源码构建或安装 CUDA/ROCm 包。

M0-3 冻结的 M1 安全上限为：Embedding `batch=1/max_tokens=512`；mDeBERTa `batch=16/max_tokens=512`；Qwen `threads=4/parallel=1/ctx=2048/deep_analysis_limit=30`。三模型只允许单实例、按阶段串行驻留，进程入口为独立 App-owned 模型 Worker；Qwen 只允许 loopback llama-server，并必须做 singleton 断言与进程组级超时/取消清理。当前没有部署该 Worker 或创建 systemd 配置。

上述单模型基准不等于端到端性能通过。以 790 个规范化标题组保守估算，128-token Embedding、39 个平铺 NLI 假设和 30 个 1,400 字 Qwen 调用合计约 84.7 分钟，超过 60 分钟。因此 M1 必须通过确定性过滤、精确去重、短代表文本与分层标签候选缩小模型入口，并以真实旧日期窗口重新验收；禁止全量平铺 39 个标签，也禁止把 7,827 条触达上界直接交给模型。

降级顺序：Qwen 失败时保留轻量初排和原文，不生成式摘要；mDeBERTa 失败时不把 Qwen 单方分类伪装成双模型一致；Embedding 失败时禁止语义合并，宁可保留独立事件。降级必须在 Debug 和飞书中可见。

---

## 12. Debug 模式

### 12.1 页面/API 最小能力

运营 Debug 明确落在现有 `frontend/`“财势乾坤数据运营管理综合平台”，导航归属为“审查中心 → 新闻智能”，建议路由 `/ops/v21/review/news-intelligence`；不放入任务中心，不复用 Wealth Shell，移动端不提供 Debug 功能。

1. 按 Run 选择 08/12/16/20/22 窗口；显示计划时间、冻结截止、实际耗时、模型/规则版本。
2. 默认显示最终 Top 30，可切换“全部候选”。
3. 支持按来源、分类、事件类型、处理阶段、排除原因、是否摘要、是否 Shadow 过滤。
4. 单事件展开显示：成员来源、代表项、分类置信度、七维评分、证据、摘要核验、初排与最终排名变化。
5. 显示 Top 15 实际 payload 和发送结果；未发送时明确原因。
6. 不向普通用户暴露 prompt、secret、内部异常堆栈或未经处理的模型原始文本。
7. 提供最小人工反馈：分类错误、重要度不合理、错误聚类、摘要事实错误、应/不应进入 Top 15 和可选备注；反馈只进入后续校准集，不实时覆盖已冻结 Run 或已发送 payload。

Debug 页面是运营能力，后端事实仍在 Biz；前端不重新计算分类或分数。首轮可先交付只读 API 与结构化导出，再交付页面，但“能够人工审查 Top 30 和全部候选”是正式推送前门禁。

### 12.2 reason code

至少包括：`EMPTY_CONTENT/EXACT_DUPLICATE/SEMANTIC_DUPLICATE_NO_DELTA/EMBEDDING_FAILED/CLASSIFICATION_LOW_CONFIDENCE/DEEP_ANALYSIS_NOT_SELECTED/DEEP_ANALYSIS_BUDGET_EXHAUSTED/SUMMARY_NOT_REQUIRED/SUMMARY_VERIFICATION_FAILED/LOW_IMPORTANCE/LOW_CREDIBILITY/DIVERSITY_DEMOTED/DELIVERY_LIMIT`。禁止仅用自由文本解释候选消失。

---

## 13. 重大新闻影子观察

固定窗口之外，App 影子 Worker 建议每 5 分钟使用独立 shadow Raw-id cursor 读取新身份，只运行低成本发现/初排；命中硬规则或高初分时才调用 Qwen 复核。上游新闻当前是否能在 5 分钟内入库需单独做只读时延审计，源数据更慢时不得宣称 5 分钟发现能力。

一期 `delivery_mode=SHADOW_ONLY`，任何路径都不得调用飞书即时发送。保存 `would_send=true`、拟 payload 和发现延迟，用历史/实时观察评估：触发次数、误报、漏报、比固定窗口提前多久、后续固定窗口排名。只有独立批准后才能新增即时 delivery 状态。

影子观察不得推进五个固定窗口的 source cursor；两者按相同来源身份幂等共享分析结果，但保持各自观察/推送语义。

---

## 14. 飞书投递

### 14.1 内容

标题包含时段和事件数，正文按最终顺序列出最多 15 个事件。每项包含：优先级、主题、标题、一句话结论/原文精简句、重要原因、主要影响对象、多来源标记和原文链接。失败降级或低置信度必须明确标记，不能装作正常摘要。

一期使用自定义机器人的 `post` 富文本消息，在每一项末尾增加 `a` 标签“查看详情”。当前仓库的 Ops 通知已使用 `msg_type=post`，本能力只借鉴载荷形式，仍使用独立 Biz delivery contract 与 App transport。建议结构如下，最终字段和长度必须在飞书测试群按[飞书自定义机器人官方文档](https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot)实测冻结：

```json
{
  "msg_type": "post",
  "content": {
    "post": {
      "zh_cn": {
        "title": "新闻简报｜12:00–16:00｜15 条",
        "content": [
          [
            {"tag": "text", "text": "1. 【高｜宏观政策】…… "},
            {"tag": "a", "text": "查看详情", "href": "https://<wealth-origin>/wealth/market/news/detail/<public-id>"}
          ]
        ]
      }
    }
  }
}
```

不优先使用“每条一个按钮”的交互卡片：15 条事件会产生较重的卡片结构，也没有业务回调需求。普通 URL 跳转不需要卡片回调服务；以后若要做“收藏、反馈分类、标记重要”等交互动作，再单独评估交互卡片、回调鉴权与事件幂等。飞书开放平台[官方 Node SDK](https://github.com/larksuite/node-sdk/blob/main/docs/channel.zh.md#%E5%8F%91%E9%80%81%E6%B6%88%E6%81%AF)同时列出 `post` 和 `card` 发送类型，M4 仍必须以测试群确认自定义机器人、客户端版本、链接点击和移动端表现。

### 14.2 详情链接与内容类型

推荐链路是“飞书 HTTPS 链接 → 免登录 Wealth 响应式详情页 → 字段最小化的公开 JSON API → 安全渲染”，不是“飞书点击后直接返回 HTML 数据”：

1. 链接地址由现有部署项 `WEALTH_PUBLIC_BASE_URL` 加固定站内路由构造，例如 `/wealth/market/news/detail/{public_id}`；禁止从请求 Host、CORS 或 Webhook 内容推断公网 origin。
2. `public_id` 使用随机、不可枚举的公开标识映射到一个已进入正式 delivery 的来源记录；URL 不暴露 `source_type`、Raw/Serving 主键、`row_key_hash`、正文、Prompt、用户信息或任意回跳地址。
3. 不移除或放宽现有 `/api/v1/wealth/market/news/items/{content_source}/{news_id}` 的 `require_quote_access`。另建只读 Public News Detail API，仅允许按有效 `public_id` 返回公开 DTO。
4. 公开 DTO 只包含标题、来源、发布时间/内容日期、系统保存的原始正文以及经过安全检查的原始来源 URL；禁止返回候选阶段、分类、评分、排名、摘要内部证据、模型/Prompt 版本、reason code、Run/Delivery ID 和数据库身份。
5. 浏览器收到正常的 `text/html` Wealth 页面；页面内部调用公开 API，API 返回 `application/json` 的互斥 `URL/HTML/TEXT` 内容合同。
6. `HTML` 由现有 sanitizer 清洗后渲染，`TEXT` 使用纯文本文章视图，`URL` 仅对通过协议和域名安全检查的外部来源展示；不得把数据库中的 HTML 作为 HTTP 响应直接裸返。
7. 当前 reader 只支持 `news/major_news`，实施时必须扩展 `cctv_news` 查询和安全解析；三种来源均通过同一公开详情页，不为飞书另建原文副本。
8. 公开页不要求登录，因而链接被转发后持有链接者也能访问；响应必须增加禁止搜索引擎收录/归档、严格 CSP、危险协议拒绝、速率限制和统一 404，且不提供公开列表、搜索、相邻记录或可枚举 ID 接口。
9. 原始外部 URL 只作为详情页里的次级“打开原始来源”动作；详情深链本身始终指向站内。若系统保存了正文，则外链失效仍展示保存正文；若源记录只有 URL 而没有正文快照，只能展示已保存元数据和“外部原文不可用”，不得声称本地保有原文。
10. 源记录不存在、撤回、超大或内容不合法时显示相同的稳定错误页，不泄露标识是否曾存在、SQL、路径、原始 HTML 或内部异常。

### 14.3 可靠性

1. Biz 生成不可变 delivery payload 和 hash；App transport 只负责签名与发送。
2. HTTP 2xx 后仍检查飞书业务 code；设置连接/响应超时。
3. 同一 payload 幂等，指数退避有上限；人工重试复用原 payload，不因重试重跑模型。
4. 飞书失败不回滚业务分析；成功响应不等于用户阅读。
5. Webhook URL/secret 只放远程 env 或受控凭据存储，日志和 Debug API 均脱敏。
6. 三个来源中任一来源发现失败、冻结范围未完整读取、排名未完成或 delivery payload 校验失败时，整次不发送；不能用剩余来源拼出一份看似完整的简报。
7. 单个事件只有生成式摘要失败、但原文有效且通过事实/可信度门禁时，可降级为原文精简句并明确标记；其他事件不因此被回滚。

新闻简报使用专用机器人/Webhook 和独立凭据引用，不复用 Ops 任务通知机器人的目标与密钥。复用现有签名/传输实现前必须先做引用审计；可抽取纯低层 client 的前提是同步迁移现有消费者且不改变 Ops 通知行为。若不满足，则在 App 新建专用 adapter，禁止让 Biz 导入 Ops 服务。

---

## 15. 配置审计

以下是目标配置合同；实施前必须确定最终命名和消费者，不允许散落常量。

| 配置 | 默认 | 来源/持久化 | 作用域 | 消费者 | 依赖/生效 | 可见性与测试 |
| --- | --- | --- | --- | --- | --- | --- |
| schedule times | 08,12,16,20,22 | policy DB | 单策略 | App scheduler | 新 Run 生效 | Debug 展示；时区/DST测试 |
| timezone | Asia/Shanghai | policy DB | 单策略 | scheduler/window builder | 与时点绑定 | 不允许无时区 datetime |
| delivery max | 15 | policy DB | 单策略 | rank/delivery | 新 Run 生效 | 上限/不足不补齐测试 |
| debug top n | 30 | policy DB | 单策略 | Debug query | 新查询生效 | 必须 >= delivery max |
| taxonomy version | news-taxonomy-v3（M1候选后缀见LLD） | M1离线策略；未来versioned policy DB | 样本/Run冻结 | 审核/classifier/debug | 新任务生效，不改旧标注 | 父路径、版本冲突与回放测试 |
| industry / interest version | news-industry-v1 / news-interest-v1（M1候选后缀见LLD） | M1离线策略；未来versioned policy DB | 样本/Run冻结 | 审核/分类/关注匹配 | 与taxonomy独立，不作为主主题 | 空值/跨行业/未知及边界测试 |
| scoring version | news-score-v1 | versioned policy DB | Run 冻结 | scorer/ranker | 依赖 taxonomy/source trust | 七维和总分测试 |
| summary version | news-summary-v1 | versioned policy DB | Run 冻结 | summarizer/verifier | 含 800/12000 阈值 | 边界与失败降级测试 |
| user interests | 中国资本市场基线；宏观/科技/AI 提权 | policy DB | owner/policy | relevance scorer | 动态更新只影响新 Run | Debug 显示权重 |
| source trust version | source-trust-v1 | versioned policy DB | Run 冻结 | credibility gate | 来源名单变化建新版本 | 未知来源负向测试 |
| deep analysis limit | M1 安全上限 30 | model policy DB | Run | Qwen selector | M0-3 冻结；M1 可调低，调高须重过性能门禁 | 预算耗尽 reason code |
| raw discovery batch size | 500 | Settings/模型策略 | Worker | reader | M0 冻结；与短事务/续跑相关 | keyset/退出续跑测试 |
| model batch size | Embedding 1；mDeBERTa 16；Qwen parallel 1 | deployment Settings | Worker | adapters | M0-3 安全上限；与模型/RSS/CPU预算相关 | 超限与降批测试 |
| model ids/revisions | 三个锁定 revision | model policy DB + deployment config | Worker | adapters | 发布模型版本后新 Run | 启动自检/版本回显 |
| model resource budget | 4 threads；Embedding/mDeBERTa 512 tokens；Qwen ctx 2048；单模型串行 | deployment Settings | 进程 | Worker | M0-3 只冻结 M1 上限；Prod 值由 M1 端到端报告准入 | 超限中止、singleton、进程组清理与进度测试 |
| shadow interval | 5 分钟建议值 | policy DB | shadow | shadow scheduler | 依赖上游时延 | 不发送负向测试 |
| shadow delivery mode | SHADOW_ONLY | policy DB，首期不可改为发送 | shadow | App transport gate | 修改需新批准 | 飞书零调用测试 |
| Feishu credential ref | 无，由用户在实施阶段提供专用机器人地址与密钥 | remote env/受控凭据 | news digest target | App transport | 不复用 Ops 通知凭据；通过正式脚本管理 | 脱敏/缺失/串用负向测试 |
| detail public origin | 复用 `WEALTH_PUBLIC_BASE_URL`，默认空 | deployment Settings/env | Prod 部署 | App payload builder | 只接受 HTTPS origin；重启生效 | 空值/非法 origin 阻断正式投递；日志不输出值 |

用户兴趣、时点、显示数量可动态调整；taxonomy、scoring、summary、source trust、model policy 必须创建新版本并冻结到 Run。模型阈值、批量和资源参数由历史回放与 Prod 基准决定，不要求用户凭偏好指定。

---

## 16. 事务、续跑、取消与观测

1. 执行 unit 为“候选批次”或“单事件深度分析”；常驻内存只与当前批次相关。
2. 每个 unit 独立短事务提交；禁止覆盖整窗的长数据库事务。
3. candidate、event、analysis 使用稳定唯一键幂等；重放不得产生第二份事实。
4. 每批次和每次模型调用前后检查取消；取消后不领取新 unit，已提交结果保留。
5. 进度必须包含阶段、当前来源/事件、完成/总量、百分比、最后更新时间；运行中不得连续 30 秒没有可见状态更新。
6. 模型、Debug、状态观测或飞书失败不得回滚已经提交的候选/分析业务事实。
7. Run 在成功、部分成功、失败、取消时进入一致终态；失败必须区分来源读取、模型、结构校验、评分、投递和资源预算。
8. 进程退出后按持久化 stage 续跑；不重新发现已冻结范围，不重新发送已成功 payload。
9. 日志禁止记录全文、Webhook/secret 或未脱敏模型 prompt；通过 source key、run/event id 和错误码定位。

---

## 17. 校准、测试与验收

### 17.1 M0：数据与性能预审

数据、容量与 Prod 资源盘点已完成，证据见 [M0 测量与实机验证报告（2026-09-24—2026-09-28）](/Users/congming/github/goldenshare/docs/architecture/news-intelligence-digest-feishu-m0-readonly-validation-2026-09-24.md)。30 个窗口的抓取触达上界最高为 7,827 条；旧表没有不可变首见时间，历史净新增只能得到约 900 条的下界代理，正式分布必须由 shadow cursor 记录。M0 同时冻结 800 字摘要资格、500 行 Raw discovery batch 和 10 GiB/年 HDD 容量预算。

M0-3 已在 Prod HDD 隔离安装三个冻结模型及运行时并完成 CPU 单模型 benchmark。Embedding 峰值约 1.78 GiB，mDeBERTa 峰值约 1.49 GiB，Qwen 峰值约 4.35 GiB；现有 Web/Ops 服务保持 active，结束后无模型残留进程或监听端口。单模型可运行，但保守整窗组合估算约 84.7 分钟，故 60 分钟门禁未通过，必须由 M1 的真实有界回放收缩并复测。`cctv_news` 首次观测停在 2026-08-19；用户手动补数后已连续更新到 2026-09-23，Raw/Serving 双向对账为 0 差异。当前数据完整性已恢复；自动更新由用户另行处理，仍是正式投递前的外部依赖，但不计入 M0 剩余任务。

### 17.2 M1：离线历史回放

使用冻结旧日期按五个时点回放；不写正式 Run、cursor 或 delivery 表。先完成 100–150 条 taxonomy 定义试标，再冻结 600–1000 条正式人工校准集，形成分类报告、聚类误差、摘要事实报告、Top 15/30 排名报告和资源测量。

### 17.3 M2：持久化与增量内核

验证三来源 Raw-id 水位、重复 upsert 不重复处理、迟到旧日期新身份、冻结上界、空窗、取消、退出续跑、幂等重放、单来源失败、模型降级和状态写失败隔离。迁移前核对真实 Alembic head；不删除或重建任何现有业务表。迁移后逐对象核验表、TOAST、主键/唯一/普通索引全部在 `gs_raw_cold_hdd`，禁止任何对象落入 `pg_default`。

### 17.4 M3：Debug 与固定窗口影子投递

生产只生成候选、Top 30、Top 15 payload，不发飞书。至少连续观察 10 个有效交易/自然日，确认窗口完整性、运行时长、模型资源、分类/排序、运营 Debug 页面和人工反馈闭环。

### 17.5 M4：五时点飞书推送

单独批准后启用固定窗口投递；先测试群再正式目标。验证重复发送、失败重试、空窗静默、Top 15 上限、内容降级、专用 Webhook 密钥隔离、15 条链接可点击、移动端/桌面端原文阅读及三来源详情展示。

### 17.6 M5：重大新闻 Shadow

在不发送的前提下运行建议 5 分钟观察，记录 would-send 质量和延迟。即时飞书不属于 M5 验收，也不能随 M4 自动启用。

### 17.7 一期最低验收

| 范围 | 门槛 |
| --- | --- |
| 增量 | 冻结样本内 0 漏候选、0 重复候选；迟到数据进入后续 Run |
| 分类 | 核心标签 Recall >= 0.85；整体 Macro-F1 >= 0.75，或经用户批准的新门槛 |
| 聚类 | Top 30 无已知重复事件；误合并逐例为 0 才能推送 |
| 摘要 | 推送样本数字/实体错误为 0；无原文支持事实为 0 |
| 排名 | 人工 Precision@15 达到约定门槛；关键漏报逐例复盘 |
| Debug | 全候选均有阶段/原因；Top 30 可解释到七维证据和版本 |
| 性能 | 最大代表窗口 < 60 分钟且不依赖 swap；Web/Ops 服务无可测退化 |
| 投递 | 同一 payload 0 重复；飞书失败不回滚业务结果 |
| 详情链接 | 每条推送均有不可枚举的免登录 HTTPS 详情入口；三来源可读；无 Debug/系统字段；HTML XSS 样本不可执行 |
| 存储 | 所有新增表、TOAST、约束索引和普通索引的有效 tablespace 均为 `gs_raw_cold_hdd` |
| Shadow | 一期任何即时场景飞书调用次数为 0 |

---

## 18. 实施影响面与测试矩阵

目标影响面预计包括：

- Biz：news intelligence domain、ORM/repository/service/query/API；
- App：模型适配器、Feishu adapter、worker/CLI 或服务装配、模型注册；
- 数据库：`app.wealth_news_digest_*` 新表与约束；
- 前端：`frontend/` 审查中心的桌面端新闻智能 Debug/反馈页面，以及 `wealth/` 免登录原文详情页；
- 部署：独立模型 Worker 与资源参数；
- 文档：本文、API/运营说明和部署手册的实施后同步。

至少覆盖以下正反测试：

1. 三来源字段映射与 CCTV 无伪造发布时间；
2. `news.score` 未被读取的静态/行为护栏；
3. 五时点跨日窗口、每来源 Raw-id 水位和重复 upsert 反例；
4. 迟到、同时间、多批、空窗、失败、取消、续跑、幂等；
5. 主/副主题、事件类型、`UNRESOLVED/AMBIGUOUS/NOT_APPLICABLE`、低置信度和版本冻结；
6. 800/12000 摘要边界、单句长文本、事实核验失败降级；
7. 七维档位映射、低可信重大传闻、来源转载不重复加分；
8. 全候选留档、Top 30 Debug、Top 15 上限和多样性调整；
9. Qwen 只处理有界集合、预算耗尽不扩大范围；
10. Shadow 全链路有记录但 Feishu adapter 零调用；
11. 飞书签名、业务错误、超时、幂等和脱敏；
12. `post` 富文本 `a` 链接、URL 编码、公开 ID 不可枚举、统一 404、外链失效和移动端/桌面端原文阅读；
13. Public DTO 字段白名单、现有鉴权 Reader 不降权、公开页无 Debug 字段、无公开列表/搜索接口；
14. `URL/HTML/TEXT` 互斥合同、HTML sanitizer、CSP、noindex/noarchive、限流与恶意脚本/事件属性/危险协议反例；
15. 任一来源发现/排序不完整时 Feishu 零调用，单条摘要失败的显式降级；
16. 候选与结构化分析无自动删除任务，90 天容量审计不执行清理；
17. 专用新闻机器人凭据不与 Ops 通知凭据串用；
18. 新表、TOAST、主键/唯一/普通索引 HDD tablespace 断言与缺失 tablespace 失败；
19. Biz/Ops/Foundation/App 依赖矩阵与 legacy 防回流。

---

## 19. CodeGraph 审计与现存消费者

本文编写前使用 `codegraph_explore`，覆盖：

- `NewsLight/MajorNewsLight/CctvNewsLight` 三个来源模型；
- `MarketNewsQuery/MajorNewsQuery/MarketNewsQueryService` 与 Wealth briefs/communications 消费；
- `FeishuTaskNotificationService`、Task completion worker；
- 现有新闻 reader API、`NewsReaderContentResolver`、前端 `NewsReaderDialog/SanitizedHtmlContent` 与 `WEALTH_PUBLIC_BASE_URL`；
- `OperationsScheduler`、新闻 DatasetDefinition/TaskRun；
- 股票新闻关联、事件合并及相关测试/前端消费者。

审计结论：现有能力可作为事实源、查询和低层传输参考，但没有可直接扩展成本文业务的统一处理合同；尤其不能让 Ops 任务通知服务承接 Biz 新闻内容，也不能把股票详情请求内事件合并当作可持久化的三来源语义事件簇。现有 reader 已有安全内容合同，但仅支持快讯/通讯和弹窗打开，需补新闻联播与可深链页面后才能承接飞书链接。

仍需在 M1 或对应实施门禁中确认：最终生成模型业务准入、聚类/分类阈值、整窗资源预算、公开详情的限流数值、测试群中 `post` 链接在桌面/移动客户端的真实表现。App Worker 已冻结为独立进程、三模型按阶段串行、Qwen loopback 单实例的目标形态；实现和常驻部署尚未开始。三个首轮候选制品的 revision/格式已冻结并在 HDD 隔离安装，项目环境未修改。运营 Debug 已明确落在 `frontend/` 的“审查中心 → 新闻智能”；新闻机器人使用用户后续提供的专用地址与密钥。

---

## 20. 风险与停止条件

1. **资源不足**：代表性最大窗口超时、swap 抖动或影响现有服务时停止启用，不增加并发掩盖问题。
2. **分类体系不清**：人工标注分歧高时先改 taxonomy，不把问题归咎模型或强行微调。
3. **模型幻觉**：摘要无证据或数字错误时降级，不以“整体看起来合理”放行。
4. **事件误合并**：公司、数字、方向冲突时宁可拆分，误合并关键事件为上线阻断。
5. **来源延迟与重复抓取**：只按 published_at 会漏迟到数据，按 fetched_at 又会因重复 upsert 反复处理；必须使用当前 Raw 稳定自增 id 水位并保留 row_key_hash 业务身份。
6. **配置漂移**：无版本 policy 或浮动模型 revision 时禁止生成正式 Run。
7. **越权发送**：Shadow 路径触发飞书、缺失 idempotency 或凭据进入日志时立即停止。
8. **计划与现实冲突**：若真实代码、数据、模型行为或 Prod 性能与本文冲突，先回写本文并等待确认，不能靠临时补丁绕过。
9. **SSD 误写**：迁移继承 `pg_default`、遗漏约束索引迁移或 HDD tablespace 缺失时立即阻断，不允许先写 SSD 再异步搬迁。
10. **公开详情泄露/XSS**：公开 DTO 出现 Debug/系统字段、可枚举身份、公开列表/搜索、未经清洗 HTML 或危险外链协议时立即阻断 M4。

---

## 21. 下一步

M0及M1-0/1/2历史成果保留：六个代表日期37,137条事实、3,252条来源内精确重复及20+120条试标包已在Prod HDD冻结；140条样本形成135个事件，轻量模型回放8.52分钟。本机Argilla通过部署、导入导出和重启持久化验收。2026-10-03旧教学集已提交20条；该结果暴露分类混轴与表单负担问题，因此旧120条表单暂停。新版10条真实NLI建议已在HDD冻结并导入Argilla教学集，接下来等待用户试审和真实响应导出，纠偏后再扩展120条。行业/关注方向目前是明示规则建议，重要度尚未预评，不宣称完整业务分析。30条盲复标与taxonomy review通过后才生成正式800条（600辅助校准、200独立验收）。不得把旧模型结果、辅助接受率或自动测试通过当作质量与整窗性能准入；硬门禁未通过不进入M2。
