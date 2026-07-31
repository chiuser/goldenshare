# 股票详情页 Figma 像素级还原验收台账 v1

**状态：M0-M7 通过；`STRUCTURE_AND_VISUAL_BASELINE_VERIFIED`。** 2026-07-31 的人工视觉复核发现 KDJ 时间轴曾错误使用实心填充；该 `FIGMA_CONSTRUCTION_DEFECT` 已按实际 CSS 渐变修复并复核。本台账只记录已核验的真实取证与 Figma 施工结果；几何施工与交互可见性证据按各自适用视口登记，不混用。

## 0. 最新 Capture Run

| 项目 | 值 |
| --- | --- |
| capture id | `stock-detail-300169-1600x1200-20260730T225124014Z` |
| 页面地址 | `http://127.0.0.1:5173/wealth/market/stock/300169.SZ` |
| 页面状态 | 已登录、`readyState=complete`、loaded；未检测到 `.stock-detail-state-panel` |
| 样本股票 | `300169.SZ`，天晟新材 |
| viewport | `1600 x 1200` CSS px，DPR `1` |
| 默认主图 / tab | `MA` / `盘口` |
| DOM 量测时间 | `2026-07-30T22:51:51.067Z` |
| mouse leave 取证 | `2026-07-30T23:45:50.912Z`；真实用户鼠标操作；`761 x 800` viewport；仅验证交互元素消失，不替代 `1600 x 1200` 几何基线 |

有效产物位于 [figma-pixel-artifacts/stock-detail-300169-1600x1200-20260730T225124014Z](figma-pixel-artifacts/stock-detail-300169-1600x1200-20260730T225124014Z)。其 [manifest.md](figma-pixel-artifacts/stock-detail-300169-1600x1200-20260730T225124014Z/manifest.md) 记录哈希、模块裁切和可信边界；[measurement.md](figma-pixel-artifacts/stock-detail-300169-1600x1200-20260730T225124014Z/measurement.md) 记录 Figma 施工所需的固定几何锚点。

## 1. Capture 身份

| 项目 | 值 |
| --- | --- |
| capture id | `stock-detail-300169-1600x1200-20260730T155157719Z` |
| 页面地址 | `http://127.0.0.1:5173/wealth/market/stock/300169.SZ` |
| 页面状态 | 已登录、`readyState=complete`、loaded；未检测到 `.stock-detail-state-panel` |
| 样本股票 | `300169.SZ`，天晟新材 |
| viewport | `1600 x 1200` CSS px，DPR `1` |
| 默认主图 | `MA` |
| 默认右侧 tab | `盘口` |
| 最终 DOM 量测时间 | `2026-07-30T16:23:46.110Z` |

这一节记录首次取证 run，供追溯，不再作为施工输入。当前有效输入以第 0 节 capture 为准。

## 2. 已完成事实取证

| 计划项 | 结果 | 证据 |
| --- | --- | --- |
| 默认 loaded 页面 | 通过 | `full-page.png`、`dom-geometry.json`、`computed-styles.json` |
| 页面根和主要模块几何 | 通过 | 页面宽 `1600px`；顶部栏 `56px`；面包屑 `42px`；工具栏 `44px`；图表工作台与右侧信息栏坐标已记录 |
| 字体 token | 通过 | 数字字体 token 为 `"DIN Alternate", "Roboto Mono", "SF Mono", ...`；浏览器缺失 DIN 时的 Roboto Mono 回退仍是已知事项 |
| K 线 hover | 通过 | 十字线覆盖 K 线、MACD、成交量和 KDJ 四区；日期标签与 OHLC tooltip 在当前交互下可见 |
| 指标区 hover | 通过 | 指标区点击后十字线仍贯穿四区，tooltip 更新为该时间点数据 |
| MA/BOLL | 通过 | 主图选择器可切到 `BOLL`，显示 `UPPER/MID/LOWER`；随后已恢复 `MA` 默认态 |
| 右侧 tab | 通过 | `盘口` 与 `资料` 均可切换，已恢复 `盘口` 默认态 |
| 不支持周期和操作按钮 | 通过 | 周 K 显示“周K 首期暂未接入真实数据”；图表工具栏设置显示“图表设置暂未开通” |
| mouse leave 消失态 | 通过 | 用户将鼠标移出图表区后，`tooltip`、`crosshair`、`dateLabel` 均为 `null`；见 `interactions/mouse-leave.json` 与 `interactions/mouse-leave-full.png` |

## 3. 阻塞项

### 3.1 `CAPTURE_CLIP_ORIGIN_UNRELIABLE`（直接浏览器裁切路径）

in-app browser 的 `screenshot({ clip })` 输出未按传入的 `x/y` 原点裁切：请求图表工作台区域时，输出仍从页面顶部开始。DOM 中的几何坐标虽然正确，但对应模块 PNG 并不对应这些坐标。

影响：不能用该浏览器直接裁切路径作为 Figma 的像素量测依据。最新 capture 已改用从 `full-page.png` 进行且经过角点核对的 CoreGraphics 等价裁切，模块 PNG 现已有效；直接浏览器 `clip` 输出仍保持禁用。

### 3.2 `CAPTURE_MOUSE_LEAVE_UNREPRODUCIBLE`（已解除）

自动化输入仍不能稳定触发 React 的 `onMouseLeave`，但这不再阻塞 M0：用户已通过真实鼠标完成离开操作，随后 DOM 读数确认 `.kline-tooltip`、`.stock-detail-crosshair-vertical` 和 `.stock-detail-crosshair-date-label` 均不存在。对应证据保存为 `interactions/mouse-leave.json` 与 `interactions/mouse-leave-full.png`。

边界：该状态截图的浏览器 viewport 为 `761 x 800`，仅用于确认离开后的可见性；所有 Figma 尺寸和位置仍使用本 capture run 的 `1600 x 1200` 默认态量测。

## 4. M0 门禁结论

| M0 验收项 | 结论 |
| --- | --- |
| 同一次 loaded 页面完整基线 | 通过 |
| DOM/CSS 几何与默认全页截图 | 通过 |
| 可验证模块 crop | 通过（同源全页图的已验证本地裁切） |
| hover/crosshair 当前可见态 | 通过 |
| mouse leave 消失态 | 通过 |
| 允许进入 M1 Figma Foundations | **允许** |

## 5. M1 Shared Shell 验收

| 项目 | 结果 | Figma 证据 |
| --- | --- | --- |
| 页面根 | 通过 | `06 Stock Detail - Desktop Loaded` / `345:3`；固定 `1600 x 1200`。 |
| 共享顶部栏 | 通过 | `345:4` 是 `97:2` 的 instance，尺寸 `1600 x 56`，未 detach。 |
| 面包屑与工具栏槽位 | 通过 | `345:55` 为 `1600 x 42`，`345:56` 为 `1600 x 44`；纵向位置分别为 `y=56`、`y=98`。 |
| 主内容与两列 | 通过 | `345:57` 从 `y=142` 起、高 `1058`；工作台 `345:58` 为 `1193.195 x 1038`，右栏 `345:59` 为 `376.797 x 1038`，列间距 `10`。 |
| Panel 外框 | 通过 | 两列使用实测的半透明深色填充、`14px` 圆角、`1px` 半透明边框及实测内外阴影。 |

M1 只完成 shell、列宽与 panel 外框，不提前填入面包屑、工具栏、图表或右栏内容。M2 已在同一 `1600 x 1200` capture 基线上完成，具体见第 6 节。

## 6. M2 顶部内容验收

| 项目 | 结果 | 本地量测与 Figma 证据 |
| --- | --- | --- |
| 面包屑 | 通过 | `345:55` 中 native trail `370:53` 固定 `x=12`、`h=42`、`gap=7`；底部分隔线 `370:52` 位于 `y=41`。路径文本依次为“财势乾坤 / 乾坤行情 / 个股详情 / 天晟新材 300169.SZ”。 |
| 文本字体 | 通过 | 本地工具栏 computed style 是 macOS system stack；Figma 可用 `SF Pro`，M2 文本层及其控件 component 均使用 `SF Pro Regular/Bold`，没有以 Noto 近似替代。 |
| 股票身份 | 通过 | 名称、代码、行业均为原生可编辑层。`Stock Identity / Main` 宽 `177.570px`；父组保留本地 `210px` 最小宽度。代码 chip `71.570 x 19px`，行业 chip `36 x 21px`。 |
| 周期控件 | 通过 | 11 个原生 instance，默认日 K active、其余沿用本地 `.unsupported` 的 `0.58` opacity。周期组 `373:61` 为 `580.977px`，从 `x=234px` 起；首个“分时”从 `x=265px` 起。各按钮按实际 DOM 宽度覆盖，非等宽。 |
| 操作控件 | 通过 | 右侧 action group `373:86` 宽 `238px`、在 `1600px` 根内位于 `x=1352px`。前复权 / 股票资料 / 诊股 / 设置宽度分别为 `59/72/46/46px`；诊股 opacity `0.45`。 |
| 工具栏表面 | 通过 | `345:56` 高 `44px`，背景 `rgba(10,16,29,.88)`，左右 padding `10px`，下边线 `rgba(148,163,184,.12)`。中性控件填充 `rgba(15,23,42,.74)`、中性边 `rgba(148,163,184,.18)`、active 填充 `rgba(247,199,107,.10)`、active 边 `rgba(247,199,107,.36)`。 |
| 组件治理 | 通过 | 新建 `06.5 Stock Detail - Components`（`358:2`），仅包含本页专用 Meta Chip、Period Button（Neutral/Active/Unsupported）、Toolbar Action（Default/Disabled）。loaded 主稿通过 instance 使用，不使用截图或 image fill。 |

M2 截图核对使用 Figma root `345:3` 的 1x 导出；该导出仅用于验收，不进入 Figma 图层。页面产品代码未改动。

## 7. 后续恢复条件

## 7. M3-M6 图表、右栏、状态与差异验收

### 7.1 M3 图表工作台

| 项目 | 结果 | Figma 证据 |
| --- | --- | --- |
| 图表四区 | 通过 | `378:69` 是 `1191.195 x 1003` 的 native charts area；K线、MACD、成交量、KDJ 节点依次为 `378:70`、`379:69`、`379:191`、`379:313`。 |
| panel 几何 | 通过 | 四区高度分别为 `464.078 / 179.305 / 179.305 / 180.312px`；起始 y 依次为 `0 / 464.078 / 643.383 / 822.688px`，与 M0 量测一致。 |
| 时间轴与指标栏 | 通过 | `379:347` 为 `24px`，绝对叠在 charts area 底部，填充为 `rgba(10,16,29,.14) -> rgba(10,16,29,.90)` 的纵向渐变并有 `1px` 半透明顶部分隔线；`379:354` 为 `34px`。二者均与 charts area 的同一 x/right axis 基线对齐。 |
| 数据与图形 | 通过 | 读取本地真实 `kline` 日 K 90 根结果（`300169.SZ`、`period=day`、`adjustment=forward`），使用原生 K 线、MA、MACD、成交量、KDJ 节点构造。 |
| 图层约束 | 通过 | 无图表截图或 image fill；主稿图表为可编辑 vector/line/rectangle/text 节点。 |

### 7.2 M4 右侧信息栏

| 项目 | 结果 | Figma 证据 |
| --- | --- | --- |
| 股票头部与 tabs | 通过 | `381:69` 为 `374.797 x 119.797`，`381:85` 为 `374.797 x 36`。 |
| 盘口摘要 | 通过 | `381:90` 位于 rail `x=10, y=165.797`，尺寸 `354.797 x 248`；两列摘要格和涨跌色已原生构造。 |
| 关联板块 | 通过 | `381:117` 位于 `x=10, y=423.797`，尺寸 `354.797 x 233`；保持 table 行、列和分割线，不降级为卡片列表。 |
| 资金与边界 | 通过 | `381:139`、`381:162` 分别为 `354.797 x 187` 和 `354.797 x 164`；继续标明当前 mock/disabled 产品边界。 |

### 7.3 M5 状态页

| 项目 | 结果 | Figma 证据 |
| --- | --- | --- |
| 状态页与主稿隔离 | 通过 | 独立 Figma page `385:2`：`07 Stock Detail - States and Interaction Notes`；主稿 page `345:2` 不含 hover 或 toast。 |
| mouse leave 消失态 | 通过 | 状态根 `385:3` / default card `385:8`；记录用户在本地页确认的“无 tooltip、无十字线、无浮动日期标签”。 |
| hover 与控制状态 | 通过 | `385:21` 记录四区联动十字线与 tooltip；`385:67` 记录 MA/BOLL、盘口/资料和 toast 边界。 |

### 7.4 M6 差异归因

| 检查项 | 结果 | 结论 |
| --- | --- | --- |
| 导出尺寸 | 通过 | source `full-page.png` 与 Figma root `345:3` 导出均为 `1600 x 1200`。 |
| shell 与网格几何 | 通过 | TopMarketBar `1600 x 56`，面包屑 `1600 x 42`，工具栏 `1600 x 44`，左右列 `1193.195 + 10 + 376.797`，四区图表和右栏内区坐标均已程序化对账。 |
| shared 顶栏 | 通过 | `345:4` 是 `97:2` 的 component instance，未 detach。 |
| image fill 检查 | 通过 | loaded 根仅发现 shared 顶栏中既有官方 Brand Logo 位图；图表、右栏、页面背景均没有 image fill。 |
| `FIGMA_CONSTRUCTION_DEFECT` | 已修复 | `379:347` 曾使用 `rgba(10,16,29,.92)` 实心填充，视觉上错误吞掉 KDJ 底部曲线；已替换为与当前页面 CSS 一致的 `.14 -> .90` 纵向渐变。 |
| `SOURCE_CHANGED` | 无 | M6 比对继续使用第 0 节的冻结 source capture，不以当前动态页面数据覆盖它。 |
| `FONT_RENDERING_GAP_OPEN` | 开放 | 页面数值 token 的浏览器首选 `DIN Alternate` 在 Figma 不可用，已按既定口径使用 `Roboto Mono`；同时浏览器 Canvas 与 Figma 原生 vector 的抗锯齿不可逐像素等同。两项已记录，不放宽布局、尺寸、颜色或字重门禁。 |

## 8. M7 页面级复核与交接

| 检查项 | 结果 | 证据 |
| --- | --- | --- |
| loaded 根结构 | 通过 | `345:3` 只有 `345:4` TopMarketBar、`345:55` 面包屑、`345:56` 工具栏、`345:57` 主内容四个直接子节点。 |
| shared TopMarketBar | 通过 | `345:4` 的类型为 `INSTANCE`，主组件为 `97:2`；没有 detach 或股票详情私有副本。 |
| 主内容双列 | 通过 | `345:57` 仅包含 `345:58` 工作台（`x=10, w=1193.195`）和 `345:59` 右栏（`x=1213.195, w=376.797`）。 |
| loaded 交互残留 | 通过 | 结构扫描中没有 tooltip、crosshair 或 date-label 节点；默认主稿保持用户已确认的 mouse leave 消失态。 |
| 状态页隔离 | 通过 | `385:2` 有且仅有 `385:3` 状态根；状态页无 image fill，hover/crosshair 只在该页表达。 |
| image fill | 通过 | loaded 根唯一 image fill 为 shared TopMarketBar 中既有官方 `Brand Logo / official asset / 36x36`；没有图表、右栏或页面截图填充。 |

## 9. 最终结论与开放项

**最终验收状态：`STRUCTURE_AND_VISUAL_BASELINE_VERIFIED`。** M0-M7 全部完成，所有布局、尺寸、组件归属、默认交互消失态和可编辑图层约束均已核验。KDJ 时间轴的实心遮罩缺陷已在人工视觉复核后修正为与线上 CSS 一致的半透明纵向渐变；不能再将“时间轴与 KDJ 曲线同时可见”误判为曲线应被遮挡。

**开放项：`FONT_RENDERING_GAP_OPEN`。** 浏览器数值字体首选 `DIN Alternate`，Figma 不可用而使用 `Roboto Mono`；浏览器 Canvas 与 Figma 原生 vector 的抗锯齿也无法逐像素一致。因此不将该页面误标为两个 PNG 位图“逐像素相同”，但上述平台级差异以外没有未分类问题。

本轮未改动 `wealth/**` 产品代码、后端 API、页面 CSS 或数据模型。
