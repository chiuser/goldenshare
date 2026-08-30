# A 股现金流量表（`cashflow`）数据集接入 LLD v1

状态：**共享 `end_type` 规范化 LLD 已按 Prod 现状对齐；`20260830_000166` 已部署，代码与 migration `20260830_000167` 待实现**
编写日期：2026-08-30
上位方案：[A 股现金流量表接入技术方案 v1](/Users/congming/github/goldenshare/docs/datasets/cashflow-dataset-development.md)

## 1. 目标与边界

本 LLD 只实现 `cashflow_vip -> raw_tushare.cashflow -> core_serving.equity_cashflow`。raw 在 HDD 保存源接口全部 97 个字段、全部 12 种 `report_type` 和全部源站版本；serving 使用普通 view，为每家公司、每个报告期提供唯一最新合并现金流量表。

```text
DatasetActionRequest(cashflow.maintain)
  -> DatasetActionResolver
  -> 公告自然日 x 已选择 report_type 的 units
  -> cashflow_vip 全部分页
  -> normalize / identity gate
  -> raw_tushare.cashflow              # gs_raw_cold_hdd 唯一物理表
  -> core_serving.equity_cashflow      # 普通 view
```

本轮固定边界：

1. 不建 serving 物理表，不双写。
2. 不接任何 workflow，不新增 probe。
3. 不把 `comp_type`、`is_calc`、`period` 暴露为运营参数。
4. 不限制运营可选择的总日期跨度；输入区间由 planner 按自然日拆分。
5. 不新增财务三表专用 API，不在页面按 `dataset_key` 写分支。
6. 不执行生产部署、迁移、历史同步或页面验收。

## 2. 审计结论

### 2.1 源接口事实

依据 [Tushare 现金流量表源文档](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/财务数据/0044_现金流量表.md) 与上位方案已记录的只读实测：

1. 全市场维护必须使用 `cashflow_vip`，不按股票代码池逐只请求普通接口。
2. 2026 半年报范围实际分页为 `5000 + 5000 + 379 = 10379` 行，必须使用 `limit/offset` 拉到短页结束。
3. 源文档定义 97 个输出字段；Definition 必须显式传递完整字段列表，不能依赖源端默认列。
4. 已测现金流公告日的八个前置字段均非空；利润表真实源站数据证明共享字段 `end_type` 可能为 `NULL`，交叉验证确认它可由 `end_date` 唯一推导。三表统一按七字段身份建模，`end_type` 规范化为非空 `1..4` 后保存。
5. `comp_type` 已观测到 `1/2/3/4/7`；它不能被建模为只允许 `1..4` 的封闭枚举。
6. 同一股票与报告期仅部分 `report_type` 有数据。被选择类型返回空集合是合法源端结果，不是同步失败。
7. `is_calc=1` 的已测样本为空，默认或 `0` 有数据。V1 不传 `is_calc`，避免把可选源参数变成静默漏数条件。

### 2.2 当前代码可复用能力

CodeGraph 与逐文件审计覆盖了 `DatasetDefinition -> ActionParameter -> DatasetActionResolver -> unit planner -> request builder -> source client -> normalizer -> writer -> DAO`，以及 catalog、手动任务、自动任务和前端消费者。结论如下：

1. Definition 应加入 `src/foundation/datasets/definitions/low_frequency.py`，继续使用现有 registry。
2. `DatasetSourceClient` 已支持 `offset_limit`：同一 unit 的分页结果全部合并后才进入 normalize/write。
3. `resolve_enum_combinations()` 已能按 Definition 的枚举字段与默认值扇出，但现有自然日 builder 没有把该能力用于财务三表，需要新增共享 builder。
4. `source_multiplicity_policy="deduplicate_identical"` 已能去掉分页重叠产生的完全相同行。
5. `batch_unique_key_fields` 已能在 DML 前拒绝同一身份、不同内容的批内冲突。
6. `raw_only_upsert` 与 `GenericDAO.bulk_upsert` 已能完成跨任务同身份修订覆盖，不需要专用 writer 或 DAO 写法。
7. `fina_indicator` 已提供 HDD fail-closed migration、raw-only 写入和普通 serving view 的同类参考。
8. 当前 Ops 参数契约没有枚举中文标签与虚拟全选元数据；手动和自动页面已有多选控件，但会显示原始值且不支持“全部”。该能力必须通过共享 contract 一次性补齐。

### 2.3 本 LLD 不采用的路径

1. 不把 12 种报表类型塞进一个源请求：源接口每次只接收一个 `report_type`。
2. 不用 `ALL/__ALL__` 作为业务值：它既不是源接口参数，也不是数据身份。
3. 不按股票池扇出：`cashflow_vip` 已支持按公告日拉全市场。
4. 不以 `end_date` 作为维护时间输入：运营维护的是公告日，报告期只属于返回数据。
5. 不根据 `comp_type` 动态切换表结构：97 列固定，不适用科目保持 `NULL`。

## 3. 共享财务报表契约

新增：

```text
src/foundation/datasets/financial_statement_contracts.py
```

该文件由 `income/balancesheet/cashflow` 共同引用，只定义三张表真正共享的事实：

```python
FINANCIAL_STATEMENT_REPORT_TYPE_VALUES = (
    "1", "2", "3", "4", "5", "6",
    "7", "8", "9", "10", "11", "12",
)

FINANCIAL_STATEMENT_REPORT_TYPE_LABELS = {
    "1": "合并报表",
    "2": "单季合并",
    "3": "调整单季合并表",
    "4": "调整合并报表",
    "5": "调整前合并报表",
    "6": "母公司报表",
    "7": "母公司单季表",
    "8": "母公司调整单季表",
    "9": "母公司调整表",
    "10": "母公司调整前报表",
    "11": "母公司调整前合并报表",
    "12": "母公司调整前报表（源站代码 12）",
}

FINANCIAL_STATEMENT_IDENTITY_FIELDS = (
    "ts_code",
    "ann_date",
    "f_ann_date",
    "end_date",
    "report_type",
    "comp_type",
    "update_flag",
)
```

禁止把某一张表的业务字段、DAO 名称或表名放进共享文件。若三张表分批开发，第一张负责落地共享契约，后续两张只消费，不复制常量。

## 4. 现金流量表字段 contract

新增：

```text
src/foundation/datasets/cashflow_contracts.py
```

文件固定定义：

```python
CASHFLOW_SOURCE_FIELDS       # 0044 源文档固定顺序的全部 97 字段
CASHFLOW_DECIMAL_FIELDS      # 89 个数值字段
CASHFLOW_DATE_FIELDS = ("ann_date", "f_ann_date", "end_date")
```

编码门禁：

1. `len(CASHFLOW_SOURCE_FIELDS) == 97`。
2. 前七字段必须依次为 `ts_code, ann_date, f_ann_date, end_date, report_type, comp_type, end_type`。
3. 最后一字段必须是 `update_flag`。
4. `len(CASHFLOW_DECIMAL_FIELDS) == 89`。
5. 七字段身份必须引用 `FINANCIAL_STATEMENT_IDENTITY_FIELDS`，不得在本文件重新抄写；`end_type` 由 `end_date` 唯一推导，不重复进入身份。
6. 97 字段只能依据 0044 源文档逐列冻结，不能从一次默认响应动态推导。

完整源字段已经逐列入表，因此不再重复保存整行 `raw_payload`。额外只增加：

```text
source_content_hash
api_name
fetched_at
```

## 5. DatasetDefinition 编码方案

在 `src/foundation/datasets/definitions/low_frequency.py` 新增 `cashflow`：

| 维度 | 代码值 |
| --- | --- |
| identity | `cashflow / 现金流量表` |
| source | `cashflow_vip`, `CASHFLOW_SOURCE_FIELDS`, `tushare.cashflow` |
| request builder | `_cashflow_vip_params` |
| date model | `natural_day / not_applicable / point_or_range / ann_date_or_start_end` |
| input | 公告日期点/区间 + 必填多选 `report_type` |
| universe | `no_pool` |
| planning | `build_financial_statement_units`, `offset_limit`, `page_limit=5000` |
| storage | `raw_only_upsert`, `raw_with_serving_view` |
| raw target | `raw_tushare.cashflow` |
| serving | `core_serving.equity_cashflow` |
| freshness | `event_run_trace` |
| date audit | `False` |
| capability | manual + regular schedule |

filter 与 fanout 固定为：

```python
{
    "name": "report_type",
    "field_type": "list",
    "required": True,
    "multi_value": True,
    "enum_values": FINANCIAL_STATEMENT_REPORT_TYPE_VALUES,
    "option_labels": FINANCIAL_STATEMENT_REPORT_TYPE_LABELS,
    "select_all_enabled": True,
    "display_name": "报表类型",
}

"enum_fanout_fields": ("report_type",),
"enum_fanout_defaults": {
    "report_type": FINANCIAL_STATEMENT_REPORT_TYPE_VALUES,
},
```

质量与事务配置：

```python
"required_fields": (*FINANCIAL_STATEMENT_IDENTITY_FIELDS, "end_type", "source_content_hash"),
"unit_date_field": "ann_date",
"batch_unique_key_fields": FINANCIAL_STATEMENT_IDENTITY_FIELDS,
"source_multiplicity_policy": "deduplicate_identical",
"reject_policy": "fail_unit_on_any_rejection",
"empty_result_policy": "allow",
"commit_policy": "unit",
```

`date_model.bucket_rule=not_applicable` 在这里仅表示“不做连续公告日 freshness/audit”，不表示无日期输入。schedule 使用 `since_last_success_day_range`；Definition 不声明 workflow 或 probe。

## 6. 通用多选“全部”契约

该能力是三张财务表的共享前置，不属于 `cashflow` 页面特例。

### 6.1 后端 contract

为 `DatasetInputField` 增加 additive 字段：

```python
option_labels: dict[str, str] = field(default_factory=dict)
select_all_enabled: bool = False
```

同步投影到：

1. `src/ops/action_catalog.py::ActionParameter`。
2. `src/ops/schemas/catalog.py::ActionParameterResponse`。
3. `CatalogQueryService` 的所有参数响应。
4. `ManualActionQueryService` 的参数转换与响应。
5. `frontend/src/shared/api/types.ts`。

默认值与显式空的语义必须分开：

1. 请求未携带 `report_type`：validator 使用 `planning.enum_fanout_defaults`，得到真实 `1..12`。
2. 请求显式携带 `report_type=[]`：服务端拒绝，不允许先丢掉空值再补默认。
3. 任一非法值或 `all/ALL/__ALL__`：服务端拒绝。
4. schedule `params_json` 只保存真实值数组。

需要同时修正 `ManualActionService` 与 schedule 校验消费者，避免手动和自动任务对“缺失”和“显式空”产生不同语义。

### 6.2 前端共享组件

新增：

```text
frontend/src/shared/ops-enum-multi-select.tsx
```

组件只读取参数元数据，不读取 `dataset_key`：

1. `select_all_enabled=false` 时保持普通多选。
2. `select_all_enabled=true` 且当前值集合等于完整 options 时，显示“全部”选中，真实选项选中并禁用。
3. 取消“全部”时写入 `[]`，解锁真实选项；页面校验阻止提交。
4. 再次选择“全部”时写回完整真实值数组。
5. 标签优先读 `option_labels[value]`，缺失时回退显示原值。

手动任务页与自动任务页都复用该组件。禁止在任一页面写 `cashflow`、`income` 或 `balancesheet` 分支。

## 7. Unit planner 与请求参数

### 7.1 共享 unit builder

在 `src/foundation/ingestion/unit_planner.py` 新增并注册：

```text
build_financial_statement_units
```

算法固定为：

1. 从 validated request 获取 point 或 range。
2. point 只产生一个公告自然日；range 使用 `_expand_natural_dates()` 展开闭区间每个自然日。
3. 调用 `resolve_enum_combinations()` 获取 `report_type` 组合。
4. 以日期为外层、报表类型为内层，按 `1..12` 的固定顺序生成 unit。
5. 不读取交易日历，不读取股票池，不发外部请求。

unit 样例：

```json
{
  "unit_id": "cashflow:20260830:report_type=1",
  "anchor_date": "2026-08-30",
  "enum_values": {"report_type": "1"}
}
```

行为门禁：

- point + 默认类型：12 个 unit。
- 两个自然日 range + 默认类型：24 个 unit，包括周末/节假日。
- 显式 `1/6`：每个日期只生成 2 个 unit。
- 空数组、非法值和哨兵值在生成 unit 前失败。

### 7.2 Request builder

在 `src/foundation/ingestion/request_builders.py` 新增并注册 `_cashflow_vip_params`。它只返回：

```json
{"ann_date":"20260830","report_type":"1"}
```

实现要求：

1. `anchor_date` 缺失立即失败。
2. `report_type` 必须是一个真实字符串值且属于 `1..12`。
3. 不向源端传 `comp_type/is_calc/period/start_date/end_date`。
4. 不由 request builder 传 `fields/limit/offset`；fields 来自 Definition，分页由 source client 添加。

## 8. Normalizer 与冲突语义

在 `src/foundation/ingestion/row_transforms.py` 增加三表共享 helper 和 `_cashflow_row_transform` wrapper。转换顺序：

1. 清除所有字符串字段中的 NUL。
2. `ts_code` trim 并转大写。
3. `ann_date/f_ann_date/end_date` 转为 `date`，缺失或非法拒绝。
4. `report_type` 只接受 `1..12`。
5. `update_flag` 只接受 `0/1`，禁止默认填补。
6. `comp_type` 必须非空但不限制为封闭枚举；`comp_type=7` 必须通过。
7. 共享 helper 按 `end_date` 推导 `end_type=1..4`：缺失补齐，非法或与日期矛盾时拒绝。
8. 对 `CASHFLOW_SOURCE_FIELDS` 的规范化值按固定顺序生成 `source_content_hash`；批次去重与冲突比较优先使用该规范化指纹。

89 个数值字段由标准 normalizer 转为 nullable `Decimal`。银行、保险、证券或一般企业不适用的现金流科目保持 `NULL`，不能补 0。

批内与跨任务语义：

```text
完全相同源行
  -> deduplicate_identical
  -> 只保留一行

同一七字段身份、不同业务内容
  -> batch_unique_key_conflicting
  -> 整个 unit 失败，不写部分数据

后续任务再次返回同一身份、内容已修订
  -> raw upsert
  -> 覆盖该身份的旧字段、hash 与 fetched_at
```

这正是已拍板的“保留不同源版本，但同身份修订覆盖错误旧内容”。不得另建版本表或自定义写入分支。

## 9. ORM、DAO 与 HDD migration

### 9.1 ORM

新增：

```text
src/foundation/models/raw/raw_cashflow.py
```

模型要求：

1. `__tablename__ = "cashflow"`，schema 为 `raw_tushare`。
2. 七个身份字段组成复合主键；规范化后的 `end_type` 非空但不参与主键。
3. 89 个源数值字段使用 nullable `Numeric`。
4. 字符串字段按源语义使用 `String`，日期字段使用 `Date`。
5. `source_content_hash` 非空；`api_name` 默认 `cashflow_vip`；`fetched_at` 非空。
6. 不定义 `raw_payload`，不定义 serving ORM。

同步更新：

- `src/foundation/models/raw/__init__.py`
- `src/foundation/models/all_models.py`
- `src/foundation/models/table_registry.py`
- 相关 ORM/table registry 测试

### 9.2 DAO

在 `src/foundation/dao/factory.py` 注册 `raw_cashflow`，复用 `GenericDAO`。Definition 的 `raw_dao_name` 与 `core_dao_name` 均指向该 raw DAO；`raw_only_upsert` 路径不得调用任何 serving DAO。

### 9.3 Alembic

初始三表迁移顺序为 `income -> balancesheet -> cashflow`。Prod 已执行 `20260830_000166`，当前三表主键均为七字段，`end_type` 均为 nullable；不改写该已部署 migration。新增 `20260830_000167`（`down_revision=20260830_000166`）：先检查表和七字段主键现状，再拒绝非季度末、非法非空值和与 `end_date` 矛盾的行，仅对空值执行确定性补齐，最后恢复 `end_type NOT NULL`。该 migration 不重建主键/索引，不移动 tablespace，不删除任何业务数据。

upgrade 顺序：

1. 在任何业务 DDL 前检查 `pg_tablespace` 存在 `gs_raw_cold_hdd`；不存在立即失败。
2. 创建 `raw_tushare.cashflow`，table heap 指向 HDD。
3. 创建复合 PK，并明确将 PK index 移到 HDD。
4. 创建两个二级索引，均显式 `TABLESPACE gs_raw_cold_hdd`：
   - `(ann_date, report_type, ts_code)`
   - `(report_type, ts_code, end_date, update_flag DESC, f_ann_date DESC, ann_date DESC)`
5. 创建 `core_serving.equity_cashflow` 普通 view。
6. 验证 heap、PK 与两个索引的 `reltablespace` 全部指向 HDD。

downgrade 不允许删除业务表或数据；按仓库硬规则直接抛出明确 `RuntimeError`，提示该迁移不可自动回退。

## 10. Serving view

`core_serving.equity_cashflow` 的唯一选择规则只写在 migration SQL：

```sql
CREATE VIEW core_serving.equity_cashflow AS
SELECT DISTINCT ON (ts_code, end_date)
       <97 source columns>,
       source_content_hash,
       api_name,
       fetched_at
FROM raw_tushare.cashflow
WHERE report_type = '1'
  AND update_flag IN ('0', '1')
ORDER BY
    ts_code,
    end_date,
    update_flag DESC,
    f_ann_date DESC,
    ann_date DESC,
    fetched_at DESC,
    comp_type DESC,
    end_type DESC,
    source_content_hash DESC;
```

业务含义：

1. 只对外提供合并报表。
2. 同报告期优先源端明确标记的更新版本。
3. 同一更新标志下优先最新实际公告日期。
4. 剩余字段只用于稳定、可复现地消除并列，不代表新增业务优先级。

页面、Biz 查询和 API 不得复制这段排序或自行拼装“最新报表”。它们只查询 view。

## 11. Ops、freshness 与运行时注册

### 11.1 Catalog 与操作入口

在 Ops 默认展示目录 `equity_financial` 新增：

```text
cashflow / 现金流量表 / order=50
```

Definition 自动投影出：

- 手动维护：公告日期点/区间 + 报表类型多选。
- 普通自动任务：`since_last_success_day_range` + 报表类型多选。

不增加前端专用接口，不加入 workflow/probe，不参加日期完整性审计。

### 11.2 Freshness

在 `src/foundation/datasets/freshness_policies.py` 将 `cashflow` 映射为 `EVENT_RUN_TRACE`。上层每次从 DatasetDefinition projection 获取该事实，不写入 snapshot 副本。

### 11.3 Runtime guardrail

更新低频数据集 runtime 期望集合，加入 `cashflow`。同时补负向断言：

1. workflow definitions 不含 `cashflow`。
2. probe condition/binding 不含 `cashflow`。
3. date completeness audit 不含 `cashflow`。

## 12. 逐文件编码清单

### 12.1 共享能力，仅实现一次

| 文件 | 改动 |
| --- | --- |
| `src/foundation/datasets/financial_statement_contracts.py` | 12 类报表、中文标签、七字段身份。 |
| `src/foundation/datasets/models.py` | `DatasetInputField` 增加标签和虚拟全选元数据。 |
| `src/foundation/ingestion/validator.py` | 缺失 filter 读取 fanout 默认；显式空仍拒绝。 |
| `src/foundation/ingestion/unit_planner.py` | 新增并注册财务报表共享 builder。 |
| `src/foundation/ingestion/row_transforms.py` | 新增财务报表共享规范化/hash helper。 |
| `src/ops/action_catalog.py` | 投影默认值、标签和全选元数据。 |
| `src/ops/schemas/catalog.py` | API response 新字段。 |
| `src/ops/queries/catalog_query_service.py` | catalog 消费与响应投影。 |
| `src/ops/queries/manual_action_query_service.py` | manual action 消费与响应投影。 |
| `src/ops/services/manual_action_service.py` | 区分缺失与显式空。 |
| `frontend/src/shared/api/types.ts` | 接收后端契约。 |
| `frontend/src/shared/ops-enum-multi-select.tsx` | 通用多选“全部”组件。 |
| 手动/自动任务页 | 复用共享组件，不写数据集分支。 |

### 12.2 `cashflow` 专属文件

| 文件 | 改动 |
| --- | --- |
| `src/foundation/datasets/cashflow_contracts.py` | 97 字段、89 数值字段、日期字段。 |
| `src/foundation/datasets/definitions/low_frequency.py` | 新增 Definition。 |
| `src/foundation/ingestion/request_builders.py` | 新增 `_cashflow_vip_params`。 |
| `src/foundation/ingestion/row_transforms.py` | 注册 `_cashflow_row_transform` wrapper。 |
| `src/foundation/models/raw/raw_cashflow.py` | raw ORM。 |
| raw/all model registry | 注册 ORM/table。 |
| `src/foundation/dao/factory.py` | 注册 raw DAO。 |
| `src/foundation/datasets/freshness_policies.py` | 注册 `event_run_trace`。 |
| Ops 展示目录 | `equity_financial` order 50。 |
| 新 Alembic revision | HDD 表、PK、索引、serving view。 |
| `tests/test_financial_statement_datasets.py` | 三张财务报表共享契约与数据集主测试。 |
| 架构/runtime/Ops 测试 | 更新事实集合和负向护栏。 |

### 12.3 本次 `end_type` 规范化收口

本表不建立独立规范化实现，直接复用 [利润表 LLD 第 10.1 节](/Users/congming/github/goldenshare/docs/datasets/income-low-level-design-v1.md)的共享 contract、row transform、normalizer、codebook 和 `000167`。本表专属改动只有 `RawCashflow.end_type nullable=False`、Definition 必填字段断言与共享测试 fixture。

## 13. 测试矩阵

| 层级 | 必测内容 |
| --- | --- |
| contract | 97/89 数量、固定首尾字段、共享七字段身份、规范化非空 `end_type`。 |
| Definition | API、fields、日期模型、no_pool、分页、raw/view、freshness、audit。 |
| input | 默认全类型、任意子集、空数组、非法值、`ALL/__ALL__` 拒绝。 |
| planner | point=类型数；range=自然日数×类型数；周末保留；不查交易日历/股票池。 |
| request | 只传 `ann_date/report_type`，不得泄漏 `is_calc/comp_type/period/start/end/pagination`。 |
| source | `5000+5000+379` 分页，短页停止，空第一页为合法空 unit。 |
| normalize | NUL、日期、Decimal、`comp_type=7`、nullable 科目、`end_type` 推导/一致性校验、规范化 hash 稳定。 |
| conflict | 相同源行去重；批内同身份不同内容失败；跨任务修订覆盖。 |
| writer | 只调 raw DAO；一个 unit 全部分页后一次事务提交。 |
| migration | `000167` 仅校验/补齐 `end_type` 并恢复 `NOT NULL`；不改主键、索引、tablespace 或 view。 |
| serving | `report_type=1`、更新标志、实际公告日、稳定并列排序。 |
| Ops/API | 中文标签、虚拟全选、真实数组、显式空拒绝、manual/schedule 可见。 |
| exclusions | 不进 workflow/probe/date completeness，无 Biz 专用 API。 |

关键负向测试不能只检查错误字符串，还要证明没有生成 plan、没有发源请求、没有调用 DAO。

## 14. 开发步骤

1. 复用利润表 LLD 的 `N0-N5` 共享收口顺序，不另建 cashflow 分支。
2. 证明空值、正确值、非法值、矛盾值、非季度末和批次规范化去重在 cashflow Definition 上行为一致。
3. 证明 `000167` 对空 cashflow 表仍可完成约束恢复，且不生成任何删除或主键 DDL。
4. 运行定向、codebook、架构、Definition lint 和 docs 检查，再更新文档为“代码已实现，待运营部署 migration `000167` 与验收”。

停止条件（本次规范化收口）：

- Prod 不是 `000166`/七字段主键现状。
- 存量值非法或矛盾，且无明确业务口径可处理。
- 共享 normalizer 指纹优先级调整导致其他数据集回归。
- `000167` 需要扩大到主键、tablespace、view 或删除操作。

初次数据集接入的历史停止条件：

- 97 字段或分页闭合与源端证据不一致。
- 同一完整身份在单次响应中出现无法解释的不同内容。
- migration 无法保证 heap、PK、全部索引都在 HDD。
- serving 选择规则不能通过 SQL fixture 唯一复现。
- Ops/UI 需要 `cashflow` 私有分支才能实现。

## 15. 验证命令

```bash
uv run ruff check src/foundation/datasets src/foundation/ingestion src/foundation/models/raw/raw_cashflow.py src/foundation/dao/factory.py src/ops tests/test_financial_statement_datasets.py
uv run pytest -q tests/test_financial_statement_datasets.py tests/test_dataset_definition_registry.py tests/test_foundation_table_model_registry.py
uv run pytest -q tests/web/test_ops_catalog_api.py tests/web/test_ops_manual_actions_api.py tests/web/test_ops_schedule_api.py
uv run pytest -q tests/architecture/test_subsystem_dependency_matrix.py tests/architecture/test_dataset_runtime_registry_guardrails.py
uv run goldenshare ingestion-lint-definitions
cd frontend && npm run test -- ops-enum-multi-select ops-v21-task-manual-tab ops-v21-task-auto-tab
cd /Users/congming/github/goldenshare && python3 scripts/check_docs_integrity.py
```

## 16. 交付状态定义

开发完成后只能把本数据集标记为“代码已实现，待运营部署与验收”。初始历史范围、生产 migration、历史同步和页面验收仍由运营后续执行，不得在开发阶段自行运行生产写操作。

开发验收必须证明：

1. 97 个源字段、12 种报表类型和全部不同身份版本写入 raw。
2. 同身份源端修订可覆盖，同批冲突会整体失败。
3. raw heap、PK、索引全部在 HDD；serving 无第二份物理数据。
4. 页面和 schedule 只保存真实类型数组，不出现任何 ALL 哨兵。
5. serving view 每公司每报告期只返回唯一最新合并报表。
