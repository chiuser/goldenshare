# A 股资产负债表（`balancesheet`）数据集接入技术方案 v1

状态：**代码已实现；共享 `end_type` 可空修正待运营部署 migration `20260830_000166` 后验收**
编写日期：2026-08-29
适用范围：Tushare `balancesheet_vip` 接入 Goldenshare Prod

详细编码设计：[A 股资产负债表数据集接入 LLD v1](/Users/congming/github/goldenshare/docs/datasets/balancesheet-low-level-design-v1.md)

## 1. 结论先行

`balancesheet` 按公告自然日维护全市场资产负债表。默认请求全部 12 种真实 `report_type`，raw 在 HDD 保存全部类型、全部版本和全部 158 个源字段；`core_serving.equity_balancesheet` 普通 view 只提供每家公司、每个报告期唯一最新合并报表。

```text
DatasetActionRequest
  -> 公告自然日 x 已选 report_type units
  -> balancesheet_vip 分页
  -> raw_tushare.balancesheet              # HDD 唯一物理表
  -> core_serving.equity_balancesheet      # 普通 view
```

硬口径：

1. raw 保留全部报表类型和源站版本；同一身份的内容修正用指纹识别并覆盖错误旧内容。
2. 页面默认“全部”，实际保存 `1..12` 数组，不产生 `ALL/__ALL__`。
3. `comp_type` 不对运营开放，也不限定为 `1..4`；它只标识公司报表科目体系，响应字段结构仍固定。
4. serving 限定 `report_type=1`，优先 `update_flag=1`，否则 `0`，再取最新 `f_ann_date`。
5. table heap 和全部索引放入 `gs_raw_cold_hdd`，不存在时 migration 必须失败。
6. 支持手动与普通自动任务，不进入 workflow，不做 probe。
7. 初始维护范围以后决定，不影响本方案架构。

## 2. 依据与接口证据

- [Tushare 资产负债表源文档](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/财务数据/0036_资产负债表.md)
- [数据集开发说明模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)
- [A 股财务指标接入方案](/Users/congming/github/goldenshare/docs/datasets/fina-indicator-dataset-development.md)
- [数据集日期模型消费指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)

已完成的只读实测：

1. 全市场使用 `balancesheet_vip`，不得按股票池调用普通接口。
2. 2026 半年报范围项目 connector 分页为 `5000 + 5000 + 980 = 10980` 行。
3. 源文档列出 158 个输出字段；默认只返回 152 个，必须显式请求完整 158 字段。
4. `2026-08-28` 返回 1,457 行，八个前置字段均无空值，`comp_type` 包含 `1/2/3/4/7`。三张财务报表共用同一身份契约；利润表已实测存在 `end_type=NULL`，所以本表也按源字段可空、身份不含 `end_type` 收口，避免共享模型漂移。
5. 实测同一 `002604.SZ + ann_date=20260820 + end_date=20260630 + report_type=1 + comp_type=1 + end_type=2 + update_flag=1` 出现两个不同 `f_ann_date`：`20260820` 和 `20260827`。因此 `f_ann_date` 必须进入 raw 身份；否则会覆盖掉源站两个版本。
6. 对 `600000.SH, period=20260630`，`report_type=1/6` 有数据，其他类型可为空。空类型不能判失败。

## 3. 时间、unit 与 freshness

| 语义层 | 目标语义 |
| --- | --- |
| 输入 | `ann_date` 或公告自然日闭区间，不是报告期。 |
| unit | range 逐自然日；每个自然日再按已选择 `report_type` 扇出。 |
| freshness | `event_run_trace`；不要求连续公告日，不参与日期完整性审计。 |

周末/节假日不得被交易日历过滤。一个 unit 固定为“一个公告日 + 一种报表类型”，全部分页在同一 unit 事务中完成。

## 4. 报表类型与页面

`report_type` 采用必填、多值、真实枚举 `1..12`，中文标签与 [利润表方案第 4 节](/Users/congming/github/goldenshare/docs/datasets/income-dataset-development.md) 相同。Definition 使用：

```text
field_type=list
multi_value=true
required=true
enum_values=("1", ..., "12")
enum_fanout_fields=("report_type",)
enum_fanout_defaults={"report_type": ("1", ..., "12")}
select_all_enabled=true
```

页面交互固定为：默认“全部”；选择“全部”时 12 个真实选项全部选中并禁用；取消时清空并恢复选择。后端请求和 schedule 只保存真实值数组，空数组、非法值和业务哨兵必须拒绝。

该能力必须通过通用 `DatasetInputField -> Ops catalog -> frontend` additive contract 实现，同时提供枚举值到中文标签映射；禁止写 `balancesheet` 页面特例。

`comp_type` 不进入输入模型。raw 使用字符串原样保存 `1/2/3/4/7` 及未来源端合法值；不同公司类型不切换列结构，只会让不适用科目保持 `NULL`。

## 5. DatasetDefinition 与请求

| 维度 | 目标值 |
| --- | --- |
| dataset | `balancesheet / 资产负债表` |
| domain | `low_frequency / 低频数据` |
| API | `balancesheet_vip` |
| fields | 完整 158 字段，固定顺序显式请求 |
| date model | `natural_day + point_or_range + ann_date_or_start_end` |
| universe | `no_pool` |
| pagination | `offset_limit`, `page_limit=5000` |
| planning | 自然日 builder + `report_type` enum fan-out |
| storage | `raw_only_upsert + raw_with_serving_view` |
| freshness/audit | `event_run_trace / False` |
| actions | manual + schedule，禁止 workflow/probe |

Request builder 只产生：

```json
{"ann_date":"YYYYMMDD","report_type":"1"}
```

不得传 `comp_type/period/start_date/end_date/limit/offset`。分页参数由 source client 负责。

## 6. Raw 与 HDD 设计

### 6.1 Relations

| Relation | 类型 | 位置 |
| --- | --- | --- |
| `raw_tushare.balancesheet` | 158 字段物理宽表 | `gs_raw_cold_hdd` |
| `core_serving.equity_balancesheet` | 普通 view | 无独立物理存储 |

raw 额外保存 `source_content_hash`、`api_name='balancesheet_vip'`、`fetched_at`。所有源数值字段使用 nullable `NUMERIC`；不适用于某类公司的字段保留 `NULL`，不填 0。源字段已完整逐列保存，不再重复保存 `raw_payload`。

### 6.2 身份与修订

主键 / conflict columns：

```text
(ts_code, ann_date, f_ann_date, end_date,
 report_type, comp_type, update_flag)
```

1. 不同完整身份全部保留。
2. 同身份同指纹幂等去重。
3. 同身份、不同指纹是源端对该身份的字段修正，覆盖该身份全部字段。
4. 同一批次同身份冲突使 unit 失败。
5. `update_flag` 必须是 `0/1`；缺失或未知值失败。
6. 不根据响应缺行删除历史 raw 行。

### 6.3 索引

1. 七字段主键；`end_type` 可空且不参与身份。
2. `(ann_date, report_type, ts_code)`。
3. `(report_type, ts_code, end_date, update_flag DESC, f_ann_date DESC, ann_date DESC)`。

全部物理 relation 位于 `gs_raw_cold_hdd`。初始建表 migration 为 `20260830_000164`；前向 migration `20260830_000166` 统一修正三表七字段主键和 `end_type` 可空约束，执行前检查现有数据无七字段冲突，禁止静默回退 SSD。

## 7. Serving 规则

`core_serving.equity_balancesheet` 按 `(ts_code, end_date)` 唯一：

1. `WHERE report_type='1' AND update_flag IN ('0','1')`。
2. `update_flag DESC`，即修订后 `1` 优先。
3. `f_ann_date DESC`。
4. 再按 `ann_date/fetched_at/comp_type/end_type/source_content_hash` 稳定排序。

使用数据库普通 view 与 `DISTINCT ON` 实现，不允许 Ops、前端或 Biz 自己重复拼选择规则。

## 8. 事务、性能与失败语义

1. 单公告日默认 12 个 unit、最多 12 次基础请求；每个类型独立分页和事务。
2. 报表类型无数据是成功空结果；源端错误、分页不闭合、字段缺失、reject 或身份冲突使对应 unit 失败。
3. 一个 unit 完整分页后才 normalize、upsert 和 commit；提交成功后才计入完成进度。
4. `fetch_concurrency=1`；V1 不增加并发。
5. 三张表全类型单日最多 36 次基础请求，一年约 13,140 次；这是完整性优先的已确认成本。
6. Ops 状态写入失败不影响 raw 已提交事务。

## 9. Ops 与自动任务

1. 放入 `A股财务数据`，建议顺序 40。
2. 手动任务提供公告日 point/range 与报表类型多选。
3. 自动任务使用普通 schedule 和 `since_last_success_day_range`，保存显式类型数组。
4. 不加入 workflow，不支持 probe，不新增专用 API。
5. 数据卡片消费 `event_run_trace`，不做 `max(ann_date)` 连续日期推断。
6. 修改既有 schedule 的类型选择只作用于未来触发日期；需要补齐过去日期的新类型时，继续使用同一手动 `maintain` 区间能力。

## 10. 测试与实施里程碑

测试门禁：

1. 158 字段显式请求，默认缺失 6 字段的反例。
2. point/range 自然日、默认 12 类型、子集、空选择和非法值。
3. 每种类型独立分页；空类型合法；半页和分页错误不能标成功。
4. `comp_type=7`、大量 nullable 行与 Decimal 宽表归一化。
5. 七字段身份与可空 `end_type`，尤其验证两个不同 `f_ann_date` 都能保留。
6. serving 选择规则与稳定排序。
7. raw-only writer、HDD migration fail-closed、手动/自动可见、workflow/probe/audit 排除。

| 里程碑 | 内容 |
| --- | --- |
| M0 | 冻结 158 字段、身份空值、分页与报表类型实测；读取真实 migration head |
| M1 | ORM/DAO、HDD 表索引、serving view |
| M2 | Definition、planner/request builder、normalizer/writer 注册 |
| M3 | 通用枚举标签和“全部”交互接入 |
| M4 | 定向测试、架构/Definition/docs 检查 |
| M5 | 运营部署、迁移、历史范围同步和页面验收 |

初始历史范围是唯一后续运营决策，不阻塞 LLD。
