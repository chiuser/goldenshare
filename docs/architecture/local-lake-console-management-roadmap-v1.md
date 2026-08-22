# Local Lake 管理台升级路线图 v1

- 版本：v1
- 状态：历史/冻结（旧 `lake_console/backend` 文档；原阶段状态仅代表文档记录时点）
- 更新时间：2026-05-11
- 适用范围：`lake_console/backend` 与 `lake_console/frontend`

> **当前边界声明**：本文保留旧 Local Lake Console 路线图证据。文中的旧 Lake Root、Kopia、`raw_tushare`、`derived`、`research`、`manifest` 等口径不得作为当前 Dagster Lake 或新开发、迁移、历史补录、bootstrap、修复、写湖任务的依据。当前正式 Lake 路径和安全规则以根目录 `AGENTS.md` 与 `lake_console/orchestrator/src/orchestrator/defs/paths.py` 为准；禁止新增或调用 Kopia。

---

## 1. 背景

`lake_console` 当前已经不再是“空盘 + 少量实验数据”的阶段。

当前现实是：

1. Lake 数据量已达到大体量，目录、分区、派生层、research 层和恢复资产都在增长。
2. 当前前端主要能力仍偏“文件浏览器 + 风险页”。
3. 近期 `stk_mins` P0 事故进一步证明：Lake 管理台不仅要能看文件，还要能管理恢复、追踪写入、判断健康和理解空间结构。

因此，管理台下一阶段目标不再只是：

```text
展示有哪些数据集
```

而应升级为：

```text
看得清
查得快
恢复有抓手
空间有认知
健康有依据
操作有边界
```

---

## 2. 目标与边界

目标：

1. 把 `lake_console` 从文件浏览台升级为本地 Lake 运维管理台。
2. 先补最缺的治理能力：
   - 恢复与写入安全
   - 空间与保留策略
   - 分区完整性与健康
   - 数据集变更活动追踪
3. 前端采用高信息密度、低噪声、桌面优先的工作台风格。
4. 所有页面都基于真实文件事实、manifest、恢复账本和后端 API，不在前端猜业务事实。

不做：

1. 不把 `lake_console` 做成营销站、大屏或花哨 dashboard。
2. 不接生产 `ops.task_run`、生产 `frontend`、生产用户体系。
3. 不把“操作说明文案”堆成一页帮助文档式页面。
4. 不为了追求“统一风格”引入第二套 UI 框架。

---

## 3. UI 与交互硬约束

本节是后续页面开发必须遵守的显式约束，不是审美建议。

### 3.1 页面气质

管理台必须呈现：

1. 专业
2. 克制
3. 紧凑
4. 高信息密度但不拥挤
5. 面向数据运维而不是面向宣传展示

明确避免：

1. 夸张渐变
2. 强装饰背景
3. 重玻璃拟态
4. 大片无意义留白
5. 废话文案铺满页面
6. 一个页面塞太多“先解释概念”的段落

### 3.2 文案策略

页面说明文案必须最小化。

规则：

1. 页面头部只保留一句功能描述。
2. 长解释放入：
   - tooltip
   - 抽屉
   - 详情区
   - 空状态
3. 不在主界面堆“什么是 xxx”“为什么要这样”的长段说明。
4. 表格、卡片、筛选器尽量用字段名、状态名、badge、数值表达，而不是用大段自然语言解释。

统一页面口径：

```text
高密度
低噪声
少废话文案
表格优先
抽屉 / 侧栏承载详情
```

### 3.3 信息密度

默认按“桌面数据运维工作台”设计：

1. 指标卡紧凑，不做大英雄卡。
2. 表格优先，卡片为辅。
3. 详情区采用：
   - 侧边抽屉
   - 可折叠面板
   - 双栏密集元信息
4. 同屏优先回答：
   - 哪个对象异常
   - 异常多严重
   - 下一步能做什么

### 3.4 组件与 token 来源

设计参考基线：

- [frontend-design-tokens-and-component-catalog-v1.md](/Users/congming/github/goldenshare/docs/frontend/frontend-design-tokens-and-component-catalog-v1.md)
- [frontend-component-showcase-v1.html](/Users/congming/github/goldenshare/docs/frontend/frontend-component-showcase-v1.html)

采用原则：

1. 吸收 token、密度规则、表格与卡片风格、状态色分层。
2. 不要求像素级复刻。
3. 旧 showcase 是视觉参考，不是最高约束。
4. `lake_console/frontend` 仍以本地 AGENTS 和现有组件体系为最高边界。

### 3.5 组件方向

后续页面优先复用或扩展：

1. `PageHeader`
2. `Metric`
3. `SectionCard`
4. `DenseToolbar`
5. `DataTableCard`
6. `Badge`
7. `HealthBadge`
8. `EmptyState`
9. `ErrorStateBlock`
10. `LoadingBlock`

不允许每加一个新页面就自造一套卡片/表头/筛选条样式。

---

## 4. 当前现状与缺口

当前已有页面：

1. `datasets`
2. `datasetDetail`
3. `commands`
4. `risks`

当前已有后端能力：

1. Lake 根目录状态
2. 数据集汇总
3. 分区扫描
4. 命令示例
5. 局部专项恢复与审计（以 `stk_mins` 为主）

当前缺口：

1. 看不到正式写入历史和恢复轨迹。
2. 看不到 backup / restore / retention / pin 的真实状态。
3. 看不到数据湖空间分布与层级占用结构。
4. 看不到完整性 / 缺失 / 已修补 / source gap 的全局视图。
5. 看不到最近写入、恢复、repair、derive、rebuild 的活动流。
6. 看不到 schema 漂移与层间契约风险。
7. 当前 command 页面更像静态示例，不像管理入口。

---

## 5. 功能优先级

### P0：Recovery / Write Safety

优先级最高。

原因：

1. `stk_mins` P0 事故已经证明“能看文件”不等于“能治理事故”。
2. 这页和 [Local Lake Kopia 集成恢复管理方案 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-write-recovery-management-plan-v1.md) 是同一条主线。

核心能力：

1. 展示 Kopia repository 状态
2. 展示 snapshot inventory
3. 展示 baseline 与 pin 状态
4. 支持按 dataset/path/scope 筛选
5. 展示 restore 命令预览

第一批页面最小 API 见：

- [Local Lake Recovery 最小 API 设计 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-recovery-api-minimal-design-v1.md)

### P1：Storage / Cost

目标：

1. 让管理者知道空间主要花在哪
2. 看清 raw / derived / research / manifest / recovery 的占用
3. 找出体量最大、文件最多、增长最快的数据集

第一期页面边界与最小 API 见：

- [Local Lake Storage / Cost 页面边界卡 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-storage-cost-page-boundary-card-v1.md)
- [Local Lake Storage / Cost 最小 API 设计 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-storage-cost-api-minimal-design-v1.md)

### P1：Partition Health / Completeness

目标：

1. 看数据集完整性，而不只是“有没有文件”
2. 明确显示：
   - missing
   - underfilled
   - source_gap
   - repaired
   - restorable

### P1：Dataset Activity / Change Feed

目标：

1. 看最近有哪些写入、恢复、repair、derive、research rebuild
2. 快速回答“最近 Lake 发生了什么”

### P2：Schema / Contract

目标：

1. 看各层 schema 摘要
2. 看是否有分区 schema 漂移
3. 看层间契约风险

### P2：Command Center 升级

目标：

1. 从静态示例页升级为管理动作入口
2. 提供建议命令、前置条件、风险等级、关联对象

### P2：DuckDB Query Workbench

目标：

1. 只读 sample query
2. 局部抽样
3. 用于诊断和抽查

---

## 6. 页面信息架构

建议主导航升级为：

```text
Datasets
Health
Recovery
Activity
Storage
Commands
Risks
```

说明：

1. `Datasets` 仍保留，作为目录入口。
2. `Risks` 不删除，但地位下降，更多承担全局告警汇总。
3. `Recovery / Activity / Storage / Health` 是新治理主轴。

---

## 7. 页面方案

### 7.1 Datasets

保留，但升级目标是：

1. 更强筛选
2. 更紧凑总览
3. 更少装饰性说明

建议新增：

1. 按 `source / group / layer / status / size tier` 筛选
2. 快捷列：
   - total bytes
   - layer count
   - latest modified
   - health badge
   - recovery badge
3. 支持排序：
   - 文件数
   - 体量
   - 风险数

### 7.2 Dataset Detail

升级重点：

1. 从“基础元信息页”升级为“对象控制面板”
2. 强化：
   - layer summary
   - partition summary
   - health summary
   - recent writes
   - recent recovery

建议结构：

1. 顶部紧凑 header
2. 第一屏：
   - 核心指标
   - 健康状态
   - 最近写入
3. 第二屏：
   - layer cards
   - partition table
   - schema摘要

### 7.3 Health

这页是“分区健康与完整性”主入口。

核心模块：

1. 全局 posture
2. 数据集健康表
3. 缺失/低填充分区表
4. source gap 与 repaired 统计
5. layer consistency 风险

默认展示原则：

1. 先表格后图形
2. 图形只做辅助，不做 dashboard 化装饰

### 7.4 Recovery

这页是恢复治理主入口。

核心模块：

1. 概览指标
2. Kopia snapshot 主表
3. baseline / pin / retention 状态
4. restore command 详情抽屉
5. repository 状态

交互：

1. 主表支持按 dataset、scope、date range、pinned、baseline 筛选
2. 行点击开右侧详情抽屉
3. 详情抽屉里给出建议命令
4. 第一期间只做命令预览，不直接在前端放 destructive 按钮

### 7.5 Activity

这页回答：

```text
最近 Lake 发生了什么？
```

核心事件：

1. sync
2. repair
3. derive
4. research rebuild
5. schema migration
6. restore
7. cleanup

展示方式：

1. 时间轴 + 紧凑事件表
2. 支持按 dataset / action type 筛选
3. 支持按 run_id 打开详情

### 7.6 Storage

这页回答：

```text
空间花在哪里？哪些最值得优化？
```

核心模块：

1. layer 占用
2. dataset 占用排行
3. file count 排行
4. recovery/backups 占用
5. growth candidates

展示原则：

1. 以表格和紧凑 bar 为主
2. 不做复杂饼图堆砌

### 7.7 Commands

升级目标：

1. 不只是示例
2. 要成为“对象上下文驱动”的命令中心

建议能力：

1. 根据当前 dataset / current risk / recovery record 自动筛选相关命令
2. 标记：
   - safe
   - write
   - destructive
3. 支持复制完整命令
4. 详情中列出 prerequisite 和 expected effect

### 7.8 Risks

保留为全局风险汇总页，但应弱化“说明书式文案”。

重点：

1. 风险汇总计数
2. 风险按 severity / type / dataset 分组
3. 支持跳转到：
   - Health
   - Recovery
   - Dataset Detail

---

## 8. 后端 API 扩展建议

第一批新增：

```text
GET  /api/health/summary
GET  /api/health/partitions
GET  /api/recovery/repository-summary
GET  /api/recovery/snapshots
GET  /api/recovery/snapshots/{snapshot_id}
GET  /api/activity/feed
GET  /api/storage/summary
GET  /api/storage/datasets
GET  /api/schema/datasets
```

说明：

1. 先以只读 API 和命令预览为主。
2. destructive apply 类 API 后置。
3. 所有新 API 都必须直接基于：
   - Kopia repository
   - Kopia snapshot inventory
   - 文件路径映射
4. 不允许前端自己拼 recovery 状态或 health 结论。

---

## 9. 组件与交互建议

建议补充的共享组件：

1. `CompactMetricStrip`
2. `FilterBar`
3. `StatePill`
4. `DeltaStat`
5. `TimelineTable`
6. `SideDetailDrawer`
7. `StatTable`
8. `RetentionBadge`
9. `PinBadge`
10. `CommandHintCard`

交互原则：

1. 列表页优先支持键盘复制、排序、筛选、抽屉详情。
2. 详情优先在抽屉展开，而不是整页跳转层层嵌套。
3. destructive 动作必须：
   - 显式标红
   - 有前置 dry-run
   - 有确认步骤
4. 常见操作结果优先给：
   - 建议命令
   - 影响范围
   - 是否可回滚

---

## 10. 与现有方案的关系

本路线图不替代：

1. [Local Lake Console 架构方案 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-console-architecture-plan-v1.md)
2. [Local Lake Kopia 集成恢复管理方案 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-write-recovery-management-plan-v1.md)

关系如下：

1. `local-lake-console-architecture-plan-v1.md`
   - 定边界和总路线
2. `local-lake-write-recovery-management-plan-v1.md`
   - 定恢复与备份主线
3. **本文**
   - 定“管理台产品形态、页面结构、优先级和 UI/交互约束”

---

## 11. 分阶段实施建议

### Phase 1

目标：

1. Recovery 页面
2. Storage 页面
3. 对应 summary/read-only API

理由：

1. 先解决 P0 恢复治理
2. 先解决大湖空间认知

### Phase 2

目标：

1. Health 页面
2. Activity 页面
3. Dataset Detail 升级

### Phase 3

目标：

1. Schema / Contract 页面
2. Command Center 升级
3. DuckDB Query Workbench

---

## 12. 验收标准

产品层：

1. 管理台不再只是“能看文件”，而是能管理恢复、空间、健康和活动。
2. 页面说明文案显著收缩，不再呈现“说明书式首页”。
3. 首屏以指标、表格、badge、抽屉为主，信息密度提升但不拥挤。

前端层：

1. 不引入第二套 UI 框架。
2. 复用现有 token 与组件体系。
3. 新页面能和当前 `lake_console` 风格一致。

后端层：

1. 新增 API 不依赖远程生产状态表。
2. 所有治理状态都来自本地文件事实与 manifest。

治理层：

1. Recovery / Write Safety 页面与恢复账本方案一致。
2. Health / Storage / Activity 页面各自有明确事实源，不互相猜状态。

---

## 13. 当前结论

数据湖管理台下一阶段最需要的，不是继续加几个“更详细的数据集卡片”，而是补齐以下三类治理能力：

1. **恢复与写入安全**
2. **空间与保留策略**
3. **完整性与活动追踪**

界面层面必须坚持：

1. 高密度
2. 低噪声
3. 少废话
4. 交互直接
5. 以表格、指标、badge、抽屉和筛选为主

如果后续按这条路线推进，`lake_console` 才会真正从“文件浏览器”升级为“可治理的数据湖管理台”。
