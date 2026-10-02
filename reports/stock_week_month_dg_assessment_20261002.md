# 股票周／月行情接入 DG：只读审计与整体评估

审计日期：2026-10-02，Asia/Shanghai；主要数据查询在 19:00–19:43 完成。本文是接入建议，不是已批准的实施方案。本轮没有修改实现、Prod、正式 Lake 或 Dagster instance。

> 2026-10-02 补充复核：本文关于“2020-02-28 是异常、Silver 优先采用 29 日”的初步建议已撤回。Tushare 当前对 28 日与 29 日均返回月线；28 日 Prod 存量与源端逐字段完全一致。两日的代码集合、复权版本不同，暂时保留两批源事实，不删除、不改日期。详见 [专项复核](/Users/congming/github/goldenshare/reports/stock_month_20200228_29_verification_20261002.md)。下文相关旧判断仅保留审计历史，不能作为执行依据。

> 管理员后续决定：2020 年 2 月在 DG 接入中只采用 2020-02-28 的未复权与复权月线，不使用 2020-02-29 月线。该决定覆盖本文此前关于保留两日期供 DG 使用的建议；本轮不删除 Prod 记录。Bootstrap 排除 29 日须作为明确过滤规则对账。其余月份的日期规则没有在本轮改为最后交易日。

> 2026-10-03 最新方向：管理员决定不在 Prod 回补剩余历史周线，改在 DG Raw 使用备用源 `weekly` 补齐。正式提案见 [DG 周线备用源 Raw 补齐方案](../lake_console/docs/design/dagster-stock-weekly-alternate-source-raw-backfill-plan-v1.md)。主源与备用源分别保留 Raw 原值，按同一自然周审计覆盖；备用源与主源在日期、成交量／金额和涨跌幅单位上存在差异，消费层需要最小标准化。首期备用补齐只证明未复权，不能据此声称复权完整。2026-10-02 所在周暂不处理。本文以下数量及缺口判断保留为早期审计快照，以后续完整复核及新方案为当前依据。

## 结论

可以采用“Prod Raw 全量 bootstrap + Tushare 按周期锚点维护”的路线。建议先确定未复权两个数据集是否为首期范围；复权两个数据集已一起审计，但涉及额外的历史价格修订问题。DG 沿用 Prod 的自然周五／自然月末业务日期口径，明确传入日期，不复用 Prod 当前缺省日期的调度行为。

Raw 保留全部历史业务记录，包括退市股票、异常历史锚点和空 end_date。Silver 不需要从日线重新计算周／月 OHLC，也没有证据支持普遍删除价格记录；但发现了历史月份重复与日期异常，不能未经处理直接承诺 Silver 全量透传。

bootstrap 和源端缺口修复分为两步：先证明 DG Raw 与 Prod 导出一致，再单独从 Tushare 补齐已核实缺口。否则 bootstrap 验收无法区分复制差异和新补数据。

## 依据与范围

已阅读根与相关子目录 AGENTS、[架构边界](/Users/congming/github/goldenshare/docs/architecture/subsystem-boundary-plan.md)、DG [编码规范](/Users/congming/github/goldenshare/lake_console/orchestrator/CODING_STANDARDS.md)、[新增数据集模板](/Users/congming/github/goldenshare/lake_console/docs/templates/dagster-dataset-onboarding-template.html)、[Schema Contract](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-asset-schema-contract-design.md)和[性能治理](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-data-pipeline-performance-governance.md)。

使用 CodeGraph explore/search 核验定义、planner、request builder 和日期归一化入口，再直接阅读当前代码，追到 Ops schedule → TaskRun → dispatcher → 日期验证 → Tushare 请求，以及 Raw/Serving 模型、Quote 消费者和 DG 日线 Silver。CodeGraph 的同名方法命中不能代替实际 dispatcher 核验。没有实施任何契约或依赖变更。

Prod SQL 使用只读事务及 30–60 秒 statement timeout；查询汇总、索引、周期覆盖和 TaskRun，不导出全量行情到本机。本轮不是全字段数值对账：价格检查覆盖基础 OHLC、成交量/金额；复权各价格列未完成全历史逐行质量检查。

## Prod 现状

| 数据集 | Tushare API | 精确行数 | 股票数 | 最早锚点 | 最晚锚点 |
|---|---|---:|---:|---|---|
| stk_period_bar_week | stk_weekly_monthly | 2,883,952 | 5,623 | 2010-01-01 | 2026-09-18 |
| stk_period_bar_month | stk_weekly_monthly | 703,828 | 5,629 | 2010-01-31 | 2026-09-30 |
| stk_period_bar_adj_week | stk_week_month_adj | 2,879,431 | 5,615 | 2010-01-01 | 2026-09-18 |
| stk_period_bar_adj_month | stk_week_month_adj | 703,052 | 5,622 | 2010-01-31 | 2026-09-30 |

未复权共 3,587,780 行；复权共 3,582,483 行。分别存于 raw_tushare.stk_period_bar / stk_period_bar_adj，每张表共用 week/month，主键为 (ts_code, trade_date, freq)。Bootstrap 应读取这两张 Raw 表，按 freq 拆分 DG 数据集，不从 Serving 反推 Raw。

源字段未复权 13 列，复权 21 列。Raw 使用 change；Prod Serving 的转换才改名 change_amount。api_name、fetched_at、raw_payload 是 Prod 存储内部字段，不进入 DG 行情字段；来源与导出时间写运行 metadata。字段与数值精度决策仍须落入正式 schema：建议价格/成交额等保持与 Prod Numeric 对齐的 DECIMAL，避免复制时先转 DOUBLE 后声称精确一致。

Prod 日线始于 1990-12-19，周／月线始于 2010 年。1990–2009 年属于 Prod 原本没有的周／月历史范围，bootstrap 不能补出。Tushare 000001.SZ 对象过滤样本返回 1,780 条周线，最早 1991-04-05，说明至少该样本有更早源数据；不能据一个样本承诺全市场早期覆盖。

精确汇总 CSV：[Prod 概况](/Users/congming/github/goldenshare/reports/stock_week_month_prod_summary_20261002.csv)。

## 同步日期：继承业务口径，显式生成锚点

当前 [DatasetDefinition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/market_equity.py:2402)规定：周线是 natural_day + week_friday，月线是 natural_day + month_last_calendar_day；周期适用性要求该周期存在开市日。[Unit planner](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py:301)枚举自然周五／自然月末，[request builder](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py:1079)以 freq 和明确 trade_date 请求。

Prod 活跃周线 schedule 在周五 22:03/22:04 执行，但 time_input 仅有 mode=point。[Dispatcher](/Users/congming/github/goldenshare/src/ops/runtime/task_run_dispatcher.py:1019)会补最近开市日期，[实际查询](/Users/congming/github/goldenshare/src/ops/runtime/task_run_dispatcher.py:1518)确认如此；这与节假日周五的自然锚点不一致。2026-09-25 的 TaskRun 13413/13414 均为 invalid_anchor_date。2026-06-19 的 3229/3230 为 worker_error，仅凭当前日志摘要不能断言与 9 月同一直接原因。

月线每个数据集有 19:35 与 22:08/22:09 两个活跃 schedule。虽然 cron 字符串含每日通配符，[monthly_last_day 策略](/Users/congming/github/goldenshare/src/ops/services/schedule_planner.py:89)实际只在自然月末生成运行，且显式填写月末日期；不应误读为 Prod 每天刷新月线。

DG 建议：

- 周线按完整 ISO 周生成自然周五锚点；月线按完整自然月生成最后一个自然日锚点。锚点当天休市也保留，周期完全休市才判为不适用。
- 请求使用全市场 freq + 明确 trade_date + 显式字段列表，不以最近交易日替换锚点，不默认逐股票下载，不使用当前上市股票池过滤 bootstrap。
- 历史范围按上述锚点逐周期维护；日常在周期结束并经过源更新窗口后请求。首期可参考 Prod 22 点时段，具体调度与重试预算在 LLD 明确，避免照搬两套月末重复调度。
- 周／月分区模型独立登记，不能直接复用 stock_trade_days。启动范围、过期判定和 completeness 以日历及周期结束时间计算，不能只看已经注册的分区或文件最大日期。

分区与检查方式参照 [Dagster 官方分区文档](https://docs.dagster.io/guides/build/partitions-and-backfills/partitioning-assets)和[官方资产检查](https://docs.dagster.io/guides/test/asset-checks)，实现按仓库现行 catalog/helper/run contract 登记，不新增另一份手写资产事实表。

## Tushare 实测

已用 tushareMcp 验证默认字段、显式字段、对象过滤、日期点、日期范围和不传日期的返回。对应本地文档为 [336](</Users/congming/github/goldenshare/docs/sources/tushare/股票数据/行情数据/0336_股票周_月线行情(每日更新).md>)与 [365](</Users/congming/github/goldenshare/docs/sources/tushare/股票数据/行情数据/0365_股票周_月线行情(复权--每日更新).md>)。

- 000001.SZ：week=20260501（节假日周五）和 month=20260531（周日月末）均有记录；20260921 周一和 20260529 最后交易日用作对应锚点时均为空。
- 整周休市的 20260220 周线为空；20261002 周线已经返回，锚点仍为 10 月 2 日，而 end_date 为 9 月 30 日。
- 20260427–20260508 日期区间返回 20260501、20260508 两条周线。
- 不传日期、仅指定 freq=week 时返回 6,000 行并有截断提示；不能把这次响应当全集 bootstrap。
- 20260619 的 000001.SZ 周线源端存在，close=10.52；20260925 源端也有样本。月线缺失候选 001237.SZ/20260531 目前源端返回 close=70.74。
- 默认字段与显式请求已覆盖未复权 13 列及复权 21 列；复权版本尚未完成与未复权同等完整的全部输入模式矩阵。

重要未完成证据：当前 MCP schema 不暴露 limit/offset，无法通过它完成真实分页验证。Prod 实现配置为 limit=6000 的 offset/limit 分页，但代码支持不等于源行为已验收。正式接入前须通过获准的现有源资源补齐小页分页与边界验证，无需安装依赖。每周期全市场目前约 5,500 行，但未来达到 6,000 或历史返回不同规模时仍必须支持完整分页。

## 与日线覆盖对账

期望集合定义为：同一股票在该周／月有至少一条 Prod Raw 日线，则期望有对应自然周期锚点的周／月线。它用于发现候选缺口，不等于证明 Tushare 必然为每个候选返回记录。没有把全部上市股票乘以全部周期，也没有要求停牌股票每天有行情。

2010–2026 全历史已经完成“周期锚点是否整批缺失”检查：仅发现 2026-06-19、2026-09-25 两个已完成周缺失；没有整月缺失。2026-10-02 也尚未入库，但审计时为 19:43，早于 Prod 当晚 22:03/22:04 调度，单独列为未到时，不计逾期缺口。

2026 年逐股票／周期对账（日线截至 9 月 30 日）：

| 类型 | 未复权缺失键 | 复权缺失键 | 说明 |
|---|---:|---:|---|
| 2026-06-19 周线 | 5,517 | 5,517 | 整周缺失，两次 TaskRun 失败 |
| 2026-09-25 周线 | 5,559 | 5,559 | 整周缺失，两次 invalid_anchor_date |
| 其他已完成周 | 30 | 29 | 4–6 月零星股票候选，需要逐项查源及身份 |
| 已完成周合计 | 11,106 | 11,105 | 排除尚未到时的 2026-10-02 |
| 月线 | 6 | 6 | 全部集中在 2026-05-31 |

月线六个候选为 001237.SZ、603435.SH、688635.SH、920161.BJ、920218.BJ、920220.BJ；其中 001237.SZ 已证实源端目前有数据。周线零星候选包括新股与 603843.SH，不能未经身份/源端核实就自动定义为入库故障。

完整逐周期 CSV：[2026 年覆盖](/Users/congming/github/goldenshare/reports/stock_week_month_daily_coverage_2026_20261002.csv)，包含 expected、missing、BJ 分类、缺失样本和 period_state。该 CSV 包含 10 月 2 日的预期集合，汇总时必须排除 not_due_at_audit。

2010–2025 全历史逐股票／周期键的单次汇总查询触及 60 秒上限，已停止，未输出有效结果。因此本文不能宣称“历史只有以上零星缺口”；实施前要用有预算的分批审计补齐。OHLC 与日线聚合的全历史数值一致性也尚未验收，不能把键覆盖当作价格一致性证明。

## Raw 与 Silver

Raw：按源字段保留全量业务记录，主键至少含 ts_code/trade_date/freq；即便 freq 拆为两个数据集，也保留或正式说明字段投影。不得套用 DG 日线 Silver 的 2014 年下限、当前上市状态或 BJ 开市时间来删 Raw。历史异常锚点也必须能归档，不能因“月份日期必须是月末”的新写入校验拒绝 bootstrap 全量。

当前两张表基础 OHLC/vol/amount 全历史的空值、OHLC 包络非法、非正收盘价与负成交量/金额检查均为 0。end_date 则存在空值、晚于或早于 trade_date；源端目前重取历史样本也会改变它。不能用 end_date 作为周期末最后交易日、完整性判断或新数据下载游标，Raw/Silver 都不能因它晚于锚点而删行。

2020 年 2 月异常：

| 类型 | 2 月 28 日行数 | 2 月 29 日行数 | 两日股票重叠 | 重叠行情数值不同 |
|---|---:|---:|---:|---:|
| 未复权 | 3,632 | 3,682 | 3,588 | 0 |
| 复权 | 3,625 | 3,682 | 3,588 | 682 |

数值比较包含基础行情列，复权另外包含 qfq/hfq 八列，不把 end_date 算作行情价格差异。未复权另有 44 条、复权另有 37 条异常日期记录，没有同代码的 2 月 29 日记录。直接全部删除 28 日或全部改成 29 日都会造成丢数或冲突。

Silver 建议做日期/类型标准化与必要的 change→change_amount 映射，不重新计算 OHLC，不强制删除退市历史。对 2020 年 2 月单独做证据化规则：有正常月末行的优先保留正常锚点版本；没有对应正常行的先查源、核实身份和日线聚合再决定归一化。这是待批准建议，尤其复权不同值不能直接选定真值。Raw 保持全部原始记录，Silver 差异必须有原因与数量对账。

现行 [DG 日线 Silver](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/duckdb_sql.py:302)有 2014 下限和生命周期点日期过滤。周／月锚点可能晚于退市日，而周期内仍有有效成交；如引入生命周期约束，应判断周期窗口与有效生命周期相交，不能复制日线单点规则。Silver 默认建议保留 Prod 2010 年以来有效历史；是否额外限制研究范围须另行确认。

## 建议实施次序与验收

1. 确定首期范围，按 DG 模板补齐正式技术方案/LLD：资产名、字段类型、独立周期分区、日常下载日期、历史异常规则、Prod 两张只读表的 whitelist、写入 unit、取消/续跑、进度、请求预算、生产 checks。复权如纳入，还需验证历史 qfq/hfq 修订的影响，不能默认“只追加新周期”保证全历史复权价格持续一致。
2. 先做代表性 bootstrap 候选：正常周、节假日周五、休市月末、2020 年 2 月、退市/BJ/新股样本；核对 Prod→Raw 业务字段、精度、键、行数与双向差异，并验证中断续跑。不修改 Prod。
3. 分批全量 bootstrap。读取层保持批次内存上限，避免按每个锚点重复全表扫描；当前仅有以 ts_code 为首列的 PK 索引，应先量测游标/主键分页方案，不为此次审计擅自给 Prod 加索引。候选与 checkpoint 位于 /Volumes/datasource/data_lake_staging，完成文件校验后以同文件系统 os.replace 逐文件提升到 /Volumes/datasource/data_lake/raw；没有多文件整体原子保证，续跑须核验每个文件事实。
4. Raw 复制验收通过，再按批准的 Silver 规则生成候选并对账。传输一致性可以通过，但源数据覆盖缺口仍需保留为单独质量证据，不能为了历史全绿伪造覆盖检查。
5. 单独补齐已证实的 Prod 历史缺口到 DG，并完成剩余候选查源、历史分批覆盖审计和分页验收；是否修复 Prod 是另一项任务。
6. 最后接入日常周期调度与有上限的重试；bootstrap job 不由日常 sensor/schedule 触发，不让日常任务一次吞掉全部历史缺口。动态分区注册、正式写湖、job/backfill 和 runless event 均按阶段批准。

目前未复权一组共 1,057 个实际历史日期（855 周、202 月，月份包含 2020-02-28 额外日期）；复权相同。若采用每日期单文件布局，一组 Raw+Silver 约 2,114 个文件，四个数据集约 4,228 个，异常 Silver 处理可能改变文件数。这是布局估算，不是源请求数或耗时实测。文件量、数据库读取耗时、源分页次数和事件量必须在代表性试运行后补齐预算。

本轮只新增 reports 下本评估及两份 CSV，不影响边界/依赖矩阵，不提交、不部署。下一步应先冻结上述范围与异常处理口径，再编制正式接入方案；当前风险是历史零星覆盖未完成、分页实测不足、复权历史版本差异和 bootstrap 读取性能尚未量测。
