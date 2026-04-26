# Sync V1 旧路径移除执行计划 v1

- 版本：v1.0
- 日期：2026-04-23
- 状态：执行完成（Batch 0/1/2/3/4/5/6 完成）
- 目标：在“不再回切 V1”的前提下，彻底移除 `src/foundation/services/sync` 下的 V1 数据集实现路径，只保留 V2 仍真实依赖的最小能力。

---

## 1. 执行边界（已拍板）

1. 不再保留“V1 回退通道”。
2. V2 如有问题，只修 V2，不回切 V1。
3. 每批只做一个目标，不顺手做计划外改动。
4. 删除前必须先做引用审计 + 最小回归。

---

## 2. Batch 0 基线冻结（本轮结果）

### 2.1 快照统计（src 代码引用视角）

1. `src/foundation/services/sync/*.py` 总模块数：`63`
2. `sync_*_service.py` 服务模块数：`56`
3. 在 `src` 范围内，仍被非 `sync` 目录引用的 `sync` 模块：`5`
4. 在 `src` 范围内，仍被非 `sync` 目录引用的 `sync_*_service.py`：`1`

### 2.2 外部引用清单（Batch 0 冻结）

1. ``src/foundation/services/sync_v2/base_sync_service.py``（历史路径，已删除）
被 ``src/foundation/services/sync_v2/service.py``（历史路径，已删除） 引用。
2. ``src/foundation/services/sync_v2/execution_errors.py``（历史路径，已删除）
被 ``src/foundation/services/sync_v2/engine.py``（历史路径，已删除）、`src/ops/runtime/dispatcher.py`（历史实现，已退场）引用。
3. ``src/foundation/services/sync_v2/fields.py``（历史路径，已删除）
被 `sync_v2` contract/planner 与 `stk_factor_pro` 模型引用。
4. `src/foundation/services/sync/registry.py`（历史基线记录，已在 Batch 4 删除）  
被 [`src/cli.py`](/Users/congming/github/goldenshare/src/cli.py)、`src/ops/runtime/dispatcher.py`（历史实现，已退场）、`src/ops/services/operations_history_backfill_service.py`（历史实现，已退场）、`src/ops/services/operations_sync_job_state_reconciliation_service.py`（历史实现，已删除）、旧 ops 规格注册表引用。
5. `src/foundation/services/sync/sync_moneyflow_service.py`（历史基线记录，已在 Batch 4 删除）  
仅被 ``src/foundation/services/sync_v2/writer.py``（历史路径，已删除） 引用（`publish_moneyflow_serving_for_keys`）。

### 2.3 门禁测试冻结（后续每批至少通过）

1. `tests/test_sync_v2_validator.py`
2. `tests/test_sync_v2_planner.py`
3. `tests/test_sync_v2_worker_client.py`
4. `tests/test_sync_v2_linter.py`
5. `tests/architecture/test_sync_v2_registry_guardrails.py`
6. 本批涉及 CLI 的最小冒烟（按改动命令集）
7. 本批涉及 ops runtime 的最小冒烟（dispatcher/spec/调度相关）

### 2.4 Batch 1 完成结果（2026-04-23）

1. V2 主路径不再直接依赖 V1 `base/errors/fields/moneyflow helper`：
   - `BaseSyncService` 主实现迁至 ``src/foundation/services/sync_v2/base_sync_service.py``（历史路径，已删除）
   - `ExecutionCanceledError` 主实现迁至 ``src/foundation/services/sync_v2/execution_errors.py``（历史路径，已删除）
   - 字段常量主实现迁至 ``src/foundation/services/sync_v2/fields.py``（历史路径，已删除）
   - `publish_moneyflow_serving_for_keys` 主实现迁至 ``src/foundation/services/sync_v2/moneyflow_publish.py``（历史路径，已删除）
2. `src/foundation/services/sync/*` 在 Batch 1 时曾保留最小兼容壳（不承接新逻辑）：
   - `src/foundation/services/sync/base_sync_service.py`（Batch 5 已删除）
   - `src/foundation/services/sync/errors.py`（Batch 5 已删除）
   - `src/foundation/services/sync/fields.py`（Batch 5 已删除）
3. Batch 1 门禁：
   - `tests/test_sync_v2_validator.py`
   - `tests/test_sync_v2_planner.py`
   - `tests/test_sync_v2_worker_client.py`
   - `tests/test_sync_v2_linter.py`
   - `tests/architecture/test_sync_v2_registry_guardrails.py`
   - `tests/test_base_sync_service_snapshot_refresh.py`
   - `tests/test_sync_moneyflow_service.py`
   - 结果：`57 passed`

### 2.5 Batch 2 完成结果（2026-04-23）

1. 新增 V2-only 运行注册入口：
   - ``src/foundation/services/sync_v2/runtime_registry.py``（历史路径，已删除）
   - 提供统一的：
     - `SYNC_SERVICE_REGISTRY`
     - `build_sync_service`
     - `list_trade_date_backfill_resources`
2. CLI/ops/runtime/spec 已统一切到 V2 runtime registry：
   - [`src/cli.py`](/Users/congming/github/goldenshare/src/cli.py)
   - `src/ops/runtime/dispatcher.py`（历史实现，已退场）
   - `src/ops/services/operations_history_backfill_service.py`（历史实现，已退场）
   - `src/ops/services/operations_sync_job_state_reconciliation_service.py`（历史实现，已删除）
   - 旧 ops 规格注册表（已退场）
3. 旧路径 `src/foundation/services/sync/registry.py` 在 Batch 2 曾降级为兼容壳，Batch 4 已删除。
4. Batch 2 门禁与最小冒烟：
   - `tests/test_sync_v2_registry_routing.py`
   - `tests/test_sync_registry.py`
   - `tests/test_ops_action_catalog.py`
   - `tests/test_sync_v2_validator.py`
   - `tests/test_sync_v2_planner.py`
   - `tests/test_sync_v2_worker_client.py`
   - `tests/test_sync_v2_linter.py`
   - `tests/architecture/test_sync_v2_registry_guardrails.py`
   - `tests/test_base_sync_service_snapshot_refresh.py`
   - `tests/test_sync_moneyflow_service.py`
   - `tests/web/test_ops_runtime.py`
   - `tests/web/test_health_api.py`
   - `tests/web/test_ops_pages.py`
   - `tests/web/test_platform_check_page.py`
   - 结果：`91 passed`

### 2.6 Batch 4 完成结果（2026-04-23）

1. 已删除 V1 业务实现文件：
   - `src/foundation/services/sync/sync_*_service.py` 全量 `56` 个文件。
   - `src/foundation/services/sync/resource_sync.py`
   - `src/foundation/services/sync/registry.py`
2. 删除前再次引用审计（`src/tests/scripts/docs/README*/pyproject/.github`）结论：
   - 代码侧不再存在对 `src.foundation.services.sync.sync_*_service`、`...resource_sync`、`...registry` 的直接引用。
   - 仅文档中的历史记录条目保留路径说明（不影响运行）。
3. 最小配套更新：
   - [`scripts/generate_dataset_catalog.py`](/Users/congming/github/goldenshare/scripts/generate_dataset_catalog.py) 切到 `sync_v2` contract 数据源，避免继续依赖已删除旧 registry。
4. Batch 4 门禁：
   - `pytest -q tests/test_sync_v2_validator.py tests/test_sync_v2_planner.py tests/test_sync_v2_worker_client.py tests/test_sync_v2_linter.py tests/architecture/test_sync_v2_registry_guardrails.py tests/test_sync_v2_registry_routing.py tests/test_sync_registry.py tests/test_ops_action_catalog.py tests/test_base_sync_service_snapshot_refresh.py tests/test_sync_moneyflow_service.py`
   - 结果：`70 passed`

### 2.7 Batch 5 完成结果（2026-04-23）

1. 已删除 V1 基础残留文件：
   - `src/foundation/services/sync/base_sync_service.py`
   - `src/foundation/services/sync/errors.py`
   - `src/foundation/services/sync/fields.py`
   - `src/foundation/services/sync/sync_execution_context.py`
   - `src/foundation/services/sync/sync_state_store.py`
2. 对应能力已迁入 `sync_v2`：
   - ``src/foundation/services/sync_v2/sync_execution_context.py``（历史路径，已删除）
   - ``src/foundation/services/sync_v2/sync_state_store.py``（历史路径，已删除）
   - `src/foundation/services/sync_v2/base_sync_service.py` 已切换到新路径导入。
3. 配套测试口径切换：
   - [`tests/test_fields_constants.py`](/Users/congming/github/goldenshare/tests/test_fields_constants.py) 改为引用 `sync_v2.fields`。
4. Batch 5 门禁：
   - `pytest -q tests/test_sync_v2_validator.py tests/test_sync_v2_planner.py tests/test_sync_v2_worker_client.py tests/test_sync_v2_linter.py tests/architecture/test_sync_v2_registry_guardrails.py tests/test_sync_v2_registry_routing.py tests/test_sync_registry.py tests/test_ops_action_catalog.py tests/test_base_sync_service_snapshot_refresh.py tests/test_sync_moneyflow_service.py tests/test_fields_constants.py`
   - 结果：`74 passed`

### 2.8 Batch 6 完成结果（2026-04-23）

1. 已删除 legacy 包壳：
   - `src/foundation/services/sync/__init__.py`
2. 新增防回流护栏测试：
   - [`tests/architecture/test_sync_v1_legacy_guardrails.py`](/Users/congming/github/goldenshare/tests/architecture/test_sync_v1_legacy_guardrails.py)
   - 覆盖：
     - 禁止 `src/tests/scripts` 继续 import `src.foundation.services.sync*`
     - 禁止 `src/foundation/services/sync` 再出现 Python 源文件
3. 文档状态已收口到“V1 旧路径移除完成”。

---

## 3. 分批执行计划（已确认）

### Batch 1（迁移公共能力，暂不删 V1）

1. 将 V2 仍依赖的公共能力迁入 `sync_v2`：
   - `BaseSyncService` 依赖基座
   - `ExecutionCanceledError`
   - `fields` 常量
   - `publish_moneyflow_serving_for_keys`
2. 改完引用后，V2 不再直接 import `src.foundation.services.sync.sync_*_service`。
3. 本批不删除 `sync` 目录文件。

### Batch 2（V2-only 运行注册入口）

1. 在 `sync_v2` 建立运行时 registry（构建 service、资源清单、target_table/job_name 元信息）。
2. CLI/ops/runtime/spec 调用统一切到 V2 runtime registry。
3. 删除“按开关回退 V1”的路径逻辑。

### Batch 3（测试口径切换）

1. 将仍依赖 V1 `sync_*_service.py` 的测试切到 V2 口径。
2. 去掉仅验证 V1 类实现细节的断言。

> 审计快照（2026-04-23，Batch 2 后）：
> - 仍直接 import `src.foundation.services.sync.sync_*_service` 的测试文件：`27` 个
> - 已完成切换：`tests/test_sync_v2_registry_routing.py`、`tests/test_sync_registry.py`、`tests/test_ops_action_catalog.py`
> - 待切换主集合：`tests/test_*sync*_service.py` 及 board/ranking/extended 组合测试

> Batch 3 完成结果（2026-04-23）：
> - 已将全部 V1 测试导入口径切到 V2（contract + dataset strategy/normalizer），覆盖：
>   - 基础/单数据集：`tests/test_sync_*_service.py` 主集合
>   - 组合测试：`tests/test_board_sync_services.py`、`tests/test_limit_theme_sync_services.py`、`tests/test_ranking_sync_services.py`、`tests/test_extended_sync_services.py`
>   - 兼容补充：`tests/test_fields_constants.py`
> - 最小门禁通过：`pytest -q tests/test_board_sync_services.py tests/test_extended_sync_services.py tests/test_limit_theme_sync_services.py tests/test_ranking_sync_services.py tests/test_sync_block_trade_service.py tests/test_sync_dividend_service.py tests/test_sync_fund_adj_service.py tests/test_sync_holdernumber_service.py tests/test_sync_moneyflow_service.py tests/test_sync_stk_factor_pro_service.py tests/test_sync_stock_basic_service.py tests/test_sync_biying_equity_daily_service.py tests/test_sync_biying_moneyflow_service.py tests/test_sync_margin_service.py tests/test_sync_limit_list_service.py tests/test_sync_top_list_service.py tests/test_sync_stk_limit_service.py tests/test_sync_stock_st_service.py tests/test_sync_suspend_d_service.py tests/test_sync_stk_nineturn_service.py tests/test_sync_cyq_perf_service.py tests/test_sync_v2_planner.py tests/architecture/test_sync_v2_registry_guardrails.py`
> - 结果：`100 passed`
> - 直接 import V1 `sync_*_service` 的测试文件余量：`0` 个。

### Batch 4（删除 V1 业务实现）

1. 删除 `sync_*_service.py` 全量 56 文件（已完成）。
2. 删除 `resource_sync.py` 与旧 `registry.py`（已完成）。

### Batch 5（删除 V1 基础残留）

1. 删除 `sync` 目录内仍残留且无引用的基础文件（`base/errors/fields/state/context`）（已完成）。

### Batch 6（护栏与文档收口）

1. 增加禁止回流护栏测试（禁止再引用 V1 sync service/registry）（已完成）。
2. 更新 AGENTS + architecture 文档基线，明确 V1 已移除（已完成）。

---

## 4. 回滚策略

1. 每个 Batch 独立 commit。
2. 若某批门禁失败，仅回退该批 commit，不跨批修复。
3. 未完成的后续批次不提前执行。

---

## 5. 复现审计命令（Batch 0）

```bash
python3 - <<'PY'
from pathlib import Path
root=Path('/Users/congming/github/goldenshare')
sync_dir=root/'src/foundation/services/sync'
all_src=[p for p in (root/'src').rglob('*.py')]
sync_modules=[]
for p in sorted(sync_dir.glob('*.py')):
    if p.name=='__init__.py':
        continue
    mod=f"src.foundation.services.sync.{p.stem}"
    users=[]
    for f in all_src:
        rel=str(f.relative_to(root))
        if mod in f.read_text(errors='ignore'):
            users.append(rel)
    users=sorted(set(users))
    external=[u for u in users if not u.startswith('src/foundation/services/sync/')]
    sync_modules.append((str(p.relative_to(root)), external))
print("sync_module_total=", len(sync_modules))
print("external_ref_modules=", [m for m,e in sync_modules if e])
PY
```
