# 板块日线字段与存储说明：dc_daily / ths_daily

更新时间：2026-09-10。本文合并原 DC 主键修复与 THS 估值字段扩表方案，区分当前实现和历史证据。范围仅为 Prod 数据集；不改变代码、字段、输入、UI、工作流或 DG 链路，不授权清表、迁移及历史回补。

## 1. 当前链路对照

两者定义均在 [board_hotspot.py](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/board_hotspot.py)，不能因为同属板块日线就套用同一种存储方式。

| 项目 | dc_daily | ths_daily |
| --- | --- | --- |
| 数据含义 | 东方财富板块日线 | 同花顺板块日线 |
| 业务身份 | `ts_code + trade_date + category` | `ts_code + trade_date` |
| 关键字段 | `category` 必填，参与主键、冲突键与质量检查 | `pe_ttm/pb_mrq` 为可空估值字段，不参与身份 |
| Raw | `raw_tushare.dc_daily` | `raw_tushare.ths_daily` |
| Serving | `core_serving.dc_daily`：直接读 Raw 的普通视图 | `core_serving.ths_daily`：独立表 |
| 写入路径 | `raw_only_upsert`，只写 Raw | `raw_core_upsert`，写 Raw 与 Serving |
| 交付类型 | `raw_with_serving_view` | `single_source_serving` |
| 运营过滤 | `ts_code/idx_type`；无 `category` 输入 | `ts_code`；无估值字段输入 |

两者均支持单日/区间维护，按交易日规划，当前分页配置均为 `offset_limit`、每页 2,000 行、计划最多 5,000 units。区间请求由 planner 生成日期锚点，builder 逐日传 `trade_date`；不是直接把运营区间原样交给源端。

DC 的 `idx_type` 支持行业、概念、地域多选，显式多选会拆成多个 unit；默认未选择时没有三类自动扇出，单日无过滤计划只有一个 unit。请求实现见 [DC/THS builder](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)。

本地接口资料：

- doc_id=382：[东财板块行情](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/打板专题数据/0382_东财概念板块行情.md)。
- doc_id=260：[同花顺板块指数行情](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/打板专题数据/0260_同花顺板块指数行情.md)。资料单次上限写 3,000 行，不等于本仓配置页长；当前采用 2,000 行。

日期/执行的通用规则见[日期模型指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)与[执行计划说明](/Users/congming/github/goldenshare/docs/architecture/dataset-execution-plan-refactor-plan-v1.md)，完整源字段以 Definition 与上述资料为准。

## 2. DC：分类是业务身份，Serving 不再复制数据

`category` 为 `varchar(32)`，在 Raw 主键及 Definition 的 `conflict_columns` 中均占一列。`ts_code/trade_date/category` 都是必填字段，缺少分类的行不能作为身份完整的数据入库。`idx_type` 是请求过滤，`category` 是返回事实，不能互相替代。

模型见 [RawDcDaily](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_dc_daily.py) 与 [DcDaily](/Users/congming/github/goldenshare/src/foundation/models/core/dc_daily.py)。Raw 保留 `trade_date` 和 `(trade_date, category)` 索引；Serving ORM 仍用于查询映射，其主键/索引 metadata 不代表数据库里还有一张对应物理表或视图自带索引。

[20260828_000154 迁移](/Users/congming/github/goldenshare/alembic/versions/20260828_000154_make_dc_daily_raw_view.py)将 Serving 改成显式列视图：

- 13 个业务字段直接来自 Raw，不另存副本。
- `created_at/updated_at` 均投影自 Raw 的 `fetched_at`。
- 独立 trigger 拒绝向 Serving 执行 INSERT/UPDATE/DELETE。
- 迁移校验身份、结构、依赖和数据等价；不重建 Raw，禁止 CASCADE 和自动 downgrade。

因此下游查询仍应保留完整三字段身份；不得恢复向 Serving 表写入，也不能仅凭两字段相同折叠分类数据。后续迁移设计与验收细节统一见[Raw 直出一期 LLD](/Users/congming/github/goldenshare/docs/governance/prod-postgresql-raw-direct-serving-phase-one-lld-v1.md)，本文不复制操作步骤。

## 3. THS：估值可空，仍按两层写入

当前 source_fields 与 decimal_fields 均包含 `pe_ttm/pb_mrq`；[RawThsDaily](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_ths_daily.py)和 [ThsDaily](/Users/congming/github/goldenshare/src/foundation/models/core/ths_daily.py)均用可空 `numeric(18,6)` 保存。

必填字段仍只有 `ts_code/trade_date`。估值指标不是业务身份，返回空值不应仅因此拒绝整行，也不应补成零。其余字段和主键不因估值扩表改变。

旧 Console 曾补充导出字段白名单，但相应代码和测试已清退，只能从 Git 追溯。旧白名单、导出 Parquet 或清理旧分区不再是本数据集的现行验收要求；这不删除 Prod 的估值字段，也不要求修改现行 DG 数据集。

## 4. 必要历史证据

### DC 主键修复与后续视图切换

原 2026-05-08 修复记录保留的源端探测范围为 `2025-01-01..2025-01-31`，显式请求行业、概念、地域三类：

| 历史探测口径 | 结果 |
| --- | ---: |
| 读取行数 | 17,704 |
| 两字段唯一身份 | 17,488 |
| 两字段重复组 / 重复行数 | 216 / 216 |
| 重复组中分类冲突 / 业务字段冲突 | 216 / 179 |
| 三字段唯一身份 / 重复组 | 17,704 / 0 |

样例 `BK0425.DC + 20250102` 可同时存在行业、概念两行。该证据解释了为什么不能退回两字段身份；当时已经折叠的数据不能仅靠增加一列无损还原。

旧探测报告已按临时产物策略移除；[探测测试](/Users/congming/github/goldenshare/tests/integration/test_tushare_dc_daily_identity_probe.py)仍在，以上是历史记录，不是本次重新请求的结果。原主键修复迁移见 [20260508_000100](/Users/congming/github/goldenshare/alembic/versions/20260508_000100_rebuild_dc_daily_category_identity.py)。

后续[存储治理记录 §2.17](/Users/congming/github/goldenshare/docs/governance/prod-postgresql-storage-space-optimization-program-v2.md)记载：2026-08-28 已完成 Serving 视图切换；2026-08-29 的 TaskRun 9747/9773 对目标日 2026-08-28 各读取/保存 1,031 行，拒绝、去重、重试均为零，Raw/view 逐字段一致，M3b 关闭。这是带日期的既有生产证据，本次没有重新检查生产状态。

### THS 估值扩表

原文记录 2026-05-08 已实施估值扩表，对应 [20260508_000101](/Users/congming/github/goldenshare/alembic/versions/20260508_000101_rebuild_ths_daily_valuation_fields.py)。当前代码确认字段已接入，但不能据此推断所有历史日期都已补齐；原先未保存的估值数据需在确认缺口并另获授权后从源端补取。

DC/THS 原方案中的 2026-05-08 清表重建批准只属于当次迁移，不是今天再次执行的许可。两份旧全文均可从 Git 提交 `b8811098` 追溯。

## 5. 验证入口与边界

当前离线测试入口：

- [DC Raw 视图专项](/Users/congming/github/goldenshare/tests/test_dc_daily_raw_view_m1.py)：存储合同、默认单 unit、显式分类扇出、字段/身份/索引，以及离线迁移 SQL 和拒绝自动降级。
- [Definition 测试](/Users/congming/github/goldenshare/tests/test_dataset_definition_registry.py)、[resolver 测试](/Users/congming/github/goldenshare/tests/test_dataset_action_resolver.py)、[normalizer 测试](/Users/congming/github/goldenshare/tests/test_dataset_normalizer.py)：字段、参数与归一化回归。

离线 DDL 检查不等于真实数据库迁移或生产验收；本轮未执行真实探测、同步或迁移。

如后续单独批准真实验收，须限定同一日期/过滤范围，对照源端行数、身份去重、拒绝原因和目标数据；upsert 保存量不等于全表净增量。DC 对照 Raw 与视图的完整三字段身份和业务值；THS 对照两层字段及空值语义。不能以两张全表的总行数相等替代本次范围验收，也不能把正常估值空值判成缺字段。
