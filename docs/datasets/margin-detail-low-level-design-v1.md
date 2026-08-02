# 融资融券交易明细（`margin_detail`）低层设计 LLD v1

状态：M0–M4 已完成；生产 HDD 落盘已完成并验收；M5a 待运营手工发起，M5b 仍待单独授权
最后更新：2026-08-03
数据集：`margin_detail`（融资融券交易明细）
源接口：`tushare.margin_detail`
源站事实：[0059_融资融券交易明细](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/两融及转融通/0059_融资融券交易明细.md)
同族时序参考：[融资融券交易汇总（`margin`）](/Users/congming/github/goldenshare/docs/datasets/margin-dataset-development.md)

---

## 1. 结论与硬约束

`margin_detail` 此前**未接入** Prod。仓库中只有 Tushare 源文档和历史接入盘点，没有 `DatasetDefinition`、请求构建、ORM/DAO、迁移、Ops action、调度、探测或测试实现。

本 LLD 固化以下已确认决策：

1. 数据只写一个 serving 表 `core_serving.equity_margin_detail`；不建 `raw_tushare.margin_detail`，不保存 `raw_payload`，以避免同一源数据双份存储。
2. 每一次正式请求和源站就绪探测都必须显式请求全部 11 个源字段；不能依赖 Tushare 默认字段集合。
3. 自动维护的最小业务单元为一个交易日；按 `limit/offset` 完整分页后才进入一次业务写入事务，不能把 6,000 行上限当成全量结果。
4. 源端发布时间与 `margin` 相同：交易日 `D` 的数据只能在下一个开市日 `N` 上午探测；就绪后正式任务仍维护 `D`。
5. `ts_code` 必须作为运营侧手工筛选条件，用于对单只证券做定点补录；它不能改变全市场日期完整性或推进 freshness。
6. serving 表的业务主键为 `(trade_date, ts_code)`；相同键以幂等 upsert 覆盖。
7. `margin_detail` 的发布探测、Probe condition、服务类、调度约束和测试必须独立于 `margin`，只复用通用 TaskRun / ProbeRunLog / 日期目标能力；不得复用或扩展 `MarginRemoteReadinessProbeService`。
8. Ops 中归入既有的“**A股行情**”目录；Definition 的领域显示名使用现有统一口径“**股票行情**”。不新增专用页面或 dataset-key 前端分支。
9. 直出 serving 不能让现有来源页显示伪造 raw 表或“—”：当 `raw_table=None` 时，来源页必须明确展示服务表 `core_serving.equity_margin_detail`。
10. 在历史数据首次写入前，全部物理叶分区（`p2010`–`p2027`、`pmax`）及其物理索引迁至 HDD tablespace `gs_raw_cold_hdd`；未来自动增量同样写 HDD。这是对“热数据留 SSD”默认原则的明确例外，接受相应读写延迟取舍。

本期不接入 Lake，不新增对外业务 API，不做派生指标，也不修改既有 `margin` 数据集。

## 2. 开发前审计与事实依据

### 2.1 已审计实现面

| 范围 | 已审计位置 | 结论 |
| --- | --- | --- |
| 数据集事实源 | `src/foundation/datasets/definitions/market_equity.py` | 已有 `margin`，没有 `margin_detail`。 |
| 请求与分页 | `src/foundation/ingestion/request_builders.py`、`source_client.py` | 通用 client 已支持 `offset_limit`，会把 `limit/offset` 追加到连接器请求；新数据集必须选用该策略。 |
| 执行计划 | `resolver.py`、`unit_planner.py` | 无对象池、无枚举扇出的按日数据集可走 generic planner：point 一天一个 unit，range 展开为逐日 unit。 |
| 写入契约 | `writer.py`、`datasets/models.py`、`definitions/_builder.py` | 当前 writer 和 storage 契约强制同时存在 raw/core DAO 及 `raw_table`，不能伪造 raw 层来实现直出，必须先支持正式的 direct-serving 写入路径。 |
| Ops 观测 | `dataset_definition_projection.py`、`freshness_query_service.py`、`dataset_card_query_service.py`、日期完整性审计 | freshness 和日期审计基于 `storage.target_table` 的 `trade_date`；direct-serving 数据集必须允许 `raw_table=None`。 |
| 发布时序 | `margin_remote_probe_service.py`、`operations_probe_runtime_service.py`、`DatasetReleaseTargetService` | `margin` 已有下一个开市日 09:00–09:30、每 5 分钟探测的通用时序基础；明细须有独立的三样本探测实现。 |
| 手工任务 | `ManualActionQueryService`、`DatasetActionResolver` | Ops 的筛选控件来自 `DatasetDefinition.input_model.filters`；可声明 `ts_code`，但必须在规划阶段执行全量口径保护。 |
| Ops 目录与前端 | `ops/catalog/dataset_catalog_views.py`、`ManualActionQueryService`、`frontend/src/pages/ops-v21-task-manual-tab.tsx` | catalog 驱动目录和排序；`margin_detail` 应置于 `equity_market` / “A股行情”，建议排序 `115`（位于 `margin=110` 与 `top_list=120` 之间）。当前手工页不会因筛选值自动限制 time mode，须补通用条件约束。 |
| 来源数据页 | `frontend/src/pages/ops-v21-source-page.tsx` | 当前非业务表卡片优先显示 `raw_table_label`；对直出数据集会显示“—”。必须改为通用 fallback：raw 不存在时显示带“服务表”前缀的 `target_table`。 |
| 直出静态校验 | `ingestion/linter.py`、`writer.py`、`dataset_definition_projection.py` | linter 尚未校验 write path 与 raw/core 字段的组合；writer 仍在分派前取 raw/core DAO；projection 的 `raw_table` 仍是非空类型。三个共享契约点必须一并改变。 |
| Probe 绑定与运行时 | `schedule_probe_binding_service.py`、`operations_probe_runtime_service.py` | 除 condition dispatch 外，尚有 schedule 模板、非 probe 拦截、目标日期解析、同日去重、action/label/error 映射和 runtime filters 兜底；必须全量接线。 |
| 源文档索引 | `docs/sources/tushare/docs_index.csv`、0059 源文档 | 本接口的本地源文档和索引已经存在；本期无需重复新增。若 M0 实测改变参数、字段或限额口径，必须同次修订源文档和索引。 |

CodeGraph 审计覆盖 DatasetDefinition 注册、resolver → unit planner → request builder → source client → writer 链路，以及 TaskRun、Probe、freshness、dataset card、日期完整性审计和相关测试消费者。影响面集中在 `foundation` 的数据集/ingestion/storage 契约与 `ops` 的独立探测接线；没有 `foundation -> ops|biz|app` 反向依赖。

### 2.2 源接口实测记录

实测日期为 2026-08-02；实测使用当前环境的 `tushareMcp`。若实现时源站行为变化，必须重新执行本节的三类字段验证和分页验收，并以当时实测校准本 LLD 与源文档。

| 验证项 | 实测结果 | 实现含义 |
| --- | --- | --- |
| 无业务参数 | 单次默认 MCP 请求返回正好 6,000 行，覆盖 `20260731`、`20260730` 两日 | 未分页的无日期请求不能作为全量同步依据；是否可完整翻页须另行实测。 |
| 单日 2026-07-30 | 4,418 行，SH 1,992、SZ 2,098、BJ 328；`(trade_date, ts_code)` 无重复 | 全市场单日可由单一按日 unit 获取；主键成立。 |
| 两日区间 2026-07-30 至 2026-07-31 | 单次默认 MCP 请求正好 6,000 行，其中 2026-07-30 仅 4,007 行、2026-07-31 1,993 行 | 未分页区间响应不完整；不能据此推断带 `limit/offset` 的区间分页也不完整，补充实测见下文。 |
| 非交易日 2026-08-01 | 0 行 | 空结果不能作为交易日数据已发布的成功证据。 |
| 默认字段 | 单只证券单日实际返回 10 列，缺少 `name` | 默认字段不完整，禁止省略 `fields`。 |
| 显式 11 字段 | 返回完整 11 列，含 `name=浦发银行` | 全链路固定使用显式字段列表。 |
| 2026-07-31 发布状态 | `600000.SH` 有行，`000001.SZ`、`920992.BJ` 无行 | 单市场可用不代表全市场已发布，必须三样本同时命中。 |
| 2026-07-30 发布状态 | 上述三个样本均有一行 | 三样本方案可识别完整发布。 |

`tushareMcp` 当前包装器不暴露 `limit` / `offset` 参数，因此不能用它完成第二页实测；这不是取消分页验证的理由。M0/M3 必须通过项目实际 Tushare connector 对同一已完整交易日发送真实分页请求，验收规则见第 6.3 节。

#### M0 项目真实 connector 分页证据（2026-08-02）

通过项目的 `DatasetSourceClient -> TushareSourceConnector -> TushareHttpClient` 对 `2026-07-30` 实测，所有请求均显式传入第 2.3 节的 11 个字段：

| 请求方式 | 请求数 | 返回行数 | 唯一 `(trade_date, ts_code)` | 结论 |
| --- | ---: | ---: | ---: | --- |
| 基准 `limit=6000, offset=0` | 1 | 4,418 | 4,418 | 未触及源端 6,000 行截断。 |
| 分页 `limit=1000, offset=0,1000,2000,3000,4000` | 5 | 4,418 | 4,418 | 最后一页为 short page；每行都有全部 11 字段。 |
| 两种结果的主键集合 | — | — | 完全相等 | 无漏键、重复键或额外键。 |

分页合并的市场分布为 SH 1,992、SZ 2,098、BJ 328。该结果与 MCP 单日实测一致，未发现需要修订本地源文档或索引的差异。

#### 区间分页补充验证（2026-08-03）

本验证只调用项目的 `TushareSourceConnector -> TushareHttpClient`，不创建数据库 session、TaskRun、normalizer 或 writer，也不写入本地或远程数据库。目的是核验“单次区间响应达到 6,000 行”究竟是单次响应限制，还是区间结果集上限。

所有请求显式传入固定 11 字段，页大小均为 `limit=1000`：

| 请求 | offset / 页大小 | 行数 | 唯一主键 | 结论 |
| --- | --- | ---: | ---: | --- |
| 区间 `start_date=20260730,end_date=20260731` | `0,1000,2000,3000,4000,5000,6000` / `1000,1000,1000,1000,1000,1000,411` | 6,411 | 6,411 | 在 offset 6,000 后仍有 411 行，所有行均含 11 字段，无重复键。 |
| 单日 `trade_date=20260730` | `0,1000,2000,3000,4000` / `1000,1000,1000,1000,418` | 4,418 | 4,418 | 与 M0 基线一致。 |
| 单日 `trade_date=20260731` | `0,1000` / `1000,993` | 1,993 | 1,993 | short page 正常结束。 |
| 区间主键集合与两单日并集 | — | 6,411 vs. 6,411 | 完全相等 | `missing=0`、`extra=0`。 |

因此，已修正此前“区间请求会静默截断”的错误表述：已证明的事实是**未分页的单次区间响应最多取到 6,000 行**；在上述超过 6,000 行的两日样本中，项目 connector 的 `limit/offset` 区间分页可继续取得数据，并与按日分页结果完全等价。该单一样本尚不证明任意年度区间的分页行为、峰值内存、重试/恢复语义或写入事务边界均适合改为区间 unit。

#### M3 隔离验证库最小真实同步证据（2026-08-03）

本次运行在全新本机 PostgreSQL 验证库 `goldenshare_margin_detail_m3_20260803` 中完成。迁移从空库完整执行至 `20260802_000123 (head)`；验证库只存在 direct-serving 表，没有 `raw_tushare.margin_detail`。目标表为 RANGE 分区父表，19 个分区，主键为 `(trade_date, ts_code)`。

真实运行由项目的 `DatasetMaintainService -> DatasetSourceClient -> TushareSourceConnector -> DatasetNormalizer -> DatasetWriter` 完整链路执行，输入为无筛选的 `point=2026-07-30`。每一页都显式请求本节固定的 11 字段，且不使用 MCP 包装器替代项目 connector。

| 环节 | 对账结果 |
| --- | --- |
| 源端分页 | 5 个请求，offset 为 `0,1000,2000,3000,4000`；每页为 `1000,1000,1000,1000,418` 行；共 4,418 行、4,418 个唯一 `(trade_date, ts_code)`，SH 1,992、SZ 2,098、BJ 328；无重试。 |
| 归一化 | 4,418 合格行，0 reject，`rejected_reason_counts={}`、样本为空。 |
| 写入 | `serving_direct_upsert` 写入 4,418 行，0 writer reject，reason counts / 样本均为空。 |
| 目标表 | 同日写前 0 行，写后 4,418 行、4,418 个唯一主键。所有 4,418 行的 11 个 source-field 键和值均与归一化结果逐键相等。 |

为使该空库验证可重复，M3 同时修正了三条历史迁移对已退役表的无条件 `ALTER TABLE` 假设：`20260421_000068`、`20260421_000069`、`20260423_000071` 现在只在对应历史表 / 列仍存在时执行类型修正。现存旧表仍保持原修正语义；clean baseline 不再因这些已不由迁移链创建的旧表失败。该修正经过针对性测试，并由本次完整迁移链验证。

#### M3 隔离验证库扩展写入验证（2026-08-03）

同一隔离库随后完成第 10.3 节第 5–7 项；所有请求仍使用项目实际 connector 和固定 11 字段，未改动生产数据或排程。

| 验证 | 实测结果 | 结论 |
| --- | --- | --- |
| 同日 full point 重跑 | 再次取得并 upsert 4,418 行，0 reject；目标仍为 4,418 个唯一键，日期桶、最小/最大日期和 11 个字段值均不变 | 幂等重跑不扩大或污染日期桶。 |
| 已有桶定点补录 | `2026-07-30 + 600000.SH` 仅请求 / 写入 1 行，0 reject；目标总行数、日期桶、最小/最大日期和其他键均不变 | 单证券补录只能修复已有 full-market 日期桶。 |
| 不存在桶定点补录 | `2026-07-29 + 600000.SH` 在请求源端前以 `scoped_repair_bucket_missing` 拒绝；源请求数 0，目标表快照不变 | 不会用单证券结果伪造全市场日期完整性。 |

### 2.3 源接口字段契约

固定的 `source_fields`，顺序也作为探测字段完整性断言的基准：

```text
trade_date, ts_code, name, rzye, rqye, rzmre, rqyl, rzche, rqchl, rqmcl, rzrqye
```

| 字段 | 类型 | 处理 | 说明 |
| --- | --- | --- | --- |
| `trade_date` | 日期 | 必填、归一化为 `date` | 观测日期、主键字段。 |
| `ts_code` | 字符串 | 必填 | 股票代码、主键字段、可选手工补录筛选。 |
| `name` | 字符串 | 可空，不参与主键 | 源文档说明 2019-09-10 后才有数据，历史行必须允许为空。 |
| `rzye`、`rqye`、`rzmre`、`rqyl`、`rzche`、`rqchl`、`rqmcl`、`rzrqye` | 数值 | 全部归一化为 `Decimal` | 不允许因未显式请求或空值而删列；空值按源事实保留。 |

字段缺失（键不存在）与字段值为空是不同错误：前者表示源字段契约未满足，应使 unit 失败；后者按字段可空性处理，`name` 的历史空值不得拒绝整行。

### 2.4 按 Prod 接入模板复核的门禁对账

本节是本轮复审新增项；它把模板要求落到具体消费者，避免只完成表、Definition 和任务入口。

#### 2.4.1 三层时间 / 执行 / 观测语义

| 层次 | `margin_detail` 的确定口径 | 禁止混淆 |
| --- | --- | --- |
| 时间输入 | 手工 full run 支持一个交易日或交易日区间；带 `ts_code` 时只允许一个交易日 | 源接口支持 `start_date/end_date` 不代表正式执行可传该区间。 |
| 执行 unit | 一个开市日一个 full-market unit；range 先按交易日历拆 unit，再逐 unit 分页 | 一个 TaskRun 的 range 不是一个源端范围请求。 |
| freshness / audit | `target_table=core_serving.equity_margin_detail` 按 `trade_date` 做 `date_bucket` 观测 | date-only 审计不证明每只标的都存在；因此单证券补录不能首次建立日期桶。 |

#### 2.4.2 字段端到端映射

所有 11 字段均由同一份 `source_fields` 显式请求；没有 raw 层是有意设计，不是映射遗漏。

| 源字段 | raw ORM / 迁移 | normalizer / serving ORM 字段 | serving 列 | 可空 | 关键约束 |
| --- | --- | --- | --- | --- | --- |
| `trade_date` | 不适用（直出） | `trade_date: date` | `trade_date` | 否 | 主键、unit 日期和 observed field 必须一致。 |
| `ts_code` | 不适用（直出） | `ts_code: str` | `ts_code` | 否 | 主键；仅作为单证券定点补录过滤。 |
| `name` | 不适用（直出） | `name: str | None` | `name` | 是 | 历史缺值保留为 null，字段键缺失则失败。 |
| `rzye` | 不适用（直出） | `rzye: Decimal | None` | `rzye NUMERIC(20,4)` | 是 | 融资余额。 |
| `rqye` | 不适用（直出） | `rqye: Decimal | None` | `rqye NUMERIC(20,4)` | 是 | 融券余额。 |
| `rzmre` | 不适用（直出） | `rzmre: Decimal | None` | `rzmre NUMERIC(20,4)` | 是 | 融资买入额。 |
| `rqyl` | 不适用（直出） | `rqyl: Decimal | None` | `rqyl NUMERIC(20,4)` | 是 | 融券余量。 |
| `rzche` | 不适用（直出） | `rzche: Decimal | None` | `rzche NUMERIC(20,4)` | 是 | 融资偿还额。 |
| `rqchl` | 不适用（直出） | `rqchl: Decimal | None` | `rqchl NUMERIC(20,4)` | 是 | 融券偿还量。 |
| `rqmcl` | 不适用（直出） | `rqmcl: Decimal | None` | `rqmcl NUMERIC(20,4)` | 是 | 融券卖出量。 |
| `rzrqye` | 不适用（直出） | `rzrqye: Decimal | None` | `rzrqye NUMERIC(20,4)` | 是 | 融资融券余额。 |

#### 2.4.3 消费者与兼容性矩阵

| 消费者 | `margin_detail` 应有行为 | 实施门禁 |
| --- | --- | --- |
| Definition registry / runtime registry | 自动从 Definition 生成 runtime entry；更新 architecture guard 的 `market_equity` key 集 | 不手写第二份运行时注册表，也不能遗漏 guard matrix。 |
| action catalog / catalog view | `margin_detail.maintain` 出现在“A股行情”，顺序 115 | `ManualActionQueryService` 和 cards 均经 catalog resolver 获取分组，不增加前端硬编码。 |
| Manual Action API / Web | API 下发“选中 `ts_code` 后仅 point”的通用条件规则；页面立即切到 point、隐藏 range，并显示补录提示 | 后端仍须拒绝绕过 UI 的 range / 多代码 / 未建日期桶请求。 |
| source page card | raw-backed 数据集维持 raw 表展示；direct-serving 显示 `服务表：<target_table>` | 不能以空 raw 表、占位字符串或 dataset-key 分支规避。 |
| Definition projection / card / snapshot / freshness | 接受 `raw_table=None`，只依 `target_table` 观测 | 所有 raw 访问均 null-safe；序列化不得把 `None` 转成虚假表名。 |
| writer / DAO | direct path 仅解析 core DAO；其他路径维持既有 raw/core 语义 | 新 path 和存储字段组合必须受 linter 严格校验。 |
| probe schedule / runtime | independent condition 只创建 `filters={}` 的 full-market task；被篡改的 filters 也在 runtime 清空或拒绝 | 不仅依赖创建 schedule 时的 API 校验。 |

#### 2.4.4 配置审计

本方案不增加环境变量、Settings 字段或新的可自由编辑开关。以下是唯一的运行配置事实源；实施不得复制成散落常量。

| 配置 / 事实 | 默认或固定值 | 持久化 / 来源 | 消费者 | 生效和门禁 |
| --- | --- | --- | --- | --- |
| `source_fields`、page limit、release policy | 11 字段、`1000`、`next_open_day_0930` | `DatasetDefinition` | request builder、source client、freshness | Definition 测试与真实 connector 分页对账。 |
| 明细 probe 样本和窗口口径 | SH/SZ/BJ 三样本；09:00–09:30、300 秒、每天 1 次 | 新的明细 probe 服务常量 / 校验函数 | probe service、schedule binding、runtime | schedule API 与 runtime 防篡改测试；不得引用 `margin` 常量。 |
| 生产 probe 排程记录 | target=`margin_detail.maintain`、condition=`remote_margin_detail_ready`、filters=`{}` | `ops.schedule` / `ops.probe_rule`，由部署后的运营操作创建 | scheduler、ProbeRuntime | 代码上线和最小真实同步验收通过后，按既有 Ops API 创建；不通过迁移自动 seed，不复制 `margin` 的 schedule id。 |

## 3. 目标架构与职责边界

```mermaid
flowchart LR
  A["交易日历和当前时间"] --> B["DatasetReleaseTargetService\n计算目标交易日 D"]
  B --> C["MarginDetailRemoteReadinessProbeService\n三个代码均验证 D"]
  C -->|"全部命中"| D["TaskRun\nmargin_detail.maintain, point=D, filters={}"]
  C -->|"未全量发布或源端异常"| E["ProbeRunLog\n不写业务数据"]
  D --> F["DatasetActionResolver / generic planner\n一天一个 unit"]
  F --> G["_margin_detail_params\ntrade_date + 可选 ts_code"]
  G --> H["DatasetSourceClient\nfields=全部 11 字段\nlimit/offset 分页"]
  H --> I["DatasetNormalizer"]
  I --> J["DatasetWriter\nserving_direct_upsert"]
  J --> K["core_serving.equity_margin_detail"]
  K --> L["freshness / 日期完整性 / Dataset Card"]
```

| 层级 | 负责内容 | 明确不负责 |
| --- | --- | --- |
| `DatasetDefinition.source` | API、全字段 source contract、请求 builder key、发布策略 | 直接拼装 Ops 输入或决定 probe 窗口。 |
| release target service | 由交易日历和当前时钟得到待探测 `D` | 请求 Tushare、写数据或判定某一证券可用。 |
| 明细独立 probe | 对固定三代码验证 `D` 已全市场发布；创建无筛选的 TaskRun | 写 serving 表、复用汇总 probe、把单个样本当全量。 |
| resolver / planner | 归一化 point/range、逐日构造 unit、执行业务筛选保护 | 推断源站发布时间。 |
| request builder | 只把已验证 plan unit 转成 `trade_date`、可选 `ts_code` | 接受任意源接口参数或分页参数。 |
| source client | 固定 `fields`、统一分页和结果累积 | 选择业务日期或绕过 pagination。 |
| writer | 一个事务把一个完整 unit 幂等写入 serving 表 | 创建 raw 镜像、写 Ops 状态。 |
| Ops freshness / audit | 从 serving target 观察全量日期桶 | 将单证券补录误记为全市场数据完成。 |

Ops / TaskRun / ProbeRunLog / snapshot 状态写入必须与 serving 业务写入事务隔离；任何状态写入失败都不得回滚或污染 `core_serving.equity_margin_detail`。

## 4. DatasetDefinition 与执行计划

### 4.1 Definition 位置和数据契约

修改 `src/foundation/datasets/definitions/market_equity.py`，新增 `margin_detail` 行。应采用以下语义（代码字段以实施时现有 dataclass 为准）：

| 分类 | 固定值 |
| --- | --- |
| identity | `dataset_key=margin_detail`；显示名“融资融券交易明细” |
| domain | `equity_market` / “股票行情” |
| source | `tushare`、adapter `tushare`、API `margin_detail`、doc id `tushare.margin_detail` |
| source fields | 第 2.3 节列出的全部 11 个字段，不能缩减 |
| request builder | `_margin_detail_params` |
| release policy | `next_open_day_0930` |
| date model | `trade_open_day`、`every_open_day`、`point_or_range`、时间输入为 `trade_date_or_start_end`、观测字段 `trade_date` |
| completeness | `date_bucket`（日期级）；不做“当日全部股票”的静态对象矩阵审计，因为可融资融券证券集合不是静态全量股票池 |
| input filters | 一个可选字符串 `ts_code`，显示为“股票代码（精确补录）”；单值，格式仅允许 `6 位数字.(SH|SZ|BJ)`，并声明 field-level scoped repair policy |
| planning | `universe_policy=no_pool`、无 enum fanout、`pagination_policy=offset_limit`、`page_limit=1000`、`chunk_size=None`、`max_units_per_execution=None`、`unit_builder_key=generic`、`fetch_concurrency=1` |
| normalization | `trade_date` 为 date；8 个数值字段为 Decimal；`trade_date`、`ts_code` 为 required fields |
| capabilities | `maintain` 支持 point/range、手动/调度/重试；自动任务只允许无 `ts_code` |
| observability | `continuous_open_day`、`audit_applicable=true`、观测 `trade_date` |
| transaction | 一个 unit 一个事务，`idempotent_write_required=true`；`write_volume_assessment` 固定说明“按单交易日完整分页后一次 upsert；基准日 4,418 行、每页 1,000 行，M0/M3 必须记录单日最大行数和事务耗时，超出可接受量级先停下评估，不以宽区间截断替代”。 |

新建 `_margin_detail_params()` 于 `src/foundation/ingestion/request_builders.py`：

```text
必传：trade_date=YYYYMMDD
可选：ts_code=<单个精确证券代码>
不得传入：start_date、end_date、limit、offset、任意 exchange 参数
```

区间当前并不映射为源接口 `start_date/end_date`。range 由 planner 展开为多个交易日，每个 unit 都只提交一个 `trade_date`；这是为了保持按日的内存、事务、重跑与日期完整性边界，不是因为源接口的区间 `limit/offset` 分页已被证明不可用。第 2.2 节的补充验证证明两日区间可分页超过 6,000 行；若要改为区间 source unit，仍须先完成第 6.4 节列出的独立设计和验证。

同步修改 `src/ops/catalog/dataset_catalog_views.py`：新增 `DatasetCatalogItem("margin_detail", "equity_market", 115)`。这是唯一的 Ops 展示分类来源：手工任务中心、数据集卡片和数据集详情均会经 catalog resolver 呈现为“A股行情”；Definition 的“股票行情”则用于 freshness / 数据域展示，两个标签各自沿用现有用途，不能互相替代。

### 4.2 `ts_code` 定点补录与全量口径保护

`ts_code` 暴露的目的，是在已知某天某只证券缺失或字段错误时让运营重拉该键。若没有保护，单证券结果会在当前 date-only freshness 与 `DISTINCT trade_date` 审计中表现为该日期存在，从而把一个尚未完成的全市场日期误报为已就绪。

采用以下规则：

| 请求 | 是否允许 | 结果 |
| --- | --- | --- |
| 无 `ts_code` 的 point `D` | 是 | 全市场单日维护；可建立新日期桶并正常参与 freshness/audit。 |
| 无 `ts_code` 的 range | 是 | 按开市日逐日执行；每个 unit 均是全市场日期桶。 |
| 有 `ts_code` 的 point `D`，且 serving 表已存在 `D` | 是 | 精确 upsert 一个既有物理日期桶中的一条记录；不新建日期桶，也不改变其 freshness/audit 语义。 |
| 有 `ts_code` 的 point `D`，但 serving 表不存在 `D` | 否 | 拒绝，防止部分证券创建“假全量”日期桶。 |
| 有 `ts_code` 的 range | 否 | 拒绝；补录一次只能针对一个明确日期和一个明确证券。 |
| 自动 probe 创建的 TaskRun | 只允许 `filters={}` | 任何带 `ts_code` 的自动任务配置都必须被拒绝。 |

为避免在 `margin_detail` 上写 dataset-key 分支，新增 filter-level declarative policy；它必须放在 `DatasetInputField`，而不是放在整个 `DatasetInputModel`，以明确是哪个筛选项触发时间限制：

```text
DatasetInputField.scoped_repair_policy: str | None = None
  - None（默认，现有数据集行为不变）
  - existing_point_bucket_only（仅 margin_detail.ts_code 使用）
```

`DatasetDefinition` builder 读取此字段；`DatasetUnitPlanner` 在已解析 date model、但尚未创建 source 请求前执行通用 preflight：

1. 当 filters 中没有带该 declaration 的值时，跳过。
2. 当 policy 为 `existing_point_bucket_only` 时，只接受 point + 一个非空字符串；拒绝逗号、数组、通配符和不匹配 `^\\d{6}\\.(SH|SZ|BJ)$` 的代码。
3. 使用 `definition.storage.target_table` 对应的 ORM，查询 `trade_date=D` 是否已有至少一条记录，即该物理日期桶已经存在。
4. 不存在时以结构化错误拒绝；错误码固定为 `scoped_repair_code_invalid`、`scoped_repair_point_required` 与 `scoped_repair_bucket_missing`，并同步更新 ingestion error codebook。

Manual Action API 不暴露内部 policy 名称。新增通用 `conditional_time_rules` 响应字段（`filter_key`、非空时允许的 `time_modes`、`help_text`），由 `ManualActionQueryService` 从 field policy 导出。`margin_detail.ts_code` 的规则只允许 `point`，提示“股票代码补录仅支持一个已存在日期桶”。前端 `ops-v21-task-manual-tab` 在输入 `ts_code` 后必须：自动将 draft 切为 point、禁止/隐藏 range、保留单日交易日控件并展示提示；清空 `ts_code` 后再恢复 Definition 声明的 point/range 选项。后端 preflight 是最终裁决，不能依赖前端。

该策略只解决“补录不能创建新日期桶”，不替代数据质量审计。若将来需要核验每个日期所有可融资融券证券都齐全，应另行设计源端/权威证券范围驱动的矩阵完整性事实，不能把当前 `ts_code` 单点输入误用为完整性来源。

## 5. Direct-serving 存储与写入契约

### 5.1 为什么必须改通用契约

当前 `DatasetStorageDefinition` 的 `raw_dao_name`、`raw_table` 是必填；`build_definition()` 强制检查 `raw_table`；`DatasetWriter.write()` 进入任何 write path 前同时解析 raw/core DAO。`raw_only_upsert` 也无法表达“没有 raw 表”。

因此不能为满足旧接口而创建空 raw 表、影子 DAO 或双写。这些都会违背本期“节省存储、serving 直出”的决策。实施必须先把 direct serving 设计为一等写入模式，且保持现有 raw 相关模式的行为不变。

### 5.2 Storage 契约变更

修改 `src/foundation/datasets/models.py`、`definitions/_builder.py` 和 `ingestion/linter.py`：

| 字段 | 新语义 |
| --- | --- |
| `raw_dao_name` | `str | None`；仅 raw 参与的 write path 必填。 |
| `raw_table` | `str | None`；direct-serving 为 `None`。 |
| `core_dao_name` | 继续必填；direct-serving 指向 `equity_margin_detail`。 |
| `serving_table` | direct-serving 必填，等于 `core_serving.equity_margin_detail`。 |
| `target_table` | 等于 serving 表，作为 freshness/audit 观测表。 |
| `write_path` | 新增且仅新增 `serving_direct_upsert`。 |

新的 lint 规则必须使非法 Definition 在启动前失败：

| `write_path` | 必须满足 | 必须拒绝 |
| --- | --- | --- |
| `serving_direct_upsert` | `raw_dao_name=None`、`raw_table=None`、非空 `core_dao_name` / `serving_table` / `target_table`、`target_table=serving_table`、非空 `conflict_columns` | 任意 raw 配置、没有 serving/core target、target 与 serving 不同。 |
| 既有 raw 路径 | 维持各自现有 raw/core 要求 | 因 raw 字段改为 Optional 而静默放过缺失 raw DAO 或 raw table。 |

`margin_detail` 的 storage 固定为：

```text
raw_dao_name=None
raw_table=None
core_dao_name="equity_margin_detail"
target_table="core_serving.equity_margin_detail"
serving_table="core_serving.equity_margin_detail"
std_table=None
delivery_mode="single_source_serving"
layer_plan="source->serving"
write_path="serving_direct_upsert"
conflict_columns=("trade_date", "ts_code")
```

`DatasetWriter` 必须先按 `write_path` 选择所需 DAO，再做存在性校验：

- `serving_direct_upsert` 只解析 `core_dao_name`，禁止访问 raw DAO，也禁止调用 raw 写入函数；
- 既有 write path 仍按其原有 raw/core 必要性校验；
- 空 batch 返回 0 写入，不建立“源端已发布”语义；发布语义只由 probe 决定；
- 非空 batch 在一个事务中执行 serving DAO 的 bulk upsert，冲突键为 `(trade_date, ts_code)`；
- 直出路径的 `WriteResult.target_table` 为 serving 表，拒绝诊断和幂等统计保持可观测。

`single_source_serving` 复用现有单源服务展示语义，不新增一个只为“直出”命名的 delivery mode。`layer_plan=source->serving` 需要在层级展示映射中补充 `source` 为“源端”，使页面准确表达“源端直出服务层”。`DatasetFreshnessProjection.raw_table`、dataset card、freshness snapshot 序列化和相关 schema 必须接受 `raw_table=None`：不得拼接、查询或显示虚假的 raw 表名。

来源数据页的可见语义另行固定：`frontend/src/pages/ops-v21-source-page.tsx` 对 `raw_table_label is None` 的源数据卡片显示 `服务表：${target_table}`；若 target 也不存在才显示“—”。这是一条面对所有 direct-serving 数据集的通用规则，raw-backed 卡片继续显示 raw 表。`target_table` 已在 card API 返回，故不新增接口，也不为 `margin_detail` 写专用前端判断。

### 5.3 数据库、ORM 与 DAO

新增 Alembic 迁移：`alembic/versions/<next_revision>_add_margin_detail_dataset.py`。实施前必须执行 `alembic heads`，`down_revision` 只能连接当时真实 head。

```sql
CREATE SCHEMA IF NOT EXISTS core_serving;

CREATE TABLE core_serving.equity_margin_detail (
    trade_date DATE NOT NULL,
    ts_code VARCHAR(16) NOT NULL,
    name VARCHAR(64),
    rzye NUMERIC(20, 4),
    rqye NUMERIC(20, 4),
    rzmre NUMERIC(20, 4),
    rqyl NUMERIC(20, 4),
    rzche NUMERIC(20, 4),
    rqchl NUMERIC(20, 4),
    rqmcl NUMERIC(20, 4),
    rzrqye NUMERIC(20, 4),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_equity_margin_detail PRIMARY KEY (trade_date, ts_code)
) PARTITION BY RANGE (trade_date);

-- 实际迁移为 2010 至当前年份加未来一年逐年创建同构分区。
CREATE TABLE core_serving.equity_margin_detail_2026
    PARTITION OF core_serving.equity_margin_detail
    FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');

CREATE INDEX idx_equity_margin_detail_trade_date
    ON core_serving.equity_margin_detail (trade_date);
CREATE INDEX idx_equity_margin_detail_ts_code_trade_date
    ON core_serving.equity_margin_detail (ts_code, trade_date DESC);
```

选择 `NUMERIC(20,4)` 与已接入的融资融券汇总金额/数量类型保持一致，并避免浮点二进制误差。表中不增加 `api_name`、`fetched_at`、`raw_payload` 或 raw 表；来源、任务参数、开始/结束时间、失败原因保留在既有 TaskRun / ProbeRunLog 观测链路。

新增 ORM：`src/foundation/models/core/equity_margin_detail.py`，类 `EquityMarginDetail`。确保模型模块可被现有 table model registry 自动发现，并注册 `DAOFactory`：

```text
equity_margin_detail -> GenericDAO(session, EquityMarginDetail)
```

迁移只新增此表和索引；不得删除、清空、重建任何既有业务表。降级仅在明确执行 Alembic downgrade 时删除本表和其索引。

### 5.4 分区与历史容量

`trade_date` 是绝大多数按日查询、freshness、补录和回补范围条件，故使用年度 RANGE 分区。迁移创建 2010 年至当前年份加未来一年分区，并在年度维护流程中提前创建下一年分区；不在首次上线时对存量业务表做重写。

以已实测 2026-07-30 的 4,418 行估算，250 个开市日约 110 万行/年。直出模式只保存一个 serving 副本；若改为 raw + serving 双写，行存储会至少翻倍且增加写入放大，故不采用。

### 5.5 生产 HDD 落盘决策（2026-08-03）

生产 catalog 已确认 Alembic revision `20260802_000123` 已应用：父表 `core_serving.equity_margin_detail` 是空的 partitioned relation，全部叶分区统计行数为 0、当前总大小仅约 456 KB。叶分区 `p2010`–`p2027` 与 `pmax` 共 19 个，及其 57 个物理索引当前均在 `pg_default`；HDD tablespace `gs_raw_cold_hdd` 位于 `/data/disk/postgresql/tablespaces/gs_stk_mins_hdd`，当时机械盘可用约 324 GB。

2026-08-03 已在同一空表、无任务、无外部锁的维护窗口完成迁移：父表默认 tablespace、3 个父级 partitioned index、19 个叶分区和 57 个物理索引均设为 `gs_raw_cold_hdd`；每个 DDL 后均立即校验。独立连接复验结果为叶分区 `19/19`、物理索引 `57/57` 均在目标 tablespace，业务行数仍为 0。父表和 3 个 partitioned index 是逻辑对象、没有承接业务数据块，不能以其 tablespace 取代叶分区/物理索引的迁移验收。此操作不改表名、主键、ORM、DAO、请求语义或 TaskRun 语义，也不迁移或复制业务行。

执行前已在同一维护窗口重新确认：目标为空、HDD tablespace/空间可用、没有 `margin_detail` 的 queued/running/canceling TaskRun、没有长事务或外部锁，且叶分区/物理索引白名单为 `19/57`。每条 `ALTER TABLE ... SET TABLESPACE` 或 `ALTER INDEX ... SET TABLESPACE` 均带 `lock_timeout='15s'` 单独执行并立即复验，未发生超时或失败。由于关系为空，执行前后文件系统可用空间未出现有意义变化。若后续性能不可接受，只能在重新确认 SSD 容量后逐对象反向迁回 `pg_default`。

## 6. 请求、分页、事务与回补

### 6.1 正式单元与请求

| 项目 | 规则 |
| --- | --- |
| full run point | 一个 `trade_date` 一个 unit、一个全市场请求序列。 |
| full run range | 由 generic planner 展开为多个开市日 unit；不得用一个源端区间请求。 |
| scoped repair | 一个 `trade_date` + 一个 `ts_code` 一个 unit。 |
| source fields | 每页都使用 11 字段的显式 `fields` 字符串。 |
| 分页 | `limit=1000`，`offset=0,1000,2000,...`；最后一个返回数少于 1000 的页面终止。 |
| 并发 | `fetch_concurrency=1`，避免偏移翻页时并发造成限流或重排不确定性。 |
| 事务 | 某日的全部页累积、字段归一化和主键冲突诊断后，才在一个事务中 upsert。 |
| 进度上下文 | full run 的 generic unit 为 `margin_detail:YYYY-MM-DD:0`；scoped repair 不改变该日期 unit 身份，但 TaskRun / progress context 必须保留唯一 `ts_code`，用于审计该次补录范围。 |

选择 1,000 而非源端最大 6,000：当前完整单日 4,418 行会强制走至少五页，能让运行主线持续覆盖真实分页；同时单日最多约五次数据请求，资源可控。不得为减少请求数把 page limit 提升到会让日常路径长期只走单页、从而失去分页回归覆盖。

### 6.2 完整分页的硬校验

source client 已有“短页停止”机制；但当前通用 DAO upsert 对重复键可能采取最后一行覆盖，因此本数据集必须在 DAO 前的 unit 质量阶段增加以下数据保护：

1. 所有返回行的 `trade_date` 必须等于该 unit 的 `trade_date`；否则拒绝该 unit。
2. full run 中不接受空批次作为成功的发布日期依据；只有独立 probe 可创建正式自动任务。
3. 合并后的行必须按 `(trade_date, ts_code)` 去重。若同键两行内容不一致，拒绝该 unit，不允许静默最后一行覆盖。
4. 当前自动维护的发布完整性由第 7 节独立 probe 的 SH/SZ/BJ 三样本承担；writer 不把“三市场后缀齐全”写死为历史回补门禁，因为北交所成立前的历史日期不具备同一市场结构。
5. 所有拒绝必须通过既有结构化错误和 TaskRun 记录 reason code、数量与不超过既有上限的样本；不得把大批 reject 记为成功。

M2 已通过 `DatasetQualityPolicy` 的声明式 `unit_date_field=trade_date` 与 `duplicate_key_policy=dedupe_identical_reject_conflicting` 落地第 1、3、5 条：日期漂移以结构化错误阻断 unit；完全相同行在写入前去重并记录 reason；相同主键但字段不同则以结构化错误阻断 unit。该策略由 linter 校验日期字段、冲突键和 required fields 的对应关系，不写 dataset-key 分支。

分页完整性由偏移页等价对账和第 6.3 节真实验收保证；三市场 probe 只解决当前自动维护的“何时可请求”问题。后续若获得逐日的官方可融资融券证券清单，才可设计并接入矩阵完整性审计。

### 6.3 真实分页验收

在实现前的 M0 和实现后的 M3，使用项目实际 connector 对一个确认完整日（基线为 `2026-07-30`，若源端窗口已不可用则选择最近同等完整日）执行：

| 请求 | 必须记录的证据 |
| --- | --- |
| 基准请求 | `trade_date=D, fields=<全部 11 字段>, limit=6000, offset=0` 的行数与唯一键数。 |
| 第 1–N 页 | `limit=1000, offset=0,1000,...` 的每页行数、最后一个 short page 的 offset。 |
| 合并结果 | 页合并行数、唯一 `(trade_date,ts_code)` 数、SH/SZ/BJ 各自数量。 |
| 等价结论 | 分页合并的 unique key 集合必须与基准请求完全相等；任何漏键、重复键或额外键都阻断上线。 |

本节仍以单日为验收基准，因为它验证的是当前按日 unit 的正式实现。未分页的两日 range 或无日期响应不能作为全量基准；第 2.2 节补充验证已证明两日 range 在显式 `limit/offset` 分页时可以超过 6,000 行，但这不改变当前运行时的 unit 契约。

### 6.4 回补范围、年度 TaskRun 与源端请求边界

历史回补从 2010 年开始，以“一个自然年一个 TaskRun 批次、内部逐交易日 unit”推进。年度 TaskRun 可以、也应当以运营侧时间窗口配置，例如 `time_input={mode: range, start_date: 2020-01-01, end_date: 2020-12-31}`，并保持 `filters={}`。

这两个日期只表达 TaskRun 的计划范围：当前 `DatasetActionResolver -> generic planner` 依据交易日历将其展开为逐开市日 unit，`_margin_detail_params()` 也只会为每个 unit 生成 `trade_date=YYYYMMDD`。这是当前正式实现的执行契约，而不是对源接口不支持区间分页的判断。源文档允许 `start_date/end_date`；2026-08-03 的项目 connector 实测已证明两日区间可经 `limit/offset` 取得超过 6,000 行的完整主键集合。2010 全年 MCP 单次默认请求的 6,000 行和 68 个交易日，仅证明未分页年度响应不完整。

当前仍保持按日 source unit，原因是完整性与资源边界：`DatasetSourceClient` 会先把一个 unit 的所有页累积在内存中，之后才进入归一化和单次 unit 写入。若把整年直接设计为一个区间 unit，按当前初估会在一个 unit 内累积约 671 万行、约 8,009 页，并将失败重跑、拒绝原因、事务粒度和日期 completeness 全部放大到年度级。要改为区间 source unit，必须另行设计有界区间切分、页/日期级 checkpoint、内存上限、跨日期质量对账和写入事务边界；不能仅因两日分页验证通过就改动正式执行模型。

禁止一次提交 2010 年至今的无界历史任务。每个年度批次必须在开始前完成第 6.5 节只读预估；若实测源端限流或耗时不可接受，必须暂停并报告测得量级，等待明确的节流决策。不得把未分页的宽区间响应当作完整数据；若未来选择区间 unit，则必须先完成上一段所列的独立设计与全量对账验证。

### 6.5 M5a 前的只读规模、存储和配额预估（2026-08-03）

本次只读预估使用 `tushareMcp` 和隔离验证库，不创建 TaskRun、不写生产数据。SSE 交易日历显示 2010–2025 共 3,886 个开市日（每年 238–245 日）。对每年最后一个开市日显式请求固定 11 字段，结果如下；`页数`按正式 `page_limit=1000` 和“short page 停止”规则估算。

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

若把每年的单一样本当作全年日均值，2010–2025 的初步规模为约 671 万行、约 8,009 次源请求。隔离验证库中 4,418 行的 2026 分区实际占用 1,810,432 B（约 410 B/行，含索引；元组本身平均 123 B）；按同一比例外推，16 年 serving 表约 2.56 GiB。以上均为**规划初值，不是容量上限或配额承诺**：年度末样本不能代表年内峰值，生产索引膨胀、并发和源站返回分布也会改变结果。

源文档只声明该接口需要 2,000 积分权限，没有提供每分钟、每日或按调用计费的公开额度；因此当前只能估计请求量，不能推断账户配额或完成耗时。M5a 执行前，每个年度须额外以首个、中位和最后一个开市日做三点只读样本，记录行数、页数、响应耗时、重试和限流；运营根据配置账户的实际限额确认节流后，才创建该年度 TaskRun。

每个实际年度批次完成时，沿用既有 TaskRun 和日期完整性审计完成运营验收：记录 TaskRun ID、时间窗口、终态、`unit_done/unit_total`、累计 `rows_fetched/rows_saved/rows_rejected`、reject reason，以及目标表的日期覆盖和实际行数。M3 已完成模板要求的最小真实同步全链路对账；M5a 不新增逐页持久化账本、原始数据镜像或新的运行时功能。若 TaskRun 失败或出现未解释的 reject，当前批次不得验收，应依据既有错误详情定位并重跑相关日期或批次。

## 7. 源端发布时间与独立 readiness probe

### 7.1 时间语义

与 `margin` 相同，但实现独立：

| 时间 | 行为 |
| --- | --- |
| 交易日 `D` 当天及当晚 | 不请求 `D` 的明细作为自动维护；源端尚未达到完整发布口径。 |
| 下一个开市日 `N` 09:00–09:30（Asia/Shanghai） | 每 5 分钟对 `D` 探测一次。 |
| 三样本均通过 | 创建一次 `margin_detail.maintain`，`time_input={mode: point, trade_date: D}`、`filters={}`。 |
| 任一样本未返回、字段缺失、日期/代码不一致或源端异常 | 仅写 ProbeRunLog；不建 TaskRun、不写 serving 表。 |
| `N` 09:30 后仍未就绪 | freshness 可以按 `next_open_day_0930` 显示 stale；不得伪造成功或创建空任务。 |

`DatasetDefinition.source.release_policy` 固定为 `next_open_day_0930`。`DatasetReleaseTargetService` 根据交易日历计算 `D` 与 `N`，不允许 cron 自行写“昨天”或自然日回退逻辑。

### 7.2 独立 probe 的实现

新增 `src/ops/services/margin_detail_remote_probe_service.py`，核心常量与 `margin` 完全分离：

```text
MARGIN_DETAIL_DATASET_KEY = "margin_detail"
MARGIN_DETAIL_ACTION_KEY = "margin_detail.maintain"
MARGIN_DETAIL_REMOTE_READY_CONDITION = "remote_margin_detail_ready"
```

固定样本如下；它们只用于发布就绪证明，不参与正式全量任务的请求范围：

| 市场 | 固定 `ts_code` |
| --- | --- |
| SSE | `600000.SH` |
| SZSE | `000001.SZ` |
| BSE | `920992.BJ` |

每次 probe 对每个样本构造一个 `point=D + ts_code` 的读请求，并且从 `margin_detail` Definition 取得同一份显式 11 字段 source contract。每个样本必须同时满足：

1. 返回至少一行，且存在精确的 `(trade_date=D, ts_code=<sample>)`；
2. 该行具有所有 11 个字段键；`name` 值可空，但字段键不得省略；
3. 不接受只返回其他日期或其他证券的行；
4. 三个样本均通过才得到 ready。

在 `operations_probe_runtime_service.py` 注册此服务和独立 condition dispatch；在 Ops schedule API 的 condition 白名单/校验中新增 `remote_margin_detail_ready`。它的配置限制固定为：

```text
dataset_action = margin_detail.maintain
window_start = 09:00
window_end = 09:30
probe_interval_seconds = 300
max_triggers_per_day = 1
params_json.time_input = {"mode": "point"}
params_json.filters = {}
```

禁止 workflow、`schedule_probe_fallback`、固定日期、日期策略、`ts_code` 或任何其他维护筛选。最多 7 轮 × 3 个样本，即一个交易日最多 21 次 probe 源请求；正式维护触发后不再为同一 `D` 重复创建 TaskRun。

以下接线均为必做项，缺任一项都不算接入完成：

| 位置 | 必须新增 / 修改的行为 |
| --- | --- |
| `schedule_probe_binding_service.py` | import 并加入 `REMOTE_SOURCE_PROBE_CONDITIONS`；在 `_build_templates` 调用独立 `_validate_remote_margin_detail_schedule`；`_validate_freshness_latest_open_dataset` 明确拒绝该数据集走 generic freshness condition；为本 condition 的 `on_success_action_json.request.filters` 固定 `{}`；非 probe 排程也须用 `_validate_remote_margin_detail_non_probe_schedule` 拦截。 |
| 明细 schedule validator | 仅 `trigger_mode=probe`、仅 `dataset_action=margin_detail.maintain`、无 `calendar_policy`、无 fixed time input、`filters={}`、固定 window/interval/max-trigger；拒绝 workflow、fallback、任何 source/filter/日期策略变体。 |
| `operations_probe_runtime_service.py` | 构造 `MarginDetailRemoteReadinessProbeService`，加入 evaluate dispatch、`_remote_source_probe_action_key`、label、binding error、`_parse_probe_target_trade_date`（读取 `target_trade_date`）和 `_has_effective_target_task` 的 condition/resource map。 |
| runtime 最后一层保护 | `_enqueue_on_match` 对该 condition 再验证 action key，并强制 TaskRun 的 `filters={}`；即使历史 DB 行或直接写库绕过 schedule API，也不能把 `ts_code` 传给自动 full-market 任务。 |
| 去重 | 同一 schedule、同一 `D` 已有 queued/running/canceling/success/partial_success 的 `margin_detail.maintain` probe TaskRun 时不得再创建；failed 任务可按现有重试口径重新触发。 |

生产启用并不通过 Alembic 自动生成 schedule：部署代码、迁移和最小真实同步验收完成后，才由运营在既有 Ops 排程接口创建独立 `ops.schedule`，并由 binding service 派生 `ops.probe_rule`。创建前须读取当前 `margin` 的持久化排程作为控制面参考，但不能复用其 id、不能复制其 target 或通过代码 seed；本节的 condition、filters 和窗口才是 `margin_detail` 的唯一硬约束。

#### M4 实施与验证记录（2026-08-03）

已新增独立的 `MarginDetailRemoteReadinessProbeService`，只复用 `DatasetReleaseTargetService` 和通用 TaskRun / ProbeRunLog 机制；它不调用 `MarginRemoteReadinessProbeService`，也不走会拒绝未建日期桶补录的 scoped-repair resolver。探测直接构造只读的 `trade_date + ts_code` 源请求，因而可在首次全市场写入前验证三样本发布状态。

`operations_probe_runtime_service.py` 同时作为最后一道防线：即使持久化规则被绕过 API 篡改为带 `ts_code` 或 range 日期，命中后仍只会创建 `point=D`、`filters={}` 的 full-market TaskRun。schedule binding 层拒绝 workflow、fallback、generic freshness、calendar policy、固定日期、筛选条件和错误窗口 / 间隔 / 最大触发数。

`tests/web/test_margin_detail_remote_probe.py` 已通过 23 项验证，覆盖三样本及完整字段、日期/代码精确性、字段键缺失、周末和国庆长假后的 `D -> N`、miss/error、runtime 清洗、同日有效任务去重、failed 重试、schedule API 和 direct validator 的全部固定约束。M4 未创建任何生产 `ops.schedule` 或 `ops.probe_rule`。

## 8. Ops、freshness 与完整性语义

### 8.1 手工入口

Ops catalog/手工 action 在 `equity_market` / “A股行情”组显示 `margin_detail`，位于 `margin` 与 `top_list` 之间，支持：

- 无筛选的单日维护与日期区间维护；
- `ts_code` 的单日精确补录，入口文案明确为“只可补录已存在日期桶”。

分页参数、`fields`、`exchange`、源端 `start_date/end_date` 不属于 Ops 输入，也不得出现在手工表单、API contract 或 TaskRun filters 中。

### 8.2 自动任务与排程

`schedule_enabled=True` 仅表示该数据集可由调度意图维护；它不允许普通 cron、workflow 或 calendar policy 绕过源端发布事实。自动维护只有第 7 节的独立 probe 路径：probe 根据交易日历求出目标 `D`，运行时创建 `time_input={mode: point, trade_date: D}` 和 `filters={}` 的 TaskRun；resolver 才把该用户/调度意图转为 request params。

本期不把 `margin_detail` 加入 workflow，不接入 Dagster sensor，也不新增任何 `schedule_probe_fallback`。如未来要接入任一项，必须另写对应设计并按当时模板审计，不能通过本数据集的 schedule 配置临时扩展。

### 8.3 TaskRun 观测

| 项目 | 固定口径 |
| --- | --- |
| 当前对象类型 | 日期；定点补录同时带一个证券代码。 |
| 对象标识 | full run：`trade_date`；scoped repair：`trade_date + ts_code`。 |
| 窗口 | point 为一个交易日；range 仅是计划窗口，执行时展开为多个单日 unit。 |
| full progress context 示例 | `{"trade_date":"2026-07-30","unit_id":"margin_detail:2026-07-30:0","filters":{}}`。 |
| scoped progress context 示例 | `{"trade_date":"2026-07-30","ts_code":"600000.SH","unit_id":"margin_detail:2026-07-30:0"}`。 |
| source / quality issue 示例 | `{"trade_date":"2026-07-30","page_offset":1000,"conflict_key":{"trade_date":"2026-07-30","ts_code":"600000.SH"}}`；只记录既有结构化 token、reason code 与受限样本。 |
| rejected 观测 | normalizer reject 必须呈现 `rows_rejected`、`rejected_reason_counts` 与受限 `rejected_reason_samples`；同键但内容冲突是 unit 失败，不得伪装为成功的 reject。 |

TaskRun 详情和 Ops 页面只解释这些通用结构化字段，不按 `dataset_key` 新增前端文案或另建观测表。

### 8.4 freshness / 日期审计

| 项目 | 语义 |
| --- | --- |
| 观测表 | `core_serving.equity_margin_detail`，不读取 raw 表。 |
| 观测字段 | `trade_date`。 |
| 新鲜度 | `continuous_open_day` + `next_open_day_0930`，与 `margin` 时钟语义一致。 |
| 日期完整性 | 延续 date-only 审计：当日有全量任务写入后作为该日期桶存在。 |
| 定点补录 | 只能更新已存在日期桶，不得创建该日期，因此不会推进 observed max date 或消除缺失日期。 |
| card 展示 | `raw_table=None`；来源数据页展示 `服务表：core_serving.equity_margin_detail`，target/serving 表同为该表。 |

任何使用 `raw_table` 的 projection、snapshot、schema、页面序列化和测试都必须做 null-safe 处理。不能以 placeholder 字符串冒充 raw 表，也不能为了页面不为空而增建空表。

## 9. 改动清单与消费者审计

### 9.1 预计改动文件

| 层 | 文件 / 目录 | 改动 |
| --- | --- | --- |
| Dataset contract | `src/foundation/datasets/models.py`、`definitions/_builder.py`、`ingestion/linter.py` | 支持 direct-serving storage、field-level scoped repair policy，并校验所有 write path 的 raw/core 组合。 |
| Definition | `definitions/market_equity.py`、`freshness_policies.py`、`ops/catalog/dataset_catalog_views.py` | 新增 `margin_detail`、`CONTINUOUS_OPEN_DAY` 映射和“A股行情”目录项。 |
| Planning/request | `ingestion/unit_planner.py`、`request_builders.py`、`ingestion/codebook.py` | scoped repair preflight / 结构化错误；`_margin_detail_params`。 |
| Source/client | `ingestion/source_client.py`（若字段/分页断言接口需补充） | 保证 Definition fields 在每页请求中生效。 |
| Writer | `ingestion/writer.py` | `serving_direct_upsert`，按 write path 解析必要 DAO。 |
| ORM/DAO | `models/core_serving/equity_margin_detail.py`、`models/all_models.py`、`dao/factory.py` | 新 model、表映射和 GenericDAO。 |
| DB | `alembic/versions/20260802_000123_add_margin_detail_serving_dataset.py` | 新 serving 表、索引与年度分区；已在隔离验证库从空库执行至 head。 |
| Ops probe | `ops/services/margin_detail_remote_probe_service.py`、`operations_probe_runtime_service.py`、`schedule_probe_binding_service.py` | 独立 condition、三样本 probe、schedule / runtime 双层严格口径和同日去重。 |
| Ops manual API | `ops/schemas/manual_action.py`、`ops/queries/manual_action_query_service.py`、`ops/services/manual_action_service.py` | `conditional_time_rules` 的响应、UI 同步与后端权威校验。 |
| Ops projections | `ops/dataset_definition_projection.py`、freshness/card/snapshot 相关 consumer | `raw_table=None` 类型和序列化兼容；`source` layer 显示名。 |
| Frontend | `frontend/src/shared/api/types.ts`、`ops-v21-task-manual-tab.tsx`、`ops-v21-source-page.tsx` | 条件 time mode、直出表 fallback；无 dataset-key 分支。 |
| Tests | `tests/**`、`tests/web/**`、`frontend/src/pages/**/*.test.tsx` | 见第 10 节。 |
| Docs | 本文和 `docs/README.md`；实现后更新数据集接入状态 | 实现与事实一致。 |

### 9.2 必须逐项复核的消费者

实现前和完成后均必须审计：manual actions、catalog、workflow、resolver/unit planner、request builder、source fields 注入、normalizer、writer、freshness、dataset cards、snapshot rebuild、date completeness audit、自动任务日期策略、Ops schedule API、ProbeRunLog、前端时间控件、table registry、DAO factory、迁移、测试与源文档索引。

其中 direct-serving 是共享 storage contract 改动：不得仅让 `margin_detail` 特判通过。需全量检查现有 raw/core、raw-only、snapshot、发布型等 write path，证明它们的 DAO 必要性、表投影和序列化行为保持不变。

## 10. 测试、真实验证与上线门禁

### 10.1 自动化测试

至少新增或扩展以下覆盖：

| 类别 | 必测断言 |
| --- | --- |
| Definition registry | `tests/test_fields_constants.py` 断言 11 个字段和顺序；`tests/test_dataset_definition_registry.py` 与 architecture runtime guard 均加入 `margin_detail`；验证 `next_open_day_0930`、date model、direct storage、主键、page limit、`no_pool` 和 catalog order。 |
| Request builder | 仅生成 `trade_date` 与可选单 `ts_code`；不接受 range 源参数、分页参数或 exchange。 |
| Resolver/planner | 无筛选 range 展开为逐交易日 unit；每个 unit 不携带 `start_date/end_date`。 |
| Scoped repair | 已有日期桶的 point + `ts_code` 成功；非法 / 多代码、不存在桶、带 `ts_code` range、自动任务带 `ts_code` 均以预期 reason code 拒绝；progress context 保留代码。 |
| Source pagination | 以多页 fixture 验证 offset 序列、短页停止、全页合并、重复键冲突拒绝和字段缺失拒绝。 |
| Writer | `serving_direct_upsert` 不解析/不调用 raw DAO；单事务 upsert、重复执行幂等、target table 正确。 |
| ORM/迁移 | 主键、nullable `name`、数值类型、索引/分区、model registry、DAO factory 一致。 |
| Ops projection | `raw_table=None` 时 freshness、snapshot、dataset card 与 API schema 均正常；layer plan 渲染为“源端 → 服务层”。 |
| TaskRun 观测 | full / scoped 的 `time_input_json`、unit id、progress context、结构化 issue 和 reject 统计按第 8.3 节可读呈现；不得把分页中间量当成最终已提交行数。 |
| Manual Action API / Web | `/manual-actions` 给出 `conditional_time_rules`；填写 `ts_code` 后只剩 point、清空后恢复 range；直接 POST range 仍由后端拒绝。 |
| Source page Web | raw-backed fixture 仍显示 raw 表；direct-serving fixture 显示 `服务表：core_serving.equity_margin_detail`，不显示“—”。 |
| Probe | 三样本、11 字段、日期/代码精确性；任一 miss 不建 TaskRun；全通过只建一个无筛选 `margin_detail.maintain` TaskRun；篡改 rule filters 也不能进入 TaskRun。 |
| Schedule API | 新 condition 的 action/window/interval/max trigger/空 filters / 非 probe 拦截；所有错误配置拒绝；runtime 的 target-date 去重和 failed 重试均覆盖。 |
| 回归 | `margin` probe 与所有现有 write paths 回归，证明没有被合并或改变。 |

### 10.2 必跑门禁

实现完成前，至少执行并在交付记录中保留结果：

```bash
pytest -q tests/architecture/test_subsystem_dependency_matrix.py
pytest -q tests/test_dataset_definition_registry.py tests/test_fields_constants.py tests/test_dataset_action_resolver.py tests/test_dataset_unit_planner.py
pytest -q tests/architecture/test_dataset_runtime_registry_guardrails.py tests/architecture/test_dataset_maintenance_refactor_guardrails.py tests/architecture/test_arch_no_all_sentinel.py
pytest -q tests/web/test_ops_manual_actions_api.py tests/web/test_ops_catalog_api.py tests/web/test_ops_freshness_api.py tests/web/test_ops_schedule_api.py tests/web/test_ops_probe_api.py
GOLDENSHARE_ENV_FILE=.env.web.local goldenshare ingestion-lint-definitions
python3 scripts/check_docs_integrity.py
git diff --check
```

按实际新增测试文件补充 normalizer / writer / migration / source-client 定向测试。前端共享交互和卡片改动还必须执行：

```bash
cd frontend && npm run typecheck && npm run test && npm run build
```

迁移只可在隔离验证库执行 upgrade / downgrade 验证；生产迁移和创建生产 schedule 是两个独立的显式授权步骤。

### 10.3 最小真实同步验收

在非生产验证环境或经明确批准的生产最小范围内，以一个已经确认全市场发布的 `D` 执行：

1. 先记录第 6.3 节真实 connector 分页对账证据；
2. 运行无 `ts_code` 的 `point=D`；
3. 对账：源端分页 unique 行数 = normalizer 合格行数 + rejected 行数，且 rejected 必须逐项有 reason code/样本；写入行数 = serving 表 `trade_date=D` 的唯一主键数；
4. 抽查 SH/SZ/BJ 各一条记录，比较 11 字段键和值类型；
5. 重跑相同 point，验证主键数不增加且值按 upsert 更新；
6. 对一条已存在记录运行 `point=D + ts_code`，验证只更新该键且 freshness/date audit 不改变；
7. 选择一个未入库日期运行 `point + ts_code`，验证被拒绝且零业务写入；
8. 以两种 probe 状态验证：一个样本缺失时无 TaskRun，三样本齐全时只创建无筛选的 `D` 任务。

没有完成“源端行数、归一化行数、写入行数、拒绝原因、目标表行数”对账，不得标记数据集已接入。

### 10.4 上线顺序

1. M0（已完成）：核验源文档、MCP 的默认/显式字段/时间请求与项目实际 connector 的分页；确认 Alembic head 为 `20260802_000122`，并完成第 6.3 节的 6,000 基准与 1,000 分页等价对账。
2. M1（已完成）：实现并测试 shared direct-serving storage contract、linter、projection nullable 以及 raw-backed write path / 前端卡片的回归。
3. M2（已完成）：实现 serving 表、ORM/DAO、Definition、catalog、planner/request builder、分页完整性保护、scoped repair 的 API / Web 约束；新增迁移 revision 为 `20260802_000123`，随后已在 M3 隔离库从空库应用至 head。生产已应用该 revision，`core_serving.equity_margin_detail` 仍为空，且第 5.5 节的 HDD 落盘已完成并验收。
4. M3（已完成）：已在隔离库完成第 6.3 节分页证据复核和第 10.3 节第 1–7 项全量对账，包括 full 重跑幂等、已有桶单证券补录和不存在桶的零写入拒绝。
5. M4（已完成）：已实现独立 probe 与 schedule API / runtime 双重门禁；以模拟 clock 验证周末/节假日后的 `D -> N`，以及同日去重和 failed 重试。
6. M5a（生产历史回补，待运营手工发起）：生产 revision `20260802_000123`、第 5.5 节 HDD 落盘与运行时代码部署均已完成；发布后的只读核验确认 `margin_detail` 的 TaskRun、schedule、probe_rule 与业务行数均为 0。不创建 `ops.schedule` 或 `ops.probe_rule`。按第 6.4 节逐年提交无筛选 range TaskRun，并按第 6.5 节用既有 TaskRun 指标和目标表日期完整性审计验收每年批次。历史回补到切换日 `C` 后，在仍未启用 schedule 的前提下，以无筛选 range 完成 `C+1` 至最近已完整发布交易日 `D` 的 cutover catch-up，消除历史耗时期间形成的近期缺口。
7. M5b（生产自动增量，待明确授权）：仅在 M5a 的所有年度批次和 cutover catch-up 均验收通过后，才通过 Ops API 创建唯一的 `remote_margin_detail_ready` probe schedule。其首次全通过只创建一个无筛选 `point=D` TaskRun；观察 TaskRun、ProbeRunLog、freshness/card 和日期审计后，才视为自动增量已启用。

上线前需要完成配置项审计。默认不新增环境变量或运营开关；若实施发现必须新增，须先列出名称、默认值、持久化位置、全部消费者、依赖关系、生效方式、运维可见性和测试门禁，不能把 page size、样本代码或窗口散落为多处常量。

## 11. 非目标、风险与后续决策

### 非目标

- 不共享 `margin` 的 probe 服务、condition 或业务代码；相同的发布时间事实不意味着相同的源契约。
- 不在 `raw_tushare` 建任何兼容表、view 或影子表。
- 不把 `ts_code` 扩展为批量、通配符或多证券输入。
- 不用自然日“昨天”、收盘后 workflow 或固定历史日期绕过 readiness。
- 不因本接口可选 `start_date/end_date` 或两日分页样本通过，就未经设计审计地改为年度区间 source unit；当前实现按日执行，未分页宽区间响应也不能视为完整。
- 不在 V1 以静态全市场股票列表声明“明细齐全”；融资融券标的范围需要独立的权威范围事实才能做矩阵审计。

### 已知风险与处理

| 风险 | 处理 |
| --- | --- |
| Tushare 默认字段随接口行为变化 | 每次都显式传全字段；probe 同样验证字段键。 |
| 单日行数增长超过当前样本 | 1,000 行页大小、offset 分页、短页结束、真实对账；超过预期先报告而不改宽区间。 |
| 北交所或某市场延迟发布 | 三样本未齐不创建任务，09:30 后以 stale 暴露问题。 |
| 定点补录污染 freshness | `existing_point_bucket_only` preflight 阻止其创建新日期桶。 |
| direct-serving 改动破坏旧 raw 线路 | 按 write path 选择 DAO，全量既有 write path 回归。 |
| 历史回补耗时或触及配额 | 一年一批、预先测算页数/耗时、达到不可接受量级即停下确认。 |

本文已记录 M0 的真实分页基准、M3 隔离库完整写入对账、M4 的独立 probe/schedule/runtime 验证，以及 M5a 的只读历史规模初估。生产 schema migration、HDD 落盘与运行时代码部署均已完成，目标表仍为空；尚未创建生产排程或触发生产同步。M5a 只能由运营按年度手工发起，M5b 仍须在 M5a 完整验收后单独授权。
