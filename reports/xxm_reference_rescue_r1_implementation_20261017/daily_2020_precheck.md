# 2020年起日线隔离预检结果

2026-10-17。按用户“先做2020年之后、更早时间记录后等补齐再做”的安排，完成上证指数`000001.SH`日线2020-01-02至2026-10-16的隔离预检。1643个收盘时点、97处前缀／恢复核对及4个已确认截图事件通过；模型最大包络159.519ms，保持200ms预算。全历史正式接口及四周期整页仍待更早数据补齐，不能由本结果替代。

机器结果见[汇总](daily_2020_precheck_summary.json)、[完整运行](daily_2020_check_01/result.json)；更早历史见[待办记录](before_2020_pending.md)。页面仍由用户验收。

## 输入、方法和验收边界

输入于14:05:59从正式数据库的只读一致快照取得，只投影当前`IndexFactorPro`的交易日期、收盘、DIF、DEA、MACD，以及SSE开闭市日历。日期范围必须从2020-01-01逐日对齐开市日，首日缺失也拒绝；保留原有限值、正收盘和连续性校验。1000行分页，上限2000日线行／3000日历行；本次分别1643／2571行。来源与校验哈希见[冻结清单](daily_2020_source_01/manifest.json)。

隔离执行只替代存储、时钟与鉴权：把真实字段投影放入内存SQLite，建表／装载后启用`query_only`，时钟固定为采集时刻；其余使用当前真实路由、query、唯一计算内核、原校准保护和DTO。没有修改产品`read_daily`的完整历史范围，没有修改算法、参数、容差、API或依赖方向。

因此下表的请求计时属于本地TestClient／SQLite链，不是正式PostgreSQL、网络HTTP、登录服务或页面性能验收；未声明完整四周期整页通过。本轮未安装依赖、修改正式数据、重启产品服务、操作浏览器、提交、推送或部署。

## 计算和预算

| 验证项 | 本轮结果 | 依据 |
| --- | --- | --- |
| 范围完整性 | 1643根，与整个显式范围的SSE开市日完全相同 | `daily_2020_source_01` |
| 冻结重叠 | 原M0的912条逐值相同 | `result.json.frozenOverlap` |
| 逐根识别 | 93个事件；97处完整前缀／快照恢复一致 | [事件账本](daily_2020_check_01/recognition_ledger.json) |
| 独立截图保护 | 2024/7/23、8/5、8/22底部历史消失及8/15底部结构均存在 | 工具中的4条字面断言，预期未由待测实现生成 |
| 逐端点预测 | 1643份真实路由／DTO响应，计算前后真实状态快照相同 | [逐时点原响应](daily_2020_check_01/forecasts.jsonl) |
| 计算包络 | 最大159.519ms，出现在2024/12/9；上限200ms | 同上；包络含求解、展示及相关校准，含测量开销 |
| 预测响应 | 最大13222B；上限32768B | 同上 |
| 本地逐时点请求 | 最大0.185秒；上限4秒 | 同上；不含真实PG／网络链 |
| 20冷＋20暖 | 冷轮各1691次step（1643真实根＋48假设根）；暖轮各0次step | [完整预算记录](daily_2020_check_01/result.json) |
| 冷／暖预测请求 | 最大0.0441／0.0142秒；配对识别最大0.0344／0.0454秒 | 同上；均为本地链 |
| 缓存 | 冷暖配对每轮1577017B／2项；上限64MiB／16项 | 同上 |
| LATEST及并发 | LATEST截止10/16；空缓存识别／预测两并发通过且输入身份相同 | [LATEST](daily_2020_check_01/latest.json)及`concurrentPairPassed` |

1643份预测中，442份为`PRECISION_PENDING / CALIBRATION_FAILED`、24份`CONFIRMED`、431份`NO_CANDIDATE / NO_ENTRY_RANGE`、647份`CONDITIONAL_ENTRY`、99份`READY`。442份保护分布在2020/1/2至2021/11/5之间，并非连续442根；保留了原校准保护，没有强行输出确定点位。通过含义是计算、合同、保护和预算符合当前模型，不能解释为每个时点都能预测或均已与原软件核对。

## 与旧日线案例的差异

旧夹具只从2023-01-03开始；本轮增加了真实2020前缀，原始重叠值完全相同。5个旧场景均记录完整数学／display差异，没有为保持旧JSON而截短输入或改预期。

| 截止日期 | 旧2023前缀 | 新2020前缀 | 校准的独立核算 |
| --- | --- | --- | --- |
| 2024/7/23 | 校准保护 | 条件触发 | 最近250根最大误差由0.001006336降至0.000496729，超容差根数15→0 |
| 2024/8/5 | 校准保护 | 条件触发 | 0.000693770→0.000496729，8→0 |
| 2024/8/22 | 校准保护 | 无近期触发范围 | 0.000557297→0.000496729，2→0；当日历史消失事件仍存在 |
| 2024/8/15 | 已形成结构 | 已形成结构 | 完整数学／display字段无差异 |
| 2026/10/13 | 条件触发 | 条件触发 | 完整数学／display字段无差异 |

独立核算使用50位Decimal逐根EMA12／EMA26、DEA9及双倍柱值，未调用产品projection helper；在各截止时点比较最近250根的DIF／DEA／MACD，保持0.0005原容差。数值及旧／新CSV哈希见[前缀校准证据](daily_2020_check_01/calibration_prefix_evidence.json)。这解释了三个旧场景解除校准保护的原因，不证明徐小明软件通用公式或其余八处R1切换真值。

## 工具、测试及计划对账

新增`xxm/daily_window_precheck.py`及`test_xxm_daily_window_precheck.py`。原验收工具的暖缓存断言另有一处纠正：当前日线设计仍读取完整SQL投影核源，随后复用计算缓存；暖请求以零内核重算为必要条件。分钟暖请求继续同时要求零完整读源。此前通用断言把日线正常核源误判为冷读，本轮只修工具，未改读取层或放宽预算。`test_xxm_acceptance_scope.py`覆盖日线暖读取允许、暖重算拒绝、分钟暖重读拒绝和冷无读源拒绝。

主题内24项测试通过，覆盖真实字段投影、2019记录排除、2020首日／中间缺口、重复／越界、非有限值／负收盘、缺闭市日、冻结时钟、内存只读与缺未来日历拒绝。CLI使用新目录并拒绝覆盖。测试替代了真实数据库；正式输入另由本次只读采集证明，运行结果不超出上述边界。

[源码清单](daily_2020_source_code_manifest.json)核对上轮30份文件：25份产品／前端消费者全部未变，只有验收工具及其测试2份已有文件变化；另列新增工具／测试2份。CodeGraph explore核对`load_entry → SeriesEntry／calculator_at → recover_projection → forecast build`及API消费者；无新增业务依赖、合同或配置，架构快照无须更新。

原方案和LLD中“尚待用户选择”为历史状态，已由本轮选择及结果接续；最新缺口记录独立保存，不把13:39的626条改写为14:13的296条。方案、LLD及研究总记只同步本轮主题状态，不改其他未提交工作。

复现命令（OUT必须是全新目录，采集阶段需本机数据库只读权限）：

```sh
.venv/bin/python -B -m scripts.research.index_market.xxm.daily_window_precheck --capture-source --output reports/xxm_daily_2020_source_NEW
.venv/bin/python -B -m scripts.research.index_market.xxm.daily_window_precheck --source reports/xxm_daily_2020_source_NEW --output reports/xxm_daily_2020_check_NEW
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -B -m pytest -q -p no:cacheprovider scripts/research/index_market/tests/test_xxm_daily_window_precheck.py scripts/research/index_market/tests/test_xxm_acceptance_scope.py
```

后续按[更早历史待办](before_2020_pending.md)恢复全历史正式日线及完整四周期16组混合／双标签；Figma文字、研究原型清退继续保留为原整体交付待办。本轮结果不自动触发补录或后续验收。

## 收尾检查

- 上述主题测试最终24项通过（0.85秒），1条既有Starlette／httpx弃用警告，未安装依赖。
- `scripts/check_docs_integrity.py`三组检查通过；另检查本主题9份文档的585个本地链接，零缺失；该检查不证明算法正确。
- 已跟踪主题文件`git diff --check`及新增工具／测试／报告尾部空白检查通过；32份源码SHA复核相同，V0.1核心修改表仍是文末最后一节。
- `codegraph sync`、`codegraph status`均确认索引为最新。没有因普通验收工具新增而重建索引或更新架构快照。

文档核对只处理本主题：原方案、LLD、研究总记及恢复报告中的旧“待用户选择”状态保留为历史，并由本轮结果接续；更早缺口数量注明快照时间，避免把下载中的来源变化误写成算法失败。没有扩大文档目录治理或修改其他工作区主题。
