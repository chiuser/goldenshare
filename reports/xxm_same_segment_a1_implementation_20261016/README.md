# A组a1内核实施与验收（2026-10-16）

已按用户确认的算法方案§12.12及识别LLD §21完成唯一内核、接口／预测和Wealth消费者迁移。先提交方案与研究基线`f44c7bdebcf4ad0f1a5b0a9e916cbc9acf9e7482`，再开发；本轮开发改动按用户要求提交，未推送或部署，页面由用户验收。

目标仅上证指数日线、60／90／120分钟。没有修改原1%工作门槛、首次选峰、TOP规则、MACD、来源／完整历史校验、20点业务日期、调度、4秒／200ms、近期分位筛选或评分。不存在第二在线引擎、源码注入、数据库／Lake写入、依赖安装、服务重启、浏览器自动验收或新分支／worktree。

## 已交付行为

- 结构反向当根已符合价格／背离条件，直接回钝化，不添加绿色；8/14日线仍有黄、8/15新结构、8/22历史绿保留。
- 当根不够格则报“结构消失”，回NONE并保留原完整参照及最近价格门槛；后续根按当根收盘重新钝化。等待期间没有钝化，参照突破／红柱／零柱只结束等待，不伪造CANCEL。
- 识别层增加强关联等待账本及过去投影；原结构不在窗口内也能解析，未来的结束不会回流到旧端点。快照严格原子恢复、深拷贝和增量缓存隔离。
- 预测先求重新钝化完整范围，再求最近可成立结构的时点；真实DULL直接求结构。真实context在身份计算前加入响应，旧任意紫色不能冒充当前确认。近期展示及18个日线校准保护保持。
- 新A事件沿用原大点、粗字、左置／引导线布局，以绿色“消失”表示；详情区分当柱等待和记录结束，四周期卡片只显示后端display。

## 验收证据

| 范围 | 证据／结果 |
| --- | --- |
| 源码与旧研究封存 | [baseline.json](./baseline.json)及h1_research_source.zip，95份旧源码与55份源／旧证据SHA；旧失败和成功报告原封不动 |
| 完整冻结 | [frozen_final/summary.json](./frozen_final/summary.json)，39747根×0.75%／1%／1.2%；45前缀／恢复、369预测及模拟通过；主参数14次同段消失／7次重入、93条B历史绿，与_04逐事件／参照及等待生命周期相同 |
| 原软件保护 | 日线7/23、8/5、8/22及120分钟8/5、8/14五处保持；3959.16重入、3892.79真失效、3944.79保持；3960仅模型反例 |
| 全域与合同 | 后端261项主回归及40项最终文案回归通过（不相加计数）；包括TOP三门槛四周期完整回放、原普通首次、根与一ULP两侧、P—C／共同区间、等待快照、过去窗口、缓存修订、严格DTO、真实SQLite／临时Parquet路由及共享加载；[日志](./backend_tests_final.log) |
| 真实路由原响应 | [api/summary.json](./api/summary.json)，13组识别＋预测及401／403保护；封存字段仅替代分钟传输，核心query／calc／DTO真实执行；临时Parquet物理读取另在集成测试中执行，正式文件在预算和混合验收中执行 |
| 页面消费者 | 前端全量166文件1186项通过；最终XXM聚焦43项通过，真实路由JSON驱动两adapter、详情和卡片；typecheck／build通过；[全量](./frontend_all_tests_final.log)、[聚焦](./frontend_targeted_final.log)、[构建](./frontend_build_final.log) |
| 架构 | 16项边界护栏通过；CodeGraph explore／impact分析XxmCalculator及query／API／前端／测试共80符号，开发后sync／status正常；没有依赖矩阵变化 |
| 正式预算 | 首轮四周期160轮预测＋配对识别、4次LATEST通过，HTTP最大2.089秒，模型包络84.208ms；最终版另补两并发，结果见下方最终对账 |
| 整页／双标签 | [page_mix/page-mix.json](./page_mix/page-mix.json)，16组306请求全部200且小于4秒；HTTP最大3.041秒、模型包络27.225ms；缓存最大50109591字节／8项。cold每分钟周期只读bars＋indicators一对，warm零次完整读取；审计进程已退出 |

## 逐条方案对账

| LLD硬口径 | 代码与测试落点 | 结果 |
| --- | --- | --- |
| A01 当根够格直回钝化 | calculator._qualifies_bottom_close／step；8月链及三门槛测试 | 通过，无无条件等待 |
| A02 不够格消失并等待 | _start_rearm／_advance_bottom_history；严格事件及原B关联 | 通过，不同一结构A／B重复绿 |
| A03 原参照、当根价重入 | _advance_rearm、forecast_entry及完整域回放 | 通过，旧低点和等号不能重入 |
| A04 终止不伪造钝化取消 | _end_rearm；突破／红／零反例 | 通过，保留结束原因 |
| A05 原首次、TOP、B保护 | 未变分段／选峰源码校验；全历史TOP oracle、五处B保护 | 通过；两条无独立软件真值的90分钟差异继续列为限制 |
| A06 截止端点及可解析关联 | SeriesEntry、_project_rearm_record、两DTO／adapter | 通过；单柱窗口、未来结束遮蔽、旧点引用已结束记录 |
| A07 唯一真实内核及预测 | clone、activation_signature、_active_confirmation、rearmContext／display | 通过；不修改forecast／forecast_joint的P—C几何 |
| A08 唯一合同一次迁移 | a1 Spec／hash、识别及预测schema／types／adapter／fixtures | 通过，旧h1快照和v0.2响应拒绝，无默认兼容字段 |
| A09 四周期、原来源及预算 | 原source／runtime／scheduler保持；物理源／并发与旧源错误测试 | 技术验证通过，最终预算见下方 |
| A10 研究退场与追溯 | 候选／旧runner／临时研究测试删除；案例迁正式测试，same_segment_acceptance只运行产品 | 通过，ZIP保留旧源与依赖SHA |

## 文件与边界

产品修改集中在`src/biz/services/wealth/market/index_detail_xxm/`（types、Spec、唯一calculator、forecast_detector／entry／spec／text），`src/biz/queries/wealth/market/index_detail_xxm/`两query、两XXM schema，以及Wealth的xxm／xxm-forecast类型、adapter、primitive／详情和测试。HTTP URL、参数、鉴权及入口行为保持原范围；批准的新合同字段一次迁移全部消费者。

研究验收位于`scripts/research/index_market/xxm/`和主题tests；没有把执行脚本新放入reports。原三方案／LLD与文末核心修改表同步。其他Lake、新闻及P0文件保持用户工作区原状，未纳入前置提交。

## 复现与限制

使用README当前`same_segment_acceptance`命令，frozen／api／budget均须新output目录，budget显式`--formal-source`且只读。混合验收沿用`xxm_page_request_audit`原TS客户端／调度及HTTP。日线912根、60分钟17260、90分钟12945、120分钟8630；冻结输入截至2026-10-13，正式来源重叠必须完全一致，后续追加可读取。

未确认项没有扩大为公式事实：1%精确门槛、OHLC依赖、原软件历史寿命、2024/9/24—9/25顶部疑报，以及两条90分钟被等待链移除的旧历史绿（2022/3/7、2023/8/16）没有新增软件真值。新工作版本与已确认图文相容，不能说所有信号已与原软件完全一致。页面仍需用户验收。

## 最终预算及交付对账

[budget_final/summary.json](./budget_final/summary.json)及[分阶段计时](./budget_final/budget_records.json)全部通过。正式输入截至2026-10-15，四周期与10/13冻结重叠全部相同。冷为应用series／forecast cache清空，OS与数据库缓冲保留；不把应用冷读称作磁盘首次读取。

| 周期 | 冷＋暖预测轮次 | 预测HTTP最大 | 配对识别HTTP最大 | 模型保守包络最大 | 正式根数 |
| --- | --- | --- | --- | --- | --- |
| day | 20＋20 | 0.367秒 | 0.459秒 | 93.074ms | 914 |
| m60 | 20＋20 | 2.082秒 | 0.636秒 | 27.514ms | 17268 |
| m90 | 20＋20 | 2.128秒 | 0.814秒 | 32.781ms | 12951 |
| m120 | 20＋20 | 2.085秒 | 0.476秒 | 15.630ms | 8634 |

160轮预测及配对识别（320请求）、4次LATEST、四周期各一组识别／预测两并发（8请求）全部通过；另16组整页／双标签306请求通过。两并发HTTP最大2.117秒、完整单请求最大2.128秒，模型包络93.074ms。单次识别最大686669字节、预测最大11663字节；混合缓存最大50109591字节／8项；1MiB／32KiB、64MiB／16项、4秒／200ms和两源槽位均未调整。分阶段sourceCheck／sourceRead／detectorStep／DTO计时仅在隔离验收进程中记录，不增加产品调试字段；模型计时包络含尾部组装，比纯数学计时更保守。

前端全量1186项后，最终共享时间校验又经43项XXM聚焦测试、typecheck和构建验证；后端261项主回归后，最终40项展示回归通过（与主回归有重叠，不相加计数）。文档完整性与git diff空白检查通过。构建仅保留既有大chunk提示，未为本任务改打包配置；Starlette测试依赖提示没有引发失败，未安装或升级依赖。

本轮所有A01—A10技术门禁已经完成。算法方案文末表格、识别LLD §22和预测方案§27已同步。页面人工验收和未明确软件公式仍保留；新增开发文件已按用户要求在dev-interface提交供review，未推送或部署。
