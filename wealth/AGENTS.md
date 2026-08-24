# AGENTS.md - wealth 财势乾坤行情系统前端规则

## 适用范围

本文件适用于 `wealth/` 目录及其所有子目录。

`wealth` 是财势乾坤行情系统的独立前端工程。它与现有 `frontend/` 运营后台同仓，但不是同一个前端项目，不共享运营后台的 Shell、路由、页面结构或视觉体系。

---

## 当前定位

```text
wealth/
  docs/
    reference/
    system/
    pages/
  src/
    app/
    shared/
    features/
    pages/
    styles/
```

- `wealth` 负责财势乾坤行情系统前端。
- 当前主线是“乾坤行情 / 市场总览”页面按模块逐步接入真实后端 API。
- 已完成真实接入的模块继续保持真实 API；未完成模块才允许保留 mock。
- 新模块必须按“交付事实链 + 模块级渐进替换”流程推进，禁止参考旧聚合 API 直接编码。交付事实链不按文档数量考核，完整 Figma 可承担视觉/交互基准，implementation design 负责业务与架构，LLD 必须内嵌编码门禁矩阵。

### 视觉事实优先级

发生视觉、组件或交互冲突时，必须按以下顺序处理：

1. 用户最新明确指令。
2. 当前实际页面的 DOM、CSS、共享组件与已验证交互行为。
3. `wealth/docs/system/design-system-baseline.md` 与 `component-guidelines-baseline.md`。
4. 当前评审通过的 Figma、页面级设计文档、implementation design、LLD 与验收账本。
5. `wealth/docs/reference/**` 的历史 HTML、Design、Showcase 和组件集合页。

当前代码/CSS 是页面还原的第一事实源。历史资料只能用于补足未覆盖状态和设计意图，不能覆盖当前页面的尺寸、布局、样式、组件边界、数据模型或 API 契约。

---

## 动代码前必读

每次进入 `wealth` 开发前，必须先读：

1. `wealth/docs/README.md`
2. `wealth/docs/reference/README.md`
3. `wealth/docs/system/wealth-system-baseline.md`
4. `wealth/docs/system/engineering-architecture.md`
5. `wealth/docs/system/module-incremental-delivery-spec-v1.md`
6. `wealth/docs/system/module-delivery-checklist-v1.md`
7. `wealth/docs/system/design-system-baseline.md`
8. `wealth/docs/system/component-guidelines-baseline.md`
9. `wealth/docs/system/exception-code-registry.md`
10. `wealth/docs/system/strategy-config-center-v1.md`
11. `wealth/docs/system/strategy-config-center-m1-coding-gate-v1.md`
12. `wealth/docs/system/strategy-config-consumer-guide-v1.md`
13. `wealth/docs/pages/market-overview/market-overview-baseline.md`
14. `wealth/docs/pages/market-overview/api-contract-baseline.md`
15. `wealth/docs/pages/market-overview/implementation-prompt-baseline.md`
16. `wealth/docs/pages/market-overview/implementation-architecture-v1.md`
17. `wealth/docs/pages/market-overview/market-overview-api-model-design-v1.md`
18. `wealth/docs/pages/market-overview/market-summary-benchmark-requirement-v1.md`
19. `wealth/docs/pages/market-overview/market-summary-implementation-design-v1.md`
20. `wealth/docs/pages/market-overview/market-summary-m2-coding-gate-v1.md`
21. `wealth/docs/pages/market-overview/leaderboard-benchmark-requirement-v1.md`
22. `wealth/docs/pages/market-overview/leaderboard-implementation-design-v1.md`
23. `wealth/docs/pages/market-overview/leaderboard-m2-coding-gate-v1.md`
24. `wealth/docs/pages/market-overview/major-indices-benchmark-requirement-v1.md`
25. `wealth/docs/pages/market-overview/major-indices-implementation-design-v1.md`
26. `wealth/docs/pages/market-overview/major-indices-m2-coding-gate-v1.md`
27. `wealth/docs/pages/market-overview/breadth-benchmark-requirement-v1.md`
28. `wealth/docs/pages/market-overview/breadth-implementation-design-v1.md`
29. `wealth/docs/pages/market-overview/breadth-m2-coding-gate-v1.md`
30. `wealth/docs/pages/market-overview/market-style-benchmark-requirement-v1.md`
31. `wealth/docs/pages/market-overview/market-style-implementation-design-v1.md`
32. `wealth/docs/pages/market-overview/market-style-m2-coding-gate-v1.md`
33. `wealth/docs/pages/market-overview/turnover-benchmark-requirement-v1.md`
34. `wealth/docs/pages/market-overview/turnover-implementation-design-v1.md`
35. `wealth/docs/pages/market-overview/turnover-minute-snapshot-plan-v1.html`
36. `wealth/docs/pages/market-overview/turnover-minute-snapshot-m2-coding-gate-v1.md`
37. `wealth/docs/pages/market-overview/turnover-m2-coding-gate-v1.md`
38. `wealth/docs/pages/market-overview/money-flow-benchmark-requirement-v1.md`
39. `wealth/docs/pages/market-overview/money-flow-implementation-design-v1.md`
40. `wealth/docs/pages/market-overview/money-flow-m2-coding-gate-v1.md`
41. `wealth/docs/pages/market-overview/streak-ladder-benchmark-requirement-v1.md`
42. `wealth/docs/pages/market-overview/streak-ladder-implementation-design-v1.md`
43. `wealth/docs/pages/market-overview/streak-ladder-m2-coding-gate-v1.md`
44. `wealth/docs/pages/market-overview/market-news-implementation-design-v1.md`
45. `wealth/docs/pages/market-overview/market-news-reader-implementation-design-v1.md`
46. `wealth/docs/pages/market-overview/market-news-reader-low-level-design-v1.md`
47. `wealth/docs/templates/benchmark-requirement-template.md`
48. `wealth/docs/templates/implementation-design-template.md`
49. `wealth/docs/templates/coding-gate-template.md`
50. `wealth/docs/pages/market-overview/sector-overview-benchmark-requirement-v2.md`
51. `wealth/docs/pages/market-overview/sector-overview-implementation-design-v2.md`
52. `wealth/docs/pages/market-overview/sector-overview-m2-coding-gate-v2.md`
53. `wealth/docs/pages/market-overview/sector-overview-low-level-design-v2.md`
54. 当前目标目录中的更近 `AGENTS.md`（如未来新增）

实现市场总览 homepage 前，还必须额外读取当前 `src/pages/market-overview/**`、`src/features/market-overview/**`、`src/shared/ui/top-market-bar/**` 与 `src/styles/**`。以下原始资料只在需要追溯视觉意图或历史评审时按需读取：

1. `wealth/docs/reference/showcase/market-overview-v4.html`
2. `wealth/docs/reference/design/03-design-tokens-v0.2.7.md`
3. `wealth/docs/reference/design/04-component-guidelines-v0.7.md`
4. `wealth/docs/reference/codex/market-overview-codex-prompt-v1.md`
5. `wealth/docs/reference/review/market-overview-html-review-v2.md`
6. `wealth/docs/reference/review/市场总览html_review_v_2_总控解读与变更单.md`

如果上述文档与用户最新指令冲突，先停下说明冲突，不要擅自猜。

注意：`wealth/docs/reference/api/**` 不在 homepage 开发必读清单中。只有做历史追溯时才读取，读取后也不得作为当前 API 或数据模型依据。

实现股票详情页前，还必须额外读取当前 `src/pages/stock-detail/**`、`src/features/stock-detail/**`、`src/shared/ui/top-market-bar/**` 与 `src/styles/**`。以下原始资料只在需要追溯视觉意图或历史评审时按需读取：

1. `wealth/docs/pages/stock-detail/stock-detail-benchmark-requirement-v1.md`
2. `wealth/docs/pages/stock-detail/stock-detail-implementation-design-v1.md`
3. `wealth/docs/pages/stock-detail/stock-detail-m2-coding-gate-v1.md`
4. `wealth/docs/update/stock-detail-v1.4.3.html`
5. `wealth/docs/update/03-design-tokens.md`
6. `wealth/docs/update/04-component-guidelines.md`
7. `wealth/docs/reference/showcase/component-library-demo-v2.2.html`

股票详情页的顶部 `TopMarketBar` 必须完全复用市场总览页当前顶部栏。实现前必须先把当前 `TopMarketBar` 抽象为 shared 组件，并保证市场总览与股票详情页消费同一个组件；禁止复制、重写或引入第二套顶部栏。

---

## 技术基线

- React + TypeScript + Vite。
- 独立 `package.json`、独立构建、独立测试。
- 默认路由首期规划为 `/market/overview`。
- 真实 API 命名空间统一为 `/api/v1/wealth/market/{module}`；整页聚合接口如需恢复，必须单独设计并评审。
- 模块真实 API 已接入后，前端不得回退到整页 mock 或旧 reference API 口径。
- `wealth/docs/reference/**` 只作为历史原始资料与视觉/产品背景参考；API、数据模型、字段映射、测试门禁必须以当前评审通过的 Figma、`wealth/docs/pages/**` implementation design/LLD 和 `wealth/docs/system/**` 当前基线为准。

---

## 工程分层

### `src/app/**`

只放应用装配：

- 根组件
- 路由装配
- Provider
- 全局错误边界
- 全局样式引入

不要把页面业务逻辑写进 `app`。

### `src/pages/**`

放页面级编排。

页面负责：

- 组织页面模块
- 消费 feature/shared 提供的数据与组件
- 处理页面级 loading / empty / error / loaded 四态

页面文件不能无限变厚。超过 400 行前必须拆分。

### `src/features/**`

放领域级页面模块和领域组合逻辑。

例如市场总览后续可放：

- summary
- indices
- breadth
- turnover
- money-flow
- leaderboards
- limit-up
- sectors

### `src/shared/**`

放跨页面共享能力：

- `api/`：请求 client、API 类型、mock adapter 基础设施
- `ui/`：通用展示组件
- `lib/`：格式化、趋势判断、数值工具
- `model/`：通用类型和值对象

共享层不能绑定具体页面布局。

### `src/styles/**`

放设计 token、主题样式、基础 reset。

颜色、间距、圆角、阴影、行情涨跌色必须通过 token 表达，不允许页面里散落魔法值。

---

## 设计与体验硬约束

1. 市场总览和股票详情页必须高保真遵循当前实际页面 CSS、组件结构与已验证交互；历史 Showcase 仅作补充参考。
2. 默认深色金融终端风。
3. A 股红涨绿跌：红色表示上涨、正值、净流入、涨停；绿色表示下跌、负值、净流出、跌停。
4. 行情色不能复用系统 success/error 语义。
5. 不做普通后台管理风格。
6. 不使用运营后台固定 SideNav。
7. 不新增主观买卖建议、仓位建议、明日预测。
8. 不展示市场温度分数、情绪指数、资金面分数、风险指数作为首页核心结论。
9. 不允许基于个人审美重排模块、删模块或重做视觉。
10. Showcase 中未确认的小瑕疵只能记录为待确认项，不得擅自改版。
11. 高保真任务必须先量测当前实际页面，再建立或更新设计稿；不能凭历史 HTML 估算尺寸或自行补全细节。
12. 任何偏离当前实际页面、Design System 或已确认页面设计的想法只能列为待拍板项，不允许直接写进代码。

---

## 数据与 API 规则

1. 前端必须通过稳定 contract 消费数据，不允许自己拼接后端事实字段。
2. mock adapter 必须遵守 `wealth/docs/pages/market-overview/api-contract-baseline.md`。
3. 字段命名统一 lowerCamelCase。
4. 禁止为了兼容旧字段新增别名字段。
5. API 未实现前，只允许 mock，不允许偷偷调用 ops 后台接口凑数据。
6. 格式化必须集中到 formatter，不允许页面各处手写金额、百分比、涨跌色规则。
7. 异常码必须在 `wealth/docs/system/exception-code-registry.md` 登记后才能进入契约和代码；禁止散落定义。
8. 本期仅榜单模块启用结构化异常码；其他模块后续分期接入，不允许提前扩散到计划外范围。
9. 后续接真实后端 API 时，`src/biz` 必须按模块目录组织（`api/queries/schemas/services` 四层都要按 `wealth/market/<module>` 分层），禁止扁平堆文件；规范见 `wealth/docs/system/engineering-architecture.md`。
10. 模块接口只返回模块对象；整页聚合对象必须独立接口与独立 DTO 文件，不允许混在模块 schema 中。
11. 禁止把 `wealth/docs/reference/api/**`、旧 Codex prompt、旧产品稿中的 `/api/market/home-overview`、`/api/moneyflow/market`、`/api/index/summary` 等旧路径作为新方案依据。
12. 旧 reference 文档出现的 `includeHistory`、旧聚合根对象、旧扁平字段，只能作为历史输入材料；进入代码前必须先在当前模块的 implementation design 或 LLD 中重新定义。

---

## 开发流程

中等及以上任务编码前必须有计划或方案，至少说明：

1. 用户任务
2. 本轮目标
3. 不做什么
4. 目录与文件计划
5. 数据 contract
6. 组件拆分
7. 状态设计
8. 验证方式

Bug 修复必须先说明原因与影响面。禁止临时补丁叠补丁。

文档门禁与变更纪律（强制）：

1. 评审通过的方案文档是编码门禁，不是“参考意见”。
2. 发现实现需要偏离已评审文档时，必须先停下，先提交偏离点与影响面，等待拍板；未拍板不得动代码。
3. 禁止“先写代码再倒改文档适配实现”。文档变更必须先于（或至少同步于）实现变更，并经过确认。
4. 任何“实现收敛后再改文档兜底”的行为，视为流程违规。

新增模块（或中等以上模块改造）必须建立并评审“交付事实链”：

1. 视觉/交互基准：优先使用完整且已评审的 Figma；Figma 必须明确页面、节点、组件、状态、交互和响应式基准。没有完整 Figma、或需求无法由 Figma 表达时，才补独立 benchmark requirement。
2. implementation design：冻结业务范围、数据/API 合同、状态、性能与架构边界。
3. LLD：细化到代码符号、调用链、组件、测试和验收，并内嵌“编码门禁矩阵”。不再强制独立 coding-gate 文件。
4. 用 `wealth/docs/system/module-delivery-checklist-v1.md` 做提交前通用检查。
5. 上述事实链评审通过后才允许编码；独立 benchmark/coding-gate 可按专项复杂度或用户要求保留，但不是固定必需产物。

交付事实链补充硬门禁（必须同时满足）：

1. 每个模块 LLD 的“编码门禁矩阵”必须逐条标注通用清单的适用/不适用、落地位置和验证方式；缺失不得开工。
2. 偏离通用清单的规则必须在 LLD 中登记模块级“例外白名单”并评审通过；未登记视为违规。
3. 关键语义（如累计值图表纵轴非负、固定刻度）必须有可执行测试断言，禁止只写文档不写测试。
4. 每个模块必须定义并落地“核心测试 case”，且进入提测前必须执行通过：
   - 后端真实 API 校验：走真实路由（非 mock service），断言页面消费所需核心字段齐全且语义正确；
   - 前端真实展示校验：前端请求真实后端 API（非 mock adapter），断言页面关键展示要素与核心字段一一对应。
5. 核心测试 case 的字段清单必须来自当前评审通过的 Figma、implementation design 和 LLD，不能临时发挥。
6. 仅有 mock 测试不允许作为模块可交付依据；mock 只能用于开发阶段占位与极端态演示。

---

## 验证要求

有效代码改动后，至少执行：

```bash
npm run typecheck
npm run test
npm run build
```

涉及页面可视行为时，还必须补 smoke 或人工浏览器检查说明。

`wealth` 模块补充验证硬约束（必须同时满足）：

1. 模块后端改动：至少通过该模块一组“真实 API 集成测试”（`tests/web/test_wealth_market_<module>_api.py` 同等粒度）。
2. 模块前端改动：至少通过该模块一组“真实 API 展示 smoke”（真实 API 响应驱动页面，而不是 mock adapter）。
3. 交付说明必须写明核心测试 case 的执行命令、覆盖字段与结果。

若某项验证暂时无法执行，必须在交付说明里写清原因。

---

## 禁止事项

1. 禁止把运营后台 `frontend` 的页面、Shell、路由直接搬入 `wealth`。
2. 禁止无计划修改后端 `src/**`；后端改动必须按模块交付事实链与 LLD 编码门禁执行。
3. 禁止整页一次性切真实 API；必须按模块级渐进替换规范逐个切换。
4. 禁止把 ops 内部状态表或 TaskRun 观测模型暴露给行情前端。
5. 禁止新增无计划功能。
6. 禁止引入重型依赖作为首期页面捷径。
7. 禁止超长文件和重复拼装。
8. 禁止写兼容方案、临时方案、旧字段别名。
9. 禁止在 `src/biz/api|queries|schemas|services` 下新增扁平 `wealth_*` 大文件来承接多个模块。

---

## 交付说明

每次 `wealth` 任务完成后，至少说明：

1. 本轮目标
2. 依据文档
3. 改动文件
4. 是否新增组件或工程规则
5. 是否影响 API contract
6. 验证结果
7. 风险与待确认项
