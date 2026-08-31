# Tushare 个股资金流向（THS）（`moneyflow_ths`）数据集开发说明

## 0. 当前架构基线（必须遵守）

本数据集结论：

- 该数据集是否对外服务：是
- 当前是否多源：否（仅 `tushare`）
- 是否已具备 std 映射与融合策略：否
- 当前代码 target_table：`raw_tushare.moneyflow_ths`
- 当前生产路径：`raw_tushare.moneyflow_ths` 唯一物理事实表、`raw_only_upsert`；`core_serving.equity_moneyflow_ths` 为 0 B 只读 view
- raw 直出专项目标：`raw_tushare.moneyflow_ths` 唯一物理事实表，原 `core_serving.equity_moneyflow_ths` 名称保留为只读 view
- 当前阶段：`P1-B3-moneyflow_ths-M0/M1/M2/M3a/M3b` 全部通过并结案；生产为 Raw 唯一物理事实表与 0 B Serving view

---

## 1. 标准交付流程（本数据集）

1. 固定上游接口 `moneyflow_ths`（doc_id=348）。
2. 明确输入输出参数与历史回补推进口径。
3. 设计 `raw_tushare.moneyflow_ths` 与 `core_serving.equity_moneyflow_ths`。
4. 打通 Ops 手动/自动任务、数据状态观测。
5. 完成单测、集成测试与回归。

---

## 2. 基本信息

- 数据集名称：个股资金流向（THS）
- 资源 key：`moneyflow_ths`
- 所属域：股票
- 数据源：`tushare`
- 官方文档链接：<https://tushare.pro/document/2?doc_id=348>
- API 名称：`moneyflow_ths`
- 文档抓取日期：`2026-04-17`

---

## 3. 接口分析

### 3.1 输入参数（上游原生）

| 参数名 | 类型 | 必填 | 说明 | 类别 | 是否暴露给运营 | 前端控件 | 执行层映射 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `ts_code` | str | 否 | 股票代码 | 代码 | 是（可选） | 代码输入 | 直传 |
| `trade_date` | str | 否 | 交易日期（YYYYMMDD） | 时间 | 是 | 单日日期选择器 | 直传 |
| `start_date` | str | 否 | 开始日期（YYYYMMDD） | 时间 | 是 | 区间选择器 | 直传 |
| `end_date` | str | 否 | 结束日期（YYYYMMDD） | 时间 | 是 | 区间选择器 | 直传 |
| `limit` | int | 否 | 单次返回数据长度 | 分页 | 否 | 不暴露 | 执行层自动注入 |
| `offset` | int | 否 | 请求数据开始位移 | 分页 | 否 | 不暴露 | 执行层自动注入 |

### 3.2 输出字段（上游原生）

| 字段名 | 类型 | 含义 | 是否落库 |
| --- | --- | --- | --- |
| `trade_date` | str | 交易日期 | 是 |
| `ts_code` | str | 股票代码 | 是 |
| `name` | str | 股票名称 | 是 |
| `pct_change` | float | 涨跌幅 | 是 |
| `latest` | float | 最新价 | 是 |
| `net_amount` | float | 净流入（万元） | 是 |
| `net_d5_amount` | float | 5日主力净额（万元） | 是 |
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
- 历史：按区间映射交易日历逐日请求。
- 分页：当单次返回触达上限时，使用 `limit` + `offset` 翻页补齐当日数据。
- 保留 `ts_code` 作为定向补数入口（默认不填，走全市场）。

---

## 4. 参数与交互设计（Ops）

### 4.1 手动任务交互

1. 第一步：选择要维护的数据  
数据分组：股票  
维护对象：个股资金流向（THS）
2. 第二步：时间参数  
支持单日、区间
3. 第三步：其他输入条件  
`ts_code`（可选）

### 4.2 自动任务交互

- 资源：`moneyflow_ths.maintain`
- 默认参数：仅 `trade_date`（由调度注入）
- 可选扩展：`ts_code`

---

## 5. 落库与发布设计

### 5.1 路径选择

- 切换前路径：同一 normalized batch 同时 upsert `raw_tushare.moneyflow_ths` 与 `core_serving.equity_moneyflow_ths`
- 当前路径：只 upsert Raw，原 Serving 名称已由 revision 159 改为显式列投影的只读 view
- 选择理由：M0 已证明两层全部 13 个业务字段、主键和 21 个自然月数据完全一致，当前没有 Serving 专属业务转换
- 不在本次范围：引入 std、多源融合、修改 Tushare fields/分页/日期模型、修改 Ops 输入或自动任务时间

### 5.2 表设计

#### A. `raw_tushare.moneyflow_ths`

- 主键：`(trade_date, ts_code)`
- 审计字段：`api_name`, `fetched_at`, `raw_payload`
- 索引：
  - `idx_raw_tushare_moneyflow_ths_trade_date(trade_date)`
  - `idx_raw_tushare_moneyflow_ths_ts_code_trade_date(ts_code, trade_date)`

#### B. `core_serving.equity_moneyflow_ths`

- 主键：`(trade_date, ts_code)`
- 对外口径：与上游业务字段一致（不含审计字段）
- 当前形态：保留原 relation 名的 0 B 普通只读 view；13 个业务字段同名投影，`fetched_at AS created_at/updated_at`
- 索引：
  - `idx_equity_moneyflow_ths_trade_date(trade_date)`
  - `idx_equity_moneyflow_ths_ts_code_trade_date(ts_code, trade_date)`
- 透明边界：业务字段、名称和查询结果保持；不承诺 OID、relkind、view 自身约束/index catalog 与历史 `created_at` 值透明

---

## 6. 维护实现设计

- IngestionExecutor / SourceClient：`moneyflow_ths` 数据集维护链路
- 当前代码 `target_table`：`raw_tushare.moneyflow_ths`；Serving 仍通过原名称读取
- 当前生产部署为 commit `754f6c78`、revision 159 和 `raw_only_upsert`；Serving 原名称继续透明承载只读查询
- 参数构建：
  - `moneyflow_ths.maintain`：`trade_date` 或 `start_date+end_date` + 可选 `ts_code`
- 幂等：按主键 upsert
- 异常策略：上游异常按现有重试；参数异常中文提示
- 进度日志示例：
  - `moneyflow_ths: 12/82 trade_date=2026-04-16 fetched=5210 written=5210`

---

## 7. 数据状态与健康度观测

- 数据状态分组：资金流向
- 健康度口径：日期范围（`trade_date`）
- 展示名称：个股资金流向（THS）
- 异常文案：中文摘要 + 原始错误可追溯

---

## 8. 测试与验收

### 8.1 测试清单

- 单元测试：
  - 参数映射（单日/区间/可选 `ts_code`）
  - 交易日历推进
  - upsert 幂等
- 集成测试：
  - `moneyflow_ths.maintain`（单日/区间）
  - Ops 手动/自动任务链路
- 回归测试：
  - 不影响既有 `moneyflow` / `moneyflow_dc` 等数据集

### 8.2 验收勾选

- [x] 输出字段全量显式请求并落入当前 Raw/Serving
- [x] Ops 手动/自动任务、分页和日期推进合同已存在
- [x] 数据状态页可按 `trade_date` 展示
- [x] M0 已完成 21 月、2,077,033 行、13 字段生产只读等价审计
- [x] M1 raw-only Definition、ORM metadata、独立 migration 和自动化测试
- [x] M2 隔离 PostgreSQL 验证
- [x] M3a 生产切换与即时验收
- [x] M3b 首个自然工作流验收

---

## 9. raw 直出后续发布与回滚

- M1：只修改本数据集 storage contract、Raw ORM 的既存索引 metadata、独立 migration 和测试。
- M2：在隔离 PostgreSQL 验证 150,000/150,001 行容量、全字段/身份差异、依赖、ACL/comment、三类 DML、回滚、writer 与查询计划。
- M3a：实时暂停 schedule #4、停止 generic worker、最终对账后使用维护迁移模式切换；回收连接池、执行最小 TaskRun 后恢复 schedule。
- 自动 downgrade 禁止；DDL 提交前失败由同一事务原子回滚，提交后的物理回退必须另行授权并从 Raw 重建。

---

## 10. 已拍板结论（本数据集）

1. 自动任务默认不暴露 `ts_code`，仅保留手动页定向补数。
2. 单次返回触顶（6000）时，优先走 `limit` + `offset` 自动分页补齐，不启用 `ts_code` 二级扇出。
3. 纳入独立工作流：每日资金流向同步，不并入其它工作流。
4. 数据状态分组归属：资金流向。

---

## 11. 2026-08-29 `P1-B3-moneyflow_ths-M0` 只读审计结论

1. 当前生产 Raw/Serving 各 2,077,033 行，日期范围 `2024-12-19..2026-08-28`，21 个自然月全部 13 个业务字段双向 `EXCEPT ALL` 为 0；身份空值和 Raw `api_name` 异常均为 0。
2. 两层主键都是 `(trade_date, ts_code)`，日期与 `(ts_code, trade_date)` 索引等价。Raw ORM 漏声明两个生产既存二级索引，M1 只补 metadata，不重建索引。
3. 自然月峰值 116,993 行，业务行最大 134 B；M1 固定 150,000 行/层/月安全上限，M2 必须验证 150,001 行在 Serving DDL 前失败。
4. 五类 Raw/Serving 代表查询结果一致、索引正确、无临时块，Raw 最大正向退化约 9.43%，不需要复制竞价开盘数据集的 vacuum。
5. Lake Console 已直接读 Raw；仓库内未发现 Biz、QTF、frontend、DG 或脚本直接读取 Serving。唯一自动入口为 schedule #4 `daily_moneyflow_maintenance`，未来 M3a 只暂停/恢复该 schedule。
6. 35,990 行旧 Serving 的 `created_at != updated_at`；仓库内无审计时间消费者。目标 view 按一期固定边界把 Raw `fetched_at` 同时投影为 `created_at/updated_at`，业务字段透明，但历史 `created_at` 不属于透明承诺。
7. M0 结论：**通过，可在独立授权后进入 M1**。M0 没有修改代码、数据库、schedule 或任务，也没有请求 Tushare。

---

## 12. 2026-08-29 `P1-B3-moneyflow_ths-M1` 实施结论

1. Definition 只修改 storage delivery contract：Raw/`target_table`/freshness 统一指向 `raw_tushare.moneyflow_ths`，写路径改为 `raw_only_upsert`；13 个 source fields、交易日逐 unit、可选 `ts_code`、6,000 行分页、手动/定时/重试能力均保持不变。
2. Raw ORM 只补生产已存在的 `trade_date` 与 `(ts_code, trade_date)` 两个索引 metadata；revision 159 不创建、删除或重建 Raw 表和索引。
3. 独立 migration `20260829_000159` 接真实 head `20260829_000158`，固定 Raw→Serving 锁序、16 MiB `work_mem`、15 秒锁等待、120 秒 statement timeout、150,000 行/层/月容量门禁、13 字段双向 `EXCEPT ALL`、`(trade_date, ts_code)` 唯一性、对象依赖/ACL/comment/索引/tablespace 门禁和三类 DML 拒绝；禁止 `CASCADE`、共享拒写函数重建和自动 downgrade。
4. 专项与共享回归覆盖 Definition/plan/filter、ORM 类型/空值/主键/索引、Raw-only writer、Raw freshness/date-completeness target、ServingPublish 旁路、migration 离线 SQL 与禁止项；M1 未连接数据库、未请求 Tushare、未部署、未创建 TaskRun、未修改 schedule #4。
5. M1 结论：**通过**。下一阶段仅为另行授权的 M2，在隔离 PostgreSQL 验证 150,000/150,001 行、原子回滚、权限与三类 DML、正式 writer 即时可见和查询计划；不得把本轮代码测试当成数据库验收或生产切换证据。

---

## 13. 2026-08-29 `P1-B3-moneyflow_ths-M2` 隔离 PostgreSQL 验收结论

1. M2 使用本轮新建的 PostgreSQL 18.4 一次性实例，`listen_addresses=''`，只允许随机 Unix socket 连接；应用 migration 的角色为非超级用户。每次 Alembic 调用前均核对最终配置 URL、数据库、用户、socket、端口、`inet_server_addr=NULL`、恢复状态和 data directory，并把 `gs_raw_cold_hdd` 映射到临时目录用于身份门禁。本轮没有连接 Prod、请求 Tushare、部署、创建 TaskRun 或修改 schedule #4。
2. 150,000 行/月正向场景从 revision 158 成功应用 159。Raw relation OID `16392` 及主键、日期索引、`(ts_code, trade_date)` 索引 OID/定义/valid/ready 状态保持不变，全部继续位于 `pg_default`；Serving 从物理表变为 0 B 普通 view。Raw/view 都是 150,000 行和 150,000 个唯一身份，13 个业务字段双向差异为 0。
3. owner、Raw/Serving SELECT 权限、grant option、relation/column comments 与独立拒写 trigger 均恢复；Serving 的 `INSERT/UPDATE/DELETE` 全部返回 SQLSTATE `55000`。直接 Raw DML 和正式 `DatasetWriter` 写入都由 view 即时可见，writer 明确写入 `raw_tushare.moneyflow_ths`，事务回滚后没有残留。
4. 150,001 行、业务字段差异、身份差异、未知外部 view 依赖、缺失 Raw `(ts_code, trade_date)` 索引五个负向场景均在 Serving DDL 前失败，并保持 revision、relation、索引、行数、comments 与 trigger 快照不变；另一个场景在完成表转 view 后注入异常，整个 migration transaction 回滚到 revision 158 和原两张物理表。
5. 单日、单股票、股票区间、最大日期和日期完整性五类查询的结果行数与 hash 前后一致，计划从等价 Serving 索引下推到 Raw 索引，临时读写块均为 0。受控样本中批量查询实际耗时未见阻塞性退化；M3a 仍须用实时生产数据重新执行代表查询门禁。
6. 首次验证运行在 migration 已成功后，因测试脚本错误地强制单股票点查必须使用主键，而 PostgreSQL 合理选择了等价的 `(ts_code, trade_date)` 索引，故测试脚本主动判失败。该临时实例已停止，未把结果冒充通过；修正为“结果一致且命中等价实体日期索引”后，从全新数据目录完整复跑七个场景并全部通过。最终报告为 `/private/tmp/goldenshare_moneyflow_ths_m2_report.json`，成功实例已停止且数据目录已删除。
7. M2 结论：**通过**，revision 159 和业务代码无需修改。生产仍为 revision 158、两张物理表和旧双写部署；下一阶段只能是另行授权的 `P1-B3-moneyflow_ths-M3a`，并必须重新完成生产身份、任务、schedule #4、worker、锁、长事务、磁盘、全量对账和查询计划门禁。

---

## 14. 2026-08-29 `P1-B3-moneyflow_ths-M3a` 生产切换与即时验收结论

1. M3a 于 `18:47..18:57+08` 按维护合同完成。切换前生产为 commit `fe3caa3b`、revision 158；schedule #4 active 且下一次触发为 `2026-08-31 20:00+08`。开放 TaskRun、目标 node、目标 relation 锁、等待锁和 30 秒以上事务均为 0，Web、generic worker、scheduler、日期完整性和 TaskRun 收尾服务均 active，两个健康端点为 200。
2. 切换前 Raw/Serving 各 2,077,033 行和同数唯一 `(trade_date, ts_code)`，日期范围 `2024-12-19..2026-08-28`；21 个自然月逐月 13 字段双向 `EXCEPT ALL` 全为 0，月峰值 116,993。对象依赖门禁全部为 0，Raw/Serving 均为 `pg_default` 物理表，原 Serving 大小为 490,921,984 B。
3. 切换前五类查询结果一致、命中等价索引、临时块为 0。首次三轮中亚毫秒“最大日期”查询出现 0.037 ms 抖动，补做 21 轮交错复测后 Raw/Serving 中位数为 `0.109/0.121 ms`；其余有实际数据量的查询 Raw 相对 Serving 约 `-9.2%..+6.0%`，性能门禁通过且无需 vacuum。
4. schedule #4 通过正式服务暂停并由 config revision 127 留痕，cron、时区和 next/last timing 未改变；scheduler 与 generic worker 分别停止后，再次完成 21 月全量对账。`--maintenance-migration` 只安装 commit `754f6c78` 并应用 revision 158→159，没有前端构建、seed、unit 同步、隐式任务或服务重启。
5. Raw relation OID `22825` 保持不变，主键和两个二级索引仍 valid/ready 且位于 `pg_default`；Serving 由 OID `22890` 物理表变为 OID `2039022`、0 B 普通 view。owner、Raw `lake_raw_reader SELECT`、Serving ACL 和独立拒写 trigger 正确，三类 DML 均返回 SQLSTATE `55000` 且无测试残留；原 Serving 490,921,984 B 已由 catalog 确认释放。
6. Web、日期完整性和 TaskRun 收尾连接池回收后，远端运行时 Definition 明确为 `raw_tushare.moneyflow_ths + raw_only_upsert`。切换后五类 Raw/view 查询 hash 一致并全部下推 Raw 索引，无临时块；批量查询最大 view/Raw 相对开销低于 6%。
7. 正式 TaskRun `10128` 请求 `2026-08-28` 一个 point unit 并一次成功：1 页短页读取/保存 `5,211/5,211`，reject、去重、重试均为 0。目标日 Raw/view 各 5,211 行和身份，全部 5,211 行在任务窗口刷新，13 字段双向差异为 0；全表最终仍为 2,077,033 行和同数身份。
8. schedule #4 通过 config revision 128 原样恢复 active，scheduler 与 generic worker 均恢复；Web、日期完整性、TaskRun 收尾服务和两个健康端点全部正常，开放任务、锁和长事务为 0。根盘可用空间从预检 `51,782,713,344 B` 变为最终 `52,283,146,240 B`，但确定性释放量只认 catalog 的 490,921,984 B，不把文件系统噪声计入收益。
9. M3a 结论：**通过**。生产已经是 Raw 唯一物理事实表和读取透明的 0 B Serving view；`P1-B3-moneyflow_ths-M3b` 只待 schedule #4 下一次自然工作流观察，不创建额外任务、不重复请求源端。
10. `2026-08-29 19:07+08` 再次只读核对生产 `ops.schedule#4`：状态为 `active`，触发规则为工作日 `0 20 * * 1-5`、时区 `Asia/Shanghai`，上次触发为 `2026-08-28 20:00:21+08`，下一次为 `2026-08-31 20:00+08`。2026-08-29 为周六，当日不会出现自然运行；手工补造任务不能替代 M3b，且 M3b 尚未到触发时刻不阻塞下一数据集独立 M0。

## 15. 2026-08-31 `P1-B3-moneyflow_ths-M3b` 自然工作流验收与结案

1. schedule #4 于 `20:00+08` 创建 TaskRun `10359`，父任务为 `success`、workflow step `7/7/0` 完成。
2. `moneyflow_ths` node `16110` 成功处理 `2026-08-31`：1 页短页读取/保存 `5,210/5,210`，reject、去重、重试均为 0，未截断。
3. 最终目标日 Raw/view 各 5,210 行和 5,210 个唯一 `(trade_date, ts_code)`；13 个源业务字段双向差异为 0，Raw 5,210 行的 `fetched_at` 全部位于 node 执行窗口内。
4. 本轮只读核验复用既有自然工作流，没有创建额外任务、重复请求 Tushare 或修改 schedule #4。

`P1-B3-moneyflow_ths-M3b` **通过**。本数据集 M0/M1/M2/M3a/M3b 全部完成并结案。
