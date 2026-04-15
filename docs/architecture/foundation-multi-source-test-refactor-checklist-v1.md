# Foundation 多源改造测试清单（按任务包绑定）v1

更新时间：2026-04-12  
适用范围：Foundation 多源改造（不含 Ops UI 细化）  
关联文档：[foundation-multi-source-upgrade-and-migration-v1.md](/Users/congming/github/goldenshare/docs/architecture/foundation-multi-source-upgrade-and-migration-v1.md)

---

## 1. 目标

本清单用于保证“架构升级 + 迁移切换”期间测试先行，避免回归：

1. 新增能力有测试护栏。  
2. 旧能力行为不退化。  
3. 停机迁移有可执行验收脚本。  

---

## 2. 测试分层与执行门槛

1. 单元测试（快）
- Connector/Normalizer/Policy/Resolver 的纯逻辑。
- 要求：本地秒级执行，可频繁跑。

2. 集成测试（中）
- `raw -> std -> resolution -> serving` 端到端链路。
- 要求：覆盖多源冲突、单源服务、字段缺失场景。

3. 回归测试（稳）
- 保持现有接口和业务行为（Quote/Ops）。
- 要求：既有测试通过率不下降。

4. 迁移验收测试（重）
- 停机窗口执行的对账与切换校验。
- 要求：全通过才能开机。

---

## 3. 按任务包绑定的测试改造清单

## 任务包 1：基础骨架与配置（Connector + 元数据）

新增测试：
- `tests/test_source_registry_models.py`
  - `source_registry`/`dataset_resolution_policy`/`dataset_source_status` 主键与约束。
- `tests/test_source_connector_factory.py`
  - `source_key -> connector` 映射正确。
  - 未注册来源抛出明确错误。
- `tests/test_source_connector_contract.py`
  - connector 返回统一结构（records + meta）。

需要改造的既有测试：
- [test_sync_registry.py](/Users/congming/github/goldenshare/tests/test_sync_registry.py)
  - 新增 source-aware 注册断言（不破坏旧 resource 注册）。

通过门槛：
- 未接 Biying 时，旧 Tushare 路径全绿。
- 引入 connector 抽象后，现有 sync 测试不报行为变化。

## 任务包 2：分源 Raw 落地

新增测试：
- `tests/test_raw_multi_writer.py`
  - 同一 `(ts_code, trade_date)` 不同 `source_key` 可并存。
  - 相同 payload_hash 幂等行为符合预期。
- `tests/test_raw_multi_schema_mapping.py`
  - 分源表命名与写入路由正确。

需要改造的既有测试：
- 各 `test_sync_*_service.py`
  - 将“写 raw”断言升级为“按 source 写入对应 raw 分区/分源表”。

通过门槛：
- 两源同日同股票不覆盖。
- 原有 raw 单源写入语义在 `source=tushare` 下等价。

## 任务包 3：Std 标准化层

新增测试：
- `tests/test_normalizer_equity_daily_bar.py`
  - 字段映射、类型精度、单位归一（`amount/vol`）正确。
  - 缺失字段按规则处理（置空/丢弃/默认值）。
- `tests/test_normalizer_error_isolation.py`
  - 单条脏数据隔离，不阻断整批。

需要改造的既有测试：
- [test_transform_services.py](/Users/congming/github/goldenshare/tests/test_transform_services.py)
  - 增加 source-aware 标准化路径断言。

通过门槛：
- `core_multi.*_std` 产出字段一致、可追溯 `source_key + rule_version`。

## 任务包 4：Resolution 融合引擎

新增测试：
- `tests/test_resolution_policy_primary_fallback.py`
- `tests/test_resolution_policy_field_merge.py`
- `tests/test_resolution_policy_freshness_first.py`
- `tests/test_resolution_conflict_audit.py`

必测场景：
- A 主 B 兜底。  
- B 覆盖 A（字段级，含 `amount`）。  
- 同优先级冲突 tie-break。  
- 单源可服务（只有 Biying 也能出 serving）。  

通过门槛：
- 每个业务键融合后最多一条。
- 决策可解释（来源与策略版本可追溯）。

## 任务包 5：Serving 发布层

新增测试：
- `tests/test_serving_builder_atomic_publish.py`
  - 构建失败不替换旧快照。
- `tests/test_serving_builder_equity_daily_bar.py`
  - serving 字段完整、主键唯一。
- `tests/test_serving_provenance_fields.py`
  - `resolved_source_key/resolved_policy_version` 回填正确。

需要改造的既有测试：
- [tests/web/test_quote_api.py](/Users/congming/github/goldenshare/tests/web/test_quote_api.py)
  - 将数据装载路径从旧 `core.*` 迁移到 `core_serving.*`（保留语义断言不变）。

通过门槛：
- Biz 查询只依赖 serving 也能通过现有 Quote 主流程测试。

## 任务包 6：指标链路多源化

新增测试：
- `tests/test_indicator_multi_source_state.py`
  - `indicator_state` 增加 `source_key` 后不会串状态。
- `tests/test_indicator_resolution_consistency.py`
  - 指标来源与行情来源一致（同 source chain）。

需要改造的既有测试：
- [test_sync_equity_indicators_service.py](/Users/congming/github/goldenshare/tests/test_sync_equity_indicators_service.py)
  - 增加 source-aware 因子读取与状态写入断言。

通过门槛：
- 前/后复权指标在多源条件下仍保持可重复计算。

## 任务包 7：停机迁移实施包

新增测试（可脚本化）：
- `tests/integration/test_migration_rowcount_reconcile.py`
- `tests/integration/test_migration_key_coverage_reconcile.py`
- `tests/integration/test_migration_date_range_reconcile.py`
- `tests/integration/test_migration_quote_smoke.py`

迁移脚本验收：
- 旧表 -> `*_multi` -> `core_serving` 一次性完成。
- 对账失败时返回非 0，阻止开机。

通过门槛：
- 所有对账脚本全绿，关键接口冒烟通过。

## 任务包 8：读路径切换与收口

新增测试：
- `tests/web/test_quote_api_serving_only.py`
  - 验证查询仅依赖 serving。
- `tests/test_legacy_table_read_guard.py`
  - 防止新代码回退读取旧 `core.*`。

需要改造的既有测试：
- [tests/web/test_ops_freshness_api.py](/Users/congming/github/goldenshare/tests/web/test_ops_freshness_api.py)
  - 后续 Ops 契约定稿后补 source 维度断言（本轮先预留）。

通过门槛：
- 读路径切换后，既有业务接口回归通过率不下降。

---

## 4. 现有测试集需要重点保护的文件

1. Quote 核心回归：
- [test_quote_api.py](/Users/congming/github/goldenshare/tests/web/test_quote_api.py)

2. Ops 规格与新鲜度：
- [test_ops_specs.py](/Users/congming/github/goldenshare/tests/test_ops_specs.py)
- [test_ops_freshness_api.py](/Users/congming/github/goldenshare/tests/web/test_ops_freshness_api.py)

3. 同步服务与指标：
- [test_sync_registry.py](/Users/congming/github/goldenshare/tests/test_sync_registry.py)
- [test_sync_equity_indicators_service.py](/Users/congming/github/goldenshare/tests/test_sync_equity_indicators_service.py)

---

## 5. 执行顺序（测试先行）

1. 先补任务包 1-3 的单元测试骨架。  
2. 再做任务包 4-5 的集成测试。  
3. 最后做任务包 6-8 的迁移与回归收口。  

原则：
- 每完成一个任务包，必须同时完成对应测试并过门槛，才能进入下一个任务包。  

---

## 6. 待 Ops 契约输入后补充项（占位）

1. Ops 对 source 维度的观测字段清单。  
2. Ops 数据状态“融合口径 vs 来源口径”断言清单。  
3. Ops 任务配置中的 source/policy 约束测试。  

以上三项将在 Ops 契约文档确认后补入本清单。
