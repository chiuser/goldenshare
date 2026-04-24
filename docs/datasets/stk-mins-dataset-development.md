# Tushare 股票历史分钟行情（`stk_mins`）数据集开发方案

## 1. 目标与边界

- 目标：新增 Tushare `stk_mins` 数据集，接入 A 股历史分钟行情，支持 `1min/5min/15min/30min/60min` 五种频度的按交易日、按交易时段拉取。
- 数据源文档：`docs/sources/tushare/股票数据/行情数据/0370_股票历史分钟行情.md`
- 本期只接入当前 Sync V2 主链路，不新增 V1 路径，不回流到 `src/platform` 或 `src/operations`。
- 因分钟数据量巨大，本数据集不做 Raw 表与 Core Serving 表双份存储；采用“Raw 单物理表 + Core Serving 只读 View”的方式降低磁盘消耗，同时保留服务层访问入口。
- 支持全市场同步：未指定 `ts_code` 时，按 Tushare `stock_basic` 证券池中的 `ts_code` 扇出请求。
- 不加入每日自动工作流；第一期通过独立 CLI `goldenshare sync-minute-history` 和 Ops 手动任务触发。
- 用户侧时间选择只能选择交易日或交易日区间，不能选择具体时间；具体交易时段由程序内部固定定义。

## 2. 上游接口事实

| 项 | 内容 |
| --- | --- |
| 接口 | `stk_mins` |
| 描述 | 获取 A 股历史分钟行情，支持 `1min/5min/15min/30min/60min` |
| 权限 | 需单独开通分钟权限 |
| 单次上限 | `8000` 行 |
| 拉取方式 | 按股票代码和时间循环获取，支持 `limit/offset` 分页 |
| 历史范围 | 可提供超过 10 年历史分钟数据 |

### 2.1 输入参数

| 上游字段 | 类型 | 必选 | 说明 | 我方口径 |
| --- | --- | --- | --- | --- |
| `ts_code` | `str` | 是 | 股票代码，如 `600000.SH` | 用户可选；未传时使用 Tushare 股票池扇出 |
| `freq` | `str` | 是 | `1min/5min/15min/30min/60min` | 必填，支持多选时按频度扇开 |
| `start_date` | `datetime` | 否 | 开始时间，如 `2023-08-25 09:00:00` | 不由用户直接填写；程序按交易日和内部交易时段生成 |
| `end_date` | `datetime` | 否 | 结束时间，如 `2023-08-25 19:00:00` | 不由用户直接填写；程序按交易日和内部交易时段生成 |
| `limit` | `int` | 否 | 单次返回数据长度 | 内部固定分页参数，默认 `8000` |
| `offset` | `int` | 否 | 请求数据的开始位移量 | 内部分页递增 |

### 2.2 输出参数

| 字段 | 类型 | 说明 | 落库口径 |
| --- | --- | --- | --- |
| `ts_code` | `str` | 股票代码 | `VARCHAR(16)`，必填 |
| `trade_time` | `str` | 交易时间 | 解析为 `TIMESTAMP WITHOUT TIME ZONE`，必填 |
| `open` | `float` | 开盘价 | `DOUBLE PRECISION` |
| `close` | `float` | 收盘价 | `DOUBLE PRECISION` |
| `high` | `float` | 最高价 | `DOUBLE PRECISION` |
| `low` | `float` | 最低价 | `DOUBLE PRECISION` |
| `vol` | `int` | 成交量（股） | `DOUBLE PRECISION`，兼容样例中小数形式 |
| `amount` | `float` | 成交金额（元） | `DOUBLE PRECISION` |

## 3. 现有“Raw/Core 同表映射”参考与本次口径

当前代码里已有类似模式：

- `biying_equity_daily` 的 contract 使用 `write_path="raw_only_upsert"`。
- 其 `raw_dao_name` 与 `core_dao_name` 都指向 `raw_biying_equity_daily_bar`。
- `target_table` 指向 `raw_biying.equity_daily_bar`。

`stk_mins` 采用同类写入口径，但额外提供 Core Serving 只读 View：

- 只有一个物理表：`raw_tushare.stk_mins`。
- V2 写入走 `raw_only_upsert`。
- contract 中 `raw_dao_name="raw_stk_mins"`，`core_dao_name="raw_stk_mins"`。
- `target_table="raw_tushare.stk_mins"`。
- 服务层访问入口：`core_serving.equity_minute_bar` 普通 View，查询 `raw_tushare.stk_mins`。
- Ops 写入进度以 `raw_tushare.stk_mins` 为目标表；后续 Biz/查询层优先通过 `core_serving.equity_minute_bar` 访问。

这样做的收益：

- 不重复存储 Raw 和 Serving，节省接近一倍空间。
- 保留 V2 contract/writer 的统一执行路径。
- 后续 Biz 可沿用 `core_serving` 分层入口，不需要直接依赖 `raw_tushare`。
- 普通 View 不复制数据，不引入 materialized view 的存储成本和刷新问题。

## 4. 命名与分层

| 层 | 名称 | 说明 |
| --- | --- | --- |
| dataset_key | `stk_mins` | 与 Tushare API 对齐 |
| display_name | `股票历史分钟行情` | Ops 展示名 |
| 物理表 | `raw_tushare.stk_mins` | 唯一物理存储表 |
| 服务层入口 | `core_serving.equity_minute_bar` | 普通只读 View，不复制数据 |
| raw DAO | `raw_stk_mins` | `DAOFactory` 中注册 |
| core DAO | `raw_stk_mins` | 逻辑映射到同一 DAO，不单独建 Core 表 |
| 策略文件 | `src/foundation/services/sync_v2/dataset_strategies/stk_mins.py` | 一数据集一策略文件 |
| contract 域 | `market_equity.py` | 股票行情类数据集 |

说明：旧模板中提到 `Raw -> Std -> Serving`，但当前 V2 主链路已收敛为按数据集选择写入路径；本数据集不引入 Std 层，不创建 `core_serving.equity_minute_bar` 物理表，只创建同名服务层 View。

## 5. 数据模型设计

### 5.1 主表：`raw_tushare.stk_mins`

字段设计：

| 字段 | 类型 | 约束 | 含义 |
| --- | --- | --- | --- |
| `ts_code` | `VARCHAR(16)` | NOT NULL | 股票代码 |
| `freq` | `VARCHAR(8)` | NOT NULL | 分钟频度，来源于请求参数 |
| `trade_time` | `TIMESTAMP WITHOUT TIME ZONE` | NOT NULL | 分钟 bar 时间 |
| `trade_date` | `DATE` | NOT NULL | 从 `trade_time` 派生，用于分区、状态、查询过滤 |
| `session_tag` | `VARCHAR(16)` | NOT NULL | `morning` 或 `afternoon`，来源于请求时段 |
| `open` | `DOUBLE PRECISION` | NULL | 开盘价 |
| `close` | `DOUBLE PRECISION` | NULL | 收盘价 |
| `high` | `DOUBLE PRECISION` | NULL | 最高价 |
| `low` | `DOUBLE PRECISION` | NULL | 最低价 |
| `vol` | `DOUBLE PRECISION` | NULL | 成交量（股） |
| `amount` | `DOUBLE PRECISION` | NULL | 成交金额（元） |
| `api_name` | `VARCHAR(64)` | NOT NULL | 固定 `stk_mins` |
| `fetched_at` | `TIMESTAMPTZ` | NOT NULL | 抓取时间 |
| `raw_payload` | `TEXT` | NULL | 原始响应行，第一期建议不写入或仅调试时写入 |

主键与索引：

- 主键：`(ts_code, freq, trade_date, trade_time)`
- 索引：`(trade_date, freq)`
- 索引：`(ts_code, freq, trade_time DESC)`

分区策略：

- 按 `trade_date` RANGE 分区。
- 分区粒度建议按月；分钟行情数据量远大于日频，月分区便于后续按月清理、回补和查询。
- 必须保留 `DEFAULT` 分区，避免用户回补很早或未来日期时因缺少分区导致任务失败。

### 5.2 `raw_payload` 口径

当前大多数 Raw 模型都有 `api_name/fetched_at/raw_payload` 审计字段，`raw_payload` 在现有模型里通常是 `TEXT`，保存 JSON 字符串，不是统一 `JSONB`。

但 `stk_mins` 数据量极大，逐行保存完整 `raw_payload` 会显著放大磁盘占用。建议：

- 表结构保留 `raw_payload TEXT NULL`，保持 Raw 表审计字段习惯和兼容性。
- 归一化写入默认不填 `raw_payload`，即保持 NULL。
- 如果后续需要问题排查，可只在小窗口调试任务中临时打开原始载荷写入，不作为默认行为。

### 5.3 服务层 View：`core_serving.equity_minute_bar`

建议创建普通 View：

```sql
CREATE OR REPLACE VIEW core_serving.equity_minute_bar AS
SELECT
    ts_code,
    freq,
    trade_time,
    trade_date,
    session_tag,
    open,
    close,
    high,
    low,
    vol,
    amount,
    'tushare'::varchar(32) AS source,
    fetched_at AS updated_at
FROM raw_tushare.stk_mins;
```

设计约束：

- 这是普通 View，不是 materialized view。
- 不承载写入，不需要 DAO 写入。
- Biz 查询优先面向该 View。
- Raw 表索引必须覆盖 View 的常用查询条件，如 `ts_code/freq/trade_time` 与 `trade_date/freq`。

### 5.4 90 分钟线计算结果表建议

90 分钟线是我方派生结果，不是 Tushare 原始 `stk_mins` 返回数据，不建议写入 `raw_tushare.stk_mins`。

建议新增派生表：

| 项 | 建议 |
| --- | --- |
| 表名 | `core_serving.equity_minute_bar_derived` |
| 主键 | `(ts_code, freq, trade_date, trade_time)` |
| `freq` | 固定使用 `90min` |
| `source` | `derived_30_60` 或更明确的计算来源 |
| 字段 | 与 `stk_mins` 主表保持 OHLCV/amount 基本一致 |
| 分区 | 按 `trade_date` 月分区 |

理由：

- 派生数据属于服务层结果，不应污染 Tushare Raw 事实表。
- 90 分钟线数据量远小于 1/5/15/30/60 分钟线，单独表空间压力可控。
- 后续 Biz 查询可以通过 API 聚合，把 `core_serving.equity_minute_bar` View 与派生表统一输出。

## 6. 日期模型与任务语义

`stk_mins` 的请求由“交易日 + 程序内部固定交易时段”驱动，不暴露具体时间选择给用户。

建议使用当前数据集日期模型体系中的交易日模型，并增加分钟策略语义：

| 字段 | 建议值 | 说明 |
| --- | --- | --- |
| `date_axis` | `trade_open_day` | 只允许开市交易日 |
| `bucket_rule` | `every_open_day` | 区间按每个交易日展开 |
| `window_mode` | `point_or_range` | 支持单交易日或交易日区间 |
| `input_shape` | `trade_date_or_start_end` | 用户侧选择交易日或交易日区间 |
| `observed_field` | `trade_date` | 数据状态先以交易日观测 |
| `audit_applicable` | `false`（第一期） | 分钟级完整性审计依赖交易时段和频度规则，第一期先不纳入 |
| `not_applicable_reason` | `minute completeness audit requires trading-session calendar` | 明确不纳入第一期审计的原因 |

交易时段由 `stk_mins` 策略固定：

```text
morning:   09:30:00 ~ 11:30:00
afternoon: 13:00:00 ~ 15:00:00
```

注意：

- 日历组件只允许选择交易日或交易日区间，不能选择小时、分钟、秒。
- 区间执行时先按交易日历过滤开市日期。
- 每个交易日固定生成上午、下午两个请求时段。
- 上游 `start_date/end_date` 虽然是 datetime 参数，但它们只由程序内部生成，不作为用户侧参数暴露。

## 7. 请求策略

### 7.1 默认规则

- `freq` 必填，可单选或多选。
- `trade_date` 或 `start_date + end_date` 必填。
- `ts_code` 可选；未传时使用 Tushare 股票池扇出全市场。
- `limit=8000`。
- `offset` 从 `0` 开始递增，直到返回行数 `< 8000`。
- 不加入 `sync_daily`；由专用 CLI 和 Ops 手动任务触发。

### 7.2 股票池扇出

当用户未指定 `ts_code` 时：

1. 从 Tushare `stock_basic` 已落库结果读取 `ts_code`。
2. 建议优先使用 `core_serving.security_serving` 中 `source='tushare'`、`security_type='EQUITY'` 的代码池；如果需要严格按 Raw 源表，则使用 `raw_tushare.stock_basic`。
3. 默认包括 `L/P/D` 状态，避免历史回补漏掉退市或暂停上市证券；如后续运营侧需要，可再增加上市状态过滤。
4. 通过 `offset/limit` 对证券池分批，避免一次任务规划出过多 unit。

示例：

```text
freq = [30min, 60min]
start_date = 2026-04-20
end_date = 2026-04-23
ts_code 未传
stock_basic 证券池 = 600000.SH, 000001.SZ, ...
```

规划维度：

```text
证券代码 x 频度 x 交易日 x 交易时段
```

### 7.3 频度扇开

当用户选择多个 `freq` 时，每个频度单独请求：

```text
stk_mins(ts_code=600000.SH, freq=30min, start_date=2026-04-23 09:30:00, end_date=2026-04-23 11:30:00)
stk_mins(ts_code=600000.SH, freq=30min, start_date=2026-04-23 13:00:00, end_date=2026-04-23 15:00:00)
stk_mins(ts_code=600000.SH, freq=60min, start_date=2026-04-23 09:30:00, end_date=2026-04-23 11:30:00)
stk_mins(ts_code=600000.SH, freq=60min, start_date=2026-04-23 13:00:00, end_date=2026-04-23 15:00:00)
```

### 7.4 参数映射

我方内部参数：

```text
ts_code?         # 可选，不传则全市场
freq             # 必填，可多选
trade_date?      # 单日
start_date?      # 区间开始交易日
end_date?        # 区间结束交易日
offset?          # 股票池分页
limit?           # 股票池分页
```

请求 Tushare 参数：

```text
ts_code
freq
start_date = YYYY-MM-DD 09:30:00 / 13:00:00
end_date = YYYY-MM-DD 11:30:00 / 15:00:00
limit = 8000
offset = 0, 8000, 16000, ...
```

说明：这里有两类分页，不要混淆：

- 股票池 `offset/limit`：控制本次处理哪些 `ts_code`。
- Tushare 请求 `limit/offset`：控制单个接口请求分页，固定按 `8000` 递增。

## 8. Sync V2 接入方案

### 8.1 字段常量

新增：

```python
STK_MINS_FIELDS = (
    "ts_code",
    "trade_time",
    "open",
    "close",
    "high",
    "low",
    "vol",
    "amount",
)
```

### 8.2 Contract

位置：`src/foundation/services/sync_v2/registry_parts/contracts/market_equity.py`

建议 contract：

- `dataset_key="stk_mins"`
- `display_name="股票历史分钟行情"`
- `job_name="sync_stk_mins"`
- `run_profiles_supported=("point_incremental", "range_rebuild")`
- `date_model=build_date_model("stk_mins")`
- `source_adapter_key="tushare"`
- `source_spec.api_name="stk_mins"`
- `source_spec.fields=STK_MINS_FIELDS`
- `planning_spec.pagination_policy="offset_limit"`
- `pagination_spec.page_limit=8000`
- `write_spec.write_path="raw_only_upsert"`
- `write_spec.raw_dao_name="raw_stk_mins"`
- `write_spec.core_dao_name="raw_stk_mins"`
- `write_spec.target_table="raw_tushare.stk_mins"`

说明：`target_table` 指写入目标与数据状态目标；服务层 View 另由 Alembic 创建，不参与 writer。

### 8.3 InputSchema

建议字段：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `ts_code` | `string` | 否 | 单股票代码；不传则走股票池全市场 |
| `freq` | `list` | 是 | 支持一个或多个频度；值限定在 `1min/5min/15min/30min/60min` |
| `trade_date` | `date` | 否 | 单交易日 |
| `start_date` | `date` | 否 | 区间开始交易日 |
| `end_date` | `date` | 否 | 区间结束交易日 |
| `offset` | `integer` | 否 | 股票池分批起始位移 |
| `limit` | `integer` | 否 | 股票池分批处理数量 |

约束：

- `trade_date` 与 `start_date/end_date` 二选一。
- `freq` 不能为空。
- `freq` 值必须在 `1min/5min/15min/30min/60min`。
- 如果不传 `ts_code`，建议必须显式给 `offset/limit` 或在 CLI 层二次确认，避免误跑全市场超大任务。

### 8.4 策略文件

新增：`src/foundation/services/sync_v2/dataset_strategies/stk_mins.py`

职责：

- 校验 `freq` 值。
- 解析单交易日或交易日区间。
- 从交易日历展开开市日期。
- 未传 `ts_code` 时，从 Tushare 股票池加载证券代码，并按 `offset/limit` 分批。
- 将维度拆成：`ts_code x freq x trade_date x session`。
- 为每个执行单元生成 Tushare 请求参数。
- 设置 `pagination_policy="offset_limit"`、`page_limit=8000`。

允许读数据库：

- 读取交易日历。
- 读取 Tushare 股票池。

禁止：

- 不直接调用 Tushare。
- 不写 SQL。
- 不绕开 V2 writer。

### 8.5 归一化

归一化规则：

- `trade_time`：解析为 `datetime`。
- `trade_date`：从 `trade_time.date()` 派生。
- `freq`：从请求上下文注入到每行。
- `session_tag`：从请求上下文注入到每行。
- 数值列：`open/close/high/low/vol/amount` 转为数值。
- 必填校验：`ts_code/freq/trade_time/trade_date/session_tag`。
- `raw_payload`：默认不填，降低存储占用。

拒绝规则：

- `trade_time` 为空或无法解析：拒绝。
- `ts_code` 为空：拒绝。
- `freq` 不在允许枚举：拒绝。

## 9. Ops 与前端接入

### 9.1 JobSpec

不加入 `sync_daily`。

新增专用任务：

| 任务 | 说明 |
| --- | --- |
| `sync_minute_history.stk_mins` | 股票历史分钟行情同步 |

参数：

- `ts_code`：可选。
- `freq`：必填，多选枚举。
- `trade_date`：单日模式。
- `start_date/end_date`：区间模式。
- `offset/limit`：全市场股票池分批。

不复用 `sync_history.stk_mins` 的原因：

- 分钟行情虽然是历史数据，但请求语义不是普通日频历史同步。
- 专用任务能把 UI、CLI、进度和风险提示做清楚。
- 避免把任意 datetime 或分钟时段逻辑污染到通用 `sync_history`。

### 9.2 手动维护页面

需要支持：

- `ts_code` 文本输入；留空表示全市场。
- `freq` 多选枚举。
- 日期选择器只允许选择交易日。
- 单日模式：选择一个交易日。
- 区间模式：选择开始交易日和结束交易日。
- 全市场模式展示 `offset/limit`，用于分批同步。
- 展示固定交易时段说明：上午 `09:30~11:30`，下午 `13:00~15:00`。
- 不提供小时、分钟、秒输入控件。
- 提示文案：分钟数据量很大，全市场建议分批执行。

不支持：

- 不支持用户任意输入 `09:42:13` 这类自定义时间。
- 不支持用户修改上午/下午交易时段边界。
- 不支持加入每日自动工作流。

### 9.3 数据状态页

第一期建议：

- 以 `trade_date` 展示数据范围。
- 数据状态目标表显示为 `raw_tushare.stk_mins`。
- 业务查询文档中对外推荐入口显示为 `core_serving.equity_minute_bar`。
- 如后续需要分钟最新时间，再扩展展示 `latest_trade_time`。

### 9.4 工作流

本期不加入：

- `daily_market_close_sync`
- `reference_data_refresh`
- 任何自动任务工作流

原因：

- 上游需要单独权限。
- 分钟数据量巨大。
- 自动任务应等分批策略、磁盘容量、失败恢复策略验证稳定后再单独评审。

## 10. CLI 接入

新增专用 CLI：

```bash
goldenshare sync-minute-history \
  --freq 30min \
  --start-date 2026-04-23 \
  --end-date 2026-04-23 \
  --ts-code 600000.SH
```

全市场分批示例：

```bash
goldenshare sync-minute-history \
  --freq 30min,60min \
  --start-date 2026-04-23 \
  --end-date 2026-04-23 \
  --offset 0 \
  --limit 200
```

CLI 行为：

- `--ts-code` 可选。
- 未传 `--ts-code` 时，从股票池读取证券代码。
- `--offset/--limit` 控制股票池分批。
- 每处理 N 只股票输出进度。
- 每个 unit 输出 `trade_date/session/freq/ts_code fetched/written/rejected`。

## 11. 对账与数据质量

### 11.1 对账范围

因为只有一张物理表，不做 Raw/Core 行数对账。

建议对账改为表内质量检查：

- 按 `ts_code + freq + trade_date` 检查重复主键。
- 检查 `trade_time` 是否为空。
- 检查 `trade_time` 是否落在固定交易时段内。
- 检查 `freq` 是否为允许值。
- 抽样检查全市场批次写入行数是否大于 0。
- 检查 `core_serving.equity_minute_bar` View 与 `raw_tushare.stk_mins` 在同一过滤条件下行数一致。

### 11.2 不纳入日期完整性审计第一期

原因：

- 分钟数据完整性不仅依赖交易日历，还依赖交易时段、午休、不同频度 bar 生成规则。
- 现有日期完整性审计主要覆盖日/周/月/自然日/月窗口，不应临时把分钟完整性硬塞进去。

后续如要做分钟完整性审计，需要先定义：

- A 股交易时段模型。
- 不同 `freq` 下应出现的 bar 时间点。
- 停牌、临停、半日交易等异常场景口径。

## 12. 代码改动清单

### 12.1 Foundation

- `src/foundation/services/sync_v2/fields.py`
  - 新增 `STK_MINS_FIELDS`。
- `src/foundation/services/sync_v2/registry_parts/contracts/market_equity.py`
  - 新增 `stk_mins` contract。
- `src/foundation/services/sync_v2/registry_parts/common/date_models.py`
  - 新增 `stk_mins` 日期模型。
- `src/foundation/services/sync_v2/dataset_strategies/stk_mins.py`
  - 新增数据集策略。
- `src/foundation/services/sync_v2/dataset_strategies/__init__.py`
  - 注册 `build_stk_mins_units`。
- `src/foundation/models/raw/raw_stk_mins.py`
  - 新增 Raw ORM。
- `src/foundation/models/all_models.py`
  - 注册新增模型。
- `src/app/model_registry.py`
  - 确保 Alembic/app 启动能加载新增模型。
- `src/foundation/dao/factory.py`
  - 注册 `raw_stk_mins` DAO。

### 12.2 Alembic

- 新增 migration：
  - 创建 `raw_tushare.stk_mins`。
  - 创建月分区与 default 分区。
  - 创建主键与索引。
  - 创建 `core_serving.equity_minute_bar` 普通 View。
- 不创建 `core_serving.equity_minute_bar` 物理表，不创建 materialized view。

### 12.3 Ops

- `src/ops/specs/job_spec.py`
  - 新增 `sync_minute_history` strategy/category。
- `src/ops/specs/registry.py`
  - 注册 `sync_minute_history.stk_mins`。
  - 明确不加入 `DAILY_SYNC_RESOURCES`。
- `src/ops/runtime/dispatcher.py`
  - 接入 `sync_minute_history` 到 V2 sync service。
- `src/ops/queries/manual_action_query_service.py`
  - 让手动动作能展示该任务的交易日、频度、股票池分页参数。

### 12.4 CLI

- `src/cli.py` 或 `src/cli_parts/*`
  - 新增 `goldenshare sync-minute-history`。
  - 支持 `--freq`、`--ts-code`、`--trade-date`、`--start-date`、`--end-date`、`--offset`、`--limit`。
  - 输出全市场批次进度。

### 12.5 Frontend

- 手动维护表单：
  - `freq` 多选。
  - 日期组件只允许交易日。
  - 全市场分批参数。
  - 固定交易时段说明。

### 12.6 文档

- `docs/datasets/stk-mins-dataset-development.md`
  - 本方案。
- `docs/README.md`
  - 增加本方案入口。
- `docs/ops/tushare-request-execution-policy-v1.md`
  - 实现时补充 `stk_mins` 请求执行口径。
- `docs/architecture/dataset-date-model-consumer-guide-v1.md`
  - 如日期模型消费方需要区分分钟策略，补充消费说明。

## 13. 测试与门禁

### 13.1 单元测试

- `tests/test_sync_v2_validator.py`
  - `freq` 必填与枚举校验。
  - `trade_date` 与 `start_date/end_date` 二选一。
- `tests/test_sync_v2_planner.py`
  - 单股票、多 `freq`、单交易日生成 `2 x freq_count` 个时段 unit。
  - 全市场模式按股票池扇出，并支持 `offset/limit`。
  - 区间模式只展开交易日。
- `tests/test_sync_v2_worker_client.py`
  - Tushare 请求分页 `limit=8000`、`offset` 递增。
- `tests/test_sync_v2_linter.py`
  - `stk_mins` contract 可通过 lint。
- `tests/architecture/test_sync_v2_registry_guardrails.py`
  - `stk_mins` 位于 `market_equity` 域。

### 13.2 模型与写入测试

- ORM 主键、索引、字段类型测试。
- 归一化测试：
  - `trade_time` 解析。
  - `trade_date` 派生。
  - `freq/session_tag` 注入。
  - `raw_payload` 默认不写。
  - 异常行拒绝。

### 13.3 最小真实冒烟

在确认分钟权限已开通后执行小窗口：

```bash
GOLDENSHARE_ENV_FILE=.env.web.local goldenshare sync-minute-history \
  --ts-code 600000.SH \
  --freq 30min \
  --trade-date 2026-04-23
```

全市场小批次冒烟：

```bash
GOLDENSHARE_ENV_FILE=.env.web.local goldenshare sync-minute-history \
  --freq 60min \
  --trade-date 2026-04-23 \
  --offset 0 \
  --limit 5
```

验证：

- `raw_tushare.stk_mins` 有写入。
- `core_serving.equity_minute_bar` 可查询到同一批数据。
- `trade_time` 都落在 `09:30~11:30` 或 `13:00~15:00`。
- `freq/session_tag/trade_date` 正确。
- Ops 任务详情展示 `fetched/written/rejected`。
- `sync-v2-lint-contracts` 通过。

## 14. 风险与控制

| 风险 | 影响 | 控制方式 |
| --- | --- | --- |
| 未开通 Tushare 分钟权限 | 真实同步失败 | 实现前或冒烟前先确认权限；错误码透出为权限问题 |
| 数据量极大 | 任务长、库膨胀、锁压力 | 单物理表 + 普通 View；不写默认 raw_payload；全市场支持 `offset/limit` 分批 |
| View 被误改成物化视图 | 又产生一份大数据 | 明确只允许普通 View，禁止 materialized view |
| 全市场 unit 过多 | 任务规划和展示压力大 | `ts_code x freq x trade_date x session` 明确拆分，并输出进度 |
| 股票池口径不清 | 漏拉退市历史数据或拉取过多 | 默认使用 Tushare stock_basic 全证券池；后续再加上市状态过滤 |
| 分区缺失导致写入失败 | 回补失败 | migration 创建历史月分区 + default 分区 |
| 分钟完整性审计口径不清 | 误报缺失 | 第一期不纳入完整性审计，后续单独设计交易时段模型 |

## 15. 建议实施顺序

1. 确认 Tushare 分钟权限。
2. 新增 Alembic + Raw ORM + DAO + Core Serving View。
3. 新增 V2 fields/contract/date_model/strategy/normalizer。
4. 新增 `sync-minute-history` CLI。
5. 接入 Ops 手动任务。
6. 补测试门禁。
7. 用单股票、单交易日、单频度真实冒烟。
8. 用全市场小批次真实冒烟。
9. 再评估是否加入自动任务或更大批量 runbook。

## 16. 需要评审拍板的问题

1. 物理表只保留 `raw_tushare.stk_mins`，并创建 `core_serving.equity_minute_bar` 普通 View，是否确认？
2. `raw_payload` 是否按建议保留字段但默认不写入？
3. 全市场股票池默认是否包括 `L/P/D` 全状态？
4. 全市场模式是否要求必须传 `offset/limit`，还是允许不传时一次规划全量？
5. 90 分钟线是否按建议落到 `core_serving.equity_minute_bar_derived`？
