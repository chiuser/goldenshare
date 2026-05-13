# Local Lake Console 数据集模型 v1

- 版本：v1
- 状态：已部分落地；已补充 `stk_mins` clean_next 基准层口径
- 更新时间：2026-05-13
- 适用范围：`lake_console` 本地移动盘 Parquet Lake
- 相关文档：
  - [Local Lake Console 架构方案 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-console-architecture-plan-v1.md)
  - [Local Lake Console 数据模型关系图 v1（HTML）](/Users/congming/github/goldenshare/docs/architecture/local-lake-console-data-model-map-v1.html)
  - [股票历史分钟行情 Parquet Lake 方案 v1](/Users/congming/github/goldenshare/docs/datasets/stk-mins-parquet-lake-plan-v1.md)

---

## 1. 目标

本文定义 `lake_console` 的数据集模型。

它解决的问题是：

1. Lake Console 需要用统一模型展示本地移动盘上的数据集。
2. 页面不能靠路径字符串自行猜测数据集、层级、分区和用途。
3. 后续讨论读写能力时，需要先有稳定的数据集对象、层级对象、分区对象和文件对象。
4. `raw_tushare`、`derived`、`research`、`manifest` 在业务语义上不同，必须在模型里明确表达。
5. 后续 `datasets / datasetDetail / storage / health / activity` 不能各自维护一套独立事实模型。

本文只定义模型，不定义写入按钮、任务执行、调度或远程同步能力。

---

## 2. 边界

本模型服务：

1. 本地移动盘 Parquet 文件事实展示。
2. 本地 DuckDB / Parquet 研究查询。
3. `stock_basic`、`stk_mins` 以及后续本地 Lake 数据集。
4. 后续页面中的数据集列表、数据集详情、分区浏览、风险提示。

本模型不服务：

1. 生产 Ops 数据状态。
2. 生产 TaskRun。
3. 远程 `goldenshare-db`。
4. 生产前端页面。
5. 自动任务调度。

---

## 3. 设计原则

1. 文件事实优先：页面展示以移动盘真实 Parquet 文件为准，manifest 只做辅助说明。
2. 层级显式：`raw_tushare`、`derived`、`research`、`manifest` 不能混成一个列表让前端猜。
3. 分区可解释：每个分区都必须说明它的分区键、覆盖范围、替换范围和推荐用途。
4. 风险结构化：空文件、临时目录残留、schema 不一致、小文件过多等风险要有统一对象。
5. 读写分离：本模型先支持读和展示；写能力后续基于该模型再设计，不在本轮混入。
6. 展示目录独立：`category` / `group_key` 等用户可见分组必须参考 Ops 默认展示目录，不得直接使用生产 `DatasetDefinition.domain` 或 Lake catalog 代码文件名。
7. 列表轻量：数据集列表默认只展示 `file_count`、`total_bytes`、日期范围、最近修改时间；`row_count` 不在列表页默认计算。
8. 页面只允许在统一核心模型上做**薄投影**，不允许为每个页面发明新的底层事实对象。

---

## 4. 当前审计结论：统一模型是否已经存在

结论先说：

**有统一核心模型，但目前只在“Lake 数据集文件事实”这条线上统一得比较明确。**

当前代码里已经稳定收敛的核心模型是：

```text
LakeDatasetDefinition
  └─ LakeLayerDefinition

LakeDatasetSummary
  └─ LakeLayerSummary[]
       └─ LakePartitionSummary[]

LakeRiskItem
LakeStatusResponse
```

这条模型链当前已经被这些代码共同使用：

1. catalog 定义层
   - [models.py](/Users/congming/github/goldenshare/lake_console/backend/app/catalog/models.py)
2. 文件系统扫描层
   - [filesystem_scanner.py](/Users/congming/github/goldenshare/lake_console/backend/app/services/filesystem_scanner.py)
3. backend schema 层
   - [lake.py](/Users/congming/github/goldenshare/lake_console/backend/app/schemas/lake.py)
4. frontend dataset / partition 消费层
   - [types.ts](/Users/congming/github/goldenshare/lake_console/frontend/src/types.ts)

所以如果只问：

```text
Datasets / DatasetDetail / Storage / 后续 Health / 后续 Activity
是不是应该共用一套数据集事实模型？
```

答案是：

**是，而且当前已经有一个应该继续共用的核心模型：`LakeDatasetSummary -> LakeLayerSummary -> LakePartitionSummary`。**

### 4.1 当前的例外域

`Recovery` 不属于上面这条数据集事实模型。

因为它的事实源不是 Lake dataset 文件本身，而是 **Kopia snapshot inventory**。

所以 `Recovery` 当前使用的是另一套对象：

1. `LakeRecoveryRepositorySummaryResponse`
2. `LakeRecoverySnapshotSummary`
3. `LakeRecoverySnapshotDetailResponse`

这不属于“页面各自发明模型”，而是**不同领域对象**：

1. `Datasets / Storage / Health / Activity`
   - 管的是 Lake 文件事实
2. `Recovery`
   - 管的是 Kopia 快照事实

### 4.2 当前真正的风险点

当前最值得警惕的不是“没有统一模型”，而是：

1. frontend 的 [types.ts](/Users/congming/github/goldenshare/lake_console/frontend/src/types.ts) 还是手写镜像，不是自动生成；
2. 旧文档里混有一部分目标态字段和 API 想象；
3. 如果后续页面开发不受约束，确实很容易开始在页面层重新拼新模型。

所以现在最应该守住的规则是：

**新页面只能在核心模型上做投影，不能再造底层事实模型。**

---

## 5. 总体模型

```text
LakeDataset
  └─ LakeLayerSummary[]
       └─ LakePartitionSummary[]
            └─ LakeFileSummary[]
```

含义：

1. `LakeDataset`：一个逻辑数据集，例如 `stock_basic`、`stk_mins`。
2. `LakeLayerSummary`：一个数据集在某个层级里的覆盖情况，例如 `stk_mins/raw_tushare`、`stk_mins/derived`、`stk_mins/research`。
3. `LakePartitionSummary`：一个可替换、可查询、可统计的物理分区。
4. `LakeFileSummary`：一个具体 Parquet 文件。

---

说明补充：

1. 当前代码里已经实际落地的是：
   - `LakeDatasetSummary`
   - `LakeLayerSummary`
   - `LakePartitionSummary`
2. `LakeFileSummary` 仍是后续可扩展方向，不是当前页面通用主对象。
3. 第一阶段新页面应优先停在 `dataset / layer / partition` 三层，不要过早扩成文件级工作台。

---

## 6. 枚举定义

### 5.1 `LakeLayer`

| 值 | 含义 | 示例 |
|---|---|---|
| `raw_tushare` | Tushare 原始接口落盘层 | `raw_tushare/stk_mins_by_date` |
| `derived` | 本地派生数据层 | `derived/stk_mins_by_date/freq=90` |
| `research` | clean 基准与研究查询优化层 | `research/stk_mins_by_date_clean_next`、`research/stk_mins_by_symbol_month` |
| `manifest` | 执行辅助清单层 | `manifest/security_universe` |

说明：

1. `raw_tushare` 是外部数据源事实。
2. `research/stk_mins_by_date_clean_next` 是从 raw 清洗后的正式分钟线基准。
3. `derived` 是我方本地计算结果，不应伪装成 Tushare 原始数据。
4. `research` 是同一批数据的查询友好物理重排，不代表新业务口径。
5. `manifest` 是执行辅助事实，不应作为主要研究查询入口，除非明确用于股票池、运行记录等辅助用途。

### 5.2 `LakeLayout`

| 值 | 含义 | 示例 |
|---|---|---|
| `current_file` | 单文件当前快照 | `raw_tushare/stock_basic/current/part-000.parquet` |
| `by_date` | 按交易日组织 | `freq=30/trade_date=2026-04-24` |
| `by_symbol_month` | 按月份与股票桶组织 | `freq=30/trade_month=2026-04/bucket=7` |
| `manifest_file` | manifest 辅助文件 | `manifest/security_universe/tushare_stock_basic.parquet` |

### 5.3 `DatasetRole`

| 值 | 含义 |
|---|---|
| `raw_dataset` | 外部数据源原始数据集 |
| `derived_dataset` | 本地派生数据集 |
| `research_dataset` | 查询优化重排数据集 |
| `universe_manifest` | 执行用股票池或证券池清单 |

### 5.4 `WritePolicy`

| 值 | 含义 |
|---|---|
| `replace_file` | 全量替换单个文件 |
| `replace_partition` | 替换单个分区 |
| `rebuild_month` | 重建某个月的 research 分区 |
| `read_only` | 只读展示，不允许写 |

### 5.5 `UpdateMode`

| 值 | 含义 |
|---|---|
| `manual_cli` | 通过 CLI 手动同步 |
| `derived_cli` | 通过 CLI 本地派生 |
| `research_rebuild` | 通过 CLI 重排 research 层 |
| `none` | 暂无写入口 |

### 5.6 `HealthStatus`

| 值 | 含义 |
|---|---|
| `ok` | 文件事实正常 |
| `warning` | 存在非阻断风险 |
| `error` | 存在阻断风险 |
| `empty` | 数据集尚未落盘 |

### 5.7 `ReplaceScope`

| 值 | 含义 |
|---|---|
| `file` | 替换单个文件 |
| `partition` | 替换单个分区 |
| `month_bucket` | 替换某月某 bucket |
| `month` | 替换某月整体 research 分区 |

---

## 7. `LakeDataset`

`LakeDataset` 是页面与 API 的核心对象。

### 6.1 字段

| 字段 | 类型 | 必填 | 含义 |
|---|---|---:|---|
| `dataset_key` | string | 是 | 数据集唯一标识，例如 `stk_mins` |
| `display_name` | string | 是 | 展示名，例如 `股票历史分钟行情` |
| `source` | string | 是 | 数据来源，例如 `tushare`、`local` |
| `category` | string | 是 | 用户可见分组名称，参考 Ops 默认展示目录，例如 `A股行情`、`资金流向` |
| `group_key` | string | 是 | 用户可见分组 key，参考 Ops 默认展示目录，例如 `equity_market` |
| `group_label` | string | 是 | 用户可见分组名称，例如 `A股行情` |
| `group_order` | integer | 是 | 用户可见分组排序 |
| `description` | string 或 null | 否 | 给用户看的简短说明 |
| `dataset_role` | `DatasetRole` | 是 | 数据集角色 |
| `storage_root` | string | 是 | 相对 Lake Root 的存储根路径 |
| `layers` | `LakeLayerSummary[]` | 是 | 已存在或可展示的层级 |
| `partition_count` | integer | 是 | 所有层级合计分区数 |
| `file_count` | integer | 是 | 所有层级合计 Parquet 文件数 |
| `total_bytes` | integer | 是 | 所有层级合计大小 |
| `row_count` | integer 或 null | 否 | 可计算时返回总行数；扫描成本高时可为空 |
| `earliest_trade_date` | string 或 null | 否 | 最早交易日，格式 `YYYY-MM-DD` |
| `latest_trade_date` | string 或 null | 否 | 最新交易日，格式 `YYYY-MM-DD` |
| `earliest_trade_month` | string 或 null | 否 | 最早交易月，格式 `YYYY-MM` |
| `latest_trade_month` | string 或 null | 否 | 最新交易月，格式 `YYYY-MM` |
| `latest_modified_at` | string 或 null | 否 | 最近文件修改时间，ISO 格式 |
| `supported_freqs` | integer[] | 否 | 可展示或可查询的全部频度 |
| `raw_freqs` | integer[] | 否 | 原始层频度，例如 `[1,5,15,30,60]` |
| `derived_freqs` | integer[] | 否 | 派生层频度，例如 `[90,120]` |
| `primary_layout` | `LakeLayout` | 是 | 主要展示布局 |
| `available_layouts` | `LakeLayout[]` | 是 | 当前可用布局 |
| `write_policy` | `WritePolicy` | 是 | 默认写策略 |
| `update_mode` | `UpdateMode` | 是 | 默认更新方式 |
| `health_status` | `HealthStatus` | 是 | 数据集健康状态 |
| `risks` | `LakeRiskItem[]` | 是 | 数据集级风险 |

### 6.1.1 行数统计口径

`row_count` 不在数据集列表页默认计算。

原因：

1. 小数据集读取 Parquet metadata 成本很低，但大数据集可能有大量分区和文件。
2. `stk_mins` 这类数据集未来可能有数万到数十万个 Parquet 文件，列表页逐个读取 metadata 会拖慢页面。
3. 移动硬盘随机 IO 能力弱于本机 SSD，频繁扫 metadata 会让“打开页面”变成重操作。

统一口径：

| 页面 / 动作 | 是否计算 `row_count` | 说明 |
|---|---:|---|
| 数据集列表页 | 否 | 默认展示 `file_count`、`total_bytes`、日期范围、最近修改时间 |
| 数据集详情页 | 是 | 用户进入详情后可计算该数据集或该层级行数 |
| 显式刷新统计 | 是 | 后续可提供“刷新行数统计”动作，但不在列表页自动触发 |

### 6.1.2 小文件风险口径

小文件过多会影响：

1. 目录扫描速度。
2. Parquet metadata 读取速度。
3. DuckDB 查询规划速度。
4. 移动硬盘随机 IO 压力。

默认建议阈值：

| 风险项 | warning | error |
|---|---:|---:|
| 单文件平均大小 | `< 8MB` | `< 1MB` |
| 单分区文件数 | `> 20` | `> 100` |
| 单数据集文件数 | `> 10000` | `> 50000` |

说明：

1. 阈值用于风险提示，不阻断读取。
2. 小型快照数据集天然文件小，例如 `stock_basic`，不应按同一阈值误报。
3. 大体量数据集如 `stk_mins`、后续 Tick 或分钟级衍生数据，应优先关注该风险。

### 6.2 示例：`stock_basic`

```json
{
  "dataset_key": "stock_basic",
  "display_name": "股票基础信息",
  "source": "tushare",
  "category": "A股基础数据",
  "group_key": "reference_data",
  "group_label": "A股基础数据",
  "group_order": 1,
  "dataset_role": "raw_dataset",
  "storage_root": "raw_tushare/stock_basic",
  "partition_count": 1,
  "file_count": 1,
  "total_bytes": 1048576,
  "primary_layout": "current_file",
  "available_layouts": ["current_file"],
  "write_policy": "replace_file",
  "update_mode": "manual_cli",
  "health_status": "ok",
  "risks": []
}
```

### 6.4 层级展示口径

`raw_tushare`、`manifest`、`derived`、`research` 都必须可见，不能因为它们是辅助层就从总览中消失。

推荐展示：

```text
stock_basic
  raw_tushare：正式研究数据
  manifest：本地同步使用的股票池

trade_cal
  raw_tushare：正式交易日历数据
  manifest：本地同步使用的交易日历

stk_mins
  raw_tushare：Tushare 原始分钟线
  derived：90/120 等本地派生分钟线
  research：面向回测和查询优化的重排布局
```

`research` 第一版作为 `stk_mins` 的子层展示，不作为独立数据集卡片展示。

原因：

1. `research` 不是新数据源事实，而是同一数据集的物理重排。
2. 用户更容易理解为“这个数据集有哪些层级”。
3. 后续如果 `derived` 或 `research` 出现多种布局，可以在详情页扩展成多层级、多布局列表。


### 6.3 示例：`stk_mins`

```json
{
  "dataset_key": "stk_mins",
  "display_name": "股票历史分钟行情",
  "source": "tushare",
  "category": "A股行情",
  "group_key": "equity_market",
  "group_label": "A股行情",
  "group_order": 2,
  "dataset_role": "raw_dataset",
  "storage_root": "raw_tushare/stk_mins_by_date",
  "supported_freqs": [1, 5, 15, 30, 60, 90, 120],
  "raw_freqs": [1, 5, 15, 30, 60],
  "derived_freqs": [90, 120],
  "primary_layout": "by_date",
  "available_layouts": ["by_date", "by_symbol_month"],
  "write_policy": "replace_partition",
  "update_mode": "manual_cli",
  "health_status": "ok",
  "risks": []
}
```

---

## 8. `LakeLayerSummary`

`LakeLayerSummary` 描述一个数据集在某个层级内的文件事实。

### 7.1 字段

| 字段 | 类型 | 必填 | 含义 |
|---|---|---:|---|
| `layer` | `LakeLayer` | 是 | 层级 |
| `layer_name` | string | 是 | 层级展示名 |
| `purpose` | string | 是 | 层级用途 |
| `source_layer` | `LakeLayer` 或 null | 否 | 数据来源层 |
| `layout` | `LakeLayout` | 是 | 该层主要布局 |
| `path` | string | 是 | 相对 Lake Root 的路径 |
| `partition_count` | integer | 是 | 分区数 |
| `file_count` | integer | 是 | 文件数 |
| `total_bytes` | integer | 是 | 总大小 |
| `row_count` | integer 或 null | 否 | 总行数，可为空 |
| `freqs` | integer[] | 否 | 该层覆盖的频度 |
| `earliest_trade_date` | string 或 null | 否 | 最早交易日 |
| `latest_trade_date` | string 或 null | 否 | 最新交易日 |
| `earliest_trade_month` | string 或 null | 否 | 最早交易月 |
| `latest_trade_month` | string 或 null | 否 | 最新交易月 |
| `latest_modified_at` | string 或 null | 否 | 最近修改时间 |
| `recommended_usage` | string | 是 | 推荐使用场景 |
| `risks` | `LakeRiskItem[]` | 是 | 层级风险 |

### 7.2 层级用途约定

| 层级 | 推荐用途 |
|---|---|
| `raw_tushare` | 原始接口落盘，适合单日全市场横截面查询和补数 |
| `derived` | 本地派生周期，例如 90/120 分钟线 |
| `research` | 单股长周期回测、少数股票多月对比、相似性分析 |
| `manifest` | 执行辅助清单，例如股票池 |

---

## 9. `LakePartitionSummary`

`LakePartitionSummary` 描述一个具体分区。

### 8.1 字段

| 字段 | 类型 | 必填 | 含义 |
|---|---|---:|---|
| `dataset_key` | string | 是 | 数据集 key |
| `layer` | `LakeLayer` | 是 | 所属层 |
| `layout` | `LakeLayout` | 是 | 分区布局 |
| `freq` | integer 或 null | 否 | 分钟频度 |
| `trade_date` | string 或 null | 否 | 交易日，格式 `YYYY-MM-DD` |
| `trade_month` | string 或 null | 否 | 交易月，格式 `YYYY-MM` |
| `bucket` | integer 或 null | 否 | research 层股票 hash bucket |
| `partition_key` | string | 是 | 可读分区键，例如 `freq=30/trade_date=2026-04-24` |
| `path` | string | 是 | 相对或绝对路径 |
| `file_count` | integer | 是 | 文件数 |
| `total_bytes` | integer | 是 | 总大小 |
| `row_count` | integer 或 null | 否 | 行数 |
| `modified_at` | string 或 null | 否 | 最近修改时间 |
| `replace_scope` | `ReplaceScope` | 是 | 替换范围 |
| `can_replace_safely` | boolean | 是 | 是否可安全替换 |
| `risks` | `LakeRiskItem[]` | 是 | 分区风险 |

### 8.2 示例：by date 分区

```json
{
  "dataset_key": "stk_mins",
  "layer": "raw_tushare",
  "layout": "by_date",
  "freq": 30,
  "trade_date": "2026-04-24",
  "partition_key": "freq=30/trade_date=2026-04-24",
  "path": "raw_tushare/stk_mins_by_date/freq=30/trade_date=2026-04-24",
  "file_count": 3,
  "total_bytes": 268435456,
  "replace_scope": "partition",
  "can_replace_safely": true,
  "risks": []
}
```

### 8.3 示例：research 分区

```json
{
  "dataset_key": "stk_mins",
  "layer": "research",
  "layout": "by_symbol_month",
  "freq": 30,
  "trade_month": "2026-04",
  "bucket": 7,
  "partition_key": "freq=30/trade_month=2026-04/bucket=7",
  "path": "research/stk_mins_by_symbol_month/freq=30/trade_month=2026-04/bucket=7",
  "file_count": 1,
  "total_bytes": 134217728,
  "replace_scope": "month_bucket",
  "can_replace_safely": true,
  "risks": []
}
```

---

## 10. `LakeFileSummary`

`LakeFileSummary` 描述一个具体 Parquet 文件。

### 9.1 字段

| 字段 | 类型 | 必填 | 含义 |
|---|---|---:|---|
| `path` | string | 是 | 文件绝对路径或相对路径 |
| `relative_path` | string | 是 | 相对 Lake Root 的路径 |
| `file_name` | string | 是 | 文件名 |
| `size_bytes` | integer | 是 | 文件大小 |
| `row_count` | integer 或 null | 否 | Parquet 行数 |
| `modified_at` | string 或 null | 否 | 最近修改时间 |
| `parquet_schema_hash` | string 或 null | 否 | schema hash，用于检测同分区 schema 漂移 |
| `parquet_schema` | `ParquetField[]` | 否 | schema 字段 |
| `risks` | `LakeRiskItem[]` | 是 | 文件风险 |

### 9.2 `ParquetField`

| 字段 | 类型 | 必填 | 含义 |
|---|---|---:|---|
| `name` | string | 是 | 字段名 |
| `physical_type` | string | 是 | Parquet 物理类型 |
| `logical_type` | string 或 null | 否 | Parquet 逻辑类型 |
| `nullable` | boolean 或 null | 否 | 是否可空 |

---

## 11. `LakeRiskItem`

`LakeRiskItem` 用于表示文件事实风险。

### 10.1 字段

| 字段 | 类型 | 必填 | 含义 |
|---|---|---:|---|
| `severity` | string | 是 | `info/warning/error` |
| `code` | string | 是 | 风险码 |
| `message` | string | 是 | 用户可读说明 |
| `path` | string 或 null | 否 | 相关路径 |
| `suggested_action` | string 或 null | 否 | 建议动作 |

### 10.2 风险码建议

| 风险码 | 含义 |
|---|---|
| `empty_file` | 空 Parquet 文件 |
| `tmp_residue` | `_tmp` 目录存在历史残留 |
| `schema_mismatch` | 同一数据集或同一分区 schema 不一致 |
| `missing_manifest` | 辅助 manifest 缺失 |
| `orphan_manifest` | manifest 指向的文件不存在 |
| `small_file_excess` | 小文件过多 |
| `partition_without_files` | 分区目录存在但无 Parquet 文件 |
| `unknown_layout` | 目录布局不符合已知 LakeLayout |

---

## 12. 当前已知数据集建模

### 11.1 `stock_basic`

| 项 | 值 |
|---|---|
| `dataset_key` | `stock_basic` |
| `display_name` | 股票基础信息 |
| `source` | `tushare` |
| `category` | A股基础数据 |
| `group_key` | `reference_data` |
| `group_label` | A股基础数据 |
| `group_order` | 1 |
| `dataset_role` | `raw_dataset` |
| `primary_layout` | `current_file` |
| `storage_root` | `raw_tushare/stock_basic` |
| `write_policy` | `replace_file` |
| `update_mode` | `manual_cli` |

说明：

1. `raw_tushare/stock_basic/current/part-000.parquet` 是正式维表。
2. 它可用于研究查询中的股票名称、行业、上市状态等 join。
3. 它不等同于执行股票池 manifest。

### 11.2 `stock_basic` 执行股票池

| 项 | 值 |
|---|---|
| `dataset_key` | `stock_basic_universe` |
| `display_name` | Tushare 股票池清单 |
| `source` | `tushare` |
| `category` | A股基础数据 |
| `group_key` | `reference_data` |
| `group_label` | A股基础数据 |
| `group_order` | 1 |
| `dataset_role` | `universe_manifest` |
| `primary_layout` | `manifest_file` |
| `storage_root` | `manifest/security_universe` |
| `write_policy` | `replace_file` |
| `update_mode` | `manual_cli` |

说明：

1. `manifest/security_universe/tushare_stock_basic.parquet` 服务 `stk_mins --all-market` 扇出。
2. 页面可以展示它，但不应把它当成研究查询主入口。

### 11.3 `trade_cal`

| 项 | 值 |
|---|---|
| `dataset_key` | `trade_cal` |
| `display_name` | 交易日历 |
| `source` | `tushare` |
| `category` | A股基础数据 |
| `group_key` | `reference_data` |
| `group_label` | A股基础数据 |
| `group_order` | 1 |
| `dataset_role` | `raw_dataset` |
| `primary_layout` | `current_file` |
| `storage_root` | `raw_tushare/trade_cal` |

说明：

1. `raw_tushare/trade_cal/current/part-000.parquet` 是正式交易日历维表。
2. `manifest/trading_calendar/tushare_trade_cal.parquet` 是区间分钟线同步的执行日历。
3. 区间分钟线同步只能读取本地交易日历，不允许访问远程数据库。
4. `sync-trade-cal` 支持两种刷新模式：
   - 不传 `start_date/end_date`：按单交易所全量分页拉取，并全量替换 current + manifest。
   - 同时传 `start_date/end_date`：按显式区间分页拉取，再全量替换 current + manifest。

### 11.4 `stk_mins`

| 项 | 值 |
|---|---|
| `dataset_key` | `stk_mins` |
| `display_name` | 股票历史分钟行情 |
| `source` | `tushare` |
| `category` | A股行情 |
| `group_key` | `equity_market` |
| `group_label` | A股行情 |
| `group_order` | 2 |
| `dataset_role` | `raw_dataset` |
| `primary_layout` | `by_date` |
| `storage_root` | `raw_tushare/stk_mins_by_date` |
| `write_policy` | `replace_partition` |
| `update_mode` | `manual_cli` |
| `raw_freqs` | `[1,5,15,30,60]` |
| `derived_freqs` | `[90,120]` |
| `available_layouts` | `[by_date, clean_next_by_date, by_symbol_month]` |

层级：

| 层级 | 布局 | 用途 |
|---|---|---|
| `raw_tushare` | `by_date` | Tushare 原始分钟线，适合单日全市场查询 |
| `derived` | `by_date` | 90/120 分钟线派生结果 |
| `research` | `by_symbol_month` | 单股长周期回测和少数股票相似性分析 |

---

## 13. 页面与 API 的统一约束

后续页面开发时，必须先判断自己属于哪个领域对象，再决定可用模型。

### 13.1 Lake 文件事实页

以下页面必须共用这条核心模型：

1. `datasets`
2. `datasetDetail`
3. `storage`
4. `health`
5. `activity`

允许使用的核心对象：

1. `LakeStatusResponse`
2. `LakeDatasetSummary`
3. `LakeLayerSummary`
4. `LakePartitionSummary`
5. `LakeRiskItem`

允许做的只是：

1. 增加筛选字段
2. 增加排序字段
3. 把已有对象组合成页面 view model

不允许：

1. 页面自己重新定义“dataset footprint”底层事实
2. 页面自己发明第二套 layer 结构
3. 页面靠路径字符串重新猜 dataset / layer / layout

### 13.2 Recovery 页

`Recovery` 是例外域。

它必须使用：

1. `LakeRecoveryRepositorySummaryResponse`
2. `LakeRecoverySnapshotSummary`
3. `LakeRecoverySnapshotDetailResponse`

不能硬套 `LakeDatasetSummary`。

原因：

1. `Recovery` 的事实源是 Kopia snapshot，不是 Lake dataset 扫描结果；
2. snapshot 可以覆盖 whole_lake，也可以覆盖某个子路径，它不是一个标准 dataset summary。

### 13.3 前端类型规则

frontend 当前的 [types.ts](/Users/congming/github/goldenshare/lake_console/frontend/src/types.ts) 只是 backend schema 的镜像层。

统一要求：

1. `DatasetSummary / LayerSummary / PartitionSummary` 必须继续对齐 backend 的：
   - `LakeDatasetSummary`
   - `LakeLayerSummary`
   - `LakePartitionSummary`
2. 前端可以做展示 view model，但不能把镜像类型改成独立事实口径。

### 13.4 Storage 页的直接约束

`Storage / Cost` 第一阶段必须直接复用：

1. `LakeStatusResponse`
2. `LakeDatasetSummary`
3. `LakeLayerSummary`

它可以在 API 层加：

1. summary 聚合
2. 排序
3. 分页

但不允许再定义一套新的“StorageDatasetFact”作为底层主对象。

---

## 14. 已确认口径

1. `manifest` 层必须展示。它可以作为数据集辅助层展示，也可以在 Lake 层级总览中统计，但不能从页面隐藏。
2. 数据集列表页默认不计算 `row_count`，只展示 `file_count`、`total_bytes`、日期范围和最近修改时间。
3. `row_count` 在详情页或显式刷新时计算。
4. `research` 第一版作为 `stk_mins` 子层展示，不作为独立数据集卡片展示。
5. 写入页面入口暂缓；第一版先做“命令示例 / 操作提示”页面，不触发写入。
6. `Storage / Health / Activity` 后续都必须站在 `LakeDatasetSummary -> LakeLayerSummary -> LakePartitionSummary` 这条统一模型上扩展。
7. `Recovery` 使用单独的 Kopia snapshot 领域模型，不属于“页面各自乱造模型”。
