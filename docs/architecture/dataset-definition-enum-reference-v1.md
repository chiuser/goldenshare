# DatasetDefinition 枚举语义参考 v1

- 状态：当前事实参考
- 更新时间：2026-05-16
- 事实来源：`src/foundation/datasets/models.py`、`src/foundation/datasets/definitions/**`、`src/foundation/datasets/freshness_policies.py`
- 目标：统一说明 `DatasetDefinition` 内枚举/准枚举字段的语义边界，避免重复定义、语义交叉或隐藏特例。
- 相关主文档：[数据集日期模型消费指南 v1](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)

说明：本文只维护“枚举语义”和约束边界，不手工维护数据集清单或数量快照。精确数据集归属与数量必须以代码 registry 和测试为准，避免文档事实滞后误导开发。

---

## 1. 使用规则

1. 新增或修改 `DatasetDefinition` 字段取值前，必须先检查本文是否已有对应语义。
2. 如果新增枚举值，必须同步更新本文、相关测试和消费者审计。
3. 不允许把同一语义拆成两个名字，也不允许把两个不同语义塞进同一个名字。
4. 如果实际行为与 Definition 字段不一致，必须视为待收口问题，不能让隐藏逻辑长期存在。
5. 完整数据集清单以 `src/foundation/datasets/registry.py::list_dataset_definitions()` 为准。

---

## 2. 领域与来源

### 2.1 `domain.domain_key`

`domain` 只表达底层数据领域事实，不等于 Ops 页面展示分组。Ops 页面分组必须由 `src/ops/catalog/dataset_catalog_views.py` 控制。

| 值 | 含义 |
| --- | --- |
| `board_theme` | 板块、主题、热榜类数据 |
| `equity_market` | A 股行情、指标、事件类数据 |
| `index_fund` | 指数、ETF、基金行情和主数据 |
| `low_frequency` | 低频事件型数据 |
| `moneyflow` | 资金流相关数据 |
| `news` | 新闻、公告、语料类数据 |
| `reference_data` | 基础主数据、证券主数据、日历等参考数据 |

### 2.2 已退场：`domain.cadence`

`DatasetDomain` 当前只包含 `domain_key/domain_display_name`，不再包含 `cadence` 或 `cadence_display_name`。

历史上的 `cadence` 曾混合表达“更新节奏、freshness 判断、用户展示文案”，现在已经退场。新增数据集不得在 `domain` 中恢复该字段。

---

## 3. Freshness Policy

`freshness_policy` 集中定义在 `src/foundation/datasets/freshness_policies.py`，由 definition builder 注入 `DatasetObservability`。它是 Ops freshness、dataset cards、overview、报表判断所需的显式策略，不写入 `domain`。

| 值 | 含义 |
| --- | --- |
| `continuous_open_day` | 按连续开市交易日判断最新业务日期 |
| `continuous_natural_day` | 按连续自然日判断最新业务日期 |
| `period_bucket` | 按周/月/月份窗口这类周期桶判断最新业务桶 |
| `event_run_trace` | 事件型数据，不要求连续日期；以最近成功维护记录和真实观测值解释状态 |
| `snapshot_run_trace` | 快照/主数据，不要求连续日期；以最近成功维护记录和真实观测值解释状态 |

硬规则：

1. 新增数据集必须在 `FRESHNESS_POLICY_BY_DATASET` 显式登记。
2. 不允许在 Ops、前端、报表中另建 policy 映射副本。
3. `unknown` 只表示技术事实缺失或异常；事件型/快照型未确认维护状态应展示为 `unconfirmed`。

---

## 4. Source 枚举

### 4.1 `source.source_key_default`

| 值 | 含义 |
| --- | --- |
| `tushare` | 默认从 Tushare 获取 |
| `biying` | 默认从 Biying 获取 |

### 4.2 `source.source_keys`

| 值 | 含义 |
| --- | --- |
| `tushare` | 只支持 Tushare |
| `biying` | 只支持 Biying |
| `biying,tushare` | 多来源数据集 |

### 4.3 `source.adapter_key`

| 值 | 含义 |
| --- | --- |
| `tushare` | 使用 Tushare source client |
| `biying` | 使用 Biying source client |

### 4.4 `source.request_builder_key`

`request_builder_key` 是源接口请求参数构造器 selector。每个值必须能在 `src/foundation/ingestion/request_builders.py` 中找到对应实现。

| 规则 | 说明 |
| --- | --- |
| 完整清单来源 | `src/foundation/datasets/definitions/**` 与 `src/foundation/ingestion/request_builders.py` |
| 复用特例 | `irm_qa_sh` 与 `irm_qa_sz` 复用 `_trade_date_or_start_end_params` |

新增 selector 必须同步实现、注册、测试和本文语义说明；不能在 Ops 或前端按数据集 key 拼请求参数。

---

## 5. 日期模型枚举

### 5.1 `date_model.date_axis`

| 值 | 含义 |
| --- | --- |
| `trade_open_day` | 以交易日为日期轴 |
| `natural_day` | 以自然日为日期轴 |
| `month_key` | 以 `YYYYMM` 月份键为日期轴 |
| `month_window` | 以自然月起止窗口为日期轴 |
| `none` | 无业务日期轴 |

### 5.2 `date_model.bucket_rule`

| 值 | 含义 |
| --- | --- |
| `every_open_day` | 每个开市交易日都应有日期桶 |
| `week_last_open_day` | 每周最后一个交易日 |
| `month_last_open_day` | 每月最后一个交易日 |
| `every_natural_day` | 每个自然日 |
| `week_friday` | 自然周五 |
| `month_last_calendar_day` | 自然月最后一天 |
| `every_natural_month` | 每个自然月 |
| `month_window_has_data` | 自然月窗口内有数据即可 |
| `not_applicable` | 不按连续业务日期做 freshness/audit 判断 |

硬规则：

1. `not_applicable` 不是“无日期输入”的同义词。是否支持时间输入必须继续看 `input_shape/window_mode`。
2. 源接口要求自然周五时用 `week_friday`；要求每周最后交易日时用 `week_last_open_day`。
3. 源接口要求自然月末时用 `month_last_calendar_day`；要求每月最后交易日时用 `month_last_open_day`。

### 5.3 `date_model.window_mode`

| 值 | 含义 |
| --- | --- |
| `point` | 单点维护 |
| `range` | 区间或窗口维护 |
| `point_or_range` | 同时支持单点和区间 |
| `none` | 不需要时间输入 |

### 5.4 `date_model.input_shape`

| 值 | 含义 |
| --- | --- |
| `trade_date_or_start_end` | 单日 `trade_date` 或区间 `start_date/end_date` |
| `ann_date_or_start_end` | 公告日期单点或区间 |
| `month_or_range` | 月份键单点或月份区间 |
| `start_end_month_window` | 自然月窗口起止 |
| `none` | 无时间输入 |

### 5.5 `audit_applicable`

| 值 | 含义 |
| --- | --- |
| `True` | 适用日期完整性审计 |
| `False` | 不适用日期完整性审计，必须说明原因 |

---

## 6. 规划与请求拆分

### 6.1 `planning.universe_policy`

| 值 | 含义 |
| --- | --- |
| `pool` | 明确按对象池展开；对象池来源由 `planning.universe` 显式声明 |
| `no_pool` | 明确不按对象池展开源站请求 |
| `none` | 未定义或历史未迁移占位；不能表达具体业务语义 |

说明：`none` 只表示未定义或历史未迁移占位，不能表达“没有对象池展开”。不展开必须写 `no_pool`，展开必须写 `pool` 与 `planning.universe`。

### 6.2 `planning.pagination_policy`

| 值 | 含义 |
| --- | --- |
| `offset_limit` | 使用 `offset/limit` 分页 |
| `none` | 不使用通用分页 |

#### `planning.page_processing_mode`

| 值 | 含义 |
| --- | --- |
| `buffer_all` | 默认行为；完整聚合一个 unit 的分页结果后再归一化和写入 |
| `staged_stream` | 显式 opt-in；逐页归一化并提交非服务暂存，short page 后以 unit 事务发布 serving |

`staged_stream` 不等于分页业务提交。它必须同时满足 Definition linter 的 stage DAO/table、单并发、offset pagination、direct-serving 和 unit transaction 门禁；未声明的数据集继续保持 `buffer_all`。

### 6.3 `planning.enum_fanout_fields`

| 值 | 含义 |
| --- | --- |
| `()` | 不按枚举字段自动扇出 |
| `idx_type` | 按板块类型扇出 |
| `market,hot_type,is_new` | 按东财热榜市场、榜单类型、最新标记组合扇出 |
| `market,is_new` | 按同花顺热榜市场和最新标记扇出 |
| `limit_type,exchange` | 按涨跌停类型和交易所组合扇出 |
| `limit_type,market` | 按同花顺涨跌停类型和市场组合扇出 |
| `src` | 按新闻来源扇出 |
| `report_type` | 按研报类型扇出 |
| `tag` | 按开盘啦榜单标签扇出 |
| `exchange_id` | 按交易所扇出 |
| `content_type` | 按板块类型扇出 |

### 6.4 `planning.unit_builder_key`

| 值 | 含义 |
| --- | --- |
| `generic` | 通用 unit builder |
| 非 generic selector | 数据集专用 unit builder；必须在 `src/foundation/ingestion/unit_planner.py` 注册并测试 |

---

## 7. 存储与写入

### 7.1 `storage.write_path`

| 值 | 含义 |
| --- | --- |
| `raw_core_upsert` | raw 与 core/serving upsert 主路径 |
| `raw_only_upsert` | 只写 raw，serving 通过 view 或轻量层提供 |
| `raw_index_daily_serving_upsert` | 指数日线 raw 全写本次返回、serving active 池门禁写入 |
| `raw_index_period_serving_upsert` | 指数周/月线 raw 全量、serving active 池门禁与日线派生补齐 |
| `raw_std_publish_moneyflow` | Tushare 资金流多源发布 |
| `raw_std_publish_moneyflow_biying` | Biying 资金流多源发布 |
| `raw_std_publish_stock_basic` | 多来源 stock_basic 发布 |
| `raw_core_snapshot_insert_by_trade_date` | 大宗交易按交易日快照插入 |

### 7.2 `storage.delivery_mode`

`delivery_mode` 只表达数据如何交付给服务层，不表达 freshness 或 UI 展示分组。具体值以 `DatasetStorageDefinition` 当前代码为准，新增值必须同步消费者审计。

---

## 8. 能力与事务

### 8.1 `capabilities.action`

| 值 | 含义 |
| --- | --- |
| `maintain` | 数据维护动作 |

### 8.2 `capabilities.supported_time_modes`

| 值 | 含义 |
| --- | --- |
| `none` | 不需要选择时间 |
| `range` | 只支持区间/窗口 |
| `point,range` | 支持单点与区间 |
| `none,point,range` | 同时支持无时间、单点、区间 |

### 8.3 `quality.reject_policy`

| 值 | 含义 |
| --- | --- |
| `record_rejections` | 记录拒绝行，不静默吞掉质量问题 |

### 8.4 `transaction.commit_policy`

| 值 | 含义 |
| --- | --- |
| `unit` | 每个 planned unit 独立提交业务数据事务 |

### 8.5 `transaction.idempotent_write_required`

| 值 | 含义 |
| --- | --- |
| `True` | 写入路径必须满足幂等要求 |
| `False` | 当前 Definition 未显式要求幂等 |

硬规则：无论该字段是否显式为 `True`，业务表写入都不得被 Ops/TaskRun/freshness/schedule 状态写入失败回滚。

---

## 9. 维护检查清单

新增数据集或修改 DatasetDefinition 时，必须逐项确认：

1. `domain_key` 是否已有同义值，不能为了页面分组新造底层领域。
2. `freshness_policy` 是否已在集中映射中登记，不能恢复 `cadence`。
3. `date_axis/bucket_rule/window_mode/input_shape` 是否与日期模型消费指南一致。
4. 所有业务枚举是否写入 `input_model.filters.enum_values`，不能让 Ops 或前端猜。
5. 自动扇出字段是否同时声明在 `enum_fanout_fields` 与 `enum_fanout_defaults`。
6. 对象池语义是否明确表达：不展开用 `universe_policy=no_pool`，展开用 `universe_policy=pool` 与 `planning.universe`，不能藏在 custom builder。
7. `request_builder_key/unit_builder_key/row_transform_name/write_path` 是否已有可复用值。
8. 如果新增 selector 字符串，必须同步实现注册表和测试。
9. 如果状态字段或 Ops 页面需要消费新字段，必须做全量消费者审计，旧口径清零。
