# 融资融券汇总（`margin`）维护与源端探测说明

- 状态：维护与探测链路已实现；Raw 直出迁移及自然探测于 2026-08-27 完成历史验收。现有运行限制见 §4。
- 更新时间：2026-09-10（按当前代码校准；未重新请求源端或核验生产）。
- 范围：Prod `margin` 汇总数据集，不是 `margin_detail` 明细接入或 DG Lake 方案。

## 1. 当前维护合同

事实源：[DatasetDefinition：`margin`](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/market_equity.py)。通用规则引用 [日期模型指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md) 与 [执行计划基线](/Users/congming/github/goldenshare/docs/architecture/dataset-execution-plan-refactor-plan-v1.md)。

| 项目 | 当前实现 |
| --- | --- |
| 动作 | `margin.maintain`；支持手动单日、区间及重试；已退出 `daily_market_close_maintenance` |
| 时间输入 | `trade_date` 或 `start_date + end_date`；区间按交易日历展开，不支持无时间全量 |
| 对象与 unit | 一个交易日 × 一个交易所；默认 SSE/SZSE/BSE，手动可选 `exchange_id` 子集；源端探测绑定不得筛选交易所 |
| 请求 | [_margin_params](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py) 生成单日 `trade_date=YYYYMMDD` 与单个 `exchange_id`，不由 Ops 拼正式业务参数 |
| 正式维护分页 | 每个 unit 使用 `limit=4000 / offset`，满页继续、短页结束；不要与探测的 `limit=1` 混淆 |
| 写入与观测 | `raw_only_upsert`，按 unit 提交；目标表及 freshness 观测目标为 `raw_tushare.margin` |
| 日期语义 | `trade_open_day / every_open_day / point_or_range`，观测字段 `trade_date`；发布日期策略 `next_open_day_0930` |

源资料：Tushare **doc_id=58**，[融资融券交易汇总](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/两融及转融通/0058_融资融券交易汇总.md)。当前显式请求九字段：`trade_date, exchange_id, rzye, rzmre, rzche, rqye, rqmcl, rzrqye, rqyl`。字段含义、金额/数量单位见源文档；本轮没有新增源端实测结论。

## 2. 自动探测与时间规则

用 `D` 表示数据所属开市日，`N` 表示下一个开市日。自动探测在 `N` 上午检查 `D`，正式任务仍处理 `D`；例如周五数据在下周一探测，而不是周六或维护周一数据。手动维护不受该探测窗口限制。

下列时间按 Asia/Shanghai 理解；**目标日期、探测窗口、freshness 判迟时点是三件事**：

| 项目 | 当前规则及责任方 |
| --- | --- |
| 目标日期 | [DatasetReleaseTargetService](/Users/congming/github/goldenshare/src/ops/services/dataset_release_target_service.py) 在 `N` 即可解析前一开市日 `D`，不必等到 09:00；非开市日或缺少可用日历时不解析 |
| 探测窗口 | schedule 配置固定 `09:00～09:30`、间隔 300 秒、每日额度 1；runtime 检查窗口和间隔，探测服务再核验业务日期 |
| 判迟时点 | 09:30 前 `is_release_due=False`，freshness 为 `unconfirmed`；09:30 起按应到日 `D` 与实际观测计算 `fresh / lagging / stale` 等状态，并非只要缺数就直接 stale |
| 就绪标准 | SSE、SZSE、BSE 各有匹配 `D + exchange_id` 的源端样本；任一未命中都不能触发正式任务 |
| 触发条件 | `remote_margin_ready` 只能绑定 `dataset_action: margin.maintain` 的纯 `probe` 模式；禁止 workflow、fallback、固定日期/区间、日期策略及 filters |

窗口、间隔和额度约束由 [ScheduleAutomationCapabilityResolver](/Users/congming/github/goldenshare/src/ops/services/schedule_automation_capability_resolver.py) 校验，[ScheduleProbeBindingService](/Users/congming/github/goldenshare/src/ops/services/schedule_probe_binding_service.py) 负责保存 ProbeRule；不再把全部校验归给 binding。页面消费后端能力合同，不自行计算 `D/N`。发布日期策略由 Definition 派生，不复制到 snapshot；该策略现在也由 `margin_detail` 使用，不是 `margin` 独占。

探测到写入的链路：

1. [MarginRemoteReadinessProbeService](/Users/congming/github/goldenshare/src/ops/services/margin_remote_probe_service.py) 校验绑定并解析 `D`。不能解析则返回 miss，零源请求。
2. 对三个交易所分别构造 `DatasetActionRequest(point=D)`，经 resolver 取得单个 unit。每个样本调用只追加 `limit=1 / offset=0`，字段为 `trade_date, exchange_id`；完整一轮为三次调用，不走正式维护的全字段分页。
3. 三者均匹配才命中；空行、错误日期、错误交易所为 miss。connector 异常交给 runtime 记录失败，不创建正式任务。探测只验证身份存在，不校验七个数值字段，也不直接写业务表。
4. [ProbeRuntimeService](/Users/congming/github/goldenshare/src/ops/services/operations_probe_runtime_service.py) 从结果的 `target_trade_date` 创建 `margin.maintain(point=D)`，正式 resolver 再展开三个 unit 并拉取九字段写 Raw。去重和每日额度限制见 §4。
5. ProbeRunLog 保留业务日、目标日、命中/缺失交易所、样本请求数及错误说明。探测日志和任务状态属于观测层，不能作为真实业务数据已齐备的替代证据。

## 3. 存储与安全边界

| 对象 | 当前合同 |
| --- | --- |
| [`raw_tushare.margin`](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_margin.py) | 唯一物理事实表；主键 `(trade_date, exchange_id)`；九个业务字段及 `api_name / fetched_at / raw_payload`；日期索引与 `(exchange_id, trade_date)` 索引 |
| [`core_serving.equity_margin`](/Users/congming/github/goldenshare/src/foundation/models/core/equity_margin.py) | 只读 view，显式投影九字段与 `fetched_at AS created_at / updated_at`；使用 Raw 底层索引，没有独立物理主键或索引 |

Definition 两个 DAO 名均为 `raw_margin`，交付模式为 `raw_with_serving_view / raw->serving_view`。Serving ORM 及注册仍保留读取映射；不能把 ORM 主键、索引元数据误当成尚存的 Serving 物理表，也不能因此删除读取入口。

[迁移 20260826_000152](/Users/congming/github/goldenshare/alembic/versions/20260826_000152_make_margin_raw_view.py) 只切换 Serving，保留 Raw 和既有索引，拒绝 Serving INSERT/UPDATE/DELETE，禁止自动 downgrade。该次迁移的 5,000 行/层安全容量是历史迁移门禁，不是日常同步上限；不重复执行迁移或据此清表。

Ops 状态写入不得阻塞或回滚业务提交，属于必须保留的架构约束，不因本文精简而放宽；本轮没有重新进行故障注入来证明所有异常路径。探测日志、运行成功与 Raw 实际数据要分别核验。

## 4. 已知运行限制，不作能力承诺

以下是 2026-09-10 代码审计结论，不在本次文档治理中改造：

- **失败/取消后不保证当天自动再试。** 去重查询只把同 schedule、同目标日的 probe 任务中 `queued/running/canceling/success/partial_success` 视为有效，确实排除了 failed/canceled；但更早执行的每日额度检查按该 rule 当天 `condition_matched=True` 的日志数计数。已有一次命中日志，即使对应任务后来失败，额度仍可能阻止下一轮。命中后去重的日志也会计入额度；“每日 1 次”不等于“每日成功 1 次”。
- **去重不是全局排他。** 查询限定 `schedule_id` 和 `trigger_source=probe`，不能承诺屏蔽其他 schedule 或人工创建的同日任务。
- **不保证整点七轮或 09:30 最后一轮。** runtime 按 `last_probed_at` 计算经过时间；窗口结束精确到 09:30:00。例如上次在 09:25:01，则 09:30:00 不足 300 秒，09:30:01 又已超窗。原“7 轮 × 3 = 21 次”只能作为理想时序估算，不是硬保证或请求限流器。
- **日期存在不等于三交易所全部落库。** probe 检查源端，freshness 主要按观测日期判迟；正式维护后仍需核对目标日三交易所身份、读取/保存/reject 及 Raw/view 数据，不能用一个新日期代替完整性验收。

若后续要改变重试、额度或末轮探测保障，应单独确认执行语义并补测试，不能只修改文档来宣称已经支持。人工重跑、自动任务修改和历史回补仍按独立授权执行。

## 5. 历史证据与回归入口

### 历史记录的保留方式

原 2026-08-01 文档记录了错误的收盘触发方式、当时源端仅部分交易所返回、生产最新日期 2026-06-18、30 个开市日缺口，以及重复维护固定历史范围的自动任务。这些是**当时的问题快照**，不再作为今天的生产现状或待执行删除清单。原设计全文可从 Git `4c263def:docs/datasets/margin-dataset-development.md` 追溯。

后续 [Raw 直出一期 LLD](/Users/congming/github/goldenshare/docs/governance/prod-postgresql-raw-direct-serving-phase-one-lld-v1.md) 的“2026-08-27 P1-B1-margin-M3b 自然 probe 验收与结案”小节已记录：

- revision `20260826_000152` 完成 Raw 唯一物理表、Serving 只读 view 切换。
- schedule **33** / rule **14** 在 **09:00:01** 自然命中，probe log **3674** 创建唯一 TaskRun **9573**，目标日为 **2026-08-26**。
- 三个交易所分别命中；正式任务及 node **15322** 成功，unit 为 `3/3/0`，读取/保存/reject/去重为 `3/3/0/0`，无重试。
- 目标日 Raw/view 各三行、三个交易所身份，业务字段及时间投影双向差异为 0；当时全表各 1,155 行和唯一身份，日期范围为 `2025-01-02..2026-08-26`。
- 当时 Raw 为 360,448 B，Serving 为 0 B view；`P1-B1-margin` M0～M3b 已结案。

因此不能继续笼统写“自动探测待首次生产验收”。上述记录也**不证明今天 schedule/rule 仍开启、旧固定任务已全部删除，或早期 30 日缺口逐日齐备**；需要处理这些事项时再做有范围的只读核验，不重新触发任务来补文档证据。

### 回归与验收

- [Raw/view 合同测试](/Users/congming/github/goldenshare/tests/test_margin_raw_view_m1.py)：storage、三交易所扇出、过滤、ORM、迁移 SQL 与禁止 downgrade。
- [发布目标测试](/Users/congming/github/goldenshare/tests/test_ops_dataset_release_target_service.py) 与 [freshness 测试](/Users/congming/github/goldenshare/tests/test_ops_freshness_snapshot_query_service.py)：目标日与判迟时点分离。
- [自动化能力测试](/Users/congming/github/goldenshare/tests/test_ops_automation_capability.py)、[工作流目录测试](/Users/congming/github/goldenshare/tests/test_ops_action_catalog.py)、[probe API/runtime 测试](/Users/congming/github/goldenshare/tests/web/test_ops_probe_api.py)：绑定、三交易所样本、任务目标、miss 与去重相关路径。局部分支测试不替代 §4 的完整调度链验证。

文档修改只跑离线合同与完整性检查；不因此创建测试数据库或生产任务。后续代码改造按 [开发模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md) 执行；真实验收应核对源端三交易所、正式三 unit、九字段读写、拒绝原因、Raw/view 对账及任务终态。无返回、时间越界与异常注入优先在获准隔离环境验证，不将 fake 数据或故障注入正式生产链路。
