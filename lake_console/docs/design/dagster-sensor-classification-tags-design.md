# Dagster Sensor 分类 Tags 方案

状态：已实施；已接入 sensor definition tags、静态门禁和治理文档。本轮不启停 sensor，不运行 Dagster。

## 1. 背景

当前 Dagster Automation 页面把所有 sensors 展示在同一个 `orchestrator` 分组下。这个分组对应 code location / repository，不是 `defs/sensors` 目录，也不是可由 Python 文件夹直接控制的业务分类。

Dagster 官方 `@sensor` API 支持 `tags`、`metadata`、`owners`。其中 `tags` 是 definition tags，可用于 UI 搜索和过滤。当前本地 Dagster 1.13.6 的 `@sensor`、`@run_status_sensor` 和 `AutomationConditionSensorDefinition` 签名也都支持 `tags`。

因此第一版不拆 code location，而是给 sensor definition 增加低基数分类 tags，让 Automation 页面可以按业务域、目标层级和职责过滤。

官方依据：

- [Dagster schedules and sensors API](https://docs.dagster.io/api/dagster/schedules-sensors)：`@sensor` 的 `tags` 参数用于标注 sensor，并可在 UI 中搜索和过滤。
- [Dagster asset metadata and tags](https://docs.dagster.io/guides/build/assets/metadata-and-tags)：asset tags 用于资产组织和过滤。本方案沿用 asset 的数据域枚举值，但不把 sensor 伪装成 asset。

## 2. 设计原则

1. sensor tags 是 **definition tags**，只描述 sensor 本身，不写入 run records。
2. 不恢复旧的自定义 run tags；`triggered_by`、`asset_family`、`trade_date`、`index_ts_code` 仍然禁止。
3. sensor 分类尽量对齐 asset 的 `DataDomain`：`basic_data`、`quote_data`、`index_topic`、`derived_metric`。
4. sensor 不是 asset，所以不直接复用 `goldenshare/layer`。sensor 可能只注册分区、可能同时写 raw+silver，也可能只是通知；这些都不能硬塞进单一 asset layer。
5. tags 只放低基数、稳定、UI 过滤有价值的信息；日期、分区、成功/失败次数、缺失数量、cursor offset 等动态事实不进入 tags。
6. `platform_observability` 是正式 sensor domain，用于平台运行观测类 sensors；它不是临时口径，也不是业务 asset data domain。

## 3. 第一版字段

### 3.1 `goldenshare/sensor_domain`

说明：sensor 归属的数据域。资产相关 sensor 的取值与 asset `DataDomain` 保持一致。

定义原因：Automation 页面当前混合展示基础资料、股票行情、指数专题、衍生指标和通知类 sensors。只按 sensor 名称过滤不稳定，按数据域过滤最符合当前 asset 组织方式。

枚举：

| value | 中文含义 | 使用原因 |
| --- | --- | --- |
| `basic_data` | 基础数据 | 对齐 asset `DataDomain.BASIC_DATA`；用于交易日历、股票基础信息等基础事实链路。 |
| `quote_data` | 行情数据 | 对齐 asset `DataDomain.QUOTE_DATA`；用于股票日线、停复牌、复权因子等股票行情链路。 |
| `index_topic` | 指数专题 | 对齐 asset `DataDomain.INDEX_TOPIC`；用于指数基础信息、指数日线、主要指数日线链路。 |
| `derived_metric` | 衍生指标 | 对齐 asset `DataDomain.DERIVED_METRIC`；用于市场宽度、涨跌幅分布、对应 serving 同步。 |
| `platform_observability` | 平台观测 | 正式 sensor domain；用于飞书 run status 等平台运行观测类 sensors，避免把通知能力硬塞进业务资产域。 |

暂不定义 `project_config` sensor：当前没有只围绕项目配置资产运行的 sensor。未来若 seed/config 资产变成 active sensor 目标，再单独补充。

`platform_observability` 的边界：

- 它是正式分类，专门承载运行通知、外部告警、运维观测这类不生产 asset 的 sensors。
- 它不对应 asset `DataDomain`，因此不允许反向推导出某个资产族。
- 如果未来新增 Slack、Teams、飞书以外的通知 sensor，也优先归入该 domain，除非它开始生产或修复具体业务资产。

### 3.2 `goldenshare/sensor_target_layer`

说明：sensor 直接影响或触发的目标层级。

定义原因：数据域只能说明“属于哪类业务数据”，不能说明 sensor 是注册分区、写 raw、写 silver、写 gold、同步 serving，还是发送通知。目标层级用于 UI 过滤和运维判断。

枚举：

| value | 中文含义 | 使用原因 |
| --- | --- | --- |
| `partition` | 分区注册 | sensor 只注册 dynamic partitions，不写 asset、不提交数据更新 run。 |
| `raw` | 原始层 | sensor 只触发 raw asset/job，例如指数日线 raw-by-code。 |
| `silver` | 标准层 | sensor 只触发 silver asset/job，例如 `silver_index_daily`。 |
| `raw_silver` | 原始层 + 标准层 | sensor 触发的 job 同时写 raw 和 silver；当前股票基础信息、停复牌、股票日线、复权因子属于此类。 |
| `gold` | 正式层 | sensor 触发或管理 gold 业务结果资产。 |
| `serving` | 服务层 | sensor 触发 ClickHouse serving asset。 |
| `platform` | 平台观测 | sensor 不触发 asset 生产，只做 run 状态通知。 |

### 3.3 `goldenshare/sensor_role`

说明：sensor 的职责类型。

定义原因：Automation 页面同时展示普通 sensor、run status sensor 和 AutomationCondition sensor。职责类型比名称更适合运维过滤。

枚举：

| value | 中文含义 | 使用原因 |
| --- | --- | --- |
| `partition_registration` | 分区注册 | 只维护 dynamic partitions，不触发数据生产。 |
| `asset_update` | 资产更新 | 普通 sensor，满足 readiness 后提交 `RunRequest`。 |
| `automation_condition` | 声明式自动化 | `AutomationConditionSensorDefinition`，由 Dagster automation condition 触发资产生产。 |
| `run_status_notification` | 运行状态通知 | `run_status_sensor` / `run_failure_sensor`，只发外部通知，不提交数据生产 run。 |

## 4. 当前 Sensor 分类表

| Sensor | 文件 | sensor_domain | sensor_target_layer | sensor_role | 分类理由 |
| --- | --- | --- | --- | --- | --- |
| `cn_a_trade_day_sensor` | `defs/sensors/cn_a_trade_day_sensor.py` | `basic_data` | `partition` | `partition_registration` | 基于交易日历注册全量 A 股交易日备份分区；交易日历属于基础数据，不触发资产生产。 |
| `stock_trade_day_sensor` | `defs/sensors/stock_trade_day_sensor.py` | `quote_data` | `partition` | `partition_registration` | 注册股票资产族交易日分区，服务股票行情链路；不触发资产生产。 |
| `stock_current_trade_day_sensor` | `defs/sensors/stock_current_trade_day_sensor.py` | `quote_data` | `partition` | `partition_registration` | 注册复权因子使用的当天股票开市日分区；复权因子属于股票行情数据。 |
| `stock_mins_trade_day_sensor` | `defs/sensors/stock_mins_trade_day_sensor.py` | `quote_data` | `partition` | `partition_registration` | 注册股票分钟线 raw 使用的交易日分区，服务分钟线 raw 链路；不触发资产生产。 |
| `stock_mins_silver_trade_day_sensor` | `defs/sensors/stock_mins_silver_trade_day_sensor.py` | `quote_data` | `partition` | `partition_registration` | 注册股票分钟线 silver 使用的 2014+ 交易日分区，等待 raw、日线、停复牌、身份映射和曾用名 ready；不触发资产生产。 |
| `index_trade_day_sensor` | `defs/sensors/index_trade_day_sensor.py` | `index_topic` | `partition` | `partition_registration` | 注册指数资产族交易日分区；不触发资产生产。 |
| `stock_basic_sensor` | `defs/sensors/stock_basic_sensor.py` | `basic_data` | `raw_silver` | `asset_update` | 触发 `stock_basic_update_job`，该 job 写 `raw_tushare_stock_basic` 和 `silver_stock_basic`。 |
| `suspend_d_sensor` | `defs/sensors/suspend_d_sensor.py` | `quote_data` | `raw_silver` | `asset_update` | 触发停复牌 raw/silver 更新；停复牌位于股票行情数据域。 |
| `stock_daily_sensor` | `defs/sensors/stock_daily_sensor.py` | `quote_data` | `raw_silver` | `asset_update` | 触发股票日线 raw/silver 更新；只读 basic/suspend 门禁。 |
| `stock_adj_factor_sensor` | `defs/sensors/stock_adj_factor_sensor.py` | `quote_data` | `raw_silver` | `asset_update` | 触发复权因子 raw/silver 更新；复权因子属于股票行情数据域。 |
| `stock_mins_silver_sensor` | `defs/sensors/stock_mins_silver_sensor.py` | `quote_data` | `silver` | `asset_update` | 触发股票分钟线 silver 五频度更新；只消费已注册 silver 分区和上游 readiness，不注册分区、不触发 raw。 |
| `index_daily_sensor` | `defs/sensors/index_daily_sensor.py` | `index_topic` | `raw` | `asset_update` | 触发 `index_daily_update_job`，只写指数日线 raw-by-code 和 raw checks，不写 silver。 |
| `silver_index_daily_sensor` | `defs/sensors/silver_index_daily_sensor.py` | `index_topic` | `silver` | `asset_update` | 触发 `silver_index_daily_update_job`，从 raw-by-code 文件集合生成指数日线 silver。 |
| `market_major_indices_daily_sensor` | `defs/sensors/market_major_indices_daily_sensor.py` | `index_topic` | `gold` | `asset_update` | 触发主要指数日线 gold；虽然是 gold 层，但业务域仍是指数专题。 |
| `market_breadth_automation_sensor` | `defs/sensors/market_breadth_automation_sensor.py` | `derived_metric` | `gold` | `automation_condition` | 管理市场宽度 gold 自动触发；资产本身是衍生指标。 |
| `stock_return_distribution_automation_sensor` | `defs/sensors/stock_return_distribution_automation_sensor.py` | `derived_metric` | `gold` | `automation_condition` | 管理股票涨跌幅分布 gold 自动触发；资产本身是衍生指标。 |
| `clickhouse_share_fact_market_breadth_automation_sensor` | `defs/sensors/clickhouse_share_fact_market_breadth_automation_sensor.py` | `derived_metric` | `serving` | `automation_condition` | 管理 ClickHouse 市场宽度 serving 同步；业务域仍来自市场宽度衍生指标，目标层是 serving。 |
| `feishu_run_started_sensor` | `defs/sensors/feishu_run_status_sensor.py` | `platform_observability` | `platform` | `run_status_notification` | 运行启动通知，不对应任何数据资产生产。 |
| `feishu_run_succeeded_sensor` | `defs/sensors/feishu_run_status_sensor.py` | `platform_observability` | `platform` | `run_status_notification` | 运行成功通知，不对应任何数据资产生产。 |
| `feishu_run_failed_sensor` | `defs/sensors/feishu_run_status_sensor.py` | `platform_observability` | `platform` | `run_status_notification` | 运行失败通知，不对应任何数据资产生产。 |

## 5. 落地结果

### S1：契约 helper

- 已新增 `defs/run_contracts/sensor_tags.py`。
- 已定义 `SensorDomain`、`SensorTargetLayer`、`SensorRole` 枚举。
- 已提供 `build_sensor_tags(sensor_domain, target_layer, role)`。
- 已通过静态门禁禁止 sensor 文件手写 tag dict。

### S2：接入 sensors

- 已给所有 `@dg.sensor`、`@dg.run_status_sensor`、`@dg.run_failure_sensor` 和 `AutomationConditionSensorDefinition` 增加 `tags=build_sensor_tags(...)`。
- 未改 `default_status`、`minimum_interval_seconds`、`job_name`、`target`、`cursor`、`RunRequest`、readiness 门禁。
- 未新增 run tags，未新增 run config。

### S3：静态门禁

- 已更新 `test_run_contract_static_gates.py`。
- 已允许 sensor definition 使用 `tags=build_sensor_tags(...)`。
- 继续禁止裸 `tags={`、`run_tags={`、`dg.RunRequest(`、`json.dumps/json.loads` 等旧坏味道。
- 已增加断言：当前所有 sensor 都必须有 `goldenshare/sensor_domain`、`goldenshare/sensor_target_layer`、`goldenshare/sensor_role`。
- 新增或修改 sensor 时，必须同步更新分类表和静态测试；不能只新增 Python sensor definition。

### S4：文档收口

- 已更新 `dagster-run-contract-governance.html`，把 sensor definition tags 纳入治理口径。
- 已更新 `dagster-asset-job-topology.html` 中 sensor 分类描述。
- 不更新历史 run records；definition tags 只在 code location reload 后对 UI 生效。

## 6. 验收方式

只做静态验证，不运行 `dg`、Dagster job、sensor tick、automation evaluation，不读取正式 Dagster instance。

验证项：

- `py_compile` 编译新增 helper 和所有 sensor 文件。
- 单元测试验证 `build_sensor_tags(...)` 只接受登记枚举值。
- 静态测试验证所有 active sensor definition 都带三类 sensor tags。
- 静态测试验证 sensor 文件不手写 `tags={` / `run_tags={`。
- `git diff --check`。
- `python3 scripts/check_docs_integrity.py`。

UI 验收需要 code location reload 后人工查看 Automation 页面，按以下搜索词验证：

```text
goldenshare/sensor_domain:quote_data
goldenshare/sensor_domain:index_topic
goldenshare/sensor_target_layer:partition
goldenshare/sensor_target_layer:gold
goldenshare/sensor_role:run_status_notification
```

如果 Dagster UI 的搜索语法不支持 `key:value` 精确匹配，则退化为搜索 tag value，例如 `quote_data`、`partition_registration`、`run_status_notification`。

## 7. 不采用方案

### 拆多个 code location

不推荐为了 Automation 页面折叠展示而拆成 `stock_orchestrator`、`index_orchestrator` 等多个 code location。这样虽然可能在 UI 上出现多个分组，但会引入部署、资源、Definitions 加载、跨 code location 依赖和 reload 成本；当前收益不足。

### 用 sensor 名称前缀替代 tags

不推荐把 sensor 改名成 `quote_stock_daily_sensor`、`index_index_daily_sensor` 这类前缀命名。当前 sensor 名称已经是长期业务语义；为了 UI 筛选改名会影响历史认知、文档引用和 Dagster instigator 状态。

### 用 run tags 做分类

禁止。run tags 是每次 run 的运行事实或 Dagster 系统事实，不是 sensor definition 的分类工具。恢复自定义 run tags 会破坏前面 run contract 治理成果。

## 8. 风险

1. UI 不一定提供目录式分组；tags 只能解决搜索和过滤，不改变 `orchestrator` 这个 code location 折叠组。
2. `AutomationConditionSensorDefinition` 同时有 `tags` 和 `run_tags` 参数；落地时必须只用 definition `tags`，不得误用 `run_tags`。
3. 如果未来新增 sensor，但没有同步分类 tags，Automation 页面会重新变乱；因此必须配套静态门禁，并已要求写入 `lake_console/orchestrator/AGENTS.md`。
4. 飞书 run status sensors 不属于任何 asset data domain；本方案把 `platform_observability` 定为正式 sensor domain，后续平台观测类 sensors 应延续这个分类。
