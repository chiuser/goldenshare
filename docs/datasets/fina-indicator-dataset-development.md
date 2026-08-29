# A 股财务指标（`fina_indicator`）数据集接入技术方案 v1

状态：**代码已实现，待运营部署与验收**
编写日期：2026-08-29
适用范围：Tushare `fina_indicator_vip` 接入 Goldenshare Prod

## 1. 结论先行

`fina_indicator` 应建模为“按公告自然日维护的全市场财务指标源站事实”。平台不按股票池逐股请求普通 `fina_indicator`，而是调用 `fina_indicator_vip`；一个 unit 只传一个 `ann_date`，按 `limit/offset` 拉完该公告日的全部分页后，在一个业务事务内写入。

存储采用 **raw 单写 + serving 普通 view**：

```text
Tushare fina_indicator_vip
  -> raw_tushare.fina_indicator      # 唯一物理业务表
  -> core_serving.equity_fina_indicator  # 普通 view，不复制数据
```

生产落盘硬约束：

1. `raw_tushare.fina_indicator` 的 table heap、主键索引和全部二级索引必须位于 `gs_raw_cold_hdd`。
2. migration 在创建任何 relation 前必须验证 `gs_raw_cold_hdd` 存在；不存在时整个 migration 失败，禁止静默落到 `pg_default` SSD。
3. `core_serving.equity_fina_indicator` 只建普通 view，没有独立 heap 或索引，不再占用第二份物理空间。
4. PostgreSQL WAL 属于实例级共享设施，仍使用现有 SSD；本方案不调整 WAL 目录。

## 2. 目标、范围与不做事项

### 2.1 目标

1. 保存 Tushare 当前能够显式返回的全部 167 个源字段。
2. 支持运营按一个公告日或公告自然日区间维护；区间由 planner 逐自然日展开。
3. 完整保留同一披露事实的 `update_flag=0/1` 两类源站行，不自行猜测哪一类是“最终版本”。
4. 为全部 167 个源字段计算确定性的 `source_content_hash`；同一四字段身份内容发生变化时，必须识别为源端修正并覆盖旧值。
5. 使用标准 TaskRun、DatasetDefinition 和 DatasetExecutionPlan 主链提供手动任务与普通自动任务。
6. 从建表开始就把全部物理业务 relation 放入 HDD，避免后续再做 SSD 到 HDD 的停机迁移。

### 2.2 V1 明确不做

1. 不使用普通 `fina_indicator` 按股票池逐股扇出。
2. 不把运营输入的日期区间直接传给源端 `start_date/end_date`。
3. 不暴露 `ts_code`、`period`、`update_flag`、`limit` 或 `offset` 为运营输入。
4. 不创建 serving 物理表、std 表、observation 表或版本历史表。
5. 不加入任何既有 workflow，不新增专用 probe。
6. 不接入日期完整性审计；没有公告的自然日是正常情况。
7. 不引入独立的“历史补数”执行系统。较长历史范围仍使用同一 `maintain` 能力，按允许的日期窗口分批提交。
8. 本文不授权部署、migration、生产同步、清表、删表或重建任何已有业务对象。

## 3. 依据与当前基线

### 3.1 文档与架构依据

- [仓库根规则](/Users/congming/github/goldenshare/AGENTS.md)
- [数据集开发说明模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)
- [Tushare 财务指标数据源文档](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/财务数据/0079_财务指标数据.md)
- [数据集日期模型消费指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)
- [DatasetDefinition 单一事实源方案](/Users/congming/github/goldenshare/docs/architecture/dataset-definition-single-source-refactor-plan-v1.md)
- [DatasetExecutionPlan 方案](/Users/congming/github/goldenshare/docs/architecture/dataset-execution-plan-refactor-plan-v1.md)
- [A 股业绩快报 LLD](/Users/congming/github/goldenshare/docs/datasets/equity-express-low-level-design-v1.md)
- [A 股财务指标 LLD](/Users/congming/github/goldenshare/docs/datasets/fina-indicator-low-level-design-v1.md)

### 3.2 当前代码与生产事实

截至 2026-08-29：

1. 代码已完成 `fina_indicator` DatasetDefinition、ORM、DAO、request builder、row transform、catalog/freshness 登记与自动化测试。
2. 新增 migration `20260829_000160`，其 `down_revision` 连接实施时真实唯一 head `20260829_000159`；当前代码 migration head 为 `20260829_000160`。
3. migration 已实现 `gs_raw_cold_hdd` fail-closed：目标 tablespace 不存在时，在创建 schema、table、index 或 view 前失败。
4. 本轮没有部署、执行数据库 migration、发起生产同步或创建 OpsSchedule；Prod relation、TaskRun 和页面状态仍以运营部署后的实际验收为准。

### 3.3 CodeGraph 影响面

本次发现审计已从仓库根 CodeGraph 核验以下链路：

```text
DatasetDefinition
  -> manual actions / catalog / schedule capability
  -> DatasetActionResolver / unit planner
  -> request builder / DatasetSourceClient pagination
  -> normalizer / DatasetWriter / DAOFactory
  -> raw ORM / migration / table registry
  -> freshness projection / dataset cards / snapshot rebuild
  -> workflow / probe / date completeness exclusion
  -> backend tests / frontend contract consumers
```

本文只形成设计，不修改上述消费者。

## 4. 源接口真实行为

### 4.1 接口选型

| 能力 | 普通 `fina_indicator` | `fina_indicator_vip` | 设计结论 |
| --- | --- | --- | --- |
| 默认对象范围 | 必须传单只股票 | 可按公告日取全市场 | 使用 VIP |
| 普通接口对象历史 | 单只股票最多 100 行，需分页 | 单对象也可查询 | 不走股票池扇出 |
| 全市场报告期 | 不适合 | 支持 `period`，但单期可能超过 5,000 行 | 不作为主时间轴 |
| 全市场公告日 | 不适合 | 支持 `ann_date` | 作为主执行入口 |
| 分页 | 项目 connector 实测支持 `limit/offset` | 项目 connector 实测支持 `limit/offset` | 统一 `offset_limit` |

### 4.2 已完成的真实请求证据

| 请求形态 | 结果 | 结论 |
| --- | --- | --- |
| 普通接口 `ts_code=600000.SH` | 恰好 100 行 | 命中普通接口单次上限，不能当完整历史 |
| VIP 不传业务参数 | 恰好 12,000 行，只覆盖两个报告期 | 无参数请求存在隐式截断，不能当全集 |
| VIP `period=20251231` | 6,818 行、6,251 个代码 | 单报告期可能超过 5,000 行，必须分页 |
| VIP `ann_date=20260430` | 1,723 行、1,251 个代码 | 公告日适合全市场事件维护 |
| VIP `ann_date=20260829` | 1,650 行，日期为周六 | 公告轴是自然日，不是交易日 |
| VIP `ann_date=20000101` | 0 行 | 空公告日是合法结果 |
| VIP 宽报告期区间 `20240101..20241231` | 恰好 12,000 行，仅剩两个报告期 | 宽区间会截断，禁止直接使用 |
| 项目 connector：VIP `period=20251231`，每页 5,000 | `5000 + 1818 + 0 = 6818`，唯一键集合与基准相等 | `limit/offset` 和短页终止有效 |
| 项目 connector：普通接口单股，每页 50 | `50 + 50 + 50 + 50 + 4 = 204` | connector 分页能力闭合 |

### 4.3 字段事实

1. 本地源文档列出 167 个输出字段。
2. 默认响应只返回 108 个字段，遗漏 59 个字段，包括 `invturn_days`、`arturn_days`、`inv_turn`、`valuechange_income`、`interst_income`、`daa`、多个单季度指标、`rd_exp` 和 `update_flag`。
3. 显式请求全部 167 个字段时，普通接口和 VIP 的已测样本均完整返回 167 个字段。
4. `DatasetDefinition.source.source_fields` 必须列出全部 167 个字段；不得依赖 Tushare 默认字段。
5. 本地源文档的输入表尚未列出实测可用的 `update_flag` 过滤参数；该差异应在进入 LLD 前同步校准 source 文档，但 `update_flag` 不对运营开放。

## 5. 三层时间语义

| 语义层 | 设计 |
| --- | --- |
| 时间输入 | 运营提交一个 `ann_date`，或公告自然日闭区间 `start_date/end_date`。这里的日期表示“源站公告日期”，不是报告期。 |
| 执行 unit | point 生成一个公告日 unit；range 按自然日逐日生成 unit。每个 unit 调用一次公告日全市场接口并拉完全部分页。 |
| freshness / audit | 使用 `event_run_trace` 判断最近维护任务是否成功；不要求每个自然日有数据，不做连续日期完整性审计。 |

关键边界：

1. 周末和法定节假日仍可能有公告，planner 不能读取交易日历过滤日期。
2. 源端 `start_date/end_date` 表示报告期范围，不是公告日期范围；request builder 禁止把 Ops 区间映射到这两个字段。
3. `bucket_rule=not_applicable` 只表示不做连续日期 freshness/audit，**不表示不支持日期输入**。

## 6. DatasetDefinition 目标设计

### 6.1 身份与来源

| 字段 | 目标值 |
| --- | --- |
| `dataset_key` | `fina_indicator` |
| `display_name` | `财务指标` |
| `domain` | `low_frequency / 低频数据` |
| `source_key_default` | `tushare` |
| `api_name` | `fina_indicator_vip` |
| `source_doc_id` | `tushare.fina_indicator` |
| `source_fields` | 源文档全部 167 个输出字段，固定顺序显式请求 |

### 6.2 日期与输入

| 定义 | 目标值 |
| --- | --- |
| `date_axis` | `natural_day` |
| `window_mode` | `point_or_range` |
| `input_shape` | `ann_date_or_start_end` |
| `observed_field` | `ann_date` |
| `bucket_rule` | `not_applicable` |
| `audit_applicable` | `False` |
| 支持模式 | `point`、`range` |
| 运营 filters | 空；V1 不开放股票、报告期或修订标识过滤 |

### 6.3 规划、分页与事务

| 定义 | 目标值 |
| --- | --- |
| `universe_policy` | `no_pool` |
| `unit_builder_key` | 复用/登记自然日 point unit builder；禁止新增股票池扇出 |
| `pagination_policy` | `offset_limit` |
| `page_limit` | `5000` |
| `max_units_per_execution` | `None`；不设置缺少源端依据的日期跨度硬上限，实际 unit 数由输入自然日区间确定 |
| `fetch_concurrency` | `1` |
| `commit_policy` | `unit` |
| 幂等要求 | 必须幂等 |

请求量与事务量：

1. 请求量可直接按自然日数估算：一年闭区间约 365/366 个 unit 和 365/366 次基础请求；只有单日超过 5,000 行时才追加下一页。
2. 实测公告日为约 1,500～1,700 行；实现不能把样本均值当硬上限，必须以短页/空页结束分页。
3. 一个 unit 的全部分页完成后才 normalize、upsert、commit；业务提交成功后才计入完成 unit。
4. 167 字段属于宽表，开发验收必须用合成 5,000 行宽记录测量单 unit 内存、SQL 批次、事务耗时和 WAL 增量；结果不可接受时必须停下重新评审，不能靠删字段绕过。

## 7. 存储与 HDD 落盘设计

### 7.1 关系设计

| Relation | 类型 | 物理位置 | 用途 |
| --- | --- | --- | --- |
| `raw_tushare.fina_indicator` | 物理表 | `gs_raw_cold_hdd` | 保存源站 167 字段当前事实 |
| `core_serving.equity_fina_indicator` | 普通 view | 无独立物理存储 | 对下游提供稳定 serving 名称 |

`DatasetStorageDefinition` 目标口径：

```text
raw_dao_name      = raw_fina_indicator
core_dao_name     = raw_fina_indicator
raw_table         = raw_tushare.fina_indicator
target_table      = raw_tushare.fina_indicator
serving_table     = core_serving.equity_fina_indicator
delivery_mode     = raw_with_serving_view
layer_plan        = raw->serving_view
write_path        = raw_only_upsert
conflict_columns  = (ts_code, ann_date, end_date, update_flag)
```

### 7.2 字段与类型

1. `ts_code`：`VARCHAR(16) NOT NULL`。
2. `ann_date`、`end_date`：`DATE NOT NULL`。
3. `update_flag`：`VARCHAR(8) NOT NULL`；显式字段请求缺失时拒绝，不填造业务占位值。
4. 其余 163 个源指标字段：nullable、未限定 precision/scale 的 PostgreSQL `NUMERIC`。源文档只声明 `float`，当前样本不足以证明统一固定精度；使用任意精度 `NUMERIC` 可避免二进制 `FLOAT` 误差，也不会因拍脑袋设置位数而拒绝未来合法修订值。
5. 内容指纹：`source_content_hash VARCHAR(64) NOT NULL`，使用现有 `compute_source_content_hash()` 对全部 167 个显式源字段做确定性哈希；不得包含 `fetched_at`、`api_name` 等内部字段。
6. 内部审计字段：`api_name VARCHAR(32) NOT NULL DEFAULT 'fina_indicator_vip'`、`fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()`。
7. 不保存 `raw_payload`：167 个源字段已经逐列完整保存，再存整行 JSON/Text 会重复占用大体积 HDD 空间、WAL 和写入成本。`api_name/fetched_at/source_content_hash` 提供来源、拉取时间和内容核对能力。

### 7.3 身份、修订与幂等

主键固定为：

```text
(ts_code, ann_date, end_date, update_flag)
```

原因：

1. 实测同一 `(ts_code, ann_date, end_date)` 会同时返回 `update_flag=0` 和 `update_flag=1`，三字段身份会发生冲突。
2. 只保留 `update_flag=1` 会丢失只返回 `0` 的公司；`20251231` 样本中，1,214 个 flag=0 行里有 647 个代码没有 flag=1 行。
3. 源站未提供可靠规则证明 `0` 或 `1` 哪一个必然是唯一最终值，因此 V1 不在 serving view 中擅自筛选。
4. 同一批次中，四字段身份和 `source_content_hash` 都相同的是完全重复，只保留一行。
5. 同一批次中，四字段身份相同但 `source_content_hash` 不同，说明源端同一次完整响应给出了互相冲突的值；整个 unit 必须失败，禁止沿用通用 DAO 的“最后一行覆盖前一行”。
6. 数据库已存在相同四字段身份且 `source_content_hash` 相同，属于幂等重跑；业务值不变。
7. 数据库已存在相同四字段身份但 `source_content_hash` 不同，属于源端对同一身份的修正；upsert 必须覆盖该身份的全部 167 个源字段、内容指纹和 `fetched_at`，不保留被覆盖旧内容。
8. `source_content_hash` 只判断“同一身份的内容是否发生变化”，不参与主键，不会把一次字段修正误写成新行。

下游通过 `update_flag` 明确区分两个源站事实。若未来需要“每个公司/报告期唯一一行”的业务口径，必须另立业务视图并明确选择规则，不能修改 raw 身份掩盖源事实。

### 7.4 索引与 tablespace

首版只建必要索引：

1. 主键索引 `(ts_code, ann_date, end_date, update_flag)`。
2. 公告日维护/核对索引 `(ann_date, ts_code)`。
3. 单证券报告期查询索引 `(ts_code, end_date DESC, ann_date DESC, update_flag)`。

三类索引与 table heap 全部显式放在 `gs_raw_cold_hdd`。不建 SSD 热索引，不做冷热拆分，不建自动分区；后续只有真实查询和容量证据证明需要时，才单独评审分区或索引调整。

### 7.5 Migration fail-closed

新增 migration 必须按以下顺序执行：

1. 查询 `pg_tablespace`，确认 `gs_raw_cold_hdd` 存在。
2. tablespace 不存在时立即抛错；此时不得创建 schema、table、view 或 index。
3. 创建 raw 表并显式指定 `postgresql_tablespace='gs_raw_cold_hdd'`。
4. 把命名主键索引显式移动/创建在 `gs_raw_cold_hdd`。
5. 两个二级索引均使用 `TABLESPACE gs_raw_cold_hdd`。
6. 创建 serving 普通 view。
7. migration 测试和实施验收必须从 PostgreSQL catalog 证明 table、PK、二级索引全部命中 HDD；不能只检查 migration 文本。
8. downgrade 不得自动删除已经写入的业务事实；需要回退应用时保留 raw 表与 serving view，另行评审 DDL。

## 8. Ingestion 设计

### 8.1 Unit 规划

```text
point(ann_date=D)
  -> unit {ann_date: D}

range(start_date=S, end_date=E)
  -> S..E 每个自然日一个 unit {ann_date: D}
```

禁止行为：

1. 不读取股票 active pool。
2. 不生成“股票 × 日期”unit。
3. 不跳过周末、节假日或没有公告的日期。
4. 不生成 `period`、报告期 start/end 或无参数全量 unit。

### 8.2 Request builder

每个 unit 只生成：

```json
{
  "ann_date": "YYYYMMDD"
}
```

`fields` 由 DatasetDefinition 的 167 字段白名单传给 connector；`limit/offset` 由 DatasetSourceClient 分页层追加。Ops、前端和 request builder 不接收分页参数。

### 8.3 Normalizer 与 writer

1. 清除字符串中的 NUL，规范化 `ts_code` 和 `update_flag`。
2. `ann_date/end_date` 转 `date`；163 个指标字段转 `Decimal`，空值保留 `NULL`。
3. 使用现有 `compute_source_content_hash()` 对规范化后的 167 个源字段计算内容指纹；哈希失败以 `normalize.source_content_hash_invalid` 拒绝。
4. `ts_code/ann_date/end_date/update_flag` 任一缺失都以结构化 reason code 拒绝。
5. 同一批次四字段身份完全重复且内容指纹一致时只保留一行；同身份内容指纹冲突时整个 unit 失败，禁止用输入顺序决定胜负。
6. 任一归一化拒绝都在业务写入前使 unit 失败；不能把部分公告日写入后标成功。
7. writer 只调用 raw DAO；数据库中同身份不同指纹必须覆盖全部源字段，同身份同指纹保持幂等。serving view 在同一事务提交后自动可见，不执行第二次写入。

## 9. Ops、自动任务与 freshness

### 9.1 展示目录

加入现有 `A股财务数据` 分组，排序在 `express` 之后。前端不增加 `fina_indicator` 私有分支，只消费 DatasetDefinition 和 Ops catalog 投影。

### 9.2 手动任务

运营可选择：

1. 一个公告日期。
2. 一个公告自然日区间。

页面不展示股票代码、报告期、修订标识或分页参数。

### 9.3 自动任务

V1 支持普通 cron，不支持 probe、fallback、once、intraday 或 workflow。推荐复用现有 `since_last_success_day_range` 通用策略：

1. 首次从运营填写的 `initial_start_date` 维护到触发日前一自然日。
2. 后续从该 schedule 最后一次成功覆盖的下一自然日继续维护到触发日前一自然日。
3. 失败或取消不推进成功覆盖范围。
4. 不设置日期跨度硬上限；运营可根据任务耗时和请求量把较长首次历史范围拆成多个普通任务，但所有任务仍使用同一 `maintain` 主链。

该策略只保证新公告日期按日进入系统。源站若在未来修订过去的 `ann_date`，需要运营重新运行对应公告日/区间；V1 不擅自增加滚动重叠窗口。

### 9.4 Freshness 与审计

1. freshness policy 使用 `event_run_trace`。
2. 数据卡片表达“最近维护是否成功”，不把 `max(ann_date)` 与当天自然日做连续缺口比较。
3. 空公告日成功执行后仍是一次有效维护，不应判滞后。
4. `audit_applicable=False`，不进入日期完整性审计页。

## 10. 消费者影响面

| 消费方 | 目标影响 |
| --- | --- |
| manual actions | 新增 point/range 财务指标维护入口 |
| catalog / 数据源页 | 新增 A股财务数据卡片；raw 表与 serving view 来源由 Definition 投影 |
| workflow | 不加入，必须有负向测试 |
| resolver / planner | 自然日逐日 unit，无对象池 |
| request builder | 只映射 `ann_date` |
| source client | 复用 offset/limit 分页，显式 167 fields |
| normalizer / writer | Decimal、四字段身份、raw-only upsert |
| freshness / snapshot | 新增 `event_run_trace` 映射并参与 snapshot rebuild |
| date completeness | 明确排除 |
| 自动任务 | 复用通用成功游标日期区间策略 |
| probe | 不注册 |
| 前端时间控件 | 复用 Definition 投影的公告日 point/range 控件 |
| table registry / DAO factory | 新增 raw ORM 与 raw DAO |
| Biz / 下游 | 新增 `core_serving.equity_fina_indicator` view；V1 不新增业务 API |

## 11. 测试与验收门禁

### 11.1 自动化测试

1. Definition：167 fields、VIP API、自然日、no_pool、raw-only/view、HDD 设计事实、event freshness。
2. Planner：point 一日一 unit；range 含周末/节假日逐日展开；不得因超过 366 日而拒绝；不得查询股票池。
3. Request builder：只产生 `ann_date`；不得泄漏 `start_date/end_date/period/ts_code/update_flag/limit/offset`。
4. Source client：5,000 满页继续、短页停止、分页合并唯一键集合闭合、每页携带完整 167 fields。
5. Normalizer：日期、Decimal、NUL、空值、四字段必填、167 字段确定性指纹、同批重复与冲突。
6. Writer：只调用 raw DAO；同身份同指纹幂等、同身份不同指纹覆盖全部源字段；两个 update_flag 可并存；任一 reject 不写业务表。
7. ORM/migration：167 源字段、`source_content_hash` 和两个审计字段逐列一致；view 字段与 raw 一致。
8. HDD：缺 tablespace 时零 relation；table/PK/两个索引全部在 `gs_raw_cold_hdd`；没有业务 heap/index 落 `pg_default`。
9. Ops：A股财务数据分组、手动/普通自动任务可见；workflow/probe/date audit 均不出现。
10. 架构：不新增 foundation 反向依赖，不回流 legacy 目录。

### 11.2 真实 connector 与数据库验收

进入“代码完成”前至少完成：

1. 用项目 connector 对一个有数据的公告日拉完整分页，记录源端行数和唯一四字段身份数。
2. 对一个空公告日确认零行能够正常成功，不产生 reject。
3. 五段对账：`fetched -> normalized -> written -> rejected -> raw scope rows`。
4. 幂等复跑同一公告日，四字段身份数不增长；构造或捕获同身份某个指标字段变化时，旧值和旧 `source_content_hash` 必须被新值覆盖，不能新增第二行。
5. raw 与 serving view 的 167 源字段双向差集为 0。
6. catalog 验收 table、PK、两个二级索引 tablespace 全为 `gs_raw_cold_hdd`；view 物理大小为 0。
7. 测量 5,000 行宽 unit 的内存、事务耗时和 WAL 增量；若超出可接受范围，停止发布并回到事务/批次设计评审。

## 12. 开发里程碑

| 阶段 | 目标 | 交付 |
| --- | --- | --- |
| M0 | source 文档校准 | 补 `update_flag` 输入差异、冻结 167 fields 与内容指纹算法 |
| M1 | LLD 与代码影响面 | 精确到文件/类/测试/迁移的 LLD，重新读取 migration head |
| M2 | Schema 与 HDD migration | raw ORM/DAO、HDD fail-closed 表与索引、serving view |
| M3 | Definition 与执行链 | Definition、planner、request builder、normalizer、writer |
| M4 | Ops 投影 | catalog、manual/schedule、freshness，明确 workflow/probe 排除 |
| M5 | 自动化门禁 | Definition、分页、写入、HDD、Ops、架构测试 |
| M6 | 运营真实验收（本轮未执行） | 有数据日、空日期、幂等、五段对账、HDD catalog 证据 |
| M7 | 文档收口 | 开发文档和 LLD 更新为真实状态；生产动作另行授权 |

## 13. 硬需求追溯账本

| ID | 硬需求 | 代码落点 | 正向门禁 | 反向门禁 | 状态 |
| --- | --- | --- | --- | --- | --- |
| FI-01 | 使用 `fina_indicator_vip` 全市场公告日请求 | Definition/request builder | 公告日返回全市场 | 不得调用普通接口逐股扇出 | 代码与自动化门禁完成，待运营验收 |
| FI-02 | 显式请求并保存全部 167 fields | Definition/ORM/migration/view | 字段逐列一致 | 默认 108 字段方案失败 | 代码与自动化门禁完成，待运营验收 |
| FI-03 | point/range 按自然日逐日 unit | date model/planner | 周末仍生成 unit | 不得走交易日历或宽区间源请求 | 代码与自动化门禁完成，待运营验收 |
| FI-04 | 四字段身份保留 0/1 两类事实；同身份字段修正必须覆盖 | ORM/normalizer/writer | 两个 flag 可并存；改一个指标后原行和指纹被覆盖 | 三字段主键、只存 flag=1、同批冲突最后一行胜出均失败 | 代码与自动化门禁完成，待运营验收 |
| FI-05 | raw 单写、serving 普通 view | storage/writer/migration | raw/view 同事务一致 | 不得双写 serving 物理表 | 代码与自动化门禁完成，待运营验收 |
| FI-06 | table/PK/index 全部 HDD | migration | catalog 全命中 `gs_raw_cold_hdd` | 缺 HDD 必须零创建，禁止 SSD fallback | 迁移代码与 fail-closed 测试完成，待运营 migration 后验收 |
| FI-07 | event freshness，不做日期完整性 | policy/projection | 空公告日成功可保持正常 | 不得按连续自然日判缺口 | 代码与自动化门禁完成，待运营验收 |
| FI-08 | 手动 + 普通自动任务，不进 workflow/probe | capabilities/catalog | 两类入口可见 | workflow/probe 必须不存在 | 代码与自动化门禁完成，待运营验收 |
| FI-09 | 不设置无源端依据的日期跨度硬上限 | Definition/resolver | 超过 366 日的合法区间仍可规划 | 不得保留 366/367 日人工阈值 | 代码与自动化门禁完成，待运营验收 |
| FI-10 | Ops 状态不影响业务事务 | executor/TaskRun adapter | 状态失败不回滚已提交 raw | 不得把状态写入纳入 raw 事务 | 复用既有事务边界并通过回归，待运营验收 |

## 14. 已确认决策

1. 不保存 `raw_payload`；167 个源字段逐列落库，并保存 `source_content_hash`、`api_name` 和 `fetched_at`。
2. 不设置 366 天或其他缺少源端依据的日期跨度硬上限；请求量按输入自然日数真实计算，运营可自行分批提交长区间。
3. 首次历史维护起点不进入代码常量，部署后由运营在创建自动任务时填写 `initial_start_date`。
4. 当前没有其他待拍板项，可以进入 LLD。
