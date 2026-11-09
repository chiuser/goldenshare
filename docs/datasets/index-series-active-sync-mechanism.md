# Prod 指数日线现行机制与周、月线重建及更新方案

更新时间：2026-11-10。第 1 节说明指数日线现行机制。第 2 节起是已确认的改造口径，具体实现和验收见 [LLD](/Users/congming/github/goldenshare/docs/datasets/prod-index-period-low-level-design-v1.md)。开发和执行按阶段放行。

<a id="index-daily"></a>

## 1. 指数日线现行机制

`index_daily` 从 Tushare 取数，写入 `raw_tushare.index_daily`，符合日线服务范围的结果进入 `core_serving.index_daily_serving`。`ops.index_series_active` 按 `resource` 区分两个日线池。

| 日线对象池 | 职责 |
| --- | --- |
| `index_daily_raw` | 默认按池内指数代码和日期窗口向 Tushare 请求。显式指定指数代码时，按指定代码请求。 |
| `index_daily` | 筛选可以写入日线服务表的指数。显式指定代码仍受这个池约束。 |

本次改造的边界是指数周线和月线。指数日线的两个池、请求、入库、完整性审计和补漏继续执行[现行日线机制](/Users/congming/github/goldenshare/docs/ops/ops-index-daily-completeness-reconciliation-plan-v2.md)。实际表和执行入口以 [DatasetDefinition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/index_series.py)、[执行规划](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py)和[写入器](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py)为准。

<a id="index-period-rebuild"></a>

## 2. 周、月线改造范围

Prod 先确定周线和月线各自的历史截止日。首次历史补数补齐其他 9 个指数的正式周、月线 Raw，并清空两张周、月线服务表、重建 10 个指数的 Serving。其他 9 个指数的历史从正式周、月线 Raw 重建，北证 50（`899050.BJ`）的历史从 Raw 日线合成。之后 10 个指数均用 Raw 日线更新当前周、月 K 线，期末只为其他 9 个指数发布 Tushare 正式数据并覆盖同周期合成值。DG 接入、财势乾坤页面和指标接入另行处理。

| 数据集 | Tushare 接口 | Prod Raw 表 | Prod 服务表 |
| --- | --- | --- | --- |
| 指数周线 `index_weekly` | [doc 171](/Users/congming/github/goldenshare/docs/sources/tushare/指数专题/0171_指数周线行情.md) | `raw_tushare.index_weekly_bar` | `core_serving.index_weekly_serving` |
| 指数月线 `index_monthly` | [doc 172](/Users/congming/github/goldenshare/docs/sources/tushare/指数专题/0172_指数月线行情.md) | `raw_tushare.index_monthly_bar` | `core_serving.index_monthly_serving` |

Tushare 的指数周线、月线接口分别按周、按月发布。2026-11-09 实查，上证指数在这两个接口按当日查询均无返回，最新正式周线和月线分别截至 11 月 6 日和 10 月 30 日。[Tushare 更新说明](https://tushare.pro/document/1?doc_id=108)

## 3. 人工补齐 10 个指数的历史周、月线

1. 本阶段只人工补齐第 4 节列出的 10 个指数。核对指数基础信息的 `list_date`（发布日期），从各指数核实后的发布日期起，分别补到已选定的周线、月线历史截止日，包含这些指数在 2020 年以前已发布的历史。截止日分别取对应已结束周期的最后交易日。其他指数的历史回补暂缓。[指数基础信息 doc 94](/Users/congming/github/goldenshare/docs/sources/tushare/指数专题/0094_指数基本信息.md)
2. 北证 50 以外的 9 个指数，从 Tushare 下载已结束周期的正式周、月线，保留返回的 `trade_date`，核对分页、业务键和字段值。区间和分页的请求方式在 LLD 中核实。[现行请求构建器](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)
3. 北证 50 的历史周、月线从 `raw_tushare.index_daily` 合成。按交易日历核对每个周期自发布日期起应有的全部日线，日线齐全才生成，`trade_date` 为周期最后交易日，结果仅进入 Serving。缺日线时在历史补数任务报错中列出代码、周期和缺失交易日。
4. 周、月线 Raw 只保存 Tushare 返回的有效正式行情。期末全范围下载不按激活池裁剪。历史补数任务对其他 9 个指数核对正式 Raw 缺项并报告代码和期末日。北证 50 的历史完整性按日线合成结果核对。

## 4. 独立激活池与服务表清空重建

**周线、月线共用一个独立于日线的激活池。** 该池限定本阶段历史补齐、日更合成和 Serving 发布的指数范围。初始名单取财势乾坤「主要指数」的 [10 个配置代码](/Users/congming/github/goldenshare/src/biz/services/wealth/config/definitions/major_indices.cn_a.v1.json)。

`000001.SH`、`399001.SZ`、`399006.SZ`、`000688.SH`、`000300.SH`、`000905.SH`、`000852.SH`、`899050.BJ`、`000510.SH`、`000016.SH`。

首期在切换时录入并核对这 10 个代码，日常维护入口不开放周、月线池的增删。**二期必须提供周、月线激活池的独立增删能力。** 新增代码时一并处理从发布日期起的历史覆盖，移除代码时一并处理 Serving 中该代码的已有周、月线。日线对象池按现行机制管理。

发布前逐个核实指数发布日期、应有周期和实际缺口。历史重建从各指数发布日期起的第一根有效周 K、月 K 开始。其他 9 个指数核对 Tushare 正式周、月线的起止日期，保留源端的周期日期。北证 50 核对历史 Raw 日线覆盖及合成结果。发现实际缺口后，再按具体指数、周期和缺数情况决定如何处理以及是否影响切换。

名单和两类重建数据验收后，在批准的切换窗口内清空两张服务表并重新加载。全部旧服务记录退出，包括名单外记录及名单内旧合成记录。重建结果只含新池 10 个代码，其他 9 个指数可按代码和期末日回查正式周、月线 Raw，北证 50 可按代码和周期回查用于合成的 Raw 日线。切换期间隔离其他写入，待两张表完整重建后对外发布。历史下载、合成及对账在正式清空前完成。切换前准备两张表的回退数据和失败恢复办法。

重建验收核对两张服务表的代码集合、各指数的起始日期、周期覆盖及两类行情的来源和字段值，确认名单外记录与旧合成记录均已清除。日更结果按第 5 节验收。指数日线的池和服务结果按原合同回归。

历史重建验收后即可接日更。周线以 2026 年 11 月 6 日为历史截止日，其他 9 个指数的正式 Raw 及 10 个指数的 Serving 均补到这期，11 月 9 日起用日线合成新一周。月线单独确定历史截止日，再从当前月首个应有交易日起按日期顺序处理。人工和自动日更都按第 5 节检查上一交易日的连续性。

<a id="index-period-daily-update"></a>

## 5. 当前周期日更与正式数据覆盖

`period_start_date` 是 Serving 本地维护的周期标识。按配置的交易所日历取所属自然周或自然月的第一个开市日。自然周从周一开始，周一休市而周二开市时取周二。自然月从 1 日开始，取该月第一个开市日。日更合成和正式数据覆盖都在对应的周线或月线 Serving 表中，按 `(ts_code, period_start_date)` 定位同一根 K 线。这个组合在该周期内保持不变。[现行周期起点计算 `_resolve_index_period_start_date`](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py)

合成成功后，`trade_date` 更新为实际算到的交易日。发布正式数据时，`trade_date` 保留 Tushare 返回的日期。按交易日历确定上一交易日，用于日线合成前的连续性检查。按同一交易日历确定期末交易日，用于查询该期正式源数据。因此本方案无需增加 `end_date`。月中合成按实际计算截至日写入，月末日期校验只用于正式月线。

1. 每个交易日所需的指数日线写入 `raw_tushare.index_daily` 后，只读取池内 10 个指数的 Raw 日线。从该指数在本周、本月各自的首个应有交易日算到当天，计算范围以指数发布日期为下限。该指数在周期内的首个应有交易日可以创建 K 线。合成结果仅写入 Serving，字段格式和单位与 Tushare 正式周、月线一致。
2. 当前周期的 Raw 日线缺失时，保留上次成功合成的 K 线及其 `trade_date`。在周期首日之后，日更合成前必须检查 Serving 中该指数、该周期的合成记录，要求其 `trade_date` 等于交易日历中的上一交易日。记录不存在或日期不符时，保留原结果、报错并将更新任务标为失败，由人工处理。例如 11 月 9 日合成成功，10 日日线缺失，11 日即使已有日线，也因 Serving 仍是 9 日、预期为 10 日而失败。
3. 按完整交易日历判断周、月的最后一个交易日，周五休市时按当周实际最后开市日。期末收盘后按该交易日分页获取 Tushare 返回的全部正式行情，有效记录写入周、月线 Raw。正式发布只覆盖北证 50 以外的 9 个指数，按指数和周期更新 Serving，已有合成记录就覆盖同一根 K 线。正式发布无需通过日线合成的连续性检查，已发布的正式值不得再被合成覆盖。
4. 北证 50 的周线、月线在期末用完整周期的 Raw 日线合成，结果即该期 Serving 最终值。Tushare 正式数据不参与其 Serving 覆盖。其他 9 个指数的正式源延迟时，Serving 保留该期最后一次合成结果。正式维护缺项在数据后台现有任务详情的报错中列频率、代码、期末日及失败阶段。人工按原期末重新请求，补入 Raw 后按第 3 项发布。日更不回算已结束周期。
5. 管理员在数据后台配置自动任务触发日更。首期按 10 个指数的日线 Raw 在上海时间 22:00 前就绪来安排，每个交易日盘后周、月各执行一次。人工逐日补数选择周线或月线、目标交易日和需要处理的池内代码，使用同一计算和连续性检查。目标日须已收盘，且仍属于所选频率的当前周期。多个交易日未更新时，从第一个未成功的交易日起顺序执行。跨过目标交易日的上海时间午夜仍未完成的日更转人工。
6. 周线和月线分别执行并记录任务结果。同一频率内，通过检查的指数正常更新并保留写入结果。连续性检查失败的指数保留原 K 线，对应频率的任务标记失败，并记录该指数代码及预期、实际截至日。另一频率按自身检查结果执行。
7. 正式维护失败时，按原范围重新请求 Tushare，再依次更新 Raw 和 Serving。即使上次已经写入 Raw、仅 Serving 发布失败，也走相同的重新请求流程。重试按业务键更新，保留已确认的有效记录，首期不提供单独的发布恢复动作。

<a id="index-period-legacy-cleanup"></a>

### 移除两个旧合成入口

实施时移除普通周、月线写入器在源返回空或缺代码时触发的日线合成分支，以及独立运维动作、执行代码和工作流中的通用历史批量合成步骤。当前周期合成由日更流程负责，北证 50 的已结束周期由第 3 节的历史补数处理。核对手动维护、重试、工作流及其他服务表发布入口，确保已退出的合成路径不会被重新触发，名单外代码不会写进服务表。财势乾坤之外仍有行情接口直接读这两张表，实施前需核对服务范围收窄对调用方的影响。

### 涉及的代码和调用方

- [DatasetDefinition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/index_series.py)、[执行规划](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py)、[写入器](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py)、[服务表发布](/Users/congming/github/goldenshare/src/foundation/serving/publish_service.py)。
- [运维动作和工作流](/Users/congming/github/goldenshare/src/ops/action_catalog.py)、[任务执行](/Users/congming/github/goldenshare/src/ops/runtime/task_run_dispatcher.py)、[任务详情](/Users/congming/github/goldenshare/src/ops/queries/task_run_query_service.py)、[指数覆盖查询](/Users/congming/github/goldenshare/src/ops/queries/review_center_query_service.py)。
- [行情 K 线读取](/Users/congming/github/goldenshare/src/biz/queries/quote_query_service.py)、[现有分层测试](/Users/congming/github/goldenshare/tests/test_dataset_writer_index_layer_alignment.py)和[周期线数据库测试](/Users/congming/github/goldenshare/tests/test_index_monthly_postgres.py)。

## 6. 长任务要求与放行条件

本次 10 个指数的历史补齐按 Prod 长任务要求设计。本节的续跑用于恢复中断的历史补齐任务，迟到数据按第 5 节人工补 Raw。按[数据集开发模板 §0.3.5](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)细化后才能开发和执行。

| 事项 | 方案要求 |
| --- | --- |
| 单元和请求量 | 9 个指数的正式历史按频率、代码和经实测确认的日期窗口下载，现行源分页大小为 1,000 行。北证 50 历史合成按频率和已结束周期组织单元，从 Raw 读日线。两类单元分别测算总量、耗时、内存、失败续跑和末次对账的开销，正式历史另计分页和限流。 |
| 事务和续跑 | 内存限于单批次。单元分页齐全且通过校验后才提交对应范围，已提交结果可读回，按持久化事实续跑。按代码、交易日期和数据集幂等重放。禁止用一个跨全历史的事务下载和提交。服务表切换的锁与恢复单独测算。 |
| 进度和取消 | 沿 TaskRun 展示当前阶段、代码或窗口、已完成与总数、百分比和更新时间。分页、单元前后检查取消，停止领取新单元。TaskRun 与活动节点终态一致，进度记录失败不回滚已经提交的数据。 |
| 实施前核验 | 在 LLD 核实 10 个指数的发布日期、9 个指数的正式源区间和分页，以及北证 50 的历史日线覆盖。用真实样本校验合成字段和单位。核验正式维护失败后重新请求、服务表清理清单、并发隔离、写入与回退步骤。正式执行前完成代表性运行、取消、续跑、幂等重放及数据库读回验收。 |
| 批次完成 | 对账 9 个指数的源、Raw、Serving，以及北证 50 的 Raw 日线与 Serving 合成结果。缺口、拉取失败、拒绝和差异在任务中说明。日更验收覆盖管理员配置触发、历史截止后的逐日接续、过午夜转人工、单个指数断档而其他指数正常更新、北证 50 期末合成定稿，以及其他 9 个指数的正式覆盖和失败后重新请求。 |

## 附录 改造前的生产记录

- 2026-08-07 周线任务收到 0 行仍成功结束，写入 1,139 条合成周线，后来源端已能查到当周数据。2026 年 7 月旧月线曾提前截至 7 月 30 日，修复后仍有部分旧合成记录。[周线任务 7602](https://wealthworld.com.cn/app/ops/tasks/7602) · [月线重跑任务 14071](https://wealthworld.com.cn/app/ops/tasks/14071)
- 2026-11-09 补数读回显示，9 月 Raw 为 4,628 行，服务表为 1,165 行，其中 564 行来自源端、601 行由日线合成，旧服务池仍缺 51 个代码。10 月 Raw 为 4,647 行，服务表为 1,163 行，其中 564 行来自源端、599 行由日线合成，旧服务池仍缺 53 个代码。两次任务均成功，拒绝 0 行。[9 月补数任务 18874](https://wealthworld.com.cn/app/ops/tasks/18874) · [10 月补数任务 18873](https://wealthworld.com.cn/app/ops/tasks/18873)
