# 指数技术因子（专业版）维护说明

更新时间：2026-09-10。状态：现行实现说明，已合并原接入方案与 LLD。本文区分代码事实和历史验收，不作为重新迁移或同步生产的指令。

依据：[DatasetDefinition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/index_series.py)、[日期消费指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)、[执行计划与可靠执行](/Users/congming/github/goldenshare/docs/architecture/dataset-execution-plan-refactor-plan-v1.md)、[数据集模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)。源资料为 [Tushare doc 358](</Users/congming/github/goldenshare/docs/sources/tushare/指数专题/0358_指数技术因子(专业版).md>)；本文不重新认证源端当前行为或账户配额。

## 1. 范围与使用入口

`idx_factor_pro.maintain` 维护 Tushare 按交易日返回的全量指数技术因子，不按指数激活池筛选。正式路径为：

```text
手动日期意图 / 自动探测命中
  -> Ops TaskRun -> DatasetActionResolver -> 每个开市日一个 unit
  -> Tushare 分页 -> 归一化 -> raw_tushare.idx_factor_pro
  -> core_serving.index_factor_pro 普通视图
```

- 手动维护支持单日或日期区间；无 `ts_code` 等业务筛选输入。
- 自动任务仅支持“探测触发”和“定时 + 探测兜底”，规则见 §4；不能把手动的 point/range 能力直接当作自动任务配置能力。
- Ops 展示在“A股指数行情”（`index_market_data`，排序 45）；底层 domain 仍为 `index_fund`。
- 不加入既有 workflow、不预置自动任务、不新增补漏链路、不接入 Dagster/Lake；`schedule_enabled=True` 不代表生产已存在或启用了 schedule。
- 不新增 Serving 物理副本，不引入股票复权因子门禁或专用历史重刷规划。股票因子差异见[股票技术面因子维护说明](/Users/congming/github/goldenshare/docs/datasets/stk-factor-pro-dataset-development.md)，不能套用旧“依赖股票对象池”的描述。

## 2. 输入、执行与日期观测

| 层次 | 当前口径 |
| --- | --- |
| 手动输入 | point 用 `trade_date`；range 用 `start_date/end_date`；`filters={}` |
| 日期模型 | `trade_open_day + every_open_day`；`point_or_range`；观测字段为 `trade_date` |
| 规划 | `generic`、`no_pool`；point 一日一个 unit，range 按交易日历展开开市日 |
| 源端请求 | builder 只生成 `trade_date=YYYYMMDD`；不透传区间、代码或 Ops 自定义分页参数 |
| 分页 | `offset_limit`，每页 8,000 行；不足一页结束，满页继续 |
| 观测 | freshness 为 `continuous_open_day`；完整性为 `date_bucket`，不做激活池代码矩阵审计 |

运营选择日期区间是维护意图，不是直接调用源接口的 `start_date/end_date`。例如一个含 23 个开市日的区间生成 23 个单日 unit，不按“指数代码数 × 日期数”扇出。

实现入口：[resolver](/Users/congming/github/goldenshare/src/foundation/ingestion/resolver.py)、[unit planner](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py)、[request builders](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py) 的 `_idx_factor_pro_params()`、[source client](/Users/congming/github/goldenshare/src/foundation/ingestion/source_client.py) 的 `fetch()/iter_pages()/_fetch_page()`。不能根据旧伪代码新增不存在的方法或错误类型。

日期桶有数据、最近业务日期较新，都不证明源站全部指数已齐备。本数据集不读取 `index_daily/index_daily_raw` 激活池或 DG 动态分区来限定请求、写入与预期代码集合；历史覆盖比较只用于解释这一设计。

## 3. 字段、存储与事务

字段唯一入口为 Definition 中的 `IDX_FACTOR_PRO_SOURCE_FIELDS` / `IDX_FACTOR_PRO_VALUE_FIELDS`。本次核对为 89 个源字段（2 个身份字段、87 个数值字段）；字段名、顺序和指标含义分别查 Definition 与 doc 358，不在本文再复制整张字段表。

| 对象 | 当前定义 |
| --- | --- |
| Raw | `raw_tushare.idx_factor_pro`，主键 `(ts_code, trade_date)`；身份列为 `VARCHAR(16)/DATE`，87 个数值列为可空 `Float(53)` |
| Raw 附加字段 | `api_name`、`fetched_at`、`raw_payload`；不进入源字段请求 |
| 索引 | 主键索引之外只有 `idx_raw_tushare_idx_factor_pro_trade_date`；不重复创建同序主键索引 |
| Serving | `core_serving.index_factor_pro` 普通视图：显式投影全部源字段，另加固定 `source=tushare` 与来自 `fetched_at` 的 `created_at/updated_at`；不暴露 Raw 的 `api_name/raw_payload` |
| 写入 | `raw_only_upsert`，按 Raw 主键幂等写入；结果的 `target_table` 仍指向 Serving 视图 |

[Raw ORM](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_idx_factor_pro.py)和[视图 ORM](/Users/congming/github/goldenshare/src/foundation/models/core/index_factor_pro.py)从 Definition 派生数值列；[迁移 20260801_000120](/Users/congming/github/goldenshare/alembic/versions/20260801_000120_add_idx_factor_pro_dataset.py)保留当时的显式字段定义。字段变更须同步核验 Definition、ORM、迁移与视图，不以文档字段数代替逐列对账。

[normalizer](/Users/congming/github/goldenshare/src/foundation/ingestion/normalizer.py)转换交易日期与数值；缺少 `ts_code/trade_date` 会记录 reject，无独立行转换或激活池过滤。[writer](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py)会取得 Raw 和 Serving DAO 元数据，但本写入分支只调用 Raw upsert；不能因 Serving 不参与写入就删除它的 DAO、ORM 或观测映射。

“维护流程不写视图”不等于“数据库强制拒绝所有视图 DML”。现有迁移与 writer 护栏测试不能证明后一项；本轮不新增数据库权限或拒写机制。

每个交易日的分页结果先汇集、归一化，再按 `commit_policy=unit` 写入提交。已提交日期与未提交日期分开；Ops 状态写失败不得回滚业务数据。内存随单日结果增长，并非仅一页大小；分页上限也不是每日总量上限。`max_units_per_execution=None` 不构成历史区间容量保证。幂等 upsert 不等于已证明进程退出后可靠续跑；长范围任务仍按[执行计划的事务与恢复约束](/Users/congming/github/goldenshare/docs/architecture/dataset-execution-plan-refactor-plan-v1.md)和模板 §0.3.5 单独验证，本轮不扩展代码改造。

## 4. 自动任务与源站探测

条件为 `remote_idx_factor_pro_ready`，展示为“源站已有指数技术因子”。它只判断源站是否**开始返回当天开市日数据**，不验证全量指数齐备。

### 配置与职责

- [ScheduleAutomationCapabilityResolver](/Users/congming/github/goldenshare/src/ops/services/schedule_automation_capability_resolver.py)统一声明、校验该动作的自动化能力：仅 `probe/schedule_probe_fallback`，禁止固定日期、日期区间、`calendar_policy` 和非空 filters；最小探测间隔 300 秒，每条规则每日触发上限固定为 1。
- [ScheduleProbeBindingService](/Users/congming/github/goldenshare/src/ops/services/schedule_probe_binding_service.py)将通过校验的自动任务意图持久化为 ProbeRule；不另维护一套该数据集专用配置校验。
- [自动任务页面](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-task-auto-tab.tsx)消费 action 返回的 `automation_capability`，不靠新增数据集页面分支决定条件和禁填字段。该动作不提供本地 `freshness_latest_open` 条件。
- 运营配置窗口和频率；不凭印象写死源站发布时间。纯 probe 与带兜底执行时间是两种触发方式，不是单日/区间两种维护输入。

### 运行链路

1. [ProbeRuntimeService](/Users/congming/github/goldenshare/src/ops/services/operations_probe_runtime_service.py)检查规则窗口、间隔及每日触发上限，再调用[专用探测服务](/Users/congming/github/goldenshare/src/ops/services/idx_factor_pro_remote_probe_service.py)。
2. 服务按 `Asia/Shanghai` 当前自然日查询交易日历；日历缺失或当天不开市，零次源请求并返回 miss，不回退为上一开市日。
3. 以当天日期和空 filters 构造 point 意图，经 resolver 生成唯一 unit；只在探测调用中追加 `fields=(ts_code,trade_date), limit=1, offset=0`。
4. 第一行的日期匹配当天且代码非空才命中；空结果、错日期、缺字段为 miss，源异常由 runtime 记录 error，不创建任务。
5. 命中后按去重规则创建标准单日 TaskRun，`trigger_source=probe`、`filters={}`；全部字段的正式分页、清洗与写入仍由 ingestion 执行。Probe payload 进入日志，不代替业务写入或 freshness/snapshot 刷新。

去重不是全系统“同日只能同步一次”：runtime 核验同 schedule、同目标日的有效 probe TaskRun，规则重建也不能绕过这一判断；[schedule 执行服务](/Users/congming/github/goldenshare/src/ops/services/operations_schedule_service.py)在兜底到期时检查同日有效 probe 任务，避免重复创建。不得把每条规则的上限理解为跨手动任务、跨 schedule 的全局互斥。

不采用五个固定指数逐只探测：该方案虽然做过历史可行性试验，但会要求绕过或扩展当前不允许 `ts_code` 的输入合同。探测参数不能写回 Definition、TaskRun 维护参数或隐藏运营字段。

## 5. 性能与验证入口

在无重试、单次扫描期间源端结果稳定且 offset 分页如约返回的前提下，单日 N 行的请求数为 `floor(N/8000)+1`；整页结尾还要请求空页确认结束。区间按各日求和，重试与独立 probe 请求另计。不能用单日样本推断所有历史日期的规模或耗时。

doc 358 的本地资料记载积分档位为 5000 积分 30 次/分钟、8000 积分以上 500 次/分钟；这不是本轮对当前账户权限、剩余配额或实际吞吐的核验。禁止把单日全量改成逐代码扇出，也不能把无日期单指数的一次返回当作完整历史。

| 核验点 | 现有入口 |
| --- | --- |
| Definition、日期 unit、非法 filters | [registry 测试](/Users/congming/github/goldenshare/tests/test_dataset_definition_registry.py)、[resolver 测试](/Users/congming/github/goldenshare/tests/test_dataset_action_resolver.py) |
| 89 字段透传、满页续拉、日期与数值转换、身份缺失 | [source client 测试](/Users/congming/github/goldenshare/tests/test_dataset_source_client.py)、[normalizer 测试](/Users/congming/github/goldenshare/tests/test_dataset_normalizer.py) |
| Raw-only、模型字段与迁移视图 | [writer 测试](/Users/congming/github/goldenshare/tests/test_dataset_writer_idx_factor_pro.py)、[模型合同测试](/Users/congming/github/goldenshare/tests/test_idx_factor_pro_model.py) |
| 自动能力、探测、绑定与兜底 | [capability 测试](/Users/congming/github/goldenshare/tests/test_ops_automation_capability.py)、[probe 测试](/Users/congming/github/goldenshare/tests/web/test_ops_probe_api.py)、[schedule API 测试](/Users/congming/github/goldenshare/tests/web/test_ops_schedule_api.py) |
| 展示与观测消费者 | [catalog 分组](/Users/congming/github/goldenshare/src/ops/catalog/dataset_catalog_views.py)、[Definition 投影](/Users/congming/github/goldenshare/src/ops/dataset_definition_projection.py)、[freshness 策略](/Users/congming/github/goldenshare/src/foundation/datasets/freshness_policies.py)、[观测注册](/Users/congming/github/goldenshare/src/ops/dataset_observation_registry.py)、[日期完整性服务](/Users/congming/github/goldenshare/src/ops/services/date_completeness_audit_service.py) |
| 不加入既有工作流 | [workflow 目录实现](/Users/congming/github/goldenshare/src/ops/action_catalog.py)、[action catalog 测试](/Users/congming/github/goldenshare/tests/test_ops_action_catalog.py) |

这些入口不表示本轮全量运行了 Web/API 或生产测试。后续若获准做真实验收，应核对源端读取、归一化、去重/reject、实际写入与目标日期数据；解释每类差异，核对 Raw/view 的身份、字段、行数及 Ops 观测。upsert 行数不能直接当新增行数，也不能无条件要求重跑写入量等于既有整日总量。

若分页失效、字段集合漂移，或需要隐藏参数/对象池才能实现新的就绪含义，应停下重新评审；不得在本文合并中更改现行合同。新迁移必须接届时真实 head，不能沿用历史 revision 的“当前 head”称谓。

## 6. 历史证据与验收边界

### 2026-08-01 接入与源端实测

以下为原两份文档保留的历史记录，不是 2026-09-10 重新查询结果：

- 接入前：候选业务表、字段、相关 TaskRun、状态快照查询均为 0，当时尚无本数据集代码。
- 同日完成 M1–M5 本地实现；M1 定向测试 210 项、M5 定向回归 399 项，以及当时的 lint、前端与文档检查通过。
- 当时 migration head 为 `20260801_000120`（父 revision `20260625_000119`）；记录时尚未执行生产迁移和真实单日同步。该状态只属于当时。

| 当时请求 | 历史结果 |
| --- | --- |
| 不传业务参数 / 只传日期区间 | 返回 `50101`，要求至少有 `ts_code` 或 `trade_date` |
| `trade_date=20260731`，两个身份字段 | 3,146 行、3,146 个代码 |
| 上述请求分别加 `limit=1, offset=0/1` | 分别返回 `000094.SH/000096.SH`，证明当时 offset 生效；MCP 公开 schema 虽未列分页参数，实际调用接受 |
| 仅 `ts_code=000001.SH` | 返回恰好 8,000 行，日期 `19930908..20260731`；单次结果不能证明完整历史 |
| 同代码加 `20260701..20260731` 区间 | 返回 23 行；显式请求全部 89 个字段时每行字段齐全 |

当时五个代码 `000001.SH/399001.SZ/399300.SZ/000016.SH/000905.SH` 分别加目标日及 `limit=1,offset=0` 都命中；只证明精确请求可行，不代表采用了固定代码探测，也不证明全部指数发布完成。

### 当时的覆盖比较与后续运行记录

| 2026-08-01 比较的集合 | 代码数 | 与 2026-07-31 因子集合重合 |
| --- | ---: | ---: |
| `index_daily` 服务激活池 | 1,216 | 1,212，缺 4 |
| `index_daily_raw` 请求池 | 3,052 | 2,049，缺 1,003 |
| 当日因子集合 | 3,146 | 其中 1,934 不在服务激活池 |
| DG `cn_a_index_ts_codes` 动态分区 | 820 | 820 |

服务激活池当日缺失代码为 `480055.CNI/480056.CNI/480057.CNI/931598.CSI`。这些结果解释为什么不把其他链路对象池作为本数据集过滤器；单日缺失不证明永久不可用，DG 比较不构成运行依赖。

后续[业绩快报专项 M3 生产记录](/Users/congming/github/goldenshare/docs/datasets/equity-express-low-level-design-v1.md#206-m3-生产验收记录)记载 `idx_factor_pro TaskRun#7924` 成功。因此不能继续以“生产同步从未执行”描述当前状态。但该旁证不包含本数据集源端—Raw—view 全量对账，不能替代其完整发布验收。

本轮仅核对仓库代码、测试和历史记录，未查询当前生产 revision、数据、schedule 或源端接口；不宣称生产验收已结案。旧文档全文可从 Git 提交 `a0df5e1a` 追溯。
