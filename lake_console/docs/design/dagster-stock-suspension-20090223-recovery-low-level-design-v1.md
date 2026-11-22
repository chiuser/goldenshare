# 平安银行 2009 年 2 月 23 日停牌订正及 DG 补数详细设计（LLD）

**需求暂缓（2026 年 11 月 23 日）。** 管理员决定暂缓 2009 年 2 月 23 日的专项补数。该日超出 DG 股票停复牌、股票日线和股票分钟行情 Silver 的正式历史范围。暂缓开发、事实登记及正式补数。

本详细设计于 2026 年 11 月 22 日编写，对应[补数方案](dagster-stock-suspension-20090223-recovery-plan-v1.md)。下文保留只读核验结果和原定执行步骤，供恢复需求时查阅。

## 1. 交付范围和运行顺序

补一个交易日 `2009-02-23`。登记的停牌事实只涉及 `000001.SZ`，当日正式停复牌、股票日线和股票分钟行情文件按各资产的市场范围验收。按以下顺序手动推进，每步用正式文件读回和已有检查结果放行下一步。

1. 登记 `000001.SZ` 下午停牌事实，补股票停复牌 Raw 和 Silver。
2. 补股票日线 Raw 和 Silver，确认包含该股票当天的交易记录。
3. 复用已有五份股票分钟 Raw，补 1、5、15、30、60 分钟股票分钟行情 Silver。
4. 用已验收的同日日线和分钟行情补依赖齐备的派生资产。股票日线前复权 Gold 在补齐所需前日行情后验收。其他依赖历史输入的资产按第 5 节核实。

本次设计只放行目标交易日所需的 DG 本地资产。服务表发布、其他交易日和历史状态重算分别按实际需要确认范围。按日切分的正式文件包含合约要求的市场数据，单只股票的样本用于核验业务事实。

## 2. 怎样只补这一天

### 2.1 需要对齐的日期判断

只读结果如下。DG 交易日历标明 2009 年 2 月 23 日开市，前一交易日是 2 月 20 日。Dagster 已在 `cn_a_stock_mins_trade_days` 登记这一天，五个原生频度的 Raw 各有一条产出记录。`cn_a_stock_trade_days` 和 `cn_a_stock_mins_silver_trade_days` 目前都未登记目标日。Raw 的产出记录要和对应文件、检查结果一起读回。

| 当前代码 | 要改或核对的地方 | 验收 |
| --- | --- | --- |
| `checks/stock_partition_checks.py` 的 `_stock_partition_key_allowed_result` | 保留正常的 2014 年起始日期。在股票停复牌 Raw/Silver、股票日线 Raw/Silver、市场宽度和股票收益分布共用的股票日期检查中，允许明确列出的 `2009-02-23`。仍要求分区已登记、日期符合现有非未来日检查。 | 隔离环境中，登记目标日并取现有日历为开市，六个检查可通过该日期判断。无登记时不通过。其他早于 2014 年的日期即使已登记也不通过。 |
| `duckdb_sql.py` 的 `silver_stock_daily_select`、`assets/stock_daily.py` 的 `_silver_filter_counts`、`checks/stock_daily_checks.py` 的 `_expected_tradable_universe_metadata` | 从同一处取股票日线收录日期规则。生成 SQL 和行数统计对源行判断 `>= 2014-01-01` 或 `= 2009-02-23`。Raw、Silver 覆盖检查用同一规则判断目标日是否在范围。生命周期、币种、北交所起始日及代码集合规则照常应用。 | 目标日的真实成交行进入 Silver 和行数统计。空文件、其他早期日期、故意缺少 `000001.SZ` 的覆盖样本均不能被判齐备。2014 年之后的样本输出和检查结果与改动前一致。 |
| `sensors/suspend_d_sensor.py`、`sensors/stock_daily_sensor.py` 的 `_eligible_registered_trade_dates` | 这两处现直接用已登记日期选待补分区。新增历史日期后，这两处日常选择仍从原有日期下限开始。手工选择目标日走下表中的现有任务。 | 隔离测试加入 `2009-02-23` 的分区和当前待运行分区，确认相关四个 sensor 继续选当前待运行日期。人工任务可单独选目标日。 |
| 股票分钟 Raw/Silver 和下游的日期集合 | Raw 现有分区和产出记录按原路径复用。日线 Silver 通过后，单独在 `cn_a_stock_mins_silver_trade_days` 登记 `2009-02-23`。分钟行情 Silver 正常任务按指定分区运行，日常历史起始日期和递推指标的日期窗口沿用现行设定。 | 用真正的任务选择验证只选这一天。复核分钟前复权、财富成交额及其他读取这两个日期集合的 sensor，确认新增历史登记不会改变日常的日期顺序，也不会触发服务表发布。 |

单日日期值只定义一处，供明确需要它的日线收录和股票分区检查引用。股票盘中停牌事实的登记与日期放行独立。登记表可以存其他有证据的事实，正式补数日期仍由各资产原有日期规则和此次批准的范围决定。手工准备时用日历只核对目标日，保持其他日期集合及历史起点的语义。 [股票分区定义](../../orchestrator/src/orchestrator/defs/partitions.py) · [股票分区检查](../../orchestrator/src/orchestrator/defs/checks/stock_partition_checks.py) · [日线生成 SQL](../../orchestrator/src/orchestrator/defs/duckdb_sql.py#L306) · [分钟历史日期规则](../../orchestrator/src/orchestrator/defs/run_contracts/stk_mins.py#L23)

### 2.2 正式操作入口与启动条件

采用现有 Dagster 单分区任务。计划操作目录为 `/Users/congming/github/goldenshare/lake_console/orchestrator`，正式实例为 `DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home`，代码位置 `orchestrator`。正式执行审批前重新核对部署代码位置、挂载、空间及目标路径。获准后，在该实例的分区界面只添加表中所需的单个键，在 Launchpad 选同一个分区启动表中任务。命令行等价参数为 `dg launch --job <表中任务名> --partition 2009-02-23`，以确认连接到正式实例的项目入口为准。一次只提交当前步骤，不选日期范围。 [现有正式实例配置](dagster-confirmed-business-facts-low-level-design-v1.md#formal-recovery-runbook) · [Dagster 单分区运行](https://dagster.io/docs/guides/build/partitions-and-backfills/partitioning-assets)

| 步骤 | 正式入口 | 进入条件与读回结果 |
| --- | --- | --- |
| 1. 确认引用数据并准备分区 | 在 `cn_a_stock_trade_days` 加 `2009-02-23` | 读回该键和开市日。通过现有就绪检查核对股票基础信息、生命周期及身份映射。资产文件存在和包含当日适用记录都需核对。`000001.SZ` 的身份映射实查是 `000001.SZ → 000001.SZ`，自 1991 年 4 月 3 日有效。 |
| 2. 按第 3 节登记并补停复牌 Raw | `raw_suspend_d_update_job` | 登记结果能读回。Tushare `suspend_d` 按 `trade_date=20090223` 取得同日市场结果。确认源表字段、日期、停牌类型和目标股票的原始行，并检查完整性。 |
| 3. 生成停复牌 Silver | `silver_suspend_d_update_job` | 停复牌 Raw 和固定全日停牌资产检查通过。确认 Silver 为 `S + 13:00-15:00`，`000001.SZ` 不在全天停牌集合，正式文件和 Dagster 检查对应同一次产出。 |
| 4. 补股票日线 Raw | `raw_stock_daily_update_job` | 已验收相关停复牌和股票基础信息。使用完整替换的默认取数方式，Tushare `daily` 只传目标交易日和现有字段、分页参数。首次生成整个日分区使用按日取数路径。读回后运行 Raw 的合同、主键、日期和应交易覆盖检查。 |
| 5. 补股票日线 Silver | `silver_stock_daily_update_job` | 同日日线 Raw 检查通过。使用现有生命周期和有效基础信息，保留该股票当日有成交的日线。读回 `000001.SZ` 唯一一行，并确认该股票属于应交易集合。日线全市场覆盖检查通过才进入步骤 6。 |
| 6. 补五个频度的股票分钟行情 Silver | 在 `cn_a_stock_mins_silver_trade_days` 加 `2009-02-23`，运行 `stock_mins_silver_update_job` | 核对已验收的股票日线和停复牌 Silver、现有身份映射、五份分钟 Raw 的正式合同检查。同一任务按现有定义生成五个频度并检查。按照第 4 节读回频度和盘中成交。 |
| 7. 补同日派生资产并审查有历史依赖的下游 | 见第 5 节 | 前置文件和正式检查全部通过才进入对应分支。登记资产名、日期、文件、检查结果、仍缺的输入及是否属于本次单日范围。 |

已有分钟 Raw 的检查如果缺记录，优先使用现有针对 Raw 的正式检查重验文件，限定目标日与五资产。检查失败按具体文件处理。正式执行前核对可能选中目标日的 sensor 和已经提交的同日任务，按批准暂停有影响的 sensor。手工依次完成本表操作，验收后恢复记录下的原状态。 [停复牌任务](../../orchestrator/src/orchestrator/defs/jobs/suspend_update.py) · [股票日线任务](../../orchestrator/src/orchestrator/defs/jobs/stock_daily_update.py) · [股票分钟行情 Silver 任务](../../orchestrator/src/orchestrator/defs/jobs/stock_mins_silver_update.py) · [Dagster 资产检查](https://dagster.io/docs/guides/test/asset-checks)

## 3. 登记事实并生成股票停复牌 Silver

### 3.1 登记接口和存储

复用 `goldenshare_lake_meta.public.confirmed_business_facts`，现有表可存本案字段。登记、更正、撤销沿用 `LAKE_META_POSTGRES_WRITE_URL` 的本地维护角色，DG 任务使用 `LAKE_META_POSTGRES_URL` 和已有 `ConfirmedBusinessFactsResource`。登记使用串行化事务，读取使用只读连接，运行输出只记事实引用及必要业务字段。

| 字段 | 本案值及用途 |
| --- | --- |
| `subject_type`、`subject_key`、`fact_type` | `stock`、`000001.SZ`、`stock_intraday_suspension`。程序使用代码、类型和日期匹配。 |
| `time_precision`、`effective_from`、`effective_until` | `timestamp`、`2009-02-23T13:00:00+08:00`、`2009-02-23T15:00:00+08:00`。开始包含、结束不含。15:00 是当日停牌时段的计算边界。 |
| `evidence`、`reason` | 深交所停复牌记录、深发展公告 `2009-006` 及链接。注明源端有停牌记录但缺时段，官方材料确认下午停牌。 |
| `fact_id`、`revision`、`action`、`recorded_by`、`recorded_at` | 复用现有生成规则，初次为 `confirm`、第 `1` 版。更正与撤销新增版本。 |

修改 `confirmed_business_facts.py` 与 `confirmed_business_facts_cli.py`。维护命令 `register`、按代码查询的 `history` 增加可选 `--subject-type`，默认保留 `etf`。这次登记显式指定 `--subject-type stock --subject-key 000001.SZ --fact-type stock_intraday_suspension`。`--effective-from`、`--effective-until` 传表中的带时区时间，`--evidence` 和 `--reason` 沿用现有书写规则。`correct` 按事实编号取当前记录后，按原对象和类型验证新时间。`revoke` 保留原对象、类型和时间精度。股票输入按现有市场股票编码规则验证，时段按上海时间归属同一交易日，要求结束晚于开始。ETF 调用仍用现有日期格式和行为。

维护端复用当前版本选择、重复提交判断及重叠校验。相同内容重试读回原记录。事实更正和撤销后，查询先取每条事实的最新版本再按有效区间筛选。盘中时段进入 DuckDB 前转换成 `HH:MM-HH:MM`。 [通用维护与查询入口](../../orchestrator/src/orchestrator/defs/confirmed_business_facts.py) · [登记使用说明](dagster-confirmed-business-facts-usage-v1.md) · [深交所停复牌记录](https://www.szse.cn/market/periodical/documents/P020180328475177314723.html) · [深发展停牌公告](https://pdf.dfcfw.com/pdf/H2_AN201202280004409300_1.pdf)

### 3.2 在何处应用订正

在 `assets/suspend_d.py` 的 Silver 入口一次调用已有资源，参数为 `subject_type='stock'`、上述事实类型和上海时间对应的 `[2009-02-23, 2009-02-24)` 查询窗口。其他日期按各自分区日查询。把读到的有效行按 `ts_code`、`trade_date` 写到运行中的 DuckDB 临时关系，值来自参数绑定。只给停复牌 Silver 增加该读取。下游按原合同读停复牌 Silver。

`duckdb_sql.py` 在现有停牌时段订正处做关联。先沿用现有时段清洗，再核对可匹配的盘中事实，保留固定全日停牌合并的现有规则。对同一股票和日期，`S + NULL` 且有一条明确时段时补入该时段。来源已给出相同时段时，结果与来源一致。若登记事实和现有非空时段、固定全日停牌事实冲突，或出现多条无法与空时段源行对应的登记区间，报出代码、日期、两边时段和事实版本，暂停该日发布。若只有 `R` 或目标记录不在来源中，保留源行语义，报告未匹配的事实，本案须复核后才验收。查询成功且无适用事实时使用原规则，查询失败时不给该日生成新的停复牌 Silver。

最终文件继续使用 `ts_code`、`trade_date`、`suspend_timing`、`suspend_type` 四列。将事实编号、版本、应用数量和未匹配信息存运行记录，并把本次使用的事实引用纳入现有候选记录。与无本案事实的输出作差集，在该份正式证据下应仅有 `000001.SZ` 当天 `S` 的时段变化。复核 Raw、Silver 主键和类型检查，复用现有固定文件校验。 [停复牌 Silver 写入](../../orchestrator/src/orchestrator/defs/assets/suspend_d.py#L372) · [合并 SQL](../../orchestrator/src/orchestrator/defs/duckdb_sql.py#L480) · [停复牌检查](../../orchestrator/src/orchestrator/defs/checks/suspend_d_checks.py)

## 4. 日线与分钟行情的读回和验收

### 4.1 股票日线 Raw 和 Silver

1. 使用既有 Tushare 按交易日取数和分页路径，记录实际请求参数、字段、每页行数与总行数。使用接口可接受的分页上限，不能用单股请求结果替代全市场。停复牌和日线源文件都按现有列、类型和唯一性约定检查。比对源端股票范围与生命周期、当天已订正的停复牌集合，列出任何覆盖差异。
2. 对 `000001.SZ` 按现行单位核对源日线。只读样本开盘 13.48 元、最高 14.99 元、最低 13.41 元、收盘 14.99 元、Tushare 成交量 693,365.62 手，成交额 1,001,283.9545 千元。写入验收值以本次获准取得并留证的源结果为准。日线和分钟成交量按各自源合同核对，现有两份源样本换算后相差 38 股，不能要求严格相等来判断这次停牌是否订正成功。
3. Silver 检查使用目标日的应交易代码和实际代码做双向差集。盘中停牌仍在应交易集合。必须同时有针对 `000001.SZ` 的单行读回和全当日文件的范围、主键、生命周期、价格和覆盖检查结果。旧日期筛选若漏改，目标日输出为空或检查的应交易集合为空均判未通过。 [日线资产与字段](../../orchestrator/src/orchestrator/defs/assets/stock_daily.py) · [日线覆盖检查](../../orchestrator/src/orchestrator/defs/checks/stock_daily_checks.py#L884)

### 4.2 股票分钟行情 Silver

复用 `assets/stk_mins.py` 中已有的五频度生成流程。按现有方式匹配身份、过滤全天停牌、按原规则用 1 分钟数据补齐符合条件的较粗周期。股票日线 Silver、停复牌 Silver、身份映射及相关 Raw 文件的输入版本写入运行记录。以正式文件实际内容核对，不能用五个资产的任务成功状态代替五份文件的验收。

| 频度 | 已有 Raw 实查总行数 / 股票数 | `000001.SZ` 上午原始正成交量记录 |
| --- | ---: | ---: |
| 1 分钟 | 345,353 / 1,433 | 121 |
| 5 分钟 | 69,874 / 1,426 | 25 |
| 15 分钟 | 24,259 / 1,427 | 9 |
| 30 分钟 | 12,834 / 1,426 | 5 |
| 60 分钟 | 7,135 / 1,427 | 3 |

上表是只读核对基线。逐频比对上海时间当日上午的时间点及成交量、成交额，总体结果应保留目标股票的有效成交。若有源时间标签或聚合差异，按现有标准化规则做对应核算。股票下午原始记录的成交量与成交额为零，Silver 的表示按现有分钟行情合同验收。五频度分别核对文件日期、字段、唯一键、时点、数值、交易所、日线代码覆盖、全天停牌过滤和名称时间线。 [分钟行情写入](../../orchestrator/src/orchestrator/defs/assets/stk_mins.py#L2196) · [分钟行情正式检查](../../orchestrator/src/orchestrator/defs/checks/stk_mins_checks.py#L2741)

## 5. 下游怎样推进和验收

| 下游 | 进入条件和现有任务 | 验收或当前限制 |
| --- | --- | --- |
| 市场宽度、股票收益分布 | 日线 Silver 已验收，对应 `daily_market_breadth_job`、`stock_return_distribution_daily_job`，各运行 `2009-02-23`。 | 对当日日线独立统计上涨、下跌、平盘及各涨跌区间，与 Gold 文件逐项对照。源代码覆盖和分区检查通过后完成本案对应验收。 |
| 财富端市场成交额 Gold | 日线 Silver 和五频度分钟行情 Silver 均验收，运行 `gold_wealth_market_turnover_update_job`。 | 用当日正式五频度及日线重算核对全市场各时点序列、汇总和单位。2009 年没有北交所，北交所输入和差额应符合既有规则。只验收 DG Gold 文件。 |
| 股票日线前复权 Gold | 日线 Silver、同日复权因子、算法实际需要的前一可用日线和对应复权因子就绪后，运行 `gold_stock_daily_qfq_update_job`。 | 现行读取器会向前查最多 20 个交易日。目标日前 20 个交易日为 `2009-01-19` 至 `2009-02-20`。实查当中日线 Raw 和 Silver 各 **0/20**，股票复权因子 Silver **20/20**。现有 writer 会跳过未落盘的前日日线，并可能将前收盘、涨跌额和涨跌幅写为 0。本案不能用这种产出通过验收。先按应有交易记录列出实际缺的前置日期，另行确认补齐方式与范围。输入齐备后，验收当日与前一可用交易记录的复权价格、前收盘、涨跌额、涨跌幅和股票覆盖。已有 20 份复权因子文件要按实际参与计算的股票继续检查有效覆盖。 |
| 股票分钟前复权 Gold | 先验收五频度 Silver 和同日股票复权因子，核对当前七频度任务 `stock_mins_qfq_daily_update_job` 所需的复权口径、派生频度输入和按股票、年份的目标文件。 | 对原生和派生频度核对代码、时点、成交量和复权价格，检查年度文件与 Dagster 记录的日期覆盖。既有日期或年度文件若冲突，按实际影响列清读写范围后再处理。 |
| 股票日线前复权九转、股票日线趋势通道 | 先补股票日线前复权 Gold。任务为 `gold_stock_daily_qfq_nineturn_update_job`、`gold_stock_daily_trend_channel_update_job`。 | 九转按现有前置行情窗口及上一个结果或历史回读规则核对。趋势通道核对前一交易日状态及当天行情。实际历史缺失时记录最早缺口和需要的前置资产，不把本日当作首次交易或初始状态验收。 |
| 股票分钟 MACD/KDJ、股票分钟前复权九转 | 先核对目标日分钟前复权 Gold。MACD/KDJ 入口 `gold_stk_mins_qfq_macd_kdj_daily_update_job` 依赖当前分钟日历窗口及前一交易日状态。九转入口 `gold_stk_mins_qfq_nineturn_update_job` 依赖前置分钟行情及九转上下文。 | 当前 MACD/KDJ 的日常日期下限是 2014 年，直接选 2009 年目标不能作为有效起算。先确定适用的历史窗口和已有状态，再用现有算法及适用入口生成。九转按 30、60、90、120 分钟检查规定的前置行情、完整性与计数。 |
| 周月线、股票技术因子、资金流向及服务表 | 复核各自原生来源、适用正式历史范围和受影响检查。周线检查 `2009-02-27` 所在周期，月线检查 `2009-02`。 | 若应覆盖且存在真实缺口，列出具体资产、时间范围、来源和缺失检查。服务表发布另行批准，本轮留验收条件。 |

本日股票日线和分钟行情是可单独验收的产出。下游每项写明使用的输入文件或状态、正式检查结果、抽查结果，以及当前不能完成的具体原因。股票日线前复权 Gold 仍是本案下游交付目标。补齐 2 月 23 日的两路行情 Silver 后，可以先验收它们及同日派生资产，待日线前复权的真实前置数据齐备再验收该分支。 [日线前复权历史查询与输出](../../orchestrator/src/orchestrator/defs/stock_daily_qfq.py#L151) · [日线九转历史输入](../../orchestrator/src/orchestrator/defs/qfq_nineturn.py#L295) · [分钟 MACD/KDJ 状态读取](../../orchestrator/src/orchestrator/defs/assets/stk_mins_qfq_macd_kdj.py) · [财富端市场成交额依赖](../../orchestrator/src/orchestrator/defs/assets/wealth_market_turnover.py)

## 6. 写入范围、失败与恢复

- 核心目标文件为 9 份，由 2 份停复牌 Raw/Silver、2 份股票日线 Raw/Silver 和 5 份分钟行情 Silver 组成。读取已有五份分钟 Raw 共 **8,108,166 字节**。按现有 writer 依赖，每次构建 1 分钟一次读取本频度，四个较粗周期各涉及本频度和同一份 1 分钟 Raw。将文件大小逐次相加为 `8,108,166 + 4 × 5,449,544 = 29,906,342 字节`，这是生成路径引用到的 Raw 文件大小之和。正式检查、确认输入一致性和读回的访问量另按涉及文件计算。缓存、列裁剪、写入大小、行情源行数和实际耗时仍需在隔离验证与正式预算中分别核对。
- 每个正式文件按自身任务形成候选并验证，候选位于 `/Volumes/datasource/data_lake_staging` 的当前运行范围，正式目标由 `paths.py` 确定。复用停复牌 Silver 已有候选和记录、分钟行情 Silver 已有文件提升流程。停复牌 Raw、日线 Raw/Silver 等现行写入如果在正式文件旁生成 `.tmp`，给本次历史单日路径传入 staging 下的候选路径。复用原取数、标准化和检查规则，对候选验证源数据、行数、日期、唯一键和范围后提升。同日已有正式文件也先核对来源与内容。核实同一文件系统，用现有原子替换方式逐个文件发布，保留对应输入及输出引用。此要求也适用于批准纳入的派生文件。
- 中断后从已完成文件核对。已落盘且读回、检查均通过的文件直接复用。只缺正式检查或 run 记录时先按现有检查入口对账，不能用补写记录掩盖文件未经验证的状态。未成功步骤使用当前已核验输入重新发起，按原任务和日期定位废弃候选，确认写入已结束后定点清理。记录中如果停牌事实版本或其他输入已变化，重新生成和验收受影响文件。发现未知来源正式目标时停止覆盖并核对。
- 正式执行前列清源请求分页方式、按步骤目标路径、预计磁盘开销及阶段耗时。候选、当前文件和中断重做期间的开销均计入。已确认的 9 个正式文件只包含目标日的核心行情，任何前置交易日和按年文件读取或覆盖另报明确范围。以实际读取对象及现有 writer 规则定预算，现阶段没有实测时长或正式写入字节数。 [性能与文件写入治理](dagster-data-pipeline-performance-governance.md)

## 7. 开发验证和正式验收证据

| 必测场景 | 如何验证 |
| --- | --- |
| 只开通目标日 | 隔离 Dagster 实例注册目标日及相邻早期日。目标日通过股票日期、生成和覆盖三处判断，相邻日仍不获放行。普通 2014 年之后交易日的 Raw/Silver 选择及输出保持既有结果。加入历史日后模拟自动选日，验证不会自动跑历史任务或服务表。 |
| 事实登记与撤销 | 以证据确定 `13:00–15:00`，用小样本验证时间比较、读回真实时区、重复提交、更正、撤销和读取失败。验证 ETF 现有命令与用例仍通过。 |
| Raw/Silver 订正 | 同一份候选数据分别有无该事实。只改变目标停牌时段。对来源自行填对、不同非空值、全日停牌、只有复牌、相邻日期和其他股票分别检查结果。核对候选和正式检查的日期及 schema。 |
| 日线检查真实反例 | 用现有日线合同构造上午成交的目标股和当天其他股票。空时段会从应交易集合扣除该股，正确时段会保留该股。故意漏掉该股的日线应由覆盖检查报缺。写入与统计应给出一致计数。 |
| 分钟过滤真实反例 | 用目标日真实合同字段和对照股票，比较 `S + NULL` 和 `S + 13:00-15:00` 两种停牌 Silver。前者触发现有全天排除，后者保留上午成交。全日停牌对照仍被排除。五频度使用正常入口验证。 |
| 下游及中断 | 历史缺失时能明确停止日线前复权及递推分支的正式验收。历史齐备的独立样本通过公式和状态连续性核对。测试候选未发布、已发布未读回、同日重试和坏候选清理。 |

测试以现有 `test_confirmed_business_facts.py`、股票停复牌、股票日线和股票分钟行情合同测试为基础，使用隔离实例和临时路径。正式验收每步记录目标分区、源文件、产出路径和实际检查结果。CodeGraph 和当前代码复核覆盖了日期选择、生成 SQL、覆盖检查、股票分钟行情及日线下游的运行依赖。开发阶段依本表验收后，再申请正式执行。
