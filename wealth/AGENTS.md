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
- 首期只落地“乾坤行情 / 市场总览”页面。
- 首期只使用 mock adapter，不接真实后端 API。
- 后端真实 API 后续单独设计，不在本阶段顺手实现。

---

## 动代码前必读

每次进入 `wealth` 开发前，必须先读：

1. `wealth/docs/README.md`
2. `wealth/docs/reference/README.md`
3. `wealth/docs/system/wealth-system-baseline.md`
4. `wealth/docs/system/engineering-architecture.md`
5. `wealth/docs/system/design-system-baseline.md`
6. `wealth/docs/system/component-guidelines-baseline.md`
7. `wealth/docs/pages/market-overview/market-overview-baseline.md`
8. `wealth/docs/pages/market-overview/api-contract-baseline.md`
9. `wealth/docs/pages/market-overview/implementation-prompt-baseline.md`
10. `wealth/docs/pages/market-overview/implementation-architecture-v1.md`
11. 当前目标目录中的更近 `AGENTS.md`（如未来新增）

实现市场总览 homepage 前，还必须额外读取：

1. `wealth/docs/reference/showcase/market-overview-v1.1.html`
2. `wealth/docs/reference/design/03-design-tokens.md`
3. `wealth/docs/reference/design/04-component-guidelines.md`
4. `wealth/docs/reference/codex/market-overview-codex-prompt-v1.md`
5. `wealth/docs/reference/review/market-overview-html-review-v2.md`
6. `wealth/docs/reference/review/市场总览html_review_v_2_总控解读与变更单.md`

如果上述文档与用户最新指令冲突，先停下说明冲突，不要擅自猜。

---

## 技术基线

- React + TypeScript + Vite。
- 独立 `package.json`、独立构建、独立测试。
- 默认路由首期规划为 `/market/overview`。
- 真实 API 命名空间规划为 `/api/v1/wealth/market/overview`。
- 首期页面数据来自本地 mock adapter，mock 结构必须贴近本地 API contract。

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

1. 市场总览必须高保真参考 `market-overview-v1.1.html`。
2. 默认深色金融终端风。
3. A 股红涨绿跌：红色表示上涨、正值、净流入、涨停；绿色表示下跌、负值、净流出、跌停。
4. 行情色不能复用系统 success/error 语义。
5. 不做普通后台管理风格。
6. 不使用运营后台固定 SideNav。
7. 不新增主观买卖建议、仓位建议、明日预测。
8. 不展示市场温度分数、情绪指数、资金面分数、风险指数作为首页核心结论。
9. 不允许基于个人审美重排模块、删模块或重做视觉。
10. Showcase 中未确认的小瑕疵只能记录为待确认项，不得擅自改版。
11. homepage 首批实现目标是高保真还原，不是重新设计；交互、布局、模块顺序、组件密度、颜色气质默认全部跟随 V1.1 Showcase。
12. 任何偏离 Showcase 或设计规范的想法只能列为待拍板项，不允许直接写进代码。

---

## 数据与 API 规则

1. 前端必须通过稳定 contract 消费数据，不允许自己拼接后端事实字段。
2. mock adapter 必须遵守 `wealth/docs/pages/market-overview/api-contract-baseline.md`。
3. 字段命名统一 lowerCamelCase。
4. 禁止为了兼容旧字段新增别名字段。
5. API 未实现前，只允许 mock，不允许偷偷调用 ops 后台接口凑数据。
6. 格式化必须集中到 formatter，不允许页面各处手写金额、百分比、涨跌色规则。

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

---

## 验证要求

有效代码改动后，至少执行：

```bash
npm run typecheck
npm run test
npm run build
```

涉及页面可视行为时，还必须补 smoke 或人工浏览器检查说明。

若某项验证暂时无法执行，必须在交付说明里写清原因。

---

## 禁止事项

1. 禁止把运营后台 `frontend` 的页面、Shell、路由直接搬入 `wealth`。
2. 禁止在本阶段修改后端 `src/**`。
3. 禁止接真实 API。
4. 禁止把 ops 内部状态表或 TaskRun 观测模型暴露给行情前端。
5. 禁止新增无计划功能。
6. 禁止引入重型依赖作为首期页面捷径。
7. 禁止超长文件和重复拼装。
8. 禁止写兼容方案、临时方案、旧字段别名。

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
