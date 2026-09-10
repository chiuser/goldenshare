# BIYING 股票日线维护说明

更新时间：2026-09-10。已实现；本轮只校准文档，不执行同步或生产验收。日线仍为 Raw-only，与资金流向的多源发布链路不同。

## 1. 写入边界与实现

- 入口：`biying_equity_daily.maintain`。
- 写入：`raw_only_upsert` → `raw_biying.equity_daily_bar`；不进行 Tushare 融合，不写 Std/Serving。
- 定义在 [market_equity.py](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/market_equity.py)；规划在 [unit_planner.py](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py) 的 `_build_biying_equity_daily_units / _build_biying_units`；请求在 [request_builders.py](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py) 的 `_biying_equity_daily_params`。
- [Raw 模型](/Users/congming/github/goldenshare/src/foundation/models/raw_multi/raw_biying_equity_daily_bar.py)主键为 `(dm, trade_date, adj_type)`。业务字段包括 dm、trade_date、adj_type、mc、quote_time、OHLC、pre_close、vol、amount、suspend_flag；审计字段为 api_name、fetched_at、raw_payload。
- 索引：`idx_raw_biying_equity_daily_bar_trade_date`、`idx_raw_biying_equity_daily_bar_dm_trade_date`。

<a id="biying-universe"></a>

## 2. 两个 BIYING 数据集共用的股票选择

日线和[资金流向](/Users/congming/github/goldenshare/docs/datasets/biying-moneyflow-dataset-development.md)都使用 `_resolve_biying_targets`：

1. 不填 `ts_code`，读取 `raw_biying.stock_basic(dm, mc)` 中有 dm 的记录；该查询没有 Tushare 上市状态筛选。
2. 显式代码经过拆分、转大写、去掉点号后的交易所后缀，作为 BIYING dm；查询主数据补名称，池中不存在的显式代码仍加入请求，不要求先入池。
3. 无显式代码且读取不到股票时，报 `universe_empty`，不会凭空生成全市场请求。
4. Definition 将 `ts_code` 暴露为字符串过滤；底层解析支持多个值，不据此宣称页面已有多选控件。

## 3. 输入、窗口与源请求

| 项目 | 当前行为 |
| --- | --- |
| 时间 | 单日 trade_date，或 start_date/end_date 闭区间 |
| 复权选择 | 可选 adj_type；默认按 n/f/b 三种执行，可指定其子集；底层按 n/f/b 稳定排序、去重并拒绝其他值 |
| unit | 股票 × 已选复权类型 × 最多 3000 个自然日窗口；单日 st=et |
| 请求 | `/hsstock/history/{dm}/{freq}/{adj_type}/{token}`；freq=d，st/et 为 YYYYMMDD，lt="5000" |
| 分页 | `pagination_policy=none`；通过日期切窗，不是 limit/offset 翻页 |

n/f/b 分别是不复权、前复权、后复权。正常入口的三种默认值由 planner 决定，不能拿 request builder 单独的 f 回退当成维护默认。切窗降低单次规模，不等于已经证明所有响应均无截断。

窗口结果归一化后按主键 upsert；`progress_context` 实际提供 ts_code、start_date、end_date。复权类型在请求与 unit 身份中，不承诺进度文本已经包含中文复权标签、股票名称或固定格式。

<a id="raw-table-metadata-deviation"></a>

## 4. 独立代码差异：Raw 元数据表名尚未修复

当前 Definition 的 `storage.raw_table` 是 `raw_biying.equity_daily`，而 `target_table`、DAO 和 ORM 都指向 `raw_biying.equity_daily_bar`。后者是当前实际写入目标；不能把本文正确表名改成前者来掩盖差异。

元数据被 [数据卡片查询](/Users/congming/github/goldenshare/src/ops/queries/dataset_card_query_service.py)与 [状态投影服务](/Users/congming/github/goldenshare/src/ops/services/operations_dataset_status_snapshot_service.py)消费；[定义测试](/Users/congming/github/goldenshare/tests/test_dataset_definition_registry.py)还断言了旧字符串。2026-09-10 离线核验确认旧元数据名无法解析到当前模型，不代表本轮查过物理库或发现数据损坏。

本轮只记录。修复需单独调整 Definition、消费者核验与测试，不改变实际写入目标，不执行改表或数据迁移。

## 5. 回归入口与证据边界

- [connector 测试](/Users/congming/github/goldenshare/tests/test_biying_connector.py)：URL 与响应解析。
- [resolver 测试](/Users/congming/github/goldenshare/tests/test_dataset_action_resolver.py)：BIYING 请求、复权与窗口。
- [Raw 映射测试](/Users/congming/github/goldenshare/tests/test_raw_multi_schema_mapping.py)：schema 与身份。
- [Ops catalog 测试](/Users/congming/github/goldenshare/tests/test_ops_action_catalog.py)：维护入口。

[本地 BIYING 资料目录](/Users/congming/github/goldenshare/docs/sources/biying/README.md)目前只是资料组织说明，不是已完整归档的接口合同。本轮依据现行实现校准，未重新请求源站；删除旧同步服务测试路径，不恢复 Sync V1。
