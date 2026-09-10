# 每日涨跌停价格（`stk_limit`）维护说明

- 状态：当前实现为 Raw-only 写入、Serving view 查询；迁移专项于 2026-08-31 结案。
- 更新时间：2026-09-10（对照当前代码精简；未重新核验生产或请求源接口）。
- 适用范围：Prod 数据集维护、业务查询与完整性审计，不是 DG Lake 接入说明。
- 迁移依据：[Raw 直出一期 LLD](/Users/congming/github/goldenshare/docs/governance/prod-postgresql-raw-direct-serving-phase-one-lld-v1.md)。历史验收见 §5，不是待执行步骤。

## 1. 当前维护合同

事实源为 [DatasetDefinition：`stk_limit`](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/market_equity.py)。通用时间与执行规则分别见 [日期模型指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md) 和 [执行计划基线](/Users/congming/github/goldenshare/docs/architecture/dataset-execution-plan-refactor-plan-v1.md)。

| 项目 | 当前实现 |
| --- | --- |
| 维护动作 | `stk_limit.maintain`；支持手动、调度、重试；纳入 `daily_market_close_maintenance` 工作流 |
| 时间输入 | 单日 `trade_date`，或区间 `start_date + end_date`；不支持无时间全量 |
| 日期模型 | `trade_open_day / every_open_day / point_or_range`；观测字段 `trade_date` |
| 对象过滤 | 可选单个 `ts_code`；builder 去首尾空格并转大写；不通过对象池逐股票扇出（`no_pool`） |
| 执行单元 | 区间由交易日历展开为逐交易日 unit；每个 unit 请求单个 `trade_date`，不是直接向源端发整个区间；空交易日区间生成 0 个 unit |
| 分页 | 每页 `limit=5800`，`offset` 逐页递增；满页继续，返回少于 5800 行即结束（包含空页），不必等到空页 |
| 写入 | `raw_only_upsert`；每个 unit 提交，目标表为 `raw_tushare.stk_limit`；没有 Serving 双写 |

代码入口：[request builder](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)、[unit planner](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py)、[source client](/Users/congming/github/goldenshare/src/foundation/ingestion/source_client.py)。

本篇不把现有单元提交和 upsert 等同于“已实现进程退出后的持久化续跑”。后续若改造大范围回补或长任务，仍须按 [开发模板 §0.3.5](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md) 单独明确内存、进度、取消与续跑边界；本轮不改运行行为。

## 2. 源字段与存储

本地来源：Tushare **doc_id=183**，[每日涨跌停价格](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/行情数据/0183_每日涨跌停价格.md)。该资料描述全市场 A/B 股与基金、单次最多 5800 行；上游可选日期参数不等于本仓允许无时间维护。

当前代码每一页显式请求并落库五字段：`trade_date, ts_code, pre_close, up_limit, down_limit`。本地源文档将 `pre_close` 标为**非默认返回**，但代码已明确请求，市场情绪计算也会使用；不能照搬源文档的默认四列样例而删去它。本轮仅核对现有代码、本地资料及历史证据，没有形成新的源端实测结论。

| 层 | 物理形态与字段 | 身份与索引 |
| --- | --- | --- |
| Raw：`raw_tushare.stk_limit` | 唯一物理事实表；五个业务字段及 `api_name / fetched_at / raw_payload` | 物理主键 `(ts_code, trade_date)`；日期索引 `idx_raw_tushare_stk_limit_trade_date` |
| Serving：`core_serving.equity_stk_limit` | 显式只读 view；五个业务字段及 `fetched_at AS created_at / updated_at` | 业务身份仍为 `(ts_code, trade_date)`；view 无物理主键、索引，查询使用底层 Raw 索引 |

[Raw ORM](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_stk_limit.py) 与 [Serving ORM](/Users/congming/github/goldenshare/src/foundation/models/core/equity_stk_limit.py) 都仍被注册。Serving ORM 保留的主键、索引元数据不代表数据库里仍有同名物理表或索引；它仍是查询映射，不能因只写 Raw 就删除。

Definition 的两个 DAO 名均为 `raw_stk_limit`，交付模式为 `raw_with_serving_view / raw->serving_view`。[迁移 20260830_000162](/Users/congming/github/goldenshare/alembic/versions/20260830_000162_make_stk_limit_raw_view.py) 建立 view 及独立拒写 trigger；Serving 的 INSERT、UPDATE、DELETE 被拒绝，禁止自动 downgrade。修数通过正式 Raw 维护链路完成，不向 view 写入。

## 3. 谁在读，审计读哪里

| 使用方 | 当前读取与用途 | 不能混淆的边界 |
| --- | --- | --- |
| [MarketMoodCalculator](/Users/congming/github/goldenshare/src/biz/services/market_mood_calculator.py) | 通过 `EquityStkLimit` 按证券代码和交易日外连接 Serving；用昨收与涨跌停价计算涨跌停相关指标 | `pre_close` 有计算用途；不能删除 view 或 ORM，也不能在文档中擅自改为直接读 Raw |
| [MarketMoodWalkForwardValidationService](/Users/congming/github/goldenshare/src/biz/services/market_mood_walkforward_validation_service.py) | 查询 Serving 在某交易日是否有涨跌停价格，配合日线、复权因子等筛选可走查日期 | 仅有日期存在性检查，不证明当天全股票齐全 |
| Ops freshness 与 [日期完整性审计](/Users/congming/github/goldenshare/src/ops/services/date_completeness_audit_service.py) | 从 Definition 投影目标表 `raw_tushare.stk_limit` 和观测字段 `trade_date` | 不再以旧 Serving 物理表作为审计目标 |

日期完整性不是“当天有一行就通过”，而是 **日期 × 股票**（`date_subject_matrix`）检查：

- 预期股票集合来自 `core_serving.security_serving`，策略为 `stock_basic_active_lifecycle`：`ts_code` 非空，`list_status=L`，上市日为空或不晚于被审计日，退市日为空或不早于被审计日。
- 实际集合为 Raw 在该日的去重 `ts_code`（应用该次审计的实际行过滤条件），再对照预期集合计算缺失。
- `no_pool` 只表示源请求不按对象池扇出，**不表示完整性审计没有预期股票集合**。源端 A/B 股和基金的全量返回，也不等于配置中的股票审计范围；不要用源端总行数直接代替矩阵验收。

## 4. 回归入口

直接合同测试：[test_stk_limit_raw_view_m1.py](/Users/congming/github/goldenshare/tests/test_stk_limit_raw_view_m1.py)，覆盖 Definition 的 Raw-only 映射、过滤参数、逐页五字段与 `5800+1` 短页终止、只写 Raw、ORM 元数据、无 ServingPublish、迁移 SQL 顺序和 downgrade 拒绝。离线 SQL 测试不等于真实数据库迁移验收。

相关共享回归按改动范围选取：

- [Definition registry](/Users/congming/github/goldenshare/tests/test_dataset_definition_registry.py)、[Ops action catalog](/Users/congming/github/goldenshare/tests/test_ops_action_catalog.py)、[字段常量](/Users/congming/github/goldenshare/tests/test_fields_constants.py)、[ORM](/Users/congming/github/goldenshare/tests/test_extended_models.py)。
- [freshness 投影](/Users/congming/github/goldenshare/tests/test_ops_freshness_snapshot_query_service.py)、[日期主体矩阵 API](/Users/congming/github/goldenshare/tests/web/test_ops_date_completeness_api.py)、[runtime registry 边界](/Users/congming/github/goldenshare/tests/architecture/test_dataset_runtime_registry_guardrails.py)。

## 5. 历史迁移与结案证据（2026-08-29～31）

以下为原执行记录摘要，**不是今天的生产状态快照、调度配置或重新执行授权**。完整阶段步骤和诊断可从 Git `5e302146:docs/datasets/stk-limit-dataset-development.md` 追溯；不再在当前维护正文保留已完成阶段的“下一步”指令。

### 5.1 M0：等价性与边界

- 当时 Raw/Serving 均为物理表，各 4,608,112 行和同数唯一身份，覆盖 `2024-01-02..2026-08-28`。32 个自然月、五个业务字段双向差异为 0；月峰值 177,009 行。
- 为本次迁移设定 **220,000 行/层/月** 容量门禁，`work_mem=16MB`、`statement_timeout=300s`，逐月有界对账。这不是日常同步行数上限，也不是后续业务 SLA。
- 历史 `updated_at` 全部与 Raw `fetched_at` 一致，但 **514,328 行的旧 created_at 不同**。当时未发现仓库内时间戳消费者，采用 view 的统一投影；只承诺五个业务字段等价，不承诺旧创建时间、OID 或物理约束元数据不变。仓库外 SQL/BI/人工脚本仍需运营确认。

### 5.2 M1/M2：实现与隔离验收

- M1 仅切换本数据集 storage delivery；迁移 `20260830_000162` 接当时真实 head `20260829_000161`。保持源字段、分页、日期输入、过滤、工作流和业务查询入口不变。
- 迁移先验证结构、权限、依赖与容量，按 Raw SHARE → Serving SHARE → 逐月身份/五字段对账 → Serving ACCESS EXCLUSIVE 切换；无 CASCADE、无 Raw DDL/DML，恢复 Serving metadata 并创建独立拒写 trigger。
- PostgreSQL 18.4 隔离实例中，220,000 行通过；220,001 行、字段/身份差异、Raw 类型漂移、未知依赖、缺日期索引、额外 Raw ACL 均在 Serving DDL 前拒绝。Raw OID/索引不变；owner、ACL、comments 恢复。
- Serving INSERT/UPDATE/DELETE 返回 SQLSTATE `55000`；Raw 修改在 view 可见，回滚无残留。DROP/CREATE/trigger 后注入错误亦完整事务回滚。市场情绪 join 和日期存在性查询的结果/hash 一致，使用 Raw 索引、无临时块。
- 当时的一次性实例已停止、临时数据目录已删除；临时报告路径不作为长期可靠入口。

### 5.3 M3a：生产切换与即时验收（2026-08-30）

- 在维护窗口暂停当时两个 workflow schedule（#24/#2）及相关领取服务，应用 revision 161 → 162 后原样恢复。部署 `da84a32a`；窗口内另有后继 `4e54dec8` 的文档提交，不涉及本项运行代码。
- Raw 表及主键/日期索引 OID 未变；Serving 成为 0 B view，释放旧 Serving relation 的 catalog 毛量 **664,354,816 B（633.58 MiB）**。Raw/view 的行数、身份、32 月五字段及时间投影一致；三类 DML 拒写通过。
- 20 日市场情绪 join 约 567 → 575 ms（约 +1.5%），64 日日期存在性查询约 0.76 ms，均使用 Raw 索引、无临时块或超过当时 20% 停止线的结构性退化。这些只是该次迁移样本，不是现行性能承诺。
- 唯一受控 TaskRun **10182** / node **15895** 维护 `2026-08-28`：两页 `5800+1968`，读取/保存各 7,768，reject/去重/重试为 0；最终短页，当日身份无重复、五字段差异为 0，全表行数未增加，验证同日刷新幂等。
- 当时已恢复两个 schedule 和相关服务；此结论不代替今天的开关检查。

### 5.4 M3b：双自然工作流验收与结案（2026-08-31）

| 历史自然入口 | 父 TaskRun / 目标 node | 验收结果 |
| --- | --- | --- |
| schedule #24，18:30+08 | 10343 / 16064 | 父任务与 `stk_limit` 节点成功；其他节点 `irm_qa_sh` 的 1 行 reject 单列处理 |
| schedule #2，21:02+08 | 10371 / 16135 | `stk_limit` 节点成功；父任务因 `anns_d` 失败为 partial_success，不能混作本节点失败 |

两个目标 node 均为 `5800+1968` 两页、读取/保存各 7,768，最终短页，reject/去重/重试为 0。最终 Raw/view 各 7,768 行和唯一身份，五字段差异为 0，全部 `fetched_at` 位于第二次执行窗口；两次自然运行未增加当日行数。

至此 **M0/M1/M2/M3a/M3b 全部结案**。其他节点的问题保留为独立事项，不重新打开本数据集迁移，也不在本篇声称它们已经修复。
