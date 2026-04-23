# 前端治理落地总计划与评审记录 v2

> 角色说明：本文件是“前端治理与推广计划专题文档”。  
> 当前前端强约束与统一门禁请以 [frontend-current-standards.md](/Users/congming/github/goldenshare/docs/frontend/frontend-current-standards.md) 为准。

## 1. 文档目的

本文用于在继续落前端治理与页面收敛之前，先把整体计划、阶段目标、评审门禁、试点范围、风险与回滚策略整理清楚，并形成一版可讨论、可执行、可复查的评审基线。

适用范围：

- `frontend/**`
- 前端治理相关文档
- 前端共享组件、主题、页面试点与自动化建设

本文不替代页面专项方案；它是前端治理这条线的总计划。

---

## 2. 背景与问题定义

当前前端并不是“没有基础”，而是“基础已出现，但没有被组织成稳定交付体系”。

已存在的基础包括：

- React 19 + TypeScript + Vite
- Mantine 作为主 UI 基座
- TanStack Query / Router
- 已有少量共享 UI 组件
- 已有前端一期方案与技术选型文档
- 已有部分页面测试

当前主要问题集中在 5 类：

1. 缺少从需求到上线的完整前端交付流程
2. 缺少统一的交互、视觉、token 规则
3. 缺少统一的共享组件标准库
4. 缺少前端任务专用的 AGENTS / 协同约束
5. 缺少自动化门禁、试点节奏与扩展路径
6. 缺少按层级梳理上下文、持续沉淀技能与规则的机制

因此，本计划的目标不是：

- 一次性重写全部前端页面
- 先做“全站视觉翻修”
- 在没有评审门禁的情况下直接大改页面

本计划的目标是：

- 先把治理骨架搭稳
- 再用试点页面验证
- 最后再规模化推广
- 在推进过程中持续沉淀流程、规范、技能与 AGENTS 分层

---

## 3. 已确认基线

以下事项已确认，作为本计划默认前提：

1. 新视觉只进入新页面和重构页面，旧页面渐进迁移
2. v1 仅正式支持亮色主题，暗色只保留 token 预留
3. `1280+` 为正式工作宽度，`1024-1279` 为降级可用区间
4. 平台固定采用红涨绿跌，不提供用户偏好切换
5. Shell 保留品牌头部结构，但整体风格做克制化收敛

### 3.1 已记录的暂缓事项

以下事项已记录为后续 `Todo`，当前不作为阻塞项：

1. 暗色模式先保留 token 预留，待 `v1` 主体完成后再单独评审。
2. 设计师建议的组件目录结构先吸收思想，不强制立即改仓库路径。
3. Storybook 先不全面落地，当前以“组件说明 + Showcase + smoke + 测试”为现实基线。
4. 设计师文档中的绝对硬规则先作为默认规范与评审口径，不立即升级为强卡点。

---

## 4. 当前现状快照

以下事实用于支撑本计划，不靠主观感觉推进：

### 4.1 工程规模

- 当前 `frontend/src/pages` 下共有 `34` 个页面/页面相关文件
- 当前 `frontend/src` 下共有 `28` 个单元/组件测试文件
- 当前 `frontend/e2e` 下已有 `1` 组 Playwright smoke/视觉门禁用例

### 4.2 页面膨胀信号

当前已有多个页面文件明显过厚：

- `frontend/src/pages/ops-v21-task-auto-tab.tsx`：1649 行
- `frontend/src/pages/ops-v21-task-manual-tab.tsx`：1123 行
- `frontend/src/pages/ops-v21-review-board-page.tsx`：893 行
- `frontend/src/pages/ops-task-detail-page.tsx`：870 行
- `frontend/src/pages/ops-v21-account-page.tsx`：788 行

这说明当前前端已进入“需要通过组件和分层治理来控厚度”的阶段。

### 4.3 自动化现状

- 当前已具备前端专用 CI：
  - `.github/workflows/frontend-quality-gate.yml`
- 当前已具备最小视觉回归门禁：
  - `typecheck + test + build + smoke/visual gate`
- 当前 Playwright smoke 已覆盖 8 个代表页面：
  - 登录页
  - `ops/v21/overview`
  - `ops/v21/datasets/tasks?tab=records`
  - `ops/v21/datasets/tasks?tab=manual`
  - `ops/v21/datasets/tasks?tab=auto`
  - `ops/v21/datasets/tasks/detail`
  - `ops/v21/review/index`
  - `share`
- 当前仍未引入完整 Storybook / Chromatic / Percy，这部分维持后续评估

### 4.4 风格现状

当前 `Phase 2` 已完成主题基线与高可见视觉收敛，旧视觉主入口已明显减少。

仍需承认：

- 共享组件标准库还未完全成型
- 页面中仍可能存在局部重复实现
- 设计规则已经有了，但已通过 `Phase 3/4` 变成可复用组件体系与试点页基线

---

## 5. 计划原则

本计划遵守以下原则：

### 5.1 先治理，后扩张

在没有统一 token、共享组件、流程门禁前，不继续放大页面数量和分支样式。

### 5.2 先试点，后推广

先选择一个能代表真实复杂度的试点流程页，用试点去校验规范是否真的能落地。

### 5.3 先主路径，后装饰

优先解决：

- 结构
- 状态
- 组件
- 测试

再处理：

- 细碎视觉 polish
- 次级动效
- 大规模页面统一清理

### 5.4 先共享组件，后页面复制

任何在试点中出现两次以上的交互模式，都优先抽成共享标准件。

### 5.5 先门禁，后提速

真正的效率来自：

- 统一流程
- 统一组件
- 统一测试门禁

而不是来自“页面先糊出来”。

### 5.6 先沉淀，再复制

每推进一个阶段，都必须留下可复用资产，而不是只留下“大家记得怎么做”。

需要持续沉淀的资产包括：

- 研发流程
- 评审清单
- 测试门禁
- 共享组件规范
- 主题与 token 规则
- 技能草案
- 各层级 AGENTS 文件

### 5.7 视觉优化与代码重构必须一起做优先级管理

任务中心试点不会只是“换皮”。

试点过程中必然会涉及：

- 页面拆分
- 共享组件抽取
- 状态流转收敛
- 查询与交互逻辑整理

因此每次改动都必须提前说明：

- 主目标
- 非目标
- 改动范围
- 风险点
- 验证方式

不允许把“顺手一起改”作为默认策略。

---

## 6. 阶段计划

## 6.1 Phase 0：计划梳理与评审

目标：

- 明确整体路径
- 固化已确认基线
- 形成本计划文档

交付物：

- 本文档

完成标准：

- 计划、范围、节奏、试点边界、风险、评审口径明确

当前状态：

- 已完成

## 6.2 Phase 1：治理骨架收口

目标：

- 把前端治理的规则文件和方法论文档落下
- 让后续前端任务有统一入口

交付物：

- `frontend/AGENTS.md`
- `docs/frontend/frontend-delivery-workflow-v1.md`
- `docs/frontend/frontend-design-tokens-and-component-catalog-v1.md`

完成标准：

- 新前端任务可以直接按这 3 份文档起步
- 评审时不再临时口头定义规则

当前状态：

- 已完成

## 6.3 Phase 2：主题与 token 基础设施

目标：

- 把文档里的 token 真正落到 `theme.ts` 与基础样式层
- 建立新旧风格并存时的迁移策略

执行基线：

- 具体执行以 `docs/frontend/frontend-phase2-execution-brief-v1.md` 为准

建议交付物：

- 收敛后的 `frontend/src/app/theme.ts`
- 收敛后的 `frontend/src/styles.css`
- 一份“旧风格兼容与迁移说明”
- 一份 token 变更检查清单

完成标准：

- 新页面可以不再直接依赖紫色梯度和 `glass-card`
- 新组件有可用的语义 token
- 页面不再随意写死颜色/间距/阴影

风险：

- 若直接全站替换，回归范围会过大
- 若 token 命名过早过细，反而拖慢推进

策略：

- 只先收主 token
- 暂不做暗色主题完整适配

配套沉淀：

- 形成一版 `theme / token` 调整的执行清单
- 为后续“主题与 token 调整 skill”积累稳定输入

## 6.4 Phase 3：高频共享组件标准库

目标：

- 把页面中最高频、最容易失控的模式抽成共享组件
- 把“设计规范 -> 组件目录 -> 视觉对照 -> 代码实现 -> 测试”串成闭环
- 为任务中心试点页准备足够稳定的第一批通用组件和领域组件

本阶段交付物：

1. 升级后的组件目录文档
2. HTML Showcase 视觉对照
3. 第一批通用组件标准件
4. 第一批领域组件标准件
5. 组件研发流程与评审清单
6. 组件接入与回归约束

第一批通用组件优先级：

1. `PageHeader`
2. `SectionCard`
3. `StatusBadge / StatusPill`
4. `StatCard`
5. `FilterBar`
6. `DataTable / TableShell`
7. `EmptyState`
8. `AlertBar`
9. `DetailDrawer`
10. `Timeline`

第一批领域组件优先级：

1. `PriceText`
2. `ChangeText`
3. `TradeDateField`
4. `StockBadge`
5. `LimitUpChip / LimitUpLadder`

完成标准：

- 关键组件具备“组件说明 + Showcase 对照 + 代码实现 + 测试”
- 试点页面不再在本地重复拼这些结构
- 后续页面接入标准件成本明显下降
- 组件边界、使用场景、禁用场景可复述

当前落地状态（2026-04-20）：

- 通用组件已收敛：`PageHeader`、`SectionCard`、`StatusBadge`、`StatCard`、`FilterBar`、`TableShell`、`EmptyState`、`AlertBar`、`DetailDrawer`、`ActivityTimeline`
- 领域组件已落下最小版本：`PriceText`、`ChangeText`、`TradeDateField`
- 当前仓库的表格基线采用 `TableShell + OpsTable`
- 任务中心链路已经稳定消费这些标准件，并已支撑 `Phase 4` 试点页重构完成

风险：

- 组件抽得过早、过大，容易变成新的大而全抽象
- 为了对齐设计稿而触发目录级迁移，导致节奏失控

策略：

- 只抽“已确认复用”的模式
- 每个组件先服务 2-3 个页面，再谈更泛化
- 先做逻辑分层，不为了 `src/components/ui` 这类建议路径做结构级迁移
- 当前组件交付基线采用“组件说明 + Showcase + 测试 + 必要 smoke”
- Storybook 先列为后续事项，不作为本阶段前置条件

配套沉淀：

- 为共享组件抽取形成组件设计说明与接入规范
- 开始补齐 `frontend` 内部分层 AGENTS
- 让 HTML Showcase 进入文档索引，作为页面级视觉对照

建议 AGENTS 分层如下：

- `frontend/src/app/AGENTS.md`
- `frontend/src/shared/ui/AGENTS.md`
- `frontend/src/shared/api/AGENTS.md`
- `frontend/src/features/AGENTS.md`
- `frontend/src/pages/AGENTS.md`

这些 AGENTS 应明确：

- 目录职责
- 允许依赖
- 不应承接的逻辑
- 测试要求
- 常见改动方式

## 6.5 Phase 4：试点页面重构

目标：

- 用一个真实复杂页面链路验证治理方案可落地

建议试点范围：

- 任务中心相关链路

建议原因：

- 同时覆盖表格、筛选、状态、详情、手动/自动任务
- 当前页面文件已有明显膨胀
- 能快速暴露流程、组件和测试的真实问题

建议试点边界：

- 先选一个主链路页面，不要一次改完整个运维系统
- 优先从任务中心中的单页或一组紧密关联页开始

建议试点顺序：

1. `DataTable v1` 支持任务：先在不引入重型表格栈的前提下，定义并验证试点页需要的表格外部契约
2. `TradeDateField v2` 支持任务：补齐交易日历读取层与组件边界，为试点页中的日期输入提供真实交易日能力
3. `task records`：最能验证 `DataTable / StatusPill / FilterBar / EmptyState`
4. `task manual`：验证表单、任务反馈、日期类组件
5. `task auto`：验证复杂筛选、状态块与详情入口
6. `task detail`：验证 Timeline、DetailDrawer、状态摘要

Phase 4 的支持任务要求：

### `DataTable v1`

- 目标：在当前 `TableShell + OpsTable` 基线之上，先收敛一版稳定的表格外部契约
- 默认实现：优先继续使用 Mantine Table 与现有表格壳，不把 TanStack Table 作为 Phase 4 前置条件
- 当前边界：
  - 先定义 `columns / rows / loading / emptyState / toolbar / density / stickyHeader` 这类外部契约
  - 数字列右对齐与 `tabular-nums` 继续作为强约束
  - 先服务任务中心主链路，不外扩到无关页面
- 暂不做：
  - 虚拟滚动
  - 列拖拽与重排
  - 大规模列配置中心
  - 因为抽象表格而引入页面级业务状态回流
- 升级到 TanStack Table 的触发条件：
  - 列排序 / 过滤 / 显隐配置开始明显复杂
  - 多页开始共享同一套列定义模式
  - 行数与交互复杂度足以证明现有实现已经不够
- 当前结果：
  - 已在 `task records`、`task auto`、`task detail` 中接入
  - 当前外部契约已稳定到 `columns / rows / emptyState / summary / getRowProps`

### `TradeDateField v2`

- 目标：把当前“跳过周末 + 预留节假日能力”的最小版本升级成真实交易日输入
- 默认架构：
  - 交易日历读取层放在 `features/*` 或 `shared/api + hook`
  - `shared/ui/TradeDateField` 继续保持展示型组件，不在组件内部直接发请求
- 当前边界：
  - 先提供可缓存、可注入的交易日判断能力
  - 先服务 `task manual` 与 `task auto`
  - 优先支持 A 股交易日场景
- 暂不做：
  - 多市场统一交易日历平台化
  - 复杂交易所差异建模
  - 为组件引入页面级查询逻辑
- 完成标准：
  - 组件层能接收真实交易日能力输入
  - 手动任务页和自动任务页的关键日期输入不再只按周末规则判断
- 当前结果：
  - 交易日历读取层已进入 `features/trade-calendar`
  - `task manual` 与 `task auto` 已接入真实交易日判断
  - 周/月锚点口径已确认统一为“每周最后一个交易日 / 每月最后一个交易日”
  - 前端不再沿用 `week_friday` 作为周锚点业务语义

每轮试点前新增一项准备动作：

- 先读相关 AGENTS
- 先研究现有页面真实代码和重复模式
- 先确定本轮将接入哪些共享组件
- 再写“改动约束卡”

试点前必须补一份“改动约束卡”，至少包含：

- 本轮主目标
- 本轮不做
- 影响文件
- 是否允许重构
- 重构优先级
- 回归范围
- 质量门禁

建议把试点重构优先级分成 3 层：

### P0：必须做

- 会阻塞试点页继续推进的结构问题
- 会直接影响稳定性的状态与交互问题
- 为共享组件抽取必须做的最小拆分

### P1：建议做

- 能明显降低页面复杂度的拆分
- 能复用到相邻页面的抽取
- 能提升测试可写性的结构调整

### P2：暂缓做

- 与试点主链路弱相关的美化
- 与试点无直接关系的壳层重做
- 牵一发而动全身的大范围 API 契约改动

试点阶段的改动边界要求：

1. 每一轮只允许一个主目标
2. 视觉收敛和结构重构可以同轮发生，但必须有主次关系
3. 不因为“顺手”扩大到无关页面
4. 未写明边界的重构不进入实现阶段
5. `DataTable v1` 与 `TradeDateField v2` 虽然属于试点支持任务，但仍然必须按“单一主目标 + 约束卡”推进

试点阶段的质量门禁：

- `npm run typecheck`
- `npm run test`
- `npm run build`
- 受影响页面的定向回归
- 新增共享组件或关键重构点必须补测试
- 每一轮改动要有明确可回滚边界

完成标准：

- 页面厚度下降
- 共享组件开始真正复用
- 页面状态更完整
- 测试覆盖比当前更稳定
- `DataTable v1` 与 `TradeDateField v2` 的边界、外部契约和接入范围可复述

## 6.6 Phase 5：自动化与门禁

目标：

- 在已具备基础质量门禁的前提下，把组件研发与试点重构的门禁继续深化

执行基线：

- 具体执行以 `docs/frontend/frontend-phase5-execution-plan-v1.md` 为准

当前基线：

- 已有 `Frontend Quality Gate`
- 已有 `typecheck + check:rules + test + build + smoke/visual gate`

建议交付物：

1. 试点页专项 smoke 扩面
2. 组件研发 PR 清单固化
3. 可自动检查的规则清单：
   - 颜色硬编码
   - 旧 Mantine 色板误用
   - 数字列对齐与 `tabular-nums`
4. 截图基线更新与验收流程说明

最低完成标准：

- PR 或合入前可以自动跑前端基础门禁
- 组件或试点页的大改动有可复用的回归路径

本阶段暂不强求：

- 完整 Storybook
- Chromatic / Percy 这类平台化视觉回归
- 全量 E2E 覆盖
- 把所有设计规范都一次性升级成 CI 阻塞规则

配套沉淀：

- 把门禁命令、失败处理方式和回归清单写入前端流程文档
- 为后续“前端验收与回归 skill”沉淀输入
- 把“哪些规则先评审、哪些规则再自动化”写清楚，避免过度卡点

当前状态：

- 已完成

## 6.7 Phase 6：规模化推广

目标：

- 将试点中验证有效的模式推广到更多页面
- 在不扩大业务改造面的前提下，把高可见页面继续拉回统一组件、统一回归流程

执行基线：

- 具体执行以 [frontend-phase6-execution-plan-v1.md](/Users/congming/github/goldenshare/docs/frontend/frontend-phase6-execution-plan-v1.md) 为准

当前建议批次：

1. `P6-1` 低风险推广批：
   - `platform-check-page.tsx`
   - `user-overview-page.tsx`
   - `ops-source-management-page.tsx`
2. `P6-2` 审查中心推广批：
   - `ops-v21-review-index-page.tsx`
   - `ops-v21-review-board-page.tsx`
3. `P6-3` 数据详情推广批：
   - `ops-v21-source-page.tsx`
   - `ops-v21-dataset-detail-page.tsx`
4. `P6-4` 管理配置推广批：
   - `ops-v21-account-page.tsx`
5. `P6-5` 收口与残留清单

推广顺序建议：

1. 试点链路相邻页面
2. 使用相同组件模式的页面
3. 壳层与导航层
4. 其他较旧页面

完成标准：

- 共享组件使用率上升
- 新旧风格差异逐步收敛
- 页面文件膨胀趋势被控制

当前状态：

- 已完成第一轮规模化推广
- 当前已形成收口总结与残留清单，后续不建议默认继续开新批次

---

## 7. 里程碑与出场条件

### M1：治理文档 ready

条件：

- 前端 AGENTS、交付流程、token/组件目录都已落地

状态：

- 已达成

### M2：主题基线 ready

条件：

- `theme.ts` 与基础样式已切到新 token 方向
- 新页面可不再依赖旧视觉遗留

状态：

- 已达成

### M3：试点组件 ready

条件：

- 至少 5 个高频共享组件可稳定复用

状态：

- 已达成

### M3.5：前端上下文分层 ready

条件：

- `frontend` 目录下关键层级 AGENTS 已补齐
- 各层职责与依赖方向已写清
- 前端任务进入目录时能快速获得正确上下文

状态：

- 已达成

### M4：试点页通过验收

条件：

- 至少一条试点页链路完成收敛
- `typecheck / test / build` 可通过
- 页面体验明显优于旧版
- 改动范围、重构优先级与回滚边界可复述

状态：

- 已达成

### M5：自动化门禁 ready

条件：

- 前端基础 CI 可跑

状态：

- 已达成基础版
- 后续进入“门禁深化”阶段

### M6：规模化推广 ready

条件：

- 已形成正式推广批次与边界卡机制
- 推广页默认验证档位已明确
- 推广过程不再靠口头约定边界

状态：

- 已达成（第一轮推广完成，并已形成残留清单）

---

## 8. 建议试点策略

状态说明：

- `Phase 4` 已完成
- 本节保留为试点策略回顾
- 当前实际推进顺序请以 `Phase 5` 与 [frontend-phase5-execution-plan-v1.md](/Users/congming/github/goldenshare/docs/frontend/frontend-phase5-execution-plan-v1.md) 为准

当前不建议：

- 一上来重做整个 `OpsShell`
- 一次性替换所有页面风格
- 同时改主题、组件、试点页、CI、E2E

当前建议：

1. 先按既有批次推进推广页
2. 每批都先补“改动边界卡”
3. 再按回归流程选定验证档位
4. 最后把推广结果收回到残留清单与下一轮建议

理由：

- 这样能把回归面控制住
- 能尽早验证共享组件是否够用
- 能避免“规范写了一堆，但页面还是老样子”的落空

---

## 9. 评审清单

本计划评审时，建议按以下问题过一遍：

### 9.1 方向评审

- [ ] 是否同意“先治理、后试点、再推广”的顺序
- [ ] 是否同意不做 big bang 全站改版
- [ ] 是否同意先不做暗色主题

### 9.2 范围评审

- [ ] 当前试点是否应聚焦任务中心链路
- [ ] 当前是否只做前端治理，不同步拉大后端改造面
- [ ] 自动化是否先从基础 CI 开始，而不是直接全量 E2E
- [ ] 任务中心试点成果是否已有足够的 smoke / visual gate 保护

### 9.3 落地评审

- [ ] Phase 2 的 token 落地是否足够克制
- [ ] Phase 3 的组件优先级是否合理
- [ ] Phase 5 的门禁深化范围是否够小
- [ ] M2 / M3 / M4 / M5 的出场条件是否足够明确
- [ ] 研发流程、技能、规范是否作为阶段产物持续沉淀
- [ ] 是否同意补齐 `frontend` 内部分层 AGENTS

---

## 10. 本轮评审结论

基于当前仓库现状，本计划的评审结论是：

### 10.1 可以继续推进

原因：

- 治理文档入口已具备
- 已确认基线已拍板
- 当前问题已经足够明确
- 试点式推进比继续零散改页面更稳
- 现在已经把流程沉淀、技能沉淀、AGENTS 分层纳入了计划本身

### 10.2 不建议跳步

当前不建议直接进入：

- 全站主题替换
- 全页面视觉重做
- 多页面并行大改
- 先上视觉回归平台再说
- 在没有边界卡和优先级分层的情况下直接重构任务中心

### 10.3 建议的下一步

按照以下顺序执行最稳：

1. 以 [frontend-phase6-execution-plan-v1.md](/Users/congming/github/goldenshare/docs/frontend/frontend-phase6-execution-plan-v1.md) 为准确认第一批 `P6-1` 的边界卡
2. 先处理低风险推广批，不并批推进
3. 每批结束后回看验证结果，再进入下一批

---

## 11. 风险与应对

### 风险 1：规范写了，但代码没有真正切过去

应对：

- 在 `Phase 6` 中继续把组件目录、Showcase、smoke 与规则检查绑到同一套门禁里

### 风险 2：组件抽象过度

应对：

- 每次只抽当前试点真实复用的模式

### 风险 3：推广范围过大

应对：

- 按批次推进，只处理边界卡中写明的页面

### 风险 3.1：试点过程中重构范围失控

应对：

- 每轮试点都先写“改动约束卡”
- 用 P0 / P1 / P2 管理重构优先级
- 无边界说明的重构不进入实现

### 风险 4：自动化过晚，治理靠记忆

应对：

- 基础 CI 已完成，后续重点转为专项回归和组件规则自动化

### 风险 5：规则沉淀停留在顶层文档，进入目录后上下文仍然模糊

应对：

- 补齐 `frontend` 内部分层 AGENTS
- 让目录级职责、依赖方向和测试要求在进入局部目录时即可获得

---

## 12. 回滚与调整策略

若后续执行中发现计划不适用，按以下顺序调整：

1. 先缩小试点范围
2. 再下调组件抽象范围
3. 再延后次级能力，例如 E2E、视觉回归、暗色主题

不采用的调整方式：

- 直接放弃治理，重新回到页面级临时拼装
- 为了赶进度重新引入第二套主 UI 风格

---

## 13. 下一步动作

若本计划继续推进，下一步建议只做一件事：

- 先评审 [frontend-phase6-rollout-summary-v1.md](/Users/congming/github/goldenshare/docs/frontend/frontend-phase6-rollout-summary-v1.md)，再决定进入专项治理还是开启新一轮推广

执行前必须先：

1. 重读相关 AGENTS
2. 对照 [frontend-phase6-rollout-summary-v1.md](/Users/congming/github/goldenshare/docs/frontend/frontend-phase6-rollout-summary-v1.md) 确认当前残留点与候选专项
3. 对照 [frontend-regression-and-baseline-workflow-v1.md](/Users/congming/github/goldenshare/docs/frontend/frontend-regression-and-baseline-workflow-v1.md) 选定本轮验证档位
4. 明确本轮属于专项治理还是新一轮推广
5. 再进入具体实现
