# 生产 PostgreSQL raw 直出一期低层设计 v1

- 版本：v1
- 状态：P1-B0-M2 `moneyflow_mkt_dc` 隔离 PostgreSQL 实证已通过；尚未授权生产迁移；其余 11 个数据集尚未编码
- 更新时间：2026-08-24
- 上位方案：[生产 PostgreSQL 存储空间优化治理专项 v2](/Users/congming/github/goldenshare/docs/governance/prod-postgresql-storage-space-optimization-program-v2.md)
- 目标：把一期 12 个无业务转换的 raw/core_serving 双写数据集收敛为“raw 唯一物理事实表 + 原 serving 名称只读 view”，预计释放约 3.305 GiB SSD

## 0. 边界与完成定义

本文定义一期实施合同，并记录已获授权完成的 P1-B0-M1 代码证据与 M2 隔离 PostgreSQL 实证；它不构成部署、生产 migration 或生产 TaskRun 授权。

一期完成必须同时满足：

1. 每个数据集只写现有 `raw_tushare` 物理表；
2. 原 `core_serving` relation 名称、业务列名、业务列类型和查询结果保持不变；
3. 所有已知 Biz、Ops、QTF、Lake Console 和 DG 只读消费者通过结果及性能验收；
4. serving view 的任何 `INSERT/UPDATE/DELETE` 都被数据库明确拒绝；
5. 每个数据集在切换前完成全量业务字段双向差集，差异必须为 0；
6. 每个数据集独立 migration、独立发布、独立验收，上一项通过后才进入下一项；
7. 不改 Tushare fields、分页、日期模型、planner、unit、自动任务时间策略和 Lake 文件；
8. 生产物理表释放量与目标 serving 表切换前大小一致，扣除本轮新增 raw 索引后再计算净收益。

以下任一项不满足，该数据集必须从当次发布中退出，不能用删除差异行、回写 raw、放宽测试或 `DROP ... CASCADE` 绕过。

## 1. 读透明性的准确口径

### 1.1 对当前已知业务与数据湖消费者的结论

在保留原 `core_serving` relation 名、业务列名和类型，并通过查询性能验收后，当前仓库内已知只读消费者可以做到代码无感：

1. Biz/ORM 仍引用原 SQLAlchemy serving 模型；模型生成的 schema-qualified SQL 不变；
2. QTF 仍读取 `core_serving.dc_daily`，无需改输入契约；
3. DG 的 `dc_board_source_probe` 仍读取 `core_serving.dc_daily`，无需改 SQL；
4. Lake Console 的 `prod-raw-db` 对一期中 10 个已接入数据集本来就读取 `raw_tushare`，来源不变；
5. `stk_auction_o/stk_auction_c` 当前未进入 Lake Console `prod-raw-db` 白名单，也未发现 DG 直接消费者，本轮不会新增 Lake 能力；
6. Ops 手动任务和 schedule 的 action key、时间输入、filters 及请求语义不变；已有 schedule 不需要删除或重新创建。

### 1.2 不能笼统称为“所有下游完全无感”的部分

relation 从物理表变为 view 后，下列物理或治理事实必然变化：

| 事实 | 切换后的变化 | 当前处理口径 |
| --- | --- | --- |
| relation OID | `DROP TABLE` + `CREATE VIEW` 会生成新 OID | 禁止把 OID 当业务合同；执行前清点仓库外消费者 |
| `relkind` | 从普通表 `r` 变为普通 view `v` | catalog/DDL 工具必须知情；普通 SELECT 不受影响 |
| 主键、唯一约束、表索引 | view 自身不再拥有，查询计划下推到 raw 索引 | raw 索引必须覆盖原 serving 索引，并做前后计划对比 |
| nullability catalog | view 的 catalog 可不再表达底表 `NOT NULL` | 结果值不允许新增空值；依赖 catalog nullability 的工具需单独验收 |
| `created_at/updated_at` | 改由 raw `fetched_at` 投影 | 当前已知 Biz/QTF/Lake/DG 不消费这两个字段；不承诺历史审计时间值逐行不变 |
| owner/ACL/comment | drop 后不会自动继承 | migration 必须恢复 owner、非 owner SELECT grants、relation/column comments |
| 写入行为 | serving 不再是写入目标 | Definition 和数据库拒写 trigger 双重防护 |

因此，本设计承诺的是“当前已知业务数据读取合同透明”，不是“物理表身份透明”。若仓库外消费者会读取 `created_at/updated_at`、检查 OID/relkind/约束，或向 serving 写数据，必须在对应数据集实施前登记；未登记即不能宣称该消费者无感。

## 2. 当前代码与生产事实

### 2.1 写入链事实

当前 12 个数据集都使用 `DatasetWriter.write()` 的 `raw_core_upsert` 分支。`_write_raw_and_core()` 会把同一个 `NormalizedBatch` 分别按 raw/serving ORM 列过滤后写入两层；12 个 Definition 的 `serving_conflict_resolution_policy` 均为 `none`。

这证明当前主链没有额外业务转换，但不自动证明历史数据没有漂移。生产数据仍必须独立对账。

目标 Definition storage contract 固定为：

```text
raw_dao_name = <现有 raw DAO>
core_dao_name = <同一个 raw DAO>
target_table = raw_tushare.<raw_table>
delivery_mode = raw_with_serving_view
layer_plan = raw->serving_view
raw_table = raw_tushare.<raw_table>
serving_table = core_serving.<原 serving 名称>
write_path = raw_only_upsert
conflict_columns = 保持现有值
```

不修改 `DatasetWriter`、resolver、request builder、source client、normalizer、schedule capability resolver 或前端生产代码。

### 2.2 一期固定名单与内部批次

下表的物理大小和精确行数来自 2026-08-23 生产只读复核。大小会变化，执行前必须重新采样；名单和顺序只有经本文修订才能改变。

| 批次 | 顺序 | 数据集 | raw → serving | 业务身份/冲突键 | serving 大小 | raw/serving 精确行数 | 当前直接消费者摘要 |
| --- | ---: | --- | --- | --- | ---: | ---: | --- |
| P1-B0 | 1 | `moneyflow_mkt_dc` | `raw_tushare.moneyflow_mkt_dc` → `core_serving.market_moneyflow_dc` | `trade_date` | 0.2 MiB | 812 / 812 | Wealth 市场资金、市场总览；Lake raw |
| P1-B1 | 2 | `moneyflow_ind_ths` | `raw_tushare.moneyflow_ind_ths` → `core_serving.industry_moneyflow_ths` | `(trade_date, ts_code)` | 9.3 MiB | 42,030 / 42,030 | Ops/freshness；Lake raw |
| P1-B1 | 3 | `moneyflow_cnt_ths` | `raw_tushare.moneyflow_cnt_ths` → `core_serving.concept_moneyflow_ths` | `(trade_date, ts_code)` | 41.9 MiB | 181,560 / 181,560 | Ops/freshness；Lake raw |
| P1-B1 | 4 | `margin` | `raw_tushare.margin` → `core_serving.equity_margin` | `(trade_date, exchange_id)` | 0.3 MiB | 1,143 / 1,143 | Ops/freshness；Lake raw；1 个 active schedule |
| P1-B2 | 5 | `moneyflow_ind_dc` | `raw_tushare.moneyflow_ind_dc` → `core_serving.board_moneyflow_dc` | `(trade_date, content_type, name)` | 83.5 MiB | 336,175 / 336,175 | Wealth 板块概览/热度；Lake raw |
| P1-B2 | 6 | `dc_daily` | `raw_tushare.dc_daily` → `core_serving.dc_daily` | `(ts_code, trade_date, category)` | 154.0 MiB | 629,993 / 629,993 | Wealth、QTF、DG source probe；Lake raw |
| P1-B2 | 7 | `suspend_d` | `raw_tushare.suspend_d` → `core_serving.equity_suspend_d` | 写入冲突键 `row_key_hash`；物理 PK `id` | 211.9 MiB | 640,481 / 640,481 | Wealth 指数/板块/连板、市场情绪；Lake raw |
| P1-B3 | 8 | `stk_auction_o` | `raw_tushare.stk_auction_o` → `core_serving.equity_auction_open` | `(ts_code, trade_date)` | 361.9 MiB | 2,161,633 / 2,161,633 | Ops/freshness；未发现当前 Lake/DG 读取 |
| P1-B3 | 9 | `stk_auction_c` | `raw_tushare.stk_auction_c` → `core_serving.equity_auction_close` | `(ts_code, trade_date)` | 364.1 MiB | 2,227,843 / 2,227,843 | Ops/freshness；未发现当前 Lake/DG 读取 |
| P1-B3 | 10 | `moneyflow_ths` | `raw_tushare.moneyflow_ths` → `core_serving.equity_moneyflow_ths` | `(trade_date, ts_code)` | 460.9 MiB | 2,050,984 / 2,050,984 | Ops/freshness；Lake raw |
| P1-B4 | 11 | `moneyflow_dc` | `raw_tushare.moneyflow_dc` → `core_serving.equity_moneyflow_dc` | `(trade_date, ts_code)` | 1,072.8 MiB | 4,120,988 / 4,120,988 | Ops/freshness；Lake raw |
| P1-B4 | 12 | `stk_limit` | `raw_tushare.stk_limit` → `core_serving.equity_stk_limit` | `(ts_code, trade_date)` | 623.5 MiB | 4,569,303 / 4,569,303 | 市场情绪/走查；Lake raw |
|  |  | **合计** |  |  | **3,548,766,208 B，约 3.305 GiB** |  |  |

批次只表达风险顺序，不表示允许合并 migration。生产发布单位始终是“一个数据集、一个 Alembic revision、一次维护窗口、一次验收”。

### 2.3 已完成与尚未完成的生产证明

已完成：

1. 12 组精确 `count(*)` 全部一致；
2. raw/serving 业务列名称、类型、空值约束在当前生产表一致；
3. raw 的主键和二级索引签名覆盖 serving；所有相关索引有效且 ready；
4. 未发现外键、外部 view/materialized view 依赖、用户 trigger 或 RLS policy；
5. 当前开放 TaskRun 为 0；仅 `margin` 存在 1 个 active schedule；
6. owner 均为 `goldenshare_user`；部分 relation 的非 owner SELECT grant 不同，migration 必须逐对象恢复。

尚未完成：

1. 除先前已验证的 `moneyflow_mkt_dc`、`margin` 外，其余 10 组尚未完成全历史业务字段双向 `EXCEPT ALL`；
2. 生产前后代表性查询的 `EXPLAIN (ANALYZE, BUFFERS)` 尚未执行；
3. 仓库外 SQL、BI、人工脚本和依赖 relation catalog 的工具尚未完成签字；
4. `suspend_d` 的 raw/serving `id` 必须逐行一致，不能只比较 `row_key_hash`；
5. 浏览器/API、QTF 和 DG 的切换后真实验收尚未执行。

因此，名单已固定，但每项当前状态仍是“候选”；未通过第 7 节门禁前禁止 drop serving 表。

### 2.4 当前代码消费者清单

本轮 CodeGraph 索引状态为 current，覆盖 2,684 个文件、46,844 个节点和 107,885 条边；对 `DatasetWriter`、`DatasetStorageDefinition`、12 个 ORM/DAO/Definition 及跨子系统调用者做了影响面审计，并用精确代码搜索补齐 CodeGraph 对动态 Definition/ORM 引用识别不足的部分。

当前必须进入回归的已知直接读取入口：

1. `moneyflow_mkt_dc`：
   - `src/biz/queries/wealth/market/money_flow/money_flow_query.py`
   - `src/biz/queries/wealth/market/money_flow/money_flow_state_query.py`
   - `src/biz/queries/wealth/market/summary/summary_metrics_query.py`
   - `src/biz/queries/wealth/market/summary/summary_state_query.py`
   - `src/biz/services/wealth/market/summary/summary_status_resolver.py`
2. `moneyflow_ind_dc/dc_daily`：
   - `src/biz/queries/wealth/market/sector_overview/sector_metrics_query.py`
   - `src/biz/queries/wealth/market/sector_overview/sector_overview_state_query.py`
   - `src/biz/services/wealth/market/sector_overview/sector_heat_source_query.py`
   - `qtf/adapters/prod/sector_source_adapter.py`
   - `lake_console/orchestrator/src/orchestrator/defs/asset_guards/dc_board_source_probe.py`
3. `suspend_d/stk_limit`：
   - `src/biz/queries/wealth/market/index_detail/index_detail_query.py`
   - `src/biz/queries/wealth/market/sector_overview/sector_member_query.py`
   - `src/biz/queries/wealth/market/streak_ladder/streak_ladder_query.py`
   - `src/biz/services/wealth/market/sector_overview/effective_a_stock_pool_query.py`
   - `src/biz/services/wealth/market/sector_overview/sector_heat_source_query.py`
   - `src/biz/services/market_mood_calculator.py`
   - `src/biz/services/market_mood_walkforward_validation_service.py`
4. Lake Console：`lake_console/backend/app/services/prod_raw_db.py` 当前对一期 10 个数据集直接映射 `raw_tushare`；对应 trade-date 同步策略位于 `lake_console/backend/app/sync/strategies/prod_db_trade_date.py`。两个 auction 数据集不在当前映射中。
5. Ops/freshness：通过 `DatasetDefinition.storage.target_table` 的现有投影链读取目标 relation，不为一期维护第二套数据集白名单。

当前没有发现 `ServingPublishService` 对这 12 个 dataset key 的 target mapping，也没有发现仓库内显式 serving DAO DML 旁路。实施每个数据集前仍要重新跑相同审计；此处不能替代对仓库外消费者的运营登记。

## 3. 硬需求追溯账本

| ID | 硬需求 | 实现落点 | 正向门禁 | 反向门禁 | 当前状态 |
| --- | --- | --- | --- | --- | --- |
| RD-001 | raw 成为唯一物理事实表 | 3 个 Definition 文件、现有 `raw_only_upsert` | writer 仅调用 raw DAO | serving DAO 零调用 | P1-B0 M1 writer 测试和 M2 物理切换已通过；生产尚未切换 |
| RD-002 | 原 serving 名称和业务列合同不变 | 每数据集独立 migration、原 serving ORM | ORM/SQL 查询结果一致 | 禁止改 Biz/QTF/DG relation 名 | P1-B0 M2 以 812 行受控数据完成双向差集、字段与 relation 合同实证 |
| RD-003 | serving 禁止写入 | Definition + DB INSTEAD OF reject trigger | SELECT 正常 | INSERT/UPDATE/DELETE 均失败 | P1-B0 M2 三类 DML 均以 SQLSTATE `55000` 拒绝 |
| RD-004 | 全量事实无差异 | 生产维护窗口分块对账 | 两层差集均为 0 | 任一差异阻断 migration | 2/12 已证 |
| RD-005 | raw 索引覆盖查询 | raw ORM index 声明、生产索引、计划基准 | 代表查询使用等价索引 | 计划/延迟退化阻断 | P1-B0 M2 代表查询由 serving 索引透明切换为 raw 索引；生产计划仍需复验 |
| RD-006 | 现有 schedule 不重建 | action key/date/capability 不变 | 暂停后原 schedule 恢复 | 禁止自动 seed/重建 | 待生产验收 |
| RD-007 | Lake/DG 已知读取合同不变 | Lake raw 白名单、DG `dc_board_source_probe` | 既有测试与真实只读查询通过 | 禁止切换 Lake source 或写 Lake | 静态审计完成 |
| RD-008 | 不改变源端请求 | Definition 只改 storage | connector/request 测试不变 | 禁止改 fields/分页/date model | P1-B0 Definition/plan 反向测试已通过 |
| RD-009 | 一个数据集一个发布单元 | 独立 revision/commit/deploy 记录 | 上一项验收后进入下一项 | 禁止批量 drop | 已固定 |
| RD-010 | owner/grant/comment 可追溯 | migration 动态快照与恢复 | 非 owner SELECT 权限一致 | 未知 grant/comment 阻断 | P1-B0 M2 已实证 owner、PUBLIC/普通/可转授权 SELECT、relation/列 comment 恢复 |
| RD-011 | Ops 观测改读 raw | `target_table` 派生、freshness registry | 新 TaskRun/freshness 读 raw | 历史 TaskRun 不回写 | P1-B0 projection 自动化测试已通过 |
| RD-012 | 失败不破坏 raw | 同事务 DDL、禁止自动 downgrade | 提交前失败原子回滚 | 禁止清表/删 raw | P1-B0 M2 在 drop 后、create view 时注入失败，旧版本、原表 OID/数据/索引/权限全部回滚 |

## 4. Definition、writer、ORM 与 DAO 设计

### 4.1 Definition 修改范围

只修改：

1. `src/foundation/datasets/definitions/moneyflow.py`
2. `src/foundation/datasets/definitions/board_hotspot.py`
3. `src/foundation/datasets/definitions/market_equity.py`

每个数据集只改第 2.1 节列出的 storage facts。identity、domain、source、date model、input model、planning、normalization、capabilities、observability、quality、transaction、completeness 全部保持不变。

### 4.2 writer 与 DAO

1. 复用现有 `DatasetWriter._write_raw_only_upsert()`；不新增 write path，不修改通用 writer；
2. `core_dao_name` 指向同一个 raw DAO，使 `_resolve_write_daos()` 只解析到 raw DAO；
3. serving DAO attr 可以保留在 `DAOFactory` 供现有管理/只读代码兼容，但任何 ingestion Definition 不得再引用它；
4. `ServingPublishService` 当前 target registry 不包含这 12 个 dataset key；测试必须固化该事实；
5. 静态扫描必须证明不存在显式 `insert/update/delete` serving model、serving DAO `bulk_upsert/bulk_insert` 或仓库内脚本旁路写入。

### 4.3 ORM 与索引事实对账

原 serving ORM 继续保留，作为 view 的只读映射，不改业务列。raw ORM 必须与当前生产索引事实一致。

当前以下 raw ORM 没有声明生产中已存在的二级索引，实施对应数据集时必须补齐 ORM metadata，但 migration 不重复创建已存在索引：

1. `raw_moneyflow_mkt_dc.py`
2. `raw_moneyflow_ind_ths.py`
3. `raw_moneyflow_cnt_ths.py`
4. `raw_moneyflow_ind_dc.py`
5. `raw_dc_daily.py`
6. `raw_moneyflow_ths.py`
7. `raw_moneyflow_dc.py`

`raw_margin.py`、`raw_suspend_d.py`、`raw_stk_auction_o.py`、`raw_stk_auction_c.py`、`raw_stk_limit.py` 当前 ORM 已声明相关二级索引。

不新增跨数据集 ORM 基类、基金式共享框架或通用 Definition 生成器。

## 5. serving view 物理合同

### 5.1 显式列投影

每个 view 必须显式列出全部 serving 列，禁止 `SELECT *`。业务列从 raw 同名投影；审计列固定为：

```sql
fetched_at AS created_at,
fetched_at AS updated_at
```

业务列集合固定为：

| 数据集 | serving 业务列 |
| --- | --- |
| `moneyflow_mkt_dc` | `trade_date, close_sh, pct_change_sh, close_sz, pct_change_sz, net_amount, net_amount_rate, buy_elg_amount, buy_elg_amount_rate, buy_lg_amount, buy_lg_amount_rate, buy_md_amount, buy_md_amount_rate, buy_sm_amount, buy_sm_amount_rate` |
| `margin` | `trade_date, exchange_id, rzye, rzmre, rzche, rqye, rqmcl, rzrqye, rqyl` |
| `moneyflow_ind_ths` | `trade_date, ts_code, industry, lead_stock, close, pct_change, company_num, pct_change_stock, close_price, net_buy_amount, net_sell_amount, net_amount` |
| `moneyflow_cnt_ths` | `trade_date, ts_code, name, lead_stock, close_price, pct_change, industry_index, company_num, pct_change_stock, net_buy_amount, net_sell_amount, net_amount` |
| `moneyflow_ind_dc` | `trade_date, content_type, name, ts_code, pct_change, close, net_amount, net_amount_rate, buy_elg_amount, buy_elg_amount_rate, buy_lg_amount, buy_lg_amount_rate, buy_md_amount, buy_md_amount_rate, buy_sm_amount, buy_sm_amount_rate, buy_sm_amount_stock, rank` |
| `dc_daily` | `ts_code, trade_date, category, close, open, high, low, change, pct_change, vol, amount, swing, turnover_rate` |
| `suspend_d` | `id, row_key_hash, ts_code, trade_date, suspend_timing, suspend_type` |
| `stk_auction_o/stk_auction_c` | `ts_code, trade_date, close, open, high, low, vol, amount, vwap` |
| `moneyflow_ths` | `trade_date, ts_code, name, pct_change, latest, net_amount, net_d5_amount, buy_lg_amount, buy_lg_amount_rate, buy_md_amount, buy_md_amount_rate, buy_sm_amount, buy_sm_amount_rate` |
| `stk_limit` | `ts_code, trade_date, pre_close, up_limit, down_limit` |
| `moneyflow_dc` | `trade_date, ts_code, name, pct_change, close, net_amount, net_amount_rate, buy_elg_amount, buy_elg_amount_rate, buy_lg_amount, buy_lg_amount_rate, buy_md_amount, buy_md_amount_rate, buy_sm_amount, buy_sm_amount_rate` |

raw 的 `api_name/fetched_at/raw_payload` 不作为 serving 业务列暴露；`fetched_at` 只用于上述两个审计列投影。

### 5.2 数据库拒写保险丝

仅依赖 Definition 防止误写不够，因为生产应用角色同时是 relation owner。P1-B0 migration 新增一个稳定、无数据集语义的数据库函数：

```text
core_serving.reject_raw_direct_serving_view_dml()
```

函数只做一件事：对 raw-backed serving view 的 DML 抛出明确异常。每个 view 都挂一个 `INSTEAD OF INSERT OR UPDATE OR DELETE` trigger。它不参与 SELECT、不读取配置、不包含数据集白名单。

这是一期唯一新增的共享地基。可以共享的原因是：

1. 合同只有“serving view 禁止写”，不包含任何数据集字段、日期或业务规则；
2. 某个数据集的变更不会改变函数；
3. 函数失效只影响误写防护，不影响正常 SELECT；
4. 每个 view 的 trigger 仍由自身 migration 独立创建和验证。

如果隔离 PostgreSQL 证明目标 view 天然不可更新，也仍保留负向 DML 测试；只有另行评审后才能取消 trigger，不允许凭经验省略。

### 5.3 owner、ACL 和 comment

migration 在 drop 前读取并暂存当前：

1. relation owner；
2. relation comment 和每个 serving 列 comment；
3. 非 owner 的 `SELECT` grants；
4. PUBLIC 是否拥有任何权限。

create view 后必须：

1. 恢复原 owner；
2. 默认 `REVOKE ALL FROM PUBLIC`；
3. 恢复原非 owner SELECT grants；
4. 恢复 relation/column comments；
5. 验证不存在非预期 DML grant。

物理表 owner 原有的 TRUNCATE/TRIGGER 等表权限不能、也不应伪装成 view 权限；当前应用通过 owner 身份读取，数据库拒写 trigger 负责阻断 DML。

## 6. migration 设计

### 6.1 独立 revision

每个数据集一个自包含 Alembic revision。编码当天必须重新读取真实 Alembic head，`down_revision` 只能接真实 head。

revision 不 import 后续可能变化的业务 helper；view SQL、列合同、preflight 和 ACL/comment 恢复逻辑都保存在自身 migration 中。P1-B0 创建的拒写函数是稳定数据库对象，后续 revision 只引用其数据库名称。

### 6.2 事务内 preflight

drop 前必须 fail-closed 验证：

1. raw relation 为普通物理表 `r`，serving relation 为普通物理表 `r`；
2. raw/serving owner 与维护窗口基线一致；
3. 业务列名称、顺序、类型和目标 nullability 白名单一致；
4. raw 主键、唯一索引和二级索引全部 valid/ready，并覆盖 serving 查询签名；
5. serving 没有外键、外部 view/materialized view、函数依赖、用户 trigger 或 RLS policy；
6. 不存在目标 relation 锁和长事务；按固定顺序先对 raw、再对 serving 获取 `SHARE` 锁，允许普通 SELECT，但阻断两层 DML；
7. maintenance runner 已提供同窗口预对账证据，并在上述锁仍由当前 DDL 事务持有时，重新完成全范围业务字段分块双向差集；最终差异必须为 0，不能只复用事务外报告；
8. 最终对账通过后，把 serving 锁升级为 `ACCESS EXCLUSIVE`；升级超时则整个事务回滚，不排队等待；
9. P1-B1 之后，拒写函数必须已存在且 owner/定义符合预期；
10. 任何未知 ACL、comment、依赖或 relation kind 都停止 migration。

### 6.3 原子 relation 切换

同一个 PostgreSQL DDL 事务内顺序固定为：

1. `SET LOCAL lock_timeout = '15s'`；
2. 执行第 6.2 节 relation/依赖 preflight；
3. 按 raw → serving 固定顺序获取 `SHARE` 锁，完成事务内最终全量分块双向差集；
4. 快照 owner、SELECT grants 和 comments；
5. 把 serving 锁升级为 `ACCESS EXCLUSIVE`；
6. `DROP TABLE core_serving.<target>`，禁止 `CASCADE`；
7. `CREATE VIEW core_serving.<target> AS SELECT ... FROM raw_tushare.<raw>`；
8. 恢复 owner、grants、comments；
9. 创建拒写 trigger；
10. 验证 `relkind='v'`、列合同和 trigger；
11. 提交。

提交前任何失败由 PostgreSQL 原子回滚，原物理 serving 表恢复。migration 不执行 Tushare 请求、不改 raw 数据、不删除 raw 表。

### 6.4 downgrade

禁止自动 downgrade 创建空 serving 表。提交后的回退必须单独授权，以 raw 为来源建立新物理 serving 表、恢复索引/owner/grants、完成全量核对，再切回双写 Definition。

## 7. 数据等价和性能门禁

### 7.1 全量数据等价

维护窗口内停止对应 writer、暂停目标 schedule，并确认开放 TaskRun 为 0 后，先做一次事务外预对账；migration 事务再持有两层 `SHARE` 锁重复最终对账。两次均按自然月分块执行：

1. raw/serving `count(*)`；
2. 业务身份键唯一数；
3. 显式业务列双向 `EXCEPT ALL`；
4. 差异样本最多 20 行，只用于定位，不进入自动修复；
5. 每块记录起止日期、两层行数、两向差异数、耗时和 statement timeout；
6. 月块超时或超过内存预算时只允许缩小为日块，禁止扩大；
7. 对账工作集必须有界：`work_mem` 必须固定；迁移角色有参数权限时可同时限制 `temp_file_limit`，没有该权限时必须根据字段最大宽度设置持锁后的明确行数上限，超过上限立即失败。P1-B0 固定为两层各不超过 5,000 行、`work_mem=16MB`，不得为迁移向业务角色追加超管级参数权限。

事务内最终对账的所有月块必须在同一事务、同一组 relation 锁下完成。不得为了缩短锁时间把它拆成多个可被写入穿插的事务；若锁持有时间或读 I/O 超出该数据集维护窗口预算，该项停止并重新评审，不能降级为只比行数或抽样。

对账投影包含第 5.1 节全部业务列；`suspend_d` 必须包含 `id` 和 `row_key_hash`。`api_name/fetched_at/raw_payload/created_at/updated_at` 属于已审计的系统列，不进入业务差集。

任一块出现 raw-only、serving-only、内容不同、业务身份重复或 `suspend_d.id` 不一致，该数据集立即退出一期当前发布。禁止在本专项中删除、覆盖或修补差异。

### 7.2 查询计划和时延

每个有直接消费者的数据集必须从真实查询提取代表性 SQL。切换前后在同一维护窗口比较：

1. 返回字段、行数、排序和结果 hash 完全一致；
2. `EXPLAIN (ANALYZE, BUFFERS)` 能下推到 raw 的等价 PK/索引；
3. 代表查询重复样本的中位耗时不得退化超过 20%，且不得突破现有 API/DG timeout；
4. shared read、temp read/write 或顺序扫描出现不可解释放大即停止；
5. `dc_daily` 必须额外验证 QTF bounded range query 和 DG 单日 completion probe；
6. `suspend_d/stk_limit` 必须额外验证市场情绪的日期范围 join；
7. 无当前业务消费者的数据集至少验证 point date、range date 和主键查询。

20% 是发布阻断线，不是性能优化目标。任何结果差异都是 0 容忍。

### 7.3 数据湖性能测算表

| 项 | 一期口径 |
| --- | --- |
| 生产 relation 数 | 12 个 raw 物理表保持不变；12 个 serving 表逐项替换为 view；一次只处理 1 个 |
| 最大单表当前行数 | `stk_limit` 4,569,303 行；`moneyflow_dc` 4,120,988 行 |
| Lake 文件/partition 写入 | 0；本专项不 materialize asset、不写 Parquet、不写 ClickHouse |
| 生产 DB 导出路径 | 10 个现有 Lake Console 数据集继续读 `raw_tushare`；0 次源路径切换 |
| DG 直接核心读取 | 1 条已知路径：`dc_board_source_probe -> core_serving.dc_daily` |
| Tushare 请求 | migration 与数据对账为 0；每项切换后仅在独立授权下做 1 个既有最小维护 TaskRun |
| DB 对账读取 | 按自然月有界分块；每块 2 个 count/identity 汇总与双向业务字段差集 |
| 写入边界 | DDL 单事务；正常同步仍沿用现有 unit 事务，不改变 Lake 写入边界 |
| 临时空间 | 每个 migration 必须选择可由最小权限角色执行的有界策略；P1-B0 以固定宽度字段、两层各 5,000 行硬上限和 `work_mem=16MB` 保证完整对账工作集有界，未来大表另行设计分块与参数权限，禁止直接复用该阈值 |
| 不可接受阈值 | 任何数据差异、未知消费者、未命中等价索引、>20% 时延退化、DG/API timeout、临时文件超限 |

本轮没有运行 `dg`、Dagster job、sensor、asset check 或正式 Lake 读取；这里只做静态消费者审计。

## 8. 每个数据集的实施步骤

以下步骤对 12 个数据集逐项重复，不能跨项合并：

### S0：编码前复审

1. 同步 CodeGraph 并复查 Definition、writer、DAO、模型、Biz/Ops/QTF/Lake/DG 消费者；
2. 重新读取 Alembic head；
3. 生产只读复核 relation、索引、owner/ACL/comment、依赖、任务、schedule、磁盘和锁；
4. 更新该数据集的生产等价与查询基线证据。

### S1：代码与 migration

1. 只修改该数据集的 Definition storage；
2. 必要时补 raw ORM index metadata；
3. 新增该数据集独立 migration；
4. 补 Definition、writer、迁移、freshness、catalog 和拒写测试；
5. 不修改其它一期数据集。

P1-B0-M1 于 2026-08-24 完成，实际落点固定为：

1. `moneyflow_mkt_dc` Definition 只改变 storage contract，改用现有 `raw_only_upsert`；15 个显式 source fields、日期模型、单元规划、3,000 行分页、能力和请求参数保持不变；
2. `RawMoneyflowMktDc` ORM 补齐生产既有 `trade_date` 二级索引 metadata，没有新建或搬迁物理索引；
3. 独立 revision `20260824_000146` 连接编码时真实 head `20260823_000145`，只处理 `moneyflow_mkt_dc`；
4. migration 在同一事务内执行 relation/字段/主键/索引/依赖/ACL preflight、持锁双向 `EXCEPT ALL`、原子 relation 切换、owner/SELECT grant/comment 恢复和数据库 DML 拒写；禁止 `CASCADE`、禁止删除 raw、禁止自动 downgrade；
5. Alembic 离线 PostgreSQL SQL 已完整渲染，并增加了对 SQLAlchemy 绑定参数误解析的回归断言；
6. Definition、执行 plan、隐藏 filter 反例、raw-only writer、ORM 索引、freshness、ServingPublish 旁路、migration 顺序/拒写/回退及 Wealth 两个直接 API 消费者的定向测试已通过；
7. 本阶段没有连接或写入任何 PostgreSQL，不代表 migration SQL、ACL 恢复、trigger 拒写、原子回滚或查询计划已获得真实数据库证明，这些仍属于 S2/M2。

### S2：隔离 PostgreSQL 验证

1. 创建结构和数据都受控的隔离库；严禁让 `.env.web.local` 覆盖隔离连接；
2. 应用 migration，核验 view 列合同、owner/grants/comments 和拒写 trigger；
3. 验证 DDL 中途失败会原子恢复原表；
4. 验证 raw-only writer、重复同步、freshness、TaskRun target 和 view 即时可见；
5. 对代表查询做结果及计划对比。

P1-B0-M2 于 2026-08-24 在临时、仅 Unix socket 可访问的 PostgreSQL 18.4 隔离实例完成。实例、两套数据库和 812 行数据均为本轮受控创建，没有连接 Prod、调用 Tushare、部署服务或创建任务。

实测结论如下：

1. migration `20260823_000145 -> 20260824_000146` 成功；切换前后 raw、serving/view 均为 812 行，业务字段双向 `EXCEPT ALL` 为 0，view 的审计时间投影差异为 0；
2. 首次运行发现 PostgreSQL 18 会把 `NOT NULL` 约束登记为 `pg_constraint.contype='n'`。原 preflight 将其误判为额外约束并在 DDL 前安全退出；修正为仅允许主键和已由 `pg_attribute.attnotnull` 精确核验的 `NOT NULL` 目录项，并增加反向测试后重跑通过；
3. relation owner、relation/列 comment、PUBLIC SELECT、普通角色 SELECT 和带 grant option 的 SELECT 均完整恢复；三个非 owner 角色均可查询 view；
4. 对 serving view 执行 `INSERT`、`UPDATE`、`DELETE` 均失败，SQLSTATE 均为 `55000`，错误明确指向禁止写 raw-backed serving view；
5. 对 raw 表插入后 view 立即可见，更新后 view 立即返回新值，删除后 view 行数立即恢复，证明没有复制延迟或第二份物理事实；
6. 代表性日期查询切换前使用 `core_serving.idx_market_moneyflow_dc_trade_date`，切换后下推使用 `raw_tushare.idx_raw_tushare_moneyflow_mkt_dc_trade_date`；两者 total cost 均为 8.29，隔离样本执行时间分别为 0.017 ms 和 0.015 ms。该小样本只证明计划形态，不替代生产数据量下的时延门禁；
7. 在 migration 已取得排他锁并删除旧 serving 表后，于 `CREATE VIEW` 注入失败。事务回滚后 Alembic 版本仍为 `20260823_000145`，旧 relation 仍为表、OID 不变、812 行 raw/serving 数据及 metadata/index 均不变，拒写函数和 trigger 均未残留；
8. 隔离实例已停止并删除；M2 不产生可复用环境，也不构成生产 migration 授权。

### S3：生产维护窗口

1. 暂停该数据集 schedule；停止会领取该数据集的 worker；Web 只读可保留，但 relation 切换可能短暂等待锁；
2. 完成最终全量分块双向差集；
3. 部署含该数据集 raw-only Definition 的版本，worker 继续停止；
4. 应用该数据集 migration；
5. 回收 Web、QTF 和其它直接消费者的长连接池，避免旧 relation OID/缓存计划跨越切换窗口；无法确认连接已回收时不得进入业务验收；
6. 完成 relation、view、ACL/comment、DML 拒绝、查询结果和性能验收；
7. 启动 worker，执行 1 个受控最小维护 TaskRun，完成 fetched/normalized/written/rejected/raw/view 五段对账；
8. 恢复原 schedule；没有 schedule 的数据集不创建新 schedule；
9. 观察首个正常任务和业务查询，再决定是否进入下一数据集。

### S4：文档证据

将 revision、部署 commit、TaskRun ID、对账结果、查询计划、磁盘释放量和残余风险写回 v2；未验收项不得标完成。

## 9. 测试清单

### 9.1 Foundation/Ops

1. 12 个 Definition 的 raw-only/view storage contract；
2. 参数化 writer 测试证明每项只调用 raw DAO 一次，serving DAO 零调用；
3. 保持原 conflict columns，覆盖 `dc_daily` 和 `suspend_d` 特殊键；
4. freshness projection 自动改读 raw target，并能观察 `trade_date`；
5. dataset card 显示“原始数据直出”，raw/serving 两个 relation 均正确；
6. manual action、schedule capability、date completeness 和 source release 事实不变；
7. `ServingPublishService` 不存在这 12 个 target mapping；
8. 静态扫描禁止任何一期 serving DML。

### 9.2 migration

1. 非 PostgreSQL 不执行；PostgreSQL 正确切换；
2. raw/serving relation kind 错误时失败；
3. 字段、索引、依赖、ACL/comment 出现未知状态时失败；
4. 不包含 `CASCADE`；
5. view 为显式列投影且 `created_at/updated_at` 均来自 `fetched_at`；
6. owner、SELECT grants 和 comments 恢复；
7. INSERT/UPDATE/DELETE 均被明确拒绝；
8. downgrade 明确拒绝自动重建空表；
9. 每个 revision 只处理一个数据集。

### 9.3 直接消费者

1. Wealth 市场资金/市场总览；
2. Wealth 板块概览、板块热度、指数详情、板块成员、连板天梯；
3. 市场情绪计算和 walk-forward validation；
4. QTF sector input；
5. Lake Console `prod-raw-db` query builder；
6. DG `dc_board_source_probe` 静态及隔离查询测试；
7. 不运行正式 Dagster instance，不触发正式 asset/job/sensor。

## 10. 发布停止条件与回退

出现任一情况立即停止当前项和后续批次：

1. 全量差异非 0、业务身份重复、`suspend_d.id` 不一致；
2. 需要 `CASCADE` 才能 drop；
3. 未知 owner/grant/comment、外部依赖、trigger、RLS 或写入调用；
4. serving view 接受 DML；
5. 代表查询结果、排序、hash 不一致；
6. 查询未下推等价索引、时延退化超过门禁或 DG/API timeout；
7. 存在开放 TaskRun、无法暂停的 schedule、目标锁或长事务；
8. root/WAL 可用空间低于当次预检门槛，或对账触发临时文件限制；
9. migration 与 raw-only Definition 不能在同一维护窗口闭环。

原 raw 表始终保留，因此本方案不会删除唯一源事实。DDL 提交前失败由事务回滚；提交后回退是独立 forward migration，不自动 downgrade、不清表、不从 Tushare 重拉。

## 11. 不做事项

一期不做：

1. 不处理 `daily_basic`、`dc_member`、`stock_st` 或缺 raw 索引的其它候选；
2. 不把一期 raw 表迁 HDD；它们继续留在 SSD，避免 serving view 查询直接转为机械盘 I/O；
3. 不改 `stk_mins`；
4. 不改 source fields、请求参数、分页、日期/unit 设计或自动任务时间；
5. 不创建、删除或重新配置 schedule；
6. 不修改 Lake Parquet、ClickHouse、Dagster asset/check/event；
7. 不做共享 writer/DAO/Definition 重构；
8. 不保证 relation OID、relkind、PK/index catalog 或历史审计时间值不变。

## 12. P1-B0 下一阶段仍需确认的事项

1. “业务读取合同透明，但物理 relation 身份和 `created_at/updated_at` 历史值不透明”的边界已作为 M1 实现口径固定；
2. 仓库外 SQL/BI/人工脚本是否存在，仍需由运营在 P1-B0 生产维护窗口前完成登记；
3. P1-B0-M2 已完成，但只证明受控 PostgreSQL 18.4 隔离环境中的迁移、权限、拒写、即时可见、计划形态和事务原子性；不替代生产数据、锁、空间、连接池和真实查询验收；
4. 生产迁移仍需独立授权；每个后续数据集也需单独授权，不能用本 LLD 一次授权 12 次 drop。

## 13. 依据

1. `src/foundation/ingestion/writer.py`
2. `src/foundation/datasets/definitions/moneyflow.py`
3. `src/foundation/datasets/definitions/board_hotspot.py`
4. `src/foundation/datasets/definitions/market_equity.py`
5. `src/foundation/dao/factory.py`
6. `src/ops/dataset_definition_projection.py`
7. `src/ops/queries/freshness_query_service.py`
8. `lake_console/backend/app/services/prod_raw_db.py`
9. `lake_console/orchestrator/src/orchestrator/defs/asset_guards/dc_board_source_probe.py`
10. `qtf/adapters/prod/sector_source_adapter.py`
11. `alembic/versions/20260803_000124_make_cyq_perf_nineturn_raw_views.py`
12. [数据集开发说明模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)
13. [Dagster 数据管道性能治理规范](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-data-pipeline-performance-governance.md)
