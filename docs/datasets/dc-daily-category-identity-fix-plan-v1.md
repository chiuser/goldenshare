# dc_daily category 字段与主键修复方案 v1

## 1. 背景

`dc_daily` 是 Tushare `dc_daily` 接口，对应“东方财富板块日线行情”。

当前仓内正式链路的问题是：

1. `DatasetDefinition.source_fields` 未包含 `category`。
2. `raw_tushare.dc_daily` 未保存 `category`。
3. `core_serving.dc_daily` 未保存 `category`。
4. raw/core 当前主键都是 `ts_code + trade_date`。

真实接口已经验证会返回 `category` 字段，含义是“分类板块”，取值包括：

1. `行业板块`
2. `概念板块`
3. `地域板块`

因此，当前主键无法表达完整业务身份。

## 2. 真实请求验证结论

已新增探测测试：

[test_tushare_dc_daily_identity_probe.py](/Users/congming/github/goldenshare/tests/integration/test_tushare_dc_daily_identity_probe.py)

真实请求范围：

```text
2025-01-01 ~ 2025-01-31
idx_type=行业板块 / 概念板块 / 地域板块
```

探测报告文件已按 `reports/` 临时产物清理策略移除；本文保留当时的验证范围与结论，后续如需复核，应重新运行探测测试生成新的本地报告。

结论：

| 口径 | 结果 |
| --- | ---: |
| 源端读取总行数 | 17,704 |
| 按 `ts_code + trade_date` 唯一 | 17,488 |
| 按 `ts_code + trade_date` 重复组 | 216 |
| 重复行数 | 216 |
| 重复组中 `category` 冲突 | 216 |
| 重复组中业务字段冲突 | 179 |
| 按 `ts_code + trade_date + category` 唯一 | 17,704 |
| 按 `ts_code + trade_date + category` 重复组 | 0 |

这说明 `ts_code + trade_date` 不是 `dc_daily` 的正确业务身份。

## 3. 目标

本轮只做两个目标：

1. 把 `category` 加入正式字段链路，并落到 raw 和 serving。
2. 把 raw 和 serving 的主键扩为 `ts_code + trade_date + category`。

不做以下事项：

1. 不改变用户输入项。
2. 不把 `category` 暴露成手动任务筛选项。
3. 不改变 `idx_type` 的扇出策略。
4. 不改其他东方财富板块数据集。
5. 不顺手改 UI。

## 4. 字段设计

### 4.1 源接口字段

源接口实际输出字段应按以下列表维护：

| 字段 | 类型 | 说明 | 当前状态 | 修复动作 |
| --- | --- | --- | --- | --- |
| `ts_code` | str | 板块代码 | 已接入 | 保持 |
| `trade_date` | str/date | 交易日 | 已接入 | 保持 |
| `close` | float | 收盘点位 | 已接入 | 保持 |
| `open` | float | 开盘点位 | 已接入 | 保持 |
| `high` | float | 最高点位 | 已接入 | 保持 |
| `low` | float | 最低点位 | 已接入 | 保持 |
| `change` | float | 涨跌点位 | 已接入 | 保持 |
| `pct_change` | float | 涨跌幅 | 已接入 | 保持 |
| `vol` | float | 成交量 | 已接入 | 保持 |
| `amount` | float | 成交额 | 已接入 | 保持 |
| `swing` | float | 振幅 | 已接入 | 保持 |
| `turnover_rate` | float | 换手率 | 已接入 | 保持 |
| `category` | str | 分类板块 | 缺失 | 新增 |

### 4.2 raw 表

表：`raw_tushare.dc_daily`

新增字段：

```text
category varchar(32) not null
```

主键改为：

```text
primary key (ts_code, trade_date, category)
```

### 4.3 serving 表

表：`core_serving.dc_daily`

新增字段：

```text
category varchar(32) not null
```

主键改为：

```text
primary key (ts_code, trade_date, category)
```

保留现有 `trade_date` 查询索引。

可新增组合查询索引：

```text
index (trade_date, category)
```

用于按日期和分类板块查看数据。

## 5. DatasetDefinition 调整

文件：

[board_hotspot.py](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/board_hotspot.py)

调整：

1. `dc_daily.source.source_fields` 增加 `category`。
2. `dc_daily.normalization.required_fields` 增加 `category`。
3. `dc_daily.quality.required_fields` 增加 `category`。
4. `storage.conflict_columns` 可显式设置为 `("ts_code", "trade_date", "category")`，避免后续模型主键变更时写入口径不清。

`category` 是源端返回的业务身份字段，不是用户输入字段，因此不加入 `input_model.filters`。

## 6. 迁移策略

当前已有 `dc_daily` 历史数据是在错误主键下写入的，已经发生折叠，无法从现有表可靠恢复 `category`。

建议迁移策略：

1. 新增 Alembic migration。
2. 对 `raw_tushare.dc_daily` 和 `core_serving.dc_daily` 做结构调整。
3. 两张表旧数据清空后重建主键。
4. 重新按 `idx_type` 三类扇开同步历史数据。

注意：

1. 新增 Alembic 迁移前必须先检查当前真实 migration head。
2. 清空业务数据表必须等待用户明确执行指令。
3. 清空范围仅限 `raw_tushare.dc_daily` 和 `core_serving.dc_daily`。

## 7. 代码改动清单

### 7.1 source 文档

文件：

[0382_东财概念板块行情.md](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/打板专题数据/0382_东财概念板块行情.md)

动作：

1. 输出参数补充 `category`。
2. 保留源站事实，不写工程实现决策。

### 7.2 数据模型

文件：

1. [raw_dc_daily.py](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_dc_daily.py)
2. [dc_daily.py](/Users/congming/github/goldenshare/src/foundation/models/core/dc_daily.py)

动作：

1. 增加 `category` 字段。
2. 将 `category` 标记为主键字段之一。

### 7.3 DatasetDefinition

文件：

[board_hotspot.py](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/board_hotspot.py)

动作：

1. `source_fields` 增加 `category`。
2. `normalization.required_fields` 增加 `category`。
3. `quality.required_fields` 增加 `category`。
4. `storage.conflict_columns` 增加显式三字段冲突键。

### 7.4 迁移

新增 Alembic 文件。

动作：

1. 检查当前 migration head。
2. 修改两张表结构。
3. 清空旧 `dc_daily` 数据。
4. 重建主键。
5. 新增必要索引。

## 8. 验证计划

### 8.1 静态验证

1. `dc_daily.source_fields` 包含 `category`。
2. raw/core model 包含 `category`。
3. raw/core model 主键均为 `ts_code + trade_date + category`。
4. `required_fields` 包含 `category`。

### 8.2 真实请求验证

继续使用：

[test_tushare_dc_daily_identity_probe.py](/Users/congming/github/goldenshare/tests/integration/test_tushare_dc_daily_identity_probe.py)

验证命令示例：

```bash
GOLDENSHARE_ENV_FILE=.env.web.local \
RUN_TUSHARE_DC_DAILY_IDENTITY_PROBE=1 \
DC_DAILY_PROBE_START_DATE=20250101 \
DC_DAILY_PROBE_END_DATE=20250131 \
DC_DAILY_PROBE_REQUEST_MODE=explicit_types \
pytest -q tests/integration/test_tushare_dc_daily_identity_probe.py -s
```

预期：

1. `ts_code + trade_date` 存在重复。
2. `ts_code + trade_date + category` 无重复。

### 8.3 最小同步验证

迁移后选择一个交易日同步 `dc_daily`。

验收：

1. 源端读取行数 = raw 表新增/更新唯一行数。
2. raw 表行数 = serving 表行数。
3. `rows_rejected = 0`。
4. `读取 > 保存` 的异常差异不再由主键折叠导致。
5. 任一重复样本，如 `BK0425.DC + 20250102`，应能同时保存 `行业板块` 和 `概念板块` 两行。

## 9. 风险

1. 旧数据不可无损补齐 `category`，必须重跑。
2. 如果源站偶发不返回 `category`，新规则会拒绝该行。这是正确行为，因为主键不完整。
3. 任何依赖 `dc_daily` 查询的下游，如果默认认为 `ts_code + trade_date` 唯一，需要同步审计。

## 10. 用户确认

2026-05-08 已确认：

1. 同意清空并重建 `raw_tushare.dc_daily`。
2. 同意清空并重建 `core_serving.dc_daily`。
3. 同意迁移后按历史区间重新同步 `dc_daily`。
