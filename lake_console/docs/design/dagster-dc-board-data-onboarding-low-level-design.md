# Dagster `dc_index` / `dc_member` / `dc_daily` 低层设计（LLD）

> 本文基于 [`dagster-dc-board-data-onboarding-plan.md`](./dagster-dc-board-data-onboarding-plan.md)。
> 方案文档冻结业务口径；本文冻结文件、函数、SQL、事务、测试和推进顺序。
>
> 当前状态：M3 Raw-only writer/staging、M4 Raw Dagster definitions、M5 Silver writer/asset/check、M6 Silver Dagster 接入、M7A 只读 Bootstrap dry-run、M7E 临时 lake 样本联调、M7F-M7I 正式 Raw/Silver Bootstrap 与对账、M8 Dagster 事件补录与验收均已实现并通过验证。M9-R 的专属分区、Lake core check、同日关系和基础 writer closure 已落地；其 `limit=1` 小页 source probe 已退出正式触发语义。M10“稳定 prod 基线 + 完整 Tushare 对照”已完成代码和本地验证，尚待正式 prod source-finalization 审计、definitions 加载验证和 sensor 启用；本轮未运行真实 Dagster job/sensor，也未写 Lake、prod 或 Dagster DB。

> **当前阅读口径**：M3-M8 章节中的共享 `cn_a_index_trade_days` 是阶段性历史实现记录，不是
> 当前板块链路的目标。专属 partition set、日历注册、Lake core check 和同日关系以 M9-R 为准；日常
> Raw 触发、prod 基线和 Tushare 完整性判断以 M10 为唯一目标口径。任何出现的“小页 source probe 可
> 触发 run”仅是当前实现事实和历史证据，不能被解释为“源端已完整”。

## 1. LLD 约束

### 1.1 硬约束

1. 三个数据集都按 `trade_date` 分区，但不再共享 `cn_a_index_trade_days`：Raw/Silver 分别使用 `cn_a_dc_index_trade_days`、`cn_a_dc_member_trade_days`、`cn_a_dc_daily_trade_days`；Gold daily technical 跟随 `cn_a_dc_daily_trade_days`。
2. `dc_index` / `dc_member` 起点 `2024-12-20`；`dc_daily` 起点 `2024-01-02`。
3. `dc_index` / `dc_daily` 的 Raw bootstrap 和日常更新都请求 Tushare；`dc_member` 历史 Bootstrap 使用 prod DB 只读导出，日常更新使用 Tushare 按交易日 + `ts_code` 请求。两者共用同一 Raw schema/path/key，但必须在 metadata 中区分来源。
4. M1 实测已否决 `dc_member` 按日期全市场分页作为成员事实源；日常按日期+板块代码是当前已验证的完整性方向。M1B 已完成 prod Bootstrap 覆盖、流式导出和有限 Tushare 对照验证；M1C 原始无界路径曾触发真实 `500 requests/minute` 限制，整改后的有界请求策略已通过只读重测。
5. `dc_daily` 保留 `category`，业务主键固定为 `(ts_code, trade_date, category)`。
6. 每个资产只有一个合并核心 blocking check，但 check 必须是 partitioned、单分区可归因、当前文件 set-based 检查。
7. 分页、行数、请求耗时和空结果属于写入前安全门禁与 materialization metadata，不再拆出额外 check event。
8. 专属 partition registration sensor 只读交易日历并幂等注册，不以 Tushare 更新时间作为注册条件。M10 落地后，只有 `raw_tushare_dc_index_update_job_sensor` 可以做完整源端可用性判定；所有 sensor 不扫描 Dagster event history，每 tick 最多 1 个 run request。
9. 任何 source/row/key/date 不一致都 fail closed，不用“已有文件”冒充 ready。
10. 不新增用户可见配置项、状态表、manifest 或 summary asset。M10 的观察起点、稳定间隔和 run-scoped reference fingerprint 是明确 contract，不在 cursor、run key 或 Lake 文件中隐式承载。
11. Tushare 保持 Raw 业务数据来源；prod `core_serving.dc_index`、`dc_daily`、`dc_member` 只允许经 `ProdPostgresResource.connect_readonly_transaction()` 作为当天完整性基线读取。不得用 prod 行替换 Tushare 行，不得使用 `ProdPostgresWriteResource`。
12. 当前交易日的 prod 基线必须经过两次间隔至少 5 分钟、fingerprint 一致的快照确认；冻结发生在第二次快照完成时。现有 Raw sensor 间隔为 600 秒，因此首轮在 21:15 时，最早冻结约为 21:25。

### 1.2 依赖边界

```text
silver_trade_calendar / 专属 partition registration sensors
          |
          v
TushareResource / ProdPostgresResource(read-only Bootstrap + M10 reference)
          |
          v
run_contracts/dc_board.py + assets/dc_board.py + bootstrap/dc_board_bootstrap.py
          |
          v
raw_tushare_dc_*  --partitioned-->  silver_dc_*
          |                              |
          +--> dc_board_checks.py <------+
                         |
                         v
          bounded lake readiness + M10 source-finalization gate -> sensors -> jobs
```

`dc_index`、`dc_member`、`dc_daily` 的历史非等集关系仍进入离线审计；日常自动链路只对同日 `dc_index` 基准、`dc_daily` 代码集合和 `dc_member` 请求终态做有界闭环校验，不扫描历史 event，不把历史 Bootstrap 差异带入 sensor。

## 2. 代码文件清单

### 2.1 M3 已实现文件

| 文件 | 职责 |
| --- | --- |
| `orchestrator/defs/run_contracts/dc_board.py` | 字段、起点、主键、分页和请求预算 contract 常量 |
| `orchestrator/defs/tushare_request_policy.py` | 共享有界分页、重试、限流、预算和重复键保护 |
| `orchestrator/defs/assets/dc_board.py` | 三个 Raw-only writer、DuckDB staging、回读校验和原子替换；无 Dagster decorator |
| `orchestrator/defs/bootstrap/dc_board_bootstrap.py` | `dc_member` Prod 只读 named cursor/`fetchmany` Bootstrap 入口；无 sensor 入口 |
| `orchestrator/defs/resources.py` | 独立 `connect_readonly_transaction()`，保持既有 `connect()` 语义不变 |
| `orchestrator/tests/test_tushare_request_policy.py` | 分页、重试、预算、跨页重复和空结果测试 |
| `orchestrator/tests/test_dc_board_raw_io.py` | 三类 Raw writer 正常/失败不覆盖/字段和主键校验 |
| `orchestrator/tests/test_dc_board_bootstrap.py` | Prod 投影、fetchmany、chunk 边界、跨 chunk 重复和 rollback 约束 |
| `orchestrator/tests/test_dc_board_performance.py` | 1,022 代码 fake staging 性能样本 |

### 2.2 修改文件

| 文件 | 变更 |
| --- | --- |
| `orchestrator/defs/paths.py` | 已新增三类 Raw/三类 Silver 按交易日路径 helper |
| `orchestrator/defs/run_contracts/asset_column_schemas.py` | 已新增三类 Raw/三类 Silver 字段 schema |
| `orchestrator/defs/catalog/lake_assets.py` | 已新增六个 catalog entry、partition model 和性能契约 |
| `orchestrator/defs/catalog/name_mapping.py` | 已增加板块数据集中文名 |
| `orchestrator/tests/test_run_contract_static_gates.py` | 已增加 M3 bounded writer、只读 Bootstrap、无 active definition 静态门禁 |

M4 已创建并验证以下文件；M5 的 Silver 文件仍未创建：`defs/assets/dc_board_raw.py`、`defs/checks/dc_board_checks.py`、`defs/asset_guards/dc_board_lake_readiness.py`、`defs/sensors/dc_board_sensor.py`、`defs/jobs/dc_board.py`。M3 writer 文件 `defs/assets/dc_board.py` 仍保持无 Dagster decorator。

不修改 `src/foundation/datasets/definitions/board_hotspot.py` 的既有 DatasetDefinition，除非后续确认 foundation 事实源需要同步；本次目标是新增 Dagster lake contract，不把两个系统的定义混为一谈。

### 2.3 M9-R 文件与职责（历史实施基线）

以下是 M9-R 已覆盖的代码面。它解释专属分区、Lake relation 和现有小页 probe 的来源；其中小页 probe
不再是 M10 的目标设计：

| 文件 | 修复职责 |
| --- | --- |
| `defs/partitions.py` | 增加三个板块专属 `DynamicPartitionsDefinition`，保留旧集合仅作历史兼容审计，不再作为新链路事实源 |
| `defs/run_contracts/dc_board.py` | 起点到 partition set 映射、probe 请求上限、probe 总耗时、source closure 字段和 ASCII reason code |
| `defs/sensors/dc_board_partition_sensor.py` | 三个 calendar-only 分区注册 sensor，不访问源站和事件历史 |
| `defs/assets/dc_board_raw.py` / `defs/assets/dc_board_silver.py` | 切换对应的专属 partition set，保持单分区 asset 语义 |
| `defs/checks/dc_board_checks.py` / `defs/checks/dc_board_silver_checks.py` | 增加 completeness、同日关系和失败规则映射，仍每资产只保留一个 blocking check |
| `defs/asset_guards/dc_board_lake_readiness.py` / `dc_board_silver_lake_readiness.py` | 读取专属 registered set，区分文件缺失、source closure 未完成和已 materialize check failure |
| `defs/sensors/dc_board_sensor.py` / `dc_board_silver_sensor.py` | source probe、first-not-ready、Raw frontier 和专属 partition set 切换 |
| `defs/assets/dc_daily_technical_asset.py`、相关 checks/jobs/sensors | 跟随 `cn_a_dc_daily_trade_days`，保持 Gold technical 与 `dc_daily` 日期域一致 |
| `tests/test_dc_board_partition_sensors.py`、`test_dc_board_completeness.py`、`test_dc_board_source_probe.py` | 专属注册、完整请求闭环、部分返回、空响应、集合不一致和负向门禁 |
| `tests/test_run_contract_static_gates.py` | 禁止旧共享 partition set 回流到板块正式链路、禁止 source probe 进入完整请求循环 |

M9-R 不新增状态表、manifest asset、summary asset、Dagster event history 扫描或用户可见配置项。

### 2.4 M10 已修改文件与职责

M10 只改日常 Raw 完整性门禁；不改资产身份、schema、路径、分区、job selection、check 数量、Silver/Gold
计算或历史 Bootstrap。正式实现必须先完成 5.5.6 的 prod identity 审计，确认后才可修改下列文件：

| 文件 | M10 精确职责 |
| --- | --- |
| `defs/run_contracts/dc_board.py` | 新增 `DC_BOARD_CURRENT_DAY_REFERENCE_NOT_BEFORE=21:15`、`DC_BOARD_REFERENCE_STABILITY_SECONDS=300`、身份 hash 规则、M10 reason code 和轻量 reference dataclass；不放完整 code set。 |
| `defs/run_contracts/configs.py` | 新增 `DcBoardIndexReferenceConfig` 与 `build_raw_dc_index_update_job_run_config(...)`；只传 `reference_trade_date`、`reference_observed_at`、`reference_fingerprint`。 |
| `defs/asset_guards/dc_board_source_probe.py` | 删除 `limit=1` 即 ready 的正式用途，改为 `load_prod_dc_board_reference(...)`、`compare_tushare_index_daily_to_reference(...)` 和紧凑结果模型；所有 prod SQL 显式字段投影。 |
| `defs/sensors/dc_board_sensor.py` | `raw_dc_index` 保留 600 秒最小间隔和 first-not-ready 选择，但增加当前日 21:15 后的两轮 prod snapshot、完整 Tushare 对照和最小 runtime cursor state；`dc_daily`/`dc_member` 删除独立小页 probe，只等待同日 Raw index ready。 |
| `defs/assets/dc_board.py` | 三个 writer 的 staging promote 前增加 reference closure：index 校验冻结 fingerprint，daily 校验 raw index + prod daily，member 校验 prod `(ts_code, con_code)` 双向差集；失败一律不 promote。 |
| `defs/assets/dc_board_raw.py` | 三个 Raw asset 注入既有 `prod_postgres` 只读 resource；`plan_dc_member_candidate_codes(...)` 删除上一日 member 并集和相关 fallback，仅返回同日 raw index code set。 |
| `defs/jobs/dc_board.py` | job selection 保持不变；仅让 `raw_tushare_dc_index_update_job` 接受既有 run-config 形状中的 reference config，不在 job 内访问 Tushare、DuckDB 或 prod。 |
| `defs/resources.py` / definitions 装配 | 不新增 resource；复用已有 `prod_postgres`，但将它列入三个 Raw asset 和 index Raw sensor 的 required resource 集合。 |
| `tests/test_dc_board_source_probe.py`、`test_dc_board_raw_io.py`、`test_dc_board_sensor.py` | 覆盖双 snapshot、部分源响应、writer execution-time reference 变化、daily/member identity mismatch、member 当天目录和人类可读 cursor。 |
| `tests/test_dc_board_completeness.py`、`test_run_contract_static_gates.py`、性能测试 | 锁定不新增 check/event、禁止 `limit=1` source-ready、禁止 previous-member fallback、禁止 `SELECT *`、禁止 member 全量请求进入 sensor 热路径。 |

`ProdPostgresResource` 的既有连接 env 是唯一外部连接配置；M10 不新增 env。`21:15` 与 300 秒是
`run_contracts/dc_board.py` 的静态运行 contract，不是用户开关：改动它们必须连同本 LLD、性能测算和测试一起复审，不能
在 sensor 文件散落字面量。

## 3. Contract 常量与数据模型

### 3.1 常量

`run_contracts/dc_board.py` 固定：

```python
DC_INDEX_HISTORY_START_DATE = "2024-12-20"
DC_MEMBER_HISTORY_START_DATE = "2024-12-20"
DC_DAILY_HISTORY_START_DATE = "2024-01-02"
DC_INDEX_TYPES = ("行业板块", "概念板块", "地域板块")
DC_DAILY_CATEGORIES = DC_INDEX_TYPES
DC_INDEX_PAGE_LIMIT = 5_000
DC_MEMBER_PAGE_LIMIT = 5_000
DC_DAILY_PAGE_LIMIT = 2_000
DC_BOARD_SENSOR_WINDOW_LIMIT = 10
DC_BOARD_MAX_REQUESTS_PER_PARTITION = ...  # 按 P0 实测后固化
DC_BOARD_MAX_ELAPSED_MS = ...             # 按 P0 实测后固化
DC_BOARD_CURRENT_DAY_REFERENCE_NOT_BEFORE = time(21, 15)
DC_BOARD_REFERENCE_STABILITY_SECONDS = 300
```

最后两个值不能凭经验填写。P0 必须用真实 `TushareResource.call` 测量最近交易日，得到 p50/p95 后再定拒绝阈值。
M10 的两个时间常量来自 2026-07-10 至 2026-07-23 prod DC 只读审计：该窗口最晚观测到的最终
`updated_at` 是 21:12 左右。它们不是“源站 21:15 必然完整”的假设，而是第一轮观察下限与两次快照最小
间隔；第二轮 fingerprint 不一致时必须继续等待。常量只在 `run_contracts/dc_board.py` 定义，禁止在 sensor、
writer 或测试中散落同义字面量。

### 3.2 Raw schemas

Raw 字段名称与 Tushare 显式 fields 一致，日期存 `VARCHAR(8)`：

```text
raw_tushare_dc_index:
ts_code, trade_date, name, leading, leading_code, pct_change,
leading_pct, total_mv, turnover_rate, up_num, down_num, idx_type, level

raw_tushare_dc_member:
trade_date, ts_code, con_code, name

raw_tushare_dc_daily:
ts_code, trade_date, close, open, high, low, change, pct_change,
vol, amount, swing, turnover_rate, category
```

数值字段按现有 `ColumnContract` 类型映射：价格/比例/金额/成交量为 `DOUBLE`，上涨/下跌家数为 `INTEGER`，文本为 `VARCHAR`。

### 3.3 Silver schemas

Silver 复用业务字段，不新增业务列：

- `trade_date` 转 `DATE`。
- 代码、名称、类型 trim；代码统一大写。
- `dc_index` key：`(ts_code, trade_date)`；`idx_type` 为身份字段。
- `dc_member` key：`(trade_date, ts_code, con_code)`。
- `dc_daily` key：`(ts_code, trade_date, category)`，`category` 禁止删除、合并或从 key 中移除。

## 4. Path 与 Catalog 设计

### 4.1 Path helpers

在 `paths.py` 中新增：

```python
def raw_dc_index_path(root: Path, trade_date: str) -> Path: ...
def raw_dc_member_path(root: Path, trade_date: str) -> Path: ...
def raw_dc_daily_path(root: Path, trade_date: str) -> Path: ...
def silver_dc_index_path(root: Path, trade_date: str) -> Path: ...
def silver_dc_member_path(root: Path, trade_date: str) -> Path: ...
def silver_dc_daily_path(root: Path, trade_date: str) -> Path: ...
```

函数内部只接受 ISO 日期，使用统一 `lake_path`，不得在 asset 文件拼接字符串。推荐路径：

```text
raw/board/{dataset}/trade_date={date}/part-000.parquet
silver/board/{dataset}/trade_date={date}/part-000.parquet
```

### 4.2 Catalog entry

在 `lake_assets.py` 中新增：

- `TRADE_DATE_PARTITION_RAW_DC_INDEX`
- `TRADE_DATE_PARTITION_RAW_DC_MEMBER`
- `TRADE_DATE_PARTITION_RAW_DC_DAILY`
- `TRADE_DATE_PARTITION_SILVER_DC_INDEX`
- `TRADE_DATE_PARTITION_SILVER_DC_MEMBER`
- `TRADE_DATE_PARTITION_SILVER_DC_DAILY`

六个 entry 必须显式登记：

```text
asset_key
dataset_id
layer/data_domain/group
source_system / data_contract / source_api / source_doc
column_schema / path_template / partition_model
ingestion_sources / bootstrap_sources / default_daily_ingestion_source
blocking_check_names
write_policy / event_policy
performance_contract
```

建议：

- `dc_index` / `dc_daily` Raw：`source_system=SourceSystem.TUSHARE`，`ingestion_sources=(TUSHARE_API,)`，`bootstrap_sources=(TUSHARE_API,)`，`default_daily_ingestion_source=TUSHARE_API`。
- `dc_member` Raw：`source_system=SourceSystem.TUSHARE` 表示数据集/API 契约族；`ingestion_sources=(TUSHARE_API, PROD_DB_READONLY)`，`bootstrap_sources=(PROD_DB_READONLY,)`，`default_daily_ingestion_source=TUSHARE_API`。历史分区必须通过 metadata 标明 prod 只读来源，不能伪装成 Tushare 直接抓取。
- Silver 三个 entry：`source_system=SourceSystem.DERIVED`，`bootstrap_sources=(DERIVED_FROM_ASSETS,)`，不把 prod DB 或 Tushare 登记为 Silver 的直接 Bootstrap source。
- `event_policy` 使用现有正式 run 事件；bootstrap 需要 runless 事件时必须另列审批和范围，不能隐式执行。

## 5. Raw 写入实现

### 5.1 Tushare 分页接口

在 `assets/dc_board.py` 使用共享 bounded policy 实现 Raw fetch/write 流程：

```text
validate fields/types
  -> build first page params
  -> TushareResource.call(api, params, fields)
  -> validate returned columns
  -> append current page to bounded rows/staging
  -> check page key/date scope and duplicate keys
  -> offset += page_size
  -> continue until source page contract says complete
  -> reject empty/partial/duplicate result
  -> atomically write target parquet
```

禁止在 asset 中直接调用 `pro.xxx`、禁止在 sensor 中调用 Tushare、禁止把分页状态写入 cursor。

### 5.2 `dc_index` 请求计划

对一个 `partition_key` 依次执行：

```python
for idx_type in DC_INDEX_TYPES:
    fetch_all_pages(
        api_name="dc_index",
        api_params={"trade_date": compact_date, "idx_type": idx_type},
        fields=DC_INDEX_FIELDS,
        limit=DC_INDEX_PAGE_LIMIT,
    )
```

合并前验证：

- 每页列集合完全一致。
- 每行 `trade_date == compact_date`。
- 每行 `idx_type == requested idx_type`。
- 单类型内 `(ts_code, trade_date)` 不重复；三类型合并后仍不重复。
- 三类型合计为空才失败；单类型为空记录 `empty_idx_type`，不把 2024-12-20 的合法历史缺类型误判为失败。

### 5.3 `dc_member` Bootstrap：prod DB 只读导出

Bootstrap 不调用 Tushare `dc_member` 全市场分页。它使用现有 `ProdPostgresResource` 的只读连接，按 expected `trade_date` 流式投影：

```sql
SELECT trade_date, ts_code, con_code, name
FROM raw_tushare.dc_member
WHERE trade_date = %(trade_date)s
ORDER BY ts_code, con_code
```

实现约束：

- 禁止 `SELECT *`、禁止 `ProdPostgresWriteResource`、禁止在 sensor 中访问 prod DB。
- 每个日期使用 server-side cursor 或等价分块读取，单次只保留有限 rows；不把约 2,500 万历史行一次性加载到 Python。
- 每个分区验证列集合、日期等于 partition、主键非空唯一、代码格式和 source/written row count；结果通过后才写临时 Parquet 并原子 promote。
- metadata 必须写 `source_method=prod_db_readonly_export`、`source_row_count`、`written_row_count`、`duplicate_key_count`、`invalid_code_count`、`elapsed_ms`。
- 先验证起始日、2025-05-30、最近交易日和随机日期；prod 日期缺失、重复、日期越界、代码非法或行数不一致时该日期 fail closed。
- Tushare 只做有限样本 reconciliation，不作为这批历史成员事实的全集基准；差异进入审计报告，不静默覆盖 prod 导出结果。

### 5.4 `dc_member` 日常：Tushare 按代码请求

日常只处理一个 expected `trade_date`。候选 `ts_code` 必须严格等于同日已 ready 的
`raw_tushare_dc_index` 三类代码并集；昨天或更早 member 文件不参与候选规划。此前“当天目录与最近 member
分区并集”的代码是为了连续性而引入的历史实现，但它会把今天已经不在目录中的板块重新带回请求，并与当天
目录的完整性检查自相矛盾，M10 必须删除。

```python
for ts_code in candidate_ts_codes:
    fetch_all_pages(
        api_name="dc_member",
        api_params={"trade_date": compact_date, "ts_code": ts_code},
        fields=DC_MEMBER_FIELDS,
        limit=DC_MEMBER_PAGE_LIMIT,
    )
```

实现约束：

- 每个 `ts_code` 单独请求；逗号拼接代码已实测返回空结果，禁止用它降低请求量。
- 单个代码空结果是合法事实；所有候选代码都为空才触发 open-date 空结果保护。
- 每行必须回验 `trade_date == partition` 且 `ts_code == requested_ts_code`；每个代码内部和合并结果都要检查 `(trade_date, ts_code, con_code)` 唯一。
- 每日 metadata 必须写 `source_method=tushare_api_by_ts_code`、`request_count`、`empty_code_count`、`source_row_count`、`written_row_count`、`elapsed_ms` 和失败代码样本。
- M1C 通过后才允许进入 Raw writer；正式 writer 仍受固定 request/elapsed budget 约束，超过预算 fail closed，不回退全市场分页。
- promote 前从 prod 只读投影当天 `(ts_code, con_code)`，用 DuckDB 对 Tushare staging 做双向 set difference；
  pair 缺失、额外、重复、空 key、日期不符或任一请求失败都 fail closed。该对照只在实际 member run 内进行，
  不能移入 sensor。

完整性规则：

- 页响应列集合完全一致，offset 严格递增；单代码分页主键不重复。
- 交易日、请求代码和输出行数逐项对账；任一失败代码、重复主键或行数不一致阻止整日写入。

### 5.5 `dc_daily` 请求计划

```python
fetch_all_pages(
    api_name="dc_daily",
    api_params={"trade_date": compact_date},
    fields=DC_DAILY_FIELDS,
    limit=DC_DAILY_PAGE_LIMIT,
)
```

验证：

- `trade_date` 全部等于 partition。
- `category` 非空且属于 `DC_DAILY_CATEGORIES`。
- `(ts_code, trade_date, category)` 跨页唯一。
- SSE open date 全量空结果失败。
- 不把 `category` 丢失或按 `ts_code` 聚合。
- promote 前必须读取同日 `raw_dc_index`，将双方去重后的 `ts_code` 做双向集合比较。缺 index
  文件、index 集合为空、daily 缺 index 代码或 daily 出现额外代码均为 source closure 失败；
  不写正式目标文件，也不产生成功 materialization。这一闭环不新增 Dagster check，现有合并
  core check 继续作为写入后的最终文件防线。
- M10 额外读取 fresh prod `core_serving.dc_daily` 的 `(category, ts_code)` identity，并要求它与同日
  `raw_dc_index` 的 `(idx_type, ts_code)` 映射以及 Tushare staging 三者严格相等。仅代码数相等不足以通过。

2026-07-19 对源站的只读复核显示，`dc_daily` 与三个 `dc_index` 类型当日均为 1,022 个代码，
集合差异为 0。此前 277 行 `dc_daily` 响应因此按部分源响应处理，而非合法板块关系差异。

### 5.6 原子写入和 metadata

`write_dc_raw_partition(...)` 只负责一个日期：

1. 写 `part-000.parquet.tmp`。
2. 完成 DuckDB schema/key/domain/page checks。
3. `os.replace` 覆盖正式文件。
4. 返回 `DcPartitionWriteResult`。

materialization metadata 使用 `build_materialization_metadata`，额外字段限定为：

```text
partition_key
source_api / source_table
source_method
source_params
requested_fields
page_count / request_count
source_row_count / written_row_count
duplicate_key_count
empty_result_guard
elapsed_ms
write_mode
```

`source_table` 只在 `dc_member` prod Bootstrap 时填写；`source_method` 使用 `prod_db_readonly_export` 或 `tushare_api_by_ts_code` 等受控值。不把 `source_method`、旧路径和 bootstrap 说明写进 parquet 业务列。

## 6. Bootstrap 实现与来源分流

### 6.1 `dc_index` / `dc_daily` Tushare Bootstrap

`bootstrap/dc_board_bootstrap.py` 使用 `TushareResource` + `DuckDBResource`，`dc_index` / `dc_daily` 使用明确 fields；禁止使用默认字段或 `select *`。

### 6.2 `dc_member` prod Bootstrap

`dc_member` Bootstrap 使用 `ProdPostgresResource` + `DuckDBResource`，不使用写资源，不把 prod 表注册成 Dagster asset。具体的按日期流式导出、临时文件、四字段投影和 fail-closed 规则见 5.3。

所有 Bootstrap staging 文件都必须通过：

- 明确 fields 与返回列集合检查。
- `trade_date` 范围过滤。
- 主键字段 non-null 检查。
- `GROUP BY` 主键重复检查。
- Tushare 资产的页间 offset 进展和跨页重复检查；`dc_member` prod 导出的分块/游标进展和跨块重复检查。
- 行数和日期分区对账。

不得把 2,500 万成员行一次性拉入 Python；采用日期批次、分页缓冲和分批 staging。一个日期完成并原子 promote 后才释放该日期的 rows/staging 资源。

### 6.3 prod / Tushare 对照审计

`reconcile_dc_partition_with_prod_audit(...)` 只在 bootstrap staging 阶段运行：

- `dc_index` / `dc_daily` 的 Tushare staging 是唯一写入事实；`dc_member` Bootstrap 的 prod staging 是历史写入事实，Tushare 只做有限样本对照；日常 `dc_member` 则以 Tushare 结果为事实。
- 对已知 `dc_daily` 12 代码/177 日期记录 prod-only 分类差异，最终以 Tushare staging 为准，不用 prod 行修复 Tushare 行。
- 对 `dc_index` 的非交易日行不发布到本专项 domain；不把周末差异解释为开市日修复。
- `dc_member` 对起始日 `2024-12-20`、`2025-05-30`、最近交易日和随机抽样日期，从 prod 确定性抽取板块代码，按 `trade_date + ts_code` 请求 Tushare 并比较行数与 `(trade_date, ts_code, con_code, name)` 四字段集合；发现差异时报告 `prod_bootstrap_vs_tushare_sample`，不静默替换 Bootstrap 事实，也不回写 prod。
- prod/Tushare 对照查询失败不改变 staging，但报告必须标记 `audit_incomplete`；审计未完成时不能把 Bootstrap 标记为最终验收通过。

对照报告输出 JSON 到 `/private/tmp`，但报告不是业务事实源；各来源 staging 的分页/游标、主键、日期和空结果阻断项为 0 才允许 promote，来源对照状态单独记录为 `matched`、`source_diff` 或 `audit_incomplete`。

### 6.4 promote 事务边界

- 数据湖文件不是数据库事务；先写 staging，后逐文件原子 rename。
- 每个日期的三个 Raw 文件作为一个 promote unit；任一文件失败不标记该日期完整。`dc_member` 的 Bootstrap 和日常可以使用同一 promote 函数，但 source metadata 必须不同。
- Silver 只在对应 Raw 文件全部存在且 Raw core check 通过后生成。
- Dagster event 补录是最后一步，失败不得删除或回滚已经通过校验的 parquet。

## 7. 高质量 Tushare 请求能力

### 7.1 统一分页 fetcher

`assets/dc_board.py` 的分页调用服务日常 `dc_index`/`dc_daily` 和 `dc_member` 代码请求；`dc_member` 的 prod Bootstrap 使用 `bootstrap/dc_board_bootstrap.py` 独立的只读分块导出器，不能强行复用 Tushare 分页语义。内部结果对象是 `DcBoardRawWriteResult`：

```python
@dataclass(frozen=True, slots=True)
class TusharePageResult:
    api_name: str
    params: Mapping[str, object]
    fields: tuple[str, ...]
    rows: tuple[Mapping[str, object], ...]
    request_index: int
    offset: int
    limit: int
    elapsed_ms: float


@dataclass(frozen=True, slots=True)
class TushareFetchSummary:
    api_name: str
    request_count: int
    page_count: int
    source_row_count: int
    duplicate_key_count: int
    empty_page_count: int
    retry_count: int
    elapsed_ms: float
```

`fetch_dc_pages(...)` 的硬行为：

1. 每次请求显式传 `limit`、`offset` 和 fields；不依赖默认字段。
2. 返回列集合变化、offset 不前进、重复主键、日期越界立即失败。
3. 只对幂等请求重试，最多 3 次；限流/网络瞬态错误使用 `1/2/4s` 指数退避，单次最多 `8s`，不得无限等待；权限、参数、字段和业务契约错误不重试。
4. 每次重试和分页记录耗时；不把完整 rows 写入 cursor。
5. 连续空页是结束条件，但 page 0 空结果由资产语义决定；`dc_index` 允许单类型空，`dc_member`/`dc_daily` 的 open date 全空失败。
6. 单 partition 超过 `1,200` 次请求或 `600s` elapsed budget 时停止该 partition，输出预算原因和失败/未尝试代码清单，整日不写 Raw，避免重试风暴。

### 7.2 并发、恢复和幂等

- 首版 bootstrap 按日期串行执行，优先保证配额、顺序和错误可定位；不使用无界并发。
- 只有完成串行性能测试后，才允许增加固定上限的 dataset-level bounded concurrency；并发上限不是运营配置，不暴露给 UI。
- 每个日期独立 staging/report；失败日期可从临时报告恢复，不重新请求已成功 promote 的日期。
- 同一 API/date/type 的 staging 路径带稳定请求摘要；重复执行先验证 staging 合同，不能直接追加造成重复。
- 正式文件只通过原子 rename 生成；请求失败或校验失败不得覆盖已有文件。

### 7.3 全量请求量预算

按当前审计规模估算，未计额外重试和分页超限：

| 数据集 | 历史日期 | 基础请求估算 |
| --- | ---: | ---: |
| `dc_index` | 376 | `376 * 3 = 1,128` 类型请求，超 5,000 行再分页 |
| `dc_member` Bootstrap | 376 | 376 个 prod 只读日期导出；请求次数由 DB cursor/chunk 决定，必须实测单日 rows、chunk 数、耗时和总吞吐 |
| `dc_member` 日常 | 每个交易日 | 当前观测约 1,023 个代码请求；使用 `0.13s` 最小间隔、最多 1,200 请求、最多 600s；超过预算整日 fail-closed |
| `dc_daily` | 610 | 约 610 个日期请求，超 2,000 行再分页 |

旧的 8,882 次全 Tushare 估算已失效，也不再用于 `dc_member` Bootstrap。新预算拆开计算：`dc_member` Bootstrap 由 prod DB 流式导出吞吐决定；`dc_member` 日常由 M1C 的代码请求预算决定；`dc_index` / `dc_daily` 仍按 Tushare 请求量计算。不能因为 Bootstrap 使用 prod 就取消日常 Tushare 的请求、配额、空结果和失败恢复门禁。

## 8. Silver 实现

`assets/dc_board.py` 中 Silver asset 调用 `write_silver_dc_*_partition(...)`，不在 decorator 函数中堆积 SQL。

每个 writer 使用 DuckDB set-based SQL：

```text
read raw partition
  -> cast/trim/upper
  -> filter partition date and SSE open date
  -> validate allowed identity domains
  -> group by business key to detect duplicate/conflict
  -> copy to temporary parquet
  -> atomic replace silver partition
```

具体过滤：

- `silver_dc_index`：保留有效 `idx_type`，同日 key 唯一；不因为没有成员而删板块。
- `silver_dc_member`：保留合法板块/股票代码格式，同一 `trade_date/ts_code/con_code` 只保留一条；业务值冲突 fail closed。
- `silver_dc_daily`：保留三种 `category`；`category` 参与唯一性和输出；不按 `dc_index` 的当前集合裁剪。

Silver writer 返回：source rows、output rows、removed duplicates、rejected rows、reject reason samples、elapsed ms。大批 reject 不是正常现象，必须阻断并报告。

## 9. Core checks 的代码结构

`checks/dc_board_checks.py` 使用同一个内部执行器：

```python
def evaluate_dc_board_core_check(
    *, asset_kind: DcBoardAssetKind, partition_key: str, lake_root: Path,
    connection: DuckDBConnection,
) -> DcBoardCheckEvaluation: ...
```

它先做 bounded file/schema checks，再做一条或少量 set-based SQL：

```sql
WITH rows AS (... current partition parquet ...),
key_counts AS (... GROUP BY business key ...),
violations AS (...)
SELECT rule_code, violation_count, sample_json
FROM violations;
```

最后由六个正式 `@dg.asset_check` wrapper 返回一个 `AssetCheckResult`：

- `asset=...`
- `blocking=True`
- `partitions_def=对应数据集的专属 partition set`
- `metadata=build_check_metadata(...)`

metadata 至少包含：

```text
check_scope=partition
partition_key
checked_row_count
failed_rule_count
failed_rules
failure_samples
input_file_path
elapsed_ms
```

check 不查询 Dagster event history，不调用 `get_event_records`，不做跨日期扫描，不把一个函数返回多个分区结果。

## 10. Readiness、sensor 和 cursor

### 10.1 Batch readiness

`asset_guards/dc_board_lake_readiness.py` 定义内存态 `DcBoardDateReadiness`、`DcBoardBatchReadiness`：

- 输入：DuckDB connection、lake root、最近 10 个 expected dates、asset kind、对应专属 registered partitions。
- 一次规划当前窗口文件；按文件存在、目标日 row count、schema/key/domain 做 set-based SQL。
- 返回 `ready/materialized/checks_passed/reason/failed_rules/elapsed_ms`。
- 文件存在但 check 失败：`materialized=True, checks_passed=False`，sensor 不自动覆盖，要求人工处理。
- 文件缺失或目标日 0 行：`materialized=False`，允许 first-not-ready 自动触发。
- readiness 不把文件存在或 row count>0 当作成功；source closure 未通过、同日代码集合不一致、核心 check 失败都必须是 not-ready。
- 批量读取只覆盖最近 10 个 expected dates；不逐日读取 Dagster event/check history，不调用 Tushare/Prod DB。

### 10.2 M10 Sensor 流程

小页 `limit=1` probe 已冻结为历史实现，不得继续作为正式触发口径。M10 在保留现有 10 日 DuckDB
readiness、first-not-ready、注册缺口和单 RunRequest 约束的前提下，将 Raw 提交流程替换为：

```text
calendar-only partition registration
 -> dataset-specific expected window (10)
 -> registered gap + one DuckDB batch lake readiness
 -> first missing/not-ready target
 -> raw_dc_index only: prod reference snapshot t1 / t2
 -> current-day t2 stable: full Tushare index+daily identity compare
 -> build one raw_dc_index RunRequest with frozen reference config
 -> raw_dc_daily/raw_dc_member wait for same-day raw_dc_index ready
 -> respective writer performs full own reference closure before promote
```

分区注册 sensor：

- 每个数据集一个独立 sensor，只从 SSE open calendar 计算日期并补注册自己的 dynamic partition set。
- 不设置“每天固定时刻注册”条件；轮询周期是调度间隔，不是源站 ready 判定。
- 不读取业务 Parquet、Tushare、Prod DB 或 Dagster event history。

`raw_tushare_dc_index_update_job_sensor` 的 M10 分支：

1. 对 `target_trade_date == evaluated_at.date()`，`evaluated_at < 21:15 Asia/Shanghai` 时立即 skip，且不访问
   prod 或 Tushare；cursor 为 `before_prod_reference_window`。
2. 到达观察窗口后，读取 prod `dc_index`、`dc_daily` 的完整 identity（约千级行）和 `dc_member` 的 aggregate
   closure，得到 `DcBoardProdReferenceSnapshot`。SQL 必须只投影 `trade_date`、identity 字段、计数和
   `updated_at` 观测字段，禁止 `SELECT *`。
3. cursor 没有同 target 的 provisional snapshot 时，只保存其 fingerprint 与 `observed_at` 并 skip；原因是
   `prod_reference_pending_confirmation`。若不足 300 秒，继续 skip，不重复做完整 Tushare 请求。
4. 满足间隔后读取第二个 prod snapshot。只有两个 fingerprint 完全相同且两者内部闭合，才冻结第二个
   snapshot；否则用新的 snapshot 覆盖 provisional state 并以 `prod_reference_changed` skip。
5. 基线冻结后，完整请求 Tushare 的三个 `dc_index` 类型与 `dc_daily`，验证字段、日期、空/重复 key、
   `(idx_type, ts_code)`、`(category, ts_code)`、行数和 sorted hash 均等于冻结基线。失败为
   `tushare_reference_mismatch`，不提交 run。
6. 通过后只提交一个 `raw_tushare_dc_index` partition run，并经 `build_raw_dc_index_update_job_run_config(...)`
   显式传入最小 reference config；run key 和 partition key 格式保持不变。

若 `target_trade_date < evaluated_at.date()`，它已不是同日发布窗口：不适用 21:15 时间下限与跨 tick 等待，
但仍必须读取一次内部闭合的 prod reference、完整读取 Tushare index/daily 并做严格 identity 对照。这样历史
补洞不会被当天时钟卡住，也不会允许部分源响应写入。

`raw_tushare_dc_daily_update_job_sensor` 与 `raw_tushare_dc_member_update_job_sensor` 不再做任何 Tushare
小页 probe。它们继续先判断同日 `raw_tushare_dc_index` ready；未 ready 时 skip，ready 后最多提交一个 run。
这两个 writer 自己执行完整 source/prod closure，因此手工 Launchpad、CLI 或 sensor 都不能绕过写前门禁。

所有 Raw sensor 的共同规则：当前日期不得超出 history start date 与 SSE open calendar；目标日期早于窗口内
更早缺口时不得越过；已 materialized 但 core check failure 时不得自动覆盖。

Silver sensor 只在同日 Raw **完整成功** 后提交 Silver run；Raw first-not-ready 早于或等于 Silver target 时阻断。Silver 文件存在但 core check 失败时不自动覆盖。

### 10.3 “更新成功”的可核验条件

一个日期只有同时满足以下三层条件，才允许 readiness 返回 `ready=True`，并允许下游 Silver/Gold 继续：

#### A. Source / prod reference closure

source closure 在 Raw writer promote 前完成，结果进入本次 materialization metadata 和内存态 writer result；它不是新的持久化状态实体，也不拆成额外 check event。

| 数据集 | 必须通过的闭环 |
| --- | --- |
| `dc_index` | run config reference fingerprint、writer fresh prod fingerprint 与 sensor 冻结 fingerprint 三者相等；三个 `idx_type` 和 `dc_daily` identity 均与冻结基线相等；无失败/未尝试请求、空/重复 key、分页或日期错误 |
| `dc_daily` | 日期分页全部完成；无失败/未尝试页；`(category, ts_code)` 同时等于同日 raw index 映射与 fresh prod daily identity；category、日期、列、主键、源/写入行数一致 |
| `dc_member` | candidate code set 精确等于同日 raw index code set；`requested = success + valid_empty`、failed=0、unattempted=0；Tushare `(ts_code, con_code)` 与 fresh prod member identity 双向相等；日期、主键、源/写入行数一致 |

source closure 任一失败时：不 promote、不产生成功 materialization；已有目标保持不变，下一次 sensor 仍可针对 missing target 重试。

`dc_member` 日常候选规划读取的 Silver 交易日历真实列名为 `trade_date`；不得使用历史命名
`cal_date`。它也不得再读取最近 member 文件或用前一日 code fallback。当天 raw index 缺失、为空或尚未
ready 时必须阻断；不能用空候选、旧目录或其他 fallback 掩盖。

#### B. 当前湖文件 core check

- 文件、schema、分区日期、非空、主键、身份字段和数值域通过。
- `dc_index` 的类型覆盖和 `dc_daily` 的 category 覆盖符合正式 contract。
- 每个资产仍只有一个合并 blocking check，失败通过 `failed_rules`、`reason_code`、有限样本解释；不增加逐页/逐请求 check event。

#### C. 同日板块族关系闭环

- `dc_daily` 的同日 `(category, ts_code)` 集合与 `dc_index` 的 `(idx_type, ts_code)` 基准集合一致。
- `dc_member` 的请求候选集合精确来自同日 `dc_index`；每个候选请求必须有成功或合法空终态，且产物 identity
  已与 prod 同日 member 基线对照。合法空响应不能通过 member 文件缺行推断。
- 关系 SQL 只读同日/当前窗口文件，不扫描历史 Dagster event；历史 Bootstrap 的非等集差异只保留为离线审计事实。

因此，小页 probe、文件存在或 row count>0 均不能单独判定更新成功。

### 10.4 Cursor 字段

使用 `build_sensor_cursor` / `build_cursor_details`，只写：

```text
reason_code
blocked_component
summary
next_action
expected_start/end/count
registered_count
first_missing_registered_date
first_not_ready_trade_date
ready_through_trade_date
batch_elapsed_ms
request_count/page_count/row_count 摘要
```

跨 tick 只允许 `runtime_state.dc_board_prod_reference` 保存 `trade_date`、`fingerprint` 和
`observed_at`。禁止写每个板块代码的完整列表、每一页的明细、完整 prod/Tushare 报告或 member pairs。

M10 正式 ASCII reason code：

```text
partition_not_registered
before_prod_reference_window
prod_reference_pending_confirmation
prod_reference_not_closed
prod_reference_changed
prod_reference_unavailable
tushare_reference_mismatch
source_request_incomplete
source_request_budget_exceeded
lake_file_missing
materialized_check_failed
cross_dataset_code_set_mismatch
all_ready
```

## 11. Job 和 Definitions 装配

每个 job 只写 selection。以下以 `dc_index` 为例，展示 M10 下仍不变的 job 边界；其余 job 使用各自对应的
专属 partition set 和 asset/check：

```python
raw_tushare_dc_index_update_job = dg.define_asset_job(
    name="raw_tushare_dc_index_update_job",
    partitions_def=cn_a_dc_index_trade_days,
    selection=(
        dg.AssetSelection.assets(raw_tushare_dc_index)
        | dg.AssetSelection.checks_for_assets(raw_tushare_dc_index)
    ),
)
```

其他五个 job 同形，不在 job 中调用 Tushare、DuckDB、prod 或 check helper。M10 只为
`raw_tushare_dc_index_update_job` 增加 asset config：

```python
class DcBoardIndexReferenceConfig(dg.Config):
    reference_trade_date: str
    reference_observed_at: str
    reference_fingerprint: str  # lowercase SHA-256, 64 chars
```

sensor 通过 `build_raw_dc_index_update_job_run_config(...)` 将该最小 config 放入
`ops.raw_tushare_dc_index.config`。`reference_trade_date` 必须等于 partition；asset 在写入前重新读取 prod，
不允许仅因 config 存在就信任已过期基线。`dc_daily` / `dc_member` 不携带跨 sensor snapshot，而是在 writer 内
从同日 raw index 和 fresh prod 做自己的对照。

Definitions 装配必须同时包含：

- 六个 asset。
- 六个 core check。
- 六个 job。
- 六个 Raw/Silver update sensor，以及三个专属 calendar-only partition registration sensor。
- 三个板块专属 partition set 和必要 resources。

M10 追加既有 `prod_postgres` 到三个 Raw asset 的资源依赖，并追加到 raw index sensor 的
`required_resource_keys`。它只能建立 readonly transaction；Definitions 不增加新 resource key、job、check、
asset 或 sensor。

正式 check 不允许通过多 partition run 只返回一条聚合结果；正式执行路径单 run 单 partition。

## 12. 测试矩阵

### 12.1 Source/contract

- 默认字段、显式字段、业务关键字段三组请求结果。
- `dc_index` 三 `idx_type` 请求和合并。
- `dc_daily` `category` 必须返回并进入字段契约。
- `dc_member` 全市场 `limit/offset` 页边界、空页、重复页、列漂移、offset 不前进；该路径只作为拒绝性回归样本。
- `dc_member` prod Bootstrap 的只读 SQL 投影、日期覆盖、游标/分块边界、跨块重复和源/写入行数对账。
- `dc_member` 日常按 `trade_date + ts_code` 的单代码分页、空代码语义、请求代码回验和 request/elapsed budget。
- 页数、请求数、行数和耗时 metadata 正确。
- 专属 partition set 与各自 history start date 一一对应；旧 `cn_a_index_trade_days` 不得出现在新板块正式 job/sensor/check 定义中。
- prod reference snapshot 只显式读取千级 index/daily identity 与 member aggregate；当前日必须两次 snapshot
  一致才允许完整 Tushare 对照，历史补洞仍必须做一次 prod/Tushare identity 对照。
- M10 的 index sensor 完整对照只请求三个 `dc_index` 类型和一个 `dc_daily` 分页；不得调用 member
  candidate loop，`dc_daily` / `dc_member` sensor 不得保留 `limit=1` source-ready probe。

### 12.2 Raw writer

- 正常单日完整写入。
- 任何页失败不覆盖正式文件。
- open date 全空失败；`dc_index` 单类型为空但总结果非空可通过。
- trade_date 越界、未知 idx_type/category、重复主键、源/写入行数不等失败。
- source closure 覆盖失败请求、未尝试请求、合法空响应、分页终态和源/写入行数对账；任一失败不得 promote。
- 2,124 条已知 prod/source `dc_daily` 差异不进入最终 Tushare staging；最终事实只来自 Tushare。
- `dc_index` writer 的 config fingerprint 缺失、日期不一致、格式非法、fresh prod fingerprint 改变，或 Tushare
  index/daily identity 不等于冻结基线时不得 promote。
- `dc_daily` writer 的 raw-index/Tushare/prod 三方 `(type, ts_code)` identity 任何双向差集非零时不得 promote。
- `dc_member` writer 的 candidate 不等于同日 raw index、Tushare/prod `(ts_code, con_code)` 双向差集非零，或
  发现前一日 fallback 仍被调用时不得 promote。

### 12.3 Silver writer

- 类型转换和交易日过滤。
- `dc_daily` category 保留并参与 key。
- duplicate key fail closed，不 silently drop conflict。
- 不因 `dc_index` / `dc_member` / `dc_daily` 的历史覆盖差异误阻断。

### 12.4 Checks and sensors

- 每个 core check 使用对应的专属 partition set；Raw/Silver/Gold technical 的 partition set 对齐同一数据集日期域。
- check 只针对当前 partition，event 归属正确。
- check 同时验证当前湖文件和同日板块族关系；source closure 未通过时不产生成功 materialization，不能只靠文件存在判定 ready。
- materialized check problem 不自动重跑；missing file/0 rows 选择 first-not-ready。
- 分区注册 sensor 只读 calendar 并幂等注册；Raw index sensor 先完成 M10 prod 双 snapshot 和完整
  Tushare 对照，Raw daily/member 只等待同日 raw index ready，再最多提交一个 request。
- sensor 使用统一 run key/cursor builder；cursor 使用稳定 ASCII reason code、中文 `summary/next_action`、
  frontier 和最小 count/hash 摘要，不承载 source/prod 报告。
- 禁止直接 `dg.RunRequest`、手写 run key、解析 event history。

### 12.5 Bootstrap

- `dc_index` / `dc_daily` 的 Tushare Bootstrap 不把全历史分页结果一次性 `fetchall` 到 Python；`dc_member` Bootstrap 不把 prod 的全历史结果一次性 `fetchall` 到 Python。
- `dc_member` Bootstrap 只使用 read-only prod resource，不能误用 write resource；M10 的 index sensor 和三个
  Raw writer 可访问 prod，但只用于明确字段投影的 reference closure，不能读取历史 event 或写 prod。
- staging/promote 失败不污染正式路径。
- source reconcile 报告为阻断时不 promote。
- event 补录失败不删除 parquet、不回滚业务文件。

## 13. 性能验收与停止条件

### 13.1 必测指标

对最近交易日和 2024-12-20 起始日样本记录：

- API request/page count。
- source/output row count。
- DuckDB SQL elapsed ms。
- parquet 写入 elapsed ms。
- 单个 sensor tick elapsed ms。
- 分区注册 sensor 的 calendar scan elapsed、注册数量和重复注册数量。
- M10 每轮 prod snapshot 的行数、3 个查询耗时、fingerprint、内部闭环结果和两轮间隔。
- M10 完整 Tushare 对照的固定 4 个请求、页数、elapsed、identity 差异计数、skip 比例和完整 run 命中比例。
- source closure 的 requested/success/valid-empty/failed/unattempted 计数。
- daily/member writer 的 prod identity 读取行数、DuckDB 双向差集耗时和差异计数。
- bootstrap 峰值内存和单日期耗时。

### 13.2 不可接受

- `dc_member` 全市场分页无法证明完整，却直接上线。
- 单个 sensor tick 超过 Dagster RPC 的安全预算，或稳定态进入秒级/十秒级深扫而没有拆分计划。
- M10 当前日 path 在两轮 prod snapshot 合计超过 6 个只读查询、完整 Tushare 对照超过 4 个请求，或稳定
  sensor tick 超过 10 秒；不得通过调大 RPC timeout 掩盖。
- 任一 sensor 对 member 执行全量 code loop、读取约九万 member pairs，或保留 `limit=1` 即 source ready 的判断。
- check 读取全历史文件、Dagster event history 或用 Python 行循环。
- 为解决数据量新增 summary asset、manifest 或数据库实体。
- 为追求通过率把空结果、重复主键、源/写入不一致降级为 WARN。

任何停止条件触发，停在当前阶段，不继续写代码或执行正式同步。

## 14. Milestone 执行顺序与交付门

### M0：口径冻结

核心任务：冻结日期范围、交易日 domain、Raw/Silver 边界、业务主键、合并 check、事件保留，以及三类资产各自的 Bootstrap/日常来源口径。

产出：本方案和本 LLD；已完成的 prod/Tushare 只读审计结论。

进入 M1 的条件：不存在未决的日期、主键、来源和事件保留冲突。

### M1A：Tushare 请求能力验证（已完成只读验证）

核心任务：用真实 `TushareResource.call` 验证 `dc_index` / `dc_daily` 的显式 fields、分页和耗时，并验证 `dc_member` 全市场分页为什么不能作为事实源、按代码请求的正确性方向。

产出：分页测试报告、实际 request/page/row/elapsed 统计、字段核验和请求预算；报告位于 `/private/tmp/dc_board_m1_tushare_validation_report_20260714.json`，并明确停止使用 `dc_member` 全市场分页。

### M1B：dc_member prod Bootstrap 只读验证（已通过）

核心任务：只读审计 prod 日期覆盖、字段/主键质量、按日期流式读取吞吐和分块边界，并完成起始日、固定历史日、最新日和中间样本日的有限 Tushare 代码级对照；本轮不写正式湖、不写 staging、不写 Dagster，以全历史聚合行数和抽样流式行数对账代替 written rows。

验证结果：`raw_tushare.dc_member` 共 `25,326,662` 行，覆盖 `2024-12-20` 至 `2026-07-13` 的 `376` 个 expected SSE open dates；缺日期、范围外日期、重复主键、空主键、非法代码和空名称均为 `0`。起始日、`2025-05-30`、最新日和中间样本日的流式行数均与聚合行数一致。全历史聚合耗时约 `110,930.151 ms`，报告为 `/private/tmp/dc_board_m1b_prod_bootstrap_validation_20260714.json`。

有限 Tushare 对照结果：四个日期分别从 prod 确定性抽取板块代码，每日至多 20 个代码；使用 Tushare MCP `dc_member` 显式请求 `trade_date,ts_code,con_code,name`，共 69 个 `trade_date + ts_code` 请求。prod 与 Tushare 的行数和排序后的四字段行集合 `69/69` 一致，差异 `0`。报告为 `/private/tmp/dc_board_m1b_prod_bootstrap_reconciliation_20260714.json`。

M1B 结论：**通过**。本轮没有写 staging，因此不把 source rows 伪装成 written rows；正式 staging 的写入耗时、磁盘和原子 promote 恢复仍需在后续临时 lake 验证。Tushare 全市场分页仍保持被拒绝；M1C 整改后的日常按代码请求结果见下节。

### M1C：dc_member 日常 Tushare 代码循环验证与策略整改

核心任务：只读实测最近交易日和历史抽样日的候选代码集合、单代码分页、空代码、请求次数、配额、失败重试和 p50/p95 耗时；先验证有界请求策略，再确认不写正式 Raw。

profiling 结果（2026-07-14）：候选集合来自当日 `dc_index` 三类代码并集；由于当前没有已完成 Raw `dc_member` 分区，未额外并入 member-only 代码。四个日期候选数为 `2024-12-20=458`、`2025-02-19=462`、`2025-05-30=552`、`2026-07-13=1,022`。每日期抽取 80 个确定性代码，使用工程 `TushareResource.call`、显式字段和 `limit=5000/offset` 做 320 个单代码请求。

- 原始无界连续请求约 `10.2 req/s` 时真实触发 Tushare `dc_member` 频率超限；这个失败事实保留为反例，不能回流。
- 2026-07-14 的 profiling 版本新增 `orchestrator/defs/tushare_request_policy.py`，提供 `0.13s` 最小间隔、最多 3 次重试、`1/2/4s` 指数退避、单次退避最多 `8s`、单分区最多 `1,200` 次请求、单分区最多 `300s`。权限/参数/字段等确定性错误不重试；限流和网络瞬态错误才重试。分页每一页共用同一预算。
- 安全重测共 323 个分页请求，其中 3 次重试全部恢复；成功/空结果/失败/未尝试代码为 `286/37/0/0`，多页代码 `0`，日期/代码/空主键/重复业务主键错误为 `0`。请求 p50 `46.112ms`、p95 `136.134ms`、最大 `1,382.451ms`，墙钟 `59,507.589ms`；最近日 1,022 个候选的硬下限仍为 `122.64s`。
- 空结果探针正常返回 0 行；合成超时后第二次真实请求返回 444 行；两者均通过有界策略且没有任何正式写入。
- 报告：`/private/tmp/dc_board_m1c_validation_20260714.json`；详情：`/private/tmp/dc_board_m1c_member_request_profile_throttled_20260714.json`。

M1C 结论：**整改后通过**。进入 M2 的条件已满足，但正式 Raw writer 必须复用该策略：任何失败代码、预算超限或分页未完成都整日 fail-closed，并把失败/未尝试代码写入本次 run metadata，而不是写入 cursor 或伪装成空结果。

### M1C 后续预算校准（2026-07-24）

上述 300 秒是 M1C profiling 的历史事实。正式运行 `raw_tushare_dc_member_update_job[2026-07-23]` 证明当前源端延迟可以使 `802 / 1,022` 个无重试请求耗尽 `300.070s`，剩余 220 个代码未尝试；writer 在对账和 promote 前停止，既有 Lake 文件未受影响。管理员已确认把当前 `DC_BOARD_MAX_ELAPSED_MS` 改为 **600,000ms / 600s**。

该调整不改变共享 `TushareRequestPolicy` 的默认 300 秒，也不改变 300 秒的 prod reference stability 间隔。DC member 仍受 `1,200` 次请求硬上限、`0.13s` 限速、3 次重试和 source/prod 完整 pair 对账保护；600 秒耗尽时仍返回 `max_elapsed_seconds_exceeded`，整日 fail-closed。

### M2：Contract / Catalog 基础

核心任务：增加 schema、字段常量、路径 helper、partition model、catalog entry、中文名和静态门禁。

产出：contract/path/catalog 代码和本地测试；不写正式 lake。

进入 M3 的条件：M2 contract/path/catalog/schema 通过本地测试；六个 active asset/check/job/sensor 不属于 M3，留到 M4/M5。

### M3：Raw 写入能力

M3 已完成。实际入口和边界如下：

- `write_dc_index_partition(...)` 将三个 `idx_type` 放在同一 bounded code-page batch 中，共享单分区请求/重试/时间预算；单类型为空允许，三类全空失败。
- `write_dc_daily_partition(...)` 使用日期分页，保留 `category` 并以 `(ts_code, trade_date, category)` 做重复校验。
- `write_dc_member_partition(...)` 只接受外部给定的 `candidate_codes`，每次只请求一个 `ts_code`，空代码可记录，全部为空失败；请求失败、未尝试代码、预算超限均不 promote。
- `_promote_table(...)` 在 DuckDB 临时表上完成字段/日期/代码/名称/主键校验，使用唯一 staging 文件，显式回读 schema 和行数后才 `os.replace`。
- `export_dc_member_partition_from_prod_db(...)` 只投影 `trade_date, ts_code, con_code, name`，使用 named cursor 和 `fetchmany`，上下文结束 rollback；目标文件失败时保持原样。

本地验证命令：

```bash
PYTHONPATH=src uv run --project . --with pytest python -m pytest \\
  tests/test_tushare_request_policy.py \\
  tests/test_dc_board_raw_io.py \\
  tests/test_dc_board_bootstrap.py \\
  tests/test_dc_board_performance.py \\
  tests/test_run_contract_static_gates.py
```

结果：`96 passed` 的核心回归，另有 1 个 1,022 代码性能样本通过；报告为 `/private/tmp/dc_board_m3_performance_20260714.json`。测试只使用临时/内存数据，未运行 `dg`、未写正式湖、未写正式 Dagster DB。

进入 M4 的条件已满足：单日临时 writer、失败不覆盖、分页/预算/回读校验和只读 Bootstrap 流式边界全部通过。

### M4：Raw Dagster 接入（历史基线，M9-R 待迁移）

M4 已完成，实际实现如下：

- `assets/dc_board_raw.py` 的三个 asset 当时使用 `cn_a_index_trade_days`，只处理 `context.partition_key`，调用 M3 writer 并写入结构化 materialization metadata。M9-R 将其分别迁移到三个专属 partition set。
- `raw_tushare_dc_member` 的 candidate planner 只读取目标日 raw `dc_index` 与最近存在的历史 member 分区；第一个 expected 日期允许无历史 baseline，后续日期缺 baseline 或 candidate 超过 `DC_BOARD_MAX_REQUESTS_PER_PARTITION` 直接 fail closed。
- `checks/dc_board_checks.py` 的三个 core check 历史上显式声明 `partitions_def=cn_a_index_trade_days`、`blocking=True`，正式路径禁止多分区聚合结果；M9-R 迁移后必须改为对应专属 partition set，并在当前文件检查之外接入 source closure/同日关系门禁。
- `asset_guards/dc_board_lake_readiness.py` 复用 `ContinuityBatchReadiness`/`ContinuityDateReadiness`，缺文件为 `materialized=False`，文件存在但语义失败为 `materialized=True, checks_passed=False`；一个 batch 调用最多扫描最近 10 日文件。
- `sensors/dc_board_sensor.py` 的每个 sensor tick 只打开一个 DuckDB connection，先做 expected calendar/registered partition 门禁，再做 batch readiness；`dc_member` 先要求 raw `dc_index` 窗口连续，不在 sensor 热路径计算 candidate 或请求 Tushare。三个 sensor 默认 `STOPPED`，每 tick 最多一个 `RunRequest`。
- `jobs/dc_board.py` 的三个 job 只选择各自 Raw asset 与 checks，不选择 Silver，不加入多分区 check。

M4 本地验证：M3 + M4 scoped suite `112 passed`；完整 definitions load 可见三资产、三 check、三 job、三 sensor。验证未运行 `dg launch`、未启动 daemon/webserver、未启用 sensor、未访问正式 lake/DB。

产出：Raw definitions、sensor 测试、单分区 check event 归属测试。

进入 M5 的条件已满足：sensor 每 tick 最多提交一个 first-not-ready 分区；不读 Dagster event history；默认 sensor 仍为 `STOPPED`；M3 writer/static gate 未回退。

### M5：Silver 写入与核心 check（历史基线，M9-R 待迁移分区与关系门禁）

#### M5.1 实际代码边界

- Silver writer 与 asset 位于 `defs/assets/dc_board_silver.py`，没有把 Dagster decorator 加回 M3 的 `defs/assets/dc_board.py`。
- `_SPECS` 为三类数据冻结 Raw schema、Silver schema、物理路径、业务主键和规范化/rejection SQL：`dc_index` 使用 `(ts_code, trade_date)`，`dc_member` 使用 `(trade_date, ts_code, con_code)`，`dc_daily` 使用 `(ts_code, trade_date, category)`。
- 每个 writer 先验证 Raw 文件存在、schema 与 Raw contract 一致、目标日期是唯一 SSE open date、源行数大于 0；再用 DuckDB 集合 SQL 完成日期解析、trim/uppercase、身份字段和数值域验证。
- 同一业务主键的完全相同行通过 `SELECT DISTINCT` 去重；同一业务主键存在不同业务值时抛 `DcBoardSilverValidationError`。拒绝行、重复数、冲突数写入内存态结果与 materialization metadata，不写入业务列。
- 输出使用 `target.parquet.m5-<uuid>.tmp`，DuckDB `COPY` 后回读 schema 和行数，全部通过后才 `os.replace`；任意异常删除 staging 并保持已有 target 不变。
- `silver_dc_index`、`silver_dc_member`、`silver_dc_daily` 历史上均使用 `cn_a_index_trade_days`、`deps=[对应 raw asset]`、同一 partition 单次执行；M9-R 必须分别迁移到对应专属 partition set，并将同日关系审计纳入正式成功门禁。

#### M5.2 Core check 实现

`defs/checks/dc_board_silver_checks.py` 提供三个 check：

```text
silver_dc_index_core_check
silver_dc_member_core_check
silver_dc_daily_core_check
```

每个 check 在历史实现中显式设置 `partitions_def=cn_a_index_trade_days`、`blocking=True`，并通过 `additional_deps` 绑定对应 Raw asset。M9-R 必须改为对应的专属 partition set，并把同日关系纳入正式成功门禁。check 只读取当前 Silver Parquet，使用 DuckDB set-based SQL 检查文件/行数、schema、分区日期、业务主键非空唯一、板块/股票身份字段和数值域。失败 metadata 固定包含 `failed_rules`、`reason_code`、`partition_key`、`checked_row_count`、`failed_row_count`、文件路径和最多 5 条样本。不存在 Dagster event history、Tushare 或 Prod DB 读取。

#### M5.3 联调与验证

- `tests/test_dc_board_silver.py` 覆盖三类 Silver writer、日期规范化、`category` 主键保留、完全重复去重、冲突主键拒绝、分区日期错误和失败不覆盖。
- `tests/test_dc_board_silver_definitions.py` 与静态门禁覆盖三个 asset/check 的分区和依赖边界，并确认 M5 没有新增 job/sensor。
- M3/M4/M5 scoped suite 结果为 `123 passed`；定义加载可见 66 个 asset 和新增三个 Silver check。仅使用临时/内存 lake，未运行 `dg launch`、未启动 daemon/webserver，未写正式湖、Dagster DB 或事件。
- 临时性能样本 `/private/tmp/dc_board_m5_performance_20260714.json` 使用每类 3,000 行：`dc_index=24.094ms`、`dc_member=20.839ms`、`dc_daily=21.587ms`；三类 source/output 均为 3,000 行，重复删除为 0。该样本不替代 M7 全量 Bootstrap 的磁盘、日期循环和总耗时验证。

进入 M6 的条件已满足：同日 Raw ready 后 Silver 能生成正确分区；失败不覆盖已有文件；跨数据集历史非等集不误阻断；三个 check 都是单分区可归因 check。

### M6：Silver Dagster 接入（历史基线，M9-R 待迁移分区与 Raw 完整成功门禁）

#### M6.1 文件与共享规则

新增或修改：

| 文件 | 责任 |
| --- | --- |
| `defs/asset_guards/dc_board_silver_quality.py` | Silver core check 与 readiness 共用的 schema、主键、身份和数值域规则 |
| `defs/asset_guards/dc_board_silver_lake_readiness.py` | 三个 Silver batch readiness，返回内存态 `ContinuityBatchReadiness` |
| `defs/jobs/dc_board_silver.py` | 三个只选择 Silver asset/check 的单分区 job |
| `defs/sensors/dc_board_silver_sensor.py` | 三个默认停止的 Silver sensor、Raw/Silver frontier 门禁和 cursor |
| `defs/checks/dc_board_silver_checks.py` | 复用共享质量规则，保持 check 名称和单分区归属不变 |

三个 job/sensor 名称固定为：

```text
silver_dc_index_update_job
silver_dc_member_update_job
silver_dc_daily_update_job
```

#### M6.2 Readiness SQL 语义

历史实现每个 sensor tick 使用一个 DuckDB connection 加载 `silver_trade_calendar` 和最近 10 个 expected `cn_a_index_trade_days`，然后批量计算同窗口的 Raw/Silver 状态。M9-R 迁移后改为读取对应专属 partition set，并在 Silver 提交前要求 Raw source closure 完整成功。

Silver readiness 复用 core check 的完整规则：

1. `DESCRIBE` 校验列顺序和类型。
2. 按路径提取分区日期，检查 `trade_date` 和行数。
3. 按业务主键聚合，检查空键和重复键。
4. 检查板块代码、股票代码、`idx_type`、`category` 和名称规则。
5. 检查价格、数量、比例和金额数值域。

文件缺失返回 `materialized=False`；文件存在但为空或任一规则失败返回 `materialized=True, checks_passed=False`，进入人工处理分支，不自动覆盖已有 Silver 文件。

#### M6.3 Sensor 选择与 Raw frontier 门禁

```text
registered partition gap
    -> Raw batch readiness
    -> Silver batch readiness
    -> Silver first-not-ready
    -> Raw frontier comparison
    -> one RunRequest or SkipReason
```

Raw first-not-ready `<` 或 `==` Silver target 时 skip；Raw first-not-ready `>` Silver target 或 Raw 全 ready 时，允许提交 Silver target。Silver materialized check failure 始终 skip，不重跑。

每次最多返回一个 RunRequest，run key 由 `build_asset_update_run_key` 生成：

```text
silver_dc_index_update:{trade_date}
silver_dc_member_update:{trade_date}
silver_dc_daily_update:{trade_date}
```

Sensor 不调用 `get_event_records`，不访问 Tushare/Prod DB，不解析 run key。cursor 只保存 ASCII reason code、阻断组件、日期 frontier、文件数、耗时和有限样本。

#### M6.4 测试与性能结果

- 新增 readiness、sensor、definition/static gate 测试，覆盖 Raw 阻断、Silver 首个缺口、Raw 较晚缺口、materialized check failure、注册分区缺口、单连接和单 RunRequest。
- M3-M6 scoped suite：`137 passed`。
- 定义加载可见 66 个 asset、162 个 asset checks，以及三组新增 Silver job/sensor。
- 临时性能报告：`/private/tmp/dc_board_m6_readiness_benchmark_20260715.json`；10 日 × 3 数据集共扫描 30 个 Silver 文件，三个 helper 均 10/10 ready，耗时约 4.972ms、5.352ms、5.578ms。
- 本阶段没有正式 lake 写入、Dagster DB 写入、event backfill、`dg launch` 或 sensor 启用。

产出：Silver batch readiness、三个 job、三个 sensor、cursor/frontier 回归测试和临时 lake 性能报告。

进入 M7 的条件已满足：Raw ready 可触发 Silver；Raw 未 ready 阻断 Silver；materialized check problem 不自动覆盖；最近 10 日、单连接、单分区、无 event history 扫描的性能门禁通过。

### M7：全量 Bootstrap

核心任务：`dc_index` / `dc_daily` 从起始日期开始请求 Tushare；`dc_member` 从 prod DB 只读导出历史分区。按日期生成 staging，执行各自来源的字段/日期/主键/行数门禁和有限对照，全部通过后原子 promote Raw，再生成 Silver。

#### M7A：只读 Planner/CLI 与源/目标审计（已完成）

新增文件：

- `orchestrator/defs/bootstrap/dc_board_bootstrap_plan.py`
- `orchestrator/defs/bootstrap/dc_board_bootstrap_cli.py`
- `orchestrator/tests/test_dc_board_bootstrap_plan.py`

实现细节：

1. CLI 只注册 `dry-run` 子命令，没有 `apply`、`os.replace`、Dagster event 或动态分区写入路径。
2. 日期计划从 `silver_trade_calendar` 的 `exchange='SSE' AND is_open=true` 生成，按数据集起点裁剪，并输出日期 fingerprint；不读取 Dagster dynamic partition 作为日期事实。
3. 默认拒绝未来日期。实际全量审计显式固定到 `2026-07-14`，因为日历含未来日期且当日 `2026-07-15` 在审计时尚未完成源数据。
4. `dc_index` 复用有界代码分页，`dc_daily` 复用有界日期分页；列漂移、分页失败、空结果、主键重复、日期越界和身份错误都进入 fail-closed 报告。
5. `dc_member` dry-run 使用 Prod 只读事务、named cursor、`fetchmany` 和数据库侧 set-based 聚合，按日期返回行数、重复主键、代码/名称/日期错误；正式 member writer 仍使用 `fetchmany` 流式导出，不把全历史装入 Python。
6. Raw/Silver 目标通过已有 batch readiness 检查：缺失是待生成，存在但核心语义错误是冲突，默认禁止覆盖。

最终只读报告：`/private/tmp/dc_board_m7_bootstrap_dry_run_20260715_v7.json`。

- `should_stop=false`，有效结束日 `2026-07-14`。
- expected dates：`dc_index=377`、`dc_member=377`、`dc_daily=611`；Raw/Silver 预计文件 `2730` 个。
- source rows：`dc_index=241,948`、`dc_member=25,418,099`、`dc_daily=596,200`。
- source elapsed：`dc_index=232,424.293ms`、`dc_member=86,700.496ms`、`dc_daily=75,199.453ms`；总耗时 `394,717.231ms`。
- Tushare requests：`dc_index=1,131`、`dc_daily=612`；Prod member aggregate cursor chunks `377`。
- Raw/Silver 目标均 missing，invalid conflict `0`，existing bytes `0`；没有正式 lake 写入。

#### M7E：临时 lake 联调（已完成）

`tests/test_dc_board_m7_sample.py` 使用起始、中间、最新三个代表日期，在唯一临时目录中完成：

```text
Tushare fake / Prod-style member stream
    -> Raw staging + atomic promote
    -> Raw file read-back
    -> Silver DuckDB set-based writer
    -> Silver file read-back
```

测试确认 Raw/Silver 文件非空、schema 可读、日期分区正确、失败不覆盖既有目标，且无 staging 残留。M7A/M7E 与 M3/M5 相关测试合计 `25 passed`。

#### M7F-M7I：正式写入与全量对账（已完成；事件/分区为历史 Bootstrap 基线）

M7F 已按最多 20 个交易日批次串行生成 Raw，M7G 已完成 DuckDB 全量对账。首次对账发现 `dc_index[2026-06-23]` 少 `496` 行后立即停止；批准后使用已经过 Tushare 重查和临时 writer 验证的 `1,021` 行 staging 做定点原子重发布。旧文件备份为 `/private/tmp/dc_board_m7_dc_index_2026-06-23_before_republish_20260715T053028Z.parquet`，重发布报告为 `/private/tmp/dc_board_m7_dc_index_republish_20260715T053028Z.json`。

重发布后的 Raw 对账 `/private/tmp/dc_board_m7_raw_audit_20260715.json` 通过：`dc_index=377/377`、`dc_member=377/377`、`dc_daily=611/611`，Raw 实际行数分别为 `241,948`、`25,418,099`、`596,200`，与 v7 源审计一致，missing/invalid/staging residue 均为 `0`。

M7H 已按相同日期计划和最多 20 日串行批次生成 `1365` 个 Silver 文件，M7I 对账 `/private/tmp/dc_board_m7_silver_audit_20260715.json` 通过。最终汇总 `/private/tmp/dc_board_m7_final_reconciliation_20260715.json` 为 `should_stop=false`；正式 Raw/Silver 共 `2730` 个文件，无 staging 残留。

### M8：Dagster 历史事件与验收

#### M8.1 实现边界

新增 `bootstrap/dc_board_events.py` 和 `bootstrap/dc_board_events_cli.py`。历史事件计划读取
M7 v7 日期 fingerprint、Raw/Silver 对账报告和当时的 `cn_a_index_trade_days` 已注册分区；不从
Dagster event history 推导湖事实。六个资产共用一次 plan 中的 DuckDB connection，分别执行
完整 Raw/Silver core readiness，Python 只汇总状态，不逐文件重扫。

- 全量 materialization：`dc_index` Raw/Silver 各 `377`，`dc_member` Raw/Silver 各 `377`，
  `dc_daily` Raw/Silver 各 `611`，共 `2730` 条。
- 最近 20 日 check：六个资产各 `20` 条，共 `120` 条；每条 check 显式带
  `partition=trade_date`、`blocking=True` 和 target materialization data。
- apply 必须显式传入 `--confirm-event-write`；dry-run 不调用 event 写入 API。apply 不写
  Parquet、不运行 job/sensor、不请求 Tushare/Prod DB、不注册动态分区。
- `raw_tushare_dc_member` catalog event policy 为 `supports_runless_event_backfill`，因为其
  历史事实来自 Prod DB 直写湖文件，不能把该分区描述成只能由 Dagster run 产生。

#### M8.2 实际执行与验收

- dry-run：`/private/tmp/dc_board_m8_events_dry_run_20260715.json`，`should_stop=false`，
  计划 materialization `2730`、check `120`、总事件 `2850`。
- apply：`/private/tmp/dc_board_m8_events_apply_20260715.json`，实际报告
  materialization `2730`、check `120`、总事件 `2850`，无跳过、无失败。
- post verify：`/private/tmp/dc_board_m8_events_post_verify_20260715.json`，六个资产的
  materialization 全部达到各自 expected 日期数；每个核心 check 的
  `asset_check_executions.partition` 正好覆盖最近 20 个交易日，target materialization
  storage id 非空，最近 20 日 readiness 全部通过；动态分区 `6427` 不变。
- post dry-run：`/private/tmp/dc_board_m8_events_post_dry_run_20260715.json`，所有资产
  `planned_event_count=0`，证明重复执行不会重复补录。

产出：事件对账报告和数据集验收报告。

该 M8 验收只证明历史 Bootstrap event 的分区归属和最近 20 日旧 readiness 可读；它不证明旧共享分区适合日常自动触发。进入 M9-R 的前置条件满足，不能据此启用旧 sensor。

### M9-R：板块分区与完整性门禁修复（历史实施记录）

M9-R 是当时日常启用前的必要修复专项。以下记录保留其代码和本地验证时的事实；不描述当前
Dagster instance 的 sensor 状态。其专属分区、Lake core check、同日关系和 writer 基础 closure 继续有效，
但 Raw availability 小页 probe 已被 M10 替代：

1. **R0 影响面审计**：核对 `cn_a_index_trade_days` 的所有消费者，特别是 Raw/Silver asset、core check、job、sensor、Gold daily technical 和相关测试；形成旧分区口径清单。
2. **R1 Contract**：在 `partitions.py` 和 `run_contracts/dc_board.py` 增加三个专属分区、起点映射、probe 上限、source closure 计数模型和 ASCII reason code；不新增状态实体。
3. **R2 分区注册**：新增三个 calendar-only registration sensor。通过临时 calendar fixtures 验证三类起点不同、未来日期不注册、重复注册幂等、源站不可用不影响注册。
4. **R3 Writer source closure**：在 Raw writer 结果中补齐请求终态、失败/未尝试、合法空响应、分页和源/写入行数对账；任何异常都在 promote 前 fail closed。
5. **R4 Core check / relation audit**：扩展合并核心 check 和 readiness，验证文件质量、类型/category 覆盖、`dc_daily` 与 `dc_index` 同日代码集合、`dc_member` 请求终态闭环；保持每资产一个 blocking check。
6. **R5 Trigger sensors**：Raw sensor 接入 bounded source probe 和专属 partition set；Silver sensor 接入新的 Raw 完整成功 gate；Gold technical normal/repair 跟随 daily 专属分区。
7. **R6 临时 lake 验证**：覆盖起始日、中间日、最新日、源部分返回、合法空响应、失败代码、未尝试代码、跨表集合不一致和旧目标不覆盖。
8. **R7 性能回归**：验证最近 10 日 batch readiness 单连接、单次 source probe ≤8 秒、event history=0、每 tick ≤1 request、cursor 小且 ASCII；任何接近 RPC deadline 的场景停止。
9. **R8 正式切换前审计**：definitions 静态检查、专属动态分区只读核对、旧 sensor 停止、备份当前 cursor/active run 状态；正式切换和启用另行批准。

#### R5.1 上游 frontier 比较规则

Raw `dc_daily` 和 `dc_member` 依赖同日 `raw_dc_index`，但依赖关系不能实现为“只要上游窗口存在任何未就绪日期就阻断”。每个 sensor 必须先计算自身的
`first_not_ready_trade_date`，再计算上游 `raw_dc_index` 的首个未就绪日期，并按日期比较：

| 上游 `raw_dc_index` 首个未就绪日期 | 自身目标日期 | 处理 |
| --- | --- | --- |
| 早于自身目标 | 任意 | 阻断自身 run |
| 等于自身目标 | 任意 | 阻断自身 run |
| 晚于自身目标 | 已存在更早缺口 | 允许提交自身目标 |
| 无上游缺口 | 已存在自身缺口 | 允许提交自身目标 |

自身 materialized 但 blocking check 失败时，优先按自身失败语义停止，不能被上游状态覆盖。该规则保证上游较晚日期的缺口不会阻断下游较早日期的补洞，同时仍保证不会越过上游尚未覆盖的同日或更早日期。

2026-07-17 的只读运行审计曾观察到：`raw_dc_index` 首个缺口为 `2026-07-17`，而 `raw_dc_daily` / `raw_dc_member` 自身首个缺口为 `2026-07-15`。旧实现只要发现上游有缺口就直接 skip，导致 `2026-07-15` 无法提交；这属于共享 sensor 的 frontier 门禁实现错误，不是源数据缺失或分区注册错误。实现必须在同一个 DuckDB connection 内完成自身和上游最近 10 日 batch readiness，不能回流 Dagster event history、Tushare 请求或 Prod DB 读取。

事件边界：M8 已写入的历史 event 作为审计事实保留，不删除、不自动改写、不用于 source readiness；新定义切换后的事件使用专属 partition set。旧事件如需迁移，另开事件对账/补录专项，不能由 M9-R 隐式完成。

M9-R 的 source closure 当时分为两层，不能混为一谈：

1. **可用性层（已由 M10 取代）**：Raw sensor 只对最近窗口的 first-not-ready 缺失文件做有界 source probe。该 probe 曾只回答“当前是否值得尝试一次 run”；它不请求全量，因而不能证明源端完整。
2. **事实层**：asset writer 在 run 内使用完整 bounded request/streaming export，并在 staging promote 前验证请求终态、分页、日期、列、主键、类别覆盖、源/写入行数和失败/未尝试集合。通过后才原子替换湖文件。随后 core check/readiness 用 DuckDB 复核已落湖文件和同日板块关系，只有三层都通过才返回 `ready=True`。

因此，“成功更新”不是 `source probe ready`、文件存在或 row count > 0；而是 **writer source closure + lake core check + same-day relation gate** 全部通过。Dagster 的事件顺序可能先记录 materialization、再记录 blocking check failure；本专项用 ready frontier 作为自动链路的成功标准，materialization event 不能单独放行下游。

M9-R 通过条件：

- 三类资产使用正确的专属 partition set；旧 `cn_a_index_trade_days` 不再参与正式板块链路。
- 小页 source probe 只属于历史筛选策略；M10 以稳定 prod reference + 完整 Tushare 对照替代。更新成功仍必须同时满足 source closure、core check 和同日关系闭环。
- 任一 partial response、failed/unattempted request、source/output row mismatch、code set mismatch 都不能进入 ready frontier。
- 不自动覆盖已 materialize 但 check 失败的文件，不读取 Dagster event history，不扩大 sensor 窗口。

本轮本地回归：板块 Raw/Silver/Gold 定义、readiness、source probe、分区注册、关系审计、临时 lake 和静态门禁共 `155 passed`；未运行 `dg`、未启用 sensor、未写正式 lake 或 Dagster event。

### M10：稳定 prod 基线与完整 Tushare 对照（代码完成，待正式审计/启用）

M10 是本 LLD 当前唯一的 Raw 日常 source-finalization 方案。它的目标是拒绝“源端能返回少量行但尚未
发布完整当天目录”的中间状态；不增加 Dagster 事件、check、资产、job、sensor、分区或 Lake 状态文件。

执行顺序固定：

1. **T0 只读 identity 审计（已完成）**：用 prod readonly transaction 核实 `core_serving.dc_index`、`dc_daily`、
   `dc_member` 的列、主键、当前日 `(type, code)` 与 `(ts_code, con_code)` identity 对照可行性，并记录
   读行数、耗时和查询计划。若 prod 语义与 Tushare Raw schema 不可直接对齐，停止，不猜测映射。
2. **T1 Contract / config（已完成）**：实现 2.4 中的单一 policy contract、紧凑 reference dataclass、run-scoped
   `DcBoardIndexReferenceConfig` 和统一 run-config builder。禁止在 run key、cursor 人可见字段或 Lake
   文件写入完整参考集合。
3. **T2 Raw index gate（已完成）**：把当前 `limit=1` probe 替换为当前日双 prod snapshot、稳定后的一次完整
   Tushare index/daily identity 对照；保持 600 秒 sensor 间隔、最近 10 日 window 和每 tick 最多一个 run。
4. **T3 Writer closure（已完成）**：三个 Raw writer 注入 readonly prod reference，index 校验冻结 fingerprint，daily
   做 raw-index/Tushare/prod 三方闭环，member 做同日候选与 pair 差集。任何失败保留正式 Parquet 原样。
5. **T4 本地验证（已完成）**：全部 fake prod/Tushare 正负向测试、静态门禁和性能测试通过；M10 定向回归 `99` 条，资产治理与 cursor contract 回归 `18` 条，Bootstrap/M7 样本调用通过。确认没有新 check、
   event、asset、job 或 member sensor 全量请求。
6. **T5 正式只读审计（待单独批准）**：读取当前 prod reference 与 Tushare 对照，输出请求数、行数、hash、耗时。
   通过后才单独决定 Definitions 验证和 sensor 启用策略；M10 本身不写 Lake、prod、Dagster DB 或动态分区。

停止条件：prod 表缺列/主键或同日内部闭环不成立；Tushare 与已稳定 prod reference identity 不一致；完整
index sensor 超过 10 秒；需要让 member sensor 逐代码请求；需要新增 manifest/summary asset；或任何路径试图
用 `limit=1`、文件存在、row count 或历史 event 代替完整 source closure。

### M9：日常切换与观察（M10 完成后，待单独批准）

正式切换前先做只读 definitions、专属 dynamic partition、active run 和 cursor 审计；通过后才在 M10 代码下
启用或恢复对应的 Raw/Silver update sensors。连续观察至少 3 个实际交易日后，再单独决定是否启用 Gold
technical normal/repair sensor。观察记录必须包含 prod snapshot 计数/hash、完整 Tushare 对照结果、source
closure 计数、check reason、frontier、cursor、tick elapsed 和下游链路状态。M10 本轮不执行任何 sensor
enable 或正式 run。

### 阶段合并边界

- M2 + M3 可以合并开发，但必须先通过 M1B 的 prod Bootstrap 门禁和 M1C 的日常 Tushare 代码请求门禁。
- M4 + M5 可以在临时 lake 上联调，正式 sensor 和 event 验收仍要分别通过。
- M6 只能在 Raw/Silver 单日正确性已确认后推进。
- M7、M8、M9-R、M10、M9 必须分开执行，不能把全量请求、文件发布、事件补录、分区迁移、source-finalization
  修改和 sensor 启用合成一个不可回滚动作。

### 全局停止条件

任一阶段发现 Tushare 分页不完整、请求量超预算、单 tick 超过 Dagster RPC 安全预算、check 归属不正确、数据湖文件被部分覆盖或需要依赖历史 event 才能判断 ready，立即停在当前 milestone，不继续扩范围。
