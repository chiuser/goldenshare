# 个股资金流向 Lake 数据集接入说明

- 版本：v1
- 状态：已接入
- 更新时间：2026-05-03
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

### 1.1 生产实现参考审计

接入 Lake 前已对照生产 `moneyflow` 链路做只读审计。生产实现只作为避坑参考，Lake 不直接依赖生产运行代码。

| 生产链路位置 | 当前事实 | Lake 是否借鉴 | Lake 处理口径 |
|---|---|---:|---|
| `DatasetDefinition.source_fields` | 生产字段与 Tushare 源站输出字段一致 | 是 | Lake raw 层使用同一组源站输出字段，不新增 std/serving 字段 |
| `DatasetDefinition.date_model` | `trade_open_day` + `every_open_day` + `point_or_range` | 是 | `trade_date` 单点；`start_date/end_date` 先用本地交易日历展开交易日 |
| `DatasetDefinition.planning` | `offset_limit`，`page_limit=6000` | 是 | 固定 `limit=6000`，`offset` 递增分页 |
| `_moneyflow_params` request builder | 实际只传 `trade_date`，可选 `ts_code` | 是 | Lake 请求参数只包含 `trade_date`、可选 `ts_code`、分页参数 |
| `_moneyflow_row_transform` | 强制 `*_vol` 字段必须是整数格式，并转为 `int` | 是 | Lake 写入前同样校验 `*_vol` 为整数；出现非整数时本交易日分区失败，不写入、不替换旧分区 |
| `DatasetNormalizer.required_fields` | `trade_date`、`ts_code` 必须存在 | 是 | 缺少 `trade_date` 或 `ts_code` 的行拒绝写入，并计入 rejected |
| 生产 writer | `raw_tushare -> core_multi.moneyflow_std -> core_serving.equity_moneyflow` | 否 | Lake 只写本地 `raw_tushare` Parquet，不写 std/serving，不做多源融合 |
| 生产多源逻辑 | 历史上存在 Tushare/BIYING 多源发布链路 | 否 | Lake 本数据集只保存 Tushare `moneyflow` 源事实，不引入 BIYING 或 source resolution |

由此确定本数据集的实现原则：

1. 只复制源站事实、时间语义、分页口径、必填字段校验、`*_vol` 整数校验和进度统计口径。
2. 不复制生产 DB 写入、Ops 状态、TaskRun、std/serving 转换、多源融合和 BIYING 逻辑。
3. Lake raw 层字段必须保持 Tushare 源站输出字段，不新增 `source`、`source_priority`、`std_*`、`serving_*`、`raw_payload` 等字段。
4. 如果后续需要面向研究的单股多年资金流查询优化，应新增 research layout，不污染 raw 层。

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
- 字段命名风险：生产存在 std/serving 统一模型，Lake raw 层不得引入 std/serving 字段别名。

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

### 3.3 新架构代码落点

本数据集按 `Local Lake CLI / Planner / Engine 架构收口方案 v1` 接入，不再把数据集逻辑写入 CLI、Planner 门面或 Engine 门面。

| 接入点 | 文件 | 当前状态 | 说明 |
|---|---|---|---|
| Catalog | `lake_console/backend/app/catalog/datasets/moneyflow.py` | 已接入 | 定义字段、分组、层级与写入策略 |
| Planner | `lake_console/backend/app/sync/planners/trade_date.py` | 已复用 | `moneyflow` 使用交易日类 planner |
| Engine | `lake_console/backend/app/sync/engine.py` | 已接入 | 只通过 strategy registry 分发 |
| Strategy | `lake_console/backend/app/sync/strategies/moneyflow.py` | 已接入 | 调用 `TushareMoneyflowSyncService` |
| Service | `lake_console/backend/app/services/tushare_moneyflow_sync_service.py` | 已接入 | 实现请求、分页、校验、写入 |
| Client | `lake_console/backend/app/services/tushare_client.py` | 已接入 | 新增 `moneyflow(...)` 方法 |
| CLI | `lake_console/backend/app/cli/commands/sync_dataset.py` | 已复用 | 不新增专用命令，使用 `sync-dataset moneyflow` |
| Guardrail | `tests/lake_console/test_sync_architecture_guardrails.py` | 已覆盖 | 防止逻辑回流到大 CLI / 大 Planner / 大 Engine |

新增或修改本数据集时，必须继续遵守：

1. CLI 只负责参数和输出。
2. Planner 只负责计划预览。
3. Engine 只负责 strategy 分发。
4. `moneyflow` 的具体请求、分页、校验、写入只允许留在 `TushareMoneyflowSyncService` 与 `MoneyflowStrategy` 链路内。
5. 不允许为了省事把特殊逻辑写回 `lake_console/backend/app/cli/commands/sync_dataset.py`、`sync/planner.py` 或 `sync/engine.py`。

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
4. 不做股票池扇出，不做枚举扇出，不访问远程数据库。

### 4.3 分页策略

- `limit`：`6000`。
- `offset` 起点：`0`。
- 结束条件：返回行数 `< 6000`。
- 每页是否立即写入：单个 `trade_date` 内按页拉取并累计到本日 buffer；本日请求流结束后一次性写入本日临时分区并替换正式分区。
- 每页是否输出进度：是。

进度输出至少包含：

```text
dataset=moneyflow trade_date=YYYY-MM-DD page=N offset=N fetched_page=N fetched_total=N
```

本日完成时输出：

```text
dataset=moneyflow trade_date=YYYY-MM-DD fetched=N written=N rejected=N output=...
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

写入边界：

1. 最小替换范围是单个 `trade_date` 分区。
2. 单个交易日所有分页请求完成后，写入 `_tmp/{run_id}/raw_tushare/moneyflow/trade_date=YYYY-MM-DD/part-000.parquet`。
3. 校验临时 Parquet 可读、字段完整、有效行数大于 0 后，替换正式分区。
4. 如果本日全市场有效行数为 0，不覆盖已有正式分区。
5. 区间同步中某一天失败，只影响该日期分区，不回滚已完成日期。

### 5.6 行级校验与归一化

| 项 | 规则 |
|---|---|
| 日期归一化 | `trade_date` 从源站 `YYYYMMDD` 归一化为 `YYYY-MM-DD` 字符串 |
| 必填字段 | `trade_date`、`ts_code` |
| 拒绝条件 | 缺少 `trade_date` 或 `ts_code`；`trade_date` 无法解析；返回行所属日期与当前分区日期不一致 |
| 分区失败条件 | 任意 `*_vol` 不是整数格式时，本交易日分区失败，不写入临时 Parquet，不替换正式分区 |
| 整数字段 | `buy_sm_vol/sell_sm_vol/buy_md_vol/sell_md_vol/buy_lg_vol/sell_lg_vol/buy_elg_vol/sell_elg_vol/net_mf_vol` 写为 int64，可空 |
| 数值字段 | `buy_sm_amount/sell_sm_amount/buy_md_amount/sell_md_amount/buy_lg_amount/sell_lg_amount/buy_elg_amount/sell_elg_amount/net_mf_amount` 写为 double，可空 |
| 拒绝统计 | 输出 `rejected` 总数；如实现成本可控，同时输出 reason count |
| raw 字段约束 | 不新增 std/serving/source/raw_payload 等非源站字段 |

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

小文件风险判断：

| 风险项 | warning | error | 本数据集判断 |
|---|---:|---:|---|
| 单文件平均大小 | `< 8MB` | `< 1MB` | 单日文件可能偏小，首次同步后以实际 `total_bytes/file_count` 校准 |
| 单分区文件数 | `> 20` | `> 100` | 第一版固定单分区 1 文件，风险低 |
| 单数据集文件数 | `> 10000` | `> 50000` | 10 年约 2440 文件，风险可控 |

说明：

1. `moneyflow` 单日一文件天然偏小，但按日分区利于补数和按日研究。
2. 该数据集字段多于 `daily`，单文件大小会比 `daily` 更大。
3. 不建议第一版做 research 重排，除非后续确认常用查询是“单股多年资金流回测”。
4. 如果后续常用查询转为“单股多年资金流回测”，再评审 `moneyflow_by_symbol_month` research layout，不改变 raw by_date。

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

命令示例必须来自后端 Lake catalog，不由前端硬编码。

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
5. 风险提示：空分区、临时目录残留、小文件风险。

---

## 9. 校验与测试

### 9.1 文档校验

```bash
python3 scripts/check_docs_integrity.py
```

### 9.2 单元测试

| 测试 | 目的 |
|---|---|
| 测试 | 当前状态 | 目的 |
|---|---|---|
| `test_lake_moneyflow_replace_partition_and_int64_volume_fields` | 已实现 | 按日分区写入、`*_vol` 使用整数 |
| `test_lake_moneyflow_paginates_until_short_page` | 已实现 | `limit=6000`、`offset` 递增直到短页 |
| `test_lake_moneyflow_fails_partition_on_non_integer_volume_fields` | 已实现 | `*_vol` 非整数格式时本交易日分区失败 |
| `test_lake_planner_dispatches_to_planner_modules` | 已实现 | `moneyflow` 通过 trade_date planner 门面分发 |
| `test_lake_sync_engine_uses_strategy_registry` | 已实现 | engine 只通过 strategy registry 分发 |
| `test_lake_sync_strategy_registry_is_explicit` | 已实现 | strategy 显式注册，避免 catalog 与 engine 脱节 |
| `test_lake_console_does_not_import_production_runtime_code` | 已实现 | 不 import 生产 Ops/App/Frontend，不访问远程 DB |

### 9.3 真实同步冒烟

```bash
lake-console plan-sync moneyflow --trade-date 2026-04-24
lake-console sync-dataset moneyflow --trade-date 2026-04-24
```

DuckDB 验证：

```bash
duckdb -c "select count(*) from read_parquet('<LAKE_ROOT>/raw_tushare/moneyflow/trade_date=2026-04-24/*.parquet');"
```

---

## 10. 风险与回滚

| 风险 | 影响 | 防护 | 回滚 |
|---|---|---|---|
| 单日返回达到分页上限 | 数据不完整 | 必须 offset 分页直到 `< limit` | 重跑分区 |
| 空结果覆盖旧数据 | 数据丢失 | 空结果拒绝覆盖已有分区 | 保留旧分区 |
| `*_vol` 类型过小 | 溢出 | 使用 int64 | 修正 schema 后重跑 |
| `*_vol` 返回小数 | 污染整数口径 | 本交易日分区失败，不替换旧分区 | 排查源站返回后重跑 |
| 误复制生产多源融合 | Lake raw 被生产 std/serving 语义污染 | 方案明确只写源站字段 | 删除错误分区后按 raw 口径重跑 |
| 区间过大 | 请求耗时长 | `plan-sync` 展示交易日数量 | 缩小区间 |

---

## 11. Checklist

编码前：

- [ ] 已阅读 `AGENTS.md`。
- [ ] 已阅读 `lake_console/AGENTS.md`。
- [ ] 已确认不访问远程 DB。
- [ ] 已确认源站文档。
- [ ] 已确认生产 DatasetDefinition。
- [ ] 已确认生产 request builder、row transform、writer 中可借鉴和不可复制的部分。
- [ ] 已确认本地交易日历依赖。
- [ ] 已确认按日分区。
- [ ] 已确认 `*_vol` 使用 int64。
- [ ] 已确认 `*_vol` 非整数格式会导致本交易日分区失败。
- [ ] 已确认展示分组来自 Ops 第 10 节目标分组表。
- [ ] 已完成数据量、文件数、文件大小估算。
- [ ] 已确认不需要 manifest 双落盘。
- [ ] 已确认不需要 derived/research。
- [ ] 已确认写入策略。
- [ ] 已确认命令示例。

编码后：

- [x] `plan-sync moneyflow` 可用。
- [x] `sync-dataset moneyflow` 可用。
- [x] 命令有进度输出。
- [x] 写入使用 `_tmp -> validate -> replace`。
- [ ] DuckDB 可读取。
- [ ] 列表页不默认计算 `row_count`。
- [ ] 详情页可展示层级与分区。
- [ ] 命令示例页面可展示命令。
- [x] 没有 import 生产 Ops / App / Frontend。
- [x] 文档校验通过。
