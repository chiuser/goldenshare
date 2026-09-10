# 股票历史分钟行情（`stk_mins`）维护说明

更新：2026-09-10。说明当前 Prod ingestion 代码，不是 Lake/Dagster 方案，也不授权同步、存储迁移或历史清理。

## 1. 维护入口与输入

- 数据集和 Tushare API 均为 `stk_mins`；资料见[本地源文档 0370](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/行情数据/0370_股票历史分钟行情.md)。源文档中的权限、历史跨度需按执行时实测确认。
- Ops 普通手动动作 `stk_mins.maintain` 接受单日 `trade_date` 或区间 `start_date/end_date`、必填多选 `freq`（1min/5min/15min/30min/60min）、可选单代码 `ts_code`。
- 不暴露时分秒、内部窗口或分页参数。未填写代码会展开默认股票集合，执行前必须评估请求量。
- Definition 支持手动、schedule 和重试，但不加入每日 workflow；schedule 能力与 workflow 编排不是一回事。股票分钟源站探测另见[探测说明](/Users/congming/github/goldenshare/docs/ops/ops-stk-mins-remote-source-probe-plan-v1.md)。

**CLI 边界：** 当前 [`maintain-dataset`](/Users/congming/github/goldenshare/src/cli.py)没有日期、区间和频率选项，[handler](/Users/congming/github/goldenshare/src/cli_parts/ingestion_handlers.py)默认时间模式为 `none`，不能表达本数据集所需输入。不要照旧文档通过它发起分钟维护，也不要臆造参数。worker CLI 只消费已有 TaskRun，不代替运营提交入口；本轮不扩展 CLI、不恢复旧命令。

## 2. 对象与 unit

[Definition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/market_equity.py)声明 `core_security_active_equities / tushare_preferred` 对象来源；[planner](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py)实际行为为：

1. 默认调用 SecurityDAO 的 `get_active_equities()`，读取 EQUITY 的 L/P/D 状态，包含历史所需退市、暂停上市证券。
2. 优先使用返回集合中的 Tushare 子集；该子集为空才使用已取证券的全部来源。不是任意在 Raw stock_basic 与 Serving 之间选表。
3. 显式代码不扫描默认全池，可另查证券名称；不能把这条路径描述为“必须是当前 Tushare 池成员”。
4. 代码去重排序，每代码按所选频率生成一个连续窗口。单日为当日 09:00–19:00，区间为起日 09:00 至末日 19:00。
5. 不拆上午/下午，也不按区间内交易日逐日展开。一个代码、两个频率的区间任务就是两个 unit，而不是交易日数×两时段×频率数。

`trade_open_day/every_open_day` 是日期模型事实，不等于该专用 planner 逐日拆请求；观测字段为 `trade_time`，普通日期完整性审计不适用。分钟网格、停牌和异常时段尚不能由“日期桶有行”证明完整。

## 3. 请求到写入的职责

| 位置 / 合同 | 职责 |
| --- | --- |
| `planning.unit_builder_key=build_stk_mins_units` | planner 查对象、校验频率、生成代码×频率×窗口及进度上下文 |
| `source.request_builder_key=_stk_mins_params` | builder 只映射 `ts_code/freq/window_start/window_end` 为源参数，不读库、不查池、不设置分页 |
| `planning.pagination_policy=offset_limit` | source client 追加 limit=8,000 和递增 offset；unit 内收齐页面 |
| normalization | 注入请求频率、转换时间/数值、检查身份和交易时段 |
| `storage.write_path=raw_only_upsert` | Raw/core DAO 均指 `raw_stk_mins`，只写一个物理表 |
| `transaction.commit_policy=unit` | 每个 unit 幂等 upsert 后独立提交；fetch concurrency=2 |

进度含代码、名称（可取得时）、频率、窗口及当前 unit/累计行数。逐 unit 提交保护已提交事实，但不能据此宣称已有退出后的精准续跑。整段多年窗口仍可能产生大 unit；大范围执行必须按[执行计划与长任务基线](/Users/congming/github/goldenshare/docs/architecture/dataset-execution-plan-refactor-plan-v1.md)另行评估内存、分页、事务和恢复，不因文档精简放宽门禁。

## 4. 九列物理表与视图

[Raw 模型](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_stk_mins.py)对应唯一物理表 `raw_tushare.stk_mins`：

| 字段 | 类型 / 语义 |
| --- | --- |
| `ts_code` | VARCHAR(16)，必填 |
| `freq` | SMALLINT，必填；源请求字符串归一为 1/5/15/30/60 |
| `trade_time` | TIMESTAMP WITHOUT TIME ZONE，必填 |
| `open/close/high/low` | REAL，可空；入库前保留两位小数 |
| `vol` | BIGINT，可空；股数，非整数拒绝，避免大 bar 超过 INTEGER 上限 |
| `amount` | REAL，可空；元 |

主键 `(ts_code,freq,trade_time)`；按 trade_time RANGE 月分区，保留 default 分区。瘦身结构不附加普通 BTree 索引，不保存 `trade_date/session_tag/api_name/fetched_at/raw_payload`。不要重放历史空表 drop/recreate。

`core_serving.equity_minute_bar` 是现有普通只读 View，投影九列并派生 `trade_date` 和常量来源 `tushare`，不是第二份表或物化视图。Definition 的写入目标仍是 Raw。查询按 `trade_time >= D AND trade_time < D+1` 过滤，不在 WHERE 对时间列做日期转换以致影响分区裁剪。

[成交额快照消费者](/Users/congming/github/goldenshare/src/biz/services/wealth/market/turnover/turnover_snapshot_materialize_service.py)仍直接读取 RawStkMins；“推荐通过 View 查询”不代表全部消费者已迁到 View，不能据此删除 Raw 模型或改变九列合同。

## 5. 质量与验收

- 必填身份为 `ts_code/freq/trade_time`；时间无法解析、频率非法、价格/数量转换失败或时间不在 09:30–11:30、13:00–15:00 时拒绝该行。
- 当前策略是 `record_rejections`，不是 ETF 分钟的“任一 rejection 使 unit 失败”。验收必须解释 rejection 的 reason 和样本。
- 同一过滤范围核验主键、频率、时段及 Raw/View 一致；不能用表非空、单日有行或最大时间替代分钟完整性。
- 经独立授权的真实冒烟先限单代码、单日、单频率，核对源行数、归一化、写入、拒绝和任务进度；本轮未执行。

当前回归入口：[resolver](/Users/congming/github/goldenshare/tests/test_dataset_action_resolver.py)的 stk_mins 用例、[source client](/Users/congming/github/goldenshare/tests/test_dataset_source_client.py)、[row transforms](/Users/congming/github/goldenshare/src/foundation/ingestion/row_transforms.py)及对应归一化测试。不要再使用旧说明中不存在的测试路径或“两时段 unit”预期。

## 6. 已确认但独立的边界

90 分钟是我方派生结果，不得写入 Tushare Raw。后续采用独立派生存储的方向已确认；原建议 `core_serving.equity_minute_bar_derived` 及字段仍需独立设计，当前没有该表实现，不能写成已接入。

存储迁移保留独立[瘦身与冷热治理方案](/Users/congming/github/goldenshare/docs/datasets/stk-mins-storage-slimming-plan-v1.md)，不在本文重列生产命令或解除 No-Go。worker 领取、取消及部署见[执行隔离说明](/Users/congming/github/goldenshare/docs/ops/ops-stk-mins-dedicated-worker-execution-lane-plan-v1.md)；停车道不等于数据库拒写。
