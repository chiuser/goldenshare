# 生产 PostgreSQL raw 直出一期低层设计 v1

- 版本：v1
- 状态：P1-B0-M3 已通过；P1-B1 首项 `moneyflow_ind_ths` M1/M2 与 M3a 生产切换、即时验收已通过，M3b 首个正常 schedule 观察待闭环；该观察不阻塞后续数据集另行授权的 M1/M2，但未闭环前不得进入下一次生产 M3a
- 更新时间：2026-08-24
- 上位方案：[生产 PostgreSQL 存储空间优化治理专项 v2](/Users/congming/github/goldenshare/docs/governance/prod-postgresql-storage-space-optimization-program-v2.md)
- 目标：把一期 12 个无业务转换的 raw/core_serving 双写数据集收敛为“raw 唯一物理事实表 + 原 serving 名称只读 view”，预计释放约 3.305 GiB SSD

## 0. 边界与完成定义

本文定义一期实施合同，并记录已获授权完成的 P1-B0-M1～M3 以及 P1-B1 首项 M0、M1、M2、M3a 证据；M3b 尚待证据闭环，已完成阶段不构成后续数据集开发、部署、生产 migration 或 TaskRun 授权。

一期完成必须同时满足：

1. 每个数据集只写现有 `raw_tushare` 物理表；
2. 原 `core_serving` relation 名称、业务列名、业务列类型和查询结果保持不变；
3. 所有已知 Biz、Ops、QTF、Lake Console 和 DG 只读消费者通过结果及性能验收；
4. serving view 的任何 `INSERT/UPDATE/DELETE` 都被数据库明确拒绝；
5. 每个数据集在切换前完成全量业务字段双向差集，差异必须为 0；
6. 每个数据集独立 migration、独立发布、独立验收；任何时刻最多一个数据集进入生产 M3a，后续项的 M1/M2 可在单独授权下并行准备，但不能把前项授权外推为后项生产授权；
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

下表的物理大小基线来自 2026-08-23；P1-B1 三项行数、relation 与任务事实已于 2026-08-24 刷新。大小会变化，执行前必须重新采样；名单和顺序只有经本文修订才能改变。

| 批次 | 顺序 | 数据集 | raw → serving | 业务身份/冲突键 | serving 大小 | raw/serving 精确行数 | 当前直接消费者摘要 |
| --- | ---: | --- | --- | --- | ---: | ---: | --- |
| P1-B0 | 1 | `moneyflow_mkt_dc` | `raw_tushare.moneyflow_mkt_dc` → `core_serving.market_moneyflow_dc` | `trade_date` | 0.2 MiB | 812 / 812 | Wealth 市场资金、市场总览；Lake raw |
| P1-B1 | 2 | `moneyflow_ind_ths` | `raw_tushare.moneyflow_ind_ths` → `core_serving.industry_moneyflow_ths` | `(trade_date, ts_code)` | 9.3 MiB | 42,030 / 42,030 | Ops/freshness；Lake raw；active 每日资金工作流 |
| P1-B1 | 3 | `moneyflow_cnt_ths` | `raw_tushare.moneyflow_cnt_ths` → `core_serving.concept_moneyflow_ths` | `(trade_date, ts_code)` | 41.9 MiB | 181,560 / 181,560 | Ops/freshness；Lake raw；active 每日资金工作流 |
| P1-B1 | 4 | `margin` | `raw_tushare.margin` → `core_serving.equity_margin` | `(trade_date, exchange_id)` | 0.3 MiB | 1,146 / 1,146 | Ops/freshness；Lake raw；active 固定源端 probe |
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
5. 当前开放 TaskRun 为 0；P1-B1 中 `moneyflow_ind_ths/moneyflow_cnt_ths` 由 1 个 active 工作流 schedule 覆盖，`margin` 存在 1 个 active probe schedule；
6. owner 均为 `goldenshare_user`；部分 relation 的非 owner SELECT grant 不同，migration 必须逐对象恢复。
7. P1-B0 已在生产完成最终 812 行全字段双向差集、relation 切换、权限与拒写、真实查询计划、连接池回收及最小 TaskRun 验收；详见第 8 节。
8. P1-B1 三项已完成全字段对账：行业与概念按 24 个自然月逐窗双向差集均为 0，margin 全量双向差集为 0。
9. P1-B1 首项 `moneyflow_ind_ths` 已在生产完成 revision 147、42,030 行 raw-backed view、拒写、查询计划、连接池、TaskRun `9217` 与 schedule 原样恢复的 M3a 即时验收；首个正常 schedule 观察属于 M3b，只约束下一次生产 M3a，不约束另行授权的 M1/M2，详见第 8 节。

尚未完成：

1. 除 `moneyflow_mkt_dc`、`moneyflow_ind_ths`、`moneyflow_cnt_ths`、`margin` 外，其余 8 组尚未完成全历史业务字段双向 `EXCEPT ALL`；
2. P1-B1 中 `moneyflow_ind_ths` 已完成切换前后生产计划和时延验收；`moneyflow_cnt_ths` 与 `margin` 仍只有切换前基线，其余 8 项尚未建立前后基线；
3. 仓库外 SQL、BI、人工脚本和依赖 relation catalog 的工具尚未完成签字；
4. `suspend_d` 的 raw/serving `id` 必须逐行一致，不能只比较 `row_key_hash`；
5. P1-B0 已运行生产 Biz 查询服务，但未做带登录态的浏览器验收；行业 relation 当前没有 Biz/QTF/DG serving 读取，已按 Ops/freshness、真实 SQL 和 TaskRun 完成验收；其余 10 项仍须按实际消费者逐项执行。

因此，名单已固定，但每项当前状态仍是“候选”；未通过第 7 节门禁前禁止 drop serving 表。

### 2.4 当前代码消费者清单

本轮 CodeGraph 索引状态为 current，覆盖 2,688 个文件、46,936 个节点和 108,072 条边；对 `DatasetWriter`、`DatasetStorageDefinition`、12 个 ORM/DAO/Definition 及跨子系统调用者做了影响面审计，并用精确代码搜索补齐 CodeGraph 对动态 Definition/ORM 引用识别不足的部分。

当前必须进入回归的已知直接读取入口：

1. `moneyflow_mkt_dc`：
   - `src/biz/queries/wealth/market/money_flow/money_flow_query.py`
   - `src/biz/queries/wealth/market/money_flow/money_flow_state_query.py`
   - `src/biz/queries/wealth/market/summary/summary_metrics_query.py`
   - `src/biz/queries/wealth/market/summary/summary_state_query.py`
   - `src/biz/services/wealth/market/summary/summary_status_resolver.py`
2. `moneyflow_ind_ths/moneyflow_cnt_ths/margin`：
   - 未发现 Biz、QTF 或 DG 对三张 serving relation 的直接读取；
   - `src/ops/action_catalog.py` 的 `daily_moneyflow_maintenance` 工作流包含两个 THS 数据集；
   - `src/ops/services/margin_remote_probe_service.py` 和 probe runtime 负责 `margin` 的三交易所源端完整性探测；
   - Lake Console 的三个 prod-raw-db 策略均直接读取 `raw_tushare`，不读取 serving。
3. `moneyflow_ind_dc/dc_daily`：
   - `src/biz/queries/wealth/market/sector_overview/sector_metrics_query.py`
   - `src/biz/queries/wealth/market/sector_overview/sector_overview_state_query.py`
   - `src/biz/services/wealth/market/sector_overview/sector_heat_source_query.py`
   - `qtf/adapters/prod/sector_source_adapter.py`
   - `lake_console/orchestrator/src/orchestrator/defs/asset_guards/dc_board_source_probe.py`
4. `suspend_d/stk_limit`：
   - `src/biz/queries/wealth/market/index_detail/index_detail_query.py`
   - `src/biz/queries/wealth/market/sector_overview/sector_member_query.py`
   - `src/biz/queries/wealth/market/streak_ladder/streak_ladder_query.py`
   - `src/biz/services/wealth/market/sector_overview/effective_a_stock_pool_query.py`
   - `src/biz/services/wealth/market/sector_overview/sector_heat_source_query.py`
   - `src/biz/services/market_mood_calculator.py`
   - `src/biz/services/market_mood_walkforward_validation_service.py`
5. Lake Console：`lake_console/backend/app/services/prod_raw_db.py` 当前对一期 10 个数据集直接映射 `raw_tushare`；对应 trade-date 同步策略位于 `lake_console/backend/app/sync/strategies/prod_db_trade_date.py`。两个 auction 数据集不在当前映射中。
6. Ops/freshness：通过 `DatasetDefinition.storage.target_table` 的现有投影链读取目标 relation，不为一期维护第二套数据集白名单。

当前没有发现 `ServingPublishService` 对这 12 个 dataset key 的 target mapping，也没有发现仓库内显式 serving DAO DML 旁路。实施每个数据集前仍要重新跑相同审计；此处不能替代对仓库外消费者的运营登记。

## 3. 硬需求追溯账本

| ID | 硬需求 | 实现落点 | 正向门禁 | 反向门禁 | 当前状态 |
| --- | --- | --- | --- | --- | --- |
| RD-001 | raw 成为唯一物理事实表 | 3 个 Definition 文件、现有 `raw_only_upsert` | writer 仅调用 raw DAO | serving DAO 零调用 | P1-B0 M3 生产切换已通过；serving 已为零物理字节 view |
| RD-002 | 原 serving 名称和业务列合同不变 | 每数据集独立 migration、原 serving ORM | ORM/SQL 查询结果一致 | 禁止改 Biz/QTF/DG relation 名 | P1-B0 M3 以生产 812 行完成双向差集、字段与 relation 合同实证 |
| RD-003 | serving 禁止写入 | Definition + DB INSTEAD OF reject trigger | SELECT 正常 | INSERT/UPDATE/DELETE 均失败 | P1-B0 M3 生产三类 DML 均以 SQLSTATE `55000` 拒绝 |
| RD-004 | 全量事实无差异 | 生产维护窗口分块对账 | 两层差集均为 0 | 任一差异阻断 migration | 4/12 已证 |
| RD-005 | raw 索引覆盖查询 | raw ORM index 声明、生产索引、计划基准 | 代表查询使用等价索引 | 计划/延迟退化阻断 | P1-B0 M3 生产点查、最大日期和 90 日范围查询均下推 raw 等价索引 |
| RD-006 | 现有 schedule 不重建 | action key/date/capability 不变 | 暂停后原 schedule 恢复 | 禁止自动 seed/重建 | P1-B0 生产原本无 schedule，M3 未创建 schedule |
| RD-007 | Lake/DG 已知读取合同不变 | Lake raw 白名单、DG `dc_board_source_probe` | 既有测试与真实只读查询通过 | 禁止切换 Lake source 或写 Lake | 静态审计完成 |
| RD-008 | 不改变源端请求 | Definition 只改 storage | connector/request 测试不变 | 禁止改 fields/分页/date model | P1-B0 Definition/plan 反向测试已通过 |
| RD-009 | 一个数据集一个发布单元 | 独立 revision/commit/deploy 记录 | M3a/M3b 与下一次生产切换有明确门禁 | 禁止批量 drop 或把生产授权外推 | 已固定；M1/M2 不被自然任务观察错误阻塞 |
| RD-010 | owner/grant/comment 可追溯 | migration 动态快照与恢复 | 非 owner SELECT 权限一致 | 未知 grant/comment 阻断 | P1-B0 M3 生产 owner、既有 `lake_raw_reader` SELECT 与空 comment 状态均保持不变 |
| RD-011 | Ops 观测改读 raw | `target_table` 派生、freshness registry | 新 TaskRun/freshness 读 raw | 历史 TaskRun 不回写 | P1-B0 M3 TaskRun 9210 已通过 raw target 写入并由 view 即时读到 |
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

### S3：生产维护窗口与自然运行观察

S3 拆成两个不同目的的阶段，禁止再把二者合并成一个模糊的“上一项通过”门禁：

- **M3a：生产切换与即时验收**。证明代码、migration、relation、拒写、查询、连接池和受控最小 TaskRun 在生产已闭环；
- **M3b：首个自然自动化观察**。证明恢复后的既有 schedule/probe 能按原配置触发，并且目标数据集对应的工作流 node 或 probe TaskRun 正常完成。

M3a 固定执行：

1. 暂停该数据集 schedule；停止会领取该数据集的 worker；Web 只读可保留，但 relation 切换可能短暂等待锁；
2. 完成最终全量分块双向差集；
3. 部署含该数据集 raw-only Definition 的版本，worker 继续停止；
4. 应用该数据集 migration；
5. 回收 Web、QTF 和其它直接消费者的长连接池，避免旧 relation OID/缓存计划跨越切换窗口；无法确认连接已回收时不得进入业务验收；
6. 完成 relation、view、ACL/comment、DML 拒绝、查询结果和性能验收；
7. 启动 worker，执行 1 个受控最小维护 TaskRun，完成 fetched/normalized/written/rejected/raw/view 五段对账；
8. 恢复原 schedule；没有 schedule 的数据集不创建新 schedule。

M3b 固定执行：

1. 普通 workflow 必须核对父 TaskRun 的 `status/unit_done/unit_failed`，再核对目标数据集 node 的 `status/time_input_json/rows_saved/rows_rejected/rows_deduplicated/ingestion_diagnostics_json`；`TaskRunNode` 没有独立 unit 字段，父任务 unit 代表 workflow step 完成数，不能把它冒充目标数据集的 source unit 数；
2. probe 数据集必须核对下一次有效 probe 窗口、源端 readiness、实际触发 TaskRun 和每日触发上限，不能套用 workflow 验收；
3. 没有既有 schedule/probe 的数据集，M3b 为不适用，M3a 的受控最小 TaskRun 即为生产运行门禁；
4. M3b 尚未到触发时刻时，不阻塞后续数据集在另行授权下执行 M1 编码或 M2 隔离验证；它只阻塞下一数据集的生产 M3a；
5. M3b 若失败，先按目标 node、源端、调度、worker、写入或下游消费归因。未归因的失败阻断下一次生产切换；若已证明与本次 raw 直出无关，是否解除阻断必须记录证据并单独拍板，禁止自动放行。

P1-B0-M3 于 2026-08-24 在生产完成，实际证据如下：

1. 生产只读预检确认 PostgreSQL `16.13`、Alembic head `20260823_000145`、raw/serving 均为 812 行且 15 个业务字段双向 `EXCEPT ALL` 为 0；目标无锁、无超过 5 分钟事务、无开放 TaskRun、无 schedule，依赖、RLS、用户 trigger、列 ACL、rewrite rule、扩展统计、security label 与 publication 阻塞均为 0；
2. 维护窗口停止 Web、scheduler 与 generic worker 后再次核对任务、锁、事务、行数和差集，结果保持不变；部署 commit 为 `11dbe4c6`，迁移修正 commit 为 `e15483a4`；
3. 首次 migration 因最小权限生产角色无权执行 `SET LOCAL temp_file_limit='64MB'`，在任何 DDL 前安全失败；Alembic 仍为 `20260823_000145`，两张表 OID、relation kind 与 812 行数据均未改变。修正后取消该特权参数，改为持锁后分别检查 raw/serving 不超过 5,000 行，并以 `work_mem=16MB` 限定完整对账工作集；
4. 修正方案在 PostgreSQL 18.4 非超级用户隔离实例再次验证：812 行迁移成功；5,001 行在 DDL 前拒绝，Alembic 版本、旧表与数据保持不变。随后生产 migration `20260823_000145 -> 20260824_000146` 成功；
5. 生产 `core_serving.market_moneyflow_dc` 已从物理表切换为普通 view，物理大小从 237,568 B 变为 0；`raw_tushare.moneyflow_mkt_dc` 保持物理表和既有有效索引，raw/view 均为 812 行、812 个唯一交易日，日期范围仍为 `2023-04-17..2026-08-21`，业务字段和审计时间投影差异均为 0；
6. owner 保持 `goldenshare_user`，raw 的 `lake_raw_reader` SELECT 保持不变，serving 原无非 owner grant 和 comment，切换后仍一致；生产 INSERT/UPDATE/DELETE 均被 reject trigger 以 SQLSTATE `55000` 拒绝，回滚后 raw/view 仍为 812 行；
7. 生产点查、最大日期和 90 日范围查询均下推 raw 的等价索引。切换前后 total cost 分别保持 `8.29`、等价反向索引计划和 `8.38`；单次执行时间均为亚毫秒级，buffer 形态一致。单次微秒值只作为计划证据，不据此宣称固定百分比加速；
8. Web 与所有 Ops worker/scheduler 的连接池均通过正式服务重启回收，Web 健康检查通过。QTF 当前没有该数据集消费者，因此未做无关重启；
9. 正式最小 TaskRun `9210` 请求 `2026-08-21` 一个 unit，状态 success，`1/1` unit 完成、0 失败；源端读取 1、归一化 1、写入 1、拒绝 0、去重 0，分页 1 页且短页正常结束。raw/view 该日均为 1 行且业务值一致，view 的 `created_at/updated_at` 与 raw `fetched_at` 即时一致；
10. 生产 `MarketMoneyFlowQueryService` 7 次中位数 3.998 ms、`MarketSummaryQueryService` 7 次中位数 12.153 ms，均无查询异常。无登录态 HTTP 只能验证认证层返回 401，未将其冒充浏览器业务验收；
11. M3 后全部服务恢复 active、开放 TaskRun 为 0；该数据集原本没有 schedule，本轮没有创建。catalog 可确认释放的 serving 物理 relation 为 237,568 B；根文件系统可用字节受发布依赖、WAL 和运行噪声影响反而减少，不能用一次 `df` 差值替代 relation 释放量。

### P1-B1：专属顺序、M0 证据与首项 M1/M2/M3a

P1-B1 固定按 `moneyflow_ind_ths -> moneyflow_cnt_ths -> margin` 顺序推进；每项都必须依次完成 M1 编码、M2 隔离 PostgreSQL、M3 生产验收，禁止把三个 relation 放进同一个 revision 或维护窗口。2026-08-24 M0 证据如下：

1. 生产 Alembic head 为 `20260824_000146`；六个 raw/serving relation 均为 `goldenshare_user` 所有的 `pg_default` 物理表，三张 raw 表保留 `lake_raw_reader` SELECT，三张 serving 表没有非 owner grant 或 comment；
2. 行业为 42,030 / 42,030 行、日期 `2024-09-10..2026-08-21`；概念为 181,560 / 181,560 行、日期相同；margin 为 1,146 / 1,146 行、日期 `2025-01-02..2026-08-21`。三项行数均等于各自主键身份数；
3. 行业与概念按 `trade_date` 索引拆成 24 个自然月，逐窗比较全部 12 个业务字段，双向 `EXCEPT ALL` 均为 0；margin 的 9 个业务字段全量双向差集为 0；
4. 三张 serving 表的 inheritance、外键、用户 trigger、列 ACL、RLS、依赖 view/function、rewrite rule、扩展统计、security label 和 publication 均为 0；约束只有主键，raw 的两个等价查询索引均 valid、ready 且位于 SSD；
5. 生产当前无开放 TaskRun、无超过 5 分钟事务。`daily_moneyflow_maintenance` 是 active 工作流 schedule，包含行业和概念两个 step；`margin.maintain` 是 active 固定源端 probe，窗口 `09:00..09:30`、300 秒间隔、每日最多触发一次。生产迁移前必须按 target key 暂停并在验收后原样恢复，禁止重建或改配置；
6. 行业、概念、margin 的单日最大行数分别为 90、395、3，业务行最大宽度分别为 121 B、126 B、99 B；单月最大行数分别为 2,070、9,070、69。由此独立固定 migration 对账门禁：行业 5,000 行/月，概念 20,000 行/月，margin 全表 5,000 行；都使用 `work_mem=16MB`，禁止设置需要超管权限的 `temp_file_limit`；
7. 切换前查询基线均命中 serving 等价索引。行业日期点查、代码范围、最大日期单次执行分别为 0.217/1.095/0.019 ms；概念为 0.621/1.438/0.033 ms；margin 为 0.835/0.377/0.032 ms。微秒值只记录计划基线，M3 必须比较计划形态、buffer 与结果，不据此承诺固定百分比；
8. CodeGraph 与精确引用审计未发现三个 dataset key 的 `ServingPublishService` target 或 serving DML 旁路；行业和概念没有 Biz/QTF/DG serving 读取，Lake Console 直接读取 raw；margin 的 probe 只调用源端和正式 resolver，不读写 serving relation。

P1-B1 首项 `moneyflow_ind_ths` M1 已按上述证据实现：

1. Definition 只把 storage 改为现有 `raw_only_upsert + raw_with_serving_view`；12 个 source fields、`ts_code` filter、日期模型、5,000 行源端分页、unit、能力和工作流 action key 均保持不变；
2. raw ORM 仅补齐生产已存在的 `trade_date` 与 `(ts_code, trade_date)` 两个索引 metadata，不创建新物理索引；
3. 独立 revision `20260824_000147` 连接真实 head `20260824_000146`，只处理行业 relation；按自然月进行持锁双向差集，任一月任一层超过 5,000 行即 fail-closed；
4. revision 要求复用 B0 已创建且契约完全匹配的数据库拒写函数；它不新增 Python 共享框架、不重建函数、不修改 B0 view。每个后续 view 仍使用自己的独立 trigger；
5. migration 保留 owner、SELECT grant 和 comment，显式投影 12 个业务字段及 `fetched_at AS created_at/updated_at`，拒绝 `CASCADE`、raw 删除和自动 downgrade；
6. Definition、filter 正反例、planner、ORM/字段/索引、raw-only writer、ServingPublish 旁路、migration 顺序/分块上限/函数前置/显式 view 与离线 SQL 渲染定向测试全部通过；M1 未连接或写入 PostgreSQL，也未创建 TaskRun。

P1-B1 首项 `moneyflow_ind_ths` M2 于 2026-08-24 在临时、仅 Unix socket 可访问的 PostgreSQL 18.4 隔离实例完成。实例中的角色、数据库、结构与数据均为本轮受控创建，应用 migration 的 `goldenshare_m2_app` 为非超级用户；显式 env URL、数据库名、用户、空 `inet_server_addr()`、端口和管理员侧 `data_directory` 六项门禁全部匹配后才执行 Alembic。没有连接 Prod、调用 Tushare、部署服务、创建 TaskRun 或修改 schedule。

实测结论如下：

1. 受控成功样本为 42,030 行，按 467 个工作日、每日 90 个身份构造，单月最大 2,070 行；raw 与 serving 在 revision 146 时业务字段、身份和审计时间完全一致。migration `20260824_000146 -> 20260824_000147` 以非超级用户成功；
2. 切换后 raw 仍为物理表，`core_serving.industry_moneyflow_ths` 为普通 view、物理大小 0；raw/view 均为 42,030 行和 42,030 个唯一 `(trade_date, ts_code)`，12 个业务字段双向 `EXCEPT ALL` 与 `fetched_at -> created_at/updated_at` 差异均为 0；
3. serving owner、relation comment、列 comment、PUBLIC SELECT、普通角色 SELECT 和 `WITH GRANT OPTION` SELECT 均完整恢复；raw 的 `lake_raw_reader` SELECT 保持可用。三个非 owner serving 角色与 raw reader 均真实查询到 42,030 行；
4. serving view 的 INSERT、UPDATE、DELETE 均以 SQLSTATE `55000` 拒绝；拒写函数保持 `SECURITY INVOKER`、固定 `search_path=pg_catalog` 且不向 PUBLIC 开放执行权限；
5. 正式 `DatasetWriter` 连续两次写同一身份时均只命中 raw target，view 在同一事务立即返回更新值；事务回滚后 raw 原值恢复。另以隔离 SQL 验证 raw INSERT/UPDATE/DELETE 均被 view 零延迟反映，结束后行数仍为 42,030；
6. 日期点查、代码日期范围和最大日期查询均由原 serving 索引等价下推到 raw 的 `trade_date` 与 `(ts_code, trade_date)` 索引。切换前后 shared buffer 分别为 `95/95`、`8/9`、`3/3`；计划总成本分别为 `259.30/271.58`、`383.64/423.59`、`0.38/0.40`。隔离样本执行时间均低于 0.3 ms，只证明计划形态与 buffer 没有失控，生产 M3 仍须以真实数据复核；
7. 负向容量库在同一自然月放入 5,001 行后，migration 在任何 DDL 前以 `monthly reconciliation exceeds safety cap` 明确失败；revision 仍为 146，旧 relation OID、物理表类型和 raw/serving 各 5,001 行均不变，未残留 trigger；
8. 在另一套 42,030 行基线库中，于取得排他锁并删除旧 serving 表后注入异常。事务关闭后 revision 仍为 146，旧物理表 OID、42,030 行、3 个有效索引、权限和注释全部恢复，证明切换不会留下半完成 relation；
9. 隔离实例已停止，受控目录已可恢复地移入废纸篓；M2 不产生可复用环境，也不构成生产 migration 授权。

P1-B1 首项 `moneyflow_ind_ths` M3a 于 2026-08-24 在生产完成，实际证据如下：

1. 最终只读预检确认 PostgreSQL `16.13`、Alembic `20260824_000146`、raw/serving 均为 42,030 行和 42,030 个唯一 `(trade_date, ts_code)`，日期范围均为 `2024-09-10..2026-08-21`，单月最大 2,070 行；12 个业务字段全量双向 `EXCEPT ALL` 均为 0；
2. 目标 relation 没有 inheritance、外键、用户 trigger、RLS、依赖 view/function、扩展统计或 publication；没有开放 TaskRun、超过 5 分钟的事务或目标锁。`daily_moneyflow_maintenance` schedule #4 原为 active，cron `0 20 * * 1-5`、时区 `Asia/Shanghai`、下一次 `2026-08-24 20:00`；
3. 维护窗口通过正式 `OperationsScheduleService` 暂停 schedule #4，并停止 scheduler 与 generic worker；Web 保持只读可用。部署 commit `60f2ce28` 只安装后端并执行 migration，不构建前端、不 seed、不提前重启执行服务；
4. migration `20260824_000146 -> 20260824_000147` 一次成功。`raw_tushare.moneyflow_ind_ths` 仍是 `pg_default` 物理表，heap/index 分别为 6,512,640/4,096,000 B；`core_serving.industry_moneyflow_ths` 已是普通 view，物理 heap/index 均为 0，原 serving 释放 9,756,672 B；
5. 切换后 raw/view 仍为 42,030 行，身份数、日期范围和 12 个业务字段保持一致，审计时间固定投影 `fetched_at -> created_at/updated_at` 差异为 0。owner 仍为 `goldenshare_user`，生产原本没有 serving 非 owner grant/comment，切换后保持相同；raw 既有关系和索引未改变；
6. 对 serving view 的 `INSERT`、`UPDATE`、`DELETE` 均由独立 trigger 以 SQLSTATE `55000` 拒绝；三类验证均在可回滚事务内执行，raw 行数前后均为 42,030；共享函数仍为 `SECURITY INVOKER`、固定 `search_path=pg_catalog` 且仅 owner 可执行；
7. 生产日期点查切换前后执行时间为 `0.244/0.234 ms`，行业代码区间为 `0.880/0.959 ms`，最大日期为 `0.028/0.024 ms`；三类查询均下推 raw 的等价日期或 `(ts_code, trade_date)` 索引，单次时延变化低于 20% 阻断线，未出现顺序扫描或临时文件；单次微秒值只作为计划证据；
8. Web、date-completeness、task-completion 和两个分钟线 worker 通过正式 service restart 回收连接池，健康检查通过；generic worker 在静态验收后才启动，scheduler 在 schedule 恢复后才启动。QTF 当前没有该 relation 消费者，因此没有做无关重启；
9. 正式最小 TaskRun `9217` 请求 `2026-08-21` 一个 unit，状态 success，`1/1` 完成、0 失败；源端 1 页读取 90 行，短页正常结束、0 重试，归一化 90、写入 90、拒绝 0、去重 0；
10. TaskRun 后该日 raw/view 均为 90 行和 90 个唯一身份，90 行 `fetched_at` 全部位于任务执行窗口，view 审计时间即时一致；全表仍为 42,030 行，业务字段双向差集、审计时间投影差异和关键字段异常均为 0；
11. schedule #4 通过正式服务恢复为 active，`next_run_at` 仍为 `2026-08-24 20:00+08`；`ops.config_revision` 留有同一用户的 `paused/resumed` 审计记录。最终 Web、worker、scheduler 及相关 Ops worker 全部 active，开放 TaskRun 为 0；首个正常工作流尚未到触发时间，因此 M3b 待闭环，但它不阻塞 `moneyflow_cnt_ths` 的 M1/M2，只阻塞其生产 M3a；
12. 根盘可用空间从维护窗口前 4,461,560 KiB 变为验收后的 4,485,480 KiB，但发布依赖、WAL 与运行噪声会影响 `df`；因此只以 catalog 的 9,756,672 B 作为本项已释放 serving 物理量，不把文件系统瞬时差额当作精确收益。

### S4：文档证据

将 revision、部署 commit、TaskRun ID、对账结果、查询计划、磁盘释放量和残余风险写回 v2；未验收项不得标完成。

## 9. 已验证经验与后续执行加固

### 9.1 两轮实施暴露的问题与固定规则

| 已发生问题或误判 | 根因 | 后续固定规则 | 落实位置 |
| --- | --- | --- | --- |
| 把首个正常 workflow 观察说成下一数据集 M1 的前置条件 | 没有区分编码/隔离验证与生产切换风险 | M3 拆成 M3a/M3b；M3b 只阻塞下一次生产 M3a，不阻塞另行授权的 M1/M2 | 第 8 节阶段合同与第 13 节完成边界 |
| 隔离 migration 曾被显式 env 文件指向 Prod | `get_settings()` 的既有合同是 `GOLDENSHARE_ENV_FILE` 内容覆盖同名 shell 变量，不能靠临时 `DATABASE_URL` 改目标 | M2 必须使用独立 env 文件，并在 Alembic 前核对 host/database/user/server address/port/data directory；禁止改变全局配置优先级来修本专项 | S2 与现有 `tests/test_db.py` 配置合同 |
| 维护发布依赖多组临时环境变量，存在漏关 seed、构建或服务重启的风险 | 通用部署入口默认执行完整发版 | 使用 `--maintenance-migration` 固定变更动作仅为拉代码、安装后端和 migration，另保留只读资源加载自检；该模式不代替 schedule 暂停、停服和恢复 | `scripts/deploy-systemd.sh`、发布文档与部署脚本测试 |
| B0 首次生产 migration 试图设置业务角色无权修改的 `temp_file_limit` | 把隔离环境能力误当成生产最小权限能力 | migration 只使用已验证的最小权限能力；工作集通过每数据集独立行数上限、分块和 `work_mem` 有界，禁止为迁移追加超管权限 | 第 7.1 节与各 revision 负向容量测试 |
| 一次验收 SQL 曾按 dataset key 猜 serving 表名 | action key、dataset key 与物理 relation 名并非机械映射 | 每项 S0 冻结显式对象表：dataset/action/raw/serving/ORM/DAO/index/schedule；所有 SQL 只从已核验对象表生成 | 第 9.2 节准入清单 |
| `df` 瞬时变化与 relation 释放量不一致 | 发布依赖、WAL、日志和后台活动共同影响文件系统水位 | 精确收益只取 PostgreSQL catalog 中被删除 heap/index 的字节；`df` 仅做容量安全水位 | S4 证据合同 |
| TaskRun 顶层诊断不能完整代表 workflow 内单个数据集 | workflow node 才保存目标步骤的 rows、reject 和分页诊断；父任务 unit 表达 step 完成数，`TaskRunNode` 本身没有 unit 字段 | 自然 workflow 验收必须同时查询目标 node；字段名称以当前 ORM 的 `rows_saved` 和 `ingestion_diagnostics_json` 为准，禁止猜 `rows_written` 或把父任务 unit 当 source unit | M3b 与五段对账模板 |
| raw upsert 的插入/匹配细分不能照搬 immutable writer 指标 | writer 语义不同，部分持久化诊断字段对 raw upsert 没有同一含义 | raw 直出验收以 `rows_saved`、reject、去重、任务时间窗内 `fetched_at` 和物理 raw/view 对账为主；不得把不适用的 immutable 指标填 0 后宣称闭环 | M3a TaskRun 对账 |
| 连续拼接多项生产状态修改曾出现本地引号错误 | 一个命令同时承担暂停、停服、恢复等多个状态变化，失败边界不清 | 一次只做一个状态修改；每次修改后立即只读回查 schedule、service、TaskRun 和 relation，再进入下一步 | M3a 操作顺序 |
| B0 的拒写函数可以被 B1 复用，但不能因此抽成通用迁移框架 | 可复用的是数据库函数契约，不是各表字段、依赖、容量和切换 SQL | 仅在 owner、参数、语言、security、search_path、ACL 完全匹配时复用拒写函数；每张 view 保留独立 trigger 和独立 migration | 第 5.2、6、9.2 节 |
| 小表验收阈值容易被误当成一期通用阈值 | 每表行宽、月峰值、索引、消费者和锁预算不同 | 5,000/20,000 行、20% 时延和分块粒度都必须在对应 S0 重新证明；大表不得复制小表上限或无界全表 `EXCEPT ALL` | 第 7 节与第 9.3 节差异矩阵 |
| “保留原表名”容易被误解为物理完全透明 | view 的 OID、relkind、catalog nullability、PK/index 与审计时间来源都会变化 | 只承诺已登记只读业务合同透明；catalog 工具、写入方和审计字段消费者必须单独登记和验收 | 第 1 节透明性边界 |

### 9.2 每个后续数据集必须重新完成的零假设审计

以下清单可以复用审计方法，不能复用结论。任何一项仍靠命名、历史文档或前一数据集推断时，不得开始编码：

1. **事实与对象**：读取当前 `DatasetDefinition`，显式记录 dataset/action key、source fields、date/unit/pagination、raw/serving relation、ORM、DAO、冲突键和审计列投影；
2. **调用链**：CodeGraph 与精确搜索同时覆盖 writer、resolver、manual action、workflow/probe、freshness、Biz、QTF、Lake Console、DG、测试和仓库内脚本；动态 registry 引用不能只靠 CodeGraph 搜索结果；
3. **物理合同**：生产只读核验 relation kind/OID、列、主键、索引、owner/ACL/comment、依赖、trigger、RLS、publication、tablespace、锁和长事务；
4. **数据合同**：按当前表的真实日期范围、峰值、行宽和业务身份设计有界双向 `EXCEPT ALL`；行数相等、主键相等或前一项差异为 0 都不能替代本项全字段证明；
5. **容量与性能**：从真实消费者 SQL 提取 point/range/join/order by，确认 raw 等价索引、buffer、timeout、锁时间、WAL 和临时空间预算；每项单独固定停止阈值；
6. **自动化类型**：明确无 schedule、普通 workflow、dataset schedule、probe 或下游 readiness 中的哪一种；冻结 pause/resume 对象和 M3b 验收对象，禁止机械复制上一项；
7. **迁移链**：编码前读取当时真实 Alembic head；离线渲染完整 PostgreSQL SQL，验证参数解析、最小权限、DDL 中途回滚和超限 fail-closed；
8. **环境身份**：M2 使用独立 env 文件和六项数据库身份门禁；M3 只使用生产正式 env 文件与维护迁移模式，禁止临时 `DATABASE_URL` 覆盖和手拼发布开关；
9. **运行对账**：受控 TaskRun 与自然任务都读取当前 ORM 的真实字段；workflow 进入目标 node，probe 进入 probe/触发链；源端、归一化、保存、reject、去重、raw/view 逐段闭环；
10. **变更边界**：一个数据集一个 Definition、revision、测试集和生产授权；只有现有实现语义完全相同时才复用 writer 或数据库函数，不新增跨数据集共享框架。

### 9.3 后续批次的差异化门禁

| 范围 | 已从当前代码确认的不同点 | 允许复用 | 禁止照搬 |
| --- | --- | --- | --- |
| `moneyflow_cnt_ths` | 与行业同属 `daily_moneyflow_maintenance`，当前无 Biz/QTF/DG serving 直读；月峰值和总量更高 | raw-only writer、显式 view、拒写函数契约、workflow pause/resume 方法 | 行业 5,000 行/月上限、行业字段/索引、把 M3b 当 M1/M2 门禁 |
| `margin` | 不在 workflow；由固定源端 probe 管理，并要求 SSE/SZSE/BSE readiness | raw-only writer、view/ACL/DML/事务回滚审计方法 | workflow 自然任务验收、概念/行业分块和请求语义 |
| `moneyflow_ind_dc` | 属于每日资金 workflow；有 Wealth 直接读取，且进入 sector heat 上游 readiness | relation 切换骨架和有界差集方法 | “无业务消费者”的验收范围；M3b 还需核对目标 node 与下游 readiness |
| `dc_daily` | 属于每日收盘 workflow；Wealth、QTF 和 DG 都有直接读取 | 只读 relation 名与显式列合同 | 只做 Ops SQL；必须增加 QTF bounded range、DG 单日 probe 和业务返回验收 |
| `suspend_d` | 属于每日收盘 workflow；多条 Wealth/市场情绪链消费，冲突键含 `row_key_hash`，物理事实还含 `id` | 分块、拒写、事务回滚方法 | 只比较业务 hash；必须证明 `id` 逐行一致并验证日期范围 join |
| P1-B3/B4 百万行表 | 分别受每日收盘或每日资金 workflow 覆盖，行数、锁时、WAL、缓存和查询面显著增大 | 阶段状态机、只读透明边界、单数据集 revision | 小表全量/单月阈值、单次微秒样本、无界锁内对账或合并发布 |

### 9.4 后续统一状态机

1. **S0/M0 只读复审**：可以在前项 M3b 等待期间开展；输出本项对象表、差异化门禁和停止条件，不写代码或数据库；
2. **M1 编码**：必须有本项授权；只改本项 Definition/ORM/migration/tests。前项 M3b 不阻塞，但若观察暴露共享 writer、scheduler 或 workflow 契约问题，应暂停 M1 并重新评审；
3. **M2 隔离验证**：必须独立授权和数据库身份门禁；不连接 Prod、不调用 Tushare、不创建任务；
4. **M3a 生产切换**：必须独立授权；前项 M3a 已闭环，且共享 schedule/runtime 的前项 M3b 已通过或其失败已完成有证据的单独处置；
5. **M3b 自然观察**：只验证既有自动化恢复后的真实路径；不重复源端扫描，不自动创建或修改 schedule；
6. **S4 文档闭环**：实际 revision、commit、TaskRun/node、释放量、查询和残余风险写回本文及 v2，历史事实与当前状态分开记录。

这套状态机的目标是把“可提前准备”与“不可叠加生产风险”分开，而不是减少任何数据、权限、消费者或回滚门禁。

## 10. 测试清单

### 10.1 Foundation/Ops

1. 12 个 Definition 的 raw-only/view storage contract；
2. 参数化 writer 测试证明每项只调用 raw DAO 一次，serving DAO 零调用；
3. 保持原 conflict columns，覆盖 `dc_daily` 和 `suspend_d` 特殊键；
4. freshness projection 自动改读 raw target，并能观察 `trade_date`；
5. dataset card 显示“原始数据直出”，raw/serving 两个 relation 均正确；
6. manual action、schedule capability、date completeness 和 source release 事实不变；
7. `ServingPublishService` 不存在这 12 个 target mapping；
8. 静态扫描禁止任何一期 serving DML。

### 10.2 migration

1. 非 PostgreSQL 不执行；PostgreSQL 正确切换；
2. raw/serving relation kind 错误时失败；
3. 字段、索引、依赖、ACL/comment 出现未知状态时失败；
4. 不包含 `CASCADE`；
5. view 为显式列投影且 `created_at/updated_at` 均来自 `fetched_at`；
6. owner、SELECT grants 和 comments 恢复；
7. INSERT/UPDATE/DELETE 均被明确拒绝；
8. downgrade 明确拒绝自动重建空表；
9. 每个 revision 只处理一个数据集。

### 10.3 直接消费者

1. Wealth 市场资金/市场总览；
2. Wealth 板块概览、板块热度、指数详情、板块成员、连板天梯；
3. 市场情绪计算和 walk-forward validation；
4. QTF sector input；
5. Lake Console `prod-raw-db` query builder；
6. DG `dc_board_source_probe` 静态及隔离查询测试；
7. 不运行正式 Dagster instance，不触发正式 asset/job/sensor。

## 11. 发布停止条件与回退

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

## 12. 不做事项

一期不做：

1. 不处理 `daily_basic`、`dc_member`、`stock_st` 或缺 raw 索引的其它候选；
2. 不把一期 raw 表迁 HDD；它们继续留在 SSD，避免 serving view 查询直接转为机械盘 I/O；
3. 不改 `stk_mins`；
4. 不改 source fields、请求参数、分页、日期/unit 设计或自动任务时间；
5. 不创建、删除或重新配置 schedule；
6. 不修改 Lake Parquet、ClickHouse、Dagster asset/check/event；
7. 不做共享 writer/DAO/Definition 重构；
8. 不保证 relation OID、relkind、PK/index catalog 或历史审计时间值不变。

## 13. 当前完成边界与下一阶段

1. P1-B0-M1～M3 已完成；P1-B1-M0 已完成，首项 `moneyflow_ind_ths` M1/M2 与 M3a 生产切换、即时验收已通过；M3b 首个正常 schedule 观察待闭环，`moneyflow_cnt_ths` 与 `margin` 尚未修改 Definition 或创建 migration；
2. `moneyflow_cnt_ths` 的 M1 编码和 M2 隔离验证可在分别获得授权后开展，不以行业 M3b 为前置条件；行业 M3b 未闭环前不得进入概念数据集的生产 M3a；
3. `moneyflow_cnt_ths` 后续仍必须独立完成 M1、M2、M3a 和 M3b，并按同一每日资金工作流的暂停/恢复契约执行；禁止把行业授权外推为概念授权，也禁止与 `margin` 合并 revision 或维护窗口；
4. 仓库外 SQL/BI/人工脚本无法由仓库审计穷尽，若存在依赖 OID、relkind、约束 catalog、旧审计时间或 serving DML 的未登记消费者，仍是每项 migration 的残余运营风险。

## 14. 依据

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
