# Drive 原始资料本地索引

本目录保存“财势乾坤”Google Drive 资料的本地原始拷贝。

重要约束：本目录是历史原始资料区，不是当前工程契约区。`api/`、`product/`、`codex/`、早期 `design/` 文档中的旧 API 路径、旧字段结构、旧聚合模型只说明历史设计来源，后续方案设计和代码实现不得直接沿用。

当前实现依据：

1. 工程规则：`wealth/docs/system/**`
2. 市场总览模块契约：`wealth/docs/pages/market-overview/**` 的三件套
3. 视觉高保真：当前生效 Showcase、Design Token、组件规范

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
| `财势乾坤/设计/03-design-tokens.md` | `design/03-design-tokens-v0.2.7.md` | 视觉 token 与硬约束（当前生效） |
| `财势乾坤/设计/04-component-guidelines.md` | `design/04-component-guidelines-v0.7.md` | 组件职责与交互规范（当前生效） |
| `财势乾坤/数据字典与API文档/p0-data-dictionary-v0.5.md` | `api/p0-data-dictionary-v0.5.md` | P0 数据字典（历史参考，不作为实现契约） |
| `财势乾坤/数据字典与API文档/market-overview-api-v0.5.md` | `api/market-overview-api-v0.5.md` | 市场总览 API 草案（历史参考，不作为实现契约） |
| `财势乾坤/Logo/*` | `brand/logo/*` | Logo 与品牌图片原始素材 |
| `财势乾坤/codex/market-overview-codex-prompt-v1.md` | `codex/market-overview-codex-prompt-v1.md` | Codex 实现边界与验收 |
| `财势乾坤/showcase/market-overview-v4.html` | `showcase/market-overview-v4.html` | homepage 还原当前生效原型 |
| `财势乾坤/showcase/market-overview-v1.1.html` | `showcase/market-overview-v1.1.html` | homepage 高保真还原最高优先级 |
| `财势乾坤/showcase/market-overview-v1.html` | `showcase/market-overview-v1.html` | Showcase 历史版本 |
| `财势乾坤/review/market-overview-html-review-v1.pdf` | `review/market-overview-html-review-v1.pdf` | Review v1 PDF |
| `财势乾坤/review/market-overview-html-review-v2.md` | `review/market-overview-html-review-v2.md` | Review v2 修改要求 |
| `财势乾坤/review/市场总览html_review_v_1_总控解读与变更单.md` | `review/市场总览html_review_v_1_总控解读与变更单.md` | Review v1 总控说明 |
| `财势乾坤/review/市场总览html_review_v_2_总控解读与变更单.md` | `review/市场总览html_review_v_2_总控解读与变更单.md` | Review v2 总控说明 |

## 使用规则

1. `showcase/market-overview-v1.1.html` 是 homepage 还原的最高优先级资料。
2. `design/03-design-tokens.md` 与 `design/04-component-guidelines.md` 是视觉与组件实现的硬约束。
3. `api/` 目录只作为历史 API/数据字典输入材料，不能作为当前实现 contract。
4. 任何与 `system/`、`pages/` 当前基线或用户最新指令冲突的旧路径、旧字段、旧命名，都必须按当前基线修正，不得擅自沿用。
5. 不允许为了“更好看”或“更工程化”偏离 Showcase 的布局、模块顺序、密度与交互。
6. 历史版本若无当前实现价值可从本地仓库移除；当前实现默认以 v4 Showcase、v0.2.7 Token、v0.7 组件规范作为视觉/组件参考，以 `pages/` 模块三件套作为 API/数据模型事实源。
