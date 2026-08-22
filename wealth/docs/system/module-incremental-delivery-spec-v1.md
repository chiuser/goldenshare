# wealth 模块级渐进替换开发规范 v1

## 1. 目标

本规范用于约束 `wealth` 的模块化开发节奏：  
**开发一个模块，只替换一个模块；未开发模块继续使用 mock，且保持不动。**

它解决的问题：

1. 避免整页一次性切换导致故障定位困难。
2. 保证每轮改动可观测、可回滚、可复盘。
3. 保证页面稳定性优先于开发速度。

---

## 2. 适用范围

适用于 `wealth/src/features/market-overview/**` 全部模块，尤其是：

1. `summary`
2. `indices`
3. `breadth`
4. `style`
5. `turnover`
6. `money-flow`
7. `leaderboards`
8. `limit-up`
9. `sectors`

---

## 3. 核心定义

1. **目标模块（target module）**  
   本轮唯一允许切换数据源的模块。
2. **非目标模块（non-target module）**  
   本轮必须保持 mock，不允许改行为。
3. **模块源（module source）**  
   `mock` 或 `real`，由模块级开关明确声明。
4. **静默回退（silent fallback）**  
   模块声称使用 `real`，但失败后悄悄回到 `mock`。  
   本规范下严禁。

---

## 4. 硬约束（必须遵守）

1. 每轮只允许一个目标模块切换到 `real`。
2. 非目标模块的 contract、mock 数据形态、页面行为不得改变。
3. 目标模块切到 `real` 后，失败必须走该模块 error/empty/delayed，不得自动回退 mock。
4. 禁止在同一轮中“顺手”改其他模块样式、字段、排序、交互。
5. 目标模块的交付事实链必须齐全且已评审通过：完整 Figma 或独立需求基线、implementation design、LLD 及其内嵌编码门禁矩阵。
6. 目标模块异常码必须先登记到异常码注册表，再进入代码实现。

---

## 5. 推荐实现结构（前端）

## 5.1 模块数据提供者（provider）边界

每个模块都应有独立 provider，且仅返回该模块 DTO：

```text
src/features/market-overview/<module>/api/
  <module>Provider.ts
  <module>Types.ts
```

规则：

1. provider 不负责页面拼装。
2. provider 不得读取其他模块数据。
3. provider 输出必须与模块 API 契约一一对应。

## 5.2 模块源开关

建议维护统一模块源清单（示意）：

```ts
type ModuleSource = "mock" | "real";

interface MarketOverviewModuleSources {
  summary: ModuleSource;
  majorIndices: ModuleSource;
  breadth: ModuleSource;
  style: ModuleSource;
  turnover: ModuleSource;
  moneyFlow: ModuleSource;
  leaderboards: ModuleSource;
  limitUp: ModuleSource;
  sectors: ModuleSource;
}
```

规则：

1. 每轮只改一个 key 的 source 值。
2. source 状态必须可在日志或调试信息中确认。

## 5.3 页面装配层职责

页面装配层只做：

1. 拉取各模块 provider 输出；
2. 合并成页面渲染所需 ViewModel；
3. 承担页面级状态归并。

禁止：

1. 在页面层写模块业务聚合逻辑；
2. 在页面层兜底修补模块字段；
3. 在页面层偷偷切换 mock/real。

---

## 6. 逐模块交付流程（标准步骤）

1. **步骤 A：范围冻结**  
   明确目标模块与非目标模块清单。
2. **步骤 B：交付事实链冻结**
   完成并评审目标模块的 Figma/需求基线、implementation design 与 LLD。
3. **步骤 B1：映射矩阵与例外白名单冻结**  
   在目标模块 LLD 中补齐“编码门禁矩阵”；若存在规则例外，必须登记模块级白名单并完成评审。
4. **步骤 C：实现落地**  
   仅实现目标模块 provider、模块 API 接入、模块状态处理。
5. **步骤 D：模块切换**  
   将目标模块 source 从 `mock -> real`。
6. **步骤 E：门禁验证**  
   执行模块级与页面级最小回归。
7. **步骤 F：回滚预案确认**  
   若失败，仅回滚目标模块 source 与目标模块变更。

---

## 7. 测试与验收门禁

每轮至少通过：

1. 目标模块类型检查、单元测试。
2. 目标模块四态验证：`READY/DELAYED/EMPTY/ERROR`（必要时含 `PARTIAL`）。
3. 页面 smoke：确认只有目标模块行为变化。
4. 视觉核对：非目标模块布局与样式不变。
5. 语义断言：关键业务语义必须有可执行断言（如累计值图表纵轴非负、固定刻度值等）。
6. 规则例外检查：存在例外时，必须能追溯到模块白名单条目。

若不满足以上任一项，不允许切换模块 source。

---

## 8. 失败处理与回滚规则

1. 回滚粒度：只回滚目标模块。
2. 回滚方式：
   - source 开关回滚到 `mock`；
   - 回退本轮目标模块实现提交。
3. 不允许通过“临时兼容字段”强行上线。
4. 回滚后必须补充问题记录，再进入下一轮。

---

## 9. 交付说明模板（每轮必须提供）

1. 本轮目标模块
2. 非目标模块冻结声明
3. 改动文件列表
4. 模块 source 切换前后值
5. 门禁验证结果
6. 回滚预案与触发条件

---

## 10. 与现有规范关系

1. 本文与 Figma/需求基线、implementation design、LLD 及其内嵌编码门禁配合使用，不按独立文档数量设置门槛。
2. 本文属于系统级开发流程约束，优先于模块内部“临时加速方案”。
3. 与 `engineering-architecture.md`、`exception-code-registry.md` 一起构成编码前门禁。

---

## 11. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-08 | 首版：冻结“开发一个替换一个，其余模块保持 mock 不动”流程 | Codex |
| v1.1 | 2026-05-10 | 新增步骤 B1：通用清单映射矩阵与模块例外白名单；补充语义断言测试门禁 | Codex |
| v1.2 | 2026-08-22 | 由固定“三件套”调整为交付事实链：完整 Figma 可承担 benchmark，编码门禁矩阵内嵌 LLD | Codex |
