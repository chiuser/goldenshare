# 股票开盘与收盘集合竞价维护说明

更新时间：2026-09-10。状态：现行实现说明，合并原开盘、收盘接入文档。两项接入及 Raw 直出专项的历史结案证据见 §6；本文不重新认证今天的生产状态，不授权再次执行迁移、同步或维护窗口。

依据：[DatasetDefinition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/market_equity.py)、[日期消费指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)、[执行计划与可靠执行](/Users/congming/github/goldenshare/docs/architecture/dataset-execution-plan-refactor-plan-v1.md)、[数据集模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)。本次只合并文档，不合并两个数据集、物理对象或迁移。

## 1. 两个数据集与共同边界

| 项目 | 开盘集合竞价 | 收盘集合竞价 |
| --- | --- | --- |
| Dataset / Tushare API | `stk_auction_o` | `stk_auction_c` |
| 维护动作 | `stk_auction_o.maintain` | `stk_auction_c.maintain` |
| Raw 写入及观测目标 | `raw_tushare.stk_auction_o` | `raw_tushare.stk_auction_c` |
| Serving 查询视图 | `core_serving.equity_auction_open` | `core_serving.equity_auction_close` |
| Raw/core DAO 配置 | 两者均为 `raw_stk_auction_o` | 两者均为 `raw_stk_auction_c` |
| Ops A股行情排序 | 82 | 84 |
| 本地源资料 | [doc 353：开盘集合竞价](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/特色数据/0353_股票开盘集合竞价数据.md) | [doc 354：收盘集合竞价](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/特色数据/0354_股票收盘集合竞价数据.md) |

两者均为股票行情域、Tushare 单源。源资料描述的是开盘 9:30 / 收盘 15:00 集合竞价，均在盘后更新，需股票分钟权限；这不是对当前账户权限或固定日内就绪时间的实测。不得与不同含义的 `stk_auction`“当日集合竞价”接口混用。

支持手动维护、自动任务配置和重试。已加入[每日收盘后维护工作流](/Users/congming/github/goldenshare/src/ops/action_catalog.py)：相邻顺序为 `daily → stk_auction_o → stk_auction_c → adj_factor`，不是待新增步骤。[Ops 展示目录](/Users/congming/github/goldenshare/src/ops/catalog/dataset_catalog_views.py)管理分组和排序，不回写 Definition domain。工作流存在不代表当前生产 schedule 一定启用；历史 schedule 记录见 §6。

## 2. 输入、请求与日期观测

```text
手动 / 自动 / Workflow 意图
  → Ops TaskRun → DatasetActionResolver → 每个开市日一个 unit
  → trade_date + 可选 ts_code → 分页 → 归一化 → Raw upsert 并提交
  → Serving 视图直接读取 Raw；Ops 独立记录结果
```

- 时间输入：point 使用 `trade_date`，range 使用 `start_date/end_date`；日期模型为 `trade_open_day + every_open_day + point_or_range`，观测字段为 `trade_date`。
- 范围：`no_pool + generic`，不按股票池扇出；不传 `ts_code` 时请求该日全市场，传入时只作单股筛选。它不是指数因子那种禁止代码筛选的合同。
- 参数：`_stk_auction_o_params()` / `_stk_auction_c_params()` 共用 `_stk_auction_params()`，只生成当前 unit 的 `trade_date=YYYYMMDD` 与可选 `ts_code`；代码参数去空格、转大写。运营日期区间先展开为开市日，不作为源端大区间直接透传。
- 分页：`offset_limit`、每页 10,000 行；满页继续、不足页结束。`limit/offset` 由 source client 追加，不是运营输入。
- 观测：freshness 为 `continuous_open_day`，完整性为 `date_bucket`，不是全市场逐股票矩阵。任务成功、日期桶存在与全部股票齐备不能互相替代；当前允许空结果，因此成功节点也可能是 `0/0`。

实现入口：[resolver](/Users/congming/github/goldenshare/src/foundation/ingestion/resolver.py)、[unit planner](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py)、[request builders](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)、[source client](/Users/congming/github/goldenshare/src/foundation/ingestion/source_client.py)、[freshness 策略](/Users/congming/github/goldenshare/src/foundation/datasets/freshness_policies.py)。源端历史上无参数可返回最近数据，不意味着平台应开放无时间 snapshot 维护。

## 3. 字段与真实写入合同

两者显式请求相同的 9 个字段：`ts_code, trade_date, close, open, high, low, vol, amount, vwap`；分别表达各自时段的竞价数据。主键均为 `(ts_code, trade_date)`。

| 字段组 | Raw 类型与处理 |
| --- | --- |
| `ts_code` / `trade_date` | `VARCHAR(16)` / `DATE`，必填身份 |
| `close/open/high/low/vwap` | `Numeric(18,4)`，可空，0 值不作为空值拒绝 |
| `vol/amount` | `Numeric(20,4)`，可空 |
| 内部审计列 | `api_name`、`fetched_at`、`raw_payload`，不进入源字段请求 |

[normalizer](/Users/congming/github/goldenshare/src/foundation/ingestion/normalizer.py)及 [coerce_row](/Users/congming/github/goldenshare/src/utils.py)转换日期和 Decimal，检查必填字段、记录拒绝原因；两者没有专用 row transform。这里不能把请求参数的 `ts_code.strip().upper()` 写成对源端返回代码的清洗保证。

当前两者均为 `delivery_mode=raw_with_serving_view`、`layer_plan=raw->serving_view`、`write_path=raw_only_upsert`。[writer](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py)只向 Raw upsert，结果的 `target_table` 也是 Raw；不再向 Serving 写第二份业务数据。Ops 的[观测投影](/Users/congming/github/goldenshare/src/ops/dataset_definition_projection.py)读取这个 Raw target，不能把 Serving 查询入口当作写入/观测目标。

Raw 有物理主键及各自的单列日期索引 `idx_raw_tushare_stk_auction_o_trade_date` / `idx_raw_tushare_stk_auction_c_trade_date`。Serving 普通视图显式投影 9 个业务字段，另以 `fetched_at` 同时提供 `created_at/updated_at`，共 11 列；没有独立物理主键、索引或业务副本。

[Raw 开盘 ORM](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_stk_auction_o.py)、[Raw 收盘 ORM](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_stk_auction_c.py)与 [Serving 开盘 ORM](/Users/congming/github/goldenshare/src/foundation/models/core_serving/equity_auction_open.py)、[Serving 收盘 ORM](/Users/congming/github/goldenshare/src/foundation/models/core_serving/equity_auction_close.py)仍存在。Serving ORM 保留了主键/索引 metadata，不能据此认定生产仍是物理表，也不能因主写入不再使用 Serving 就擅自删除 ORM、DAO 或映射。

## 4. 事务、容量与查询边界

每个交易日一个事务单元，当前 `page_processing_mode=buffer_all`：单 unit 的全部分页先在内存汇集，再归一化、写入、提交，不是每页提交。10,000 是页大小，不是单日行数或内存上限；`max_source_rows_per_unit/max_units_per_execution` 均未设上限。不能用约 5,500 行的历史单日样本承诺所有范围的容量和耗时。

Raw 主键 upsert 支持既有身份刷新，历史重跑证据见 §6；但这不等于已证明长任务中断后的可靠续跑。已提交 unit 不得因后续失败或 Ops 观测失败而回滚，未提交写入不能冒充完成。长范围执行仍按执行计划专题及模板 §0.3.5 核验，不在文档合并中新增恢复框架或改变现行行为。

在源端结果稳定、分页按约返回且无重试时，N 行的单日请求数为 `floor(N/10000)+1`，整页末尾还需空页确认结束；区间按各日求和。不能按“股票数 × 日期数”重复全市场请求，不能把一次短页或历史 18:30 空页当成永久就绪规则。

业务字段查询保持 Raw/view 一致，不代表所有物理属性透明：迁移改变 Serving 的 OID、relkind、物理约束/索引，且 `created_at` 不再保留原物理 Serving 的首次创建时间。依赖这些属性的仓库外 SQL/BI/脚本需另行核验，不能从代码内未发现消费者推断仓库外也没有。

## 5. 独立迁移与验证入口

| 数据集 | 已落地的独立迁移 | 原始父 revision |
| --- | --- | --- |
| 开盘 | [20260828_000156](/Users/congming/github/goldenshare/alembic/versions/20260828_000156_make_stk_auction_o_raw_view.py) | `20260828_000155` |
| 收盘 | [20260829_000158](/Users/congming/github/goldenshare/alembic/versions/20260829_000158_make_stk_auction_c_raw_view.py) | `20260829_000157` |

两份迁移独立校验列、主键/索引、owner/ACL/comments、未知依赖及 Raw SSD 表空间；Raw→Serving 加锁后按自然月对 9 个业务字段双向对账，每层每月 160,000 行为当时迁移容量上限，超限在 Serving DDL 前失败。这个数不是日常同步配额，不能因为两者相同就省略各自验证。

迁移在同一事务切换物理 Serving 为 view、恢复元数据，并分别创建 `trg_equity_auction_open_reject_dml` / `trg_equity_auction_close_reject_dml`，调用既有 `core_serving.reject_raw_direct_serving_view_dml()` 拒绝 `INSERT/UPDATE/DELETE`。历史真实验收记录为 SQLSTATE `55000`，不只是 writer 不写入的应用层约定；本轮没有重测生产 trigger。两份迁移均禁止自动 downgrade；不能为恢复旧双写而删除视图或重建业务表。

| 验证内容 | 当前入口 |
| --- | --- |
| Definition/plan、合法代码与非法 filters、模型、迁移顺序/容量/回滚保护、SQL 渲染、禁止 downgrade | [开盘专项测试](/Users/congming/github/goldenshare/tests/test_stk_auction_o_raw_view_m1.py)、[收盘专项测试](/Users/congming/github/goldenshare/tests/test_stk_auction_c_raw_view_m1.py) |
| Raw-only 写入与目标表 | [Raw/Serving view writer 测试](/Users/congming/github/goldenshare/tests/test_dataset_writer_raw_serving_views.py) |
| 日期展开、字段、分页与目录/工作流 | [resolver 测试](/Users/congming/github/goldenshare/tests/test_dataset_action_resolver.py)、[字段常量测试](/Users/congming/github/goldenshare/tests/test_fields_constants.py)、[source client 测试](/Users/congming/github/goldenshare/tests/test_dataset_source_client.py)、[action catalog 测试](/Users/congming/github/goldenshare/tests/test_ops_action_catalog.py) |

后续获准真实验收时，对账源端读取、归一化、拒绝/去重、Raw 写入与提交、Raw/view 对应日期的身份和 9 个字段，以及审计时间投影；不再要求“Serving 写入行数”。Raw upsert 的写入量不是新增行数，不能套用 immutable-fact 插入/匹配诊断。父 TaskRun 与目标 node 分开验收，其他节点失败不自动否定本节点。

## 6. 历史证据摘要（不是当前施工步骤）

### 初始源端核验：2026-05-16 文档记录

两份原文记载通过 MCP/SDK 验证：不传业务参数或只传代码、均加 `limit=5` 时返回 5 行；`trade_date=20260515,limit=10000` 开盘返回 5,488 行、收盘 5,515 行；`limit=3,offset=3` 各返回 3 行。`000001.SZ` 的 `20260514..20260515` 区间各返回 2 行。开盘 MCP 区间请求曾超时、同参数 SDK 成功；这些是历史可行性证据，不是本轮重新实测或固定服务时序承诺。

### Raw 直出 M0–M3a：2026-08-28 / 08-29

| 历史事项 | 开盘 | 收盘 |
| --- | --- | --- |
| 切换前两层各自行数 | 2,183,621 | 2,255,593 |
| 历史日期范围 | `2025-01-02..2026-08-27` | `2025-01-02..2026-08-28` |
| 全量等价 | 20 个自然月，9 字段双向差异均为 0 | 同样逐月独立验证，差异均为 0 |
| 月峰值 / 迁移上限 | 126,364 / 160,000 | 132,619 / 160,000 |
| 原 Serving catalog 大小 | 382,353,408 B | 390,266,880 B |
| 原 `created_at` 受投影影响行数 | 93,560 | 93,769 |
| 生产最小重跑 | TaskRun `9726`，目标 `2026-08-27`，读取/保存 `5,512/5,512` | TaskRun `10111`，目标 `2026-08-28`，读取/保存 `5,551/5,551` |

两者 M2 各自在一次性 PostgreSQL 18.4 验证了 160,000 行成功、160,001 行及字段/身份差异、外部依赖失败、DDL 后异常完整回滚、权限恢复、三类 DML 拒绝、Raw 写入后 view 即时可见及查询等价。原记录中临时实例已停止、数据目录已删除；不要求本轮重建测试环境。

生产 M3a 均保留 Raw OID 与主键/日期索引、SSD `pg_default` 及权限，Serving 成为 0 B view；旧 Serving catalog 大小是确定性毛释放依据，不以文件系统瞬时变化估算。两次最小重跑均无 reject/去重/重试，目标日刷新、全表行数未增加、Raw/view 9 字段一致，构成既有日期幂等刷新证据。

必须保留的不同点：

- **开盘存在发布流程偏差。** 标准部署在维护门禁之前自动应用 revision 156 并重启服务。发现时已是 Raw-only/view，记录中无开放任务、旧双写写 view 窗口或业务损坏证据；没有重复迁移，也没有补造迁移前门禁。随后正式暂停并恢复 schedule #2/#24，回收相关连接池，完成重跑与读回；该流程偏差不因结果通过而抹去。
- **开盘曾有性能阻塞。** M0 日期完整性 Raw/旧 Serving 为 `75.683/54.636 ms`（慢 38.5%），原因涉及可见页和 heap fetch。维护窗口普通 VACUUM 后 Raw 为 `50.751 ms`，相对 M0 留存 Serving 基线快约 7.1%；比较使用历史基线，不是假称补做同一时点迁移前测试。原 20% 门禁据此关闭，普通 VACUUM 不计为释放空间。
- **收盘未复制开盘的 VACUUM。** 实时 M3a 最大代表查询退化约 7.14%，在原 20% 门禁内；按维护窗口顺序暂停 schedule、停止 worker、使用当时的 maintenance-migration 模式切换、验收并恢复。不能把开盘补救步骤变成收盘或所有数据集的固定运维要求。

### 两次自然入口分别验收与结案

| 数据集 / 目标日 | 历史 18:30 schedule #24 | 历史 21:02 schedule #2 | 最终对账 |
| --- | --- | --- | --- |
| 开盘 / `2026-08-28` | TaskRun `9747`：空短页，读取/保存 `0/0` | TaskRun `9773`：短页，`5,508/5,508` | Raw/view 各 5,508 个唯一身份；9 字段及审计投影无差异，BJ/SH/SZ 分别 296/2,315/2,897 行 |
| 收盘 / `2026-08-31` | TaskRun `10343`、node `16058`：空短页，`0/0` | TaskRun `10371`、node `16129`：短页，`5,551/5,551` | Raw/view 各 5,551 个唯一身份、9 字段无差异，`fetched_at` 在后一次节点窗口内 |

两组目标节点均无 reject、去重、重试或截断。收盘后一次父任务因无关 `anns_d` 失败为 `partial_success`，目标节点自身成功；该独立故障未重新打开本数据集结案。

早空晚非空证明的是这些日期的源端就绪时序，不能冒充两次相同非空快照的幂等测试；幂等证据来自 M3a 已有日期重跑。开盘于 2026-08-29、收盘于 2026-08-31 分别完成 M0/M1/M2/M3a/M3b 并结案；本轮不重新开启阶段任务，也不宣称上述 schedule、生产 revision 或数据规模今天仍相同。

本轮只核对仓库代码、离线测试、本地源资料及上述历史记录，不访问源端或生产。原文全文可从 Git 提交 `8bc1fb44` 追溯；合并去向见[文档治理记录](/Users/congming/github/goldenshare/docs/governance/docs-information-architecture-v1.md#stk-auction-docs-consolidation-20260910)。
