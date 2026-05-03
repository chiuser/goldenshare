# Local Lake 数据集接入说明模板

> 使用说明：
> - 每新增一个 Lake 数据集，先复制本模板生成独立方案文档。
> - 建议放在 `docs/datasets/`，命名为 `<dataset-key>-lake-dataset-development.md`。
> - 未完成本文档，不得进入 `lake_console` 编码。
> - 本模板只适用于 `lake_console` 本地移动盘 Parquet Lake，不适用于生产 Ops 数据维护链路。

---

## 0. 架构基线与禁止项

### 0.1 当前必须遵守的主线

1. `lake_console` 是本地独立工程，不是生产 `src/ops`、`src/app`、`frontend` 的一部分。
2. `lake_console` 不允许读取或写入远程 `goldenshare-db`。
3. `lake_console` 不允许 import `src/ops/**`、生产 `src/app/**`、生产 `frontend/src/**`。
4. Lake 数据集事实可以参考生产 `DatasetDefinition` 和源站文档，但不得直接复用生产同步运行时。
5. 所有写入必须使用 `_tmp -> 校验 -> 替换正式文件/分区`。
6. 长任务必须有进度输出。
7. 大表必须分页请求、分批写入，不能整任务攒在内存里最后一次写。

### 0.2 禁止项

1. 禁止为了省事读取远程数据库补股票池、指数池、交易日历或状态。
2. 禁止让 Lake 页面依赖生产 Ops API。
3. 禁止直接覆盖正式 Parquet 文件或分区。
4. 禁止新增没有 `plan-sync` 或命令示例的数据集。
5. 禁止前端自行拼数据集路径、分区路径或命令模板。
6. 禁止把 `raw_tushare`、`derived`、`research`、`manifest` 混成一个不可解释的扁平列表。
7. 禁止把生产 `DatasetDefinition.domain` 或 catalog 代码文件名当作前端展示分组。

---

## 1. 标准交付流程

1. 固定源站事实：官方文档、输入参数、输出字段、分页、限速、更新时间。
2. 确认数据集是否适合进入 Lake；不适合的要写清暂缓原因。
3. 完成本文档，明确请求策略、Parquet 存储策略、文件规模估算和页面展示方案。
4. 新增或更新 Lake Dataset Catalog。
5. 新增或更新请求策略文件。
6. 新增或更新命令示例。
7. 新增或更新 `plan-sync` 输出。
8. 新增最小测试。
9. 本地跑小窗口真实同步。
10. 用 DuckDB 验证 Parquet 可读。
11. 更新相关 README 或索引。

---

## 2. 基本信息

- 数据集 key：
- 中文显示名：
- 数据源：`tushare` / `biying` / 其他
- 源站 API 名称：
- 源站文档链接：
- 本地源站文档路径：
- 是否已经存在生产 `DatasetDefinition`：是 / 否
- 对应生产 `DatasetDefinition` 路径：
- 是否依赖本地 manifest：是 / 否
- 是否需要作为 manifest 双落盘：是 / 否
- 是否需要 `derived` 层：是 / 否
- 是否需要 `research` 层：是 / 否

---

## 3. 源站接口分析

### 3.1 输入参数

| 参数名 | 类型 | 必填 | 说明 | 类别（时间/代码/枚举/分页/其他） | 是否支持多值 | Lake 用户是否可填写 | 默认值 | 备注 |
|---|---|---:|---|---|---:|---:|---|---|

### 3.2 输出字段

| 字段名 | 类型 | 含义 | 是否写入 Parquet | Lake 字段类型 | 是否可空 | 备注 |
|---|---|---|---:|---|---:|---|

### 3.3 源端行为

- 是否分页：
- 分页参数：
- 单次最大返回：
- 分页结束条件：
- 是否限速：
- 是否支持按日期请求：
- 是否支持按区间请求：
- 是否支持代码参数：
- 是否支持枚举参数：
- 枚举多值是否必须扇出：
- 是否存在上游返回空行但实际应有数据的风险：
- 是否存在字段类型与文档不一致风险：

---

## 4. Lake Catalog 设计

### 4.1 展示分组

Lake 前端展示分组必须参考：

```text
docs/ops/ops-dataset-catalog-view-plan-v1.md
```

第 10 节目标展示分组表。

| 字段 | 值 |
|---|---|
| `group_key` |  |
| `group_label` |  |
| `group_order` |  |

说明：

1. 不得用生产 `DatasetDefinition.domain` 直接做前端分组。
2. 不得用 `catalog/datasets/*.py` 文件名做前端分组。
3. 如果 Ops 目标展示分组表没有该数据集，先补方案评审，不得放入“其他”。

### 4.2 Lake Dataset Catalog 字段

| 字段 | 值 | 说明 |
|---|---|---|
| `dataset_key` |  | 唯一标识 |
| `display_name` |  | 中文展示名 |
| `source` |  | 数据来源 |
| `api_name` |  | 源站 API |
| `source_doc_id` |  | 源站文档 ID |
| `primary_layout` |  | 主布局 |
| `available_layouts` |  | 可用布局 |
| `write_policy` |  | 写入策略 |
| `update_mode` |  | 更新入口 |
| `page_limit` |  | 分页上限 |
| `request_strategy_key` |  | 请求策略 |
| `supported_commands` |  | 支持命令 |

### 4.3 Sync 架构接入点

新增数据集必须明确以下代码落点。不得把数据集逻辑写回 CLI、Planner 门面或 Engine 门面。

| 接入点 | 文件 | 是否需要新增/修改 | 说明 |
|---|---|---:|---|
| Catalog | `lake_console/backend/app/catalog/datasets/<group>.py` |  | 定义展示、层级、路径、写入策略 |
| Planner | `lake_console/backend/app/sync/planners/<type>.py` |  | 选择 snapshot / trade_date / stk_mins 或新增明确类型 |
| Strategy | `lake_console/backend/app/sync/strategies/<dataset_key>.py` |  | 单数据集请求、分页、校验、写入 |
| Strategy registry | `lake_console/backend/app/sync/strategies/__init__.py` |  | 显式注册已实现数据集 |
| CLI | `lake_console/backend/app/cli/commands/sync_dataset.py` |  | 普通数据集默认不新增专用命令，只复用 `sync-dataset` |
| Tests | `tests/lake_console/*` |  | 计划、策略、隔离和必要 smoke |

---

## 5. 请求策略设计

### 5.1 请求模式

选择一种或多种：

| 模式 | 是否使用 | 说明 |
|---|---:|---|
| `snapshot_current` | 否 | 快照 / current 文件 |
| `trade_date_points` | 否 | 按交易日逐日请求 |
| `natural_date_points` | 否 | 按自然日逐日请求 |
| `month_key_points` | 否 | 按 `YYYYMM` 请求 |
| `month_window` | 否 | 按自然月首尾请求 |
| `datetime_window` | 否 | 按 datetime 区间请求 |
| `enum_fanout` | 否 | 枚举字段扇出 |
| `security_universe_fanout` | 否 | 本地证券池扇出 |

### 5.2 请求单元生成

- 用户输入：
- 本地依赖：
- 请求单元粒度：
- 单元数量估算：
- 是否支持 `plan-sync` 预览：
- 失败后可重跑的最小粒度：

### 5.3 分页策略

- `limit`：
- `offset` 起点：
- 结束条件：
- 每页是否立即写入：
- 每页是否输出进度：

### 5.4 本地依赖

| 依赖 | 来源 | 缺失时行为 |
|---|---|---|
| 交易日历 | `manifest/trading_calendar/tushare_trade_cal.parquet` | 失败并提示先同步 |
| 股票池 | `manifest/security_universe/tushare_stock_basic.parquet` | 失败并提示先同步 |
| 指数池 |  |  |
| 板块池 |  |  |

禁止从远程 DB 获取这些依赖。

---

## 6. Parquet 存储设计

### 6.1 层级

| 层级 | 是否使用 | 用途 |
|---|---:|---|
| `raw_tushare` | 是 | 源站原始事实 |
| `manifest` | 否 | 执行辅助清单 |
| `derived` | 否 | 本地派生数据 |
| `research` | 否 | 查询优化重排 |

说明：

1. 双落盘数据集必须同时展示 `raw_tushare` 和 `manifest`。
2. `derived` / `research` 第一版作为原数据集子层展示，不作为独立数据集卡片。

### 6.2 路径设计

| 层级 | 路径模板 | 替换范围 |
|---|---|---|
| `raw_tushare` |  |  |
| `manifest` |  |  |
| `derived` |  |  |
| `research` |  |  |

常见路径：

```text
raw_tushare/<dataset_key>/current/part-000.parquet
raw_tushare/<dataset_key>/trade_date=YYYY-MM-DD/part-000.parquet
raw_tushare/<dataset_key>/month=YYYY-MM/part-000.parquet
raw_tushare/<dataset_key>/<date_field>=YYYY-MM-DD/part-000.parquet
```

### 6.3 分区字段

| 分区字段 | 类型 | 说明 |
|---|---|---|

### 6.4 文件命名

- 单文件：`part-000.parquet`
- 多文件：`part-00000.parquet`、`part-00001.parquet`
- 是否允许多 part：
- 多 part 触发条件：

### 6.5 写入策略

| 策略 | 是否使用 | 说明 |
|---|---:|---|
| `replace_file` | 否 | 全量替换单文件 |
| `replace_partition` | 否 | 替换单个分区 |
| `rebuild_month` | 否 | 重建某月 research |
| `append_only` | 否 | 原则上慎用，需说明去重策略 |

所有策略必须走：

```text
_tmp -> 校验 -> 替换正式文件/分区
```

---

## 7. 数据量与文件数评估

### 7.1 数据量估算

| 维度 | 估算 |
|---|---:|
| 单请求最大行数 |  |
| 单日行数 |  |
| 单月行数 |  |
| 单年行数 |  |
| 10 年行数 |  |

### 7.2 文件数估算

| 场景 | 估算文件数 |
|---|---:|
| 单日 |  |
| 单月 |  |
| 单年 |  |
| 10 年 |  |

### 7.3 单文件大小估算

| 场景 | 估算大小 |
|---|---:|
| 满 part 文件 |  |
| 低频小分区文件 |  |
| 单日总大小 |  |
| 单年总大小 |  |

### 7.4 小文件风险

默认参考阈值：

| 风险项 | warning | error |
|---|---:|---:|
| 单文件平均大小 | `< 8MB` | `< 1MB` |
| 单分区文件数 | `> 20` | `> 100` |
| 单数据集文件数 | `> 10000` | `> 50000` |

本数据集判断：

- 是否可能出现小文件过多：
- 是否需要调大 `part_rows`：
- 是否需要 research 重排：
- 是否需要后续 compact 命令：

---

## 8. 命令设计

### 8.1 `plan-sync`

```bash
lake-console plan-sync <dataset_key> ...
```

需要输出：

1. 请求数量。
2. 分区数量。
3. 预计写入路径。
4. 是否需要本地 manifest。
5. 是否可能触发大量请求。

### 8.2 同步命令

```bash
lake-console sync-dataset <dataset_key> ...
```

或专用命令：

```bash
lake-console sync-<dataset-key> ...
```

是否需要专用命令：

原因：

### 8.3 命令示例

每个数据集必须提供命令示例，用于“命令示例 / 操作提示”页面。

| 标题 | 说明 | 命令 |
|---|---|---|

---

## 9. 前端展示设计

### 9.1 列表页

默认展示：

1. 分组。
2. 数据集名称。
3. 层级数量。
4. `file_count`。
5. `total_bytes`。
6. 日期范围。
7. 最近修改时间。

默认不展示：

1. `row_count`。

### 9.2 详情页

详情页展示：

1. `raw_tushare` 层。
2. `manifest` 层。
3. `derived` 层。
4. `research` 层。
5. 分区列表。
6. 文件列表。
7. 风险提示。
8. 可显式计算 `row_count`。

### 9.3 命令示例页

交互：

1. 选择分组。
2. 选择数据集。
3. 展示命令例子。

说明：

1. 第一版只展示命令，不执行。
2. 命令例子来自后端 catalog，不由前端硬编码。

---

## 10. 校验与测试

### 10.1 文档校验

```bash
python3 scripts/check_docs_integrity.py
```

### 10.2 单元测试

| 测试 | 目的 |
|---|---|
| catalog 完整性 | 数据集字段、分组、命令示例齐全 |
| 请求计划 | `plan-sync` 输出符合源站参数 |
| 分页 | `limit/offset` 结束条件正确 |
| 写入替换 | `_tmp -> validate -> replace` 正确 |
| 禁远程 DB | `lake_console` 不依赖远程 DB |
| 命令示例 | 命令模板与真实 CLI 参数一致 |

### 10.3 真实同步冒烟

最小真实同步命令：

```bash

```

DuckDB 验证：

```bash

```

---

## 11. 风险与回滚

| 风险 | 影响 | 防护 | 回滚 |
|---|---|---|---|
| 请求量过大 | 同步过慢或超限 | `plan-sync` 预览 + 限速 | 缩小日期窗口 |
| 文件过多 | 查询和扫描慢 | 分区评审 + part_rows | 后续 compact |
| 写入中断 | 临时目录残留 | `_tmp` 隔离 | 删除 `_tmp/{run_id}` |
| schema 漂移 | DuckDB 查询失败 | 写入前后校验 | 回滚分区 |
| 本地依赖缺失 | 同步失败 | 启动前检查 manifest | 先同步依赖 |

---

## 12. Checklist

编码前：

- [ ] 已阅读 `AGENTS.md`
- [ ] 已阅读 `lake_console/AGENTS.md`
- [ ] 已确认不访问远程 DB
- [ ] 已确认源站文档路径
- [ ] 已确认输入参数和分页上限
- [ ] 已确认输出字段和 Parquet 类型
- [ ] 已确认展示分组来自 Ops 第 10 节目标分组表
- [ ] 已完成数据量、文件数、文件大小估算
- [ ] 已确认是否需要 manifest
- [ ] 已确认是否需要 derived/research
- [ ] 已确认写入策略
- [ ] 已写明命令示例

编码后：

- [ ] `plan-sync` 可用
- [ ] 同步命令可用
- [ ] 命令有进度输出
- [ ] 写入使用 `_tmp -> validate -> replace`
- [ ] DuckDB 可读取
- [ ] 列表页不默认计算 `row_count`
- [ ] 详情页可展示层级与分区
- [ ] 命令示例页面可展示该数据集命令
- [ ] 没有 import 生产 Ops / App / Frontend
- [ ] 文档校验通过
