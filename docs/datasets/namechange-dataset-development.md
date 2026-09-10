# 股票曾用名（`namechange`）维护说明

状态：当前代码说明；2026-09-10 文档治理核对。本文不证明生产部署、最新数据或自动任务状态；原接入阶段结论不因此重新打开，也不升级为本轮生产验收。

## 1. 范围与依据

- Tushare `namechange`，doc_id=100；[本地源说明](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/基础数据/0100_股票曾用名.md)。
- 当前事实源为 [reference_master Definition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/reference_master.py)；底层域 `reference_data / 基础主数据`，Ops 展示分组 `reference_data / A股基础数据`。
- 通用规则引用 [开发模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)与 [日期模型消费指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)，不重复粘贴完整 Definition、建表 SQL 或施工清单。

## 2. 输入与执行

- 动作为 `namechange.maintain`，只使用 `time_input.mode=none`；默认不传日期，按源默认结果分页，可选 `ts_code`。
- 源接口 `start_date/end_date` 过滤的是公告日期，历史名称区间可能没有 `ann_date`；因此已确认不将公告日过滤作为维护主轴，不开放 point/range。
- generic planner 一个 unit，内部 `snapshot_refresh` 只是 resolver 归一化结果，不是另一种对外动作。
- 当前 `page_limit=1000` 已配置，不是待开发值；源文档没有给出最大页容量，本轮也未新增实测。未来提高该值须另行验证，不能混淆“当前配置”和“源端上限”。

`universe_policy=no_pool`；分页由 [SourceClient](/Users/congming/github/goldenshare/src/foundation/ingestion/source_client.py)注入 `limit=1000/offset`，空页或短页结束。[request builder](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)只生成业务参数。当前 `buffer_all + commit_policy=unit`，分页不切事务，也不代表页级持久化或中断后从任意页续跑。

## 3. 字段与身份

| 字段名 | 源类型 | 是否落 raw | 备注 |
| --- | --- | --- | --- |
| `ts_code` | string | 是 | 股票代码 |
| `name` | string | 是 | 证券名称 |
| `start_date` | string | 是 | 开始日期；源站为 `YYYYMMDD` 字符串，raw 层直接落 `date` |
| `end_date` | string | 是 | 结束日期，可能为空；raw 层直接落 `date` |
| `ann_date` | string | 是 | 公告日期；源站为 `YYYYMMDD` 字符串，raw 层直接落 `date` |
| `change_reason` | string | 是 | 变更原因 |

- `ts_code/name/start_date` 必填；`end_date/ann_date/change_reason` 可空，三个日期字段直接落 `date`。
- 哈希输入按 `namechange, ts_code, name, start_date, end_date, ann_date, change_reason` 顺序；日期用 ISO，空值用空串，`\x1f` 分隔后 SHA-256。
- **end_date 参与 hash**。不用可空日期直接承担物理组合唯一约束，不等于将其排除出身份。结束日期等内容改变会产生新 hash，不能把它描述成同一名称事件永远不变的 ID。
- 原记录提醒源端重复行可能进入批内冲突/拒绝诊断；不能无样本把它们全算“正常去重”。若要改变拒绝计数语义，需独立审计写入器，不在本次文档治理中修改。

具体解析和哈希见 [normalizer](/Users/congming/github/goldenshare/src/foundation/ingestion/normalizer.py)及 [row_transforms](/Users/congming/github/goldenshare/src/foundation/ingestion/row_transforms.py)。

## 4. 存储与观测

- 写入 `raw_tushare.namechange`，`raw_only_upsert`；幂等冲突列为 `row_key_hash`。自增 `id` 是物理主键，`row_key_hash` 是唯一业务身份。
- [Raw ORM](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_namechange.py)定义真实类型、可空性、物理索引及审计字段 `api_name/fetched_at/raw_payload`，不执行旧文档中“建议新增”的 DDL。
- `target_table=core_serving_light.namechange`；[Light 模型](/Users/congming/github/goldenshare/src/foundation/models/core_serving_light/namechange.py)对应 Raw 普通读取视图，不复制第二份物理数据，也不是 writer 的 DML 目标。
- 日期模型 `none / not_applicable`，无运营时间输入、无业务日期 observed field；`snapshot_run_trace` 关注最近成功维护，不做连续日期完整性判断。
- 已纳入 `reference_data_refresh`，见 [action_catalog](/Users/congming/github/goldenshare/src/ops/action_catalog.py)；手动、定时、重试是能力，不等于实时 schedule 状态已核验。

## 5. 回归与运行边界

- [Definition 回归](/Users/congming/github/goldenshare/tests/test_dataset_definition_registry.py)、[Resolver 回归](/Users/congming/github/goldenshare/tests/test_dataset_action_resolver.py)、[Ops 目录与工作流回归](/Users/congming/github/goldenshare/tests/test_ops_action_catalog.py)覆盖注册、输入及当前展开路径；日期/哈希相关样本见 [normalizer 回归](/Users/congming/github/goldenshare/tests/test_dataset_normalizer.py)。
- 本轮未新增源端调用或生产验收；不能从“已有实现”推出全部历史完整。扩大范围前，按开发模板核对真实请求量、单 unit 内存、提交量、取消和续跑证据，不把单页 1000 行当成整个任务上限。
