# 详情页共享图表与 K 线缩放 M2 编码前门禁 v1

> 状态：产品参数、技术方案、正式 Web 设计稿与 LLD 已确认；M1 已完成实现和验收，待独立提交后进入 M2。
> 正式设计稿：[Goldenshare Web / 10 Detail Chart Zoom - Web Handoff](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=581-516&m=dev)
> 需求：[详情页 K 线缩放标杆需求 v1](./detail-chart-zoom-benchmark-requirement-v1.md)
> 方案：[详情页共享图表与 K 线缩放技术实施方案 v1](./detail-chart-zoom-implementation-design-v1.md)
> LLD：[详情页共享图表与 K 线缩放 LLD v1](./detail-chart-zoom-low-level-design-v1.md)

---

## 1. 总门禁

1. [x] 最少 45 根、最多 180 根、步长 15 根已冻结。
2. [x] 1600px 默认 120 根、自适应目标约 9.5px/根、默认 clamp 75～150 已冻结。
3. [x] 放大/缩小只改变横轴可见根数，纵轴按可见行情自动适配已冻结。
4. [x] 日线 300 根、分钟 500 根足够覆盖 180 根上限，不改 API 已确认。
5. [x] 必须先收敛股票分钟共享组件，再开发缩放功能已确认。
6. [x] 正式 Figma page `581:516` 已升级并标记 `APPROVED FOR WEB DEVELOPMENT`；本功能不增加后端、配置或异常码改动。
7. [x] 技术实施方案经用户评审确认。
8. [x] 正式组件、四场景、密度、状态、几何和 Web 映射节点已登记到技术方案与 LLD。
9. [x] LLD 经用户评审确认。
10. [x] M1 迁移前四类图表 1600×1200 浏览器基线截图已保存。
11. [x] M1 共享收敛已通过；仍须形成独立提交后才进入 M2 缩放实现。

## 2. M1：共享收敛门禁

### 2.1 必须完成

1. [x] `StockMinuteChartWorkspace` 已改为 shared adapter，不再直接创建 chart。
2. [x] 股票日线、股票分钟、指数日线、指数分钟均渲染 `DetailChartWorkspace`。
3. [x] 股票分钟 loading/empty/error/ready、状态块、Tooltip、单位和指标标题保持。
4. [x] shared minute 时间轴、crosshair、Y 轴标签和四 pane drag 保持。
5. [x] 股票分钟重复 chart options、series、sync、drag、pane 生命周期已删除。
6. [x] M1 仍使用旧 90 根窗口，未提前混入 120 根和缩放按钮。
7. [x] 股票分钟四 pane 原生时间轴、原生 crosshair 轴标签、顶部状态块和 34px 空轨道通过 shared 的通用展示合同保持，不使用页面补偿 CSS。

### 2.2 禁止项

1. [x] 没有保留旧股票分钟 chart 作为 fallback 或兼容分支。
2. [x] 没有复制 `DetailChartWorkspace` 形成新的 minute shared 组件。
3. [x] 没有修改 API、DTO、请求量、分钟能力开关或后端路由。
4. [x] 没有修改趋势通道 geometry、公式或颜色。
5. [x] 没有用补偿坐标掩盖 shared CSS 与股票分钟 CSS 的结构差异。

### 2.3 M1 退出门禁

1. [x] `npm --prefix wealth run typecheck` 通过。
2. [x] `npm --prefix wealth run test` 通过（22 files / 112 tests）。
3. [x] `npm --prefix wealth run build` 通过。
4. [x] 四类图表浏览器 smoke 通过；干净页面会话无 console error，未新增网络调用。
5. [x] 迁移前后普通 UI 几何偏差不超过 2px（核心容器与 28 个 canvas 实测均为 0px）。
6. [ ] M1 形成独立、可审计提交后，才进入 M2。

## 3. M2：缩放合同门禁

### 3.1 常量唯一性

以下常量只能定义在 `detailChartViewport.ts`：

```ts
MIN_VISIBLE_BARS = 45
MAX_VISIBLE_BARS = 180
ZOOM_STEP_BARS = 15
DEFAULT_VISIBLE_BARS = 120
MIN_ADAPTIVE_DEFAULT_BARS = 75
MAX_ADAPTIVE_DEFAULT_BARS = 150
TARGET_PIXELS_PER_BAR = 9.5
RIGHT_PRICE_SCALE_WIDTH = 56
```

门禁：

1. [ ] 页面、adapter、CSS 和测试 fixture 未复制业务常量。
2. [ ] `visibleBars?: number` 已从 public shared props 删除。
3. [ ] 没有新增 env、Vite flag、策略中心 key 或 localStorage 配置。

### 3.2 初始范围

1. [ ] 使用 K 线 host 宽度减 56px 价格轴计算真实绘图区宽度。
2. [ ] 除以 9.5 后四舍五入到最接近的 15 根，再 clamp 到 75～150。
3. [ ] 1600×1200 页面精确得到 120 根。
4. [ ] 宽度为 0/NaN/不可测时回退 120 根。
5. [ ] 初始右边界为最新一根；数据不足时显示全部。

### 3.3 点击与锚点

1. [ ] 放大镜加号每次减少 15 根，最低 45；45 根时该按钮 disabled。
2. [ ] 放大镜减号每次增加 15 根，最高 `min(180, pointCount)`；到达上界时该按钮 disabled。
3. [ ] 当前贴近最新时固定最新右边界。
4. [ ] 历史区间缩放保持区间中心；边界 clamp 不静默缩短目标范围。
5. [ ] 四个 pane 接收完全相同的 logical range。
6. [ ] 点击按钮不触发 pointer drag、`fitContent()`、API 请求或 chart 重建。
7. [ ] `buildChartOptions()` 显式设置 `rightPriceScale.autoScale=true`；没有 CSS scale 或行情值倍率转换。

### 3.4 生命周期

1. [ ] 四个 adapter 均传稳定且必填的 `dataKey`。
2. [ ] dataKey 改变时重置自适应默认。
3. [ ] MA/BOLL/趋势通道图层切换保留当前范围。
4. [ ] 用户交互后 resize 保持选择；未交互时 resize 允许更新自适应默认。
5. [ ] 同一 dataKey 新增最新 bar 时，最新视图跟随；历史视图不跳回最新。
6. [ ] 卸载时 observer、subscription 和 pointer listener 全部清除。

## 4. 控件与视觉门禁

1. [ ] 两个真实 button 位于 K 线主图右下角。
2. [ ] 排列为 Phosphor `magnifying-glass-minus`（缩小）后 `magnifying-glass-plus`（放大），单按钮 28×28px、间距 4px、组合宽 60px。
3. [ ] 控件右侧距价格轴左边 8px，底部距绘图区 8px。
4. [ ] 图标从正式 Figma 组件 `583:534` 导出完整同源 SVG 并固化：16×16、内部约 13.014×13.014、保留约 1.493px 左右的 x/y 居中位移、`currentColor`、`aria-hidden`；没有纯文本、左上角偏移或近似图标。
5. [ ] 缩小按钮 aria-label 为“缩小K线，增加可见根数”。
6. [ ] 放大按钮 aria-label 为“放大K线，减少可见根数”。
7. [ ] disabled 同时具备原生属性、45% 视觉弱化和不可点击行为。
8. [ ] focus-visible 清晰，颜色和圆角使用现有 Design Token。
9. [ ] 控件不遮挡价格轴、Y 轴浮标、Tooltip、十字线、时间轴或重要 K 线。
10. [ ] 页面、左右栏、pane、底部指标栏尺寸不变。
11. [ ] 不新增 Phosphor/Supericons 运行时依赖。

## 5. 状态门禁

| 状态 | 缩放控件 | 预期 |
|---|---|---|
| Loaded，点数 >=45 | 显示 | 按当前范围决定 disabled |
| Loaded，点数 <45 | 显示 | 两个按钮均 disabled |
| Partial，有 K 线 | 显示 | 指标缺失不阻塞缩放 |
| Loading | 不显示 | 保持骨架 |
| Empty | 不显示 | 保持模块空态 |
| Error | 不显示 | 保持错误与重试 |
| Forbidden | 不显示 | 保持权限态 |

门禁：

1. [ ] 切换标的/周期时旧缩放状态不串入新图表。
2. [ ] 状态切换不展示旧图表的缩放按钮。
3. [ ] 本功能没有新增 API 错误或异常码。

## 6. 测试门禁

### 6.1 纯函数测试

1. [ ] 75/120/150 自适应样例。
2. [ ] 45/180 和 pointCount 边界。
3. [ ] pointCount 为 0、30、60、100、300、500。
4. [ ] latest 锚点、历史中心、左右 clamp。
5. [ ] logical span 始终等于 `visibleCount-1`。

### 6.2 Shared 组件测试

1. [ ] 默认 120 根和四 pane 同步。
2. [ ] 连续放大至 45、连续缩小至 180。
3. [ ] 数据少于 45、介于 45 与默认、少于 180 三类边界。
4. [ ] 点击按钮时 `createChart` 次数不变、fetch 次数为 0。
5. [ ] overlay 切换、resize、dataKey 和 append bar 行为。
6. [ ] drag/crosshair/tooltip/时间轴/axis label 回归。
7. [ ] 通过 aria-label 找到两个按钮，并断言 45/最大值/ShortData 的 disabled 方向与组件集 `585:550` 一致。
8. [ ] SVG source/样式断言证明没有纯文本 `−`/`＋` 或近似 icon 回退。

### 6.3 Adapter 与页面测试

1. [ ] `StockMinuteChartWorkspace` 的真实字段映射和状态过程。
2. [ ] `StockChartWorkspace` MA/BOLL 回归。
3. [ ] `IndexChartWorkspace` 趋势 primitive 与 autoscale 回归。
4. [ ] `IndexMinuteChartWorkspace` minute 时间轴与模拟指标标识回归。
5. [ ] 股票/指数页面切标的、切周期和局部异常回归。

### 6.4 验证命令

```bash
npm --prefix wealth run typecheck
npm --prefix wealth run test
npm --prefix wealth run build
git diff --check
```

通过标准：全部命令退出码为 0；不能只运行新增测试替代全量 Wealth 回归。

## 7. 浏览器与像素门禁

### 7.1 M1 无漂移

1. [x] 保存迁移前与迁移后同尺寸截图：`/private/tmp/goldenshare-detail-chart-zoom/m1-before|m1-after`。
2. [x] 股票分钟状态块、四 pane、Tooltip、crosshair 和底栏无视觉漂移。
3. [x] 普通 UI 偏差 <=2px，无新增换行、裁剪、重叠或溢出。

### 7.2 M2 预期变化

1600×1200 至少验收：

1. [ ] 股票日线 120/45/180 根。
2. [ ] 股票分钟 120 根、历史区间缩放、Tooltip。
3. [ ] 上证指数日线 120 根、趋势通道、Tooltip。
4. [ ] 指数分钟 1m/60m/120m 与模拟指标标识。
5. [ ] 宽度变化后的 75/150 clamp。

设计对照：股票日线 `588:524`、指数日线 `590:613`、股票分钟 `591:1711`、指数分钟 `592:918`；45/120/180 密度 `593:1095`；状态 `597:1107`；几何与 <=2px 门禁 `597:1120`。

允许变化仅限：新增缩放按钮、K 线横向密度、纵轴依据可见数据的自动范围。其它 UI 仍按 <=2px 验收。

## 8. 性能门禁

1. [ ] 单次点击只执行四个 chart 的 `setVisibleLogicalRange()`。
2. [ ] 单次点击不销毁/重建 chart 或 series。
3. [ ] 单次点击不触发 React 页面请求和网络请求。
4. [ ] ResizeObserver 不形成同步回调循环或持续重绘。
5. [ ] 300/500 点输入下连续点击与拖动无可见卡顿。

## 9. 通用清单映射矩阵

| 通用清单项 | 适用性 | 本模块落点/理由 | 验证 |
|---|---|---|---|
| 2.1 三件套先行 | 适用 | 本目录三件套 | 用户确认后开工 |
| 2.2 后端事实归一 | 不适用 | 不新增事实字段或前端业务计算；仅管理图表 viewport | API 零差异审计 |
| 2.3 模块状态机 | 适用 | 沿用页面状态，冻结按钮可见性矩阵 | 组件/页面状态测试 |
| 2.4 显示与数据语义绑定 | 适用 | 纵轴只依据可见真实数据 autoscale | range/autoscale 回归 |
| 2.5 行为过程测试 | 适用 | 点击、拖动、resize、切换过程 | 交互测试 |
| 2.6 文档实现同轮同步 | 适用 | 三件套和股票/指数原文档 | 实施后对账 |
| 2.7 渐进替换 | 适用 | M1 共享迁移，M2 产品功能 | 两次独立提交 |
| 2.8 契约与消费者对齐 | 适用 | shared props/dataKey；无 API 变更 | 四 adapter typecheck |
| 2.9 图表坐标约束 | 适用 | x range 同步、y autoScale | 四 pane/趋势测试 |
| 2.10 统计与传输边界 | 不适用 | 不计算统计、不增传输；复用 300/500 点 | 网络请求为 0 |
| 2.11 配置生效语义 | 不适用 | 不新增配置 | 常量唯一性检索 |
| 2.12 通用清单映射 | 适用 | 本表逐项映射 | 文档审计 |
| 2.13 例外白名单 | 适用 | 无例外 | 方案第 11 节 |
| 2.14 图表参数优先级 | 适用 | 不开放页面覆盖；shared 冻结 viewport | props 删除/范围测试 |
| 2.15 双图坐标对齐 | 不适用 | 无并排双图；四个纵向 pane 使用统一 x range | 四 pane 同步测试 |
| 2.16 卡片单行约束 | 不适用 | 不修改指标卡片 | 浏览器回归 |
| 2.17 真实 API + 前端展示 | 适用但无新 API | 用既有真实日线/本地分钟 API 驱动四页面 smoke | 浏览器 network/DOM |
| 2.18 跨模块抽象原则 | 适用 | 方案 1.1 八条映射 | 对应测试矩阵 |

## 10. 例外白名单

无。

## 11. 签字清单

### 前端负责人

1. [x] shared props 与 viewport 状态可实现。
2. [x] 股票分钟已无兼容分支迁入 shared。
3. [x] M1 测试和浏览器门禁已执行；M2 门禁已冻结待实施。

### 架构负责人

1. [x] 共享职责和 feature adapter 边界清晰。
2. [x] 没有 API、后端或依赖矩阵变化。
3. [x] 两阶段提交边界可审计。

### 产品负责人

1. [x] 45/180/15、120、9.5px、75～150 已确认。
2. [x] K 线主图右下角按钮已确认。
3. [x] 本技术方案整体确认。
4. [x] 正式 Figma Web 开发稿及放大镜图标、边界 disabled 状态已确认。
5. [x] LLD 整体确认，M1 已完成实现与验收。

## 12. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1.3 | 2026-08-12 | 回填 M1 shared 迁移、112 项测试、1600×1200 前后截图与 0px 核心几何验收；保留独立提交门禁 | Codex |
| v1.2 | 2026-08-12 | 登记正式 Figma 开发稿、节点验收矩阵和同源 Phosphor 放大镜 SVG 门禁；明确 45/最大值/ShortData disabled 方向 | Codex |
| v1.1 | 2026-08-12 | 记录技术方案已确认，增加 LLD 评审门禁，并登记股票分钟时间轴、crosshair 轴标签和空轨道的无漂移要求 | Codex |
| v1 | 2026-08-12 | 初版：冻结 M1 共享收敛、M2 缩放实现及完整测试/视觉门禁 | Codex |
