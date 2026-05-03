# 股票日线 Lake 数据集接入说明

- 版本：v1
- 状态：首版已实现
- 更新时间：2026-05-03
- 数据集 key：`daily`
- 数据源：Tushare
- 源站文档：`docs/sources/tushare/股票数据/行情数据/0027_A股日线行情.md`
- 参考模板：`docs/templates/lake-dataset-development-template.md`

---

## 0. 架构基线与禁止项

本数据集只接入 `lake_console` 本地移动盘 Parquet Lake，不接入生产 Ops 任务链。

必须遵守：

1. 不访问远程 `goldenshare-db`。
2. 区间同步只能读取本地 `manifest/trading_calendar/tushare_trade_cal.parquet` 展开交易日。
3. 写入必须按 `trade_date` 分区，使用 `_tmp -> 校验 -> 替换正式分区`。
4. 大区间必须逐交易日处理，不允许把多年数据一次性写入单个大事务或单个内存集合。
5. 前端展示分组参考 Ops 默认展示目录。

---

## 1. 基本信息

| 项 | 值 |
|---|---|
| 数据集 key | `daily` |
| 中文显示名 | 股票日线 |
| 数据源 | `tushare` |
| 源站 API | `daily` |
| 源站 doc_id | `27` |
| 源站链接 | `https://tushare.pro/document/2?doc_id=27` |
| 本地源站文档 | `docs/sources/tushare/股票数据/行情数据/0027_A股日线行情.md` |
| 生产 DatasetDefinition | 已存在 |
| 生产定义文件 | `src/foundation/datasets/definitions/market_equity.py` |
| 是否依赖本地 manifest | 是，交易日历 |
| 是否双落盘 manifest | 否 |
| 是否需要 derived 层 | 否 |
| 是否需要 research 层 | 第一阶段不做；后续建议专项评审 `daily_by_symbol_month` 或 `daily_by_symbol_year` |

生产 `DatasetDefinition` 当前事实：

| 字段 | 值 |
|---|---|
| `source.api_name` | `daily` |
| `source.request_builder_key` | `_daily_params` |
| `date_model.date_axis` | `trade_open_day` |
| `date_model.bucket_rule` | `every_open_day` |
| `date_model.window_mode` | `point_or_range` |
| `date_model.observed_field` | `trade_date` |
| `planning.pagination_policy` | `offset_limit` |
| `planning.page_limit` | `6000` |
| `storage.raw_table` | `raw_tushare.daily` |

### 1.1 生产实现参考审计

接入 Lake 前已对照生产 `daily` 链路做只读审计。生产实现只作为避坑参考，Lake 不直接依赖生产运行代码。

| 生产链路位置 | 当前事实 | Lake 是否借鉴 | Lake 处理口径 |
|---|---|---:|---|
| `DatasetDefinition.source_fields` | 生产字段为 `ts_code/trade_date/open/high/low/close/pre_close/change/pct_chg/vol/amount` | 是 | Lake raw 层使用同一组源站输出字段，不新增 serving 字段 |
| `DatasetDefinition.date_model` | `trade_open_day` + `every_open_day` + `point_or_range` | 是 | `trade_date` 单点；`start_date/end_date` 先用本地交易日历展开交易日 |
| `DatasetDefinition.planning` | `offset_limit`，`page_limit=6000` | 是 | 固定 `limit=6000`，`offset` 递增分页 |
| `_daily_params` request builder | 实际只传 `trade_date`，可选 `ts_code` | 是 | Lake 请求参数只包含 `trade_date`、可选 `ts_code`、分页参数 |
| `input_model.filters.exchange` | 生产定义里有 `exchange`，但 `_daily_params` 不使用 | 否 | Lake 不暴露、不传递 `exchange`，避免复制无效参数 |
| `_daily_row_transform` | 生产写 serving 时把 `change` 映射为 `change_amount`，并补 `source=tushare` | 否 | Lake raw 层保留源站字段 `change`，不写 `change_amount/source` |
| `DatasetNormalizer.required_fields` | `trade_date`、`ts_code` 必须存在 | 是 | 缺少 `trade_date` 或 `ts_code` 的行拒绝写入，并计入 rejected |
| `IngestionExecutor` | 每个执行 unit 独立 fetch/normalize/write/commit，并上报 fetched/written/rejected | 是 | Lake 以单个 `trade_date` 为最小替换单元，进度输出同样包含 fetched/written/rejected |
| 生产 writer | `raw_core_upsert` 写远程 Postgres 与 serving 表 | 否 | Lake 只写本地 Parquet，不访问远程数据库 |

由此确定本数据集的实现原则：

1. 只复制源站事实、时间语义、分页口径、必填字段校验和进度统计口径。
2. 不复制生产 DB 写入、Ops 状态、TaskRun、serving 字段转换和无效 filter。
3. `exchange` 不进入 Lake `daily` 的命令参数、请求参数或 catalog 字段。
4. `change` 保持源站字段名；如后续研究层需要别名，应在 research layout 单独设计，不污染 raw 层。

---

## 2. 源站接口分析

### 2.1 输入参数

| 参数名 | 类型 | 必填 | 说明 | 类别 | 是否支持多值 | Lake 用户是否可填写 | 默认值 | 备注 |
|---|---|---:|---|---|---:|---:|---|---|
| `ts_code` | str | 否 | 股票代码，支持逗号分隔 | 代码 | 是 | 是 | 空 | 第一版不用于全市场扇出 |
| `trade_date` | str | 否 | 交易日期 | 时间 | 否 | 是 | 空 | 单日同步主参数 |
| `start_date` | str | 否 | 开始日期 | 时间 | 否 | 是 | 空 | 区间由本地交易日历展开 |
| `end_date` | str | 否 | 结束日期 | 时间 | 否 | 是 | 空 | 区间由本地交易日历展开 |
| `limit` | int | 否 | 单次返回数据长度 | 分页 | 否 | 否 | `6000` | Lake 固定 |
| `offset` | int | 否 | 请求数据开始位移量 | 分页 | 否 | 否 | `0` 起 | Lake 递增 |

不支持也不暴露 `exchange`。生产定义中虽然残留该 filter，但生产 `_daily_params` 实际不使用，且 Tushare `daily` 接口当前请求不需要该参数。

### 2.2 输出字段

| 字段名 | 类型 | 含义 | 是否写入 Parquet | Lake 字段类型 | 是否可空 | 备注 |
|---|---|---|---:|---|---:|---|
| `ts_code` | str | 股票代码 | 是 | string | 否 |  |
| `trade_date` | str | 交易日期 | 是 | string | 否 | 分区字段也来自该值 |
| `open` | float | 开盘价 | 是 | double | 是 |  |
| `high` | float | 最高价 | 是 | double | 是 |  |
| `low` | float | 最低价 | 是 | double | 是 |  |
| `close` | float | 收盘价 | 是 | double | 是 |  |
| `pre_close` | float | 昨收价 | 是 | double | 是 |  |
| `change` | float | 涨跌额 | 是 | double | 是 |  |
| `pct_chg` | float | 涨跌幅 | 是 | double | 是 |  |
| `vol` | float | 成交量（手） | 是 | double | 是 | 源站定义为 float，Lake 用 double 承接，不转 int |
| `amount` | float | 成交额（千元） | 是 | double | 是 |  |

### 2.3 源端行为

- 是否分页：是。
- 分页参数：`limit` / `offset`。
- 单次最大返回：源文档说明每次 `6000` 条。
- 分页结束条件：返回行数 `< 6000`。
- 是否限速：基础积分每分钟可调取 500 次，Lake 使用全局 Tushare 限速配置。
- 是否支持按日期请求：支持 `trade_date`。
- 是否支持按区间请求：支持 `start_date` / `end_date`，但 Lake 全市场默认按交易日逐日请求。
- 是否支持代码参数：支持 `ts_code`，且源站支持逗号分隔。
- 是否支持枚举参数：否。
- 上游空行风险：非交易日或停牌股票可能无数据；按交易日全市场返回空时需告警，不应静默覆盖。
- 字段类型风险：`vol` 文档为 float，不应转 int。
- 字段命名风险：生产 serving 层存在 `change_amount`，Lake raw 层不得使用该别名，必须保留源站 `change`。

---

## 3. Lake Catalog 设计

### 3.1 展示分组

| 字段 | 值 |
|---|---|
| `group_key` | `equity_market` |
| `group_label` | A股行情 |
| `group_order` | 2 |

### 3.2 Lake Dataset Catalog 字段

| 字段 | 值 | 说明 |
|---|---|---|
| `dataset_key` | `daily` | 唯一标识 |
| `display_name` | 股票日线 | 中文展示名 |
| `source` | `tushare` | 数据来源 |
| `api_name` | `daily` | 源站 API |
| `source_doc_id` | `27` | 源站文档 ID |
| `primary_layout` | `by_date` | 按交易日 |
| `available_layouts` | `by_date` | 第一版只做原始层 |
| `write_policy` | `replace_partition` | 按日替换 |
| `update_mode` | `manual_cli` | CLI 手动 |
| `page_limit` | `6000` | 分页上限 |
| `request_strategy_key` | `daily` | 独立策略 |
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

1. 用户传 `trade_date`：请求 `daily(trade_date=YYYYMMDD, limit=6000, offset=...)`。
2. 用户传 `start_date/end_date` 且未传 `ts_code`：读取本地交易日历，逐个交易日请求。
3. 用户传 `ts_code + start_date/end_date`：允许作为单股区间调试模式，但写入仍按返回行的 `trade_date` 分区。
4. 无论哪种模式，都不传 `exchange`。

### 4.3 分页策略

- `limit`：`6000`。
- `offset` 起点：`0`。
- 结束条件：返回行数 `< 6000`。
- 每页是否立即写入：单个 `trade_date` 内按页拉取并累计到本日 buffer；本日请求流结束后一次性写入本日临时分区并替换正式分区。
- 每页是否输出进度：是。

进度输出至少包含：

```text
dataset=daily trade_date=YYYY-MM-DD page=N offset=N fetched_page=N fetched_total=N
```

本日完成时输出：

```text
dataset=daily trade_date=YYYY-MM-DD fetched=N written=N rejected=N output=...
```

### 4.4 本地依赖

| 依赖 | 来源 | 缺失时行为 |
|---|---|---|
| 交易日历 | `manifest/trading_calendar/tushare_trade_cal.parquet` | 区间同步失败并提示先同步 |

---

## 5. Parquet 存储设计

### 5.1 层级

| 层级 | 是否使用 | 用途 |
|---|---:|---|
| `raw_tushare` | 是 | Tushare 股票日线原始事实 |
| `manifest` | 否 |  |
| `derived` | 否 |  |
| `research` | 否 | 第一阶段不做；后续可评审按股票和月份/年份重排 |

### 5.2 路径设计

| 层级 | 路径模板 | 替换范围 |
|---|---|---|
| `raw_tushare` | `raw_tushare/daily/trade_date=YYYY-MM-DD/part-000.parquet` | 单交易日分区 |

### 5.3 分区字段

| 分区字段 | 类型 | 说明 |
|---|---|---|
| `trade_date` | date string | 交易日，目录格式 `YYYY-MM-DD` |

### 5.4 文件命名

- 单文件：`part-000.parquet`。
- 是否允许多 part：第一版默认否。
- 多 part 触发条件：若单日超过内存或文件大小阈值，再评审增加 `part-xxxxx`。

### 5.5 写入策略

| 策略 | 是否使用 | 说明 |
|---|---:|---|
| `replace_file` | 否 |  |
| `replace_partition` | 是 | 替换单个交易日分区 |
| `rebuild_month` | 否 |  |
| `append_only` | 否 |  |

写入边界：

1. 最小替换范围是单个 `trade_date` 分区。
2. 单个交易日所有分页请求完成后，写入 `_tmp/{run_id}/raw_tushare/daily/trade_date=YYYY-MM-DD/part-000.parquet`。
3. 校验临时 Parquet 可读、字段完整、有效行数大于 0 后，替换正式分区。
4. 如果本日全市场有效行数为 0，不覆盖已有正式分区。
5. 区间同步中某一天失败，只影响该日期分区，不回滚已完成日期。

### 5.6 行级校验与归一化

| 项 | 规则 |
|---|---|
| 日期归一化 | `trade_date` 从源站 `YYYYMMDD` 归一化为 `YYYY-MM-DD` 字符串 |
| 必填字段 | `trade_date`、`ts_code` |
| 拒绝条件 | 缺少 `trade_date` 或 `ts_code`；`trade_date` 无法解析；返回行所属日期与当前分区日期不一致 |
| 数值字段 | `open/high/low/close/pre_close/change/pct_chg/vol/amount` 写为 double，可空 |
| 拒绝统计 | 输出 `rejected` 总数；如实现成本可控，同时输出 reason count |
| raw 字段约束 | 不新增 `change_amount`、`source`、`raw_payload` 等非源站字段 |

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
| 单文件大小 | 预计小于 5MB |

小文件风险：

1. `daily` 单日文件天然偏小，但按日分区利于补数和按日扫描。
2. `daily` 不建议为了减少文件数改为按月 raw 分区，否则补某一天需要重写整月。
3. 后续如研究侧需要长周期单股查询，可另建 `daily_by_symbol_month` 或 `daily_by_symbol_year` research layout，不改变 raw by_date。

---

## 7. 命令设计

### 7.1 `plan-sync`

```bash
lake-console plan-sync daily --trade-date 2026-04-24
lake-console plan-sync daily --start-date 2026-04-01 --end-date 2026-04-30
lake-console plan-sync daily --ts-code 600000.SH --start-date 2026-04-01 --end-date 2026-04-30
```

### 7.2 同步命令

```bash
lake-console sync-dataset daily --trade-date 2026-04-24
lake-console sync-dataset daily --start-date 2026-04-01 --end-date 2026-04-30
lake-console sync-dataset daily --ts-code 600000.SH --start-date 2026-04-01 --end-date 2026-04-30
```

是否需要专用命令：否。

### 7.3 命令示例页

| 标题 | 说明 | 命令 |
|---|---|---|
| 同步单日全市场日线 | 写入一个 `trade_date` 分区 | `lake-console sync-dataset daily --trade-date 2026-04-24` |
| 同步区间全市场日线 | 用本地交易日历展开交易日 | `lake-console sync-dataset daily --start-date 2026-04-01 --end-date 2026-04-30` |
| 同步单股区间日线 | 适合调试或补单股 | `lake-console sync-dataset daily --ts-code 600000.SH --start-date 2026-04-01 --end-date 2026-04-30` |

---

## 8. 前端展示设计

列表页默认展示：

1. 分组：A股行情。
2. 数据集：股票日线。
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
| `test_lake_catalog_daily` | catalog 字段、分组、命令示例完整 |
| `test_lake_plan_daily_trade_date` | 单日请求计划 |
| `test_lake_plan_daily_range_uses_local_trade_cal` | 区间模式使用本地交易日历 |
| `test_lake_sync_daily_replace_partition` | 按日分区原子替换 |
| `test_lake_sync_daily_paginates_until_short_page` | `limit=6000`、`offset` 递增直到短页 |
| `test_lake_sync_daily_does_not_send_exchange` | 确认请求参数不包含 `exchange` |
| `test_lake_sync_daily_rejects_missing_required_fields` | 缺少 `trade_date/ts_code` 的行不写入 |
| `test_lake_sync_daily_preserves_source_change_field` | 写入字段保留 `change`，不生成 `change_amount` |

### 9.3 真实同步冒烟

```bash
lake-console plan-sync daily --trade-date 2026-04-24
lake-console sync-dataset daily --trade-date 2026-04-24
```

DuckDB 验证：

```sql
select count(*) from read_parquet('<LAKE_ROOT>/raw_tushare/daily/trade_date=2026-04-24/*.parquet');
```

---

## 10. 风险与回滚

| 风险 | 影响 | 防护 | 回滚 |
|---|---|---|---|
| 非交易日误请求 | 返回空 | 区间模式只读本地交易日历 | 不写分区 |
| 单日空结果覆盖旧数据 | 数据丢失 | 空结果拒绝覆盖已有分区 | 保留旧分区 |
| 文件过小 | 查询规划成本增加 | 当前可接受，后续 research 优化 | 不影响 raw |
| 区间过大 | 请求时间过长 | `plan-sync` 提示交易日数量 | 缩小区间 |

---

## 11. Checklist

编码前：

- [ ] 已确认源站文档。
- [ ] 已确认生产 DatasetDefinition。
- [ ] 已确认本地交易日历依赖。
- [ ] 已确认按日分区。
- [ ] 已确认命令示例。

编码后：

- [ ] `plan-sync daily` 可用。
- [ ] `sync-dataset daily` 可用。
- [ ] 写入使用 `_tmp -> validate -> replace`。
- [ ] DuckDB 可读取。
- [ ] 列表页不默认计算 `row_count`。
- [ ] 命令示例页面可展示命令。
