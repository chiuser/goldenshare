# 股票历史复权因子修正与 DG 下游修复 LLD v1

<a id="joint-history-repair-lld-20261012"></a>

本次设计采用上位方案 §2 的唯一范围表；不另复制一份股票清单。当前 Prod 和 DG 均需修 25 只/2,489 因子键。DG 日线输入影响 2,495 条，按七价格字段当前比较实际差异 2,489 条/25 只，量额差异 0；分钟目标库存 795,340 根/25 只/七频，60m 首个实际行情日样本 25 只均有差异，完整改写行/文件/指标/事件数仍须候选确认。不能用因子日期数推导行情行数，也不能只看 close 排除 688689。

本轮审计七价格字段按 2026-10-09 基准比较，1e-8 仅用于审计 DOUBLE 噪声，不是新增业务配置或正式写入容差。R0 冻结每股当前正式基准，禁止不经确认把混用基准的序列改为全历史换基准。

Prod 周线接收降为非阻断价格诊断，目标/冻结因子等真门禁保留。有限 Prod 因子维护后可继续周线原批；DG 因子/QFQ 候选可以同时准备，不等待 B0。周线本身继续 Prod → DG，不由此 LLD 计算或修改源周/月价格。


状态：2026-10-12 已完成与 Prod/DG 周线方案的文档对齐；范围与只读审计见上位方案 §2。新增文件、函数、CLI 和专项预算仍为设计，尚未开发、不可执行，正式写入另行授权。

> 2026-10-12 文档纠偏已确认：管理员决定保留当前分钟生成逻辑。§5.4 及相关复用、规划、验收描述已改为七频从规定的 Silver 输入加因子生成，不读取新 Gold 30/60 生成 90/120。冲突历史与 R0 只读库存/性能结果见 §15；本轮不开发、不冻结执行计划、不写正式数据。

上位方案：[修复方案](./dagster-stock-adj-factor-history-repair-plan-v1.md)。本 LLD 设计上位方案中 25 只股票/2,489 个非舍入变化因子键的受控历史修复；取消原 601198.SH 的 451 日纯精度修复，不修改日常自动 repair 的参数、触发条件或字段合同。

## 1. 硬口径及实现映射

| 编号 | 硬口径 | 拟实现点 | 验收 |
| --- | --- | --- | --- |
| H1 | 只修批准股票及不能由精度变化解释的冻结因子键 | scope 校验、因子差异关系 | 其他股/范围外拒绝；全区间差异计数 |
| H2 | Raw 仅批准修正键使用当前 Tushare 原值，其余保留历史采集值；Silver 保持生命周期合同 | factor candidate adapter | 源键/值集合一致，类型和生命周期规则通过 |
| H3 | 保持显式当前基准，不用修正旧日作为 as-of | frozen anchor、source overlay | 基准漂移/历史混用基准拒绝 |
| H4 | 日线连带修正实际后继行的 pre_close | daily impact planner、既有 QFQ SQL | 停牌、多区间、首次行和缺因子反例 |
| H5 | 七频保持现行标准 K 线合同和 Silver 选源，统一调用 canonical QFQ SQL | minute candidate adapter、gold_stk_mins_qfq_source_freq | Gold 1/5/15/30/60/90/120←Silver 1/1/5/5/30/30/60；90/120 不依赖 Gold 30/60；窗口/量额等价 |
| H6 | 递推指标和 state 重放到既有末端 | trend/MACD/KDJ adapters | 分段对完整计算、跨年和末端 state |
| H7 | 九转按既有无价格合同重算 | canonical nine-turn builders | 连续计数超过九、区间外连带变化 |
| H8 | 非本股及范围外行不变 | merge、双向集合差和主键审计 | 多股票、多日期样本；全范围聚合对账 |
| H9 | 候选全链完成后才正式提升 | build/audit/promote 分离 | 候选失败零正式写；中断/恢复/幂等 |
| H10 | 只对账本次修复一次，无日常 reports 依赖 | finish、事件入口分离 | 日常 config/job/sensor 不消费 repair 文件 |
| H11 | 有界内存/批次，源事实和预算漂移即停 | frozen budget、进度和资源门禁 | 最长 1m 样本、超限反例 |
| H12 | 普通自动 repair 不新增人工股票池 | CLI 独立、旧入口回归 | 原 config/sensor payload 合同不变 |
| H13 | 分钟指标起算日从日首计算，上一 expected 日 state 精确存在 | indicator replay planner、既有 continuity 核 | 任意更早 state、漏 expected 日、年初重置均拒绝 |
| H14 | 分别验收七频结果、七频 state、四频分钟九转 | replay scope、candidate audit、formal verify | 停牌沿用 state、跨年、末端及下一日 seed 一致 |

不引入新的价格公式、指标版本、ordinary 公式正确性 check。有限的一次性修复对账不能变成长期 readiness 门禁；重复运行同一公式也不能被表述为独立证明公式正确。

## 2. 代码组织与真实复用边界

拟新增：

```text
defs/bootstrap/stock_adj_factor_history_repair.py
defs/bootstrap/stock_adj_factor_history_repair_candidates.py
defs/bootstrap/stock_adj_factor_history_repair_cli.py
tests/bootstrap/test_stock_adj_factor_history_repair.py
tests/bootstrap/test_stock_adj_factor_history_repair_candidates.py
```

合同数据类和编排放第一个模块；候选适配、合并和本次审计放第二个；CLI 只解析输入与调用。不要新增通用修复框架、asset/job/sensor、业务表或永久 checkpoint 服务。测试路径实施时按现行测试目录校准。

| 当前实现 | 复用方式和限制 |
| --- | --- |
| `assets/adj_factor.py` | 复用列合同、生命周期语义和转换；候选模式不得调用其直接正式 writer |
| `stock_daily_qfq.py::build_stock_daily_qfq_select_sql` | 使用单股源投影和候选因子路径；沿用 previous source row、价格字段规则 |
| `stk_mins_qfq.py::gold_stk_mins_qfq_source_freq` / `build_canonical_gold_stk_mins_qfq_select_sql` | 七频均按统一映射选 Silver 输入，再加候选因子和冻结基准生成单股候选；不传 Gold 30/60 作为 90/120 源 |
| `stock_daily_trend_channel.py::build_stock_daily_trend_channel_repair_segment_sql` | 复用分段计算，单股 source/state 关系；不调用末尾自动提升正式文件的完整 writer |
| `stk_mins_qfq_macd_kdj.py` 的 replacement tables 计算 | 将现有计算抽成同模块公开的候选准备函数，原 writer 和专项共用；禁止复制递推 SQL |
| `qfq_nineturn.py` 两个完整历史 select builder | 单股完整历史输入，输出后过滤目标时间；不得先裁掉早期历史再从零计数 |
| `duckdb_connection.py` | 使用 `connect_configured_duckdb` 并显式传本专项 settings |
| 既有普通 factor repair executor | 不复用入口：它们自动选相邻日变化代码并直接写正式 Lake |
| `qfq_nineturn_history.py::rebuild_qfq_nineturn_scope` | 不直接复用：它会自动正式替换并创建 backup；只使用其共享计算核和已核实的审计语义 |
| `stk_mins_qfq_macd_kdj_history.py` | 不直接使用全市场执行器及其 `14GB` settings |

若现有纯计算函数只接受固定路径，为专项先在 staging 写最小单股输入投影，再传入原 SQL builder。避免为了单股修复修改日常字段合同或新建一个公式实现。共享计算函数提取前做 callers/callees/impact 核验，迁移全部调用方，不保留双轨算法。

## 3. 不可变执行合同

### 3.1 拟定义的数据类

```python
@dataclass(frozen=True)
class FactorRepairScope:
    ts_code: str
    factor_ranges: tuple[tuple[str, str], ...]
    as_of_trade_date: str
    repair_end_trade_date: str

@dataclass(frozen=True)
class FactorRepairPlan:
    run_id: str
    plan_hash: str
    scopes: tuple[FactorRepairScope, ...]
    anchors: tuple[StockFactorAnchor, ...]
    source_fingerprints: tuple[FileIdentity, ...]
    target_preimages: tuple[FileIdentity, ...]
    units: tuple[RepairUnit, ...]
    budget: RepairBudget

@dataclass(frozen=True)
class RepairFileCandidate:
    asset_key: str
    partition_key: str
    target_relative_path: str
    candidate_relative_path: str
    preimage_sha256: str
    candidate_sha256: str
    original_rows: int
    candidate_rows: int
    changed_stock_rows: int
```

`FileIdentity` 包含规范路径、大小、mtime_ns 和 SHA256；同一文件只计算一次强指纹，源码清单也冻结影响公式/schema 的文件哈希。源站返回先按列/类型/主键排序标准化，记录内容哈希；因子值以规范数字字符串记录，比较时使用现有数值类型和显式误差规则，不用格式差异当作修正。

`RepairUnit` 至少包含 phase、asset、freq、年月窗口、输入/输出路径、预计单股行数及状态。`unit_id` 用这些业务范围与 `plan_hash` 生成，不依赖 Dagster event storage id。正式目标集合在完整候选审计后冻结，不允许运行途中增加股票或历史区间。

### 3.2 输入和默认行为

- 股票必须显式输入，本批只允许上位方案表中的 25 只；每只一个 FactorRepairScope，不允许空代码代表全市场。601198.SH、000668.SZ 仅精度变化的历史日期不在本批，输入时拒绝而非自动维护。
- 各股因子范围显式输入，ISO 日期，源请求转换为 YYYYMMDD；范围相同不等于所有日期获准，执行按冻结的精确差异键。
- `as_of_trade_date`、`repair_end_trade_date` 必填，不默认 today；每个资产的有效末端不晚于 end，并记录实际日期。
- Lake/staging 只能使用正式根。staging 的 run 子目录与正式目标均拒绝越界、符号链接和 `..`；确认 `st_dev` 一致再允许提升。
- 未得到写入授权只运行 inspect，输出 stdout，不创建 run 目录、checkpoint 或候选。freeze/build/audit 的临时写入也需在获准执行范围内。
- 因子已一致的文件不重写；全链 no-op 必须在价格、指标及 state 候选与正式数据全部一致后才能确认。若 Raw/Silver 已正确而 Gold 仍旧，仍须通过未复权输入判断下游实际差异，不能仅看因子文件 diff 就判全链 no-op。

### 3.3 参数与资源配置审计

以下均为专项入口的拟定配置，不新增 env、Settings、数据库配置或普通 repair config 字段。CLI 输入与冻结 plan 是唯一来源；预算由 `RepairBudget` 一处定义，运行不得各模块自设默认值。

| 参数 | 提案值/默认 | 来源和持久化 | 所有消费者/生效方式 |
| --- | --- | --- | --- |
| scopes（逐股 ts_code、factor_ranges） | 必填；当前 25 股 | CLI → run plan | source fetch、impact、candidate、audit；同批不可修改 |
| as_of/end | 必填 | CLI → plan | anchor、价格和各指标端点；每步核验 |
| duckdb_memory_limit | 512 MiB | 专项 budget → plan | configured connection；新进程/连接生效 |
| max_rss | 1 GiB | 同上 | 编排采样、每 unit 退出判定；超限不提升 |
| threads | 2 | 同上 | configured connection |
| max_spill | 2 GiB | 同上 | connection；temp 位于 run/temp |
| max_candidate_bytes | 10 GiB | 同上 | 规划、每次 COPY 前后、全链审计 |
| max_stock_batch_rows | 100,000 | 同上 | 单股计算批 planner；超限拆年月/bar 片段 |
| progress_interval | 最长 30 秒 | 专项常量，写入 plan | CLI 阶段/当前频年/已完成量/最后更新时间 |

`512 MiB` 不是现行共享默认：当前 `duckdb_connection.py` 默认为 `16GB`、4 threads；不能调用默认 resource 误用它。也不更改共享默认。`max_stock_batch_rows` 约束计算关系，不能声称全市场保留行也小于十万；全市场文件合并使用向量化流式 COPY，另受 RSS/spill/磁盘预算约束。

审计输出每项 effective value、消费者、源/目标字节、单位进度、RSS/spill 峰值和错误码。参数变化必须新计划，不能在续跑中加大预算。上述新配置在方案评审确认后才能开发。

## 4. R0 规划函数及算法

拟函数：

```text
inspect_stock_factor_repair(scope, readonly_dependencies) -> RepairInspection
fetch_current_factor_rows(scope, tushare) -> ValidatedFactorRows
freeze_stock_factor_repair(inspection, run_root) -> FactorRepairPlan
plan_daily_price_impact(factor_changes, daily_keys, previous_row_keys)
plan_minute_price_impact(factor_changes, minute_keys_by_freq)
plan_indicator_replay(price_impact, existing_asset_endpoints)
```

`fetch_current_factor_rows` 调用 `adj_factor`，显式字段 `ts_code,trade_date,adj_factor`。本批 25 个单股区间，本轮 MCP 实际 25 次/2,489 行；正式执行另加每股基准/边界请求及真实分页；按真实响应分页，不能假设首包就是完整数据。MCP 不暴露分页参数，需核验正式 `TushareResource.call` 的 limit/offset 行为、空结果字段和边界。调用失败和合法空结果分别报错；不从 Prod 文件冒充 Tushare Raw。

冻结前做以下集合核验：

1. 源主键唯一、代码准确、日期落入范围、因子正数且有限；交易日和生命周期符合现行规则。
2. 源与 DG Raw/Silver 双向比较，记录缺行和不同值。缺行不得 silently upsert 当作这次既知修正；新缺口先说明并评审。
3. 用未复权日线和 Gold 现值确认本股完整既有 QFQ 历史基准。`as_of` 与实际 anchor 行分开记录；该股在 as-of 无行情不代表无有效基准。
4. 对同股日线按实际可用记录计算 `lag(trade_date)`。初始影响集是“当日因子变化”的行，加“上一实际日线日期因子变化”的行；可去重。即使 DG 因子已被维护修正，也对批准区间内全部实际日线及其后继行计算候选并比较，识别上游已正确但旧 Gold 未修复的情况。
5. 分钟对批准区间内全部实际股票行情生成候选并比较，避免因子已修正后漏掉旧 QFQ；实际不同的日期才合入正式替换集。七频端点分别确认，Silver 输入频率由 gold_stk_mins_qfq_source_freq 选择。90/120 分别使用 Silver 30/60 的真实 bar 和候选因子，不依赖 Gold 30/60 候选，不按固定根数补缺。
6. 各指标按实际消费字段确定首次变化输入，到其现有完整末端；MACD/KDJ 按 §6.2 从该输入所在日的日首计算。若价格已经被修正，但没有可信的指标同步完成证据，则从批准区间内首个实际输入候选重放，不能依赖当前价格 diff 空集跳过指标。结果/state 输入缺失或 seed 不可信即停止，不用空值从半途初始化。
7. 库存汇总源文件、最大行数、扫描字节、候选字节和可用空间。得到本次精确预计写入行、文件、事件上界后才 freeze。

本轮 25 只/2,489 键只是最新只读审计结果，R0 必须再次确认。仅数字格式或旧值舍入能解释的变化记录为不修改；额外代码/日期、缺行、源漂移或非预期变化必须停止并重新确认，不能自动扩大执行任务。三位舍入是本轮实测分类，不定义源接口永久精度。

## 5. 因子与价格候选

### 5.1 因子

Raw 候选为原全市场日文件按 `ts_code,trade_date` 保留非目标记录，再并入源站目标行；Silver 候选应用相同生命周期过滤和日期类型规则。使用 `RAW_TUSHARE_ADJ_FACTOR_SCHEMA`、`SILVER_ADJ_FACTOR_SCHEMA`，不添加采集信息或修复标记列。

新行即使落在停牌日也保留因子；有因子并不强求行情存在。生命周期或源字段与当前合同冲突则停止，不改身份数据。

### 5.2 候选输入覆盖

`resolve_repair_input(relative_path, manifest)`：若此路径有已通过校验的候选，返回候选；否则返回冻结的正式输入。每个逻辑分区只能出现一次，不把原件和候选同时 UNION ALL 导致重复键。输出路径明确指向 run/candidates，不伪装成正式 Lake resource。

日线 SQL 需要单股输入投影时，按原列合同生成 run/inputs 的 Parquet，再调用现有 builder；源市场宽表只做投影，不在 Python 中遍历大批行情行。

### 5.3 日线

调用现有 SQL，用修正后的交易日和 previous 因子、冻结 anchor，重算 `open/high/low/close/pre_close/change_amount/pct_chg`。`vol/amount` 取未复权源值，保持原单位和现行类型。没有 previous source row 时沿用零值合同；有 previous source row 但无因子时拒绝。

价格不是先四舍五入成两位再计算指标。保留现行 Gold DOUBLE 精度，源端两位行情只用于解释样本。

### 5.4 分钟

七频全部调用 build_canonical_gold_stk_mins_qfq_select_sql，Silver 输入频率由 gold_stk_mins_qfq_source_freq 及 CN_A_GOLD_MINUTE_SOURCE_FREQ_BY_TARGET 决定：Gold 1/5/15/30/60/90/120 分钟对应 Silver 1/1/5/5/30/30/60 分钟。按修正的日因子和冻结 anchor 调整源 OHLC，再沿用唯一 canonical 窗口 SQL 聚合；成交量/额不复权，按原窗口汇总。Silver 保留独立 09:30，Gold 非 1m 将其贡献并入首根而不单独输出；15:00 后源行不进入 Gold。详细窗口与价格顺序以[标准 K 线 LLD §2.4—§2.5](dagster-cn-a-minute-gold-canonical-bars-rebuild-low-level-design.md#24-七频率首根合同)为准。

90/120 从 Silver 30/60 与候选因子直接生成，不读取新 Gold 30/60；因此价格候选之间没有“先完成 Gold 30/60 才能生成 90/120”的依赖。所有分钟指标仍从同频新 Gold 价格候选读取，不读取 Silver 计算指标。无需新增源频率、资产、聚合算法或修改日常/历史/factor repair 的正式入口。

输出年度单股候选，合并原文件本次目标日期外的记录。上游 Silver 只读；分钟价格无需从 2020 连续重算到 2026，本轮目标涉及 2023、2024、2025、2026，按各股真实变化日和既有 bar 冻结；不能套用原 601198 的 2020—2024 年度清单。

## 6. 指标候选和状态传播

### 6.1 趋势通道

使用现有 25/90 EMA 和 hysteresis 计算核。按现行日期链取首次变化输入之前的有效 state 为 seed，后续片段用上一候选片段 state；source/state 关系仅含目标股。沿用现行 segment 上限，按各股首次实际影响及各资产端点规划，不通过长事务物化全市场历史。

每个结果和 state 候选分别与原件比；结果无差但 state 有差仍生成 state 替换。需要沿既有交易日状态分区传播停牌 state，保留 state_source_trade_date、observed_on_partition 及 CNY 生命周期过滤规则；趋势结果仍只有当日实际行情。价格仅 pre_close/change_amount/pct_chg 变化不直接触发此 OHLC 计算核，仍须核验之前未完成的指标更新，不自行修改覆盖语义。

### 6.2 分钟 MACD/KDJ

七频 1/5/15/30/60/90/120 分别规划，结果与 state 均为必验资产；保留 `macd_12_26_9__kdj_9_3_3` 和现行 indicator_version=1。当前计算核消费 high/low/close，并按 target_trade_dates 选择整日 bar，不能传入盘中半天数据后直接沿用前一天 state。首次实际变化 bar 所在日从日首第一根已有 bar 重算，上一 expected 交易日的精确 state 为 seed；前 8 根实际 bar 供 KDJ 的 9 根高低价窗口计算。seed 包含 EMA fast/slow、DEA、K/D、last_trade_time，核对股票、频率、params_key、版本、日期及最后实际输入 bar，不能仅凭文件存在认定可信。

expected dates 来自现行交易日历 helper，与注册分区及物理结果/state 集合做聚合差异核验；不能仅列现存文件，越过中间缺失的 expected 日。上一 expected 日 state 缺失即拒绝，不调用 discover_latest_macd_kdj_state_path_before_trade_date 作更早状态兜底。仅现行合同允许的真实首次初始化能无 seed；已有股票的中途缺 state 不能冒充新股。从当前批准集合识别出额外历史错误时停下重审，不自行向前扩大修复范围。

R0 冻结每股每频的 first_changed_input_time、calculation_start_date、result_end_time、state_end_date、previous_expected_date、seed_last_trade_time、context keys、target expected dates；在 RepairUnit/plan 中保存这些执行事实，不新增普通 asset metadata 合同或永久表。结果终点和 state 终点可以不同：结果只重算既有行情 bar；state 对其既有 expected 日期逐日生成，包括停牌沿用状态，last_trade_time 仍指向最后实际 bar。既有 state 已覆盖更晚停牌日时也须继续传播，不能在最后有行情日提前结束。若末端状态需输入但对应既有价格缺失，拒绝而非补行情。

拟在 `stk_mins_qfq_macd_kdj.py` 提供公开的 `prepare_stk_mins_qfq_macd_kdj_replacement_tables(...)`：复用现有 `_create_macd_kdj_replacement_tables` 计算体，返回 result/state relations，不执行正式 COPY 或 replace。现有 writer 改为调用同一公开计算函数；专项只消费其关系。实施前核验全部调用者和 tests。

按股/频/完整交易日片段计算；年度仅为结果文件合并边界，不是计算重置点。超过单股 100,000 行先在整日边界拆片段，延续上一候选片段 state 和前 8 根实际价格，沿用核内部 1,024 bar segment；R0 核对最大单股单日行数，若实际单日超限先重审 kernel 拆分方案，不把同日切片伪装成整日输入。

现有 _create_macd_kdj_source_tables 会物化传入路径的全部历史 high/low/close；_create_macd_kdj_replacement_tables 的 previous_state 关系没有同股过滤。因此专项必须先用 SQL 投影出本股、本片段及必要 context 的输入和本股精确 seed，再传给共享核。不能把全市场 seed 或整年文件直接传入后声称只计算十万行。context 的日期在当前片段之前，不能同时作为 target 重复递推。后续片段只取候选 seed，不重新加载尚未修正的正式中间 state。

年度 result 文件与全市场日 state 分别合并、分别 checkpoint；多个目标股合并到同一路径一次。末端必须核对五个递推数值、params_key、版本和 last_trade_time，不能只核对页面的 DIF/DEA/K/D；结果未变但 state 不同仍替换 state，停牌 state 保持现行沿用规则。

### 6.3 九转

单股历史规模较小，优先调用两个既有 full-history builders：日线完整历史一次、30/60/90/120 各频完整历史一次。输入早于修正区间的历史仍参与 lag 和连续计数，只有输出的目标时间范围参与正式合并。

若完整单股频率历史超过批次预算，改用 `nineturn_formula.py` 的 context/seed 分段：前 4 根实际 close 用于比较，前段方向和完整连续计数用于 seed；测试证明与完整历史等价。不得把连续计数截到九，或跳过“信号未变但计数变化”的行。

沿用现行无价格 schema；不恢复被清退的价格列或旧公式版本。分钟九转只有 30/60/90/120 四频，不扩到 1/5/15；日线和各分钟频率的结果端点分别冻结。分段 seed 来自上一候选九转结果中的 up_count/down_count，不制造现有资产中不存在的九转 state 文件。统一缩放一段价格时部分信号/计数可以不变，仍需计算核验边界和后续序列；无差异结果跳过写入。

### 6.4 指标计算与写入量分开统计

七频结果、七频 state、四频分钟九转合计 18 个现有分钟资产，加趋势结果/state、日线九转合计 21 个指标资产进入范围核验，不表示每个资产都有实际差异。25 股对应七频 175、四频 100 个组合，实际缺数据不能静默跳过或自行补新的覆盖。

R0 的 replay_inventory 按 asset/ts_code/freq 列出输入字段、首次输入变化、计算起止、现有端点、seed/context 行数、计算行数、state 日期数、原目标文件行/字节数、预计完整候选字节；候选审计再填实际差异行、结果/state 差异文件、保留行、无变化跳过文件和事件映射。795,340 根只是因子区间内七频行情库存，指标重放还包括后续已有行情和前序 context，不能拿它乘一个系数代替审计。最早修正从 2023 年起，本批分钟指标的计算不会默认从 2020 年全历史重跑；若 seed 不可信则先报告，重新评审必要前置范围。

10 GiB 约束是候选文件总量，包括全市场日 state/九转文件的保留行，不能只计 25 股的变化行。空间预检另计 source、inputs 投影、中间片段、候选合并临时输出、checkpoint/audit 和最多 2 GiB spill 的同时存留峰值，乘既定 20%余量；磁盘不足停止，不以压缩变化行数低估完整文件。计数聚合复用输入投影，不对 25 股重复扫描宽全市场文件。

## 7. 合并、校验和无变化跳过

拟函数：`build_scoped_file_candidate`、`audit_repair_candidate_batch`、`audit_repair_chain`。

合并 SQL 结构（字段从正式 ColumnContract 显式生成，不用隐式列顺序）：

```sql
WITH retained AS (
  SELECT <contract columns> FROM original_file
  WHERE NOT (<approved stock AND approved replacement keys>)
), replacement AS (
  SELECT <contract columns> FROM recomputed_rows
  WHERE <approved stock AND approved replacement keys>
)
SELECT <contract columns> FROM retained
UNION ALL
SELECT <contract columns> FROM replacement;
```

替换键来自本次实际存在的目标键集合，不用一个宽日期范围误删无源记录。分区值、主键唯一、schema、NULL/finite 规则、行数和源覆盖先过门禁；保留行做双向 `EXCEPT ALL` 聚合，防止数量相同但值不同。

无变化判定比较全部目标业务列，包括 state，不用 Parquet 字节相同作为行等价的必要条件。整数/日期/代码精确比较；浮点沿用对应既有合同误差用于计算验收，跳过写入原则上要求目标值确实相同，不能以展示精度容差吞掉小幅修正。重复执行相同算法要稳定；NaN/NULL 用显式现行语义。

超过 100 个分区按资产/频率/月窗口聚合复用正式检查规则，只保存错误计数与少量样本。不得逐日运行一组全市场深度 blocking checks。各资产正式 check 的纯校验核若尚未分离，先提取同一语义公共核供候选和原资产使用，不另写一套“近似通过”规则。

全链候选审计必须覆盖因子源集合、价格影响集、指标端点/state、所有保留行、候选 schema 和正式目标清单。价格量额未变化也要列明证据；“指标有多少行真的不同”以此时结果为准。

## 8. 状态、提升、取消和续跑

run 内结构：

```text
plan.json
source/                 # 本批源因子事实，不含令牌
inputs/                 # 必要单股列投影
candidates/<lake-relative-path>
temp/                   # DuckDB spill
checkpoint.json
audit.json
```

`plan`、checkpoint 均原子写入 staging。状态为 `PLANNED → BUILDING → CANDIDATES_READY → PROMOTING → FILES_VERIFIED → CLOSED`，另有 `FAILED/CANCELLED`；只表示本次人工执行，不修改既有 Dagster run 为成功。events 独立记录完成集合，不作为业务事务前提。

正式提升順序：Raw/Silver 因子 → Gold 日线/分钟价格 → 指标结果/state。所有候选完成后才进入 PROMOTING，指标各文件失败不会回滚因子或删除已经提升的文件。

每文件步骤：

1. 检查取消、独占维护状态、plan/source/anchor 未漂移、target preimage 正确。
2. 校验 candidate hash 与候选审计一致；确认候选和正式文件同文件系统。
3. `os.replace(candidate, target)`；读回结构及内容哈希。
4. checkpoint 标记完成，再领取下一个文件。

进程在第 3 步后、第 4 步前退出：续跑若 target hash 等于已冻结 candidate hash，认定该文件已经提升并补 checkpoint；若等于 preimage 且候选仍在，继续提升；否则报 `target_drift` 停止。已完成文件指纹不一致同样停止。不要复制原文件做备份、删除现有表/事件，或借续跑覆盖外部合法修正。

正式输入同时也是本批目标时，提升及续跑的漂移核验接受该路径已冻结的 preimage 或本批已审计 postimage，按实际文件与 checkpoint 判断完成状态；不能在自己提升 Raw/Silver 后仍要求它等于旧输入哈希，误报外部变化。未在本批提升清单内的输入必须保持冻结值，不允许以“已修复”放过其他变动。依赖读取仍经候选覆盖映射，未审计数据不能混入下游计算。

取消在每个源分页、计算片段、COPY 前后、正式文件前后检查；单个长 SQL 若无法在 30 秒内给出单位进度，先拆批或使用可中断子进程执行。状态心跳不冒充业务进度；ETA 未有样本时显示暂无法估算。

独占维护由运营流程执行，本 CLI 不自动关闭服务或修改 sensor。需逐一列出因子、QFQ、趋势、九转、MACD/KDJ 和 serving 发布相关 writer 的活动 run；不能只关闭当前 repair job。构建候选期间允许读正式数据；正式提升期间避免向用户提供混合链版本，跨文件原子性不作承诺。

## 9. 一次性正式对账、事件与 serving

`audit_stock_factor_repair_formal(plan)` 对本次正式目标和保留范围做一次完整聚合对账；读回精确等于候选业务行，核验最新 result/state，可用的源修正样本以及未受影响股票/日期。通过后业务修复完成，不向日常入口添加 checksum/plan/report 依赖。

事件阶段先 `preview`：列出实际修改的 asset/partition、事件消费者、已有事件、需要补录的 materialization/check 数量和近期 readiness 样本。先小样本，后按资产/日期批次补录；只为经过同一 blocking 语义校验的文件报告成功。未变化文件不无意义补录。若现行 readiness 因上游文件版本变化确实需要重新验证，而下游业务行未变，events-preview 应单独列为“仅复验检查、无数据改写”，复用原 check 语义并另行批准，不伪造新的业务 materialization。

年度文件有多个日期分区的资产，事件影响日期按该股实际变化行映射，不能因为年度文件替换就说该年度每天重新 materialize。历史修正 metadata 表明本批人工来源，不伪造原自动 repair 的 `upstream_batch_id`、代码 hash 或成功 run。实施前审核 run-status、asset/event 相关消费者，确保不被误解为普通自动批；有冲突时停止事件阶段，不能随意更改其合同。

现有 Prod publisher 按整个交易日 DELETE/INSERT，不能传单股 rows 调用它。日线九转候选对比后若信号/计数未变，Prod 不需要发布；若有变化，先输出确切日期数和行差异，再单独批准开发和执行 scoped publisher。拟以 `(ts_code,trade_date)` 幂等 upsert，每个有界批事务提交及读回；只更新本股变化的六个业务字段，formula_version/published_at 沿用现行发布合同。不得删全市场日分区或发布未变化行。这一可选阶段不属于当前 DG 正式写入授权。

收尾文档记录数量、资源峰值、通过项和残留限制即可；活动 run 的 JSON/候选在 CLOSED 后不再参与运行，后续清理由明确批准的 staging 清理完成，不由日常程序反复检查历史。

### 9.1 页面读取与恢复日更验收

当前财势乾坤本地分钟 bars 和 MACD/KDJ 是两个接口，StockMinuteQueryService 分别调用 StockMinsLakeReader.read_bars/read_indicators，读取价格年度文件和指标年度文件；页面不会因为价格变了就自动重算指标。StockMinuteNineTurnQueryService 通过 StockNineTurnLakeReader 将价格和四频九转关联读取。分钟 bars/MACD Reader 每次请求新建连接，九转缓存的是 Reader 对象且持有连接，不是已计算业务结果；日线趋势 Reader 也持有连接。因此获准提升后应对原存活 reader 和新请求读取分别取样，核对改价区间、修正区间结束后的指标、跨年和末端，页面已有请求结果须重新获取。不能从文件 os.replace 推断所有消费者已经读到新版本，也不预先新增缓存清除机制或默认重启服务；真实读取不一致时停下诊断。

最后 expected 日的 result/state 按现行覆盖规则通过，并用隔离测试或获准候选计算验证下一交易日从新 seed 续算正确；尚未到来的下一日不能伪造真实行情验收。暂停窗口涉及因子、价格、MACD/KDJ、九转、趋势及其 repair 和 serving writer，包含排队、运行、自动触发者；R0 列出实际 job/sensor 名称和运行状态。事件/readiness 完成后才恢复获准的日更，不改 cursor 越过欠账，不报普通 factor-repair completion 假成功。

研究脚本也直接读取 Gold 分钟历史；此前已导出的研究结果可能使用旧价格，收尾记录所用数据日期与修复范围即可。本专项不擅自重跑研究、发布报告或把这些结果变成日常验收依赖。日线九转当前 Prod serving 仍按 §9 的独立发布边界处理，DG 完成不等于 Prod 副本已更新。

## 10. 拟新增 CLI 和推进清单

以下为接口设计，不是现有可运行命令。模块入口拟为 `orchestrator.defs.bootstrap.stock_adj_factor_history_repair_cli`：

| 命令 | 输入 | 读写边界 |
| --- | --- | --- |
| inspect | ts-code、可重复 factor-range、as-of、end | 只读源/正式 Lake，stdout |
| freeze | 与 inspect 相同，run-root | 核验并完整冻结 staging plan；不写正式 Lake |
| build | plan、expected-plan-hash、phase、sample/full | staging 因子/价格/指标候选和 checkpoint |
| audit | plan、expected-plan-hash | staging 完整候选对账 |
| promote | plan、expected-plan-hash | 明确批准后逐文件正式提升，可原批续跑 |
| verify | plan、expected-plan-hash | 一次正式读回对账；写 run 内结论 |
| events-preview / events-apply | plan、expected-plan-hash | preview 只读；apply 单独批准后写 Dagster 事件 |

inspect/freeze 使用可重复的逐股 scope 输入（股票代码及其日期范围），必须与上位方案 §2 的 25 股表及冻结差异键一致；例如 002713.SZ:2025-12-30:2026-09-22。as-of/end 按股/资产在 R0 核验，不直接复制今天日期。原 601198 三范围不再作为样本或默认输入。命令行不放 token；使用现行 resource 鉴权来源。

开发顺序与方案一致：R0 实测冻结 → R1 因子/价格候选 → R2 指标候选 → R3 小样本中断/续跑与性能 → R4 全链候选/正式提升 → R5 事件及可选 serving 收尾。R1/R2 的实际代码交付需同步原设计的专项边界说明，不把本文提案提前标记已实现。

## 11. 测试与真实验收清单

| 类别 | 必测场景 | 证据要求 |
| --- | --- | --- |
| scope/source | 错代码、区间外行、重复键、截断分页、缺因子、已一致因子但旧 Gold | 明确拒绝/no-op，不能遗漏下游修复 |
| anchor | 历史日期误当 as-of、基准变化、不同历史基准 | 停止；普通 daily/repair 默认不变 |
| 日线 | 停牌跨日后继、多范围交叠、首日、previous 因子缺失 | pre_close/change/pct 正确，vol/amount 不变 |
| 分钟 | 七频 Silver 选源、90/120 直接生成、年度范围外行 | 无 Gold 30/60 候选仍可生成 90/120；不把 Gold 路径当 Silver 输入；09:30/15:00 边界、时间 bucket/量额/行键均符合原核 |
| 指标 | 七频跨年、首次变化位于日中、前 8 根 context、上一 expected 日缺失/更早 state 存在 | 日首起算；精确 seed；禁止更早兜底；分段等价完整单股重放 |
| state | 结果相同 state 不同、连续停牌日、state 末端晚于最后 bar、多股共享文件 | last_trade_time/参数/版本及五个递推值正确，保留其他股 |
| 消费与续算 | 旧连接及新请求读取、bars/指标同时间键、下一日 seed、仅复验事件 | 页面与新文件一致；隔离续算等价；不伪造普通 repair 或未来行情 |
| 九转 | 长连续计数、超过修正区间的影响、无价格 schema | 与完整历史 kernel 等价；不截断到九 |
| 范围保留 | 两股同文件、一股多日期、无变化结果 | 非目标逐字段不变，等价文件不替换 |
| 恢复 | COPY 失败、取消、replace 后 checkpoint 失败、重复续跑、外部改写 | 已完成保留、目标漂移拒绝、幂等 |
| 资源 | 最长 1m 单股片段、宽全市场 state 文件、RSS/spill/磁盘超限 | 保持 budget；超限没有正式提升 |
| 事件/消费 | 未通过 check、错误自动 batch、未变日、普通 sensor payload | 不伪造成功，不扩大发布，不依赖 reports |

真实小样本先选择 002713.SZ 等大变化股及 688689.SH（close 已正确但其他字段/分钟仍旧），覆盖批准区间起止边界、实际后继日线、60m、最高行数 1m 片段及跨年指标 state；先只生成候选。R0 需列出源行/因子差异日/实际行情行/候选行/保留行/拒绝行，拒绝必须解释到 reason code 和样本。

最终验收不声称指标全部改变；分别统计计算行、实际差异行、跳过文件、提升文件和末端 state。正式源/目标对账一次完成，不能以测试通过替代真实行数和预算证据。

## 12. 未解决项和设计限制

1. 25 股/2,489 因子键已完整 MCP 和两边实物核对，无缺行；R0 仍须在执行前重新核验源集合、全部既有序列基准与各资产端点，当前快照不代替冻结。
2. R0 的源文件大小、九转完整文件规模和样本吞吐已见 §15；全链修正候选的实际扫描/写入、累计 RSS/空间及取消续跑仍待验证，不以单核样本放行全量写入。
3. 普通日线 repair 明确禁止人工股票池；独立历史入口属于拟批准的专项能力，不改变旧 config。当前代码尚无此入口。
4. 事件消费者和独占维护窗口需运行时核验；必要的调度操作、正式写入、事件和可选 Prod publisher 均未在本轮执行。
5. CodeGraph `codegraph_explore` 与当前代码读取已用于调用链/消费面审计；计算核提取开发前还须完整 callers/callees/impact 和回归。不存在新增 foundation/ops/biz 依赖或跨产品域调用。

原始依据及源文档链接见上位方案；本文不取代相关资产的正式 schema、普通 check 和日常调度设计。

## 13. 多股范围、代码级对齐及验收补充（2026-10-12）

本节保留 R0 前的范围与开发约束。库存、端点和性能待测状态已由 §15 更新，不把本节历史待办重复当作当前未测事实。

`FactorRepairPlan.scopes` 是批准股票范围的有界 tuple；每股保留 FactorRepairScope 的日期、as_of/end。新增 StockFactorAnchor 仅作为本执行计划内部类型，记录 ts_code、有效 as_of、因子行日期/值和各资产冻结端点；不新增 asset/数据库事实表。25 个 scope 是本批，不改变普通自动 repair 股票池。inspect/freeze 必须校验重复代码、相交日期、范围外键、纯精度变化、缺行及全部单股边界；不解析 run_key 或依赖外部 reports 生成 scope。

只读 R0 先按股核验完整源区间，分类为 identical、precision_only、value_changed、missing_or_unverified。只有批准的 value_changed 精确键能进入 factor candidate，其他键保留。当前三位舍入足以解释精度差异的观察只是审计分类，不推定未来源量化单位，也不新建±0.0005 gate。Prod 和 DG 共享本批源值数值核对，DG 输入来源仍是 TushareResource；不新增 Prod 因子读取 resource 白名单或自动同步链。

按股生成有界因子/价格/递推结果关系，分段时仅当前股/频率/窗口常驻；全市场目标文件先汇总本批所有股票 replacement keys，再统一 retained+replacement 合并一次。跨股同文件不得生成互相覆盖的候选；preimage 和 checkpoint 以目标路径唯一，取消/退出后继续同一冻结批，不追加新股。所有下游候选完成并通过后才提升，先 Raw/Silver 因子、再价格、再指标/state；同链涉及资产失败则维持维护窗口，不能先恢复半链消费者。

本批源 25 次 MCP/2,489 行，正式 SDK 页行为另验；每股范围最多 240 行。日线影响范围 2023-06-01—2026-09-23，分钟价格范围 2023-06-01—2026-09-22，指标端点分别冻结到既有末端，不补新覆盖。单股 100,000 行、512MiB DuckDB/1GiB RSS/2GiB spill/10GiB 累计候选预算沿 §3.3；共享全市场日文件受总 RSS/空间约束。全 25 股候选总字节、指标输入/state 文件数、最大的合并关系、事件数及吞吐未测完，R0 补齐后才能进入全量开发和正式执行；超过预算先设计有完整闭环的有限子批，不提高预算或逐股重复扫宽表绕过。

补充正反测试：601198/000668 纯精度 scope 拒绝且不写；23 只周线价差不限制 25 只因子集合；001331/600016 的两位周价无差异仍有自主价格变化；688689 close 相同而 pre_close/分钟不同必须候选重算；25 股同日文件其他股票不变；所有字段一致的 6 条日线跳过；浮点审计容差不作为生产跳过阈值；完全一致的因子但旧指标/state 仍候选审计。source/anchor/输入版本漂移和预算超限保持拒绝，正式事件/可选 serving 与文件写入分别授权。

验收输出按环境、资产、代码集合分开统计因子键、行情输入行、实际差异行、计算/保留/拒绝行、候选/跳过/提升文件、事件和末端 state。Prod 源行情 21 列完全照收，DG 自主价格比较基于批准 source overlay 和既有公式，不要求这两条链价格逐分相等。一次修复完整对账结束后，日常 job/sensor/check 不引用任何 scope/plan/audit/candidate 文件。本轮只更新文档和只读审计，所有新增函数/CLI/测试仍待实现。


<a id="indicator-repair-audit-20261012"></a>

## 14. 本轮补全与代码审计（2026-10-12，文档完成）

本节记录 R0 前的文档审计，不证明修复已实现；后续实测与本轮已确认的文档纠偏见 §15。范围仍为方案 §2 的 25 股/2,489 因子键；没有新增行情来源、公式、资产、配置或正式写入。

| 审计问题 | 当前代码依据 | 已落回设计的处理 | 尚待验证 |
| --- | --- | --- | --- |
| 只修分钟价格会留下旧指标 | StockMinuteQueryService.read_indicators；catalog 七频结果/七频 state/四频九转 | 方案 §2.3/§3.1、LLD §6 分项纳入 18 个分钟资产 | 逐股逐频起止及实际变化行/文件 |
| “从首次 bar”与日粒度 state 不匹配 | _create_macd_kdj_source_tables 的 target_trade_dates、KDJ_PERIOD=9；assert_exact_previous_state_path | §4/§6.2 日首重算，前 8 根 context，上一 expected 日精确 seed | seed 数值/版本及 expected 日期覆盖 |
| 只到改价最后一天，或只计有行情 state | _create_macd_kdj_replacement_tables 的 ranked/all_state_events；趋势 _build_daily_state_output_sql | §6 各自结果/state 末端，停牌沿用不补 bar；跨年延续 | 全部末端、停牌 state 行数和读回 |
| 按股修复却物化整年历史/全市场 seed | _create_macd_kdj_source_tables 的输入物化与 previous_state_rows | §6.2 单股片段/context/seed SQL 投影；§6.4 完整候选空间 | 最长 1m、最大 state 文件的 RSS/耗时 |
| 自己提升上游后被旧输入哈希误判为漂移 | 原 §8 的输入冻结与逐文件 checkpoint 设计 | §8 区分本批已审计 postimage 与外部变化 | Raw/Silver 提升后取消及恢复反例 |
| 九转不是重算 9 根，也不保证全部变化 | nineturn_formula 的 lag=4/context/seed；qfq_nineturn 四频合同 | §6.3 完整历史或等价分段、连续计数不截断；实际等价跳过 | 100 个组合的计算/变化量及跨片段等价 |
| 修因子不等于更新了所有消费者 | 本地 minutes/indicators/minute-nine-turn API 与 Reader；Prod 日线九转 publisher | §9/§9.1 页面读回、存活连接、下一日续算、可选 serving 分开 | 正式事件消费者、动态 writer 名称/状态、Prod 九转差异 |
| 审计范围与指标实际输入范围容易混用 | 趋势 OHLC、MACD high/low/close、九转 close | §4/§6 按消费者字段选起点；完整修复候选范围冻结后保留其他键 | 日线 pre_close-only 场景和旧指标已滞后场景 |

CodeGraph 本轮使用 codegraph_explore 与 codegraph_impact(_create_macd_kdj_replacement_tables, depth=2)：影响面包含正常分钟 writer/asset、历史 MACD 重建、BSE 递推恢复、repair op，以及 test_stk_mins_qfq_m12_macd_kdj.py 的公式、精确 previous state、 scoped merge 回归。explore 对宽泛名称匹配到了无关 query/reader，未用这些结果推断消费链；改为读取上述确切代码和 catalog/check/API/Reader。共享核提取时必须迁移这些实际调用方，不复用历史直接写入/备份 wrapper。边界、依赖矩阵和普通入口均不变。

现有正式因子与价格规模沿用方案 §2 的本日只读快照，本轮未重跑源抓取、全量指标计算或正式验收。分钟指标的精确重放行数、全市场状态候选空间、运行时 writer/事件消费者及样本吞吐仍需 R0 和候选核验；这些是显式下一阶段项，不能标为已验收。文档整理与静态审计完成后先进行只读 R0，资源门禁通过再开发候选能力，正式数据/事件继续按阶段批准。

<a id="r0-readonly-audit-20261012"></a>

## 15. R0 实物、性能与提交历史审计（2026-10-12）

本节更新 §14 审计之后的事实，不修改正式实现。最终库存时点为 2026-10-12 19:58:19 +08:00，查询期间文件路径集合及 size/mtime 稳定。因子、价格、分钟指标/state/九转、日线指标/state/九转分别核验；临时脚本、只读统计和样本 COPY 仅使用本机临时目录，没有生成正式 staging 修复批。正式 SDK 分页、全链修正候选、完整执行性能及取消/续跑仍未验证。

<a id="r0-source-provenance-20261012"></a>

### 15.1 为什么代码与本次修复文档不同

| 时间与提交 | 实现及文档证据 | 结论 |
| --- | --- | --- |
| 2026-06-05，`1806e031` | 新增 90/120 writer，从 Gold 30/60 年文件读取；同期 HTML M11 写“derived 重建只读 qfq 30/60” | 最初代码与当时方案一致 |
| 2026-08-13，`3ab3b448` | 同一次提交新增标准 K 线 LLD §1.1/§2.4、选源常量、canonical SQL，并改 asset/bootstrap/factor repair 与测试；旧 90/120 LLD 增加历史失效声明 | 后来有明确方案变更，代码、专项 LLD 和测试同步迁移 |
| 2026-08-19，`23b59bb7` | 基础 HTML M11 完成说明改成 Silver 30/60，但 M9E 及其他旧段落仍写 Gold 30/60 | 基础文档只更新部分位置，同一文档存在相互冲突的陈述 |
| 2026-10-12，`b51cd5e6` | 本次新修复 LLD §5.4 又写“90 从新 30、120 从新 60”；该文件 Git 历史从此提交开始 | 本轮修复设计写回了已经失效的关系，上一轮静态审计漏检 |

Git 证据证明设计及代码演变，不据提交作者推测具体是谁复制了旧句，也不把提交本身当作管理员审批记录。没有证据表明 8 月实现偏离当时专项 LLD。

改变的原因是 09:30 集合竞价处理：旧 Gold 30/60 有独立 09:30 行，旧派生算法读取它作为第一根的开盘和量额输入。标准 K 线改为非 1m Gold 不单独输出 09:30，而将它计入首根 bar。继续给原聚合核传新 Gold，就缺少它要求的独立竞价行；当年设计因此改为读取仍保留竞价事实的 Silver，加复权因子后按统一窗口聚合。不能通过补一根 Gold 09:30 或另写聚合算法来绕开现行合同。

当前实际关系如下，管理员已确认本次修复保持该关系：

| Gold 目标频率 | 实际 Silver 输入频率 | 首根输出时间 |
| --- | --- | --- |
| 1m | 1m | 09:30 |
| 5m | 1m | 09:35 |
| 15m | 5m | 09:45 |
| 30m | 5m | 10:00 |
| 60m | 30m | 10:30 |
| 90m | 30m | 11:00 |
| 120m | 60m | 11:30 |

当前依据为[标准 K 线 LLD §2.4](dagster-cn-a-minute-gold-canonical-bars-rebuild-low-level-design.md#24-七频率首根合同)、[选源常量](../../orchestrator/src/orchestrator/defs/run_contracts/cn_a_derived_minute_bars.py)、[共享 QFQ SQL](../../orchestrator/src/orchestrator/defs/stk_mins_qfq.py)、[日常 asset writer](../../orchestrator/src/orchestrator/defs/assets/stk_mins.py)、[factor repair](../../orchestrator/src/orchestrator/defs/stk_mins_qfq_factor_repair.py)及[历史 90/120 writer](../../orchestrator/src/orchestrator/defs/bootstrap/stk_mins_qfq_derived_history.py)。上述路径均按同一 target-to-source 映射读取 Silver，并调用 canonical SQL。现有测试明确断言 90 从 Silver 30、120 从 Silver 60；该测试在 8 月 13 日提交中已存在，本轮只读源码，未重新运行整套测试。

CodeGraph explore 已覆盖 gold_stk_mins_qfq_source_freq 和映射常量，以及日常、历史、repair、readiness 与测试消费者；提交 diff/blame 再核对历史。实现边界、子系统依赖及 API/UI 未变。

R0 溯源完成后，管理员明确确认保留当前分钟生成逻辑，并纠正本方案 §3、本 LLD §5.4 和基础 HTML 的失效描述。本轮已完成这些文档纠偏，保留上表的历史证据；当前执行设计不再依赖新 Gold 30/60 来生成 90/120。不修改正式算法、资产或入口，未进入 R1。

### 15.2 最新源、价格及末端

25 次单股区间 MCP 请求显式取 ts_code/trade_date/adj_factor，返回 2,489 行，集合与批准范围一致；DG Raw/Silver 全部存在、没有重复、两层相等且仍与源不同。另外 25 次基准范围请求返回 10 月 9 日和 12 日共 50 行，各股两个日期的基准值相等，与当前有效基准一致。未重查 Prod DB，Prod 的 25 股/2,489 键仍是方案 §2 之前的实物核验，不宣称本次重验。

日线受输入影响 2,495 行，七价格字段实际不同 2,489 行/25 股、6 行完全相同；OHLC/close 不同 2,463 行/24 股。688689.SH 的 8 根日线 OHLC/close 已正确，6 月 29 日和 7 月 8 日两根的 previous 相关字段需修。将现有日线趋势、state、九转 70 日输出按当前公式重新核验，结果/九转相同；state 原始递推数值最大约 2.13e-14 噪声，没有指标或信号差异，因此不需要重写其日线指标。其因子和分钟仍须修正。

分钟按 §15.1 当前实际映射和 canonical SQL 对全部目标范围比较：175 个股票×频率组合、795,340 行 OHLC 均有差异，Gold 键没有缺失；每个组合首次实际行情日的输入均已变化。成交量差异为零，成交额最大差异 3.73e-9，属于 DOUBLE 聚合噪声，不定义新的业务容差。新价格换回旧因子后与既有 close 的差异最大 5.68e-14，1e-8 审计阈值下零不一致；这仅证明本批既有价格基准，没有将阈值用于候选跳过或正式写入。

指标末端均已存在至 10 月 12 日。较早 19:35 盘点时，当天价格已落地而指标尚到 9 日；之后现行自动 repair 和指标任务正常执行，末端自行追到 12 日。本轮没有触发这些任务，也不能把中间的正常追赶窗口记成历史缺口。各频首次重算日之前的 175 份精确 previous state、各自 8 根实际 context 均存在，版本/参数正确、数值有限、最后时间与 context 相符。24 股趋势 previous seed 同样通过；预期日期注册无缺口。

### 15.3 指标重算量

计算到既有 10 月 12 日末端，不自动向未来扩展覆盖。以下是计算或输出窗口行数，不是最终不同结果行数：

| 分钟频率 | MACD/KDJ 输入根数 | 日 state 行数 | 九转输出窗口行数 |
| --- | ---: | ---: | ---: |
| 1m | 1,164,994 | 4,853 | 不在资产范围 |
| 5m | 232,032 | 4,853 | 不在资产范围 |
| 15m | 77,344 | 4,853 | 不在资产范围 |
| 30m | 38,672 | 4,853 | 38,672 |
| 60m | 19,336 | 4,853 | 19,336 |
| 90m | 14,502 | 4,853 | 14,502 |
| 120m | 9,668 | 4,853 | 9,668 |
| 合计 | 1,556,548 | 33,971 | 82,178 |

每频有 4,834 个有行情的股票日、19 个无行情但需沿用递推 state 的股票日，不补造 bar。MACD 以单股频年组织共 301 个单元，最大单元 58,563 根，另需最多 8 根片段 context；计算关系受 100,000 行预算约束。四频九转若直接复用完整历史核，会实际读取 1,129,038 根历史输入，最大单股频率 24,824 根；不能用 82,178 输出窗口行声称全部计算量。

日线趋势结果 4,764 行、state 4,783 行、九转 4,764 行，24 股合计 14,311 行。日线 state 多出的 19 行与停牌延续一致。最长可用单股日线历史自 2014-01-02，当前日历最多 3,103 日，未要求全市场历史指标重算。逐股起算日与数量见 §15.7，因子范围仍以方案 §2 唯一范围表为准。

### 15.4 完整文件空间

全市场日文件需保留非本批股票的记录，因此空间和合并行数必须看完整文件。以下文件集合已去重；实际相同文件可在候选审计后跳过，不能提前宣称全数需要提升。

| 类型 | 目标文件上界 | 完整文件现有行数 | 当前压缩字节 |
| --- | ---: | ---: | ---: |
| Raw/Silver 因子两份 | 702 | 3,820,295 | 37,131,287 |
| 日线 QFQ 价格 | 354 | 1,916,858 | 123,604,742 |
| 七频分钟 QFQ 价格 | 266 | 2,498,720 | 51,146,894 |
| 七频 MACD/KDJ 结果 | 301 | 2,851,632 | 154,774,711 |
| 七频 MACD/KDJ state | 5,691 | 30,482,487 | 1,365,378,609 |
| 四频分钟九转 | 3,252 | 73,906,429 | 99,414,786 |
| 日线趋势结果 | 813 | 4,347,702 | 254,584,410 |
| 日线趋势 state | 813 | 4,353,716 | 164,075,976 |
| 日线九转 | 813 | 4,347,702 | 25,569,926 |
| 合计 | 13,005 | 128,525,541 | 2,275,681,341 |

按现有压缩大小估计候选约 2.12 GiB，不是实际修正候选大小；完整候选必须实测，不改变 10 GiB 候选和 2 GiB spill 上限。最大目标文件为 600016.SH 的 2025 年 1m MACD，3,168,372 字节。正式 Lake 与 staging 设备号均为 16777244，可用 2,928,782,848,000 字节。磁盘仍需预留 inputs、候选、spill 和 20% 余量，空间充足不代表 CPU/RSS 或完整候选已通过。

分钟源输入是 351 日的四种 Silver 频率，共 1,404 个文件、约 8.48 GB 压缩大小；这是涉及文件大小，不是硬盘真实读取量，不能忽略列裁剪与缓存。同一宽文件统一投影本批股票并复用，不能逐股重复扫描。状态文件占候选估计的大头，同日文件合并全部批准股票后仅生成一次候选。

### 15.5 性能实测与未通过项

所有连接显式 512 MiB DuckDB、2 threads，审计禁 spill/扩展自动安装；样本 COPY 写本机临时目录。下列为真实只读或临时输出测试，不是正式修复任务性能：

| 测量 | 规模 | 耗时 / RSS |
| --- | --- | --- |
| 全目标分钟价格比较 | 795,340 行，七频 | 16.143 秒，峰值 820.72 MiB |
| 单股全年 1m MACD 核 | 58,563 根 + context，243 日 | 0.416 秒；临时结果 COPY/比较约 0.020 秒 |
| 分钟九转完整历史核 | 24,824 根 | 0.020 秒 |
| 日线趋势有界核 | 24 股、64 日、1,518 根 | 0.010 秒 |
| 共享完整文件 COPY | state 5,587 行、九转 44,488 行、趋势 state 5,573 行 | 分别约 0.0024、0.0054、0.0019 秒 |
| 上述核与 COPY 样本进程 | 当前输入，不是全链修正候选 | 峰值 337.11 MiB |
| 全七频库存共用一个进程 | 完整目标文件元数据及状态关系 | 10.65 秒，峰值约 1,072.72 MiB，超过 1 GiB |
| 各频单独新进程盘点 | 七个独立频率探针 | 每个约 0.47—0.74 秒，峰值约 161—188 MiB，均通过 |

单进程连续盘点的 RSS 超预算是真实未通过项。DuckDB 连接释放不能据此推断进程累计内存一定释放；按频率新进程的实测支持上位方案 §5 已列出的子进程拆分方向。后续须验证编排进程不保留明细/全部 footer，新进程按阶段或频率退出，写入 checkpoint 后释放；这属于待落实的性能设计，不能提高预算、仅调用 GC，或拿单核样本通过代替全流程验收。

长递推已可在单股年度预算内计算，主要剩余成本是 13,005 文件的保留行合并、校验、fsync/hash 和恢复记录。没有测完整新因子→新价格→指标候选，因此不给出未经验证的全量完成时间。后续 R3 必须测全过程峰值、累计候选、spill、实际扫描和取消/续跑。

checkpoint 的内部存储结构也需在开发前明确：以约 1.2 万个路径的模拟完成列表估算，最终约 1 MB；如果每完成一个文件都重写增长的完整列表，累计约 6 GB，尚不含哈希/状态。这是格式成本模拟，不是已实现 writer 的实测结果或本批精确文件数。建议沿用逐文件 checkpoint 的语义，使用有界的单文件完成记录和小汇总，避免二次增长；具体格式待设计确认，不新增永久台账或 reports 依赖。

### 15.6 事件、并发与剩余验收

当前 catalog 涉及 31 个资产：2 因子、1 日线价格、7 分钟价格、21 指标。按全部可能变化的逻辑日期预览，materialization 上界 20,586、blocking check 上界 41,907，合计 62,493；实际无变化结果可能跳过，正式补录只按核验后的变更分区。年度文件替换不是每一天全都有业务变化。

当前分钟 MACD 日常 run-status sensor 监听 stock_mins_qfq_daily_update_job、stock_mins_qfq_factor_repair_job 的 SUCCESS run；指标 repair 还监听 MACD 日常 SUCCESS。runless materialization 不等于一个 SUCCESS run，不会替代这些触发条件。分钟/日线九转另有按实物 readiness 的有界 sensor，不能只维护一条事件链。19:44 只读 instance 快照见到正常 factor repair 运行、相关 sensor RUNNING，之后价格/指标末端已追齐 12 日；本轮未停止或触发它们。正式冻结前须再次列出活动/排队 writer，另获批准后暂停、排空并独占执行。

分钟选源的文档纠偏已确认。后续仍需：正式 SDK 分页/边界实测；完整修正候选及逐行/逐字段等价；实际不同指标/state/file 数；共享合并与子进程全链预算；checkpoint 具体格式与中断续跑；候选后的事件精确预览；存活 Reader/页面/下一日续算验证；可选 Prod 日线九转 serving 的差异与独立授权。本轮未开发、未写正式数据，不宣称这些门禁完成。

### 15.7 逐股指标重算起点与数量

以下数量截至既有 2026-10-12；分钟列合计七频 MACD 和 state、四频九转输出窗口。日线三列分别为趋势结果/state/九转；“不重写”只适用于 688689 的日线指标。首次因子变化与首次实际行情可能不同，不能把停牌日期当价格缺口。

| 股票 | 分钟起算日 | 日线指标起算日 | 分钟 MACD 输入 | 分钟 state | 分钟九转窗口 | 日趋势 | 日 state | 日九转 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 000430.SZ | 2025-12-29 | 2025-12-29 | 59,570 | 1,309 | 3,145 | 185 | 187 | 185 |
| 000615.SZ | 2025-12-29 | 2025-12-29 | 60,214 | 1,309 | 3,179 | 187 | 187 | 187 |
| 000691.SZ | 2026-01-05 | 2026-01-05 | 58,926 | 1,288 | 3,111 | 183 | 184 | 183 |
| 000697.SZ | 2025-11-28 | 2025-11-28 | 66,332 | 1,456 | 3,502 | 206 | 208 | 206 |
| 000793.SZ | 2026-06-22 | 2026-06-22 | 23,828 | 525 | 1,258 | 74 | 75 | 74 |
| 000908.SZ | 2026-03-11 | 2026-03-11 | 45,402 | 1,001 | 2,397 | 141 | 143 | 141 |
| 001331.SZ | 2026-06-29 | 2026-06-29 | 22,540 | 490 | 1,190 | 70 | 70 | 70 |
| 002012.SZ | 2026-07-06 | 2026-07-06 | 20,930 | 455 | 1,105 | 65 | 65 | 65 |
| 002117.SZ | 2024-06-25 | 2024-06-25 | 179,032 | 3,892 | 9,452 | 556 | 556 | 556 |
| 002200.SZ | 2025-12-12 | 2025-12-12 | 63,434 | 1,386 | 3,349 | 197 | 198 | 197 |
| 002713.SZ | 2025-12-30 | 2025-12-30 | 59,570 | 1,302 | 3,145 | 185 | 186 | 185 |
| 002742.SZ | 2025-12-10 | 2025-12-10 | 64,078 | 1,400 | 3,383 | 199 | 200 | 199 |
| 002822.SZ | 2025-12-30 | 2025-12-30 | 59,570 | 1,302 | 3,145 | 185 | 186 | 185 |
| 300091.SZ | 2026-02-12 | 2026-02-12 | 50,232 | 1,092 | 2,652 | 156 | 156 | 156 |
| 300093.SZ | 2025-11-20 | 2025-11-20 | 68,586 | 1,498 | 3,621 | 213 | 214 | 213 |
| 300125.SZ | 2025-12-29 | 2025-12-29 | 59,892 | 1,309 | 3,162 | 186 | 187 | 186 |
| 300159.SZ | 2025-12-24 | 2025-12-24 | 60,858 | 1,330 | 3,213 | 189 | 190 | 189 |
| 300176.SZ | 2026-08-21 | 2026-08-21 | 9,982 | 217 | 527 | 31 | 31 | 31 |
| 300506.SZ | 2025-12-22 | 2025-12-22 | 61,180 | 1,344 | 3,230 | 190 | 192 | 190 |
| 600016.SH | 2023-06-01 | 2023-06-01 | 261,786 | 5,691 | 13,821 | 813 | 813 | 813 |
| 600165.SH | 2025-12-11 | 2025-12-11 | 63,434 | 1,393 | 3,349 | 197 | 199 | 197 |
| 600717.SH | 2026-06-23 | 2026-06-23 | 23,828 | 518 | 1,258 | 74 | 74 | 74 |
| 603221.SH | 2026-08-18 | 2026-08-18 | 10,948 | 238 | 578 | 34 | 34 | 34 |
| 688109.SH | 2025-09-25 | 2025-09-25 | 79,856 | 1,736 | 4,216 | 248 | 248 | 248 |
| 688689.SH | 2026-06-29 | 不重写 | 22,540 | 490 | 1,190 | 0 | 0 | 0 |
