# Local Lake Storage / Cost 页面边界卡 v1

- 版本：v1
- 状态：历史/冻结（旧 `lake_console/backend` 文档；原阶段状态仅代表文档记录时点）
- 更新时间：2026-05-12
- 适用范围：`lake_console/frontend`
- 关联文档：
  - [Local Lake 管理台升级路线图 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-console-management-roadmap-v1.md)
  - [Local Lake 页面演进边界卡 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-console-page-evolution-boundary-card-v1.md)
  - [Local Lake Console 数据集模型 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-console-dataset-model-v1.md)
  - [Local Lake Storage / Cost 最小 API 设计 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-storage-cost-api-minimal-design-v1.md)

> **当前边界声明**：本文保留旧 Local Lake Console Storage / Cost 页面边界证据。文中的旧 Lake Root、Kopia、`raw_tushare`、`derived`、`research`、`manifest` 等口径不得作为当前 Dagster Lake 或新开发、迁移、历史补录、bootstrap、修复、写湖任务的依据。当前正式 Lake 路径和安全规则以根目录 `AGENTS.md` 与 `lake_console/orchestrator/src/orchestrator/defs/paths.py` 为准；禁止新增或调用 Kopia。

---

## 1. 目标

本边界卡只回答 3 件事：

1. `Storage / Cost` 页面要解决什么管理问题。
2. 它和现有 `datasets / recovery / risks` 的边界怎么切。
3. 第一期允许做到哪里，不允许顺手扩成什么。

本卡不展开具体视觉样式，不展开实现细节，不进入编码。

---

## 2. 设计依据

这页不是凭空发明出来的，而是直接建立在当前 backend 已有事实之上。

当前代码已经能提供：

1. Lake 根目录磁盘占用
   - 见 [lake_status.py](/Users/congming/github/goldenshare/lake_console/backend/app/api/lake_status.py)
2. 数据集级别的：
   - `total_bytes`
   - `file_count`
   - `partition_count`
   - `latest_modified_at`
   - `layer_summaries`
   - 见 [filesystem_scanner.py](/Users/congming/github/goldenshare/lake_console/backend/app/services/filesystem_scanner.py)
3. layer 级别的：
   - `raw_tushare / manifest / derived / research / indicators`
   占用与文件规模

所以 `Storage / Cost` 页第一期的边界应该是：

```text
把已有空间事实看清楚
而不是新增另一套扫描引擎
```

---

## 3. 页面定位

`Storage / Cost` 是 Lake 的**空间与占用治理页**。

它主要回答：

1. Lake 总空间用了多少。
2. 哪些 dataset 最大。
3. 哪些 layer 最重。
4. 哪些 dataset 文件最多、分区最多。
5. 哪些对象值得后续进入清理、压缩、重排或保留策略讨论。

它不负责回答：

1. 数据是否完整
2. 哪次恢复能不能回滚
3. 哪次同步最近失败
4. schema 是否漂移

这些问题分别属于：

1. `Health`
2. `Recovery`
3. `Activity`
4. `Schema / Contract`

---

## 4. 与现有页面的边界

### 4.1 `datasets`

`datasets` 保留为总览页。

`Storage` 不替代 `datasets`，而是把“容量/文件/分区/层级占用”单独拉平。

边界：

1. `datasets` 负责看全局目录与健康概况。
2. `Storage` 负责看空间结构与体量排序。

### 4.2 `recovery`

`Recovery` 看的是 Kopia snapshot、pin、restore 命令。

`Storage` 不展示：

1. snapshot inventory
2. restore command
3. repository 连接状态

除非后续要单独补“备份体量占用”，第一期也不把 Kopia repository 当作本页主对象。

### 4.3 `risks`

`risks` 继续保留为基础风险总览。

`Storage` 不接管通用风险页，只承接：

1. 体量过大
2. 文件数异常高
3. 某 layer 占用异常偏重

这类空间治理视角的问题。

### 4.4 `datasetDetail`

第一期不恢复重型独立详情页。

`Storage` 的详情交互统一走：

1. 右侧抽屉
2. 侧栏密集元信息

不新开第二套“大详情页”。

---

## 5. 第一期页面边界

### 5.1 页面必须有

第一期只做 3 块：

1. 顶部紧凑 summary
2. 主表：dataset storage inventory
3. 右侧详情抽屉

### 5.2 顶部 summary 回答什么

顶部 summary 只回答最值钱的几个数：

1. Lake 总容量 / 已用 / 可用
2. 当前 dataset 数
3. 当前文件总数
4. 当前分区总数
5. 按 layer 聚合的总占用

不做大卡片墙，不做长解释。

### 5.3 主表回答什么

主表只按 dataset 展开，回答：

1. 哪个 dataset 最大
2. 哪个 dataset 文件最多
3. 哪个 dataset 分区最多
4. 哪个 dataset 最近被改动
5. 它主要重在哪一层

### 5.4 详情抽屉回答什么

详情抽屉第一期只看 dataset footprint 细节：

1. 各 layer 占用
2. 各 layer 文件数 / 分区数
3. 各 layer 最新修改时间
4. 各 layer path
5. 哪一层是主占用层

不在这里展开：

1. 分区级全量表格
2. 恢复记录
3. 完整性统计
4. schema 详情

---

## 6. 第一期允许的筛选与排序

允许：

1. `query`
2. `group_key`
3. `layer`
4. `include_empty`
5. `sort_by`
   - `total_bytes`
   - `file_count`
   - `partition_count`
   - `latest_modified_at`
6. `sort_order`

不做：

1. 时间轴趋势图
2. 多维 pivot
3. 复杂保存视图
4. 自定义列配置

---

## 7. 交互约束

仍然遵守统一口径：

```text
高密度
低噪声
少废话文案
表格优先
抽屉 / 侧栏承载详情
```

落到这页上就是：

1. 主表优先可扫描，不优先解释概念。
2. 长路径不在主表平铺。
3. layer 明细进抽屉，不在主表堆栈成小作文。
4. 主表列数保持克制，避免把“dataset、layer、path、count、growth、risk”全塞一张表。

---

## 8. 第一期明确不做

第一期不做：

1. 清理动作执行
2. 压缩 / 重排动作执行
3. retention policy 编辑
4. partition 级 deep drilldown
5. 增长趋势曲线
6. Kopia repository 占用管理
7. 任何 destructive 按钮

这页是：

```text
看清空间结构
不是直接改空间结构
```

---

## 9. 第一期导航建议

进入 `Storage` 后，一级导航建议更新为：

```text
Datasets
Recovery
Storage
Commands
Risks
```

说明：

1. `Storage` 作为第二批新增一级入口。
2. `Health / Activity` 仍然后置。

---

## 10. 验收口径

本边界卡对应的一期页面完成后，应满足：

1. 能看清 Lake 总空间与已用空间。
2. 能按 dataset 排序看体量、文件数、分区数。
3. 能按 layer 粗看占用结构。
4. 能从主表进入单 dataset 的 footprint 抽屉。
5. 没有把 `Health / Recovery / Activity` 的职责偷偷混进来。
