# 股票每日指标接入 DG 技术方案

状态：P0 有界核验完成，P1/P2 实施口径已批准，待编码验收；历史全量性能门禁未放行。尚未注册或写湖。更新：2026-09-15。

对应 [代码级 LLD](dagster-stock-daily-basic-onboarding-low-level-design-v1.md)。本文件定义目标和边界；LLD 定义代码、测试与分阶段验收。两份文件共同使用 R01-R12 约束编号。

## 1. 目标与已确认范围

把股票 `daily_basic` 的 18 个业务字段保存为 DG 按交易日管理的 Raw 数据，供后续研究、筛选和展示使用。它不是指数 `index_daily_basic`，也不是重新计算财务指标。

管理员已确认：

- 只保留 18 个业务字段，不带 prod 的内部系统字段。
- 日常增量直接请求 Tushare；历史首次从 prod 导入。
- 本轮先完成技术方案、详细 LLD 与一致性审计，不开发或操作正式数据。

2026-09-15 已确认第一版只增加 Raw、不增加 Silver，采用专属分区、两个聚合 check、最低覆盖及其局限；17:00注册、19:00更新、900秒观察间隔和最近10日窗口，默认STOPPED。历史实际导出及状态发布仍单独批准。

不做：prod 回写、Wealth API 切换、市值筛选功能、指标再计算、新增股票池、其它数据集改造。

## 2. 依据与模板对照

遵守根及 orchestrator AGENTS、[编码规范](../../orchestrator/CODING_STANDARDS.md)、[接入模板](../templates/dagster-dataset-onboarding-template.html)、[性能治理](dagster-data-pipeline-performance-governance.md)、[Schema 契约](dagster-asset-schema-contract-design.md)。

源资料：`doc_id=32`，仓库 `docs/sources/tushare/股票数据/行情数据/0032_每日指标.md`。源文档中的 15:00-17:00 是更新时间说明，不是当天完整性承诺。

| 模板要求 | 本方案 | LLD |
|---|---|---|
| 身份、来源与用途 | §1、§4 | §2、§3 |
| 路径、分区、字段 | §4、§5 | §3、§4 |
| 源端实测及 7A 非 Tushare 来源审计 | §3 | §1、§7 |
| asset/job/sensor、metadata、日志、cursor | §4、§6、§8 | §2、§5、§6 |
| checks 与 readiness | §6 | §5、§9 |
| bootstrap、性能、状态发布 | §7 | §7、§8 |
| 开发步骤、验收与风险 | §9、§10 | §9、§10 |

## 3. 当前代码与真实取样

### 3.1 当前实现事实

prod 的 `src/foundation/datasets/definitions/market_equity.py` 已定义 `daily_basic`，每页 6,000；`src/foundation/models/raw/raw_daily_basic.py` 定义原始表。DG catalog 尚无该数据集。本次不能直接 import prod DatasetDefinition 或搬用它的股票池逻辑。

历史来源限定 `raw_tushare.daily_basic`。已核对 21 列，其中 18 列业务字段；主键 `(ts_code, trade_date)`，没有日期前导索引。既有只读账户有 SELECT 权限；权限存在不等于本次已授权全量导出。

### 3.2 2026-09-14 的证据

| 项目 | 实测结果 | 能证明什么 |
|---|---|---|
| Tushare 2026-09-11 | 5,550 行、5,550 个代码，键不重复，日期一致 | 该样本可读取，不代表未来每日固定 5,550 行 |
| 分页 | 2,000 + 2,000 + 1,550 与整页 18 字段一致；offset=6,000 为空 | offset 分页有效；不能证明发布已经结束 |
| 源耗时 | 整页约 1.016 秒，独立尾页取样约 0.071 秒 | 单次观测，不是 p95 或完整 writer 耗时 |
| 参数样本 | 默认字段/显式 18 字段；对象、单日、区间、无业务参数受限样本；周末为空 | 适合按交易日取增量，不把无日期样本当历史全集 |
| NULL | pe=1,456、pe_ttm=1,633、volume_ratio=6；另有股息率等空值 | 业务字段为空是真实情况，不能全部判错 |
| 额外字段 | 源可返回 `limit_status` | 本期明确不接入，不声称源只有 18 字段 |
| prod 历史 | 14,288,011 行，2010-01-04 至 2026-09-14 | 时点统计；最大日期不等于已完整可导入日期 |
| prod 执行计划 | 日期条件会走并行全表扫描；主键有序取首 10,000 行约 1.827 秒 | 禁止对每个交易日重复扫描历史表 |

证据：`/private/tmp/daily_basic_source_probe_20260914.json`、`/private/tmp/daily_basic_mcp_prod_probe_20260914.json`、`/private/tmp/daily_basic_prod_export_perf_20260914.txt`。MCP 未暴露 limit/offset 的部分使用既有 TushareResource 验证，不能把它写成 MCP 分页实测。临时报告不是正式运行依赖。

## 4. 建议交付对象

| 对象 | 建议名称/职责 |
|---|---|
| Raw asset | `raw_tushare_daily_basic`，18 字段源镜像 |
| 动态分区 | `cn_a_daily_basic_trade_days`，不借用从 2014 年起的共享股票分区 |
| 注册 sensor | `daily_basic_trade_day_sensor`，日历注册，不提交业务 run |
| job | `raw_tushare_daily_basic_update_job`，只选 Raw 和它的两个 check |
| 更新 sensor | `raw_tushare_daily_basic_update_job_sensor`，每 tick 最多一个日期 |
| check 1 | `raw_tushare_daily_basic_file_contract_check`，文件、类型、日期、键 |
| check 2 | `raw_tushare_daily_basic_source_coverage_check`，交付行与约定覆盖证据 |
| 历史工具 | 非 active bootstrap CLI；分开 plan/export/build/audit/report-events |

两个 sensor 默认 STOPPED，正式启用单独批准。不存在新 Silver、prod writer 或新 resource。复用既有 Tushare、只读 ProdPostgres、DuckDB、Lake 路径资源。

正式路径：`/Volumes/datasource/data_lake/raw/tushare/daily_basic/trade_date=<YYYY-MM-DD>/part-000.parquet`。

候选路径：`/Volumes/datasource/data_lake_staging/daily_basic/run_id=<run_id>/trade_date=<YYYY-MM-DD>/part-000.parquet`。禁止在正式 Lake 中建 staging，禁止旧 Lake、Kopia 和自行增加备份流程。

## 5. 数据口径

18 字段顺序与类型详见 LLD §3。键为 `ts_code + trade_date`，目录日期为 ISO，文件日期为 `YYYYMMDD` 字符串。prod DATE 显式转换，不能把日期分区额外写成第 19 列。

保留源端全部行；不以当前活跃股票、退市日、停牌或某个股票池过滤 Raw。不做单位转换、填零、前值填充、财务公式推算、静默去重。PE 等 NULL、负值不因其经济含义被删除。

数值采用 prod 对应 DECIMAL 精度的建议已通过 P0 样本验证，详见 §11；后续仍须在写前检测精度损失，不能先四舍五入再宣称保留原值。新数据超出精度时先修订合同，不静默截断。字段级类型与单位是统一契约，不由日更和历史 writer 分别决定。

## 6. 日更与完整性边界

### 6.1 建议调度

注册建议 17:00 后，更新建议 19:00 后，每 900 秒评估。两者只是最早观察时间，不保证立刻运行。专属交易日缺口先补注册，不能无分区运行。更新限定最近 10 个交易日，选择最早未完成日；历史缺口超出窗口走人工工具。

Tushare 请求为 `trade_date + fields + limit=6000 + offset`，不传 ts_code，短页/空页结束。不能把当前少于 6,000 行固化成永远单次请求。源探测不通过可下个 tick 再查；已经失败的 run 不通过换 run key 无限重试，人工处理。

### 6.2 怎样防止拉到半成品

“源请求成功、没有下一页”只说明请求结束，不说明当天所有股票都发布了。

建议以同日已 ready 的 `raw_tushare_stock_daily` 代码作为必须覆盖的最低集合；daily_basic 额外返回的代码原样保留。例：股票日线有 A/B/C，指标只返回 A/B，则不提交；返回 A/B/C/D，则保留四行，不删 D。

**P0 的七个日期已验证此建议在样本中成立，不是跨数据集永久等价的证明。** 新股、停牌、退市前后样本及两向差集见 §11。这条最低覆盖不能发现“没有日线行情、但理应有指标”的所有遗漏，也不能发现两个源同时漏同一代码，不能对外声称完整性百分之百。若需要更强证明，须找到源端应有集合；不能偷用 prod 每日表或固定昨日数量补成门禁。

探测和 writer 都执行这条门禁，writer 还验证完整 18 字段。生产 check 不联网重拉，不重算 PE/市值等公式；通过本次写入证据及同日输入验证文件。历史导入覆盖与冻结 prod 导出比较，不用今天的股票集合验十多年前数据。

## 7. 历史 bootstrap 与性能

范围建议从 prod 首日 2010-01-04 到离线 plan 冻结的已验证完成日。P0 支持以 2026-09-14 作为本次建议截止，不写成生产常量。该范围日历候选为 4,056 日，不等于 prod 实际日期数。正式文件数量、distinct pair、有效交易日差集仍须后续 plan 冻结。

不能按每个历史交易日查询 prod。建议按主键 keyset 批量导出，每批最多 10,000 行，落外部 staging，再使用 DuckDB 列式转换成按日文件。以 14,288,011 行估计约 1,429 个非空批次，另有终止探测；这是请求规模测算，不是批准立即执行。

首批 10,000 行实测涉及约 8,668 个 shared read buffer，约 67.7 MiB 页面读取；不能拿 1.827 秒简单外推为全程 SLA。P0 必须比较有界 keyset 样本的服务端 IO、传输字节和候选体量。若成本超预算，暂停修订导出方式，不加 prod 索引、不自行开启长事务快照或全表反复扫描。

每批独立只读事务和 checkpoint 不是全表同一时刻快照。最终以已冻结导出为版本输入；若要求与发布时 prod 完全一致，必须在 source 稳定窗口逐批重核，成本计入 plan。来源有变化就停止受影响批次，重做版本，禁止声称天然一致或混拼不同版本。

完整候选通过后逐文件原子提升；已成功分区 checkpoint 可续跑，不承诺多个文件整体原子性。旧目标不一致时停止，不自动覆盖；范围内已有数据通过内容对账后跳过。

历史状态建议：全部已验证文件可以补 materialization 供 UI 展示；check 只补最新 20 个实际交易日，最多 40 条。materialization 数为实际可写分区数，不是行数。状态写入另行批准，旧日期没有 check 不等于没有物理数据，也不等于 ready。

## 8. 人类可读与治理

asset description 说明“按交易日保存股票每日指标原始值”，列说明明确万元、万股、百分比和 NULL。稳定 schema 放 definition，运行 metadata 只放行数、路径、来源、摘要、输入基线 hash、校验与耗时，不放全表。

stdout：开始、源获取结束、校验结束、提升完成；失败说明“哪个日期、哪个阶段、缺多少、下一步做什么”。不输出 token、完整 SQL 或代码全集。

cursor 使用共享 v1 contract，中文 summary/next_action；只保留目标日、原因、阻断组件、计数和最多 3 个样本，普通小于 2KB、硬上限 8KB。禁止报告型 `to_cursor_details()`、完整 readiness 或字段类型列表。

## 9. 分阶段推进与批准边界

| 阶段 | 交付与退出条件 |
|---|---|
| P0 | 验证覆盖口径、全字段精度、历史边界及预算；分别判定P1/P2编码与P3全量准入，不把日更通过等同历史放行 |
| P1 | 按 LLD 实现 contract/path/source/writer/check、fixture 测试 |
| P2 | 实现 asset/job/sensor/catalog/readiness 与治理测试；默认 STOPPED |
| P3 | 历史工具及本地故障/幂等测试；正式只读 plan，单独批准 Lake apply |
| P4 | 文件审计通过后，单独批准分区注册和 materialization/recent-20 checks |
| P5 | 单独批准 definitions 验证、最小日更 run 与 sensor 启用；观察一次自然触发 |

生产验收必须分别列 source 行数、接收行数、拒绝原因、候选行数、正式行数。重复/空键/损失精度不是“正常 reject”，整分区不发布。既有其它数据集不受影响。

## 10. 统一约束与待确认

| ID | 两份文档必须一致的口径 |
|---|---|
| R01 | 股票 daily_basic，严格 18 字段，不接 limit_status 或内部字段 |
| R02 | Raw 保留源行、原单位和 NULL，无业务过滤或公式重算 |
| R03 | 日更 Tushare；prod 只作首次历史导入 |
| R04 | 6000 分页，累计预算，重复/截断失败 |
| R05 | 专属交易日分区、历史范围由 plan 冻结 |
| R06 | 最低代码覆盖建议须 P0 验证，不伪称源完成证明 |
| R07 | 外置 staging、单文件原子提升、幂等续跑、冲突停止 |
| R08 | 两个聚合 check，历史用导出版本而非当前股票池 |
| R09 | 中文观测、紧凑 v1 cursor、schema 属于 definition |
| R10 | 历史 materialization 可全补，checks 最多最近 20 日/40 条 |
| R11 | 热路径最多 10 日；prod 不逐日历史全扫；实测后批准长任务 |
| R12 | 只新增本族；生产执行分阶段批准，无自动部署或写 prod |

Raw-only、两个check、最低覆盖及局限、17:00/19:00调度、10日窗口与2010-01-04分区下限已确认。全字段精度和跨源覆盖样本已补齐；完整bootstrap成本、实际历史截止和状态发布仍须P3以后独立准入，不在P1/P2批准范围。

## 11. P0 执行结果（2026-09-15）

报告目录：`/private/tmp/daily_basic_p0_20260915_070936/`。主报告 `summary.json`，另有 `coverage_summary.csv`、`code_differences.csv`、`boundary_evidence.csv`、`precision_detail.csv`、`prod_report.json`、`performance_estimates.json`。保留9月14日原始证据，未重复全历史统计。

| 日期 | daily_basic 行/代码数 | 同日股票日线代码数 | 缺失/额外 |
|---|---:|---:|---|
| 2026-09-08 | 5,549 | 5,549 | 0 / 0 |
| 2026-09-09 | 5,550 | 5,550 | 0 / 0 |
| 2026-09-10 | 5,549 | 5,549 | 0 / 0 |
| 2026-09-11 | 5,550 | 5,550 | 0 / 0 |
| 2026-09-14 | 5,550 | 5,550 | 0 / 0 |
| 2026-07-29（退市前） | 5,524 | 5,524 | 0 / 0 |
| 2026-07-30（退市日） | 5,528 | 5,528 | 0 / 0 |

- 七日合计 38,800 行；keys-only 与完整字段请求键集合一致；重复、空键、空字符串键、错误日期均为0。
- `301699.SZ` 上市日9月9日已有指标；`920305.BJ` 在7月29日有指标、7月30日退市生效后无指标。9月8日 `600825.SH`、`000016.SZ` 有停牌事实，两类日线均不包含它们。未为这些案例增加过滤或例外。
- 38,800 行源样本及 20,000 行 prod 导出样本均可无损转为18列约定 schema；最大观察小数位4，双向读回差异0。NULL保持NULL，负的ps/ps_ttm也保留。样本验证不是对未来任意数值的保证。
- 本轮14次SDK调用加1次MCP取样，共15次，无重试；串行、请求间隔至少1秒。主样本18字段请求约0.20-1.27秒，keys-only约0.07-0.10秒；不声称p95。
- prod仅两个主键位置：一次EXPLAIN ANALYZE执行10,000行，加两次各10,000行导出，累计业务执行行上限30,000，实际导出20,000行；全部单查询10秒超时。两份非执行计划均为主键Index Scan，无按日全表循环。
- 首位置实际执行约2.96秒，shared read 10,154个页面，约79.3MiB；说明存在明显heap读取放大。客户端两批导出约1.33/4.95秒，首批已受分析查询预热影响。停止进一步取样，不追加第三位置或放大查询。
- 每10,000行审计JSON约3.61-3.63MB，Parquet约0.30-0.31MB。按旧14,288,011行线性测算：单遍31.6-117.8分钟，含一遍来源重核63.2-235.6分钟；还不含年度分流、排序、spill。**这是情景测算，不是执行SLA；历史全量方案不放行。**
- 候选日期4,056；目标目录不存在；最多候选4,056条materialization+40条历史check，实际以P3文件事实为准。正式数据估算约0.70GiB、chunk约0.40-0.42GiB、年度分流另留同量副本；spill与排序峰值未实测。磁盘可用约2.68TiB，空间不是当前主要风险。

开发准入结论：P1/P2 的源行为、字段精度和最低覆盖实现已有样本依据，建议确认相关口径后进入，不自动开工。P3 仍需先收敛导出IO与来源重核成本、冻结实际历史日期/行数和并发来源稳定策略，再评审全量窗口。本轮仅临时文件与两份文档发生写入，无正式Lake/DB/DG状态操作。
