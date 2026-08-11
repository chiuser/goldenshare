# 指数详情页 M0 生产因子审计 v1

> 审计日期：2026-08-11
>
> 审计环境：生产 PostgreSQL，只读事务
>
> 结论：**通过 M0 当前生产快照的数据覆盖与旧候选 joined 查询的保守性能门禁；冻结 factor 量额源选择规则。最终 factor-only SQL 在 M1 精确复测。MA 空值只记录为审计时点现象，不冻结指数、日期或固定 warm-up 区间。**

## 1. 目标与边界

本审计回答四个问题：

1. 首页 10 个指数是否都有可支撑默认 300 根日线的 `idx_factor_pro` 数据。
2. 页面需要的 OHLC、MA、BOLL、MACD、KDJ 字段是否可用，空值是否可解释。
3. 因子行情与正式指数日线是否同日、同价、同量额口径。
4. 当时的 factor + daily 候选 K 线查询在生产数据上的索引路径和数据库内耗时是否合格；后续源选择修订后的 factor-only SQL 另行复测。

本次不审计 page-init、权重完整响应体、Web 进程序列化或浏览器端到端 P95；这些在 API 落地后按 M1/M2 门禁继续验收。

## 2. 只读保护与查询范围

| 项目 | 实际执行 |
|---|---|
| 连接方式 | 仓库 `scripts/psql-remote.sh`，凭据不输出 |
| 事务 | `REPEATABLE READ, READ ONLY`，最终 `ROLLBACK` |
| 超时 | statement 30 秒，lock 2 秒 |
| 业务表白名单 | `core_serving.index_factor_pro`、`core_serving.index_daily_serving` |
| 元数据白名单 | `pg_catalog` 中上述关系与索引 |
| code | 仅 10 个 `majorIndices/CN_A` code |
| 字段 | 最终 K 线 DTO 所需 27 个字段；无 `SELECT *` |
| 质量窗口 | 每 code 最近 300 条；历史覆盖只做聚合 |
| 性能样本 | 300/2000 limit × 10 code × 5 轮，共 100 次 `EXPLAIN ANALYZE` |
| 原始明细导出 | 无；只保留聚合、每 code 最新一行诊断和执行计划 |

本机临时证据：

1. `/private/tmp/index_detail_m0_prod_factor_audit_20260811.log`
2. `/private/tmp/index_detail_m0_prod_factor_diagnostics_20260811.log`

临时日志不进入仓库，也不包含凭据或连接串。

## 3. 当前代码与存储事实

1. `IndexFactorPro` 是 `core_serving.index_factor_pro` 的只读 ORM。
2. 生产该对象是 view，直接读取 `raw_tushare.idx_factor_pro`。
3. raw 基表主键为 `(ts_code, trade_date)`，另有 `trade_date` 索引。
4. `index_daily_serving` 主键同样是 `(ts_code, trade_date)`。
5. 本页只需要 27 个字段：2 个键、7 个价格/涨跌字段、2 个量额字段、7 个 MA、3 个 BOLL、3 个 MACD、3 个 KDJ。
6. Tushare `idx_factor_pro` 和 `index_daily` 文档均将 `vol` 定义为“手”、`amount` 定义为“千元”。

### 3.1 CodeGraph 影响面

本轮使用 `codegraph status/search/impact`，仓库根索引为 up-to-date：

1. `IndexFactorPro` 是现有 raw-backed serving view 的只读模型；本轮不修改模型、DatasetDefinition、DAO factory 或 writer。
2. `StockDetailPageInitResponseDto` 已被后端 schema、前端 API type、adapter 与页面消费；指数详情必须新增独立 DTO，禁止向股票响应加字段。
3. 主要指数卡片 DTO 继续只负责首页 10 卡；详情页只复用 `majorIndices/CN_A` 配置，不修改卡片响应。
4. 既有 Quote trend-channel 继续只服务 `000001.SH + day`；本轮 DTO 不包装、不修改该 contract。
5. M0 只新增文档合同，不改变 `foundation -> biz -> app` 依赖方向，也不触发架构快照更新。

## 4. 10 指数覆盖结果

所有 code 的最新日都与 `index_daily_serving` 对齐到 `2026-08-10`，主键无重复。

| 顺序 | code | 因子行数 | 日期范围 | 最近 300 根 | 结论 |
|---:|---|---:|---|---:|---|
| 1 | `000001.SH` | 388 | 2025-01-02 ~ 2026-08-10 | 300 | 通过 |
| 2 | `399001.SZ` | 388 | 2025-01-02 ~ 2026-08-10 | 300 | 通过 |
| 3 | `399006.SZ` | 388 | 2025-01-02 ~ 2026-08-10 | 300 | 通过 |
| 4 | `000688.SH` | 388 | 2025-01-02 ~ 2026-08-10 | 300 | 通过 |
| 5 | `000300.SH` | 388 | 2025-01-02 ~ 2026-08-10 | 300 | 通过 |
| 6 | `000905.SH` | 388 | 2025-01-02 ~ 2026-08-10 | 300 | 通过 |
| 7 | `000852.SH` | 388 | 2025-01-02 ~ 2026-08-10 | 300 | 通过 |
| 8 | `899050.BJ` | 388 | 2025-01-02 ~ 2026-08-10 | 300 | 通过 |
| 9 | `000510.SH` | 388 | 2025-01-02 ~ 2026-08-10 | 300 | 通过；当前快照 MA250 为 206/300 非空 |
| 10 | `000016.SH` | 388 | 2025-01-02 ~ 2026-08-10 | 300 | 通过 |

重复 `(ts_code, trade_date)`：0。

## 5. 字段覆盖与动态历史边界

最近 300 根内：

1. 10 个指数的 OHLC、昨收、涨跌、涨跌幅、量额、MA5/10/20/30/60/90、BOLL、MACD、KDJ 全部 300/300 非空。
2. 9 个指数的 MA250 为 300/300 非空。
3. `000510.SH` 的 MA250 为 206/300 非空。

`000510.SH` 全历史 MA250 诊断：

| 项目 | 结果 |
|---|---|
| 因子总行数 | 388 |
| MA250 null | 182 |
| null 日期范围 | 2025-01-02 ~ 2025-09-29 |
| 首个可用日 | 2025-09-30 |
| 首个可用日之后非空行数 | 206 |

以上结果只描述 2026-08-11 审计时生产 PostgreSQL 中已有的物理数据。当时每个 code 只覆盖 2025-01-02 之后的 388 行；更早的 2024 技术因子正在同步，因此不能据此推断 `000510.SH` 的长期历史边界，也不能把 `2025-09-30` 固化成 MA250 的业务分界日。

冻结的通用规则如下：

1. 不按指数代码、固定日期、当前表起点或“首个非空值之前”预设 warm-up 区间。
2. `maN` 是否属于合理的历史不足，只能按同一 code 截至该交易日实际可用的有效历史 K 线根数判断；有效根数小于 N 时，源字段为 null 才属于历史不足。
3. 历史根数必须基于数据源实际历史计算，不能直接拿本次接口的 `limit` 或前端可见窗口长度判断。
4. 源字段有值就原样返回；源字段为 null 时 DTO 仍保持 null，图表断点，不补 0、不向前填充，也不在详情接口临时重算均线。
5. 实际有效历史已达到 N 根但 `maN` 仍为 null 时，属于异常缺失，登记 `ID_FACTOR_PARTIAL`；不得继续按 warm-up 豁免。

因此，`000510.SH` 的 182 行 MA250 null 只是本次快照观察，不是代码特例。2024 数据同步完成后必须重新执行覆盖审计；回填带来的非空值和历史根数变化应由同一通用规则自动生效，不需要修改代码。

## 6. 与正式指数日线的一致性

### 6.1 日期与价格

最近 300 根的同日 join 均为 300/300。以下字段最大绝对差均为 0：

`open/high/low/close/pre_close/change/pct_change`。

### 6.2 量额异常

量额存在生产源值分叉：

| code | 异常交易日数 | 日期范围 | 最新日 vol 比值（factor/daily） | 最新日 amount 比值 |
|---|---:|---|---:|---:|
| `399001.SZ` | 26 | 2026-07-06 ~ 2026-08-10 | 2.819215 | 1.715006 |
| `399006.SZ` | 26 | 2026-07-06 ~ 2026-08-10 | 4.890341 | 2.049293 |

其余 8 个指数没有超过 1 个源单位的量额差异。两个接口的文档单位相同，且异常只从固定日期开始，不能用固定倍率解释。产品方随后使用外部数据源核对 5 个抽样交易日，确认 `index_factor_pro` 的量额准确；该确认是本次源选择决策依据，生产数据库审计本身只证明两源分叉，不单独证明哪一侧正确。

因此禁止：

1. 猜测单位并做倍率换算。
2. 对两个源取平均、最大值或任意 fallback。
3. 指数详情从 `index_daily_serving` 读取或回退成交量、成交额。

### 6.3 冻结的源选择

最终日线 K 线采用：

| 页面字段 | 唯一来源 |
|---|---|
| Kline `tradeDate/open/high/low/close/preClose/change/changePct/vol/amount` | `core_serving.index_factor_pro` |
| Kline `MA/BOLL/MACD/KDJ` | `core_serving.index_factor_pro` |
| page-init 基本行情 `vol/amount` | 与 `asOfTradeDate` 同 code、同交易日的 `core_serving.index_factor_pro` |

`index_daily_serving` 仍用于 page-init 的日期和价格锚点，但它的 `vol/amount` 不进入指数详情 DTO。若 `asOfTradeDate` 的 factor 行或其量额缺失，基本行情量额为 null、页面 PARTIAL；Kline 中 factor 量额缺失同样为 null + PARTIAL。两条链都不得回退 daily 量额，确保基本行情与图表使用同一个 factor 事实源。

## 7. 查询形态与性能

最终 Kline 查询只读 factor 的 27 个 DTO 字段，先 `trade_date DESC LIMIT`，服务层再反转为升序，不再 JOIN daily。

生产计划稳定使用：

1. factor：`pk_raw_tushare_idx_factor_pro` 反向索引扫描。
2. 无全表顺序扫描，无无界排序。

数据库内 50 个样本汇总：

| 请求 limit | 实际每 code 行数 | min | P50 | P95 | max | 平均 |
|---:|---:|---:|---:|---:|---:|---:|
| 300 | 300 | 1.395ms | 1.555ms | 1.636ms | 1.925ms | 1.559ms |
| 2000 | 388 | 1.163ms | 1.425ms | 2.127ms | 2.163ms | 1.471ms |

结论：上述样本来自更复杂的 factor LEFT JOIN daily 旧候选查询，当前生产数据规模下仍远低于 API P95 400ms 目标与 1s 硬门禁。最终 factor-only 查询删除了 daily JOIN；该项在 M0 时仍待复测，现已由第 9 节 M1 补充完成，不能把本节旧候选查询指标冒充为最终链路实测。

限制：M0 快照每 code 只有 388 条 factor 数据，所以 `limit=2000` 当时只证明 2000 上限请求的查询计划与当前响应耗时，不证明真实 2000 行 payload、序列化或 Web-host 到 PostgreSQL 的端到端 P95。修正后的 LLD 还会在返回 MA null 时追加一次实际历史基数查询；该条件查询和当前实返 455~630 行的服务链已在第 9 节补验，但不足 2000 行仍不能伪称“2000 行性能已验收”。

## 8. M0 判定

| 门禁 | 判定 | 证据/处理 |
|---|---|---|
| 10 code 有数据 | PASS | 全部 388 行 |
| 最新日与 daily 对齐 | PASS | 全部 2026-08-10 |
| 默认 300 根 | PASS | 全部至少 300 |
| 主键唯一 | PASS | 0 重复 |
| OHLC/涨跌一致 | PASS | 最近 300 根最大绝对差 0 |
| 技术字段覆盖 | PASS（当前快照） | 记录 A500 MA250 的 182 行前缀空值；不冻结 code/date 特例，2024 数据同步后需复审 |
| 量额事实源 | PASS（外部核对后拍板） | 指数详情统一取 factor；禁止 daily fallback |
| 最终 SQL 索引路径 | PASS | factor 主键反向扫描；删除 daily JOIN |
| 旧候选 joined 查询 P95 | PASS（保守参考） | 300: 1.636ms；2000-limit: 2.127ms |
| 最终 factor-only 查询 P95 | PASS（M1 补充） | 见第 9 节：300 根 1.681ms；2000 上限实返 630 根 1.869ms |
| MA 历史基数条件查询 P95 | PASS（M1 补充） | 见第 9 节：2.063ms；完整 Kline 服务链 P95 同步通过 |
| 真实 2000 行 API P95 | DEFERRED | API 落地且数据具备后验收 |

M0 当前快照的数据门禁通过，已具备进入独立 DTO/API 的 M1 数据与合同条件；是否进入 M1 仍按编码门禁确认。M1/M2 不能删除本报告记录的量额源选择、动态历史判断和真实 2000 行性能限制。2024 数据同步完成后的覆盖复审是生产验收项，不把本次快照日期固化进实现。

## 9. M1 实现后只读复验补充

2026-08-11 在 M1 三条正式接口实现后，使用同一 10 code、显式只读事务和最终字段投影复验。该节是后续时点补充，不覆盖第 4~8 节的 M0 原始快照。

### 9.1 当前覆盖快照

1. `000001.SH`、`399001.SZ`、`399006.SZ`、`000688.SH`、`000300.SH`、`000905.SH`、`000852.SH`、`899050.BJ`、`000016.SH` 当前均为 630 行，日期范围 2024-01-02 ~ 2026-08-10，MA250 为 630/630 非空。
2. `000510.SH` 当前为 455 行，日期范围 2024-09-23 ~ 2026-08-10，MA250 为 206/455 非空。
3. 以上变化说明 2024 因子同步已经改变物理覆盖。实现不根据这些数字、code 或日期推断 warm-up；仍按同 code 截至目标 bar 的实际有效历史根数动态判断。
4. 10 个指数最新权重日期均为 2026-07-31；批次 `count(*) = count(weight) = count(distinct con_code)`，当前批次合同完整，行数范围 50~2224。

### 9.2 最终 SQL 与完整服务链

| 项目 | 结果 |
|---|---:|
| factor-only 300 根 `EXPLAIN ANALYZE` | 1.681ms，主键反向索引扫描 |
| factor-only 2000 上限，实返 630 根 | 1.869ms，主键 bitmap scan + 单 code 内存排序 |
| MA 历史基数条件查询 | 2.063ms，主键 bitmap index scan |
| page-init latest daily + 同日 factor | 0.071ms，两侧主键索引 |
| 上证 2224 成分 breadth 聚合 | 4.488ms |
| 上证完整 weights LEFT JOIN | 12.927ms |

按 10 code × 5 轮计 50 个样本，本机到生产库、包含 query/service、DTO 和 JSON 序列化的 P95：page-init 246.054ms、kline 300 211.169ms、kline 2000 上限 248.925ms、weights 271.337ms，均通过 LLD 预算。该结果不包含 HTTP Server 中间件，也不是生产 Web-host 同拓扑；kline 2000 当前仅实返 455~630 行，所以真实 2000 行性能门禁继续保留。
