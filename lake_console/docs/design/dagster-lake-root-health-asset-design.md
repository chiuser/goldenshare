# Dagster Lake Root Health Asset 设计方案

更新时间：2026-06-06

状态：方案已拍板，代码已落地；正式 schedule 是否启用仍需单独审批。

## 1. 背景

落地前，`LakeRootResource.ensure_available_for_run()` 只在具体业务 asset 运行时检查：

```text
lake_root
lake_root/raw
lake_root/silver
lake_root/gold
```

这能发现一部分路径不存在问题，但发现时机偏晚：通常要等某个业务 asset 已经开始运行，才会暴露移动盘未挂载、权限异常、磁盘空间不足或 DuckDB temp/spill 目录不可用。

当前代码已增强 `LakeRootResource.ensure_available_for_run()`：业务 asset 执行前会检查必要路径，并在 `_tmp/lake_root_health` 做 canary 写读删 fail-fast。磁盘空间和 DuckDB temp/spill 状态由独立 `lake_root_health` asset/checks 暴露，不作为所有业务 asset 的直接运行前置。

本方案新增一个独立的 Dagster 基础设施健康资产 `lake_root_health`，把“湖根目录和 DuckDB 临时目录是否适合继续生产”从业务 asset 失败中剥离出来。

## 2. 已拍板口径

1. 磁盘空间阈值固定为：
   - lake root 可用空间低于 `64 GiB` 判定失败。
   - DuckDB temp directory 可用空间低于 `64 GiB` 判定失败。
2. 允许增强 `LakeRootResource.ensure_available_for_run()`：
   - 增加 canary 读写检查。
   - 影响所有调用它的业务 asset，使其在湖根目录不可写时 fail-fast。
3. 本轮不新增 env、YAML 或 run config 配置项。
4. 本轮不运行正式 Dagster，不读取正式 Dagster instance，不写正式业务 lake 数据。

## 3. 目标

`lake_root_health` 的目标是提前识别基础设施异常，而不是替代数据质量检查。

它负责检查：

1. lake root 是否存在。
2. `raw/silver/gold` 目录是否存在且是目录，`_tmp` 目录是否可创建。
3. lake root 是否可读。
4. lake root 的 `_tmp/lake_root_health` 是否可写、可读、可删除 canary 文件。
5. lake root 所在文件系统可用空间是否不低于 `64 GiB`。
6. DuckDB temp directory 是否存在或可创建。
7. DuckDB temp directory 是否可读写。
8. DuckDB temp directory 所在文件系统可用空间是否不低于 `64 GiB`。

## 4. 非目标

本方案不做：

1. 不检查每个数据集的文件完整性。
2. 不递归扫描全湖。
3. 不读取 Parquet 明细。
4. 不替代 raw/silver/gold/serving 的 blocking asset checks。
5. 不自动修改所有生产 sensor 的触发逻辑。
6. 不新增状态表、summary asset、数据库表或配置项。
7. 不对正式 lake 数据文件做任何写入、覆盖、删除或修复。

## 5. 资产设计

### 5.1 Asset

新增非分区 asset：

```text
lake_root_health
```

已落点：

```text
lake_console/orchestrator/src/orchestrator/defs/assets/lake_root_health.py
```

资产语义：

1. 它是基础设施健康状态，不是数据集文件。
2. 它不写 Parquet。
3. 它只产生 Dagster materialization metadata。
4. 如果关键检查失败，asset materialization 失败，并在 failure metadata 中记录失败项。

已落地 metadata 口径：

```text
goldenshare/dataset_id = lake_root_health
goldenshare/dataset_name = Lake 根目录健康
goldenshare/source_system = derived
goldenshare/data_contract = lake_root_health_v1
goldenshare/health_status = healthy | failed
goldenshare/lake_root = <path>
goldenshare/duckdb_temp_directory = <path>
goldenshare/lake_root_free_bytes = <int>
goldenshare/duckdb_temp_free_bytes = <int>
goldenshare/lake_root_free_gib = <float>
goldenshare/duckdb_temp_free_gib = <float>
goldenshare/lake_root_min_free_gib = 64
goldenshare/duckdb_temp_min_free_gib = 64
goldenshare/checked_at = <ISO timestamp>
goldenshare/failure_reasons = []
```

该 asset 不注册 `dagster/column_schema`，因为它不是 table-like asset。

### 5.2 Asset Tags

当前 asset layer 枚举只有 `raw/silver/gold/serving`。`lake_root_health` 属于平台观测，不应伪装成任一数据层。

已扩展治理枚举：

```text
AssetLayer.PLATFORM = "platform"
DataDomain.PLATFORM_OBSERVABILITY = "platform_observability"
```

`lake_root_health` 使用：

```text
goldenshare/layer = platform
goldenshare/data_domain = platform_observability
```

对应测试需要同步更新 asset governance static contracts。

## 6. Health Evaluation Helper

新增稳定 helper，已落点：

```text
lake_console/orchestrator/src/orchestrator/defs/health/lake_root.py
```

已落地核心接口：

```python
evaluate_lake_root_health(
    *,
    lake_root: Path,
    duckdb_temp_directory: Path,
    min_lake_root_free_bytes: int = 64 * GiB,
    min_duckdb_temp_free_bytes: int = 64 * GiB,
    check_disk_space: bool = True,
    check_duckdb_temp: bool = True,
) -> LakeRootHealthStatus
```

`LakeRootHealthStatus` 已包含：

```text
healthy: bool
run_available: bool
lake_root: Path
duckdb_temp_directory: Path
required_paths: tuple[Path, ...]
missing_required_paths: tuple[Path, ...]
non_directory_required_paths: tuple[Path, ...]
lake_root_canary_path: Path | None
lake_root_canary_error: str | None
duckdb_temp_canary_path: Path | None
duckdb_temp_canary_error: str | None
lake_root_free_bytes: int | None
duckdb_temp_free_bytes: int | None
required_paths_ready: bool
lake_root_read_write_ready: bool
lake_root_disk_space_ready: bool
duckdb_temp_directory_ready: bool
failure_reasons: tuple[str, ...]
```

Helper 只能做轻量文件系统操作：

1. `Path.exists()` / `Path.is_dir()`。
2. `mkdir(parents=True, exist_ok=True)` 创建 `root/_tmp`、`root/_tmp/lake_root_health` 和 DuckDB temp 目录。
3. 写入一个小 canary 文件。
4. 读取 canary 内容。
5. 删除 canary 文件。
6. `shutil.disk_usage(...)` 获取空间。

说明：`raw/silver/gold` 缺失或不是目录时 fail closed；helper 不自动创建这些业务层目录。

禁止：

1. 递归扫描数据集目录。
2. 打开或读取 Parquet 明细。
3. 写入 `raw/silver/gold` 业务数据目录。
4. 静默修复业务数据文件。

## 7. LakeRootResource 增强

当前：

```python
def ensure_available_for_run(self) -> None:
    root = self.root()
    required_paths = [root, root / RAW, root / SILVER, root / GOLD]
    missing_paths = [path for path in required_paths if not path.exists()]
    if missing_paths:
        ...
```

已增强为：

1. 必须检查：
   - `root`
   - `root/raw`
   - `root/silver`
   - `root/gold`
   - `root/_tmp`
2. `root/_tmp/lake_root_health` 可创建。
3. 在 `root/_tmp/lake_root_health` 下执行 canary 写、读、删。
4. 失败时抛清晰异常，包含失败路径和原因。

说明：

1. 该增强会影响所有调用 `lake_root.ensure_available_for_run()` 的业务 asset。
2. 这是已拍板的 fail-fast 行为。
3. 它只检查 lake root 必要路径和 canary 读写能力，不检查 DuckDB temp，不负责替代业务 asset 的质量检查。

## 8. Checks 设计

新增 blocking asset checks，已落点：

```text
lake_console/orchestrator/src/orchestrator/defs/checks/lake_root_health_checks.py
```

### 8.1 lake_root_required_paths_ready

检查：

```text
lake_root
lake_root/raw
lake_root/silver
lake_root/gold
lake_root/_tmp
```

通过条件：

1. `lake_root/raw/silver/gold` 必须存在且是目录。
2. `lake_root/_tmp` 必须存在或可创建。
3. 必需路径是目录。

### 8.2 lake_root_read_write_ready

检查：

1. lake root 可读。
2. `_tmp/lake_root_health` 可写。
3. canary 文件可写、可读、可删除。

### 8.3 lake_root_disk_space_ready

检查：

1. `shutil.disk_usage(lake_root).free >= 64 GiB`。

### 8.4 duckdb_temp_directory_ready

检查：

1. DuckDB temp directory 可创建。
2. DuckDB temp directory 可读写。
3. `shutil.disk_usage(duckdb_temp_directory).free >= 64 GiB`。

所有 checks 写入 metadata：

```text
check_scope
free_bytes
free_gib
min_free_gib
failure_reasons
canary_path
```

## 9. Job / Schedule

新增 asset job：

```text
lake_root_health_check_job
```

selection：

```text
lake_root_health + checks_for_assets(lake_root_health)
```

已落点：

```text
lake_console/orchestrator/src/orchestrator/defs/jobs/lake_root_health_check.py
```

已新增 schedule，默认 `STOPPED`：

```text
lake_root_health_schedule
cron: 0 */2 * * *
timezone: Asia/Shanghai
default_status: STOPPED
```

原因：

1. 让 UI 中有固定健康检查入口。
2. 不在代码发布后自动开始生产操作。
3. 正式启用 schedule 需要单独审批。

## 10. 与 Sensor 的关系

本轮不修改现有业务 sensor。

后续可单独立项：

1. `stock_daily_sensor`
2. `stock_mins_raw_sensor`
3. `stock_mins_silver_sensor`
4. `stock_mins_qfq_daily_sensor`
5. `stock_mins_qfq_factor_repair_sensor`
6. ClickHouse serving automation sensors

在提交 run 前先读取 `lake_root_health` readiness：

```text
lake_root_health materialized
and lake_root_health blocking checks passed
```

该动作必须单独设计，因为它会改变现有 sensor tick 行为和 SkipReason 文案。

## 11. 性能门禁

| 项 | 口径 |
|---|---|
| 数据集扫描 | 0，不递归扫描 lake |
| Parquet 读取 | 0 |
| DuckDB 查询 | 0 |
| 正式 lake 数据写入 | 0 |
| 文件写入 | `root/_tmp/lake_root_health` 和 DuckDB temp 下各一个 canary 小文件 |
| 文件删除 | 仅删除本次两个 canary 小文件 |
| 预计耗时 | 毫秒级到秒级 |
| 空间阈值 | lake root 64 GiB，DuckDB temp 64 GiB |
| 不可接受行为 | 扫描全湖、读取 Parquet、写 raw/silver/gold 数据、自动修复业务数据 |
| 失败策略 | fail closed，metadata 写明失败项 |

## 12. 测试计划

新增测试：

```text
tests/test_lake_root_health_asset.py
```

契约测试同步扩展：

```text
tests/test_asset_governance_contracts.py
tests/test_run_contract_static_gates.py
```

覆盖：

1. required paths 缺失时失败。
2. `_tmp/lake_root_health` 可创建时通过。
3. canary 写入失败时失败。
4. canary 读取内容不一致时失败。
5. canary 删除失败时失败。
6. lake root free space 低于 `64 GiB` 时失败。
7. DuckDB temp free space 低于 `64 GiB` 时失败。
8. `LakeRootResource.ensure_available_for_run()` 调用 canary 检查。
9. `lake_root_health_check_job` 只选择 `lake_root_health` 和 checks。
10. `lake_root_health` 不注册 `dagster/column_schema`。
11. `lake_root_health` 使用 `platform/platform_observability` governance tags。
12. 不新增业务 sensor 依赖。

## 13. 验证命令

开发落地后执行：

```bash
cd /Users/congming/github/goldenshare/lake_console/orchestrator
.venv/bin/python -m py_compile \
  src/orchestrator/defs/assets/lake_root_health.py \
  src/orchestrator/defs/checks/lake_root_health_checks.py \
  src/orchestrator/defs/health/lake_root.py \
  src/orchestrator/defs/jobs/lake_root_health_check.py \
  src/orchestrator/defs/schedules/lake_root_health.py \
  src/orchestrator/defs/resources.py \
  tests/test_lake_root_health_asset.py \
  tests/test_asset_governance_contracts.py \
  tests/test_run_contract_static_gates.py

.venv/bin/python -m unittest \
  tests.test_lake_root_health_asset \
  tests.test_asset_governance_contracts \
  tests.test_run_contract_static_gates

.venv/bin/ruff check \
  src/orchestrator/defs/assets/lake_root_health.py \
  src/orchestrator/defs/checks/lake_root_health_checks.py \
  src/orchestrator/defs/health/lake_root.py \
  src/orchestrator/defs/jobs/lake_root_health_check.py \
  src/orchestrator/defs/schedules/lake_root_health.py \
  src/orchestrator/defs/resources.py \
  tests/test_lake_root_health_asset.py \
  tests/test_asset_governance_contracts.py \
  tests/test_run_contract_static_gates.py

git diff --check
python3 scripts/check_docs_integrity.py
```

禁止执行：

```text
dg
dagster
正式 job
正式 sensor
正式 backfill
正式 materialization
正式 asset check
读取正式 Dagster instance
写正式 lake 数据文件
```

## 14. 风险与后续

### 14.1 业务 asset 更早失败

`LakeRootResource.ensure_available_for_run()` 增加 canary 后，部分原本会继续跑到后续 DuckDB 或 Parquet 写入才失败的 run，会提前失败。

这是预期行为。

### 14.2 health asset 与业务 sensor 尚未联动

V1 只新增 health asset/job/checks，不改变业务 sensor 提交流程。

如果要在 sensor 提交前强制检查 `lake_root_health`，需要单独做 V2：

1. 设计批量读取 health readiness 的 helper。
2. 修改关键 sensors。
3. 更新 SkipReason。
4. 加 static gates，防止 sensor 绕过。

### 14.3 阈值暂不配置化

阈值固定为 `64 GiB`，不新增配置项。

未来如需配置化，必须先做配置项审计，列清默认值、来源、持久化位置、消费者、生效方式和运维可见性。
