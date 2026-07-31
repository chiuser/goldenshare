# 指数技术因子（专业版）`idx_factor_pro` 低层设计 v1

状态：开发中；M1 Foundation 主链已完成，后续按第 11 节顺序继续实施

更新时间：2026-08-01

上游方案：[指数技术因子（专业版）`idx_factor_pro` 数据集接入方案](/Users/congming/github/goldenshare/docs/datasets/idx-factor-pro-dataset-development.md)

源站事实：[指数技术因子（专业版）源文档](</Users/congming/github/goldenshare/docs/sources/tushare/指数专题/0358_指数技术因子(专业版).md>)

## 实施进度

2026-08-01 已完成 M1 Foundation 主链：Definition、交易日 request builder、raw 表与 serving view ORM、DAOFactory、Alembic revision `20260801_000120`、freshness 映射，以及 Definition/resolver/source pagination/normalizer/writer/model-view 契约测试。未实现 Ops catalog、源站探测、自动任务页面或 workflow 改动；后续必须继续遵守本 LLD 第 1.2 节边界。

## 1. 本 LLD 固定的边界

### 1.1 已确认的目标

接入 Tushare `idx_factor_pro`，把每个交易日的全量指数技术因子写入 `raw_tushare.idx_factor_pro`，并由 `core_serving.index_factor_pro` 普通 view 对外查询。

首期只开放两种运营入口：

1. 手动维护 `idx_factor_pro.maintain`。
2. 运营人员在自动任务页自行创建 `idx_factor_pro.maintain` 的 schedule。
3. 自动任务可选“源站已有指数技术因子”作为触发条件；命中后只创建正常单日维护 TaskRun。

### 1.2 已确认的不做项

1. 不加入 `daily_market_close_maintenance`、`index_extension_maintenance`、`index_kline_maintenance_pipeline` 或任何其他既有 workflow。
2. 不预置自动任务，不新增补漏、schedule policy、Dagster 或 Lake 链路。
3. 不暴露 `ts_code`、`start_date`、`end_date` 等源接口过滤参数给运营。
4. 不按指数激活池请求、过滤或审计；raw 与 view 都保留源站按日返回的全量指数事实。
5. 不创建 serving 物理表，不双写；writer 只写 raw，view 不可写。
6. 不改通用 resolver、unit planner、source client、normalizer、writer、TaskRun 三表模型或既有 workflow；只允许改动本数据集的 Ops 探测分发、绑定校验和自动任务页面条件。
7. 不清空、删除、重建任何既有业务表、对象池或状态表。

源站探测不属于 ingestion 主链改造：它只决定何时创建 TaskRun，不参与 source 数据分页、normalizer、writer 或业务事务。

## 2. 审计结论

### 2.1 源端契约已经核实

接入方案已记录 2026-08-01 的 `tushareMcp.idx_factor_pro` 实测。实施必须以这些已验证结论为准：

| 事实 | 对实现的约束 |
| --- | --- |
| 未传 `ts_code` 或 `trade_date` 会返回参数校验错误 | 不允许无条件请求，也不能把 dataset 建成 no-time snapshot。 |
| `trade_date=20260731` 返回 3,146 条、3,146 个不同指数 | 一个交易日是一个完整全市场维护 unit。 |
| `start_date/end_date` 不带 `ts_code` 仍被拒绝 | range 不能直接透传给源端，必须先按交易日展开。 |
| `ts_code=000001.SH` 不带时间恰好返回 8,000 行 | 单指数全历史会截断，不能成为运营主入口。 |
| `limit/offset` 实测可分页 | 使用既有 `offset_limit`，分页由 source client 追加。 |
| 显式请求 89 个字段时返回恰好 89 个字段 | `source_fields`、raw ORM、迁移、view 必须逐列覆盖 89 字段。 |

源站单页上限为 8,000 行。当前单日规模小于一页，但实现仍用 `page_limit=8000`，以便未来超过一页时由统一分页逻辑继续拉取下一页。

### 2.2 接入前激活池覆盖审计

2026-08-01 已完成一次只读审计：2026-07-31 的 `idx_factor_pro` 源端集合为 3,146 个代码；`ops.index_series_active(resource='index_daily')` 的 1,216 个服务激活代码中，1,212 个当日有对应技术因子，4 个没有返回（`480055.CNI`、`480056.CNI`、`480057.CNI`、`931598.CSI`）。

这项审计用于避免误把“指数日线激活池”当成“技术因子源端完整集合”。它不改变 LLD 第 1.2 节：`idx_factor_pro` 运行时不读取、不过滤、不审计指数激活池；每个交易日仍只按 `trade_date` 拉取源端全量，并原样写入 raw/view。单日缺失不能推断永久不可用，未来若要做代码级服务资格管理，必须另立需求。

同日对本机 Dagster 实例 `cn_a_index_ts_codes` 的只读核验显示：当前 820 个指数日线动态分区代码全部位于该日 `idx_factor_pro` 源端集合中。它只说明 DG 当前日线运行时集合的源端覆盖为 100%，不把 DG dynamic partition 引入 `idx_factor_pro` 的 Definition、planner、request builder、freshness 或 completeness 语义。

### 2.3 当前代码可直接复用的主链

| 链路 | 已审计实现 | 本数据集采用方式 |
| --- | --- | --- |
| Definition 注册 | `src/foundation/datasets/definitions/index_series.py` 的 `index_daily_basic` | 在同一领域文件追加一条 `idx_factor_pro` Definition。 |
| 时间归一化 | `DatasetActionResolver.build_plan()` | point 生成 `point_incremental`，range 生成 `range_rebuild`；Ops 不提前展开日期。 |
| 交易日 unit | `DatasetUnitPlanner._build_generic_units()` / `_resolve_anchors()` | `trade_open_day + every_open_day`：point 一日一个 unit；range 取交易日历所有开市日，各生成一个 unit。 |
| 请求参数 | `request_builders._index_daily_basic_params()` | 新建语义准确的 `_idx_factor_pro_params()`；只格式化已归一化的 `trade_date`。 |
| 分页与字段透传 | `DatasetSourceClient.fetch()` / `_fetch_rows_with_pagination()` / `_execute_with_retry()` | source client 追加 `offset/limit`，并把 `definition.source.source_fields` 传给 connector。 |
| 清洗 | `DatasetNormalizer.normalize()` | 通用 `coerce_row` 把 `trade_date` 转日期、其余数值字段转数值；不新增 row transform。 |
| raw-only 写入 | `DatasetWriter._write_raw_only_upsert()` | 只调用 `raw_idx_factor_pro`；`index_factor_pro` view DAO 不得写入。 |
| 模型发现 | `table_model_registry()` | 新 raw 与 view ORM 由 package 扫描发现；同时显式导入 `all_models.py`，保证全模型加载路径完整。 |
| freshness 投影 | `build_dataset_freshness_projection()` / `dataset_observation_registry.py` | target 指向 view，`trade_date` 由 view 映射模型观测；不建立第二份 freshness 配置。 |
| 日期完整性 | `DateCompletenessRunCommandService` / `DateCompletenessAuditExecutor` | Definition `audit_applicable=True`，默认走 `date_bucket`；只检查每个应有交易日是否至少有数据。 |
| 手动/自动任务 | `ManualActionQueryService` / `OpsCatalogQueryService` | 由 Definition capability 自动派生，不新增页面分支。 |
| workflow | `WORKFLOW_DEFINITION_REGISTRY` | 只增加负向测试，确保 `idx_factor_pro` 不被加入任何 step。 |

### 2.4 与两个相近数据集的差异

| 对照对象 | 可复用处 | 不可照搬处 |
| --- | --- | --- |
| `index_daily_basic` | 全市场、按交易日、generic planner、`no_pool`、`offset_limit` | 它是 `raw_core_upsert` 且有 `ts_code` filter；本数据集必须是 raw-only view，且首期不能有 `ts_code` 输入。 |
| `stk_factor_pro` | 宽表字段动态映射、raw-only upsert、raw-backed `core_serving` view、writer 护栏测试 | 它依赖股票对象池、复权因子门禁和专用 unit builder；本数据集不能继承这些股票语义。 |

### 2.5 源站探测链路的代码审计

现有 `index_daily`、`index_mins`、`stk_mins` 与 `kpl_list` 探测共用两段 Ops 主链：

1. `ScheduleProbeBindingService` 验证 `probe_config.condition_kind`、目标 action、触发方式、固定日期与 calendar policy，随后重建该 schedule 对应的 `ProbeRule`。
2. `ProbeRuntimeService` 在窗口和间隔满足时执行条件服务；命中后以 `TaskRunCommandService` 创建普通 TaskRun，miss/error 只写 `ProbeRunLog`。`schedule_probe_fallback` 已会检查当日是否已有有效 probe TaskRun，避免兜底重复创建。

`idx_factor_pro` 不能直接照搬 `IndexDailyRemoteReadinessProbeService` 的五个代码循环。该服务向 `DatasetActionResolver` 临时传入 `filters={"ts_code": ...}`；而本数据集的 Definition 明确没有 filter，`DatasetActionValidator._normalize_input_params(..., strict=True)` 会将此拒绝为 `unknown_params`。当前 `DatasetInputField`、manual action API 和自动任务 API 也没有“内部可用、运营不可见”的字段语义。

因此本 LLD 推荐只复用探测框架，不复用“逐代码样本”细节：探测以空 filters 的正式 point 意图进入 resolver，再对已生成的单日 request params 追加探测专用分页和 fields。这样 source 日期参数仍由 ingestion builder 生成，Ops 不自行拼装源接口日期参数。

## 3. 目标对象与唯一事实

### 3.1 DatasetDefinition

唯一数据集事实追加到 `src/foundation/datasets/definitions/index_series.py`。不可在 Ops、前端、catalog 查询或 schedule 服务另建同名映射。

```python
{
    "identity": {
        "dataset_key": "idx_factor_pro",
        "display_name": "指数技术因子（专业版）",
        "description": "维护指数技术因子（专业版）数据。",
        "aliases": (),
    },
    "domain": {
        "domain_key": "index_fund",
        "domain_display_name": "指数 / ETF",
    },
    "source": {
        "source_key_default": "tushare",
        "source_keys": ("tushare",),
        "adapter_key": "tushare",
        "api_name": "idx_factor_pro",
        "source_doc_id": "tushare.idx_factor_pro",
        "request_builder_key": "_idx_factor_pro_params",
        "base_params": {},
        "source_fields": IDX_FACTOR_PRO_SOURCE_FIELDS,
    },
    "date_model": {
        "date_axis": "trade_open_day",
        "bucket_rule": "every_open_day",
        "window_mode": "point_or_range",
        "input_shape": "trade_date_or_start_end",
        "observed_field": "trade_date",
        "audit_applicable": True,
        "not_applicable_reason": None,
    },
    "input_model": {
        "time_fields": (trade_date, start_date, end_date),
        "filters": (),
        "required_groups": (),
        "mutually_exclusive_groups": (),
        "dependencies": (),
    },
    "storage": {
        "raw_dao_name": "raw_idx_factor_pro",
        "core_dao_name": "index_factor_pro",
        "target_table": "core_serving.index_factor_pro",
        "delivery_mode": "single_source_serving",
        "layer_plan": "raw->serving_view",
        "std_table": None,
        "serving_table": "core_serving.index_factor_pro",
        "raw_table": "raw_tushare.idx_factor_pro",
        "raw_conflict_columns": None,
        "conflict_columns": None,
        "write_path": "raw_only_upsert",
    },
    "planning": {
        "universe_policy": "no_pool",
        "universe": None,
        "enum_fanout_fields": (),
        "enum_fanout_defaults": {},
        "pagination_policy": "offset_limit",
        "page_limit": 8000,
        "chunk_size": None,
        "max_units_per_execution": None,
        "unit_builder_key": "generic",
        "fetch_concurrency": 1,
    },
    "normalization": {
        "date_fields": ("trade_date",),
        "decimal_fields": IDX_FACTOR_PRO_NUMERIC_FIELDS,
        "required_fields": ("ts_code", "trade_date"),
        "row_transform_name": None,
    },
    "capabilities": {
        "actions": (("maintain", True, True, True, ("point", "range")),),
    },
    "observability": {
        "progress_label": "idx_factor_pro",
        "observed_field": "trade_date",
        "audit_applicable": True,
        "freshness_policy": "continuous_open_day",
    },
    "quality": {
        "reject_policy": "record_rejections",
        "required_fields": ("ts_code", "trade_date"),
    },
    "transaction": {
        "commit_policy": "unit",
        "idempotent_write_required": True,
        "write_volume_assessment": "一个 unit 是一个交易日的全量指数技术因子；当前实测约 3,146 行，超过 8,000 行由 source client 分页后在同一 unit 提交。",
    },
    "completeness": {
        "scope": "date_bucket",
    },
}
```

上面的 pseudo literal 只说明最终值。实现必须使用当前 Definition 数据类的真实构造方式，不能为了接入改造数据类、resolver 或 validator。

### 3.2 字段常量边界

在 `index_series.py` 内部新增两个模块级 tuple：

1. `IDX_FACTOR_PRO_SOURCE_FIELDS`：方案文档第 5.3 节列出的 89 个源字段，顺序与源文档和实测结果一致。
2. `IDX_FACTOR_PRO_NUMERIC_FIELDS`：从前者排除 `ts_code`、`trade_date` 后的 87 个字段。

这两个 tuple 是 Definition 的组成部分，不是第二份独立模型事实。raw ORM 和 view ORM 必须通过 `get_dataset_definition("idx_factor_pro").source.source_fields` 读取同一字段集合，和当前 `stk_factor_pro` 一致。Alembic 因需要稳定 DDL，可有自己的静态列清单；测试必须逐列校验 Definition、两个 ORM、迁移 view 的字段集合一致。

## 4. 时间、unit 与请求参数

### 4.1 用户意图到源请求的时序

```mermaid
sequenceDiagram
    participant O as "Ops 手动或自动任务"
    participant R as "DatasetActionResolver"
    participant P as "DatasetUnitPlanner"
    participant B as "_idx_factor_pro_params"
    participant S as "DatasetSourceClient"
    participant T as "Tushare idx_factor_pro"
    participant N as "DatasetNormalizer"
    participant W as "DatasetWriter"
    participant D as "raw_tushare.idx_factor_pro"
    participant V as "core_serving.index_factor_pro view"

    O->>R: "time_input(point/range), 无 filters"
    R->>P: "ValidatedDatasetActionRequest + Definition"
    P->>P: "point 保留一天；range 查询交易日历并按 every_open_day 展开"
    P->>B: "每个 anchor trade_date"
    B-->>P: "{trade_date: YYYYMMDD}"
    P-->>R: "DatasetExecutionPlan units"
    R-->>S: "执行单个 unit"
    loop "offset=0, 8000, 16000 ..."
        S->>T: "trade_date + offset + limit; fields=89 字段"
        T-->>S: "本页 rows"
    end
    S->>N: "该 unit 的全部 rows"
    N->>W: "日期/数值已归一化的 batch"
    W->>D: "按 (ts_code, trade_date) upsert"
    D-->>V: "view 直接读取，无复制写入"
```

### 4.2 point

输入：

```json
{
  "time_input": {
    "mode": "point",
    "trade_date": "2026-07-31"
  },
  "filters": {}
}
```

计划结果：

```text
run_profile = point_incremental
unit_count = 1
unit.trade_date = 2026-07-31
unit.request_params = {"trade_date": "20260731"}
```

### 4.3 range

输入：

```json
{
  "time_input": {
    "mode": "range",
    "start_date": "2026-07-01",
    "end_date": "2026-07-31"
  },
  "filters": {}
}
```

`DatasetUnitPlanner._resolve_anchors()` 调用交易日历，取得该区间全部开市日。每个开市日独立生成一个 unit，例如 23 个交易日就是 23 个 unit。每个 unit 的 request builder 都只输出一个 `trade_date`；绝不把 `start_date/end_date` 直接传给源端。

### 4.4 专用 request builder

新增位置：`src/foundation/ingestion/request_builders.py`。

```python
def _idx_factor_pro_params(
    request: ValidatedDatasetActionRequest,
    anchor: date | None,
    values: dict[str, Any],
) -> dict[str, Any]:
    if anchor is None:
        raise IngestionPlanningError(...)
    return {"trade_date": anchor.strftime("%Y%m%d")}
```

实现要求：

1. 不读取、不过滤 `values["ts_code"]`，因为 Definition 没有这个输入。
2. 不接受或生成 `start_date/end_date`。
3. 不生成 `limit/offset/fields`；三者分别属于 source client 分页和 Definition source 字段白名单。
4. 缺 anchor 使用当前项目已有的 planning error 写法与 codebook；若现有可复用 error code 不够，才新增 codebook 项和测试。

## 5. 表、ORM、DAO 与迁移

### 5.1 Raw 表

新 relation：`raw_tushare.idx_factor_pro`。

| 内容 | 定义 |
| --- | --- |
| 主键 | `(ts_code, trade_date)` |
| 源字段 | 第 5.3 节的 89 列，列名不改名 |
| 标识列 | `ts_code VARCHAR(16) NOT NULL`、`trade_date DATE NOT NULL` |
| 数值列 | 其余 87 列均为 `DOUBLE PRECISION` / SQLAlchemy `Float(53)`，可空 |
| 内部审计列 | `api_name VARCHAR(32) NOT NULL DEFAULT 'idx_factor_pro'`、`fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()`、`raw_payload TEXT NULL` |
| 物理索引 | 仅 `idx_raw_tushare_idx_factor_pro_trade_date (trade_date)` |

主键已有 `(ts_code, trade_date)` B-tree。不得额外创建同顺序的 `ts_code, trade_date` 重复索引。

### 5.2 Serving view

新 relation：`core_serving.index_factor_pro`，普通 view，不是表。

```sql
CREATE VIEW core_serving.index_factor_pro AS
SELECT
    <89 个源字段，按 Definition source_fields 顺序显式列出>,
    'tushare'::varchar(32) AS source,
    fetched_at AS created_at,
    fetched_at AS updated_at
FROM raw_tushare.idx_factor_pro;
```

view 不包含 `api_name` 和 `raw_payload`，这两个字段只用于 raw 源端审计。view 上不创建伪索引；PostgreSQL 普通 view 不存储数据。查询优化依赖 raw 表主键与 `trade_date` 索引。

### 5.3 89 个源字段

以下顺序同时是 `source_fields`、raw/view 列顺序和迁移字段对账基准：

```text
ts_code, trade_date, open, high, low, close, pre_close, change, pct_change, vol, amount,
asi_bfq, asit_bfq, atr_bfq, bbi_bfq, bias1_bfq, bias2_bfq, bias3_bfq,
boll_lower_bfq, boll_mid_bfq, boll_upper_bfq, brar_ar_bfq, brar_br_bfq, cci_bfq,
cr_bfq, dfma_dif_bfq, dfma_difma_bfq, dmi_adx_bfq, dmi_adxr_bfq, dmi_mdi_bfq,
dmi_pdi_bfq, downdays, updays, dpo_bfq, madpo_bfq, ema_bfq_10, ema_bfq_20,
ema_bfq_250, ema_bfq_30, ema_bfq_5, ema_bfq_60, ema_bfq_90, emv_bfq, maemv_bfq,
expma_12_bfq, expma_50_bfq, kdj_bfq, kdj_d_bfq, kdj_k_bfq, ktn_down_bfq,
ktn_mid_bfq, ktn_upper_bfq, lowdays, topdays, ma_bfq_10, ma_bfq_20, ma_bfq_250,
ma_bfq_30, ma_bfq_5, ma_bfq_60, ma_bfq_90, macd_bfq, macd_dea_bfq, macd_dif_bfq,
mass_bfq, ma_mass_bfq, mfi_bfq, mtm_bfq, mtmma_bfq, obv_bfq, psy_bfq, psyma_bfq,
roc_bfq, maroc_bfq, rsi_bfq_12, rsi_bfq_24, rsi_bfq_6, taq_down_bfq, taq_mid_bfq,
taq_up_bfq, trix_bfq, trma_bfq, vr_bfq, wr_bfq, wr1_bfq, xsii_td1_bfq,
xsii_td2_bfq, xsii_td3_bfq, xsii_td4_bfq
```

`change`、`pct_change`、`downdays`、`updays` 等也属于源端返回字段，不能因为不是传统技术指标而漏列。

### 5.4 ORM 文件

新增：

1. `src/foundation/models/raw/raw_idx_factor_pro.py`
2. `src/foundation/models/core/index_factor_pro.py`

两个模型都从 `get_dataset_definition("idx_factor_pro").source.source_fields` 派生 87 个数值列，避免把字段集在 Python 代码里复制第三份。

| 模型 | schema / relation | 特殊字段 |
| --- | --- | --- |
| `RawIdxFactorPro` | `raw_tushare.idx_factor_pro` | raw 的三列内部审计字段；一个 `trade_date` 索引。 |
| `IndexFactorPro` | `core_serving.index_factor_pro` | `TimestampMixin` 对应 view 的 `created_at/updated_at`，并定义 `source`。 |

`IndexFactorPro` 是查询/观测映射，不能被 writer 写入。它不声明物理 view 索引。

### 5.5 DAO 与模型注册

变更位置：

| 文件 | 精确改动 |
| --- | --- |
| `src/foundation/models/all_models.py` | 显式导入并导出 `RawIdxFactorPro`、`IndexFactorPro`。 |
| `src/foundation/dao/factory.py` | 导入两个 ORM；初始化 `raw_idx_factor_pro = GenericDAO(session, RawIdxFactorPro)` 和 `index_factor_pro = GenericDAO(session, IndexFactorPro)`。 |
| `src/foundation/models/table_model_registry.py` | 不改实现；包扫描会发现两个新模型，view 映射将使 freshness projection 找到 `core_serving.index_factor_pro.trade_date`。 |

不得新建专用 DAO：当前数据集只需要通用 upsert/查询行为，专用 DAO 会制造没有业务价值的第二套访问逻辑。

### 5.6 Alembic revision

新增一条 revision。创建前必须在真实开发分支运行 `uv run alembic heads`，新 revision 的 `down_revision` 只接该命令返回的真实唯一 head；不得按日期、文件名或本 LLD 猜测 revision。

升级顺序：

1. `CREATE SCHEMA IF NOT EXISTS raw_tushare` 与 `core_serving`。
2. 创建 `raw_tushare.idx_factor_pro`、主键、唯一的日期索引。
3. 显式列出 89 个源字段创建 `core_serving.index_factor_pro` view。

迁移不得查询、改写、删除任何既有 relation；`downgrade()` 仅能移除本 revision 新建的 view、索引和 raw 表，且不会在普通发布流程中执行。

## 6. 写入、事务与错误边界

### 6.1 Normalizer

`DatasetNormalizer` 复用：

1. `coerce_row()` 将 `trade_date=YYYYMMDD` 转 `date`。
2. 对 87 个数值字段执行当前通用数值转换。
3. `ts_code` 或 `trade_date` 缺失，按既有 `required_fields` reject 原因记录。
4. 无 row transform、无 index active pool 过滤、无数据集特判。

### 6.2 Writer

`DatasetWriter.write()` 根据 `write_path="raw_only_upsert"` 调用 `_write_raw_only_upsert()`：

1. 通过 `raw_dao_name="raw_idx_factor_pro"` 取得 raw DAO。
2. 按 raw 表主键 `(ts_code, trade_date)` 批量 upsert。
3. 返回给 TaskRun 的 `target_table` 仍为 `core_serving.index_factor_pro`，因为这是对外服务和 freshness 观测目标。
4. 不读取、不调用、不写入 `index_factor_pro` DAO。

### 6.3 事务边界

一个 unit 是一个交易日：该日所有分页先在内存中汇集、归一化，再由 writer 完成该日 raw upsert，并按 `commit_policy="unit"` 提交。

TaskRun、进度、freshness/snapshot 等 Ops 状态仍走各自隔离的状态写入链路。状态写入失败不得回滚已经提交的 raw 数据；本接入不改变该硬约束。

## 7. Ops、卡片与自动任务

### 7.1 Ops 展示目录

只改 `src/ops/catalog/dataset_catalog_views.py`：

```python
DatasetCatalogItem("idx_factor_pro", "index_market_data", 45)
```

这会把它放在“A股指数行情”中，顺序位于 `index_daily_basic`（40）和 `index_mins`（50）之间。该分组是 Ops 展示事实，不回写 `DatasetDefinition.domain`。

### 7.2 手动任务

`ManualActionQueryService` 从 Definition 的 `time_fields` 和 capability 构造 `/api/v1/ops/manual-actions` 返回值。因为只有 `trade_date/start_date/end_date`：

1. 页面显示“只处理一天”和“处理一个时间区间”。
2. 日期选择规则来自 `date_model.selection_rule()`，为交易日选择。
3. 不出现证券代码输入框。
4. 提交仍是 TaskRun 意图；页面不发送 source 参数、分页字段或 89 字段清单。

不需要修改 `frontend/src/pages/ops-v21-task-manual-tab.tsx`。该页面已经按 API 返回的 `time_form/filters` 渲染。

### 7.3 运营自动任务

`schedule_enabled=True` 让 `OpsCatalogQueryService` 的 dataset action catalog 标记为可配置，从而使现有自动任务页可选该动作。

首期不新增 schedule 记录。运营在页面创建 schedule 后，`OperationsScheduleService` 仅保存时间意图和空 filters；实际日期仍由 `DatasetActionResolver` 归一化。不得为本数据集添加 calendar policy、固定日期、`ts_code` 或其他源接口参数。

本数据集增加一个**条件特例** `remote_idx_factor_pro_ready`。这不是新 schedule policy，也不改变 date model：它只决定自动任务何时把“当天”的 point 意图提交给 TaskRun。

### 7.4 源站就绪探测 LLD（已确认）

#### 条件与绑定

新增 `src/ops/services/idx_factor_pro_remote_probe_service.py`，定义：

```python
IDX_FACTOR_PRO_REMOTE_READY_CONDITION = "remote_idx_factor_pro_ready"
IDX_FACTOR_PRO_REMOTE_READY_LABEL = "源站已有指数技术因子"
IDX_FACTOR_PRO_ACTION_KEY = "idx_factor_pro.maintain"
IDX_FACTOR_PRO_DATASET_KEY = "idx_factor_pro"
IDX_FACTOR_PRO_REMOTE_PROBE_FIELDS = ("ts_code", "trade_date")
```

`ScheduleProbeBindingService` 将该条件加入 `REMOTE_SOURCE_PROBE_CONDITIONS` 与 `SUPPORTED_PROBE_CONDITIONS`，并新增专用校验：

1. 只允许 `target_type="dataset_action"`、`target_key="idx_factor_pro.maintain"`。
2. 只允许 `trigger_mode="probe"` 或 `"schedule_probe_fallback"`。
3. `params_json.filters` 必须为空；不得传 `ts_code`、`source_key` 或其他未定义过滤条件。
4. 不允许 `calendar_policy`。
5. 不允许固定 `trade_date`、日期区间或其他固定时间输入；探测目标日只能来自交易日历。
6. 强制 `probe_interval_seconds >= 300` 且 `max_triggers_per_day == 1`。

#### 探测执行

`IdxFactorProRemoteReadinessProbeService.evaluate(session, rule, current)` 必须按如下顺序执行：

1. 用 `Asia/Shanghai` 的当前自然日查询 `TradeCalendarDAO.fetch_by_pk(exchange, business_date)`；日历缺失或 `is_open is not True` 时零次源端请求并返回 miss。
2. 把当天作为 `latest_open_date`，构造 `DatasetActionRequest(dataset_key="idx_factor_pro", action="maintain", time_input=point, filters={})`。
3. 调用 `DatasetActionResolver(session).build_plan(request)`；取唯一 unit 的 `request_params`，其唯一业务参数必须是 builder 生成的 `trade_date=YYYYMMDD`。
4. 仅为本次 probe 追加 `limit=1`、`offset=0`，并以 `IDX_FACTOR_PRO_REMOTE_PROBE_FIELDS` 调用 connector。`limit/offset/fields` 不保存到 TaskRun，不写回 Definition，也不暴露到自动任务页面。
5. 第一条返回记录同时满足 `trade_date == latest_open_date`、`ts_code` 非空时命中；空结果、日期不匹配或字段缺失为 miss。connector 源端异常由现有 runtime 记录为 probe error。两种非命中结果都不创建 TaskRun。

Probe payload 至少记录 `dataset_key`、`condition_type`、`business_date`、`latest_open_date`、`sample_request_count`（最多 1）、命中行的 `ts_code/trade_date` 与用户可读 message。它只进入 `ops.probe_run_log`；不得刷新 freshness、snapshot，不得写 raw/view 或其他业务表。

`ProbeRuntimeService` 需像现有远程条件一样完成四个接点：构造服务、`_evaluate_rule()` 分发、`_remote_source_probe_action_key()` 映射、标签和绑定错误文本。命中后现有 `_enqueue_on_match()` 把 `time_input` 固定为 `{mode: "point", trade_date: latest_open_date}`，filters 仍为空，`request_payload.run_scope="probe_triggered"`，`trigger_source="probe"`。纯 probe 不显示执行时间；`schedule_probe_fallback` 继续使用已有的当日有效 probe TaskRun 去重。

#### 自动任务页面

`frontend/src/pages/ops-v21-task-auto-tab.tsx` 只在 `idx_factor_pro.maintain` 被选中时显示“源站已有指数技术因子”。本数据集选择该条件时，不显示本地 `freshness_latest_open`，避免把本地数据是否新鲜误当成源站是否已发布。

说明文案应直接表达：系统会检查源站是否已返回当天的一条指数技术因子；返回后创建正式全量维护任务。不得说成“已验证源端全部指数齐备”。页面不增加样本代码、`ts_code` 或额外维护参数输入。

### 7.5 既有 workflow 的负向门禁

`src/ops/action_catalog.py` 的 `WORKFLOW_DEFINITION_REGISTRY` 不修改。测试必须汇集全部 workflow 的 `step.dataset_key`，断言 `idx_factor_pro` 不在集合中，特别是不在：

1. `daily_market_close_maintenance`。
2. `index_extension_maintenance`。
3. `index_kline_maintenance_pipeline`。

这条门禁防止“Definition 可配置自动任务”被误解为“应自动塞入现有批量工作流”。

## 8. Freshness 与日期完整性

### 8.1 Freshness

在 `src/foundation/datasets/freshness_policies.py` 的集中映射增加：

```python
"idx_factor_pro": CONTINUOUS_OPEN_DAY
```

`DatasetDefinition` 只引用这一集中 policy；`build_dataset_freshness_projection()` 每次从 Definition 读取 `target_table=core_serving.index_factor_pro` 和 `observed_field=trade_date`。禁止在 snapshot、查询层或前端创建 policy 副本或自行拼接“最近同步”。

### 8.2 日期完整性

Definition：

```text
audit_applicable=True
completeness.scope=date_bucket
```

`DateCompletenessRunCommandService` 会把非 `date_subject_matrix` scope 投影为 `audit_scope="date_bucket"`。`DateCompletenessAuditExecutor` 用交易日历生成期望开市日集合，再对 `core_serving.index_factor_pro.trade_date` 做 `distinct` 查询。

结论：它只能回答“某个交易日是否至少有一条指数技术因子”，不能回答“该交易日每个指数是否齐备”。这是本期已确认的源端全量批次 freshness 语义，不新增指数激活池矩阵审计。

## 9. 精确代码改动清单

| 文件 | 改动 | 原因 | 不改的相邻代码 |
| --- | --- | --- | --- |
| `src/foundation/datasets/definitions/index_series.py` | 新增字段 tuple 与 `idx_factor_pro` Definition | 数据集唯一事实源 | 不改 `index_daily` 请求池、`index_daily_basic` 写入路径。 |
| `src/foundation/datasets/freshness_policies.py` | 登记 `continuous_open_day` | freshness policy 集中定义 | 不改任何其他 dataset policy。 |
| `src/foundation/ingestion/request_builders.py` | 新增 `_idx_factor_pro_params` | 单日 source 参数格式化 | 不改 generic planner 或任何已有 builder。 |
| `src/foundation/models/raw/raw_idx_factor_pro.py` | 新 raw ORM | raw 表映射 | 不改已有 raw model。 |
| `src/foundation/models/core/index_factor_pro.py` | 新 view ORM | query/freshness 映射 | 不写入 view。 |
| `src/foundation/models/all_models.py` | 显式导入/导出模型 | 全模型注册完整性 | 不改 app model registry 架构。 |
| `src/foundation/dao/factory.py` | 新增两个 GenericDAO 属性 | writer 与观测模型可解析 | 不加编排/事务逻辑。 |
| `alembic/versions/<new>_add_idx_factor_pro_dataset.py` | 新 raw 表、日期索引、view | schema 落地 | 不改变既有 relation。 |
| `src/ops/catalog/dataset_catalog_views.py` | 新 catalog item | 必须显式配置 Ops 分组 | 不改 foundation domain。 |
| `src/ops/services/idx_factor_pro_remote_probe_service.py` | 新增该数据集专用源站探测服务 | 复用 Ops probe 框架，不向 Definition 添加隐藏 `ts_code` | 不写业务表、不读取激活池。 |
| `src/ops/services/schedule_probe_binding_service.py` | 注册和验证 `remote_idx_factor_pro_ready` | 只允许本数据集的 probe/fallback schedule | 不改变其他探测条件。 |
| `src/ops/services/operations_probe_runtime_service.py` | 接入条件分发与 TaskRun action 映射 | 命中后复用标准 TaskRun 创建 | 不改 worker/ingestion。 |
| `frontend/src/pages/ops-v21-task-auto-tab.tsx` | 条件可见性、文案与本地 freshness 选项限制 | 运营只配置窗口和频率，不配置源参数 | 不修改手动任务页面。 |
| `tests/**` | 新 Definition、resolver、source、normalizer、writer、Ops、migration/view 合同测试 | 为本 LLD 固定口径建门禁 | 不改非本数据集生产链路。 |
| `docs/datasets/idx-factor-pro-dataset-development.md` | 更新实施状态与验证结果 | 方案和实现一致 | 不改无关数据集文档。 |

## 10. 测试设计

### 10.1 Definition 与运行时注册

在 `tests/test_dataset_definition_registry.py`、`tests/test_fields_constants.py`、`tests/architecture/test_dataset_runtime_registry_guardrails.py` 增加断言：

1. `idx_factor_pro` 注册在 `index_series`，并加入对应 expected domain key 集合。
2. source API、89 个字段、日期模型、`no_pool`、generic builder、`offset_limit/8000`、raw-only view 存储、`continuous_open_day`、`date_bucket` 都精确匹配。
3. `source_fields` 首两列是 `ts_code/trade_date`，字段数量为 89，且末尾 `xsii_td4_bfq` 不丢失。
4. runtime registry 与 Definition key 集合仍完全相等。

### 10.2 Resolver 与 request builder

在 `tests/test_dataset_action_resolver.py`：

1. point `2026-04-24` 生成 1 个 `{"trade_date": "20260424"}` unit。
2. range 在 mock 交易日历中只展开开市日；不得生成自然日、`ts_code` 或 `start_date/end_date` source 参数。
3. request 带 `filters={"ts_code": "000300.SH"}` 必须被 validator 拒绝为未定义参数。
4. planner 不能访问 `index_series_active`、`index_basic` 或其他对象池 DAO。
5. builder 缺 anchor 必须产生明确 planning error。

### 10.3 Source client 与 normalizer

在 `tests/test_dataset_source_client.py`：

1. RecordingConnector 接收 `api_name="idx_factor_pro"`、Definition 的完整 89 字段、`offset=0, limit=8000`。
2. Fake connector 第一页返回恰好 8,000 行、第二页不足 8,000 行时，断言两次调用及 offset 递进。

新增或在相邻测试文件中覆盖 normalizer：

1. `trade_date="20260424"` 转为 `date(2026, 4, 24)`。
2. `open`、`pct_change` 等数值字段可归一化。
3. 缺 `ts_code` 或 `trade_date` 有明确 rejection reason 与样本。
4. 不触发 row transform。

### 10.4 Writer、模型与迁移/view 合同

新增 `tests/test_dataset_writer_idx_factor_pro.py`，沿用 `stk_factor_pro` 的禁止 serving DAO 写入模式：

1. raw DAO 收到完整 normalized batch。
2. view DAO 被替换成抛错 stub，调用次数必须为 0。
3. `WriteResult.target_table == "core_serving.index_factor_pro"`。

在 `tests/test_extended_models.py` 或专用 schema contract 测试：

1. raw ORM 主键为 `ts_code, trade_date`，仅有日期索引。
2. raw ORM 和 view ORM 都覆盖 89 个源字段。
3. raw ORM 有三个内部审计字段，view ORM 有 `source/created_at/updated_at`。
4. Alembic SQL / 最小迁移数据库验证证明 view 字段集合与 raw 源字段一致，且 view 指向 `raw_tushare.idx_factor_pro`。

### 10.5 Ops 与 workflow

在 `tests/test_ops_action_catalog.py`、`tests/web/test_ops_catalog_api.py`、`tests/web/test_ops_manual_actions_api.py` 或其最贴近的现有测试：

1. catalog group 为 `index_market_data/A股指数行情`，order 为 45。
2. manual action 存在，支持 point/range，只有时间字段，没有 `ts_code` filter。
3. schedule action 可配置。
4. 所有 workflow 的 step 集合都不含 `idx_factor_pro`。
5. `remote_idx_factor_pro_ready` 只绑定 `idx_factor_pro.maintain`；拒绝 workflow、固定日期、calendar policy、非空 filters、其他数据集 action，以及不满足的间隔/每日触发上限。
6. 当前日期非开市日或交易日历缺失时，探测服务零次请求源端且不创建 TaskRun。
7. 当 source 返回目标日 `ts_code/trade_date` 时，探测命中并创建一个空 filters 的 point TaskRun；空结果、日期不匹配、字段缺失和 connector 异常时只写 ProbeRunLog。
8. `schedule_probe_fallback` 在同日已有有效 probe TaskRun 时不再创建 scheduled TaskRun；既有 `index_daily`、`index_mins`、`stk_mins`、`kpl_list` 探测回归不变。
9. 自动任务页仅在 `idx_factor_pro.maintain` 显示新条件；选择该条件时不提供 `freshness_latest_open`，纯 probe/兜底时间字段语义保持现有约定。

### 10.6 实施完成前的真实验收

代码测试不能替代真实源端验证。发布到开发/生产环境后，只运行最近一个已开市日的单日维护，并记录：

| 指标 | 验收规则 |
| --- | --- |
| `fetched` | 等于源端实际拉取行数。 |
| `normalized` | 等于 fetched，除非有可解释 reject。 |
| `written` | 等于 normalized 的幂等写入结果。 |
| `rejected` | 必须为 0；非 0 时记录 reason code、样本与根因。 |
| raw 行数 | 指定交易日 raw 行数等于 written 后该日全量结果。 |
| view 行数 | 同一交易日 `core_serving` view 行数等于 raw。 |
| 字段集合 | raw 89 源字段和 view 89 源字段逐列一致。 |
| Ops 卡片 | 最近业务日期、freshness、手动任务详情与实际结果一致。 |

## 11. 开发顺序与停止条件

1. 开发前重新读取根、`foundation`、`datasets`、`ingestion`、`models`、`dao`、`ops/catalog`、前端页面和 docs 的逐级 `AGENTS.md`，并重新执行 CodeGraph 影响面确认。
2. 先加 Definition、builder、模型、DAO、catalog、freshness 映射和所有测试，再创建 migration；migration 前重新核验真实 Alembic head。
3. 本地运行 Definition/resolver/source/writer/Ops/architecture 测试、`goldenshare ingestion-lint-definitions`、`python3 scripts/check_docs_integrity.py`。
4. 迁移和最小真实同步只在用户明确授权的部署阶段执行；不得在开发过程中连接生产库做写入、更不得清表。

以下任何一项发生时必须停止并重新评审，不能靠兼容或补丁继续：

1. Tushare 单日返回超过 8,000 行且分页行为与实测不一致。
2. 89 字段任意一列在 source、Definition、ORM、迁移或 view 之间不一致。
3. 实测表明 `trade_date + limit=1` 无法代表源端当日发布，且必须新增隐藏 `ts_code` 或对象池依赖才能判断。
4. 自动任务 capability 意外要求修改 workflow 或除探测条件外的前端特例。
5. 新 revision 没有真实唯一 Alembic head 可接。

## 12. 验收对账

| 已确认口径 | LLD 对应实现/门禁 |
| --- | --- |
| 只支持手动维护和运营自动任务配置 | `manual_enabled=True`、`schedule_enabled=True`，manual/catalog API 测试。 |
| 不进入既有每日工作流 | `WORKFLOW_DEFINITION_REGISTRY` 不改，workflow 负向测试。 |
| 按交易日同步源站全量 | `trade_open_day/every_open_day`、generic planner、仅 `trade_date` builder。 |
| 不按指数代码逐只请求 | 无 `ts_code` input/filter，`no_pool`，planner DAO 禁用测试。 |
| 所有源字段落库 | 89 列 Definition/ORM/migration/view 对账测试。 |
| raw 是事实层，serving 只读直出 | `raw_only_upsert` writer 禁止 serving DAO 写入测试，普通 view DDL。 |
| 新鲜度不造第二份规则 | `freshness_policies.py` 集中登记，Definition 投影读取。 |
| 源站就绪后再自动维护 | `remote_idx_factor_pro_ready` 仅在当日开市日命中一条目标日期记录后创建 point TaskRun；miss/error 不创建。 |
| 不改变其他执行链路 | 不改通用 ingestion、TaskRun 三表模型、既有 workflow 或无关前端页面；仅增加本数据集的 Ops 探测条件，架构回归测试。 |

## 13. 建议验证命令

```bash
uv run ruff check \
  src/foundation/datasets/definitions/index_series.py \
  src/foundation/datasets/freshness_policies.py \
  src/foundation/ingestion/request_builders.py \
  src/foundation/models/raw/raw_idx_factor_pro.py \
  src/foundation/models/core/index_factor_pro.py \
  src/foundation/models/all_models.py \
  src/foundation/dao/factory.py \
  src/ops/catalog/dataset_catalog_views.py \
  src/ops/services/idx_factor_pro_remote_probe_service.py \
  src/ops/services/schedule_probe_binding_service.py \
  src/ops/services/operations_probe_runtime_service.py \
  tests

uv run pytest -q \
  tests/test_dataset_definition_registry.py \
  tests/test_fields_constants.py \
  tests/test_dataset_action_resolver.py \
  tests/test_dataset_source_client.py \
  tests/test_dataset_writer_idx_factor_pro.py \
  tests/test_extended_models.py \
  tests/test_ops_action_catalog.py \
  tests/web/test_ops_catalog_api.py \
  tests/web/test_ops_manual_actions_api.py \
  tests/web/test_ops_probe_api.py \
  tests/web/test_ops_schedule_api.py \
  tests/architecture/test_dataset_runtime_registry_guardrails.py \
  tests/architecture/test_ops_dataset_catalog_view.py \
  tests/architecture/test_subsystem_dependency_matrix.py

uv run goldenshare ingestion-lint-definitions
(cd frontend && npm run test -- ops-v21-task-auto-tab)
python3 scripts/check_docs_integrity.py
```

通过代码门禁后，才能进入“用户授权的迁移与单日真实同步验收”阶段。
