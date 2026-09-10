# 每日停复牌（`suspend_d`）维护说明

- 状态：当前为 Raw-only 写入、Serving view 查询；Raw 直出专项已于 2026-08-29 记录结案。
- 更新时间：2026-09-10（按当前代码校准；未重新请求源端或核验生产）。
- 范围：Prod `suspend_d` 维护及数据库消费者。本文不替代本地 DG 停牌事实专题，不改变两条链路各自的读取口径。

## 1. 当前维护合同

事实源：[DatasetDefinition：`suspend_d`](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/market_equity.py)。日期与执行通则见 [日期模型指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md) 和 [执行计划基线](/Users/congming/github/goldenshare/docs/architecture/dataset-execution-plan-refactor-plan-v1.md)。

| 项目 | 当前实现 |
| --- | --- |
| 动作与入口 | `suspend_d.maintain`；支持手动、调度及重试，已纳入 `daily_market_close_maintenance` |
| 运营目录 | `reference_data / A股基础数据`；这是目录分类，不是 Definition 的业务域 |
| 时间输入 | 单日 `trade_date` 或区间 `start_date + end_date`，禁止无时间全量 |
| 日期模型 | `trade_open_day / every_open_day / point_or_range`；区间按默认交易所日历展开，`DEFAULT_EXCHANGE` 默认 SSE，不是本数据集硬编码 SSE |
| 代码过滤 | 可选 `ts_code`；builder 去首尾空格并转大写，不是原样传递；无对象池扇出 |
| 类型过滤 | 可选多选 `suspend_type`：S 停牌、R 复牌；不选时不传，选择后由 planner 展开为合法单值 unit |
| 分页 | 每个 unit 内按 `limit=5000 / offset` 分页；满页继续、短页结束，不设置任意最大页数 |
| 写入与进度 | 只写 Raw，按 unit 提交；进度计数为执行单元而非日期数，另报读取、写入和拒绝数量 |

类型选择的实际展开：单日不选类型为 1 个无类型过滤 unit；单日同时选 S/R 为 2 个 unit；两个开市日同时选 S/R 为 4 个 unit。非法类型在规划前拒绝；[_suspend_d_params](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py) 遇到未展开列表会报错，不能将列表字符串直接发送给源端。区间日期与类型规则对手动和工作流维护共用。

采集使用现有日历和通用 ingestion；没有因本文新增采集前置步骤。“无额外采集级联”不代表没有下游消费者，见 §3。自动任务配置按现行 [Ops 自动化合同](/Users/congming/github/goldenshare/docs/ops/ops-contract-current.md) 使用，不在本篇重复定义页面控件及调度模式。

## 2. 源字段、存储与幂等

本地来源：Tushare **doc_id=214**，[每日停复牌信息](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/行情数据/0214_每日停复牌信息.md)。当前每页显式请求四字段：`ts_code, trade_date, suspend_timing, suspend_type`；源资料标注不定期更新。本轮未重新实测源接口，不将源文档样例代替当前字段映射。

| 对象 | 当前合同 |
| --- | --- |
| [`raw_tushare.suspend_d`](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_suspend_d.py) | 唯一物理事实表；自增 `id` 为物理主键；四个源字段、`row_key_hash` 及 `api_name / fetched_at / raw_payload` |
| Raw 索引 | `uq_raw_tushare_suspend_d_row_key_hash` 唯一索引，以及 `idx_raw_tushare_suspend_d_trade_date`、`idx_raw_tushare_suspend_d_ts_code_trade_date` |
| [`core_serving.equity_suspend_d`](/Users/congming/github/goldenshare/src/foundation/models/core/equity_suspend_d.py) | 只读普通 view；显式投影 `id, row_key_hash, ts_code, trade_date, suspend_timing, suspend_type, created_at, updated_at`，不保存第二份数据 |
| 时间与字段长度 | view 两个系统时间均来自 Raw `fetched_at`，不承诺旧 Serving 历史 `created_at` 不变；两层 `suspend_timing` 为 varchar(128)、`suspend_type` 为 varchar(16) |

`suspend_timing` 可能包含多个日内时段，例如 `09:30-10:31,10:31-13:02,13:42-14:57`，不得截断。view 没有物理主键或索引，查询使用 Raw 底层索引；Serving ORM 的主键、索引元数据仍用于映射，不能据此认为旧物理表尚存，也不能删除当前读取入口。

幂等身份由 [build_suspend_d_row_key_hash](/Users/congming/github/goldenshare/src/foundation/services/transform/suspend_hash.py) 生成：

- 按 `ts_code, trade_date, suspend_timing, suspend_type` 的固定顺序序列化，以 `|` 拼接后计算 SHA-256；None 序列化为空串，日期对象使用 ISO 日期。
- `row_key_hash` 是写入冲突键，**不是物理主键 id，也不是“股票代码＋日期”**。相同序列化事实重跑按同一 hash upsert；时段或类型改变会形成不同 hash。
- 因此同一股票同一天可以有多条不同事实。当前 Raw-only writer 不按股票/日期清除旧记录，不能承诺“源端改过时段后自动覆盖旧事实”，也不能把同日多条直接判成重复并删除。

Definition 两个 DAO 名均为 `raw_suspend_d`，`write_path=raw_only_upsert`，`conflict_columns=(row_key_hash,)`；view 在同一事务内反映 Raw 更新。独立拒写 trigger 对 Serving INSERT/UPDATE/DELETE 返回 SQLSTATE `55000`，不通过 view 修数。

## 3. 当前消费者与观测边界

以下均是当前读取 Serving view 的代码，不能与本地 Silver 消费者混为一条链路：

| 消费者 | 当前查询口径 |
| --- | --- |
| [市场情绪计算](/Users/congming/github/goldenshare/src/biz/services/market_mood_calculator.py) | 按日期/代码关联去重后的停复牌记录，生成 `is_suspend` 并在统计中排除；当前未筛选 `suspend_type=S` |
| [指数详情](/Users/congming/github/goldenshare/src/biz/queries/wealth/market/index_detail/index_detail_query.py) | 以 S 记录判断停牌；优先使用日线涨跌幅，缺日线涨跌幅且命中停牌时取 0 |
| [板块成员](/Users/congming/github/goldenshare/src/biz/queries/wealth/market/sector_overview/sector_member_query.py) | 对当日 S 记录对应的股票隐藏涨跌幅 |
| [有效 A 股池](/Users/congming/github/goldenshare/src/biz/services/wealth/market/sector_overview/effective_a_stock_pool_query.py) | 按成员股票/日期构造 S 类型停牌集合，用于有效池筛选 |
| [板块热度数据源](/Users/congming/github/goldenshare/src/biz/services/wealth/market/sector_overview/sector_heat_source_query.py) | 读取计算日期和股票范围内的 S 记录，按日期/代码去重，并结合完成证据检查日期 |
| [连板梯队](/Users/congming/github/goldenshare/src/biz/queries/wealth/market/streak_ladder/streak_ladder_query.py) | 对缺行情的股票检查当日 S 记录，区分 `SUSPENDED` 与 `MISSING` |

这些是现行实现差异，不表示本文批准统一过滤或重新定义“全天停牌”。涉及消费者语义调整须单独审计并确认，本轮不改查询。

Ops 的 [freshness 投影](/Users/congming/github/goldenshare/src/ops/dataset_definition_projection.py) 从 Definition 取 `raw_tushare.suspend_d / trade_date`；当前 freshness 策略仍为 `continuous_open_day`。任务成功时间、业务记录日期和数据完整性不是同一件事，不用“显示最小/最大日期”代替健康度合同，也不在本轮擅自修改日期审计策略。

## 4. 历史迁移与验收摘要

以下保留原文的历史证据，不是今天的生产数据、开关状态或执行授权。原全文可从 Git `e38f5dfe:docs/datasets/suspend-d-dataset-development.md` 追溯；跨数据集背景见 [Raw 直出一期 LLD](/Users/congming/github/goldenshare/docs/governance/prod-postgresql-raw-direct-serving-phase-one-lld-v1.md)。

- **类型实测（2026-08-28）：**目标日 `20260827`、显式四字段，不筛类型返回 4 行，S 为 3 行，R 为 1 行，多重集并集与无过滤结果一致；列表字符串 `"['S', 'R']"` 返回源端 `50101`。该记录支持单值展开设计，不代替本次源端实测。
- **M0/M1：**当时 Raw/Serving 各 640,504 行，320 个自然月按 `id, row_key_hash` 与四个源字段双向差异为 0，月峰值 17,074。Definition 切至 Raw-only，独立 [revision 20260828_000155](/Users/congming/github/goldenshare/alembic/versions/20260828_000155_make_suspend_d_raw_view.py) 接 revision 154，保留源字段、日期、类型展开、分页和工作流合同。
- **迁移门禁：**20,000 行/层/月是该次迁移的有界对账容量，**不是日常同步上限**。超限、字段/双身份差异、对象/索引/权限/依赖漂移在 Serving DDL 前拒绝；不执行 CASCADE，不修改 Raw 数据或索引，禁止自动 downgrade。该次 Raw heap/索引保持 SSD `pg_default`，不迁 HDD。
- **M2：**隔离 PostgreSQL 验证了 20,000/20,001 边界、字段及双身份差异、未知依赖、ACL/comment、DML 拒写、正式 writer、Raw/view 即时可见、事务回滚和三类查询计划；没有连接 Prod 或请求 Tushare。
- **M3a：**生产 revision 154→155，Raw/view 各 640,504 行、六字段差异为 0，旧 Serving relation 的 catalog 毛释放量为 222,199,808 B。拒写、消费者查询、连接池回收和 TaskRun **9717** 验收通过，当时 schedule #2/#24 原样恢复。
- **M3b：**TaskRun **9747/9773** 中两个目标节点均维护 `2026-08-28`，各一页短页、读取/保存 `7/7`，reject/去重/重试为 0。最终 Raw/view 各 7 行，hash 与源事实唯一，六字段差异为 0，最终 `fetched_at` 来自 21:02 第二轮更新，未制造重复；本数据集迁移结案。

## 5. 回归与后续修改

- [类型过滤合同测试](/Users/congming/github/goldenshare/tests/test_suspend_d_filter_contract.py)：无类型、单选、多选、日期×类型展开、非法值及未展开列表拒绝。
- [hash 测试](/Users/congming/github/goldenshare/tests/test_suspend_hash.py)：长度稳定、时段变更和多时段参与身份。
- [Raw/view 合同测试](/Users/congming/github/goldenshare/tests/test_suspend_d_raw_view_m1.py)：Definition、过滤、模型、索引、迁移容量/顺序/禁止项、离线 SQL 与 downgrade 拒绝。

本次文档治理只使用现有离线测试和文档检查，不重跑历史迁移、不写生产或 Lake。涉及字段、身份、消费者或长任务改造时按 [开发模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md) 重新明确影响面；旧验收不证明所有后续变更安全，也不证明已经支持进程退出后的持久化续跑。
