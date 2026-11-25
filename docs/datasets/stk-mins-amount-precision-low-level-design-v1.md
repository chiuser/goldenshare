# Prod 股票分钟行情成交额精度改造 LLD v1

- 日期：2026-11-25
- 状态：阶段 1 开发与隔离验收完成，阶段 2 生产切换完成，待阶段 3 首批正式数据验收。
- 依据：[改造方案](stk-mins-amount-precision-plan-v1.md) · [现行数据集维护说明](stk-mins-dataset-development.md) · [数据集开发说明模板](../templates/dataset-development-template.md)
- 数据源：[Tushare 股票历史分钟行情，doc_id 370](../sources/tushare/股票数据/行情数据/0370_股票历史分钟行情.md)

## 1. 实施范围和验收口径

只在 Prod `raw_tushare.stk_mins` 新增一个物理列 `amount_precise`。金额单位为元。每条由新版写入的记录，其成交额从收到 Tushare JSON 到 PostgreSQL 落库全过程保留十进制值。下游仍读业务字段 `amount`。历史行使用已保存的金额，切换本身省去历史重新取数、计算和重写。若运营此后通过既有入口定向重取一条记录，该条记录随正常 upsert 使用新精度。

本专项审计、迁移预检及验收禁止全局、全量读取和扫描业务数据，包括全表或全历史统计、导出和逐分区扫全市场。生产侧只使用系统目录、既有任务状态和按业务键限制的只读查询。验收不得为比较结果触发全市场重算。

`stk_mins` 仍使用 Tushare 的 `ts_code` 和 `freq` 及现有请求窗口。现有点、区间维护能力，日历和时区规则，1、5、15、30、60 分钟频率，股票池、质量判定和主键均适用。业务日期按现有开市日解释，计划 unit 仍按股票、频率和时间窗口生成，时效观测字段仍为 `trade_time`。金额升级也不改变其他源字段、指数及 ETF 写入、算子启用状态或本地股票分钟图改造计划。 [DatasetDefinition](../../src/foundation/datasets/definitions/market_equity.py#L2208) · [上游请求参数](../../src/foundation/ingestion/request_builders.py#L175)

2026-11-25 复核到仓库 Alembic 单一 head 与 Prod 当前 revision 均为 `20261116_000190`，Prod PostgreSQL 为 16.13。当前成交额视图列位于第 10 位，类型 `REAL`，唯一直接登记依赖为这个普通视图，下游无登记视图依赖。原表和视图 owner 均为 `goldenshare_user`。原表另有 `lake_raw_reader` 表级 `SELECT`，视图 ACL 只有 owner，无列级授权、注释和视图选项。事实为当日只读核验，上线前刷新。 [上一版迁移中的视图](../../alembic/versions/20260427_000081_widen_stk_mins_vol_to_bigint.py#L46) · [当时 head](../../alembic/versions/20261116_000190_stock_period_adj_serving_unique_period.py)

## 2. Prod 数据库存储与迁移

### 2.1 物理字段

| 字段 | PostgreSQL 类型 | 可空 | 数据来源 |
| --- | --- | --- | --- |
| `amount` | `REAL` | 是 | 现有历史值。新版写入的记录填 `NULL`。 |
| `amount_precise` | 未指定精度和小数位数的 `NUMERIC` | 是 | 新版从 Tushare 解码的精确成交额。旧版本写入的行和源金额为空的行保持 `NULL`。 |

SQLAlchemy 模型 `RawStkMins` 增加一个成员。原 `amount` 的 ORM 声明照旧，视图和查询的取值采用 §3。

```python
# raw_stk_mins.py，新增分区原表列的 ORM 映射
amount_precise: Mapped[Decimal | None] = mapped_column(Numeric(), nullable=True)
```

### 2.2 Alembic 迁移

新增一个 revision，`down_revision` 取开发时实查的唯一 head。生产前确认应用目标与预期版本一致。迁移在同一事务完成下列 SQL，具体由 `op.add_column` 和 `op.execute` 表达。SQL 示例列出了全部视图输出。

```sql
ALTER TABLE raw_tushare.stk_mins
    ADD COLUMN amount_precise numeric;

DROP VIEW core_serving.equity_minute_bar RESTRICT;

CREATE VIEW core_serving.equity_minute_bar AS
SELECT ts_code, freq, trade_time, trade_time::date AS trade_date,
       open, close, high, low, vol,
       COALESCE(amount_precise, amount::double precision::numeric) AS amount,
       'tushare'::varchar(32) AS source
FROM raw_tushare.stk_mins;
```

1. 变更前记录视图 owner、ACL、授权选项、列及对象注释和视图选项，原表 owner 和授权，以及依赖对象。切换同事务内按这些事实恢复与核对视图元数据。以原 owner 执行，现有授权快照只有 owner，无须引入新的角色或授权。如果实施窗口发现真实依赖不同，先按现行对象校准迁移清单。
2. 父表加列覆盖已有月分区、默认分区，新建分区继续继承父表。列可空、无默认值、无索引。无需更新已有记录，也不改变原表、主键或分区定义。记录两处有数据的月分区与索引迁移前后的 OID 和 `pg_relation_filenode`，并核对全体叶分区的新列定义。
3. PostgreSQL 视图更换类型须重建视图，所有操作保留在一次事务里。依赖拦截、权限或锁失败时让 Alembic 回滚事务，视图与原表继续使用原合同。用实际读者连接确认视图重建后的查询。遇到保留旧结果类型的连接，按现有应用方式重建连接后复查。
4. 稳定版本迁移内保留自己的视图 SQL。故障处理按 §6.3，避免以删除精确列作为返回旧应用的手段。

[现有数据库事务装配](../../alembic/env.py#L34) · [PostgreSQL ALTER TABLE 规则](https://www.postgresql.org/docs/16/sql-altertable.html#SQL-ALTERTABLE-NOTES) · [PostgreSQL 视图定义](https://www.postgresql.org/docs/16/sql-createview.html)

## 3. 写入与读取实现

### 3.1 从 Tushare 回包到数据库

沿用 `DatasetSourceClient` → `TushareSourceConnector.call` → `TushareHttpClient.call` → `DatasetNormalizer` → `DatasetWriter._write_raw_only_upsert` → `GenericDAO.bulk_upsert`。手动、自动和重试使用同一个股票分钟专用 worker。

1. 在 `TushareHttpClient.call` 确认 API 为 `stk_mins` 时，以 `response.json(parse_float=Decimal)` 解码原响应，沿用 `TushareEnvelope` 校验。按回包中的 `fields` 对齐 `items` 来识别金额列，无需依赖字段固定下标。构造成功行时，仅保留 `amount` 的十进制值，其他由 JSON 数字解析得到的 `Decimal` 保持原浮点行为；整数、文本、空值沿用原行为。其他接口继续走原解码；Tushare 非零错误码、限频和请求异常按现有分支处理，错误详情沿用原响应字段和可序列化类型。股票分钟的非零响应在构造既有业务异常时用默认解码取错误详情，成功路径只解码一次。
2. 在 `_stk_mins_row_transform` 用现有 `to_decimal` 读源 `amount`，赋给 `amount_precise`，原 `amount` 固定赋 `None`。正常输入为 JSON 解析保留下来的 `Decimal`、整数、兼容的数值文本或空值。保留 0，原先当作空值的输入仍为空。非法金额沿用 `normalize.row_transform_failed` 的行拒绝路径。四价舍入、成交量整数和时间检查沿用现有规则。
3. 归一化后的两列同时交给现有通用 DAO。DAO 会以模型列过滤输入，并用 `excluded` 更新已有主键上的可写列。验证新增列不会被过滤，新写入和冲突更新均把原列置空。曾有历史金额的主键收到合法空值时，两列均为 `NULL`，读取结果也是 `NULL`。
4. 源站探测只请求 `ts_code`、`trade_time`，不会写表，继续沿用原判定。DG 直接向 Tushare 拉取及按股票合并文件的入口维持自己的 Raw Parquet 合同。

[HTTP 客户端](../../src/foundation/clients/tushare_client.py#L196) · [响应模型](../../src/foundation/schemas.py#L10) · [行转换](../../src/foundation/ingestion/row_transforms.py#L972) · [现有十进制转换](../../src/utils.py#L41) · [写入路径](../../src/foundation/ingestion/writer.py#L2167) · [DAO](../../src/foundation/dao/base_dao.py#L26) · [Prod 源探测](../../src/ops/services/stk_mins_remote_probe_service.py#L21) · [DG 直拉和复用](../../lake_console/orchestrator/src/orchestrator/defs/assets/stk_mins.py#L592)

### 3.2 Prod 读者

视图、原表消费 SQL 和 DG 使用同一个选择语义。以 `NULL` 决定取值，新列为 0 元时正常返回 0。历史 `REAL` 必须先扩大成双精度再转换为十进制。生产 PostgreSQL 常量验证，`1228092544::real::numeric` 得到 1,228,090,000，而经过双精度得到 1,228,092,544。此过程保留库里已有的精度，源响应中之前丢失的数值仍无法找回。

| 读者 | 改动点与类型 |
| --- | --- |
| `core_serving.equity_minute_bar` | 使用 §2.2 SQL。SQL 客户端会读到 `NUMERIC`，视图仍含原有 11 个字段，字段顺序与单位沿用现行定义。SQL 中的金额成为计算列，维护任务通过原表写入。历史 `REAL` 转成十进制后，文本形式可能多出比原 `REAL` 显示更长的小数尾数，业务继续按原格式显示。 |
| `TurnoverSnapshotMaterializeService._materialize_one` | 在本方法内定义一次 `func.coalesce(RawStkMins.amount_precise, cast(cast(RawStkMins.amount, Double()), Numeric()))`，替换市场总额和逐时间序列两处 `func.sum(RawStkMins.amount)`。先以十进制汇总元，再经原 `_to_thousand_yuan` 输出，复用快照字段与 API 格式。重算历史日时求和的精度可提高，已生成的历史快照不参与回写。 |
| 已有视图配置与业务入口 | 算子库配置中股票原生分钟指向该视图，默认仍无已启用的股票分钟获取能力。现行本地股票分钟页使用 DG 的 K 线成品，交易助手读交易时间、收盘及成交量，业务不增加金额字段。 |

[市场总额和分时汇总](../../src/biz/services/wealth/market/turnover/turnover_snapshot_materialize_service.py#L51) · [算子库配置](../../packages/technical_indicators/src/goldenshare_technical_indicators/configuration/datasets.py#L89) · [请求启用判定](../../packages/technical_indicators/src/goldenshare_technical_indicators/request_parser.py#L46) · [交易助手读取](../../src/foundation/clients/local_lake/stock_rule_minute_reader.py#L61)

### 3.3 DG 从 Prod 的读取

只修改共用 PostgreSQL 投影 `PROD_STK_MINS_SELECT_TEMPLATE` 的最后一列。股票分钟日常同步和从 Prod 的单日修复均通过这个 SQL 读取。实际联调用既有只读连接、`postgres_query` 和现行输出 SQL 验证。

```sql
SELECT ts_code, freq, trade_time, open, close, high, low, vol,
       COALESCE(amount_precise, amount::double precision::numeric)
           ::double precision AS amount
FROM raw_tushare.stk_mins
WHERE freq = {freq}
  AND trade_time >= TIMESTAMP {start_datetime}
  AND trade_time < TIMESTAMP {end_datetime}
  AND ts_code = ANY(ARRAY[{stock_codes}]::text[])
ORDER BY ts_code, trade_time
```

- 由 PostgreSQL 统一选值并转双精度。DuckDB 仍按原九个源字段读取，DG Raw 导出的 `amount` 与 VWAP 都使用同一个有效金额。用实际 `lake_raw_reader` 检查新列权限。覆盖率探测和修复计划的键、行数探测保留现有查询。
- DG Raw、Silver、Gold 和股票分钟 API 保留现有字段和类型。按当前 `DOUBLE` 的能力验收到分等有意义的小数位，精确十进制保证落在 Prod。用正常有成交样本检验精度，另外按原规则核对 Silver 无成交处理，以及 Gold 开盘竞价与 90／120 分钟的金额加总。MACD、KDJ 和九转继续用原有价格输入。
- DG 市场成交额以 Silver 分钟及股票日线为输入，仍按既有口径求和、处理北交所日线差额、以千元生成快照，沿原日常发布将 Gold 写回 Prod 快照。验收分别核对这条日常链和 Prod 直接读原表的快照运维命令。页面、洞察接口继续从各自快照读数。

[共用 PostgreSQL SQL](../../lake_console/orchestrator/src/orchestrator/defs/prod_db/stk_mins.py#L61) · [日常读取](../../lake_console/orchestrator/src/orchestrator/defs/assets/stk_mins.py#L644) · [单日修复](../../lake_console/orchestrator/src/orchestrator/defs/bootstrap/stk_mins_raw_replace_from_prod.py#L326) · [Raw 投影和 VWAP](../../lake_console/orchestrator/src/orchestrator/defs/assets/stk_mins.py#L1108) · [Silver 处理](../../lake_console/orchestrator/src/orchestrator/defs/assets/stk_mins.py#L1716) · [市场成交额聚合](../../lake_console/orchestrator/src/orchestrator/defs/wealth_market_turnover_contract.py#L124) · [从 DG 发布 Prod 快照](../../lake_console/orchestrator/src/orchestrator/defs/assets/wealth_market_turnover_prod_core.py#L41)

## 4. 执行规模、事务和恢复

| 项目 | 预算和依据 |
| --- | --- |
| 迁移 | 一次 PostgreSQL 迁移事务，加一列及重建一个现有视图。已核 Prod 325 个叶分区，11 个已分配数据页。隔离实验创建同数量叶分区，并在有数据的代表月验证 heap 和主键索引文件标识保持。预算是历史数据行重写 0，源请求 0，历史回刷 0。用实际锁占用及执行时间为生产维护窗口设置 `lock_timeout` 与 `statement_timeout`，同时计入超时回滚和复查开销。 |
| Prod 现有同步 | 每个 unit 仍为一股、一频和一窗口，最多 8,000 条源端记录一页，现有取数并发为 2。新增源请求与提交次数均为 0。原路径累积同一 unit 的结果后归一化再按批次 upsert，一次 unit 提交。单行绑定列由 9 增为 10，DAO 仍取有效配置和参数上限的较小值。默认配置下每批均为 1,000 行。若命中参数上限，单批上限由 (65,535 − 32) ÷ 9 向下取整的 7,278 行降到按 10 列计算的 6,550 行，SQL 批数以实际有效批次和待写行数计算。十进制解码的 CPU、内存开销用现有单日和正常多页请求夹具，按原路径和新路径同条件记录峰值与时长。 |
| DG 同步与验收 | 日常与按日修复各沿用现有按目标日、频率及股票集合过滤的批量查询。新增查询、Parquet 列和历史文件重生成均为 0。隔离测同一批过滤的新旧 SQL、历史和新值混合时的查询计划以及导出耗时。生产新增人工对账只查一股、一频、一日。五频覆盖从现有日常任务状态判断。快照只查同日期、同频率的已发布结果。 |
| 磁盘与读者 | 新列仅随未来写入占空间，`NUMERIC` 随数值长度占用，旧行无需重新保存。用实际验收批计算新增字段占用和汇总耗时。已核 53.3 GiB 关系大小是历史原表和索引基线，不拿它推算本次临时写盘成本。 |

这次改造沿用现有任务、写入 unit、主键和阶段状态。任务取消、单元失败、已提交单元的保留以及运营重试仍按现有任务规则执行。持久事实是按主键写入的业务行与既有 TaskRun 记录。对旧任务的重试需经新版 worker，同一个 unit 重放结果幂等。状态、进度与写入沿用既有执行器的边界。本期没有新建历史同步或改造通用任务恢复机制。 [现行专用 worker 运维说明](../ops/ops-stk-mins-dedicated-worker-execution-lane-plan-v1.md) · [数据集事务和分页配置](../../src/foundation/datasets/definitions/market_equity.py#L2264)

## 5. 开发和隔离验收清单

| 验证项 | 现有入口与通过标准 |
| --- | --- |
| 源合同与解码 | [HTTP 测试](../../tests/test_tushare_client.py)、[取数测试](../../tests/test_dataset_source_client.py)。以真实形状的原始 JSON 响应构造样本，金额包含已有实测的 7,473,614,620.35 元与 1,228,092,577 元。断言小数在 HTTP 输出中是 `Decimal`，数值精确，再核其他价格类型、空值、0 元以及另一个接口解码行为。 |
| 模型、写入与幂等 | [归一化测试](../../tests/test_dataset_normalizer.py)、[模型测试](../../tests/test_extended_models.py)。用真实 PostgreSQL 隔离验证行转换、通用 DAO 与视图。分别覆盖只存在旧值、新主键、覆盖旧主键以及一次精确写入后再返回空金额。对拍新旧列、统一读取结果和重复执行后的行数。 |
| 迁移 | 隔离建分区父表、月分区、默认分区、主键和现行视图，写入经 `REAL` 表示的历史基准。迁移后表和索引物理标识一致，视图字段顺序、owner、ACL 和权限规则一致。使用 1,228,092,544 元核实读历史不会再次舍入。迁移失败能在原事务中恢复旧视图和原列定义。 |
| 直接快照 | [成交额快照测试](../../tests/test_turnover_snapshot_materialize_service.py)。两处汇总都用同一固定输入，含新值、旧值及 0。独立加总核对千元总额与分时序列。现有数据库替身覆盖表示合同，真实 PostgreSQL 核对 `REAL` 历史值转换和 `NUMERIC` 求和。 |
| DG 和末端 | [DG 股票分钟精度测试](../../lake_console/orchestrator/tests/test_stk_mins_prod_price_precision.py)、[单日修复测试](../../lake_console/orchestrator/tests/test_stk_mins_raw_replace_from_prod.py)、[市场成交额发布测试](../../lake_console/orchestrator/tests/test_gold_wealth_market_turnover_prod_core_sync.py)、[成交额 API 测试](../../tests/web/test_wealth_market_turnover_api.py)。用实际 `postgres_query` 验证新旧金额读取、双精度、原有分区过滤和 VWAP。验证现有行情输出和间接产出的市场快照沿用字段及单位。 |

编写 LLD 时，已用现有响应模型验证 `response.json(parse_float=Decimal)` 能把 7,473,614,620.35 元保留到 `TushareEnvelope.data.items`，并核对 0 和空值。拟用的 ORM 表达式也已编译为预期的 PostgreSQL 双层转换。隔离入库与跨库验收结果见 §8。生产读回按 §6.3 执行。

## 6. 三个推进阶段与生产切换

### 6.1 阶段 1 开发与隔离验证

按 §2、§3 实现迁移、HTTP 解码、股票分钟写入、Prod 视图、快照直接读者和 DG 共用投影。用 §4、§5 的用例和实测完成独立验收。编码前补齐[数据集维护说明的实施合同](stk-mins-dataset-development.md)。切换时记录 Prod 和 DG 的实际发布版本，验收时按 §6.3 对账。

### 6.2 阶段 2 Prod 和 DG 切换

获准后按以下次序执行，可用同一份 Prod 发布版本。靠现有专用 worker 的启停控制写入时点。

1. 预检版本、分区、视图、权限和目标锁。使用现有 Ops 入口暂停股票分钟自动触发及其绑定的源站探测，窗口内暂缓手动提交和重试。等待在途股票分钟任务结束，停止 `goldenshare-ops-stk-mins-worker.service`。保留原排程状态供恢复。运行脚本与 worker 均使用已确认的版本。
2. 用既有 Prod 发布入口的 `--maintenance-migration` 模式应用迁移。该模式不会重启服务。先用新视图执行一条有界历史查询，核对历史值、列顺序、属主和授权。
3. 让 Prod 直接构建快照的命令使用新版，发布 DG 日常同步和按日修复读者。用实际连接验证它们都能读取历史行。此时可先完成 DG 的读取验证而无需发起历史生成。核对进程实际加载的版本，避免部署脚本提前启动旧股票分钟 worker。
4. 启动新版股票分钟专用 worker，恢复手动提交、重试和窗口前启用的自动触发配置。其他车道和业务服务以现有发布入口控制。写入启用前，所有需要切的读者都能按新规则查询。

[既有迁移发布入口](../../scripts/deploy-systemd.sh#L191) · [股票分钟 worker](../../scripts/goldenshare-ops-stk-mins-worker.service) · [运维入口与取消规则](../ops/ops-stk-mins-dedicated-worker-execution-lane-plan-v1.md)

### 6.3 阶段 3 首批真实验收和故障恢复

1. 精确写入在隔离测试中使用同一份源 JSON 对账。生产只做一次定向验收，选新版已完成入库的一股、一日、一频，向 Tushare 只读核对同一已收盘窗口的时间键和成交额。用 `ts_code`、`freq` 和 `trade_time` 的有界范围查询 Prod 原表和视图，核对新列值、旧列为空和实际结果。另用一个明确的旧主键验证旧值。源样本只在当次对账中使用，日常同步沿用现有流程，无需新增源响应留存、日志字段或逐次校验。
2. 查看首个由新版完整写入的交易日已有任务状态，确认五个基础周期成功同步，且 DG 样本来源为 Prod 导出。读取 DG 时直接定位样本的日、频率文件并按股票及时间过滤，Gold 和分钟接口同样限定样本股票、日期、频率。市场链仅定位该日该频率已经产出的 DG Gold 和 Prod 快照，核对读回及对应接口结果。记录应用版本、交易日、样本键和有限范围内的对账结果。
3. 迁移事务失败时沿事务回滚，旧视图与旧表继续工作。若迁移已提交、尚未写入精确值，可保留新列、已放行读者及旧写入能力，再安排恢复。只要已有一笔精确值落库，就保持视图和所有读者可见新列。遇到故障先暂停相关写入并修复或重发支持新列的版本，防止旧 worker 对新键写回单精度，或对旧键重写其他字段却留下上次的精确金额。
4. 本轮达标以首批数据和业务读回证据为准，历史金额维持存量规则。若有异常，沿同一组样本键检查源响应、Prod 存储、远程导出和 DG 文件。新增核对只允许针对有证据的业务键。

## 7. 设计对账

| 已确认口径 | 本文落实位置 |
| --- | --- |
| 现有历史按原金额服务，未来精确入库 | §2、§3.1、§5 |
| 下游沿用 `amount`，只在 Prod 原表加列 | §2.1、§3.2、§3.3 |
| 覆盖两条快照路径、DG 日常和按日修复 | §3.2、§3.3、§5 |
| 读者先到位、单一新版写入、验收五频 | §6.2、§6.3 |
| 分区、窗口、提交、任务优先复用现有合同 | §1、§3.1、§4 |

## 8. 阶段 1 独立验收记录

2026-11-25，逐项对照方案、LLD、代码差异和实际调用方。用 CodeGraph `codegraph_explore` 追踪源接口、股票分钟写入、成交额快照及 DG 共用读取，随后以当前 SQL、模型和测试核对。验证只使用临时 PostgreSQL 18.4、DG DuckDB 1.5.2 和有界夹具。正式 Prod PostgreSQL 16.13 数据、正式 DG 文件和任务未改动。

| 验收项 | 实际结果 |
| --- | --- |
| 迁移和权限 | 本地 Alembic 唯一 head 为 `20261125_000191`，接 `20261116_000190`。325 个叶分区都继承无默认值的可空 `NUMERIC`。两个有测试数据的月份及主键索引共四个对象的 OID 和文件标识一致。视图仍为 11 列，仅 `amount` 改为 `NUMERIC`，原属主和有效授权一致。用 `lake_raw_reader` 实际读取新列。加入现有依赖的反例中，`DROP VIEW RESTRICT` 阻止迁移，回滚后原表列和原视图均在。 |
| 源响应到 Prod 落库 | 用已有 Tushare 样本的原始数字及响应结构走正常 HTTP、取数、归一化和 DAO。7,473,614,620.35 元精确保存在新列，旧列为空。按原主键重放仍为一行。旧主键分别覆盖为 0 元、1,228,092,577 元和空值，读回符合源值，最后两列均为空。另一个历史主键仍读到 1,228,092,544 元。 |
| DG 日常和单日修复 | 两条路径共用同一 PostgreSQL 投影。用实际 `postgres_query` 按股票、日期、频率读取新值、旧值和空值，使用现有 Raw 输出 SQL 导出临时 Parquet。金额列仍为 `DOUBLE`，两个非空样本的金额与数据库读回值一致，VWAP 分别等于 `amount / vol`。空值的 VWAP 沿用 0。旧样本用迁移前投影再读一次，导出的历史金额和空值一致。 |
| 两条成交额快照链 | Prod 直接读数以新旧两行合计，总额为 8,701,707.16 千元，逐时点也核对通过。DG 使用含 30 分钟跨库输出的单日 Silver 形状夹具生成五频 Gold 快照，经现有发布代码写入临时 PostgreSQL 并读回。30 分钟总额为 7,473,627.62 千元，10:00 时点为 7,473,614.62 千元，保留 DG 快照现有的千元两位小数口径。 |
| 回归检查 | 根仓库 166 项通过，含 4 项成交额 API 测试。DG 109 项和 28 项子测试通过，含股票分钟精度、日常及修复合同、Gold 快照及发布。DG 语法和名称检查通过。针对改动的两个 DG 文件，常规 Ruff 的 5 项报告在修改前即存在。 |

隔离 DDL 整个事务最后一次耗时 76.3 毫秒，且代表有数据分区的文件未重写。按业务键读取旧值的查询前后均只访问同一个月分区，PostgreSQL 执行时间为 0.006 和 0.017 毫秒。DG 旧样本从查询到临时文件分别用时 1.5 和 1.9 毫秒。精确金额样本在 `NUMERIC` 列内占 11 字节。上述记录是小样本实测，生产锁等待和正式环境耗时留待切换时核验。

取数性能对比复用相同的模拟源 JSON、副本页和股票分钟取数入口，排除网络及限频等待。241 行单页的中位耗时由 0.22 增至 0.40 毫秒。一个满页加一个短页共 8,241 行，中位耗时由 7.20 增至 15.21 毫秒，测试进程峰值 RSS 相对加载夹具后的增量由 7.0 增至 11.9 MiB。旧版与新版分别完成同样的一次及两次源请求。耗时取一次预热后九次测量的中位数，数据为测试输入重复构造的行。

阶段 2 的复核见 §9。阶段 3 对账仅定位一股、一日、一频以及对应已产出的快照。阶段 1 验收未执行全表、全市场或全历史读取，也未触发正式重算。

## 9. 阶段 2 生产切换记录

2026-11-25，北京时间。迁移前确认股票分钟自动任务 #25 已暂停，绑定探测和在途任务均为 0，10:51 确认旧股票分钟 worker 已停止。管理员在 Prod 执行维护迁移。

- **Prod** 已加载提交 `61b42198c28959ce5e9f7396da457905d3c6f5b4`，Alembic 为 `20261125_000191`。325 个叶分区均继承可空、无默认值的 `amount_precise NUMERIC`。视图保持 11 列，`amount` 为 `NUMERIC`，属主和有效授权一致。按主键读回贵州茅台 `600519.SH` 2026-11-17 15:00 的 30 分钟 K 线，原表旧列和视图都返回 1,228,092,544 元，新列为空。另核实 Prod 成交额快照命令实际加载的代码中，市场总额和时点金额都使用新版表达式。
- **DG** 当前代码位置为 `orchestrator`，指向本机项目源码，股票分钟读取代码含 `54c24f52e` 的新版投影。用正式 `lake_raw_reader` 账号，经 DuckDB 1.5.2 的 `postgres_query` 和现有 Raw 输出 SQL，只读核对同一主键。返回一行，成交额 1,228,092,544 元、类型 `DOUBLE`，成交量 841,723 股，VWAP 与金额除以成交量一致。日常导入及按日修复共用该投影。未启动正式导入、回刷或快照重算。
- **恢复** 11:04 启动新版专用 worker，11:12 复核仍为 `active/running`，重启次数为 0。管理员通过运营页面恢复自动任务 #25。11:12 只读确认 #25 为 `active`、触发模式为 `probe`，仅有一条启用的股票分钟源站探测 #27 绑定该任务，来源为 `tushare`，窗口沿用北京时间 18:00–21:30。复核时在途任务为 0。阶段 2 完成，首批新成交额和下游实际产出按 §6.3 验收。
