# 市场总览｜新闻弹窗阅读器视觉与安全基线 v2

> 稳定文档路径沿用 `market-news-reader-implementation-design-v1.md`，正文版本升级为 v2。
> 状态：现有阅读器已开发并经过用户验收；双来源合同扩展已开发完成，待用户部署与页面验收。
> 视觉依据：Figma `RADlZzREU4lPVviYfkLy6x`，`13 News Reader - Components and States`（node `876:2`）。
> 数据源与 API 方案：[market-news-implementation-design-v1.md](./market-news-implementation-design-v1.md)。
> 代码级改造：[market-news-reader-low-level-design-v1.md](./market-news-reader-low-level-design-v1.md)。

## 1. 本文职责

本文只保留新闻弹窗阅读器已经确认的视觉、交互和安全合同。新闻列表来源、接口、字段、排序和 source-specific 正文策略全部由主技术方案与 LLD 定义，本文不再重复一套可能冲突的数据规则。

## 2. 已验收的阅读器合同

1. 仅实现 PC Web，不实现移动端。
2. 使用原生 modal dialog；弹窗打开后获得焦点，背景不可点击。
3. 支持 loading、ready、empty、error。
4. 支持右上角关闭按钮、Escape 关闭、关闭后焦点返回原新闻 item。
5. 弹窗打开时锁定背景滚动，关闭或组件卸载时恢复。
6. 标题和“时间 + 来源”居中展示，长标题自然换行。
7. URL 模式使用受限 sandbox iframe。
8. HTML 模式必须经过 DOMPurify 固定 allowlist 清洗。
9. TEXT 模式只使用 React 文本节点，不解释为 HTML。
10. 正文最大 256 KiB；超限、非法或缺失时显示受控状态，不泄露 SQL、路径或堆栈。
11. 列表定时刷新不得关闭、替换或重置已经打开的阅读器。

HTML 来源容错固定为：进入 DOMPurify 前仅移除源站不规范的自闭合 `<iframe .../>`。`iframe` 本来就不在 allowlist 中；预处理的目的只是防止浏览器把其后的正常正文误解析为 iframe 子内容，并不开放 iframe、属性或外部页面加载能力。规范闭合的 iframe 仍由 DOMPurify 删除，URL/TEXT 模式不经过该预处理。

## 3. 来源相关新增口径

阅读器继续支持 URL、HTML、TEXT 三种渲染器，但正文选择不再使用全局统一优先级：

| `contentSource` | 正文选择 | 原文 URL |
|---|---|---|
| `news` | `content` 按 URL > HTML > TEXT 识别 | 无独立原文 URL |
| `major_news` | 数据库 `content` 按 HTML > TEXT 识别 | `url` 仅保存在 `originalUrl`，不加载、不显示、不跳转 |

弹窗组件不自行判断来源、不自行判断正文类型。后端返回唯一 `readerMode` 与互斥载荷，feature adapter 校验合同后再交给 shared reader。

## 4. 不变边界

本轮不修改弹窗尺寸、header 布局、标题样式、正文宽度、关闭图标、动画、Design Token、HTML allowlist 或 iframe sandbox。若未来需要展示“查看原文”，必须单独设计并评审，不得因为 API 已保留 `originalUrl` 就直接增加链接。
