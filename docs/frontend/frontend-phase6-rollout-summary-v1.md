# 前端 Phase 6 推广收口总结 v1

> 角色说明：本文件用于完成 `Phase 6 / P6-5` 的收口，总结第一轮规模化推广的结果、残留清单与后续建议。
> 当前统一强约束请以 [frontend-current-standards.md](/Users/congming/github/goldenshare/docs/frontend/frontend-current-standards.md) 为准。

## 1. 文档目的

本文用于回答 3 个问题：

1. `Phase 6` 第一轮推广到底完成了什么。
2. 当前还有哪些前端残留点，不适合继续用“顺手推广”去处理。
3. 下一步应该继续什么，不应该继续什么。

本文不负责新增页面实现；只做总结、证据归档与下一步建议。

---

## 2. 推广范围与结果

`Phase 6` 第一轮推广按计划完成了 4 个批次；其中旧数据源桥接页已在后续架构收口中下线。

1. `P6-1` 低风险推广批
   - `platform-check-page.tsx`
   - `user-overview-page.tsx`
2. `P6-2` 审查中心推广批
   - `ops-v21-review-index-page.tsx`
   - `ops-v21-review-board-page.tsx`
3. `P6-3` 数据详情推广批
   - `ops-v21-source-page.tsx`
   - `ops-v21-dataset-detail-page.tsx`
4. `P6-4` 管理配置推广批
   - `ops-v21-account-page.tsx`

本轮推广带来的直接结果：

1. 高可见页面进一步收敛到统一的 `PageHeader / SectionCard / StatusBadge / TableShell / DetailDrawer / DataTable` 模式。
2. 审查中心页进入统一页头、筛选栏、表格壳与 smoke / visual gate 口径。
3. 数据详情页与管理配置页不再继续放大页面级旧卡面和旧状态表达。
4. 管理配置页的用户列表、邀请码列表、编辑动作和重置动作进入统一模式，没有扩大到业务重构。

---

## 3. 当前质量基线

截至本轮收口时，前端当前质量基线为：

1. `npm run typecheck`
2. `npm run check:rules`
3. `npm run test`
4. `npm run build`
5. `npm run test:smoke`
6. `.github/workflows/frontend-quality-gate.yml`

当前前端测试基线证据：

1. 前端共有 `34` 个测试文件。
2. 当前全量测试为 `67` 个测试。
3. 当前 smoke / visual gate 已覆盖 `11` 条基线、`9` 个高价值页面入口或关键状态。

结论：

`Phase 6` 不是只做了页面视觉推广，而是把更多页面拉进了统一组件口径和统一回归纪律。

---

## 4. 当前残留清单

以下残留点已经不适合继续通过“顺手推广”处理，应作为后续专项候选单独评估。

### 4.1 页面级旧视觉入口仍有少量残留

当前运行时代码里，页面层明确还保留的 `glass-card` 直写残留点主要是：

1. `frontend/src/pages/ops-v21-overview-page.tsx`

这说明：

- `Phase 6` 已经把大部分推广页拉回统一基线
- 但 `overview` 这类仍在主链路中的老页，还需要单独立题处理

### 4.2 共享兼容类仍未完全退休

当前共享组件层仍保留 `glass-card` 兼容类入口：

1. `frontend/src/shared/ui/section-card.tsx`
2. `frontend/src/shared/ui/stat-card.tsx`
3. `frontend/src/shared/ui/auth-page-layout.tsx`

这不是本轮阻塞问题，但说明：

- 当前视觉兼容层仍存在
- 后续若要真正清理旧视觉遗留，应单独立题，而不是在页面推广时顺手拆

### 4.3 多个页面仍然明显偏厚

按当前仓库代码统计，以下页面体量仍明显偏大：

1. `frontend/src/pages/ops-v21-task-auto-tab.tsx`：`1618` 行
2. `frontend/src/pages/ops-v21-task-manual-tab.tsx`：`1134` 行
3. `frontend/src/pages/ops-v21-review-board-page.tsx`：`920` 行
4. `frontend/src/pages/ops-v21-account-page.tsx`：`851` 行
5. `frontend/src/pages/ops-task-detail-page.tsx`：`838` 行

这些页面说明：

- 推广并不等于重构完成
- 后续若要继续提升可维护性，应转入“大页控厚 / 局部拆分”专项，而不是继续按批次推广思路推进

### 4.4 smoke 覆盖仍然不是全量

当前仍未进入 smoke / visual gate 的高可见页面包括：

1. `platform-check-page.tsx`
2. `user-overview-page.tsx`
3. `ops-v21-account-page.tsx`
4. `ops-v21-source-page.tsx`
5. `ops-v21-dataset-detail-page.tsx`

这并不代表当前阶段失败，而是说明：

- `Phase 6` 有意控制了 fixture 膨胀
- 下一步如果要继续加固，应按价值继续补 smoke，而不是平均铺开

---

## 5. 结论判断

当前判断：

1. `Phase 6` 第一轮规模化推广已完成。
2. 继续沿用“批次推广”模式的边际收益正在下降。
3. 下一步更合适的方向，不是马上开启第二轮大范围推广，而是从残留清单里挑专项。

不建议的下一步：

1. 继续一口气拉更多页面进入推广批。
2. 把大页控厚、视觉兼容层清理和 smoke 扩面混成一轮。
3. 为了追求统一视觉，再开启无边界页面修改。

更建议的下一步：

1. `专项 A`：`ops-v21-overview-page.tsx` 收口与旧视觉遗留清理。
2. `专项 B`：超大页控厚与局部拆分评估。
3. `专项 C`：高可见但仍未进入 smoke 的页面，按价值继续补最小视觉门禁。

---

## 6. 建议出场条件

若后续准备进入下一阶段，建议至少遵守：

1. 不再把“页面推广”当作默认动作。
2. 新任务先判断属于：
   - 页面推广
   - 大页控厚
   - 旧视觉兼容层清理
   - smoke 扩面
3. 仍然沿用边界卡与统一回归档位，不回到口头约定。

结论：

`Phase 6` 当前可以视为已完成第一轮收口，后续应从“批次推广”切换到“专项治理 + 有依据扩面”。
