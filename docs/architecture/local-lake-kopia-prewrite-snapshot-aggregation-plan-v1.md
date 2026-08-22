# Local Lake Kopia Prewrite Snapshot 聚合改造方案 v1

> **文档状态：历史/冻结（旧 `lake_console/backend` 方案证据）**：本文只记录旧 Kopia prewrite 实现及其历史收口讨论，不代表当前批准的写湖或恢复主线。不得据此开展新开发、迁移、历史补录、bootstrap、修复或写湖任务；当前正式 Lake 路径和安全规则以根目录 `AGENTS.md` 与 `lake_console/orchestrator/src/orchestrator/defs/paths.py` 为准；禁止新增或调用 Kopia。

## 1. 背景

Sync Center 写入任务在执行真实写盘前，会创建 Kopia prewrite snapshot，目的是在写入失败或误写时保留恢复点。

当前实现存在一个严重管理问题：

```text
一个已存在 backup_path -> 创建一个 Kopia snapshot
```

当一次补数任务涉及多个日期分区时，Recovery / Write Safety 页面会出现大量 snapshot。这个结果不是页面误解，而是当前代码真实行为。

本方案只讨论后续代码如何收口，**不删除现有 snapshot，不重新备份，不动真实 Parquet 数据**。

## 2. 当前代码事实

### 2.1 plan 阶段如何生成 backup_paths

文件：`lake_console/backend/app/services/sync_center_profiles.py`

当前代码：

```python
308 def _build_backup_plan(self, *, dataset_plans: list[dict[str, Any]]) -> dict[str, Any]:
309     backup_paths: list[str] = []
310     missing_paths: list[str] = []
311     for dataset_plan in dataset_plans:
312         for relative_path in dataset_plan["write_paths"]:
313             path = self.lake_root / relative_path
314             if path.exists():
315                 backup_paths.append(relative_path)
316             else:
317                 missing_paths.append(relative_path)
318     lake_jobs = self.lake_root / "manifest" / "lake_jobs"
319     if lake_jobs.exists():
320         backup_paths.append("manifest/lake_jobs")
```

事实：

1. `dataset_plan["write_paths"]` 是本次要写的具体路径。
2. 对日期分区数据集，这些路径通常是：

```text
raw_tushare/<dataset_key>/trade_date=YYYY-MM-DD
```

3. 已存在路径进入 `backup_paths`。
4. 不存在路径进入 `path_missing_before_write`。

### 2.2 backup 阶段如何创建 snapshot

文件：`lake_console/backend/app/services/kopia_prewrite_backup_service.py`

当前代码：

```python
34 def create_prewrite_backup(...):
35     backup_paths = [str(item) for item in backup_plan.get("backup_paths") or []]
...
40     for relative_path in backup_paths:
41         absolute_path = (self.lake_root / relative_path).resolve()
...
47         description = f"lake-sync prewrite run={run_id} profile={profile_key} path={relative_path}"
48         payload = self.runner(
49             [
50                 self.kopia_bin,
51                 "snapshot",
52                 "create",
53                 str(absolute_path),
...
```

事实：

1. 当前按 `backup_paths` 循环。
2. 每个 `relative_path` 调一次 `kopia snapshot create`。
3. 因此每个已存在路径都会生成独立 snapshot。
4. 备份记录里 `snapshots[]` 也是 path 级记录。

### 2.3 Recovery 页面为什么看到很多 snapshot

文件：`lake_console/backend/app/services/kopia_recovery_service.py`

当前代码：

```python
155 def _load_snapshots(self) -> list[KopiaSnapshotRecord]:
156     payload = self.runner([self.kopia_bin, "snapshot", "list", "--all", "--json", "--disable-file-logging"])
...
183     scope, dataset = _classify_scope(relative_path)
...
193     records.append(KopiaSnapshotRecord(...))
```

事实：

1. Recovery 页面读取 Kopia 仓库里的真实 snapshot list。
2. 当前每个 path 已经创建成独立 snapshot，所以页面自然会看到很多行。
3. 这不是展示误解，也不是 Kopia 自动展开目录。

### 2.4 当前测试也锁定了错误行为

文件：`lake_console/backend/tests/test_kopia_prewrite_backup_service.py`

当前测试：

```python
10 def test_kopia_prewrite_backup_creates_snapshots_for_existing_paths(...)
```

事实：

1. 测试名称和断言都在确认“existing paths -> snapshots”。
2. 改造时必须同步修改测试，否则测试会保护旧错误行为。

## 3. 新目标

后续 prewrite backup 必须从“path 级 snapshot”改为“聚合 snapshot”。

目标口径：

```text
一次 run 按写入目标聚合成少量 snapshot
path 明细仍保存在 backup record
Recovery 页面可按 run 识别 prewrite backup
```

不做：

1. 不删除已有 Kopia snapshot。
2. 不重写已有 Kopia snapshot。
3. 不修改真实 Lake 数据。
4. 不改变 Sync Profile Runner 写入逻辑。
5. 不改变 Kopia restore 命令真实执行能力。

## 4. 聚合策略

### 4.1 聚合原则

将具体写入路径归并到更稳定的父目录：

| 原 backup_path 示例 | 聚合 snapshot path |
| --- | --- |
| `raw_tushare/dc_daily/trade_date=2026-05-06` | `raw_tushare/dc_daily` |
| `raw_tushare/dc_daily/trade_date=2026-05-07` | `raw_tushare/dc_daily` |
| `raw_tushare/moneyflow/trade_date=2026-05-06` | `raw_tushare/moneyflow` |
| `manifest/lake_jobs` | `manifest/lake_jobs` |
| `manifest/security_universe/tushare_stock_basic.parquet` | `manifest/security_universe` |

这样一次 `prod_db_manual_backfill` 即使涉及多个日期，也只会按数据集父目录创建 snapshot。

### 4.2 为什么不备份整个 Lake Root

不采用：

```text
snapshot create <lake_root>
```

原因：

1. 范围太大。
2. 扫描成本过高。
3. 恢复时风险过大。
4. 与“只保护本次写入影响面”的目标不一致。

### 4.3 为什么不继续按日期分区备份

不继续采用：

```text
snapshot create raw_tushare/dc_daily/trade_date=...
```

原因：

1. snapshot 数量膨胀。
2. Recovery 页面不可读。
3. 后续 pin / delete / restore 容易误操作。
4. 一次 run 的备份语义被打散。

## 5. 需要修改的文件和具体改动点

### 5.1 `sync_center_profiles.py`

文件：`lake_console/backend/app/services/sync_center_profiles.py`

#### 改动点 A：保留 path 明细，同时增加聚合路径

当前位置：

```python
308 def _build_backup_plan(...)
```

建议修改：

1. 保留现有 `backup_paths`，含义改为“本次会写且写前已存在的具体路径明细”。
2. 新增 `snapshot_paths`，表示真正传给 Kopia 的聚合路径。
3. `summary.backup_path_count` 继续表示具体 path 数。
4. 新增 `summary.snapshot_path_count` 表示聚合后 snapshot path 数。

目标返回结构：

```python
return {
    "required": True,
    "provider": "kopia",
    "snapshot_strategy": "prewrite_dataset_root_scope",
    "pin_policy": "none",
    "pinned": False,
    "backup_paths": sorted(set(backup_paths)),
    "snapshot_paths": sorted(set(snapshot_paths)),
    "path_missing_before_write": sorted(set(missing_paths)),
}
```

#### 改动点 B：新增路径聚合函数

在 `SyncProfilePlanner` 内新增私有方法：

```python
def _snapshot_root_for_backup_path(self, relative_path: str) -> str:
    ...
```

规则：

1. `raw_tushare/<dataset_key>/...` -> `raw_tushare/<dataset_key>`
2. `derived/<dataset_key>/...` -> `derived/<dataset_key>`
3. `research/<dataset_key>/...` -> `research/<dataset_key>`
4. `manifest/lake_jobs` -> `manifest/lake_jobs`
5. `manifest/<group>/<file-or-child>` -> `manifest/<group>`
6. 其它路径默认取第一层目录，禁止返回空字符串。

#### 改动点 C：存在性判断仍以具体 path 为准

不能只看聚合目录是否存在。

原因：

```text
raw_tushare/dc_daily 存在
但 raw_tushare/dc_daily/trade_date=2026-05-09 可能不存在
```

因此：

1. `backup_paths` / `path_missing_before_write` 仍按具体写入 path 判断。
2. `snapshot_paths` 只从已存在的 `backup_paths` 聚合而来。

### 5.2 `kopia_prewrite_backup_service.py`

文件：`lake_console/backend/app/services/kopia_prewrite_backup_service.py`

#### 改动点 A：用 `snapshot_paths` 创建 snapshot

当前位置：

```python
35 backup_paths = [str(item) for item in backup_plan.get("backup_paths") or []]
...
40 for relative_path in backup_paths:
```

建议修改：

```python
backup_paths = [str(item) for item in backup_plan.get("backup_paths") or []]
snapshot_paths = [str(item) for item in backup_plan.get("snapshot_paths") or backup_paths]
```

说明：

1. 新计划使用 `snapshot_paths`。
2. `or backup_paths` 是为了读旧 plan 或旧测试时不崩，但不作为长期行为。

#### 改动点 B：循环 `snapshot_paths`，不是 `backup_paths`

当前位置：

```python
40 for relative_path in backup_paths:
```

修改为：

```python
for relative_path in sorted(set(snapshot_paths)):
```

#### 改动点 C：description 改成 run + scope，不再写 path-level 误导

当前位置：

```python
47 description = f"lake-sync prewrite run={run_id} profile={profile_key} path={relative_path}"
```

修改为：

```python
description = f"lake-sync prewrite run={run_id} profile={profile_key} snapshot_path={relative_path}"
```

#### 改动点 D：返回结构区分 snapshot_paths 与 backup_paths

当前位置：

```python
"snapshots": snapshot_records,
"backup_paths": backup_paths,
```

建议返回：

```python
"snapshots": snapshot_records,
"snapshot_paths": sorted(set(snapshot_paths)),
"backup_paths": backup_paths,
"path_missing_before_write": sorted(set(missing_paths)),
```

其中 `snapshot_records[].path` 改为聚合 snapshot path。

### 5.3 `sync_center.py`

文件：`lake_console/backend/app/api/sync_center.py`

#### 改动点 A：backup completed metrics 增加聚合信息

当前位置：

```python
203 "metrics": {"snapshot_count": len(backup.get("snapshot_ids") or [])},
```

建议修改：

```python
"metrics": {
    "snapshot_count": len(backup.get("snapshot_ids") or []),
    "snapshot_path_count": len(backup.get("snapshot_paths") or []),
    "backup_path_count": len(backup.get("backup_paths") or []),
    "path_missing_before_write_count": len(backup.get("path_missing_before_write") or []),
}
```

目的：

1. 事件流直接显示“创建了多少 snapshot”。
2. 与 plan 里的 path 数区别清楚。

### 5.4 `sync_center` schema / types

文件：

1. `lake_console/backend/app/schemas/sync_center.py`
2. `lake_console/frontend/src/types.ts`

当前 `backup_plan` 是 `dict[str, Any]`，前端类型里 `SyncBackupPlan` 只有：

```ts
backup_paths: string[];
path_missing_before_write: string[];
```

建议：

1. 后端 schema 暂不需要新增 Pydantic 字段，因为 `backup_plan` 是 dict。
2. 前端 `SyncBackupPlan` 增加：

```ts
snapshot_paths: string[];
```

### 5.5 `SyncCenterPage.tsx`

文件：`lake_console/frontend/src/pages/SyncCenterPage.tsx`

#### 改动点 A：Kopia 备份范围展示分清三类

当前页面展示：

```text
将备份的路径
写入前不存在
```

建议改为三块：

```text
本次将创建 snapshot 的聚合路径
本次会写且写前已存在的明细路径
写入前不存在
```

说明：

1. `snapshot_paths` 是 Kopia 真正创建 snapshot 的路径。
2. `backup_paths` 是本次会写且已有旧内容的明细路径。
3. `path_missing_before_write` 是新建路径，恢复时用于删除新建内容。

#### 改动点 B：文案明确不再一条明细一个 snapshot

建议描述：

```text
后端会按聚合路径创建 Kopia snapshot；明细路径只用于恢复判断，不会逐条创建 snapshot。
```

### 5.6 `RecoveryPage.tsx` 与 `kopia_recovery_service.py`

本轮不建议强行改 Recovery 聚合展示。

原因：

1. 先修未来 snapshot 创建数量，止血优先。
2. Recovery 页面当前展示 Kopia 真实 snapshot list，事实上没错。
3. 已经产生的旧 path-level snapshots 需要单独审计和删除，不应混入本轮。

但文档需要记录后续任务：

```text
后续可按 backup record 的 run_id 聚合展示 prewrite snapshots。
```

## 6. 测试修改方案

### 6.1 修改 `test_kopia_prewrite_backup_service.py`

当前测试：

```python
test_kopia_prewrite_backup_creates_snapshots_for_existing_paths
```

建议改名：

```python
test_kopia_prewrite_backup_creates_snapshots_for_aggregated_snapshot_paths
```

构造计划：

```python
backup_plan={
    "backup_paths": [
        "raw_tushare/daily/trade_date=2026-05-13",
        "raw_tushare/daily/trade_date=2026-05-14",
    ],
    "snapshot_paths": ["raw_tushare/daily"],
    "path_missing_before_write": ["raw_tushare/moneyflow/trade_date=2026-05-14"],
}
```

断言：

1. `fake_runner` 只被调用 1 次。
2. 创建 snapshot 的路径是 `lake_root/raw_tushare/daily`。
3. `backup["backup_paths"]` 仍保留 2 条明细路径。
4. `backup["snapshot_paths"] == ["raw_tushare/daily"]`。
5. `backup["snapshot_ids"]` 只有 1 个。

### 6.2 新增 `SyncProfilePlanner` 测试

可在现有 Sync Center API / profile 测试中补一条，或新增测试文件。

目标：

1. 创建两个已存在日期分区：

```text
raw_tushare/daily/trade_date=2026-05-13
raw_tushare/daily/trade_date=2026-05-14
```

2. build plan。
3. 断言：

```python
backup_plan["backup_paths"] 包含两个具体日期
backup_plan["snapshot_paths"] 只包含 raw_tushare/daily
```

### 6.3 前端构建

必须跑：

```bash
cd lake_console/frontend
npm run build
```

### 6.4 后端测试

必须跑：

```bash
lake_console/.venv/bin/python -m pytest -q \
  lake_console/backend/tests/test_kopia_prewrite_backup_service.py \
  lake_console/backend/tests/test_sync_center_api.py \
  lake_console/backend/tests/test_sync_center_state.py \
  lake_console/backend/tests/test_sync_profile_runner.py
```

### 6.5 文档完整性

必须跑：

```bash
python3 scripts/check_docs_integrity.py
```

## 7. 迁移与兼容边界

### 7.1 已存在的 path-level snapshots 不处理

本方案不删除、不合并、不隐藏旧 snapshots。

原因：

1. Kopia 不支持原地合并 snapshot。
2. 删除旧 snapshot 是破坏性操作，必须单独出候选清单并由用户确认。
3. 本轮只修后续行为。

### 7.2 旧 backup record 仍可读

旧 `backups/<run_id>-kopia.json` 没有 `snapshot_paths` 字段。

处理方式：

1. Recovery 页面不依赖该字段。
2. `KopiaPrewriteBackupService` 使用 `snapshot_paths or backup_paths`，避免旧测试或旧计划崩溃。
3. 新 plan 必须生成 `snapshot_paths`。

### 7.3 不改真实写入逻辑

本方案只改：

1. plan 的备份范围计算。
2. prewrite backup 的 Kopia create 粒度。
3. UI 展示文案。
4. 测试。

不改：

1. `SyncProfileRunner` 数据写入。
2. remote DB 读取。
3. Parquet 写入。
4. Kopia restore。

## 8. 风险与防护

### 风险 1：snapshot 聚合路径过大

表现：

```text
只改几个日期，却备份整个 dataset root。
```

接受理由：

1. Kopia 增量去重，重复内容不会按全量重新占空间。
2. snapshot 数量显著减少。
3. 恢复明细仍由 `backup_paths` 和 `path_missing_before_write` 控制。

### 风险 2：dataset root 不存在但具体路径存在

理论上不成立。若具体路径存在，父目录必然存在。

防护：

1. `snapshot_paths` 只从已存在 `backup_paths` 聚合。
2. 创建 snapshot 前仍检查 path exists。

### 风险 3：manifest 文件路径聚合不准

规则必须保守：

1. `manifest/lake_jobs` 保持原样。
2. `manifest/<group>/...` 聚合到 `manifest/<group>`。
3. 不聚合到整个 `manifest`，避免范围过大。

### 风险 4：Recovery 页面仍显示旧大量 snapshot

这是历史数据，不是新实现问题。

处理方式：

1. 本轮不处理旧 snapshot。
2. 后续单独做“按 run_id 聚合展示”和“旧 snapshot 删除候选审计”。

## 9. 执行顺序

建议分一轮完成，但严格按顺序：

1. 修改 `SyncProfilePlanner._build_backup_plan`，新增 `snapshot_paths`。
2. 修改 `KopiaPrewriteBackupService.create_prewrite_backup`，按 `snapshot_paths` 创建 snapshot。
3. 修改 backup completed event metrics。
4. 修改前端 `SyncBackupPlan` 类型。
5. 修改 `SyncCenterPage` Kopia 备份范围展示。
6. 修改 / 新增测试。
7. 跑后端测试。
8. 跑前端 build。
9. 跑 docs integrity。

## 10. 完成标准

完成后，生成一个涉及同一数据集多个日期分区的计划时，应满足：

```text
backup_paths: 多个 trade_date 明细路径
snapshot_paths: 一个 dataset root 路径
path_missing_before_write: 新建路径明细
```

启动 run 后，应满足：

```text
Kopia snapshot 数量约等于 snapshot_paths 数量
不再等于 backup_paths 数量
```

Recovery 页面仍可看到 Kopia 真实 snapshot，但后续新任务不会再按日期分区爆炸式增加 snapshot。
