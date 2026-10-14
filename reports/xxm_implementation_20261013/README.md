# 上证徐小明 V0.1 实施与验收报告

2026-10-13。状态：开发态实现及技术验收完成，等用户验收；没有提交、推送或部署。

依据是已批准的[算法方案](/Users/congming/github/goldenshare/docs/product/xxm-direction-algorithm-plan-v0.1.md)、[Figma 设计](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-web?node-id=1983-80)及[专项 LLD §13](/Users/congming/github/goldenshare/wealth/docs/pages/index-detail/index-detail-xxm-implementation-and-low-level-design-v0.1.md#13-实施与技术验收2026-10-13)。用户已批准一次扫描完整历史、按 1000 根推进计算，以及仅指数详情页支持 1280／1440px。

验收页：<http://127.0.0.1:5175/wealth/market/index/000001.SH>。同柱两层事件例：<http://127.0.0.1:5175/wealth/market/index/000001.SH?tradeDate=2025-03-14>，进入后选择 90 分钟、查看 11:00 柱。页面用真实日线数据库与正式分钟 Gold；本任务独立后端为 8001，关闭应用后台生命周期任务，原 8000 服务未重启。没有把测试文件作为产品数据。

## 实现范围

只对 000001.SH 的 day／m60／m90／m120 开放研究算法及图层。主门槛 1%，0.75%／1.2% 只用于离线回归。最近价格前置、两段原始池、最强合格参照、目标锁定、转向／反色、普通状态与历史记录分离均按原方案实现。顶部普通取消显示“顶消失”，底部普通取消显示“底取消”；历史撤销显示“顶结构消失”。没有加历史到期、负柱门禁、趋势动作或仓位逻辑。

新接口独立于原 K 线／指标／九转／趋势响应；由 App 注入既有鉴权和 Session，Biz 不新增 App import。共享图表只增加可选 MACD primitive 接口，挂在实际 DIF series；图层异步更新不重建四窗格。其他对象／频度不发 XXM 请求，两类股票图表的旧路径已回归。只改指数页的最小宽度和页内 grid，离开后全站 1460px 规则恢复；没有改其他页面的布局。

## 连续基线与真实 API 对照

[算法验收 JSON](./algorithm_acceptance.json)记录 Spec、输入 manifest 哈希、内核文件哈希、检查方法及每周期汇总。逐事件和历史记录分别保存在 baseline_day／m60／m90／m120.json。M0 快照保持原样，见[原只读来源审计](/Users/congming/github/goldenshare/reports/xxm_source_audit_20261013_213852/README.md)；其中“调整待确认”是当时状态，当前确认已记录回原方案和 LLD。

| 周期 | 连续范围 | 输入根数 | 普通钝化／结构／取消 | 历史研究消失 | 历史结束／仍跟踪 | 独立事件前缀 |
| --- | --- | ---: | --- | ---: | --- | ---: |
| day | 2023-01-03—2026-10-13 | 912 | 29／16／13 | 3 | 8／1 | 63 |
| m60 | 2009-01-05—2026-10-13 | 17260 | 529／327／204 | 63 | 183／1 | 1130 |
| m90 | 2009-01-05—2026-10-13 | 12945 | 396／251／146 | 50 | 147／1 | 850 |
| m120 | 2009-01-05—2026-10-13 | 8630 | 271／155／116 | 27 | 80／0 | 572 |

共 39747 根，2615 个普通事件／历史创建与结束／输入末端独立重放前缀，完整前缀事件账本与一次回放相等。另做 15 处前缀／snapshot 恢复续接检查，源数值覆盖原冻结分钟 3161 根。原三组门槛的逐柱普通事件、参照及历史生命周期回归通过；这不是软件全历史准确率。

api_day_sample／api_m60_sample／api_m90_sample／api_m120_sample.json 来自真实 HTTP。1800 个返回逐柱对象、所有窗口事件和关联历史与同一正式源快照的离线内核逐字段相等。另保存过去窗口 2025-03-14 与 2025-07-03 的 90 分钟响应，过去的 endedAt／PENDING 不引用未来状态。2025-03-14 11:00 确有同柱底 STRUCTURE 和顶部 RESEARCH_HISTORICAL_WITHDRAWAL，普通状态为 NONE；两份事件参照均保留。

## 已有软件末端读数

[27 条读数 JSON](./software_readouts.json)及[CSV](./software_readouts.csv)保留素材位置、周期、完整柱端点、软件显示值、原图 SHA256、正式源原值、差值及显示精度匹配。已有 26 个分钟末端按 60／90／120 分钟各 7／7／12 个，另有一个日线末端。4 月 20 日被遮挡的柱值留空，未用 DIF／DEA 反推。

| 周期 | 软件减正式 DIF 范围 | DIF／DEA／柱值都按三位显示相同 |
| --- | --- | ---: |
| 60 分钟 | -0.020884～+0.038090 | 0 / 7 |
| 90 分钟 | -0.047829～-0.014162 | 0 / 7 |
| 120 分钟 | -0.000973～+0.000890 | 5 / 12 |
| 日线 | DIF 相同；DEA 软件 36.454、源 36.453；H 相同 | 0 / 1 |

这些差异没有被调参数、重算 MACD 或固定偏移抹平。既有视频是回归／读数对照资料，不能改称独立验证。后续其他视频仍需先登记冻结预测，再核对。

## 性能与资源

[API P95 明细](./api_p95.json)每周期各 20 个冷缓存及 20 个暖组真实 HTTP 样本，用 nearest-rank P95。8002 临时进程让查询缓存 get 恒不命中，其余实际 API、SQL、完整 Parquet 读取与内核保持；Python 和操作系统文件缓存未清空。因此这里测的是查询冷缓存，不宣称物理冷盘或服务启动 P95。暖组第一个请求可能实际填充缓存，保守保留在样本中。算法与完整窗口计算来自真实数据。

| 周期 | 冷缓存 P95 | 暖组 P95 | 目标 |
| --- | ---: | ---: | --- |
| day | 0.463s | 0.520s | ≤3s／≤1s |
| m60 | 2.583s | 0.675s | ≤3s／≤1s |
| m90 | 2.183s | 0.724s | ≤3s／≤1s |
| m120 | 1.985s | 0.688s | ≤3s／≤1s |

冷组最大 3.050s，未放宽 4s 请求硬预算。默认窗口最大响应 135924 字节，低于 1MiB。缓存按 Python 对象深度计量，64MiB／16 项，超过驱逐；最多两个请求并行、来源行数 20000、每流分区 5000。完整扫描的 DuckDB 连接单独设置 512MB／2 线程。应用加 DuckDB 的进程峰值为 1.168GiB；DuckDB 管理内存设置和缓存对象限额不等于进程 RSS 上限，上线前需在目标环境复测并发资源。

## 实际页面验收

四周期真实响应均正常显示研究身份、标记与详情。原日线均线／BOLL／趋势、分钟均线／BOLL、九转、成交量和 KDJ 继续存在。确认了：

- 黄钝化、紫结构、灰普通消失及绿色历史消失挂在 MACD DIF 时间／数值锚点；碰撞只调整文字，详情保留全部事件。
- 2025-03-14 90 分钟 11:00：底结构＋顶结构消失、普通 NONE，两份事件参照、保存价格峰和结束原因完整。历史日线上涨／平盘／下跌数缺失会显示原页面的“部分数据缺失”，XXM 自身为 READY，没有补造缺失值。
- 120 分钟原 2025-11-14 紫色顶部结构与 2026-01-06 绿色消失同屏，原标记未删；悬停读到旧价格峰、69 根跟踪和结束时间。
- 缩放、拖动、切换、鼠标离开正常；图层异步完成不重建图表，shared 单测同时验证范围不变。
- 实际 503 预算错误时 28 个画布／四窗格保留；恢复正常进程后，只点研究“重试”恢复 READY。发现并修复标题栏 pointer-events:none 对按钮的阻挡，仅研究状态区域启用点击。另作浏览器超时检查，临时拦截页已关闭；最终验收页无拦截。
- 30 分钟和深证指数实际详情页均无 XXM 请求／图层。两类股票 adapter 的共享生命周期回归通过。
- 1280／1440px 无页面横向滚动，图表右轴完整；离开到市场总览后原 1460px 最小宽度恢复。

截图：ui_day_1600／ui_m60_1600／ui_m90_1600／ui_m120_1600.jpg，ui_two_events.jpg，ui_history_withdrawal.jpg，ui_history_both_markers.jpg，ui_1280／ui_1440.jpg，ui_layer_failure_503／ui_layer_retry.jpg，ui_other_index.jpg。图片是实际页面，Figma 情景图未用作算法证据。

## 检查命令与结果

```bash
.venv/bin/python -B -m pytest -q scripts/research/index_market/tests/test_xxm_calculator.py tests/web/test_wealth_index_detail_xxm_api.py tests/test_major_index_mins_reader.py tests/test_major_index_mins_contract_alignment.py tests/web/test_wealth_index_detail_api.py tests/architecture/test_subsystem_dependency_matrix.py tests/architecture/test_index_daily_serving_guardrails.py
npm --prefix wealth run test -- --run src/features/index-detail src/pages/index-detail src/shared/charts/detail-workspace/DetailChartWorkspace.test.tsx src/features/stock-detail/chart
npm --prefix wealth run typecheck
npm --prefix wealth run build
.venv/bin/python -B -m scripts.research.index_market.xxm.acceptance --source reports/xxm_source_audit_20261013_213852 --research reports/xxm_macd_structure_20261011 --output reports/xxm_implementation_20261013
```

后端及边界 86 项通过；Wealth 16 个文件 98 项通过；typecheck/build 通过。源 reader 的 26 项合同／分页回归单独通过。既有 Starlette testclient 弃用提示及 Vite 主 chunk 约 1.44MB 提示保留，没有安装或升级工具。开发前使用 CodeGraph status/search/explore/impact，开发后 sync/status/impact；索引的 React 间接调用覆盖有限，以实际四个 chart adapter 代码及测试补核，无依赖矩阵变更。

## 改动文件与未关闭事项

后端新增 Biz 下 XXM services／queries／schema／两 router，App 只装配；Foundation reader 新增完整历史入口及签名，原分页保留。前端新增 index-detail/xxm，两个指数 adapter 消费，共享图表只新增可选 MACD primitive 接口。新增相应用例和离线验收入口；指数页 CSS 只承接已批准的尺寸修正。九份方案／研究／展示／索引文档及异常码登记同步；完整文件和 SHA256 清单见 manifest.json。

下一步是用户验收开发态结果，之后另定发布及其他视频验证。原软件公式、60／90 数值偏差、日线完整软件事件时间线、底部镜像、长历史寿命及算法初始历史截断继续未确认；源元数据 initialHistoryIncomplete 为 true。没有用源码一致性测试代替软件准确率，没有扩大对象／频度或实施交易操作。没有正式 DB／Lake 写入、DG 操作、安装、提交、推送或部署；已有无关工作区修改保持。
