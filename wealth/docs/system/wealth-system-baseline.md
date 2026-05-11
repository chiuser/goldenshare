# 财势乾坤行情系统基线

## 定位

财势乾坤行情系统是基于 goldenshare 数据基座建设的独立业务前端项目。

它不是现有运营后台的一个页面，也不是 `frontend/` 工程内的子模块。

## 工程边界

```text
goldenshare/
  wealth/      # 财势乾坤行情系统前端
  frontend/    # 运营后台前端
  src/         # 后端数据基座、ops、biz、app
```

`wealth` 与 `frontend` 的关系：

- 同仓管理
- 独立工程
- 独立依赖
- 独立构建
- 独立测试
- 独立设计体系

## 首期范围

首期已完成并进入模块化真实 API 接入阶段的内容：

1. 独立工程骨架。
2. 本地文档基线。
3. 市场总览页面高保真实现。
4. 本地 mock adapter 与模块级真实 API 渐进替换机制。
5. smoke 测试与模块级真实 API 测试。

当前仍不做：

1. 运营后台集成。
2. 用户体系改造。
3. 财势乾坤其它页面。
4. 交易建议、仓位建议、明日预测。
5. 未评审模块的真实 API 临时接入。

## 首期页面

```text
财势乾坤 / 乾坤行情 / 市场总览
```

规划路由：

```text
/market/overview
```

真实 API 命名空间：

```http
GET /api/v1/wealth/market/{module}
```

整页聚合接口若后续需要恢复，必须单独设计与评审，不能复用早期 `/api/market/home-overview` 口径。

## 外部资料基线

当前本地基线来自 Drive 中的以下材料：

| 类型 | Drive 路径 |
|---|---|
| Codex 提示词 | `财势乾坤/codex/market-overview-codex-prompt-v1.md` |
| Showcase | `财势乾坤/showcase/market-overview-v1.1.html` |
| 页面设计 | `财势乾坤/设计/02-market-overview-page-design.md` |
| Design Token | `财势乾坤/设计/03-design-tokens.md` |
| 组件规范 | `财势乾坤/设计/04-component-guidelines.md` |
| 数据字典 | `财势乾坤/数据字典与API文档/p0-data-dictionary-v0.4/v0.5.md`（历史参考，不作为实现契约） |
| API 草案 | `财势乾坤/数据字典与API文档/market-overview-api-v0.4/v0.5.md`（历史参考，不作为实现契约） |

当前 API 与数据模型实现契约以 `wealth/docs/pages/market-overview/**` 的模块三件套和 `wealth/docs/system/**` 为准。

## 当前拍板结论

1. 工程目录名：`wealth`。
2. 技术栈：React + TypeScript + Vite。
3. 首期只做市场总览 homepage。
4. 已完成真实接入的模块继续走真实 API；未接入模块可保留 mock。
5. 后端 API 命名空间统一为 `/api/v1/wealth/market/{module}`。
6. Drive 文档需要落成本地文档基线。
