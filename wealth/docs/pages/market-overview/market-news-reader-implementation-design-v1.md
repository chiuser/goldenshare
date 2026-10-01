# 市场总览｜新闻弹窗阅读器视觉与安全基线 v3

> 稳定文档路径沿用 `market-news-reader-implementation-design-v1.md`，正文版本升级为 v3。
> 基线状态：已实现并结案（2026-09-01 用户确认）；阅读器视觉、安全及双来源合同均已完成。
> 图片增强状态：M1 方案已冻结（2026-10-01），尚未编码、测试、部署。
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

图片增强不修改弹窗尺寸、header 布局、标题样式、正文宽度、关闭图标、动画、Design Token 或 iframe sandbox。HTML allowlist 只按第 5 节开放经过归一化的安全图片，不开放 iframe、链接跳转、源站样式或事件属性。若未来需要展示“查看原文”，必须单独设计并评审，不得因为 API 已保留 `originalUrl` 就直接增加链接。

## 5. 图片显示与失败状态基线（M1 冻结，未实现）

1. 图片是 HTML 正文中的从属内容，不新增 reader mode、不增加图片画廊、轮播、预览层或下载入口。
2. 合规图片按正文顺序展示，最大宽度为正文容器宽度，高度自动；不得造成横向滚动或撑大 modal。
3. 浏览器使用 lazy loading 和 async decoding；请求不发送页面 referrer。
4. 单图失败不得把阅读器切到整体 error，也不得遮挡其后的文本。失败图片隐藏或显示无外链的本地占位即可。
5. 每篇最多显示 24 张图片。相对路径、未知域名和不安全 scheme 直接移除，不向用户暴露破损 URL，也不尝试访问原文页面补图。
6. 可访问性使用清洗后的源 `alt`；缺少有效 `alt` 时按装饰图片处理。禁止把文件名、URL 或 host 自动拼成替代文本。
7. DOM 最终只能保留系统生成的安全图片属性；源站的事件、样式、class、id 不能进入 DOM。

域名白名单、URL 归一化算法和测试门禁以主技术方案第 14 节及 LLD N20～N23 为准。本文只冻结用户可见结果，不另建第二套数据或安全规则。
