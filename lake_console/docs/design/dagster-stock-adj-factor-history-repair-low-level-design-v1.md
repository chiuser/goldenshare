# 股票历史复权因子修正与 DG 下游修复 LLD v1

> 当前任务（2026-10-13）：DG 因子 Silver 当前上市规则迁移已完成，见 §18.10。现在回到原批准的 25 股/2,489 个历史因子键数值修正及受影响行情、指标/state 修复。最新只读结果、资产末端、事件补录设计和性能验收见[§19](#factor-downstream-repair-readiness-20261013)。本轮只更新文档；不改代码，不构建候选，不写正式 Lake/数据库或 Dagster 事件。Prod 保持现状。

> 最新范围（2026-10-13，管理员已确认）：因子仍25股/2,489键；额外统一688689.SH日线历史基准，1,299根OHLC差异位于2021-01-27—2026-06-11，日线指标/state需从2021-01-27重放至各资产冻结的实际既有末端（批准时快照为2026-10-12，最新见§19）。§15短区间审计中“日线指标不重写”是此前范围的结果，不能覆盖本次更早历史。范围/候选合并基础实现已有本地代码，完整执行入口仍未完成，25股正式数据尚未修正；详情及新增执行事实见§17、§19。

> 2026-10-13 周线接收状态更新：Prod 全量刷新已闭合为 B0=1785，DG 859 个复权 Raw 周文件/3,028,907 行、859 新物化和2,577检查及B0水位迁移已通过。详见[周线 LLD A21.4](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#adjusted-weekly-bootstrap-event-replacement-20261013)。本文较早库存/周线执行数量是2026-10-12审计快照；DG自主因子、日线/七频分钟QFQ、指标与state专项仍需按本文开发、候选和分阶段验收，不能将Raw周线完成当作下游重算完成。


<a id="joint-history-repair-lld-20261012"></a>

本次设计采用上位方案 §2 的唯一范围表；不另复制一份股票清单。2026-10-12 原审计确认 Prod 和 DG 均需修 25 只/2,489 因子键；Prod 后续维护已完成，当前仅 DG 尚待修正。下列价格数量为原短区间快照，不包含§17批准的688689额外历史日线范围或§19的更新末端。DG 日线输入影响 2,495 条，按七价格字段当前比较实际差异 2,489 条/25 只，量额差异 0；分钟目标库存 795,340 根/25 只/七频，60m 首个实际行情日样本 25 只均有差异，完整改写行/文件/指标/事件数仍须候选确认。不能用因子日期数推导行情行数，也不能只看 close 排除 688689。

本轮审计七价格字段按 2026-10-09 基准比较，1e-8 仅用于审计 DOUBLE 噪声，不是新增业务配置或正式写入容差。R0 冻结每股当前正式基准，禁止不经确认把混用基准的序列改为全历史换基准。

Prod 周线接收降为非阻断价格诊断，目标/冻结因子等真门禁保留。有限 Prod 因子维护后可继续周线原批；DG 因子/QFQ 候选可以同时准备，不等待 B0。周线本身继续 Prod → DG，不由此 LLD 计算或修改源周/月价格。


状态：原联合文档已对齐；范围/源值校验、逐文件候选合并和 MACD/KDJ 计算准备函数已有基础实现，完整 CLI、候选适配、提升及事件闭环尚未实现。§13—§17保留当时证据，§18的Silver规则迁移已闭合，当前25股任务以§19为准。正式执行仍需逐阶段验收和写入授权。

> 2026-10-12 文档纠偏已确认：管理员决定保留当前分钟生成逻辑。§5.4 及相关复用、规划、验收描述已改为七频从规定的 Silver 输入加因子生成，不读取新 Gold 30/60 生成 90/120。冲突历史与 R0 只读库存/性能结果见 §15；本轮不开发、不冻结执行计划、不写正式数据。

上位方案：[修复方案](./dagster-stock-adj-factor-history-repair-plan-v1.md)。本 LLD 设计上位方案中 25 只股票/2,489 个非舍入变化因子键的受控历史修复；取消原 601198.SH 的 451 日纯精度修复，不修改日常自动 repair 的参数、触发条件或字段合同。

## 1. 硬口径及实现映射

| 编号 | 硬口径 | 拟实现点 | 验收 |
| --- | --- | --- | --- |
| H1 | 只修批准股票及不能由精度变化解释的冻结因子键 | scope 校验、因子差异关系 | 其他股/范围外拒绝；全区间差异计数 |
| H2 | 原25股修复段 Raw 仅批准修正键使用当前 Tushare 原值；Silver 遵守当前上市 CNY 股票合同。已完成的 §18 迁移段不改任何 Raw 值 | factor candidate adapter、§18独立迁移 | 两段分别冻结及验收；当前上市范围、日期与源值一致 |
| H3 | 保持显式当前基准，不用修正旧日作为as-of；仅允许§17批准的688689日线统一基准例外 | frozen anchor、source overlay、批准scope | 基准漂移/未批准混基准拒绝；688689原范围正向验收 |
| H4 | 日线连带修正实际后继行的 pre_close | daily impact planner、既有 QFQ SQL | 停牌、多区间、首次行和缺因子反例 |
| H5 | 七频保持现行标准 K 线合同和 Silver 选源，统一调用 canonical QFQ SQL | minute candidate adapter、gold_stk_mins_qfq_source_freq | Gold 1/5/15/30/60/90/120←Silver 1/1/5/5/30/30/60；90/120 不依赖 Gold 30/60；窗口/量额等价 |
| H6 | 递推指标和 state 重放到既有末端 | trend/MACD/KDJ adapters | 分段对完整计算、跨年和末端 state |
| H7 | 九转按既有无价格合同重算 | canonical nine-turn builders | 连续计数超过九、区间外连带变化 |
| H8 | 原25股修复段非本股及范围外行不变；§18独立迁移段只移除冻结名单中非当前上市股票的因子，当前上市记录不变 | merge、双向集合差和主键审计 | 两段不共用变化集合；不得顺带修数值或改其他数据集 |
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

合同数据类和编排放第一个模块；候选适配、合并和本次审计放第二个；CLI 只解析输入与调用。不要新增通用修复框架、asset/sensor、业务表或永久checkpoint服务。job仅允许§19.3管理员已确认的一个手动检查补录入口，不新增其他job或自动调度；该入口只登记已验收检查，不执行asset、不计算行情、不写Lake。测试路径实施时按现行测试目录校准。

| 当前实现 | 复用方式和限制 |
| --- | --- |
| `assets/adj_factor.py` | 复用列合同、当前上市选择及日期转换；沿用§18已完成的当前上市规则；候选模式不得调用其直接正式 writer |
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

`RepairUnit` 至少包含 phase、asset、freq、年月窗口、输入/输出路径、预计单股行数及状态。`unit_id` 用这些业务范围与 `plan_hash` 生成，不依赖 Dagster event storage id。plan 另冻结逐股/逐资产/逐频率的实际价格末端、指标 result 末端、state expected 日期末端及上一 expected 日 seed/context 身份，详见 §19.2；总 end 只是允许核验的上界，不能覆盖这些实际末端。正式目标集合在完整候选审计后冻结，不允许运行途中增加股票或历史区间。

### 3.2 输入和默认行为

- 股票必须显式输入，本批只允许上位方案表中的 25 只；每只一个 FactorRepairScope，不允许空代码代表全市场。601198.SH、000668.SZ 仅精度变化的历史日期不在本批，输入时拒绝而非自动维护。
- 各股因子范围显式输入，ISO 日期，源请求转换为 YYYYMMDD；范围相同不等于所有日期获准，执行按冻结的精确差异键。
- `as_of_trade_date`、`repair_end_trade_date` 必填，不默认 today；每个资产的有效末端不晚于 end，并逐股分别记录实际日期/时间；不得用价格末端代替指标或state末端，也不把所有资产统一裁到最早末端。
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

`fetch_current_factor_rows` 调用 `adj_factor`，显式字段 `ts_code,trade_date,adj_factor`。本批 25 个单股区间，本轮 MCP 实际 25 次/2,489 行；正式执行另加每股基准/边界请求及真实分页；按真实响应分页，不能假设首包就是完整数据。MCP 不暴露分页参数，正式 `TushareResource.call` 的 limit/offset、空结果字段和边界已按 §16.1 实测；分页适配器仍待开发。调用失败和合法空结果分别报错；不从 Prod 文件冒充 Tushare Raw。

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

本节仅适用后续原25股因子值修复：Raw 候选为原全市场日文件按 `ts_code,trade_date` 保留非目标记录，再并入源站目标行；Silver 候选应用当前上市 CNY 股票筛选及日期规则。使用 `RAW_TUSHARE_ADJ_FACTOR_SCHEMA`、`SILVER_ADJ_FACTOR_SCHEMA`，不添加采集信息或修复标记列。先完成§18的Silver规则迁移，再重新冻结本节正式输入指纹；不得复用迁移前文件计划。§18不调用本节源因子修正或下游计算链。

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
checkpoints/candidates/<target-id>.json
checkpoints/promoted/<target-id>.json
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

事件阶段当前设计及性能门禁见 §19.3—§19.4；不得直接复制 §18 的逐日任务执行方式。先 `preview`：列出实际修改的 asset/partition、事件消费者、已有事件、需要补录的 materialization/check 数量和近期 readiness 样本。先小样本，后按资产/日期批次补录；只为经过同一 blocking 语义校验的文件报告成功。未变化文件不无意义补录。若现行 readiness 因上游文件版本变化确实需要重新验证，而下游业务行未变，events-preview 应单独列为“仅复验检查、无数据改写”，复用原 check 语义并另行批准，不伪造新的业务 materialization。

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
| 事件/消费 | 未通过check、错target/旧物化、多分区同check真实run、事件已写但checkpoint丢失、批次超限/错instance、未变日、普通sensor payload | §19.3隔离证明绑定/幂等；不伪造自动成功、不启动asset/写Lake；不扩大发布、不依赖reports |

真实小样本先选择 002713.SZ 等大变化股及 688689.SH（同时核验原短区间字段/分钟及§17批准的2021年起日线混基准/指标链），覆盖批准区间起止边界、实际后继日线、60m、最高行数 1m 片段及跨年指标 state；先只生成候选。R0 需列出源行/因子差异日/实际行情行/候选行/保留行/拒绝行，拒绝必须解释到 reason code 和样本。

最终验收不声称指标全部改变；分别统计计算行、实际差异行、跳过文件、提升文件和末端 state。正式源/目标对账一次完成，不能以测试通过替代真实行数和预算证据。

## 12. 未解决项和设计限制

1. 25 股/2,489 因子键已完整 MCP 和两边实物核对，无缺行；R0 仍须在执行前重新核验源集合、全部既有序列基准与各资产端点，当前快照不代替冻结。
2. R0 的源文件大小、九转完整文件规模和样本吞吐已见 §15；全链修正候选的实际扫描/写入、累计 RSS/空间及取消续跑仍待验证，不以单核样本放行全量写入。
3. 普通日线 repair 明确禁止人工股票池；独立历史入口不改变旧 config。基础 helper 已有代码，完整 CLI 与全链适配尚未完成；不能把 helper 测试通过当作正式修复完成。
4. 事件消费者已做只读核验，见 §19；执行前仍需核验活动/排队 writer、正常自动链完成及冻结输入。必要的调度操作、正式写入、事件和可选 Prod publisher 均未在本轮执行。
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

单进程连续盘点的 RSS 超预算是真实未通过项。DuckDB 连接释放不能据此推断进程累计内存一定释放；按频率新进程的实测支持上位方案 §5 已列出的子进程拆分方向。实施设计已收敛到 §16.2：编排进程不保留明细/全部 footer，计算子进程按阶段、频率和窗口退出，写入逐文件记录后释放。全链实现及资源实测仍待 R1—R3，不能提高预算、仅调用 GC，或拿单核样本通过代替全流程验收。

长递推已可在单股年度预算内计算，主要剩余成本是 13,005 文件的保留行合并、校验、fsync/hash 和恢复记录。没有测完整新因子→新价格→指标候选，因此不给出未经验证的全量完成时间。后续 R3 必须测全过程峰值、累计候选、spill、实际扫描和取消/续跑。

以约 1.2 万个路径的模拟完成列表估算，最终约 1 MB；如果每完成一个文件都重写增长的完整列表，累计约 6 GB，尚不含哈希/状态。这是格式成本模拟，不是已实现 writer 的实测结果或本批精确文件数。§16.3 已明确使用单文件完成记录和小汇总；不新增永久台账或 reports 依赖，待隔离中断/续跑测试证明实现符合该设计。

### 15.6 事件、并发与剩余验收

本专项catalog范围涉及31个资产：2 因子、1 日线价格、7 分钟价格、21 指标。按全部可能变化的逻辑日期预览，当时 materialization 上界 20,586、blocking check 上界 41,907，合计 62,493；这些数字不含§17新增范围与10月13日末端，也不含任务/日志事件，不能用作本次冻结预算；实际无变化结果可能跳过，正式补录只按核验后的变更分区。年度文件替换不是每一天全都有业务变化。

当前分钟 MACD 日常 run-status sensor 监听 stock_mins_qfq_daily_update_job、stock_mins_qfq_factor_repair_job 的 SUCCESS run；指标 repair 还监听 MACD 日常 SUCCESS。runless materialization 不等于一个 SUCCESS run，不会替代这些触发条件。分钟/日线九转另有按实物 readiness 的有界 sensor，不能只维护一条事件链。19:44 只读 instance 快照见到正常 factor repair 运行、相关 sensor RUNNING，之后价格/指标末端已追齐 12 日；本轮未停止或触发它们。正式冻结前须再次列出活动/排队 writer，另获批准后暂停、排空并独占执行。

分钟选源的文档纠偏已确认。正式 SDK 分页/边界实测和子进程/checkpoint 实施设计已在 §16 完成。后续仍需：完整修正候选及逐行/逐字段等价；实际不同指标/state/file 数；共享合并与子进程全链预算；checkpoint 实现与中断续跑；候选后的事件精确预览；存活 Reader/页面/下一日续算验证；可选 Prod 日线九转 serving 的差异与独立授权。这是10月12日的开发前记录；当前基础实现已存在，完整专项及上述门禁仍未完成，最新状态见§19，不宣称25股正式修复完成。

### 15.7 逐股指标重算起点与数量

以下数量截至既有 2026-10-12；分钟列合计七频 MACD 和 state、四频九转输出窗口。日线三列分别为趋势结果/state/九转；“不重写”仅是688689原短区间的旧结论，已被§17批准的额外历史日线范围替代；全表保留为10月12日快照，不是当前执行清单。首次因子变化与首次实际行情可能不同，不能把停牌日期当价格缺口。

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

<a id="history-repair-execution-design"></a>

## 16. 实施设计收尾（2026-10-12，步骤 1）

本节完成分页、进程拆分和恢复记录的开发前设计，不表示 R0 可执行计划已经冻结或 DG 修复工具已经实现。执行时仍重新读取批准的 25 股源集合、正式基准、全部资产端点及活动 writer；范围变化按原门禁停止。本节不改变分钟选源、公式、事件合同或共享配置。

### 16.1 正式客户端分页与边界实测

读取 `resources.py::TushareResource.call`：参数原样传给 SDK，fields 必须显式；返回 `TushareResult.rows/columns`。无字段的响应抛出 `TushareResponseError`，不能当成合法空页。SDK 调用不会自行遍历分页。鉴权使用现行 `TUSHARE_TOKEN`，不增加来源或记录令牌。本地源文档为 [adj_factor](../../../docs/sources/tushare/股票数据/行情数据/0028_复权因子.md)。

先用 MCP 显式请求三字段核对 `688689.SH` 的 `20260629—20260707`，返回 7 个唯一日期、因子均为 1.0597。再在现有 orchestrator 环境直接调用正式 Resource，共 8 次只读小请求：

| 区间 | 完整参照请求 | limit=3，offset=0/3/6 | 验收 |
| --- | --- | --- | --- |
| 20260629—20260707 | limit=6000，offset=0，7 行 | 3/3/1 行 | 页合并与完整参照逐键逐值一致，无重复，无越界 |
| 20260629—20260706 | limit=6000，offset=0，6 行 | 3/3/0 行 | 整页边界后的终空页仍保留 ts_code/trade_date/adj_factor 三列 |

两端日期都包含在响应中。上述小样本证明当前客户端可传分页参数及合法终空页结构，不证明未来源排序或完整性恒定。临时 JSON 仅为本轮实测材料；事实和结果已写入本节，后续入口不消费该文件。

拟分页适配器使用 limit=6000、offset=0 起步；满页后 offset 加 6000 并继续，短页（含有列的空页）结束。批准区间当前每股最多 240 行，通常首包短页；每个区间最多两页作为截断/源漂移保护，超过冻结行数或出现异常满页停止重审，不把额外股票/日期纳入修复。每页前后检查取消，校验响应列、代码、日期、正有限因子和唯一键；重复键即拒绝，不 silently 去重。整段与冻结精确键双向一致后才接受，缺行或额外日期均停止。基准/边界请求单独有界，按相同规则核验。请求异常继续传播，不转为空数据，不新增自动重试策略。isolated 测试需覆盖 3/3/1、3/3/0、无字段伪空页、重复/越界/缺键及分页取消。

### 16.2 顺序子进程和阶段边界

编排进程只负责计划、取消、进度、预算和恢复，最多同时一个工作子进程；不初始化 DuckDB、不保留行情/state 明细或所有 Parquet footer。工作进程使用新解释器启动，输入为已冻结 plan 路径/hash 和 unit_id，读取自己需要的关系；禁止 fork 继承上一次计算堆。返回消息仅为 unit_id、计数、字节、记录目录及有限错误信息，明细通过 staging 文件交接，不能通过 IPC 回传整个 DataFrame 或文件列表。

| 子进程任务 | 业务 unit 与输入复用 | 持久化及下一步 |
| --- | --- | --- |
| 源核验/因子与输入投影 | 因子按单股批准区间；宽 Silver 按源频率/月投影全部批准股票，同一输入只投影一次 | 有界源与 inputs 文件、内容哈希；下游复用，不能逐股重复扫宽文件 |
| 日线/七频价格 | 日线按年度；分钟按频率/年度，内部按股和≤100,000 行片段计算 | replacement 文件；同一目标汇总全部股票后合并一次，逐文件候选记录 |
| MACD/KDJ | 单一频率/年度，内部按单股年度片段，读取上一片段新 seed；日首起算 | 年度结果 replacement 和日 state replacement；跨年 seed 经 staging 交接 |
| 趋势/九转 | 单资产/频率/月，内部按股的现行有界核及精确 seed/context | 当月 replacement；九转完整单股输入最大 24,824 行可复用现行完整核 |
| 共享日文件合并、候选审计和正式读回 | 单资产/频率/月；年度文件按单文件处理，不跨七频连续累积 | 每目标文件仅一份最终候选/记录；哈希与计数按文件输出 |

递推子进程退出前必须保存新的 seed/state 与完成记录；未保存的片段从上一持久化边界重算。共享目标候选只有收齐该文件所有批准 replacement 才可生成，单股片段完成不代表最终文件已完成。候选准备顺序沿 §8；所有价格/指标候选及完整审计通过后才可正式提升，不在内存高时先提升半链。

每个子进程显式 512 MiB DuckDB、2 threads、run/temp 下 spill；父进程监控自己与活动子进程的 RSS，合计不得超过 1 GiB，避免把拆进程当作成倍扩大预算。总 spill≤2 GiB、累计候选≤10 GiB，退出后记录测量值，不改变共享默认。取消先中断活动 SQL/子进程并等待退出，保留已完成文件，之后不领取新 unit；恢复重建新进程。最长 30 秒更新真实片段/文件完成量；无业务进展时明确显示仍在当前 SQL，不用心跳虚增百分比。

R3 必须测父+子全链 RSS、累计候选、spill、文件合并/哈希/fsync、最长 1m、跨年 seed 以及取消后无残留进程。当前各频新进程探针只能支持拆分方向；本节不声称全链预算通过。若某 unit 超预算，先拆窗口或优化输入/SQL，不能自动提高限额。

### 16.3 单文件恢复记录

`target-id = SHA256(规范化 Lake 相对目标路径)`；记录同时保存真实路径，读取时核验 hash/路径/plan_hash 一致，拒绝越界、符号链接和碰撞。两个目录分别表示候选完成和正式提升完成，均在本 run 的 staging 下；不注册新 asset、数据库表或日常台账。

每个 `checkpoints/candidates/<target-id>.json` 保存 format_version=1、plan_hash、unit_id、asset/partition、target_relative_path、candidate_relative_path、preimage_sha256、candidate_sha256、原/候选行数、实际变化行数、候选字节和文件校验结果。只有 COPY 关闭、候选 fsync、结构/键/保留范围与哈希校验完成后，才写临时记录并 fsync、原子 replace、fsync 目录。无差异文件记录 no-op 及原哈希，不造新候选；未完成文件不得伪装完成。

`checkpoints/promoted/<target-id>.json` 保存 format_version、plan_hash、target_relative_path、审计后的 candidate_sha256、正式读回哈希和 verified 标志，逐文件读回成功后按相同原子流程保存。正式文件 replace 后 fsync 目标目录，再读回；提升后记录失败不回滚已经提升的业务文件。

`checkpoint.json` 仅保存 plan_hash、phase/status、当前 unit、阶段完成数、累计字节/资源峰值和最后更新时间，不存不断增长的路径或事件列表。它是进度投影，写失败不能否定已经完成的文件。恢复按目录逐条读取记录、核验文件实物并重建小汇总，文件路径与哈希才是续跑依据；每文件记录独立写一次，避免每次重写约一万项列表。最终 audit 完整目标索引只写一次；下游审计按资产/频率/窗口读取记录，不把全部行情或 footer 留在编排进程。

恢复分支保持 §8：已提升 target=审计后 candidate hash，补齐缺失提升记录后跳过；target=preimage 且候选有效，继续；其他 hash 停止。已有完成记录但实物不符也停止。候选记录缺失但文件存在，不按存在即完成，重新完整校验或重建当前未完成文件。用临时测试目录验证 COPY/记录/fsync 失败、replace 后进程退出、损坏记录、外部改写、重放和取消；无需在正式 Lake 制造故障。

### 16.4 本轮完成与后续门禁

步骤1的分页实测和两项实施设计当时已完成；随后基础代码已有实现，最新状态见§19。下一轮 R1/R2 按本节实现候选适配器及共享计算核提取，测试和全链样本性能通过后再审计候选。因子 25 股/2,489 键、日线/七频分钟及 21 个指标资产边界均沿原范围，正式写入、事件和调度仍分阶段授权。原 R0 快照不直接作为稍后执行的冻结事实。

## 17. 执行前复核及688689日线基准扩展（2026-10-13）

管理员已批准继续DG下游修复，并在发现历史混基准后单独确认扩展688689.SH日线。重新MCP请求25股批准区间，返回2,489个唯一键；正式Raw/Silver同键均存在，两层相等且仍与源不同。702个日文件、37,131,287字节的因子核验1.128秒/RSS183.3MiB，生命周期冲突、重复、缺行和读取期间文件漂移均0。25股10月9/12日源基准返回50行；本次端点仍为10月12日。

按月扫描25股完整既有日线66,414行，比较未复权OHLC×既有当日因子/当前1.0597等逐股基准，仅688689.SH出现混基准。其2021-01-27样本：未复权close=32.07，Gold close=30.426944971537，对应旧基准1.054；7月8日及后续使用1.0597。原批准7个因子日期替换后OHLC已正确；其他1,299根日线仍应统一当前基准，日期2021-01-27—2026-06-11，最大close差0.2969191201763266。不是舍入噪声；原短区间审计遗漏了更早历史。完整源因子额外精度差异不纳入修复，保留旧采集值更多数位。

| 新增范围 | 执行语义与验收 |
| --- | --- |
| 688689日线价格 | 用原QFQ SQL与修正因子、当前有效基准，重算自2021-01-27至既有末端的候选；只合并实际不同键，包含previous相关字段；范围外股票不变 |
| 688689日线趋势/result、state、九转 | 从实际首次上市行情2021-01-27起重放到各自冻结末端；下列数量截至批准时的2026-10-12，执行前重新盘点；结果1,369行、state1,379行、九转1,369行进入核验，不能据此声称全部不同 |
| 因子与分钟 | 原25股/2,489键不变；不把旧价格基准问题扩成全历史因子重采。688689七频每年首个行情日样本1,932根，按现有因子/当前基准生成与Gold一致；该样本不替代分钟全链候选验收 |

H3调整为：普通股票历史混基准仍停止；只允许上述已批准688689日线统一基准例外。不放宽源/目标漂移或预算，不添加自动历史检查。FactorRepairScope新增可空daily_basis_start_trade_date，其他股票为空，688689只能为2021-01-27；来源为批准scope→冻结plan，无env/Settings/数据库来源，无默认today。消费者为日线impact、日线候选、趋势/九转replay planner和候选范围审计，续跑不可更改，CLI inspect/freeze显式输入并校验白名单；正反测试覆盖其他代码、任意更早日期及未批准混基准拒绝。各资产冻结末端仍独立，不能用这一字段更改分钟起点。

开发继续遵守H1—H14及§16的分页、顺序子进程与逐文件记录。先生成因子/行情/指标/state全链候选，通过完整审计后，独占窗口按因子→价格→指标/state提升；不得先覆盖因子让消费者读取混合链。新增日期的文件、事件和空间上界在freeze前重新统计，10GiB候选、512MiB DuckDB/1GiB父子合计RSS预算不变。

### 17.1 退市股票的Silver历史因子与周线来源（2026-10-13只读核清）

> 以下数量和旧检查结果保留为历史审计证据。管理员随后明确 Silver 只保留当前上市股票，退市股票不要求历史因子；最新执行口径见§18。不能继续据此补125只退市股票或把其7,468条历史缺记录视为本次阻断项。

复用当前正式检查SQL复核本次涉及的351日/702个Raw和Silver文件：Raw结构、分区、唯一键和正因子通过；252个Silver日期不符合现行全市场覆盖/生命周期检查。2023-06-01—2026-04-24缺少125只其他股票合计7,468条股票—日期因子记录；另有6条退市生效日记录：000638.SZ/2026-06-03、688287.SH/2026-06-10、600599.SH和600421.SH/2026-06-26、600636.SH和600696.SH/2026-06-29。本批25股的2,489条记录均存在且生命周期合法。例000005.SZ/2023-06-01在Raw有adj_factor=9.268，但Silver没有；不能将Silver缺记录统称源端无数据。

全文件扫描2.478秒，峰值RSS326.6MiB；缺记录数按股票和日期累计，不是7,468只股票。先前未分类当前上市状态就请求验收口径确认，管理员指出证据不足，该确认已撤回，以下补全实物/源核验；不得把该问题认作扩大范围授权。

MCP stock_basic分别请求L/D/P，显式取ts_code/name/list_status/list_date/delist_date/exchange/curr_type，返回5,574/339/0行，代码唯一。与125股逐一关联：**125只全部D（已退市），当前上市或状态未知均0**；源退市日期与DG生命周期表完全相等，与本次25股无交集。

历史根因证据：14f68cb2（2026-06-21）将Silver因子从silver_stock_basic/current_cny_stock_basic_select的“当前上市名单”过滤改为silver_stock_lifecycle历史生命周期过滤；此前已经退市的股票会被旧过滤器连同上市期间历史因子一起排除。正式2023-06-01的Silver最新物化storage_id=3802125仍为旧初始化记录、row_count=5,071，与当前文件一致；Raw相应旧初始化row_count=5,252。旧文件没有随过滤逻辑变更而完整重建。125股源退市时间全部早于该旧Silver初始化时间；不能将历史代码修正当作旧文件自动修正，也不能把此根因混同4条源本来无返回的记录。

7,468条Silver未保留的历史因子中，**7,464条DG Raw有有效正因子**。Prod规定脚本在READ ONLY/20秒事务按同一7,468个明确股票—日期查询，Raw和Core均有7,464条且Raw/Core值差异0。另4条Raw、Prod Raw/Core也没有，全部是2026-02-03的002231.SZ、300344.SZ、300391.SZ、603056.SH；逐股MCP请求20260202—20260204均返回2日和4日因子，没有3日。因此这4条只能记录源缺记录事实，不能归因漏下载、从邻日自行补值或要求无源强补。

当前周线是Tushare stk_week_month_adj直接提供21个源字段，Prod接收close_qfq/close_hfq原值；validate_weekly_adj_source_basis只使用Prod core.equity_adj_factor及core_serving.equity_daily_bar做有界基准核验和价格诊断，不读取DG Silver因子。历史bootstrap无独立依据时记录unverified后保留源价，不表示本地重新算过或所有行已独立核验。DG assemble_adjusted_bootstrap_relation只合并21列并保留独有键，不调用日线/分钟QFQ SQL。源码与传输事实不能表述为缺因子时本地仍算出周线。

对这125股按明确代码集合核验2010-01-01—2026-10-09：Prod/DG实际各有**36股/23,656条复权周线**，qfq/hfq空值均0，另89股没有这套源复权周线。没有为125股全部生成历史周线。样本300344.SZ/2026-02-06，MCP源、Prod、DG均close=2.78、close_qfq=2.78、close_hfq=13.19；Prod当周最后实际日线为2月5日close=2.78/因子4.743，源计算截至4月17日的因子也4.743，缺2月3日因子不影响该周收盘基准。不能用这个样本宣称36股全部价格已独立验证。

本次25股候选与周线传输是独立链。2026-10-13管理员最新决定已明确：不补125只退市股票的Silver历史因子，按§18迁移因子Silver生成和检查规则，并重建受影响文件；6条退市日旧记录包含在本次移除退市股票的集合中，不另做删除任务。原25股及688689日线扩展仍保留为后续独立任务，当前段不执行。正式候选、文件和事件仍未写入。

本轮已完成专项scope/source/逐文件候选记录与保留行合并基础代码；正式因子checks的分区、重复、正值和生命周期/覆盖SQL已提取为共享纯校验片段，原checks名称及语义保留。MACD/KDJ公开prepare_stk_mins_qfq_macd_kdj_replacement_tables返回两张候选关系与初始化标记，原writer已迁移同一计算体，无旧算法或兼容别名；正常/历史/BSE/repair通过同一writer消费。64项相关隔离回归及16个子测试通过，本轮Python默认Ruff、文档完整性和差异检查通过；CodeGraph explore/impact用于范围和调用方核验，sync/status最新。CLI、完整R0冻结、实际候选与正式提升仍未完成，不把基础代码通过称为25股正式修正完成。

<a id="adj-factor-current-listed-migration"></a>

## 18. DG复权因子Silver当前上市规则迁移LLD（2026-10-13，已完成并正式验收）

### 18.1 硬边界、现状与完成定义

本段只完成复权因子Silver选股规则及存量文件迁移。Raw源全集保持不变；Prod保持现状；原25股因子值修正、日线/分钟行情、技术指标及state不在本段执行。既有Raw中退市记录不得裁剪，因子值精度不得重新规范化，禁止Tushare或Prod请求。正式写目标只能是`/Volumes/datasource/data_lake/silver/quote/adj_factor/trade_date=*/part-000.parquet`；staging只能在`/Volumes/datasource/data_lake_staging`。

迁移前代码使用历史生命周期集合，现有文件又混有旧当前上市规则的结果。S0代码已统一当前上市集合，S1—S4正式文件及事件迁移已完成，证据见§18.10。2026-10-13已核验的八个Prod关键源码文件与本地相同，本段不触碰它们。整项完成须同时满足：生成SQL、生产checks、physical readiness、窄范围安全重建评估使用同一当前上市集合；正式Silver文件按新规则完成迁移；实际变化分区有对应新物化和真实检查结果。仅文档、代码或文件单项完成均不能称为整项完成。

### 18.2 单一选股事实及SQL

继续以通过检查的`silver_stock_lifecycle`为身份来源，其中已有`list_status`、`is_cny_stock`、`list_date`、`delist_date`。新增因子专属纯SQL函数，拟名`adj_factor_current_listed_stock_select(lifecycle_path)`，输出`ts_code/list_date/delist_date`，只选`is_cny_stock AND list_status='L'`且身份、上市日期有效的股票；函数在`duckdb_sql.py`中定义。

生成与expected集合共用该函数，日期条件保留：

```sql
SELECT normalized.ts_code, normalized.trade_date, normalized.adj_factor
FROM normalized
JOIN current_listed USING (ts_code)
WHERE normalized.trade_date >= current_listed.list_date
  AND (current_listed.delist_date IS NULL
       OR normalized.trade_date < current_listed.delist_date)
```

`normalized`仍为Raw三源字段及既有DATE/DOUBLE转换；不得计算新因子。当前上市状态决定股票是否进入所有历史分区，日期边界只约束该股票的合法日期。D股票退市前因子也排除，D股票缺历史因子不进入coverage_missing。P、未知身份、非CNY和上市前记录按同一选择规则排除，不擅自当L保留。

**不修改`silver_cny_stock_lifecycle_select`。** CodeGraph impact已确认它还被股票日线等数据集消费，改通用函数会改变本次以外的历史保留规则。新函数只进入因子生成、因子检查、因子physical readiness和本段重建；不恢复旧湖、旧Console或兼容双轨，不新增可配置过滤开关。

### 18.3 代码、契约和测试映射

| 代码位置 | 必须统一的内容 | 实施验收 |
| --- | --- | --- |
| `defs/duckdb_sql.py` | 因子专属当前上市选择；`silver_adj_factor_select`使用它 | L合法历史保留；D退市前/当天/之后均排除；P、非CNY、上市前反例 |
| `defs/assets/adj_factor.py` | writer、`_silver_filter_counts`、filter_policy、description、运行说明与新SQL一致 | 日常输出等于候选输出；source/selected/rejected计数闭合；已有`lifecycle_stock_count`不暗改为当前上市数量 |
| `defs/checks/adj_factor_checks.py` | `adj_factor_invalid_lifecycle_sql`、`adj_factor_coverage_relations_sql`、候选规则审计统一当前上市集合 | D不再报缺失；D残留报unexpected/非法范围；L真缺因子仍失败；schema/分区/键/正值规则不弱化 |
| `defs/asset_guards/adj_factor_lake_readiness.py` | `_silver_metrics_by_trade_date`及安全重建评估中的expected、invalid选择统一 | physical readiness与正式checks对同fixture结论相等；Raw缺L拒绝，Raw缺D不阻断 |
| `defs/sensors/stock_adj_factor_sensor.py`、`defs/sensors/readiness.py` | 继续消费上述统一判定；最近10日窗口、既有job、run key、cursor和四项check名保留 | 同日名单变化安全重建；非名单问题拒绝；正常tick不新增全历史查询 |
| `defs/catalog/lake_assets.py`及definition metadata | 审核`silver_adj_factor`的合同描述与实际规则相同；保持schema/path/asset/check身份 | catalog、定义metadata、文档三者一致，不新增资产或版本表 |
| `defs/bootstrap/adj_factor_silver_history.py` | 在原模块提供plan/build/audit/promote职责，候选使用同一SQL | 旧工具默认跳过已有文件且直接正式写，不能拿它原样执行本迁移 |
| `defs/bootstrap/stock_adj_factor_history_repair.py` | 后续25股入口的scope身份校验引用因子专属选择；本段不调用其数值修复链 | 迁移后重新冻结25股计划；退市历史不被原检查再补回 |

测试落在现有`test_adj_factor_contracts.py`、`test_adj_factor_checks.py`、`test_adj_factor_lifecycle_rebuildability.py`、`test_adj_factor_silver_history.py`、`test_adj_factor_human_readable_contracts.py`、`test_batch_readiness_hotpath_performance.py`、`test_asset_governance_contracts.py`及原25股scope测试。增加同一股票从L改D后既有历史因子被移除的样本，证明日常生成、历史候选和检查一致；不能只测试退市当天。对通用日线生命周期SQL保留独立回归，证明其他数据集没有被改为当前上市。

原25股候选合并函数仅允许替换既有批准键，不允许删除任意股票，**不为本段向它增加通用删除参数**。本段生成完整Silver预期关系并比较，删除权限仅来自冻结的当前上市筛选计划；不动行情/指标核或其测试期望。

### 18.4 只读冻结及已核实文件规模

S1以冻结时既有Silver日期集合为边界。初次盘点Raw10月13日已存在、Silver尚未生成，属于普通日更；执行时该Silver已由日更生成，所以纳入4,315文件的只读范围并保留。本迁移不为缺日新建文件或动态分区。先核验生命周期文件检查、名单唯一性和新鲜度，再冻结名单身份及源码、原Raw、原Silver的强指纹。股票名单可在run下保存最小只读输入投影，不创建正式版本资产或备份。

最多64日一批，投影Raw/Silver三字段，按新SQL从Raw生成expected，与既有Silver做双向`EXCEPT ALL`、主键和保留值比较。冻结只存在业务差异的文件；禁止因为计划范围覆盖全历史就替换所有文件。发现L股票缺键、数值变化、非预期删除或名单冲突，输出代码/日期及原因，停止重审；不顺带修原25股数值或补源日期。

2026-10-13只读实测：

| 项 | 结果 |
| --- | --- |
| 已有Silver范围 | 4,314文件，2009-01-05—2026-10-12，14,457,307行 |
| 新规则差异 | 移除14只D股票45,997行，新增/改值0；包含6条旧退市日记录 |
| 差异文件 | 4,267个，2009-01-05—2026-07-29；47个文件不变 |
| 新规则预期总行数 | 14,411,310；执行前重审，不写死为永久断言 |
| 差异文件压缩字节 | 原Silver132,096,174，对应Raw141,535,789 |
| 审计方法和耗时 | 64日批次，新连接、2线程、512MB上限、禁spill，双向集合核验5.442秒 |
| 内存反例 | 单条全历史集合查询在相同预算下触发内存拒绝；未写文件，未提高预算；已改用上述有界批次审计 |

每个迁移unit是一份Silver日文件；冻结记录包含名单/代码指纹、日期、Raw输入指纹、Silver原指纹、预期移除键及计数、当前上市保留记录摘要、候选指纹和结果。运行中的数字若偏离冻结集合，停止而不是自动扩大范围。首次审计5.442秒不代表正式生成、事件或RSS实测通过。

### 18.5 预算、候选和文件提升

| 参数/约束 | 本段值 | 来源及消费者 |
| --- | --- | --- |
| 规划日期批次 | 最多64日 | 本段常量→冻结计划；差异SQL及完整范围验收 |
| DuckDB/threads | 512MiB/2 | 本段计划→configured connection；不改共享默认 |
| 父子进程RSS合计 | 1GiB | 编排进程监测；超限不提升 |
| 候选/spill | 256MiB/512MiB | plan→COPY前后累计检查、run/temp；超限停止 |
| staging可用空间 | 至少1GiB | 候选+spill及20%余量，启动及COPY前检查 |
| 同时写文件/真实check run | 各最多1个 | 顺序执行，下一unit前检查取消 |
| 可见业务进度 | 最长30秒 | 日期、已完成文件/总数、累计行数/字节、最后更新时间；不伪造ETA |

这些仅为本段冻结计划参数，不新增env、数据库配置、sensor参数或普通job开关。改变预算需重新评审并冻结，不能在恢复时提高。先取早期历史、退市生效日、当前上市但无变化日三类隔离样本，再对最大现有日文件生成候选，记录实际生成/校验耗时、RSS、压缩大小；据样本估算全量文件和事件阶段的各自耗时。

`build`在run/candidates下按同一日常SQL从Raw重建目标日全市场Silver，完整校验schema、日期、正值、唯一键、新上市集合覆盖，并与expected精确一致。进一步证明全部当前上市业务行与迁移前逐字段相同，全部删行均不属于冻结当前上市集合。无变化文件仅校验并跳过，不写候选或事件。

完整候选通过后进入因子writer维护窗口，逐一核对目标preimage、源Raw和名单未漂移，同文件系统`os.replace()`，读回并记每文件checkpoint。取消不领取新文件；replace后记录失败不回滚数据。续跑接受目标等于preimage或已审计candidate hash，其他变化停止。不同日文件不承诺整体原子，不创建Kopia/备份或改业务表。

旧`report_adj_factor_silver_history(overwrite=True)`会调用直接正式writer，不能用它替代候选流程；`skip_existing=True`也不能当作规则迁移完成。S3后只做本批一次完整读回对账，证明目标等于候选、47个快照未变文件仍未变、全部Raw未变，之后不把指纹或run记录加入日常门禁。

### 18.6 Dagster事件、依赖消费者及收尾

文件提升与事件登记分开，保留旧历史事件。按冻结后的实际差异文件预览：本次快照最多4,267条新物化、4×4,267=17,068条既有聚合检查结果，合计21,335条业务事件；真实check运行的运行日志另计。事件阶段单独取样实测吞吐，不按文件COPY速度估算。

新物化登记前核对对应正式文件仍等于已审计候选；metadata写真实日期、行数、移除数量及本次人工来源。检查沿用`silver_adj_factor_contract_check`、`silver_adj_factor_key_value_integrity_check`、`silver_adj_factor_lifecycle_coverage_check`、`silver_adj_factor_partition_allowed_check`四项身份，不能追加同名无运行检查或伪造run ID。

已实现解析既有`silver_adj_factor_update_job`，用`JobDefinition.get_subset(asset_selection=set(), asset_check_selection=<四项key>)`取得只执行检查的子集，逐日期创建真实运行，绑定刚登记的新物化。隔离instance已验证分区上下文、原job身份、零asset执行和实际物化绑定；正式阶段仍须先预览和小样本，再完整范围执行。无需新增注册job或sensor。若正式子集不能保持这些语义，停止事件阶段并说明，不回退同名无运行检查、不直接重跑资产。参考[Dagster检查子集官方文档](https://dagster.io/docs/guides/test/running-a-subset-of-asset-checks)。

事件消费者须预览并隔离核验，避免下游自动响应历史因子物化而重算行情或指标；正式事件窗口使用运营维护流程控制相关触发者，CLI不擅自启停服务/sensor。事件失败保留文件及真实失败run，按文件/物化/检查记录续跑，不清旧run、事件、cursor或水位。因子代码部署后可用新生成器处理正常新日期，但本段历史文件和事件未验收前不称全历史迁移完成。

CodeGraph explore/impact已覆盖因子writer、check、physical readiness、安全重建sensor及通用生命周期选择的其他调用方。下游日线/分钟QFQ仍依赖Silver因子，部分旧历史输入包含退市股票；移除D因子后，这类股票历史重算可能被既有覆盖检查拒绝。这是本次允许Silver不保留D的影响，不为此补D因子、改Gold/指标、静默跳过消费者检查或增加Raw兜底。当前上市股票数值未变，本段没有价格或指标数值重算需求；不能声称所有历史下游检查已通过。

本段完成后以迁移后的正式文件重新冻结原25股修复计划，不复用旧文件哈希或旧候选。日常更新仅使用当前输入和本次日期检查，不依赖reports或本段run目录。未来上市状态改变时，新日期按最新L集合生成；历史是否重新迁移由同一受控入口处理，本段不新增自动全历史扫描或清理机制。

### 18.7 本轮状态及后续顺序

文档先提交`a6a75cc6`，规则和工具提交`a3ad9b84`，同预算规划优化提交`60978af9`。S0—S4已完成；当前上市筛选的代码、正式Silver、检查和文档已对齐，正式证据见§18.10。本段仅复权因子Silver TODO结案；原25股因子值、行情、指标/state修复尚未执行，须以迁移后文件重新冻结其输入。下一自然交易日只观察既有日更生成与同日检查，不再添加全历史对账或reports依赖。

### 18.8 实现和验证记录（2026-10-13）

- 因子专属`adj_factor_current_listed_stock_select`已被生成器、filter counts、候选检查、physical readiness、安全重建评估共同使用；共享生命周期选择及日线SQL未改。已有`lifecycle_stock_count`仍表示源表CNY股票总数，不暗改成当前上市数量。catalog的schema/path/四check身份审核一致，不需要新增entry。
- 原`adj_factor_silver_history.py`提供`plan_silver_adj_factor_rebuild`、`freeze/load_silver_adj_factor_rebuild`、`build_silver_adj_factor_rebuild_candidates`、`promote_silver_adj_factor_rebuild`、`verify_silver_adj_factor_rebuild`及事件preview/report入口。计划包含预算、名单、Raw/Silver和源码强指纹；最多64日比较，按日COPY。完整候选审计冻结每份候选记录指纹，提升前及逐文件核对，防止候选和记录同时被改后误提升。COPY及replace后fsync；replace后checkpoint失败按目标内容续跑，不回滚已完成文件。正式promote和events均默认拒绝，需明确维护窗口确认。
- 100项针对性隔离回归及18个子测试通过，覆盖D股票退市前历史也排除、P/非CNY/未知身份/上市前排除、L真缺因子不放过、当前上市值不变、Raw和其他层不变、候选取消续跑、正式替换中取消、replace后记录失败恢复、幂等、输入漂移、候选损坏、候选记录篡改、预算和staging越界拒绝，以及run成功但检查绑定错误仍不得标记验收通过。未改或执行原25股因子值修正/行情/指标/state链。
- 既有job的检查子集在隔离Dagster instance中登记2条新物化、创建2个真实check run并产生8条检查，全部绑定正确物化；零asset执行，幂等重放不追加物化或run。事件记录只有四项检查及绑定完整通过才标记`checks_verified`，不能仅凭run成功跳过未验证记录。
- 通用性能文件依赖停牌专项启动器，直接收集曾失败，没有放宽或绕过保护；因子独立测试使用5,000只上市股、1只退市股的十日夹具，扫描20个因子文件，42条SQL（40条schema/列查询及2条聚合），满足既有10秒预算。资产治理改用已有受保护启动器，12项及其子测试通过，schema、分区、catalog、check身份均保持一致；原保护文件/白名单未改。
- 三个正式日期仅只读核验：2020-02-28原3,588行→新规则3,577行，移除11；2026-06-03原5,525行→5,511行，移除14；2026-10-12原/新均5,573行。三个日期新增或改值均0，7个输入文件指纹读取前后不变。只读比较0.027秒、进程峰值RSS138.5MiB；不是正式候选生成或事件吞吐。
- 本轮Python默认Ruff、全项目致命错误基线、文档完整性及差异检查通过。CodeGraph explore/impact及sync/status覆盖入口、调用方及共享生命周期影响面；未改变子系统依赖矩阵、Prod代码/文档、数据schema、job/check身份、sensor配置或API。

本轮提交范围仅含S0因子Silver规则、受控重建工具及测试、三份原文档；原25股入口的本地待提交工具不混入本次提交，其scope选择在原25股任务恢复前按§18.3重新校准。S0阶段执行记录：当时正式Lake、Prod、正式instance事件/分区/cursor零写入，没有部署、重新加载、启停服务或sensor。正式候选、文件覆盖、事件吞吐和自然日更仍待后续按S1—S4实测，当前旧Silver文件不能宣布已清理。

### 18.9 正式执行预检及同预算SQL修正（2026-10-13）

代码与三份文档已提交`a3ad9b84`。用户重新加载后，GraphQL返回新当前上市描述；正式实例无运行中任务，生命周期2026-10-13物化7471878及检查、新鲜度均通过。S1只读规划尚未冻结，连续64日批次在256日后峰值RSS1,086.4MiB，触发既定1GiB门禁；没有候选、正式文件或事件写入。隔离测试此前未覆盖多批累计内存，不能用小样本结果替代完整规划性能。

根因定位到batch比较重复引用包含64个文件分支的视图；改为每批仅物化一次before/expected临时表，比较SQL、选股、字段和精确集合验收均保持原口径。只读全范围比较4,315日通过，17.3秒、峰值586.8MiB，移除45,997行，无新增/改值。正式helper沿用64日、512MiB/2线程、1GiB、禁spill的原预算；不改配置或扩大业务范围。增加256日×5,001股连续批次回归，核对每日期5,001→5,000且进程不超预算。正式冻结及后续候选、提升、事件性能仍待执行结果，不将此次只读结果写成迁移完成。


### 18.10 S1—S4正式执行及收尾（2026-10-13）

S0代码提交`a3ad9b84`，同预算规划优化提交`60978af9`，74项隔离回归及18子测试通过。正式冻结plan hash=`23204ed4ddd257d5936ea0de4ebf1299e2dce8a253602a4736d5643a9afad714`，运行目录为`/Volumes/datasource/data_lake_staging/adj_factor_silver_current_listed/20261013-23204ed4ddd2`；记录仅供本次操作续跑，不进入日常门禁、不依赖reports。

| 阶段 | 实际结果 | 时间和RSS |
| --- | --- | --- |
| S1完整只读规划 | 4,315 Raw文件、4,315现有Silver文件；原Silver14,462,881行；仅4,267文件需移除45,997行，2009-01-05—2026-07-29；当前上市新增/改值0 | 19.18秒，663.5MiB |
| S2候选 | 4,267完整候选均通过；131,536,425字节；完成记录及audit=candidates_ready | 91.34秒，489.4MiB |
| S3正式提升及一次对账 | 4,267文件逐一原子提升并完成checkpoint；48文件指纹保持原样；全部Raw和名单/源码未变；正式Silver14,416,884行精确等于当前上市生成SQL | 102.94秒，759.8MiB |
| S4前三日 | 3新物化、3真实run、12四项检查全部通过并绑定新物化，零asset执行 | 含全范围复核22.30秒，722.5MiB；检查每日期约1秒 |

S4小样本：2009-01-05物化7473870/run `8475db4f-641a-4361-bb72-254bbbdf4caa`，01-06物化7473898/run `ec057039-3eeb-4e5b-8db9-4447f118d006`，01-07物化7473926/run `63ab4d83-0d13-47bf-ba68-66379274a9db`。完整范围预览4,267新物化、4,267真实check runs、17,068检查，业务事件合计21,335；随后同计划续跑，已验证日期跳过。完整阶段随后完成，收尾证据如下。

当前workspace没有ASSET/MULTI_ASSET/AUTOMATION类型的事件sensor。因子和日线/分钟日常入口只检查最近10交易日，变化历史截止7月29日不在窗口内；日线factor repair监听`gold_stock_daily_qfq_update_job`成功，检查子集仍使用`silver_adj_factor_update_job`身份，不匹配该触发者。执行前和S3中只读确认没有在跑因子/生命周期writer；未启停服务或sensor、未清cursor或旧事件。

本段所有Lake写入仅在复权因子Silver路径；Raw和Prod零写入，25股因子值修正、行情、技术指标和state均未推进。7月29日以后的48份既有Silver未因历史迁移重写。


**S4和本段收尾已完成。** 正式事件全范围耗时3,048.89秒（约50.8分钟），峰值RSS678.2MiB。独立只读SQL核对：4,267个run全部`SUCCESS`，4项检查各4,267条，共17,068条`SUCCEEDED`；每项检查的`materialization_event_storage_id`均等于对应日期本批新物化，错误绑定0。4,267条新物化均实际存在，检查run中的asset物化0，即零asset执行。首次物化7473870/run `8475db4f-641a-4361-bb72-254bbbdf4caa`；末次2026-07-29物化7593820/run `4f1dadc4-5012-4901-8ba9-1ebd0bd39542`。

收尾仅读取控制面和文件指纹，不再次计算历史expected：全部4,315 Raw输入、名单及本段源码强指纹未变；4,267变化Silver等于已审计候选，48不变文件的内容和mtime均保持原样；最终Silver4,315文件/14,416,884行。事件记录全部`checks_verified=true`，无待恢复或失败日期。初次只读收尾脚本误用`status`字段，按实际`execution_status`修正后通过，没有正式写入或任务失败。

本次代码、文档和正式文件规则一致，复权因子Silver当前上市TODO已完成。候选与逐文件记录仅为本次受控操作的staging，不进入日常更新；没有永久reports依赖、自动全历史扫描或新的注册job。正式S3后做一次完整数据对账；S4小样本和正式事件启动时旧入口各复核了一次文件关系，收尾不重复业务集合计算，日常仍仅校验本次日期。原25股值修正及所有下游重算保持待执行，不扩展此次范围。

<a id="factor-downstream-repair-readiness-20261013"></a>

## 19. 25股下游修复的最新实施设计与审计（2026-10-13）

本节覆盖§12、§15.6中的旧待办与旧预算数量；不覆盖§18已经完成的独立Silver规则迁移。当前范围是上位方案§2.2的25股/2,489键及§17已经批准的688689日线扩展；Prod保持现状。本轮只更新文档，不改代码、不创建候选或可执行计划、不写正式Lake/数据库/Dagster事件。

### 19.1 输入、代码和文件现状

| 核验对象 | 10月13日晚只读结果 | 能证明及不能证明的内容 |
| --- | --- | --- |
| 当前源及DG因子 | 25个区间请求/2,489唯一键；Raw/Silver同键存在且相同，全部仍为非舍入差异；351日/702文件；37,125,373字节 | 集合仍待修，当前Silver规则未阻断；未执行因子数值修正 |
| 当前基准 | 25股×10月12、13日共50键，源与Silver一致，两日值相同 | 当前基准无新漂移；执行前仍重新核验 |
| 日线完整既有序列 | 66,439行；源价/因子缺记录0；仅覆盖批准因子源值后仍有688689的1,299根OHLC差异 | 2021-01-27—2026-06-11批准例外仍需要修，其他24股未发现新增混基准范围；不是全链候选验收 |
| 分钟递推入口 | 175个精确上一expected日seed，1,400根前序实际bar；版本/参数/有限数值/last_trade_time合法 | 七频入口可用；仍须证明从修正价格重放后的结果/state正确 |
| 基础实现 | `stock_adj_factor_history_repair.py`有范围/source校验；`stock_adj_factor_history_repair_candidates.py`有受控合并/保留行比较；MACD/KDJ已有公开prepare计算核 | 部分本地实现存在；CLI、各资产适配、冻结/提升/事件及完整资源恢复验收未完成，不能直接执行正式修复 |

当前上市集合包括本批全部25股，因子351日按现行Raw/Silver正式检查语义通过；不再把已退市股票Silver无因子列为本次缺口。临时源值仅用于只读比较，未写正式因子；最大额外日线OHLC差0.3028863097、close差0.2969191202。基准审核应使用批准源值覆盖后的公式结果：旧因子比较的1,306条异常包含7条原因子日期，不能将其误写成新增1,306条混基准范围。

### 19.2 末端冻结合同

| 资产族 | 25股各自既有末端快照 | plan冻结字段与范围 |
| --- | --- | --- |
| 日线QFQ | 2026-10-13 | `price_end_trade_date`；批准因子日期及实际后继，另含688689自2021-01-27的基准修复；只合并不同键 |
| 日趋势结果/state、日九转 | 各为2026-10-13 | `result_end_time`/`state_end_date`分别记录，首次受影响输入到各自末端；688689起点2021-01-27 |
| 分钟QFQ七频 | 各为2026-10-13 15:00 | 每股/频率`price_end_time`；修价日期仍是批准因子影响集合，不重写区间外价格 |
| MACD/KDJ七频结果 | 各为2026-10-12 15:00 | 每股/频率`result_end_time`；日首起算至既有结果覆盖，区间后价格参与递推 |
| MACD/KDJ七频每日state | 各为2026-10-12 | 每股/频率`state_end_date`和expected日期集合；停牌日沿用state，不补bar |
| 分钟九转四频 | 各为2026-10-13 | 每股/频率既有结果末端；完整历史上下文输入后，只合并真实差异 |

这些是审计快照，不是CLI默认值。`StockFactorAnchor`记录基准，另在plan的逐资产范围中保存：代码、资产、频率、首次变化输入/计算起点、价格/结果/state各自末端、expected日期、精确上一expected日、seed最后bar时间、前序context键及文件身份。缺已有覆盖、没有实际变化或全链no-op都须显式分类；不生成未来日期/缺失bar/state。

执行顺序：先只读确认正常日更是否已追齐，列出相关排队/活动writer和sensor；在获准维护窗口暂停/排空所有相关写入者后，重新核验并冻结计划。构建与提升前核验全部输入/目标/当前基准；后续正常日更产生新末端即重新冻结，不追加到旧计划，不绕过preimage漂移。无活动run但sensor仍RUNNING时不能认定独占成立。不同资产末端允许不同，不一律截到12日，也不因价格已有13日而人工补13日MACD覆盖。后者只能等正常链完成后重新冻结。

10月13日价格日更run `0990c73b-aa1f-42ca-beaf-505600b569ad`于19:40:11 +08成功，因子repair run `b90e787f-5930-4707-b238-782b1221077b`于19:48:03 +08成功。只读时run-status sensor cursor已经过前者SUCCESS storage id 7560542，尚未经过后者7579933，约有567条SUCCESS记录待过滤；sensor正常推进且无失败。当前storage的job-name过滤能力为false，本地Dagster 1.13.26默认每次fetch 25条、处理5条，全局无关SUCCESS也参与翻页。此前4,267个检查任务会拖慢该处理。该观察解释分钟指标末端落后，不授权跳cursor、加大全局环境参数、更换storage、升级依赖或手工重算新的13日覆盖。

### 19.3 事件入口设计（单一手动job例外已确认，待实现）

**边界确认（2026-10-13）。** 管理员已同意增加一个手动检查补录任务，§2据此只开放这个例外。原来禁止新增job；现有`gold_stock_daily_qfq_check_refresh_job`和`gold_stk_mins_qfq_macd_kdj_check_refresh_job`只覆盖部分资产。`silver_adj_factor_rebuild_check_job`证明check-only subset可零asset执行，但逐日真实run的成本已测得约51分钟。使用分钟价格日更或MACD日更job的名字执行check-only subset，其SUCCESS仍会进入现有run-status消费者；即使暂停sensor，恢复后记录依然存在。因此不能借普通更新job的成功记录补录本次历史检查。

已确认的设计仅增加一个手动`stock_adj_factor_history_repair_check_events_job`，每批登记多个已验收分区的检查并绑定本次物化；不执行asset、不计算行情、不写Lake、不自动调度。不增加asset、check身份、自动job、sensor或永久状态实体，不改变普通job/config。**本确认只解除§2的入口设计限制，不表示实现、隔离性能或正式事件执行已完成；本轮仍只改文档，R5继续按既定门禁验收并取得正式执行授权。** 它沿用已实现的周线`report_stock_weekly_bootstrap_checks`/`apply_weekly_events`模式，在真实`OpExecutionContext`中登记同批多个分区检查；不得复用周线B0专用配置/身份或创建伪造run。

拟职责放在本专项现有bootstrap模块，新增job/ops/typed run config仅承载这个手动检查阶段，按现行目录装配；冻结计划是唯一范围来源，默认无schedule/sensor触发。CLI只顺序执行已批准批次，记录每批真实run ID和结果，未完成批次才续跑。逐分区数据检查先由共享纯校验核按资产/频率/月聚合完成，登记任务不重复计算行情或扫描整段历史。

| 配置/执行事实 | 默认或来源 | 消费者、生效和可见性 |
| --- | --- | --- |
| plan_path、expected_plan_hash、instance identity | 必填，已验收staging计划及当前正式instance；不从reports读取 | CLI、手动op、查重/读回；批前核验，错instance/hash拒绝 |
| event batch start/count | 必填，冻结排序后的事件条目范围 | CLI→typed job config；运营可见阶段/范围/完成量，重试不得扩大 |
| event_write_batch | 拟100条业务事件/批，参考既有WeeklyBudget的100条上限；最终按隔离样本可缩小，不增大 | 统一专项budget→plan；物化CLI和真实check job共同约束；依赖RSS/启动/写入耗时实测，所有默认只定义一处 |
| materialization/check IDs、run IDs | 正式读回，staging逐条完成记录 | 幂等/错误绑定检查；不是输入授权，不允许伪造 |

100条是写入上限，不是100个日期，也不是总Dagster日志预算。mat及checks分阶段、按资产/日期稳定排序，每批任务只登记不超过上限的check evaluations；先3个分区隔离样本，再最多100条的代表批次测吞吐。单批保持30秒内业务进度，超限拆小批。只允许当前完整正式检查通过的资产/分区；原全市场检查没有通过，不报告它为passed，停止该部分事件阶段并列出原因，不扩大修数值范围。

事件算法和恢复：

1. `events-preview`从已审计变化行映射分区，分别列物化、检查、只复验旧物化、当前失败、无变化跳过。年度合并文件只登记真正有变化的日期。列明全部check名称、已有物化/检查ID、实际行数/路径/哈希及消费者，冻结`event_plan_hash`；原20,586/41,907事件不是当前数量。
2. 正式文件一次完整业务对账通过后，事件启动核验文件身份和校验摘要；按实际文件路径去重，必要的强指纹不在每条check重算。物化CLI只登记真实变化的资产/分区，使用现行metadata helper的uri、row_count、observed_columns及本次人工plan/hash，不冒充自动batch/completion/B0。登记后读回并保存精确storage id。
3. 检查op确认真实run存在、STARTED且job身份正确。读取本批已通过的完整检查证据及现行文件身份；每个`AssetCheckEvaluation`保持原asset/check/partition身份和blocking/severity，明确填写`target_materialization_data`的storage id/run id/timestamp。通过`instance.report_dagster_event(..., run_id=context.run_id)`登记，禁止用无运行检查重复撞旧记录或自行造UUID/run终态。当前1.13.26接口和多分区字段已在现行周线链使用；本专项仍须隔离验证同asset/check多个partition在同run的数据库唯一性及读回，不能仅凭API字段证明兼容。
4. 每条登记后按asset/check/partition/本批物化ID有界读回，验证passed、plan/hash、run及target绑定，先记written状态；CLI在真实run进入SUCCESS后读回并将本批记为verified。取消/失败保留已登记记录，不当作成功批。重试只跳过绑定正确且来源run已SUCCESS的检查；失败run的记录保留，并在新的真实续跑run内重新登记所需检查。事件已写而checkpoint丢失时先查询来源run及正式事实，不重复成功记录、不只信checkpoint；外部新物化或文件漂移拒绝。
5. 最终聚合核对本批实际物化、checks、成功/失败真实runs、错绑定0、同一run内重复登记0、asset执行0、Lake写入0及少量近期readiness。以每个预期asset/check/partition及对应物化最新的成功run检查核对完成数；失败/取消run的旧检查不删除、不算本批成功完成，也不篡改旧终态。合法失败续跑产生的历史检查另计，不将它误判成重复业务修复。不同物化的合法历史记录保留。

普通run-status sensor不监听该拟手动job，且不伪造自动repair completion；新手动run仍会形成全局SUCCESS记录，因此批次合并只能减少这项成本，不能声称完全没有影响。隔离检查现有run-status、asset事件、physical readiness及serving消费者；正式小样本后核对无额外日更/repair请求。自动链恢复保持原cursor自然追赶，核对13日及后续实际expected日结果/state。若未追齐，记录等待，不将事件成功等同于自动任务成功。

依据：当前周线真实补录实现、`adj_factor_silver_history.py`check-only运行、现行job/sensor定义、本地Dagster1.13.26的事件存储和run-status源码；[官方asset checks说明](https://docs.dagster.io/guides/test/asset-checks)与[execution API](https://docs.dagster.io/api/dagster/execution)只提供基础语义，不能代替本专项绑定/唯一性隔离验收。不改变现行检查到preview分区check API、不迁移Dagster库。

### 19.4 性能测量与放行顺序

| 已完成测量 | 耗时/峰值 | 适用限制 |
| --- | --- | --- |
| 351日因子键/规则核验 | 2.363秒/524.55MiB | 只读，不是候选/提升 |
| 25股日线完整序列加批准因子值比较 | 3.716秒/251.34MiB | 只读确认688689范围，未生成完整文件 |
| 七频精确seed/context分别新进程读取 | 每频0.304—0.553秒/225.47—335.22MiB | 输入可用性，不是整段指标重算 |
| 已完成Silver规则迁移事件 | 3,048.89秒/678.2MiB，4,267真实runs/17,068checks | 证明逐日启动成本和全局事件影响；不能线性套用为本次总耗时 |

日线2021-01-27—2026-10-13的保守全文件库存：价格、趋势结果、state、九转各1,380文件；压缩字节分别472,629,271、413,756,618、261,851,567、40,966,827，合计1,189,204,283。这是保留行库存，不代表全部需要生成候选。原13,005文件/2,275,681,341字节不含批准扩展和新末端；当前精确目标并集、候选字节、事件数均待完整freeze/候选确认，不把两次库存相加重复计算。约2.66TiB空闲及同文件系统只证明空间可用，不证明10GiB候选门禁已通过。

按§3.3和§16.2原预算执行，父进程加当前子进程RSS合计不超过1GiB，DuckDB512MiB/2线程/最多2GiB spill，全部全市场候选合计最多10GiB，单股计算片段最多100,000行，30秒内业务进度。不同阶段顺序启动/退出子进程，编排只持有小索引及逐文件记录，不保留完整bar/footer。共享目标文件汇总所有批准股票后只合并一次；保留行COPY不受单股十万行约束，但仍受内存、spill及完整文件空间门禁。

| 门禁 | 必须测的规模/流程 | 通过条件与下一步 |
| --- | --- | --- |
| R0冻结前 | 最新源键/基准/逐资产末端，writer排空，完整输入/目标路径并集、保留行/最大文件、逻辑变化分区/check/run数 | 来源/范围无额外漂移；库存不是候选量；给出暂存输入+中间输出+候选+spill同时存留峰值及20%余量 |
| R1/R2小样本 | 大变化股、688689的2021年起日价/趋势/state/九转、最长1m、跨年七频及多股共享全市场文件 | 原公式和校验核、量额不变、范围外逐字段不变；完整合并和校验，不只25股输出 |
| R3隔离恢复 | 同一冻结范围连续多个年度/阶段、取消与进程退出、COPY/replace/checkpoint失败、重复续跑 | 计算阶段峰值和跨阶段RSS均通过；已完成文件不重写，目标漂移拒绝；失败不正式提升 |
| 全量候选放行 | 25股因子→日线/七频价格→全部结果/state/九转候选→完整审计 | 实测全流程扫描/写入/保留行、计算及实际差异行、候选/跳过文件/总字节、hash/fsync时间、RSS/spill；通过后才申请R4正式提升 |
| 事件实现放行 | 隔离3分区及100条上限代表批次；多日期同check、已有旧检查、错target、崩溃续跑、末端消费者 | 正确绑定/幂等、零asset/Lake执行；测任务数/启动成本、每秒业务事件及总日志、读回/UI/sensor处理耗时，给出冻结全量估计 |
| R4/R5正式小样本及收尾 | 逐文件提升和一次完整正式对账；批准后事件小样本/完整批次；存活reader与新请求、下一expected日隔离续算 | 不假设已有全量性能通过；确认实际新seed与结果/state、事件及普通调度均正确后关闭维护窗口 |

事件check复用已完成的完整语义审计，不逐partition启动全市场重扫描；正式对账完成后只核验本批文件身份及事件读回，日常没有plan/reports依赖。事件任务耗时估计必须包含真实run启动和生命周期日志，run-status追赶测cursor覆盖到真实最新上游SUCCESS及是否出现多余任务，不只显示sensor RUNNING。未测全链、任务吞吐或恢复，不承诺预计完成时刻；超限先减少重复扫描/物化、拆计算片段或事件批次，不提高原预算。

### 19.5 本轮文档审计与下一步

CodeGraph explore用于周线真实检查补录调用链，结合当前源码核对因子check-only subset、七频价格/指标及日线/九转job、run-status消费者。发现并纠正：文首仍写Silver文件未迁移、基础实现全部不存在；统一10月12日末端；旧688689“不重写日指标”；扩展前文件/事件数量仍被当作当前预算；事件登记没有真实任务/消费者和资源验收设计。历史证据保留并标明适用日期，不把文档审计或只读通过称作正式修复完成。

下一步先完成完整R0冻结与R1/R2各资产候选适配，再做R3隔离资源/恢复验收，完整候选通过后才执行获准R4。事件入口的§2单一手动job例外已确认，后续仍须隔离唯一性/绑定/性能通过后才能部署和申请R5；现有Silver规则、Prod、普通job/sensor合同、API、schema和子系统依赖矩阵均不变。技术设计只有必要的一次性手动入口，不增加全市场因子同步、退市补因子、新指标覆盖、自动历史扫描或永久审计表。
