# `etf_share_size` 低层设计 LLD v1

状态：代码已实现，待运营部署、迁移、同步和页面验收。
对应方案：[ETF 份额规模数据集接入方案](/Users/congming/github/goldenshare/docs/datasets/etf-share-size-dataset-development.md)
审计日期：2026-08-22

## 1. 本 LLD 的边界

本 LLD 只落地 `etf_share_size` 的 Goldenshare 代码设计，不执行部署、Alembic 迁移、生产同步、回补或页面验收。首期固定：

- raw 保存 Tushare 返回的全部当日结果，不用 ETF 激活池过滤。
- `core_serving.etf_share_size` 只做普通 view，禁止建立第二份 serving 物理表。
- 手动任务和普通自动任务可用，不加入既有工作流，不新增专用 probe。
- 默认按一个交易日生成一个全市场 unit；区间由 resolver 按交易日展开，不按 ETF 代码拆 unit。
- `ts_code` 仅作为单 ETF 局部维护过滤，不改变默认全量快照语义；不暴露 `exchange`、`limit`、`offset`。
- Ops/TaskRun/freshness 状态写入与业务数据事务隔离。

## 2. 代码审计结论

### 2.1 当前接入状态

本轮已新增 `etf_share_size` 的 DatasetDefinition、request builder、custom unit builder、raw ORM、DAO 属性、Alembic 迁移、serving view、freshness 登记和 Ops catalog item。既有 ETF 主线 `etf_sh_cons`、`fund_daily` 未改动。

### 2.2 已确认的复用点与新增点

| 层 | 当前真实实现 | 本数据集处理 |
| --- | --- | --- |
| Definition | `src/foundation/datasets/definitions/market_fund.py` 的 `DATASET_ROWS` | 新增一条 Definition；不改已有 ETF 定义 |
| resolver/planner | `DatasetUnitPlanner.plan()` 按 `unit_builder_key` 选择 custom builder；generic planner 对 `every_open_day` 使用 `TradeCalendarDAO` | 新增 `build_etf_share_size_units`，明确日快照和单 code 过滤；不把源接口区间直接传给 Tushare |
| request builder | `request_builders.py` 按 Definition 中的函数名动态解析 | 新增 `_etf_share_size_params`，只生成 `trade_date`，必要时追加单个 `ts_code` |
| source client | `DatasetSourceClient._iter_request_pages()` 统一追加 `limit/offset`，短页结束 | 复用；`page_limit=5000` |
| normalizer | `DatasetNormalizer` 先做日期/Decimal 转换，再执行 `row_transform_name` | 新增轻量文本清洗 transform，不派生业务字段 |
| writer | `DatasetWriter._write_raw_only_upsert()` 只调用 raw DAO | 复用；冲突键为 `(trade_date, ts_code)` |
| DAO | `DAOFactory` 暴露 `GenericDAO`，模型由 `table_model_registry` 自动发现 | 新增 raw model 和 `DAOFactory.raw_etf_share_size` |
| freshness | `FRESHNESS_POLICY_BY_DATASET` 是单一映射，`_builder.py` 投影到 Definition | 登记 `etf_share_size -> continuous_open_day` |
| Ops catalog | `OPS_DATASET_DEFAULT_VIEW` 显式维护展示分组；manual/catalog query 读取 Definition 的输入和能力 | 增加 `etf_fund` item；不在前端另造字段 |
| workflow/probe | 当前数据集未存在相关入口 | 本期不增加 workflow 或 probe |

### 2.3 CodeGraph 审计范围

已使用 CodeGraph（项目根 `/Users/congming/github/goldenshare`）检查：

- `DatasetUnitPlanner.plan`、custom unit builder 分发、`DatasetActionResolver` 到 `DatasetExecutionPlan` 的投影；
- `_etf_sh_cons_params`、`DatasetSourceClient` 分页、`DatasetWriter._write_raw_only_upsert`、`DAOFactory`；
- `DatasetNormalizer`、`table_model_registry`、`FRESHNESS_POLICY_BY_DATASET`、Ops catalog/manual action/freshness 投影；
- `EtfSeriesActiveDAO` 与 `EtfSeriesActiveSeedService`，确认本数据集不应接入 ETF active pool。

CodeGraph 索引状态正常：2,563 个文件、45,133 个节点、103,096 条边。当前审计没有发现需要修改依赖矩阵的跨子系统边界。

## 3. 源接口契约与真实证据

源文档：[0408 ETF 份额规模](/Users/congming/github/goldenshare/docs/sources/tushare/ETF专题/0408_ETF份额规模.md)。接口为 `etf_share_size`，单次最大 5,000 条；字段为：

`trade_date, ts_code, etf_name, total_share, total_size, nav, close, exchange`

前置实测证据：

| 请求 | 实测结果 | 设计结论 |
| --- | --- | --- |
| `{}` | 5,000 条，日期混杂 | 不能当作全集 |
| `ts_code=510300.SH` | 3,297 条，跨历史日期 | 只适合局部过滤，不作为默认规划方式 |
| `trade_date=20260821` | 1,637 条，均为目标日 | 默认单日全市场 unit 可行 |
| `ts_code=510300.SH,start_date=20260818,end_date=20260821` | 4 条 | 单 ETF 区间可返回历史，但不作为默认区间主链 |
| 项目 connector，`trade_date=20260821,limit=5000,offset=0` | 1,637 条，显式 8 字段齐备，`(trade_date, ts_code)` 无重复 | 默认 unit 的短页和字段契约已实测 |
| 项目 connector，`trade_date=20260821,limit=5000,offset=5000` | 0 条 | 默认 unit 的短页终止边界已实测 |
| 项目 connector，不传业务日期、连续两页 | 两页各 5,000 条，跨 4 个日期且跨页有 91 个重复业务键 | 无日期请求不能进入默认维护链路 |
| 显式全部字段 | 8 个字段均可返回，`nav/close` 需要显式请求 | `source_fields` 必须列全 8 个字段 |

这组证据不代表生产快照永远少于 5,000。实施时必须用实际 Definition + 项目 connector 重跑同日分页验证；若真实日结果超过 5,000，必须先重新评估是否按交易所拆 unit，不能静默接受截断。

## 4. 三层语义与输入契约

| 层 | 固定语义 | 示例 |
| --- | --- | --- |
| Ops/TaskRun | 保存用户意图：单日、区间、可选单 code | `trade_date=2026-08-21` |
| resolver/planner | 把区间展开为开市日 anchors；每个 anchor 生成一个全市场 unit | `2026-08-21` |
| request builder | 把 unit 的日期格式化为 Tushare 参数 | `{"trade_date":"20260821"}` |

建议 Definition 输入：

```python
"input_model": {
    "time_fields": ("trade_date", "start_date", "end_date"),
    "filters": ("ts_code",),
    "required_groups": (),
    "mutually_exclusive_groups": (("trade_date", "start_date", "end_date"),),
}
```

实际代码中仍使用 `DatasetInputField` 对象，以上仅表达字段关系。`ts_code` 的 `multi_value=False`，planner 还必须拒绝逗号分隔的多个 code，避免运营误以为可以拼接多个对象。

## 5. Definition 设计

新增条目位置：`src/foundation/datasets/definitions/market_fund.py` 的 `DATASET_ROWS`。

关键事实：

```python
identity.dataset_key = "etf_share_size"
identity.display_name = "ETF 份额规模"
domain = {"domain_key": "index_fund", "domain_display_name": "指数 / ETF"}
source.api_name = "etf_share_size"
source.source_fields = (
    "trade_date", "ts_code", "etf_name", "total_share",
    "total_size", "nav", "close", "exchange",
)
source.source_doc_id = "tushare.etf_share_size"
source.request_builder_key = "_etf_share_size_params"
source.release_policy = "same_day"
date_model = {
    "date_axis": "trade_open_day",
    "bucket_rule": "every_open_day",
    "window_mode": "point_or_range",
    "input_shape": "trade_date_or_start_end",
    "observed_field": "trade_date",
    "audit_applicable": False,
}
planning = {
    "universe_policy": "no_pool",
    "pagination_policy": "offset_limit",
    "page_limit": 5000,
    "unit_builder_key": "build_etf_share_size_units",
}
storage = {
    "raw_dao_name": "raw_etf_share_size",
    "core_dao_name": "raw_etf_share_size",
    "target_table": "raw_tushare.etf_share_size",
    "delivery_mode": "raw_with_serving_view",
    "layer_plan": "raw->serving_view",
    "serving_table": "core_serving.etf_share_size",
    "raw_table": "raw_tushare.etf_share_size",
    "conflict_columns": ("trade_date", "ts_code"),
    "write_path": "raw_only_upsert",
}
normalization = {
    "date_fields": ("trade_date",),
    "decimal_fields": ("total_share", "total_size", "nav", "close"),
    "required_fields": ("trade_date", "ts_code"),
    "row_transform_name": "_etf_share_size_row_transform",
}
capabilities.actions = (maintain with manual_enabled=True,
                        schedule_enabled=True,
                        retry_enabled=True,
                        supported_time_modes=("point", "range"))
observability.freshness_policy = "continuous_open_day"
```

`completeness.scope` 为 `not_applicable`：本期不以 ETF 数量建立日期 × 对象完整性矩阵。`source.release_policy` 不新增新枚举；19:00 后再运行是运营排程约定，不在本 LLD 中新增 probe 或新的发布模型。

## 6. Unit 与请求生成

### 6.1 `build_etf_share_size_units`

实现位置：`src/foundation/ingestion/unit_planner.py` 的 `_CUSTOM_UNIT_BUILDERS` 旁及其 builder 函数。

规则：

1. `point_incremental`：要求 `request.trade_date`，生成一个 unit。
2. `range_rebuild`：要求 `start_date/end_date`，调用已有交易日历 DAO 生成区间内开市日，每个开市日一个 unit。
3. `universe_policy=no_pool`：不读取 `EtfSeriesActiveDAO`，不查 `etf_basic`，不发起隐藏对象池 fallback。
4. 没有 `ts_code` 时，unit 请求只含目标日；有单个 `ts_code` 时，在每个 unit 中追加该 code。
5. unit 的 `trade_date` 是业务日期；`progress_context` 使用 ISO 字符串，不能把 Python `date` 直接写入 TaskRun JSON。

unit 示例：

```json
{
  "unit_id": "etf_share_size:2026-08-21:0",
  "trade_date": "2026-08-21",
  "request_params": {"trade_date": "20260821"},
  "pagination_policy": "offset_limit",
  "page_limit": 5000
}
```

单 ETF 局部修复：

```json
{
  "request_params": {"ts_code": "510300.SH", "trade_date": "20260821"}
}
```

### 6.2 `_etf_share_size_params`

实现位置：`src/foundation/ingestion/request_builders.py`。函数只读取 resolver 已归一化的 unit 值，不负责展开日期：

- point/range 展开后的每个 unit 都输出 `trade_date=YYYYMMDD`；
- 显式单 code 时追加规范化后的 `ts_code`；
- 不输出 `start_date/end_date`、`exchange`、`limit`、`offset`；
- 非 `point_incremental` / `range_rebuild` 或日期缺失时抛出已有结构化 planning/request 错误。

### 6.3 分页、事务与性能

`DatasetSourceClient` 对每个 unit 依次请求：`limit=5000, offset=0, 5000, ...`，直到返回短页。一个 unit 的所有页必须先合并，再 normalize、write、commit；不能一页一事务，也不能把多个日期合并为一个大事务。

按当前实测：单日 1 unit、约 1,637 行、通常 1 页；一年约 245 个开市日 unit。实际请求量必须以 connector 日志中的 page_count 为准，不能把 unit 数直接当 HTTP 请求数。

## 7. Schema、模型、DAO 与 view

### 7.1 raw 表

迁移已创建为 `20260822_000140_add_etf_share_size_dataset.py`，并且在创建时接真实 head `20260822_000139`。部署前仍须复核部署分支的 Alembic head。

实际表：`raw_tushare.etf_share_size`。

| 列 | 类型 | 空值 | 说明 |
| --- | --- | --- | --- |
| `trade_date` | `DATE` | 否 | 源字段，主键 |
| `ts_code` | `VARCHAR(16)` | 否 | 源字段，主键 |
| `etf_name` | `VARCHAR(256)` | 是 | 源字段 |
| `total_share` | `NUMERIC(24,6)` | 是 | 源字段 |
| `total_size` | `NUMERIC(24,6)` | 是 | 源字段 |
| `nav` | `NUMERIC(18,8)` | 是 | 源字段 |
| `close` | `NUMERIC(18,8)` | 是 | 源字段 |
| `exchange` | `VARCHAR(16)` | 是 | 源字段 |
| `api_name` | `VARCHAR(32)` | 否 | 固定 `etf_share_size` |
| `fetched_at` | `TIMESTAMPTZ` | 否 | 入库时间 |
| `raw_payload` | `TEXT` | 是 | 原始行载荷 |

主键固定为 `(trade_date, ts_code)`。项目 connector 已实测 `2026-08-21` 同日 1,637 行无重复键；若后续源端出现重复，不得用 hash 临时绕过，必须停下来重新评审。

主键 `(trade_date, ts_code)` 已覆盖交易日查询，因此不再建立冗余单列 `(trade_date)` 索引；仅建立 `(ts_code, trade_date)` 辅助局部 ETF 查询。view `core_serving.etf_share_size` 逐列直出 raw，不过滤、不重命名、不派生。

### 7.2 ORM、DAO、模型注册

新增：

- `src/foundation/models/raw/raw_etf_share_size.py`，类 `RawEtfShareSize`；
- `DAOFactory.raw_etf_share_size = GenericDAO(session, RawEtfShareSize)`；
- Alembic 创建表、索引和 view。

`table_model_registry` 会通过 `walk_packages` 自动导入模型，不需要另建全局模型映射；仍需补模型注册测试，确保表名为 `raw_tushare.etf_share_size`。

## 8. Normalizer 与 writer

`_etf_share_size_row_transform` 只做：

- 去除文本 NUL；
- `ts_code`、`exchange` 做 trim/大写；
- 保留 `etf_name` 和空值，不生成业务派生列。

日期和数值转换由 `DatasetNormalizer` 的 `date_fields/decimal_fields` 负责。缺 `trade_date` 或 `ts_code` 的行按现有 required-field reason code 拒绝；不能吞掉。

`DatasetWriter.write()` 对该 Definition 必须命中 `raw_only_upsert`，调用 `raw_etf_share_size.bulk_upsert()`，不访问 serving DAO。每次 unit 的业务事务提交由执行器控制；Ops 状态失败不能回滚已经提交的 raw 数据。

## 9. Ops、freshness 与页面消费

- `src/ops/catalog/dataset_catalog_views.py` 增加 `DatasetCatalogItem("etf_share_size", "etf_fund", <order>)`。
- `CatalogQueryService`、`ManualActionQueryService` 自动从 Definition 读取显示名、输入字段和支持时间模式；不在 Ops 拼接参数。
- `OpsFreshnessQueryService` 通过 Definition projection 读取 `continuous_open_day`，观测 `raw_tushare.etf_share_size.trade_date`。
- 页面只看到“ETF 份额规模”、处理日期/区间和可选单代码；不展示底层 planner、分页参数或 active pool。
- 普通自动任务只表达 schedule 意图；建议由运营安排在源站建议发布时间之后。本期不新增 probe，不加入 `daily_market_close_maintenance`。

## 10. 测试与真实验收门禁

### 10.1 必须新增的测试

| 硬口径 | 正向测试 | 负向测试 |
| --- | --- | --- |
| Definition 注册 | registry 包含字段、raw/view、freshness | 缺 freshness 或 source field 时 linter 失败 |
| 按交易日 unit | point 1 unit；range 按开市日展开 | 周末不生成 unit；不能生成 ETF × 日期 units |
| 全量默认请求 | 无 `ts_code` 只生成 `trade_date` | 不读取 active pool；不输出 `exchange/limit/offset` |
| 单 code 修复 | 一个 code 追加到每个请求 | 逗号多 code、空日期拒绝 |
| 分页 | page_count/短页终止 | 不能把首页 5,000 条当完整成功 |
| raw-only | writer 只调用 raw DAO | serving DAO 不得被调用 |
| 字段与主键 | 8 源字段均进入 raw/view | 缺主键字段行有明确 reject |
| Ops | catalog、manual、schedule 路由出现 | workflow/probe 不应出现 |

### 10.2 真实 connector 门禁

本轮已使用项目 connector 验证普通交易日、显式 `fields`、短页、空第二页和同日重复键集合；未带业务日期的两页结果也证明该请求形态跨日且跨页重复，不能复用。生产最小闭环仍必须记录：`fetched_rows`、`normalized_rows`、`written_rows`、`rejected_rows`、reason code 样本和目标表行数。

## 11. 实施顺序与停止条件

1. M0：已重读本 LLD、确认迁移 head，并重跑 connector 分页和字段证据。
2. M1：已新增 raw ORM、DAO、迁移和 view。
3. M2：已新增 Definition、freshness、planner、request builder、row transform。
4. M3：已新增 Ops catalog 投影与测试。
5. M4：已完成本地目标测试、linter 和 docs integrity；逐条对账本 LLD。
6. M5：待运营方部署、迁移、同步和页面验收。

出现以下任一情况必须停止，不用临时兼容绕过：源端同键重复、单日超过 5,000 且分页不完整、字段与文档/MCP/connector 不一致、无法确认真实迁移 head、任何 reject 无法解释。
