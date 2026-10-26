# 股票技术因子 DG 数据集接入技术方案 v1

状态：第一批“契约与基础结构”已开发并通过本批验收，具备申请第二批的条件；第二批日下载、校验与发布已开发；提交后发现的候选路径遗漏已按LLD§15.9修复，针对性测试及再次独立审计通过，具备申请第三批的条件（见§13.4）。其余批次及整个数据集尚未完成。未装配本数据集正式DG资产/job/sensor，未执行bootstrap或启用自动更新。第一批证据见[验收记录](../../reports/stock_factor_pro_batch1_20261026/README.md)；tushare数据下载组件原本期开发及隔离验收已完成。

编写日期：2026-10-18；更新日期：2026-10-26。配套文档：[股票技术因子接入LLD](dagster-stock-technical-factor-onboarding-low-level-design-v1.md)。

目标数据集：Tushare `stk_factor_pro`，股票技术面因子专业版。业务使用的契约名确定为 `stk_factor_pro`，不加来源前缀或版本后缀；版本作为契约独立字段维护。

## 1. 目标与已确认要求

将 Prod 已有的股票技术因子历史数据 bootstrap 到正式 DG Lake；初始化完成并验收后，由 DG 自动从 Tushare 下载后续交易日数据、处理并发布 Raw/Silver，不继续每日从 Prod 导出本数据集。DG 同时监控复权因子变化，从 Tushare 重新获取受影响股票的历史技术因子。直接使用已完成的下载器及语义适用的既有读写能力，不把抽取其他公共模块或迁移旧数据集作为前置条件。这里描述的是接入后的运行方式，当前尚未开发或启用该自动更新。

实施顺序：依据本方案和配套LLD完成代码影响面审计 → 调整契约名校验并登记完整契约与固定请求方式 → 实现并隔离验收DG接入 → 获准正式初始化并完成数据完整性审计 → 获准补记且补完全部历史事件 → 另行批准自动更新。初始化导入可以先保留合法已有行；历史事件和自动启用不得跳过完整性条件。

已确认要求：

1. 历史 bootstrap 来源是 Prod；范围已确定为正式初始化开始时确认的 `raw_tushare.stk_factor_pro` 全部现有业务数据，包含全部日期和全部股票（含退市股票），保留261个业务字段；不能自行缩短日期或筛选股票。日常来源是 Tushare，不能把初始化改成从 Tushare 重拉全部历史。
2. 复权因子监控及受影响股票的历史更新是本次接入的组成部分，不能只有当天追加。
3. Tushare 请求使用已完成的下载器；复用 DG 现有 DuckDB、日历、运行合同以及可直接适用的写入与恢复能力。旧数据集迁移、其他公共模块抽取均不在本次范围。
4. 按 DG 接入模板设计 Raw、Silver、Catalog、checks、job、sensor、初始化、恢复、性能与人的排障路径。
5. 正式 Lake 只使用 `/Volumes/datasource/data_lake`；候选文件只使用 `/Volumes/datasource/data_lake_staging`。不使用旧 Lake、旧 Console、Kopia 或已经清退的一次性修复入口。
6. tushare数据下载组件每下载完整一个unit，就向业务交付一次源数据；分页不逐页回传，也不等整批结束才返回。业务按本工程规则决定正式存到哪里、怎么写入，复用现有写入与发布能力。下载完成、正式写入和数据集完成分别确认；业务校验或写入失败不进入源请求自动重试。
7. 历史下载默认每股从可信最早已有日期至目标T，按该股完整范围形成unit，不为配合20日本地合并批次而切成20日网络请求。请求量/分页和实际容量按完整契约处理；范围未获准或容量不够时说明原因，不截短历史。处理旧日期只发布d<T。
8. bootstrap前不再独立审计Prod全历史股票覆盖缺口。利用本次必需的导出及本地已发布Raw，在每个完整交易日导入后统计应有股票与实际股票的集合差异；源到DG的传输完整性核对继续保留。Prod原有缺口只记录，不阻止合法已有数据导入，不在bootstrap中自动补采，具体步骤见§7.3及LLD§10.5。
9. bootstrap物理导入完成后，管理员通过同一个日更job发起首次人工补数，以原bootstrap批准及当前缺口日期为依据，不要求已有日更run；完整执行日更新和必要复权历史。入口、授权、失败重新下载及统计更新见§7.4和LLD§2.4、§10.7。该设计不新增job/sensor，不放开任意日期、股票或字段输入。

保留 Raw/Silver 两个资产，Silver按§4.2定义完整业务字段及日期归一化规则。日常只检查今天及上一个交易日。上一个交易日未补齐时，先安排一次补采；同一执行日期内，进入该次下载流程后就不再自动补第二次。补后仍缺、日下载/日发布失败且无法确认已齐、或覆盖未知时，不推进今天，交管理员判断与修复。上个交易日本来已齐，或这一次已补齐后，才允许安排今天；只有历史阶段失败而日覆盖已确认齐全，不当成日数据缺口。完整的前置检查、排队及重启处理见 §8.3 和 LLD §3。

只在执行日为开市日时自动运行：北京时间 19:00 开始，之后 19:30～23:30 每半小时安排今天的新一轮；午夜不再新开任务，已实际运行任务可正常结束，排队任务实际开跑时须再查截止时间。已有排队或运行任务就跳过该次，不累积待跑任务。19:00～23:30 共 10 个计划时点，不是要求无论是否补齐都运行 10 次，也不是允许把前日的一次机会变成每半小时一次。

每轮取得并按既定规则处理好的数据即可发布给业务使用，不等全市场股票全部补齐，不设最低数量或覆盖比例。按当天非停牌上市股票的代码集合判断缺失，用于继续补采、历史回刷前置和说明覆盖情况；不拿这份集合删掉来源其他合法行。要分开记录“本轮已发布”“当天股票已补齐”“复权历史已更新”。完整下载 unit 指已取完本次接口查询的全部页，不表示全市场应有股票都已在源端发布。

下载阶段不建设逐页、逐股票断点续传。**任务在任何阶段失败、异常退出或取消后，获准重执行一律重新下载，不复用该失败任务的下载数据或尚未发布的合并候选。**当日完整UnitResult只留在当前运行内存，下载会话正常关闭且最终summary核对通过后，直接构造Raw发布候选；不保存`source/day`下载副本、day manifest或day source-complete，不保留可用于后续任务的当日下载缓存。Raw/Silver发布前必要的原子提升候选仍须生成、校验，失败后不能沿用。日更重执行重新取得原目标T的完整日源；历史失败的全部原股票及原窗口重新取得历史源，不逐股、逐页或按已完成20日接续。失败前已经发布的正式文件保留，作为新请求合并的基础，不删除、不回滚；完整变化名单、批准范围及失败证据保留。其他此前整批成功且仍有效的历史不并入本次失败范围重刷。同一个仍正常运行的任务取全源后继续发布，不是失败重试。下载器同页有限重试及bootstrap原恢复规则不变。

一个日更 job 承载每轮更新和必要复权历史处理，自动sensor和获准人工执行共用；另提供管理员手动历史repair job。Raw、Silver 各一个综合 blocking check。股票复权因子数据集的目标日及前一交易日Raw已就绪，才允许提交自动技术因子 job；job 开始再次核实，并在下载技术因子前根据当前T/P生成、保存目标日的完整变化名单，保留同T以前尚未完成的历史范围。日更job先发布有效日Raw/Silver并通过必要检查，再确认原目标T已发布Raw按应有代码集合齐备，便在同一个job内立即执行所需历史，不等待另一个sensor或job。正常日更不支持只选Raw后启动历史；历史按每个日期先Raw、再从其生成Silver，两层均更新，不承诺两份文件同时生效。手动日更可以经管理员明确批准跨原午夜处理旧T；仍重下T日源、不恢复自动机会。手动repair不执行T日阶段，按§8.5先核原T Raw齐备，再确认原T正式Silver存在、已有检查通过且对应当前Raw，才核原历史前置；Silver不满足时提示管理员处理，不由repair补当天Raw或Silver。Raw不齐或覆盖未知时自动历史等待，repair直接报“原日期数据缺失”。确认全天停牌仍从应有集合扣除，不要求补造停牌日行；技术因子同名adj_factor值不一致仅作诊断。历史源漏回原应刷新键时，保留已发布数据、记录完整未完成范围并使run失败；今天的自动流程可在下一既定时点重取该完整范围。手动repair失败后由管理员查看原因、处理后再次点击执行，sensor不会代为提交repair，Dagster也不自动重试该op。日数据可以部分发布，历史必须满足覆盖前置；job失败不回滚已有文件。

分区由独立 sensor 根据日历注册今天（若开市）及上一个交易日；bootstrap先注册源表实际首尾之间的全部开市日。注册不表示来源、上游因子或业务数据已就绪，不等待 Tushare 发布，也不删除更早的历史键。复权因子前置与技术因子Raw覆盖是两种判断；日数据可部分发布，历史必须等Raw覆盖齐备。

本次接入只在 DG 内维护 `stk_factor_pro` 的一份完整源契约及其消费者。Prod 定义只作参考、Prod Raw 只作获准 bootstrap 来源，不修改 Prod 契约、DatasetDefinition、执行器或消费者；财势乾坤接入、三工程契约统一、契约平台和跨工程 import 均不在本次范围。不新增本地 MACD/KDJ 计算，不修改 Wealth、ClickHouse、Redis 或其他数据集的调用方式。

## 2. 依据与当前实现

### 2.1 设计依据

- [根规则](/Users/congming/github/goldenshare/AGENTS.md)、[Lake 规则](/Users/congming/github/goldenshare/lake_console/AGENTS.md)、[orchestrator 规则](/Users/congming/github/goldenshare/lake_console/orchestrator/AGENTS.md)。
- [架构边界](/Users/congming/github/goldenshare/docs/architecture/subsystem-boundary-plan.md)、[DG 编码规范](/Users/congming/github/goldenshare/lake_console/orchestrator/CODING_STANDARDS.md)。
- [DG 数据集接入综合模板](/Users/congming/github/goldenshare/lake_console/docs/templates/dagster-dataset-onboarding-template.html)，包括 4A、7A、10A 的合同、实测与可读性要求。
- [性能治理规范](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-data-pipeline-performance-governance.md)。
- Tushare `doc_id=328`：[本地接口文档](</Users/congming/github/goldenshare/docs/sources/tushare/股票数据/特色数据/0328_股票技术面因子(专业版).md>)。
- [下载器技术方案](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-tushare-request-common-module-comparison-v1.html)、[组件 LLD](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-tushare-download-component-low-level-design-v1.html)、[业务使用文档](/Users/congming/github/goldenshare/lake_console/docs/architecture/tushare-download-component-usage-v1.html)。
- [Prod 股票技术因子维护说明](/Users/congming/github/goldenshare/docs/datasets/stk-factor-pro-dataset-development.md)。它说明 Prod 当前实现，不直接规定 DG 的资产和自动更新行为。

### 2.2 当前代码核验结果

| 对象 | 当前实现及对本方案的影响 |
| --- | --- |
| 下载器实现 | [tushare_download](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/tushare_download/__init__.py) 已完成 T01～T14，原组件收尾记录为167项隔离验证通过。第一批已在CONTRACTS及BINDINGS登记唯一数据集`stk_factor_pro`，SDK_ADAPTERS仍为空；公开load入口已完成§3.1所述有界HTTP验证。尚无本数据集正式资产、job或sensor装配。 |
| 契约名称 | [contract_registry.py](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/tushare_download/contract_registry.py) 已解除名称必须以`@版本`结尾的格式绑定；保留名称唯一、版本非空、完整内容比较及unit身份，不增加旧名别名或两套命名。 |
| Prod 数据定义 | [market_equity.py](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/market_equity.py:1563) 定义 `stk_factor_pro`，261 个业务字段，按交易日执行，无对象池，分页方式为 `offset_limit`、页大小 10,000，Raw 写入后由视图提供 Serving。DG 不直接继承这些执行默认值。 |
| Prod 历史更新 | [unit_planner.py](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py:906) 在默认单日规划时检查因子存在，比较相邻交易日因子，为变化股票追加从已有最早日期开始的历史单元；这是可参考的业务流程，不是可 import 的 DG 执行器。存在性检查不能证明因子全市场完整。 |
| Prod 请求参数 | [request_builders.py](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py:859) 区分全市场单日请求和指定股票的历史区间请求。DG 也保留这两个明确用途。 |
| DG 指数因子 | [idx_factor_pro_raw_writer.py](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/io/idx_factor_pro_raw_writer.py) 可提供分页写入经验，但含 11 个主要指数筛选及已有文件处理规则，不能整份复制给股票因子。 |
| DG 复权变化 | [stk_mins_qfq.py](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/stk_mins_qfq.py)、[stock_daily_qfq.py](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/stock_daily_qfq.py) 已比较相邻交易日因子，但缺失值、新上市股票和浮点比较规则存在差别；可参考读数与对齐方法，不修改原消费者或先抽取公共模块。 |
| DG 技术指标历史更新 | [MACD/KDJ repair sensor](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/sensors/gold_stk_mins_qfq_macd_kdj_repair_job_sensor.py) 校验上游完成、完整股票范围和批次，不能仅凭某个 run 成功便认定历史已更新。股票因子沿用这个原则，数据仍从 Tushare 获取。 |
| DG 因子范围 | [adj_factor.py](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/assets/adj_factor.py) 的 Raw 接收接口日数据；[duckdb_sql.py](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/duckdb_sql.py:341) 的 Silver 当前只保留人民币、当前上市股票。不能据此删掉本数据集退市股票的历史。 |
| Catalog | [lake_assets.py](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/catalog/lake_assets.py) 当前没有本数据集；Catalog 是只读资产事实登记，不是运行时生成 asset、job、sensor 的引擎。 |

## 3. 已有真实核验记录与证据缺口

### 3.1 Tushare

以下为2026-10-18的`tushareMcp`核验记录；10月21日的来源覆盖与历史抽样核验见§3.2。各记录只证明对应日期和范围。

| 核验方式 | 结果 | 能证明与不能证明的内容 |
| --- | --- | --- |
| `000001.SZ`、`20261016`，不传 fields | 1 行、261 列 | 证明该样本的默认返回；不证明任何日期都完整。 |
| 同一对象、日期，显式请求全部 261 字段 | 1 行、261 列，名称和顺序一致 | 字段合同与该样本相符。 |
| 显式请求主键、复权因子及关键价格和指标 | `adj_factor=142.0699`、`close=11.5`、`close_qfq=11.5`、`close_hfq=1633.80385`、`macd_dif_qfq=0.051`、`kdj_k_qfq=40.23101` | 为关键字段提供真实样本；不据此推导所有指标的计算公式。 |
| `000001.SZ`、`20261012～20261016` | 5 行、5 个唯一主键 | 证明该对象的区间过滤有效。 |
| `20261016` 全市场，只取 `ts_code/trade_date` | 5,566 行、5,566 个唯一主键，日期均相符 | 小于文档所述 10,000 行上限；不证明最终发布时间、分页能力或所有历史日期完整。 |
| 休市日 `000001.SZ/20261017` | 0 行 | 休市空结果与失败分开处理。 |
| 已知停牌样本 `600825.SH/20260908` | 0 行 | 只证明这个样本，不扩展为所有停牌股票的统一行为。 |
| 只传 `000001.SZ`，不传日期，只取主键 | 8,455 行，`19910403～20261016` | 证明该对象可不传日期读取历史；不据此改成无时间快照，也不把 DG 初始化自动扩展到 1991 年。 |

261 个业务字段中，2 个身份字段为 `ts_code/trade_date`，其余 259 个为数值字段；字段名称、顺序、类型和含义必须逐项核对，不能只比较数量。

仍缺少的证据：

1. 当时MCP工具未开放`limit/offset`参数；2026-10-26第一批已用直接HTTP补证：固定`000001.SZ/20261012～20261016`，公开下载器按完整契约请求1次得到5行、261字段；另以limit=2、offset=0/2/4请求3次，得到2/2/1行，无主键重叠，合并后全部261业务值与组件结果一致。共4次真实请求、0重试。证据见[第一批验收记录](../../reports/stock_factor_pro_batch1_20261026/README.md)及[source/result.json](../../reports/stock_factor_pro_batch1_20261026/source/result.json)。这证明小页offset生效，未验证真实10,000行满页边界。
2. 未执行不带任何业务过滤的全局请求；MCP 的输入提示不能代替源 API 的参数合同。后续只在可限制返回量、已评估读取范围的方式下验证，不能为补齐用例无界拉历史。
3. 本次三个原始HTTP响应分别7,729/7,743/5,546字节，耗时0.1310/0.1160/0.1902秒；组件单次0.2968秒。仅为一股五日样本，不能据此宣称全市场耗时、内存或19:00时来源覆盖已达标。后续业务安排频率下的表现仍在对应批次验证。运行窗口按§8执行，源覆盖不足不阻止当轮有效日数据发布；内存上限沿用组件现有配置。

本地文档给出单次最多 10,000 行的依据；本方案采用的分页规则仍按 §6.4 标为假设。业务负责请求频率，不在本需求增加账号额度调查或管理。

### 3.2 Prod

以下先保留2026-10-18的Prod只读审计证据，用于说明当时差异；不用于确定当前初始化边界。10月21日、10月23日及10月24日核验边界见本节后文。正式初始化范围是来源表全部现有业务数据，执行时再确认实际首尾日期、按日计数及来源维护窗口，不沿用旧记录裁剪范围。

| 项目 | 结果 |
| --- | --- |
| 来源 | `raw_tushare.stk_factor_pro` 是物理表；`core_serving.equity_factor_pro` 是视图。bootstrap 只读 Raw 表的显式业务字段。 |
| 字段 | 264 列；排除 `api_name/fetched_at/raw_payload` 后为 261 个业务字段，字段序列与本地定义及源样本一致。 |
| 类型 | `ts_code` 字符串、`trade_date` 为 SQL DATE；259 个数值字段为可空 `double precision`。 |
| 索引 | `trade_date` 索引、`(ts_code, trade_date)` 索引及同键主键。具备按日期导出、按股票读取区间的索引依据。 |
| 首尾日期 | `2020-01-02～2026-10-16`。首尾日期不能证明中间无缺日。 |
| 行数估计 | `pg_class.reltuples=8,324,097`，为估计值，没有用它冒充精确计数。 |
| 体积 | 表及相关对象合计 23,548,297,216 字节，约 23.55 GB；不是 Parquet 体积预测。 |
| 最近单日 | `2026-10-16` 精确计数 5,347 行。 |
| 单个股票 | `000001.SZ/2026-10-16` 的上述关键字段与本轮源样本一致。 |

同日源返回 5,566 行，Prod 为 5,347 行，相差 219 行。这是**数量差异**，尚未核对股票集合，不能直接写成“Prod 缺少 219 只股票”，更不能据此自动补全全部历史。

这项差异尚未解释，作为Prod既有数据质量问题记录，不作为忠实导入已有合法数据的阻断条件，也不据此自动从Tushare补历史。导入验收核对Prod实际已有行与DG对应结果；它不证明Prod已经覆盖所有应有股票和历史日期。差异追查优先使用有界样本或聚合证据；确需读取全市场代码明细时另获全局读取批准。

2026-10-22 新增[10 月 21 日 Prod 只读审计](/Users/congming/github/goldenshare/lake_console/reports/stock_factor_pro_prod_audit_20261021/README.md)：当日上市 A 股 5,576 只，Prod 技术因子 5,567 只；8 只停牌股票在源因子及日线也无记录，另缺当日上市且已有源因子和日线的 `920296.BJ`。来源当日 5,568 个代码与 Prod 完整集合比较，缺口仅该新股。来源与 Prod 均识别 17 只复权变化股票，其既有 29,991 行均记录为 21 日刷新；34 行、全部 261 字段抽样与源一致。该审计不证明每个历史字段均已全量比对，也不解释 10 月 16 日旧数量差异。部分已审计股票已有历史起点为 2017 年，后续 bootstrap 不能继续把旧首尾日期当成当前范围。

本次另核对普通同步的日期范围：Prod `point_incremental` 只展开请求指定的一个交易日，普通请求仅有 `trade_date=T`，没有最近多天的滚动重刷。10 月 21 日两个实际定时节点（25501、25572）均记录 `mode=point, trade_date=2026-10-21`。复权变化股票的 `ts_code/start_date/end_date` 请求另外追加，不属于普通日数据范围。21:02 那次来源/保存 35,558 行，与当天 5,567 行加变化股票既有历史 29,991 行吻合；不能因此把总行数解释为全市场多日重刷。代码与实际节点证据详见审计报告 §4.1；没有取得原始 HTTP 请求日志，不声称复原了昨晚每一次网络响应。

2026-10-23 23:56（北京时间）通过规定的`psql-remote.sh`、READ ONLY事务重新核对本表元数据和按日期索引取得的首尾值，结果如下。没有导出业务明细，也未写入DG。

| 当前核验项目 | 结果及边界 |
| --- | --- |
| 实际首尾日期 | `2017-01-03～2026-10-21`；这是本轮查询时范围，不证明中间每天齐备，也不固定将来执行时的截止日。 |
| 字段 | 264列，其中261业务字段、259个`double precision`数值字段；`trade_date`为DATE。辅助列仍是`api_name/fetched_at/raw_payload`，不导入源业务契约。 |
| 行数估计 | `pg_class.reltuples=10,338,305`；精确总计数触及30秒语句超时后停止，未延长或反复扫描，不能把估计值写成精确行数。 |
| 存储体积 | 表本体30,069,604,352字节，表及索引31,262,990,336字节，约31.26GB；不等于导出业务字段或Parquet体积。 |
| 索引 | 日期索引、`(ts_code, trade_date)`索引及同键唯一主键仍在，可按月份有界导出。 |

管理员已确定导入Prod全部现有业务数据；实际初始化时在约定来源维护窗口内重新取得真实首尾和按日计数，保存到既有执行记录。若届时Prod增加了日期或历史，不静默沿用本表旧边界漏掉新增行。来源不再更新的约定、月窗口行数上界及超时属于执行安排，不再要求管理员重新选择导入哪些股票或日期。

2026-10-24的[Prod缺口审计报告](/Users/congming/github/goldenshare/lake_console/reports/stock_factor_pro_gap_audit_20261024/README.md)只完成部分日期，全历史缺口总数未取得，不能据此声称Prod历史齐备。本次已确认将完整覆盖统计放到bootstrap本地导入过程中，按§7.3执行；不继续把独立Prod全历史覆盖审计作为bootstrap前置。

## 4. 数据产品、时间与层级

### 4.1 数据集说明卡

| 项目 | 方案 |
| --- | --- |
| 中文名称 | 股票技术因子 |
| 来源身份 | `stk_factor_pro`；bootstrap 为 `prod_db_readonly`，日更及历史更新为 `tushare_api`，来源随执行记录保存，不混成一个来源说明。 |
| 用途 | 在 DG 中保存和读取股票日频技术因子，包含源提供的不复权、前复权、后复权价格及指标。 |
| 主键 | `ts_code + trade_date`。不增加频度参数、对象池或运营侧任意字段选择。 |
| 时间输入 | 正常更新为一个交易日；历史更新为明确股票集合及起止日期。接口可传区间，不代表每日每只股票都必须有一行。 |
| 执行单元 | 下载 unit 为一个交易日的全市场完整结果，或一只股票在一个明确窗口内的完整结果；网络分页不是 unit。发布单元是一个日期的一层文件，与下载 unit 不相同。日unit在内存保留到会话成功关闭，再直接构造Raw发布候选；历史unit及时落盘、释放内存。 |
| 完整性 | 按 SSE 日历确定目标日，按目标日非停牌上市股票代码集合报告缺失、决定是否继续补采及能否启动历史；股票覆盖不设日发布门槛。网络全部页已取完、本轮数据可发布、当天股票已补齐分别判断。 |
| 数据含义 | 保存源端当前可取得的因子结果。历史会随复权更新，不构成“历史当时所见”的版本档案。 |

### 4.2 Raw 与 Silver

采用以下两个资产；这是方案与 LLD 的计划定义，当前代码尚未接入：

| 层 | 计划资产 | 职责及路径 |
| --- | --- | --- |
| Raw | `raw_tushare_stk_factor_pro` | 显式保存全部 261 个源业务字段；路径为 `raw/tushare/stk_factor_pro/trade_date=YYYY-MM-DD/data.parquet`。`trade_date` 保留源 `YYYYMMDD` 字符串；Prod DATE 导出时按合同转换。 |
| Silver | `silver_stock_factor_pro` | 保留相同业务字段和主键，将 `trade_date` 标准化为 DATE；路径为 `silver/stock_factor_pro/trade_date=YYYY-MM-DD/data.parquet`。 |

以上路径均由 `defs/paths.py` 统一提供，不在脚本、页面和 Catalog 分别拼装。文件名固定为 `data.parquet`，与LLD§8一致。数值采用 DOUBLE，保留合法 NULL；指标可负，不设统一“全部非负”或“全部非空”规则。主键、日期解析错误、重复主键和数值转换失败必须阻止发布，并给出原因及样本，不能静默丢弃。

Raw 完整保留来源返回的业务行，包括历史退市股票；Silver完整保留这261个业务字段及对应行，将 trade_date 归一化为 DATE；其余合法值保留，不增删行、不填值、不按“当前上市”筛掉历史股票。来源存在非预期证券类型时先解释合同与真实样本，不能依靠隐含过滤消除行数差异。Silver 提供标准日期和可复用事实，不增加重新计算的技术指标，因此不需要新增 Gold。

独立使用 `cn_a_stock_factor_pro_trade_days` 分区定义，Raw、Silver 和其分区 checks 共用，避免借用分钟线历史起点或当前上市因子分区范围。初始化覆盖来源维护窗口内确认的Prod全部现有日期，起止由源表实际最早和最晚日期得出，核实SSE日历后注册其中全部可确认开市日；不按当前上市股票过滤，不沿用旧2020起点或把当前2017起点写死。日历已明确休市而Prod有源行属于已知冲突，须说明并停止处理该错误，不能静默漏行；日历缺失或无法判断不等于已知休市，合法Prod行仍按实际源DATE直接导入，统计保留“是否开市无法判断”，不伪造开市、分区注册或Dagster事件。源原有缺日单独记录，不虚构文件，完整范围与未知日期见§7.3。

Raw→Silver 按主键逐行对应，仅日期归一化，其他合法业务值保持；两层都通过必要校验才记为本轮两层处理完成。Raw 已写好但 Silver 失败时，保留已提交文件并如实记录未完成。日后获准新增清洗时，再同步方案、LLD、测试及验收。

## 5. 本次实际复用的能力

| 能力 | 当前代码 | 本次如何使用 |
| --- | --- | --- |
| Tushare 下载 | [download_api.py](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/tushare_download/download_api.py)、[公开类型](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/tushare_download/download_models.py) | 登记本数据集后，业务使用固定契约名和任务模式；分页、有限重试、排序、三类通知、取消及关闭由组件完成。不再从 moneyflow 或旧 resource 复制下载流程。 |
| 连接配置 | [configuration.py](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/tushare_download/configuration.py) | 已从 DG 现有读取逻辑抽取 token/地址读取与校验，组件创建时读当前进程环境。业务不传凭据；不替换其他旧读取入口。 |
| DuckDB 与现有业务写入 | [duckdb_connection.py](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/duckdb_connection.py)、[指数因子 writer](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/io/idx_factor_pro_raw_writer.py) | 复用连接及 SQL/COPY 能力；指数 writer 的固定指数范围不能直接套用。新业务按完整 unit 消费，不采用旧 writer 的逐页下载接口。 |
| 有界日历与连续性 | [bounded_continuity.py](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/asset_guards/bounded_continuity.py) | 核对 SSE 日历范围和开市标志，批量判断 expected dates 与可行动日期，不新增 SZSE 日历要求。 |
| Prod 只读导出 | [ProdPostgresResource](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/resources.py:105) | 复用只读事务能力，限定本表及显式字段投影，导出窗口、流式读取和限制见LLD§10.1～10.4。bootstrap 不经过 Tushare 下载器。 |
| 候选发布和恢复 | [moneyflow_update_publication.py](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/io/moneyflow_update_publication.py) | 参考提升意图、原目标核对、os.replace 和 checkpoint；其中路径约束、数据集身份及校验函数与资金流向绑定，不能未经调整直接调用。不以先抽取公共 publisher 为前置。 |
| DG 运行合同与 Catalog | [run_contracts](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/run_contracts/metadata.py)、[lake_assets.py](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/catalog/lake_assets.py) | 保留既有运行身份、metadata、批次与只读目录职责，引用 DG 本地源契约和本地存储定义，不重复抄字段或另建运行注册平台。 |

复用前继续核对实现和消费者的真实语义。本需求不安排其他公共能力抽取、现有数据集迁移或原有复权判断统一。

## 6. 完整源契约定义与下载器登记

<a id="download-contract-registration"></a>

### 6.1 名称、版本与维护位置

业务使用的契约名直接是 **`stk_factor_pro`**，与源数据集名一致。此次 `contract_name`、`dataset_id`、`source_api_name` 均为该值；`version` 初始为独立文本 `"1"`，不放进名称，也不加 `tushare.` 前缀。业务无需选择或拼接版本名。

在当前 [contracts/](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/tushare_download/contracts/__init__.py) 下新增本数据集的定义文件，使用现有 `SourceDatasetContract`，不新建契约平台、配置表、解析框架或另外的登记入口。下载器维护通用类型和校验；数据集接入开发维护这一份具体定义和登记，业务运行时只引用名称。

第一批已在`validate_contract()`删除名称与版本后缀的格式绑定，保留名称唯一、版本非空及完整内容校验；本数据集正式名称为`stk_factor_pro`，不登记带版本的旧名或别名。通用校验不把名称格式与独立版本字段重新绑定。

契约修改时更新独立 version 并同步本次获准消费者；DownloadUnit 已提供契约版本和内容摘要，业务据此保存执行记录和续跑依据。名称不变不等于内容相同，不能把旧契约下的完成记录直接当成新契约下已完成。

### 6.2 完整契约的具体内容

| 项目 | 本数据集定义 | 依据和限制 |
| --- | --- | --- |
| 身份 | 名称及源 API 为 `stk_factor_pro`；独立 version。 | 名称不带版本；完整内容变化仍可追踪。 |
| 完整业务字段 | 261 个有序字段：`ts_code`、`trade_date` 及 259 个数值字段，含 `adj_factor`、不复权/前复权/后复权价格及指标。 | 当前 Prod 字段序列作参考，本地 doc_id=328 提供源类型和含义，结合已有字段实测逐项确认。不从数据库全列直接生成接口 fields。 |
| 源类型与格式 | `ts_code` 为源字符串；`trade_date` 为源 `YYYYMMDD` 字符串；指标为源数值，明确可空和精度说明。 | `SourceField` 只写源定义，不写 SQL DATE、DOUBLE 等本地目标类型。字段数相同不能代替名称、顺序和类型核对。 |
| 业务请求参数 | `ts_code`、`trade_date`、`start_date`、`end_date`；以对应模式规定对象和时间角色。 | 源参数可选不代表运营输入全部开放；不把 token、地址、fields、存储位置或分页参数放入普通 filters。 |
| 模式 | 正常日更用 BY_POINT；指定股票历史更新用 BY_OBJECT_RANGE。 | 组件六种模式已经实现，本数据集只登记有用途并经过相应源证据核对的模式，不为字段消费差异建子契约。 |
| 时间 | 调用输入 `YYYY-MM-DD`，请求转为源 `YYYYMMDD`；闭区间，日级最小单位；结果按 `trade_date` 升序。 | 只是请求参数转换和结果排序；返回记录日期仍保持源表示。业务负责 Silver 的 DATE 归一化。 |
| 分页 | 暂定 offset 分页，完整参数见 §6.4。 | 属本数据集契约，不使用组件全接口固定页大小，不伪造可靠总量或下一页元数据。 |
| 证据 | doc_id=328、已有真实字段/过滤记录及后续分页验证记录。 | 已验证内容与设计假设分开记录，不能因登记成功就宣称源行为验收完成。 |

完整契约只包含源业务字段与请求规则。Prod 的 `api_name/fetched_at/raw_payload` 以及 DG 本地创建时间、执行信息、来源记录等辅助字段不进入接口 fields。同一数据集始终请求全部业务字段，业务只用部分指标或只更新部分股票都不产生字段子契约。

### 6.3 DG 内共用和跨工程边界

| DG 消费者 | 从同一份契约取得什么 | 自己仍负责什么 |
| --- | --- | --- |
| 下载器 | 完整 fields、参数、模式、时间与分页规则。 | 请求、解析、有限重试、完整 unit 交付和通知。 |
| 业务检查 | 完整源字段、含义及声明的类型/可空规则。 | 实际缺列、主键、业务时间、值域、行覆盖和拒绝原因；下载器不补列补值或替代检查。 |
| Raw/Silver 存储定义和 writer | 完整业务字段名及源类型。 | 维护本地类型映射、表/路径、辅助列、索引及写入规则；不得各抄一份独立业务字段清单。 |
| Prod bootstrap | 同一份 DG 契约的有序业务字段，用于显式源表投影。 | 来源白名单、过滤、只读窗口、Prod DATE 到 Raw 源格式的转换、候选校验和发布。 |

源 `YYYYMMDD`、Raw 字符串和 Silver DATE 的对应关系单独写入本地存储映射；不能要求源契约与数据表所有列及类型相等。主键 `ts_code + trade_date` 属本数据集业务检查和存储定义，不为此修改通用下载器职责。

本次只维护 DG 副本。以后财势乾坤获准接入时可保留独立副本，在开发/交付阶段使用已有 `ContractRegistry.same_content()` 核对解析后完整内容，包括字段顺序、源类型、含义、参数、模式和分页；本地证据路径可不同。运行时各读本地，不访问其他工程。Prod 仅参考，不实施其契约迁移或统一。

### 6.4 暂定分页规则

管理员已同意采用下面的契约规则。已有本地文档及Prod配置均提供10,000行依据；第一批已验证小页offset、页间主键及业务值一致，真实10,000行满页边界仍未实测，不能混为同一结论。

| 项目 | 暂定值 |
| --- | --- |
| strategy | 2，即 offset 分页。 |
| effective_limit / limit_param | `10000` / `limit`。 |
| offset_start / offset_step / offset_param | `0` / `10000` / `offset`。 |
| short_page_ends / empty_page_ends | 均为 true；非空不足 10,000 行或合法空页结束。 |
| 恰好满页 | 保留本页并继续下一 offset；下一页是合法空结果也可结束，不报满页错误。 |
| reliable_total_path / reliable_next_offset_path | 暂不声明，均为 None；不自行推测可靠总量。 |

第一批已按LLD§14.4用单股票短区间和可控页大小验证offset生效、页间主键覆盖及短页终点，并用隔离测试覆盖不足页、恰好满页再空、重试同页不重复交付。小页与真实10,000行满页的证据范围继续分开；不得为制造满页样本无界拉取全市场历史。

暂定分页规则按LLD落实，真实接入验收和正式执行前补齐相应证据；若源限制、步长或结束行为与假设不同，更新这一份契约、原方案、LLD 和测试，不能由业务在调用时覆写页大小或绕过终点检查。

### 6.5 登记步骤与调用例子

1. 按LLD§2核对名称校验、全部实现/测试引用及示例；调整命名规则后再登记本数据集，不先提交一个无法加载的正式契约。第一批同时须验证现有Definitions在隔离条件下可加载且未提前装配本数据集；复用已有受保护测试runner，仅增加固定用例清单，具体隔离方式见LLD§14.3。
2. 定义完整 `stk_factor_pro` 契约，在现有 `CONTRACTS` 中显式登记；名称唯一，一个名称对应一份当前完整契约。
3. 在 [BINDINGS](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/tushare_download/dataset_transport_mapping.py) 以相同dataset_id登记源API。第一批已固定直接HTTP、base地址路径并完成有界真实验收；不能因失败自动切换SDK，也不让业务选择。
4. 让下载、业务字段检查、Raw/Silver 映射及 bootstrap 投影引用该定义，核对全部 261 字段；不修改 Prod 定义，不迁移其他数据集。
5. 以隔离测试验证登记完整、名称查找、完整 fields、模式参数、分页和错误归属；再按获准范围做真实来源到业务保存的最小验证。

以下调用形式已经可以按正式名称加载；所示日期是用法示例，不表示其日更新业务已执行。第一批真实请求范围及结论单列在§3.1和LLD§14.4。

```python
from orchestrator.tushare_download import (
    DownloadMode, DownloadStatus, DownloadTask, TimeRange, TushareDownloader,
)

daily_task = DownloadTask(
    contract_name="stk_factor_pro",
    mode=DownloadMode.BY_POINT,
    points=("2026-10-21",),
)

history_task = DownloadTask(
    contract_name="stk_factor_pro",   # 同一份完整契约
    mode=DownloadMode.BY_OBJECT_RANGE,
    objects=("000001.SZ",),          # 业务确定的受影响股票
    time_range=TimeRange("2026-10-19", "2026-10-21"),
)

def require_complete(summary, *, expected_unit_count, expected_rows):
    if (summary.status != DownloadStatus.SUCCEEDED
            or not summary.download_complete
            or summary.total_units != expected_unit_count
            or summary.completed_units != expected_unit_count
            or summary.delivered_units != expected_unit_count
            or summary.row_count != expected_rows
            or summary.completed_row_count != expected_rows):
        raise ValueError("下载会话未成功完成，不能发布正式文件")

def download_day(task, *, control=None, on_progress=None):
    downloader = TushareDownloader.load()
    session = downloader.download(task, control=control, on_progress=on_progress)
    day_result = None
    with session:
        for result in session:
            if day_result is not None:
                raise ValueError("日请求必须恰好交付一个完整unit")
            day_result = result     # 只留当前运行内存，不保存日下载副本
    if day_result is None:
        raise ValueError("日请求未交付完整unit")
    require_complete(session.summary, expected_unit_count=1,
                     expected_rows=len(day_result.records))
    return day_result               # 交业务校验后直接构造Raw发布候选

def download_and_save_history(task, save_unit, *, expected_unit_count,
                              control=None, on_progress=None):
    downloader = TushareDownloader.load()
    session = downloader.download(task, control=control, on_progress=on_progress)
    source_rows = 0
    with session:
        for result in session:
            save_unit(result)        # 历史unit校验、落盘/读回，不发布正式文件
            source_rows += result.statistics.row_count
            del result
    summary = session.summary       # 正常退出with，关闭成功后才判断阶段完整
    require_complete(summary, expected_unit_count=expected_unit_count,
                     expected_rows=source_rows)
    return summary
```

两个下载函数分别用于上述daily_task和history_task，不能给日请求套用历史落盘流程。`expected_unit_count`由本次已核验任务范围得出，不是运营配置；上述两个例子均为1。日请求只保留当前内存结果，正常退出with并核summary后，由业务核`statistics.row_count == len(records)`、字段/主键/日期及完整内容，再将内存新源与当前正式Raw合并，直接写唯一Raw发布候选；不先写一份日源文件。历史`save_unit`须核源行数、保存行数及读回内容一致，逐unit落盘释放，全部任务正常关闭且manifest覆盖全部范围后才保存history source-complete，继而进入历史发布。关闭失败、STOPPED/CANCELLED/FAILED不能因unit已全部交付就放行；阶段失败仍按§9重新下载。日期传给下载器时统一使用ISO字符串，业务记录中的日期类型按本地合同转换。

无分类展开时，daily_task 的一个 unit 是该交易日全市场完整结果；history_task 的一个 unit 是该股票在所给整个窗口的完整结果，不是每天一次。示例短窗口仅说明输入，实际历史更新仍须覆盖 §8 确认的全部历史，由业务安排连续、有界且不遗漏的窗口。

窗口由业务在调用前确定，下载器不会根据内存余量自动缩小BY_OBJECT_RANGE范围。本数据集按LLD§5、§6、§10规划每股可信最早日期至目标T的完整范围。多个连续窗口按窗口分次调用。同一股票的多个窗口须分次构造任务，不能把重复代码的多个 object_ranges 放进同一个 DownloadTask；当前输入校验会以 1102 拒绝重复对象。

**股票代码的扇开由下载器完成，不要求业务逐只股票调用。**DG 业务确定变化股票清单及各股票的历史范围；同一窗口可一次传入多个 objects，各股票范围不同时可一次传入每个代码一项的 object_ranges。下载器现有 UnitPlanner 按代码生成 unit，串行下载并逐个完整交付。例如同一窗口传入 3 个代码，一个任务就会生成 3 个 unit。业务安排多个时间窗口时按窗口分次提交，可在每个任务中继续传入多个代码；“多窗口分次调用”不是“业务按代码扇开”。日常 BY_POINT 则直接按交易日取得全市场结果，无需逐个代码请求。

### 6.6 已有组件边界及接入要求

组件同步调用，业务在 DG 独立任务进程的执行线程中创建、使用和关闭实例即可；需要持续响应页面时由业务另开下载线程。组件不创建线程/子进程，不管理业务通信、全机并发、同 token 合计频率或账号额度。

业务可注册标准 PAGE_COMPLETED、RETRY_SCHEDULED、UNIT_COMPLETED 回调；回调在下载调用线程同步执行，只传摘要，不传分页数据。业务负责把摘要交给页面或其他进程，并在结束/异常后转发最终 summary；不能等待下载器另发结束事件。普通回调异常只影响观测，业务保存异常必须从结果循环抛出，不进入源重试。

完成一个完整 unit 后才交付不可变内存结果，不预取下一 unit；当前默认 2 GiB 是单 unit 工作空间约束，不是进程总内存保证。日阶段仅保留这一个完整unit直到会话成功关闭、直接生成Raw发布候选，完成必要对账后释放；不额外构造整份日行列表或复制一份日源文件。历史阶段逐unit校验、保存、读回并释放，避免把所有历史留在内存最后才写。

分页或重试阶段取消丢弃未完成 unit。完成回调中 cancel 或 DownloadCancelled 都先交当前完整 unit，再停后续；若已是最后一个则正常下载完成。使用 with 确保正常、提前退出、取消和业务异常均关闭自身资源，网络取消受当前同步调用返回/超时约束。进程重启后未完成 unit 从第一页开始；哪些结果已形成候选或正式提交由业务记录，不能用进度 100% 或下载完成代替数据集完成。

以上描述组件行为；本数据集采用更简单的业务重执行方式：日数据只在本次内存保留，下载会话成功后直接形成Raw发布候选，不保留下载副本；历史完整unit及时落盘，整个历史约定范围取全后才进入20日合并发布。任务一旦失败、异常退出或取消，重新执行不读取旧下载候选继续发布，而是重新下载原目标日和需要重试的原历史完整范围。仅执行历史repair时不请求T日数据；它先检查原T Raw是否齐备，不齐或未知报“原日期数据缺失”，再核原T Silver文件、有效检查及其对应当前Raw的身份，不满足报“原日期Silver不可用”，均交管理员处理，不代补T日两层数据。旧正式文件、完整名单、原范围和排障证据保留；排障记录不包含另存的日下载数据，必要发布候选失效后也不得用于后续任务。今天新轮同样重新请求T；前日一次限制不因人工重执行而恢复。此前整批历史成功且仍有效的记录可用于避免无关重复回刷，失败范围内已发布一部分不能据此缩小本次重新下载范围。详见§8～9；bootstrap恢复规则独立不变。

本节复用已完成组件，不重复列出全部错误码、超时及内部单元设计；以组件 LLD 和业务使用文档为准。

## 7. 历史 bootstrap

### 7.1 范围与来源

只从 `raw_tushare.stk_factor_pro` 导出全部现有业务数据的261个业务字段，包含全部股票和全部实际历史日期，不按当前上市状态、固定年份或人为日期范围筛减。不读Serving视图补字段，不带入三列系统字段，不读生产任务状态充当Lake数据事实。明确登记该表为此次只读导出的来源白名单；不因此开放其他表。

正式开始前在来源维护窗口内核实全表实际首尾日期和按日计数，将全部现有日期、已知缺日及来源截止条件保存到既有批准记录。起止日期是实际全量范围的记录及月查询边界，不是另行筛选范围的开关；来源截止日等于本次确认的最晚日期。**不在bootstrap前另做Prod全历史应有股票与实际股票的覆盖审计。**原有源按日计数、复权基准有界样本、来源稳定性及字段/主键对账仍执行，用来保证忠实导入，不承担全历史市场覆盖预审。Prod原有缺股、缺日或§3.2数量差异如实登记，不阻止其余合法已有行导入，不在bootstrap中嵌套Tushare补缺。导出漏行、字段/类型错误、来源变化及目标冲突仍按原规则停止。

源按日计数按自然月有界查询并汇总，覆盖源实际全范围；其合计用于最终行数对账，不要求额外执行整表`COUNT(*)`，也不能拿元数据估计值代替实际计数。

历史因子结果可能已经被 Prod 按较新的复权基准更新。初始化前还须核对 Prod 因子与 DG 同一截止日期的复权基准，选取发生过复权变化的股票和历史日期做有界对照；不能用单个当日价格相等证明全部历史已正确刷新。若发现未解释的不一致，先处理范围和来源结论，再执行正式初始化。

截止日期也不能阻止 Prod 在导出期间更新旧日期。正式导出须事先协调来源维护窗口，确认批准范围内没有并发历史重刷，并按窗口记录来源内容核验依据；发现来源已变就停止并重新确认受影响范围。不能通过锁住生产表或长期持有全历史事务换取一致性；续跑和最后来源复核的开销纳入预算。

### 7.2 导出、候选、发布

1. 用日期索引将源表实际最早至最晚日期按自然月完整规划为有界导出窗口，显式排序、261业务字段投影、SQL超时和窗口总行数上界；使用“上限加一行”发现截断，不把上限内的结果冒充全部结果。每次读取5,000行是内存批次，不是窗口总行数上限。执行前根据全部按日计数确定每月上界及超时，不能为满足上界而丢弃日期或股票。
2. 复用`ProdPostgresResource.connect_readonly_transaction()`，使用服务端named cursor，`itersize`及`fetchmany`均取同一个5,000行常量；普通cursor即使分次fetchmany也可能已把整月结果传入客户端，不能当作流式。按`trade_date, ts_code`稳定排序，当前批转为staging分片后释放；同一日期可以跨多个读取批次，见到下一日期或游标EOF才确认该日源完整，再形成一次该日期候选，不每5,000行覆盖一次正式文件，也不要求整月都读完才保存完整日期。月读取函数通过内部同步回调交付完整日期；回调依次完成Raw/Silver发布、读回和本地缺口统计，返回后读取下一日，不加线程或业务配置。回调失败立即关闭游标及只读事务，保留已完成日期事实，未完整日期不发布。按当前代码的2个身份/日期字段和259个Float(53)估算，5,000行净字段约9.94MiB，含协议传输约15～35MiB、Python基本行对象约40MiB；连同缓冲/转换按128MiB工作空间、256MiB余量考虑。这是已接受的估算，不是实测峰值或新增硬限制；字段类型、批次/副本变化时须重核。bootstrap不经过Tushare下载器，其64MiB HTTP及2GiB unit限制不适用于此数据库批次。月窗口保持有界只读事务，不能启用覆盖全部历史的数据库长事务。
3. Raw 候选与 Silver 候选分别校验。每个已完成独立文件形成可读回事实，从 staging 通过同文件系统 `os.replace()` 到正式目录。
4. 逐文件记录来源范围、候选/目标指纹、校验结果和完成情况。本bootstrap入口只支持无目标的首次发布、已有目标与本次来源生成结果内容等价，以及同operation沿原intent恢复；不同目标一律停止，交管理员单独处理。当前批准结构没有覆盖不同目标的授权字段，不凭一句“另行批准”就在本入口合并或覆盖。意外目标变化、候选变化或来源范围改变必须停止。
5. Raw 和 Silver 的多个文件不是整体原子提交。中断后保留已完成文件，续跑识别“已提升但 checkpoint 未完成”等情况，读回核验后推进；不能因状态记录失败撤销已提交业务文件。
6. 完成全部物理导入和§7.3完整性审计，确认批准全范围导入无遗漏、市场覆盖无缺口/未知、Raw/Silver必要校验均通过后，才能进入另行设计和批准的Dagster历史事件补记。存在市场缺口、依据未知或待完成导入时保持历史事件未补状态；合法已发布文件可继续使用，不回滚、不伪造绿灯。历史事件全部补完且事件/文件对应验收通过后，才能另行申请自动化启用。Direct Lake bootstrap不等于逐日Dagster backfill，事件不能代替文件验收，本轮也不执行事件补记。

bootstrap的批准输入、字段类型、单月行数上界R、事务内SQL超时、受控SQL与日期数组、来源身份和逐日期完整记录在LLD§10.2～10.4细化。日源完成记录、逐文件提升意图/完成记录和摘要由同一组固定类型及读写方法维护，明确文件字节SHA-256与业务内容摘要分别用于什么，不让导出方和恢复方各猜算法。全量业务范围已确定；执行前核实实际首尾和按日计数，批准维护窗口、资源开销、超时及正式执行，不再另选股票和日期子集。R+1仅为截断检测，收到超限行先停止，不能拿它当下一日期到达的证明；跨日片段须显式按日期过滤并核计数/摘要，完整日才发布。

5,000行只控制一次接收和转换的规模，不成为SQL总LIMIT。中断时未收齐日期的分片不可发布；已经完整保存或提升的日期按逐文件记录核对复用，未完成日期在其批准月窗口内重新读取，不按数据库offset/第几批断点续传，也不新增整月完整才可恢复的门槛。源维护窗口、原日期/字段和目标身份仍必须有效；不能拿旧来源记录覆盖后来合法更新。

**补数功能收尾直接更新原导入记录的当前状态，已确认。**原Prod源及忠实导入完成事实保留，现有逐日result和summary保存最新正式文件数量、SHA、覆盖及补数发布/check引用。例：原来源及导入4,800条，正式补数后当前Raw/Silver各5,000条、缺口0；原source_rows保持4,800，当前数量允许不同。“源=Raw=Silver”只用于原忠实导入验收，不再约束补数后的当前状态。原源0但补出数据时，原空源事实同样保留，当前文件和覆盖按实际更新。

补数控制层完成两层发布、既有检查及事件保存后，按LLD§10.5.6核真实发布引用、只复算受影响日期的代码差集、原子更新同一operation逐日结果，再从现有小记录更新summary，不重扫全部指标或重查Prod。仅Raw完成、Silver失败或记录写失败时不宣告当前齐备，不回滚正式文件；旧结果和旧summary必须核身份/逐日引用，不能继续放行。已有合法补数物化/check在最终补录计划中直接使用，不重复补记。原源0、当前两层仍无文件、本次补数完整请求仍0行且已知应有股票>0时，不伪造发布引用、物化或check；先保存真实来源成功/实际0/覆盖与完整缺失事实，并更新本operation当前result及summary，再按§8.1报业务失败。无需另建修复后审计入口。

**bootstrap后的首次人工补数已确定复用同一个日更job。**新增`purpose="bootstrap_supplement"`，以原operation批准摘要及当前缺口result的字节SHA核对首次请求依据；不伪造旧日更parent。仍走原T/P因子、完整日更新、必要历史回刷和§7.3的当前记录更新。具体配置、首次与重执行的区别及失败行为见§7.4和LLD§2.4、§10.7；不新增job、sensor或命令平台。

正式导出属于数据集全局明细读取，必须先获得明确批准；正式 Lake 写入、事件补记分别授权。小样本或代码开发授权均不替代这些授权。

### 7.3 导入过程中的逐日缺口统计

#### 7.3.1 统计依据与范围

bootstrap一边忠实导入Prod已有数据，一边利用本地数据统计股票覆盖，不额外在Prod做一次全历史代码集合扫描或导出，不为统计再次下载261个指标字段。统计依据只使用DG本地现行日历、`silver_stock_lifecycle`、最终`silver_stock_suspend_daily`及现行身份映射；不能用当前上市股票清单替代历史生命周期，也不另读Prod基础表拼一套依据。

开始前记录本次实际采用的正式DG文件身份、内容摘要及本地物理校验结论，读前后核对，按已批准月窗口复用；不复制、锁定或修改正式上游文件。日历按源实际首尾间每个自然日期核验，缺失或不可判断日期单列，不能自行推定开休市。生命周期固定使用正式历史文件，核现行完整schema、必需字段、主键、日期和人民币股票规则，不接受当前上市快照替代；该资产没有独立历史覆盖起止字段，不虚构“全历史来源完整”证明，也不增设人工审批或事件扫描。最终停牌使用正式日文件并核现行schema、日期、主键及域规则；符合这些条件的0行文件表示无停牌，缺文件或无效文件不能当0。身份映射须对相应日期有效。结果固定说明“按本次DG正式历史生命周期及最终停牌事实统计”，不声称独立证明上游全部历史证券或停牌从未遗漏。依据不足日期仍忠实导入合法已有行，覆盖记“无法判断”并说明缺哪项，不填0、不远程补读、不自动获取Tushare数据。依据之后修正，只在本地对受影响日期复算，不重读Prod技术因子明细。

统计先保留本次确认的源最早至最晚日期之间的完整自然日期范围，再区分SSE已确认开市日、已确认休市日及日历未知日期。缺口计算覆盖**范围内源计数为0的所有已确认开市日**；日历未知日记录“是否开市无法判断”，有源行时照原源实际DATE导入，不伪造开市标志、分区注册或事件，不因未生成Parquet就跳过该日期。源首尾以外的日期不自动扩进bootstrap，例如源截至21日时，22、23日缺少数据须单列为范围外情况，不能混入本次导入缺口或静默请求这些日期。源存在已确认休市日记录时按§4.2已知日期冲突停止，不靠覆盖统计删除记录。

#### 7.3.2 完整日完成后计算

1. 按§7.2流式接收5,000行批次；同一日可以跨批，只有下一日开始或正常EOF、未触发R+1且按日源计数及完整字段/主键对账通过，才确认这一日源完整。中断留下的半日数据不参与正式缺口统计。
2. 有源数据的日期完成Raw、Silver各自候选校验、正式提升及读回核对后，从这份正式Raw取主键；复用同次读回的键和计数，不为覆盖另扫全部指标。两个层的完成状态分别保留；仅Raw已发布而Silver未完成时仍是导入未完成，只能保存已有阶段事实，不能写“导入成功”或宣告本日正式统计完成。只有完整候选尚未发布时同样不能写成已正式导入。
3. 本地按交易日计算应有股票：`list_date <= d AND (delist_date IS NULL OR d < delist_date)`，北交所按现行`2021-11-15`开市边界处理，不照搬日线资产自己的最早数据起点；最终停牌仅`suspend_type='S' AND suspend_timing IS NULL`从应有集合排除，盘中停牌仍计入。应有、停牌及实际三侧均按同一现行身份映射统一旧新代码，再去重成代码集合；统一代码只用于统计，不修改忠实导入的源业务字段、不合并源行。
4. 用DuckDB集合差异取得“应有代码集合EXCEPT实际代码集合”，记录全部缺失代码与精确数量；实际存在但不属于应有集合的代码另外计数和保存，不能拿它抵消缺失，也不据此删除合法源行。应有5,000只、Prod只有4,800只且DG已完整导入4,800只时，缺口记200；应有A、B而实际A、C时，仍须报告缺B，不能因数量相等写成无缺口。
5. 首次忠实导入时，源按日计数为0需在月窗口正常读完、来源稳定且计数复核通过后确认，不伪造空Raw/Silver文件。没有既有目标时按空实际集合比较；无合法补数凭据的既有目标仍按冲突停止，不删除、不冒充原导入。后续按§7.4合法补出数据时，原空源事实保留，当前数量和覆盖按补数结果更新，不能再因原source_rows=0拒绝当前文件。依据完整且尚无补数、应有集合非空时全记缺失；依据不足则记无法判断。
6. 把逐日记录及对应缺失代码写入既有bootstrap执行记录所属staging审计目录；每份结果关联本次执行身份、日期、源计数/完整性校验、正式Raw/Silver状态、目标文件身份、本地依据身份、应有/实际/覆盖/缺失/额外数量与结果位置。完整代码明细存本地报告文件，不塞入sensor cursor或大量Dagster事件。

源到DG完整性与市场覆盖必须分开：源4,800条而DG少保存了行，或完整字段/主键对账失败时，这是导入失败，停止当前窗口并保留证据，不能把差额当作Prod原有缺口继续；源已有合法行全部导入后，相对本地应有集合仍缺股票，才记录为“按DG本地依据确认的Prod已有数据缺口”。它不证明全部指标值正确、全部复权历史已正确更新，也不新增覆盖率发布门槛。

#### 7.3.3 中断、复算与最终汇总

每个日期只有一份当前结果，同一bootstrap执行身份加交易日作为记录键，使用临时结果写全后原子替换，不按5,000行批次、恢复次数或进程重启次数累加。Raw/Silver完整日均已发布但统计尚未完成时，恢复核原导入或已获准补数对应的发布依据，再从该日正式Raw主键补算；统计已完成且文件及本地依据身份均未变时直接复用。正式补数造成的合法变化由补数收尾更新当前结果，不改原源/导入完成记录；无合法凭据的变更仍按目标冲突停止。原源尚未完整的日期仍沿bootstrap恢复，不由补数统计伪造导入完成。

同一bootstrap入口先区分实际剩余工作：仍需读取Prod、生成或恢复业务文件时，必须满足原来源维护窗口及源稳定条件；全部业务文件已完整发布、仅核对既有完成事实并复算本地覆盖时，不要求Prod维护窗口继续有效，不建立Prod连接。后者仍核原批准身份、正式目标冲突及DG维护条件，不允许顺带恢复文件发布或远程补读；发现导入尚未完成或文件冲突就停止并按原正式执行条件另行处理，不因“只统计”绕过原写入要求。

最终按批准首尾间完整自然日期范围核对记录，分列已确认开市日、休市日和日历未知日；用现有小记录求和，分别列原导入日期/原三项传输行数、原源空日，以及当前两层数量、当前缺口/额外记录、文件不可核验日期和其他未知原因。原导入数量从不可变原完成记录取，不从补数后当前数量反推；当前总数只在全范围当前文件均已核验时给出，否则为None。summary绑定逐日result字节SHA，变更或只完成一层时旧汇总不能放行。缺失总数仍为“股票＋交易日”条数，包含未知时不能报全范围精确总缺口。完整性条件使用最新合法当前结果，补数后不再要求它等于原Prod行数。

增量开销限定为本地当日主键列及按月复用的必要依据；不重拉Prod指标、不逐股票访问远程、不在sensor中全历史统计。日历/生命周期/身份小表每次执行或月窗口复用，停牌按对应日期文件一次规划读取；覆盖结果与缺失明细用列式集合计算和本地文件输出，Python只做窗口/文件编排和小型汇总。实现放在本数据集bootstrap内复用现行纯集合SQL语义，不逐日调用含instance事件/check核验的日更覆盖入口，纯统计不调用日更/repair网络入口，人工配置按§7.4。正常、恢复补算及最终汇总的读取/文件/SQL次数与拒绝阈值按LLD§10.5执行；最终汇总只读已有逐日统计，不再扫描全部技术因子。测试和真实验收见§12及LLD§10.5、§11。

最终历史事件补录及启用还须直接核同operation补数产生的必要历史无未完成范围/未解除失败，不能仅因当前覆盖缺口0就放行；沿用DG已有阶段/名单/完整发布记录，不新增审计入口或重算全历史。

### 7.4 bootstrap后的首次人工补数

管理员使用现有`raw_tushare_stk_factor_pro_update_job`，在同一个multi_asset配置入口`ops.stk_factor_pro.config`填`purpose="bootstrap_supplement"`。一次处理一个原bootstrap范围内、已登记的SSE开市日T；首次执行无需旧日更run，也不等历史事件补录或自动化启用。原全范围物理导入必须已经完成，当前缺口有明确依据；源空但已形成完整空源事实的日期也可以申请。覆盖未知不等于已确认缺口，应先处理依据。维护、队列及唯一写入沿§8.6，不因人工用途绕开；本设计确认不是某次正式下载或写湖的执行批准。

| 入口字段 | 首次补数的值与核验 |
| --- | --- |
| `execution_day` | 首次发起的实际上海日期，严格ISO，可为休市日；原生重执行保留原值，实际重执行时间另记。 |
| `target_trade_date` | 原批准闭区间内的开市日，等于所选分区；缺失/未知日历或未登记分区不得执行。 |
| `purpose` | 固定`bootstrap_supplement`；自动sensor只生成today/previous_day，不生成此用途。 |
| `scheduled_slot`、`submission_no` | 均为null，不能填写自动slot/提交序号，也不产生Q自动机会。 |
| `bootstrap_operation_id` | 非空受控operation标识，定位固定staging下的原approval和统计，不接受任意路径。 |
| `expected_bootstrap_approval_digest` | 原不可变approval的64位小写SHA-256，精确匹配，不可用当前文件摘要替代。 |
| `expected_bootstrap_date_result_digest` | 原operation当前`coverage/<T>/result.json`的文件字节SHA-256，核对首次操作所依据的缺口；不是业务input_digest或summary摘要。 |

普通today/previous_day保留原日期/时点/parent规则，三项bootstrap字段默认None且必须为None；人工用途必须提供三项，未知字段、bool冒充整数、其他日期/operation或混合用途配置在下载前拒绝。配置随本次run_config持久化，由本数据集run_contracts统一定义；不是新env、全局默认、热更或扩大数据源范围的开关。

首次无parent时，控制层按固定路径读回approval、原SourceComplete/两层导入完成事实及当前T缺口result，核operation/批准摘要、原全范围导入完成、T在原范围且已登记开市；result字节SHA、当前正式文件/发布依据、覆盖输入及完整缺失代码引用均须匹配，且覆盖已知、missing_count>0。不把source_rows为0当导入未完成，不要求Raw/Silver本来就存在；也不能仅凭“数量少”代替股票集合。核原T/P股票复权因子Raw就绪后，在技术因子请求前把已核授权的小摘要随原有开始AssetObservation持久化并读回，至少绑定operation、approval摘要、T、原缺口result摘要及缺口依据，不能只依赖内存或cursor。

原生重执行必须有同一日更job、同T和相同八字段的真实parent/root，保留原首次授权摘要及已知历史未完范围。前次日数据已补齐、只是历史或统计写入失败时，不再要求当前missing_count>0或当前result仍等于首次旧SHA；以已持久化的原授权证明本次仍处理原T，重新读取当前原T/P并完整下载T，之后重新下载原失败历史完整范围。若前次未保存授权且有明确PRECHECK_NO_DOWNLOAD事实，只可按首次规则重新核当前缺口；授权和是否已下载均无法确认时停止，不猜作首次；已有授权损坏或首次依据已变而无法核实就停止，不能伪造parent、用空名单掩盖或复用旧源。

固定业务顺序是：维护及身份/缺口授权→原T/P就绪并保存完整变化名单→全新T日完整unit仅本次内存→合并/发布Raw→由最终Raw生成Silver并发布→两层物化/check持久及覆盖→更新T的既有result/summary→Raw齐且Silver有效后处理必要d<T历史→更新本次历史实际影响的原operation日期result及汇总。T日不齐仍可发布有效数据并记录剩余缺口，历史不启动；源全市场完整unit不等于业务覆盖全齐。停牌、权威adj_factor、原可信历史范围及20交易日本地合并均沿原规则，不仅补若干字段、仅Raw或跳过必要历史。

补数无论在下载、两层发布、历史或记录收尾的哪一步失败/取消，获准重执行都重新下载T日和所需原失败历史范围，不读取失败源/候选或逐股逐页续接。已发布文件和原导入事实保留。日T两层/check已完成即更新该日统计，不能等待所有历史成功才记录；历史按已有检查通过的日期/批次更新，未完成一层的日期不宣告当前齐备。summary按阶段/本批收尾刷新；异常时对已保存逐日结果尽力汇总但不能覆盖原失败。记录写失败只影响当前统计可确认性，不回滚数据、不重发源请求；旧result/summary身份不符不得继续放行。原4800、补后当前5000按各自事实分别保存，不在旧总数上累加。

首次补数若原T没有既有日文件、本次完整请求0行且已知应有股票数大于0，按§8.1保存实际0和缺失清单、刷新当前result/summary后，主动使本job失败；不执行历史、不造空文件或绿色check。来源请求成功与业务补数失败分别记录。再次处理由管理员重新执行，sensor不提交人工补数，不能因retryable=True在本job中自动循环。该例外不改变有有效行的部分补数发布、旧文件保留或原Prod空源导入事实。

本用途不受自动19:00/午夜/Q一次限制，不消耗或重置自动机会；自动计数及轮次查询必须排除这个人工用途，活动任务检查仍包含它，已有同T结果读取可使用其有效日文件及完整历史成功事实。首次补数生成了真实日更run后，可原生重执行；仅剩历史失败也可由§8.5历史repair引用该run的完整plan/ranges及bootstrap上下文，repair仍不补T、不扩大原范围，历史发布后同样更新本operation统计。已有合法物化/check保留供最终事件补录直接使用，不重复补记。

验收至少覆盖：无parent的合法bootstrap首次补数；自动用途携带bootstrap参数、错operation/摘要/日期/缺口依据、未知或0缺口均拒绝；原空源0日可补；授权写后中断保留事实；日齐后历史/记录失败可按原授权重执行；失败全新下载；Raw-only、result/summary任一写失败不误报齐备；历史repair继承上下文；人工任务不挤占Q自动计数但仍占活动写入；多次补数不累计统计、当前结果已产生合法事件不重复补录。编码接口与失败metadata、受控路径和有界查询见LLD§2.4、§6.2、§10.5.6～10.7。

## 8. 每日更新与复权变化后的历史更新

bootstrap只读Prod全部现有业务历史；完成初始化完整性审计、全部历史事件补记及另行启用批准后，DG直接从Tushare自动下载。一个日更job承载所选目标日的更新和必要复权历史处理，自动及获准人工执行共用；管理员另可使用手动历史repair job处理保存的原目标日范围；sensor只检查、选择目标日和提交，不计算完整变化名单，不写Parquet，不拉历史。新sensor默认STOPPED。

本节使用三个不同日期：执行日期 D 是当前北京时间日期；目标日 T 是本次实际要更新的交易日；P 是 T 的前一交易日。先补上一个交易日时，T 不是执行日期，P 也不是执行日期的“昨天”。例如周一补周五，比较周五与周四因子，不能比较周一与周五。

### 8.1 当日应有股票、可发布数据与复权前置

这里的股票复权因子数据集是现有 Tushare `adj_factor`，在 DG 对应 Raw 资产 `raw_tushare_adj_factor`。`stk_factor_pro` 自身也返回一列 `adj_factor`；两者名称相同但分别来自两个接口。以前者的T/P值比较变化、生成回刷名单；后者同名字段按源保存并记录差异，不作为否定前者的依据，

覆盖以 T 日上市 A 股减去全天停牌的代码集合为准，盘中停牌仍列应有；这是已确认规则。按目标日读取现有 `silver_stock_lifecycle` 与最终 `silver_stock_suspend_daily`，不能用当前上市清单回推历史。生命周期采用 `list_date <= T AND (delist_date IS NULL OR T < delist_date)`；最终停牌中 `suspend_type='S' AND suspend_timing IS NULL` 表示全天。参考 [现有日线覆盖检查](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/checks/stock_daily_checks.py:882) 的语义，不照搬它的日线起点或其他限制。

本数据集日更/repair历史门槛及bootstrap统计共用同一纯代码集合函数，上市、全天停牌和实际三侧按正式身份映射及业务日期统一旧新代码后比较；缺映射/过期/歧义记未知。只用于统计，不改业务行、物理主键或下载对象。RawCoverage同时绑定身份文件SHA，变更即失效重算；bootstrap不调用带instance的日更前置，详见LLD§5.2.1及§10.5.3。这样旧日期补数不会出现统计已齐而历史门槛因代码字面不同仍被阻断，不影响其他数据集。

“确认全天停牌”必须有具体依据：复用现行 `suspend_d_ready_for_trade_date(instance, T)` 核对Raw与最终Silver的最新物化及关联检查，按记录关联T日最终Silver的日期、必需字段和文件身份。首次覆盖计算或依据变化时读取必要输入，已绑定的有效结论及文件身份未变时直接复用，不每次重跑停牌全表校验。历史前置和覆盖计算共用这一次已核验输入，不各自叠加固定修正源；输入未知或被改写时，覆盖不能宣告已齐，整个历史阶段不得启动，本轮有效日数据仍可发布。具体读取和失效判断见LLD§5.2、§9。

比较“应有代码减去合并后已发布代码”，不只比行数，也不只看本轮源响应。股票覆盖用于继续补采、是否启动历史及说明，不是本轮日数据发布门槛；覆盖输入暂不可用时不能宣告已齐，但已经取得的有效数据仍可使用。应有集合不是下载过滤器或清洗规则，来源其他合法行不能据此从 Raw 删除。每轮记录应有、本轮返回、合并后已发布集合的输入身份、数量与完整缺失清单位置；依据变更就重新核对，不沿用过期的 100%。本期 Silver 不额外过滤行，成功生成后与 Raw 的主键/行数对应；两层处理是否成功与源缺股票分别记录。后续新增清洗不作为当前前置。

本次新增的空源业务失败条件是：**原T没有既有日Raw/Silver文件，本次日unit及最终summary均证明完整请求成功但返回0行，并且可信覆盖依据确认应有股票数大于0。**此时来源请求仍记成功，先在既有阶段观察中保存本轮实际0、覆盖False、应有/缺失数量和完整缺失清单引用，再主动抛业务`Failure`：`failure_phase=day`、`retryable=True`、`source_error_code=None`、`allow_retries=False`。这些是请求及业务结果摘要，不另存日源文件或source-complete。不造空文件、物化、绿色check或日处理完成，不进入历史；bootstrap关联还须按§7.4更新原operation当前result/summary。统计或观察保存失败如实报告，不伪装为此可重试空源分支。覆盖未知不能硬写False，应有为0也不能套本条件。有效4000行相对应有5000行仍照常发布，两层check可通过、run可成功、覆盖False；本次源空但旧Raw有效时仍保留并核既有数据，不机械判空源失败。下载组件对合法空结果成功交付的边界不变。

**股票复权因子数据集就绪是提交技术因子 job 的前置条件。**更新 sensor 在日期已注册且运行窗口允许之后，检查股票复权因子Raw资产 `raw_tushare_adj_factor` 的 T 和 P；任一未就绪就不提交 job，也不消耗前日补采机会。job 开始再次核对，不能把“日期已登记”“文件存在”或“有一条因子”当成已更新好。

现有 [raw_tushare_adj_factor_ready_for_trade_date](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/sensors/readiness.py:1024) 关联该分区最新 materialization 及其既有三个 blocking checks：`raw_adj_factor_contract_check`、`raw_adj_factor_key_value_integrity_check`、`raw_adj_factor_partition_allowed_check`。这些检查不证明全市场股票覆盖；本方案复用其就绪语义，不新增一个要求全市场因子齐全的检查。job按已绑定记录核日期、文件身份，读取T/P值用于本次名单计算；既有合同、主键及正值检查不为每次使用再独立重复扫描。记录未绑定当前输入或身份变化时，只补必要范围的核验，不以旧成功放行新文件。Raw避免Silver当前上市筛选漏掉历史对象，不改现有因子资产和消费者。

任一需要比较的旧股缺 T/P 值，记录“无法判断”及代码，不能内连接静默丢掉或写成无变化；生命周期能证明的真正新上市股票不补造上市前历史。整体输入资产未就绪时不启动；输入已就绪但个别股票不能比较时，保留未判定范围，不能伪称全部历史判断完成。它不等于技术因子本轮股票缺行，也不恢复股票覆盖发布门槛。

### 8.2 一个 job 内完整时序

两个资产固定在同一`@dg.multi_asset(can_subset=True)`中编排；`can_subset=True`用于让未产生数据的分支可以省略输出，不开放业务只更新Raw或漏跑检查的能力。正式job固定选择Raw、Silver及两项综合check，执行函数第一步验证实际selection恰含这两资产与两检查；任一漏选在下载及文件写入前直接拒绝。该选择检查独立于业务空源是否失败：上游未就绪等明确`PRECHECK_NO_DOWNLOAD`分支只yield真实观察并正常结束，不能因没有资产/check输出而被框架误判失败，也不消耗Q机会。

1. 开始时核对目标日T、执行身份、注册日期及唯一写入条件；自动入口另核执行日期D、计划时点和原午夜截止，获准人工日更按批准原T执行，不受原午夜截止拦截。两者都再次确认股票复权因子Raw T/P已就绪，读取实际比较输入。
2. **在任何技术因子请求前**根据当前T/P重新生成并完整保存本run目标T的变化名单、对应因子值、各股历史范围、无法判断范围及输入依据；从DG既有记录取得同T尚未完成的原范围并保留。这里保存的是尚需回刷的股票代码及起止日期，不是当日日下载进度或下载文件。如果上次任务在生成回刷名单前就失败，这次重新读取原T/P复权因子、生成本次名单，再完整下载，不读取上次下载数据。现存历史意图记录若损坏或互相冲突则明确停止，不能把无法读出的旧待处理范围当作空。
3. 每轮以及失败后的日更重执行，都以BY_POINT重新请求原T的全部网络页。完整unit才交业务，当前完整UnitResult只保留在内存；正常退出下载with、会话最终成功且恰好一个unit及行数对账通过后，才进入发布。日阶段不保存下载副本、manifest或source-complete；业务错误不触发组件源重试。若满足§8.1“无旧日数据、完整请求0行、已知应有>0”，先持久化真实源成功及覆盖/统计，再主动业务失败，不进入下一步候选生成。自动五项原字段及三项必须为空的bootstrap字段、人工补数的完整八字段、准确层级和各自来源校验见§7.4及LLD§2.4；自动截止不得错误套到获准人工日更。
4. 检查内存新源的字段、日期、主键、类型及计数，按主键与当前正式T Raw合并，未返回旧行保留；直接生成唯一Raw发布候选，核新源/合并内容后提升并读回Raw T，随后释放日UnitResult及转换内存。直接从这份合并后的Raw全部业务行生成Silver T，日期转DATE，校验、发布并读回Silver T，保存绑定本次Silver物化的检查及对应Raw身份。Raw/Silver候选是原子发布必需的临时文件，不是下载副本或重执行缓存，失败后不能沿用。这里“完整Raw”指合并后的文件，股票是否齐备另算；日数据没有最低股票数、比例或全历史完成门槛。
5. **以已发布Raw T计算历史前置。**应有集合为T上市A股扣除确认全天停牌股票；必须有真实覆盖依据且缺失代码集合为空。Raw不齐或覆盖未知时，记录缺失及历史待处理，结束本轮历史步骤：不下载、不合并、不提升任何历史文件，也不先处理名单中已到的股票。Raw齐备且日Silver必要检查通过后，才进入下一步。全天停牌缺T行不会造成应有集合缺失，仍可处理原名单内该股d<T历史；盘中停牌不扣除。
6. 核对完整变化名单内本次尚待处理的原范围，以及相应当前T/P输入；个股缺比较值仍明确待处理，不伪造无变化。同股票、基准、范围、契约及处理规则此前**整批成功发布并读回有效**的历史可排除；某失败批次即使已发布一部分，其原完整范围仍作为整体重试，不据中间文件缩小范围。技术源同名adj_factor不同只记录差异，不阻断，也不改源业务值。
7. 对本次确定的全部股票及原窗口重新下载完整历史源，整个约定范围取全、保存并校验后，按升序每批20个交易日合并。每个d<T先合并、检查并发布Raw d，再从其全部业务行生成、检查并发布Silver d；两层均回刷，但两份文件不会同时原子生效，不能先只刷Raw便宣称该日期完成。当前T不由历史阶段覆盖。同一正常运行内从完整源进入发布是正常流程；任何阶段失败后再次执行，都重新下载本次失败的原完整范围，不读取失败run候选继续提升。
8. 历史下载前、首次历史提升前、整个范围完成记录前，核对本次T/P输入仍有效，并核原T Raw、原T Silver、生命周期及最终停牌输入的文件身份；Silver与当前Raw的关联失效时停止后续历史，不通过重做全字段对账绕过。因子输入变化则停止；覆盖依据变化时只重新计算原T覆盖，不能确认齐备则停止后续历史步骤，保留正式文件和待处理依据。输入未变复用本run核验结果，分页和每个历史文件不重复扫描整份因子或全市场覆盖，不在同job无限重算。
9. 分别记录本轮日发布、T日Raw覆盖和历史完成/待处理。历史源合法空或少回原应刷新的键，可以发布合法返回行并保留旧行，但完整范围未完成时run必须失败，不以日文件可用、已下载全部页或业务状态waiting伪装run成功。今天的自动流程在下一既定时点重新取得同T原失败完整范围；前日一次、午夜截止和永久错误停止规则继续生效。获准人工日更在同job内执行上述全部步骤，日数据齐备后直接回刷所需历史，不依赖另一个自动任务。业务从已正式提交文件读当前结果；历史每个日期的Raw、Silver依次发布，两层都回刷；Raw/Silver多文件不是整体原子事务，不新增全Lake版本目录或整体切换服务。

例如名单A/B/C在19:00请求前已保存，19:00日Raw仍缺非全天停牌B，则日Raw/Silver照常发布，A/B/C历史都不启动。19:30用新请求补齐Raw且日Silver通过后，才处理三股尚未成功完成的原历史；若B确认全天停牌，它不属于应有缺失集合，可以没有T行。若历史下载完整后发布到第10日失败，重试重新下载该失败范围全部历史，已发布前10日保留作当前合并基础，不从第11日接旧候选。

最终合并按旧B行、新U个唯一键、交集K核对`B-K+U`；例如旧4,000、本轮4,800唯一键且漏回旧50个，最终4,850行，数字不是门槛。合法空响应不删除旧行；首次无有效行不伪造可用文件，已知应有>0时按§8.1记录后主动失败。每个阶段按日期/层合并，不逐股重写全市场文件。

历史下载按股票组织，正式文件按交易日组织，因此在回刷或repair发布时需合入该日全市场文件，保留其他股票。历史本地合并固定每批20个交易日，按有效SSE日历及原范围形成升序d<T清单，末批不足20日照常处理；不凑日、越界、造空文件或自动注册旧分区。每批最多40个日期/层文件，仍逐文件校验、提升和记录。20日不是网络页、下载unit、独立修复范围、失败后可跳过下载的边界或整个历史成功标记；批次变化本身不改变业务内容身份。

业务适配逐行核历史响应的股票及日期属于原请求unit，不把请求A返回的B股票写入历史；日全市场仍接收其他合法股票。全部历史源完整后、首次历史提升前，用日期集合聚合核所有d<T源日期均已纳入可信SSE开市日期发布计划并注册分区；源含已确认休市行、日历未知或计划漏日就停止并说明，不能静默跳过后宣称整范围完成。具体接口及正反例见LLD§8.2、§9.1和§11。

### 8.3 前一交易日只补一次与今天的半小时轮次

| 已确认规则 | 执行含义 |
| --- | --- |
| 日期选择 | “昨天”固定为执行日期之前的上一个交易日。先判断它是否已补齐；已齐可转今天，未齐先安排一次补采，只在今天为开市日时执行自动更新；周末及其他休市日不发起前日补采或日更。 |
| 一次的边界 | 同一执行日期、同一前交易日，job 通过开跑前置并进入该次下载流程前持久记录开始；从此无论源失败、取消或仍缺股票，都不自动第二次补采。组件内部有限分页重试不算第二个 job。输入未就绪、仅评估或排队未执行不算实际尝试，但已有排队 run 必须占位，防止并行提交。 |
| 保护 | 补后仍缺、日下载/日发布失败且无法证明日覆盖已齐、或无法确认已齐时，当天不再推进今天，保留原因和缺失供管理员处理。不用下一半小时时点、新 run_id、进程重启或清空 cursor 绕开。仅历史失败而前日日覆盖已确认齐全，不据此阻断今天，也不自动第二次补前日日数据。 |
| 更早旧日 | 更早缺口保留诊断并交管理员；例如周一补周五仍缺会阻止周一更新，周二只检查周一，周五旧缺仍须人工修复。这是只补前交易日的范围限制。 |
| 时间 | `Asia/Shanghai`，19:00、19:30、20:00、20:30、21:00、21:30、22:00、22:30、23:00、23:30。前日补采先占用符合条件的一次任务；同一时点不连发前日和今天两个 job，前日补齐后在后续计划时点推进今天。 |
| 今天继续 | 今天已发布应有代码尚缺、覆盖未知、历史仍待处理或股票复权因子数据集输入后来修订时，在后续固定时点继续符合条件的新轮。即使日覆盖已齐，也保留轻量时点评估，输入未变且历史已完成才跳过新的技术因子请求。已发布成功本身不是全部完成依据；截止及前日保护不能被历史重试绕开。 |
| 无旧日数据的0行失败 | 仅§8.1限定条件主动Failure；今天可在下一允许slot新下载，不在同run/op自动重试。Q已持久化开始事实，机会仍耗用，不再补Q且当天不推进今天；不能改记PRECHECK_NO_DOWNLOAD。人工补数由管理员再次执行，不自动起job。 |
| 活动任务 | 同数据集有排队、待启动、启动、运行、取消中的任务就跳过，不积压；手动和 bootstrap 写入也须唯一写入。 |
| 午夜 | 次日00:00起不提交新尝试；排队任务真正开始时再核对原执行日期的截止时间，过期不下载或发布。午夜前已开始实际流程的任务可正常结束，不中断文件提升。 |
| 今天去重 | 目标日、执行日期、半小时时点构成轮次，固定时点用固定 run_key；不能每 tick 随机，也不能全日永远同一 key。 |
| 前日去重 | 前日补采使用执行日期＋前日目标＋本日唯一业务尝试身份；不能因半小时时点变更增加实际下载机会。创建/排队仅占位；只有明确证明先前所有发起均在预检结束且未进入下载，才在后续未用时点重新提交，业务尝试仍为1，提交序号单调增加以避开已用key。已有下载开始事实或执行情况不明时不再自动提交，详见以下规则与LLD。 |
| 错过时点 | 只考虑当前已到达的最近时点，不回放错过轮次；当前时点已有任务或已标跳过就等待后续时点。LLD 列出延迟、重启和长任务结束的具体选择算法及测试。 |

前日发起记录只按本数据集job、执行日期、前日目标和运行用途精确查询，最多11条用于发现超过十时点的异常；不扫描全run历史。每时点最多发起一次；旧run未终结就占位。旧run明确记为预检终止且未下载（`PRECHECK_NO_DOWNLOAD`），才允许下一时点使用新的提交序号；仅run失败、找不到记录或cursor为空都不能证明未下载。持久开始事实在首次下载前写入并读回确认，写不成功不联网，写后进程退出保守算已用；不追求证明网络报文实际发出的瞬间。LLD规定具体字段、统一run_key builder调用及异常测试，不另建调度状态表或下载器锁。

一次限制和原午夜截止只约束自动调度，不取消管理员明确处理问题后手动日更的能力。**管理员明确批准后，复用日更job跨过原执行日期午夜，重新下载原目标T；原run失败或成功但仍缺股均可处理。**人工入口仍须明确原T、来源及批准执行身份，核原T/P上游和原分区，遵守唯一写入要求；不恢复自动补采机会、不增加自动轮次。原完整名单不存在不阻止本次按当前T/P重建，已存在的同T未完成历史不能丢失。日Raw齐备且日Silver必要检查通过后，在同job内立即处理所需原历史，不需要管理员再触发repair；若仍缺股票则正常保留有效日数据和未处理历史，不自动扩大为连续手动任务。日更重执行及历史失败范围都重新下载，不复用失败任务候选；正式已提交文件保留。前日日覆盖已补齐与全部历史已完成分别记录，前者允许按规则推进今天；本期Silver与Raw行/主键对应，两层必要检查未通过不能标为处理完成。

永久输入/契约/权限错误、确定目标冲突需人工；今天临时源错误可在后续时点重试，前日则仍受一次限制。cursor 只存日期、轮次和小型状态，完整范围在业务文件；常态目标2 KiB、复杂目标3 KiB、UTF-8硬上限8 KiB。持久 run 和开始记录用于防重，重启不清除；不能因 cursor 缺失把次数默认为0，也不能无界遍历全部 run/event。

multi_asset的op固定为`stk_factor_pro`，同一配置合同包括`execution_day/target_trade_date/purpose/scheduled_slot/submission_no`及§7.4三项bootstrap字段。today/previous_day只使用原五项，bootstrap字段默认且必须为None；today提交序号为null，前日为1～10，attempt由用途派生。首次bootstrap_supplement允许无parent，但须精确核原operation及当前缺口；其原生重执行才从真实parent/root及开始授权摘要定位，不扫描目录或猜最新成功。分区必须等于T，各用途分别核日历、日期和时点，不增加token、fields、分页或路径覆盖项。自动机会查询必须限定自动来源，再核用途；不能先混合截取11条人工/自动run后过滤，导致人工补数挤掉前日实际开始事实。准确schema、样例和接口见LLD§2.4、§3和§10.7。

因活动任务跳过当前slot的决定使用现有SensorResult cursor保存到Dagster原生持久tick；当前cursor被清空时读取同sensor、当天、最近一条已完成tick恢复小型closed_slots集合，不新增文件、表或锁。上游未就绪但未占用slot不提前关闭；真正首次启动仍可在当前slot发起。查询与保留期异常时保守跳过当前slot，不追补旧slot，具体原生接口/边界见LLD§3.5。

永久输入/契约/权限、结构、目标冲突、本地读写和未分类失败停止对应T/阶段自动重试；临时源错误、§8.1无旧数据0行的日业务失败及历史源合法漏回原应刷新键，只允许按原时点及前日一次边界继续。历史漏键记录history waiting及原完整未完成范围，同时通过明确可重试失败使run显示FAILED，不能只写waiting后返回成功。sensor必须读取STEP_FAILURE的固定阶段/目标/retryable metadata，不能把主动0行失败误作永久源错误，也不能对其他失败仅因缺股票便再次提交。管理员修复并明确重新执行、取得同T/阶段真实成功事实后解除永久停止；清cursor、仅标run SUCCESS或未执行该阶段不能解除，已用前日机会不恢复。历史失败不清除日完成，也不阻止Q日已齐后推进今天；细化矩阵及有界读取见LLD§6.1。

### 8.4 变化名单的输入、持久化与分区注册

1. 名单归属于目标 T，包括前一交易日 P、完整变化代码/因子值、无法比较代码、最早已有日期至 T 的范围、源契约及处理版本、输入和范围依据。业务在 job 开始、技术下载前完整保存到本轮 staging；后续步骤读回，不靠 metadata 样本或 cursor 拼名单。
2. 每次同T日更job开始，根据当前股票复权因子数据集T/P重新生成本次完整名单；手动repair先按§8.5检查原T Raw齐备及原T Silver有效、对应当前Raw，再核T/P及原完整授权。不是每下载一页就重算，也不另建监控进程。新日更名单必须保留DG记录中同T旧名单尚未完成的范围；即使当前T/P重新相等，也不能把尚未完成的历史静默删掉，须按当前有效依据完成回刷，或有生命周期证据说明本来没有该段历史并留下具体原因。以前目标日的未完成名单保留且可追溯，不因今天建新名单而覆盖或丢弃。历史repair仍必须取得原完整授权，授权记录损坏时停止；这与日更从当前T/P重新生成名单是两个入口条件，不以“重新下载”取消原范围约束。
3. 名单复用与历史已完成复用分开。历史只从**此前整批已完整发布且读回有效**的完成记录推导，比较股票、该股 T/P 值、历史范围、契约与处理规则；不能把下载到第9股但整批第10股失败当作逐股续传。补入新股改变整份因子摘要，不能无条件推翻其他股票相同基准下的完成依据。
4. T 日正常增行不使已完成的 `d<T` 历史自动失效；目标被外部改写、股票因子/范围或规则变化则复核，不盲目复用。当前 run_id 是轮次身份，不是历史数据需要重下的理由。日期更早的待处理历史不在 sensor 中扫描/自动另起任务，管理员通过手动repair job引用其原完整名单/范围处理；不借今天的新名单覆盖旧待处理，不增加跨日自动任务。正常自动任务的前日保护与午夜截止不变。
5. 变化股有历史时更新已有最早日期至 T 的全部约定窗口，不缩成30/90日，不只改 adj_factor、不按比例缩指标、不本地重算。多个股票/范围交组件按代码扇开，多个窗口分次调用，完整 unit 立即保存并释放。最早日期从可信初始化记录或有界聚合取得，不在每 tick 扫全历史。
6. 独立动态分区 `cn_a_stock_factor_pro_trade_days` 由 Raw、Silver、job/check 共用。bootstrap在源全量范围及日历核实后先注册全部对应开市日；日常注册今天（若开市）和上一个交易日，不等因子或Tushare发布，不注册未来、不删旧键。用于比较的P若更早，只读已存在的股票复权因子数据集分区，不因此自动安排技术因子补采。
7. 借鉴分钟线完整清单、范围和执行前复核，不照搬500只上限、截断清单或新增跨 job 触发链。两个综合 check 不增加；覆盖或两接口同名因子值不一致不进入其失败条件。历史分区事件按LLD§4、§9绑定实际分区，开销按LLD§10统计；不能以当日一条事件代表全部历史。

#### 8.4.1 直接使用DG已有完成和检查记录

DG已有run、物化和asset check的持久记录；本数据集实施时把股票覆盖、历史完成及原范围引用写入既有阶段观察，后续直接读取这些凭据，不能另建一套每次从头审计的流程。常规入口通过同一有界读取方法取得日更、历史repair两个job中同目标T的观察及关联run，得到完整名单/范围引用、已完成范围、未完成范围、生产run身份及未解除错误；普通新轮没有parent关系也须能读取同T已有事实。原生日更run查询同时防止首次观察前退出被遗漏；明确过滤、固定排序、上限及超界处理见LLD。sensor只取小型摘要，不读取完整历史数据或扫描staging寻找“最新”。

使用记录时核对其目标T、资产/层、实际分区、生产run/物化身份，以及关联的文件、契约、范围和输入身份。身份未变且结论有效就直接使用，不重跑源到Raw、Raw到Silver或全历史对账；只有缺少必要记录、输入/文件改变或存在明确冲突时，才按必要范围核验或停止。run的SUCCESS只说明该run没有执行异常：当晚允许部分日数据发布，因此它本身不证明当天股票齐备，也不能代替原历史整范围完成记录。相反，某run历史失败但T日物化及check有效，T日文件和日覆盖事实仍可用。

repair先用绑定当前T Raw和当前生命周期/停牌输入的有效Raw综合检查及覆盖结果确认股票齐备，再确认原T Silver存在、检查有效且对应当前Raw；两项均通过后才进入历史前置和下载。不重新制造“旧数据＋本轮日下载”来复做日发布对账，也不能拿Raw与自身比较伪装源对账。记录缺失或与当前身份不符时不能直接假报齐备；按LLD限定的当前文件/覆盖核验处理，历史repair始终不下载T日、不嵌套日更新。历史repair成功记录须能被后续日更读取，避免19:00历史失败、人工repair成功后19:30仍重复重刷。

### 8.5 管理员手动历史repair job

**必须提供`raw_tushare_stk_factor_pro_repair_job`。**它只处理保存的原目标T及原历史名单/范围，不嵌套日更新、不发布T，不增加自动repair sensor。沿原历史窗口的BY_OBJECT_RANGE若包含T可完整保存源返回，但正式只发布d<T。

管理员从原日更或repair run的metadata复制完整配置。输入固定为四个必填字段：`target_trade_date`、`source_run_id`、`expected_history_plan_digest`、`expected_history_ranges_digest`。仅接受上述四项输入。`source_run_id`仅定位原完整名单、原范围、批准依据和失败证据，不表示从该run读取下载候选。引用run须属于本数据集和原T；可以是bootstrap_supplement的真实日更run，其已保存的bootstrap授权上下文须核同operation后继承，不要求重新证明当前缺口仍大于0。repair引用repair时保留原始完整名单/范围及bootstrap上下文出处，不改原run，不扫描历史任务或staging目录猜最新候选。

执行顺序固定如下：

1. 校验四项输入、run身份、原T、原完整名单/范围摘要、契约/规则及允许的staging位置；不匹配即停止。
2. **检查原T已经发布的Raw是否按当日应有股票集合齐备。**使用原T的生命周期和已核实最终停牌数据，不能拿今天覆盖替代。缺股票、Raw不存在、覆盖依据未知或无法确认齐备，直接失败，固定提示**“原日期数据缺失”**，附原T、缺失代码数量/证据位置及“请管理员先处理原日期日数据”。此分支零Tushare请求、零正式文件提升，不启动日更新，不以对象T单日窄查询确认资格，不自动补日，不擅自改分区。Raw齐备是手动repair与自动历史共同的硬前置。
3. **确认原T的正式Silver文件存在、已有综合check通过且对应当前Raw。**按原T取最新Silver物化及绑定该次物化的通过检查，核文件、契约和处理版本身份，再核其中记录的Raw文件SHA与当前已核Raw一致。若Raw只是等价重物化、文件SHA未变，不因Raw物化记录ID变化误判Silver失效。直接使用DG已有结果，不重做Raw到Silver的261字段对账；缺文件、检查缺失/失败、绑定错误、文件变化或Raw内容不符时，立即失败，固定提示**“原日期Silver不可用：<T>；请管理员先处理原日期Silver后重试历史repair。”**，附具体原因。本分支零Tushare请求、零历史提升，不创建或重写T日Raw/Silver，不把错误送入下载重试。
4. 检查原T/P的股票复权因子输入、原历史分区、当前目标及唯一写入条件。仅T/P值后来修订且股票/范围/契约/规则仍在原授权内时，本run保存新因子依据和差异；不要求管理员另起准备任务，也不因当前T/P重比相等删除原待刷范围。缺权威值或其他身份变化明确停止说明。
5. 根据原完整范围及可核对的**此前整批成功**记录确定本次尚待处理的原失败范围；此前独立成功的其他范围不混入。失败范围即使部分日期或股票已正式写入，也不从中间恢复下载；先保存本次完整名单及范围，再重新下载该范围全部历史源。空待处理范围核对后如实返回无待处理历史，不为产生网络请求重复刷成功结果。
6. 全部约定历史源取全并校验后，按20交易日/批、逐d先Raw后Silver发布d<T；核对并记录整个本次范围是否完成。源完整后进入发布属于本次正常流程，不是在失败任务之间复用源。继承bootstrap上下文时，把本次两层及checks已完成的原operation日期按LLD§10.5.6更新既有result/summary，不因本入口只处理历史而漏记统计；原T只读且不制造T新发布事件。
7. 任一阶段失败、异常退出或取消后，完整名单、原范围、失败证据及已提交正式文件保留；下一次获准repair仍从原名单定位失败完整范围，重新下载全部源，不读取本次失败候选续发。新记录写本run，不改原run；原完整名单/范围摘要用来限制授权，而非允许旧源复用。

原目标日T的Silver有效性是上述repair前置；**不要求每个待回刷历史日d的Silver预先存在**。历史d只在本轮刷新Raw后按同一业务字段生成Silver：缺文件则创建，已有则按本轮结果发布，并完成两层必要检查。不能因原历史Silver缺失而拒绝一次本来用于修复该历史的repair。

repair、日更、bootstrap及其他同数据集写入互斥，具体步骤和编码要求见§8.6及LLD§4.2。人工repair不受19:00～午夜自动排程限制，但原历史范围及正式执行仍需批准；不会消耗、重置或恢复前日的一次自动机会。缺应写历史分区或唯一写入条件就停止，不边修边扩大范围。

历史源网络完整但合法空、或少回原已存在且应刷新的键时，合法返回行可以合并，旧缺行保留并记录未刷新范围，不假报整批成功。例如原100条只返回99条，发布合法99条并保留旧1条，整范围仍待处理；该repair明确失败，提示“历史修复未完成”，附数量和完整清单位置。管理员查看原因、处理并获准后再次点击执行；sensor不替管理员提交repair，Dagster不自动重试该op。业务状态可记waiting，但不能令run显示SUCCESS。再次执行重新下载该原完整范围，不按缺1条续传。技术源同名adj_factor差异只排障，不要求历史值全部等于T日权威值，不新增blocking check。

[Dagster RunRequest / SensorResult](https://docs.dagster.io/api/dagster/schedules-sensors)对同一sensor已用run_key去重，清cursor不能恢复机会；最短评估间隔不等于精确准点。本规则仅在本数据集业务合同中落实，不改下载组件或其他数据集。

### 8.6 手动任务与排队任务的处理顺序

已确认采用既有队列加运营维护步骤，不给下载器新增锁、线程、进程管理或额度协调。2026-10-23核对本机正式Dagster配置为队列内同时只运行一个任务；日更、bootstrap首次人工补数、手动repair及人工重新执行均须经同一队列提交。直接文件bootstrap不受队列控制，必须同时满足以下步骤：

1. 运营记录`raw_tushare_stk_factor_pro_update_job_sensor`原启停状态，将其停止并确认生效；不改cursor或运行记录，不暂停其他数据集。只注册分区的sensor不承担下载，不增加停启要求。
2. **在提交手动操作之前**，核对本数据集日更和repair两个job的全部活动任务，包括尚未开始、排队、启动、运行、取消中的任务。让它们正常结束；确需取消由管理员明确处理，仍须等到终态。停止sensor不等于取消旧任务，停止时正在评估也可能补入请求，因此提交前要重新查询。
3. 运营确认没有另一终端bootstrap或其他手动写入，维护期间不启动第二个直接写入。不同目标日的历史任务可能改同一个旧日期，不能仅查本次目标日。bootstrap没有run记录，不能宣称查完Dagster队列就已证明没有bootstrap。
4. 检查通过才提交bootstrap人工补数、repair或启动获准bootstrap。人工补数使用§7.4八字段，repair仍只有原四项输入，不加维护开关、跳过检查参数或自动恢复功能。日更、repair和bootstrap入口复用同一活动检查；各job排除本次run，物理bootstrap不排除任何run。
5. **已启动的手动入口发现冲突立即失败，不在job内部等队列。**否则它占着唯一运行名额，后面的排队任务又无法启动。sensor遇活动任务沿原规则跳过时点；其活动查询失败也按本时点不能确认处理，关闭当前时点，不消耗Q实际下载机会。自动job开跑时尚未下载的冲突按原未开始分支结束。查询失败不能当作队列为空。首次正式提升前再核一次；若已下载才发现冲突，按实际失败阶段处理并保留证据。
6. 手动操作结束并确认任务/进程已退出、已发布文件和未完成范围清楚后，由运营恢复原本开启的更新sensor；原本停止的保持停止，首次bootstrap不顺带启用自动化。失败、取消、进程状态不明或恢复操作失败时先保持停止，管理员确认后再恢复。恢复失败不回滚文件、不改业务结果、不重置Q机会，也不补发过去时点。

LLD§4.2规定固定两job、五种活动状态、每job至多2条的有界查询、排除自身及错误提示；入口与首次提升前合计至多4次查询，不随历史日期增加。运营处理队列用原生界面查看全部活动任务，不能把程序最多4条冲突样本当成完整清单。运营维护步骤与入口检查共同成立，单次查询不作为锁；逐文件目标指纹核对继续保留。新入口及实际队列串行行为在实现后用临时instance验收，不操作正式sensor做测试。

## 9. 发布安全、失败与恢复

bootstrap、正常日发布及历史发布都使用候选校验、原目标核对、提升意图、同文件系统`os.replace()`和读回；多个Raw/Silver文件不是整体事务，不新增备份、快照、共享锁或下载器进程管理。bootstrap自身中断恢复按§7独立执行；本节失败候选弃用规则只规定Tushare日更及历史repair，不改写已批准的bootstrap规则。

日阶段不保存`source/day`下载文件、day manifest或day source-complete；完整结果仅在本次内存中使用。正常关闭下载会话后核unit、行数和summary，再以该内存新源构造唯一Raw发布候选；DG阶段结果及发布意图只记录必要计数、业务摘要和本次文件身份，不夹带日下载行或供以后任务读取的下载引用。Raw/Silver正式文件继续保留并可供业务读取，发布前的必要临时候选不作为重执行缓存。历史阶段仍保存`source/history/source-complete.json`，记录本run、D/T/P、原名单/范围摘要、全部约定unit和文件摘要，只证明当前运行历史源已取全，允许随后校验和发布；它不表示股票已齐或整个范围已发布，失败后仍须完整重新下载，不能沿用旧源。完整名单及原范围记录的是尚需回刷哪些股票的哪些历史日期，不是日下载进度。

| 情况 | 行为 |
| --- | --- |
| 日源完整且有有效行，但合并后Raw仍缺应有股票 | 发布有效日Raw/Silver，报告覆盖False，本轮run可成功；历史不启动。今天等下一固定时点，前日一次后仍缺则停止当天自动推进并交管理员。 |
| 日源合法空但有既有有效日数据 | 保留旧正式行，核当前合并Raw真实覆盖；不能只因本轮0行机械判业务失败或清空文件。 |
| 无旧日文件、完整请求0行、已知应有股票>0 | 先保存来源成功、实际0、覆盖False及完整缺失/必要bootstrap统计，然后主动日阶段业务Failure，retryable=True、source_error_code=None、allow_retries=False。无物化/check/历史；今天可下一slot，Q机会已耗且阻止今天，人工再次执行由管理员发起。 |
| 任何阶段失败、超时终止、异常退出或取消 | 获准重执行一律新下载。日更重新取得原T日源；历史重新取得该失败原股票/窗口全部源，不按页、股票或20日批次继续。下载器同页有限重试不受此条改变。 |
| 日内存结果已完整或历史源已保存完整，但清洗/合并/发布失败 | 日内存结果释放，不另存日下载缓存；历史旧源和未发布候选也不复用。下次重新下载，当前正式文件作为新合并基础。 |
| 已提交部分正式文件 | 保留、不删除、不回滚；旧源弃用不等于删除正式文件。重新下载后从当前正式文件合并，未返回旧行保留。 |
| schema、主键、日期、转换或目标冲突 | 保留原因及小样本，阻止错误候选继续发布；不让业务错误进入组件源重试，人工修正后重执行仍新下载。 |
| 正式替换成功但记录失败 | 当前文件尽力完成同步、读回及证据；仍失败则保留提升意图和真实文件，下一次先认清已提交事实用于排障，再新下载。不能用认清事实作为续发旧候选的入口。 |
| Raw覆盖不齐或未知 | 日数据仍可发布；自动历史不启动。手动repair直接报错“原日期数据缺失”，零网络、零正式写入，交管理员处理，不嵌套补日。 |
| 原T Silver不可用 | 手动repair在历史下载前失败，提示管理员处理原日期Silver；原文件、DG物化/check或对应当前Raw的身份不满足均不得放行，零技术请求、零历史提升，不代补T日Silver。 |
| 日数据已发布而历史失败 | 日文件可用，历史待处理；手动repair只处理原历史，不重新日更。历史失败前已提交的正式文件也保留，但整个失败历史范围下次重新下载。 |
| 历史源少回原应刷新键 | 合法新行和旧行保留，保存完整未完成范围、数量及清单，run显示FAILED；自动今天在下一既定时点重新下载原完整范围，仍受午夜/前日一次限制。手动repair报“历史修复未完成”，由管理员处理原因后再次点击执行，sensor不会提交新的repair任务、Dagster不自动重试该op。waiting仅表示历史业务未完成，不表示run成功。 |
| 观察或事件记录失败 | 不回滚业务文件；缺必要证据时不能假报整批成功，不因界面状态缺失自动把正式文件删除。 |

取消在网络请求、校验、提升前检查；当前文件已经替换时，尽力完成同步、读回及记录，再停止下一文件。候选失效仅表示后续不得使用，不授权本轮物理清理。旧完整名单、授权范围和失败记录继续限制新请求，不能据失败重执行扩大历史。

### 9.1 本run逐文件核对与成功历史完成依据

每次实际提升前，从**当前正式文件**生成候选并保存本run提升意图：阶段、原T、实际日期/层、原名单及范围、当前目标指纹、候选/预期发布指纹和必要检查结果。替换前再核目标没有在候选生成后被其他写入改变；不一致就停止，不能覆盖未知改写。正常流程只提升本run新源生成的候选。替换成功后读回并写本run完成记录；源/候选/意图/完成记录身份明确，不能只比文件个数。

任务已经失败后，提升意图仅帮助认清哪些正式文件已经提交，不授权继续提升旧候选。新run按本run新下载源与当前正式文件重新合并；来源本身可能修订，不能承诺来源数值永远不变。

此前**整批已成功且仍有效**的历史完成事实仍用于避免无关重复：必须整范围发布、读回及必要事件通过，且产生该结果的run最终成功；全部物理文件写完但事件或收尾失败，仍按失败任务重新下载。先直接使用DG记录中绑定股票、T/P、范围、契约、规则及文件身份的完成事实；身份未变不重复逐字段核验整历史。其他股票改变同一整日文件，不自动推翻本批成功结果，只在必要时对原范围做有界内容核对。失败批次里的部分写入不等于整批成功，不用于从中间跳过重试范围。成功依据与失败候选严格区分，前者保留，后者任何阶段失败后都不能续发。

## 10. 性能测算与停止条件

### 10.1 已有样本规模及暂定请求量模型

| 场景 | 当前可测算的量 | 验证项目（未实测） |
| --- | --- | --- |
| 单轮日更 | 当前源样本N=5,568、F=261；暂定p=10,000，`floor(N/p)+1=1`次正常请求。只保留一个完整内存unit，关闭成功后直接合并当前Raw、写唯一Raw发布候选，再生成Silver候选，不额外保存日源。 | 完整HTTP字节/耗时、内存unit与当前批转换/合并结果共存的峰值、正式旧文件/候选/检查及覆盖输入读取；不把取消日源副本误算成无需发布候选。 |
| 当晚多轮 | 19:00～23:30最多10个计划时点；其中可能先占用一次前日补采，不能再加出第11个自动时点。样本条件下合计至多约10次正常日查询。提前补齐和活动任务跳过减少轮次；组件重试、分页、历史及手动重执行另计。 | 十轮合计写入/摘要/事件成本和候选留存峰值，不能只估首轮。该数量不是下载器任务请求硬上限。 |
| bootstrap | 2026-10-18约832万行旧估计；仅259个DOUBLE约17.25GB/层未压缩，双层约34.50GB，未计其他字段与压缩。 | 当前准确日期/行数/窗口/压缩率、连接和超时、流式批量、峰值空间及最终验收。旧Prod体积不是Lake预算。 |
| 复权历史 | 实际代码×窗口unit，第i个H_i行，暂定正常请求`Q=sum(floor(H_i/p)+1)`；同页最多另加3Q次尝试。同基准同范围已完成历史不应每轮重下。 | 稳定完成身份、源基准/范围变更、D个日期的整日旧文件扫描、源候选和最终候选空间；T只由日阶段正式更新，历史正式合并d<T；实际事件数按阶段/文件核算。 |
| 手动repair | 原T Raw齐备、原T Silver有效且对应当前Raw后，仅按原名单/原范围重下尚待处理历史；失败原范围全部新请求，不重拉T日或资格查询；无待处理且此前整批成功有效时可0请求。 | 原T覆盖核对及原T Silver物化/绑定check/文件身份和Raw SHA关联读取、完整失败范围重下、当前文件合并、两层文件/check事件与最终审计；前置只新增原T一份Silver的有界记录及文件身份读取，不扫描历史Silver或重做261字段对账；计入旧证据仍占空间，不把不复用误算成已清理。 |
| 失败后重执行 | 无论源是否完整、失败在哪一步，一律重新取得原目标日或失败历史原完整范围的源；旧正式文件保留。 | 必须计入完整范围再次请求、已发布读回、重新合并、最终聚合及事件；不估算旧候选带来的网络节省。 |

**单日内存估算与依据。**以已有5,568行来源样本为规模依据，按5,600～6,000只股票、261字段（代码、日期及259个数值）估算，不另拉数据或跑压测。259个数值按8字节DOUBLE计算，净数值为`N×259×8`，约11～12MiB；这不是下载结果的实际内存。当前下载器的HTTP解析使用`int/Decimal`，每行以`SourceRecord.fields/values`及tuple保存，字段名元组可共用，不为每行复制261个字段名。以64位CPython常见Decimal约104字节、tuple引用约8字节估算，数值全部非空且按Decimal计算约144～154MiB，加行对象、值元组、代码/日期及分配余量，完整日结果按150～220MiB考虑；int和NULL占比会影响实际值。

下载解析时还会有响应字节、JSON对象及下载器内存统计对象；处理时会有本次UnitResult、列转换、DuckDB临时U和当天旧Raw/候选计算缓冲。按各阶段的较高占用保守估计，本次单日数据处理峰值约0.5～1GiB，先按约1GiB处理余量规划。这是已确认的估算，不是实测峰值、进程总内存上限或新增配置。组件现有2GiB单unit工作空间和64MiB响应限制保持不变，2GiB不是启动时预占；解析预留计数仍按组件算法执行，不能由此宣称任意64MiB响应都必然通过。DuckDB16GB是其既有内存限制，不是为本数据集预留16GB。

正常日两层发布/读回结束后立即释放本次结果、转换对象和临时U；失败/取消的finally也释放，不保留多轮日下载结果。释放指不再持有业务引用，不承诺Python进程的RSS立即下降。发布候选继续承担原子提升职责，不成为下一任务的下载缓存。估算仅针对一轮日数据，不套到bootstrap的5000行float批次或多股票全历史；编码时的具体释放位置及正反测试见LLD§5.4.1、§9.1、§10和§11。

历史导出按有界窗口及索引组织，不能每日期新建连接作为未经测量的默认，也不能改成无上限全历史事务。历史恢复和最终验收都要计入，尚无实测秒数，不据上述模型承诺吞吐或放行开发。

成功历史完成依据先取DG已绑定的有效完成记录；身份未变直接使用，只在输入、目标或必要引用改变时对实际股票/日期范围有界核对，不复制正式文件或拼接全历史进内存。不能每个时点重审全部成功历史，也不因其他股票更新而无条件重刷。新下载后的候选只从当下正式文件合并，写前核对目标未被改写。预算包含必要记录读取、失败后完整范围重下、旧证据留存、新候选、当前目标合并及最终读回。Raw/Silver按各自日期类型比较，记录和SQL见LLD§5.4、§8～9。

### 10.2 已确认资源参数、验收目标与分阶段核验

以下参数由本数据集运行合同单处维护。历史合并20日、bootstrap读取5,000行、sensor评估间隔是本数据集的本地运行规则，不进入Tushare源契约；DuckDB直接引用现有连接设置，不复制一套新的全局默认。精确常量、消费者、运行记录、加载生效及测试见§11与LLD§10。

| 已确认值 | 作用边界 |
| --- | --- |
| 历史本地合并20个交易日/批 | 原批准d<T日期升序切批，末批不足20日仍处理；最多40个日期/层文件逐文件提交，不是请求/股票/完整任务上限。 |
| bootstrap5,000行/读取批次 | 自然月查询、服务端named cursor、当前批落盘释放；跨批日期收齐后形成日候选，月不是整体发布/恢复门槛。 |
| 更新sensor60秒、分区注册sensor600秒 | 作为`minimum_interval_seconds`，不承诺精确准点、不改变19:00起固定半小时下载轮次，已用/跳过slot先轻量返回。 |
| DuckDB16GB、4线程 | 沿用`DEFAULT_DUCKDB_CONNECTION_SETTINGS`及既有连接；同任务同时1个主要DuckDB计算连接，在业务函数间传递，处理完关闭。不是整个进程内存保证或4路下载。 |
| DuckDB临时目录及512GB上限 | 沿用`/Volumes/datasource/.goldenshare_duckdb_tmp`和现有上限；上限不是预先占用，仍要核实际磁盘。它是计算临时空间，不存放源候选、发布候选、名单或checkpoint；这些继续只在正式staging根。 |
| 性能目标5秒/120秒/1200秒 | 分别为sensor一次评估、无历史正常日更、类似17股完整历史的估算评审目标；不是运行超时或强制终止，不要求为证明1200秒而实际跑17股全历史。 |

先按已批准参数、已有规模和明确标注的分页假设说明对象/日期/页数、请求数、SQL/连接数、读写和恢复成本，并补必要有界来源证据。实现后按LLD§11.1的小样本隔离计时与核验，分别记录正常、任一阶段失败后完整范围重下、重新合并、已发布事实核对和最后读回的开销；测量用于判断是否达标，不用于自动扩大范围或暗改参数。超目标先定位和说明，不降低质量、不砍历史、不强杀在途任务。下载器既定2GiB值沿用，不重新立项测量选值；bootstrap128MiB估算/256MiB余量也不是新增硬限制。

下载器当前默认连接/读取/请求时间为 5/30/45 秒，同页最多 4 次尝试、默认 1/2/4 秒退避，HTTP 响应上限 64 MiB，并受单 unit 解析/排序工作空间限制；具体边界见组件文档。组件没有频率配置，业务调度负责总频率，不另建额度管理或整个任务的请求数/时长硬截断。记录请求规模和耗时用于性能评估与排障，不把旧 transport 的其他数值带入本数据集，也不据既有样本承诺吞吐。

业务层将Dagster当前run的取消状态适配为组件要求的`DownloadControl.is_cancelled()->bool`，保存/发布也使用同一状态来源；普通组件检查的PG状态读取按内部1秒间隔复用，首次及保存/replace等业务边界强制读取，避免每行或排序比较都查询PG。状态缺失/读取失败直接停止，不伪装成未取消，也不放到可隔离异常的进度回调。实现接口、内部常量来源和正反测试见LLD§6、§10～11；不修改下载器、不增线程/锁/定时任务，1秒不是网络取消完成时限。

物理内存、单页字节或磁盘承载不足、执行超出已批准的数据读写范围时，停止领取新单元并保留已完成结果，输出剩余范围和原因；不得丢股票、减少字段、缩短历史或推进完成状态来规避问题。不把请求总数或整个任务耗时作为下载组件的人为截断条件。需要扩大范围时先更新本方案及对应 LLD，再申请执行。

sensor 不遍历全 Lake、不读取无界事件历史；批量检查须一次读取明确文件集合，避免包一层 Python 循环仍逐分区扫描。超过 100 个历史分区或 `分区数×blocking checks数>1000` 时，按性能治理规范做批量聚合与分层验证，不逐分区全深扫。

## 11. 配置及依赖边界

第一批已按本节落地源契约规则、本地运行常量及封闭八字段配置schema/纯解析，尚无正式job/sensor消费这些新增配置。后续每项新增或改动的配置，仍先在对应步骤LLD登记默认值及依据、来源/持久化位置、所有消费者、关联限制、生效方式、运营可见性和测试，再开发。

| 项目 | 归属与处理方式 |
| --- | --- |
| 字段、主键、日期、来源白名单、资产/check 身份 | §6 的单份完整源契约维护业务字段和请求规则；业务存储定义维护主键、DATE等目标映射和辅助列；DG run_contracts维护运行/asset/check身份，Catalog引用同一事实。 |
| Lake 与 staging | `paths.py` 和既有 resource；不加旧路径兜底、不引入页面或脚本独有默认根。 |
| Tushare 地址/token | 直接使用组件已实现的 configuration.py，在创建对象时读取当前进程 TUSHARE_TOKEN/TUSHARE_BASE_URL；不自行加载 .env，不再抽取读取方法，不迁移旧读取入口。业务不传凭据，真实token不进入Git、checkpoint、日志、argv或诊断报告。 |
| 正式存储目标、写入及发布规则 | 业务及本工程适用的写入/发布代码维护，不以抽取公共模块为前置；不进入Tushare配置或下载输入，不因此新增任意数据库/文件写入权限。 |
| 页大小、业务限频边界、单次超时、重试、内存和字节约束 | 分页大小/步进/终点在完整契约；整体限频由业务保证，组件不设置共享/每实例频率或发送协调。无账户额度或任务总请求数/总时长硬截断。新增配置先审计；不改旧消费者默认。 |
| 运行时点及轮次 | 只在交易日自动执行，19:00首轮、30分钟固定时点、午夜截止、Asia/Shanghai已经确认，计划由本数据集run_contracts统一维护，消费者为sensor、run_key及任务开跑检查；更新/注册sensor最短评估60/600秒，仍不等于业务30分钟。随代码加载，不新增env/页面开关。 |
| 覆盖与历史执行策略 | 覆盖影响补采并决定历史能否启动，不阻止日数据发布；输入是现行生命周期和最终停牌事实；前日一次保护、先生成名单再下载、先日发布后历史按§8落实；特殊情形见§15.1，不从源可选参数自动生成运营输入，也不新增未批准的历史股票数上限。 |
| 手动repair运行输入 | 仅`target_trade_date/source_run_id/expected_history_plan_digest/expected_history_ranges_digest`四项必填，无源复用开关。由原run的metadata提供配置，保存到新run_config及本run业务记录；消费者为repair op、原记录/覆盖校验、重新下载和发布。逐run生效，不是env或热更；摘要按完整内容核对，错误、原T Raw缺失/未知或原T Silver不可用均不下载不发布。 |
| bootstrap首次人工补数运行输入 | 同一个日更job采用§7.4的完整八字段。purpose只允许bootstrap_supplement时使用三项bootstrap字段；operation标识来自原批准记录，两个expected摘要来自不可变approval和当前缺口result，不默认生成、不允许任意路径。持久在当前run_config及开始授权观察，消费者为入口解析、授权/分区/原身份核验、完整日更新/历史、统计更新及同T结果读取；仅对本run生效。自动sensor不生成此用途；重执行沿原授权，测试错用途/来源/摘要、首次缺口消失、日齐后历史失败重试和人工不消耗自动机会。 |
| bootstrap 日期、来源截止日、窗口与发布范围 | 属已批准执行输入和记录，不成为任意扩大读取范围的开关。 |

本方案不改变 `foundation/ops/biz/app/qtf` 的依赖矩阵，不恢复 legacy 层，不引入 DG 对 Prod 业务入口的依赖。本次契约及业务接入位于当前 orchestrator；其他工程接入另行限定范围。

已确认业务参数及内部参数审计如下。第一批已将新增常量集中于`defs/run_contracts/stk_factor_pro.py`；后续消费者import，不各自写默认；代码重新加载后对新执行生效，不运行中热改。正式运行metadata及sensor装配在后续批次实现，须记录实际使用值、阶段耗时及sensor间隔；历史run保留当时取值。常量已实现不代表相关下载、发布或自动调度已实现。

| 参数与值 | 来源、消费者及测试 |
| --- | --- |
| `STK_FACTOR_PRO_HISTORY_MERGE_BATCH_TRADE_DAYS=20` | 本数据集run_contracts；自动历史/repair共用日期切批、批量读取/合并/核验，逐文件发布模块使用同一计划。测试1/20/21/41日、休市、末批、中途失败，批次不进入稳定源或历史内容身份。 |
| `STK_FACTOR_PRO_BOOTSTRAP_FETCH_ROWS=5000` | 同上；bootstrap的游标itersize、fetchmany和当前批落盘；测试跨批同日、月边界、中断及完整日复用，不能普通cursor/fetchall/累计整月或SQL总LIMIT5000。 |
| `STK_FACTOR_PRO_UPDATE_SENSOR_INTERVAL_SECONDS=60` | 同上；更新sensor装饰器及轻量评估，定义可见，测试不能每分钟下载、追排或绕过前日一次。 |
| `STK_FACTOR_PRO_PARTITION_SENSOR_INTERVAL_SECONDS=600` | 同上；注册sensor装饰器，测试仅今天/Q、真实开市、不删旧键且不等数据就绪；默认STOPPED。 |
| `STK_FACTOR_PRO_CANCEL_STATUS_POLL_SECONDS=1` | 本轮取消适配的内部编码常量，同一run_contracts维护，无env/run_config覆盖；只限制普通取消检查读取当前run状态的频率，首次及保存/replace等业务边界强制读取。模拟时钟核密集检查不逐行查PG、取消保持、读取失败停止；不改变网络超时或日下载频率。 |
| `DEFAULT_DUCKDB_CONNECTION_SETTINGS` | 原`defs/duckdb_connection.py`单一事实源，通过既有DuckDBResource/connect_configured_duckdb使用；不另建env/run参数或修改其他消费者。测试同任务一个主要计算连接、参数实际生效和关闭；metadata记录实际设置，暂存候选不混进计算临时目录。 |
| `STK_FACTOR_PRO_SENSOR_TARGET_SECONDS=5`、`STK_FACTOR_PRO_DAY_UPDATE_TARGET_SECONDS=120`、`STK_FACTOR_PRO_HISTORY_REFERENCE_TARGET_SECONDS=1200` | 本数据集run_contracts；只由性能验收/报告比较，覆盖小样本计时和全范围成本估算，不能传给运行取消/超时或下载器请求预算。 |

没有新增可任意覆盖这些值的运营输入；手动repair只有四个必填字段。将来改参数时先同步这两份原文档并核对消费者/测试，不借本次确认迁移其他数据集。

## 12. Checks、真实验收与人的排障

### 12.1 数据验收

| 检查 | 主要内容 |
| --- | --- |
| schema | 261 个显式业务字段、类型、日期格式和可空数值；Prod 辅助列不进入源投影。本地辅助列按本地存储定义另行检查，不混入接口契约。 |
| 主键及日期 | 主键非空、唯一、日期在执行范围并与分区一致；日阶段核完整内存unit及合并前后计数，历史另核源保存/读回计数，合法少股票不是错误。空结果不能删除旧数据或伪造已补齐。 |
| 行数与拒绝 | 下载unit的源行数与归一化行数对账；日阶段直接核内存新源与Raw发布候选的B−K+U关系，历史另核源文件保存行数。最终文件不能与部分股票的源行数直接相比；任何拒绝都有原因和小样本。 |
| bootstrap导入完整性 | 与批准来源范围逐窗口/日期核对源计数、显式业务字段/主键及Raw/Silver读回；实际少导入或内容不符即失败，不能仅凭估计总行数验收，也不能当成Prod原有缺口。 |
| bootstrap股票覆盖 | 导入后按§7.3在本地比较所有范围内开市日的应有与实际代码集合，含已核实源0行日；逐日记录精确缺失代码与数量或无法判断原因。既有缺口、依据未知不拦合法数据导入，不将覆盖未知或未完成导入写成已齐。 |
| Raw→Silver | 本期完整保留261业务字段及对应行，trade_date归一化为DATE，其余合法值保留；核对主键、行数及字段映射。 |
| 股票覆盖（不阻断日发布，阻止未齐时回刷） | 按目标日非停牌上市代码集合与合并后已发布代码求差，缺失决定补采并阻止历史启动；依据未知不宣告补齐，也不阻止有效数据使用。 |
| 复权更新 | 变化集合和范围完整、应更新文件读回、未变化行保持相同；“无变化”须能证明比较过。历史完成与当轮日数据发布结果分开，日阶段先提交，历史异常不回滚日文件；缺前因子不记0变化。 |
| 发布/恢复 | 文件指纹、批次、checkpoint和DG已保存事件对应；绑定当前身份的有效记录直接使用，身份改变才补必要范围核验，不能仅凭旧run SUCCESS证明新文件仍有效。 |

计算、合并和恢复正确性主要由独立金样本及离线有界验证证明；正式checks检查必要数据合同，不把全市场股票覆盖当作失败条件。覆盖另作有界集合计算；不新增按股票的常驻check、不为判断覆盖重拉全源或重算历史。已绑定当前文件及输入的DG检查、覆盖和完成事实直接供后续入口使用，不在repair或sensor重新跑全部发布对账。物理文件可用判断与正式checks共用纯校验及聚合语义，股票补齐和历史完成另有明确事实，不能把三者压成一个ready。

**已确认：Raw、Silver 每层只设一个综合 blocking check，共两个检查定义。**Raw 检查合并文件可读、字段/主键/日期及本次来源范围与合并计数；日阶段以完整内存新源和旧正式Raw为对账依据，不要求日源落盘，历史另核源保存与读回；Silver 检查合并文件可读、归一化/清洗后的合同及与本批输入的对应关系，本期按完整业务字段、仅日期归一化及与Raw逐行对账检查；后续新增清洗另行变更。不为每个字段、每只股票或每个历史窗口分别新增 check。发布前候选校验、文件检查及整批完成判断尽量复用同次聚合结果，不能在三个位置重复扫描同一批历史。两个检查定义不代表任意历史范围只产生两条检查事件；分区、事件数及读写成本见LLD§4、§9～11，并须在隔离 instance 核验分区及事件关联，不把样本 metadata 充当完整核对。

有有效数据但缺股票不使上述两个check失败，未补齐时本轮仍可发布成功；检查成功也不能令sensor误以为全天已经补齐而停止。§8.1限定的无旧数据0行失败是业务主动Failure，此时根本没有可物化文件或check结果，不能伪造失败/绿色文件check来实现。历史分区及当日检查依赖按LLD的分阶段编码设计落实，不能继续以全部历史已绿作为不加说明的当日发布门槛。只计十个实际执行的目标日发布阶段，共20个物化及20个检查结果（可能含一次前日，不能额外加一次前日而仍称20）；预检未下载、0行无文件不产生这些事件，历史阶段、同日重复发布和重执行另计，不能按不同日期去重估算，也不声称整晚只有两个事件。内容等价时保留正式文件，事件如实标记mode=reuse并绑定该文件的本轮校验结果，按LLD§4、§8执行。

复权变化清单和应发布文件的完成核对仍是必要业务条件，但不因此增加一个扫描全部历史的常驻 blocking check。初始化完整性审计与日常检查分开。检查名称、分区绑定及读取范围按LLD§2、§9落实，SQL/文件读取次数和正常/重入耗时按LLD§10～11验收；本次 Prod 审计不是这些尚未实现检查的性能验收，没有秒数承诺，也不能在缺少开销上界时进入开发。

Raw/Silver 分区 checks 必须显式使用与资产相同的 `partitions_def`；隔离 instance 中核对实际产生的 check event 分区，不能只看函数返回成功。开始实现后按代码约束运行必要单元、契约、隔离集成及最小真实验收。

源到本地及两层对账按LLD§9.1～9.2的确定规则实现：HTTP允许int/Decimal/NULL，Prod数值按已核实Float(53)取得float/NULL，统一显式转换为有限DOUBLE；不接受bool/字符串数字，不用TRY_CAST吞错，不加任意容差。HTTP日期严格YYYYMMDD，Prod DATE显式格式化，Silver再形成DATE；完整字段按名称对应并投影为契约顺序。先核唯一主键，再以NULL-aware双向键差和全部数值字段比较核对，合法NULL/负数正常；合并后保留旧行不能误当历史已经全部刷新。schema、函数签名、检查结果结构和独立样本均在上述LLD章节。

### 12.2 测试重点

本数据集实施时，至少覆盖：源超时、取消及业务进程退出后的新下载重执行；尾页/恰好满页/完整unit交付，业务调度与源限频错误归属；业务重复键处理；缺列、错类型、错日期和合法 NULL/负指标；各阶段退出后重下原范围；目标冲突；发布后状态写失败；历史只更新指定股票、跨年范围、没有变化、新上市与旧股票缺前因子；股票集合相同但值变化、同样行数但主键不同；正常复权变化不会被错误拦截。

夹具来自已核对的源字段、Prod schema 和有界真实样本。预期结果用独立可人工核算样本，不能用被测函数生成 expected。真实接入验收须分别记录源返回、归一化、拒绝、目标行数，mock 通过不能代替真实边界。

bootstrap缺口统计的独立小样本必须覆盖：应有A/B、实际A/C仍缺B；源缺股但完整导入可以发布；源计数与保存不符停止，不能记覆盖缺失；跨5,000行批次仍只记一次完整日；范围内源0行开市日不漏、不造空文件；源0日与既有目标冲突；Raw已发布而Silver失败、源已收齐未发布均不得记导入成功；全天与盘中停牌、新上市/退市日、北交所开市边界及旧新代码统一；本地依据缺失/过期/读取中变化记无法判断而非0缺口，不能触发远程加读或Tushare补采；已确认休市的源行停止，日历未知的合法源行照常导入且不伪造分区/事件，整段日历未知不能报总缺口0；统计写入中断、发布完成后补算、重复恢复不重复计数，依据变更仅本地复算；范围外日期单列，最终汇总保留未知日期且不重扫全历史指标。不以几十年真实跑数代替这些能人工核算的用例，最小真实验收复用已获准代表日期的bootstrap输出。

日下载存储回归必须证明：当前run不创建`source/day`、day manifest或day source-complete；完整日UnitResult在会话正常关闭前不得触发正式写入，关闭后直接形成唯一Raw发布候选，计数/完整内容对账仍执行。Raw正式发布后只由该Raw生成Silver，两个正式文件保留供业务使用。失败新run须重新请求日源，旧日内存结果或候选一旦被用于发布就使测试失败；历史源落盘和bootstrap原恢复规则不受影响。必要候选、内存转换与读回的峰值仍计入性能验收，不能以取消日源副本为由省略原子发布安全。

本轮衔接回归须证明：人工旧T日更跨原午夜仍重下T源，日Raw齐备且Silver通过后同job直接进入所需历史；原名单生成前失败也能按当前T/P重新生成，不读取失败候选；原run成功但缺股可获准人工日更，不恢复自动机会。同T新日更能够读取repair成功事实，绑定身份未变时不执行历史全量对账；身份变更只核必要范围，单独SUCCESS不能掩盖日缺股或历史未完成。历史100条只返99条后run必须FAILED且保存完整waiting范围，自动今天下一既定时点重新下载全范围，手动repair失败后由管理员处理原因并再次点击执行，sensor不代为提交，已发布文件保留。bootstrap同步日期回调每完整日只触发一次，异常关闭named cursor/事务；固定记录/摘要读写一致；仅本地统计在来源维护窗口过期后仍可运行且Prod连接数为0，任何需要恢复文件/源读取的分支继续受原条件约束。全范围导入、覆盖或依据存在缺口/未知时，不允许历史事件补绿或启用自动化；全部历史事件未补完时即使物理数据齐备也不得启用。

组件既有隔离测试按其原验收记录保留，不在本数据集重新立项开发六种模式。新增回归重点是：源数据集名可登记/查找；独立 version 与内容变化仍影响比较及 unit 身份；同名重复登记仍拒绝；完整 261 字段及所用两种模式；固定 HTTP 登记及有界真实边界；假定分页的正常与失败终点。名称变更时同步全部受影响夹具和测试，不靠保留旧名别名通过。

下载收尾回归须覆盖：本地date先转ISO字符串后才能通过组件输入校验；unit全部交付但关闭抛1304，或summary未成功、数量不符时，日内存结果不得形成发布候选、历史不得记录source-complete，两者均不正式发布。多窗口逐session核验各任务子范围，全部任务成功且覆盖完整阶段范围才记阶段完整。预检未下载仅真实观察、正常结束且不耗Q；无旧日数据、完整请求0行且已知应有>0，先保存源成功/实际0/覆盖False/完整缺失及关联bootstrap当前统计，再主动Failure，无假物化/check及历史。断言day/retryable=True/source_error_code=None/allow_retries=False、今天下一slot新下载、Q已用不得重补且挡今天、人工由管理员再执行。4000/5000部分发布仍可成功；源空但旧Raw有效不能机械失败，覆盖未知不伪False。历史物化先yield持久化，再绑定真实记录yield检查。管理员明确重新执行可处理已用自动Q机会或永久失败的原目标，但不恢复自动机会。

multi_asset固定`can_subset=True`，正式job选两资产及两check；测试完整selection正常，以及漏任一资产/检查在网络、候选及正式写入前拒绝。观察-only预检正常结束与0行主动业务失败是两条独立分支，不能靠前者伪造输出，也不能把后者改成框架缺输出异常。

事件隔离测试使用临时instance的内置`ConsolidatedSqliteEventLogStorage`统一事件库。默认SQLite按run分库并另有资产索引库，两处storage_id不是同一编号；不能把从run库读到的id拿去当资产索引物化id绑定check。测试保持目标T加两个历史日期，真实yield后有界读取，逐一核物化/check的partition、storage_id、run_id和timestamp指向同一实际物化，关闭并重开临时instance后仍可核；不修改正式PG配置或实现。此前已记录的5个测试失败保留为原始证据，不等于5个业务错误；本次只修设计，尚未重新测试，不能因更换设计就宣称通过。

存储边界还须证明：相同完整契约可由不同业务调用方选择本工程允许的正式目标和写入方式，无需改变下载配置；下载器不触碰正式数据库或文件。分别覆盖unit内部部分页成功但unit失败、完整unit已交付但业务未提交、全部下载结束但发布失败、提交后状态写失败和接收不明；业务失败停止后续下载而不触发源重试，已提交数据保留。合法NULL与负指标必须有可写入正例，不能只测试错误被拒绝。

本次多轮规则新增回归必须覆盖：19:00/23:30/00:00边界、固定时点不按结束后滚动、活动任务不积压、延迟和重启不回放全部旧轮；同轮去重/下一轮新请求；覆盖不足可发布、覆盖输入未知仍可用、同数量不同股票仍报告缺失；后轮源漏回旧股票仍保留；合法空结果不清空旧文件；当日发布成功与历史未完分别记录。

历史流程还须覆盖：同股多窗口分次且不重不漏、同任务重复object_ranges拒绝；任一阶段失败后的重执行都重新请求原完整范围，即使旧完整记录存在也不得读取旧源或提升旧候选；最终文件B-K+U及未变化行不变；稳定代码/因子/范围历史完成可复用，新增一股或正常改写T文件不误触全历史重下。日期T只由日阶段更新、历史d<T合并和历史失败不回滚日数据均须有独立样本；历史失败如实报告，不能以日文件已可用冒充整轮成功。进度100%不代表股票齐全或业务发布完成。

新增回归：权威T值2、技术源同名值1时仍以权威T/P生成名单，Raw/Silver保留源值1且差异可查。19:00 Raw缺非全天股票时名单完整保留、日数据可用、历史请求/历史提升均0；19:30新源补齐并完成日Silver后才下载全部待刷原范围。确认全天停牌从应有集合扣除；盘中/非停牌缺行、停牌输入未知或错日不能获得齐备结论。

手动repair核对四项配置与原完整授权；Raw不存在、缺股票或覆盖未知均直接报“原日期数据缺失”；原T Silver缺失、检查失败/缺失/错绑、文件身份变化或对应Raw内容过期，直接报“原日期Silver不可用”。两类失败均零网络、零正式提升，不嵌套日更新、不做T窄查询；Raw齐备且原T Silver有效、对应当前Raw后才重取原失败完整范围。已有有效DG检查直接使用，断言Raw到Silver全字段重新对账次数为0；原T Raw等价重物化但SHA不变仍可通过，Raw内容改变但Silver仍旧则必须拒绝。历史d Silver缺失时仍可从本轮刷新Raw生成，不能误加历史Silver全存在门槛。已成功的其他范围不被并入。历史合法空或漏旧键保留合法数据及旧行，不伪造整批完成；源错误、转换错误、取消及事件分区绑定仍须验证。§8.6的活动状态、排除自身、不同T重叠、停止sensor但仍有排队任务、查询失败与立即拒绝均须有隔离用例；维护和恢复步骤列运营检查清单，不为测试新增自动停启功能。

失败重执行必须逐点覆盖：日源完整未发布、日Raw已发Silver失败、历史源完整未发布、历史部分文件已发、替换后记录失败、取消及进程退出。每种新run都重新下载所需日/历史原范围，不能因旧完整源、旧候选、旧页/股票/20日checkpoint而跳过请求；旧正式文件、名单、范围和失败证据保留。19:00失败、19:30成功后重执行19:00也只用新请求，验证后轮新值不会被旧候选写回。正常同run源完整后进入合并不反复下载，下载器同页有限重试不变。bootstrap完整日复用、未完成日重取继续由§7及其独立测试覆盖。原100条源返99条时合法99条发布、旧1条保留且整范围仍待处理；T/P重比相等不能清空旧未完成范围。

### 12.3 可见信息和排障顺序

资产、check、job、sensor 均使用中文说明，讲明数据是什么、读取什么、何时可执行、会改哪些文件以及失败后如何处理。metadata 先展示 `summary`、`next_action`、结果、输入和过滤范围、诊断位置，再展示机器字段。

长任务展示阶段、当前日期/股票窗口、已完成/总量、页数、来源/目标行数、耗时和最后更新时间；业务将标准页/重试/unit通知接到现有任务观测，并在退出或异常后报告最终结果；下载器没有固定间隔心跳，不能承诺阻塞网络调用期间持续发回调。进度随已完成工作推进，不能伪造完成量，ETA 无依据时明确暂无法估算。

多个下载任务组成一个历史批次时，组件 total_units 和百分比只覆盖各自会话，不会自动累计成整批进度。业务依据已确定的股票×窗口范围及实际完成事实汇总批次状态，并分别展示下载、业务保存、合并和发布阶段；某个会话 100% 不能显示成整批完成。

每轮展示目标日、计划日期/时点、本轮源代码数、合并后可用代码数、应有/缺失代码数、覆盖依据和历史状态；完整清单放业务文件，metadata仅引用位置和摘要。午夜结束仍缺股票时如实显示缺失，不把窗口截止显示成成功补齐；前日一次仍缺则停止当日推进并明确提示管理员；更早旧洞不自动扩展补采，不在午夜开启新一晚重试。

| 运营看到的问题 | 首先查看及下一动作 |
| --- | --- |
| 未启动 | 先看目标T及P的股票复权因子Raw因子是否就绪、前日一次是否已耗且仍缺，再看注册日期、时点、活动任务。技术因子源股票未全不是门槛，但上游复权因子未就绪禁止发起job。 |
| 本轮已发布但仍缺股票 | 正常显示已可用范围及缺失；今天等下一计划时点，前日一次后仍缺则停止当天推进并交管理员。不将股票缺失视为blocking check失败，不用旧完整候选跳过新请求。 |
| 没有旧日数据且完整日请求0行 | 仅已知应有股票>0时按§8.1显示日更新失败；说明来源成功、实际0和缺口，统计先如实保存，无假文件/check。今天等下一slot，Q已用不重补并阻止今天，人工由管理员再次执行。 |
| 旧日期已退出自动范围 | 管理员明确批准后通过原日更job人工更新原T，可跨原午夜；仍核原T/P、原分区及互斥，全部新下载。Raw齐备且日Silver通过后同job接着处理历史，不另等待repair触发。 |
| 源请求失败 | 查看API、目标日/股票、页号、错误和重试；今天临时错误可在后续时点新轮再试，前日不得突破当天一次限制。获准重执行总是重新下载，不读取旧候选，不做页/股票断点续传。 |
| 行数/字段不一致 | 查看源/归一化/候选计数、原因和样本，不能跳过校验强行发布。 |
| 历史更新未完成 | 从原日更/repair复制四项配置，核对原T Raw齐备及原T Silver有效、对应当前Raw；Raw不齐或未知报“原日期数据缺失”，Silver不可用报“原日期Silver不可用”，管理员另行处理原日期数据。满足前置后重新下载原失败完整历史范围，不复用旧候选、不做T窄查询；原完整名单和范围不变。契约/范围/目标等冲突停止说明，不拿今天零变化当原日完成。 |
| 文件冲突 | 查看预期与实际目标指纹、已有任务/维护窗口，确认范围后再执行，不覆盖未知结果。 |
| 文件完成、状态不完整 | 按提升意图核清已提交文件并保留证据，不回滚。需要重执行时重新下载失败原范围，不继续发布旧候选；此前其他整批成功历史不无端重刷，新结果写本run，不改原run。 |

## 13. 开发批次、验收及正式执行顺序

### 13.1 开发批次

按以下七个主批次逐批开发、逐批验收，另设历史事件补录工具批次。每批通过后独立确认下一批；本节安排不等于后续开发或正式执行已经获准。2026-10-26第一、第二批均已完成并通过各自验收；第三批及以后、整个数据集尚未完成，结果见§13.2、§13.4。

| 批次 | 主要任务与交付 | 本批验收重点 |
| --- | --- | --- |
| 第一批：契约与基础结构 | 解除名称与`@version`绑定；登记261字段完整源契约、两种下载模式及固定HTTP mapping；统一Raw/Silver列合同、八字段纯配置解析、基础身份/日结果类型、纯路径及专属分区定义；提前用临时instance验证事件/check API。细节见LLD§14。 | 字段逐项一致且本地schema派生同一源定义；配置/路径正反例完整；不挂本数据集正式asset/job/sensor，不写正式分区/文件。4次正常有界请求核HTTP及分页，沿组件同页重试最坏7次实际发送，证据不扩大为全市场验收。 |
| 第二批：日下载、校验与发布 | 实现日完整unit内存接收、正常关闭及summary核验、源类型转换、当前Raw合并、Silver生成、候选校验/逐文件发布/读回；实现日更/bootstrap共用的纯覆盖集合计算。 | 少股票仍发布有效行；不保存日下载副本；半unit、关闭失败、非法日期/重复键不发布；Raw→Silver顺序和旧未返回键保留；文件check与股票齐备分开，全部测试使用临时目标。 |
| 第三批：复权变化与历史回刷 | 实现T/P变化名单、完整原范围/未完意图、历史全部unit下载保存及核验、20交易日合并批次、d<T两层发布及历史完成依据。 | 名单先于技术请求，以`adj_factor`数据集为准；原T Raw齐且Silver有效后历史；全天停牌例外；失败完整新下载，不按页/股/日期接续；漏旧键失败且保留已发布文件。 |
| 第四批：Prod bootstrap与统计 | 实现批准/源身份/自然月规划、5000行服务端游标、完整日同步回调、源→Raw→Silver对账、逐日缺口及汇总、补数后当前result/summary更新函数。 | 忠实导入批准全量，原Prod缺口不冒充传输失败；不累计整月、不另审Prod全历史；原传输/当前状态分开；原0行、跨批同日、统计失败及本地复算可核实。本批开发不执行正式导出。 |
| 第五批：完整日更job与手动repair | 装配自动两用途、原生日更重新执行及bootstrap首次补数；实现原run/PG结果读取、开始事实与授权、完整日更/必要历史/统计收尾；接通四字段repair。 | 合法无parent首次补数可用；缺口归0后原授权重执行不误拦；失败均重新下载；repair只d<T，原T/Silver不足零网络；统计失败不回滚正式数据，尚不启用自动触发。 |
| 第六批：分区、sensor、catalog与装载 | 实现今天/Q注册、19:00起半小时选择、前日一次、上游就绪、活动任务互斥及原生持久去重，登记catalog和正式definitions。 | 默认STOPPED；不积压；休市/午夜/清cursor/排队及手动任务符合规则；模拟时钟与临时instance证明有界查询，sensor不下载、不写业务文件。 |
| 第七批：主链集成及交付 | 在各批已完成测试上补最小真实交接、跨模块流程、进程退出/发布/事件故障、性能和逐项对账，补调用及管理员排障说明。 | 分开报告单元、隔离集成及真实核验；正常/重新下载/最终验收成本均列出；不把模拟或外推当作正式全量及真实复权分支验收。 |
| 独立工具批：历史事件补录 | 先完成该工具自己的方案、LLD及批准范围，再实现缺失事件规划、绑定、幂等补录及读回，复用本数据集文件/check语义。 | 只为完整审计通过的数据补真实绿色事件，已有合法补数事件不重复；不借bootstrap导出自动补录。正式event写入和自动化启用仍分别批准。 |

### 13.2 每批推进与变更处理

2026-10-26第一批已完成：定向合并281项、既有受影响159项主测试及513项子测试、受保护Definitions加载1项均通过；Ruff和文档完整性通过，4次有界真实HTTP请求验证5行、261字段及小页2/2/1一致。修订后的预检/0行分支及事件绑定/持久化均已实际验证，逐项对账见[验收记录](../../reports/stock_factor_pro_batch1_20261026/README.md)和LLD§14.6。没有新增业务决策阻塞；第一批完成后第二批另获批准，当前第二批结论见§13.4；不自动推进第三批或操作正式资源。

每批开工先读适用AGENTS、本文和LLD，将硬约束逐项对应当前代码、消费者、正反测试；补入原文档后编码，不另建冲突计划。各批同时完成测试和代码核实，第七批补跨模块证据，不把测试都拖到最后。未完成的执行入口不以空函数或提前挂正式definitions伪装完成。

收尾逐项给出代码、测试、真实证据范围、未覆盖项和下一批进入条件；提交仅含获准文件，保留其他工作区改动。源行为、现代码或框架API与方案冲突时，停止受影响的开发，说明发生步骤、原因、影响及建议，管理员review后先同步本文/LLD再继续，不新增兼容兜底或扩大跑数绕过。

### 13.3 正式执行顺序

开发验收与下面操作分开批准，不因代码完成便自动执行正式写入。

| 顺序 | 正式动作及前置 | 完成与下一步门槛 |
| --- | --- | --- |
| 1. Prod全量bootstrap | 主链开发/必要验收通过；刷新全表实际范围、按日计数、维护条件、参数和空间；获准全局明细读取及正式Lake写入后，先代表窗口，再推进批准全量。 | 忠实导入、源/目标对账、本地覆盖统计完成；原缺口/未知如实记录，合法文件可读，不补虚假绿事件。 |
| 2. 人工补齐及必要历史 | 按原批准及缺口日期运行bootstrap_supplement，必要时按原授权重新执行或手动历史repair。 | 原T及影响历史的Raw/Silver、checks、result/summary均更新，原导入事实保留；无缺口/未知/必要历史未完，完整性审计通过。 |
| 3. 历史事件补录 | 独立工具设计、开发与隔离验收通过，另获正式event写入批准后补仍缺或失效的事件。 | 全部获准事件读回且绑定实际文件/check，合法事件不重复，部分完成不能启用自动化。 |
| 4. 自动化启用 | 核初始化完整、必要历史完成、历史事件全部补完及日常最小真实验收后，另获启用批准。 | 按19:00起、半小时、今天/Q及历史前置运行；未遇到真实复权变化时仍不宣称其正式分支已验收。 |

## 14. 接入模板对账

| 模板要求 | 本方案对应位置 | 实现与验收要求 |
| --- | --- | --- |
| §3 说明卡、§4 分层、§5 命名、§6 路径 | §4 | 按已确定的资产、分区及路径实现，并完成全消费者审计。 |
| §4A Run Contract | §5、§6、§8、§11 | §6单份契约、名称/version、登记及存储映射；批次/运行参数和完整范围，旧消费者不迁移。 |
| §7 拉取、§7A 源合同/预算/实测 | §3、§7、§8、§10 | 暂定分页及后续实测、不传过滤的验证限制、业务调度频率、请求及恢复/最终验收开销；不新增下载器限频或账户预算。 |
| §8 类型、§9 Asset | §4、§12 | 261 字段逐项类型合同、依赖、metadata、隔离定义装载。 |
| §10/10A 可读性与排障 | §12.3 | 各定义中文说明、summary/next_action、进度与实际 UI 核验。 |
| §11 Checks | §12 | 同分区定义、实际 check event 分区及共享 readiness 判断。 |
| §12 Job、§13 Sensor | §8.3～8.5、§9、§13 | 单个自动日更job、手动历史repair job、独立注册sensor、触发窗口、批次去重、互斥、游标和默认停止。 |
| §14 初始化、§15 恢复 | §7、§9、§10 | 逐文件记录、重试/恢复证据、最终物理审计及独立事件授权。 |
| §16 开发切片、§17 授权、§18 验收 | §13、§15 | 按配套LLD完成代码、测试与真实证据对账，并记录独立验收结论。 |

## 15. 实施验证与执行授权

本次已确认：契约名使用 `stk_factor_pro`，version 独立；完整业务字段共用，DG 内维护一份；Prod 不统一、不修改；分页按 10,000 行 offset 规则暂定，后续调整落回契约和原文档；业务仍负责归一化、校验与保存。组件已完成，本需求直接接入，不先做旧数据集迁移或其他公共模块抽取。

bootstrap业务范围已确定为Prod来源表全部现有业务数据，包含全部日期、全部股票及261业务字段。最新只读规模证据见§3.2；这次范围确认不等于已执行全量导出或已批准正式Lake写入。

以下实施核验尚未完成，按所列范围取得并记录证据：

1. 按§3.2保留Prod既有缺口及数量差异，区别“忠实导入已有行”和“来源业务覆盖完整”；不把旧差异追查或独立Prod全历史覆盖审计作为导入前置。按§7.3及LLD§10.5在本地完整日导入后统计，不另扫Prod全历史代码集合，不在bootstrap补采。额外明细追查仍遵守独立授权。
2. 暂定分页真实行为、固定HTTP完整字段响应及十轮请求/读写成本。19:00起每30分钟及午夜截止已确认；源完整发布时间不是首轮和当轮发布前置。分页缺口不阻止设计，但真实接入验收须交代。
3. DG股票复权因子数据集的T/P Raw的实际字段/日期/股票覆盖与生命周期边界；Prod 历史复权基准与初始化截止条件的对应关系。
4. 全量范围已确定；执行前刷新实际首尾及按日计数，核实来源维护窗口，以及候选、正式文件、中断恢复、覆盖补算和最终验收的有界开销，不允许缩小来源既有范围。该源计数用于传输完整性核对；范围内源0行开市日在本地逐日覆盖记录中列明，不能额外要求Prod先完成应有股票缺口审计。
5. LLD已明确资产/分区/路径、唯一写入要求、20日合并、5,000行接收、60/600秒sensor、既有资源及逐文件记录，分开可用文件、当天补齐和历史完成；下载unit与发布文件不是同一个提交边界。后续实施按§15.1、LLD§11.1在对应阶段核验。

开发按配套LLD实施；全局明细读取、正式写入、历史事件和启用自动化分别取得批准。

### 15.1 开发对账

实施时逐项核对下表：

| 已确认要求 | 本方案落点 | LLD必须达到的编码细节 |
| --- | --- | --- |
| 昨天=上一个交易日；先补一次，仍缺则不推进今天 | §1、§8.3 | 日历选择、执行日期/目标日期、持久开始事实、排队占位、重启和失败正反例；不得增加第二次自动尝试。 |
| 日期注册不等来源；只看今天和前交易日 | §1、§8.4 | 独立分区注册器、仅新增、不删旧键；P的因子读取不等于安排P技术因子更新。 |
| 股票复权因子Raw T/P就绪后才提交技术因子job | §8.1 | 复用现有就绪函数及对应最新物化检查；开跑二次确认，目标T不能误用执行当天。不得让缺股票变成日数据发布门槛；历史前置仍要求技术因子Raw覆盖齐备。 |
| job最开始先保存完整变化名单，再下载技术因子 | §8.2、§8.4 | 从当前T/P重新生成本run完整名单；旧名单仅保留未完成意图，名单生成前失败不阻断新日更，repair原授权仍严格；sensor不计算名单。 |
| 每轮重核股票复权因子输入，保留旧未完范围，使用DG有效完成事实 | §8.2、§8.4 | 固定两job同T有界查询、统一输出当前完整/未完/已完/错误；身份未变直接读DG记录，变化才核必要范围；Raw缺1股时整个历史0请求，补齐后才启动。 |
| 日数据先发布，历史未完不回滚；每轮结果业务可读 | §8.2、§9 | 一个job、两个资产的分阶段组织、显式失败传播、同层综合check和历史分区事件；不新增全Lake版本服务。 |
| 完整选择与无旧数据0行失败 | §7.4、§8.1～8.3、§9、§12.2 | can_subset=True但只准完整两资产/两check；未下载预检观察-only正常结束。已知应有>0且无旧文件、完整新源0行，先存真实来源/覆盖/缺失及bootstrap当前统计，再业务Failure；今天下slot、Q已耗且挡今天、人工管理员再执行；部分有效发布及旧Raw保留不变。 |
| T由日阶段更新；历史正式合并d<T | §8.2 | 历史源候选仍完整保留T用于核对，历史不能重盖T；日源不另存副本，文件实际替换后再记完成。 |
| 股票覆盖决定补采及历史前置，全天停牌扣除、盘中保留 | §8.1、§12 | 最终生命周期/停牌输入、代码集合差；不据此删源行，合法NULL/负指标不误拒。 |
| 原目标日Raw齐备及Silver有效才执行历史 | §8.1、§8.2、§8.5 | 自动日Raw/Silver处理通过后核覆盖；repair先核原T Raw齐备，再核原T Silver存在、绑定检查通过且对应当前Raw，不执行T日阶段。Raw不齐或未知报“原日期数据缺失”，Silver不可用报“原日期Silver不可用”；两分支均零技术网络、零正式提升，不嵌套日更新。 |
| 新轮及失败重执行都重新请求，不复用失败候选 | §6.6、§8～9 | 无论失败点/旧源是否完整都重下原范围；不按页/股票/20日接续，保留正式文件、完整名单和证据。 |
| 人工旧日更新复用日更job，可跨原午夜并接续所需历史 | §8.2～8.3 | 显式人工执行身份和原T，原T/P与互斥不放宽；新下载、Raw齐备且Silver通过后同job进入历史，不恢复自动机会；上次若尚未生成名单，这次重新读取原T/P生成名单后下载。 |
| 历史漏旧键是可重试失败，waiting不等于run成功 | §8.2、§8.3、§8.5、§9 | FAILED及固定retryable错误metadata；保留原完整范围和已发布文件，自动今天下一slot重取，repair失败由管理员处理原因后再次点击执行，sensor不代为提交。 |
| bootstrap完整日回调、记录和本地复算闭合 | §7.2～7.3 | 同步回调顺序、失败关闭游标/事务、固定类型/摘要读写、无源空日及恢复；纯本地统计不连Prod、不受过期Prod维护窗口阻断。 |
| 完整数据审计→全部历史事件→另行启用自动化 | §7.2、§13 | 无缺口/未知的完整性凭据、全部事件与文件/检查对应、独立批准；各阶段不越权，不以合法部分发布替代初始化完整验收。 |
| 19:00起固定半小时，午夜截止，不积压 | §8.3、§10～11 | 迟到只选当前已到时点、稳定key、实际开跑截止；前日补采占用时点，不额外加出新自动机会。 |

以下业务边界与LLD§12一致：

| 已确认事项 | 执行含义 | 验收重点 |
| --- | --- | --- |
| 必须提供手动历史repair job | 正常日更仍一个自动job；另有`raw_tushare_stk_factor_pro_repair_job`读原完整名单/范围，仅发布d<T，完整历史响应可保留T原文；配置和流程见§8.5。 | 四项必填配置限制原目标/完整范围；原T Raw不齐直接报“原日期数据缺失”，无日更新/窄查询；失败原范围全部新取，各入口互斥。 |
| 以股票复权因子数据集为准 | 比较`adj_factor`数据集T/P、决定名单和回刷依据；技术因子同名字段值不同仅诊断，不阻断日发布或历史，不改源业务值。 | 输入2、技术因子源1仍能下载/发布；不能只改单列制造一致，历史各日期值也不必等T。 |
| 全天停牌且无T行也刷更早历史 | 变化名单内、最终停牌确认T全天、缺T技术因子行，允许d<T；不补造T、不影响当天覆盖口径。 | 全天例外正例；盘中/非停牌缺T行及停牌输入未知的反例；缺股票复权因子数据集T/P时不能套用停牌例外。 |
| 仅交易日自动、Silver本期沿用原规则 | 周末不自动新增机会；Silver完整字段/对应行、日期DATE及必要校验。后续新增清洗不是本期阻塞。 | 自动休市不请求、周一Q=周五；手动repair范围独立于自动时点但仍受执行授权和唯一写入约束；两层行/键对应。 |

人工与自动的范围分别为：自动只处理今天/Q及其本次历史；原普通日更人工重执行引用真实原run；bootstrap首次人工补数引用原operation及当前缺口；已有完整历史范围的失败批次可由管理员触发repair。bootstrap补数run也可成为后续重执行或历史repair的真实来源，后者继承相同bootstrap上下文并更新实际发布日期统计；不新增跨日自动调度。

### 15.2 分阶段工程核验

以下核验不改变已确认业务规则：

| 工程内容 | 当前落档与进入开发前的要求 |
| --- | --- |
| 前日未实际开始即终止后的重发 | §8.3明确每时点最多一次、业务尝试固定1、只有已证实预检终止未下载才增加提交序号；任一开始记录即耗用，不明不猜。LLD给精确过滤、11条查询上界、字段和builder参数；开工前核对现行API与保存/读回顺序设计，对应实现后隔离验证持久时机、重启和预检失败。禁止靠随机key或清cursor重置。 |
| 资产/检查编排与历史事件 | 同一multi_asset采用can_subset=True，正式job仍固定两资产及两check，执行入口完整selection检查在下载/写入前拒绝漏选；预检观察-only正常结束。事件测试按§12.2使用临时ConsolidatedSqliteEventLogStorage统一事件库，核真实yield/读回及重开持久的分区/id/run/timestamp绑定，不修改正式PG。此前5个测试失败未因文档修改变成通过，按修订设计重测后才能更新结论。 |
| 当前代码和消费者核验 | 已用CodeGraph核对Raw因子就绪、run_key builder及调用方；本轮未改共享helper、Prod或其他数据集。命名校验、261字段契约、mapping及全部实现/测试消费者，仍须在对应实现切片完成影响面审计。 |
| 有界来源与性能证据 | 固定HTTP完整字段/分页、T/P真实输入范围、正式Prod初始化范围和截止、窗口/超时/磁盘、实际事件数；已确认参数与5/120/1200秒目标，来源按固定小清单补缺，读写/性能实现后按§10及LLD§11.1隔离验证并外推十时点/原范围成本。不把目标报成实测，也不为20分钟目标默认跑17股全历史。 |
| 记录、配置及错误 | LLD明确名单、日内存下载统计、历史源完整、发布意图/完成和开始记录；时刻、20日/5,000行、60/600秒及验收目标单处run_contracts维护，DuckDB资源引用原设置。消费者/生效/metadata与测试已列§11，未来变更再审计；禁止业务保存失败触发源自动重试。 |
| bootstrap首次人工补数及当前记录 | §7.4和LLD§2.4、§10.7明确同job的bootstrap_supplement八字段、首次授权及parent/root重执行、完整日更新和必要历史。LLD§10.5.4～10.5.6明确CurrentPublication引用、原/当前计数、原空源补出行、受影响日期及result/summary原子更新，§10.6使用最新有效记录。回归必须证明日已齐但历史/统计失败后仍可沿原授权重执行且全新下载，不因当前缺口归0被误拦。 |

## 16. 补充参考与证据保留

参数与性能核验见§10，具体分阶段验证安排见LLD§11.1。

Dagster接口参考：

- [External resources](https://docs.dagster.io/guides/build/external-resources)
- [Asset checks](https://docs.dagster.io/guides/test/asset-checks)

2026-10-18 的核验记录已在 §3 标出日期、范围和限制；原临时证据文件不作为未来运行输入或当前已验证依据。后续真实验收将证据回写本方案或对应 LLD，不另起冲突口径。

### 13.4 第二批批准后的执行安排（2026-10-26）

第一批已提交为`0daf0b5e`，未push，其他任务修改保留。第二批依据LLD§15，按“日下载及控制→严格列转换/内存U→Raw合并/Silver生成→纯校验→逐文件发布→纯覆盖→隔离集成”执行。先补本节和LLD细节再编码，批准范围不包含历史回刷、bootstrap、PG事实读取、正式asset/job/sensor/catalog装配及正式资源操作。

日发布同步逐层返回实际发布及audit结果，Raw结果交出后才处理Silver，为第五批按顺序yield真实物化/check保留位置。首次空且无旧文件返回无文件事实，不在底层提前抛业务Failure绕过缺失/阶段记录；第五批依§4.0.1保存事实后终止。失败新run必须重新下载，当前正式文件保留，旧候选/intent不得续写。

只复用组件、契约、统一DuckDB连接、路径及适用的摘要算法；不直接调用含资金流限定/旧checkpoint续跑的发布函数，不抽取额外公共平台。沿已确认单日约0.5～1GiB估算、2GiB组件unit及64MiB响应限制；一任务一个主要连接，只处理T及两个目标文件，最终验收及失败重下载均计成本。

验收复用第一批一股五日261字段有界响应，在临时目录做正常/补入各一次；其余用独立小样本覆盖错误、取消、Raw成功Silver失败、等价不替换及失败后新下载。不新增真实网络、正式PG/Lake/Prod读取或写入，不做内存压测。Definitions通过原受保护入口核无提前装配。每项硬规则对应实现/正反测试并记报告，第二批通过后独立确认第三批，不自动推进。

2026-10-26第二批验收通过：373项定向回归（含新增92项）、159项既有回归、1项受保护Definitions加载通过，另518项子测试通过；Ruff和文档检查通过。日源内存/关闭后核summary、B−K+U、Raw→Silver、逐层发布及记录、失败新下载、纯覆盖共用均已实现。先保存历史名单造成run目录已存在的正常交接已允许，仅旧日候选/日发布记录拒绝续跑；两轮引用不累计及子进程Raw后退出再新下载均有测试。完整证据见[第二批验收记录](../../reports/stock_factor_pro_batch2_20261026/README.md)。第三批未开工，不操作正式资源。

2026-10-26提交后独立审计：第二批提交`5edb6409`，未push。发现候选子目录符号链接在COPY后才被拒绝，违反LLD§15.4；1行隔离复现已证明向run目录外写出候选。当前暂停上一轮推进第三批的验收结论，修正并补回归后重新验收。其余本批流程核验匹配，91项隔离回归通过；详见[独立审计](../../reports/stock_factor_pro_batch2_20261026/independent-audit.md)。本轮仅审计，未修代码或操作正式资源。

2026-10-26路径修复已获批准，执行细节见LLD§15.9：将现行路径检查复用为同一函数，两个候选构造函数显式接收当前run_root，在创建目录/COPY前检查完整路径及归属；发布入口先检查两层，Raw交付后的Silver再独立核查。存在或悬空链接、越界、旧候选一律写前拒绝，正常history-plan目录继续允许。不增加配置、锁、线程、网络请求或SQL，只增加固定两层的路径元信息检查；Raw已发布仍保留，失败新run重新下载。先确认反例在修复前失败，再修复、针对性回归和独立复核；验收关注外部目录零新增、已有文件不变及正常流程不误拦，不操作正式资源或推进第三批。

2026-10-26修复收尾：按上述批准方案落地，4个原复现反例在修复前失败、修复后通过；针对性23项通过，第二批四文件离线回归113项通过（1项本机HTTP适配明确未重复），Ruff及文档检查通过。正常history-plan目录不误拦，Raw已发布后发现Silver路径错误仍保留Raw；1行261字段样本SQL及数据写入数未增加。独立复核未发现新的确证问题，§13.4前述验收暂停解除，第二批具备申请第三批条件。结果见[独立审计收尾](../../reports/stock_factor_pro_batch2_20261026/independent-audit.md)。本轮未提交、未push，不推进第三批或操作正式资源。
