# 市场总览 Codex 实现提示词基线

## 来源

本基线来自 Drive：

```text
财势乾坤/codex/market-overview-codex-prompt-v1.md
```

## 本地化调整

Drive 原提示词中的“现有前端项目”已按用户最新决策修正为：

```text
在仓库根目录 wealth/ 中实现独立财势乾坤行情系统前端工程。
```

因此后续实现不得进入现有运营后台 `frontend/`。

## 执行总原则

目标是在 `wealth` 工程中实现“财势乾坤 / 乾坤行情 / 市场总览”页面。

这不是视觉重设计任务，也不是静态 HTML 复制任务。

页面实现必须工程化承接 `market-overview-v1.1.html`：

- 视觉
- 布局
- 模块顺序
- 数据密度
- 核心交互
- 状态表达

## 必读本地文件

实现市场总览前必须读取：

1. `wealth/AGENTS.md`
2. `wealth/docs/system/wealth-system-baseline.md`
3. `wealth/docs/system/engineering-architecture.md`
4. `wealth/docs/system/design-system-baseline.md`
5. `wealth/docs/system/component-guidelines-baseline.md`
6. `wealth/docs/pages/market-overview/market-overview-baseline.md`
7. `wealth/docs/pages/market-overview/api-contract-baseline.md`
8. `wealth/docs/pages/market-overview/implementation-prompt-baseline.md`

## 首期实现目标

1. 在 `wealth` 中实现市场总览页面。
2. 使用本地 mock adapter，不接真实 API。
3. 路由规划为 `/market/overview`。
4. mock contract 对齐 `/api/v1/wealth/market/overview`。
5. 高保真参考 `market-overview-v1.1.html`。
6. 保证红涨绿跌。
7. 覆盖 loading / empty / error / data delayed / loaded。
8. 补最小 smoke 测试。

## 不做事项

1. 不接真实后端。
2. 不修改 `src/**` 后端。
3. 不修改现有 `frontend/**`。
4. 不复用运营后台 Shell。
5. 不引入固定 SideNav。
6. 不新增交易建议。
7. 不发明新模块。
8. 不等待 v1.2。

## 验收清单

1. 页面可打开。
2. 页面无白屏。
3. 控制台无明显错误。
4. 页面标题为“市场总览”。
5. 页面归属为“财势乾坤 / 乾坤行情 / 市场总览”。
6. 无固定 SideNav。
7. TopMarketBar 正确。
8. Breadcrumb 正确。
9. ShortcutBar 正确。
10. 今日市场客观总结与主要指数左右结构正确。
11. 今日市场客观总结为 5 个事实卡 + 说明卡。
12. 主要指数为 2 行 x 5 列。
13. 榜单 Top10 正确。
14. 榜单列顺序正确。
15. 涨跌停统计与分布 2 x 2 正确。
16. 板块速览左侧 4 x 2 榜单矩阵正确。
17. 板块热力图右侧跨两行，内部 5 x 4。
18. 红涨绿跌正确。
19. 未展示禁止字段。
20. mock 数据稳定。
