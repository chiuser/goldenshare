# ETF 历史分钟行情数据集 LLD v1

状态：本地代码、迁移文件和定向测试已完成；尚未部署、执行迁移、初始化 `etf_mins` 活跃池或同步生产数据。

创建日期：2026-08-24
最近更新：2026-08-25

关联文档：

- [ETF 历史分钟行情数据集接入方案](/Users/congming/github/goldenshare/docs/datasets/etf-mins-dataset-development.md)
- [数据集开发模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)
- [Tushare 0387 ETF 历史分钟行情](/Users/congming/github/goldenshare/docs/sources/tushare/ETF专题/0387_ETF历史分钟行情.md)
- [ETF 活跃池 LLD](/Users/congming/github/goldenshare/docs/architecture/etf-active-pool-low-level-design-v1.md)

---

## 1. 编码目标与边界

### 1.1 唯一执行链

```text
Manual action / Dataset schedule
  -> DatasetActionRequest(etf_mins.maintain)
  -> DatasetActionResolver
  -> DatasetExecutionPlan
  -> PlanUnit(ts_code, freq, start_date, end_date)
  -> DatasetSourceClient(etf_mins, offset pagination)
  -> DatasetNormalizer
  -> DatasetWriter(raw_only_upsert)
  -> COMMIT raw_tushare.etf_minute_bar
  -> unit completed
```

每个 unit 拉完全部分页后执行一次幂等写入和业务事务提交。

### 1.2 实施边界

本轮只新增标准数据集接入所需的 Definition、planner、request builder、source 校验、normalizer、writer 质量门禁、ORM、DAO、迁移、Ops catalog 和测试。以下核心结构无需修改：

- `src/foundation/ingestion/execution_plan.py`
- `src/foundation/ingestion/resolver.py`
- `src/foundation/ingestion/executor.py`
- TaskRun plan snapshot 结构
- workflow 定义

现有 `DatasetDefinition -> PlanUnit -> raw_only_upsert -> unit commit` 已能完整表达本数据集。

---

## 2. 当前代码事实与复用结论

| 环节 | 当前事实 | ETF 实现方式 |
| --- | --- | --- |
| Definition | `src/foundation/datasets/definitions/market_fund.py` 管理 ETF/基金数据集 | 在该文件新增 `etf_mins`。 |
| 股票分钟参考 | `market_equity.py` 中 `stk_mins` 已支持 point/range、频率多选、raw-only | 复用产品和执行语义，不复制股票池或字段精度处理。 |
| unit planner | `_build_stk_mins_units` 按代码 × 频率生成整体时间窗口 unit | 新增 ETF 专用 builder，池来源改为 `ops.etf_series_active`，并按频率切割 range。 |
| request builder | `_stk_mins_params` 已能映射代码、频率、起止时间 | 新增 `_etf_mins_params`，避免 API 身份混淆。 |
| pagination | `DatasetSourceClient` 已支持 `offset_limit` 和累计行数上限 | 配置 `page_limit=8000`、`max_source_rows_per_unit=24000`；窗口按一到两页测算，第三页作为安全余量。 |
| writer | `raw_only_upsert` 已存在 | 直接复用，不新增 write path。 |
| DAO | `GenericDAO` 可按 ORM 主键 upsert | 新增 raw ORM 并注册到 `DAOFactory`。 |
| ETF pool | `EtfSeriesActiveDAO.list_active_codes(resource)` 已存在 | 读取 `resource='etf_mins'`。 |
| freshness | `definitions/_builder.py` 强制调用 `get_freshness_policy()` | 在集中映射增加 `etf_mins`，否则 Definition 无法加载。 |
| completeness | `audit_applicable=false` 时 builder 要求 `scope=not_applicable` | 在定义中显式声明，防止文档与默认行为脱节。 |
| runtime registry | `DATASET_RUNTIME_REGISTRY` 从 Definition registry 自动生成 | 不增加手工注册项，只做 registry/linter 回归。 |
| manual / schedule | Definition contract 自动生成通用表单和排程能力 | 不新增专属页面。 |
| 自动日期 | `TaskRunDispatcher._prepare_dataset_action_request()` 会补全无固定日期的 point 请求 | 沿用最近开市日规则，不在前端计算。 |
| cards / audit | projection、freshness、snapshot、date completeness 都读取 Definition | 只补 Definition 事实和现有消费者测试。 |

不能直接照抄 `stk_mins` 的两个细节：

1. `stk_mins` 把 `freq` 转成整数，ETF raw 表必须保留 Tushare 原始字符串。
2. `stk_mins` 对 OHLC 做两位小数处理，ETF raw 表不得做该精度裁剪。

---

## 3. 硬需求追溯

| ID | 硬需求 | 影响层 / 消费者 | 后端权威约束 | 前端表现 / 直接消费者 | 实现文件 | 正向测试 | 反向测试 | 真实验证 | 阶段 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `ETFM-001` | API 只能是 `etf_mins` | source / connector | Definition 固定 `api_name=etf_mins` | 数据源页只展示该 API 事实 | `market_fund.py`、`source_client.py` | connector payload 调用 `etf_mins` | 不得调用 `stk_mins` | 最小真实同步记录请求 API | M1/M3/M5 | 本地已实现，待部署验收 |
| `ETFM-002` | 只支持五种源端频率 | input / planner / normalizer | enum 与返回值校验固定五种值 | 手动、自动任务使用通用多选 | `market_fund.py`、`unit_planner.py`、`row_transforms.py` | 五种频率均可生成 unit | 其他值返回结构化错误 | 五频率最小任务 | M1/M3/M5 | 本地已实现，待部署验收 |
| `ETFM-003` | 所有行直接来自 Tushare | source / raw writer | 只接受 connector 返回行，不生成行情 | 无额外加工控件 | `source_client.py`、`writer.py` | 源端唯一键与 raw 唯一键一致 | 返回频率错配时 unit 失败 | source/normalized/written key 对账 | M3/M5 | 本地已实现，待部署验收 |
| `ETFM-004` | 只有一个 raw 物理表 | storage / DAO / cards | storage 只声明 `raw_tushare.etf_minute_bar` | 页面展示 raw-only，不显示虚假 serving | migration、raw ORM、`market_fund.py` | raw-only upsert 成功 | 迁移不得创建第二张业务表 | PostgreSQL relation 清单 | M2/M5 | 本地已实现，待迁移验收 |
| `ETFM-005` | 所有 relation 在 HDD | PostgreSQL storage | tablespace 缺失时迁移失败；预建 `2009-01` 至 `2037-12` 月分区和 HDD 默认分区 | 不新增页面配置 | migration | 父表、分区、索引均为 `gs_raw_cold_hdd` | 禁止静默落 SSD 或运行时建分区 | `pg_class/pg_tablespace/pg_inherits` 对账 | M2/M5 | 迁移文件已实现，待执行验收 |
| `ETFM-006` | point/range 使用标准时间输入并按频率切窗 | resolver / planner / builder | point 当日窗口；range 按 `2/12/36/72/120` 个自然月切割 | 通用单日 / 区间控件 | `unit_planner.py`、`request_builders.py` | 两种模式参数与窗口边界正确 | 窗口不得重叠、遗漏或超出输入范围，none 被拒绝 | 真实 point/range 请求 | M1/M3/M5 | 本地已实现，待部署验收 |
| `ETFM-007` | 对象池使用独立 `etf_mins` resource | planner / seed / review center | 全池和显式代码都只读 `ops.etf_series_active(resource='etf_mins')` | 复用现有 ETF 活跃池审查能力 | `unit_planner.py`、`etf_series_active_seed_service.py` | 1,395 个代码稳定生成 unit，池内显式代码可执行 | 不读取 `fund_daily/etf_rt_daily`，拒绝 `.OF` 和池外显式代码 | seed dry-run 数量与样本 | M1/M5 | 本地已实现，待 seed 验收 |
| `ETFM-008` | 支持手动和独立自动任务，不进 workflow | Ops / TaskRun / frontend | capabilities 开启 manual/schedule | 通用手动页和自动任务页可配置 | `market_fund.py`、既有 Ops/前端消费者 | 两类任务均生成同一 action plan | workflow registry 无 `etf_mins` | 实际页面路径与 TaskRun | M1/M4/M5 | 本地已实现，待页面验收 |
| `ETFM-009` | 单页 8,000，窗口按一到两页测算、最多接纳三个数据页，endpoint 限速 500/min | source / limiter | `page_limit=8000`、`max_source_rows_per_unit=24000` 与独立 limiter | 数据集详情展示分页事实 | `market_fund.py`、`source_client.py`、`tushare_client.py` | offset `0/8000/16000`、短页结束 | 超过 24,000 行立即失败，不得接纳第四个数据页或回退通用限速 | 分页唯一键集合、边界探测与 `source_rows_exceeded` 对账 | M3/M5 | 本地已实现，待真实同步验收 |
| `ETFM-010` | identity 重复或任意 reject 时 unit 失败 | normalizer / writer / TaskRun issue | DAO 前执行 fail-any policy | 任务详情显示原因和样本 | `normalizer.py`、`writer.py`、`codebook.py` | 干净批次正常提交 | 重复、冲突、任意 reject 均零写入并失败 | reject 样本对账 | M3/M5 | 本地已实现，待真实同步验收 |
| `ETFM-011` | 每个 unit 一次业务提交 | source pagination / writer | 页只负责拉取，完整 unit 才写入提交 | 页面只显示已提交行数 | `source_client.py`、`executor.py`、`writer.py` | 多页 unit 一次提交 | 不得逐页提交 | TaskRun 与目标表行数对账 | M3/M5 | 本地已实现，待真实同步验收 |
| `ETFM-012` | raw 保留源端价格精度 | normalizer / ORM | ETF transform 不做两位小数裁剪 | 页面无精度编辑能力 | `row_transforms.py`、raw ORM | 多位小数样本原样保存 | 不得复用股票分钟价格裁剪 | 源行与 raw 数值抽样 | M3/M5 | 本地已实现，待真实同步验收 |

---

## 4. DatasetDefinition

目标文件：

```text
src/foundation/datasets/definitions/market_fund.py
```

目标定义：

```python
{
    "identity": {
        "dataset_key": "etf_mins",
        "display_name": "ETF 历史分钟行情",
        "description": "维护 Tushare ETF 原生历史分钟行情。",
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
        "api_name": "etf_mins",
        "source_fields": (
            "ts_code", "freq", "trade_time",
            "open", "close", "high", "low",
            "vol", "amount", "vwap", "exchange",
        ),
        "source_doc_id": "tushare.etf_mins",
        "request_builder_key": "_etf_mins_params",
        "base_params": {},
        "release_policy": "same_day",
    },
    "date_model": {
        "date_axis": "trade_open_day",
        "bucket_rule": "every_open_day",
        "window_mode": "point_or_range",
        "input_shape": "trade_date_or_start_end",
        "observed_field": "trade_time",
        "audit_applicable": False,
        "not_applicable_reason": "minute completeness audit requires trading-session calendar",
    },
    "input_model": {
        "time_fields": (
            {
                "name": "trade_date",
                "field_type": "date",
                "required": False,
                "default": None,
                "enum_values": (),
                "multi_value": False,
                "display_name": "处理日期",
                "description": "交易日",
            },
            {
                "name": "start_date",
                "field_type": "date",
                "required": False,
                "default": None,
                "enum_values": (),
                "multi_value": False,
                "display_name": "开始日期",
                "description": "起始交易日",
            },
            {
                "name": "end_date",
                "field_type": "date",
                "required": False,
                "default": None,
                "enum_values": (),
                "multi_value": False,
                "display_name": "结束日期",
                "description": "结束交易日",
            },
        ),
        "filters": (
            {
                "name": "ts_code",
                "field_type": "string",
                "required": False,
                "default": None,
                "enum_values": (),
                "multi_value": False,
                "display_name": "ETF 代码",
                "description": "不填写时按 ETF 历史分钟激活池维护",
            },
            {
                "name": "freq",
                "field_type": "list",
                "required": True,
                "default": None,
                "enum_values": ("1min", "5min", "15min", "30min", "60min"),
                "multi_value": True,
                "display_name": "分钟周期",
                "description": "至少选择一个 Tushare 原生分钟周期",
            },
        ),
        "required_groups": (),
        "mutually_exclusive_groups": (),
        "dependencies": (),
    },
    "storage": {
        "raw_dao_name": "raw_etf_minute_bar",
        "core_dao_name": "raw_etf_minute_bar",
        "target_table": "raw_tushare.etf_minute_bar",
        "delivery_mode": "raw_collection",
        "layer_plan": "raw-only",
        "std_table": None,
        "serving_table": None,
        "raw_table": "raw_tushare.etf_minute_bar",
        "conflict_columns": ("ts_code", "freq", "trade_time"),
        "write_path": "raw_only_upsert",
    },
    "planning": {
        "universe_policy": "pool",
        "universe": {
            "request_field": "ts_code",
            "override_fields": ("ts_code",),
            "sources": ({"type": "ops_etf_series_active", "resource": "etf_mins"},),
        },
        "enum_fanout_fields": (),
        "enum_fanout_defaults": {},
        "pagination_policy": "offset_limit",
        "page_limit": 8000,
        "max_source_rows_per_unit": 24000,
        "chunk_size": None,
        "max_units_per_execution": None,
        "unit_builder_key": "build_etf_mins_units",
        "fetch_concurrency": 2,
        "page_processing_mode": "buffer_all",
    },
    "normalization": {
        "date_fields": (),
        "decimal_fields": (),
        "required_fields": ("ts_code", "freq", "trade_time"),
        "row_transform_name": "_etf_mins_row_transform",
    },
    "capabilities": {
        "actions": ({
            "action": "maintain",
            "manual_enabled": True,
            "schedule_enabled": True,
            "retry_enabled": True,
            "supported_time_modes": ("point", "range"),
        },),
    },
    "observability": {
        "progress_label": "etf_mins",
        "observed_field": "trade_time",
        "audit_applicable": False,
    },
    "quality": {
        "reject_policy": "fail_unit_on_any_rejection",
        "required_fields": ("ts_code", "freq", "trade_time"),
        "duplicate_key_policy": "allow",
        "batch_unique_key_fields": ("ts_code", "freq", "trade_time"),
        "source_multiplicity_policy": "reject",
        "empty_result_policy": "allow",
    },
    "transaction": {
        "commit_policy": "unit",
        "idempotent_write_required": True,
        "write_volume_assessment": "一个 unit 对应一个 ETF、一个源端频率和一个受控时间窗口；按一到两页测算，最多接纳三个数据页、24000 行，分页拉完后一次 upsert 与提交。",
    },
    "completeness": {
        "scope": "not_applicable",
    },
}
```

`build_definition()` 会无条件调用集中 freshness 映射，因此还必须在 `src/foundation/datasets/freshness_policies.py` 增加：

```python
"etf_mins": CONTINUOUS_OPEN_DAY
```

这里的 `audit_applicable=false` 和 `completeness.scope=not_applicable` 只表示普通日期完整性审计不适用于分钟表，不会关闭 point/range 时间输入，也不会把卡片 freshness 改成运行健康口径。

### 4.1 InputModel

时间字段与 `stk_mins` 保持一致；filters 固定为：

```python
(
    {
        "name": "ts_code",
        "field_type": "string",
        "required": False,
        "default": None,
        "multi_value": False,
        "display_name": "ETF 代码",
        "description": "不填写时按 ETF 历史分钟激活池维护",
    },
    {
        "name": "freq",
        "field_type": "list",
        "required": True,
        "default": None,
        "enum_values": ("1min", "5min", "15min", "30min", "60min"),
        "multi_value": True,
        "display_name": "分钟周期",
        "description": "至少选择一个 Tushare 原生分钟周期",
    },
)
```

不设置默认全选。和生产 `stk_mins` 一致，页面必须要求运营明确选择。字段完全缺失时输入校验返回 `required_param_missing`；显式提交空列表时返回 `empty_not_allowed`。planner 仍保留空值 fail-closed 门禁，但正常请求会先被通用输入校验拦截。

---

## 5. Unit Planner

目标文件：

```text
src/foundation/ingestion/unit_planner.py
```

新增：

```text
ETF_MINS_RESOURCE = "etf_mins"
ETF_MINS_RANGE_WINDOW_MONTHS = {
    "1min": 2,
    "5min": 12,
    "15min": 36,
    "30min": 72,
    "60min": 120,
}
ETF_MINS_MAX_SOURCE_ROWS_PER_UNIT = 24000
_split_calendar_month_span_windows(...)
_resolve_etf_mins_targets(...)
_build_etf_mins_units(...)
UNIT_BUILDERS["build_etf_mins_units"]
```

### 5.1 频率校验

```python
allowed_freqs = ("1min", "5min", "15min", "30min", "60min")
raw_freqs = split_multi_values(request.params.get("freq"))
```

规则：

1. 空列表直接失败。
2. 包含五种允许值之外的任何值直接失败。
3. 去重后按 `allowed_freqs` 固定顺序生成 unit。
4. planner 不自动追加运营没有选择的频率。

### 5.2 ETF 目标解析

Definition 的 universe 必须精确为：

```text
request_field=ts_code
override_fields=(ts_code,)
source=(ops_etf_series_active, etf_mins)
```

处理方式：

- `ts_code` 为空：读取并排序 `dao.etf_series_active.list_active_codes("etf_mins")`。
- `ts_code` 显式填写：标准化为大写，校验 `.SH/.SZ`，再确认其属于 `dao.etf_series_active.list_active_codes("etf_mins")`；池外代码规划失败，池内代码只生成该 ETF 的 unit。
- 池为空：失败并提示先初始化 `etf_mins` ETF 活跃池。
- 池内出现 `.OF` 或非 `.SH/.SZ`：规划失败，不进入源请求。

### 5.3 时间切窗

以下逻辑必须在每个已选择的 `freq` 循环内执行；不同频率使用各自固定的月跨度，不能先按用户完整 range 生成一套公共窗口再复用。

```python
if request.trade_date is not None:
    date_windows = ((request.trade_date, request.trade_date),)
    unit_trade_date = request.trade_date
elif request.start_date is not None and request.end_date is not None:
    date_windows = _split_calendar_month_span_windows(
        request.start_date,
        request.end_date,
        months=ETF_MINS_RANGE_WINDOW_MONTHS[freq],
    )
    unit_trade_date = None
else:
    raise planning_error("range_required", ...)

for window_index, (window_start_date, window_end_date) in enumerate(
    date_windows,
    start=1,
):
    window_start = f"{window_start_date.isoformat()} 09:00:00"
    window_end = f"{window_end_date.isoformat()} 19:00:00"
    # 使用当前 freq、当前窗口生成一个 PlanUnitSnapshot。
```

`_split_calendar_month_span_windows()` 是 ETF 分钟专用的确定性 helper，不修改现有 `_split_calendar_month_windows()`，避免影响其当前消费者。算法要求：

1. 第一个窗口从用户 `start_date` 开始，不回退到月初。
2. 以当前窗口所在自然月为第一个月，向后覆盖该频率声明的月数。
3. 窗口结束取“跨度最后一个自然月的月末”和用户 `end_date` 的较早值。
4. 下一个窗口从前一窗口结束日期的下一自然日开始。
5. 输出必须按日期升序，覆盖集合精确等于用户输入的闭区间，不能重叠、遗漏或越界。
6. 跨年、2 月和闰年只使用 `calendar.monthrange()` 计算，不手写月份天数。

helper 的实现语义固定为：

```python
def _split_calendar_month_span_windows(
    start_date: date,
    end_date: date,
    *,
    months: int,
) -> tuple[tuple[date, date], ...]:
    if months <= 0 or start_date > end_date:
        raise planning_error("invalid_range_window", ...)

    windows: list[tuple[date, date]] = []
    cursor = start_date
    while cursor <= end_date:
        last_month_index = (
            cursor.year * 12 + (cursor.month - 1) + (months - 1)
        )
        last_year, last_month_zero_based = divmod(last_month_index, 12)
        last_month = last_month_zero_based + 1
        natural_window_end = date(
            last_year,
            last_month,
            monthrange(last_year, last_month)[1],
        )
        window_end = min(natural_window_end, end_date)
        windows.append((cursor, window_end))
        cursor = window_end + timedelta(days=1)

    return tuple(windows)
```

这里的 `months` 表示“包含当前自然月在内的连续自然月数量”。例如从 `2025-01-15` 开始、`months=2`，第一个窗口结束于 `2025-02-28`，不是简单给起始日期加 60 天。

固定窗口表：

```python
ETF_MINS_RANGE_WINDOW_MONTHS = {
    "1min": 2,
    "5min": 12,
    "15min": 36,
    "30min": 72,
    "60min": 120,
}
```

该映射是 `etf_mins` 的固定 planner 规则，不是运营配置项，也不进入前端 filters。range 不按交易日逐日展开，而是按频率生成多个受控多月 unit；仍然只有一个 TaskRun。

例如：

```text
freq=1min, range=2025-01-15~2025-05-10
  -> 2025-01-15~2025-02-28
  -> 2025-03-01~2025-04-30
  -> 2025-05-01~2025-05-10
```

### 5.4 Unit 内容

```python
PlanUnitSnapshot(
    unit_id=(
        f"etf_mins:ts_code={ts_code}:freq={freq}:"
        f"start={window_start.replace(' ', 'T')}:"
        f"end={window_end.replace(' ', 'T')}:{ordinal}"
    ),
    dataset_key="etf_mins",
    source_key="tushare",
    trade_date=unit_trade_date,
    request_params=request_builder(
        request,
        unit_trade_date,
        {
            "ts_code": ts_code,
            "freq": freq,
            "window_start": window_start,
            "window_end": window_end,
        },
    ),
    progress_context={
        "unit": "etf",
        "ts_code": ts_code,
        "freq": freq,
        "start_date": window_start,
        "end_date": window_end,
        "window_index": window_index,
        "window_total": len(date_windows),
    },
    pagination_policy="offset_limit",
    page_limit=8000,
    max_source_rows_per_unit=definition.planning.max_source_rows_per_unit,
)
```

builder 循环顺序固定为：`ts_code` 升序 -> `allowed_freqs` 固定顺序 -> 该频率窗口日期升序。`date_windows` 必须在每个 `freq` 循环内按对应月跨度生成。`unit_id` 必须包含切割后的 `start/end`，不能继续使用用户完整 range。`window_index/window_total` 只进入标准 progress context，不新增页面专属状态模型。

### 5.5 Unit 容量与事务基准

`page_processing_mode=buffer_all` 和 `commit_policy=unit` 的含义是：分页只降低单次源请求规模，不改变一个 ETF + 一个频率 + 一个时间窗口的事务边界。实现不得逐页提交。

当前 `DatasetSourceClient.fetch()` 会把一个 unit 的所有分页合并为 `SourceFetchResult.rows_raw`；`IngestionExecutor._process_fetched_unit()` 随后归一化、写入并调用一次 `session.commit()`。`fetch_concurrency` 只允许多个 unit 的源请求同时在途，不把多个 unit 合并成一个数据库事务。当前 unit 失败时只回滚当前 unit，已提交 unit 不回滚。

`max_source_rows_per_unit=24000` 是在“一到两页正常容量”之外增加一个完整数据页的安全余量。第一页、第二页、第三页的数据 offset 分别为 `0/8000/16000`；任意短页正常结束，最多接纳 24,000 行。累计出现第 24,001 行时，现有 `DatasetSourceClient.fetch()` 使用 `projected_row_count > max_source_rows_per_unit` 判断并抛出 `source_rows_exceeded`，当前 unit 不写库。

必须区分“可接纳数据页”和“边界探测请求”：第三页如果恰好满 8,000 行，通用分页器无法仅凭满页判断源端是否结束，会继续请求 `offset=24000`。该请求返回空页时，unit 以恰好 24,000 行成功；返回一行或更多数据时，累计值超过 24,000，立即失败。`offset=24000` 只用于确认边界，返回的数据不得被接纳为第四个数据页。

以 2009 至 2026 年约 213 个自然月估算，单只 ETF、五种频率分别约生成 `107/18/6/3/2` 个窗口，共约 136 个 unit。按正常每 unit 两页估算，全池约 37.9 万次基础分页请求、500 次/分钟下理论下限约 12.7 小时；按三个数据页的硬缓冲上限估算，约 56.9 万次基础分页请求、理论下限约 19.0 小时。两者均不包含同一页重试和第三个满页后的空边界探测。该数字用于容量规划，不是源站实测耗时。

M5 真实验收必须分别验证五种频率的完整窗口，记录页数、源端行数、峰值内存、normalize、写入和提交耗时。固定窗口应以一到两页为常态；偶发第三页属于安全余量。如果某个频率经常进入第三页，或在合法窗口内触发 `source_rows_exceeded`，必须缩短该频率的固定月跨度并同步修改 Definition、LLD 和测试；不得继续放宽 24,000 行门禁。

当前手动任务层和 ingestion validator 仍只校验起止日期存在且顺序正确，没有用户 range 最大跨度限制；`max_units_per_execution` 保持 `None`。长 range 由 planner 自动拆成受控 unit，不截断用户时间范围。

---

## 6. Request Builder 与源端调用

### 6.1 Request Builder

目标文件：

```text
src/foundation/ingestion/request_builders.py
```

新增：

```python
def _etf_mins_params(request, anchor_date, enum_values):
    del request
    del anchor_date
    return {
        "ts_code": str(enum_values["ts_code"]).strip().upper(),
        "freq": str(enum_values["freq"]).strip(),
        "start_date": str(enum_values["window_start"]).strip(),
        "end_date": str(enum_values["window_end"]).strip(),
    }
```

`limit/offset` 不在 builder 中写死，由 `DatasetSourceClient` 的 `offset_limit` 分页统一追加。可接纳数据页的 offset 为 `0/8000/16000`；第三页满页时允许一次 `offset=24000` 边界探测。探测为空则以 24,000 行结束，探测返回任何数据则由 `max_source_rows_per_unit=24000` 触发结构化错误，禁止写入第四个数据页。

### 6.2 Fields

connector 最终 payload 必须同时包含：

```text
api_name=etf_mins
params={ts_code,freq,start_date,end_date,limit,offset}
fields=ts_code,freq,trade_time,open,close,high,low,vol,amount,vwap,exchange
```

测试必须断言 `fields`，不能只断言 request builder 返回的 params。

`freq` 同时是请求参数和数据身份。`row_transform` 只有单行上下文，不能负责判断返回频率是否与当前 unit 相同。因此在 `DatasetSourceClient._execute_with_retry()` 得到源端 rows 后，新增 ETF 分钟专用的请求-返回一致性校验：

```text
expected_freq = params["freq"]
每行 freq 缺失或 row.freq != expected_freq
  -> source_variant_mismatch
  -> 整个 unit 失败
```

该校验不得像现有 `stk_mins` 一样无条件用请求值覆盖返回值。`etf_mins` 已实测可显式返回 `freq`，所以必须验证源端事实，而不是静默修补身份字段。

### 6.3 限速

目标文件：

```text
src/foundation/clients/tushare_client.py
```

在 `_API_RATE_LIMITS` 增加：

```python
"etf_mins": 500
```

不得复用 `stk_mins` 的 key，也不得依赖全局默认限速。

### 6.4 结构化错误

| 场景 | reason code | 处理 |
| --- | --- | --- |
| 必填参数缺失 / 显式空列表 | `required_param_missing` / `empty_not_allowed` | 不生成 unit。 |
| 频率值非法 | `invalid_enum` | 不生成 unit。 |
| 对象池为空或非法 | `universe_empty` / `invalid_enum` | 不请求源站。 |
| 返回频率缺失或错配 | `source_variant_mismatch` | 当前 unit 失败。 |
| 批内同键同内容 | `normalize.batch_unique_key_duplicate` | 当前 unit 失败。 |
| 批内同键不同内容 | `normalize.batch_unique_key_conflicting` | 当前 unit 失败。 |
| 任意归一化拒绝 | `write.unit_rows_rejected` | DAO 调用前失败。 |

新增 reason code 必须进入 `src/foundation/ingestion/codebook.py`；页面继续通过 TaskRun issue 展示结构化原因和样本，不新增另一套错误通道。

---

## 7. Normalizer 与质量门禁

### 7.1 Row Transform

目标文件：

```text
src/foundation/ingestion/row_transforms.py
```

新增 `_etf_mins_row_transform`：

```python
def _etf_mins_row_transform(row: dict[str, Any]) -> dict[str, Any]:
    trade_time = _parse_quote_time(row.get("trade_time"))
    current_time = trade_time.time()
    if not (
        time(9, 30) <= current_time <= time(11, 30)
        or time(13, 0) <= current_time <= time(15, 0)
    ):
        raise ValueError(...)

    freq = str(row.get("freq") or "").strip()
    if freq not in {"1min", "5min", "15min", "30min", "60min"}:
        raise ValueError(...)

    return {
        "ts_code": str(row.get("ts_code") or "").strip().upper(),
        "freq": freq,
        "trade_time": trade_time,
        "open": _optional_float(row.get("open")),
        "close": _optional_float(row.get("close")),
        "high": _optional_float(row.get("high")),
        "low": _optional_float(row.get("low")),
        "vol": _optional_int(row.get("vol")),
        "amount": _optional_float(row.get("amount")),
        "vwap": _optional_float(row.get("vwap")),
        "exchange": normalized_optional_exchange,
    }
```

硬规则：

- `freq` 保留字符串，不转整数。
- OHLC 不传 `ndigits=2`，不照抄股票分钟的两位小数裁剪。
- `trade_time` 必须落在 A 股交易时段；`09:30` 合法。
- row transform 负责确认 `freq` 属于五种合法值；它与当前 unit 请求频率的一致性由 source client 在进入 normalizer 前确认。

### 7.2 任意 reject 失败

Definition 使用：

```text
reject_policy=fail_unit_on_any_rejection
batch_unique_key_fields=(ts_code,freq,trade_time)
```

`DatasetNormalizer._validate_batch_unique_keys` 已能在同一完整批次出现完全重复键或冲突键时抛出结构化错误。对于普通字段转换造成的部分 reject，需要在 `DatasetWriter.write()` 进入空批次返回和具体 write path 分派之前执行通用 policy 判断：

```text
if reject_policy == fail_unit_on_any_rejection and batch.rows_rejected > 0:
    raise write.unit_rows_rejected
```

错误详情必须携带 `rows_rejected`、`rejected_reasons` 和 `rejected_samples`，并在 `src/foundation/ingestion/codebook.py` 注册。判断位于 DAO 调用之前，保证被拒绝的 unit 不发生业务写入。这项改动只补齐现有 quality policy 的真实执行语义；`record_rejections` 数据集行为不变，测试必须覆盖现有 `stk_mins` 仍保持原行为。

这是共享 writer contract 变更，消费者审计不能只测 ETF。当前使用 `fail_unit_on_any_rejection` 的 `index_classify`、`index_member_all`、`sw_daily` 也必须回归，确认它们仍在 DAO 前失败且既有结构化错误语义没有退化。

空结果不是 reject。某 ETF 在所选历史窗口确实无数据时，unit 可成功写入 0 行。

---

## 8. 数据表、ORM 与 DAO

### 8.1 Alembic 前置门禁

编码时先运行：

```text
uv run alembic heads
```

新迁移的 `down_revision` 只能接当时唯一真实 head。不得按本文日期或历史迁移文件名猜 revision。

本轮迁移文件：

```text
alembic/versions/20260825_000151_add_etf_minute_bar.py
```

### 8.2 DDL

```sql
CREATE TABLE raw_tushare.etf_minute_bar (
    ts_code varchar(16) NOT NULL,
    freq varchar(8) NOT NULL,
    trade_time timestamp without time zone NOT NULL,
    open double precision,
    close double precision,
    high double precision,
    low double precision,
    vol bigint,
    amount double precision,
    vwap double precision,
    exchange varchar(16),
    CONSTRAINT pk_raw_tushare_etf_minute_bar
        PRIMARY KEY (ts_code, freq, trade_time)
        USING INDEX TABLESPACE gs_raw_cold_hdd
) PARTITION BY RANGE (trade_time)
TABLESPACE gs_raw_cold_hdd;
```

迁移必须：

1. 开始时确认 `gs_raw_cold_hdd` 存在，不存在则抛错终止。
2. 连续预建 `2009-01` 至 `2037-12` 月分区，不得在迁移中留下月份空洞。
3. 每个普通月分区显式 `TABLESPACE gs_raw_cold_hdd`。
4. 默认分区也显式 `TABLESPACE gs_raw_cold_hdd`。
5. 父级分区索引、每个分区的主键索引和辅助索引都迁移到 `gs_raw_cold_hdd`。
6. 创建辅助索引 `(freq, trade_time DESC, ts_code)`，同样位于 HDD。
7. 不在运行时自动执行 DDL；超出 `2037-12` 前通过受控 Alembic 迁移扩展。默认分区可以防止遗漏月份写入失败，但不能替代正式月分区维护。

验收 SQL 必须遍历父表、所有分区和索引的 tablespace，不能只看父表。

### 8.3 ORM

新增：

```text
src/foundation/models/raw/raw_etf_minute_bar.py
```

类名：

```text
RawEtfMinuteBar
```

ORM 字段与 DDL 一一对应；`freq` 是 `String(8)`，价格、成交额和 `vwap` 使用 `Float(53)`，`vol` 是 `BigInteger`，主键是 `(ts_code, freq, trade_time)`。

注册位置：

- `src/foundation/models/all_models.py`
- `src/app/model_registry.py`，仅在当前 registry 需要显式模型导入时增加
- `tests/web/conftest.py`，仅在测试 schema 需要显式注册时增加

### 8.4 DAO

不新增专属 DAO 类。`src/foundation/dao/factory.py` 增加：

```python
self.raw_etf_minute_bar = GenericDAO(session, RawEtfMinuteBar)
```

`raw_only_upsert` 使用 Definition 的 conflict columns：

```text
ts_code,freq,trade_time
```

不创建第二个业务 DAO。

---

## 9. ETF 活跃池接入

### 9.1 现有事实

`src/foundation/dao/etf_series_active_dao.py` 已提供：

```python
list_active_codes(resource: str) -> list[str]
```

无需修改 DAO contract。

### 9.2 Seed 白名单

目标文件：

```text
src/ops/services/etf_series_active_seed_service.py
```

修改：

```python
ETF_SERIES_ACTIVE_RESOURCES += {"etf_mins"}
ETF_SERIES_ACTIVE_SEED_EXPECTED_ROWS_BY_RESOURCE["etf_mins"] = 1395
```

初始化复用现有 seed CSV 和现有 CLI：

```text
goldenshare ops-seed-etf-series-active \
  --resource etf_mins \
  --from-seed-csv reports/etf_series_active_seed_1395_20260617.csv
```

仍然默认 dry-run；生产 `--apply` 必须单独确认。开发阶段不连接生产，也不执行 seed。

“1,395 行强校验”的含义是：当 resource 为 `etf_mins` 时，seed service 要求输入 CSV 恰好包含 1,395 个不重复的 `.SH/.SZ` 代码；不是拿同步结果行数与 1,395 比较。

---

## 10. Ops、自动任务与展示

### 10.1 数据集目录

目标文件：

```text
src/ops/catalog/dataset_catalog_views.py
```

在 `etf_fund / ETF基金` 组中增加 `etf_mins`，排序放在现有 ETF 数据集之后；不调整其他数据集顺序。

### 10.2 手动任务

通用 manual action API 从 Definition 生成：

- point / range 时间模式
- `ts_code` 文本输入
- `freq` 多选

前端沿用 `frontend/src/pages/ops-v21-task-manual-tab.tsx` 的现有动态字段渲染。若通用多选已满足 `stk_mins`，不得为 ETF 新建页面或特殊控件。

### 10.3 自动任务

Definition 设置 `schedule_enabled=true` 后，复用现有自动任务创建与执行主链。自动任务保存的仍是用户意图：时间策略、可选 ETF 代码、已选频率；源端 `start_date/end_date` 仍由 resolver/planner/request builder 在运行时生成。

当前 `TaskRunDispatcher._prepare_dataset_action_request()` 对 point 模式的标准行为是：如果排程没有固定 `trade_date`，运行时从交易日历选择 `<= 当天` 的最近开市日，再交给 resolver。ETF 分钟沿用该行为，不在 schedule service 或前端提前计算日期。固定 range 仍按保存的 `start_date/end_date` 执行。

V1：

- 不创建默认 schedule。
- 不加入 workflow。
- 不增加 ETF 专属隐藏参数。

### 10.4 任务进度

使用现有 `progress_context`：

```json
{
  "unit": "etf",
  "ts_code": "510300.SH",
  "freq": "5min",
  "start_date": "2025-01-01 09:00:00",
  "end_date": "2025-12-31 19:00:00",
  "window_index": 1,
  "window_total": 3
}
```

任务详情只显示标准 unit 进度与已提交行数。TaskRun 的 `total_units` 必须使用 planner 展开后的 ETF × 频率 × 时间窗口总数，不能继续按 ETF × 频率估算；当前对象文案使用 `window_index/window_total` 和切割后的 `start_date/end_date`，不显示用户完整 range 冒充当前 unit。

### 10.5 Freshness、数据卡片与日期审计

- `src/foundation/datasets/freshness_policies.py` 注册 `etf_mins -> CONTINUOUS_OPEN_DAY`。
- `dataset_definition_projection.py` 从 Definition 读取 `target_table/raw_table/observed_field/freshness_policy`，不得新增 ETF 特例。
- `freshness_query_service.py` 以 `raw_tushare.etf_minute_bar.trade_time` 的最大值作为业务观测日期，并结合最近成功任务展示状态。
- `audit_applicable=false` 与 `completeness.scope=not_applicable` 使普通日期完整性审计页显示“不适用”，但不影响手动和自动任务的 point/range 输入。
- `operations_dataset_status_snapshot_service.py` 继续生成数据卡片快照；状态写入失败不得影响分钟表事务。

---

## 11. 文件级修改清单

### 11.1 新增

| 文件 | 用途 |
| --- | --- |
| `src/foundation/models/raw/raw_etf_minute_bar.py` | 唯一 raw ORM。 |
| `alembic/versions/20260825_000151_add_etf_minute_bar.py` | HDD 月分区表迁移。 |
| `tests/test_etf_mins_dataset.py` | Definition、planner、builder、transform、writer 主测试。 |
| `tests/test_etf_minute_bar_model.py` | ORM、迁移、HDD DDL 静态约束。 |

测试文件可按仓库现有测试粒度拆分，但不得因此遗漏任何门禁。

### 11.2 修改

| 文件 | 修改内容 |
| --- | --- |
| `src/foundation/datasets/definitions/market_fund.py` | 新增 Definition。 |
| `src/foundation/datasets/freshness_policies.py` | 注册 `CONTINUOUS_OPEN_DAY`。 |
| `src/foundation/ingestion/unit_planner.py` | 新增 ETF target resolver 与 unit builder。 |
| `src/foundation/ingestion/request_builders.py` | 新增 `_etf_mins_params` 并注册。 |
| `src/foundation/ingestion/source_client.py` | 校验源端每行 `freq` 与 unit 请求值一致，不静默覆盖。 |
| `src/foundation/ingestion/row_transforms.py` | 新增 `_etf_mins_row_transform` 并注册。 |
| `src/foundation/ingestion/writer.py` | 让 raw-only 路径执行既有 fail-any reject policy。 |
| `src/foundation/ingestion/codebook.py` | 注册 `write.unit_rows_rejected`。 |
| `src/foundation/clients/tushare_client.py` | 新增 500/min endpoint 限速。 |
| `src/foundation/dao/factory.py` | 注册 `raw_etf_minute_bar`。 |
| `src/foundation/models/all_models.py` | 注册 ORM。 |
| `src/ops/services/etf_series_active_seed_service.py` | 增加 resource 白名单与 1,395 映射。 |
| `src/ops/catalog/dataset_catalog_views.py` | 加入 ETF基金展示组。 |
| `docs/sources/tushare/docs_index.csv` | 保持 doc 387 的 API 名为 `etf_mins`。 |

### 11.3 明确不修改

```text
src/foundation/ingestion/execution_plan.py
src/foundation/ingestion/resolver.py
src/foundation/ingestion/executor.py
任何 workflow 定义
```

---

## 12. 测试设计

### 12.1 Definition 与消费者

- `dataset_key/api_name/source_doc_id/source_fields` 正确。
- storage 只有 raw 表、`raw_only_upsert`，serving/std 为空。
- 只支持 point/range，手动和 schedule 开启，workflow 无引用。
- 频率枚举精确等于 `1min/5min/15min/30min/60min`。
- `completeness.scope=not_applicable`，freshness policy 为 `continuous_open_day`。
- Ops catalog 归入 `etf_fund`。

### 12.2 Planner

- point 生成 ETF × freq unit，窗口为当日 09:00-19:00。
- range 按频率分别以 `2/12/36/72/120` 个自然月切窗，再生成 ETF × freq × window unit。
- point 不调用 range splitter；每个 point unit 的 `window_index/window_total` 均为 `1/1`。
- `1min + 2025-01-15~2025-05-10` 必须精确生成 `2025-01-15~2025-02-28`、`2025-03-01~2025-04-30`、`2025-05-01~2025-05-10` 三个窗口。
- 五种频率必须分别覆盖固定月跨度；不能错误复用 `1min` 的两个月窗口或生成一套公共窗口。
- 首尾窗口按用户日期裁剪；跨年、闰年和非月初起点覆盖正确。
- 所有窗口连续、无重叠、无遗漏，集合精确覆盖用户 range。
- 每个生成的 unit 都必须携带 `page_limit=8000`、`max_source_rows_per_unit=24000` 和切割后的 start/end。
- 未选 freq 失败；非法 freq 失败。
- 空 `ts_code` 读取 `etf_mins` 池；显式代码必须属于同一池并只生成一个 ETF。
- 空池、池外显式代码、`.OF` 和非法后缀失败。
- unit 顺序稳定，progress context 完整。

### 12.3 Request 与分页

- 参数精确为 `ts_code/freq/start_date/end_date`。
- connector payload 带全部显式 fields。
- 可接纳数据页 offset 只允许 `0/8000/16000`。
- 第一页、第二页或第三页出现短页时正常结束，合并后的唯一键集合完整。
- 同一页失败后的 retry 必须保持原 offset，不能把重试误算成下一页。
- 第三页短页时成功并写入不超过 23,999 行。
- 第三页满页时必须请求一次 `offset=24000` 边界探测；空结果允许恰好 24,000 行成功，非空结果必须以 `source_rows_exceeded` 失败，writer 未被调用且当前 unit 未提交。
- 测试必须证明 `offset=24000` 返回的数据不会被接纳为第四个数据页。
- `etf_mins` 使用 500/min 独立 limiter。

### 12.4 Normalizer 与 Writer

- 五种频率均保留字符串。
- 价格不裁剪到两位小数。
- `09:30`、午前、午后、`15:00` 合法；午休和盘外时间拒绝。
- 缺 `ts_code/freq/trade_time` 拒绝。
- 返回 freq 与 unit 不一致时失败。
- 完全重复 identity 和冲突 identity 均失败。
- 任意部分 reject 时 unit 不写入、不提交。
- 空结果允许成功 0 行。
- 重复执行同一数据幂等，表行数不膨胀。
- `stk_mins` 的 `record_rejections` 既有行为不受 fail-any policy 改动影响。

### 12.5 ORM、迁移与 HDD

- ORM schema、字段、主键与 DDL 一致。
- 新迁移只接执行时真实 Alembic head。
- migration 只创建 `raw_tushare.etf_minute_bar`。
- 父表、普通分区、默认分区、主键和辅助索引都显式指向 `gs_raw_cold_hdd`。
- tablespace 不存在时迁移失败。
- `uv run alembic heads` 仍只有一个 head。

### 12.6 Ops 手动与自动

- manual API 返回代码和五频率多选字段。
- 页面只显示 Definition 契约生成的通用代码、频率和时间控件。
- schedule 可保存同一 filters，并在运行时形成正确 plan。
- workflow registry 中无 `etf_mins`。
- TaskRun 总 unit 数等于 planner 完整展开后的数量；进度只使用标准 unit 机制，并包含 ETF、频率、切割后时间范围和窗口序号。
- point 自动任务未固定日期时使用最近开市日；固定日期和 range 不被改写。
- 数据卡片读取 raw 表最大 `trade_time`；日期完整性审计显示不适用。

### 12.7 必跑命令

```bash
uv run pytest -q tests/test_etf_mins_dataset.py tests/test_etf_minute_bar_model.py
uv run pytest -q tests/test_dataset_definition_registry.py tests/test_dataset_action_resolver.py tests/architecture/test_dataset_runtime_registry_guardrails.py
uv run pytest -q tests/architecture/test_subsystem_dependency_matrix.py tests/architecture/test_platform_legacy_guardrails.py tests/architecture/test_operations_legacy_guardrails.py
uv run goldenshare ingestion-lint-definitions
uv run ruff check src/foundation/datasets/definitions/market_fund.py src/foundation/datasets/freshness_policies.py src/foundation/ingestion src/foundation/models/raw/raw_etf_minute_bar.py src/ops/services/etf_series_active_seed_service.py tests/test_etf_mins_dataset.py tests/test_etf_minute_bar_model.py
cd frontend && npm run typecheck
cd frontend && npm run test -- ops-v21-task-manual-tab ops-v21-task-auto-tab ops-v21-source-page ops-v21-dataset-audit-page
python3 scripts/check_docs_integrity.py
```

若实际测试文件按现有粒度拆分，命令同步替换为真实文件名；不能保留不存在的占位路径作为交付证据。

---

## 13. 最小真实验收

编码和迁移完成后，先在非生产环境做一个 ETF、一个交易日、五种频率的最小任务：

```text
ts_code=510300.SH
trade_date=2026-08-21
freq=1min,5min,15min,30min,60min
```

逐项记录：

- 每个频率的请求参数和页数。
- `rows_fetched`。
- `rows_normalized`。
- `rows_written/rows_committed`。
- `rows_rejected` 和 reason sample。
- 表中按 `(ts_code,freq,trade_time)` 查询的实际行数。
- 重复执行后的行数。

验收成功必须满足：

```text
rows_rejected = 0
written keys = source unique keys
second run does not increase unique-key count
```

随后用 PostgreSQL 元数据确认所有 relation 和 index 均位于 HDD。没有这一步，不能进入生产全池同步。

---

## 14. 发布与回退

发布顺序：

1. 完成本 LLD 的定向测试、全量 Definition lint、架构护栏和文档检查。
2. 在开发环境执行迁移，并查询 `pg_class/pg_tablespace/pg_inherits` 验证父表、全部分区和索引。
3. `etf_mins` active resource 先 dry-run，人工核对 1,395 个代码后才 apply。
4. 先执行一个 ETF、一个交易日、一个频率的真实任务，再执行五频率任务。
5. 对账通过后才允许创建自动任务。

若迁移尚未执行，回退只需回退应用提交。若迁移已执行但表为空，可在明确批准后执行 migration downgrade；若表已有业务数据，禁止自动 drop、truncate 或重建，必须保留数据并另行制定清理清单。

---

## 15. 开发顺序

1. **M1 Definition / planner 契约（本地已完成）**：定义、频率、时间、active resource、catalog 和静态测试。
2. **M2 HDD 表 / ORM / DAO（本地已完成）**：已核对 Alembic head，落唯一 raw 表迁移及完整 HDD 门禁；尚未执行迁移。
3. **M3 source / normalize / writer（本地已完成）**：按频率切窗、一到两页正常容量与第三页安全余量、builder、分页 fields、500/min、transform、fail-any 质量策略。
4. **M4 manual / schedule 契约（本地已完成）**：通用页面和自动任务消费者测试已覆盖，不新增专属交互，且 workflow 反向门禁已覆盖。
5. **M5 回归与真实验收（部分完成）**：本地单元、架构、通用前端契约与文档检查已完成；最小真实同步和 HDD 元数据核验待部署后执行。

每个 milestone 只做表中列出的范围。若实现时发现源接口真实字段、当前 Alembic head、HDD tablespace 名称或通用手动/自动任务契约与本文不一致，必须停下更新方案，不得靠兼容代码绕过。

---

## 16. 已冻结结论

1. ETF 历史分钟只落 `raw_tushare.etf_minute_bar`。
2. `1min/5min/15min/30min/60min` 全部直接请求 Tushare。
3. 平台只接受 `1min/5min/15min/30min/60min` 五种频率。
4. 复用现有 execution plan 和 executor。
5. 手动、自动都支持；不进 workflow。
6. 交互复用生产 `stk_mins` 的普通频率多选。
7. 表、分区、索引全部在 `gs_raw_cold_hdd`。
8. ETF 对象池使用 `ops.etf_series_active(resource='etf_mins')`，初始 1,395 只。
9. 首版迁移连续预建 `2009-01` 至 `2037-12` 月分区，并建立 HDD 默认分区；运行时同步禁止建分区。
10. 显式 `ts_code` 必须属于 `resource='etf_mins'`，池外代码在 planner 阶段拒绝。
11. range 按频率使用 `2/12/36/72/120` 个自然月切窗；一个 TaskRun 内生成多个时间窗口 unit。
12. `page_limit=8000`、`max_source_rows_per_unit=24000`；每个 unit 按一到两页测算，最多接纳三个数据页，`offset=24000` 只允许作为满三页后的边界探测。
