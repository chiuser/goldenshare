# 公募基金 B4：基金规模（`fund_share`）LLD v1

状态：**B4-FS-M3 已通过：生产 migration、真实 HDD 路径、正式 TaskRun `#7556` 首次最小同步及完整对账均已闭环。`2026-07-07` 的 source/accepted/written/current/observation 均为 1,673，reject 0；未创建自动任务、probe、workflow，也未执行历史回补。**
设计日期：2026-08-07
上游接口：Tushare `fund_share`
源文档：[基金规模数据](../sources/tushare/公募基金/0207_基金规模数据.md)（doc_id=207）
发现审计：[基金规模接入发现审计](fund-share-onboarding-discovery-audit.md)
总计划：[公募基金九数据集接入总览与分批推进计划](public-fund-nine-dataset-onboarding-program-plan-v1.md)

## 1. 结论与范围

B4 先只实现 `fund_share`，不同时实现 `fund_div`。`fund_share` 是按自然日发布的基金份额/规模源事实，不是基金主数据快照，也不是基金净值。生产主链固定为：

1. 运营输入单个自然日，或自然日起止区间；区间在执行层展开为逐自然日 unit。
2. 每个日期 unit 只发送一个 `trade_date`，不发送 `market`、`ts_code` 或基金池过滤。
3. 每页显式请求全部六个 source fields，使用 `offset/limit` 分页，短页结束且不设最大页数。
4. 每个日期 unit 独立归一化、校验、写入和提交；非空 unit 以该日期为作用域原子替换 current，并保留 observation 观察版本。
5. 自然日零行是合法成功 no-op，不删除已经存在的数据，也不触发日期完整性缺失告警。
6. 两张 direct-serving 表及全部索引显式落 `gs_raw_cold_hdd`；PostgreSQL WAL 继续使用现有 SSD。

B4-FS-M1 的代码范围不包含：`fund_div`、历史回补、生产迁移、首次生产同步、自动创建 schedule、workflow、probe、Lake/Dagster 或业务查询 API。生产迁移与首次最小同步随后经独立授权在 B4-FS-M3 完成；其余边界保持不变，实际 cron 时间和历史回补起止范围继续延后。

## 2. 设计依据与已验证事实

### 2.1 源端请求与分页

项目 connector 的真实请求已证明：

| 场景 | 结果 | 设计结论 |
| --- | --- | --- |
| 无业务参数、显式六字段 | 返回 2,000 行并命中单次上限 | 不能把无参返回当成完整快照。 |
| 单日 `20260616` | 1,664 行，`limit=1000` 为 `1000/664` | 单日 point 可完整分页。 |
| 单日 `20260617` | 1,652 行，`limit=1000` 为 `1000/652` | 单日 point 可完整分页。 |
| 两日区间 | 3,316 行，`1000/1000/1000/316` | 区间请求本身支持分页。 |
| 七个自然日区间 | 8,393 行，`1000`×8+`393` | 分页并集与七个 point 行多重集完全一致。 |
| 周六 `20260704` | 0 行 | 零行是合法源状态。 |
| 周日 `20260705` | 6 行，全部为 O | 必须按自然日展开，不能用交易日历裁剪。 |

逐日 unit 不是为了规避一个已经被证明不存在的“区间无法分页”问题，而是为了把内存、事务、失败回滚和单日补录限制在一个自然日。

### 2.2 输入参数决策

| Tushare 参数 | 源端能力 | Goldenshare 决策 |
| --- | --- | --- |
| `ts_code` | 可选对象过滤；单代码无日期请求也会命中 2,000 行上限 | 不进入 input model，不用于主维护请求。 |
| `trade_date` | 可请求一个自然日 | 作为每个执行 unit 唯一业务参数。 |
| `start_date/end_date` | 可请求日期区间，已验证可分页 | 只作为运营 range 意图；resolver 展开后不透传源端。 |
| `market` | 可选，实测接受 O | 不进入 input model；主请求不传，避免裁剪全市场。 |
| `limit/offset` | 支持分页 | 由 source client 统一追加，运营不可编辑。 |
| `fields` | 可显式选择输出列 | 由 Definition 固定六字段，每页必须携带。 |

### 2.3 字段契约

Definition 必须按以下顺序显式请求并保存全部字段：

```text
ts_code, trade_date, fd_share, total_share, fund_type, market
```

不传 `fields` 的当前默认返回实际包含五列，源文档与 MCP 元数据又只列出三列；三者存在差异，因此生产代码不得依赖默认字段。七日样本中 `total_share` 全部为空，`fund_type` 有 473 行为空；它们仍必须逐页请求、显式建列和原值保存。

`fd_share` 的真实样本最大绝对值为 `8,960,544`，小数位最多为 4；设计使用 `NUMERIC(30,10)`，避免浮点改写源内容，并为后续数值增长和更多小数位保留余量。

### 2.4 source fields 端到端映射

| Source field | 源类型/含义 | 归一化 | ORM/DDL | Null 口径 | 身份/内容散列 |
| --- | --- | --- | --- | --- | --- |
| `ts_code` | str，基金代码 | 源值保真；仅派生身份时 trim + upper | `TEXT NOT NULL` | 拒绝空值 | 实体键 + 内容散列 |
| `trade_date` | str，交易（变动）日期 | `YYYYMMDD` -> `date` | `DATE NOT NULL` | 拒绝空值；必须等于 unit anchor | 实体键 + 内容散列 + scope |
| `fd_share` | float，基金份额（万） | 精确 Decimal | `NUMERIC(30,10) NOT NULL` | 拒绝空值 | 内容散列 |
| `total_share` | float，合计份额（万） | null 或精确 Decimal | `NUMERIC(30,10) NULL` | 允许 null，字段本身不可缺失 | 内容散列 |
| `fund_type` | str，基金类型 | 原值保真 | `TEXT NULL` | 允许 null，字段本身不可缺失 | 内容散列 |
| `market` | str，市场 | 原值保真，不设枚举 | `TEXT NOT NULL` | 拒绝空值 | 内容散列 |

`source_content_hash` 必须使用六个归一化后 source fields 的规范序列化结果；不得只散列非空字段，也不得因 `total_share` 当前全空而把它排除。

### 2.5 全市场与身份

七日样本包含 SH/SZ/O=`4,766/3,584/43`。O 是当前源端真实范围的一部分，不是可选市场。主请求不传 `market`，不得按 ETF 池、代码后缀或 `fund_basic` 关联结果过滤。

源实体固定为 `(ts_code, trade_date)`。已验证样本中该组合完全唯一，但实现仍必须在归一化和数据库两层 fail-closed，不能把样本唯一性当成永久保证。

## 3. 三层时间语义

| 层 | 固定口径 |
| --- | --- |
| 时间输入语义 | 支持 `point` 的 `trade_date`，以及 `range` 的 `start_date/end_date`；均为自然日。 |
| 执行 / unit 语义 | point 生成一个日期 unit；range 展开为闭区间内每个自然日一个 unit。每个 unit 只向源端发送 `trade_date=YYYYMMDD`。 |
| freshness / audit 语义 | `date_axis=natural_day`，但 `bucket_rule=not_applicable`、`audit_applicable=false`。它表示不要求每天都有源记录，不表示不支持日期输入。 |

`observed_field=trade_date` 用于展示最近源事件日；不把它解释成连续日期覆盖率。最新源事件日和最近成功 TaskRun 可以展示，但不得由零行自然日推导“缺数”。

## 4. `DatasetDefinition` 契约

在 `src/foundation/datasets/definitions/public_fund.py` 新增 `fund_share`，并由现有 registry 与 domain guard 注册。固定配置如下：

| 区域 | 配置 |
| --- | --- |
| identity | `dataset_key=fund_share`；domain=`public_fund / 公募基金`；中文名“基金规模” |
| source | provider=`tushare`；api=`fund_share`；显式六字段；`base_params={}` |
| date model | `date_axis=natural_day`；`bucket_rule=not_applicable`；`window_mode=point_or_range`；`input_shape=trade_date_or_start_end` |
| action | `maintain` 支持 manual / schedule / retry；允许 point/range；无 filters |
| planning | `offset_limit`；`page_limit=2000`；`concurrency=1`；无最大页数；选择新的自然日 point unit builder |
| request | 复用 `_daily_params`，每个 unit 只生成 `trade_date`；不得使用会生成 `start_date/end_date` 的 range request builder |
| normalization | `trade_date` 转 `date`；`fd_share/total_share` 转精确 Decimal；row transform 只生成派生身份字段，不改写六个 source fields |
| quality | required=`ts_code,trade_date,fd_share,market,source_entity_key`；`unit_date_field=trade_date`；`batch_unique_key_fields=(source_entity_key,)` |
| storage | `write_path=serving_observed_fact_scope_refresh`；current + observation；无 raw/std/EAV/JSON |
| observability | `observed_field=trade_date`；`audit_applicable=false`；freshness=`EVENT_RUN_TRACE` |

不得暴露 `market`、`ts_code`、`fund_type` 为运营过滤条件。Tushare 接口“支持某个可选参数”不等于 Goldenshare 应允许它替换全市场 current。

## 5. unit planner 与请求链

### 5.1 新增最小共享 unit builder

当前 generic planner 对 `natural_day + not_applicable` 的 range 不会逐日展开。B4 新增一个显式 opt-in 的通用 builder，例如：

```text
build_natural_day_point_units(request, definition)
```

它只处理选择了该 builder 的 Definition：

- point：校验一个自然日，生成一个带 anchor 的 unit；
- range：校验闭区间，调用现有 `_expand_natural_dates`，每天生成一个带 anchor 的 unit；
- none/snapshot：拒绝；
- 不查询交易日历，不跳过周末或节假日；
- unit 按日期升序稳定生成，并保持并发 1。

它应在 `_CUSTOM_UNIT_BUILDERS` 中显式注册。不得修改 generic fallback，否则会改变其他 `natural_day + not_applicable` 数据集的执行语义。

### 5.2 请求与分页

每个 unit 复用既有 `_daily_params`，得到：

```python
{"trade_date": "YYYYMMDD"}
```

`DatasetSourceClient` 继续负责：

1. 每一页都携带 Definition 的六个 `fields`；
2. offset 依次为 `0, 2000, 4000, ...`；
3. 只有返回行数 `< 2000` 才结束；
4. 任一页异常使整个日期 unit 失败；
5. 不增加任意 `max_pages`，也不把 2,000 误当成日期行数上限。

当前 source client 会在 unit 内聚合全部页。单日样本约 1,700 行、约 0.20 MB，B4 可继续使用；M2 必须用明显高于当前样本的单日 fixture 验证内存和事务边界。若未来单日规模越过验收门禁，应另立页流式 contract，不能在 B4 中提前改写通用 client。

## 6. 归一化、身份与完整性

### 6.1 身份派生

在 `src/foundation/datasets/definitions/public_fund_contracts.py` 增加字段 tuple 与纯身份函数，在 `src/foundation/ingestion/row_transforms.py` 增加 normalizer 动态加载的 row transform。不得把 B4 逻辑写进 normalizer 主链。

派生规则：

1. `ts_code` 仅在计算身份时去首尾空格并转大写；源列保存原值。
2. `trade_date` 使用 normalizer 已归一化的 ISO 日期。
3. `source_entity_key = "share:" + sha256(normalized_ts_code + "|" + trade_date)`。
4. `identity_basis = "ts_code_trade_date"`。
5. `source_content_hash` 由 writer 对全部六个 source fields 的规范内容计算。

若 `ts_code` 或 `trade_date` 为空，直接 reject；不得回退到内容哈希充当实体身份。

### 6.2 日期与唯一性门禁

每行实际 `trade_date` 必须等于 plan unit 的 anchor。以下任一情况都使非空日期 unit 整体失败并回滚：

- 任一 normalizer reject；
- 缺少六个 source fields 中任一字段，即使它的值允许为 null；
- required 字段为空；
- 两行具有相同 `source_entity_key`，无论内容相同还是不同；
- observation 或 current 持久化数量与预期不一致；
- scope 不是单一 `trade_date`；
- 任一页失败。

错误码至少覆盖：

| 错误码 | 含义 |
| --- | --- |
| `write.fact_rows_rejected` | 非空 unit 含 normalizer reject。 |
| `write.fact_scope_invalid` | unit anchor 缺失、字段不匹配或出现多个日期。 |
| `write.fact_duplicate_record` | 同一批出现重复实体键或内容冲突。 |
| `write.fact_persistence_incomplete` | observation/current 持久化计数不完整。 |
| `write.source_field_missing` | 请求契约中的 source field 未出现。 |
| `write.source_entity_key_missing` | 派生实体键缺失。 |

新增错误码须同步维护 `docs/operations/dataset-error-codebook.md`，并有稳定测试断言。

## 7. 写入协议：观察型时序事实按日期作用域替换

### 7.1 为什么不能复用 B0 snapshot writer

`serving_observed_snapshot_refresh` 的语义是“一个 unit 代表整张 current 的完整快照”，会删除并重建整张 current，且空结果必须失败。`fund_share` 的一个 unit 只代表一个自然日；直接复用会删除其他日期，属于确定性数据破坏。

B4 新增显式 opt-in write path：

```text
serving_observed_fact_scope_refresh
```

它只允许用于“一个 unit 对应一个日期作用域”的 direct-serving 数据集，不改变 B1/B2/B3 snapshot writer。

### 7.2 非空日期 unit

在 executor 已有的单 unit 事务内，writer 必须按顺序完成：

1. 校验 reject、source fields、实体键、内容散列、批内唯一性和 unit 日期；
2. current DAO 对“表 + 日期作用域”取得 PostgreSQL transaction-scoped advisory lock；
3. observation DAO 按 `(source_entity_key, source_content_hash)` upsert：首次写入设置 first/last，重复观察只推进 last；
4. current DAO 删除 `trade_date = unit_date` 的现有 current 行；
5. 插入本 unit 的全部 current 行，并验证数量；
6. 不在 DAO/writer 内 commit，由 executor 在两表全部成功后统一提交。

按日期完整替换而不是只 upsert incoming keys，才能在源端一个非空日期后续少了一条记录时，把已经撤回的旧行从 current 移除，同时在 observation 保留旧版本。

advisory lock 的 key 必须由稳定的“current 表名 + ISO 日期”确定，并仅维持当前事务。它防止两个相同日期任务交叉 delete/insert；不同日期仍可独立执行。SQLite 单测可使用串行 no-op，PostgreSQL 集成测试必须验证锁和回滚。

### 7.3 空日期 unit

满足 `fetched=0, normalized=0, rejected=0` 时：

- 返回成功 no-op；
- current/observation DAO 都不得执行删除或写入；
- 计数为 0，并保留 TaskRun 的成功运行事实；
- 不因为一次空响应静默擦除该日期过去已经观察到的数据。

最后一条是故障安全边界：全空既可能是真实零事件，也可能是源端暂时异常，系统不能自动区分。若需要确认某个过去非空日期已经被上游整体撤回，必须经过单独的只读核验和明确修正授权，不能由日常同步自动删除。

### 7.4 幂等与版本语义

| 场景 | current | observation |
| --- | --- | --- |
| 首次同步日期 D | 保存 D 的完整当前集合 | 创建每个实体内容版本 |
| 相同内容重复同步 | 集合不变，`observed_at` 前进 | 不增行；`first_observed_at` 不变，`last_observed_at` 前进 |
| 同一实体内容变化 | D 中只保留新内容 | 新旧内容版本都保留 |
| 非空新快照少一实体 | 撤回实体从 D 的 current 消失 | 旧 observation 保留 |
| 空结果 | 不变 | 不变 |
| 任一步骤失败 | 整个 D 回滚 | 整个 D 回滚 |

### 7.5 shared contract linter

Definition builder/linter 对新 write path 必须验证：

- raw/std DAO 和表均为空；
- current/observation DAO 和表均存在；
- `quality.unit_date_field` 存在，且同时属于 source/date/required fields；
- date model 支持 point/range，planner 每 unit 只有一个日期；
- `batch_unique_key_fields=(source_entity_key,)`；
- conflict columns 固定为 `(source_entity_key, source_content_hash)`；
- no-time snapshot Definition 不得选择该 write path。

这使共享能力由契约选择，而不是由 `dataset_key == "fund_share"` 分支驱动。

## 8. ORM、DAO 与物理表

### 8.1 表与列

新增：

- `core_serving.fund_share_current`
- `core_serving.fund_share_observation`

两表均使用显式列，不保存 raw JSON/EAV：

| 列 | current | observation | 类型与约束 |
| --- | --- | --- | --- |
| `source_entity_key` | 是 | 是 | `TEXT NOT NULL` |
| `source_content_hash` | 是 | 是 | `VARCHAR(64) NOT NULL` |
| `identity_basis` | 是 | 是 | `TEXT NOT NULL` |
| `ts_code` | 是 | 是 | `TEXT NOT NULL`，源值保真 |
| `trade_date` | 是 | 是 | `DATE NOT NULL` |
| `fd_share` | 是 | 是 | `NUMERIC(30,10) NOT NULL` |
| `total_share` | 是 | 是 | `NUMERIC(30,10) NULL` |
| `fund_type` | 是 | 是 | `TEXT NULL`，不设枚举 |
| `market` | 是 | 是 | `TEXT NOT NULL`，原值保真 |
| `observed_at` | 是 | 否 | `TIMESTAMPTZ NOT NULL` |
| `first_observed_at` | 否 | 是 | `TIMESTAMPTZ NOT NULL` |
| `last_observed_at` | 否 | 是 | `TIMESTAMPTZ NOT NULL` |
| `created_at/updated_at` | 是 | 是 | 既有审计时间戳 |

两表主键均为 `(source_entity_key, source_content_hash)`。current 再建唯一索引 `(source_entity_key)`，作为逻辑实体唯一性的数据库防线；observation 不建该唯一索引，以允许同一实体保留多个内容版本。

### 8.2 索引

除 PK/唯一索引外，至少创建：

```text
fund_share_current:
  (trade_date DESC, market, ts_code)
  (ts_code, trade_date DESC)

fund_share_observation:
  (source_entity_key, last_observed_at DESC)
  (trade_date DESC, market, ts_code)
  (ts_code, trade_date DESC, last_observed_at DESC)
```

DAO factory 注册 current 与 observation。observation 继续复用 `ObservedSnapshotDAO.record_observations`；current 在同一 DAO 类型上增加通用 `replace_current_scope`，参数显式包含 scope field/value，不新增 `FundShareDAO` 或数据集专用 SQL 类。

### 8.3 不分区的决定

B4 两表不分区，原因是正确性而不是省事：

1. PostgreSQL 分区表的 PK/唯一约束必须包含分区键；当前实体/版本 contract 是 `(source_entity_key, source_content_hash)`，current 还要求 `source_entity_key` 全局唯一。
2. 强行按 `trade_date` 分区会迫使 observation DAO 的 conflict contract 扩大，或失去数据库全局唯一防线。
3. 当前单日约 1,700 行，非分区 HDD 表足以支撑日常同步；尚无查询或维护证据证明必须承担分区契约复杂度。
4. 历史总量尚未做逐年只读估算，不能用猜测推翻已经清晰的身份语义。

若后续真实容量和查询证据要求分区，应另立迁移方案并重新审计唯一键、DAO `ON CONFLICT`、所有查询消费者和回滚路径；不得在 B4 实施中临时改变。

### 8.4 migration 与 HDD

LLD 编写时真实 Alembic head 为 `20260806_000127`；编码前必须重新执行 head 检查，migration 的 `down_revision` 只能接实施当时的真实 head。

upgrade 必须：

1. 确认数据库为 PostgreSQL；
2. 在创建任何对象前验证 `gs_raw_cold_hdd` 存在；
3. 两张表、PK/unique 和全部二级索引显式指定该 tablespace；
4. 任一步失败则整个 migration 失败，不回退默认 SSD；
5. migration 不创建任务、不执行同步、不改 `pg_wal`。

downgrade 不自动删除两张源事实表，应显式拒绝破坏性降级。确需回退由运营另行审批逐表方案。

## 9. Ops、自动任务与前端契约

### 9.1 Catalog 与手动任务

在现有 `public_fund / 公募基金` 分组新增：

```text
fund_share / 基金规模 / order=50
```

手动维护由 Definition 自动展示自然日 point/range。界面不展示 `market`、`ts_code` 或其他 filters；API 后端同样拒绝这些未声明输入。不得新增前端 dataset-key 字段白名单。

不加入任何 workflow；不提供 probe 或 `schedule_probe_fallback`；不自动创建 schedule。

### 9.2 消除 `trigger_day_point` 特殊白名单

当前 `trigger_day_point` 同时散落在 `TaskRunCommandService`、`OperationsScheduleService` 和前端 action-key 判断中，并写死 `news/major_news`。B4 不能再把 `fund_share` 追加到这些列表。

新增一个 Ops 内部 `DatasetScheduleTimePolicyResolver`，以 Definition 的 action capability 为唯一事实源，供以下消费者共同使用：

1. Catalog 的 `ScheduleAutomationCapabilityResolver`；
2. schedule create/update 的 `OperationsScheduleService`；
3. schedule 触发 TaskRun 时生成时间输入的 `TaskRunCommandService`；
4. API `AutomationCapabilityResponse`；
5. 前端自动任务表单和回显。

Definition action 增加声明式 schedule time policy。B4-FS-M1 为 `fund_share.maintain` 实现的基础 cron 取时能力为：

```text
policy = trigger_day_point
schedule_types = cron
explicit_time_input = forbidden
generated_time_mode = point
```

含义是：cron 每次触发时，后端可以把该次触发所在的 `Asia/Shanghai` 自然日生成 point 输入；运营不保存固定日期或日期区间。`once` 不使用动态策略，仍由运营选择一个固定 point/range。

该能力只证明“系统能正确生成触发日 point”，不等于已经证明源端在触发当天的哪个时点发布完整数据，也不能自动发现对过去日期的延迟修订。当前源文档没有发布 SLA，单次只读响应也无法证明发布时间。因此：

- M1 可以实现并测试该 capability contract；
- M3 不创建 cron；
- 首个生产 cron 创建前，必须做跨多个自然日、多个时点的只读观察，拍板执行时点，以及是否需要额外的滚动修订任务；
- 若证据要求“前一自然日”或“滚动 N 日”，必须先把相对日期策略作为声明式 capability 补入本文和代码，再允许建任务，禁止在 schedule params 或前端临时拼日期。

API 必须返回上述固定能力；前端只渲染 capability，自动隐藏并清空 cron 的显式日期输入。schedule 创建和运行时都再次由同一 resolver 校验，不能只信任 UI。

本次改造同时把 `news/major_news` 的既有能力迁入相同 Definition 契约，并删除：

- `TRIGGER_DAY_POINT_TARGET_KEYS`；
- 两个后端 `_supports_trigger_day_point_policy` 数据集白名单；
- 前端 `actionSupportsTriggerDayPointPolicy` 白名单。

迁移必须保持 news/major_news 现有 cron 行为和最小 3 分钟的 interval 防护。`fund_share` 的具体 cron 表达式暂不创建；普通 daily/weekly/monthly cron 均由现有 schedule 机制承载，若使用 `*/N` 分钟型 cron，仍受既有最小间隔限制。该 contract 改造不得重新配置、改写或删除现有 schedule 记录；发布验收应在部署前后分别留存 schedule 配置快照，并运行只读 capability 审计。`next_run_at` 会随 scheduler 正常推进，不能用静态相等作为正确性条件；应核对 cron、启停、calendar policy 等持久化意图未被发布过程改写。

### 9.3 freshness、cards 与审计

- freshness policy 注册 `fund_share: EVENT_RUN_TRACE`；
- 数据卡 target/serving 均为 `core_serving.fund_share_current`，raw 为空；
- 展示最近源 `trade_date` 与最近成功 TaskRun，不计算预期连续日期或 lag 缺口；
- 不进入 date completeness audit/schedule；
- snapshot/card model registry 必须发现 current ORM。

## 10. 配置项审计

| 配置/契约 | 固定值或来源 | 持久化位置 | 消费者 | 生效方式与运维可见性 |
| --- | --- | --- | --- | --- |
| source fields | 六字段固定 tuple | Definition 代码 | source client、normalizer、writer | 随部署生效；Catalog 不允许编辑 |
| page limit | 2,000 | Definition 代码 | source client | 随部署生效；无 env 覆盖 |
| concurrency | 1 | Definition 代码 | executor/planner | 随部署生效 |
| unit builder | natural-day point fan-out | Definition 代码 | planner | 随部署生效 |
| write path | scoped observed fact refresh | Definition 代码 | writer/linter/DAO | 随部署生效 |
| tablespace | `gs_raw_cold_hdd` | migration DDL | PostgreSQL | migration 时校验；通过系统目录审计 |
| WAL | 现有集群配置 | PostgreSQL 实例 | 全部数据库 | B4 不改；继续位于 SSD |
| schedule time policy | cron trigger day -> point | Definition + capability API | Catalog、schedule service、TaskRun、前端 | 系统默认不可编辑；部署后生效 |
| 实际 cron/once | 暂无 | 后续 Ops schedule 表 | schedule runner | 运营后续手工创建；B4 不 seed |

B4 不新增环境变量、Settings 或页面常量。若实施中发现必须新增配置，须先回到本节补全来源、消费者、依赖、生效和门禁，不得散落实现。

## 11. 代码影响面与文件落点

### 11.1 预计新增

- `src/foundation/models/core_serving/fund_share_current.py`
- `src/foundation/models/core_serving/fund_share_observation.py`
- 一条接真实 head 的 Alembic migration
- `tests/test_public_fund_b4_fund_share_dataset.py`
- `tests/test_public_fund_b4_migration.py`

### 11.2 预计修改

- Definition/contract/transform：`definitions/public_fund.py`、`public_fund_contracts.py`、`definitions/__init__.py`、`row_transforms.py`
- planner：unit builder registry 与自然日展开测试
- writer/DAO：writer 路由、新 scoped fact writer、`ObservedSnapshotDAO.replace_current_scope`
- model/DAO registry：`core_serving/__init__.py`、`all_models.py`、DAO factory
- definition builder/linter、error codebook
- Ops catalog、freshness mapping、schedule policy resolver/capability schema/query/service/runtime
- 前端 API type 与自动任务页面：只消费新的 capability，并删除 action-key 白名单
- 对应 definition、writer、Ops API、schedule、frontend、cards、migration 测试

不修改 Tushare connector、source client、biz、legacy `platform/operations`、Lake/Dagster，也不新增基金领域通用框架。

### 11.3 `DatasetDefinition` 消费者审计

| 消费者 | 当前代码权威 | B4 预期行为与门禁 |
| --- | --- | --- |
| manual actions | `src/ops/queries/manual_action_query_service.py`、`src/ops/services/manual_action_service.py` | 自动派生 point/range，无 filters；非法时间或额外参数 422。 |
| Ops Catalog | `src/ops/catalog/dataset_catalog_views.py`、`src/ops/queries/catalog_query_service.py` | 公募基金 order=50，返回 date model、freshness 和 automation capability。 |
| workflow | 当前 workflow definitions/registry | 不新增 `fund_share.maintain` step，并用精确负向测试锁定。 |
| resolver / unit planner | Dataset action resolver、`DatasetUnitPlanner`、custom unit builders | 运营 range 归一化为逐自然日 point unit；不改变 generic fallback。 |
| request builder | `src/foundation/ingestion/request_builders.py` | 每 unit 只产生 `trade_date`，无 market/ts_code/start/end。 |
| source client | 当前 `DatasetSourceClient` | 复用 offset/limit、逐页 fields、短页结束；本轮不改代码。 |
| normalizer / writer | normalizer、row transforms、writer registry、executor | 同日/唯一/字段门禁；空日 no-op；非空日单事务 scoped refresh。 |
| freshness | `src/ops/queries/freshness_query_service.py` 与 freshness registry | `EVENT_RUN_TRACE`，展示事件日和运行，不计算连续日期 lag。 |
| dataset cards | dataset projection、`src/ops/api/dataset_cards.py` | target/serving 指向 current，raw 为空，模型 registry 可解析。 |
| status snapshot rebuild | `src/ops/services/operations_dataset_status_snapshot_service.py`、`src/cli_parts/ops_handlers.py` | rebuild 可纳入 fund_share，且使用 Definition projection，不自行拼字段。 |
| date completeness | date completeness rule/query/run/schedule services | `audit_applicable=false`，不能创建 run 或 schedule。 |
| 自动任务 | capability resolver、schedule service、TaskRun service、Catalog schema/API | calendar policy 由 Definition 单一事实派生，create/update/runtime 一致验证。 |
| 前端时间控件 | `frontend/src/pages/ops-v21-task-auto-tab.tsx` 与共享 API types | 手动 point/range；cron 固定触发日策略；无 action-key 白名单。 |
| 测试与文档 | registry、Ops API、writer、migration、frontend、docs tests | 正/反向测试与本 LLD 账本逐项闭环，旧 news/major_news 行为回归。 |

## 12. 硬口径到代码与测试的对账表

| ID | 硬口径 | 代码落点 | 正向测试 | 反向测试 |
| --- | --- | --- | --- | --- |
| B4-FS-001 | 六字段逐页显式请求、全部保存 | Definition、source client、ORM | 多页每页 fields 相同；六列入两表 | 默认 fields 或缺一字段则失败 |
| B4-FS-002 | 全市场 SH/SZ/O，无 filters | Definition/input/request | O 样本正常保存 | market/ts_code 输入被拒绝 |
| B4-FS-003 | range 按每个自然日展开 | unit builder | 跨周末 range 含每天 unit | 不得查询交易日历或发送 start/end |
| B4-FS-004 | offset/limit、短页结束、无 max pages | source client + Definition | 2,000/2,000/short 三页 | 满页后不得提前停止 |
| B4-FS-005 | unit 日期与行日期一致 | normalizer quality | 同日全部通过 | 混入其他日期整 unit reject |
| B4-FS-006 | 实体 `(ts_code,trade_date)` 唯一 | transform、batch gate、unique index | 不同日期/代码并存 | 同实体同内容或不同内容均失败 |
| B4-FS-007 | 非空日按日期原子替换 current | scoped writer/DAO | 变更/撤回正确反映 current | 不得删除其他日期 |
| B4-FS-008 | observation 保留版本、重复幂等 | writer/ObservedSnapshotDAO | first/last 与版本语义正确 | 失败不得留下半写 observation |
| B4-FS-009 | 空日成功 no-op | writer | 0/0/0 成功 | 不得 delete/insert 或清除旧日数据 |
| B4-FS-010 | 同日期并发串行 | advisory lock/transaction | PostgreSQL 并发测试 | 不得交叉覆盖或 DAO 内 commit |
| B4-FS-011 | HDD 表和全部索引、WAL 不动 | migration | 系统目录逐 relation 检查 | tablespace 缺失 migration 先失败 |
| B4-FS-012 | 公募基金 Ops，手动 point/range | Catalog/API/UI | order=50、日期控件正确 | 无 filter/workflow/probe |
| B4-FS-013 | cron 触发日由 capability 驱动 | Definition、Ops resolver/API/runtime/UI | cron 生成触发日 point | 删除 key 白名单；显式 cron 日期被拒绝 |
| B4-FS-014 | 事件型 freshness，无连续日审计 | freshness/cards/audit | 展示最新事件日/运行 | 周末零行不产生 completeness 缺口 |

## 13. 验证与验收

### 13.1 B4-FS-M1：实现与本地门禁

本阶段已按以下顺序完成：

1. Definition、unit builder、identity/normalizer；
2. scoped writer/DAO 与 contract linter；
3. ORM、registry、migration；
4. Ops Catalog、freshness、schedule capability 单一事实源和前端消费；
5. 定向单元/集成测试、definition lint、类型检查和文档检查。

本地验收已覆盖：后端 fund_share/B0-B3/Definition/Ops/API/scheduler 定向回归、definition lint、schedule capability audit、前端 `npm run typecheck`、相关 Vitest、`npm run build`、`python3 scripts/check_docs_integrity.py`、Ruff 与 `git diff --check`。PostgreSQL migration/HDD/并发与真实同步验收仍属于 M2，未在 M1 假装完成。

### 13.2 B4-FS-M2：隔离 PostgreSQL

本阶段已在全新本机隔离 PostgreSQL 18.4 集群完成，连接固定为 `127.0.0.1:55407`，未复用历史验收库、未连接生产数据库。验收项如下：

1. application migration，逐张表/索引验证 HDD tablespace 与真实路径；
2. 用真实源同步 `20260704..20260705`，证明零行日和周日 O 数据的逐自然日语义；
3. 再同步一个正常全市场日期（基线可用 `20260707`，当时 1,673 行）；
4. 每个 unit 完成五段对账：源端 fetched、归一化 accepted、写入、reject reason、current/observation 行数与摘要；
5. 相同日期重跑，验证幂等时间戳；用定向 fixture 验证内容变更、非空撤回、空日 no-op 和事务回滚；
6. PostgreSQL 双事务验证同日期 advisory lock，不同日期互不污染；
7. 用代表性字段长度的 10,000 行单日期 fixture 验证多页、单事务和 current scope replacement：峰值 RSS 不超过 512 MiB 且不超过主机 `MemAvailable` 的 10%，单数据库事务不超过 60 秒，单 unit 端到端不超过 120 秒。任一门禁不满足则停止，不缩小源范围。

真实样本行数仅是验收基线，不是永久 SLA。M2 不创建生产任务、不写生产库。

#### 13.2.1 migration 与物理落盘

- 在缺少 `gs_raw_cold_hdd` 的 fail-closed 库中，migration 在创建 B4 表前按预期失败；Alembic head 保持 `20260806_000127`，B4 表数量为 0，没有回退默认 tablespace。
- 在真实验收库和容量验收库中，migration 均到达 `20260807_000128`。两张表、两个主键索引、一个 current 唯一索引和五个二级索引共 10 个 relation，系统目录中的 tablespace 均为 `gs_raw_cold_hdd`，relation path 均位于该 tablespace 路径。
- 隔离 tablespace 指向 `/private/tmp/goldenshare_b4_m2.IEJjql/hdd_tablespace`；集群 `data_directory` 为独立的 `/private/tmp/goldenshare_b4_m2.IEJjql/data`，`pg_wal` 未改为 tablespace 或单独链接。该阶段只验证迁移和 placement contract；生产 M3 后续已确认真实路径为 `/data/disk/postgresql/tablespaces/gs_stk_mins_hdd`，见 13.3.1。
- 首次曾并行启动两个“从零应用全部历史 migration”的隔离库，其中容量库在旧 migration `20260427_000080` 因临时集群 `max_locks_per_transaction` 资源不足而整事务回滚；改为串行应用后成功。故障不发生在 B4 migration，未留下半迁移对象，也不改变生产必须串行、逐库应用 migration 的口径。

#### 13.2.2 真实最小同步与五段对账

每页均显式请求 `ts_code, trade_date, fd_share, total_share, fund_type, market`，请求参数仅含单日 `trade_date` 和 connector 追加的 `limit/offset`；三个日期均由短页结束，无 reject：

| 日期 | 源端 fetched | accepted | written | reject | current | observation | 市场明细 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 2026-07-04 | 0 | 0 | 0 | 0 | 0 | 0 | 合法空自然日，0 行 no-op |
| 2026-07-05 | 6 | 6 | 6 | 0 | 6 | 6 | O=6 |
| 2026-07-07 | 1,673 | 1,673 | 1,673 | 0 | 1,673 | 1,673 | SH=953、SZ=718、O=2 |

源端、归一化 batch、current 与 observation 的 `(source_entity_key, source_content_hash)` 集合一致；从两张目标表六个 source fields 重新计算的内容散列差异均为 0，市场分组行数一致。两次完整执行期间 `fund_share` 的 TaskRun、schedule 和 probe 记录始终为 0。

相同真实快照再次同步后，2026-07-07 的 current/observation 仍各为 1,673 行；observation 的 `first_observed_at` 保持 `2026-08-07 07:26:04.527814+08`，`last_observed_at` 与 current `observed_at` 前进到 `2026-08-07 07:28:04.261759+08`，证明重复执行不制造新版本且观察时间语义正确。

#### 13.2.3 容量、回滚与 advisory lock

- 10,000 行单日期 fixture 通过实际 source client、normalizer、writer、DAO 和数据库事务执行；分页为 `2,000/2,000/2,000/2,000/2,000/0`，offset 为 `0/2000/4000/6000/8000/10000`，六页 fields 与参数契约全部一致。
- fetched/accepted/written/current/observation 均为 10,000，reject 0，内容散列一致；只发生一次业务 commit。数据库事务 2.635 秒、unit 端到端 2.755 秒，峰值 RSS `245,121,024` bytes，均低于 60 秒、120 秒和 512 MiB 门禁；本次 WAL 增量 `20,440,504` bytes，仅作隔离样本，不外推历史回补容量。
- 分别在 observation upsert 后、current scope replacement 后注入故障，两次均返回 `write_failed`，事务前后完整指纹一致，没有半写 observation 或半替换 current。
- 两个真实 PostgreSQL 事务并发写同一日期时，第二个事务在第一个提交前被 transaction-scoped advisory lock 阻塞；提交顺序确定最终 current，observation 保留两个内容版本。不同日期锁互不阻塞。

以上门禁全部通过，B4-FS-M2 不存在需要通过缩小源范围或降低完整性要求规避的问题。

### 13.3 B4-FS-M3：生产首次同步

B4-FS-M3 已于 2026-08-07 按独立授权完成，未把部署、migration、业务同步和自动任务混成一个授权。生产验收如下。

#### 13.3.1 只读预检、版本与物理落盘

- 远程分支为 `dev-interface`，部署 HEAD `2264fbe0` 包含 B4 提交 `0514d6e7`；工作区干净，六个生产服务均为 active，Web 健康检查返回 prod 正常。
- migration 已到 `20260807_000128`。同步前 `fund_share_current` 与 `fund_share_observation` 均为 0 行；活动 TaskRun、活动日期完整性任务、`fund_share` schedule/probe/历史 TaskRun 均为 0。
- 两张表、两个主键索引、一个 current 唯一索引和五个二级索引共 10 个 relation，系统目录均报告 tablespace=`gs_raw_cold_hdd`，relation path 全部位于该 tablespace。
- tablespace 真实路径为 `/data/disk/postgresql/tablespaces/gs_stk_mins_hdd`；`/data/disk` 挂载于 `/dev/vdb`，验收时可用空间 323 GiB。PostgreSQL 主数据目录仍位于根盘 `/dev/vda2`，B4 没有迁移共享 WAL。
- 生产应用数据库角色无权读取 `data_directory` 设置；该只读目录信息改由主机 `findmnt`/路径解析核验，不影响 relation tablespace、业务行数或同步验收结论。

#### 13.3.2 正式 TaskRun 与五段对账

正式同步前先通过生产 connector 做无写入预检，日期固定为 `2026-07-07`：

- 只生成一个 point unit，请求业务参数只有 `trade_date=20260707`；connector 追加 `limit=2000, offset=0`。
- 唯一一页返回 1,673 行，以短页结束；每页显式 fields 均为 `ts_code, trade_date, fd_share, total_share, fund_type, market`。
- accepted=1,673、reject=0、缺字段=0、实体键唯一数=1,673；市场 SH/SZ/O=`953/718/2`。
- source 内容摘要为 `6bd1c1a21780c557e2bbe90450616c1f83ddfab566e7d89f3083ded3b6ed6463`。

随后仅通过 `ManualActionCommandService` 创建正式 TaskRun `#7556`，未直接 SQL 写业务表：

| 项目 | 生产结果 |
| --- | --- |
| resource/action | `fund_share / maintain` |
| trigger/time input | `manual` / `point: 2026-07-07` |
| filters/schedule | `{}` / `null` |
| 状态与 unit | success；`1/1/0` |
| requested/started/ended | `10:49:07.380707` / `10:49:07.969608` / `10:49:09.064834`（Asia/Shanghai） |
| fetched/saved/rejected | `1,673 / 1,673 / 0` |
| reject reasons | `{}` |

任务完成后又由独立只读脚本重新拉取源端、重新归一化并按日期读取目标表，17 项门禁全部通过：

- source、accepted、TaskRun fetched/saved、current、observation 六个计数均为 1,673，reject 0；
- source/current/observation 三份内容摘要完全一致，三方六向身份差集均为 0；
- current/observation 从六个 source fields 重算的内容散列错误均为 0；
- 三方市场分组均为 SH/SZ/O=`953/718/2`；首次 observation 的 `first_observed_at=last_observed_at`；
- 验收后 current relation 总大小为 1,245,184 bytes，observation 为 1,294,336 bytes，仅记录本次最小样本，不外推历史容量。

#### 13.3.3 运行状态与停止边界

同步后活动 TaskRun、活动日期完整性任务、`fund_share` schedule 和 probe 均为 0；六个服务继续 active，Web 健康检查正常。worker 本次观测 `MemoryPeak=182,329,344` bytes，低于 M2 已冻结的 512 MiB 单 unit 门禁。

部署后的 automation capability 只读审计连续执行两次，第二次以首次读到的 29 条 schedule、7 条 ProbeRule 作为期望计数；两次均为一页、零 issue、`passed=true`。B4 migration 只创建 fund_share 表与索引，不含 ops schedule/probe DML，因此没有迁移主动重配任务的路径。

本轮部署发生在 M3 验收接手之前，没有留下同一时点的部署前逐字段快照，因而不能把“29/7 当前有效”夸大为“每条 cron/启停字段与部署前逐字相同”；`next_run_at` 本身也会正常推进。该证据缺口不影响 fund_share schema、HDD 和业务数据五段对账，但已将“部署前后快照”明确保留为后续共享 contract 发布门禁。

M3 只证明生产 schema、HDD placement、单日完整同步和运行链路可用；它不授权历史回补、自动任务创建或 `fund_div` 开发。

### 13.4 历史回补与自动任务门禁

M3 不等于获准回补历史或创建自动任务。两者分开授权：

- 历史回补前先做只读逐年行数、请求页数、预计 HDD/索引/WAL 增量、耗时和配额估算，再拍板起止日期、批次与停止阈值；
- 自动任务由运营后续手工创建 cron/once；cron 创建前必须用多时点只读证据拍板频率、具体时间、相对日期和是否需要滚动修订窗口，代码不 seed 默认 schedule。

### 13.5 发布失败与回滚

- M1 代码未通过门禁：不进入 migration；只修复当前开发分支，不以关闭完整性检查换取通过。
- M2 migration 失败：隔离库事务回滚；不得把表或索引落到默认 tablespace。
- M3 migration 已成功但首次同步失败：保留空业务表和 migration 版本，修复后通过正式 TaskRun 重试；不得直接 SQL 写业务表。
- 首次同步写入过程中失败：executor 回滚该日期 current 与 observation；TaskRun 状态写入失败不得反向回滚已经成功提交的业务事务。
- 部署代码需要回退：先停止新 TaskRun，再回退应用版本；migration downgrade 不删事实表。旧版本若不识别 `fund_share`，两表保留但不再被调度。
- 已创建 schedule 的回滚不在 M3：本批不自动创建 schedule；后续若运营创建，停用/删除必须单独审计其目标和运行中任务。

## 14. milestone 与停止边界

| Milestone | 内容 | 当前状态 |
| --- | --- | --- |
| B4-FS-M0 | 源文档、MCP/connector、分页、日期、字段、市场和代码影响面复审 | 已完成 |
| B4-FS-M1 | 按本 LLD 编码并完成本地自动化/前端回归 | 已完成 |
| B4-FS-M2 | 隔离 PostgreSQL migration、HDD、真实同步、容量/并发/回滚验收 | 已完成 |
| B4-FS-M3 | 生产 migration、HDD、首次最小真实同步与对账 | 已完成；TaskRun `#7556`，1,673 行，reject 0 |
| B4-FS-M4 | 只读历史规模预算、历史回补和自动 schedule | 不在当前范围，分别拍板 |

每个 milestone 都是授权边界。M1 完成后不得自行进入隔离库；M2 完成后不得自行进入生产；M3 完成后不得自行回补历史或创建 schedule。

## 15. 风险、非阻塞决策与最终判断

### 15.1 已关闭的设计风险

- 区间分页已被真实验证，文档不再把“可能截断”写成事实。
- 周日 O 数据证明必须按自然日，不再沿用交易日历假设。
- scoped refresh 避免 B0 writer 全表替换造成跨日期数据破坏。
- 不分区避免破坏实体/版本唯一 contract。
- schedule capability 单一事实源避免再次出现新增数据集漏改前端或后端白名单。

### 15.2 仍需后续拍板

- 实际自动任务频率、cron 时间、相对日期和滚动修订窗口；
- 历史回补起止日期、批量大小和磁盘/WAL 停止阈值；
- 是否以及何时进入 B4 的 `fund_div`。

### 15.3 当前判断

LLD 已覆盖 source contract、三层时间语义、unit/request、身份/完整性、事务/current/observation、表/索引/HDD、Ops/UI、schedule 能力、配置、性能和分阶段验收。M2 已关闭隔离环境的容量、事务回滚和并发风险；M3 又以正式 TaskRun 与独立只读复核关闭了生产 migration、物理 placement和单日完整同步风险。

因此，**B4-FS-M3 已通过，`fund_share` 的首次生产接入闭环。当前停止在 B4-FS-M4 / `fund_div` 之前；历史回补、schedule 创建与 `fund_div` 均须分别获得后续授权。**
