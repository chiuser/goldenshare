# XXM密集标注修复

2026-10-16，当前`dev-interface`。依据用户“修复一下标注吧”、[展示基准§10](/Users/congming/github/goldenshare/wealth/docs/pages/index-detail/index-detail-xxm-benchmark-requirement-v0.1.md:140)及[LLD§19](/Users/congming/github/goldenshare/wealth/docs/pages/index-detail/index-detail-xxm-implementation-and-low-level-design-v0.1.md:1160)。只修文字位置与节点对应，日线和60／90／120分钟使用同一图层；没有修改识别结果、事件日期、DIF、API、算法、数据源或预测。没有提交、推送、部署或改动其他任务的脏文件。

## 修复与截图回归

原布局可沿整个pane向上／下找空位，文字因此远离自己的节点。现在优先给靠近上下边界的节点安排文字，文字上下最多移动40px、沿原侧额外水平最多48px；需要移位时用同色1px引线连回自己的圆点，优先直连，受阻时近端折线绕行。先排文字再排线，避免为连线删文字。原字体、颜色、圆点大小和原始坐标保持。

用户截图四事件的CSS坐标回放结果如下。这是截图近似坐标复现，不是浏览器实测；真实日期、DIF及事件来自已保存的h1接口／adapter输出。

| 事件日期 | 文字 | 原文字中心上下偏移 | 当前偏移 | 当前对应方式 |
| --- | --- | --- | --- | --- |
| 2026-07-13 | 钝化 | 0px | 0px，额外左移12px | 细直线 |
| 2026-07-15 | 取消 | 上移约38px | 上移20px | 细直线 |
| 2026-07-17 | 钝化 | 上移约92px | 上移1.5px，额外左移36px | 折线避开相邻文字 |
| 2026-07-20 | 取消 | 上移约56px | 上移9.5px，额外左移12px | 细直线 |

114／114.5／115px pane下四条文字均保留；近端布局稳定，文字不相互覆盖、不盖圆点，引线各段不穿其他文字或圆点。点中心、DIF、事件时间不动，autoscale仍为null。原“取消”文案未改名。

## 技术验证及实际限制

- `markerGeometry.test.ts`10项通过，包含截图四事件、上下边界、左／右边界、邻点、同柱`+2`、极窄pane、引线实际绘制顺序／端点／颜色和不改变纵轴的正反例。
- [全量日志](./wealth_tests.log)：165文件／1183项通过；[类型](./wealth_typecheck.log)及[构建](./wealth_build.log)通过。构建仍有既有主chunk超过500kB提示。
- [响应驱动绘制记录](./recorded_api_draw.json)：四周期×3种canvas宽度×2种高度共24场景，加截图3场景。输入为先前正式验收留存的真实h1响应和严格adapter结果，不是mock行情；各源文件路径和SHA-256在记录中。现有primitive的所有圆点逐一匹配事件time／DIF，文字在边界内且位移有界。
- 日线21点、60分钟34点、90分钟23点、120分钟21点全部保留。60分钟1000／1280px canvas的极密集区有1—2条文字没有可用近端空位，原点及完整详情仍保留；1445px下四周期所有文字均保留。不用远移标签或改变纵轴解决空间不足。
- 本轮记录的canvas是Node中的绘制调用检查，中文测宽为12px近似，不是浏览器字体、实际像素、交互或页面验收；耗时也不替代浏览器帧性能。原算法和后端4秒预算没有变化，本次不重跑数据读取预算。
- 现有`127.0.0.1:5175`连接被拒绝，没有启动或重配服务。浏览器状态读取被自动审批按用户此前自行验收的要求拒绝，没有绕过；本轮未操作浏览器或读取登录状态。页面由用户自行复看。

代码改动为[markerGeometry.ts](/Users/congming/github/goldenshare/wealth/src/features/index-detail/xxm/markerGeometry.ts)、[XxmMacdPrimitive.ts](/Users/congming/github/goldenshare/wealth/src/features/index-detail/xxm/XxmMacdPrimitive.ts)及对应测试；同步原展示基准和LLD。CodeGraph开工前explore／impact覆盖几何→primitive→共享hook及分钟消费者，当前代码补核日线共用链；开发后sync／status正常。没有共享API contract或依赖矩阵变更，索引未识别的测试关系由实际测试补核。

复查命令（仓库根）：

```sh
npm --prefix wealth run test -- src/features/index-detail/xxm/markerGeometry.test.ts --maxWorkers=2
npm --prefix wealth run test -- --maxWorkers=2
npm --prefix wealth run typecheck
npm --prefix wealth run build
node reports/xxm_label_alignment_20261016/draw_check.cjs
.venv/bin/python -B scripts/check_docs_integrity.py
codegraph sync
codegraph status
```
