# 本地 DG 停牌历史确认事实持久化与统一消费技术方案 v1

更新时间：2026-09-08

状态：**S0–S2已完成，S2六份文档已提交`47ae5404`、未推送。S3文件侧已完成：首次OS规则拒绝后，管理员确认最小修正，一次重试成功发布4,022行固定事实；完整读回通过，checkpoint=committed，6,166个既有Raw/Silver文件未变，详见LLD §18.29D。事件登记尚未批准/执行，S3整体未关闭；切换、CSV删除及最终清理未执行，未恢复sensor或安装套件。本轮记录未提交。**

首次设计基线：`dev-interface@b324ec48ce8fd67fdf216fedc6a69103fab4ae3a`；本次文档修订依据为`dev-interface@f003a3c5`及现有未提交专项代码，未将其视为已验收实现。

管理员新增收尾约束（2026-09-07）：未经明确允许不得在本机安装套件；前置验收只保留与本需求直接相关的必要范围，不继续扩展通用测试工程。本需求业务验收后、最终交付前，必须彻底清除专项临时DG实例、测试库、日志和运行残留；本任务新增的独立套件纳入卸载，不误卸载既有共享依赖。范围及完成条件见[LLD §18.11](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-suspend-confirmed-facts-low-level-design-v1.md#s1-test-cleanup-and-install-boundary)。当前使用的SQLite属于既有Miniconda Python依赖，I01/I02没有安装SQLite；没有已确认的专项独立SQLite套件可卸载。后续管理员再次确认清理要求并独立批准最小权限修订和复验，结果见§18.12；清理尚未执行。

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

最初“出技术方案”仅授权文档；随后用户已批准S0、S1开发与隔离测试，以及仅暂停`silver_suspend_d_update_job_sensor`的维护安排。2026-09-08用户要求“提交，并继续推进S2”，已提交S1并完成指定staging候选/计划/报告和正式输入只读比较；S2批准本身不包含正式发布。其后“提交，然后推进S3”批准单文件发布；首次失败停止后，管理员回复“确认，马上修正”，已据此修正最小OS规则并成功重试。事件登记仍另行确认。服务重载、恢复sensor或删除未获本轮批准，提交也不等于上线。原维护/框架实验见[LLD §15](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-suspend-confirmed-facts-low-level-design-v1.md#s1-dagster-gate)，历史事故及隔离修订保留于§17–18；S1总对账见§18.27、S2结果见[§18.28](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-suspend-confirmed-facts-low-level-design-v1.md#s2-real-candidate-reconciliation)、当前停止点见[§18.29D](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-suspend-confirmed-facts-low-level-design-v1.md#s3-confirmed-file-publication)。历史记录不覆盖当前状态，后续通过也不抹去此前失败。

## 2. 为什么选择这条路

| 选择 | 主要问题 | 结论 |
| --- | --- | --- |
| 修正回写 Tushare Raw | Raw 重抓会整分区替换，必须额外保护修正，破坏源镜像语义 | 不采用 |
| 只保留现有 Silver，删除修正来源 | 历史 Silver 重新生成时会丢失无法从 Raw 推导的事实；读取旧输出续算又会形成自依赖 | 不采用 |
| 把 CSV 改名为 JSON、Python 常量或未登记 Parquet | 仍然是代码旁边的隐性输入，归属、版本和依赖没有解决 | 不采用 |
| 固定事实作为正式上游，统一生成 Silver | 新增一个小型数据资产及其完整性检查，保持 Raw 与业务消费边界 | 采用 |

这批事实没有出现在原始输入中，必须有独立、持久的载体。目标不是“完全不读文件”——本地数据湖本身就是 Parquet——而是取消未登记、未校验、依赖进程缓存的旁路文件。

## 3. 首次设计时的事实与证据

### 3.1 首次设计基线的运行方式

本节保留首次设计基线`b324ec48`与S0审计的来源事实，用于说明为什么重构；不是S1结束后的现行调用链。当前源码已移除日常CSV读取，固定事实尚未正式发布，现状以文首及LLD §18.27为准。

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
| 资源 | 复用LakeRootResource及统一DuckDB连接；默认配置不变。仅专项CLI按LLD §8.2A使用显式受限初始化策略，无新数据库/env或运营开关 |
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
2. 固定文件先做物理头信息inspection，再按schema/行数决定是否解码，校验和合并复用本连接TEMP TABLE；不保留跨进程cache。头信息查询与行解码分别计数，不能笼统声称只打开一次文件。
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

checks绑定固定AssetKey、无日期分区、不套每日freshness；与readiness和发布共用纯合同。schema只由物理五列决定：0行/少行/多行而schema正确时，字段检查仍可通过，content必须失败；超过批准行数不解码以算hash。缺文件/损坏/资源超限/漂移作为明确的前置或IO失败，不混成schema错误。LLD §4.1已规定inspection、loader、唯一schema比较和各分支；现有草稿共同loader过早拒绝行数的实现须重构，不能改expected掩盖。

S1 隔离实测：Dagster 1.13.18 的 `AssetCheckResult` 在日期 job 内自动按 job 日期查固定发布，因此两个检查虽通过，却缺少无分区发布的原生 target，不能满足 readiness。**不降低关联要求。**已批准仅在两个固定检查的 adapter 显式产出关联真实发布的原生 `AssetCheckEvaluation` 和依赖完成输出，保持 ERROR blocking；不做日常 runless 补录，不改 SDK。框架可行性样例5项是历史证据；实际adapter、writer/readiness、实际job与原生存储读回均已通过S1隔离回归（LLD §18.19–18.27）。设计见LLD §15.3，不能将小样本当作生产数据验收。

两个新 checks 的文件前置核验采用只读路径/普通文件检查，取消现有部分实现中会写探针的健康 helper 调用；不改其他资产共用的健康函数、Lake/DuckDB 默认配置。Dagster 正常 check event 仍保留。测试必须先证明进程级文件隔离覆盖原生 DuckDB/SQLite IO，再验证实际 check，不以网络 mock 或任意失败充数，详见 LLD §18。

最终Silver保留原checks。现有Silver分区检查只核对任务日期，而Raw行内日期检查不在Silver-only job selection中；因此新writer须在已加载Raw关系上明确拒绝NULL/非目标日期，不能靠sensor保证，也不能过滤错行后继续写。该窄输入校验不改Raw数据、字段或check名称。合并公式仍由独立expected及S2等价对账证明，日常checks不重算全历史。

每日writer还须绑定同一输入版本：身份→SQL加载→身份→物理hash→身份，提升前再复核身份/hash。checkpoint保存Raw和固定文件的物理身份/hash、批准逻辑身份、候选/目标前态及结果统计。续跑先识别已提交，再决定能否继续提交；已提交但当前输入漂移时保留文件并失败，不能重复覆盖或声称当前ready。具体优先级和故障注入见LLD §5/§13。

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
| `defs/duckdb_sql.py` | Raw标准化、14条时段修正及旧全日补充 | 修改全日输入；标准化/时段修正保留，错日期不静默过滤 |
| `defs/duckdb_connection.py` | 统一连接及默认temp目录初始化 | 已提交`d59b7980`：CLI显式existing_no_spill策略；默认managed、默认值及其他调用方保持；本轮文件CLI复用不再改连接 |
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
| `src/orchestrator/defs/stock_suspend_confirmed_contract.py` | 唯一批准身份、inspection/loader和字段/内容分类；调用方统一新签名；不复制31条明细 |
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

回归集合还包括当前 `test_stock_daily_raw_checks.py`、`test_stock_daily_raw_repair.py`、`test_stock_daily_freshness_guard.py`、`test_stk_mins_silver_m5b_contracts.py`、`test_stk_mins_silver_m5e_job_contracts.py`、`test_stk_mins_lake_readiness.py`、`test_stk_mins_silver_m6_history.py`、`test_stk_mins_silver_replace_from_raw.py`、`test_stk_mins_bse_history_recovery.py`、`test_stk_mins_silver_strict_audit.py`，以及相关日常连续性/增量 check 治理测试。LLD §10.4已逐文件列出资源矩阵，并纳入test_duckdb_connection.py：覆盖资源注入、直接统一连接别名、测试裸连接和collection期副作用。原S1全部测试经同一受限runner执行，不只保护两份新测试；只能修fixture，不删除分钟回归或改业务expected。连接合同suite保留真实默认/受限分支验收，不用替身自证。

## 9. 迁移与切换：先具备新输入，再退出旧输入

### S0：冻结来源与实现合同——低风险，只读/文档

1. 刷新 CSV、两个覆盖键、正式 SSE 开市日集合及目标 Raw/Silver 指纹。
2. 从版本固定的 CSV 与正式日历一次性展开 4,022 个键；不从最终 Silver 反推全部历史事实。
3. 只把两个既有覆盖键标为 `replace_confirmed`，剩余为 `add_missing`；确认无额外范围、重复或缺失。
4. 与现有 Silver 对账，并单列“保留现有效果”和“独立业务真实性”两类结论。
5. LLD 已获认可：固定逻辑哈希编码、函数边界、CLI 参数、事件接口、字段/metadata 登记、隔离验证方案见配套文档。来源或结果不符时停止，不擅自更新批准哈希。

2026-09-06 S0 完成：上述输入已刷新，真实逻辑哈希已回填，4,022 键的现有 Silver 效果全部通过；两层各 3,083 文件，无非开市日分区、错放日期或输入漂移。S0 时工作区被正式 code location 直接加载、两个停牌 sensor 均 RUNNING，因此提出 S1 开发前先批准维护安排。明细见 S0 清单；本阶段不创建候选或执行新 helper 全范围对账。后续批准与暂停事实见 S1，不覆盖 S0 历史快照。

### S1：隔离实现与测试——中风险，已完成；正式迁移待S2

1. 原模型D06关联失败与探针越权的历史记录保留。I01–I08完成后管理员已要求继续；LLD §18.19按白名单落实合同分类、两个新checks及受限测试，59例C/D通过。无正式数据/实例访问，不改共享健康函数、SDK或业务字段。
2. 已完成writer与唯一公开SQL接口同轮切换，已提交`4887cfac`、未推送，不保留旧签名/CSV回退；58例实际临时writer及42例SQL回归通过，见LLD §18.21。prepared/committed先按文件事实续跑，输入漂移不得覆盖，等价目标不重写；Raw和最终四列合同不变。job/check/readiness/sensor集成、受限连接、五CLI及全部消费者/治理回归均已通过；[LLD §18.27](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-suspend-confirmed-facts-low-level-design-v1.md#s1-total-reconciliation)给出S1总对账。下一步为S2真实候选、生产C01/C05与全范围等价，须独立授权；S1完成不等于正式发布。

   集成前曾发现三个原最终Silver检查缺少日期声明，而替身测试显式设置了日期，未覆盖真实定义差异。管理员了解两类资产的区别后要求继续，已仅给三个日频检查绑定现有`cn_a_stock_trade_days`；检查业务判断、四列数据、Raw与新固定事实无分区语义不变。job一writer五checks、正确日期归属、真实发布关联及专用readiness/sensor接入已在隔离环境通过。审计经过见[LLD §18.22](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-suspend-confirmed-facts-low-level-design-v1.md#s1-daily-check-partition-audit)，53例＋5subtests及实际逐文件落点见[LLD §18.23](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-suspend-confirmed-facts-low-level-design-v1.md#s1-confirmed-integration-acceptance)。上述实现、消费者与治理回归均已完成，不再列为待拍板。

   2026-09-07实施澄清：先只读核验路径，再优先恢复已有checkpoint；不得让后来丢失的Raw挡住已提交文件的认定。当前writer不调用健康canary、不读instance；checkpoint严格两阶段、内部JSON上界1MiB，冻结实际统计和时段元数据。首次非等价写入输入hash各4轮、reuse各2轮，额外字节IO已计入LLD §12，不改日常连接默认。临时故障注入＋新连接续跑通过，不等于正式进程中断/完整job验收；没有新建DG实例/数据库、安装套件、改正式数据或恢复sensor。具体文件矩阵、100例有效集合及14处最终清理登记见[LLD §18.21](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-suspend-confirmed-facts-low-level-design-v1.md#s1-confirmed-writer-acceptance)。旧历史小轮状态仍保留为证据，当前状态以本文文首及该节为准。
3. 本阶段只允许临时虚构数据测试，不准备真实迁移候选。实际候选放在 `/Volumes/datasource/data_lake_staging/stock_suspend_confirmed/run_id=<批准的运行标识>/`，按 LLD §11 归 S2 的独立 staging 授权，不将 S1 开发批准当写入批准。
4. 一次性 CSV 展开脚本仅用于后续获准的迁移准备，存放在审计临时区，不注册进 Definitions、不成为日常依赖。长期发布 CLI 只接收经过校验的 Parquet 候选，不提供 CSV 回退模式。

维护历史记录：2026-09-06 17:47:27（北京时间）仅停牌 Silver sensor 变为 STOPPED；88 个 sensor 中其他 87 个状态不变，Raw 仍 RUNNING，暂停前后无活动 run。该维护步骤本身无业务源码修改、正式文件/事件写入、删除、服务重载或提交；不代表后续事故没有越权写入。维护期间不手工启动停牌 Silver job；S1 结束不自动恢复入口。

### S2：全范围等价验证——已完成，中风险，仅staging写入

先取得真实staging准备授权，生成候选并用未修改的生产合同完成C01（真实4,022行通过）与C05（等计数换键/扩大覆盖范围必须拒绝）；反例只改内存TEMP TABLE，不改候选/批准常量，不复制正式Raw/Silver。随后冻结候选与plan；有staging写入，不以“只读”之名隐含授权。S1最多32行的synthetic样本不计这两项；生产合同未通过禁止发布。后续对正式Raw/Silver的比较保持只读：

1. 验证全部 1,857 个受影响日期，而不只抽两只股票。
2. 按年度或有界日期批，读取所选 Raw 与当前 Silver，以新合并 helper 得出候选关系；最终四列进行双向 `EXCEPT ALL`，必须零差异。
3. 对其余已有日期亦完成范围内新旧关系对账，证明不新增停牌、不改变盘中停牌/复牌。以 S0 文件清单为上限；新增日期须显式刷新清单，不递归扫描其他湖目录。
4. 固定事实每批只加载一次；不能循环 1,857 次调用正式 asset、sensor 或逐日 Dagster 深审计。
5. 新合并结果与当前正确 Silver 等价时，**不为了迁移重新覆盖全部历史 Silver**。只记录等价审计，不伪造新的历史 materialization。
6. 独立字面金样本测试证明算法；物理对账证明迁移等价。两者不能用同一 helper 生成 expected 后自证。
7. CSV 原逻辑按日期区间判断，新固定集合按开市日展开；若现有非交易日文件也受到原规则影响，必须列差异并停止，不能默认两者等价。批读还需核对行内日期与文件分区，避免跨分区错放在总集合比较中抵消。

2026-09-08实际执行：operation_id=`s2_20260908_d43bed1a`，仅1个5,615字节候选及冻结plan/比较/来源证据/汇总，共5文件2,372,026字节。真实4,022行批准内容通过；同计数换键和扩大覆盖键两个内存反例均被未修改的生产validator拒绝，候选未改动。S0的6,166输入及来源/日历前后无漂移；13年度覆盖全部3,083配对日期（含1,226无修正日），Raw386,240行，新输出/当前Silver各390,259行，四列双向EXCEPT ALL零差异。

完整执行9,333ms，其中compare4,101ms；连接512MB/2线程/0spill，进程峰值RSS约558MiB，后者包含Python/框架，不等于DuckDB内存限额。Raw目录新出现`2026-09-07`，按S0冻结边界仅登记、不解码、不纳入本次比较；Silver该日尚未生成，留后续日更验收。正式固定目标仍不存在，正式文件/事件/实例/job/sensor写入及安装均0。详见[LLD §18.28（含精确hash与证据）](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-suspend-confirmed-facts-low-level-design-v1.md#s2-real-candidate-reconciliation)。S2通过只满足申请S3的前置，不自动发布或删除。

### S3：固定事实发布与登记——高风险，文件侧完成、事件待批准

正式数据写入目标仅一个：§4.1 的固定事实 Parquet；Raw 写入数为 0，历史最终 Silver 批量写入数为 0。

1. 用户审查候选来源、逻辑哈希、唯一目标、磁盘和占用检查、预期事件清单后，批准文件发布。
2. 确认挂载正确、目标不指向其他目录、候选与目标同文件系统、无其他发布者。
3. 目标缺失：完整校验候选后 `os.replace()` 原子提升；目标等价：复用；目标不等价：停止，禁止自动覆盖或删除。
4. 发布后重新读回，保存本 run checkpoint。中断后以正式文件事实为准：文件正确而 checkpoint 未记下，补记完成；文件不符或缺失且候选丢失，保留现场人工处理。
5. 文件确认后，另行批准外部资产事件登记：本版本首次人工登记最多 1 条 materialization + 2 条通过的 check 事件，不限制日常 job 的正常 check evaluations。已有完整匹配记录不重复写；LLD §9 规定确定性 token、逐条 pending/confirmed 和真实事件身份读回。API 超时或 pending 但无法确认结果时停止人工核验，不能盲目重发，也不承诺事件 API 自带唯一键事务。
6. 事件写入失败不得撤回或删除已正确发布的文件；先报告“文件已发布、观测未完整”，经批准补齐事件。不能把事件失败当成重新写文件的理由。

2026-09-08首次执行记录：先提交S2文档`47ae5404`，不改生产代码；真实CLI只读预览通过（2.908秒），一次文件发布返回`PermissionError`（退出6、2.107秒）。原因是新增OS白名单用`[0-9a-f]{32}`匹配checkpoint临时名，未被系统按预期匹配；当时仅创建目标两级父目录，未创建checkpoint或提升候选。候选及6,166个既有Raw/Silver文件全身份/hash未变；03:17:02指定Silver sensor仍STOPPED、Raw仍RUNNING、活动run为空，没有事件登记。

后续管理员确认后，已将临时OS策略中的量词展开为32个显式字符类，保持路径和长度范围；此前`/private/tmp`的1字节验证已证明正确32位名可写、33位名仍被拒绝。**03:38:28一次重试发布成功，03:38:36独立读回通过：正式固定文件4,022行、5,615字节，物理hash及inode与原候选一致，checkpoint=committed，6,166个既有Raw/Silver文件不变。** 预览3.135秒、apply3.672秒、inspect0.978秒；没有提高资源、修改业务代码或冻结plan/hash。事件登记未执行，指定Silver sensor仍STOPPED。原失败证据与本次报告均保留，详见[LLD §18.29D](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-suspend-confirmed-facts-low-level-design-v1.md#s3-confirmed-file-publication)。下一步先做事件只读审计、确认拟登记清单，事件写入另行批准；S3整体不能标完成，禁止据此恢复sensor或删除CSV。

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
| SQL / DuckDB | 纯SQL、统一连接；日常默认不变，专项CLI显式禁目录初始化/禁spill/禁自动扩展。记录metadata查询、行解码、hash字节读取，不做逐日Dagster调用 |
| 日常新增读取 | 生成器读固定事实 1 次；两个固定 checks 各最多 1 次；sensor 有候选时每 tick 1 次固定事实校验，不按日期重复 |
| 日常事件读取 | 固定资产最多 1 次有界 materialization 查询、2 次有界 check 查询，整 tick 复用；不读取全部历史 |
| 内存 / spill | 固定4,022行新增关系预期远低于512MiB；日常默认16GB/4threads等保持。专项CLI强制0spill，内存不足明确停止；测试分阶段预算见LLD §10.4/§18，不缩小业务fixture迎合32行限制 |
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
| 统一连接内部temp_policy | LLD §8.2A：managed默认保持，existing_no_spill仅专项CLI显式选择；唯一入口定义，非env/持久配置/运营参数；默认合同与受限分支分别测试 |
| 其他资源/前端设置 | 不新增、不修改 |

CLI 精确参数、默认只读行为和退出码已在 LLD §8 固定，均为未实现接口：`inspect`、`compare`、`publish-file`、`audit-events`、`register-events`。文件发布与事件登记分开确认；未确认分支同样只读。LLD §8.2A已按命令列清连接/实例初始化：help/参数错误无资源，文件命令无instance，事件命令先核定实例；只读全链不得mkdir/写checkpoint/发event/初始化存储。受限连接只核验既有temp目录，不创建，不自动扩展，不spill；显式save-report才可写批准报告。不改stk_mins CLI。

以上是目标行为，不是SDK构造已验证零副作用；正式事件CLI前仍须完成构造期副作用与实例身份验收，缺依据时不能先连正式实例试跑。

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
| 固定输入身份 | S2用未修改的生产validator完成C01/C05，31范围、4,022键/29代码/1,857日期及覆盖键一致；S1合成通过不代替此项 |
| 迁移等价 | 全部批准日期范围新结果与当前正确 Silver 双向 `EXCEPT ALL` 为零；既有其他日期不变 |
| Raw 重抓场景 | 隔离测试用原源镜像替换 Raw 后重建 Silver，历史修正仍存在；正式验收不为此重抓 Raw |
| Silver 重建场景 | 隔离测试删除临时 Silver 后能用 Raw＋固定事实重建，不读旧输出；不删除正式 Silver 做试验 |
| 补缺 / 覆盖 | 缺失补齐、正确不重添、两个明确覆盖、未批准冲突失败、正常交易日不误标 |
| 边界保持 | 14 条时段清洗保持；盘中停牌、复牌不被全日化；既有合法空分区仍合法 |
| 非法输入 | 文件缺失、错误 schema、重复键、错误内容哈希、未知模式、越界候选路径均失败且无正式写入 |
| 测试隔离 | I组先行；§10.4全部suite覆盖资源/直接连接/裸连接/collection；实际路径、实例与原生IO拒绝有证据；不以任意失败/skip/改expected通过 |
| Dagster 集成 | AssetSpec 被发现并纳管、固定 checks 正确绑定、无日更 freshness、失败阻断下游、日常不写固定资产 |
| 绕过 sensor | 手动 job / 直接生成路径不能在固定输入缺失或错误时产出正式文件 |
| 中断与复用 | 已提升但未记committed可确认；输入变化不重复提升；冻结输入指纹与统计，字段缺失/现场不明即停；事件失败不撤回正确文件 |
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

当前状态（2026-09-08）：S1开发及计划隔离回归、S2真实候选/生产集合及全范围比较均已完成，逐项见LLD §18.27–18.28。S3首次失败经确认修正后，已成功原子发布一个固定事实文件，见[LLD §18.29D](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-suspend-confirmed-facts-low-level-design-v1.md#s3-confirmed-file-publication)；事件、S4本地切换和S5删除/最终清理未完成。此前暂停指定sensor及正式健康探针越权写入的记录保留于§17。业务代码未改，6,166个既有Raw/Silver文件未变；本轮仅修改临时执行策略/审计日志名并同步原文档，未提交、安装或推送。

本轮文档验证：仓库文档完整性检查通过；另核本文 15 个本地链接及显式锚点、§7 的 27 个现有文件路径，均存在；已跟踪差异和新文档的空白/差异检查通过。这些检查只证明文档引用与格式，不代表新资产、合并算法或正式迁移已验收。

2026-09-06 LLD 细化补充：已形成配套 LLD 并同步上述接口/顺序边界；业务代码、正式/候选文件、Dagster 状态仍未改变。原文档验证数字是技术方案首轮记录，不代表 LLD 或新代码的验收结果。

2026-09-06 S0 补充：用户已认可方案并授权 S0，已完成真实只读核验和部署边界确认；未写业务代码、正式/候选文件或 Dagster 状态。S0 结果及方法单独落清单，不覆盖以上两轮文档验证的历史记录。

2026-09-06 S1 补充：用户已批准开发与维护安排，指定 Silver sensor 已暂停；原模型隔离测试 7 过 1 失败，窄修正机制实验 5 过。业务实现因 LLD 与 SDK 关联行为冲突暂停；维护状态、源码根因、测试范围与证据均落 LLD §15，不将临时机制实验冒充业务验收。

后续确认与实际偏离：用户已批准 LLD §15.3，已开始固定合同/AssetSpec/check/catalog代码。首次测试误用资源参数，回落到正式 Lake 并触发现有健康检查的探针写入/删除；该动作未经批准，不能再声称实际“正式环境零写入”。已停止并只读核实探针目录无残留，未进入停牌writer或正式事件发布；完整范围、证据限制和修复建议落在LLD §17。纯合同测试通过不代表整体S1验收。

前序启动阻塞记录（2026-09-06）：§18安全方案曾提交，用户随后要求继续推进。2026-09-06 23:10:38（北京时间）首次 I01 能力预检启动返回134；系统诊断显示 Python 在加载阶段 SIGABRT，没有进入虚构文件用例，哨兵前后内容和身份相同。已按门禁停止，没有放宽策略或降级重试，I02–I08 及 C/D 未运行。命令、策略、证据和后续修订门见 [LLD §18.7](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-suspend-confirmed-facts-low-level-design-v1.md#s1-isolation-capability-blocked)。先只读定位必要启动依赖与实际拒绝原因，最小修订策略交管理员确认，再从 I01 重新验收；不能把启动失败推断为系统隔离机制不可用。原字段、合并规则和其他业务范围不变；S2–S5 仍按阶段批准。Silver 自动入口未自行恢复，本次没有业务源码修改、正式资源操作、提交或推送。

2026-09-07文档修订：用户要求先按六项代码审计结论修正LLD。本轮同步资源覆盖、只读初始化、Raw行内日期、生产C01/C05阶段、输入指纹/续跑及schema/content分工；明细和待验证条件统一见[LLD §14.1](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-suspend-confirmed-facts-low-level-design-v1.md#audit-fixes-20260907)。只改文档，没有修业务代码、重跑隔离/业务测试、操作正式数据/事件/调度或提交。下一实施步骤仍先解决并验证隔离启动条件，不能直接进入adapter。

2026-09-07提交后继续诊断：上段文档随后按用户要求提交为 `a0361fc4`。本轮只读比对崩溃记录与相同UUID的本机系统加载器，确认 `boot_boot + 228` 对应只读打开根目录失败的分支，不再停留在笼统的“dyld崩溃”。仅建议为测试策略增加 `(allow file-read* (literal "/"))`，不是允许读取整个文件系统；禁止 `subpath "/"`，并增加根目录FD访问虚构禁止文件的反例。具体边界、可能可见的根目录信息、证据限制和单次预检门禁见[LLD §18.8](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-suspend-confirmed-facts-low-level-design-v1.md#s1-isolation-startup-diagnosis)。该读取例外按原LLD要求等待管理员确认，尚未执行；也不能承诺它已经覆盖全部后续启动依赖。本轮没有修改业务源码、现有隔离策略或正式资源，未提交/推送。

2026-09-07 15:50 获批执行：管理员回复“同意。继续吧”后，在全新虚构目录只执行一次I01，策略仅追加根目录对象的精确读取例外。解释器正常启动，正向操作通过，11类禁止操作均返回权限拒绝，哨兵前后不变，耗时121毫秒。原启动阻塞已经通过实测修正；此结果不是DuckDB/SQLite、网络、pytest或实际资源隔离通过。报告、哈希、预算及下一步I02范围见[LLD §18.9](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-suspend-confirmed-facts-low-level-design-v1.md#s1-isolation-i01-passed)。本轮没有改业务代码、运行业务测试或操作正式资源；未提交/推送。

2026-09-07 16:10 I02执行：管理员要求继续I02后，先固定两行虚构样本、四批共31组正反例、完整argv及预算，再在新临时根沿用I01权限启动。CPython 3.13.5/SQLite 3.50.2/DuckDB 1.5.2真实导入成功，但prepare首次SQLite连接失败，170毫秒退出；未生成数据库或Parquet，父进程未复制样本，后三批未运行，禁止哨兵身份/内容不变。只读系统日志和实际SQLite动态库确认：逐级路径检查被 `/private` 的 `file-read-metadata` 拒绝。本次暴露的是测试隔离策略的目录属性权限缺口，不是停牌业务方案或正式数据损坏。最小建议仅补 `/private`、`/private/tmp`、`/tmp` 和下次精确临时根的元数据读取，必须确认后再复验I01/I02，不自行放开目录内容/写入/网络。证据、状态和审批边界见[LLD §18.10](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-suspend-confirmed-facts-low-level-design-v1.md#s1-isolation-i02-native-io)。本轮没有继续业务代码、实际checks、writer或正式资源操作；没有提交/推送/删除。

2026-09-07 16:36获批复验：先重读AGENTS，按上述四个literal只增加目录属性权限，在全新虚构根复验I01并重跑I02，未改用例断言或增加其它权限。I01正向与11项拒绝通过；I02两行样本准备、原生10组、SQLite12组、DuckDB9组全部通过，I02约1.1秒，禁止区和原始样本前后不变，临时根236KiB。未安装依赖、创建新DG实例、导入业务模块或访问正式数据。结果及精确报告见[LLD §18.12](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-suspend-confirmed-facts-low-level-design-v1.md#s1-isolation-parent-metadata-retest)。只收口本次I01/I02，I03–I08和业务验收不自动计通过；本任务新增安装项完成后卸载，临时运行产物按§18.11清理，当前未执行清理/提交/推送。

`0f2bbbf9`提交后的I03增量（前两次执行记录）：仅新增专项runner/support/隔离测试三文件，不改共享资源和业务链路。当时八例均未执行；第一次pytest误将`/dev`作为测试根，已通过显式rootdir/confcutdir修正且没有增加权限；第二次收集检查`tests/__init__.py`被拒绝，按门禁停止。基于当前pytest源码提出“忽略非显式兄弟项＋只读空tests包标记＋精确检查项目根包标记不存在”的最小修订，提出时尚未实施，详见[LLD §18.13 C](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-suspend-confirmed-facts-low-level-design-v1.md#s1-isolation-i03-real-resource)。两次禁止哨兵均不变，无新DG实例/数据库/依赖安装或正式操作；增量未提交。

2026-09-07 17:05获批复验：只落实上述两个精确读取例外及固定ignore-glob，启动前核验包标记内容/不存在性；策略差异严格对账，八例断言未改。全新根中OS自检七项拒绝及正向通过，I03实际收集并完成8/8，反例文件操作和健康探针调用均为0；整体1.108秒，禁止哨兵前后不变，现场52KiB。四条既有Dagster/Pydantic弃用警告保留，未安装依赖或改共享库。没有创建DG实例/数据库、正式读写或恢复sensor。证据与源码哈希见LLD §18.13 D；只收口I03，下一个隔离项为I04，I04–I08和业务验收仍待后续完成。结果同步原方案及索引，未提交/推送；临时产物最终按§18.11清理。

2026-09-07 17:27 I04：I03增量已按指令提交为`ff72d48f`，本轮在相同权限下补齐测试输入的只读前置检查。I04八例及I03八例回归一次通过，整批1.214秒；缺根/文件、错误类型、`..`和文件/父目录链接均准确拒绝，零补建/探针/内容读取，虚构样本前后不变。只改三份测试文件和方案/索引，不改实际checks/合同或正式资源，不创建DG实例/数据库、不安装依赖；具体方案、原因及证据见[LLD §18.14](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-suspend-confirmed-facts-low-level-design-v1.md#s1-isolation-i04-input-paths)。现场92KiB纳入最终清理；I05–I08和实际adapter/业务验收未完成，下一步为I05。本轮未提交、未推送。

2026-09-07 18:03 I05：I04六文件先提交为`c8ab3bb4`，未推送。测试工厂新增显式临时DuckDB资源，六项设置实际读回一致才交给调用方；仅在受限测试子进程提前拒绝共享正式默认连接，不改生产配置。固定两批一次通过：I03–I04为16/16、1.234秒；I05为14/14、0.923秒。设置错误6例在yield前准确失败并关闭连接，参数错误3例及正式入口4例均在路径IO/原生连接前拒绝；无spill文件，禁止哨兵不变，权限与I04逐字等价（仅随机根不同）。危险开关反例为明确标记的读回故障，不实际开放扩展安装或spill。保留8条既有依赖弃用警告，不升级环境。详见[LLD §18.15实施矩阵与实测证据](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-suspend-confirmed-facts-low-level-design-v1.md#s1-isolation-i05-duckdb-settings)。只改三份测试文件和本文/LLD/索引，无新DG实例、SQLite库、依赖安装或正式操作；两个临时根92KiB/60KiB纳入最终清理。I06–I08、实际adapter和业务验收未完成；下一步仅I06，本轮不自动启动。I05增量未提交、未推送。

2026-09-07 18:59 I06：先按指令提交I05六文件为`73de21f1`，未推送，再补齐临时实例与网络隔离。I06为16/16、1.692秒，原16+14例分批回归也一次通过。真实临时实例三类存储连接路径均读回正确；1条synthetic事件在关闭重开后仍恰好1条、相同storage_id和metadata，job run为0。错误参数/配置5例、默认发现4例在副作用前拒绝；Python网络4例拒绝，原生TCP/Unix连接2例均EPERM，父进程同端点前后可达且最终关闭监听。权限和源码白名单与I05等价，没有放宽重试。详见[LLD §18.16实施矩阵、报告与清理路径](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-suspend-confirmed-facts-low-level-design-v1.md#s1-isolation-i06-instance-network)。仅改三份测试文件和本文/LLD/索引，未改业务源码或正式资源，未安装依赖、新建DG服务或恢复sensor。三处现场92KiB/60KiB/492KiB纳入最终清理，含本次临时实例4个SQLite文件共428KiB，不是安装SQLite套件。I06增量未提交；下一步I07，I07–I08、实际adapter及业务验收仍未完成。

2026-09-07 19:20 I07：I06六文件已按指令提交为`99e73ccf`，未推送。本轮启动参数5项、独立受限子进程10项均按预期通过，I07合计4.103秒；原46例回归也一次通过。错误参数在创建目录/进程前拒绝，保护缺失/晚加载、错误策略/哈希、自检失败均准确拒绝；导入期越界为真实EPERM且测试体未执行。故意skip/xfail即使pytest退出0，正常资源验收仍失败；虚构旧成功标记同样不能放行。有效profile与I06逐字等价（仅随机根不同），无放宽权限或重试。实施和逐项证据见[LLD §18.17](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-suspend-confirmed-facts-low-level-design-v1.md#s1-isolation-i07-startup-collection)。只改runner/support两个测试支持文件及本文/LLD/索引，不改业务源码；I07现场共592KiB，没有新实例/数据库。I06回归的临时实例已关闭，4个SQLite文件共428KiB，仅1条虚构事件；本轮14处精确根统一纳入§18.11最终清理，无安装项、正式操作或sensor恢复。下一步仅I08共享健康helper的临时副作用识别验证，本轮不自动启动；实际adapter和S1业务验收仍未完成。I07增量未提交、未推送。

2026-09-07 19:39 I08：先按指令提交I07五文件为`8bf5a54b`，未推送。I08三例一次通过，受限子进程0.868秒；原46例及I07十五项回归也通过。只读正例无写入，两个真实健康helper反例各记录2次mkdir调用、1次62字节canary写入、1次同内容读回和1次删除。首次场景确实新增两级健康目录；已有目录场景最终文件相同，却仍被准确识别为有写入副作用。共享函数未替换、正式源码与默认值未改，权限保持I07原样。I08现场84KiB，无数据库或实例；本轮15处精确根（含I06回归实例）按§18.11最终清理，不安装依赖、不操作正式资源或恢复sensor。结果、逐文件计划对账和阶段状态见[LLD §18.18](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-suspend-confirmed-facts-low-level-design-v1.md#s1-isolation-i08-health-side-effects)。本轮只改runner、isolation测试及本文/LLD/索引，I08增量未提交。I组分项证据已齐，按原计划在此报告并等待独立review；通过后下一步才是合同分类、两个新checks取消探针及C/D小样本，不能跳到正式数据发布。

2026-09-07 20:25实际adapter收口：按管理员“提交吧。继续推进”先提交I08为`79476407`，再完成合同inspection/加载分工、两个checks去探针/异常分类以及测试保护改造。最终34个合同用例＋25个检查集成用例通过，隔离回归46＋15＋3项通过；真实target、零探针、失败阻断和临时湖不变均有读回证据。期间修正启动器跟随pytest链接统计的错误，以及测试将下游SDK查询混入固定检查预算的错误，未通过记录保留，不扩权限/预算。详细改法、代码/测试对账、资源证据和44处临时清理清单见[LLD §18.19](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-suspend-confirmed-facts-low-level-design-v1.md#s1-confirmed-check-adapter-acceptance)。只增加精确源码读取，无正式操作、安装套件或服务启动；现行CLI/CSV及共享资源未改。本轮增量未提交，下一步纯SQL合并与金样本；完整S1和S2仍未完成。
