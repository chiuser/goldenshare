# A股业绩快报（`express`）数据集低层设计 v1

状态：**M1/M2/M3/M4a/M4b 已完成；M4c 未开始**
编写日期：2026-08-10；M1/M2/M3/M4a/M4b 状态更新：2026-08-11
适用范围：Tushare `express_vip` 业绩快报接入 Goldenshare Prod

## 1. 结论先行

`express` 应设计为“按公告自然日维护的全市场不可变事件事实”：平台调用 `express_vip`，每个 unit 只向源端传一个 `ann_date`，完成该日全部分页、33 个字段归一化和完整性校验后，在一个事务内只插入新事实。

业务表只建 `core_serving.equity_express`，不建 raw、std、current、observation、EAV 或 JSON 影子表。表、主键索引和全部二级索引都放在 `gs_raw_cold_hdd`；PostgreSQL 共享 WAL 继续留在 SSD。

已拍板的运营能力为：

1. 手动任务支持单个 `ann_date` 或自然日闭区间；区间在 planner 内逐日展开。
2. 自动任务只支持普通 cron，运营可选每日、每周或每月及具体北京时间；不支持 once、probe、fallback 或 workflow。
3. 首次自动触发生成 `[initial_start_date, 触发日-1]`；后续从该 schedule 最后一次成功覆盖的 `end_date+1` 续跑至触发日前一天。
4. 失败或取消不推进覆盖游标；retry 复用原 TaskRun 的同一时间窗口。
5. 调度参数和续跑逻辑由通用 schedule capability contract 驱动，不得在前端或 Ops 服务中增加 `express` key 白名单。

当前没有尚未拍板的 M1–M4b 业务设计项。生产 migration、首次同步和幂等验收已经完成；M4a 也已完成不调用 Tushare、不写生产数据库的规模与水位测算。M4b 已按管理员确认的 `2010-01-01` 起点完成 17 个串行 TaskRun，并回补至执行日冻结的 `D-1=2026-08-10`。生产 cron 时间与 schedule 创建仍属于独立的 M4c。

## 2. 目标、范围与明确不做

### 2.1 目标

- 冻结 `express_vip` 参数、显式字段、分页和全市场完整性契约；
- 分开时间输入、执行 unit、freshness/audit 三层语义；
- 固定单事实表、主键、去重、修订和 fail-closed 规则；
- 给出 Definition、planner、request builder、normalizer、writer、ORM/DAO、migration、Ops/UI 和测试的真实落点；
- 把自动任务“首次起点 + 最后成功续跑”表达为通用契约，并证明不会要求现有自动任务重新配置。

### 2.2 M1 明确不做

- 生成 migration 代码，但不在任何 PostgreSQL 环境应用 migration；
- 不连接或写入隔离/生产 PostgreSQL；
- 不调用 Tushare，不消耗新的接口配额；
- 不创建、修改、启用或触发 TaskRun、schedule、probe 或 workflow；
- 不实施历史回补，不自动 seed schedule；
- 不暴露 `ts_code`、`period`、`start_date/end_date` 等源端筛选参数；
- 不把本数据集接入 Lake/Dagster；
- 不为“可能的晚到或上游原地修改”自行增加重叠窗口或 observation 表。

## 3. 依据与当前基线

### 3.1 文档依据

- [数据集开发说明模板](../templates/dataset-development-template.md)
- [Tushare 业绩快报源文档](../sources/tushare/股票数据/财务数据/0046_业绩快报.md)
- [Dataset 日期模型消费指南](../architecture/dataset-date-model-consumer-guide-v1.md)
- [DatasetDefinition 单一事实源方案](../architecture/dataset-definition-single-source-refactor-plan-v1.md)
- [DatasetExecutionPlan 方案](../architecture/dataset-execution-plan-refactor-plan-v1.md)
- [Ops Catalog 当前配置](../../src/ops/catalog/dataset_catalog_views.py)

### 3.2 当前代码依据与 CodeGraph 影响面

CodeGraph 索引在仓库根目录校验为 up to date。本轮使用 CodeGraph 与逐文件阅读核验了以下消费者：

```text
DatasetDefinition / definition builder / runtime registry guard
  -> manual actions / catalog / workflow exclusion
  -> DatasetActionResolver / natural-day unit planner
  -> request builder / paginated source client
  -> normalizer / immutable writer / DAO factory
  -> ORM registry / freshness / dataset cards / snapshot rebuild
  -> schedule time policy resolver / capability resolver
  -> schedule schema / catalog query / TaskRun service / scheduler
  -> frontend automatic-task form and API types
```

M1 已新增 `express` Definition、ORM、DAO 注册、migration、Ops item 与专项测试；`low_frequency` runtime guard 当前固定为 `dividend`、`express` 和 `stk_holdernumber`。

已确认可直接复用：

```text
build_natural_day_point_units
offset_limit 源端分页（每页显式 fields，短页结束）
source_multiplicity_policy=deduplicate_identical
serving_immutable_fact_insert
ImmutableFactDAO
TaskRun 任务详情与 event-run freshness
```

必须扩展但不得按数据集硬编码的共享契约：

- schedule policy 参数的 Definition 表达、API 输出、前端渲染和后端校验；
- 按同一 schedule 最近成功 TaskRun 生成下一闭区间的通用日期策略；
- 到期 schedule 的锁定、TaskRun 创建和 `next_run_at` 推进的单事务语义。

不新增通用“A股财务数据框架”，不修改既有 writer/DAO 语义，不把 `forecast/fina_indicator` 等未审计数据集提前绑定进来。

### 3.3 Alembic 与工作区基线

- 2026-08-11 M1 编码前重新只读核验的 Alembic 唯一 head 是 `20260810_000131`；新增 migration 为 `20260811_000132`，`down_revision` 精确连接该真实 head。
- `20260811_000132` 已在本机全新 PostgreSQL 18.4 隔离库从零迁移到唯一 head；Prod 也已提前应用该 revision，并已部署包含同一 migration 的代码版本。隔离库证明目标 relation 强制路由到 `gs_raw_cold_hdd`；Prod 只读核验的冷存储路径为 `/data/disk/postgresql/tablespaces/gs_stk_mins_hdd`。
- 当前工作区存在与本数据集无关的用户修改；M1 对账只认本文列出的文件，不纳入或覆盖其他改动。

## 4. 源端契约复审

### 4.1 接口身份和权限

- Tushare 文档 doc_id=46 的数据是“业绩快报”，不是“业绩预告”；后者是另一个 `forecast` 接口。
- `express` 面向单股历史，文档要求 `ts_code`；全市场通道是参数一致的 `express_vip`。
- 本数据集 key 保持 `express`，源端 `api_name` 固定为 `express_vip`。
- 普通接口需 2,000 积分，VIP 全市场接口需 5,000 积分。当前审计凭据能成功调用，但隔离库和生产环境仍需各自只读预检权限。

### 4.2 输入参数真实行为表

| 请求形态 | 已验证参数 | 结果 | 分页证据 | 设计结论 |
| --- | --- | ---: | --- | --- |
| 不传业务参数 | `express_vip()` | 29,590 行（6 页） | `5000*5+4590` | 宽范围在不同 fields 组合下出现分页重叠差异，禁止用作生产维护主路径或完整性基线。 |
| 只传对象 | `express(ts_code=603535.SH)` | 11 行历史 | 未触发第二页 | 只能证明单股查询，不满足全市场维护。 |
| 只传时间点 | `ann_date=20250408` | 14 行 | 未触发第二页 | 可定义一个全市场公告日 unit。 |
| 传时间区间 | `20250408..20250410` | 34 行 | 业务键集合等于 14+11+9 三个单日并集 | 源端区间可用于 A/B，不用于生产 unit；生产按日分隔完整性和事务边界。 |
| 只传报告期 | `period=20241231` | 1,409 行 | `limit=500` 为 `500/500/409` | 证明 offset/limit 可用；`period` 不是主维护输入。 |

源端有可选参数不等于平台要暴露它。`ts_code`、`period`、源端区间参数都会把全公告日 scope 缩成局部结果，不能进入本数据集的运营 filters。

### 4.3 默认、显式和业务关键字段

固定 `source_fields` 共 33 个：

```text
ts_code, ann_date, end_date, revenue, operate_profit, total_profit,
n_income, total_assets, total_hldr_eqy_exc_min_int, diluted_eps,
diluted_roe, yoy_net_profit, bps, yoy_sales, yoy_op, yoy_tp,
yoy_dedu_np, yoy_eps, yoy_roe, growth_assets, yoy_equity, growth_bps,
or_last_year, op_last_year, tp_last_year, np_last_year, eps_last_year,
open_net_assets, open_bps, perf_summary, is_audit, remark, update_flag
```

| 验证组 | 当前结果 | 结论 |
| --- | --- | --- |
| 不传 `fields` | 约 15 个默认字段 | 不完整，禁止依赖默认返回。 |
| 按原文档显式请求 | 32 个原页字段全部返回 | 文档字段可用，但仍缺 `update_flag`。 |
| 补入业务关键字段 | 33 个字段全部返回 | `update_flag` 必须显式请求并入库。 |

每一页必须携带完全相同的 33 字段 `fields`。不得因为 Ops 页面暂时不展示某列而减少源字段。

### 4.4 未文档化值与修订样本

- 29,590 行明确字段样本中，`is_audit=0/1/2` 分别为 `29,092/442/56`。官方文档只说明 0/1，因此本地保留 nullable INTEGER 原值，不用 CHECK 限制 0/1，不自行解释 2。
- `update_flag=0/1` 当前分别为 `29,589/1`；按 nullable TEXT 保留，不作为主键或过滤条件。
- `601231.SH + end_date=20260630` 存在两条不同公告：`ann_date=20260710/update_flag=0` 与 `ann_date=20260729/update_flag=1`。两条都是独立披露事实，必须同时保存。

上述样本证明 `update_flag` 是内容字段，不能代替公告日事件身份；也不能把新公告覆盖到旧公告上。

### 4.5 分页契约与宽范围异常

`period=20241231` 的有界分页已证明：`offset=0/500/1000`返回 `500/500/409`，合并后 1,409 个业务键与同范围不分页基线一致。因此实现固定：

- `pagination_policy=offset_limit`；
- `page_limit=5000`；
- offset 从 0 开始，每次加固定 `page_limit`；
- 短页才结束；满页必须继续请求下一页；
- 不设任意最大页数；
- 任一页失败、字段缺失或分页合并冲突，整个 `ann_date` unit 失败，不发布部分结果。

宽范围无参请求只能做研究证据：

- 33 字段请求返回 29,590 行，三字段业务键和完整行当前都是唯一的；
- 另一次四字段请求也返回 29,590 行，但只有 27,961 个唯一行，存在 1,629 个页间重叠；
- 异常成因尚未证明，禁止把“可能的服务端顺序不稳定”写成已证明结论。

生产因此不请求无参全历史或宽日期范围，而是把一个公告日定义为独立且可对账的 scope。

### 4.6 请求量、配额与事务容量

- 每个自然日至少 1 次请求；若返回满 5,000 行则继续翻页。
- 单日样本 `20250408/09/10` 分别为 14/11/9 行，完整报告期样本 `20241231` 为 1,409 行；这些是审计样本，不是永久峰值 SLA。
- 一次手动或自动执行最多 366 个自然日 unit。按当前样本一页/日估算，最多约 366 次基础请求，不把多年历史暗中塞入一次任务。
- M1 使用 10,000 行合成单 unit 验证内存、去重、冲突和回滚；它是工程门禁，不消耗源端配额，也不声称源端真实单日有 10,000 行。
- 源端调用串行，`fetch_concurrency=1`；实际耗时、限流、配额、WAL 和 HDD 水位必须在隔离/生产验收阶段实测，不用理论估算代替。

## 5. 时间、unit 与 freshness 三层语义

### 5.1 时间输入语义

| mode | 运营输入 | 含义 |
| --- | --- | --- |
| point | `ann_date` | 维护一个公告自然日的全市场快报。 |
| range | `start_date/end_date` | 维护闭区间中的每个公告自然日。 |

不支持 no-time，不暴露任何 filters。公告可发生在周末，因此必须使用自然日，不能使用交易日历。

### 5.2 执行 / unit 语义

- 一个 unit = 一个 `ann_date` 的全市场完整分页结果；
- range 按自然日升序展开；
- unit 请求参数只有 `ann_date`，`fields/limit/offset` 由通用 source client 添加；
- 一个 unit 一个业务事务；分页不是部分提交边界；
- 锁 scope 为 `express + ann_date`；
- 任一 reject、跨日行、字段缺失、同身份内容冲突或数据库失败导致整个 unit 回滚。

### 5.3 freshness / audit 语义

- `date_axis=natural_day`只表示输入和 unit 是自然日；
- `bucket_rule=not_applicable` 表示不按连续日期判定“每天应该有数据”，不等于不支持日期输入；
- `audit_applicable=false`；
- dataset card/freshness 使用 `EVENT_RUN_TRACE`，展示最近运行与覆盖窗口，不把真实空公告日标记为缺数；
- 不进入 date completeness audit 和连续日期 snapshot rebuild 逻辑。

## 6. 事实身份、去重与修订

### 6.1 主键与内容哈希

源事实身份固定为：

```text
(trim(upper(ts_code)), ann_date, end_date)
```

`source_entity_key` 算法固定为：把规范化后的三元组按 JSON 数组编码（UTF-8、`ensure_ascii=False`、紧凑分隔符），再生成 `express:<sha256>`；`identity_basis=ts_code_ann_date_end_date`。其中 `ts_code` 只在身份计算时 trim/uppercase，两个日期使用 ISO 文本。`ts_code` 源字段本身不改写。

`source_content_hash` 由归一化后全部 33 个 source fields 生成，不包含 `ingested_at`。

### 6.2 固定冲突处理

| 情况 | 处理 |
| --- | --- |
| 33 个字段完全一样的源行 | 该 unit 仅保留 1 条，`rows_deduplicated` 记录差额，不进业务表。 |
| 同一三元身份在同批出现不同内容 | fail-closed，不依赖 DAO 的“最后一行覆盖”。 |
| 目标已有同身份同内容 | 幂等匹配，不新增行，不改动原 `ingested_at`。 |
| 目标已有同身份不同内容 | `write.immutable_fact_conflict`，整个 unit 失败，需人工核查源端语义。 |
| 新公告与旧公告的 `ann_date` 不同 | 两条都插入，新公告不覆盖旧公告。 |
| 某日首次请求为空，目标 scope 也为空 | 合法 no-op，该 unit 可成功。 |
| 某日目标已有事实，重跑时源端缺少既有身份 | `write.immutable_scope_regression`，禁止把源端短暂回退当成删除。 |

当前 33 字段宽范围样本中没有发现 exact duplicate 或三元身份重复；上述策略是完整性门禁，不是声称源端已经出现了这两类异常。

## 7. `DatasetDefinition` 固定设计

目标文件：`src/foundation/datasets/definitions/low_frequency.py`。`express` 使用既有 `low_frequency / 低频数据` domain，Ops 展示分组另由 Catalog 定义为“A股财务数据”，不把展示分组误写成 foundation domain。

| 契约段 | 固定设计 |
| --- | --- |
| identity | `dataset_key=express`，`display_name=业绩快报`，`domain=low_frequency` |
| source | `api_name=express_vip`，`source_doc_id=tushare.express`，33 字段，request builder=`_express_vip_params` |
| date_model | `natural_day / not_applicable / point_or_range / ann_date_or_start_end / observed_field=ann_date / audit=false` |
| input_model | `ann_date,start_date,end_date`；无 filters |
| storage | `source->serving`；`serving_immutable_fact_insert`；只有 `core_serving.equity_express` |
| planning | `no_pool / offset_limit / page_limit=5000 / max_units=366 / build_natural_day_point_units / concurrency=1` |
| normalization | 2 个日期、26 个数值、不可变事实 transform；身份字段必填 |
| capabilities | manual point/range；cron daily/weekly/monthly；retry；无 once/probe/workflow |
| observability | `progress_label=express`，`observed_field=ann_date`，`EVENT_RUN_TRACE` |
| quality | reject 全部记录；unit_date=`ann_date`；完全重复去重；同身份冲突失败 |
| transaction | `commit_policy=unit`；一公告日一事务；幂等必须 |

### 7.1 时间输入

Definition 中按顺序声明：

```text
ann_date   公告日，point 模式使用
start_date 自然日区间开始
end_date   自然日区间结束
```

Resolver 必须拒绝：无时间输入、point/range 混用、只给区间一端、开始晚于结束、任意 filters、超过 366 个自然日。手动 API 提交前必须调用同一正式 planner 预检，不得把 `units_exceeded` 延迟到 worker 才显示。

### 7.2 归一化与 transform 落点

- `date_fields=(ann_date,end_date)`；
- `decimal_fields` 为 `revenue` 至 `open_bps` 的 26 个数值字段；
- `required_fields=(ts_code,ann_date,end_date,source_entity_key)`；
- `row_transform_name=_express_immutable_fact_row_transform`；
- transform 必须放在 `src/foundation/ingestion/row_transforms.py`，由已有动态加载机制调用；不修改 normalizer 主链，不在 request builder 里生成身份。

首版不创建通用“财务数据 contracts”模块。字段 tuple 保留在 Definition，纯身份转换保留在 `row_transforms.py`；只有未来第二个数据集证明身份算法完全相同时才评审提取，避免为了“共享”提前过耦合。

## 8. 请求、执行和写入主链

### 8.1 Request builder

新增 `src/foundation/ingestion/request_builders.py::_express_vip_params`：

- 只接受 planner unit 中的 `ann_date`；
- 格式化为 Tushare `YYYYMMDD`；
- 不接受/生成 `ts_code`、`period`、`start_date`、`end_date`；
- 不附加 `fields/limit/offset`，这三者由通用分页 client 逐页添加；
- 不做“触发日-1”或覆盖游标计算，调度策略只生成 TaskRun 意图，正式 resolver/planner 再展开成 unit。

### 8.2 Planner 和进度

复用 `build_natural_day_point_units`：

```text
unit_id: express:ann_date:<YYYY-MM-DD>
request_params: {ann_date: <date>}
progress_context:
  object_type: date
  object_label: 公告日
  object_value: <YYYY-MM-DD>
  window_start: <YYYY-MM-DD>
  window_end: <YYYY-MM-DD>
```

TaskRun 主进度按自然日 unit 展示；分页诊断使用现有逐页读取计数。页面不得在前端按 `express` key 组装进度文案。

### 8.3 Writer/DAO 复用结论

复用 `serving_immutable_fact_insert` 和 `ImmutableFactDAO`，不新增 writer/DAO 类型。这两个现有契约已支持：

- 按 unit scope 取 advisory lock；
- 任一 reject 阻断发布；
- 同批完全重复去重，同身份不同内容阻断；
- 对比已存事实，检测回退与内容冲突；
- 只插入新身份，不 update/delete 旧事实；
- 写后精确对账。

DAO factory 只增加 `self.equity_express = ImmutableFactDAO(session, EquityExpress)`。Definition 的 `core_dao_name` 对应 `equity_express`，`raw_dao_name/raw_table/observation_*` 均为 `None`。

## 9. 表结构、ORM、DAO 与 HDD migration

### 9.1 显式列模型

新增 `src/foundation/models/core_serving/equity_express.py::EquityExpress`，对应 `core_serving.equity_express`。

| 字段 | PostgreSQL 类型 | null | 说明 |
| --- | --- | --- | --- |
| `source_entity_key` | TEXT | N | 主键，三元身份哈希 |
| `source_content_hash` | VARCHAR(64) | N | 33 个源字段内容哈希 |
| `identity_basis` | TEXT | N | `ts_code+ann_date+end_date` |
| `ts_code` | TEXT | N | 源股票代码 |
| `ann_date` | DATE | N | 公告日，unit scope |
| `end_date` | DATE | N | 报告期 |
| `revenue` 至 `open_bps` | DOUBLE PRECISION | Y | 26 个源 float 字段，不自行改单位 |
| `perf_summary` | TEXT | Y | 业绩简要说明 |
| `is_audit` | INTEGER | Y | 保留 0/1/2 及未来未知整数，无布尔 CHECK |
| `remark` | TEXT | Y | 备注 |
| `update_flag` | TEXT | Y | 源端更新标识原值 |
| `ingested_at` | TIMESTAMPTZ | N | 该事实首次成功入库时间 |

数值使用 `DOUBLE PRECISION` 是因为源契约就是 float，且没有官方固定小数精度。不使用任意 `NUMERIC(30,10)` 制造并不存在的上游精度承诺。

### 9.2 约束与索引

- 命名主键：`pk_core_serving_equity_express(source_entity_key)`；
- `idx_equity_express_ann_date_ts_code(ann_date DESC, ts_code)`；
- `idx_equity_express_ts_code_end_ann(ts_code, end_date DESC, ann_date DESC)`；
- `idx_equity_express_end_date_ts_code(end_date DESC, ts_code)`。

当前全历史宽范围样本只有约 2.96 万行，且主维护 scope 是稀疏公告日。首版不分区；不为了形式上“大表化”增加空分区和运维成本。

### 9.3 Migration 契约

新 migration 必须：

1. 在任何 schema/table/index 写入前验证 `gs_raw_cold_hdd` 存在；不存在则整个 upgrade 失败。
2. table 显式指定 `postgresql_tablespace=gs_raw_cold_hdd`。
3. 命名主键索引以及三个二级索引均显式 `SET/CREATE ... TABLESPACE gs_raw_cold_hdd`。
4. 不回退到默认 SSD，不创建任何 raw/std 表。
5. downgrade 不自动删除业务事实，直接拒绝 destructive downgrade；需回退应回滚应用版本并保留表。
6. 模型能被 `table_model_registry()` 自动发现，ORM、migration 和真实表逐列一致。

WAL 是 PostgreSQL 实例共享的事务日志，不是一张表一份。本项目只控制业务 relation 的 tablespace，不修改 PostgreSQL 实例的 WAL 目录。

## 10. 自动任务通用契约

### 10.1 新策略，不新白名单

在 `DatasetScheduleTimePolicy` 中新增通用策略：

```text
policy = since_last_success_day_range
schedule_types = (cron,)
cron_repeat_modes = (daily, weekly, monthly)
explicit_time_input = forbidden
generated_time_mode = range
generated_time_field = start_date_end_date
policy_parameters = (
  initial_start_date: date, required, 首次覆盖开始日期
)
```

策略名固定为 28 字符的 `since_last_success_day_range`，不得在实现时改成超过现有 `ops.schedule.calendar_policy VARCHAR(32)` 的长名。首版不因这个策略修改 OpsSchedule 表结构。

`DatasetScheduleTimePolicy.policy_parameters` 的类型固定为 `tuple[DatasetInputField, ...]`，Definition builder 复用现有 `DatasetInputField(**row)` 构建和日期类型校验，不新建另一套前后端参数模型。API 投影复用 `ActionParameterResponse`。

`policy_parameters` 是 schedule 策略配置，不是源端 filter，不进入 `DatasetDefinition.input_model`。在 `OpsSchedule.params_json` 中使用独立结构：

```json
{
  "dataset_key": "express",
  "action": "maintain",
  "time_input": {"mode": "range"},
  "filters": {},
  "schedule_policy_params": {"initial_start_date": "YYYY-MM-DD"}
}
```

所有层都只消费这份契约，禁止 `if dataset_key == "express"`。

### 10.2 窗口生成规则

对一次计划触发时间 `scheduled_at`：

```text
target_end = Asia/Shanghai 时区中 scheduled_at 所在自然日 - 1 day

if 该 schedule 没有成功的 express maintain TaskRun:
    start = initial_start_date
else:
    start = max(成功 TaskRun.time_input_json.end_date) + 1 day

end = target_end
```

“成功 TaskRun”必须同时满足：同一 `schedule_id`、`resource_key=express`、`action=maintain`、最终状态 success，且 `time_input_json` 是有效 range。失败、取消、运行中或其他 schedule 的任务都不参与游标。retry 保留原 `schedule_id` 和原窗口，成功后自然成为新的覆盖上界。

如果 `start > end`，该次不创建空 TaskRun，只推进 `next_run_at`，并记录结构化 scheduler skip 日志。不得伪造成功业务运行。

### 10.3 创建、更新、恢复和 runtime 校验

后端通用校验器必须在以下入口都执行：

- schedule create；
- schedule update；
- schedule resume；
- scheduler runtime 入队前。

它必须拒绝：缺少/非法/未知策略参数，非 cron，日内高频，固定 time_input，任意 filters，probe/fallback，以及下一窗口超过 366 个 unit。

首次 create/update/resume 能根据下一次预计触发日期预检窗口。runtime 如因长时间停机或连续失败导致窗口超过 366 天，必须生成可读的 `units_exceeded` 问题并暂停该 schedule；不能分批后偷偷推进游标，也不能每个 scheduler tick 重复消耗请求。运营先用明确授权的手动分段任务补齐，再 resume。

### 10.4 并发入队与原子性

当前 `enqueue_due_schedules()` 先查询到期行，`TaskRunService.create_from_schedule_target()` 内部提交 TaskRun，然后再推进 schedule 并二次提交。该顺序不能提供“一个到期意图只入队一次”的数据库原子证明。

M1 必须把通用 scheduler 收敛为：

1. 每次只用 `FOR UPDATE SKIP LOCKED` 取一条到期 schedule；
2. TaskRun service 提供明确的“在当前事务中构建/flush，不自行 commit”入口，既有手动和 retry 入口保持原子语义；
3. 同一事务内完成窗口生成、正式 resolver/planner 预检、TaskRun 插入、`last_triggered_at/next_run_at/status` 更新；
4. 全部成功后一次 commit，任一失败全部 rollback；
5. 多 scheduler 实例并发测试必须证明同一 schedule/同一 `next_run_at` 只有一个 TaskRun。

这是对现有通用 schedule 事务边界的根因收敛，不是 `express` 特例。影响面覆盖所有自动任务，因此必须跑现有 schedule API/runtime/probe-fallback 回归。该改造不改 OpsSchedule 数据结构，不改现有 schedule 的 `target_key/cron/params_json`，现有自动配置不需重建。

## 11. Ops Catalog 与前端契约

### 11.1 新分组

`OPS_DATASET_DEFAULT_VIEW` 新增：

```text
DatasetCatalogGroup("equity_financial", "A股财务数据", 3)
DatasetCatalogItem("express", "equity_financial", 10)
```

新组放在“A股行情”之后；原有 3–14 组顺延为 4–15。这只是展示顺序变化，现有 TaskRun/schedule 依然按 action key 关联，不需重新配置。

### 11.2 手动任务

- `GET /api/v1/ops/manual-actions` 在“A股财务数据”显示“业绩快报”；
- 时间控件由 Definition 派生为单日/日期范围，使用自然日控件；
- 无 filters、无 no-time；
- API 在创建 TaskRun 前调用正式 resolver/planner，向前端返回最多 366 天的能力与结构化错误；
- TaskRun 保存运营输入，不保存 `fields/limit/offset` 等源参数。

### 11.3 自动任务表单

Calendar capability API 的每条 rule 新增通用 `policy_parameters`，复用现有参数描述结构（key、display name、type、required、description）。对 `express` 返回一个必填日期 `initial_start_date`。

前端 `ops-v21-task-auto-tab.tsx` 必须：

- 从当前生效 rule 渲染策略参数，而不是加 action-key 分支；
- 用自然日 `DateField` 展示“首次覆盖开始日期”；
- 必填值为空时禁止保存；
- 保存到 `schedule_policy_params`，不放进 filters/time_input；
- 编辑时回填，详情页显示参数的中文名和值；
- 随数据集能力只显示 daily/weekly/monthly + 具体时间，不显示 once/intraday/probe/fallback/fixed date/filters。

前后端契约新增字段是加性变更，`AutomationCapability.version` 保持 1；但必须同版本部署，且类型、schema、query 和前端测试必须同步，避免旧前端无法填必填策略参数。

## 12. 字段端到端对账

| # | 源字段 | 显式请求 | 归一化 | ORM/migration | 业务用途 |
| ---: | --- | --- | --- | --- | --- |
| 1 | `ts_code` | Y | TEXT；仅身份 trim/upper | TEXT NOT NULL | 身份/查询 |
| 2 | `ann_date` | Y | DATE | DATE NOT NULL | unit/身份/日期查询 |
| 3 | `end_date` | Y | DATE | DATE NOT NULL | 报告期/身份 |
| 4 | `revenue` | Y | decimal parse | DOUBLE PRECISION NULL | 营业收入 |
| 5 | `operate_profit` | Y | decimal parse | DOUBLE PRECISION NULL | 营业利润 |
| 6 | `total_profit` | Y | decimal parse | DOUBLE PRECISION NULL | 利润总额 |
| 7 | `n_income` | Y | decimal parse | DOUBLE PRECISION NULL | 净利润 |
| 8 | `total_assets` | Y | decimal parse | DOUBLE PRECISION NULL | 总资产 |
| 9 | `total_hldr_eqy_exc_min_int` | Y | decimal parse | DOUBLE PRECISION NULL | 股东权益 |
| 10 | `diluted_eps` | Y | decimal parse | DOUBLE PRECISION NULL | 摊薄 EPS |
| 11 | `diluted_roe` | Y | decimal parse | DOUBLE PRECISION NULL | 摊薄 ROE |
| 12 | `yoy_net_profit` | Y | decimal parse | DOUBLE PRECISION NULL | 同期修正净利润 |
| 13 | `bps` | Y | decimal parse | DOUBLE PRECISION NULL | 每股净资产 |
| 14 | `yoy_sales` | Y | decimal parse | DOUBLE PRECISION NULL | 收入同比 |
| 15 | `yoy_op` | Y | decimal parse | DOUBLE PRECISION NULL | 营业利润同比 |
| 16 | `yoy_tp` | Y | decimal parse | DOUBLE PRECISION NULL | 利润总额同比 |
| 17 | `yoy_dedu_np` | Y | decimal parse | DOUBLE PRECISION NULL | 归母净利润同比 |
| 18 | `yoy_eps` | Y | decimal parse | DOUBLE PRECISION NULL | EPS 同比 |
| 19 | `yoy_roe` | Y | decimal parse | DOUBLE PRECISION NULL | ROE 同比 |
| 20 | `growth_assets` | Y | decimal parse | DOUBLE PRECISION NULL | 总资产较年初 |
| 21 | `yoy_equity` | Y | decimal parse | DOUBLE PRECISION NULL | 权益较年初 |
| 22 | `growth_bps` | Y | decimal parse | DOUBLE PRECISION NULL | BPS 较年初 |
| 23 | `or_last_year` | Y | decimal parse | DOUBLE PRECISION NULL | 去年营收 |
| 24 | `op_last_year` | Y | decimal parse | DOUBLE PRECISION NULL | 去年营业利润 |
| 25 | `tp_last_year` | Y | decimal parse | DOUBLE PRECISION NULL | 去年利润总额 |
| 26 | `np_last_year` | Y | decimal parse | DOUBLE PRECISION NULL | 去年净利润 |
| 27 | `eps_last_year` | Y | decimal parse | DOUBLE PRECISION NULL | 去年 EPS |
| 28 | `open_net_assets` | Y | decimal parse | DOUBLE PRECISION NULL | 期初净资产 |
| 29 | `open_bps` | Y | decimal parse | DOUBLE PRECISION NULL | 期初每股净资产 |
| 30 | `perf_summary` | Y | TEXT | TEXT NULL | 业绩简要说明 |
| 31 | `is_audit` | Y | nullable integer | INTEGER NULL，无 0/1 CHECK | 审计原值 |
| 32 | `remark` | Y | TEXT | TEXT NULL | 备注 |
| 33 | `update_flag` | Y | TEXT | TEXT NULL | 更新标识原值 |

追加系统列只有 `source_entity_key/source_content_hash/identity_basis/ingested_at`，全部明确标识为平台审计列，不冒充源字段。

## 13. Definition 消费者对账矩阵

| 消费者 | 代码落点 | `express` 固定结果 | 必测反例 |
| --- | --- | --- | --- |
| registry/domain | `definitions/low_frequency.py`、`definitions/__init__.py`、runtime guard | 唯一 key，low_frequency 新增 express | 重复 key/域矩阵遗漏失败 |
| manual actions | manual API/catalog query | 显示 point/range 自然日 | none/filter/超 366 日被拒绝 |
| catalog | `dataset_catalog_views.py` | A股财务数据，item 10 | 分组/顺序不唯一失败 |
| workflow | workflow registry/resolver | 不出现 | 尝试 workflow/probe 被拒绝 |
| resolver/planner | `dataset_action_resolver.py`、`unit_planner.py` | 按自然日逐日 unit | 不得用交易日/宽区间 unit |
| request builder | `request_builders.py` | 只生成 ann_date | ts_code/period/start/end 不得进源请求 |
| source client | `source_clients.py` | 每页33 fields，5000 页大小，短页结束 | 第二页丢 fields/满页早停失败 |
| normalizer | `normalizer.py`、`row_transforms.py` | 日期/数值/身份/完全重复去重 | 空主键、跨日、同身份冲突失败 |
| writer/DAO | `writer.py`、`immutable_fact_dao.py`、`factory.py` | 只插入不可变新事实 | 回退/内容冲突/任一 reject 回滚 |
| ORM/migration | model registry/Alembic | 显式列单表，所有 relation 在 HDD | 缺 tablespace 原子失败，不回退 SSD |
| freshness/cards | freshness resolver/dataset cards/snapshot | event-run trace，target table 回退展示 | 不得显示伪 raw/空日缺数 |
| date audit | completeness audit | 明确不适用 | 不得生成连续期望桶 |
| schedule capability | policy resolver/capability/API/types | cron + 续跑 range + initial date | once/intraday/fixed date/filter/probe 拒绝 |
| scheduler runtime | operations schedule/task run services | 最近成功续跑，原子单次入队 | failed/canceled 不推进，并发只一 TaskRun |
| frontend | auto/manual/task detail/data source pages | 通用契约渲染 | 无 express key 分支，无不允许控件 |

## 14. 配置项审计

| 配置 | 默认/必填 | 持久化 | 消费者 | 生效方式 | 运维可见性 |
| --- | --- | --- | --- | --- | --- |
| `initial_start_date` | 必填，无默认 | `OpsSchedule.params_json.schedule_policy_params` | capability validator、TaskRun schedule resolver、前端 | create/update/resume/runtime 重校验 | 自动任务详情显示 |
| cron 周期 | daily/weekly/monthly 三选一 | `OpsSchedule.cron_expr` | schedule planner/runtime/UI | 保存后下一触发生效 | 自动任务列表/详情 |
| 执行时间 | 运营明确填写 | `cron_expr + timezone` | schedule planner/runtime/UI | 北京时间 | 预览和详情 |
| `max_units_per_execution` | Definition 固定 366，不可在 UI 修改 | 代码 Definition | resolver/planner/manual/schedule preflight | 发布后 | capability 提示和错误详情 |
| `page_limit` | Definition 固定 5000 | 代码 Definition | source client | 发布后 | TaskRun 分页诊断 |
| `fetch_concurrency` | Definition 固定 1 | 代码 Definition | executor | 发布后 | TaskRun 执行摘要 |
| HDD tablespace | 固定 `gs_raw_cold_hdd` | Alembic DDL | PostgreSQL | migration | 验收 SQL |
| Tushare 凭据/限流 | 复用现有全局配置 | env/Settings | Tushare client | 部署环境 | 环境预检/运行错误 |

不新增环境变量、数据集私有限流开关、页面常量或自动 schedule seed。现有 schedule 不使用新 policy，其 params_json 不需修改。

## 15. 文件级实现范围

### 15.1 业务数据主链

| 文件 | 变更 |
| --- | --- |
| `src/foundation/datasets/definitions/low_frequency.py` | 新增 33 字段 `express` Definition |
| `src/foundation/datasets/definitions/__init__.py` | 注册/导入低频 Definition（如当前自动发现不需则不做无效改动） |
| `src/foundation/ingestion/request_builders.py` | `_express_vip_params` |
| `src/foundation/ingestion/row_transforms.py` | `_express_immutable_fact_row_transform` |
| `src/foundation/models/core_serving/equity_express.py` | 新 ORM |
| `src/foundation/dao/factory.py` | 注册现有 `ImmutableFactDAO` |
| `alembic/versions/<then-head>_add_equity_express.py` | HDD 显式列单表与索引 |
| `src/ops/catalog/dataset_catalog_views.py` | 新分组与 item |

### 15.2 通用 schedule contract

| 文件 | 变更 |
| --- | --- |
| `src/foundation/datasets/models.py` | schedule policy 参数契约 |
| `src/foundation/datasets/definitions/_builder.py` | 新 policy/parameter 构建与静态校验 |
| `src/ops/services/dataset_schedule_time_policy_resolver.py` | 新策略和参数投影 |
| `src/ops/services/schedule_automation_capability_resolver.py` | capability 携带 policy parameters |
| `src/ops/services/schedule_automation_capability_audit_service.py` | 审计新策略及必填参数，历史非法配置可见 |
| `src/ops/services/schedule_planner.py` | 接受 28 字符新 policy，cron 时点仍按普通 daily/weekly/monthly 计算 |
| `src/ops/schemas/catalog.py` | API schema 增加 `policy_parameters` |
| `src/ops/queries/catalog_query_service.py` | Definition -> API 投影 |
| `src/ops/services/operations_schedule_service.py` | create/update/resume/runtime 校验，原子入队 |
| `src/ops/services/task_run_service.py` | 按最近成功窗口生成 range；提供不自行 commit 的 scheduler 入口 |
| `frontend/src/shared/api/types.ts` | 新 policy 字面量与参数类型 |
| `frontend/src/pages/ops-v21-task-auto-tab.tsx` | 通用参数渲染/编辑/详情，无 dataset key 分支 |

实施时若发现还需修改本表之外的共享主链，必须先用 CodeGraph 更新影响面并回写本 LLD，不得悄然扩大范围。

## 16. 测试、真实验收与门禁

### 16.1 M1 自动化测试

1. Definition/registry
   - 33 字段顺序精确一致；
   - point/range、natural-day、not-applicable、max 366、page 5000、concurrency 1；
   - runtime domain guard 的 `low_frequency` 集合增加 `express`。
2. Resolver/planner/request
   - 单日产生 1 unit，闭区间逐自然日展开，包含周末；
   - 第 367 日在提交前返回 `units_exceeded`；
   - builder 只生成 `ann_date`；
   - client 每页都带 33 fields，offset 为 0/5000/... ，短页结束；
   - 任一页失败不返回部分 unit。
3. Normalizer/writer
   - 26 数值、2 日期、`is_audit=2`、`update_flag=1` 保存；
   - 三元身份，空字段和跨日拒绝 reason code；
   - exact duplicate 去一条；同身份不同内容 fail-closed；
   - 首次插入、幂等重跑、新公告新增、scope regression、既有内容冲突、任一 reject、事务 rollback；
   - 10,000 行合成单 unit 完整执行且不消耗 Tushare 配额。
4. ORM/migration/HDD
   - registry/DAO factory 发现正确模型和 DAO；
   - migration 连真实 head；
   - 无 tablespace 时不创表；table/PK/三索引全部显式 HDD；
   - 无 raw/std/current/observation，无 destructive downgrade。
5. Ops/UI
   - 新分组顺序唯一，业绩快报不出现在 A股行情或基础数据；
   - 手动 point/range，无 filters/probe/workflow；
   - 能力 API 返回 cron daily/weekly/monthly 和必填 `initial_start_date`；
   - 前端新建/编辑/详情使用通用契约，无 `express` 分支；
   - once/intraday/fixed time/filter/probe/fallback 的 API 绕过请求全被拒绝。
6. Schedule 续跑/并发
   - 首次生成 `[initial_start_date,D-1]`；
   - success 推进，failed/canceled 不推进，retry 成功推进；
   - 不同 schedule 的成功窗口不互相污染；
   - `start>end` 跳过且不伪造 TaskRun；
   - 超 366 日失败并暂停，不发起源端请求；
   - 两个 scheduler 会话并发抢同一到期行时只有一个 TaskRun；
   - 所有既有 calendar policy、probe fallback、schedule API/runtime 测试全量回归。

### 16.2 隔离 PostgreSQL 验收（M2，需独立授权）

- 只在授权后应用 migration；
- 核验 table、PK 和三个索引的 `pg_tablespace_location()` 真实为 HDD；
- 运行 10,000 行合成容量/回滚/锁竞争门禁；
- 选一个有数据的单日做最小真实同步，不做宽范围扫描；
- 五段对账：源端分页行数、归一化接受数、写入数、reject reason/sample、目标 `ann_date` 行数；
- 幂等再跑表行数不增，`ingested_at` 不变。

### 16.3 生产验收（M3，需独立授权）

1. 只读确认当前无执行中/排队中任务，确认已部署包含对应 migration 的同一代码版本。
2. 应用生产 migration，核验真实 HDD 路径和字段/索引。
3. 使用正式 TaskRun 同步一个有数据的单日，做五段对账与幂等再跑。
4. 独立验证 dataset card/freshness/TaskRun 详情和 direct-serving 表展示。
5. 本阶段不回补历史，不创建 schedule。

### 16.4 历史与自动任务（M4，再分别授权）

- M4a：只读测算选定历史起点到当前的自然日数、预计页数、限流耗时和数据/WAL/HDD 水位，不逐日打源站接口。
- M4b：明确授权后，历史回补每次最多 366 日，分段运行并逐段对账。
- M4c：运营手工选择 `initial_start_date`、cron 周期与时间并创建 schedule；不由 migration 或代码自动 seed。

### 16.5 必跑门禁

```bash
pytest -q tests/architecture/test_subsystem_dependency_matrix.py
pytest -q tests/test_dataset_definition_registry.py tests/test_dataset_action_resolver.py tests/test_dataset_unit_planner.py
pytest -q tests/architecture/test_dataset_runtime_registry_guardrails.py tests/architecture/test_dataset_maintenance_refactor_guardrails.py tests/architecture/test_arch_no_all_sentinel.py
pytest -q tests/test_equity_express_dataset.py
pytest -q tests/web/test_ops_manual_actions_api.py tests/web/test_ops_catalog_api.py tests/web/test_ops_freshness_api.py tests/web/test_ops_schedule_api.py tests/web/test_ops_runtime.py
GOLDENSHARE_ENV_FILE=.env.web.local goldenshare ingestion-lint-definitions
cd frontend && npm run typecheck && npm run test && npm run build
python3 scripts/check_docs_integrity.py
git diff --check
```

自动任务表单有用户可见变化，M1 还必须从“新建/编辑自动任务 -> 选择业绩快报 -> 填写首次覆盖日 -> 保存 -> 查看详情”走真实浏览器验收，并验证禁止控件没有出现。

## 17. 硬需求追溯账本

| ID | 硬需求 | 代码落点 | 正向测试 | 反向测试 | 当前状态 |
| --- | --- | --- | --- | --- | --- |
| EX-01 | 使用 `express_vip` 全市场 | Definition/request builder | 单日返回全市场样本 | 不得调用 `express` 单股通道 | M0 实测、M1 契约已落地；M2 connector 与 M3 正式 TaskRun 均通过 |
| EX-02 | 33 fields 逐页显式请求且全保存 | Definition/client/ORM/migration | 第二页仍有 33 fields | 默认字段/丢 `update_flag` 失败 | M1 自动化、M2 单日源端哈希对账、M3 生产字段/冻结指纹对账通过 |
| EX-03 | point/range 逐自然日 | date model/planner | 周末仍生成 unit | 交易日展开/宽区间请求失败 | M1 已完成 |
| EX-04 | direct-serving 单不可变事实表 | Definition/writer/DAO/model | 新公告新增、幂等重跑 | raw/current/observation/覆盖旧事实禁止 | M1 已完成 |
| EX-05 | 三元身份和内容冲突 fail-closed | transform/writer | 新 ann_date 可并存 | 同身份不同内容阻断 | M1 已完成 |
| EX-06 | table/PK/index 全部 HDD，WAL 不改 | migration | 真实 tablespace 路径 | 缺 HDD 不得落默认盘 | M2 隔离库 5 个 relation 均命中 `gs_raw_cold_hdd`；Prod 冷存储真实路径已只读确认 |
| EX-07 | Ops 新增“A股财务数据” | catalog | 手动/自动均显示新组 | 不得塞入 A股行情 | M1 已完成 |
| EX-08 | cron 可配 daily/weekly/monthly+时间 | capability/API/UI | 三种周期可保存 | once/intraday/probe/fallback 拒绝 | M1 自动化完成；浏览器走查待有效本地账号 |
| EX-09 | 首次起点+最后成功续跑 | schedule policy/TaskRun query | success 推进 | failed/canceled/他 schedule 不推进 | M1 已完成 |
| EX-10 | 策略参数通用契约驱动 | model/schema/query/types/UI | API 渲染 initial date | 代码无 `express` key 分支 | M1 已完成；浏览器走查待有效本地账号 |
| EX-11 | 到期 schedule 原子单次入队 | schedule service/task service | 单事务成功 | 并发不得创建 2 个 TaskRun | M1 自动化完成；M2 真实 PostgreSQL 双会话 `SKIP LOCKED` 只创建 1 个 TaskRun |
| EX-12 | 最多 366 天且提交/runtime 预检 | Definition/manual/schedule | 366 成功 | 367 不发请求并显示正确错误 | M1 已完成 |
| EX-13 | 五段真实对账后才能验收 | M2/M3 运行证据 | source=normalized+dedup+reject，DB 一致 | 任一差额阻断 | M2 隔离库、M3 首次正式 TaskRun 与正式幂等 TaskRun 均已通过 |
| EX-14 | 历史回补前先做无源端扫描的规模、水位和配额测算 | M4a 只读审计记录 | 候选起点均给出 unit/批次/节拍/空间 | 未拍板起点不得进入 M4b | M4a 测算完成；管理员已拍板 `2010-01-01` |
| EX-15 | M4b 从 2010 起逐年串行回补，逐批对账后才继续 | 正式 Manual Action/TaskRun 主链 | 每年成功并完成五段对账 | 不并行、不额外源端扫描、不进入 M4c | 已完成；17/17 TaskRun、6,066/6,066 unit 和逐批五段对账全部通过 |

## 18. 里程碑与发布顺序

| 阶段 | 内容 | 状态/边界 |
| --- | --- | --- |
| M0 | 本地文档、Tushare 真实行为、当前代码和 LLD 审计 | 已完成；未编码 |
| M1 | Definition、request/normalizer、ORM/DAO/migration、Ops/UI、通用 schedule contract、单元/集成/前端验证 | 代码与自动化门禁完成；真实浏览器走查待有效本地账号 |
| M2 | 隔离 PostgreSQL migration、HDD placement、合成容量/锁/回滚、最小真实同步对账 | 已完成；使用临时目标门禁隔离到 `127.0.0.1:55410/goldenshare_express_m2`，Prod 前后只读指纹一致 |
| M3 | 生产只读预检、migration、HDD 路径、首次单日同步与五段对账 | 已完成；`TaskRun#7923/#7928` 分别验证首次插入和正式幂等再跑，卡片/freshness/详情验收通过 |
| M4a | 历史规模与配额只读预估 | 已完成；零 Tushare 请求、零生产写入；后续由管理员固定历史起点为 `2010-01-01` |
| M4b | 历史分段回补 | 已完成；17 个年度 TaskRun 串行回补至 `2026-08-10`，逐批与最终汇总对账全部通过 |
| M4c | 运营手工创建/启用 schedule | 需独立授权；无代码 seed |

发布顺序固定为：同版本部署后端+前端 -> 确认无正在运行任务 -> migration -> HDD 核验 -> 单日首次同步 -> 幂等重跑 -> 卡片/页面验收。历史和 schedule 不随 migration 自动执行。

## 19. 风险、回滚与已知边界

### 19.1 主要风险

| 风险 | 影响 | 门禁 |
| --- | --- | --- |
| 宽范围页序不稳定原因未证明 | 可能重复/漏行 | 生产只按 ann_date，有界分页，同身份冲突失败 |
| `is_audit=2` 语义未文档化 | 布尔化会丢信息 | 保留 nullable INTEGER 原值，不加 0/1 CHECK |
| 同三元身份真的被上游原地修改 | 不可变契约冲突 | fail-closed 并人工核查，不覆盖 |
| 一次窗口太长 | 配额/耗时/失败面扩大 | 366 unit 上限，手动/调度共用 preflight |
| scheduler 并发重复入队 | 重复任务和额外请求 | 到期行锁+创建/推进单事务+并发测试 |
| 后端先于前端部署新必填参数 | 旧 UI 不能创建 express schedule | 前后端同版本部署，API/browser 验收后才创建 schedule |

### 19.2 晚到记录边界

已拍板的自动策略确保每个自然日不因调度停机而跳过，但它不自动重跑已经成功的旧 `ann_date`。如果上游在某日成功同步之后，才把一条新记录归入该旧公告日，首版只能通过手动重跑该日发现。

这是明确已知边界，不得在 M1 自行增加滚动重叠窗口。若生产证据证明晚到有规律，再另行拍板重跑周期和配额成本。

### 19.3 回滚

- M1 代码回滚：回滚应用版本；不删表，不删数据。
- M2/M3 migration 失败：利用 PostgreSQL DDL 事务整体回滚；缺 HDD 不允许部分落盘。
- schedule 契约回滚：只暂停新创建的 `express` schedule，保留 TaskRun 和业务数据；现有数据集 schedule 不需迁移或重建。
- 业务数据不使用 downgrade 删除；如需清理必须另行授权并给出逐表备份/清单。

## 20. M1–M3 阶段完成记录

### 20.1 已完成

- Definition 固定 `express_vip`、33 个显式字段、5,000 行分页、自然日逐日 unit、366 unit 上限和 direct-serving immutable fact 写入契约。
- 新增三元身份 transform、显式 ORM、`ImmutableFactDAO` 注册和 HDD fail-closed migration；该 migration 已应用于隔离库和 Prod。
- Ops Catalog 新增“A股财务数据”，手动任务支持 point/range 且无 filters；workflow/probe 均未接入。
- 新增通用 `since_last_success_day_range` 策略参数契约；前后端从 capability 渲染 `initial_start_date`，无 `express` action-key 白名单。
- scheduler 使用 `FOR UPDATE SKIP LOCKED` 逐条锁定到期配置，TaskRun stage 与 schedule 推进同事务提交；空窗口结构化 skip，超 366 日创建 planner issue 并暂停 schedule。
- 自动化覆盖 10,000 行本地合成 unit、后续页失败、完全重复去重、身份冲突、scope regression、事务回滚、成功游标、失败/取消/他 schedule 隔离、API 绕过拒绝和旧 schedule/probe-fallback 回归。合成数据完全在本地生成，未调用 Tushare、未消耗配额。

### 20.2 本地验证证据

- M1 规定的后端集合：`419 passed, 1 deselected`；deselect 的唯一项是当前 HEAD 中分页进度实现与旧 guardrail `test_task_run_query_does_not_use_technical_unit_id_as_display_title` 的既有冲突，文件不在 M1 改动范围，未用无关测试补丁掩盖。
- express 成功游标定向回归：`5 passed`；已覆盖首次起点、最后成功续跑、配置起点下界、空窗口跳过和超限暂停。
- frontend：`npm run typecheck`、全量 Vitest `138 passed`、生产 build 通过；自动任务页定向 Vitest 为 `15 passed`。
- Ruff、`ingestion-lint-definitions`、docs integrity 与 `git diff --check` 通过。

### 20.3 未完成与边界

- M1 时本地独立浏览器能打开登录页，但预填测试账号无效，因此当时没有把生产旧页面冒充本地新表单验收。生产现已部署同版本；自动任务新建/编辑表单的真实浏览器路径仍留到 M4c 创建 schedule 前验收。
- M2 已完成。隔离库中的 1 条 schedule 和 1 条 TaskRun 仅用于真实 PostgreSQL `SKIP LOCKED` 并发验收，没有启动 worker；M3 已在 Prod 创建正式 express TaskRun，仍未创建或修改 express schedule、probe/workflow。
- M2 只调用 `express_vip` 2 次，均为 `ann_date=20250408` 的单页请求；未扫描其他日期、未回补历史。

### 20.4 M2 配置优先级事故记录

- M2 首次执行时，命令行虽然显式设置了隔离 `DATABASE_URL`，但 `get_settings()` 会把 `GOLDENSHARE_ENV_FILE=.env.web.local` 中的同名值作为构造参数，并临时移除同名环境变量，因此 Alembic 实际连接到了 Prod。
- 结果是 Prod 提前应用 `20260811_000132`。只读复核确认 `core_serving.equity_express` 行数为 0；表、主键和三个二级索引均位于生产 `gs_raw_cold_hdd`，真实路径为 `/data/disk/postgresql/tablespaces/gs_stk_mins_hdd`。
- Prod 中 `express` TaskRun、schedule 和 queued/running/canceling 任务均为 0；本轮事故没有调用 Tushare，也没有写入业务行。禁止用这次提前 migration 冒充 M2 或 M3 通过。
- 未执行 destructive downgrade 或删表。M2 恢复时使用不加载 `.env.web.local` 数据库地址的临时隔离配置，并在同一进程中同时断言应用设置对象和数据库服务端返回的 host、port、database；传入非隔离目标的负向测试在连接前失败。

### 20.5 M2 隔离验收记录

- 隔离环境：全新 PostgreSQL 18.4，固定目标 `127.0.0.1:55410/goldenshare_express_m2`。迁移前目标门禁负向测试确认远程 host/port/database 会在连接前被拒绝；随后从空库完整迁移到唯一 head `20260811_000132`。
- 本机物理介质说明：`/Volumes/datasource` 被 macOS 识别为外置 SSD，因此没有把它冒充机械盘。隔离验收只证明 `equity_express`、主键索引和三个二级索引共 5 个 relation 全部显式落到独立 `gs_raw_cold_hdd` tablespace；生产冷存储的实际路径另由 Prod 只读核验确认。
- 10,000 行容量：本地生成 10,001 条输入（含 1 条完全重复），归一化后 10,000 条、去重 1 条、插入 10,000 条、目标 10,000 条，用时 3.976 秒；验收进程峰值 RSS 为 448.12 MiB。该进程随后还构造了另一批 10,000 行用于回滚注入，因此该 RSS 是整个验收进程上界，不是单个生产 unit 的增量内存。
- 事务回滚：第二批 10,000 行在第 2 个批量 INSERT 前注入故障；事务回滚后该 `ann_date` 目标行数为 0，证明前一批 INSERT 未部分可见。
- 数据 scope 锁：第一会话持有同一 `ann_date` 的 advisory xact lock 时，第二会话得到 PostgreSQL `55P03`；第一会话释放后第二会话可取得锁。
- scheduler 并发：第一会话锁住唯一到期的 express schedule，第二会话通过 `FOR UPDATE SKIP LOCKED` 创建 0 个 TaskRun；持锁会话创建 1 个，最终该 schedule 只有 1 个 TaskRun，时间窗口为 `2026-08-10..2026-08-10`，`next_run_at` 原子推进到下一次 cron。
- 最小真实同步：项目 connector 对 `ann_date=20250408` 首次和幂等重跑各请求一次；每次参数均为 `ann_date=20250408, offset=0, limit=5000`，33 个 `source_fields` 完整携带，均返回 14 行短页。
- 五段对账：首次 `source=14`、`normalized=14`、`deduplicated=0`、`rejected=0`、`inserted_new=14`、目标 scope `=14`；源端身份/33 字段内容哈希多重集与目标表完全一致。第二次 `source=14`、`normalized=14`、`rejected=0`、`inserted_new=0`、`matched_existing=14`、目标仍为 14，包含 `ingested_at` 的 scope 指纹不变。
- Prod 前后只读指纹一致：revision 均为 `20260811_000132`，`core_serving.equity_express=0`，express TaskRun/schedule 均为 0，全系统 queued/running/canceling 均为 0。M2 没有向 Prod 写入任何业务或 Ops 数据。

### 20.6 M3 生产验收记录

- 生产预检：远端 `dev-interface` HEAD 为 `55a460713725c50d6f33492f68a26b772f068336` 且工作区干净；Web、worker、scheduler 均 active，两个健康接口通过，Web 入口为 `python -m src.app.web.run`。数据库 revision 为 `20260811_000132`，express 表/TaskRun/schedule 和全系统开放任务均为 0。
- 生产 placement：`equity_express`、主键和三个二级索引共 5 个 relation 均位于 `gs_raw_cold_hdd`，`pg_tablespace_location()` 为 `/data/disk/postgresql/tablespaces/gs_stk_mins_hdd`。
- 创建门禁：首次尝试因把外部只读连接看到的 `10.2.24.2` 误当作远端应用本机连接地址而在任何写入前失败；复核仍为 0 行/0 TaskRun。修正后的门禁同时校验应用解析目标、服务端返回的 `127.0.0.1:5432/goldenshare`、revision 和 5 个 relation 的生产冷盘路径，不是放宽为任意本机数据库。
- 正式 TaskRun：通过 `ManualActionCommandService` 的正式 Manual Action 主链创建 `TaskRun#7923`，`action_key=express.maintain`、`trigger_source=manual`、`time_input={mode: point, ann_date: 2025-04-08}`、无 filters；正式 planner 在入队前完成预检。
- 首次执行：TaskRun 成功，`unit_total=1`、`unit_done=1`、`unit_failed=0`；源端分页为 1 页、`offset=0`、终止短页 14 行、无 retry。五段结果为 `fetched=14`、`normalized_before_dedupe=14`、`deduplicated=0`、`rejected=0`、`saved/inserted_new=14`，无 reject reason、无 issue。
- 目标核对：生产 scope/全表均为 14 行，实体键和 `(ts_code, ann_date, end_date)` 业务键均为 14 个，必填字段空值为 0；33 个显式 source fields 全部存在于 37 列目标表中，14 个实体身份和 `identity_basis` 均可从目标字段重算一致。
- 源内容核对没有再次请求 Tushare：Prod 14 条 `(source_entity_key, source_content_hash)` 的有序指纹为 `bbd09c0b291d7c8128d3604cabdfe83a`，与 M2 中已经通过源端哈希对账的冻结隔离快照完全一致。不能用目标表读回值直接重算 `source_content_hash`：源数值在 hash 时是 `Decimal`，LLD 固定的目标列是 `FLOAT`，读回后是 `float`，类型敏感 hash 会产生伪差异；正确审计对象是源归一化 hash 与持久化 hash。
- Ops 投影与浏览验收：后端 TaskRun 查询投影和生产页面 `/app/ops/tasks/7923` 均显示“业绩快报”、手动发起、范围 `2025-04-08`、进度 `1/1` 与 100%、读取/保存/拒绝/去重为 `14/14/0/0`、源端 1 页短页结束、不可变事实首次插入 14 条且无 issue。生产数据集页 `/app/ops/v21/datasets/tushare` 中该卡片只出现一次，位于“A股财务数据”，服务表为 `core_serving.equity_express`，最新事件日期为 `2025-04-08`；API 投影同时证明 `raw_table/raw_table_label=null`、`layer_plan=source->serving`、freshness policy 为 `event_run_trace` 且状态为 `fresh`，没有 schedule 或 probe。
- 并发门禁：首次验收后出现用户的 `idx_factor_pro TaskRun#7924` 和 `news TaskRun#7925`，本轮没有抢占或插队；只读等待两者均成功且开放队列恢复为 0 后，才允许创建幂等任务。两次远端脚本尝试分别因交互式 shell 缺少 Web 生产环境和普通账号无权读取 `/etc/goldenshare/web.env` 而在数据库连接前失败；复核证明未创建 TaskRun、未调用 Tushare、目标仍为 14 行。最终只使用现有 sudo 授权，以 Web 服务相同的 `GOLDENSHARE_ENV_FILE` 执行门禁，没有读取/输出凭据、修改 sudoers 或更改服务配置。
- 正式幂等 TaskRun：`TaskRun#7928` 使用与首次相同的 `express.maintain`、`ann_date=2025-04-08` 和空 filters；成功完成 `1/1` unit，耗时 80 ms，无 issue。结果为 `fetched=14`、`normalized_before_dedupe=14`、`deduplicated=0`、`rejected=0`、`inserted_new=0`、`matched_existing=14`、`scope_existing_count=14`。
- 幂等目标核对：再跑后生产 scope/全表仍为 14 行，实体键和业务键均为 14 个，必填字段空值为 0；内容指纹仍为 `bbd09c0b291d7c8128d3604cabdfe83a`，包含 `ingested_at` 的不可变指纹在再跑前后均为 `a5931861d7b392ddf7f9c1548c7433a4`。`TaskRun#7923/#7928` 均成功，开放队列再次为 0。M3 总计仅由两个正式 TaskRun 各调用一次 `express_vip`，没有额外源端扫描。

| 本阶段追溯 ID | 已验证证据 | 未完成项 | 结论 |
| --- | --- | --- | --- |
| EX-01–EX-12 | M0 源端证据、M1 代码/自动化、M2 PostgreSQL migration/placement/容量/回滚/并发与真实 connector、M3 生产 placement 和 Ops 页面 | 生产自动任务新建/编辑页属于 M4c 创建 schedule 前验收 | **M1/M2/M3 当前范围通过** |
| EX-13 | M2 单日两次真实请求、五段对账、目标哈希与幂等指纹；M3 `TaskRun#7923/#7928` 首次生产同步和正式幂等再跑 | 无 | **M2/M3 均通过** |

### 20.7 M4a 历史规模与配额只读测算

#### 20.7.1 执行边界与生产基线

M4a 审计时点为 2026-08-11，历史回补测算终点固定为前一自然日 `2026-08-10`。本阶段没有调用 Tushare，没有创建 TaskRun/schedule，没有写生产数据库，也没有执行 migration、部署或历史回补。

生产核验只在显式 `READ ONLY` 事务中读取 `core_serving.equity_express`、express TaskRun/schedule 的聚合值和 PostgreSQL relation 元数据，并在服务器上只读检查文件系统水位：

- 目标表仍为 14 行，`ann_date` 只有 `2025-04-08`；平均和最大 `pg_column_size` 均为 304 bytes。
- heap 为 8 KiB、四个索引合计 64 KiB、总 relation 为 80 KiB。该数值主要是五个 relation 的最小页开销，不能按 `80 KiB / 14` 外推历史容量。
- 表、主键和三个二级索引仍全部位于 `gs_raw_cold_hdd`，真实路径为 `/data/disk/postgresql/tablespaces/gs_stk_mins_hdd`。
- HDD 文件系统总量 393.53 GiB、已用 55.78 GiB、可用 317.74 GiB，使用率 15%。
- PostgreSQL/WAL 所在 SSD 文件系统总量 216.43 GiB、已用 190.66 GiB、可用 16.85 GiB，使用率 92%。WAL 配置为 `max_wal_size=1GB`、`min_wal_size=80MB`、`checkpoint_timeout=5min`、`wal_compression=off`、`full_page_writes=on`、`archive_mode=off`。`max_wal_size` 是共享 WAL 的检查点软目标，不是 express 的独占空间或硬上限。
- express 仍只有成功的 `TaskRun#7923/#7928`，没有 express schedule；审计时全系统没有 queued/running/canceling TaskRun。

第一次只读查询尝试读取受限的 PostgreSQL `data_directory` 设置时被权限拒绝，事务在任何业务统计返回前中止。随后删除该非必要字段并重新执行上述白名单查询；两次均为只读操作，没有扩大权限。

#### 20.7.2 请求数、分页和时间测算

当前生产 worker 使用 `/etc/goldenshare/web.env`；其中未配置 `TUSHARE_MAX_CALLS_PER_MINUTE`，因此 `express_vip` 使用代码默认 280 次/分钟。`express_vip` 没有单接口 override，Definition 固定 `fetch_concurrency=1`，所以同一 worker 内相邻请求的最小节拍约为 `60/280=0.214` 秒。

每个自然日 unit 至少发起一次请求，即使该日返回空结果也消耗一次请求。下表的“基础请求数”假设每个自然日都在第一页短页结束；若某日超过 5,000 行，实际请求数还要增加该日的后续分页数。当前只证明 `2025-04-08` 单日 14 行和 `2025-04-08..10` 三日 14/11/9 行，尚无“历史所有单日都不超过一页”的证据，因此基础请求数是精确下限，不冒充绝对总数。

| 候选起点 | 至 `2026-08-10` 自然日 unit | 基础请求数 | 按每批最多 366 日计算的最少批次 | 按 280 次/分钟的纯请求节拍下限 |
| --- | ---: | ---: | ---: | ---: |
| `1990-01-01` | 13,371 | 13,371 | 37 | 47.75 分钟 |
| `2000-01-01` | 9,719 | 9,719 | 27 | 34.71 分钟 |
| `2010-01-01` | 6,066 | 6,066 | 17 | 21.66 分钟 |
| `2014-01-01` | 4,605 | 4,605 | 13 | 16.45 分钟 |
| `2018-01-01` | 3,144 | 3,144 | 9 | 11.23 分钟 |
| `2020-01-01` | 2,414 | 2,414 | 7 | 8.62 分钟 |

这些时间不包含网络波动、源端限流重试、空日处理、归一化、逐日事务、任务排队和人工分段间隔，不能作为完成 SLA。M4b 应按自然年顺序串行提交；完整自然年为 365/366 个 unit，天然满足 366 上限，同时把失败、对账和重试边界限制在一年内。不得并行创建多个历史 TaskRun 来绕过 `fetch_concurrency=1` 或共享 Tushare 限流器。

M4a 实际消耗的 Tushare 请求数为 **0**。29,590 行宽范围样本只复用 M0 已有证据做容量量级参考，不重新请求，也不把该宽范围结果当成完整性基线。

#### 20.7.3 HDD 与 WAL 容量门禁

M0 的无业务参数宽范围样本为 29,590 行，但它在不同 fields 组合下出现过分页重叠差异，因此只能说明行数量级。按生产现有 304 bytes/row 计算，29,590 行的纯 tuple 载荷约 8.58 MiB；这不含 heap page、TOAST 和四个 B-tree 索引，也不证明历史最终只有这些行。

为避免把 14 行样本误当精确容量模型，M4a 使用显式压力假设而不是伪精确预测：按 M0 行数的 4 倍、当前平均行宽的 2 倍估算，纯 tuple 载荷约 68.63 MiB；再为 page、可变长文本和四个索引预留 4 倍空间后约 274.5 MiB，最终把 express 历史表的 HDD 操作预留向上取整为 **512 MiB**。这是回补前容量门禁，不是源端行数 SLA。

WAL 在 SSD 上按日事务持续产生，但因为每个 unit 单独提交，不需要把整个历史事务的 WAL 同时保留。M4b 为 express 额外保留 **2 GiB** 瞬时 WAL 操作余量；这相当于当前 `max_wal_size` 软目标的 2 倍，但不能替代对共享 WAL、复制槽或其他写任务的实时监控。当前 SSD 可用 16.85 GiB，满足该 express 操作余量；不过总盘已使用 92%，因此每个年度批次开始前仍必须重新核验开放任务和 SSD/HDD 水位，不能沿用本次快照。

#### 20.7.4 结论与历史起点拍板

M4a 的工程结论是：即使从 `1990-01-01` 回补到 `2026-08-10`，请求量、年度批次数和 HDD/WAL 预留都没有达到必须裁剪历史的程度。源端文档和既有实测没有证明最早可用 `ann_date`，因此不得把 2014、2018 或任一有数据样本年宣称为“源端起点”。

管理员明确不采用 `1990-01-01`，M4b 历史起点固定为 **`2010-01-01`**。执行时终点冻结为 `D-1`；以 2026-08-11 为执行日时，终点为 `2026-08-10`，共 6,066 个自然日 unit、至少 6,066 次请求和 17 个年度 TaskRun。该决策表示 2010 年以前的数据不属于本轮回补范围，不能把未回补年份误报为缺失或失败。

M4b 已获独立授权；M4c 的 cron 时间和 schedule 创建继续独立授权，本轮不得创建或修改 schedule。

| 本阶段追溯 ID | 已验证证据 | 未完成项 | 结论 |
| --- | --- | --- | --- |
| EX-14 | 零 Tushare 请求；生产表/TaskRun/schedule、HDD/SSD、WAL 配置只读核验；六个起点情景测算 | 无 | **M4a 测算完成；历史起点固定为 `2010-01-01`** |

### 20.8 M4b 生产历史回补执行契约

#### 20.8.1 范围与分段

- `2010-01-01..2025-12-31` 按完整自然年拆为 16 个闭区间 TaskRun；2012、2016、2020、2024 各 366 个 unit，其余完整年各 365 个 unit。
- 最后一批为 `2026-01-01..D-1`；终点在实际执行开始时冻结。若执行日仍为 2026-08-11，该批为 222 个 unit。
- 所有区间从旧到新串行；一次只允许创建一个正式 TaskRun。上一个年度成功并通过逐批对账后，才允许创建下一个。
- TaskRun 必须通过 `ManualActionCommandService -> DatasetActionResolver -> TaskRun` 正式主链创建，`action_key=express.maintain`、`time_input.mode=range`、`filters={}`；禁止直接写业务表或绕过 planner。
- 本轮不部署、不迁移、不改代码/API/Definition，不创建 schedule，不额外调用 Tushare 做第二遍源端扫描。

#### 20.8.2 每批执行前门禁

- 当前部署包含既有 Express Definition、planner、request builder、source client、normalizer 和 immutable writer；目标 migration、HDD placement 与服务状态正确。
- 全系统没有 queued/running/canceling TaskRun，且不存在 `express.maintain` schedule。
- HDD 可用空间至少覆盖 512 MiB 操作预留；WAL 所在 SSD 可用空间至少覆盖 2 GiB 操作预留。
- Definition 仍为 33 个显式 source fields、`page_limit=5000`、`fetch_concurrency=1`、`max_units_per_execution=366`。
- 正式 resolver 只读预规划证明年度区间 unit 数、首尾日期、无重叠和无缺口；预规划不创建 TaskRun、不调用 Tushare。

#### 20.8.3 逐批对账公式

每个年度 TaskRun 必须同时满足：

1. `status=success`、`unit_done=unit_total`、`unit_failed=0`。
2. `unit_count_with_pagination=unit_total`、`short_page_unit_count=unit_total`、`total_rows_merged=rows_fetched`、`total_page_count>=unit_total`；多页 unit 必须最终出现短页，不设置任意页数截断。
3. `rows_fetched = rows_normalized_before_dedupe + rows_rejected`，成功批次必须 `rows_rejected=0` 且 reject reason/sample 为空。
4. `rows_normalized_before_dedupe = rows_written + rows_deduplicated`；完全相同源行允许去重，同身份不同内容必须失败。
5. `rows_written = rows_inserted_new + rows_matched_existing`；年度目标表后置行数等于前置行数加 `rows_inserted_new`，也等于本批 `rows_written`。
6. 年度目标表 `count(*)`、`count(distinct source_entity_key)` 和三元业务键唯一数一致；`ts_code/ann_date/end_date/source_entity_key` 无空值，窗口外行数不变。

源端行数、分页和请求次数只使用正式 TaskRun 的运行诊断；目标表使用有界年度只读 SQL 核验。禁止为对账再请求一遍 Tushare。2025 年已存在的 `2025-04-08` 事实由本批 `rows_matched_existing` 自然验证，不单独重跑。

#### 20.8.4 失败与恢复

- 任一 TaskRun 失败、取消、出现 reject、分页失败、身份冲突、范围回退或写后核对不一致，立即停止后续年度。
- 每个自然日独立提交；年度任务中途失败时保留此前成功日期，不删除、不覆盖、不清表。
- 修复后重试同一年度完整区间；已完成日期通过 `rows_matched_existing` 幂等核对，失败日期及其后续日期继续执行。
- `write.immutable_fact_conflict`、`write.immutable_scope_regression` 或缺字段错误必须人工审计源端样本，禁止自动忽略。
- 若执行期间出现其他系统任务，完成当前年度并对账后暂停创建下一年度，待开放队列清空再继续。
- 数据清理、人工改表和 M4c schedule 均不属于 M4b，必须另行授权。

#### 20.8.5 实际执行与验收证据

M4b 于 2026-08-11 使用已部署版本 `55a460713725c50d6f33492f68a26b772f068336` 执行。P0 重新核验 migration `20260811_000132`、三项服务、Definition、空执行队列、零 Express schedule，以及表和四个索引的 HDD placement 后，才创建 2010 年先导 TaskRun。2010 年完整对账通过后，后续年度严格从旧到新串行；执行期间出现其他系统任务时，完成当前年度对账后等待开放队列清零，再创建下一年度任务。

| TaskRun | 窗口 | unit/页 | 读取/写入 | 新增 | 匹配既有 |
| ---: | --- | ---: | ---: | ---: | ---: |
| 7957 | 2010 | 365 | 726 | 726 | 0 |
| 7959 | 2011 | 365 | 1,199 | 1,199 | 0 |
| 7961 | 2012 | 366 | 1,443 | 1,443 | 0 |
| 7962 | 2013 | 365 | 1,594 | 1,594 | 0 |
| 7963 | 2014 | 365 | 1,479 | 1,479 | 0 |
| 7964 | 2015 | 365 | 1,633 | 1,633 | 0 |
| 7965 | 2016 | 366 | 1,749 | 1,749 | 0 |
| 7968 | 2017 | 365 | 1,910 | 1,910 | 0 |
| 7969 | 2018 | 365 | 2,323 | 2,323 | 0 |
| 7970 | 2019 | 365 | 2,256 | 2,256 | 0 |
| 7974 | 2020 | 366 | 2,280 | 2,280 | 0 |
| 7975 | 2021 | 365 | 1,807 | 1,807 | 0 |
| 7976 | 2022 | 365 | 1,644 | 1,644 | 0 |
| 7977 | 2023 | 365 | 1,609 | 1,609 | 0 |
| 7978 | 2024 | 366 | 1,579 | 1,579 | 0 |
| 7979 | 2025 | 365 | 1,514 | 1,500 | 14 |
| 7980 | `2026-01-01..2026-08-10` | 222 | 1,226 | 1,226 | 0 |
| **合计** | `2010-01-01..2026-08-10` | **6,066** | **27,971** | **27,957** | **14** |

最终正式 TaskRun 诊断和目标表只读对账证明：

- 17/17 TaskRun 均为 `success`，`unit_done=unit_total`，合计 `unit_failed=0`；
- 每个自然日都在第一页短页结束，实际 `total_page_count=6,066`、`short_page_unit_count=6,066`、`multi_page_unit_count=0`、`total_retry_count=0`，因此本轮实际 Tushare 页面请求数为 6,066；
- `rows_fetched=rows_written=27,971`，`rows_rejected=0`、`rows_deduplicated=0`、TaskRun issue 为 0；
- `rows_inserted_new=27,957`、`rows_matched_existing=14`。2025 年原有 14 行全部自然匹配，没有重复插入；
- 目标表最终为 27,971 行，`count(distinct source_entity_key)` 和三元业务键唯一数也均为 27,971，必填字段缺失 0、回补窗口外记录 0；实际记录的 `ann_date` 为 `2010-01-05..2026-08-08`，而 6,066 个请求 unit 已完整覆盖批准窗口内的每个自然日；
- P0 执行前 HDD/SSD 可用空间分别为 341,166,731,264 / 17,113,653,248 bytes，最终复核分别为 341,149,868,032 / 17,196,929,024 bytes，始终高于 512 MiB / 2 GiB 门禁。水位变化包含同期系统任务和 PostgreSQL 共享 WAL/checkpoint 影响，不归因于 Express 单一数据集；
- 最终三项服务仍为 active，`express.maintain` schedule 仍为 0。M4b 没有部署、migration、代码/API/Definition 修改、额外源端扫描或直接业务表写入。

M4b 至此完成。自动更新频率、cron 时间和 schedule 创建仍属于独立 M4c，未在本轮启动。
