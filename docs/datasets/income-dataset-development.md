# A 股利润表（income）维护说明与财务三表共用规则

更新时间：2026-10-31。原开发方案与 LLD 已合并于本文；2026-08-30 初始范围 Prod 验收保留为历史。§7 的特殊报告期修正开发已结案，开发提交为 `96bc3b191`，本轮复核见 §7.6；本轮未部署、迁移或重跑生产任务。

2026-11-19，[财务三表报告期修复](/Users/congming/github/goldenshare/docs/datasets/income-dataset-development.md#financial-statement-period-repair)已在工作区实现，生产版本仍待发布。§2 说明工作区实现，§8 记录修复方案与验收条件。

## 1. 范围与阅读入口

`income.maintain` 按公告自然日维护全市场利润表，使用 `income_vip`，不是按证券池调用普通 income 接口。

`Ops 手动/普通自动任务 → DatasetActionResolver → 公告日 × 报告期 × 报表类型 → VIP 分页 → 规范化与身份校验 → Raw upsert → Serving 普通 view`。

本文 §2 集中说明 income、[balancesheet](/Users/congming/github/goldenshare/docs/datasets/balancesheet-dataset-development.md)、[cashflow](/Users/congming/github/goldenshare/docs/datasets/cashflow-dataset-development.md) 共用规则；各表字段、源端样本和验收证据分别维护，不复制三套共享实现。变更门禁仍见[数据集模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)及[执行计划说明](/Users/congming/github/goldenshare/docs/architecture/dataset-execution-plan-refactor-plan-v1.md)，本文不是再次部署、迁移或全量同步授权。

<a id="financial-statement-shared-rules"></a>

## 2. 财务三表共用规则

### 2.1 时间、输入与执行单元

| 维度 | 当前事实 |
| --- | --- |
| 日期输入 | 单公告日 ann_date，或公告自然日 start_date/end_date 闭区间。报告期是独立范围，手动可选填。 |
| 日期模型 | natural_day / not_applicable / point_or_range / ann_date_or_start_end；observed_field=ann_date |
| 股票范围 | no_pool；不读证券池，不用交易日历过滤周末或节假日 |
| 类型输入 | report_type 必填、多值，真实值为字符串 1..12；缺失时用 enum_fanout_defaults，显式空拒绝 |
| 报告期输入 | 默认上年年末加当年截至公告日的季度末，手动选填时只查指定报告期。 |
| unit | build_financial_statement_units 按公告日、报告期、报表类型顺序生成。 |
| 请求 | 三个 VIP builder 共用 _financial_statement_vip_params，每次传一个 ann_date、一个 period 和一个 report_type。 |
| 源字段/分页 | Definition 显式 fields；source client 追加 limit/offset，page_limit=5000，短页结束 |
| 不向源端传递 | 股票过滤、comp_type、is_calc、原始 start/end 区间或任何 ALL 哨兵。分页由源客户端处理。 |

首请求数为各公告日的适用报告期数乘所选报表类型数后累加，分页与重试另计。自动积压每表每段最多两个连续公告自然日，手动可指定范围。生成算法见[规划器](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py)，实测与预算见 §8.4。

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
2. end_type 不入身份：源 end_type 为 0，且（end_date 严格早于证券主数据的正式上市日期，或查询成功但查不到上市日期）时，保留 end_date 与 end_type=0，跳过季度末及对应类型校验；完整实现与验收见 §7。其他记录按 end_date 的 03-31/06-30/09-30/12-31 映射为 1/2/3/4，缺失补齐，非空值必须匹配。
3. 不满足上述例外的非季度末报 `normalize.financial_statement_end_date_invalid`，非法 end_type 报 `normalize.invalid_enum:end_type`，矛盾报 `normalize.end_type_mismatch`。查不到上市日期不同于数据库查询报错，后者必须停止；禁止静默覆盖矛盾值。
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
- 普通 schedule 使用 `since_last_success_day_range`，策略参数 initial_start_date 必填。每次截取最早两个待处理公告日，成功后按本段末日续接。类型数组按配置保存，手动报告期字段仅在手动入口可用。
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
| 规范化 | comp_type=7、nullable 科目、四类季度、缺失 end_type 补齐、规范化指纹一致；end_type=0 且（上市前或查不到上市日期）时保留；其他非法/矛盾/同身份异内容失败且不进入 DAO；本次边界矩阵见 §7 |
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

<a id="financial-statement-prelisting-zero-end-type"></a>

## 7. 2026-10-29 上市前 end_type=0 修正方案与 LLD

### 7.1 目标、依据与范围

管理员确认并在同次开发中补充：**源 end_type=0，且（end_date < 正式上市日期，或查询成功但上市日期查不到）** 的记录豁免季度末和 end_type 映射校验，保留源值。查不到包括无该证券记录、该记录 list_date 为 NULL；不能据此认定它未上市。比较的是报告期，不是公告日，也不是任务运行当天是否已上市；已知上市日时，等于上市日不豁免。适用于 income、balancesheet、cashflow 的共享规范化步骤。

问题依据：TaskRun 17453 / node 26701 的 balancesheet 公告日 2024-01-11、report_type=1 单元，源记录 `920202.BJ / end_date=20230831 / end_type=0` 被原季度末检查拒绝，writer 按既有规则阻止整单元写入。2026-10-29 通过 tushareMcp 以同公告日及类型复现，stock_basic 返回安达股份正式上市日 20260929。本地源说明为 [doc 36](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/财务数据/0036_资产负债表.md)：end_type 是报告期类型，未明确说明 0 的定义；本次是获准的本地保留规则，不将推断写成源合同。

现有实现审计：CodeGraph explore/impact 已追踪 `_financial_statement_row_transform` 的三个 wrapper；结合当前 normalizer、executor、SecurityDAO、Security 模型、stock_basic writer、财务 Raw ORM、000163～000167 及测试核验。股票基础数据发布到 `core_serving.security_serving`，其中 `list_date` 为 DATE、允许空；财务 Raw 的 end_type 是非空字符串，无 1..4 CHECK，保留 0 无需 schema 迁移。原 LLD 合并记录见 [文档治理记录](/Users/congming/github/goldenshare/docs/governance/docs-information-architecture-v1.md#cyq-biying-financial-docs-consolidation-20260910)。

范围：只修改上述三表的共享规范化、上市日期的有界只读查询和执行器接线、错误说明及相关测试。源字段、请求、分页、DatasetDefinition、DatasetExecutionPlan、日期输入、七字段身份、view 选择、Ops/API/前端合同不变；不增加运营参数或配置，不安装依赖，不恢复旧 LLD，不修改历史迁移或其他数据集。

### 7.2 LLD：读取、判断与写入

1. `SecurityDAO.get_listing_dates(ts_codes)` 只从 `core_serving.security_serving` 读取给定代码的 `ts_code/list_date`，不按当前上市状态过滤，不读取证券池。代码去重后每批最多 500 个，空集合不发 SQL；不查询全表、不调用 Tushare、不提交事务。
2. `IngestionExecutor.__init__` 将同一 session 上的该只读方法注入 `DatasetNormalizer`。normalizer 仅在所选 row transform 属于三表 wrapper 时收集当前 fetch_result 内源 end_type=0 的代码，按现有清 NUL、trim/upper 规则匹配主数据；无此类行则无额外 SQL。结果仅存活于本次 normalize 调用，不增加跨 unit/跨任务缓存。
3. 三个 wrapper 将对应上市日期传给共享 `_financial_statement_row_transform`。日期仍先经标准 coerce 转为 Python date；三个日期与 ts_code 必填检查继续执行。end_type=0 且 list_date 为 None 或严格晚于 end_date 时保留 0，不推导季度、不改 end_date；实际存在但类型错误的上市日期不是“查不到”，报 `normalize.invalid_date:list_date`。其余记录执行原季度检查、缺失补齐及映射一致性检查。纯内存调用未提供查询方法时，上市日期上下文为空；正式执行器必须注入查询方法。
4. 例外分支之后仍执行 report_type=1..12、comp_type 非空、update_flag=0/1、完整源字段内容指纹、公告日期一致性、同身份内容冲突和去重规则。上市日期仅为校验上下文，不能进入源字段、Raw 行或 source_content_hash。
5. 主数据 SQL 失败由 normalizer 抛出 `normalize.financial_statement_listing_dates_failed`，当前单元在 writer 前终止；不得吞异常、按无上市日期继续放行或部分写入。错误登记 codebook，不新增缺日期拒绝原因。正常的缺失补齐、拒绝整单元策略保持不变。

### 7.3 事务、取消、续跑与性能预算

| 项目 | 本次边界与预算 |
| --- | --- |
| 执行 unit / 幂等键 | 沿用公告自然日×report_type；七字段身份不变，同一 unit 重放仍为 upsert |
| 批次与内存 | 源 page_limit=5000 不变；本次新增内存仅与当前 unit 内 end_type=0 的不同代码数 K 有关，O(K)，不累积历史日期或全市场主数据 |
| 额外请求量 | Tushare 额外请求为 0；主数据 SQL 为 ceil(K/500)，无 0 记录时为 0，每次只投影两列；500 为内部查询分批上限，不新增配置 |
| 目标耗时 / 配额 | 小样本新增查询与判断目标小于 1 秒；不会增加源分页或 Tushare 配额消耗。若真实环境缺表、权限错误或查询失败，停止该 unit，不尝试全表读取或源端补查 |
| 持久化 / 事务 | 查询与业务写入使用既有 unit session；仍完整规范化后写 Raw、每 unit 提交。查询本身无写入，不引入长历史事务或额外状态表 |
| 失败 / 中断 | 当前 unit 提交前失败/退出无新增业务事实；此前已提交 unit 保留。按既有重试入口重新获取当前 unit、重新查询上市日期，不以进程内字典作为续跑依据 |
| 取消 / 可见进度 | 复用当前 unit 前后取消与进度检查，串行/并发入口及 TaskRun/节点终态不改；查询按最多 500 代码短查询执行，不新增超过 30 秒的不可分割工作 |
| 续跑与最后验收开销 | 重试当前 unit 增量仍为 ceil(K/500) 次主数据查询；最终验收仅以单股票、单公告日源样本和主数据单代码查询核验，不全库对比、不重跑历史 |
| 真实执行边界 | 本次只做源端/数据库有界只读和临时资源的隔离验证；不启动或重试生产 TaskRun，不宣称长任务取消恢复或部署已验收 |

### 7.4 硬口径与验收矩阵

| 要求 | 代码位置 | 必须覆盖的场景 |
| --- | --- | --- |
| 类型与日期条件必须同时成立 | row_transforms 共享 helper | 上市前非季度末+0 放行；上市前季度末+0 也保留；查不到上市日期+0 保留；已知上市当日/之后+0 拒绝；上市前或日期未知+非0/空值仍检查 |
| 查不到日期与查询错误分开 | security_dao / normalizer / executor | 已退市状态仍可读取原上市日；缺代码/NULL 日期且 end_type=0 保留；错误日期类型拒绝；数据库异常停止且不调用 writer |
| 其他检查不被跳过 | row_transforms / normalizer / writer | 例外记录仍拒绝非法日期、空身份、非法 report_type/update_flag、错误公告日和同身份异内容；合法常规季度及缺失 end_type 补齐不误拒绝 |
| 不污染源字段和指纹 | wrappers / normalizer | 上市日期上下文不进入输出；0 原值保留；相同源记录在两次合法上市日期上下文中指纹一致；重复源行幂等去重 |
| 读取有界且无额外源请求 | DAO / executor | 只查 0 记录的去重代码、500/501 代码分批、无候选不发查询；通过真实 SQL 的隔离数据库验证列与过滤条件 |
| 真实错误可复现并修复 | 三表测试 / 有界源端验证 | 安达股份真实报文在旧逻辑被拒绝；修正后字段原值保留、拒绝数为 0，并能经正式 writer 写入隔离 Raw 表再读回；生产不写入 |

### 7.5 实施与验证结果（2026-10-29）

本次先完成 §7.1～7.4 并通过文档完整性检查，再修改代码；管理员补充“查不到上市日期且 end_type=0 也保留”后，先同步原方案与 LLD，再调整实现。实现文件为 §7.2 所列 security_dao.py、executor.py、normalizer.py、row_transforms.py 和 codebook.py。未修改源合同、Definition、执行计划、模型或迁移。

1. **真实上游与错误重现**：tushareMcp `balancesheet_vip(ts_code=920202.BJ, ann_date=20240111, report_type=1, fields=完整158字段)` 返回 3 条；旧代码归一化 2 条、拒绝 1 条，原因为 `normalize.financial_statement_end_date_invalid`。其中完整特殊报告期记录连同请求及来源日期保存为[真实夹具](/Users/congming/github/goldenshare/tests/fixtures/financial_statements/balancesheet_920202_prelisting.json)，不是按消费者猜出的报文。
2. **真实主数据只读核验**：使用仓库 psql-remote 入口，READ ONLY 事务、5 秒查询超时，只查 `core_serving.security_serving` 的单个 `920202.BJ`，投影 ts_code/list_date/list_status、LIMIT 1，结果为 `920202.BJ / 2026-09-29 / L`，随后 ROLLBACK；与 tushareMcp stock_basic 一致。没有生产写入或全局明细读取。
3. **修正后最小链路**：重放同一批 3 条完整源记录，实际 IngestionExecutor → SecurityDAO → DatasetNormalizer → DatasetWriter/Raw GenericDAO → 临时 SQLite，源端/归一化/写入/目标表均为 3 条、拒绝为 0；读回保留 `2023-08-31 / 0`，样本链路耗时约 0.015 秒。这证明源合同交接与本地写入路径，不能替代生产 PostgreSQL 写入或部署验收。
4. **硬口径逐项覆盖**：[专项测试](/Users/congming/github/goldenshare/tests/test_financial_statement_prelisting.py)共 83 项。`test_zero_end_type_preserved_before_listing_or_with_unknown_date` / `test_other_cases_still_rejected` 覆盖类型与日期条件；`test_exemption_does_not_skip_other_fields` / `test_exemption_keeps_unit_date_and_conflict_checks` 覆盖其他校验；`test_valid_quarter_needs_no_listing_query_and_zero_has_stable_source_hash` 覆盖指纹和常规补齐；两个 `test_listing_dao_*` 场景覆盖只查指定两列/代码、退市证券与 500/501 分批；`test_executor_uses_listing_dao_then_real_writer_and_idempotent_readback` 在三表×已知/NULL/无记录共 9 个场景写入、提交、重放及读回；`test_executor_reads_known_listing_date_and_blocks_postlisting_zero` 防止遗漏执行器接线被误当未知日期；查询异常和混合拒绝单元均验证 writer 不写入。
5. **共享回归**：上述专项、原三表、通用 normalizer、fina_indicator、fund_daily 两阶段执行器、Definition registry、action resolver、子系统依赖/runtime/codebook 护栏，共 399 项通过；`ingestion-lint-definitions` 通过。文档完整性与差异空白检查通过。CodeGraph explore/impact 覆盖共享校验三个调用者及 DAO/normalizer/executor，修改后 sync/status 正常。

2026-10-29 验证结束时，文档、代码和有界验证已完成，当时尚未提交；随后按管理员指令提交为 `96bc3b191`。当轮未部署、未执行数据库迁移、未重试 TaskRun 17453。正式运行、页面效果及长任务真实取消恢复不在当轮验证范围，历史 Prod 验收不作为本次通过依据。

### 7.6 开发结案（2026-10-31）

**本次特殊报告期校验修正的开发工作已完成并结案。** 最终规则为：源 `end_type=0`，且报告期严格早于上市日期或查询成功但查不到上市日期时，保留源报告期及类型；其他记录继续原有校验。数据库查询报错仍停止当前单元，其他必填、类型、公告日和身份冲突检查继续生效。

- 开发提交：`96bc3b1915ca89dd9cf72fcbaad8609aac384260`，包含三表文档、五个实现文件、专项测试和真实源报文夹具，共 10 个文件；当前 `dev-interface` 分支包含该提交。与收尾修改前 HEAD `02cad691d` 对比，相关代码、测试及三表原文档均无后续差异。
- 本轮复核：重跑 §7.5 所列相同范围的 399 项测试，全部通过（4.40 秒）；`ingestion-lint-definitions`、文档完整性及差异空白检查通过。测试继续覆盖三表、已知/NULL/缺失上市日期、上市当日与之后的拒绝、其他校验保留、有界查询及隔离数据库写入读回和幂等重放。本轮未新增代码、配置或迁移。
- 源端与主数据证据：沿用 §7.5 的 2026-10-29 有界实测及完整夹具，不将其表述为 2026-10-31 再次查询结果；无需为文档收尾重复访问源接口或生产数据库。
- 收尾修改仅限 income、balancesheet、cashflow 三份原开发说明，修正提交状态并统一结案标记；历史验收及原方案、LLD、测试证据保留，工作区其他修改不纳入本次收尾。
- 生产边界：本会话未执行部署或重试 TaskRun 17453；本轮未核验当前生产版本、该任务终态或页面效果，不将开发结案等同于生产验收。后续如需部署或正式运行，应另按明确授权执行。

<a id="financial-statement-period-repair"></a>

## 8. 2026-11-19 财务三表报告期修复方案与详细设计（本地实施，待验收）

### 8.1 目标和依据

恢复 Prod 的 A 股利润表、资产负债表、现金流量表按公告日维护。自动和手动共用默认报告期计算，手动可以指定更早或非季末的报告期。成功表示完成了任务列明的报告期和报表类型。超出默认范围的旧报表及非季末报表，通过指定报告期补录。

已确认季末当天计入默认范围，手动填写后只查指定报告期，自动积压每张表每段最多连续两个完整公告自然日。分段上限由管理员确认，依据见有界只读实测及 §8.4.2。开发和隔离回归已获授权，生产部署和生产任务执行另行授权。

2026-11-18 自动任务 `20140` 和手动任务 `20194` 对同一公告日 `2026-11-17` 生成了逐条相同的 12 条业务请求。自动任务在 19:30 读取并写入 1 行，手动任务在 23:47 首条请求收到 Tushare `50101`，要求 `period`。现行三表共用的 `_financial_statement_vip_params` 只组装 `ann_date` 和 `report_type`。随后对 `income_vip`、`balancesheet_vip`、`cashflow_vip` 的有界实测均复现缺少 `period` 的报错，带有效报告期均能取数。资产负债表通过 MCP 传空 `period` 也复现了源端错误。源站变更时间和原因尚待源站确认。 [共享请求组装](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)

三组样本用于验收报告期范围。`688133.SH` 的资产负债表在 `2026-11-17` 公告，报告期为 `2026-09-30`，`report_type=6`。`600000.SH` 的利润表在同一公告日 `2018-04-28` 分别命中 `2017-12-31` 和 `2018-03-31`。`920202.BJ` 的资产负债表在 `2024-01-11` 公告，传实际报告期 `2023-08-31` 命中 `end_type=0` 的记录，传 `2023-09-30` 返回空。源接口分别见 [利润表 doc_id=33](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/财务数据/0033_利润表.md)、[资产负债表 doc_id=36](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/财务数据/0036_资产负债表.md)、[现金流量表 doc_id=44](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/财务数据/0044_现金流量表.md)和[非季末真实源报文](/Users/congming/github/goldenshare/tests/fixtures/financial_statements/balancesheet_920202_prelisting.json)。

### 8.2 运营输入和实际查询范围

| 场景 | 按每个公告自然日计算报告期 |
| --- | --- |
| 自动任务、手动留空 | 上一年 `12-31`，加公告日所在年截至该日的 `03-31`、`06-30`、`09-30`、`12-31`。以公告日为准，季末当天计入，周末和节假日照常计算。 |
| 手动填写一个或多个报告期 | 只查询填写的日期。列表去重后按日期排序，保留任意合法日历日期。每个公告日只查询截至当日的指定报告期。晚于公告窗口末日的报告期在提交时提示错误。区间内某天没有适用的指定报告期时明确显示未纳入本次范围。 |
| 重试 | 沿用原任务公告日、报表类型和手动指定报告期。部署前未记录报告期的旧任务，按原公告日重新计算默认范围。部署前留下的超两日自动任务在执行预检时停止，由自动任务从最后成功日期起按两天一段接续。 |

例如 `2026-11-17` 默认请求 `2025-12-31`、`2026-03-31`、`2026-06-30`、`2026-09-30`。`2026-12-31` 的默认范围含上年末和当年四季末，共五个日期。次日 `2027-01-01` 只含 `2026-12-31`。区间跨季度或跨年时，每个公告日分别计算。手动填写 `2023-08-31` 时，可用公告日 `2024-01-11` 精确补录这期。

手动页显示选填项「报告期」，输入格式 `YYYY-MM-DD`，多个日期以逗号分隔。空白沿用默认规则，填写后只查所填日期。拟用现有手动提交接口中的 `filters.report_periods` 日期字符串数组承载，原公告日及 `report_type` 字段保持原语义。自动任务配置页和自动任务提交接口仅支持默认报告期规则，直接传手动报告期的请求在生成计划前被拒绝。原有任务入口、三个源接口、显式返回字段、报表类型 1–12、Raw 表和 Serving 视图沿用现行合同。

### 8.3 实现位置和影响面

1. **定义与表单。** 在三表共用定义中声明可选报告期列表，由手动动作目录投影给前端。复用手动过滤字段的数组提交，日期合法性、去重和区间交叉规则由后端统一处理。核对自动能力目录、保存规则和触发规则，自动来源的重试仍走默认规则。现有自动配置和未填写报告期的调用保持兼容。 [三表定义](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/low_frequency.py) · [手动动作目录](/Users/congming/github/goldenshare/src/ops/queries/manual_action_query_service.py) · [手动提交](/Users/congming/github/goldenshare/src/ops/services/manual_action_service.py) · [自动参数处理](/Users/congming/github/goldenshare/src/ops/services/task_run_service.py) · [手动页](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-task-manual-tab.tsx)
2. **执行计划。** 继续由 `DatasetActionResolver` 调用三表共用规划器。最小执行单元拟定为一个数据集、一个公告日、一个报告期、一个报表类型，按公告日、报告期、既有报表类型顺序串行处理。报告期进入单元标识和进度。共享请求组装把该单元变为 `ann_date=YYYYMMDD`、`period=YYYYMMDD`、单个 `report_type`。源客户端按原字段和 `limit/offset` 分页。前端、TaskRun 和调度保存提交意图，报告期的默认计算统一留在规划器。 [Resolver](/Users/congming/github/goldenshare/src/foundation/ingestion/resolver.py) · [三表规划器](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py) · [分页](/Users/congming/github/goldenshare/src/foundation/ingestion/source_client.py)
3. **质量与入库。** 先取完单元的全部分页，要求返回记录的 `ann_date`、`end_date`、`report_type` 与该单元一致。源端合法空结果可以完成单元。保留 §7 对上市前非季末报告期的约定及七字段身份、修订覆盖和重复识别，同一身份的不同内容按既有质量规则处理。通过后由现有 Raw writer 按单元 upsert，Serving 继续由普通视图提供。 [执行器](/Users/congming/github/goldenshare/src/foundation/ingestion/executor.py) · [Raw writer](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py)
4. **状态及消费者。** 公告日仍是任务意图与状态日期，报告期用于限定源读取。任务详情展示本次默认或指定模式、已计划/已完成范围、当前公告日、报告期、报表类型和分页位置。逐项回归手动目录、提交/重试、自动配置与日期策略、数据集目录/卡片、freshness、snapshot、日期完整性审计、前端时间控件及既有 Workflow 能力边界。卡片保留 `event_run_trace`，没有公告的自然日仍可合法为空。 [调度成功日期读取](/Users/congming/github/goldenshare/src/ops/services/task_run_service.py) · [任务进度](/Users/congming/github/goldenshare/src/ops/services/task_run_ingestion_context.py) · [卡片状态快照](/Users/congming/github/goldenshare/src/ops/services/operations_dataset_status_snapshot_service.py)

### 8.4 失败、续跑和性能

日期区间、报告期及分页都可能扩大请求量，按 Prod 长任务设计。复用现有通用 Worker 串行执行、Raw 单元事务与 TaskRun 任务详情。实施范围限于三表及其必要的参数投影和任务恢复，使用现行表及配置来源。正式部署、真实写入和历史补录为分别授权的步骤。

| 项目 | 拟定规则及验证方法 |
| --- | --- |
| 提交与失败 | 分页失败、源返回范围不匹配、质量拒绝或提交前取消时，本单元没有部分入库。此前已提交单元保留。源接口成功返回只是完成一次请求，只有该日所有纳入范围的报告期和类型都完成，才算完成这一天。自动任务全部通过后才产生有效的成功窗口。原计划的报表类型和报告期作为对账依据。 |
| 进程退出与重试 | 现有重试只复制意图，计划预览最多 20 个单元。拟在已有 TaskRun 记录持久化完整计划的可重建意图、规则版本、计划标识及已连续完成的位置，只在 Raw 单元提交后记录完成位置，空单元也记录。重试核对同一计划后从最后确认的位置接续，原记录缺少可验证进度时用原意图幂等重跑。业务提交成功但进度写入失败时，续跑可重放尚未确认的单元，状态写失败不回滚 Raw。计划标识不一致时提示按原范围重新提交。 |
| 可见状态与取消 | 每个单元及每页前后检查取消，限流等待可取消。现有阻塞源调用及 65 秒限流等待不能直接满足长任务要求。三表复用有界 HTTP 调用与可取消等待的基础能力，约束单次不可中断步骤并实测；确认停止后不领取新单元。显示阶段、日期、报告期、类型、页、已完成数/总数、百分比和最后更新时间，达到仓库要求的 30 秒内可见更新。无法可靠估算时显示「暂无法估算」。结束时 TaskRun 与活动节点状态一致。 |
| 量与内存 | 每张表的计划单元数为所选公告日逐日累加「适用报告期数 × 所选类型数」。11 月 17 日每张表 4 × 12 = 48 个单元，三表 144 个。按季末当天计入的拟定规则，12 月 31 日每张表最多 5 × 12 = 60 个默认单元，三表 180 个。每单元按现行 5,000 行/页串行取数，多页的行数及内存在单元内有界。长区间先按已确认的计划容量分段，避免在内存中汇总全范围源数据。 |
| 普通、重试与验收开销 | 对同一单元，若全部非末页满页、以短页结束，则首请求加分页共 `floor(源返回行数 / 5000) + 1` 次，满页时含末尾探测。超时、限流和重试另计。续跑成本按「重建同范围计划并核对进度 + 未确认单元的取数/校验/写入」计算。最终验收预算单列一次有界真实运行、取消后的未确认部分重放、按同一组公告日和报告期的源数据与 Raw 读回对账。 |

#### 8.4.1 2026-11-19 有界只读实测

先对生产三张 Raw 表指定公告日做聚合计数。选择 `2026-04-28` 至 `2026-04-29` 作为候选中行数较多的连续两日，选择 `2025-12-30` 至 `2025-12-31` 作为默认规则下请求组合最多的连续两日。只读查到三张表各有一个现行每日自动任务，资产负债表 `19:30`、现金流量表 `19:31`、利润表 `19:35`，均为北京时间。

使用项目现有 Tushare HTTP 客户端串行请求。MCP 已用于验证报告期语义，因三表 MCP 工具未开放 `limit/offset`，本轮分页与耗时用项目客户端实测。每个公告日请求该日默认报告期与全部 12 种报表类型，字段分别为 94、158、97 个，`limit=5000`，`offset` 从 0 开始。主测每个组合最多探测两页，短页即结束，本次禁用重试。表中「合计」包含本机取数、解析、用现有归一化逻辑校验和测量开销，生产排队、写库和任务状态提交待后续验收。

| 公告日窗口 | 数据集 | 实际请求 | 源返回行数 | 取数秒 | 内存归一化秒 | 合计秒 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 2026-04-28 至 04-29 | 利润表 | 48 | 10,635 | 11.130 | 2.177 | 13.378 |
| 同上 | 资产负债表 | 48 | 6,249 | 10.840 | 1.943 | 12.852 |
| 同上 | 现金流量表 | 48 | 12,548 | 11.624 | 2.849 | 14.580 |
| 2025-12-30 至 12-31 | 利润表 | 108 | 135 | 25.905 | 0.047 | 26.005 |
| 同上 | 资产负债表 | 108 | 69 | 23.816 | 0.039 | 23.908 |
| 同上 | 现金流量表 | 108 | 136 | 24.736 | 0.045 | 24.832 |

春季两天每天有两个报告期，每表 `2 天 × 2 期 × 12 类 = 48` 次首请求。年末分别有四个、五个报告期，每表 `(4 + 5) × 12 = 108` 次。主测合计 468 次请求、29,772 行，350 个组合为空，全部在首个短页结束。返回字段和公告日、报告期、报表类型校验均通过，29,772 行内存归一化后为 29,772 行，拒绝及去重均为 0。主测单次请求第 95 百分位 0.392 秒，最长 1.135 秒。项目客户端使用本机配置的每接口每分钟 280 次节奏，本轮未触发限流；Tushare 服务端配额和生产并发可用额度待核实。

同一公告日下对三表各做 3 次小页复核。`2026-04-29`、报告期 `2026-03-31`、报表类型 `1` 以 `limit=1` 验证偏移 0、1 返回与主测前两条一致的记录，偏移到实际总数时返回空。另为测量满页负载，仅按 `period=20260930` 和 `report_type=1` 各查一页 5,000 行，并在 `offset=5000, limit=1` 各查到一条后续记录。首屏解压后响应正文及耗时为利润表 3,563,172 字节、1.163 秒，资产负债表 5,875,580 字节、0.562 秒，现金流量表 3,640,972 字节、0.938 秒。满页样本按报告期选取，用于量响应开销。全轮源请求共 `468 + 9 + 6 = 483` 次，未创建任务或写库。

生产 Raw 计数用于选样及确认默认范围的边界。例如 `2026-04-29` 已存记录中，默认报告期之外有利润表 2,475 行、资产负债表 1,602 行、现金流量表 2,476 行。上述取数与内存校验结论限于本次指定报告期。历史 Raw 与当前源端的行数也存在差异，完整身份与版本对账留在正式验收。

#### 8.4.2 自动积压分段上限（已确认）

自动积压**每张表每次最多连续两个完整公告自然日**。从原自动任务应开始的最早日期起取两天，最多到当次原目标日，成功后按实际完成的窗口末日推进。失败或取消沿用 §8.4 的提交及续跑规则。现行排程每天触发一次，每天新增一个待处理日期。每次只取一天时，连续成功也无法缩短积压。两天是每次成功可消化一天积压的最小窗口。上限只用于三张表的自动任务，手动选定范围仍按 §8.2 处理。

两个连续公告日最多有九个「公告日 × 报告期」组合，出现在 `12-30` 的四个加 `12-31` 的五个。默认全选 12 类时，上限为**每张表每段 108 个计划单元及首请求，三表合计 324 次首请求**。分页和重试另计。实际年末窗口三表每表分别耗时 26.005、23.908、24.832 秒，测量合计 74.745 秒。春季繁忙窗口三表合计 40.810 秒。这两组实测分别验证请求组合和繁忙数据量，生产端到端耗时需包括有界请求控制、数据库事务、排队及限流重试，待实现后计入。

续跑先恢复已确认完成的位置，源端开销由剩余单元及其实际分页决定。若用春季两日样本进行正式验收，三表一轮实测为 144 次请求。按相同分页形态且每请求无重试计算，取消前最多 144 次、重跑最多 144 次、独立源核对一轮 144 次，合计最多 432 次；另计实际分页变化、重试及同期 Raw 有界读回。生产写入、进程退出续跑和任务终态仍按 §8.5 验证。

两个公告日限制的是自动任务范围。单个执行单元沿用 5,000 行/页。首期的保护上限取三表历史整期实测的最大量 10,980 行（资产负债表半年报全类型 `5,000 + 5,000 + 980`），足以容纳本次公告日样本最大单组合的 2,163 行，并允许第三页；这是执行保护值，超过时整单元明确失败，源记录可以在独立复核后重新处理。单页正文使用同一通用 Worker 已有的 8 MiB 级预算，与本次三表 5,000 行满页实测最大 5,875,580 字节核对。最多三页对应的响应正文总预算为 24 MiB，Python 对象和事务内存另计。HTTP 单次总期限沿用已有有界调用的 25 秒，锁等待和业务事务沿用同一 Worker 的 2 秒和 20 秒预算。每页处理、限流等待及事务前后可检查取消，预算超出时保留此前提交。 [现有规划与分页](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/low_frequency.py) · [历史分页实测](/Users/congming/github/goldenshare/docs/datasets/balancesheet-dataset-development.md) · [项目有界调用](/Users/congming/github/goldenshare/src/foundation/clients/bounded_tushare_call.py) · [同 Worker 的事务与内存预算](/Users/congming/github/goldenshare/src/foundation/datasets/models.py) · [长任务验收合同](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md#035-prod-数据集长任务识别与执行合同)

开发前用按真实字段构造的 10,980 行/表做隔离 SQLite 容量核验。三表分别用时 3.193/4.942/3.377 秒完成归一化，8.692/13.413/9.017 秒完成真实 DAO 写入及提交，均读回 10,980 行。最大单进程峰值为 653,082,624 字节。只读查看生产 Worker 无单独的 cgroup 内存上限，当时占用 658,407,424 字节，主机可用内存 9,990,764 KiB。隔离测试证明本次保护值有可复算的本地依据，生产 PostgreSQL 的真实事务耗时仍在部署前的独立验收范围。内存只保留当前单元数据，较长手动区间仍使用现行执行计划的轻量单元元数据。

### 8.5 验收条件

| 验收项 | 通过条件 |
| --- | --- |
| 默认规则与人工指定 | 三表按同一组公告日、报表类型提交自动和手动留空任务，逐个核对生成的 `ann_date/period/report_type` 和单元总数。独立写明平日、季末当天、年末、元旦及跨季度/跨年区间的预期日期。手动样本以 `2023-08-31` 验证老期、非季末和精确范围，覆盖重复日期、非法日期、窗口外日期、空值及自动接口误传拒绝。 |
| 真实源与完整分页 | 用三表各一组已知数据抽样，验证带报告期能返回正确记录及完整的现行显式字段。资产负债表覆盖 `688133.SH` 正常三季报和 `920202.BJ` 非季末，利润表覆盖 `600000.SH` 同公告日的两个报告期。另用有界样本核验分页、整页后合法空页及实际请求开销。故意构造报告期、公告日、报表类型不匹配及缺 `period` 的反例，确认当前单元停止且记录原因。 |
| 数据正确性 | 在隔离库跑正式取数到写入链路，逐单元对账源行、去重后的归一化行、已提交 Raw 行及拒绝原因。合法空单元零行成功，相同数据重放不增加行数，不同 `f_ann_date` 的合法版本仍保留，Serving 视图结果符合原规则。 |
| 失败和恢复 | 在日期内第二个报告期或分页中制造失败，验证已有提交保留、失败单元没有部分写入、该日未计为完成、自动窗口不提前推进。覆盖取消、进程退出、进度写失败、续跑、幂等重放、进度单调和 TaskRun/节点终态一致。专门验证业务提交后、进度记录前中断可安全重放。 |
| 正式验收 | 经单独批准后，三表各选有已知源记录的小范围，核对自动/手动默认计划和指定报告期提交链路。至少一次代表性真实执行、取消、续跑并读回 Raw，对照计划报告期、源请求次数、分页、耗时、进度、任务终态和库中记录。预期只按已列明的报告期及报表类型判定完成。 |

测试从 [财务三表回归](/Users/congming/github/goldenshare/tests/test_financial_statement_datasets.py)、[上市前特殊报告期回归](/Users/congming/github/goldenshare/tests/test_financial_statement_prelisting.py)、[手动 API](/Users/congming/github/goldenshare/tests/web/test_ops_manual_actions_api.py)、[自动任务 API](/Users/congming/github/goldenshare/tests/web/test_ops_schedule_api.py)、[TaskRun API](/Users/congming/github/goldenshare/tests/web/test_ops_task_run_api.py)、[手动页回归](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-task-manual-tab.test.tsx) 扩展。报告期规则和两个公告日的自动分段上限均已确认。有界只读实测见 §8.4.1，生产结果和端到端耗时在对应阶段实测后补录。

### 8.6 本地实现与核验

- 共享规划器负责默认及手动指定报告期，源端逐请求携带公告日、报告期、报表类型，校验响应范围。Ops 负责截取自动窗口及保存已完成单元数。重试按原意图重建计划，核对计划标识后接续。源取数和写入仍由 Foundation 执行，业务提交与任务观察分别处理。
- 使用正式 Tushare 源接口、工作区执行器和本机独立的 SQLite Raw 表，按公告日 `2026-04-29`、报告期 `2026-03-31`、报表类型 `1` 各跑一个单元。利润表源端、写入和读回均为 1,499 行，资产负债表均为 1,561 行，现金流量表均为 2,163 行，拒绝数均为 0。对应本机耗时 2.409、3.533、2.896 秒，包含隔离库写入与读回。未运行生产任务。
- [实际任务入口回归](/Users/congming/github/goldenshare/tests/web/test_ops_financial_statement_repair.py)使用隔离数据库，验证失败及取消不推进自动日期，分页失败保留此前单元，进程退出后可续跑，进度无法写入时保留已提交数据并允许幂等重放。浏览器核对手动报告期的回填及提交体，请求由测试接管。
- 财务三表及直接调用方回归 373 项通过，前端任务页回归 44 项通过，Chrome 实测 1 项通过。扩展回归 856 项通过，14 项失败在修改前的代码上逐项复现，涉及股票周期线调度及任务修正、维护动作目录和旧执行命名检查。这些基线失败保留在原有范围。
