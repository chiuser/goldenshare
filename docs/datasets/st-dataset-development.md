# ST 风险警示事件（`st`）维护说明

状态：当前代码说明；2026-09-10 文档治理核对。本文不证明生产部署、最新数据或自动任务状态；字段修复的历史证据与未核实验收见第 6 节。

## 1. 范围与依据

- Tushare `st`，doc_id=423；[本地源说明](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/基础数据/0423_ST风险警示板股票.md)。
- 当前事实源为 [reference_master Definition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/reference_master.py)；底层域 `reference_data / 基础主数据`，Ops 展示分组 `reference_data / A股基础数据`。
- 通用规则引用 [开发模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)与 [日期模型消费指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)，不重复粘贴完整 Definition、建表 SQL 或施工清单。

## 2. 输入与执行

- 动作为 `st.maintain`，仅支持 `time_input.mode=none`，默认业务请求 `{}`，可选 `ts_code`。
- `pub_date/imp_date` 是源结果字段，虽然接口允许过滤，现行运营入口不开放它们，也不按发布日期/实施日期展开 unit。
- generic planner 一个无日期 unit，源结果在 unit 内分页；不恢复按 `imp_date` 的独立动作。未来确有需求再评审，不列为本轮待办。
- 与 [stock_st 每日名单](/Users/congming/github/goldenshare/docs/datasets/stock-st-dataset-development.md)是两个数据集：本文是事件历史，对方是每天有哪些股票属于风险类型，不能互换日期模型、字段或存储路径。

`universe_policy=no_pool`；分页由 [SourceClient](/Users/congming/github/goldenshare/src/foundation/ingestion/source_client.py)注入 `limit=1000/offset`，空页或短页结束。[request builder](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)只生成业务参数。当前 `buffer_all + commit_policy=unit`，分页不切事务，也不代表页级持久化或中断后从任意页续跑。

## 3. 字段与身份

| 字段名 | 源类型 | 是否落 raw | 备注 |
| --- | --- | --- | --- |
| `ts_code` | string | 是 | 股票代码 |
| `name` | string | 是 | 股票名称 |
| `pub_date` | string | 是 | 发布日期；源站为 `YYYYMMDD` 字符串，raw 层直接落 `date` |
| `imp_date` | string | 是 | 实施日期；源站为 `YYYYMMDD` 字符串，raw 层直接落 `date` |
| `st_type` | string | 是 | 当前源站字段，表示风险警示类型 |
| `st_reason` | string | 是 | 变更原因 |
| `st_explain` | string | 是 | 详细原因说明 |

- 显式请求 `ts_code/name/pub_date/imp_date/st_type/st_reason/st_explain` 七字段；`ts_code/pub_date/st_type` 必填，`imp_date/name/st_reason/st_explain` 可空。
- `pub_date/imp_date` 直接转日期，代码大写，类型、名称及原因做文本清理。
- 哈希输入顺序为 `st, ts_code, pub_date, imp_date, st_type, st_reason, st_explain, name`；日期 ISO、空值为空串，`\x1f` 分隔后 SHA-256。
- 唯一现行类型字段为 `st_type`，不接受旧拼写别名、不新增双字段兼容。历史字段修复只改键名，不改哈希值输入、顺序和分隔符。

具体解析和哈希见 [normalizer](/Users/congming/github/goldenshare/src/foundation/ingestion/normalizer.py)及 [row_transforms](/Users/congming/github/goldenshare/src/foundation/ingestion/row_transforms.py)。

## 4. 存储与观测

- 写入 `raw_tushare.st`，`raw_only_upsert`；幂等冲突列为 `row_key_hash`。自增 `id` 是物理主键，`row_key_hash` 是唯一业务身份。
- [Raw ORM](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_st.py)定义真实类型、可空性、物理索引及审计字段 `api_name/fetched_at/raw_payload`，不执行旧文档中“建议新增”的 DDL。
- `target_table=core_serving_light.st`；[Light 模型](/Users/congming/github/goldenshare/src/foundation/models/core_serving_light/st.py)对应 Raw 普通读取视图，不复制第二份物理数据，也不是 writer 的 DML 目标。
- 日期模型 `none / not_applicable`，无运营时间输入、无业务日期 observed field；`snapshot_run_trace` 关注最近成功维护，不做连续日期完整性判断。
- 已纳入 `reference_data_refresh`，见 [action_catalog](/Users/congming/github/goldenshare/src/ops/action_catalog.py)；手动、定时、重试是能力，不等于实时 schedule 状态已核验。

## 5. 回归与运行边界

- [Definition 回归](/Users/congming/github/goldenshare/tests/test_dataset_definition_registry.py)、[Resolver 回归](/Users/congming/github/goldenshare/tests/test_dataset_action_resolver.py)、[Ops 目录与工作流回归](/Users/congming/github/goldenshare/tests/test_ops_action_catalog.py)覆盖注册、输入及当前展开路径；日期/哈希相关样本见 [normalizer 回归](/Users/congming/github/goldenshare/tests/test_dataset_normalizer.py)。
- 本轮未新增源端调用或生产验收；不能从“已有实现”推出全部历史完整。扩大范围前，按开发模板核对真实请求量、单 unit 内存、提交量、取消和续跑证据，不把单页 1000 行当成整个任务上限。

<a id="st-source-field-repair"></a>

## 6. 2026-08-12 字段修复：根因、迁移与证据

本节承接原 ST 字段修复 LLD 的有效信息；旧全文可从 Git 历史追溯。原记录状态为“本地已实现，待部署与生产验收”，2026-09-10 未新增生产核验证据，因此不改写为已部署或已验收。

### 根因与保留证据

- 历史 TaskRun `8080` 的 `st` 节点读到 `4147` 行，因缺旧字段全部拒绝；当时生产既有 `4126` 行类型有效，失败任务未写入新事实。
- 2026-08-12 的 tushareMcp 记录：默认返回及显式请求 `st_type` 均返回该字段；显式请求旧拼写 `st_tpye` 时源端静默省略。根因是字段合同漂移，不是任务参数、工作流或 writer 故障。
- 当时 Definition、ORM、视图和旧导出白名单共同沿用错误拼写；现行 Definition、transform、RawSt、StLight 和低频重建读取器已使用 `st_type`。

### 已实现的迁移安全边界

[revision 20260812_000133](/Users/congming/github/goldenshare/alembic/versions/20260812_000133_rename_st_type_field.py)接历史 revision `20260811_000132`，不是要求新迁移继续接这个旧 head。

1. PostgreSQL 下先确认 Raw 为物理表、Light 为普通 view，二者均有旧列、没有新列；不符合则报错，不猜测修复。
2. 依次重命名 `raw_tushare.st.st_tpye → st_type`、`core_serving_light.st.st_tpye → st_type`，之后再次检查只有新列。
3. 当时隔离 PostgreSQL 18.4 验证表明：只改 Raw 列名不会自动改视图输出列名，所以两条 DDL 都必要。
4. 不 DELETE、TRUNCATE、重建表、重放数据或重算 hash；既有行、索引、主键和哈希值保留。downgrade 明确拒绝，防止恢复失效字段。

### 当前消费者与退役边界

| 位置 | 当前作用 |
| --- | --- |
| Definition → SourceClient | 显式请求七字段，包含 `st_type` |
| normalizer / writer / RawSt | 按现行字段验证和 Raw-only upsert，保留原哈希值语义 |
| StLight | 普通 view 字段映射，不增加物理副本 |
| [stock_st 重建候选读取器](/Users/congming/github/goldenshare/src/foundation/services/migration/stock_st_missing_date_repair/candidate_loader.py) | 读取 RawSt，把 `row.st_type` 放入事件对象；不是每日名单同步的隐式步骤 |
| Ops 工作流 | 使用数据集身份、动作和运行结果，不承担源字段映射 |
| 旧 `ST_FIELDS` 静态 Lake 导出 | 已不在当前源码；只保留历史根因说明，不恢复为当前消费者或验收前置项 |

测试证据入口：[字段传递](/Users/congming/github/goldenshare/tests/test_dataset_source_client.py)、[新拼写正向/旧拼写负向与固定哈希](/Users/congming/github/goldenshare/tests/test_dataset_normalizer.py)、[迁移禁止项](/Users/congming/github/goldenshare/tests/test_st_source_field_contract_migration.py)。这些不能证明某个生产实例已应用迁移。

若另行授权补生产验收，先只读确认 head 与 Raw/Light 实际列名；需要迁移时再单独授权，并核对迁移前后行数和唯一 hash 数，最小维护记录 fetched/normalized/written/rejected。已清退的旧导出不再要求执行。本轮不迁移、不补跑、不删除数据。
