# 市场总览 Figma 本地视觉 Capture Manifest

## Capture Identity

| 字段 | 值 |
|---|---|
| Capture ID | `20260728-local-loaded-1600-2x` |
| 捕获时间 | `2026-07-29T00:32:03.207Z` |
| 浏览器地址 | `http://127.0.0.1:5173/wealth/` |
| 实际页面状态 | `main.page-shell` 存在；登录表单、DEV 调试面板和 error marker 均不存在；16 个目标模块根存在。 |
| Viewport / DPR | `1600 x 1200 CSS px` / `1` |
| DOM 页面尺寸 | `1600 x 4343 CSS px` |
| 全页截图尺寸 | `1600 x 4342 px` |
| 本地代码 revision | `88ff3f880e09ff2bc4aac034893cf18c9c2e2f78` |
| 样式装载方式 | 6 个本地 Vite 运行时 style sheet。 |
| 量测文件 hash | `46556f523924106133cf433d402d3762452723aeaa9cf439ef3d3301545c33f8` |
| 整页截图 hash | `4d552b5dfed947efa6476f9a291adf04158390403a691569be5994c69c47544f` |

## 产物

- `measurement.json`：根/模块 geometry、模块 computed style、body 背景和 root token。
- `measurement.sha256`：`measurement.json` 的 SHA-256。
- `full-page.png`：同一次已登录 loaded DOM 的 1x 全页截图。
- `modules/*.png`：历史上从同一张 `full-page.png` 以对应模块 border-box 的 `floor(x/y) + ceil(width/height)` 裁出的 16 张候选图；不是第二次浏览器截图。对于带粘性顶部栏的长页面，这种全页拼接结果可能重复插入顶部栏，不能自动视为 M7 的模块级视觉证据。
- `modules/crop-manifest.json`：每张裁图的整数像素裁切框。

### M7 连板天梯补充证据

`modules/streak-ladder.png` 在本地复核中被判为无效：其内容不是 `[aria-label="连板天梯"]` 的完整模块，而是受粘性 `TopMarketBar` 全页拼接影响的错误裁切。因此它不能用于 M7 验收，也不能作为该模块的视觉事实。

- `modules/streak-ladder-m7-source.png`：在同一已登录本地页面上，以两段 viewport 截图的无顶栏可见区域按 DOM `y=2196.109375..3641.609375` 拼接得到；尺寸 `1564 x 1446`，SHA-256 `ce17afb9df6733c684d5b0176468acb4acdf6b5a45be82d695154971e41b91b4`。
- `figma/streak-ladder-106-122-m7.png`：Figma `106:122` 的模块导出，按梯度位移测算裁掉导出视觉范围顶部 `15px` 后得到；尺寸 `1564 x 1446`，SHA-256 `b1b7132ed859bd64000e20e94744f664c681809ee357574029e08c6e8ad504e8`。
- `figma/streak-ladder-106-122-overlay-m7.png`：上述两图以 `50%` alpha 叠加的审计辅助图，SHA-256 `f4b039e269db43ef33c1900acb09ec236d47971bf1d3631f1e32a51d58179270`。它只用于差异定位，不代表 `PIXEL_VERIFIED`。

### M7 板块速览源变更证据

`106:123` 的结构尺寸可继续以当前活动 capture 量测为准，但其 Figma 可见数据来自较早冻结样本，不能和当前本地 source 直接做像素验收。

- `modules/sector-overview-m7-source.png`：同一已登录本地会话中，按 `[aria-label="板块速览"]` 的当前 viewport `x=18 / y=511 / 1564 x 501px` 取得的 source 图。尺寸 `1564 x 501`，SHA-256 `91470e3ae641c4a440884e0b90c3d155a72b17fd9a464896b340bdf2ae2001b9`。
- `figma/sector-overview-106-123-m7-source-changed.png`：Figma `106:123` 导出，尺寸 `1564 x 549`，SHA-256 `0161e488def49ae835d116aca58876bb2ccb697e367d75c999b898f460a533c8`。
- 当前 source 的 Top5/资金流向与 heatmap 已改变，其中 heatmap 从冻结样本的上涨红色变为当前的下跌绿色；因此不生成 overlay。该组证据只证明 `SOURCE_CHANGED`，不代表 Figma 或页面任一方的样式通过。

## 量测说明

浏览器 `body.scrollHeight` 是 `4343 CSS px`，而全页位图导出为 `4342 px`。这是 Chromium 全页截图的像素取整，不是页面容器少 `1px`；模块几何与 Figma 的比较一律使用 `measurement.json` 中的 DOM border-box，不以整页位图尾部取整推断布局。

## 边界

此 capture 是用户明确指定的本地视觉施工事实源。它未读取或存储 Cookie、token、local storage、authorization header 或 API 响应正文，也未记录网络响应 hash；因此它只证明已登录页面的 DOM/CSS/截图视觉事实，不能作为 API 数据正确性的审计证据。
