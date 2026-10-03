# DG 股票周线备用源 Raw 补齐：代码级 LLD v1

日期：2026-10-03，Asia/Shanghai。状态：M0 开发前核验已收口；M1 纯合同／规划器已完成。M2 adapter、M4 definitions、M9 更新编排及正式同步／启用尚未实施。技术方案见 [方案 v1](dagster-stock-weekly-alternate-source-raw-backfill-plan-v1.md)。本文不是实施授权或“开发门禁全部通过”的证明。

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

# prod_db/stock_weekly.py：每 unit 单连接 readonly，fetchmany 有界
inspect_prod_weekly_source(resource, source: StockWeeklySource) -> ProdSourceInspection
iter_prod_weekly_batches(resource, unit: ProdWeeklyUnit, budget: WeeklyBudget,
                        cancel: CancelProbe) -> Iterator[pd.DataFrame]

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

利用实际主键前缀，每 unit 最多 300 个显式代码＋锚点年度对应源日期窗口。Planner 让各 unit 归属的周分区范围互斥：以源日期所属周五是否落入目标年度决定归属；读取跨年边界允许重叠，非本 unit 所属周记录只记 boundary_duplicate，交给对应年度 unit 保留，不造成源数据丢失。异常非周五源日期同样按其自然周存，Raw 源日期不改。

SQL 只允许固定表 enum 和字段 schema，值参数化；数值列投影为 `numeric::text`，日期 `to_char`，避免 psycopg2 Decimal → pandas float。示意：

```sql
SELECT ts_code, to_char(trade_date,'YYYYMMDD') AS trade_date,
       to_char(end_date,'YYYYMMDD') AS end_date, freq,
       open::text AS open, high::text AS high, low::text AS low,
       close::text AS close, pre_close::text AS pre_close,
       vol::text AS vol, amount::text AS amount,
       change::text AS change, pct_chg::text AS pct_chg
FROM raw_tushare.stk_period_bar
WHERE ts_code = ANY(%(codes)s) AND freq = 'week'
  AND trade_date >= %(source_start)s AND trade_date <= %(source_end)s
ORDER BY ts_code, trade_date, freq;
```

复权适配按 §4 的 21 列显式投影，不 SELECT *。连接通过 `connect_readonly_transaction()`；业务查询前设置 `REPEATABLE READ, READ ONLY`，SET LOCAL statement_timeout / work_mem，服务端 cursor `itersize=fetch_batch_rows`；同 unit 的 source count/control aggregates 和 streaming SELECT 在同一快照。结束 rollback，不建立全历史长事务。

每 `fetchmany(10000)` 立即构造 bounded DataFrame（SQL 已返回数值字符串），register 到受控 DuckDB connection，SQL 显式 CAST 后 COPY 一个 staging source chunk；unregister 并释放该 DataFrame。禁止 executemany 或 Python 一行一行写 Parquet，禁止整个年度 DataFrame 常驻。max_source_rows_per_unit 初始 30,000，超过时停止；规划阶段可按确定规则缩小代码批次，不能在 apply 中自动扩大预算。

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

命令名是未来代码接口，不是当前可执行命令。本轮未运行这些命令。采用现有项目解释器，不安装依赖：

```text
.venv/bin/python -B -m orchestrator.defs.bootstrap.stock_weekly_history_cli inspect --source primary_unadjusted
.venv/bin/python -B -m orchestrator.defs.bootstrap.stock_weekly_history_cli plan --scope-file <approved_scope.json> --output <approved_staging>
.venv/bin/python -B -m orchestrator.defs.bootstrap.stock_weekly_history_cli capture --plan <plan.json> --apply
.venv/bin/python -B -m orchestrator.defs.bootstrap.stock_weekly_history_cli build --plan <plan.json> --apply
.venv/bin/python -B -m orchestrator.defs.bootstrap.stock_weekly_history_cli audit --plan <plan.json>
.venv/bin/python -B -m orchestrator.defs.bootstrap.stock_weekly_history_cli promote --plan <plan.json> --audit <audit.json> --apply
.venv/bin/python -B -m orchestrator.defs.bootstrap.stock_weekly_history_cli audit-formal --plan <plan.json>
.venv/bin/python -B -m orchestrator.defs.bootstrap.stock_weekly_events_cli plan --formal-audit <formal-audit.json>
.venv/bin/python -B -m orchestrator.defs.bootstrap.stock_weekly_events_cli register --plan <events.json> --apply
.venv/bin/python -B -m orchestrator.defs.bootstrap.stock_weekly_events_cli report-events --plan <events.json> --apply
.venv/bin/python -B -m orchestrator.defs.bootstrap.stock_weekly_events_cli audit --plan <events.json>
```

plan/audit 可输出获准报告；capture/build 会写staging，promote会写正式Lake，register/report会写instance。没有apply时各mutating stage仅返回dry-run预算，不触发源调用、隐式注册或目录创建。scope文件路径参数不等于写入授权；审批必须匹配plan hash、stage、对象／文件／事件上限。

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
| `test_stock_weekly_prod_source.py` | fake named cursor＋300code/year | readonly在query前设置、每batch≤10000、无fetchall全集/SELECT *、保NULL/退市/非周五，单位不改 |
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

拟接口：`latest_completed_week_anchor(now, calendar, cutoff) -> WeekEligibility`，返回自然周五、周期窗口、截止状态与交易日依据；`plan_stock_weekly_updates(calendar, last_verified_delivery, pending_runs, budget) -> UpdatePlan` 只规划有界遗漏周期；`fetch_primary_week_pages(source, anchor, fields, budget, consume_page, cancel) -> SourceReceipt` 不在sensor重复拉源；`audit_weekly_delivery(receipt, expected_key_ref, unavailable_ledger) -> DeliveryAudit`；`plan_weekly_revision(old_fingerprint, new_capture) -> RevisionPlan` 单独处理同key异值。

采用一只独立编排sensor，周期性检查而非日线freshness。只选择两个主源job，不含备用历史job、不写上游。定义默认STOPPED，重载不启动。sensor不写Parquet、不直接调用源；新增动态周分区、RunRequest、cursor属于正式编排写入，启用前单独验收与授权。每tick先判已完成自然周期和正式交付证据，再排除queued/started运行；run_key必须复用当前 `build_asset_update_run_key(subject, unit_id)`；unit_id由source/anchor/计划版本构成，禁止自写run_key拼接或专属builder，cursor只记有界选择和观测，不以cursor成功替代物理交付。失败重试走现有受控重试机制，不能不断变run_key生成重复任务。

当周自然周五到达截止才可自动选择该周；休市周五不回退到最近开市日作为请求参数，仍显式trade_date=自然周五。使用正式交易日历判断周期内是否有交易日；日历缺失为calendar_unverified，不自动判整周无交易。整周确实无交易可明确跳过并记录，不能报告非空行情已完成。覆盖expected取周期内实际Raw日线键及核实身份，不要求所有在市股票每周有行，也不因Raw日线未准备就触发上游写入。历史欠账按最早未完成周期有界推进；不能仅用latest周而永久跳过长停机期间。日线证据/身份未决记原因，源无数据仍按管理员尽力补齐口径处理。

新周期 create_or_identical 支持新增键及同值幂等；同key异值、end_date或qfq/hfq快照变化生成修订差异及计划，不能自动提升为覆盖。bootstrap保留Prod原计算版本；Raw不是一份全历史实时重算的qfq序列。后续需要历史刷新时复用完整候选校验/原子提升/逐文件checkpoint，单独执行；不为新增一周自动重拉全历史。

### 18.2 更新配置审计补充（拟定，实施前校准）

新增配置集中于 typed `WeeklyUpdatePolicy`，与`WeeklyBudget`共同冻结；以下是设计默认值，尚非上线配置。不可散落在sensor/CLI/UI。沿用Tushare token和限流来源，不新增secret配置。

| 配置 | 默认／来源与持久化 | 消费者、依赖、生效、可见与门禁 |
|---|---|---|
| timezone / close_cutoff | Asia/Shanghai / 周五22:15；版本化policy→plan | planner/sensor；晚于源文档19–20点而非保证源已就绪；截止正反例，tick读取且cursor显示 |
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
