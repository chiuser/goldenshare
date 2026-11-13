# 股票每日指标扩充需求：Prod 与 DG 增加收盘涨跌状态的方案与 LLD

更新时间：2026-11-13。

状态：**§12 两个现有修复已提交 `e393aba66`，§13 的接口验证及当时设计已提交 `adee47129`。简化取舍见 §14，开工前复核见 §15。第一阶段已提交 `9fa2d3d6f`，验收见 §16；第二阶段完整 19 字段日更、严格校验和错误提示已提交 `634a2a1d2`，结果见 §17。第三阶段历史补录已提交 `d4e9a038f`，原始验收与存量检查问题见 §18；取消响应字节限制已提交 `f858a6e70`，见 §19。第三阶段两交易日生产小样基于部署 `4f41388fb`，取消、续跑、幂等与源站核对通过，任务和证据见 §20。三字段补录修订 `341dd7ee1` 已部署，见 §21；Prod 全历史 PLAN `19412` 成功，APPLY `19413` 在完成 2,182/4,093 日后，因 `2018-12-24` 缺少润农节水 `920964.BJ` 的源记录而 failed，已提交日期保留、未重试，见 §22。全历史尚未补完；管理员已确认上市前源缺记录可保留 NULL 的例外，见 §23，已开发并隔离验证，随本次提交保存、尚未部署，补录尚未恢复。DG 第四、第五阶段尚未开发。** 管理员已认可“Prod 只补新增列，DG 从补齐后的 Prod 重新 bootstrap”的方向，并要求新增能力不得影响既有能力。本文不是未批准生产范围的执行授权。

本文是本次扩充的唯一专项主文档，同时承接需求、方案、代码设计、性能依据和后续执行结果。原 [DG 接入方案](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-daily-basic-onboarding-plan-v1.md)及 [DG 接入 LLD](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-daily-basic-onboarding-low-level-design-v1.md)保留原 18 字段实现与历史验收；本专项获评审后，在原文增加本专项入口及适用边界，不复制本次方案或改写旧验收。

## 1. 目标、范围与已确认原则

本次给股票每日指标数据集 `daily_basic` 增加收盘涨跌状态 `limit_status`，补齐现有历史，并使以后的日常同步持续保存该字段。

| 编号 | 硬要求 | 落地位置 | 验收依据 |
|---|---|---|---|
| R01 | 新能力不得改变旧能力 | §5 新 DAO 方法；§6 独立维护动作；§7 bootstrap 显式替换分支 | 旧方法签名、默认行为及调用方不变；原有回归通过；反例证明新方法不会清空旧列 |
| R02 | Prod 原始表、服务表都增加字段 | §4、§5 | 两表均为可空 `INTEGER`，不设 0 默认值，主键不变 |
| R03 | 历史补录只更新 `limit_status` | §5、§6 | 原 18 个业务字段及未指定系统字段保持原值；不增加或删除业务行 |
| R04 | 正常日更使用完整 19 字段；专用历史补录按 §21 只下载代码、日期、状态三列 | §4、§6.1、§7.1、§21 | 日更完整合同不变；补录只校验本次必需字段，不下载或回写原估值等字段 |
| R05 | DG 复用原 bootstrap，从补齐后的 Prod 重建 | §7.2 | 一次正常完整导出；19 字段候选与冻结导出完整一致；不另写 DG 补列主流程 |
| R06 | 正式文件先完整校验，再逐文件原子替换 | §7.3 | 候选审计、旧文件身份、同文件系统、日期锁和逐文件进度均通过 |
| R07 | 新检查只能对应新文件生成记录 | §7.4 | 当前文件校验值、最新物化记录及检查目标的 storage id/run id/timestamp 对应 |
| R08 | 保留旧物化、旧检查历史，不制造全历史绿色状态 | §7.4 | 追加记录；检查范围为已有检查日期与既有近期窗口的并集；其余日期保留未检查语义 |
| R09 | 中断后保留已提交数据并能续跑 | §6.4、§7.5 | 取消、退出、重放、事件部分写入、状态保存失败的测试和真实样本 |
| R10 | 数量、限制和耗时说明有依据 | §8 | 区分本次统计、历史实测、推导和未知项；按管理员决定免除本专项新增测量，保留现有执行限制，不虚构数字或性能保证 |
| R11 | 按阶段取得正式操作批准 | §10 | 开发、Prod 迁移/小样/全量、DG 导出/替换/事件分别有明确范围 |

边界：只处理 `daily_basic`。不增加行情页面功能，不重新计算估值，不将本次字段补齐扩成历史数据纠错，不增加 DG Silver 或 ClickHouse 副本，不清空数据库表、Lake 目录或 Dagster 历史，不新增 worker、队列和系统服务。

2026-11-12 管理员进一步要求：信任已核实的上游调用约束；正常链路已经排除的情况，不在下层反复设防。新增代码只解决字段扩充、旧值保留、已批准的校验、取消/续跑及文件与检查对应问题。不因为绕过入口的人为实验能构造异常，就增加锁、线程、通用恢复机制或发布前置条件。

## 2. 已核实的当前情况

### 2.1 本次只读证据

以下是 2026-11-11 本会话的核验记录，执行前须刷新，不作为永久数量常量。

| 对象 | 已核实结果 | 读取方法及限制 |
|---|---|---|
| Prod `raw_tushare.daily_basic` | 2010-01-04～2026-11-10；4,091 个日期；14,482,741 行 | 只读计数；首日 1,632 行、末日 5,573 行，范围前后计数均为 0 |
| Prod `core_serving.equity_daily_basic` | 日期范围、日期数、总行数及两端日期计数与上述相同 | 独立只读计数；不是全历史逐行对账 |
| Prod 物理结构 | 两表各 18 个业务字段，均没有 `limit_status` | `information_schema.columns` 共返回 41 条字段记录；其余为现有系统字段 |
| Prod 索引 | 原始表只有 `(ts_code, trade_date)` 主键；服务表另有日期前导索引 | `pg_indexes`；禁止据此设计原始表逐日全表扫描 |
| DG 物理文件 | 4,091 个 `part-000.parquet`，范围同上，共 14,482,741 行 | 正式根目录文件清单及只计数查询；未全读业务字段 |
| DG 文件体量 | 771,774,454 字节，约 736.02 MiB | 文件大小之和；不是新候选空间上限或内存需求 |
| DG 单日规模 | 最少 1,341 行、最多 5,602 行；首/末文件为 18 列 | 按文件计数，首尾文件内部 schema；读取时关闭 Hive 分区推断 |
| DG 检查 | 55 个日期，2026-08-18～2026-11-10，共 110 条最新检查，均为 SUCCEEDED | 对本资产两项检查按 500 日期批量读取索引；没有执行检查或写事件 |
| 本地 Alembic head | `20261031_000187` | 解析当前全部迁移依赖；实施前重查，迁移编号现在不预占 |

Prod 之前核对的部署提交为 `d971f60e5b312e1da60ba497b4fad4cac985038a`，相关每日指标读取代码与工作区一致。该提交只说明当时部署情况；正式发版前还须核对实际提交和迁移状态。

### 2.2 DG 层级与来源

DG 仅有 `raw_tushare_daily_basic`，没有本数据集的 Silver。正式路径为：

```text
/Volumes/datasource/data_lake/raw/tushare/daily_basic/trade_date=<YYYY-MM-DD>/part-000.parquet
```

历史 bootstrap 来源为 Prod 原始表；日常增量直接请求 Tushare。资产、日期分区、两项检查由 [daily_basic_contract.py](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/daily_basic_contract.py)、[catalog](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/catalog/lake_assets.py)和 [paths.py](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/paths.py)共同约束，不增加另一套路径或资产名称。

### 2.3 源端证据与覆盖局限

官方接口为 [Tushare 每日指标，doc_id=32](https://tushare.pro/document/2?doc_id=32)。本地 [源资料](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/行情数据/0032_每日指标.md)最初保存于 2026-04-19；第二阶段已在原路径补齐收盘涨跌状态、默认返回说明及更新的公式说明，核验日期为 2026-11-12，`docs_index.csv` 的 doc_id、路径不变。以下保留首次调研证据，本轮新增验证见 §17.4。

| 请求 | 结果 | 能证明的范围 |
|---|---|---|
| `000001.SZ`，20261110，默认字段 | 1 行、18 字段 | 默认不含新增字段 |
| 同代码、同日期，显式完整 19 字段 | 1 行，`limit_status=4`，原 18 字段与默认响应相同 | 新字段可显式获取；不能证明整个历史没有源端修订 |
| 20100104，仅请求代码、日期、状态 | 1,632 行，状态均为 0～6 整数，无缺失和重复键 | 该日源端代码集合与 DG 完全一致 |
| 20261110，同样的三字段抽样 | 5,573 行，状态均为 0～6 整数，无缺失和重复键 | 该日源端代码集合与 DG 完全一致 |
| `000001.SZ`，20151231、20200102 | 各 1 行，状态分别为 4、1 | 跨年代样本可获取；不等于所有日期已验证 |

上述三字段真实证据供 §21 专用补录复用；完整 Tushare 接口及正常日更仍使用 19 字段。管理员在 §21 明确要求只为本次维护动作裁剪下载列，不建立另一个数据集或修改完整接口字段事实。原方案已有对象、日期、区间、分页的历史验证；本次不改时间模型，不重做无日期全市场读取。MCP 没有暴露 limit/offset，其结果不作为项目 connector 分页验收；§13.2 保留原完整 19 字段下载器、分页合并、短页及空末页的历史证据。

## 3. 选择重新 bootstrap 的原因与影响面

DG 补列和重新 bootstrap 都要重写目标 Parquet，也都必须更新文件生成记录及对应检查。选择从 Prod 完整重建，是为了沿用已有单一来源导出、DuckDB 构建和完整字段对账，避免新增“旧文件与单列源数据拼接”的第二条历史主流程。代价是多读一次 Prod 完整历史，必须在 §8、§10 明确批准。

### 3.1 当前代码中的具体限制

| 当前代码 | 已核实行为 | 本次设计 |
|---|---|---|
| `BaseDAO.bulk_upsert` | 冲突时更新全部非主键列；缺少输入的可空列可能写成 NULL | 原方法不改，新增独立的指定列更新方法 |
| `IngestionWriter._write_raw_and_core` | 正常维护将同批行写原始表、服务表 | 正常维护扩到 19 字段；历史补列走独立动作，不改现有 `write_path` 含义 |
| `make_history_plan` | 现有目标文件会阻止直接导入；主键之后的字段都检查为 numeric | 显式批准替换计划；区分现有小数字段与新增整数字段 |
| `_canonical_page`、日更 `consume` | 主键之后的字段统一按 4 位小数处理 | 16 个现有数值字段保持原规则；状态字段单独检查整数与枚举，不能经小数转换后取整 |
| 历史 `audit`、`promote` | 已有文件内容不同就拒绝 | 在显式替换分支验证原 18 字段一致、旧身份未变后允许替换；默认分支继续拒绝异内容 |
| `plan_daily_basic_events`、`apply_daily_basic_events` | 旧物化身份或旧检查不一致即拒绝；仅给最近 20 日补检查 | 为本次批准的替换计划识别“旧记录→新记录”；重检已有检查日期与最近窗口的并集 |

### 3.2 CodeGraph 与直接核验范围

已使用 `codegraph_explore`、`codegraph_impact(BaseDAO.bulk_upsert)`、`codegraph_callers(call_bounded)`。BaseDAO 影响面包括 GenericDAO、股票/指数基础信息、新闻 DAO、多个现行 writer 及对应测试；本次通过新增方法隔离，不能把旧调用方迁移到新方法。`call_bounded` 的现有调用方包括公告、股票周线复权、指数周期线和通用 source client。

DG 已追到原 CLI→导出→构建→审计→提升→事件发布，以及检查→readiness→日更 sensor。CodeGraph 未完整识别字符串注册、SQL 和所有测试关系，已直接阅读实际实现与测试，不能把图中“无测试”当成真实没有测试。

### 3.3 DatasetDefinition 与业务消费者对账

| 消费方 | 本次影响与代码依据 |
|---|---|
| manual actions、catalog、workflow | 现有 `daily_basic.maintain` 的时间、过滤器和自动资格保持原值；只新增专用历史维护动作。依据 `src/ops/action_catalog.py`、`src/ops/catalog/dataset_catalog_views.py` |
| resolver、unit planner、request builder | 继续由 Definition 的 `trade_open_day/every_open_day/point_or_range` 归一化；`_daily_basic_params` 只把日期格式化为 YYYYMMDD；新维护动作不自行拼源参数 |
| source client、normalizer、writer | 请求清单追加字段；增加状态类型/值检查；历史指定列更新不进入旧整行 writer |
| freshness、dataset cards、snapshot、date completeness | 日期轴、observed_field、raw/serving 表名和对象完整性口径不变。新增列的历史完成度由本专项验收，不能仅凭旧日期 freshness 宣称完成 |
| 自动任务日期策略、前端时间控件 | 仍读取既有日期事实；不新增源站过滤参数或变更已有表单默认值 |
| Wealth 市场榜单 | 读取换手率、量比；相关旧字段及接口结果须回归 |
| Wealth 我的自选 | 读取滚动市盈率、市净率、量比、换手率；旧字段及排序须回归 |
| Quote 行情接口 | 读取估值、市值、活跃度及日线换手率；不因为加数据库列就自动向 API 增加字段 |
| 市场情绪验证、行业景气度研究 | 前者仅判断日期存在，后者读取估值/股本/市值；原数据和读取投影保持 |
| DG | 本族日更、schema、历史导入、事件、readiness、sensor、catalog 及测试统一迁到 19 字段；不把名字含 `etf_daily_basic_reference` 的 ETF 基础信息误算为消费者 |

实施前须用当前分支补齐完整消费者清单；只有“日期合同不变”不能免除源字段、DAO、API 与测试核验。

### 3.4 开发模板对照

本文按 [Prod 数据集开发模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)填写本次修改所需的事实与设计，DG 部分对应 [DG 接入模板](/Users/congming/github/goldenshare/lake_console/docs/templates/dagster-dataset-onboarding-template.html)，两端在本文件内交接，不再新建第二份专项正文。

| 模板内容 | 本文位置与当前状态 |
|---|---|
| 0.3.0 源端行为、默认/显式字段、分页 | §2.3、§13.2；完整字段的项目真实 connector 分页验证已通过，范围为单代码有界日期，不代表全历史验收 |
| 0.3.1 时间、unit、freshness | §4.1，三层分别说明 |
| 0.3.2 全部 Definition 消费者 | §3.3；实施前完成当前分支清单核验，不把“预计无影响”当已回归 |
| 0.3.3 字段来源、存储与键 | §4.2、§5.1、§16；模型和迁移文件已完成，正式库尚未迁移，原列维持现行类型 |
| 0.3.4 需求追溯 | R01～R11、§9 测试及 §10 分阶段验收；实现后补最终符号与实际结果 |
| 0.3.5 Prod 长任务 | §6.4；管理员免测决定及未实测边界见 §8.2，功能恢复验收保留 |
| Definition 全部事实组 | §4.3；只列本次允许变化及必须保留的当前值 |
| DAO、迁移、Ingestion、Ops、配置 | §5、§6；DAO 与迁移文件的第一阶段实现见 §16，其余仍为设计 |
| DG 非 Tushare 来源 7A、字段与发布 | §7、§8.3；白名单为 Prod 原始表，全局读取、正式提升和事件仍须分别批准 |
| 测试、性能、发布与恢复 | §8～§10；生产通过记录当前为空，不能预填 |

## 4. 完整字段与数据集事实

### 4.1 时间、执行和审计三层

| 层次 | 当前及本次口径 |
|---|---|
| 时间输入 | 支持单个交易日或日期区间，`ts_code` 保持现有过滤语义；历史补录只接受冻结范围，不增加对象过滤输入 |
| 执行 unit | 正常维护继续由 resolver 生成；专用历史补录按一个交易日构成独立业务提交边界 |
| freshness/audit | 继续按交易日，观测字段为 `trade_date`；补一个新字段不改变旧日期完整性定义 |

基线范围为 2010-01-04～2026-11-10。执行时若日更已产生后续日期，先刷新并冻结新的截止日、日期集合和统计；旧文件、旧事件及检查清单在维护窗口的 audit 中保存，见 §7.7。不能自动把后续日期加入已批准计划。源端更早有数据不构成本次扩展历史起点的理由。

### 4.2 完整业务字段顺序与存储映射

Prod 原始表与服务表使用相同业务列映射。DG 保持源日期字符串。下表中的 1～18 是已有列，19 是本次新增列。

| 顺序 | 字段 | 业务名称 | 源类型 | Prod 类型 | DG Raw 类型 |
|---:|---|---|---|---|---|
| 1 | ts_code | 股票代码 | str | VARCHAR(16) | VARCHAR |
| 2 | trade_date | 交易日期 | str | DATE | VARCHAR，YYYYMMDD |
| 3 | close | 收盘价 | float | NUMERIC(18,4) | DECIMAL(18,4) |
| 4 | turnover_rate | 换手率 | float | NUMERIC(12,4) | DECIMAL(12,4) |
| 5 | turnover_rate_f | 自由流通股换手率 | float | NUMERIC(12,4) | DECIMAL(12,4) |
| 6 | volume_ratio | 量比 | float | NUMERIC(12,4) | DECIMAL(12,4) |
| 7 | pe | 市盈率 | float | NUMERIC(18,4) | DECIMAL(18,4) |
| 8 | pe_ttm | 滚动市盈率 | float | NUMERIC(18,4) | DECIMAL(18,4) |
| 9 | pb | 市净率 | float | NUMERIC(18,4) | DECIMAL(18,4) |
| 10 | ps | 市销率 | float | NUMERIC(18,4) | DECIMAL(18,4) |
| 11 | ps_ttm | 滚动市销率 | float | NUMERIC(18,4) | DECIMAL(18,4) |
| 12 | dv_ratio | 股息率 | float | NUMERIC(12,4) | DECIMAL(12,4) |
| 13 | dv_ttm | 滚动股息率 | float | NUMERIC(12,4) | DECIMAL(12,4) |
| 14 | total_share | 总股本 | float | NUMERIC(20,4) | DECIMAL(20,4) |
| 15 | float_share | 流通股本 | float | NUMERIC(20,4) | DECIMAL(20,4) |
| 16 | free_share | 自由流通股本 | float | NUMERIC(20,4) | DECIMAL(20,4) |
| 17 | total_mv | 总市值 | float | NUMERIC(20,4) | DECIMAL(20,4) |
| 18 | circ_mv | 流通市值 | float | NUMERIC(20,4) | DECIMAL(20,4) |
| 19 | limit_status | 收盘涨跌状态 | int | INTEGER，迁移期可空，无默认值 | INTEGER |

状态的合法值为 0～6：平盘、普通上涨、非一字涨停、一字涨停、普通下跌、非一字跌停、一字跌停。0 是实际业务值，禁止拿它填充未取得的数据。缺列、NULL、非整数、布尔值或范围外值记录具体原因和样本，本次补录不得宣称该日期完成；源端确有 NULL 时先解释其业务含义，不自行改成 0 或放宽验收。

原数字单位、精度和 NULL 原值保持：换手率/股息率保留百分比原值，股本为万股，市值为万元。官网市净率等说明更新只同步资料，不在本次重新计算或重写历史估值。

Tushare 完整业务字段合同不包含 `api_name/fetched_at/raw_payload/created_at/updated_at`。各工程读取自己的字段定义，不跨工程 import。若落成共用契约副本，比较完整解析内容、字段顺序、源类型、说明、输入及分页规则，不只比版本号。

### 4.3 Definition 全部事实组的变更边界

| 事实组 | 当前依据与本次处理 |
|---|---|
| identity / domain / source | `daily_basic`、每日指标、股票行情、Tushare；只追加完整源字段，不创建第二个数据集 |
| date_model / input_model | `trade_open_day/every_open_day/point_or_range/trade_date_or_start_end`，observed_field 为 `trade_date`；保留现有时间和代码过滤定义 |
| storage | `raw_daily_basic → equity_daily_basic`，`raw->serving`，表名见 §2，`raw_core_upsert`；不把普通维护切到新指定列方法 |
| planning | `no_pool`、generic unit、`offset_limit`、每页 6,000；本次不新增股票池或给普通维护增加分页上限 |
| normalization | 原日期、小数字段和必需主键保持；只增加本数据集状态校验，状态不进入 decimal_fields |
| capabilities | 原 `maintain` 支持单点/区间、手动/排程/重试；专用历史动作另行注册，不覆盖这些能力 |
| observability / quality / transaction | 原 observed_field、日期审计和按 unit 提交保持；每日指标校验错误按管理员决定使任务失败并展示原因，其他数据集拒绝策略不变；新动作采用 §6 的严格匹配与独立事务 |
| completeness | 现行日期×股票对象口径，按 `security_serving` 活跃生命周期判断；不因为增加状态列而改变日常应有对象定义 |

## 5. Prod 表结构与新增指定列更新能力

### 5.1 数据库迁移

新增 Alembic 迁移只为以下两表追加 `limit_status INTEGER NULL`，不设默认值、不改主键、不新建索引、不删除或重建表：

```sql
ALTER TABLE raw_tushare.daily_basic ADD COLUMN limit_status INTEGER;
ALTER TABLE core_serving.equity_daily_basic ADD COLUMN limit_status INTEGER;
```

以上是设计示意，不是执行命令。实施前重查真实 head 和 Prod `alembic_version`，`down_revision` 只能接实施时真实 head。先确认锁等待、维护窗口及现有写入；不能因新增列无默认值通常不需重写整表，就承诺它不会等锁。依据 [PostgreSQL ALTER TABLE](https://www.postgresql.org/docs/current/sql-altertable.html)。

同步两个 ORM；`DAOFactory.raw_daily_basic` 仍为现有 GenericDAO，服务表仍为 EquityDailyBasicDAO。模型、完整请求清单和状态校验一起发布，避免新模型遇到旧 18 字段输入后将新增列写成 NULL。

### 5.2 新方法的合同

拟在 `BaseDAO` 新增 `bulk_update_columns(rows, update_columns) -> int`，由原始表 GenericDAO 与服务表 DAO 复用。只增加独立方法，**不改 `bulk_upsert/bulk_insert/bulk_insert_ignore_conflicts` 的签名、默认值、重复键处理和 SQL 行为，不迁移它们的既有调用方。**

新方法约定：

- 主键取当前模型真实主键；输入中包含主键和全部指定更新列。调用方已完成重复键、类型和本次业务值检查，不在 DAO 重复做业务校验。
- `update_columns` 只能是模型中真实的非主键列；不从任意输入字段推导更新范围。本次固定为 `("limit_status",)`。
- 使用参数绑定的 PostgreSQL `UPDATE ... FROM (VALUES ...)`，只匹配现有主键；没有匹配的行不插入。缺键由调用方的独立匹配计数解释，不能当成功跳过。
- 只有指定列的值不同才更新；返回实际变更行数。已相同的行返回 0 也是幂等成功，不用变更行数代替覆盖行数。
- 未指定的业务列和系统列均保持原值，尤其 `updated_at`。采用 `sqlalchemy.text()` 承载参数绑定的更新 SQL；表名、列名只来自当前 ORM 元数据，不接受外部 SQL 标识符。不得用带 `onupdate` 的 `Table.update()` 替代：当前模型编译该写法会附加 `updated_at=now()`。不修改共享模型的 onupdate；测试既断言最终 SQL 只更新指定列，也读回旧业务列和系统列原值。
- 复用既有绑定参数批次计算。每条三值输入为代码、日期、状态，沿用 `sync_batch_size` 的实际配置；不把每个 SQL 批次变成独立业务提交。
- 不 commit、不 rollback、不写 TaskRun，由调用方控制事务。

SQLAlchemy 的多行更新依据见 [UPDATE FROM 与 VALUES](https://docs.sqlalchemy.org/en/20/tutorial/data_update.html#update-from)。具体语句须在既有 PostgreSQL 隔离环境验证；仅 SQLite/mock 测试不能验收 PostgreSQL 更新合同。

### 5.3 单日期业务事务

历史服务读取服务表日期索引下的当日键与状态，再按这些主键匹配原始表。冻结计划已有每日期两表计数，用它证明没有遗漏原始表中的额外行；禁止为每个日期重复扫描原始表。

一个日期内完成：匹配与值检查 → 原始表指定列更新 → 服务表指定列更新 → commit。正常成功路径不在更新后重新读取整日两表数据；提交成功后报告本日已覆盖行数和实际变更量。输入匹配与新方法 SQL 合同已经确定更新对象及值，提交前的回读也不能证明数据已经持久化。读回保留在隔离测试、已完成的 §20 生产小样及中断续跑；按 §21 不在正式全历史补录成功后另加一次全范围核对。任一步失败只回滚这个未提交日期，已经提交的其他日期保留。

补录前的初始 NULL 表示尚未补齐；§23 实现后，满足上市前源缺记录例外的已有 NULL 也允许保留，不能仅据 NULL 断言未处理。源端与已存在非空状态不同，或两表非空状态相互不一致时停止解释，不把本次补齐变成已存在状态的自动纠错。两表均已完整、合法且值相同的日期可按 §6.4 读回判定已完成。新方法本身不限制为 NULL，限制来自本次历史服务。

## 6. Prod 正常同步与历史维护 LLD

### 6.1 正常同步

在 `market_equity.py` 的现有 Definition 追加第 19 个 `source_fields`；日期、过滤器、分页策略、`write_path=raw_core_upsert` 和 `commit_policy=unit` 保持现行含义。新增字段不加入小数字段清单。

当前 `coerce_row()` 只按已有清单把交易日期转为日期对象、把原数值字段转为 Decimal；每日指标当前没有专用 `row_transform`。本次新增的状态检查不计算状态、不取整、不把字符串转成整数、不补 NULL 或 0。完整字段缺失，或状态为 NULL、非原生整数、布尔值、0～6 之外的值，均为校验错误。

管理员已确认：遇到本数据集校验错误，当前任务失败并停止后续日期，不沿用通用 normalizer 的“丢弃坏行后提交其他行”。必须在当前日期写入前完成所有源分页的校验；该日期两张表都不提交，之前已提交日期保留。工作流中的该步骤失败后也停止，不因 `continue_on_error` 继续本次每日指标扩充。此要求仅适用于本次每日指标校验，不改变其他数据集的拒绝策略。

错误在任务详情直接展示交易日、股票代码、股票名称、字段名称、原始值及类型、合法范围和具体原因，由管理员处理后重试。名称从现行股票服务表 `core_serving.security_serving` 按出错代码有界读取；源接口不提供名称，禁止补一个猜测名称。没有可用名称时明确显示“股票名称缺失”并保留代码，不让名称查询错误掩盖原始数值错误。名称是当前服务表名称，不宣称为历史交易日当时名称。例：`2010-01-04，000001.SZ（股票名称：当前服务表名称），收盘涨跌状态 limit_status 原始值 1.5（float），应为 0～6 的整数；该日期未提交，任务失败，等待管理员处理。`

具体接线、reason code、已提交进度及工作流停止规则见 §6.6。它们是后续扩充设计，不属于 §12 已交付的两个修复。

正常链路仍为 `DatasetDefinition → DatasetActionResolver → request builder → source client → normalizer → 原整行 writer`。本次历史动作不会被手动维护、workflow 或 schedule 默认调用。

### 6.2 独立维护入口与配置审计

新增维护动作 `maintenance.fill_daily_basic_limit_status`，中文为“补齐每日指标收盘涨跌状态”。复用既有维护动作 PLAN/APPLY、general worker、TaskRun 详情、取消和重试入口；不改变 `daily_basic.maintain`。第三阶段实现及隔离验证见 §18。

管理员接受该一次性补录占用串行 general worker，人工选择后半夜平峰窗口。保留显式日期范围输入，但不为让出 worker 新增自动分段、抢占调度、worker、队列或服务；不承诺此窗口内其他通用任务同时执行。

| 配置/输入 | 默认、来源和保存位置 | 消费者、生效与限制 |
|---|---|---|
| 新维护动作及 executor key | 代码注册；`src/ops/action_catalog.py` 与 `ops_worker_factory.py`；第三阶段已实现 | 既有维护目录、手动入口、dispatcher；人工可用，schedule 不可用，retry 可用 |
| `execution_mode` | 复用现有 PLAN 默认；请求意图存 TaskRun | PLAN 只读并冻结，APPLY 必须引用原 PLAN id/hash |
| `start_date/end_date` | 必须显式填写；没有自动扩展默认范围；存 PLAN/TaskRun | resolver 按 Definition 归一化，不能从源参数反推日期模型 |
| `plan_task_run_id/plan_hash` | APPLY 必填，复用既有维护重放合同 | dispatcher 验证同一动作、成功冻结及范围；执行时不重新规划 |
| 更新列与目标表 | 代码固定两表与 `limit_status`，并写入冻结计划 | 不提供运营任意字段名、表名或 SQL 输入 |
| SQL 批次 | Settings `sync_batch_size`，代码默认 1,000；运行值必须冻结 | 新方法复用，不能改动旧方法或静默放大运行配置 |
| 分页 | Definition 现有每页 6,000 | 源请求、分页完整性；不是每日永远最多 6,000 行的保证 |
| 本动作 SQL/观察超时 | SQL 20 秒、观察查询 2 秒；沿用现有 Prod TaskRun 长任务相同用途的取值，分别见 `stock_weekly_adj_contracts.py` 的对应参数；在新动作注册配置及 PLAN 中保存 | 单条业务 SQL、独立状态事务；不借用周线行数/内存预算，不改全局连接或旧动作；改值后重启 worker 并重新 PLAN |
| 传输时限、单日期行数/内存与总规模 | 无本次专项实测，按 §8.2 管理员免测决定记录实际参数及来源；不虚构新上限 | 不新增全局配置；本动作按 §19 取消响应字节上限，其他已定边界保留；不声称已测通过 |

新参数不写入新 env 文件或配置表。配置仍由各自现行事实源拥有，TaskRun 只保存此次批准的快照与意图。运营可从计划和详情看到实际值及依据。

### 6.3 PLAN 和来源读取

1. 通过 `DatasetActionResolver` 取得当次范围的日期 unit；使用一次按日期计数的聚合核对两表日期集合、计数和完整性。计划只持有日期、计数及有界描述，不装载全历史业务行。
2. 每日期冻结目标计数，保存本次三列下载投影、主键/存储映射、实际批次配置和 §8 的预算；当前设计的计划合同按 §23.4 升为 v3；§21/§22 的 v2 冻结和执行记录保留。代码版本只用于追溯，不新增代码摘要计算或因无关提交变化拒绝续跑。PLAN 草稿以现有 `TaskRunMaintenancePlanContext` 保存，只有全部审计通过并原子冻结后 `apply_ready=True`。
3. APPLY 先读取该日期两表状态并判定能否跳过；未完成日期按 §21 显式请求 `ts_code,trade_date,limit_status`。源参数仍来自现有 request builder；源范围允许额外代码时须列清并说明本次只匹配已有目标。目标缺失按 §23 的上市前例外处理，其他缺失、重复键或日期不符仍不能提交；本次例外已在本地实现，Prod 尚未部署此修订，仍按原规则停止。
4. 分页只保留单日期的有界输入，禁止积累全历史。按冻结范围和现有分页规则处理；若实施入口要求数值限制，应记录实际取值与代码来源或管理员决定，不能把未实测的数写成测量结论；超出已有限制停止，不临时抬高。
5. 本次历史补录只使用两主键和新增列；原 16 个非主键业务指标不下载、不转换、不回写。正常同步继续使用其完整字段合同。

`TushareSourceConnector.call_bounded` 已有可终止调用；`TushareHttpClient.call_bounded` 和 `bounded_tushare_call.py` 两层的 `daily_basic/v1` 固定绑定 `api_name=daily_basic`，按 §21 支持原完整 19 字段或本维护动作固定三列投影，其他字段组合仍拒绝，不能伪装为指数/公告合同。公告默认分支、`stock_weekly_adj/v1`、`index_period_raw/v1` 继续保持原行为。通用 source client 带 control 的现行分支会指定指数合同，新历史服务不能直接借该分支绕过检查；复用原 request builder、分页规则及底层有界调用，使用本数据集合同。旧三类合同、未知合同拒绝及其错误行为分别回归；失败不得交付或进入正式执行。执行参数见 §6.8，不增加专项测量前置条件。

### 6.4 Prod 长任务合同（对应模板 0.3.5）

| 项目 | 具体设计及验收 |
|---|---|
| unit / 批次 / 内存 | 一个交易日是业务 unit；SQL 子批次按现有参数上限；只驻留一个日期有界数据及日期描述列表；没有本次峰值内存实测，不给峰值保证 |
| 业务持久化 | 两表同一日期在同一独立业务事务提交；不使用全历史长事务，不新增业务表或 checkpoint 表 |
| 幂等键 | 两表均以 `(ts_code, trade_date)` 匹配；只有新增列可变；相同值不重复更新、不插行 |
| 续跑依据 | 引用同一冻结 PLAN；逐日期读回实际业务状态，不能仅信 TaskRun 的 success/行数。两表键/计数与计划一致且新增列完整、合法、相同时可跳过；NULL 日期继续；冲突值停止。前提是本次历史窗口仅由批准的补录写入，日更/其他维护不会改该窗口 |
| 状态写入失败 | commit 后再独立保存 TaskRun/node 进度与结果；状态失败不得回滚业务数据。下一次以两表业务值判定，不因缺少 success 节点而重写旧业务列 |
| 取消 | 每个日期、源分页、SQL 子批次前后检查；取消回滚当前未提交日期，不领取下一日期；源调用可终止，不靠同步 HTTP 结束后的检查冒充可取消 |
| 可见进度 | 阶段、当前日期/页、已完成日期数、总数、百分比、已保存行数和更新时间；不得连续 30 秒没有可见更新。未提交日期只显示处理中，不计入完成量；ETA 不可靠时显示“暂无法估算” |
| 终态 | TaskRun 与活动节点成功/失败/取消一致；已提交进度由修复后的 dispatcher/worker 保留，不能把原通用异常收尾当成已具备该保证；具体修复见 §12 |
| 最小真实验收 | 经单独批准，在代表日期实际运行、取消、续跑、读回；验证两表新增列、旧列原值、业务提交后状态失败以及页面进度，不用 mock 结果代替 |

续跑不是免费：最坏需重新检查全部计划日期的键和新增列；不能按每个日期扫描原始表。按 §8.2 不另做专项耗时测量，但仍记录这一完整检查遍次，不能宣称续跑零成本。若输入已变不能沿用同一 PLAN。

### 6.5 代码位置

| 文件/对象 | 拟改动 |
|---|---|
| `src/foundation/models/raw/raw_daily_basic.py`、`models/core_serving/equity_daily_basic.py` | 增加新列 |
| `alembic/versions/<实施时真实head之后的新迁移>.py` | 两表加可空列；不预猜编号 |
| `src/foundation/dao/base_dao.py` | 只新增 `bulk_update_columns`，旧方法原样保留 |
| `src/foundation/datasets/definitions/market_equity.py` | 完整字段清单与本数据集状态检查声明 |
| `src/foundation/ingestion/row_transforms.py`、`codebook.py` | 本数据集整数状态检查及明确错误原因；不改旧转换行为 |
| `src/foundation/ingestion/executor.py` | 仅为严格拒绝且整行双表写入的组合，在 writer 前终止，并在本次致命校验错误中携带已提交进度 |
| `src/ops/runtime/task_run_dispatcher.py`、`worker.py` | §6.6 的错误展示、正常维护进度保留及工作流整体失败；不能误用 §12 的维护任务修复代替 |
| 新增 `src/foundation/ingestion/daily_basic_limit_status.py` | PLAN 所需事实与单日期补录业务服务；只依赖 Foundation，注入取消/进度接口 |
| `src/foundation/ingestion/daily_basic_limit_status_fields.py` | §21 专用补录固定三列下载清单；完整接口字段事实仍在 Definition |
| `src/foundation/clients/bounded_tushare_call.py` 及对应 client 传递 | 新响应合同分支，旧合同不改 |
| 新增 `src/app/runtime/daily_basic_limit_status_task_executor.py` | 维护协议与 Foundation 服务的组合适配，独立业务 Session |
| `src/ops/action_catalog.py`、`src/app/runtime/ops_worker_factory.py` | 注册新维护动作/执行器；复用现有 dispatcher，不新增 dataset-key 分支 |
| `docs/templates/dataset-development-template.md` | Definition 修改时核对模板合同仍相符；若新事实必须由通用模板表达，实施中同步校准，不复制本专项参数到模板 |

### 6.6 正常维护的校验、任务失败和进度传递

本节依据当前 `DatasetNormalizer.normalize/raise_if_all_rejected`、`DatasetWriter.write`、`IngestionExecutor._process_fetched_unit/_record_unit_exception`、dispatcher 的 dataset action/workflow 分支与 worker 收尾逐项设计。当前 executor 遇到 `IngestionError` 已会回滚当前日期并重新抛出；缺口是“有坏行但仍有好行”没有形成致命错误，以及 Ops 没有保留这个错误对应的已提交进度，不能写成 executor 吞掉异常继续下一个日期。

1. **复用既有策略，不增加全局开关。** 每日指标 Definition 将 `quality.reject_policy` 声明为已有的 `fail_unit_on_any_rejection`，登记专用 `row_transform_name=daily_basic_limit_status`。目前 writer 只对部分 raw-only 路径执行这个策略；仅改 Definition 不会保护每日指标。故在 executor 的 writer 之前增加 `write_path=raw_core_upsert` 且该策略生效的处理。2026-11-11 枚举当前全部 Definition，该组合目前为 0 个；本次只让每日指标进入，其他已有策略的处理位置、错误码和默认行为不改。
2. **逐行样本与整日终止分开。** 转换检查全部 19 个业务字段存在；原数值字段允许现行 NULL/负值，状态必须是原生整数且在 0～6。缺字段使用 `normalize.required_field_missing:<字段>`；新增状态错误为 `normalize.daily_basic_limit_status_invalid:limit_status`，message 区分 NULL、bool、字符串、小数与越界，带原始类型和允许值。延用 `RowTransformReject` 和现有 `reason:field` 拆分；在 codebook 登记基础 reason。不改现有 Decimal、日期转换。
3. **writer 前产生任务级错误。** 上述严格组合的归一化结果只要 `rows_rejected>0`，即在原 `raise_if_all_rejected` 之前抛 `IngestionNormalizeError`，错误码新增 `normalize.source_validation_failed`。details 含 `dataset_key/unit_id/trade_date`、源行数、拒绝数量、reason counts 和 samples；同一组合在 normalize 中直接抛出的日期/重复键等校验错误也统一成该码，保留原错误码和 cause。程序错误、连接错误不伪装成数值错误。当前日期的两表 writer 均不能被调用，后续日期不再领取。
4. **保存真实已提交数量。** `_record_unit_exception` 在 rollback 后，仅为该新错误码向 details 增加 `committed_progress`，取自本次 `_RunState` 的已完成日期数 `unit_done`、累计 fetched/written/committed/rejected 及既有诊断；不假设 state 已保存全部成功 unit id。失败日期的代码、源/拒绝数量放在 `failed_unit`，不混入已提交行数。dispatcher 的 dataset action 分支识别该码，恢复计数并令 outcome 的 `status_reason_code` 为该码；worker 据此为 dataset action/workflow 保留已有进度与异常进度中的较大值。旧 dataset action 失败的收尾不在本次顺带修改。业务 commit 后所有观察写入仍独立，状态失败不能回滚业务数据。
5. **工作流明确失败。** dispatcher 的 workflow 分支识别该新错误码，无论 `failure_policy` 为何都停止后续步骤，工作流及活动节点均为 `failed`；前面成功步骤保持成功。最终总数为前面步骤累计量加本步骤 `committed_progress` 一次，不再把同一份全任务快照重复相加。不能继续使用“已有成功步骤就返回 partial_success”的通用分支。其他错误和其他数据集的 workflow 行为不变。
6. **错误直接可见。** 复用既有 `TaskRunIssue.operator_message/technical_payload` 及详情 API/UI，不新增接口字段。按现有每个 reason 最多 3 个样本、值文本最多 240 字符的规则展示；计数仍覆盖全部拒绝行。用样本代码一次有界查询当前股票名称；缺名称明确标注，名称查询失败也保留原错误。原始值类型写入错误 message，避免日期/Decimal 样本序列化后丢失类型。没有代码的错误显示“股票代码缺失”，不伪造名称。
7. **同一提示覆盖历史补录。** 新历史服务也使用上述 `normalize.source_validation_failed` 和样本结构。`_dispatch_registered_maintenance_action` 对这一错误码复用相同的名称查询与错误展示，把 structured_error 保存到既有 technical_payload，operator_message 直接显示日期、代码、名称、字段、原始值和原因；不能仍只显示“系统维护动作执行失败”。仅处理这一新增错误，其余维护异常维持原行为；不新增维护异常类、接口字段或另一套错误框架。维护任务累计量继续使用 §12 已修复的机制。

验收必须覆盖：先提交日期 A、日期 B 仅一行状态为 1.5、日期 C 未执行；B 两表零提交，A 与其节点数量保留，TaskRun/活动节点失败且详情可见代码、名称、B 日期和原始值。工作流在已有成功步骤、`continue_on_error` 两种条件下仍整体失败。另用其他数据集的部分拒绝及普通工作流失败证明旧策略没有变化。§12 的维护任务回归不能替代这些测试。

上面的数量恢复须区分单位：dataset action 的 unit_done 是日期数；workflow 的 unit_done 是成功步骤数，不能用本步骤已提交的日期数覆盖工作流步骤进度。本步骤的日期进度存节点/诊断，行数才按步骤累计。

### 6.7 新维护适配器如何进入既有 PLAN/APPLY

`daily_basic_limit_status_task_executor.py` 同时实现现有 `TaskRunAwareMaintenancePlanner.plan_for_task_run` 与 `TaskRunAwareMaintenanceExecutor.execute_unit_for_task_run`；注册动作的 `execution_config.plan_apply_replay=True`，只允许人工 PLAN/APPLY。不能只实现普通 `plan/execute_unit`：那样 dispatcher 不会注入 TaskRun 的取消/进度上下文。新动作的普通无上下文方法明确拒绝执行，不提供绕过 PLAN 的入口；既有动作不改。

| 阶段 | 输入、持久化及调用规则 |
|---|---|
| PLAN | 注入 `TaskRunMaintenancePlanContext`，调用现有 resolver 生成日期。按日期聚合核对两表数量，逐批保存日期描述草稿、阶段和进度；每批前后检查取消。描述不含全历史股票明细。只有完整校验后冻结既有 schema_version=1 的维护 snapshot、hash 和 apply_ready，取消/失败草稿不可 APPLY |
| 冻结 metadata | `contract_kind=daily_basic_limit_status/v3`、§23.4 的缺失处理规则及上市日期来源、dataset/action、显式起止、日期集合、每日期两表计数、固定两表/键/列、三列下载清单、实际 `sync_batch_size`、§6.8 控制参数与来源；代码版本作追溯。不升级共享 snapshot 格式或改变其他动作重放 |
| APPLY | dispatcher 已用 `_load_replay_apply_units` 校验动作、hash、范围和成功冻结，适配器直接消费这些已验证 unit，按下文读取原 PLAN 的冻结配置，不再做一套相同校验或代码版本对比。不得重新解析出更多日期或静默换字段 |
| 单日期 | 接受 `MaintenanceTaskRunContext.task_run_id/run_context`；适配器按下述方式接出取消/进度，Foundation 只接收接口，不 import Ops。业务使用独立 Session；源读取完成后才开始该日期双表事务，状态 Session 不参与业务事务 |
| 返回 | unit 返回现有 `MaintenanceExecutionResult`：正常执行在 commit 成功后报告已核对的覆盖量与实际变更量，不增加整日回读；恢复时按两表实际状态判定已完成，再报告覆盖量。不能用 UPDATE 返回 0 推断没有完成 |
| 取消/失败 | replay 分支当前没有替 executor 自动覆盖 unit 内取消，新适配器必须在每日期和每页/SQL 子批次前后检查。已有 §12 修复负责保存已返回 unit 累计；当前 unit 内分批观察不等于已提交。进程退出、commit 回执不明时按 §6.8 读回 |

**冻结配置传递。** 当前 `_load_replay_apply_units` 只返回日期 unit，不会把 snapshot 的 `metadata` 注入 `MaintenanceTaskRunContext`；`bulk_update_columns` 则直接读取 DAO 的 `settings.sync_batch_size`。因此，在新适配器每个日期的入口，用注入的 Session factory 创建独立读取 Session，通过 `context.task_run_id` 取得当前 APPLY 的维护参数、累计量及活动节点 id，再按其中的 `plan_task_run_id` 读取原 PLAN 所需的冻结配置及 contract_kind。按 §23.4 检查为包含本次例外的 v3 计划，旧 v1/v2 明确要求重新 PLAN。只投影本日需要的 TaskRun 字段、冻结配置和版本，不反复读取完整计划；不扩充共享上下文或重放协议，也不重复 dispatcher 已完成的校验。

适配器把冻结的源请求与 SQL 控制参数传给 Foundation 补录服务，观察超时由适配器自身使用。两表各创建本次补录专用 DAO，用独立 Settings 副本承接冻结的 `sync_batch_size`，不修改 `get_settings()` 返回的共享对象，不改变 DAO 构造器、旧方法或其他动作。服务和 DAO 使用同一冻结值及既有绑定参数上限计算批次，使 §6.8 的每次 DAO 调用最多执行一条更新 SQL；PLAN 后当前配置升高或降低，都不能改变本次 APPLY 或原 PLAN 重试的批次。

**进度累计。** 每日期入口读到的本次 APPLY 已完成日期数及累计行数，是本日显示进度的固定起点，不在每次回调时读取更新后的累计值再相加。适配器在当前执行线程的请求等待回调和 SQL 批次前后报告进度，不新增观察线程。取消读取复用 `TaskRunIngestionContext(independent_cancel=True, timeout_seconds=2)` 的独立查询；2 秒沿用同一 TaskRun 策略的 observation_timeout_seconds。私有进度方法用独立事务更新阶段、当前日期/页和更新时间，设置同样的局部观察超时；处理中不改已完成日期数、累计已保存量或当前日期节点的保存量。当前 `TaskRunIngestionContext.update_progress` 会把全任务合计复制给当前节点，本动作不直接调用它，不改变其既有行为。

未提交日期节点保存量保持为 0；业务 commit 确认成功后直接返回本日 `MaintenanceExecutionResult`，由现有 dispatcher 累加一次并保存 TaskRun 合计与节点本日数量，适配器不再另行累加。观察写入异常不抛进业务事务；已确认提交的 unit 先返回结果，由 dispatcher 保留累计，再在下一日期开始前处理取消。原 PLAN 重试创建新的 APPLY TaskRun，其累计量从新任务开始；逐日期按两表实际状态判断是否跳过，已完成日期按 §6.4 返回覆盖量，不把上次 APPLY 的累计量带入后再重复累计。

上述当前 APPLY 字段与原 PLAN 冻结配置每日期各读取一次，正常执行和续跑均计入这一开销；回调复用本日已读值，不为计算累计进度增加业务数据回读。开发验收补充：PLAN 后调高、调低当前批次配置，新动作仍使用冻结批次且每次 DAO 调用只有一条更新 SQL，共享 Settings 和旧方法行为不变；同一日期多次回调、连续日期提交及原 PLAN 重试时，TaskRun 合计和日期节点数量均不重复累计，未提交日期不增加已保存量。既有取消、提交后状态写失败和业务读回验收继续适用。

### 6.8 复用现有取消、超时和日期续跑

按现有 Prod 长任务做法，在当前执行线程检查取消并报告进度。保留每日期独立提交、源请求可终止和 SQL 子批次前后检查；不新增 SQL 取消线程、连接登记表、操作序号、跨线程关闭连接或针对 COMMIT 的自动修复流程。

- **源请求：** 新动作使用 §6.3 的 `daily_basic/v1` 有界调用，复用现有等待循环的 check/tick、最多 0.2 秒接收轮询及子进程清理。源请求等待期间按已有 5 秒进度间隔报告阶段、日期和页数；取消后不再重试或请求下一页。此处只接入已有能力，不再包装一层线程或子进程。源调用截止沿用当前 HTTP 客户端 30 秒接收取值，用作本次有界调用总截止；这是执行取值，不是耗时测量或完整任务期限。
- **业务 SQL：** 维护服务按已有绑定参数计算得到的有效批次，逐批调用 `bulk_update_columns`；每次调用最多执行一条更新 SQL，DAO 不增加取消参数。每次查询、更新和提交前后检查取消并报告当前步骤。业务事务使用局部 `statement_timeout=20s`，沿用现有 `stock_weekly_adj_execution.py` 设置局部 SQL 超时和检查执行边界的做法，不 import 周线的业务 policy 或错误类，不改全局连接。正在执行的 SQL 等其返回或超时，再取消并回滚当前未提交日期；不承诺点击后立即打断数据库语句。
- **进度：** 取消查询和状态事务各沿用 2 秒观察超时；正常源等待由既有 tick 报进度，SQL 20 秒边界加上述观察步骤用于满足根规则的 30 秒可见更新要求。它们是相同 TaskRun 交互场景已有取值，不是性能实测。数据库/网络不可用仍按现有任务错误处理，不为极端断连新增监控服务或恢复框架。
- **正常取消：** 提交前发现取消就回滚当前日期；提交已经开始时不主动取消 COMMIT，先处理其返回结果。成功提交的日期保留并返回 unit 结果，随后停止；不领取下一日期。
- **提交异常：** commit 报错或连接中断时，本次任务停止，提示“当前日期提交结果未确认，确认原任务已结束后按原 PLAN 重试”；不立即在另一连接看到旧值就认定已回滚，也不自动重写该日期。管理员确认原执行已结束后，仍使用 §6.4 原有的两表键、计数与状态读回续跑：已完整一致则跳过，待补则处理，冲突则解释。无需新增事务状态表、后台确认循环或另一种恢复入口。
- **内存与参数：** 只保留当前日期数据；按冻结目标计数核对键与状态，缺少、重复或日期不符不能提交。每页保持 6,000，最多页数为 `floor(目标计数/6000)+1`，包含整页后的空终止页。按 §19 取消本动作的 `max_response_bytes` 配置、必填判断与实际响应字节拦截；不新增替代上限、配置页面或测量任务，不对单页字节数及峰值内存给出保证。其他数据集的字节限制不变。

依据是当前 `bounded_tushare_call.py` 的等待循环、`stock_weekly_adj_execution.py` 的局部超时/边界检查，以及 `TaskRunIngestionContext` 的独立观察事务；[PostgreSQL statement_timeout](https://www.postgresql.org/docs/current/runtime-config-client.html#GUC-STATEMENT-TIMEOUT)只限制数据库语句，不能证明断连后的提交结果。必要测试覆盖请求中取消、SQL 等锁超时后取消、日期提交后取消、原 PLAN 续跑、提交异常停止、观察失败不撤销业务；删除仅服务于新取消线程的竞争和连接池测试。

## 7. DG 新结构与重新 bootstrap LLD

本次按一次性维护执行：候选可以提前在 staging 准备；正式审计、替换和事件发布期间，暂停 `raw_tushare_daily_basic_update_job_sensor`，等待本资产相关排队、执行中及检查任务结束，不再手动触发本族作业。bootstrap 依次执行，不并行启动 promote 与 report-events。事件写入统一走现行 history CLI；其 `_event_apply_lock` 排除第二个 CLI 发布者，`_idle` 保留现有活动任务检查，日期锁继续保护文件写入。这里不要求停止其他资产或 DG 整体服务。

以上是本次维护的执行边界。正常日更已退出、正式事件入口被串行化时，不会再有另一个受支持的发布者插入同资产事件。因此不增加逐日期最新身份查询、第二把全局锁、反复检查所有任务或防止任意脚本直接写 Dagster 的代码。违反维护边界后不能继续沿用旧批准；这不等于本方案承诺现有锁能够禁止所有外部事件写入。

### 7.1 19 字段正常日更

在 `DAILY_BASIC_COLUMN_SPECS` 末尾追加整数状态；派生 schema、catalog、asset definition metadata、检查说明和测试同步。日更与历史转换都只对原 16 个数值字段调用小数处理，对状态检查原始整数；不能因 DuckDB 能把小数 CAST 为整数就接受错误值。

日更的最近 10 日期窗口、17:00 注册/19:00 更新观察时刻、900 秒间隔，以及原 1 秒请求间隔、12 次请求/3 次重试、60 秒接收截止的本族规则保持原定义。这些是已存在规则，不是本次新增预算；60 秒仍不等于 SDK 保证在 60 秒内结束。新结构切换期间不得启动本族日更去读取混合 schema。

### 7.2 一次正常导出与候选构建

Prod 新增列验收完成并确认冻结范围稳定后，沿用 `daily_basic_history_cli` 的 `plan/export/build/audit/promote` 及事件阶段。新增显式 `--replace-existing`，默认 false：

- false：原导入路径的默认行为和异内容拒绝规则不变；旧 18 字段报表不能作为新结构执行输入。
- true：只允许在新的完整计划中记录批准的 18→19 字段替换意图；计划冻结来源、旧字段投影、日期和预算。候选完成并进入上述维护窗口后，才在审计报告冻结候选、旧文件校验值和旧事件身份；不在长时间准备候选之前冻结可能被正常日更更新的旧事件，也不回写已封存计划。

来源只允许 `raw_tushare.daily_basic` 完整 19 业务字段，日期显式转为 YYYYMMDD。使用现有 `(ts_code, trade_date)` 主键分页，每批最多 10,000 行，每批独立只读事务，不按历史日期反复查询原始表，不使用 OFFSET 扫历史。必须复查 EXPLAIN，无排序或顺序扫描放大才放行。

正常完成只导出一遍，并以冻结导出为后续输入；中断仍沿用原工具的已落盘前缀重核，再继续，不因为换入口放弃这一已确认修正。导出依赖管理员确认的来源稳定窗口，不宣称短事务构成整个历史的一致性快照。

候选与中间产物仅位于 `/Volumes/datasource/data_lake_staging`，继续由 DuckDB 按年度分流、按日期生成每日期一个 `part-000.parquet`。不得将第 19 个字段当作目录分区推断出来的字段，所有内部字段检查关闭 Hive partition inference。

### 7.3 审计与受控替换

候选全部完成以下核验后才允许开始正式替换：

1. 19 字段名称、顺序和类型，日期/文件归属、主键唯一、源状态合法性，以及来源导出与候选的完整 19 字段双向对账。
2. 候选的前 18 字段与原 DG 文件做双向对账，键及每日期行数一致；差异停止解释，不能以“Prod 是新来源”为由顺带改旧数据。
3. 按本节维护边界确认日更/检查已退出，取得当时的旧文件校验值、旧物化/检查 id，与候选清单一同保存到批准的 audit 报告；后续阶段引用这份报告。

`make_history_plan`、`audit_daily_basic_history`、`promote_daily_basic_history` 都须识别显式替换计划，不能只删除 `history_target_conflict` 检查。提升继续使用本族日期锁、同文件系统确认及逐文件 `os.replace()`。目标为 audit 中的旧文件时替换，为本批新文件时跳过；其他内容沿用目标冲突停止。这是正常替换/续跑所需判断，不新增通用并发恢复能力。

保留原候选供重核，不创建旧文件备份、不运行 Kopia。每次成功替换保存日期、旧/新校验值及当前阶段；确认目标已是新文件后续跑不再复制。跨全部日期不具有一次原子性，维护窗口内不能承诺全部日期同时切换。

### 7.4 文件生成记录与检查事件

设 `D` 为冻结替换日期集合，`C` 为这些日期中已有本资产任一检查记录的日期，`W` 为原规则要求的最近 20 个实际交易日。新检查范围 `K = C ∪ W`，且均属于 `D`；不能自动扩到其他日期。

本次审计时 `|D|=4,091`、`|C|=55`，`W` 已包含在 `C`，因此预计追加 4,091 条新物化记录及 110 条检查结果，共 4,201 条。执行前重算；这些数是清单推导，不是授权或永久写入上限。

事件处理规则：

- 替换前冻结候选与旧文件校验值、旧物化/检查 id、`D/K` 和允许追加的记录范围，作为替换批准依据；此时不调用要求全部文件已提升的现行 `plan_daily_basic_events` 冒充替换前计划。
- 文件提升后，才依据已批准范围、审计报告、提升报告及当前实例生成新鲜事件执行清单，供现有 PLAN/APPLY 使用。清单重新生成不扩大原批准范围、不覆盖原始旧身份，也不重新导出 Prod。
- 不删除、改写旧事件，不复用旧成功检查证明新文件已检查。旧成功结果继续表示旧文件当时的结果。
- 对每个新文件追加同一 asset key、同一 partition 的物化记录，记录路径、19 字段观察结果、行数、新文件校验值和本次 plan/export/audit 身份。继续明确来源为 Prod 历史，不伪装为自然日更。
- 对 `K` 中每个日期实际调用现行两项校验逻辑，验证新文件的 schema、日期、键及新交付身份；只有实际通过才写 passed。不能只见候选报告写了 passed，就无条件填入绿色结果。
- 每条新检查明确绑定该日期新物化记录的 `storage_id/run_id/timestamp`，`partition` 明确为该交易日；两项检查均为现行 blocking/ERROR 语义。
- 当前 `plan_daily_basic_events` 的旧身份冲突不再一概当错误：旧 id/旧文件对应批准 audit 时允许登记本次新记录；本批记录沿用 `_history_evidence` 识别，其他冲突保留原拒绝行为。该判断用于区分尚未处理和中断后已处理的日期，不实现额外的实时事件监视。
- 当前 `apply_daily_basic_events` 的“已有检查就跳过”必须细分：已绑定本次新物化且内容身份一致则跳过；绑定批准旧物化则需重检并追加；其他目标停止。
- 非 `K` 日期追加文件生成记录，但不制造检查成功。readiness 仍要求当前文件、最新物化及目标一致的检查全部满足；历史 materialized 不等于全历史 ready。

沿用 §12 已实现的日期锁与读回：物化阶段使用现有批量读取的身份，在日期锁内核对文件并登记，随后批量读回；检查阶段在日期锁内确认新物化并绑定检查目标。日期锁路径仍为 `<staging_root>/daily_basic/locks/<trade_date>.lock`，一次只持一把、非阻塞取得，外层 CLI/工作目录锁顺序不变。此次字段扩充不增加新锁或锁内逐日期物化查询。结合本节维护边界即可满足本次操作，不把对任意外部写入的抵御作为开发目标。

通过 `DagsterInstance.report_runless_asset_event` 写入，不用 SQL 改 Dagster 内部表。新增记录的基础能力见 [Dagster 外部事件 API](https://docs.dagster.io/api/dagster/external-assets-instance-api)；具体检查目标合同以当前安装版本和已存在 `AssetCheckEvaluationTargetMaterializationData` 实现及测试为准，不从无目标的官方简例推断本工程可省略绑定。

### 7.5 DG 中断后如何继续

| 实际文件和记录 | 续跑动作 |
|---|---|
| 旧文件、批准的旧事件 | 尚未替换；验证候选与旧身份后再提升 |
| 新文件、仍为批准的旧事件 | 不重写文件；补本次新物化，再处理需要的检查 |
| 新文件、本次新物化、检查仍指旧物化或缺失 | 不重复物化；执行并登记缺少的本次检查 |
| 新文件、本次新物化、两项检查均绑定新物化且通过 | 核对身份后跳过，幂等完成 |
| 新文件、本次新检查失败 | 保留失败现场，停止并解释；不追加一条绿色记录掩盖失败 |
| 文件校验值或事件 id 不属于批准的旧/本批次新状态 | 判定存在计划外变化，停止，不覆盖 |

物理文件替换和事件数据库写入不是一个事务。失败只能从实际文件和记录恢复；不能把所有失败都当成重新复制全量文件，也不能只信本地进度文件。每批次开始前刷新有关 id；写后读回，source/file/event 的身份不一致时保持不可用，完成验收后才恢复日更。

续跑必须重新生成事件执行清单：原始替换批准的范围与旧身份保持不变；逐日期将实际文件和事件分类为批准旧状态、本批次新状态或计划外状态；前两类据上表计算剩余项，第三类停止。用本批次 plan/export/audit 身份和新文件校验值确认新物化归属；新检查还须绑定该物化三个身份字段并实际通过。部分写入使原 `state_fingerprint` 改变属于预期，不能直接拿原清单再次 APPLY，也不能删除 stale 检查。只写新物化、只写一项新检查时，重新规划后仅追加缺少项。当前原始导入已有重新规划续跑测试；18→19 替换的状态分类和清单仍是后续待开发能力。

替换分支的小样至少覆盖三种已有事实：最早历史日（没有旧检查）、`C` 中但不在最近窗口的日期、最近窗口中的日期。按本次基线可分别选 2010-01-04、2026-08-18、2026-11-10，执行前重核。原 CLI 的事件阶段 `--sample-date` 只允许最近窗口；仅在显式替换计划中放开到批准日期集合，并让 promote 支持该选择，按该日是否属于 `K` 决定是否登记检查。必须先完成全候选审计，但不必先提升全部日期；具体见 §7.7。普通首次导入仍保留原限制。

### 7.6 DG 修改位置

| 文件 | 拟改动 |
|---|---|
| `defs/daily_basic_contract.py` | 第 19 字段与整数/小数分离事实 |
| `defs/daily_basic_raw_io.py` | 日更整数处理及新增列校验；原小数精度规则保留 |
| `defs/run_contracts/asset_column_schemas.py`、`catalog/lake_assets.py`、`assets/daily_basic.py` | 派生 19 字段 schema、说明和观察结果 |
| `defs/source_readiness/daily_basic.py`、`checks/daily_basic_checks.py`、`asset_guards/daily_basic_readiness.py` | 完整字段写入/检查与新交付身份一致，原近期窗口不扩大 |
| `defs/prod_db/daily_basic.py` | 完整 19 字段投影，保留主键分页、原生 DATE 条件和显式原表排序 |
| `defs/bootstrap/daily_basic_history.py` | numeric/integer 类型核验、状态规范化、现有目标审计与显式替换 |
| `defs/bootstrap/daily_basic_history_cli.py` | 新替换意图参数、冻结计划及阶段传递，原参数默认行为不变 |
| `defs/bootstrap/daily_basic_events.py` | 冻结旧/新身份、`K` 清单、追加物化和目标正确的新检查、部分成功续跑 |

### 7.7 替换报告、旧新身份和小样执行的具体合同

沿用现有报告及 fingerprint 算法，plan 的 schema_version 仍为 1；只增加本次替换所需内容，不另建第二套报告版本。plan 的 `replace_existing` 缺省为 false，只有显式 `--replace-existing` 才为 true；该标志不赋予任意覆盖能力。旧 18 字段报告仍不能作为新 19 字段执行输入，正常首次导入的行为不变。

| 文件/报告 | 必需字段及冻结时点 |
|---|---|
| `plan.json` | 保留现有来源、日期、限制、calendar SHA、source/cost evidence，增加 `replace_existing`。日期集合 D、完整字段和允许的原 18 列比较投影固定；不提前保存尚未生成的候选或维护前还会变化的事件身份。旧 18 列清单仅作迁移比较，不形成源字段子契约 |
| `export.json/build.json` | 继续绑定同一个 plan fingerprint；导出批次、前缀重核和候选路径沿用现有合同，不增设状态文件 |
| `audit.json` | 全部 D 候选审计完成后封存，绑定 plan/export/build fingerprint。保留现有 `files[].date/path/sha256/rows`；替换时每项增加 `old_sha256`，表示已经比较通过的旧文件。`replacement` 中保存维护窗口内按现行批查询取得的 `materialization_ids/check_ids/check_dates`；前两项分别为日期到旧物化 storage id、日期与检查名到旧检查 event storage id 的映射，check_dates 为 K。已有 ID 唯一标识记录，不重复保存旧 run id、timestamp 或单独 schema hash |
| `promote.json` | 沿用 `files[]` 累计已确认的新目标日期和 SHA。替换续跑时按 audit 与实际目标重核后合并，不每次清空；不再增加一份 completed_dates。文件已替换但进度未保存时，可按批准的新 SHA 补回现有列表 |
| 事件执行清单 | 沿用现有 files、materialization_ids、check_ids、pending_materializations、pending_checks 和 state_fingerprint。files 表示本次选择；替换分支的 check_dates 从 audit 的 K 取交集。已有 plan/export/audit fingerprint 和文件 SHA 识别本次新记录；promote fingerprint 只用于当前清单新鲜度，不进入固定物化归属 |

**旧身份在替换前审计保存。** 先完成候选，再进入维护窗口并按现行检查规则核对旧文件与旧事件，得到 K；不为每条旧记录增加重复字段。已有失败、运行中或目标不一致的检查仍按原行为停止。审计封存后保持不变；中断后引用它，不重新导出来源，也不缩小 K。

**剩余工作用已有事实判断。** 文件是 audit 旧 SHA 就待替换，是新 SHA 就已替换；物化是 audit 保存的旧 ID 就待追加，与现有 `_history_evidence(plan,audit,item)` 完整相同就已追加。该函数实际使用 `trade_date`，不新增或误用 `date` 元数据键。检查仍指旧物化就重检，成功且指向本次新物化就跳过；新检查继续从当前物化取 storage_id/run_id/timestamp 作为目标。无旧记录就正常新增；其他内容按现有冲突处理。这里复用现有批量读取与 §7.4 日期锁，不加逐日期并发探测。

**中断沿用现有重新规划。** 物化或检查写出一部分后 state_fingerprint 改变，重新生成事件清单，只列剩余项。可以同时存在待处理的旧检查和本次已完成检查，不能因此重复物化。检查失败仍保留现场并停止，不追加绿色记录掩盖。文件进度仍以现有 promote.files 与实际 SHA 对账，不维护第二份日期状态。

现行 promote 会再次调用 audit；本次显式替换分支不继承这次全历史重跑。首次 audit 已完整验证来源、全部候选与原 18 列并封存文件校验值；promote 只校验批准报告及 plan/export/build 引用，按本次选择逐文件核对候选新 SHA 和目标旧/新 SHA。目标是批准旧 SHA 就提升，是新 SHA 就跳过，其他内容按现有目标冲突停止；沿用复制后校验、同文件系统原子替换和现有进度保存。不再全读冻结导出、重新比较原 18 列或重建 DuckDB 审计关系，也不改批准 audit 的 fingerprint。普通首次导入继续执行原有审计流程。

**小样无需先替换全部文件：**

1. 对全部 D 完成候选审计，批准固定 audit 报告。`--replace-existing` 只在 plan 阶段写入；后续不能临时打开覆盖。promote 仍用原 `--fingerprint` 校验 plan fingerprint，并读取现有 `--audit-report` 指定的批准报告，不改变同一个参数在文件阶段的含义。
2. 仅替换分支让 promote 支持已有 `--sample-date`：选一天或默认全部 D。事件规划直接使用 promote.files 中已确认提升的日期，audit 仍覆盖全部 D，不要求小样前先提升全部日期；plan-events 不增加样本参数。普通导入的前提与参数限制不变。
3. 依次处理 §7.5 三类日期：该日期 promote→plan-events→report-events→audit-events。第一次 promote.files 只有一个样本日，后续累计已提升样本；重新规划只列未完成事件，原 report-events 的 sample-date 如有填写仍用于选择该日。audit-events 按现有清单确认已提升日期，不增加样本参数。无旧检查且不在 K 的样本只新增物化；其他两个样本各实际运行两项检查。按现有基线推导为 3 个文件和 `1+3+3=7` 条事件，不是固定上限，执行前核对各日期归属。小样以外旧文件和事件尚不改动。
4. 小样通过后提升剩余日期，再为剩余日期生成事件清单；样本的新物化始终绑定同一个 plan/export/audit，后续 promote 追加进度不会令其变成外部记录。中断后同样按物理事实计算 remaining，不生成一个换了父 fingerprint 的小样子计划。

plan-events、audit-events 保留原参数合同，不接收 sample-date；其范围来自当前 promote.files，已经完成的样本由现有 pending 清单排除。report-events 保留已有样本选择能力，仅在替换分支允许选择已提升的历史样本日。事件 APPLY 沿用现有 fingerprint 校验；register 仅登记当前清单所需分区。最后验收要求实际已提升日期等于 D、K 的检查全部对应当前新物化。

读取成本为首次完整候选审计，加每次替换提升所选文件的校验值核对；不因小样或续跑再全读来源和全部候选内容。事件 PLAN/APPLY 沿用现有清单与文件核验，最终验收仍覆盖 D/K。测试须证明首次完整审计保留、候选变化仍拒绝、替换提升不重调全历史 audit、只读事件命令不扩参数、小样和部分文件/事件能续跑；不追加性能测量。

## 8. 性能与读取预算

### 8.1 已有依据与可复算规模

| 项目 | 数字与计算 | 性质、适用条件 |
|---|---|---|
| Prod 历史补齐 | 每表 14,482,741 行；两表首次全补最多涉及 `14,482,741 × 2 = 28,965,482` 行更新 | 本次计数推导；已相同行不重复更新，源缺口会阻止完成 |
| Prod 正常更新后的整日回读 | 0 次；保留更新前的键/状态匹配，正常 commit 成功即返回 | §5.3 的执行步骤；隔离测试、最终验收与续跑读回另外计算，不是删除这些验证 |
| Tushare 请求 | 若所有日期仍与目前单日计数一致且每页 6,000 行，4,091 个日期各一短页，约 4,091 次请求 | 条件估算；原 DG 单日最大 5,602 行；源变化、整页终止探测和重试另计 |
| DG Prod 导出 | `ceil(14,482,741 / 10,000) = 1,449` 个非空批次，现有工具另需 1 个空终止页，即 1,450 次业务页查询 | 不含 schema/index/EXPLAIN 检查；每批 10,000 来自现行合同 |
| DG 正式文件 | 4,091 个待重建文件，原文件 771,774,454 字节 | 当前文件事实；不能以 18 列体量直接承诺 19 列大小 |
| DG 状态发布 | `4,091 + 55 × 2 = 4,201` 条 | 当前 `D/K` 推导；刷新后按清单计算 |
| DG 索引读取 | 500 日期一批，`ceil(4,091/500)=9` 个日期批次 | 沿用原代码；物化分页另计，已有 20,000 条返回限制保持，超限先审计而非静默扩大 |
| DG 本次替换的完整内容审计 | 全部候选首次审计 1 次；后续每次 promote 不再执行全历史内容比较，仅核对所选文件校验值 | §7.7 的执行步骤；样本、续跑与最终验收仍有文件校验值读取；普通导入不变 |

历史参考：原 LLD 记录 2026-09-15 的 18 字段导出 14,288,011 行，实测 2,427.37 秒；按日候选 761,591,306 字节；本地审计函数 17.54 秒，峰值 RSS 约 5.14 GiB。这些记录保留原范围和类型，不能照搬为本次 19 字段 SLA 或预算，原方案的倍率/余量也不沿用。

### 8.2 管理员决定不另做专项性能测量

2026-11-11 管理员明确决定：本专项不再安排额外性能测量，不以测量未完成阻止修复或后续开发；全历史补录由管理员人工安排后半夜平峰窗口。这是管理员接受未知耗时的执行选择，不是“小数据已实测通过”、耗时承诺或对全仓性能治理的修改。功能校验、取消/恢复和数据一致性测试照常保留；本轮只开发 §12 两项修复，不执行全量正式任务。

| 未实测项目 | 本次处理 | 保留的边界 |
|---|---|---|
| 指定列更新耗时、数据库日志/空间 | 不追加专项基准测试 | 正式写入仍需批准；同日两表事务、旧列不变仍须正确性验收 |
| 新响应字节、取消耗时、峰值内存 | 未实测，不写保证值 | 保留源分页、单日期内存与可终止调用设计；参数须记录现行来源或管理员决定 |
| Prod 续跑成本 | 已完成日期仍可能全部读回一遍 | 不把逐日主键匹配改成逐日扫描整个原始表，不宣称零成本 |
| 19 字段磁盘与 DuckDB 峰值 | 记录阶段内同时存在的导出、年度中间、候选与提升副本 | 不自造磁盘余量或扩大现行资源配置；正式执行前仍核对可用空间 |
| DG 首次、样本、续跑及验收 | 正常导出一遍；导出中断重核前缀；首次完整候选审计后，本次替换提升只核对所选文件校验值；事件重新规划及 APPLY 沿用原文件核验 | 不删除首次审计或跳过旧文件核对，不重跑全历史内容比较，不反复重拉 Prod；普通导入不变 |

现有入口要求的 `max_source_rows/max_source_seconds/max_stage_seconds/max_spill_bytes` 等执行输入保留；不删除必填检查、静默抬高现行限制或新增没有依据的数字。未来阶段按实际代码和配置冻结运行值；需要管理员给定取值时如实标记为执行决定，不标记为实测。免测不构成生产操作批准。

按当前调用链，一次单独生成事件 PLAN 再完整 APPLY，至少读取全部目标文件校验值三遍：外部 PLAN、APPLY 内重新规划、写物化前校验；检查日期另外读取 schema/覆盖与校验值。重新生成清单、样本和最终验收各按实际调用累计，不能只记录事件写入条数。本轮日期锁修复不增加全历史源或文件扫描，检查写后读回只覆盖原最近窗口。

DG 沿用现有 DuckDB 16GB/4 线程资源配置，不把它解释为本次实测需求；候选 spill 位于本批次外置 staging，审计沿用禁 spill 规则。原始 18 列文件、冻结 19 列导出、年度中间、候选、提升临时副本的同时存在量须逐项相加。每一遍完整旧文件校验值读取按当前清单约 736.02 MiB 计算；候选读取另计，不能把重复读取说成独立数据量。

### 8.3 全局读取审批清单

本次文档编写没有批准或执行以下全局业务读取。正式操作前分别说明并取得明确批准：

- Prod 新字段补录会按日期有界读取全历史目标键/新增列并更新两表；按 §21 不再增加补录后的全历史重放、旧列全量比对或二次源请求，不能把计数例外扩成额外全量内容读取。
- DG 导出会完整读取 Prod 原始表冻结范围的 19 业务字段，约 1,448 万行，正常一遍；中断续跑可能重读已持久前缀，应单列其最坏开销。
- DG 候选审计会读取全部冻结导出、全部候选，以及旧 DG 原 18 字段做内容对账；再按已批准次数核验正式文件和事件。源冻结后不额外重拉一遍 Prod 全历史。

任一阶段失败先使用已冻结来源、候选和实际已提交事实判断恢复路径；不能以修复为名增加未经批准的全量重读。

## 9. 测试与验收矩阵

下列是完整扩充所需门禁；前三阶段的实际结果见 §16～18，DG 门禁仍待实施，不预填其他项通过。此前两个修复的实际状态单独记录在 §12。真实样本、schema 与预期分别来自 §2/§4；预期值不得调用待测 helper 生成。测试覆盖本次实际业务路径和明确禁止项，不把绕过唯一入口、违反维护前提的任意故障注入作为新增开发要求。

| 测试组 | 正向与反向要求 | 拟落点/现有回归 |
|---|---|---|
| 新 DAO 方法 | 只变指定列；0 值合法；相同值不重复写；缺匹配不插行；旧 18 列、系统列不变；非法更新列/主键不被当更新列 | `tests/test_base_dao.py`、`test_base_dao_batching.py`；增加真实 PostgreSQL 隔离用例 |
| 旧 DAO 能力 | 原重复键保留末条、缺键拒绝、绑定参数分批、新闻 surrogate id 行为保持；旧测试不能改成迎合新方法 | 现有 BaseDAO、新闻、行键、财务绑定参数及索引回归 |
| Prod 源合同 | 默认 18 与显式 19 区别；真实 connector 分页合并；缺状态、NULL、1.5、字符串、bool、范围外值均导致任务失败；同日两表不提交，错误包含日期/代码/当前名称/字段/原始值与类型/原因；合法 0、负估值、原 NULL 数值不误拦；不改其他数据集策略 | 拟 `tests/test_daily_basic_limit_status.py`；Definition/resolver/fields 测试 |
| Prod 两表事务 | 两表均匹配才提交；第二表失败回滚同日；另一日期已提交不受影响；已有合法正常变化可通过、不误拦新日期 | 同上及独立 PostgreSQL 集成 |
| Prod 正常成功路径 | 两表更新后 commit 成功即返回；覆盖量来自已匹配输入，变更量来自 UPDATE；没有额外整日回读；续跑与验收仍读回 | 新历史服务隔离用例；测试独立查询实际结果，不把该查询加入业务执行路径 |
| Prod 长任务 | 中途取消、进程退出、同 PLAN 重跑、业务已提交但状态失败、无状态时业务值恢复、进度单调、TaskRun/node 终态；调用挂起时可取消且 30 秒内有可见状态 | 拟 `tests/web/test_daily_basic_limit_status_maintenance_api.py`、维护 executor 集成 |
| Prod 正常维护失败 | 一条错误阻止整日双表 writer；保留前日提交量；错误显示代码/当前名称/原值/类型；工作流已有成功步骤或允许继续时仍 failed；其他数据集旧行为不变 | §6.6 的 executor/dispatcher/worker 用例；不能以维护动作回归替代 |
| Prod 协议与取消 | TaskRunAware PLAN/APPLY 两个协议注入上下文；取消草稿不可 APPLY；源等待可取消、SQL 等锁按超时后检查取消；提交成功后取消保留本日；提交异常停止，原执行结束后按原 PLAN 读回续跑；维护动作也显示完整值错误；观察失败不影响业务提交 | §6.6～6.8；隔离 PostgreSQL 和可控源替身，不新增跨线程取消测试 |
| Definition 消费者 | 现有维护/排程/工作流时间与过滤器不变；新维护动作不自动进入日常流程 | registry、resolver、catalog、manual actions、date completeness 既有测试 |
| 有界传输 | 新合同不改变公告/周线复权/指数周期线的解析、错误和取消；未知合同仍拒绝 | 对应现有 bounded-call/stream 测试及新合同测试 |
| DG schema/转换 | 完整 19 字段；状态严格整数；原 DECIMAL 精度、NULL、负值和顺序保持；18 列旧文件不能冒充新结构 | `test_daily_basic_contracts.py`、`test_daily_basic_raw_io.py`、`test_daily_basic_history.py` |
| DG 显式替换 | 默认路径仍拒绝异内容；批准替换可通过正常 18→19；旧列变化、执行前目标与审计不符、候选损坏、跨文件系统拒绝；已有日期锁生效 | `test_daily_basic_history.py`；按年源对账与逐文件提升；不增加绕过入口制造并发事件的用例 |
| DG 事件 | 同日期旧→新追加成功；检查目标三个身份字段均正确；旧绿色不跳过新检查；已有本次结果幂等跳过；执行前发现的计划外记录或失败检查仍按原行为拒绝 | `test_daily_basic_events.py`、`test_daily_basic_checks.py`；不增加实时并发事件拦截用例 |
| DG 部分完成 | §7.5 各状态均覆盖；文件已换而事件未写、只写物化、只写一项检查均能正确续跑；恢复后没有重复记录 | 同上；不能只测全成功 |
| DG 报告与小样 | 原报告与参数默认行为不变；首次完整审计保留，替换提升不重调全历史 audit，候选 SHA 变化仍拒绝；样本、续跑使用 promote.files；只读事件命令不新增 sample-date；后续全量不改变样本归属；trade_date 元数据一致 | §7.7 的 history/events/CLI 隔离测试；普通导入仍走原流程 |
| DG 范围/性能 | `K=C∪W`，55 日样本不能退回仅 20 日；无历史检查日期不造绿；索引批查询，不逐日深读全历史 | `test_daily_basic_performance.py`、`test_daily_basic_sensor.py`、catalog/static gates |
| 业务读取回归 | 榜单、自选、Quote 旧字段/排序及相关查询保持 | 已有对应 Wealth/Quote API 测试；不新增前端功能 |

真实验收分开记录：隔离单元/集成证明方法与事务；有界源样本证明源合同；获批最小真实运行证明取消—续跑—读回与进度；完整正式执行及对账才证明历史全部补齐。任一层缺失都不能由“测试总数通过”代替。

## 10. 分阶段实施、读写边界与完成条件

所有阶段在当前 `dev-interface` 工作区推进，保留其他未提交改动，不创建分支/worktree、不自行提交或发布。第一至第三阶段开发与隔离验证已完成，结果见 §16～§19；管理员部署后，本轮获准完成第三阶段两交易日生产验收，结果见 §20。全历史与 DG 的后续执行仍按下述范围分别批准。

### 10.1 五个开发阶段

| 阶段 | 主要开发内容 | 完成目标与验收 |
|---|---|---|
| 1. 表结构和指定列更新 | 两表 ORM、真实 Alembic head 后的新迁移、独立 `bulk_update_columns`；不迁移旧调用方 | 隔离 PostgreSQL 证明仅改指定列、原 18 列和系统列不变、同值重放幂等；旧 DAO 回归保持 |
| 2. Prod 日更与错误提示 | 完整 19 字段、本数据集严格校验；普通维护、工作流和新维护动作共用错误展示；正常维护失败保留已提交量 | 一条坏值阻止整日提交并显示代码/名称/数值原因；工作流停止；其他数据集及原应用返回不变 |
| 3. Prod 历史补录 | 新维护动作 PLAN/APPLY、逐日双表事务、有界请求、SQL 子批次、现有取消/进度与原 PLAN 续跑 | 中断保留已提交日期、未提交日期回滚、状态失败不撤销业务、提交异常不报假成功；不新增取消线程和恢复表 |
| 4. DG 字段和历史文件 | 19 字段日更/检查、完整导出、候选构建和审计、原 bootstrap 的显式替换分支与现有文件进度 | 原 18 列一致、新增状态正确；全候选审计后小样提升；实际文件与现有 promote.files 能对账续跑 |
| 5. DG 事件与整体回归 | 原事件流程识别批准旧记录/本次新记录，按 K 重检并绑定新物化；部分完成后重新规划；文件与事件联调 | 小样、只写物化、只写一项检查均可继续；无重复事件、无旧检查冒充新检查；旧入口和消费接口回归保持 |

每阶段先核对本文对应设计和当前代码，再实施最小补丁并独立验收。阶段 4、5 都完成前不切换正式 DG 结构。字段名修正、错误展示和上述正常续跑用例属于本需求；新锁、跨线程取消、独立状态实体或任意外部写入防护不属于开发内容。

### 10.2 正式执行顺序

下表 P0～P6 为原方案的准备、部署和生产执行顺序，不等于另有七个开发阶段。各次正式读取和写入仍按其范围批准；不以完成某个开发阶段自动取得生产授权。

| 阶段 | 目标、实现范围 | 读写/失败/恢复 | 放行与验收 |
|---|---|---|---|
| P0 设计核验 | 刷新 schema/head、完整合同、消费者和配置；按 §8.2 不增加专项性能测量 | 纯代码/统计/有界源读取；真实写样本另批；未实测如实记录 | 本文评审；实际运行输入来源明确；旧能力回归范围明确 |
| P1 Prod 代码与隔离验证 | 两模型、新迁移、新指定列方法、专用维护动作、完整日更与有界合同；实施前在本文记录最终符号 | 仅隔离资源；新方法不进入旧调用方；旧合同回归失败则停止 | §9 Prod 门禁；真实 head 与调用方审计；无旧能力变化 |
| P2 Prod 迁移与代表样本 | 批准后迁移两表、部署配套代码；实际运行/取消/续跑/读回 | 维护窗口控制冲突；不清表；只回滚未提交日期；状态失败不撤销业务 | 独立批准及真实证据；预算与空间仍适用 |
| P3 Prod 全历史补录 | 按 §23.4 的 v3 冻结 PLAN 和三字段投影处理剩余日期；通过现有节点/页面观察 | 同日两表事务；执行/续跑时完整日期读取跳过；冲突停止；成功后不另加全范围核对 | 明确全历史范围批准；任务日期全部完成、覆盖量对应冻结目标、拒绝量为零及终态一致；只改新增列的 SQL 与样本证据沿用，不重复全量旧列比对 |
| P4 DG 新结构与候选 | 同步 19 字段日更、检查、bootstrap 代码并隔离验证；批准后从 Prod 导出、构建、审计 | 不提前覆盖正式文件；保留冻结导出和候选；中断按原前缀核验续跑 | 独立全局读取批准；§7.3 全候选审计及现行执行限制通过 |
| P5 DG 文件与事件切换 | 替换前批准候选/旧身份/范围；暂停日更和检查并确认无活动 run；文件提升后生成当前事件清单，小样后分批登记 | 中断后在原批准范围内重建剩余清单；逐日期非阻塞锁保护，既有历史不删 | 文件写入与 runless 事件分别批准；§7.4/7.5 样本与读回通过 |
| P6 收口与自然日更 | 正式对账、新检查目标核对、恢复原启用状态并观察下一次自然日更 | 失败日期保持不可用；未完成不得恢复日更掩盖；新日期不暗中扩进旧计划 | Prod 与 DG 结果、全部差异、110 检查基线刷新后的实际清单及自然日更结果回填本文 |

Prod 在 P3 完成后冻结历史窗口，随后 DG 才导出；其他日期正常业务读取与本次补录分开。DG 可先在 staging 完成耗时的导出和候选准备，正式结构切换与文件/事件发布才进入本族维护窗口。存在会改冻结历史的任务时不得承诺来源稳定，须停止并重新安排窗口。

原 DG 代码不支持把 18 字段旧目标当作 19 字段目标，因此新代码正式切换和文件提升不能当作互不相关的部署。任何文件变成 19 列后，不得简单回滚到只认 18 列的代码。Prod 失败暂停新动作、保留已增加的列和已提交结果；DG 失败保留新候选/进度，按实际状态继续完成，不自动删除新增列、回退文件或擦除事件。

## 11. 当前交付与后续记录

| 项目 | 当前状态 |
|---|---|
| 管理员确认的方向 | Prod 只补新增列；DG 从补齐后的 Prod 重新 bootstrap；新增能力不影响旧能力 |
| 只读事实与源样本 | §2 已记录；统计、检查数和版本执行前刷新 |
| 扩充代码、数据库、Lake、事件变更 | 第一至第三阶段及 Prod 代表样本完成，见 §16～§20；三字段补录见 §21，最新代码已部署，正式全历史执行见 §22。DG 第四、第五阶段尚未开发，未进行本次 DG 文件或事件变更；两个现有修复见 §12 |
| 性能决定 | 管理员决定不另做专项测量，后半夜平峰执行；未知耗时如实保留，现有执行限制不变 |
| 已确认修订 | 校验错误任务失败并给代码/名称/数值原因；文本 SQL 保持旧列；DG 旧身份冻结、重新规划续跑及日期锁 |
| 后续证据落点 | 本文对应阶段回填最终代码位置、命令/范围、测试、源/归一化/拒绝/写入/目标计数、性能与恢复验收；不另存第二份主方案 |

文档完整性检查只能证明索引/链接等检查范围通过，不能证明上述待开发能力、预算或生产验收已经完成。

## 12. 两个现有问题的修复 LLD 与 2026-11-11 交付记录

### 12.1 目标、范围与当前依据

管理员已批准修复两个问题，并在本轮范围选择中明确不开发完整扩充。目标是保留已提交维护进度，以及在登记每日指标历史事件时阻止同日期文件并发替换。只修改下列源码、相应隔离测试和本文；不增加配置、接口参数、数据模型、迁移、后台服务或生产执行入口。

CodeGraph 已检查 `TaskRunDispatchOutcome` 的影响面、维护 dispatcher 到 worker 的收尾，以及 `apply_daily_basic_events`、日更写文件和历史提升的调用链。直接核验补齐字符串注册及测试：新闻关联和板块热度走通用维护协议，板块每日分析还会提供单元内进度，指数周期服务有独立分支；修复不得把这些任务的执行方式迁到每日指标专用分支。测试直接覆盖当前代码，图中缺少测试关系不作为没有测试的结论。

| 问题 | 当前错误步骤 | 实现位置与边界 |
|---|---|---|
| 维护进度归零 | 通用维护只在整个成功时返回累计值；异常返回默认 0；worker 又以 0 覆盖已提交的 TaskRun 进度 | `src/ops/runtime/task_run_dispatcher.py` 的通用维护分支：在原有逐 unit 状态提交中保存累计值；unit 返回后先保留已提交结果，再处理观察状态；取消/失败结果携带已知累计值。`src/ops/runtime/worker.py` 仅对维护任务失败/取消保留已有进度与诊断，其他类型收尾不变 |
| 文件/事件缺少同一日期锁 | 提升/日更持日期锁，事件发布只持 CLI 全局锁；文件校验和事件登记间可被其他文件写入打断 | `daily_basic_events.py` 新增私有日期锁上下文；物化登记和检查登记各在同一现行日期锁下核验/写入；不改变物化批次先于检查批次的现行顺序，不修改日更与提升算法 |

### 12.2 维护进度、失败和恢复

1. 业务提交仍由各现有 executor 控制，dispatcher/worker 只使用 executor 返回的结果和已持久化观察值，不介入业务事务。
2. 累计值在进入 PLAN/APPLY 前初始化，PLAN 失败也有明确的 0；每个成功 unit 的返回值先计入内存累计，再结束节点并在原有状态事务中同步 TaskRun 累计行数、诊断及原因统计，不增加每 unit 的提交次数。
3. 若业务已提交、结束节点或保存进度失败，内存中已返回的业务结果不得因状态 rollback 丢失；异常结果仍带回这些已知值。当前 unit 没有返回成功结果时，不把它的临时计数当成提交量。
4. worker 对维护任务失败/取消取“原持久进度与异常结果已知进度中的较大值”，防止默认 0 或滞后快照把进度降低。诊断没有新结果时保留原内容；当前活动节点进入相同失败/取消终态，保留节点自己的数量，不把全任务合计写到单个日期节点。
5. 多个 unit 中的已成功节点保持成功，失败/取消只收口当前活动节点；不得因新节点建立失败而回头改坏先前成功节点。正常成功分支的结果和其他任务类型维持原义。
6. 进程退出后仍以原计划及业务事实恢复；本次不新增 checkpoint 表，也不声称仅靠通用观察表能推断“业务已提交但任何结果或观察都没留下”的未知数量。未来每日指标服务仍按 §6.4 读回实际两表状态。业务数据保持已提交，观察缺失不得触发删除或回滚。

### 12.3 日期锁、检查身份与避免死锁

1. 私有锁只在 `report-events` 写入路径调用，`plan-events`、`audit-events` 和 `register` 不创建日期锁。路径严格复用 `<staging_root>/daily_basic/locks/<日期>.lock`，用现行 `_safe_root` 核对父路径；不写正式 Lake。
2. 使用 `fcntl.LOCK_EX | fcntl.LOCK_NB`。锁已被日更、提升或其他事件进程占用时，立即报 `partition_locked`，不循环等待，不 sleep，不删除锁文件。无论正常、校验失败、事件写入失败，退出上下文都关闭文件并释放锁。
3. 保持原物化批次与检查批次顺序；物化身份在批量读取时取得，日期锁内核对文件及这份身份后登记，随后批量读回。这里不是在锁内重新读取物化身份，不承诺检测绕过正式入口的所有并发事件；2026-11-12 的适用性复核见 §14。不为所有历史日期新增逐日期事件深查。
4. 所有日期的物化沿用现有批量查询读回并核对交付信息，包括没有检查的历史日期。检查阶段只对原最近窗口日期重新持锁，锁内有界读取该日当前物化，重新审计文件和交付信息；确认一致后绑定 `storage_id/run_id/timestamp` 追加缺少的检查。两项写完读回这两项检查和当前物化，任一不对应即失败，不报告整体成功。锁限制文件写入；维护期的正式发布顺序与现有 CLI 全局锁负责排除另一个受支持的写入者。
5. 同时最多持一个日期锁；不在日期锁内申请全局事件锁或历史工作目录锁；原入口先取得自身外层锁，日期锁一律非阻塞取得。因此不存在持日期 A 等日期 B 或反向等待外层锁的环路。两个阶段之间允许释放锁，重新取得后必须重新验证，不能借用上阶段结论。
6. 事件部分写入保留，重新生成原范围的事件计划后只补缺少项；文件变化或失败检查停止，不擦除事件。锁修复不放开已有目标冲突、不实现 18→19 旧新身份分类、不改变最近 20 日检查范围。

### 12.4 性能、测试与验收清单

管理员已决定不另做专项性能测量。本次维护修复只使用当前任务及当前活动节点，不扫描业务数据；在原 unit 状态提交内增加少量字段赋值，不增加业务事务。DG 锁每个物化日期取得一次，每个原检查日期再取得一次；不扩大日期、文件或源读取范围，写后事件读回仅限原检查日期。已有每批 500 日期、20,000 条事件返回限制与其他执行限制不变。中断后按现有重新规划成本继续，不能宣称无重读。

| 硬要求 | 正向测试 | 反向测试/回归 | 验收边界 |
|---|---|---|---|
| 已提交维护进度不归零 | 一个 unit 成功后第二个取消/失败；TaskRun 与成功节点保留字面预期数量 | 已保存的单元内进度高于异常返回时不降低；正常成功统计不变 | `tests/test_maintenance_progress.py`，临时 SQLite 与独立业务事实，不连接正式数据库 |
| 业务提交后状态保存失败 | executor 已提交并返回，故意让节点结束或一次状态提交失败，失败结果保留该 unit 数量 | 失败前没有提交的不增加数量；状态失败不撤销业务事实；非维护任务不改变旧收尾 | 同上，故障注入不替代 PostgreSQL/新字段 SQL 验收 |
| 节点终态和诊断 | TaskRun 与当前节点同为失败/取消，已成功节点不改，已有诊断保留 | 新节点建立失败不把前一成功节点改成失败 | 同上及现有新闻任务、worker lane/运行时回归 |
| 同日期文件锁生效 | 锁内登记物化与检查，回调尝试竞争同日期锁被拒绝 | 已持锁立即报错且不写事件；未选日期不被锁住；下一日期可取得锁 | `test_daily_basic_events.py`，临时 staging、DuckDB、ephemeral Dagster instance |
| 异常释放与续跑 | 事件接口中途报错后重新规划继续，数量及三个检查目标身份正确，无重复事件 | 一项检查后失败也释放锁；旧冲突/失败检查仍拒绝 | 原 `test_partial_api_failure_resumes_without_duplicate` 加锁竞争及读回用例；不连接正式 instance |

开工前审计结论：上述修复复用现有任务模型、维护协议和日期锁协议，不引入共享合同字段，不改变数据集日期、字段或存储事实；允许按本节进入两个修复。测试缓存、临时数据库、Dagster home、日志统一位于 `/private/tmp/daily-basic-lld-fixes.*`，不安装依赖。

### 12.5 本轮实际交付与验证（2026-11-11）

本轮两个修复已实现并完成下列隔离验收，未部署。完整 19 字段、值校验失败的代码/名称提示、指定列更新方法、历史补录动作及 DG 18→19 替换尚未开发；这些决定已经回填设计，不能算作已交付功能。

| 改动文件 | 本轮实际结果 |
|---|---|
| `src/ops/runtime/task_run_dispatcher.py` | 每个成功 unit 在原状态提交中保存累计数量；业务返回结果先保留再结束节点；失败/取消返回已知数量；状态提交失败也能保留已返回的业务结果；新节点建立失败不改坏已成功节点 |
| `src/ops/runtime/worker.py` | 维护任务失败/取消不再以默认 0 覆盖持久数量；无新诊断时保留原内容；活动节点结束时保留其自身数量；其他任务类型的默认收尾不变 |
| `tests/test_maintenance_progress.py` | 11 个独立字面预期用例，覆盖已提交后取消/失败、单元内部分提交、状态提交失败、正常成功、不误改成功节点、非维护任务原行为和活动节点终态；临时业务表实际行数独立读回 |
| `daily_basic_events.py` | 物化和检查登记均持现行非阻塞日期锁；所有物化沿用批量查询读回交付信息；检查窗口内锁内再读当前物化，检查登记后核对两项结果的目标；其他日期不造检查 |
| `test_daily_basic_events.py` | 新增 5 个用例，覆盖真实文件锁竞争、同时只持一个日期锁、检查异常释放后续跑、检查目标写后读回以及无检查历史日的物化读回 |

基线缺陷已先重现：维护新增用例首次运行 7 失败/2 通过，失败即进度归零；DG 最初 4 个新增用例首次运行 3 失败/1 通过，分别暴露不遵守文件锁及不核对检查写后身份。随后另补活动节点和历史物化读回用例。没有通过修改原预期来消除这些缺陷。

| 验证组 | 实际命令/范围 | 结果及限制 |
|---|---|---|
| 维护与架构回归 | 仓库根 `.venv/bin/python -B -m pytest -q tests/test_maintenance_progress.py tests/test_news_stock_task_runtime.py tests/test_worker_lane.py tests/architecture/test_subsystem_dependency_matrix.py tests/architecture/test_platform_legacy_guardrails.py tests/architecture/test_operations_legacy_guardrails.py` | 40 passed；仅内存/临时 SQLite 和替身，不代表 PostgreSQL 新字段验收 |
| 现有 Ops 运行时 | 仓库根 `.venv/bin/python -B -m pytest -q tests/web/test_ops_runtime.py` | 64 passed；现有隔离 API/运行时夹具 |
| DG 本族回归 | orchestrator 目录 `.venv/bin/python3 -B -m pytest -q tests/test_daily_basic_events.py tests/test_daily_basic_history.py tests/test_daily_basic_raw_io.py tests/test_daily_basic_checks.py` | 100 passed；临时 Parquet、DuckDB 和 ephemeral instance；包括原导入、冲突拒绝、部分事件续跑和原文件写入合同 |
| DG 全局治理与静态门禁 | 同一解释器运行 `test_asset_governance_contracts.py` 与 `test_run_contract_static_gates.py` | 120 passed、5 failed，另 223 subtests passed；没有宣称全局通过 |
| 全局失败对照 | 新进程显式加载修改前保存的 `daily_basic_events.py`，重跑上述 5 个失败用例，不还原工作区文件 | 同样 5 failed：`gold_major_index_quantitative_structure` 的 catalog/active definitions 数量、schema/check 注册不一致，以及 `stock_suspend_confirmed_test_support` 辅助模块导入失败；涉及文件本轮未改，未扩大修复 |
| 静态与文档检查 | DG 项目 Ruff 致命错误基线及本轮 DG 文件完整规则；Prod 三个修改/新增文件的致命错误检查和 AST 解析；`scripts/check_docs_integrity.py`；本轮差异空白检查 | 通过；仅证明对应静态范围，不替代正式执行 |

最终回归命令显式把 pytest cache/basetemp、TMPDIR 及 DG 的隔离 DAGSTER_HOME 放到本任务 `/private/tmp` 目录；表中记录命令核心与范围，省略这些临时路径参数。前期首轮基线同样把 pytest cache/basetemp 放在本任务目录，只用于隔离夹具；未调用正式 Dagster instance、正式 Lake、Prod DB 或 Tushare。既有 dispatcher/worker 的指数周期调度未提交改动保持原样。CodeGraph 已按仓库根同步并确认索引状态，未改变架构边界或新增消费者。

后续生产资源状态仍为：未迁移、未补数、未替换正式文件、未登记正式事件。管理员后半夜窗口决定不等同于本轮已批准或已执行这些操作。

## 13. 本轮设计补齐与接口验证（2026-11-11）

本节保留当时的有界接口验证记录，设计取舍已由 2026-11-12 的 §6、§7、§10 和 §14 更新；不把当时讨论过的取消线程、第二套报告版本作为当前开发要求。

### 13.1 范围、步骤及检查条件

管理员本轮只要求补齐上一轮具体设计，再验证源接口并汇报；不开发扩充代码。设计已补到 §6.6～6.8 与 §7.7：校验错误的具体传递、TaskRunAware 协议、请求/SQL 取消、提交结果不明时读回、DG 报告身份和先小样再全量。

验证限于 `000001.SZ`：近期 2026-11-02～2026-11-10、历史起点 2010-01-04。先用 tushareMcp 核对默认字段、显式旧 18 字段及完整 19 字段；MCP 不暴露 limit/offset。再用本地项目现有 `TushareHttpClient → TushareSourceConnector → DatasetSourceClient` 对官方 HTTPS 做真实请求，不连接数据库、不调用 normalizer/writer、不读取正式 Lake/instance、不安装依赖。

项目验证用进程内 Definition 副本追加 `limit_status`，不修改 registry。点日期参数经现行 `_daily_basic_params` 生成；区间仅作源接口/通用下载器试验，使用文档中的单代码 start_date/end_date，不能声称正式 resolver 把日期 unit 改成范围。临时 page_limit=1/3 只用于让极小样本产生整页、空末页与多个非空页，原 Definition 的 6,000 不变。

| 项目验证 | 预计逻辑请求量（不含失败重试） | 断言 |
|---|---:|---|
| 20261110 默认、显式旧 18、显式完整 19 | 3 | 默认仍 18；显式 19 字段顺序完整；同日原 18 值完全相同 |
| 20100104 完整 19 | 1 | 历史起点该股票可获取，状态原生整数 0～6 |
| 近期单代码范围，一次完整响应 | 1 | 作为分页比较的独立基准，记录实际日期/键/值 |
| 20261110，page_limit=3 | 1 | 一行短页即终止，不继续请求 |
| 同点，page_limit=1 | 2 | 整页后探测空页，合并结果无重复 |
| 近期范围，page_limit=3 | 3（若为 7 行） | 3+3+1，offset=0/3/6，合并后的完整 19 值与独立基准一致 |

预计 MCP 3 次、项目 11 次；这些是此次有界验证请求的逐项推导，不是生产历史任务预算。发生错误先记录实际错误和已完成范围，不自动改为全市场、放大日期或绕过项目解析。审计记录只保留参数、字段、页数、数量、样本状态和对比结论，不保存 token 或完整请求载荷。临时输出位于 `/private/tmp/daily-basic-design-interface.*`，有效结果回填下节。

### 13.2 实际验证结果

验证时间为 2026-11-11 23:33（Asia/Shanghai，项目请求开始 15:33:23 UTC）。本轮只改本文；未开发扩充、未提交本轮文档、未部署、未访问 Prod DB 或正式 DG 数据/事件。

| 核验项 | 实际请求与结果 | 结论 |
|---|---|---|
| MCP 字段 | 3 次：20261110 默认/显式旧 18 各 1 行，20261102～20261110 显式 19 共 7 行 | 默认不包含状态；完整 19 顺序、类型和单代码/日期范围符合预期；同日旧值一致 |
| 项目默认与显式字段 | 真实 connector 各 1 次默认、显式旧 18、显式 19；均 HTTP 200、业务 code=0，各 1 行 | 原 18 字段逐值相同，且与本轮 MCP 同日样本完全相同；状态 4，原生 int |
| 历史起点 | `000001.SZ,trade_date=20100104`，完整 19，1 行 | `limit_status=4`，原生 int；只证明该股票该日，不外推全部历史 |
| 区间基准 | 单代码 `start_date=20261102,end_date=20261110`，完整 19，一次 7 行 | 与 MCP 的 7 行完整业务值一致；日期为 11-02、03、04、05、06、09、10，主键不重复 |
| 短页结束 | 20261110，limit=3，offset=0，1 行后结束 | request_count=1，未多发请求；与独立点请求完全相同 |
| 整页后空末页 | 同点，limit=1，offset=0/1，返回 1/0 | request_count=2，terminal_offset=1、terminal_page_rows=0；合并为 1 行，无重复/遗漏 |
| 多个非空页 | 同一有界区间，limit=3，offset=0/3/6，返回 3/3/1 | request_count=3、合并 7 行、末页 offset=6；全部 19 字段逐值及返回顺序与独立区间请求相同 |
| 字段与元数据分离 | 所有非空完整响应均有完整 19 业务列；SourceClient 另追加本地辅助字段 | 比较只投影业务列，未把 api_name/fetched_at 当源合同字段；状态全部为合法原生整数，无 NULL/字符串/bool |
| 请求总量 | MCP 3 次；项目 11 次逻辑请求，项目累计返回 20 行，去重为 8 个股票/日期键 | 项目 11 次均 HTTP 200/code=0、传输重试 0、下载器重试 0；这些数量含重复比较，不能当 20 条独立历史数据 |

项目链路实际经过现行 `TushareHttpClient.call`、`TushareSourceConnector.call`、`DatasetSourceClient.fetch/iter_pages` 与原 HTTP 解析。临时审计只在 `requests.Session.post` 外包一层记录参数/页数，内层仍调用原方法真实联网，未替换响应。进程显式设置 `GOLDENSHARE_ENV_FILE=/dev/null`，使用已有进程凭证及默认官方 `https://api.tushare.pro`，未加载仓库 `.env`；这证明本地项目客户端接官方接口的行为，不代表已验证部署中 Prod 的网络配置。

本轮使用 `codegraph_explore` 核对严格拒绝策略到 normalizer/executor/dispatcher/workflow，以及 TaskRunAware planner/executor 到运行上下文的影响面；直接代码补核字符串注册、worker 收尾、原生 SQL 与 DG CLI。新补的 §6.6～6.8、§7.7 已与实际类名、协议字段、两层有界合同检查、CLI sample-date 限制、现行报告初始化和事件身份字段对照。源接口的完整字段/分页门禁通过；后续可以按本设计进入扩充代码的开发评审。仍需在相应实施阶段完成旧消费者回归、隔离 PostgreSQL 更新/取消测试、DG 小样/中断测试；正式执行前补齐动作接收字节上限的管理员取值及现行 DG 必需执行输入，取得各阶段读写批准。这里没有新增性能测量前置条件，也没有把小样或两个旧 bug 的测试当作完整扩充已验收。

本轮文档完整性检查与本文件差异空白检查通过。源码未改，因此未重复执行 §12 的隔离回归；本轮真实证据仅覆盖上述源请求与下载器，不覆盖尚未实现的写入、失败提示和取消/恢复。临时审计脚本与响应记录在结果回填后清理，不作为第二份长期报告。

## 14. 2026-11-12 按实际调用链简化方案

### 14.1 对上一轮审计结论的纠正

上一轮把“批量读物化之后、取得日期锁之前插入事件”的实验列为 P1，是我的判断错误：实验直接调用 `report_runless_asset_event`，没有经过正式 CLI 的全局事件锁，也没有纳入本次维护已经暂停日更和检查的前提。它证明绕过入口能插入记录，不能证明按本次执行方式会有第二个发布者。将它直接升级为必须修复的问题，造成了不必要的逐日期查询和防护设计；本轮撤回该 P1，不追加这项代码或回归要求。

实际链条为：本族日更和检查退出 → bootstrap 文件/事件阶段顺序执行 → 事件写入走唯一现行 CLI → `_event_apply_lock` 排除第二个 CLI 写入者 → 沿用现有日期锁和批量读回。代码依据是 `daily_basic_history_cli.py` 的 `_run_event_stage/_event_apply_lock`、`daily_basic_events.py` 的 `_idle/apply_daily_basic_events`，以及本族 asset/job/sensor。直接写事件的其他生产调用方未在当前源码中发现；手工绕过入口或维护中重新启动作业不在本次支持的执行方式内。这是有前提的结论，不是声称文件锁会锁住 Dagster 全部事件。

### 14.2 保留和删减的具体范围

| 原问题或设计 | 实际发生条件与依据 | 本次处理 |
|---|---|---|
| DG 再增加锁内逐日期身份查询 | 需要在维护中另有发布者；正式 CLI 已串行，本族正常作业已退出，实验绕过了这条链 | 撤回新增防护，保留现有锁、批查询和检查目标读回；不改锁顺序 |
| Prod SQL 观察线程、连接操作序号、跨线程取消与关闭 | 是为了追求正在执行的每条 SQL 都即时取消；现有小批次 SQL 超时和执行前后检查已经提供停止边界 | 删除该设计及专属测试，按 §6.8 复用现有做法，不主动取消 COMMIT |
| 提交回执丢失后自动识别事务结果 | 正常返回的提交不存在这个歧义；断连后简单 SELECT 旧值也不能证明回滚 | 保留“异常停止、不报假成功”这一必要规则；原执行结束后复用原 PLAN 读回续跑，不另建自动确认或恢复流程 |
| 历史补录只有泛化错误提示 | 正式维护入口确实走 `_dispatch_registered_maintenance_action`；源校验错误会进入其现有通用异常分支 | 补齐这一新增错误的 operator_message/technical_payload；复用同一展示逻辑，不改其他维护异常 |
| 物化 metadata 写成 date | 现有 `_history_evidence` 实际使用 trade_date，按错误字段实现会误识别本次记录 | 修正文档，直接复用原 evidence 内容，不再维护另一份字段清单 |
| 第二套报告版本、重复日期状态、过早冻结旧事件 | 不是追加字段和重新 bootstrap 所必需；旧事件在候选准备期间还可能被正常日更更新 | 保留原报告和参数含义，只加 replace_existing、audit 的必要旧身份/旧 SHA；promote.files 继续表示进度；在维护窗口审计时保存旧身份 |
| 正常更新后、提交前再读整日两表值 | 输入已匹配，指定列 SQL 和同日事务已确定写入；提交前读回不能证明提交成功 | 删除正常成功路径的回读；保留测试、最终验收和续跑读回，同步调整返回计数口径 |
| 每次替换提升都重复全历史审计 | 首次完整审计已保存候选与旧目标 SHA，后续匹配相同 SHA 即对应同一批已审计文件 | 本次替换只做所选文件校验值核对，不重读全历史或重新比较原 18 列；普通导入不变 |
| plan-events、audit-events 增加样本参数 | 样本提升后 promote.files 已限定范围，已有 pending 清单排除完成项 | 删除两项只读命令的参数扩展；保留 promote 选样本及原 report-events 能力 |

新增代码的目的仅为满足本需求。原 18 列不变、状态值合法、两表同日提交、候选完整审计、逐文件提升、检查绑定新物化，以及只写部分文件/事件后的续跑，都是本次功能实际依赖的要求，仍须实现；这些与禁止无实际用途的防护不冲突。不再增加“所有异常都自动恢复”“阻止任意管理员脚本写入”等目标。

### 14.3 本轮核验与下一步

本轮使用 `codegraph_explore` 核对 CLI、事件发布、日更入口和 Prod 维护协议，直接补核调用方、局部 SQL 超时、TaskRun 取消/进度以及现有报告字段；没有进行源请求、数据库或 Lake 读取/写入。沿用 §13 的真实字段与分页证据，不重复调用源接口。只修改本专项原文，未修改代码或撤销已提交修复。

文档完整性、修改差异空白及上述当前设计的一致性检查通过后，按 §10.1 五个开发阶段推进；各阶段仍先核对其原有消费者和必要回归。不增加专项性能测量，不把本轮删去的实验防护重新列为开工条件。正式执行所需的现有预算输入和读写批准按原阶段办理。

## 15. 2026-11-12 删除重复步骤后的开发条件复核

**当前具备开始 §10.1 第 1 阶段“表结构和指定列更新”开发的条件。** 本次复核未发现仍需先讨论的架构选择或必须新增的防护；后续阶段按既定次序进入，不把未完成的实现、测试或生产执行算作已验收。

| 复核项 | 当前依据与判断 |
|---|---|
| 实施范围和旧能力 | 只处理每日指标；新 DAO 方法不迁移原调用方，历史动作不替换正常整行写入；原接口只消费其既有字段。没有新增 worker、锁、取消线程或重复状态 |
| 源字段和分页 | §13 的完整 19 字段、短页、多页及空末页真实验证仍适用；本轮没有改变源参数或时间模型，无需重复请求 |
| 当前实现及迁移起点 | 2026-11-12 本地静态解析确认 Alembic 单一 head 为 `20261031_000187`，没有缺失父迁移；登记的每日指标仍是 18 字段、raw_core_upsert；严格拒绝策略与该写入路径组合仍为 0 个。第 1 阶段可据此实施，写迁移时再核对 head，避免期间其他提交造成变化 |
| 新更新方法 | 原 `BaseDAO.bulk_upsert` 仍更新全部非主键列，因此独立指定列方法确有必要；输入匹配、参数绑定、只写指定列和事务归调用方的合同明确。已删除正常更新后的整日回读，测试仍独立读回验证 SQL 和旧列 |
| DG 替换与事件 | 首次完整审计仍覆盖来源、全部候选及原 18 列；提升按已审计 SHA 和旧/新文件判断执行。正常路径与部分完成后的恢复均有步骤和测试要求；只读事件命令参数不变 |
| 剩余验证的阶段 | PostgreSQL 指定列更新、取消/事务用例和旧 DAO 回归是第 1～3 阶段的开发验收；DG 文件/检查及续跑用例是第 4～5 阶段的验收。§3.3 的 Definition 消费者在第 2 阶段修改事实源前按当时代码核对，不因日期合同不变而省略 |
| 正式执行的条件 | Prod 部署版本/实际迁移状态、冻结日期及 DG 事件清单在正式执行前刷新；已有预算输入、接收字节取值和各阶段读写授权在对应执行准备中落实。它们不阻止第 1 阶段的隔离开发，也不新增专项测量 |

本轮使用 CodeGraph 和当前代码复核 promote→audit 调用、文件 SHA 核对及 CLI 的样本参数传递，并静态核对本地迁移与 Definition；只改本文，没有执行数据库/Lake 读取或写入、源请求、开发或部署。文档完整性和差异检查用于检查文档，不作为未开发能力的通过证据。

## 16. 第一阶段实施与验收（2026-11-12）

### 16.1 本阶段范围和开工核对

管理员明确要求严格执行第一阶段，完成后独立审计。本阶段只实现 §5 的两表模型、迁移与独立指定列更新方法，并完成隔离验证；不修改 DatasetDefinition、source_fields、normalizer、writer、Ops、API 或 DG，不部署、不执行正式迁移/补录，不新增配置、线程、锁或状态实体。

开工时 CodeGraph 的 explore/impact 已覆盖 BaseDAO、GenericDAO、服务表 DAO、整行 writer 与旧调用方及测试；直接补核两表模型、DAOFactory、Quote/榜单/自选查询。新方法没有现有调用方，旧 writer 仍走 bulk_upsert；Quote 整对象读取要求后续先迁移数据库再部署新模型，本阶段代码不能单独部署。当前本地单一 Alembic head 再次核实为 `20261031_000187`，故本次迁移使用 `20261112_000188`，直接接该 head。

| 硬要求 | 实现位置与边界 | 正向/反向验收 |
|---|---|---|
| 两表新增可空整数，无 0 默认值 | 两个现有模型；`alembic/versions/20261112_000188_add_daily_basic_limit_status.py` | 真实旧 18 字段结构上升级，旧行新列为 NULL；旧行、主键和索引不变 |
| 原 DAO 方法不变 | `src/foundation/dao/base_dao.py` 只增加 bulk_update_columns 及必要 import | 原方法及批次计算的源码对照；原 BaseDAO、新闻/行键等回归不改预期 |
| 只更新指定列，不插行 | 元数据取得主键/列，update_columns 为非空真实非主键列；调用方保证行内键和值、类型和去重 | 0 值、已有相同值、复合主键不同日期、目标不存在；旧 18 列及系统列保持；非法列/主键更新被拒绝 |
| 文本 SQL，不触发 onupdate | 用 sqlalchemy.text 的参数绑定 UPDATE FROM VALUES；标识符由当前表元数据及 dialect 引用；VALUES 参数按元数据类型显式 CAST | 检查真实执行 SQL 的 SET 只有指定列；真实读回 updated_at 原值；NULL 到值、值到 NULL 均按 SQL 比较处理，不补 0 |
| 有效分批与事务由调用方控制 | 使用原 _compute_batch_size，参数数为主键列数加更新列数；方法不 commit/rollback/写状态 | 人工缩小参数上限触发分批；返回实际变更量，0 不回退为输入行数；真实调用方提交/回滚、第二表失败回滚 |

### 16.2 SQL、测试资源与交付文件

SQL 形态为 `UPDATE <表> AS target SET <指定列>=incoming.<指定列> FROM (VALUES (CAST(:v AS <元数据类型>), ...)) AS incoming (<主键和指定列>) WHERE <主键相等> AND (<任一指定列 IS DISTINCT FROM 新值>)`。CAST 用于让 DATE/INTEGER 和全 NULL 参数仍有明确 SQL 类型；不增加业务值转换、重复键处理或错误吞并。新方法可被原始表 GenericDAO 和服务表 DAO 继承，旧方法的签名与 SQL 不变。

新迁移只 add_column 两次；downgrade 仅声明移除本次新增的两列，属于显式反向迁移，不在失败恢复中自动调用。本阶段只在临时测试实例验证 upgrade/downgrade，不执行任何正式降级，也不删除或重建正式业务表。

拟修改/新增文件限定为两个模型、BaseDAO、新迁移、`tests/test_base_dao_update_columns.py`、`tests/test_daily_basic_limit_status_storage.py` 和本文。测试不从待测方法生成 expected：SQL/类型依据当前生产者模型；结果用独立字面值和写入前数据库快照判断。旧业务字段样本包含 NULL、负值和固定时间戳。

真实 PostgreSQL 验证复用现有 `tests.wealth_watchlist_postgres_support.isolated_postgres` 的新建/停止临时实例能力，不调用其自选业务 seed，不接受已有数据库地址。已核实本机 PostgreSQL 18 与项目依赖可用，不安装或升级。临时实例、pytest cache、日志和审计输入统一放 `/private/tmp/daily-basic-stage1.*`；只使用少量人工记录，不连接 Prod、DG 或正式 Lake。

本阶段没有历史长任务：SQL 内存随一个批次变化，批次继续受现有 sync_batch_size 和绑定参数上限约束；按原默认 1,000、三个参数/行，仍为每批最多 1,000 行。失败由测试/调用方回滚；无独立状态或续跑机制可开发，不把第三阶段逻辑提前加入。功能测试与旧能力回归通过后，另做一次以本表硬要求为依据的审计，结果回填本节，不用测试总数替代逐项对账。

### 16.3 实现结果与实际验证

实现文件为：

- `src/foundation/models/raw/raw_daily_basic.py` 与 `src/foundation/models/core_serving/equity_daily_basic.py`：仅增加 Integer import 及可空的收盘涨跌状态 `limit_status`，没有 Python 默认值或数据库默认值。
- `alembic/versions/20261112_000188_add_daily_basic_limit_status.py`：接 `20261031_000187`，upgrade 只给两表各增加一列；本地迁移图现在只有新 head `20261112_000188`。没有执行正式库迁移。
- `src/foundation/dao/base_dao.py::BaseDAO.bulk_update_columns`：独立文本 SQL；按主键匹配已存在行，只写显式指定列；不同值才更新，累计实际 rowcount；沿用原批次计算，事务由调用方控制。旧方法、批次计算和既有调用方均未改动。
- 两个新增测试文件见下表。未修改既有测试预期，未新增生产配置、锁、线程、重试或异常兜底。

| 验证 | 实际范围与结果 | 证明的内容及限制 |
|---|---|---|
| 新方法单元测试 | `tests/test_base_dao_update_columns.py`：8 项通过；与原 BaseDAO/分批测试合跑共 15 项通过 | 参数绑定、0 值、复合主键、其他模型主键、非法列/主键拒绝、空输入、受参数上限约束的分批及真实 0 返回；会话是替身，不代替数据库验收 |
| 模型、迁移和真实 PostgreSQL | `tests/test_daily_basic_limit_status_storage.py`：4 项通过；使用本机已有 PostgreSQL 18.4 的临时实例，两表各 3 条人工旧结构记录 | 旧结构独立 DDL；升级后新增列为 NULL，原字段类型/空值规则/默认值、主键、索引及所有旧行不变；0 和 6 正确写入；相同代码不同日期不误改；不存在的键不插入；重放返回 0；全 NULL 更新仍可执行；指定列更新保留两表旧 18 列、原始载荷、采集时间与服务表创建/更新时间 |
| 真实事务与反向迁移 | 同一 PostgreSQL 测试 | 未提交更新可整体回滚，显式提交后可由新连接读回；第二表用测试专属约束故意失败后，两表均由调用方回滚；downgrade 后旧列/主键/索引/旧值不变，再 upgrade 新列为 NULL。只覆盖临时实例，不代表正式库或历史动作已执行 |
| 原 DAO、写入与结构回归 | 原 BaseDAO/分批、CCTV 新闻、重要新闻、新闻、行键、ETF 基础信息 DAO 及快照 writer、表模型 registry、DatasetDefinition registry、子系统依赖矩阵，共 108 项通过 | 现行写入能力和边界回归；不修改其输入、预期或调用方式 |
| 原应用消费者回归 | `tests/web/test_wealth_market_leaderboards_api.py`、`test_wealth_market_watchlist_api.py`、`test_quote_api.py`：98 项通过 | 使用现行内存 SQLite fixture 及增加新列后的 ORM，覆盖榜单、自选和行情接口的原字段、返回及行为；不是线上流量验证，也不代替 PostgreSQL 存储测试 |
| 静态与文档检查 | 本阶段 Python 文件的 Ruff 错误规则通过，三个新增文件全规则通过；与开工前文件对照确认存量文件没有新增 lint 问题；本文差异空白检查、`scripts/check_docs_integrity.py` 通过 | BaseDAO 原有 I001/UP046、原始表模型原有 RUF012 保持未改，不为消除旧提示重构上下文；静态/文档检查不扩张为后续阶段验收 |

上表共覆盖 218 项不同测试：新增单元 8＋存储 4＋原能力 108＋消费者 98；首次 15 项合跑中的 7 项原测试已包含在 108 项中，不重复计数。编写新增测试时曾修正跨测试模块导入导致的重复表注册，以及直接比较反射类型对象造成的结构误判；改为独立测试模型、比较实际 SQL 类型定义，没有删掉旧字段、事务或读回断言。

测试进程显式关闭仓库环境文件加载，pytest 的临时目录、缓存及 PostgreSQL 数据目录均在本任务 `/private/tmp` 下；实例已经停止。没有连接现有数据库、请求源接口、读取正式 Lake、写 Dagster 事件或安装依赖。沿用 §13 已核实的源字段证据，本阶段不重复联网。

### 16.4 开发完成后的独立审计

在开发和上述测试完成后，重新以 §5.2、§10.1 第一阶段及 §16.1 的要求检查代码差异、真实执行 SQL、读回值和原调用方，不以测试数量代替审计。结论：**第一阶段符合当前 LLD，未发现阻止本阶段验收的问题。**

| 审计项 | 逐项核对结果 |
|---|---|
| 是否影响旧能力 | 与开工前源文件逐项比较：移除本次新增的方法/字段/import 后，BaseDAO 和两模型的语法树与原文件完全一致。原三个批量写入方法、读取方法及分批 helper 原样保留；全文检索确认生产源码中只有新方法定义，没有迁移旧调用方 |
| 是否只改指定列 | 实际发给 PostgreSQL 的每条新方法 UPDATE，其 SET 均只有 `limit_status = incoming.limit_status`，代码/日期/状态均为绑定参数，额外输入 close 不进入 SQL；两表旧 18 列及全部系统列逐行与更新前记录一致 |
| 是否保留实际计数与事务 | SQL 用 `IS DISTINCT FROM` 排除同值和 NULL 同值；数据库读回与 2/0/1 的实际变更计数吻合。不存在的键没有插入；DAO 无 commit/rollback 或状态写入，第二表错误直接交给调用方处理 |
| 是否有多余设计 | 仅保留 LLD 要求的真实非主键列约束；没有增加重复键处理、源值校验、重试、额外状态、取消机制或 DG 防护。类型 CAST 只负责 PostgreSQL VALUES 参数类型，不承担收盘涨跌状态的业务检查 |
| 是否跨阶段或夸大验收 | DatasetDefinition/source_fields 仍是原 18 字段，normalizer、writer、Ops、API 与 DG 均未修改；§2 的正式数据事实没有刷新。本阶段不声称完整日更、历史任务取消/续跑或 DG 文件/事件已经验收 |

开工前用到 CodeGraph 的 explore/impact，覆盖 BaseDAO、继承 DAO、旧 writer、调用方与跨层边界；审计时补充直接源码及消费者测试核对，并在修改后执行 `codegraph sync` 和 status，索引正常。没有需要人工补判的第一阶段调用边界。后续仍按 §5.1、§10.2 协调完整发布：正式数据库先迁移，模型、19 字段请求和状态校验一起部署，不能单独部署本阶段模型。

第一阶段至此完成。本轮只修改 §16.2 限定文件并回填原文档，保留工作区其他改动，没有提交、部署或开展第二阶段开发。

## 17. 第二阶段实施与验收（2026-11-12）

### 17.1 本步目标、范围与开工依据

第一阶段已提交 `9fa2d3d6f`。管理员现已批准按 §10.1 第二阶段完成 Prod 日更与错误提示，并在开发后重新审计。本步落实 §4、§6.1、§6.6；不实现第三阶段 PLAN/APPLY、历史补录服务、有界传输新合同或动作注册，不修改 DG，不运行正式迁移、部署或正式数据任务。

开工前再次用 CodeGraph explore/node/impact 核对 normalizer→executor→writer、dispatcher 的普通维护/工作流/已注册维护三条异常路径及 worker。当前每日指标仍为 18 字段、无行转换、record_rejections、raw_core_upsert、逐 unit 提交；全部现行定义中 raw_core_upsert 与 fail_unit_on_any_rejection 的组合仍为空。已有转换只转换存在的日期/小数字段，不补缺列；状态不在 decimal_fields，因此能保留原生类型。源码中现有名称 DAO 没有批量名称查询，错误分支需要一次按样本代码限定的查询。

此前消费者核验继续适用，并在本步回归：source_fields 由 resolver/source client 传到每页 connector；row_transform_name 经 row_transforms.__all__ 进入 normalizer；reject_policy 在本步新增的 executor 组合中生效。手动表单、catalog、工作流定义、freshness、数据卡片、snapshot、日期/对象完整性、自动日期策略及前端时间控件继续消费原 date_model、input_model 和存储事实，不改变其事实字段。榜单、自选、Quote 的旧读取投影与返回不改。

| 编号 | 本步硬要求与实现位置 | 正向和反向验收 |
|---|---|---|
| S2-01 | market_equity.py 的完整字段清单追加状态；将同一清单提为本模块常量供 Definition 和行检查复用，不再维护第二份清单 | 独立字面 19 字段、所有分页 fields、原日期/过滤器/decimal_fields/表映射保持；缺任一业务列均拒绝，旧数值 NULL 仍允许 |
| S2-02 | row_transforms.py 登记 daily_basic_limit_status 并加入 __all__；codebook.py 登记状态 reason 与源校验失败 error | 0～6 原生 int 通过；NULL、bool、字符串、小数、越界失败，message 有原值类型和具体原因；负估值及原 NULL 不误拦 |
| S2-03 | executor.py 仅对严格策略与 raw_core_upsert 的组合，在 writer 前终止；只将源值校验错误统一为 normalize.source_validation_failed | 先提交 A，B 一条坏值时两表 writer 均不执行、C 不执行；已配置的日期/重复键错误保留原码和 cause；程序/连接异常不伪装成状态值错误；其他数据集部分拒绝保持原义 |
| S2-04 | 新错误携带 failed_unit、全部拒绝计数/有界样本及 committed_progress；dispatcher/worker 只为该码保留真实已提交量 | A 提交后 B 失败、观察状态写失败、当前节点失败时数量不归零；失败日期的源/拒绝量不算已提交；普通旧错误及第一阶段旧维护回归不变 |
| S2-05 | dispatcher 三种入口共用一个私有错误展示方法，复用现有 issue、详情 API/UI | 日期、股票代码/当前名称、字段、原值/类型/原因可读；无代码/名称缺失有明确提示；一次有界名称查询；错误 technical_payload 保存完整结构，不新增 API 字段 |
| S2-06 | 工作流遇该码立即 failed，不服从 continue_on_error；当前节点失败、先前成功节点保持成功 | 已有成功步骤与允许继续均停止后续步骤；任务 unit_done 是成功步骤数，失败步骤的日期数量留在节点诊断；行数为前面步骤加本步骤已提交量一次 |
| S2-07 | 源说明、通用模板与本专项同步；仅调整第一阶段“当前仍 18 字段”的阶段性断言 | 迁移夹具仍为真实旧 18 字段；新 19 字段正常写入用隔离 PostgreSQL 验收；原 DAO、业务读取和 Ops 入口回归保持 |

### 17.2 具体实现与边界

字段清单在现有 `market_equity.py` 中定义一次，Definition 和专用行检查共同引用；不新增跨工程 import、配置项或通用策略。行检查只判断完整列存在和状态值，不增加本数据集原来未启用的日期/重复键规则，不改变原日期、小数转换或主键。专用行检查抛现有 RowTransformReject；executor 在现有归一化后、raise_if_all_rejected/writer 前拒绝整个日期。正常日更仍使用原 bulk_upsert，第一阶段指定列方法不接入日更。

新源校验异常的 details 保存 dataset_key、unit_id、trade_date、unit_total、rows_fetched、rows_rejected、rejected_reasons、rejected_samples、failed_unit；直接抛出的已知源校验错误另保存 original_error。_record_unit_exception 回滚当前未提交日期后，仅为新错误补充本次 _RunState 的 committed_progress：unit_done、rows_fetched/written/committed/rejected/deduplicated、原诊断及原因统计。未返回的失败日期不混入该累计。未知行转换、程序异常和连接错误继续使用既有错误路径。

dispatcher 的名称展示方法只在三个异常分支 rollback 后调用、恢复进度和写 issue 之前执行。用现有 Session 的 begin_nested 包住一次 Security.ts_code/name 查询，以便名称查询失败时仅回滚该查询、保留原校验错误；不另建连接、线程、重试或名称缓存。SQLAlchemy 的 begin_nested 会先 flush，故调用顺序保证查询前没有待保存的进度/issue 变更。查询失败按 §6.6 显示名称未找到，不能盖掉源错误。三个分支只有该新增 error_code 改用详细提示，其余错误的代码、提示及收尾保持。

普通维护恢复日期成功量；工作流分别累计成功步骤与本步骤已提交行数，失败步骤的日期数量放当前节点既有诊断，不把日期数写入工作流 unit_done。worker 对该码在 failed 终态保留旧观察值与异常返回数量的较大者，沿用既有当前节点收尾，不将全工作流数量复制给失败节点。

本步文件清单：`src/foundation/datasets/definitions/market_equity.py`、`src/foundation/ingestion/row_transforms.py`、`codebook.py`、`executor.py`、`src/ops/runtime/task_run_dispatcher.py`、`worker.py`；新增 `tests/test_daily_basic_limit_status.py`、`tests/test_daily_basic_limit_status_postgres.py`、`tests/web/test_daily_basic_limit_status_runtime.py`，调整 `tests/test_daily_basic_limit_status_storage.py` 的阶段性字段断言；更新本文、`docs/templates/dataset-development-template.md` 和原 `0032_每日指标.md`。没有新的配置、动作、接口、表或迁移。

### 17.3 验证资源、成本和独立审计方法

沿用 §13 完整字段及分页证据；本轮已再次通过 MCP 获取 000001.SZ、20261110 的完整 19 字段一行，状态为原生 int 4、收盘价 11.86。该样本只是有界接入证据，不外推历史。正常请求数量、每页 6,000、原 SQL 批次和逐日期事务均不变；仅已有归一化循环追加列存在/状态检查。拒绝统计仍覆盖全部坏行，诊断仍复用每 reason 最多 3 个样本和单值文本 240 字符；错误展示仅查这批有限样本的名称一次。SAVEPOINT 的建立、释放或回滚不增加数据查询范围。没有专项耗时或峰值测量，不虚构新的预算、上限或性能保证。

测试和临时审计只使用 `/private/tmp/daily-basic-stage2.*`；SQLite 使用独立内存资源，PostgreSQL 复用已安装套件和现有临时实例 helper，完成后停止清理，不连接已有数据库。按完整源样本经过真实 normalizer/writer 写入隔离两表，独立读回 19 字段；事务反例覆盖坏日期零写入及前日保留。再验证真实 dispatcher/worker/详情 API 的错误与进度，源网络层允许替身但不得把它称为真实联网验收。若复用现行项目 connector 做有界真实请求，只取上述一个代码和日期。

先跑本步正反用例、第一阶段和原拒绝策略/Ops 回归，再跑 Definition/resolver、codebook、依赖边界和原应用消费者门禁。开发完成后另按 S2-01～07 审查最终差异、SQL/数据库结果、工作流计数和错误范围；实际结果回填本节，不因既有 295 项基线通过就宣称第二阶段完成。

### 17.4 实现结果与实际验证

本步已按 §17.2 清单落地。Definition 只改完整字段、行检查名称及拒绝策略三个事实；完整清单只在 market_equity.py 定义一次。normalizer、source client、request builder、writer、DAO、模型、迁移、动作目录和 API/schema 源码未改。普通维护、工作流及已注册维护动作共用 dispatcher 私有提示方法；后者只增加新错误的展示支持，没有提前注册第三阶段历史动作。

| 验证 | 实际结果与范围 | 证据边界 |
|---|---|---|
| 新字段/归一化/执行单元 | `tests/test_daily_basic_limit_status.py`，47 项通过 | 独立源样本的完整 19 列、0～6、NULL/bool/字符串/小数/越界、全部缺列反例、负估值/旧 NULL、样本计数、全部分页 fields；前日已提交/次日坏行/后日停止；原日期/重复键错误保留 cause；程序及连接错误不改成状态值错误；其他数据集仍可按旧策略部分拒绝。网络与 writer 在该组中由替身隔离 |
| 任务运行、工作流和详情 | `tests/web/test_daily_basic_limit_status_runtime.py`，13 项通过 | 真实 resolver/normalizer/writer/dispatcher/worker 与内存 SQLite；健康区间三日期四行成功，包含状态 0/6、数值变化和旧负值/NULL；坏日无双表写入、先前提交保留；观察失败仍保留数量；错误经原 view 和问题详情接口可读；名称缺失/查询失败及无代码提示。网络 fetch 是替身；工作流先前步骤用独立字面计数替代，不声称其他数据集的完整同步已验收 |
| PostgreSQL 日更与名称查询 | `tests/test_daily_basic_limit_status_postgres.py`，2 项通过 | 原生 PostgreSQL 上使用真实 normalizer/writer：合法日保留，坏日和后日不写；人工约束使第二表失败时第一表同日回滚；不存在的名称表产生真实 SQL 错误后，SAVEPOINT 回滚、原错误和外层 Session 可用。约束与缺表仅存在于临时测试资源 |
| 第一阶段回归 | 指定列/原 BaseDAO/分批 15 项；原存储验收 4 项，均通过 | 旧 18 字段迁移夹具、两表 upgrade/downgrade、原列/时间戳、主键/索引、指定列 0/幂等/事务仍通过；阶段性字段断言按已批准的新合同调整为完整 19 列 |
| 原策略与 Ops 门禁 | Definition/resolver、normalizer/source client、进度、旧维护、依赖边界/runtime/codebook、TaskRun API 与手动入口，共 343 项通过 | 原消费者和运行语义的回归；普通工作流原 fail_fast/continue_on_error 的 partial_success 反例另在新任务链测试中直接验证 |
| 业务读取 | 榜单、自选、Quote 原 API 测试 98 项通过 | 原字段、返回、排序和读取行为；使用既有隔离数据库 fixture，不是线上流量或浏览器验收 |
| 静态检查 | 新增测试文件完整 Ruff 通过；变更 Python 文件错误规则通过；与开工前代码对照无新增 lint 提示；Definition lint、文档完整性及差异空白检查通过 | 存量样式提示不顺手清理；静态通过不代表生产操作验收 |

去重共 522 项测试：47＋13＋2＋15＋4＋343＋98。综合合跑先通过 521 项，开发后审计补齐健康区间正例后，任务链测试文件 13 项通过；其中原有的 12 项不重复计数。没有跳过失败或修改旧业务预期来凑通过。

真实接入另经现行项目 `DatasetSourceClient→TushareSourceConnector→TushareHttpClient` 完成一次逻辑请求：000001.SZ、20261110，完整 19 业务列，一行短页终止。与本轮 MCP 一行样本全部业务值一致。归一化一行、拒绝零行；将这份已下载响应交给真实 executor/writer，不再请求来源，隔离 PostgreSQL 原始表和服务表各新增一行，written/committed 均为 1，独立字面预期读回全部 19 值一致（状态 4、收盘价 11.8600）。这证明有界真实来源到隔离存储的接入，不证明 Prod 部署或全市场历史已执行。

初次任务链测试错误地给股票基础信息使用日期区间，并假定 view 直接包含完整技术载荷；依据现行代码改用支持交易日期的其他工作流步骤，并从原问题详情接口验证完整结构，未修改产品接口。错误值长度反例说明见下节。正式数据库、正式 Lake、Dagster 事件均未读取或写入，没有安装依赖；临时 PostgreSQL 实例已停止，临时输入、缓存及日志在回填后清理。

### 17.5 开发后的独立审计与阶段结论

开发完成后重新审阅最终差异、当前调用链和测试证据，逐条对照 S2-01～07；不以用例数量代替实现审计。结论：**第二阶段符合本 LLD，未发现尚未解决、阻止本阶段验收的问题。**

- **S2-01/02：** 对照开工前全部市场股票定义，除每日指标 source_fields、row_transform_name、reject_policy 三项外完全一致；同一清单供请求与行检查引用。状态不经 Decimal/int 强转或补值。审计发现原先将类型提示放在原值之后，长字符串会在已有 240 字符截断时丢掉类型；先用 300 字符错误输入证明失败，再仅调整提示顺序，反例通过，没有增加新限制。
- **S2-03/04：** writer 调用前失败，已提交数量只取 _RunState；坏日数量留在 failed_unit/有界样本，不混入提交量。观察失败仍有业务提交与异常快照。原 DAO、writer、模型、迁移完全未改，旧方法没有迁移到指定列更新；已有行转换和不在本步范围的方法语法树保持一致。
- **S2-05/06：** 三个异常分支均在 rollback 后、恢复观察状态/写 issue 前查名称；真实 PostgreSQL 错误证明不会污染外层事务。工作流测试的前两步骤合计读取 7、保存 5、拒绝 2，加本步骤已提交的 1 行后最终为 8/6/2；成功步骤数 2 与失败步骤已提交日期数 1 分别保存，没有重复加总或把全任务 6 行复制给失败节点。旧普通错误仍保留原 partial_success/继续策略。
- **S2-07 与影响面：** 源资料和通用模板同步，旧 18 字段夹具保留；原应用 98 项回归通过。CodeGraph explore/node/impact 覆盖本步 executor、继承调用链及 dispatcher/worker、原消费者；修改后 sync/status 正常，直接代码审计补足字符串注册和测试关系。没有新增反向依赖、配置、线程、锁、恢复表或其他数据集特例。

本轮只完成第二阶段，未部署或批准正式迁移；第三阶段历史补录和 DG 两阶段继续按原设计和授权边界推进。正式发布仍必须先迁移数据库，再配套发布模型、19 字段请求与严格校验；本次通过不能代替 §10.2 的正式执行验收。

## 18. 第三阶段实施与验收（2026-11-12）

### 18.1 开工范围及代码依据

管理员已批准严格按 §5.3、§6.2～6.8、§9、§10.1 第三阶段开发并在完成后独立审计。§6.7 两处配置与进度传递补充已提交 `07db15253`。本步只开发 Prod 历史补录及隔离验收，不部署、不执行正式迁移、正式 PLAN/APPLY 或全历史读取，不修改 DG、日常同步、Definition 日期模型或原业务 API。

开工前 CodeGraph explore/impact 已覆盖维护协议、dispatcher 重放、有界 client/connector 和旧公告、股票周线、指数周期线消费者；另核对 resolver、日期 request builder、normalizer、两表模型、新 DAO、动作目录、worker factory 及现有隔离 PostgreSQL 测试。当前 resolver 已生成每日日期和源参数；两层有界合同尚无 `daily_basic/v1`；APPLY 只传日期 unit，冻结配置按 §6.7 读取。独立观察更新只写阶段和当前对象，数量仍由原 dispatcher 累计。未发现需要改变共享协议、旧转换或旧写入方法的前提。

本轮再次经 MCP 查询 `000001.SZ/20261110` 完整 19 字段，返回一行、状态为原生整数 4，与 §17 的样本一致。新测试沿用该完整字面样本；其他代码、日期、错误值及目标旧值明确是人工小样，不作为额外源端事实。

### 18.2 硬要求、实现位置与验收

| 编号 | 必须落实的口径 | 代码位置及正反验收 |
|---|---|---|
| S3-01 | 人工 PLAN/APPLY、显式 PLAN 起止、原计划重放，不能绕开上下文或自动调度 | 新 app 适配器、action_catalog、worker factory；缺日期不可冻结，草稿不可 APPLY，无上下文入口拒绝，旧动作注册保持；字节限制要求已由 §19 取消 |
| S3-02 | resolver 负责日期和源参数；两表各一次日期计数聚合，不持有历史业务明细 | Foundation 新服务；真实小样日历与两表计数、缺日/计数不符、取消草稿与完整冻结 |
| S3-03 | 完整 19 字段、每页 6,000、最多 `floor(目标计数/6000)+1` 页，当前日期有界驻留 | 新服务、client 与底层有界合同；整页空末页、短页、额外源代码说明、缺目标、重复键、错日期、无效状态及旧三类合同回归 |
| S3-04 | 日期索引读取服务表，按复合主键批量匹配原始表；已完整一致可跳过，冲突停止 | 新服务；真实 PostgreSQL 核对正常 NULL、部分已补、全补跳过及非空冲突；SQL 不对原始表逐日无主键扫描 |
| S3-05 | 只改新增列；双表单日独立事务；成功无整日回读；提交未确认就停止 | 新服务与现有 bulk_update_columns；旧 18 列/系统列原值、第二表失败回滚、前日提交保留、实际变更量和覆盖量分开、提交异常不报成功 |
| S3-06 | 使用原 PLAN 冻结配置，DAO 独立 Settings 副本；逐批一条 SQL、20 秒 SQL/2 秒观察超时 | 新适配器及服务；运行配置调高/调低、绑定参数批次、全局配置与旧方法不变；沿用原配置依据，不新增 env 或配置表 |
| S3-07 | 现有请求等待循环检查取消/每 5 秒观察；SQL 前后检查；取消不领取新日期；原 PLAN 可续跑 | 新服务及适配器；请求中取消、SQL 等锁超时、日期提交后取消、退出后新实例续跑、幂等重放 |
| S3-08 | 处理中不增加已保存量，完成只由 dispatcher 累计一次；状态失败不撤销业务；任务/节点终态一致 | 新适配器及原 dispatcher/worker；多次回调、连续日期、重试不带旧累计、观察失败、提交后状态失败与真实读回 |

按已有配置来源注册 `source_timeout_seconds=30`、`statement_timeout_seconds=20`、`observation_timeout_seconds=2`、`progress_interval_seconds=5`。第三阶段最初还注册了 `max_response_bytes=None` 并在未给值时拒绝冻结，现已按 §19 删除该配置与检查。消费者是新适配器及其注入的新服务/有界调用，生效方式、取值来源与可见性沿用 §6.2。SQL 批次仍来自现行 Settings 并冻结；不增加任意列、代码池或源参数运营输入。包版本只记入计划追溯，不作为重试条件。

新 Foundation 服务输出日期描述、计数与每日期结果；app 只适配维护协议、配置注入和 TaskRun 观察，不承载匹配、分页或写表规则。新服务复用 normalizer 的完整字段与状态检查，坏行使用已登记的 `normalize.source_validation_failed` 及样本结构，交给第二阶段已完成的名称查询/错误展示。错日期及重复主键复用 `normalize.unit_date_mismatch`、`normalize.batch_unique_key_duplicate`，同时登记为样本原因供详情展示。目标计数/键/状态冲突登记 `daily_basic_limit_status.target_mismatch`，分页未结束登记 `daily_basic_limit_status.pagination_incomplete`，提交未确认登记 `daily_basic_limit_status.commit_unconfirmed`；新传输合同登记 `daily_basic.delivery_contract_mismatch/source_payload_invalid/source_deadline_exceeded/response_size_exceeded`，既有错误行为不改。

### 18.3 读写、恢复及验证边界

覆盖量按本日逻辑记录数计一次，实际变更量分别记录两表 UPDATE 行数，已相同的 0 不是失败。读取时仅保留日期计数和当前日期键/状态；服务表读取后按主键匹配原始表，源读取结束才开启双表更新事务。正常路径不增加成功后回读；跳过、重试与最终测试验收读回依 §6.4。恢复使用同一冻结 PLAN，不设新 checkpoint 表或后台确认机制。

正常、重试和最终验收开销沿用 §6.7、§8：PLAN 两表各一次计数聚合；执行每日期读取一次当前 APPLY 字段及原 PLAN 所需配置、两表当前键/状态，未完成日期按冻结页数读取源并逐批更新；重试最坏复核全部计划日期；隔离验收另读回样本完整旧列与新增列。没有本专项耗时、峰值内存或字节实测，不新增测量门禁或无依据上限。测试中的字节值由人工响应内容大小推导，只约束临时测试资源，不转为正式默认值。

使用已有虚拟环境与临时 PostgreSQL，全部数据库、HTTP 替身、日志和 pytest 缓存置于 `/private/tmp`。先做本步正反与真实 PostgreSQL/loopback HTTP 链路，再跑旧有界合同、DAO、每日指标、维护任务、动作/API 消费者和架构门禁。完成后独立重读最终差异并按 S3-01～08 对账；正式运行—取消—续跑及页面生产验收仍须 §10.2 的后续授权，不用隔离通过替代。

### 18.4 实现结果与实际验证

本节保留第三阶段最初的验收记录；其中响应字节限制及其拒绝用例已由管理员在 §19 要求取消，当前执行口径以 §6、§19 为准。

本步新增 Foundation 补录服务和 app 维护适配器，在动作目录与 general worker 注册；两层有界传输增加每日指标合同，codebook 增加对应错误及原因说明。未修改 DAO、两表模型、迁移、Definition、resolver、request builder、normalizer、正常 executor/writer、dispatcher、worker 主循环、业务 API 或 DG。

| 验证组 | 实际结果 | 证明范围及限制 |
|---|---|---|
| 补录业务与 PostgreSQL | `tests/test_daily_basic_limit_status_backfill.py`，24 项通过 | 两日期、每日期两股票的人工目标；完整 19 字段来源样本经 normalizer，只改新增列。独立读回全部旧列/系统列不变、0 合法、部分已补、全补跳过、额外源代码说明、缺字段/缺代码/重复/错日期/空源/坏状态拒绝、相同数量但不同主键拒绝、第二表失败回滚、提交回执丢失停止、SQL 等锁超时后取消。源 I/O 在本组用替身 |
| 有界源传输与最小完整链路 | `tests/test_daily_basic_limit_status_transport.py`，8 项通过 | 真实 loopback HTTP/子进程/client/connector；完整字段及原生 int、错绑定拒绝、字节超限、坏 JSON、等待中取消/截止及清理、短页/整页空末页/冻结页数拒绝。另以观察来源的两行人工小样打通 HTTP→有界 connector→服务→normalizer→临时 PostgreSQL 双表更新，源/归一化/匹配/覆盖均为 2，拒绝 0，两表各实际变更 2。HTTP 服务是替身，不声称全历史真实联网验收 |
| 维护运行与 HTTP 详情 | `tests/web/test_daily_basic_limit_status_maintenance_api.py`，10 项通过 | 真实 PLAN 草稿/冻结/hash/replay、dispatcher/worker、状态与 HTTP schema；提交首日后取消保留 2 行，未提交节点为 0；新 APPLY 跳过首日后覆盖量为 4，不加上旧任务的 2；多次回调显示 0/2 而非重复增加，日期节点分别为 2/2。观察失败不撤销业务；状态保存失败仍保留首日。实际子进程在提交前/后退出，分别回滚/保留，再由新进程对象按原计划完成。认证、源网络在本组隔离；HTTP 验收不是浏览器或生产页面验收 |
| 相关能力与架构合跑 | 577 项通过，12 项旧集成用例跳过，1 项存量检查失败；上述 42 项包含在 577 中 | 覆盖旧公告/股票周线/指数周期线有界调用、DAO、日更、维护进度、Definition/resolver、目录/API 与分层/runtime/codebook。12 项要求其自身专用 PostgreSQL 环境，本轮未提供该环境；新动作的真实 PostgreSQL 用例均已执行。按管理员免测决定排除 1 项大响应性能测量，不修改或跳过失败断言 |
| 既有业务使用方 | Quote、榜单、自选原 API 测试 98 项通过 | `test_quote_api.py`、`test_wealth_market_watchlist_api.py`、`test_wealth_market_leaderboards_api.py`；使用原隔离 fixture。与上述 577 项无重叠，合计 675 项通过，不是线上验收 |
| 静态及文档 | 新增五个 Python 文件完整 Ruff、全部变更 Python 文件错误规则、Definition lint、文档完整性和差异检查通过 | 只证明对应静态/文档边界，不替代业务、部署或正式数据验证 |

存量失败为 `test_active_code_does_not_reference_legacy_dataset_run_names`：命中 `src/ops/runtime/announcement_archive/supervisor.py` 中的 `archive_execution_failed`，以及 `src/ops/services/task_run_service.py` 中的 `_freeze_dataset_execution_payload`。两文件均逐字节与开工 HEAD 一致，用相同扫描函数读取 HEAD 也得到相同命中；本步没有引入这些名称，不修改无关实现或放宽检查。因此不能报告“全仓门禁全绿”。

首次合跑还发现 Foundation 的日期回调命名为 checkpoint，错误带入 Ops 检查点概念；现改为 `on_batch`，Foundation 只报告日期批次，适配器调用既有 Ops 草稿保存能力，分层检查已通过。旧连续慢响应清理测试首次出现子进程尚未结束的断言，定向及最终完整复跑均通过；未修改共享清理代码、断言或时间限制。最终结果以上表为准。

### 18.5 开发后的独立审计

实现完成后重新按 §5.3、§6.2～6.8 和 S3-01～08 审查当前代码、SQL、数据库读回、调用方与最终测试，不以测试数量替代设计对账：

- **S3-01/02：** 只为人工维护注册新动作；普通无上下文方法拒绝。实际 resolver 负责日期和请求参数，两表各一次聚合计数，日期描述按已有批次保存草稿，取消草稿不可 APPLY，完整计划才能冻结。共享重放协议、日期模型与调度入口未变。
- **S3-03/04：** 两层均要求每日指标接口及完整 19 字段；业务验证后才匹配现有目标。服务表按日期查，原始表 SQL 带复合主键 IN；冻结计数及键匹配共同判断目标完整性。已完整一致的日期不请求源；NULL 继续，非法/冲突值停止，不自动纠错。
- **S3-05/06：** 源读取期间没有保持双表更新事务；两表同日提交。指定列方法仍是第一阶段原实现，实际 SQL 只更新新增列，正常成功后无整日业务回读。当前批次调低或调高均仍用原计划冻结值，专用 Settings 副本未修改共享配置；SQL 子批次按同一绑定参数算法，每次一条更新语句。提交异常停止，恢复时才重新判定业务值。
- **S3-07/08：** 使用已有等待循环取消/tick 和独立取消查询；SQL 前后观察，SQL 失败先结束本日事务，再辨认已请求的取消；普通数据库错误仍保留原因。进度写入仅改阶段/日期/页/更新时间，不改完成数量；确定提交后立即把本日结果交回原 dispatcher 累计一次。正常执行、取消、进程退出和观察失败后，均以实际两表状态续跑，不依赖上次任务计数。
- **旧能力：** 独立 AST 对照排除新增每日指标分支后，两层 client 的原代码结构与 HEAD 完全一致；DAO、Definition、normalizer、executor、request builder、dispatcher、worker 和前端详情页面逐字节未改。旧三类有界合同、正常日更、原 API 及使用方回归均覆盖；没有 foundation 向 Ops/App 的反向依赖，也没有新线程、锁、恢复表、worker 或配置服务。

结论：**第三阶段符合本 LLD 的开发范围与隔离验收目标，未发现本阶段尚未解决的实现问题；扩大检查中的一项存量扫描失败单独保留，不算本阶段引入的问题，也不隐去。** CodeGraph explore/impact 及开发后 sync/status 已覆盖新服务、维护组合与旧传输消费者；索引正常。

第三阶段最初交付仅完成开发及隔离验收，未包含生产操作；后续部署核验与字节限制修订见 §19。正式补录仍需按 §10.2 完成生产小样运行—取消—续跑—读回及历史范围批准，字节限额不再是准备项。DG 第四、第五阶段尚未实施。测试只用现有套件，临时资源在结果回填后停止清理，不留下重复过程报告。

## 19. 取消每日指标补录的响应字节限制（2026-11-12）

### 19.1 原因、范围及开工依据

2026-11-12 14:50（北京时间）只读审计已核实 Prod 为 `d4e9a038f`、迁移为 `20261112_000188`，九个服务运行、两表新列及完整 19 字段来源读取符合预期。该次审计未触发正式任务；最新每日指标仍为 11 月 11 日、5,574 行，新增列尚未补齐。以下取消字节限制是部署后的新修订，不能据此前部署记录宣称已经生效。

管理员明确要求取消 `max_response_bytes` 限制。最初为复用现有可终止 HTTP 接收器，沿用了其逐块字节检查，并将没有配置上限视为禁止冻结 PLAN；这使每日指标补录需要先指定一个额外数值。此次取消这一操作前提及实际字节拦截，不换成隐藏默认值，不扩充配置界面或资源管理机制。

本轮只修改每日指标补录的动作注册配置、PLAN 配置提取、服务调用和共享接收器中的每日指标合同分支，以及对应测试。新 PLAN 的冻结配置不再包含字节上限；APPLY 不再读取此值。下载仍使用 `daily_basic/v1` 完整 19 字段合同、原有可取消等待循环及源调用截止；原始表/服务表、逐日事务、分页、状态校验、进度与原 PLAN 续跑均不变。不部署、不创建正式任务或写正式数据，不修改 DG。

CodeGraph impact 已核对两个 client、connector、新历史服务及公告、股票周线、指数周期线调用方；共享 `maximum` 参数仍由旧调用方传入实际上限，签名不变。新服务固定传 `maximum=None`，接收器仅对 `daily_basic/v1` 跳过逐块字节数比较；其他合同原条件、异常和取消清理不变。已有响应结构、编码和接口/字段绑定检查仍保持原行为，本次不重做错误分类。

### 19.2 实现位置、配置、失败及验收

| 要求 | 实现位置与验收 |
|---|---|
| 没有字节配置也能冻结并执行 | action_catalog 删除该配置，适配器删除提取及必填判断，服务不再读取它；以原始注册配置在临时 PostgreSQL 完成 PLAN/APPLY，断言冻结配置无该字段、覆盖量正确 |
| 实际接收不再因字节数拒绝每日指标 | 共享接收器只对该合同跳过字节比较；loopback HTTP 同时验证 `maximum=None` 和响应大于旧传入值时均能正常解码，坏 JSON 仍拒绝 |
| 旧数据集限制不变 | 公告、股票周线、指数周期线在相同小上限下仍报告各自超限错误；原有有界传输回归继续执行，不放宽旧断言 |
| 原有取消、期限及数据语义不变 | 保留源等待取消/截止、分页完整性、两表事务、状态校验、SQL 子批次、观察失败与续跑用例；复用同日已核实的真实 19 字段样本，不重复请求全市场或全历史 |

没有新增配置或状态实体，也不改其他 Settings。删除的字节参数不再是正式执行前置条件；日期范围、正常预算、运行—取消—续跑的小样及正式写入批准仍按 §10.2 推进。本轮单日驻留和请求量规则不变，但取消字节限制后不再宣称有单页字节上界；峰值内存仍未测量，不增加专项测量门禁。

测试全部使用既有依赖、临时 PostgreSQL 与本机 HTTP；缓存、日志和临时资源放在 `/private/tmp`。开发后核对改动范围、共享分支、配置引用和原 LLD 对账，再回填结果。此前 §13、§15、§18 中有关管理员给定响应字节上限、未给值拒绝 PLAN 的旧要求均已被本节替代；原历史验证记录保留，不再作为当前执行限制。

### 19.3 实现、验证及开发后复核

产品代码只改四处：动作注册删除 `max_response_bytes`；适配器删除该配置提取与必填校验；新服务固定传 `maximum=None`；接收器仅对 `daily_basic/v1` 跳过字节比较。没有换成其他默认上限，也没有扩大到其他合同。调用签名、完整字段、正常同步、事务、进度和取消机制保持原样。

新增“不配置字节上限也能 PLAN/APPLY”的 PostgreSQL 回归先在旧代码上失败，失败位置为原 PLAN 未能成功冻结；修改后正常通过。当前三组每日指标补录测试共 46 项：业务 PostgreSQL 24 项、传输 11 项、维护/HTTP 11 项。维护测试直接使用原始注册配置，未注入字节值；冻结计划不包含该字段，服务请求的 maximum 为 None。真实 loopback HTTP 同时验证无上限、大于旧传入字节值仍可解码、错误 JSON 仍拒绝；三个旧合同仍在小上限处停止接收。

| 检查 | 本轮结果与证据范围 |
|---|---|
| 每日指标及旧接收器 | 71 项通过，包含上述 46 项；按已定免测决定排除 1 项大响应性能测量。真实源样本沿用同日已核实的完整 19 字段，不发起新的全市场/全历史请求 |
| Definition/resolver、分层/runtime/codebook、公告、指数周期线、维护进度 | 255 项通过，12 项原集成用例因其自身专用 PostgreSQL 未配置而跳过。新补录及指数周期线所需临时 PostgreSQL 均实际运行 |
| 独立源码复核 | AST 对照确认共享接收器与 HEAD 只有每日指标字节比较条件不同，其他合同和清理代码结构不变；该动作生产代码中已无 max_response_bytes 引用。CodeGraph impact、sync/status 覆盖两层 client/connector、服务及三类旧调用方，索引正常 |
| 静态与文档 | 新改测试/适配器/服务完整 Ruff、全部变更 Python 错误规则、Definition lint、文档完整性及差异检查通过 |

去重合计 326 项通过，12 项原集成用例跳过，没有修改旧数据集的字节限制断言。首次补充回归误用了不允许本机端口的执行环境，28 项指数周期线用例在临时库初始化时被阻止；改用前轮已有的本机测试执行方式后全组通过，未改代码或断言掩盖该执行错误。

复核结论：本轮落实管理员要求，去除了每日指标补录的字节配置前提与实际字节拦截，其他数据集的原有限制保持有效。Prod 小样前不再需要给定此参数；其他执行批准按 §10.2 不变。本修订尚未提交或部署，没有操作正式数据；测试临时资源在记录后清理。

## 20. 第三阶段生产小样：执行方案与 LLD（2026-11-12）

### 20.1 本步批准、范围与执行前核对

管理员在确认 Prod 已部署后批准“按照 LLD 完成第三阶段”，承接上一轮明确的两交易日 PLAN/APPLY、完成一天后取消、原 PLAN 续跑及两表读回。本步限定 `2010-01-04`、`2010-01-05`，不执行全历史补录、普通日更、DG 开发/写入、服务重启或配置变更。全历史仍按 §10.2 P3 独立批准。

本日部署只读验收为 `4f41388fb`：两个健康接口正常；技术指标实际安装文件与源码一致，之前缺配置字段的启动问题已消除。执行前再次只读核实迁移 `20261112_000188`，两表 `limit_status` 均为可空 integer、无默认值；原始表复合主键及服务表日期索引保持。SSE 日历两天均开市，服务表分别 1,632、1,630 行，新增列非空数均为 0；当时无 queued/running/canceling 任务，也没有本动作既有任务。

配置来自 Prod 现行注册与 Settings：SQL 批次 1,000，分页 6,000，源调用 30 秒、SQL 20 秒、观察查询 2 秒、进度 5 秒；不设响应字节限额，不改参数或新增开关。当前有效管理员标识为 1，用于已有命令服务的请求归属，不获取或伪造登录凭据。

开工前已使用 CodeGraph explore 核对维护适配器、dispatcher 和现行 TaskRun 协议，直接阅读命令服务创建/取消/重试、worker 领取与节点累计、原 PLAN 重放及两表执行实现。正式任务只通过 `TaskRunCommandService.create_task_run/request_cancel/retry_task_run` 创建与控制，由现有通用 worker 执行；不直接调用更新 DAO、不另起 worker、不拦截或替换执行方法、不手写业务 UPDATE。

### 20.2 执行、失败与继续

| 步骤 | 实现与验收 |
| --- | --- |
| 写前记录 | 只读投影两日服务表全部现有列；按这些主键分批读取原始表全部现有列。分别保存主键、除 limit_status 外所有列的 SHA256、状态计数；包括原 18 个业务字段、原始载荷/抓取时间及服务表创建/更新时间。只输出摘要，不导出业务明细 |
| PLAN | 创建本动作、显式两日起止的 PLAN，等待原 worker 成功冻结。核对 2 个日期、两表逐日计数、完整 19 字段、仅更新 limit_status、冻结配置无字节参数；保存 TaskRun id 与 plan_hash。失败或不一致则停止，不创建 APPLY |
| APPLY 与取消 | 引用该 PLAN 创建 APPLY；观察仅查询本任务的状态、完成日期数、行数及节点。在完成量首次为 1 时调用已有 request_cancel，等待终态；预计保留首日 1,632 行覆盖，第二日未提交，TaskRun 与活动节点均 canceled。观察循环的 100 毫秒间隔仅是本次执行刷新选择，不是取消时限或保证；若任务已完成两天，如实记为取消未验收，不改回数据或暗中扩大日期 |
| 取消后读回 | 重读同样两日，比较原列与主键摘要不变；首日两表状态完整且一致、次日仍为 NULL，已提交数量保留。存在冲突或非预期写入即停止，不清表或重置新增列 |
| 原 PLAN 续跑 | 通过 retry_task_run 重试已取消 APPLY，新 TaskRun 仍引用原 PLAN/hash；首日识别完整并跳过，次日正常补齐。目标覆盖为 3,262，源端新增读取应只计次日 1,630；读回两表及所有原列摘要 |
| 幂等重放 | 再创建一个引用相同 PLAN 的 APPLY；两天均完整跳过，rows_fetched=0，两表 changed=0，rows_saved=3,262 表示覆盖量。再次读回，验证没有重复写入或改动原字段 |
| 独立源核对 | 复用冻结 unit 的 request_params/page_limit 与完整 19 字段，通过真实 Tushare client 读取这两日；不使用待测归一化方法生成预期。直接检查日期、唯一代码、状态原生整数 0～6，并逐主键与最终两表状态比较 |

只操作本次创建的任务；控制观察使用独立短事务，不能与两表业务事务共用。各阶段都等待前一任务终态才推进。断连或提交结果不明时停止后续创建，记录已输出/已持久化的任务 ID；先读回这些任务及原 PLAN，按现有机制继续，不自动重复创建或把未确认提交当成失败。任务本身仍遵守 §6.8 的取消和提交规则；不修改 worker/scheduler 运行状态。

### 20.3 读取、请求及最后验收开销

本次每表目标为 `1,632+1,630=3,262` 行，两表合计 6,524 行；不是全历史读取。每次读回按服务表日期索引及原始表复合主键查询，批次 1,000，两日各为 2 个原始表批次。写前、取消后、续跑后及重放后共 4 次记录摘要，合计返回 `6,524×4=26,096` 条表记录；独立源核对另按日期索引只读 3,262 个目标代码，以目标主键集合过滤并单列源端额外代码，合计 29,358 条记录结果，不把它当作磁盘实际读取量或独立股票数。PLAN 沿用两次日期计数聚合，其中原始表会扫描计数；计数不是明细导出，不重复做全历史校验。

两日均少于 6,000 行，每个日期一次完整源页。首次 APPLY 至多发起两页（取消可能已进入第二日），续跑只需次日一页，幂等重放零页，独立核对两页，合计至多 5 次源调用；如产生未预期分页/重试先停止核对原因。业务更新每日期、每表各 2 个 SQL 批次，两天共 8 次更新 SQL；最终实际数量依首次取消位置记录，不虚构执行耗时或峰值字节保证。内存只处理所选日期，摘要按日生成；单日两表目标最多 `1,632×2=3,264` 条表记录，不是 Python 对象数或内存字节上限。

源调用、SQL 和观察沿用上述既有超时；总耗时受排队、源服务及数据库影响，未实测前不写任意总时限。观察只读本次任务 ID，按状态/日期/行数变化报告，不把心跳当业务进度。所有临时脚本、摘要和日志仅放本机 `/private/tmp/daily-basic-stage3-prod-*`，SSH stdin 执行服务调用，服务器不落临时脚本；本机不安装依赖。最终把任务 ID、计划 hash、取消/续跑与幂等数量、读回和源比较结果回填本节，记录后删除临时文件。

### 20.4 正式执行结果与独立复核

本轮按 §20.1 范围，通过原命令服务及既有通用 worker 完成正式执行。没有修改产品代码或注入替身，也未新建 worker、调整服务/配置、扩大日期。所有 TaskRun 均引用原动作 `maintenance.fill_daily_basic_limit_status`，后续三个 APPLY 使用同一 PLAN `19347`，hash 为 `d1e0cd4dab592633b99789ee1c7076bce1afb963a0335da97916543ce21de481`。

| TaskRun | 实际结果 | 完成日期/目标日期 | 源读取行数 | 覆盖行数 | 执行时间（不含排队） |
| --- | --- | --- | --- | --- | --- |
| 19347 PLAN | success，完整冻结两日及 19 字段，配置无字节上限 | 2/2 | 0 | 0 | 9.948 秒 |
| 19348 首次 APPLY | canceled，首日已提交，次日未提交 | 1/2 | 1,632 | 1,632 | 4.831 秒 |
| 19349 原任务重试 | success，首日完整跳过，只补次日 | 2/2 | 1,630 | 3,262 | 4.202 秒 |
| 19350 同 PLAN 重放 | success，两天均完整跳过 | 2/2 | 0 | 3,262 | 1.159 秒 |

时间仅由本次 TaskRun 的 started_at/ended_at 相减并保留三位小数，不是全历史耗时估算或新增性能门禁。首次取消在北京时间 17:24:44.962621 请求，17:24:45.317519 终止，差为本次实测约 0.355 秒，不承诺其他任务同样时限。

首次 APPLY 的节点 `29213` 为 success、覆盖 1,632；`29214` 为 canceled、覆盖 0。取消后 TaskRun 保留 `unit_done=1/2`、`rows_saved=1,632`、进度 50%，读回确认首日两表完整、次日两表仍有 1,630 个 NULL。续跑节点 `29215/29216` 均 success：首日 `already_complete=true`、两表 changed=0；次日两表各 changed=1,630。重放节点 `29217/29218` 均 success、`already_complete=true`、两表 changed=0。重放显示 3,262 是覆盖数量，不是再次更新 3,262 行。

| 两表物理核对 | 2010-01-04 | 2010-01-05 |
| --- | --- | --- |
| 最终每表行数与非空状态数 | 1,632 / 1,632 | 1,630 / 1,630 |
| 原字段及系统列 | raw 除新列外 21 列、serving 除新列外 20 列均与写前摘要一致 | 同左 |
| 主键集合 | 两表均与写前 SHA256 一致，无增删 | 两表均与写前 SHA256 一致，无增删 |
| 最终状态 SHA256，源与两表相同 | `fd70ed3337f82cab9fcbf5712c883cc5e01f2b8cad8465292acc4d160be125a6` | `0a082c06fa3e6e96d3db48aaee6f355281ba855a8f5749887d9e488cbe6b45f7` |
| 合法 0 值数 | 42 | 32 |

“原字段”完整包含原 18 个业务字段，系统列包含原始表 api_name/fetched_at/raw_payload、服务表 created_at/updated_at；四次摘要逐日、逐表比较均通过。两表本次各实际新增非空状态 3,262 行，合计 6,524 个列值；TaskRun 行数不按两表重复累计。

旧列 SHA256 的写前值及三次读回值完全相同，保留如下，避免临时文件清理后仅剩结论：

| 日期 | 原始表除新列外所有列 | 服务表除新列外所有列 |
| --- | --- | --- |
| 2010-01-04 | `8930465564f4f8daca0d606ba1d9efd856eae8d1745c1d3572cb2cb6a23d3d62` | `4716b58f28532cc8f461d2969d7c1e5165e35c0789d5e687e2fc6e584d910bcd` |
| 2010-01-05 | `3a56c679a66a1ee1778a43574701b359ba2d169ae0831d26116e5e8b08b04d94` | `f256498894dd0f5e866a5ded2e8a40501e44232691ca42832812a01c32d2d56a` |

独立真实源请求使用原 PLAN 参数和完整 19 字段，两天分别返回 1,632、1,630 行，日期正确、主键唯一、状态原生 int 且在 0～6，目标缺失/额外代码均为 0。按目标主键顺序生成的全部状态摘要与两表最终读回一致，没有用归一化器或写入服务生成预期。实际源调用为首次首日一页、续跑次日一页、独立核对两页，共 4 页；首次第二日停在原始表主键核对阶段，未进入源读取；幂等重放不发源请求。

另以独立只读事务调用现行 `TaskRunQueryService.get_view`，核验上述四个任务及七个节点，任务详情响应的完成量、源读取量、覆盖量与终态均与数据库一致，无拒绝行或 primary issue，未截断节点；运行期间观察的完成日期数及已保存量单调。没有把命令服务调用或详情查询等同于浏览器 UI 点击验收。最后 Web 和通用 worker 均 active/running、NRestarts=0，两个健康接口为 ok。

独立复核按“原 PLAN/hash及两日范围 → 原 worker 的真实结果 → 取消后读回 → 续跑/重放读回 → 真实源结果 → 任务详情”重新对账，未发现第三阶段未满足项。代码沿用既有第三阶段与字节限制修订，不再增加实现或重复跑隔离测试。文档完整性与差异检查通过后，本次第三阶段生产代表样本验收完成；结果不外推为全历史已补齐、DG 已替换或下一次自然日更已验收。

后续可按 §10.2 P3 单独批准全历史范围和夜间执行时间，并按 §10.1 开展 DG 第四、第五阶段开发；DG 正式导出在 Prod 全历史补齐后进行。本轮只改原专项文档，未自行提交；临时执行脚本、摘要及日志在正式记录核对后删除。

### 20.5 按本次生产样本估算全历史耗时（2026-11-12）

本节是旧 19 字段版本的历史估算；§21 已改三字段补录并取消额外核对，以下数字不直接作为新版本耗时结论。

管理员要求按本次实际耗时测算，未批准全历史执行或新增性能测试。本轮仅在只读事务、20 秒 SQL 超时下刷新服务表的日期计数汇总，并按 id 读取已有节点时间戳；没有读取全历史业务明细、重跑样本或请求源接口。

当前服务表范围为 `2010-01-04～2026-11-11`，4,092 个日期、14,488,315 行；日行数最少 1,341、最多 5,602，平均 `14,488,315÷4,092=3,540.64`。这是服务表计数，不宣称本次已经逐日核对原始表全历史。以下假设除已完成的两日外其余均待补，则待补为 `4,092−2=4,090` 日、`14,488,315−3,262=14,485,053` 行；正式运行仍须重新冻结实际范围及两表计数。

估算使用真实写入节点 `29213` 的 4.389098 秒/1,632 行和 `29216` 的 3.401381 秒/1,630 行：合计 7.790479 秒/3,262 行，平均每日期 3.8952395 秒。没有把首次 APPLY 的取消收尾、续跑时重复核对首日、排队或独立源验收算作新日期写入。两个已完成日期仍需读取跳过，其已有重放节点 `29217/29218` 合计为 1.142791 秒。

| 推算方式与假设 | 计算 | 补录 APPLY 的推算结果 |
| --- | --- | --- |
| 每个日期仍按样本平均耗时，忽略单日行数增长 | `(4,090×3.8952395+1.142791)÷3,600` | 约 4.43 小时 |
| 网络等待、解码、数据库等全部耗时都随行数同比增长 | `(14,485,053÷3,262×7.790479+1.142791)÷3,600` | 约 9.61 小时 |

样本每日平均只有 1,631 行，而全历史平均 3,540.64 行，不能只报第一种算法；第二种又把每日期固定请求成本一起按行数放大。实际包含固定成本和随行数增长的成本，仅凭两个几乎等行数的早期交易日无法分离两部分。**因此补录本身粗估为上述 4.4 与 9.6 小时两种情景，不能当成已验证的最短/最长时间。** 网络延迟、数据库负载或中断会改变结果，不额外乘任意系数或添加无依据余量。

作为范围依据，按当前行数每日期均少于 6,000，假设源记录规模相近且不出现额外分页，待补约 4,090 次源请求。每表当前 SQL 批次数 `sum(ceil(日行数÷1,000))=16,718`；扣掉已完成两日各 2 批，待补两表合计 `2×(16,718−4)=33,428` 条业务更新 SQL。它们是基于当前计数与代码的推导，不是实测执行条数或吞吐保证。

以下保留当时的可选核验成本推算，管理员现已在 §21 取消补录后的额外核对，不再列为执行步骤：同 PLAN 全范围状态重放按两个跳过节点的日期/行数外推，额外为 `1.142791÷2×4,092÷60=38.97` 分钟，或 `1.142791÷3,262×14,488,315÷60=84.60` 分钟；与当时补录情景相加约 5.08/11.02 小时。此记录不能继续用作当前排期要求。

PLAN 本次为 9.947510 秒，但它做两次范围计数并批量保存日期，不能按 `9.947510×日期数` 外推。全历史 PLAN、最终原 18 列核验、排队、中断后已完成日期的重读及故障重试未包含在上述时长中；核验范围尚需随 P3 执行方案明确，暂不能给这些项目的总耗时。DG 导出、候选与事件阶段也不在本估算内。所有数字仅用于此次排期讨论，不设定完成时限、不扩展正式执行批准。

## 21. 专用补录只下载三列，取消额外核对（2026-11-12）

### 21.1 管理员决定与范围

管理员明确要求：不再做补录完成后的额外核对；只更新收盘涨跌状态就只下载需要的字段。历史补录固定请求 `ts_code,trade_date,limit_status`，不再下载原 16 个非主键指标，不转换估值、换手率等字段，也不生成无用的 raw_payload。正常日更、数据集完整 19 字段合同、旧整行写入、DG 均不变。

正式补录成功后只根据既有 TaskRun 的日期完成量、覆盖量、拒绝量和终态收尾，不再安排额外全历史重放、全量旧字段前后比对或二次 Tushare 请求。§20 已完成的验收记录保留，不重复执行。写入前的必要主键/日期/状态校验、两表同日事务和中断续跑时的目标读取仍是执行链本身的组成部分，不删除，也不把它们改成独立核对任务。此前章节与本节冲突的完整字段补录和额外核验要求由本节替代；DG 自身文件/事件一致性要求不受影响。

本轮只修改 Prod 专用补录和它依赖的最小下载、校验部分及对应文档/测试；管理员已批准本次单独提交，明确当前为更新密集时段，暂不部署、重启或执行生产任务。新方案沿用 §2.3 已核实的两个历史日期三字段真实响应，依管理员要求不再调用 MCP 或官方源做重复验证。

### 21.2 代码位置、调用方与计划合同

开工前 CodeGraph explore/impact 已覆盖专用服务、两层 call_bounded、connector、普通 source_client，以及公告、股票周线、指数周期线和相关测试；直接补核全字段 normalizer、行检查与维护适配器。当前生产只存在旧 19 字段 PLAN `19347` 及已完成的样本 APPLY，不改写这些记录。

| 硬口径 | 最小实现及验收 |
| --- | --- |
| 只下载三列 | 新增仅保存 `DAILY_BASIC_LIMIT_STATUS_DOWNLOAD_FIELDS` 的小模块，供专用服务、计划适配器和两个 client 使用；避免 client 反向 import 专用服务形成循环，不定义新数据集或完整字段子合同。每一页显式使用相同三列，日期参数仍取原 resolver/unit，不增加参数或下载模式 |
| 保留原下载能力 | 现有 daily_basic/v1 调用只新增允许本动作的固定三字段投影，原完整 19 字段调用继续支持；错误接口、旧 18 字段及任意其他字段组合仍拒绝。公告、股票周线、指数周期线条件和行为逐字保持，不改 byte/timeout/cancel 逻辑 |
| 只转换本次三列 | 专用服务只取三列，复用原 coerce_row 转换日期和原收盘涨跌状态检查；该行检查新增仅内部使用的 required_fields 参数，默认仍为完整 19 字段。补录传固定三列，不复制或修改 DatasetDefinition。继续复用现有必填键和拒绝样本规则；任一错误仍使整日失败、保留之前已提交量 |
| 不改变原字段或进度 | 后续主键/状态匹配、bulk_update_columns、同日事务、取消、状态写失败、幂等跳过和续跑完全保留；新行只含三列，不伪造旧指标填入 normalizer |
| 新 PLAN 与实际下载一致 | 补录 PLAN_CONTRACT 升为 daily_basic_limit_status/v2，source_fields 冻结为实际下载三列。适配器每日期只投影旧有 execution_config 和 contract_kind，不读完整计划；v1 计划明确拒绝并提示重新 PLAN。不添加兼容双轨，不修改通用重放协议或已完成历史计划 |
| 错误说明与模板同步 | 既有 daily_basic.delivery_contract_mismatch 提示改为核对接口和支持的请求字段，不新增错误码。通用模板说明管理员明确批准的指定列维护可固定冻结所需下载投影；普通数据集下载仍为完整 source_fields，不允许任意调用方自行裁剪 |

没有新增配置、表、迁移、worker、线程或锁。PLAN/APPLY 的 unit、日期范围、1,000 行批次、6,000 行分页和既有超时保持；正式全历史执行需部署后新建 v2 PLAN，不直接复用样本 v1 PLAN。失败、取消和续跑仍按 §6.8，提交结果不明时停止，不新增恢复入口。

### 21.3 开销和验证

下载列从 19 减为 3，源请求次数、分页次数及两表 SQL 批次数不因此减少；不按 19/3 承诺速度或流量倍率。§20.5 的耗时来自旧 19 字段样本，只保留为历史参考，不能直接作为三字段版本的运行时限。取消的完整重放/二次源请求不再计入执行预算。成功后的任务收尾只读取本次 TaskRun/节点，不重新扫描历史数据；中断后继续仍须按原逐日主键读取已完成日期，不能声称续跑零成本。不新增性能测量。

必要验证用原有临时 PostgreSQL 和 loopback HTTP，输入投影来自 §2.3 已确认三字段及已有真实字面样本：三列正常补录、原列/系统时间不变、0 合法、缺代码/日期/状态、NULL/空键、非法日期、错误日期/重复键、非法状态、取消/续跑/进度/状态失败/事务回滚；HTTP 捕获实际 fields 确为三列，同时证明原 19 字段仍可调用、其他合同不变；v2 计划字段与调用一致、旧 v1 计划在源调用和业务更新前被拒绝。原日更完整合同用原测试保持，正常日更拿到只有三列时仍失败。真实边界由实际 HTTP client → connector → 专用转换 → 临时两表事务覆盖，不使用 mock 代替这段集成。

所有临时资源放 `/private/tmp`，使用现有依赖，不请求 Prod/源站或修改正式数据。开发后按上述约束重新对账并回填结果，不重复生产小样、全历史核对或源站验证。

### 21.4 实现结果与复核

本轮实现限于本节列明的七个源码文件、四个测试文件、本文和数据集开发模板。没有改动 Definition、原整行 writer、指定列 DAO、通用 dispatcher/worker、DG 或正式数据。

| 要求 | 实现与证据 |
| --- | --- |
| 每页只下载三列 | 专用服务引用固定清单；分页测试逐页断言 fields。实际本机 HTTP client → connector → 三列转换 → 临时 PostgreSQL 两表事务通过，请求字段严格为 `ts_code,trade_date,limit_status`，旧业务列及系统时间保持原值 |
| 原有能力保持 | 普通日更仍要求完整 19 字段，只有三列的输入仍拒绝。两层下载器继续接受完整 19 字段；静态语法树对比确认共享 client 除每日指标字段绑定分支外与原实现一致，原接收、字节、截止、取消及其他合同逻辑没有改动 |
| 校验与恢复保留 | 缺三列任一列、NULL/空键、非法日期/状态、重复键及日期不符仍整日失败；两表事务、取消、退出后续跑、幂等、进度和状态写失败回归通过。旧 v1 PLAN 测试使用原生产者的计划与快照哈希规则，确认进入明确的重新 PLAN 提示，源请求和业务更新均为零 |
| 验证结果 | 按测试名称合并重跑结果，共 401 项通过、12 项既有专用集成环境用例跳过；实际临时 PostgreSQL 和本机 HTTP 集成已运行。遵照此前免测决定排除 1 项大响应性能测量；没有新增性能测试、依赖安装或源站验证 |

首次测试启动漏载现有 pytest-mock 插件，旧计划夹具也先后误用错误记录字段、漏算快照完整性哈希；已按真实模型与生产者修正，仅重跑受影响用例至通过，没有修改产品校验来迁就夹具。数据集定义检查、文档完整性、改动文件静态检查和差异空白检查通过。CodeGraph explore/impact 覆盖入口、共享下载器、既有公告/股票周线/指数周期线消费者，完成后 sync/status 确认索引已更新。

本轮没有请求 Tushare/MCP、连接 Prod、重新执行生产小样或全历史核对。本次提交仅保存代码、测试和文档，不推送或部署；后续部署后需新建三字段 v2 PLAN，旧样本 PLAN 不再执行。旧耗时数据保留原记录，不将下载列数缩减比例当作提速结论。


## 22. Prod 全历史正式补录（2026-11-12）

### 22.1 本步授权、执行范围与开工核对

管理员已明确批准严格按 LLD 执行 Prod 全历史补录，结束日期取最新已完整入库的交易日，完成后汇报，先不动 DG。本步只执行 `maintenance.fill_daily_basic_limit_status` 的新 v2 PLAN/APPLY，不开发或部署代码、不重启服务、不改配置，不调用旧样本 v1 PLAN，不进行 DG 开发、读取、导出或写入。

2026-11-12 23:49 起（北京时间）的只读开工核对：远程提交为 `5f3cff280357789e88b2ac99b1b63b091d1ad4d6`，包含三字段补录提交 `341dd7ee1`；实际加载合同为 `daily_basic_limit_status/v2`，下载列为 `ts_code,trade_date,limit_status`；迁移为 `20261112_000188`。Web 和通用 worker 均 active/running、NRestarts=0，当时没有 queued/running/canceling 任务。有效管理员标识仍为 1，仅用于命令服务的请求归属，不获取登录凭据。

服务表首日为 `2010-01-04`，最新日为 `2026-11-12`。最新日原始表、服务表各 5,573 行，收盘涨跌状态各有 5,573 个非空值；既有状态记录的 observed/latest/last_sync_date 均为 `2026-11-12`，latest_success_at 为当日 21:02:43.452067+08:00，freshness=fresh。因此本次固定起止为 `2010-01-04～2026-11-12`，之后的新日期不加入本计划。最新四日服务表及最新日原始表仅做日期计数，没有读取全历史业务明细。

### 22.2 执行步骤、读写与失败边界

沿用 §6、§8、§20 的既有命令服务和 worker 操作方式。开工前 CodeGraph explore 已覆盖 `TaskRunCreateContext`、`TaskRunCommandService.create_task_run/retry_task_run`、新适配器及调用链；直接核对本次三列服务、配置、TaskRun/节点字段与此前真实执行记录。既有三字段源证据及 §21 隔离验收继续适用，不重跑生产小样或二次源请求。

| 步骤 | 操作及验收 |
| --- | --- |
| 新 PLAN | 通过 `TaskRunCommandService.create_task_run`，传本动作、PLAN、显式起止和管理员 1；由原通用 worker 执行。PLAN 只读两表逐日计数，并写现有 Ops 草稿与冻结记录；成功后一次读取该计划，确认 FROZEN、apply_ready、v2、三列、固定两表及 limit_status、日期集合/计数、配置与 plan_hash；记录实际日期数和覆盖量。失败或不一致不创建 APPLY |
| APPLY | 通过同一命令服务创建引用新 PLAN id/hash 的 APPLY；不重新规划范围，不直接调用 DAO，不另起 worker 或手写业务 UPDATE。读取仅为逐日目标代码、交易日和状态，以及对应三字段来源；只匹配现有主键，更新两表 limit_status，不增删行、不改旧列/系统时间。已经完整一致的日期跳过；单日两表同一业务事务，子批次不独立提交 |
| 观察 | 独立只读短事务按本次 TaskRun id 投影状态、当前日期/阶段、完成量、覆盖量、拒绝量和更新时间；不反复读完整计划或全历史业务数据。节点仅按本次 task_run_id 读取；不修改其他任务、worker 或 scheduler。保留既有进度和详情入口 |
| 失败与中断 | 严格按 §6.8：当前日期未提交则回滚，已提交日期保留。源/目标校验冲突或提交结果不明时停止，不自动改值或更换范围。先确认原任务终态，再按原 PLAN 用 `retry_task_run` 续跑；先解释错误，不盲目重复创建。SSH 断开先按已持久任务 ID 读回，不能当任务未创建而重发 |
| 成功收尾 | 只核对本次 TaskRun 日期全部完成、覆盖量等于冻结目标、拒绝为零、任务和节点终态一致；汇总现有节点的两表变更量和跳过量。按 §21 不额外执行全历史重放、全量旧列比对或二次 Tushare 请求。完成结果回填本节，不把任务覆盖量说成每表实际变更量 |

本步必要全历史读取已随管理员批准的 LLD 执行范围获准：两表仅逐日读取匹配所需三列，源接口仅下载三列，内存只保留当前日期，不导出历史明细。旧业务列不进入本次全局读取。所有过程脚本/摘要仅放本机 `/private/tmp/daily-basic-full-prod-*`，SSH stdin 执行现有服务，服务器不落临时脚本。产品代码和运行配置不变；本步只在原文追加执行记录，不自行提交。

### 22.3 配置、成本及验收依据

实际配置仍为 SQL 批次 1,000、分页 6,000、源调用 30 秒、SQL 20 秒、观察查询 2 秒、进度 5 秒，不设响应字节限额。PLAN 用一次每表按日计数，冻结后据日期描述计算实际总行数、单日最大行数、分页上界和 SQL 批次数，不为估算再读全历史业务行。源请求上界仍按每个未完整日期 `floor(目标计数/6000)+1` 页，SQL 批次数按两表 `2×sum(ceil(日目标计数/1000))` 解释；跳过日期不发源请求或更新 SQL。

§20.5 的旧 19 字段耗时只作历史排期参考，不能承诺本次三字段总时长，不新增测量或任意余量。中断后续跑会重新读取前面日期的键/状态，已完成日期不再次请求来源或更新；最坏仍涉及全计划目标三列的逐日读取，该开销不能宣称为零。最终验收只读一次本次任务和相关节点汇总，业务表追加全历史核验遍次为零。性能和进度依正式任务实际结果记录；不另设未经核实的总耗时或次数限制。


### 22.4 新 PLAN 已冻结，APPLY 执行前记录

PLAN `19412` 由原通用 worker 执行成功：2026-11-12 23:53:52.167276 至 23:54:02.384325+08:00，耗时 10.217049 秒。冻结状态 FROZEN、apply_ready=true，合同 `daily_basic_limit_status/v2`、三列、两表及仅更新 limit_status 均符合本节；覆盖 `2010-01-04～2026-11-12` 的 4,093 个交易日，两表逐日计数一致，每表目标覆盖 14,493,888 行。

plan_hash 为 `fd157a5e38a4d8e65d28101911988905792e7bdc0ca021b2e77188b69e99ef7b`。单日目标最少 1,341 行、最多 5,602 行；每日期最多 `floor(日行数/6000)+1=1` 页，所有日期都待补时至多 4,093 页。两表 SQL 更新批次数上界为冻结计数的 `2×sum(ceil(日行数/1000))=33,448`；完整跳过日期不请求来源、不执行更新，实际数量以后续节点结果为准。以上来自计划描述计算，不是额外业务明细读取或性能实测。

接下来只创建一个引用 `19412` 及上述 hash 的 APPLY，由原 worker 执行。不修改 PLAN，不新增日期；APPLY 运行和最终结果在本节继续记录。


APPLY 19413 于 2026-11-12 23:55:50.440602+08:00 创建，原 worker 于 23:55:52.585636+08:00 开始执行，引用上述 PLAN/hash。截至首轮观察，已完成 14/4,093 日、覆盖 22,920 行、源读取 19,658 行、拒绝 0；差额 3,262 行为此前两日已完成样本的跳过覆盖量。正式任务执行中，最终完成量以终态记录为准。后续观察仅每 45 秒读取本任务六个进度字段，这是本次操作的观察间隔，不是产品配置或性能保证。


### 22.5 首次 APPLY 因来源缺少目标股票停止（2026-11-13）

APPLY 19413 于 2026-11-13 02:19:29.783920+08:00 以 failed 结束，任务和节点终态一致。已成功 2,182/4,093 日，最后成功日期为 2018-12-21；覆盖 5,402,518 行，TaskRun 的已成功日期源行数统计为 5,399,256，两表实际新增状态各 5,399,256 行，另 3,262 行是此前两个样本日的跳过覆盖。拒绝行计数为 0 不代表通过：本次属于目标股票缺失，unit_failed=1。

失败节点 31533，序号 2,183、日期 2018-12-24，rows_saved=0；issue 299 的原始错误为“2018-12-24 源数据缺少目标股票，当前日期未提交”。该日按业务合同在创建更新事务前停止，未写两表；没有重试、改值、重建计划或操作 DG。

错误记录未保存 missing_codes 详情，因此下一步仅做该失败日期的必要只读诊断：从 PLAN 19412 按已知序号投影该 unit 的 payload 和冻结配置；按服务表日期索引读取当日 ts_code，不读旧指标；用原冻结参数、原项目 connector 和三列请求这一日期的一页，比较缺失/额外代码；只对缺失代码有界读取当前名称，以及两表该复合主键的状态。该诊断不是补录成功后的额外核验，不扩到其他日期、不发起 APPLY 或更新。若确认源/目标冲突，保持停止并向管理员报告，按根规则等待处理决定，禁止用临时补丁绕过。


失败日只读诊断确认：冻结目标和当前服务表均为 3,582 个代码，按原参数请求的源页为 3,581 行/3,581 个唯一代码，无额外代码，只缺润农节水 920964.BJ；名称来自当前 security_serving，list_status=L。该代码该日两表原记录均存在、limit_status 均为 NULL。补充诊断仅允许再对 920964.BJ、2018-12-24 使用本地源文档已支持的 ts_code＋trade_date 及相同三字段请求一页，用于区分按日查询遗漏和源历史记录不可得；不回写、不重试 APPLY、不扩大日期或对象。


### 22.6 本轮结果与待管理员处理项

对唯一缺失代码 920964.BJ、日期 20181224 的三字段定点查询返回 0 行；与失败日全市场查询结果一致，当前接口无法按该目标主键提供记录。仅核实这个日期，不外推该股票其他日期或其他股票的历史情况，也不把源端缺记录判定为目标表原记录错误。

| 项目 | 本轮实际结果 |
| --- | --- |
| 冻结范围 | 2010-01-04～2026-11-12，4,093 日，每表目标覆盖 14,493,888 行；PLAN 19412/hash 保持不变 |
| 正式执行 | APPLY 19413 failed；开始 2026-11-12 23:55:52.585636+08:00，结束 2026-11-13 02:19:29.783920+08:00，相减为 8,617.198284 秒，即 2 小时 23 分 37.198284 秒。这是含失败日期处理的本次实际耗时，不外推剩余任务时限 |
| 成功提交 | 2,182 日，至 2018-12-21；覆盖 5,402,518 行，每表实际变更 5,399,256 行；两个原样本日共 3,262 行完整跳过 |
| 失败日期 | 2018-12-24，节点 31533；目标 3,582 代码，诊断源页 3,581 唯一代码，缺润农节水 920964.BJ，无额外代码；定点查询也为 0 行。该复合主键两表状态仍 NULL；该日期因缺目标在更新事务前失败 |
| 尚未覆盖 | 本任务剩余 1,911 日、冻结目标覆盖 9,091,370 行，包括失败日；这不是待更新行数，后面的已完整日期仍会在续跑时跳过 |
| 任务与节点 | TaskRun failed、unit_done=2,182、unit_failed=1、rows_rejected=0；成功节点 2,182 个、失败节点 1 个，当前节点 failed，失败节点覆盖 0，终态一致 |
| 本轮边界 | 未重试或改写计划，未跳过目标、补默认值、改旧字段或手写业务更新；未做全历史重放、旧字段全量比较或成功后的二次源请求；未操作 DG、重启或部署 |

TaskRun.rows_fetched 只包含成功返回 unit 的统计，失败日虽然请求过源，但没有返回 unit 结果，其节点 fetched/saved 为 0；不能将 5,399,256 说成所有实际下载行数。缺目标属于 target_mismatch，不是逐行数值拒绝，所以 rows_rejected=0 仍必须失败。原 issue 299 仅保存通用失败码和错误文字，没有保存 missing_codes；本次必要只读诊断补全了代码与名称，未自行修改产品错误处理。

本次诊断成功发起两个有界源请求：失败日期一页三字段，以及唯一缺失代码同日的一页三字段。诊断脚本首次使用 python 标准输入入口，下载器 spawn 子进程找不到 stdin 路径，未发源请求；改为 python -c 从 stdin 读取后使用原下载器正常完成，两次均未写数据，服务器未落脚本。正式补录没有因诊断脚本错误被重启或重试。

当前阻塞为真实源/目标不一致，按 §6.3、§22.2 和根规则“若发现计划口径与当前实现、真实数据或源接口行为冲突，必须停下来说明冲突点，等待确认”保持停止。本轮不能宣称全历史完成。建议先针对润农节水这一历史记录确认来源和源端代码口径，再决定修复源记录或明确缺失记录的业务处理口径；在决定前不删除目标记录、不推算状态或直接填 0。若源记录恢复且原计划输入未变，可按既有原 PLAN 重试继续；若需要改变缺失记录处理规则，须先修订原 LLD，再开发和授权执行，不能通过执行脚本绕过现行规则。

本轮只追加原专项 LLD，执行结果和阻塞已记录；未自行提交。文档完整性和差异空白检查通过后清理本任务临时脚本，后续定位以现有 PLAN/APPLY/issue/节点及本节证据为准。


## 23. 上市日期之前且源无当日记录时保留 NULL（2026-11-13，已开发、未部署）

### 23.1 管理员确认与 NULL 的含义

管理员确认：若该历史交易日在股票基础信息记载的上市日期之前，且 Tushare 每日指标源当日没有该代码的数据，则收盘涨跌状态保留为空。此处字段为每日指标的 limit_status，不是股票基础信息的 list_status；股票上市状态不修改。

当前两表 limit_status 从第一阶段起就定义为可空 INTEGER，用于存储未补齐状态；本节修订前，正常同步与专用补录严格拒绝源返回的 NULL，专用补录还会在源缺目标代码时整日失败；本节只为历史补录增加已批准例外，正常同步和源已返回行的数值校验保持严格。因此数据库可存 NULL 不等于原任务允许带缺失记录成功，本节是管理员新增确认的历史补录业务例外，无需改表结构。

核对事实：Prod raw_tushare.stock_basic、core_serving.security_serving 及当前 Tushare stock_basic 对 920964.BJ 的 list_date 均为 2020-07-27；[北交所代码对照表](https://www.bse.cn/code_mapping/200025792.html)列相同日期，并注明精选层平移公司的上市日期取原精选层挂牌日期。[公司披露](https://www.bse.cn/disclosure/2025/2025-08-26/73e88618ea5f4686ac7f4fd28079cedf.pdf)还记载 2014-07-23 新三板挂牌、2021-11-15 平移北交所。这些阶段解释了为何不能仅因早于 list_date 就删除旧每日指标记录。本次业务判断使用现有 list_date 字段，不新增挂牌日期模型或历史代码推导。

### 23.2 例外条件和原有能力边界

1. 补录目标继续取两张每日指标表当天已有记录，不按上市日期提前排除代码，也不增删行。
2. 同日源结果缺少某个目标代码时，按缺失代码一次有界批量查询 core_serving.security_serving 的 ts_code/list_date。只有能明确确认 trade_date < list_date，且两表该记录原本均为 NULL，才保留这两个 NULL，允许该日其他目标按原事务补录。润农节水的 2018-12-24/2020-07-27 符合这个条件；判断不要求补请求整只股票历史。
3. 源当日有该代码且状态合法时照常补齐，包含上市日期之前有合法来源的情况；不因早于上市日期就忽略源数据。源确实返回该行但 limit_status 为 NULL，不属于本次“缺少该代码记录”的例外，仍按原数值校验失败。
4. 交易日等于或晚于 list_date 时缺失、缺少可用上市日期，或已有值不能满足上述保留 NULL 条件时，继续按原缺失/冲突规则停止。不得借本节清空已有非空状态、填默认 0 或放开所有 NULL。
5. 正常 19 字段日更、原 DAO、两表旧业务列和系统列、主键、单日双表事务、取消及状态写失败边界保持原要求。本轮不修改 DG。

### 23.3 实现位置、续跑和验收要求

开工核对使用 CodeGraph explore 追到 app 维护适配器 → DailyBasicLimitStatusService.execute_day/_execute_day → _read_targets；直接阅读两表模型、正常状态行检查和现有 PostgreSQL 回归。后续最小改动落在专用补录的 missing 处理、结果说明和维护 PLAN 冻结口径，不修改正常 row_transform 来普遍接受 NULL，也不新增配置、状态表或另一种执行入口。

- 对允许留空的目标不构造伪造源行，不向 DAO 提交 NULL 更新；其余目标继续只更新 limit_status。日完成量须区分目标覆盖量、实际变更量和本例外保留 NULL 的数量/代码；覆盖整个目标不等于所有目标都填成非空。
- 已完整非空日期继续按原逻辑跳过。中断后遇到含 NULL 的日期，沿用原流程重新读取当日源并重新判定；不得仅信旧 TaskRun 成功或仅凭早于 list_date 就跳过。这样会增加这类日期续跑时的一页或既有分页请求，成本按实际重新处理日期数及冻结分页规则计算，不新增 checkpoint 或进度表来规避该开销。
- 查询上市日期只针对当日缺失代码，新增查询返回量至多为该日缺失目标数；不扫描全市场股票基础信息，不为识别本例外逐股票再发 Tushare 请求。正常无缺失路径不增加该查询；原请求/SQL批次、超时和单日期驻留不变，不新增性能测量。
- 回归至少覆盖：本次真实日期/上市日期的独立小样、同日源缺失留空且其他股票成功、源有合法 0 仍写入、源行状态 NULL 仍失败、上市当日及之后缺失仍失败、缺上市日期仍失败、已有状态不清空、原列不变，以及含本例外 NULL 的取消后续跑和完成统计。此前已通过结果不能替代本次业务例外验收。
- 执行前需按 §23.4 冻结包含本次规则的新 v3 PLAN；不改写 PLAN 19412 或把 APPLY 19413 的失败改为成功。新规则已完成开发和隔离验证，随本次提交保存，尚未部署或正式执行，不能直接恢复当前 Prod 旧代码任务。

本轮只将管理员确认的例外与必要影响面落回原 LLD，未修改代码、连接 Prod、请求源数据或恢复补录，未自行提交。


### 23.4 开发前补齐的实现与续跑 LLD

管理员已明确要求先落完 LLD，再修改代码。本步目标仅为 Prod 专用历史补录实现 §23.2；范围是两个专用源码文件及其测试、原 LLD，不部署、不恢复正式任务，不改普通日更、完整接口字段合同、DAO、数据表/迁移、通用 dispatcher/worker、API 结构或 DG。沿用开发审计与 Tushare 契约核验技能；真实依据复用 §22 的失败日期、缺失源结果和已核实的 list_date，不再请求源端或读取 Prod。

| 硬要求 | 实现位置与验收 |
| --- | --- |
| 仅处理源缺记录 | DailyBasicLimitStatusService._execute_day 在原 missing 集合分支读取 Security.ts_code/list_date，WHERE ts_code IN 当日缺失集合；查询前后复用 check/observe 和现有局部 SQL 超时。无 missing 不查询基础信息，不在下载或正常 normalizer 中补列/补值 |
| 严格小于上市日期且两表已有 NULL | 在缺失集合内筛出 list_date 可用、trade_date < list_date、raw 和 serving 均为 None 的代码，允许留下原 NULL。未满足条件的缺失继续原 target_mismatch；原已有值合法性与两表冲突校验继续先执行。不新增全局可空开关或错误码 |
| 同日其他股票正常提交 | 仅为源结果中存在的目标构造 updates；保留 NULL 的代码不传给 bulk_update_columns。原两表同日事务、提交与取消边界、SQL 子批次及原列不变合同原样保留 |
| 覆盖量与留空说明 | 返回 rows_saved=len(serving)，含本日已按规则处理的全部目标；raw_changed/serving_changed 仍为实际变更量。仅存在例外时附加 null_before_listing_codes（按代码排序）；没有例外的原结果字段集合和语义不变。适配器把该结果放入既有节点 metadata，并在现有 phase 和返回的 summary_message 中显示留空数量，使既有详情能读回数量说明；不增加共享计数器、接口字段或新状态表 |
| 新规则不能伪装为旧计划 | 专用 PLAN_CONTRACT 升为 daily_basic_limit_status/v3。metadata 固定写 missing_source_policy=keep_existing_null_before_list_date，以及 listing_date_source=core_serving.security_serving.list_date；它们是本动作代码固定规则的执行记录，不是新增配置或运营输入。既有 hash 冻结自然包含这些 metadata；APPLY 继续只投影 contract_kind/execution_config，原版本比较拒绝 v1/v2，提示按新规则重新 PLAN，不改通用 snapshot/replay |
| 含留空记录的幂等续跑 | 两表均合法非空的日期仍跳过；含 NULL 日期按原流程再次取当日源，重新判断例外。上次已填的其他股票相同值不再实际变更，NULL 仍只在本次条件成立时保留；若源后来返回合法状态则填入。不用 TaskRun 成功来替代该判定，不新增例外状态持久化机制 |

本次新增规则 metadata 只有专用 planner 写入、既有快照/hash 与详情读取、专用适配器按 v3 版本执行及测试使用；不存在 env/Settings/数据库配置项，不变更原 batch/timeout 来源或生效方式。Foundation 只读本层 Security 模型，不依赖 Ops；app 只做 PLAN 和结果说明装配，不承载上市日期判断。CodeGraph impact 对 DailyBasicLimitStatusService 覆盖专用服务、适配器和业务/传输测试，普通下载器、日更 Definition/normalizer 和现有页面/API 消费者不需迁移。

**后续正式范围。** 已完成前缀保留 APPLY 19413 的 2010-01-04～2018-12-21、2,182 日及 5,402,518 行覆盖证据；后续部署新代码后，从失败日期 2018-12-24 到原终点 2026-11-12 生成新 v3 PLAN/APPLY，不再读取或重放已完成前缀，也不顺带扩到新的最新交易日。原 PLAN 差额为 1,911 日、每表 9,091,370 行覆盖目标，只作此次剩余范围参考，新 PLAN 必须以实际两表计数冻结。跨两次任务按不重叠日期合并覆盖量，分别报告实际变更和例外留空，不能声称全历史都变成非空。新 v3 APPLY 自身中断时继续引用同一 v3 PLAN；旧 19412/19413 不改写、不自动重试。

**失败、内存和预算。** 继续沿用 §6.8，状态写失败不回滚业务、取消不领取下一日期、提交结果不明停止。新增上市日期查询仅在本日期源缺失时一次执行，输入和最多返回行数均为当日缺失代码数；不全量加载股票基础信息，无新增源调用。内存增加的日期映射/例外代码清单只与当前日期缺失数有关。正常请求、分页和 SQL 批次/超时不变；续跑含例外 NULL 日期的成本为再次读取当日两表与既有源分页并重判，其他已相同值实际变更为 0。最终验收依旧只读本任务/节点，例外留空数量从已记录代码清单按节点汇总，不额外扫全历史业务数据。不增加性能测量、任意余量或无依据时限。

**测试与最小真实边界。** 使用已有临时 PostgreSQL 与本机 HTTP 夹具，不安装依赖，全部临时资源在 /private/tmp。§22/§23 已核实的真实代码 920964.BJ、日期 2018-12-24、上市日期 2020-07-27 作为独立事实；其他股票/状态是明确的人工小样。先以本次真实日期关系的测试证明旧代码会因 missing 失败，再验证新行为。正例覆盖留空但其他股票正常补、源有合法 0 不跳过、完整源日不增加基础信息查询、幂等重放；反例覆盖上市当日/之后缺失、无基础信息/无上市日期、任一表已有值、源行 NULL/错误类型，以及混合缺失导致整日回滚。按真实 worker/TaskRun 在临时两日运行，验证新 v3 PLAN 只选择剩余日期且前缀数据不变、留空数量说明、日期及行数累计、首日提交后取消、同 v3 PLAN 续跑重新判断、节点与任务终态。原进程退出、状态写失败、事务回滚、正常 19 字段严格校验和三字段 HTTP → 两表链路一并保留回归；仅替代真实 Tushare 网络，不以人工夹具宣称新的生产验收。v1/v2 旧计划使用真实生产者相同的两个哈希规则构造有效快照，必须实际进入新版本拒绝分支，不能用损坏快照冒充版本测试。

开发完成后逐条复核本表、记录实际测试结果和剩余生产边界；不自行提交或部署。


### 23.5 实现结果、验证与开发后复核

本轮先完成 §23.4，再修改 DailyBasicLimitStatusService 和其 TaskRun 适配器；同时更新三份现有测试及本文，共六个文件。没有新增配置、表、迁移、状态表、worker 或线程，没有修改普通日更、DAO、通用下载器、dispatcher/worker 或 DG。

| 验收项 | 实际结果 |
| --- | --- |
| 真实缺陷关系的修复前证明 | 临时 PostgreSQL 中以 920964.BJ、2018-12-24、list_date=2020-07-27 和独立人工配对股票构造小样，旧代码准确在 missing 分支失败。此为刻意验证旧缺陷的预期失败，不计作最终未解决失败 |
| 补录、传输、维护运行与正常日更 | 主组 136 项通过。覆盖留空且其他股票提交、原列/系统列不变、0 合法、上市当日和之后/缺基础信息/缺上市日期仍失败、已有非空状态不清空、源返回 NULL 仍拒绝、混合缺失不部分提交、两表回滚及源恢复后能补入新状态 |
| 最小真实集成 | 实际本机 HTTP client → connector → 三字段转换 → 临时 PostgreSQL 基础信息读取及两表事务通过，只发一次该日期三字段请求，未为缺失代码增加源请求。Tushare 网络由真实合同的本机 HTTP 响应替代，其他股票状态明确为人工小样，不作为生产源事实 |
| 完成说明与续跑 | 真实 worker 首日提交后取消，保留覆盖 2 行（其中 1 行留空）；新 APPLY 重新请求含 NULL 的首日并复核，首日实际变更 0、次日实际变更 1，两日期累计覆盖 4 行。TaskRun/节点阶段持久化并读回“其中 1 行收盘涨跌状态留空”，每日期代码清单和实际变更量可读回，任务及节点终态一致。阶段说明补充回归单独重跑通过，包含在上述 136 个唯一测试中 |
| 旧计划与剩余范围 | 有效 v1/v2 历史快照均在源请求和业务更新前被拒绝；v3 写入已确认规则及上市日期来源。补充剩余范围测试 1 项通过：新 PLAN 只包含指定后续日期，APPLY 只取该日源，原已完成前缀全部旧值保持；该项不在上述 136 中 |
| 定义、架构与维护进度 | 201 项通过；另两项既有 PostgreSQL 正常日更/名称查询隔离集成通过。首次门禁调用漏用本机端口所需执行权限，造成这两项无法启动临时数据库；只纠正命令权限后重跑，没有改变产品实现或断言来迁就失败 |
| 最终合并与静态门禁 | 按测试名称合并重跑结果，共 340 项通过、无失败或跳过。Definition lint、改动文件 Ruff、文档完整性和差异空白检查通过，未安装或升级任何依赖 |

开发后另做语法树对账：专用服务的 plan_dates、execute_day、_read_targets、_fetch、_normalize 及结构化数值错误方法与 HEAD 相同，原两表更新/提交/取消代码块与 HEAD 相同；只增加 missing 的已批准分类和覆盖说明。共享 row_transform、Definition、BaseDAO、两个下载器和 dispatcher/worker 文件逐字与 HEAD 一致。结合正反例和有效旧计划测试，未发现本次例外放宽普通日更、源返回 NULL 或其他动作的情况。

CodeGraph explore/impact 已覆盖专用服务、适配器和业务/传输测试；直接补核既有 TaskRun 详情原样暴露 ingestion_diagnostics 的路径，既有字典可承载例外代码和阶段说明，不需迁移 API/前端消费者。开发后 sync/status 确认索引最新。

开发验证阶段未连接 Prod、请求真实 Tushare 数据（包括 tushareMcp）、修改正式数据或部署，也没有恢复失败任务或开始 DG 工作。管理员已批准本次只提交代码、测试和 LLD，不推送、不部署、不恢复补录。后续部署新代码后按 §23.4 从 2018-12-24 到原终点 2026-11-12 新建 v3 PLAN/APPLY，沿用已完成前缀的既有证据；正式继续前仍须取得该步执行安排。临时测试资源在结果落档后清理。
