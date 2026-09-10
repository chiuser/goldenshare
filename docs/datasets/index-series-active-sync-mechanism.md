# 指数行情分层、对象池与周期线维护说明

更新时间：2026-09-10。状态：当前代码机制说明，已合并原 Raw/Serving 分层方案；历史执行证据见 §6。

适用范围：Prod 数据集 `index_daily`、`index_weekly`、`index_monthly` 及其对象池，不涉及 DG Lake。2026-09-04 月线修复记录为“代码与本地回归完成，待生产部署与验收”；本次未重新核实生产部署或历史数据校正状态，不能据此宣布已上线或仍未上线。

## 1. 分层与对象池

数据集身份、日期与表映射以 [index_series.py](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/index_series.py) 为准；股票周期线的不同日期规则见[日期指南 §4](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md#period-anchors)。

| 数据集 | Raw 表 | Serving 表 | 写入入口 |
| --- | --- | --- | --- |
| `index_daily` | `raw_tushare.index_daily` | `core_serving.index_daily_serving` | `raw_index_daily_serving_upsert` |
| `index_weekly` | `raw_tushare.index_weekly_bar` | `core_serving.index_weekly_serving` | `raw_index_period_serving_upsert` |
| `index_monthly` | `raw_tushare.index_monthly_bar` | `core_serving.index_monthly_serving` | `raw_index_period_serving_upsert` |

`ops.index_series_active` 的主键为 `(resource, ts_code)`，不是只有单一用途的池。本说明涉及两种资源：

| resource | 用途 | 当前消费者 |
| --- | --- | --- |
| `index_daily_raw` | 日线默认源站请求池，决定请求哪些指数 | planner 的 `_resolve_index_codes` / `_build_index_daily_units` |
| `index_daily` | 日、周、月线共同的 Serving 入库门禁 | writer 的 `_resolve_active_index_codes` |

模型见 [IndexSeriesActive](/Users/congming/github/goldenshare/src/ops/models/ops/index_series_active.py)，读取见 [DAO](/Users/congming/github/goldenshare/src/foundation/dao/index_series_active_dao.py)，建表历史见[迁移](/Users/congming/github/goldenshare/alembic/versions/20260404_000028_add_index_series_active.py)。`first_seen_date/last_seen_date/last_checked_at` 记录纳入或观测日期、检查时间；本文不固化当前代码数量。

共同边界：

- Raw 保存通过归一化校验的源站事实，不按 Serving 池裁剪，不写日线派生结果。它经过校验、去重和 upsert，不是原始响应逐行存档；不能把“返回多少就新增多少”当验收等式。
- Serving 只写命中 `index_daily` 池的行。显式 `ts_code` 仅限定源站请求，不能绕过 Serving 门禁；非 active 行不因未进入 Serving 而被算作业务拒绝。
- Serving 池为空时不写 Serving，不回退到 `index_basic`。对象池不是 TaskRun 观测数据，不得随任务清理；普通日线同步成功不会自动更新它。池审阅与重建见[指数完整性与激活池说明](/Users/congming/github/goldenshare/docs/ops/ops-index-daily-completeness-reconciliation-plan-v2.md)。
- 周/月线的 `source='api'` 表示源站周期行情，`derived_daily` 表示由 `core_serving.index_daily_serving` 派生。派生发生在对应周/月线维护中，日线同步不顺带重算周期线。

## 2. 请求、写入与事务

入口链路是 `DatasetActionRequest(action=maintain) -> Resolver -> Plan units -> source client -> normalizer -> writer`。Ops 保存意图；源参数只在 request builder 格式化，不在前端或 Ops 另算日期、对象池和派生规则。

- **日线**：默认按 `index_daily_raw` 池逐代码生成 unit；显式代码绕过默认请求池。point 请求带 `ts_code + trade_date`，range 带 `ts_code + start_date/end_date`。默认池为空时报 `universe_empty`，不会隐式扩大请求范围。
- **日线 Definition 的例外说明**：`universe_policy='no_pool'` 不代表运行时不读池；custom builder `build_index_daily_units` 实际读取请求池。若将其改成通用 universe 合同，必须另行审计，不能在文档整合中改模型。
- **周/月线**：generic planner 生成日期锚点 unit，builder 带 `trade_date` 及可选 `ts_code`；当前分页大小为 1000，源端分页全部成功后才归一化和写入。请求或后续分页失败不能解释成“没有数据”而转派生。
- **Raw 刷新区别**：周/月线未指定代码的 point/range 维护，在本批存在归一化行时，先按这些行的 `trade_date` 删除对应 Raw 日期，再 upsert；不是按 Serving 池裁剪，也不是整表清空。显式代码分支不做该按日全范围刷新。月线 Serving 的空返回保护不等于 Raw 具有相同保留规则。
- **事务与续跑**：三个数据集沿用 unit 事务，Raw 与 Serving 在同一 unit 提交；失败回滚当前 unit，之前已提交 unit 保留。月线依靠同月幂等键重放，不自动跳过已完成月份。TaskRun 状态或来源观测不得决定业务提交，失败不能回滚已提交业务数据。

代码入口：[unit_planner.py](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py)、[request_builders.py](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)、[normalizer.py](/Users/congming/github/goldenshare/src/foundation/ingestion/normalizer.py)、[writer.py](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py)、[executor.py](/Users/congming/github/goldenshare/src/foundation/ingestion/executor.py)。源资料见本地 [doc 171 指数周线](/Users/congming/github/goldenshare/docs/sources/tushare/指数专题/0171_指数周线行情.md)、[doc 172 指数月线](/Users/congming/github/goldenshare/docs/sources/tushare/指数专题/0172_指数月线行情.md)；本次未重新实测源接口。

## 3. 周线现状：不能套用月线保证

Definition 声明 `week_last_open_day`，但 planner 的区间实现只压缩**输入范围内**的开市日。例如范围截至周四，可以生成周四单元；point 也没有月线那套完整周期末校验。writer 聚合已有日线，不做月线的跨自然月与整周期日线完整性检查。

周线写入仍有不同分支：

- 无显式代码的 point/range 维护：API 行经过 Serving 池过滤，对缺少返回的 active 代码尝试日线派生；存在待写 Serving 行时，按结果日期删除旧行再插入。这个分支不具备“已有 API 永不被派生替换”的统一保护。
- 显式代码且有返回：按代码与周期/日期替换。非 active 代码只能写 Raw。
- 显式 active 代码的 point 维护成功空返回：派生写入前保护已有同周期 API 行；显式代码的 range 空返回不进入这条周线派生分支。

以上是当前代码事实，不是新增设计建议。月线修复刻意保留了周线行为，见 [test_weekly_clipped_range_keeps_existing_behavior](/Users/congming/github/goldenshare/tests/test_index_monthly_calendar.py) 和[周线实际 SQL 回归](/Users/congming/github/goldenshare/tests/test_index_monthly_postgres.py)。若要修正周线，须另行确认目标和影响面；不能借本次文档整合全局替换共享 writer。

<a id="monthly-rules"></a>

## 4. 月线规则与验收边界

### 日期与派生资格

1. planner/writer 共用 [load_index_month_open_dates](/Users/congming/github/goldenshare/src/foundation/ingestion/index_month_calendar.py)：整月每个自然日都必须有开闭市记录，缺失不能当休市。`trade_date` 是真实最后开市日，`period_start_date` 是第一个开市日。
2. range 只取落在输入范围内的真实月末交易日；截至 2026-07-30 不生成 7 月单元，截至 2026-09-01 不生成 9 月 1 日单元。point 非真实月末明确拒绝；日历不完整不能猜日期。
3. 派生必须等实际北京时间进入下一个自然月；月末当天即使收盘且日线齐全，也不派生。输入未来日期不能提前放行。该限制针对派生，不禁止合法源站月线在月末当天写入。
4. 对本次范围内的 active 指数，只有源站全部分页成功、本次没有该指数月线、库内也没有同月 API 行时，才可派生。源站归一化存在拒绝时，本批月线不进入派生，防止把拒绝当作源站缺失。
5. 按指数核验整月日线日期集合，不只看最大日期或行数；计算必要字段 `open/high/low/close/pre_close/vol/amount` 必须非空且有限，`pre_close` 不得为零。不填零、不跨日补齐、不缩短月份；不新增上市期间豁免。
6. 某指数日线不全不影响其他合格指数。派生只写 Serving，不改变既有 OHLC、量额和涨跌计算公式。

### 同月覆盖规则

月线业务身份为 `(ts_code, period_start_date)`；现有[月线模型](/Users/congming/github/goldenshare/src/foundation/models/core_serving/index_monthly_serving.py)的月份唯一约束不移除。

| 本次情况 | Serving 行为 |
| --- | --- |
| 取得同月源站月线或修订 | 覆盖旧派生或旧 API，更新截至日期及行情字段 |
| 成功请求但未返回，库内已有同月 API | 保留，不删除、不降级为派生 |
| 无同月 API，全部派生条件满足 | 新建或刷新同月派生行 |
| 月份未结束、日线不齐或字段无效 | 不新增派生、不以空结果删除旧行；不合格旧派生仍待校正 |
| 请求或分页失败 | 沿原错误路径失败，不写部分分页结果，不转派生 |

`_upsert_index_monthly_serving_rows` 使用月份唯一键条件 upsert，更新包括 `trade_date`；SQL 条件也保护并发 API 写入不被派生降级，`RETURNING` 统计实际写入。单代码和全范围沿用同一月线规则，不用忽略冲突代替修订，不先删整月 Serving 再插入。

### 执行与验收要点

- 月线一个月末全范围或显式单代码为一个 unit。完整月历最多 31 行；派生逐指数读取该月日线，SQL 只返回合格聚合结果，不将多月日线全集载入内存。沿用已有批量写入、取消/进度与事务边界，不增加分页提交、心跳或续跑状态。
- 月末当天缺源站结果的指数不会当场派生，最早下月再次维护该月份时处理。没有新增调度或自动补跑；历史修正须有有效替代结果，不能把旧派生仍存在视为已修复。
- 后续获准的大范围重跑先完成日线，再维护周线和月线（既有建议顺序为日→周→月），因为派生依赖日线 Serving；这不是授权现在重跑或清理。

| 回归重点 | 必须保留的反例/结果 |
| --- | --- |
| 日期与时间门禁 | 截断范围、非月末 point、月底周末/节假日、缺失日历、实际尚未跨月而输入未来日期 |
| 日线完整性 | 月初/月中/月末缺日、日期集合不同、必要字段空值/非有限值；不合格指数不派生 |
| 来源与范围 | 旧 7 月 30 日派生被 7 月 31 日 API 覆盖；API 修订、空返回保护、派生刷新、非 active 不入 Serving、单代码/全范围一致 |
| 失败与续跑 | 首页/后页失败、当前 unit 回滚、先前 unit 保留、取消/进程退出后读回与幂等重放、并发来源保护 |
| 共享代码 | 周线原行为及其他 planner 消费者不因月线修复改变 |

<a id="source-summary"></a>

## 5. 来源展示与只读核验

任务详情的 `progress.period_source_summary` 只适用于指数周/月线。[查询实现](/Users/congming/github/goldenshare/src/ops/queries/task_run_query_service.py)按**任务日期范围**查询当前 Serving 全部指数的 `source` 构成；不按本次 `ts_code` 过滤，也不是本次任务新增/修改行数或执行时冻结快照。后续维护修改同范围数据时，统计可变化。

返回 `total_rows/api_rows/derived_daily_rows/other_rows`，`start_date/end_date` 是命中数据实际覆盖日期；没有可解析日期范围或查不到行时返回 `null`。这是只读观测，不参与 writer 或业务事务。

以下只读查询使用绑定参数；日期须换成本次获准范围，不沿用旧文档的 2026 年 4 月样本范围：

```sql
select resource, count(*) as code_count, min(first_seen_date), max(last_seen_date)
from ops.index_series_active
where resource in ('index_daily_raw', 'index_daily')
group by resource;

select source, count(*) as rows, min(trade_date), max(trade_date)
from core_serving.index_monthly_serving
where trade_date between :start_date and :end_date
group by source;
```

核验周线时查询 `core_serving.index_weekly_serving`。比较日/周/月代码集合时也必须限定日期，差集只用于定位，不能直接要求三个集合相等；还要区分源站返回、派生资格及待校正数据。本次未执行生产 SQL，也不授权清空对象池、观测表或业务表。

<a id="monthly-history"></a>

## 6. 历史修复证据（非当前待执行清单）

### 原分层与对象池记录

2026-05-05 记录：Serving 池基于 2026-04-15 指数日线代码集合审阅后写入；这是当时来源，不证明当前池内容未变化。原分层改造将日线移入专用 writer，周/月线 Raw 不再受 Serving 池过滤。曾提出的六表清空重建和 M1–M6 清单已退出当前指引；不得据此清表、备份或重跑，历史全文从 Git 追溯。

### 2026-09-04 月线事故与修复

以下沿用当时生产只读审计记录，本次未重新查询生产：

| 证据 | 当时事实 |
| --- | --- |
| TaskRun 6891 | 2026-07-31 07:14:55 开始，范围 2026-04-30～2026-07-30，计划错误包含 7 月 30 日月线单元 |
| 交易日历与旧月线 | SSE 7 月 31 日开市；1,212 条 7 月月线却为 `trade_date=2026-07-30`、`source=derived_daily`，创建于 7 月 31 日 07:15:03，位于任务执行期间 |
| TaskRun 10869 | 9 月 4 日维护 2026-06-30～2026-09-01；6 月已提交，7 月 31 日写入失败，计划还错误包含 9 月 1 日单元 |
| 唯一键冲突 | `000001.SH` 旧行截至 7 月 30 日、新行截至 7 月 31 日，同属 7 月，触发 `uq_index_monthly_serving_ts_period` |

当时根因：月末压缩只看输入范围；日线派生不检查跨月与整月完整性；全范围 Serving 仅按截至日期删除后插入，遗漏同月不同截至日期旧行。修复提交 `caca5811` 已用 §4 的完整月历、派生资格、月份键覆盖处理；共享周线行为保持不变。

当时开发记录（不是本次新验收）：

- 先补复现测试，再修 planner、派生资格和同月覆盖，最后验证共享函数；未改 Definition/Plan 合同、源参数、执行器、Ops、页面或配置，没有迁移、清表和部署。
- 本地 doc 172 对照实测：`000001.SH + trade_date=20260731` 显式 11 字段返回 1 行；`trade_date=20260730` 默认字段返回 0 行。单月全范围样本 1,998 行，按 1,000 分页约两页；不是今天的源端规模保证。
- 开发前 resolver/writer 基线 114 项；开发后核心及架构门禁 251 项通过（含 39 项隔离 PostgreSQL 用例和周线实际 SQL 回归），自动任务月末相关 4 项通过；Ruff、definition lint、文档检查通过。
- PostgreSQL 验证当时使用临时集群及独立测试库，覆盖实际约束、来源保护、事务回滚、取消重跑和子进程退出；没有使用本机业务库或 Prod。本次不创建测试实例。
- CodeGraph 当时覆盖 resolver、共享日期入口、writer、执行器和 Ops；核对手动预检、自动日期策略、freshness、日期审计、来源统计及页面时间选择。该记录不证明今天生产部署或历史数据校正完成。

当时后续事项为部署后维护受影响的已结束月份。代码完成不代表历史数据修复；无源站替代且日线不齐时旧行仍保留。“待校正”只是说明，不是新状态字段；是否部署、重跑或单独删除错误数据需另行确认。

## 7. 代码与测试维护入口

| 关注点 | 现有测试 |
| --- | --- |
| 请求池、显式代码与日期/参数规划 | [resolver 测试](/Users/congming/github/goldenshare/tests/test_dataset_action_resolver.py) |
| Raw/Serving 分层、非 active 隔离、空池不兜底 | [writer 分层测试](/Users/congming/github/goldenshare/tests/test_dataset_writer_index_layer_alignment.py) |
| 月线真实月末与周线差异 | [月历测试](/Users/congming/github/goldenshare/tests/test_index_monthly_calendar.py) |
| 月份唯一键、完整性、来源、事务及进程退出 | [隔离 PostgreSQL 测试](/Users/congming/github/goldenshare/tests/test_index_monthly_postgres.py) |
| 来源统计 API 与页面展示 | [API 测试](/Users/congming/github/goldenshare/tests/web/test_ops_task_run_api.py)、[页面测试](/Users/congming/github/goldenshare/frontend/src/pages/ops-task-detail-page.test.tsx) |

2026-09-10 文档审计使用 CodeGraph `status/query/impact` 和当前代码交叉核验，定向离线测试 24 项通过（95 项未选）；未重跑 PostgreSQL 集成测试、未查询生产或重新实测 Tushare。合并不改变子系统边界、API/CLI、数据模型或执行行为。

后续若修改对象池来源、共享 planner/writer 或合同，按根 AGENTS 重新审计所有消费者并同步本说明、日期指南及相关测试，不能把本次文档审计当成代码改造或生产执行授权。
