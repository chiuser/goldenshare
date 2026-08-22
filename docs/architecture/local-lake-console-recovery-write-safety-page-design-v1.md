# Local Lake Recovery / Write Safety 页面交互设计 v1

- 版本：v1
- 状态：历史/冻结（旧 `lake_console/backend` 文档；原阶段状态仅代表文档记录时点）
- 更新时间：2026-05-11
- 适用范围：`lake_console/frontend` 第一期新增页面
- 关联文档：
  - [Local Lake 管理台升级路线图 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-console-management-roadmap-v1.md)
  - [Local Lake 页面演进边界卡 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-console-page-evolution-boundary-card-v1.md)
  - [Local Lake Kopia 集成恢复管理方案 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-write-recovery-management-plan-v1.md)

> **当前边界声明**：本文保留旧 Local Lake Console Recovery / Write Safety 页面证据。文中的 Kopia、旧 Lake Root 和旧恢复链路不得作为当前 Dagster Lake 或新开发、迁移、历史补录、bootstrap、修复、写湖依据。当前正式 Lake 路径和安全规则以根目录 `AGENTS.md` 与 `lake_console/orchestrator/src/orchestrator/defs/paths.py` 为准；禁止新增或调用 Kopia。

---

## 1. 页面目标

页面只回答 4 件事：

1. 当前 Kopia repository 是否正常连接。
2. 当前 Lake 有没有 baseline snapshot。
3. 某个数据集或路径有哪些 snapshots、哪些已 pin。
4. 针对选中快照，下一步 restore 命令是什么。

页面不负责：

1. 自己执行 restore。
2. 自己执行 pin / unpin。
3. 自己解释底层备份原理。
4. 管理自研 recovery 主账本。

第一期页面定位：

```text
Kopia Snapshot Manager / Restore Assistant
```

---

## 2. 设计原则

### 2.1 视觉原则

1. 高密度
2. 低噪声
3. 少废话文案
4. 表格优先
5. 抽屉 / 侧栏承载详情

### 2.2 信息表达原则

1. 主界面优先展示 snapshot、pin、path、size、time、scope。
2. 说明性内容压到最少。
3. 不在主界面堆长文案。
4. 一屏优先回答：
   - baseline 在不在
   - 哪些快照已 pin
   - 哪些路径有保护
   - 该执行哪条恢复命令

### 2.3 风格参考

设计参考：

- [frontend-design-tokens-and-component-catalog-v1.md](/Users/congming/github/goldenshare/docs/frontend/frontend-design-tokens-and-component-catalog-v1.md)
- [frontend-component-showcase-v1.html](/Users/congming/github/goldenshare/docs/frontend/frontend-component-showcase-v1.html)

采用方向：

1. 紧凑工具栏
2. 中性底色 + 白色 surface
3. 轻量 badge
4. Dense table
5. 右侧详情抽屉

---

## 3. 页面信息架构

```text
PageHeader
Metric row
Dense filter toolbar
Snapshot table
Right-side detail drawer
```

---

## 4. 页面顶部

### 4.1 Header

标题：

```text
Recovery / Write Safety
```

副标题只保留一句：

```text
查看 Kopia 快照、pin 与恢复命令。
```

---

## 5. 指标条

一行 4 个紧凑指标卡：

1. `Repository`
   - `Connected / Disconnected`
2. `Snapshots`
   - 当前列表总数
3. `Pinned`
   - 已 pin 数量
4. `Latest Baseline`
   - 最近 baseline 时间或 `—`

规则：

1. 高度紧凑；
2. 数值优先；
3. 不写大段 hint。

---

## 6. 筛选条

使用 `DenseToolbar` 风格。

筛选项建议：

1. `scope`
   - `whole_lake / manifest / raw / derived / research / indicators`
2. `dataset`
3. `pinned`
4. `baseline_only`
5. `query`
6. `time range`

说明：

- `query`
  - 匹配 `snapshot_id / path / description / pin name`

工具栏右侧按钮：

1. `仅看已 pin`
2. `仅看 baseline`
3. `刷新`

第一期不放：

1. `导出 JSONL`
2. `恢复执行`
3. `清理`

---

## 7. 主表格

主表格是页面中心。

### 7.1 表格列

主表格应控制在 **6 列以内**，避免为了“信息全”把单行挤坏。

当前建议列如下：

| 列 | 含义 |
|---|---|
| 时间 | snapshot 时间与基础类型 |
| 对象 | dataset / whole_lake 主标签，附横向 badge：`scope / baseline / pin` |
| Snapshot | description 主标题 + 短 id |
| 大小 | total size + 文件/目录压缩统计 |
| Retention | retention 摘要 |
| 操作 | `详情` |

说明：

1. `scope` 不再单独占列。
2. 长路径不在主表展示，退回右侧详情抽屉。
3. pin 名全量不在主表平铺，只保留 pin 数或摘要。
4. description 允许单行省略；完整内容交给详情抽屉。

### 7.2 表格交互规则

1. 单击行：高亮。
2. 点击 `详情`：打开右侧抽屉。
3. 不在表格中直接放 destructive 按钮。
4. `Baseline`、`scope`、`pin` 用横向 badge 表达，不做纵向堆叠。
5. 主表应优先保证单行稳定，不为展示全量路径牺牲版式。

---

## 8. 右侧详情抽屉

建议宽度：

```text
640px ~ 760px
```

抽屉结构分 4 段。

### 8.1 概览段

展示：

1. `snapshot_id`
2. `description`
3. `scope`
4. `source_path`
5. `baseline badge`
6. `pins`

### 8.2 统计段

展示：

1. `total_size`
2. `file_count`
3. `dir_count`
4. `start_time`
5. `end_time`

### 8.3 Retention / Pin 段

展示：

1. `pins`
2. `retention_reasons`
3. `是否 whole lake baseline`

### 8.4 Restore Command 段

展示：

1. 恢复整目录到临时路径的建议命令；
2. 如果当前对象是子路径，则显示子路径 restore 命令；
3. 如有 pin，则显示对应 unpin 命令预览。

规则：

1. 只做 command preview；
2. 提供 copy 按钮；
3. 不做 apply 按钮。

---

## 9. 空状态与异常状态

### 9.1 无 repository

显示：

```text
Kopia repository 未连接
```

并给出最短提示：

```text
先连接 repository，再查看快照。
```

### 9.2 无 snapshot

显示：

```text
当前没有可展示的 Kopia 快照
```

### 9.3 API 失败

显示简短错误块，不写长解释。

---

## 10. 第一期明确不做

1. restore apply
2. pin / unpin 执行
3. cleanup 执行
4. 自研 recovery 账本浏览
5. `_recovery/**` 历史目录补录展示

---

## 11. 第一批验收标准

页面完成后，应满足：

1. 能看到 repository 状态；
2. 能看到全湖 baseline；
3. 能看到已 pin snapshots；
4. 能按 dataset/path 筛选；
5. 能在详情抽屉看到 restore 命令；
6. 页面风格保持高密度、低噪声、少废话文案。
