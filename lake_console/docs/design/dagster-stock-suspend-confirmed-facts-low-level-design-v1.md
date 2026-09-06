# 本地 DG 停牌历史确认事实持久化与统一消费 LLD v1

更新时间：2026-09-06

状态：**S1 部分代码已编写但未验收；测试越权事故记录见 §17。用户已同意“先补 LLD review → 仅修隔离与两个新检查 → 独立验收 → 继续 S1”的顺序；本轮只完成 §18 安全实施细化，等待 review，未恢复代码修改或测试。指定 Silver sensor 未自行恢复。未迁移停牌数据、发布正式事件、切换或删除旧文件；事故不能改写为正式环境零写入。§15.3 窄修正已获确认。**

代码基线：`dev-interface@b324ec48ce8fd67fdf216fedc6a69103fab4ae3a`。

上位依据：[技术方案 v1](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-suspend-confirmed-facts-technical-plan-v1.md)。本文细化该方案，不另起业务口径；原清退专项的 `TODO-SUSPEND-001` 仍未关闭。

本文所有“新增”“改为”、函数签名、SQL、命令及测试名，均是**待实施设计**。用户随后已批准 S1 开发、隔离测试及仅暂停 `silver_suspend_d_update_job_sensor` 的维护安排；维护期间不手工启动停牌 Silver job，Raw 和其他入口不动。该批准不包含正式 Lake/staging 写入、正式 materialization/check 事件、服务重载、删除或 Git 提交。S1 结束不自动恢复该 sensor；等 S3/S4 验收或另行明确批准。本次实际执行及新发现的停止条件见 §15。

实际证据：[S0 审计清单](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-suspend-confirmed-facts-s0-audit-checklist-v1.md)。以下设计不得与 S0 已完成的只读核验混为一谈。

## 1. 交付目标与硬边界

目标只有一个：把当前 CSV 中已确认的历史全日停牌事实，迁移为显式登记、可验证的固定 Silver 输入；现有本地 DG 消费者继续只认 `silver_stock_suspend_daily`。

| 编号 | 硬口径 | 实现落点 | 验收组 |
| --- | --- | --- | --- |
| H01 | Raw 原样镜像不动，不回写、不冻结、不新增源请求 | Raw asset、`tushare_api_io.py` 不改；发布入口无 Raw 写路径 | B、G |
| H02 | 新固定输入只有一个正式文件、一个人工写入方 | §3、§8；`AssetSpec` 无计算函数 | C、B、D |
| H03 | 最终 Silver 四列、原路径、分区、asset/check/job 名称不变 | §4–6、§10 | M、D、G |
| H04 | 保留 4,022 个确认键及两个明确覆盖键的效果 | 固定内容身份、合并 SQL、全范围对账 | C、M、B |
| H05 | 其余冲突仍先失败；保留 14 条时段清洗及执行顺序 | §4；只退出 `suspend_full_day` 链 | M |
| H06 | 不依赖旧 Silver、CSV、Git 或进程缓存生成日常结果 | 新输入校验与纯 SQL；静态直接读取方白名单 | C、M、G |
| H07 | 日线、分钟、恢复工具只读最终停牌 Silver | §10 保留矩阵；不改 `stk_mins` CLI | G |
| H08 | 候选完整校验，同文件系统逐文件原子提升和对账 | §5、§8；正式 Lake 内不生成本轮候选 | W、B |
| H09 | 文件写入与事件登记分开批准，事件失败不回滚数据 | §8–9 | E、B |
| H10 | 不改 Prod、远程 Web、ClickHouse、Ops snapshot 和旧湖 | 文件矩阵与禁止路径测试 | G |
| H11 | 历史对账有界、集合式；不全历史逐日 materialize | §8、§12 | B、P |
| H12 | 删除精确两文件，先等价验证、发布、切换并获准 | §11；时段修正文件保留 | G |
| H13 | S1 测试不得访问正式文件/实例/网络，隔离先验收、业务后运行 | §18 的专用测试启动器、测试资源和两个新 checks；不改全局资源 | I、D |

测试编号在 §13 定义。硬口径不是“测试通过后可以顺便做”的授权；实施仍按 §11 分阶段验收。

## 2. 代码复核结论与容易误改的地方

本轮先用 CodeGraph `explore` 检查生成 SQL、sensor 日期选择和调用入口，再用 `impact(silver_stock_suspend_daily_path, depth=2)` 检查分钟 writer/check 影响面；结合当前源码搜索补齐图中未覆盖的消费者和测试。影响范围在 orchestrator 内，不新增子系统间依赖。

| 当前位置（行号仅对应上述基线） | 已核事实 | 设计约束 |
| --- | --- | --- |
| `defs/duckdb_sql.py:359` | Raw 标准化为四列，日期解析，空白时段转 NULL | 保留表达式，不改源字段 |
| `defs/duckdb_sql.py:373` | 同日 Raw＋14 条时段修正＋CSV 范围＋两条覆盖 | 删除范围/覆盖元组输入，改用已验证关系；不是删除所有 corrections |
| `defs/assets/suspend_d.py:164` | 冲突查询检查的是**时段修正前的 normalized Raw** | 不能把冲突查询移到时段清洗之后 |
| `defs/assets/suspend_d.py:267` | 覆盖统计按实际 Raw 命中键数和行数计算 | 区分“规则键数”“命中键数”“移除源行数” |
| `defs/assets/suspend_d.py:84` | 本文件的 `.tmp` writer 只有 Silver 调用；Raw 使用另一个 IO helper | 替换并删除这个私有 writer；不按同名函数批量修改其他文件 |
| `defs/assets/suspend_d.py:421` | 资产依次检查冲突、统计、写 Silver、输出 metadata | 新来源加载放在冲突检查前；失败不得先碰正式输出 |
| `defs/sensors/suspend_d_sensor.py:429` | 候选是待生成日期的前 2 个，按原 Raw readiness 筛选 | 固定输入检查放在截取候选后、日期循环前，只做一次 |
| `defs/sensors/readiness.py:370` | 通用单资产检查会取最多 5,000 条历史记录 | 新固定资产不照搬该深扫；只取最新 materialization 和各 check 最新记录 |
| `tests/test_asset_governance_contracts.py:331` | 当前集合处理 `.keys` / `.get_asset_spec()`，假定全是可执行定义 | 显式支持 `AssetSpec`，保留 catalog/schema/check 全覆盖 |
| `tests/architecture/test_lake_console_retirement_guardrails.py:174`（仓库根） | 当前把 CSV 存在作为保护锚点 | 获准删除时只替换这个锚点，不放宽其他保护 |

上表的当前文件位于 [orchestrator 工程](/Users/congming/github/goldenshare/lake_console/orchestrator)，根测试另行标注。没有把文件名、CodeGraph 零命中或历史报告当作无人使用的证明。

2026-09-06 S0 已刷新物理只读证据：31 范围、29 代码、4,022 键、1,857 日期；现有 Silver 已包含全部确认结果；Raw 中 4,020 键缺失，两个覆盖键共 3 行。两层各 3,083 文件的内容身份已冻结，审计前后无漂移。详情见 S0 清单；这不是新 helper 等价验收或发布凭据。

## 3. 固定资产合同、路径与身份

### 3.1 完整 registry 事实卡

| `LakeAssetCatalogEntry` 字段 | 新登记值 |
| --- | --- |
| `asset_key` | `silver_stock_suspend_confirmed` |
| `dataset_id` / `dataset_name` | `stock_suspend_confirmed` / 股票历史确认全日停牌事实 |
| `layer` / `data_domain` / `group_name` | `AssetLayer.SILVER` / `DataDomain.QUOTE_DATA` / `quote` |
| `source_system` / `data_contract_source` | `SourceSystem.SEED` / `DataContractSource.SEED_CONTRACT` |
| `data_contract` | `confirmed_stock_full_day_suspend_v1` |
| `column_schema` | 新增 `SILVER_STOCK_SUSPEND_CONFIRMED_SCHEMA`，见 §3.2 |
| `path_template` | `{lake_root}/silver/quote/stock_suspend_confirmed/full/part-000.parquet` |
| `partition_model` | 新增 `PartitionModel.FULL_FILE_SILVER_STOCK_SUSPEND_CONFIRMED`，值 `full_file_silver_stock_suspend_confirmed` |
| 分区模型登记 | `FULL_FILE` family、Silver、dataset `stock_suspend_confirmed`、Dagster dimension `None`、`SINGLE_FILE` layout |
| `source_api` / `source_doc` | `None`；不是 Tushare 新接口，溯源另进审计 metadata |
| `ingestion_sources` | `(IngestionSource.SEED_FILE,)` |
| `default_daily_ingestion_source` | `None` |
| `bootstrap_sources` | `(IngestionSource.SEED_FILE,)`；含义限于人工批准的 Parquet 发布 |
| `blocking_check_names` | §6.2 的两个固定 check 名称 |
| `write_policy` | `SINGLE_FILE_ATOMIC_REPLACE`；额外收紧为缺失发布、等价复用、不等停止 |
| `event_policy` | `SUPPORTS_RUNLESS_EVENT_BACKFILL` |
| `performance_contract` | `batch_grain="one_confirmed_file"`、`DUCKDB_SQL`、`python_row_loop_allowed=False`、`source_request_policy="none"` |
| `notes` | 固定历史确认集，人工单 writer，无日更 freshness；仅最终停牌 Silver 作为业务消费者 |

`lake_assets.py` 仍只是 registry，不用它动态生成 assets/jobs 或执行发布。新 AssetSpec 使用既有 metadata/tags helper，值与事实卡一致。

### 3.2 字段及内容校验

列序严格固定，不允许 `SELECT *` 的隐式字段扩散：

| 序号 | 字段 | 物理类型 | 值域 / NULL |
| --- | --- | --- | --- |
| 1 | `ts_code` | `VARCHAR` | 非 NULL；六位数字＋`.SH` / `.SZ` / `.BJ`；不 trim、改大小写或重映射身份 |
| 2 | `trade_date` | `DATE` | 非 NULL；原事实发生日，不使用发布日期 |
| 3 | `suspend_timing` | `VARCHAR` | 必须为 NULL；空字符串不等价 |
| 4 | `suspend_type` | `VARCHAR` | 必须为 `S` |
| 5 | `merge_mode` | `VARCHAR` | 非 NULL，`add_missing` 或 `replace_confirmed` |

复用现有 `ColumnContract(name, type, description)`。它**没有 nullable 参数**，不为本专项修改全局 schema 类型；非空和值域约束由内容 validator 明确实现。schema check 比较实际列名、列序和 DuckDB 物理类型，不先 cast 成目标 schema 再说“通过”。

内容门禁：总行数 4,022；不同键 4,022；不同代码 29；不同日期 1,857；`add_missing=4,020`、`replace_confirmed=2`；五列逻辑哈希等于批准值。两个覆盖键必须恰好是 `688766.SH / 2025-11-26`、`688005.SH / 2026-01-16`，不得多、少或换键。

这两个键作为合同验收断言保留，不再作为独立 SQL 覆盖规则表；运行时覆盖模式来自已批准 Parquet。不得把 31 条区间或 4,022 行复制进 Python 常量。

### 3.3 唯一身份与确定性编码

新增 `defs/stock_suspend_confirmed_contract.py`，定义：

- `STOCK_SUSPEND_CONFIRMED_VERSION = "confirmed_stock_full_day_suspend_v1"`。
- `STOCK_SUSPEND_CONFIRMED_APPROVED_LOGICAL_SHA256`：S0 已实算为 `c88a7406ecda31c7dfe92b20b1d9cc719ffd2d049ece93113676ef4e60db4307`，规范编码 152,875 字节，两种 SHA-256 实现复核一致。该常量已写入部分实现，但不代表 S1 已验收。不能填写样例值、空值后默认通过，或由运行时文件反向给自己背书。
- 固定 check 名称元组、两个模式、预期计数和两个覆盖键断言；schema 本体仍只定义在 `asset_column_schemas.py`。

哈希编码 v1：

1. 先通过 schema、非空、值域和重复键校验。
2. 按 `ts_code` 的 ASCII 顺序、`trade_date` 升序排列全部行。
3. 头行字节为 `stock_suspend_confirmed|v1\n`。
4. 每行五列以一个 TAB（`0x09`）连接；日期为 `YYYY-MM-DD`；NULL 用两个 ASCII 字符 `\N`；行末恰好一个 LF（`0x0a`）。无 BOM、CR、额外空格或末尾空行。
5. 此合同的代码、日期、枚举都是 ASCII，禁止值中包含 TAB/LF/反斜线，NULL 标记不与合法值冲突。因此无需自定义字符串转义系统。
6. 在 DuckDB 中有序 `string_agg` 得到上述单个有界字符串，Python 只对其 UTF-8 bytes 调用一次 SHA-256；不逐行处理业务数据。禁止依赖默认行序、Parquet 二进制哈希或 JSON 库默认格式。

字面金样本（**仅编码测试，不是生产事实集**）对应 bytes 表达式：

```python
b"stock_suspend_confirmed|v1\n" \
b"000001.SZ\t2020-01-02\t\\N\tS\tadd_missing\n" \
b"688005.SH\t2026-01-16\t\\N\tS\treplace_confirmed\n"
```

该样本 SHA-256 为 `dc7dde4185854a5c36d1fdc7a6da7e02405272fd688488bb3904f732a9914099`；它只是编码金样本，与 S0 的实际 4,022 行指纹不同，不能用作正式内容批准值。测试同时固定 bytes 和 digest，并用重排行、改变压缩、NULL 改空串、改一个模式作反例。

### 3.4 路径函数与边界

在 `defs/paths.py` 新增以下纯函数；不创建目录，不检查 instance：

```python
silver_stock_suspend_confirmed_path(root: Path) -> Path
stock_suspend_confirmed_staging_dir(staging_root: Path, operation_id: str) -> Path
silver_stock_suspend_daily_staging_path(
    staging_root: Path, run_id: str, trade_date: str
) -> Path
```

分别返回：

```text
data_lake/silver/quote/stock_suspend_confirmed/full/part-000.parquet
data_lake_staging/stock_suspend_confirmed/run_id=<operation_id>/
data_lake_staging/stock_suspend_daily/run_id=<run_id>/trade_date=<date>/part-000.parquet
```

`operation_id/run_id` 只允许 `[A-Za-z0-9][A-Za-z0-9_-]{0,79}`；日期须实际解析并与 ISO 字符串一致。不得复用错误信息或语义专属于 ETF/index_global 的私有校验器，亦不借机重构其他 staging helper。

正式 CLI 固定现有 Lake/staging 根，不提供 `--lake-root`、`--target` 或任意目录覆盖。测试通过 helper 参数注入临时根，不能通过运行时“测试模式”开放正式路径绕过。

IO 边界进一步检查：挂载存在；规范化路径在批准根；各路径组件无符号链接；目标不是目录/其他文件类型；candidate 与目标父目录 `st_dev` 相同；空间/权限符合本次预算。缺移动盘时失败，不能在系统盘自动创建同名 `/Volumes` 目录。

## 4. 纯校验和 SQL 合并接口

### 4.1 模块与连接边界

`stock_suspend_confirmed_contract.py` 不 import assets、jobs、sensors、bootstrap 或 `duckdb_sql.py`，不读取 CSV、Git、Dagster instance 或文件级历史报告。以下是目标接口，不是已存在的 API：

```python
load_confirmed_relation(connection, path: Path, *, relation_name: str) -> LoadedConfirmedFacts
validate_confirmed_schema(connection, relation_name: str) -> ValidationResult
validate_confirmed_content(connection, relation_name: str) -> ValidationResult
confirmed_logical_sha256(connection, relation_name: str) -> str
```

`load_confirmed_relation` 用参数绑定的 `read_parquet(..., hive_partitioning=false)` 创建本连接 TEMP TABLE：直接读物理五列、不做 cast/trim。`relation_name` 必须是代码指定的简单 SQL identifier，并经白名单校验；不是 CLI 输入。缺列/多列/错序在 cast 之前失败。加载前后比较文件身份，加载一次后 schema、内容、合并共用该内存关系；连接结束即销毁，无跨 run 缓存。

| 结果对象 | 必要字段 |
| --- | --- |
| `LoadedConfirmedFacts` | `relation_name`、`path`、`file_identity`；不返回全量 Python 明细 |
| `ValidationResult` | `passed`、`reason_code`、`checked_rows`、`failed_rows`、最多 20 条 `samples`、`logical_sha256`（校验可计算时） |
| `ConfirmedFactsSummary` | version、logical_sha256、row_count、code_count、date_count、两模式计数、日期范围 |
| `FileIdentity` | resolved path、device、inode、size、mtime_ns；人工发布另存物理 SHA-256 |

底层 validator 返回可解释失败，CLI 转为 JSON 和退出码。Dagster adapter 原拟转为 `AssetCheckResult` / `Failure`；**S1 实测表明前者自动关联发布记录的假设不成立，不得照此实现两个固定 checks**，采用已确认的 §15.3 显式原生关联方案。不得在纯函数里自己创建连接或输出假绿 event。schema check 的 passed 只由 schema 决定；为记录检查对象身份，在内容可规范编码时复用实际 digest 计算，不把批准常量当作“实测 hash”。不能编码时该值留空，内容 check 明确失败。内容 check 先 schema 合格再判内容；每日 generator 两项都必须满足。

`duckdb_sql.py` 保留 `suspend_d_normalized_select(raw_path)`；移除旧两参数 `silver_stock_suspend_daily_select(raw_path, partition_key)`，**不保留兼容 wrapper**，替换为：

```python
silver_stock_suspend_daily_select(
    *, normalized_relation: str, confirmed_relation: str, dates_relation: str
) -> str
stock_suspend_confirmed_conflicts_select(
    *, normalized_relation: str, confirmed_relation: str, dates_relation: str
) -> str
stock_suspend_confirmed_stats_select(
    *, normalized_relation: str, confirmed_relation: str, dates_relation: str
) -> str
```

三个 relation 均由调用者在同一连接建立。日常 `dates_relation` 一行 `trade_date DATE`；批量审计是已批准日期集合。`normalized_relation` 保留原始标准化后的重复行，`confirmed_relation` 必须先通过全文件批准身份校验，不能仅校验当天切片。

这三个 helper 返回 SQL，不执行 IO、不打开其他日期路径、不调用 instance。共同的 CTE 构造保留在 `duckdb_sql.py` 私有 helper，三个查询共享定义；不是复制三份合并公式。

### 4.2 查询关系与执行次序

```text
当次明确 Raw 文件集合 -> normalized（保留重复）
批准固定文件 -> validated_confirmed -> selected_confirmed（按 dates）
normalized + selected_confirmed -> conflicts -> 有冲突则停止
normalized + 原14条时段修正 -> timing_corrected
timing_corrected - replace_confirmed键 -> retained
selected_confirmed中待补/覆盖行 -> additions
retained UNION ALL additions -> 最终四列
```

`normalized` 对日常 Raw 仍使用原日期解析/空白时段标准化。日期归属继续遵守原 Raw partition check；不把其他日期记录悄悄过滤掉以掩盖错误。

关键 SQL 模板（relation 名为内部固定名，以下省略通用转义代码）：

```sql
-- 冲突：与当前实现一致，在时段清洗之前检查。
SELECT n.ts_code, n.trade_date, n.suspend_type, n.suspend_timing
FROM normalized n
JOIN selected_confirmed f USING (ts_code, trade_date)
WHERE f.merge_mode = 'add_missing'
  AND NOT (n.suspend_type = 'S' AND n.suspend_timing IS NULL);
```

保留上式现有业务判定，不借迁移重定义 Raw NULL 合同。非法 Raw 仍受现行 Raw checks 约束；本轮不额外修改其字段清洗。总冲突数用聚合准确计数，样本另取排序前 20 条，**不再把 `len(LIMIT 20 样本)` 当总数**。

```sql
WITH selected_confirmed AS (
  SELECT f.* FROM confirmed f JOIN selected_dates d USING (trade_date)
), corrections(ts_code, trade_date, corrected_suspend_timing) AS (
  /* 原 suspend_timing_corrections_values_sql() 原样生成 */
), timing_corrected AS (
  SELECT n.ts_code, n.trade_date,
         COALESCE(c.corrected_suspend_timing, n.suspend_timing) AS suspend_timing,
         n.suspend_type
  FROM normalized n
  LEFT JOIN corrections c USING (ts_code, trade_date)
), retained AS (
  SELECT n.* FROM timing_corrected n
  WHERE NOT EXISTS (
    SELECT 1 FROM selected_confirmed f
    WHERE f.merge_mode = 'replace_confirmed'
      AND f.ts_code = n.ts_code AND f.trade_date = n.trade_date
  )
), additions AS (
  SELECT f.ts_code, f.trade_date, f.suspend_timing, f.suspend_type
  FROM selected_confirmed f
  WHERE f.merge_mode = 'replace_confirmed'
     OR (f.merge_mode = 'add_missing' AND NOT EXISTS (
       SELECT 1 FROM retained n
       WHERE n.ts_code = f.ts_code AND n.trade_date = f.trade_date
         AND n.suspend_type = 'S' AND n.suspend_timing IS NULL
     ))
)
SELECT ts_code, trade_date, suspend_timing, suspend_type FROM retained
UNION ALL
SELECT ts_code, trade_date, suspend_timing, suspend_type FROM additions;
```

执行此合并 SQL 的前置条件是冲突查询通过；不能把 `select` helper 独立当作已校验 writer。所有正式调用通过 §5 的唯一写入函数，批量审计同样先检查冲突。

### 4.3 业务与统计边界

1. `add_missing` 无 Raw：补一行。已有一行正确全日记录：复用，不重添。
2. 已有两行正确全日记录：仍保留两行，现有重复 check 应失败；不得用 `DISTINCT` 美化结果。
3. 正确全日记录与 R/盘中记录并存：仍冲突失败，不能因找到一条正确行就跳过冲突。
4. 两个 `replace_confirmed` 键：不论当天 Raw 缺失、已正确或出现多条现行记录，沿用按键排除后补一行的旧规则。不把模式改成“只覆盖本轮采样的那 3 行”。
5. 未命中固定事实的行不变；两条覆盖键之外绝不自动覆盖。
6. 14 条时段修正继续在 `timing_corrected` 生效；冲突检查用之前的 normalized，与旧实现顺序相同。
7. 字段中不再携带股票名称，样本以股票代码＋日期标识；不为展示名称额外读 stock_basic。

统计接口输出：`selected_fact_keys`、`add_missing_inserted_keys`、`add_missing_reused_keys`、`replace_confirmed_keys`、`replace_confirmed_matched_raw_keys`、`removed_raw_rows`、`conflict_rows`、`output_rows`、最多 20 条分类样本。前三类确认键归属应能对账；“覆盖键数”不得与“被覆盖 Raw 行数”混用。

## 5. 每日 Silver writer：精确改法与失败恢复

### 5.1 入口与正常流程

`defs/assets/suspend_d.py` 新增内部正式 writer（供 asset 和隔离测试调用，不做新 CLI）：

```python
write_silver_stock_suspend_daily_partition(
    connection, *, lake_root: Path, staging_root: Path,
    trade_date: str, run_id: str
) -> SuspendDailyWriteResult
```

输入路径只能由三个正式 helper 派生。保留原 `silver_stock_suspend_daily(context, lake_root, duckdb)` 入口和资源契约，连接继续使用统一 `connect_configured_duckdb(...)`；不引入裸连接或新 DuckDB 配置。

执行顺序：

1. 校验挂载、根路径、trade_date/run_id 和该日 Raw 存在；核验本次维护/任务无同日另一个 writer。
2. 加载固定全文件到 TEMP TABLE，schema＋批准内容校验通过；记录输入 version/hash/file_identity。
3. 同日 Raw 一次加载为 normalized TEMP TABLE，记录 Raw 文件物理 SHA-256 和身份。生成一行日期关系。
4. 执行原口径冲突查询；非零抛 `dg.Failure`，正式输出和旧输出不变。
5. 构造一次输出 TEMP TABLE，统计结果。若目标存在且四列 schema/双向 `EXCEPT ALL` 已等价，复核输入与目标未变后返回 `reused`，不覆盖；否则 `COPY` 到本 run 独立 staging 候选，绝不在正式目录写 `.tmp`。
6. 重新读取候选，验证四列物理 schema、完整可读、行数及相对输出 TEMP TABLE 的双向 `EXCEPT ALL=0`。合法空表保留四列类型；不能以空表为失败。
7. 固定输入/Raw 未变、目标仍为本次记录的前态；同文件系统检查通过。候选 fsync 后，写入 `prepared` checkpoint，再 `os.replace(candidate, target)`。不预先删除正式目标。
8. fsync 目标父目录、读回目标验证候选物理 SHA-256；checkpoint 写 `committed`，返回统计。元数据/事件由原 asset 框架产生。

第 6 步是候选与已计算结果的**传输完整性**校验，不引入一套新的交易判断；原三个最终 Silver checks 仍在写后运行，重复、类型值域和分区归属语义不放宽。不会为了减少 checks 而把所有业务质量判断塞进 writer。

### 5.2 每文件 checkpoint 与并发边界

checkpoint 位于候选同目录 `checkpoint.json`，写 checkpoint 的临时文件也只能在 staging。字段：schema_version、run_id、trade_date、source Raw path/sha256、confirmed version/logical_sha256、候选 path/sha256、目标 path、目标写前身份或 absent、阶段、最近更新时间和错误摘要。

只需要 `prepared` / `committed` 两个持久阶段，不增加任务队列、锁服务或庞大状态机。校验前临时中断的未完成候选不是可提升候选。

| 重试现场 | 处理 |
| --- | --- |
| 目标已等于 prepared 候选 hash，checkpoint 未记 committed | 物理确认已完成，补 checkpoint，返回；不再 replace |
| 候选完整、输入未变、目标仍为记录前态 | 校验后继续同一个逐文件提升 |
| 原目标未变、候选不存在、无 prepared | 可以在本 run 重新计算；若已有残缺候选则保留并停止，人工核验后再发起新 run |
| 有 prepared、候选丢失、目标也不匹配 | 停止，保留现场人工核验；不猜测发生了什么 |
| Raw、固定输入或目标在中途变化 | 本次结果不可直接提升；停止并重新审计/发起新 run，不混用旧 prepared |
| committed 后 Dagster metadata/event 失败 | 正式数据保留；重试先物理对账，不能为了补观测重复覆盖 |

同 run 重试复用 checkpoint；另一个 Dagster run 不自动扫描其他 run 的 staging。新 run 用当前批准输入重新计算，若正式目标已与计算结果四列等价，则 `reused` 返回，不覆盖。跨 run 的业务结果幂等不要求 Parquet 二进制相同。

原子 rename 只保证单文件完整出现，**不提供并发 compare-and-swap**。本轮不新增全局锁、concurrency pool 或任意覆盖参数。同日手工重建与日更必须错开；S4 在人工维护窗口验收。目标前态检查是异常提示，不伪称能防住任意并发写入的最后一瞬间；如果实际发现并发需求，停止当前发布，另行设计。

## 6. Dagster 定义、checks、job 和 readiness

### 6.1 定义及无分区语义

新 `defs/assets/stock_suspend_confirmed.py` 只声明 `silver_stock_suspend_confirmed = dg.AssetSpec(...)`，无 `@asset` 计算、无 sensor、无 schedule、无 import-time IO。

最终 Silver 的 `deps` 变为原 Raw 加新固定资产；不向日线/分钟 asset 追加固定资产依赖。固定输入在图上是 external asset，意为由专用本地人工工具发布，**不是远程数据源**。[Dagster 官方外部资产说明](https://docs.dagster.io/guides/build/assets/external-assets)。

此固定资产 `partitions_def=None`，没有 `ready_for_trade_date`、当天 materialization 或每日刷新要求。历史日期列不等于日更资产。日常检查可以重复检查同一个版本，但不能生成新固定文件或新的固定资产 materialization。

### 6.2 两个 blocking checks

新 `defs/checks/stock_suspend_confirmed_checks.py`：

```python
@dg.asset_check(
    asset=dg.AssetKey("silver_stock_suspend_confirmed"),
    name="silver_stock_suspend_confirmed_schema_check",
    blocking=True,
)
# 函数接 AssetCheckExecutionContext + 既有 lake_root/duckdb 资源

@dg.asset_check(
    asset=dg.AssetKey("silver_stock_suspend_confirmed"),
    name="silver_stock_suspend_confirmed_approved_content_check",
    blocking=True,
)
```

check 绑定 `AssetKey`，不是把 `AssetSpec` 直接传给本机 decorator；不声明日期 partitions_def，不访问 `context.partition_key`。`passed=False` 使用 ERROR severity；读取错误须明确失败，不能返回空通过。

schema check 使用 `CheckScope.SCHEMA`；内容 check 使用 `CheckScope.RECONCILIATION`，复用 §4.1。schema 检查失败，内容 check 也不得尝试 cast 后通过。每个 check 最多读取固定文件一次，结果记录批准身份及实际检查范围；成功结果能与该固定资产 materialization 建立关联。

**S1 验证状态：**上述关联要求不变，但不能依赖 `AssetCheckResult` 自动填写原生 target。§15.2 已复现关联为空；§15.3 的显式原生 evaluation 方案已批准，部分 adapter 已写，但实际验收未完成。原三个最终 Silver checks 不作此变更。

两个新 checks 的文件前置检查必须只读：按 §18.4 核验根、目标路径和文件，不调用 `LakeRootResource.ensure_available_for_run()` 或底层健康探针。不修改现行全局健康 helper 或其他资产；Dagster 当前 run 的正常 check 事件仍按 §15.3 产生，不能把“文件只读”理解为取消检查事件。

### 6.3 Silver-only job selection

仅修改 `defs/jobs/suspend_update.py` 的 `silver_suspend_d_update_job` selection：

```python
dg.AssetSelection.assets(silver_stock_suspend_daily) \
    | dg.AssetSelection.checks_for_assets(silver_stock_suspend_daily) \
    | dg.AssetSelection.checks_for_assets(
        dg.AssetKey("silver_stock_suspend_confirmed")
    )
```

目标解析集合：可写资产恰好 `{silver_stock_suspend_daily}`，checks 恰好原 3 个 Silver checks＋新 2 个固定 checks。不能使用 `.upstream()` 拉入 Raw 写入；固定 AssetSpec 没有可执行 writer。

要求执行次序：两个固定检查通过 → 最终 Silver writer → 原三个最终 checks。不能仅画依赖图后假定执行顺序成立；Dagster blocking check 的说明见[官方检查文档](https://docs.dagster.io/guides/test/asset-checks)，本项目还必须通过 §13 D 组隔离集成验证。

本机源码基线为 Dagster 1.13.18，线上当前文档版本可能更高；实际实现以锁定版本为准。隔离验证若发现 non-partitioned checks 与 partitioned job 无法按上式阻断，**先停止 S1 并回修本节和技术方案**，不能移除 checks、假造 partition 或默认退回 sensor-only 门禁。

2026-09-06 已执行该提前门禁：上述 selection、先检查后写入及失败阻断在替身定义中通过；D06 的原生发布记录关联失败。按计划冲突停止要求暂停业务实现，详见 §15；不把“作业成功”当作 D06 或完整 S1 通过。

### 6.4 固定输入 readiness

在 `defs/sensors/readiness.py` 新增专用函数，不改变通用其他资产 readiness 的默认行为：

```python
stock_suspend_confirmed_readiness(
    instance, connection, *, lake_root: Path
) -> ConfirmedReadinessStatus
```

返回字段：ready、reason_code、中文 reason、version、physical_logical_sha256、materialization_storage_id、两项 check 的最简结果。内部可以组合现有 `AssetReadinessStatus`，但无需修改其所有消费者或增加全局 freshness 开关。

每次调用：

1. 校验当前固定文件一次，不信历史绿灯；失败直接返回，不查历史补救。
2. `instance.fetch_materializations(dg.AssetRecordsFilter(asset_key=...), limit=1)`，只允许无 partition 的新固定资产记录；metadata 版本、logical_sha256、正式 URI 必须与当前合同一致。
3. 两个 `AssetCheckKey` 各调用一次 `get_asset_check_execution_history(check_key, limit=1)`。不套用通用 5,000 条历史窗口，不过滤掉最新失败/进行中记录来寻找老绿灯。
4. 最新记录必须 `SUCCEEDED`、evaluation.passed、blocking 为真，evaluation.partition 为 None，target_materialization_data.storage_id 等于第 2 步记录；检查 metadata 的 version/hash 与批准版本一致。任一未满足即阻断。
5. 不比较 materialization 是否今天发生，不读旧湖、Prod 或 Ops snapshot。

调用上界：有候选的一次 tick ≤1 次固定文件校验＋1 次 materialization 查询＋2 次 check 查询。check 正在运行/无结果时本 tick 保守跳过；失败后由人工检查或 Silver job 显式验收恢复，不自动写事件把状态刷绿。

### 6.5 sensor 插入位置与独立执行保护

保留原 `registered_keys → gap_status → materialized_keys → pending_keys → candidate_keys[:2]` 流程。在非空 candidate 确定后，日期循环之前调用固定 readiness 一次。

- 无候选：不增加固定事实 IO/event 查询，原“已生成完成”输出不变。
- 固定输入不 ready：此次不发 RunRequest；cursor details 只加一份 `stock_suspend_confirmed` 摘要，保留原连续性字段；不把所有日期或 4,022 行塞进去。
- ready：继续原候选日期循环、Raw readiness、run key、窗口、tag 和每 tick 上限；不跳过前两个被阻断日期而擅自扩大窗口。
- 手工选 asset 绕过 sensor/check selection：§5 writer 仍验证固定文件 schema/批准内容，不能误写；纯 SQL helper 不是正式写入口。

事件是调度可观测门禁，不是生成四列数据必需的额外事实源。直接 writer 的正确性不依赖 instance；不得为统一 sensor 而让每批 SQL 对账读一次事件库。

## 7. Metadata 和配置项审计

### 7.1 新身份字段与既有字段

新 key 在 `defs/run_contracts/metadata.py` 登记；具体值由唯一合同模块或本次物理检查生成，禁止各处写常量：

| metadata key | 值来源 / 消费者 |
| --- | --- |
| `goldenshare/confirmed_fact_version` | 合同版本；固定发布、两 checks、Silver materialization、readiness |
| `goldenshare/confirmed_fact_logical_sha256` | 实际校验结果，必须匹配批准值；同上 |
| `goldenshare/confirmed_fact_source_revision` | 已冻结来源提交；固定发布审计，不参与每日额外读 Git |
| `goldenshare/confirmed_fact_source_sha256` | 原 CSV 内容 SHA-256；固定发布审计 |
| `goldenshare/confirmed_fact_calendar_sha256` | S0 展开使用的有序开市日期集合指纹；固定发布审计 |
| `goldenshare/confirmed_fact_operation_id` | 专用人工发布标识；事件与 checkpoint 对账 |
| `goldenshare/confirmed_fact_event_token` | §9 的确定性事件身份；只用于人工登记去重核验 |
| `goldenshare/confirmed_fact_stats` | §4.3 的精确分类统计；最终 Silver metadata |

复用现有 `dagster/uri`、`dagster/row_count`、`dagster/column_schema`、`goldenshare/observed_columns`、`goldenshare/failure_samples`、summary/next_action/diagnostic_ref。check 不使用 materialization helper 冒充成功资产事件。

删除新运行输出中的旧 `full_day_suspend_patch_*`、`full_day_suspend_raw_override_*` 版本/来源/样本字段及其生成函数，统一为上述身份和分类统计；原 `suspend_timing_correction_*` 保留。只读旧历史事件时允许看到旧字段，不批量改写历史 metadata，也不保留新旧双写。

当前引用搜索未发现独立业务消费者依赖旧 patch metadata；实施时全仓复核这些 key 和日志读取方。若发现实际消费者，补入逐文件矩阵后同轮迁移，不能以“只是 metadata”忽略合同变更。

### 7.2 配置清单

| 项目 | 来源 / 持久位置 | 默认 / 作用域 / 生效 | 运维可见性与测试 |
| --- | --- | --- | --- |
| Lake 根 | 现有 `LakeRootResource` 与 `paths.py` | 既有正式根；本轮不改来源或 env | 资产 URI、路径反例测试 |
| staging 根 | `paths.py::DEFAULT_LAKE_STAGING_ROOT` | `/Volumes/datasource/data_lake_staging`；无本专项可调 env | CLI 展示唯一目录，跨根拒绝 |
| 固定版本/hash/schema | 唯一合同模块＋现有 schema registry | 代码发布生效，非运营输入 | definition/check metadata；错误版本拒绝 |
| DuckDB | 现有统一连接配置 | 原默认 16GB/4 threads 等不变，不新增设置 | 分阶段耗时/文件数，测试拦截裸连接 |
| CLI 操作标识/确认项 | 单次参数；plan/checkpoint 在专项 staging | 无配置中心、无默认写入；仅本次操作 | §8 参数测试和事件隔离 |

本轮无新 env、Settings、数据库配置表、前端常量或自动更新策略。version/hash 是数据合同，不是可调性能开关。

## 8. 人工工具、一次性准备和文件发布

### 8.1 长期入口与一次性来源转换的分工

新文件位于现有 `defs/bootstrap/`，不是不存在的 `orchestrator/cli/`，也不塞入 `stk_mins` CLI：

- `stock_suspend_confirmed.py`：纯计划/审计、候选核验、逐文件发布、事件对账函数。
- `stock_suspend_confirmed_cli.py`：argparse、参数与权限边界、统一连接和实例取得、结果输出。无参数只显示帮助，不写任何东西。

一次性转换使用获准的临时审计脚本：从**固定 Git/CSV 来源**和正式 SSE 开市日展开。该脚本人工执行、接受审查，不注册 Definitions，不成为长期日常依赖；长期 CLI **没有 CSV 参数、Git checkout、规则更新或隐式转换功能**。

候选目录固定结构（均为目标设计，尚未创建）：

```text
data_lake_staging/stock_suspend_confirmed/run_id=<operation_id>/
  candidate/part-000.parquet
  plan.json
  comparison.json
  file-checkpoint.json
  events-checkpoint.json
```

`plan.json` 一经审定不原地修订；含 schema_version、operation_id、代码 revision、来源 CSV commit/blob/hash、两个覆盖键、日历有效日期集合/hash、候选逻辑/物理 hash、预期计数、唯一正式目标、按日期冻结的 Raw/Silver 路径及指纹、S2 日期/批次上界、批准的本地 instance 身份。instance 身份只记规范化 home 路径与非敏感存储标识，不保存密码、连接串或环境变量全集；S0 从当前正式部署核实，本文不猜路径。不复制正式 Raw/Silver 内容。

plan 的 hash 为其实际 UTF-8 文件 bytes SHA-256，文件不包含自身 hash；外部批准参数钉住该 hash。`comparison.json` 引用 plan hash、逐批计数、输入身份复核、双向差异数、最多 20 条差异样本和耗时。不存在“plan 包含 report hash，report 又包含 plan hash”的循环身份。

### 8.2 CLI 命令与参数合同

以下命令均**尚不可执行**；以后入口为 `python -m orchestrator.defs.bootstrap.stock_suspend_confirmed_cli`。

| 子命令 | 必填参数 | 可选参数 / 缺省行为 | 可变更的内容 |
| --- | --- | --- | --- |
| `inspect` | `--operation-id` | 无；展示计划、候选/目标身份、差异和下一步 | 无，stdout JSON |
| `compare` | `--operation-id`、`--expected-plan-sha256` | `--save-report`；默认只输出结果，不落报告 | 仅带 save 且获准时写本 operation 的 `comparison.json` |
| `publish-file` | `--operation-id`、`--expected-plan-sha256`、`--expected-comparison-sha256` | `--confirm-file-publish`；缺失时只展示精确写入计划 | 带确认且获准：唯一固定文件＋file checkpoint；不连 instance |
| `audit-events` | `--operation-id` | 无；只读当前文件与固定资产事件 | 无，stdout JSON |
| `register-events` | `--operation-id`、`--expected-plan-sha256` | `--confirm-event-publish`；缺失时只列待登记事件 | 带确认且获准：§9 最多三个登记动作＋event checkpoint；绝不写 Lake |

read-only 命令不得顺便 mkdir、写 cursor/checkpoint、记录 asset observation 或刷新 catalog。`compare --save-report` 是明确的 staging 写入，若已存在不同报告则拒绝，先展示差异，不自动覆盖。

确认参数只是防误触，不等于用户授权已存在；执行前仍需用户批准对应的文件/事件及 staging 记录写入。没有 `--force`、`--overwrite`、`--skip-checks`、日期筛选缩小验收、任意候选/输出路径、合并模式或 SQL 参数。

退出码：0=审计/计划成功或执行完成/等价复用；2=参数/路径不合法；3=校验或全范围对账不通过；4=输入/目标冲突或漂移；5=数据已发布但观测或 checkpoint 未完整；6=IO/instance 失败，无法确认结果。输出必须带 `mode=readonly|apply` 和 `applied`，dry-run 返回 0 不能误解为已发布。

### 8.3 内部函数边界

```python
inspect_confirmed_publication(connection, *, paths) -> PublicationInspection
compare_confirmed_migration(connection, *, plan) -> MigrationComparison
publish_confirmed_file(connection, *, plan, comparison) -> FilePublishResult
audit_confirmed_events(instance, connection, *, plan) -> EventAudit
register_confirmed_events(instance, connection, *, plan, audit) -> EventPublishResult
```

`paths/plan` 是验证后的专用结构，不接受任意字典透传目标；CLI 在进入 mutator 前完成确认参数校验。bootstrap 模块不能 import asset 函数执行真实任务；SQL/validator 与每日路径共用。`publish_confirmed_file` 不接收 instance，`register_confirmed_events` 不接收数据 writer；通过签名和禁止调用测试固定这两条边界。

### 8.4 S0 准备与 S2 对账算法

1. 核验 CSV SHA-256 仍为技术方案 §3 指定值，并核验两个覆盖键的源码身份；变化即停，不重新猜范围。
2. 将 31 范围临时读为关系，与锁定 `exchange='SSE' AND is_open=true` 的正式日历日期关系连接，生成五列事实；保留来源审计，拒绝重叠导致重复键，不用 `DISTINCT` 隐去来源错误。
3. S0 确认 4,022/29/1,857 和两模式数量，按 §3.3 实算批准逻辑 hash；S2 获准写 staging 后才冻结候选及 plan。S0 已完成前半步，未创建候选或发布 plan；实际 hash 不由本文样例推算。
4. S0 冻结两个停牌目录的**具体日期文件集合**，拒绝缺失配对文件和非预期路径；对集合之外的目录不递归扫描。日常新增日期不默默扩大本次审计。
5. 比较全部已有日期，包含所有 1,857 受影响日期和其余已存在日期。按年拆分且每批最多 366 日期；每批明确 Raw/Silver 文件列表，`hive_partitioning=false`，固定事实一次入 TEMP TABLE。
6. 每批规范化 Raw，先冲突查询，再新关系生成；与当前 Silver 原四列执行双向 `EXCEPT ALL`，分别统计新增、缺失、重复差异。不得只对总行数，也不能按代码去重再比。
7. 批前/批后核对输入文件身份与冻结指纹。Raw 批读验证内部日期与文件的日期归属一致，防止跨分区错放而在全局比较中抵消。
8. 任意差异或输入漂移，输出精确日期和最多 20 条样本，停止发布；不自动修 Raw/最终 Silver、不更改批准 hash。已经正确的历史 Silver 不批量重写。

S0 已核验当前两个停牌目录的 3,083 个日期全部属于正式 SSE 开市日，不存在非开市日分区。后续范围刷新仍须保留该检查：若发现原 CSV 在非交易日文件也实际影响输出，则明确列出并停止，不自动加入/忽略它。31 个区间的旧逻辑按日期范围判断，新固定集按开市日展开；新 helper 与旧输出的全范围等价仍须在 S2 按上述第 5–8 步证明，不能由 S0 逐键结果替代。

### 8.5 固定文件发布与重试

文件发布只允许一名人工发布者，在维护窗口操作。先复核 plan/report hash、所有批准比较结果、固定候选真实身份和目标，禁止用几天的抽样报告冒充全范围对账。

| 目标与候选状态 | `publish-file` 结果 |
| --- | --- |
| 目标缺失，候选及比较报告正确 | 同 FS 完整校验、fsync、prepared checkpoint、`os.replace`、读回、committed checkpoint |
| 目标存在且 schema＋逻辑内容等价 | `reused`；不再移动候选或重写目标，不强求相同 Parquet bytes |
| 目标存在但错误、损坏、不等价 | 停止；不能覆盖、删除或“升级”内容 |
| 目标正确，candidate 已被提升、checkpoint 丢失 | 以批准合同/plan及实际目标确认完成，补记录；不是缺候选失败重写 |
| 目标缺失，候选丢失/错误 | 保留现场，人工处理 |
| checkpoint 写成功但 replace 失败 | 原目标未变；下次重新校验后继续同一批准单文件动作 |
| replace 成功但读回或 checkpoint 失败 | 不删除目标，不自动重试 replace；报告不确定并只读对账 |

不存在“事务失败便自动恢复旧文件”的分支。固定文件 v1 不提供不同内容更新能力；未来版本变更须单独审计，不预建版本后台。源事实只靠 hash 不能还原：需要人工从固定 Git 证据与被记录的日历集合重建候选，再匹配批准 hash，无法复现就停止。

## 9. 事件登记：身份、次数和不确定结果

### 9.1 事件计划

只有文件已通过正式路径读回才能制定事件写计划。**一个固定版本的首次人工登记**最多如下 3 条；该上限不限制以后每个 Silver job 正常产生的两个 check evaluations。

| 顺序 | 事件 | 必填身份 |
| --- | --- | --- |
| E1 | 无 partition 的 `AssetMaterialization` | asset key、正式 URI、实际行数/列、version/hash、来源审计、operation_id、event_token |
| E2 | schema `AssetCheckEvaluation` | asset/check key、passed、blocking、ERROR severity、partition=None、指向 E1 的 target materialization |
| E3 | approved content `AssetCheckEvaluation` | 同上；本次完整内容 validator 实际通过 |

专用 helper 使用当前实例已支持的 `instance.report_runless_asset_event(...)`，不调用 materialize、不补动态分区、不写其他资产事件、不使用直接 SQL 插入事件表。当前 1.13.18 本机源码已核对该方法接受 `AssetCheckEvaluation`。事件 CLI 取得 instance 前后均核验其配置身份与 plan 批准的本地 instance 一致；缺配置、错 home 或身份不符即失败，不默认创建临时 instance 冒充正式登记、不接受任意远程地址。

`AssetCheckEvaluationTargetMaterializationData` 的 `storage_id/run_id/timestamp` 必须来自 E1 的**真实读回记录**，runless run_id 也读实际值；不能填人工 operation_id 或伪造 run_id。该类型位于锁定版本内部模块；§15.3 已批准使用范围为 bootstrap 事件 adapter 和两个固定 check 的事件 adapter。不得扩散到纯 validator、SQL、writer 或其他资产 checks；必须用隔离事件 round-trip 测试防 API 漂移。

### 9.2 去重与中断协议

确定性 token：`stock_suspend_confirmed:<version>:<logical_sha256>:<event_kind>`，kind 为 materialization 或精确 check 名。token 的依据是同一批准内容，不因更换 operation_id 就产生第二套事件。

单发布者前提下逐条操作：

1. `audit-events` 先查固定资产最新 materialization、两个 check 各最新记录。不存在任何记录可列计划；有完整正确记录则所有动作 `reuse`。日常 job 产生的有效 check 也可证明现有检查完整，不因它没有人工 event_token 就重复补一条人工绿灯。
2. 每写一条之前先把该 token 标记 `pending` 写入独立 events checkpoint，保存已知 event/storage identity；checkpoint 未持久成功不发 event。
3. 调用一次事件写 API 后读回真实记录，核对 asset/check/version/hash/token/target identity，通过才标记 `confirmed` 并进入下一条。
4. 进程在 API 调用后退出：下次先读回，查到同 token 则补 checkpoint，**不重发**。
5. API 超时、读回失败或 pending 但查不到事件：标记 `uncertain`，停止自动续写；不能认定“没成功”而盲重试。恢复前须人工核验是否真实未入库，排除延迟/并发后才能明确批准重试该条。
6. 无 pending 且确认该条从未尝试，才可作为剩余缺项继续。失败/不匹配的已有记录不自动覆盖成绿灯。

事件写 API 没有本专项可依赖的唯一键事务，token 也不是数据库唯一索引。因此本文不承诺跨进程任意重试的 exactly-once；通过人工单 writer、逐条持久化意图、读回与不确定即停，避免无依据重复登记。

日常 readiness 只查各最新 1 条；人工恢复若 checkpoint 的记录已非最新，不能无限翻历史。可按 checkpoint 已知 ID 核对，或在明确审计中每类最多读取 10 条记录；超出/出现不同版本、多个发布者、重复或身份歧义即停止交用户确认，不扩大为全历史清理。不得删除历史 event 让数量“符合”。

文件与事件状态独立：`file_committed=true, events_complete=false` 是合法的未完成发布状态；保留正确数据，sensor 暂不触发新 Silver，后续只处理观测缺项。

## 10. 逐文件处理矩阵

### 10.1 当前文件：改什么、不能改什么

下表路径相对 `lake_console/orchestrator/src/orchestrator/`，每项都在本轮基线中存在。

| 当前文件 | 处理 | 精确改动 / 保留边界 | 回归 |
| --- | --- | --- | --- |
| `defs/assets/suspend_d.py` | 修改 | Silver deps、新 writer、新输入和统计；删除 `_full_day_patch_ctes`、`_full_day_patch_conflict_rows`、`_full_day_patch_metadata`、`_full_day_raw_override_metadata` 和仅 Silver 使用的私有 `.tmp` writer；Raw 函数/decorator 不改 | M、W、D |
| `defs/duckdb_sql.py` | 修改 | 删除两项 full-day import；替换旧 Silver select 签名为 §4 三关系签名，增加冲突/统计 helper；保留 normalized 和时段清洗 | M |
| `defs/corrections/suspend_full_day.py` | 待批准删除 | 代码切换同轮清零所有 import，S5 精确删除，无兼容 wrapper | G |
| `defs/corrections/suspend_full_day_ranges.csv` | 待批准删除 | S0 冻结来源，S3/S4 验收后单独确认；不是先删再补数据 | G |
| `defs/corrections/suspend_timing.py` | 保留 | 14 条独立清洗原样，不删 corrections 目录 | M、G |
| `defs/paths.py` | 修改 | 仅新增 §3.4 三 helper；原 Raw/最终 Silver helper 不改 | C、W |
| `defs/catalog/lake_assets.py` | 修改 | §3.1 enum/model/entry；最终 Silver notes/上游描述校准；不动 Raw 合同、不引入动态 planner | C、D |
| `defs/catalog/name_mapping.py` | 修改 | 只登记新 dataset 中文名 | C |
| `defs/run_contracts/asset_column_schemas.py` | 修改 | 新五列常量；现有 Raw/Silver 四列不变 | C |
| `defs/run_contracts/metadata.py` | 修改 | 登记 §7 key，复用既有 helper；不修改 `ColumnContract` | C、G |
| `defs/checks/suspend_d_checks.py` | 保留/测试适配 | 原 2 Raw＋3 Silver checks 名称/语义不变，不换名字清历史 | D、G |
| `defs/jobs/suspend_update.py` | 修改 | 仅 Silver selection 增加固定两 checks；Raw job 不改 | D |
| `defs/sensors/suspend_d_sensor.py` | 修改 | candidate 非空后共享 readiness 一次；原 Raw sensor、窗口、2 个上限、run key 不变 | R |
| `defs/sensors/readiness.py` | 修改 | 新无分区固定输入专用 adapter；不改变其他 spec 的 freshness/历史扫描语义 | R、G |
| `defs/assets/stock_daily.py` | 保留 | 现有停牌依赖/readiness；日线生成 SQL 并非直接按 suspend 过滤，不虚构改 SQL 项 | G |
| `defs/checks/stock_daily_checks.py` | 保留 | 预期可交易集合减去最终 Silver 的 `S+NULL`；盘中诊断不变 | G |
| `defs/sensors/stock_daily_raw_repair.py` | 保留 | 缺口补拉集合继续从最终 Silver 排除全日停牌 | G |
| `defs/assets/stk_mins.py` | 保留 | 身份映射后的全日停牌过滤，五个原生频度和 fallback 不改 | G |
| `defs/checks/stk_mins_checks.py` | 保留 | 最终分钟 Silver 的停牌结构检查不改 | G |
| `defs/asset_guards/stk_mins_lake_readiness.py` | 保留 | 批量只读最终 Silver，不旁读新固定资产 | G |
| `defs/bootstrap/stk_mins_silver_history.py` | 保留 | 原路径/正式分钟 writer 复用、参数不改 | G |
| `defs/bootstrap/stk_mins_silver_replace_from_raw.py` | 保留 | 恢复输入指纹仍跟踪实际消费的最终停牌 Silver，不追加固定源直接依赖 | G |
| `defs/bootstrap/stk_mins_bse_history_recovery.py` | 保留 | 同日 `S+NULL` 和 BSE 1m fallback 语义、CLI 不改 | G |
| `audits/stk_mins_silver_strict_audit.py` | 保留 | 覆盖诊断读全部停/复牌代码，不改成只取全日停牌 | G |
| `defs/checks/stock_partition_checks.py` | 保留 | 原最终 Silver 分区检查；无分区新输入不加入日期检查 | D |
| `defs/bootstrap/historical_materialization_reconciliation.py` | 保留 | 不自动给 1,857 历史日期补新事件、不扩其写入白名单 | G、E |
| `defs/bootstrap/asset_check_event_retention.py` | 保留 | 不清理/重写历史事件，也不顺手纳入新资产清理 | G、E |

禁止把当前“保留/测试适配”读成预先允许修改业务行为；若回归暴露真实消费者改动需求，先补清单和原因。

### 10.2 新增文件

均相对 orchestrator 工程；这是计划新增矩阵，不表示这些文件目前全部不存在。§17.3 记录已写的部分实现；§18.2 单列下一轮安全修正白名单。

| 新增文件 | 必须包含 / 禁止包含 |
| --- | --- |
| `src/orchestrator/defs/assets/stock_suspend_confirmed.py` | 一个 AssetSpec；无 IO、writer、动态读取或自动化 |
| `src/orchestrator/defs/stock_suspend_confirmed_contract.py` | 版本/hash/validator/结果结构；不 import `duckdb_sql.py` 形成环；不藏 CSV |
| `src/orchestrator/defs/checks/stock_suspend_confirmed_checks.py` | 两 check adapter；纯逻辑复用 contract |
| `src/orchestrator/defs/bootstrap/stock_suspend_confirmed.py` | §8/9 专用计划、比较、文件/事件 adapter；无源接口和每日调度 |
| `src/orchestrator/defs/bootstrap/stock_suspend_confirmed_cli.py` | 五个专用子命令、确认/错误码；不接入 stk_mins CLI |
| `tests/test_stock_suspend_confirmed_contracts.py` | C 组；类型、编码、路径、批准内容身份 |
| `tests/test_stock_suspend_confirmed_merge.py` | M/W 组；独立 expected 与每日 writer 故障注入 |
| `tests/test_stock_suspend_confirmed_bootstrap.py` | B/E 组；CLI、文件发布、事件中断 |
| `tests/test_stock_suspend_confirmed_dagster.py` | D 组；自动发现、外部检查与分区 job、真实隔离事件关联 |
| `tests/stock_suspend_confirmed_test_runner.py` | 专项测试进程隔离与两阶段启动；不进入正式 defs、不提供任意测试/命令透传 |
| `tests/stock_suspend_confirmed_test_support.py` | 专项提前加载的测试插件、临时资源工厂、目录/连接断言；只供本专项测试 |
| `tests/test_stock_suspend_confirmed_isolation.py` | I 组；隔离自身正反验收、启动失败不进入业务测试 |

### 10.3 现有测试修改与保留

`tests/` 以下默认指 orchestrator tests：

| 文件 | 明确动作 |
| --- | --- |
| `test_asset_governance_contracts.py` | 对执行定义与外部 spec 分类型收集，合并为全资产 specs；定义对象 map 可只保留 executable，但 catalog 数量/键/schema/check 对账必须使用全 specs；断言新资产不可执行且无分区；不放进 CONTRACT_ONLY 排除集合 |
| `test_run_contract_static_gates.py` | 新固定读取方白名单、唯一 writer、AssetSpec metadata 注册、无 CSV/旧 import/Git fallback/源请求和正式目录 staging |
| `test_suspend_d_sensor.py` | 补固定 readiness fixture、计数和失败用例；原 Raw sensor/run key/date window assertions 保留 |
| `test_suspend_d_checks.py` | 保留原 5 check 名称、合法空分区/错日期/重复；新增来源变更不影响这些 check 的例子 |
| 根 `tests/architecture/test_lake_console_retirement_guardrails.py` | S5 才替换 CSV 存在锚点为新正式源码及禁止旧读取检查；其余 Ops/Local Lake/ClickHouse 保护不变，禁止读移动盘作测试 |

必跑现有消费者回归，路径已核对：

```text
test_stock_daily_raw_checks.py
test_stock_daily_raw_repair.py
test_stock_daily_freshness_guard.py
test_stk_mins_silver_m5b_contracts.py
test_stk_mins_silver_m5e_job_contracts.py
test_stk_mins_lake_readiness.py
test_stk_mins_silver_m6_history.py
test_stk_mins_silver_replace_from_raw.py
test_stk_mins_bse_history_recovery.py
test_stk_mins_silver_strict_audit.py
test_stock_mins_daily_continuity_sensors.py
test_stk_mins_silver_m6g_sensor_contracts.py
test_asset_check_incremental_governance.py
```

除必要 fixture 外不改这些文件的业务 expected 来迎合新实现。CLI 不变不仅是 `--help` 不变，还包括既有参数拒绝、计划选择、文件选择、退出码和恢复行为测试不退化。

## 11. 实施、发布与删除顺序

沿用技术方案 S0–S5，不新增一套编号；每阶段独立验收，不自动跨过高风险步骤。

| 阶段 / 风险 | 明确产出与顺序 | 进入下一步的条件 |
| --- | --- | --- |
| S0 / 低，已完成 | LLD 已认可；来源/日历/文件集合已刷新；批准 hash 已实算；隔离验证设计已固定 | 来源一致，见 S0 清单；后续已取得 S1 开发及本地维护安排授权 |
| S1 / 中，安全修正待 review | §15.3 框架方案已确认；部分实现因 §17 事故停止。先按 §18 完成文档 review、隔离独立验收和两个新 checks 的 D06/D07 验收，再继续原 contract/merge/writer/readiness/CLI 工作 | I 组必须先通过，真实 adapter 不能以替身实验代替；完整 D/W/B/E/R 和等价测试仍须通过。安全修正通过不等于 S1 完成；不得自动重载 code location |
| S2 / 中 | 获准准备 staging 后，冻结候选与 plan，全既有日期分批比较 | report 差异为零、输入身份未漂移、性能/文件范围可核验 |
| S3 / 高 | 先单固定文件发布，再另行批准事件登记；准备代码不启动正式新链 | 文件正确＋E1/E2/E3 完整匹配；正式 Raw 0 写，历史最终 Silver 0 批量写 |
| S4 / 高 | 精确维护窗口、确认旧 writer 已结束、切换代码；运行少量 Silver-only 验收；恢复指定触发器并观察正常日更 | 两覆盖日期＋一补缺日期＋一无修正日期等价；5 checks 通过；下一次正常链通过 |
| S5 / 中 | 最后确认删除两个旧文件，更新护栏与当前引用文档 | 无旧 import/旁路/双读；保留 timing.py；TODO 方可关闭 |

S0 时正式 code location 通过 editable 安装直接加载当前工作区，Raw/Silver 停牌 sensor 均为 RUNNING。S1 源代码修改可能影响新的 run 导入，即便尚未重载 code server，也不能假设“写了工作区代码就绝无运行影响”。用户已批准仅暂停停牌 Silver sensor，并在维护期间不手工启动其 job；2026-09-06 17:47:27 已执行并读回确认。Raw 和其他 86 个 sensor 状态不变；S1 不自行恢复 Silver 入口，§15 记录实际状态。本轮不自建分支/worktree 绕过部署边界。

S3 事件可由专用工具对指定 key 登记，不要求为了发事件提前启动新的每日 Silver 链；S4 再加载包含新 definitions 的正式版本并核验可观测性。若实际 code location 部署必须提前纳管 AssetSpec，先明确该步骤只登记定义、保持旧 writer 运行边界，不允许暗中提前切换。

S4 暂停清单默认只针对当前停牌 Silver 触发入口 `silver_suspend_d_update_job_sensor`；若正在写验收日 Raw，则等它结束或另行批准停止该写任务。下游不用统一停机：历史结果未变，新结果不 ready 时沿用其既有门禁。恢复清单与先前状态一致，不把原本停用的其他 sensor 启用。

S4 中固定输入依赖与旧 import 清理是**同一交付版本**，没有运行时兼容双读。S5 前两个旧源文件可作为不被 import 的待删除文件存在，仍不能由新代码回退读取。

任何失败都保留现有正式文件和现场，不自动回退 CSV、不删除正确结果重跑；不能宣称“无备份仍能随时恢复任意旧版本”。异常的处理是停止扩大影响、物理对账、明确修正后再批准。

## 12. 性能、资源和实际验收记录

| 项目 | 上界 / 实现 |
| --- | --- |
| 新源调用 | Tushare 0、Prod 0、ClickHouse 0；不改 Raw 参数，因此本轮不做新的源接口探测 |
| 固定数据计算 | 4,022 行一个关系；DuckDB 集合式编码/合并；无 Python 全量业务逐行处理 |
| 日常新增固定读取 | writer 1 次、每个 check 各 1 次、非空候选 sensor 1 次/tick；无跨进程缓存 |
| 日常固定事件查询 | sensor 每 tick 最多 1 mat＋2 check；latest limit=1；无候选为 0。已确认 §15.3：每个固定 check 显式查 mat 至多 1 次，即每 job 至多 2 次；不在 writer/SQL 增加事件查询 |
| 全范围比较 | 前序基线两层各 3,083 文件，实施用 S0 精确清单；按年且≤366 日期/批；每批一次固定加载，显式 Raw/Silver 文件列表 |
| 人工固定发布 | 最多 1 正式新文件；初次事件最多 3 条；无历史日期事件补录 |
| S4 验收 | 4 个不同类型日期，实际精确日期在 S2 后审定；每日期单独候选/检查；不重抓 Raw |
| 内存/空间 | 复用现有 DuckDB 设置；固定输入增量预期远低于 512MiB、无 spill；固定文件估算<1MiB，准备报告预算100MiB；超额记录实测并停止扩大范围 |
| 日常开销 | 新增计算/读取目标约1秒，须分别计 writer、checks、sensor；不是本轮实测结论 |
| 全范围耗时 | 分钟级目标；超过5分钟输出慢阶段/已完成批次，人工复核，不用严苛倍率跳过正确性 |

writer 提升前复核使用已记录输入身份；首次加载/长批核验需要真实内容指纹，不把 mtime 当内容唯一证明。额外只读字节核验单独计入 IO 统计，不隐瞒在“文件一次读取”的 Parquet 解码预算中。

进度以每批实际完成量、日期批、文件数、差异数、耗时输出。发布只有一个文件，不建 ETA/进度数据库；长批比较至少每完成一批报告，单批异常慢时报告阶段而不虚构完成量。

硬拒绝项是多源请求、超出批准文件清单、错误根、无界循环、错误写入/事件、数据不等价。轻微耗时偏慢不改变业务标准，也不顺手调全局资源。

S0 实测已落清单：主审计 3,024 ms，15 次有界 DuckDB 调用、13 个年度批次，两层各 3,083 文件；真实逻辑 hash 见 §3.3。配置 512 MB/2 threads、禁止 spill，未测峰值 RSS。S1/S2 的候选物理 hash、新 helper 全范围差异、writer/check/sensor 开销、测试及内存证据仍待执行；不得把 S0 耗时或前序约0.4秒的审计当新链路性能。

## 13. 测试和验收用例矩阵

### C：固定合同

| 编号 | 正/反向用例 | 必须结果 |
| --- | --- | --- |
| C01 | 正确五列、批准集合 | schema/content通过，真实摘要匹配 |
| C02 | 少/多列、错序、DATE改VARCHAR、timing全NULL但物理类型错 | 失败，不 cast掩盖 |
| C03 | 空文件、缺文件、损坏、NULL键、重复键、未知模式、空串时段 | 失败，最多20样本，无写入 |
| C04 | 同行换序/换压缩、改单个值/模式 | 前者逻辑hash不变，后者失败；金样本bytes/hash固定 |
| C05 | 4,022计数相同但换一个键，或覆盖键扩大 | 拒绝，不能靠计数自证 |
| C06 | 候选/目标symlink、`..`、跨设备、挂载缺失、错误根 | 拒绝，不能在系统盘建目录 |
| C07 | 修改文件但沿用旧 metadata/hash | 实际内容检验失败；无进程cache续用 |

### M：独立合并金样本

| 编号 | 用例 | 必须结果 |
| --- | --- | --- |
| M01 | add_missing无Raw；已有一条正确行 | 分别补1/补0；四列字面expected |
| M02 | 两条正确全日重复 | 不补、不去重；原最终key check仍失败 |
| M03 | R、盘中停牌、正确全日＋冲突并存 | 冲突先失败、目标不变 |
| M04 | 两覆盖键分别0/1/多Raw，包括原3行样本 | 每键恰好一条确认S+NULL；其他键不动 |
| M05 | 非修正日、合法空Raw/空最终输出、正常盘中/复牌 | 维持原结果，不凭NULL时段判所有记录为全日停牌 |
| M06 | 原14条时段修正及人工构造的修正/确认重叠样本 | 14条效果保留，冲突阶段与原顺序一致 |
| M07 | 临时Raw重抓替换、临时Silver原先不存在 | 仅Raw＋固定输入可重建；不能读取旧Silver或CSV |
| M08 | 日常单日期与同输入多日期批SQL | 同日期四列一致；非法跨日期文件明确报错 |
| M09 | 21条以上冲突、覆盖键数≠Raw行数 | 总计数准确，样本≤20，各统计不混用 |

expected 必须是手写字面行，不调用被测 helper 生成 expected。C01 的生产批准内容验证与 M 组小型关系样本分开：M 组直接测试纯关系算法，不能为方便小样本给正式 validator 增加“跳过批准hash”参数。

### W/B/E：文件、CLI 和事件故障注入

| 编号 | 用例 | 必须结果 |
| --- | --- | --- |
| W01 | COPY失败、候选不完整、EXCEPT ALL非零 | 原正式Silver字节不变，无replace |
| W02 | prepared后replace前退出、replace后checkpoint前退出 | 按§5恢复；已提升不重复覆盖 |
| W03 | 输入/目标漂移、candidate丢失、跨run等价 | 漂移停止；等价reuse；不删现场 |
| B01 | 五命令参数矩阵；无参数/无确认/错误hash | 不写文件/event、不构造无关instance，不改stk_mins CLI |
| B02 | inspect/compare只读、save-report显式写入 | 默认目录/文件mtime及instance均不变；写报告只在批准专项目录 |
| B03 | 正式固定目标absent/equal/different/broken | publish/reuse/refuse/refuse，绝不自动覆盖不同内容 |
| B04 | 全日期/年度边界、漏配对日期、1个差异或输入变化 | 批次有界、范围不可缩小跳过、差异阻止发布 |
| B05 | 文件发布API参数签名与调用spy | Raw/Prod/其他Silver/event调用数为0 |
| E01 | 临时instance E1→E2→E3 round-trip | 真实storage_id/run_id/timestamp关联，partition=None、blocking/通过/metadata正确 |
| E02 | 全成功后重复运行、仅E1成功、仅E1/E2成功 | 不重复已确认event，只续从未尝试缺项；文件不重写 |
| E03 | event写入后超时/进程退出、pending且查不到 | 查到则补checkpoint；不明则uncertain停止，不能盲重发 |
| E04 | 已有不同版本/失败/错误target/并发记录、超过有界窗口、instance身份不符 | 停止人工核验，不翻全部历史、不删event、不写错实例 |
| E05 | event失败而文件正确 | 文件保留，返回观测未完成状态，sensor暂不触发 |

### D/R：Dagster 与 sensor 集成

| 编号 | 用例 | 必须结果 |
| --- | --- | --- |
| D01 | 实际模块发现加载 AssetSpec＋checks | 新key只有一个，catalog/schema/path/check全纳管；不可执行、无分区 |
| D02 | 临时Definitions解析Silver-only job | asset写集合恰好1、check集合5；不选择Raw writer/固定writer |
| D03 | 合格输入＋明确partition_key执行job | 固定checks先通过，writer再执行，最终checks通过；固定check无partition、最终check有该日期 |
| D04 | 固定任一check失败/抛错 | writer调用计数0，临时正式目标不变 |
| D05 | 绕sensor、只选Silver asset | 固定内容错仍拒绝；不依赖日常恰好经过sensor |
| D06 | runless首次checks后再跑日常job checks | evaluation/storage记录仍正确关联固定materialization；readiness可读，不因每日job分区污染固定check |
| D07（§15.3 已确认） | 固定 check 显式 evaluation：无mat/有日期的mat/错误URI、version或hash；文件schema正确但内容错误；事件存储失败 | 无效发布记录或存储失败时 writer不执行；有效记录时 schema/content 各自报告真实结果、实际hash不伪造；全部事件属于当前run，无日常runless调用或新增固定mat；逐类失败证据见 §18.5 |
| R01 | 无候选/候选2日期 | 固定调用分别0/1；两日期不重复查固定文件/事件 |
| R02 | 文件缺/错、无mat、错version/hash、check失败/进行中/缺/旧target | 不发run，无历史绿灯回退 |
| R03 | 很早的正确固定materialization＋当前正确文件/checks | ready；不得加当天freshness要求 |
| R04 | 固定ready、原Raw其中一天不ready | 原日期窗口/阻断/最多2/run key/cursor语义不变 |

D 组必须使用显式临时 instance、临时 Lake/staging、测试动态分区；不读取用户正式 `DAGSTER_HOME`、不加载真实网络资源、不跑真实Tushare。用解析后的 asset job 执行，不能用 `dagster.materialize(..., asset_checks=...)` 代替集成验收。

§18 的 I 组是恢复本专项测试前的独立前置门禁；必须先通过，再收集/运行 C、D 等业务测试。不能先运行实际 checks 再以“未发现文件损坏”倒推隔离通过；也不能仅 monkeypatch Python 文件函数就声称 DuckDB 原生 IO 已被拦截。

### G/P：消费者和范围护栏

- G01：§10.3 既有日线/分钟/BSE/恢复/严格审计/CLI 回归全过；错误结果不能通过修改expected消化。
- G02：Raw函数/schema/API参数/checks、最终四列/path/check/job名字、14时段规则前后冻结一致。
- G03：全仓旧loader/import/VALUES/override规则消费者清零；新固定文件业务读取只在最终停牌生成链，其他读取只允许contract/check/readiness/专用bootstrap。
- G04：旧Console/Kopia/旧湖读取为0；Prod/ClickHouse/Ops snapshot/Local Lake客户端源码无修改；根清退护栏其余保护保持。
- G05：模块import没有读盘/连接/写事件；无新sensor/schedule/自动writer；无CSV/Git兜底；测试不依赖移动盘。
- P01：对read_parquet解码、固定事件查询、SQL批次数做调用计数，断言§12上界；额外哈希字节IO单列。
- P02：S2真实只读报告记录全范围差异为0和输入身份；性能实测分段，不用单元计时替代。

## 14. 文档同步与本轮交付状态

本轮新增本文，并回写技术方案中的 LLD 入口、细化后的执行边界和下一步；`docs/README.md` 与清退 LLD TODO 添加导航。没有提前修改“当前架构”图或把 CSV 标记成已清退。

实施同轮文档矩阵：

| 文档 | 实施时修改点 |
| --- | --- |
| [技术方案](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-suspend-confirmed-facts-technical-plan-v1.md) / 本文 | 分阶段写实际hash、测试/物理/事件证据及未完成项；设计变化先回主案 |
| [资产目录](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-new-lake-asset-catalog-design.md) | 新固定asset/model/来源/唯一writer，最终Silver两个输入 |
| [资产/Job拓扑](/Users/congming/github/goldenshare/lake_console/docs/architecture/dagster-asset-job-topology.html) | 外部无分区输入、Silver-only选中checks，不新增Raw联动写 |
| [readiness登记](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-silver-raw-readiness-registry.html) | 新固定身份门禁、无每日freshness、每tick一次 |
| [run contract治理](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-run-contract-governance.html) | 新metadata keys、旧patch字段退出、可解释错误与样本上限 |
| `lake_console/AGENTS.md`、`lake_console/orchestrator/AGENTS.md` | S5核对当前CSV保护说明；只更新实际存在且已获准替换的条目，不扩大改规则 |
| 原清退方案/LLD/M0 TODO记录与主索引 | 保留历史审计语境；完整验收后再关闭TODO，不重写清退历史 |

根子系统依赖矩阵不变。CodeGraph 架构快照是否更新，以实际实施时正式依赖/入口变化为准，本轮不提前声称已发生。

S0 已完成，没有新增业务数据范围；§15.3 框架窄修正已确认，当前停止原因是 §17 的执行越界，不是框架方案仍待拍板。当前进展及剩余项：

1. S0：真实展开逻辑 hash、源/日历/Raw/Silver 清单身份和当前部署边界均已刷新，见 S0 清单。
2. S1：已有部分固定合同/AssetSpec/check/catalog 代码；首轮 adapter 测试越界，未验收。当前只补齐 §18 供 review；安全修正和任何后续测试均未在本轮执行。§15 的 5 项机制实验不等于实际 adapter 验收。
3. S2–S5：staging 准备、文件发布、事件登记、本地切换、精确删除均未执行；不能合并成一次默许授权。

S0 增加了真实物理只读核验和现有运行状态核验，但没有执行新代码测试或正式迁移验收。后续执行记录须在对应阶段补齐，缺一项不能标记本专项完成。

2026-09-06 首轮文档验收记录（历史）：`scripts/check_docs_integrity.py` 通过；本技术方案及 LLD 合计 23 个本地链接/显式锚点有效；本 LLD §10.1 的 27 个现有源码路径及 §10.3 的 13 个消费者回归测试路径均存在；代码围栏、已跟踪文档及两份新增文档的空白检查通过。该文档轮未执行任何业务测试或正式 Dagster 操作；之后 S1 的唯一正式状态修改及隔离测试见下节。

<a id="s1-dagster-gate"></a>

## 15. 2026-09-06 S1 维护与隔离门禁记录

### 15.1 已授权并执行的维护动作

用户确认按维护计划推进。2026-09-06 **17:47:27（北京时间）**，核实当前 code location 正确且已加载后，按唯一 ID 停止 `silver_suspend_d_update_job_sensor` 并读回：

| 核验项 | 结果 |
| --- | --- |
| 目标 sensor | RUNNING → STOPPED |
| 全部 sensor 前后比较 | 共 88 项，仅上述一项变化；Raw 仍 RUNNING，其他 86 项不变 |
| 暂停前后活动 run 查询 | 均为空；包括排队、未启动、启动中、运行中、取消中 |
| 正式修改范围 | 只有上述 sensor 状态；未启动 job、写入 materialization/check 事件或重载服务 |
| 数据与代码 | 未修改业务代码；未写正式 Lake/staging，未删 CSV 或其他文件，未提交/推送 |
| 恢复条件 | S1 结束不自行恢复；等 S3/S4 或另行明确批准。暂停不是旧入口已清退，维护未结束前该自动入口不会发新任务 |

证据位于本机临时审计目录 `/private/tmp/stock-suspend-s1-20260906.ujj5Ni` 的 `maintenance-before.json`、`maintenance-stop-attempt.json`、`maintenance-stop-response.json`、`maintenance-after.json`。这是一轮点时核验，不声称其他链路此后永远不会启动任务。

### 15.2 原模型实测：阻断成立，自动发布关联不成立

使用安装版本 **Dagster 1.13.18**，显式临时 SQLite instance、一个测试日期分区、两个替身固定检查和三个替身最终检查。清除 `DAGSTER_HOME`，禁止隐式正式 instance 和网络访问；不导入业务资源、不读实际 Lake，writer 只改临时哨兵文件。测试中的 runless 事件也仅写入该临时实例。

| 原模型用例 | 数量 | 结果 |
| --- | --- | --- |
| 单 writer／五 checks 选择集合（D02 框架层） | 1 | 通过 |
| 合格输入的检查顺序与分区语义（D03 框架层） | 1 | 通过 |
| 任一固定 check 返回失败／抛异常（D04 框架层） | 4 | 全通过，writer 未调用，哨兵未变 |
| 无日期 job 的固定 checks 关联对照 | 1 | 通过，能关联同一条无分区发布记录 |
| 初始化发布/检查后执行日期 job（D06 框架层） | 1 | **失败**；job 成功、两个 checks 的 evaluation.partition 均为 None，但原生 target 均为 None |

合计 **7 通过、1 失败，3.27 秒**。失败样例中固定发布 `storage_id=1`；两个最新检查执行状态均为 SUCCEEDED，却都缺少 `target_materialization_data`，不是错误关联到了另一个有效发布。按 §6.4 的严格规则推导，下一次有候选日期的 tick 会拒绝就绪。这是新设计尚未实施时发现的问题，**不是现有停牌数据损坏，也不能据此声称当前在线 writer 存在该问题**。

原因已追到当前安装源码：[asset_check_result.py](/Users/congming/github/goldenshare/lake_console/orchestrator/.venv/lib/python3.13/site-packages/dagster/_core/definitions/asset_checks/asset_check_result.py:180)。`_get_target_materialization_data()` 根据 **step 是否有日期分区**选择查找路径，即便 check 本身无分区，也按 job 日期过滤 materialization。固定资产发布无分区，因此查不到；而 evaluation.partition 的生成独立按 check spec 判断，仍为 None。LLD 原先假定“无分区 check 就会自动关联无分区发布”，这个假定不成立。这里不将 SDK 的全部混合分区/阻断机制判为失效，也不假定升级版本即可解决。

### 15.3 已确认窄修正：两个固定检查显式记录真实发布关联

**状态：用户于本节实验报告后明确回复“确认，可以”，已批准作为 S1 正式实施方案；不是已完成代码验收。**保留 §6.4 的真实关联要求，不把 metadata 上写一个 ID 当作原生关联，不回退到历史绿灯。上文标注的“待确认”均为首次实验时状态，本次确认仅解除此窄修正的开发阻断，不授予 S2–S5 权限。

拟修改仅限 `defs/checks/stock_suspend_confirmed_checks.py` 的两个 Dagster adapter：

1. 每个 check 至多一次 `fetch_materializations(..., limit=1)` 读取固定资产最新真实发布记录；不按每日 job 日期查找。记录必须无 partition，URI/version/批准 logical hash 与合同一致。缺失或不符时抛可解释 `Failure`，不编造发布、target 或绿灯；下游 writer 不执行。
2. 纯 validator 仍不读 instance，schema/content 判断不合并。文件检查 metadata 记录**实际** digest，不能用批准常量替代；schema 合格而内容错误时，schema 可通过、内容必须失败。发布记录存在只是检查执行前提，不代替物理校验。
3. 从真实记录取得 `storage_id/run_id/timestamp`，显式 `yield AssetCheckEvaluation(..., partition=None, target_materialization_data=..., blocking=True, severity=ERROR)`，随后 `yield dg.Output(None)` 完成依赖输出。结果仍是**本次 job 的原生检查事件**，失败由 Dagster 阻断，不调用日常 `report_runless_asset_event()` 补录。
4. 不改变两个 check 名称、绑定 AssetKey、无分区合同、一 writer 五 checks 集合或执行顺序；原三个最终 checks 不变。不升级/修改 SDK、不 monkeypatch、不新增分区、额外 job、sensor 或配置。
5. `AssetCheckEvaluation` 及 target 类型在当前安装版本的内部模块，使用仅封装在这两个 checks 的事件 adapter 和原 bootstrap adapter；纯合同/SQL/writer 不引入该依赖。锁定版本并以实际存储读回测试约束；这是本建议需披露的框架 API 风险。
6. 每 job 两次有界 mat 查询取代 SDK 原先的自动查找，不新增扫描历史或逐日回溯。sensor 原有 1 mat＋2 check 预算不变；SQL/writer 不查 instance。文件与事件发布仍只在获准的人工窗口完成。

临时实验 **5 项通过，2.40 秒**：成功 1 项、两个 check 分别返回失败 2 项、分别抛读取异常 2 项。成功路径验证当前 run 下的 evaluation 和存储执行记录都关联真实固定 materialization、固定 partition=None、最终检查属于测试日期、仍仅五 checks、固定 materialization 总数未增加；失败路径 writer 未执行且哨兵未变。安装源码的 [execute_step.py](/Users/congming/github/goldenshare/lake_console/orchestrator/.venv/lib/python3.13/site-packages/dagster/_core/execution/plan/execute_step.py:520) 也确认显式原生 evaluation 仍接受 ERROR blocking 处理。

**尚未验证：**真实模块发现 D01、绕过 sensor 的真实 writer D05、真实固定文件 schema/content、URI/version/hash 错误记录、事件存储故障、readiness R 组、纯合并/CLI/checkpoint、消费者回归及 S2 全范围等价。这 5 项是修正机制的可行性证据，不能标记 D/R 全组或 S1 通过。确认后先落正式 adapter 的 D06/D07 反例及真实 readiness 读回测试，再继续其余 S1；任一不符仍停止。

### 15.4 可复核证据与下一步

所有下列文件均位于 `/private/tmp/stock-suspend-s1-20260906.ujj5Ni`，不进入正式运行源码；临时文件以后可能被系统清理，因此本文保留结论、方法、版本与指纹。

| 文件 | SHA-256 | 用途 |
| --- | --- | --- |
| `test_confirmed_suspend_dagster_boundary.py` | `055b1c65c4eedb9ad489cd55498c4c8e5c8e885e0f3034d36b03f4d9eba856bb` | 原模型复现，8 项 |
| `dagster-gate-run2.xml` | `e5915118a335cea8778d00a93c7bf417d56a3be33622e5c898f139fa79c5f3bc` | 7 过 1 失败的 JUnit，含缺失 target 明细 |
| `test_confirmed_suspend_explicit_evaluation.py` | `1c0f5467c21f103c60b4ba806e37552e8a2b3d6cded3a021654805c80a207056` | 待确认修正的独立机制实验，5 项 |
| `dagster-explicit-run1.xml` | `380a49c6fae101fdfdb40da92af198338889c4bf87b8d6b1221600fedc7ee9ae` | 5 过的 JUnit |

测试均在 orchestrator 现有环境以 `uv run --no-sync python -m pytest` 执行，清除 `DAGSTER_HOME`、关闭自动插件、`-c /dev/null --noconftest -p no:cacheprovider`，显式 `--basetemp` 和 `--junitxml` 指向上述临时目录。两轮均出现现有 Dagster partitioned checks 的 preview 提示，未安装或更新依赖。首次本地 fixture 缺少临时 instance 父目录的设置错误已修正后重跑，不将该设置错误计为 SDK 缺陷。

本次 CodeGraph `explore` 覆盖停牌 Silver writer、sensor 与路径，`impact(silver_stock_suspend_daily, depth=2)` 辅助确认影响面；图有漏边，结合当前源码、原消费者矩阵和 SDK 实现核验。未修改架构边界、子系统依赖矩阵或业务源码，不提前更新架构快照。

**首次实验交付时的下一步（历史）：确认 §15.3 的窄修正是否采纳。**该确认随后已经取得，不再作为当前待办；当前事故后恢复顺序见 §18。S2–S5 数据准备、正式发布、事件登记、验收切换和删除仍各自申请，不自动恢复 Silver sensor 或扩大暂停范围。

交付复核：18:03:37（北京时间）再次只读查询，仍共 88 个 sensor，与维护前比较仅指定 Silver 为 STOPPED，Raw 为 RUNNING，活动 run 为空。仓库文档完整性检查、已跟踪及两份新增设计文档的空白检查通过；技术方案/LLD 的 28 个本地链接与显式锚点及代码围栏有效，四份测试证据 SHA-256 复核一致。本次修改技术方案、LLD、主索引及原清退三份文档中的当前 TODO 进度，未改 S0 历史清单、业务代码、规则或依赖矩阵。

## 16. S1 窄修正确认后的执行清单

2026-09-06 用户确认继续；18:07:59 只读复核指定 Silver STOPPED、Raw RUNNING，88 个 sensor，活动 run 为空。开发仅在当前 dev-interface 工作区；不提交、不恢复入口、不执行正式文件/事件或 S2 候选准备。

| 执行约束 | 代码落点 | 必须验证 |
| --- | --- | --- |
| 固定 4,022 行、五列与批准 hash；一个外部无分区输入 | contract、schema、paths、catalog、AssetSpec | C01–C07、D01；错类型/错内容/错误路径拒绝 |
| 两固定检查显式真实 target，一 writer 五 checks | checks、Silver job | D02–D04、D06–D07；当前 run 存储读回，失败不调用 writer |
| Raw 不变，四列及原14条清洗不变，不读旧CSV | SQL、Silver writer | 独立 M 金样本、W 故障注入、现有消费者回归 |
| 一次候选校验、原子提升、checkpoint、重放不覆盖 | Silver writer、人工文件发布 | W/B；异常现场保留，事件失败不回滚文件 |
| 非空候选每tick固定校验一次；latest原生身份严格相符 | readiness、现有 Silver sensor | R01–R04、P01；无候选0读取，不回找历史绿灯 |
| 五命令只读默认，文件/事件确认与能力分离 | 专用 bootstrap/CLI | B/E 参数、漂移、不确定结果、幂等和越界反例 |
| 不改消费者/CLI/Prod，不删两个旧文件 | 静态护栏、原回归 | G01–G05；旧文件仅暂留作S5删除目标，不作运行兜底 |

预算沿用 §12：生产固定输入4,022行，writer/各check一次文件加载、每check至多一次mat查询，sensor有候选1次固定加载＋3次事件查询；无新源请求、全局配置或缓存。S1只有虚构临时数据/实例写入，正式Lake/staging/事件写入均为0；真实历史对账和发布性能不得由单元测试计时冒充。

以上是执行前约束，不是实际结果；§17 记录发现的偏离。发现后停止，不再以该预算行宣称实际零写入。

## 17. S1 测试隔离失误、只读核验与停止状态

### 17.1 发生了什么

2026-09-06 约18:15（北京时间），首次真实 adapter 测试把 `LakeRootResource` 的参数误写为 `lake_root=临时路径`；真实字段应为 `root_path`。该构造没有拒绝未知参数，实际 `root()` 回落到默认正式路径 `/Volumes/datasource/data_lake`。

新检查调用 `lake_root.ensure_available_for_run()`。此前未完整审计该复用函数的副作用；当前 [health/lake_root.py](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/health/lake_root.py:186) 表明，它不只是读取目录状态：会确保 `_tmp/lake_root_health` 目录存在，并写入、读回、删除 `canary-<随机标识>.txt`。因此这轮测试**超出了“不写正式环境”的批准边界**。这是执行与测试隔离失误，不是已批准的探针操作，也不是用户新提出的需求。

路径参数在排查失败时已改为 `root_path`，测试中的错误 Dagster event 属性也已纠正；随后读完整健康 helper 才确认首次测试曾有正式探针写入，立即停止测试和业务改造并告知用户。后两轮指向临时 Lake，但因虚构目录缺少 Raw/Gold，健康检查提前失败；不能把这些提前失败当作预期的内容门禁验收。

### 17.2 已核实的影响与证据边界

| 项目 | 已核结果 |
| --- | --- |
| 首次测试临时运行记录 | `pytest-196` 下9个 run SQLite 文件：18次 STEP_START、18次 STEP_FAILURE，9个 PIPELINE_FAILURE；无实际 ASSET_MATERIALIZATION 或 ASSET_CHECK_EVALUATION。45条 check planned、9条 materialization planned 均在临时实例，不代表业务执行 |
| 失败位置 | 代表性成功输入样例的两个 check 均在“固定事实缺少匹配的无分区发布记录”处失败。该检查在健康探针之后、固定文件加载之前；参数错配使批准的临时发布 URI 与正式路径不符 |
| 正式探针目录 | `/Volumes/datasource/data_lake/_tmp/lake_root_health` 当前为空，无 `canary-*.txt` 残留；目录修改时间为18:15:49，父 `_tmp` 的修改时间仍为8月7日。未执行任何补充删除 |
| 停牌数据与事件 | 本次尚未修改原 Silver writer/job/sensor/readiness/SQL；失败的临时作业未进入 writer。未调用正式实例事件发布或正式作业启动。没有进行正式 Parquet 全内容重审计，不能把以上证据写成全湖无变化证明 |
| 当前维护状态 | 18:18:04只读查询：Silver sensor STOPPED，Raw sensor RUNNING，活动 run为空；未恢复/扩大暂停范围，未重载服务 |
| 版本控制 | 当前 dev-interface，未提交/推送；源文件为部分实现状态，不能部署或将S1标记完成 |

首轮临时证据根为 `/private/var/folders/0x/12zkmckd1hb2vfp3w4vb7w480000gn/T/pytest-of-congming/pytest-196`。代表性run为 `test_real_checks_native_target0/instance/history/runs/1f7ea1ed-2f09-423d-87a4-655c4d598ba9.db`。对已关闭的 SQLite 文件使用 `mode=ro&immutable=1` 读取结构和事件聚合，没有连接正式 Dagster PostgreSQL；临时证据可能被系统后续清理。

### 17.3 代码与测试实际进度

已编写但未整体验收：新固定合同、三条路径 helper、五列 schema、中文名及 metadata key、catalog entry/model、外部 AssetSpec、两个显式 target 检查，以及合同/Dagster测试。原 Raw/Silver四列、14条时段修正、原writer、job、sensor、SQL、分钟CLI均未修改；未开始人工发布CLI及文件checkpoint。

纯合同测试23项通过；但完整新测试首轮31过3失败、纠正fixture后的Dagster轮9过2失败，**均不构成S1验收**。若负向样例只断言“作业失败、writer未执行”，会被非预期的健康检查失败蒙混通过，必须同时断言失败原因、到达的阶段和检查事件。§15 的独立框架机制实验仍是历史证据，不可移作当前正式adapter通过的证据。

### 17.4 事故后提出的处置顺序（已确认先补方案供 review）

1. 测试资源必须显式传 `root_path` 并立即断言实际根等于当前临时根；未知参数/默认根必须被测试拒绝。不能只修参数后宣称隔离可靠。
2. 在测试执行前建立路径和资源拒绝保护：任何正式 `/Volumes` 路径、正式 `DAGSTER_HOME`、默认DuckDB临时目录、正式instance或网络访问立即失败；覆盖mkdir、open、rename/replace、unlink等入口，不能只拦网络和instance。
3. 两个新固定 checks 改用只读根/文件边界核验，不再复用会写探针的 `ensure_available_for_run()`；不改现行全局健康helper和其他资产，不借本次事故扩范围治理健康链。
4. 在虚构完整目录与显式临时instance中重新验证D06/D07；反例必须核实预期失败原因，不能用任意失败充数。再校准一次加载预算、无分区发现/catalog纳管、readiness和后续writer/CLI。
5. 用户已同意先补原 LLD 供 review，再修隔离与两个新 checks、独立验收后继续 S1。具体执行细节见 §18；本轮停在文档 review，不运行测试、继续业务修改、清理现场或恢复 sensor。S1 完成、S2–S5 仍分别验收批准。

此停止由正式环境边界和开发审计技能的“复用前核验真实语义”要求触发；已主动向用户报告，没有把事故包装成正常进度。

<a id="s1-test-isolation-repair"></a>

## 18. 测试隔离与新检查安全修正 LLD（本轮 review 入口）

### 18.1 范围、事实依据与本轮停止点

这是 H13 的实施补充，不是新的数据治理专项。用户确认的顺序是：**补齐原 LLD review → 仅修隔离与两个新检查 → 独立验收 → 继续原 S1**。本轮只改本文、技术方案和主索引；不改 Python、依赖、AGENTS、正式状态或数据，不提交、不删除。下面的文件和接口均为待实施，不能因本节写完就标记隔离已建立。

本轮静态复核及 CodeGraph `status/search/callers/callees` 覆盖新 checks、LakeRootResource、健康 helper、DuckDB 连接和两份现有专项测试。图中 `ensure_available_for_run` 有同名测试替身，callers 返回有数量上限，`fetch_materializations` 还误关联到测试同名方法；因此调用边以实际函数与临时实例注入代码核定，不能把图当运行验证。已确认的直接链为：

`新 check → LakeRootResource.ensure_available_for_run → assert_lake_root_available_for_run → canary 写入/删除`。

`DuckDBResource.connect → connect_configured_duckdb` 也会先创建默认移动盘临时目录。修正不能只替换 Lake 参数而忘记 DuckDB。两条共享资源链有其他现行资产消费者，本轮均不改默认值、不全局改模型校验策略、不删健康函数。只在新检查取消不必要的探针调用，并在专项测试中约束资源。

### 18.2 下一轮逐文件白名单

以下路径均相对 `lake_console/orchestrator/`。下轮先实现前三行的隔离支持并验收 I 组，再修改实际 checks 和 C/D 测试；其余 S1 业务文件先不继续开发。

| 文件 | 已核现状 | 精确修改 / 验收 |
| --- | --- | --- |
| `tests/stock_suspend_confirmed_test_runner.py`（拟新增） | 尚不存在 | 父启动器仅用标准库，管理一次独立临时目录、受限子进程、阶段选择和证据；父进程不 import orchestrator/Dagster、不构造业务资源，I 组通过前禁止启动 adapter 阶段 |
| `tests/stock_suspend_confirmed_test_support.py`（拟新增） | 尚不存在；当前 fixture 藏在 contracts 测试中 | 提前加载的专项 pytest 插件及资源工厂；集中清理继承环境、核验实际路径、连接设置和实例身份；不新建全仓 `conftest.py`，不让测试文件互相导入 fixture |
| `tests/test_stock_suspend_confirmed_isolation.py`（拟新增） | 尚无独立隔离验收 | I01–I08 正反测试；用虚构禁止目录验证 Python 与原生 IO 拒绝，不以正式湖为试验目标 |
| `src/orchestrator/defs/checks/stock_suspend_confirmed_checks.py` | `_evaluate_confirmed_check` 首行调用写探针 | 仅按 §18.4 改为文件只读前置检查，补失败阶段/原因；保留两 check 名、ERROR blocking、显式 target、无分区与查询上限 |
| `tests/test_stock_suspend_confirmed_contracts.py` | fixture 只禁止 instance 自动发现与 socket；固定文件放 `tmp_path` | 业务 import 前先调用 support 的运行上下文断言；fixture 移至 support 并显式使用，移除重复定义；原 C 组业务 expected/批准身份不放宽 |
| `tests/test_stock_suspend_confirmed_dagster.py` | 已改正参数名，但未断言资源实际根；从另一测试文件 import fixture | 同样先断言受限上下文，再 import 业务；用 support 工厂构造真实 `LakeRootResource` 并核对最终根；按 §18.5 验证真实成功与失败，不仅断言 `success=False` |
| `src/orchestrator/defs/resources.py`、`defs/health/lake_root.py`、`defs/duckdb_connection.py` | 全局共享且有其他资产使用 | **不改**；防止通过改默认根、全局禁止探针或放宽连接配置影响其他资产 |
| `defs/stock_suspend_confirmed_contract.py`、catalog/schema/paths/metadata 的已有部分实现 | 尚未整体验收 | 本安全修正轮先不继续扩写；如只读检查所需能力不能由现行接口满足，先记录差异回修本节，不临场增加通用 helper |
| 原 `assets/suspend_d.py`、SQL、job、sensor、readiness、bootstrap、分钟 CLI/消费者、CSV/timing | 现行链/后续 S1 工作 | **本安全修正轮不改**，不得混入 writer 迁移、CLI 实现或旧文件删除 |

### 18.3 测试启动、文件隔离与资源构造

#### A. 先隔离进程，再加载业务模块

单靠 `tmp_path` 或 Python monkeypatch 不足以阻止 DuckDB/SQLite 原生文件访问。专项 runner 必须在 pytest/业务模块导入前，为子进程建立操作系统级文件与网络限制；Python 拦截只负责早报错和计数，不能作为唯一防护。

本机已只读确认存在 `/usr/bin/sandbox-exec`，其本地手册 `/usr/share/man/man1/sandbox-exec.1` 支持 `-f/-p/-D`，同时明确标为 **DEPRECATED**。因此本方案仅把它用于当前 macOS 的专项测试子进程，不进入正式产品或修改系统全局配置。**命令存在不等于限制有效**：下一轮第一项是对虚构目录做 I01/I02 能力验证；不支持、策略加载失败或底层 IO 未被阻止就停止，不降级为无保护 pytest，也不自行改用新容器、机器或依赖。策略正文和精确启动 argv 在执行前展示，只允许本节范围；本轮尚未生成或运行策略。

runner 单次创建一个新的 `/private/tmp/stock-suspend-isolated-<随机串>/`，不复用前次 pytest 目录；内部为 `allowed/` 与 `denied-fixture/` 两个兄弟目录。`allowed/` 内固定放 Lake、staging、DuckDB temp、SQLite instance、pytest 临时区和报告；`denied-fixture/` 仅由无业务导入的父 runner 写入小型虚构样本，之后受限子进程不可读写。结束保留精确路径供 review，不递归清理其他运行目录。

受限子进程策略必须满足：

1. 持久文件写入只允许本次 `allowed/`；仓库、虚拟环境、用户目录、正式 Lake/staging 均不可写。标准输出/错误等进程运行所需非业务通道单列，不用宽泛目录例外放开。
2. 正式 `/Volumes`、用户正式 Dagster home、正式凭据/配置和本次 `denied-fixture/` 不可读取；规则按规范化真实路径生效，不能被符号链接、`..`、`/tmp` 别名或打开文件描述符绕过。拒绝把正式数据复制到临时目录作为 fixture。
3. 禁止网络连接及本地数据库 Unix socket；不加载 token、数据库 DSN 或正式 instance 配置。子进程关闭不必要继承 FD，不给它父进程已打开的业务文件。
4. 不设置或覆盖 `HOME`、`CODEX_HOME`，不修改 shell 配置；以受控子进程环境移除 `DAGSTER_HOME`、连接凭据、`PYTHONPATH`、外部 pytest 插件参数等继承项。临时目录和报告参数仅作用于当前子进程。
5. pytest 关闭自动插件和缓存，不加载仓库 conftest；显式使用 `-c /dev/null --noconftest -p no:cacheprovider`，只额外加载本专项 support 插件。插件在业务测试 collection 前安装保护；autouse fixture 不能作为保护开始的最早时点。
6. support 发现不是本次受限运行上下文时，在导入业务测试之前报错；runner 不接受任意命令、文件路径或额外 pytest 参数透传。直接运行现有两份专项测试不得静默跳过保护。

support 顶层只加载标准库与 pytest，不在保护安装之前 import Dagster、DuckDB 或 orchestrator；资源工厂在通过当前受限上下文断言后才延迟导入实际类。I 组自身使用单独的虚构 collection 样例检验这一顺序，不能为了验证保护先收集尚未修正的两份业务测试。

runner 的操作意图仅 `--scope isolation` / `--scope adapter`，没有默认连续执行模式。`isolation` 完成后退出并报告，人工 review 通过才进入 `adapter`；进入 adapter 时先在同一限制下重新做小型隔离自检，不能仅信任上次报告或一个环境变量。解释器使用当前 orchestrator 项目的现有 `.venv`，不安装依赖、不设置 `PYTHONPATH`，不调用 `dg` 来启动测试；父 runner 不构造 Lake/DuckDB/Dagster 资源。

#### B. 测试资源必须读回实际值

support 的测试工厂 `make_confirmed_test_resources(*, lake_root, work_root)` 不接受 `**kwargs`；参数必须为本次临时目录内的绝对路径。它构造**实际类** `LakeRootResource(root_path=str(lake_root))`，随即断言 `.root()` 等于已核定的临时根；错误参数、缺少明确根或回落正式默认根均报错。未知参数反例由测试工厂拒绝，不为本专项改全局 Pydantic/Dagster 配置；也不使用一个永远返回临时路径的假资源掩盖真实构造问题。

固定输入 fixture 只包含手写小样本，生成目录和文件前先核定临时根。不向正式 `paths.py` 增加测试开关，也不 monkeypatch 正式默认根把参数错误藏住。Python 路径拦截核验目标在允许范围内后才调用真实 IO；双路径操作如 rename/replace 必须同时核验源和目标。

DuckDB 测试资源保留显式 `:memory:` 连接，所有连接均限定 `temp_directory=本次临时目录`、`max_temp_directory_size=0B`、`threads=2`、`memory_limit=512MB`；关闭自动扩展安装/加载。连接建立后读回设置，任何不符立即失败；不调用会 mkdir 默认正式临时目录的统一默认连接。上述仅为已有测试替身设置，不改变正式 `DuckDBResource` 配置。隔离自身验收还必须直接测试原生 `read_parquet` / `COPY`，不能只测试 Python `open`。

Dagster 使用 `DagsterInstance.local_temp(本次临时instance目录)` 和显式 `execute_in_process(instance=...)`；关闭遥测，仅一个虚构日期。建实例前核定路径，建后核验 event/run/schedule 存储均为该临时 SQLite 实例；禁止 `DagsterInstance.get()` 和自动发现正式 home。测试中的初始 runless 发布只写该实例；对真实 checks，不 mock 掉其实际发布关联逻辑。

#### C. 新增测试设置审计

这不是生产配置变更，设置只在 runner/support 一处定义和显示；不得新增 env/Settings/数据库配置。

| 设置 | 来源 / 默认 / 消费者 | 生效与可见性 / 门禁 |
| --- | --- | --- |
| `scope` | 显式二选一，无默认；runner | 每次启动生效，报告记录；I07 拒绝缺值/未知值/任意透传 |
| 临时工作根及允许/拒绝目录 | runner 用安全临时目录 API 生成，不接受外部任意根 | profile、support、资源工厂共用；报告写真实根；I01–I04 |
| 文件/网络隔离策略 | 专项 runner 固定规则；仅子进程 | 报告保存策略摘要/哈希、argv、版本、拒绝结果；能力失败立即停止 |
| DuckDB 内存/线程/spill | support 的现有测试口径 512MB/2/0B | 每个连接读回；I05；不改正式16GB/4线程默认值 |
| pytest 插件/环境 | runner 固定清单，无用户任意追加 | collection 前生效；报告仅记录安全字段，不输出完整环境或凭据；I06/I07 |

### 18.4 两个新 checks 的修改顺序与只读范围

仅在 `stock_suspend_confirmed_checks.py` 内增加私有 `_confirmed_input_path_readonly(lake_root) -> Path`，不新建全局 resource/helper。顺序固定：

1. 取实际 `lake_root.root()`，通过既有 `silver_stock_suspend_confirmed_path(root)` 生成唯一文件路径。这里只取路径，**不调用健康检查**。
2. 以该实际 root 调用 `contract.assert_suspend_path(path, root=root)`，先验证路径边界、目录存在及无符号链接，再用 `contract.suspend_file_identity(path)` 确认目标是现存普通文件。后者当前以文件系统根做内部检查，不能把它单独当作 Lake 根限制。只允许只读 stat/lstat/文件读取，不 mkdir、写探针、修复或删文件。
3. 根缺失、文件缺失/类型错误/越界即明确失败，后续 instance 查询、DuckDB 连接、writer 调用均为 0。文件已存在但损坏由实际加载报错，不伪造为空文件成功。
4. 路径通过后沿用最多一次 latest materialization 查询和现行 URI/version/hash/partition 校验；无有效发布则失败，固定文件解码和 writer 调用为 0。
5. 发布身份通过后才打开传入的 DuckDB 资源，复用现有 loader/schema/content validator；不跳过批准 hash、不通过修数据来通过检查。按已确认 §15.3 记录真实 target，仍是当前 run 的 ERROR blocking check。

在该 adapter 的已有失败 metadata 上给出可测试的 `failure_stage`（`input_path` / `publication` / `validation`）及具体原因；缺文件明确为缺文件，不能全部包装成“发布缺失”。存储抛错继续原异常语义，不伪造一条已存成功事件；测试以实际异常和存储读回验证该阶段。成功 metadata 不因此增添新的业务合同字段。

文件“只读”不取消 Dagster 正常 check event，也不要求把正式 DuckDB 的全局工作目录改掉：本小轮取消的是两个新 checks 的健康探针副作用。实际生产连接、writer、readiness 和一次加载预算的完整验收仍属于原 S1 后续，不因这轮防护通过而自动算完成。

### 18.5 独立隔离门禁及 D06/D07 逐类证据

I 组不能选择业务 asset/job。I01 先用标准库和虚构文件验证进程隔离；通过后 I02 才在受限进程中导入 DuckDB/SQLite 验证原生 IO，随后 I03–I08 验证资源类及临时 Dagster 实例，不加载正式 Definitions。I02 的 Parquet 正反样本由受限子进程先在允许目录生成，父 runner 只将该微型虚构文件复制到同次禁止目录；不用正式 Parquet，也不在无保护父进程中构造业务资源。

| 编号 | 正/反例 | 必须证据，不满足立即停 |
| --- | --- | --- |
| I01 | 允许目录正常读写；禁止目录读取、新建、覆盖、删除、mkdir、rename/replace，含两个方向 | 受限子进程被拒绝；父进程对虚构哨兵/文件集合前后核验一致。禁止操作只指向虚构目录，不拿正式 Lake 验证 |
| I02 | 原生 open/SQLite、DuckDB `read_parquet` / `COPY`；路径别名与 symlink 越界 | 原生路径也被 OS 拒绝；允许范围的同类操作可成功，排除因库没装或 fixture 坏而假通过。不得仅据 Python spy 计数判断 |
| I03 | 实际资源正确参数；错误参数名、未显式根、默认正式根 | 正确资源实际根等于临时根；其余在任何路径 IO 前拒绝。正式路径只作字符串输入，底层调用 spy 为 0 |
| I04 | 文件缺失、根缺失、目标是目录、`..` 或链接指向禁止目录 | 失败原因准确；不补建目录、不创建探针，不把符号链接 resolve 后当作合法原路径 |
| I05 | 临时 DuckDB 设置正确/错误；误用正式默认资源 | 正常设置读回一致；错误被拒绝且无 spill/默认路径调用；测试替身不得悄悄代替实际配置核验 |
| I06 | 临时实例创建/读回；显式默认 home、自动实例发现、网络/Unix socket | 合法事件仅在临时 SQLite；其他路径在调用前拒绝。OS 网络能力检查只对本机虚构端点，不连接真实数据库 |
| I07 | 保护未提前加载、策略缺失/失败、scope 错误、虚构 fixture 导入期故意越界 | collection 前拒绝；业务模块未运行；不得用 pytest skip/xfail 表示隔离通过；重跑不复用旧“成功”标记 |
| I08 | 仅在本次临时范围调用共享健康 helper 的故意反例 | 真实探针副作用被记录且仅位于临时区，证明能识别该类副作用；不选择实际 checks，不修改全局健康函数。两个新 checks 零探针调用在下一阶段 D 组验收 |

I 组报告验收后，adapter 阶段才运行真实 C 组及以下 D06/D07 用例。先静态确认两份业务测试在业务 import 前要求受限上下文、两个新 checks 不再调用健康 helper，再以 spy 证明实际运行探针调用数为 0。`daily` 仍是只修改临时哨兵的替身，避免这一轮提前运行正式 Silver writer；因此不能用本轮结果替代 D05 或完整 writer 验收。

| 输入 / 故障 | 必须到达的阶段与结果 | 禁止的假通过 |
| --- | --- | --- |
| 正确 fixture + 正确临时发布 | 两固定 checks 均通过、显式 target 与实际临时发布记录相同；下游哨兵执行一次，最终3 checks通过，合计5 checks | 不能只看 job success；必须存储读回 partition/run/storage_id/timestamp |
| 缺根/缺文件/非普通文件/路径越界 | `input_path` 明确原因；无事件查询、无解码、无下游写 | 不能因发布 metadata 错误而通过缺文件测试 |
| 无发布、有日期发布、错误 URI/version/hash | `publication` 拒绝；spy 证明检查到对应错误；不打开 DuckDB、不调用下游 | 不能被健康检查、临时目录缺失等提前失败替代 |
| 五列正确但内容错误 | 确实进入 validator；schema 可通过，content 失败；实际 digest 非批准值；下游不执行 | 不能只断言作业失败，必须有真实 content 失败 evaluation |
| schema 错误/Parquet 损坏 | 进入实际 loader 并取得对应 schema/读取错误；无下游写 | 不能被错误发布记录提前阻挡而充数 |
| check event 存储抛错 | 先证明已执行实际校验，再注入特定存储异常；writer 不执行，读回无伪造成功记录 | 不能使用不存在的事件属性导致 setup 失败，也不能吞异常补 runless 绿灯 |

每例同时保存：输入变体、阶段/原因、执行/未执行调用计数、run id、实际 check event 摘要和临时哨兵前后身份。禁止只凭“作业失败”或 planned 事件计数验收；正向失败时整阶段失败。

### 18.6 执行门、预算与交付

| 顺序 | 允许内容 | 完成条件与停止点 |
| --- | --- | --- |
| 1，本轮 | 只补原 LLD/技术方案/索引，静态核对源码及文档 | 交管理员 review；没有任何代码/测试已获验收的含义 |
| 2，review 后 | 只实现 §18.2 的隔离启动器/support/I测试，先做虚构目录能力验证 | I01–I08 逐项通过、留真实证据；报告后停，不在同一命令中串联 adapter |
| 3，隔离验收后 | 只修两个新 checks 及现有 C/D 测试，运行明确测试白名单 | D06/D07 正反证据完整；无正式资源访问；报告后再继续原 S1 |
| 4，原 S1 | 按 §10/§13 继续尚未完成的 merge/writer/readiness/CLI/消费者回归 | 每项独立对账；不自动进入 S2，不恢复 sensor、不重载或提交 |

安全验收规模：虚构事实通常2行、最多32行；一个日期/每 case 独立临时实例，单连接512MB/2线程/0 spill；不读取 S0 的6,166个实际文件、不发源请求。每批最多16个 case，小型 fixture 总量上限1MiB；报告只存摘要，单批工作区预算100MiB。每 case 超过30秒、单批超过60秒或空间超预算就停止该批并保留临时证据；超时不是业务失败样例的成功。超时管理仅针对 runner 自己的子进程，不杀正式服务或其他任务。

执行前给出工作目录、现有解释器、完整 argv、允许写目录、禁止目录、测试清单和影响；不把上述设计参数当成已经通过的实测。每批报告启动/当前 case/实际完成数/耗时，不创建新进度库、锁或自动重试任务。

交付必须区分 **文档检查通过 / 隔离通过 / 实际 adapter 通过 / S1 完成** 四个状态，分别附证据，不能相互替代。任何库、进程边界或环境能力不符合本节时停止并回修原文；不能在执行时临场放开目录、网络或绕过防护。

当前结果：本节只完成静态设计，三个拟新增测试支持文件尚未创建，OS 隔离能力未运行验证，I/C/D 未重跑。除批准的三份文档外不增加改动；正式数据/事件/调度不因本节发生变化。

文档验收：已阅读文档校验脚本，其只检查仓库文档引用/索引；本轮执行该检查及 `git diff --check` 均通过。另对技术方案与 LLD 的30个本地链接/显式锚点、围栏和空白做静态核验，无问题。工作区内容哈希对账确认本轮只变更本文、技术方案及 `docs/README.md`；既有未提交 Python 和其他文档未改。以上不是 OS/I/D 测试证据。
