# Local Lake Storage / Cost 最小 API 设计 v1

- 版本：v1
- 状态：历史/冻结（旧 `lake_console/backend` 文档；原阶段状态仅代表文档记录时点）
- 更新时间：2026-05-12
- 适用范围：`lake_console/backend` 第一期 `Storage / Cost` 页面只读 API
- 关联文档：
  - [Local Lake 管理台升级路线图 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-console-management-roadmap-v1.md)
  - [Local Lake 页面演进边界卡 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-console-page-evolution-boundary-card-v1.md)
  - [Local Lake Console 数据集模型 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-console-dataset-model-v1.md)
  - [Local Lake Storage / Cost 页面边界卡 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-storage-cost-page-boundary-card-v1.md)

> **当前边界声明**：本文保留旧 Local Lake Console Storage / Cost API 证据。文中的旧 Lake Root、Kopia、`raw_tushare`、`derived`、`research`、`manifest` 等口径不得作为当前 Dagster Lake 或新开发、迁移、历史补录、bootstrap、修复、写湖任务的依据。当前正式 Lake 路径和安全规则以根目录 `AGENTS.md` 与 `lake_console/orchestrator/src/orchestrator/defs/paths.py` 为准；禁止新增或调用 Kopia。

---

## 1. 目标

本方案只定义 `Storage / Cost` 页面第一期**最小只读 API**。

本批只解决：

1. 页面能拿到 Lake 总磁盘空间摘要；
2. 页面能拿到 dataset 级占用列表；
3. 页面能拿到单个 dataset 的 layer footprint 详情；
4. 页面不需要自行拼装空间统计事实。

本批明确不解决：

1. 清理执行
2. retention policy 编辑
3. 分区级 deep drilldown
4. 增长趋势时间序列
5. Kopia repository 占用分析

---

## 2. 代码审计依据

这份 API 设计不是按想象写的，直接建立在当前代码事实上。

### 2.1 现有 API

当前已有：

1. [lake_status.py](/Users/congming/github/goldenshare/lake_console/backend/app/api/lake_status.py)
   - `GET /api/lake/status`
2. [datasets.py](/Users/congming/github/goldenshare/lake_console/backend/app/api/datasets.py)
   - `GET /api/datasets`

### 2.2 现有底层事实

[filesystem_scanner.py](/Users/congming/github/goldenshare/lake_console/backend/app/services/filesystem_scanner.py) 现在已经能产出：

1. dataset 级：
   - `partition_count`
   - `file_count`
   - `total_bytes`
   - `latest_modified_at`
   - `layer_summaries`
2. layer 级：
   - `partition_count`
   - `file_count`
   - `total_bytes`
   - `path`
   - `layout`
   - `latest_modified_at`
3. lake 根目录级：
   - 总容量
   - 已用
   - 可用
   - 使用率
   见 [lake.py](/Users/congming/github/goldenshare/lake_console/backend/app/schemas/lake.py) 中的：
   - `LakeStatusResponse`
   - `LakeDatasetSummary`
   - `LakeLayerSummary`

### 2.3 设计含义

因此，`Storage / Cost` 第一期不应该新发明一套扫描器。

正确做法是：

1. 复用 `LakeRootService`
2. 复用 `FilesystemScanner.list_datasets()`
3. 在 API 层做轻量聚合、过滤、排序、分页

---

## 3. 设计原则

### 3.1 只读

第一期只读，不做任何会修改 Lake 文件结构的动作。

### 3.2 后端负责聚合

前端不负责：

1. 自己求总 bytes
2. 自己排序大 dataset
3. 自己推 dominant layer
4. 自己把 layer_summaries 压平成主表所需字段

### 3.3 dataset 优先，layer 细节后置

第一页的主对象是：

```text
dataset
```

不是：

```text
partition
```

layer 细节进入单 dataset 详情接口即可。

---

## 4. 第一期 API 范围

只包含 3 个接口：

```text
GET /api/storage/summary
GET /api/storage/datasets
GET /api/storage/datasets/{dataset_key}
```

本批不包含：

```text
GET /api/storage/partitions
POST /api/storage/cleanup
POST /api/storage/repack
POST /api/storage/retention
```

---

## 5. 路由与返回模型

建议新增：

- `lake_console/backend/app/api/storage.py`

建议新增 schema：

1. `LakeStorageSummaryResponse`
2. `LakeStorageLayerAggregate`
3. `LakeStorageDatasetListResponse`
4. `LakeStorageDatasetDetailResponse`

其中：

1. dataset 明细主体可直接复用 `LakeDatasetSummary`
2. layer 明细主体可直接复用 `LakeLayerSummary`

也就是说，第一期不需要再造第二套 dataset/layer 事实模型。

---

## 6. `GET /api/storage/summary`

### 6.1 作用

供页面顶部 summary 使用。

### 6.2 数据来源

1. `LakeRootService.get_status()`
2. `FilesystemScanner.list_datasets()`

### 6.3 返回字段

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `lake_root` | `str` | 当前 Lake 根路径 |
| `disk_total_bytes` | `int \| null` | 磁盘总容量 |
| `disk_used_bytes` | `int \| null` | 磁盘已用 |
| `disk_free_bytes` | `int \| null` | 磁盘可用 |
| `disk_usage_percent` | `float \| null` | 磁盘使用率 |
| `dataset_count` | `int` | 数据集总数 |
| `non_empty_dataset_count` | `int` | 非空数据集数 |
| `total_bytes` | `int` | Lake 已扫描到的数据总字节数 |
| `total_file_count` | `int` | 总文件数 |
| `total_partition_count` | `int` | 总分区数 |
| `layer_aggregates` | `list[LakeStorageLayerAggregate]` | 按 layer 聚合的空间摘要 |

### 6.4 `LakeStorageLayerAggregate`

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `layer` | `str` | `raw_tushare / manifest / derived / research / indicators` |
| `dataset_count` | `int` | 覆盖的数据集数 |
| `total_bytes` | `int` | 总字节数 |
| `file_count` | `int` | 总文件数 |
| `partition_count` | `int` | 总分区数 |

---

## 7. `GET /api/storage/datasets`

### 7.1 作用

供主表格使用。

### 7.2 查询参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `query` | `str` | 否 | 匹配 `dataset_key / display_name / group_label` |
| `group_key` | `str` | 否 | 按视图组过滤 |
| `layer` | `str` | 否 | 仅保留包含某 layer 的 dataset |
| `include_empty` | `bool` | 否 | 是否包含 `total_bytes = 0` 的 dataset，默认 `false` |
| `sort_by` | `str` | 否 | `total_bytes / file_count / partition_count / latest_modified_at`，默认 `total_bytes` |
| `sort_order` | `str` | 否 | `asc / desc`，默认 `desc` |
| `limit` | `int` | 否 | 默认 `100`，最大 `500` |
| `offset` | `int` | 否 | 默认 `0` |

### 7.3 返回字段

建议：

```text
items: list[LakeDatasetSummary]
total: int
limit: int
offset: int
```

原因：

1. 当前 `LakeDatasetSummary` 已经覆盖 Storage 页主表和抽屉第一期所需的大部分事实；
2. 第一批不必再发明一套“Storage 专用 dataset 模型”；
3. 只需要在 list 响应外层增加分页壳。

### 7.4 后端排序规则

建议由 backend 统一处理，前端不自行排序。

排序键映射：

1. `total_bytes`
2. `file_count`
3. `partition_count`
4. `latest_modified_at`

---

## 8. `GET /api/storage/datasets/{dataset_key}`

### 8.1 作用

供右侧详情抽屉使用。

### 8.2 返回字段

第一期可直接返回：

```text
LakeDatasetSummary
```

因为其中已经包含：

1. `layer_summaries`
2. `total_bytes`
3. `file_count`
4. `partition_count`
5. `latest_modified_at`
6. `available_layouts`
7. `storage_root`
8. `health_status`
9. `risks`

### 8.3 为什么第一期不再拆更细接口

因为 Storage 页第一期抽屉只需要看：

1. 这个 dataset 总体多大
2. 各 layer 怎么分
3. 路径在哪
4. 最近何时变动

还不需要：

1. 分区级列表
2. 文件级列表
3. 历史增长曲线

---

## 9. 归一化规则

后端应统一完成：

1. `include_empty` 过滤
2. `group_key / layer / query` 过滤
3. dataset 排序
4. summary 的全局聚合
5. layer aggregate 的归并

前端不应：

1. 自己把 `/api/datasets` 全量拉回来再求总
2. 自己按 layer 重新折叠
3. 自己推“哪个 layer 最重”

---

## 10. 第一期实现边界

允许：

1. 在现有 scanner 结果上做轻量聚合
2. 在 API 层补分页、排序、过滤
3. 在 schema 层新增 Storage summary/list response

不允许：

1. 为了 Storage 页重写 scanner
2. 直接引入 partition 深度扫描接口
3. 把 growth trend、cleanup、retention 一起做掉

---

## 11. 验收口径

本 API 设计对应的一期实现完成后，应满足：

1. 页面能拿到 Lake 总空间摘要；
2. 页面能按 dataset 体量排序；
3. 页面能按 layer / group 过滤；
4. 页面能打开单 dataset 抽屉看 layer footprint；
5. 前端不需要自行聚合空间事实。
