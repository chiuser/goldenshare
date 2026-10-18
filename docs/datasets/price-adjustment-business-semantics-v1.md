# 价格复权、基准与下游影响说明 v1

业务代码首次核验日期：2026-10-16；专项完成状态和引用更新：2026-10-18。状态：代码知识说明；记录已核验差异和待确认事项，不调整公式、修复范围或生产入口。本次只同步25股专项完成及工具清退后的引用，其他业务结论仍沿首次核验，不升级为新的源站、正式数据或Prod验收。

范围：DG 股票日线/分钟 QFQ、复权因子、日常指标代码及25股专项完成记录，Prod 股票详情查询中的日线和周/月价格路径。首次核验基线为 `dev-interface` 当时工作区（起点 HEAD `8ce4f252bc704c2079e263818e3ebe1ac9d7c696`，含未提交改动）；专项工具清退提交为 `bcbe45590`。本次未实测 Tushare、查询正式库/Lake、运行测试或启动任何修复；已有历史记录不升级为本次重新验收。

QFQ 指前复权，HFQ 指后复权；state 指递推计算在下一批继续运行所需的状态，不能与最终展示的指标结果混为一份产物。

## 1. 先说清价格与时间坐标

| 概念 | 本轮应如何理解 | 不能混同 |
| --- | --- | --- |
| 原始/源行情 | 按该源字段合同提供的价格；同一响应可以同时含多种价格 | Raw 层不等于所有列都是不复权价 |
| 因子交易日 `t` | 该历史行情对应的因子日期 | 不是文件生成日或当前观察日 |
| 复权基准 `A` | 当前计算选用的锚点/分母因子及其日期 | 不一定是行情日，也不一定等于请求区间末日 |
| 源周/月 `end_date` | 本地源文档将其解释为计算截至日期，并保存日期样本 | 不能当作每根历史 K 线内部最后交易日，也不能直接视作 DG 的 `as_of_trade_date` |
| 观察/写入时刻 | 本次取得源值或生成结果的时刻 | 业务日期相同不保证不同观察时刻的内容相同 |
| 展示精度 | 页面或对账的舍入尺度 | 两位显示相同不能证明因子或 DOUBLE 价格相同 |

外部字段资料引用[doc_id=28 复权因子](../sources/tushare/股票数据/行情数据/0028_复权因子.md)、[doc_id=365 周/月复权行情](../sources/tushare/股票数据/行情数据/0365_股票周_月线行情(复权--每日更新).md)。其中源参数与样本是本地资料或其日期记录；本轮不据此宣称当前源过滤、分页、基准或全量能力已实测。

## 2. 当前计算与读取路径存在差异

### 2.1 DG 日线 QFQ

`_stock_daily_qfq_base_ctes_sql` 与 `build_stock_daily_qfq_select_sql` 的核心关系是：

```text
QFQ_OHLC(t, A) = Silver_OHLC(t) × factor(t) / factor(A)
QFQ_pre_close(t, A) = previous_actual_close × previous_actual_factor / factor(A)
```

这里 previous 在调用方提供的 previous lookup 输入中，按该股票日期倒序选上一实际 Silver 行，不机械等于日历前一交易日；是否提供足够的查找范围还要核对调用方。无上一行时，当前输出 `pre_close/change_amount/pct_chg` 使用相应首行处理；有上一行但缺因子不能当首行跳过。`change_amount/pct_chg` 按同一基准的前收盘重算；`vol/amount` 不乘复权比例。

现有字面样本：上一行收盘 9、因子 2，本行收盘 10.5、基准因子 4，输出前收盘 4.5、涨跌额 6。该例来自合同测试，说明“只修 OHLC”不足以保持相关字段一致，不证明正式数据已经通过。

### 2.2 DG 分钟 QFQ

`build_canonical_gold_stk_mins_qfq_select_sql` 从已选 Silver 源频度与因子生成 `price_multiplier`，再调用正式标准 K 线计算。默认按提供的 as-of 因子路径逐股选最新基准，也支持显式按交易日匹配；不能把“最新”解释成自动扫描全库最新。

目标频度的源频度、竞价锚点和聚合窗口由当前 canonical 合同决定。不能沿用旧文档中已被替代的“从 Gold 30m/60m 派生 90m/120m”等算法，也不能只因频度名称相同就假定源窗口一致。详细依据见[标准 K 线 LLD](../../lake_console/docs/design/dagster-cn-a-minute-gold-canonical-bars-rebuild-low-level-design.md)。

日常生产与因子 repair 的基准选择不同，必须核对实际输入范围和基准。历史文件经过 repair 后，用目标日因子当分母重新比较，可能把不同基准误报成价格错误。

### 2.3 Prod 股票详情日线

`QuoteQueryService._build_stock_points_from_rows` 从 Prod 日线与因子表构造结果。当前前复权锚点取该股票因子表最新行，后复权取最早行；查询没有按本次显示区间截断锚点。因此只请求历史小区间，也不能假定复权基准固定在该区间末日。

该路径按同日 `factor/anchor` 缩放 OHLC、源 `pre_close/change_amount`，保留源 `pct_chg/vol/amount`；与 DG 日线“取上一实际源行并重算相关字段”是不同实现。缺因子或锚点时显式报错。本文记录差异，不自行判定两条链已经语义等价，也不改变 API 行为。

### 2.4 Prod 周/月与 DG 周/月 Raw

Prod `_load_stock_period_points` 直接选择 `StkPeriodBarAdj` 的 QFQ/HFQ OHLC，不用 DG 因子重新算源复权价；前收盘优先用本次返回序列的上一根复权收盘，首根回退该行源 `pre_close`，源涨跌幅仍保留。首根可能受取数窗口影响，不能按 DG 日线口径直接解释。

DG 周/月 Raw 当前合同同样保留源 QFQ/HFQ 字段。源价格修订应沿该来源路径处理，不能以本地日线因子公式覆盖源值后声称仍是源镜像。工作区直接源接线与正式生效状态的分界见[Raw/Silver 说明](raw-silver-business-semantics-v1.md)。

## 3. 复权因子本身的对象范围

DG 当前 `silver_adj_factor` 只保留生命周期中的当前上市 L、CNY 股票，并限制合法日期；已退市股票退市前历史因子也排除。Raw 保留源记录，生命周期表不随此政策删除退市身份。原专项最新决定见[因子设计 §14](../../lake_console/docs/design/dagster-adj-factor-asset-design.md)。

这意味着：历史行情存在、历史因子 Raw 存在、因子 Silver 覆盖、QFQ 可重建分别是不同判断。因子 check 在其 expected universe 内通过，不证明所有历史行情代码都有因子；也不能因为历史 QFQ 需求就给 writer 添加 Raw 兜底。

## 4. 修改因子或基准时的影响清单

下表是基于已读代码的检查入口，不是自动重算清单。执行前仍须按本次对象、数值差异、锚点、现存覆盖和末端冻结范围作决定。

| 对象 | 应评估的影响 | 范围判断与边界 |
| --- | --- | --- |
| 源因子与 Silver | 源值修订、数值精度、身份和准入范围 | 格式/小数位变化不自动等于数值修复；源修订日期集合不是下游全部影响日期集合 |
| 日线/分钟 QFQ | 分子因子、基准分母及聚合输入变化 | 基准变化可能影响更早历史；按逐股基准、源日期和目标实际覆盖确定，不能只重算因子变化日 |
| 日线前收盘、涨跌额、涨跌幅 | 与上一实际源行和同一价格基准的关系 | DG 与 Prod 当前路径不同，需分别核验；不能只替换四个价格字段 |
| MACD/KDJ 结果与 state | 输入价、窗口、递推种子与后续状态 | 日常指标代码及保留的公式测试继续核对上一状态和上下文；不能在截断修复窗口重新初始化，或只更改结果不更改受影响 state |
| 九转、趋势结果与 state | 连续计数、上下文、初始化、停牌 carry 与输出末端 | 已完成专项的逐项范围见原方案与LLD；不是所有指标统一一个 lookback，仍须保持未受影响行和原不存在的覆盖边界；已退役的专项规划函数不再作为现行入口 |
| 周/月源复权行情 | 源本身的修订、计算截至日期、请求对象和交付版本 | 重新从对应源获取与内部 QFQ 重算分开；不能拿任一条链的完成证明另一条链已更新 |
| Prod 查询、预计算指标、发布副本 | 消费的是动态价、源复权价还是预计算因子，参数和刷新时机是否一致 | 本轮核对查询与指标选择入口；未覆盖所有发布、缓存、API 和前端，不能宣告影响面清零 |
| 研究/回测 | 价格版本、锚点、对象池和可知时间是否一致 | 这是后续需求评估项，本轮未审计所有研究/QTF 消费者，不声明已具备历史时点重现能力 |

已完成专项中分钟 replay 的 8 根上下文、九转的 4 根上下文等是该次修复的历史合同，不是新数据集默认参数。后续任务须依据日常计算规则、种子和其已确认方案确定范围，不调用已退役专项工具。

## 5. 历史教训与专项完成状态

1. **结果反推依据只能证明内部自洽。** 已撤销的[as-of basis 方案](../../lake_console/docs/design/dagster-stk-mins-qfq-as-of-basis-low-level-design.md)试图从既有 QFQ 反推分母并在 production check/readiness 重算；既不能独立证明历史源依据，也带来失控扫描成本。该记录明确禁止启用，不能抽取其中代码路径当范例。
2. **公式验证与本次生产事实分工。** 现行[计算测试与 Check 治理](../../lake_console/docs/design/dagster-stk-mins-qfq-validation-governance-low-level-design.md)由独立字面金样本保护计算，生产检查验证真实输入、合同、文件和修复状态。不能为变绿改写依据，也不能因此弱化覆盖、身份和状态检查。
3. **显示相同不等于业务无影响。** [25 股专项](../../lake_console/docs/design/dagster-stock-adj-factor-history-repair-plan-v1.md)保留了“无两位价差仍需评估真实因子变化”和“混基准历史需扩展核验”的案例；批准股票、键与范围外不变分别受控。案例数量不应转成所有新修复的默认范围。
4. **25股专项及工具清退已完成。** 原方案和LLD已记录R3隔离验收、R4正式文件修复、R5的31条DG观察记录及第7步清退结果；9个专用模块和10份专用测试已删除，必要公式断言保留在日常测试中，原计划/hash及执行证据保留。DG观察记录供人查看本次修复，不冒充全市场普通检查或serving发布；本文不重启修复，也不把旧暂停记录写成当前待办。

## 6. 已核验的实现、测试与影响面

| 结论 | 实现与测试入口 | 本轮核验 |
| --- | --- | --- |
| DG 日线公式与前收盘 | [stock_daily_qfq.py](../../lake_console/orchestrator/src/orchestrator/defs/stock_daily_qfq.py)：`build_stock_daily_qfq_select_sql`、`_stock_daily_qfq_base_ctes_sql`；[test_stock_daily_qfq_contracts.py](../../lake_console/orchestrator/tests/test_stock_daily_qfq_contracts.py)：`test_writer_uses_qfq_formula_and_recomputes_previous_fields` | 已读公式、字面断言与缺因子拒绝分支；未运行 |
| 分钟基准与标准窗口 | [stk_mins_qfq.py](../../lake_console/orchestrator/src/orchestrator/defs/stk_mins_qfq.py)：`build_as_of_adj_factor_by_code_sql`、`build_canonical_gold_stk_mins_qfq_select_sql` | 已读输入、比例和 canonical 调用；未做正式价格对账 |
| Prod 动态日线与源周/月 | [quote_query_service.py](../../src/biz/queries/quote_query_service.py)：`_build_stock_points_from_rows`、`_load_stock_adjustment_anchor`、`_load_stock_period_points`；[test_quote_api.py](../../tests/web/test_quote_api.py)：`test_quote_kline_rejects_forward_when_adj_factor_incomplete`、`test_quote_kline_supports_stock_week_backward_and_month_none` | 已读查询实现及测试覆盖入口；未执行 API 或浏览器验收 |
| 因子范围 | [duckdb_sql.py](../../lake_console/orchestrator/src/orchestrator/defs/duckdb_sql.py)：`adj_factor_current_listed_stock_select`、`silver_adj_factor_select`；[test_adj_factor_current_listed_policy.py](../../lake_console/orchestrator/tests/test_adj_factor_current_listed_policy.py) | 已读当前上市规则与历史反例；未重验正式迁移结果 |
| 指标计算、state及专项完成 | [日常MACD/KDJ代码](../../lake_console/orchestrator/src/orchestrator/defs/stk_mins_qfq_macd_kdj.py)：`prepare_stk_mins_qfq_macd_kdj_replacement_tables`、`write_gold_stk_mins_qfq_macd_kdj_rows`；[保留的公式测试](../../lake_console/orchestrator/tests/test_stk_mins_qfq_macd_kdj_formula_golden_contracts.py)：`test_seven_frequencies_keep_literal_values_and_state_across_years`、`test_scoped_repair_preserves_unselected_state_rows`；[专项完成及清退记录](../../lake_console/docs/design/dagster-stock-adj-factor-history-repair-low-level-design-v1.md#237-第7步实施与验收结果2026-10-18) | 本次核对日常函数及保留的字面断言；修复、登记和清退结果引用LLD §22.9、§24.10、§23.7，不重复执行修复或测试 |

2026-10-16首次核验时，CodeGraph 的 `codegraph_explore` 与 `codegraph_impact(build_stock_daily_qfq_select_sql)`覆盖当时的日常 writer、repair writer、历史 bootstrap、候选生成及相关测试；`codegraph_impact(_build_stock_points_from_rows)`覆盖当时的Prod日线查询与预热/指标上下文入口。该记录保留为首次核验依据，不表示候选/专项模块仍在，也不作为全部产品消费者清单。

## 7. 待确认项与结论失效条件

| 待确认项 | 当前已知事实 | 下一次需要解决什么 |
| --- | --- | --- |
| DG 与 Prod 的前收盘/涨跌额/涨跌幅是否要对齐 | 当前实现不同，不能仅按“都叫前复权”要求逐字段相等 | 明确产品想表达的收益口径，再以相同对象/日期/基准的有界样本核验；改变公式或 API 须另行批准 |
| 退市股票历史复权覆盖 | 行情与因子 Silver 对象范围不同 | 与[生命周期待确认项](security-lifecycle-business-semantics-v1.md)共同确定需求，不悄悄扩大因子范围 |
| 历史查询能否重现当时所见价格 | Prod 锚点随因子表最早/最新值选择，DG 历史可经 repair 改写；没有本轮历史版本证据 | 区分“按当前基准回看历史”与“重现当时已知价格”，后者需额外数据依据与产品决定 |
| 复权修订后的完整发布影响面 | 已知价格和 state 计算入口；全部 serving、缓存、前端与研究消费者未清零 | 在具体变更前补定向消费者审计，列明刷新/重放和不受影响的理由 |

因子来源/值、基准选择、生命周期状态、聚合窗口、种子、精度、查询路径或输出合同任一变化时，相关结论需要重核；只读知识检索不自动触发全历史审计。正式修复应分别证明计算正确、本次输入真实、改写范围正确和下游状态一致，不以一份旧报告互相替代。
