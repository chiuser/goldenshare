# 生产 PostgreSQL raw 直出一期低层设计 v1

- 版本：v1
- 状态：P1-B0 与 P1-B1 已结案；`P1-B2-moneyflow_ind_dc` 已结案；`P1-B2-dc_daily` 的 M0/M1/M2/M3a 已通过，待两个既有 workflow 的自然 M3b 验收
- 更新时间：2026-08-28
- 上位方案：[生产 PostgreSQL 存储空间优化治理专项 v2](/Users/congming/github/goldenshare/docs/governance/prod-postgresql-storage-space-optimization-program-v2.md)
- 目标：把一期 12 个无业务转换的 raw/core_serving 双写数据集收敛为“raw 唯一物理事实表 + 原 serving 名称只读 view”，预计释放约 3.305 GiB SSD

## 0. 边界与完成定义

本文定义一期实施合同，并记录已获授权完成的 P1-B0-M1～M3、P1-B0 市场资金补充 M3b、P1-B1 M0、行业/概念/`margin` 的 M1/M2/M3a/M3b、`P1-GATE-SSE-M1/M2/M3`，P1-B2 首项 `moneyflow_ind_dc` 的 M0/M1/M2/M3a/M3b，以及 `dc_daily` 的 M0/M1/M2/M3a。`moneyflow_ind_dc` 已完成只读生产基线、代码、自动化测试、隔离 PostgreSQL migration、切换后生产只读合同与自然运行验收；完整部署在未暂停 schedule/worker 时自动应用 revision 153 的发布顺序偏差继续作为历史事实保留，不因最终验收通过而删除。`dc_daily` 已按维护窗口顺序完成生产 revision 154、连接池回收、查询合同与最小 TaskRun 验收，当前只剩两个既有 workflow 的自然 M3b 观察。

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

一期启动前，12 个数据集都使用 `DatasetWriter.write()` 的 `raw_core_upsert` 分支；`_write_raw_and_core()` 会把同一个 `NormalizedBatch` 分别按 raw/serving ORM 列过滤后写入两层，且 12 个 Definition 的 `serving_conflict_resolution_policy` 均为 `none`。截至 2026-08-28，前 6 项已经完成生产 raw-only 切换；其中 `dc_daily` 已应用 revision 154 并通过 M3a，其余 6 项仍保持双写。

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

下表的物理大小基线来自 2026-08-23；P1-B1 行业/概念事实来自 2026-08-24，`margin` 行数与自然任务事实已于 2026-08-27 刷新。大小会变化，执行前必须重新采样；名单和顺序只有经本文修订才能改变。

| 批次 | 顺序 | 数据集 | raw → serving | 业务身份/冲突键 | serving 大小 | raw/serving 精确行数 | 当前直接消费者摘要 |
| --- | ---: | --- | --- | --- | ---: | ---: | --- |
| P1-B0 | 1 | `moneyflow_mkt_dc` | `raw_tushare.moneyflow_mkt_dc` → `core_serving.market_moneyflow_dc` | `trade_date` | 0.2 MiB | 812 / 812 | Wealth 市场资金、市场总览；Lake raw |
| P1-B1 | 2 | `moneyflow_ind_ths` | `raw_tushare.moneyflow_ind_ths` → `core_serving.industry_moneyflow_ths` | `(trade_date, ts_code)` | 9.3 MiB | 42,030 / 42,030 | Ops/freshness；Lake raw；active 每日资金工作流 |
| P1-B1 | 3 | `moneyflow_cnt_ths` | `raw_tushare.moneyflow_cnt_ths` → `core_serving.concept_moneyflow_ths` | `(trade_date, ts_code)` | 41.9 MiB | 181,560 / 181,560 | Ops/freshness；Lake raw；active 每日资金工作流 |
| P1-B1 | 4 | `margin` | `raw_tushare.margin` → `core_serving.equity_margin` | `(trade_date, exchange_id)` | 0.3 MiB | 1,155 / 1,155 | Ops/freshness；Lake raw；active 固定源端 probe；M3b 已通过 |
| P1-B2 | 5 | `moneyflow_ind_dc` | `raw_tushare.moneyflow_ind_dc` → `core_serving.board_moneyflow_dc` | `(trade_date, content_type, name)` | 84.27 MiB | 339,268 / 339,268 | Wealth 板块概览/热度；Lake raw；M0/M1/M2/M3a/M3b 已完成并结案 |
| P1-B2 | 6 | `dc_daily` | `raw_tushare.dc_daily` → `core_serving.dc_daily` | `(ts_code, trade_date, category)` | 154.22 MiB | 634,116 / 634,116 | Wealth、QTF、DG source probe；Lake raw；M0/M1/M2/M3a 已通过，待自然 M3b |
| P1-B2 | 7 | `suspend_d` | `raw_tushare.suspend_d` → `core_serving.equity_suspend_d` | 写入冲突键 `row_key_hash`；物理 PK `id` | 211.9 MiB | 640,481 / 640,481 | Wealth 指数/板块/连板、市场情绪；Lake raw |
| P1-B3 | 8 | `stk_auction_o` | `raw_tushare.stk_auction_o` → `core_serving.equity_auction_open` | `(ts_code, trade_date)` | 361.9 MiB | 2,161,633 / 2,161,633 | Ops/freshness；未发现当前 Lake/DG 读取 |
| P1-B3 | 9 | `stk_auction_c` | `raw_tushare.stk_auction_c` → `core_serving.equity_auction_close` | `(ts_code, trade_date)` | 364.1 MiB | 2,227,843 / 2,227,843 | Ops/freshness；未发现当前 Lake/DG 读取 |
| P1-B3 | 10 | `moneyflow_ths` | `raw_tushare.moneyflow_ths` → `core_serving.equity_moneyflow_ths` | `(trade_date, ts_code)` | 460.9 MiB | 2,050,984 / 2,050,984 | Ops/freshness；Lake raw |
| P1-B4 | 11 | `moneyflow_dc` | `raw_tushare.moneyflow_dc` → `core_serving.equity_moneyflow_dc` | `(trade_date, ts_code)` | 1,072.8 MiB | 4,120,988 / 4,120,988 | Ops/freshness；Lake raw |
| P1-B4 | 12 | `stk_limit` | `raw_tushare.stk_limit` → `core_serving.equity_stk_limit` | `(ts_code, trade_date)` | 623.5 MiB | 4,569,303 / 4,569,303 | 市场情绪/走查；Lake raw |
|  |  | **合计** |  |  | **3,548,766,208 B，约 3.305 GiB** |  |  |

合计仍是 2026-08-23 全名单同一时点基线；`moneyflow_ind_dc` 与 `dc_daily` 行已分别按各自 M0 时点刷新，不把不同时点数据重新相加伪装成同一容量快照。在 P1-B2 其余对象各自 M0 前，不用不同时点数据重算合计。

批次只表达风险顺序，不表示允许合并 migration。生产发布单位始终是“一个数据集、一个 Alembic revision、一次维护窗口、一次验收”。

### 2.3 已完成与尚未完成的生产证明

已完成：

1. 12 组精确 `count(*)` 全部一致；
2. raw/serving 业务列名称、类型、空值约束在当前生产表一致；
3. raw 的主键和二级索引签名覆盖 serving；所有相关索引有效且 ready；
4. 未发现外键、外部 view/materialized view 依赖、用户 trigger 或 RLS policy；
5. 2026-08-23 初始基线的开放 TaskRun 为 0；2026-08-24 18:07+08 当日暂停复核时有 2 个与本专项无关的分钟线 TaskRun 正在运行。`moneyflow_mkt_dc/moneyflow_ind_ths/moneyflow_cnt_ths` 均由 active 的 `daily_moneyflow_maintenance` workflow schedule #4 覆盖，`margin` 存在 1 个 active probe schedule；每次生产维护窗口仍须重新核验开放任务和 workflow step，不能复用历史快照或只查 dataset schedule；
6. owner 均为 `goldenshare_user`；部分 relation 的非 owner SELECT grant 不同，migration 必须逐对象恢复。
7. P1-B0 已在生产完成最终 812 行全字段双向差集、relation 切换、权限与拒写、真实查询计划、连接池回收及最小 TaskRun 验收；详见第 8 节。
8. P1-B1 三项已完成全字段对账：行业与概念按 24 个自然月逐窗双向差集均为 0，margin 全量双向差集为 0。
9. P1-B1 首项 `moneyflow_ind_ths` 已在生产完成 revision 147、42,030 行 raw-backed view、拒写、查询计划、连接池、TaskRun `9217` 与 schedule 原样恢复的 M3a 即时验收；首个正常 schedule 观察属于 M3b，统一登记、集中验收，尚未触发或尚未核验本身不阻塞后续数据集另行授权的 M1/M2/M3a，详见第 8 节。
10. P1-B1 第二项 `moneyflow_cnt_ths` 已在生产完成 revision 148、181,560 行 raw-backed view、拒写、查询计划、连接池、TaskRun `9224` 与 schedule 原样恢复的 M3a 即时验收；部署提前自动应用 migration 的流程偏差与残余风险已在第 8、9 节如实登记。
11. schedule #4 TaskRun `9244` 已分别完成 `P1-B0-market-M3b`、`P1-B1-industry-M3b`、`P1-B1-concept-M3b` 数据链验收；任务因部署锁等待在 20:07 而非 20:00 创建，不能作为准点性证据。
12. schedule #33 的固定源端 probe rule #14 已于 `2026-08-27 09:00:01+08` 自然命中，创建唯一 TaskRun `9573`；三交易所源端、分页、写入、拒绝和 raw/view 对账全部通过，`P1-B1-margin-M3b` 已关闭。
13. `P1-B2-moneyflow_ind_dc-M0` 已完成 36 个自然月和全表 18 个业务字段双向 `EXCEPT ALL`，raw/serving 各 339,268 行，双向差异均为 0；生产物理合同、消费者、容量和查询计划基线见第 8 节专属记录。
14. `P1-B2-moneyflow_ind_dc-M2` 已在仅 Unix socket 可达的 PostgreSQL 18.4 隔离实例完成 revision 153 正向 migration、30,001 行容量门禁、差异/身份/依赖 fail-closed、ACL/comment、三类 DML、正式 writer、事务回滚、即时可见和代表查询计划验收；该结论不改变生产 revision 152。
15. `P1-B2-moneyflow_ind_dc-M3a/M3b` 已完成：revision 153 已把 serving 收敛为 0 B raw-backed view；2026-08-27 的自然 TaskRun `9633/9644/9645` 已证明 raw-only 写入、双上游 readiness、Heat 发布和同日自动幂等，详见第 8 节。
16. `P1-B2-dc_daily-M0` 已完成 32 个自然月、634,116 行和全部 13 个业务字段双向 `EXCEPT ALL`，并建立 Wealth、QTF、DG 和 Heat 真实查询基线；`P1-B2-dc_daily-M1` 已完成 Definition、raw ORM、独立 revision 154 和专项自动化测试，详见第 8 节。
17. `P1-B2-dc_daily-M2` 已在仅 Unix socket 可达的 PostgreSQL 18.4 隔离实例完成 revision 154、30,000/30,001 行边界、字段/身份/主键/依赖 fail-closed、ACL/comment、三类 DML、正式 writer、事务回滚、即时可见和代表查询计划验收；该结论不改变生产 revision 153。
18. `P1-B2-dc_daily-M3a` 已按“两个 schedule 同时暂停 → 通用 worker 停止 → maintenance migration → 连接池回收 → 查询合同 → 最小 TaskRun → schedule 原样恢复”的固定顺序完成；生产现为 revision 154，serving 为 0 B raw-backed view，TaskRun `9704` 成功。

尚未完成：

1. 除 `moneyflow_mkt_dc`、`moneyflow_ind_ths`、`moneyflow_cnt_ths`、`margin`、`moneyflow_ind_dc`、`dc_daily` 外，其余 6 组尚未完成全历史业务字段双向 `EXCEPT ALL`；
2. P1-B1 中 `moneyflow_ind_ths`、`moneyflow_cnt_ths`、`margin` 已完成生产切换前后查询计划和时延验收；`moneyflow_ind_dc` 与 `dc_daily` 已完成生产查询验收；其余 6 项尚未建立前后基线；
3. 仓库外 SQL、BI、人工脚本和依赖 relation catalog 的工具尚未完成签字；
4. `suspend_d` 的 raw/serving `id` 必须逐行一致，不能只比较 `row_key_hash`；
5. P1-B0 已运行生产 Biz 查询服务，但未做带登录态的浏览器验收；行业 relation 当前没有 Biz/QTF/DG serving 读取，已按 Ops/freshness、真实 SQL 和 TaskRun 完成验收；`moneyflow_ind_dc` 已完成生产查询、Heat source/readiness、自然 TaskRun 与结果回读验收；`dc_daily` 已完成 Wealth/QTF/DG 代表查询与最小 TaskRun 验收，尚待两个既有 workflow 的自然 M3b；其余数据集按自身消费者逐项执行。

因此，名单已固定，但每项当前状态仍是“候选”；未通过第 7 节门禁前禁止 drop serving 表。

### 2.4 当前代码消费者清单

2026-08-27 `moneyflow_ind_dc` M0 复审时 CodeGraph 索引为 current，覆盖 2,718 个文件、47,985 个节点和 111,182 条边；本轮重新审计了 Definition、request builder、writer、raw/serving ORM、DAO、Ops workflow/readiness、Biz/Wealth、前端 API 消费者、Lake Console 和测试，并用精确代码搜索补齐动态 registry、schema 字符串和文档引用。

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
3. `moneyflow_ind_dc`：
   - `src/biz/queries/wealth/market/sector_overview/sector_metrics_query.py`
   - `src/biz/queries/wealth/market/sector_overview/sector_overview_state_query.py`
   - `src/biz/services/wealth/market/sector_overview/sector_heat_source_query.py`
   - `src/ops/services/sector_heat_upstream_readiness_service.py` 将其作为板块热度必需上游节点；`daily_moneyflow_maintenance` workflow schedule #4 负责自然同步；
   - Wealth 前端只消费 `/api/v1/wealth/market/sector-overview`，不读取物理 relation；Lake Console 直接读取 `raw_tushare.moneyflow_ind_dc`；
   - 本轮未发现 QTF、DG orchestrator 或 frontend 直接读取 `core_serving.board_moneyflow_dc`，不能把 `dc_daily` 的消费者机械归到本数据集。
4. `dc_daily`：
   - 对应 Wealth 板块查询；
   - `qtf/adapters/prod/sector_source_adapter.py`
   - `lake_console/orchestrator/src/orchestrator/defs/asset_guards/dc_board_source_probe.py`
5. `suspend_d/stk_limit`：
   - `src/biz/queries/wealth/market/index_detail/index_detail_query.py`
   - `src/biz/queries/wealth/market/sector_overview/sector_member_query.py`
   - `src/biz/queries/wealth/market/streak_ladder/streak_ladder_query.py`
   - `src/biz/services/wealth/market/sector_overview/effective_a_stock_pool_query.py`
   - `src/biz/services/wealth/market/sector_overview/sector_heat_source_query.py`
   - `src/biz/services/market_mood_calculator.py`
   - `src/biz/services/market_mood_walkforward_validation_service.py`
6. Lake Console：`lake_console/backend/app/services/prod_raw_db.py` 当前对一期 10 个数据集直接映射 `raw_tushare`；对应 trade-date 同步策略位于 `lake_console/backend/app/sync/strategies/prod_db_trade_date.py`。两个 auction 数据集不在当前映射中。
7. Ops/freshness：通过 `DatasetDefinition.storage.target_table` 的现有投影链读取目标 relation，不为一期维护第二套数据集白名单。

当前没有发现 `ServingPublishService` 对这 12 个 dataset key 的 target mapping，也没有发现仓库内显式 serving DAO DML 旁路。实施每个数据集前仍要重新跑相同审计；此处不能替代对仓库外消费者的运营登记。

## 3. 硬需求追溯账本

| ID | 硬需求 | 实现落点 | 正向门禁 | 反向门禁 | 当前状态 |
| --- | --- | --- | --- | --- | --- |
| RD-001 | raw 成为唯一物理事实表 | 对应 Definition、现有 `raw_only_upsert` | writer 仅调用 raw DAO | serving DAO 零调用 | P1-B0/B1 四项生产切换均已通过；原 serving 均为零物理字节 view |
| RD-002 | 原 serving 名称和业务列合同不变 | 每数据集独立 migration、原 serving ORM | ORM/SQL 查询结果一致 | 禁止改 Biz/QTF/DG relation 名 | P1-B0/B1 四项生产合同已实证；`moneyflow_ind_dc` M0 已完成切换前 18 字段等价证明 |
| RD-003 | serving 禁止写入 | Definition + DB INSTEAD OF reject trigger | SELECT 正常 | INSERT/UPDATE/DELETE 均失败 | P1-B0/B1 四项生产三类 DML 均以 SQLSTATE `55000` 拒绝 |
| RD-004 | 全量事实无差异 | 生产维护窗口分块对账 | 两层差集均为 0 | 任一差异阻断 migration | 5/12 已证；`moneyflow_ind_dc` 36 月与全表均为 0 差异 |
| RD-005 | raw 索引覆盖查询 | raw ORM index 声明、生产索引、计划基准 | 代表查询使用等价索引 | 计划/延迟退化阻断 | 已切换项通过；`moneyflow_ind_dc` M0 三类代表查询结构等价，热缓存差约 5.0% |
| RD-006 | 现有 schedule 不重建 | action key/date/capability 不变 | 暂停后原 schedule 恢复 | 禁止自动 seed/重建 | P1-B0/B1 资金数据集一直由 schedule #4 workflow 覆盖；本专项未创建或重建 schedule |
| RD-007 | Lake/DG 已知读取合同不变 | Lake raw 白名单、DG `dc_board_source_probe` | 既有测试与真实只读查询通过 | 禁止切换 Lake source 或写 Lake | 静态审计完成 |
| RD-008 | 不改变源端请求 | Definition 只改 storage | connector/request 测试不变 | 禁止改 fields/分页/date model | 已切换四项均保持原请求合同；`moneyflow_ind_dc` M0 明确禁止修改 18 字段、分页与日期模型 |
| RD-009 | 一个数据集一个发布单元 | 独立 revision/commit/deploy 记录 | M3a 独立授权；M3b 统一登记并按数据集节点验收 | 禁止批量 drop、外推生产授权或把“尚未触发”当成失败 | 已固定；仅已发现且未解决的共享运行链异常阻塞后续 M3a |
| RD-010 | owner/grant/comment 可追溯 | migration 动态快照与恢复 | 非 owner SELECT 权限一致 | 未知 grant/comment 阻断 | P1-B0/B1 四项生产 owner、既有读取权限与 comment 状态均保持不变；后续仍逐表冻结 |
| RD-011 | Ops 观测改读 raw | `target_table` 派生、freshness registry | 新 TaskRun/freshness 读 raw | 历史 TaskRun 不回写 | P1-B0/B1 四项切换后 TaskRun 均写 raw 并由原 serving view 即时可见 |
| RD-012 | 失败不破坏 raw | 同事务 DDL、禁止自动 downgrade | 提交前失败原子回滚 | 禁止清表/删 raw | 已切换四项的隔离 M2 均完成事务回滚门禁；生产未执行清表、删 raw 或自动 downgrade |

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
4. M3b 尚未到触发时刻、尚未统一查看或目标节点因上游 `fail_fast` 而未执行时，状态均为“待验收”，不是失败，默认不阻塞后续数据集另行授权的 M1/M2/M3a；
5. M3b 若实际观察到失败，先按目标 node、源端、调度、worker、写入或下游消费归因。只有已经发现且尚未解决、可能影响后续切换的共享 schedule/runtime/writer 问题才阻塞下一次生产 M3a；已证明无关的单数据集源端问题只记录在对应数据集，不扩大为全批次门禁；
6. 同一自然 workflow 可以在一次 TaskRun 中分别关闭多个数据集的 M3b，但必须逐个核对目标 `TaskRunNode`；父 TaskRun 成功不能替代节点证据，某个节点成功也不能替代其它节点。

#### 夜间自然任务统一验收台账

夜间才能出现的 schedule/probe 证据统一登记到下表，在后续只读验收窗口集中查看；不再为了等待触发反复中断白天的编码、隔离验证或已独立授权的生产 M3a。每次 M3a 完成后只追加该数据集的待验收项，不创建额外任务、不重复请求源端。

| 完整阶段编号 | 数据集 | 自然入口 | 必查证据 | 当前登记状态 |
| --- | --- | --- | --- | --- |
| `P1-B0-market-M3b` | `moneyflow_mkt_dc` | `daily_moneyflow_maintenance` schedule #4；B0 原台账漏登记该 workflow step | 父 TaskRun；市场目标 node 的时间输入、读取、保存、reject、去重、分页；raw/view 当日一致性 | TaskRun `9244` 补充验收通过；20:07 延迟不作为准点性证据 |
| `P1-B1-industry-M3b` | `moneyflow_ind_ths` | `daily_moneyflow_maintenance` schedule #4，候选触发 `2026-08-24 20:00+08` | 父 TaskRun；行业目标 node 的时间输入、读取、保存、reject、去重、分页；raw/view 当日一致性 | TaskRun `9244` 验收通过；20:07 延迟不作为准点性证据 |
| `P1-B1-concept-M3b` | `moneyflow_cnt_ths` | 同一 workflow 和同一 TaskRun | 父 TaskRun；概念目标 node 的时间输入、读取、保存、reject、去重、分页；raw/view 当日一致性 | TaskRun `9244` 验收通过；20:07 延迟不作为准点性证据 |
| `P1-B1-margin-M3b` | `margin` | schedule #33 恢复后生成的固定源端 probe rule #14；自然窗口 `2026-08-27 09:00..09:30+08` | rule 字段、源端 readiness、实际 TaskRun、每日触发上限、三交易所 unit、分页/reject、raw/view 当日一致性 | TaskRun `9573` 自然验收通过；当日只触发 1 次 |
| `P1-B2-dc_daily-M3b` | `dc_daily` | `daily_market_close_maintenance` schedule #24（18:30）与 schedule #2（21:02）；首个候选目标日 `2026-08-28` | 分别核对两个父 TaskRun 与 `dc_daily` node 的目标日、状态、读取、保存、reject、去重和分页；raw/view 当日行数、唯一身份与业务字段一致；第二次执行幂等且不制造重复 | **TODO：待两个自然 workflow 完成后只读验收；不创建额外任务、不重复请求源端** |

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
11. M3 后全部服务恢复 active、开放 TaskRun 为 0；本轮没有创建或重建 schedule，但后续审计确认该数据集一直是 `daily_moneyflow_maintenance` schedule #4 的 workflow step，原“没有 schedule”口径是消费者审计遗漏。catalog 可确认释放的 serving 物理 relation 为 237,568 B；根文件系统可用字节受发布依赖、WAL 和运行噪声影响反而减少，不能用一次 `df` 差值替代 relation 释放量。

### P1-B1：专属顺序、M0 与行业/概念 M1～M3 证据

P1-B1 固定按 `moneyflow_ind_ths -> moneyflow_cnt_ths -> margin` 顺序推进；每项都必须依次完成 M1 编码、M2 隔离 PostgreSQL、M3 生产验收，禁止把三个 relation 放进同一个 revision 或维护窗口。2026-08-24 M0 证据如下：

1. 生产 Alembic head 为 `20260824_000146`；六个 raw/serving relation 均为 `goldenshare_user` 所有的 `pg_default` 物理表，三张 raw 表保留 `lake_raw_reader` SELECT，三张 serving 表没有非 owner grant 或 comment；
2. 行业为 42,030 / 42,030 行、日期 `2024-09-10..2026-08-21`；概念为 181,560 / 181,560 行、日期相同；margin 为 1,146 / 1,146 行、日期 `2025-01-02..2026-08-21`。三项行数均等于各自主键身份数；
3. 行业与概念按 `trade_date` 索引拆成 24 个自然月，逐窗比较全部 12 个业务字段，双向 `EXCEPT ALL` 均为 0；margin 的 9 个业务字段全量双向差集为 0；
4. 三张 serving 表的 inheritance、外键、用户 trigger、列 ACL、RLS、依赖 view/function、rewrite rule、扩展统计、security label 和 publication 均为 0；约束只有主键，raw 的两个等价查询索引均 valid、ready 且位于 SSD；
5. 生产当前无开放 TaskRun、无超过 5 分钟事务。`daily_moneyflow_maintenance` 是 active 工作流 schedule，包含行业、概念以及已完成 P1-B0 的市场资金等 7 个 step；`margin.maintain` 是 active 固定源端 probe，窗口 `09:00..09:30`、300 秒间隔、每日最多触发一次。生产迁移前必须按 workflow/schedule 反查真实覆盖关系并暂停，禁止只按 dataset action key 查找自动入口；
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
11. schedule #4 通过正式服务恢复为 active，`next_run_at` 仍为 `2026-08-24 20:00+08`；`ops.config_revision` 留有同一用户的 `paused/resumed` 审计记录。最终 Web、worker、scheduler 及相关 Ops worker 全部 active，开放 TaskRun 为 0；首个正常工作流当时尚未到触发时间，因此 `P1-B1-industry-M3b` 已进入统一夜间验收台账，待核验本身不阻塞 `moneyflow_cnt_ths` 的 M1/M2/M3a；
12. 根盘可用空间从维护窗口前 4,461,560 KiB 变为验收后的 4,485,480 KiB，但发布依赖、WAL 与运行噪声会影响 `df`；因此只以 catalog 的 9,756,672 B 作为本项已释放 serving 物理量，不把文件系统瞬时差额当作精确收益。

P1-B1 第二项 `moneyflow_cnt_ths` M1 于 2026-08-24 完成，实际落点固定为：

1. Definition 只把 storage 改为既有 `raw_only_upsert + raw_with_serving_view`；12 个 source fields、`ts_code` filter、日期模型、point/range unit、5,000 行源端分页、能力与 `daily_moneyflow_maintenance` 工作流 action key 均保持不变；
2. raw ORM 只补齐生产已存在的 `trade_date` 与 `(ts_code, trade_date)` 两个索引 metadata，不创建、删除或搬迁物理索引；
3. 独立 revision `20260824_000148` 连接编码时真实 head `20260824_000147`，只处理 `raw_tushare.moneyflow_cnt_ths -> core_serving.concept_moneyflow_ths`；按自然月完成持锁双向 `EXCEPT ALL`，任一月任一层超过 20,000 行即在 DDL 前 fail-closed；
4. migration 要求复用且严格验证现有 `core_serving.reject_raw_direct_serving_view_dml()`，不重建共享函数、不修改市场或行业 view；概念 view 使用独立 `trg_concept_moneyflow_ths_reject_dml`；
5. view 显式投影 `trade_date, ts_code, name, lead_stock, close_price, pct_change, industry_index, company_num, pct_change_stock, net_buy_amount, net_sell_amount, net_amount` 及 `fetched_at AS created_at/updated_at`；migration 保留 owner、SELECT grant、relation/column comment，禁止 `CASCADE`、删除 raw 和自动 downgrade；
6. Definition、source/request/filter 正反例、planner、ORM 字段类型/空值/索引、raw-only writer、freshness 投影、ServingPublish 旁路、migration 锁顺序/月上限/共享函数前置/显式 SQL/离线 PostgreSQL 渲染与禁止 downgrade 测试均通过；M1 未连接 PostgreSQL、未调用 Tushare、未部署、未应用 migration、未创建 TaskRun 或修改 schedule。

P1-B1 第二项 `moneyflow_cnt_ths` M2 于 2026-08-24 在临时、仅 Unix socket 可访问的 PostgreSQL 18.4 隔离实例完成。实例中的角色、数据库、结构和数据均为本轮受控创建，应用 migration 的 `concept_m2_app` 为非超级用户；每套验证库在 Alembic 前均通过独立 env URL、数据库名、用户、空 `inet_server_addr()`、端口和管理员侧临时 `data_directory` 六项门禁。没有连接 Prod、调用 Tushare、部署服务、创建 TaskRun 或修改 schedule。

实测结论如下：

1. 成功库以 revision 147 的 181,560 行 raw/serving 等价样本为基线，覆盖 `2024-09-10..2025-12-13`、181,560 个唯一 `(trade_date, ts_code)`，单月最大 12,245 行。migration `20260824_000147 -> 20260824_000148` 以非超级用户成功；
2. 切换后 raw OID 保持不变并继续作为物理表，`core_serving.concept_moneyflow_ths` 成为普通 view；raw/view 均为 181,560 行和 181,560 个唯一身份，12 个业务字段双向 `EXCEPT ALL` 与 `fetched_at -> created_at/updated_at` 差异均为 0；
3. serving owner、relation comment、列 comment、PUBLIC SELECT、普通角色 SELECT 和 `WITH GRANT OPTION` SELECT 完整恢复；raw reader 仍可查询 181,560 行。拒写函数保持 `SECURITY INVOKER`、`search_path=pg_catalog`、返回 trigger 且未向 PUBLIC 开放执行权限，概念独立 trigger 为 enabled；
4. serving view 的 INSERT、UPDATE、DELETE 均以 SQLSTATE `55000` 拒绝，三类失败事务均完成回滚。隔离 SQL 对 raw 的 INSERT/UPDATE/DELETE 会被 view 在同一事务即时反映，最终回滚无残留；正式 `DatasetWriter` 也只写 `raw_tushare.moneyflow_cnt_ths`，view 同事务可见，回滚后目标行不存在；
5. 日期点查、代码日期范围和最大日期查询切换后分别下推 `idx_raw_tushare_moneyflow_cnt_ths_trade_date`、`idx_raw_tushare_moneyflow_cnt_ths_ts_code_trade_date` 和 raw 主键；没有顺序扫描或临时文件。受缓存影响，隔离样本切换前后单次执行时间分别为 `0.278/0.046 ms`、`0.672/0.388 ms`、`0.490/0.023 ms`，这些数字只证明计划形态未失控，不能替代生产 M3 的真实计划与时延验收；
6. 负向容量库在同一自然月放入 20,001 行后，migration 在 DDL 前以 `monthly reconciliation exceeds safety cap` 明确失败；revision 仍为 147，raw/serving OID、物理表类型、各 20,001 行和零用户 trigger 均不变；
7. 另一套 181,560 行库在旧 serving 表已执行 DROP、下一条语句注入异常后完成事务回滚；revision 仍为 147，旧物理表 OID、181,560 行、三个索引、权限和注释与迁移前逐项相同；
8. 隔离实例已停止，受控目录已可恢复地移入废纸篓；M2 不产生可复用环境，也不构成生产部署、migration、TaskRun 或 schedule 授权。

P1-B1 第二项 `moneyflow_cnt_ths` M3a 于 2026-08-24 在生产完成。验收结论与执行偏差如下：

1. 部署版本为 commit `7450423c`，远端分支和工作区与该提交一致。运营按标准部署流程完成部署后，生产 Alembic 已为 `20260824_000148`，`core_serving.concept_moneyflow_ths` 已是普通 view；也就是说 migration 在本次 M3a 正式暂停 schedule/worker 前被部署流程自动应用。本轮没有重复执行 migration，也不能倒推或补造“切换前已暂停”的证据；该项记为发布顺序不符合 M3a 合同的流程偏差，而不是数据验收通过后将偏差抹去。
2. 发现偏差后的只读检查确认 PostgreSQL `16.13`、无开放 TaskRun、无超过 5 分钟事务、无目标 relation 锁；随后通过正式 `OperationsScheduleService` 于 `16:51:59+08` 暂停 `daily_moneyflow_maintenance` schedule #4，并停止 scheduler 与 generic worker，后续 DML、查询和 TaskRun 验收均在受控窗口内执行。
3. raw 保持 `pg_default` 物理表，三个既有索引均 valid/ready；serving 为 0 B 普通 view。原 serving 物理量基线为 43,958,272 B，切换后不再占用第二份 heap/index；验收时 raw 总大小为 47,087,616 B。根盘 `df` 仍为 98%，发布依赖、WAL 和并行系统任务会影响瞬时水位，因此释放量只采用 relation catalog 基线，不用文件系统差额替代。
4. raw/view 均为 181,560 行和 181,560 个唯一 `(trade_date, ts_code)`，日期范围均为 `2024-09-10..2026-08-21`，单月最大 9,070 行；12 个业务字段全量双向 `EXCEPT ALL` 均为 0，`fetched_at -> created_at/updated_at` 映射差异为 0。
5. view 显式列顺序、投影 SQL、owner `goldenshare_user` 均符合契约；raw 的 `lake_raw_reader` SELECT 权限保持不变，serving 原无非 owner grant/comment 的状态未漂移。共享拒写函数仍为 `SECURITY INVOKER`、固定 `search_path=pg_catalog`、返回 trigger 且未向 PUBLIC 授权；概念独立 trigger 为 enabled。
6. serving view 的 INSERT、UPDATE、DELETE 均以 SQLSTATE `55000` 和明确的 raw-backed view 拒写信息失败；三类验证在显式事务中执行并回滚，raw 行数前后均为 181,560，没有测试残留。
7. 生产日期点查 `2026-08-21` 下推日期索引，返回 387 行、执行 `0.182 ms`；代码 `885311.TI` 的 2026 年区间查询下推 `(ts_code, trade_date)` 索引，返回 153 行、执行 `1.069 ms`；最大日期查询反向扫描 raw 主键，执行 `0.036 ms`。三类查询均无顺序扫描或临时文件，单次微秒值只作为计划形态证据。
8. Web、date-completeness 和 task-completion 服务通过正式 restart 回收连接池，两个健康端点均返回 200；generic worker 在静态验收和唯一待执行任务核对完成后才启动，scheduler 继续保持停止。QTF 和两个分钟 worker 未发现该 relation 消费者，且分钟 worker 原本即为 inactive，因此没有为本项擅自启动无关服务。
9. 正式最小 TaskRun `9224` 通过 `ManualActionCommandService -> DatasetActionResolver -> TaskRun` 主链创建，只请求 `2026-08-21` 一个 point unit。任务 success、`1/1` unit 完成、0 失败；源端 1 页读取 387、短页结束、0 重试，归一化前去重 387、保存 387、拒绝 0、去重 0、issue 0。
10. 写后 `2026-08-21` 的 raw/view 均为 387 行和 387 个唯一身份，业务字段双向差集为 0，387 行 `fetched_at/created_at/updated_at` 均为本次执行时间；全表仍为 181,560 行，证明本次为按主键幂等刷新，没有制造重复数据。当前通用诊断把所有 writer 的细分计数放在名为 `persistence.immutable_fact` 的容器中；raw-only upsert 不提供 inserted/matched 拆分，因此本项以 `rows_saved=387`、目标日身份数和全表前后行数完成写入对账，不把该容器中的零值误解释成“未写入”。
11. schedule #4 于 `17:00:01+08` 通过正式服务恢复为 active，cron 仍为 `0 20 * * 1-5`、时区 `Asia/Shanghai`、下一次 `2026-08-24 20:00+08`；config revision 97/98 分别记录本轮 pause/resume。worker、scheduler、Web 和相关 Ops worker 最终均为 active，两个健康端点为 200；恢复 scheduler 后正常到点产生的新闻 TaskRun `9225/9226` 均成功，最终开放 TaskRun 为 0。
12. `P1-B1-concept-M3a` 据此通过，但发布顺序偏差保留为残余流程风险。后续生产 M3a 必须在部署前先暂停目标自动入口和执行 worker，并使用不会自动迁移的部署模式；只有进入维护窗口后才单独应用 migration。标准完整部署不可再被当作“只部署代码、稍后迁移”。概念首个自然工作流验证已登记为 `P1-B1-concept-M3b`，与行业 M3b 一起在夜间按目标 node 只读验收，待验收本身不阻塞 `margin` 的独立 M1/M2。

#### 2026-08-24 当日暂停点

18:07+08 使用生产只读事务和只读主机命令重新核验，不执行部署、migration、DDL、DML、TaskRun 创建或 Tushare 请求：

1. 生产 Alembic 为 `20260824_000148`，生产代码检出为 `bbcff0e7`。`core_serving.market_moneyflow_dc`、`industry_moneyflow_ths`、`concept_moneyflow_ths` 均为 0 B 普通 view，显式读取各自 raw 表；三张 view 均有 enabled 的 `INSTEAD OF INSERT/UPDATE/DELETE` 拒写 trigger；
2. 市场 raw/view 均为 812 行和 812 个唯一交易日，行业 raw/view 均为 42,030 行和 42,030 个唯一 `(trade_date, ts_code)`，概念 raw/view 均为 181,560 行和 181,560 个唯一身份；三组日期范围与 M3a 验收一致；
3. `margin` raw/serving 仍是两张 `pg_default` 物理表，均为 1,146 行和 1,146 个唯一 `(trade_date, exchange_id)`，日期范围 `2025-01-02..2026-08-21`。这证明 margin 仍停留在 M0 等价审计，不能因 probe 契约修复已编码而误记为 raw 直出 M1 已完成；
4. schedule #4 为 active，下一次为 `2026-08-24 20:00+08`，当天尚无该 schedule 生成的 TaskRun，因此行业与概念 M3b 保持“尚未到触发时刻”；
5. TaskRun `9229`（`stk_mins`）与 `9230`（`index_mins`）当时均为 running，进度分别为 17,368/29,450 和 2,200/2,650 unit。它们虽与本次 relation 无关，但任何开放任务都使新的生产维护窗口门禁不成立，所以当日迁移在此停止；
6. 根盘已由运营扩容至名义 270 GB；实际文件系统总容量为 285,230,424,064 B，可用 55,484,956,672 B、使用率 80%。扩容仅增加安全缓冲，不放宽“一次一个数据集、无开放任务、先暂停自动入口、显式 migration、即时验收”的合同；
7. 本地 commit `6221f5d9` 及 revision `20260824_000150` 已完成 pure-probe 时间字段收口，但尚未推送或部署，生产 schedule #33 仍处于 revision 148 的历史字段状态。本地 revision 149/150 与生产 148 的差异必须在未来 margin 生产 M3a 前独立审计和处理，不得由 margin migration 或标准部署顺带隐式应用。

以上内容是 `18:07+08` 的暂停快照，不再代表夜间验收后的当前状态；后续事实以如下记录为准。

#### 2026-08-24 夜间 M3b 与 revision 150 验收

本轮只读审计未创建 TaskRun、未修改 schedule、未写业务数据，也未额外请求 Tushare。当前生产代码、本地 HEAD 与远端 `dev-interface` 均为 commit `dc8d4eed`，生产 Alembic 已升至 `20260824_000150`；revision 149/150 均已应用，pure-probe 约束有效，schedule #33 的 `cron_expr` 与 `next_run_at` 已归一化为 `NULL`。

schedule #4 `daily_moneyflow_maintenance` 生成 TaskRun `9244`。父任务为 scheduled 触发，状态 success，七个 workflow step 全部完成：`unit_total/unit_done/unit_failed=7/7/0`，`rows_fetched/rows_saved/rows_rejected/rows_deduplicated=18,267/18,267/0/0`。任务于 `20:07:29.268470+08` 创建、`20:08:25.318186+08` 开始、`20:08:56.765062+08` 结束；它证明数据链正常，但由于部署 migration 的锁等待错过了候选 `20:00` 时刻，不能作为准点触发 SLA 证据。

| 完整阶段编号 | 数据集 | 目标日期 | node 读取/保存/拒绝/去重 | 分页证据 | raw/view 当日对账 | 结论 |
| --- | --- | --- | ---: | --- | --- | --- |
| `P1-B0-market-M3b` | `moneyflow_mkt_dc` | `2026-08-24` | `1/1/0/0` | 1 页、短页结束、0 重试、未截断 | `1/1` 行、唯一身份 `1/1`；15 个业务字段双向差集 0，审计时间映射差异 0 | 通过 |
| `P1-B1-industry-M3b` | `moneyflow_ind_ths` | `2026-08-24` | `90/90/0/0` | 1 页、短页结束、0 重试、未截断 | `90/90` 行、唯一身份 `90/90`；12 个业务字段双向差集 0、空 `ts_code` 0、审计时间映射差异 0 | 通过 |
| `P1-B1-concept-M3b` | `moneyflow_cnt_ths` | `2026-08-24` | `387/387/0/0` | 1 页、短页结束、0 重试、未截断 | `387/387` 行、唯一身份 `387/387`；12 个业务字段双向差集 0、空 `ts_code` 0、审计时间映射差异 0 | 通过 |

revision 150 的部署同时暴露了一项尚未修复的共享运行链风险：`/api/v1/ops/schedules/stream` 使用 request-scoped `Session` 持续轮询。数据库 PID `37355` 自 `19:45:59+08` 起处于 `idle in transaction`，并持有 `ops.schedule` 的 `AccessShareLock`；migration PID `38772` 在新增 pure-probe check constraint 时等待 `AccessExclusiveLock`，scheduler PID `37410` 又排在 migration 后。生产 `lock_timeout=0`、`idle_in_transaction_session_timeout=0`，因此该 SSE 连接若不结束，migration 会无限等待。连接释放后 migration 已正常提交，服务和健康端点恢复；但“最终成功”不能替代根因修复。

该问题不阻塞 `margin` 的 M1 编码或 M2 隔离验证；在 SSE 改为有界短事务并完成回归、生产 migration 增加锁预检和有界等待之前，任何后续生产 M3a 均不得开始。

#### 2026-08-26 `P1-GATE-SSE-M1` 编码与自动化测试

本阶段开始前只读复核了当前代码、生产状态和后续影响面；没有部署、执行 migration、创建 TaskRun、修改 schedule、写业务数据或请求 Tushare。复核时生产代码为 commit `0cfc7e79e6a1d0303cc7164b71d443071ef343e7`，生产与本地 Alembic head 均为 `20260825_000151`，且没有 queued/running/canceling TaskRun。schedule #33 仍为 active pure-probe，`cron_expr/next_run_at` 均为 `NULL`，活动 probe rule 为 `09:00..09:30`、300 秒间隔、每日最多一次。

同一只读复核确认 `margin` raw/serving 仍是两张 `pg_default` 物理表，物理大小分别为 360,448 B 与 344,064 B；两层均为 1,149 行和 1,149 个唯一 `(trade_date, exchange_id)`，日期范围 `2025-01-02..2026-08-24`，9 个业务字段全量双向 `EXCEPT ALL` 差异为 0。根盘为 266 GiB 总量、206 GiB 已用、50 GiB 可用、81%；HDD 为 394 GiB 总量、62 GiB 已用、312 GiB 可用、17%。这些是 2026-08-26 的瞬时准入事实，不构成未来 M2/M3 执行授权。

代码复核确认原根因仍是 SSE endpoint 把 request-scoped `Session` 传入无限 generator，并在每两秒轮询后不结束读取事务；原 `alembic/env.py` 也没有在线 PostgreSQL migration 的集中锁等待上限。M1 按冻结合同完成以下最小改动：

1. `/api/v1/ops/schedules/stream` 只用请求会话完成 token 鉴权和会话工厂绑定，返回 `StreamingResponse` 前无条件回滚鉴权事务；无限 generator 不再接收或使用请求会话；
2. 每次 schedule/task signature 轮询都创建一个独立短会话；无论读取成功或抛错，都在 event/ping 输出或 2 秒休眠前回滚并关闭，不跨轮次持有连接、事务或 relation lock；
3. 前端既有 EventSource URL、`event: schedules`、JSON payload、`: ping` 和 2 秒轮询合同全部保持不变；本阶段不修改前端代码；
4. PostgreSQL 在线 Alembic migration 在自己的 migration transaction 内、`context.run_migrations()` 前执行 `SET LOCAL lock_timeout = '15s'`；非 PostgreSQL 与 offline SQL 不注入该设置，不修改数据库全局参数，也不增加 `statement_timeout` 或 `idle_in_transaction_session_timeout`；
5. `lock_timeout` 只限制等待数据库锁的时间。15 秒内无法取得所需锁时整次 migration 明确失败并回滚；取得锁后不会因为本设置而中止后续 DDL 或数据对账；
6. 自动化测试覆盖鉴权成功/失败均结束请求事务、每轮使用不同会话、读取成功/失败均回滚关闭、SSE event/ping 合同不变，以及 Alembic PostgreSQL dialect guard、offline 不注入和在线执行顺序。

本节记录 M1 完成时的阶段边界：当时仍须由 M2 证明持续 SSE 与真实 migration 回滚，再由独立授权的生产 M3 完成只读预检、部署后长连接观测和受控锁等待验收；后续小节已经记录这两项门禁的实际闭环证据。

#### 2026-08-26 `P1-GATE-SSE-M2` 隔离 PostgreSQL 验证

M2 在临时 PostgreSQL 18.4 隔离实例完成。实例只监听 `/private/tmp/p1-gate-sse-m2.FCOtvd/socket` Unix socket，端口 55448、`inet_server_addr()` 为 `NULL`、`listen_addresses` 为空；应用数据库/角色为 `goldenshare_gate_m2/goldenshare_m2_app`，应用角色非超级用户，管理员侧另行核对 `data_directory` 与 `gs_raw_cold_hdd` 路径均位于本轮临时目录。全程没有连接 Prod、调用 Tushare、部署服务、创建 TaskRun 或修改任何生产 schedule/业务表。

隔离环境准备过程保留两项真实修正证据：应用角色按 PostgreSQL 最小权限不能读取 `data_directory`，因此六项门禁严格拆成应用侧五项身份与管理员侧目录/tablespace 核对，没有为测试增加权限；首次 env 使用 `%2F` 编码 Unix socket 时，Alembic 在连接前被 ConfigParser 插值规则拒绝，改用 psycopg 同样支持的原始绝对 socket 路径后重新通过全部身份门禁，失败尝试没有创建 `alembic_version` 或修改结构。

实测结论如下：

1. 使用当前代码从空库完整迁移到 revision `20260824_000149` 成功，并建立一个管理员用户和一条受控 legacy pure-probe 行；该行固定为 `cron_expr='0 19 * * *'` 且 `next_run_at` 非空，只用于验证 revision 150 的归一化与回滚；
2. 通过最小 FastAPI/真实 HTTP 启动当前 `/api/v1/ops/schedules/stream`，HTTP 200，跨越多个 2 秒轮询周期收到 2 个 `event: schedules` 与 2 个 `: ping`；运行中修改隔离 schedule 的 `updated_at` 后按原协议收到第二个数据事件；
3. SSE 存续期间以 20ms 间隔完成 216 次 `pg_stat_activity/pg_locks` 采样。只命中 1 次查询结果返回到紧接 rollback 之间的瞬时 `idle in transaction`，事务年龄 0.997ms、连续采样 1 次；没有任何 idle session 持有 `ops.schedule/ops.task_run` relation lock，流结束后 `idle in transaction=0`。因此事务没有跨入 2 秒 sleep 或下一轮查询，不能把瞬时状态错误写成“数据库永远观察不到该状态”；
4. 在独立连接持有 `ops.schedule` 的真实 `AccessShareLock` 时执行 `20260824_000149 -> 20260824_000150`，Alembic 于 15.815 秒以 lock timeout 非零退出。失败后 revision 仍为 149，legacy probe 的 cron/next-run 原值保留，目标约束不存在，`ops.schedule` 仍为物理表，证明 UPDATE 与 DDL 在同一事务完整回滚；
5. 释放冲突锁后确认开放事务和目标 relation lock 均为 0；同一 migration 随即成功，legacy probe 被归一化为 `schedule_type='cron'`、`cron_expr/next_run_at=NULL`；物理约束名受仓库 naming convention 影响为 `ck_schedule_ck_ops_schedule_pure_probe_has_no_schedule_timing`，定义已 validated；
6. 负向 UPDATE 试图为 pure-probe 恢复 cron 时以 SQLSTATE `23514` 被拒绝，回滚后行保持归一化；新会话 `SHOW lock_timeout` 为 0，证明 `SET LOCAL` 没有污染数据库或连接全局；
7. 最后升级到当前 head `20260825_000151` 成功；revision 151 创建的 ETF 分区表及索引共核对 1,048 个 relation，位于非 HDD tablespace 的数量为 0。该项只证明当前迁移链没有被共享 gate 改动破坏，不构成 ETF 数据集额外验收；
8. 相关定向、schedule/probe、架构边界和部署脚本回归共 167 项通过。M2 不包含前端构建，SSE 浏览合同已由真实 HTTP event/ping 验证。

M2 据此通过，但只证明隔离实例中的事务与锁合同；生产结论见下述 M3 证据。

#### 2026-08-26 `P1-GATE-SSE-M3` 生产验收

M3 于 `2026-08-26 11:07..11:14+08` 完成。执行前确认生产数据库为 `goldenshare/goldenshare_user`、Alembic revision 为 `20260825_000151`，queued/running/canceling TaskRun 为 0，`ops.schedule`/`ops.task_run` 没有等待锁或长期事务；schedule #33 仍为 active pure-probe，`cron_expr/next_run_at` 均为 `NULL`，probe rule #12 仍为 `09:00..09:30`、300 秒间隔、每日最多一次。根盘约 51 GiB 可用，Web、worker、scheduler 和相关执行服务均为 active。

生产执行和验收证据如下：

1. 生产只部署已经推送到 `origin/dev-interface` 的 commit `99e1148f4429a9bc7bc4f9dea594b9a5733062d2`，其中 SSE/Alembic 修复来自 `a27f1470`。本轮只拉取代码、安装后端并重启 Web；没有执行数据库升级、构建前端、seed、同步 unit、重启 worker/scheduler、创建 TaskRun、修改 schedule/probe 或请求 Tushare；
2. 远端 `goldenshare` 运行用户当前不具备标准 `--platform-only` 脚本所要求的无密码 `systemctl` 权限，标准入口会在拉代码前失败。为避免修改 sudo 配置，本轮由 `goldenshare` 在部署锁内完成 `git pull + pip install`，随后由现有管理账号只重启 Web。发布后远端工作区干净，Web 主进程启动于 `11:09:44+08`，两个健康端点均返回 prod `ok`；这是已记录的发布工具权限边界，不得在后续步骤中误写成标准脚本已完整执行；
3. 使用生产 Web、真实管理员鉴权和 `/api/v1/ops/schedules/stream` 建立实际 SSE 连接，收到 HTTP 200、1 个 `event: schedules` 和跨越三个轮询周期的 3 个 ping。约 9 秒内以 20ms 间隔采样 302 次 `pg_stat_activity/pg_locks`，目标 SSE 事务命中 0 次 `idle in transaction`，连续跨采样次数 0，idle session 持有 `ops.schedule/ops.task_run` relation lock 的次数 0，锁等待次数 0；断流后开放 idle transaction、锁等待和目标 relation lock 均为 0；
4. 生产已经位于 Alembic head，没有安全理由倒退 revision 150 或重放业务 DDL。M3 因此先核对运行时 `get_settings()` 与 `/etc/goldenshare/web.env` 的数据库地址完全一致，再执行真实 Alembic `upgrade head` no-op；前后 revision 均为 `20260825_000151`。随后用不涉及业务 relation 的 PostgreSQL advisory transaction lock 制造受控冲突，竞争会话执行 `SET LOCAL lock_timeout='15s'` 后于 15.11 秒明确报 `canceling statement due to lock timeout`，持锁会话取消后残留 advisory lock、长事务和锁等待均为 0；
5. 第 4 项证明生产数据库中的 15 秒事务级锁等待有界，以及当前 Alembic 在线入口能安全连接正确生产库且不改变 head；它不冒充“在生产重演 revision 150 的失败回滚”。真实 migration 的失败原子回滚已经由 M2 的 revision 150 冲突实验完成，M3 不为重复证据而对生产结构做降级、临时 revision 或业务 DDL；
6. 最终生产 commit 为 `99e1148f`、Alembic 为 head 151、远端工作区变更数 0，全部相关服务 active，健康端点正常，开放 TaskRun、长事务、锁等待和目标 idle relation lock 均为 0。schedule #33 与 probe rule #12 的字段和最后触发事实未被本轮改变。

`P1-GATE-SSE-M3` 据此通过，共享生产门禁解除。该结论只关闭 schedule SSE 长事务和在线 Alembic 无界锁等待问题；`margin` 或其它数据集仍须获得各自的 M1/M2/M3a/M3b 授权并执行独立门禁。

#### 2026-08-26 `P1-B1-margin-M1` 编码与自动化测试

本阶段严格按 `margin` 自身合同推进，只修改 Definition 的 storage facts、新增单数据集 revision 和专项/既有参数化测试；没有连接 PostgreSQL、调用 Tushare、部署、应用 migration、创建 TaskRun，或修改 schedule/probe。编码前重新确认本地真实 Alembic head 为 `20260825_000151`，因此独立 revision 固定为 `20260826_000152`，不沿用行业、概念或历史文件名推断 `down_revision`。

实际落点如下：

1. `margin` Definition 只把 `core_dao_name/target_table/delivery_mode/layer_plan/write_path` 收敛为 `raw_margin/raw_tushare.margin/raw_with_serving_view/raw->serving_view/raw_only_upsert`；9 个显式 source fields、`next_open_day_0930` 发布事实、交易日 point/range、`exchange_id` 三交易所 fan-out、4,000 行 offset 分页、manual/schedule/retry 与固定源端 probe 合同全部保持不变；
2. 复用现有 `DatasetWriter._write_raw_only_upsert()`、`raw_margin` DAO 和既有 ORM；`RawMargin` 已声明 `(trade_date, exchange_id)` 主键、`trade_date` 与 `(exchange_id, trade_date)` 两个生产等价索引，因此 M1 没有修改 ORM、DAO factory、writer、resolver、request builder、normalizer、probe service、schedule capability resolver 或前端；
3. revision `20260826_000152` 只处理 `raw_tushare.margin -> core_serving.equity_margin`。它要求 raw/serving 均为当前用户所有的普通物理表，raw heap、主键索引和两个二级索引全部留在 `pg_default`，字段、主键、索引、约束、依赖、ACL、comment、trigger、RLS、rewrite、扩展统计、security label 与 publication 任一未知状态均 fail-closed；
4. migration 固定 `lock_timeout=15s`、`statement_timeout=120s`、`work_mem=16MB`，不使用特权 `temp_file_limit`；两层按 raw → serving 获取 `SHARE` 锁后，全表分别不得超过 5,000 行，并对 9 个业务字段执行双向 `EXCEPT ALL`、行数及 `(trade_date, exchange_id)` 身份唯一性核对，通过后才升级 serving 的 `ACCESS EXCLUSIVE` 锁；
5. view 显式投影 `trade_date, exchange_id, rzye, rzmre, rzche, rqye, rqmcl, rzrqye, rqyl`，并固定 `fetched_at AS created_at/updated_at`；migration 保留原 owner、非 owner SELECT grant、relation/column comment，复用且验证现有 `core_serving.reject_raw_direct_serving_view_dml()`，只为 margin 创建独立拒写 trigger；禁止 `CASCADE`、删除 raw、重建共享函数和自动 downgrade；
6. CodeGraph 对 Definition、resolver、raw-only writer、DAO/ORM、ServingPublish target、freshness、Ops probe 和 schedule 消费者做了影响面分析；精确静态搜索未发现仓库内 serving DML 旁路。`margin_remote_probe_service` 只用正式 resolver 生成三交易所 point unit 并探测源端，不读取或写入 serving relation，因此本次 storage 收口不需要改变 probe；
7. 自动化测试已覆盖 Definition 未变事实、三交易所默认/显式 filter 与未知 filter 反例、planner/request fields/4,000 行分页、raw-only writer、freshness raw target、ORM 字段/主键/索引、ServingPublish 无旁路、migration 独立性/有界资源/锁顺序/5,000 行上限/显式 view/共享函数前置/禁止回退和离线 PostgreSQL SQL 渲染；同时回归 Ops Catalog、固定 margin probe、schedule capability、source client、definition lint 与 runtime registry 均通过。

M1 据此完成，但只证明代码和静态 migration 合同。生产中 raw/serving 仍是两张物理表；下一阶段只能是另行授权的 `P1-B1-margin-M2`，在隔离 PostgreSQL 真实验证 migration、5,001 行 fail-closed、三类 DML 拒绝、事务回滚、view 即时可见与查询计划。M2 通过后仍需单独授权 M3a；M1 不构成生产部署或 migration 授权。

#### 2026-08-26 `P1-B1-margin-M2` 隔离 PostgreSQL 验证

M2 在临时、仅 Unix socket 可访问的 PostgreSQL 18.4 隔离实例完成。实例、角色、数据库、schema、数据与 HDD tablespace 均为本轮受控创建；应用 migration 的 `margin_m2_app` 为非超级用户。为规避仓库配置文件覆盖命令行 `DATABASE_URL` 的既知风险，本轮以不存在的独立 env 文件禁用默认配置加载，并在同一 Alembic 进程内先校验数据库名、用户、socket、端口、空 `inet_server_addr()`、`listen_addresses=''`、非恢复模式与非超级用户身份，任一不符即在 migration 前失败。负向身份门禁已证明错误数据库名不会推进 revision。M2 没有连接 Prod、调用 Tushare、部署服务、创建 TaskRun、修改 schedule/probe 或触碰正式数据。

验证结果如下：

1. 成功库从 revision `20260825_000151` 升至 `20260826_000152`。受控样本为 raw/serving 各 1,149 行、1,149 个 `(trade_date, exchange_id)` 身份，日期范围 `2020-01-01..2021-01-17`；9 个业务字段双向多重集差集与审计时间投影差异均为 0；
2. raw relation OID、主键与两个二级索引均保持不变且 valid/ready，heap 与索引继续位于 `pg_default`。serving 从 311,296 B 的物理表切换为 0 B 普通 view；本轮另建的 `gs_raw_cold_hdd` 仅用于验证环境边界，目标对象落入该 tablespace 的数量为 0，隔离 WAL 仍在实例默认数据目录；
3. 原 serving owner、relation/column comments、PUBLIC SELECT、普通角色 SELECT、`WITH GRANT OPTION` 均完整恢复；共享拒写函数仍为当前 owner、`SECURITY INVOKER`、`search_path=pg_catalog`、无 PUBLIC execute。view 的 `INSERT/UPDATE/DELETE` 均以 SQLSTATE `55000` 和固定拒写文案失败；
4. 对 raw 的 INSERT、UPDATE、DELETE 会由 serving view 在同一事务即时反映，事务回滚后行数恢复为 1,149。正式 `DatasetWriter` 也只写 `raw_tushare.margin`，两次 upsert 均由 view 即时可见，回滚后原值与行数完整恢复；freshness target 同样为 raw；
5. 日期点查、交易所日期范围、最大日期三类代表查询切换前后结果哈希一致，成本分别保持 `8.36/8.36`、`11.32/11.32`、`0.35/0.35`；交易所复合索引查询切换前后均为成本 `20.51`、366 行，并从 serving 等价索引下推到 raw 等价索引。所有查询临时块均为 0；这些证据证明隔离计划形态未退化，不替代生产 M3a 的真实计划和时延验收；
6. 5,001 行容量库在任何 DDL 前明确报 `raw=5001, serving=5001, cap=5000`，revision、relation OID/类型、行数和 trigger 均保持原状；证明上限是 fail-closed 而非截断；
7. 回滚库使用 revision 152 的真实 SQL，在同一事务内完成 serving `DROP TABLE -> CREATE VIEW -> trigger` 后立即注入失败；回滚后 revision 151、两张物理表、raw/serving OID、六个索引 OID/定义/有效状态、ACL、comments、行数和零用户 trigger 与执行前逐项一致；
8. 三个验证库结束前均无未结束的业务事务；隔离实例停止后移入本机废纸篓，未保留运行服务或监听端口。

`P1-B1-margin-M2` 据此通过。该结论只证明 revision 152 在受控 PostgreSQL 中满足数据等价、原子失败、权限恢复、拒写、raw-only writer 和查询计划合同；生产中 raw/serving 仍是两张物理表。下一阶段只能是另行授权的 `P1-B1-margin-M3a`，并必须重新执行生产实时只读预检、暂停 schedule #33 及其 probe rule、停 worker、应用 migration、回收连接池、核验真实查询计划和最小 TaskRun。后续固定源端 probe 的自然运行验收另记为 `P1-B1-margin-M3b`。

#### 2026-08-26 `P1-B1-margin-M3a` 生产切换与即时验收

M3a 于 `2026-08-26 13:33..13:45+08` 完成。开始前通过正式生产连接和主机只读命令确认 PostgreSQL `16.13`、数据库/用户为 `goldenshare/goldenshare_user`、revision 151、远端 commit `99e1148f`、工作区干净、开放 TaskRun 为 0、无目标等待锁或超过 5 分钟事务；根盘可用 54,220,095,488 B，HDD 可用 334,831,624,192 B。schedule #33 为 active pure-probe，`cron_expr/next_run_at` 均为 `NULL`，rule #12 为 `09:00..09:30`、300 秒、每日最多一次；当天 09:00 已成功触发旧双写合同下的 TaskRun `9445`，该历史事实不作为切换后的 M3b。

执行与验收证据如下：

1. 切换前 raw/serving 均为 `pg_default` 物理表，各 1,152 行和 1,152 个 `(trade_date, exchange_id)` 身份，日期范围 `2025-01-02..2026-08-25`；9 个业务字段双向 `EXCEPT ALL` 均为 0。raw/serving OID 分别为 `21743/21754`，总大小分别为 360,448 B/344,064 B；raw 的主键与两个二级索引均 valid/ready 且位于 `pg_default`；
2. 本地只推送已经提交的 `bbf6b63f/35bb0c0e/03803f43`，未提交工作区文件未进入远端。通过正式 `OpsScheduleCommandService` 暂停 schedule #33，config revision `103` 记录 paused，rule #12 被删除；只读回查确认 schedule paused、probe rule 0、开放任务 0 后，单独停止通用 worker。scheduler、Web 和无关专用 worker未被这一步停止；
3. 维护窗口内再次完成同一组 1,152 行全字段对账并确认无锁、无长事务。随后只使用正式生产 env 和 `bash scripts/deploy-systemd.sh dev-interface --maintenance-migration`：远端快进到 commit `03803f43`，只安装后端并执行 revision `20260825_000151 -> 20260826_000152`；前端/Wealth 构建、seed、unit 同步、服务重启均被该模式明确跳过；
4. migration 成功后 raw OID 仍为 `21743`，heap、主键和两个索引仍在 `pg_default`；serving 变为 OID `2023658`、0 B 普通 view，显式投影 9 个业务字段和 `fetched_at AS created_at/updated_at`。raw/view 均为 1,152 行和 1,152 个身份，业务双向差异和审计投影差异均为 0；owner/ACL 与原合同一致，raw 的 `lake_raw_reader` SELECT 未改变；
5. 共享拒写函数仍由 `goldenshare_user` 所有、`SECURITY INVOKER`、`search_path=pg_catalog`、不向 PUBLIC 授权；margin 独立 trigger enabled。对 view 的 INSERT、UPDATE、DELETE 均以 SQLSTATE `55000` 和固定文案拒绝，显式事务回滚后 raw/view 行数保持 1,152；
6. 切换前后三组结果 hash 固定为 `ee09ac9f6271b42b4a569badd2bed510`、`9f8f4c04fe51f74e9cdaf4934848b92a`、`be03abf2b2d4cee9fd091ca63801e2e9`。日期点查、交易所 90 行范围、最新 10 行和 2025 年 SSE 范围查询均下推 raw 等价索引；total cost 分别从 `9.42/15.58/1.28/43.94` 变为 `9.59/16.14/1.31/44.94`，变化均低于 4%，buffer/排序形态无不可解释放大。单次执行仍为亚毫秒级，只作为计划形态证据，不把微秒波动解释成稳定 SLA；
7. 仓库与 CodeGraph 未发现 Biz/QTF/DG 对该 serving relation 的直接读取。按实际消费者回收 Web、scheduler、date-completeness 和 task-completion 连接池，Web 两个健康端点通过；QTF 和分钟 worker 不属于该 relation 消费者，未做无关重启。随后启动加载新 Definition 的通用 worker；
8. 正式最小 TaskRun `9468` 通过 `ManualActionCommandService -> DatasetActionResolver -> TaskRun` 主链创建，只请求 point `2026-08-25`。plan 生成 SSE/SZSE/BSE 三个 unit，任务 success、`3/3/0`；源端共 3 页、每个 unit 1 页且短页结束，读取/归一化/保存 `3/3/3`、重试 0、reject 0、去重 0、issue 0、未截断；
9. TaskRun 后 `2026-08-25` raw/view 均为 3 行和 3 个交易所身份，本次刷新 `fetched_at` 的 raw 行为 3；全表仍为 1,152 行，业务双向差异和审计投影差异为 0。通用诊断中的 `persistence.immutable_fact` 插入/匹配细分不适用于 raw upsert，本项按既定合同使用 `rows_saved=3`、刷新时间和目标表行数完成写入对账；
10. 任务完成且开放任务归零后，通过正式服务恢复 schedule #33，config revision `104` 记录 resumed，并生成唯一 active rule #14；其 dataset/source/window/interval/max/condition/action 与原固定合同一致，`cron_expr/next_run_at` 继续为 `NULL`。最终远端 commit `03803f43`、工作区干净、所有相关服务 active、健康端点正常、开放任务/长事务/等待锁/目标等待锁均为 0；
11. catalog 可确认本项释放旧 serving 物理 relation 344,064 B。部署、依赖安装和 WAL 使根盘可用空间从 54,220,095,488 B 变为 54,199,353,344 B，瞬时 `df` 减少 20,742,144 B；该差值不否定 relation 释放量，也不能被当作本项净收益。

`P1-B1-margin-M3a` 据此通过。生产已经是 raw 唯一物理事实表和原 serving 名只读 view；代码读取合同不需要下游改名。在 M3a 完成时，尚未完成的是 `P1-B1-margin-M3b`：下一有效 probe 窗口为 `2026-08-27 09:00..09:30+08`，只需只读核对 rule #14 的 readiness、实际 TaskRun、每日触发上限、三交易所分页/reject 和 raw/view 当日一致性，不创建额外任务、不重复扫描源端。该待验收项已由下节记录的自然 TaskRun `9573` 关闭。

#### 2026-08-27 `P1-B1-margin-M3b` 自然 probe 验收与结案

本阶段只读取生产调度、任务与目标 relation，没有人工触发 probe、没有创建 TaskRun、没有重复请求 Tushare、没有修改生产状态。自然窗口后的验收证据如下：

1. schedule #33 保持 `active/cron/probe`，`cron_expr` 与 `next_run_at` 均为 `NULL`；唯一 active rule #14 仍固定为 `margin/tushare`、`09:00..09:30+08`、间隔 300 秒、每日最多 1 次、condition `remote_margin_ready`、action `margin.maintain`；
2. probe log `3674` 于 `09:00:01.266662+08` 成功命中，目标交易日 `2026-08-26`；3 次有界样本请求分别命中 SSE、SZSE、BSE，缺失交易所为空，并创建 TaskRun `9573`。当日该 schedule 只有 1 条 probe log、1 次命中和 1 个不同 TaskRun，符合每日最多一次；
3. TaskRun `9573` 为 `probe -> margin.maintain` point 请求，时间输入 `2026-08-26`、filters 为空，状态 success，unit `3/3/0`，读取/保存/reject/完全重复去重为 `3/3/0/0`，父任务和 node `15322` 均无 issue 或 reject reason；
4. node 分页诊断为 3 个 unit、3 页、0 重试、合并 3 行、0 个多页 unit、每 unit 最多 1 页、3 个短页结束、未截断；归一化前行数为 3，与读取和保存一致；
5. 目标日 raw/view 均为 3 行和 3 个交易所身份，业务字段及 `fetched_at -> created_at/updated_at` 投影双向差异均为 0；3 条 raw 行的 `fetched_at` 全部落在 TaskRun 执行窗口内。全表 raw/view 均为 1,155 行和 1,155 个唯一身份，日期范围 `2025-01-02..2026-08-26`；
6. `raw_tushare.margin` 仍为 360,448 B 物理表，`core_serving.equity_margin` 仍为 0 B 普通 view；生产 Alembic 为 `20260826_000152`，远端分支为 `dev-interface`、审计时 commit 为 `f732f8bd`，所有正式 Goldenshare Web/Ops 服务 active，开放 TaskRun 为 0。

`P1-B1-margin-M3b` 据此通过，`margin` 的 M0/M1/M2/M3a/M3b 全部完成并结案。本次没有观察到会阻塞后续批次的共享 scheduler、probe、worker、writer 或 raw/view 契约问题；下一阶段按固定顺序进入 `P1-B2-moneyflow_ind_dc-M0` 只读复审，不直接跳到 M1，也不复制 `margin` 的 probe 或小表容量结论。

### P1-B2 首项 `moneyflow_ind_dc` M0 只读复审与 M1 准入合同

本轮只读复审于 `2026-08-27` 完成。没有修改代码或生产配置，没有部署、迁移、暂停 schedule、创建 TaskRun、调用 Tushare 或写数据库。CodeGraph 使用 `query/impact` 覆盖 Definition、request builder、writer、ORM/DAO、Ops workflow/readiness、Biz/Wealth 与测试，再以仓库精确搜索补齐 Lake 的 schema 字符串和前端 API 消费链。

#### M0-1 当前数据集与写入事实

1. Definition 固定显式请求 18 个 source fields：`trade_date/content_type/ts_code/name/pct_change/close/net_amount/net_amount_rate/buy_elg_amount/buy_elg_amount_rate/buy_lg_amount/buy_lg_amount_rate/buy_md_amount/buy_md_amount_rate/buy_sm_amount/buy_sm_amount_rate/buy_sm_amount_stock/rank`；M1 不允许修改字段、日期模型、filters、分页、能力或请求 builder；
2. point/range 输入按开市交易日展开；每个日期默认 fanout 为 `行业/概念/地域` 三个 unit。每个 unit 请求固定携带 `trade_date + content_type`，可选 `ts_code` 仍只来自现有运营 filter；分页保持 `offset_limit/page_limit=5000`、无任意最大页数；
3. 当前 storage 为 `raw_moneyflow_ind_dc + board_moneyflow_dc`、`raw_core_upsert`。`DatasetWriter._write_raw_and_core()` 对同一 normalized batch 只按 ORM 列过滤后分别 upsert，没有第二层业务转换；M1 只切换为既有 `raw_only_upsert + raw_with_serving_view`，不修改共享 writer、source client、normalizer、resolver 或 planner；
4. raw/serving 业务主键同为 `(trade_date, content_type, name)`，18 个业务字段的类型与空值合同一致。生产两边都已有 `trade_date` 和 `(content_type, trade_date)` 两个有效二级索引；`RawMoneyflowIndDc` ORM 尚未声明这两个既存索引，M1 只补 metadata，不在数据库重复创建；
5. 最近自然 workflow TaskRun `9506` 的目标 node `15226` 成功处理 `2026-08-26`：三类 unit 分别返回 `31/504/496` 行，共 1,031 行；3 页均为短页、0 重试、0 reject、0 去重、保存 1,031。该运行证据用于确认当前主链，不替代 M3 的切换后验收，也没有产生额外源端请求。

#### M0-2 生产物理合同、数据等价与容量

1. 只读观测时生产分支/commit 为 `dev-interface/f732f8bd`，Alembic 为 `20260826_000152`；Web、通用 worker、scheduler、date-completeness worker 和 task-completion worker 全部 active，两个健康端点通过，开放 TaskRun、超过 5 分钟事务和目标 relation 锁均为 0；
2. `raw_tushare.moneyflow_ind_dc` 与 `core_serving.board_moneyflow_dc` 均为 owner `goldenshare_user`、`pg_default` 普通物理表，OID 分别为 `22869/22926`；两边 ACL 都只有 owner 全权限和 `lake_raw_reader` SELECT，relation/column comment 为空；
3. 两表均无 inheritance/partition、外键、用户 trigger、列 ACL、RLS/policy、外部 view/materialized view、function dependency、rewrite rule、扩展统计、security label 或 publication；因此 M1 不需要 `CASCADE`，出现任一新增对象即 fail-closed；
4. raw/serving 各 339,268 行，日期范围均为 `2023-09-12..2026-08-26`；分类行数一致：地域 11,377、概念 167,894、行业 159,997。空 `ts_code` 为 0，非空 `(trade_date, content_type, ts_code)` 重复组为 0，raw `api_name` 异常为 0；
5. 按 36 个自然月逐窗比较全部 18 个业务字段，每月 raw-only/serving-only 均为 0；再做一次全表多重集复核，双向 `EXCEPT ALL` 仍均为 0。M0 因而关闭“只有行数一致、内容尚未证明”的旧结论；
6. 实测单类单日峰值 509 行、全分类单日峰值 1,031 行、自然月峰值 23,541 行。M1 migration 固定按自然月对账、每层 `30,000` 行上限、`work_mem=16MB`，30,001 行 fixture 必须在任何 DDL 前失败；不复制 THS 的 5,000/20,000 上限，也不在锁内追加一次无界全表差集；
7. raw 物理大小 94,789,632 B（90.40 MiB），serving 物理大小 88,358,912 B（84.27 MiB）。本项切换不新增 raw 索引，预期 SSD catalog 毛释放量就是 88,358,912 B；根盘当前可用 52,376,059,904 B、HDD 可用 334,694,993,920 B，仅作为 M0 水位快照；
8. raw `fetched_at` 与 serving `updated_at` 339,268 行全部一致，但 serving `created_at` 有 10,191 行与 `fetched_at` 不同。已登记消费者不读取审计列，view 仍按一期统一合同投影 `fetched_at AS created_at/updated_at`；因此业务读取透明成立，但历史 `created_at` 值明确不属于透明承诺。

#### M0-3 消费者、查询计划与透明边界

1. serving 直接消费者只有 Wealth/Biz：`SectorOverviewStateQuery` 用三类资金流的最新共同交易日，`SectorMetricsQuery` 用同日 `ts_code/net_amount`，`SectorHeatSourceQuery` 用概念板块最近 10 个完成交易日的 `ts_code/net_amount/net_amount_rate` 并要求 `(trade_date, ts_code)` 唯一；
2. Wealth 页面通过 `/api/v1/wealth/market/sector-overview` 消费后端结果，不引用物理 relation。M1 不需要前端代码、action-key 或字段白名单改动；M2 必须运行现有 Wealth API/服务回归，带生产数据和登录态的浏览验收仍属于 M3a；
3. Lake Console 的 `prod-raw-db` 已直接读取 `raw_tushare.moneyflow_ind_dc` 的 18 个字段，排序键为 `content_type/ts_code`；本轮未发现 QTF 或 DG orchestrator 对 `core_serving.board_moneyflow_dc` 的直接读取，因此 Lake/DG 不需要改 source；
4. raw 与 serving 的最大日期查询计划同为日期索引反向扫描，实际 `0.125/0.172 ms`；同日概念聚合均为日期索引扫描，`1.311/1.343 ms`；10 日 Heat 代表查询在公平热缓存下均为相同嵌套循环/索引计划，返回 5,040 行，raw/serving 为 `19.275/18.355 ms`，raw 慢约 5.0%，低于 20% 门禁；
5. 首次 raw 10 日查询曾出现 `129.533 ms`，随后相同查询为 `19.275 ms`。计划显示额外耗时主要来自共同依赖 `dc_index` 的 505 个冷页读取，serving 紧随其后复用了缓存；不能把这个顺序效应误判为 raw relation 退化。M2 用两套完整隔离复验核对计划形态与稳定结果，M3a 仍须在生产交错、重复测量 raw 与 view，并分别记录冷/热缓存，不用单次微秒值宣称 SLA；
6. 仓库内没有 `BoardMoneyflowDc.created_at/updated_at` 消费，也没有 serving DML、ServingPublish target mapping 或数据库依赖对象。仓库外 SQL/BI/catalog 工具仍无法由代码审计穷尽，继续作为生产 M3a 前的运营登记风险。

#### M0-4 M1/M2 范围与现存 Heat 时间契约阻塞项

`P1-B2-moneyflow_ind_dc-M0` 对 raw 直出代码准入通过。后续 M1 只允许修改该 Definition 的 storage、`RawMoneyflowIndDc` 的两个既存索引 metadata、新增一条接当时真实 head 的独立 migration，并新增本数据集测试；禁止改 request builder、source fields、writer、Ops workflow、Heat readiness、前端或 Lake。migration 必须显式投影 18 个业务字段和 `fetched_at AS created_at/updated_at`，动态恢复 owner/SELECT ACL/空 comments，复核共享拒写函数后创建本 view 独立 trigger，并覆盖 30,001 行超限、任一月差异、身份重复、未知依赖、三类 DML、事务回滚和离线 SQL。

M0 同时发现一项与 raw 直出无因果关系、但会阻断未来 M3a 的现存生产异常：schedule #4 `daily_moneyflow_maintenance` 固定在 `20:00`，而 Heat readiness 只接受 `21:00` 以后请求的同日资金工作流证据；schedule #36 在 `21:15` 开始检查后，`2026-08-20/21/24/25/26` 均于次日 `00:30` 以 `HEAT_AUTOMATION_SOURCE_TIMEOUT` 失败，原因明确为缺少 21:00 后的 `daily_moneyflow_maintenance` 证据。`daily_market_close_maintenance` 已有 21:02 执行，当前缺口只剩资金工作流时间合同。

该异常不改变 Definition、数据等价、raw 索引或 M1/M2 隔离实现，因此不阻塞另行授权的 M1/M2；但在其时间口径经独立审计、修正并恢复至少一次自然 Heat 成功基线前，禁止进入 `moneyflow_ind_dc` 生产 M3a。M0 不替用户拍板把 schedule 改到 21:00 后，或把 readiness 放宽到 20:00；两种业务口径必须另行评审，不能混入本数据集 migration。

#### 2026-08-27 `P1-B2-moneyflow_ind_dc-M1` 编码与自动化验证

M1 严格沿用 M0 冻结边界，没有请求 Tushare、连接生产或隔离数据库，也没有修改 shared writer/planner、Ops/Heat、前端或 Lake：

1. `moneyflow_ind_dc` Definition 只把 storage 从 `raw_core_upsert + single_source_serving` 改为 `raw_only_upsert + raw_with_serving_view`；`core_dao_name/target_table` 收敛为 `raw_moneyflow_ind_dc/raw_tushare.moneyflow_ind_dc`。18 个 source fields、point/range、三类 fanout、`content_type/ts_code` filters、5,000 行分页和能力合同均由正反向测试锁定不变；
2. `RawMoneyflowIndDc` 只补齐生产已存在的 `trade_date` 与 `(content_type, trade_date)` 两个索引 metadata，没有新增字段、索引 DDL、主键或类型变更；通用 writer 测试证明本数据集只调用 raw DAO，serving DAO 不再参与写入；
3. 新增独立 revision `20260827_000153`，`down_revision` 接编码时唯一真实 head `20260826_000152`。migration 固定 `lock_timeout=15s`、`statement_timeout=120s`、`work_mem=16MB`，先冻结 relation/owner/tablespace/列/三列主键/两个索引/ACL/dependency，再以自然月逐窗执行 18 字段双向 `EXCEPT ALL`；任一月任一层超过 30,000 行、身份数不一致或差集非零都在 serving 的 `ACCESS EXCLUSIVE` 和 `DROP TABLE` 前失败；
4. migration 不使用 `CASCADE`、不创建或删除 raw 索引、不修改 raw 数据，不重建共享拒写函数；它只复核既有函数合同，动态恢复原 serving owner、非 owner SELECT grant 和 comments，显式创建 20 列 view 与本 relation 独立的三类 DML 拒写 trigger。自动 downgrade 继续 fail-closed；
5. 新增 M1 专项测试，并补齐 Definition registry、raw-only writer 和日期完整性 target 的现有消费者测试。已验证离线 PostgreSQL SQL 可完整渲染、迁移操作顺序正确、未知依赖/30,001 行上限/非授权 filter/共享函数重建/`CASCADE`/自动 downgrade 均有反向门禁；Definition lint、架构护栏、Wealth/Heat 与日期完整性定向回归通过。

M1 结束时只证明了代码和静态 migration 合同，生产 Alembic 仍是 `20260826_000152`。当时的下一阶段 `P1-B2-moneyflow_ind_dc-M2` 必须在隔离 PostgreSQL 应用 revision 153，真实验证 30,001 行在 DDL 前拒绝、任一月差异、身份冲突、未知依赖、权限恢复、三类 DML、事务回滚、view 即时可见和代表查询计划；在随后取得 M2 授权前不得连接或写入任何数据库。

#### 2026-08-27 `P1-B2-moneyflow_ind_dc-M2` 隔离 PostgreSQL 验证

M2 在本轮受控创建的 PostgreSQL 18.4 临时实例完成，并做了两次完整正向复验。实例只监听私有 Unix socket，`listen_addresses=''`、`inet_server_addr() IS NULL`；应用 migration 的 `moneyflow_ind_dc_m2_app` 为非超级用户。每个验证库都使用只包含隔离连接的独立 env 文件，并在同一 Alembic 进程内先核对 URL 与服务端的数据库、用户、socket、配置端口、监听地址、恢复状态和角色权限，管理员侧另行核对 `data_directory`。错误数据库名的负向门禁在创建 `alembic_version` 前即停止。全程没有连接 Prod、调用 Tushare、部署、创建 TaskRun 或修改 schedule/Heat 配置。

实测结论如下：

1. 成功库从 revision `20260826_000152` 升至 `20260827_000153`。受控样本为 raw/serving 各 36,000 行，覆盖连续 120 个日期、36,000 个唯一 `(trade_date, content_type, name)`，自然月峰值 9,300 行；18 个业务字段双向多重集差异和 `fetched_at -> created_at/updated_at` 投影差异均为 0；
2. raw relation OID、主键和两个二级索引 OID/定义/有效状态全部保持不变，heap 与三个索引仍在 `pg_default`。serving 从物理表切换为 0 B 普通 view；原 owner、relation comment、列 comment、PUBLIC SELECT、普通 SELECT 和 `WITH GRANT OPTION` SELECT 全部恢复，三个非 owner serving 读取角色及 raw reader 均真实读到 36,000 行；
3. 共享拒写函数保持当前 owner、`SECURITY INVOKER`、`search_path=pg_catalog` 且未向 PUBLIC 授权，`trg_board_moneyflow_dc_reject_dml` 为 enabled。对 view 的 `INSERT/UPDATE/DELETE` 均以 SQLSTATE `55000` 和固定文案拒绝，失败事务回滚后业务字段差异仍为 0；
4. 正式 `DatasetWriter` 连续两次写同一身份时均只命中 `raw_tushare.moneyflow_ind_dc`，view 在同一事务立即返回第二次的 `net_amount=222.0000`，回滚后目标身份不存在。另以隔离 SQL 验证 raw 的 INSERT/UPDATE/DELETE 均被 view 零延迟反映，最终回滚后基线行数不变；
5. 三组代表查询切换前后结果 SHA-256 完全一致。最大日期、同日概念点查和概念最近 10 日查询分别从 serving 索引等价下推到 raw 的 `trade_date` 或 `(content_type, trade_date)` 索引；最终复跑 total cost 为 `0.83/0.90`、`8.32/8.32`、`128.08/128.08`，执行时间为 `0.008/0.008 ms`、`0.049/0.052 ms`、`0.392/0.388 ms`，临时块均为 0。另一套完整复验得到相同索引形态和结果 hash；隔离微秒值只证明计划形态，没有替代生产 M3a 的真实时延门禁；
6. 30,001 行同月容量库在 serving `ACCESS EXCLUSIVE`/`DROP TABLE` 前明确报 `monthly reconciliation exceeds safety cap`；revision 保持 152，raw/serving OID、物理表类型、各 30,001 行及零用户 trigger 不变；
7. 单字段差异库以 `moneyflow_ind_dc monthly mismatch` 在 DDL 前失败；未知依赖 view 以 `Unexpected view dependency` 在 DDL 前失败。两者的 revision、relation OID/类型、行数、ACL/comment/index 和零 trigger 均保持原状；
8. 合法三列主键存在时，同身份第二行由 PostgreSQL 以 SQLSTATE `23505` 物理拒绝，因此 migration 的“身份重复”分支在合法表合同下不可达。M2 没有把这一点误写成 migration 发现重复；另用缺失 serving 主键的合同漂移库证明 preflight 会以 `Unexpected serving primary key` 在 DDL 前停止，旧 relation 完整保留；
9. 回滚库在同一事务内完成 preflight、持锁、`DROP TABLE -> CREATE VIEW -> trigger` 后立即注入异常。回滚后 revision 仍为 152，两张物理表、raw/serving OID、36,000 行、全部索引 OID/定义/有效状态、ACL/comment 和零用户 trigger 与执行前逐项一致；
10. 六套验证库结束时未留开放业务事务；两次完整复验的临时实例、数据目录和 socket 均已停止并删除。M2 没有发现需要修改 revision 153 或业务代码的问题。

`P1-B2-moneyflow_ind_dc-M2` 据此通过。该结论只证明 revision 153 在隔离 PostgreSQL 满足数据等价、权限恢复、拒写、raw-only writer、原子失败和查询计划合同；生产仍为 revision 152、raw/serving 仍是两张物理表。后续生产 M3a 需要独立授权，并继续受 M0 已登记的 Heat 上游时间契约异常阻塞；该异常未闭环前不得部署或应用 revision 153。

#### 2026-08-27 `P1-B2-moneyflow_ind_dc-M3a` 提前切换事实与 Heat 契约修复

运营执行完整部署后，生产在未暂停 schedule #4、worker 或进入独立维护窗口的情况下自动从 revision 152 升至 153；`ops.config_revision` 在 `16:30..17:30+08` 没有 schedule #4/#36 的 pause/resume 记录。该顺序违反 M3a 合同，不能补造前置证据，也不以切换后验收通过抹去流程偏差。

切换后只读审计确认：远端 commit 为 `b00d3d10`，Web、worker、scheduler 等服务 active，健康端点正常且没有 warning；raw 保持 `pg_default` 物理表、三个原索引和 94,789,632 B，serving 成为 0 B 普通 view。raw/view 均为 339,268 行、339,268 个唯一 `(trade_date, content_type, name)`，日期范围 `2023-09-12..2026-08-26`，view 的 20 列显式投影、owner、`lake_raw_reader` SELECT、独立拒写 trigger 与共享函数合同均正确；开放 TaskRun 和审计会话之外的目标锁为 0。

生产查询继续下推 raw 索引：最大日期查询约 `0.212 ms`，同日概念聚合约 `2.024 ms`；近 10 日 Heat 查询首次冷缓存约 `148.074 ms`，随后两遍为 `20.680/18.322 ms`，5,040 行、无临时块，符合 M0 已记录的冷页顺序效应。上述证据证明提前应用后没有观察到数据、权限或查询损坏，但尚未替代切换后正式 TaskRun/自然工作流验收。

同轮根因修复把旧单值 `upstream_not_before_local_time=21:00` 删除，改为 action catalog 唯一持有的 `upstream_workflow_not_before_local_times`：`daily_market_close_maintenance=21:00`、`daily_moneyflow_maintenance=20:00`。app scheduler factory 只负责解析和装配；Ops readiness service 要求配置键与两个必需 workflow 精确一致，并按各自时间门槛筛选同交易日成功节点。该配置不进入 env、数据库或页面，不设第二份默认值；修改后通过 scheduler 重启生效。正向测试证明 20:00 后资金流与 21:00 后收盘工作流可共同满足，反向测试证明 19:59 资金流、20:59 收盘工作流、缺失或未知 workflow 配置均 fail-closed。

`2026-08-27 18:47+08` 在开放 TaskRun 为 0、schedule #4 下一次为 20:00、schedule #36 下一次为 21:15 的窗口完成代码发布：远端 head 为 `6c16ac31`，跳过 migration、前端构建、seed、unit 同步和全部业务 worker 重启，仅在代码安装后于 `18:47:51` 重启 `goldenshare-ops-scheduler.service`。Web 与通用 worker 的启动时间保持 `17:09`，Alembic 保持 `20260827_000153`，schedule #4/#36 配置未改；运行时 factory 成功构造 `OperationsScheduler`，两个健康端点正常，发布后开放 TaskRun 仍为 0。

#### 2026-08-28 `P1-B2-moneyflow_ind_dc-M3b` 自然运行验收

2026-08-27 的自然链路关闭了 M3a 后剩余门禁，全程没有补造任务或额外请求 Tushare：

1. schedule #4 于 `20:00:26+08` 创建资金流 workflow TaskRun `9633`，状态 `success`、7/7 节点完成；`moneyflow_ind_dc` 节点处理目标日 `2026-08-27`，读取/保存均为 1,031 行，拒绝和去重均为 0。
2. 当日 `raw_tushare.moneyflow_ind_dc` 与 `core_serving.board_moneyflow_dc` 均为 1,031 行和 1,031 个唯一 `(trade_date, content_type, name)`；20 个投影字段双向 `EXCEPT ALL` 均为 0。serving 仍为 0 B 普通 view，raw 是唯一物理事实表。
3. 收盘 workflow TaskRun `9644` 于 `21:02:27+08` 创建并成功；Heat 必需的 `daily/dc_index/dc_member/dc_daily/limit_list/suspend_d` 六个节点全部为目标日 `2026-08-27`、状态 `success`，且均在 Heat 检查前结束。
4. schedule #36 于 `21:15:28+08` 得到 `HEAT_READY`，证据明确引用 `9644` 与 `9633`，随后只创建一个 Heat TaskRun `9645`。该任务 1/1 unit 成功，于 `21:15:53+08` 发布 504 行，其中 476 行 `VALID`、28 行合规 `INVALID`；后者为 12 个 `HISTORY_INSUFFICIENT` 和 16 个 `MEMBER_COUNT_LOW` 业务结果，不是源行丢失或写入 reject。
5. readiness 与执行诊断的 hash 逐项一致：config `a5257ad4c70c681e683ef728235012c1d50fd9c825bdb43684e6f02f157422f5`、source `42fe3639f7dd7428a85f10964c2c9d86d4e7eb1981618a17e991feda0fe00815`、plan `fea8c37b53572960aceceb892d51b0947ab048c8f2c635d76052f15a53831c3a`、content `9a7104071c22d81eb34a1a23aead07fa176d7974e33f4b7f90ff7f58c5f149b1`；目标表 504 个唯一板块只出现一个 config hash、一个 source hash 和一个 `calculated_at`。当日 schedule #36 仅有 1 个自动 TaskRun，调度器在 `scheduled=1` 后持续运行的后续 tick 均为 0，没有重复 TaskRun 或 DML；schedule #4/#36 均已推进到 2026-08-28 的原定时间。

`P1-B2-moneyflow_ind_dc-M3b` 据此通过；M0/M1/M2/M3a/M3b 全部完成并结案。下一阶段只能是单独授权的 `P1-B2-dc_daily-M0` 只读复审，不自动进入编码、迁移或生产操作。

#### 2026-08-28 `P1-B2-dc_daily-M0` 只读复审

本阶段只读取当前代码、生产 catalog、受控 SQL 结果和既有 TaskRun 诊断；没有改代码、连接源端、创建任务、部署、执行 migration 或修改 schedule。CodeGraph 索引为 current，覆盖 2,774 个文件、48,805 个节点和 113,147 条边；影响面沿 Definition、resolver/request builder、writer/DAO/ORM、Ops workflow/readiness、Wealth、QTF、DG source probe、Lake Console 和相应测试逐项复核。

1. `dc_daily` 继续显式请求 13 个 source fields，支持交易日 point/range、可选 `ts_code` 和行业/概念/地域 `idx_type` fan-out；不带 filter 的一个交易日只形成一个 unit，源端分页固定为 2,000 行、offset/limit、最多 5,000 unit。M0 没有为验证重复请求 Tushare；
2. raw/serving 都是 `pg_default` 普通物理表，主键同为 `(ts_code, trade_date, category)`，并各有 `trade_date` 和 `(trade_date, category)` 两个有效等价索引；raw 的 `lake_raw_reader` SELECT 权限必须在后续阶段保持；
3. raw/serving 各 634,116 行，日期范围 `2024-01-02..2026-08-27`。按 32 个自然月比较全部 13 个业务字段，两个方向的 `EXCEPT ALL` 都为 0；月峰值 23,537 行，因此 revision 154 固定 30,000 行/月的 fail-closed 容量门禁；
4. serving 物理大小为 161,710,080 B（154.22 MiB），是本项当前可释放的毛量；raw 和既有两个 raw 二级索引保持 SSD，不新增生产不存在的索引；
5. 已知 serving 读取者包括 Wealth 板块查询、QTF `sector_source_adapter` 与 DG `dc_board_source_probe`；Lake Console 已直接读取 raw。实际消费者基线显示 DG 单日探测 raw 与 serving 约 `2.11/2.16 ms`，QTF 有界范围 raw 约慢 10.3%，完整 Wealth Heat 26 个开市日 raw 约慢 0.6%，完整 Wealth SectorMetrics 七次交错中位数 raw 约慢 1.46%，均未出现结果或结构性计划退化。单独 503 行子查询 raw 较慢只记作诊断，不能替代完整消费者验收；
6. 当前有两个 active workflow 会写入本数据集：schedule #24 的 18:30 任务和 schedule #2 的 21:02 收盘任务。两者最近同一目标日分别读取 1,026 与 1,030 行，因此 M3a 必须同时暂停、恢复并核验，不能只处理其中一个；
7. raw `fetched_at` 与 serving `updated_at` 全部一致；57,367 行历史 `created_at` 与 raw `fetched_at` 不同。已登记消费者不读取审计列，所以继续采用 `fetched_at AS created_at/updated_at` 的既定透明性边界，但不宣称历史审计时间逐行相同。

M0 据此通过 Definition、物理对象、全字段等价、消费者、容量、查询和自动入口的 M1 准入；它没有授权任何生产修改。

#### 2026-08-28 `P1-B2-dc_daily-M1` 编码与自动化测试

M1 严格限于本数据集的 storage contract、raw ORM metadata、独立 migration、测试和本文档，没有修改 source client、request builder、resolver、planner、writer 共享实现、Ops workflow/readiness、schedule、QTF、DG、Lake Console、Wealth 或前端生产代码，也没有连接数据库、请求 Tushare、部署或执行 migration。

1. Definition 只把 storage 收敛为 `raw_dc_daily/raw_tushare.dc_daily/raw_only_upsert/raw_with_serving_view`；13 个 source fields、日期与 filter、一个无 filter unit、2,000 行分页、5,000 unit 上限和两条 workflow 行为保持不变；
2. `RawDcDaily` 只补齐生产已经存在的 `trade_date` 与 `(trade_date, category)` 索引 metadata；字段、类型、空值合同和三列主键未改变；
3. 新增独立 revision `20260828_000154`，只接编码时唯一真实 head `20260827_000153`。migration 先检查 relation 类型、owner、SSD tablespace、字段、主键、四个二级索引、未知约束/依赖/ACL/RLS/trigger/rewrite/统计/security label/publication，再持有 raw/serving `SHARE` 锁按月比较 13 字段与三列身份；任何月超过 30,000 行或任何差异均在 serving DDL 前失败；
4. 通过前置检查后才取得 serving `ACCESS EXCLUSIVE` 锁，保存并恢复 owner、非 owner SELECT grant、relation/column comments，把原表替换为显式 15 列 raw-backed view，并复用既有共享拒写函数创建本 relation 独立 trigger；禁止 `CASCADE`、raw DDL、共享函数重建和自动 downgrade；
5. 专项正反向测试覆盖 Definition 不漂移、一个 unit 与 filter fan-out、未知 filter 拒绝、raw/serving ORM 合同、raw-only writer、ServingPublish 无旁路、migration 顺序/有界资源/差异与依赖 fail-closed、显式投影、三类拒写前置及离线 PostgreSQL SQL 渲染；registry、freshness、Wealth/QTF/DG 和架构边界纳入定向回归。

M1 只在代码和静态合同层完成。生产仍处于 revision 153，`raw_tushare.dc_daily` 与 `core_serving.dc_daily` 仍是两张物理表；下一阶段只能是另行授权的 `P1-B2-dc_daily-M2` 隔离 PostgreSQL 验证。

#### 2026-08-28 `P1-B2-dc_daily-M2` 隔离 PostgreSQL 验证

M2 在 PostgreSQL 18.4 临时实例完成。实例只监听 `/private/tmp` 下本轮独立 Unix socket，`listen_addresses=''`、`inet_server_addr()` 为空；迁移角色 `dc_daily_m2_app` 为非超级用户，数据库名、用户、socket、恢复模式和管理员读取的 `data_directory` 都在每次 Alembic 调用前核验。`GOLDENSHARE_ENV_FILE` 指向本轮不存在的临时路径，`DATABASE_URL` 再由同一子进程读取并比对，规避仓库 env 文件覆盖命令行连接的历史风险。本轮没有连接 Prod、调用 Tushare、部署、创建 TaskRun 或修改 schedule/workflow。

1. 成功库从 revision 153 升至 154，raw/serving 各 36,000 行；2024-01 恰好 30,000 行、2024-02 为 6,000 行，全部 13 个业务字段和 36,000 个三列身份一致。raw relation OID、主键和两个二级索引 OID/定义/valid/ready 状态保持不变并继续位于 `pg_default`；serving 从 8,028,160 B 物理表变为 0 B 普通 view；
2. 隔离实例建立了真实 `gs_raw_cold_hdd` 并由管理员核验路径，但 `dc_daily` heap/index 没有对象落入 HDD。raw 的 `lake_raw_reader` SELECT 保持；serving 的 relation/column comment、PUBLIC SELECT、普通 reader SELECT 和 `WITH GRANT OPTION` 均完整恢复；
3. view 的 INSERT/UPDATE/DELETE 全部以 SQLSTATE `55000` 被独立 trigger 拒绝。对 raw 的 INSERT、UPDATE、DELETE 会在同一事务立即反映到 view，rollback 后行数和值恢复；正式 `DatasetWriter` 只向 `raw_tushare.dc_daily` 写入 1 行，view 同事务可见，rollback 后两边均无残留；
4. 交易日点查、分类日期范围和最大日期三类查询结果切换前后完全一致，计划从 serving 索引下推到 raw 等价索引。总成本分别为 `214.70→212.94`、`9.25→9.20`、`0.49→0.54`；末项仅增加 0.05，不构成结构性退化，仍须在生产 M3a 以真实数据复核；
5. 单月 30,001 行库在 serving DDL 前报 `monthly reconciliation exceeds safety cap`；业务字段值差异、三列身份值差异、raw 主键顺序漂移和外部 view 依赖分别被 `monthly mismatch`、`Unexpected raw primary key`、`Unexpected view dependency` 拒绝。每个失败库都保持 revision 153、原 raw/serving OID、两张物理表、原行数和零用户 trigger；
6. 回滚库执行 revision 154 的真实前置 SQL 和 `DROP TABLE → CREATE VIEW → trigger` 后注入除零异常；事务回滚后 revision 153、两张物理表 OID、raw 索引 OID/定义/valid/ready 和数据全部恢复；
7. 所有场景使用独立数据库，避免失败状态污染后续证明；临时 PostgreSQL 完成后已停止，不保留监听服务。首次试运行误用了只含客户端的 `libpq/bin/initdb`，在创建数据库前因找不到同目录 `postgres` 安全失败；随后固定使用 PostgreSQL 18.4 服务端工具重新建立全新实例，未复用半初始化目录。

`P1-B2-dc_daily-M2` 据此通过。该结论只关闭隔离数据库门禁；生产仍为 revision 153 和两张物理表。下一阶段只能是单独授权的 `P1-B2-dc_daily-M3a`，并必须实时复核生产代码/head、634,116 行基线漂移、32 月全字段差异、磁盘/锁/长事务/开放 TaskRun，同时暂停并回查 schedule #24 和 schedule #2 两个写入入口，再停止相关 worker、应用 revision 154、回收连接池并完成生产查询与最小 TaskRun 验收。

#### 2026-08-28 `P1-B2-dc_daily-M3a` 生产切换与即时验收

M3a 于 `10:02..10:10+08` 按固定维护顺序完成。生产预检时 Alembic 为 revision 153，raw/serving 仍是两张 `pg_default` 物理表，各 634,116 行和 634,116 个唯一 `(ts_code, trade_date, category)`，日期范围 `2024-01-02..2026-08-27`；32 个自然月的 13 个业务字段双向差异为 0，月峰值 23,537。没有 queued/running/canceling TaskRun、目标 relation 锁或超过 30 秒的开放事务；根盘可用 52,362,596,352 B，HDD 可用 320,994,295,808 B。

1. M1/M2 精确代码以 commit `fa5fcf8c` 推送并同步到生产代码源。schedule #2 与 #24 在变更前均为 active，目标同为 `daily_market_close_maintenance`，cron 分别为 `2 21 * * 1,2,3,4,5` 与 `30 18 * * 1,2,3,4,5`；通过正式 schedule service 暂停后再次确认开放 TaskRun 为 0，再停止通用 `goldenshare-ops-worker.service`；
2. 使用固定 `--maintenance-migration` 模式拉取并安装后端、应用 revision 154。该模式没有构建前端、seed、创建任务或重启 worker；migration 于 `10:06:58..10:07:13+08` 在自己的事务中完成，未出现锁等待、部分 DDL 或回滚；
3. 切换后 `raw_tushare.dc_daily` OID 仍为 `545332`，主键和两个二级索引继续位于 `pg_default`；`core_serving.dc_daily` 成为 OID `2032662`、0 B 的普通 view，显式投影原 15 列。原 owner、`lake_raw_reader` SELECT、relation/column comment 合同恢复，独立 trigger enabled，共享拒写函数保持非 SECURITY DEFINER 且固定 `search_path=pg_catalog`；view 的 INSERT/UPDATE/DELETE 均以 SQLSTATE `55000` 拒绝；
4. raw/view 各 634,116 行和 634,116 个唯一身份，全量 13 字段双向 `EXCEPT ALL` 为 0；切换后的 `created_at/updated_at` 均按合同映射 raw `fetched_at`，不再保留旧 serving 中 57,367 行不同的历史 `created_at`。原 serving 物理 relation 161,710,080 B 已释放为 0 B view；根盘 `df` 在整个窗口前后净增加约 172.83 MB 可用空间，但该瞬时值包含运行噪声，精确毛收益仍以 catalog 的 161,710,080 B 为准；
5. Web、QTF、日期完整性 worker 和 Ops scheduler 均已重启以回收连接池并加载新 Definition，通用 worker 在查询合同通过后恢复。DG 单日、Wealth 同日概念和 QTF 有界历史结果分别为 1,030、503、5,376 行，raw/view hash 完全一致；view/raw 执行时间分别为 `1.988/1.895 ms`、`0.866/0.856 ms`、`14.308/14.121 ms`，最大日期为 `0.034/0.031 ms`，计划均下推 raw 等价索引，没有顺序扫描或临时文件异常；
6. 正式手动主链创建 TaskRun `9704`，只请求 `2026-08-27` 一个 unit。任务 `1/1/0` 成功，源端 1 页、短页结束、0 重试、`truncated=false`，读取/归一化/保存均为 1,030，拒绝与完全重复去重均为 0。raw-only upsert 不提供 inserted/matched 拆分，通用 `persistence.immutable_fact` 容器中的相应零值不解释为“未写入”；目标日 raw/view 均为 1,030 行和 1,030 个唯一身份，全表仍为 634,116 行，证明幂等覆盖没有制造重复；
7. TaskRun 完成且开放任务回到 0 后，通过同一正式 service 恢复 schedule #2/#24；cron、时区和 `last_triggered_at` 未变，下一次仍为 `2026-08-28 21:02/18:30+08`。Web、通用 worker、scheduler、QTF 和日期完整性 worker 最终均为 active，两个健康端点为 200，生产代码为 `fa5fcf8c`、工作区干净、Alembic 为 revision 154，目标长事务为 0。

`P1-B2-dc_daily-M3a` 据此通过。尚未完成的是 `P1-B2-dc_daily-M3b`：分别观察 schedule #24 的 18:30 与 schedule #2 的 21:02 自然 workflow，按 `dc_daily` node 核验目标日期、分页、读取/保存/拒绝、raw/view 当日身份和幂等结果。该自然观察统一登记，不阻塞下一数据集的 M0/M1/M2；若任一自然 node 失败或出现 raw/view 差异，才升级为共享阻塞。

### S4：文档证据

将 revision、部署 commit、TaskRun ID、对账结果、查询计划、磁盘释放量和残余风险写回 v2；未验收项不得标完成。

## 9. 已验证经验与后续执行加固

### 9.1 两轮实施暴露的问题与固定规则

| 已发生问题或误判 | 根因 | 后续固定规则 | 落实位置 |
| --- | --- | --- | --- |
| 反复把夜间自然 workflow 观察设成后续阶段的硬前置 | 把“尚未触发/尚未查看”误当成失败，又没有统一待验收台账 | M3 拆成 M3a/M3b；夜间 M3b 统一登记、集中按节点验收，默认不阻塞后续 M1/M2/M3a；仅已发现且未解决的共享运行链异常形成阻塞 | 第 8 节夜间自然任务统一验收台账与第 13 节完成边界 |
| 隔离 migration 曾被显式 env 文件指向 Prod | `get_settings()` 的既有合同是 `GOLDENSHARE_ENV_FILE` 内容覆盖同名 shell 变量，不能靠临时 `DATABASE_URL` 改目标 | M2 必须使用独立 env 文件，并在 Alembic 前核对 host/database/user/server address/port/data directory；禁止改变全局配置优先级来修本专项 | S2 与现有 `tests/test_db.py` 配置合同 |
| 维护发布依赖多组临时环境变量，存在漏关 seed、构建或服务重启的风险 | 通用部署入口默认执行完整发版 | 使用 `--maintenance-migration` 固定变更动作仅为拉代码、安装后端和 migration，另保留只读资源加载自检；该模式不代替 schedule 暂停、停服和恢复 | `scripts/deploy-systemd.sh`、发布文档与部署脚本测试 |
| 概念 M3a 的标准部署在维护窗口前自动应用了 revision 148 | 把“部署代码”和“生产 migration”当成可分开的口头步骤，但标准部署实际会自动升级到 head | 生产 M3a 在暂停目标 schedule/worker 前不得运行会自动 migration 的标准部署；先用不迁移模式安装代码，再在维护窗口内显式应用 migration。若顺序已偏离，禁止重复 migration 或补造前置证据，必须记录偏差并完成切换后全量验收 | `P1-B1-concept-M3a` 实证与后续 M3a 发布清单 |
| schedule SSE 长连接持有数据库事务并阻塞 revision 150 | SSE endpoint 复用 request-scoped `Session` 无限轮询，读取完成后事务未结束，持续持有 `ops.schedule` 的 `AccessShareLock` | `P1-GATE-SSE-M1` 已改为鉴权事务先结束、每轮独立短会话并在输出/休眠前释放；M2/M3 已分别在隔离库和生产真实 SSE 证明不存在跨轮询长期事务或目标 idle relation lock | 夜间 revision 150 锁事件、`src/ops/api/schedules.py`、相关测试与 `P1-GATE-SSE-M2/M3` |
| 生产 DDL 在锁冲突时可以无限等待 | 生产全局 `lock_timeout` 与 `idle_in_transaction_session_timeout` 均为 0，标准部署又在在线服务存活时执行 migration | PostgreSQL 在线 Alembic 已在 migration transaction 内设置 `SET LOCAL lock_timeout='15s'`；M2 证明真实 migration 超时和原子回滚，M3 证明生产事务级锁冲突于 15.11 秒 fail-fast 且无残留锁。后续仍须在每次 migration 前做实时锁预检 | `alembic/env.py`、相关测试与 `P1-GATE-SSE-M2/M3` |
| B0 首次生产 migration 试图设置业务角色无权修改的 `temp_file_limit` | 把隔离环境能力误当成生产最小权限能力 | migration 只使用已验证的最小权限能力；工作集通过每数据集独立行数上限、分块和 `work_mem` 有界，禁止为迁移追加超管权限 | 第 7.1 节与各 revision 负向容量测试 |
| 一次验收 SQL 曾按 dataset key 猜 serving 表名 | action key、dataset key 与物理 relation 名并非机械映射 | 每项 S0 冻结显式对象表：dataset/action/raw/serving/ORM/DAO/index/schedule；所有 SQL 只从已核验对象表生成 | 第 9.2 节准入清单 |
| `df` 瞬时变化与 relation 释放量不一致 | 发布依赖、WAL、日志和后台活动共同影响文件系统水位 | 精确收益只取 PostgreSQL catalog 中被删除 heap/index 的字节；`df` 仅做容量安全水位 | S4 证据合同 |
| TaskRun 顶层诊断不能完整代表 workflow 内单个数据集 | workflow node 才保存目标步骤的 rows、reject 和分页诊断；父任务 unit 表达 step 完成数，`TaskRunNode` 本身没有 unit 字段 | 自然 workflow 验收必须同时查询目标 node；字段名称以当前 ORM 的 `rows_saved` 和 `ingestion_diagnostics_json` 为准，禁止猜 `rows_written` 或把父任务 unit 当 source unit | M3b 与五段对账模板 |
| raw upsert 的插入/匹配细分不能照搬 immutable writer 指标 | writer 语义不同，部分持久化诊断字段对 raw upsert 没有同一含义 | raw 直出验收以 `rows_saved`、reject、去重、任务时间窗内 `fetched_at` 和物理 raw/view 对账为主；不得把不适用的 immutable 指标填 0 后宣称闭环 | M3a TaskRun 对账 |
| 连续拼接多项生产状态修改曾出现本地引号错误 | 一个命令同时承担暂停、停服、恢复等多个状态变化，失败边界不清 | 一次只做一个状态修改；每次修改后立即只读回查 schedule、service、TaskRun 和 relation，再进入下一步 | M3a 操作顺序 |
| B0 的拒写函数可以被 B1 复用，但不能因此抽成通用迁移框架 | 可复用的是数据库函数契约，不是各表字段、依赖、容量和切换 SQL | 仅在 owner、参数、语言、security、search_path、ACL 完全匹配时复用拒写函数；每张 view 保留独立 trigger 和独立 migration | 第 5.2、6、9.2 节 |
| 小表验收阈值容易被误当成一期通用阈值 | 每表行宽、月峰值、索引、消费者和锁预算不同 | 5,000/20,000 行、20% 时延和分块粒度都必须在对应 S0 重新证明；大表不得复制小表上限或无界全表 `EXCEPT ALL` | 第 7 节与第 9.3 节差异矩阵 |
| 自动任务成功不等于下游 readiness 可使用 | `moneyflow_ind_dc` 资金工作流在 20:00 成功，但原 Heat 合同只承认 21:00 后请求的证据，形成连续超时 | 每项 M0 必须沿下游 readiness 继续审计实际 schedule 时间；源任务成功、行数完整和下游自动化成功是三个不同门禁。该问题已用按 workflow 区分的 `21:00/20:00` 双门槛修正，禁止重新收敛成全局时间 | `P1-B2-moneyflow_ind_dc-M0` 与本轮 Heat 时间契约修复 |
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
| `moneyflow_ind_dc` | M0 已证 339,268 行、36 月全字段等价；月峰值 23,541；有 Wealth 直接读取并进入 sector heat readiness；revision 153、Heat 双门槛和自然 M3b 均已通过 | raw-only writer、显式 view、拒写函数、30,000 行/月有界差集方法 | THS 的 5,000/20,000 上限、“无业务消费者”的验收范围；不得把两个上游门槛重新压成单一时间 |
| `dc_daily` | 属于每日收盘 workflow；Wealth、QTF 和 DG 都有直接读取 | 只读 relation 名与显式列合同 | 只做 Ops SQL；必须增加 QTF bounded range、DG 单日 probe 和业务返回验收 |
| `suspend_d` | 属于每日收盘 workflow；多条 Wealth/市场情绪链消费，冲突键含 `row_key_hash`，物理事实还含 `id` | 分块、拒写、事务回滚方法 | 只比较业务 hash；必须证明 `id` 逐行一致并验证日期范围 join |
| P1-B3/B4 百万行表 | 分别受每日收盘或每日资金 workflow 覆盖，行数、锁时、WAL、缓存和查询面显著增大 | 阶段状态机、只读透明边界、单数据集 revision | 小表全量/单月阈值、单次微秒样本、无界锁内对账或合并发布 |

### 9.4 后续统一状态机

1. **S0/M0 只读复审**：可以在前项 M3b 等待期间开展；输出本项对象表、差异化门禁和停止条件，不写代码或数据库；
2. **M1 编码**：必须有本项授权；只改本项 Definition/ORM/migration/tests。前项 M3b 不阻塞，但若观察暴露共享 writer、scheduler 或 workflow 契约问题，应暂停 M1 并重新评审；
3. **M2 隔离验证**：必须独立授权和数据库身份门禁；不连接 Prod、不调用 Tushare、不创建任务；
4. **M3a 生产切换**：必须独立授权；前项 M3a 已闭环，且当前没有已发现但未解决的共享 schedule/runtime/writer 异常。前项 M3b 仅处于待触发或待统一核验状态时不构成阻塞；
5. **M3b 自然观察**：只验证既有自动化恢复后的真实路径；统一登记、集中查看，不重复源端扫描，不自动创建或修改 schedule；
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
4. raw 直出 migration 本身不改 source fields、请求参数、分页、日期/unit 设计或自动任务时间；本轮 Heat 修复是经独立根因审计后的运行契约变更，不混入 migration；
5. 不创建、删除或重新配置 schedule；
6. 不修改 Lake Parquet、ClickHouse、Dagster asset/check/event；
7. 不做共享 writer/DAO/Definition 重构；
8. 不保证 relation OID、relkind、PK/index catalog 或历史审计时间值不变。

## 13. 当前完成边界与下一阶段

1. P1-B0 市场资金已完成 M1～M3，并补充通过 `P1-B0-market-M3b`；P1-B1 行业、概念和 `margin` 均已完成 M1/M2/M3a/M3b。`margin` 已在 revision `20260826_000152` 切换为 raw 唯一物理表和 0 B serving view，并由自然 TaskRun `9573` 完成自动化数据链验收；
2. schedule #4 TaskRun `9244` 已逐个关闭市场、行业、概念三项自然工作流数据链验收：目标 node 全部 success、拒绝和去重均为 0、分页短页结束、raw/view 当日全字段一致。任务受部署锁等待影响在 `20:07` 创建，因此本轮不提供 `20:00` 准点触发 SLA 证据；
3. `margin` 的 schedule #33/rule #14 已在 `2026-08-27 09:00..09:30+08` 自然窗口完成 M3b：log `3674` 唯一命中并创建 TaskRun `9573`，三交易所、分页、拒绝、写入和 raw/view 对账均通过；本项不再有待验收开发或生产步骤；
4. `margin` 结案时生产 Alembic 为 `20260826_000152`、远端审计 commit 为 `f732f8bd`；随后 `moneyflow_ind_dc` 的完整部署已把生产推进到 `20260827_000153/b00d3d10`。两个快照属于不同执行阶段，不得互相覆盖；
5. `P1-B2-moneyflow_ind_dc-M0/M1/M2/M3a/M3b` 已完成：36 月及全表 18 字段生产差异为 0，Definition 已收敛 raw-only，独立 revision `20260827_000153` 与隔离门禁通过；生产切换后静态合同、自然 raw-only TaskRun `9633`、双上游 `9633/9644`、Heat TaskRun `9645`、结果/hash 回读和自动幂等均通过。提前 migration 的发布顺序偏差继续保留为历史教训；
6. Heat 时间口径固定为收盘工作流 21:00、资金流工作流 20:00，代码、正反向测试、生产调度器发布和自然运行均已闭环；
7. `P1-B2-dc_daily-M0/M1/M2/M3a` 已完成；生产 revision 154、0 B raw-backed view、TaskRun `9704` 与两个 schedule 原样恢复均已验收。其自然 M3b 已登记，不阻塞下一项 `suspend_d` 从 M0 开始只读复审；
8. 未来任何生产操作仍须实时确认开放 TaskRun 为 0、目标 schedule/probe 已按本项契约暂停、worker 已停止、目标锁和磁盘水位满足门禁。扩容后的容量快照不是跳过这些检查的理由；
9. 仓库外 SQL/BI/人工脚本无法由仓库审计穷尽，若存在依赖 OID、relkind、约束 catalog、旧审计时间或 serving DML 的未登记消费者，仍是每项 migration 的残余运营风险。

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
