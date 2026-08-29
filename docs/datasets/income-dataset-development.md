# A 股利润表（`income`）数据集接入技术方案 v1

状态：**关键口径已确认，LLD 已完成，待开发**
编写日期：2026-08-29
适用范围：Tushare `income_vip` 接入 Goldenshare Prod

详细编码设计：[A 股利润表数据集接入 LLD v1](/Users/congming/github/goldenshare/docs/datasets/income-low-level-design-v1.md)

## 1. 结论先行

`income` 建模为“按公告自然日维护的全市场利润表源站事实”。运营选择一个公告日或公告自然日区间，同时选择需要维护的报表类型；默认维护全部 12 种真实 `report_type`。

```text
Ops 手动任务 / 普通自动任务
  -> DatasetActionRequest(dataset_key=income, action=maintain)
  -> DatasetActionResolver
  -> 公告自然日 x 已选择 report_type 的 planned units
  -> Tushare income_vip 分页
  -> raw_tushare.income                       # HDD 唯一物理表，保留全部版本与类型
  -> core_serving.equity_income               # 普通 view，每公司每报告期唯一最新合并报表
```

已确认的硬口径：

1. raw 保存全部源字段、全部 `report_type` 和全部修订版本。
2. 默认报表类型是 `1..12` 全部真实值；页面“全部”只是交互控件，不进入请求、执行计划或数据库。
3. `comp_type` 不对运营开放；源端返回什么就保存什么，不把它限制为文档中的 `1..4`。
4. serving 只选 `report_type=1`；优先 `update_flag=1`，否则选 `0`，再取最新 `f_ann_date`。
5. raw 表、主键和全部二级索引必须位于 `gs_raw_cold_hdd`；serving 是普通 view，不复制物理数据。
6. 支持手动任务与普通自动任务，不加入 workflow，不新增 probe。
7. 初始历史维护范围由运营后续决定，本文不设拍脑袋的日期跨度上限。

## 2. 依据与源端事实

### 2.1 依据

- [仓库根规则](/Users/congming/github/goldenshare/AGENTS.md)
- [数据集开发说明模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)
- [Tushare 利润表源文档](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/财务数据/0033_利润表.md)
- [A 股财务指标接入方案](/Users/congming/github/goldenshare/docs/datasets/fina-indicator-dataset-development.md)
- [数据集日期模型消费指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)

### 2.2 已核验的接口事实

1. 普通 `income` 以单只股票历史查询为主；全市场维护应使用 `income_vip`。
2. 项目 connector 对 2026 半年报范围实测分页为 `5000 + 5000 + 409 = 10409` 行，说明必须使用 `limit/offset` 拉到短页结束。
3. 源文档共列出 94 个输出字段；默认响应只有 84 个，实施必须显式请求完整 94 字段。
4. `2026-08-28` 身份字段实测返回 1,442 行，`ts_code/ann_date/f_ann_date/end_date/report_type/comp_type/end_type/update_flag` 均无空值。
5. 同日实测 `comp_type` 出现 `1/2/3/4/7`；值 `7` 的样本为 `002961.SZ 瑞达期货`。本地源文档仅说明 `1..4`，因此不得把 `comp_type` 建成封闭枚举。
6. 对 `600000.SH, period=20260630` 显式请求各报表类型时，`1/2/6/7` 有数据，其他类型可以为空。所选类型空结果是合法源端事实，不能使 unit 失败。
7. `update_flag=0/1` 都真实存在；只请求或只保存其中一个都会漏源站版本。

## 3. 三层时间语义

| 语义层 | 设计结论 |
| --- | --- |
| 时间输入 | 运营输入 `ann_date`，或公告自然日闭区间 `start_date/end_date`；含义是公告日期，不是报告期。 |
| 执行 / unit | range 按每个自然日展开；每个公告日再按已选择的真实 `report_type` 展开，一个 unit 对应“一个公告日 + 一种报表类型”。 |
| freshness / audit | 使用 `event_run_trace`；公告属于事件数据，不要求每个自然日都有记录，不进入日期完整性审计。 |

周末和节假日可能有公告，因此 planner 不读取交易日历。`bucket_rule=not_applicable` 只表示不做连续日期完整性判断，不表示不支持日期输入。

## 4. 输入模型与报表类型交互

### 4.1 后端事实

`report_type` 是必填、多值、显式枚举输入：

| 值 | 页面名称 |
| --- | --- |
| `1` | 合并报表 |
| `2` | 单季合并 |
| `3` | 调整单季合并表 |
| `4` | 调整合并报表 |
| `5` | 调整前合并报表 |
| `6` | 母公司报表 |
| `7` | 母公司单季表 |
| `8` | 母公司调整单季表 |
| `9` | 母公司调整表 |
| `10` | 母公司调整前报表 |
| `11` | 母公司调整前合并报表 |
| `12` | 母公司调整前报表（源站代码 12） |

`DatasetDefinition` 目标配置：

```text
input filter:
  name                = report_type
  field_type          = list
  required            = true
  multi_value         = true
  enum_values         = ("1", ..., "12")
  select_all_enabled  = true

planning:
  enum_fanout_fields  = ("report_type",)
  enum_fanout_defaults= {"report_type": ("1", ..., "12")}
```

实现前需要以最小、通用、向后兼容的 additive contract 为 `DatasetInputField -> Ops catalog -> frontend` 增加枚举显示名与 `select_all_enabled`。禁止按 `dataset_key=income` 在页面写私有分支。

### 4.2 页面行为

1. 初始默认选中“全部”，同时显示 12 个选项已选中且禁用。
2. 取消“全部”后，12 个选项全部清空并恢复可选。
3. 再次选择“全部”时，页面把实际值数组设置为 `1..12`。
4. 未选择任何真实类型时禁止提交，服务端也必须拒绝。
5. 请求体和 schedule `params_json` 只保存真实值数组，例如 `{"report_type":["1","2","6"]}`；严禁保存 `all`、`ALL` 或 `__ALL__`。

### 4.3 `comp_type`

`comp_type` 表示公司采用的报表科目体系，不改变响应字段集合。接口仍返回同一套固定宽表，只是不同公司类型适用字段有值，其他字段为空。

V1 不把它暴露为运营输入：默认请求所有公司类型，raw 原样保存该字段。数据库使用字符串字段，不设置 `1..4` CHECK；未来源端出现新值时不会静默丢数。

## 5. DatasetDefinition 目标设计

| 维度 | 目标值 |
| --- | --- |
| `dataset_key` | `income` |
| `display_name` | `利润表` |
| domain | `low_frequency / 低频数据` |
| source API | `income_vip` |
| source fields | 源文档完整 94 字段，固定顺序显式请求 |
| date model | `natural_day + point_or_range + ann_date_or_start_end` |
| universe | `no_pool` |
| pagination | `offset_limit`, `page_limit=5000` |
| unit builder | 通用自然日 builder + `report_type` enum fan-out |
| write path | `raw_only_upsert` |
| delivery mode | `raw_with_serving_view` |
| freshness | `event_run_trace` |
| audit | `False` |
| capability | manual + schedule，禁止 workflow/probe |

Request builder 每个 unit 只生成：

```json
{"ann_date":"YYYYMMDD","report_type":"1"}
```

`fields` 来自 Definition；`limit/offset` 由 `DatasetSourceClient` 追加。不得向源端传 `comp_type`、`period`、`start_date/end_date`、`is_calc` 或业务哨兵值。

## 6. Raw 存储、身份与修订

### 6.1 关系与字段

| Relation | 类型 | 位置 | 用途 |
| --- | --- | --- | --- |
| `raw_tushare.income` | 物理宽表 | `gs_raw_cold_hdd` | 全部 94 个源字段、类型和版本 |
| `core_serving.equity_income` | 普通 view | 无独立存储 | 每公司每报告期唯一最新合并报表 |

raw 逐列保存全部源字段，数值字段使用 nullable `NUMERIC`，日期字段使用 `DATE`，字符串保留 `NULL`。额外保存：

- `source_content_hash VARCHAR(64) NOT NULL`
- `api_name VARCHAR NOT NULL DEFAULT 'income_vip'`
- `fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()`

不保存重复的整行 `raw_payload`，因为源字段已经完整逐列落库。

### 6.2 Raw 身份

主键 / conflict columns：

```text
(ts_code, ann_date, f_ann_date, end_date,
 report_type, comp_type, end_type, update_flag)
```

规则：

1. 身份不同即保留为不同源站版本。
2. 同一完整身份、同一内容指纹是幂等重复，只保留一行。
3. 同一完整身份、内容指纹变化表示源端修正，upsert 覆盖该身份全部业务字段，不保留错误旧内容。
4. 同一批次出现同身份不同内容时整个 unit 失败，禁止依赖输入顺序决定结果。
5. `update_flag` 只接受源文档定义的 `0/1`；缺失或其他值使 unit 失败，不造默认值。
6. 不因某次源响应缺少旧身份而删除 raw 既有行。

### 6.3 索引与 HDD 门禁

首版索引：

1. 上述八字段主键。
2. `(ann_date, report_type, ts_code)`，服务 unit 对账与公告日查询。
3. `(report_type, ts_code, end_date, update_flag DESC, f_ann_date DESC, ann_date DESC)`，服务 serving 选择和单公司报告期查询。

table heap、主键与两个二级索引全部显式放入 `gs_raw_cold_hdd`。migration 必须先验证 tablespace 存在，不存在则在创建任何 relation 前失败，禁止回退 SSD。实施前重新读取真实 Alembic head；本文记录的当前 head `20260829_000161` 不是未来编码时可直接照抄的 `down_revision`。

## 7. Serving 唯一报表规则

`core_serving.equity_income` 使用普通 view，按 `(ts_code, end_date)` 唯一选择：

1. 只保留 `report_type='1'`。
2. `update_flag='1'` 优先于 `'0'`。
3. 同优先级取最新 `f_ann_date`。
4. 再按 `ann_date`、`fetched_at`、`comp_type`、`end_type`、`source_content_hash` 做稳定排序，保证结果确定。

建议使用 `DISTINCT ON (ts_code, end_date)` 实现，不在应用层拼装。view 输出源字段及必要的内容指纹/拉取时间，不新增第二次写入。

## 8. 执行、事务与性能

1. 一个 unit 是一个 `ann_date + report_type`；该类型全部分页拉完后再 normalize、校验、raw upsert、commit。
2. 某个报表类型返回 0 行是合法完成；分页错误、字段缺失、身份冲突或 reject 会使该 unit 失败。
3. `fetch_concurrency=1`，V1 不增加并发；不要用并发掩盖请求量问题。
4. 单数据集、单公告日、默认全部类型最多产生 12 次基础请求；分页超过 5,000 行时按类型继续翻页。
5. 三张表同时按全部类型维护时，单公告日最多 36 次基础请求；一年约 `365 x 36 = 13,140` 次基础请求。该成本是完整保存所有报表类型的已确认取舍。
6. TaskRun 进度使用真实 unit 数，运营可看到公告日和报表类型；业务提交完成后才计入 unit 完成。
7. Ops/TaskRun 状态失败不得回滚已提交 raw 业务事务。

## 9. Ops、自动任务与边界

1. 加入 `A股财务数据` 展示分组，建议顺序 30。
2. 手动任务支持单公告日、公告日区间及报表类型多选。
3. 普通自动任务复用 `since_last_success_day_range`；`report_type` 选择随 schedule 保存，默认显式 `1..12`。
4. 不加入任何 workflow，不注册 probe，不新增专用 API。
5. freshness 使用 `event_run_trace`；空公告日成功执行也算有效维护。
6. 不进入日期完整性审计；页面不得把 `max(ann_date)` 与当前自然日直接比较后判滞后。
7. 后续修改既有 schedule 的报表类型只影响未来触发日期，不自动回头补齐新增加的类型；历史新增类型仍通过同一手动 `maintain` 区间补齐，不引入另一套补数系统。

## 10. 消费者影响面与测试门禁

| 消费方 | 影响与门禁 |
| --- | --- |
| DatasetDefinition / resolver | 新增 Definition；日期与报表类型全部由 resolver 展开 |
| request builder / source client | 只传 `ann_date + report_type`；显式 94 fields；分页到短页 |
| normalizer / writer / DAO | 八字段身份、内容指纹、raw-only、HDD |
| manual/catalog/schedule | 新增必填多选；默认真实 `1..12` |
| frontend | 通用“全部”交互，不按 dataset key 写分支 |
| freshness/cards/snapshot | 直接读取 Definition 的 `event_run_trace` 与 raw/view 事实 |
| workflow/probe/audit | 必须有负向测试证明未接入 |
| Biz/downstream | 新增 serving view，不在本轮新增业务 API |

自动化测试至少覆盖：

1. 94 字段显式请求与默认字段缺失的负向护栏。
2. point/range 含周末逐自然日展开。
3. 默认 12 类型、任意子集、多选去重、空选择拒绝、非法类型拒绝、禁止 `ALL/__ALL__`。
4. 某个类型空结果合法；分页短页闭合；不能返回半页集合后标成功。
5. `comp_type=7` 可保存，非适用财务字段可为空。
6. raw 八字段身份、同身份同指纹幂等、同身份修订覆盖、批次冲突失败。
7. serving 对 `report_type/update_flag/f_ann_date` 的选择顺序。
8. migration tablespace fail-closed 与全部索引 HDD 位置。
9. 手动/自动可见，workflow/probe/date completeness 不出现。

## 11. 实施里程碑

| 里程碑 | 内容 |
| --- | --- |
| M0 | 冻结 94 字段、报表类型标签、身份空值与分页实测；重新读取 Alembic head |
| M1 | 增加 raw ORM/DAO、HDD migration、serving view |
| M2 | 增加 Definition、request builder、normalizer、writer 注册 |
| M3 | 增加通用枚举标签与“全部”选择 contract，接入手动/自动页面 |
| M4 | 完成测试、Definition lint、架构和文档检查 |
| M5 | 由运营执行部署、migration、初始范围同步和页面验收 |

## 12. 待后续确定

仅剩初始历史维护范围由运营后续决定。它不影响数据模型、请求模型、raw 身份、serving 规则或代码设计，不阻塞 LLD。
