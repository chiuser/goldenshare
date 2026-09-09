# `kpl_list` 次日发布适配与自动维护方案 v1

状态：主体代码已实现；历史研发记录未完成生产验收，当前生产配置及验收进展待核实。全量维护的配置约束缺口见 §3。

创建日期：2026-07-28；代码与文档口径核对：2026-09-10。

适用范围：`kpl_list` 自动维护、源站探测、freshness 与运行验收；不改写入模型、表结构或其他数据集。

本文分别记录现行代码、已确认配置、实现缺口与历史证据。通用日期策略见[自动任务日期策略](/Users/congming/github/goldenshare/docs/ops/ops-schedule-calendar-policy-plan-v1.md)，配置字段见 [API capability](/Users/congming/github/goldenshare/docs/ops/ops-api-reference-v1.md#automation-capability-schema)，状态投影边界见 [Ops 当前契约](/Users/congming/github/goldenshare/docs/ops/ops-contract-current.md)。本文不是生产切换、删除任务或补数的执行授权。

## 1. 发布规则与目标日期

本地源资料：[doc_id=0347，开盘啦榜单数据](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/打板专题数据/0347_开盘啦榜单数据.md)，记载“次日 8:30”更新。结合原专项核验，本项目采用下一**自然日**口径，在 `DatasetDefinition.source.release_policy` 声明 `next_calendar_day_0830`。

`DatasetReleaseTargetService` 按北京时间、Definition 与交易日历，选择满足以下条件的最新开市日 `D`：

```text
当前时间 >= D 的下一自然日 08:30
```

这只是“按发布规则应当可用”的日期，源端是否实际返回数据仍须探测；不是对准点发布的保证。普通周、无节假日时：

| 当前北京时间 | 目标日 | 原因 |
| --- | --- | --- |
| 周二 07:00 | 上周五 | 周一尚未到发布时点 |
| 周二 08:35 | 周一 | 周一已到发布时点 |
| 周六 08:35、周日 | 周五 | 周五数据在周六进入可用窗口 |

交易日历不足以确定目标日时不猜日期：probe 报失败且不创建任务，freshness 目标日无法确认。服务也已被其他发布策略复用，不再在本文维护“全仓只有两个策略”的历史枚举表；完整集合以 [source release policies](/Users/congming/github/goldenshare/src/foundation/datasets/source_release_policies.py)为准。

选择探测而非“每天 09:00 直接维护”的原因是：需要使用正确的已发布目标日，并在源端延迟时继续尝试。每天运行本身包含周六，不能把“覆盖不了周末”作为否定每日定时的理由。

## 2. 现行触发链路

条件为 `remote_kpl_list_ready`（源站已有开盘啦榜单），仅接受 `target_type=dataset_action`、`target_key=kpl_list.maintain`、`trigger_mode=probe`。绑定时拒绝 workflow、fallback、固定日期、日期范围和 `calendar_policy`；该限制针对本探测条件，不等于所有 KPL 手动或定时维护入口都被禁止。

执行顺序：

1. Probe runtime 检查配置窗口、间隔与当天命中上限；KPL 不因当前自然日非交易日而跳过。
2. KPL probe 通过统一目标日期服务取得 `D`，复用 `DatasetActionResolver -> unit -> _kpl_list_params` 生成目标日请求，样本固定为 `tag=竞价`。
3. 源请求仅追加探测专用 `limit=1`、`offset=0`、`fields=ts_code,trade_date,tag`。目标日、标签匹配一行即命中；空结果或不匹配记 miss，源错误记失败，均不创建维护任务。
4. **命中后**检查同一 schedule 是否已有该目标日的有效 probe TaskRun；没有才创建普通 `kpl_list.maintain`，明确写入 `time_input={mode: point, trade_date: D}`。
5. 正式任务走既有 ingestion 主链。探测自身不写业务表、不刷新 freshness；runtime 仍会保存探测日志及任务观测状态。

跨日去重匹配同一 `schedule_id`、`target_trade_date`、`trigger_source=probe`，并限定 KPL 维护动作：

- `queued/running/canceling/success/partial_success` 阻止重复创建；不跨不同 schedule 去重。
- `failed/canceled` 不阻止后续重试，但仍须满足窗口、间隔与当日上限。
- 周六已有周五有效任务，周日仍可能请求源站，然后记 `deduplicated`，不创建第二个任务。不能写成“周日不会请求源站”。
- 当前每日上限计数依据是本规则的 `ProbeRunLog.condition_matched=true`，包括去重命中，并非成功创建任务数。配置上限为 1 时，命中过一次后即使正式任务失败，也不能据此保证当天自动再试；后续自然日可重新判断。

固定竞价样本是已确认决策，不逐类探测，因为类别可以自然为空。样本命中不证明五类标签已全部发布或全部入库；若竞价自然为空，可能一直不触发，须先人工核实源端全标签返回，而非自行扩大探测范围。

## 3. 全量维护要求与已知实现缺口

**原方案要求保留：自动维护应使用空 `filters={}`，覆盖 `涨停/炸板/跌停/自然涨停/竞价` 五类标签，不缩小股票范围。** 探测用竞价样本，不应把正式任务也限制成竞价。

2026-09-10 静态核对的实现差距：

- KPL capability 的过滤模式为 `dataset_default`，没有强制空过滤条件。
- `ScheduleProbeBindingService` 将配置过滤条件写入规则；runtime 创建 TaskRun 时继续保留，只移除 `source_key`。
- 样本请求覆盖 `tag=竞价`，但保留其他过滤条件。因此配置了股票过滤时，连探测也可能被缩小。
- 空过滤配置下，正式任务按 Definition 默认值扇出五类标签；配置了标签或股票过滤则不再有全量保证。

因此，配置及真实验收必须检查 filters 为空，不能把“默认全量”写成“代码强制全量”。是否增加强制校验需单独批准代码变更；本次文档治理只记录缺口，不放宽原要求，也不修改 runtime。

## 4. Freshness 与已确认配置

KPL 的业务日期仍按 `trade_open_day + every_open_day` 连续覆盖，使用 `continuous_open_day` freshness 口径。期望业务日期与 probe 同样由 `DatasetReleaseTargetService` 计算；不另造 KPL freshness policy。

发布策略在 Definition 声明，目标日期服务解释策略；`ops.dataset_status_snapshot` 缓存观测结果与状态，不复制另一份发布规则。卡片/API 按现行查询和状态投影链路消费，前端不自行计算日期。以普通周二为例，08:30 前不要求周一已入库；08:30 后周一成为期望日期，缺失才应判滞后。这是计算口径，不是页面状态已实时刷新的证明。

原专项已确认的运营配置如下，不是后端锁定值，也不证明生产已采用：

| 项目 | 已确认值 |
| --- | --- |
| 模式、条件 | 纯 probe、`remote_kpl_list_ready`；无固定执行时刻和 fallback |
| 时区、窗口 | `Asia/Shanghai`，每日（含周末）08:35～23:30 |
| 探测间隔 | 30 分钟 |
| 每日上限 | `max_triggers_per_day=1`，实际计数语义见 §2 |
| 维护参数 | 无固定日期、范围或 calendar_policy；`filters={}` |

窗口内未命中时约 30 次轻量样本请求/日；正式维护扇出及分页另计。积分与配额按源资料和账号实际权限核实，不混用不同积分档位的分钟、每日限额。

## 5. 代码与回归定位

| 环节 | 当前代码 | 相关测试 |
| --- | --- | --- |
| 数据集与工作流 | [board_hotspot Definition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/board_hotspot.py)、[action catalog](/Users/congming/github/goldenshare/src/ops/action_catalog.py)：KPL 已移出 `daily_market_close_maintenance` 定义 | 本轮按左侧 Definition 与工作流成员静态核对 |
| 发布目标日 | [DatasetReleaseTargetService](/Users/congming/github/goldenshare/src/ops/services/dataset_release_target_service.py)、[freshness query](/Users/congming/github/goldenshare/src/ops/queries/freshness_query_service.py) | [目标日期测试](/Users/congming/github/goldenshare/tests/test_ops_dataset_release_target_service.py)：发布前后、周末、日历不足 |
| 探测请求 | [KPL probe](/Users/congming/github/goldenshare/src/ops/services/kpl_list_remote_probe_service.py)、[request builders](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py) | [Probe API 测试](/Users/congming/github/goldenshare/tests/web/test_ops_probe_api.py)：resolver 参数、miss、目标日任务 |
| 绑定与过滤 | [capability resolver](/Users/congming/github/goldenshare/src/ops/services/schedule_automation_capability_resolver.py)、[probe binding](/Users/congming/github/goldenshare/src/ops/services/schedule_probe_binding_service.py) | [Schedule API 测试](/Users/congming/github/goldenshare/tests/web/test_ops_schedule_api.py)：KPL 绑定与拒绝组合；不代表已补齐 §3 缺口 |
| 去重与上限 | [Probe runtime](/Users/congming/github/goldenshare/src/ops/services/operations_probe_runtime_service.py) | [Probe API 测试](/Users/congming/github/goldenshare/tests/web/test_ops_probe_api.py)：有效任务去重、failed 任务不阻止重试 |

后续代码回归还应关注：命中后去重仍计入当日上限、失败后的跨日重试、空过滤的五标签覆盖、页面不自行生成目标日。现有测试路径只是定位，不代表这些组合都已有测试，更不替代真实运行验收。本轮未重跑业务测试。

## 6. 历史证据与生产验收边界

### 2026-07-28 核验记录（不是当前数据状态）

原专项通过生产只读查询与 `tushareMcp.kpl_list` 记录：

| 交易日 | 当时源端五标签合计 | 当时库内情况 | 当时竞价样本行数 |
| --- | ---: | --- | ---: |
| 2026-07-22 | 278 | 已有，raw 与 serving 一致 | 141 |
| 2026-07-23 | 398 | 缺失 | 120 |
| 2026-07-24 | 271 | 缺失 | 153 |
| 2026-07-27 | 402 | 缺失 | 143 |

2026-07-28 13:12 请求当日五标签均为 0，而前一交易日有返回。当时状态投影显示最近业务日 07-22、最近成功时间 07-27 23:30、期望日 07-27；“任务成功”并不等于取到了目标日数据。旧入口在交易日 18:30、21:02、23:30 请求当日，形成了本次发布日期适配的背景。

历史研发记录说明：主体代码和自动化测试已完成，当次没有执行生产配置切换、真实验收或历史补数。2026-09-10 仅复核代码与文档，未重新查生产或请求源端，因此不能断言上述缺口今天仍存在，也不能宣布生产已完成迁移。

### 后续核实与执行顺序（须另获授权）

1. 先只读核实当前部署版本、工作流、既有 schedule/probe 配置及验收记录；代码已移除工作流中的 KPL，不应再要求运营修改这份源码定义。历史记录不能代替当前部署核验。
2. 如仍需切换，列出精确 schedule/rule ID、用途及变更清单，获批准后调整。不得照旧文档笼统停用或删除所有 KPL 任务，也不重复创建已有的正确配置；新配置须满足 §3、§4。
3. 获运行授权后，在源端已发布时点做一个业务日 `D` 的最小验证：任务日期为 `D`，五类标签都被请求；非空数据写入、空类别有解释，source/raw 行数及 raw/serving 对账一致。
4. 核实同一 schedule 下一自然日不重复创建 `D` 的有效任务；区分再次源请求、去重日志和新任务。核实发布时点前后的 freshness 期望日及状态投影更新。
5. 重新确定仍缺失的历史日期；确需补数时单独批准普通区间维护，完成后逐日逐标签对账。不按 7 月记录直接发起补数。

本方案不授权清理、删除或重建业务数据，不新增表、outbox、checkpoint 或迁移，不改变 normalizer/writer/DAO/幂等主键。到达发布时点、样本命中、代码测试通过都不等于生产数据完整；验收必须以当次真实读回证据为准。
