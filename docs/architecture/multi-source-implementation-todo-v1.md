# 多源改造代码级 TODO 清单 v1（按任务包）

更新时间：2026-04-12  
适用范围：Foundation + Ops（基于已定稿契约）  
关联文档：  
- [foundation-multi-source-upgrade-and-migration-v1.md](/Users/congming/github/goldenshare/docs/architecture/foundation-multi-source-upgrade-and-migration-v1.md)  
- [ops-multi-source-contract-v1.md](/Users/congming/github/goldenshare/docs/ops/ops-multi-source-contract-v1.md)  
- [foundation-multi-source-test-refactor-checklist-v1.md](/Users/congming/github/goldenshare/docs/architecture/foundation-multi-source-test-refactor-checklist-v1.md)

## 执行进度记录

- 2026-04-12 包 1 完成（模型+connector+migration+测试）
  - 完成 `foundation.source_registry` / `foundation.dataset_resolution_policy` / `foundation.dataset_source_status`
  - 完成 `SourceConnector` 抽象与 `tushare`/`biying` connector 工厂
  - 完成迁移：
    - `20260412_000035_create_foundation_meta_tables.py`
  - 完成测试：
    - `tests/test_source_registry_models.py`
    - `tests/test_source_connector_factory.py`
    - `tests/test_source_connector_contract.py`

- 2026-04-12 包 2 完成（分源 raw 最小闭环）
  - 完成 `raw_tushare` / `raw_biying` 的首批 3 张表模型：
    - `equity_daily_bar`
    - `equity_adj_factor`
    - `equity_daily_basic`
  - 完成 `RawMultiWriter` 路由写入器
  - 完成迁移：
    - `20260412_000036_create_raw_multi_tables.py`
  - 完成测试：
    - `tests/test_raw_multi_schema_mapping.py`
    - `tests/test_raw_multi_writer.py`

- 2026-04-12 包 3 进行中（Std 标准化层）
  - 已完成模型：
    - `core_multi.equity_daily_bar_std`
    - `core_multi.equity_adj_factor_std`
    - `core_multi.equity_daily_basic_std`
    - `core_multi.stk_period_bar_std`
    - `core_multi.stk_period_bar_adj_std`
  - 已完成 normalizer：
    - `EquityDailyBarNormalizer`
    - `EquityAdjFactorNormalizer`
    - `EquityDailyBasicNormalizer`
    - `StkPeriodBarNormalizer`
    - `StkPeriodBarAdjNormalizer`
  - 已完成迁移：
    - `20260412_000037_create_core_multi_std_tables.py`
  - 已完成测试：
    - `tests/test_core_multi_models.py`
    - `tests/test_normalizer_equity_daily_bar.py`
    - `tests/test_normalizer_error_isolation.py`

- 2026-04-12 BIYING 接入并行事项（stock_basic 首批）
  - 已完成设置项：
    - `BIYING_TOKEN`
    - `BIYING_BASE_URL`
  - 已完成 connector：
    - `BiyingSourceConnector` 支持 `stock_basic`
  - 已完成双源主数据链路：
    - `raw_tushare.stock_basic`
    - `raw_biying.stock_basic`
    - `core_multi.security_std`
    - `core.security_serving`（由 `core.security` 重命名切换）
  - 已完成服务改造：
    - `sync_stock_basic` 按 `source_key` 拉取/标准化/发布
    - 策略：`tushare` 主，`biying` 仅补缺（不覆盖已有 richer 字段）
  - 已完成测试：
    - `tests/test_biying_connector.py`
    - `tests/test_sync_stock_basic_service.py`
  - 已补历史回填迁移：
    - `20260412_000039_backfill_raw_tushare_stock_basic_from_legacy_raw.py`
  - 已执行范围收敛（移除无关示例表与代码）：
    - 删除非 `stock_basic` 的多源 demo 模型与路由
    - 新增迁移：`20260412_000040_drop_non_stock_multi_source_demo_tables.py`

- 2026-04-12 包 4 启动（框架骨架完成，无示例数据集扩展）
  - 已完成 resolution 骨架：
    - `ResolutionPolicyEngine`（`primary/fallback/field_merge/freshness_first`）
    - `ConflictScorer`
    - `ResolutionPolicyStore`（读取 `foundation.dataset_resolution_policy` / `dataset_source_status`）
    - `ResolutionRegistry` 与 resolver 协议
  - 已完成测试：
    - `tests/test_resolution_policy_engine.py`
    - `tests/test_resolution_conflict_scorer.py`
  - 已完成首个接线：
    - `sync_stock_basic` 的 `source=all` 发布改为通过 ResolutionPolicyEngine 统一决策
    - 单源模式（`tushare` / `biying`）保持原有行为，降低切换风险

- 2026-04-12 包 5 启动（最小发布层抽离）
  - 已新增发布层骨架：
    - `src/foundation/serving/publish_service.py`
    - `src/foundation/serving/builders/security_serving_builder.py`
    - `src/foundation/serving/builders/registry.py`（builder 注册机制）
    - `src/foundation/serving/targets.py`（dataset -> target DAO 映射）
    - `ServingPublishPlan` 与两段式发布（plan -> execute）骨架，支持 `dry_run` 与空发布保护
    - serving 模型命名空间开始切换到 `core_serving`（首个：`security_serving`）
    - 已补齐 `core_serving` 命名空间迁移（不改表结构）：
      - `equity_daily_bar`
      - `equity_adj_factor`
      - `equity_daily_basic`
      - `stk_period_bar`
      - `stk_period_bar_adj`
      - `index_daily_serving`
      - `index_weekly_serving`
      - `index_monthly_serving`
    - builder 通用结果类型 `ServingBuildResult`，并支持可选溯源字段透传（仅当目标列存在时写入）：
      - `resolution_mode`
      - `resolution_policy_version`
      - `candidate_sources`
      - `resolution_audit`
    - 通用融合模板 `ResolutionServingBuilder`（按业务键聚合 + 策略融合）
    - 首批可复用模板 builder：
      - `EquityDailyBarServingBuilder`
      - `EquityAdjFactorServingBuilder`
      - `EquityDailyBasicServingBuilder`
      - `IndexDailyServingBuilder`
      - `IndexWeeklyServingBuilder`
      - `IndexMonthlyServingBuilder`
    - `SERVING_TARGET_DAO_ATTR` 新增预置映射：
      - `equity_daily_bar -> equity_daily_bar`
      - `equity_adj_factor -> equity_adj_factor`
      - `equity_daily_basic -> equity_daily_basic`
      - `index_daily -> index_daily_serving`
      - `index_weekly -> index_weekly_serving`
      - `index_monthly -> index_monthly_serving`
  - 已完成 `sync_stock_basic` 接线：
    - `source=all` 通过 `ServingPublishService` 发布到 `core.security_serving`
  - 已完成测试：
    - `tests/test_security_serving_builder.py`
    - `tests/test_serving_publish_service.py`
    - `tests/test_serving_builder_registry.py`
    - `tests/test_serving_provenance_fields.py`
    - `tests/test_serving_builder_atomic_publish.py`
    - `tests/test_resolution_serving_builder.py`
    - `tests/test_index_serving_builders.py`
    - `tests/test_serving_targets.py`

- 2026-04-12 停机迁移工具（阶段1）补充
  - 已新增 CLI：`goldenshare bootstrap-raw-tushare`
  - 能力：`raw.*` 镜像建表到 `raw_tushare.*`，并可选执行全量迁移
  - 参数：
    - `--create-only`（只建表）
    - `--table/-t`（指定表）
    - `--drop-if-exists`（重建模式）
  - 已完成测试：
    - `tests/test_raw_tushare_bootstrap_service.py`

---

## 包 1：基础骨架与元数据

目标：建立 source/policy/status 元数据与 connector 抽象。

代码 TODO：
1. 新增模型文件：
- `/Users/congming/github/goldenshare/src/foundation/models/meta/source_registry.py`
- `/Users/congming/github/goldenshare/src/foundation/models/meta/dataset_resolution_policy.py`
- `/Users/congming/github/goldenshare/src/foundation/models/meta/dataset_source_status.py`
- `/Users/congming/github/goldenshare/src/foundation/models/meta/__init__.py`

2. 注册模型：
- 修改 `/Users/congming/github/goldenshare/src/foundation/models/all_models.py`

3. 新增 connector 抽象与工厂：
- `/Users/congming/github/goldenshare/src/foundation/connectors/base.py`
- `/Users/congming/github/goldenshare/src/foundation/connectors/tushare_connector.py`
- `/Users/congming/github/goldenshare/src/foundation/connectors/biying_connector.py`
- `/Users/congming/github/goldenshare/src/foundation/connectors/factory.py`
- `/Users/congming/github/goldenshare/src/foundation/connectors/__init__.py`

4. Alembic：
- 新增 migration：`/Users/congming/github/goldenshare/alembic/versions/*_create_foundation_meta_tables.py`

5. 测试：
- `/Users/congming/github/goldenshare/tests/test_source_registry_models.py`
- `/Users/congming/github/goldenshare/tests/test_source_connector_factory.py`
- `/Users/congming/github/goldenshare/tests/test_source_connector_contract.py`

---

## 包 2：分源 Raw 落地

目标：同一业务键多来源并存，不覆盖。

代码 TODO：
1. 新增分源 raw 模型（首批股票主链路）：
- `/Users/congming/github/goldenshare/src/foundation/models/raw_multi/raw_tushare_equity_daily_bar.py`
- `/Users/congming/github/goldenshare/src/foundation/models/raw_multi/raw_biying_equity_daily_bar.py`
- `/Users/congming/github/goldenshare/src/foundation/models/raw_multi/raw_tushare_equity_adj_factor.py`
- `/Users/congming/github/goldenshare/src/foundation/models/raw_multi/raw_biying_equity_adj_factor.py`
- `/Users/congming/github/goldenshare/src/foundation/models/raw_multi/raw_tushare_equity_daily_basic.py`
- `/Users/congming/github/goldenshare/src/foundation/models/raw_multi/raw_biying_equity_daily_basic.py`
- `/Users/congming/github/goldenshare/src/foundation/models/raw_multi/__init__.py`

2. DAO 扩展：
- `/Users/congming/github/goldenshare/src/foundation/dao/factory.py`
- 新增 `/Users/congming/github/goldenshare/src/foundation/dao/raw_multi_writer.py`

3. 同步层接入 source 路由：
- `/Users/congming/github/goldenshare/src/foundation/services/sync/resource_sync.py`

4. Alembic：
- 新增 migration：`/Users/congming/github/goldenshare/alembic/versions/*_create_raw_multi_tables.py`

5. 测试：
- `/Users/congming/github/goldenshare/tests/test_raw_multi_writer.py`
- `/Users/congming/github/goldenshare/tests/test_raw_multi_schema_mapping.py`

---

## 包 3：Std 标准化层

目标：不同 source 字段统一到标准事实层。

代码 TODO：
1. 新增 std 模型：
- `/Users/congming/github/goldenshare/src/foundation/models/core_multi/equity_daily_bar_std.py`
- `/Users/congming/github/goldenshare/src/foundation/models/core_multi/equity_adj_factor_std.py`
- `/Users/congming/github/goldenshare/src/foundation/models/core_multi/equity_daily_basic_std.py`
- `/Users/congming/github/goldenshare/src/foundation/models/core_multi/stk_period_bar_std.py`
- `/Users/congming/github/goldenshare/src/foundation/models/core_multi/stk_period_bar_adj_std.py`
- `/Users/congming/github/goldenshare/src/foundation/models/core_multi/__init__.py`

2. 新增 normalizer：
- `/Users/congming/github/goldenshare/src/foundation/normalization/equity_daily_bar_normalizer.py`
- `/Users/congming/github/goldenshare/src/foundation/normalization/equity_adj_factor_normalizer.py`
- `/Users/congming/github/goldenshare/src/foundation/normalization/equity_daily_basic_normalizer.py`
- `/Users/congming/github/goldenshare/src/foundation/normalization/stk_period_bar_normalizer.py`
- `/Users/congming/github/goldenshare/src/foundation/normalization/__init__.py`

3. Alembic：
- 新增 migration：`/Users/congming/github/goldenshare/alembic/versions/*_create_core_multi_std_tables.py`

4. 测试：
- `/Users/congming/github/goldenshare/tests/test_normalizer_equity_daily_bar.py`
- `/Users/congming/github/goldenshare/tests/test_normalizer_error_isolation.py`

---

## 包 4：融合引擎（Resolution）

目标：primary/fallback/field_merge/freshness_first 策略可执行。

代码 TODO：
1. 新增策略引擎与 resolver：
- `/Users/congming/github/goldenshare/src/foundation/resolution/policy_engine.py`
- `/Users/congming/github/goldenshare/src/foundation/resolution/conflict_scorer.py`
- `/Users/congming/github/goldenshare/src/foundation/resolution/resolvers/equity_daily_bar_resolver.py`
- `/Users/congming/github/goldenshare/src/foundation/resolution/resolvers/equity_adj_factor_resolver.py`
- `/Users/congming/github/goldenshare/src/foundation/resolution/resolvers/equity_daily_basic_resolver.py`
- `/Users/congming/github/goldenshare/src/foundation/resolution/resolvers/__init__.py`

2. service 编排接入：
- `/Users/congming/github/goldenshare/src/foundation/services/sync/sync_equity_daily_service.py`
- `/Users/congming/github/goldenshare/src/foundation/services/sync/sync_adj_factor_service.py`
- `/Users/congming/github/goldenshare/src/foundation/services/sync/sync_daily_basic_service.py`

3. 测试：
- `/Users/congming/github/goldenshare/tests/test_resolution_policy_primary_fallback.py`
- `/Users/congming/github/goldenshare/tests/test_resolution_policy_field_merge.py`
- `/Users/congming/github/goldenshare/tests/test_resolution_policy_freshness_first.py`
- `/Users/congming/github/goldenshare/tests/test_resolution_conflict_audit.py`

---

## 包 5：Serving 发布层

目标：对上统一读取，原子发布可回滚。

代码 TODO：
1. 新增 serving 模型：
- `/Users/congming/github/goldenshare/src/foundation/models/core_serving/equity_daily_bar.py`
- `/Users/congming/github/goldenshare/src/foundation/models/core_serving/equity_adj_factor.py`
- `/Users/congming/github/goldenshare/src/foundation/models/core_serving/equity_daily_basic.py`
- `/Users/congming/github/goldenshare/src/foundation/models/core_serving/stk_period_bar.py`
- `/Users/congming/github/goldenshare/src/foundation/models/core_serving/stk_period_bar_adj.py`
- `/Users/congming/github/goldenshare/src/foundation/models/core_serving/__init__.py`

2. 新增 builder：
- `/Users/congming/github/goldenshare/src/foundation/serving/builders/equity_daily_bar_builder.py`
- `/Users/congming/github/goldenshare/src/foundation/serving/builders/equity_adj_factor_builder.py`
- `/Users/congming/github/goldenshare/src/foundation/serving/builders/equity_daily_basic_builder.py`
- `/Users/congming/github/goldenshare/src/foundation/serving/builders/__init__.py`
- `/Users/congming/github/goldenshare/src/foundation/serving/publish_service.py`

3. Biz 查询切换：
- `/Users/congming/github/goldenshare/src/biz/queries/quote_query_service.py`

4. Alembic：
- 新增 migration：`/Users/congming/github/goldenshare/alembic/versions/*_create_core_serving_tables.py`

5. 测试：
- `/Users/congming/github/goldenshare/tests/test_serving_builder_atomic_publish.py`
- `/Users/congming/github/goldenshare/tests/test_serving_builder_equity_daily_bar.py`
- `/Users/congming/github/goldenshare/tests/test_serving_provenance_fields.py`
- 修改 `/Users/congming/github/goldenshare/tests/web/test_quote_api.py`

---

## 包 6：指标链路多源化

目标：指标与行情同源一致，状态不串线。

代码 TODO：
1. 指标 std + serving 模型：
- `/Users/congming/github/goldenshare/src/foundation/models/core_multi/indicator_macd_std.py`
- `/Users/congming/github/goldenshare/src/foundation/models/core_multi/indicator_kdj_std.py`
- `/Users/congming/github/goldenshare/src/foundation/models/core_multi/indicator_rsi_std.py`
- `/Users/congming/github/goldenshare/src/foundation/models/core_serving/ind_macd.py`
- `/Users/congming/github/goldenshare/src/foundation/models/core_serving/ind_kdj.py`
- `/Users/congming/github/goldenshare/src/foundation/models/core_serving/ind_rsi.py`

2. 迁移与服务改造：
- `/Users/congming/github/goldenshare/src/foundation/models/core/indicator_state.py`（增加 `source_key`）
- `/Users/congming/github/goldenshare/src/foundation/services/sync/sync_equity_indicators_service.py`

3. Alembic：
- 新增 migration：`/Users/congming/github/goldenshare/alembic/versions/*_indicator_state_add_source_key.py`
- 新增 migration：`/Users/congming/github/goldenshare/alembic/versions/*_create_indicator_multi_serving_tables.py`

4. 测试：
- `/Users/congming/github/goldenshare/tests/test_indicator_multi_source_state.py`
- `/Users/congming/github/goldenshare/tests/test_indicator_resolution_consistency.py`
- 修改 `/Users/congming/github/goldenshare/tests/test_sync_equity_indicators_service.py`

---

## 包 7：停机迁移实施包

目标：一次性停机迁移可执行、可验收、可回滚。

代码 TODO：
1. 迁移脚本：
- `/Users/congming/github/goldenshare/src/scripts/migrate_to_multi_source_v1.py`
- `/Users/congming/github/goldenshare/src/scripts/rebuild_core_serving_v1.py`

2. 对账脚本：
- `/Users/congming/github/goldenshare/src/scripts/reconcile_multi_source_rowcount.py`
- `/Users/congming/github/goldenshare/src/scripts/reconcile_multi_source_key_coverage.py`
- `/Users/congming/github/goldenshare/src/scripts/reconcile_multi_source_date_range.py`

3. 发布脚本补充：
- `/Users/congming/github/goldenshare/scripts/deploy-systemd.sh`
- `/Users/congming/github/goldenshare/scripts/release.sh`（若已使用）

4. 测试：
- `/Users/congming/github/goldenshare/tests/integration/test_migration_rowcount_reconcile.py`
- `/Users/congming/github/goldenshare/tests/integration/test_migration_key_coverage_reconcile.py`
- `/Users/congming/github/goldenshare/tests/integration/test_migration_date_range_reconcile.py`
- `/Users/congming/github/goldenshare/tests/integration/test_migration_quote_smoke.py`

---

## 包 8：Ops 多源契约落地（已定稿方案）

目标：Ops 支持多源多层综合运维。

代码 TODO：
1. 新增模型：
- `/Users/congming/github/goldenshare/src/ops/models/ops/dataset_layer_snapshot.py`
- `/Users/congming/github/goldenshare/src/ops/models/ops/probe_rule.py`
- `/Users/congming/github/goldenshare/src/ops/models/ops/resolution_policy.py`
- `/Users/congming/github/goldenshare/src/ops/models/ops/resolution_policy_revision.py`

2. 扩展 execution 维度：
- `/Users/congming/github/goldenshare/src/ops/models/ops/job_execution.py`
- `/Users/congming/github/goldenshare/src/ops/models/ops/job_execution_step.py`
- `/Users/congming/github/goldenshare/src/ops/schemas/execution.py`
- `/Users/congming/github/goldenshare/src/ops/queries/execution_query_service.py`

3. freshness 改造为总览+明细：
- `/Users/congming/github/goldenshare/src/ops/queries/freshness_query_service.py`
- `/Users/congming/github/goldenshare/src/operations/services/dataset_status_snapshot_service.py`
- `/Users/congming/github/goldenshare/src/ops/models/ops/dataset_status_snapshot.py`
- `/Users/congming/github/goldenshare/src/ops/schemas/freshness.py`
- `/Users/congming/github/goldenshare/src/ops/api/freshness.py`

4. Probe API 与服务：
- `/Users/congming/github/goldenshare/src/ops/api/probe_rules.py`
- `/Users/congming/github/goldenshare/src/ops/schemas/probe_rule.py`
- `/Users/congming/github/goldenshare/src/ops/services/probe_rule_service.py`
- `/Users/congming/github/goldenshare/src/operations/runtime/probe_executor.py`

5. 策略中心 API：
- `/Users/congming/github/goldenshare/src/ops/api/resolution_policies.py`
- `/Users/congming/github/goldenshare/src/ops/schemas/resolution_policy.py`
- `/Users/congming/github/goldenshare/src/ops/services/resolution_policy_service.py`

6. 前端页面重组：
- `/Users/congming/github/goldenshare/frontend/src/app/shell.tsx`
- `/Users/congming/github/goldenshare/frontend/src/pages/ops-data-status-page.tsx`（升级三层视图）
- `/Users/congming/github/goldenshare/frontend/src/pages/ops-source-management-page.tsx`（新增）
- `/Users/congming/github/goldenshare/frontend/src/pages/ops-policy-center-page.tsx`（新增）
- `/Users/congming/github/goldenshare/frontend/src/pages/ops-operations-release-page.tsx`（新增，承接 today/automation/manual/tasks）

7. Alembic：
- 新增 migration：`/Users/congming/github/goldenshare/alembic/versions/*_ops_multi_source_tables_v1.py`
- 新增 migration：`/Users/congming/github/goldenshare/alembic/versions/*_job_execution_add_stage_source_policy.py`

8. 测试：
- 新增 `tests/web/test_ops_source_management_api.py`
- 新增 `tests/web/test_ops_policy_center_api.py`
- 新增 `tests/web/test_ops_probe_rule_api.py`
- 修改 `/Users/congming/github/goldenshare/tests/web/test_ops_freshness_api.py`
- 修改 `/Users/congming/github/goldenshare/tests/test_ops_models.py`

---

## 执行规则

1. 每个任务包必须“代码 + 测试”同包完成。  
2. 每个任务包完成后先跑对应测试，再进入下一包。  
3. 不得跨包引入未定义 schema 依赖。  
4. 若与契约冲突，先改文档再改代码。  
