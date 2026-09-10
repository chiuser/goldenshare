# A 股利润表（income）维护说明与财务三表共用规则

更新时间：2026-09-10。已实现；2026-08-30 已完成下文所列初始范围的 Prod 验收，原开发需求关闭。本次将 LLD 有效细节并入本文，不重新认证当前生产数据、源接口或部署状态。

## 1. 范围与阅读入口

`income.maintain` 按公告自然日维护全市场利润表，使用 `income_vip`，不是按证券池调用普通 income 接口。

`Ops 手动/普通自动任务 → DatasetActionResolver → 公告自然日×report_type units → VIP 分页 → 规范化与身份校验 → Raw upsert → Serving 普通 view`。

本文 §2 集中说明 income、[balancesheet](/Users/congming/github/goldenshare/docs/datasets/balancesheet-dataset-development.md)、[cashflow](/Users/congming/github/goldenshare/docs/datasets/cashflow-dataset-development.md) 共用规则；各表字段、源端样本和验收证据分别维护，不复制三套共享实现。变更门禁仍见[数据集模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)及[执行计划说明](/Users/congming/github/goldenshare/docs/architecture/dataset-execution-plan-refactor-plan-v1.md)，本文不是再次部署、迁移或全量同步授权。

<a id="financial-statement-shared-rules"></a>

## 2. 财务三表共用规则

### 2.1 时间、输入与执行单元

| 维度 | 当前事实 |
| --- | --- |
| 日期输入 | 单公告日 ann_date，或公告自然日 start_date/end_date 闭区间；不是报告期 end_date |
| 日期模型 | natural_day / not_applicable / point_or_range / ann_date_or_start_end；observed_field=ann_date |
| 股票范围 | no_pool；不读证券池，不用交易日历过滤周末或节假日 |
| 类型输入 | report_type 必填、多值，真实值为字符串 1..12；缺失时用 enum_fanout_defaults，显式空拒绝 |
| unit | 已注册的 build_financial_statement_units；日期为外层，类型按 1..12 顺序为内层 |
| 请求 | 三个 VIP builder 共用 _financial_statement_vip_params，只生成 ann_date=YYYYMMDD 与单个 report_type |
| 源字段/分页 | Definition 显式 fields；source client 追加 limit/offset，page_limit=5000，短页结束 |
| 不向源端传递 | 股票过滤、comp_type、period、is_calc、原始 start/end 区间或任何 ALL 哨兵；分页不在 builder 手写 |

两个自然日默认 24 units；选择 1/6 时每天 2 units。unit 的现行字段为 trade_date、request_params、progress_context 等，不另定义 anchor_date/enum_values 的对外计划结构。完整结构和生成算法见[unit_planner.py](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py)与[plan_helpers.py](/Users/congming/github/goldenshare/src/foundation/ingestion/plan_helpers.py)。

单日 12、三表 36 是**各 unit 至少请求一次的基础量，不是实际请求上限**；365 天三表约 13,140 次基础请求，分页、满页后终止探测和重试另计。不能通过只取类型 1 缩减已选范围。当前 fetch_concurrency=1，无总日期跨度硬上限；这些不等于已证明任意长任务的内存、耗时或强制退出续跑达标。

### 2.2 通用多选与消费者

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

标签和全选元数据已由 `DatasetInputField.option_labels/select_all_enabled` 投影到 Ops 参数与前端，**不是待新增能力**：

- 模型检查标签 key 属于 enum_values，启用全选要求多值且枚举非空；未配标签的普通枚举可回退显示原值。
- 手动与自动页面共用 [OpsEnumMultiSelect](/Users/congming/github/goldenshare/frontend/src/shared/ui/ops-enum-multi-select.tsx)，只消费 options、标签、value 等元数据，不按数据集 key 写分支。
- 默认完整数组使“全部”选中，真实选项选中且禁用；取消全部写回空数组并恢复选择；再次全选写回真实 1..12。
- 缺失 report_type 使用 Definition 默认值；显式空、非法值或 all/ALL/__ALL__ 必须拒绝，不能丢掉空输入再补默认。手动/自动 API 对无效提交返回 422。
- TaskRun filters_json、schedule params_json.filters 保存真实值数组，不保存虚拟全选值。
- comp_type 必须非空，但不限制为 1..4、不向运营开放；不同公司类型适用的科目不同，宽表字段集合固定，不适用数值为 NULL，不能填 0。

### 2.3 Raw 身份、规范化与修订

共享身份直接来自 [financial_statement_contracts.py](/Users/congming/github/goldenshare/src/foundation/datasets/financial_statement_contracts.py)：

`(ts_code, ann_date, f_ann_date, end_date, report_type, comp_type, update_flag)`。

七字段身份不能与源字段列表的前七列混淆：源字段前部还含 end_type，而身份含 update_flag。三表保留全部不同身份和已选择类型；同身份的内容修正允许覆盖，不是无限保留每次拉取副本。

1. 标准 normalizer 转 Date/Decimal；共享 row transform 清 NUL、代码 trim/upper，校验三个日期、非空身份、report_type=1..12 和 update_flag=0/1。
2. end_type 不入身份：按 end_date 的 03-31/06-30/09-30/12-31 映射为 1/2/3/4，缺失补齐，非空值必须匹配。
3. 非季度末报 `normalize.financial_statement_end_date_invalid`，非法 end_type 报 `normalize.invalid_enum:end_type`，矛盾报 `normalize.end_type_mismatch`；禁止静默覆盖矛盾值。
4. 对全部规范化源字段计算 SHA-256 source_content_hash；先 NULL、后正确 end_type 得到同一指纹。
5. `deduplicate_identical` 和批次唯一检查优先使用规范化 source_content_hash，未提供时才回退隐藏原始指纹。同批同身份同内容去重，异内容报 `normalize.batch_unique_key_conflicting` 并使 unit 失败。
6. 跨任务同身份修订由 Raw upsert 更新业务列、指纹及 fetched_at；不因本次响应少了旧身份而删除历史行。
7. Raw 逐列保存源字段，另存 source_content_hash、api_name、fetched_at，不重复保存整行 raw_payload。三个日期为 Date，数值列 nullable Numeric；七个身份字段和规范化后的 end_type 非空。

质量设置为 `fail_unit_on_any_rejection`、`empty_result_policy=allow`、`unit_date_field=ann_date`，身份字段同时用于 batch_unique_key_fields。每个 unit 完整获取分页后再归一化、校验、写 Raw 并按 unit 提交；中间页错误不能拿已获取的部分结果冒充完整成功。合法空类型可零行成功。

raw/core DAO 名均指向各表的 Raw GenericDAO；`raw_only_upsert` 实际不调用 Serving DAO、不做第二次写入。Ops 状态写入不得回滚已经提交的业务事务。详细的持久化、取消和恢复能力边界归执行计划说明；不把幂等 upsert 等同于已证明进程退出后无损续跑。

### 2.4 Serving 与物理存储

三张 Raw 表、主键及两个二级索引均要求位于 `gs_raw_cold_hdd`。二级索引分别为公告日/类型/代码，以及类型/代码/报告期/更新标志/实际公告日/公告日。Serving 是普通 view，无独立物理数据。

每个 view 对 `(ts_code, end_date)` 使用 DISTINCT ON：

1. 仅 `WHERE report_type='1'`。
2. `CASE update_flag WHEN '1' THEN 0 ELSE 1 END` 优先更新版本；正常入库 flag 已限制为 0/1。
3. 再依次按 f_ann_date、ann_date、fetched_at、comp_type、end_type、source_content_hash 降序消除并列。
4. 输出全部源字段和 source_content_hash/api_name/fetched_at。选择规则归数据库 view，页面和查询服务不复制算法。

准确 SQL 见各表初始迁移，不再复制易漂移的 SQL 草图。例如较旧 f_ann_date 的 flag=1 优先于较新 f_ann_date 的 flag=0，不是单纯取最大公告日。

### 2.5 Ops 与调度

- 支持 manual、regular schedule、retry；没有 workflow/probe，不新增财务专用 API。
- 普通 schedule 使用 `since_last_success_day_range`，策略参数 initial_start_date 必填；日期由策略生成，不在 schedule 手填 point/range 日期。类型数组按配置保存。
- 修改 schedule 的类型选择不追溯补历史；需要补过去的新类型，仍用同一手动 maintain 区间。
- freshness 为 event_run_trace，日期完整性审计关闭。not_applicable 只是不要求每日有公告，不是无日期输入；空公告日成功维护也有运行迹象。
- Policy 从 Definition projection 获取，不另存 snapshot Policy 副本；现行状态 snapshot 本身仍保留。卡片不能仅用 max(ann_date) 与今天比较后判滞后。
- 默认 Ops 展示组 equity_financial（A股财务数据），income/balancesheet/cashflow 顺序为 30/40/50。

<a id="financial-statement-implementation"></a>

### 2.6 当前文件与消费者索引

以下是**已存在的实现位置**，替代三份 LLD 的“待新增文件”清单：

| 责任 | 位置 |
| --- | --- |
| 字段、定义与输入合同 | [共享财务合同](/Users/congming/github/goldenshare/src/foundation/datasets/financial_statement_contracts.py)、各表 contracts、[low_frequency.py](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/low_frequency.py)、[models.py](/Users/congming/github/goldenshare/src/foundation/datasets/models.py) |
| 默认/显式空、规划与请求 | [validator.py](/Users/congming/github/goldenshare/src/foundation/ingestion/validator.py)、[unit_planner.py](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py)、[request_builders.py](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py) |
| 分页与质量 | [source_client.py](/Users/congming/github/goldenshare/src/foundation/ingestion/source_client.py)、[row_transforms.py](/Users/congming/github/goldenshare/src/foundation/ingestion/row_transforms.py)、[normalizer.py](/Users/congming/github/goldenshare/src/foundation/ingestion/normalizer.py)、[codebook.py](/Users/congming/github/goldenshare/src/foundation/ingestion/codebook.py) |
| 写入、模型注册 | [writer.py](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py)、[factory.py](/Users/congming/github/goldenshare/src/foundation/dao/factory.py)、[all_models.py](/Users/congming/github/goldenshare/src/foundation/models/all_models.py)、[table_model_registry.py](/Users/congming/github/goldenshare/src/foundation/models/table_model_registry.py) |
| Ops 参数与响应 | [action_catalog.py](/Users/congming/github/goldenshare/src/ops/action_catalog.py)、[catalog schema](/Users/congming/github/goldenshare/src/ops/schemas/catalog.py)、[catalog query](/Users/congming/github/goldenshare/src/ops/queries/catalog_query_service.py)、[manual query](/Users/congming/github/goldenshare/src/ops/queries/manual_action_query_service.py) |
| 提交消费者 | [manual_action_service.py](/Users/congming/github/goldenshare/src/ops/services/manual_action_service.py)、[task_run_service.py](/Users/congming/github/goldenshare/src/ops/services/task_run_service.py) |
| 观测与展示组 | [freshness_policies.py](/Users/congming/github/goldenshare/src/foundation/datasets/freshness_policies.py)、[dataset_catalog_views.py](/Users/congming/github/goldenshare/src/ops/catalog/dataset_catalog_views.py) |
| 前端参数与页面 | [types.ts](/Users/congming/github/goldenshare/frontend/src/shared/api/types.ts)、[手动页](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-task-manual-tab.tsx)、[自动页](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-task-auto-tab.tsx)、§2.2 共享组件 |

<a id="financial-statement-migration-history"></a>

## 3. 财务三表迁移沿革（历史，不是重跑清单）

| Revision | 当时作用与保留边界 |
| --- | --- |
| [000163](/Users/congming/github/goldenshare/alembic/versions/20260830_000163_add_income_dataset.py) / [000164](/Users/congming/github/goldenshare/alembic/versions/20260830_000164_add_balancesheet_dataset.py) / [000165](/Users/congming/github/goldenshare/alembic/versions/20260830_000165_add_cashflow_dataset.py) | 依次创建三表与 view；初版含 end_type 的八字段主键。建表前检查 PostgreSQL 和 HDD tablespace，heap/PK/二级索引显式落 HDD |
| [000166](/Users/congming/github/goldenshare/alembic/versions/20260830_000166_allow_financial_statement_end_type_null.py) | 三表改为七字段主键，end_type 暂时允许 NULL；保留已部署迁移原意，不改写 |
| [000167](/Users/congming/github/goldenshare/alembic/versions/20260830_000167_enforce_financial_statement_end_type.py) | 前向校验并仅补齐空 end_type，再恢复 NOT NULL；不重建 PK/索引、不移动 tablespace、不改 view、不删除业务行 |

修正动因：TaskRun 10189 暴露源站 end_type=NULL，后续交叉验证确认季度映射。000166 后的中间只读审计记录 income 为 116 行、另外两表为空；那不是今天的行数。000167 在执行时检查三表、七字段主键、季度末和非空值一致性，拒绝非法/矛盾数据，再补空值并复核，不用历史空表结论跳过检查；自动 downgrade 被拒绝。

原 N0～N5 是这次已完成收口的施工顺序，不再要求后续运维把生产退回 000166。未来迁移仍要重新确认真实 head、并发写入与数据风险并取得授权；原部署要求避免三表任务与迁移并发写入，不是本轮停 worker 或重跑迁移指令。

## 4. income 专属合同与历史源端证据

- 来源：doc_id=33，[本地利润表说明](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/财务数据/0033_利润表.md)。
- [income_contracts.py](/Users/congming/github/goldenshare/src/foundation/datasets/income_contracts.py)：94 个显式源字段、86 个数值字段，日期为 ann_date/f_ann_date/end_date；字段顺序及数量由合同和测试固定，不从默认响应猜测。
- [RawIncome](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_income.py) 与 DAO raw_income：`raw_tushare.income`；view 为 `core_serving.equity_income`，api_name 默认 income_vip。
- Definition 调用共享 helper，使用 `_income_vip_params`、`_income_row_transform`；不是再次新增独立 planner/writer。

以下为原 2026-08-29～30 接入记录中的源端证据，本轮未重新请求：

1. 普通 `income` 以单只股票历史查询为主；全市场维护应使用 `income_vip`。
2. 项目 connector 对 2026 半年报范围实测分页为 `5000 + 5000 + 409 = 10409` 行，说明必须使用 `limit/offset` 拉到短页结束。
3. 源文档共列出 94 个输出字段；默认响应只有 84 个，实施必须显式请求完整 94 字段。
4. `2026-08-28` 返回 1,442 行，八个前置字段均无空值；但 `2026-01-09` 的真实源站响应中，`601112.SH / 2024-09-30 / report_type=1` 的 `end_type` 为 `NULL`。同公司其他报告期与 `600000.SH / 2024-09-30` 交叉验证确认映射为：`03-31→1`、`06-30→2`、`09-30→3`、`12-31→4`，因此该缺失值应规范化为 `3`。
5. 同日实测 `comp_type` 出现 `1/2/3/4/7`；值 `7` 的样本为 `002961.SZ 瑞达期货`。本地源文档仅说明 `1..4`，因此不得把 `comp_type` 建成封闭枚举。
6. 对 `600000.SH, period=20260630` 显式请求各报表类型时，`1/2/6/7` 有数据，其他类型可以为空。所选类型空结果是合法源端事实，不能使 unit 失败。
7. `update_flag=0/1` 都真实存在；只请求或只保存其中一个都会漏源站版本。

<a id="financial-statement-regression"></a>

## 5. 回归与验收要求

三表共用 [test_financial_statement_datasets.py](/Users/congming/github/goldenshare/tests/test_financial_statement_datasets.py)；测试使用替身、内存样本与迁移调用记录，不能当成今天的生产 SQL 或端到端验收。

| 维度 | 必须保留的正向/负向检查 |
| --- | --- |
| 字段与定义 | 94/86、158/150、97/89 的源/数值字段数和固定顺序；no_pool、raw/view、event freshness |
| 输入和 planner | 缺省全部、子集去重、周末保留、显式空/非法/sentinel 拒绝；负例不产生有效计划或源请求 |
| 分页 | 满页继续、短页结束、空类型合法；中间页错误不能写半套数据 |
| 规范化 | comp_type=7、nullable 科目、四类季度、缺失 end_type 补齐、规范化指纹一致；非法/矛盾/同身份异内容失败且不进入 DAO |
| 写入与 view | 只调 Raw DAO、跨任务修订覆盖；不同 f_ann_date 的版本保留，Serving 按 flag 优先再日期和稳定并列规则选择 |
| 迁移 | HDD 缺失拒绝；000167 对空值补齐、非法现状在写入前失败、不扩大到 PK/索引/tablespace/删表，downgrade 拒绝 |
| Ops/UI | 中文标签、全选/取消/子集、真实数组、空输入拒绝；手动/自动一致，无数据集私有分支 |
| 排除边界 | 不接 workflow/probe/date completeness，不改变 fina_indicator 等其他数据集行为 |

相关回归位置：`tests/test_dataset_action_resolver.py`、`tests/test_dataset_definition_registry.py`、`tests/test_foundation_table_model_registry.py`；Web catalog/manual/schedule 三项 API 测试；runtime/codebook/子系统架构护栏；`frontend/src/shared/ui/ops-enum-multi-select.test.tsx` 和两张任务页测试。共享 normalizer 改动仍须回归 fina_indicator 及其他 deduplicate_identical 消费者。

只运行与变更有关、已确认不访问正式资源的测试；使用既有环境，不用可能自动同步依赖的命令。真实部署/迁移/同步与页面验收单独授权，并对账 unit、fetched/normalized/written/rejected、Raw 身份/字段/行数、view 双向差集与唯一性、HDD 位置。长任务恢复门禁按根规则与模板验收，不由本次文档合并追加实现或假定已通过。

<a id="income-prod-acceptance-20260830"></a>

## 6. income 初始范围 Prod 验收（历史）

2026-08-30 已完成 `2025-01-01 ~ 2026-08-31` 初始范围验收：

1. TaskRun `10214`、`10219` 均成功，合计完成 `7,296/7,296` 个 unit，写入 `206,707` 行，拒绝和失败 unit 均为 0；任务写入量与 `raw_tushare.income` 实际总行数完全一致。
2. raw 覆盖 6,334 个证券代码；身份空值、`end_type` 空值、非季度末、`end_type` 与 `end_date` 矛盾、非法内容指纹均为 0。
3. `core_serving.equity_income` 与 raw 的既定最新报表排序结果双向差集均为 0，每个 `(ts_code, end_date)` 唯一。
4. 源站仅在利润表返回异常代码 `4920017.BJ`，证券主数据和另外两张财务报表均无此代码。raw 按既定职责保留该源站事实，不将其误判为同步丢失。
5. migration 已到 `20260830_000167`，表、主键及索引继续位于 `gs_raw_cold_hdd`；页面验收由运营确认通过。

该记录证明当时所列范围已验收；不证明全历史覆盖，也不证明此后每个公告日或当前生产状态已重新核验。
