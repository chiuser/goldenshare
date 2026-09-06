# 本地 DG 停牌历史确认事实持久化与统一消费技术方案 v1

更新时间：2026-09-06

状态：**S0 已完成；LLD §15.3 窄修正已获批准。S1 部分代码因测试越权事故停止，未验收。用户已同意先补原 LLD review，再修隔离与两个新检查、独立验收后继续 S1；本轮仅补齐 LLD §18，未恢复代码修改或测试。未迁移停牌数据或发布正式事件，Silver sensor 未自行恢复。**

代码审计基线：`dev-interface@b324ec48ce8fd67fdf216fedc6a69103fab4ae3a`。

需求来源：清退 LLD §16.11 的 `TODO-SUSPEND-001`。本方案是该 TODO 的独立实施主案，不重开清退 M0–M8。

实施细节：[配套 LLD v1](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-suspend-confirmed-facts-low-level-design-v1.md)。技术方案约束范围和架构，LLD 约束接口、SQL、CLI、失败恢复与逐项测试；两份必须同步，不将待实施设计当作当前代码。

实际证据：[S0 审计清单](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-suspend-confirmed-facts-s0-audit-checklist-v1.md)。S0 已刷新来源、逻辑指纹、文件集合与部署边界；不是新链路实现或发布验收。

## 1. 结论与已确认边界

保留 Tushare Raw 原样镜像。将当前 CSV 承载的历史全日停牌修正，转为一份独立、固定、正式登记的 Silver 输入资产；由现有 `silver_stock_suspend_daily` 合成唯一供本地 DG 业务消费的停复牌事实。

```text
raw_tushare_suspend_d ───────────────┐
                                    ├─→ silver_stock_suspend_daily ─→ 本地 DG 业务消费者
silver_stock_suspend_confirmed ─────┘
       历史确认事实，只读输入
```

管理员已确认：

1. 只治理本地 DG 数据湖及其消费者。原有读取 Prod 的代码、数据库视图、Web 远程部署均不在范围内。
2. 不将修正回写 Tushare Raw，不冻结历史 Raw 分区，不改变 Raw 重抓规则。
3. 去掉运行时 CSV 隐性依赖，但必须保留已经确认的业务效果。
4. 下游统一读取现有停牌 Silver，不让日线、分钟线、恢复工具各自叠加修正规则。
5. 固定事实独立保存，Silver 可以从 Raw 与该事实重新生成，不依赖上一次 Silver 输出。
6. 低频人工维护，不建管理后台、规则引擎、数据库表或自动更新任务。

最初“出技术方案”仅授权文档；随后用户已批准 S0、S1 开发与隔离测试，以及仅暂停 `silver_suspend_d_update_job_sensor` 的维护安排。本文的新增文件、资产、字段、checks、迁移步骤是目标设计，部分已有代码但不代表全部实现或验收。当前批准不含正式 Lake/staging 写入、正式 materialization/check 事件、服务重载、删除或 Git 提交；S1 结束不自行恢复该 sensor。原维护/框架实验见 [LLD §15](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-suspend-confirmed-facts-low-level-design-v1.md#s1-dagster-gate)；事故后当前顺序以 [LLD §18 安全实施补充](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-suspend-confirmed-facts-low-level-design-v1.md#s1-test-isolation-repair) 为准，本轮停在文档 review。

## 2. 为什么选择这条路

| 选择 | 主要问题 | 结论 |
| --- | --- | --- |
| 修正回写 Tushare Raw | Raw 重抓会整分区替换，必须额外保护修正，破坏源镜像语义 | 不采用 |
| 只保留现有 Silver，删除修正来源 | 历史 Silver 重新生成时会丢失无法从 Raw 推导的事实；读取旧输出续算又会形成自依赖 | 不采用 |
| 把 CSV 改名为 JSON、Python 常量或未登记 Parquet | 仍然是代码旁边的隐性输入，归属、版本和依赖没有解决 | 不采用 |
| 固定事实作为正式上游，统一生成 Silver | 新增一个小型数据资产及其完整性检查，保持 Raw 与业务消费边界 | 采用 |

这批事实没有出现在原始输入中，必须有独立、持久的载体。目标不是“完全不读文件”——本地数据湖本身就是 Parquet——而是取消未登记、未校验、依赖进程缓存的旁路文件。

## 3. 当前事实与证据

### 3.1 当前代码确实如何运行

| 事实 | 当前代码依据 |
| --- | --- |
| CSV 通过同目录路径隐式加载，并用进程内 `@cache` 缓存 | [suspend_full_day.py](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/corrections/suspend_full_day.py)，`suspend_full_day_ranges()` |
| 每次生成某日 Silver，读取同日 Raw，再展开 CSV 区间补 `S + NULL` | [duckdb_sql.py](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/duckdb_sql.py)，`silver_stock_suspend_daily_select()` |
| 两个明确覆盖键会先排除其 Raw 记录，再从 CSV 补全日停牌；不能只删 CSV 而留下排除逻辑 | 同一 SQL 的 `full_day_raw_overrides`、`corrected` 和 `eligible_full_day_patches` |
| 其他补全日停牌键若与 Raw 非全日停牌记录冲突，会在写入前失败 | [suspend_d.py](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/assets/suspend_d.py)，`_full_day_patch_conflict_rows()` |
| Silver 的显式数据依赖当前只有 Raw；CSV 没有独立资产身份 | 同文件 `silver_stock_suspend_daily` 的 `deps` |
| Raw 是按交易日请求和落盘的源镜像，不是最新日期保存全量历史 | 同文件 `raw_tushare_suspend_d`，以及 [paths.py](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/paths.py) |
| Raw 重抓使用本次请求结果替换目标文件，不合并人工补入的数据 | [tushare_api_io.py](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/tushare_api_io.py)，`fetch_tushare_partition_to_raw()` / `_write_rows_to_parquet()` |
| 当前另有 14 条停牌时段修正，不属于这份 CSV | [suspend_timing.py](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/corrections/suspend_timing.py)，本轮保留 |

### 3.2 已有只读数据证据

以下规模来自本任务 2026-09-06 前序只读审计；本轮重新核对代码、CSV 内容身份和 Git 基线，没有重新扫描正式 Lake。实施前需要刷新输入指纹，不能直接把这些点时数字当作写入授权。

| 项目 | 已核验结果 |
| --- | --- |
| 当前 CSV | 31 条区间，29 个股票代码，日期范围 2014-01-02 至 2026-01-16；无重复区间、无反向区间 |
| 按正式日历 SSE 开市日展开 | 4,022 个不同的“股票＋交易日”，涉及 1,857 个日期 |
| 对应 Raw / Silver 日期文件 | 两层各 1,857 个均存在；当时两层各有 3,083 个日期文件 |
| 现有 Silver | 4,022 个键均恰好有一条 `suspend_type='S' AND suspend_timing IS NULL`，无缺失、重复全日记录或冲突键 |
| 对应 Raw | 4,020 个键无记录；另外 2 个键共 3 条非全日停牌记录；不存在已经正确的全日停牌键 |
| 688766.SH / 2025-11-26 | Raw 为 `R + NULL`、`S + 09:30-09:30`；Silver 为一条 `S + NULL` |
| 688005.SH / 2026-01-16 | Raw 为 `S + 09:30-09:30`；Silver 为一条 `S + NULL` |

只读审计采用有界 DuckDB SQL、显式日期文件集合、`hive_partitioning=false`、聚合及集合差异；两次目标扫描各约 0.4 秒。这不是新方案的性能实测，也不是对历史交易所公告的再次独立核真。本文目标是迁移现有已确认口径，不借机重新判定哪些股票应该停牌。

本轮核验的迁移来源身份：

- 文件：`lake_console/orchestrator/src/orchestrator/defs/corrections/suspend_full_day_ranges.csv`。
- 最后修改提交：`77ff8e1de72d3cb2eaf7e212edc0f402f3a05763`，2026-05-21。
- 文件 SHA-256：`3969f5c9ccd177bb4ea389136798b6e28925b2a54b1a583e3a47bca2af8a9e63`。
- 两个覆盖键的依据是同基线 `suspend_full_day.py` 的 `SUSPEND_FULL_DAY_RAW_OVERRIDES`，不是旧 reports。
- 不读旧湖，不重新引入已删除旧日线报告中的其他标注，尤其不能补入现行修正集合以外的股票日期。

## 4. 目标资产与归属

### 4.1 固定资产事实卡

| 项目 | 目标设计 |
| --- | --- |
| 中文名 | 股票历史确认全日停牌事实 |
| asset key | `silver_stock_suspend_confirmed` |
| dataset id | `stock_suspend_confirmed`，在现有中文名映射登记 |
| 归属 | 正式 orchestrator 的股票行情域；维护责任属于停复牌数据管道，不属于分钟工具、旧 Console 或 Prod |
| layer / domain / group | `silver` / `quote_data` / `quote`，复用现有枚举 |
| 数据含义 | 已确认、有限集合的历史全日停牌事实，不是完整每日停复牌表 |
| 来源分类 | `SourceSystem.SEED` / `DataContractSource.SEED_CONTRACT`；历史来源版本固定，不冒充 Tushare 原样返回 |
| data contract | `confirmed_stock_full_day_suspend_v1` |
| 正式路径 | `/Volumes/datasource/data_lake/silver/quote/stock_suspend_confirmed/full/part-000.parquet`，**拟新增，尚未创建** |
| 分区模型 | 新登记 `full_file_silver_stock_suspend_confirmed`；一个全量文件，无 `partitions_def` |
| 时间语义 | 行内 `trade_date` 是事实发生日；发布日期不是业务日期；无“每天必须更新”的 freshness 要求 |
| 直接业务消费者 | 只有 `silver_stock_suspend_daily`；配套检查、审计、发布工具可以读取 |
| 唯一写入方 | 经人工批准的专用发布 helper / CLI；日常 asset、sensor、下游任务均只读 |
| 写策略 | 复用 `SINGLE_FILE_ATOMIC_REPLACE` 表达单文件提升；本版本实际只允许“目标缺失时发布 / 内容等价时复用 / 内容不等时停止” |
| 事件策略 | `SUPPORTS_RUNLESS_EVENT_BACKFILL`；文件发布与事件补录分开，正常日常不产生固定资产更新事件 |
| 资源 | 复用 `LakeRootResource`、`DuckDBResource`；不新增连接、数据库或环境变量 |
| 当前规模 | 4,022 行、29 个代码、1 个正式文件；不是 1,857 个小文件 |

### 4.2 固定事实的字段

| 字段 | 类型 / 可空性 | 来源与含义 |
| --- | --- | --- |
| `ts_code` | VARCHAR，非空 | 现有已确认代码，保留当前身份；不借本轮重做 BSE 代码映射 |
| `trade_date` | DATE，非空 | CSV 起止区间与当次锁定的正式 SSE 开市日集合展开结果 |
| `suspend_timing` | VARCHAR，可空 | 本资产固定为 NULL，表示全日停牌 |
| `suspend_type` | VARCHAR，非空 | 本资产固定为 `S` |
| `merge_mode` | VARCHAR，非空 | `add_missing` 或 `replace_confirmed`，见 §5；它不是运营可调开关 |

主键为 `(ts_code, trade_date)`。4,020 行 `add_missing`，两个已确认覆盖键为 `replace_confirmed`。字段顺序按上表固定。

`name` 和原始区间不进入运行时事实：股票名称不是合并键，区间已经展开。它们及批准依据保留在迁移审计记录中。无需在每行重复提交号、发布日期、来源文件路径。

版本、来源提交、来源文件哈希、行数、日期范围、目标逻辑哈希进入批准记录和资产 metadata。批准的版本及逻辑哈希在唯一合同模块登记，不能只读文件自己声明的哈希来证明它正确。

逻辑哈希覆盖全部五列、固定列序、显式 NULL 表示和 ISO 日期，按 `(ts_code, trade_date)` 排序后计算 SHA-256；与 Parquet 压缩或物理行序无关。序列化格式及字面金样本已在 LLD §3.3 固定。**S0 已从实际来源展开并实算批准逻辑哈希，值见 LLD §3.3 及 S0 清单 §3；新 Parquet 尚未生成，不能混同为物理发布凭据。**

### 4.3 对外 Silver 合同不变

`silver_stock_suspend_daily` 保持：

- 原 asset key、dataset id `suspend_d`、`cn_a_stock_trade_days` 分区及正式路径。
- 原四列：`ts_code VARCHAR`、`trade_date DATE`、`suspend_timing VARCHAR`、`suspend_type VARCHAR`。
- 原三个 blocking check 名称，不为了命名整齐重命名历史 check。
- 合法空分区、全日停牌、盘中停牌和复牌的现行业务含义。

`merge_mode`、批准版本及历史来源信息不向最终四列追加。这里的“统一 Silver”指统一输出事实，不要求它只能有一个上游。

## 5. 合并语义：只搬迁既有事实，不改业务判断

生成指定交易日时，读取同日 Raw、固定事实中同日记录，并保留现有 14 条停牌时段清洗。

| 固定事实 | 对应 Raw 标准化后的情况 | 处理 |
| --- | --- | --- |
| 无此键 | 任意现行合法记录 | 继续现有清洗，不因本方案增加、删除或覆盖 |
| `add_missing` | 无记录 | 增加一条 `S + NULL` |
| `add_missing` | 已有正确全日停牌记录，且无其他冲突 | 不再追加；原有重复/质量检查不放宽 |
| `add_missing` | 存在 `R`、盘中停牌或其他非全日记录，包括“正确记录与冲突记录并存” | 失败并列样本，不自动选一边 |
| `replace_confirmed` | 两个原已批准覆盖键 | 沿用原来的按键覆盖语义：输出一条确认事实，不输出该键的 Raw 记录；Raw 文件本身不变 |
| `merge_mode` 未知、固定事实重复或内容非批准版本 | 任意 | 失败，不去重修补后继续 |

两个允许覆盖键精确限定为 `688766.SH / 2025-11-26` 和 `688005.SH / 2026-01-16`。这里“新的冲突需人工确认”指不在已批准覆盖范围内的冲突；不将这次迁移悄悄变成新的冲突裁决策略。未来若要改变这两个已确认事实，也必须另行审计和批准。

目标实现：

1. 将合并逻辑抽成接收 Raw 标准化关系、已校验固定事实关系的纯 SQL helper，日常与批量审计共用。
2. 日常固定事实只加载到本次连接的有界临时关系，校验和合并复用；不保留跨进程、无版本的 `@cache`。
3. 保留现有冲突先失败、后写入的边界；冲突查询仍使用时段修正前的 normalized Raw，不调换次序。不将冲突降为 WARN，不以自动去重掩盖冲突；冲突总数与最多 20 条样本分开统计。
4. 保留 `suspend_timing.py` 及对应 SQL 清洗，不将“删除 CSV”扩大成删除整个 corrections 目录。
5. 旧 CSV 加载、区间 VALUES 构造、独立覆盖元组和旧统计实现同轮退出，以固定事实的数据和统一 helper 承接，不留双轨兜底。
6. 当前 `assets/suspend_d.py` 私有 `_replace_parquet_from_query()` 使用正式目标旁的 `.tmp`。本次改动到的 Silver 写入应改为独立 staging 候选、完整性校验后同文件系统原子提升；不能沿用正式 Lake 内 staging。范围仅限该文件的 Silver 调用，不凭同名函数批量修改其他资产，也不改 Raw writer。

最终 Silver 的候选路径拟为 `/Volumes/datasource/data_lake_staging/stock_suspend_daily/run_id=<运行标识>/trade_date=<业务日期>/part-000.parquet`，由 `paths.py` 的专用 staging helper 生成。该调整不改变最终正式路径或输出字段；候选丢失/验证失败时保留原正式文件，不先删后写。单日任务按候选与实际目标核验重试，不能承诺文件和 Dagster 事件跨系统原子提交。

## 6. Dagster 登记、检查与触发

### 6.1 固定数据采用非日常执行的资产登记

拟使用 `AssetSpec` 登记固定事实，由专用人工工具发布物理文件。它在 Dagster 中是外部资产，**“外部”指不由日常 Dagster 计算生成，不指远程服务器**。不为其增加自动更新 asset、sensor 或 schedule，也不在业务 job 中顺手重新生成它。

官方支持将由独立工具写入的 Lake 文件登记为外部资产，并作为普通资产的上游：[External assets](https://docs.dagster.io/guides/build/assets/external-assets)。

当前项目固定依赖 Dagster 1.13.18；本轮读取了本机安装包的模块发现实现，确认其对象模型支持 `AssetSpec`。但当前仓库 `tests/test_asset_governance_contracts.py::_asset_specs_and_definitions_by_key()` 默认逐个处理 `AssetsDefinition`，**需扩展外部资产的纳管，不得把新资产排除在 catalog 对账之外**。

开发前隔离验证必须证明：自动发现、catalog 对账、无分区外部检查与有分区下游 job 共存、blocking 检查失败阻断下游。文档查阅和静态源码检查不等同于这些验证已通过。

### 6.2 两项新增固定事实检查

| 新 check 名称 | 验证属性 | 失败行为 |
| --- | --- | --- |
| `silver_stock_suspend_confirmed_schema_check` | 文件可读、五列物理类型及字段合同 | blocking；缺失/错误明确报错 |
| `silver_stock_suspend_confirmed_approved_content_check` | 内容属于批准版本：逻辑哈希、键唯一性、4,022 行及合并模式范围一致 | blocking；不自动修数据或回退 CSV |

checks 绑定固定资产的 `AssetKey`，无日期分区，不套用每日 freshness。它们与只读 readiness、发布完整性校验复用纯校验 helper，不分别实现三套判断。

S1 隔离实测：Dagster 1.13.18 的 `AssetCheckResult` 在日期 job 内自动按 job 日期查固定发布，因此两个检查虽通过，却缺少无分区发布的原生 target，不能满足 readiness。**不降低关联要求。**已批准仅在两个固定检查的 adapter 显式产出关联真实发布的原生 `AssetCheckEvaluation` 和依赖完成输出，保持 ERROR blocking；不做日常 runless 补录，不改 SDK。框架可行性样例 5 项通过，但实际 adapter 部分实现尚未验收，不能用该实验替代；完整设计见 LLD §15.3。

两个新 checks 的文件前置核验采用只读路径/普通文件检查，取消现有部分实现中会写探针的健康 helper 调用；不改其他资产共用的健康函数、Lake/DuckDB 默认配置。Dagster 正常 check event 仍保留。测试必须先证明进程级文件隔离覆盖原生 DuckDB/SQLite IO，再验证实际 check，不以网络 mock 或任意失败充数，详见 LLD §18。

最终 Silver 保留原 checks。合并公式由独立字面 expected 测试和一次性迁移对账证明，日常生产 check 不全量重算整个历史结果。

### 6.3 更新入口和安全边界

- `raw_suspend_d_update_job` 及其 sensor：不改。
- `silver_suspend_d_update_job`：保持名字和 Silver-only 写入边界；加入固定资产的两个 checks，确保本 run 检查通过后才生成 Silver。不得选择 Raw 或固定资产的写入动作。
- `silver_suspend_d_update_job_sensor`：保留已有日期选择、运行窗口、单 tick 上限及 run key；在确有候选日期时，对固定资产只做一次共享 readiness 判断，不在日期循环内反复检查。
- 固定事实 readiness：已发布记录及检查身份与批准版本相符，并以当前文件的完整性检查确认可读；不以“有一次历史绿灯”代替当前文件。无日更时效要求，不读取其他 Ops 状态。
- 人工直接生成/重建 Silver：仍必须读取批准版本；缺文件、内容不符、未知模式必须在写正式输出前失败。不能依靠“正常都会经过 sensor”保证安全。
- 更新固定资产不是日常工作，唯一写入入口要求人工维护窗口；禁止同时运行两个发布者。日常读取方无写权入口，不增加锁文件、锁服务或自动修复队列。

仅声明 `deps` 不保证任意选择方式都会执行 checks；LLD 和测试必须落实 job selection、独立调用和失败边界。参照 [Asset checks](https://docs.dagster.io/guides/test/asset-checks)。

S1 提前验证的原模型共 8 项：selection、执行顺序、错误阻断及无日期对照 7 项通过，日期 job 的原生 target 关联 1 项失败。停止业务代码改造，不因 job 成功就标记 S1 完成，也不改成仅靠 sensor 检查。事件查找修正不改变 Raw/Silver 业务字段和合并语义。

## 7. 本地消费者审计与处理矩阵

本轮 CodeGraph 使用 `explore` 覆盖加载、路径与 Silver 生成，`impact(silver_stock_suspend_daily_path, depth=2)` 命中分钟 writer/check 等影响点。图中存在漏边，故另以全仓引用搜索和当前函数读取补齐，未把图的零命中当作无消费者。

以下路径均相对 `lake_console/orchestrator/src/orchestrator/`。只改真正生产或校验输入的地方；已经正确消费最终 Silver 的代码以回归为主。

| 当前文件 | 实际用途 | 本轮处理 |
| --- | --- | --- |
| `defs/assets/suspend_d.py` | 生成 Raw/Silver，执行全日补充、冲突检查与统计 | Raw 不动；Silver 增加显式上游，改读固定事实和统一合并 helper；本文件 Silver 写入改用独立 staging |
| `defs/duckdb_sql.py` | Raw 标准化、14 条时段修正、CSV 补充与两条覆盖 | 修改全日补充输入；保留标准化及时段修正 |
| `defs/corrections/suspend_full_day.py` | CSV 读取、范围 SQL、两条覆盖元组和样本 | 等价迁移验收并获准后删除整文件，不保留 import 兼容 |
| `defs/corrections/suspend_full_day_ranges.csv` | 当前 31 条运行时范围规则 | 固定事实发布、切换、验收并获准后删除；此前继续保护 |
| `defs/corrections/suspend_timing.py` | 14 条独立停牌时段清洗 | 保留，不扩大本轮范围 |
| `defs/paths.py` | 正式 Raw/Silver 路径 | 新增固定事实路径及最终 Silver staging helper；现有正式路径不改 |
| `defs/catalog/lake_assets.py` | 资产、字段、分区、来源、checks 与写入策略登记 | 增加固定资产事实卡、无分区模型；更新最终 Silver 的来源说明 |
| `defs/catalog/name_mapping.py` | dataset 中文名 | 增加新固定资产中文名 |
| `defs/run_contracts/asset_column_schemas.py` | 稳定字段 schema | 增加五列固定事实 schema；现有 Raw/Silver schema 不改 |
| `defs/run_contracts/metadata.py` | metadata 统一构造与命名空间 | 复用；新增版本/完整性观测字段先登记，不恢复旧裸 key |
| `defs/checks/suspend_d_checks.py` | 最终停复牌检查 | 保留现有名称和语义；补来源切换回归，不用新名字替换旧检查 |
| `defs/jobs/suspend_update.py` | Raw-only / Silver-only job selection | 仅 Silver job 加固定输入检查 |
| `defs/sensors/suspend_d_sensor.py` | 选择待生成停牌日期并检查 Raw readiness | 加一次固定事实 readiness，原日期策略不变 |
| `defs/sensors/readiness.py` | 资产 readiness 身份和门禁 | 增加固定资产身份和专用只读入口，不向所有消费者传修正规则 |
| `defs/assets/stock_daily.py` | 声明停牌依赖、验证同日文件；日线生成 SQL 本身不是停牌过滤器 | 保留；不能借本轮给日线生成 SQL 新加删行逻辑 |
| `defs/checks/stock_daily_checks.py` | 从生命周期股票集合扣除 Silver 全日停牌，检查日线覆盖 | 保留，验证补缺与覆盖计数不变 |
| `defs/sensors/stock_daily_raw_repair.py` | 用 Silver 全日停牌排除不应补拉的日线代码 | 保留，不改读固定资产或 Raw |
| `defs/assets/stk_mins.py` | 身份映射后用 Silver `S + NULL` 排除全日停牌分钟记录 | 保留，五个原生频度及 1m fallback 回归 |
| `defs/checks/stk_mins_checks.py` | 检查 Silver 分钟不含全日停牌结构性记录 | 保留 |
| `defs/asset_guards/stk_mins_lake_readiness.py` | 批量复刻分钟 check 所需的停牌事实读取 | 保留，不能引入固定事实旁读或变重日期循环 |
| `defs/bootstrap/stk_mins_silver_history.py` | 历史重建前置文件与正式分钟 writer | 保留，仍通过最终停牌 Silver |
| `defs/bootstrap/stk_mins_silver_replace_from_raw.py` | 恢复候选、输入指纹、正式分钟 writer | 保留；既有恢复计划只跟踪实际消费的最终 Silver，不新增固定事实直接输入 |
| `defs/bootstrap/stk_mins_bse_history_recovery.py` | 同日停牌排除、1m fallback、候选恢复 | 保留；不扩大 BSE 修复范围、不改变当前 CLI |
| `audits/stk_mins_silver_strict_audit.py` | 将日线或停复牌出现的代码用于覆盖诊断 | 保留；这里读取全部停复牌代码，不等于全日停牌过滤，不能统一改成 `S + NULL` |
| `defs/checks/stock_partition_checks.py` | 停牌分区归属 checks | 保留最终 Silver 分区及名字；固定资产无分区，不塞进此检查 |
| `defs/bootstrap/historical_materialization_reconciliation.py` | 路径与历史事件对账 | 保留旧资产映射；不自动批量补写历史停牌事件 |
| `defs/bootstrap/asset_check_event_retention.py` | 历史事件保留策略中的资产身份 | 保留，不因新增固定资产清理任何历史事件 |

新资产只增加一个直接消费者：`silver_stock_suspend_daily`。检查、发布和审计是治理读取方，不是另一条业务口径。

本轮全仓目标字符串搜索未在 `src/**`、`qtf/**` 发现直接读取这份 CSV 或 DG 停牌路径的新增入口；这不是声称这些域没有停牌业务。既有 Prod 停牌链路、Foundation Local Lake 分钟读取器、前端和 API 均不在改造清单，不修改子系统依赖矩阵。

## 8. 计划新增代码与测试落点

下列为计划新增清单，不能理解为当前全部不存在；已有部分实现见 LLD §17.3，事故后下一轮修改白名单见 §18.2。正式命名不使用清退阶段编号。

| 拟新增文件（相对 orchestrator 工程） | 单一职责 |
| --- | --- |
| `src/orchestrator/defs/assets/stock_suspend_confirmed.py` | 固定资产 `AssetSpec`、中文说明和 definition metadata；不在 import 时读盘 |
| `src/orchestrator/defs/stock_suspend_confirmed_contract.py` | 唯一批准版本、逻辑哈希合同、合并模式及有界纯校验/SQL 关系 helper；不复制 31 条明细到代码 |
| `src/orchestrator/defs/checks/stock_suspend_confirmed_checks.py` | 两个固定事实 blocking checks |
| `src/orchestrator/defs/bootstrap/stock_suspend_confirmed.py` | 专用候选核验、等价比较、人工发布及状态对账，不承担每日同步 |
| `src/orchestrator/defs/bootstrap/stock_suspend_confirmed_cli.py` | 专用人工操作入口；不接入现有 `stk_mins` CLI，不增加其参数或命令 |
| `tests/test_stock_suspend_confirmed_contracts.py` | 字段、内容身份、模式、空值、重复、哈希与路径边界 |
| `tests/test_stock_suspend_confirmed_merge.py` | 独立金样本：补缺、等价、不覆盖未批准冲突、两条覆盖、时段清洗、无修正日 |
| `tests/test_stock_suspend_confirmed_bootstrap.py` | 只读 audit、发布复用/拒绝、原子性、中断续跑、事件独立授权 |
| `tests/test_stock_suspend_confirmed_dagster.py` | AssetSpec 自动发现、无分区固定 checks 与分区 job 的执行次序、隔离事件关联 |
| `tests/stock_suspend_confirmed_test_runner.py` | 专项测试受限子进程、隔离先行、阶段与证据管理；不进入正式运行链 |
| `tests/stock_suspend_confirmed_test_support.py` | collection 前保护、临时资源与设置读回；不改全局测试框架 |
| `tests/test_stock_suspend_confirmed_isolation.py` | 独立 I 组正反验收，覆盖 Python 与原生 IO；不使用正式数据验证 |

需修改而非删除的现有测试：

1. `tests/test_asset_governance_contracts.py`：将非执行 `AssetSpec` 与执行资产共同纳入 schema、path、catalog、check 集合对账；不得用排除名单绕开。
2. `tests/test_run_contract_static_gates.py`：新增唯一读取方、无 CSV/Git 运行时回退、无自动 writer、无 Raw 写入、外部资产 metadata 门禁。
3. `tests/test_suspend_d_sensor.py`：固定事实缺失、内容错误、已发布但检查失败、无候选不重扫、共享检查一次、原 run key/日期选择不变。
4. `tests/test_suspend_d_checks.py`：保留当前三个 Silver checks 和两个 Raw checks 的名字与合法空分区行为。
5. 仓库根 `tests/architecture/test_lake_console_retirement_guardrails.py` 当前断言 CSV 必须存在。删除阶段必须精确替换此锚点为新正式资产代码与禁止旧加载的检查；其余 Local Lake、Ops snapshot、ClickHouse 保护全部保留。根测试不能访问移动盘来检查新物理文件。

回归集合还包括当前 `test_stock_daily_raw_checks.py`、`test_stock_daily_raw_repair.py`、`test_stock_daily_freshness_guard.py`、`test_stk_mins_silver_m5b_contracts.py`、`test_stk_mins_silver_m5e_job_contracts.py`、`test_stk_mins_lake_readiness.py`、`test_stk_mins_silver_m6_history.py`、`test_stk_mins_silver_replace_from_raw.py`、`test_stk_mins_bse_history_recovery.py`、`test_stk_mins_silver_strict_audit.py`，以及相关日常连续性/增量 check 治理测试。实施时按实际差异冻结测试文件清单，不把关键分钟回归删掉来通过新来源切换。

## 9. 迁移与切换：先具备新输入，再退出旧输入

### S0：冻结来源与实现合同——低风险，只读/文档

1. 刷新 CSV、两个覆盖键、正式 SSE 开市日集合及目标 Raw/Silver 指纹。
2. 从版本固定的 CSV 与正式日历一次性展开 4,022 个键；不从最终 Silver 反推全部历史事实。
3. 只把两个既有覆盖键标为 `replace_confirmed`，剩余为 `add_missing`；确认无额外范围、重复或缺失。
4. 与现有 Silver 对账，并单列“保留现有效果”和“独立业务真实性”两类结论。
5. LLD 已获认可：固定逻辑哈希编码、函数边界、CLI 参数、事件接口、字段/metadata 登记、隔离验证方案见配套文档。来源或结果不符时停止，不擅自更新批准哈希。

2026-09-06 S0 完成：上述输入已刷新，真实逻辑哈希已回填，4,022 键的现有 Silver 效果全部通过；两层各 3,083 文件，无非开市日分区、错放日期或输入漂移。S0 时工作区被正式 code location 直接加载、两个停牌 sensor 均 RUNNING，因此提出 S1 开发前先批准维护安排。明细见 S0 清单；本阶段不创建候选或执行新 helper 全范围对账。后续批准与暂停事实见 S1，不覆盖 S0 历史快照。

### S1：隔离实现与测试——中风险，事故后安全修正待 review

1. 原模型 D06 关联失败后的 LLD §15.3 窄修正已确认，部分代码已写；实际 adapter 测试发生正式湖探针越权，当前不是等待再次确认框架方案。先 review LLD §18，再只实现并独立验收测试隔离；不能直接重跑业务测试。
2. 隔离验收后，只修两个新 checks 和 C/D 测试，核对实际失败原因、阶段、原生发布关联和临时目标不变；报告后继续原 S1 的合同、专用发布入口、纯合并 helper、writer 和 readiness 等剩余项。安全修正通过不等于 S1 完成。
3. 本阶段只允许临时虚构数据测试，不准备真实迁移候选。实际候选放在 `/Volumes/datasource/data_lake_staging/stock_suspend_confirmed/run_id=<批准的运行标识>/`，按 LLD §11 归 S2 的独立 staging 授权，不将 S1 开发批准当写入批准。
4. 一次性 CSV 展开脚本仅用于后续获准的迁移准备，存放在审计临时区，不注册进 Definitions、不成为日常依赖。长期发布 CLI 只接收经过校验的 Parquet 候选，不提供 CSV 回退模式。

维护历史记录：2026-09-06 17:47:27（北京时间）仅停牌 Silver sensor 变为 STOPPED；88 个 sensor 中其他 87 个状态不变，Raw 仍 RUNNING，暂停前后无活动 run。该维护步骤本身无业务源码修改、正式文件/事件写入、删除、服务重载或提交；不代表后续事故没有越权写入。维护期间不手工启动停牌 Silver job；S1 结束不自动恢复入口。

### S2：全范围只读等价验证——中风险，不写正式结果

先取得真实 staging 准备授权，生成一次性候选并校验 schema、主键、模式、计数、逻辑哈希、来源指纹，冻结候选与 plan；此步骤有 staging 写入，不以“只读等价验证”之名隐含授权。后续对正式 Raw/Silver 的比较保持只读：

1. 验证全部 1,857 个受影响日期，而不只抽两只股票。
2. 按年度或有界日期批，读取所选 Raw 与当前 Silver，以新合并 helper 得出候选关系；最终四列进行双向 `EXCEPT ALL`，必须零差异。
3. 对其余已有日期亦完成范围内新旧关系对账，证明不新增停牌、不改变盘中停牌/复牌。以 S0 文件清单为上限；新增日期须显式刷新清单，不递归扫描其他湖目录。
4. 固定事实每批只加载一次；不能循环 1,857 次调用正式 asset、sensor 或逐日 Dagster 深审计。
5. 新合并结果与当前正确 Silver 等价时，**不为了迁移重新覆盖全部历史 Silver**。只记录等价审计，不伪造新的历史 materialization。
6. 独立字面金样本测试证明算法；物理对账证明迁移等价。两者不能用同一 helper 生成 expected 后自证。
7. CSV 原逻辑按日期区间判断，新固定集合按开市日展开；若现有非交易日文件也受到原规则影响，必须列差异并停止，不能默认两者等价。批读还需核对行内日期与文件分区，避免跨分区错放在总集合比较中抵消。

### S3：固定事实发布与登记——高风险，逐项批准

正式数据写入目标仅一个：§4.1 的固定事实 Parquet；Raw 写入数为 0，历史最终 Silver 批量写入数为 0。

1. 用户审查候选来源、逻辑哈希、唯一目标、磁盘和占用检查、预期事件清单后，批准文件发布。
2. 确认挂载正确、目标不指向其他目录、候选与目标同文件系统、无其他发布者。
3. 目标缺失：完整校验候选后 `os.replace()` 原子提升；目标等价：复用；目标不等价：停止，禁止自动覆盖或删除。
4. 发布后重新读回，保存本 run checkpoint。中断后以正式文件事实为准：文件正确而 checkpoint 未记下，补记完成；文件不符或缺失且候选丢失，保留现场人工处理。
5. 文件确认后，另行批准外部资产事件登记：本版本首次人工登记最多 1 条 materialization + 2 条通过的 check 事件，不限制日常 job 的正常 check evaluations。已有完整匹配记录不重复写；LLD §9 规定确定性 token、逐条 pending/confirmed 和真实事件身份读回。API 超时或 pending 但无法确认结果时停止人工核验，不能盲目重发，也不承诺事件 API 自带唯一键事务。
6. 事件写入失败不得撤回或删除已正确发布的文件；先报告“文件已发布、观测未完整”，经批准补齐事件。不能把事件失败当成重新写文件的理由。

### S4：切换正式读取与验收——高风险，人工维护窗口

1. 只在固定文件已发布、检查与来源身份已核验后，才将正式停牌 Silver 切换到新输入。
2. 代码部署/重载须在批准的本地维护窗口进行，检查没有旧代码执行中的停牌写任务；暂停及恢复的本地触发器精确列单，不泛停其他数据集。
   实施前还应核实工作区是否被正式 code location 直接加载；不能假设“尚未重载”就允许边改源文件边运行旧写任务。这个运行边界须先明确，不能自建分支/worktree 绕开。
3. 新代码只读固定事实，不保留“文件缺失就读 CSV”的兼容路径；代码和输入必须成对满足上线前置条件。
4. 以批准的少量日期运行正式 Silver-only 验收：至少覆盖两个覆盖日期、一个纯补缺日期和一个无历史修正日期。Raw 不重抓，其他业务资产不顺手重跑。
5. 这些日期结果必须等价，现有 checks 通过；再观察下一次正常本地日更及下游 readiness，不以本轮手动验证代替日常链验收。
6. 若未通过，停止继续切换或推广，保留现有正式文件和候选，修正后重新验证。不自动恢复 CSV 运行时路径，不引入 Kopia、备份或快照。

### S5：退出旧读取链与文档收口——中风险，删除需明确确认

1. 审查后删除精确两文件：`defs/corrections/suspend_full_day.py`、`defs/corrections/suspend_full_day_ranges.csv`；不删除 `suspend_timing.py` 或目录中的其他内容。
2. 最终代码切换与旧 import 清理必须同一交付版本完成。物理删除仓库 CSV 可以放在最后确认，但正式执行代码不得保留双读取逻辑。
3. 更新根清退护栏、直接引用文档、资产图、readiness 登记与本 TODO 状态；历史审计文字保留其日期语境，不假装过去从未读过 CSV。
4. staging、审计报告和异常现场不自动删除，另列清单确认。完成技术迁移不代表授权清理其他数据。

## 10. 执行预算与性能验收

依据正式 onboarding 模板 §7A 填写；本方案不新增 Tushare 请求、不接入 Prod，不需要用接口探测来论证本次存储迁移。原始接口参数和 Raw schema 均不修改。

| 维度 | 预算与口径 |
| --- | --- |
| 业务规模 | 31 个范围 → 29 个代码 / 4,022 个键 / 1,857 个日期；无频度扇出 |
| 请求 / 分页 / DB 连接 | 新增 Tushare 0、Prod 0、ClickHouse 0；事件登记仅本地 Dagster，单独批准 |
| 正式文件 | 新固定资产 1 个；既有 Raw 不写；历史最终 Silver 不批量重写 |
| 候选文件 | 固定事实 1 个，加有限样本候选；全范围等价用关系查询，不强制生成上千份候选 |
| 历史扫描 | 上限为 S0 冻结的两个停牌目录文件清单；前序基线两层各 3,083 文件；按年度/有界批读，每批固定事实只加载一次 |
| SQL / DuckDB | 纯 SQL 展开、合并和集合对账；复用统一连接。每批记录真实 SQL 数和读入文件数，不做逐日 Dagster 调用 |
| 日常新增读取 | 生成器读固定事实 1 次；两个固定 checks 各最多 1 次；sensor 有候选时每 tick 1 次固定事实校验，不按日期重复 |
| 日常事件读取 | 固定资产最多 1 次有界 materialization 查询、2 次有界 check 查询，整 tick 复用；不读取全部历史 |
| 内存 / spill | 固定事实只有 4,022 行，新增关系预期远低于 512 MiB；既有 DuckDB 默认 16GB / 4 threads 等配置不改，本固定事实路径预期不 spill |
| 空间 | 新固定 Parquet 预计不足 1 MiB，准备/报告预算 100 MiB；均为估算，S0/S1 实测后登记。空间不足或范围扩大停止，不扩配额兜底 |
| 耗时 | 前序目标读审约 0.4 秒/层，仅作参考。新增日常开销目标不超过约 1 秒；人工整体验证目标分钟级，超过 5 分钟记录慢阶段，不因单次略慢取消正确性验收 |
| 超预算处置 | 额外网络请求、超出批准文件集合、错误写入层、无界日期循环是硬拒绝；低频耗时属于诊断/人工复核，不设苛刻倍率门禁 |
| 提交 / 重试单位 | 唯一固定文件；每个正式验收日期独立原子提交。checkpoint 与物理文件对账，不声称文件与事件整体原子 |

性能验收分离：新 helper 的纯计算、Parquet 读取、Dagster 检查/事件开销分别计时。不得把前序 0.4 秒当作新增 checks 和 sensor 已实测通过。

## 11. 可观测性、配置与故障处理

### 11.1 不增加散落配置

| 项目 | 来源 / 生效 / 消费者 |
| --- | --- |
| Lake 根 | 现有 `LakeRootResource` / `paths.py`，保持不变 |
| 固定事实正式路径 | 新路径 helper，由定义、checks、生成器和发布工具共用；不得另加 env 或任意目标路径输入 |
| 批准版本、逻辑哈希、schema、合并模式 | 唯一 `stock_suspend_confirmed_contract.py` 合同与批准记录；不是运营手填参数，变更须评审并重新发布 |
| 人工 CLI 参数 | 仅候选标识/路径、操作阶段和明确执行意图；候选必须位于本专项 staging，不能透传任意 SQL、Raw 路径、合并开关或目标表 |
| 其他连接/资源/前端设置 | 不新增、不修改 |

CLI 精确参数、默认只读行为和退出码已在 LLD §8 固定，均为未实现接口：`inspect`、`compare`、`publish-file`、`audit-events`、`register-events`。文件发布和事件登记分开确认；只读模式不写报告或 checkpoint，显式保存报告属于另获准的 staging 写入。不改现有 `stk_mins` CLI。

### 11.2 人能看懂的运行信息

- 固定资产说明：“已确认的历史全日停牌事实，仅由人工发布，供每日停复牌标准表合并使用。”
- Silver job 说明：“在原始停复牌数据和历史确认事实合格后，生成当日统一停复牌数据；不修改原始数据。”
- source materialization：实际 URI、4,022 行、观察字段、批准版本、来源提交、逻辑哈希及审计引用。
- Silver materialization：输入版本、本日补入数、本日复用数、已批准覆盖键数、被覆盖的输入行数和最多 20 个样本。历史 metadata 不批量改写。
- check metadata：使用现有 helper 和命名空间，给出失败规则、计数、最多 20 个样本、中文结论与下一步。
- sensor：共享输入阻断用短中文说明，不把 4,022 条事实或全日期清单写进 cursor。新增字段先同步 run-contract 治理文档和静态测试。

| 现象 | 处理 |
| --- | --- |
| 固定文件缺失/损坏 | 阻断新 Silver 写入，保留已有结果；人工恢复同一批准内容，不自动用空集或 CSV |
| 目标已存在但不等价 | 停止发布，展示差异；不自动覆盖，也不提高“允许覆盖”级别 |
| Raw 出现未批准冲突 | 当前 Silver 生成失败，给出股票、日期、源记录样本；人工裁决，不改 Raw |
| 文件正确但事件未补齐 | 不重写文件，单独审计并补齐同版本观测 |
| 固定事实未来需要变更 | 单独列差异键、依据、受影响日期与下游重建范围，人工批准后处理；本方案不预建版本管理后台 |

固定文件丢失后的恢复依据必须可追溯：保留来源提交、CSV blob 身份、展开交易日集合指纹及批准逻辑哈希。必要时由人工从固定 Git 证据与正式日历重建候选，只有命中原批准逻辑哈希才可发布；不恢复旧运行代码。Git 只有规则而非完整灾备，若无法复现，明确停止，不能声称凭 metadata 哈希就能还原数据。

## 12. 验收矩阵与完成标准

| 验收项 | 必须证明的结果 |
| --- | --- |
| 固定输入身份 | 31 个范围准确展开，4,022 键、29 代码、1,857 日期及两个覆盖键一致；无非批准项 |
| 迁移等价 | 全部批准日期范围新结果与当前正确 Silver 双向 `EXCEPT ALL` 为零；既有其他日期不变 |
| Raw 重抓场景 | 隔离测试用原源镜像替换 Raw 后重建 Silver，历史修正仍存在；正式验收不为此重抓 Raw |
| Silver 重建场景 | 隔离测试删除临时 Silver 后能用 Raw＋固定事实重建，不读旧输出；不删除正式 Silver 做试验 |
| 补缺 / 覆盖 | 缺失补齐、正确不重添、两个明确覆盖、未批准冲突失败、正常交易日不误标 |
| 边界保持 | 14 条时段清洗保持；盘中停牌、复牌不被全日化；既有合法空分区仍合法 |
| 非法输入 | 文件缺失、错误 schema、重复键、错误内容哈希、未知模式、越界候选路径均失败且无正式写入 |
| 测试隔离 | LLD §18 I 组先行，实际生效路径/临时实例/原生 IO 拒绝均有证据；不以任意失败、skip 或修改全局默认值通过 |
| Dagster 集成 | AssetSpec 被发现并纳管、固定 checks 正确绑定、无日更 freshness、失败阻断下游、日常不写固定资产 |
| 绕过 sensor | 手动 job / 直接生成路径不能在固定输入缺失或错误时产出正式文件 |
| 中断与复用 | 原子提升后 checkpoint 丢失可识别完成；同内容复用；不同内容拒绝；事件失败不撤回正确文件 |
| 本地消费者 | 日线缺口与补拉集合、五频分钟过滤、BSE fallback、严格审计结果保持；不要求不同用途使用相同过滤谓词 |
| CLI / 边界 | 原 `stk_mins` CLI 行为不变；Prod、远程 Web、ClickHouse、Ops snapshot、其他数据集零改动 |
| 旧依赖退出 | 最终运行代码无 CSV 加载/旧 import/区间 VALUES/旧覆盖元组兜底；清退护栏精确更新，时段修正保留 |
| 性能 | 满足 §10 的范围和调用次数，计时透明；不跑全历史逐日 Dagster 深扫 |

完成必须同时满足：固定资产已发布并可观测、正式读取已切换、结果等价、日常链验收通过、旧依赖获准退出、相关文档与测试对账。仅写好文档、通过静态检查或生成候选，都不能关闭 TODO。

## 13. 文档同步与当前交付状态

本次文档改动范围：

1. 新增本文，作为 `TODO-SUSPEND-001` 的唯一实施主案。
2. 清退 LLD §16.11、清退专项方案 §0.3、M0 清单 §19 添加后续方案入口及新确认边界；保留清退历史事实和 CSV 当前保护状态。
3. `docs/README.md` 增加索引，明确“方向已确认、待实施”。

后续代码实施同轮需要同步：[资产目录](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-new-lake-asset-catalog-design.md)、[资产与 Job 拓扑](/Users/congming/github/goldenshare/lake_console/docs/architecture/dagster-asset-job-topology.html)、[readiness 登记](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-silver-raw-readiness-registry.html)、[run contract 治理](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-run-contract-governance.html)及两份 Lake AGENTS 的相关 CSV 保护说明。按实际落地更新，不提前把现有架构图改成已实现。子系统依赖矩阵不变；CodeGraph 架构快照待真实入口/依赖变化后再按根规则判断是否更新。

依据：

- [原 TODO 与清退 LLD](/Users/congming/github/goldenshare/lake_console/docs/design/legacy-lake-console-kopia-old-lake-bootstrap-retirement-low-level-design-v1.md#suspend-confirmed-followup)。
- [正式接入模板及 §7A](/Users/congming/github/goldenshare/lake_console/docs/templates/dagster-dataset-onboarding-template.html#source-contract-budget)。
- [编码规范](/Users/congming/github/goldenshare/lake_console/orchestrator/CODING_STANDARDS.md)、[字段合同设计](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-asset-schema-contract-design.md)、[性能治理](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-data-pipeline-performance-governance.md)。
- 本文各表对应的当前代码、现有测试及 §3 标记的前序只读审计证据；未用清退文档替代代码核验。

当前未完成：完整 S1 开发与验收。已有部分业务代码和测试，并执行过指定 sensor 停止；另发生未经批准的正式健康探针写入，见 LLD §17。未执行停牌业务数据迁移、真实候选准备、Tushare/Prod 请求、正式作业/materialization/check 事件、服务重载、CSV 删除、Git 提交或推送。不得笼统写成“未改代码、正式环境零写入”。

本轮文档验证：仓库文档完整性检查通过；另核本文 15 个本地链接及显式锚点、§7 的 27 个现有文件路径，均存在；已跟踪差异和新文档的空白/差异检查通过。这些检查只证明文档引用与格式，不代表新资产、合并算法或正式迁移已验收。

2026-09-06 LLD 细化补充：已形成配套 LLD 并同步上述接口/顺序边界；业务代码、正式/候选文件、Dagster 状态仍未改变。原文档验证数字是技术方案首轮记录，不代表 LLD 或新代码的验收结果。

2026-09-06 S0 补充：用户已认可方案并授权 S0，已完成真实只读核验和部署边界确认；未写业务代码、正式/候选文件或 Dagster 状态。S0 结果及方法单独落清单，不覆盖以上两轮文档验证的历史记录。

2026-09-06 S1 补充：用户已批准开发与维护安排，指定 Silver sensor 已暂停；原模型隔离测试 7 过 1 失败，窄修正机制实验 5 过。业务实现因 LLD 与 SDK 关联行为冲突暂停；维护状态、源码根因、测试范围与证据均落 LLD §15，不将临时机制实验冒充业务验收。

后续确认与实际偏离：用户已批准 LLD §15.3，已开始固定合同/AssetSpec/check/catalog代码。首次测试误用资源参数，回落到正式 Lake 并触发现有健康检查的探针写入/删除；该动作未经批准，不能再声称实际“正式环境零写入”。已停止并只读核实探针目录无残留，未进入停牌writer或正式事件发布；完整范围、证据限制和修复建议落在LLD §17。纯合同测试通过不代表整体S1验收。

当前下一步：用户已同意先补方案供 review。本轮补齐 LLD §18 的逐文件矩阵、资源构造、文件/网络隔离、失败证据和执行门；文档 review 后才修隔离并单独验收，再修两个新 checks、验证 D06/D07，最后继续原 S1。隔离需要覆盖 DuckDB 原生 IO；本机 sandbox-exec 只查阅了路径与手册，其弃用状态和未验证可用性已披露，能力失败即停，不降级运行。原字段、合并规则和其他业务范围不变；S2–S5 仍按阶段批准。Silver 自动入口未自行恢复，本轮未重跑任何测试。
