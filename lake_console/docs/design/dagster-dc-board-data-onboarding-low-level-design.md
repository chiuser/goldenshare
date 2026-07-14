# Dagster `dc_index` / `dc_member` / `dc_daily` 低层设计（LLD）

> 本文基于 [`dagster-dc-board-data-onboarding-plan.md`](./dagster-dc-board-data-onboarding-plan.md)。
> 方案文档冻结业务口径；本文冻结文件、函数、SQL、事务、测试和推进顺序。
>
> 当前状态：M3 Raw-only writer/staging、M4 Raw Dagster definitions、M5 Silver writer/asset/check 已实现并通过本地临时 lake 验证；M6 尚未开始。M4 sensor 仍为 `STOPPED`，M5 未启用 Silver sensor，不运行正式 job，不读写正式数据湖或 Dagster DB。

## 1. LLD 约束

### 1.1 硬约束

1. 三个数据集都按 `trade_date` 分区，复用 `cn_a_index_trade_days`。
2. `dc_index` / `dc_member` 起点 `2024-12-20`；`dc_daily` 起点 `2024-01-02`。
3. `dc_index` / `dc_daily` 的 Raw bootstrap 和日常更新都请求 Tushare；`dc_member` 历史 Bootstrap 使用 prod DB 只读导出，日常更新使用 Tushare 按交易日 + `ts_code` 请求。两者共用同一 Raw schema/path/key，但必须在 metadata 中区分来源。
4. M1 实测已否决 `dc_member` 按日期全市场分页作为成员事实源；日常按日期+板块代码是当前已验证的完整性方向。M1B 已完成 prod Bootstrap 覆盖、流式导出和有限 Tushare 对照验证；M1C 原始无界路径曾触发真实 `500 requests/minute` 限制，整改后的有界请求策略已通过只读重测。
5. `dc_daily` 保留 `category`，业务主键固定为 `(ts_code, trade_date, category)`。
6. 每个资产只有一个合并核心 blocking check，但 check 必须是 partitioned、单分区可归因、当前文件 set-based 检查。
7. 分页、行数、请求耗时和空结果属于写入前安全门禁与 materialization metadata，不再拆出额外 check event。
8. sensor 只读 DuckDB/lake 文件和当前资源事实，不扫描 Dagster event history；每 tick 最多 1 个 run request。
9. 任何 source/row/key/date 不一致都 fail closed，不用“已有文件”冒充 ready。
10. 不新增用户可见配置项。起点、页大小、允许的类型和性能上限先作为代码 contract 常量；若后续需要运营可调，再单独做配置审计。

### 1.2 依赖边界

```text
TushareResource / ProdPostgresResource(read-only Bootstrap)
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
          bounded lake readiness -> sensors -> jobs
```

`dc_index`、`dc_member`、`dc_daily` 的跨数据集关系只进入离线审计 helper，不作为 Silver asset 的 Dagster dependency，避免历史覆盖差异把正常更新全部卡死。

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
```

最后两个值不能凭经验填写。P0 必须用真实 `TushareResource.call` 测量最近交易日，得到 p50/p95 后再定拒绝阈值。

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

日常只处理一个 expected `trade_date`。候选 `ts_code` 取当日 `dc_index` 三类代码与最近已完成 Raw `dc_member` 分区代码的并集，避免只取指数当天代码而漏掉历史 member-only 代码。

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
6. 单 partition 超过 `1,200` 次请求或 `300s` elapsed budget 时停止该 partition，输出预算原因和失败/未尝试代码清单，整日不写 Raw，避免重试风暴。

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
| `dc_member` 日常 | 每个交易日 | 当前观测约 1,023 个代码请求；使用 `0.13s` 最小间隔、最多 1,200 请求、最多 300s；超过预算整日 fail-closed |
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
- `partitions_def=cn_a_index_trade_days`
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

- 输入：DuckDB connection、lake root、最近 10 个 expected dates、asset kind、registered partitions。
- 一次规划当前窗口文件；按文件存在、目标日 row count、schema/key/domain 做 set-based SQL。
- 返回 `ready/materialized/checks_passed/reason/failed_rules/elapsed_ms`。
- 文件存在但 check 失败：`materialized=True, checks_passed=False`，sensor 不自动覆盖，要求人工处理。
- 文件缺失或目标日 0 行：`materialized=False`，允许 first-not-ready 自动触发。

### 10.2 Sensor 流程

每个 sensor 遵循同一流程：

```text
load SSE expected window (10)
 -> check dynamic partition registered gap
 -> one DuckDB batch readiness call
 -> select_first_not_ready_trade_date
 -> materialized check problem => skip
 -> missing/unready file => build_run_request(one partition)
```

Raw sensor 在提交前还必须完成：

- source API readiness（不把 Tushare 空响应当成成功）。
- 当前日期不超出历史起点和 SSE open calendar。

Silver sensor 只在同日 Raw ready 后提交 Silver run。跨数据集关系不进入 sensor。

### 10.3 Cursor 字段

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

禁止写每个板块代码的完整列表、每一页的明细或跨 tick 业务事实。

## 11. Job 和 Definitions 装配

每个 job 只写 selection：

```python
raw_tushare_dc_index_update_job = dg.define_asset_job(
    name="raw_tushare_dc_index_update_job",
    selection=(
        dg.AssetSelection.assets(raw_tushare_dc_index)
        | dg.AssetSelection.checks_for_assets(raw_tushare_dc_index)
    ),
)
```

其他五个 job 同形，不在 job 中调用 Tushare、DuckDB 或 check helper。

Definitions 装配必须同时包含：

- 六个 asset。
- 六个 core check。
- 六个 job。
- 六个 sensor。
- 共享 `cn_a_index_trade_days` 和必要 resources。

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

### 12.2 Raw writer

- 正常单日完整写入。
- 任何页失败不覆盖正式文件。
- open date 全空失败；`dc_index` 单类型为空但总结果非空可通过。
- trade_date 越界、未知 idx_type/category、重复主键、源/写入行数不等失败。
- 2,124 条已知 prod/source `dc_daily` 差异不进入最终 Tushare staging；最终事实只来自 Tushare。

### 12.3 Silver writer

- 类型转换和交易日过滤。
- `dc_daily` category 保留并参与 key。
- duplicate key fail closed，不 silently drop conflict。
- 不因 `dc_index` / `dc_member` / `dc_daily` 的历史覆盖差异误阻断。

### 12.4 Checks and sensors

- 每个 core check 的 `partitions_def` 为 `cn_a_index_trade_days`。
- check 只针对当前 partition，event 归属正确。
- materialized check problem 不自动重跑。
- missing file/0 rows 选择 first-not-ready。
- sensor 每 tick 最多 1 个 request，使用统一 run key/cursor builder。
- 禁止直接 `dg.RunRequest`、手写 run key、解析 event history。

### 12.5 Bootstrap

- `dc_index` / `dc_daily` 的 Tushare Bootstrap 不把全历史分页结果一次性 `fetchall` 到 Python；`dc_member` Bootstrap 不把 prod 的全历史结果一次性 `fetchall` 到 Python。
- `dc_member` Bootstrap 只使用 read-only prod resource，不能误用 write resource 或在 sensor 中访问 prod。
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
- bootstrap 峰值内存和单日期耗时。

### 13.2 不可接受

- `dc_member` 全市场分页无法证明完整，却直接上线。
- 单个 sensor tick 超过 Dagster RPC 的安全预算，或稳定态进入秒级/十秒级深扫而没有拆分计划。
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
- 新增 `orchestrator/defs/tushare_request_policy.py`，提供 `0.13s` 最小间隔、最多 3 次重试、`1/2/4s` 指数退避、单次退避最多 `8s`、单分区最多 `1,200` 次请求、单分区最多 `300s`。权限/参数/字段等确定性错误不重试；限流和网络瞬态错误才重试。分页每一页共用同一预算。
- 安全重测共 323 个分页请求，其中 3 次重试全部恢复；成功/空结果/失败/未尝试代码为 `286/37/0/0`，多页代码 `0`，日期/代码/空主键/重复业务主键错误为 `0`。请求 p50 `46.112ms`、p95 `136.134ms`、最大 `1,382.451ms`，墙钟 `59,507.589ms`；最近日 1,022 个候选的硬下限仍为 `122.64s`。
- 空结果探针正常返回 0 行；合成超时后第二次真实请求返回 444 行；两者均通过有界策略且没有任何正式写入。
- 报告：`/private/tmp/dc_board_m1c_validation_20260714.json`；详情：`/private/tmp/dc_board_m1c_member_request_profile_throttled_20260714.json`。

M1C 结论：**整改后通过**。进入 M2 的条件已满足，但正式 Raw writer 必须复用该策略：任何失败代码、预算超限或分页未完成都整日 fail-closed，并把失败/未尝试代码写入本次 run metadata，而不是写入 cursor 或伪装成空结果。

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

### M4：Raw Dagster 接入

M4 已完成，实际实现如下：

- `assets/dc_board_raw.py` 的三个 asset 使用 `cn_a_index_trade_days`，只处理 `context.partition_key`，调用 M3 writer 并写入结构化 materialization metadata。
- `raw_tushare_dc_member` 的 candidate planner 只读取目标日 raw `dc_index` 与最近存在的历史 member 分区；第一个 expected 日期允许无历史 baseline，后续日期缺 baseline 或 candidate 超过 `DC_BOARD_MAX_REQUESTS_PER_PARTITION` 直接 fail closed。
- `checks/dc_board_checks.py` 的三个 core check 均显式声明 `partitions_def=cn_a_index_trade_days`、`blocking=True`，正式路径禁止多分区聚合结果；每个 check 只在当前文件上做 set-based schema/row/date/key/identity 检查。
- `asset_guards/dc_board_lake_readiness.py` 复用 `ContinuityBatchReadiness`/`ContinuityDateReadiness`，缺文件为 `materialized=False`，文件存在但语义失败为 `materialized=True, checks_passed=False`；一个 batch 调用最多扫描最近 10 日文件。
- `sensors/dc_board_sensor.py` 的每个 sensor tick 只打开一个 DuckDB connection，先做 expected calendar/registered partition 门禁，再做 batch readiness；`dc_member` 先要求 raw `dc_index` 窗口连续，不在 sensor 热路径计算 candidate 或请求 Tushare。三个 sensor 默认 `STOPPED`，每 tick 最多一个 `RunRequest`。
- `jobs/dc_board.py` 的三个 job 只选择各自 Raw asset 与 checks，不选择 Silver，不加入多分区 check。

M4 本地验证：M3 + M4 scoped suite `112 passed`；完整 definitions load 可见三资产、三 check、三 job、三 sensor。验证未运行 `dg launch`、未启动 daemon/webserver、未启用 sensor、未访问正式 lake/DB。

产出：Raw definitions、sensor 测试、单分区 check event 归属测试。

进入 M5 的条件已满足：sensor 每 tick 最多提交一个 first-not-ready 分区；不读 Dagster event history；默认 sensor 仍为 `STOPPED`；M3 writer/static gate 未回退。

### M5：Silver 写入与核心 check（已完成）

#### M5.1 实际代码边界

- Silver writer 与 asset 位于 `defs/assets/dc_board_silver.py`，没有把 Dagster decorator 加回 M3 的 `defs/assets/dc_board.py`。
- `_SPECS` 为三类数据冻结 Raw schema、Silver schema、物理路径、业务主键和规范化/rejection SQL：`dc_index` 使用 `(ts_code, trade_date)`，`dc_member` 使用 `(trade_date, ts_code, con_code)`，`dc_daily` 使用 `(ts_code, trade_date, category)`。
- 每个 writer 先验证 Raw 文件存在、schema 与 Raw contract 一致、目标日期是唯一 SSE open date、源行数大于 0；再用 DuckDB 集合 SQL 完成日期解析、trim/uppercase、身份字段和数值域验证。
- 同一业务主键的完全相同行通过 `SELECT DISTINCT` 去重；同一业务主键存在不同业务值时抛 `DcBoardSilverValidationError`。拒绝行、重复数、冲突数写入内存态结果与 materialization metadata，不写入业务列。
- 输出使用 `target.parquet.m5-<uuid>.tmp`，DuckDB `COPY` 后回读 schema 和行数，全部通过后才 `os.replace`；任意异常删除 staging 并保持已有 target 不变。
- `silver_dc_index`、`silver_dc_member`、`silver_dc_daily` 均使用 `cn_a_index_trade_days`、`deps=[对应 raw asset]`、同一 partition 单次执行；不依赖跨数据集集合相等。

#### M5.2 Core check 实现

`defs/checks/dc_board_silver_checks.py` 提供三个 check：

```text
silver_dc_index_core_check
silver_dc_member_core_check
silver_dc_daily_core_check
```

每个 check 显式设置 `partitions_def=cn_a_index_trade_days`、`blocking=True`，并通过 `additional_deps` 绑定对应 Raw asset。check 只读取当前 Silver Parquet，使用 DuckDB set-based SQL 检查文件/行数、schema、分区日期、业务主键非空唯一、板块/股票身份字段和数值域。失败 metadata 固定包含 `failed_rules`、`reason_code`、`partition_key`、`checked_row_count`、`failed_row_count`、文件路径和最多 5 条样本。不存在 Dagster event history、Tushare 或 Prod DB 读取。

#### M5.3 联调与验证

- `tests/test_dc_board_silver.py` 覆盖三类 Silver writer、日期规范化、`category` 主键保留、完全重复去重、冲突主键拒绝、分区日期错误和失败不覆盖。
- `tests/test_dc_board_silver_definitions.py` 与静态门禁覆盖三个 asset/check 的分区和依赖边界，并确认 M5 没有新增 job/sensor。
- M3/M4/M5 scoped suite 结果为 `123 passed`；定义加载可见 66 个 asset 和新增三个 Silver check。仅使用临时/内存 lake，未运行 `dg launch`、未启动 daemon/webserver，未写正式湖、Dagster DB 或事件。
- 临时性能样本 `/private/tmp/dc_board_m5_performance_20260714.json` 使用每类 3,000 行：`dc_index=24.094ms`、`dc_member=20.839ms`、`dc_daily=21.587ms`；三类 source/output 均为 3,000 行，重复删除为 0。该样本不替代 M7 全量 Bootstrap 的磁盘、日期循环和总耗时验证。

进入 M6 的条件已满足：同日 Raw ready 后 Silver 能生成正确分区；失败不覆盖已有文件；跨数据集历史非等集不误阻断；三个 check 都是单分区可归因 check。

### M6：Silver Dagster 接入（待开始）

核心任务：增加三个 Silver job/sensor，接通 Raw → Silver 的 first-not-ready 连续触发，保持最近 10 日窗口和 lake readiness。

产出：Silver sensor/cursor/partition event 回归测试。

进入 M7 的条件：Raw ready 可触发 Silver；materialized check problem 不自动覆盖；sensor 热路径保持性能预算。

### M7：全量 Bootstrap

核心任务：`dc_index` / `dc_daily` 从起始日期开始请求 Tushare；`dc_member` 从 prod DB 只读导出历史分区。按日期生成 staging，执行各自来源的字段/日期/主键/行数门禁和有限对照，全部通过后原子 promote Raw，再生成 Silver。

产出：完整 request/page/row/elapsed 报告、失败日期清单、prod 对照报告、Raw/Silver 文件。

进入 M8 的条件：所有请求和 staging 门禁通过；没有未解释的空结果、分页缺口、重复主键、日期越界或写入行数不一致。

### M8：Dagster 历史事件与验收

核心任务：成功分区补全 materialization；只为最近 20 个交易日补 check event；对账文件、事件 partition、prod/Tushare 样本和业务查询。

产出：事件对账报告和数据集验收报告。

进入 M9 的条件：materialization/check partition 归属正确，事件补录失败不会影响 parquet，最近 20 日状态可被 readiness 正确读取。

### M9：日常切换与观察

核心任务：保持 sensor 默认关闭，由运营手动启用；观察连续多个交易日的 Raw/Silver 更新、请求量、耗时、cursor 和下游查询。

产出：日常运行报告、性能回归报告和专项收口记录。

### 阶段合并边界

- M2 + M3 可以合并开发，但必须先通过 M1B 的 prod Bootstrap 门禁和 M1C 的日常 Tushare 代码请求门禁。
- M4 + M5 可以在临时 lake 上联调，正式 sensor 和 event 验收仍要分别通过。
- M6 只能在 Raw/Silver 单日正确性已确认后推进。
- M7、M8、M9 必须分开执行，不能把全量请求、文件发布、事件补录和 sensor 启用合成一个不可回滚动作。

### 全局停止条件

任一阶段发现 Tushare 分页不完整、请求量超预算、单 tick 超过 Dagster RPC 安全预算、check 归属不正确、数据湖文件被部分覆盖或需要依赖历史 event 才能判断 ready，立即停在当前 milestone，不继续扩范围。
