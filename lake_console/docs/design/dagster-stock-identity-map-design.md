# Dagster Stock Identity Map 设计方案

更新时间：2026-05-31

## 1. 背景

`silver_stock_identity_map` 是股票代码身份归一资产，用来回答一个问题：

```text
源数据里出现的 source_ts_code，到底应该归到哪个标准 latest_ts_code？
```

它不是股票曾用名表，也不是分钟线专用临时表。它是基础 silver 资产，供分钟线、复权因子、日线差异审计、历史代码归一等链路只读消费。

历史上该资产是在 `stk_mins` 迁移方案中顺带设计和初始化的，没有独立维护文档。当前需要把它从分钟线方案中抽出来，作为单独基础资产设计和维护。

## 2. 当前代码事实

当前代码中，`silver_stock_identity_map` 已是 active Dagster asset。

已有内容：

| 类型 | 当前事实 |
|---|---|
| 物理路径 helper | `silver/basic/stock_identity_map/part-000.parquet` |
| 字段契约 | `SILVER_STOCK_IDENTITY_MAP_SCHEMA` |
| 初始化来源 | 旧湖 `manifest/security_identity/security_identity_map.parquet`，仅保留为历史 bootstrap 记录 |
| 初始化 helper | `stock_identity_map_bootstrap_spec(...)` / `bootstrap_stock_identity_map_to_silver(...)` |
| 初始化事件 | M3 已补录 runless materialization 与 9 个 blocking check events |
| active asset | `silver_stock_identity_map` |
| active job | `stock_identity_map_update_job` |
| active sensor | `stock_identity_map_sensor`，默认 `STOPPED`，16:30 后评估 |
| seed | `orchestrator/seeds/basic/stock_identity_mappings.cn_a.csv` |

这意味着：

1. 更新 `silver_stock_basic` 和 `silver_namechange` 后，`stock_identity_map_sensor` 会在 16:30 后检查 freshness 与 checks，满足条件才触发 `stock_identity_map_update_job`。
2. 旧湖 manifest 只是历史初始化来源，不是长期运行时依赖。
3. identity map 的日常维护入口已经收敛到 active asset / checks / job / sensor。

## 3. 资产职责

`silver_stock_identity_map` 负责维护代码身份映射，不负责维护名称时间线。

### 3.1 负责的事情

1. 把当前标准代码映射到自身。
2. 把历史源代码、旧代码、北交所旧代码映射到当前标准代码。
3. 记录映射来源、置信度、有效区间和原因。
4. 给下游标准化过程提供唯一 join 口径。
5. 给历史数据差异审计提供解释依据。

### 3.2 不负责的事情

1. 不替代 `silver_namechange` 表达股票名称历史。
2. 不在分钟线 asset 中临时拼装映射规则。
3. 不依赖旧湖 manifest 做日常更新。
4. 不由下游业务 job 顺手重建。
5. 不在消费者里二次补充映射逻辑。

## 4. 字段契约

| 字段 | 类型 | 说明 |
|---|---|---|
| `latest_ts_code` | `VARCHAR` | 标准股票代码，下游 silver/gold 层最终使用的代码 |
| `source_ts_code` | `VARCHAR` | 源代码或历史代码，消费者用它 join identity map |
| `valid_from` | `DATE` | 该映射有效起始日期 |
| `valid_to` | `DATE` | 该映射有效结束日期，可为空 |
| `effective_list_date` | `DATE` | 标准股票上市日期 |
| `effective_delist_date` | `DATE` | 标准股票退市日期，可为空 |
| `identity_source` | `VARCHAR` | 映射来源枚举 |
| `confidence` | `VARCHAR` | 映射置信度枚举 |
| `reason` | `VARCHAR` | 映射原因 |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | 本次 full snapshot 生成时间 |

字段契约必须继续由 `SILVER_STOCK_IDENTITY_MAP_SCHEMA` 维护，并注册到 asset definition metadata。materialization metadata 只记录本次运行观察结果，例如 path、row count、observed columns 和各来源行数统计。

## 5. 来源数据

长期生成 `silver_stock_identity_map` 需要以下来源。

### 5.1 `silver_stock_basic`

用途：生成标准代码自身映射。

规则：

```text
latest_ts_code = stock_basic.ts_code
source_ts_code = stock_basic.ts_code
identity_source = stock_basic
confidence = confirmed
```

维护含义：

1. 新股进入 `silver_stock_basic` 后，应在 identity map 中新增自身映射。
2. 股票生命周期字段来自 `silver_stock_basic.list_date` / `delist_date`。
3. 当前 `silver_stock_basic` 只保留 `list_status='L'` 的当前上市股票，因此 identity map 第一版也应服务当前上市股票主线；如未来需要覆盖退市股票，必须先调整 stock basic 基础事实口径。

### 5.2 BSE / 代码迁移映射

用途：维护确认过的旧代码到新代码映射，尤其是北交所代码切换。

规则：

```text
identity_source = bse_mapping
confidence = confirmed
```

维护要求：

1. 该来源不能靠 `namechange` 猜。
2. 第一版可以用受版本控制的 seed 或单独基础资产承载，但必须有明确字段契约和 review 入口。
3. 生成 identity map 前，BSE 映射中的 `latest_ts_code` 必须能在 `silver_stock_basic` 中找到。

### 5.3 `silver_namechange`

用途：辅助解释少量名称变更导致的历史身份映射。

规则：

```text
identity_source = namechange
confidence = inferred
```

重要边界：

1. 不是每条 `silver_namechange` 都会生成 identity map 行。
2. 普通改名只说明同一股票的名称历史，不等于发生代码身份迁移。
3. 只有当名称时间线能解释某个历史 `source_ts_code -> latest_ts_code` 关系时，才允许生成 inferred 映射。
4. inferred 映射不能覆盖 `stock_basic` 或 `bse_mapping` confirmed 映射。

### 5.4 `stk_mins` 源代码集合

用途：覆盖审计，不作为主生成来源。

维护要求：

1. 从分钟线 raw/silver 或审计报告中提取实际出现过的 `source_ts_code` 集合。
2. 检查这些代码是否都能在 identity map 中找到唯一映射。
3. 缺失样本必须输出到 check metadata 或审计报告，不能由消费者静默跳过。

## 6. 生成模型

`silver_stock_identity_map` 应采用 full snapshot 生成。

原因：

1. 数据规模只有几千行，整表重建成本低。
2. 映射规则依赖多个基础事实，增量补丁容易留下历史污染。
3. 全量重建更容易做唯一性、冲突和覆盖检查。
4. 上游 `silver_stock_basic` / `silver_namechange` 更新后，identity map 的正确结果是“重新合成后的完整事实”，不是局部 append。

目标路径固定：

```text
/Volumes/datasource/data_lake/silver/basic/stock_identity_map/part-000.parquet
```

写入语义：

1. 先写临时文件。
2. 校验行数、字段、主键、枚举和冲突。
3. 校验通过后 `os.replace(...)` 原子替换正式文件。
4. 失败时不得留下半成品。

## 7. 合成优先级

同一个 `source_ts_code` 最终只能映射到一个 `latest_ts_code`。

建议优先级：

1. `stock_basic / confirmed`
2. `bse_mapping / confirmed`
3. `namechange / inferred`

冲突处理：

1. confirmed 与 confirmed 冲突：直接失败。
2. confirmed 与 inferred 冲突：保留 confirmed，inferred 进入冲突样本，check 失败或由设计确认后改规则。
3. inferred 与 inferred 冲突：直接失败，等待人工确认规则或 seed。
4. 任何冲突都不能在消费者侧临时修。
5. 当前 seed 从已验证 identity map 的非自映射行抽取，但只保留 `latest_ts_code` 仍在当前 `silver_stock_basic` 上市股票池中的映射。审计时排除的两条退市主线样本为 `706055.SH -> 600680.SH`、`839680.BJ -> 920680.BJ`；第一版不服务退市股票历史覆盖。

## 8. Checks 设计

### 8.1 Blocking checks

| Check | 目的 |
|---|---|
| `silver_stock_identity_map_file_exists` | 文件必须存在 |
| `silver_stock_identity_map_row_count_positive` | full snapshot 不能为空 |
| `silver_stock_identity_map_schema_matches_contract` | 字段必须等于 `SILVER_STOCK_IDENTITY_MAP_SCHEMA` |
| `silver_stock_identity_map_source_ts_code_present` | `source_ts_code` 必须非空 |
| `silver_stock_identity_map_source_ts_code_unique` | 每个源代码只能出现一次 |
| `silver_stock_identity_map_latest_ts_code_present` | 标准代码必须非空 |
| `silver_stock_identity_map_latest_code_exists_in_stock_basic` | 标准代码必须存在于 `silver_stock_basic` |
| `silver_stock_identity_map_known_identity_source` | `identity_source` 只能是允许枚举 |
| `silver_stock_identity_map_known_confidence` | `confidence` 只能是允许枚举 |
| `silver_stock_identity_map_date_ranges_valid` | `valid_to` 不能早于 `valid_from` |
| `silver_stock_identity_map_conflicting_mapping_absent` | 同一源代码不能映射到多个标准代码 |
| `silver_stock_identity_map_seed_latest_code_explainable` | seed 中的标准代码必须能在 `silver_stock_basic` 当前上市股票池中解释 |

### 8.2 WARN checks / metadata

| 项目 | 目的 |
|---|---|
| 来源分布 | 统计 `stock_basic` / `bse_mapping` / `namechange` 行数 |
| 置信度分布 | 统计 confirmed / inferred 行数 |
| 新增/删除样本 | 观察本次重建相对上一版变化 |
| inferred 样本 | 方便人工复核 namechange 推断映射 |

WARN 只做观测，不阻断；blocking check 才决定下游是否可以消费。

## 9. Job 与触发

`silver_stock_identity_map` 是交易日级基础资产，但物理上仍是 full snapshot。

含义：

1. 它不按 `trade_date` 分区。
2. 每个需要生产股票分钟线的交易日，都必须先确保它已经基于当日最新基础事实重建。
3. 重建动作仍然是整表替换，而不是按日 append。
4. `stk_mins` 只读等待它 ready，不拥有它的更新逻辑。

### 9.1 正式 job

应新增：

```text
stock_identity_map_update_job
```

selection 只包含：

```text
silver_stock_identity_map
silver_stock_identity_map checks
```

禁止：

1. 不顺手更新 `silver_stock_basic`。
2. 不顺手更新 `silver_namechange`。
3. 不触发分钟线。
4. 不读取旧湖 manifest。

### 9.2 触发口径

第一版应新增独立 `stock_identity_map_sensor`，按交易日触发 `stock_identity_map_update_job`。

设计原因：

1. 新股上市会先进入 `silver_stock_basic`。
2. 股票名称事实会进入 `silver_namechange`。
3. `stk_mins` 生产依赖身份映射；如果 identity map 更新不及时，新股或历史代码映射会导致分钟线标准化失败。
4. 因此 identity map 不能只靠人工偶尔更新，也不能塞进分钟线 job 里顺手更新。

触发口径已拍板：

1. 目标交易日读取 `cn_a_stock_trade_days` 的最新已注册交易日，不读取 `cn_a_stock_current_trade_days`。
2. sensor 默认 `STOPPED`，每 10 分钟评估一次。
3. 每天上海时间 16:30 前直接 skip，不检查上游、不提交 run。
4. 16:30 后才检查基础事实 readiness。
5. 该口径与 stock_basic raw/silver 日更 sensors 使用的最新 `cn_a_stock_trade_days` 目标交易日集合一致，也能早于 22:00 后的 `stk_mins` raw 日常更新窗口完成。

触发条件：

1. 当天是已注册的股票交易日，且来自 `cn_a_stock_trade_days`。
2. `silver_stock_basic` 已 materialized，且 blocking checks 全部通过，并满足当天 freshness。
3. `silver_namechange` 已 materialized，且 blocking checks 全部通过，并满足当天 freshness。
4. BSE / namechange inferred 非自映射 seed 文件存在且通过 loader 校验。
5. 当天尚未成功运行过 `stock_identity_map_update_job`，或当前 `silver_stock_identity_map` 的 materialization 时间早于 `silver_stock_basic` / `silver_namechange` 的最新 materialization。

sensor 行为：

1. 满足条件时发出 `stock_identity_map_update_job` 的 `RunRequest`。
2. 不满足条件时返回中文 `SkipReason`，说明是 `stock_basic` 未 ready、`namechange` 未 ready、BSE 映射未 ready，还是当天已完成。
3. sensor 不调用 Tushare，不写 parquet，不读取旧湖 manifest。
4. sensor 不触发分钟线；分钟线由自己的 job/sensor 在 identity map ready 后继续推进。

run key 建议：

```text
stock_identity_map:{trade_date}
```

cursor 只记录观测信息，例如 `evaluated_at`、`target_trade_date`、`stock_basic_ready`、`namechange_ready`、`identity_map_current`。正确性仍以 materialization 和 blocking checks 为准。

## 10. 和 `namechange` 的关系

`silver_namechange` 表达“某只股票在某段时间用什么名称”。

`silver_stock_identity_map` 表达“某个源代码应该归到哪个标准代码”。

它们不是同一张表。

维护动作的区别：

1. 更新 `silver_namechange_update_job` 后，只能说明名称时间线更新了。
2. 若新增名称事实影响历史身份映射，需要重新生成 `silver_stock_identity_map`。
3. 重新生成时，只有符合身份迁移规则的 namechange 结果才进入 identity map。

换句话说：

```text
namechange 更新
  -> 可能影响 identity map
  -> 但不会自动等于 identity map 新增行
```

## 11. 和 `stk_mins` 的关系

`stk_mins` 是重要消费者，但不拥有 identity map。

规则：

1. `silver_stk_mins_*` 只能只读依赖 `silver_stock_identity_map`。
2. 分钟线 asset 里不得直接读旧湖 manifest。
3. 分钟线 asset 里不得自己拼 BSE 或 namechange 映射。
4. 如果 identity map 不 ready，分钟线 silver 应失败或跳过，不能降级使用旧逻辑。

## 12. 历史 bootstrap 退场边界

旧湖 `security_identity_map.parquet` 的定位：

1. 只作为 `silver_stock_identity_map` 初始化来源。
2. 可保留 bootstrap helper 作为迁移审计工具。
3. 不进入日常更新 job。
4. 不作为消费者 fallback。
5. 不作为新增映射的人工编辑入口。

当 active asset 完成并通过历史对账后，可以把旧 bootstrap 从日常维护文档中退场，只保留在 bootstrap legacy 记录中。

## 13. 开发推进计划

### IM-0：现状审计

目标：确认当前旧 manifest、当前 `silver_stock_basic`、当前 `silver_namechange`、BSE 映射来源和分钟线源代码集合之间的差异。

输出：

1. 当前 identity map 行数和来源分布。
2. 从新湖事实重建的候选 identity map。
3. 候选结果与旧 manifest 的差异 CSV。
4. 需要人工确认的 inferred 映射清单。
5. 已完成：当前旧 identity map 非自映射共 `252` 行，其中 `250` 行的 `latest_ts_code` 仍在当前上市股票池中，已进入版本化 seed；`2` 行退市主线不进入第一版 active asset。

### IM-1：BSE 映射来源设计

目标：决定 BSE 映射作为 seed 还是正式基础 asset。

当前结论：第一版使用仓库内版本化 seed，路径为 `lake_console/orchestrator/src/orchestrator/seeds/basic/stock_identity_mappings.cn_a.csv`。

门禁：

1. 必须有版本控制。
2. 必须能审计新增、删除和修改。
3. 必须能被 `stock_identity_map_update_job` 只读消费。

### IM-2：active asset 实现

目标：新增 `silver_stock_identity_map` active asset。

当前状态：已实现。asset 只读 `silver_stock_basic`、`silver_namechange` 和版本化 seed；不读取旧湖 manifest。

要求：

1. 接入 definition column schema。
2. 从新湖基础事实生成 full snapshot。
3. 不读取旧湖 manifest。
4. materialization metadata 记录来源行数、输出行数、差异摘要和 observed columns。

### IM-3：checks 与 job

目标：新增 blocking checks 和 `stock_identity_map_update_job`。

当前状态：已实现。job selection 只包含 `silver_stock_identity_map` 和它自己的 checks。

要求：

1. job 只做 asset selection。
2. checks 覆盖 schema、唯一性、枚举、日期、冲突和 coverage。
3. 不触发下游分钟线。

### IM-4：触发与维护

目标：新增 `stock_identity_map_sensor`。

当前状态：已实现。sensor 使用 `cn_a_stock_trade_days` 最新已注册交易日，16:30 前直接 skip；16:30 后等待 `silver_stock_basic` 与 `silver_namechange` ready，且 identity map stale 时提交 `stock_identity_map_update_job`。

要求：

1. sensor 默认 `STOPPED`。
2. 只在交易日基础事实 ready 后触发 `stock_identity_map_update_job`。
3. 只提交 identity map job，不触发 `stock_basic`、`namechange` 或 `stk_mins`。
4. 目标交易日读取 `cn_a_stock_trade_days`，并且 16:30 后才开始检查 `stock_basic` / `namechange` freshness；不能只看历史上 materialized 过。
5. BSE 映射第一版作为静态 seed，seed 文件存在且校验通过即可视为 ready。

### IM-5：旧 bootstrap 收口

目标：active asset 稳定后，把旧 bootstrap helper 从“维护方式”退回“历史审计记录”。

不删除历史 run/event，不删除已有 parquet，除非另起清理方案并经确认。

## 14. 验收标准

1. `silver_stock_identity_map` 可由新湖基础事实重建，不依赖旧湖 manifest。
2. `source_ts_code` 唯一。
3. `latest_ts_code` 都能在 `silver_stock_basic` 中找到。
4. confirmed 映射不被 inferred 覆盖。
5. 分钟线源代码集合可以被 identity map 解释。
6. `stock_identity_map_update_job` 不更新其它基础资产。
7. `stock_identity_map_sensor` 能在 `cn_a_stock_trade_days` 最新已注册交易日、16:30 后且 `stock_basic` / `namechange` ready 时触发整表重建。
8. 下游只读消费该 asset，不再自行实现映射规则。

## 15. 当前后续事项

1. BSE 映射第一版按静态 seed 维护；后续如需改为 active asset，另起设计。
2. 第一版只服务当前上市股票主线；如需覆盖退市股票历史映射，必须先调整 stock basic 基础事实口径并重做 seed 审计。
3. `namechange` inferred 映射第一版仍由人工确认后写入 seed；不从 `silver_namechange` 自动推断新增映射。
4. 分钟线源代码覆盖审计的正式来源仍需在分钟线 silver 开发前确认；本轮不把分钟线覆盖集合写入 identity map check。
5. `stock_basic` / `namechange` freshness 第一版按 materialization 本地日期不早于 `cn_a_stock_trade_days` 最新目标交易日判断；如后续需要更精确运行日期 tag 或 freshness metadata，另起设计。
