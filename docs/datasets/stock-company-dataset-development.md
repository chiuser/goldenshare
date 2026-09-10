# 上市公司基本信息（`stock_company`）维护说明

状态：当前代码说明；2026-09-10 文档治理核对。本文不证明生产部署、最新数据或自动任务状态；原接入阶段结论不因此重新打开，也不升级为本轮生产验收。

## 1. 范围与依据

- Tushare `stock_company`，doc_id=112；[本地源说明](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/基础数据/0112_上市公司基本信息.md)。
- 当前事实源为 [reference_master Definition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/reference_master.py)；底层域 `reference_data / 基础主数据`，Ops 展示分组 `reference_data / A股基础数据`。
- 通用规则引用 [开发模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)与 [日期模型消费指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)，不重复粘贴完整 Definition、建表 SQL 或施工清单。

## 2. 输入与执行

- 动作为 `stock_company.maintain`，`time_input.mode=none`。过滤为代码字符串 `ts_code`、交易所多选 `exchange`。
- 使用专用 `build_stock_company_units`，按下表选择请求；默认交易所顺序由当前 planner 执行，不由页面另造列表。

| 输入 | 实际展开 |
| --- | --- |
| 一个代码 | 一个代码 unit，只传 `ts_code` |
| 逗号分隔多个代码 | 代码去空白、大写、去重排序后逐代码 unit |
| 代码与 exchange 同时填写 | 优先代码路径，源请求不再附带 exchange |
| 仅选 exchange | 按 `SSE/SZSE/BSE` 固定顺序展开所选项 |
| 二者均不填 | 默认三个交易所分别生成 unit |

多代码支持来自后端解析现状，不是本轮新增多选控件。`page_limit=4500` 是当前配置，与本地来源描述对应；本轮不宣称已重新核验源端最大容量。

`universe_policy=no_pool`；分页由 [SourceClient](/Users/congming/github/goldenshare/src/foundation/ingestion/source_client.py)注入 `limit=4500/offset`，空页或短页结束。[request builder](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)只生成业务参数。当前 `buffer_all + commit_policy=unit`，分页不切事务，也不代表页级持久化或中断后从任意页续跑。

## 3. 字段与身份

| 字段名 | 源类型 | 是否落 raw | 备注 |
| --- | --- | --- | --- |
| `ts_code` | string | 是 | 股票代码 |
| `com_name` | string | 是 | 公司全称 |
| `com_id` | string | 是 | 统一社会信用代码 |
| `exchange` | string | 是 | 交易所代码 |
| `chairman` | string | 是 | 法人代表 |
| `manager` | string | 是 | 总经理 |
| `secretary` | string | 是 | 董秘 |
| `reg_capital` | float | 是 | 注册资本（万元，源文档口径） |
| `setup_date` | string | 是 | 注册日期；源站为 `YYYYMMDD` 字符串，raw 层直接落 `date` |
| `province` | string | 是 |  |
| `city` | string | 是 |  |
| `introduction` | string | 是 | 长文本 |
| `website` | string | 是 |  |
| `email` | string | 是 |  |
| `office` | string | 是 | 长文本 |
| `employees` | int | 是 | 员工人数 |
| `main_business` | string | 是 | 长文本 |
| `business_scope` | string | 是 | 长文本 |
| `ann_date` | string | 是 | 公告日期；源站为 `YYYYMMDD` 字符串，raw 层直接落 `date` |

- 显式请求 19 个源字段，包括 `introduction/office/main_business/business_scope/ann_date` 等非默认字段。
- `ts_code/exchange` 必填，清理首尾空白并大写；`setup_date/ann_date` 直接转日期，`reg_capital` 做数值解析。
- `com_id` 不作主键或唯一约束；不能根据“统一社会信用代码”这个名字假设源返回全量非空、绝对唯一。长文本字段不删减。

具体解析和哈希见 [normalizer](/Users/congming/github/goldenshare/src/foundation/ingestion/normalizer.py)及 [row_transforms](/Users/congming/github/goldenshare/src/foundation/ingestion/row_transforms.py)。

## 4. 存储与观测

- 写入 `raw_tushare.stock_company`，`raw_only_upsert`；幂等冲突列为 `ts_code`。冲突列同时为 Raw 主键。
- [Raw ORM](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_stock_company.py)定义真实类型、可空性、物理索引及审计字段 `api_name/fetched_at/raw_payload`，不执行旧文档中“建议新增”的 DDL。
- `target_table=core_serving_light.stock_company`；[Light 模型](/Users/congming/github/goldenshare/src/foundation/models/core_serving_light/stock_company.py)对应 Raw 普通读取视图，不复制第二份物理数据，也不是 writer 的 DML 目标。
- 日期模型 `none / not_applicable`，无运营时间输入、无业务日期 observed field；`snapshot_run_trace` 关注最近成功维护，不做连续日期完整性判断。
- 已纳入 `reference_data_refresh`，见 [action_catalog](/Users/congming/github/goldenshare/src/ops/action_catalog.py)；手动、定时、重试是能力，不等于实时 schedule 状态已核验。

## 5. 回归与运行边界

- [Definition 回归](/Users/congming/github/goldenshare/tests/test_dataset_definition_registry.py)、[Resolver 回归](/Users/congming/github/goldenshare/tests/test_dataset_action_resolver.py)、[Ops 目录与工作流回归](/Users/congming/github/goldenshare/tests/test_ops_action_catalog.py)覆盖注册、输入及当前展开路径；日期/哈希相关样本见 [normalizer 回归](/Users/congming/github/goldenshare/tests/test_dataset_normalizer.py)。
- 本轮未新增源端调用或生产验收；不能从“已有实现”推出全部历史完整。扩大范围前，按开发模板核对真实请求量、单 unit 内存、提交量、取消和续跑证据，不把单页 4500 行当成整个任务上限。
