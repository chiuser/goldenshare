# ETF 基础信息重建与下游数据审计清理 LLD v1

状态：重新基线完成；P0-P6 已完成（未执行生产快照重建），原 P2-P9 执行序列已作废，新版 P7-P12 尚未开始
创建日期：2026-08-28
依据方案：[ETF 基础信息重建与下游数据审计清理技术方案 v1](/Users/congming/github/goldenshare/docs/architecture/etf-basic-rebuild-and-downstream-data-audit-cleanup-plan-v1.md)
适用代码：`src/foundation/**`、`src/ops/**`、`src/app/**`、`frontend/**`、`alembic/**`
不适用范围：公募基金 `.OF` 主数据域、`fund_adj` 现有全市场事实链、`etf_share_size` raw 直出链、`etf_rt_daily` provider 请求段

---

## 1. 设计结果

本 LLD 在 P2 开发前完成第一次代码重审，并在 P3 开工前再次核对 planner、Ops 观测、实时监控与分钟对齐链。业务口径 D1-D20 不变，但旧版 P2-P9 的阶段设计及本版曾写入的无消费者扩展已经作废。新版开发链以“先新增替代能力、再逐个迁移消费者、全部引用清零后才删除旧基础设施”为唯一顺序。

### 1.1 本次重审发现的严重问题

| 编号 | 旧 LLD 问题 | 直接风险 | 新版处理 |
|---|---|---|---|
| R1 | 旧 P2 要求从 `DAOFactory` 删除 `etf_series_active`，但 P3-P5 的 planner、writer、health 和监控仍在调用它 | P2 一完成，后续阶段和现有运行时立即断裂 | P2 只新增 Basic selector；旧 DAO 属性保留到所有消费者完成迁移后的 P8 |
| R2 | 旧 P2 的完成门禁要求 planner、发布、Health、候选和实时批次都完成生命周期测试 | P2 的验收依赖尚未开发的 P3-P5，阶段无法独立完成 | 每个消费者的生命周期测试归属自己的迁移阶段；P2 只验 selector 自身 |
| R3 | 旧文档写“更新 DAOFactory 暴露新 DAO”，但当前 `DAOFactory.etf_basic` 已存在 | 会制造无意义修改，并掩盖真正工作量 | P2 不改 `DAOFactory.etf_basic` 装配，只扩展 `EtfBasicDAO` 契约 |
| R4 | “每次只读一次”没有区分一次业务生命周期和一次 SQL；候选分页天然包含 count 与 page 两条 SQL | 容易为了字面上的“一条 SQL”破坏分页，或在循环中反复查 Basic | 统一解释为一次调用固定一个 `as_of_date` 和一份资格快照/子查询；候选允许 count + page 两条 SQL，但不得逐行、逐页重算条件 |
| R5 | selector 要输出排除统计，但公共方法只返回 target list/subquery | 诊断无法从指定契约可靠产生，消费者只能自行拼统计 | 新增 `EtfRequestabilitySnapshot`，一次返回 targets 与互斥排除计数 |
| R6 | 旧 cleanup service、旧 review API/UI 在多个阶段重复分配删除责任 | 同一文件可能被提前删除或重复处理，阶段边界失真 | cleanup 只在 P4 删除；review 只在 P7 删除；P8 只删除剩余激活池基础设施和表 |
| R7 | 旧 P6 同时说“不做 manifest”，又要求分钟 alignment manifest | 下游清理候选和分钟请求计划两个不同概念混用 | 禁止的是“事实删除清单”；分钟对齐产物统一命名 `alignment_plan`，只描述请求，不包含 DELETE |
| R8 | 分钟差集按“每个交易日至少一条 bar”判断，会把停牌/源端空日反复判成缺口 | 重复消耗额度，且仍不能证明分钟级完整 | V1 改为代码/频率的前缀与尾部请求覆盖；内部逐日缺口审计明确不在本需求 |
| R9 | 旧 P9 把不可逆删表、Basic 重建和大规模分钟补拉放在一个生产阶段 | 一个授权动作意外放大成多种不可逆或高额度动作 | 拆成 P11 生产切换与 Basic 重建、P12 独立额度审批后的分钟补拉 |
| R10 | 上位方案 M2 把 selector、全部消费者迁移和删表合成一个里程碑 | 无法做逐阶段验收，也无法判断何时允许删表 | 上位方案同步拆为与新版 P2-P12 一一对应的里程碑 |
| R11 | 曾为自动计划设计 `WINDOW_BEFORE_LIST_DATE` 汇总统计，并牵连共享 plan 与 Ops 诊断 | 只是“不生成 unit”的内部结果，却人为扩大共享契约和长期维护面 | 自动空窗口直接不生成 unit；只保留显式请求的结构化越界错误与实际 unit 上下文 |
| R12 | 曾笼统要求 planner、writer、monitor 都加载全量 snapshot 并写统一诊断 | 显式单代码请求浪费数据库读取，且多处没有真实诊断消费者 | 自动计划读一次 scoped snapshot；显式单代码只查一次 target；各消费者只输出已有业务真正需要的结果 |
| R13 | 曾给实时 monitor runtime 规划新的 eligible 计数和持久化诊断 | 当前结果契约和唯一消费者都不需要，属于无需求扩展 | 空集合复用现有 `skipped` 结果和 message，只进入 collector 日志 |
| R14 | 分钟 preview 曾允许历史 `as_of_date`、代码子集和频率子集 | Basic 没有历史表，历史资格无法还原；生产子集入口也偏离“全量对齐” | 公开输入只保留 `alignment_end_date`，固定全部当前可请求 ETF × 五个原生频率 |
| R15 | 曾在不知道真实 action/TaskRun 规模前同时设计 preview 和 submit，且每频率各建一个 TaskRun | 可能先造出大量 TaskRun，再靠批次掩盖设计失控 | P9A 只做真实只读 preview；同代码同区间合并频率；规模拍板后才允许 P9B |
| R16 | 曾用完整 Basic 内容 hash 做计划门禁，并按通用限速参数估算总耗时 | 无关字段变化会误杀计划，endpoint 实际限速和执行墙钟也无法由 unit 数可靠推出 | target hash 只包含代码、上市日、交易所；只报请求上下界，首批后反馈真实耗时 |
| R17 | 分钟覆盖区间曾未明确裁到目标区间，submit 也未阻止并发或重复的未完成 TaskRun | 代码复用的旧历史可能把补拉起点算到当前上市日前；重复提交可能生成重叠任务 | 覆盖先与 `[list_date, alignment_end_date]` 求交；submit 本地串行、拒绝已有 open `etf_mins` 任务，并原子创建一批 TaskRun |
| R18 | 曾为 Basic 对象来源新造 `universe_policy='master_data'` | 当前 `pool` 已表达“按对象集合展开”；新增 policy 会无端扩大 DatasetDefinition、catalog、resolver 和测试影响面 | 保留现有 `pool` 技术形状，只把 source 从旧 Ops 表改为 `core_serving_etf_basic`；它不表示持久化激活池 |
| R19 | 曾为“可请求集合为空”新造 ETF 专用错误码 | 现有 `universe_empty` 已准确覆盖，新增错误码只会扩大公共 codebook | 复用 `universe_empty`；P3 只新增两个无法由现有码准确表达的错误 |
| R20 | 曾给 Basic universe source 再挂一个 `resource='requestable_etf'` | Basic 没有多资源选择，这个伪 resource 没有信息量，还容易被理解成新池 | source 只保留 `type='core_serving_etf_basic'`；全市场/SH/SZ 由三个既有 builder 固定决定 |
| R21 | 分钟 preview 未限定 6,500 万行 raw 的查询形状和 Prod 超时 | 可能出现 ETF×频率 N+1 查询或无界聚合，给生产库制造长期压力 | P9A 只允许集合查询、只读事务和 60 秒 statement timeout；现有索引仍不能满足时停止，不擅自加索引 |

原 P2-P9 的文字不得再作为开发或发布依据。本文 P0-P6 的执行记录均为当前有效基线；P7 及以后没有已完成代码可继承。

### 1.2 重排后的核心结果

本 LLD 把 D1-D20 重新落成以下可独立验收的结果：

1. `etf_basic` 改为无业务过滤的完整快照请求，新增专用快照替换 write path；raw 保存全部源端行，serving 只保存 `.SH/.SZ`。
2. `EtfBasicDAO` 成为 ETF 身份与可请求资格的唯一查询入口，统一返回代码与 `list_date`；下游不得自行拼 `list_status`、后缀和上市日条件。
3. `etf_mins/etf_sh_cons/etf_sz_cons` 改由 Basic serving 展开代码，并在切窗前按 `list_date` 裁剪。
4. `fund_daily` 保持按交易日拉源端全集，但写入改为“raw 先提交、serving 后发布”两阶段事务，Basic 选择器失败不能回滚已成功写入的 raw，也不能让 serving 假成功。
5. `etf_rt_daily` 的源请求不变；health、实时监控候选和监控运行时在各自一次查询/运行开始时读取当前可请求 ETF，旧 `active_*` 契约彻底改名为 `eligible_*`。
6. 删除 `ops.etf_series_active` 的全部运行时、运维和前端能力；`ops.index_series_active` 明确保留，禁止按同名 `list_active_codes` 误删。
7. Prod 只读审计已确认下游已批准删除候选为 0；不实现通用事实清理 CLI、service、删除 manifest 或 apply，只在 Basic 重建后复跑同口径只读核验。
8. ETF 历史分钟全量对齐先计算“当前可请求 ETF × 频率”的上市日前缀/现有尾部请求缺口和额度预览，再复用正式 `etf_mins` TaskRun 补拉；内部逐日空洞不在 V1 猜测，不新增旁路抓取器。
9. `fund_adj`、`etf_share_size` 的数据链不改；尤其不新建 `etf_share_size` 物理 core/serving，不迁移直出 view，不接入 Basic 过滤。

本 LLD 没有新增业务口径待拍板。编码期间如果实测与本设计的当前代码事实不一致，必须停在对应开发阶段重新审计，不能自行引入兼容读取或临时旁路。

---

## 2. 本轮代码审计结论

### 2.1 审计方法与边界

本轮先在仓库根使用 CodeGraph 检查索引状态、探索入口和调用链，并对 `EtfSeriesActive`、`EtfSeriesActiveDAO`、`EtfSeriesActiveStore`、`EtfFundDailyServingCleanupService` 执行 impact 分析；随后使用精确字符串搜索补足动态注册、write path、CLI 名、HTTP 路由、前端请求和 Alembic 迁移。

CodeGraph 审计时索引包含 2,787 个文件、49,059 个节点和 124,757 条边。审计范围覆盖：

1. DatasetDefinition -> validator -> resolver -> unit planner -> request builder -> source client -> normalizer -> writer -> executor。
2. `EtfBasic` raw/serving model、DAO、DAOFactory 与写入链。
3. `EtfSeriesActive` model、DAO、Foundation contract、Ops adapter、seed、CLI、review API/UI、实时健康和实时监控。
4. 相关 Web API、前端类型、路由、导航和测试。
5. Alembic 当前 head 与旧激活池建表迁移。

CodeGraph 的宽泛 `list_active_codes` 影响结果同时命中 ETF 池和指数池，因此本次删除必须按 ETF 的具体类型、表名和 resource 精确执行，不能按方法名批量替换。

### 2.2 P1 开发前主数据链（历史基线）

| 环节 | P1 开发前实现 | 已确认问题 | P1 目标 |
|---|---|---|---|
| 定义 | `reference_master.py` 中 `etf_basic` 允许 6 个业务过滤字段 | 带过滤请求也可能走正式发布 | 正式 maintain 无业务过滤，只发布完整快照 |
| 分页 | `offset_limit`，`page_limit=5000`，短页终止 | 实现可复用 | 保留并将短页完整性纳入发布门禁 |
| 归一化 | 只要求 `ts_code`，reject 记录后可继续 | 快照允许部分行被丢弃 | 改为任何 reject 阻断整个 unit |
| 写入 | `raw_core_upsert` 同时 upsert raw/serving | 源端消失的旧主键不会删除 | 专用 raw/serving 同事务完整替换 |
| serving | 当前写入与 raw 同一批全部行 | `.OF` 也可进入 serving | 只发布 `.SH/.SZ`，状态不在发布层过滤 |
| 历史 | 两张表均为当前态物理表 | 无 SCD 或版本表 | 保持当前态，不新增历史表 |

当前 14 个业务字段为：

```text
ts_code, csname, extname, cname, index_code, index_name,
setup_date, list_date, list_status, exchange,
mgr_name, custod_name, mgt_fee, etf_type
```

raw 另有 `api_name/fetched_at/raw_payload`，serving 另有 `created_at/updated_at`。这些元数据字段不进入主数据内容 hash。

### 2.3 P3 开工前请求驱动链

| 数据集/能力 | 对应阶段开工前代码事实 | 目标替代 |
|---|---|---|
| `etf_mins` | unit planner 从 `resource='etf_mins'` 激活池读代码；未使用 `list_date` | 当前可请求 ETF + 上市日裁剪 |
| `etf_sh_cons` | 从 `.SH` resource 激活池读代码 | 当前可请求 ETF 中 `.SH` |
| `etf_sz_cons` | 从 `.SZ` resource 激活池读代码 | 当前可请求 ETF 中 `.SZ` |
| `fund_daily` | 源请求按日期全市场；writer 用 `resource='fund_daily'` 旧池过滤 serving | 源请求不变；serving 用当前可请求 ETF + 上市日 |
| `fund_adj` | 按日期全市场；不使用 ETF 激活池 | 完全不改 |
| `etf_share_size` | 按日期全市场；raw 单份存储、serving view 直出 | 完全不改 |
| `etf_rt_daily` | provider 固定请求 `5*.SH`、`1*.SZ`；旧池只用于 health/候选 | provider 不改；health/候选换 Basic |

P3 完成后，表中前三个 planner 已改用 Basic selector 且已按上市日裁剪；P4 又完成了 `fund_daily` writer 迁移和旧 cleanup 删除；P5 再迁移实时 Health。表中 `etf_rt_daily` 行现在只剩 monitor 与 review 的后续阶段消费者仍符合阶段前旧池事实。

P2 开工前，`EtfBasicDAO.get_active_etfs()` 把 `L/P/D` 都称为 active，`get_fund_daily_candidates()` 也接受 `L/P/D`，且 ingestion 主链没有调用这两个方法。P2 已将二者删除并替换为语义准确的新契约，没有保留别名。

### 2.4 P4 开工前事务问题（已修复）

P4 开工前，`IngestionExecutor._process_fetched_unit()` 的顺序是归一化、调用 writer、统一 `session.commit()`；`fund_daily` writer 在同一事务中先 upsert raw，再查询旧激活池并写 serving。因此选择器异常会让 raw 一起回滚，与上层方案确认的 raw/serving 边界不符。

P1 已新增通用 `persistence_diagnostics`，并打通 `_RunState -> IngestionExecutor -> TaskRunIngestionContext` 的有界 JSON 链路，未新增 TaskRun 列。P4 已在该既有链路中加入 `raw/serving/eligibility_as_of/excluded_reason_counts` 分层诊断，并由 executor 执行两个明确提交点；普通 `unit` 提交路径不变。

### 2.5 Tushare 契约复核

本轮复核的本地源文档为：

```text
docs/sources/tushare/ETF专题/0385_ETF基础信息.md
docs/sources/tushare/ETF专题/0387_ETF历史分钟行情.md
docs/sources/tushare/ETF专题/0407_ETF申赎清单.md
docs/sources/tushare/ETF专题/0471_ETF每日持仓组合(沪市）.md
docs/sources/tushare/ETF专题/0472_ETF每日持仓组合(深市）.md
docs/sources/tushare/ETF专题/0127_ETF日线行情.md
docs/sources/tushare/ETF专题/0199_基金复权因子.md
docs/sources/tushare/ETF专题/0408_ETF份额规模.md
docs/sources/tushare/ETF专题/0400_ETF实时日线.md
```

已确认：

1. `etf_basic` 支持 `limit/offset`，单页上限 5,000，当前 DatasetDefinition 的 14 个字段与源契约一致。
2. `etf_mins` 要求代码和频率，支持区间与 `limit/offset`；当前 `page_limit=8000`、每 unit 上限 24,000 行。
3. `fund_daily/fund_adj` 不传 `ts_code` 时是按交易日全市场请求，返回范围比 `etf_basic` 更宽。
4. `etf_share_size` 是按日期全市场接口；它的 raw 与业务使用口径相同。
5. `rt_etf_k` 当前固定通配符请求不需要 ETF 代码 fan-out。

本轮还使用 Tushare MCP 对 `510300.SH` 显式请求 14 个 `etf_basic` 字段，返回当前 `L` 状态、`setup_date=20120504`、`list_date=20120528` 和 `exchange=SH`，验证了关键字段仍可由当前源端显式返回。行数快照不固化为永久代码门禁。

### 2.6 Alembic 基线事实

2026-08-28 LLD 编写时的只读检查结果：

```text
heads   = 20260828_000155
current = 20260828_000155
文件     = alembic/versions/20260828_000155_make_suspend_d_raw_view.py
```

P0 复核期间，当前分支合入了本需求范围外的 `20260828_000156_make_stk_auction_o_raw_view.py`，实际结果变为：

```text
heads   = 20260828_000156
current = 20260828_000155
000156 down_revision = 20260828_000155
```

P0 没有修改或执行该迁移。当时代码端仍是唯一 head，但连接数据库落后一个版本；`heads != current` 触发了开发停止门禁。

2026-08-28 P1 恢复前重新实测：

```text
heads   = 20260828_000156
current = 20260828_000156
```

唯一 head/current 已对齐，P1 停止门禁解除。P1 未新增 Alembic 迁移；未来 drop-table migration 的 `down_revision` 仍必须接实施时再次确认的真实唯一 head。

### 2.7 Prod 下游清理范围实测

2026-08-28 使用当前 Tushare ETF Basic 全量结果对 Prod 做了受控只读审计。当前源端共有 1,825 行 ETF Basic，其中按本设计在当日可请求的 `.SH/.SZ` ETF 为 1,647 个；另有 1 个未来上市的 `L` 和 8 个 `L + list_date 为空`，均不进入可请求集合。

| 对象 | 当前规模 | 非 `.SH/.SZ` | 不在当前源端 ETF Basic | 交易所身份冲突 | 已批准删除候选 |
|---|---:|---:|---:|---:|---:|
| `raw_tushare.etf_minute_bar` | 约 6,584 万行，1,395 个代码 | 0 | 0 | 0 | 0 |
| `raw_tushare.etf_sh_cons` | 5,675,323 行，803 个代码 | 0 | 0 | 0 | 0 |
| `raw_tushare.etf_sz_cons` | 11,567,504 行，720 个代码 | 0 | 0 | 0 | 0 |
| `core_serving.fund_daily_bar` | 1,180,869 行，1,395 个代码 | 0 | 0 | 0 | 0 |
| `ops.etf_realtime_monitor_pool` | 3 行 | - | 0 个无效配置 | - | 0 |
| `ops.etf_realtime_monitor_rule` | 0 条 ETF 规则 | - | 0 | - | 0 |

`core_serving.fund_daily_bar` 有 2,091 行、3 个代码的事实日期早于**当前** `list_date`：`159908.SZ` 624 行、`511220.SH` 805 行、`512990.SH` 662 行。它们符合“上市日后移或代码复用无法从当前态主数据判明”的保留边界，只报告、不删除。ETF 分钟表同类候选为 0。

因此本 LLD 不再设计通用事实清理实现。Basic 重建后只复跑相同只读统计；若明确旧 `.OF` 身份仍为 0，本阶段无操作结束。若意外非零，停止并另立精确一次性方案。

### 2.8 P3 开工前二次代码审计

2026-08-28 再次检查 CodeGraph，索引为 up to date，包含 2,815 个文件、49,687 个节点和 126,215 条边。query/impact 与当前代码逐项确认：

1. 三个 ETF 数据集已经各有专用 target resolver 和 unit builder；旧表绑定发生在 Definition 的 `sources.type/resource` 与这三个 resolver 内。无需修改共享 `DatasetPlanningDefinition`，也无需新增 `master_data` policy。
2. `DatasetExecutionPlan` 没有 plan 级诊断字段，现有 Ops plan snapshot 只序列化 unit 自带的 `progress_context`。P3 因而只写实际 unit 的上市日上下文，不扩展共享执行计划。
3. `EtfRealtimeMonitorRunResult` 现有字段已经能用 `status='skipped' + message` 表达空资格集合，当前运行时消费者是 collector 日志。P6 不新增 eligible 计数或 TaskRun 诊断。
4. 当前 `etf_mins` TaskRun 请求已支持一次选择多个频率；同代码、同日期范围无需拆成多个 TaskRun。P9 按该现有能力合并 action；各频率仍生成自己的 unit 和源请求，不新增任务类型，也不虚减请求量。
5. Tushare client 对 `etf_mins` 的 endpoint 级限速为 500 次/分钟，而通用 Settings 默认值为 280 次/分钟；真实耗时还包含队列、网络、重试和写入，不能用通用 Settings 伪造预估总耗时。
6. `TaskRunCommandService.stage_task_run()` 已支持由调用方控制事务。P9B 可以在 alignment submit service 内完成专用锁、open-run 检查和整批原子提交，不需要修改共享 TaskRun 创建契约。

---

## 3. 工程设计决策

| 编号 | 已落定设计 | 原因 |
|---|---|---|
| E1 | `EtfBasicDAO` 提供统一主数据/当前可请求查询；所有消费者调用它 | 消灭各下游自行拼状态、后缀和日期条件 |
| E2 | 正式 `etf_basic maintain` 删除所有业务过滤输入 | 防止部分源结果覆盖完整快照 |
| E3 | 新增 `raw_etf_basic_snapshot_replace` 专用 write path | 通用 upsert 不具备删除缺失主键的快照语义 |
| E4 | 快照先完整拉取和校验，再在一个事务中替换 raw/serving | 源失败不触碰旧数据；raw/serving 不出现跨版本 |
| E5 | `fund_daily` 使用 `raw_then_serving` 两阶段提交策略 | raw 是源端事实，不能因 ETF serving 选择器失败而丢失 |
| E6 | `fund_daily/fund_adj/etf_share_size` 现有显式 `ts_code` 入口保留，但只视为对应源接口的人工探测/修复；Basic 不用它们扇出请求 | 保持现有单代码运维能力，同时避免把它误当成 ETF 自动同步主链 |
| E7 | `etf_mins/sh_cons/sz_cons` 保留现有 `universe_policy='pool'` 对象展开形状，只把 source 改为 `core_serving_etf_basic` | 避免新增无必要的共享 policy 或伪 resource；持久化激活池由 source 类型决定，不由这个通用字段名决定 |
| E8 | 上市日裁剪必须早于切窗；自动计划的空窗口不生成 unit，显式请求越界直接报结构化错误 | 不向源端发上市日之前的无效请求，不为无消费者的自动跳过数量扩展共享计划或 Ops 契约 |
| E9 | health 改名为 `eligible_etf_count/eligible_snapshot_count`，候选接口改为 `/eligible-etfs` | 表退场后不再传播“激活池”概念；不留旧字段别名 |
| E10 | 不新增通用下游事实清理 CLI、service、删除 manifest 或 apply；旧 `fund_daily` cleanup 与 CLI 直接删除 | 当前已批准删除候选为 0，避免为零规模问题建设长期删除系统 |
| E11 | 激活池 migration 的 downgrade 明确不可逆 | 不允许降级时重建一个无事实依据的空池或旧池 |
| E12 | 分钟全量对齐只生成正式 TaskRun，不直接调用 connector 或 writer | 保留正式分页、限流、归一化、幂等和观测链 |
| E13 | P9 拆为“全量只读 preview”和“规模拍板后的 submit” | 在建设写入口前先证明真实任务量，避免用执行批次掩盖错误粒度 |
| E14 | submit 的并发门禁和批量事务只放在 alignment submit service，不扩展共享 TaskRun 契约 | 这是一次性对齐工作流的安全要求，不冒充通用调度能力 |

### 3.1 没有新增配置项

本设计不新增 env、Settings、数据库配置或运营页面开关：

| 事项 | 来源 | 生效方式 | 消费者 |
|---|---|---|---|
| ETF 分钟频率窗口 | 现有 `ETF_MINS_RANGE_WINDOW_MONTHS` | 代码发布 | unit planner、对齐预览 |
| `page_limit=8000`、unit 上限 24,000 | 现有 DatasetDefinition | 代码发布 | source client、额度预览 |
| 当前可请求日期 | 调用方在一次查询、规划或发布开始时显式计算中国时区自然日 | 对应调用生命周期内固定 | Basic DAO selector |
| P9A Prod 查询超时 | alignment plan service 内部安全常量 60 秒；不进入 env/Settings/数据库配置 | 每次 preview 事务用 `SET LOCAL` 生效，CLI 报告是否超时 | 只读 alignment preview |

P9A 的 60 秒是防止只读审计拖垮 Prod 的 fail-closed 上限，不是业务参数，也不允许页面或 CLI 覆盖。如果实施阶段再提出其他阈值、开关或持久化路径，必须另做配置项审计，不能把它偷偷写成页面常量或脚本常量。

---

## 4. ETF Basic 统一查询契约

### 4.1 值对象与统计口径

在 `src/foundation/dao/etf_basic_dao.py` 定义不可变值对象：

```python
@dataclass(frozen=True, slots=True)
class EtfRequestTarget:
    ts_code: str
    list_date: date
    exchange: Literal["SH", "SZ"]

@dataclass(frozen=True, slots=True)
class EtfRequestabilitySnapshot:
    as_of_date: date
    exchange: Literal["SH", "SZ"] | None
    targets: tuple[EtfRequestTarget, ...]
    serving_row_count: int
    requestable_count: int
    excluded_reason_counts: Mapping[str, int]
```

`EtfRequestTarget` 不携带 `list_status`，因为能返回该对象本身就表示已满足 `L`。`list_date` 和 `exchange` 均不可空，从类型层阻止调用方忘记上市日或再次猜交易所。

snapshot 的排除原因使用固定优先级，保证一行只能进入一个分类：

```text
NON_EXCHANGE_SUFFIX
-> EXCHANGE_MISMATCH
-> STATUS_NOT_LISTED
-> LIST_DATE_NULL
-> LIST_DATE_AFTER_AS_OF
-> REQUESTABLE
```

全市场 snapshot 对 serving 全表分类，因此生产重建前残留的 `.OF` 会进入 `NON_EXCHANGE_SUFFIX`，绝不能成为 target。传 `exchange='SH'/'SZ'` 时，统计作用域只包含该规范后缀；另一交易所不算排除项。

### 4.2 DAO 公共方法

删除语义错误且无运行时消费者的旧方法：

```python
get_active_etfs()
get_fund_daily_candidates()
```

新增且只新增：

```python
load_requestability_snapshot(
    *,
    as_of_date: date,
    exchange: Literal["SH", "SZ"] | None = None,
) -> EtfRequestabilitySnapshot

get_requestable_target(
    *,
    ts_code: str,
    as_of_date: date,
    exchange: Literal["SH", "SZ"] | None = None,
) -> EtfRequestTarget | None

requestable_targets_subquery(
    *,
    as_of_date: date,
    exchange: Literal["SH", "SZ"] | None = None,
)
```

不新增无实际消费者的 `list_master_rows()`。审计用 snapshot 统计或受控 SQL，不能为了“以后可能用”扩大 DAO 契约。

三个方法共同复用：

1. `_normalize_exchange()`：只接受 `None/SH/SZ`，其他值抛 `ValueError`。
2. `_normalize_ts_code()`：执行 `strip().upper()`；空值或非 `.SH/.SZ` 返回 `None`。
3. `_requestable_predicates()`：资格条件的唯一实现。
4. `_classify_master_row()`：只为 snapshot 生成互斥排除统计。

`requestable_targets_subquery()` 固定暴露以下列，供 Ops 分页 join：

```text
ts_code, list_date, exchange, csname, extname, cname, etf_type, list_status
```

其中 `list_status` 对返回行恒为 `L`，保留它只是避免当前监控候选 DTO 再次 join Basic。Ops 不得在 subquery 外复制状态、后缀或上市日条件。

当前 `DAOFactory` 已经暴露 `etf_basic`，P2 不修改该装配。`DAOFactory.etf_series_active` 在 P2 仍保留，直到 P3-P7 的所有消费者迁移并通过零引用门禁后，才在 P8 删除。

### 4.3 唯一资格条件

```text
list_status = 'L'
AND list_date IS NOT NULL
AND list_date <= :as_of_date
AND (
  (ts_code LIKE '%.SH' AND exchange = 'SH')
  OR
  (ts_code LIKE '%.SZ' AND exchange = 'SZ')
)
```

SQL 中后缀组合必须整体加括号。传 `exchange='SH'` 时只保留第一支，传 `exchange='SZ'` 时只保留第二支。结果按 `ts_code` 排序。raw 中的 `.OF` 不会通过该 DAO 进入下游。

### 4.4 读取时点与调用日期

“动态读取当前可请求 ETF”不是每天生成一个新池，也不是每发一个 Tushare 请求都查询一次数据库。各消费者按一次业务生命周期固定资格结果：

| 消费者 | 读取时点 | 本次结果使用范围 |
|---|---|---|
| `etf_mins/etf_sh_cons/etf_sz_cons` 自动 planner | 一次 `DatasetUnitPlanner.plan()` 开始时 | 调用一次对应交易所作用域的 snapshot；同一次 plan 的代码、裁剪和切窗复用 targets |
| `etf_mins/etf_sh_cons/etf_sz_cons` 显式单代码 planner | 一次 `DatasetUnitPlanner.plan()` 开始时 | 只调用一次 `get_requestable_target()`；不为单代码请求加载全市场 snapshot |
| `fund_daily` serving 发布 | 一次 serving phase 开始时 | 调用一次 snapshot；本批全部行复用 `ts_code -> target` map |
| `etf_rt_daily` Health | 每次 Health API 查询开始时 | 调用一次 snapshot；本次响应复用 target codes |
| 实时监控候选列表 | 每次 `/eligible-etfs` API 请求开始时 | 固定一个 `as_of_date` 并构造一次 subquery；允许 count 与 page 两条 SQL |
| 实时监控运行时 | 每次 `run_after_etf_batch()` 开始时 | 调用一次 snapshot；本批规则和告警复用 target codes |
| ETF 分钟对齐 preview | 每次 preview 开始时 | 内部计算一次当前中国日期并调用一次全市场 snapshot；本次全量计划固定 targets |

“一次读取”指一次业务生命周期只解析一次资格口径，不是所有接口只能执行一条 SQL。禁止的是在逐代码、逐 unit、逐指标、逐规则或分页结果循环里重复查 Basic。

每个调用者只计算一次 `as_of_date = datetime.now(ZoneInfo("Asia/Shanghai")).date()` 并显式传给 DAO。长任务跨过自然日零点也不在中途换集合；下一次任务重新读取。

读取结果只按已有消费者需要输出，不再统一要求“写入诊断 JSON”：

1. planner 只在实际生成的 unit `progress_context` 中写当前 target 的 `eligibility_as_of/master_list_date/requested_start_date/effective_start_date`；不持久化全市场汇总统计，不扩展 `DatasetExecutionPlan`、TaskRun 或 Ops 契约。
2. `fund_daily` 因存在 raw 已提交、serving 失败的业务边界，只把第 7.4 节规定的分层持久化结果写入现有 ingestion diagnostics。
3. Health 只返回现有页面消费的 `eligible_etf_count/eligible_snapshot_count`，不写 TaskRun。
4. monitor runtime 只把本批处理结果返回 collector 日志；空资格集合用 `skipped` 与明确 message 表达，不新增计数字段或持久化诊断。

---

## 5. `etf_basic` 完整快照发布

### 5.1 DatasetDefinition 修改

文件：`src/foundation/datasets/definitions/reference_master.py`

目标值：

| 字段 | 目标 |
|---|---|
| `input_model.filters` | 空元组 |
| `request_builder_key` | `_etf_basic_snapshot_params` |
| `write_path` | `raw_etf_basic_snapshot_replace` |
| `reject_policy` | `fail_unit_on_any_rejection` |
| `batch_unique_key_fields` | `('ts_code',)` |
| `source_multiplicity_policy` | `reject` |
| `empty_result_policy` | `fail_unit` |
| `pre_write_validator_key` | `etf_basic_snapshot` |
| `page_processing_mode` | `buffer_all`，必须先拿到完整分页批次再开数据库事务 |
| `transaction.commit_policy` | `unit`，保持单业务事务 |
| `idempotent_write_required` | `True` |

`_etf_basic_snapshot_params()` 必须拒绝请求中残留的 `ts_code/index_code/exchange/mgr/list_status/list_date`，并始终返回空业务参数。旧 `_etf_basic_params()` 删除，不留探测型正式写入口。

如果以后确实需要源端筛选探测，应放在只读 probe 能力中，不能复用 Dataset maintain 和正式 writer。

### 5.2 发布前校验器

新增纯函数模块：

```text
src/foundation/ingestion/etf_basic_snapshot.py
```

职责仅包括：

1. 校验非空、主键唯一、源端行数等于归一化行数。
2. 校验 `list_status` 只出现 `L/P/D`。
3. 校验后缀只出现 `.SH/.SZ/.OF`。
4. 校验 `.SH -> exchange=SH`、`.SZ -> exchange=SZ`；`.OF` 不强制伪造交易所。
5. 统计各状态下 `list_date` 为空数量，但不因此拒绝 raw。
6. 以 14 个业务字段计算规范化 hash 和变更摘要。

规范化规则：

```text
按 ts_code 排序
日期转 YYYY-MM-DD 或 null
Decimal/数值转不含科学计数法的规范字符串或 null
字符串保留源端语义，只将数据库 null 统一为 JSON null
JSON 使用 UTF-8、固定字段顺序、无多余空白
SHA-256 计算内容 hash
```

不得把 `api_name/fetched_at/raw_payload/created_at/updated_at` 纳入 hash，否则相同业务快照每天都会产生伪变化。

### 5.3 writer 事务

`DatasetWriter.write()` 新增精确 dispatch：

```python
if definition.storage.write_path == "raw_etf_basic_snapshot_replace":
    return self._write_etf_basic_snapshot_replace(...)
```

事务内顺序：

```text
1. SELECT pg_advisory_xact_lock(稳定的 etf_basic snapshot lock key)
2. 读取旧 raw/serving 的业务字段，计算 before hash 与 diff
3. DELETE raw_tushare.etf_basic
4. INSERT 完整已校验 raw rows
5. DELETE core_serving.etf_basic
6. INSERT 本批次中仅 .SH/.SZ 的业务字段
7. flush
8. 对账 raw 主键集合 = 源批次主键集合
9. 对账 serving 主键集合 = 源批次中 .SH/.SZ 主键集合
10. 对账 raw 业务 hash = 完整源批次 hash，serving 业务 hash = 源批次 `.SH/.SZ` 子集 hash
11. 返回 WriteResult，由 executor 执行唯一一次 commit
```

DAO 只执行 SQL，不调用 commit。writer 内任一对账失败抛 `IngestionWriteError(error_code='etf_basic_snapshot_invalid')`，executor rollback 后旧 raw/serving 都恢复。

不使用 `TRUNCATE`，因为它不应脱离当前事务和表权限模型；不 drop/recreate 表；不触发任何下游级联删除。

### 5.4 并发门禁

两层门禁同时存在：

1. Ops 创建 `etf_basic` TaskRun 时拒绝第二个 `queued/running/canceling` 的同数据集 maintain 任务。
2. writer 使用 PostgreSQL transaction advisory lock 防止绕过 Ops 或多个 worker 同时替换。

advisory lock 是最终数据安全门禁；Ops 冲突检查用于提前给运营明确错误。两者都不能改成旧激活池或 seed fallback。

### 5.5 诊断扩展

在 `WriteResult` 新增：

```python
persistence_diagnostics: dict[str, Any] = field(default_factory=dict)
```

并经 `_RunState`、`IngestionExecutor._build_ingestion_diagnostics()` 和 `TaskRunIngestionContext` 的现有安全清洗器写入诊断 JSON。样本代码最多保留 20 个，避免 TaskRun JSON 无界增长。

快照诊断至少包含：

```text
source_rows
normalized_rows
raw_before_count / raw_after_count
serving_before_count / serving_after_count
source_snapshot_hash
raw_business_hash / serving_business_hash
added_count / removed_count / changed_count
status_changed_count / list_date_changed_count
bounded added/removed/changed samples
pagination page_count / terminal_offset / terminal_page_rows / observed_short_page
```

`rows_written` 继续表达正式 serving 写入数；raw 写入数放在 `persistence_diagnostics`，不改变所有数据集共享的顶层语义。

---

## 6. 代码驱动数据集规划

### 6.1 DatasetDefinition universe

`etf_mins/etf_sh_cons/etf_sz_cons` 的 planning 改为：

```python
universe_policy = "pool"
universe.sources = (
    DatasetUniverseSourceDefinition(
        type="core_serving_etf_basic",
    ),
)
```

`request_field='ts_code'` 和 `override_fields=('ts_code',)` 保持。旧 `ops_etf_series_active` resource 全部删除。

这里的 `pool` 只沿用当前 DatasetDefinition 的“按对象集合 fan-out”技术形状，不表示存在新的持久化池，也不允许继续访问 Ops 激活池。Basic source 不配置 `resource`；新增共用的 planner 私有 Definition 校验 helper，只负责确认 `pool + core_serving_etf_basic + resource is None` 形状，不读数据库。通过校验后按请求形状分流：

1. 自动计划调用一次 `EtfBasicDAO.load_requestability_snapshot()`；`etf_mins` 读全市场，`etf_sh_cons/etf_sz_cons` 分别读 `SH/SZ` 作用域。对应作用域 targets 为空时复用现有 `universe_empty` 并在错误详情中写 exchange。
2. 显式单代码计划不调用 snapshot，只走第 6.2 节的 `get_requestable_target()`。

三个 builder 共用 Definition 校验和 P2 DAO 资格契约，不能分别实现 SQL，也不得回退旧池。

### 6.2 显式代码

显式 `ts_code` 的规则：

1. 一次仍只允许一个代码。
2. 必须命中 `get_requestable_target(ts_code, as_of_date)`。
3. `etf_sh_cons` 额外要求 `.SH`；`etf_sz_cons` 额外要求 `.SZ`。
4. 不命中时抛 `etf_not_requestable`，错误详情记录代码和 `as_of_date`，不泄露内部 SQL。
5. 不允许回退到 seed CSV、旧表或“只要是 `.SH/.SZ` 就放行”。

本需求使用的结构化错误码按阶段登记到 `src/foundation/ingestion/codebook.py`，P3 不提前实现 P4 错误：

| 错误码 | 错误阶段 | 实现阶段 | 含义 |
|---|---|---|---|
| `etf_not_requestable` | planner | P3 | 代码不满足当前 Basic 可请求条件 |
| `window_before_list_date` | planner | P3 | 显式请求窗口整体早于上市日 |
| `etf_basic_snapshot_invalid` | validator/writer | P1 已完成 | Basic 完整快照校验或对账失败 |
| `fund_daily_serving_publish_failed` | writer/executor | P4 | raw 已提交但 ETF serving 发布失败 |
| `universe_empty` | planner | 现有复用 | 本次作用域没有当前可请求 ETF，自动任务停止且不生成源请求 |

### 6.3 上市日裁剪顺序

对每个 `EtfRequestTarget`：

```python
effective_start = max(requested_start, target.list_date)
effective_end = requested_end
```

严格顺序：

```text
解析请求日期
-> 取得 EtfRequestTarget
-> 按 list_date 裁剪
-> 若空窗口则跳过/报错
-> 按频率自然月跨度切窗
-> 生成 PlanUnitSnapshot
```

不能先按全市场日期切窗再逐 unit 丢弃，否则计划量和额度预览仍包含上市前无效窗口。

自动全量计划中，整个请求窗口早于某只 ETF 上市日时，该 ETF 直接不生成 unit；不新增自动跳过原因计数，也不为此扩展 `DatasetExecutionPlan`、TaskRun 或 Ops 观测契约。显式单代码请求的整个窗口为空时抛 `window_before_list_date`；point 请求要求 `trade_date >= list_date`。

若自动计划中的全部 target 都因本次窗口早于各自上市日而被裁掉，planner 返回现有合法的 0-unit plan；当前 executor 会以 0 个单元正常完成且不调用源端。P3 只补回归测试固定这一既有语义，不新增 `skipped` 状态或汇总原因。

每个生成 unit 的 `progress_context` 增加：

```text
eligibility_as_of
master_list_date
requested_start_date
effective_start_date
```

源请求 builder 只接收已经裁剪后的日期，不能再次自行改日期。

P3 同时把当前仅由 `etf_mins` 使用的频率窗口选择和自然月切窗移到 ETF 专用纯函数模块：

```text
src/foundation/ingestion/etf_minute_windows.py
```

```python
build_etf_minute_windows(
    *, freq: str, start_date: date, end_date: date
) -> tuple[tuple[date, date], ...]
```

该模块同时保存五个频率对应的 2/12/36/72/120 月常量，原 `_split_calendar_month_span_windows()` 和 `ETF_MINS_RANGE_WINDOW_MONTHS` 不再在 `unit_planner.py` 保留第二份。planner 在完成 selector 与 `list_date` 裁剪后调用该函数；P9 alignment preview 也只调用该纯函数计算 unit，不得为每个 action 实例化一次完整 resolver。它是 ETF 分钟专用计算，不新增 `DatasetExecutionPlan` 字段、不进入共享 Ops 契约，也不泛化成其他数据集能力。

### 6.4 各数据集差异

| 数据集 | 对象集合 | 日期裁剪 | 原有切窗/分页 |
|---|---|---|---|
| `etf_mins` | 全部当前可请求 ETF | `DATE(trade_time) >= list_date` | 保留 5 个频率的现有自然月窗口、8,000 分页 |
| `etf_sh_cons` | 当前可请求 `.SH` | `trade_date >= list_date` | 保留 point/半年窗口和现有分页 |
| `etf_sz_cons` | 当前可请求 `.SZ` | `trade_date >= list_date` | 保留 point/月窗口和现有分页 |

`fund_daily` 不进入本节 fan-out；它仍由 generic planner 每个交易日生成一个全市场 unit。

---

## 7. `fund_daily` 两阶段落库

### 7.1 Definition 与请求边界

文件：`src/foundation/datasets/definitions/market_fund.py`

目标修改：

```text
write_path: raw_fund_daily_etf_serving_publish
transaction.commit_policy: raw_then_serving
```

以下保持不变：

1. 默认按 `trade_date` 一次请求源端全集并分页。
2. 不按 Basic ETF 数量拆成逐代码请求。
3. 显式 `ts_code` 仍是基金接口的人工探测/修复入口，不由 Basic 扇出，不改变 raw 边界。
4. raw 保存源端返回的所有场内基金代码。

### 7.2 writer/executor 职责

writer 新增两个只写不提交的方法：

```python
write_raw_phase(...)
write_serving_phase(..., eligibility_as_of: date)
```

executor 对 `commit_policy='raw_then_serving'` 执行：

```text
normalize once
-> raw phase upsert
-> COMMIT raw
-> 记录 raw_committed=true 与 raw_rows_committed
-> 读取当前可请求 ETF map(ts_code -> list_date)
-> serving phase filter + upsert
-> COMMIT serving
-> unit success
```

DAO 和 writer phase 均不得自己 commit；两个提交点只存在于 executor。普通 `commit_policy='unit'` 的其他数据集不受影响。

### 7.3 serving 过滤

对每个归一化 row：

```python
target = requestable_by_code.get(row["ts_code"])
publish = target is not None and row["trade_date"] >= target.list_date
```

未发布到 ETF serving 的行不是 normalizer reject，也不影响 raw 成功；按原因统计：

```text
CODE_NOT_REQUESTABLE_AT_PUBLISH
BEFORE_CURRENT_LIST_DATE
```

selector 返回空集合、数据库查询失败或 serving upsert 失败时：

1. rollback 当前 serving 事务。
2. 保留已提交 raw。
3. 抛 `fund_daily_serving_publish_failed`。
4. TaskRun unit 标记失败，不得标成功或 partial success。
5. 诊断必须明确 `raw_committed=true`、raw 行数、serving 行数和失败阶段。
6. 重试时 raw upsert 幂等，再尝试 serving 发布。

绝不允许 selector 失败后把全部 raw 行写入 ETF serving，也不允许退回旧激活池。

### 7.4 观测语义

顶层 `rows_written/rows_committed` 继续表达 serving 目标表，新增分层诊断：

```json
{
  "persistence": {
    "raw": {"rows_upserted": 0, "committed": true},
    "serving": {"eligible_rows": 0, "rows_upserted": 0, "committed": false},
    "eligibility_as_of": "2026-08-28",
    "excluded_reason_counts": {}
  }
}
```

如果 raw commit 后 observer 状态写入失败，不能反向影响 raw；这沿用业务事务与 TaskRun 观测事务隔离规则。

### 7.5 `fund_adj/etf_share_size` 显式入口

D17 中待 LLD 定位的另外两个显式单代码入口结论如下：

1. `fund_adj` 的显式 `ts_code` 保留，继续把源端返回写入 `raw_tushare.fund_adj` 和 `core.fund_adj_factor`，不接 Basic 过滤。
2. `etf_share_size` 的显式 `ts_code` 保留，继续写 `raw_tushare.etf_share_size`，现有 `core_serving.etf_share_size` view 自动直出，不接 Basic 过滤。
3. 两者都不得由 Basic 当前可请求列表自动 fan-out；日常任务继续按交易日一次拉源端全集。
4. 本次不修改它们的 write path、事务策略、物理表或 serving view；只增加回归测试证明这些边界没有被 ETF 主数据改造误伤。

---

## 8. ETF 实时链路替换

### 8.1 provider 不改

`src/foundation/realtime/etf_rt_daily.py` 的固定沪深通配符请求、Redis batch、snapshot 和 delta 发布全部保持。不得改成逐 ETF 请求。

### 8.2 health 契约改名

后端：

```text
active_pool_count     -> eligible_etf_count
active_snapshot_count -> eligible_snapshot_count
```

`eligible_etf_count` 来自 `EtfBasicDAO.load_requestability_snapshot(as_of_date)`；`eligible_snapshot_count` 是当前 Redis batch 中命中这些代码的数量。`source_snapshot_count` 等源端字段不改。

读取时点是**每次 `build_etf_rt_daily_health()` API 调用开始时一次**，不是 collector 的每个源请求，也不是每日预生成。两项只表达本次 Health 响应里的业务覆盖率，不改变 provider 请求，不作为 collector 是否发请求的门禁。

必须同步修改：

```text
src/ops/queries/realtime_feed_health_query_service.py
src/ops/schemas/realtime.py
frontend/src/shared/api/realtime-types.ts
frontend/src/pages/ops-realtime-monitor-page.tsx
对应后端与前端测试
```

不保留旧 JSON 字段、Pydantic alias 或前端 fallback。

selector 返回空集合时 Health 仍正常返回，`eligible_etf_count=0`、`eligible_snapshot_count=0`；这表示业务资格集合为空，不得改写成 Redis 不可用，也不得回退到 provider 全量 snapshot 当分母。

### 8.3 监控候选接口

当前 `/api/v1/ops/realtime/etf-monitor/active-etfs` 改为：

```text
GET /api/v1/ops/realtime/etf-monitor/eligible-etfs
```

服务和 DTO 同步改名：

```text
list_active_etfs                  -> list_eligible_etfs
EtfRealtimeMonitorActiveEtfItem  -> EtfRealtimeMonitorEligibleEtfItem
EtfRealtimeMonitorActiveEtfListResponse
                                  -> EtfRealtimeMonitorEligibleEtfListResponse
```

查询从 `requestable_targets_subquery(as_of_date)` 起表，再 outer join 最新 fund daily、最新 share size 和现有监控池。分页、关键词、规模排序逻辑保留。`RawEtfShareSize` 仍直接读取，这是直出存储设计，不是需要迁移的旁路。

读取时点是**每次候选分页 API 请求开始时一次**。服务先固定 `as_of_date`，再构造一次 subquery；总数与分页结果允许执行两条数据库 SQL，但两条 SQL 必须复用同一个 subquery 定义和日期。它决定这次页面可选哪些 ETF，不创建持久化 eligible pool，也不把所有 eligible ETF 自动加入运营监控池。当前可请求集合为空时正常返回 `total=0/items=[]`，不是 500，也不回退旧池。

### 8.4 监控配置与运行时

`ops.etf_realtime_monitor_pool` 保留，它表示运营重点关注对象，不是同步激活池。

目标行为：

1. 新增监控对象，以及把现有对象从 disabled 改为 enabled 时，用 `get_requestable_target()` 校验；保持 disabled 的备注/分组修改允许保存。
2. 新增或修改 ETF scope rule 时同时校验监控池成员和当前可请求资格；group scope rule 不逐代码固化资格。
3. `EtfRealtimeMonitorService.run_after_etf_batch()` 处理前将 enabled monitor pool 与当前可请求集合求交集。
4. 已失效配置即使仍保留在配置表中，也不得参与本批指标计算或产生新告警。
5. 历史 `etf_realtime_alert` 和分钟统计保留，不因主数据变化删除。

第 3 项的读取时点是**每次实时批次进入 `run_after_etf_batch()` 时一次**，本批监控计算期间固定；不是每条指标或每条规则重查 Basic。当前可请求集合为空时，本批次正常 no-op，不做指标计算、不发新告警；返回 `EtfRealtimeMonitorRunResult(status='skipped', evaluated_count=0, alert_count=0, message='eligible ETF set empty')` 供现有 collector 日志输出。不新增 `eligible_etf_count` 字段、TaskRun 记录或其他诊断持久化；provider 的抓取与 Redis 发布仍不受影响。

`run_after_etf_batch()` 当前只读取既有 `ops.etf_realtime_minute_stat` 作为历史基线并生成告警，本身不写分钟统计。独立手工入口 `EtfRealtimeMinuteArchiveService` / `ops-archive-etf-realtime-minute-stats` 已由《ETF 实时成交额异动监控 LLD v1》冻结并安排退场，不属于 P6，也不得为了本阶段继续扩展。仓库内没有该 CLI 的自动调用方；在其正式退场前，运营若手工执行，它仍按 enabled monitor pool 工作。这一已知边界不改变当前 Prod 审计中“不可请求监控配置为 0”的事实。

### 8.5 旧 review 页面删除

旧 ETF 激活池审查能力没有新的业务用途，直接删除：

```text
GET /api/v1/ops/review/etf/active
GET /api/v1/ops/review/etf/active/summary
ops-v21-review-etf-page.tsx
对应路由、导航、schema、共享类型和测试
```

不把它改造成 Basic 浏览页面；用户没有提出新的 Basic 管理 UI。

---

## 9. 下游只读复核门禁

### 9.1 不新增清理实现

本轮 Prod 审计的已批准删除候选为 0，因此明确不新增：

```text
etf_master_alignment_cleanup_service.py
ops-etf-master-alignment-cleanup CLI
audit/apply 模式
事实删除 manifest/候选 CSV
分批 DELETE、断点续跑或恢复逻辑
```

现有 `EtfFundDailyServingCleanupService` 和 `ops-cleanup-etf-fund-daily-serving` 在 P4 与 fund daily 旧门禁一起删除，不改名、不复用，也不保留兼容入口；P8 不再重复处理。

### 9.2 重建后的复核时点

`etf_basic` 完整快照重建并通过 raw/serving 集合验收后，以该次 `source_snapshot_hash` 为基准复跑一次受控只读统计。它是发布验收步骤，不是日常 schedule、产品 API 或可重复删除工具。

| 对象 | 复核项 | 当前结果 |
|---|---|---:|
| `raw_tushare.etf_minute_bar` | 非交易所后缀、交易所冲突、不在当前源端 Basic、早于当前上市日 | 明确删除候选 0；上市日前事实 0 |
| `raw_tushare.etf_sh_cons` | 非 `.SH`、交易所冲突、不在当前源端 Basic、早于当前上市日 | 全部 0 |
| `raw_tushare.etf_sz_cons` | 非 `.SZ`、交易所冲突、不在当前源端 Basic、早于当前上市日 | 全部 0 |
| `core_serving.fund_daily_bar` | 非交易所后缀、交易所冲突、不在当前源端 Basic | 全部 0 |
| `core_serving.fund_daily_bar` | 早于当前 `list_date` | 2,091 行、3 个代码，只报告 |
| `ops.etf_realtime_monitor_pool/rule` | 当前不可请求配置 | 0 |

### 9.3 分类与动作

| 分类 | 动作 |
|---|---|
| `NON_EXCHANGE_ETF_SUFFIX` | 当前为 0；重建后若非零，停止并另立精确一次性方案 |
| `CODE_NOT_IN_ETF_MASTER` | 只报告；代码可能从当前主数据消失，不自动删除历史 |
| `BEFORE_CURRENT_LIST_DATE` | 只报告；可能是上市日后移或代码复用，不自动删除历史 |
| `PENDING_ETF_HAS_FACT` | 只报告，不自动删除 |
| `LISTED_WITHOUT_LIST_DATE_HAS_FACT` | 只报告，不自动删除 |
| `MONITOR_CONFIG_NOT_REQUESTABLE` | 运行时资格门禁阻止继续生效；当前为 0，不建设清理程序 |

`ops.etf_series_active` 的整表 drop 属于激活池 schema 退场，不是本节下游事实清理。

### 9.4 明确保护

以下对象继续保持原边界，不进入 ETF Basic 差集删除：

```text
raw_tushare.fund_daily
raw_tushare.fund_adj
core.fund_adj_factor
raw_tushare.etf_share_size
core_serving.etf_share_size view
ETF index 数据
fund_basic/fund_manager/fund_share 等公募基金域
ops.etf_realtime_alert
ops.etf_realtime_minute_stat
```

复核结果仍为 0 时，本阶段无业务写入并直接结束。若明确旧 `.OF` 身份意外非零，必须停止、报告精确表/代码/主键/行数并等待新的授权；不能在实施时临时补回通用 CLI。

---

## 10. ETF 历史分钟全量对齐

### 10.1 V1 对齐目标与非目标

V1 的目标是：对每个**当前可请求 ETF × Tushare 原生分钟频率**，从该 ETF 当前 `list_date` 起，到指定截止日为止，至少完成一次受控区间请求覆盖，并把源端实际返回写入正式 `raw_tushare.etf_minute_bar`。

V1 不声称以下能力：

1. 不以交易日历推断停牌日一定应有分钟数据。
2. 不检查盘中每一个分钟格是否完整。
3. 不自动补现有最早与最晚数据之间的内部空洞。
4. 不从 `.OF`、其他频率或其他数据集复制数据。

原因是“某交易日零行”既可能是未请求，也可能是停牌或源端本来无数据。没有可靠源端存在性证据时按日补洞，会重复消耗额度且仍不能证明逐 bar 完整。

### 10.2 只读规划服务

新增：

```text
src/ops/services/etf_minute_history_alignment_plan_service.py
```

服务只读取 Basic serving、分钟 raw 和成功的显式 `etf_mins` TaskRun 请求范围，不调用 Tushare、不写业务表、不创建 TaskRun。输入固定为：

```text
alignment_end_date（必须是 `core_serving.trade_calendar` 中不晚于 preview 开始时中国当日的 SSE 开市日）
```

V1 公开 preview 不接受 `as_of_date`、`ts_codes` 或频率子集。Basic 没有历史表，所以调用方不能伪造历史资格日期；本次 `eligibility_as_of` 由服务在开始时用中国时区计算一次并固定。服务用现有 `TradeCalendarDAO.get_latest_open_date('SSE', eligibility_as_of)` 校验上界，并确认输入日期本身是 SSE 开市日；日历缺失或输入无效时返回结构化校验错误，不回退到自然日。对齐对象固定为该 snapshot 中的全部当前可请求 ETF，频率固定为 `1min/5min/15min/30min/60min`。局部样本只在测试 fixture 中构造，不增加生产 CLI 分支。

服务加载一次 `EtfRequestabilitySnapshot`，再按 `ts_code + freq` 聚合：

```text
desired_interval = [list_date, alignment_end_date]
raw_observed_interval = [MIN(DATE(trade_time)), MAX(DATE(trade_time))]
successful_explicit_task_intervals = 已成功、明确携带 ts_code/freq/start/end 的 etf_mins TaskRun
covered_intervals = raw_observed_interval 与 successful_explicit_task_intervals 的并集
effective_covered_intervals = covered_intervals 分别与 desired_interval 求交、丢弃空交集后再合并
missing_prefix = list_date 到第一个 effective covered interval 之前
missing_suffix = 最后一个 effective covered interval 之后到 alignment_end_date
```

prefix/suffix 只基于 `effective_covered_intervals` 计算；完全落在当前 `list_date` 之前的代码复用旧历史不算覆盖。若交集为空，则整个 `desired_interval` 都是待请求范围。只生成 prefix/suffix；有效 covered interval 之间的内部空洞列入 `interior_gap_not_audited=true`，不生成请求。没有 raw 的代码从 `list_date` 开始。显式成功但源端零行的 TaskRun 区间仍算“已请求覆盖”，避免下次 preview 重复请求空窗口。

Prod raw 当前约 6,584 万行。P9A 的物理读取固定为：

1. 在 `SET TRANSACTION READ ONLY` 的事务内执行，并设置 `SET LOCAL statement_timeout = '60s'`。
2. Basic targets、raw `ts_code + freq -> MIN/MAX(trade_time)`、成功 TaskRun 请求范围分别使用集合查询；禁止在 ETF×频率循环内发 ORM/SQL 查询。
3. raw 查询只投影目标代码、五个频率和 `MIN/MAX(trade_time)`，利用现有主键 `(ts_code, freq, trade_time)` 与现有分钟索引；P9A 不新增索引或迁移。
4. 首次连接 Prod 前先查看 `EXPLAIN` 计划，再运行受 60 秒限制的真实 preview，并记录 SQL 次数、数据库查询耗时、总耗时和超时结果。
5. 若超时、出现不可接受的全表/分区扫描，或真实执行影响生产稳定性，P9A 立即停止。索引或物理模型调整必须另行审计和拍板，不能为了完成 preview 偷带 schema 变更。

成功 TaskRun 只有在 `resource_key='etf_mins'`、最终状态成功、单个 `ts_code`、非空合法频率集合与 `start_date/end_date` 均可无歧义还原时才进入覆盖；多频率 TaskRun 按每个频率分别记入同一请求区间。池式旧任务、失败任务、参数不完整任务均不猜测覆盖范围。

每个 prefix/suffix 调用 P3 已抽取的 `build_etf_minute_windows()` 计算 unit 数。alignment service 自己已从同一份 snapshot 取得并应用 `list_date`，不为每个 action 再实例化 `DatasetActionResolver`，也不复制 2/12/36/72/120 月切窗算法。

当同一 `ts_code` 的多个频率具有完全相同的 `start_date/end_date` 时，preview 将它们合并为一个 action，利用现有 `etf_mins` 多频率 filter 在一个 TaskRun 内生成各自 unit；不同日期范围不得为减少 TaskRun 而合并。action 按 `ts_code/start_date/end_date/frequencies` 稳定排序，保证重复 preview 可对账。

### 10.3 `alignment_plan` 契约与额度

输出统一命名为 `alignment_plan`，它是请求计划，不是下游事实删除 manifest。内存对象与可选 JSON 输出包含：

```text
plan_id, plan_content_hash and generated_at
request_target_hash and eligibility_as_of
alignment_end_date
requestable_etf_count and excluded_reason_counts
per frequency: action_count, planned_unit_count, source_request_lower_bound, page_request_upper_bound
raw-covered / successful-empty-covered / missing-prefix / missing-suffix counts
per action: ts_code, frequencies, start_date, end_date, planned_unit_count
planned_action_count
planned_unit_count
source_request_lower_bound
page_request_upper_bound
interior_gap_not_audited=true
```

`request_target_hash` 只对本次 snapshot 中按 `ts_code` 排序后的 `(ts_code, list_date, exchange)` target 投影计算规范 SHA-256，日期序列化为 ISO `YYYY-MM-DD`。`eligibility_as_of` 单独作为计划元数据，不强制跨日提交失效；如果日期推进使未来上市 ETF 进入可请求集合，target 投影本身会变化并导致 hash 不一致。名称、管理人、托管人、费率等不影响请求对象或上市日的字段不得使计划失效。

不新增数据库 plan 表。只读 CLI 明确为：

```text
ops-preview-etf-minute-alignment
```

默认把摘要输出到终端；只有运营显式传 `--output <json path>` 时才写 JSON 文件。该文件不包含 DELETE、数据库备份或源端响应数据。

当前 `page_limit=8000`、`max_source_rows_per_unit=24000`。每个 unit 至少发一次请求；分页需要一个终止短页/空页，因此单 unit 请求上界按 4 次计算：

```text
source_request_lower_bound = planned_unit_count
page_request_upper_bound = planned_unit_count * 4
```

不在 preview 中伪造“预计总耗时”。当前 Tushare client 对 `etf_mins` 有 endpoint 级限速，实际墙钟还受 worker 排队、并发、网络、重试、归一化和入库影响；仅靠 unit 数不能给出可信耗时。preview 只展示可对账的请求上下界；执行第一个已批准批次后，再用真实 `request_count` 和实际耗时反馈后续批次。实际执行后必须以 TaskRun 真实 request count 对账。

### 10.4 Preview 规模门禁与 TaskRun 提交

P9 必须分成两个可独立停止的子阶段：

1. **P9A 只实现 preview**：完成只读 service、CLI、action 合并、unit/请求上下界测算和测试；不实现 submit 入口。
2. **P9B 需要规模拍板**：用 P9A 连接 Prod DB 做只读计算，输出真实 `planned_action_count/planned_unit_count/request bounds`，同时列出 action 按 ETF 和频率的分布；不访问 Tushare。用户确认 TaskRun 数量可接受并明确选择首批 `batch-size` 后，才允许继续实现 submit；LLD 不凭空计算“推荐批次”。如果规模不可接受，停止并重新设计任务分组，不得只靠调小 `batch-size` 掩盖过量 TaskRun。

P9A 的只读规模报告是 P9B 的硬前置，不在 LLD 里凭经验预设一个永久阈值。

P9B 获得确认后才新增独立提交入口：

```text
ops-submit-etf-minute-alignment \
  --plan <json path> \
  --confirm-plan-hash <plan_content_hash> \
  --batch-size <positive integer>
```

`plan_content_hash` 使用去掉自身字段后的规范 JSON 计算 SHA-256：UTF-8、对象 key 排序、紧凑分隔符、日期使用 ISO 字符串、频率按固定原生顺序。提交时先复算文件内容再比较，防止 preview 后文件被改。`--batch-size` 必填且只控制本次最多创建多少个 TaskRun，不落入 Settings 或数据库配置。

提交入口只创建现有正式 `etf_mins` range TaskRun，不直接调用 connector、planner executor 或 writer。固定门禁：

1. 用户必须在看到 action/unit/request 上下界后单独授权执行；P11 的生产切换授权不包含本动作。
2. alignment submit service 在自己的数据库事务内获取专用 PostgreSQL transaction advisory lock；该锁和以下 open-run 检查不下沉到共享 `TaskRunCommandService`。
3. 持锁后若存在任意 `resource_key='etf_mins'` 且状态为 `queued/running/canceling` 的 TaskRun，整次 submit 返回 conflict，不创建新任务。运营须等待现有分钟任务结束后重新 preview/submit，避免自动任务或上一批与本批重叠。
4. 重新固定当前中国日期、加载一次全市场 requestability snapshot，构造 `ts_code -> target` map 并计算 `request_target_hash`；与 plan 不一致则整批拒绝并要求重新 preview。
5. 逐 action 只查该内存 map，验证代码仍存在且 `start_date >= 当前 list_date`；不得逐 action 重复查 Basic。
6. 重新读取 raw 与成功 TaskRun 覆盖；已经不缺的 action 跳过并计数。
7. 只选择 plan 中前 `batch-size` 个仍缺失 action；剩余 action 留给下一次显式提交，不新增长期配置项。
8. 每个 action 通过 `TaskRunCommandService.stage_task_run()` 暂存一个现有 `etf_mins` range TaskRun，filters 为单 `ts_code` 和该 action 的 `frequencies` 列表，不创建新 TaskRun 类型或直接 unit 提交契约。
9. 一批 action 全部 stage 成功后只提交一次数据库事务；任一创建失败则整批 rollback，不留下部分 queued TaskRun。提交结果返回创建的 TaskRun IDs 与因已有覆盖跳过的 action 数。
10. 请求、分页、限流、重试、幂等写入和观测全部走正式 `etf_mins` 主链。

提交 CLI 不具备事实 DELETE、Basic 重建或激活池迁移能力。

### 10.5 日常主数据变化

本需求不新增 Basic 历史表，也不新增自动消费 Basic diff 的 schedule。日常 Basic 发布只改变下一次 selector 结果：

| 变化 | 日常动作 |
|---|---|
| 新增 `.SH/.SZ` 且已可请求 | 下一次 preview 自动发现无 raw/无成功覆盖，从 `list_date` 生成 prefix/suffix |
| `P -> L` 或空 `list_date -> 有效日期` | 同上 |
| `L -> D` | selector 停止新请求；不删除历史 |
| 代码从当前 Basic 消失 | selector 停止新请求并由 Basic diff 报告；不删除历史 |
| `list_date` 变晚 | 新 preview 使用新下界；不追溯删除历史 |

Basic TaskRun 诊断只用于审计变化，不自动创建分钟 TaskRun。任何额度消耗都必须经过 preview 和独立提交授权。

---

## 11. 激活池退场全量清单

### 11.1 直接删除

| 归属阶段 | 层 | 当前文件/对象 | 唯一动作 |
|---|---|---|---|
| P4 | Cleanup | `src/ops/services/etf_fund_daily_serving_cleanup_service.py` 与 `ops-cleanup-etf-fund-daily-serving` | 与 fund daily 旧门禁一起删除，不提供替代清理入口 |
| P7 | Review | `review_center_query_service.py`、`review_center.py`、`schemas/review_center.py`、`schemas/__init__.py` 中 ETF active 类型/方法/路由 | 只删除 ETF active 部分，保留 review center 其他能力 |
| P7 | Frontend review | `ops-v21-review-etf-page*`、router、shell、shared types 中旧页面/路由/导航/类型 | 删除 ETF active 部分 |
| P8 | Migration | `20260618_000117_add_etf_series_active.py` | 保留历史迁移文件；新增迁移 drop 当前表 |
| P8 | ORM | `src/ops/models/ops/etf_series_active.py` | 删除 |
| P8 | 注册 | `src/ops/models/ops/__init__.py`、`src/app/model_registry.py` | 删除 ETF model 注册 |
| P8 | DAO | `src/foundation/dao/etf_series_active_dao.py`、`src/foundation/dao/factory.py` 中的 ETF 属性 | 删除；必须晚于消费者迁移 |
| P8 | Contract | `src/foundation/kernel/contracts/etf_series_active_store.py` | 删除 |
| P8 | Adapter | `src/ops/etf_series_active_store_adapter.py` | 删除 |
| P8 | Seed | `src/ops/services/etf_series_active_seed_service.py` | 删除 |
| P8 | CLI | `src/cli.py`、`src/cli_parts/ops_handlers.py` 中 `ops-seed-etf-series-active` 及 handler/import | 删除 |
| 各消费阶段 + P8 | Tests | resolver/writer/Health/monitor 测试由各迁移阶段重写；model/DAO/seed/CLI 独立测试由 P8 删除 | 不把旧测试集中拖到最后才处理 |

历史 Alembic 文件保留是数据库迁移链要求，不算运行时兼容路径。历史设计文档保留作证据，但必须标注已被本方案和本 LLD 取代。

当前测试引用的 `reports/etf_series_active_seed_1395_20260617.csv` 和 `reports/etf_series_active_fund_daily_accepted_gaps_31_20260617.csv` 在本轮工作区中实际不存在；实施时只删除其测试和代码引用，不编造“已删除 seed 文件”的交付记录。

### 11.2 改写消费者

| 当前消费者 | 当前读法 | 目标读法 |
|---|---|---|
| `_resolve_etf_mins_targets` | `etf_mins` resource | Basic 当前可请求 + list_date |
| sh/sz cons target resolver | 各自 resource | Basic 当前可请求 + 交易所 |
| fund daily writer | `fund_daily` resource | Basic 当前可请求 map |
| realtime feed health | `etf_rt_daily` resource | Basic 当前可请求 codes |
| realtime monitor candidate | `EtfSeriesActive` 起表 | Basic requestable subquery 起表 |
| realtime monitor runtime | enabled monitor pool，不做 Basic 交集 | monitor pool ∩ 当前可请求 |

### 11.3 明确保留

以下名字或机制与 ETF 激活池不同，禁止误删：

```text
ops.index_series_active
IndexSeriesActiveDAO
指数 planner 的 list_active_codes
ETF 实时业务监控池 ops.etf_realtime_monitor_pool
ETF 实时 provider 固定通配符请求
```

`etf_rt_min` 当前不在资源白名单和已落地运行时消费者中，本次不虚构该 resource 的删除或迁移代码。

### 11.4 静态清零命令范围

P7 结束时先做“业务消费者零引用”检查；P8 删除基础设施和旧测试后，再执行分层清零。不能把“字符串绝对为 0”写成测试层要求，因为新 migration 验证和负向 guardrail 必须提到被删除对象：

```text
EtfSeriesActive
etf_series_active
ops_etf_series_active
ops-seed-etf-series-active
/ops/review/etf/active
active_pool_count
active_snapshot_count
/active-etfs
```

分层标准：

1. `src/**`、`frontend/src/**` 和当前配置：上述旧名必须为 0。
2. `tests/**`：不得 import、创建、seed、mock 或调用旧能力；只允许专门的 retirement/migration 负向测试在字符串断言中提到旧名。
3. `alembic/**`：历史建表 migration 与新 drop migration 允许出现表名。
4. 明确标注为历史/superseded 的文档允许保留旧名。
5. 数据库验收要求 `to_regclass('ops.etf_series_active') IS NULL`。

---

## 12. Alembic 与无兼容发布

### 12.1 迁移内容

实现时新建唯一迁移：

```text
upgrade:
  DROP TABLE ops.etf_series_active

downgrade:
  raise RuntimeError("ops.etf_series_active retirement is irreversible")
```

由 drop table 自动删除其索引。迁移不删除任何 ETF 下游事实，本方案也没有下游事实删除 CLI。迁移前重新确认真实 head，禁止把本 LLD 记录的 `20260828_000155` 直接复制为未来 `down_revision`。

### 12.2 发布顺序

本次不支持旧进程与新 schema 混跑，不做双读：

1. 完成新 selector、planner、writer、实时消费者、前端和测试。
2. 在候选环境完成静态清零与 migration upgrade 验证。
3. 生产维护窗口暂停相关 schedule、worker、ETF realtime collector 和 Web 进程。
4. 确认 `etf_basic/etf_mins/etf_sh_cons/etf_sz_cons/fund_daily` 没有 `queued/running/canceling` TaskRun。
5. 部署完整新代码，但进程保持停止。
6. 用新代码对应的 Alembic 执行 drop-table migration。
7. 验证表不存在、旧引用静态为 0、旧 Basic serving 仍可读。
8. 只启动执行 Basic TaskRun 所需的 Web/worker，realtime collector 与所有相关 schedule 继续暂停。
9. 立即执行 `etf_basic` 完整快照重建并完成 raw/serving 验收。
10. 启动 realtime 和其余 Web 进程，冒烟验证 planner、fund daily 两阶段写入、health、eligible candidates 和 monitor runtime。
11. 恢复 schedule。

任何旧进程尚未停止、引用清零失败或 migration head 不唯一，都必须停止发布。

### 12.3 回滚边界

代码与 drop-table migration 是不可逆退场：

1. migration 前可以停止发布并继续运行旧版本。
2. migration 后不支持回滚到依赖激活池的旧版本。
3. 不重建空的 `ops.etf_series_active`，也不从 seed CSV 恢复。
4. 出现问题只能前向修复新 Basic selector/消费者。

这与“不保留兼容路径”的已确认口径一致。

---

## 13. 逐步开发流程

每一步都遵守“先完成当前阶段测试和差异审计，再进入下一阶段”。不得把删除表提前到消费者切换之前。

### P0：开发前复核与基线冻结

动作：

1. 同步 CodeGraph 并确认状态。
2. 重新跑本 LLD 第 11.4 节引用搜索，保存当前引用基线。
3. 重新确认 Alembic heads/current。
4. 只读记录 prod Basic、六类下游复核对象和保护对象的行数及分类统计。
5. 用 Tushare MCP 做一个最小 `etf_basic` 字段样本；除非源文档或行为变化，不重复全量耗额度。

停止条件：代码链、源字段、真实 migration head 或生产物理表与 LLD 不一致。

#### P0 执行记录（2026-08-28）

P0 严格限定为同步索引、静态搜索、迁移状态检查、Prod 白名单只读查询和一次最小源端抽样；没有修改运行时代码、数据库、Lake、配置或 schedule，也没有进入 P1。

**CodeGraph 与引用基线**

`codegraph sync/status` 完成并在 P0 收尾时复核后，索引为 2,798 个文件、49,327 个节点、125,393 条边。相较 LLD 编写时的数量变化来自当前工作区其他文件变化；对 `EtfSeriesActive`、`EtfSeriesActiveDAO`、`EtfSeriesActiveStore`、`EtfFundDailyServingCleanupService` 重新执行 impact 后，分别得到 18、13、10、14 个受影响符号，调用链仍落在本 LLD 已列出的 model、DAO、contract、adapter、seed、CLI、review、health、实时监控和测试范围，没有发现新的 ETF 池消费者。

第 11.4 节八组旧引用在 `src/**`、`frontend/src/**`、`tests/**` 和当前配置中的实施前基线为：

| 精确字符串 | 匹配数 | 文件数 |
|---|---:|---:|
| `EtfSeriesActive` | 121 | 19 |
| `etf_series_active` | 115 | 31 |
| `ops_etf_series_active` | 8 | 3 |
| `ops-seed-etf-series-active` | 10 | 3 |
| `/ops/review/etf/active` | 20 | 4 |
| `active_pool_count` | 7 | 6 |
| `active_snapshot_count` | 9 | 6 |
| `/active-etfs` | 8 | 4 |

当前配置文件的上述引用均为 0。该表是 P8 静态清零验收的对照基线，不代表 P0 已删除任何引用。

**Prod Basic 与旧激活池基线**

所有查询均限定在明确白名单内，以只读事务执行；未执行 DDL、DML 或数据导出。`raw_tushare.etf_basic` 与 `core_serving.etf_basic` 当前行数和以下分类统计一致：

| 指标 | 数量 |
|---|---:|
| 总行数 / distinct code | 3,405 / 3,405 |
| `.OF` | 1,585 |
| 未知后缀 | 0 |
| `L / P / D` | 3,089 / 62 / 254 |
| `list_date IS NULL` | 71 |
| 后缀与 `exchange` 冲突 | 0 |
| 截至当日当前可请求 `.SH/.SZ` | 1,647 |

按后缀和状态拆分：`.OF` 为 `L=1,437`（其中 5 个无上市日）、`P=23`（其中 22 个无上市日）、`D=125`；`.SH` 为 `L=924`（其中 3 个无上市日）、`P=23`（全部无上市日）、`D=82`；`.SZ` 为 `L=728`（其中 2 个无上市日）、`P=16`（全部无上市日）、`D=47`。

旧 `ops.etf_series_active` 共 5,708 行：`etf_mins=1,395`、`etf_rt_daily=1,395`、`etf_sh_cons=803`、`etf_sz_cons=720`、`fund_daily=1,395`，非交易所后缀均为 0。该结果只用于退场前对账，不改变“直接删除旧池、不迁移池内容”的既定方案。

**六类下游复核对象**

本次 P0 按当前 Prod Basic 重新分类；它不是源端完整快照重建后的最终验收，最终仍须按第 9.2 节在 Basic 重建后复跑。

| 对象 | 行数 | 代码数 | 非目标后缀/交易所冲突/不在当前 Prod Basic | 早于当前 `list_date` | 其他报告项 |
|---|---:|---:|---:|---:|---:|
| `raw_tushare.etf_minute_bar` | 67,423,145 | 1,395 | 0 / 0 / 0 | 0 | `P` 或 `L+空日期` 均为 0 |
| `raw_tushare.etf_sh_cons` | 5,675,323 | 803 | 0 / 0 / 0 | 0 | `P` 或 `L+空日期` 均为 0 |
| `raw_tushare.etf_sz_cons` | 11,567,504 | 720 | 0 / 0 / 0 | 0 | `P` 或 `L+空日期` 均为 0 |
| `core_serving.fund_daily_bar` | 1,180,869 | 1,395 | 0 / 0 / 0 | 2,091 行 / 3 个代码 | `P` 或 `L+空日期` 均为 0 |
| `ops.etf_realtime_monitor_pool` | 3 | 3 | 当前不可请求配置 0 | - | - |
| `ops.etf_realtime_monitor_rule` | 0 条 ETF 规则 | 0 | 无效规则 0 | - | - |

`fund_daily_bar` 的 2,091 行继续按已拍板口径只报告、不删除；其余明确删除候选仍为 0，因此不恢复通用清理 CLI/service 设计。

**保护对象基线**

| 保护对象 | 当前行数 |
|---|---:|
| `raw_tushare.fund_daily` | 2,608,675 |
| `raw_tushare.fund_adj` | 2,792,339 |
| `core.fund_adj_factor` | 2,792,339 |
| `raw_tushare.etf_share_size` | 234,042 |
| `core_serving.etf_share_size`（直出 view） | 234,042 |
| `raw_tushare.etf_index` | 1,524 |
| `core_serving.etf_index` | 1,524 |
| `core_serving.fund_basic_current` | 32,412 |
| `core_serving.fund_manager_current` | 84,357 |
| `core_serving.fund_share_current` | 2,572,451 |
| `ops.etf_realtime_alert` | 0 |
| `ops.etf_realtime_minute_stat` | 0 |

21 个白名单对象均存在，表/view 类型和主键与本 LLD 一致；`core_serving.etf_share_size` 仍是 raw 直出 view，没有发现需要新建 core 或迁移 view 的理由。

**最小源端抽样与 P0 结论**

仅对 `510300.SH` 发起一次 `etf_basic` 请求，并显式指定本 LLD 的 14 个字段。源端完整返回 14 个字段，其中 `list_status=L`、`setup_date=20120504`、`list_date=20120528`、`exchange=SH`，与第 2.5 节字段契约一致；没有重复发起源端全量请求。

P0 五项动作均已完成。代码链、源字段和 Prod 物理对象没有发现与 LLD 冲突；P0 当时的唯一停止项是连接数据库落后于代码 head。该历史门禁已在 P1 开发前按第 2.6 节重新实测并解除。

### P1：ETF Basic 快照发布

编码：

1. 收口 DatasetDefinition 和 request builder。
2. 新增 snapshot 校验/hash/diff 纯函数。
3. 新增专用 writer dispatch 和事务内对账。
4. 扩展 `WriteResult` 与 ingestion diagnostics。
5. 在 Ops TaskRun 创建侧增加同数据集 open-run 冲突检查。

测试：完整 `.SH/.SZ/.OF` 批次、旧代码消失、未知状态、未知后缀、交易所不一致、重复主键、reject、空结果、事务中途失败、并发锁、幂等重跑。

完成门禁：任何失败都不能改变旧 raw/serving；成功后集合和 hash 不变量成立。

#### P1 执行记录（2026-08-28）

P1 严格限定在 ETF Basic 快照发布链路，未进入 P2 选择器、下游 planner、旧激活池删除、实时契约或前端改造。

**CodeGraph 与消费者审计**

P1 开发前 `codegraph status` 为 up to date，索引包含 2,798 个文件、49,327 个节点和 125,393 条边。本阶段对 `DatasetWriter` / `WriteResult` / `TaskRunCommandService` 执行 query/impact，影响面覆盖 writer 分派、executor 诊断、TaskRun API/手工任务/schedule/retry 共用创建入口和现有测试。`DatasetDefinition` 消费者还核对了 registry、manual actions、catalog、resolver/planner、schedule capability、freshness 与 dataset card；没有发现需要提前带入 P2 的契约。

**实现结果**

1. `etf_basic` Definition 已收口为无过滤、单并发、`buffer_all` 的 5,000 行分页快照；请求构造器固定返回空业务参数，并拒绝 6 个旧筛选参数残留。
2. 新增 14 业务字段的纯函数校验、规范化 SHA-256 hash 和 diff；校验状态、后缀、交易所、空上市日期统计与主键唯一性。
3. 新增 `raw_etf_basic_snapshot_replace` 专用 writer；PostgreSQL transaction advisory lock、raw 全量、serving 仅 `.SH/.SZ`、两表删除/写入/flush/集合/hash 对账均在 executor 的同一 unit 事务内完成，DAO 不 commit。
4. `WriteResult.persistence_diagnostics` 已打通现有 TaskRun JSON，代码样本最多 20 个，没有新增 TaskRun 列。
5. `TaskRunCommandService.stage_task_run()` 在全部共用创建入口前增加 `etf_basic` open-run 检查；第二个 `queued/running/canceling` maintain 任务会返回 409，PostgreSQL 创建侧也使用 transaction advisory lock。

**测试与真实只读验收**

P1 新增和直接 API 用例 34 个全部通过；Definition/registry、observed snapshot、executor progress、action catalog、manual actions、TaskRun、news concurrency 与 runtime guardrail 的扩展回归 170 个全部通过。测试覆盖固定 14 字段、无筛选请求、`.SH/.SZ/.OF`、旧代码消失、状态/后缀/交易所异常、重复主键、reject、空结果、事务中途失败、写后对账失败、两层并发锁、单次 commit、诊断上限和幂等重跑。

扩大到 `tests/`（排除当前无法收集的 `tests/lake_console`）后，结果为 2,279 passed、10 skipped、7 failed。7 个失败均不在 P1 改动链路：3 个是既有架构/文档门禁与当前并行改动不一致，1 个是既有 CLI reporter 行为，2 个是仓库缺少旧激活池历史 CSV，1 个仍硬编码旧 Alembic head `20260824_000150`；P1 新增及相关回归没有失败。全量测试直接收集还会被 `tests/lake_console` 的缺失旧模块和同名测试模块冲突阻断，P1 不越界修复这些问题。

Prod 只读输入严格限定为 `raw_tushare.etf_basic` 和 `core_serving.etf_basic` 的 14 个业务字段。当前两表均为 3,405 行，业务 hash 均为 `39957b8f493a81b9de4e43f14534191f519646678df2af83f702aa812b655d7b`，现有 raw 能通过新状态、后缀、交易所和主键校验。按新 serving 规则从当前 raw 投影得到 1,820 行；现有 serving 相比投影只多 1,585 个 `.OF`，没有 `.SH/.SZ` 缺失或内容差异。该数据仅是生产重建前基线；P1 未请求源端全量、未写生产表、未触发 schedule。

P1 完成门禁已满足：成功路径的 raw/serving 集合和 hash 不变量成立；空结果、拒绝行、校验失败、中途写失败与对账失败均不能改变事务前的旧快照。

### P2：统一 Basic selector（已完成）

前置门禁：用户已在 2026-08-28 明确要求按重新基线后的 LLD 推进 P2，本阶段授权成立。

范围只限 Foundation selector：

1. 在 `etf_basic_dao.py` 新增 `EtfRequestTarget`、`EtfRequestabilitySnapshot` 和第 4 节三个方法。
2. 用唯一 predicate builder 实现状态、上市日、后缀、exchange 规则；snapshot 分类为互斥计数。
3. 删除无运行时消费者的 `get_active_etfs()/get_fund_daily_candidates()`。
4. **不修改**已经存在的 `DAOFactory.etf_basic`。
5. **不删除** `DAOFactory.etf_series_active`、旧 DAO、model、contract、adapter 或表。

测试：L/P/D、空日期、未来上市、`.OF`、交易所冲突、SH/SZ scope、非法 exchange、代码规范化、排序、排除计数对账、subquery 列契约，以及同一 `as_of_date/exchange` 下 snapshot target codes 与 subquery codes 完全一致。

完成门禁：P2 可以在所有旧消费者仍正常工作的情况下独立合入；资格 SQL 只存在于 DAO；本阶段没有 planner/writer/Ops/frontend 行为变化。

**P2 执行记录**

1. `EtfBasicDAO` 新增不可变的 `EtfRequestTarget`、`EtfRequestabilitySnapshot`，以及 snapshot、单代码 target、可复用 subquery 三个公共方法；三个方法共同复用 exchange/代码规范化和唯一资格 predicate。
2. snapshot 只执行一次 Serving 查询，按规定优先级产生互斥排除计数；全市场统计包含 `.OF` 排除项，SH/SZ 统计只按对应代码后缀划定作用域。snapshot targets 和 subquery 在相同 `as_of_date/exchange` 下通过代码集合一致性测试。
3. 删除了没有运行时消费者且语义不明确的 `get_active_etfs()`、`get_fund_daily_candidates()`；`fund_daily` 现行测试中的同名 mock 只用于证明 writer 不会回退该旧方法，不是运行时消费者，留到 P4 随 writer 测试一起迁移。
4. 按阶段边界没有修改 `DAOFactory.etf_basic`，也没有删除 `DAOFactory.etf_series_active`、旧 DAO/model/contract/adapter/table；planner、writer、Ops、API 和前端均未改动。
5. 开发前 CodeGraph 索引为 up to date，包含 2,814 个文件、49,646 个节点和 126,123 条边。query/impact 与精确代码搜索覆盖 `EtfBasicDAO`、`DAOFactory`、旧方法、旧激活池消费者和相关测试；确认 P2 可独立完成，旧池运行时消费者必须留给 P3-P8 逐阶段迁移。
6. 新 selector 与 DAOFactory 定向测试 21 个全部通过；旧激活池 DAO、`fund_daily` 现行写入链和子系统依赖矩阵扩展回归 12 个全部通过；相关 Ruff 检查通过。测试覆盖 L/P/D、空/未来上市日期、`.OF`、交易所冲突、作用域、非法 exchange、规范化、排序、不可变性、排除计数对账、subquery 列契约和两条选择路径一致性。

P2 完成门禁已满足：统一资格 SQL 只在 `EtfBasicDAO`，旧消费者仍可运行。本阶段没有数据库、源端或生产写入，也没有开始 P3。

### P3：三个代码驱动 planner（已完成）

代码白名单：

```text
src/foundation/datasets/definitions/market_fund.py
src/foundation/ingestion/unit_planner.py
src/foundation/ingestion/etf_minute_windows.py
src/foundation/ingestion/codebook.py
tests/test_dataset_definition_registry.py
tests/test_dataset_action_resolver.py
tests/test_etf_mins_dataset.py
```

若实现发现必须修改白名单外的共享 resolver、execution plan、Ops、API 或 writer，立即停止并重新审计，不得顺手扩范围。

编码：

1. Definition 保留 `universe_policy='pool'`，只把 universe source 从 `ops_etf_series_active + resource` 改为无 resource 的 `core_serving_etf_basic`；不新增共享 policy 或伪资源名。
2. 三个 target resolver 改用 `EtfRequestTarget`。
3. 上市日裁剪移到切窗前。
4. 抽取 `etf_mins` 纯切窗函数，正式 planner 与后续 alignment preview 共用。
5. 只新增 `etf_not_requestable/window_before_list_date` 两个错误码并同步 codebook 版本；空集合复用现有 `universe_empty`。增加 unit 级进度上下文，不新增 plan/TaskRun 汇总诊断。
6. 自动请求每次 plan 只调用一次 snapshot；显式单代码每次 plan 只调用一次 `get_requestable_target()` 且不调用 snapshot。
7. 保护所有指数池 planner 不变。

测试：自动全集、自动全部被上市日裁剪后的 0-unit 正常完成且源请求为 0、显式单代码、SH/SZ 限制、P/D/L-null/未来上市、point 越界、range 部分重叠、range 全部早于上市日、每个频率的纯切窗边界、planner 与纯函数的窗口结果一致，以及“自动 snapshot 一次 / 显式 target 一次且 snapshot 零次”。

完成门禁：生成的每个源请求起点都不早于 `list_date`；旧 ETF resource 引用从 DatasetDefinition 与 Foundation planner 清零；`DAOFactory.etf_series_active` 仍可被尚未迁移的 writer/Ops 使用。

**P3 执行记录**

1. `etf_mins/etf_sh_cons/etf_sz_cons` 保留 `universe_policy='pool'` 的对象展开形状，universe source 统一改为无 `resource` 的 `core_serving_etf_basic`；私有 Definition helper 只校验该形状，不读数据库，没有新增共享 policy 或伪 resource。
2. 三个 builder 共用 P2 的 `EtfRequestTarget`：自动请求在一次 plan 内只加载一份 ALL/SH/SZ snapshot，显式单代码只查询一次 target 且不加载全市场 snapshot。空资格集合继续使用 `universe_empty`，未回退旧池、seed 或代码后缀放行。
3. 所有请求先计算 `effective_start=max(requested_start,list_date)`，再执行分钟自然月、沪市半年或深市自然月切窗。自动 target 的窗口全早于上市日时直接不生成 unit，全部被裁后沿用现有 0-unit 成功语义且源请求为 0；显式请求分别用 `etf_not_requestable` 和 `window_before_list_date` 报错。
4. 只有真实生成的 unit 增加 `eligibility_as_of/master_list_date/requested_start_date/effective_start_date`；没有新增跳过统计、plan/TaskRun 汇总诊断、Ops 契约或写入逻辑。
5. 新增 ETF 分钟专用纯函数模块，唯一保存 1/5/15/30/60 分钟对应的 2/12/36/72/120 个月规则；`unit_planner.py` 中的旧常量和旧函数已删除，指数 planner 未改动。
6. 开发前 CodeGraph 索引为 up to date，覆盖 2,815 个文件、49,687 个节点和 126,215 条边；查询与 impact 覆盖 `DatasetUnitPlanner`、`DatasetPlanningDefinition`、三个 ETF builder、DAO 选择器、resolver/dispatcher/manual action 和相关测试。实现后同步索引，最终为 2,816 个文件、49,716 个节点和 126,302 条边，状态仍为 up to date。
7. 本地 Tushare 文档复核了 ETF 历史分钟、沪市申赎清单和深市持仓组合的日期/分页/字段契约；同日使用 Tushare MCP 各执行一个最小只读样本请求，结果与现有 request builder 一致，因此 P3 没有修改源请求参数或字段契约。
8. 目标 Ruff 检查通过；Definition/planner/minute 定向测试 209 个全部通过；扩展至 Basic DAO、旧池 DAO、申赎模型、代码本、运行时注册表和子系统边界的 240 个测试全部通过，另外 20 个 Basic 快照 writer 与 `fund_daily` 旧池 writer 阶段边界测试全部通过，Definition lint 通过。扩展回归只有旧 SQLite date/datetime adapter 的 15 个弃用警告，无失败。

P3 完成门禁已满足：实际 unit 的请求起点不早于 `list_date`，DatasetDefinition 与 Foundation planner 对三个旧 ETF resource 的引用已清零，旧 `DAOFactory.etf_series_active` 及其他消费者仍保留给 P4-P8 逐阶段迁移。本阶段没有生产数据库、Tushare 业务数据或其他外部状态写入。

### P4：`fund_daily` 两阶段发布（已完成）

编码：

1. 新增 `raw_then_serving` commit policy 的 linter 白名单。
2. 拆 raw/serving writer phase。
3. executor 增加两个明确提交点，以及“Raw 已提交、Serving 未提交”的分层诊断；这不是 partial success。
4. serving 接统一 selector 与 `trade_date >= list_date`。
5. 删除旧 active-pool writer helper。
6. 在本阶段唯一一次删除旧 `EtfFundDailyServingCleanupService`、`ops-cleanup-etf-fund-daily-serving` 及其测试/导出；不在 P8 重复处理。

测试：全市场 raw、ETF serving、LOF/REIT 只进 raw、上市日前只进 raw、selector 空、selector 异常、serving upsert 异常、raw upsert 异常、重试幂等、显式 ts_code 不扇出。

完成门禁：selector/serving 失败时 raw 已提交且 TaskRun 失败；不得出现 raw 被回滚或 serving 假成功；`fund_daily` 与 cleanup 对旧池引用清零，其他未迁移消费者仍可运行。

#### P4 执行记录（2026-08-28）

1. `fund_daily` Definition 已改为 `raw_fund_daily_etf_serving_publish` 和 `raw_then_serving`；linter 只对白名单中的 `fund_daily` 专用 write path 放行，其他数据集不能复用该提交策略。
2. `DatasetWriter` 已拆出只写不提交的 `write_raw_phase()` 与 `write_serving_phase()`；Raw 保存源端完整返回，Serving 每个发布阶段只加载一次固定执行日的 Basic snapshot，并按 `trade_date >= list_date` 发布。未发布行只进入 `CODE_NOT_REQUESTABLE_AT_PUBLISH/BEFORE_CURRENT_LIST_DATE` 统计，不作为 normalizer reject。
3. `IngestionExecutor` 在每个任务开始时固定一次中国自然日；每个 unit 先提交 Raw，再执行 selector/Serving 并提交，分层行数与排除原因在多 unit 任务中按任务累计。selector 空、selector 查询异常、Serving upsert/commit 异常统一抛 `fund_daily_serving_publish_failed`，保留已提交 Raw，unit/TaskRun 失败，顶层 `rows_written/rows_committed` 仍只表示 Serving。
4. 已删除旧 active-pool writer helper、`EtfFundDailyServingCleanupService`、`ops-cleanup-etf-fund-daily-serving` CLI、handler 和两组专用测试；没有替代 cleanup service、CLI、删除 manifest 或兼容入口。P4 交付时 ETF review、Health、monitor 和旧池基础设施按 P5-P8 原边界保留；其中 Health 已在后续 P5 完成迁移。
5. request builder、分页、默认全市场请求和显式 `ts_code` 单代码探测入口未改；`fund_adj`、`etf_share_size`、实时链路、TaskRun schema、前端和数据库迁移均未修改。
6. CodeGraph 在开工前确认 `DatasetWriter` 影响 Foundation executor 与 writer 定向测试，旧 cleanup 的 14 个符号只落在 service 和专用测试；精确搜索确认删除后 `fund_daily` 与 cleanup 对旧池引用清零，指数池及其他未迁移 ETF 消费者仍在。
7. Definition/linter/resolver/writer/executor 与普通 executor、ETF Basic snapshot、ETF minutes、代码本、运行时注册、三组架构边界合计 279 个测试通过；剩余旧池 DAO/model/seed、CLI 和 review 消费者保护回归 64 个通过；本阶段修改的 Python 文件 Ruff 检查通过。失败注入覆盖 Raw upsert/commit、selector 空/异常、Serving upsert/commit，以及失败后 Raw 幂等重放和 Serving 再发布。
8. 本阶段没有请求 Tushare、写入生产数据库、执行事实删除或运行旧 cleanup；历史 Serving 事实未被回删，代码消失或 `list_date` 变晚仍只影响未来发布。

### P5：实时 Health 后端与页面切换（已完成）

编码：

1. `RealtimeFeedHealthQueryService` 改为一次加载 Basic snapshot。
2. 后端 schema 将 `active_pool_count/active_snapshot_count` 改为 `eligible_etf_count/eligible_snapshot_count`。
3. 同步 realtime frontend type、健康卡片文案和测试。
4. 保持 provider 通配符、Redis key、batch/snapshot/delta 逻辑完全不变。

完成门禁：provider 请求参数快照测试保持固定通配符；Health 链不再引用旧池；候选、monitor runtime 和 review 尚未在本阶段删除。

#### P5 执行记录（2026-08-28）

1. `RealtimeFeedHealthQueryService.build_etf_rt_daily_health()` 已删除 `EtfSeriesActiveDAO` 依赖；每次 API 调用固定当前中国自然日并只调用一次 `EtfBasicDAO.load_requestability_snapshot(as_of_date)`，随后用同一份 target codes 计算当前 Redis batch 命中数。
2. 后端响应、前端类型和页面消费已从 `active_pool_count/active_snapshot_count` 直接切换为 `eligible_etf_count/eligible_snapshot_count`；没有 Pydantic alias、旧 JSON 字段或前端 fallback。`/api/v1/ops/realtime/etf-rt-daily/health` 路径及其余源端、批次、状态和轮询字段未改。
3. selector 空集合时，源端批次仍照常读取，资格分母和命中数返回 `0/0`，不标记为 Redis 不可用，也不以源端全量回填分母；Redis 不可用时保留已加载的 Basic 分母，命中数返回 0。
4. 实时监控页只把旧“活跃池命中”卡片改为“可请求 ETF 覆盖”，继续复用现有 `SectionCard/StatCard`，没有调整布局、查询路径、轮询策略或其他实时对象页面状态。
5. provider、runtime config、collector、Redis key、batch/snapshot/delta 发布实现均未修改；现有请求参数快照测试继续固定 `5*.SH` 与 `1*.SZ` 两个源请求段。
6. P6 的 candidate/pool/rule/runtime、P7 的旧 ETF review，以及 P8 的 DAO/model/seed/CLI/table 均保持原边界；本阶段没有数据库迁移、生产写入、Tushare 请求或配置变化。
7. 开发前 CodeGraph 索引为 up to date，包含 2,814 个文件、49,728 个节点和 126,369 条边；query/impact 与精确搜索覆盖 Health query、Ops API/schema、前端类型/页面及后端和前端测试，未发现需要扩大 P5 的隐藏消费者。
8. ETF Basic DAO、Health API、实时 provider/state/config/collector 与三组架构边界共 68 个后端测试通过，相关 Ruff 检查通过；前端 typecheck、规则检查、149 个测试和生产构建全部通过。测试包含资格/非资格交集、单次 snapshot 调用、空资格、Redis 故障和旧字段缺失。

### P6：实时监控候选、配置和运行时切换（已完成）

编码：

1. candidate query 改由 Basic requestable subquery 起表；endpoint/DTO/method 从 `active` 改为 `eligible`。
2. count 与 page 查询固定同一 `as_of_date`/subquery；增加空集合正常返回测试。
3. 新增监控对象和 disabled -> enabled 更新用 `get_requestable_target()` 校验。
4. ETF scope rule 写入同时校验监控池成员与当前资格；group rule 不逐代码校验。
5. `run_after_etf_batch()` 每批加载一次 snapshot，并以 `enabled monitor pool ∩ requestable codes` 执行；空交集只返回现有 `skipped` 结果和 message，不新增计数或诊断持久化。
6. 同步监控配置前端 API、DTO、页面和测试。
7. 保留 `ops.etf_realtime_monitor_pool/rule/alert/minute_stat` 及历史数据。
8. 不修改独立旧分钟归档 service/CLI；它保持冻结并由专门的实时监控 LLD 后续退场。

完成门禁：candidate、pool add、ETF rule 与 runtime 对旧池引用清零；空 selector 时 candidate 返回空页、runtime no-op；review 页面仍可暂时读旧池，留给 P7 独立删除。

#### P6 执行记录（2026-08-28）

1. 候选 API、service method 和 DTO 已从 `active` 直接改名为 `eligible`；`GET /api/v1/ops/realtime/etf-monitor/eligible-etfs` 每次请求固定一次中国自然日并只构造一次 `EtfBasicDAO.requestable_targets_subquery(as_of_date)`，count/page 复用同一对象。查询仍关联最新 `fund_daily`、最新 `raw_tushare.etf_share_size` 和运营监控池，保留关键词、分页、规模降序与代码排序；旧 `/active-etfs` 无 alias，测试确认 404。
2. 候选资格的正反样本覆盖 `.SH/.SZ + L + 有效上市日`，以及 `P/D`、空上市日、未来上市日、`.OF` 和代码后缀/交易所冲突。旧激活池即使仍有对应记录也不会回退；Basic 空集合返回 `200 + total=0 + items=[]`。
3. 新增监控对象无论 `enabled` 取值均通过 `get_requestable_target()`；`disabled -> enabled` 重新校验，`disabled -> disabled`、`enabled -> enabled` 和 `enabled -> disabled` 保持既定行为。失败仍使用 `422 / invalid_etf`，且测试确认不会新增记录或把 disabled 状态误改为 enabled。
4. ETF 级规则创建和修改先校验监控池成员，再校验当前可请求资格，失败沿用 `422 / invalid_scope` 且不污染原规则；group 规则只校验分组存在，global 规则保持 `__GLOBAL__`。规则删除、窗口、比例、冲突和默认规则逻辑未改。
5. `run_after_etf_batch()` 在批次开始固定当前中国时间，读取 enabled monitor pool 后只加载一次 Basic requestability snapshot，并只对两者交集读取 Redis 指标、历史基线和创建告警。`trade_date` 仍只决定行情交易日；Basic 名称查询只提供展示元数据，不改变资格集合。
6. 空监控池、空 Basic 或无交集统一返回 `status='skipped'`、`evaluated_count=0`、`alert_count=0` 和 `message='eligible ETF set empty'`；此路径不读规则、不计算指标、不调用飞书、不产生告警。selector 异常不回退旧池并继续抛给 collector 既有失败隔离；原告警提交顺序、飞书失败隔离、单 ETF 失败隔离和冷却升级行为保持。
7. 前端类型、query key、状态/组件参数和请求路径均迁移为 `eligibleEtf*` / `EligibleEtf*` / `/eligible-etfs`；候选文案改为“从当前可请求 ETF 中选择”。每页 50 条、关键词搜索、规模展示、分组选择和逐行添加保持，页面布局、监控池管理、规则编辑与告警区域未改。
8. `EtfRealtimeMinuteArchiveService`、`ops-archive-etf-realtime-minute-stats`、provider、Redis contract、实时配置、review center、旧池 DAO/model/contract/adapter/seed/CLI/table 均未修改。旧归档回归测试继续通过；P7 仍负责 review，P8 仍负责旧池基础设施和数据库表。
9. 后端 P6/旧归档/collector CLI 定向测试 26 个通过，实时 API 与三组架构边界回归 33 个通过，修改 Python 文件 Ruff 通过。前端目标测试 3 个、全量测试 149 个、typecheck、规则检查和生产构建通过；构建只有既有大 chunk 警告。浏览器核验时发现本机 `5173` 正运行独立 `wealth` 前端，因此未接管或重启用户服务；P6 页面请求与文案由目标测试和全量构建验证。
10. 完成后 CodeGraph 索引为 up to date，包含 2,830 个文件、50,141 个节点和 127,564 条边；query/impact 与精确搜索复核 pool/rule/runtime/API/schema/frontend/tests，未发现新增消费者或依赖越界。P6 监控链对 `EtfSeriesActive`、`list_active_etfs`、`ActiveEtf` 和 `/active-etfs` 的生产引用已清零；旧 review 引用按 P7 边界保留。未执行生产写入、数据库迁移、Tushare 请求、旧分钟归档或历史数据清理。

### P7：旧 ETF 激活池 review 能力删除与消费者清零

编码：

1. 删除 `/api/v1/ops/review/etf/active` 与 summary 路由、query method、ETF active schema/export。
2. 删除 `ops-v21-review-etf-page*`、对应路由、导航、共享类型和测试。
3. 不新建 Basic 浏览页面。
4. 使用 CodeGraph impact + 精确字符串搜索证明运行时消费者已清零。

P7 的“消费者零引用”允许旧基础设施本体暂时存在：model、DAO、contract、adapter、seed、CLI、历史 migration 及其独立测试仍由 P8 处理。除此以外，planner、writer、cleanup、Health、monitor、review 均不得再引用旧池。

完成门禁：形成 P8 可核验的删除白名单；若发现未登记消费者，停止并修订 LLD，不进入 P8。

### P8：激活池基础设施与 schema 退场

编码：

1. 按 P7 白名单删除 model、DAO、contract、adapter、seed service、seed CLI 和独立旧测试。
2. 从 `DAOFactory` 删除 `etf_series_active`，清理 model registry 与 ORM export。
3. **不再处理**已由 P4 删除的 cleanup 和已由 P7 删除的 review。
4. 同步 CodeGraph，执行全仓当前态字符串清零，精确保护 `index_series_active`。
5. 重新确认唯一 Alembic head 后新增不可逆 drop-table migration；历史建表 migration 保留。
6. 给历史激活池文档补充 superseded 链接。

完成门禁：运行时代码/前端/config 旧引用为 0；测试无旧能力 import/fixture/call，仅保留明确负向断言；指数池测试全部通过；migration 能从真实 head 升级。

### P9：分钟对齐 preview 与受控 TaskRun 提交

子阶段 P9A 编码：

1. 实现第 10 节只读 alignment plan service 和 `ops-preview-etf-minute-alignment`。
2. preview 固定全部当前可请求 ETF 和五个原生频率，不暴露历史 `as_of_date`、代码子集或频率子集输入。
3. preview 复用 Basic selector 与 P3 纯切窗函数，对相同代码与日期区间的频率合并 action，输出 target hash、action/unit 数与请求上下界。
4. 不实现 submit，不新增数据库 plan/history 表、schedule 或任何业务写入。

P9A 测试：无 raw、只有前缀、只有尾部、已有全区间、只有当前上市日前的代码复用旧历史、覆盖区间裁到 desired interval、源端成功空区间由显式成功 TaskRun 覆盖、多频率 TaskRun 覆盖还原、内部 gap 不生成请求、相同范围频率 action 合并、交易日历缺失/非开市日/晚于最近开市日、非资格字段变化不改 target hash、新增/移除 target 或 `list_date` 变化会改 hash、raw/TaskRun 集合查询次数恒定且无 ETF×频率 N+1，以及 1-call/4-call 请求边界。

P9A 完成门禁：preview 零网络/零业务写；真实只读规模报告已展示给用户；仓库中仍不存在 submit 或事实清理入口。

P9B 只在用户对 P9A 的真实 TaskRun 规模和首批 `batch-size` 拍板后开始：

1. 实现 `ops-submit-etf-minute-alignment`，只通过 `TaskRunCommandService` 创建正式 TaskRun。
2. submit 重新加载一次 snapshot，用内存 target map 校验所有 action，禁止逐 action 查 Basic。
3. submit 复用当前 TaskRun 创建契约，实际执行再由正式 resolver/planner 校验；不增加 connector/writer 旁路。
4. submit service 自己串行化提交，并在一个事务内 stage/commit 整批 TaskRun；不修改共享 `TaskRunCommandService` 的并发策略。
5. 测试 target hash 变化整批拒绝、已有 open `etf_mins` TaskRun 拒绝、并发 submit 只有一个进入、重复 submit 跳过已覆盖、分批提交、任一 stage 失败整批回滚。

P9B 完成门禁：只有显式 submit 命令才创建 TaskRun；提交前只读重校验不执行 Tushare 请求或业务写入；仓库不存在事实清理入口。

### P10：候选环境总回归与发布门禁

1. 执行全部后端目标测试、架构边界测试、前端 typecheck/rules/test/build。
2. 在临时 PostgreSQL 从旧 schema 升级并验证新进程启动。
3. 跑一次 Basic 小型完整快照 fixture。
4. 跑一次 fund daily raw 成功/serving 故障注入。
5. 验证 Health、eligible candidate、pool/rule/runtime 和 review 404。
6. 按第 9 节受控 SQL复核下游统计，并运行分钟 preview；禁止事实删除、生产 TaskRun 和真实补拉。
7. 复核 Alembic head/current、旧引用 0、`index_series_active` 正常。

完成门禁：D1-D20 测试矩阵全部有证据，不能只以“测试总数通过”代替口径对账。

### P11：生产切换、Basic 重建与只读审计

本阶段需要用户单独授权，授权范围只包含新版本切换、`ops.etf_series_active` drop、`etf_basic` 正式快照重建和下游只读验收，不包含分钟补拉或下游事实删除。

顺序固定：

```text
维护窗口与零运行任务
-> 无兼容版本发布和 drop 激活池表
-> etf_basic 完整快照重建
-> raw/serving 验收
-> 下游只读复核
-> 确认已批准删除候选为 0
-> Health/eligible candidate/monitor 冒烟
-> 恢复相关进程与 schedule
```

若 Basic 重建失败，P1 的快照事务保留上一版 raw/serving；新 selector 会过滤旧 serving 中的 `.OF`，但相关 schedule 保持暂停，必须前向修复并重新验收。若复核意外出现明确非交易所身份，停止并另行评审，不执行事实删除。

### P12：分钟全量补拉与最终对账

本阶段需要第二次独立授权：

1. 在 P11 成功后的 Basic snapshot 上生成生产 alignment plan。
2. 向用户展示 ETF 数、action 数、unit 数、请求上下界和拟采用的 `batch-size`；批次大小由用户明确选择，不由 preview 伪造推荐值，也不提供总耗时预测。
3. 用户确认后按批提交正式 TaskRun；失败批次停止继续提交。
4. 首个已批准批次结束后先对账真实请求数与耗时，向用户反馈后再继续下一批；同时对账成功/失败 TaskRun、源端空结果、写入行数和重复主键。
5. 重跑 preview，确认 prefix/suffix 请求缺口按 V1 口径归零或有明确失败原因。

P12 不执行下游 DELETE，也不能用“P11 已授权”代替额度确认。

---

## 14. 测试与硬口径对账

| 方案决策 | 必须落到的代码/测试 |
|---|---|
| D1-D3 | Basic Definition、snapshot validator/writer；完整 raw、单事务替换、失败回滚 |
| D4 | 禁止 OF rename/merge；当前无旧 OF 下游候选；未来非零时停止并另立精确方案 |
| D5-D9 | Basic DAO + 三个 planner；状态、日期、后缀、切窗和无退市日上界测试 |
| D10-D11 | serving 后缀测试；公募基金保护表 checksum；3 条 OF 仅 raw fixture |
| D12 | 全量引用清零、drop-table migration、无 fallback 负向测试 |
| D13 | 不新增通用事实 cleanup service/CLI/删除 manifest/apply；旧 cleanup 在 P4 直接退场 |
| D14 | 无新历史表/字段；仅 `etf_basic` 正式快照 TaskRun 的现有 diagnostics 承载主数据 hash/摘要，不外推为所有 planner/monitor 的统一诊断 |
| D15 | 日常 Basic 变化测试只影响新计划，不调用事实 DELETE |
| D16 | CodeGraph + 字符串 + DB 六层清零、维护窗口发布顺序 |
| D17 | fund daily/fund adj/share size 默认全市场请求不扇出；显式入口定位测试 |
| D18 | raw/core/直出 view 零删除保护测试 |
| D19 | fund daily 两阶段 serving gate；fund_adj/share size 零改动回归 |
| D20 | realtime provider 固定通配符请求快照测试；只替换 health/候选 |

### 14.1 后端目标测试

实现时至少覆盖：

```text
tests/test_etf_basic_dao.py
tests/test_etf_basic_dataset.py
tests/test_etf_basic_snapshot_writer.py
tests/test_dataset_definition_registry.py
tests/test_dataset_action_resolver.py
tests/test_etf_mins_dataset.py
tests/test_etf_sh_cons_model.py
tests/test_dataset_writer_fund_daily_master_gate.py
tests/test_ingestion_executor_fund_daily_two_phase.py
tests/test_etf_minute_history_alignment_plan_service.py
tests/test_etf_minute_history_alignment_submit_service.py
tests/web/test_realtime_api.py
tests/web/test_ops_etf_realtime_monitor_api.py
tests/web/test_ops_review_center_api.py 中删除旧 ETF review 用例
```

旧 active pool model/DAO/seed/CLI/固定 1,395 报告测试删除，不改写成新名字继续维护旧语义。

### 14.2 前端目标测试

至少覆盖：

```text
ops-realtime-monitor-page.test.tsx
ops-etf-realtime-monitor-config-page.test.tsx
router/navigation 相关测试
```

验证新 eligible 字段和 endpoint；旧 review 页面测试删除。

### 14.3 建议验证命令

编码阶段按受影响范围逐步运行，最终至少包括：

```text
uv run pytest -q <上述后端目标测试>
uv run ruff check <本次修改的 Python 文件>
uv run alembic heads
uv run alembic current
python3 scripts/check_docs_integrity.py
git diff --check

cd frontend
npm run typecheck
npm run check:rules
npm run test
npm run build
```

还必须运行仓库现有的架构/依赖边界测试；实施时先用文件搜索确认当前真实测试入口，不在 LLD 中猜一个可能过期的文件名。

---

## 15. 生产验收证据

### 15.1 Basic

```text
源端完整行数 = raw 行数
源端 ts_code 集合 = raw ts_code 集合
serving ts_code 集合 = raw 中 .SH/.SZ 集合
raw/serving 重复主键 = 0
serving .OF/未知后缀 = 0
TaskRun snapshot hash = 只读复算 hash
```

### 15.2 激活池退场

```text
src/frontend/current config 旧引用 = 0
tests 旧能力 import/fixture/call = 0（允许 retirement/migration 负向字符串断言）
旧 review routes = 404
旧 CLI = 不存在
ops.etf_series_active = 不存在
index_series_active 规划与测试 = 正常
```

### 15.3 下游只读复核

```text
NON_EXCHANGE_ETF_SUFFIX = 0
CODE_NOT_IN_ETF_MASTER = 只报告，不删除
BEFORE_CURRENT_LIST_DATE = 只报告，不删除
下游事实 DELETE 执行次数 = 0
保护表没有因本次改造发生历史删除
历史 alert/stat = 保留
```

### 15.4 分钟补拉

```text
每个实际请求 start_date >= 对应 list_date
计划 TaskRun/unit/request 上下界与实际可对账
已有 raw 观察区间不重复生成 prefix/suffix
成功的显式空结果 TaskRun 区间不重复请求
内部逐日/逐 bar 空洞明确标记为未审计
失败与源端空结果有代码和样本
重复执行不增加重复主键
```

V1 验收只能声明“当前可请求 ETF 与频率的区间请求前缀/尾部已按本次计划覆盖”，不能声明每个交易日或每个分钟 bar 均完整。

---

## 16. 边界、文档与未决项

### 16.1 子系统边界

目标依赖保持：

```text
foundation <- ops <- app
foundation <- biz <- app
```

Foundation planner/writer 只访问 Foundation 的 `core_serving.etf_basic` DAO；删除 Foundation 为读取 Ops ETF 激活池而设置的 contract。不存在 `foundation -> ops` ORM 依赖。`qtf` 不受影响。

依赖矩阵的方向没有新增变化。P1 只在现有 Foundation ingestion 与 Ops TaskRun 责任内扩展专用 write path、诊断和并发门禁，没有改变子系统边界、主要入口或依赖方向，因此本阶段不更新 `codegraph-architecture-snapshot.md`。P2 以后如果关键 contract/adapter 和调用链发生实质变化，再按根规则复核是否更新。

### 16.2 必须同步的文档

实现阶段至少更新：

1. 本 LLD 状态和里程碑完成证据。
2. 上层技术方案的实现状态。
3. 旧 ETF active pool 方案/LLD 的 superseded 状态。
4. `etf_mins` 数据集方案/LLD 中对象来源与上市日规则。
5. Tushare 本地源文档仅在真实参数/字段行为变化时更新。
6. 数据集目录/运营说明中删除旧 seed、review 页面和激活池初始化步骤。

### 16.3 未决项

没有业务口径待拍板。以下是实施期停止门禁，不是可由开发者自行选择的方案分支：

1. Alembic head 在编码时若已变化，必须接新的真实 head。
2. 生产复核对象或统计结果若与本 LLD 不一致，必须重新审计并修订 LLD。
3. Tushare 关键字段、分页或返回范围若与本轮实测不一致，必须先修本地源文档和设计。
4. `NON_EXCHANGE_ETF_SUFFIX` 若实际非零，必须停止并另立精确一次性方案；`PENDING_ETF_HAS_FACT` 只报告，不自动删除。
5. P9A 真实 preview 的 action、unit 或请求上下界达到不可接受量级时，停在 P9A，不实现 submit。可以重新评审无额外请求的 action 分组或执行批次，但不能取消上市日、已有覆盖和正式 TaskRun 主链门禁。

---

## 17. LLD 完成定义

本 LLD 的“完成”表示：

1. 上层 D1-D20 均有明确代码点、事务语义、正反测试和生产证据。
2. 激活池所有已发现消费者都有删除或替代去向。
3. `etf_basic`、`fund_daily`、分钟补拉和下游只读复核的失败边界已落清。
4. 明确保护 `fund_adj`、`etf_share_size`、公募基金域、指数池和历史实时事实。
5. 开发顺序阻止了“先删表再找消费者”，并明确当前不建设下游事实清理系统。

本文中 P0-P6 的执行记录代表对应阶段已完成；原 P2-P9 已作废，新版 P7-P12 均未实施。本 LLD 不授权执行生产快照重建、删表迁移、下游删除或全量补拉。当前停在 P6 阶段边界，P7 及以后仍须按用户的阶段指令逐步推进。
