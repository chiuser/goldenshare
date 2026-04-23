# 前端当前强约束（统一基线）

更新时间：2026-04-23

## 1. 文档定位

本文件是前端研发流程与交付门禁的统一基线，解决“多份前端文档口径不一致”的问题。

当以下文档出现冲突时，以本文件为准：

1. `frontend-application-phase1.md`
2. `frontend-delivery-workflow-v1.md`
3. `frontend-design-tokens-and-component-catalog-v1.md`
4. `frontend-governance-rollout-plan-v1.md`
5. `frontend-phase2-execution-brief-v1.md`
6. `frontend-phase5-execution-plan-v1.md`
7. `frontend-phase6-execution-plan-v1.md`
8. `frontend-regression-and-baseline-workflow-v1.md`

---

## 2. 范围与边界

1. 适用范围：`frontend/**`。
2. 本文件不定义后端架构，不替代 `docs/architecture/*`。
3. 前端页面必须通过稳定 API 契约消费数据，不下沉同步与调度逻辑。

---

## 3. 交付流程基线

中等及以上前端任务必须包含：

1. 需求与用户任务梳理（主任务/次任务/本轮不做）。
2. 交互状态设计（加载/空/异常/权限/成功反馈）。
3. 数据契约确认（接口、字段、错误态）。
4. 实现与测试（最小可回归）。
5. 验收与文档同步（README 索引更新）。
6. 若本轮涉及共享组件，还必须明确组件说明、视觉对照与最小测试策略。

---

## 4. 设计与实现约束

1. 先信息层级，后视觉装饰。
2. 先收敛 token，再做页面风格扩展。
3. 共享组件优先，不允许页面内散落重复实现。
4. 新增页面与重构页面必须遵循统一 token/组件目录。
5. 不得把临时视觉方案写成全局默认。
6. 组件任务默认遵循“组件说明 + Showcase + 测试 + 必要 smoke”的顺序。

---

## 5. 测试与验收基线

至少覆盖：

1. 关键页面渲染 smoke case。
2. 关键交互路径（含异常分支）。
3. 与后端契约相关的最小回归（字段与状态渲染）。
4. 高可见组件或页面模式调整，应评估是否需要截图门禁。
5. 当前已自动化的前端规则，应通过 `npm run check:rules` 校验。
6. 具体回归档位、截图基线刷新纪律与 CI 排查顺序，以 [frontend-regression-and-baseline-workflow-v1.md](/Users/congming/github/goldenshare/docs/frontend/frontend-regression-and-baseline-workflow-v1.md) 为准。

---

## 6. 文档协作规则

1. 本文件维护“当前强约束”；其余文档维护专题细节。
2. 每轮改动前先确认是否触及交付门禁。
3. 专题文档与本文件冲突时，先修正文档再改代码。
4. 共享组件形态变更时，应同步更新组件目录文档与视觉 Showcase。

---

## 7. 当前已确认的暂缓事项

以下事项已确认记录为 `Todo`，当前不作为阻塞项：

1. 暗色模式：
   - `v1` 仅保留 token 预留，不要求正式支持。
   - 待 `v1` 主体完成后，再评估是否进入正式计划。
2. 组件目录路径：
   - 吸收“通用组件 / 领域组件”的分类思想。
   - 实际目录路径以当前仓库 `frontend/src/**` 为准，不为了对齐设计稿做目录级 big-bang 迁移。
3. Storybook：
   - 暂不做全面落地。
   - 当前组件交付基线是“组件说明 + HTML Showcase + 测试 + 必要 smoke”。
   - 待高频组件与试点页稳定后，再单独评估 Storybook 切入方式。
4. 设计师文档中的绝对硬规则：
   - 先作为默认规范与评审参考吸收。
   - 当前不立即升级为强阻塞门禁或 CI 卡点。
