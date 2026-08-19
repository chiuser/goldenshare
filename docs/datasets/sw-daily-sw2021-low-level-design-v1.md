# 申万 SW2021 行业日行情 `sw_daily` Prod 数据集 LLD v1

> 状态：M0～M4 已完成；迁移 `20260818_000138`、分类和成员生产发布及幂等重放已通过。M5 日行情生产发布进行中：OHLC 取整纠偏部署后，TaskRun `8732` 已发布 2026-07-01～2026-08-18 共 35 个交易日；2026-08-19 源端尚未出数触发空结果失败。用户已拍板单日源端空结果应安全跳过、不写数据库且不使任务失败，本地声明式契约、正反例和回归已完成，待部署后生产验收。
> 初版：2026-08-16；代码对账：2026-08-17；最终产品拍板：2026-08-18；M2/M3 纠偏验收与 M4 本地验收：2026-08-19。
> 前置 LLD：[申万 SW2021 行业分类 `index_classify` Prod 数据集 LLD v1](./index-classify-sw2021-low-level-design-v1.md)。
> 上游产品依据：[板块雷达产品设计方案 v1](../../wealth/docs/pages/wealth-exploration/sector-radar-product-design-v1.md)。
> 数据依据：[板块雷达数据覆盖审计 v1](../../wealth/docs/pages/wealth-exploration/sector-radar-data-coverage-audit-v1.md)。
> 源站依据：Tushare `sw_daily`，本地文档 `docs/sources/tushare/指数专题/0327_申万行业日线行情.md`（doc_id=327）。

---

## 0. 2026-08-18 最终拍板

以下两项由用户按推荐方案确认，已成为三份申万数据集 LLD 的共同硬约束，不再列为待拍板项：

1. `index_classify` 首版只保留最近一次成功发布的完整 SW2021 分类快照，不保存抓取时点历史，也不把观察时间伪装成官方分类生效时间。历史研究如使用分类表，必须标注“按当前 SW2021 分类重述历史”。
2. `sw_daily` 服务表保留源接口按交易日返回的全部申万指数事实；板块雷达只在查询时与 `index_classify` 内连接并过滤 `is_pub=true`。源端额外综合/风格指数不得在 Foundation 入库阶段丢弃，也不得进入正式行业榜。

成员数据仍完整保存 Y/N 当前与历史关系；`out_date` 边界必须由业务样本核验，不属于偏好选择。

---

## 1. 结论与边界

本数据集负责按交易日获取 Tushare 申万 2021 行业指数日行情，并直接发布到 Prod `core_serving.sw_industry_daily`。它保存源接口当日返回的全部申万指数行；板块雷达的“可发布 SW2021 行业池”由查询时与分类表 `src='SW2021' AND is_pub=true` 内连接得到。

已冻结口径：

1. 数据集 key 和源 API 均固定为 `sw_daily`。
2. 首版只服务 SW2021，不建设 SW2014 分支或兼容表。
3. 使用 `source -> core_serving` direct-serving；不建设 Raw、Lake 或双写。
4. 主维护请求必须按单个 `trade_date` 拉取当日全体申万指数；禁止不传日期拉取，禁止用宽日期区间作为日常或历史主链。
5. 源端 `ts_code` 保存为 `source_ts_code`，跨表和业务查询使用标准化 `ts_code`。
6. “特钢Ⅲ”业务码固定为 `850412.SI`；`840401` 禁止进入规则、表和测试。
7. 服务表保留当日源接口返回的 15 个字段，即使某些申万综合/风格指数不在行业分类表中；产品行业榜必须内连接当前分类并过滤 `is_pub=true`。
8. 首版不建设技术指标、复权、行业权重、研究分数、API 或前端。

### 1.1 架构归属

```text
Ops point/range intent
  -> DatasetDefinition(sw_daily)
  -> DatasetActionResolver(trade_open_day/every_open_day)
  -> 每个开市日 1 个 unit
  -> Tushare sw_daily(trade_date=YYYYMMDD)
  -> offset/limit 分页
  -> 代码标准化与日内唯一性校验
  -> core_serving.sw_industry_daily
  -> Ops TaskRun / continuous_open_day freshness
```

- Foundation domain：`board_theme`。
- Ops 展示分组：`board_theme / 板块 / 题材`。
- 交易日历：复用现有上交所交易日解析契约。
- 依赖方向不变，不把业务排名或页面过滤逻辑下沉到 Foundation。

---

## 2. 真实源接口证据

### 2.1 请求矩阵

2026-08-16 通过项目现有 `TushareHttpClient` 只读实测：

| 请求形态 | 参数 | 行数/分页 | 结论 |
|---|---|---:|---|
| 不传业务参数 | `{}` | 恰好 4,000 行，日期 `20260803..20260814` | 命中接口上限并截断，禁止作为全集或历史基线 |
| 单交易日全集 | `trade_date=20260814` | 439 行、439 个代码 | 正式单日主请求形态 |
| 两日区间 | `start_date=20260813,end_date=20260814` | 878 行，每日 439 | 能返回区间，但主链仍必须拆成每日 unit |
| 单对象全历史 | `ts_code=850412.SI` | `2000/1410`，合计 3,410 | 覆盖 `20120801..20260814`，业务码有真实行情 |
| 异常源代码 | `ts_code=850401.SI` | 0 行 | 分类异常码没有行情 |
| 代表行业全历史 | `ts_code=801010.SI` | `2000/1410`，合计 3,410 | 覆盖 `20120801..20260814`，主键无重复 |
| 早期单日 | `trade_date=20120731` | 199 行 | SW 行情早期已存在，但代码池不同 |
| 边界单日 | `trade_date=20120801` | 586 行 | 不能据单个代码断言全市场统一起点 |
| 默认字段 | `trade_date=20260814`，不传 `fields` | 已实测 | 不能替代显式 15 字段白名单 |
| 显式完整字段 | `trade_date=20260814`，显式 15 字段 | 439 行 | 正式 connector payload 必须逐页携带全部字段 |

单对象 `850412.SI` 和 `801010.SI` 的 `(ts_code,trade_date)` 重复均为 0。

`tushare-data` 接口家族结论：`sw_daily` 是申万指数日行情接口，不提供分类层级或成分有效期；行业池必须与 `index_classify` 联接，历史成员研究必须另用 `index_member_all`。

2026-08-19 M4 开工前又通过 `tushareMcp` 做了只读复核：`trade_date=20260814` 显式请求 15 字段返回 439 行、439 个唯一代码且日期全集仅为 `20260814`；15 个字段均实际返回，其中 `pe` 空 1 行；`850412.SI` 默认字段与显式 15 字段请求均返回同一条“特钢Ⅲ”事实。该工具未暴露 `limit/offset`，所以分页契约继续以本地源文档、既有 HTTP 审计和 M4 可执行 source-client 边界测试为依据，不伪造 MCP 分页结论。

### 2.2 最新交易日分类覆盖

`20260814` 的 439 行与当前 SW2021 分类对账：

| 项目 | 行数 |
|---|---:|
| 当日行情代码 | 439 |
| 命中全部 SW2021 分类代码 | 414 |
| 当前分类 `is_pub=true` | 414 |
| 当前分类 `is_pub=false`，当日无行情 | 97 |
| 当日存在但不在 SW2021 行业分类中的申万指数 | 25 |

因此 439 不是“行业分类应有数量”，也不是异常。服务表保存 439 条源事实；板块雷达行业池必须通过分类表内连接得到 414 条当前发布行业，不能凭代码前缀、名称或固定数量筛选。

### 2.3 字段与空值

正式 `source_fields` 固定显式包含：

```text
ts_code, trade_date, name, open, low, high, close,
change, pct_change, vol, amount, pe, pb, float_mv, total_mv
```

`20260814` 的 439 行中：

- `pe` 空 1 行；
- 其余已核字段无空值。

代表对象 `801010.SI` 的 3,410 行中：

- `pe` 空 2 行；
- `total_mv` 空 4 行；
- 首行 OHLC 完整。

因此身份、日期、名称和 OHLC 为必填；估值、市值以及可能受源端历史口径影响的派生指标允许空值，不能用 0 填充。

### 2.4 源输入参数与运营暴露

| 源参数 | 源端可选 | 正式用途 | 运营是否可填 |
|---|---|---|---|
| `trade_date` | 是 | 每个 resolved open-day unit 唯一业务参数 | 通过平台 point/range 时间意图间接生成 |
| `start_date/end_date` | 是 | 仅源行为审计；正式 connector 请求禁止使用 | 否 |
| `ts_code` | 是 | 仅只读覆盖核验；首版不做单代码补录 | 否 |
| `limit/offset` | 是 | 通用分页器内部生成 | 否 |

运营提交的是单日或区间意图，不是 Tushare 参数；resolver/planner 展开交易日后，`_daily_params` 才生成单个 `trade_date`。宽区间参数不能穿透到源端。

### 2.5 历史覆盖结论边界

当前实测证明接口可分页取得代表代码的 3,410 条历史，也证明早于 2012-08-01 已有部分申万行情；但尚未对所有源代码完成起止日、交易日连续性、重复键和字段空值矩阵审计。

因此：

- LLD 可以冻结请求、字段、主键和存储契约；
- 不能宣称全体 SW2021 已具备统一的 3～5 年完整历史；
- 首次历史回补窗口必须在实施前完成全代码覆盖审计后单独批准。

---

## 3. 三层时间语义

| 语义层 | 固定设计 |
|---|---|
| 时间输入 | `point_or_range`；运营可输入单日或日期区间 |
| 执行/unit | resolver 依据上交所交易日历，把区间展开为每个开市日 1 个 unit |
| freshness/audit | 按 `trade_date` 做 `continuous_open_day` 连续交易日覆盖审计 |

`DatasetDateModel`：

```python
{
    "date_axis": "trade_open_day",
    "bucket_rule": "every_open_day",
    "window_mode": "point_or_range",
    "input_shape": "trade_date_or_start_end",
    "observed_field": "trade_date",
    "audit_applicable": True,
}
```

关键约束：

1. Ops/TaskRun 保存用户选择的 point/range 意图。
2. `DatasetActionResolver` 负责按交易日历归一化为每日 unit。
3. request builder 只接受 unit 的单个 `trade_date`，不得重新发送原始宽区间。
4. 日期区间只生成区间内的开市日 unit；单日输入必须由专用 unit builder 查询交易日历，非开市日以 `planning.trade_date_not_open` 拒绝，不能依赖前端控件或源端空结果兜底。
5. 单次执行最多 60 个交易日 unit；更长历史窗口必须拆成经批准的多个执行请求，不能绕过 `max_units_per_execution`。

### 3.1 当前代码消费者审计

| 消费方 | 本数据集固定结果 | 已核验代码位置 | 实施影响 |
|---|---|---|---|
| Manual Action | point/range 交易日表单，区间上限 60 units | `src/ops/queries/manual_action_query_service.py` | 已由 Definition 派生并通过 API/浏览器正反例 |
| Catalog | 使用 Definition 日期选择规则与 Ops 显式目录 | `src/ops/catalog/dataset_catalog_view_resolver.py`、`src/ops/catalog/dataset_catalog_views.py` | 已固定唯一 `item_order=100` |
| Workflow | 首版不进入 workflow | `src/ops/action_catalog.py` | 不修改 workflow |
| Resolver / planner | point/range 均查交易日历；非开市 point 使用 `trade_date_not_open` | `src/foundation/ingestion/resolver.py`、`src/foundation/ingestion/unit_planner.py` | `build_sw_daily_units` 已以交易日历为权威并通过 60/61 unit 边界 |
| Request builder | 现有 `_daily_params` 只发单个 `trade_date`，语义匹配 | `src/foundation/ingestion/request_builders.py` | 明确复用 `_daily_params`，禁止 `_trade_date_or_start_end_params` |
| Freshness | `CONTINUOUS_OPEN_DAY` | `src/foundation/datasets/freshness_policies.py`、`src/ops/queries/freshness_query_service.py` | 显式映射及 Ops 投影已验收 |
| Dataset card | 无 Raw，只展示 serving/target 表 | `src/ops/dataset_definition_projection.py`、`src/ops/queries/dataset_card_query_service.py` | direct-serving API 回归已验收 |
| Snapshot rebuild | 按 `trade_date` 读取成功业务事实 | `src/ops/services/operations_dataset_status_snapshot_service.py` | 目标模型注册、observed field 与 freshness 投影已验收 |
| Date completeness | `date_bucket` 只验证交易日桶存在 | `src/ops/services/date_completeness_audit_service.py` | 不宣称当前服务能比较行数或代码集合 |
| 自动任务 | 首版不开放 | `src/ops/services/schedule_automation_capability_resolver.py` | `schedule_enabled=False`；到达时间未审计前不建排程 |
| Source release / Probe | 首版不建设 | `src/ops/services/operations_schedule_service.py` | 后续必须独立做 `sw_daily` 到达时间审计 |
| 前端时间控件 | point/range；不提供代码 filter | `frontend/src/pages/ops-v21-task-manual-tab.tsx` | 通用控件消费 selection rule/max units；浏览器已验证且未加 dataset-key 分支 |
| Ops 展示目录 | `board_theme` 第 100 位 | `src/ops/catalog/dataset_catalog_views.py` | 位于分类和成员之后 |
| 数据源页 / 分层 | `raw_table=None`，展示日行情服务表 | `src/ops/schemas/dataset_card.py`、`frontend/src/pages/ops-v21-source-page.tsx`、`frontend/src/pages/ops-v21-dataset-detail-page.tsx` | 不显示伪 Raw |
| Shared storage / writer | 每个 `trade_date` 完整范围原子替换 | `src/foundation/ingestion/writer.py`、`src/foundation/datasets/definitions/_builder.py`、`src/foundation/ingestion/linter.py` | 复用分类 LLD 新增的通用 scope replace |
| 测试与文档 | M4 专项验收已建立 | `tests/test_sw2021_sw_daily_dataset_m4.py`、`tests/web/test_ops_sw2021_sw_daily_m4.py`、前端 smoke | Definition/planner/source/normalizer/writer/freshness/completeness/Ops/浏览器契约均已覆盖 |

---

## 4. 字段端到端设计

| 源字段 | 源文档 | 真实样本 | `source_fields` | Raw ORM/迁移 | Serving ORM/迁移 | Lake | 必填 | 目标与规则 |
|---|---|---|---|---|---|---|---|---|
| `ts_code` | 是 | 是 | 是 | 不适用 | `source_ts_code`、`ts_code` | 不适用 | 是 | 源码保真并生成业务码，主键组成 |
| `trade_date` | 是 | 是 | 是 | 不适用 | `trade_date date` | 不适用 | 是 | 主键和 unit 范围字段 |
| `name` | 是 | 是 | 是 | 不适用 | `name varchar(64)` | 不适用 | 是 | 源指数名称 |
| `open` | 是 | 是 | 是 | 不适用 | `open double precision` | 不适用 | 是 | 开盘点位 |
| `low` | 是 | 是 | 是 | 不适用 | `low double precision` | 不适用 | 是 | 最低点位 |
| `high` | 是 | 是 | 是 | 不适用 | `high double precision` | 不适用 | 是 | 最高点位 |
| `close` | 是 | 是 | 是 | 不适用 | `close double precision` | 不适用 | 是 | 收盘点位 |
| `change` | 是 | 是 | 是 | 不适用 | `change double precision NULL` | 不适用 | 否 | 涨跌点位，不补 0 |
| `pct_change` | 是 | 是 | 是 | 不适用 | `pct_change double precision NULL` | 不适用 | 否 | 涨跌幅，不补 0 |
| `vol` | 是 | 是 | 是 | 不适用 | `vol double precision NULL` | 不适用 | 否 | 源单位万股，非空时不得为负 |
| `amount` | 是 | 是 | 是 | 不适用 | `amount double precision NULL` | 不适用 | 否 | 源单位万元，非空时不得为负 |
| `pe` | 是 | 是，20260814 空 1 行 | 是 | 不适用 | `pe double precision NULL` | 不适用 | 否 | 不补 0 |
| `pb` | 是 | 是 | 是 | 不适用 | `pb double precision NULL` | 不适用 | 否 | 不补 0 |
| `float_mv` | 是 | 是 | 是 | 不适用 | `float_mv double precision NULL` | 不适用 | 否 | 源单位万元，非空时不得为负 |
| `total_mv` | 是 | 是，历史样本可空 | 是 | 不适用 | `total_mv double precision NULL` | 不适用 | 否 | 源单位万元，非空时不得为负 |

系统字段不进入 `source_fields`：`classification_version='SW2021'`、`source='tushare'`、`normalization_rule_version='sw2021-index-code-v1'`、`created_at/updated_at`。Raw ORM、Raw 迁移和 Lake 白名单均为“不适用”。

源单位必须进入字段描述、API 数据字典和测试；首版不在入库时把万股/万元换算成其他单位。

### 4.1 标准化规则

1. 先保存 `source_ts_code`。
2. 统一调用 `src/foundation/datasets/sw_industry_contracts.py` 的代码函数。
3. `850401.SI` 规范为 `850412.SI`；当前真实行情不会触发该映射，但必须有共享正反例。
4. `840401` 或 `840401.SI` 直接拒绝。
5. 标准化后同一 `(ts_code,trade_date)` 若出现多个不同源行，整 unit 失败，禁止最后写入者覆盖。

本表不对分类表建外键，因为源端每天还返回 25 个不属于行业分类的申万综合/风格指数；该差异是已确认的源事实。行业业务池的分类闭包在查询/研究契约中实现。

---

## 5. DatasetDefinition 设计

| 段 | 固定值 |
|---|---|
| identity | `dataset_key=sw_daily`，显示名“申万 SW2021 行业日行情” |
| domain | `board_theme / 板块 / 题材` |
| source | `source_key_default=tushare`，`source_keys=(tushare,)`，`adapter=tushare`，`api_name=sw_daily`，`source_doc_id=tushare.sw_daily`，`request_builder_key=_daily_params`，`base_params={}`，`release_policy=same_day`；无不带日期的维护请求 |
| input_model | 只暴露 point/range 日期；首版不暴露 `ts_code` filter |
| storage | `delivery_mode=core_direct`，`layer_plan=source->serving`，无 Raw/Std；`core_dao_name=sw_industry_daily`，`target_table=serving_table=core_serving.sw_industry_daily`，`write_path=serving_direct_scope_replace`，`raw_conflict_columns=None`，`conflict_columns=(ts_code,trade_date)`，`replacement_scope_fields=(trade_date,)`，`row_identity_filters={}` |
| planning | `universe_policy=no_pool`，无 enum fanout，`pagination_policy=offset_limit`，`page_limit=2000`，`max_source_rows_per_unit=2000`，`unit_builder_key=build_sw_daily_units`，`max_units_per_execution=60`，`fetch_concurrency=1`，`page_processing_mode=buffer_all` |
| normalization | `date_fields=(trade_date,)`，`decimal_fields=(open,low,high,close,change,pct_change,vol,amount,pe,pb,float_mv,total_mv)`，`row_transform_name=normalize_sw2021_daily_row` |
| capabilities | `maintain` 支持 point/range、手动和重试；`schedule_enabled=False` |
| observability | `continuous_open_day`，`observed_field=trade_date` |
| completeness | `scope=date_bucket`，实际字段 `trade_date`；只检查预期开市日是否有事实 |
| transaction | `commit_policy=unit`、`idempotent_write_required=True`；每个交易日约 439 行、通常 1 页，单事务上限按 2,000 行；超过单页时仍合并同日全部页后提交 |

Definition 落点：`src/foundation/datasets/definitions/board_hotspot.py`。Freshness 显式登记：

```python
FRESHNESS_POLICY_BY_DATASET["sw_daily"] = CONTINUOUS_OPEN_DAY
```

`page_limit=2000` 虽高于单日当前 439 行，仍必须显式配置，以避免未来源代码池增长或接口行为变化造成静默截断。

### 5.1 质量策略

```python
"quality": {
    "reject_policy": "fail_unit_on_any_rejection",
    "empty_result_policy": "allow",
    "required_fields": (
        "source_ts_code", "ts_code", "trade_date", "name",
        "open", "low", "high", "close",
        "classification_version", "source",
        "normalization_rule_version",
    ),
    "unit_date_field": "trade_date",
    "duplicate_key_policy": "allow",
    "source_multiplicity_policy": "deduplicate_identical",
    "batch_unique_key_fields": ("ts_code", "trade_date"),
    "pre_write_validator_key": "sw2021_daily_scope",
}
```

额外批次校验：

- `low <= min(open, close) <= max(open, close) <= high`；
- `vol/amount/float_mv/total_mv` 非空时不得为负；
- 返回行的 `trade_date` 必须全部等于 unit 日期；
- 单日源端空结果视为“该日尚未发布”，必须在解析 DAO 和任何 DML 前安全返回 0 行 no-op；不得删除该日既有事实，也不得使整个 TaskRun 失败；
- 空结果 no-op 不代表日期完整：Freshness/Date completeness 仍按 `trade_date` 桶报告该交易日缺失，后续可单日重试；
- 439、414 和 25 是 M0 观测基线，不写成永久数量常量。

M1 已完成 `empty_result_policy/pre_write_validator_key`、`replacement_scope_fields`、`serving_direct_scope_replace` 及对应 builder/linter、plan snapshot、运行时 preflight 和既有 write path 回归。M4 已将本数据集既定单日上限 2,000 写入 Definition，并通过通用 source-client 路径完成 2,000/2,001 行正反例；没有在 `sw_daily` row transform 内叠加局部门禁。

writer 必须先按 `empty_result_policy` 处理空批次：`allow` 返回 0 行 no-op，`fail_unit`/`fail_unit_per_request_variant` 仍抛出 `write.scope_empty`。非空批次再提取唯一 `trade_date` scope tuple，并与 plan unit 的 `trade_date` 相等后才允许 DML。`row_identity_filters` 继续只服务日期完整性身份过滤，不作为替换范围；本数据集没有额外身份维度，因此固定为空。多个日期或 unit/batch 日期不一致均在 DML 前失败。

---

## 6. 表、DAO 与迁移

### 6.1 ORM

- 文件：`src/foundation/models/core_serving/sw_industry_daily.py`
- 类：`SwIndustryDaily`
- 表：`core_serving.sw_industry_daily`
- 主键/冲突键：`(ts_code, trade_date)`
- 索引：
  - `(trade_date, ts_code)`：单日横截面与完整性审计；
  - `(ts_code, trade_date DESC)`：单行业纵向序列。
- 不分区：按约 439 行/日、约 3,400 个交易日估算首版约 150 万行，现阶段普通复合索引足够；是否分区必须以后续实际查询和膨胀数据决定，不能为预期规模提前复杂化。

所有业务数值使用 `double precision` 以保持当前行情模型和计算路径一致，不使用字符串或隐式单位换算。

### 6.2 DAO

复用 `GenericDAO`，在 `DAOFactory` 增加 `sw_industry_daily` 属性；不在 DAO 做分类筛选、排名或技术指标计算。

### 6.3 Alembic

三张申万服务表可由同一个线性迁移创建。迁移只建表、约束和索引，不 seed、不回填、不创建分区、不创建账号或模块专属 GRANT。

M1 开工时，本地仓库唯一 head 为 `20260816_000137`；M1 已生成线性迁移 `20260818_000138`，其 `down_revision` 为 `20260816_000137`。M1 阶段只完成本地生成与测试；M5 于 2026-08-19 重新核验仓库与 Prod head 后执行迁移，当前 Prod 已为 `20260818_000138`。

---

## 7. Ingestion、Ops 与消费者

### 7.1 请求、分页与事务

1. request builder 明确复用当前存在的 `_daily_params`，只从 resolved unit 生成 `trade_date=YYYYMMDD`；由于 input model 不含 `ts_code`，正式请求不会带对象过滤。
2. `build_sw_daily_units` 对 point/range 均查询上交所交易日历；禁止把用户原始 `start_date/end_date` 直接交给 Tushare，范围必须先展开为开市日 unit，单日非开市日直接失败。
3. 每页显式发送 15 个 `source_fields`、`limit=2000`、offset。
4. 每个交易日的全部页先合并、标准化、去重。源端 0 行时直接完成该 unit，读取/保存/拒绝均为 0，不解析目标 DAO、不执行 DELETE/INSERT/read-back，也不使 TaskRun 失败；该日期仍由完整性检查报告为缺失。非空结果中的任意 reject、日期越界、取整后 OHLC 非法、负量额或业务键冲突都在 DML 前使当日 unit 失败。OHLC 只在质量判断时分别使用十进制 `ROUND_HALF_UP` 四舍五入到整数，再校验 `low <= min(open, close) <= max(open, close) <= high`；不设置固定小数差阈值，不使用 Python 银行家舍入，原始小数值必须原样保存。只要取整后的关系合法，即使源值存在小数级交叉也允许发布；取整后仍越界才失败。
5. `serving_direct_scope_replace` 从 normalized batch 提取唯一 `trade_date` 并与当前 unit 对账，只参数化替换该日期范围：同一事务内删除旧日期范围、插入完整新集合、比较源/目标代码键集和内容摘要；失败整体回滚。
6. point/range 重放按日期 scope 幂等；禁止 `TRUNCATE`、无条件 DELETE、跨日期删除或把部分页提前提交。
7. 日期完整性服务只验证日期桶存在；当日行数、代码集合、分类内外分布和内容摘要由 writer read-back 与发布验收报告负责，不得写成现有 completeness 能力。

### 7.2 Ops 派生

| 消费方 | 设计结果 |
|---|---|
| Manual Action | 单日/日期区间控件；不提供代码、版本或分页参数 |
| Catalog | `board_theme` 组，固定 `item_order=100` |
| TaskRun | 每个交易日一个 unit，展示日期、页号、offset、页行数、总行数 |
| Freshness | 按上交所交易日检查 `trade_date` 连续性 |
| Date completeness | 只检查开市日是否至少存在一个 `trade_date` 桶；非交易日不算缺口，不负责行数/代码集合比较 |
| Dataset card | `raw_table=null`，服务表为 `core_serving.sw_industry_daily` |
| Schedule | 首版 `schedule_enabled=False`；本文不确定生产触发时间，也不创建 schedule seed |
| Workflow | 首版不新增；正式自动化需在运行时确认交易日和源端就绪 |

排程启用前必须另做申万源端到达时间审计，给出“空结果安全跳过、缺口可观测、延迟重试、最终失败”规则。不能沿用东财数据集时间或凭产品希望值直接设 cron。

### 7.3 后续业务消费者契约

板块雷达行业行情池必须使用以下关系：

```sql
FROM core_serving.sw_industry_daily AS d
JOIN core_serving.sw_industry_classification AS c
  ON c.src = 'SW2021'
 AND c.index_code = d.ts_code
 AND c.is_pub = TRUE
WHERE d.trade_date = :target_date
```

由此自然排除 25 个非行业分类申万指数和 97 个未发布分类。禁止：

- 按 `8xxxxx.SI` 前缀猜行业；
- 把当日全部 439 行都排成行业榜；
- 用 `source_ts_code` 做跨表关联；
- 用当前 `is_pub` 状态宣称历史日期当时的发布状态。

产品若按当前 SW2021 分类回看历史，必须标注“按当前 SW2021 分类重述历史”。

---

## 8. 历史回补与性能预算

### 8.1 请求量模型

主链每个交易日 1 次请求；当前单日 439 行，小于 2,000 页上限，通常 1 页结束。

示例预算：

| 回补窗口 | 交易日 unit | 最少执行批次（每批最多 60 unit） | 预计请求页 | 预计行数 |
|---|---:|---:|---:|---:|
| 60 日 | 60 | 1 | 60 | 约 26,340 |
| 250 日 | 250 | 5 | 250 | 约 109,750 |
| 750 日 | 750 | 13 | 750 | 约 329,250 |
| 3,410 日 | 3,410 | 57 | 至少 3,410 | 约 150 万，早期单日代码数会变化 |

这些只是按当前单日行数估算，不是执行授权。正式回补前需确认：

1. 所有日期的页数分布和最早有效日期；
2. 预计耗时、Tushare 配额和限流；
3. source fetch concurrency 是否仍固定为 1；
4. 按失败日期幂等重试和 read-back 报告范围；禁止引入 checkpoint/acquire/定点跳过语义；
5. 首次回补窗口及上线所需最小历史长度。

若全历史逐日请求超出配额或发布窗口，必须回到方案评审；禁止偷偷切换为无日期 4,000 行请求或宽区间请求规避计划模型。

### 8.2 发布顺序

1. 先发布分类快照并验收代码映射。
2. 再发布成员全集并验收分类闭包。
3. 先同步 `sw_daily` 最近一个有效交易日，验证 439/414/25 基线和幂等重放。
4. 批准历史窗口后再做按日回补。
5. 数据覆盖通过后，板块雷达才可进入申万回测；页面能力不属于本 LLD。

---

## 9. 测试与验收

### 9.1 正反例

| 约束 | 正向测试 | 反向测试 |
|---|---|---|
| 按交易日主链 | point/range 展开成每日开市 unit，每个请求只带 `trade_date` | 无日期、宽区间直传、非交易日请求被拒绝 |
| 完整字段 | 每页显式请求 15 个字段 | 漏 `trade_date/ts_code/name/OHLC` 或只依赖默认字段时失败 |
| direct-serving | 只解析 serving DAO | Raw DAO、Raw 表、双写或 Lake 路径出现时 linter 失败 |
| 分页 | 单日 short page 正常终止，未来多页能合并 | 以 4,000 默认返回作全集、漏页或页间冲突时失败 |
| 代码标准化 | 850412 保持 850412，源码保真 | 850401 未标准化、840401 或业务键冲突时失败 |
| 日内质量 | 439 行可含 1 个空 pe；原始 OHLC 原样保存，四舍五入取整后关系合法即可发布 | 空值补 0、日期越界、使用固定小数阈值或银行家舍入、取整后 OHLC 仍非法、负量额时失败 |
| 分类消费 | 439 源行经 `is_pub=true` 内连接得到 414 行 | 25 个额外指数进入行业榜、97 个未发布分类进入榜时失败 |
| 幂等 | 同日重放行数、键集和内容摘要稳定 | 重放产生重复、跨日期删除或部分页发布时失败 |
| freshness | 开市日有日期桶、非交易日无缺口 | 开市日整桶缺失却报 Ready，或非交易日误报缺口时失败 |

### 9.2 M1～M4 文件级实施范围

M1～M4 已按以下范围实现；M4 没有扩展到 Prod、Lake、Dagster、Wealth 页面或业务 API：

- `src/foundation/datasets/sw_industry_contracts.py`
- `src/foundation/datasets/definitions/board_hotspot.py`
- `src/foundation/datasets/freshness_policies.py`
- `src/foundation/datasets/models.py`
- `src/foundation/datasets/definitions/_builder.py`
- `src/foundation/models/core_serving/sw_industry_daily.py`
- `src/foundation/dao/factory.py`
- `src/foundation/ingestion/linter.py`
- `src/foundation/ingestion/unit_planner.py`
- `src/foundation/ingestion/row_transforms.py`
- `src/foundation/ingestion/writer.py`
- `src/foundation/ingestion/codebook.py`
- `src/ops/catalog/dataset_catalog_views.py`
- 一条实施日确定 revision 的 Alembic 迁移
- Definition、resolver、request builder/source client、normalizer、writer、freshness、日期完整性、Ops API、数据源卡片和迁移测试

不修改 `src/platform/**`、`src/operations/**`、Lake/Dagster 或 Wealth 页面。

M4 本轮实际新增/修改文件收敛为：

- `src/foundation/datasets/definitions/board_hotspot.py`：声明单日源端 2,000 行上限；
- `src/foundation/ingestion/unit_planner.py`：非开市 point 使用 `trade_date_not_open`；
- `src/foundation/ingestion/codebook.py`：登记上述错误码并升级 codebook 版本；
- `tests/test_sw2021_sw_daily_dataset_m4.py`：完整后端正反例和本地事务验收；
- `tests/web/test_ops_sw2021_sw_daily_m4.py`：Manual Actions、卡片、日期完整性和 60/61 unit API 验收；
- `frontend/e2e/support/smoke-fixtures.ts`、`frontend/e2e/smoke-visual.spec.ts`：浏览器消费真实 point/range、无筛选和任务 payload 契约；
- `tests/test_sw2021_industry_datasets_m1.py`：同步既有共享基座断言与新错误码。

M4 没有修改 ORM、DAO、迁移、共享 writer 算法、调度能力或任何生产数据；这些共享基座由 M1 提供，本轮只通过本数据集专项正反例复核其真实语义。

### 9.3 最小真实发布验收

首次单日发布以 `20260814` 审计快照为对照，必须记录：

```text
source_rows = 439
normalized_rows = 439
rejected_rows = 0
written_rows = 439
target_unique_rows(trade_date=20260814) = 439
duplicate_business_keys = 0
classification_join_rows = 414
non_classification_source_rows = 25
unpublished_classification_rows_in_daily = 0
source_850401_rows = 0
business_850412_rows = 1
business_840401_rows = 0
null_pe_rows = 1
```

随后对同日执行一次幂等重放，read-back 行数、键集和内容摘要必须不变。若实施日源站合法变化，必须记录完整差异并重新解释分类覆盖，不能机械以 439 作为永久门槛。

### 9.4 历史回补验收

每个获批窗口至少输出：

- 计划交易日数、实际成功 unit 数、失败/跳过日期；
- 每日源/标准化/拒绝/写入/目标行数；
- 每日重复键、日期越界、分类内/外代码数；
- 各代码起止日期和交易日覆盖率；
- 关键字段空值率和异常样本；
- 首次 APPLY 后全窗口 read-back；
- 同窗口重放后的幂等摘要。

在该报告通过前，不能把代表代码 3,410 行推广为全体 SW2021 的历史完整性结论。

### 9.5 M4 实际验收记录（2026-08-19）

- Tushare 只读复核：`20260814` 显式 15 字段为 439 行、439 个唯一代码，`pe` 空 1 行；未执行任何源端或 Prod 写入。
- M1～M4 申万专项与三组 Ops API 回归：53 passed；覆盖 2,000/2,001 行、60/61 units、439/414/25 保留、原空结果失败口径、部分 reject、日期越界、OHLC/负量额、同日替换、跨日保护和幂等重放。M5 空结果口径按用户最新拍板另行纠偏，不回写为当时已通过。
- M4 后端专项：7 passed；M4 Web API 专项：6 passed。
- 前端：规则检查、TypeScript typecheck、production build 均通过；Playwright 的 SW2021 Manual Actions 契约 1 passed，已实际切换 point/range，并验证 point 提交只含 `trade_date` 和空 filters。
- 扩展通用 Definition/source/planner/freshness/card/completeness/manual-action 回归为 167 passed、1 failed；唯一失败是未改动的既有 `kpl_list` 卡片 freshness 用例（期望 `fresh`，当前返回 `unconfirmed`），单独复跑仍失败。它不在 M4 调用链或文件范围内，本轮按“不得跑偏”约束未修改该模块，也不把该失败写成 M4 通过项。
- `git diff --check` 通过；CodeGraph 已同步并确认索引 up to date。

M4 验收只证明本地代码契约和事务行为满足 LLD；生产迁移、最小同步、真实目标表 read-back 与幂等重放仍全部属于 M5。

### 9.6 M5 OHLC 生产纠偏（2026-08-19）

- TaskRun `8724` 请求 2026-07-01～2026-08-19 共 36 个交易日；前 15 日已各发布 439 行，共 6,585 行，2026-07-22 在当日 DML 前失败，失败日没有部分写入。
- 生产同源只读复核发现两条同类样本：`801280.SI@20260722` 的 `high=2513.36/close=2513.37`，`801270.SI@20260817` 的 `high=4279.41/close=4279.42`。两条源值直接比较均交叉 `0.01`，但按 `ROUND_HALF_UP` 四舍五入取整后上下界一致。
- 用户最终拍板：不采用 `0.01` 或其他固定小数阈值；OHLC 合法性统一按四个点位各自四舍五入取整后的关系判断，原始值不改写。取整一致的微小交叉接受，取整后仍越界拒绝。
- 本地实现已使用十进制 `ROUND_HALF_UP` 落地该规则；生产样本、无固定阈值样本、上下界取整一致和取整后越界正反例均已通过，SW2021 专项 53 passed，Foundation 最小门禁 157 passed。
- 同期源端复核中 2026-08-19 返回 0 行；它与 OHLC 规则无关。OHLC 纠偏部署后 TaskRun `8732` 已将 2026-07-01～2026-08-18 共 35 个交易日全部发布，每日 439 行；但 2026-08-19 空结果仍被旧 `fail_unit` 契约判为失败。

### 9.7 M5 单日空结果纠偏（2026-08-19）

- TaskRun `8732` 于 14:29 请求 2026-07-01～2026-08-19 共 36 个交易日；前 35 日共读取并保存 15,365 行，最后一个 unit `sw_daily:2026-08-19:35` 因源端 0 行触发 `write.scope_empty`。Prod 只读核验确认 2026-08-18 为 439 行，2026-08-19 为 0 行；同参数源端实测分别返回 439/0 行。
- 用户最终拍板：尚未出数的单个交易日不应报错；请求源端无返回时，不需要也不得写入数据库。
- 实现边界固定为声明式策略：只将 `sw_daily.empty_result_policy` 改为 `allow`；分类快照 `index_classify=fail_unit`、成员快照 `index_member_all=fail_unit_per_request_variant` 保持失败关闭。通用 scope-replace writer 按声明处理空批次，不得按 `dataset_key` 硬编码。
- 空结果 no-op 必须发生在 DAO 解析和任何 DML 前，TaskRun 正常完成；但 `trade_date` 桶仍不存在，Freshness/Date completeness 必须继续报告缺口，禁止把 no-op 伪装成数据已发布。
- 正例：范围中最后一天空结果时，前序日期正常提交、最后一天 0 读取/0 保存/0 拒绝、总任务成功。反例：`fail_unit` 完整快照空结果仍报 `write.scope_empty`；任意 reject、日期错配、非法 OHLC、跨日范围仍失败且不发生目标 DML。
- 本地验收：申万 M1～M4 与三组 Ops API 共 55 passed；Foundation Definition/resolver/runtime/codebook 最小门禁 160 passed；Ruff、`ingestion-lint-definitions` 和 `git diff --check` 均通过。

---

## 10. 硬需求追溯账本

| ID | 硬需求与依据 | 影响层/消费者 | 后端权威约束 | 前端表现 | 实现文件 | 正向测试 | 反向测试 | 真实验证 | 阶段 | 状态 |
|---|---|---|---|---|---|---|---|---|---|---|
| SD-001 | 日期模型使用当前合法枚举 | Definition/Manual Action | `trade_open_day` + `trade_date_or_start_end` | point/range 交易日控件 | Definition、builder | registry/linter 通过 | 旧枚举导致门禁失败 | plan snapshot | M4 | 已完成 |
| SD-002 | point/range 都只生成开市日 unit | planner/request | `build_sw_daily_units` 查交易日历；每请求仅 `trade_date` | 非开市日不可提交 | planner、`_daily_params` | 单日/区间展开正确 | 周末、无日期、宽区间直传失败 | 真实日历计划 | M4 | 已完成 |
| SD-003 | 单次最多 60 个交易日 | planner/Manual Action | `max_units_per_execution=60` | 显示范围限制 | Definition、planner、Ops | 60 units 通过 | 61 units 拒绝 | 60 日 PLAN | M4/M6 | M4 本地/API 边界完成；M6 真实窗口待授权 |
| SD-004 | 无 Raw/Lake/双写 | storage/card | direct-serving scope replace | 卡片展示服务表 | linter、writer、Ops query | 只解析 serving DAO | Raw/双写出现失败 | source/target 对账 | M1/M4/M5 | M1/M4 已完成；待 M5 Prod 对账 |
| SD-005 | 15 个源字段保真 | source/normalizer/ORM | 显式 source_fields | 不适用 | Definition、ORM、迁移 | 全字段 payload/落库 | 漏身份/OHLC 字段失败 | 20260814 样本 | M1/M4/M5 | M1/M4 已完成；待 M5 Prod read-back |
| SD-006 | 源码与业务码分离 | normalization/下游 | 共享 code contracts | 不以源码关联 | contracts、transform、ORM | 850412 保持 | 850401 未归一/840401 失败 | 关键码 read-back | M1/M4/M5 | M1/M4 已完成；待 M5 Prod read-back |
| SD-007 | 保存当日全部源行 | writer/read-back | 不在 Foundation 过滤分类外指数 | 不适用 | writer、ORM | 439 源行全入 | 擅自过滤 25 行失败 | 439/414/25 对账 | M4/M5 | M4 本地 439/414/25 保留完成；待 M5 Prod 对账 |
| SD-008 | 单日空结果安全跳过；任意 reject 不发布；OHLC 按金融四舍五入取整后判断 | Definition/normalizer/writer/completeness | `empty_result_policy=allow`；空批次在任何 DML 前 no-op；非空批次执行 quality preflight；`ROUND_HALF_UP` 只用于判断，源值原样保存 | 空结果任务成功但日期仍显示缺口；其他非法事实结构化失败 | Definition、builder、linter、writer、completeness | 空日 0 读取/0 保存且既有数据不变；nullable 指标允许；取整后关系合法的小数交叉允许发布 | `fail_unit` 数据集空结果仍失败；日期越界、固定小数阈值、银行家舍入、取整后 OHLC/负值非法或部分 reject 回滚 | TaskRun 8732、四段行数与 20260722/20260817 样本对账 | M1/M4/M5 | 本地实现与正反例已完成；待部署和生产重放 |
| SD-009 | 同日精确替换且幂等 | writer/DAO | 限定 `trade_date` scope replace + read-back | 不适用 | writer、DAO | 同日重放摘要一致 | 无 where/跨日期/部分页发布失败 | 两次 APPLY/read-back | M1/M4/M5 | M1/M4 本地事务完成；待 M5 Prod APPLY/read-back |
| SD-010 | 日期完整性只证明桶存在 | completeness/freshness | date_bucket distinct date | 展示日期缺口，不宣称行数完整 | Definition、Ops audit | 开市日桶存在 | 非交易日误报/把部分行当集合验收失败 | 日期审计+独立 key set 报告 | M4/M5 | M4 Definition/API 完成；待 M5 Prod 日期审计 |
| SD-011 | 产品只取当前发布行业 | 后续 Biz 查询 | 与 classification 的 `is_pub=true` 内连接 | 后续雷达展示 | 后续 Biz 实现 | 414 行 | 25+97 进入榜失败 | 查询对账 | 雷达阶段 | 待实施 |
| SD-012 | 首版无自动排程 | schedule/probe | `schedule_enabled=False` | 自动任务不可选 | Definition、Ops | 手动动作可见 | schedule 创建拒绝 | API/浏览器路径 | M4；启用另属 M7 | M4 已完成；自动化仍仅属 M7 |
| SD-013 | 历史覆盖不越权宣称 | 回补报告 | 每批最多 60 日、全代码覆盖后结论 | 不适用 | runbook/验收报告 | 获批窗口完整对账 | 单代码外推/超 60 unit 失败 | 分批 PLAN/APPLY/read-back | M6 | 待实施 |

---

## 11. 三数据集统一开发里程碑与停止条件

三份 LLD 统一使用以下 M0～M7 编号。任何单份文档不得另建一套阶段含义，也不得在前置阶段未通过时提前执行后续生产动作。

| 里程碑 | 目标与交付 | 完成门禁 | 当前状态 |
|---|---|---|---|
| M0 产品与开发门禁 | 两项最终拍板写入三份 LLD；硬需求账本、影响面和实施边界一致 | 文档校验通过；用户明确允许进入 M1 | 已完成 |
| M1 共享基座与迁移准备 | 实现共享代码标准化、质量/预写校验声明、fixed request fan-in、原子 scope replace；新增三表 ORM/DAO/Definition、Ops 目录/freshness 和一条线性迁移 | CodeGraph 列出的消费者均有对应实现与回归；所有既有 writer/source/Definition 路径通过；迁移仅生成和测试，不对 Prod 执行 | 已完成；迁移 `20260818_000138` 已于 2026-08-19 在 Prod 执行并与仓库 head 对齐 |
| M2 分类数据集 | 完成 `index_classify` request、分页、transform、双唯一性、层级闭包、Ops 派生及正反例 | 511 与 31/134/346 等基线可解释；空/错码/孤儿/跨范围替换均阻断；本地或测试库幂等 | 已完成；Prod TaskRun `8714/8717` 发布与幂等重放通过，511 行内容摘要一致 |
| M3 成员数据集 | 完成单 unit 的 Y/N fan-in、分页、标准化、分类三级闭包、原子替换及 Ops 正反例 | Y/N 任一失败目标零变化；7,899 基线、唯一键、日期和闭包可解释；本地或测试库幂等 | 已完成；Prod TaskRun `8718/8719` 发布与幂等重放通过，7,899 行内容摘要一致 |
| M4 日行情数据集 | 完成交易日 point/range unit、15 字段、全源行保留、同日原子替换、freshness/completeness 及 Ops 正反例 | 非交易日、宽区间直传、日期越界、过滤 25 行、跨日删除均阻断；单日本地幂等 | 已完成（2026-08-19）；最终 OHLC 取整口径已完成本地代码与正反例纠偏 |
| M5 生产最小发布 | 经单独授权后重新核验仓库/Prod Alembic head，部署并执行迁移；按分类→成员→一个交易日日行情同步 | 三段 fetched/normalized/rejected/written/target 对账、read-back 和幂等重放全部通过；不包含历史回补 | 进行中；迁移、分类和成员已通过，日行情已发布 2026-07-01～2026-08-18；单日空结果 no-op 已完成本地纠偏，待部署后重放 2026-08-19：源端仍为空时验收任务成功/0 DML，源端已出数时验收 439 行正常发布 |
| M6 历史事实与回补 | 核验成员 `out_date` 边界，审计 `sw_daily` 全代码历史覆盖、配额、耗时与事务预算，提交明确窗口 | 用户批准具体日期范围后才能 PLAN/APPLY；全窗口 read-back 与幂等重放通过 | 未开始 |
| M7 自动化 | 审计三个源接口到达/变化节奏，设计独立 readiness、重试和最终失败规则 | 用户另行批准生产 schedule 的创建与启用；不得把当前 `schedule_enabled=False` 静默改为 true | 未开始 |

板块雷达的申万回测不属于本轮数据集开发；只有 M6 形成可回测日期集合并确认无前视成员谓词后，才进入后续研究阶段。

立即停止条件：

- 实施日仓库与 Prod Alembic head 未对齐；
- 主请求必须依赖无日期或宽区间才能完成；
- 单日返回日期越界、业务键冲突或发生未解释的代码集合突变；
- 出现除已批准规则外的新跨接口错码；
- 需要 Raw/Lake、生产账号、连接、无条件删除、跨日期删除或未评审排程；
- 未完成全代码历史审计却要求启动长期回补或宣称 3～5 年完整。

M5 已按用户授权进入生产发布，迁移、分类和成员已完成，日行情已发布到 2026-08-18；单日空结果 no-op 已完成本地纠偏并等待部署。本轮不授权新增迁移、历史回补、研究物化或排程启用；部署后只重放已批准的 2026-08-19：若源端仍为空，则核验任务成功、0 DML 和日期缺口仍可见；若源端已出数，则按正常单日发布完成 read-back。
