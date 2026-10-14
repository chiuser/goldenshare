# 徐小明标记视觉修订：页面验收

2026-10-14。已按用户确认的 [Figma `2010:2173`](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-web?node-id=2010-2173)同步本地财势乾坤，日线和 60／90／120 分钟技术验收通过，等用户复看。没有提交、推送或部署。

页面：[上证指数](http://127.0.0.1:5175/wealth/market/index/000001.SH)。依据为[展示基准 §5／§9](/Users/congming/github/goldenshare/wealth/docs/pages/index-detail/index-detail-xxm-benchmark-requirement-v0.1.md)与[LLD §7.1](/Users/congming/github/goldenshare/wealth/docs/pages/index-detail/index-detail-xxm-implementation-and-low-level-design-v0.1.md)。本轮只改图上格式与像素几何，不改算法、后端、接口、来源或其他图层。

## 实际效果与硬口径对账

| 用户要求／边界 | 落地与验收 |
| --- | --- |
| 圆点更清晰 | 半径 4px、直径 8px；实际 canvas arc 已测量，原时间／DIF 坐标继续取自图表 |
| 加粗、去掉顶底前缀 | 12px、700 字重；浏览器会把 700 规范化为 bold。图上显示钝化、结构、消失、取消、结构消失 |
| 文字尽量在左侧 | 文字右缘距点左缘 8px；先同一行，再在左侧上下避让；仅左边界无完整空间时用右侧 |
| 密集时保持可读 | 文字不重叠、不盖事件圆点；窄屏同柱两事件用 +2 时保留两次圆点绘制和完整详情 |
| 四周期一起同步 | 原日线及分钟 adapter 继续复用同一 XXM primitive；四个真实 API 请求均 200，300／500／500／500 根真实响应已保存 |
| 保留方向与算法事实 | 图上短标签单独格式化；详情仍显示底结构／顶结构消失，DTO 的 direction、事件、参照和历史记录不变；autoscaleInfo 仍为 null |

[实际 MACD 局部效果](./macd_day_preview.png)；完整页面： [日线](./ui_day_1600.png)、[60 分钟](./ui_m60_1600.png)、[90 分钟](./ui_m90_1600.png)、[120 分钟](./ui_m120_1600.png)。设计行情图没有作为页面或算法数据。

## 真实页面检查

[浏览器绘制证据](./browser_evidence.json)保存 10 个场景的 canvas 圆点、文字、字号与字重、坐标、窗格边界、碰撞检查、请求参数和控制台结果：日线三个宽度、三个分钟周期、120 分钟缩放、90 分钟密集历史案例三个宽度。均无页面横向溢出、文字裁切、标签间重叠或标签覆盖圆点；最终控制台无 warning／error。正常位置均左侧；点靠左边界时才右侧。

2025-03-14 11:00 的 90 分钟真实响应同时包含 BOTTOM STRUCTURE 与 TOP RESEARCH_HISTORICAL_WITHDRAWAL。图上用“结构／结构消失”，详情仍显示“底结构 / 顶结构消失”，两份参照、保存价格峰与结束时间完整。见[真实响应](./api_same_bar_m90.json)、[同柱页面](./ui_same_bar_m90_1600.png)、[详情](./ui_same_bar_details.png)、[1440px](./ui_same_bar_m90_1440.png)、[1280px](./ui_same_bar_m90_1280.png)。历史日线的涨跌家数原本缺失，页面如实提示，未补造。

当前四周期真实响应： [日线](./api_day.json)、[60 分钟](./api_m60.json)、[90 分钟](./api_m90.json)、[120 分钟](./api_m120.json)。本轮未改变源数据或计算规则；真实响应驱动 adapter 的原有身份、时间、C／DIF／DEA／柱值校验及实际渲染。

验收时恢复了已停止的独立 5175／8001 服务，复用 `.env.web.local` 和既有临时 Vite 配置；8001 使用 `--lifespan off`，没有启动后台数据任务，原 8000 服务未重启。临时配置在默认打包加载时解析 Vite 内部模块失败，改用现有 Vite 支持的 `--configLoader native` 后恢复；没有安装、升级或修改依赖。旧失效标签页的浏览器助手无法恢复，改用同一浏览器的新标签页完成验收；已有登录状态自动刷新后正常使用。

canvas 测量包装已恢复原方法，临时浏览器尺寸已 reset，当前干净日线页保留供用户复看。没有将测试挂钩或调试状态写入产品代码。

## 改动与验证

代码只改这五个文件：

- [adapter.ts](/Users/congming/github/goldenshare/wealth/src/features/index-detail/xxm/adapter.ts)：图上短标签格式化，详情格式保持。
- [markerGeometry.ts](/Users/congming/github/goldenshare/wealth/src/features/index-detail/xxm/markerGeometry.ts)：单一视觉参数、左侧布局、邻点与标签避让。
- [XxmMacdPrimitive.ts](/Users/congming/github/goldenshare/wealth/src/features/index-detail/xxm/XxmMacdPrimitive.ts)：加粗 canvas 字体、行内文字定位，8px 圆点沿用已有动态绘制。
- [adapter.test.tsx](/Users/congming/github/goldenshare/wealth/src/features/index-detail/xxm/adapter.test.tsx)、[markerGeometry.test.ts](/Users/congming/github/goldenshare/wealth/src/features/index-detail/xxm/markerGeometry.test.ts)：短文字与详情语义、禁止事件、边界、密集、+2、实际圆点与字体。

同步了展示基准、专项 LLD 和 Wealth 文档索引；保存了本目录的 API、截图、测试日志及代码哈希。无关脏文件保持原样。

```bash
npm --prefix wealth run typecheck
npm --prefix wealth run test -- --maxWorkers=2
npm --prefix wealth run build
.venv/bin/python -B scripts/check_docs_integrity.py
codegraph sync
codegraph status
```

typecheck／build 通过；全量 162 个文件、1156 项测试通过，日志见 [wealth_tests.log](./wealth_tests.log)。新增几何与标签用例覆盖正向和边界反例，原两类指数 adapter、两类股票 adapter 与 shared 工作台回归通过。文档完整性检查通过。构建保留已有主 chunk 超过 500kB 的提示，没有扩大本轮范围去调整打包。

两次默认并发全量复跑分别出现 PriceVolumeWorkspace 的 scope 切换、DualMomentumWorkspace 的浏览器历史恢复异步用例失败，日志保存在[第一次](./wealth_tests_full_first.log)与[第二次](./wealth_tests_full_second.log)。量价模块及新增几何用例[定向重跑](./targeted_recheck.log)共 21 项通过；随后仅把完整套件并发降至两个 worker，162 文件／1156 项全部通过。没有跳过测试、修改断言、放宽超时或改动这两个其他模块；默认并发下的测试不稳定性仍保留为独立问题。

CodeGraph 开发前使用 explore／impact，覆盖标签、详情、几何、primitive、hook、两类指数 adapter；索引未识别测试关联，以当前真实测试文件补核。开发后 sync／status 正常，impact(layoutXxmLabels) 只涉及几何与绘制层；无接口或架构依赖矩阵变化。

下一步是用户复看本地页面。生产分钟能力仍受原门禁限制；软件公式、视频对照和算法准确率继续按原研究方案验证，不因视觉修改获准而算完成。
