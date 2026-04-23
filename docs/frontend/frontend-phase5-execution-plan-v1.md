# 前端 Phase 5 执行计划 v1

> 角色说明：本文件是“Phase 5 自动化与门禁深化”的执行计划文档。
> 当前前端强约束与统一门禁请以 [frontend-current-standards.md](/Users/congming/github/goldenshare/docs/frontend/frontend-current-standards.md) 为准。

## 1. 文档目的

本文用于把前端治理在 `Phase 5` 的执行边界、工作包、顺序、完成标准和非目标写清楚，避免在 `Phase 4` 已完成后继续以“试点页重构”的方式推进后续工作。

适用范围：

- `frontend/**`
- 前端质量门禁相关文档
- 前端 smoke / visual gate
- 前端规则自动检查
- 前端相关 AGENTS 与交付流程文档

本文不替代：

- 共享组件目录文档
- 页面专项方案
- 后端架构与契约文档

---

## 2. 当前起点

截至 `2026-04-23`，前端治理进度以当前仓库实际状态为准：

1. `Phase 1` 已完成：治理骨架已落地。
2. `Phase 2` 已完成：主题与 token 基线已收敛。
3. `Phase 3` 已完成：高频共享组件标准库与最小领域组件已形成。
4. `Phase 4` 已完成：任务中心试点页与试点支持任务已落地。

当前已具备的质量基线：

- `npm run typecheck`
- `npm run test`
- `npm run build`
- `npm run test:smoke`
- `.github/workflows/frontend-quality-gate.yml`

当前已覆盖的关键页面基线：

1. 登录页
2. `ops/v21/overview`
3. `ops/v21/datasets/tasks?tab=records`
4. `ops/v21/datasets/tasks?tab=manual`
5. `ops/v21/datasets/tasks?tab=auto`
6. `ops/v21/datasets/tasks/detail`
7. `ops/v21/review/index`
8. `share`

---

## 3. Phase 5 目标

`Phase 5` 的目标不是继续“做页面”，而是把前面 4 个阶段已经收下来的成果保护住、制度化、自动化。

本阶段目标：

1. 更新已过时的前端阶段文档与 AGENTS，避免后续继续按 `Phase 3/4` 语境执行。
2. 盘点当前门禁矩阵，明确已覆盖项、薄弱项和未自动化规则。
3. 扩充任务中心试点链路的 smoke / visual gate，强化回归保护。
4. 把一批已经稳定的前端规则变成可执行检查，而不是继续靠人工记忆。
5. 将新增检查纳入现有 `Frontend Quality Gate`。
6. 固化“什么时候需要跑什么验证、什么时候允许刷新截图基线”的流程说明。

---

## 4. 非目标

本阶段明确不做：

1. 不再进行任务中心页面大重构。
2. 不新增一批与当前门禁无关的共享组件。
3. 不引入完整 Storybook / Chromatic / Percy。
4. 不进行全量 E2E 覆盖建设。
5. 不顺手扩大到后端主线或 API 契约改造。
6. 不把“为了过检查”变成跨页面的大规模样式清理。

---

## 5. 工作包拆分

## 5.1 P5-0：过时文档与 AGENTS 同步

目标：

- 先把仍停留在 `Phase 3/4` 语境的前端文档和 AGENTS 更新为当前阶段口径。

交付物：

1. 更新后的 `frontend-governance-rollout-plan-v1.md`
2. 更新后的 `frontend-smoke-visual-gate-v1.md`
3. 更新后的 `frontend-design-tokens-and-component-catalog-v1.md`
4. 更新后的 `frontend-delivery-workflow-v1.md`
5. 更新后的前端相关 AGENTS
6. 本文档

边界：

- 只修正文档与规则口径
- 不做新的页面实现

---

## 5.2 P5-1：门禁矩阵盘点

目标：

- 形成一份当前前端门禁矩阵，明确“已有、缺失、后续自动化候选”。

交付物：

1. 门禁矩阵文档或章节
2. 当前覆盖页面与组件清单
3. 当前未覆盖风险清单

至少回答：

1. 哪些关键页面已经有 smoke / visual gate
2. 哪些共享组件有单测但没有高可见回归保护
3. 哪些规则仍停留在 AGENTS / 文档中，没有自动检查

边界：

- 只做盘点和结论，不顺手扩 E2E

---

## 5.3 P5-2：Smoke / Visual Gate 扩面

目标：

- 将任务中心试点链路的关键路径与关键状态收进更稳的 smoke / visual gate。

优先覆盖：

1. 任务中心默认入口与 tab 切换
2. `task records` 核心表格与筛选基线
3. `task manual` 的关键日期输入和提交基线
4. `task auto` 的主表与详情抽屉联动基线
5. `task detail` 的状态摘要与时间线基线

边界：

- 只覆盖高价值主路径
- 不追求全量交互录制

---

## 5.4 P5-3：规则自动检查

目标：

- 把一批已经稳定的前端规则升级为自动检查。

第一批候选规则：

1. 禁止新增旧色名误用
2. 禁止新增 `week_friday` 等旧业务语义
3. 禁止在页面中新增旧视觉遗留类作为默认入口
4. 数字列相关规则是否进入共享表达
5. 高可见共享组件改动后是否触发补充验证要求

默认实现方向：

- 优先轻量脚本或 grep 型检查
- 暂不为了这批规则立刻引入复杂 lint 体系

边界：

- 只做高收益、低歧义规则
- 不把所有设计规范一次性 CI 化

---

## 5.5 P5-4：CI 接入与失败可读性

目标：

- 将 `P5-2` 与 `P5-3` 的新增检查纳入现有 `Frontend Quality Gate`。

要求：

1. 失败信息应足够可读
2. 门禁命令应能本地复现
3. 不把 workflow 变成难以排查的黑盒

边界：

- 只深化现有 workflow
- 不另起第二套前端 CI 流程

---

## 5.6 P5-5：回归与更新流程固化

目标：

- 把“以后前端怎么回归、怎么更新截图基线、怎么解释门禁失败”写成明确流程。

交付物：

1. 门禁与回归流程说明
2. 截图基线更新纪律
3. 共享组件改动的最小验证口径
4. 试点页与推广页的最小验证口径

边界：

- 只固化流程，不新增页面改造任务

---

## 6. 执行顺序

`Phase 5` 默认按以下顺序推进：

1. `P5-0` 过时文档与 AGENTS 同步
2. `P5-1` 门禁矩阵盘点
3. `P5-2` smoke / visual gate 扩面
4. `P5-3` 规则自动检查
5. `P5-4` CI 接入
6. `P5-5` 回归流程固化

任何一轮都必须遵守：

1. 只做一个主目标
2. 不顺手扩大到页面重构
3. 不触碰后端主线
4. 不做与当前工作包无关的共享组件抽象

---

## 7. 验证要求

根据工作包不同，至少考虑：

1. `npm run typecheck`
2. `npm run test`
3. `npm run build`
4. `npm run test:smoke`
5. `python3 scripts/check_docs_integrity.py`

默认原则：

- 文档 / AGENTS 更新至少跑文档完整性检查
- 门禁脚本或 workflow 变更必须跑对应本地命令链
- smoke 变更必须明确是否需要更新截图基线

---

## 8. 完成标准

`Phase 5` 完成时，应满足：

1. 前端治理文档和 AGENTS 不再停留在 `Phase 3/4` 语境
2. 任务中心试点链路的 smoke / visual gate 比当前更完整
3. 至少一批前端规则已从“文档要求”升级为“自动检查”
4. 新增检查已接入现有 `Frontend Quality Gate`
5. 回归与截图基线更新流程已被写清楚，可供后续推广使用

---

## 9. 下一阶段入口

`Phase 5` 完成后，再进入 `Phase 6：规模化推广`。

进入 `Phase 6` 的前提是：

1. 门禁深化已落地
2. 试点页成果已有稳定保护
3. 团队不需要重新口头定义页面推广的质量基线
