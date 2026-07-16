# Dagster 历史 Materialization 状态恢复低层设计

更新时间：2026-07-15
状态：已完成（A-E 单日文件资产与 P4 股票-年份分钟金层可信历史状态恢复均已完成）
范围：只恢复历史 Lake 分区的 Dagster `AssetMaterialization`；不补任何 asset check。

## 1. 要解决什么

此前为了收敛 Dagster PostgreSQL 体积，历史 materialization event 被大范围清理，只保留了最近状态。Lake 中的大量历史 Parquet 仍在，但 Dagster Asset 页面把这些分区显示为“未 materialized”。这会带来两个误导：

1. 人在 Asset 页面看不出文件到底不存在，还是仅仅少了历史 UI 状态。
2. 以 materialized partition 为起点的历史 backfill 选择，会把已有文件误当成待生产分区。

本专项要恢复的只是这一个事实：**某个已注册的 asset partition 在 Lake 中已有可读取的物理产物。**

它不恢复、更不伪造以下事实：

- 文件是否通过 blocking checks；
- 该数据是否可以被下游消费；
- 该分区是否已由正式 job 成功生产；
- 历史 run、check、cursor、dynamic partition 或 source 数据。

Dagster 的分区页面以 materialization 显示分区状态；一个 partition 通常对应一个文件或一段表数据。因此，用受控 runless materialization 把“已有历史文件”重新呈现在 UI 中，符合这个用途。[Dagster partitioned assets](https://release-1-5-9.dagster.dagster-docs.io/concepts/partitions-schedules-sensors/partitioning-assets)

## 2. 已确认口径

以下三项已经拍板，后续实现不得再重新解释：

1. **范围**：只处理当前 active、Lake-backed、且有明确物理文件枚举规则的分区 asset。ClickHouse/Postgres serving、无数据文件 asset、平台 health asset、contract-only asset、已退出资产均排除。
2. **异常不自动处理**：空文件、Parquet footer 无法读取、文件集合不完整、已有 check 但无 materialization、路径或分区身份无法确认，全部只报告，不写 materialization。
3. **materialized 不等于 ready**：本专项不补 check；缺 check 或 check 未绑定最新 materialization 的分区仍必须是 not ready，不能触发下游自动生产。

## 3. 关键风险与设计结论

### 3.1 最大风险：错误地覆盖“最新 materialization”身份

当前 `partition_dataset_readiness_status_from_latest_checks(...)` 会先读取目标分区的**最新** materialization，再只接受绑定到该 storage id 的 blocking check。也就是说，给一个已有 check 的历史分区追加 materialization，会使原 check 不再绑定最新 materialization，原本可能 ready 的分区会变成 not ready。

因此，本专项的硬规则是：

```text
只要目标 (asset_key, partition_key) 已存在任意 check execution，
即使没有 materialization，也不得自动补 materialization。
```

这类记录归为 `check_without_materialization` 异常，由后续专项单独判断其历史 event 是否本来就不完整；本轮绝不“顺手修好”。

### 3.2 不能用 catalog 的 path_template 直接扫目录

`LakeAssetCatalogEntry.path_template` 是治理和 UI 契约，不是可执行的文件发现器。不同 asset 的物理布局包括：单日单文件、频率加日期、多文件的股票年度布局，以及无 Lake 文件的 serving table。直接把模板拼成 glob 会把错误路径、临时目录或不属于分区的文件混入候选。

结论：实现必须维护显式的物理路径注册表。当前实现由 `FAMILY_ASSET_KEYS` 和 `SIMPLE_PATTERNS` 固化可补录资产、family 顺序和目录发现规则；每个候选再保存精确 required paths、canonical URI 与文件 fingerprint。运行时统一执行最小物理合同验证和最近热窗口排除。

catalog 只作为交叉校验：资产仍 active、partition model/layout 允许、asset key 和 blocking check 名称仍一致。

### 3.3 “UI 完整”不能变成“生产门禁变绿”

当前活跃 sensor 中有一部分会读 `materialized_partition_keys(...)` 进行连续性或缺口判断；另一些则读 latest materialization + checks 的 readiness。恢复历史 materialization 会让前一类历史分区不再被当成“未生产”，这是本专项的目标；但不允许让后一类在无 check 的情况下 ready。

实现和测试必须固定下面结果：

| 物理文件 | materialization | blocking check | 恢复后 UI | 恢复后 readiness |
| --- | --- | --- | --- | --- |
| 有且最小合同通过 | 无 | 无 | materialized | not ready |
| 有且最小合同通过 | 有 | 任意 | 不写，保持原状 | 保持原状 |
| 有且最小合同通过 | 无 | 有 | 不写，列异常 | 保持原状 |
| 无、空或不可读 | 无 | 无 | 不写 | not ready |

## 4. 范围与排除清单

### 4.1 候选资产

P0 只读 profiling 从 `list_lake_asset_catalog_entries()` 和当前 active asset 定义交叉得到候选。只有同时满足下列条件才进入候选 registry：

1. catalog entry 不在 `CONTRACT_ONLY_CATALOG_ASSET_KEYS`；
2. asset 仍在 `ACTIVE_ASSETS_BY_KEY`；
3. `path_template` 非空；
4. partition physical layout 为 `SINGLE_FILE`、`PARTITION_FILE` 或经专门 validator 支持的 `STOCK_YEAR_FILE`；
5. asset 是按 partition 产生 Lake 文件的资产，且能从真实文件反推唯一 partition key；P4 明确列出的股票-年份分钟金层除外，它以此前已通过的正式 check 作为历史物理事实依据，只恢复被清理的 Dagster materialization 状态；
6. 该 partition key 已存在于该 asset 当前的 Dagster partition set；
7. 未被专门排除为 current/hot window、repair/status-only 或多 writer 资产。

`SINGLE_FILE` 和 `PARTITION_FILE` 不代表自动加入；仍必须有显式 spec。`STOCK_YEAR_FILE` 默认不进入通用扫描器。P4 是唯一例外：它不从股票年文件反推日期，也不重新做物理或业务核验，而是按照已确认的历史生产成功事实恢复被删除的 UI 状态；其控制面门禁与写入边界见第 9 节。

### 4.2 永久排除

本专项永久不处理：

- `SERVING_TABLE`、`POSTGRES_TABLE` 和其它远程 serving 资产；
- `NO_DATA_FILE`、`lake_root_health` 及没有物理 Lake 输出的资产；
- contract-only catalog entry、P7 已退出资产；
- `raw_index_daily` 旧 by-code 路径与任何 quarantine 路径；
- 未能建立“分区 -> 精确文件集合”映射的 asset；
- 单纯状态或 repair completion asset，除非未来单独设计。

### 4.3 热窗口排除

每个 eligible spec 都有 `hot_window_size=20`。P0 从该 spec 已发现的有效物理分区中取最新 20 个分区，全部列为 `hot_window_excluded`，不进入本专项 apply。

这让正在日更、重跑或 repair 的近期分区继续由正式 job/check 产生状态，避免历史 UI 修复干扰当前 sensor 或 latest-materialization 语义。这个窗口按 asset 自身的分区集合计算，不假设所有资产同一天开始或同一交易日历。

## 5. 分区分类与 fail-closed 规则

每个 `(asset_key, partition_key)` 必须且只能落入一个分类：

| 分类 | 物理文件 | 既有 materialization | 既有 check | 行为 |
| --- | --- | --- | --- | --- |
| `already_materialized` | 不要求重新验证 | 有 | 任意 | 跳过 |
| `safe_candidate` | 全部存在、非空、Parquet footer 可读、身份一致 | 无 | 无 | 可计划补 1 条 materialization |
| `check_without_materialization` | 可用或不可用 | 无 | 有 | 异常，禁止写 |
| `unregistered_physical_partition` | 可用或不可用 | 无 | 任意 | 异常，禁止写 |
| `missing_or_invalid_physical_file` | 缺失、0 byte、非 regular file、footer 不可读或分区身份不符 | 无 | 无 | 异常，禁止写 |
| `hot_window_excluded` | 任意 | 任意 | 任意 | 不写，留给日常链路 |
| `unsupported_or_ambiguous` | 无法精确枚举或映射 | 任意 | 任意 | 异常，禁止写 |

P0 输出每类的 asset、分区数、起止日期、最多 20 条样本和排序 hash。报告不得装入完整文件列表，完整 manifest 另存为 JSONL，主报告只保留其路径和 sha256。

## 6. 实现落点

本专项只新增离线 bootstrap 工具，不注册 asset、check、job、sensor 或 resource。

```text
lake_console/orchestrator/src/orchestrator/defs/bootstrap/
  historical_materialization_reconciliation.py
  historical_materialization_reconciliation_cli.py

lake_console/orchestrator/tests/
  test_historical_materialization_reconciliation.py
```

### 6.1 核心模型

```python
@dataclass(frozen=True, slots=True)
class PhysicalPartition:
    partition_key: str
    required_paths: tuple[Path, ...]
    canonical_uri: str

@dataclass(frozen=True, slots=True)
class ReconciliationCandidate:
    asset_key: str
    partition_key: str
    physical_fingerprint: str
    canonical_uri: str
    file_count: int
```

`ReconciliationCandidate` 只来自 `safe_candidate` manifest。物理验证只检查文件集合完整、非空、Parquet footer 可读、目录分区与 partition key 一致；它不运行正式 asset check SQL，不计算 coverage、数值域、公式或业务质量。

### 6.2 只读 plan

CLI 固定阶段：

```text
plan      # 默认；读取 definitions/catalog、Lake 文件和 Dagster 状态，零写入
apply     # 必须 --apply --plan-report <fresh plan>，只写 materialization
audit     # 只读；比较计划与实际 event/state 差异
```

`plan` 的输入：

1. 当前 catalog 与 active asset definitions；
2. spec 枚举到的 Lake 文件；
3. `instance.get_materialized_partitions(asset_key)`；
4. 从每个 active asset 的 `partitions_def.get_partition_keys(dynamic_partitions_store=instance)` 读取当前注册 partition set；
5. 仅对“无 materialization 的已注册物理候选”批量读取 check existence 的 Dagster 只读状态；
6. 当前 active run 摘要，仅用于标记冲突而不主动停止任何 run。

为避免逐分区深扫 Dagster event history：

- materialization 按 asset 一次读取 partition set；
- check existence 用只读、按 asset/check/partition 范围聚合的查询或等价批量 API；
- Lake 文件按 spec 以目录发现和 Parquet footer 读取完成，不读取业务列、不扫描行；
- 任何超过 100 个分区的检查按 250 个 partition key 分块；不进入 sensor 热路径。

plan 在 `/private/tmp/dagster_historical_materialization_reconciliation_plan_<timestamp>.json` 写主报告，另写 `<timestamp>.jsonl` 候选 manifest。两份文件都包含同一个 `plan_fingerprint`：由 schema version、catalog asset key、分区 key、所需相对路径、file size、mtime_ns、物理验证结果排序后 SHA-256 得到。它不是数据内容 hash；目的只是阻止“计划后文件集合已变化”仍继续 apply。

### 6.3 apply

`apply` 的前置条件：

1. 调用方显式传入新鲜 plan report；报告 `should_stop=false`；
2. 只选 `safe_candidate`。本专项按 A -> B -> C -> D -> E 连续执行全量已批准候选；每个内部 API 提交块不超过 **500** 条 materialization，它只是失败定位与可恢复边界，不是 sample 或逐块审批；
3. 当前 definitions/catalog 与 plan 中的 eligible spec fingerprint 一致；
4. 重新验证本 batch 的 physical fingerprint、既有 materialization 和 check existence；
5. selected asset 没有 active run 触及同一 asset partition；发现冲突则整个 batch 停止；
6. batch 内没有 hot-window partition、unsupported asset 或候选外 key。

写入只允许这一种 API：

```python
instance.report_runless_asset_event(
    dg.AssetMaterialization(
        asset_key=candidate.asset_key,
        partition=candidate.partition_key,
        metadata=...,
    )
)
```

禁止：

- 直接 `INSERT/UPDATE/DELETE` Dagster PostgreSQL；
- `AssetCheckEvaluation`、job、backfill、sensor、materialize 或 dynamic partition 请求；
- Lake/prod/ClickHouse 写入；
- 因 apply 失败而现场删除已写入 event。

apply 是逐 event API 写入，不能承诺跨 500 条的数据库事务。发生异常时停止，不重试当前 batch；重新 `plan` 后，已成功写入的 key 会自然归入 `already_materialized`，其余仍是候选，具备幂等恢复能力。

### 6.4 最小 metadata

每条补录 event 只写以下 metadata，避免再次制造大 payload：

| key | 值 |
| --- | --- |
| `dagster/uri` | spec 的 canonical URI |
| `goldenshare/reconciliation_method` | `historical_lake_partition_materialization_v1` |
| `goldenshare/reconciliation_batch_id` | 本次 apply UUID |
| `goldenshare/reconciliation_file_count` | 必需文件数 |
| `goldenshare/reconciliation_plan_fingerprint` | plan fingerprint |
| `goldenshare/check_events_reported` | `false` |

不得写 row samples、全量路径、schema 明细、SQL、业务行数、完整 check 报告或冗余 asset contract。完整诊断只存在 `/private/tmp` plan/audit 报告中。

## 7. 事件量、性能与存储门禁

本专项的成本是每个 safe candidate 增加一条 materialization event；没有 check event。实际总数在 P0 前不能猜。

| 指标 | P0 必须输出 | apply 门禁 |
| --- | --- | --- |
| eligible asset 数 | 按 physical layout/asset family 分类 | 未知 asset 不可 apply |
| discovered physical partition 数 | 每 asset、起止分区、hash | 无法唯一映射则 stop |
| safe candidate 数 | 每 asset/asset family | 只写该集合 |
| check-without-materialization 数 | 每 asset、样本 | 大于 0 的 key 全部排除 |
| 每条 metadata 序列化大小 | p50/p95/max | max 不得超过 1 KiB |
| 单 apply batch | event 数、耗时、失败数 | 最大 500 条 |
| 总 event 预算 | P0 的总候选数、预估 event-log bytes | 本轮已批准 A-E 的当前全部 `safe_candidate`；`STOCK_YEAR_FILE` 只能按第 9 节专项另行冻结 |
| Lake 读取 | 文件/目录数、footer 读取数、业务行扫描数 | A-E 与 P4 均不得读取 Lake；P4 只读取 Dagster 控制面状态 |

P0 后必须按 asset family 给出总 event 数和基于本机实际序列化 metadata 的字节估算。本轮已由管理员明确批准 A-E 全量直接执行；500 条仅是 API 内部失败定位边界，不是 sample 或额外审批边界。

## 8. 运行阶段

### P0：只读 inventory（需单独批准）

输出 plan 和 manifest，冻结真实资产范围、文件数、候选数、异常数、预计 event 量、磁盘读取量与统计耗时。P0 不写 Dagster DB、不写 Lake。

P0 接受条件：

- 每个候选都有明确 spec、唯一 partition key 和精确 required paths；
- 所有 `safe_candidate` 都无 materialization、无 check、且不在各自最新 20 分区；
- 所有 `safe_candidate` 都已在对应 asset 当前 Dagster partition set 中注册；
- 所有排除理由有可读样本；
- 报告能给出每个 asset family 的总 event 预算。

#### P0 执行结果（2026-07-15，已完成）

本次执行只读取当前 definitions/catalog、本机 Dagster instance、只读 PostgreSQL 聚合和 Lake Parquet footer；没有读取业务行、没有写 Dagster DB、Lake、prod、event、check、run 或 dynamic partition。

报告：

```text
/private/tmp/dagster_historical_materialization_reconciliation_plan_20260715_182010.json
/private/tmp/dagster_historical_materialization_reconciliation_candidates_20260715_182010.jsonl
```

主报告的 `plan_fingerprint` 为：

```text
9105f19b9f483b300649ac765de49ecf8b5d58599267967fcb16fa2aa6e71781
```

候选 manifest 有 79,037 行，SHA-256 为：

```text
829e73ebe6c3ff5ee682cd7badf5907b2c3fa11bec679bb3059088757f23a64c
```

冻结结果：

| 项目 | 结果 |
| --- | ---: |
| active asset spec / catalog entry | 67 / 67，完全对齐 |
| active trade-date asset | 53 |
| 已支持的单日单文件 asset | 32 |
| 可安全补录 materialization | 79,037 |
| 已 materialized，跳过 | 32,002 |
| 最新 20 分区排除 | 640 |
| 有 check 但无 materialization，排除 | 7 |
| 有物理文件但未注册，排除 | 351 |
| 股票-年份文件，暂不映射到日期分区 | 14 个 asset、740,046 个物理文件 |
| 计划 check event | 0 |
| metadata payload p50 / p95 / max | 473 / 494 / 495 bytes |
| metadata payload 总量 | 37,744,653 bytes，仅 metadata，不含 Dagster event envelope/index |
| P0 耗时 | 48,095.41 ms |

当前没有 `QUEUED`、`STARTING`、`STARTED` 或 `CANCELING` run；P0 的结构性 `should_stop=false`。这只表示计划可被后续阶段消费，**不表示可以直接 apply**。

需要明确保留的异常：

1. 7 个 `check_without_materialization` 都是七个 `gold_stk_mins_qfq_macd_kdj_state_*` asset 在 `2014-01-02` 的历史 check；本专项不会为它们追加 materialization，以免破坏原 check 身份。
2. `raw_index_daily` 有 351 个物理目录不在当前 `cn_a_index_trade_days` 注册集合中。样本包括 2005 年春节、五一、国庆等非当前指数交易日；它们不满足分区注册门槛，不能写 event。
3. 14 个 `STOCK_YEAR_FILE` asset 虽有 740,046 个物理文件，但一个文件覆盖多个交易日。通用 P0 不读取文件内业务列，因此将其全部标为 `unsupported_or_ambiguous`；它们不在 A-E 候选 manifest 中。第 9 节的 P4 不再从文件建立日期映射，而是以此前已通过的生产 check 为可信历史依据，仅通过 Dagster 控制面冻结可恢复的 materialization；P4B 获批前仍不允许写 event。

候选按 asset family 的 event 预算：

| asset family | safe candidate |
| --- | ---: |
| `stock_mins` | 36,155 |
| `stock_mins_qfq_macd_kdj_state` | 21,063 |
| `index_daily` | 6,393 |
| `market_major_indices_daily` | 6,393 |
| `market_breadth` | 3,011 |
| `stock_return_distribution` | 3,011 |
| `wealth_market_turnover` | 3,011 |

结论：P0 通过。随后已完成 P1 的离线工具与 ephemeral-instance 测试、完整 Dagster PostgreSQL 备份，以及 A -> B -> C -> D -> E 的全部 `safe_candidate` 写入。本轮没有 50 条 sample 阶段；每 500 条始终只是内部 API 写入与失败定位边界。

### P1：本地实现与测试（已完成，无需正式 instance）

已实现离线模块、CLI 和 tests。专项测试覆盖候选范围、manifest SHA、防重复、物理 fingerprint 漂移、已有 check、未注册分区、热窗口、部分失败续跑，以及“materialized 但缺 blocking check 仍 not ready”。测试使用临时 Lake 目录和 ephemeral Dagster instance，不访问正式 Lake、正式 DB 或正式 instance。

### P2：完整 DB 备份与 A-E 直接 apply（已完成）

已在新鲜 P0 plan 全绿后，先对 `goldenshare_dagster` 做完整逻辑备份并完整读取校验归档，再按 A -> B -> C -> D -> E 连续写入全部 79,037 个 `safe_candidate`。未暂停 sensor；每个 asset 的最新 20 个物理分区保持排除。

备份使用本机兼容的 custom + `gzip:6` 归档（本机 `pg_dump` 不支持 ZSTD），并通过 `pg_restore --list` 与完整只读恢复流校验：

```text
/Users/congming/.goldenshare/dagster_backups/historical_materialization_reconciliation_20260715_182158/
```

源数据库为 16,050,919,103 bytes；归档为 395,996,639 bytes；SHA-256 为：

```text
0a98fc547ae225162ebd83fbb2f635d00ec8dcddb54efa6a863375ad4ad8a1e4
```

apply 使用 P0 plan fingerprint `9105f19b9f483b300649ac765de49ecf8b5d58599267967fcb16fa2aa6e71781`，batch id 为 `11ec9d58-fc78-4a1d-81d2-447153358b10`，实际耗时 2,275,375.15 ms。每 500 条 event 为一个内部提交块，family 结果如下：

| family | 实际 materialization | 内部块数 |
| --- | ---: | ---: |
| A | 15,426 | 31 |
| B | 6,393 | 13 |
| C | 21,105 | 43 |
| D | 15,050 | 31 |
| E | 21,063 | 43 |
| 合计 | **79,037** | **161** |

apply 报告：

```text
/private/tmp/dagster_historical_materialization_reconciliation_apply_20260715_190149.json
```

### P3：最终只读审计与文档收口（已完成）

最终 audit 确认 79,037 个候选全部 materialized，缺失样本为空。batch id 精确对应 79,037 条 `ASSET_MATERIALIZATION`，没有 check event；`asset_check_executions`、check event、`runs`、`run_tags`、`asset_event_tags` 与 dynamic partitions 的计数均与 apply 前一致。Lake 未被本专项写入。

```text
/private/tmp/dagster_historical_materialization_reconciliation_audit_20260715_190213.json
/private/tmp/dagster_historical_materialization_reconciliation_plan_20260715_190326.json
```

最后 fresh plan 的 `safe_candidate=0`、`planned_check_event_count=0`、`should_stop=false`。仍按设计保留：7 个 check-only MACD/KDJ state 分区、351 个未注册 `raw_index_daily` 物理目录；两类都没有补录。14 个按股票年保存的 asset 已在第 9 节通过 P4 可信历史状态恢复补齐其安全历史 materialization。

## 9. P4：股票-年份分钟金层可信历史状态恢复（已完成）

### 9.0 P4S：静态性能基线（2026-07-15，已完成）

在提出任何 DuckDB 读取方案前，已只读执行文件系统静态测算：只使用 `find`、`du` 和路径层级统计；没有调用 `read_parquet`、DuckDB、Dagster instance、job、sensor 或任何写入。

| 范围 | 文件数 | 目录占用 | 若重扫时的用途 |
| --- | ---: | ---: | --- |
| QFQ target，7 个频度 | 370,023 | 78.85 GiB | 日期身份反推 |
| MACD/KDJ indicator target，7 个频度 | 370,023 | 191.03 GiB | 日期身份反推 |
| native QFQ Silver 输入，5 个频度 | 15,225 | 57.31 GiB | source 覆盖复验 |
| `silver_adj_factor` 输入 | 4,256 | 0.13 GiB | factor 覆盖复验 |
| derived QFQ source，30m + 60m | 105,731 | 5.87 GiB | derived 覆盖复验 |
| indicator 的 QFQ source，7 个频度 | 370,023 | 78.85 GiB | indicator 覆盖复验 |

静态事实：

- 14 个 target asset 共跨 2014 至 2026 的 13 个自然年，即 **182 个 `asset/freq/year` shard**。
- 单个 target shard 最多有 **5,540** 个股票年文件；2026 年虽未结束，按股票建年文件后已经达到该规模。
- target 唯一物理文件数为 740,046，约 269.88 GiB。
- 若按原“再做一次 source-target identity 复验”的思路执行，逻辑上会打开约 **1,235,281** 个文件、覆盖约 **412.04 GiB** 目录数据；若 apply 前再重验一次，规模会翻倍到约 **2,470,562** 次文件访问、**824.09 GiB** 数据覆盖。

**设计结论：禁止为本次状态恢复重新扫描 Lake、打开 Parquet 或运行 DuckDB。** 这些历史数据此前已经通过相应 production check 并留下成功日志；现在缺失的是为缩小 Dagster PostgreSQL 而删除的 materialization/check 历史，而不是文件事实或计算结果。本专项只恢复前者中的 materialization UI 状态，绝不重新证明已经被正式链路证明过的数据。

### 9.1 为什么仍需独立专项

上一轮 A-E 资产的物理路径可直接反推交易日，例如 `trade_date=2026-07-14/part-000.parquet`。剩余 QFQ 与 MACD/KDJ 分钟金层的布局不同：

```text
gold/quote/stk_mins_qfq/freq=<freq>/ts_code=<code>/year=<YYYY>/part-000.parquet
gold/indicator/stk_mins_qfq_macd_kdj/freq=<freq>/ts_code=<code>/year=<YYYY>/part-000.parquet
```

单个股票年文件包含多个交易日，通用 A-E 单日文件工具无法从路径安全地列出日期。此前的方案想再次读取文件内身份列来建立日期映射；P4S 已证明这会把“恢复已删除状态”错误地做成一次大规模 Lake 重验。

P4 的新口径更直接：

> 历史数据的可靠性由此前成功的生产 job 和 blocking check 负责；P4 只补回清理时被删除的 `AssetMaterialization`。现在唯一需要重新核验的是 Dagster 控制面，避免重复写、破坏 check 绑定或碰到正在运行的生产任务。

### 9.2 范围与可信输入

P4 只处理 14 个当前 active、按股票年存储、但 Dagster 分区仍是交易日的 asset：

| 子族 | asset | 频度 | 数量 |
| --- | --- | --- | ---: |
| QFQ native | `gold_stk_mins_qfq_<freq>m` | 1/5/15/30/60 | 5 |
| QFQ derived | `gold_stk_mins_qfq_<freq>m` | 90/120 | 2 |
| MACD/KDJ indicator | `gold_stk_mins_qfq_macd_kdj_<freq>m` | 1/5/15/30/60/90/120 | 7 |

历史候选的唯一业务输入是当前 `cn_a_stock_mins_silver_trade_days` 已注册集合中、不早于生产常量 `STK_MINS_QFQ_HISTORY_START_DATE` 的交易日。实现必须导入该常量，不得硬编码日期、总分区数或 event 数。

可信依据与控制面读取如下：

1. 管理员已确认：这些待补历史分区此前已完成对应 production check，后来因 Dagster PostgreSQL 清理而失去历史 event；P4 不把它们当成待验证的数据。
2. `DagsterInstance.get_dynamic_partitions(...)` 只读当前九转无关的分钟 Silver 交易日注册集合。
3. `DagsterInstance.get_materialized_partitions(AssetKey(...))` 只读每个目标 asset 的现有 materialization，防止重复写。
4. `asset_check_executions` 的只读查询用于区分会保护现状的 check 与历史 repair completion 标记；普通 check、失败 check 或绑定 materialization 的 check 必须排除，不能被本专项改写其 readiness 身份。
5. `runs` 的只读查询只用于发现活跃 Dagster run；任何活跃 run 都阻止后续 apply。

以下对象不进入 P4：

- 7 个 `gold_stk_mins_qfq_macd_kdj_state_<freq>m`，它们已在 A-E 处理；`2014-01-02` 的 check-only 异常维持不动。
- Raw/Silver 分钟线，它们已在 C/D 处理。
- 任何历史 QFQ/indicator check、baseline event、repair completion event、run、cursor 或 dynamic partition。
- `stk_mins_qfq_history.py`、`stk_mins_qfq_macd_kdj_history.py` 和既有 baseline-event 工具；它们会生成数据或报告 check，不符合本专项边界。
- Lake 文件、Parquet schema、行数、身份列、QFQ 公式、MACD/KDJ 公式，以及任何生产 check 的重新执行。

### 9.3 候选分类与 fail-closed 规则

对每一个 `(asset_key, partition_key)`，P4 只按控制面事实分类：

| 分类 | 条件 | 动作 |
| --- | --- | --- |
| `safe_candidate` | 已注册、在历史起点之后、非最新 20 个已注册日期、没有 materialization、没有保护性 check、无活跃 run | 仅在后续获批后补一条 materialization |
| `already_materialized` | 已有 materialization | 跳过 |
| `unbound_repair_completion_marker_only` | 仅七个 indicator asset；该分区所有 check 都是 `gold_stk_mins_qfq_macd_kdj_repair_completed_check`、`SUCCEEDED` 且 `materialization_event_storage_id IS NULL` | 允许作为 `safe_candidate`；保留原 check，不写新 check |
| `check_without_materialization` | 没有 materialization，且存在普通 check、失败 check、绑定 materialization 的 check，或不满足上述精确例外的任意 check | 跳过并报告；绝不补 materialization |
| `hot_window_excluded` | 属于注册集合最新 20 个日期 | 跳过；把近期生产状态完全留给正常 job/sensor |
| `before_history_start` | 早于 `STK_MINS_QFQ_HISTORY_START_DATE` | 不属于 P4 候选 |
| `active_run_blocked` | Dagster instance 存在 `QUEUED/STARTING/STARTED/CANCELING` run | 整个 plan 标记 `should_stop=true`，不得进入 apply |
| `invalid_partition_key` | 注册 key 不是 ISO 日期，或无法稳定排序 | `should_stop=true`，不得进入 apply |

`check_without_materialization` 必须排除。向这种分区追加 materialization 会使原 check 不再绑定最新 materialization，反而可能让原本可用的状态变为 not ready。唯一例外是 P4C 识别的旧 repair completion 标记：它本来就是 repair 状态记录，不绑定 materialization，也不是指标分区的 blocking data check。该例外只覆盖七个非 state 指标 asset 的精确 check 名、成功状态和空绑定三项同时成立；一条普通、失败或绑定 check 即恢复 fail-closed。P4 仍只补 materialization、不补 check，因此 P4 写入后的历史分区在 readiness 语义中仍是 **not ready**；这正是本专项的安全边界。

### 9.4 P4A：正式 instance 只读 Plan（已完成）

P4A 是 P4 的初始只读冻结阶段。首次临时计划器位于 `/private/tmp`，不注册 asset/check/job/sensor，也没有 `--apply` 参数。P4B 实现后，同一只读 plan 逻辑被纳入离线 bootstrap 模块 `defs/bootstrap/stk_mins_stock_year_materialization_reconciliation.py`；该模块不进入 active definitions，不注册 asset/check/job/sensor。

它只读取：

- 一个动态分区集合；
- 14 个 asset 的 materialized partition 集合；
- `asset_check_executions` 中这 14 个 asset 的分区、check 名、执行状态和 materialization 绑定关系；
- `runs` 的状态聚合。

它明确不读取：

- `/Volumes/datasource` 下任何路径；
- Parquet、DuckDB、Lake root、QFQ/MACD-KDJ writer 或 production check；
- source、prod、ClickHouse、run log、cursor、event payload 或 dynamic partition 写接口。

P4A 输出聚合报告和仅含 `(asset_key, partition_key)` 的候选 manifest：

```text
/private/tmp/dagster_historical_materialization_reconciliation_stock_year_trusted_plan_<timestamp>.json
/private/tmp/dagster_historical_materialization_reconciliation_stock_year_trusted_candidates_<timestamp>.jsonl
```

报告必须包含：

- 固定 14 个 asset key、历史起点、注册日期集合的 count/min/max/sorted hash；
- 每个 asset 的 `already_materialized`、`check_without_materialization`、`unbound_repair_completion_marker_only`、`hot_window_excluded`、`safe_candidate` 数量及首尾日期/有限样本；
- 全部 safe candidate 的 count 与 `asset_key + partition_key` 排序 hash，不把完整候选清单塞入 cursor 或 Dagster metadata；
- active run 状态聚合、`should_stop` 和具体 stop reason；
- 基于“注册集合、materialization 集合、check 身份/状态/绑定集合、热窗口集合”的 plan fingerprint；
- 读取耗时；进程峰值内存和报告字节数如需留档，由外部只读审计记录，不作为 plan JSON 的强制字段。

2026-07-15 的正式 instance 只读执行结果：

| 项目 | 实际结果 |
| --- | --- |
| 注册分钟 Silver 交易日 | 3,046 个，`2014-01-02` 至 `2026-07-15` |
| 无效或历史起点前注册 key | 0 / 0 |
| 热窗口 | 20 个，`2026-06-17` 至 `2026-07-15` |
| active run | 0，`should_stop=false` |
| 7 个 QFQ asset | 每个 35 个已有 materialization、1 个热窗口排除、3,010 个 safe candidate |
| 7 个 indicator asset | 每个 35 个已有 materialization、1 个 `2014-01-02` check-only、1 个热窗口排除、3,009 个 safe candidate |
| 总候选 materialization | **42,133** 条 |

报告和候选清单：

```text
/private/tmp/dagster_historical_materialization_reconciliation_stock_year_trusted_plan_20260715_212122.json
/private/tmp/dagster_historical_materialization_reconciliation_stock_year_trusted_candidates_20260715_212122.jsonl
```

本次 plan fingerprint 为 `08b854ce275a342998ce4c1f07ff3128dc279224c08fa053da8b15bbf2957b34`，候选 manifest hash 为 `10dcf7a1b8ccff26dc83973183426ad4bc71f5fd8a601c143383c7b591310fbb`。计划耗时 791.38 ms、进程峰值内存约 192 MiB；没有读取 Lake、DuckDB 或 Parquet。它不是 Lake 完整性证明，也不取代历史 check；其目的只是冻结“现在能够安全追加哪几条 UI 状态”。P4B apply 前按规则重新生成了新鲜 plan，并以该新鲜 plan 为唯一写入基线，见第 9.6.1 节。

### 9.5 性能与数据量边界

P4 的性能模型只处理 Dagster PostgreSQL/instance 的小型状态集合，不处理分钟数据文件：

| 读取 | 次数 | 规模上界 | 禁止项 |
| --- | ---: | --- | --- |
| 动态分区集合 | 1 | 当前注册分钟 Silver 交易日数 | 不扫 Lake |
| materialized partition 集合 | 14 | 每 asset 至多一个日期集合 | 不读 event payload |
| check 状态集合 | 1 个聚合查询 | 14 asset 的分区、check 名、状态和绑定 ID | 不读 check metadata 或 event payload |
| run 状态 | 1 个聚合查询 | 状态行数很小 | 不读 run log |
| 候选计算 | 内存 set 差集 | 14 × 注册日期数 | 不建文件/代码级映射 |

这比已否决的 Lake 身份重扫少掉约 1,235,281 次文件访问和 412.04 GiB 目录数据覆盖。计划输出只有聚合统计、有限样本和集合 hash；即使未来需要生成完整候选清单，也只能写 `/private/tmp` 的紧凑 JSONL，不得写入 Dagster cursor 或 event metadata。

### 9.6 P4B：获批后的直接状态恢复（已完成）

P4B 已按以下规则实现为离线 bootstrap 工具；它先做一份新的完整 Dagster PostgreSQL 逻辑备份，不能复用 A-E 旧备份。备份以 `pg_dump --format=custom --create --compress=gzip:3` 生成，并用 `pg_restore --list` 和完整读取校验归档。2026-07-15 已确认本机 `pg_dump 18.3` 未编译 ZSTD 支持，故本专项使用受支持的 `gzip:3`，不因压缩格式差异降低备份、校验或恢复边界。

P4B 的 apply 规则：

1. 只对 P4A fingerprint 一致的 `safe_candidate` 追加 `DagsterInstance.report_runless_asset_event(AssetMaterialization(...))`。
2. 每 500 条为内部提交边界；每个边界前重新读取注册/materialization/check/active-run 控制面事实。任何变化都停止当前及后续批次，不现场删除已写 event。
3. 每条 event 仅写 `dagster/uri`、恢复方法、batch id、plan fingerprint 与 `check_events_reported=false` 等最小 metadata；不写代码列表、文件路径列表、样本行或 check metadata。
4. 不写 check event、Lake、prod、ClickHouse、dynamic partitions；不运行 job、sensor、materialize、backfill。
5. apply 后只读审计必须证明：目标候选都 materialized，check/run/run-tag/dynamic-partition/Lake 均没有本专项写入；历史分区在 UI 可见，但 readiness 仍未因本专项变绿。

#### 9.6.1 实际执行记录（2026-07-15）

P4B 使用 apply 前新鲜生成的控制面 plan，而不是复用较早的 P4A 报告。该计划仍为 14 个白名单 asset、42,133 个候选、0 个活跃 run、`should_stop=false`；apply 前后均未读取 Lake 或业务数据文件。

```text
plan:
/private/tmp/dagster_historical_materialization_reconciliation_stock_year_trusted_plan_20260715_213135.json

candidate manifest:
/private/tmp/dagster_historical_materialization_reconciliation_stock_year_trusted_candidates_20260715_213135.jsonl

plan fingerprint:
0c7da770a34ed4aa5657d6053c2dac337b610ec715dfbcf861c1683e8818bf0b

backup manifest:
/Users/congming/.goldenshare/dagster_backups/historical_materialization_reconciliation_stock_year_20260715_213753/manifest.json

backup archive:
/Users/congming/.goldenshare/dagster_backups/historical_materialization_reconciliation_stock_year_20260715_213753/goldenshare_dagster.dump

apply report:
/private/tmp/dagster_historical_materialization_reconciliation_stock_year_trusted_apply_20260715_214819.json

post-audit report:
/private/tmp/dagster_historical_materialization_reconciliation_stock_year_trusted_audit_20260715_214825.json

fresh post-plan:
/private/tmp/dagster_historical_materialization_reconciliation_stock_year_trusted_plan_20260715_214855.json
```

完整 Dagster PostgreSQL 逻辑备份使用 custom + `gzip:3`：源数据库为 16,051,443,391 bytes，归档为 565,727,829 bytes，归档 SHA-256 为 `c1554891a9f9483e66d2db0e4aea85e01879fda2ac7caf0d3b31ba02c6a02e6f`。`pg_restore --list` 与完整读取校验均通过。

apply 以 500 条为内部失败边界，共 85 个提交块，实际追加 `42,133` 条 `AssetMaterialization`，耗时 554,276.78 ms。每个提交块前均重读注册分区、热窗口、已有 materialization、已有 check 和 active run；没有发生漂移或中断。

post-audit 结论：

1. `all_selected_candidates_materialized=true`，14 个 asset 均无缺失候选。
2. 新鲜 plan 的 `planned_materialization_event_count=0`、`should_stop=false`、active run 为空；没有待补历史候选。
3. 在 P4B 当时，7 个 QFQ asset 各有 3,045 个历史 materialization；7 个 indicator asset 各有 3,044 个 materialization，且各自保留 `2014-01-02` 的一个 check-only 分区。该过宽的“任意 check 都排除”分类在后续 P4C 中已精确纠正，见第 9.6.2 节。最新热窗口仍完全由正常生产链路负责。
4. 下列非 materialization 控制面计数在 apply 前后严格一致：`asset_check_event_logs=701,643`、`asset_check_executions=422,221`、`asset_event_tags=28,377`、`dynamic_partitions=31,458`、`run_tags=320,868`、`runs=47,146`。
5. 对 `2014-01-02` 的正式 instance 只读验证显示：五个 native QFQ asset 都已 materialized，但各自四个 blocking check 都缺失，整体 readiness 仍为 `false`。因此，本次补录只恢复 UI/backfill 的 materialized 可见性，没有把历史分区误标为当前可消费状态。

#### 9.6.2 P4C：旧 repair completion 标记的精确纠正（已完成）

P4B 后发现七个 `gold_stk_mins_qfq_macd_kdj_<freq>m` indicator asset 的 `2014-01-02` 没有 materialization。根因不是缺 Lake 文件或缺计算，而是 P4B 的初版分类把“有任意 check”一概归入 `check_without_materialization`。实际控制面事实是：每个 asset 有 25 条历史 `gold_stk_mins_qfq_macd_kdj_repair_completed_check`，全部 `SUCCEEDED`，全部 `materialization_event_storage_id IS NULL`，没有其它 check；它们是 repair completion 状态，不是绑定到指标 materialization 的数据检查。

P4C 将离线工具的 plan schema 升为 `2`，使旧 schema `1` plan 不能在新规则下 apply。唯一新增例外严格限制为：七个 indicator asset、精确 repair completion check 名、`SUCCEEDED`、未绑定 materialization；任何普通 check、失败 check、绑定 check、state asset 或范围外 asset 均继续保护并拒绝写入。工具不进入 active definitions，不改计算、Lake、check、job、sensor、动态分区或 readiness 实现。

本次只读 plan 精确得到 7 条候选，全部为 `2014-01-02`：

```text
plan:
/private/tmp/dagster_historical_materialization_reconciliation_stock_year_trusted_plan_20260715_221023.json

candidate manifest:
/private/tmp/dagster_historical_materialization_reconciliation_stock_year_trusted_candidates_20260715_221023.jsonl

plan fingerprint:
4bc64591df9edecc3bfef73086af786a93730f9564e6ab8954f0d5009e3c1f0f

backup manifest:
/Users/congming/.goldenshare/dagster_backups/historical_materialization_reconciliation_stock_year_p4c_20260715_221023/manifest.json

backup archive:
/Users/congming/.goldenshare/dagster_backups/historical_materialization_reconciliation_stock_year_p4c_20260715_221023/goldenshare_dagster.dump

apply report:
/private/tmp/dagster_historical_materialization_reconciliation_stock_year_trusted_apply_20260715_221139.json

post-audit report:
/private/tmp/dagster_historical_materialization_reconciliation_stock_year_trusted_audit_20260715_221147.json

fresh post-plan:
/private/tmp/dagster_historical_materialization_reconciliation_stock_year_trusted_plan_20260715_221252.json
```

新的完整 Dagster PostgreSQL 逻辑备份使用 custom + `gzip:3`，源数据库为 16,051,943,103 bytes，归档为 568,625,866 bytes，SHA-256 为 `b9b871160ac0843a94c13c439822041c721c532a00b40ef8583be858c524ba60`；`pg_restore --list` 与完整读取均通过。apply 在一个 7-event 内部块内完成，batch id 为 `0c7a21dc-0251-49a3-aa18-c6e1a45f7266`，耗时 1,727.4 ms。

post-audit 确认：

1. 7 个目标 asset 的 `2014-01-02` 均已有 1 条 materialization；各自 25 条旧 completion check 原样保留，且不存在其它 check。
2. `asset_check_event_logs=701,645`、`asset_check_executions=422,222`、`asset_event_tags=28,378`、`dynamic_partitions=31,458`、`run_tags=320,874`、`runs=47,147` 在 apply 前后严格一致。
3. 新 schema `2` fresh plan 的 `planned_materialization_event_count=0`、`should_stop=false`；七个 asset 都显示 3,045 个 materialization，最早日期已是 `2014-01-02`。
4. 原 completion 标记仍不绑定 materialization，也不参与指标的 blocking readiness；P4C 只恢复 UI/backfill 的 materialized 展示，不会把历史分区标为 ready。

### 9.7 测试、验收和停止条件

P4B 已新增离线测试 `tests/test_stk_mins_stock_year_materialization_reconciliation.py`，并与静态门禁一起执行 89 个 unittest、全部通过。覆盖范围至少包括：

1. 候选只来自注册集合，且严格应用生产常量的历史起点。
2. 14 个 asset 是固定白名单；state、raw、silver 和任何其它 asset 都不能进入。
3. 已 materialized、已有 check、最新 20 个日期、早于历史起点、异常分区键和活跃 run 的分类准确。
4. 计划器与 apply 工具静态禁止导入 DuckDB、Lake root、Parquet reader、QFQ/MACD-KDJ writer/check builder。
5. apply 只能构造 `AssetMaterialization`，不能构造 `AssetCheckEvaluation`，也不能调用 job/sensor/dynamic-partition API。
6. 只有 materialization 的 ephemeral Dagster fixture 必须仍显示 not ready，保护现有 readiness 语义。
7. stale fingerprint、部分写入后的重试和已有 materialization 都必须幂等。

P4C 额外覆盖：只有成功且未绑定的精确 repair completion 标记可进入候选；空字符串形式的 `psql` NULL 必须等价于未绑定；普通 check、绑定 check 和失败 completion 标记均必须继续阻断。P4C 本地专项测试共 12 个用例通过。

P4B 停止条件：

- P4A 发现 active run、非 ISO 注册 key、资产白名单漂移或任何未解释的控制面契约异常；
- P4A 与 apply 前重新读取的注册/materialization/check/热窗口集合 fingerprint 不一致；
- 需要读取 Lake 或重新执行 check 才能决定候选；
- 出现计划外 asset、check、run、Lake、dynamic partition 或数据库表写入；
- 新备份无法完整校验。

### 9.8 对运行链路的影响

P4 不改 asset、check、job、sensor、partition、run key、Lake layout、公式 SQL 或 readiness 实现。QFQ/MACD-KDJ daily 与 repair sensor 仍通过最新 materialization 加 blocking checks 的原有 API 判断 readiness；P4 只写 materialization，不能替代当前生产 check 或 repair。除 P4C 的精确历史 repair completion 例外外，任何已有 check 均继续阻断历史 materialization 恢复。

对历史 UI 和 materialization-based backfill 选择而言，已恢复分区会正常显示为 materialized。对当前日更而言，最新 20 个注册交易日和任何已有 check 的分区始终排除，因此 P4 不会把历史状态误写成当前生产成功，也不会改变自动触发逻辑。
## 10. A-E 通用工具测试设计

新增 `tests/test_historical_materialization_reconciliation.py`，至少覆盖：

1. `plan` 默认 dry-run，绝不调用 `report_runless_asset_event`；
2. 只有 active、Lake-backed、spec 已注册的 asset 可以进入候选；serving/no-file/contract-only asset 被排除；
3. 文件缺失、0 byte、footer 不可读、分区路径不符均不得成为 `safe_candidate`；
4. 已 materialized 分区跳过，且不会写重复 event；
5. 已有任意 check 但无 materialization 的分区被拒绝；
6. 文件存在但目标日期未注册时归为 `unregistered_physical_partition`，不得写 event；
7. 最新 20 个发现分区被排除；
8. plan fingerprint、catalog/spec fingerprint、物理 fingerprint、注册 partition set 或 Dagster state 在 apply 前改变，整个 batch 拒绝；
9. apply 只报告 `AssetMaterialization`，从不构造 `AssetCheckEvaluation`；
10. minimal metadata 小于 1 KiB，且没有路径列表、SQL、rows sample、schema 明细；
11. ephemeral instance 中，写入 materialization 后 `materialized_partition_keys(...)` 包含目标 key，而 `partition_dataset_readiness_status_from_latest_checks(...)` 对有 blocking check spec 仍是 not ready；
12. 失败中断后重新 plan，已写 key 成为 `already_materialized`，未写 key 保持候选；
13. 每个内部 API 写入块不得超过 500 条；A-E 连续执行不得退化为 sample-only 流程，也不得绕过候选重验。

静态门禁补入 `tests/test_run_contract_static_gates.py`：该模块不得 import active sensor/job definitions 以注册行为，不得调用 job/sensor/materialize/backfill API，不得出现 `AssetCheckEvaluation` 或 Dagster DB 写 SQL。

## 11. 影响面审计

不改 active definitions，但 materialization state 被以下两类消费者读取，A-E 的 P0/P1 与 P4 的 P4A/P4B 都必须逐项复核：

1. `materialized_partition_keys(...)` 的调用方：它们会把已恢复的**非热历史物理分区**识别为已 materialized。这是本专项期望的 UI/backfill 改善，不得用于把缺 check 分区判为 ready。
2. `partition_dataset_readiness_status_from_latest_checks(...)` 的调用方：它们必须继续把“只有 materialization、没有绑定 blocking check”的 partition 判为 not ready。

已通过 CodeGraph 审计到的直接重点调用方包括 `stock_daily_sensor.py`、`suspend_d_sensor.py`、QFQ/MACD-KDJ daily 与 repair sensors；P1 在当前代码基线再次生成完整调用方清单，附到 P0 报告，不把历史清单写死在代码中。

不影响：

- asset key、partition definition、catalog entry、path、schema、DuckDB SQL、job selection、sensor cursor、run key；
- Lake 文件和任何生产数据库；
- check 定义、check event、check 绑定、readiness 算法；
- 已存在 materialization、run、run tag、asset event tag、dynamic partition。

## 12. 停止条件与回滚姿态

以下任一情况，停止该 apply batch，不降级处理：

1. P0 出现无法唯一映射、未注册的文件目标分区；
2. candidate 有任何 existing check、existing materialization 或进入热窗口；
3. plan/apply 间 fingerprint 或注册 partition set 变化；
4. target asset/partition 有 active run 冲突；
5. 发现 metadata 超过 1 KiB、候选量超过批准预算，或在 A-E 之外未经第 9 节批准地读取业务列；
6. 任何测试显示缺 check 的 partition 被错误判为 ready；
7. 写入后 audit 发现 check/runs/tags/dynamic partitions/Lake 有非零意外变化。

apply 前可完全停止；apply 中出现失败不做现场删除。原因是 runless event 已提交后，直接删除 event 既高风险又会重演此前 Dagster DB 治理问题。正确恢复方式是停止、重新 plan、记录已成功 key，并以新 plan 继续；若确实要撤销已写 materialization，必须另起精确 event cleanup 方案、备份和审批。

## 13. 代码与文档对账

| 设计要求 | 实现落点 | 验证 |
| --- | --- | --- |
| 仅 materialization | bootstrap module 的唯一报告函数 | 禁止 `AssetCheckEvaluation` 的单测和静态门禁 |
| 不破坏 readiness | candidate classifier + apply recheck | ephemeral instance readiness 测试 |
| 只处理真实 Lake 文件 | spec registry + physical validator | 缺失/空/错误 layout 测试 |
| 控制 Dagster DB 增长 | minimal metadata + 500 batch cap + P0 预算 | metadata 大小、event count、post-audit |
| 不干扰日更 | 每 spec 最新 20 分区排除 + active-run gate | hot-window/active-run 拒绝测试 |
| 可审计可恢复 | plan fingerprint、JSONL manifest、apply/audit report | stale plan 和部分失败幂等测试 |
| 股票年文件不猜日期 | P4 专项以此前已验证历史和 Dagster 控制面状态恢复 UI | 白名单、分区集合、check 保护、热窗口与 active-run 测试 |
| P4 离线状态恢复 | `defs/bootstrap/stk_mins_stock_year_materialization_reconciliation.py` 与 `_cli.py` | P4B apply/post-audit 报告、89 个 unittest |

本文是该专项唯一设计文档。实施后只回写本文的 A-E P0/P2/P3 与 P4S/P4A/P4B 实际报告路径、数量和结论，不再建立平行方案文档。
