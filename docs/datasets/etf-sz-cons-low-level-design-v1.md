# `etf_sz_cons` 低层设计 LLD v1

状态：已完成生产验收。
对应方案：[ETF 每日持仓组合（深市）数据集接入方案](/Users/congming/github/goldenshare/docs/datasets/etf-sz-cons-dataset-development.md)
审计日期：2026-08-22

## 1. 本 LLD 的边界

本 LLD 落地深市 ETF 每日持仓组合的代码设计。部署、数据库迁移、对象池初始化、历史同步和页面验收由运营手动执行，不由本轮自动完成；这些生产步骤已于 2026-08-22 完成。

首期固定：

- 默认对象来自 `ops.etf_series_active(resource='etf_sz_cons')`。
- 对象池 seed 只接受 `.SZ + list_status='L'`，初始审计候选为 726 个；`.OF`、`.SH`、P/D 和其他后缀均不是有效对象。对象池不绑定固定行数，当前生产运营池为 720 个。
- 单日是“一个 ETF code 一个 unit”；区间是“一个 ETF code 一个自然月窗口 unit”。窗口内分页完成后才写入和提交。
- raw 保存全部 11 个源字段；`core_serving.etf_sz_cons` 仅普通 view 直出 raw，不建立 serving 物理表。
- 手动和普通自动任务可用；不加入既有 workflow，不新增 probe；输入区间不设置总跨度限制。
- 池为空、池内非法后缀、显式 code 不在池内、显式多 code 均直接失败；不静默跳过、不调用源站补池。

## 2. 代码审计结论

### 2.1 当前接入状态

实施前代码只有已落地的 `etf_sh_cons`。本轮实现后的当前状态如下：

- `etf_sh_cons` 继续保持既有 Definition、半年窗口、`.SH` 对象池和 raw/view 路径；
- `etf_sz_cons` 已新增 Definition、planner、request builder、raw ORM、DAO 属性、migration、view、freshness 和 catalog item；
- `EtfSeriesActiveSeedService` resource 白名单已包含 `fund_daily`、`etf_rt_daily`、`etf_sh_cons`、`etf_sz_cons`；深市资源只接受 `.SZ` code，不得只在 planner 中接受字符串；
- `DatasetWriter` 已有 `raw_only_upsert`，无需增加新的 writer 路径；
- `table_model_registry` 自动发现模型，但 DAOFactory 仍需显式暴露 raw DAO。

### 2.2 影响面表

| 层 | 真实入口 | 本次动作 |
| --- | --- | --- |
| Definition | `src/foundation/datasets/definitions/market_fund.py` | 新增 `etf_sz_cons` 事实定义 |
| active pool | `src/ops/services/etf_series_active_seed_service.py`、`src/foundation/dao/etf_series_active_dao.py` | 允许 `etf_sz_cons` resource；校验 `.SZ` |
| planner | `src/foundation/ingestion/unit_planner.py` | 新增 `build_etf_sz_cons_units` 和严格对象池解析 |
| request | `src/foundation/ingestion/request_builders.py` | 新增 `_etf_sz_cons_params`，point/range 映射源端参数 |
| source client | `src/foundation/ingestion/source_client.py` | 复用 `offset_limit`、`page_limit=3000` |
| normalizer | `src/foundation/ingestion/row_transforms.py` | 新增文本清洗，不丢空字段 |
| storage | `src/foundation/models/raw`、`DAOFactory`、Alembic | 新增 raw 表、索引、view |
| freshness | `src/foundation/datasets/freshness_policies.py` | 登记 `continuous_open_day` |
| Ops | `src/ops/catalog/dataset_catalog_views.py` | 放入 `etf_fund` 展示目录 |
| workflow/probe | `src/ops/action_catalog.py`、probe services | 不增加入口 |

### 2.3 CodeGraph 审计范围

已使用 CodeGraph 检查 `DatasetUnitPlanner.plan`、`DatasetActionResolver`、custom builder 分发、`_etf_sh_cons_params`、`DatasetSourceClient`、`DatasetWriter._write_raw_only_upsert`、`DAOFactory`、`table_model_registry`、`EtfSeriesActiveDAO`、`EtfSeriesActiveSeedService`、Ops catalog、manual action 和 freshness projection。

CodeGraph 索引正常：2,563 个文件、45,133 个节点、103,096 条边。影响面保持在 foundation ingestion/model/DAO 与 ops catalog/对象池配置；不改变依赖矩阵。

## 3. 源接口契约与真实证据

源站文档：[0472 ETF 每日持仓组合（深市）](/Users/congming/github/goldenshare/docs/sources/tushare/ETF专题/0472_ETF每日持仓组合(深市）.md)。文档由运营方提供，本轮不重复创建源站文档。

源字段固定为：

`trade_date, ts_code, con_code, con_name, qty, sub_flag, cpr, rdr, sub_cc, red_cc, exchange`

前置实测：

| 请求 | 实测结果 | 设计结论 |
| --- | --- | --- |
| `{}` | 3,000 条，日期混杂 | 不作为正式全集请求 |
| `trade_date=20260731` | 3,000 条，命中单页上限 | 禁止把首屏当完整日结果 |
| `ts_code=159919.SZ, trade_date=20260731` | 301 条 | 单 ETF 单日 unit 可控 |
| `ts_code=159051.SZ, trade_date=20260731` | 100 条 | 单 ETF 单日数据量可变 |
| `ts_code=159001.SZ, trade_date=20260731` | 1 条 | 小结果 ETF 也必须保留源站行 |
| `con_code=000001.SZ, trade_date=20260731` | 73 条，跨多个 ETF | `con_code` 不能作为默认维护对象 |
| 全部 11 个显式字段 | 样本字段均可返回，部分数值字段可空 | 全字段进入 `source_fields` 和 raw |
| 项目 connector 分页 `limit=100` | `159919.SZ + 20260731` offset 0/100/200/300，共 301 行；业务键无重复 | 分页和短页终止可复用，实施后仍需用真实 Definition 重跑 |

对象池 seed 审计：Tushare `etf_basic(exchange='SZ', list_status='L')` 返回 727 行，其中 `.SZ=726`、`.OF=1`（`158008.OF`）。因此 seed 输入只能取 726 个 `.SZ` 候选，不能把 `exchange='SZ'` 当作后缀门禁；候选数量不等于源端 `etf_sz_cons` 的可服务数量，也不是运行时固定值。

## 4. 三层语义与输入契约

| 层 | 固定语义 | 示例 |
| --- | --- | --- |
| Ops/TaskRun | 用户指定单日或任意跨度区间，可选一个 ETF code | `start_date=2026-01-01,end_date=2026-07-31` |
| resolver/planner | 从 active pool 取 code；point 生成单日 unit；range 按自然月切窗 | `159919.SZ + 2026-07-01~2026-07-31` |
| request builder | 将 unit 日期格式化为 Tushare `trade_date` 或 `start_date/end_date` | `{"ts_code":"159919.SZ","start_date":"20260701","end_date":"20260731"}` |

`con_code` 是源端查询过滤字段，不进入 `DatasetInputModel.filters`。原因是它会返回多个 ETF 的交叉结果，无法表达一个完整 ETF 组合 unit。`limit/offset` 由 source client 管理，不能暴露给 Ops。

## 5. Definition 设计

新增条目位置：`src/foundation/datasets/definitions/market_fund.py` 的 `DATASET_ROWS`。

```python
identity.dataset_key = "etf_sz_cons"
identity.display_name = "ETF 每日持仓组合（深市）"
domain = {"domain_key": "index_fund", "domain_display_name": "指数 / ETF"}
source.api_name = "etf_sz_cons"
source.source_fields = (
    "trade_date", "ts_code", "con_code", "con_name", "qty",
    "sub_flag", "cpr", "rdr", "sub_cc", "red_cc", "exchange",
)
source.source_doc_id = "tushare.etf_sz_cons"
source.request_builder_key = "_etf_sz_cons_params"
date_model = {
    "date_axis": "trade_open_day",
    "bucket_rule": "every_open_day",
    "window_mode": "point_or_range",
    "input_shape": "trade_date_or_start_end",
    "observed_field": "trade_date",
    "audit_applicable": False,
}
planning = {
    "universe_policy": "pool",
    "universe": {
        "request_field": "ts_code",
        "override_fields": ("ts_code",),
        "sources": (("ops_etf_series_active", "etf_sz_cons"),),
    },
    "pagination_policy": "offset_limit",
    "page_limit": 3000,
    "unit_builder_key": "build_etf_sz_cons_units",
}
storage = {
    "raw_dao_name": "raw_etf_sz_cons",
    "core_dao_name": "raw_etf_sz_cons",
    "target_table": "raw_tushare.etf_sz_cons",
    "delivery_mode": "raw_with_serving_view",
    "layer_plan": "raw->serving_view",
    "serving_table": "core_serving.etf_sz_cons",
    "raw_table": "raw_tushare.etf_sz_cons",
    "conflict_columns": ("trade_date", "ts_code", "con_code"),
    "write_path": "raw_only_upsert",
}
normalization = {
    "date_fields": ("trade_date",),
    "decimal_fields": ("qty", "cpr", "rdr", "sub_cc", "red_cc"),
    "required_fields": ("trade_date", "ts_code", "con_code"),
    "row_transform_name": "_etf_sz_cons_row_transform",
}
capabilities.actions = (maintain with manual_enabled=True,
                        schedule_enabled=True,
                        retry_enabled=True,
                        supported_time_modes=("point", "range"))
observability.freshness_policy = "continuous_open_day"
```

`completeness.scope=not_applicable`：V1 只接 freshness，不把 ETF × 日期缺行自动判为缺口。对象池本身是请求范围，不是完整性结果表。

## 6. Active pool 与 planner

### 6.1 active pool 白名单

修改 `src/ops/services/etf_series_active_seed_service.py`：

1. `ETF_SERIES_ACTIVE_RESOURCES` 增加 `etf_sz_cons`；
2. `etf_sz_cons` 不复用 `fund_daily` 的 1,395 行预期；它没有硬编码行数，只使用独立 `.SZ` 输入校验；
3. seed 行必须是 `.SZ`；`.OF`、`.SH` 和其他后缀直接报错；
4. 不在 seed service 中自动请求 Tushare、自动生成池或从其他 resource 复制；
5. `EtfSeriesActiveDAO.list_active_codes("etf_sz_cons")` 是 planner 唯一对象来源。

### 6.2 `build_etf_sz_cons_units`

实现位置：`src/foundation/ingestion/unit_planner.py` 的 `_CUSTOM_UNIT_BUILDERS` 及 custom builder。

对象解析：

1. 校验 Definition 是 `universe_policy=pool`，source 类型和 resource 精确匹配 `ops_etf_series_active/etf_sz_cons`；
2. 读取 active pool，排序并规范化大写；
3. 池为空抛 `universe_empty`；存在非 `.SZ` 抛明确的 `invalid_enum`；
4. 无显式 `ts_code` 返回全部池内 code；
5. 有显式 `ts_code` 时只能是一个 `.SZ` 且必须在池内；逗号多 code 直接失败；
6. 绝不调用 `etf_basic`、`etf_sz_cons` 或其他外部源接口做 fallback。

unit 生成：

- point：要求 `trade_date`，每个 code 生成一 unit，`trade_date` 为目标日；
- range：要求 `start_date/end_date`，调用 `_split_calendar_month_windows`，每个 code × 月窗口一 unit；不设置总区间上限；
- 每个 unit 的 `progress_context` 使用字符串日期，避免 Python `date` 进入 TaskRun JSON；
- 每个 unit 的分页政策和 page limit 来自 Definition，不由 UI 参数覆盖。

示例：

```json
{
  "unit_id": "etf_sz_cons:159919.SZ:2026-07:0",
  "request_params": {
    "ts_code": "159919.SZ",
    "start_date": "20260701",
    "end_date": "20260731"
  },
  "pagination_policy": "offset_limit",
  "page_limit": 3000
}
```

## 7. Request builder、分页与事务

`_etf_sz_cons_params` 位于 `src/foundation/ingestion/request_builders.py`，只格式化 planner 已决定的值：

- point 输出 `ts_code + trade_date=YYYYMMDD`；
- range 输出 `ts_code + start_date/end_date=YYYYMMDD`；
- 不输出 `con_code`、`limit`、`offset`；
- 缺 code、日期或不支持的 run profile 直接抛错，不偷偷改成全市场请求。

`DatasetSourceClient` 对每个 unit 追加 `limit=3000` 和递增 offset，直到短页。分页全部完成后才进入 normalizer/writer/commit。一个 unit 一个业务事务；页与页之间不提交。

性能基线：当前生产 pool 为 720 个 code，单日约 720 个 unit；一年约 8,640 个 code×自然月 unit，三年约 25,920 个 unit，实际 HTTP 请求数按每 unit page_count 计算。对象池数量可运营调整，估算必须以任务发起时的真实 pool 为准。不能用全市场单日 3,000 条截断结果减少请求，也不能把一个长区间直接交给 Tushare。

## 8. Schema、模型、DAO 与 view

### 8.1 raw 表

新增迁移必须接实施时真实 head；本轮实施前 `uv run alembic heads` 为 `20260822_000140`，新迁移已正确接续该 head。

表：`raw_tushare.etf_sz_cons`。

| 列 | 类型 | 空值 | 说明 |
| --- | --- | --- | --- |
| `trade_date` | `DATE` | 否 | 源字段，主键 |
| `ts_code` | `VARCHAR(16)` | 否 | ETF code，主键 |
| `con_code` | `VARCHAR(16)` | 否 | 成分 code，主键 |
| `con_name` | `VARCHAR(128)` | 是 | 成分名称 |
| `qty` | `NUMERIC(24,6)` | 是 | 股票数量，保留源值 |
| `sub_flag` | `VARCHAR(16)` | 是 | 现金替代标志 |
| `cpr` | `NUMERIC(24,8)` | 是 | 申购现金替代保证金率 |
| `rdr` | `NUMERIC(24,8)` | 是 | 赎回现金替代保证金率 |
| `sub_cc` | `NUMERIC(24,8)` | 是 | 申购替代金额 |
| `red_cc` | `NUMERIC(24,8)` | 是 | 赎回替代金额 |
| `exchange` | `VARCHAR(16)` | 是 | 成分证券交易所 |
| `api_name` | `VARCHAR(32)` | 否 | 固定 `etf_sz_cons` |
| `fetched_at` | `TIMESTAMPTZ` | 否 | 入库时间 |
| `raw_payload` | `TEXT` | 是 | 原始行载荷 |

主键固定为 `(trade_date, ts_code, con_code)`。`exchange` 不能替代主键，因为它是成分证券市场，不是 ETF 对象池市场。实施前需复核同 ETF/日期分页合并后的业务键无重复。

索引：`(ts_code, trade_date)`、`(con_code)`。不建冗余单列 `(trade_date)` 索引，因为主键 `(trade_date, ts_code, con_code)` 已覆盖按业务日期的前缀查询。view `core_serving.etf_sz_cons` 与 raw 逐列一致。

### 8.2 ORM 与 DAO

新增：

- `src/foundation/models/raw/raw_etf_sz_cons.py`，类 `RawEtfSzCons`；
- `DAOFactory.raw_etf_sz_cons = GenericDAO(session, RawEtfSzCons)`；
- migration 创建 raw 表、索引和 view。

`table_model_registry` 自动发现 ORM；仍需补 table-to-model 测试。不要创建 serving ORM，不要创建专用 DAO，不要复制一份 core 物理表。

## 9. Normalizer 与 writer

新增 `_etf_sz_cons_row_transform`：

- 去除文本 NUL；
- `ts_code`、`con_code`、`exchange` trim/大写；
- `con_name`、`sub_flag` 保留源值和空值；
- 不计算、不改写 `qty/cpr/rdr/sub_cc/red_cc`。

日期和数值转换由 normalizer 定义负责。缺 `trade_date/ts_code/con_code` 的行必须记录 reason code 和样本并计入 reject，不能因源端返回空字段而静默写入。

writer 必须命中 `raw_only_upsert`，只调用 `raw_etf_sz_cons`。`core_serving.etf_sz_cons` 由数据库 view 读取 raw；不调用 serving DAO。业务 commit 由执行器控制，Ops 状态写入失败不影响业务事务。

## 10. Ops、freshness 与 workflow

- `dataset_catalog_views.py` 已增加 `DatasetCatalogItem("etf_sz_cons", "etf_fund", 60)`；
- manual action 自动从 Definition 得到“单日/区间/ETF代码”字段；
- ordinary schedule 可配置，运行时间由运营安排在深交所源站盘前组合发布完成后；
- `freshness_policies.py` 登记 `etf_sz_cons -> continuous_open_day`，观测 raw `trade_date`；
- `audit_applicable=False`，本期不做日期 × ETF 完整性审计；
- `daily_market_close_maintenance` 和其他已有 workflow 不新增步骤；
- 不新增 `remote_etf_sz_cons_ready` 或其他 probe。

## 11. 测试与硬需求追溯账本

| 硬口径 | 正向测试 | 负向测试/验收 |
| --- | --- | --- |
| `.SZ + L` 对象池 | planner 使用 `resource=etf_sz_cons` 并逐 code 生成 unit | 运营初始化时排除 `.OF/.SH/P/D`；运行时空池、池内非 `.SZ` 后缀必须失败，不能 fallback |
| 显式单 code | 单个池内 `.SZ` code 生成 unit | 非 `.SZ`、不在池内、逗号多 code 拒绝 |
| point/range | point 一 code 一 unit；range 一 code 一自然月 unit | range 不得按每交易日拆分，不得限制总跨度 |
| 请求参数 | point 为 `ts_code+trade_date`；range 为 `ts_code+start/end` | 不得输出 `con_code/limit/offset`，不得把月键提前传给源端 |
| 分页 | 3000 page limit、短页终止、业务键合并 | 首页满 3000 不得判定 unit 完成 |
| 全字段 | 11 个源字段进入 source_fields/ORM/view | 缺身份字段或 transform 不存在必须失败 |
| raw-only | writer 只写 raw | serving DAO 不得被调用 |
| Ops | ETF 分类、manual/schedule route 出现 | workflow/probe 不应出现 |

必须新增/更新测试：Definition registry、planner、request builder、source pagination、normalizer、raw-only writer、model registry、active seed service、Ops catalog/manual action、freshness policy。必须通过 `ingestion-lint-definitions` 和 docs integrity。

生产闭环已记录：TaskRun `9080` 对 `2026-01-05 ~ 2026-08-21` 完成 5,808 个 unit，读取和写入均为 11,251,932 行，拒绝为 0。`raw_tushare.etf_sz_cons` 与 `core_serving.etf_sz_cons` view 均为 11,251,932 行，日期范围同为 `2026-01-05 ~ 2026-08-21`。代表性小/大 ETF 的 connector 分页、字段和业务键验证见第 13 节；本次无 reject reason 需要解释。

## 12. 实施顺序与停止条件

1. M0：已完成。实施前复核 Alembic head 为 `20260822_000140`；已用项目 connector 验证小 ETF 点日期和大 ETF 月窗口。
2. M1：已完成。`etf_sz_cons` 已加入 active resource 白名单，并在 seed/planner 两处强制 `.SZ`。
3. M2：已完成。新增 raw ORM、DAO、迁移和 view。
4. M3：已完成。Definition、freshness、自然月 planner、request builder 和 row transform 已落地。
5. M4：已完成。Ops catalog 自动投影和定向测试已覆盖。
6. M5：已完成。代码侧验证、生产部署、迁移、对象池初始化、同步和页面验收均已完成。

以下情况必须停止，不做临时兼容：seed 输入含非 `.SZ` 或非 L 代码、active pool 含非法后缀、源端同键重复、月窗口分页不闭合、源字段缺失、迁移 head 不明确、reject 无法解释、业务事务和 Ops 状态事务发生耦合。

## 13. 实现与生产验收闭环

代码、部署和生产验收均已完成。

- 新迁移为 `20260822_000141_add_etf_sz_cons_dataset.py`，`down_revision` 为实施时确认的 `20260822_000140`。
- 项目 connector 只读验证：`159001.SZ + 20260731` 返回 1 行、1 次请求、业务键无重复；`159919.SZ + 20260701~20260731` 返回 6,020 行、3 次分页请求、20 个业务日期、`(trade_date, ts_code, con_code)` 无重复，11 个源字段齐备。
- 生产激活池初始按 `.SZ + list_status='L'` seed 为 726 个候选，非法后缀数量为 0。源端复核后，6 个 `list_status='L'` 但 `etf_sz_cons` 无日期请求和 `2026-01-05 ~ 2026-08-21` 区间请求均返回空数组的代码已退出池：`158001.SZ`、`158008.SZ`、`158010.SZ`、`158017.SZ`、`158019.SZ`、`159096.SZ`。
- 生产区间任务 `TaskRun 9080` 成功完成：`unit_total=unit_done=5808`、`unit_failed=0`、`rows_fetched=rows_saved=11251932`、`rows_rejected=0`。
- 生产 raw 表和 serving view 均为 11,251,932 行，覆盖 154 个交易日、717 个实际返回数据的 ETF，日期范围同为 `2026-01-05 ~ 2026-08-21`；运营页面验收通过。当前 active 池为 720 个，其中另 3 个待上市代码 `158000.SZ`、`158005.SZ`、`159043.SZ` 分别计划于 `2026-08-26`、`2026-08-24`、`2026-08-24` 上市，保留等待后续源端数据发布。
- 当前没有本数据集的待部署、待迁移、待对象池初始化或待页面验收事项。
