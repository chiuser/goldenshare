# 本地 DG 停牌历史确认事实持久化与统一消费 LLD v1

更新时间：2026-09-07

状态：**S0已完成；前序增量已提交`630ba12a`、`4887cfac`，未推送。管理员确认最小日期声明修正后，§18.23完成job/check/readiness/sensor集成：53例测试＋5个既有subtests通过，其中真实job使用实际writer和三个现行最终检查。当前增量未提交；S1的人工CLI、受限连接模式及其余全套回归仍待完成。没有操作正式数据/实例、删除CSV、恢复sensor、安装套件或启动DG服务。S2未执行；临时产物最终按§18.11精确清理。**

首次设计代码基线：`dev-interface@b324ec48ce8fd67fdf216fedc6a69103fab4ae3a`。六项修订依据为 `dev-interface@f003a3c5` 加现有未提交专项代码；§18.8 启动诊断基线为 `dev-interface@a0361fc4` 加保留的未提交内容。未提交实现不是正式验收结果。

2026-09-07管理员新增约束：未经明确允许不得安装本机套件；本需求完成后必须彻底清理专项临时测试实例和运行残留，清理属于收尾验收，不得长期保留。前置验收不得继续扩展为独立通用测试工程。落实范围与SQLite来源见§18.11；权限修订和复验的后续独立批准及结果见§18.12。

上位依据：[技术方案 v1](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-suspend-confirmed-facts-technical-plan-v1.md)。本文细化该方案，不另起业务口径；原清退专项的 `TODO-SUSPEND-001` 仍未关闭。

本文未在状态与执行记录中明确标为已实现的“新增”“改为”、函数签名、SQL、命令及测试名，仍是**待实施设计**。用户随后已批准 S1 开发、隔离测试及仅暂停 `silver_suspend_d_update_job_sensor` 的维护安排；维护期间不手工启动停牌 Silver job，Raw 和其他入口不动。该批准不包含正式 Lake/staging 写入、正式 materialization/check 事件、服务重载、删除或 Git 提交。S1 结束不自动恢复该 sensor；等 S3/S4 验收或另行明确批准。本次实际执行及新发现的停止条件见 §15。

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
| H13 | S1 全部测试不得访问正式文件/实例/网络，隔离先验收、业务后运行 | §18 启动器与 §10.4 全量测试资源矩阵；不改正式资源默认值 | I、C、M、W、B、E、D、R、G |

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

`stock_suspend_confirmed_contract.py` 不 import assets、jobs、sensors、bootstrap 或 `duckdb_sql.py`，不读取 CSV、Git、Dagster instance 或文件级历史报告。以下合同接口已在§18.19实现并通过合成小样本验收；不代表后续SQL/writer/CLI已实现或生产数据已验收：

```python
inspect_confirmed_file(connection, path: Path) -> ConfirmedFileInspection
load_confirmed_relation(connection, inspection: ConfirmedFileInspection, *, relation_name: str) -> LoadedConfirmedFacts
validate_confirmed_schema(connection, relation_name: str) -> ValidationResult
validate_confirmed_content(connection, relation_name: str) -> ValidationResult
confirmed_logical_sha256(connection, relation_name: str) -> str
```

先检查文件，再决定是否加载行数据；不能把“内容行数不符”当成“字段结构错误”。全部接口仍在唯一 contract 模块中，不新增旁路 schema 或业务配置。

| 步骤 | 精确行为 / 失败 |
| --- | --- |
| 路径与资源前置 | 调用方先核定允许根；inspection 记录文件身份，沿用现有单文件 100MiB 拒绝上界。缺文件、类型/路径错误、文件超预算或不可读属于前置/IO 失败，不伪装成 schema 判断 |
| 物理头信息 | 使用参数绑定、`hive_partitioning=false`；至多一次 DESCRIBE、一次行数聚合，读取真实五列类型/顺序与行数，检查前后身份不变。结果只保留 schema、计数、身份，不持有 Python 明细 |
| schema 判定 | 只比较五列名字、顺序、物理类型；与关系级 `validate_confirmed_schema` 共用唯一私有列比较函数。合法空表或多一行不会因此变成字段错误 |
| 内容前置 | 完整内容通过必须是 4,022 行。行数不符返回 `row_count_mismatch`；这属于 content 失败，不改变 schema 结果。超过批准行数不解码整表来算 hash |
| 行加载 | 仅物理 schema 合格且行数不超过批准上界时允许；加载前身份必须与 inspection 一致，直接投影五列建 TEMP TABLE，不 cast/trim，加载后再比身份。旧 inspection 不能复用到已变化文件 |
| 校验与复用 | 每连接至多一次行解码，schema/content/合并复用该 TEMP TABLE；无跨 run 缓存。schema check 在可有界编码时记录实际 digest，否则留空，不能填批准常量 |

100MiB 是异常文件拒绝阈值，**不是**预期文件大小，也不代表可分配100MiB明细到 Python；正常固定 Parquet 仍预计不足1MiB。DuckDB 连接内存/spill 约束独立生效。DESCRIBE、行数聚合与行解码分项计数，不能把三条 SQL 说成三次完整解码，也不能把一次行解码说成只打开文件一次。

| 结果对象 | 必要字段 |
| --- | --- |
| `ConfirmedFileInspection` | path、file_identity、实际列名/类型/顺序、row_count、schema_validation；不可变，不保存连接/实例 |
| `LoadedConfirmedFacts` | relation_name、path、file_identity；不返回全量 Python 明细 |
| `ValidationResult` | passed、reason_code、checked_rows、failed_rows、最多20条samples、logical_sha256（可计算时） |
| `ConfirmedFactsSummary` | version、logical_sha256、row_count、code_count、date_count、两模式计数、日期范围 |
| `FileIdentity` | resolved path、device、inode、size、mtime_ns；人工发布及每日writer输入另存物理SHA-256 |

两个新 checks 的执行分支固定为：

1. 路径与发布身份先过 §18.4；随后取得 inspection。
2. schema 错：两 check 均报告失败，不加载行数据。
3. schema 对、行数超过4,022：schema 通过且实际 digest 留空，content 返回行数不符；writer 不执行。0行或少行同样 content 失败，schema 仍通过。
4. schema 对、行数允许：schema check 可加载以记录实际 digest；content check 只有行数准确时才继续键/模式/hash完整验证。行数正确但换键，schema 通过、content 失败。
5. 文件损坏/漂移/资源超限等前置错误抛有原因的 Failure，不伪造“schema 已完整检查”的绿灯。捕获边界见 §18.4。

Dagster adapter 采用已确认 §15.3 显式原生发布关联，不使用已被实测否定的自动 target 假设。纯合同模块不创建连接、instance 或事件。已有草稿的“共同 loader 在 schema 分支之前拒绝超行数”必须重构；这是 §18.2 明列的合同修改，不是继续沿用原实现后改测试 expected。

`duckdb_sql.py` 保留 `suspend_d_normalized_select(raw_path)`；移除旧两参数 `silver_stock_suspend_daily_select(raw_path, partition_key)`，不保留兼容 wrapper，替换为：

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

实施顺序补充（2026-09-07）：当前 `assets/suspend_d.py` 的唯一 writer 仍调用旧两参数接口，签名不能先于调用方单独切换。先实现长期共用的私有 `_stock_suspend_confirmed_ctes`（包含最终四列 `suspend_merged` 关系），以及上面两个冲突/统计接口；金样本直接查询该关系。随后在 §5 writer 改造同轮，将旧公开接口替换为上述关系式接口并删除旧实现。不是新增第二个合并入口、兼容 wrapper 或签名分支；本小轮不修改现行 writer/旧 SQL，不声称现行链路已退出 CSV。

三个 relation 均由调用者在同一连接建立，名字是内部简单 identifier，经白名单校验，不是 CLI 输入。日常 dates_relation 一行 `trade_date DATE`；批量为批准日期集合。normalized 保留重复；confirmed 先通过全文件批准身份，不能只检查当天切片。

这些 helper 只返回 SQL；共享 CTE 构造，不执行 IO、不查询 instance，不打开其他日期路径。文件内日期归属由 §5 writer / §8.4 批量入口在合并前验证；不要在 SQL 中过滤掉错放行。

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

`normalized` 仍使用原日期解析/空白时段标准化。Raw check 的日期规则保持，但它并不被 Silver-only job 选中；Silver 现有分区检查只核对任务日期。因此 §5 writer 必须在当前已加载关系上检查行内日期；§8.4 还要检查批读文件与日期的映射。此处是明确批准的写前输入校验，不新增/改名 asset check，不改 Raw 数据或正常清洗语义。

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

返回形状为单行八个 BIGINT 计数及 `samples` 列；samples 是最多20个 `{category, ts_code, trade_date}`，按 category/code/date 排序，空集合返回空列表。分类为 `add_missing_inserted`、`add_missing_reused`、`replace_confirmed`，按确认键统计；冲突明细由独立 conflicts SELECT 返回，调用方聚合总数、另取排序前20行。冲突非零时 `output_rows` 只是待拒绝关系的规模，不是写入成功量，禁止继续写文件。

## 5. 每日 Silver writer：精确改法与失败恢复

### 5.1 入口与正常流程

`defs/assets/suspend_d.py` 新增内部正式 writer（供 asset 和隔离测试调用，不做新 CLI）：

```python
write_silver_stock_suspend_daily_partition(
    connection, *, lake_root: Path, staging_root: Path,
    trade_date: str, run_id: str
) -> SuspendDailyWriteResult
```

输入路径只能由正式 helper 派生。保留原 `silver_stock_suspend_daily(context, lake_root, duckdb)` 入口和资源契约；日常连接继续使用现有统一默认配置。§8.2A 的受限连接模式仅供专项人工工具，不改变日常 writer/check/sensor 的配置。

执行顺序：

1. 先只读核验根目录存在、路径无 symlink/越界、Lake 与 staging 分离且同设备、trade_date/run_id；首先按 §5.2 处理本 run 已有 checkpoint，再要求首次计算的同日 Raw 存在。已提交现场必须先认定文件提交，不能被后来缺失的 Raw 提前挡住。无同日另一个 writer 是人工维护前提，不新增实例查询或排它锁；不调用会落盘的健康探针。
2. 在读取/比较前记录目标身份（或 absent），不把比较后才取得的身份当作比较前态。
3. 对固定输入：记身份 F0 → inspection/一次加载 → 完整 schema/content 校验 → 记身份 F1 → 计算物理 SHA-256（其内部也检查读前/读后）→ 记身份 F2。F0/F1/F2必须相同；保存实际 logical hash/version/物理hash。
4. 对 Raw：记身份 R0 → 一次加载 normalized TEMP TABLE → 记身份 R1 → 计算物理 SHA-256 → 记身份 R2。R0/R1/R2必须相同。不得先算出结果，再用被替换的新文件 hash 给旧结果签名。
5. 对已加载 normalized 聚合检查 `trade_date IS NULL OR trade_date <> 目标DATE`，计数非零即 `raw_partition_date_mismatch`，最多20条样本，COPY/replace均为0。原解析错误同样失败；空 Raw 为合法四列空关系。该检查不重新打开 Raw，不过滤错误行，也不修改 Raw check。
6. 原口径冲突查询非零即失败，旧目标不变；通过后构造一次输出 TEMP TABLE并统计。目标四列schema/双向EXCEPT ALL等价时，按第8步复核所有输入与目标后返回 reused，不覆盖。
7. 非等价时 COPY 到本 run staging 候选；重新读候选，核对四列物理schema、完整可读、行数、与输出关系双向EXCEPT ALL=0。候选读回前后身份不变，并取得物理hash；保留合法空表。
8. 提升/复用前，重新校验固定输入与Raw身份及物理hash仍等于第3/4步；目标仍为第2步前态，候选仍为第7步事实。任意漂移先停。同文件系统、候选fsync通过后，原子持久化 prepared checkpoint并fsync其目录，再os.replace；不预删正式目标。
9. fsync目标父目录，按候选hash读回目标并检查读前/读后身份；保存 committed checkpoint。统计和元数据取本次已经冻结的结果，不用后来变化的输入重新拼装。

所有身份与hash都是同一个输入版本的证据；身份核验不能替代hash，hash函数自身的读前/后检查也不能替代跨SQL加载的R0/R1/R2检查。额外hash字节读取列入§12预算，不新增Raw行解码。

候选对账证明传输完整性，不改变交易规则。原三个最终Silver checks仍在写后执行；仅新增上述输入日期归属拒绝，不将所有质量检查塞进writer。

### 5.2 每文件 checkpoint 与并发边界

checkpoint 位于候选同目录 `checkpoint.json`，临时写入文件亦只在staging；采用临时JSON→fsync→replace→父目录fsync。仅 `prepared` / `committed` 两个持久阶段，不新增队列、锁服务或备份。

prepared 必须包含：schema_version、run_id、trade_date；Raw path/file_identity/physical_sha256；confirmed path/file_identity/physical_sha256/version/logical_sha256；候选path/file_identity/physical_sha256；目标path、写前身份或absent；本次输出schema/row_count及§4.3全部统计（samples≤20）；阶段、更新时间、错误摘要。committed另记提升后的目标身份。缺必填字段或身份不匹配即拒绝续跑，不为未发布的草稿格式保留兼容分支。

序列化细节：checkpoint 为 UTF-8 JSON，内部格式 `schema_version=1`，最大1MiB（不是 env/运营配置，仅 writer 读写共同采用的损坏文件拒绝上界）。严格核验字段集合、类型、路径与当前 run/day、schema、计数及样本；拒绝重复 JSON key。输出同时冻结既有时段修正的计数、版本和规则样本，续跑元数据不读取新输入重算。每次原子保存使用同目录独立临时 JSON，失败临时文件留存，不覆盖旧诊断；有效 prepared 不因无关失败临时 JSON 而丢失续跑能力。

恢复按以下优先级执行，先判“已经提交”，再判“是否允许继续提交”：

| 优先级 / 现场 | 精确处理 |
| --- | --- |
| 1：checkpoint合法，目标存在且完整读回hash等于prepared候选hash（阶段可为prepared/committed） | 这是上次文件动作已完成；不得再次replace。核验schema/行数与冻结结果一致，补记committed。随后只读核对当前输入身份/hash：仍一致才返回冻结统计；若输入已变化/缺失，保存“文件已提交、当前输入已漂移”诊断并失败退出，不宣称当前链ready、不用新输入修改旧结果；新run另行重算 |
| 2：checkpoint为committed但目标不匹配/缺失 | 停止人工核验，不能把已提交任务变成覆盖后来目标的重放 |
| 3：只有prepared、目标不等于候选hash | 必须同时证明候选完整、Raw/confirmed物理身份与hash及批准逻辑身份未变、目标仍等于写前身份/absent，才能执行原提升步骤；任一不符即停 |
| 4：无prepared、目标和输入可重新读取 | 无残缺候选时可在本run从头计算；有残缺候选则保留现场并停，不猜它是否可提升 |
| 5：prepared候选丢失且目标也不匹配、checkpoint损坏或必填项缺失 | 停止并保留现场，不扫描别的run猜测恢复依据 |

文件提交后metadata/event失败，仍保留正确文件；同run重试依据上述表，不通过重复覆盖“补观测”。这里的“确认已提交”只说明上次文件事实，不自动证明现在输入仍有效。

另一个run不扫描旧run staging。它用当前批准输入重新计算，若目标四列等价则reused返回；允许Parquet压缩/二进制不同，不要求跨run物理hash相同。

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

**S1 验证状态：**上述关联要求不变，不能依赖 `AssetCheckResult` 自动填写原生 target。§15.2 已复现关联为空；§15.3 的显式原生evaluation在§18.19通过实际adapter小样本，§18.23进一步通过实际writer/job与readiness的隔离集成。原三个最终Silver checks仍返回`AssetCheckResult`，不改成显式evaluation；只按已确认§18.22补齐日频检查分区声明。

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

2026-09-07实际定义复核曾发现三个原最终checks缺少显式日期分区，原替身检查却声明了测试分区，导致D03未覆盖真实定义差异。管理员确认最小改法后，只给三个日频检查增加现有`cn_a_stock_trade_days`声明，业务判断不改；实际definition/evaluation/storage三层日期归属已在§18.23通过，D03未放宽为允许空分区。审计与确认经过见[§18.22](#s1-daily-check-partition-audit)。

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
| DuckDB | 统一连接；日常沿用原默认，专项CLI显式§8.2A受限模式 | 默认16GB/4threads及原spill路径/上限不变；新增的内部初始化策略不进入env/Settings/运营参数 | 默认分支与受限分支分开验收，禁止绕开统一入口 |
| CLI 操作标识/确认项 | 单次参数；plan/checkpoint 在专项 staging | 无配置中心、无默认写入；仅本次操作 | §8 参数测试和事件隔离 |

本轮无新env、Settings、数据库配置表、前端常量或自动更新策略。version/hash是数据合同；§8.2A只扩展统一连接的内部初始化策略，不增加可随意调整的CLI性能参数，所有消费者与门禁在该节登记。

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

read-only 命令（含两个发布命令未确认的分支）不得顺便mkdir、写cursor/checkpoint、记录asset observation或刷新catalog；连接/实例初始化也在此约束内，不能只检查最终业务函数。`compare --save-report` 是明确的 staging 写入，若已存在不同报告则拒绝，先展示差异，不自动覆盖。

确认参数只是防误触，不等于用户授权已存在；执行前仍需用户批准对应的文件/事件及 staging 记录写入。没有 `--force`、`--overwrite`、`--skip-checks`、日期筛选缩小验收、任意候选/输出路径、合并模式或 SQL 参数。

退出码：0=审计/计划成功或执行完成/等价复用；2=参数/路径不合法；3=校验或全范围对账不通过；4=输入/目标冲突或漂移；5=数据已发布但观测或 checkpoint 未完整；6=IO/instance 失败，无法确认结果。输出必须带 `mode=readonly|apply` 和 `applied`，dry-run 返回 0 不能误解为已发布。

### 8.2A 连接与实例取得：先分命令，再取得必要资源

代码依据：当前 `defs/duckdb_connection.py::connect_configured_duckdb` 首先调用默认移动盘temp目录的mkdir；`DuckDBResource.connect` 委托它。只换SQL不能使CLI只读。本次选择**在统一入口增加显式受限初始化策略，默认分支不变**，不在bootstrap私建裸连接。

目标签名：

```python
connect_configured_duckdb(
    settings: DuckDBConnectionSettings = DEFAULT_DUCKDB_CONNECTION_SETTINGS,
    *, temp_policy: Literal["managed", "existing_no_spill"] = "managed",
)
```

| 策略 | 初始化与配置 | 消费者 |
| --- | --- | --- |
| managed（默认） | 原mkdir、settings.config、连接校验与关闭行为保持；默认目录/16GB/4线程/512GB spill不变 | 当前全部日常asset/check/sensor/bootstrap与DuckDBResource，不批量改调用方 |
| existing_no_spill（显式） | 先验证settings指定temp是现存普通目录、无symlink；缺失即失败，不mkdir。连接配置覆写max_temp_directory_size=0B、autoinstall_known_extensions=false、autoload_known_extensions=false；其余设置保持。连接建立后按有效配置读回上述值，不符即关闭并失败 | 仅本专项CLI的五个命令及专项bootstrap验收；不是运营开关，也不等于数据库层禁止任意COPY |

专项CLI固定使用现有统一temp路径作为**仅校验、不创建、不写入**的工作路径，最大内存/线程沿用默认；目录未准备好就报告缺失，不能自建。显式apply也用同一无spill连接；获准的候选/报告/checkpoint写入由命令自己的白名单控制，不通过切回managed取得额外权限。无spill内存不足即停，不自动增内存或借临时目录兜底。

所有设置只在统一入口定义有效策略，CLI选择策略；不新增env/持久配置、不修改DEFAULT常量、DuckDBResource或其他业务模块。实现前静态列全当前调用方及有无显式settings；验收保留 `test_duckdb_connection.py` 的默认合同、临时目录创建、关闭/异常传播，并增加受限模式目录缺失/已存在、禁扩展/0spill读回及未知策略反例。不能用替身连接替代被测统一入口，见§10.4。

| 命令 / 分支 | 取得顺序及允许副作用 |
| --- | --- |
| 无参数、help、参数/operation_id格式错误 | 解析即返回；不打开Lake/staging文件、不构造DuckDB/instance，不创建输出目录 |
| inspect | 参数/路径检查→只读plan/候选/目标→受限连接；无instance，无文件写入 |
| compare | 读取冻结plan→受限连接→有界比较；无instance。只有明确save-report且另获准时，才在既有专项目录写报告，不隐式创建整个工作目录 |
| publish-file无确认 | 只读核查计划/报告/hash/实际文件，展示动作；不调用文件mutator、不构造instance、不补checkpoint |
| publish-file有确认 | 先完成确认参数及只读验证，再调用文件mutator；仅目标和file checkpoint的批准写入，无instance |
| audit-events / register-events无确认 | 参数与文件校验→受限连接→核定plan中的本地实例配置→只读取得已有实例→有界事件读取；无事件/checkpoint写入 |
| register-events有确认 | 同上只读前置完成后，单独进入§9事件写入与event checkpoint；没有Lake写入能力 |

实例构造也是被审计的IO入口，不因方法名是get就假定只读。取得前核验既有home/config与plan身份，取得后核验存储身份；禁止创建home、存储表、SQLite库、日志目录或迁移schema。E/B测试覆盖构造阶段的mkdir/DDL/事件写入拦截，以及错误身份在查询前被拒绝。当前本文**不声称已验证SDK构造零副作用**；若实际配置/构造做不到，事件CLI不得进入正式试跑，应先补充具体只读取得路径的代码证据和设计，不以构造后的身份检查掩盖提前写入。

以上资源能力在同一CLI测试中从参数解析到退出全链记录：文件变更集合、mkdir/COPY/replace/checkpoint/event计数、连接设置和instance调用次数。只读分支不能借save-report或确认参数测试的授权写入。读取可能产生系统atime，不将其等同于业务内容写入；文件校验比较内容、集合、size/inode/mtime。

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
| `defs/assets/suspend_d.py` | 修改 | Silver deps、新writer/输入/统计；§5行内日期校验、输入版本绑定和checkpoint；删除旧full-day私有查询/统计及仅Silver使用的.tmp writer；Raw函数/decorator不改 | M、W、D |
| `defs/duckdb_sql.py` | 修改 | 删除两项full-day import；替换§4三关系签名；保留normalized及时段清洗，不过滤错日期行 | M |
| `defs/duckdb_connection.py` | 原S1后段窄修改 | §8.2A受限初始化策略；默认分支/默认值/既有消费者保持；不在隔离首轮修改 | B、G、连接合同 |
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
| `src/orchestrator/defs/stock_suspend_confirmed_contract.py` | 版本/hash、inspection与loader分工、schema/content/资源失败分类；统一新签名；不import duckdb_sql、不藏CSV |
| `src/orchestrator/defs/checks/stock_suspend_confirmed_checks.py` | 两 check adapter；纯逻辑复用 contract |
| `src/orchestrator/defs/bootstrap/stock_suspend_confirmed.py` | §8/9 专用计划、比较、文件/事件 adapter；无源接口和每日调度 |
| `src/orchestrator/defs/bootstrap/stock_suspend_confirmed_cli.py` | 五个专用子命令、确认/错误码；不接入 stk_mins CLI |
| `tests/test_stock_suspend_confirmed_contracts.py` | C 组；类型、编码、路径、批准内容身份 |
| `tests/test_stock_suspend_confirmed_merge.py` | M/W 组；独立 expected 与每日 writer 故障注入 |
| `tests/test_stock_suspend_confirmed_bootstrap.py` | B/E 组；CLI、文件发布、事件中断 |
| `tests/test_stock_suspend_confirmed_dagster.py` | D 组；自动发现、外部检查与分区 job、真实隔离事件关联 |
| `tests/stock_suspend_confirmed_test_runner.py` | isolation/adapter独立停止；原S1恢复后§10.4固定regression清单；不开放任意命令/路径，不进入正式defs |
| `tests/stock_suspend_confirmed_test_support.py` | 专项提前加载的测试插件、临时资源工厂、目录/连接断言；只供本专项测试 |
| `tests/test_stock_suspend_confirmed_isolation.py` | I 组；隔离自身正反验收、启动失败不进入业务测试 |

### 10.3 现有测试修改与保留

`tests/` 以下默认指 orchestrator tests：

| 文件 | 明确动作 |
| --- | --- |
| `test_asset_governance_contracts.py` | 对执行定义与外部 spec 分类型收集，合并为全资产 specs；定义对象 map 可只保留 executable，但 catalog 数量/键/schema/check 对账必须使用全 specs；断言新资产不可执行且无分区；不放进 CONTRACT_ONLY 排除集合 |
| `test_run_contract_static_gates.py` | 新固定读取方白名单、唯一 writer、AssetSpec metadata 注册、无 CSV/旧 import/Git fallback/源请求和正式目录 staging |
| `test_suspend_d_sensor.py` | 补固定 readiness fixture、计数和失败用例；原 Raw sensor/run key/date window assertions 保留 |
| `test_suspend_d_checks.py` | 保留原5 check名称、空分区/错日期/重复；修测试资源；Raw行内日期与Silver任务分区检查不能混为一谈 |
| `test_duckdb_connection.py` | 默认分支合同保持；新增受限初始化正反验收；真实实现不得被连接替身替换，保留委托/异常断言 |
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

### 10.4 全部必跑测试的资源处理矩阵

§18先实施隔离和adapter，不代表其余回归可以在保护外运行。本表连同§10.2/10.3是固定白名单。原S1恢复后，runner新增显式 `--scope regression --suite <表内测试名>`，精确映射到一个文件，禁止任意路径、`-k`或额外参数透传。一个suite所有case分批完整对账，不挑过失败项；一个suite结束即退出报告，不串联S2。

全部suite在业务import/collection前启用同一OS限制。临时Lake、staging、instance、DuckDB、报告、TemporaryDirectory均在本次allowed下；拒绝正式根、实例和网络。根架构护栏仅只读仓库，不访问物理Lake。

连接按三类处理，不能只替换传入的duckdb参数：

- R：实际使用DuckDBResource的测试/函数，注入受限临时连接。
- C：被测函数内部直接调用统一连接。support在业务模块导入前绑定测试入口；已导入模块逐一核对登记的直接别名，包括 `from ... import connect_configured_duckdb`。只在测试进程替换连接，不修改业务文件、默认常量或业务结果。
- N：测试自身/测试替身的裸内存连接，改用临时连接工厂，明确512MB/2线程/0spill、禁自动扩展，读回验证。OS限制仍承担原生IO保护，不能被Python替换代替。

加载后列出本suite实际连接绑定；新增未登记入口先回修矩阵及fixture，不能执行时自动扫描并改写全仓对象。成功例必须进入真实业务查询；负例必须是预期原因，不能把OS拒绝默认目录算作业务验收通过。

| suite（默认在orchestrator/tests下） | 已核当前入口 | 精确处理 / 必须保持 |
| --- | --- | --- |
| test_stock_suspend_confirmed_contracts.py | 顶层业务import、小型连接、approved_sample改常量 | 提前保护；N；fixture移support；synthetic标记，C01/C05生产验收待S2 |
| test_stock_suspend_confirmed_dagster.py | 实际checks、临时instance、跨测试导fixture | R；核对实际root与SQLite存储；移除跨测试fixture；真实target/失败原因验收 |
| test_stock_suspend_confirmed_merge.py（新增） | 计划的SQL/真实writer/直接统一连接 | C/N；临时Raw/Silver/staging；M/W必须实际执行被测writer和续跑 |
| test_stock_suspend_confirmed_bootstrap.py（新增） | 计划的CLI/初始化/文件/事件入口 | 真实受限连接配测试settings，不能mock初始化绕过B02/B06；其他计算R/C，E用临时instance |
| test_suspend_d_checks.py | _write_rows:57默认资源；check内直接连接 | R/C；保持原5checks与业务expected |
| test_suspend_d_sensor.py | FakeInstance/patch；后续新增固定readiness | 保留原选择替身；固定事实用临时R/C；不构造正式instance |
| test_stock_daily_raw_checks.py | _write_rows:49及多处默认资源、stock_daily_checks | R/C；缺口/停牌/空表/重复expected不变 |
| test_stock_daily_raw_repair.py | fixture:63/161默认资源、缺口定位及Tushare替身 | R/C；保留Tushare替身，禁真实网络；补拉集合不变 |
| test_stock_daily_freshness_guard.py | fixture:82/249默认资源、stock_daily路径 | R/C；临时引用文件，日期/freshness断言不变 |
| test_stk_mins_silver_m5b_contracts.py | fixture:55/84默认资源、writer/check | R/C；五频/停牌过滤/时段/数值expected不变 |
| test_stk_mins_silver_m5e_job_contracts.py | job selection解析 | collection保护；连接/写文件为0，selection不变 |
| test_stk_mins_lake_readiness.py | 默认资源和裸duckdb.connect并存 | R/C/N；保留批量日期、SQL计数与阻断原因 |
| test_stk_mins_silver_m6_history.py | fixture:51默认资源、历史writer/补录helper | R/C；事件用原替身或显式临时instance，文件选择与恢复语义不变 |
| test_stk_mins_silver_replace_from_raw.py | setUp:37默认资源、恢复writer | R/C；临时候选/指纹/checkpoint；CLI参数、退出码、幂等不变 |
| test_stk_mins_bse_history_recovery.py | fixture:85裸连接、setUp:158默认资源、现行CLI | R/C/N；保留源替身、BSE/fallback与CLI拒绝项 |
| test_stk_mins_silver_strict_audit.py | 多个裸连接fixture与审计器连接 | N/C；临时输入/报告；保留全部停复牌代码的诊断语义 |
| test_stock_mins_daily_continuity_sensors.py | _DuckDBResource:123裸连接、sensor patch | N；保留源/实例替身，窗口与run key不变 |
| test_stk_mins_silver_m6g_sensor_contracts.py | 就绪/实例替身、sensor选择 | collection保护；无真实资源，窗口/run key不变 |
| test_asset_check_incremental_governance.py | 遍历导入checks/sensors、catalog | 保护全部发现模块；import期连接/写入拒绝，不缩小发现集合 |
| test_asset_governance_contracts.py | 全模块发现/catalog对账 | 同上；外部AssetSpec完整纳管，不为通过而排除 |
| test_run_contract_static_gates.py | 源码/metadata门禁 | 仓库只读；补唯一读取方、日期校验及受限连接策略门禁 |
| test_duckdb_connection.py | 真实统一连接的显式settings、资源委托spy | 独立连接合同suite，不替换被测函数；临时路径；保留原1GB内存/1GB spill参数测试，默认正式路径仅静态/spy断言，不实际连接 |
| root-guard → 根tests/architecture/test_lake_console_retirement_guardrails.py | 纯源码路径护栏 | runner唯一固定根测试映射；只读；S5前CSV断言保持，S5才换锚点 |

行号为2026-09-07静态定位，不是执行证据。C类绑定至少覆盖resources、suspend_d_checks、stock_daily_checks、assets/suspend_d、assets/stock_daily、assets/stk_mins及对应bootstrap/asset_guards/audits链。按当前实际import绑定核定，不按函数名猜测；仅修测试资源，不授权修改保留的业务模块。

预算分阶段：§18的32行/1MiB只约束隔离和小型adapter事实，不套到既有分钟回归。regression保留原fixture业务规模，一个suite一个受限进程、连接串行、默认512MB/2线程/0spill；连接合同suite仅允许上表原显式1GB设置。每批≤16case、单case30秒/单批60秒、工作区100MiB为初始停止上界；启动前从实际fixture列出日期/代码/行数上限，超出先拆批或补预算依据，不删样本/改expected。suite累计耗时单列，不把整套回归要求压成60秒。

## 11. 实施、发布与删除顺序

沿用技术方案 S0–S5，不新增一套编号；每阶段独立验收，不自动跨过高风险步骤。

| 阶段 / 风险 | 明确产出与顺序 | 进入下一步的条件 |
| --- | --- | --- |
| S0 / 低，已完成 | LLD 已认可；来源/日历/文件集合已刷新；批准 hash 已实算；隔离验证设计已固定 | 来源一致，见 S0 清单；后续已取得 S1 开发及本地维护安排授权 |
| S1 / 中，隔离、C/D及SQL核心小样本已验收；余项未完成 | §18独立隔离→合同分类/两个checks验收→§10.4全部合成/消费者/连接回归及原S1剩余实现 | 只证明隔离与实现机制；生产C01/C05明确待S2，不能声称全合同已验收；不自动重载/恢复入口 |
| S2 / 中 | 获准准备staging后，使用未修改的生产合同完成C01/C05，再冻结plan并全既有日期分批比较 | 生产批准集合与全范围EXCEPT ALL均通过，输入未漂移；任一未过禁止S3 |
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
| 日常新增固定读取 | writer、各check、非空候选sensor每次各至多1次完整行解码；每份inspection最多1次DESCRIBE/1次行数聚合。头信息、解码、hash分别计数，无跨进程cache |
| 日常固定事件查询 | sensor 每 tick 最多 1 mat＋2 check；latest limit=1；无候选为 0。已确认 §15.3：每个固定 check 显式查 mat 至多 1 次，即每 job 至多 2 次；不在 writer/SQL 增加事件查询 |
| 全范围比较 | 前序基线两层各 3,083 文件，实施用 S0 精确清单；按年且≤366 日期/批；每批一次固定加载，显式 Raw/Silver 文件列表 |
| 人工固定发布 | 最多 1 正式新文件；初次事件最多 3 条；无历史日期事件补录 |
| S4 验收 | 4 个不同类型日期，实际精确日期在 S2 后审定；每日期单独候选/检查；不重抓 Raw |
| 内存/空间 | 日常默认不变，固定关系增量预期远低于512MiB；专项CLI按§8.2A强制0spill。固定文件估算<1MiB、异常文件拒绝上界100MiB、准备报告100MiB分别登记；测试预算见§10.4/§18，不能互相代替 |
| 日常开销 | 新增计算/读取目标约1秒，须分别计 writer、checks、sensor；不是本轮实测结论 |
| 全范围耗时 | 分钟级目标；超过5分钟输出慢阶段/已完成批次，人工复核，不用严苛倍率跳过正确性 |

writer首次非等价写入的Raw/固定文件各4轮物理hash：加载后、prepared前、prepared落盘后紧邻提升前、提交后。后两次用于识别checkpoint落盘窗口漂移及“文件已提交但输入已变”，仍不重新解码输入；等价reuse各2轮。候选正常3轮hash（读回、prepared前/后），已有目标等价比较1轮、提升后的目标1轮；reuse目标另复核1轮。恢复路径按§5.2计数，不与首次合并混算。hash不替代跨SQL身份绑定，mtime不是内容唯一证明；新增的是字节读取，不新增源请求、进程cache或备份，所有字节IO不藏在“一次行解码”预算中。

进度以每批实际完成量、日期批、文件数、差异数、耗时输出。发布只有一个文件，不建 ETA/进度数据库；长批比较至少每完成一批报告，单批异常慢时报告阶段而不虚构完成量。

硬拒绝项是多源请求、超出批准文件清单、错误根、无界循环、错误写入/事件、数据不等价。轻微耗时偏慢不改变业务标准，也不顺手调全局资源。

S0 实测已落清单：主审计 3,024 ms，15 次有界 DuckDB 调用、13 个年度批次，两层各 3,083 文件；真实逻辑 hash 见 §3.3。配置 512 MB/2 threads、禁止 spill，未测峰值 RSS。S1/S2 的候选物理 hash、新 helper 全范围差异、writer/check/sensor 开销、测试及内存证据仍待执行；不得把 S0 耗时或前序约0.4秒的审计当新链路性能。

## 13. 测试和验收用例矩阵

### C：固定合同

| 编号 | 正/反向用例 | 必须结果 |
| --- | --- | --- |
| C01（生产，S2） | 正确五列、真实4,022行批准集合；生产常量未修改 | schema/content通过、真实摘要匹配；S1两行机制测试不计此项 |
| C02 | 少/多列、错序、DATE改VARCHAR、timing全NULL但物理类型错 | 失败，不 cast掩盖 |
| C03 | 空文件、缺文件、损坏、NULL键、重复键、未知模式、空串时段 | 失败，最多20样本，无写入 |
| C04 | 同行换序/换压缩、改单个值/模式 | 前者逻辑hash不变，后者失败；金样本bytes/hash固定 |
| C05（生产，S2） | 获准候选加载为TEMP TABLE后，保持4,022计数换键/扩大覆盖键，不改候选文件 | 未修改的生产validator拒绝；schema不因内容错误失败，不能靠计数自证 |
| C06 | 候选/目标symlink、`..`、跨设备、挂载缺失、错误根 | 拒绝，不能在系统盘建目录 |
| C07 | 修改文件但沿用旧 metadata/hash | 实际内容检验失败；无进程cache续用 |
| C08（S1机制） | synthetic批准2行，分别变0/1/3行、同计数换键、错schema | schema正确时通过、content失败；超synthetic行数上界不解码；不冒充C01/C05 |
| C09（S1机制） | 缺文件、损坏头、超文件预算、inspection后换文件、解码IO错误 | 预期前置/IO/漂移失败，无假绿；COPY/replace为0 |

### M：独立合并金样本

SQL 核心小轮先完成 M01–M06/M08/M09 的纯关系断言；M02 原正式 check 执行、M03 writer 拒绝且目标不变、M07 文件重建、M08 文件日期错放拒绝，必须等 writer 和相应资源矩阵落地后实际运行，不能用纯 SQL 冒充这些验收。原S1的固定 regression suite 首次只开放 `test_stock_suspend_confirmed_merge.py`，逐批穷举该文件当前全部 case；后续新增 W case 时同步批次计数。

本小轮开工预算：每例至多32行 normalized、32行 confirmed、14个日期（14条既有时段修正的纯关系样本）；零 API/分页、零 Parquet 扫描或输出、零 instance/event、零 replace/checkpoint。三张内存 TEMP TABLE，SQL集合式join/count；仅字面小样本读回完整行，冲突/分类样本≤20。复用既有512MB/2线程/0spill、fixture≤1MiB、单批≤16例/60秒、单例30秒和工作区100MiB门禁，预计每批不足10秒，超限停止保留证据。

精确新增只读源码白名单（均相对 `src/orchestrator/`）：`defs/duckdb_sql.py`、`defs/corrections/__init__.py`、`defs/corrections/suspend_full_day.py`、`defs/corrections/suspend_timing.py`、`defs/stock_suspend_confirmed_contract.py`、`defs/run_contracts/asset_column_schemas.py`、`defs/run_contracts/column_schema.py`。后3项已在adapter登记。旧范围模块只是 `duckdb_sql` 的现存静态import，不运行其函数，不放行CSV；不放行整个源码目录、正式路径或网络。N类连接使用现有support工厂，默认正式连接保持拒绝，不新增C类绑定或实例工厂。

执行目录仍为 orchestrator，完整父入口：`/opt/homebrew/bin/uv --no-cache run --offline --no-sync --no-env-file --no-config --no-python-downloads .venv/bin/python -I -B -S tests/stock_suspend_confirmed_test_runner.py --scope regression --suite test_stock_suspend_confirmed_merge.py`。子进程继续使用§18.19同一OS模板、精确文件白名单和env限制；只写各自 `/private/tmp/stock-suspend-isolated-*/allowed`，逐次精确根与argv在报告中登记，最终按§18.11清理，不在本轮删除现场。

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

expected 必须是手写字面行，不调用被测 helper 生成 expected。C01/C05生产验收放在S2，和S1机制样本分开。S1 support只允许明确标记的synthetic用例暂换测试批准身份，case结束恢复，报告标注identity_profile=synthetic；生产常量未改的小样本拒绝/编码测试仍保留，但不是生产正例。M组只测纯关系算法，不给生产validator增加跳过hash参数。需要实际固定validator的S1 D/W/B/E/R正例也使用同一显式synthetic fixture，生产代码不识别该标记、不增加测试开关。超100MiB前置反例使用受控文件身份/大小替身验证拒绝分支，不生成超工作区预算的文件；真实stat取值与小文件路径另测。

S2用已获准候选执行C01/C05及完整schema验证，变体只在TEMP TABLE中，不复制正式Raw/Silver、不改候选/批准常量；将生产验收前移S1须另行明确数据范围授权，当前不执行。

### W/B/E：文件、CLI 和事件故障注入

writer 小轮范围与预算（2026-09-07，开工约束）：同轮替换唯一公开 SQL 接口及 `assets/suspend_d.py` 的唯一调用方，Raw 函数/请求、14条时段修正、其他 SQL 与最终三个 checks 不变；job/readiness/人工工具与正式发布仍属后续验收。S1 每例固定事实2行 synthetic、Raw≤32行、仅1个日期、输出≤33行；每文件≤1MiB、单批≤16例/60秒，沿用单例30秒、工作区100MiB和受限 DuckDB。正常非等价路径固定/Raw各一次行解码、输出TEMP一次构造、候选一次完整读回；如已有目标，至多一次等价读回；提升后目标一次完整读回。输入/候选的阶段 hash 为字节读取而非重复行解码，计入报告耗时与文件预算。零API/分页、零instance/event、零正式Lake操作、零安装；每次只提升一个临时日期目标。

新增测试入口固定为 `test_stock_suspend_confirmed_writer.py`。精确补入只读源码：`defs/assets/suspend_d.py`、`defs/assets/__init__.py`、`defs/partitions.py`、`defs/tushare_api_io.py`、`utils/__init__.py`、`utils/dg_log_helper.py`及已核验 adapter/resource 闭包；删除 SQL 已不再引用的 `defs/corrections/suspend_full_day.py` 权限。只调用实际内部 writer、显式临时连接/Lake/staging；不放开默认连接、不调用真实 asset job、不新增SDK实例，不放行CSV/源码目录/网络/正式路径。原三个 checks 的实际执行与完整D组仍待下一轮，不以本轮关系/文件测试代替。

| 编号 | 用例 | 必须结果 |
| --- | --- | --- |
| W01 | COPY失败、候选不完整、EXCEPT ALL非零 | 原正式Silver字节不变，无replace |
| W02 | prepared后replace前退出、replace后checkpoint前退出；已提升但输入后来改变 | 先认定上次提交；输入一致才返回冻结统计，漂移时保留文件并失败，replace为0 |
| W03 | 输入/目标漂移、candidate丢失、跨run等价 | 未提交候选遇漂移停止；等价reuse；不删现场 |
| W04 | Raw或固定文件在SQL后/hash前替换，或hash后/提升前改写 | 拒绝，不能生成“旧结果＋新输入hash”的prepared |
| W05 | checkpoint缺字段/损坏/统计缺失、committed目标不匹配、checkpoint落盘失败 | 保留现场，不兼容草稿、不覆盖后来目标；metadata取冻结的同版本结果 |
| B01 | 五命令参数矩阵；无参数/无确认/错误hash | 不写文件/event、不构造无关instance，不改stk_mins CLI |
| B02 | 全部只读分支，从初始化到退出；save-report显式写入 | mkdir/COPY/replace/checkpoint/event写入为0；比较内容/集合/mtime，不以atime当写入；仅save-report写批准报告 |
| B03 | 正式固定目标absent/equal/different/broken | publish/reuse/refuse/refuse，绝不自动覆盖不同内容 |
| B04 | 全日期/年度边界、漏配对日期、1个差异或输入变化 | 批次有界、范围不可缩小跳过、差异阻止发布 |
| B05 | 文件发布API参数签名与调用spy | Raw/Prod/其他Silver/event调用数为0 |
| B06 | 受限连接temp已存在/缺失/非目录；未知策略、设置读回不符、内存不足 | 正常只读或明确失败；不mkdir、不切回默认/放宽配置；默认分支合同保持 |
| B07 | 事件CLI实例错身份、构造试图mkdir/DDL、无确认登记 | 无写入；构造阶段也验收，不只spy最终report_runless调用 |
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
- P01：物理schema查询、行数聚合、完整行解码分项计数，inspection/loader共用身份，每消费者至多一次行解码；事件/SQL批次按§12。两轮输入hash及读回字节IO单列，不误报metadata查询为全表重解码。
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

S0 已完成，没有新增业务数据范围；§15.3 框架窄修正已确认，§17事故后又发生§18.7隔离启动失败，尚无安全恢复实施的验收证据；不是业务方向仍待拍板。当前进展及剩余项：

1. S0：真实展开逻辑 hash、源/日历/Raw/Silver 清单身份和当前部署边界均已刷新，见 S0 清单。
2. S1：已有部分固定合同/AssetSpec/check/catalog 代码；首轮 adapter 测试越界，未验收。2026-09-07只修订六项设计缺口；隔离、合同分类、adapter及回归尚未完成。§15 的 5 项机制实验不等于实际 adapter 验收。
3. S2–S5：staging 准备、文件发布、事件登记、本地切换、精确删除均未执行；不能合并成一次默许授权。

S0 增加了真实物理只读核验和现有运行状态核验，但没有执行新代码测试或正式迁移验收。后续执行记录须在对应阶段补齐，缺一项不能标记本专项完成。

2026-09-06 首轮文档验收记录（历史）：`scripts/check_docs_integrity.py` 通过；本技术方案及 LLD 合计 23 个本地链接/显式锚点有效；本 LLD §10.1 的 27 个现有源码路径及 §10.3 的 13 个消费者回归测试路径均存在；代码围栏、已跟踪文档及两份新增文档的空白检查通过。该文档轮未执行任何业务测试或正式 Dagster 操作；之后 S1 的唯一正式状态修改及隔离测试见下节。

<a id="audit-fixes-20260907"></a>

### 14.1 2026-09-07 六项审计修订对账（只改文档）

用户确认先按审计修正LLD；本表是review入口，执行细节已改入正文，不能只读本表实施。业务方向不变：Raw/最终四列/本地消费者不变；既定两文件仍在S5最后获准删除，14条时段修正保留。

| 审计问题 / 风险 | 代码事实与修订位置 | 必须证据 / 当前状态 |
| --- | --- | --- |
| 回归隔离漏覆盖 / 高 | test_suspend_d_checks默认资源及check直接统一连接；§10.4全23项资源矩阵、§18分阶段入口 | collection先保护；R/C/N三类连接全覆盖、默认路径拒绝；待实施/验收 |
| 只读CLI初始化副作用 / 高 | connect_configured_duckdb原mkdir；§7/§8.2A精确资源矩阵及显式受限策略，§10增连接文件与合同测试 | B01/B02/B06/B07，全链零写入与默认分支不变；实例构造还须实测，无提前通过 |
| 日常错放日期无校验落点 / 高 | Raw check不在Silver-only job；Silver分区check不读行内日期；§4/§5明确Raw关系日期聚合校验 | M08＋绕sensor的writer反例，COPY/replace=0；未判定正式数据有错 |
| 生产批准集合被小样本替代 / 中 | approved_sample改计数/hash；§11/§13/§18划清S1 synthetic与S2 C01/C05 | S2未修改生产合同的正例/等计数反例；当前未运行，不以S1绿灯代替 |
| 输入指纹/续跑不够精确 / 中 | hash函数只保护自身读取；§5补跨SQL身份/hash时序、checkpoint统计和恢复优先级 | W02–W05故障注入；已提交不重复覆盖，输入变化不冒充当前ready；待实施 |
| schema与content混淆 / 中 | 草稿loader提前拒绝超行数；§4.1 inspection分工、§18.2合同修改白名单、§18.4错误分类 | C08/C09与D07：字段对但计数错时分别报告，资源/IO异常不伪造校验；待实施 |

本轮CodeGraph explore/impact覆盖统一连接、资源及其跨资产消费者；结合当前源码与AST核对直接导入调用。2026-09-07静态结果：src/orchestrator内58文件有220处可解析的直接命名调用，209处无参数、11处传一个settings位置参数；该计数不包括测试或未解析动态调用，不能当运行调用次数。新增策略是keyword-only，所有既有调用仍走managed；实现前仍须核对完整别名/动态入口并保留默认合同，不按图的返回上限断言无漏边。

本次修改白名单仅本文、技术方案及主索引的状态/导航。未修改源码、测试、AGENTS、全局配置、架构/依赖矩阵，未重跑隔离或业务测试、未操作正式文件/实例/调度、未提交。文档校验只能证明链接/结构，不是安全验收。

本次静态校验：仓库文档完整性、git diff --check通过；两份方案32个仓库内链接（含目录/行号/显式锚点）、代码围栏及23项suite矩阵检查通过，2项尚未创建的测试已明确标为新增。内容hash对账确认仅上述3份文档变化，其余12份原有未提交文件未变；没有新增文件。未运行业务import、pytest或Dagster验证。

仍未证明的条件：§18.7解释器启动拒绝原因与OS隔离能力；§8.2A实例构造只读边界；以及所有尚未实施的业务测试和S2真实验收。没有新增待用户选择的业务规则，但也没有因本次修文档取得执行这些步骤的权限。下一实施步骤先定位并验证隔离启动条件，按独立停止点报告；不直接跳入adapter或数据迁移。

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
4. 不改变两个 check 名称、绑定 AssetKey、无分区合同、一 writer 五 checks 集合或执行顺序；原三个最终checks业务判断和自动target关联不变，仅按随后确认的§18.22补齐其已有交易日分区声明。不升级/修改SDK、不在生产代码monkeypatch、不新增分区、额外job、sensor或配置。
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

## 16. S1 窄修正确认后的执行清单（历史授权记录）

保留当时执行前口径；2026-09-07修订后的合同分类、C01/C05阶段及资源覆盖以§4/§10/§13/§18为准，不能沿用本表推导所有C项都在S1完成。

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

## 18. 测试隔离与新检查安全修正 LLD（隔离及实际adapter小样本通过）

### 18.1 范围、事实依据与本轮停止点

这是H13的实施补充，不是新的数据治理专项。2026-09-07按审计修订顺序为：**修订LLD → 隔离独立验收 → 合同检查分类及两个新checks独立验收 → 原S1剩余实现和全部受限回归**。合同分类是本次明确补入的代码落点，不在下一轮临场增加；当前用户指令仅修文档，不运行下列步骤。本节设计轮只改本文、技术方案和主索引，没有改 Python、依赖、AGENTS、正式状态或数据。其后用户单独要求提交文档，形成 `f003a3c5`，再要求继续推进；本次执行结果独立记在 §18.7。下面的文件和接口仍为待实施；2026-09-07修订的合同分工和资源覆盖不改写历史记录，不能因文档已提交或尝试过能力预检就标记隔离已建立。

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
| `src/orchestrator/defs/checks/stock_suspend_confirmed_checks.py` | 首行写探针；两checks共用loader行数拒绝 | §18.4取消探针，按§4.1 inspection区分字段/内容/资源失败；补阶段/原因，保留名称、ERROR blocking、target、无分区及查询上限 |
| `tests/test_stock_suspend_confirmed_contracts.py` | fixture仅拦instance/socket，synthetic fixture修改批准常量 | import前保护；fixture移support；C08/C09及原编码/拒绝测试；synthetic标记明确，不把生产C01/C05算作通过，不新增生产跳过hash接口 |
| `tests/test_stock_suspend_confirmed_dagster.py` | 已改正参数名，但未断言资源实际根；从另一测试文件 import fixture | 同样先断言受限上下文，再 import 业务；用 support 工厂构造真实 `LakeRootResource` 并核对最终根；按 §18.5 验证真实成功与失败，不仅断言 `success=False` |
| `src/orchestrator/defs/resources.py`、`defs/health/lake_root.py`、`defs/duckdb_connection.py` | 全局共享，有其他现行消费者 | 隔离/adapter小轮不改；全局默认值始终保持。原S1后段才按§8.2A修改统一连接显式策略并独立验收，不扩大暂停或修改其他资产 |
| `src/orchestrator/defs/stock_suspend_confirmed_contract.py` | loader先按批准行数拒绝，导致schema误失败 | I组通过后同checks重构§4.1 inspection/加载接口和唯一schema比较；列全checks、测试以及未来writer/readiness/bootstrap调用方，统一新签名，无兼容wrapper；不改五列/批准常量 |
| catalog/schema/paths/metadata的已有部分实现 | 未整体验收 | 本小轮不扩写；保持现有字段/路径/身份，失败描述用现有extra metadata结构；后续原S1按矩阵完成 |
| 原 `assets/suspend_d.py`、SQL、job、sensor、readiness、bootstrap、分钟 CLI/消费者、CSV/timing | 现行链/后续 S1 工作 | **本安全修正轮不改**，不得混入 writer 迁移、CLI 实现或旧文件删除 |

### 18.3 测试启动、文件隔离与资源构造

#### A. 先隔离进程，再加载业务模块

单靠 `tmp_path` 或 Python monkeypatch 不足以阻止 DuckDB/SQLite 原生文件访问。专项 runner 必须在 pytest/业务模块导入前，为子进程建立操作系统级文件与网络限制；Python 拦截只负责早报错和计数，不能作为唯一防护。

本机已只读确认存在 `/usr/bin/sandbox-exec`，其本地手册 `/usr/share/man/man1/sandbox-exec.1` 支持 `-f/-p/-D`，同时明确标为 **DEPRECATED**。因此本方案仅把它用于当前 macOS 的专项测试子进程，不进入正式产品或修改系统全局配置。**命令存在不等于限制有效**：第一项是对虚构目录做 I01/I02 能力验证；不支持、策略加载失败或底层 IO 未被阻止就停止，不降级为无保护 pytest，也不自行改用新容器、机器或依赖。策略正文和精确启动 argv 在执行前展示，只允许本节范围。设计时尚未运行策略；后续首次启动失败记录见 §18.7，不能据此认定隔离可用或系统机制本身不可用。

runner 单次创建一个新的 `/private/tmp/stock-suspend-isolated-<随机串>/`，不复用前次 pytest 目录；内部为 `allowed/` 与 `denied-fixture/` 两个兄弟目录。`allowed/` 内固定放 Lake、staging、DuckDB temp、SQLite instance、pytest 临时区和报告；`denied-fixture/` 仅由无业务导入的父 runner 写入小型虚构样本，之后受限子进程不可读写。结束保留精确路径供 review，不递归清理其他运行目录。

受限子进程策略必须满足：

1. 持久文件写入只允许本次 `allowed/`；仓库、虚拟环境、用户目录、正式 Lake/staging 均不可写。标准输出/错误等进程运行所需非业务通道单列，不用宽泛目录例外放开。
2. 正式 `/Volumes`、用户正式 Dagster home、正式凭据/配置和本次 `denied-fixture/` 不可读取；规则按规范化真实路径生效，不能被符号链接、`..`、`/tmp` 别名或打开文件描述符绕过。拒绝把正式数据复制到临时目录作为 fixture。
3. 禁止网络连接及本地数据库 Unix socket；不加载 token、数据库 DSN 或正式 instance 配置。子进程关闭不必要继承 FD，不给它父进程已打开的业务文件。
4. 不设置或覆盖 `HOME`、`CODEX_HOME`，不修改 shell 配置；以受控子进程环境移除 `DAGSTER_HOME`、连接凭据、`PYTHONPATH`、外部 pytest 插件参数等继承项。临时目录和报告参数仅作用于当前子进程。
5. pytest 关闭自动插件和缓存，不加载仓库 conftest；显式使用 `-c /dev/null --noconftest -p no:cacheprovider`，只额外加载本专项 support 插件。插件在业务测试 collection 前安装保护；autouse fixture 不能作为保护开始的最早时点。
6. support 发现不是本次受限运行上下文时，在导入业务测试之前报错；runner 不接受任意命令、文件路径或额外 pytest 参数透传。直接运行现有两份专项测试不得静默跳过保护。

support 顶层只加载标准库与 pytest，不在保护安装之前 import Dagster、DuckDB 或 orchestrator；资源工厂在通过当前受限上下文断言后才延迟导入实际类。I 组自身使用单独的虚构 collection 样例检验这一顺序，不能为了验证保护先收集尚未修正的两份业务测试。

本小轮runner只开放 `--scope isolation` / `--scope adapter`，无默认连续执行；原S1恢复后才按§10.4增加固定regression suite，不用额外pytest参数绕过阶段。`isolation` 完成后退出并报告，人工 review 通过才进入 `adapter`；进入 adapter 时先在同一限制下重新做小型隔离自检，不能仅信任上次报告或一个环境变量。解释器使用当前 orchestrator 项目的现有 `.venv`，不安装依赖、不设置 `PYTHONPATH`，不调用 `dg` 来启动测试；父 runner 不构造 Lake/DuckDB/Dagster 资源。

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
5. 发布身份通过后才打开传入的 DuckDB 资源，调用§4.1 inspection和重构后的loader/schema/content分支；不跳过批准hash、不修改事实来通过检查。schema正确而计数不符时必须是schema通过/content失败，不再由共同loader把两者一起判红。按已确认 §15.3 记录真实 target，仍是当前 run 的 ERROR blocking check。

在adapter已有失败metadata中记录failure_stage与具体reason，不新增业务数据字段：

| 失败时点 | stage / 处理 |
| --- | --- |
| 根/路径/普通文件前置失败，包括FileNotFoundError/权限OSError | input_path；后续instance/连接/writer均0 |
| 无mat、partition/URI/version/hash不符 | publication；不解码，不伪造target |
| 单文件超既有100MiB阈值、受限连接资源不足 | input_resource；不包装成schema不符，不扩大资源重试 |
| schema或批准内容不符 | validation；分别使用真实ValidationResult和§4.1分类，原生ERROR blocking |
| inspection/加载/哈希期间文件消失或变动、Parquet读取失败 | validation；区分input_disappeared/input_drift/parquet_read_error，保留异常原因，不能转成空表或“发布缺失” |
| event存储异常 | 原异常继续失败；读回验证无伪造成功，不补runless、不掩盖成文件校验失败 |

只捕获上述已经识别的文件/读取/预算异常并转换为可解释Failure；编程错误不得用宽泛except包装成预期业务拒绝。schema检查的失败计数和内容检查分别来自实际校验；前置异常没有完整校验结果时不能伪造checked_rows。

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

I组验收后，adapter只运行§13列明的S1编码/拒绝和C08/C09机制测试及以下D06/D07；调用真实合同实现，但小型批准身份是synthetic，不计生产C01/C05。先静态确认两份业务测试在业务 import 前要求受限上下文、两个新 checks 不再调用健康 helper，再以 spy 证明实际运行探针调用数为 0。`daily` 仍是只修改临时哨兵的替身，避免这一轮提前运行正式 Silver writer；因此不能用本轮结果替代 D05 或完整 writer 验收。

| 输入 / 故障 | 必须到达的阶段与结果 | 禁止的假通过 |
| --- | --- | --- |
| 正确synthetic fixture＋同身份临时发布 | 实际两checks通过，target与临时发布相同；下游哨兵一次，合计5checks | 读回partition/run/storage_id/timestamp并标记synthetic；不能冒充生产集合/真实writer验收 |
| 缺根/缺文件/非普通文件/路径越界 | `input_path` 明确原因；无事件查询、无解码、无下游写 | 不能因发布 metadata 错误而通过缺文件测试 |
| 无发布、有日期发布、错误 URI/version/hash | `publication` 拒绝；spy 证明检查到对应错误；不打开 DuckDB、不调用下游 | 不能被健康检查、临时目录缺失等提前失败替代 |
| 五列正确但内容错误 | 同计数换键进入validator，schema通过/content失败、实际digest非批准值；0/少/超行数按§4.1分别验收，超行数digest留空且不解码；下游不执行 | 必须读回真实content失败，不能用任意失败、批准常量或假schema失败充数 |
| schema错误/Parquet损坏 | 进入实际inspection或loader，区分字段不符与parquet_read_error；无下游写 | 不因发布记录或健康探针提前失败而充数 |
| check event 存储抛错 | 先证明已执行实际校验，再注入特定存储异常；writer 不执行，读回无伪造成功记录 | 不能使用不存在的事件属性导致 setup 失败，也不能吞异常补 runless 绿灯 |

每例同时保存：输入变体、阶段/原因、执行/未执行调用计数、run id、实际 check event 摘要和临时哨兵前后身份。禁止只凭“作业失败”或 planned 事件计数验收；正向失败时整阶段失败。

### 18.6 执行门、预算与交付

| 顺序 | 允许内容 | 完成条件与停止点 |
| --- | --- | --- |
| 1，设计轮（已完成并按另行指令提交） | 只补原 LLD/技术方案/索引，静态核对源码及文档 | 没有任何代码/测试已获验收的含义 |
| 2，review 后 | 只实现 §18.2 的隔离启动器/support/I测试，先做虚构目录能力验证 | I01–I08 逐项通过、留真实证据；报告后停，不在同一命令中串联 adapter |
| 3，隔离验收后 | 仅§18.2合同分类、两个新checks及C/D测试；synthetic小样本明确标记 | C08/C09、D06/D07正反证据完整；生产C01/C05待S2；报告后再继续原S1 |
| 4，原S1 | 按§10/§13继续merge/writer/readiness/CLI、受限连接策略及§10.4全部回归 | 测试与资源矩阵完整对账；不把C01/C05提前计通过；不自动进入S2、恢复sensor、重载或提交 |

隔离/adapter安全验收规模：synthetic事实通常2行、最多32行（相应批准身份只在测试case内）；一个日期/每 case 独立临时实例，单连接512MB/2线程/0 spill；不读取 S0 的6,166个实际文件、不发源请求。每批最多16个 case，小型 fixture 总量上限1MiB；报告只存摘要，单批工作区预算100MiB。每 case 超过30秒、单批超过60秒或空间超预算就停止该批并保留临时证据；超时不是业务失败样例的成功。超时管理仅针对 runner 自己的子进程，不杀正式服务或其他任务。

原S1消费者/连接合同回归预算见§10.4，S2真实4,022行候选验收见§13；不能用本小轮32行限制替代或跳过后两者。

执行前给出工作目录、现有解释器、完整argv、允许写目录、禁止目录、测试清单和影响；不把上述设计参数当成已经通过的实测。每批报告启动/当前 case/实际完成数/耗时，不创建新进度库、锁或自动重试任务。

交付必须分别标注文档检查、隔离、实际adapter、S1实现/合成回归、S2生产批准集合、S2全范围等价六类状态，分别附证据；S1完成不代表生产C01/C05已过，也不代表可发布。任何库、进程边界或环境能力不符合本节时停止并回修原文；不能在执行时临场放开目录、网络或绕过防护。

设计轮结果（历史）：当时只完成静态设计，三个拟新增测试支持文件尚未创建，OS 隔离能力未运行验证，I/C/D 未重跑；正式数据/事件/调度不因该设计轮发生变化。后续执行状态以 §18.7 为准。

设计轮文档验收（历史）：已阅读文档校验脚本，其只检查仓库文档引用/索引；当轮执行该检查及 `git diff --check` 均通过。另对技术方案与 LLD 的30个本地链接/显式锚点、围栏和空白做静态核验，无问题。工作区内容哈希对账确认当轮只变更本文、技术方案及 `docs/README.md`；既有未提交 Python 和其他文档未改。以上不是 OS/I/D 测试证据。

<a id="s1-isolation-capability-blocked"></a>
### 18.7 首次隔离启动预检：未进入用例，按门禁停止

执行时间：2026-09-06 23:10:38（北京时间）。起点为 `dev-interface@f003a3c5` 加原有未提交文件。用户要求继续推进后，只尝试 §18.6 第2步的首个虚构目录能力预检；没有进入业务修改阶段。CodeGraph `status/explore` 复核了资源根、健康 helper 和默认 DuckDB 连接链；图中健康入口还有其他现行消费者，因此本轮不改共享资源、默认值或健康函数。

**结果是启动阻塞，不是 I01 通过，也不是数据损坏。** 外层命令返回 `134`，耗时140毫秒，未超时，stdout/stderr 均为空。子脚本应在任何测试文件操作之前输出的 `child_started` 标记没有出现。对应系统诊断记录为 Python 进程 `42831` 的 `SIGABRT`，故障栈位于 `dyld` 的 `ignition_halt/boot_boot` 启动阶段。尚不能确定具体被拒绝的资源或启动条件，也不能把原因写成“sandbox-exec 不支持”或“Python 业务代码有错”。

#### A. 本次执行的精确范围

- 一次独立目录：`/private/tmp/stock-suspend-isolated-ixxBAyLw/`；只创建 `allowed/` 与 `denied-fixture/` 内的小型审计文件，保留现场，不清理其他目录。
- 无业务导入的 Node 标准库父进程启动现有 `uv`；子进程使用当前项目 `.venv/bin/python`，未安装或更新依赖。该解释器原有链接指向 `/Users/congming/miniconda3/bin/python3`，不是切换到另一套环境。
- 父进程为子进程仅提供 `PATH/LANG/TMPDIR`，不注入 `HOME/CODEX_HOME/DAGSTER_HOME/PYTHONPATH` 或凭据；标准输入关闭、输出接管，不传业务文件描述符。`uv` 禁网、禁同步、禁 `.env` 加载，缓存位置在本次 `allowed/`。
- 测试脚本只导入 Python 标准库；`-I -B -S` 禁止从用户环境加载模块、写字节码和执行 site 初始化。计划的正向读写与9种拒绝操作均只面向虚构目录，没有针对正式路径做读写探测。
- 策略默认拒绝文件读写及网络，仅放行系统/解释器所需读取、明确设备例外及本次 `allowed/` 的文件读写。该策略只用于能力预检，尚未证明足以安全运行 pytest 或原生数据库库。

工作目录：`/Users/congming/github/goldenshare/lake_console/orchestrator`。完整 argv：

```text
/opt/homebrew/bin/uv run --offline --no-sync --no-env-file --no-config --no-python-downloads --cache-dir /private/tmp/stock-suspend-isolated-ixxBAyLw/allowed/uv-cache /usr/bin/sandbox-exec -f /private/tmp/stock-suspend-isolated-ixxBAyLw/allowed/capability.sb /Users/congming/github/goldenshare/lake_console/orchestrator/.venv/bin/python -I -B -S /private/tmp/stock-suspend-isolated-ixxBAyLw/allowed/capability_probe.py
```

#### B. 可复核证据与边界

| 证据 | 实际结果 |
| --- | --- |
| [启动报告](/private/tmp/stock-suspend-isolated-ixxBAyLw/allowed/capability-result.json) | 保存 argv、策略哈希、环境变量名清单、耗时、退出码、输出和虚构哨兵前后身份；无凭据 |
| [策略正文](/private/tmp/stock-suspend-isolated-ixxBAyLw/allowed/capability.sb) / [预检脚本](/private/tmp/stock-suspend-isolated-ixxBAyLw/allowed/capability_probe.py) | 策略 SHA256：`b17b51cd44a19f226634ad762de0093a9ee2c8d744f191f45fe33756919960cc`；没有业务模块导入 |
| 虚构禁止目录 | 前后均只有 `sentinel.txt`，24字节；SHA256 `b14c3e61ade8760c6ea5e018fb8fe7ef90e54eb794b758c78aa7c1766076e40c`、inode `99123842` 和 mtime 一致。哨兵不变不能代替拒绝用例通过 |
| 系统诊断 | 只读核对 `/Users/congming/Library/Logs/DiagnosticReports/python3.13-2026-09-06-231039.ips` 的时间、进程、异常及加载栈；系统生成了该非业务崩溃记录，不能声称整台机器只有临时目录发生文件变化 |
| I01 | 仅尝试启动；脚本启动标记未出现，正向用例及9种拒绝用例均未取得执行证据 |
| I02–I08、C/D、S1 | 未运行；三个拟新增隔离支持文件未创建，两个新 checks 和已有业务测试未修改，不能进入 adapter 或宣告 S1 完成 |
| 正式资源 | 本次未执行正式 Lake/staging 文件操作、Dagster instance 访问、源请求、数据库请求、事件发布或调度变更；不重做实际6,166文件审计，不自行恢复 Silver sensor |

临时路径用于当前机器 review，可能被系统后续清理；退出码、启动阶段、哈希和验收状态已记入本文，不能仅凭临时文件存在与否改变验收结论。它们也不作为后续 runner 的“曾经通过”标记。

#### C. 停止点与下一步

已按 §18.3/§18.6 停止：没有放宽目录或网络权限重试，没有绕过隔离运行 pytest，没有更换容器、机器或依赖。本轮仓库变更仅为本文、技术方案与主索引的状态和证据同步；没有提交或推送。

交付静态核验：文档完整性检查、`git diff --check` 及两份方案34个本地链接/显式锚点检查通过；带 `:行号` 的源码链接按文件路径和行号分别识别。13份原有未提交文件的内容哈希前后相同，包含既有专项 Python 和其他任务文档；依赖矩阵未改变。临时工作区占用28KiB。上述只证明文档与改动边界，不证明 OS 隔离或业务测试通过。

下一步先只读定位解释器的必要启动依赖与实际拒绝原因，给出最小修订策略及其读取边界，回写本节并交管理员确认；未知原因不能靠扩大允许目录来试错。确认后仍从新临时目录的 I01 开始，I01/I02 有真实正反证据后才可实施、验收其余隔离支持；原有独立验收停止点不变；后续业务修正范围以更新后的§18.2为准。2026-09-07本轮只修文档，未补做启动实验；必要启动依赖/拒绝原因仍须基于证据定位，不能宣称六项文档修订已经解决了启动问题。

<a id="s1-isolation-startup-diagnosis"></a>

### 18.8 只读定位结果：根目录打开失败；最小策略修订已获确认

2026-09-07，用户在文档提交 `a0361fc4` 后要求继续推进。本轮完成 §18.7 C 的只读诊断，没有重跑 sandbox/Python 子进程、pytest 或 Dagster，也没有修改三个待建隔离文件、既有业务代码或旧预检现场。以下更新不覆盖 §18.7 的历史证据。

#### A. 已定位到具体失败操作，不再只停留在“dyld 崩溃”

| 核验对象 | 本次证据与结论 |
| --- | --- |
| 崩溃二进制身份 | 旧 `.ips` 中 dyld UUID 为 `74e52480-c2bd-3c8d-812d-95fe2b74a096`；本机 `/usr/lib/dyld` 的 `LC_UUID` 完全相同，因此可以用当前二进制解释这份崩溃地址，不是拿另一版本猜测 |
| 精确返回位置 | 崩溃栈 `boot_boot + 228` 的 `imageOffset=557820`，即 `0x882fc`；本机 `_boot_boot` 起点 `0x88218`，相减恰为 228 |
| 失败分支 | `0x88254` 调用 `_open`，参数路径为 `/`、flags 为 `0x20100000`；返回负数才跳到 `0x882c4`。该分支使用错误文本 `failed to open root directory: %s: %d`，在 `0x882f8` 调用 `_ignition_halt`，返回地址恰为上述 `0x882fc` |
| 打开方式 | 本机 SDK `sys/fcntl.h` 定义：`O_RDONLY=0`、`O_DIRECTORY=0x00100000`、`O_NOFOLLOW_ANY=0x20000000`。因此是只读打开根目录、拒绝路径链接，不是创建/写入文件，也不是正式湖访问 |
| 原策略 | §18.7 保存的策略先拒绝 `file-read*`，读取例外只有系统库、解释器、项目环境、设备及本次 `allowed/`，没有精确路径 `/`；系统加载器所需的这次根目录打开未被允许 |
| 系统日志的证据限制 | 对 23:10:37–23:10:41 的有界日志查询只有崩溃收集记录；针对 sandboxd/dyld/deny 的紧邻窗口没有拒绝明细。因此不虚构该 syscall 的 errno 或一条不存在的 sandbox deny 日志 |

可复核的只读命令：

```text
/usr/bin/otool -l /usr/lib/dyld
/usr/bin/otool -arch arm64e -tvV /usr/lib/dyld
```

上表来自本机二进制与崩溃地址的逐项对应。Apple 公布的 [DyldProcessConfig.cpp](https://github.com/apple-oss-distributions/dyld/blob/main/dyld/DyldProcessConfig.cpp#L1031-L1112) 也显示 `CacheFinder` 调用 `ignite` 查找系统共享库缓存；公开源码仅作链路背景，不能替代本机 UUID/指令证据。

**结论：首个启动阻塞是隔离策略漏掉系统加载器只读打开根目录的需求，不是停牌业务代码已执行后报错。** 已定位这个实际失败点，不等于已证明只修这一处便能通过后续全部启动和 IO 验收。

另已核实系统库缓存实物位于 `/System/Volumes/Preboot/Cryptexes/OS/System/Library/dyld`，`/System/Cryptexes/OS` 为系统链接；原策略的 `/System/Library` 读取例外不直接覆盖该真实位置。这是后续启动依赖线索，**不是本次崩溃已执行到该路径的证据**，本轮不据此放开整个 `/System`、Preboot 或 Cryptexes 目录。

#### B. 已确认的最小修改及读取边界

管理员随后明确回复“同意。继续吧”，批准本节精确读取例外和 C 项单次 I01 能力预检；这不包含其他目录例外、业务测试或正式资源操作。下述原提案边界保持，实际执行结果另记 §18.9，不把批准当作预检通过。

只拟在下一次 I01 能力预检策略中追加以下一条规则，其余拒绝规则和原有读取例外保持；临时允许目录仍替换为当次新建路径：

```scheme
(allow file-read* (literal "/"))
```

- `literal "/"` 只匹配根目录对象本身；**禁止写成 `subpath "/"`**，后者会扩大到整棵文件树。
- 该例外可能允许查看根目录本身的元信息和顶层目录项，因此不能宣传为“仅允许加载器使用、对测试代码完全不可见”。它不按调用者身份区分系统加载器与 Python。
- 不授予 `/` 写权限，不新增对其下业务文件的读取权限；`/Volumes`、正式 Dagster home、凭据、虚构禁止目录及网络仍受原拒绝规则约束。取得根目录 FD 后不能借 `openat` 绕过子路径限制，这一点必须用下面的反例实测，不能只凭策略文本宣布安全。
- 不增加 `DYLD_*` 启动绕过变量，不切换解释器、不改安装环境、系统安全设置、全局 Lake/DuckDB 默认值或正式服务。
- 此例外只用于本专项受限测试子进程，不成为产品运行配置。只有管理员明确确认后才生成并执行新策略；当前文档修改不是策略已生效。

#### C. 确认后的有界验证与停止点

1. 新建单独临时目录，不覆盖旧现场；启动前展示完整策略、真实允许/拒绝目录、argv、解释器及预算。仍使用 §18.7 的现有 uv/项目 `.venv`、禁网/禁同步/禁配置加载选项，父进程不导入业务。
2. I01 只运行标准库能力预检：必须先出现 `child_started`，允许区正向读写成功，原有九类禁止操作均因权限拒绝而失败，父进程核实禁止目录文件集合和哨兵内容/身份不变。
3. 为根目录 FD 新增两项反例：取得只读根目录 FD 后，以相对路径和 `dir_fd` 尝试读取虚构禁止目录哨兵、新建虚构禁止文件，均须得到权限拒绝；不是“找不到文件”便算通过。I02 随后还须通过原生 `openat` 与路径别名/链接验证同一边界。不得拿正式路径做读写反例。
4. 本次 I01 最多一个子进程，九类原反例加两类 FD 反例；每例 30 秒、整批 60 秒、工作区 100MiB 的既定上限不变。无业务对象、交易日、Parquet、数据库或正式事件，源请求为零；不会读写 6,166 个正式停牌文件。
5. 若仍在加载阶段退出，保留新地址/错误证据并停止；不得自动追加其他目录或把未知启动失败当预期拒绝通过。I01 通过也不能直接开始 adapter，后续仍需 I02–I08 独立验收与报告。

这次确认仅涉及上述精确读取例外和相应能力预检，不重新讨论已批准的停牌业务方案，也不授权正式文件/事件写入、服务重载、sensor 恢复或删除。

#### D. 只读定位轮交付状态（历史，批准后的执行见 §18.9）

- CodeGraph `explore` 复核 LakeRootResource → 健康 canary、DuckDBResource → 默认连接初始化两条共享链。其他现行消费者继续使用它们，本轮不改共享代码；图中同名 `run` 关联到了无关模块，没有将其纳入范围，依赖矩阵不变。
- 本轮只修改本 LLD、技术方案和主索引；没有执行新隔离策略、业务测试、正式资源操作、提交或推送。
- 文档检查、隔离、adapter、S1 合成回归、S2 生产批准集合、S2 全范围等价分别验收；本次只读定位不能计入后五项通过。实际下一步等待 B 项读取例外确认，再执行 C 项 I01，不能跳至业务修改。

<a id="s1-isolation-i01-passed"></a>

### 18.9 精确读取例外获批后的 I01：单次能力预检通过

执行时间：2026-09-07 15:50:18（北京时间）。本轮仅执行管理员确认的 §18.8 C，新增读取例外只有 `(allow file-read* (literal "/"))`，没有追加系统缓存目录权限。**此次启动成功，不再处于原来的 Python 启动阻塞；但只通过 I01，不代表整个隔离阶段或 S1 已完成。**

#### A. 实际执行边界

- 新工作根：`/private/tmp/stock-suspend-isolated-kOXHMRMv/`。子进程文件写入只允许其 `allowed/` 与既有 `/dev/null` 设备例外；禁止用例只对同次 `denied-fixture/` 操作。原现场未覆盖或清理。
- 父启动器为该 `allowed/` 内的 Node 标准库脚本；只启动一次 uv/受限 Python 命令，不导入业务模块。启动前逐字断言新策略等于旧策略替换当次临时根后，仅追加上述一行；其余权限没有变化。
- 工作目录仍为正式 orchestrator 工程，但子进程使用现有 `.venv/bin/python -I -B -S`，禁用户模块搜索、字节码和 site 初始化；脚本只导入标准库，不导入 pytest、orchestrator、Dagster、DuckDB 或 SQLite。
- 继续使用 `uv run --offline --no-sync --no-env-file --no-config --no-python-downloads`，cache 位于本次 `allowed/uv-cache`。父进程只向 uv 提供 `PATH/LANG/TMPDIR`，不传正式凭据或业务 FD；未设置/覆盖 HOME/CODEX_HOME，未更换解释器或依赖。
- 单 case 30 秒、整批60秒、工作区100MiB上限保持；超时只终止本次父启动器建立的子进程组。此次没有触发超时、空间或输出上限，也没有重试。
- 没有正式 Lake/staging、Dagster instance、数据库、源接口、事件或调度操作。原有暂停的 Silver sensor 未恢复；没有创建仓库中的三个隔离支持文件，也没有改业务代码。

#### B. 实测结果

| 验收项 | 结果 |
| --- | --- |
| 启动与退出 | 明确出现 `child_started`；退出码0、无signal、stderr为空，父启动器记录耗时121毫秒 |
| 允许区正向操作 | 文件创建、读取、覆盖、rename/replace、删除、目录创建/删除全部成功；同一 `dir_fd` 接口读取允许文件成功，排除因接口不支持而假拒绝 |
| 原有九类反例 | read/create/overwrite/delete/mkdir、rename双向、replace双向，全部 `EPERM(errno=1)`；不是靠文件缺失、库缺失或异常提前退出通过 |
| 根目录 FD 两类反例 | 只读打开 `/` 成功后，用相对路径及 `dir_fd` 读取禁止哨兵、新建禁止文件，均 `EPERM(errno=1)` |
| 虚构禁止目录 | 前后只有一个 `sentinel.txt`；24字节、dev `16777234`、inode `99210398`、mtime_ns `1788767371874394400` 及内容SHA256全部相同 |
| 哨兵内容SHA256 | `4d18a51647b7cde7bcbc872065f6811fa6507b260d675fa909c8e38222b8ad94` |
| 新策略SHA256 | `b10bfc46e1e1e83d8bbc1f8736155e0ee7a540532d6f3118755c8939efff33e3` |
| 预检脚本SHA256 | `1da499dd98dbb8045d9763cb7539ed8ef7ef2f6ea2b441661535291689758316` |
| 实际规模 | 一个启动链、一个虚构哨兵、11类拒绝反例；无业务行/日期/Parquet/数据库/事件。报告定稿后工作根磁盘占用44KiB，未达预算 |

完整 argv、父进程PID、逐项输出和前后身份见[预检报告](/private/tmp/stock-suspend-isolated-kOXHMRMv/allowed/capability-result.json)；[策略](/private/tmp/stock-suspend-isolated-kOXHMRMv/allowed/capability.sb)、[标准库用例](/private/tmp/stock-suspend-isolated-kOXHMRMv/allowed/capability_probe.py)及[父启动器](/private/tmp/stock-suspend-isolated-kOXHMRMv/allowed/run_preflight.mjs)保留供当前任务审阅。报告的 `pid` 为父启动器所启动的 uv 进程PID，不冒充每个后代进程PID。临时文件可能被系统后续清理，关键结果已经落入本文；它们不作为后续免重验的成功标记。

#### C. 验收边界与下一步

1. 本次只证明“现有解释器能够在修订策略下启动，标准库文件操作及根目录FD反例按预期被限制”。没有验证 DuckDB/SQLite 原生IO、symlink/路径别名、网络/Unix socket、实际资源构造或 pytest collection 保护，不能把11个反例数当作I01–I08全部完成。
2. 下一步是按 §18.5 准备并执行 I02：先在允许区用原生组件生成微型虚构样本，再由无业务导入的父进程放入同次禁止区，验证允许路径成功、禁止路径失败、原生openat及路径别名/链接不能绕过。仍不使用正式数据样本，不执行实际 checks 或 writer。
3. I02若需要新增启动/导入读取例外，必须先核验具体依赖并按原门禁确认，不能把这次 `/` 的批准解释为任意系统或仓库目录读取授权。I01成功也不取消I02–I08独立验收和进入adapter前的报告停止点。
4. 本次预检临时脚本由当前任务负责，仅用于能力验证，不注册到Definitions。完整隔离支持验收并提取必要证据后，再按精确清单确认清理本次临时目录；本轮不删除现场，不把临时脚本变成业务兼容入口。
5. 本轮仓库仅续写LLD、技术方案和主索引；既有未提交源码及其他文档不变，依赖矩阵不变。未提交、未推送；业务代码及S2批准集合/全范围等价验收均未推进。

<a id="s1-isolation-i02-native-io"></a>

### 18.10 I02：原生 IO 与路径绕过的有界验证

#### A. 执行前固定的范围与判据

管理员本轮指令为“继续推进I02”。基线为 `dev-interface@a77b51e7` 加保留的未提交内容；本轮不修改那些业务文件，不执行I03–I08、adapter、业务测试或正式资源操作。

1. 新工作根为 `/private/tmp/stock-suspend-isolated-paqWh57w`，只使用其中 `allowed/` 和同次 `denied-fixture/`。父启动器逐字比较策略：只把I01策略的临时根换为本次根，读取/写入/网络权限零增加。保留既有 `/dev/null` 写设备例外，不把临时目录当正式数据源；不清理前次或本次现场。
2. 原生依赖静态核验：项目虚拟环境使用CPython 3.13.5；DuckDB 1.5.2的 `_duckdb.cpython-313-darwin.so` 链接 `/usr/lib` 的 libc++/libSystem；`_sqlite3` 和 `_ctypes` 经 `@loader_path/../../` 解析到已有读取白名单中的 `/Users/congming/miniconda3/lib`（SQLite/ffi）。未发现需要追加读取权限的依赖。项目site目录的4份 `.pth` 已逐份审查：editable只登记源码路径，另外为virtualenv/distutils初始化及受环境变量控制的coloredlogs；不设置该变量，不导入业务包。
3. I01使用 `-S` 只加载标准库；I02需要实际已安装DuckDB，因此使用同一项目解释器 `-I -B`，不加 `-S`，不改 `sys.path/PYTHONPATH`、不安装依赖。OS隔离仍在解释器及site初始化之前生效，项目源码未加入读取白名单。运行中核验实际 `sys.prefix`、原生模块位置与版本，并断言没有加载orchestrator/Dagster/pytest。
4. 分四个独立受限子进程：prepare仅创建/读回2行虚构SQLite和Parquet；native为10组；SQLite为12组；DuckDB为9组。后三批共31组，每组必须先在允许目录完成同类正向操作，再证明拒绝；每批最多12组，未超过§18.6的16例上限。一批失败就停止，不自动重试、不调整权限或验收断言。

| 批次 | 精确操作与路径 | 判据 |
| --- | --- | --- |
| prepare，1例 | 2行SQLite建表/提交/读回/关闭；DuckDB内存连接COPY并读回2行Parquet | 两种样本可用，原生模块真实加载；关闭后父进程只复制两份小文件至同次禁止区，并逐份核验SHA256一致，父进程不导入数据库或业务库 |
| native，10组 | C `open`读取/新建 × canonical、`/tmp`别名、`..`、symlink四种路径；C `openat`从 `/` 的FD读取/新建各一组 | 实际libSystem调用，禁止项只能是EPERM/EACCES；`ctypes.use_errno=True`，Apple ARM64变参仅声明固定参数类型，排除错误调用签名假失败 |
| SQLite，12组 | 读现有库、改现有库、建新库 × 四种路径 | 允许区真实SQL完成并读回；禁止区只认可SQLITE_CANTOPEN/SQLITE_READONLY且同一路径C open权限拒绝。写现有库使用rw，不用只读连接制造假拒绝；每次显式close |
| DuckDB，9组 | `read_parquet`、`COPY`新文件 × 四种路径，加1组glob读取 | 允许区COPY后读回精确两行；禁止区必须为IOException，且同一目标文件的C open拒绝。glob可包装成“没有匹配文件”，必须结合父进程证明同内容文件确实存在及原生权限证据，不能只认任意SQL异常 |

DuckDB使用显式 `:memory:`、512MB、2线程、本次允许目录temp、0B spill，关闭扩展自动安装/自动加载；读回设置核验。保持 `enable_external_access=true`，避免把DuckDB自身禁外部IO误当OS隔离有效。Parquet支持若不能在此配置下正常工作就停止，不临场INSTALL/LOAD或放开网络。正反同内容种子、禁止目录文件集合/大小/mode/dev/inode/mtime_ns/SHA256必须保持一致；允许区写例只改各自虚构副本，不改种子。

每例30秒、每批60秒、fixture合计1MiB、工作区100MiB、stdout/stderr各64KiB上限；父启动器只终止自身创建的子进程组。每批保存启动、当前例、实际完成数、耗时及前后身份，失败保留报告，绝不把超时或导入失败算作成功。

执行目录为 `/Users/congming/github/goldenshare/lake_console/orchestrator`。父进程只用Node标准库，向uv仅传 `PATH/LANG/TMPDIR`；不透传业务凭据，不设置HOME/CODEX_HOME，不继承业务FD。父入口与四批完整argv为：

```text
/usr/bin/env -u NODE_OPTIONS /opt/homebrew/bin/node /private/tmp/stock-suspend-isolated-paqWh57w/allowed/run_native_io.mjs

# 以下完整命令各执行一次，末尾phase依次为prepare、native、sqlite、duckdb；失败即停止后续批次。
/opt/homebrew/bin/uv run --offline --no-sync --no-env-file --no-config --no-python-downloads --cache-dir /private/tmp/stock-suspend-isolated-paqWh57w/allowed/uv-cache /usr/bin/sandbox-exec -f /private/tmp/stock-suspend-isolated-paqWh57w/allowed/capability.sb /Users/congming/github/goldenshare/lake_console/orchestrator/.venv/bin/python -I -B /private/tmp/stock-suspend-isolated-paqWh57w/allowed/native_io_probe.py prepare
/opt/homebrew/bin/uv run --offline --no-sync --no-env-file --no-config --no-python-downloads --cache-dir /private/tmp/stock-suspend-isolated-paqWh57w/allowed/uv-cache /usr/bin/sandbox-exec -f /private/tmp/stock-suspend-isolated-paqWh57w/allowed/capability.sb /Users/congming/github/goldenshare/lake_console/orchestrator/.venv/bin/python -I -B /private/tmp/stock-suspend-isolated-paqWh57w/allowed/native_io_probe.py native
/opt/homebrew/bin/uv run --offline --no-sync --no-env-file --no-config --no-python-downloads --cache-dir /private/tmp/stock-suspend-isolated-paqWh57w/allowed/uv-cache /usr/bin/sandbox-exec -f /private/tmp/stock-suspend-isolated-paqWh57w/allowed/capability.sb /Users/congming/github/goldenshare/lake_console/orchestrator/.venv/bin/python -I -B /private/tmp/stock-suspend-isolated-paqWh57w/allowed/native_io_probe.py sqlite
/opt/homebrew/bin/uv run --offline --no-sync --no-env-file --no-config --no-python-downloads --cache-dir /private/tmp/stock-suspend-isolated-paqWh57w/allowed/uv-cache /usr/bin/sandbox-exec -f /private/tmp/stock-suspend-isolated-paqWh57w/allowed/capability.sb /Users/congming/github/goldenshare/lake_console/orchestrator/.venv/bin/python -I -B /private/tmp/stock-suspend-isolated-paqWh57w/allowed/native_io_probe.py duckdb
```

临时实现及报告归本次能力验证，不注册Definitions、不成为业务兼容入口；后续隔离support仍须按§18.2正式实现和独立验收。本节先固定执行约束，下面仅在实际执行后登记结果。

API校验依据：[Python ctypes的Apple ARM64变参约束](https://docs.python.org/3.13/library/ctypes.html#calling-variadic-functions)、[SQLite连接URI与显式关闭](https://docs.python.org/3.13/library/sqlite3.html)、[DuckDB设置](https://duckdb.org/docs/current/configuration/overview)、[Parquet读写](https://duckdb.org/docs/current/data/parquet/overview)。这些资料用于校准调用方法，不能代替本次OS实测。

#### B. 2026-09-07 16:10 实测：准备批次失败，I02未通过

| 验收项 | 实际结果 |
| --- | --- |
| 启动与原生导入 | 受限Python PID `65078`（父runner启动的uv PID `65076`）；CPython 3.13.5、SQLite 3.50.2、DuckDB 1.5.2均真实加载，实际prefix为项目`.venv`，源码读取被OS拒绝，没有业务模块加载 |
| 正向样本准备 | 创建允许区的24字节虚构文本后，首次 `sqlite3.connect(file:…/allowed/fixtures/toy.sqlite?mode=rwc)` 抛 `OperationalError: unable to open database file`；没有进入建表SQL |
| 停止情况 | prepare退出码1、无signal，170毫秒；0个完整case。后三批未启动，31组正反例均未执行；没有重新运行或改策略 |
| 实际生成范围 | `allowed/fixtures/`只有 `sentinel.txt`，SQLite文件、SQLite journal、Parquet均未生成；父进程尚未执行复制样本步骤。DuckDB仅导入，尚未创建显式连接或读回设置 |
| 虚构禁止目录 | 前后只有24字节 `sentinel.txt`；dev `16777234`、inode `99214256`、mode `33188`、mtime_ns `1788768431420790474`、SHA256 `4d18a51647b7cde7bcbc872065f6811fa6507b260d675fa909c8e38222b8ad94`全部一致 |
| 预算与正式边界 | 没有超时/超空间/超输出；报告定稿时整个临时根磁盘占用60KiB。没有正式Lake/staging/数据库、Dagster实例、事件、调度或源接口操作；没有读取正式文件作样本 |
| 策略SHA256 | `b15bdeb9b34f6f5f282202f9a54f1ca01dde37781e384d81994d82dcc0d4c77d`；与I01仅临时根字符串不同 |
| 原生用例SHA256 | `955426d93fb20c325b6f8f20b8cb415afdbffa78cf21422a6efe0cf98290a94f` |
| 父启动器SHA256 | `d9611016106864eed374c832cc4c7b3e5f12f24a875e03bb83f01d535324eab2` |

完整[执行报告](/private/tmp/stock-suspend-isolated-paqWh57w/allowed/native-io-result.json)、[策略](/private/tmp/stock-suspend-isolated-paqWh57w/allowed/capability.sb)、[原生用例](/private/tmp/stock-suspend-isolated-paqWh57w/allowed/native_io_probe.py)、[父启动器](/private/tmp/stock-suspend-isolated-paqWh57w/allowed/run_native_io.mjs)保留，不覆盖失败记录。报告中的 `imports_passed` 仅表示导入及路径核验完成，不是数据库IO成功；预算配置也不是已读回的DuckDB设置。禁止把该失败登记为权限反例成功或S1验收通过。

#### C. 失败后的只读定位：目录属性权限缺口

没有再次启动测试子进程、打开数据库、改变权限或修改用例断言。只读查询本次PID的系统日志，并检查本机实际加载的SQLite动态库及对应版本源码：

1. 系统日志在 `2026-09-07 16:10:27.611` 明确记录：`Sandbox: python3.13(65078) deny(1) file-read-metadata /private`。它出现在库加载成功后、首次SQLite连接失败时；不是从泛化错误文本猜路径。
2. SQLite 3.50.2的 `unixFullPathname → appendAllPathElements → appendOnePathElement` 对绝对路径逐段调用 `lstat`。非ENOENT错误会设置SQLITE_CANTOPEN；已知目标位于允许目录也不会省略父目录检查。[对应版本源码，6248–6355行](https://raw.githubusercontent.com/sqlite/sqlite/version-3.50.2/src/os_unix.c)。
3. 对实际 `/Users/congming/miniconda3/lib/libsqlite3.3.50.2.dylib` 的只读符号/反汇编核验也有相同分支：`_appendAllPathElements` 位于 `0x2a2c8`；`0x2a428`调用lstat，随后比较errno是否为2（ENOENT），其他错误进入日志并设置14（CANTOPEN）。这与本次 `/private` 拒绝和Python连接异常吻合，不仅依据线上源码或库名下结论。
4. 现策略允许 `allowed/` 子树及根目录 `/`，但没有允许其祖先 `/private`、`/private/tmp`、当次工作根本身的元数据读取。动态日志证明首先卡在 `/private`；其余祖先及 `/tmp` 别名的需要来自逐段检查实现，尚未在修订权限后实测。
5. 同一PID更早还有Cryptex、Data、`/etc`、`/var`、dtracehelper、editable源码路径的拒绝日志，但解释器及三个原生模块随后加载成功。不能把这些日志全部视为必要权限，更不能据此追加系统目录或仓库读权限。

结论：**本轮暴露的是专项测试隔离策略未覆盖SQLite路径解析所需的父目录属性读取，不是停牌业务字段/合并方案错误，也不是现有正式SQLite数据损坏。** 当前无法据此证明修订后所有原生IO都会通过；I02仍须完整实测。

#### D. 最小修订建议（提出时待确认；后续批准与复验见§18.12）

只建议在下次全新临时根的策略中增加以下**目录元数据**精确例外，既有权限不变：

```text
(allow file-read-metadata
  (literal "/private")
  (literal "/private/tmp")
  (literal "/tmp")
  (literal "<下次runner生成并核验的完整临时工作根>"))
```

其中前三项为确定路径，最后一项必须绑定当次真实随机根，不能改成 `/private/tmp` 的subpath或通配符。权限意图仅为检查这些目录/链接对象的属性；不开放目录列表/文件内容读取，不增加任何写权限，也不放开兄弟禁止区、正式Lake、正式实例、仓库源码或网络。本段是待批准策略设计，不是可直接执行的成品profile；当前失败现场profile保持原样。

获批后先核对策略差异与元数据例外范围，在全新虚构目录复验I01，再重跑I02的prepare/native/SQLite/DuckDB四批；必须同时证明允许路径可用、越界路径被拒绝、禁止区和种子不变。I01/I02仍按独立门禁报告；若还有其他权限或库能力缺口，先核验事实再请求确认，不能自动扩大白名单。未获批准前不启动重跑，不推进I03–I08或实际adapter。

本轮仅修改LLD、上位技术方案和主索引；临时文件由本专项持有供review。原有12项未提交文件、共享资源默认值及依赖矩阵不变；文档完整性和差异检查与I02运行状态分开报告，不以文档检查通过替代测试验收。没有提交、推送或删除现场。

#### E. 本轮交付核验

- 文档完整性检查三项全部通过；`git diff --check`通过。它们不证明原生隔离、adapter或S1业务回归通过。
- 排除本轮三份文档后，已跟踪差异的SHA256前后均为 `f94f46dae3117fa76d1bb8ac6a280edc5c43eb9a379ec70eeb56f6b61d09a4d2`；五份未跟踪专项源码/测试的逐文件SHA256也与开工前一致。既有未提交工作没有被本轮覆盖。
- 分项状态：文档检查通过；隔离为I01历史通过、I02准备失败；I03–I08、实际adapter、S1实现/合成回归、S2生产批准集合、S2全范围等价均未新增验收结果。下一动作仅为确认§18.10 D的最小权限修订，不能进入下一业务阶段。

<a id="s1-test-cleanup-and-install-boundary"></a>

### 18.11 管理员要求：前置验收收敛、完成后清理、禁止擅自安装

2026-09-07管理员指出前置验收过重，明确要求本需求完成后彻底删除测试DG实例，并卸载本任务自行安装的本地SQLite；未经允许不得在本地安装套件。按以下口径执行，不新增独立清理项目或常驻服务：

1. **收敛范围。** 后续只围绕本需求的数据正确性、关键失败阻断及不误触正式资源做必要验收，不继续扩展通用隔离功能。该要求不等于已有失败项通过，也不授权无保护运行、安装依赖或放宽权限。本轮仅登记约束，没有重跑测试或更改I组验收判据。
2. **收尾清理是完成条件。** 本需求的业务验收完成后、最终交付前，清除本专项创建的所有临时DG实例目录及其运行/事件/调度数据库、日志、虚构数据、临时探测脚本/profile和专项缓存。不因早前“保留现场供review”永久保留；清理结束后再宣布本需求完成。
3. **按归属精确删除。** 从本专项实际执行记录提取完整路径，确认无活动进程占用、内容确属本任务后执行本次已授权的收尾清理。共享pytest根只清理可归属本专项的子目录，不按目录名前缀扫删；不删除正式DG实例、正式Lake/staging数据、其他任务实例、项目既有`.venv`或整个Miniconda环境。归属不清的对象先说明，不能猜测删除。
4. **保留结论，不保留运行实例。** 必要结论、哈希和删除清单落回本方案；临时路径链接在删除后改为已清理的历史记录。交付列清实际删除路径、已不存在的路径、未删除项及原因，并验证测试实例/专项残留不存在。这里只清理运行产物，不把项目测试源码或正式固定停牌事实列入清理。
5. **禁止未经批准安装。** 适用根AGENTS的本机套件安装限制。测试或缺库不是安装授权；不得通过uv自动同步、pip/Conda/Homebrew/npm安装、下载解释器或数据库扩展来绕过。任何以后获批且仅为本需求安装的独立套件，登记准确包名/位置，并纳入收尾卸载；共享依赖不能冒充专项安装项卸载。

SQLite来源核验（本轮只读）：I02报告实际使用CPython 3.13.5和SQLite 3.50.2；项目`.venv/pyvenv.cfg`指向已有 `/Users/congming/miniconda3/bin`。该环境的 `conda-meta/sqlite-3.50.2-h79febb2_1.json`登记实际 `lib/libsqlite3.3.50.2.dylib`，`python-3.13.5-h2eb94d5_100_cp313.json`同时登记 `_sqlite3` 模块并显式依赖 `sqlite >=3.45.3,<4.0a0`。因此当前使用的是既有Python环境的SQLite组件，不是I02单独安装的服务或套件；I01/I02命令为 `uv run --offline --no-sync --no-python-downloads`，没有执行安装。

要删除的是本任务生成的测试数据库和实例；不能把卸载SQLite原有运行库当成删除数据库文件。当前未核实到本需求新增的独立SQLite安装项，故不存在已确认可卸载的专项SQLite套件；不能承诺卸载已有共享运行库。I02本身没有创建成功SQLite文件，早前S1测试已产生的临时实例仍须按上述归属清单一并清理，不因I02失败而漏掉。

本轮只更新根AGENTS、本LLD及上位技术方案；没有安装/卸载/删除任何内容，没有改业务代码或依赖矩阵，没有继续测试、修改权限、提交或推送。收尾清理尚未执行，必须保留为未完成项。

<a id="s1-isolation-parent-metadata-retest"></a>

### 18.12 四项目录属性权限获批后的I01复验与I02重跑

管理员明确确认：本需求新增安装项必须在完成后卸载；按§18.10 D最小修订修改、复验、重跑，执行前读AGENTS。本轮已重读根AGENTS（含安装限制）、AGENTS.local及src/docs/lake_console/orchestrator目录规则；继续遵守已读的架构、编码、schema与性能基线。不安装、升级或自动同步依赖，不更改业务源码、共享资源或正式环境。

执行前固定：全新根 `/private/tmp/stock-suspend-isolated-CXgYldhn`，复验I01后才运行I02；两阶段分别留报告。只在新策略增加 `/private`、`/private/tmp`、`/tmp`、当次完整临时根四个literal的 `file-read-metadata`，不增加内容读取/写入/网络权限，既有设备例外不变。父启动器逐字比对批准差异；I02额外核验同次I01已通过且策略哈希一致。旧失败现场和脚本不修改。

用例内容、SQL、预期结果和预算沿用§18.9、§18.10：I01正向与11个拒绝反例；I02两行虚构样本准备后，原生10组、SQLite12组、DuckDB9组。两个Python用例只替换本次临时根，不改断言或扩大范围。每例30秒、每批60秒、fixture1MiB/工作区100MiB上限不变，失败停止；不进入I03–I08、adapter或S1业务开发。

工作目录仍为 `/Users/congming/github/goldenshare/lake_console/orchestrator`，现有项目`.venv`解释器、uv离线/禁止同步下载、受控PATH/LANG/TMPDIR及不继承业务FD不变。允许写目录只为本次 `allowed/` 与既有 `/dev/null` 例外；拒绝样本只为同次 `denied-fixture/`。完整子进程argv由已核对的父启动器在启动前输出并逐批写入报告。两个父入口依次单独执行，不自动进入其它阶段：

```text
/usr/bin/env -u NODE_OPTIONS /opt/homebrew/bin/node /private/tmp/stock-suspend-isolated-CXgYldhn/allowed/run_preflight.mjs
/usr/bin/env -u NODE_OPTIONS /opt/homebrew/bin/node /private/tmp/stock-suspend-isolated-CXgYldhn/allowed/run_native_io.mjs
```

#### 实测结果与收尾边界

执行时间：I01为2026-09-07 16:36:34，I02为16:36:51–16:36:52（北京时间）。两阶段均使用策略SHA256 `604fd5431d57920de7ba72ed80efc0181440651c0ee3a4b43a18f79270c76818`；没有新增其它读取例外。所有批次退出码0、无signal、stderr为空，未触发超时/空间/输出限制。

| 阶段 | 实际结果 | 耗时 |
| --- | --- | --- |
| I01复验 | 正向操作通过；11类禁止操作全部EPERM(errno=1)，哨兵身份/内容不变 | 111毫秒 |
| I02 prepare | 2行SQLite建表/提交/读回/关闭成功，2行Parquet COPY/读回成功；父进程复制至禁止区并核验同内容 | 539毫秒 |
| I02 native | 10/10组正向与权限拒绝通过，含C open/openat、根FD、四种路径 | 94毫秒 |
| I02 SQLite | 12/12组通过；禁止项均SQLITE_CANTOPEN(14)，同目标原生调用均EPERM；不是只读连接制造的拒绝 | 94毫秒 |
| I02 DuckDB | 9/9组通过；COPY越界返回Operation not permitted；read_parquet/glob包装为No files found，但父进程证明目标存在且同内容，原生调用为EPERM | 371毫秒 |

I02全程约1.1秒，31组全部有同类正向成功与禁止项失败证据。实际版本仍为CPython 3.13.5、SQLite 3.50.2、DuckDB 1.5.2。显式内存连接设置读回：`memory_limit=488.2 MiB`（512MB的格式化显示）、`threads=2`、`max_temp_directory_size=0 bytes`、temp位于当次allowed；扩展自动安装/加载均false，external access为true，故不是靠DuckDB禁外部IO假通过。

fixture种子合计8,535字节：文本24字节、SQLite8,192字节、Parquet319字节。原始允许区种子以及禁止区复制完成后的文件集合、dev/inode/mode/mtime_ns/size/SHA256，在全部测试前后保持一致；写入正例仅改各自虚构副本。Parquet SHA256为 `a6ee7d93afa1a109583a1f976d5dd239f873bbc3c7edb8eff34ab3b9edf9403f`，SQLite SHA256为 `d43a30ebddcf79505d1489ac4f397a1951c734595821f7bd34c1ef004cc0584f`。报告定稿后当次临时根磁盘占用236KiB，远低于100MiB预算。

证据：[I01报告](/private/tmp/stock-suspend-isolated-CXgYldhn/allowed/capability-result.json)、[I02报告](/private/tmp/stock-suspend-isolated-CXgYldhn/allowed/native-io-result.json)、[精确策略](/private/tmp/stock-suspend-isolated-CXgYldhn/allowed/capability.sb)。I01用例SHA256 `77c158d4bf3eff40ce834bce27fcaae304d7925f686064749b3ee785ae24c1d6`；I02用例SHA256 `484c430c25167ae9b39befcf0ebd47191323f08f9e3631ad311712d71429664f`；I02父启动器SHA256 `876a80c8b51e402e9952a8633e49dfaadb22f8cdc8e0d317d265ea49c9b495a0`。两份Python用例除当次根字符串外与原用例一致。

本轮只证明I01/I02能力验证通过；没有导入orchestrator、Dagster或pytest，没有创建新DG实例/服务，也没有访问正式Lake/staging/数据库、修改正式事件或恢复sensor。SQLite文件只是本次原生IO虚构样本。I03–I08、实际adapter、S1实现/合成回归、S2生产批准集合与全范围等价均未新增验收结果；按§18.11收敛后续必要测试，不把本次通过当成整体安全验收结束。

本需求新增安装项完成后必须卸载的要求已再次确认；本轮安装/升级/同步/卸载次数为0。本目录及以前本任务生成的实例/文件均纳入§18.11最终清理，不作为长期本机环境保留；当前需求尚未完成，因此本轮不删除证据或现有共享运行库。仓库仅同步本LLD、技术方案及主索引，业务源码与依赖矩阵不变；未提交、未推送。

交付核验：文档完整性三项与 `git diff --check` 均通过。排除本轮三份文档后的已跟踪差异SHA256前后均为 `783a4185f391fb709eaf89ae539bab23e839480bc6f75c45ce916159f2892d4e`，五份未跟踪专项源码/测试哈希前后一致；已有AGENTS变更与其它未提交内容均保留。

<a id="s1-isolation-i03-real-resource"></a>

### 18.13 I03：真实 Lake 资源参数保护，独立增量实施

管理员要求“提交一下，然后继续推进”。先按四文件白名单提交规则、方案和I01/I02证据，提交为 `0f2bbbf9`；原有十二项未验收业务代码/测试及其他文档保留。随后按§18.2启动测试支持的最小增量：**本次只实现和验收I03，不把其余I组或adapter串入同轮。** 三个测试支持文件此前不存在，本次新增；现有两个业务测试、新checks、合同和共享资源均不修改。

#### A. 当前代码及影响面

CodeGraph `explore` 与实际源码核验覆盖 `LakeRootResource`、`DuckDBResource`、新checks及健康函数。`root()`只返回`Path(self.root_path)`；未知`lake_root`参数会回落默认根。`ensure_available_for_run()`实际进入写/读/删canary，默认DuckDB连接也先创建正式temp目录，故本轮不调用这两条链。不修改资源默认值、共享健康函数、依赖矩阵或业务字段。

实际资源导入链为 `resources → paths → 12个run_contracts模块/tushare_request_policy/major_indices`，另有`health/lake_root`、`notifications/feishu`及既有第三方库。`major_indices.py`只定义CSV读取函数，不在本轮调用；飞书与ClickHouse模块是资源声明所需的既有依赖，本轮不调用其连接或发送方法。

必须区分“资源声明对象”和“正式执行图”：`resources.py`尾部确有顶层`defs = dg.Definitions(resources=...)`，正常导入实际类会同时构造该资源声明及EnvVar占位，不能声称只定义类、绝不构造任何Definitions对象。本测试不读取/调用该`defs`，不调用资源setup/connect/探针，不导入`orchestrator.definitions`、执行`load_from_defs_folder`或构造完整正式执行图。若后续导入过程中实际触发配置解析、连接或额外IO，仍应由保护拒绝并停止，而非把声明当成运行授权。本次实际运行在测试文件导入前已经失败，因此真实资源及这些声明均尚未进入执行。

I01/I02的能力profile刻意不开放源码，因此不能直接用它来证明真实资源可测。I03按§18.2已经批准的实际类测试范围生成独立profile：保留原运行库、设备和四项目录属性规则，仅增加runner内固定的26份资源依赖Python源码、三个专项测试支持文件，以及Python导入所需目录对象的精确读取。**没有整个仓库或src/defs子树读取许可**；不开放CSV、`.env`、配置、正式实例、Lake/staging、网络或任何新增持久写目录。目录literal只涵盖目录对象，不递归开放子项。这是从无业务导入的能力验证进入计划内真实资源测试，不改写或重跑旧I02现场；完整源码白名单、profile及哈希在每次启动前输出并保存。若发现额外库/文件权限缺口，停止核验，不自动加权限重试。

#### B. 文件—约束—测试对账

| 文件 | 本次落地 | 验证 |
| --- | --- | --- |
| `tests/stock_suspend_confirmed_test_runner.py` | stdlib父进程；安全生成独立根；固定测试文件、禁止任意参数透传；受控环境/关闭继承FD；60秒、100MiB、64KiB输出预算；保存证据不清理 | scope仅isolation/adapter且必须指定；adapter明确拒绝，不能因为I03成功开放；父进程核对禁止目录前后身份 |
| `tests/stock_suspend_confirmed_test_support.py` | pytest及业务import前做当次OS自检；显式插件，无conftest/自动插件/缓存；资源工厂无默认值/`**kwargs`；核验实际`.root()`；30秒case上限 | 允许区正常读写和C open；C拒绝读及六项Python越界写拒绝。这里只是当前profile小型自检，不冒充完整I01/I02重新验收 |
| `tests/test_stock_suspend_confirmed_isolation.py` | 顶部保护断言早于业务import；仅I03八例 | 正确真实资源1例；错误工厂参数/缺根/正式根/错误工作根4例；实际类错误参数、隐式默认、显式正式根3例。反例stat/lstat/open/mkdir/健康probe调用均为0 |

resource工厂本次只返回真实Lake资源；DuckDB设置和临时instance支持分别留到I05/I06，不预建不用的库或实例。I04/I07/I08尚未实现，不能因runner存在就声称覆盖完整路径/实例/导入门禁矩阵。

执行目录为当前orchestrator工作区；现有项目`.venv`、uv禁同步/禁下载/禁`.env`，父入口使用`-I -B -S`，受限子进程使用`-I -B`。父启动前命令为：

```text
/opt/homebrew/bin/uv --no-cache run --offline --no-sync --no-env-file --no-config --no-python-downloads .venv/bin/python -I -B -S tests/stock_suspend_confirmed_test_runner.py --scope isolation
```

当次随机根由runner生成，完整子进程argv、策略及精确目录必须在启动子进程前输出。测试只构造真实资源，不建Dagster实例、不运行checks/job、不生成湖文件。正式路径仅为反例字符串；禁止用实际正式文件验证拒绝。合成哨兵不足1KiB，八例、单批60秒/100MiB；预计秒级，无源请求、分页、业务提交或spill。全部临时产物纳入§18.11收尾清理，不安装任何套件。

以下结果只有实际运行后登记；当前设计/静态检查不能算I03通过。

首次运行根 `/private/tmp/stock-suspend-isolated-1rbe3d6i`：OS自检七项拒绝及正向通过，但pytest因`-c /dev/null`把rootdir推导为`/dev`，collection尚未开始就因读取该目录属性被拒绝；I03为0/8，未构造资源、未创建实例。已核对当前pytest 9.1.1的`determine_setup`、`Session.collect`及`_get_directory`：需显式固定rootdir和confcutdir，不能把禁用配置文件的位置当成测试根。修订仅给pytest增加 `--rootdir <项目/tests> --confcutdir <项目/tests>`，均为原profile已允许的目录对象；**不增加任何文件/目录权限**，也不加载conftest。失败现场保留，修正后的复验使用新根。

#### C. 前两次复验结果与当时停止原因（后续获批复验见D）

| 运行 | 实际结果 | 禁止区与预算 |
| --- | --- | --- |
| `1rbe3d6i` | 291毫秒，pytest退出3；错误为`/dev`属性读取，0/8 | 34字节哨兵及文件集合/身份不变，52KiB现场 |
| `nizsicff` | 288毫秒，pytest退出4；测试根已正确，但目录收集检查`tests/__init__.py`属性被OS拒绝，0/8 | 同内容哨兵及身份不变，48KiB现场 |

两轮当次OS自检均为正向成功、七项拒绝成功；第二轮profile除随机根外与第一轮逐字相同，没有为首次失败增加`/dev`权限。第二轮策略SHA256为`d1338b74aa7b64f57704e4eb628b97f036c812ccf8969a2e6f191c1da9c170ec`。完整证据：[首次报告](/private/tmp/stock-suspend-isolated-1rbe3d6i/allowed/resource-result.json)、[第二次报告](/private/tmp/stock-suspend-isolated-nizsicff/allowed/resource-result.json)。均未进入八例资源构造/检查，不把任何一次collection失败当作预期负例成功。

这是本轮对pytest收集/import行为审计不完整造成的测试入口问题，不是固定停牌事实或正式业务数据失败。当前pytest源码证明两条额外行为：

1. `Dir.collect → pytest_ignore_collect`会遍历指定文件所在目录，对不是初始指定文件的兄弟项做目录属性判断；仅传一个文件并不等于不检查兄弟项。
2. `resolve_package_path`会逐级检查`__init__.py`以确定包边界；本仓库`tests/__init__.py`确实存在，为1字节换行，SHA256 `01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b`；项目根的`orchestrator/__init__.py`路径当前不存在。后者必须允许属性检查返回“不存在”，不能用PermissionError冒充不存在。

**最小修订建议（提出时待确认；管理员随后确认，实施与复验见D）：**

- 固定增加`--ignore-glob <项目/tests>/*`，利用当前pytest对初始显式文件先豁免ignore的实现，仅排除所有非显式兄弟项；不新增自定义collector、复制测试源码或修改pytest库。
- 增加精确`file-read*`：`/Users/congming/github/goldenshare/lake_console/orchestrator/tests/__init__.py`，只读这个已核验的空包文件。
- 增加精确`file-read-metadata`：`/Users/congming/github/goldenshare/lake_console/orchestrator/__init__.py`，只为识别当前不存在的包标记。启动前须确认该路径仍不存在，若新增则重新审计，不能默许执行新包初始化代码。
- 不开放tests目录子树或所有文件元数据，不修改正式配置/业务源码、不加系统目录、写权限或网络权限。新根先自检，再验证必须恰好收集并完成八例；任何skip/xfail、0例或提前失败均不通过。这里是基于当前源码的建议，不保证未执行的后续导入已经通过。

第二次失败后已停止运行；上面两项权限和ignore参数未加入当前代码，也没有第三次重跑。I03未验收，adapter硬拒绝、I04–I08未实施。下一步只需核准上述测试收集边界修订，不涉及业务字段、正式资源写入或安装套件的拍板。

本轮只新增三个测试支持文件并回写原LLD、技术方案及主索引；I03增量未提交/推送。原有已跟踪差异SHA256仍为`f94f46dae3117fa76d1bb8ac6a280edc5c43eb9a379ec70eeb56f6b61d09a4d2`，五个原有未跟踪业务源码/测试哈希与开工前一致。没有创建新Dagster实例或SQLite库、没有修改正式文件/事件/调度、没有安装/卸载套件。两个临时根纳入既有收尾清单；需求未完成，本轮保留现场。

#### D. 两个精确只读例外获批后的修订与复验

管理员回复“确认”，批准C段的两个精确只读例外和限定收集后的I03重跑。本轮先复核AGENTS、技能和当前runner/support/八个用例；工作区仍为`dev-interface`，其他专项和wealth文档改动不纳入本轮。

执行硬口径不变：只改runner/support；新增权限只有`tests/__init__.py`的精确读取及项目根`__init__.py`的精确属性读取，既有文件/写入/网络限制不变。runner启动前检查tests包标记仍为单个换行且不是链接，并用lstat确认项目根包标记不存在；若内容改变、出现目录/文件/链接或检查权限错误，立即失败，不进入受限子进程。pytest仅增加固定ignore-glob，不改八个用例断言；必须实际收集并完成八例才算I03通过。

沿用B段完整父入口和工作目录，子进程完整argv/profile及精确随机根在启动前输出；报告补记当次三份测试源码SHA256。全新临时根，先做原生/写入拒绝自检再收集I03，case30秒、批次60秒、100MiB上限。没有新增DG实例、正式运行状态查询、业务数据操作或依赖安装授权；I04–I08、adapter仍不进入。以下只在实测后登记结果。

**2026-09-07 17:05:39–17:05:40（北京时间）实测通过。** 当次根为`/private/tmp/stock-suspend-isolated-nafmpdxm`；整体1,108毫秒、退出码0、stderr为空，pytest八例耗时0.74秒。结果不是前两次0例失败的沿用，也不是修改断言后的假通过。

| 验收项 | 实际证据 |
| --- | --- |
| 权限差异 | 启动前将新策略与上次profile逐字对账，新增内容恰为批准的两个literal，无其他权限变化；包标记改变/新出现的两个注入反例均在策略生成阶段拒绝，无文件写入或业务导入 |
| 当次隔离自检 | 允许路径Python读写与C open成功；禁止路径C读取及六项Python写操作全部拒绝，共七项；这只是本次小型自检，不冒充完整I01/I02重跑 |
| I03正向1例 | 实际`LakeRootResource`，`root_path`及`.root()`等于临时Lake路径；资源构造后该目录仍不存在，没有mkdir或探针 |
| 工厂反例4例 | 错误参数名、缺根、正式根字符串、错误工作根全部拒绝；每例stat/lstat/open/mkdir/健康probe调用均为0 |
| 实际资源反例3例 | 错误参数、隐式默认和显式正式根均真实回落/指向正式根字符串，测试侧核验立即拒绝；每例上述五类调用均为0，未访问该正式路径 |
| 收集与结果 | 恰好八例，8 passed、0 failed、0 skipped；四条既有Dagster/Pydantic弃用警告未隐藏，不改库或升级依赖来消除 |
| 现场与预算 | 禁止区34字节哨兵的文件集合、dev/inode/mode/size/mtime_ns/SHA256前后相同；整个现场52KiB，无超时、空间或输出超限 |

证据：[完整运行报告](/private/tmp/stock-suspend-isolated-nafmpdxm/allowed/resource-result.json)、[八例汇总](/private/tmp/stock-suspend-isolated-nafmpdxm/allowed/pytest-result.json)、[当次策略](/private/tmp/stock-suspend-isolated-nafmpdxm/allowed/capability.sb)。策略SHA256为`9cfa5e2d8dd30d8ced661d69fa806986601a68da741fb398659d670fb6a3bfd4`；用例文件SHA256仍为`cfebba6825b2b2f640f7db1b9ad7258624a76b02582783521e9ec92bc4c0b3b8`，与本轮修改前完全一致。runner/support两份源码哈希已记录在完整报告中。

目录清单仅包含本次profile、启动脚本、报告、微型哨兵和uv专项缓存；没有生成Lake文件、DG实例或SQLite数据库。已导入真实资源及其模块级资源声明，但没有调用正式执行图、资源连接、健康探针、job或checks；没有读取正式运行状态、恢复sensor或安装/卸载依赖。不得把本次I03通过推广为I04–I08、实际adapter、S1全套回归或S2真实数据验收通过。

交付范围：本轮修改runner/support及原LLD、技术方案、主索引；既有八例文件未改。CodeGraph `explore`核对了测试工厂/路径核验/策略入口，通用`run`的同名图边以本次实际源码为准；没有跨子系统依赖或业务接口变更。原有业务已跟踪差异SHA256仍为`f94f46dae3117fa76d1bb8ac6a280edc5c43eb9a379ec70eeb56f6b61d09a4d2`，五份原有未跟踪业务源码/测试哈希也保持一致；wealth及其他任务文档未修改。

I03收口后停在独立验收点；下一步为I04的缺失文件/错误类型/路径越界测试，不自动推进业务adapter。当前没有新增待拍板项；本次临时根和前两次失败现场继续纳入§18.11最终精确清理，当前尚未执行清理。未提交、未推送。

交付检查：orchestrator全量`src/tests`的Ruff致命错误基线、三份专项测试文件默认Ruff检查、文档完整性三项及`git diff --check`均通过；这些静态结果与I03实际8/8结果分别记录，不替代未运行阶段的验收。

<a id="s1-isolation-i04-input-paths"></a>

### 18.14 I04：测试输入的文件与路径边界

管理员要求继续I04；起点为`dev-interface@ff72d48f`及原有未验收业务改动。本轮只修改§18.2前三个测试文件并同步方案/索引，不修改正式合同、checks、共享资源、writer或消费者。I04验证的是测试侧输入保护；真实checks的`input_path`失败阶段及instance/连接/writer零调用仍须在adapter阶段独立验收，不能用I04替代。

#### A. 实施约束与代码落点

| 约束 | 精确落点及验收 |
| --- | --- |
| 保留I03资源构造可指向尚未创建的临时根 | `make_confirmed_test_resources`行为不变，原八例完整回归；不把“构造资源”改成自动建目录或必须有输入文件 |
| 读取测试输入前必须存在普通根目录及普通文件 | support增加`checked_test_input_file(path, *, lake_root)`，先做纯路径范围检查，再检查根和文件的存在性/类型；缺根、缺文件、根为文件、目标为目录分别给出准确错误 |
| 不接受`..`、越界或符号链接 | 复用`checked_test_path`，提取纯词法检查供两个入口使用；在任何路径IO前拒绝词法越界，逐组件检查原路径的链接身份，不调用`resolve`把链接洗成合法路径 |
| 只验证拒绝，不修复现场 | 检查期间open、mkdir、rename/replace、unlink、resolve及健康探针均用失败spy拦截；允许真实lstat读取合法组件，不允许沿链接访问禁止目标。检查前后虚构文件集合、身份、内容一致 |
| 固定且有界的测试清单 | I04恰好8例：普通文件正向、缺根、缺文件、根为文件、目标为目录、`..`越界、目标文件链接、父目录链接。链接和越界只指向本次虚构禁止目录；I03八例不改断言，总计16例 |
| 不扩大隔离能力 | runner沿用I03的同一profile/源码白名单/环境和启动argv，仅报告改为I03–I04及16例；源码之外没有新增读取、写入或网络权限。adapter仍硬拒绝 |

测试只在当前`allowed/`生成少量文本和链接样本；不是Parquet字段检查、不建DG实例/SQLite、不连接DuckDB、不发源请求、不读取CSV或正式Lake。每例30秒、批次60秒、fixture总量1MiB及工作区100MiB上限不变，预计秒级；业务对象/日期/分区/请求/分页/扫描/业务写入/事件/spill均为0。全部临时产物按§18.11最终精确清理，不安装套件。

CodeGraph `explore/search/callers/impact`核对了测试路径入口；开工时`checked_test_path`只有测试资源工厂调用，本轮新增测试输入前置检查调用，影响局限于support及测试，不涉及前端/API或跨子系统依赖。`explore`对宽泛名称返回的无关同名图边未作为依据，已用精确符号和当前源码补核。真实资源继续按[Dagster官方资源测试文档](https://docs.dagster.io/guides/build/external-resources/testing-configurable-resources)直接构造，不修改正式资源初始化方式。

执行目录和父入口沿用§18.13 B；runner在受限子进程启动前输出完整argv/profile及当次随机根。先做当次OS小型自检，再完整执行I03/I04；失败即停止，不自动加权限或推进I05/adapter。实际结果在运行后记录，当前不能将本段设计算作通过。

#### B. 2026-09-07 17:27 实测与对账

本次仅启动一次，全新根为`/private/tmp/stock-suspend-isolated-zxqbe2iy`。I04 **8/8**，I03回归 **8/8**，合计16 passed、0 failed、0 skipped；pytest耗时0.81秒，整批1,214毫秒、退出码0、stderr为空。四条既有Dagster/Pydantic弃用警告保留。当前源码SHA256与运行报告逐一匹配；I03三个测试函数及参数化与`ff72d48f`的AST完全一致，没有改断言。

| I04样例 | 真实结果 | 不跟随链接的属性读取次数 |
| --- | --- | ---: |
| 普通文件 | 返回原路径，不读取内容或改变现场 | 9 |
| 缺根 | `test_lake_root_missing` | 4 |
| 缺文件 | `test_input_file_missing` | 9 |
| 根是文件 | `test_lake_root_not_directory` | 4 |
| 目标是目录 | `test_input_not_regular_file` | 9 |
| `..`指向虚构禁止目录 | `outside_test_root`，任何路径IO前拒绝 | 0 |
| 目标文件为链接 | `symlink_not_allowed`，停在链接对象 | 8 |
| 父目录为链接 | `symlink_not_allowed`，不访问链接下的目标 | 8 |

上述八例的open、mkdir、rename/replace、unlink、resolve和健康探针调用均为0；每例虚构文件集合及dev/inode/mode/size/mtime_ns/内容或链接文本前后相同。当前CPython 3.13的`Path.lstat()`实际委托`os.stat(follow_symlinks=False)`，因此测试在这个真实入口计数并要求不跟随链接，不能把所有`stat`一律禁止后让合法lstat也失败。此处仅核验调用边界，没有修改标准库或业务健康函数。

当次OS小型自检为允许区Python读写/C open成功、禁止区七项拒绝成功；不是完整I01/I02重跑。与上次I03成功profile替换随机根后逐字相同，源码白名单和权限没有变化。禁止区34字节哨兵身份/内容不变；整个现场92KiB，没有超时或空间/输出超限。无Parquet、DG实例或SQLite库，无正式Lake/staging读写、事件写入、sensor恢复、依赖安装/升级/卸载。

证据：[完整运行报告](/private/tmp/stock-suspend-isolated-zxqbe2iy/allowed/resource-result.json)、[16例汇总](/private/tmp/stock-suspend-isolated-zxqbe2iy/allowed/pytest-result.json)、[实际策略](/private/tmp/stock-suspend-isolated-zxqbe2iy/allowed/capability.sb)。策略SHA256为`8662865953c9f307c3e1eabdf183abfbdd8eaf4f1fc71369147f297ef641f66f`；三份测试源码哈希及逐例原因/调用路径在报告中。该精确临时根纳入§18.11最终清理；本轮不提前清理证据或其他任务环境。

交付范围为三个测试文件、本文、技术方案和主索引。原有业务已跟踪差异SHA256仍为`f94f46dae3117fa76d1bb8ac6a280edc5c43eb9a379ec70eeb56f6b61d09a4d2`，五个原有未跟踪业务源码/测试保持原哈希；Wealth及其他专项文件未改。无依赖矩阵、正式资产/资源/check/分区或数据字段变化。

交付检查：orchestrator全量`src/tests`的Ruff致命错误基线、三份专项测试文件默认Ruff检查、文档完整性三项及`git diff --check`均通过；CodeGraph同步后确认索引已是最新。未运行正式Definitions加载或业务测试。

验收状态分开记录：文档及静态检查通过；隔离I01–I04已通过；I05–I08、实际adapter、S1实现/合成全套回归、S2生产批准集合和S2全范围等价均未完成。下一步仅I05临时DuckDB设置与默认资源误用测试，不自动推进；本轮未提交、未推送。

<a id="s1-isolation-i05-duckdb-settings"></a>

### 18.15 I05：临时DuckDB设置与默认资源拒绝

管理员要求先提交I04、再推进I05。I04六文件已提交为`c8ab3bb4`，没有推送；其他未验收业务改动保留。本轮仍仅修改三个专项测试文件及LLD/技术方案/索引，不进入I06、adapter或正式运行。

#### A. 代码事实、实施矩阵与预算

CodeGraph `explore/impact`及当前源码确认：`DuckDBResource.connect()`调用`resources.connect_configured_duckdb()`；实际统一函数先执行默认temp的`mkdir`，再连接数据库。它有大量现行消费者，I05不改生产函数、默认16GB/4线程/512GB spill及其配置来源。当前两份未验收业务测试另有直接`:memory:`连接和`IsolatedDuckDBResource`，仍留待adapter阶段归并，不在I05运行或修改。

| 硬约束 | 本轮落点及测试 |
| --- | --- |
| 测试资源集中且延迟构造 | support的`make_confirmed_test_resources`保留原签名及真实Lake根核验，增加DuckDB测试子类对象；只在受限上下文中定义/构造，不在父进程导入业务，不因构造资源而mkdir/连接 |
| 六项设置必须实际生效 | `connect_confirmed_test_duckdb(*, temp_directory)`只接受显式当前临时路径；配置固定`:memory:`、512MB、2线程、0B spill、自动安装/加载扩展均false。路径检查后仅创建该临时temp；连接后通过`duckdb_settings()`精确读取六项，全部匹配才yield，失败或退出均close |
| 不把显示单位差异误判成配置错误 | 当前既有DuckDB 1.5.2及I02实测将512MB显示为`488.2 MiB`、0B显示为`0 bytes`；测试侧按这两个已核显示值精确对账，不采用宽范围数值容差。若环境变化导致表示不同，先核验再调整，不能跳过设置校验 |
| 默认正式入口在副作用前拒绝 | OS自检后、collection前，只在受限子进程替换`resources`及`duckdb_connection`两个模块的统一连接引用为显式拒绝函数；实际默认资源的connect仍执行到这个保护。0个正式默认目录IO、0次原生connect；不是改生产源码或默认资源行为 |
| 正常连接必须真实，错误必须准确 | 正向用工厂返回的DuckDB子类，读回六项、执行两行虚构VALUES、确认退出后连接关闭且temp无文件。线程1/内存256MB的错误用真实低配连接注入；temp/spill/两项扩展开关错误仅注入真实settings查询后的读回行，不真的开放危险设置。六例必须在yield前报出具体错误字段并关闭连接 |
| 参数与入口反例 | 临时连接的缺参数、错参数名、正式temp字符串3例均在IO/原生connect前拒绝；默认资源、实际类忽略错误temp参数、两个统一函数引用共4例准确拒绝，路径IO及原生connect均0 |
| 单批不超16例，不开放任意选择 | runner把已存在执行体提取为固定批次函数，顺序执行I03–I04的16例和I05的14例；每批全新随机根、独立受限进程/报告/OS自检。测试节点清单和数量只在runner声明，传给support；不新增CLI选项、不接受任意路径/SQL/pytest参数，不用`-k`挑过失败项。前批失败不启动后批 |

两批沿用§18.13 B的同一父入口和profile白名单，不新增权限、依赖或源码文件。每批启动前展示完整argv、精确根、profile和测试节点；每例30秒、每批60秒、工作区100MiB及fixture1MiB上限不变。I05最多7个串行内存连接，验证查询只读取六个设置及两行虚构值，无业务对象/日期/分区、源请求/分页、Parquet扫描/写入、事件或spill；预计秒级，只留下空temp目录与报告。所有本轮临时根纳入§18.11最终清理。

依据：[DuckDB配置及设置读回](https://duckdb.org/docs/current/configuration/overview)、[Python连接配置](https://duckdb.org/docs/current/clients/python/overview)、[Dagster资源测试](https://docs.dagster.io/guides/build/external-resources/testing-configurable-resources)。DuckDB文档技能包含安装扩展步骤，本轮依管理员禁止安装要求未执行，直接查阅官方文档和现有I02证据；没有安装/升级或自动下载授权。

没有新增业务拍板项；若遇到额外权限、库能力或正式边界冲突，立即停止，不临场放宽。以下实际结果只覆盖本节，不把隔离验收扩大为业务验收。

#### B. 实测结果与证据

2026-09-07 18:03（北京时间），按§18.13 B固定父入口一次运行两个固定批次。I03–I04收集并通过16/16，I05收集并通过14/14；没有跳过、xfail或失败后放宽重试。两个子进程都先通过原生正向及7项拒绝自检，退出码0、stderr空、无超时/空间/输出限制触发；禁止哨兵的文件身份和内容前后相同。

| 批次 | 结果与关键证据 | 整批耗时 / 现场占用 |
| --- | --- | --- |
| I03–I04回归 | 16/16；新增DuckDB资源和默认入口拒绝保护未破坏原有根校验、输入路径和零探针断言 | 1,234毫秒 / 92KiB |
| I05正常连接 | 工厂返回真实DuckDBResource子类；六项实际设置全部一致，两行VALUES准确读回，退出后查询报连接已关闭，temp为空 | I05共923毫秒 / 60KiB；pytest用例本体0.10秒，不把启动开销漏掉 |
| I05设置错误6例 | 线程/内存的实际低配连接，以及其他四项明确标记的读回故障，均报出对应字段；没有yield给调用方，底层7个连接（含正向）均关闭，7个temp目录均无文件 | 纳入上述I05批次 |
| I05参数错误3例、正式入口4例 | 缺参数/错参数/正式temp，以及真实默认资源、被忽略的错误配置参数、两个统一函数入口，均准确拒绝；stat/lstat/mkdir/open和原生connect调用均0 | 纳入上述I05批次 |

正常连接实际值：`memory_limit=488.2 MiB`、`threads=2`、`max_temp_directory_size=0 bytes`、`temp_directory=/private/tmp/stock-suspend-isolated-_jxmnpwc/allowed/duckdb-temp`、两项扩展自动安装/加载均`false`。实际使用既有DuckDB 1.5.2，没有安装或升级。8条Dagster/Pydantic弃用警告来自默认空字段资源触发既有`pydantic_compat_layer.py:74`的`__fields__`读取；已核当前源码，保留警告，不改或升级共享库。

报告：[I03–I04回归](/private/tmp/stock-suspend-isolated-owijtk9c/allowed/resource-result.json)、[I05验收](/private/tmp/stock-suspend-isolated-_jxmnpwc/allowed/resource-result.json)。两份报告包含完整argv、策略、源码哈希、逐例原因与调用计数、禁止区前后清单。对应策略SHA256分别为`871fe9ceb9f0e5eeba9664b2cf03b1f1c409ac19796bd897f2c94254a684054e`、`72bc81efcd6726aa543a8964a0f97d6ba3c2b17f134d0aa49d9ff7477ae5481e`；除各自随机根字符串外，与§18.14通过的策略逐字一致，源码读取白名单不变。

本轮验收源码SHA256：

- `stock_suspend_confirmed_test_runner.py`：`d217f498ab39801b4f7f38bdd802adc62ba14afbea5233f33f4a5eaa89665831`
- `stock_suspend_confirmed_test_support.py`：`2ae30dce3542e21785078051a097d7684766e38e4c4510f084b2595385917db6`
- `test_stock_suspend_confirmed_isolation.py`：`145440bc0be40c7d4e6cc0b6e6e570d96fce4b8965837cf41686db60b1729332`

验收后再次比对上述源码与报告哈希一致；既有业务源码差异及五份未跟踪专项文件的哈希保持不变。本轮只改三份测试文件和LLD/技术方案/索引；CodeGraph `explore/impact`覆盖共享连接、真实资源与测试工厂，`sync/status`确认最新，不改变子系统边界或依赖矩阵。没有运行正式Definitions加载、实际checks/业务测试、文件发布或sensor恢复；没有创建DG实例、SQLite数据库或Parquet文件，没有依赖安装/自动下载。两处新增现场纳入§18.11最终精确清理，本轮不提前删除证据。

交付检查：orchestrator全量`src/tests`的Ruff致命错误基线及三份测试文件的默认Ruff均通过；文档完整性三项、三份文档315个本地链接及17个显式锚点、围栏和`git diff --check`均通过。补充链接校验首次把`:行号`当成路径的一部分而报错，修正校验器解析后通过，没有为此改动源链接或放宽文件存在性要求。

验收分项：文档/静态检查通过；隔离I01–I05通过；I06–I08、实际adapter、S1实现/合成全套回归、S2生产批准集合及S2全范围等价仍未完成。下一步仅I06：临时实例身份、默认实例发现拒绝及网络/Unix socket隔离，仍限本机虚构端点与临时实例，不安装套件，不操作正式实例；本轮不自动启动。I05增量未提交、未推送。

<a id="s1-isolation-i06-instance-network"></a>

### 18.16 I06：临时实例身份和网络拒绝

本轮指令为“提交修改，然后推进下一步”。I05六文件已提交为`73de21f1`，未推送；仅推进§18.5 I06，仍不修改业务源码或运行实际checks/Definitions。代码、文档白名单沿用§18.15的六文件，不安装依赖，不改变正式Lake/实例/网络配置、共享资源及隔离profile。

#### A. 编码前约束、真实调用链和验收矩阵

CodeGraph `explore/impact/node`核对专项runner/support和消费者；同名`run`的图结果混入无关模块，已用精确文件的`node`校正，不据此扩大范围。当前既有Dagster 1.13.18源码确认：`DagsterInstance.local_temp → factory.create_local_temp_instance → InstanceRef.from_dir → create_instance_from_ref`；默认`get → create_instance_from_dagster_home`会读取环境。`from_config`也会读取配置并实例化存储。因此保护在collection之前安装，只允许明确临时根及固定关闭遥测的local_temp调用；无默认根回退。

| 硬约束 | 代码落点 / 验收 |
| --- | --- |
| 唯一专项临时实例工厂 | support新增`make_confirmed_test_instance(*, instance_root)`，调用真实`DagsterInstance.local_temp`；子进程包装SDK的`create_local_temp_instance`，先检查显式根在allowed内、无符号链接、overrides恰为关闭遥测、根内无`dagster.yaml`，再创建临时目录及实例。保护仅存在于受限进程，不修改安装包 |
| 不能只核对传入的路径 | 创建后先核真实类型、persistent标志、root、telemetry，以及实际event/run/schedule存储类型与连接路径；全部静态路径匹配才依次打开三个真实连接，用`PRAGMA database_list`读回main路径。任一不符立即dispose，不把实例交给测试 |
| 真正的本地持久化正例 | 一处临时instance，两次打开；写一条明确synthetic的无分区runless materialization，不选择业务asset/job、不注册动态分区。关闭后重新打开，同key、limit=2读回恰好一条、相同storage_id和metadata。三种存储main路径分别为`history/runs/index.db`、`history/runs.db`、`schedules/schedules.db`；逐种错误路径故障注入在打开连接前被拒绝，原连接调用0 |
| 反例必须在副作用前拒绝 | 5例local_temp参数/配置错误：缺根、错参数名、正式home字符串、错误overrides、根内已有配置文件；4例默认入口：实际`get`、factory默认home入口、实际`from_config`、实际`from_ref`。默认入口拒绝函数和local_temp路径包装在collection前生效；用例内再以spy核验拒绝前无IO，正式home仅作字符串，文件/配置内容读取和实例创建0 |
| Python网络调用提前拒绝 | socket `connect`、`connect_ex`、`create_connection`、`getaddrinfo`在collection前拒绝；4例覆盖TCP connect/connect_ex/create_connection和Unix connect。无DNS、无真实数据库地址 |
| 原生网络不能被Python替身掩盖 | runner标准库父进程只为I06建立一个随机loopback TCP监听和一个当次allowed内Unix socket；父进程前后各一次同端点握手、收发固定一字节，证明端点可达。子进程保存原生socket连接方法，只在两个独立OS反例调用，要求EPERM/EACCES，不能用connection refused/timeout当隔离成功；父进程确认无意外待接受连接，finally关闭两个监听，不启动服务/线程、不放宽子进程网络权限 |
| 保留单批规模和停止门 | 固定三批：I03–I04 16例、I05 14例、I06 16例，各自全新根。父runner不导入业务/数据库库，listener FD不继承；support只接收该批父进程给出的虚构端点，不新增CLI参数。任一失败即停，不进入I07/I08或adapter |

配置审计：新增的instance_root由专项用例在本批allowed下显式给出，无env来源和默认home；唯一overrides为`telemetry.enabled=false`，support设置并实际读回；不允许用户透传storage/DSN等配置。TCP端口由loopback的端口0绑定分配、Unix路径由随机根派生，仅在同批报告与子进程内部传递；无固定端口、无系统配置和持久服务。已有正式SDK默认值不变。

预算：只有1个synthetic事件、0业务对象/日期/分区、0源请求/分页、0Parquet/正式文件读写；最多1个临时实例目录、2次创建/关闭，读回每次limit=2。默认三库及runless事件库由SDK按需建立，含WAL/SHM和日志预计低于10MiB，硬上限仍为单批100MiB/fixture1MiB、每例30秒/批次60秒；失败不扩空间/权限重试。TCP/Unix父正向各前后1次一字节往返，连接超时1秒；子原生拒绝各1次。新16例及原30例预计秒级，无DuckDB新增扫描/join/COPY/spill，无数据库配额影响；临时写入由SQLite短事务管理，不做正式迁移或数据库清理。所有临时实例、测试库、Unix socket节点和报告纳入§18.11最终清理。

依据：[Dagster实例API](https://docs.dagster.io/api/dagster/internals)、[实例配置与遥测](https://docs.dagster.io/deployment/oss/oss-instance-configuration)，结合当前安装包`instance/instance.py`、`instance/factory.py`、`instance/ref.py`及三种SQLite storage实现核验。网上当前版本较本机新，不据其改变依赖；以本机源码和本轮受限实测为准。

#### B. 2026-09-07 18:59 实测与计划对账

按§18.13 B固定父入口一次执行三个固定批次，无失败重试或权限追加。I03–I04为16/16、1.293秒；I05为14/14、0.940秒；I06为16/16、1.692秒（其中用例本体0.70秒）。均退出码0、stderr空，无skip/xfail、超时/空间/输出限制触发。三批启动时均重新通过原生正向及7项拒绝自检，禁止哨兵身份和内容前后相同。

| I06计划项 | 当前代码和实际结果 |
| --- | --- |
| 实例身份及持久化 | `make_confirmed_test_instance`调用真实SDK工厂，三类存储的真实连接读回路径均在本批`allowed/instance`；遥测关闭。同一临时目录关闭后重开，仍只有1条synthetic事件，storage_id=1，metadata一致、无分区，job run记录0 |
| 三种错误存储路径 | 逐种注入错误连接路径，核验函数均准确拒绝；三个存储连接入口调用均0，没有生成wrong.db。故障只改变路径声明，不把实际数据库搬到错误路径 |
| 5例错误参数/配置、4例默认发现 | 缺根/错误关键字/正式home字符串/错误overrides/根内配置分别报出规定原因；实际get/from_config、默认home工厂和from_ref均在环境与文件读取、实例创建前拒绝。已有配置反例只允许检查文件是否存在，不读配置内容 |
| 4例Python网络拒绝 | TCP connect/connect_ex/create_connection及Unix connect均提前抛出network_forbidden_in_test；DNS调用0。保护只安装在受限子进程，不改共享库或安装包 |
| 2例OS原生网络拒绝 | 对同批虚构TCP/Unix端点，保存的原生socket连接方法均返回EPERM(errno=1)；不是connection refused或timeout。父进程在子进程前后都能向同端点完成一字节往返，且无意外待接连接。结束后两个监听均关闭；只读lsof未见该端口或socket的占用 |
| 预算与剩余现场 | 三处根磁盘占用分别92KiB、60KiB、492KiB；I06实例含4个SQLite文件共428KiB，无残留WAL/SHM。第四个是SDK以空RUNLESS_RUN_ID命名的`history/runs/.db`，不是额外业务实例。没有Parquet、正式对象/日期/分区或源请求 |

报告：[I03–I04回归](/private/tmp/stock-suspend-isolated-ltxrw1xe/allowed/resource-result.json)、[I05回归](/private/tmp/stock-suspend-isolated-3rbse6pc/allowed/resource-result.json)、[I06验收](/private/tmp/stock-suspend-isolated-tb6gs2o4/allowed/resource-result.json)。三份报告包含完整argv、策略、源码哈希、逐例原因、网络正向控制及禁止区前后清单。将随机根归一后，三份profile与§18.15逐字相同，源码读取白名单不变；I06策略SHA256为`2f2c001f6c6ac954751f313067cfc65d774015b0b064a062573dc7a4050e38da`。

验收源码SHA256：runner为`1186516ce3b2e6dcbf9e754a27e4cc29858c854567de9b463f35e746cf0bac7e`；support为`7b1582854b2a89016fd0f7988a6319c437971611bc79d54347517a744d396f1b`；isolation用例为`16b5949efaf3cf27dd37acc1bcd993e06abd5b72091730ad6655e4e9f76211ee`。运行后再次核对与磁盘源码一致；既有业务差异哈希及五份未跟踪专项文件哈希未变。I05回归仍有8条既有Dagster/Pydantic弃用警告，I06没有新增警告；未屏蔽警告或升级依赖。

本轮三个新增根`/private/tmp/stock-suspend-isolated-ltxrw1xe`、`/private/tmp/stock-suspend-isolated-3rbse6pc`、`/private/tmp/stock-suspend-isolated-tb6gs2o4`均登记为§18.11最终精确清理对象，含临时实例、4个数据库、配置反例、socket节点、报告和缓存；本轮保留证据，不提前删除，也不永久保留测试实例。没有创建DG webserver/daemon、安装或卸载套件、恢复sensor或操作正式数据。

仅修改三份测试文件及本LLD/技术方案/主索引；CodeGraph分析覆盖专项入口、SDK工厂调用、资源及测试消费者，已sync/status确认最新。无子系统边界或依赖矩阵变化。交付检查：三份测试的默认Ruff、全量src/tests致命错误基线、文档完整性三项、三份文档319个本地链接/18个显式锚点、围栏及git diff --check均通过，不将静态检查替代运行验收。下一步仅I07的提前保护、策略/scope错误及导入期越界验证，仍不进入I08或实际adapter。本轮I06增量未提交、未推送，I07–I08、S1业务验收和后续生产阶段仍未完成。

<a id="s1-isolation-i07-startup-collection"></a>

### 18.17 I07：启动拒绝与导入期隔离

I06已按管理员指令提交为`99e73ccf`，未推送。本轮“继续推进”只进入§18.5 I07；不运行I08、尚未修正的两份业务测试或正式Definitions，不安装依赖、不扩大隔离权限。沿用前三批46例回归，再执行以下15项I07验证；没有任意脚本或pytest参数透传入口。

#### A. 编码前核对与实施约束

CodeGraph `explore/impact`及精确文件`node`核对runner → support.run → OS自检 → 资源导入 → pytest collection的顺序；图中泛化同名run误连无关研究模块，已排除。当前`require_isolated_context`在未初始化时直接报错；`run`先核导入时机、继承环境、解释器标志、profile哈希并执行当次原生自检，随后才设置允许根。现有runner同时要求退出码、完成数、pytest判据和禁止区不变，不能只读历史passed标志。

| 验证项 | 精确实施 / 判据 |
| --- | --- |
| scope错误5项 | 在标准库父进程调用实际main/parser，分别传缺scope、缺值、未知值、尚未开放的adapter、额外pytest参数。捕获实际SystemExit(2)及对应原因；临时目录创建、mkdir、Popen调用spy均0。不是运行业务测试或启动嵌套runner |
| guard_missing | 新受限子进程只加载标准库support，直接导入现有isolation测试文件，必须在require_isolated_context处拒绝；Dagster/DuckDB/orchestrator/pytest均未导入 |
| guard_late | 新受限子进程先真实导入pytest，再调用实际support.run；必须报protection_loaded_too_late，允许根未设置，Dagster/DuckDB/orchestrator未导入。不是用假模块冒充晚加载 |
| policy_missing / policy_invalid | 分别以不存在的profile、仅含版本及故意未定义规则I07_INVALID_PROFILE的文件调用真实sandbox-exec。必须在解释器payload启动前失败，stderr对应精确文件缺失/未定义规则；不接受任意非零退出、信号或超时。payload仅标准库及虚构标记，绝不在策略失败后回退启动 |
| policy_mismatch | OS仍使用正常profile，调用support.run时传错误哈希；必须在资源/pytest导入前报policy_mismatch。不是修改实际权限 |
| selfcheck_failed_stale | 在新根预放明确虚构的passed=true旧结果，再仅对本次support的自检函数注入固定失败；实际run必须拒绝且允许根仍未初始化，资源/pytest未导入，正常资源验收判据仍为false。该项证明失败传播和旧标记无效，不冒充真实OS权限反例 |
| collection_allowed / collection_denied | 父进程在各自新根生成同结构微型pytest文件和同内容文本；真实support/pytest完成导入。正例读allowed后执行1个空业务测试体；反例在模块导入期读本次denied哨兵，记录真实OSError.errno/路径并重新抛出，pytest collection失败，导入完成标记与测试体标记均不存在。只能认可EPERM/EACCES和对应目标；不选择实际asset/check/job |
| skip / xfail | 两个明确故障样例分别被pytest跳过/标记预期失败；即使pytest返回0，实际完成数0、失败/跳过计数1，专项资源验收仍必须false，不能冒充正常通过。只作为验证拒绝判据的反例，不用它们替代缺失的正常用例 |

仅改`tests/stock_suspend_confirmed_test_runner.py`、`tests/stock_suspend_confirmed_test_support.py`及本文/技术方案/主索引；已有isolation测试文件保持不变但参与回归与提前保护验证。runner复用既有有界子进程执行和报告逻辑，增加内部固定I07清单、微型collection样例及精确判据；support提供仅标准库的提前拒绝验证入口，collection仍走实际run，不能替换pytest收集或OS文件IO。所有新增设置只在专项测试内部，不增加CLI选项、env、共享配置或生产字段。启动器在每个子进程前输出完整argv、profile、真实根和本项预期，不只报最终绿灯。

预算：I07共15项，其中5项纯标准库参数验证、10个串行新子进程；每个子进程独立新根，另有1处汇总根，绝不复用旧pytest目录。每个collection样例最多1个测试体、1个微型文本读，业务对象/日期/分区、源请求/分页、Parquet/DuckDB查询、新实例/数据库/事件写入均0；原I06回归仍只使用自己的1处临时实例/1条synthetic事件。I07预计低于15秒、总现场低于2MiB；每个子例30秒，整个I07批次60秒，全部I07根合计100MiB、虚构fixture合计1MiB、单子进程stdout/stderr各64KiB。超限或不符即停，保留失败证据，不放宽权限/判据重跑。标准回归仍按16/14/16分批和既有预算执行。临时标记、故意错误profile、测试样例及报告全部登记§18.11最终清理，无新常驻服务。

本机sandbox-exec手册明确-f读取指定策略并在策略下执行命令；已核当前pytest的main与ExitCode实现，并参考[pytest调用及早期插件机制](https://docs.pytest.org/en/stable/how-to/usage.html#calling-pytest-from-python-code)、[退出码说明](https://docs.pytest.org/en/stable/reference/exit-codes.html)。collection错误可能通过pytest的中断或节点选择错误出口报告；必须结合准确的权限错误、导入阶段标记和零测试体执行，而不是仅接受某个退出码。

#### B. 2026-09-07 19:20 实测与计划对账

按§18.13 B固定父入口一次运行，无失败重试或权限追加。原I03–I04为16/16、1.223秒，I05为14/14、0.929秒，I06为16/16、1.654秒；I07为15/15、4.103秒。这里的15项指“启动拒绝与验收判据检查通过”，不把其中故意失败/跳过的子pytest算作正常资源验收通过；报告分别记录`passed`与`resource_gate_passed`。

| I07硬口径 / 代码点 | 实际证据 |
| --- | --- |
| `run_startup_gate_batch`：错误scope不启动 | 缺参数、缺值、未知值、adapter、额外参数5项均实际SystemExit(2)，原因准确，mkdir/mkdtemp/Popen调用均0 |
| `probe_startup_gate`：保护先于资源与collection | 缺保护报`isolation_not_initialized_before_collection`；真实pytest先导入报`protection_loaded_too_late`。两项均退出1、允许根未初始化，前者无四类模块导入，后者仅pytest；无业务执行 |
| `run_isolation_child`：真实策略加载失败不能回退 | 缺失/无效profile均由sandbox-exec返回65，分别为精确missing.sb缺失、invalid.sb第2行未定义规则；payload启动标记、pytest结果和proof均不存在，非崩溃或超时 |
| `run`：错误哈希、自检失败不能被旧记录掩盖 | 错哈希准确报`policy_mismatch`；明确故障注入自检恰好调用1次后失败。两者均在资源/pytest导入前退出1；后者即使保留虚构passed=true旧JSON，`resource_gate_passed`仍false |
| `prepare_startup_fixture` → 实际`run/pytest`：导入期IO边界 | 正例读allowed，collection和测试体标记齐全、完成1例，退出0、资源验收true；反例真实读取当次denied哨兵返回EPERM(errno=1)，退出4、完成0例，collection结束及测试体标记均不存在，资源验收false。没有用任意非零退出代替权限证据 |
| `evaluate_startup_probe`与实际pytest计数：不接受skip/xfail | 两个故意样例均退出0，但实际完成数0、失败/跳过计数1，测试体未运行，资源验收false；stdout分别确认1 skipped/1 xfailed。只有对这一拒绝行为的I07检查为true |
| 原有安全范围不变 | 13份子进程报告的正常profile随机根归一后均与§18.16基线逐字相同，读取白名单、环境白名单和生产默认值不变；两项策略加载反例另存实际选用的错误profile，绝无回退。全部禁止哨兵内容、身份、时间前后相同，无时间/空间/输出超限 |

汇总报告：[I07全部15项及精确子报告路径](/private/tmp/stock-suspend-isolated-xd177k63/allowed/startup-result.json)。原回归报告：[I03–I04](/private/tmp/stock-suspend-isolated-w8vslr4i/allowed/resource-result.json)、[I05](/private/tmp/stock-suspend-isolated-f7wo9vlx/allowed/resource-result.json)、[I06](/private/tmp/stock-suspend-isolated-iuxuac53/allowed/resource-result.json)。10个I07子进程逐个保存实际argv、policy、预期判据、stdout/stderr及proof；汇总在每项完成后落盘，不只保留末尾绿灯。

验收源码SHA256：runner为`55086e62a25f849bfb3e786131f4aaded7e4eee75300fa0945b64e87f19aa2e7`；support为`10e766fa6587c690a5f0018d6d0a5bf67e600d58db51a862282e55001f59f1a0`；未修改的isolation用例为`16b5949efaf3cf27dd37acc1bcd993e06abd5b72091730ad6655e4e9f76211ee`。运行后逐报告核对源码哈希一致；既有业务差异哈希及五份未跟踪专项文件哈希均未变。I05仍有8条既有依赖弃用警告，未屏蔽或升级环境。

I07的11处根共592KiB磁盘占用，普通文件合计232,567字节；四个生成测试文件共2,754字节，没有Parquet/数据库/实例/事件。原I06回归单独占496KiB，仍只有1条synthetic事件、0 job run，实例关闭重开后读回一致，4个SQLite文件共428KiB，无WAL/SHM残留。loopback端口55193、Unix socket及instance文件的只读lsof复核均无占用；不复连端点、不启动服务。

本次新增14处根逐一登记为§18.11最终精确清理对象；此处是穷举清单，不授权按通配符删除。清理包括其中的故意错误profile、微型测试、标记、报告、临时实例/数据库、socket节点及缓存，本轮不提前删除证据：

```text
/private/tmp/stock-suspend-isolated-w8vslr4i
/private/tmp/stock-suspend-isolated-f7wo9vlx
/private/tmp/stock-suspend-isolated-iuxuac53
/private/tmp/stock-suspend-isolated-xd177k63
/private/tmp/stock-suspend-isolated-43e714fe
/private/tmp/stock-suspend-isolated-e9ypg9ti
/private/tmp/stock-suspend-isolated-8keu73ft
/private/tmp/stock-suspend-isolated-6t9odx0p
/private/tmp/stock-suspend-isolated-myaqc7_5
/private/tmp/stock-suspend-isolated-m2fpa63_
/private/tmp/stock-suspend-isolated-ts2oql0v
/private/tmp/stock-suspend-isolated-0_o59hck
/private/tmp/stock-suspend-isolated-2_c32rg7
/private/tmp/stock-suspend-isolated-zbr5tqrk
```

交付静态检查：两个变更测试支持文件默认Ruff、全量src/tests致命错误基线、文档完整性三项、三份文档324个本地链接/19个显式锚点、围栏及git diff --check均通过；CodeGraph sync/status为最新。上述检查不替代15项真实启动验证与46例回归。

本轮仅改runner/support两个测试支持文件及本LLD/技术方案/主索引，未改实际业务代码、生产字段、子系统边界或依赖矩阵；不安装套件、不创建DG服务、不操作正式实例/数据或恢复sensor。下一步仅I08：在当次虚构临时范围调用真实共享健康helper，核验其探针副作用可被准确记录；不选择实际checks，不修改全局健康函数。I08及后续adapter仍未运行，不能把I07通过当S1业务验收完成；本轮增量未提交、未推送。

<a id="s1-isolation-i08-health-side-effects"></a>

### 18.18 I08：共享健康探针副作用识别

I07五文件已按管理员指令提交为`8bf5a54b`，未推送。本轮只推进§18.5的I08，完成后报告并停止；不自动打开adapter入口、不运行实际checks、不推进原S1业务实现。

#### A. 编码前核对、逐项实施与预算

当前真实调用链：`LakeRootResource.ensure_available_for_run()` → `assert_lake_root_available_for_run()` → `evaluate_lake_root_health(check_disk_space=False, check_duckdb_temp=False)`。它检查root/raw/silver/gold，创建`_tmp`和`_tmp/lake_root_health`，在后者写入、读回、删除一个随机`canary-<uuid>.txt`。因此这不是只读路径：即使已有目录、最终文件列表相同，仍发生探针写入与删除；首次调用还会留下两级目录。该入口不执行磁盘空间检查或DuckDB temp探针，不能把完整平台health的另一分支扩大进本轮。

CodeGraph `explore`泛化名称返回了无关health/check，已排除；以精确源码核验真实链，再用`impact(assert_lake_root_available_for_run, depth=2)`确认共享入口有资源、资产、sensor和测试消费者（图返回133个相关符号，非调用次数）。本轮不改该共享实现、正式默认值或其他消费者。

| 硬口径 | 代码落点 / 验收判据 |
| --- | --- |
| 只读正例1项 | isolation测试构造一个微型普通文本，调用现有`checked_test_input_file`后读回。记录器应只见1次成功read_text；mkdir/write/unlink均0，完整fixture身份及内容前后相同。这是测试输入预检，不冒充尚未修改的实际checks验收 |
| 真实健康helper反例2项 | 分别使用尚无健康目录、已存在健康目录的两个新临时lake；均由既有工厂构造实际LakeRootResource并核对root，调用真实ensure_available_for_run一次。精确记录2次mkdir调用、1次write_text、1次read_text、1次unlink；每次均真正执行原Path方法，不替换健康函数或伪造成功返回 |
| 写完删除也必须识别 | write/read记录实际字节数与SHA256一致，并核对内容为规定前缀加该探针文件名中的32位十六进制token；unlink返回后目标确实不存在。最终普通文件清单/身份相同，但写入与删除证据仍保留。首次调用新增目录恰为上述两级，已有目录场景不新增目录 |
| 所有副作用仅在本case临时根 | 记录器仅在测试调用期间包装Path.mkdir/write_text/read_text/unlink；每次先用现有checked_test_path核定路径在该case root下且无链接，再调用保存的真实方法。异常记录后原样抛出，不转成通过。OS策略仍是底层边界，不依赖这个Python记录器保证隔离 |
| 不污染其他测试或正式链 | 上下文退出恢复Path方法，记录器不修改共享健康函数、资源默认值、安装包或正式文件；保存逐case JSON及stdout证据。runner沿用46例、I07十五项，再用全新子进程跑I08三例，失败即停；adapter仍无条件拒绝 |

本轮文件白名单：`tests/stock_suspend_confirmed_test_runner.py`、`tests/test_stock_suspend_confirmed_isolation.py`及本文/技术方案/主索引；support不需改动。runner仅增加固定I08选择与阶段报告，不新增CLI/环境/生产配置、文件读取白名单或权限。记录器只服务I08三个固定样例，不扩展为通用审计框架。参考[Python测试上下文替换与恢复](https://docs.python.org/3.13/library/unittest.mock.html#patch-object)、[Dagster资源职责](https://docs.dagster.io/guides/build/external-resources)，并以当前resources及health源码确定实际IO。

预算：I08只有3个case、1个新受限子进程/根、每case各自独立小目录；2次真实helper调用、2个微型canary写/读/删，3份小型证据。业务对象/日期/分区/枚举、源请求/分页/行数、Parquet文件和DuckDB scan/join/COPY/spill、实例/数据库/事件均0，无提交事务或原子提升。文本合计低于1KiB，整体fixture上限1MiB；I08预计低于5秒/现场1MiB，仍按每case30秒/批次60秒/工作区100MiB/输出各64KiB硬门禁，失败不放宽重试。原46例与I07回归使用各自既有预算，I06仍仅创建自己的1处临时实例并写1条synthetic事件。所有本轮精确根和运行残留均按§18.11最终清理，不安装套件或启动新DG服务。

执行沿用§18.13 B唯一入口和现有项目环境；启动时输出精确根、argv、完整profile与预期case，结束核验禁止哨兵及源码哈希。I08通过也须与后续adapter、S1、S2分别标注，不能自动认定业务验收完成。

#### B. 2026-09-07 19:39 实测与计划对账

一次执行完成，无失败重试或权限追加：I03–I04为16/16、1.195秒；I05为14/14、0.923秒；I06为16/16、1.620秒；I07为15/15、4.094秒；I08为3/3、0.868秒（用例本体0.04秒）。正常pytest批次无skip/xfail，I07的两项故意样例仍准确使资源验收失败而不是假通过；无超时/空间/输出门禁触发。

| 计划项 / 文件 | 实际证据 |
| --- | --- |
| 真实IO记录：isolation测试`_record_i08_path_io` | 仅在调用期间包装四个Path方法，核验case根后真正调用原方法；每项记录路径、是否完成，文本记录字节数/摘要，删除后记录不存在。退出后四个方法恢复原对象，三个独立JSON保存证据；没有替换健康函数 |
| 只读正例：`test_i08_readonly_input_has_no_side_effects` | 只有1次25字节成功读；没有mkdir/write/unlink，完整fixture身份及内容不变。证明记录器不会把只读输入误判成写入，不声称两个实际checks已只读 |
| 首次探针：`test_i08_health_probe_side_effects[first_probe]` | 真实资源调用1次；2次mkdir，新增目录恰为`_tmp`、`_tmp/lake_root_health`。随后写入62字节、读回同内容/摘要并删除canary，删除后目标不存在，既有普通文件身份与内容不变 |
| 已有目录探针：同函数的`existing_probe_directory` | 2次mkdir调用不新增目录，仍发生62字节写入、读回及删除；最终普通文件完全相同，但`readonly_contract_passed=false`，不能把自动清理误当作没有副作用 |
| 固定入口：runner.main | 46例→I07→I08，阶段各自新根；I08只选择两个函数展开3例。adapter继续无条件拒绝，最终`independent_review_required=true`、`all_isolation_accepted=false`表示尚待人工review，不代表本轮测试失败 |
| 共享代码及权限不变 | 14份子进程报告的正常profile随机根归一后均与§18.17逐字相同；读取白名单和env不变。正式health/resources/duckdb_connection哈希、既有业务差异哈希和五份未跟踪业务文件哈希均未变；没有改support、生产默认值或业务字段 |

报告：[I08验收](/private/tmp/stock-suspend-isolated-b2ll8jes/allowed/resource-result.json)、[只读IO记录](/private/tmp/stock-suspend-isolated-b2ll8jes/allowed/i08-readonly-io.json)、[首次探针IO记录](/private/tmp/stock-suspend-isolated-b2ll8jes/allowed/i08-first_probe-io.json)、[已有目录探针IO记录](/private/tmp/stock-suspend-isolated-b2ll8jes/allowed/i08-existing_probe_directory-io.json)。回归：[I03–I04](/private/tmp/stock-suspend-isolated-66cyka68/allowed/resource-result.json)、[I05](/private/tmp/stock-suspend-isolated-o_k8q9n6/allowed/resource-result.json)、[I06](/private/tmp/stock-suspend-isolated-gw__u2qr/allowed/resource-result.json)、[I07汇总及十个子报告](/private/tmp/stock-suspend-isolated-jqad3xyz/allowed/startup-result.json)。所有禁止哨兵前后身份/内容相同；I05保留8条既有依赖弃用警告，未屏蔽或升级，I08无警告。

验收源码SHA256：runner为`c78c41c0009a0f45b754f2a785e0489bf819feb55298927cbd12bd6950188246`；support为`10e766fa6587c690a5f0018d6d0a5bf67e600d58db51a862282e55001f59f1a0`；isolation测试为`1b53bc79599939e69802afbd8ffd220caccfc03751e22ebee381eaca11893ec3`。逐报告均与当前磁盘源码一致。未改的共享health/resources/duckdb_connection分别为`09550c89f3d11a2b8479e695a3d2f6987f88382c9c991795b8de67e65ee880ac`、`190df73d9afc5df9db45c5bc80aef6daf7f5cb5a11d759dc4e6ad5a034a8fca1`、`896b360665fa0882b3e98508947d3135810a30492192f7d79a7743e6da70d994`。

I08现场84KiB，三个输入文本各25字节，两次canary各62字节且已由真实helper自行删除；没有Parquet、数据库、实例或事件。原前三批现场分别96/64/496KiB，I06临时实例属于原回归范围，结束后端口56608、Unix socket和instance均无lsof占用。没有新DG服务、安装项、正式资源操作或sensor恢复。

本次15处根作为§18.11最终精确清理对象登记，包括报告、虚构样本、健康目录、I06临时数据库/socket和缓存；不按前缀通配删除，本轮保留证据：

```text
/private/tmp/stock-suspend-isolated-66cyka68
/private/tmp/stock-suspend-isolated-o_k8q9n6
/private/tmp/stock-suspend-isolated-gw__u2qr
/private/tmp/stock-suspend-isolated-jqad3xyz
/private/tmp/stock-suspend-isolated-d7a_8mfs
/private/tmp/stock-suspend-isolated-v8m4idde
/private/tmp/stock-suspend-isolated-_nqo15l8
/private/tmp/stock-suspend-isolated-yn6y_r_x
/private/tmp/stock-suspend-isolated-ydhmeuid
/private/tmp/stock-suspend-isolated-stzgexid
/private/tmp/stock-suspend-isolated-vc8s1wlq
/private/tmp/stock-suspend-isolated-jwjvlvt1
/private/tmp/stock-suspend-isolated-28brhxiz
/private/tmp/stock-suspend-isolated-oyyoo4ks
/private/tmp/stock-suspend-isolated-b2ll8jes
```

#### C. 本轮停止点与后续边界

| 验收层次 | 当前状态 |
| --- | --- |
| 文档与静态检查 | 两个变更Python文件默认Ruff、全量src/tests致命错误基线、文档完整性三项、三文档333个本地链接/20个显式锚点、围栏和git diff --check均通过；CodeGraph sync/status为最新。不替代运行证据 |
| 独立隔离I01–I08 | 分项运行证据齐全：I01/I02沿用§18.12已获批复验，本轮重跑I03–I08；按§18.6报告后等待管理员review |
| 实际adapter及C/D小样本 | 未验收；两个新checks取消探针、合同schema/content分类和受限测试改造仍是下一步，不由本轮正例代替 |
| 原S1实现/合成全套回归 | 未完成，writer/readiness/CLI等仍按原矩阵推进 |
| S2生产批准集合C01/C05 | 未执行，不以小样本代替真实4,022键验收 |
| S2全范围等价及正式发布/切换 | 未执行，真实staging与正式写入分别授权；不自动恢复sensor、删除CSV或清理环境 |

本轮只改A节五文件，未改子系统边界、依赖矩阵或正式路径。I08增量未提交、未推送；I07提交不包含既有未验收业务改动。管理员review隔离结果后，下一轮按§18.2/§18.4修改合同分类、两个新checks和C/D测试，不扩展共享健康函数或继续增加前置隔离工程。

<a id="s1-confirmed-check-adapter-acceptance"></a>

### 18.19 合同分类与实际检查验收

管理员随后指令“提交吧。继续推进。”：I08五文件提交为`79476407`，未推送；按§18.6第3步进入实际adapter，不再等待同一隔离结果的重复确认。这不是S2或正式操作授权。

#### A. 本轮实施约束（执行前）

CodeGraph explore/impact已用于合同与checks影响面分析。泛化check名称混入其他数据集、impact未解析出模块别名调用，已按当前源码补查：`load_confirmed_relation`现行消费者只有本专项两个新checks和contracts测试；writer/readiness/bootstrap尚未接入，不能称其已迁移。五列、批准常量、paths/catalog/metadata及共享resources/health/duckdb_connection不改。

| 硬口径 | 本轮代码与验收 |
| --- | --- |
| §4.1结构、计数分离 | 新增不可变inspection，唯一私有列比较，loader改接inspection、加载前后核身份；无旧签名wrapper。0/少/多行是content的row_count_mismatch；超行不加载，不伪造digest |
| §18.4只读与分类 | 两checks先路径、后一次发布查询、再连接/inspection；已识别的路径、资源、读取异常带stage/reason的Failure；schema/content用真实结果。异常捕获不覆盖yield和事件存储 |
| §18.5真实正反例 | 合成批准身份仅在fixture内替换；两测试在业务import前断言隔离，公共fixture移support。实际检查＋临时原生实例读回target；daily只改本case哨兵，5checks且无新固定mat。缺路径、无效发布、计数、换键、错schema、损坏、漂移/读错和存储故障分别验证 |
| 原权限不放宽 | adapter复用原父进程预算、env和OS自检；只增加下述源码literal读取，无仓库目录subpath、网络、正式数据或凭据访问。isolation仍使用原读取白名单 |

adapter新增精确源码读取（相对`src/orchestrator/`）：`defs/stock_suspend_confirmed_contract.py`、`defs/assets/__init__.py`、`defs/assets/stock_suspend_confirmed.py`、`defs/checks/__init__.py`、`defs/checks/stock_suspend_confirmed_checks.py`、`defs/run_contracts/asset_column_schemas.py`、`defs/run_contracts/column_schema.py`、`defs/run_contracts/asset_tags.py`、`defs/run_contracts/metadata.py`、`defs/catalog/__init__.py`、`defs/catalog/name_mapping.py`；另仅两份专项业务测试。已读实际import：catalog包仅加载name_mapping，registry是惰性加载，本次不读取lake_assets或Definitions，不允许其业务发现链。import目录对象仅literal读取，不开放其中其他文件。

runner的adapter固定分批清单不接收任意路径/参数；I07原“adapter尚未批准”拒绝例改为“错误工作目录”拒绝例，仍须在创建目录/进程前失败。支持层fixture只在adapter且OS保护已生效后注册，不改变isolation早期导入保护。每批报告完整源码哈希及实际argv/profile。

预算仍为每批≤16例、每例30秒/批60秒、512MB/2线程/0 spill、fixture≤1MiB/现场≤100MiB；源请求/分页/正式数据读写均0。每个D用例新建自己的临时实例，只写虚构发布与测试事件；不启动DG服务。超100MiB文件预算用FileIdentity尺寸注入验证，实际不制造大文件；SQL明细最多3行。控制台测试日志调至CRITICAL以避免框架调试文本淹没报告，原生事件仍完整持久化，负例核对存储及Failure详情，不能靠静默忽略错误。失败按既定门禁停下，不扩权限/资源试错。

下一停止点是本节C/D小样本结果；原S1的merge/writer/readiness/CLI及S2均另步进行。参考[Dagster检查测试](https://docs.dagster.io/guides/test/asset-checks)，实际事件接口以本机锁定SDK源码和存储读回为准；不升级SDK。

#### B. 首次adapter启动器错误与同范围修复

2026-09-07 20:18，隔离回归通过后首次运行adapter。C-encoding前4例通过，第5例开始时父runner的空间统计在`Path.is_file()`跟随pytest的`test_content_negative_cases_UPcurrent`链接处收到`OSError errno=22`，父进程异常退出；不是业务内容反例通过，也不是权限拒绝。源码显示pytest创建编号目录时会先unlink再重建current链接；旧统计先`is_file`再`lstat`，不适用于运行中变动的链接。现场为`/private/tmp/stock-suspend-isolated-1d6kxgi9`，子pytest记录4完成/0断言失败/未通过；外层退出1，资源报告只保留启动状态。只读核验该路径的进程与lsof均无占用，未启动其余5批，不读取正式数据。

本轮范围内修复runner：空间统计只对每项取一次lstat，只累计普通文件，不跟随current别名；仅忽略扫描中已消失的文件，其他异常仍失败。父monitor增加finally式子进程组回收与异常报告保存；只处理本runner创建的子进程，不碰其他服务。源码及虚构目录回归核对后再从新根执行同一adapter清单，旧现场保留为失败证据。不放开任何读取目录、网络或预算，不把这次代码修复描述为原运行通过或自动重试成功。

目录统计单独用9字节文件、正常链接、失效链接验证，禁止调用`Path.is_file`时仍正确得9字节；现场`/private/tmp/stock-suspend-isolated-fm63ra5c`。修复后C三批34例和D路径/发布11例通过；D-validation首个正例实际job成功、两固定检查正确关联、writer一次、湖文件未变，但测试把3个下游fixture checks的SDK target查询也算进“固定检查两次查询”，断言失败。SDK `asset_check_result.py` 的partitioned target查询和完整证据显示固定资产2次、下游资产6次，均limit=1。修正只收紧测试按AssetKey分组计数，保留全部8条查询，并断言成功时下游恰6次、失败时0次；不改adapter、SDK或生产查询预算。该未通过验收现场`/private/tmp/stock-suspend-isolated-lev3tgrx`保留，不把实际job成功冒充整例通过。

#### C. 最终实测与计划对账（2026-09-07 20:22–20:25）

最后一次完整adapter调用退出0，6批合计59/59，无skip/xfail或资源门禁触发；每批都有新的原生OS自检、精确argv/env/profile、源码哈希、禁止哨兵前后身份及pytest完成数。只允许A节11份新增源码和两测试的literal读取；没有增加正式目录、网络或写入权限。

| 批次 / 报告 | 实际数 / 含启动耗时 | 覆盖结果 |
| --- | --- | --- |
| [C编码及内容拒绝](/private/tmp/stock-suspend-isolated-fmjp_gpb/allowed/resource-result.json) | 11/11，1.361秒 | 字面编码/hash、生产批准拒绝两行样本、synthetic换键及值域/重复键反例 |
| [C物理schema与路径](/private/tmp/stock-suspend-isolated-1vdxd1vq/allowed/resource-result.json) | 12/12，1.309秒 | 少/多/错序/错类型均拒绝，换序压缩逻辑身份不变，非法路径/操作名拒绝 |
| [C08/C09](/private/tmp/stock-suspend-isolated-gpl1lmwt/allowed/resource-result.json) | 11/11，1.381秒 | 0/1/2/3行inspection仅DESCRIBE＋count；超行零加载。缺文件/损坏/尺寸预算/inspection及加载漂移/加载消失/解码异常准确拒绝；真实换文件后旧inspection失效 |
| [D路径与发布](/private/tmp/stock-suspend-isolated-r2f0v1jc/allowed/resource-result.json) | 11/11，9.502秒 | 1项AssetSpec＋10种路径/发布反例；路径失败零查询，发布失败每检查一次查询；全部零连接/解码/下游写 |
| [D校验、target及存储](/private/tmp/stock-suspend-isolated-a7ciaqd0/allowed/resource-result.json) | 9/9，9.358秒 | 成功、换键、空/少/多行、错schema、损坏、事件存储故障、非法值域；结果见下表 |
| [D输入异常分类](/private/tmp/stock-suspend-isolated-n_i5noe7/allowed/resource-result.json) | 5/5，5.877秒 | 大小/连接资源超限分别input_resource；消失/漂移/解码异常为validation且原因准确；无虚构checked_rows或下游写 |

| §4.1 / §18.4 / §18.5硬口径 | 当前实际落点与证据 |
| --- | --- |
| 结构与内容分工 | contract的`inspect_confirmed_file`、`_validate_confirmed_columns`、inspection版loader及content行数前置；checks的`_validate_inspected_file`。0/1/3行均schema绿、content为row_count_mismatch；3行两个检查合计decode=0，0/1行仅schema分支decode=1 |
| 真实hash、不用批准值充数 | 同计数换键时schema/content记录相同的实际新hash，schema通过、content失败；非法值域时schema通过但digest空；错schema两个均失败、不解码 |
| 路径只读与执行顺序 | checks私有`_confirmed_input_path_readonly`按真实root校验，不调用health。24个实际job用例健康helper/日常runless调用均0，临时lake文件与目录身份/内容前后相同；只成功例的下游哨兵写1次，其余23例哨兵不变 |
| 真实发布关联 | 成功例先用实际validator建立临时runless检查，再运行日期job；本次run=`a6a91524-b36f-43d6-b602-5a1fac688397`，读回两检查SUCCEEDED、partition=None、target的storage_id/run_id/timestamp均等于初始无分区发布（1 / 空字符串 / 1788783769.886732）；固定mat仍仅1条，合计5checks，最终3checks属于测试日期 |
| 不掩盖事件存储异常 | 两实际检查完成解码后各注入一次`synthetic check storage failure`，错误进入真实step failure；存储中没有成功evaluation、没有补runless，writer=0 |
| 测试保护 | 两测试import前断言上下文；fixture只在保护安装后从support注册，实际LakeRootResource构造与DuckDB/SQLite设置均读回。loader的当前全部调用方已改新签名，没有旧签名wrapper；未来writer/readiness/bootstrap仍未实现 |

成功例的精确run id以[原生读回证据](/private/tmp/stock-suspend-isolated-a7ciaqd0/allowed/pytest/test_validation_and_storage_ok0/adapter-evidence.json)为事实源。每个D例另存同目录`adapter-evidence.json`，包括所有查询、SQL调用数、实际Failure metadata、target、哨兵与lake不变证据；decode计数指加载SQL尝试次数，故障注入例不将尝试当作已完成解码。

最终adapter三批C现场普通文件约50–53KB，三个D批分别6,415,594 / 6,068,410 / 3,316,433字节，均低于100MiB；正常Parquet每批不足10KB，没有为了超预算反例生成大文件。Dagster分区check预览警告保留，SDK未升级；正式S2的4,022行、6,166文件没有读取或运行。

最终runner再跑隔离回归：I03/I04 16项1.244秒、I05 14项1.016秒、I06 16项1.654秒、I07 15项4.254秒、I08 3项0.938秒，全部通过。报告分别在下列清单的`tc_f6109`、`5j_aeasd`、`r7_63cle`、`lkjj0uf0`（startup-result.json）和`s7adtgpx`的allowed内。另对父monitor注入精确OSError，报告确实保存`parent_monitor_error`、`child_reaped=true`、退出-9，异常未吞掉，禁止哨兵未变；仅终止本轮虚构子进程组，证据见[zre1uc4g报告](/private/tmp/stock-suspend-isolated-zre1uc4g/allowed/resource-result.json)，不是普通用例通过或业务中断。

验收源码SHA256：

| 文件（相对orchestrator） | SHA256 |
| --- | --- |
| `defs/stock_suspend_confirmed_contract.py`（位于src/orchestrator下） | `4d34f304a9d8b3dbe975cb7a7c8ea845ac27a0744d2efd8b470b1814ba346514` |
| `defs/checks/stock_suspend_confirmed_checks.py`（同上） | `c9201f706063ebf1ce77bd49b4aa32ad8272c9c9680420d3d224b24984855af9` |
| `tests/stock_suspend_confirmed_test_runner.py` | `ca10f9ef65ea07fc947f5d2870f7c2b84be834432cb886986fe185e5e7dd0916` |
| `tests/stock_suspend_confirmed_test_support.py` | `590d2857c3a122553d7b4b9b83c17147ca7579220ed275a762fd65f904fc38ae` |
| `tests/test_stock_suspend_confirmed_contracts.py` | `09781ec7bec6fc4782bbe4f44f8b3a126fe5366bebe89a743c1b749c7e7ec5dc` |
| `tests/test_stock_suspend_confirmed_dagster.py` | `f2d792f57183ed115961de27dd16b9adc32967acbf413b1ec5b546cb077651e4` |

#### D. 临时清理登记与本轮停止点

本轮44处精确根均加入§18.11最终清理范围（包括未通过尝试、临时SQLite实例、日志、链接、缓存、报告和虚构样本）；当前保留review证据，不做通配删除，不存在新增套件或DG服务：

收尾只读核验44处均无lsof打开句柄。六个变更Python文件默认Ruff、全量src/tests致命错误基线、文档完整性检查与git diff --check通过，CodeGraph sync/status最新；这些静态结果不替代上面的59例实际验收。

```text
/private/tmp/stock-suspend-isolated-jhyikcg5
/private/tmp/stock-suspend-isolated-9bavud_j
/private/tmp/stock-suspend-isolated-e45xrydd
/private/tmp/stock-suspend-isolated-a_owu69g
/private/tmp/stock-suspend-isolated-tkt48eei
/private/tmp/stock-suspend-isolated-yirxhw4k
/private/tmp/stock-suspend-isolated-pl4br19y
/private/tmp/stock-suspend-isolated-n6i7dzyw
/private/tmp/stock-suspend-isolated-6igdob9z
/private/tmp/stock-suspend-isolated-njjh9u2_
/private/tmp/stock-suspend-isolated-lt5n2vg2
/private/tmp/stock-suspend-isolated-_qy15hsd
/private/tmp/stock-suspend-isolated-s6lzapwq
/private/tmp/stock-suspend-isolated-82w8kpjx
/private/tmp/stock-suspend-isolated-7up0zkht
/private/tmp/stock-suspend-isolated-1d6kxgi9
/private/tmp/stock-suspend-isolated-fm63ra5c
/private/tmp/stock-suspend-isolated-ex7kgrir
/private/tmp/stock-suspend-isolated-6xu62q2k
/private/tmp/stock-suspend-isolated-iutmx2s0
/private/tmp/stock-suspend-isolated-hfw8qawb
/private/tmp/stock-suspend-isolated-lev3tgrx
/private/tmp/stock-suspend-isolated-fmjp_gpb
/private/tmp/stock-suspend-isolated-1vdxd1vq
/private/tmp/stock-suspend-isolated-gpl1lmwt
/private/tmp/stock-suspend-isolated-r2f0v1jc
/private/tmp/stock-suspend-isolated-a7ciaqd0
/private/tmp/stock-suspend-isolated-n_i5noe7
/private/tmp/stock-suspend-isolated-tc_f6109
/private/tmp/stock-suspend-isolated-5j_aeasd
/private/tmp/stock-suspend-isolated-r7_63cle
/private/tmp/stock-suspend-isolated-lkjj0uf0
/private/tmp/stock-suspend-isolated-ajjjdatr
/private/tmp/stock-suspend-isolated-nyedjqii
/private/tmp/stock-suspend-isolated-evus9ne2
/private/tmp/stock-suspend-isolated-57pfm6v6
/private/tmp/stock-suspend-isolated-665g505b
/private/tmp/stock-suspend-isolated-6fqet8gn
/private/tmp/stock-suspend-isolated-ggnni8f9
/private/tmp/stock-suspend-isolated-ozmr_6ou
/private/tmp/stock-suspend-isolated-kdz75qr2
/private/tmp/stock-suspend-isolated-ri5_skph
/private/tmp/stock-suspend-isolated-s7adtgpx
/private/tmp/stock-suspend-isolated-zre1uc4g
```

阶段对账：文档/静态检查、隔离验收、实际adapter的本节C/D小样本已通过；原S1实现及合成全套回归未完成；S2生产C01/C05未运行；S2全范围等价及正式发布/切换未运行。D06本轮只验adapter和存储关联，完整readiness的R组仍待后续，不能将其一起计通过。

本轮改动为contract、checks、两业务测试、runner/support及原LLD/技术方案/主索引，共9文件。没有改共享health/resources/duckdb_connection、五列/批准常量、既有catalog/paths/metadata增量、现行分钟CLI/CSV、其他任务文档或依赖矩阵。I08提交已完成；本轮新修改尚未提交、未推送。下一步回到原S1的纯SQL合并与金样本测试，然后按矩阵推进writer/readiness/CLI；不在本轮自动执行。

<a id="s1-confirmed-sql-core-acceptance"></a>
### 18.20 纯 SQL 核心及金样本：通过，尚未切换 writer

2026-09-07，管理员要求继续。按开发审查、数据湖、Dagster与文档治理技能，先核验当前代码及§4/§10/§13，再补实施顺序与资源白名单；不新增业务需求、配置项、连接、实例或状态实体。CodeGraph `explore` 覆盖标准化、合并、时段修正，`impact` 检查旧SQL入口；图未覆盖的直接import调用由源码补齐：`assets/suspend_d.py` 仍是唯一生产调用方。因此本轮不先破坏旧接口，也不接半成品writer。

#### A. 逐项落地与未完成边界

| 文件/硬口径 | 实际修改与验收 |
| --- | --- |
| `defs/duckdb_sql.py`；H03/H05/H06 | 新增长期共享CTE、完整冲突SELECT、单行计数/有界分类样本SELECT；只生成SQL，无连接/IO/事件。最终四列、Raw重复、NULL判定和14条时段修正顺序均由字面样本验证 |
| `tests/test_stock_suspend_confirmed_merge.py`；M01–M06/M08/M09算法部分 | 新增17个测试函数、参数展开42例；含S0记录的两个覆盖键原3行字面样本、0/1/多行覆盖、25条冲突只取20样本但总数25、25键分类只返回20样本、单日期/多日期及非法identifier |
| `tests/stock_suspend_confirmed_test_runner.py`；H13 | 只新增固定regression suite及七文件只读闭包；四批9/7/10/16。无任意路径/额外参数透传，4个参数拒绝用例在创建临时根之前失败；静态对账17个测试函数全部且只调度一次 |
| `tests/stock_suspend_confirmed_test_support.py`；H13 | regression复用已验收连接fixture；不增加资源/连接替换入口。正式默认连接、网络和实例发现保持拒绝 |
| 本文、技术方案、主索引 | 同步实际停止点、接口/调用方同轮切换顺序、样本形状与资源记录；未把私有CTE测试写成writer或生产验收 |

旧 `silver_stock_suspend_daily_select(raw_path, partition_key)`、标准化及模块内其余函数共21个，与HEAD逐个AST比较相同；除了必要import及其排序，只新增3个函数。现行writer、CSV/覆盖规则、时段修正文件、共享health/resources/duckdb_connection、Raw、分钟CLI和其他消费者未改。此前非SQL源码及旧清退文档差异摘要仍为 `f94f46dae3117fa76d1bb8ac6a280edc5c43eb9a379ec70eeb56f6b61d09a4d2`，没有覆盖既有增量。模块新增依赖仅指向既有纯合同，无跨子系统依赖或依赖矩阵变更。

**尚未验收：** M02实际原check调用、M03真实writer拒绝且目标不变、M07文件重建、M08文件日期校验及全部W/B/E/R；旧公开SQL签名也尚未替换。纯SQL的冲突结果不负责抛写入失败，不得独立绕过writer拿SELECT去写湖。两个固定覆盖键来自已批准输入的前置合同，本轮没有放松生产validator。

#### B. 本轮实测

完整执行命令与预算见§13本小轮说明。四批一次通过，总耗时5.797秒；报告均记录源码/测试哈希、完整argv、实际连接设置、逐例输出、禁止区前后身份和退出码。所有批次无超时、预算拒绝、跳过或失败；每批先完成OS原生自检。

| 批次 | 通过/耗时 | 精确报告 |
| --- | --- | --- |
| M-add-conflict | 9 / 2.009秒 | [报告](/private/tmp/stock-suspend-isolated-7r1kq5it/allowed/resource-result.json) |
| M-override | 7 / 1.499秒 | [报告](/private/tmp/stock-suspend-isolated-24lj2dtj/allowed/resource-result.json) |
| M-order-stats | 10 / 1.409秒 | [报告](/private/tmp/stock-suspend-isolated-m1dkuzcm/allowed/resource-result.json) |
| M-input-boundaries | 16 / 0.880秒 | [报告](/private/tmp/stock-suspend-isolated-s3ioq_17/allowed/resource-result.json) |
| 隔离 I03–I04 / I05 / I06 | 16 / 1.161秒；14 / 0.922秒；16 / 1.746秒 | 根分别为 `us5nxks0` / `po1sdlvr` / `8gzzq73n`，各 `allowed/resource-result.json` |
| 隔离 I07 / I08 | 15 / 4.228秒；3 / 0.880秒 | [I07](/private/tmp/stock-suspend-isolated-c0dw5f_8/allowed/startup-result.json)、[I08](/private/tmp/stock-suspend-isolated-mawpsd_8/allowed/resource-result.json) |

SQL四根合计264KiB，未生成Parquet或数据库文件，未创建DG实例，未读CSV/真实湖；连接为既有512MB/2线程/0spill/禁扩展安装。隔离回归I06确实新建了临时SDK实例及SQLite文件，结束已关闭；不能把“SQL用例无实例”扩大成“本轮所有验证都无实例”。没有安装SQLite/任何套件、启动DG服务、访问正式资源或恢复sensor。原隔离scope策略与§18.19逐字等价，仅随机运行根不同；regression只增加事先列明的源码literal读取。

变更四个Python文件完整Ruff、全量src/tests致命错误基线通过；21个旧函数不变与17个测试函数全覆盖静态对账通过。原59例C/D本轮未重跑，仍只引用§18.19结果，不计入本轮106项结果。文档完整性校验与 `git diff --check` 通过，CodeGraph sync/status最新；不运行 `dg check defs` 或实际业务writer。

#### C. 精确清理登记与下一步

以下本轮19个根统一纳入§18.11最终清理，当前只保留review证据，无删除动作。逐根lsof复核均无打开句柄。`c0dw5f_8/allowed/startup-result.json`另完整列出I07的十个子根：

```text
/private/tmp/stock-suspend-isolated-7r1kq5it
/private/tmp/stock-suspend-isolated-24lj2dtj
/private/tmp/stock-suspend-isolated-m1dkuzcm
/private/tmp/stock-suspend-isolated-s3ioq_17
/private/tmp/stock-suspend-isolated-us5nxks0
/private/tmp/stock-suspend-isolated-po1sdlvr
/private/tmp/stock-suspend-isolated-8gzzq73n
/private/tmp/stock-suspend-isolated-c0dw5f_8
/private/tmp/stock-suspend-isolated-o3d018qf
/private/tmp/stock-suspend-isolated-zw_kocuh
/private/tmp/stock-suspend-isolated-bxc9xxr0
/private/tmp/stock-suspend-isolated-x_lmha19
/private/tmp/stock-suspend-isolated-cn53ceou
/private/tmp/stock-suspend-isolated-1vg8asi0
/private/tmp/stock-suspend-isolated-3dz5mk80
/private/tmp/stock-suspend-isolated-ie7nzgl_
/private/tmp/stock-suspend-isolated-vhl2wa1w
/private/tmp/stock-suspend-isolated-59g_d836
/private/tmp/stock-suspend-isolated-mawpsd_8
```

下一步是§5唯一writer：按完整输入校验、候选验证、原子提升、checkpoint续跑的设计实施，同时切换旧公开SQL接口和调用方，跑真实临时writer的M/W用例。本轮不自动进入这一步，也不进入readiness/CLI、正式发布、CSV删除或sensor恢复。本轮共7文件增量，未提交、未推送；S1未完成、S2未执行。

<a id="s1-confirmed-writer-acceptance"></a>

### 18.21 writer 与公开 SQL 同轮切换及临时文件验收（2026-09-07）

#### A. 提交边界与本轮实现

按管理员“提交修改，然后继续推进”，先将此前合同、checks、SQL核心、测试及关联文档19文件提交为 `630ba12a`，未推送；未纳入Wealth文件。随后在同一 `dev-interface` 工作区实施本节。§18.19/18.20的“writer未切换/未提交”是对应历史小轮状态，当前以本节和文首状态为准。

CodeGraph explore覆盖原 `silver_stock_suspend_daily`、原replace helper和冲突helper；impact只返回本模块，并不能代替跨模块审计。全仓核验确认：旧两参数SQL唯一正式调用方是本asset；旧patch/override metadata没有独立业务调用方。实际变更仍在orchestrator内部，无Foundation/Ops/Biz/Wealth或子系统依赖方向变化；同步局部架构快照，未重审其他模块。

| 硬口径 | 当前落点 | 本轮验证 |
| --- | --- | --- |
| Raw与最终字段不变 | Raw函数/列类型不变；输出仍四列；唯一公开SQL改为三个keyword-only关系名 | Raw函数含decorator AST逐项相等；除公开入口外23个SQL函数AST相等；42例字面金样本 |
| 固定事实是完整批准输入，不读CSV | writer调用原inspection/load/content合同；SQL与asset移除旧范围模块import | synthetic固定文件真实校验；缺文件/坏文件拒绝；OS策略未放行CSV或旧模块 |
| 原业务规则保留 | 不去重；冲突先拒绝；原14条时段修正；两覆盖键仍按键替换 | SQL覆盖全部14条和两覆盖键，writer覆盖重复保留、冲突、空表和真实文件重建；原最终checks的实际运行仍待D组 |
| 先校验输入日期，再COPY | normalized一次加载，NULL/错日聚合拒绝，不过滤坏行 | 错日、NULL、解析失败均不能覆盖；旧目标字节不变 |
| 候选校验后原子提升 | staging COPY、四列schema、完整读回、行数与双向EXCEPT ALL；fsync后替换 | COPY失败、坏候选、内容差异均拒绝；没有预删、备份、其他run扫描 |
| 续跑先看真实目标 | checkpoint字段/身份/路径严格校验；prepared和committed两阶段 | 替换前/后中断、新DuckDB连接续跑；已提交但输入漂移先记提交再失败；目标被后来替换不能重放 |
| 版本必须绑定参与计算的文件 | 加载前后身份＋实际物理hash；prepared落盘后再次核验 | SQL后文件改写、落盘窗口漂移，以及保持大小/mtime但改内容均被拒绝 |
| 元数据不重算旧结果 | `SuspendDailyWriteResult(target_path,status,output,confirmed_version,confirmed_logical_sha256)`，output冻结schema/count/stats/时段元数据 | 续跑返回与prepared完全相同的output；旧patch metadata不再新写，历史事件不变 |
| 等价即复用 | 新run当前输入重新计算，与目标多重集等价返回reused，不建新run候选 | Raw重抓后重建；目标换Parquet编码后仍复用且身份不变 |

实现分布：`assets/suspend_d.py` 新内部writer和checkpoint helper，同时改原Silver adapter依赖/调用及metadata；`duckdb_sql.py` 删除旧签名体，复用已通过金样本的关系核心，不留wrapper；`test_stock_suspend_confirmed_merge.py` 改测新的唯一公开入口；新增 `test_stock_suspend_confirmed_writer.py`，固定runner登记5个小批次及准确源码闭包。共享resources/连接默认、Raw、原时段修正文件、原最终checks、job/sensor均未改动。

§5.1顺序已澄清为“只读路径前置→已有checkpoint恢复→首次计算输入检查”，避免已提交但Raw后来丢失时提前退出；不调用会写canary的健康探针。checkpoint最大1MiB是本writer内部读写合同，不是新增可调配置。§12同步实际hash次数：首次非等价写入Raw/固定各4轮，等价reuse各2轮；不把额外字节IO说成零成本或新增行解码。

#### B. 实际验收与证据限制

只运行既有隔离父入口，分别指定 `--scope regression --suite test_stock_suspend_confirmed_writer.py` 与 `test_stock_suspend_confirmed_merge.py`；完整启动参数沿用§13的offline/no-sync/no-env/no-config/no-download约束。每批先通过原生OS自检；无跳过、xfail、超时、放宽权限或正式路径访问。

首次54例全部通过，随后加强“新连接续跑、committed checkpoint落盘失败、内容漂移但大小/mtime未变”并复验。最终有效集合是**58例writer＋42例SQL，共100例**；首次54例与最终重叠，不相加冒充154个独立case。

| 最终批次 | 例数 / 总耗时 | 精确报告 |
| --- | --- | --- |
| W-success | 9 / 1.995秒 | [报告](/private/tmp/stock-suspend-isolated-aiogcdex/allowed/resource-result.json) |
| W-reject | 11 / 1.443秒 | [报告](/private/tmp/stock-suspend-isolated-9sibr7h5/allowed/resource-result.json) |
| W-resume | 12 / 1.799秒 | [报告](/private/tmp/stock-suspend-isolated-qn8gb4_8/allowed/resource-result.json) |
| W-checkpoint | 13 / 1.764秒 | [报告](/private/tmp/stock-suspend-isolated-or5c3wgf/allowed/resource-result.json) |
| W-identity | 13 / 1.599秒 | [报告](/private/tmp/stock-suspend-isolated-qv2q7x2z/allowed/resource-result.json) |
| M-add-conflict | 9 / 1.401秒 | [报告](/private/tmp/stock-suspend-isolated-90elx2nj/allowed/resource-result.json) |
| M-override | 7 / 1.399秒 | [报告](/private/tmp/stock-suspend-isolated-be2snnea/allowed/resource-result.json) |
| M-order-stats | 10 / 1.367秒 | [报告](/private/tmp/stock-suspend-isolated-du0m18b8/allowed/resource-result.json) |
| M-input-boundaries | 16 / 0.885秒 | [报告](/private/tmp/stock-suspend-isolated-elxwxe4w/allowed/resource-result.json) |

writer五批合计8.600秒，SQL四批5.052秒。这是临时小样本总测试耗时，不是正式4,022行writer性能结论。使用既有512MB/2线程/0spill连接、显式临时Lake/staging；没有SDK实例、SQLite文件或其他数据库文件，没有安装任何依赖、启动DG服务或读取真实数据。原59例C/D及64项隔离回归本轮不重复计入；静态执行stdlib runner并比较渲染结果，isolation/adapter的OS策略与提交基线逐字相等，regression只增删事先审计的精确源码文件。

中断测试使用实际writer在replace边界注入BaseException，磁盘现场保留，续跑另开内存DuckDB连接；不是杀死正式DG进程，也不宣称已完成完整job/D/R验收。首次父入口末尾沿用了SQL小轮的 `writer_executed=false` 摘要，已在最终运行修正为按固定suite真实填值，并分别标记synthetic和formal_writer_executed=false；逐case实际writer执行及54例结果并未缺失。

五个变更Python文件完整Ruff通过；全量src/tests致命错误基线通过；两suite共35个测试函数全部登记且无重复，固定case计数匹配。文档完整性和diff空白检查通过。CodeGraph sync/status最新（2,959files）；不运行dg发现命令或正式reload。

#### C. 清理登记与尚未执行范围

本轮14个临时根如下；合计约1.14MiB，全部纳入§18.11最终精确清理，现在保留review证据。前5个是首轮54例，后9个是最终100例。交付前逐根执行lsof复核，14处均无打开句柄（退出码1、无输出），未删除任何现场。

```text
/private/tmp/stock-suspend-isolated-rnrlplak
/private/tmp/stock-suspend-isolated-4qx3tr3o
/private/tmp/stock-suspend-isolated-pjfi692r
/private/tmp/stock-suspend-isolated-9ioeljdy
/private/tmp/stock-suspend-isolated-db3424ja
/private/tmp/stock-suspend-isolated-aiogcdex
/private/tmp/stock-suspend-isolated-9sibr7h5
/private/tmp/stock-suspend-isolated-qn8gb4_8
/private/tmp/stock-suspend-isolated-or5c3wgf
/private/tmp/stock-suspend-isolated-qv2q7x2z
/private/tmp/stock-suspend-isolated-90elx2nj
/private/tmp/stock-suspend-isolated-be2snnea
/private/tmp/stock-suspend-isolated-du0m18b8
/private/tmp/stock-suspend-isolated-elxwxe4w
```

下一小轮先做§6的Silver-only job/check选择与readiness集成：核验只写最终Silver一个asset、固定两个blocking checks先行、最终三个checks保留，补D/R矩阵；M02实际原key check、D组真实job和readiness、后续人工CLI/B/E/G/P全套回归仍未完成。直接内部writer不读事件/实例这一边界不变。

**本轮新9文件增量尚未提交、未推送；S1未全部完成、S2及正式发布未执行。固定正式文件未发布，CSV及旧修正模块仍保留待S5；没有恢复已暂停的sensor。不能手动启动依赖新固定文件的正式Silver job来“试试看”。** 同日写入依旧依赖人工错峰，本轮没有新增锁、调度或后台自动维护。

后续提交记录：管理员要求“提交吧。然后继续推进”后，上述9文件以 `4887cfac` 提交，提交说明为 `feat(lake): make suspension Silver writes recoverable`；未推送，未纳入Wealth任务文件。上段“尚未提交”是§18.21交付时的历史状态。

<a id="s1-daily-check-partition-audit"></a>

### 18.22 集成前审计：原三个日分区检查的定义缺口（已确认修正，保留审计经过）

**本轮做到哪里：**已完成上述提交，随后用CodeGraph `explore` / `impact`及源码核对Silver job、固定checks、三个原最终checks、readiness、sensor和现有测试。图的impact仅返回检查定义文件，未覆盖字符串登记；另用源码搜索核实catalog、readiness、sensor/check测试及增量治理测试。不改跨子系统依赖或依赖矩阵。本轮后半段仅更新本文、技术方案和主索引；未改生产/测试Python、测试权限白名单或资源绑定，未创建临时实例、执行作业或访问正式数据。

#### A. 事实、影响与此前遗漏原因

| 核验位置 | 当前代码事实 | 对方案的影响 |
| --- | --- | --- |
| `defs/checks/suspend_d_checks.py` 的 `silver_suspend_d_key_integrity_check`、`silver_suspend_d_suspend_type_domain_check` | decorator只传资产对象和`blocking=True`，未传`partitions_def`；函数仍按`context.partition_key`检查对应文件 | 能按日期读取文件，不等于生成的检查事件带有该日期 |
| `defs/checks/stock_partition_checks.py` 的 `silver_suspend_d_partition_allowed_check` | 同样未传`partitions_def`；函数核验注册日期、起始日期和非未来日期 | 合法分区检查本身，也缺少事件日期归属声明 |
| 本机Dagster 1.13.18 `asset_check_decorator.py:225`、`asset_check_result.py:214` | decorator将参数原样写入check spec；生成evaluation时，只有step有日期且spec分区非空才写入日期，否则为None | 不能假定绑定资产对象后自动继承日期分区；[官方说明](https://docs.dagster.io/guides/test/asset-checks#partitioned-asset-checks)与安装源码一致 |
| `tests/test_stock_suspend_confirmed_dagster.py` 的 `make_final_check` | 三个最终检查是替身，并显式传了`partitions_def=PARTITIONS` | §18.19通过证明了两个新固定adapter的关联/阻断机制，**没有证明原三个实际检查的日期归属**；先前证据仍有效，但范围不足以覆盖D03 |
| `tests/test_suspend_d_checks.py` 的合法空Silver用例 | 直接调用实际check函数，断言`result.passed`；没有通过job写入后读回日期字段 | 可以验证业务判断，不能覆盖Dagster事件分区 |
| 本LLD §13 D03、§15.3第4项 | 前者要求最终检查有当天日期，后者仍写“原三个最终checks不变” | 若按“定义完全不改”执行，两个条件不能同时通过，必须先确认窄修正，不得改expected让测试通过 |

这是**现行检查定义的事件分区缺口，以及LLD未将其列入修改矩阵的遗漏**，不是新合并SQL产生的停牌事实错误，也不同于§15.2两个固定检查的target关联问题。源代码足以确认上述分区生成分支；本轮没有执行实际job或读取正式历史事件，因此不声称已新复现存储结果、生产故障或数据损坏。

当前通用readiness的`_check_result_for_materialization_ids()`仍按原生target的storage_id关联结果，并不检查evaluation.partition。因此不能仅凭本缺口就断言所有既有下游被阻断；本轮也不修改通用readiness去掩盖缺口。此次直接阻碍的是D03及目录规则要求的正确日期归属验收。

此前遗漏的具体原因是：设计要求保留三个现行检查，却只在提前实验中给三个替身检查声明了日期分区，没有把同一属性核对到三个真实decorator。补救必须是实际定义＋真实job＋存储读回，不能再增加替身正例来替代。

#### B. 最小修改矩阵（随后已确认并按§18.23落实）

| 文件 | 建议修改 | 明确保留 |
| --- | --- | --- |
| `defs/checks/suspend_d_checks.py` | 引入现有`cn_a_stock_trade_days`；只给上述两个Silver decorator增加`partitions_def=cn_a_stock_trade_days` | 业务函数、SQL、空分区通过规则、检查名称、blocking/severity、返回`AssetCheckResult`的方式及Raw检查全部不变 |
| `defs/checks/stock_partition_checks.py` | 复用文件已有的`cn_a_stock_trade_days`；只给`silver_suspend_d_partition_allowed_check`增加同一参数 | 注册日/日期范围判断及本文件其他资产、Raw检查全部不变 |
| 本LLD §6 / §15.3及技术方案 | 确认后明确“保留三项业务判断及自动target关联，仅补齐最终Silver检查的日期归属声明” | 新固定资产及其两checks继续无分区；不把显式原生evaluation方案扩到原三个检查 |
| 原S1 D组及现行检查回归 | 使用三个实际检查定义验收，不再用最终检查替身证明D03；给definition、evaluation、存储记录分别断言日期 | 名称集合仍为一writer五checks；固定两项partition=None，最终三项partition=测试交易日 |

本建议不新增日期分区、不注册正式动态分区、不改四列事实、数据路径、请求参数、作业名称或日期选择，不重写旧事件，也不修改SDK。不是全仓分区check治理；其他check即使有类似情况，也不因本次发现自动纳入。

#### C. 确认后的执行顺序与验收

1. 先同步上述窄修正口径到原方案并修改三处decorator；保留check函数体前后静态对账，证明没有夹带业务判断修改。
2. 继续原§6 Silver-only job/readiness/sensor集成；通用readiness不改，只给新固定事实增加专用有界校验。没有候选不新增IO，有候选每tick固定校验一次；Raw就绪筛选、最多两个请求、run key及连续性信息保持原行为。
3. 按既有隔离方案审计实际模块的精确import闭包及连接/临时staging绑定，再经固定runner运行小批次，不开放整个源码目录或正式路径、不安装依赖。当前没有为此提前扩权限或启动测试。
4. D03通过必须同时具备：实际job只写最终Silver；两个固定检查先行；三个原最终检查真实执行；三层日期属性/事件/存储读回一致；固定发布数量不增加、固定检查仍关联原无分区发布。重复键失败、合法空分区通过、固定输入失败writer不执行等反例一并保留。
5. 通过后再进行CLI/连接模式及原S1消费者全套回归；S2–S5、正式发布、恢复sensor、删除和最终测试环境清理仍按原阶段批准，不能因本窄修正自动执行。

上轮停止点是确认三个日频检查的日期声明。管理员在明确区分“已有日频资产有分区、新固定事实无分区”和三处最小改法后要求“你赶紧继续推进”，本窄修正及原§6集成进入实施；不再将其列为待拍板。历史100例不计作新运行数。

本次开工约束：原三个检查仅增加与已有资产相同的分区声明，业务判断和自动target关联不变；§6.2/§15.3所说“不变”不再指遗漏的日期声明。新固定两检查保持无分区。性能/资源上界如下，生产配置不新增、不修改。

| 范围 | 数量与IO上界 | 拒绝/验收 |
| --- | --- | --- |
| 固定readiness | 有候选tick：单个固定文件校验1次、最新mat查询1次、最新check查询各1次；无候选新增IO为0 | 物理失败、查询失败或最新记录不合格即阻断；不查老绿灯、不加每日freshness |
| 原sensor | 日期集合/窗口/Raw判断不变；最多2个RunRequest，零源请求或分页 | 只对前2个候选评估，不因阻断扩大窗口；cursor固定摘要只有一份 |
| D/R隔离回归 | 固定事实2行synthetic、Raw≤32行、每次job一个日期/一个目标文件，sensor≤3候选；每文件≤1MiB | 沿用单例30秒、批≤16例/60秒、工作区100MiB、DuckDB512MB/2线程/0spill、零网络；每次原子提升一个临时目标 |
| 新测试入口 | 固定runner登记`test_stock_suspend_confirmed_integration.py`和`test_stock_suspend_confirmed_readiness.py`；真实job/三实际最终checks | 显式临时Lake/staging/instance；只绑定实际Silver adapter及两个最终check所在模块的连接别名到既有测试工厂，其他默认连接保持拒绝；不改生产默认根 |

只读源码权限按实际import闭包精确增加：`defs/jobs/{__init__,suspend_update}.py`、`defs/checks/{suspend_d_checks,stock_partition_checks}.py`、`defs/sensors/{__init__,suspend_d_sensor,cn_a_trade_day_sensor,stock_trade_day_sensor,readiness}.py`、`defs/asset_guards/{__init__,bounded_continuity,stock_daily}.py`、`defs/assets/{market_breadth,stock_basic,stock_daily,stock_lifecycle,stock_return_distribution}.py`、`defs/catalog/lake_assets.py`、`defs/run_contracts/{cursor_payloads,cursors,dc_board,dc_daily_technical,dc_daily_technical_serving,index_global,requests,run_keys,sensor_tags}.py`。这些模块因现有导入关系被加载，不选择或执行其他资产；原CSV、其他源码目录、正式数据和网络仍不放行。当前sensor原有日历健康探针不在本轮修改：R用例替换既有日历窗口读取为虚构窗口，单独真实执行新增固定readiness；不把它计为全sensor物理日历验收。

现行`test_suspend_d_sensor.py`同轮纳入固定runner（13例）：只补固定输入ready的测试上下文，既有日期、run key、检查名称、cursor、Raw及stdout断言不放宽。复核发现上一轮writer adapter遗漏了原`silver_suspend_d_validation_failed`日志事件，按原观测合同补回：捕获已有合同错误，输出日期和reason_code后原样抛出，不打印全量行、不改失败/写入结果；内部writer与SQL不改。新真实job反例同时验证这一事件。该文件仅stdout adapter有变化，不把日志补齐变成新状态机或恢复规则。

<a id="s1-confirmed-integration-acceptance"></a>

### 18.23 job/check/readiness/sensor集成验收（2026-09-07）

本轮完成原§6与§18.22已确认的窄修正，不再停留在检查清单。开发审查、数据湖和Dagster技能约束代码/测试范围，文档治理技能用于同步原方案状态；没有另建测试框架。CodeGraph `explore`覆盖sensor调用链，`impact(asset_readiness_status)`显示36项相关符号，因而保留通用函数不改，新增固定事实专用判断。跨子系统依赖和依赖矩阵不变。

| 硬口径 | 实际修改 | 验证 |
| --- | --- | --- |
| 三个日频检查有日期，固定两检查无日期 | `checks/suspend_d_checks.py`两处、`checks/stock_partition_checks.py`一处补声明 | 实际定义、evaluation、storage.partition同时读回；原检查所有函数体AST不变 |
| 只写最终Silver、先固定检查后写入 | `jobs/suspend_update.py`只增加固定检查selection | 实际job解析：一个可写资产、五checks；真实事件顺序及固定失败writer=0 |
| 当前物理文件＋最新发布＋最新两检查 | `sensors/readiness.py`新增`ConfirmedReadinessStatus`及专用函数 | 文件坏时事件查询0；正常单次1文件＋1mat＋2check；不加日期freshness；两检查分别单独失败也阻断；不回退老绿灯 |
| 原sensor选择行为保留 | `sensors/suspend_d_sensor.py`仅在非空前两候选处加一次固定检查和紧凑cursor摘要 | 无候选/登记缺口新增IO=0；原Raw阻断、run key、最多2请求、连续性字段不变；连接错误保守跳过 |
| 业务规则不变 | 原最终检查、内部writer、Raw asset/sensor、通用readiness全部函数体AST对照通过 | 合法空文件通过；重复行保留并被原key检查判失败；Raw冲突拒绝，目标不变；绕过checks时writer仍拒绝坏固定事实 |
| 观测与数据分离 | `assets/suspend_d.py`仅补回合同失败日志，原样抛错 | 冲突/绕过门禁反例输出原失败事件名称及当前reason_code；没有重新引入旧CSV专属的conflict_count日志拼装或状态写入 |

文件分布：生产代码6份（上述两checks、job、readiness、sensor、Silver adapter日志）；测试4份（固定runner、现行sensor fixture、新integration、新readiness）；文档3份（本文、技术方案、主索引），共13份专项文件。其他任务的Wealth改动保留，不纳入本轮。

#### 有效结果及性能

| 固定批次 | 有效测试 | 启动到结束耗时 | 证据目录后缀 |
| --- | --- | --- | --- |
| D-actual-job | 10：9个实际job场景＋catalog唯一登记 | 10.379秒 | `kxj8p4gt` |
| R-file-publication | 11 | 1.867秒 | `8u1z16x4` |
| R-latest-checks | 11 | 1.389秒 | `r1lxsxew` |
| R-sensor | 8 | 1.339秒 | `wqf_wv02` |
| R-existing-contract | 6＋2个subtests | 1.259秒 | `pyw3xa73` |
| R-existing-selection | 7＋3个subtests | 0.935秒 | `ysflhk2d` |

合计**53例测试＋5个既有subtests**，不是58个独立测试方法。每个证据位于 `/private/tmp/stock-suspend-isolated-<后缀>/allowed/resource-result.json`；D组各用例另有`integration-evidence.json`，记录run_id、五项检查的实际日期/通过状态/target ID和writer调用数。六批原生隔离自检均通过，虚构禁止目录前后不变，零超时/资源中止。全部是临时synthetic数据和实例，不计作生产4,022行身份验收或正式发布证据。

修改Python文件完整Ruff、全src/tests致命错误扫描及函数体静态对照通过；文档完整性和diff空白检查在交付前复验。本轮未重跑§18.21的58＋42例，内部writer/SQL未改，不能将历史100例重复计为本轮新结果。全仓Definitions发现/catalog治理测试、人工CLI、受限连接模式、剩余B/E/G/P与正式全范围验收仍待原S1后续阶段，不能据本节标记整个S1完成。

#### 首轮失败与保留现场

实际job首轮已成功执行，但测试读取事件时使用了本机SDK不存在的`is_asset_check_evaluation`属性，导致测试失败；改为已有`get_asset_check_evaluations()`及实际事件类型字段后重跑通过，没有改生产结果或放宽期望。现行sensor首轮13例和5个subtests均通过，但固定runner按13登记、实际成功报告计18，导致总计核验不通过；将原测试完整拆为8/10报告的小批次重跑，不改support计数规则、不跳过subtests、不提高单批16上限。

以下**全部12个本轮创建的精确目录**追加到§18.11最终清理登记，包括失败/中间通过及最终六批。现在不清理或重用；需求完成后按既定要求彻底清除，不卸载现有共享SQLite/Python：

```text
/private/tmp/stock-suspend-isolated-jbyr_nds
/private/tmp/stock-suspend-isolated-v0_d_yc9
/private/tmp/stock-suspend-isolated-rrkv8poo
/private/tmp/stock-suspend-isolated-0y_1m42a
/private/tmp/stock-suspend-isolated-1lrn7ro8
/private/tmp/stock-suspend-isolated-kxj8p4gt
/private/tmp/stock-suspend-isolated-ngbmiu1d
/private/tmp/stock-suspend-isolated-8u1z16x4
/private/tmp/stock-suspend-isolated-r1lxsxew
/private/tmp/stock-suspend-isolated-wqf_wv02
/private/tmp/stock-suspend-isolated-pyw3xa73
/private/tmp/stock-suspend-isolated-ysflhk2d
```

当前增量未提交、未推送。没有正式Lake/staging/instance访问、服务重载、sensor恢复、CSV删除或套件安装。下一步是原§8–9的人工CLI/文件与事件发布分离、受限连接模式及B/E验收；继续只在隔离环境实现，正式S2–S5仍分别批准。
