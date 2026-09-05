# ths_daily 估值字段扩表重建方案 v1

> M5 清退边界（2026-09-05）：生产 DatasetDefinition、pe_ttm/pb_mrq 字段与重建验收记录继续保留；旧 Console 导出白名单/CLI 部分只作 2026-05-08 实施证据，不是当前 DG 接入入口。旧 Console 代码待 M6 删除，本轮不改生产字段。

状态：已实施（2026-05-08）

## 1. 背景

`ths_daily` 是 Tushare `ths_daily` 接口，对应“同花顺板块指数行情”。

源接口文档已经补齐输出字段：

[0260_同花顺板块指数行情.md](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/打板专题数据/0260_同花顺板块指数行情.md)

当前仓内正式链路的问题是：

1. `DatasetDefinition.source_fields` 未包含 `pe_ttm`、`pb_mrq`。
2. `raw_tushare.ths_daily` 未保存 `pe_ttm`、`pb_mrq`。
3. `core_serving.ths_daily` 未保存 `pe_ttm`、`pb_mrq`。
4. Lake prod-raw-db 导出字段白名单未包含 `pe_ttm`、`pb_mrq`。

这会导致正式同步时即使源接口返回估值字段，系统也不会请求、不会落库、不会导出到本地 Lake。

## 2. 源接口字段对账

源接口输出字段应为：

| 字段 | 类型 | 说明 | 当前状态 | 修复动作 |
| --- | --- | --- | --- | --- |
| `ts_code` | str | TS指数代码 | 已接入 | 保持 |
| `trade_date` | str/date | 交易日 | 已接入 | 保持 |
| `open` | float | 开盘点位 | 已接入 | 保持 |
| `high` | float | 最高点位 | 已接入 | 保持 |
| `low` | float | 最低点位 | 已接入 | 保持 |
| `close` | float | 收盘点位 | 已接入 | 保持 |
| `pre_close` | float | 昨日收盘点 | 已接入 | 保持 |
| `avg_price` | float | 平均点位 | 已接入 | 保持 |
| `change` | float | 涨跌点位 | 已接入 | 保持 |
| `pct_change` | float | 涨跌幅 | 已接入 | 保持 |
| `vol` | float | 成交量 | 已接入 | 保持 |
| `turnover_rate` | float | 换手率 | 已接入 | 保持 |
| `total_mv` | float | 总市值 | 已接入 | 保持 |
| `float_mv` | float | 流通市值 | 已接入 | 保持 |
| `pe_ttm` | float | PE TTM | 缺失 | 新增 |
| `pb_mrq` | float | PB MRQ | 缺失 | 新增 |

## 3. 目标

本轮只做一个目标：

把 `ths_daily` 未支持的输出字段 `pe_ttm`、`pb_mrq` 加入正式链路，并落到 raw 和 serving。

不做以下事项：

1. 不改变 `ths_daily` 主键，仍为 `ts_code + trade_date`。
2. 不改变用户输入项。
3. 不改变请求策略。
4. 不改变工作流。
5. 不顺手改 UI。

## 4. 数据表设计

### 4.1 raw 表

表：`raw_tushare.ths_daily`

新增字段：

```text
pe_ttm numeric(18, 6)
pb_mrq numeric(18, 6)
```

主键保持：

```text
primary key (ts_code, trade_date)
```

### 4.2 serving 表

表：`core_serving.ths_daily`

新增字段：

```text
pe_ttm numeric(18, 6)
pb_mrq numeric(18, 6)
```

主键保持：

```text
primary key (ts_code, trade_date)
```

保留现有 `trade_date` 查询索引。

## 5. DatasetDefinition 调整

文件：

[board_hotspot.py](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/board_hotspot.py)

调整：

1. `ths_daily.source.source_fields` 增加 `pe_ttm`、`pb_mrq`。
2. `ths_daily.normalization.decimal_fields` 增加 `pe_ttm`、`pb_mrq`。
3. `required_fields` 不增加这两个字段。

原因：

1. `pe_ttm`、`pb_mrq` 是估值指标，不是业务身份字段。
2. 源端可能因缺值、亏损或板块口径原因返回空值。
3. 缺值不应导致整行拒绝入库。

## 6. 迁移策略

用户已确认可以重建表。

建议迁移策略：

1. 新增 Alembic migration。
2. 迁移中 drop/recreate `raw_tushare.ths_daily`。
3. 迁移中 drop/recreate `core_serving.ths_daily`。
4. 新表包含完整字段。
5. 迁移后重新同步历史数据。

注意：

1. 新增 Alembic 迁移前必须先检查当前真实 migration head。
2. 清空范围仅限 `raw_tushare.ths_daily` 和 `core_serving.ths_daily`。
3. 迁移不触碰 `dc_daily` 或其他板块数据集。

## 7. 代码改动清单

### 7.1 DatasetDefinition

文件：

[board_hotspot.py](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/board_hotspot.py)

动作：

1. `source_fields` 增加 `pe_ttm`、`pb_mrq`。
2. `decimal_fields` 增加 `pe_ttm`、`pb_mrq`。

### 7.2 数据模型

文件：

1. [raw_ths_daily.py](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_ths_daily.py)
2. [ths_daily.py](/Users/congming/github/goldenshare/src/foundation/models/core/ths_daily.py)

动作：

1. 新增 `pe_ttm` 字段。
2. 新增 `pb_mrq` 字段。
3. 主键不变。

### 7.3 Lake prod-raw-db 导出

文件：

[board_hotspot.py](/Users/congming/github/goldenshare/lake_console/backend/app/catalog/datasets/board_hotspot.py)

动作：

1. `THS_DAILY_FIELDS` 增加 `pe_ttm`、`pb_mrq`。
2. 相关导出测试同步更新。

### 7.4 迁移

新增 Alembic 文件。

动作：

1. 检查当前 migration head。
2. 重建 `raw_tushare.ths_daily`。
3. 重建 `core_serving.ths_daily`。

实施文件：

[20260508_000101_rebuild_ths_daily_valuation_fields.py](/Users/congming/github/goldenshare/alembic/versions/20260508_000101_rebuild_ths_daily_valuation_fields.py)

## 8. 验证计划

### 8.1 静态验证

1. `ths_daily.source_fields` 包含 `pe_ttm`、`pb_mrq`。
2. `ths_daily.decimal_fields` 包含 `pe_ttm`、`pb_mrq`。
3. raw/core model 包含 `pe_ttm`、`pb_mrq`。
4. raw/core 主键仍为 `ts_code + trade_date`。
5. Lake `THS_DAILY_FIELDS` 包含 `pe_ttm`、`pb_mrq`。

### 8.2 迁移验证

1. `alembic heads` 确认真实 head。
2. `alembic upgrade <previous_head>:<new_head> --sql` 可生成预期 DDL。

### 8.3 最小同步验证

迁移后选择一个交易日同步 `ths_daily`。

验收：

1. 源端读取行数 = raw 表唯一行数。
2. raw 表行数 = serving 表行数。
3. `rows_rejected = 0`。
4. 抽样记录包含 `pe_ttm`、`pb_mrq` 字段。
5. Lake prod-raw-db 导出 Parquet 包含 `pe_ttm`、`pb_mrq`。

## 9. 风险

1. 旧数据没有保存 `pe_ttm`、`pb_mrq`，需要重跑历史才能补齐。
2. `pe_ttm`、`pb_mrq` 可能为空，这是正常源端语义，不应视为拒绝。
3. Lake 侧导出字段变化后，旧 Parquet 分区若存在，会与新字段不一致；建议在重导对应分区前清理或覆盖旧分区。

## 10. 用户确认

2026-05-08 已确认：

1. 可以重建 `raw_tushare.ths_daily`。
2. 可以重建 `core_serving.ths_daily`。
3. 要把未支持字段 `pe_ttm`、`pb_mrq` 加入正式链路。
