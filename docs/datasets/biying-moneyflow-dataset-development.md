# BIYING 资金流向维护说明

更新时间：2026-09-10。已实现；本轮只校准文档，不执行同步、发布或生产验收。旧“仅写 Raw、没有 Std/Serving”的阶段边界已过时。

## 1. 当前写入影响面

`biying_moneyflow.maintain` → BIYING 请求 → `raw_biying.moneyflow` → 标准化并写 `core_multi.moneyflow_std` → 按触及的证券/日期调用共享发布逻辑 → `core_serving.equity_moneyflow`。

- [moneyflow.py](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/moneyflow.py)声明 `write_path=raw_std_publish_moneyflow_biying`、`delivery_mode=multi_source_fusion`。
- [writer.py](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py)的 `_write_moneyflow_std_publish_biying` 依次 upsert Raw、Std，再调用 [moneyflow_publish.py](/Users/congming/github/goldenshare/src/foundation/ingestion/moneyflow_publish.py) 的 `publish_moneyflow_serving_for_keys`。
- 共享发布读取触及键的各来源 Std，再按发布逻辑选择；因此本任务会影响共享 Serving，不是一个与 Tushare 完全隔离的 Raw 收集动作，也不是无条件用 BIYING 覆盖其他来源。
- `WriteResult.rows_written/rows_upserted` 返回的是 Serving 写入数，不能把任务“写入行数”直接当作 Raw 行数。
- 本轮不改变多源优先级、mapping、配置或其他来源行为；共享发布的设计边界见[多源映射与发布规则](/Users/congming/github/goldenshare/docs/architecture/dataset-publish-governance-spec-v1.md)。

## 2. 输入与执行

股票范围沿用[BIYING 共用股票选择](/Users/congming/github/goldenshare/docs/datasets/biying-equity-daily-dataset-development.md#biying-universe)：默认从 raw_biying.stock_basic 读取 dm/mc，支持显式 ts_code，不要求显式代码已在池中。

- 单日输入 trade_date，源端 st=et；区间输入 start_date/end_date。
- `_build_biying_moneyflow_units` 按股票 × **最多 100 个自然日闭区间**生成 units，不读取交易日历逐日扇出。
- `_biying_moneyflow_params` 生成 dm、YYYYMMDD 格式的 st/et；不传 lt，不带复权选择。
- 请求路径为 `/hsstock/history/transaction/{dm}/{token}?st=...&et=...`；规划分页策略为 none，靠切窗控制范围，不使用 offset 翻页。
- connector 将 `{"error":"数据不存在"}` 作为空结果处理；切窗与不传 lt 本身不能证明任意范围均无源端截断。

实现：[unit_planner.py](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py)、[request_builders.py](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)。

## 3. Raw 与标准化

[Raw 模型](/Users/congming/github/goldenshare/src/foundation/models/raw_multi/raw_biying_moneyflow.py)：

- 表 `raw_biying.moneyflow`，主键 `(dm, trade_date)`。
- quote_time 来自接口 t，trade_date 取其日期；保留 api_name、fetched_at、raw_payload。
- 原字段包括主买/主卖统计 zmbzds、zmszds、zmbzdszl、zmszdszl、cjbszl，动向指标 dddx、zddy、ddcf，以及各档金额/成交量/总额/增量字段。完整列及各列数值精度以模型为准，不把所有比例或数量概括为同一种类型。
- 索引为 `idx_raw_biying_moneyflow_trade_date` 和 `idx_raw_biying_moneyflow_dm_trade_date`。

[NormalizeMoneyflowService](/Users/congming/github/goldenshare/src/foundation/services/transform/normalize_moneyflow_service.py) 的 `to_std_from_biying_raw` 将 dm 映射为 ts_code，将四档主买/主卖金额与数量映射到 Std buy/sell 字段，并计算净额。Raw 原字段仍保留；这里说明现有转换，不据此认定不同源的原始统计口径天然完全等价。

## 4. 观测、回归与验收

数据集 key 为 biying_moneyflow，业务日期为 trade_date；planner 的 progress_context 只有 ts_code、start_date、end_date，不承诺已经输出“代码+名称+窗口+获取+写入”的固定文本。核验需分清 fetched/normalized、Raw、Std 和 Serving 行数及拒绝原因。

现有回归入口：

- [connector](/Users/congming/github/goldenshare/tests/test_biying_connector.py)：请求拼装与空响应。
- [resolver](/Users/congming/github/goldenshare/tests/test_dataset_action_resolver.py)：100 日切窗及空池拒绝。
- [标准化](/Users/congming/github/goldenshare/tests/test_normalize_moneyflow_service.py)：BIYING → Std 与净额。
- [Raw 映射](/Users/congming/github/goldenshare/tests/test_raw_multi_schema_mapping.py)、[Ops catalog](/Users/congming/github/goldenshare/tests/test_ops_action_catalog.py)。

上述测试不替代真实 Raw→Std→Serving 联合对账。[本地 BIYING 资料目录](/Users/congming/github/goldenshare/docs/sources/biying/README.md)尚非完整源接口归档，本轮未新增源行为结论或生产验收记录。
