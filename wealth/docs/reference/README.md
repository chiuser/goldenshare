# Drive 原始资料本地索引

本目录保存“财势乾坤”Google Drive 资料的本地原始拷贝。

这些文件不是工程实现方案，而是设计、产品、API、Showcase、Logo 与评审资料的本地原始记录入口。后续实现市场总览 homepage 时，必须先读取这些参考资料，再写实现方案。

## 资料来源

Drive 根目录：

```text
财势乾坤
folder_id: 1229F69PQHtu8Zh7VUiXVOFhVamqlH28g
```

## 目录结构

```text
reference/
  system/       # 项目总说明、公共区规则
  product/      # 产品需求
  design/       # 页面设计、design token、组件规范
  api/          # 数据字典与 API 草案
  brand/logo/   # Logo 与品牌图片原始素材
  codex/        # Codex 落地提示词
  showcase/     # HTML Showcase 还原基线
  review/       # HTML review 与变更单
```

## 本地资料清单

| Drive 路径 | 本地路径 | 用途 |
|---|---|---|
| `财势乾坤/项目总说明/财势乾坤行情软件项目总说明_v_0_2.md` | `system/财势乾坤行情软件项目总说明_v_0_2.md` | 系统定位、项目边界 |
| `财势乾坤/项目总说明/财势乾坤公共区使用规范_v_0_3.md` | `system/财势乾坤公共区使用规范_v_0_3.md` | Drive 公共区协作规则 |
| `财势乾坤/产品文档/市场总览产品需求文档 v0.2.md` | `product/市场总览产品需求文档 v0.2.md` | 市场总览产品需求当前版本 |
| `财势乾坤/产品文档/市场总览产品需求文档_v_0_1.md` | `product/市场总览产品需求文档_v_0_1.md` | 市场总览产品需求历史版本 |
| `财势乾坤/设计/02-market-overview-page-design.md` | `design/02-market-overview-page-design.md` | 市场总览页面设计 |
| `财势乾坤/设计/03-design-tokens.md` | `design/03-design-tokens.md` | 视觉 token 与硬约束 |
| `财势乾坤/设计/04-component-guidelines.md` | `design/04-component-guidelines.md` | 组件职责与交互规范 |
| `财势乾坤/数据字典与API文档/p0-data-dictionary-v0.4.md` | `api/p0-data-dictionary-v0.4.md` | P0 数据字典 |
| `财势乾坤/数据字典与API文档/market-overview-api-v0.4.md` | `api/market-overview-api-v0.4.md` | 市场总览 API 草案 |
| `财势乾坤/Logo/*` | `brand/logo/*` | Logo 与品牌图片原始素材 |
| `财势乾坤/codex/market-overview-codex-prompt-v1.md` | `codex/market-overview-codex-prompt-v1.md` | Codex 实现边界与验收 |
| `财势乾坤/showcase/market-overview-v1.1.html` | `showcase/market-overview-v1.1.html` | homepage 高保真还原最高优先级 |
| `财势乾坤/showcase/market-overview-v1.html` | `showcase/market-overview-v1.html` | Showcase 历史版本 |
| `财势乾坤/review/market-overview-html-review-v1.pdf` | `review/market-overview-html-review-v1.pdf` | Review v1 PDF |
| `财势乾坤/review/market-overview-html-review-v2.md` | `review/market-overview-html-review-v2.md` | Review v2 修改要求 |
| `财势乾坤/review/市场总览html_review_v_1_总控解读与变更单.md` | `review/市场总览html_review_v_1_总控解读与变更单.md` | Review v1 总控说明 |
| `财势乾坤/review/市场总览html_review_v_2_总控解读与变更单.md` | `review/市场总览html_review_v_2_总控解读与变更单.md` | Review v2 总控说明 |

## 使用规则

1. `showcase/market-overview-v1.1.html` 是 homepage 还原的最高优先级资料。
2. `design/03-design-tokens.md` 与 `design/04-component-guidelines.md` 是视觉与组件实现的硬约束。
3. `api/` 目录只作为首期 mock contract 的来源，本阶段不接真实 API。
4. 任何与用户最新指令冲突的旧路径或旧命名，都必须先列为待拍板项，不得擅自沿用。
5. 不允许为了“更好看”或“更工程化”偏离 Showcase 的布局、模块顺序、密度与交互。
6. 历史版本若无当前实现价值可从本地仓库移除；当前实现默认以 v1.1 Showcase、v0.4 API/数据字典、v2 review 为准。
