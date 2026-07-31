# Drive 原始资料本地索引

本目录保存“财势乾坤”Google Drive 资料的本地原始拷贝。

重要约束：本目录是历史原始资料区，不是当前工程契约区。`api/`、`product/`、`codex/`、早期 `design/` 文档中的旧 API 路径、旧字段结构、旧聚合模型只说明历史设计来源，后续方案设计和代码实现不得直接沿用。

这些文件不是当前工程实现方案，而是设计、产品、API、Showcase、Logo 与评审资料的本地原始记录入口。它们用于理解历史设计意图和追溯决策，不能替代当前页面实现。

当前工程的优先级是：用户最新指令 -> 当前页面 DOM/CSS/已验证交互 -> `wealth/docs/system/**` -> `wealth/docs/pages/**` -> 本目录。后续实现前，先读实际页面与系统基线；只有遇到需要追溯的视觉意图、原型状态或历史评审时才按需读取本目录。

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
| `财势乾坤/设计/03-design-tokens.md` | `design/03-design-tokens-v0.2.7.md` | 历史 token 与视觉意图参考 |
| `财势乾坤/设计/04-component-guidelines.md` | `design/04-component-guidelines-v0.7.md` | 历史组件职责与交互意图参考 |
| `财势乾坤/数据字典与API文档/p0-data-dictionary-v0.5.md` | `api/p0-data-dictionary-v0.5.md` | P0 数据字典（历史参考，不作为实现契约） |
| `财势乾坤/数据字典与API文档/market-overview-api-v0.5.md` | `api/market-overview-api-v0.5.md` | 市场总览 API 草案（历史参考，不作为实现契约） |
| `财势乾坤/Logo/*` | `brand/logo/*` | Logo 与品牌图片原始素材 |
| `财势乾坤/codex/market-overview-codex-prompt-v1.md` | `codex/market-overview-codex-prompt-v1.md` | Codex 实现边界与验收 |
| `财势乾坤/showcase/market-overview-v4.html` | `showcase/market-overview-v4.html` | homepage 历史原型参考 |
| `财势乾坤/showcase/market-overview-v1.1.html` | `showcase/market-overview-v1.1.html` | homepage 历史高保真视觉参考 |
| `财势乾坤/showcase/market-overview-v1.html` | `showcase/market-overview-v1.html` | Showcase 历史版本 |
| `财势乾坤/review/market-overview-html-review-v1.pdf` | `review/market-overview-html-review-v1.pdf` | Review v1 PDF |
| `财势乾坤/review/market-overview-html-review-v2.md` | `review/market-overview-html-review-v2.md` | Review v2 修改要求 |
| `财势乾坤/review/市场总览html_review_v_1_总控解读与变更单.md` | `review/市场总览html_review_v_1_总控解读与变更单.md` | Review v1 总控说明 |
| `财势乾坤/review/市场总览html_review_v_2_总控解读与变更单.md` | `review/市场总览html_review_v_2_总控解读与变更单.md` | Review v2 总控说明 |

## 使用规则

1. 本目录只能作为补充参考，当前页面 DOM/CSS 与已验证交互永远优先。
2. `design/` 与 `showcase/` 可以解释视觉意图、组件状态和原型细节，但不是 token、组件 API 或布局尺寸的正式来源。
3. `api/` 目录只作为历史 API/数据字典输入材料，不能作为当前实现 contract。
4. 任何与当前代码、`system/`、`pages/` 当前基线或用户最新指令冲突的旧路径、旧字段、旧 token、旧命名，都必须按当前基线修正，不得擅自沿用。
5. 不允许为了“更好看”或“更工程化”偏离已验收的当前页面；若历史 Showcase 与当前页面不一致，先记录差异并以当前页面为准。
6. 历史版本若无保留价值可在单独清理任务中移除；本轮不删除原始资料。
