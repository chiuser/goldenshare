# 指数基础信息 Lake 数据集接入说明

- 版本：v1
- 状态：待评审
- 更新时间：2026-05-01
- 数据集 key：`index_basic`
- 数据源：Tushare
- 源站文档：`docs/sources/tushare/指数专题/0094_指数基本信息.md`
- 参考模板：`docs/templates/lake-dataset-development-template.md`

---

## 0. 架构基线与禁止项

本数据集只接入 `lake_console` 本地移动盘 Parquet Lake，不接入生产 Ops 任务链。

必须遵守：

1. 不访问远程 `goldenshare-db`。
2. 不 import `src/ops/**`、生产 `src/app/**`、生产 `frontend/src/**`。
3. 不复用生产同步运行时，只参考 `DatasetDefinition` 与源站文档事实。
4. 写入必须使用 `_tmp -> 校验 -> 替换正式文件`。
5. 前端展示分组参考 Ops 默认展示目录，不使用生产 domain 或 Lake 代码文件名。

---

## 1. 基本信息

| 项 | 值 |
|---|---|
| 数据集 key | `index_basic` |
| 中文显示名 | 指数基础信息 |
| 数据源 | `tushare` |
| 源站 API | `index_basic` |
| 源站 doc_id | `94` |
| 源站链接 | `https://tushare.pro/document/2?doc_id=94` |
| 本地源站文档 | `docs/sources/tushare/指数专题/0094_指数基本信息.md` |
| 生产 DatasetDefinition | 已存在 |
| 生产定义文件 | `src/foundation/datasets/definitions/index_series.py` |
| Lake 是否依赖 manifest | 否；但后续指数行情类数据集会依赖本数据集生成的 index universe manifest |
| 是否双落盘 manifest | 是 |
| 是否需要 derived 层 | 否 |
| 是否需要 research 层 | 否 |

生产 `DatasetDefinition` 当前事实：

| 字段 | 值 |
|---|---|
| `source.api_name` | `index_basic` |
| `source.request_builder_key` | `_index_basic_params` |
| `date_model.date_axis` | `none` |
| `date_model.window_mode` | `point` |
| `planning.pagination_policy` | `offset_limit` |
| `planning.page_limit` | `6000` |
| `storage.raw_table` | `raw_tushare.index_basic` |

---

## 2. 源站接口分析

### 2.1 输入参数

| 参数名 | 类型 | 必填 | 说明 | 类别 | 是否支持多值 | Lake 用户是否可填写 | 默认值 | 备注 |
|---|---|---:|---|---|---:|---:|---|---|
| `ts_code` | str | 否 | 指数代码 | 代码 | 否 | 是 | 空 | 用于单指数筛选 |
| `name` | str | 否 | 指数简称 | 过滤 | 否 | 是 | 空 | 精确含义以源站为准 |
| `market` | str | 否 | 交易所或服务商 | 枚举 | 是 | 是 | 不传 | 多选时必须扇出 |
| `publisher` | str | 否 | 发布商 | 过滤 | 否 | 是 | 空 | 可选 |
| `category` | str | 否 | 指数类别 | 过滤 | 否 | 是 | 空 | 可选 |
| `limit` | int | 否 | 单次返回数据长度 | 分页 | 否 | 否 | `6000` | Lake 固定 |
| `offset` | int | 否 | 请求数据开始位移量 | 分页 | 否 | 否 | `0` 起 | Lake 递增 |

### 2.2 输出字段

| 字段名 | 类型 | 含义 | 是否写入 Parquet | Lake 字段类型 | 是否可空 | 备注 |
|---|---|---|---:|---|---:|---|
| `ts_code` | str | TS代码 | 是 | string | 否 | 主标识 |
| `name` | str | 简称 | 是 | string | 是 |  |
| `fullname` | str | 指数全称 | 是 | string | 是 |  |
| `market` | str | 市场 | 是 | string | 是 |  |
| `publisher` | str | 发布方 | 是 | string | 是 |  |
| `index_type` | str | 指数风格 | 是 | string | 是 |  |
| `category` | str | 指数类别 | 是 | string | 是 |  |
| `base_date` | str | 基期 | 是 | string | 是 | 不强转日期，保持源字段 |
| `base_point` | float | 基点 | 是 | double | 是 |  |
| `list_date` | str | 发布日期 | 是 | string | 是 | 不强转日期，保持源字段 |
| `weight_rule` | str | 加权方式 | 是 | string | 是 |  |
| `desc` | str | 描述 | 是 | string | 是 |  |
| `exp_date` | str | 终止日期 | 是 | string | 是 |  |

### 2.3 源端行为

- 是否分页：是。
- 分页参数：`limit` / `offset`。
- 单次最大返回：生产定义按 `6000`。
- 分页结束条件：返回行数 `< limit`。
- 是否限速：使用 Lake 全局 Tushare 限速配置。
- 是否支持按日期请求：否。
- 是否支持按区间请求：否。
- 是否支持代码参数：支持 `ts_code`。
- 是否支持枚举参数：支持 `market`，用户多选时必须扇出。
- 上游空行风险：快照类接口可能在过滤条件过窄时返回空；全量刷新返回空时不得覆盖正式文件。
- 字段类型风险：日期字段按字符串保留，避免不同市场日期格式导致解析失败。

---

## 3. Lake Catalog 设计

### 3.1 展示分组

| 字段 | 值 |
|---|---|
| `group_key` | `reference_data` |
| `group_label` | A股基础数据 |
| `group_order` | 1 |

依据：`docs/ops/ops-dataset-catalog-view-plan-v1.md` 第 10 节目标展示分组表。

### 3.2 Lake Dataset Catalog 字段

| 字段 | 值 | 说明 |
|---|---|---|
| `dataset_key` | `index_basic` | 唯一标识 |
| `display_name` | 指数基础信息 | 中文展示名 |
| `source` | `tushare` | 数据来源 |
| `api_name` | `index_basic` | 源站 API |
| `source_doc_id` | `94` | 源站文档 ID |
| `primary_layout` | `current_file` | 快照 current 文件 |
| `available_layouts` | `current_file`, `manifest_file` | raw 与 manifest 双落 |
| `write_policy` | `replace_file` | raw current 与 manifest 文件均全量替换 |
| `update_mode` | `manual_cli` | CLI 手动 |
| `page_limit` | `6000` | 分页上限 |
| `request_strategy_key` | `index_basic` | 独立策略 |
| `supported_commands` | `plan-sync`, `sync-dataset` | 先走通用命令 |

---

## 4. 请求策略设计

### 4.1 请求模式

| 模式 | 是否使用 | 说明 |
|---|---:|---|
| `snapshot_current` | 是 | 全量快照写入 current |
| `trade_date_points` | 否 | 无交易日参数 |
| `natural_date_points` | 否 | 无自然日参数 |
| `month_key_points` | 否 | 无月份参数 |
| `month_window` | 否 | 无月份窗口 |
| `datetime_window` | 否 | 无 datetime 窗口 |
| `enum_fanout` | 是 | `market` 多选时扇出 |
| `security_universe_fanout` | 否 | 不需要证券池 |

### 4.2 请求单元生成

- 用户输入：可选 `ts_code`、`market`、`publisher`、`category`。
- 本地依赖：无。
- 请求单元粒度：每个过滤组合一个请求流。
- 单元数量估算：默认 1 个；`market` 多选时按 market 数量增加。
- 是否支持 `plan-sync` 预览：是。
- 失败后可重跑的最小粒度：整个 current 快照。

### 4.3 分页策略

- `limit`：`6000`。
- `offset` 起点：`0`。
- 结束条件：返回行数 `< 6000`。
- 每页是否立即写入：否。快照类数据量小，先聚合到 `_tmp` 单文件。
- 每页是否输出进度：是，输出 `offset` 和 `fetched_rows`。

---

## 5. Parquet 存储设计

### 5.1 层级

| 层级 | 是否使用 | 用途 |
|---|---:|---|
| `raw_tushare` | 是 | 源站原始指数基础信息 |
| `manifest` | 是 | 后续指数行情、周线、月线、成分权重同步使用的本地指数池 |
| `derived` | 否 | 无派生 |
| `research` | 否 | 无重排 |

### 5.2 路径设计

| 层级 | 路径模板 | 替换范围 |
|---|---|---|
| `raw_tushare` | `raw_tushare/index_basic/current/part-000.parquet` | 单文件 |
| `manifest` | `manifest/index_universe/tushare_index_basic.parquet` | 单文件 |

### 5.3 分区字段

无分区字段。该数据集为 current 快照。

### 5.4 文件命名

- 单文件：`part-000.parquet`
- 是否允许多 part：否。
- 多 part 触发条件：无。

### 5.5 写入策略

| 策略 | 是否使用 | 说明 |
|---|---:|---|
| `replace_file` | 是 | 全量替换 raw current 与 index universe manifest |
| `replace_partition` | 否 |  |
| `rebuild_month` | 否 |  |
| `append_only` | 否 |  |

---

## 6. 数据量与文件数评估

| 维度 | 估算 |
|---|---:|
| 单请求最大行数 | 6000 |
| 单次全量行数 | 预计数千到数万，需以首次同步实测为准 |
| 文件数 | 1 |
| 单文件大小 | 预计小于 10MB |

小文件风险：

1. current 快照天然小文件，不按大体量阈值误报。
2. 列表页不默认计算 `row_count`。
3. 详情页可读取 Parquet metadata 计算行数。
4. manifest 文件也必须展示，不能因为它是执行辅助层而从总览中隐藏。

---

## 7. 命令设计

### 7.1 `plan-sync`

```bash
lake-console plan-sync index_basic
lake-console plan-sync index_basic --market CSI
lake-console plan-sync index_basic --market CSI,SSE,SZSE
```

### 7.2 同步命令

```bash
lake-console sync-dataset index_basic
lake-console sync-dataset index_basic --market CSI
lake-console sync-dataset index_basic --market CSI,SSE,SZSE
```

是否需要专用命令：否。

### 7.3 命令示例页

| 标题 | 说明 | 命令 |
|---|---|---|
| 全量刷新指数基础信息 | 拉取全部指数基础信息并替换 current 文件 | `lake-console sync-dataset index_basic` |
| 按市场刷新 | 只拉取指定市场，适合调试 | `lake-console sync-dataset index_basic --market CSI` |
| 预览请求计划 | 不发请求，只展示请求数量和写入路径 | `lake-console plan-sync index_basic --market CSI,SSE,SZSE` |

---

## 8. 前端展示设计

列表页默认展示：

1. 分组：A股基础数据。
2. 数据集：指数基础信息。
3. 层级：`raw_tushare`。
4. `file_count`。
5. `total_bytes`。
6. 最近修改时间。

详情页展示：

1. current 文件路径。
2. 文件大小。
3. 可显式计算 `row_count`。
4. 最近同步命令示例。

---

## 9. 校验与测试

### 9.1 文档校验

```bash
python3 scripts/check_docs_integrity.py
```

### 9.2 单元测试建议

| 测试 | 目的 |
|---|---|
| `test_lake_catalog_index_basic` | catalog 字段、分组、命令示例完整 |
| `test_lake_plan_index_basic_market_fanout` | 多 market 生成多个请求流 |
| `test_lake_sync_index_basic_replace_file` | raw current 文件原子替换 |
| `test_lake_sync_index_basic_manifest_replace_file` | index universe manifest 文件原子替换 |

### 9.3 真实同步冒烟

```bash
lake-console plan-sync index_basic --market CSI
lake-console sync-dataset index_basic --market CSI
```

DuckDB 验证：

```sql
select count(*) from read_parquet('<LAKE_ROOT>/raw_tushare/index_basic/current/part-000.parquet');
select count(*) from read_parquet('<LAKE_ROOT>/manifest/index_universe/tushare_index_basic.parquet');
```

---

## 10. 风险与回滚

| 风险 | 影响 | 防护 | 回滚 |
|---|---|---|---|
| 全量返回空 | 误覆盖 current | 空结果拒绝覆盖 | 保留旧文件 |
| market 多选未扇出 | Tushare 参数错误 | enum fanout 测试 | 修正策略后重跑 |
| 字段新增或缺失 | DuckDB 查询异常 | schema 校验 | 回滚 current |
| manifest 与 raw 不一致 | 后续指数同步使用错误指数池 | raw 与 manifest 同 run 写入并分别校验 | 保留旧 manifest |

---

## 11. Checklist

编码前：

- [ ] 已确认源站文档。
- [ ] 已确认生产 DatasetDefinition。
- [ ] 已确认展示分组。
- [ ] 已确认 current 文件布局。
- [ ] 已确认 index universe manifest 路径。
- [ ] 已确认命令示例。

编码后：

- [ ] `plan-sync index_basic` 可用。
- [ ] `sync-dataset index_basic` 可用。
- [ ] 写入使用 `_tmp -> validate -> replace`。
- [ ] 同步同时生成 raw current 和 index universe manifest。
- [ ] DuckDB 可读取。
- [ ] 列表页不默认计算 `row_count`。
- [ ] 命令示例页面可展示命令。
