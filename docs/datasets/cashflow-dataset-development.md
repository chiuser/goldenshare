# A 股现金流量表（`cashflow`）数据集接入技术方案 v1

状态：**关键口径已确认，LLD 已完成，待开发**
编写日期：2026-08-29
适用范围：Tushare `cashflow_vip` 接入 Goldenshare Prod

详细编码设计：[A 股现金流量表数据集接入 LLD v1](/Users/congming/github/goldenshare/docs/datasets/cashflow-low-level-design-v1.md)

## 1. 结论先行

`cashflow` 按公告自然日维护全市场现金流量表。raw 在 HDD 保存全部 97 个源字段、全部 12 种 `report_type` 和全部修订版本；`core_serving.equity_cashflow` 普通 view 按公司与报告期提供唯一最新合并报表。

```text
公告日 + report_type 多选
  -> DatasetExecutionPlan units
  -> cashflow_vip 全部分页
  -> raw_tushare.cashflow              # HDD 唯一物理表
  -> core_serving.equity_cashflow      # 普通 view
```

确认口径：

1. 页面默认“全部”，后端只保存显式 `1..12`，不允许 `ALL/__ALL__`。
2. raw 保留全部类型和版本；同身份内容修正通过指纹覆盖。
3. serving 只选择 `report_type=1`，优先 `update_flag=1`，否则 `0`，再取最新 `f_ann_date`。
4. `comp_type` 不是可选维护范围，不对运营开放；字段结构固定，不适用科目为空。
5. table heap、PK 和全部索引都在 `gs_raw_cold_hdd`。
6. 支持手动与普通自动任务，不加入 workflow，不做 probe。
7. 初始历史范围后续确定。

## 2. 依据与接口证据

- [Tushare 现金流量表源文档](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/财务数据/0044_现金流量表.md)
- [数据集开发说明模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)
- [A 股财务指标接入方案](/Users/congming/github/goldenshare/docs/datasets/fina-indicator-dataset-development.md)
- [数据集日期模型消费指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)

只读实测结论：

1. 全市场使用 `cashflow_vip`，不按股票池调用普通接口。
2. 2026 半年报项目 connector 分页为 `5000 + 5000 + 379 = 10379` 行。
3. 源文档列出 97 个字段；当前默认响应已包含 97 个，但 Definition 仍必须显式请求完整字段，避免源端默认列未来变化。
4. `2026-08-28` 返回 1,426 行，八个身份字段均无空值；`comp_type` 出现 `1/2/3/4/7`。
5. `600000.SH, period=20260630` 的 `report_type=1/2/6/7` 有数据，其他类型为空。空报表类型是合法结果。
6. `is_calc=1` 的已测样本为空，默认/`0` 有数据。V1 不暴露或传 `is_calc`，避免把可选源参数变成漏数入口。

## 3. 三层语义

| 语义层 | 目标语义 |
| --- | --- |
| 时间输入 | `ann_date` 或公告自然日闭区间，不是现金流报告期。 |
| unit | range 逐自然日展开，再按运营选择的每个 `report_type` 扇出。 |
| freshness/audit | `event_run_trace`；不要求每天有现金流量表公告，不参加日期完整性审计。 |

周末和节假日仍保留。每个 unit 是一个公告自然日和一种报表类型的全部分页事务。

## 4. 报表类型、`comp_type` 与页面

`report_type` 必填、多值，真实值为 `1..12`；中文标签统一引用 [利润表方案第 4 节](/Users/congming/github/goldenshare/docs/datasets/income-dataset-development.md)。Definition 目标：

```text
field_type=list
required=true
multi_value=true
enum_values=("1", ..., "12")
enum_fanout_fields=("report_type",)
enum_fanout_defaults={"report_type": ("1", ..., "12")}
select_all_enabled=true
```

“全部”是前端虚拟控制项：初始选中并禁用 12 个真实选项；取消后清空并启用；再次选中时写回完整真实数组。空选择不能提交，服务端是最终裁决。

通用 contract 需要以 additive 字段提供枚举显示名和 `select_all_enabled`；禁止写 `cashflow` 页面特例。

`comp_type` 原样保存但不作为输入。它说明一行使用一般工商业、银行、保险、证券或其他源端报表科目体系；同一个 `cashflow_vip` 响应字段集合固定，不适用的现金流科目保持 `NULL`。字段不得设置只允许 `1..4` 的数据库约束。

## 5. DatasetDefinition 与请求

| 维度 | 目标值 |
| --- | --- |
| dataset | `cashflow / 现金流量表` |
| domain | `low_frequency / 低频数据` |
| API | `cashflow_vip` |
| fields | 完整 97 字段，显式请求 |
| date model | `natural_day + point_or_range + ann_date_or_start_end` |
| universe | `no_pool` |
| pagination | `offset_limit`, `page_limit=5000` |
| planning | 自然日 builder + `report_type` fan-out |
| storage | `raw_only_upsert + raw_with_serving_view` |
| freshness/audit | `event_run_trace / False` |
| actions | manual + schedule；禁止 workflow/probe |

Request builder：

```json
{"ann_date":"YYYYMMDD","report_type":"1"}
```

禁止传 `comp_type/is_calc/period/start_date/end_date/limit/offset`。分页只由 source client 追加。

## 6. Raw、身份与 HDD

### 6.1 Relations

| Relation | 类型 | 位置 |
| --- | --- | --- |
| `raw_tushare.cashflow` | 97 字段物理宽表 | `gs_raw_cold_hdd` |
| `core_serving.equity_cashflow` | 普通 view | 无独立存储 |

raw 额外保存 `source_content_hash`、`api_name='cashflow_vip'`、`fetched_at`。源数值列使用 nullable `NUMERIC`，空值保持 `NULL`；不重复保存整行 `raw_payload`。

### 6.2 身份与修订

主键 / conflict columns：

```text
(ts_code, ann_date, f_ann_date, end_date,
 report_type, comp_type, end_type, update_flag)
```

1. 不同身份全部保留。
2. 同身份同指纹幂等去重。
3. 同身份不同指纹表示该版本字段被源端修正，覆盖旧内容。
4. 同批次同身份冲突使整个 unit 失败。
5. `update_flag` 必须是 `0/1`，不能默认填补。
6. 响应缺少旧行时不自动删除 raw 历史事实。

### 6.3 索引与 migration

1. 八字段主键。
2. `(ann_date, report_type, ts_code)`。
3. `(report_type, ts_code, end_date, update_flag DESC, f_ann_date DESC, ann_date DESC)`。

表和全部索引必须位于 `gs_raw_cold_hdd`。migration 先验证 tablespace，不存在则 fail-closed。编码时重新读取 Alembic head；当前 `20260829_000161` 只记录方案编写时状态。

## 7. Serving 唯一报表

`core_serving.equity_cashflow` 用普通 view 和 `DISTINCT ON (ts_code, end_date)`：

1. 过滤 `report_type='1'`、`update_flag IN ('0','1')`。
2. `update_flag DESC`。
3. `f_ann_date DESC`。
4. 再按 `ann_date/fetched_at/comp_type/end_type/source_content_hash` 稳定排序。

该规则只定义在数据库 view，不允许页面或查询服务复制实现。

## 8. 事务与性能

1. 单公告日默认 12 个 unit；每种类型先拉完分页，再归一化、校验、upsert、commit。
2. 类型空结果成功；错误、分页不闭合、reject、身份冲突失败。
3. `fetch_concurrency=1`。
4. 单数据集单公告日最多 12 次基础请求；三张表全部类型单日最多 36 次，一年约 13,140 次基础请求。
5. 该请求量是保存所有报表类型的明确取舍，不再通过只取 `report_type=1` 偷减范围。
6. TaskRun 以真实 unit 展示进度；只有 raw 事务提交后才增加完成数。
7. Ops 状态失败不回滚业务数据。

## 9. Ops、测试与里程碑

Ops：

1. 加入 `A股财务数据`，建议顺序 50。
2. 手动支持公告日 point/range 与报表类型多选。
3. 自动任务使用普通 schedule、`since_last_success_day_range` 和显式类型数组。
4. 不加入 workflow、probe、日期完整性审计，不新增专用 API。
5. 修改既有 schedule 的类型选择不追溯历史日期；历史新类型仍由同一手动 `maintain` 区间补齐。

测试门禁：

1. 97 个 fields 始终显式传递，禁止依赖默认返回。
2. point/range、周末、默认 12 类型、子集、空/非法选择、sentinel 拒绝。
3. 空类型合法、分页短页闭合、源错误不产生部分成功假象。
4. `comp_type=7` 与行业专属 nullable 字段。
5. 八字段身份、指纹、修订覆盖和批次冲突。
6. serving 唯一选择顺序。
7. raw-only、HDD fail-closed、Ops 可见与 workflow/probe/audit 排除。

| 里程碑 | 内容 |
| --- | --- |
| M0 | 冻结 97 字段、身份、分页与类型证据；读取真实 migration head |
| M1 | ORM/DAO、HDD migration、serving view |
| M2 | Definition、request builder、normalizer、writer 注册 |
| M3 | 通用多选“全部”交互与手动/自动投影 |
| M4 | 测试、lint、架构和文档检查 |
| M5 | 运营部署、迁移、初始同步与页面验收 |

初始历史范围是唯一待后续确定事项，不阻塞 LLD。
