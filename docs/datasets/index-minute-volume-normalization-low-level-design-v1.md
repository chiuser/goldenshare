# 指数分钟成交量归一化、入库保护与页面展示 LLD v1

更新于 2026-11-26。阶段 1 已验收。阶段 2 的 Prod 上证综指 30 分钟正式试点已通过，首批重刷、DG 文件发布及读数切换待推进。

依据[专项方案](index-minute-volume-normalization-plan-v1.md)。历史范围、换算阈值和交付顺序以该方案为准。源接口为 Tushare `idx_mins`，见本地源文档 [doc_id 419](../sources/tushare/指数专题/0419_股票历史分钟行情.md)。

## 1. 数据经过哪些步骤

| 路径 | 写入单位 | 本期修改 |
| --- | --- | --- |
| Tushare → Prod `raw_tushare.index_mins` → `core_serving.index_minute_bar` | 股 | 写表前按指数、交易日、原生频率确认源单位。服务视图直接返回表值。 |
| Prod → DG 通用指数分钟 Raw → Silver → Gold | 股 | 继承 Prod 的股数。按原有时段规则生成派生行情。 |
| Tushare → DG 主要指数分钟 Raw → Silver → Gold | Raw 为源值，Silver／Gold 为股 | 主要指数 Raw 保留源值。生成基础频率 Silver 时乘数只用一次。 |
| 算子库 → 本地分钟 API → 指数详情分钟图 | 算子和 API 为股，页面为手 | 算子读取归一后的股数。前端分钟 ViewModel 除以 100。 |
| 日、周、月 K 和右栏总量 | API 已是手，页面为手 | 统一展示格式。沿用各周期的存储和接口。 |

各层的成交额沿用既有单位，分钟行情的成交额为元。已有 Prod 分钟能力是算子库的 5 分钟读取。本地指数分钟图沿用现有接口、周期、指数范围、分页和指标。深证成指历史日线量额的修复见[原验收记录](index-volume-normalization-plan-v1.md)。股票行情和股票详情共用图表时保留原有展示行为。既有数据集的接口字段、类型、主键、请求日期和运营配置均沿用现行合同。[Prod 模型](../../src/foundation/models/raw/raw_index_mins.py#L11) · [服务视图](../../alembic/versions/20260506_000098_add_index_mins_dataset.py#L64) · [运行时频率配置](../../src/app/runtime/technical_indicators/composition.py#L44) · [分钟路由装配](../../src/app/api/v1/router.py#L177)

## 2. 阶段 1：写入前确认单位

### 2.1 单位判定

Prod 和 DG 主要指数分钟采用同一规则。以 `ts_code`、`freq`、上海时区下 `trade_time` 所属交易日分组，汇总当天收到的源 `vol`。当天有数据即按齐备计算。上一交易日用同源、同代码、同频率保存的**源成交量合计和单位**。首次启用用已经确认单位的合计作为比较起点。当天无行情时沿用各入口已有处理。

```python
def resolve_index_minute_volume_unit(previous_total, previous_unit, source_total):
    if source_total > previous_total * 50:
        return "share"
    if source_total * 50 < previous_total:
        return "lot"
    return previous_unit
```

按上述结果对本组每根行情处理 `vol`。源单位是 `lot` 时乘 100，是 `share` 时沿用原值。等于 50 倍或 1／50 时沿用上一交易日的源单位。价格、成交额及时间沿用原值。

### 2.2 Prod：字段转换后、写表前

1. `_build_index_mins_units`、`_idx_mins_params` 与 `_index_mins_row_transform` 沿用现有取数、分页和行转换。行转换产出的 `vol` 是源值。
2. 在 `DatasetWriter.write` 的 `index_mins` 写表路径，按现有主键去重，然后按交易日依次汇总源 `vol`。通过现有 A 股交易日历定位前一交易日。区间请求的第一天读一次起点记录，后续日优先使用本批刚算出的前一交易日记录。有记录的交易日按顺序处理，已有确认起点用于开始比较。
3. 将股数写入 `raw_tushare.index_mins`，复用原 DAO 批量 upsert。由 `IngestionExecutor._process_fetched_unit` 沿用现有提交边界，行情和单位记录同事务提交。重跑从本次收到的源值重新计算。服务视图、任务提交和状态沿用现有入口。

新增内部表 `raw_tushare.index_mins_volume_evidence` 保存计算所需的两项值。行情表写入后只有股数，因此前一交易日的源总量和单位从这张表读。首次启用时用已确认的源数据写入起点。Alembic 在开发时接实际迁移 head。

| 字段 | PostgreSQL 类型 | 含义 |
| --- | --- | --- |
| `ts_code`、`freq`、`trade_date` | `varchar(32)`、`varchar(16)`、`date` | 联合主键，来源固定为 Tushare `idx_mins`。 |
| `source_vol` | `double precision` | 换算前的源成交量日合计。 |
| `source_unit` | `varchar(5)` | `share` 或 `lot`。 |

[取数计划](../../src/foundation/ingestion/unit_planner.py#L1912) · [行转换](../../src/foundation/ingestion/row_transforms.py#L1032) · [任务写入与提交](../../src/foundation/ingestion/executor.py#L786) · [交易日历 DAO](../../src/foundation/dao/trade_calendar_dao.py#L34)

### 2.3 DG：主要指数生成基础 Silver 时转换

1. `major_index_mins_raw.py` 日常从 Tushare 直采，Raw 文件保留源值。日常 Silver 资产调用 `write_major_index_mins_silver_partition`。原生 Silver 构造输出前，用 DuckDB 对当前 Raw 分区按 `ts_code` 执行 `sum(vol)`，直接用收到的文件计算。
2. 原生 Silver 只读依赖现有交易日历定位前一交易日。按原生 Silver 资产键及对应日期读取发布记录中的源合计和单位，按指数匹配。首次启用传入已确认的起点。复用 `MinutePartitionPublication` 的结果记录和现有资产发布元数据，保存每个指数当天的源合计和单位，供下一交易日使用。
3. 将计算结果作为 `ts_code, multiplier` 临时关系，原生直采行的 Silver 投影用 `raw.vol * unit.multiplier AS vol`。既有历史补充如果来自已经归一的 DG 通用 Silver，直接取其中的股数。历史重刷使用阶段 2 的清单。
4. 通用指数 Raw 通过 `write_raw_index_mins_partition_from_prod_db` 从 Prod 按日、按频率复制股数。通用 Silver、两套 90／120 分钟和 Gold 继续按原有流程使用股数。

[DG 主要指数直采](../../lake_console/orchestrator/src/orchestrator/defs/assets/major_index_mins_raw.py#L72) · [Silver 写入](../../lake_console/orchestrator/src/orchestrator/defs/io/major_index_mins_silver_writer.py#L425) · [DG 通用指数同步](../../lake_console/orchestrator/src/orchestrator/defs/assets/index_mins.py#L119) · [发布回执](../../lake_console/orchestrator/src/orchestrator/defs/io/minute_partition_writer.py#L112)

### 2.4 验收

| 样本 | 预期 |
| --- | --- |
| 上证综指 30 分钟，2026-11-09 → 11-10 | 从 42,772,225,700 股到 404,865,177 手，第二天应存 40,486,517,700 股。 |
| 沪市连续为手，含 2026-11-24 | 493,526,296 手应存 49,352,629,600 股。 |
| 上证综指 30 分钟，2026-11-24 → 11-25 | 后一天源值 47,256,142,700 已是股，原值写入。 |
| 深证成指与创业板指样本 | 连续为股，源值原样写入。 |
| 同批重跑及 DG 派生 | 正式输出的股数相同。DG 直采 Raw 保持源值，通用同步和派生继承股数。 |

Prod 验收覆盖行情和单位记录同事务提交。DG 用原生 Silver 写入测试核对转换与重跑，并确认派生周期继续按原时段合计。[DG Silver 测试](../../lake_console/orchestrator/tests/test_major_index_mins_silver_writer.py)

### 2.5 阶段 1 实施与审计记录

- Prod 在原有写入器内处理 `index_mins`，迁移 `20261126_000192` 增加源成交量与单位记录。隔离 PostgreSQL 验证了实际迁移、行情和单位记录同事务提交与回滚，以及同批重跑。Prod 相关回归通过 83 项。[写入转换](../../src/foundation/ingestion/index_minute_volume.py) · [迁移](../../alembic/versions/20261126_000192_add_index_mins_volume_evidence.py)
- DG 复用主要指数的 Raw 与 Silver 作业，原生 Silver 读取前一交易日的计量记录，通用指数分钟继续同步 Prod。隔离 Dagster 和 DuckDB 相关回归通过 67 项。取 2026-11-24 和 11-25 的真实 30 分钟 Raw 分区副本分别核对 90 根，沪市 24 日手转股、25 日直接写股，深圳对照、成交额、时间、开高低收一致。两次隔离写入分别耗时 179.7 和 169.9 毫秒，仅用于记录本次样本。[原生 Silver 作业测试](../../lake_console/orchestrator/tests/test_major_index_mins_publication.py)
- 按首批 11 个交易日的范围读取 DG 通用 Raw 镜像，整理了 189 只指数、10,395 组、667,359 个精确主键的预览，列出 363 个 DG 正式目标文件。同步整理 11 月 24 日已确认的源成交量与单位，其中 Prod 镜像 945 组、DG 主要指数 40 组。阶段 2 用实际 Prod 表值确认预览中的旧值，并按正式启用日期准备上一交易日的起点。
- 本轮使用隔离环境验证。正式迁移、文件发布及读端切换列入阶段 2。

## 3. 阶段 2：定向重刷及读数切换

### 3.1 冻结清单与试点

最小试点用 **`000001.SH`、2026-11-24、30 分钟**。Prod 现有 9 根原生行情总量为 493,526,296 手，目标为 49,352,629,600 股。先生成清单并预演 SQL，再提交该组并从表和视图读回每根的主键、成交量与成交额。DG 用同一组核对通用 Raw、30 分钟 Silver 和基于 30 分钟 Silver 的 90 分钟。需要在正式文件发布其他周期时，先确认那些周期的基础频率已经归一。单一试点不能证明同天全部周期已可发布。只在批准窗口执行正式写入。

首批按方案 §2.1 冻结 **2026-11-10 至 11-24 的 11 个交易日**。Prod 和 DG 通用指数范围为已核实的 189 个指数代码、5 个基础频率，合计 **10,395 组、667,359 根**。主要指数范围为上证综指 `000001.SH`、上证50 `000016.SH`、沪深300 `000300.SH`、中证500 `000905.SH`、中证1000 `000852.SH`、科创50 `000688.SH`、中证A500 `000510.SH`、科创综指 `000680.SH`。代码精确清单由阶段 1 的已核实证据导出并复核，执行时只接受清单中的代码、交易日和频率。查询按这些值限定范围，禁止用沪市后缀直接执行更新或扫描全部历史。11 月 9 日、25 日，以及深证成指、创业板指，仅核对原值。

PostgreSQL 清单每行含 `ts_code, freq, trade_time, old_vol, target_vol`。组头保留交易日、审批范围、源证据和本组非成交量字段的摘要。DG 清单另含数据集、分区频率、日期、正式路径、目标代码、输入与旧文件指纹、预计变化行数。正式执行前冻结清单摘要，计划变动时仅重做有差异的已获准分组。持久化参数与结果沿用现有业务执行与发布回执；全历史扫描、重新拉取已可复用的历史源批次以及扩大本次窗口均超出范围。

### 3.2 PostgreSQL 逐组刷新

准备组清单的查询只读一个代码、一个频率和指定自然日的半开区间，参数绑定沿用表的本地时间。现有复合主键为 `(ts_code, freq, trade_time)`。每组事务先按这些键锁定正式行并分类：

- `vol == target_vol` 的行已完成。
- `vol == old_vol` 的行可以更新。
- 缺键、其他值、非成交量摘要变化或根数与冻结清单不符时，本组保留原结果并核实。

```sql
-- repair_rows 是本事务绑定的单组清单，含完整主键和预期旧值。
UPDATE raw_tushare.index_mins AS bars
SET vol = repair.target_vol
FROM repair_rows AS repair
WHERE bars.ts_code = repair.ts_code
  AND bars.freq = repair.freq
  AND bars.trade_time = repair.trade_time
  AND bars.vol IS NOT DISTINCT FROM repair.old_vol
  AND bars.vol IS DISTINCT FROM repair.target_vol
RETURNING bars.ts_code, bars.freq, bars.trade_time, bars.vol;
```

核对更新根数等于事务刚判定的待更新根数，按同组键读回并核对 `vol`、行情键和非成交量字段后提交。历史修复清单用于更新股数。用于日常判断的源成交量合计和单位，以已确认的源记录为准。续跑读回当前有限主键，确认已等于目标值即可跳过，无需再乘 100。每组保存完成事实并更新现有任务进度；数据库更新只涉及 `vol`，避免沿用普通行情 upsert 覆盖其他字段。

#### Prod 后台入口与隔离试点

- `src/scripts/index_minute_volume_repair.py` 的 `prepare` 接收阶段 1 的主键预览和明确的 `pilot` 或 `first-batch` 范围。按组排序读取预览，逐组按原主键读取目标库并核对旧量或目标量，计算原时间、开高低收、成交额、交易所和 VWAP 的摘要。按组写入一行 JSON，全部吻合后原子冻结文件并返回 SHA-256。试点限定 `000001.SH / 30min / 2026-11-24` 的 9 行。首批限定 §3.1 的 11 日、189 个代码与五个原生频率，代码集合以阶段 1 预览已确认的摘要标识，最多一组 241 行。准备与执行均只读清单指定的行情键。
- `enqueue` 以冻结清单绝对路径及 SHA-256 创建现有 `dataset_action / index_mins / maintain` 的后台任务。执行参数使用专用清单字段，只有后台提交及其原任务重试走该分支。调度器在普通取数计划前分派到按清单重刷函数，现有指数分钟 worker 领取任务。普通补数、自动任务、手动接口和 worker 配置照旧。清单文件保存在同一 worker 可读的持久目录，目录由本次运营命令指定。
- `src/foundation/ingestion/index_minute_volume_repair.py` 负责按原主键锁定、检查旧值与非成交量摘要、绑定单组 `VALUES` 并执行本节更新 SQL。提交前重新按相同键读回。每组一个独立业务事务，TaskRun 及活动节点使用现有独立观察事务。每组前后检查停止请求，按已提交组更新完成数和当前代码、日期、频率。恢复时用同一清单读回目标键，已等于目标值的组计为已完成，该组更新数为零。中途中止保留提交组，业务数据不依赖观察写入成功。冻结文件按组流式消费，无需把全部行情放进任务参数。
- 准备每组只读一次原行情，执行每组一次锁定读取、一次更新和一次读回。事务内沿用 30 秒观察门槛设置单条 SQL 的等待上限。已完成组恢复时只需锁定读取。试点记录执行计划、用时和行数，通过后再核算正式窗口。隔离验收验证 9 根原价、成交额和时间保持原值，实际服务视图返回 49,352,629,600 股，重跑没有再次更新。正式 PG 迁移、DG 正式发布与算子读数切换在运营确认后执行。

#### 隔离试点和独立审计结果

- 使用与 Prod 逐键核对过的上证综指 2026-11-24 的 9 根 30 分钟行情，在隔离 PostgreSQL 经清单准备、后台提交、现有指数分钟 worker 执行，再从正式定义的服务视图读回。首次更新 9 根，合计从 493,526,296 手变为 49,352,629,600 股。同清单由新 worker 重跑，核对 9 根，更新 0 根。价格、时间、成交额、VWAP、交易所字段及同日深市对照保持原值。
- SQL 实际只执行一次针对 `raw_tushare.index_mins.vol` 的更新。锁定查询计划为 Limit、LockRows、Index Scan，返回 9 根。一次隔离试点的提交、执行和任务收尾合计 147.1 毫秒，首次锁定查询返回至开始提交为 1.3 毫秒。计时仅反映九行隔离环境。
- 验证了清单变更被拒绝、非成交量数据发生变化时整组保留原量、状态观察失败和提交后取消均保留已提交行情，以及取消后用同清单重试为零更新。任务和当前节点终态一致。22 项隔离及相关回归通过。
- 独立流式核对阶段 1 的本地预览，包含 189 个确认代码、10,395 组、667,359 根，最大单组 241 根。代码集合变化时拒绝准备或执行。本轮到部署及正式写入前停止。

[后台入口](../../src/scripts/index_minute_volume_repair.py) · [更新与读回](../../src/foundation/ingestion/index_minute_volume_repair.py) · [隔离 PostgreSQL 验收](../../tests/test_index_minute_volume_repair_postgres.py)

<a id="prod-pilot-result"></a>

#### Prod 正式试点和独立审计

- 2026-11-26 北京时间 22:12 至 22:13 在 Prod 执行。部署版本为 `7318d01a5`，实际迁移版本为 `20261126_000192`。试点对象为 `000001.SH / 30min / 2026-11-24`。首次提交前无排队或执行中的指数分钟任务，下次自动任务排在 2026-11-27 19:02。
- 冻结清单 SHA-256 为 `55f9e9ac33f878701748ec2e38283f310985f77c3f2a451556b7e22a471cdbd3`。首次 TaskRun 21244、节点 35987 成功，核对 9 根、更新 9 根。用同一清单重跑 TaskRun 21245、节点 35988 成功，核对 9 根、更新 0 根。两次 worker 任务开始到结束分别为 67.2 和 31.0 毫秒。锁定查询的 `EXPLAIN` 计划为 Limit、LockRows、Index Scan。任务计时仅适用于本次试点。
- 从 `raw_tushare.index_mins` 和 `core_serving.index_minute_bar` 独立逐根读回。两处成交量均由 493,526,296 手改为 49,352,629,600 股。时间键、开高低收、交易所、VWAP 及每根成交额均与更新前一致，成交额合计 771,861,010,308.9 元。重跑后再读回，结果一致。
- DG 只读核对同日上证综指。通用 Raw 30 分钟、两套 Silver 30 分钟各为 9 根，两套 Silver 90 分钟各为 3 根，成交量合计仍为 493,526,296 手。本轮正式写入范围止于 Prod 这一组。首批重刷、DG 文件发布、按实际启用日补充日常同步的单位判断起点及读数切换均待后续推进。

### 3.3 DG 刷新文件及顺序

正式 Lake 根为 `/Volumes/datasource/data_lake`。候选使用现有正式 staging 根 `/Volumes/datasource/data_lake_staging`。Raw 和 Silver 的路径频率是 `freq=30min` 这种字面值，Gold 为 `freq=30`。路径统一由现有构造函数生成，均以 `trade_date=YYYY-MM-DD/part-000.parquet` 结尾。

| 正式层 | 文件数 | 修正输入、键和输出 |
| --- | ---: | --- |
| `raw/tushare/major_index_mins` | 55 个只读 | 读取已确认的直采记录及原始成交量。 |
| `raw/tushare/index_mins` | 55 | PG 组验收通过后按精确键读取股数，将其合并进对应日期、基础频率的 Raw。保留其他代码。目标共 667,359 根。 |
| 两套原生 Silver | 各 55 | 主要指数从直采 Raw 对确认的行算股数，通用指数从已修 Raw 取股数。若用了经确认的历史补充行，直接继承。 |
| 两套派生 Silver | 各 22 | 90 分钟从同日 30 分钟 Silver 生成，120 分钟从同日 60 分钟 Silver 生成。两套 Silver 含原生与派生分别涉及主要指数 28,688 根、通用指数 677,754 根。 |
| 两套 Gold | 各 77 | 按既有规则从各自 Silver 生成待替换的成交量。目标到源周期的映射是 `1→1、5→1、15→5、30→5、60→30、90→30、120→60`。Gold 涉及主要指数 28,336 根、通用指数 669,438 根。 |

每个文件通过现有 Raw/Silver 或 Gold 计算入口生成成交量投影，按 `ts_code + trade_time` 与同频率旧文件合并。数据库使用原生频率字段，DG 文件内频率由路径和现有 schema 固定。`vol` 来自正式单位确认的输入或窗口求和。目标代码应覆盖预定的原有键，合并后所有 `vol` 以外的列用正式旧值，未上线的目标键和其他代码保持原样。若现有窗规则计算的键与计划不一致，暂停该文件复核。原子替换前用同分区 SQL 差集校验两侧键集合及非 `vol` 列等价，用逐行或逐窗口量差核对目标键。基础频率先发布，随后使用已发布的基础文件生成派生 Silver 和 Gold；切换日前后的首屏和续页读同一版存储合同。

候选的合并查询如下。`formal_bars` 只指当前日期、频率的正式文件，`repaired_volume` 是按本节依赖算出的目标键和股数。两边在合并前检查主键唯一，且所有目标键均存在于正式文件。

```sql
SELECT old.* REPLACE (
    CASE WHEN repair.ts_code IS NOT NULL THEN repair.vol ELSE old.vol END AS vol
)
FROM formal_bars AS old
LEFT JOIN repaired_volume AS repair USING (ts_code, trade_time);
```

Raw/Silver 沿用 `MinutePartitionPublication` 的候选、校验和逐文件回执；Gold 沿用现有 Gold 写入器的候选及同文件系统原子替换，将正式文件摘要与同一份重刷清单中的文件进度核对。已经发布的文件重跑先校验读回指纹，变化的输入或旧值冲突只复核该目标文件。只对清单内已验证旧版本使用显式覆盖。冻结一份发布记录关联数据集、日期、频率、旧与目标文件身份和已发布结果，阶段 2 结束时共核对 **363 个正式文件**，即 55 个通用 Raw 加 4×77 个 Silver／Gold。影响面包括用到这些文件的成交量读取。现有九转、技术指标、结构识别等只消费价格或 MACD 的输出，以及只消费成交额的统计，沿用现值。其他确实持久化成交量的结果要经引用审计列明后才可纳入变更清单。[分区路径](../../lake_console/orchestrator/src/orchestrator/defs/paths.py#L1088) · [Gold 窗口映射](../../lake_console/orchestrator/src/orchestrator/defs/run_contracts/cn_a_derived_minute_bars.py#L11) · [Gold 写入器](../../lake_console/orchestrator/src/orchestrator/defs/io/cn_a_gold_minute_writer.py#L98) · [结构识别选列](../../src/biz/queries/wealth/market/index_detail_xxm/source.py#L252) · [成交额读取](../../src/foundation/clients/local_lake/major_index_turnover_reader.py#L238)

### 3.4 撤转换时同时核对数据、算子和接口

1. **DG 主要指数分钟。** 归一前，`_DG_RECENT_MINUTE_VOLUME` 针对 2026-11-10 至 11-24 的沪市记录执行 `vol * 100`。对应 DG 文件全部确认后，在 `dg_recent_index_minute_sql` 的直接读取路径用 `vol AS volume`，在 90／120 分钟合成路径用 `sum(vol) AS volume`。开高低收、成交额、时间窗口和分页 SQL 沿用现有实现。
2. **DG 通用与 Prod 既有 5 分钟。** `index_minute_volume_unit` 当前同时承担来源校验、指数支持范围和静态倍率。保留现有后端、数据集、频率、复权方式以及指数代码的校验，输入单位改为股。核对 `_describe_index_minutes` 与 PostgreSQL 两处调用。**撤掉全历史读数的静态倍率之前，须核清每个后端受旧倍率影响的支持代码及相应时段。** 首批 11 天和对照样本只证明核过的区间。如果发现其他异常时段，仅列出实际核实的日期、代码、频率并走同一有界清单确认流程。没核清的来源暂不切换全历史读取声明。
3. **发布操作。** 在同一次维护窗口协调写入保护、数据刷新及所涉读者版本。按来源验收后恢复相应读者和任务，避免旧读者对已经归一的行情多乘一次。保留已提交组及文件确认结果，中断后完成对应来源再恢复流量。外部分钟 API 成交量仍为股，原有支持范围、回包字段和成交额口径继续沿用。

[两处旧单位逻辑](../../src/foundation/clients/technical_indicator_index_minutes.py#L8) · [DG 5 分钟适配](../../src/foundation/clients/local_lake/technical_indicator_price_locator.py#L793) · [Prod 来源校验](../../src/foundation/clients/technical_indicator_postgres.py#L168) · [Prod 单位使用](../../src/foundation/clients/technical_indicator_postgres.py#L405)

### 3.5 执行进度、资源与验收

| 项目 | 实施要求 |
| --- | --- |
| Prod 执行入口与持久化 | 复用现有 `index_mins` 任务执行通道及 TaskRun／活动节点进度，定向重刷采用冻结清单执行。一个代码、交易日、原生频率是一笔提交，10,395 组串行分批。无需全历史事务或新工作进程。任务运行期间协调现有自动写入窗口。 |
| Prod 内存和请求 | 日常保留现有源分页及已有请求窗口，单位保护复用同批内存行和上一开市日证据。冻结清单与正式重刷按组分页保存和读取，内存只保留当前组的行与摘要。试点 30 分钟为 9 根。按目前沪深原生时段，1／5／15／30／60 分钟每组分别为 241／49／17／9／5 根，包含开盘记录。试点实测扫描行数与 SQL 计划，避免把目标根数当成数据库实际扫描量。按计划首批的历史回读以 667,359 条目标键为范围，重刷无需重请求 Tushare。 |
| 进度和取消 | Prod 显示阶段、当前代码／日期／频率、已完成组数、总组数、百分比和最后更新时间，使用现有运行状态与进度上报。每组前后检查取消，每组提交后上报；活跃运行的可见更新遵守现有 30 秒门禁，实测一个组事务或对账不能阻塞超过该窗口，耗时仍未知则不填写 ETA。终态同时校准 TaskRun 和活动节点。 |
| 续跑与最后读回 | Prod 中断后从首个未确认组开始，只回读已冻结的相关主键确定进度。DG 按回执和正式文件摘要定位未完成文件，已完成文件直接核对摘要。最终验收读冻结范围的摘要与指定边界样本，无需增加一轮重新拉取或全历史扫描。 |
| 试点与性能测量 | 第一批正式执行前测一组 Prod SQL 的计划、读写锁持有时长、更新根数与提交时长，并测实际取消、重新执行和读回。DG 测一个日期、基础频率的输入和目标文件数、Parquet 字节数、构造与发布用时，带上一个关联派生文件。按清单逐项汇总候选生成、续跑和最后验收开销后再排正式窗口。隔离试点实测见 §3.2。正式批次的累计时间按正式试点实测估算。 |
| 边界对账 | 核对 11 月 9→10 日和 24→25 日，选上证综指 30／90／120 分钟及深证成指对照。已核实手数只乘一次。实际接口验证首屏、左翻页、本地 5 分钟及 Prod 既有 5 分钟读取；确认所有时间、非目标行、OHLC、成交额保持原值。核验中断续跑并确认新写入的日常样本按股。 |

Prod 历史 APPLY 按长任务交付。已提交数据的续跑事实来自清单主键读回，任务状态写入失败不回滚已提交组。DG 使用数据湖既有候选和发布机制。性能预算依据当前源分页、交易日合同和首批实际行数，开工后的计时、真实取消和续跑结果补入本节。[Prod 长任务要求](../templates/dataset-development-template.md#035-prod-数据集长任务识别与执行合同) · [现有任务通道](../../src/ops/runtime/worker_lane.py#L13) · [DG 性能规范](../../lake_console/docs/design/dagster-data-pipeline-performance-governance.md)

## 4. 阶段 3：指数详情统一显示手

| 文件或调用点 | 修改 |
| --- | --- |
| `indexMinuteViewModelAdapter.ts` | 在分钟 K 线原有适配函数里设 `volume = bar.vol / 100`。首屏和续页共用此处，保留小数手。API DTO `vol` 仍是股。 |
| `indexDetailViewModelAdapter.ts` | 右栏总量使用 `quote.vol`，日周月 K 使用 `bar.vol`；两者已是手。重新生成 ViewModel 的成交量显示文案，API `volDisplay` 字段继续保留。 |
| 指数详情格式化函数 | 增加指数详情内部的 `formatIndexVolumeLots(value)`。无值显示 `--`，零显示 `0手`。不足万手显示手，满万和满亿分别显示万手和亿手。显示值保留至多两位小数，用原手数绘图。例如 12,345 股 → 123.45 手，显示 `123.45手`；10000 手显示 `1万手`。 |
| `IndexMinuteChartWorkspace.tsx` 与 `IndexChartWorkspace.tsx` | 顶部成交量总量、对应悬浮提示共用指数成交量格式化函数。普通与结构图工作区两处都传入统一的图表成交量格式。 |
| `DetailChartWorkspace.tsx` 与 `detailChartTypes.ts` | 增加可选 `formatVolume?: (value: number) => string`。指数传入后，成交量 Histogram 的右轴采用自定义格式，成交量面板的十字线标签用同一个函数；其他调用继续使用现有 volume 和通用轴格式。不要在共享图表再除以 100。 |

验收用实际 `/minutes` 回包核对同根柱的数值与右轴、顶部总量、十字线和悬浮提示。覆盖至少一个有小数手的分钟样本，检查日、周、月与分钟切换、分钟首屏和续页，比较右栏从原有手数生成的格式。对共享股票图测一条原有成交量展示回归。成交额继续走各自现有格式。[分钟适配](../../wealth/src/features/index-detail/api/indexMinuteViewModelAdapter.ts#L108) · [日周月与右栏适配](../../wealth/src/features/index-detail/api/indexDetailViewModelAdapter.ts#L101) · [分钟图](../../wealth/src/features/index-detail/chart/IndexMinuteChartWorkspace.tsx#L180) · [日周月图](../../wealth/src/features/index-detail/chart/IndexChartWorkspace.tsx#L290) · [共享成交量柱与十字线](../../wealth/src/shared/charts/detail-workspace/DetailChartWorkspace.tsx#L315)

## 5. 阶段交付

| 阶段 | 进入和完成条件 |
| --- | --- |
| 1. 入库保护 | 以本 LLD 和专项方案为开发依据。完成 Prod、DG 直采两处保护、隔离与有界样本验收，并生成可审查的 PG 主键、DG 文件清单及首次启用证据。 |
| 2. 定向重刷 | 先验证单组和受影响的 DG 窗口，批准后按冻结清单依次发布。目标数据、现行读数以及有界性能、续跑验收全部通过后恢复对应读者和自动任务。 |
| 3. 页面展示 | 复用已归一的分钟接口，在页面以手显示并做浏览器验收。按现在方案范围核对 Prod 数据读取合同和股票图表回归。 |

首次生效时使用已确认的源成交量合计和单位作为起点。阶段 2 按首批清单和 §3.4 发布数据及切换对应读数。
