# Tushare 个股资金流向（DC）（`moneyflow_dc`）数据集开发说明

- 当前阶段：`P1-B4-moneyflow_dc-M1` 已通过，下一步为独立授权的 M2
- 当前代码：Definition 已切换为 `raw_only_upsert + raw_with_serving_view`；Raw ORM 已声明生产既有两个二级索引；独立 revision `20260829_000161` 已完成离线验证
- 当前生产：Raw 与 Serving 仍为两张 SSD 物理表、生产仍按已部署旧版本双写；M1 未连接或修改任何数据库
- 目标形态：`raw_tushare.moneyflow_dc` 为唯一物理事实表，`core_serving.equity_moneyflow_dc` 保留为受保护的只读 Raw-backed view

## 0. 当前架构基线（必须遵守）

本数据集结论：

- 该数据集是否对外服务：是
- 当前是否多源：否（仅 `tushare`）
- 是否已具备 std 映射与融合策略：否
- 当前开发代码 target_table：`raw_tushare.moneyflow_dc`
- 当前生产已部署旧版 target_table：`core_serving.equity_moneyflow_dc`
- 当前生产物理路径：`raw_tushare -> core_serving` 双物理表、双写
- revision 161 应用后的目标路径：`raw_tushare` 唯一物理事实表 + 原 Serving 名称只读 view

---

## 1. 标准交付流程（本数据集）

1. 固定上游接口 `moneyflow_dc`（doc_id=349）。
2. 明确历史区间推进与容量上限处理。
3. 设计 `raw_tushare.moneyflow_dc` 与 `core_serving.equity_moneyflow_dc`。
4. 打通 Ops 与健康度观测。
5. 完成测试与回归。

---

## 2. 基本信息

- 数据集名称：个股资金流向（DC）
- 资源 key：`moneyflow_dc`
- 所属域：股票
- 数据源：`tushare`
- 官方文档链接：<https://tushare.pro/document/2?doc_id=349>
- API 名称：`moneyflow_dc`
- 文档抓取日期：`2026-04-17`

---

## 3. 接口分析

### 3.1 输入参数（上游原生）

| 参数名 | 类型 | 必填 | 说明 | 类别 | 是否暴露给用户 | 前端控件 | 执行层映射 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `ts_code` | str | 否 | 股票代码 | 代码 | 是（可选） | 代码输入 | 直传 |
| `trade_date` | str | 否 | 交易日期 | 时间 | 是 | 单日选择器 | 直传 |
| `start_date` | str | 否 | 开始日期 | 时间 | 是 | 区间选择器 | 直传 |
| `end_date` | str | 否 | 结束日期 | 时间 | 是 | 区间选择器 | 直传 |

### 3.2 输出字段（上游原生）

| 字段名 | 类型 | 含义 | 是否落库 |
| --- | --- | --- | --- |
| `trade_date` | str | 交易日期 | 是 |
| `ts_code` | str | 股票代码 | 是 |
| `name` | str | 股票名称 | 是 |
| `pct_change` | float | 涨跌幅（%） | 是 |
| `close` | float | 最新收盘价 | 是 |
| `net_amount` | float | 净流入（万元） | 是 |
| `net_amount_rate` | float | 净流入占比（%） | 是 |
| `buy_elg_amount` | float | 今日超大单净流入额（万元） | 是 |
| `buy_elg_amount_rate` | float | 今日超大单净流入占比（%） | 是 |
| `buy_lg_amount` | float | 今日大单净流入额（万元） | 是 |
| `buy_lg_amount_rate` | float | 今日大单净流入占比（%） | 是 |
| `buy_md_amount` | float | 今日中单净流入额（万元） | 是 |
| `buy_md_amount_rate` | float | 今日中单净流入占比（%） | 是 |
| `buy_sm_amount` | float | 今日小单净流入额（万元） | 是 |
| `buy_sm_amount_rate` | float | 今日小单净流入占比（%） | 是 |

### 3.3 同步策略结论

- 是否支持单次时间点：是
- 是否支持区间回补：是
- 时间粒度：日
- 时间推进策略：交易日历逐日推进
- 是否需要分页循环：是（接口支持 `limit` / `offset`）
- 是否有级联依赖：否

推荐最省力拉取方式：

- 日常：按 `trade_date` 单日请求。
- 历史：按交易日历逐日请求。
- 分页：当单次返回触达上限时，使用 `limit`+`offset` 翻页补齐当日数据。
- `ts_code` 仅用于定向修复，不作为默认全量路径。

---

## 4. 参数与交互设计（Ops）

### 4.1 手动任务交互

1. 第一步：股票 -> 个股资金流向（DC）
2. 第二步：时间参数（单日/区间）
3. 第三步：其他输入条件（可选 `ts_code`）

### 4.2 自动任务交互

- 资源：`moneyflow_dc.maintain`
- 默认不暴露 `ts_code`，仅注入 `trade_date`

---

## 5. 落库与发布设计

### 5.1 路径选择

- 当前生产已部署旧版路径类型：`raw_core_upsert`，Raw 与 Serving 各保存一份相同业务事实。
- 当前开发代码已实现：`raw_only_upsert + raw_with_serving_view`；生产需在后续 M3a 应用 revision 161 后才形成同一物理事实。
- 选择理由：当前 writer 对同一 normalized batch 仅按两套 ORM 列过滤后分别 upsert，生产 36 个自然月的 15 个业务字段已证明完全一致；保留原 Serving relation 名称可以维持已登记只读消费者的 SQL 合同。
- 边界：不修改源字段、请求参数、日期/unit、分页、手动/自动任务或工作流；不承诺 relation OID、relkind、PK/index catalog 以及历史 `created_at` 值不变。

### 5.2 表设计

#### A. `raw_tushare.moneyflow_dc`

- 主键：`(trade_date, ts_code)`
- 审计字段：`api_name`, `fetched_at`, `raw_payload`
- 索引：
  - `idx_raw_tushare_moneyflow_dc_trade_date(trade_date)`
  - `idx_raw_tushare_moneyflow_dc_ts_code_trade_date(ts_code, trade_date)`

#### B. `core_serving.equity_moneyflow_dc`

- 当前为物理表，主键与两个查询索引分别为 `(trade_date, ts_code)`、`(trade_date)`、`(ts_code, trade_date)`。
- revision 161 的目标为显式只读 view，继续投影全部 15 个业务字段，并把 Raw `fetched_at` 投影为 `created_at/updated_at`；当前生产尚未应用。
- view 必须使用独立 DML 拒绝 trigger，`INSERT/UPDATE/DELETE` 均 fail-closed；不得使用 `CASCADE`，不得自动 downgrade 重建空表。

---

## 6. 维护实现设计

- IngestionExecutor / SourceClient：`moneyflow_dc` 数据集维护链路
- 当前开发代码 `target_table`：`raw_tushare.moneyflow_dc`
- 当前生产已部署旧版 `target_table`：`core_serving.equity_moneyflow_dc`
- 参数构建：
  - `moneyflow_dc.maintain`：`trade_date` 或 `start_date+end_date`（可选 `ts_code`）
- 幂等：按主键 upsert
- 进度日志示例：
  - `moneyflow_dc: 25/83 trade_date=2026-04-16 fetched=4987 written=4987`

---

## 7. 数据状态与健康度观测

- 数据状态分组：资金流向
- 健康度口径：`trade_date` 日期范围
- 展示名：个股资金流向（DC）

---

## 8. 测试与验收

- 单测：参数映射、交易日历推进、upsert 幂等
- 集成：`moneyflow_dc.maintain`（单日/区间）
- 回归：不影响既有 `moneyflow`（旧资金流）链路

---

## 9. 发布与回滚

- 历史 migration 已创建 `raw_tushare.moneyflow_dc` 与 `core_serving.equity_moneyflow_dc`；P1-B4 不重新建 Raw 表或索引。
- M1 已新增只处理本数据集的独立 forward migration `20260829_000161`：先有界验证物理合同和数据等价，再原子替换 Serving 物理表为只读 view。该 migration 尚未应用到任何数据库。
- 发布后验证：回收读取连接池，执行一个交易日的最小正式 TaskRun，并核对源端分页、归一化、保存、reject、Raw/view 行数和 15 字段。
- 回退：DDL 提交前依赖 PostgreSQL 事务回滚；提交后只能另做显式 forward migration，不自动 downgrade、不清表、不从 Tushare 重拉。

---

## 10. 已拍板结论（本数据集）

1. 若单次返回达到上限 6000，默认启用 `limit` + `offset` 分页补数。
2. 自动任务不附带单股 `ts_code`，仅手动页可选。
3. 纳入独立工作流：每日资金流向同步，不并入其它工作流。
4. 数据状态分组归属：资金流向。

---

## 11. `P1-B4-moneyflow_dc-M0` 只读复审结论（2026-08-29）

本阶段只读取当前代码、CodeGraph、生产 PostgreSQL catalog/数据/查询计划和既有 TaskRun 诊断；没有修改生产代码或配置，没有部署、migration、schedule 操作、TaskRun 创建、Tushare 请求或业务数据写入。

1. 当前 Definition 显式请求并保存本文件第 3.2 节的全部 15 个源字段。point/range 输入按交易日历逐日形成单日 unit；request builder 每个 unit 只发送 `trade_date` 和可选 `ts_code`；source client 使用 `limit/offset`、`page_limit=6000`、短页结束且无任意最大页数。2026-08-28 的既有自然节点真实读取 6,007 行：第 1 页 6,000 行、第 2 页 7 行，最终短页结束、无截断、无重试、reject 和去重均为 0。
2. 当前 storage 是 `raw_moneyflow_dc + equity_moneyflow_dc + raw_core_upsert`。共享 writer 把同一 normalized batch 仅按 ORM 列过滤后分别 upsert，未发现 Serving 专属转换、过滤、聚合、冲突消解、ServingPublish mapping 或旁路 DML。M1 只允许复用既有 `raw_only_upsert`，不修改共享 writer、DAO 类型、normalizer、resolver、planner 或 source client。
3. 生产 Alembic 为 `20260829_000159`。Raw/Serving OID 分别为 `22836/22899`，均为 owner `goldenshare_user`、`pg_default` 普通物理表；总大小分别为 `1,188,683,776/1,131,995,136 B`，后者约 `1.054 GiB`，是本项当前可释放毛量。两层业务列、类型、nullability、主键 `(trade_date, ts_code)` 和两个二级索引签名一致，索引均 valid/ready；Raw 的 `lake_raw_reader SELECT` 必须保留。
4. 两层各 `4,151,016` 行和同数唯一身份，日期范围均为 `2023-09-11..2026-08-28`，空身份与异常 `api_name` 均为 0。36 个自然月逐月比较全部 15 个业务字段，Raw-only 与 Serving-only 差异全部为 0；最大业务行宽为 148 B。
5. 717 个交易日的日行数最小 2,812、中位 5,807、P95 6,088、最大 6,106；自然月峰值为 `2025-07` 的 139,877 行。M1 migration 的独立月容量门禁固定为 **170,000 行/层/月**，等于实测峰值上浮约 20% 后向上取整；M2 必须证明 170,000 行通过、170,001 行在任何 Serving DDL 前 fail-closed。
6. `raw.fetched_at = serving.updated_at` 对全部 4,151,016 行成立；2,350,240 行历史 `serving.created_at != raw.fetched_at`。仓库内未发现审计时间消费者，因此仍采用一期固定投影 `fetched_at AS created_at/updated_at`，但只承诺已登记消费者的业务字段读取透明，不宣称这些历史 `created_at` 值透明。
7. Raw/Serving all-visible 分别为 90.57%/88.18%，当前没有先做 vacuum 的证据。最大日期、单日、单股票全历史、28 日 Lake 范围和日期完整性五类查询都使用等价索引且无异常计划；交错样本中有实际数据量的 Raw 正向退化不超过约 10.3%，低于本项 20% 停止门禁。M2/M3a 仍须复测结果 hash、索引下推、临时块和交错中位时延。
8. 仓库内未发现 Biz、QTF、frontend 或 DG 直接读取 `core_serving.equity_moneyflow_dc`；Ops freshness/date completeness 由 Definition target 驱动，Lake Console 已显式读取 Raw 的同一 15 字段并按 `trade_date, ts_code` 排序。仓库外 SQL、BI、人工脚本和依赖 OID/relkind/catalog/审计时间的工具无法由代码审计穷尽，继续作为残余运营风险。
9. 自动写入口是 active 的 `daily_moneyflow_maintenance` schedule #4，工作日 20:00 触发。M3a 必须暂停并原样恢复 #4，停止会领取该 workflow 的 generic worker，且在 migration 前重新确认开放 TaskRun、目标 node、锁、长事务和磁盘水位。M0 快照时这些运行门禁均为 0；下一次自然触发为 `2026-08-31 20:00+08`。
10. Raw ORM 当前没有声明生产既存的两个二级索引。M1 只补索引 metadata，migration 不得重建索引；独立 revision 必须接编码时真实 Alembic head，按 Raw→Serving 顺序持有 `SHARE` 锁，在 16 MiB `work_mem` 下逐月做 170,000 行上限、身份和 15 字段双向对账，之后才获取 Serving `ACCESS EXCLUSIVE` 锁并执行原子切换。

结论：`P1-B4-moneyflow_dc-M0` **通过**，具备 M1 编码准入。M1 仍需单独授权，范围只包括本数据集 Definition storage、Raw ORM 索引 metadata、独立 migration、专项测试与文档；M0 不授权隔离数据库、生产 migration、TaskRun 或 schedule 修改。

## 12. `P1-B4-moneyflow_dc-M1` 编码与离线验证结论（2026-08-29）

M1 严格按 M0 冻结合同完成，只修改本数据集及共享 writer 的参数化回归样本；没有连接 PostgreSQL、请求 Tushare、部署、应用 migration、创建 TaskRun、修改 schedule，亦未启动 `stk_limit`。

1. Definition 只修改 storage delivery：`core_dao_name` 改为 `raw_moneyflow_dc`，`target_table` 改为 `raw_tushare.moneyflow_dc`，`delivery_mode/layer_plan/write_path` 固定为 `raw_with_serving_view / raw->serving_view / raw_only_upsert`。15 个 source fields、日期语义、`ts_code` filter、6,000 行分页、短页结束、manual/schedule/retry 能力和工作流均未改变。
2. `RawMoneyflowDc` 仅补齐生产已经存在的 `(trade_date)` 与 `(ts_code, trade_date)` 两个索引 metadata；没有创建、重建或移动 Raw 表/索引，也没有修改 DAO factory、共享 writer、resolver、request builder、normalizer、source client、Ops 或前端代码。
3. 独立 migration `20260829_000161_make_moneyflow_dc_raw_view.py` 接编码时唯一真实 head `20260829_000160`。它固定 `lock_timeout=15s`、`statement_timeout=300s`、`work_mem=16MB`，要求 Raw/Serving 均为 owner 当前角色的 SSD `pg_default` 物理表，逐项校验 15 个业务字段、主键、四个二级索引、ACL、依赖和共享拒写函数。
4. migration 按 Raw→Serving 顺序持有 `SHARE` 锁，逐自然月核对行数、唯一 `(trade_date, ts_code)` 与 15 字段双向 `EXCEPT ALL`，每层每月最多 170,000 行；任何漂移、超限或未知依赖都在 Serving DDL 前失败。全部通过后才取得 Serving `ACCESS EXCLUSIVE` 锁，以不带 `CASCADE` 的单事务切换创建显式 view，恢复 owner、SELECT ACL、comments，并挂独立三类 DML 拒写 trigger。
5. view 显式投影全部 15 个业务字段，并将 `fetched_at` 投影为 `created_at/updated_at`；migration 不执行任何 Raw DDL/DML、不创建索引、不重建共享拒写函数，且自动 downgrade 明确失败。
6. 专项测试覆盖 Definition/Resolver/filter/pagination 不漂移、Raw/Serving ORM 字段类型和索引合同、ServingPublish 无旁路、Raw freshness target、writer 只写 Raw、migration 顺序/禁止项和完整 PostgreSQL 离线 SQL 渲染。M1 完整回归结果以本轮交付记录为准。

结论：`P1-B4-moneyflow_dc-M1` **通过**。生产仍为两张物理表，尚未释放 1,131,995,136 B；下一步只能在独立授权后进入 M2，在隔离 PostgreSQL 真实应用 revision 161，并验证 170,000 行通过、170,001 行 DDL 前拒绝、三类 view DML 拒绝、事务回滚、writer 同事务即时可见和代表查询计划。M1 不构成任何生产 migration 授权。
