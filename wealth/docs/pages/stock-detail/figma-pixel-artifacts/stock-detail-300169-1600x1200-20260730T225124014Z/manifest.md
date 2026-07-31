# 股票详情页 M0 Capture Manifest

## Capture 身份

| 项目 | 值 |
| --- | --- |
| capture id | `stock-detail-300169-1600x1200-20260730T225124014Z` |
| URL | `http://127.0.0.1:5173/wealth/market/stock/300169.SZ` |
| 样本股票 | `300169.SZ`，天晟新材 |
| captured at | `2026-07-30T22:51:51.067Z` |
| 页面状态 | `readyState=complete`，存在 `.stock-detail-app`，未发现 `.stock-detail-state-panel` |
| viewport | `1600 x 1200` CSS px |
| device pixel ratio | `1` |
| 默认态 | 日 K、`MA`、右侧 `盘口`，无 hover、tooltip 或 focus ring |

## 取证方法与可信边界

1. 通过 in-app Chromium 的原生 viewport 能力设置 `1600 x 1200` 后重新加载页面，得到本次 `full-page.png`。
2. `full-page.png` 是唯一的默认态全页源图。所有模块图均从它裁切，且每个裁切矩形记录在 `crop-specs.json`。
3. 模块裁切使用本地 CoreGraphics 裁切器执行；裁切前后均核对来源与目标的左上、右下像素，避免把浏览器裁切原点问题带入产物。
4. 直接调用浏览器 `Page.captureScreenshot({ clip })` 时，非零 `clip.y` 仍会错误地从页面顶部输出，故该路径的模块截图一律不采信。
5. `kline-hover-full.png` 是使用原生浏览器输入触发十字线后的完整可见截图；对应的 DOM 边界与文本记录在 `interactions/kline-hover.json`。
6. `mouse-leave-probe.json` 是阻塞证据，不是通过证据：两条原生输入路径都到达了图表外的工具栏，但未产生 `mouseout`、`pointerout`、`mouseleave` 或 `pointerleave`。
7. 用户随后以真实鼠标移出图表区，浏览器 DOM 确认 tooltip、十字线和日期标签均不存在；证据保存为 `interactions/mouse-leave.json` 与 `interactions/mouse-leave-full.png`。该状态截图的 viewport 是 `761 x 800`，仅证明交互元素消失，不能替代本 manifest 中 `1600 x 1200` 的默认态尺寸和施工量测。

## 默认态产物

| 产物 | 尺寸或范围 | SHA-256 |
| --- | --- | --- |
| `full-page.png` | `1600 x 1200` | `207a43ddcf331af0aca3490c337370889bd51e9cbdecd307a8eb9bf5f8f531e9` |
| `dom-geometry.json` | 页面、四区图表及 Canvas 坐标 | `bf9e323c147638d99c4865ae249a303308693cf3489b5015a0c09c46df5ccc6e` |
| `computed-styles.json` | 模块 CSS 计算值 | `00016ea410ea663163a10a5d96b0dd5b5ea376036f8ff524399b0e2854c63553` |
| `crop-specs.json` | 模块裁切矩形 | `2403aff7045e971f8b5b2f628ac1406da80eb9cc28897e0e906d264b552c7d22` |

| 模块 | 文件 | 源图矩形（CSS px） | SHA-256 |
| --- | --- | --- | --- |
| TopMarketBar | `modules/top-market-bar.png` | `0,0,1600,56` | `bd7e750eeac2b4ca7a4d44840ec4b5a1f7f03a8bfeab5d1159283cf21fa3010c` |
| 面包屑行动条 | `modules/breadcrumb-action-bar.png` | `0,56,1600,42` | `2482813b28dbb4c4f31f519081cc85f3ed0846fb5e7394042776e91f02fd551b` |
| 图表工具栏 | `modules/chart-toolbar.png` | `0,98,1600,44` | `459fc61723baa20134417aead7b32ea06c36f50fbeb07c948124392ce7b631f2` |
| 图表工作台 | `modules/chart-workbench.png` | `10,152,1193,1038` | `b91c844998b032892fddc7dd8067faafdd21a143650f232135fa9c0ac27ab5b6` |
| K 线主图 | `modules/chart-kline.png` | `11,153,1191,464` | `733841ac31f507dd2ac7509498e4fc0ae8f4c31c353679c6444b579a7b109f46` |
| MACD | `modules/chart-macd.png` | `11,617,1191,179` | `bb6560f102d30a4ac1d31af40b5b274a0748fd6e0dc991c51ad46ffcbe0dfa22` |
| 成交量 | `modules/chart-volume.png` | `11,796,1191,179` | `782eaa205dbdd97f06d26f70baa7493c5a83beb660c2d981208759c9ed5baa37` |
| KDJ | `modules/chart-kdj.png` | `11,975,1191,179` | `1015e6bff0973ada7a88b1a060e97c4d1473521074564c7dab6170185f7b0853` |
| 底部指标栏 | `modules/indicator-bar.png` | `11,1155,1191,34` | `7faa72977bc36b50a3949ecca1e203fe77fe3e877c4aff6575d317fe06f4f4c8` |
| 右侧信息栏 | `modules/info-rail.png` | `1213,152,377,1038` | `2efbb9c76452f01edb930d149ac1bb612d415dcb7bc33533fbad6025e996bf62` |

## 交互产物

| 状态 | 文件 | 结果 | SHA-256 |
| --- | --- | --- | --- |
| K 线 hover | `interactions/kline-hover-full.png`、`interactions/kline-hover.json` | 通过。十字线纵向贯穿四区，底部日期标签与 K 线 tooltip 均可见。 | `cea9bfeee1ee05439b2094c0d54a55d7d23bf81bc740aef6caf2b066faaf4ef8` / `bd6d1e1e0680f8e98ed58d5988137775dccc7ad75a27d135a24a889ec9b781b5` |
| 鼠标离开图表 | `interactions/mouse-leave.json`、`interactions/mouse-leave-full.png` | 通过。用户真实移出图表区后，tooltip、十字线和日期标签均不存在。该状态仅验证可见性，几何继续使用默认态 `1600 x 1200` 基线。 | `c8d71fe8916d589ee0ecbc7bde3b1a4028368a4c77c0bb22cc533df7d26a0bac` |

## M0 结论

默认 loaded、模块裁切、DOM/CSS 量测、K 线 hover 与 mouse leave 消失态均已可复查。`CAPTURE_MOUSE_LEAVE_UNREPRODUCIBLE` 的自动化限制仍存在，但已由真实用户操作及其 DOM/screenshot 证据覆盖，不再阻塞施工。依照执行计划，M0 通过，允许进入 M1；本轮尚未创建或修改任何 Figma 节点。
