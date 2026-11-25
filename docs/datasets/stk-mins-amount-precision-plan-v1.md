# Prod 股票分钟行情成交额精度改造方案 v1

- 日期：2026-11-25
- 状态：阶段 1 开发和隔离验收完成，详见 [LLD 验收记录](stk-mins-amount-precision-low-level-design-v1.md#8-阶段-1-独立验收记录)。阶段 2 生产切换待执行。
- 范围：Prod 股票历史分钟行情 `stk_mins` 的成交额写入、Prod 消费者和 DG 从 Prod 取数。覆盖 Tushare 原生 1、5、15、30、60 分钟。成交额单位为元。
- 依据：[股票历史分钟维护说明](stk-mins-dataset-development.md) · [Tushare 股票历史分钟行情 0370](../sources/tushare/股票数据/行情数据/0370_股票历史分钟行情.md)

## 1. 目标与现状

新入库的成交额精确保留 Tushare 响应中的十进制数值。已经入库的历史数据保留原值，本期省去历史重新下载、回刷和物理重写。股票分钟四价、成交量、频率、时间和交易时段继续用现有规则。指数、ETF、本地股票分钟图接入算子库各按原专项处理。

本专项的审计、迁移预检及验收禁止全局、全量读取和扫描业务数据。只查系统目录、既有任务状态和有业务键限制的样本。禁止读取整表、遍历全市场或全历史，也禁止借统计、导出、批次拆分或验收重算完成等价的全量读取。

2026-11-25 只读生产系统目录核验如下。行数是 PostgreSQL 目录估计。容量来自叶分区的实际关系大小，含索引。核验没有扫描业务行情。

| 对象 | 实际结果 |
| --- | --- |
| PostgreSQL | 16.13 |
| `raw_tushare.stk_mins.amount` | `REAL`，单精度 |
| `core_serving.equity_minute_bar.amount` | `REAL`，由原表普通视图直接投影 |
| 原表叶分区 | 按月及默认分区共 325 个，其中 11 个已分配数据页 |
| 数据量 | 约 3.69 亿行，表及索引合计 57,222,864,896 字节，约 53.3 GiB |

2026-11-17 贵州茅台 15:00 的 30 分钟成交额源值为 1,228,092,577 元，经 Prod `REAL` 入库变成 1,228,092,544 元，DG 继承该结果。旧湖逐股直拉历史样本的差异在迁入 DG 前就已存在，现有证据不足以判定当时 Tushare 返回了什么。本方案处理已经定位的 **Prod 入库精度损失**。 2026-11-25 切换前复查按 `600519.SH`、30 分钟、`2026-11-17 15:00:00` 的完整主键只读一行，Prod 仍为 1,228,092,544 元。 [历史金额读取验证](stk-mins-amount-precision-low-level-design-v1.md#32-prod-读者)

## 2. 存储与写入

### 2.1 加列和统一读值

在现有父表内新增 `amount_precise NUMERIC`，允许为空且省略默认值。现有月分区随父表增加该字段，后续月分区继承同一列定义。现有 `amount REAL` 承载只在旧口径下入库的历史金额。新增字段采用精确十进制，直接保存源数值，省去预设两位小数造成的二次截位。采用加列是因为 PostgreSQL 可省去重写已有数据和索引。直接扩大 `REAL` 列会重写分区，也无法恢复已舍入的金额。 [PostgreSQL ALTER TABLE](https://www.postgresql.org/docs/16/sql-altertable.html#SQL-ALTERTABLE-NOTES) · [PostgreSQL 数值类型](https://www.postgresql.org/docs/16/datatype-numeric.html)

业务继续看到一个 `amount`。库内读值统一使用下式。历史 `REAL` 先无损扩大为 `DOUBLE PRECISION`，再转十进制，避免直接 `REAL::NUMERIC` 追加一次单精度转换的十进制取整。用生产 PostgreSQL 只读常量验证，历史样本的单精度值 1,228,092,544 元直接转 `NUMERIC` 会变为 1,228,090,000 元，先转双精度再转十进制则保留 1,228,092,544 元。验收再用旧值核对原读取结果与业务舍入。

```sql
COALESCE(amount_precise, amount::double precision::numeric) AS amount
```

| 记录来源 | 原 `amount` 列 | 新 `amount_precise` 列 | 统一读值 |
| --- | --- | --- | --- |
| 旧口径已入库，切换后未重取 | 原值 | `NULL` | 原列金额 |
| 切换后新写入或按现有入口重取 | `NULL` | 精确源值 | 新列金额，0 元照常返回 |
| 切换后源金额为 `NULL` | `NULL` | `NULL` | `NULL` |

以写入版本区分口径，交易日期只用于取数。如果切换后通过现有动作重取一条历史记录，同样用新列写入。同一主键的重新写入同时清空旧金额栏，避免新响应的合法空值读回上次的金额。

### 2.2 写入入口及字段传递

| 环节 | 当前行为 | 切换时处理 |
| --- | --- | --- |
| **Prod 维护任务入口** | 手动、自动和重试通过同一个 `stk_mins.maintain`，由股票分钟专用 worker 执行。日常和获准的定向补数共用写入路径。源站可用性探测只请求 `ts_code` 和 `trade_time`。 | 全部维护入口随同一个写入实现切换。源站探测继续检查日期与记录是否存在。现有请求参数、频率、分页、计划 unit 和提交边界照旧。 [专用 worker](../../src/app/runtime/ops_worker_factory.py#L91) · [源站探测字段](../../src/ops/services/stk_mins_remote_probe_service.py#L21) · [数据集维护说明](stk-mins-dataset-development.md) |
| **HTTP 解码与连接器** | `TushareSourceConnector` 调 `TushareHttpClient.call`，`response.json()` 会先把普通小数解成 Python `float`。 | `stk_mins` 的 `amount` 在 JSON 解码时保留十进制原值，以 `Decimal` 进入归一化。整元和合法空值沿用其语义。其他源字段维持当前类型，源请求和响应字段仍叫 `amount`。 [连接器](../../src/foundation/connectors/tushare_connector.py#L16) · [HTTP 回包解码](../../src/foundation/clients/tushare_client.py#L196) |
| **归一化、ORM 与 upsert** | `DatasetNormalizer` 调用 `_stk_mins_row_transform`，当前将 `amount` 转成 `float`，`raw_only_upsert` 经 `GenericDAO` 写入表列。 | 行转换将精确值写入新增的 `Numeric` 列，旧列赋 `NULL`。核对 DAO 按 ORM 列过滤后的实际写入值，以及主键冲突更新时两列的结果。从同一源重试时按 `(ts_code, freq, trade_time)` 覆盖同一条记录。 [归一化入口](../../src/foundation/ingestion/normalizer.py#L132) · [股票分钟行转换](../../src/foundation/ingestion/row_transforms.py#L972) · [原表模型](../../src/foundation/models/raw/raw_stk_mins.py#L11) · [写入入口](../../src/foundation/ingestion/writer.py#L2167) · [DAO](../../src/foundation/dao/base_dao.py#L26) |
| **DG 直接从 Tushare 取数或补数** | DG 直拉和合并修复写 DG Raw Parquet，独立于 Prod 写入。 | 沿用 DG 自己的取数和 `amount DOUBLE` 写盘。只有读取 Prod 原表的 DG 入口使用本方案新增的列。 [DG 直拉](../../lake_console/orchestrator/src/orchestrator/defs/assets/stk_mins.py#L592) · [DG 合并修复](../../lake_console/orchestrator/src/orchestrator/defs/assets/stk_mins.py#L771) |

同一次精确写入从 HTTP 数字到数据库绑定参数持续保留十进制值。验收从固定的 JSON 原文开始跑现有入库入口，覆盖带小数的大额、0 元、空值、重复提交和已存在的旧主键。这样可以同时检查首次写入、按键覆盖和 DAO 实际收到的数据。

## 3. 下游读数和对应改动

**只在 Prod 原表新增物理列。** 查询结果统一仍叫 `amount`。现有视图、DG 文件、快照表、API 和前端都使用各自的现有字段。会直接看到新物理列的只有下面负责选值的 SQL 和 ORM。

| 已核对的读取入口 | 切换安排 | 验收 |
| --- | --- | --- |
| **Prod 公共视图** `core_serving.equity_minute_bar`。目前逐列投影股票分钟原表。 [视图定义](../../alembic/versions/20260427_000081_widen_stk_mins_vol_to_bigint.py#L46) | 改为按 §2.1 取值，SQL 列 `amount` 从 `REAL` 改为 `NUMERIC`。PostgreSQL 需要重建这个视图才能改变已有输出列类型。在迁移事务内处理，恢复原有 owner、权限和注释。 | 用现有读取角色核对字段顺序、时间和频率筛选、原有读权限及金额。核对 SQL 客户端收到的 `Decimal` 在业务边界按既有合同交付。 |
| **Prod 直接构建成交额快照的运维命令** `wealth-build-turnover-snapshot`。两处直接对 `RawStkMins.amount` 聚合，分别生成市场总额和按时间的序列。 [命令入口](../../src/cli.py#L263) · [市场总额](../../src/biz/services/wealth/market/turnover/turnover_snapshot_materialize_service.py#L68) · [按时间聚合](../../src/biz/services/wealth/market/turnover/turnover_snapshot_materialize_service.py#L112) | 两处都先按 §2.1 取值，再用十进制求和，最后按原合同转成千元。既有快照保留。将来重算旧日期时，单根旧金额维持原值，汇总可能因求和从单精度改为十进制而有细微差异。 | 对含新值、旧值、0 元和空值的同一批数据分别核对总额和时间序列，检查快照存储与 API 的单位及格式。 |
| **DG 从 Prod 日常同步及按日修复。** 均复用 `build_prod_stk_mins_duckdb_source_sql`，真正读金额的 SQL 在 PostgreSQL 端执行。 [日常读取](../../lake_console/orchestrator/src/orchestrator/defs/assets/stk_mins.py#L644) · [按日修复](../../lake_console/orchestrator/src/orchestrator/defs/bootstrap/stk_mins_raw_replace_from_prod.py#L326) · [共用 SQL](../../lake_console/orchestrator/src/orchestrator/defs/prod_db/stk_mins.py#L61) | 在远端先按 §2.1 取值，再显式转成 `DOUBLE PRECISION AS amount` 交给 DuckDB，保留原字段投影和频率、时间、代码过滤。Prod 完成状态、覆盖率探测和修复计划的键、行数探测不取金额，继续用原规则。 | 用 DG 实际只读角色和 `postgres_query` 验证新旧样本，核对投影、结果类型和筛选。日常与按日修复须读到同一金额。首个新日期需确认实际经过远端读取，避免重用旧 Parquet 充当新列验收。 |
| **DG 股票行情和本地股票分钟图。** DG Raw 用金额和成交量生成 VWAP，Silver 按现有规则清洗。Gold 生成前复权 K 线及合成周期，本地股票分钟接口读现有 Gold 文件。 [DG Raw 金额与 VWAP](../../lake_console/orchestrator/src/orchestrator/defs/assets/stk_mins.py#L1108) · [Silver 处理](../../lake_console/orchestrator/src/orchestrator/defs/assets/stk_mins.py#L1716) · [前复权与合成取数](../../lake_console/orchestrator/src/orchestrator/defs/stk_mins_qfq.py#L368) · [分钟图行情读取](../../src/foundation/clients/local_lake/stock_mins_reader.py#L109) | Raw、Silver、Gold 继续使用现有 `amount DOUBLE`。VWAP 取同一条选中的金额。Silver 的无成交处理和 Gold 的竞价归入、周期合成继续遵循各自规则。前复权只调价格，分钟 MACD、KDJ 和九转沿用原价格输入与计算规则。 | 对正常有成交样本核对 Raw、Silver 和页面的金额，验证现有合成只按既有窗口加总。现有历史文件按原值提供服务。 |
| **DG 计算全市场成交额并发布回 Prod 快照。** 日常 Job 从股票分钟 Silver 和股票日线计算 Gold 市场快照，再把同一分区发布到 `core_serving.wealth_market_turnover_snapshot`。市场成交额和成交额洞察接口读快照表。 [聚合 SQL](../../lake_console/orchestrator/src/orchestrator/defs/wealth_market_turnover_contract.py#L124) · [日常 Job](../../lake_console/orchestrator/src/orchestrator/defs/jobs/gold_wealth_market_turnover_update.py#L9) · [快照发布](../../lake_console/orchestrator/src/orchestrator/defs/assets/wealth_market_turnover_prod_core.py#L41) · [成交额查询](../../src/biz/queries/wealth/market/turnover/turnover_query.py) · [成交额洞察查询](../../src/biz/queries/wealth/market/turnover_insight/turnover_insight_query.py) | 精度改进经 Silver 的既有 `amount` 传到 Gold，再到 Prod 快照表。聚合规则、已有北交所日线差额处理、千元单位、快照表列和 API 保持现行合同。该日常发布链条与 Prod 快照运维命令分别核对。 | 在首个实际同步的新日期查看日常任务状态，按指定日期、频率读取已产出的 Gold 和 Prod 快照及对应接口结果，核对总额、序列和单位。Silver 金额单独按样本股票核对。 |
| **算子库配置、指标与只读取价的消费者。** 算子库配置登记了 Prod 股票分钟视图，但默认未启用该能力。交易助手当前只读交易时间、收盘价和成交量。 [算子库位置配置](../../packages/technical_indicators/src/goldenshare_technical_indicators/configuration/datasets.py#L89) · [启用判定](../../packages/technical_indicators/src/goldenshare_technical_indicators/request_parser.py#L46) · [交易助手投影](../../src/foundation/clients/local_lake/stock_rule_minute_reader.py#L61) | 视图仍是已登记的数据位置，保持股票分钟算子现有启用状态。交易助手继续读现有价格与成交量投影。 | 复核字段、单位及调用路径，确认业务仍使用各自数据源。 |

2026-11-25 补查了 Prod 系统目录。股票分钟原表金额的登记依赖只有 `core_serving.equity_minute_bar`，未查到依赖该视图的其他视图或物化视图。原表、叶分区与视图均无触发器。常用业务 schema 的存储例程中也未找到直接引用这两个关系的定义。`lake_raw_reader` 当前具备原表的表级 `SELECT` 权限。系统目录核验覆盖数据库登记的依赖，代码审计覆盖本仓库的入库和读取实现。上线按实测读取角色验证新列和重建视图的权限。

本方案对 **Prod** 承诺十进制原值，对 **DG** 保留当前 `DOUBLE` 文件合同并消除从 Prod `REAL` 带入的舍入。以 7,473,614,620.35 元为例，跨库、落 Parquet、读取时逐根核对到分。若源样本含更多有效小数位，在隔离核验中按其有效位对账。DG `DOUBLE` 属于浮点，整条 DG 链逐位精确保留任意十进制小数是独立的文件合同变更。 [DG Raw 和 Silver 列类型](../../lake_console/orchestrator/src/orchestrator/defs/run_contracts/asset_column_schemas.py#L190)

## 4. 实施顺序和验收

1. **LLD 与隔离验证。** 查实际迁移 head、视图权限和读写入口。使用真实的旧主键和模拟源 JSON 在隔离 PostgreSQL 跑现有入库路径，核对每层金额、原列置空、任务重试与冲突更新。用隔离数据库核对迁移前后分区及主键索引的物理标识，核算 DDL 锁耗时与读写耗时。隔离跑通两条快照生成路径和 DG 的 `postgres_query`，复用现有测试入口补关键回归。
2. **生产加列，读者先就位。** 获准后选择股票分钟写入空档。加列并切换视图，部署 Prod 快照命令和 DG 日常同步、按日修复的新版读者。用已入库的历史行通过所有需改的读者核验金额、权限、类型和接口。旧写入仍在时只会产生旧列金额，这段时间的业务读值由 §2.1 的历史规则覆盖。
3. **切换唯一写入版本。** 使用现有运维入口暂停股票分钟自动触发和新提交，等在途股票分钟任务结束，再更换专用 worker。重新开放前核对手动、自动和重试都由新版 worker 执行。避免旧 worker 在新版之后写入，将新键写回单精度口径，或更新同一旧键时留下与新列不一致的值。读者确认到位后恢复任务。
4. **验收首批写入及下游产出。** 这是切换后的一次性验收。选定一股、一日、一频，临时从 Tushare 查同范围的时间键和成交额，只与 Prod 该范围已写入的新列、视图及实际产出的 DG 行情对照。首个完整交易日的五档同步通过已有任务状态核验。市场快照只读该日该频率已产出的 DG、Prod 快照和对应接口结果。日常同步继续按现有流程，验收无需保存原始回包或新增重复取数和校验。

如果在首笔精确写入前退出维护窗口，可保留空的新列并恢复原写入。已经写入精确值后，恢复服务需保留精确列和能读取它的版本，暂停相关生产者后修复或重新部署。停回旧写入会重新引入单精度，切回只读旧列会让新的金额读成空值。

具体的迁移 SQL、代码改动点、分阶段开发及生产验收见 [LLD](stk-mins-amount-precision-low-level-design-v1.md)。实施后更新 [现行股票分钟维护说明](stk-mins-dataset-development.md) 的模型与验收证据。
