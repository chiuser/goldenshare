# 前端 Phase 2 执行简报 v1

> 角色说明：本文件是“前端阶段执行专题文档（Phase 2）”。  
> 当前前端强约束与统一门禁请以 [frontend-current-standards.md](/Users/congming/github/goldenshare/docs/frontend/frontend-current-standards.md) 为准。
>
> 状态说明：本文件保留为“阶段执行模板 + 历史复盘材料”，用于后续同类阶段的开工检查参考。

## 1. 文档目的

本文用于沉淀 Phase 2 的执行模板（目标、边界、步骤、检查项），并作为后续阶段的复用参考。

当前真正生效的“统一规则”仍以：

1. [frontend-current-standards.md](/Users/congming/github/goldenshare/docs/frontend/frontend-current-standards.md)
2. [frontend-governance-rollout-plan-v1.md](/Users/congming/github/goldenshare/docs/frontend/frontend-governance-rollout-plan-v1.md)

为准。

---

## 2. 依据来源

本文基于以下规则与现状整理：

1. `AGENTS.md`
2. `frontend/AGENTS.md`
3. `frontend/src/app/AGENTS.md`
4. `frontend/src/shared/ui/AGENTS.md`
5. `docs/frontend/frontend-governance-rollout-plan-v1.md`
6. 当前前端主题、样式、壳层与共享组件实现

若后续这些文档发生更新，应以最新版本为准。

---

## 3. Phase 2 工作目标

Phase 2 的目标只有一个：

- 收敛前端主题与基础样式层，为后续共享组件与试点页重构建立稳定的 token 基线

本阶段重点落点：

- `frontend/src/app/theme.ts`
- `frontend/src/styles.css`

本阶段预期产出：

1. 将当前紫色渐变 / 玻璃拟态 / 高阴影风格收敛到已确认的视觉方向
2. 建立主题 token 的主入口
3. 让后续共享组件可以消费稳定的 token，而不是页面继续写死颜色和样式
4. 形成 Phase 2 的执行清单与迁移说明

---

## 4. Phase 2 非目标

本阶段明确不做以下事情：

1. 不重构任务中心主流程
2. 不做页面级大规模结构重构
3. 不改 API 契约
4. 不改路由结构
5. 不做暗色主题完整支持
6. 不做全站视觉一次性翻新
7. 不顺手把“看起来也能一起改”的页面问题一起收掉

如果执行中发现某项改动已经超出以上边界，应停下来重新评估，而不是继续扩张。

---

## 5. 当前硬约束

### 5.1 改动范围约束

Phase 2 默认只允许直接改动：

- `frontend/src/app/theme.ts`
- `frontend/src/styles.css`

允许少量联动修补的范围仅限：

- 直接消费这些全局 token / class 的壳层文件
- 直接依赖这些基础样式的共享组件

例如：

- `frontend/src/app/shell.tsx`
- `frontend/src/app/share-shell.tsx`
- `frontend/src/shared/ui/section-card.tsx`

但这些联动修补必须满足：

- 为了完成主题与样式收敛必需
- 不引入页面业务重构
- 不扩大到无关页面

### 5.2 统一约束引用

目录职责、决策约束与方法约束已统一收口到：

- [前端当前强约束（统一基线）](/Users/congming/github/goldenshare/docs/frontend/frontend-current-standards.md)

本执行简报仅保留 Phase 2 的阶段边界与执行步骤，不重复维护通用约束。

---

## 6. 每轮开工前必做清单

每一轮开始前，至少执行以下检查。

### 6.1 规则检查

必须重读：

1. `frontend/AGENTS.md`
2. 本轮目标目录下更近的 `AGENTS.md`

Phase 2 默认至少会涉及：

- `frontend/src/app/AGENTS.md`
- `frontend/src/shared/ui/AGENTS.md`

### 6.2 代码检查

必须确认：

1. 当前目标文件的最新实现
2. 当前目标 token / class 的真实使用点
3. 当前壳层和共享组件是否直接依赖这些样式
4. 当前测试是否已经覆盖相关行为

推荐最小检查方式：

- 读目标文件
- `rg` 查找类名、token 名、主题色名、组件使用点
- 读直接消费者文件

### 6.3 边界检查

每轮开始前写清：

- 本轮主目标
- 本轮不做
- 允许修改的文件
- 不允许扩张到的目录
- 验证方式

如果这 5 项说不清，不进入实际修改。

---

## 7. Phase 2 推荐执行步骤

建议按以下顺序推进，每次只做一小轮。

### Step 1：盘点旧视觉入口

优先盘点：

- `theme.ts` 中品牌色、圆角、阴影、组件默认样式
- `styles.css` 中渐变背景、`glass-card`、品牌相关 class
- `shell.tsx` / `share-shell.tsx` 对这些样式的直接消费

产出：

- 旧视觉入口清单
- 新 token 对应关系

### Step 2：建立主 token 结构

先在 `theme.ts` 与 `styles.css` 中建立主 token 结构：

- neutral
- brand
- up / down
- semantic
- spacing / radius / shadow

要求：

- 先主干，后细节
- 不过早把 token 拆得过细

### Step 3：收敛全局基础样式

收敛：

- 页面底色
- 全局字体
- 根级颜色变量
- `app-gradient-shell`
- `glass-card`
- logo / brand 相关类

要求：

- 优先兼容式替换
- 不直接造成整站大面积回归风险

### Step 4：收敛 Mantine 主题入口

收敛：

- `Button`
- `Badge`
- `NavLink`
- `Card`

要求：

- 只做与 Phase 2 目标直接相关的默认样式调整
- 不在本阶段顺手重做所有组件体系

### Step 5：最小联动修补

如果壳层或共享组件因为 Phase 2 收敛而必须调整，只做最小修补。

优先范围：

- `app/shell.tsx`
- `app/share-shell.tsx`
- `shared/ui/section-card.tsx`

### Step 6：验证与记录

每一轮结束后至少记录：

- 本轮目标
- 改动文件
- 哪些旧入口被收敛了
- 哪些遗留故意保留到下一轮
- 验证结果
- 风险与待确认项

---

## 8. 每轮验证要求

Phase 2 每一轮结束后，至少考虑：

1. `npm run typecheck`
2. `npm run test`
3. `npm run build`

若影响壳层或共享组件，额外确认：

- 登录页可用
- 壳层页面可进入
- 卡片与基础组件未明显退化

---

## 9. 风险与停手条件

出现以下情况时，应暂停继续改，而不是硬推：

1. 发现必须同时重构页面业务逻辑才能继续
2. 发现主题收敛会牵出大量页面级回归
3. 发现当前目录职责与计划不匹配
4. 发现真实使用点和预期不一致
5. 发现需要重新拍板的设计决策

暂停后应先做：

- 代码研究
- 影响面梳理
- 风险说明

不要用猜测补空白。

---

## 10. 执行纪律

Phase 2 的默认执行纪律如下：

1. 每轮开始前先读相关 AGENTS
2. 每轮开始前先研究目标文件和直接使用点
3. 每轮只做一个主目标
4. 不把额外页面重构混入本轮
5. 不靠猜测做主题或样式迁移决策
6. 每轮结束都要留下可复查记录

本文的意义，就是让 Phase 2 从一开始就是“受控推进”，而不是“边改边想”。
