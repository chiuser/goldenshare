# 股票每日指标扩充需求：Prod 与 DG 增加收盘涨跌状态的方案与 LLD

更新时间：2026-11-11。

状态：**§12 的维护进度与 DG 日期锁修复已提交 `e393aba66`；本轮补齐 §6.6～6.8、§7.7 的具体设计，并按 §13 做有界源接口验证。19 字段、历史补录和 DG 替换能力尚未开发。** 管理员已认可“Prod 只补新增列，DG 从补齐后的 Prod 重新 bootstrap”的方向，并要求新增能力不得影响既有能力。本文不是生产执行批准。

本文是本次扩充的唯一专项主文档，同时承接需求、方案、代码设计、性能依据和后续执行结果。原 [DG 接入方案](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-daily-basic-onboarding-plan-v1.md)及 [DG 接入 LLD](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-daily-basic-onboarding-low-level-design-v1.md)保留原 18 字段实现与历史验收；本专项获评审后，在原文增加本专项入口及适用边界，不复制本次方案或改写旧验收。

## 1. 目标、范围与已确认原则

本次给股票每日指标数据集 `daily_basic` 增加收盘涨跌状态 `limit_status`，补齐现有历史，并使以后的日常同步持续保存该字段。

| 编号 | 硬要求 | 落地位置 | 验收依据 |
|---|---|---|---|
| R01 | 新能力不得改变旧能力 | §5 新 DAO 方法；§6 独立维护动作；§7 bootstrap 显式替换分支 | 旧方法签名、默认行为及调用方不变；原有回归通过；反例证明新方法不会清空旧列 |
| R02 | Prod 原始表、服务表都增加字段 | §4、§5 | 两表均为可空 `INTEGER`，不设 0 默认值，主键不变 |
| R03 | 历史补录只更新 `limit_status` | §5、§6 | 原 18 个业务字段及未指定系统字段保持原值；不增加或删除业务行 |
| R04 | 正常日更使用完整 19 字段 | §4、§6.1、§7.1 | 显式请求新增字段；缺列、错误类型不能变成成功写入 |
| R05 | DG 复用原 bootstrap，从补齐后的 Prod 重建 | §7.2 | 一次正常完整导出；19 字段候选与冻结导出完整一致；不另写 DG 补列主流程 |
| R06 | 正式文件先完整校验，再逐文件原子替换 | §7.3 | 候选审计、旧文件身份、同文件系统、日期锁和逐文件进度均通过 |
| R07 | 新检查只能对应新文件生成记录 | §7.4 | 当前文件校验值、最新物化记录及检查目标的 storage id/run id/timestamp 对应 |
| R08 | 保留旧物化、旧检查历史，不制造全历史绿色状态 | §7.4 | 追加记录；检查范围为已有检查日期与既有近期窗口的并集；其余日期保留未检查语义 |
| R09 | 中断后保留已提交数据并能续跑 | §6.4、§7.5 | 取消、退出、重放、事件部分写入、状态保存失败的测试和真实样本 |
| R10 | 数量、限制和耗时说明有依据 | §8 | 区分本次统计、历史实测、推导和未知项；按管理员决定免除本专项新增测量，保留现有执行限制，不虚构数字或性能保证 |
| R11 | 按阶段取得正式操作批准 | §10 | 开发、Prod 迁移/小样/全量、DG 导出/替换/事件分别有明确范围 |

边界：只处理 `daily_basic`。不增加行情页面功能，不重新计算估值，不将本次字段补齐扩成历史数据纠错，不增加 DG Silver 或 ClickHouse 副本，不清空数据库表、Lake 目录或 Dagster 历史，不新增 worker、队列和系统服务。

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

官方接口为 [Tushare 每日指标，doc_id=32](https://tushare.pro/document/2?doc_id=32)。本地 [源资料](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/行情数据/0032_每日指标.md)是 2026-04-19 保存的旧版本，仍列 18 字段；实施阶段更新同一路径并保持 `docs_index.csv` 的 doc_id、路径不变。

| 请求 | 结果 | 能证明的范围 |
|---|---|---|
| `000001.SZ`，20261110，默认字段 | 1 行、18 字段 | 默认不含新增字段 |
| 同代码、同日期，显式完整 19 字段 | 1 行，`limit_status=4`，原 18 字段与默认响应相同 | 新字段可显式获取；不能证明整个历史没有源端修订 |
| 20100104，仅请求代码、日期、状态 | 1,632 行，状态均为 0～6 整数，无缺失和重复键 | 该日源端代码集合与 DG 完全一致 |
| 20261110，同样的三字段抽样 | 5,573 行，状态均为 0～6 整数，无缺失和重复键 | 该日源端代码集合与 DG 完全一致 |
| `000001.SZ`，20151231、20200102 | 各 1 行，状态分别为 4、1 | 跨年代样本可获取；不等于所有日期已验证 |

三字段请求只用于上述有界调研，不建立三字段的 Tushare 子契约。正式下载使用完整 19 字段。原方案已有对象、日期、区间、分页的历史验证；本次不改时间模型，不重做无日期全市场读取。MCP 没有暴露 limit/offset，其结果不作为项目 connector 分页验收；本轮已另经项目真实下载器验证完整 19 字段、分页合并、短页及空末页，实际范围与结果见 §13.2。

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
| 0.3.3 字段来源、存储与键 | §4.2、§5.1；新增列尚未迁移，原列维持现行类型 |
| 0.3.4 需求追溯 | R01～R11、§9 测试及 §10 分阶段验收；实现后补最终符号与实际结果 |
| 0.3.5 Prod 长任务 | §6.4；管理员免测决定及未实测边界见 §8.2，功能恢复验收保留 |
| Definition 全部事实组 | §4.3；只列本次允许变化及必须保留的当前值 |
| DAO、迁移、Ingestion、Ops、配置 | §5、§6；均为设计，未声明已实现 |
| DG 非 Tushare 来源 7A、字段与发布 | §7、§8.3；白名单为 Prod 原始表，全局读取、正式提升和事件仍须分别批准 |
| 测试、性能、发布与恢复 | §8～§10；生产通过记录当前为空，不能预填 |

## 4. 完整字段与数据集事实

### 4.1 时间、执行和审计三层

| 层次 | 当前及本次口径 |
|---|---|
| 时间输入 | 支持单个交易日或日期区间，`ts_code` 保持现有过滤语义；历史补录只接受冻结范围，不增加对象过滤输入 |
| 执行 unit | 正常维护继续由 resolver 生成；专用历史补录按一个交易日构成独立业务提交边界 |
| freshness/audit | 继续按交易日，观测字段为 `trade_date`；补一个新字段不改变旧日期完整性定义 |

基线范围为 2010-01-04～2026-11-10。执行时若日更已产生后续日期，先刷新并冻结新的截止日、日期集合、统计和检查清单；不能自动把后续日期加入已批准计划。源端更早有数据不构成本次扩展历史起点的理由。

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

一个日期内完成：匹配与值检查 → 原始表指定列更新 → 服务表指定列更新 → 读回两表新值 → commit。任一步失败只回滚这个未提交日期；已经提交的其他日期保留。

初始 NULL 表示尚未补齐。源端与已存在非空状态不同，或两表非空状态相互不一致时停止解释，不把本次补齐变成已存在状态的自动纠错。两表均已完整、合法且值相同的日期可按 §6.4 读回判定已完成。新方法本身不限制为 NULL，限制来自本次历史服务。

## 6. Prod 正常同步与历史维护 LLD

### 6.1 正常同步

在 `market_equity.py` 的现有 Definition 追加第 19 个 `source_fields`；日期、过滤器、分页策略、`write_path=raw_core_upsert` 和 `commit_policy=unit` 保持现行含义。新增字段不加入小数字段清单。

当前 `coerce_row()` 只按已有清单把交易日期转为日期对象、把原数值字段转为 Decimal；每日指标当前没有专用 `row_transform`。本次新增的状态检查不计算状态、不取整、不把字符串转成整数、不补 NULL 或 0。完整字段缺失，或状态为 NULL、非原生整数、布尔值、0～6 之外的值，均为校验错误。

管理员已确认：遇到本数据集校验错误，当前任务失败并停止后续日期，不沿用通用 normalizer 的“丢弃坏行后提交其他行”。必须在当前日期写入前完成所有源分页的校验；该日期两张表都不提交，之前已提交日期保留。工作流中的该步骤失败后也停止，不因 `continue_on_error` 继续本次每日指标扩充。此要求仅适用于本次每日指标校验，不改变其他数据集的拒绝策略。

错误在任务详情直接展示交易日、股票代码、股票名称、字段名称、原始值及类型、合法范围和具体原因，由管理员处理后重试。名称从现行股票服务表 `core_serving.security_serving` 按出错代码有界读取；源接口不提供名称，禁止补一个猜测名称。没有可用名称时明确显示“股票名称缺失”并保留代码，不让名称查询错误掩盖原始数值错误。名称是当前服务表名称，不宣称为历史交易日当时名称。例：`2010-01-04，000001.SZ（股票名称：当前服务表名称），收盘涨跌状态 limit_status 原始值 1.5（float），应为 0～6 的整数；该日期未提交，任务失败，等待管理员处理。`

具体接线、reason code、已提交进度及工作流停止规则见 §6.6。它们是后续扩充设计，不属于 §12 已交付的两个修复。

正常链路仍为 `DatasetDefinition → DatasetActionResolver → request builder → source client → normalizer → 原整行 writer`。本次历史动作不会被手动维护、workflow 或 schedule 默认调用。

### 6.2 独立维护入口与配置审计

拟新增维护动作 `maintenance.fill_daily_basic_limit_status`，中文为“补齐每日指标收盘涨跌状态”。复用既有维护动作 PLAN/APPLY、general worker、TaskRun 详情、取消和重试入口；不改变 `daily_basic.maintain`。

管理员接受该一次性补录占用串行 general worker，人工选择后半夜平峰窗口。保留显式日期范围输入，但不为让出 worker 新增自动分段、抢占调度、worker、队列或服务；不承诺此窗口内其他通用任务同时执行。

| 配置/输入 | 默认、来源和保存位置 | 消费者、生效与限制 |
|---|---|---|
| 新维护动作及 executor key | 代码注册；`src/ops/action_catalog.py` 与 `ops_worker_factory.py`；尚未实现 | 既有维护目录、手动入口、dispatcher；人工可用，schedule 不可用，retry 可用 |
| `execution_mode` | 复用现有 PLAN 默认；请求意图存 TaskRun | PLAN 只读并冻结，APPLY 必须引用原 PLAN id/hash |
| `start_date/end_date` | 必须显式填写；没有自动扩展默认范围；存 PLAN/TaskRun | resolver 按 Definition 归一化，不能从源参数反推日期模型 |
| `plan_task_run_id/plan_hash` | APPLY 必填，复用既有维护重放合同 | dispatcher 验证同一动作、成功冻结及范围；执行时不重新规划 |
| 更新列与目标表 | 代码固定两表与 `limit_status`，并写入冻结计划 | 不提供运营任意字段名、表名或 SQL 输入 |
| SQL 批次 | Settings `sync_batch_size`，代码默认 1,000；运行值必须冻结 | 新方法复用，不能改动旧方法或静默放大运行配置 |
| 分页 | Definition 现有每页 6,000 | 源请求、分页完整性；不是每日永远最多 6,000 行的保证 |
| 源响应字节、传输时限、单日期行数/内存与总规模 | 无本次专项实测，按 §8.2 管理员免测决定记录实际参数及来源；不虚构新上限 | 不新增全局配置；保留已有必填执行限制；免测不代表无限制或已测通过 |
| 本动作接收字节预算 | §6.8 `execution_config.max_response_bytes`，无默认值，执行准备时由管理员给定并冻结 | 只用于本动作 planner/接收器；缺值阻止冻结；不是其他数据集的限制或本轮实测值 |

新参数不写入新 env 文件或配置表。配置仍由各自现行事实源拥有，TaskRun 只保存此次批准的快照与意图。运营可从计划和详情看到实际值及依据。

### 6.3 PLAN 和来源读取

1. 通过 `DatasetActionResolver` 取得当次范围的日期 unit；使用一次按日期计数的聚合核对两表日期集合、计数和完整性。计划只持有日期、计数及有界描述，不装载全历史业务行。
2. 每日期冻结目标计数；冻结 Definition 完整字段/主键/存储映射摘要、代码版本、实际批次配置和 §8 的预算。PLAN 草稿以现有 `TaskRunMaintenancePlanContext` 保存，只有全部审计通过并原子冻结后 `apply_ready=True`。
3. APPLY 先读取该日期两表状态并判定能否跳过；未完成日期显式请求完整 19 字段。源参数仍来自现有 request builder；源范围允许额外代码时须列清并说明本次只匹配已有目标，目标缺失、重复键或日期不符均不能提交。
4. 分页只保留单日期的有界输入，禁止积累全历史。按冻结范围和现有分页规则处理；若实施入口要求数值限制，应记录实际取值与代码来源或管理员决定，不能把未实测的数写成测量结论；超出已有限制停止，不临时抬高。
5. 本次历史补录只使用新增列；源端返回的原 18 字段不用于覆盖已有值。正常同步继续使用其完整字段合同。

`TushareSourceConnector.call_bounded` 已有可终止调用，但 `TushareHttpClient.call_bounded` 和 `bounded_tushare_call.py` 各有一层合同检查，目前只识别公告默认分支、`stock_weekly_adj/v1` 和 `index_period_raw/v1`。两层均须增加 `daily_basic/v1`，绑定 `api_name=daily_basic` 与完整 19 字段，不能把新任务伪装为指数/公告合同。通用 source client 带 control 的现行分支会指定指数合同，新历史服务不能直接借该分支绕过检查；复用原 request builder、分页规则及底层有界调用，使用本数据集合同。旧三类合同、未知合同拒绝及其错误行为分别回归；失败不得交付或进入正式执行。执行参数见 §6.8，不增加专项测量前置条件。

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
| 拟新增 `src/foundation/ingestion/daily_basic_limit_status.py` | PLAN 所需事实与单日期补录业务服务；只依赖 Foundation，注入取消/进度接口 |
| `src/foundation/clients/bounded_tushare_call.py` 及对应 client 传递 | 新响应合同分支，旧合同不改 |
| 拟新增 `src/app/runtime/daily_basic_limit_status_task_executor.py` | 维护协议与 Foundation 服务的组合适配，独立业务 Session |
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

验收必须覆盖：先提交日期 A、日期 B 仅一行状态为 1.5、日期 C 未执行；B 两表零提交，A 与其节点数量保留，TaskRun/活动节点失败且详情可见代码、名称、B 日期和原始值。工作流在已有成功步骤、`continue_on_error` 两种条件下仍整体失败。另用其他数据集的部分拒绝及普通工作流失败证明旧策略没有变化。§12 的维护任务回归不能替代这些测试。

上面的数量恢复须区分单位：dataset action 的 unit_done 是日期数；workflow 的 unit_done 是成功步骤数，不能用本步骤已提交的日期数覆盖工作流步骤进度。本步骤的日期进度存节点/诊断，行数才按步骤累计。

### 6.7 新维护适配器如何进入既有 PLAN/APPLY

`daily_basic_limit_status_task_executor.py` 同时实现现有 `TaskRunAwareMaintenancePlanner.plan_for_task_run` 与 `TaskRunAwareMaintenanceExecutor.execute_unit_for_task_run`；注册动作的 `execution_config.plan_apply_replay=True`，只允许人工 PLAN/APPLY。不能只实现普通 `plan/execute_unit`：那样 dispatcher 不会注入 TaskRun 的取消/进度上下文。新动作的普通无上下文方法明确拒绝执行，不提供绕过 PLAN 的入口；既有动作不改。

| 阶段 | 输入、持久化及调用规则 |
|---|---|
| PLAN | 注入 `TaskRunMaintenancePlanContext`，调用现有 resolver 生成日期。按日期聚合核对两表数量，逐批保存日期描述草稿、阶段和进度；每批前后检查取消。描述不含全历史股票明细。只有完整校验后冻结既有 schema_version=1 的维护 snapshot、hash 和 apply_ready，取消/失败草稿不可 APPLY |
| 冻结 metadata | `contract_kind=daily_basic_limit_status/v1`、dataset/action、显式起止、日期集合、每日期两表计数、Definition/代码摘要、固定两表/键/列、实际 `sync_batch_size`、§6.8 控制参数与来源。业务合同版本放 metadata，不升级共享 snapshot 格式或改变其他动作重放 |
| APPLY | dispatcher 使用现有 `_load_replay_apply_units` 校验动作、hash、范围和成功冻结，直接重放原日期 unit；适配器再核对本数据集合同摘要与运行配置。不得重新解析出更多日期、静默换字段或采用当前新批次配置 |
| 单日期 | 接受 `MaintenanceTaskRunContext.task_run_id/run_context`；适配器按下述方式接出取消/进度，Foundation 只接收接口，不 import Ops。业务使用独立 Session；源读取完成后才开始该日期双表事务，状态 Session 不参与业务事务 |
| 返回 | unit 返回现有 `MaintenanceExecutionResult`，计数只表示已读回并确认提交的结果；恢复读回后判定已完成也报告覆盖量，同时区分本次实际变更量，不能用 UPDATE 返回 0 推断没有完成 |
| 取消/失败 | replay 分支当前没有替 executor 自动覆盖 unit 内取消，新适配器必须在每日期和每页/SQL 子批次前后检查。已有 §12 修复负责保存已返回 unit 累计；当前 unit 内分批观察不等于已提交。进程退出、commit 回执不明时按 §6.8 读回 |

适配器的观察线程不能直接使用注入上下文持有的原 Session。取消读取复用 `TaskRunIngestionContext(independent_cancel=True, timeout_seconds=2)` 的独立查询；2 秒沿用同一 TaskRun 策略的 observation_timeout_seconds，不借用业务耗时预算。进度在本动作适配器私有方法中用独立事务保存 TaskRun 合计、当前日期/阶段及活动日期节点的本日数量，并设置同样的局部观察超时。当前 `TaskRunIngestionContext.update_progress` 会把全任务合计复制给当前节点，不能直接用它给逐日期节点报累计行数；不修改其既有调用行为。未提交日期节点保存量为 0，已读回确认提交后才写本日量，避免失败时把先前日期行数算到本日。观察异常只影响状态显示，不抛进业务事务；已确认提交的 unit 应先返回结果，由 dispatcher 保留累计，再在下一日期开始前处理取消。

### 6.8 正在请求和正在执行 SQL 时的取消

根规则要求长任务不超过 30 秒没有可见更新，可能超过 30 秒的不可分割步骤须能中断；这是执行要求，不是本次测量结论。控制频率复用当前 TaskRun 周线复权策略中取消轮询 2 秒、进度更新 5 秒的现行交互频率（`stock_weekly_adj_contracts.py`），适用理由是同一任务页面与取消入口；不借用该数据集的行数、内存或性能预算，也不跨数据集 import 其 policy。

- **源请求：** 新动作使用 §6.3 的 `daily_basic/v1` 有界子进程调用。每页前后取消检查；等待接收时沿用现有最多 0.2 秒轮询与 terminate/join/kill 清理，不把同步 requests 的重试等待当作可取消实现。重试前重新检查取消，取消后不再发请求。保持原每页 6,000，不把试验分页大小写回 Definition。
- **内存和输入值：** 每日期允许保留的目标键/状态数取冻结的当日目标计数；源代码集合须与目标一致，超出或缺少均停止解释，不自动放宽。最多页数为 `floor(目标计数/6000)+1`（整页时包含空终止页）。响应 `max_response_bytes` 没有可直接复用的每日指标依据，不能抄其他数据集的 8 MiB。该值在正式执行准备时由管理员给定，作为新动作注册 `execution_config` 中的必需预算值，随 PLAN 冻结；无值不得冻结 APPLY。默认值为空、来源为动作代码配置、作用域仅此动作、消费者为 planner/有界接收器，修改后重启 worker 并重新 PLAN；不增加 env、数据库或前端任意参数。该值是执行决定，非性能保证；免测照常生效。
- **请求和 SQL 截止：** 新动作每次源调用总截止、每条 SQL 的 `SET LOCAL statement_timeout` 均为 30 秒，依据上述不可分割步骤边界，不声称代表耗时测量。不能改全局连接参数；连接归还前清除当前操作状态。超时回滚未提交日期并失败，不自动扩大限制。statement_timeout 不能保证网络回执时限，COMMIT 结果按下述方式读回。
- **执行中的 SQL：** 2026-11-11 本地驱动核实为 psycopg 3.3.4、libpq 18，支持跨线程 `Connection.cancel_safe(timeout=...)`。适配器在本任务内使用一个观察线程，独立 Ops Session 轮询取消和保存可见阶段；它不使用业务 SQLAlchemy Session 查询。主线程仅在当前 SELECT/UPDATE/COMMIT 操作期间登记该 psycopg 连接，并标明操作种类；观察线程对这次登记调用 cancel_safe，timeout 取同一进度更新间隔 5 秒，避免取消请求本身长时间阻塞观察。普通未提交 SQL 收到取消错误后 rollback 当前日期；COMMIT 则必须按下述独立读回处理，取消未确认不能报告已回滚。
- **连接和线程生命周期：** 连接登记带当前操作序号。取连接/标记正在 cancel 用同一短锁；主线程撤销登记并等本次 cancel 返回后，才允许复用该连接执行下一 SQL。不得持这把锁等待线程退出、执行数据库请求或归还连接，防止等待环路；任务结束停止并回收观察线程。cancel 通信失败则关闭/失效该业务连接，不把可能被迟到 cancel 的连接放回池。状态写入失败只影响观察状态，不触发业务回滚或取消。
- **COMMIT 与回执：** commit 前先检查取消；已经进入 commit 后若收到取消或超过上述截止，按同一操作序号发起取消，但取消返回不能证明事务没提交，也不能继续领取下一日期。commit 取消、回执丢失或连接断开时，以新独立只读事务按计划键分批读回两表：都与本次已校验源状态一致才记为已提交；仍为原状态则记未提交并停止；一表不同、键缺失或其他值则报结果未确认，停止管理员处理。读回各语句沿用上述超时，不等待未知连接回到池后再查；读回也失败则保留未知结果，重试仍先读回，不能算成功或贸然重写。取消后不把读回扩成下一个日期的源请求，§6.4 续跑复用同一判定。源/SQL 取消调用均不能保证网络故障时瞬时结束，观察线程须持续显示“取消处理中”或“确认提交结果”，不得报虚假的取消完成。

依据：[Psycopg Connection.cancel_safe](https://www.psycopg.org/psycopg3/docs/api/connections.html#psycopg.Connection.cancel_safe)、[PostgreSQL statement_timeout](https://www.postgresql.org/docs/current/runtime-config-client.html#GUC-STATEMENT-TIMEOUT)。API 已查官方文档；本轮没有连接数据库试验取消，不能写成已验收。自动化须覆盖源挂起、SQL 锁等待时取消、cancel 与语句结束竞争、提交回执丢失、观察失败及连接池不受迟到取消影响。

## 7. DG 新结构与重新 bootstrap LLD

### 7.1 19 字段正常日更

在 `DAILY_BASIC_COLUMN_SPECS` 末尾追加整数状态；派生 schema、catalog、asset definition metadata、检查说明和测试同步。日更与历史转换都只对原 16 个数值字段调用小数处理，对状态检查原始整数；不能因 DuckDB 能把小数 CAST 为整数就接受错误值。

日更的最近 10 日期窗口、17:00 注册/19:00 更新观察时刻、900 秒间隔，以及原 1 秒请求间隔、12 次请求/3 次重试、60 秒接收截止的本族规则保持原定义。这些是已存在规则，不是本次新增预算；60 秒仍不等于 SDK 保证在 60 秒内结束。新结构切换期间不得启动本族日更去读取混合 schema。

### 7.2 一次正常导出与候选构建

Prod 新增列验收完成并确认冻结范围稳定后，沿用 `daily_basic_history_cli` 的 `plan/export/build/audit/promote` 及事件阶段。新增显式 `--replace-existing`，默认 false：

- false：原导入路径的默认行为和异内容拒绝规则不变；旧 18 字段报表不能作为新结构执行输入。
- true：只允许在新的完整计划中记录批准的 18→19 字段替换意图；它不是任意覆盖开关。计划冻结来源、旧字段投影、日期/键、旧文件校验值、旧物化/检查 id 和预算；候选尚未生成，随后在不可变审计报告中冻结，不能回写已封存计划。

来源只允许 `raw_tushare.daily_basic` 完整 19 业务字段，日期显式转为 YYYYMMDD。使用现有 `(ts_code, trade_date)` 主键分页，每批最多 10,000 行，每批独立只读事务，不按历史日期反复查询原始表，不使用 OFFSET 扫历史。必须复查 EXPLAIN，无排序或顺序扫描放大才放行。

正常完成只导出一遍，并以冻结导出为后续输入；中断仍沿用原工具的已落盘前缀重核，再继续，不因为换入口放弃这一已确认修正。导出依赖管理员确认的来源稳定窗口，不宣称短事务构成整个历史的一致性快照。

候选与中间产物仅位于 `/Volumes/datasource/data_lake_staging`，继续由 DuckDB 按年度分流、按日期生成每日期一个 `part-000.parquet`。不得将第 19 个字段当作目录分区推断出来的字段，所有内部字段检查关闭 Hive partition inference。

### 7.3 审计与受控替换

候选全部完成以下核验后才允许开始正式替换：

1. 19 字段名称、顺序和类型，日期/文件归属、主键唯一、源状态合法性，以及来源导出与候选的完整 19 字段双向对账。
2. 候选的前 18 字段与原 DG 文件做双向对账，键及每日期行数一致；差异停止解释，不能以“Prod 是新来源”为由顺带改旧数据。
3. 文件清单、候选校验值、旧文件校验值、旧最新物化/检查 id 与批准计划一致；确认本族日更/检查任务已停止且没有活动 run。

`make_history_plan`、`audit_daily_basic_history`、`promote_daily_basic_history` 都须识别显式替换计划，不能只删除 `history_target_conflict` 检查。提升继续使用本族日期锁、同文件系统确认及逐文件 `os.replace()`。仅允许目标仍是计划中的旧文件，或已是本批次核验通过的新文件；第三种内容一律停止。

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
- 当前 `plan_daily_basic_events` 的旧身份冲突不再一概当并发错误：仅当旧 id/旧文件对应批准计划，才允许登记其后的本次新记录；不在计划中的失败、运行中检查或并发物化先阻断。
- 当前 `apply_daily_basic_events` 的“已有检查就跳过”必须细分：已绑定本次新物化且内容身份一致则跳过；绑定批准旧物化则需重检并追加；其他目标停止。
- 非 `K` 日期追加文件生成记录，但不制造检查成功。readiness 仍要求当前文件、最新物化及目标一致的检查全部满足；历史 materialized 不等于全历史 ready。

事件写入与文件写入使用同一日期锁路径：`<staging_root>/daily_basic/locks/<trade_date>.lock`。物化阶段在日期锁内核对当前文件及当前物化 id，再登记；检查阶段再次取得该日期锁，重新核对文件与物化，登记缺少的检查并读回目标。两个阶段之间不长期持锁；文件若在间隔中变化，检查阶段必须停止，不能登记绿色结果。每次只持有一个日期锁，取得失败立即报错，不等待；不在持日期锁时取得历史工作目录锁或 CLI 事件发布锁。已有 CLI 全局事件锁和历史工作目录锁仍由各自入口先取得，锁文件不删除，以免同路径出现不同 inode。具体本轮修复见 §12。

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

以下结构只用于新的显式替换计划。普通首次导入继续读取原 schema_version=1 的报告及原参数含义；替换使用 schema_version=2，并由 `_validate_plan` 显式分派。不能让旧报告缺少新字段时被默认值补成可替换计划。所有 fingerprint 沿用现有报告封存算法；封存后不增补字段、不改日期、不覆盖旧批准。

| 文件/报告 | 必需字段及冻结时点 |
|---|---|
| `plan.json` | 保留现有来源、日期、限制、calendar SHA、source/cost evidence；新增 `replacement.mode=add_limit_status`、原 18 业务列顺序、完整 19 业务列、`dates=D/check_dates=K`、各日期旧文件 `path/sha256/rows/schema_hash` 和下述旧事件身份。首次 plan 完成即封存。尚无候选 SHA，不把候选填回 plan。旧 18 列清单只作迁移比较，不形成新的 Tushare 子契约 |
| `export.json/build.json` | 继续绑定同一个 plan fingerprint；导出批次、前缀重核和候选路径沿用现有合同。仅在识别替换版本时允许旧目标存在；不取消来源限制或其他 stop_reasons |
| `audit.json` | 全部 D 候选完成后封存，绑定 plan/export/build fingerprint；保留现有 `files[].date/path/sha256/rows`，每项增加完整 schema 摘要、计划旧文件 SHA、原 18 列双向比较结果和完整 19 列来源比较结果。任何日期不符则报告不可提升，不能只审小样后放行全部日期 |
| `promote.json` | 绑定 plan/audit fingerprint；`selected_dates` 是本次选取，`completed_dates` 是累计实际确认的新目标日期；`files[]` 保留每个已完成日期的旧/新 SHA 与路径。现行入口每次把 files 初始化为空，替换分支必须改为读回旧进度并与实际文件重核后合并，不能在续跑时清掉累计列表。此报告可追加推进，不得被用作新物化归属的固定身份 |
| 事件执行清单 | 绑定固定 plan/export/audit fingerprint、本次 promote fingerprint、`selected_dates`、该范围文件 SHA、当前物化/检查身份与 `state_fingerprint`，并列出待追加物化/两项检查。promote fingerprint 只证明本次清单生成时的进度；物化归属仍只用固定 plan/export/audit 与新文件 SHA。继续保留现有清单新鲜度、500 日期批次及事件返回上限 |

**旧身份在首次计划读取，不在替换后倒推。** 每日期的 `old_materialization` 为 null 或 `{storage_id,run_id,timestamp}`；每项 `old_checks[check_name]` 为 null 或 `{event_storage_id,status,target_storage_id,target_run_id,target_timestamp}`，连同检查名称、partition 保存。计划前先按现行身份规则核对旧文件与这些记录。失败、运行中或目标本已不一致的检查先停止处理，不把它们批准为可以忽略的旧记录。检查范围 K 从这些旧记录与最近窗口推导；不能在后续阶段重新挑一个更小的 K。

**具体允许状态：** 锁内分别读取当前文件 SHA、最新物化、两项检查。文件只能是计划旧 SHA 或审计新 SHA。当前物化只能等于批准旧身份，或 metadata 的 `delivery_method=prod_history/source_system=prod_raw_db/date/file_sha256/history_plan_fingerprint/history_export_fingerprint/history_audit_fingerprint` 全部等于本批新身份；检查只能等于批准旧记录，或实际成功且目标的三个身份字段对应本次新物化。任一其他新事件、失败/运行中检查、同名但不同来源物化均停止。无旧物化的日期允许 null→本次新物化；无旧检查的日期仅在 K 内新增检查。各项读取与写后确认均按 §7.4 的非阻塞日期锁规则，事件本身不能靠文件锁阻止的竞争仍由身份读回拒绝。

**中断重做事件 PLAN，不改父计划。** apply 前将当前状态与这份新鲜执行清单匹配；物化/检查写出一部分后 state_fingerprint 改变，必须重新生成清单，只列剩余项。可以保留批准旧检查及已完成的本次新检查混合状态，不能因为另一项仍旧就重复物化。新检查绑定错误或失败均保留现场并停止。实际新文件已存在而 promote 进度未写成时，以审计 SHA 重建累计进度；未确认文件不纳入 completed_dates。

现行 promote 内部会再调用 audit；替换分支必须区分首次审计与提升前重核。旧目标仍在时，重核旧 SHA 并比较原 18 列；目标已是审计新 SHA 时，原文件已不存在，复用已批准审计中的旧列比较证据，重新确认候选和当前目标 SHA，不能要求把新目标重新当 18 列旧文件读取。新旧之外停止。重核结果不替换批准 audit，不把每次重核的耗时/进度字段变成新的 history_audit_fingerprint，否则已经写出的物化会失去归属。

**小样无需先替换全部文件：**

1. 对全部 D 完成候选审计，批准固定 audit fingerprint。`--replace-existing` 只允许在 plan 阶段提供并写入不可变计划；后续阶段不能临时打开覆盖。替换 promote 的 `--fingerprint` 校验该 audit fingerprint（它已绑定父 plan 和全部候选/旧身份）；普通导入仍校验原 plan fingerprint，不改变原义。
2. 替换 promote 支持既有 `--sample-date` 从 D 选一天；无 sample-date 时选择 D。事件阶段在替换版本中只要求 `selected_dates ⊆ completed_dates ⊆ D`，不用现行的“所有 D 已提升”前提；audit 仍必须覆盖全部 D。既有普通导入的前提和 sample-date 限制不变。
3. 依次处理 §7.5 三类日期：该日期 promote→plan-events→report-events→audit-events。无旧检查且不在 K 的样本只新增物化；其他两个样本各实际运行两项检查。按现有基线推导为 3 个文件和 `1+3+3=7` 条事件，不是固定的样本上限，执行前核对各日期归属。小样以外旧文件和事件尚不改动。
4. 小样通过后提升剩余日期，再为剩余日期生成事件清单；样本的新物化始终绑定同一个 plan/export/audit，后续 promote 追加进度不会令其变成外部记录。中断后同样按物理事实计算 remaining，不生成一个换了父 fingerprint 的小样子计划。

CLI 当前只允许 report-events 携带 sample-date；替换版本须明确让 plan-events/report-events/audit-events 都传递同一选择，并写进事件清单；register 只登记清单所需分区。APPLY 的选择必须与批准清单相同，不能带另一个日期或省略选择后扩大范围。无 sample-date 的替换事件规划以当前累计 completed_dates 为所选范围，并识别其中已完成项；最后验收另外要求 completed_dates=D、K 的检查全部当前有效。

额外读取成本如实累计：所有候选先完整审计；每次现行 promote 仍有候选重核；每次事件 PLAN/APPLY 只处理所选日期，但完整执行与最终验收仍覆盖全部 D/K。日期小样的目的为一致性验收，不追加性能测量。测试须证明小样在全量提升前可完成、后续提升不改变已写事件归属、promote 进度写失败能恢复、只写一项检查可续跑，以及非 K 日期没有伪造绿色检查。

## 8. 性能与读取预算

### 8.1 已有依据与可复算规模

| 项目 | 数字与计算 | 性质、适用条件 |
|---|---|---|
| Prod 历史补齐 | 每表 14,482,741 行；两表首次全补最多涉及 `14,482,741 × 2 = 28,965,482` 行更新 | 本次计数推导；已相同行不重复更新，源缺口会阻止完成 |
| Tushare 请求 | 若所有日期仍与目前单日计数一致且每页 6,000 行，4,091 个日期各一短页，约 4,091 次请求 | 条件估算；原 DG 单日最大 5,602 行；源变化、整页终止探测和重试另计 |
| DG Prod 导出 | `ceil(14,482,741 / 10,000) = 1,449` 个非空批次，现有工具另需 1 个空终止页，即 1,450 次业务页查询 | 不含 schema/index/EXPLAIN 检查；每批 10,000 来自现行合同 |
| DG 正式文件 | 4,091 个待重建文件，原文件 771,774,454 字节 | 当前文件事实；不能以 18 列体量直接承诺 19 列大小 |
| DG 状态发布 | `4,091 + 55 × 2 = 4,201` 条 | 当前 `D/K` 推导；刷新后按清单计算 |
| DG 索引读取 | 500 日期一批，`ceil(4,091/500)=9` 个日期批次 | 沿用原代码；物化分页另计，已有 20,000 条返回限制保持，超限先审计而非静默扩大 |

历史参考：原 LLD 记录 2026-09-15 的 18 字段导出 14,288,011 行，实测 2,427.37 秒；按日候选 761,591,306 字节；本地审计函数 17.54 秒，峰值 RSS 约 5.14 GiB。这些记录保留原范围和类型，不能照搬为本次 19 字段 SLA 或预算，原方案的倍率/余量也不沿用。

### 8.2 管理员决定不另做专项性能测量

2026-11-11 管理员明确决定：本专项不再安排额外性能测量，不以测量未完成阻止修复或后续开发；全历史补录由管理员人工安排后半夜平峰窗口。这是管理员接受未知耗时的执行选择，不是“小数据已实测通过”、耗时承诺或对全仓性能治理的修改。功能校验、取消/恢复和数据一致性测试照常保留；本轮只开发 §12 两项修复，不执行全量正式任务。

| 未实测项目 | 本次处理 | 保留的边界 |
|---|---|---|
| 指定列更新耗时、数据库日志/空间 | 不追加专项基准测试 | 正式写入仍需批准；同日两表事务、旧列不变仍须正确性验收 |
| 新响应字节、取消耗时、峰值内存 | 未实测，不写保证值 | 保留源分页、单日期内存与可终止调用设计；参数须记录现行来源或管理员决定 |
| Prod 续跑成本 | 已完成日期仍可能全部读回一遍 | 不把逐日主键匹配改成逐日扫描整个原始表，不宣称零成本 |
| 19 字段磁盘与 DuckDB 峰值 | 记录阶段内同时存在的导出、年度中间、候选与提升副本 | 不自造磁盘余量或扩大现行资源配置；正式执行前仍核对可用空间 |
| DG 首次、样本、续跑及验收 | 正常导出一遍；导出中断重核前缀；promote 现行入口重做候选审计；事件清单重建及 APPLY 仍有文件校验读取 | 不以免测为由删除审计、跳过旧身份核对或反复重拉 Prod |

现有入口要求的 `max_source_rows/max_source_seconds/max_stage_seconds/max_spill_bytes` 等执行输入保留；不删除必填检查、静默抬高现行限制或新增没有依据的数字。未来阶段按实际代码和配置冻结运行值；需要管理员给定取值时如实标记为执行决定，不标记为实测。免测不构成生产操作批准。

按当前调用链，一次单独生成事件 PLAN 再完整 APPLY，至少读取全部目标文件校验值三遍：外部 PLAN、APPLY 内重新规划、写物化前校验；检查日期另外读取 schema/覆盖与校验值。重新生成清单、样本和最终验收各按实际调用累计，不能只记录事件写入条数。本轮日期锁修复不增加全历史源或文件扫描，检查写后读回只覆盖原最近窗口。

DG 沿用现有 DuckDB 16GB/4 线程资源配置，不把它解释为本次实测需求；候选 spill 位于本批次外置 staging，审计沿用禁 spill 规则。原始 18 列文件、冻结 19 列导出、年度中间、候选、提升临时副本的同时存在量须逐项相加。每一遍完整旧文件校验值读取按当前清单约 736.02 MiB 计算；候选读取另计，不能把重复读取说成独立数据量。

### 8.3 全局读取审批清单

本次文档编写没有批准或执行以下全局业务读取。正式操作前分别说明并取得明确批准：

- Prod 新字段补录会按日期有界读取全历史目标键/新增列并更新两表；整体验收对原 18 列的核验范围及方法列入同次方案，不能把计数例外扩成全量内容比较。
- DG 导出会完整读取 Prod 原始表冻结范围的 19 业务字段，约 1,448 万行，正常一遍；中断续跑可能重读已持久前缀，应单列其最坏开销。
- DG 候选审计会读取全部冻结导出、全部候选，以及旧 DG 原 18 字段做内容对账；再按已批准次数核验正式文件和事件。源冻结后不额外重拉一遍 Prod 全历史。

任一阶段失败先使用已冻结来源、候选和实际已提交事实判断恢复路径；不能以修复为名增加未经批准的全量重读。

## 9. 测试与验收矩阵

下列是完整扩充所需门禁，19 字段扩充均未实施；本轮两个修复的实际状态单独记录在 §12，不预填其他项通过。真实样本、schema 与预期分别来自 §2/§4；预期值不得调用待测 helper 生成。

| 测试组 | 正向与反向要求 | 拟落点/现有回归 |
|---|---|---|
| 新 DAO 方法 | 只变指定列；0 值合法；相同值不重复写；缺匹配不插行；旧 18 列、系统列不变；非法更新列/主键不被当更新列 | `tests/test_base_dao.py`、`test_base_dao_batching.py`；增加真实 PostgreSQL 隔离用例 |
| 旧 DAO 能力 | 原重复键保留末条、缺键拒绝、绑定参数分批、新闻 surrogate id 行为保持；旧测试不能改成迎合新方法 | 现有 BaseDAO、新闻、行键、财务绑定参数及索引回归 |
| Prod 源合同 | 默认 18 与显式 19 区别；真实 connector 分页合并；缺状态、NULL、1.5、字符串、bool、范围外值均导致任务失败；同日两表不提交，错误包含日期/代码/当前名称/字段/原始值与类型/原因；合法 0、负估值、原 NULL 数值不误拦；不改其他数据集策略 | 拟 `tests/test_daily_basic_limit_status.py`；Definition/resolver/fields 测试 |
| Prod 两表事务 | 两表均匹配才提交；第二表失败回滚同日；另一日期已提交不受影响；已有合法正常变化可通过、不误拦新日期 | 同上及独立 PostgreSQL 集成 |
| Prod 长任务 | 中途取消、进程退出、同 PLAN 重跑、业务已提交但状态失败、无状态时业务值恢复、进度单调、TaskRun/node 终态；调用挂起时可取消且 30 秒内有可见状态 | 拟 `tests/web/test_daily_basic_limit_status_maintenance_api.py`、维护 executor 集成 |
| Prod 正常维护失败 | 一条错误阻止整日双表 writer；保留前日提交量；错误显示代码/当前名称/原值/类型；工作流已有成功步骤或允许继续时仍 failed；其他数据集旧行为不变 | §6.6 的 executor/dispatcher/worker 用例；不能以维护动作回归替代 |
| Prod 协议与取消 | TaskRunAware PLAN/APPLY 两个协议均注入上下文；取消草稿不可 APPLY；源挂起/SQL 等锁可取消；连接归还不受迟到 cancel；COMMIT 回执不明读回；观察失败不影响业务提交 | §6.7/6.8；隔离 PostgreSQL、真实驱动取消验收，源采用可控挂起替身 |
| Definition 消费者 | 现有维护/排程/工作流时间与过滤器不变；新维护动作不自动进入日常流程 | registry、resolver、catalog、manual actions、date completeness 既有测试 |
| 有界传输 | 新合同不改变公告/周线复权/指数周期线的解析、错误和取消；未知合同仍拒绝 | 对应现有 bounded-call/stream 测试及新合同测试 |
| DG schema/转换 | 完整 19 字段；状态严格整数；原 DECIMAL 精度、NULL、负值和顺序保持；18 列旧文件不能冒充新结构 | `test_daily_basic_contracts.py`、`test_daily_basic_raw_io.py`、`test_daily_basic_history.py` |
| DG 显式替换 | 默认路径仍拒绝异内容；批准替换可通过正常 18→19；旧列变化、目标被并发改写、候选损坏、跨文件系统拒绝 | `test_daily_basic_history.py`；按年源对账与逐文件提升 |
| DG 事件 | 同日期旧→新追加成功；检查目标三个身份字段均正确；旧绿色不跳过新检查；已有本次结果幂等跳过；计划外事件或失败检查拒绝 | `test_daily_basic_events.py`、`test_daily_basic_checks.py` |
| DG 部分完成 | §7.5 各状态均覆盖；文件已换而事件未写、只写物化、只写一项检查均能正确续跑；恢复后没有重复记录 | 同上；不能只测全成功 |
| DG 报告与小样 | schema_version=2 必填身份；旧版本默认行为不变；全部候选审计后可先提升样本并写事件；累计 promote 进度恢复；后续全量不改变样本归属；计划外身份拒绝 | §7.7 的 history/events/CLI 隔离测试 |
| DG 范围/性能 | `K=C∪W`，55 日样本不能退回仅 20 日；无历史检查日期不造绿；索引批查询，不逐日深读全历史 | `test_daily_basic_performance.py`、`test_daily_basic_sensor.py`、catalog/static gates |
| 业务读取回归 | 榜单、自选、Quote 旧字段/排序及相关查询保持 | 已有对应 Wealth/Quote API 测试；不新增前端功能 |

真实验收分开记录：隔离单元/集成证明方法与事务；有界源样本证明源合同；获批最小真实运行证明取消—续跑—读回与进度；完整正式执行及对账才证明历史全部补齐。任一层缺失都不能由“测试总数通过”代替。

## 10. 分阶段实施、读写边界与完成条件

所有阶段在当前 `dev-interface` 工作区推进，保留其他未提交改动，不创建分支/worktree、不自行提交或发布。此前管理员只批准实现 §12 两个修复，随后已按要求提交；本轮仅补齐具体设计和源接口验证。P1/P4 的扩充代码仍不在本轮范围。

| 阶段 | 目标、实现范围 | 读写/失败/恢复 | 放行与验收 |
|---|---|---|---|
| P0 设计核验 | 刷新 schema/head、完整合同、消费者和配置；按 §8.2 不增加专项性能测量 | 纯代码/统计/有界源读取；真实写样本另批；未实测如实记录 | 本文评审；实际运行输入来源明确；旧能力回归范围明确 |
| P1 Prod 代码与隔离验证 | 两模型、新迁移、新指定列方法、专用维护动作、完整日更与有界合同；实施前在本文记录最终符号 | 仅隔离资源；新方法不进入旧调用方；旧合同回归失败则停止 | §9 Prod 门禁；真实 head 与调用方审计；无旧能力变化 |
| P2 Prod 迁移与代表样本 | 批准后迁移两表、部署配套代码；实际运行/取消/续跑/读回 | 维护窗口控制冲突；不清表；只回滚未提交日期；状态失败不撤销业务 | 独立批准及真实证据；预算与空间仍适用 |
| P3 Prod 全历史补录 | 按冻结 PLAN 补齐现有日期；通过现有节点/页面观察 | 同日两表事务；完整日期可读回跳过；冲突停止；最终对账成本含在预算 | 明确全历史范围批准；目标行数不变；新增列源/归一化/匹配/变更/读回计数可解释；原列不变 |
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
| 扩充代码、数据库、Lake、事件变更 | 19 字段及补录尚未开发；未执行正式资源写入；两个现有修复见 §12 |
| 性能决定 | 管理员决定不另做专项测量，后半夜平峰执行；未知耗时如实保留，现有执行限制不变 |
| 已确认修订 | 校验错误任务失败并给代码/名称/数值原因；文本 SQL 保持旧列；DG 旧身份冻结、重新规划续跑及日期锁 |
| 后续证据落点 | 本文对应阶段回填最终代码位置、命令/范围、测试、源/归一化/拒绝/写入/目标计数、性能与恢复验收；不另存第二份主方案 |

文档完整性检查只能证明索引/链接等检查范围通过，不能证明上述待开发能力、预算或生产验收已经完成。

## 12. 本轮两个现有问题的修复 LLD

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
3. 保持原物化批次与检查批次顺序；物化阶段在日期锁内检查校验值和批准物化 id，然后登记。沿用原批量读取最新物化的步骤读回；无需为所有历史日期额外增加逐日期事件深查。
4. 所有日期的物化沿用现有批量查询读回并核对交付信息，包括没有检查的历史日期。检查阶段只对原最近窗口日期重新持锁，锁内有界读取该日当前物化，重新审计文件和交付信息；确认一致后绑定 `storage_id/run_id/timestamp` 追加缺少的检查。两项写完读回这两项检查和当前物化，任一不对应即失败，不报告整体成功。锁只限制文件写入；计划外并发事件仍由现行身份检查拒绝。
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
