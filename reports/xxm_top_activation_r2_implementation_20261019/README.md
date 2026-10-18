# 首次顶部钝化修订r2：开发与验收结果

2026-10-19。已按管理员确认的LLD完成本轮开发、冻结与隔离技术验证。范围只含首次顶部钝化及必要预测、身份和消费者联动；底部、已激活钝化、R1参照切换和等待重入规则保持。未提交、推送或部署，未访问正式数据库、Lake、DG或网络。

依据：[V0.1方案§12.46—§12.48及末尾修改表](../../docs/product/xxm-direction-algorithm-plan-v0.1.md)、[识别LLD§26—§30](../../wealth/docs/pages/index-detail/index-detail-xxm-implementation-and-low-level-design-v0.1.md)、[预测方案§32—§35](../../wealth/docs/pages/index-detail/index-detail-xxm-key-point-forecast-implementation-plan-v0.1.md)。当前分支为dev-interface，原有无关修改保留。

## 已完成的四项修改

| 项目 | 实际修改 | 解决的问题与范围 |
| --- | --- | --- |
| 识别 | calculator.step最后首次activation分支增加TOP当根DIF>0；原selector及此前转换分支不动 | 不能用本段曾经较高的DIF代替当前值；9/24原TOP钝化和9/25跟随取消链已去除，同段以后转正可正常激活 |
| 预测 | forecast_entry完整分界、稳定证明及原因同步；日线先按真实三位输入判正值，再使用原保守界；forecast_text写明“DIF未转为正值” | 识别拒绝时不再预测仍可触发；不以末尾删除例子代替求完整范围，不把未转正说成指标创新高；原guard／8ULP保持 |
| 版本与缓存 | 唯一检测器v0.1-r2、预测v0.3-r2；复用已有含hash的缓存key和restore拒绝检查 | 不延用旧series、旧预测或旧保存状态；sourceInputId／指标来源不变，无备用旧引擎或新配置 |
| 消费者 | Python预测DTO与TS两adapter严格核当前身份，新增原因仅允许NONE TOP activation；新路由响应驱动当前正向测试 | 错hash、旧版、原因错位／未知值被拒绝，旧JSON原样保留作反例；hook／Card／client原错误及迟到响应处理继续 |

实际文件清单及本轮前后SHA见[changed_files.json](changed_files.json)，共36个源文件、测试和原文档。本清单按开工时文件SHA计算，避免将此前尚未提交的R1等修改误算成本轮新增。新增报告和证据位于本目录；未改变业务分层或依赖矩阵。

当前固定身份：

| 身份 | 数值 |
| --- | --- |
| 检测器版本 | xxm-direction-v0.1-r2 |
| 主比例1.0 hash | 6db425730c72f22ea756c121a832f27c966d1324ef0a72a2312a3c572038724d |
| 比例0.75 hash | ddc241ad701a483a0e1659ed1a70ef46e695499199776c13694a29ddda3c1a04 |
| 比例1.2 hash | 81992335d6bd197e56cc2ff6d02b35fe46ddc61cfbeb282fb3e5e375bd3d2021 |
| 预测版本 | xxm-key-point-forecast-v0.3-r2 |
| 预测hash | add5e3636e6972e267bdda81c05e0e864f600f9e67d658b6a560445e39dda6d8 |

## 验收结果

| 检查 | 结果 | 证据及限制 |
| --- | --- | --- |
| 完整识别 | 三来源、三比例、24单元，共133653根完整step与开发前独立预期相符 | 旧分钟3161根、四周期39747根、2020起日线1643根，每组0.75／1.0／1.2。测试读取封存完整事件／历史／等待及最终snapshot，不调用改后研究候选生成expected |
| 冻结预测 | 1215项全部通过：711项原完整数学／display保持，504项独立完整域核验（213无入口、291第二根） | [frozen_06/result.json](frozen_06/result.json)；完整入口／参照／目标条件及展示范围核验，45处前缀恢复，4次模拟；最长82.94ms，原200ms门槛保持 |
| 新API与TS正向来源 | 18场景识别及预测响应均200，另401／403反例通过 | [api/result.json](api/result.json)；真实三路由／query／DTO、隔离SQLite和冻结字段fixture，非正式受保护服务或真实浏览器 |
| 2020起日线隔离 | 1643端点预测、94处识别前缀／恢复、4截图事件、20轮冷／20轮暖、LATEST及两并发均通过 | [daily_2020_01/result.json](daily_2020_01/result.json)；442份CALIBRATION_FAILED保护保留，最长模型162.22ms、扫历史请求174.10ms、响应最大13222字节、缓存最大1574852字节／2项；原4秒、32KiB、64MiB／16项保持 |
| Python相关主题与API | 434项通过；另98项收尾专项通过，后者包含在最终434项中，不累加 | [最终日志](logs/python_434.txt)；包括完整冻结三来源、字面门槛／旧历史、缓存旧key与混合hash、同版深复制、schema错位、源采集身份及已完成单元读回 |
| Wealth | 168个文件、1191项通过；typecheck与build通过 | [测试日志](logs/wealth_1191.txt)、[构建日志](logs/wealth_build.txt)、[类型检查](logs/wealth_typecheck.txt)；沿用已安装依赖，无安装／升级。现有构建大chunk和Starlette弃用警告保留，没有放宽门槛 |
| 内存与复核 | 冻结约212MiB、日线约119MiB，均低于256MiB；两批次原验收继续通过 | [资源记录](memory_measurements.json)、[冻结复核](frozen_08_memory/result.json)、[日线复核](daily_2020_02_memory/result.json)；日线最长171.51ms，冻结资源复核89.34ms；重复执行仅补资源测量，不累加独立样本 |
| 原件与最终对账 | 原冻结117文件、36份源／旧证据SHA保持；13个完整单元／身份记录读回通过；V0.1修改表仍在文末 | [保护检查](final_protection_checks.json)、[目录大小](report_size.json)；原分类文件不反写 |

日线94处恢复少于R1记录的97处，是本版识别事件减少后的实际数量，没有沿用旧数字。旧api_02的部分日线预测使用更短的912根输入，会因投影校准失败而与本次1643根不同；[oldCases字段](daily_2020_01/result.json)分列变化。该差异不是本轮改了底部规则，也不能把全部预测变化都归因于TOP条件。源重叠912根已逐值核对。

“52项软件观察”等旧证据的直接／映射等级不变。本轮完整识别通过的是实现与已冻结候选定义的一致性，4次模拟是旧观察回归，不是新增独立盲测、原软件准确率或收益回测。

## 已获准的18项分类更正

原准备清单只看NONE＋红段，漏看当根已确认的底部结构，错把18项列为首次TOP未来预测。这是验收分类错误；原query一直优先返回CONFIRMED，产品底部规则不应改变。

管理员确认“同意更正并继续”后，新增[更正记录](forecast_classification_correction.json)及SHA；原117文件和失败批次全部保留。当前711＋504替代旧693＋522，撤回旧分类对完整预测预期的通过结论。六时点各含0.75／1.0／1.2三比例：

| 周期 | 当根已确认底部结构的时点 |
| --- | --- |
| 日线 | 2024-08-15 |
| 60分钟 | 2022-09-27 14:00；2022-09-30 14:00 |
| 90分钟 | 2013-06-19 15:00；2019-01-03 14:00 |
| 120分钟 | 2024-08-13 15:00 |

每项原响应SHA、原确认事件、新旧context和原分类见[原提案](expected_classification_correction_proposal.md)及其JSON。没有用新算法结果反写expected。

## 失败与纠正记录

| 记录 | 原因与处理 | 未改动的产品口径 |
| --- | --- | --- |
| frozen_01 | 上述18项分类漏掉确认优先，按管理员批准加更正记录 | 底部确认仍优先 |
| frozen_02 | 新验收helper漏保存空前缀snapshot，补0位置记录 | 初始化／产品恢复规则不变 |
| frozen_03／04 | 验证器误把精确分数根当现浮点算式包络中心；现K为2/13−2/27，与分数直接转float相差一ULP | 分开核独立分数误差和实际中心±原8ULP，不扩大guard或数值预算；原failed_forecast保留 |
| 首轮核心测试 | 新零基值样例最后价格104突破结构峰103，却误断言全部无事件；补明确历史消失预期 | 普通STRUCTURE保持，历史消失不可吞掉 |
| 首轮426测试中的旧R1断言 | 仍期待已被R1参照切换替代的取消再激活，按未改动的救援分支及独立参照路径纠正字面 | 本轮不改底部实现 |
| 首轮响应大小夹具 | 通过替换Spec预算制造小限制导致Spec hash变化，被新DTO正确拒绝；改用超过真实32768字节的文案fixture验证503 | 真实大小门槛与双hash检查不放宽 |
| 首轮日线并发 | 与其他计算任务重叠时触发200ms；独立最终428／434完整重跑均通过 | 200ms不改；正式环境负载表现仍须后续实测 |
| 完成单元读回 | 三比例全复用时原汇总未取得events；单元中同时保存和读回events，补完整跳过计算／身份变化／SHA损坏测试 | 研究工具修正，不改产品；frozen_05原通过记录保留，最终代码复核用frozen_06 |

补测资源时，系统time工具在产品执行通过后，读取kern.clockrate被当前环境拒绝，统计命令因此退出1；[原失败日志](logs/frozen_07_memory_stat_failed.txt)及该批run.json保留。随后通过wait4仅读当前子进程的实际资源统计，两条现有CLI返回0且通过原验收。没有提权、安装或修改测试预算。

首次426项失败日志及核心失败日志见logs；frozen_01—04失败目录和frozen_05原通过目录保留。后续新批次没有覆盖旧结果。

## 当前代码与方案的对账

CodeGraph开工使用codegraph_explore及codegraph_impact（depth 2）覆盖solve_entry_ranges、query、calculator、DTO；图中旧报告同名符号及TS缺边已按真实导入补读。核验三API入口、App装配、query／cache／shared load、两条TS adapter／hook／Card及测试／验收委派。开发后[codegraph sync日志](logs/codegraph_sync.txt)报告Already up to date，status可读；未重建索引。未改变架构边界，无需改架构快照。

LLD§30.8逐条对应识别、预测、版本、消费者、真实隔离接口、继续执行和原预算。selector、forecast／paths／joint、来源查询与共享加载等未因本轮修订而改变，见changed_files及开工前manifest。现有旧研究子类在父类升级后不能当可运行r1基准；README已标明旧a1／r1入口为历史，新版验收复用reference_rescue_acceptance及daily_window原链。

继续执行仅复用同代码／源／预期身份、完整SHA和完成标记，损坏／身份变化拒绝；原CLI继续要求新目录，不新增resume参数。输出和临时SQLite仅在本轮目录或临时目录内，未写正式数据。产品原4秒、200ms、32KiB、识别1MiB／2000项、缓存64MiB／16项、两并发和客户端5秒保持。

## 未完成项与建议

1. 本版正式数据／受保护API的冷暖、并发和四周期整页尚未验收；本地冻结计时不能替代正式PG、Lake、网络或真实页面。
2. 2020年以前日线正式验收继续按[原TODO](../xxm_reference_rescue_r1_implementation_20261017/before_2020_pending.md)保留；本轮没有重查数据是否下载完成，不扩展当前范围。
3. 软件零值等号、首次黄字、实际采用哪个参照及OHLC依赖仍未知；已有支持可用于工程修订，但不宣称完全还原。当前不需管理员继续寻找同组图。
4. Figma、历史原型清退和发布另按原计划处理；旧页面的JavaScript不会自动换版，发布时须同批核前后端及刷新后的页面，不能承诺旧页面无刷新升级。

2026-10-19后续安排：管理员要求将上述真实数据接口的正确性、性能和四周期实际页面验收先记录为TODO，本次不执行。统一可勾选清单见[识别LLD§30.9](../../wealth/docs/pages/index-detail/index-detail-xxm-implementation-and-low-level-design-v0.1.md#309-r2后续验收todo2026-10-19管理员要求先记录)。本轮开发与已有测试成绩保留；2020以前日线继续按原TODO等待补齐。本次只更新待办，不改代码、原测试或验收数据，也不提交／部署。
