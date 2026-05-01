# 个股资金流向 Lake 数据集接入说明

- 版本：v1
- 状态：待评审
- 更新时间：2026-05-01
- 数据集 key：`moneyflow`
- 数据源：Tushare
- 源站文档：`docs/sources/tushare/股票数据/资金流向数据/0170_个股资金流向.md`
- 参考模板：`docs/templates/lake-dataset-development-template.md`

---

## 0. 架构基线与禁止项

本数据集只接入 `lake_console` 本地移动盘 Parquet Lake，不接入生产 Ops 任务链。

必须遵守：

1. 不访问远程 `goldenshare-db`。
2. 区间同步只能读取本地交易日历展开交易日。
3. 写入必须按 `trade_date` 分区，使用 `_tmp -> 校验 -> 替换正式分区`。
4. 资金流 Lake 只保存 Tushare 源数据事实，不引入生产多源融合逻辑。
5. 前端展示分组参考 Ops 默认展示目录。

---

## 1. 基本信息

| 项 | 值 |
|---|---|
| 数据集 key | `moneyflow` |
| 中文显示名 | 个股资金流向 |
| 数据源 | `tushare` |
| 源站 API | `moneyflow` |
| 源站 doc_id | `170` |
| 源站链接 | `https://tushare.pro/document/2?doc_id=170` |
| 本地源站文档 | `docs/sources/tushare/股票数据/资金流向数据/0170_个股资金流向.md` |
| 生产 DatasetDefinition | 已存在 |
| 生产定义文件 | `src/foundation/datasets/definitions/moneyflow.py` |
| 是否依赖本地 manifest | 是，交易日历 |
| 是否双落盘 manifest | 否 |
| 是否需要 derived 层 | 否 |
| 是否需要 research 层 | 暂不需要 |

生产 `DatasetDefinition` 当前事实：

| 字段 | 值 |
|---|---|
| `source.api_name` | `moneyflow` |
| `source.request_builder_key` | `_moneyflow_params` |
| `date_model.date_axis` | `trade_open_day` |
| `date_model.bucket_rule` | `every_open_day` |
| `date_model.window_mode` | `point_or_range` |
| `date_model.observed_field` | `trade_date` |
| `planning.pagination_policy` | `offset_limit` |
| `planning.page_limit` | `6000` |
| `storage.raw_table` | `raw_tushare.moneyflow` |

---

## 2. 源站接口分析

### 2.1 输入参数

| 参数名 | 类型 | 必填 | 说明 | 类别 | 是否支持多值 | Lake 用户是否可填写 | 默认值 | 备注 |
|---|---|---:|---|---|---:|---:|---|---|
| `ts_code` | str | 否 | 股票代码，股票和时间参数至少输入一个 | 代码 | 否 | 是 | 空 | 单股区间调试可用 |
| `trade_date` | str | 否 | 交易日期 | 时间 | 否 | 是 | 空 | 单日同步主参数 |
| `start_date` | str | 否 | 开始日期 | 时间 | 否 | 是 | 空 | 区间由本地交易日历展开 |
| `end_date` | str | 否 | 结束日期 | 时间 | 否 | 是 | 空 | 区间由本地交易日历展开 |
| `limit` | int | 否 | 单次返回数据长度 | 分页 | 否 | 否 | `6000` | Lake 固定 |
| `offset` | int | 否 | 请求数据开始位移量 | 分页 | 否 | 否 | `0` 起 | Lake 递增 |

### 2.2 输出字段

| 字段名 | 类型 | 含义 | 是否写入 Parquet | Lake 字段类型 | 是否可空 | 备注 |
|---|---|---|---:|---|---:|---|
| `ts_code` | str | TS代码 | 是 | string | 否 |  |
| `trade_date` | str | 交易日期 | 是 | string | 否 | 分区字段 |
| `buy_sm_vol` | int | 小单买入量（手） | 是 | int64 | 是 | 文档为 int |
| `buy_sm_amount` | float | 小单买入金额（万元） | 是 | double | 是 |  |
| `sell_sm_vol` | int | 小单卖出量（手） | 是 | int64 | 是 | 文档为 int |
| `sell_sm_amount` | float | 小单卖出金额（万元） | 是 | double | 是 |  |
| `buy_md_vol` | int | 中单买入量（手） | 是 | int64 | 是 | 文档为 int |
| `buy_md_amount` | float | 中单买入金额（万元） | 是 | double | 是 |  |
| `sell_md_vol` | int | 中单卖出量（手） | 是 | int64 | 是 | 文档为 int |
| `sell_md_amount` | float | 中单卖出金额（万元） | 是 | double | 是 |  |
| `buy_lg_vol` | int | 大单买入量（手） | 是 | int64 | 是 | 文档为 int |
| `buy_lg_amount` | float | 大单买入金额（万元） | 是 | double | 是 |  |
| `sell_lg_vol` | int | 大单卖出量（手） | 是 | int64 | 是 | 文档为 int |
| `sell_lg_amount` | float | 大单卖出金额（万元） | 是 | double | 是 |  |
| `buy_elg_vol` | int | 特大单买入量（手） | 是 | int64 | 是 | 文档为 int |
| `buy_elg_amount` | float | 特大单买入金额（万元） | 是 | double | 是 |  |
| `sell_elg_vol` | int | 特大单卖出量（手） | 是 | int64 | 是 | 文档为 int |
| `sell_elg_amount` | float | 特大单卖出金额（万元） | 是 | double | 是 |  |
| `net_mf_vol` | int | 净流入量（手） | 是 | int64 | 是 | 文档为 int |
| `net_mf_amount` | float | 净流入额（万元） | 是 | double | 是 |  |

### 2.3 源端行为

- 是否分页：是。
- 分页参数：`limit` / `offset`。
- 单次最大返回：`6000` 行。
- 分页结束条件：返回行数 `< 6000`。
- 是否限速：使用 Lake 全局 Tushare 限速配置。
- 是否支持按日期请求：支持 `trade_date`。
- 是否支持按区间请求：支持 `start_date` / `end_date`，但 Lake 全市场默认按交易日逐日请求。
- 是否支持代码参数：支持 `ts_code`。
- 是否支持枚举参数：否。
- 上游空行风险：单日全市场返回空时应告警，不得覆盖已有分区。
- 字段类型风险：`*_vol` 文档为 int，Lake 使用 int64，避免成交量极端值溢出。

---

## 3. Lake Catalog 设计

### 3.1 展示分组

| 字段 | 值 |
|---|---|
| `group_key` | `moneyflow` |
| `group_label` | 资金流向 |
| `group_order` | 8 |

### 3.2 Lake Dataset Catalog 字段

| 字段 | 值 | 说明 |
|---|---|---|
| `dataset_key` | `moneyflow` | 唯一标识 |
| `display_name` | 个股资金流向 | 中文展示名 |
| `source` | `tushare` | 数据来源 |
| `api_name` | `moneyflow` | 源站 API |
| `source_doc_id` | `170` | 源站文档 ID |
| `primary_layout` | `by_date` | 按交易日 |
| `available_layouts` | `by_date` | 第一版只做原始层 |
| `write_policy` | `replace_partition` | 按日替换 |
| `update_mode` | `manual_cli` | CLI 手动 |
| `page_limit` | `6000` | 分页上限 |
| `request_strategy_key` | `moneyflow` | 独立策略 |
| `supported_commands` | `plan-sync`, `sync-dataset` | 通用命令 |

---

## 4. 请求策略设计

### 4.1 请求模式

| 模式 | 是否使用 | 说明 |
|---|---:|---|
| `snapshot_current` | 否 |  |
| `trade_date_points` | 是 | 默认按交易日逐日请求 |
| `natural_date_points` | 否 |  |
| `month_key_points` | 否 |  |
| `month_window` | 否 |  |
| `datetime_window` | 否 |  |
| `enum_fanout` | 否 |  |
| `security_universe_fanout` | 否 | 默认不按股票池扇出 |

### 4.2 请求单元生成

- 用户输入：`trade_date` 或 `start_date/end_date`，可选 `ts_code`。
- 本地依赖：区间模式需要 `manifest/trading_calendar/tushare_trade_cal.parquet`。
- 请求单元粒度：一个交易日一个请求流。
- 单元数量估算：交易日数量。
- 是否支持 `plan-sync` 预览：是。
- 失败后可重跑的最小粒度：单个 `trade_date` 分区。

默认策略：

1. 用户传 `trade_date`：请求 `moneyflow(trade_date=YYYYMMDD, limit=6000, offset=...)`。
2. 用户传 `start_date/end_date` 且未传 `ts_code`：读取本地交易日历，逐个交易日请求。
3. 用户传 `ts_code + start_date/end_date`：允许作为单股区间调试模式，但写入仍按返回行的 `trade_date` 分区。

### 4.3 分页策略

- `limit`：`6000`。
- `offset` 起点：`0`。
- 结束条件：返回行数 `< 6000`。
- 每页是否立即写入：第一版可按日聚合后写入；如果实测单日接近或超过上限，则保留多页聚合后写单分区。
- 每页是否输出进度：是。

### 4.4 本地依赖

| 依赖 | 来源 | 缺失时行为 |
|---|---|---|
| 交易日历 | `manifest/trading_calendar/tushare_trade_cal.parquet` | 区间同步失败并提示先同步 |

---

## 5. Parquet 存储设计

### 5.1 层级

| 层级 | 是否使用 | 用途 |
|---|---:|---|
| `raw_tushare` | 是 | Tushare 个股资金流向原始事实 |
| `manifest` | 否 |  |
| `derived` | 否 |  |
| `research` | 否 | 暂不需要 |

### 5.2 路径设计

| 层级 | 路径模板 | 替换范围 |
|---|---|---|
| `raw_tushare` | `raw_tushare/moneyflow/trade_date=YYYY-MM-DD/part-000.parquet` | 单交易日分区 |

### 5.3 分区字段

| 分区字段 | 类型 | 说明 |
|---|---|---|
| `trade_date` | date string | 交易日，目录格式 `YYYY-MM-DD` |

### 5.4 文件命名

- 单文件：`part-000.parquet`。
- 是否允许多 part：第一版默认否。
- 多 part 触发条件：如果单日资金流向未来超过单文件目标大小，再评审增加多 part。

### 5.5 写入策略

| 策略 | 是否使用 | 说明 |
|---|---:|---|
| `replace_file` | 否 |  |
| `replace_partition` | 是 | 替换单个交易日分区 |
| `rebuild_month` | 否 |  |
| `append_only` | 否 |  |

---

## 6. 数据量与文件数评估

| 维度 | 估算 |
|---|---:|
| 单请求最大行数 | 6000 |
| 单日行数 | 约 5000 到 6000 |
| 单年行数 | 约 120 万到 150 万 |
| 10 年行数 | 约 1200 万到 1500 万 |
| 单日文件数 | 1 |
| 10 年文件数 | 约 2440 |
| 单文件大小 | 字段较多，预计数 MB 级，需首次同步实测 |

小文件风险：

1. `moneyflow` 单日一文件天然偏小，但按日分区利于补数和按日研究。
2. 该数据集字段多于 `daily`，单文件大小会比 `daily` 更大。
3. 不建议第一版做 research 重排，除非后续确认常用查询是“单股多年资金流回测”。

---

## 7. 命令设计

### 7.1 `plan-sync`

```bash
lake-console plan-sync moneyflow --trade-date 2026-04-24
lake-console plan-sync moneyflow --start-date 2026-04-01 --end-date 2026-04-30
lake-console plan-sync moneyflow --ts-code 600000.SH --start-date 2026-04-01 --end-date 2026-04-30
```

### 7.2 同步命令

```bash
lake-console sync-dataset moneyflow --trade-date 2026-04-24
lake-console sync-dataset moneyflow --start-date 2026-04-01 --end-date 2026-04-30
lake-console sync-dataset moneyflow --ts-code 600000.SH --start-date 2026-04-01 --end-date 2026-04-30
```

是否需要专用命令：否。

### 7.3 命令示例页

| 标题 | 说明 | 命令 |
|---|---|---|
| 同步单日全市场资金流 | 写入一个 `trade_date` 分区 | `lake-console sync-dataset moneyflow --trade-date 2026-04-24` |
| 同步区间全市场资金流 | 用本地交易日历展开交易日 | `lake-console sync-dataset moneyflow --start-date 2026-04-01 --end-date 2026-04-30` |
| 同步单股区间资金流 | 适合调试或单股研究 | `lake-console sync-dataset moneyflow --ts-code 600000.SH --start-date 2026-04-01 --end-date 2026-04-30` |

---

## 8. 前端展示设计

列表页默认展示：

1. 分组：资金流向。
2. 数据集：个股资金流向。
3. 层级：`raw_tushare`。
4. `file_count`。
5. `total_bytes`。
6. 日期范围。
7. 最近修改时间。

详情页展示：

1. `trade_date` 分区列表。
2. 每个分区文件大小和修改时间。
3. 显式计算 `row_count`。
4. 命令示例。

---

## 9. 校验与测试

### 9.1 文档校验

```bash
python3 scripts/check_docs_integrity.py
```

### 9.2 单元测试建议

| 测试 | 目的 |
|---|---|
| `test_lake_catalog_moneyflow` | catalog 字段、分组、命令示例完整 |
| `test_lake_plan_moneyflow_trade_date` | 单日请求计划 |
| `test_lake_plan_moneyflow_range_uses_local_trade_cal` | 区间模式使用本地交易日历 |
| `test_lake_sync_moneyflow_replace_partition` | 按日分区原子替换 |
| `test_lake_moneyflow_int64_volume_fields` | `*_vol` 字段使用 int64 |

### 9.3 真实同步冒烟

```bash
lake-console plan-sync moneyflow --trade-date 2026-04-24
lake-console sync-dataset moneyflow --trade-date 2026-04-24
```

DuckDB 验证：

```sql
select count(*) from read_parquet('<LAKE_ROOT>/raw_tushare/moneyflow/trade_date=2026-04-24/*.parquet');
```

---

## 10. 风险与回滚

| 风险 | 影响 | 防护 | 回滚 |
|---|---|---|---|
| 单日返回达到分页上限 | 数据不完整 | 必须 offset 分页直到 `< limit` | 重跑分区 |
| 空结果覆盖旧数据 | 数据丢失 | 空结果拒绝覆盖已有分区 | 保留旧分区 |
| `*_vol` 类型过小 | 溢出 | 使用 int64 | 修正 schema 后重跑 |
| 区间过大 | 请求耗时长 | `plan-sync` 展示交易日数量 | 缩小区间 |

---

## 11. Checklist

编码前：

- [ ] 已确认源站文档。
- [ ] 已确认生产 DatasetDefinition。
- [ ] 已确认本地交易日历依赖。
- [ ] 已确认按日分区。
- [ ] 已确认 `*_vol` 使用 int64。
- [ ] 已确认命令示例。

编码后：

- [ ] `plan-sync moneyflow` 可用。
- [ ] `sync-dataset moneyflow` 可用。
- [ ] 写入使用 `_tmp -> validate -> replace`。
- [ ] DuckDB 可读取。
- [ ] 列表页不默认计算 `row_count`。
- [ ] 命令示例页面可展示命令。

