# DG 股票周线备用源 Raw 补齐：代码级 LLD v1

日期：2026-10-03，Asia/Shanghai。状态：M0 开发前核验已收口；M1 纯合同／规划器已完成。M2 capture、M3候选与提升恢复已完成开发及隔离验收；M4 definitions及受限单周手动交付已完成开发和隔离验收；M5两主源物理bootstrap与M6五只备用源补齐已完成；M7退市推广与身份核验已完成物理验收；M8事件补录及写后验收已于2026-10-04完成；M9自动更新仍待推进。技术方案见 [方案 v1](dagster-stock-weekly-alternate-source-raw-backfill-plan-v1.md)。本文不是实施授权或“开发门禁全部通过”的证明。

## 1. 范围、依据和硬口径

第一阶段完成 Prod 未复权、复权两套周线 Raw 的 bootstrap 和更新机制开发；备用 `weekly` 保持独立 Raw，用于未复权历史补齐。第二阶段在周线验收后完成两套月线的 bootstrap 和更新机制开发。三源不混写。Silver/Gold/Serving、自行复权重建、Prod 回补不附带实施。本文已有历史捕获、提升、恢复设计；更新任务触发、源 readiness、修订策略、完整性能预算及验收尚需细化，不能将本次范围修订表述成这些设计已完成。

Raw 只对齐 Tushare 源字段，明确排除 Prod 的 `api_name/fetched_at/raw_payload` 等采集信息。Prod bootstrap 复制 `freq='week'` 的全部历史业务记录及全部源行情列，不以在市、日线存在或 2010 起点过滤。备用及完整性审计起点改为当前 Prod 周线的最早日期：M0 分别核验两表 week/month 四组 MIN(trade_date)，同频度以较早日期形成审计下界，冻结原值与快照时间；2026-10-03 M0 已核验：两套 week 最早均为 2010-01-01，两套 month 最早均为 2010-01-31；周线最晚 2026-09-25，月线最晚 2026-09-30，见 [边界 CSV](../../../reports/stock_week_month_m0_prod_bounds_20261003.csv)。源请求向首周期周一／周日展开，不截断首周。旧审计数字按本次 Prod 快照重算；2010–2026 是 17 个年份。真实数量、预算及样本限制见 §18。2026-10-02 所在周暂不补，不限制以后新增周线。月线另写专项 LLD，沿用 2020 年 2 月只使用 28 日的决定。

| 硬口径 | 代码落点（拟新增） | 必需正／反例 |
|---|---|---|
| Prod 不写入、全量源业务记录保留 | `prod_db/stock_weekly.py` 白名单与 readonly transaction | 两源退市／空值／异常日期保留；写 SQL 被拒绝 |
| 三源独立，备用不填复权 | schema、path、`StockWeeklySource`、writer | 备用无 qfq/hfq；跨源目标拒绝 |
| Raw 原始代码、日期、单位不改 | source adapters、显式投影 | 节假日周四仍写原日期；不得统一为周五或转换 vol |
| 当前周不进入备用补齐 | `plan_weekly_source_units`、manifest | 2026-09-25 纳入，2026-10-02 排除；跨年首周正确 |
| 读取有界、每 unit 持久化 | source capture、export chunks、checkpoint | 不累积全集；取消后已完成捕获可读回 |
| 候选先完整校验，再原子提升 | `io/stock_weekly_raw.py`、promoter | 子集合并保留其他代码；冲突／坏文件不得提升 |
| 不改全局资源和既有资产行为 | 局部预算与新模型登记 | 全局 DuckDB defaults 不变；旧 job selection 不扩写 |
| coverage 不是每日 freshness | `bootstrap/stock_weekly_coverage.py` | 非开市星期五可作周期键；无交易周不要求非空 |
| 文件与事件分阶段 | history CLI / event CLI | 文件未通过不能写绿 check；事件失败不回滚文件 |

使用 [DG 接入模板](../templates/dagster-dataset-onboarding-template.html) §3、§4A、§7/7A、§8–§18，[性能治理](dagster-data-pipeline-performance-governance.md)、[Schema Contract](dagster-asset-schema-contract-design.md)、根及两个 Lake AGENTS、`CODING_STANDARDS.md`。本文用 §17 逐项对账模板，不另造模板事实源。

## 2. 当前代码与实测基线

本轮用 CodeGraph `codegraph_explore` 核验 metadata builders、catalog、partition、资源及调用方；未覆盖的具体 schema、配置、job 和事件代码再按路径读当前实现。以下事实不是拟新增代码：

| 当前文件／符号 | 已核实语义 | 本次处理 |
|---|---|---|
| `defs/catalog/lake_assets.py` | `LakeAssetCatalogEntry` 注册源、schema/path/partition/check/write/event/performance；不是生成器 | 新增 3 entries，不让运行时 asset 依赖 catalog 生成 |
| `defs/partitions.py` | 股票日线使用 `cn_a_stock_trade_days` 等 DynamicPartitionsDefinition | 新增专属自然周分区，不扩展旧交易日集合 |
| `defs/resources.py` | Tushare 显式 fields；零列响应抛错；Prod rollback-only 只读事务 | 复用，不改所有消费者 |
| `defs/tushare_api_io.py::_fetch_all_pages` | 全部分页累积内存，目标旁 `.tmp` 写入 | 新周线不使用该历史批量写入链 |
| `defs/tushare_request_policy.py` | `BoundedCodePageRequestSession.execute_pages(..., consume_page, retain_rows=False)` 可流式消费，但没有取消参数和单调用硬截止 | 复用策略类型／错误语义；周线专用 supervisor 补取消和调用边界，不改共享 runner |
| `defs/duckdb_connection.py` | 可显式传 `DuckDBConnectionSettings`；默认 16GB、4 threads、512GB spill | 通过现有工厂传局部设置；不改 globals 或共享 DuckDBResource |
| `definitions.py` | `load_from_defs_folder` 发现 definitions | 新模块导入不访问网络、Lake、instance，不做初始化写入 |
| `bootstrap/daily_basic_events.py` | register 与 report-events 分阶段；check 绑定目标 materialization storage identity | 借鉴接口行为；不 import 私有 daily-basic 函数作为周线主实现 |
| `assets/stock_identity_map.py` | 历史 `source_ts_code → latest_ts_code`，`valid_from/valid_to` 与 confidence | 只读消费，不自动补 seed 或改 Raw 代码 |
| `defs/duckdb_sql.py` | 股票日线 Silver 最早日期常量 2014-01-01 | 2010–2013 覆盖不能只用当前 Silver 日线证明 |

现有环境只做 package discovery：Dagster 1.13.18，duckdb/pandas/psycopg2/tushare 可用，pyarrow 不可用。已读本地 `dg check defs --help`；它会用 instance 加载定义，所以本轮只运行 help，不执行正式 check defs。不使用 uv 隐式同步或安装。

Prod 只读证据：[字段及索引 CSV](../../../reports/stock_week_lld_prod_catalog_20261003.csv)，42 行（40 列定义＋2 个索引），system catalog 查询最多 100 行、15 秒 timeout、BEGIN READ ONLY/ROLLBACK。两表都只有 `(ts_code,trade_date,freq)` B-tree 主键索引。故历史导出按代码批次＋年份走现有索引，不做年份×无代码约束的反复整表扫描。

历史源和单位证据沿用 [备用源区间／字段实测](../../../reports/stock_week_alternate_contract_probe_20261003.json)、[重叠样本](../../../reports/stock_week_alternate_overlap_probe_20261003.json)、[5 只退市源报告](../../../reports/stock_week_delisted_source_assessment_20261002.md)。这里不把其 3,132 个覆盖键当作全体股票可补证明。

官方依据：[资产定义](https://docs.dagster.io/guides/build/assets/defining-assets)、[分区示例](https://docs.dagster.io/examples/full-pipelines/etl-pipeline/partition-asset)、[资源](https://docs.dagster.io/guides/build/external-resources)、[分区 check 版本说明](https://docs.dagster.io/about/changelog)、[并发](https://docs.dagster.io/guides/operate/managing-concurrency)。部分页面直读因工具重定向不可用，相关能力结合官方搜索内容与本机 1.13.18 API 源码核验；不能以此代替隔离执行测试。

## 3. 资产卡、登记与分区

下列名称是最终合同。M1 已实现 schema/path/分区对象及纯合同/planner；asset/job/config 等执行定义仍待 M4/M9；不额外创造同义名字。

| 字段 | 主源未复权 | 主源复权 | 备用源 |
|---|---|---|---|
| asset key | `raw_tushare_stk_period_bar_week` | `raw_tushare_stk_period_bar_adj_week` | `raw_tushare_weekly` |
| dataset_id / 中文名 | `stk_period_bar_week` / 股票周线原始行情 | `stk_period_bar_adj_week` / 股票周线原始复权行情 | `weekly` / 股票周线备用源原始行情 |
| source_api | `stk_weekly_monthly` | `stk_week_month_adj` | `weekly` |
| data_contract | `tushare_stk_period_bar_week` | `tushare_stk_period_bar_adj_week` | `tushare_weekly_source_mirror` |
| source_doc | doc_id 336 | doc_id 365 | doc_id 144 |
| bootstrap_sources | PROD_DB_READONLY | PROD_DB_READONLY | TUSHARE_API |
| ingestion_sources | PROD_DB_READONLY, TUSHARE_API | 同左 | TUSHARE_API |
| default_daily_ingestion_source | TUSHARE_API（只描述主源，尚无自动触发） | 同左 | None（历史补齐，不每日维护） |
| schema | `RAW_STK_PERIOD_BAR_WEEK_SCHEMA`，13 列 | `RAW_STK_PERIOD_BAR_ADJ_WEEK_SCHEMA`，21 列 | `RAW_TUSHARE_WEEKLY_SCHEMA`，11 列 |
| path helper | `raw_stk_period_bar_week_path` | `raw_stk_period_bar_adj_week_path` | `raw_tushare_weekly_path` |

三者共同登记：`AssetLayer.RAW`、`DataDomain.QUOTE_DATA`、`group_name='quote'`、`SourceSystem.TUSHARE`、`DataContractSource.TUSHARE_RAW_CONTRACT`、`WritePolicy.PARTITION_FILE_ATOMIC_REPLACE`、`EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL`。performance 使用 DuckDB SQL；Python 只允许有界源响应／传输批次转换，不允许逐行落库。Prod 是运输来源，不能把资产原始源身份错误写为“当前全量来自 Tushare API”。materialization 区分 delivery_method=`prod_bootstrap|tushare_weekly_history|tushare_week_point`。

新增 `cn_a_stock_week_ends = dg.DynamicPartitionsDefinition(name='cn_a_stock_week_ends')`；不是交易日，星期五休市仍合法。目录和 UI partition key 为 `YYYY-MM-DD`，对应 ISO 周的星期五。dynamic partition 只在独立获准 register 阶段登记，不在只读计划、asset 导入或源读取中注册。

Catalog 新增 `PartitionModelFamily.NATURAL_WEEK_PARTITION`，3 个 `PartitionModel` 值：`week_end_partition_raw_stk_period_bar_week`、`week_end_partition_raw_stk_period_bar_adj_week`、`week_end_partition_raw_tushare_weekly`。对应 Definition 的 family 为新自然周族、dimension=`week_end`、physical_layout=`PARTITION_FILE`、layer RAW；不修改旧 enum 值或 family 的含义。所有 enum consumers（catalog indexing、治理测试、分区策略断言）均补新增分支，不能用 trade_date 假装兼容。

正式路径保持方案：`/Volumes/datasource/data_lake/raw/tushare/{stk_period_bar_week|stk_period_bar_adj_week|weekly}/week_end={key}/part-000.parquet`，模板必须由 paths helper＋`lake_path_template` 派生。staging 使用 `/Volumes/datasource/data_lake_staging/stock_weekly_raw/plan_hash={hash}/attempt_id={id}/`；spill、capture、candidate、audit、checkpoint 都在该 run-scoped 根下。正式根不放 staging 或运行账本。

## 4. 字段与转换：逐列开发契约

只有 schema constants 定义字段、顺序、DuckDB 类型、中文说明；请求 fields、显式 CAST 和 checks 从其派生。代码不导入 Prod ORM 作为 DG 运行时依赖；下面的 DB 模型／真实 catalog 是设计证据。`end_date` 与 `trade_date` 的 Raw 类型均为 VARCHAR，不能因 Prod 为 DATE 就写成 Raw DATE。

### 4.1 主源未复权，严格按 13 列顺序

| 字段 | Prod 类型／可空 | Raw 类型 | 转换及用途 |
|---|---|---|---|
| ts_code | varchar / NO | VARCHAR | 原值，业务 key，禁止 upper/trim 改写 |
| trade_date | date / NO | VARCHAR | SQL `to_char(...,'YYYYMMDD')`；源日期，业务 key |
| end_date | date / YES | VARCHAR | 同格式，NULL 保留；不是分区依据，不判断末交易日时盲用它 |
| freq | varchar / NO | VARCHAR | 原值 `week`；key 与源频度验证 |
| open | numeric(18,4) / YES | DECIMAL(18,4) | 原值；不算复权 |
| high | numeric(18,4) / YES | DECIMAL(18,4) | 原值 |
| low | numeric(18,4) / YES | DECIMAL(18,4) | 原值 |
| close | numeric(18,4) / YES | DECIMAL(18,4) | 原值 |
| pre_close | numeric(18,4) / YES | DECIMAL(18,4) | 原值；不从上一记录填 NULL |
| vol | numeric(20,4) / YES | DECIMAL(20,4) | 保留主源单位，不乘 100 |
| amount | numeric(20,4) / YES | DECIMAL(20,4) | 保留主源单位，不乘 1000 |
| change | numeric(18,4) / YES | DECIMAL(18,4) | 保留源字段名，不改 change_amount |
| pct_chg | numeric(10,4) / YES | DECIMAL(10,4) | 保留源值，不乘／除 100 |

### 4.2 主源复权，严格按 21 列顺序

顺序为 `ts_code,trade_date,end_date,freq,open,high,low,close,pre_close,open_qfq,high_qfq,low_qfq,close_qfq,open_hfq,high_hfq,low_hfq,close_hfq,vol,amount,change,pct_chg`。共同列完全沿用上表类型／可空规则。

| 专属列 | Prod 类型／可空 | Raw 类型 | 处理 |
|---|---|---|---|
| open_qfq | numeric(18,4) / YES | DECIMAL(18,4) | 源前复权原值 |
| high_qfq | numeric(18,4) / YES | DECIMAL(18,4) | 同上 |
| low_qfq | numeric(18,4) / YES | DECIMAL(18,4) | 同上 |
| close_qfq | numeric(18,4) / YES | DECIMAL(18,4) | 同上 |
| open_hfq | numeric(18,4) / YES | DECIMAL(18,4) | 源后复权原值 |
| high_hfq | numeric(18,4) / YES | DECIMAL(18,4) | 同上 |
| low_hfq | numeric(18,4) / YES | DECIMAL(18,4) | 同上 |
| close_hfq | numeric(18,4) / YES | DECIMAL(18,4) | 同上 |

这里的 `pre_close` 按 doc 365 是除权后的参考昨收，其涨跌幅不能与 doc 336 视为完全相同业务公式。NULL 价格保留且报告，不能因质量警告删除 Prod 原始行。

### 4.3 备用源 11 列

顺序为 `ts_code,trade_date,close,open,high,low,pre_close,change,pct_chg,vol,amount`。前两列 VARCHAR／必填；其余全部 DOUBLE，源字段原名、原值、原单位。close/open/high/low/vol/amount 必须可解析、非 NULL／非 NaN／非 infinity；备用 vol/amount 为负时按方案阻止候选提升，原响应保留 staging；pre_close/change/pct_chg 可空。不填 freq/end_date/qfq/hfq。该空值／负值策略不同于保留 Prod 历史空值，不能拿备用检查删除主源记录；源异常响应完整保留 staging，单位与源价格异常不悄悄清洗。

数值 Decimal 的源真实响应若多于 4 位小数或者超范围：Prod export 必须精确可逆；新增 Tushare 主源适配先验证源→规范小数串→Decimal 的舍入规则。尚未批准舍入时应 `decimal_precision_loss` 阻断该 unit，不静默 CAST 后宣称完全一致。FLOAT 只在备用原镜像使用；主源 bootstrap 不经 float 中转。

### 4.4 Prod 技术列白名单决策

| 列 | 类型 | 不进入源行情 Parquet 的原因 | 保留的审计证据 |
|---|---|---|---|
| api_name | varchar | Prod 采集管道标签，已由资产固定 source_api 表达；不是行情字段 | M0 聚合分布；若异常源名则阻止冻结并核查 |
| fetched_at | timestamptz | Prod 每行采集时间，不是行情周期日期 | bootstrap 单元源读取时间、快照边界及技术时间范围 |
| raw_payload | text nullable | Prod 采集原响应副本，不是已声明 13/21 源字段 | schema 白名单和源投影哈希；管理员已明确不包含；源字段投影之外不复制 Prod 原采集副本 |

不新增技术 ID，当前两表均没有自增 ID。所有投影与排除写入 manifest。任何管理员要求“保留全部物理列”时，必须先回到方案明确扩展 schema 与体积预算，而不是本 LLD 隐式多加列。

## 5. 文件／模块划分及接口

所有签名是拟实现合同，不是当前 API；新 CLI 与 typed config 不影响现有入口。每模块控制职责，禁止一个 helper 同时拉全市场历史、提升、补事件、生成 Silver。

源 enum 固定为 `PRIMARY_UNADJUSTED='primary_unadjusted'`、`PRIMARY_ADJUSTED='primary_adjusted'`、`ALTERNATE_WEEKLY='weekly'`；交付途径另外记录，不能把同一资产的 Prod bootstrap 与 Tushare 新增误建成两张主源资产。核心配置骨架如下，代码实现必须补 §9 的 source-specific validation：

```python
class StockWeeklyRawConfig(dg.Config):
    write_mode: Literal['create_or_identical'] = 'create_or_identical'
    code_list_path: str | None = None  # 仅备用手动job使用，受控冻结清单

# decorator骨架：key来自函数名；每个source独立显式定义，不用catalog生成
@dg.asset(
    partitions_def=cn_a_stock_week_ends,
    group_name='quote',
    tags=build_asset_tags(layer=AssetLayer.RAW, data_domain=DataDomain.QUOTE_DATA),
    metadata=build_asset_definition_metadata(
        dataset_id='weekly', source_system=SourceSystem.TUSHARE,
        data_contract='tushare_weekly_source_mirror',
        column_schema=RAW_TUSHARE_WEEKLY_SCHEMA,
        path_template=lake_path_template(raw_tushare_weekly_path(
            PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY)),
        source_api='weekly', source_category_path='股票数据/行情数据',
        source_doc='docs/sources/tushare/股票数据/行情数据/0144_周线行情.md',
    ),
    description='保留Tushare备用周线原始值，周分区为自然周五，源日期及单位不改；按批准代码范围补齐历史。',
)
def raw_tushare_weekly(context: dg.AssetExecutionContext,
                      config: StockWeeklyRawConfig,
                      lake_root: LakeRootResource,
                      tushare: TushareResource) -> dg.MaterializeResult:
    ...  # 校验范围→受控capture→build/audit/promote一个周→正式metadata
```

与单周 asset 不同，历史 CLI 不循环调用 asset 来生成874个run；按source unit捕获与年度批次分区写入。以上骨架仅定义未来接口，没有在本轮注册或执行。

| 文件（相对 `orchestrator/src/orchestrator/`） | 新增／修改 | 实现内容与主要消费者 |
|---|---|---|
| `defs/run_contracts/stock_weekly.py` | 新增 | source enum、keys/check names、typed budget、unit/result dataclasses、scope validation；adapters/planner/writer 共用 |
| `defs/run_contracts/asset_column_schemas.py` | 修改 | 三份 schema；所有 fields/type projection 从 schema 派生 |
| `defs/run_contracts/configs.py` | 修改 | `StockWeeklyRawConfig`，手动单周输入，不暴露源字段／分页 |
| `defs/catalog/name_mapping.py` | 修改 | 3 个 dataset_id 中文名；metadata 自动生成 |
| `defs/catalog/lake_assets.py` | 修改 | 3 entries、3 partition models、新 family；不生成资产 |
| `defs/partitions.py`、`defs/paths.py` | 修改 | 专属动态周分区、3 path helpers；旧调用方行为不变 |
| `defs/stock_weekly_planner.py` | 新增 | 日期／对象范围、年度 source units、bootstrap code batches、预算估算；纯函数 |
| `defs/prod_db/stock_weekly.py` | 新增 | index-aware metadata inspect、readonly source stream、expected daily week stream |
| `defs/stock_weekly_source.py` | 新增 | bounded Tushare page capture、成功空响应／失败区分、单调用 supervisor |
| `defs/io/stock_weekly_raw.py` | 新增 | 显式类型 projection、DuckDB source relation、merge/audit/hash/atomic promote |
| `defs/assets/stock_weekly.py` | 新增 | 3 个独立 `@dg.asset`；每次只写本来源一个周分区 |
| `defs/checks/stock_weekly_checks.py` | 新增 | 实际资产对象绑定，显式同一 partitions_def，blocking/WARN |
| `defs/jobs/stock_weekly_update.py` | 新增 | 3 个 raw-only 手动 update jobs，互不扩大 selection |
| `defs/bootstrap/stock_weekly_history.py` | 新增 | freeze/capture/build/audit/promote/resume，不访问 instance |
| `defs/bootstrap/stock_weekly_coverage.py` | 新增 | expected vs 两个未复权 Raw 的向量化集合审计，复权另报 |
| `defs/bootstrap/stock_weekly_events.py` | 新增 | instance event dry-run/register/report/audit，不写 Lake |
| `defs/bootstrap/stock_weekly_history_cli.py`、`stock_weekly_events_cli.py` | 新增 | 显式 stage、默认 dry-run；输出中文结论及机器 reason_code |
| `tests/test_stock_weekly_*.py` | 新增 | §16 定向测试；不替换历史门禁 |

```python
# stock_weekly_planner.py：无 IO；代码排序和 unit identity 均确定性
normalize_week_key(value: str) -> str  # ISO YYYY-MM-DD，必须周五
source_date_week_key(value: str) -> str  # 源 YYYYMMDD 转所属 ISO 周五
plan_weekly_source_units(scope: WeeklyHistoryScope) -> tuple[WeeklySourceUnit, ...]
plan_prod_source_units(scope: ProdWeeklyScope) -> tuple[ProdWeeklyUnit, ...]

# prod_db/stock_weekly.py：脚本唯一入口、每unit一只读快照
PsqlWeeklyExporter.export(unit, budget, attempt, cancel, progress,
                         remaining_rows) -> tuple[Path, dict]
load_prod_weekly_csv(connection, path, unit, evidence) -> int

# source capture 成功即留下可读 evidence；失败也不触碰正式文件
capture_weekly_source_unit(unit: WeeklySourceUnit, *, worker: WeeklySourceWorker,
                          capture_root: Path, budget: WeeklyBudget,
                          cancel: CancelProbe) -> SourceUnitReceipt

# io/stock_weekly_raw.py：依赖显式 connection，受控目录
build_weekly_partition_candidates(connection, *, source, unit_receipts,
                                 frozen_targets, output_root) -> CandidateManifest
audit_weekly_candidates(connection, manifest, *, source_evidence) -> AuditReceipt
promote_weekly_candidates(manifest, audit, *, checkpoint, cancel) -> PromoteReceipt
audit_weekly_formal(connection, manifest, checkpoint) -> FormalAuditReceipt

# events.py 不拉数据、不改文件；apply 和物理 promote 分开
plan_weekly_events(instance, formal_audit, budget) -> EventPlan
apply_weekly_events(instance, event_plan, *, stage, apply: bool,
                    cancel: CancelProbe) -> EventReceipt
```

`WeeklySourceUnit`：unit_id、source、ts_code、anchor_start/end、request_start/end、expected_key_ref/hash、max_rows。`ProdWeeklyUnit`：unit_id、source、sorted_codes、source_date_start/end、schema_hash、max_rows。Receipt 包括 source column names、params、counts、page/chunk paths/hash、success_empty/failed、开始／结束时间；不包含 token。

`WeeklyBudget`、`WeeklyHistoryScope` 为 frozen dataclass。日期以 ISO 表达，进入 Tushare adapter 才变为 YYYYMMDD；Prod 参数使用 date，不让 Ops/前端代拼请求。来源映射仅包含本 slice 的 3 个固定来源，不从 catalog 生成执行逻辑。

## 6. 请求规划与 Prod 导出算法

### 6.0 模板 §7/7A 源行为验证矩阵

| 输入／字段模式 | `weekly` 已有证据 | 主源两接口已有证据／M0要求 |
|---|---|---|
| 不传业务参数 | MCP声明 code/date 至少其一；真实无参SDK调用仍须核验，不能用schema校验代替源行为 | freq必填；分别核验缺freq失败，以及只传freq无对象／日期的6000截断，禁止据截断响应bootstrap |
| 只传对象 | 5退市＋000001.SZ对照历史返回，未触6000上限 | 5退市空、300114.SZ对照各726行；空响应字段完整性在正式SDK另验 |
| 时间点 | 000005.SZ/20240308默认11列；000001.SZ/20260925为空 | 主源自然周五样本有值，非周五会空；两个接口各补同一SDK验证 |
| 区间 | 000005.SZ/2020年52行显式11列；000001.SZ/2026年9月5行，源日期可为周四 | 年界、节假日与对象历史子集同key对照；主源对象＋区间日期语义仍按各接口验证 |
| 分页／满页 | MCP不提供limit/offset；首期年度路径不用未验证分页，但需对象全集对照证明无遗漏 | SDK小页limit、offset、终空页、重复页、limit6000恰好满页需真实核验，未验收不启用全市场手动维护 |
| 默认fields | 000005.SZ/20240308默认11列，1行 | 原评估已有13/21列样本，M0 SDK实际columns与顺序再次比对 |
| 显式fields | 000005.SZ/2020年11列52行 | 请求§4的13/21列，NULL/decimal/field顺序对账 |
| 关键fields | 历史样本显式ts_code/trade_date/close；11列样本包括时间与身份 | 必须显式ts_code/trade_date/end_date/freq，复权8列和pre_close同时核验，不能因一次未请求而判断缺字段 |

本地source文档：doc144 [weekly](<../../../docs/sources/tushare/股票数据/行情数据/0144_周线行情.md>)、doc336 [未复权](<../../../docs/sources/tushare/股票数据/行情数据/0336_股票周_月线行情(每日更新).md>)、doc365 [复权](<../../../docs/sources/tushare/股票数据/行情数据/0365_股票周_月线行情(复权--每日更新).md>)。M0把每次params、fields、columns、行数、边界、错误类型、SDK/依赖版本和耗时留证；原设计轮未执行表中待补请求；2026-10-03 M0 已补 SDK 的默认／显式关键字段、区间、完整小页和终空页，三接口各 52 键与对象历史子集完全一致。两个主源全市场样本各 5,557 行，后续页空；具体结果及未验证账户额度见 §18，不把局部样本当所有接口行为已保证。

### 6.1 备用源：对象年请求，按周输出

1. 读取已冻结、校验 hash 的候选 CSV／expected key Parquet，选择确认为该源可补的原始代码；5 只试点固定清单。不是全部在市池，也不是每个代码乘所有日期。
2. 按 **锚点年份**分组所需周；完整源请求边界为所选首周周一至末周周日。2010-01-01 周可包含 2009-12-28–31；不同年度窗口可重叠，不以自然年 1 月 1 日截断周期。
3. API `weekly(ts_code=one_code,start_date=...,end_date=...,fields=11_columns)`；年度有界范围最多 54 个自然周。源回应按源日期归属路由，范围内所有返回行进入 Raw，包括主源已有周；越界行不得直接提升，先报 `source_range_mismatch`。
4. 冻结锚点截止 2026-09-25，即最末源区间不超过 2026-09-27；不把 9 月 30 日记录投到排除的 10 月 2 日。
5. API MCP 未暴露 limit/offset，年窗口路径首期不依赖分页；超过 unit 最大自然周数、满 6,000 行、同代码同周多条非同值记录时 fail closed。M0 必须证明年请求同对象全历史请求的对应区间 key 相同；仅“短于上限”不足以证明完整。
6. 将成功响应字段／参数、取数时间、counts、源响应 hash、受控 page capture 原子持久化，再更新 unit receipt。空响应必须有正常字段；零列、认证失败、HTTP 异常均不记 source_unavailable。

Raw 覆盖 key 为源 `(ts_code,trade_date)`，同周两个不同源日期不在 Raw 自动合并；业务周期冲突必须作为 WARN／待决事项，不能以 DISTINCT ISO_week 静默删行。M0 年窗口上限依据该接口“一股票一周”合同；发生多日期说明合同不匹配，不能边报错边改为日线。

### 6.2 Prod：代码批次 × 年窗口、流式批次

M0 先检查 live column/PK/index 与本轮 catalog hash；一次有界 inspect 取得两表独立股票代码集合及最早／最晚源日期，不能只用日线 5,846 个代码代替 Prod 集合。只读代码清单上限 10,000；超限重新定预算，不截断。metadata inspection 只查系统目录；实际 DISTINCT/范围聚合须先 EXPLAIN 并纳入单独只读预算，不能冒充零成本目录统计。

利用实际主键前缀，每 unit 最多300个显式代码，按源日期自然年半开窗口导出；M1/M2各unit的代码与源日期范围互斥，不按周归属过滤Prod行。M3再按源日期所属ISO周五路由，跨年周可能包含来自两个自然年capture的行，必须合并完整分区。异常非周五源日期保留，Raw源日期不改。

SQL 只允许固定表 enum 和字段 schema。内部query builder保留参数模板，psql脚本对已严格校验的代码、日期和预算生成SQL字面量，不接受任意SQL或未校验的字符串；数值列投影为 `numeric::text`，日期 `to_char`，避免 psycopg2 Decimal → pandas float。示意：

```sql
SELECT ts_code, to_char(trade_date,'YYYYMMDD') AS trade_date,
       to_char(end_date,'YYYYMMDD') AS end_date, freq,
       open::text AS open, high::text AS high, low::text AS low,
       close::text AS close, pre_close::text AS pre_close,
       vol::text AS vol, amount::text AS amount,
       change::text AS change, pct_chg::text AS pct_chg
FROM raw_tushare.stk_period_bar
WHERE ts_code = ANY(%(codes)s) AND freq = 'week'
  AND trade_date >= %(source_start)s AND trade_date < %(source_end)s
ORDER BY ts_code, trade_date, freq;
```

复权适配按 §4 的 21 列显式投影，不 SELECT *。唯一数据库入口为 `bash scripts/psql-remote.sh -f <受控SQL文件> -- -qAt -w`，固定使用 `.env.web.local`；不读取或拼装 DSN，不使用 Resource 直连。每 unit 独立 psql 进程，在业务查询前建立 `REPEATABLE READ, READ ONLY`，设置本地 statement_timeout/work_mem；count、snapshot/control 与 `COPY (SELECT ...) TO STDOUT` 在同一事务，最后 ROLLBACK。control JSON 单独输出，stdout 只有 CSV。

CSV 数值仍是 SQL numeric::text，NULL 使用显式 `\N`，DuckDB 显式 VARCHAR 输入后按 schema CAST；禁止经 pandas float 中转。每 unit 最多30,000行、CSV最多64MiB；先验证 header、控制行数、只读快照、CSV完整性，再由 DuckDB 有界 relation 按最多10,000行构建 capture chunks。Python只读header和控制证据，不逐行处理业务数据。超过预算停止，不在 apply 自动放宽范围。进程组取消、文件完整性、续跑证据与配置审计以 §27 为当前执行口径；M2服务端游标描述只保留为历史记录。

每 unit 最多 45 秒；初测年度单元超过预算则在冻结计划前分割代码清单／时间窗口。query plan 必须证明使用 PK 对 bounded code/date 范围读取；不执行 force enable_seqscan=false 作为默认掩盖缺索引，也不擅自建索引。source SQL 的计数／控制聚合与导出读取次数都计入预算。

跨 unit 不共享数据库快照：manifest 写每单元时间与 snapshot evidence，不能称同一瞬间全库备份。冻结后源出现修订／新增代码时，delta audit 生成差异并要求新计划；最终“与 Prod 一致”限定为获准 capture 快照，不能拿旧哈希宣称永远等于当前库。

### 6.3 主源新增手动单周维护（后续启用）

资产运行只接受显式周分区，主源请求 `freq='week',trade_date=YYYYMMDD`。不以最新开市日代替星期五，不依赖本周默认日期。全市场分页 limit=6000、offset 单调递增，每页即落 staging；正常约 5,500 行可一页，满页必须取下一页至短页并做跨页 key 去重／重复页防护。最多 4 页／18,000 源行，超限先调整方案，不写截断数据。

每页请求及重试受 supervisor 和总体预算约束。M0 已完成代表性 limit/offset、空终页、小 page_size 和主源 Decimal 对账；实际 adapter 的完整采集、超时与恢复在 M2 验收前不能启用此路径。备用手动 asset 必须提供冻结代码列表文件，单周最多 20 代码，逐对象查询周一至周日；历史初始化不逐周启动这个 job。

## 7. DuckDB 构建、合并与候选校验

先完成一个批准来源／年度阶段的全部 source captures，再按明确文件清单做候选；20对象仅是捕获工作批次，不能每捕获20对象就重新提升整年。每来源每年度至多一遍候选构建／提升；试点和后续推广是不同批准计划，推广允许完整合并试点文件，但需单列新增计划的 rewrite bytes。Capture 与 assemble 两阶段可单独续跑，不能为降低内存而反复扫描源窗口。

通过既有 `connect_configured_duckdb(DuckDBConnectionSettings(...))`；历史 CLI 与单周 asset 的周线 adapter 使用局部 settings，底层 IO 接口只接显式 connection，连接工厂可注入隔离 tests 替身。asset 不声明一个实际上未使用的 DuckDBResource，也不新增共享 resource 或改变全局 defaults。新连接显式关闭 extension autoinstall/autoload，不安装扩展。实现时从构造到连接均使用同一 `WeeklyBudget`，不能维护两份数值。

source numeric text → 显式 Decimal CAST；备用有界响应 DataFrame → 11 列显式 DOUBLE 投影／capture Parquet，JSON receipt 只用于证据，不要求自动加载 JSON 扩展。Parquet 读取固定 `hive_partitioning=false`、`union_by_name=false`。同 schema 型 source chunks 合成一张年份 relation，SQL 派生临时 week_end；目录虚拟列不写回业务 Parquet。合并后的年份 relation 用一次 `COPY ... PARTITION_BY(week_end), WRITE_PARTITION_COLUMNS false` 向 run-scoped 目录写候选；再核验每周单文件并在 staging 规范名为 part-000.parquet。若实际引擎每周产生多 part，先在 staging 有界合并、计入额外 IO，不能把未知 part 全搬进正式目标。[DuckDB COPY 官方选项](https://duckdb.org/docs/lts/sql/statements/copy)支持该分区写入与不写目录列的语义，具体本机版本行为仍需隔离测试。整年度数据只扫描／合并一次，不能在 874 周上反复跑全历史 SELECT。

Canonical hash 在 DuckDB 内按显式字段顺序、NULL编码、原始源 key 排序生成：每行 schema固定序列化→SHA256，按 week_end 聚合排序后的 row hashes→分区 SHA256；包括 schema hash及编码版本。不得用非加密 hash 求和代替完整值对账；额外用 NULL-safe join／EXCEPT ALL验证值差集。单分区聚合受行数预算约束，禁止把全历史 string_agg 放一组或在 Python逐行序列化百万行。file SHA256 则流式读取文件字节；逻辑 hash和物理 hash职责不同，版本改变不能被误认作价格修订。

合并算法：existing_target 与新 source 分别投影相同 schema → 按源 key 做 FULL OUTER JOIN 分类 → 相同 key 同值保留一份 → 新 key 添加 → existing-only 全部保留 → 同 key 异值 fail closed。比较使用 NULL-safe `IS NOT DISTINCT FROM`，主源 Decimal 完全相等；备用同源值要求相同 canonical 数值，不用跨源单位舍入容差掩盖同源修订。

严格守恒：`candidate_rows = existing_rows + new_unique_keys`；`captured_rows = owned_rows + boundary_duplicate_rows + explicit_out_of_scope_rows`；同值重复计数另外报告，拒绝和 NULL 各有 reason/sample。bootstrap 空目标时 candidate_rows 等于全部 owned 源 key 行数。不得因为现有目标有额外行就删除它来伪造与 Prod 一致；主源已有 DG 记录冲突需另列 baseline diff 并重新确认范围。

候选 schema、业务 key、源列／行守恒、路径日期及 hash 完成全量校验后，生成 `audit.json` 签名：manifest_hash、candidate_manifest_hash、target_baseline_hash、schema_hash、source_evidence_hash。缺任一项不允许 promote。结构坏文件阻断；主源 NULL 行、源异常 OHLC／非自然周五仅 WARN 并保留，不把原始质量问题变成 bootstrap 数据丢失。

## 8. Manifest、checkpoint、并发与恢复

版本化执行产物保存 staging，不新增 metadata DB 表、summary asset 或跨 sensor readiness 账本。所有内容原子写入同目录临时文件、fsync、replace；异常旧文件不自动删除。JSON manifests 只存 unit/file 索引和预算，海量 key 清单用 Parquet／CSV引用，不把 167,097 个键塞入 cursor 或 JSON 日志。

```json
{
  "schema_version": 1,
  "plan_id": "opaque-id",
  "plan_hash": "sha256(canonical immutable fields)",
  "stage_scope": "prod_bootstrap|weekly_pilot|weekly_delisted",
  "source_scope": {"source": "weekly", "code_list_ref": "...", "code_hash": "..."},
  "anchor_range": {"start": "2010-01-01", "end": "2026-09-25"},
  "schema_hashes": {}, "budget": {}, "unit_index_ref": "...",
  "expected_key_ref": "...", "expected_key_hash": "...",
  "target_baseline_ref": "...", "source_validation_ref": "...",
  "created_at": "UTC ISO timestamp"
}
```

manifest canonical hash 排除 mutable 进度和 hash 字段自身；所有引用必须限定在获准 staging／repo evidence／正式只读路径，无 symlink、`..` 或未知根。plan immutable；变更 codes、日期、schema、预算或源策略生成新 plan_hash，不原地改旧计划。attempt_id 仅标识续跑尝试，不改变同一 frozen plan。

checkpoint 分离 source unit 和目标 file：

- unit：`pending → fetching → captured|success_empty|failed|canceled`，保存尝试计数、capture hash、参数 hash、row/page/chunk counts；捕获完成先有可读文件，后写 captured。
- file：`pending → built → audited → promoting → promoted → verified`；保存 original_target fingerprint、candidate hash、expected row count、formal readback hash、error、updated_at。
- stage：所有前置 evidence 合格才进入 audited/promote-ready；partial 必须显式报告，不能当 complete。

同一目标周文件唯一 writer。所有本 slice writer 在 `stock_weekly_raw/writer_locks/{asset}/{week}` 获得 OS advisory lock，lock 不新增正式 Raw 文件；持锁期间重查 target fingerprint→replace→读回→checkpoint。锁按 asset/week 排序，单进程单文件，进程退出释放；不得只靠 PID 文件永远阻塞。其他绕过此协议的工具不在批准 writer 集合，存在 active writer 则停止。main/alternate 目标不同可独立，但首期全局 source 调用仍单并发。

promote 只接受 audit hash＋独立 `apply=True`，需要整批准阶段候选都合格。先检查文件系统 `st_dev` 一致、候选完整、lock 和 target 基线；写 `promoting` 后再 `os.replace()`，然后 formal readback 与 checkpoint。候选和正式不同卷则 fail closed，不退化为 copy+delete。

| 中断位置 | 续跑判断／动作 |
|---|---|
| 响应未落盘 | 未完成 unit 重取；之前 captured units 不重取 |
| capture 完成、receipt 未完成 | 对有效 receipt-less capture 核对 unit/params/schema/hash；能证明才补登记，否则保留现场、重新捕获到新 attempt |
| candidate 校验未完成 | 来源已封存则重建该候选，不重新请求全年 |
| replace 前崩溃 | target 仍为 baseline，candidate hash 合格可再提升 |
| replace 后、checkpoint 前崩溃 | target hash 等于 candidate hash，补 promoted/verified；不要求候选路径仍存在 |
| target 已被其他 writer 改 | `target_changed`；不覆盖、不把目标当 baseline，重新 freeze/audit |
| 事件写失败 | 文件保持 verified，独立事件 checkpoint 继续；不回滚业务文件 |
| source 修订冲突 | 保留 captures 与差异，生成新计划；不覆盖源 Raw 历史 |

取消检查在每请求／fetch batch／候选文件／replace 前后；没有完成的步骤不得领取新 unit。Tushare 单 SDK 调用隔离到受监督子进程，硬截止初值 20 秒；父进程每秒检查取消／截止，终止并确认子进程退出后写失败，不把线程 timeout 当终止调用。token 仅继承获准环境或内存传递，不进入命令行、manifest、文件或日志。该 supervisor 仅隔离新周线请求，不改现行 TushareResource 全部调用方；若隔离验收达不到取消边界，M0 阻断。

纠错姿态：正式文件不自动回滚或删除；重建受影响完整分区候选、再审批提升。不得引入 Kopia、快照或预写备份，不默认删除 event log。保留旧 checkpoint 与 captured evidence 供对账。

## 9. Checks、依赖、手动入口与可观测

每来源三项 blocking checks：`{asset}_file_contract_check`（存在／完整／显式 schema）、`{asset}_key_partition_check`（源 key、日期解析、所属周、freq）、`{asset}_delivery_reconciliation_check`（captured 交付行数和 canonical hash 与目标一致）。可选非 blocking `{asset}_price_observation_check` 报 NULL、负成交、OHLC 异常和主源非周五日期，保留 Raw；其 WARN 不写成失败被静默吞掉。

所有 check 绑定实际 asset 对象并显式 `partitions_def=cn_a_stock_week_ends`；ERROR/ blocking 同一分区。Candidate validator 与正式 checks 使用同一纯 SQL predicate／audit evaluator，但不在生产 check 重跑业务 source fetch/merge。delivery check 使用本次有效 materialization 的 source receipt/hash、完整文件 hash和独立 source capture/control count；不能从输出自己 count 后宣布“源对账通过”。captured evidence 已丢失或 hash 不符时报告 evidence_missing，不能制造 PASS。

metadata：definition 使用 schema、dataset_id、source_api/doc/category、path_template；materialization 使用 URI、row_count、observed_columns、delivery_method、capture/plan/audit hashes、report_ref、数量和时间；check 使用 `build_check_metadata(CheckScope.RECONCILIATION,...)` 与 bounded failure_samples（最多 10 条）。hash/schema 是证据，不把稳定 column_schema/source定义每次复制进 runtime。

历史 Raw 不设置对日线的 Dagster asset deps：源行是否存在不受日线 Ready 控制，避免为覆盖审计扩大写入 selection。Code/date 范围和请求完整性在捕获／候选门禁验证；生产 Raw检查只读自身及其独立交付证据。后续 Silver 才依赖两张未复权 Raw 和 identity map，partition mapping／consumer schema 届时单独审计。

三个手动 jobs：`raw_stk_period_bar_week_update_job`、`raw_stk_period_bar_adj_week_update_job`、`raw_tushare_weekly_update_job`；selection 仅对应 asset＋对应 checks，不 upstream()/all()，不写日线/身份/另一源。`StockWeeklyRawConfig` 只接受 `write_mode='create_or_identical'`，备用另需 `code_list_path`（冻结且受控、≤20代码），主源拒绝备用过滤字段。已有正式目标同值允许幂等，异值必须离线修订计划，不加一个任意 force 开关。

两套主源更新机制必须在第一阶段交付，包含周期规划、源 readiness、分页、幂等／修订处理和定向任务。正式 sensor/schedule 的触发模型、run_key/cursor、并发隔离与取消门禁仍待补充详细设计，不能继续以“首期不适用”跳过接入模板。备用资产不增加日常自动修复。definitions reload 不启动任务；正式调度启用需按阶段授权。

运营可读 description 要写：数据代表什么、源日期与周分区区别、Raw单位、对象范围、更新会写什么及重跑边界。进度日志通过现有 `DgStdoutLogger`，每 unit 启停＋最多每 10 秒一条阶段进度；完成量来自 committed receipts，心跳不得当业务完成量。CLI stdout 展示已捕获 units/总量、已审计／已提升文件数、当前对象／窗口、最后更新时间，ETA 写“暂无法估算”直到有可靠滚动测量。

| reason_code | 中文解释／下一步 |
|---|---|
| source_empty_confirmed | 当前接口该范围成功为空；另列源不可用，不盲目补任务 |
| source_failed / source_timeout | 请求未成功，不能当无源；按剩余预算重试 |
| decimal_precision_loss | 当前 schema 无法无损保存；核验源精度，不自动舍入 |
| identity_unresolved | 旧代码身份缺证据；核验历史映射，不改 Raw |
| target_changed / source_key_conflict | 基线或源修订冲突；检查差异、冻结新计划 |
| budget_exceeded | 明确请求／扫描／内存／时间的超限项；缩小批次重新规划 |
| candidate_invalid / evidence_missing | 先看 audit report／capture receipt，不提升或补绿事件 |

## 10. 历史覆盖：完整性与可补性分开

expected：同一原始代码在该自然周有至少一条 Prod Raw 日线，则形成候选 `(source_ts_code,week_end)`；只读 PG 聚合输出去重周期键，不导出全部日线价格。2010–2013 不依赖当前 DG Silver 起点。按代码批次＋日期窗口执行，参数与最大 keys 写预算；执行前验证 daily 的真实索引，不能假设与两张周线相同。

将日线期望、主源 Raw、备用 Raw 的源日期分别转周坐标，再按历史身份 map 生效范围做等价对账；不修改 Raw key。保留两种视图：原代码物理差异和已确认 canonical 身份差异。周内身份切换时用日线真实日期／源真实日期选映射，不能仅用星期五替代所有生效日；多重／冲突映射阻断 canonical 分类，但不删除物理源事实。

DuckDB 年份 relation：expected LEFT ANTI JOIN primary UNION fallback key 集合；复权只与复权主源对账。不将 adjusted 的 pre_close/价格混入未复权路径。重叠主源优先仅用于覆盖与未来消费选择，Raw 重叠行仍保留。

输出原始键缺失、身份等价已覆盖、primary_present、fallback_recovered、source_empty_confirmed、source_failed、source_unchecked、identity_unresolved、source_contract_blocked；每 key 计数守恒，不把当前上市状态 D 当 coverage过滤。日线候选不等于源承诺。最终状态允许“未复权可补部分已闭合，已查无源／身份未决另列”，不得把 WARN或待查全部抹成零缺口。

管理员确认：退市 `weekly` 未复权补齐和后续复权历史补齐均尽力而为，不以全部历史缺口清零作为数据集交付条件。可取得且契约合格的数据完成写入／读回；已核实无源的缺口允许保留，且不得冒充完整覆盖。请求失败、超时、权限不足、身份未决、未查源与真正无数据严格分开；预算耗尽只表示本轮尝试结束，不代表不存在来源。无源不阻塞已通过验收的 bootstrap／更新机制；存在技术失败或未核验事项时必须在交付报告显式列出，不能自动按无源结案。该口径继承至后续月线设计。

coverage auditor 输出 `reports/` CSV 缺口台账，逐 `(source_ts_code, freq, period_key, adjustment_type)` 记录；adjustment_type 明确 unadjusted/qfq/hfq，不能合并成模糊“复权缺失”。列合同至少包含 source_ts_code、canonical_code（未决可空）、freq、period_key、adjustment_type、attempted_api、request_start、request_end、checked_at、response_rows、status、reason_code、evidence_ref、next_action。多接口尝试保留独立证据引用，不以最后一次结果覆盖先前证据；报告计数守恒，区间汇总保留逐周期明细链接。执行产生真实台账，本次只定义输出合同。

补充测试要求：成功空响应可以保留有证据的历史缺口；超时／权限失败不能转成 source_empty_confirmed；未复权已恢复不能同时标 qfq/hfq 已恢复；允许残余缺口时汇总仍显示真实数量；bootstrap 源目标不一致和坏文件仍阻断提升，不因尽力补齐口径放松数据质量。

Silver 仅保留后续设计接口：粒度 `(latest_ts_code,week_end)`，主源优先，保留 source_api/source_ts_code/source_trade_date，统一股／元／百分数；单位仅有有限样本证明，首期不实现、不改变当前任何日线或 Quote消费者。不得做日线聚合周 OHLC 或简单 factor 复权。

## 11. 配置审计卡与执行预算

下表是拟定局部 defaults，集中定义 `WeeklyBudget`，随 manifest 持久化；typed config、CLI、source、writer、auditor、event helper从同一对象派生，不在每个模块重新设值。预算调整产生新 plan hash，仅对新计划生效，既有 checkpoint 必须按原计划续跑。秘密配置只用现有 resource/environment，不复制到 manifest。

| 配置／参数 | 当前／拟默认 | 来源／持久化 | 消费者／依赖／生效与可见性 |
|---|---|---|---|
| TUSHARE_TOKEN | 无项目新默认 | 现有 dg.EnvVar、获准本机环境；不持久化值 | resource/worker；执行时读取；缺失仅相关源失败，导入不失败 |
| PROD_POSTGRES_* | 现有 host/port/user/password/database/sslmode；sslmode 默认 prefer，连接 timeout 10s | 现有 resource/env | Prod adapter；只读连接；日志仅来源标识，隐藏凭据 |
| lake_root/staging_root | 现有 paths.py 正式常量 | 不新增 env；plan 写受控绝对路径 | paths/writer/check；不可任意覆盖到旧湖或系统目录 |
| source_concurrency | 1 | WeeklyBudget/manifest | supervisor/CLI；跨 source 同阶段不得放大；进度报当前值 |
| minimum_interval_seconds | 1.0（工程保守间隔；账户配额已确认充足） | 同上 | 所有成功／失败请求都计间隔；共用阶段计数，不能逐 unit 重置总额 |
| max_retries / call_timeout_seconds | 2 / 20 | 同上 | supervisor；单 call 上限，3 次总尝试；取消回收子进程 |
| phase_request_cap | 由 unit×pages×3 计算并显式冻结 | manifest | source scheduler；重试计费，超限不领取新 unit |
| prod_code_batch / fetch_batch_rows | 300 / 10,000 | WeeklyBudget/manifest | planner/Prod adapter；依赖 source_rows_unit cap，不扩大常驻内存 |
| prod_statement_timeout_ms / prod_unit_seconds | 30,000 / 45 | 同上 | 每 readonly transaction SET LOCAL／supervisor；不修改数据库全局配置 |
| prod_work_mem / prod_max_connections | 32MB / 1 | 同上 | 只读 transaction；记 actual queries/connections |
| max_source_rows_per_prod_unit | 30,000 | 同上 | freeze 与 fetch guard；超限确定性缩小计划，不丢弃行 |
| max_codes / objects_per_batch | 10,000 inventory cap / 20 备用工作对象 | 同上 | inventory/planner；清单 hash 冻结，禁止静默截断 |
| duckdb_memory_limit / threads | 512MiB / 2 | 局部 DuckDBConnectionSettings 从 budget构造 | writer/audit；不改 16GB/4 的当前全局defaults |
| duckdb_max_temp / temp_directory | 2GiB / run-scoped staging/spill | 同上 | 新连接；仅 capture/build/audit 获准 staging，拒绝未知根／symlink |
| event_partition_batch / event_write_batch | 100 / 100 | 同上 | event helper；实际只读请求调用与写入数量均有 cap |
| event_record_read_cap / event_write_cap | 20,000 / 12,000 | 同上 | 当前约三源×874×(1 mat＋3 blocking)≤10,488；更早存量额外计数，超限分获批计划 |
| failure_sample_limit / progress_interval | 10 / 10秒 | 同上 | audit/check/CLI；大列表引用报告，不塞日志/cursor |

必须测试所有上限的边界与超限、同一计划预算不可变、CLI未知字段拒绝、局部 DuckDB配置真实生效、密码/token不出现在证据或日志。此卡是设计配置审计，实际 code consumers 在实施完成时反查核对，不宣称新增参数已生效。

### 性能模型及拒绝策略

| 维度 | 实测／设计模型 | 运行门禁 |
|---|---|---|
| 股票、窗口、枚举展开 | 当前未复权候选 462＝211退市＋249身份候选＋2未知；试点5；频度只 week、源3 | 身份分支不自动加入源可补池；不用对象×日历日×两频度 |
| 备用请求／行数 | M0旧候选中实际退市code/year＝2363，最多7089次尝试；矩形最坏211×17＝3587单元、10761次尝试；每unit≤54行，矩形正常返回上界193698（去重前）；试点按真实候选years冻结，不固定80 | 单并发1/s；源持续限流暂停；请求cap含重试、不每unit重置 |
| Prod 连接／SQL | `U=Σsource Σyear ceil(code_count_year/300)`；每unit1连接、1控制聚合＋1stream SELECT，SET LOCAL另记 | 例6000代码×16年×2源≤640 units、约1280业务SELECT；真实inventory和EXPLAIN决定批准值 |
| Prod传输／写入 | 两主源按13/21列流式；正常约54×300＝16200行/unit；历史价格NULL／异常不过滤 | unit row cap30000，fetch10000，任何误截断／精度损失阻止提升 |
| expected keys | 前次全市场已完成周expected 3062878，当前只是旧snapshot基准，不是导出行数 | 捕获更新expected另单独预算；分代码批次，聚合keys不搬全部daily价格 |
| 文件／原子粒度 | 2010–2026Sep25最多874分区/source，3源≤2622正式files；Prod更早周期另计；临时source_chunks按fetchbatch，不每股票生成正式文件 | 单来源单周一个part，所有源码批次先assemble再promote，避免211×874重复rewrite |
| 扫描／join | source_chunks和existing清单按年向量化；一次 FULL OUTER 合并、group audits；主源/备用覆盖每年各一次读取 | 无 sensor 全历史扫描；partition>100 禁止逐分区深readiness；记录扫描文件／字节和query数 |
| 估算空间 | 未压缩payload：行数×(数值列×16bytes或8bytes＋字符串及NULL overhead)；压缩字节来自M0真实样本，目标大小不靠固定MB阈值 | source_capture + candidates + spill2GiB + audit＋checkpoint，申请空闲空间≥测得峰值的1.5倍；不足停止，不清理他人目录 |
| 备用耗时 | `base_calls×max(1秒,测得调用延迟+worker开销)+retry/backoff+assemble/audit/promote` | 2363个实际候选year单元、每次完成后间隔1秒，间隔至少约39分钟，另计调用/worker/重试/IO；54次SDK样本调用本体0.067–0.539秒，不据此推算正式ETA |
| 执行规模 | 年份／20对象批次；初始全阶段写入行数上限12M、文件3000、源调用按上表冻结 | 更早存量或异常日期超阈值需重新拆分批准；不能开无界扫描“先看跑多久” |

source units与target files的复用必须测：失败重跑只重新获取未 captured unit；改一个code的source不能触发重新下载其他20codes；candidate失效只重建受影响target，未审计候选不补绿events。DuckDB内存超限或spill2GiB满时停止并缩批，不能提升全局资源上限绕门禁。

## 12. 事件补录：独立计划与预算

直写补录不是 Dagster backfill。先正式文件 verified，再独立只读 event dry-run。按 asset/year 和每100partition批读取 materializations/check evaluations，分页 cursor稳定且每页≤500 records；最多20,000 records，超限停止、缩小事件计划。既有events只作为观测事实，不用于全历史行情统计。

EventPlan 固定 asset keys、partition keys、file/canonical hashes、formal_audit hash、missing registrations/materializations/checks和数量；缺check不能自动扩大批准event范围。registration、materialization、blocking check 分阶段 apply，每批最多100事件，每写前核对正式指纹和最新target materialization。只补当前文件对应证据缺失项，重复执行已匹配事件跳过。

report runless materialization 后取得 storage identity；用现行 `AssetCheckEvaluationTargetMaterializationData` 绑定 check 的 target_materialization_data，写 `partition=week_key,blocking=True,severity=ERROR`。不得拿旧source快照hash给新的formal文件补绿；events修订不可默认删除旧记录。日志／run key中不使用 storage_id作为业务identity，storage_id只用于目标check关联。

新文件数F最多3×874＝2622，3 blocking checks的最坏新增事件数`E=F×4＝10488`，register最多874 keys；Prod更早存量需另测，不能漏算。WARN事实如需登记另列预算；全量深readiness不用做主验收，采用总数与5个代表周的实际 readiness 样本。event写入失败仅影响观测状态，文件不会回滚。

## 13. 拟定 CLI 与运行手册

M5当前入口如下（使用现有项目解释器；各命令均须填写实际绝对路径）：

```text
.venv/bin/python -B -m orchestrator.defs.bootstrap.stock_weekly_history_cli --inventory <frozen_inventory.json> --plan <copy_capture_plan.json> --capture-root /Volumes/datasource/data_lake_staging --target-root /Volumes/datasource/data_lake
.venv/bin/python -B -m orchestrator.defs.bootstrap.stock_weekly_history_cli --inventory <frozen_inventory.json> --plan <copy_capture_plan.json> --capture-root /Volumes/datasource/data_lake_staging --target-root /Volumes/datasource/data_lake --mode capture --apply
.venv/bin/python -B -m orchestrator.defs.bootstrap.stock_weekly_history_cli --inventory <frozen_inventory.json> --plan <copy_capture_plan.json> --capture-root /Volumes/datasource/data_lake_staging --target-root /Volumes/datasource/data_lake --mode build --year <year> --apply
.venv/bin/python -B -m orchestrator.defs.bootstrap.stock_weekly_history_cli --inventory <frozen_inventory.json> --plan <copy_capture_plan.json> --capture-root /Volumes/datasource/data_lake_staging --target-root /Volumes/datasource/data_lake --mode promote --audit <audit.json>
.venv/bin/python -B -m orchestrator.defs.bootstrap.stock_weekly_history_cli --inventory <frozen_inventory.json> --plan <copy_capture_plan.json> --capture-root /Volumes/datasource/data_lake_staging --target-root /Volumes/datasource/data_lake --mode promote --audit <audit.json> --apply
```

默认dry-run只核验冻结库存/路径并输出预算，不创建目录、不调用源、不写instance。capture/build没有apply立即拒绝；promote没有apply只预检；续跑重用相同freeze/预算/目录与命令。SIGINT/SIGTERM只设置取消意图，由各阶段检查点安全退出。CLI各执行阶段要求显式冻结plan文件，逐字段与inventory重建结果一致（包括预算），防止默认值变化隐式生成新计划。CLI校验inventory→plan一致、year在冻结范围、audit属于当前plan/roots，不能借文件参数扩大写入范围。最终formal聚合审计单独保存报告；M7 events CLI未实现，不在本轮调用。scope路径不等于授权，正式命令执行前仍列明阶段、plan hash、文件上限与恢复方式。

| 排障入口 | 看哪里 | 处理 |
|---|---|---|
| 源失败／进度停滞 | unit receipt、source supervisor日志、request/elapsed预算 | 先区分空源与失败，按剩余预算resume |
| schema／数值不匹配 | candidate audit failed_rules＋最多10样本、source capture | 修源契约，不编辑正式Parquet |
| 文件基线变化 | target fingerprint diff、writer lock、promote checkpoint | 重新freeze受影响范围 |
| 缺口仍在 | coverage分类CSV／expected evidence／identity hash | 查源可补性或代码映射，不按上市状态删除 |
| UI显示不Ready | event audit、目标materialization/check partition关联 | 文件verified后修观测，不重复拉源 |

## 14. 消费者影响与权限边界

已有共享helper不修改签名或默认行为；catalog新增不会变成runtimeplanner。现有下游Quote API、Prod DatasetDefinition/ExecutionPlan、TaskRun及调度不消费新DGRaw，首期不改它们。边界不产生 foundation→ops/biz/app 或任何→qtf反向依赖。

| 消费面 | 本次动作 | 验证 |
|---|---|---|
| definitions discovery / name mapping | 新增独立definitions、3中文名 | 隔离加载实际defs；导入无网络/目录/instance写入 |
| catalog enum/index/static gates | 新family、3entries/models | registry API / policy / schema/path/check一致性 |
| job selection | 3个定向raw jobs | exact asset+checks集合；不包含日线/identity/其他source |
| resources / DuckDB | Lake/Tushare/Prod复用注入，DuckDB复用现有受控connection factory与新局部settings | 全局defaults与48个原connection consumers不变；IO连接工厂可隔离注入 |
| Tushare resource/runner | 新source adapter不改现有函数 | 年窗口和有界pages；zero-column、timeout、取消反例 |
| paths / partitions | 新helpers＋专属dynamic集 | 旧调用path不变；不向交易日集注册星期五 |
| identity/lifecycle | 只读审计消费 | 生效期冲突、不确定身份单列，不回写seed |
| checks / historical event API | 新check对象真实partition绑定 | 实际evaluation及execution records都归属正确week |
| sensors/readiness/automation | 主源更新消费者须补审计；备用不加日常consumer | static断言不扩写all/upstream；主源触发须补去重／周期门禁测试 |
| source/date/serving consumers in src | 不改现行链 | 文档状态明确，不将拟定source字段当已上线API |

更新机制的 trigger/readiness、源修订处理及配置项尚未设计完，不允许凭当前 history-only 配置直接编码。M0 已核实 Prod 起点并校准为 17 年、退市候选2363个code/year单元；874是自然周坐标上界，两主源各857个实际源日期。账户配额已由管理员确认充足；样本通过不自动触发正式执行。

M1 已审计 schema/path/partition 的现行引用；无 active 周线资产和现行下游 consumer，active catalog/partition-model 同 M4 定义一起注册。

尚需实施后对actual新symbols和所有import/callers复查（CodeGraph impact）；这是开发验收，不是允许省略当前代码审计。任何改通用helper、新共享resource或者Silver契约的需求需先同步方案并全量消费者核验，不能借本slice顺手迁移旧链。

## 15. 开发切片、依赖和交付门禁

| 切片 | 具体开发及证据 | 进入下一阶段条件 |
|---|---|---|
| M0 来源／性能冻结 | 补年窗口边界、一致性、小页分页、主源Decimal精度及账户额度；Prod readonly EXPLAIN＋代表unit；依赖现有环境 | 真实source合同与预算合格；无缺项才进入相应adapter实现 |
| M1 纯合同／规划 | 3schemas、source scope、keys/path/分区模型、typed budget、manifest/receipt/hash | 日期／字段／配置／范围正反例通过；不注册正式分区 |
| M2 Captures | readonly Prod batches、备用worker、checkpoint/cancel、有界Pandas→DuckDB | 隔离目录源端→capture→读回等量；timeout/取消/续跑通过 |
| M3 候选／提升 | 分区完整merge、audit、lock/fingerprint/replace/recovery | 私有临时目录真实replace中断测试、同值幂等、冲突拒绝 |
| M4 DG定义集成 | assets/checks/jobs、name_mapping/catalog/metadata、分区事件隔离验收 | actualdefinitions与catalog/static gates一致；未自动触发 |
| M5 主源存量bootstrap | 先小样本，再年度代码批次，正式提升及聚合对账 | 获准计划范围正式文件与captured Prod业务投影一致 |
| M6 备用5只 | 5对象、Prod周线最早日期至获准结束周；3132旧候选仅作复核基准 | 新快照逐key闭合、源字段无误、不伪造复权、单位仍保源 |
| M7 退市推广／身份分支 | 可补对象逐批；211调查后准入，251身份候选核清才扩范围 | 分类counts守恒、failures可续跑、不可补单列 |
| M8 事件补录 | 独立event plan/dry-run/sample/batches/final audit | 每事件真实file、partition及target association一致 |

新增 M9：完成两套主源周线更新机制设计、开发和验收（源 readiness、周期日期、全市场分页、触发去重、并发、修订处理、取消／续跑、状态与业务文件隔离）。M9 是第一阶段交付条件，不能只完成 M0–M8 就转入月线。随后 M10：两套月线专项 LLD、bootstrap 和更新机制开发／验收。Silver／自行复权重建不顺带完成；任务实际启用与正式写入仍按阶段授权。每切片先列具体文件白名单、测试、真实样本和读写授权，不把“写LLD”扩成执行M5–M8。本次不提交Git或推送，提交需后续明确指令。

## 16. 测试到代码的可执行验收矩阵

| 拟定测试文件／用例 | 目标模块／输入 | 必需断言 |
|---|---|---|
| `test_stock_weekly_contract.py` | schema/keys/field sequence | 13/21/11列严格顺序、Decimal规模、Raw日期字符串；备用不能出现freq/qfq |
| `test_stock_weekly_planner.py` | 2010-01-01、2026-09-25/10-02、跨年和休市周五 | Mon/Sun源界、排除当前周、年度所有权唯一、unknown/source-unchecked不进apply |
| `test_stock_weekly_prod_source.py` | 隔离psql子进程＋300code/year | 唯一脚本入口、readonly在query前设置、每chunk≤10000、无直连/SELECT *、保NULL/退市/非周五，单位不改 |
| `test_stock_weekly_source.py` | 默认／显式／关键字段fixtures、年窗口和小页 | 零列不是空源、年度子集不截断、满页续取、重复页停止、precision_loss不提升 |
| `test_stock_weekly_source_supervisor.py` | 阻塞worker、重试、取消 | 超时子进程确实退出，取消不领新unit、cap含失败和重试、日志无token |
| `test_stock_weekly_raw_io.py` | existing+new、Decimal/NULL、坏文件 | exactkey merge、existing-only保留、源异值fail、schema漂移、无executemany逐行写入 |
| `test_stock_weekly_history.py` | unit receipts / source修订 / checkpoint | 捕获持久化在completed前、已完成unit不重拉、scope或hash篡改拒绝 |
| `test_stock_weekly_promote.py` | 临时同卷路径＋注入replace/crash | replace前后恢复、目标变化、不同st_dev、并发lock、部分成功保留、不自动删异常现场 |
| `test_stock_weekly_coverage.py` | 2010早于Silver起点、退市、身份切换、两源不同日期 | 真实expected keys、canonical歧义单列、周粒度集合闭合、adjusted独立、计数守恒 |
| `test_stock_weekly_definitions.py` | actualasset/check/job＋临时instance | explicitpartition同源、AssetCheckEvaluation.partition与execution table均正确、selection精确、typedconfig拒绝force/源分页字段 |
| `test_stock_weekly_events.py` | 独立fake/临时instance | dryrun零写、无materialization不补check、targetfile变化阻断、写失败不删文件、幂等与eventcap |
| `test_stock_weekly_performance.py` | 17年/874周规划、fakePG/SDK计数、受控样本 | O(units)源读取、O(years)聚合而非全历史×周重扫、call/SQL/scan上界、局部memory/spill生效 |

既有定向门禁：`tests/test_asset_governance_contracts.py`、`test_run_contract_static_gates.py`、`test_metadata_contracts.py`、`test_duckdb_connection.py`；新enum/path/schema/metadata分别补适用断言，不能放宽旧tests。最终测试命令在代码存在、确认隔离和依赖可用后执行，不能拿不存在文件跑一遍称通过。

真实M0/M2/M5记录至少：source_rows、owned_rows、boundary_duplicate_rows、same_value_duplicate_rows、rejected_rows/reason/sample、candidate_rows、written_rows、readback_rows、requests/pages/retries、SQL/connections、source_seconds/assemble_seconds/audit_seconds/promote_seconds、peak_RSS、spill_bytes、source/candidate/formal bytes/files、cancel/resume证据。Prod业务列精确对账；备用值镜像和候选coverage分开证明，NULL/舍入/单位不可混成一个“值一致”。

## 17. 模板 §18 对账与本轮验证

| 模板项 | LLD落点 | 当前状态 |
|---|---|---|
| §3 说明卡／层级／下游 | §1–3、§9、§14 | 设计已填写；没有现行消费者接入 |
| §4A catalog/metadata/tags/name | §3、§5、§9 | 设计已填写；registry代码待开发 |
| §6路径／§7、7A来源预算 | §4、§6–8、§11 | catalog字段索引已真实核验；M0 日期/分页/代表性能已验证；M2实际adapter与恢复待验收 |
| §8逐字段类型／过滤 | §4 | 主源live16/24列白名单已对账、投影13/21；实际Parquet精度读回待实施 |
| §9–10A definition/UI | §3、§5、§9、§13 | 中文说明／错误／日志设计已填；UI真实验收未执行 |
| §11 checks／partition事件 | §9、§12、§16 | 已指定actualchecks隔离验收；未生成事件 |
| §12 jobs／共享writer | §8–9、§14 | 3独立入口与lock，未运行job |
| §13 sensor/automation | §9、§15 M9 | 两套主源更新机制纳入第一阶段；触发／去重／cursor/run_key详细设计待补全，备用不日常自动修复 |
| §14–15 bootstrap/backfill | §6–8、§12–13 | 直写文件与runless分开；正式Lake和instance均未写 |
| §16切片／§17验收 | §15–16 | 测试矩阵、权限阶段明确；代码/真实写入/性能验收待实施 |

本轮验证：现有环境dependency discovery、dg help、Prod system catalog 42行只读核验；文档相对引用、字段计数、schema与live catalog类型对应、静态文档完整性和diff检查。没有启动definitions、运行正式job/sensor、materialize、backfill、动态分区注册或事件补录，没有写正式Lake或业务数据库，没有安装套件。

截至 M1，M0 开发前证据及纯合同／规划器已完成，详见 §19；更新机制设计仍需 M9 专项落地，不能据此声明第一阶段全部完成。后续门禁集中在实际 adapter 的精度、压力及取消／恢复验收，身份分支和全体退市源可获取性。失败时只收缩／重设对应切片，不隐式扩为全量Prod或Lake修复。


2026-10-03 复权字段复核证据：[MCP 默认／显式／补充字段及复权主接口样本](../../../reports/stock_week_adjustment_field_probe_20261003.json)。weekly 不返回请求的 qfq/hfq/adj_factor；stk_week_month_adj 同日返回两种复权四价。备用不能填复权，但复权主源 bootstrap 和更新仍是第一阶段必交付。


## 18. M0 实证、更新机制接口补充与未闭合项

依据 [M0 核验报告](../../../reports/stock_week_m0_assessment_20261003.md)、[年度规模](../../../reports/stock_week_m0_prod_scale_20261003.csv)、[源集合对账](../../../reports/stock_week_m0_source_reconciliation_20261003.json)、[性能样本](../../../reports/stock_week_m0_performance_20261003.json)、[预算](../../../reports/stock_week_m0_budget_20261003.json)。两主源当前周线共5,787,046行，各857个源日期；按每年实际代码库存、300代码批次，各源至少212个导出unit。年库存一次冻结，不在每unit重复DISTINCT全库；有失败拆分则重算unit，不伪报固定424全成功。

代表性300代码×2025年实有298代码，两源各15,346行，52个临时周文件；显式Decimal写出／读回双向差异和重复键都为零。未复权代码/日期/freq主键索引查询205.886ms。ZSTD每行约40.832/70.055字节，按现有行数外推两主源约321MB；该外推不是最终磁盘承诺。临时CSV→列式Parquet合计单源0.3221/0.1762s、进程累计RSS167.438/211.094MiB，不含正式PG cursor传输、真实Lake IO、merge/hash/promote。内存和spill压力、actual adapter端到端在M2验收；不得跳过。

### 18.1 更新模块与生命周期

第一阶段新增 `defs/stock_weekly_update.py`（纯日期/选择合同）、`defs/source_readiness/stock_weekly.py`（只读完成周期及覆盖判断）、`defs/sensors/raw_stock_weekly_update_job_sensor.py`（只编排两主源更新job）、`tests/test_stock_weekly_update.py`、`tests/test_raw_stock_weekly_update_job_sensor.py`。exact active定义、现行sensor通用helper消费者和注册方式在M4/M9接入前补专项影响面审计，不凭此草案直接复制日线sensor。

拟接口：`latest_completed_week_anchor(now, calendar, policy) -> WeekEligibility`，返回自然周五、周期窗口、截止状态与交易日依据；`plan_stock_weekly_updates(calendar, last_verified_delivery, pending_runs, budget) -> UpdatePlan` 只规划有界遗漏周期；`fetch_primary_week_pages(source, anchor, fields, budget, consume_page, cancel) -> SourceReceipt` 不在sensor重复拉源；`audit_weekly_delivery(receipt, expected_key_ref, unavailable_ledger) -> DeliveryAudit`；`plan_weekly_revision(old_fingerprint, new_capture) -> RevisionPlan` 单独处理同key异值。

采用一只独立编排sensor，周期性检查而非日线freshness。只选择两个主源job，不含备用历史job、不写上游。定义默认STOPPED，重载不启动。sensor不写Parquet、不直接调用源；新增动态周分区、RunRequest、cursor属于正式编排写入，启用前单独验收与授权。每tick先判已完成自然周期和正式交付证据，再排除queued/started运行；run_key必须复用当前 `build_asset_update_run_key(subject, unit_id)`；unit_id由source/anchor/计划版本构成，禁止自写run_key拼接或专属builder，cursor只记有界选择和观测，不以cursor成功替代物理交付。同一日同一source/week只创建一个自动意图；源调用技术失败使用现有有界重试。源未就绪保留欠账与原因，下一个每日19:30窗口可形成新的明确日更新意图；不能按tick时间戳不断变run_key生成重复任务。

每天Asia/Shanghai 19:30起才允许自动选周；触发时间与周期完成分开判断。当周自然周五已过19:30且源完成证据合格才可交付该周；休市周五不回退到最近开市日作为请求参数，仍显式trade_date=自然周五。使用正式交易日历判断周期内是否有交易日；日历缺失为calendar_unverified，不自动判整周无交易。整周确实无交易可明确跳过并记录，不能报告非空行情已完成。覆盖expected取周期内实际Raw日线键及核实身份，不要求所有在市股票每周有行，也不因Raw日线未准备就触发上游写入。历史欠账按最早未完成周期有界推进；不能仅用latest周而永久跳过长停机期间。日线证据/身份未决记原因，源无数据仍按管理员尽力补齐口径处理。

新周期 create_or_identical 支持新增键及同值幂等；同key异值、end_date或qfq/hfq快照变化生成修订差异及计划，不能自动提升为覆盖。bootstrap保留Prod原计算版本；Raw不是一份全历史实时重算的qfq序列。后续需要历史刷新时复用完整候选校验/原子提升/逐文件checkpoint，单独执行；不为新增一周自动重拉全历史。

### 18.2 更新配置审计补充（拟定，实施前校准）

新增配置集中于 typed `WeeklyUpdatePolicy`，与`WeeklyBudget`共同冻结；以下是设计默认值，尚非上线配置。不可散落在sensor/CLI/UI。沿用Tushare token和限流来源，不新增secret配置。

| 配置 | 默认／来源与持久化 | 消费者、依赖、生效、可见与门禁 |
|---|---|---|
| timezone / daily_start_time | Asia/Shanghai / 每日19:30（管理员2026-10-04确认，替代旧周五22:15草案）；typed policy→冻结plan | planner/sensor；19:30仅开放触发窗口，不保证源已就绪；19:29:59/19:30:00、非周五、时区正反例，tick读取且cursor显示 |
| tick_min_seconds | 60；同policy→sensor definition | 编排sensor；不等于每分钟下载；definition reload生效，metadata可见 |
| max_periods_per_tick / max_pending_runs | 1 / 两主源各1；同policy→plan | planner/sensor；只取最早欠账周期，阻止并发重写；bounded instance查询及故障/长停机测试 |
| update_page_limit / page_call_cap | 6000 / 每源每周期最多4页；同budget→receipt | source adapter；最后一满页仍需终空页，超cap拒绝，不能把截断当完整；计数metadata |
| request_parallelism / min_interval_seconds | 1 / 1；沿用历史budget，显式记录为“每次完成后等待” | 两源adapter共享进程额度；跨进程共享同token限流模型需M2/M9审计，不能假称全局已隔离；限流暂停 |
| default_status | STOPPED；definition | 两主源编排；新定义/重载不自动启动；启用时完成真实样本和明确运行授权 |

动态分区、正式asset readiness、queued/started run查询的exact API、读cap和故障恢复细节尚需按当前Dagster/helper做专项核验；不得声明新配置消费者已经全量审计。单位/日期实证已具备，完整更新机制设计门禁仍按§15 M9落地。

### 18.3 M0 剩余边界

账户配额由管理员确认足够，不再调查积分、每分钟/每日额度或用其阻塞开发。54次成功仍只作为接口行为样本；代码保留有界请求、超时、重试和限流错误处理。全体211退市源可用性与251身份分支在有界调查后逐批准入，不自动承诺全部可补。正式文件指纹、runless events、更新启用、中断恢复均未执行。2026-10-03 管理员确认账户配额足够，已解除此项待核实；M0 开发前核验收口。后续实际执行验收仍按阶段推进。


## 19. M0／M1 完成对账（2026-10-03）

管理员明确账户配额足够，M0 对进入 M1 的来源／范围／性能预算门禁收口；最后 Prod API标签异常聚合两行均为零。[M1 开发验收记录](../../../reports/stock_week_m1_assessment_20261003.md)列出精确改动、硬口径测试与真实只读 dry-run。

实际代码：`run_contracts/stock_weekly.py`（三源 enum、13/21/11字段类型及必填/键合同、frozen预算/scope/inventory/unit/manifest）、`stock_weekly_planner.py`（纯自然周/年度代码批次、界限拒绝、外部证据hash/plan hash、分类统计）、`asset_column_schemas.py` 三schema、`partitions.py` 独立动态周对象、`paths.py` 三路径。仅追加，不改变已有签名/默认行为。可补或已查空必须给出源证据引用和hash；未查源/失败/身份未决不生成source unit，但台账数量保留。大key明细仍在外部引用，不塞入manifest。

M1 不注册 dynamic keys、active assets/catalog entries/partition models、typed Dagster执行config、jobs/sensors/事件；这些在 M4 同步接入消费者，故不是遗漏。M1预算增加 `max_candidate_keys=250000`，防止纯计划器接收无界Python候选集合；来源为 frozen WeeklyBudget/manifest，消费者为scope验证与planner；超限拒绝、无静默截断，预算变更生成新plan hash，定向负例覆盖。schema/row NULL策略由单一source合同派生，Prod价格空值保留，备用必填字段独立。

CodeGraph `codegraph_explore` 覆盖ColumnContract/catalog模型/资源合同；`codegraph_impact(cn_a_stock_trade_days,depth=1)`仅返回分区定义，不足以证明无消费者。已补当前schema/path/partition imports、catalog active定义和OS隔离源码清单的直接引用审计；下游Prod DatasetDefinition/TaskRun/QuoteAPI不消费新合同。动态分区消费者和更新sensor的exact API/热路径在M4/M9专项验收，不能用M1结果替代。

现有OS隔离测试启动器的精确源码清单同步新增纯合同；AST直接import审计另发现现行ETF checks/writer已引用、但清单遗漏的 `etf_adj_factor_terminal_exceptions.py`，只补这一源码文件，不改该ETF实现或开放其YAML、正式Lake/instance及网络。纯代码变更未执行正式writer。治理suite通过12例/456subtests，定向和相邻回归75例通过；初始直接pytest的fixture导入失败及旧清单失败已记录，不放宽或跳过门禁。

真实M1 dry-run仅消费M0临时CSV和reports证据：两主源各298代码/15346行，分别规划一个2025代码批次；退市000005.SZ的656个已证实候选键形成15个year单位、含重试上限45次，首请求2009-12-28，单元最多53周；无网络/DB/湖/instance写入。下一阶段M2：实际readonly Prod stream、Tushare supervisor/capture、持久化checkpoint与取消/续跑，不扩为正式bootstrap执行。

## 20. M2 开工约束与执行卡（2026-10-03）

M0/M1 已提交 `114a15c6`。本轮按 §15 M2 开发：新增 `defs/prod_db/stock_weekly.py`、`defs/stock_weekly_source.py`、`defs/bootstrap/stock_weekly_capture.py`、`defs/bootstrap/stock_weekly_history.py` 及对应隔离测试。只生产 source chunks/receipt/checkpoint，不实现 M3 分区 merge/promote 或 M4 definitions；不修改共享 resource/helper 的行为。

| 硬口径 | 代码点／正反验收 |
|---|---|
| 固定两张 Prod 表、显式业务投影、源日期年度半开窗口 | prod adapter；SQL 白名单、numeric 文本、跨年及非周五保留；拒绝备用/伪造 unit |
| 同 unit 单个只读 repeatable-read 快照 | connection 在首查询前设隔离；count/control 与 named cursor 同连接；异常/取消 rollback；不使用全集 fetchall |
| 每批≤10000、unit≤30000、45秒、SQL≤30秒 | frozen budget 派生；计数超限先拒绝；fetch 前后取消／deadline，watchdog 调用 connection.cancel 终止阻塞查询 |
| 备用一代码一年窗口，≤54行，不凭失败断言空源 | supervised worker；显式11列和对象/区间；字段、代码、范围、NULL及重复周反例；完整字段成功空单列 |
| SDK每调用≤20秒，最多两次重试，阶段共享调用cap | 子进程终止并确认退出；阶段请求ledger调用前落盘，重启不归零；完成后至少间隔1秒；不记录token/异常原文 |
| captured 前必须有可读、等量、显式schema chunks | 有界DataFrame→DuckDB CAST/COPY/readback；Decimal多余非零小数拒绝，保留Prod NULL；源count与capture count一致 |
| 续跑只复用同一plan/unit/params/schema且hash一致的证据 | plan锁、独立attempt目录、原子JSON/fsync、逐chunk hash；完成receipt后checkpoint；篡改拒绝、receipt先成而checkpoint缺失可恢复 |
| 取消不领取新unit，完成单元不重新请求 | history coordinator；完成量来自可读receipt；中断/取消/续跑/幂等重放与进度测试 |
| 所有写入受控、正式环境不用于test case | 正式调用仅staging根，隔离测试仅系统临时根；拒绝正式Lake、旧湖、路径逃逸与symlink；本轮不执行正式capture |

规模沿用 M0：17年，两源共5,787,046行；代码批次300，每源预计至少212unit，单unit通常≤3chunk。备用候选211对象、2363code/year，只有已证实可补键入计划；本轮隔离样本≤54行备用／30000行Prod，source chunk总数受3000上限约束。COPY只处理当前批；整unit最终只读一次有界chunk集合做schema/key/count验证，DuckDB512MiB/2线程/2GiB spill，目录为本次capture下的spill。chunk为原子提交粒度，unit receipt封存后才算完成；失败不删除已捕获现场，只在新attempt重取未完成unit。无整年/全历史DataFrame或逐行Parquet写入。

主源按 M1 已批准的**源日期自然年半开窗口**导出全部业务行，再由 M3 按ISO周路由；§6.2旧“锚点年互斥”描述不适用于当前Prod adapter，不以周归属过滤导出行。真实远程核验继续通过管理员指定 `psql-remote.sh`；代码注入现有readonly resource不代表授权本轮直接连接正式资源。验收将已有M0真实源样本与实际capture/readback对账，网络实时行为另有M0证据，隔离测试不使用正式token。


## 21. M2 开发验收（2026-10-03）

[M2 验收报告](../../../reports/stock_week_m2_assessment_20261003.md)与[样本测量](../../../reports/stock_week_m2_capture_sample_20261003.json)记录实际结果。四个新模块实现固定源投影、repeatable-read/count/named-cursor、取消watchdog、SDK可终止子进程、阶段调用ledger、显式COPY/readback、逐chunk hash、receipt与checkpoint恢复及history进度；没有接入active Definitions或修改共享resource默认行为。

两套真实M0源数据各15346行，分别分两chunk，续跑源调用零；备用51行经监督子进程捕获；30000行容量样本分三chunk，累计进程峰值RSS305.547MiB。数据值双向EXCEPT ALL为零；这些耗时只含离线replay，不含生产传输，不作为正式同步ETA。spill未触发，不能声称强制spill压力已验收。生产网络传输与正式staging执行仍未实施，须在M5/M6批准范围补实际执行验收。

scope的`manifest.evidence_hash`是外部文件SHA256；`WeeklySourceUnit.expected_key_hash`是所选周键列表的逻辑hash，两者用途不同。执行先验证外部来源/键库存文件字节hash及受控根；unit身份/hash由frozen manifest锁定，后续M3覆盖审计仍须从外部expected证据做逐键对账，不能把capture成功当历史缺口清零。

定向/相邻回归与DuckDB OS隔离回归通过，详见验收报告命令和计数。真实子进程以exit17退出后，已完成unit保留、OS锁释放、续跑只读未完成unit；无正式Lake/instance/Prod写入。M0/M1已提交114a15c6，M2修改本轮保留工作区，未推送。下一切片M3仅候选构建／完整校验／提升恢复的开发与私有临时目录验收。

## 22. M3 开工执行卡（2026-10-03）

M2已提交`30b118ff`。M3新增`defs/io/stock_weekly_raw.py`（年度批量relation/merge/hash/audit）、`defs/bootstrap/stock_weekly_candidates.py`（捕获证据与候选清单冻结）、`defs/bootstrap/stock_weekly_promote.py`（逐文件锁/提升/checkpoint/恢复）及对应测试。M2 store仅追加只读receipt验证入口，保持resume行为不变；不改通用resource、API、definitions或现行writer。

| 必须／禁止 | 代码／正反门禁 |
|---|---|
| 先完成来源/年度全部捕获；不逐周重扫全历史 | 只选与锚点年度源窗口相交的units，缺receipt拒绝；一次年度relation筛选、merge、PARTITION_BY写出；跨年周由相邻自然年capture合并，不遗漏边界 |
| 显式schema、源日期及NULL保留 | 三源contract投影；Hive虚拟week_end不写入Parquet；非周五、合法NULL仅记录观察，不清洗 |
| 同key同值去重、existing-only保留、异值阻断 | NULL-safe SQL merge，source duplicates同值计数；异值/坏schema/重复目标/错误周/超预算正反例 |
| 年度全量校验后才形成audit证据 | candidate↔source+existing双向EXCEPT ALL、源/owned/boundary/excluded/duplicate守恒、schema/key/分区/hash；缺项不能promote |
| frozen targets及candidate/source审计hash可核验 | 三源受控路径与baseline fingerprint；plan/assembly/audit签名绑定；候选或源或目标变化拒绝，重新freeze而非force |
| 单文件同卷原子提升，不伪称组级原子 | 所有文件预检后、source/week全局advisory锁、baseline重查、promoting checkpoint、os.replace、读回、verified checkpoint；拒绝跨st_dev且不copy/delete |
| replace前后退出均能恢复，不重新拉源或删除现场 | checkpoint与实际target hash交叉判断；候选搬走后不要求原path存在；已verified幂等重放；部分成功/取消保留 |
| 路径/并发/副作用边界 | staging根与正式Lake根固定；隔离样本只在系统临时根；拒绝symlink/旧根/路径逃逸；apply=False不改目标，未接入instance |

成本沿用WeeklyBudget：每次一个来源、一个锚点年度（最多54周），最多10000代码、1200万source+existing行、3000输入/候选文件，DuckDB512MiB/2线程/2GiB spill。实际代表样本M2两主源各15346行、52周、2chunks；本轮以该捕获集及少量existing/边界/异常样本验收，候选每周单文件。阶段锁内一次目录发现，年度源和目标读为有界集合；merge/hash/audit扫描次数为固定阶段数，不按周重复年度计算。逐文件最终读回只读该周，不能替代年度全集对账。按key唯一且日期合法，每周行数再限制为max_codes×7，避免全历史string_agg无界；schema版本及NULL编码进入canonical SHA256。

候选目录采用独立assembly attempt，完成manifest/audit后才封存；失败现场保留，新attempt不覆盖旧文件。单文件replace为持久化边界，checkpoint JSON逐文件atomic/fsync。跨年bootstrap在freeze阶段必须包含与完整锚点周相交的库存year；缺少邻年capture时不得宣称该周完整。本轮不读取或写入正式Lake，不触发真实job/event；正式执行仍在M5/M6单独批准。


## 23. M3 开发验收（2026-10-03）

M2提交`30b118ff`，未推送。[M3验收报告](../../../reports/stock_week_m3_assessment_20261003.md)与[真实源样本测量](../../../reports/stock_week_m3_candidate_sample_20261003.json)记录代码、测试和边界。§22三模块及M2只读receipt入口已实现；当前API/CLI/resource/definitions无变更，M3修改留在工作区。

年度显式schema/NULL-safe合并、同值去重/异值阻断、existing-only保留、一次分区COPY、完整差集与hash校验，均由测试及实际M0值读回证明。audit签名含manifest_hash、candidate_manifest_hash、target_baseline_hash、schema_hash、source_evidence_hash；逐文件提升前核验源/候选/原目标，跨设备拒绝，checkpoint在replace前原子落盘，replace后读回再verified。真实子进程在replace前后exit23均可恢复，不重新拉源；取消保留已完成文件。未伪称整年度组级原子，也未写正式Lake或instance。

备用expected文件明确为ts_code/ISO Friday week_key的CSV或Parquet，文件hash与unit选择键逻辑hash分开校验；每unit读取最多55键用于拒绝超过54的库存，整体键数受max_candidate_keys预算限制。source-key-outcomes.parquet外部台账只区分成功完整源请求的候选键存在/缺行，失败或未查不能据此记空。全市场日线期望、历史身份、复权覆盖仍需后续coverage阶段，不以这份源台账替代。

partial_scope是隔离样本的调用参数，默认False，仅临时目录目标允许，audit明确记录；不新增env、Settings、数据库配置或运营输入，消费者仅候选构建、只读审计与测试。完整主源年度须带相交邻年已捕获unit。最早/最晚历史边界的真实空窗口证据，在M5冻结inventory时补实证，不能制造非零inventory或把缺receipt放宽为无源。

两套主源各15346行/52周文件，均保留49条业务NULL记录，重建新增key0；备用51行/51文件，4条非周五保留，冻结2键全部找到。累计RSS435.219MiB，未触发spill，不能替代全历史/强制spill验收。224项定向、相邻与静态门禁通过；最终观察计数追加后M3的24项和真实样本重跑通过。Ruff、docs、diff及CodeGraph核验详见报告。下一阶段M4仍待推进；正式执行、事件和更新编排不在M3验收范围。

## 24. M4 开工执行卡（2026-10-03）

M3提交1638d42b。按§3/5/9/15注册三份真实asset、每源三blocking checks、三个精确selection手动jobs、名称/schema/catalog/自然周partition model及typed config；自动sensor/schedule与正式注册/执行不在本轮。M4包含让上述asset可实际运行的单周source→capture→merge/audit→promote适配，不能注册空壳或用测试替身冒充正式生产链。

| 硬口径 | 落点与正反验收 |
|---|---|
| 三源独立、schema从现行13/21/11列合同派生 | stock_weekly assets及catalog/name mapping；typed schema与active definitions对账 |
| Friday动态分区，节假日合法，不引用交易日/日线/身份资产 | partitions/models/asset/check/job；临时instance注册一个Friday，验证event.partition和check execution表，非Friday拒绝 |
| 三blocking checks绑定实际asset且同一partitions_def | file/schema、key/week/freq、独立delivery receipt/hash；丢证据/篡改目标/错误周拒绝，不从输出count制造源一致 |
| 只开放create_or_identical；备用要求受控冻结≤20代码文件，主源拒绝code_list_path；未知字段/force/fields分页参数拒绝 | StockWeeklyRawConfig extra=forbid、source-specific validation；config来源是run_config并持久化run/receipt，不新增env/DB配置 |
| 主源指定Friday、freq=week、显式fields、完整分页；备用单代码Monday–Sunday | 单周source helper复用监督子进程；默认page_limit=6000、page_call_cap=4归一到独立frozen PointPolicy，最多12尝试、20秒/call、至少1秒间隔；4页仍满拒绝，≤10000行；备用≤20请求、每对象≤1行，成功空另记 |
| 原值、NULL与单位保留；已有目标不同值不能自动覆盖 | M2有界capture及M3纯SQL合并/audit/promote复用，逐页capture/receipt持久化；完整existing-only保留，但已有目标新增key也属于修改，create_or_identical阻断 |
| 导入不连网络、不创建instance/目录、不触发任务 | load_from_defs_folder/registry静态核验；现有EnvVar只在执行时解析；临时instance与临时Lake/staging验证，dg CLI单独隔离home与环境 |

配置审计：StockWeeklyRawConfig.write_mode默认create_or_identical/code_list_path默认None，来源run_config、持久化Dagster run与来源intent，消费者仅三源asset/point adapter；生效每run，UI可见，互斥规则及未知参数有反例。PointPolicy两个分页默认来自§18.2，frozen纯合同，持久化intent/receipt；消费者仅主源point请求循环，不能用于历史Prod或备用。WeeklyBudget已有超时/重试/间隔/行数/DuckDB预算保持原值；TUSHARE_TOKEN与LakeRootResource复用现行资源，未增新配置来源。

规模：每job一个source×一个week×一个文件，不展开历史；主源最多4页/12尝试，≤10000源行；备用≤20代码/≤60尝试，≤20源行。每页≤6000有界传输，捕获完成立即Parquet+receipt；SQL只读当前捕获和目标周，各阶段固定扫描数、merge/join≤70000已有行+10000新增行，每个check只读一文件+一个当期materialization及独立receipt（≤20units）。DuckDB512MiB/2线程/2GiB spill，staging仍在正式根外，单文件replace/checkpoint，retry只重取失败请求、旧capture保留。正常主源通常1–2页；异常12×20秒加间隔上限约252秒，监督回调提供进度；备用最坏60×20秒另列预算，不提供虚假ETA。空间以实际文件字节及候选测量为准，超行/page/code/file预算拒绝。已有M0/M3实际15346历史样本及M0 point行为作为规模依据；本轮再用tushareMcp小样本和隔离单周job验收，不调用正式instance或正式写湖。

## 25. M4 实现对账（2026-10-03）

§24执行卡已落地：三源名称/schema/path及自然周partition model同步注册；metadata直接调用统一构造器，config禁止force/fields/limit/offset；jobs只选择自身asset与三checks，不注册分区、不附带sensor/schedule。真实单周适配使用集中PointPolicy、受监督子进程、逐页独立capture/receipt和M3候选/提升；已有目标异值/新增key阻断。源等待进度每10秒更新；短页终止、满页继续、重复/空/跨周/超限反例均有测试。

九checks只读文件及最新同分区materialization引用的交付证据；临时instance真实evaluation.partition和execution history.partition均核验，统一check metadata/static gates通过。自然周未套入通用TRADE_DATE历史事件扫描；M7单独接入。备用成功空保留receipt，失败不归为empty；大范围缺口用离线冻结计划，不开放20代码限制以外的手动更新。

CodeGraph与直接消费者审计、配置来源/生效方式、模板7A预算/恢复、源端→捕获→候选→读回对账及验证明细见[M4验收](../../../reports/stock_week_m4_assessment_20261003.md)。218项定向/静态回归、18项OS隔离治理、完整dg check defs通过；最后config类型和请求参数断言更新后相关测试再次通过。两套真实源1行样本差异0；10000行合成容量两页、峰值RSS276.156MiB，未验证正式网络/全历史或强制spill。本轮未改变子系统依赖、Prod契约或通用连接工厂；未安装依赖，未写正式Lake/instance。M3提交1638d42b；M4修改未提交。下一步M5冻结库存及授权范围，不自动进入正式执行。

## 26. M5 开工与只读冻结（2026-10-03）

M4提交eb1a3aab，未推送。本轮M5范围为两主源Prod存量bootstrap，不附带备用源、事件/动态分区、sensor/schedule或Silver。先经psql-remote.sh在同一repeatable-read/read-only事务冻结freq=week年度代码/行数、2009–2027相邻年窗口、日期边界和快照；两源仍为2895784/2891262行、各212个300代码units，源日期2010-01-01至2026-09-25。每unit≤30000行、每fetch≤10000；各源phase≤1200万行/3000文件，DuckDB512MiB/2线程/2GiB spill。预计输出各857个周文件，压缩空间沿M0约321MB外推；staging+候选+目标和重写量实际测量，不以外推替代门禁。正式根/两个目标和staging只读预检：目标尚不存在、同设备、自由空间约2.94TB，写权限须在实际执行环境核验。

捕获传输存在待确认冲突：AGENTS.local.md只允许psql-remote.sh访问远程DB，§6.2/M2实现为readonly resource/named cursor。已向管理员列出保留入口并改有界CSV流与本次窄直连例外两种选项；未确认前不修改捕获合同、不进入正式写湖。完成只读冻结不代表M5验收通过。

独立边界修正按M3已明确的空窗口证据要求实施：当前2010首周需要2009窗口，而2009库存为0、无unit；不能伪造有数据unit或启用partial_scope。新增识别`prod_weekly_inventory`版本1的冻结JSON证据，逐项重建ProdYearInventory/ProdWeeklyScope，复算完整manifest必须与输入一致，快照必须read-only/repeatable-read；只允许其中rows=0且codes为空的自然年扩展coverage intervals。证据先通过既有受控路径和hash校验；缺格式/缺声明仍按原门禁拒绝。读取JSON上限16MiB，source/count/unit/hash不一致均阻断，正例覆盖已证实空年，反例覆盖篡改、非零年伪装空年、scope/manifest不一致和旧格式缺证据。该格式不修改WeeklyPlanManifest/receipt schema或既有plan hash算法；消费者仅候选年度边界检查与冻结脚本，未增加运营/env/数据库配置。

M5边界校验进一步绑定原始库存CSV：受控路径/hash与16MiB上限、各年代码集合及行数必须与冻结JSON一致；原始CSV同时进入候选audit evidence，不能仅靠JSON自己声明空年。87项相邻/定向回归及113项static gates通过。已形成每源300代码、2024–2026三units、41932输入/15450归属2025行的具体试点草案，以及各212units的全量草案；尚未正式捕获或提升。当前结果与传输路径待确认事项见[M5预检](../../../reports/stock_week_m5_preflight_assessment_20261003.md)，不将预检记为M5完成。

## 27. M5 捕获传输调整与执行门禁（2026-10-03）

管理员已确认保留 AGENTS.local.md 的唯一数据库入口并改用 COPY CSV。此节取代 §26 的待确认状态及 M2 的 named cursor 路径；M2历史验收不改写为新路径已验收。本轮先更新LLD、再开发和隔离验收，M5完成仍须真实捕获、正式文件读回与最终对账。

### 27.1 代码范围、合同与证据

| 硬口径 | 实现落点 | 验收与反例 |
|---|---|---|
| 只经现有脚本访问Prod；不增加DB配置或修改脚本 | `defs/prod_db/stock_weekly.py` 的 PsqlWeeklyExporter；删除原cursor adapter | argv固定脚本/固定env；模拟进程不访问正式资源；全消费者扫描无旧adapter |
| 单unit只读快照，控制数量与CSV属于同一事务 | 固定表/字段/代码/日期 SQL生成；count后COPY、ROLLBACK | 只读/隔离/快照缺失、退出非零、CSV不完整均不能封存 |
| Prod全部业务行原样保留 | 13/21字段投影，NULL标记，VARCHAR→Decimal，现有capture校验 | NULL、非周五、末尾零和超精度反例；无退市过滤、无采集字段 |
| 取消不领取新unit，已提交unit续跑不重取 | 进程组TERM→KILL及reap；capture receipt/checkpoint | 真子进程阻塞取消、超时、退出；取消后续跑、幂等、source calls为零 |
| 只有完整证据算完成 | SQL/CSV/control hash进入receipt；candidate audit继承源证据 | 任一证据篡改阻止resume/promote；失败attempt保留 |
| 有界columnar写入 | DuckDB unit relation→每chunk≤10000→CAST/COPY/readback | source/count/capture一致；不整年DataFrame、无逐行Parquet写入 |

内部协调器参数由 `prod_resource` 迁移为 `prod_exporter`，一次迁移全部代码与测试消费者，不留双轨。DataFrame chunk入口仅供备用源现有SDK使用；Prod改用同一校验逻辑的relation入口。无需新增asset/resource/check/job/sensor，也不改变业务schema、正式路径或子系统依赖。

### 27.2 子进程与文件边界

每unit在独立attempt目录保存SQL、CSV、control。SQL值只来自经校验的固定枚举、股票代码和date对象；psql元命令路径必须在受控attempt内，拒绝引号、反斜杠、换行，避免元命令或shell解释。启动参数列表而非shell拼接，stdin关闭、stderr不输出凭证，失败只记录reason code。

先写 `.pending`，每0.1秒检查取消、45秒deadline和输出字节；每10秒报告当前unit/window及进度，等待期间不能伪造完成量。取消/超时/字节超限终止整个进程组，TERM等待1秒后KILL并回收。服务器断开结束只读事务；失败不能封存receipt。exit=0后校验control≤16KiB、source_rows是非负整数且不超过unit/phase、readonly=on、isolation=repeatable read及snapshot/time非空；fsync并原子封存。CSV显式header、UTF8、NULL='\N'；quoted NULL保持字符串，空字符串不得自动成为NULL。

DuckDB显式列类型VARCHAR、strict解析，unit relation计数与source_rows一致后再写chunks；所有精度、身份、范围、重复键和Parquet读回校验沿用M2。SQL/CSV/control逐文件hash校验包含seal、resume及candidate源证据。已有已封存unit不会重取；未完成unit在新attempt整体重取，不复用半截CSV。正式提升继续使用M3的签名、目标指纹、逐文件checkpoint和同设备os.replace，无备份或快照。

### 27.3 配置审计与性能预算

新增预算仅放 `WeeklyBudget`，随冻结manifest持久化并进入plan hash，无新env/Settings/数据库配置/运营字段；修改预算必须重新freeze。消费者为Prod exporter、证据校验及对应测试，运行前显示manifest预算，修改后仅新计划生效。新增 `prod_csv_max_bytes=67108864`、`prod_control_max_bytes=16384`、`prod_process_shutdown_seconds=1`；正整数校验，超限失败，禁止自动扩大。其余沿用300代码/unit、30000行/unit、10000行/chunk、statement30秒、unit45秒、单连接、work_mem32MB、DuckDB512MiB/2线程/2GiB staging spill。

全量两源5,787,046行、424units；每unit一次COUNT/一次COPY和一只读事务，最多1272个源Parquet chunks，预计两源1714个正式周文件。unit CSV最多64MiB，当前unit DuckDB relation最多30000行；保留全部原始CSV证据，理论CSV上限424×64MiB约26.5GiB，另外Parquet/候选/正式/2GiB spill计入预检，当前2.94TB空闲可容纳。实际耗时、字节、RSS与spill必须试点记录，不把45秒×424预算上界约5.3小时当ETA。超时或超行先停止，重新冻结更小unit；不能无限重试或全历史事务。

试点为每源300代码、2024–2026三个自然年units、41932输入行，候选归属2025的15450行；这不是完整市场年度证明。试点捕获取消→续跑→完整业务列读回后才进入全量；全量年度构建仅扫描当年和相交边界capture，单源单周单文件。结束独立聚合审计源/目标文件集、schema、key、rows及双向业务值差集，并重新经脚本冻结只读库存作delta审计。不同unit快照不宣称同一瞬间全库备份。

### 27.4 阶段执行顺序与权限

先隔离验证传输与CSV→DuckDB，再重冻结全量及试点计划（旧计划未执行，不复用旧hash）。执行入口须默认dry-run，分开capture、candidate/audit、promote和resume，输出完整命令、cwd、manifest/hash、staging、正式目标、预期数量及失败恢复方式。M5只写两主源Raw，Prod始终只读，不写Dagster instance、动态分区或events；M6备用、M7事件、M9自动更新另按阶段推进。任何正式执行前核验实际主机权限与同设备边界，不能把沙箱os.access结果当主机权限结论。

依据：[PostgreSQL psql元命令与批处理](https://www.postgresql.org/docs/current/app-psql.html)、[COPY TO STDOUT/CSV](https://www.postgresql.org/docs/current/sql-copy.html)，以及本仓当前脚本、capture/候选/提升实现。正式传输与全量写入结果尚未产生，不计为M5完成。

### 27.5 新路径实际验证进展

真实只读COPY审计两源各300代码/15450行，CSV计数和Parquet读回数量一致，业务列双向EXCEPT ALL均为0；CSV分别1690640/2651985字节，源导出加转换读回约1.66/3.97秒，峰值RSS约239MiB。详见[传输证据](../../../reports/stock_week_m5_transport_probe_20261003.json)。这是2025样本，不是全量验收。

两源试点各捕获3units/41932行，取消后已封存unit被复用，完整重放源调用0；2025候选各15450行/52文件，值差集0。正式staging与/private/tmp属于不同设备，试点向临时目标提升正确触发cross_device_promotion_forbidden，无正式Raw写入；部分市场试点只审计候选，完整年度才进入正式提升，不放宽路径或同设备门禁。详见[试点证据](../../../reports/stock_week_m5_copy_pilot_20261003.json)。

CodeGraph query/impact覆盖捕获协调器、Prod adapter、capture store及候选消费者，直接代码搜索补齐测试和CLI调用方；新空年证据helper引入纯planner依赖，受保护治理启动器只增该文件的读取白名单，网络/正式Lake/凭证禁令保持。当前正式全量仍待执行及delta审计，未写events。

## 28. M5 物理 bootstrap 结果（2026-10-03）

已按 §27 执行两主源完整历史捕获、年度候选校验、同设备原子提升及独立正式读回。未复权2895784行、复权2891262行，各212units、410个source chunks、857个正式周文件；正式源日期2010-01-01至2026-09-25。源行数=捕获行数=正式行数；reject、同值去重、排除行、重复key与年度业务值双向差集均为0，正式文件集和全部指纹匹配。结束经唯一脚本再读Prod库存：代码年记录、行数/日期边界及全表最早/最晚源日期差异0，正式代码年库存与原冻结库存差异0。业务值一致性限定于已捕获unit快照；库存delta不是此后同键值修订的完整认证。

Raw完整保留源NULL：只有end_date为空，未复权21495行、复权16976行；价格/成交量/复权价格列NULL均为0。非周五/异常OHLC或负成交量统计0。未新增Silver清洗、未自行补复权、未开始备用源修补。

| 性能实测 | 未复权 | 复权 |
|---|---:|---:|
| capture总耗时（含脚本/转换/chunk校验） | 395.100秒 | 435.355秒 |
| 最慢单unit导出 | 4.312秒 | 4.325秒 |
| 年度build/audit合计 | 27.050秒 | 34.588秒 |
| promote/readback合计 | 14.302秒 | 18.521秒 |
| CSV字节 | 319150325 | 498881104 |
| source chunk字节 | 78559392 | 138599798 |
| 正式Parquet字节 | 89441602 | 157624274 |
| capture/staging留存字节 | 401345522 | 641172856 |

组合执行进程累计peak RSS=1867988992字节（1781.453MiB，约1.74GiB）；不能把DuckDB memory_limit=512MiB写成进程RSS硬上限。[DuckDB官方说明](https://duckdb.org/docs/lts/configuration/pragmas)指出该参数约束buffer manager，string_agg等聚合可在其外分配。当前canonical hash仍按有界年度/周group处理，没有内存/临时空间超限错误。实际结束留存spill为0字节，执行期间peak spill没有采样，**不宣称未发生spill或已完成强制spill压力验收**。后续标准操作采用 §13 已交付的capture/build/promote独立CLI阶段、按年度进程执行，并在下一阶段补过程RSS/peak spill测量；此为性能可观测性剩余项，不影响本次业务物理对账结论。

验收与测量详见[M5报告](../../../reports/stock_week_m5_copy_assessment_20261003.md)、[最终对账](../../../reports/stock_week_m5_final_reconciliation_20261003.json)、[性能/NULL测量](../../../reports/stock_week_m5_copy_metrics_20261003.json)。M5两主源物理bootstrap完成；M6备用源、M7事件、M9自动更新尚未执行，不能把物理文件完成说成全部DG就绪。本轮没有instance/events/动态分区/sensor/schedule变更；源码和文档修改尚未提交、未推送。

## 29. M6 五对象执行卡（执行前冻结）

范围固定为000005.SZ、000961.SZ、002089.SZ、300090.SZ、600090.SH；anchor从2010-01-01至2026-09-25，排除2026-10-02。M7才扩查211退市与251身份候选，M8才补事件。本轮不修改主源Raw、Prod、Silver、definitions、自动任务或任何字段合同。

先刷新五对象有界历史源证据：weekly显式11列，20091228至20260927，单对象最多874周，响应达到6000或有重复周/越界即拒绝。成功完整响应逐key与既有日线期望候选对账；有数据键才进入AVAILABLE，成功缺行记录source_key_absent_confirmed，错误保持failed/unchecked。旧3132只作独立基准。原始业务响应CSV与请求/时间/数量/字段/hash证据持久化，不保存token。

按anchor年冻结CSV候选状态及expected键，单年最多5对象×53周=265键、5units、含重试最多15次年度请求；最多17年度、85units、255尝试，非空实际数量由dry-run决定。每年度独立capture、build、promote进程；每来源每年度完整捕获后仅构建和提升一次，不逐对象重写周文件。源响应及年度候选上界约4505行/857文件，实际written按完整窗口返回行计而非只按缺口计。正常年度约5次调用加至少1秒间隔，预计数秒到十余秒；极端重试可达315秒，预算上限不是ETA。512MiB为DuckDB buffer，2线程、2GiB spill沿用WeeklyBudget；进程RSS和spill过程峰值另测，0.1秒采样是观测下界，进程退出resource peak RSS另记。每阶段设置12分钟外部期限，超时取消且保留已封存unit及checkpoint；源/目标量或hash不一致不提升。staging和正式目标同设备且空间预检后执行，目标仅raw/tushare/weekly。

代码落点：stock_weekly_history_cli.load_inventory增加明确kind=weekly_history_inventory/version=1的读取；原Prod格式与行为保持。新增load_weekly_inventory从受控CSV读取WeeklyCandidate，验证文件hash/大小/行数、严格列合同和AVAILABLE集合与expected文件完全相等，复用WeeklyHistoryScope与freeze_weekly_history_plan。build的年度来自WeeklySourceUnit.anchor_start；capture仅alternate选择现有WeeklySdkWorker，token只在capture执行时从现有TUSHARE_TOKEN取。预算默认不新增/不修改，现有CLI参数不删除；新格式仅离线bootstrap消费者使用，不对用户/运营时间控件增加参数。

正反验收：主源dry-run不构造exporter；备用dry-run不读取token/不创建目录；篡改候选/expected、缺proof、空白错误状态、重复键、错误year/未冻结plan拒绝；AVAILABLE范围外状态不能进入请求；源等待取消及已封存receipt重放无需源调用；年度业务值差集、源端/捕获/正式行数、NULL/schema/key/分区/文件hash及逐key恢复结果对账。CodeGraph query/impact覆盖WeeklyHistoryScope、capture_weekly_history、load_inventory，直接搜索补齐CLI/测试与candidate/promoter调用；没有src子系统/API/前端消费者变更。真实只读源刷新与正式写入分阶段列精确命令，临时审计/测量脚本仅执行本卡，证据落reports，脚本不接入definitions。

M6执行前启动失败记录：临时stage启动器首次缺少__main__保护，spawn子进程重复进入协调器，被writer锁拒绝；三次unit启动尝试已计入原计划，未形成receipt或正式文件。修正保护后原unit_attempt_budget_exceeded正确阻止继续，不能清空attempt或扩大重试预算。保留原冻结计划、失败目录与两份日志；重新冻结v2证据格式为每对象JSON，包含同一真实响应的请求/时间/列/CSV指纹及完整原始业务行，原CSV仍保留。新证据hash产生独立计划，仍是相同五对象/3132键/69units及默认2次重试；不伪称旧计划续跑成功。修正启动器后执行新计划取消→resume→replay，验收分别记录。


## 30. M6 五对象物理补齐验收

新source快照与原候选基准一致：000005.SZ 656、000961.SZ 732、002089.SZ 674、300090.SZ 473、600090.SH 597，共3132候选键；限定历史窗口内源响应也是3132行。15个anchor年度、69units完成捕获与一次年度构建/提升；734正式周文件、1372621字节，源日期20091231至20240510。Raw原日期/11列/DOUBLE/源单位保留，20091231正确归入2010-01-01分区。source↔capture↔formal全部业务列EXCEPT ALL差集0、重复键0、分区错放0、候选遗漏0，全部目标文件集和hash与audit一致；逐key恢复台账3132行。

v2计划真实取消在封存首unit后发生，续跑复用receipt；最终69次请求恰等于69units，完整重放不增加请求。v1临时启动失误和三次失败attempt留存，未删除检查点/增加预算/写正式文件；不将v1失败描述为v2续跑成功。累计阶段实测153.213秒；进程自身退出peak RSS255852544字节，采样进程树peak RSS447283200字节（426.5625MiB）；1147次观测spill峰值0。采样间隔目标0.1秒，ps/扫描开销会延长实际间隔，故只能作为峰值下界，未强制spill测试。

前后复权未恢复：另存3132周期×qfq/hfq=6264条记录，引用2026-10-02的stk_week_month_adj对象历史成功空响应，checked_at保留原日期，reason明确本轮未刷新该源。weekly响应不能证明qfq/hfq已补；并不宣称全体211退市、251身份候选或全市场完整。

CLI及范围冻结正反例、source监督/取消、candidate/promoter/边界、定义/static gates三组测试46/50/162通过（含重复测试，不累加）；补充成功空候选证据校验后CLI17项再通过；Ruff默认及致命错误基线、文档integrity、diff检查、CodeGraph sync/status通过。依据M6执行卡及接入模板7A，本轮只涉及离线CLI，未改字段、asset/catalog、API/前端或子系统依赖。详见[M6验收](../../../reports/stock_week_m6_assessment_20261003.md)、[独立对账](../../../reports/stock_week_m6_reconciliation_20261003.json)、[逐key台账](../../../reports/stock_week_m6_key_outcomes_20261003.csv)及[复权残余](../../../reports/stock_week_m6_adjusted_residual_keys_20261003.csv)。M6完成；M7为退市推广与身份分支，M8才是事件补录（以§15为准，之前附录中的阶段号混写不作为执行依据）。本轮未提交或推送。

## 31. M7 退市推广与身份分支执行卡（执行前）

本轮沿用已批准M7：固定旧候选快照，退市未复权206对象/100505键/2294实际code-year（211对象中M6五只已完成），年份2010–2024；anchor范围仍2010-01-01至2026-09-25，排除2026-10-02。身份分支251对象/63460键（249 BSE/62563，另2未知/897）先只读核验，不因名字相似或当前股票池更名自动准入，不改identity seed/正式map。字段/单位/Rawkey/日期语义、默认预算及CLI合同均不变。

| 性能项 | 执行范围/门禁 |
|---|---|
| 来源调查 | 206对象×有界20091228–20260927窗口，≤874周/对象，显式11列；每对象最多3次/618尝试，22秒外部期限，成功空保列，不把zero-column/HTTP错误当空 |
| 真正捕获 | 只取源证据AVAILABLE键，年度max182对象、每unit≤54行；上界2294units/6882尝试、123876行、857周文件；实际计划dry-run后减少，禁止全市场矩形展开 |
| 批次/请求 | 捕获并发1，默认1秒间隔/20秒超时/2次重试；20对象是工作批次，完整年度捕获后构建/提升一次，不每20对象重写全年 |
| DuckDB/输出 | 512MiB buffer/2threads/2GiB spill、年度候选/目标扫描；scope/candidate≤250000键，候选输入/源证据分别hash校验，外部年度阶段12分钟期限 |
| 成本实测依据 | M6 69units/153秒含构建与提升；本轮2294units按相同监督路径约一小时量级，实际测量、不以预算当ETA；源调查预计数分钟 |
| 写入/恢复 | canonical staging与正式weekly同盘，保留M6五对象；原候选全校验、逐文件checkpoint与replace，退出保留receipt/attempt；成功空/失败/未查分列，超预算不清checkpoint或扩重试 |
| 观测 | 当前对象/年度及已封存完成量；独立年度进程RSS、进程树RSS及spill采样；只按当前阶段目录扫描spill，目标采样间隔0.1秒为观测下界，不宣称压力通过 |

身份只读审计消费正式silver/basic/stock_identity_map及两张主源Raw；对confirmed且整自然周包含于有效区间的键做保守canonical覆盖判定。inferred、缺map、边界周、映射冲突及identity-source有效区间不清单列pending，不用星期五假定周内真实变更日期；需要时再用获准Prod日线真实日期/源真实日期核清。不将canonical已覆盖写成原代码物理已补。先聚合代码/周键而不是734/857文件逐check深扫，源日期用文件内部VARCHAR、hive_partitioning=false。已确认身份但确有残余的对象另冻结准入计划，未查源不得当无源。

实施与验收落点：只复用CLI load_weekly_inventory、纯planner、WeeklySdkWorker、capture store、candidate/promoter，不修改definitions/API/src层或新增配置。新增本轮临时调查/冻结/执行/只读审计脚本不接入正式definitions，证据落reports；所有真实响应先保存CSV/每对象JSON参数/日期/列/行/hash，年度candidate与expected hash冻结后才capture。目标写入仅raw/tushare/weekly，正式identity map与主源Raw只读，Prod不写；不写Dagster instance/events/动态分区，也不启用sensor/schedule。M8仍是下一独立阶段。

M7身份只读预检结果：两主源对63460历史键均没有可据confirmed map闭合的canonical周键；245对象/38893键处于整周confirmed有效区间，但源未核验；剩余24567键含249对象/23670映射有效期之前或边界、2对象/897 inferred键。这里不是证明源为空，也不改写正式映射。按本节已约定“已确认身份但确有残余另冻结准入”，新增245对象的只读weekly可用性调查，显式原始代码、不改用canonical请求。总调查451对象，最多1353次尝试；只允许38893个confirmed区间键在合格源实测后准入。若空响应记录该范围无源；有效区间之前/边界/inferred继续pending，不能把原始物理缺行抹成已覆盖。

捕获年度阶段按现有objects_per_batch=20细分进程工作批次：临时执行器每次调用同一冻结年度manifest的capture_weekly_history，仅在新增20个receipt封存后的安全边界设置cancel；没有开始下一unit、不增加失败attempt，不提前构建/提升。下一批resume严格验证已封存receipt；所有年度units完成才一次build/promote。此控制避免退市与身份合并年度超过12分钟单阶段期限；不增加CLI/config/typed budget合同。既有coordinator会重验已完成的小型receipt/Parquet，年内累计验证开销独立测量，不扩为全历史扫描；超时/校验失败保留现场并拒绝提升。后续真实源→捕获→正式对账以冻结unit窗口内全部返回行数为准，窗口以外源调查数据不伪称应写入行。

### 31.1 实际冻结与残留细分

初始206退市对象/2294 code-year是退市支预算，不能当成最终两支总规模。完成只读身份核验后，两支实际451对象、139398候选键，136549 AVAILABLE、2849成功缺行；16年度3232units，年度最多319units，默认request cap9696，单位完整返回行上界144964。范围和源证据已冻结，capture、构建和提升进行中；最终全部业务列与文件集读回通过前，不标M7完成。

身份未决24567键细分：2 inferred对象897键，239对象23494键的整个周落在映射有效区间之外，176对象176键真正跨有效区间边界。后两者不能都表述为“周跨边界”；历史冻结台账原reason保留，新细分台账另存，不改绑定manifest的证据。未决键不能按confirmed admission进入apply；已准入unit完整源响应仍全部保留，可能物理覆盖部分未决键，最终报告须分别给出原始代码物理覆盖与canonical身份确认状态，不能直接把24567当成最终物理缺口。

复权台账按原historical raw_adjusted缺口171616键分别列qfq/hfq，343232是复权侧记账数量，不是接口请求数。同一stk_week_month_adj响应承载两侧字段。本轮weekly未验证复权源，除M6原五只6264条保留2026-10-02历史空源证据外，336968条均为source_unchecked，查询时间/response_rows不伪造。后续可补性最佳努力，不作为本次未复权Raw提升门禁。证据：[M7执行前评估](../../../reports/stock_week_m7_preflight_assessment_20261003.md)、[残留分类](../../../reports/stock_week_m7_residuals_prepared_20261003.json)。

### 31.2 最新代码主源覆盖交叉核验

额外只读核验canonical_code在两主源Raw直接存在的情况：38893 confirmed候选均无对应最新代码周线，未因canonical投影的有效区间过滤制造准入误报。897 inferred键在两主源有最新代码周线，但映射仍未确认，不作为等价覆盖证明；不得自动改正式identity map或Raw代码。其余23670有效区间外/跨边界键也无最新代码直接覆盖。结果见[交叉核验](../../../reports/stock_week_m7_canonical_presence_20261003.json)，该核验不修改冻结manifest或apply范围。

## 32. M7 物理验收与残留（2026-10-03）

M7已完成退市推广与confirmed身份分支：16年度3232units，本轮136549行、正式139681行/803文件；全字段差集、重复、分区错放、AVAILABLE键遗漏均0，M6原3132行保持，两主源1714文件和identity map指纹不变。139398候选键中136549可补键原代码已读回；2849源成功缺行单列；24567身份未决按有效区间/inferred/边界及物理存在分别记账。历史167097原代码缺口候选中现物理覆盖139681键、27416候选仍未覆盖；身份区间外/未决不能直接认定应补，不表述为全市场已完整。148个跨边界键在源快照存在，仍需实际日线日期核验后才能准入。复权343232条保留6264历史源空、336968未核验，没有生成复权值。独立审计首次全局读取3232分块触及512MiB，后改为128文件SQL批次读入、关闭审计插入顺序保留，在同预算下通过；失败证据保留，没有改正式数据或源请求。进程阶段及其子进程树RSS采样峰值527.12MiB，spill采样0不等于强制压力通过；真实请求数3232，批次续跑无额外重复请求。详见[M7验收](../../../reports/stock_week_m7_assessment_20261003.md)。未提交/推送；M8事件及M9更新未执行。

## 33. M8 事件补录开发卡（2026-10-04）

沿用§12与接入模板§7A：输入是M5两主源、M7备用源最新年度sealed audit的路径与SHA，不扫描目录扩大范围，不调用Tushare/Prod、不修改行情。预计2517文件、5926727行；最多10068个事件，实际缺少的分区和事件由只读dry-run冻结。M7年度证据包含M6存量，不能拿已过期的M6文件指纹发布通过事件。

代码落点：`bootstrap/stock_weekly_event_files.py`按source/year复用正式schema、key/partition、canonical校验；`checks/stock_weekly_checks.py`提取同一交付证据核验函数，每年度只深扫receipt一次；`bootstrap/stock_weekly_events.py`负责事件读取、冻结计划、分阶段写入和读回；独立CLI与instance adapter负责命令/现有本机PG存储连接。不上definitions、不新增asset/check/job或环境配置，既有check入口及元数据语义保持一致。

预算来自唯一WeeklyBudget：DuckDB512MiB/2线程；只读不spill；每年度最多54文件；事件读取每100分区、每页500记录、累计20000记录上限，稳定cursor与storage-id批量读取check正文；拒绝无界历史扫描。每次apply最多100个事件或100个注册键，取消检查在每个unit前后；每个完成unit写原子checkpoint，事件写后 checkpoint失败靠实际事件身份恢复，禁止删除历史事件。

EventPlan封存源/asset/week、文件SHA/逻辑hash/行数、audit路径/hash/SHA、instance配置SHA与非敏感存储身份、当前materialization关联以及待补清单。materialization复用统一metadata helper与weekly_delivery证据；check为同分区blocking/ERROR/passed，绑定实际storage_id/run_id/timestamp。apply逐文件重验SHA和最新materialization；新目标或未知事件变化拒绝续跑，不自动扩容计划。分区注册、materialization、check分开执行；checkpoint只证明执行进度，物理及实际事件读回才证明成功。

隔离测试覆盖源证据变更、错分区/重复/字段异常、读取上限与cursor、历史failed/旧目标、取消、事件写后异常、幂等续跑。正式dry-run只构造现有PG存储，autocreate=false，禁止默认instance discovery、DDL、launcher和sensor。正式apply遵守性能治理§7.2，先报告数量与完整命令，再单独审批；写后聚合审计并抽五个代表分区校验实际readiness，不全历史逐check深扫。当前开发卡不代表正式事件已补录。

### M8 开发与正式只读验收（2026-10-04）

四个事件helper/CLI、同一源证据校验提取及隔离测试已完成。只读核验2517文件/5926727行与50年度证明一致，50连接/2867 SQL/14352证据文件、15.719秒；现有相关events为0，冻结857注册键、2517 materializations、7551blocking checks，10068事件。计划hash `39154bfe35d3395c65472513fb08805866fa7aa707d906d76f916429368a2012`，只采用v3计划。

CLI的start/count只选择冻结清单：register每100键，materializations每100条，checks每25文件最多75事件；每次写上限仍100。apply按批重验源receipt及sealed条目，每写重验文件/auditSHA和实际当前target。既有不匹配check列blocked并拒绝全部apply：现行Dagster runless唯一键不支持直接覆盖旧check，不删除历史、不伪造run_id；本轮blocked=0。五代表分区实际readiness抽查只在最终audit做。

78项定向/相邻、125项OS隔离治理/静态测试通过；静态启动器旧113/112数量与20个源码路径清单漂移已精确校准，未扩大资源权限。CodeGraph query/impact/sync/status与当前消费者核验完成，未改变API/前端、catalog/schema或子系统边界。正式apply尚待性能治理§7.2单独审批；完整读写/恢复及139条命令见[M8验收及执行卡](../../../reports/stock_week_m8_assessment_20261004.md)。未提交/推送，M9未开始。


## M8 正式补录与写后验收完成（2026-10-04）

管理员确认冻结执行清单后，按原v3 plan hash执行全部139条命令：857周分区注册、2517 materializations、7551 blocking checks，共10068事件。单分区试点实际readiness通过后进入全量，重复遇到试点时幂等跳过1 materialization和3 checks；全部批次成功，无额外事件、重试或范围扩张。

最终只读审计重新验证2517文件/5926727行与原证据一致；缺registration/materialization/check、blocked及latest failed均0。返回17619条观测记录，低于20000预算；两主源2010-01-01与2026-09-25、备用源2010-01-01五代表分区真实文件及check target关联/readiness全部通过。当前批准文件范围已就绪，不等于M7残余业务缺口消失。

命令累计实测1503.595秒：注册33.946秒、materializations131.788秒、checks1311.883秒、最终audit25.978秒；此数是命令耗时累计，不含人工试点审阅等间隔，也不是RSS/spill压力验收。此次未改正式行情/Prod/Silver，不调用源、不启用sensor/schedule、不改变依赖矩阵。代码沿用此前78项定向/相邻及125项OS隔离治理/静态验收，本轮只执行获批命令、读回和文档对账。

[最终对账](../../../reports/stock_week_m8_final_reconciliation_20261004.json)、[逐批执行台账](../../../reports/stock_week_m8_execution_20261004.jsonl)、[完整验收](../../../reports/stock_week_m8_assessment_20261004.md)。M8完成；下一独立阶段M9为更新机制，未开始。修改未提交/推送。


## 34. M9 更新机制：每日19:30与备用仅手动（2026-10-04）

### 34.1 管理员口径与范围

自动更新每天Asia/Shanghai 19:30开始，只选择`raw_stk_period_bar_week_update_job`与`raw_stk_period_bar_adj_week_update_job`及各自三个blocking checks。`raw_tushare_weekly_update_job`不进入任何自动selection、fallback、repair或自动source probe；源异常只向运营显示原因及手动备用方案，执行备用必须有明确手动任务。备用只提供未复权行情，不能提示它补qfq/hfq，也不混写主源Raw。

沿用本方案已有“已结束周/遗漏周”语义，不默认扩为当周每日滚动快照。每日触发与每周产生新分区不同：没有新的已完成周且没有欠账时，显示已就绪并跳过下载；周末可继续尝试之前未完成的周。已向管理员提出滚动当周的可选澄清；在进一步改变周期交付口径之前，以既有已结束周设计推进。当周滚动模式若被选择，需要另补源行为实测、快照/修订及日期输入合同，不能仅改时间常量就启用。

### 34.2 编排与选择

沿用单只独立sensor，tick_min_seconds=60，通过纯planner的每日19:30时间门禁开启更新；不再并设schedule形成两个写入发起方。19:30之前先返回skip，不查源、不重扫Lake或深读事件；19:30后的首个实际tick开始判断，daemon延迟必须显示真实evaluated_at，不能承诺准点完成。该模式沿用当前stock_mins_qfq_daily_sensor的时间门禁结构，并参考[Dagster sensor官方说明](https://dagster.io/docs/guides/automate/sensors)；minimum_interval是最小间隔，不是精确时钟。若服务停机后晚于19:30恢复，按欠账事实判断；次日19:30前不补发凌晨任务。

每次为一个最早未完成自然周规划两主源：

1. 先读正式交易日历，确定已经结束的周、该周最后实际交易日和无交易整周；自然周五仍是请求/分区坐标，节假日不改成最近交易日。
2. 缺日历或日线/身份覆盖证据时显示具体blocked原因，不推断无交易、不触发上游日线任务。
3. 用两资产当前文件/交付证据/实际target checks判断已完成、未完成、需要人工修订，M8已verified历史作为初始化基线。cursor只是有界frontier与选择理由；不保存全历史键、不替代物理事实、不将已知退市/身份未决残余自动重解释成新欠账。
4. 查询两主源queued/started意图，按source/week去重；同一source最多一个pending，同一个目标文件只能有一个writer。为避免独立SDK进程假称共享限流，首期两主源串行领取同周任务，完成一个后再领取另一个；不增加全局token配置。
5. 两源独立提交/验收，一个失败不回滚另一个已验证文件。下一周不越过未完成的当前周期；大范围停机积压走专项恢复，sensor不得全历史深扫。

新自动unit由source、自然周、policy_version、每日意图日期构成，复用`build_asset_update_run_key(subject,unit_id)`及`build_run_request`，不自建run key builder。每日意图日期用于明确每日19:30的新尝试，不用于每tick换key；同日源未就绪不得每分钟重开job。已提交任务的进程退出/技术失败在原unit内按持久化receipt/checkpoint恢复，实际run retry消费者须在实现前专项审计，不能靠变更unit冒充安全续跑。

### 34.3 下载、交付与异常

源参数继续采用当前Prod request builder与DG point helper已核对的`trade_date=自然周五,freq=week`，显式完整业务fields，6000/页、最多4页，必须证明分页结束，满页达到cap不视作完整。不从当前上市池过滤全市场请求，不自动重拉全历史复权。

19:30仅表示开始尝试；源成功返回仍可能不是完整周。对新周期，捕获receipt后在候选提升前核验`end_date`、周期内实际日线覆盖/身份及分页完整性，区分停牌/退市合法缺行与未完成计算。具体end_date谓词与停牌/除权样本需按当前源实测收口：两份本地文档都定义计算截至日期，未复权示例显示trade_date周五、end_date周四；不能把接口名称“每日更新”或非空响应作为周已完成证明。未完成证据停留在staging，记source_not_ready/coverage_unverified，不写正式文件或PASS。

现有`deliver_stock_weekly_point`提供单周capture、候选及create_or_identical，但源码中每次生成新的point assembly，不具备自动意图的持久化unit续跑，也没有完整周source-readiness门禁。M9应在同一交付主链加冻结update unit、receipt/checkpoint恢复和候选前门禁，保留现有手动入口语义；禁止只给现有helper加一个sensor就宣称M9完成。任何需要修改其手动输入/行为的方案先逐项说明并确认。

新文件验证合格才原子提升并由实际asset job产生materialization/check。同值重跑幂等；同key异值、end_date或复权快照变化输出revision_required差异和计划，不自动覆盖既有文件，不使用M8 runless补绿流程。取消在请求/分页/审计/提升单元前后检查；已提交文件保留，观测写入失败不回滚业务数据。

运营说明通过现有sensor SkipReason、cursor detail与run日志承载，不另做前端页面或通知服务。至少展示source、week、daily_intent_date、当前阶段、已完成量、reason_code、证据引用与next_action。技术错误不记成无源；两源失败/超时/空/分页不完整/身份未决都不得自动调用weekly。

| 状态 | 处理与运营说明 |
|---|---|
| before_daily_start / already_verified | 等待19:30／该范围已验证，跳过源请求 |
| source_not_ready / coverage_unverified | 保留欠账与证据，下一每日窗口再判断；不写绿 |
| source_timeout / source_failed / page_cap_exceeded | 保存失败阶段与请求计数，原unit有界重试或明确手动续跑 |
| revision_required / identity_unresolved | 保留差异或身份依据，建议先审阅；不自动覆盖 |
| 主源未复权问题需考虑备用 | 显示“可按明确代码/周范围手动运行备用weekly，结果仅落独立Raw；未执行” |
| 复权主源问题 | 显示“weekly不提供复权，不能替代此资产；待主源/专项复权处理” |

### 34.4 配置与预算审计

以下是待实现配置设计，不代表已修改配置/启用服务。唯一持久化事实为typed policy版本、冻结update plan与staging receipts/checkpoint；沿用现有token及WeeklyBudget，没有新secret/env/DB表。所有消费者限定planner、sensor、worker、运行证据及其测试；policy变更生成新plan版本，不能让旧unit隐式改参数。

| 配置或固定约束 | 来源/默认与持久化 | 消费者、生效、可见和门禁 |
|---|---|---|
| timezone / daily_start_time | WeeklyUpdatePolicy：Asia/Shanghai / 19:30；plan显式序列化 | planner/sensor；reload后新意图生效，cursor显示；时间边界/非交易日/晚恢复测试 |
| tick_min_seconds | policy：60；definition/plan | sensor；reload生效；19:30前轻量skip，不能解释为每分钟下载 |
| max_periods_per_tick / per_source_pending / global_auto_pending | policy：1 / 1 / 1；plan | planner/sensor；两主源串行，共享预算；queued/started去重与手动writer冲突测试 |
| 每日每source/week一个自动意图 | 固定编排合同，daily_intent_date入unit/hash | planner/request/run查询；午夜换日、同日重复tick、源空次日再判断测试 |
| fields / page_limit / page_call_cap | source schema +现有StockWeeklyPointPolicy：完整字段/6000/4；receipt | worker与分页；完整page/终空页/超cap反例；不新增独立散落配置 |
| source_concurrency / min_interval / max_retries / timeout | 现有WeeklyBudget：1 / 1秒 / 2 / 20秒；plan | source supervisor；逐调用记数、取消与超时；源空不是技术重试许可证 |
| default_status | STOPPED；新definition固定 | definition/reload不启动，正式启用按阶段确认；停止状态测试 |
| automatic_sources | 两主源固定允许清单，不做可编辑fallback开关 | planner/sensor/run_request；selection、失败/空/超时全部断言weekly调用数0 |

每周期两源正常请求上界8次，含每页最多2次技术重试的硬上界24次；时间超时部分上界480秒，加限流/下载及候选校验，不把此数字当真实ETA。新周期最多2个正式文件，行数受当前WeeklyBudget与page cap共同约束；每源独立candidate/checkpoint，不全历史事务。sensor只查有界frontier，不扫描M8全部2517文件；实际SQL/连接/文件/事件API cap须在实现前按现有helper选择收口，禁止宣称已验证。

### 34.5 代码切片与验收

设计落点仍为`defs/stock_weekly_update.py`纯周期/意图planner、`defs/source_readiness/stock_weekly.py`有界事实判断、`defs/sensors/raw_stock_weekly_update_job_sensor.py`两主源编排，及现有point/capture/candidate主链的update-unit恢复；备用手动asset/job不改。审计现有配置/run query/retry/cursor helper和definitions加载消费者后再编码；若语义不符不得直接复用名称。

| 硬口径 | 必需验证 |
|---|---|
| 每日19:30，仅已结束周期 | 19:29:59/19:30:00、周一/周五/周末、UTC→上海、整周休市、日历缺失、服务晚恢复 |
| 只两主源；无备用自动fallback | selection精确；两主源分别失败、超时、源空、分页不完整时weekly fetch和run request均0 |
| 去重/串行/不越过欠账 | 同日重复tick、排队/运行中、手动writer、两源一成功一失败、长停机frontier有界 |
| 完整周证明 | 非空但end_date落后、日线覆盖未验证、合法停牌/退市、满页截断、终空页、source-empty与技术失败分开 |
| 安全恢复及修订 | 分页中取消/退出、receipt读回续跑、重复意图、文件变化、同key异值、观测失败不回滚正式文件 |
| 性能/真实样本 | 一正常新周两源、一次源未就绪样本、一个代表取消→续跑→读回；记录请求/行数/文件/SQL/耗时，正式写入另按实际unit批准 |

本轮只修订两份原设计文档；CodeGraph query/impact及当前代码审计覆盖run key消费者、现有weekly资产/jobs/checks、point helper、Prod参数builder、现有19:30 sensor模式及备用入口。无代码、配置或调度写入，不改变子系统依赖/源字段合同。M9尚未开发；先收口源完成谓词、持久化意图恢复及有界readiness API预算，完成配置/消费者审计后进入代码切片。

### 34.6 实现前收口：源完成、配置与读取预算

2026-10-04 已通过 Tushare MCP 核验两主源的默认、完整字段和关键字段请求，并以正式 Raw 日线对账 2026-10-02 周：两源均为5565行，与9月28/29/30日线代码并集一致。未复权5561行end_date=20260930，3行=20260929，1行=20260928；不得把后4行误判为缺口。历史20260925周的end_date可晚于所属周，不能要求等于周五或位于所属周。完整周谓词采用确认身份归一后的日线代码并集覆盖，每只股票end_date不得早于它在该周的最后实际日线日期。Raw保留源代码与原值；身份只用于审计，不改写Raw。无日线的停牌/退市不凭上市池生成缺口；无法确认身份则阻断。源无数据、日期格式错误、未覆盖日线、缺日历或上游check不绿均不提升。MCP接口不暴露limit/offset，本轮不把它冒充分页实测；沿用已核验point参数与6000/4硬门禁，隔离测试验证满页终止与截断反例。

新增自动意图输入只作用于两主源：StockWeeklyRawConfig.automatic_intent_date默认为None（现有手动行为），sensor显式传本地日期；不解析run key生成参数。WeeklyUpdatePolicy唯一保存时区/19:30/60秒及有界读取预算；history_verified_through=2026-09-25来自M8已核验历史，通过两源该周文件、交付和check初始化，禁止自动追讨M7历史残余。新字段消费者仅weekly asset、planner、point交付与测试；不新增env/数据库配置。旧手动任务不传新字段；备用传入自动意图必须拒绝。配置reload只影响新意图，冻结意图不得隐式改预算。

sensor一次只判断frontier相邻一个周，两源串行：最多2次pending-run查询各limit=1、2次当日run-key查询各limit=1、2次周materialization各limit=1及2次批量3-check查询；物理最多2个周文件及2份有界audit JSON。未提交阶段不下载源。日历一次查询仅周一到周五5天；选中源在asset内最多5个日线文件、1个身份文件、1个日历文件、2个冻结控制文件。日线与身份的blocking checks采用分区明确的batch API并绑定目标materialization；上限6组上游、每组最多1次materialization查询+1次批量check查询。参考读取在一条受限DuckDB连接中，最多8次业务SQL，扫描日线不超过5×10000行，身份不超过10000行；超过上限fail closed。停机积压按frontier逐周推进，不使用latest registered作为目标、不枚举全历史Lake。

自动意图在原point主链使用稳定assembly及source/week writer lock；每页落typed capture+receipt，成功页可读回，逐调用持久化请求总量和每页尝试次数（各最多3，累计最多12）。进程退出后显式原run重执行沿相同config/unit恢复；源未就绪同日不重开job，次日新日意图重新捕获。现有jobs没有Dagster RetryPolicy，本次不虚构全run自动重试，也不修改全局重试配置；技术调用在unit内重试，运营可原配置重执行。候选审计、提升checkpoint复用原实现；提升后即使日志或事件写失败，已提交文件保留，恢复沿原audit继续，而不是新建assembly覆盖。

每个新周期只写两个独立Raw文件及各自实际job的1个materialization+3个checks，禁止runless。单源新写最大10000行，最多4页/12含重试调用；两源串行总上限24调用/480秒超时部分，另加限流与向量化审计。每日门禁前0源调用、0Lake/DB读取。源完成依据被冻结到staging控制证据中，正式check校验该证据及Raw覆盖；后续身份snapshot正常更新不回溯污染旧交付。以上预算、取消/续跑/修订/观测失败反例是实现门禁，正式启用仍需最小真实交付验收。

### 34.7 M9开发与只读预演结果（2026-10-04，正式验收未完成）

已落地每日19:30的两主源sensor、完整周planner、有界源完成判断、稳定自动意图、成功页receipt复用、跨进程请求预算与间隔、执行锁、同值复用和异值修订说明。只选择两套主源及原三个blocking checks；备用只手动，任何自动失败/空/超时/分页截断不触发备用。StockWeeklyRawConfig增加可选automatic_intent_date，None保留原手动语义；统一configs builder生成run_config。通用build_run_request增加可选job_name，既有调用默认值和tags不变；run key仍由统一builder生成，不解析key作为执行输入。两个原jobs与checks的分区/字段合同不变，无新业务表、env、secret或Silver改动。

源完成判断与正式delivery check共享同一纯谓词；冻结引用在staging并进入signed audit，checks不依赖后续变动的身份snapshot。捕获预算逐调用持久化，技术失败最多每页3次，重执行不清零；成功页不会再查源。实际进程退出、取消后续跑、提升后观测失败、同key异值、源未就绪、满页达到cap、未确认身份和两个主源实际job的分区check均有隔离测试。source/week执行锁保护point任务，正式提升沿用已有writer lock、目标fingerprint与checkpoint，不引入备份或第二个writer。

**日线上游事件口径校准**：当前Raw日线4个blocking checks的日期绑定依据是target materialization，不是check.partition。首轮分区过滤错误地显示缺check，已用当前readiness纯helper的目标绑定语义校准；不改日线、不增加兼容分支。上游日线采用一次日期集合materialization查询（最多50条）及4个check历史各最多20条；身份采用1个materialization+1次3-check batch。新增typed policy max_upstream_check_records=20与max_materialization_versions_per_period=10，来源仅WeeklyUpdatePolicy，消费者为周线事件batch、冻结意图和测试，reload仅对新意图生效。不得直接复用全局CHECK_HISTORY_LIMIT=5000作为M9热路径预算。未匹配到目标、失败、不blocking或超出有界窗口均阻断，禁止扩大历史扫描冒充ready。

最终sensor每次最多核验基线与相邻目标两个周、两种源，最多4个materialization、4次weekly check batch、4个周文件及4份有界audit；加两次pending查询、最多两次当日意图查询、一次上游batch与一次has_dynamic_partition，总事件API上界20次、返回记录上界160条。19:30前仍0外部读取。无交易周的examined_through与最后真实交付verified_through分别保存，不能拿休市周要求不存在的周文件。缺分区时在同一SensorResult生成该一个自然周五的add request及一个主源RunRequest；只有正式启用后才由daemon写分区。消费者已核验三个weekly assets、九checks、三个jobs和新sensor，备用共用分区定义但不进入自动selection。

正式只读预演（模拟2026-10-04 19:30）确定首个欠账为2026-10-02；日线/身份blocking checks通过，两源MCP样本均覆盖5565代码。最终预演约0.268秒、16次事件API、95条返回记录（80条check历史+6条materialization+9条check batch），0源请求、0正式写入。报告：reports/stock_week_m9_readonly_preview_verified_20261004.json；先前未校准的preview/upstream报告保留为审计过程，不能当作当前门禁结论。

开发验证：11组相关回归167项通过；新增代码与修改的weekly路径Ruff通过。共享configs.py既有11项lint问题未在本轮扩大修复。续验补齐隔离器7个公告源码的精确读取清单及资产治理中raw_tushare_anns_d登记；完整113项静态检查与12项资产治理检查（468 subtests）通过，没有降低断言或修改公告业务代码。两个测试改动默认Ruff、全src/tests致命错误基线通过。现有dg check defs --no-check-yaml --use-active-venv在临时instance和精确源码只读隔离中成功加载整个code location，禁止网络及正式Lake/DB访问，没有安装或同步依赖。详见reports/stock_week_m9_defs_validation_20261004.json。共享静态门禁已解除；最小正式执行验收和调度启用仍分别待批准。
CodeGraph explore/query影响面覆盖原point调用者、资产/job/check、64个run request消费者及配置/cursor/readiness链；完成本轮后已sync/status。无src子系统边界或依赖矩阵变动，无正式路径变动。当前未提交、未执行正式更新、未启用sensor，M9状态为开发及静态/隔离验收已完成、最小正式验收待完成。

### 34.8 正式验收延期与月线先行（2026-10-04）

管理员确认源站尚未生成2026-10-02周线，本周最小正式验收记录为source_not_ready（管理员源站核查，非本轮API空响应实测）。不运行job、注册分区或启用sensor；源端就绪后再取得完整交付证据并恢复原验收。此前readonly preview/MCP字段样本不等于已经获得可正式交付的周线版本。

管理员明确允许先推进后续任务，因此§15“先完成M9再进入M10”调整为允许M10准备/开发先行，M9正式验收仍保留独立未完成项，不合并验收或提前标第一阶段完成。月线来源调查与[专项LLD初稿](dagster-stock-monthly-raw-onboarding-low-level-design-v1.md)已落档；本轮没有改动weekly执行代码。M10实现与正式bootstrap/事件/更新启用继续分阶段核验和授权。

### 34.9 月线bootstrap helper隔离验收（2026-10-05）

月线M10.C实现和验收详见[月线LLD §12](dagster-stock-monthly-raw-onboarding-low-level-design-v1.md#12-m10c-落地与验收2026-10-05)及[报告](../../../reports/stock_month_m10c_assessment_20261005.md)。只新增月线薄模块，复用统一DuckDB连接入口，不迁移或改变weekly helper合同。未注册月线definitions、未正式bootstrap/补录事件/启用sensor；下一步M10.D更新机制与definitions集成。M9仍待源就绪后的正式验收，不能用本轮隔离结果替代。


### 2026-10-05：M10.C提交及M10.D开发验收

M10.C已提交ac063248，未推送。M10.D按月线LLD完成两套Raw资产/6个blocking checks/2 jobs/默认STOPPED月线sensor及手动与每日19:30完整月更新开发；历史NULL bootstrap证明与新增源个股截至证明分开校验，不新增Silver/Gold，不自动备用或覆盖异值。代码与临时instance验收通过，正式bootstrap/事件及启用未执行；M9待源就绪的正式周线更新验收仍单列。当前月线范围及配置/性能/代码对账以[月线LLD §13–14](dagster-stock-monthly-raw-onboarding-low-level-design-v1.md)和[本轮验收报告](../../../reports/stock_month_m10d_assessment_20261005.md)为准，下一阶段M10.E，未宣称正式接入完成。
