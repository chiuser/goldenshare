# Tushare 股票历史分钟行情（`stk_mins`）数据集开发方案

## 1. 目标与边界

- 目标：新增 Tushare `stk_mins` 数据集，接入 A 股历史分钟行情，支持 `1min/5min/15min/30min/60min` 五种频度的按交易日或交易日区间拉取。
- 数据源文档：`docs/sources/tushare/股票数据/行情数据/0370_股票历史分钟行情.md`
- 本期只接入当前 Sync V2 主链路，不新增 V1 路径，不回流到 `src/platform` 或 `src/operations`。
- 因分钟数据量巨大，本数据集不做 Raw 表与 Core Serving 表双份存储；采用“Raw 单物理表 + Core Serving 只读 View”的方式降低磁盘消耗，同时保留服务层访问入口。
- 支持全市场同步：未指定 `ts_code` 时，按 Tushare `stock_basic` 证券池中的 `ts_code` 扇出请求。
- 不加入每日自动工作流；第一期通过独立 CLI `goldenshare sync-minute-history` 和 Ops 手动任务触发。
- 用户侧时间选择只能选择交易日或交易日区间，不能选择具体时间；程序内部转换为 `09:00:00~19:00:00` datetime 窗口后分页请求。

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
| `start_date` | `datetime` | 否 | 开始时间，如 `2023-08-25 09:00:00` | 不由用户直接填写；程序按用户选择的交易日或区间起点生成 |
| `end_date` | `datetime` | 否 | 结束时间，如 `2023-08-25 19:00:00` | 不由用户直接填写；程序按用户选择的交易日或区间终点生成 |
| `limit` | `int` | 否 | 单次返回数据长度 | 内部固定分页参数，默认 `8000` |
| `offset` | `int` | 否 | 请求数据的开始位移量 | 内部分页递增 |

### 2.2 输出参数

| 字段 | 类型 | 说明 | 落库口径 |
| --- | --- | --- | --- |
| `ts_code` | `str` | 股票代码 | `VARCHAR(16)`，必填 |
| `trade_time` | `str` | 交易时间 | 解析为 `TIMESTAMP WITHOUT TIME ZONE`，必填 |
| `open` | `float` | 开盘价 | `REAL`，入库前保留 2 位小数 |
| `close` | `float` | 收盘价 | `REAL`，入库前保留 2 位小数 |
| `high` | `float` | 最高价 | `REAL`，入库前保留 2 位小数 |
| `low` | `float` | 最低价 | `REAL`，入库前保留 2 位小数 |
| `vol` | `int` | 成交量（股） | `BIGINT`，保留整数语义并覆盖大成交量分钟 bar |
| `amount` | `float` | 成交金额（元） | `REAL` |

## 3. 现有“Raw/Core 同表映射”参考与本次口径

当前代码里已有类似写入模式：

- `biying_equity_daily` 的 DatasetDefinition 使用 `write_path="raw_only_upsert"`。
- 其 `raw_dao_name` 与 `core_dao_name` 都指向 `raw_biying_equity_daily_bar`。
- `target_table` 指向 `raw_biying.equity_daily_bar`。

`stk_mins` 采用同类写入口径，但额外提供 Core Serving 只读 View：

- 只有一个物理表：`raw_tushare.stk_mins`。
- 写入走 `raw_only_upsert`。
- DatasetDefinition 中 `raw_dao_name="raw_stk_mins"`，`core_dao_name="raw_stk_mins"`。
- `target_table="raw_tushare.stk_mins"`。
- 服务层访问入口：`core_serving.equity_minute_bar` 普通 View，查询 `raw_tushare.stk_mins`。
- Ops 写入进度以 `raw_tushare.stk_mins` 为目标表；后续 Biz/查询层优先通过 `core_serving.equity_minute_bar` 访问。

这样做的收益：

- 不重复存储 Raw 和 Serving，节省接近一倍空间。
- 保留 DatasetDefinition / writer 的统一执行路径。
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
| 请求构建 | `src/foundation/ingestion/request_builders.py` | 注册 `build_stk_mins_units`，生成分钟线执行单元 |
| 定义域 | `src/foundation/datasets/definitions/market_equity.py` | 股票行情类数据集 |

说明：旧模板中提到 `Raw -> Std -> Serving`，但当前 V2 主链路已收敛为按数据集选择写入路径；本数据集不引入 Std 层，不创建 `core_serving.equity_minute_bar` 物理表，只创建同名服务层 View。

## 5. 数据模型设计

### 5.1 主表：`raw_tushare.stk_mins`

字段设计：

| 字段 | 类型 | 约束 | 含义 |
| --- | --- | --- | --- |
| `ts_code` | `VARCHAR(16)` | NOT NULL | 股票代码 |
| `freq` | `SMALLINT` | NOT NULL | 分钟频度，固定写入 `1/5/15/30/60` |
| `trade_time` | `TIMESTAMP WITHOUT TIME ZONE` | NOT NULL | 分钟 bar 时间 |
| `open` | `REAL` | NULL | 开盘价，入库前保留 2 位小数 |
| `close` | `REAL` | NULL | 收盘价，入库前保留 2 位小数 |
| `high` | `REAL` | NULL | 最高价，入库前保留 2 位小数 |
| `low` | `REAL` | NULL | 最低价，入库前保留 2 位小数 |
| `vol` | `BIGINT` | NULL | 成交量（股）；Tushare 类型为整数，但单个 60 分钟 bar 可能超过 PostgreSQL `INTEGER` 上限 |
| `amount` | `REAL` | NULL | 成交金额（元） |

主键与索引：

- 主键：`(ts_code, freq, trade_time)`
- 不额外创建普通 BTree 索引，先依赖主键服务核心写入与按股票查询。
- 按交易日查询时，上层可使用 `trade_time >= :date AND trade_time < :date + interval '1 day'`，不要在 WHERE 中写 `trade_time::date = :date`。

分区策略：

- 按 `trade_time` RANGE 月分区。
- 分区粒度建议按月；分钟行情数据量远大于日频，月分区便于后续按月清理、回补和查询。
- 必须保留 `DEFAULT` 分区，避免用户回补很早或未来日期时因缺少分区导致任务失败。

### 5.2 不保存逐行审计冗余字段

`stk_mins` 数据量极大，不保留以下逐行冗余字段：

- `trade_date`：由 `trade_time::date` 派生。
- `session_tag`：可由 `trade_time` 所属交易时段推导，不落库。
- `api_name`：表名与 DatasetDefinition 已表达来源，不逐行重复保存。
- `fetched_at`：任务级抓取时间由 TaskRun/进度事件表达，不逐行保存。
- `raw_payload`：不保存原始响应行，避免磁盘放大。

### 5.3 服务层 View：`core_serving.equity_minute_bar`

建议创建普通 View：

```sql
CREATE OR REPLACE VIEW core_serving.equity_minute_bar AS
SELECT
    ts_code,
    freq,
    trade_time,
    trade_time::date AS trade_date,
    open,
    close,
    high,
    low,
    vol,
    amount,
    'tushare'::varchar(32) AS source
FROM raw_tushare.stk_mins;
```

设计约束：

- 这是普通 View，不是 materialized view。
- 不承载写入，不需要 DAO 写入。
- Biz 查询优先面向该 View。
- `trade_date` 只在 View 中派生，方便上层按日期筛选和展示。

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

`stk_mins` 的请求由“交易日或交易日区间 + 程序内部 datetime 窗口”驱动，不暴露具体时间选择给用户。

建议使用当前数据集日期模型体系中的交易日模型，并增加分钟策略语义：

| 字段 | 建议值 | 说明 |
| --- | --- | --- |
| `date_axis` | `trade_open_day` | 只允许开市交易日 |
| `bucket_rule` | `every_open_day` | 区间按每个交易日展开 |
| `window_mode` | `point_or_range` | 支持单交易日或交易日区间 |
| `input_shape` | `trade_date_or_start_end` | 用户侧选择交易日或交易日区间 |
| `observed_field` | `trade_time` | 数据状态以分钟 bar 时间观测；日级状态由 `max(trade_time)::date` 派生 |
| `audit_applicable` | `false`（第一期） | 分钟级完整性审计依赖交易时段和频度规则，第一期先不纳入 |
| `not_applicable_reason` | `minute completeness audit requires trading-session calendar` | 明确不纳入第一期审计的原因 |

请求窗口由 `stk_mins` 策略固定：

```text
单日：trade_date 09:00:00 ~ trade_date 19:00:00
区间：start_date 09:00:00 ~ end_date 19:00:00
```

注意：

- 日历组件只允许选择交易日或交易日区间，不能选择小时、分钟、秒。
- 区间执行时不再按交易日逐日拆分，而是生成一个连续 datetime 大窗口。
- 不再按上午、下午 session 拆请求；入库时只校验返回行 `trade_time` 是否落在合法交易时段。
- 上游 `start_date/end_date` 虽然是 datetime 参数，但它们只由程序内部生成，不作为用户侧参数暴露。

## 7. 请求策略

### 7.1 默认规则

- `freq` 必填，可单选或多选。
- `trade_date` 或 `start_date + end_date` 必填。
- `ts_code` 可选；未传时使用 Tushare 股票池扇出全市场。
- `limit=8000`。
- `offset` 从 `0` 开始递增，直到返回行数 `< 8000`。
- 不加入每日自动工作流；由专用 CLI 和 Ops 手动任务触发。

### 7.2 股票池扇出

当用户未指定 `ts_code` 时：

1. 从 Tushare `stock_basic` 已落库结果读取 `ts_code`。
2. 建议优先使用 `core_serving.security_serving` 中 `source='tushare'`、`security_type='EQUITY'` 的代码池；如果需要严格按 Raw 源表，则使用 `raw_tushare.stock_basic`。
3. 默认包括 `L/P/D` 状态，避免历史回补漏掉退市或暂停上市证券；如后续运营侧需要，可再增加上市状态过滤。
4. 不暴露股票池 `offset/limit`；未传 `ts_code` 时，直接按当前 Tushare 股票池全量扇出。

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
证券代码 x 频度 x datetime 窗口
```

### 7.3 频度扇开

当用户选择多个 `freq` 时，每个频度单独请求：

```text
stk_mins(ts_code=600000.SH, freq=30min, start_date=2026-04-23 09:00:00, end_date=2026-04-23 19:00:00)
stk_mins(ts_code=600000.SH, freq=60min, start_date=2026-04-23 09:00:00, end_date=2026-04-23 19:00:00)
```

### 7.4 参数映射

我方内部参数：

```text
ts_code?         # 可选，不传则全市场
freq             # 必填，可多选
trade_date?      # 单日
start_date?      # 区间开始交易日
end_date?        # 区间结束交易日
```

请求 Tushare 参数：

```text
ts_code
freq
start_date = YYYY-MM-DD 09:00:00
end_date = YYYY-MM-DD 19:00:00
limit = 8000
offset = 0, 8000, 16000, ...
```

说明：这里只保留 Tushare 请求 `limit/offset` 这一类内部分页，固定按 `8000` 递增，不作为用户输入参数暴露。

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

### 8.2 DatasetDefinition

位置：`src/foundation/datasets/definitions/market_equity.py`

建议定义：

- `dataset_key="stk_mins"`
- `display_name="股票历史分钟行情"`
- `date_model=build_date_model("stk_mins")`
- `source.api_name="stk_mins"`
- `source.source_fields=STK_MINS_FIELDS`
- `planning.request_builder_key="build_stk_mins_units"`
- `planning.pagination_mode="offset_limit"`
- `planning.page_limit=8000`
- `write.raw_dao_name="raw_stk_mins"`
- `write.core_dao_name="raw_stk_mins"`
- `write.target_table="raw_tushare.stk_mins"`

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
约束：

- `trade_date` 与 `start_date/end_date` 二选一。
- `freq` 不能为空。
- `freq` 值必须在 `1min/5min/15min/30min/60min`。
- 如果不传 `ts_code`，按股票池全量扇出；页面和 CLI 需要清晰提示分钟数据量较大。

### 8.4 请求构建函数

位置：`src/foundation/ingestion/request_builders.py`

职责：

- 校验 `freq` 值。
- 解析单交易日或交易日区间，生成一个 `09:00:00~19:00:00` datetime 窗口。
- 未传 `ts_code` 时，从 Tushare 股票池加载证券代码并全量扇出。
- 将维度拆成：`ts_code x freq x datetime_window`。
- 为每个执行单元生成 Tushare 请求参数。
- 为每个执行单元填充通用进度游标元信息，如 `unit=stock`、`ts_code`、`security_name`、`freq`、`unit_fetched`、`unit_written`。
- 设置分页参数 `limit=8000`、`offset` 递增。

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
- `freq`：从请求上下文注入到每行，并由 `1min/5min/15min/30min/60min` 归一化为 `1/5/15/30/60`。
- `open/close/high/low`：转为浮点数并保留 2 位小数。
- `vol`：转为整数，非整数值拒绝。
- `amount`：转为浮点数。
- 必填校验：`ts_code/freq/trade_time`。
- 不写入 `trade_date/session_tag/api_name/fetched_at/raw_payload`。

拒绝规则：

- `trade_time` 为空或无法解析：拒绝。
- `ts_code` 为空：拒绝。
- `freq` 不在允许枚举：拒绝。

## 9. Ops 与前端接入

### 9.1 DatasetDefinition action

不加入自动盘后工作流。

新增维护动作：

| 任务 | 说明 |
| --- | --- |
| `stk_mins.maintain` | 股票历史分钟行情维护 |

参数：

- `ts_code`：可选。
- `freq`：必填，多选枚举。
- `trade_date`：单日模式。
- `start_date/end_date`：区间模式。
使用专用分钟线任务的原因：

- 分钟行情虽然是历史数据，但请求语义不是普通日频历史同步。
- 专用任务能把 UI、CLI、进度和风险提示做清楚。
- 避免把任意 datetime 或分钟时段逻辑污染到普通数据集维护动作。

### 9.2 手动维护页面

需要支持：

- `ts_code` 文本输入；留空表示全市场。
- `freq` 多选枚举。
- 日期选择器只允许选择交易日。
- 单日模式：选择一个交易日。
- 区间模式：选择开始交易日和结束交易日。
- 展示说明：用户只选交易日；系统内部按 `09:00~19:00` 大窗口请求，落库时校验真实 `trade_time` 必须位于交易时段。
- 不提供小时、分钟、秒输入控件。
- 提示文案：分钟数据量很大；未填股票代码时会按当前股票列表全市场扇开请求。

不支持：

- 不支持用户任意输入 `09:42:13` 这类自定义时间。
- 不支持用户修改内部请求窗口边界。
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
- 自动任务应等权限、磁盘容量、失败恢复策略验证稳定后再单独评审。

## 10. CLI 接入

新增专用 CLI：

```bash
goldenshare sync-minute-history \
  --freq 30min \
  --start-date 2026-04-23 \
  --end-date 2026-04-23 \
  --ts-code 600000.SH
```

CLI 行为：

- `--ts-code` 可选。
- 未传 `--ts-code` 时，从股票池读取证券代码。
- 通过 V2 进度上报输出执行单元进度。
- 每个 unit 输出 `unit=stock ts_code security_name freq unit_fetched/unit_written fetched/written/rejected`；其中 `fetched/written` 为任务累计，`unit_fetched/unit_written` 为当前 unit。

## 11. 对账与数据质量

### 11.1 对账范围

因为只有一张物理表，不做 Raw/Core 行数对账。

建议对账改为表内质量检查：

- 按 `ts_code + freq + trade_date` 检查重复主键。
- 检查 `trade_time` 是否为空。
- 检查 `trade_time` 是否落在固定交易时段内。
- 检查 `freq` 是否为允许值。
- 抽样检查全市场写入行数是否大于 0。
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

- `src/foundation/datasets/fields.py`
  - 新增 `STK_MINS_FIELDS`。
- `src/foundation/datasets/definitions/market_equity.py`
  - 新增 `stk_mins` DatasetDefinition 与日期模型。
- `src/foundation/ingestion/request_builders.py`
  - 注册 `build_stk_mins_units`。
- `src/foundation/ingestion/row_transforms.py`
  - 新增 `_stk_mins_row_transform`。
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
  - 创建主键。
  - 创建 `core_serving.equity_minute_bar` 普通 View。
- 不创建 `core_serving.equity_minute_bar` 物理表，不创建 materialized view。

### 12.3 Ops

- `src/ops/action_catalog.py`
  - 仅承接非数据集维护动作与 workflow；单数据集维护动作必须从 DatasetDefinition 派生。
- `src/ops/runtime/task_run_dispatcher.py`
  - 通过 `DatasetActionRequest -> DatasetExecutionPlan -> IngestionExecutor` 主链执行，不新增旧执行分类。
- `src/ops/queries/manual_action_query_service.py`
  - 从 DatasetDefinition 派生手动动作展示所需的交易日和频度参数。

### 12.4 CLI

- `src/cli.py` 或 `src/cli_parts/*`
  - 新增 `goldenshare sync-minute-history`。
  - 支持 `--freq`、`--ts-code`、`--trade-date`、`--start-date`、`--end-date`。
  - 输出 V2 执行进度。

### 12.5 Frontend

- 手动维护表单：
  - `freq` 多选。
  - 日期组件只允许交易日。
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

- `tests/test_dataset_request_validator.py`
  - `freq` 必填与枚举校验。
  - `trade_date` 与 `start_date/end_date` 二选一。
- `tests/test_dataset_unit_planner.py`
  - 单股票、多 `freq`、单交易日生成 `2 x freq_count` 个时段 unit。
  - 全市场模式按股票池全量扇出。
  - 区间模式只展开交易日。
- `tests/test_ingestion_source_client.py` 或等价请求执行测试
  - Tushare 请求分页 `limit=8000`、`offset` 递增。
- `tests/test_ingestion_linter.py`
  - `stk_mins` 定义可通过 lint。
- `tests/architecture/test_dataset_runtime_registry_guardrails.py`
  - `stk_mins` 位于 `market_equity` 域。

### 13.2 模型与写入测试

- ORM 主键、索引、字段类型测试。
- 归一化测试：
  - `trade_time` 解析。
  - `freq` 从字符串归一化为整数。
  - 价格、成交量、成交金额类型转换。
  - 不输出 `trade_date/session_tag/api_name/fetched_at/raw_payload`。
  - 异常行拒绝。

### 13.3 最小真实冒烟

在确认分钟权限已开通后执行小窗口：

```bash
GOLDENSHARE_ENV_FILE=.env.web.local goldenshare sync-minute-history \
  --ts-code 600000.SH \
  --freq 30min \
  --trade-date 2026-04-23
```

全市场冒烟：

```bash
GOLDENSHARE_ENV_FILE=.env.web.local goldenshare sync-minute-history \
  --freq 60min \
  --trade-date 2026-04-23
```

验证：

- `raw_tushare.stk_mins` 有写入。
- `core_serving.equity_minute_bar` 可查询到同一批数据。
- `trade_time` 都落在 `09:30~11:30` 或 `13:00~15:00`。
- raw 表中 `freq` 为 `1/5/15/30/60` 整数，View 中 `trade_date` 可由 `trade_time` 派生查询。
- Ops 任务详情展示当前股票、频度、`unit_fetched/unit_written` 与累计 `fetched/written/rejected`。
- `goldenshare ingestion-lint-definitions` 通过。

## 14. 风险与控制

| 风险 | 影响 | 控制方式 |
| --- | --- | --- |
| 未开通 Tushare 分钟权限 | 真实同步失败 | 实现前或冒烟前先确认权限；错误码透出为权限问题 |
| 数据量极大 | 任务长、库膨胀、锁压力 | 单物理表 + 普通 View；不写逐行 raw payload；全市场按股票池扇出，真实执行前先用单股票冒烟确认 |
| View 被误改成物化视图 | 又产生一份大数据 | 明确只允许普通 View，禁止 materialized view |
| 全市场 unit 过多 | 任务规划和展示压力大 | `ts_code x freq x datetime_window` 明确拆分，并输出当前股票、频度与当前 unit 读取/写入 |
| 股票池口径不清 | 漏拉退市历史数据或拉取过多 | 默认使用 Tushare stock_basic 全证券池；后续再加上市状态过滤 |
| 分区缺失导致写入失败 | 回补失败 | migration 创建历史月分区 + default 分区 |
| 分钟完整性审计口径不清 | 误报缺失 | 第一期不纳入完整性审计，后续单独设计交易时段模型 |

## 15. 建议实施顺序

1. 确认 Tushare 分钟权限。
2. 新增 Alembic + Raw ORM + DAO + Core Serving View。
3. 新增字段常量、DatasetDefinition、日期模型、请求构建与 normalizer。
4. 新增 `sync-minute-history` CLI。
5. 接入 Ops 手动任务。
6. 补测试门禁。
7. 用单股票、单交易日、单频度真实冒烟。
8. 再评估全市场真实执行窗口与运行风险。
9. 再评估是否加入自动任务或更大批量 runbook。

## 16. 需要评审拍板的问题

1. 物理表只保留 `raw_tushare.stk_mins`，并创建 `core_serving.equity_minute_bar` 普通 View：已确认。
2. `raw_payload/api_name/fetched_at/trade_date/session_tag` 不落库：已确认。
3. 全市场股票池默认包括 `L/P/D` 全状态：已确认。
4. 90 分钟线后续落到独立派生表：已确认，表名与字段另行设计。
