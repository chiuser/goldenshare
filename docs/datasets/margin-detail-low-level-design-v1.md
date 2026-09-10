# 融资融券交易明细（`margin_detail`）维护与低层设计

更新：2026-09-10。数据集、direct-serving、单日补录保护和独立 probe 已有代码；M0–M4、HDD 与 M5a/M5b 状态集中保留为 2026-08-03 历史记录。本轮不核实后续生产启用状态、不执行回补。

## 1. 现行合同

| 项目 | 行为 |
| --- | --- |
| 身份 / 来源 | `margin_detail` / `tushare.margin_detail` |
| 时间输入 | point 的 trade_date 或 range 的 start_date/end_date |
| 执行 | no_pool、generic planner，按开市日生成 unit；年度范围仍在内部逐日请求 |
| 可选代码 | 单证券精确补录，仅允许已有日期桶的 point，详见 §3 |
| 分页 | offset_limit，page_limit=1,000，fetch_concurrency=1 |
| 写入 | `serving_direct_upsert`；一个交易日完整分页后一次幂等 upsert/commit |
| 目标 | 唯一物理表 `core_serving.equity_margin_detail`；没有 Raw 表、raw_payload 或 Std |
| 观测 | trade_date；date_bucket 完整性，不是证券×日期矩阵 |
| 发布时序 | `next_open_day_0930`；自动维护只走独立三市场 probe |
| 运营展示 | A股行情，位于 margin 与 top_list 之间；无专用业务页面/API，不接 Lake |

[Definition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/market_equity.py)中 `raw_dao_name/raw_table=None`，core DAO 为 `equity_margin_detail`。历史接入曾需要扩展 storage/writer/linter/卡片投影以支持 direct-serving，现已实现；不能继续把“强制需要 Raw”写成当前合同，也不能因其他数据集改为 Raw/view 就擅自改变本表。

来源页应明确展示“服务表 core_serving.equity_margin_detail”，不伪造 Raw 层。业务提交与 Ops/TaskRun/ProbeRunLog/snapshot 观测写入隔离仍是硬约束；状态写入失败不能回滚或污染本表，不因删去通用施工清单而放宽。

通用合同见[DatasetDefinition 说明](/Users/congming/github/goldenshare/docs/architecture/dataset-definition-single-source-refactor-plan-v1.md)、[执行计划说明](/Users/congming/github/goldenshare/docs/architecture/dataset-execution-plan-refactor-plan-v1.md)及[开发模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)。本文只保留数据集专有规则。

## 2. 字段、质量与未完成项

每页正式请求及 probe 都显式使用以下 11 个字段，不能依赖默认返回：

```text
trade_date, ts_code, name, rzye, rqye, rzmre, rqyl, rzche, rqchl, rqmcl, rzrqye
```

[源文档 0059](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/两融及转融通/0059_融资融券交易明细.md)说明 name 在 2019-09-10 后才有数据。trade_date/ts_code 必填、构成主键；name 可空，八个数值字段按 Decimal 归一化并允许源端空值。

已实现质量规则：

- 返回 trade_date 不等于 unit 日期时阻断 unit。
- 相同主键且内容完全相同的行写前去重并记录；同键内容冲突则阻断，不能静默最后一行覆盖。
- 普通行 rejection 记录 reason 和样本，任何未解释的拒绝不能视为验收完成。
- 三市场样本服务于当前自动维护 readiness，不硬编码成历史写入必须同时具备 SH/SZ/BJ 的门禁；早期历史没有今天的市场结构。
- 空结果不能作为全市场已发布或日期完整的证据；不能用“短页结束”单独证明分页完整。

### 未兑现的原始目标：返回字段键完整性

原 LLD 要求“11 个源字段的键必须存在，缺键使 unit 失败；值为 null 按可空性处理”。**该目标保留，但正式同步尚未完整实现，不能标成已验收。**

[HTTP client](/Users/congming/github/goldenshare/src/foundation/clients/tushare_client.py)按响应字段组装行，[normalizer](/Users/congming/github/goldenshare/src/foundation/ingestion/normalizer.py)只检查 Definition 的 required_fields（本数据集仅 trade_date/ts_code）。正式链显式请求 11 字段，并不额外校验响应键齐全；[probe](/Users/congming/github/goldenshare/src/ops/services/margin_detail_remote_probe_service.py)则已检查全部 11 键。

2026-09-10 离线复现：只传 `trade_date=20260730, ts_code=600000.SH`，缺其余九键，normalizer 仍得到 accepted=1、rejected=0。未连源端或数据库，不证明生产发生过缺字段或损坏。后续补实现需单独批准，审计共享 source client/normalizer 消费者，并增加“键缺失拒绝、合法 null 接纳”两类负/正例；本轮只修文档，不撤销目标来迁就代码。

## 3. 手工补录与完整性边界

运营可无过滤维护单日/区间；`ts_code` 为六位数字加 SH/SZ/BJ 后缀的单代码，仅供已有日期桶定点补录：

1. `scoped_repair_policy=existing_point_bucket_only`；不接受多代码数组、逗号列表、通配符或带代码的 range。
2. [planner 预检](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py)先确认目标日已有行；桶不存在则以 `scoped_repair_bucket_missing` 拒绝，在源请求和写入前结束。
3. “已有桶”只证明日期存在，不证明该日全市场证券齐全；此保护避免单证券首次建桶伪造全量日期，不会补出一套证券矩阵审计。
4. 源端可选参数不全部暴露给运营。limit/offset/fields/exchange 不开放；运营的 start_date/end_date 表示 TaskRun 范围，不是原样传给源端的区间参数。

正式 [`_margin_detail_params`](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)为每个 unit 生成 trade_date；不复用 probe 的只读样本请求作为正式补录入口。freshness 按目标表业务日期及发布时序判断，不能拿一次单代码成功任务宣称全市场完整。

## 4. 存储、分区与部署边界

[ORM](/Users/congming/github/goldenshare/src/foundation/models/core_serving/equity_margin_detail.py)为 EquityMarginDetail，GenericDAO 注册为 equity_margin_detail。name 为 VARCHAR(64)，八个数值字段为 NUMERIC(20,4)，主键 `(trade_date,ts_code)`；另有 trade_date 索引及 `idx_equity_margin_detail_ts_code_trade_date_desc`。

[迁移 20260802_000123](/Users/congming/github/goldenshare/alembic/versions/20260802_000123_add_margin_detail_serving_dataset.py)固定创建年度 RANGE 分区 2010–2027 和 pmax。它不是按今天年份动态创建，也不自带未来年度维护任务；后续分区操作独立评估，禁止重建既有业务表。

已批准存储例外为全部历史及未来增量放在 `gs_raw_cold_hdd`，接受相应延迟；2026-08-03 的 19 叶/57 物理索引迁移证据见 §7。不能拿父级逻辑对象的位置代替叶/物理索引验收。若未来要回 SSD，须重新核验容量并获得逐对象授权。

## 5. 独立源站就绪探测

`MarginDetailRemoteReadinessProbeService` 独立于 margin 汇总服务，只共享 release target、TaskRun、ProbeRunLog 能力。同族说明见 [margin](/Users/congming/github/goldenshare/docs/datasets/margin-dataset-development.md)。

| 条件 | 固定边界 |
| --- | --- |
| condition / action | remote_margin_detail_ready / margin_detail.maintain |
| 日期 | 数据日 D 的下一个开市日 N，Asia/Shanghai 09:00–09:30 探测 D，不用自然日“昨天” |
| 样本 | SH 600000.SH、SZ 000001.SZ、BJ 920992.BJ |
| 请求 | Definition 的显式 11 fields，trade_date=D + 单样本代码；匹配精确代码/日期且所有键存在，值可按合同为空 |
| 绑定 | 仅 probe；300 秒、max_triggers_per_day=1、time_input={mode:point}、filters={} |
| 禁止 | 普通 cron、workflow、fallback、generic freshness 条件、calendar policy、固定日期和维护筛选 |
| 命中后 | 普通 TaskRun，point=D、filters={}；probe 本身不写 Serving |
| 去重 | 同一 schedule/D 的 queued/running/canceling/success/partial_success 任务阻止重复；failed 可按现有规则重触发 |

probe 直接构造受限的只读源请求，不走“已有桶补录”resolver，否则首次全市场写入前无法探测。正式任务仍必须走 resolver。运行时另强制清除持久化规则中的筛选并固定 point=D，不能因 API 被绕过就降为单证券自动任务。

任一样本 miss、缺字段、代码/日期错误或源端异常不创建任务；09:30 后仍未就绪可按发布时序显示 stale，不能伪造成功。三样本只是 readiness 代理，不证明全市场逐证券齐备。无重试时窗口最多 7 轮×3=21 次样本请求，不是账户级硬上限。

代码部署和迁移不会自动创建生产 schedule。运营启用仍需独立批准，通过 Ops 正式接口创建 schedule 和派生 probe rule，不复用 margin 的 id，不手写 seed 或直接改库。

## 6. 历史回补的执行与性能边界

原批准方向是自 2010 年按自然年分 TaskRun、内部按开市日 unit，不一次提交 2010 年至今的无界范围。page_limit=1,000 保留真实分页路径；4,418 行基准日需要五页，这是样本，不是每日最多五页。

宽区间源请求可分页不等于适合一个年度 unit：当前 source client 在 unit 内聚合全部页面，年度 unit 会放大内存、事务和失败重跑范围。**约 671 万行、8,009 请求是 2010–2025 共 16 年的按日估计合计，不是单年行数，也不是一次区间请求的分页数。**

未来年度批次执行前，按当时长任务基线及账户限额，取首/中/末开市日样本，记录行数、页数、耗时、重试/限流和存储预估；超出可接受量级先停下，不擅自改分页、并发或 source unit。每批验收 TaskRun 终态、unit_done/total、fetched/saved/rejected、reason、目标日期覆盖和实际行数。逐日 commit/幂等不等于已完整实现取消、退出与精准续跑门禁；本轮不开发新账本或扩大生产执行。

## 7. 2026-08-02/03 历史证据

以下记录不得推导今天仍空表、没有 schedule，或后续 M5 已完成。

### 源字段与分页

| 验证 | 当时结果 |
| --- | --- |
| 8 月 2 日 MCP 无参数 | 默认返回 6,000 行、覆盖 7 月 30–31 日；非全量依据 |
| 7 月 30 日单日 | 4,418 行，SH 1,992/SZ 2,098/BJ 328，唯一主键 4,418 |
| 未分页两日 | 6,000 行（4,007+1,993）；仅证明单次响应受限 |
| 默认/显式 fields | 默认 10 列缺 name；显式 11 列含“浦发银行”；8 月 1 日休市返回 0 |
| 发布样本 | 7 月 31 日仅 SH 样本有行，SZ/BJ 无；7 月 30 日三样本均有行 |
| M0 项目 connector | 单日 limit=6,000 基准 4,418；limit=1,000 五页为 1,000×4+418，合并键集合完全一致、每行 11 键 |
| 8 月 3 日区间分页 | 7 月 30–31 日七页为 1,000×6+411，共 6,411；与单日 4,418+1,993 的键并集一致，missing/extra=0 |

当时 MCP 包装器不暴露 limit/offset，分页证据来自项目实际 connector。两日样本证明区间分页可超过 6,000，不证明任意年度区间的内存、恢复和事务可接受；不保留“区间必然静默截断”的旧结论。

### M3 / M4 / HDD

- M3 在隔离 PostgreSQL 库 `goldenshare_margin_detail_m3_20260803` 从空库迁移至 000123，只有 direct-serving 表；4,418 行 fetched/normalized/written/目标唯一键一致，0 reject，11 字段逐键值相等。
- 同日重跑仍 4,418；已有桶 600000.SH 补录 1 行不扩大桶；不存在 7 月 29 日桶在源请求前拒绝，零请求零写入。
- 当时修正历史迁移 000068/000069/000071 对已退役表无条件 ALTER 的假设，完整空库迁移通过；这是历史实施记录，不授权今天重新建库或跑迁移。
- M4 当时 23 项后端 probe 测试通过，覆盖三样本、缺键、日期、节假日、运行时清洗和去重；前端单测与 mock smoke 覆盖唯一条件、固定窗口及隐藏输入。当时没有创建生产 schedule/probe_rule。
- HDD 执行前目标空、19 叶/57 物理索引、约 456 KB，机械盘可用约 324 GB。8 月 3 日无任务/长事务/外锁窗口中，独立 DDL 带 15 秒 lock_timeout，逐对象移动并复验；19/19 叶、57/57 物理索引、父表默认位置和 3 个父级逻辑索引均为 gs_raw_cold_hdd，行数仍为 0，无超时失败。
- 当时 M0–M4 与 HDD 验收完成，M5a 等运营手工回补、M5b 等自动增量授权；后续状态本轮未查，不将其继续列为今天待执行清单。

### 16 年规模估计（2026-08-03）

以每年末单日样本代表当年日均，仅用于历史规划初值：

| 年份 | 开市日数 | 样本交易日 | 样本行数 | 估计单日请求数 |
| --- | ---: | --- | ---: | ---: |
| 2010 | 242 | 2010-12-31 | 89 | 1 |
| 2011 | 244 | 2011-12-30 | 276 | 1 |
| 2012 | 243 | 2012-12-31 | 276 | 1 |
| 2013 | 238 | 2013-12-31 | 700 | 1 |
| 2014 | 245 | 2014-12-31 | 897 | 1 |
| 2015 | 244 | 2015-12-31 | 913 | 1 |
| 2016 | 244 | 2016-12-30 | 970 | 1 |
| 2017 | 244 | 2017-12-29 | 970 | 1 |
| 2018 | 243 | 2018-12-28 | 994 | 1 |
| 2019 | 244 | 2019-12-31 | 1,738 | 2 |
| 2020 | 243 | 2020-12-31 | 1,992 | 2 |
| 2021 | 243 | 2021-12-31 | 2,407 | 3 |
| 2022 | 242 | 2022-12-30 | 3,316 | 4 |
| 2023 | 242 | 2023-12-29 | 3,841 | 4 |
| 2024 | 242 | 2024-12-31 | 3,980 | 4 |
| 2025 | 243 | 2025-12-31 | 4,283 | 5 |

2010–2025 共 3,886 开市日，估计约 671 万行、8,009 次按日请求。隔离库 4,418 行占 1,810,432 B，约 410 B/行（含索引，元组平均 123 B），外推约 2.56 GiB；年末样本不代表峰值，膨胀、并发和返回分布会改变结果。源文档的 2,000 积分条件不等于已知账户分钟/日配额或完成时间承诺。

## 8. 回归入口与剩余边界

- [数据集测试](/Users/congming/github/goldenshare/tests/test_margin_detail_dataset.py)：字段请求、日期漂移、同键冲突、direct-serving 与补录保护。
- [独立 probe 测试](/Users/congming/github/goldenshare/tests/web/test_margin_detail_remote_probe.py)：源样本与绑定/运行时边界，运行前确认隔离环境。
- 正式源响应缺九个可选键的负例仍是 §2 已知缺口；通过现有样本测试不代表该门禁存在。
- 本轮不新增 Raw、修改 margin、创建业务 API、接入 Lake、启动历史回补或自动任务。任何字段校验修复和新的生产操作另行授权。
