# Dagster 数据管道性能治理规范

更新时间：2026-09-05（M5 合并只读导出检查项，不调整既有热路径预算）

本文是 `lake_console/orchestrator` 的长期性能治理规范，适用于 Dagster 资产、asset check、sensor、run-status sensor、continuity selector、readiness helper、bootstrap、runless event 补录、DuckDB/Parquet 计算和数据集接入设计。

本文不是某个专项方案的替代品。新增或修改具体链路时，仍需按对应专项文档、`AGENTS.md`、`lake_console/orchestrator/CODING_STANDARDS.md` 执行；本文只定义通用设计规则和性能门禁。

---

## 1. 背景

近期连续处理了多类性能和连续性问题：

1. 股票分钟线停机后，后续日期跳过空洞，导致 raw、silver、qfq、MACD/KDJ 等链路需要重建。
2. sensor 在热路径中逐日读取 Dagster event/check history，导致 tick 超时或拖慢 UI。
3. 部分 helper 名称上叫 batch，实际内部仍按日期、频度、文件重复执行重 SQL，导致 10 天窗口仍可能接近或超过 sensor 预算。
4. 部分 sensor 在运行时间窗口之前就执行重 DuckDB readiness 扫描，白白消耗 code server 和 daemon 资源。
5. 曾出现把 row count、文件存在当作 ready 的风险，但正式 ready 必须等价于 blocking checks 语义。
6. `000638.SZ` 退市历史股票暴露出 current-listed-only 和 namechange 不能作为股票生命周期事实源的问题。
7. runless check event 补录、历史 bootstrap、非分钟线 continuity 等任务暴露出：写入动作前必须先 dry-run、测量、设上限，不能把正式 Dagster instance 当实验环境。

这些问题的根因不是某个单点 bug，而是设计阶段没有把“读取模型、写入模型、窗口大小、状态来源、性能预算、回退门禁”当成硬契约。本文用于把这些经验固化成以后必须遵守的规则。

---

## 2. 总原则

### 2.1 性能是设计门禁，不是上线后优化项

任何新增或修改数据集、asset、check、sensor、readiness helper、bootstrap、补录脚本前，都必须先回答：

1. 每次执行最多读多少日期、多少资产、多少 check、多少文件、多少行。
2. 每次执行最多写多少文件、多少 Dagster event、多少 metadata。
3. 读取是否在 sensor 热路径、asset 写入路径、离线 bootstrap 路径，还是一次性审计路径。
4. 最坏情况下是否会触发 Dagster gRPC 60 秒超时、UI 卡顿、DuckDB 大量重复扫描或 event log 深扫。
5. 若数据量超过预算，是 fail closed、分批处理、要求人工审批，还是进入离线工具。

没有这些估算和验证，不允许进入编码。

### 2.2 正确性不能让位给性能

性能优化不得降低数据质量语义：

1. ready 不是“文件存在”。
2. ready 不是“row count 大于 0”。
3. ready 必须等价于正式 blocking checks 通过，或由 DuckDB/lake 查询完整复刻这些 blocking check 的 SQL 语义。
4. 可以用文件存在和 row count 做粗筛，但不能把粗筛结果写成正式 ready。
5. 若完整语义无法在预算内完成，必须停下重设方案，不能偷换语义。

### 2.3 先优化读取模型，再讨论新增状态实体

新增 status manifest、readiness asset、summary asset、数据库表、缓存文件或配置项前，必须先证明以下方案都不可行：

1. Dagster metadata 按 asset/check/partition 做有界批量读取。
2. DuckDB 直接读取 lake Parquet 文件事实。
3. 通过现有 materialization/check metadata 的小字段完成判断。
4. 通过 cursor 记录小型 frontier，而不是完整明细。

新增实体会引入一致性、回补、写失败、schema 演进和退出成本。不能因为当前实现慢，就默认新建一个状态资产。

### 2.4 热路径和离线路径必须分开设计

sensor、run-status sensor、AutomationCondition 替代 sensor、日常 readiness gate 属于热路径。

历史补洞、全量审计、runless event 补录、bootstrap、长窗口回归属于离线路径。

热路径要求小窗口、低查询次数、低反序列化、低 cursor 体积。离线路径可以更重，但必须 dry-run、分批、设上限、输出报告，并经审批后才能写正式环境。

### 2.5 计算正确性与生产 Check 必须分工

计算逻辑的正确性由受保护的测试金样本负责；production check 负责本次真实运行的输入、文件和状态事实。两者不得互相替代。

1. 公式、转换、窗口、边界和 repair 范围必须由独立 expected 值的 unit/integration fixture 覆盖。禁止由被测 helper 反向生成 expected 值。
2. production check 默认不得为证明公式正确而对全量输出做第二次计算。它应优先验证上游覆盖、空值/重复、schema、分区、文件写入和状态新鲜度。
3. 只有存在独立外部对账事实，且该对账是明确业务契约时，才可设计计算型 production check；必须先给出读取量、性能预算和为什么测试不足以覆盖该风险。
4. 不能为了让历史 check 变绿，从输出结果反推“依据”再用该依据证明输出正确。这最多是内部一致性审计，不是源头正确性证明。
5. 公式金样本不得随意删除、弱化或跳过。业务公式确实变更时，必须同时更新设计口径、fixture 输入、字面 expected 输出、测试说明和静态门禁。

---

## 3. 开发前性能设计清单

每个涉及数据管道性能的方案，开发前必须列出下表。

| 项 | 必须写清 |
| --- | --- |
| 执行入口 | asset、check、sensor、run-status sensor、CLI、bootstrap、runless 补录 |
| 路径类型 | 热路径、离线审计、一次性补录、历史 bootstrap |
| 目标范围 | 日期窗口、partition set、asset 列表、check 列表、股票/指数/代码范围 |
| 读取来源 | Dagster event log、asset check records、DuckDB Parquet、ClickHouse、Tushare、配置文件 |
| 读取次数模型 | 日期数 × asset 数 × check 数 × 频度数，是否批量读取 |
| 写入模型 | 写 lake 文件、Dagster event、metadata、cursor、数据库表、临时报告 |
| 正确性语义 | 对应哪些正式 blocking checks 或字段契约 |
| 性能预算 | 稳态耗时、异常耗时、最大文件数、最大记录数、最大 API 调用数 |
| 失败策略 | fail closed、SkipReason、人工处理、停止审批、分批处理 |
| 测试门禁 | 单元测试、静态门禁、只读 profiling、性能样本 |
| 文档对账 | 需要同步哪些方案文档、AGENTS、编码规范 |

缺任何一项，都不能进入正式代码开发。

---

## 4. Sensor 热路径规则

### 4.1 先做轻量判断，再做重计算

sensor 必须按从轻到重的顺序执行：

1. lake root 可用性。
2. 当前是否到运行时间窗口。
3. expected date 和 registered partition 的轻量缺口判断。
4. cursor 或 already-submitted 小型判断。
5. 必要的 batch readiness。
6. selected date 上游 readiness。
7. 构造 RunRequest。

禁止在运行窗口之前执行重 DuckDB 扫描、Dagster event history 深扫或大文件读取。

### 4.2 日常热路径默认窗口为 10 个 expected trade dates

日常 continuity 和 readiness sensor 的默认回看窗口是最近 10 个 expected trade dates。

60 天窗口只能用于：

1. 经专项明确批准的离线审计。
2. 性能测试容量样本。
3. 用户明确要求的长窗口修复或历史治理。

不能因为“60 天更保险”就在日常 sensor 热路径里默认扫 60 天。若业务确实需要超过 10 天，必须先给出性能测试和运行预算。

### 4.3 Batch 必须是真 batch

函数名、变量名或文档写了 batch，不代表实现就是 batch。

真正的 batch 必须满足：

1. 对窗口内日期一次性规划文件集合。
2. 对同一类数据尽量用一次或少量 DuckDB SQL 完成聚合。
3. 不能在 Python 循环中对每个日期、每个频度、每个文件反复执行重 SQL。
4. 不能在窗口内逐日调用 Dagster readiness helper。
5. 性能测试必须记录 SQL 次数、文件数、耗时和最慢子查询。

如果 batch helper 内部仍是 `日期 × 频度 × 重 SQL`，应视为高危实现，必须重构或限制进入热路径。

### 4.4 Cursor 必须小

sensor cursor 只允许存：

1. schema version。
2. evaluated_at。
3. selected date。
4. frontier。
5. 小型状态摘要。
6. 必要的错误样本，且必须有 sample limit。

禁止把完整文件路径列表、全量失败行、全量 partition 明细、完整 SQL 结果、长 metadata payload 写入 cursor。

### 4.5 热路径不得无界读取 Dagster event/check history

sensor 热路径禁止：

1. 对每个日期调用一次 event/check history 查询。
2. 使用没有明确上限和过滤条件的 `get_event_records(...)`。
3. 为了补齐 storage id 或历史 metadata，在日常 tick 中扫描大量 Dagster 事件。
4. 先取大批 event 再在 Python 里过滤。

如必须读 Dagster metadata，必须按 asset/check/partition 做有界读取，并在测试中证明 API 调用次数和返回记录数。

---

## 5. Readiness 与 Asset Check 语义规则

### 5.1 Ready 的最低定义

一个上游资产 ready，至少满足：

1. 目标 asset 或 partition 已 materialized。
2. 所有关联 blocking checks 已通过。
3. full snapshot 资产满足 freshness 或当日可用口径。
4. 分区资产按同一 partition_key 判断。
5. WARN checks 只记录观测，不阻断生产。

### 5.2 DuckDB readiness 必须复刻正式 check 语义

使用 DuckDB 读取 lake 文件计算 readiness 时，必须复用或抽取 `defs/checks/**` 里的正式 SQL/契约语义。

允许做：

1. 把现有 check SQL 抽成可复用 helper。
2. 用 DuckDB 对多个日期或多个文件批量执行同等语义。
3. 输出和 check metadata 对齐的小型失败原因和样本。

禁止做：

1. 只看文件存在和 row count。
2. 忽略 schema、date/freq、唯一键、价格成交量、覆盖率、生命周期等正式 blocking checks；公式正确性默认由测试金样本负责，不应被重新塞入 readiness。
3. 因性能压力删除或弱化 blocking check 条件。

### 5.3 身份和生命周期事实必须来自稳定资产

股票是否应出现在某天的数据里，必须由稳定生命周期事实判断。

规则：

1. 当前上市股票池不能代表历史生命周期。
2. namechange 不能代表股票生命周期。
3. 退市历史股票不能靠往 current-listed-only 数据集里塞记录解决。
4. 生命周期事实应沉淀为明确数据集，例如 `silver_stock_lifecycle`，下游统一消费。
5. 下游 check 或 readiness 不得各自拼装 lifecycle 口径。

### 5.4 Materialized check problem 不自动重跑

若目标文件已存在，但 blocking checks 未通过，sensor 应返回 SkipReason 或 blocked status，要求人工处理。

禁止自动重跑并推进后续日期，除非专项设计明确说明这是安全的 repair 场景。

---

## 6. DuckDB、Parquet 与大数据量计算规则

### 6.1 优先使用向量化 SQL

大数据量处理必须优先使用 DuckDB SQL、`COPY`、Parquet projection、partition pruning 和 set-based join。

禁止：

1. Python 逐行循环处理大表。
2. 对大查询结果无界 `fetchall()`。
3. 大批量 `executemany()` 逐行写入。
4. 每个 partition 重复扫描同一份全量事实文件。

### 6.2 控制文件扫描模型

设计时必须写清：

1. 每次读取多少 Parquet 文件。
2. 是否会读取同一文件多次。
3. 是否能按日期、频度、代码、列投影裁剪。
4. 是否需要预聚合临时表。
5. 是否会触发内存压力或临时目录溢出。

### 6.3 批量写入必须有原子性和审计

写 lake 文件时必须考虑：

1. 临时路径。
2. 原子替换。
3. 写前 preflight。
4. 写后 row count、schema、sample、checksum 或必要 metadata。
5. 失败后不留下半成品。

大范围 bootstrap 必须先 dry-run，再 sample，再 batch，再 final audit。

<a id="prod-readonly-export"></a>

### 6.4 Prod 只读导出：先确认来源，再约束读取成本

本节适用于正式 orchestrator 从已批准 prod 数据源读取并生成 Lake 候选的链路，不授予生产写入权限，
也不把旧 Console 的“只允许 raw_tushare、禁止读取 Ops”套到现行链路上。
例如分钟 Raw 恢复会读取 `ops.task_run` 作为来源就绪证据；其字段、范围和查询上限由该专项约束，不能删掉。

1. 表/列白名单必须来自本数据集当前 source contract 和获准范围，不能从数据库全字段推导。显式投影，禁止源表 `SELECT *`；标识符来自受控映射，输入值采用参数绑定或已验证的专用 SQL builder，禁止任意 SQL/标识符透传。
2. 只读属性必须在业务查询前建立。Python 流式读取优先复用 `ProdPostgresResource.connect_readonly_transaction()`，结束 rollback 并关闭连接；不混入生产写入事务。DuckDB 读取使用现行受控只读 attach/source contract。
3. 大范围读取优先按一个有界 unit 使用单连接、只读事务、服务端游标和 `fetchmany`；读范围与写分区可以不同。不得无依据退化为“每日重新建连接 + 每日查询”，也不得让全历史长事务成为默认值。分页、分区读取或 DuckDB COPY 路径如更适合现有契约，写明理由和预算，不为统一模板强制改写。
4. 大表禁止无界 `fetchall` 或完整 DataFrame 常驻内存。小型有界聚合可以读回结果，但须记录返回上限；流式路径写清 fetch batch、写 batch、缓冲上限、内存/spill 预算、取消与重试粒度。
5. 每次设计列出连接次数、SQL 次数、扫描行/文件数、分页次数、预计耗时和超预算行为；最低真实验证记录实际数量和最慢阶段。人工低频恢复可记录慢操作告警，不因慢于历史单次样本而否决；正确性、只读和范围边界不能放宽。
6. 源 schema、显式投影、归一化与目标 schema 逐项对账；源行数、读取行数、归一化行数、reject/过滤原因与样本、写入行数、目标读回行数必须可解释。按当前 Raw/Silver 契约处理合法清洗差异，不强制所有字段或行数不变。
7. 正式源只允许本数据集已获准的 Tushare、prod 只读源、正式 Lake 上游或版本化 seed。旧湖不得用作来源或 staging；Kopia 禁止。候选位于 `data_lake_staging`，正式目标位于 `data_lake/raw|silver|gold`，完整候选校验后同文件系统逐文件 `os.replace()`，保留 checkpoint 与幂等续跑；不得自动删除异常现场。

代码依据：`defs/resources.py` 的只读连接、`defs/bootstrap/stk_mins_raw_replace_from_prod.py` 的有界状态查询及
受控导出、`defs/prod_db/stk_mins.py` 的显式源契约（路径均相对于 `lake_console/orchestrator/src/orchestrator/`）。
接入记录统一填写 [正式 onboarding 模板 7A](../templates/dagster-dataset-onboarding-template.html#source-contract-budget)。

---

## 7. Dagster Event 与 Runless Event 规则

### 7.1 Event log 不是事实表

Dagster event log 主要服务编排和可观测，不应作为大窗口数据事实扫描源。

可以使用 event log 判断：

1. 某个 run 是否成功。
2. 某个 partition 最近一次 materialization/check 状态。
3. 小范围 metadata 一致性。

不应使用 event log 做：

1. 大窗口逐日 readiness 深扫。
2. 大规模业务事实统计。
3. 高频 sensor 的主判断来源。

### 7.2 Runless check event 写入必须单独审批

runless check event 补录只能用于修正历史 Dagster check 观测状态，不能替代业务数据修复。

流程必须是：

1. 只读 dry-run，统计候选、已有 passed、历史 failed、缺 materialization、真实待补数。
2. 输出报告并设上限。
3. 用户审批 apply。
4. 小批量写入。
5. 写后只读 audit。

禁止：

1. 在 dry-run 代码路径中隐藏写入参数。
2. 把 missing check event 自动扩进补录范围。
3. 没有 materialization 就补 check event。
4. 对正式 Dagster instance 做无界写入。

---

## 8. 历史补洞与日常连续性规则

### 8.1 日常 sensor 只推进最早可行动日期

continuity selector 必须遵守：

1. 先查 expected date 是否注册。
2. 再查最早 not ready。
3. 一次只提交最早可行动日期。
4. 前一天未 ready 时，不提交后一天。
5. 已生成但 checks 未绿时，不自动重跑后续日期。

### 8.2 长停机和历史空洞走专项恢复

若缺口超过日常热路径窗口，不能把日常 sensor 临时改重。

应走：

1. 只读缺口审计。
2. 明确补注册、补跑、repair 或 runless check event 的范围。
3. 分阶段执行。
4. 执行后对账。

### 8.3 Direct lake bootstrap 不等于 Dagster backfill

直接写 lake 的 bootstrap 适用于历史大批量文件生成或重建，但必须明确它不会自动生成对应 Dagster materialization/check event。

后续若需要 Dagster UI 状态一致，必须单独设计 runless event 或状态对账，不得混在 bootstrap 写文件里顺手做。

---

## 9. 新数据集与新 Sensor 的必备性能门禁

### 9.1 新数据集

新增数据集或修改数据集口径前，必须先完成：

1. 源接口请求量、分页次数、字段投影、限流影响测算。
2. 写入行数、reject 行数、失败 reason code 样本。
3. Parquet 文件大小、分区策略、预计文件数。
4. 下游消费者审计。
5. blocking checks 和 readiness 语义。
6. 大量历史数据的 bootstrap 策略。

### 9.2 新 Sensor

新增 sensor 前，必须写清：

1. 触发目标。
2. expected date 来源。
3. partition set。
4. ready 条件。
5. 单 tick 最大 RunRequest 数。
6. 单 tick 最大 Dagster API 调用数。
7. 单 tick 最大 DuckDB 文件扫描数。
8. cursor 字段。
9. 时间窗口。
10. 性能预算和超预算行为。

### 9.3 新 Batch Helper

新增 batch readiness/helper 前，必须提供：

1. 与正式 check 语义的映射表。
2. SQL 数量和文件扫描模型。
3. 10 天和 60 天性能样本，60 天可作为容量测试，不代表日常窗口。
4. 单元测试覆盖全 ready、缺文件、文件存在但 checks failed、未知日期 fail closed。
5. 静态门禁防止回流逐日 Dagster readiness。

---

## 10. 必须建立的测试和静态门禁

性能相关改动必须至少覆盖：

1. 正向测试：正常 ready 路径。
2. 负向测试：禁止项不会发生。
3. 缺文件测试：`materialized=False`。
4. 文件存在但 check 失败测试：`materialized=True, checks_passed=False`。
5. unknown date fail closed。
6. window-before-heavy-work 测试。
7. cursor 小型 payload 测试。
8. 静态门禁：禁止未批准的逐日 readiness helper、直接 event history 深扫、旧 helper 回流。
9. 性能样本：记录 elapsed_ms、文件数、日期数、SQL 次数。

若某项无法测试，必须在方案和交付说明中写清原因，不能默认通过。

---

## 11. 一票否决反模式

以下模式以后默认禁止：

1. sensor 热路径先跑重 DuckDB，再判断时间窗口。
2. 日常 sensor 默认扫 60 天窗口。
3. batch helper 内部按日期、频度循环执行重 SQL。
4. 逐日调用 Dagster event/check history 判断 readiness。
5. 只用文件存在或 row count 冒充 blocking check ready。
6. 为了性能新增状态实体，但没有证明 batch metadata 和 DuckDB/lake 方案不可行。
7. 把 current-listed-only 数据集当历史生命周期事实源。
8. 把 namechange 当生命周期事实源。
9. 在 cursor 写入大量明细。
10. 对正式 Dagster instance 做无界 dry-run、无界 event 读取或无界 runless event 写入。
11. 用 Python 逐行循环处理大体量 Parquet/SQL 结果。
12. 性能测试脚本本身采用错误的逐日深扫模型，却拿结果指导方案。
13. 方案文档只写“应该很快”“很慢”“不多”，不写真实数量和耗时。

---

## 12. 交付说明必须包含的性能对账

涉及性能的任务完成后，交付说明必须包含：

1. 本轮目标和依据文档。
2. 读写模型是否改变。
3. 触碰的热路径入口。
4. 性能测试或只读 profiling 结果。
5. 静态门禁结果。
6. 是否运行 `dg` 或访问正式 Dagster runtime。未运行也要说明。
7. 是否触碰正式 lake。未触碰也要说明。
8. 与本文规则不一致的地方及原因。

---

## 13. 相关文档

长期规范：

1. `lake_console/orchestrator/CODING_STANDARDS.md`
2. `lake_console/docs/design/dagster-asset-schema-contract-design.md`

已沉淀的专项经验：

1. `lake_console/docs/design/dagster-stk-mins-continuity-governance.html`
2. `lake_console/docs/design/dagster-stk-mins-continuity-governance-low-level-design.html`
3. `lake_console/docs/design/dagster-stk-mins-continuity-performance-optimization-plan.html`
4. `lake_console/docs/design/dagster-stk-mins-continuity-performance-optimization-low-level-design.html`
5. `lake_console/docs/design/dagster-stk-mins-qfq-sensor-hotpath-performance-fix-plan.md`
6. `lake_console/docs/design/dagster-batch-readiness-hotpath-governance-plan.md`
7. `lake_console/docs/design/dagster-batch-readiness-hotpath-governance-low-level-design.md`
8. `lake_console/docs/design/dagster-non-stk-mins-continuity-governance-plan.md`
9. `lake_console/docs/design/dagster-non-stk-mins-continuity-governance-low-level-design.md`
10. `lake_console/docs/design/dagster-bounded-continuity-selector-foundation-plan.md`
11. `lake_console/docs/design/dagster-bounded-continuity-selector-foundation-low-level-design.md`
12. `lake_console/docs/design/dagster-market-major-indices-sensor-performance-governance-plan.md`
13. `lake_console/docs/design/dagster-market-major-indices-sensor-performance-governance-low-level-design.md`
14. `lake_console/docs/design/dagster-new-lake-asset-performance-audit.md`
15. `lake_console/docs/design/dagster-asset-check-incremental-governance-plan.md`
16. `lake_console/docs/design/dagster-asset-check-incremental-governance-low-level-design.md`
