# A股财务指标（`fina_indicator`）维护说明

更新时间：2026-09-10。状态：已合并接入方案与 LLD；保留 2026-08-29 生产验收关闭结论。本文校准当前代码，不重新认证生产状态或追加回补任务。

## 1. 定位与主链

`fina_indicator` 按公告自然日维护全市场财务指标，调用 `fina_indicator_vip`，只物理写 `raw_tushare.fina_indicator`。`core_serving.equity_fina_indicator` 是显式列普通 view，不再写第二份 Serving 数据。

```text
手动 / cron maintain 意图 → DatasetActionResolver
  → build_natural_day_point_units → _fina_indicator_vip_params
  → DatasetSourceClient → normalizer → raw_only_upsert
  → raw_tushare.fina_indicator → core_serving.equity_fina_indicator view
```

不读取股票激活池，不按股票扇出，不使用普通 `fina_indicator` 单股通道，不新增 Std、版本历史或 JSON payload。底层域为 `low_frequency`；Ops 展示位于“A股财务数据”、Express 之后，二者不是同一个分类体系。

依据：[Definition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/low_frequency.py)、[源字段合同](/Users/congming/github/goldenshare/src/foundation/datasets/fina_indicator_contracts.py)、[Tushare doc 79](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/财务数据/0079_财务指标数据.md)。通用规则引用 [日期指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)与[执行计划](/Users/congming/github/goldenshare/docs/architecture/dataset-execution-plan-refactor-plan-v1.md)。

## 2. 输入、执行与观测分开

| 维度 | 当前合同 |
| --- | --- |
| 运营输入 | 单点 `ann_date`，或 `start_date/end_date` 自然日闭区间；无 filters、无 no-time |
| unit | 一个自然公告日、全市场；周末和空公告日不跳过 |
| 源参数 | builder 只生成 `ann_date=YYYYMMDD`；167 个 fields、limit/offset 由 source client 传入 |
| 分页 | `offset_limit`，每页 5,000；满页继续，短页（含空页）终止 |
| 规模 | `fetch_concurrency=1`，`max_units_per_execution=None`；不套用 Express 的 366 天上限 |
| 持久化 | 一个 unit 全部分页聚合、归一化后在业务事务内写 Raw；不是每页独立发布 |
| freshness | `event_run_trace`，观测 `ann_date`；不要求每日有公告 |
| 日期完整性 | `bucket_rule=not_applicable, audit_applicable=False`；不构造连续日期缺口 |
| 运营入口 | 手动、普通 cron、retry；不接 workflow、probe 或 fallback |

源接口的 `period/start_date/end_date/update_flag` 等筛选能力不等于运营输入。`fina_indicator_vip` 的源端 start/end 表示报告期范围，本系统的运营 start/end 表示公告日执行范围，不能直接透传替代逐日请求。

[planner](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py)使用通用自然日 builder。以首个单日为例，unit ID 为 `fina_indicator:2026-08-29:0`，进度上下文为 `{"ann_date":"2026-08-29","date_field":"ann_date"}`；不是独立股票对象或报告期窗口。

## 3. 字段、身份与修订

完整字段清单仅维护于 `FINA_INDICATOR_SOURCE_FIELDS`：167 个源字段，其中 `ts_code/ann_date/end_date/update_flag` 构成四字段身份，另有 163 个可空数值指标。请求、[Raw ORM](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_fina_indicator.py)、迁移和 view 必须一致。

| 内容 | 当前行为 |
| --- | --- |
| 代码 / 标识 | 清理 NUL；ts_code trim/upper，update_flag trim；四字段身份均不得为空 |
| 日期 / 指标 | ann_date/end_date 转 date；163 指标转 Decimal，数据库为无固定 precision/scale 的 Numeric，空值保留 NULL |
| 系统列 | `source_content_hash`、`api_name`、`fetched_at`；共 170 列，不保存 raw_payload |
| 内容指纹 | 以规范化后完整 167 字段计算；去重优先使用行转换生成的 canonical hash，不以原始字符串格式差异制造冲突 |
| 同批同身份 | 内容相同去重；内容不同整个 unit 失败，不能让最后一行胜出 |
| 不同批同身份 | GenericDAO upsert 覆盖非身份源字段、指纹和采集字段；同内容重跑不增行，但不承诺 fetched_at 不变 |
| 拒绝 / 空日 | 任一归一化拒绝使 unit 失败；合法空公告日可以成功，不删除已有 Raw 事实 |

`update_flag=0/1` 都保留，没有“只取 1”的过滤。Serving view 逐列直出全部四字段身份，不按公司/报告期选最新一行，也不把 0/1 合并。这与财务三表的七字段身份、版本筛选不同，不得为文档统一而改变。

实现：[row transform](/Users/congming/github/goldenshare/src/foundation/ingestion/row_transforms.py)、[normalizer](/Users/congming/github/goldenshare/src/foundation/ingestion/normalizer.py)、[writer](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py)、[BaseDAO](/Users/congming/github/goldenshare/src/foundation/dao/base_dao.py)。

## 4. 存储、事务与性能边界

- Raw 命名主键 `pk_raw_tushare_fina_indicator`；索引覆盖 `ann_date, ts_code` 与 `ts_code, end_date DESC, ann_date DESC, update_flag`。
- 历史迁移 [20260829_000160](/Users/congming/github/goldenshare/alembic/versions/20260829_000160_add_fina_indicator_dataset.py)承接 `20260829_000159`，显式把 heap、主键和两个索引放入 `gs_raw_cold_hdd`。缺少 tablespace 时拒绝创建，不回退默认盘，不自动分区；downgrade 拒绝删除事实。这不是未来新增迁移应复制的 head。
- 普通 view 无第二份存储或独立索引；Raw 提交后自动反映结果。
- DAO 按 PostgreSQL bind 参数预算分批：65,535 减 32 预留，170 列时最多 385 行，并受 `sync_batch_size` 限制；SQL batch 不改变 unit 事务边界。
- 一年约 365/366 个 unit，每个至少一次请求；返回满 5,000 行即追加请求，不能写成“超过 5,000 才分页”。所有页可能合并成超过 5,000 行的 unit，分页大小不是内存或事务行数上限。
- 已有 5,000 行 × 170 列替身测试证明 13 个 bind-safe SQL batch；它不是生产内存、事务时延或 WAL 测量。原方案要求的真实容量评估不能由这个测试冒充。

失败或取消保留先前已提交 unit；重试同范围依赖上述行级幂等。Ops 状态写入不得影响已提交 Raw。更大规模维护仍须按[模板长任务合同](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)核验内存、取消、持久化续跑及真实读回；本文不把旧验收升级为所有新门禁已通过，也不自行添加跨度阈值。

## 5. 自动任务与维护边界

复用 `since_last_success_day_range`：

1. 运营选择 daily/weekly/monthly cron，并填写 `initial_start_date`，保存在 `OpsSchedule.params_json.schedule_policy_params`；不是源接口 filter。
2. 目标结束日为排程时区触发日的前一天。无成功窗口时从 initial_start_date 开始；否则从同一 schedule、同一动作最后成功窗口末日加一开始，且不早于配置起点。
3. failed/canceled 不推进成功游标；空窗口跳过，不伪造成功业务运行。
4. 历史公告日发生晚到或修订，需要运营手动重跑；自动策略不会周期性回扫已成功的旧日期。

实现：[策略与能力](/Users/congming/github/goldenshare/src/ops/services/dataset_schedule_time_policy_resolver.py)、[窗口生成](/Users/congming/github/goldenshare/src/ops/services/task_run_service.py)、[排程事务](/Users/congming/github/goldenshare/src/ops/services/operations_schedule_service.py)。前端消费通用能力，不新增 fina_indicator 私有分支。

## 6. 历史源端验证与生产关闭

以下均为 2026-08-29 原接入记录，不是本轮重新请求或当前行数：

| 证据 | 当时结果 / 保留原因 |
| --- | --- |
| 字段 | 本地 167 个；默认仅 108，缺 59；显式 167 可返回。update_flag 输入已补入 doc 79，不再列为待补文档 |
| 普通接口 | 单股默认 100 行不能证明全集；按 50 行分页得到 50×4+4=204 |
| VIP 宽范围 | 无业务参数恰好 12,000 行、只涉及两个报告期；报告期宽区间也触及 12,000，不能作为完整基线 |
| VIP 单报告期 | period=20251231：6,818 行 / 6,251 代码；原 connector 核验记为 5000+1818+0，与基准键集合一致 |
| 分页记录边界 | 上行的额外空页保留为历史核验记录；当前 source client 在 1,818 短页就停止，不据历史序列要求追加探空页 |
| 公告日 | 20260430：1,723 行 / 1,251 代码；20260829 周六：1,650 行；20000101 为空，支持自然日而非交易日模型 |
| flag | 原样本有 1,214 条 flag=0、涉及 647 代码且无对应 flag=1，不能只存 1 |
| Prod 身份对账 | 42,809 行，四字段身份数同为 42,809；ann_date 范围 2025-01-01～2026-08-29 |
| Prod 存储 | Raw 四个 relation 均在 gs_raw_cold_hdd；Serving 为 0 字节普通 view |
| 一季报 | 5,493 / 5,496 家，99.95%；三项差异中，当时仍上市且季末前已上市的差异仅 002731.SZ，经确认不阻塞验收 |
| 半年报 | 5,368 / 5,528 家，97.11%，满足截至验收日超过 5,000 家披露的预期 |

原 FI-01～FI-10（VIP 全市场、167 fields、自然日 unit、四字段修订、Raw/view、HDD、事件观测、入口、无任意跨度上限、状态隔离）已按原接入范围验收，运营确认关闭。后续日常更新不是接入尾项，不再保留“可以进入 LLD”或重复开发里程碑。

## 7. 回归与文档边界

[专项测试](/Users/congming/github/goldenshare/tests/test_fina_indicator_dataset.py)覆盖字段合同、自然日与超 366 日规划、禁止筛选、逐页 fields、后页失败、空日、0/1 并存、canonical 去重/冲突、Raw-only writer、宽表批次、ORM/migration/catalog。公共回归继续看 registry、resolver、freshness 和 schedule 测试，不在本文复制全量通用门禁。

本次只合并文档，删除重复 LLD；不改字段、身份、类型、调度、数据库或生产数据。旧全文从 Git 历史追溯，后续实施仍按[数据集模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)与当时实际代码核验。
