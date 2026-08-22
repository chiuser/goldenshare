# ETF 份额规模（`etf_share_size`）数据集接入方案

状态：已完成。已完成运营部署、数据库迁移、最小生产同步与页面验收。

审计日期：2026-08-22  
上游接口：Tushare `etf_share_size`，文档 0408  
源站文档：[ETF份额规模](/Users/congming/github/goldenshare/docs/sources/tushare/ETF专题/0408_ETF份额规模.md)

## 1. 结论

`etf_share_size` 当前没有进入 Goldenshare 的 DatasetDefinition、ingestion、ORM/DAO、Ops 目录或生产表。它适合按“一个交易日一个 unit”请求源站当日 ETF 全量结果，而不是按 ETF 代码乘交易日展开。

首期固定采用：

- 保留源站返回的全部字段和全部当日结果。
- 写入 `raw_tushare.etf_share_size`。
- `core_serving.etf_share_size` 只建立普通 view，直接读取 raw，不再写第二份 serving 物理表。
- 默认不使用 ETF 激活池。原因是实测一个交易日源站返回 1,637 条，而当前 ETF 池的规模小于源站当日结果，使用激活池会把源站事实截断。
- 手动任务和自动任务均可支持；首期不加入既有工作流，不做专用 probe。
- 默认维护按交易日执行；区间维护由 resolver 展开为交易日 unit，每个 unit 请求该交易日全市场数据。

本方案的代码设计与实现、运营部署、生产数据库迁移、最小生产同步和页面验收均已完成。后续数据范围扩展仍由运营方按正常维护流程执行。

## 2. 审计事实

### 2.1 开发前接入状态（历史审计）

| 检查项 | 当前结果 |
| --- | --- |
| DatasetDefinition | 未发现 `etf_share_size` |
| request builder | 未发现 `_etf_share_size_params` |
| unit planner | 未发现 `build_etf_share_size_units` |
| raw ORM / DAO | 未发现 `raw_tushare.etf_share_size` |
| Ops catalog | 未发现 `etf_share_size` |
| freshness policy | 未登记 |
| 自动任务 / 工作流 | 未发现 |
| 本地源站索引 | 有 `408, ETF份额规模, etf_share_size` |

当前 ETF 相关主线集中在：

- `src/foundation/datasets/definitions/market_fund.py`
- `src/foundation/ingestion/unit_planner.py`
- `src/foundation/ingestion/request_builders.py`
- `src/foundation/ingestion/source_client.py`
- `src/foundation/ingestion/row_transforms.py`
- `src/foundation/ingestion/writer.py`
- `src/foundation/dao/etf_series_active_dao.py`
- `src/ops/catalog/dataset_catalog_views.py`
- `src/foundation/datasets/freshness_policies.py`

CodeGraph 已审计现有 `etf_sh_cons` 的 Definition、planner、request builder、source client、writer、DAO、ETF active pool、freshness、Ops catalog 影响面。新数据集可以复用这些通用机制，但不能复用 `etf_sh_cons` 的深市代码池和半年 unit 语义。

### 2.2 源站文档事实

源接口文档说明：

- 接口：`etf_share_size`。
- 描述：获取沪深 ETF 每日份额、规模、净值和收盘价。
- 建议每日 19 点后提取，因为指标分批入库；海外 ETF 晚些更新属于正常情况。
- 单次最大 5,000 条。
- 输入参数：`ts_code`、`trade_date`、`start_date`、`end_date`、`exchange`，均为可选。
- 输出字段：`trade_date`、`ts_code`、`etf_name`、`total_share`、`total_size`、`nav`、`close`、`exchange`。

源站文档已存在于 Goldenshare；不重复创建源站事实文档。实施前仍需用项目实际 connector 完成分页实测。

### 2.3 `tushare-data` 家族结论

该接口属于 ETF/基金每日行情与规模事实，适合做日频观察和资金规模变化分析；skill 只用于接口家族理解，具体字段、行数和日期语义以本地源文档与 `tushareMcp` 实测为准。

### 2.4 `tushareMcp` 实测矩阵

实测使用接口返回的默认字段和显式字段；测试日期为 `20260821`，对象样本为 `510300.SH`。

| 请求形态 | 实际参数 | 返回情况 | 结论 |
| --- | --- | --- | --- |
| 不传业务参数 | `{}` | 5,000 条；首行 `trade_date=20260821`，末行 `trade_date=20260818` | 命中单次上限，日期混杂，不能作为全集基线 |
| 只传对象 | `ts_code=510300.SH` | 3,297 条，首日 `20260821`，末日 `20130123` | 可查单 ETF 历史，但仍需 connector 分页验证 |
| 只传时间点 | `trade_date=20260821` | 1,637 条，均为 `20260821` | 当前规模低于 5,000，适合默认日 unit |
| 对象 + 时间区间 | `ts_code=510300.SH, start_date=20260818, end_date=20260821` | 4 条，日期为该区间内交易日 | 可用于单 ETF 修复，但默认全量维护不采用 |
| 显式关键字段 | `trade_date,ts_code,etf_name,total_share,total_size,nav,close,exchange` | `20260821` 全市场 1,637 行均包含 `nav`、`close` | 全部 8 个源字段必须进入 `source_fields` |
| 默认日分页 | 项目 connector：`trade_date=20260821, limit=5000, offset=0/5000` | 第 1 页 1,637 条，第 2 页 0 条；同日无重复主键 | 短页终止、字段和业务键已实测 |
| 无日期分页 | 项目 connector：`limit=5000, offset=0/5000` | 两页各 5,000 条，跨日期且有 91 个跨页重复业务键 | 无日期请求不能进入默认维护链路 |

补充证据：`etf_basic(exchange='SZ')` 实测返回 788 条，其中 `.SZ` 786 条、`.OF` 2 条；这说明当前 ETF 主数据范围与 `etf_share_size` 单日返回的 1,637 条不是同一个数量口径，不能用某个现有池替代源站日快照。

生产激活池只作为对账参考，不作为入库过滤条件：只读审计显示，`ops.etf_series_active(resource='fund_daily')` 当前有 1,395 个代码；在 2026-08-18 至 2026-08-21 四个业务日，`etf_share_size` 源站结果均命中这 1,395 个代码，同时还返回激活池之外的源站代码。因此默认维护必须保存源站返回的全部结果，不能只保存激活池命中的数据。

## 3. 三层语义拆分

| 语义层 | 本方案口径 | 核验依据 |
| --- | --- | --- |
| 时间输入语义 | 运营提交一个交易日，或一段交易日期区间；日期表达的是要拉取的 ETF 份额规模业务日 | 源文档 `trade_date/start_date/end_date`；MCP 点查询只返回目标日 |
| 执行 / unit 语义 | 单日一个全市场 unit；区间由 resolver 按交易日展开为多个全市场日 unit；不做 ETF × 日期 fan-out | `trade_date=20260821` 返回 1,637 条且低于 5,000 上限 |
| freshness / audit 语义 | V1 只做 freshness，不做日期 × ETF 完整性审计；判断的是源站日快照是否已进入 raw，不把当前 ETF 数量硬编码成完整性基准 | 源站存在海外 ETF 延迟，且未建立稳定的全量 subject universe |

`bucket_rule` 建议为 `every_open_day`，`date_axis` 为 `trade_open_day`，`input_shape` 为 `trade_date_or_start_end`。`audit_applicable=false` 只表示暂不做日期对象矩阵审计，不表示不支持日期输入。

## 4. 推荐的 DatasetDefinition

### 4.1 基本事实

| 字段 | 建议值 |
| --- | --- |
| `dataset_key` | `etf_share_size` |
| `display_name` | `ETF 份额规模` |
| `domain` | `index_fund / 指数 / ETF`，沿用现有 ETF 分类 |
| `source.api_name` | `etf_share_size` |
| `source_doc_id` | `tushare.etf_share_size` |
| `request_builder_key` | 新增 `_etf_share_size_params` |
| `planning.unit_builder_key` | 新增 `build_etf_share_size_units` |
| `planning.universe_policy` | `no_pool`；默认按交易日请求源站当日全量 |
| `planning.pagination_policy` | `offset_limit` |
| `planning.page_limit` | `5000`，仍由 source client 统一分页 |

### 4.2 输入字段

建议只暴露：

- 时间：`trade_date` 或 `start_date/end_date`。
- 可选局部维护过滤：`ts_code`，单个 ETF 代码；这只影响该次显式局部任务，不改变默认保存源站全量结果的口径。

不暴露 `limit/offset`。`exchange` 不作为默认运营输入，因为默认日查询已能返回 SSE/SZSE 的全量结果，增加交易所筛选会把全量维护能力拆成两个容易漏跑的运营参数。若后续真实 connector 证明日结果超过 5,000，再单独评审是否按交易所拆 unit。

### 4.3 请求参数

- 默认单日：`trade_date=YYYYMMDD`。
- 显式单 ETF 单日：`ts_code=<code>, trade_date=YYYYMMDD`。
- 区间：resolver 先按交易日拆 unit，每个 unit 仍请求 `trade_date=YYYYMMDD`；不直接把全市场区间请求交给源站。

这样做的原因是：不带日期的全市场请求会混合多日数据、触及 5,000 上限并出现跨页重复；按交易日 unit 可以把完整性和事务边界固定在一个业务日。

## 5. 存储与字段设计

### 5.1 存储口径

首期建议：`raw_only_upsert + serving view`。

- raw 表：`raw_tushare.etf_share_size`。
- 对外 view：`core_serving.etf_share_size`。
- 不创建 serving 物理表，不双写两份业务数据。
- Ops/TaskRun 状态与业务数据事务隔离。

### 5.2 字段端到端对账表

| 源字段 | 文档 | MCP 默认 | MCP 显式关键字段 | raw ORM/迁移 | serving view | 必填/主键角色 |
| --- | --- | --- | --- | --- | --- | --- |
| `trade_date` | 是 | 是 | 是 | `DATE` | 是 | 必填；主键 |
| `ts_code` | 是 | 是 | 是 | `VARCHAR(16)` | 是 | 必填；主键 |
| `etf_name` | 是 | 是 | 是 | `VARCHAR(256)` | 是 | 事实字段，可空性按源样本核定 |
| `total_share` | 是 | 是 | 是 | `NUMERIC` | 是 | 规模事实 |
| `total_size` | 是 | 是 | 是 | `NUMERIC` | 是 | 规模事实，可为空 |
| `nav` | 是 | 否 | 是 | `NUMERIC` | 是 | 份额净值，可为空 |
| `close` | 是 | 否 | 是 | `NUMERIC` | 是 | 收盘价，可为空 |
| `exchange` | 是 | 是 | 是 | `VARCHAR(16)` | 是 | 市场事实 |

建议主键：`(trade_date, ts_code)`。实施前必须用项目 connector 在同一日期验证是否存在重复键；若存在，必须停下来重新评审主键，不得用 hash 临时覆盖。

Goldenshare 内部字段 `api_name`、`fetched_at`、`raw_payload` 可按现有 raw 表规范保留，但不能混入 `source_fields`。

## 6. Ingestion 实现边界

预计改动范围：

- `src/foundation/datasets/definitions/market_fund.py`
- `src/foundation/ingestion/unit_planner.py`
- `src/foundation/ingestion/request_builders.py`
- `src/foundation/ingestion/row_transforms.py`
- 新增 raw ORM、DAO factory 注册和 Alembic migration
- `src/foundation/datasets/freshness_policies.py`
- `src/ops/catalog/dataset_catalog_views.py`
- 相关 definition、planner、request、normalizer、writer、model、catalog 测试

不改：

- 现有 ETF 日线、ETF 申赎清单的请求和写入语义。
- `daily_market_close_maintenance` 工作流。
- 其他 ETF 激活池资源。
- 前端通用日期控件的公共语义。

Writer 复用现有 `raw_only_upsert`；不能为本数据集新增 serving 双写分支。每个交易日 unit 拉完全部分页、完成 normalize 后，再以单事务 upsert。

## 7. Ops、自动任务与 freshness

- Ops 展示分组：`etf_fund`，名称为“ETF 份额规模”。
- 手动任务：单日、区间；可选单个 `ts_code` 做局部修复。
- 自动任务：支持普通 schedule，推荐在源站发布时点之后运行；不允许把 `exchange`、`limit`、`offset` 暴露为普通运营参数。
- freshness：建议登记 `continuous_open_day`，但以 19:00 发布时点作为运营配置前提；早于 19:00 的 `unconfirmed` 不能误报为滞后。
- 日期完整性审计：V1 不启用，不根据当前 ETF 数量推断“应该有多少条”。
- 探测：V1 不新增专用 probe；如果生产中发现 19:00 后仍有明显分批延迟，再单独设计源站就绪探测，不复用其他数据集的样本或条件。

## 8. 性能与事务门禁

以当前 MCP 实测规模估算：

| 场景 | unit 数 | 请求量估计 |
| --- | ---: | ---: |
| 单日全量 | 1 | 1 页，当前约 1,637 行 |
| 1 年历史 | 约 245 个交易日 unit | 约 245 页，若未来超过 5,000 则按分页增加 |
| 3 年历史 | 约 735 个交易日 unit | 约 735 页，按实际分页增加 |
| 单 ETF 修复 | 1 个 code × 输入日期 unit | 按日期范围拆分，避免宽区间单事务 |

硬门禁：

1. 真实 connector 必须验证 `limit/offset`、短页终止、分页合并和唯一键集合。
2. 单个交易日 unit 的真实返回不能超过声明的源行数安全边界；若接近 5,000，必须先重新评估是否按交易所拆分。
3. 不允许把“不传参数返回 5,000 条”当作全量成功。
4. 不允许通过扩大单事务范围来减少请求次数。

## 9. 开发里程碑

| 阶段 | 目标 | 关键动作 |
| --- | --- | --- |
| M0 | connector 与字段门禁 | 已确认真实 Alembic head；项目 connector 已验证默认日短页、显式字段、同日唯一键和无日期分页风险 |
| M1 | Schema 与 view | 已新增 raw ORM、DAO、迁移、`core_serving.etf_share_size` view；未建 serving 物理表 |
| M2 | Definition 与 planner | 已新增按交易日 unit 的 Definition、resolver 投影、request builder；显式 code 只做局部过滤 |
| M3 | Normalizer / writer | 已接通全部 8 个源字段，数值/日期转换，按 `(trade_date, ts_code)` 幂等 upsert |
| M4 | Ops 与 freshness | 已加入 ETF 分类目录、手动/自动能力、freshness policy；未加入既有收盘工作流 |
| M5 | 本地测试与交接 | 已完成 Definition、planner、source、normalizer、writer、model、Ops 和架构护栏测试 |
| M6 | 运营方部署与验收 | 已完成生产部署、迁移、最小数据同步和页面验收 |
| M7 | 文档收口 | 已完成；本文档状态已按最终验收事实收口 |

## 10. 已确认口径

1. **默认不使用 ETF 激活池**：源站单日实测 1,637 条，而当前 ETF 池规模更小；复用激活池会让 raw 不再代表源站当日全量。
2. **首期不加入既有工作流**：只支持手动和自动任务，避免在源站发布前触发。
3. **采用 raw-only + view**：保留源站事实且不产生第二份 serving 物理数据。
4. **允许单 ETF `ts_code` 修复过滤**：不改变默认全市场按日维护语义；不允许多个 code 拼接。
5. **首期不做专用 probe**：使用运营配置的普通 schedule。
6. **部署后的同步与回补由运营方负责**：本方案不设计单独的回补流程，也不代执行部署、迁移或生产同步。

## 11. 验收标准

- 一天默认只生成一个全市场 unit，默认请求返回该日全量 ETF 份额规模。
- `nav`、`close` 等默认返回中没有的字段也会通过显式 `source_fields` 请求并落库。
- 区间任务不直接把宽区间交给源站，而是由 resolver 按交易日生成 units。
- `raw_tushare.etf_share_size` 与 `core_serving.etf_share_size` view 字段一致。
- 任何 source reject 都有明确 reason code 和样本；不能以“源站分批入库”为理由吞掉 reject。
- Ops/TaskRun 状态写入失败不影响 raw 业务事务。
