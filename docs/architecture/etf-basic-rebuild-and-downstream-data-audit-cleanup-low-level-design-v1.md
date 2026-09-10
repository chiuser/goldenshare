# ETF 基础信息重建与下游身份治理 LLD

更新：2026-09-10（代码对账与文档合并）。创建：2026-08-28。
业务决策唯一入口：[D1–D20 主方案](./etf-basic-rebuild-and-downstream-data-audit-cleanup-plan-v1.md)。
本文保留现行实现与带日期历史证据；原 ETF 激活池两份历史文档的独有信息已并入 §11–13。

状态：代码已完成 P0–P12，旧 alignment Submit 已删除。**生产证据截至 2026-08-29**：Basic、旧池 drop、分钟指定区间、SH 申赎、fund daily 已验；当时 SZ 自然调度和 ETF 实时开市批次待验。本轮未核实后来运行情况，不宣称今天仍未运行、开放任务仍为零或整体已结案。

## 1. 阅读入口与保留教训

- 当前契约：§3–9；分钟操作转到 §10 的单一维护入口；退场事实与保护范围：§11–12。
- 历史施工和生产流水：§13，含部分提交、设计纠偏和真实部署先后，**不是可再次执行的命令/授权清单**。
- 回归入口与验收判据：§14–15；新的变更须重新核实消费者和源端合同。

原 LLD 的错误设计已撤销：不得先删 DAO 再迁移消费者；不得给已有 DAO 重复装配；候选 count/page 两条 SQL 不等于重复业务资格；不新增无消费者的 master_data policy、伪 resource、全局诊断或专用 TaskRun；不能把删除 manifest 与只读 alignment_plan 混同，也不能靠全历史/逐空日补拉猜分钟完整性。当前态 Basic 无法还原历史资格，计划 hash 不应把无关展示字段当作请求身份；请求数量不能直接推导真实墙钟耗时。P9B 的“一 action 一 TaskRun”已在实际停止后撤销，执行改用普通多代码任务。

## 2. 历史审计基线（2026-08-28）

以下源端、数据库及 Alembic 结果仅对应当时审计，不是 2026-09-10 的实测。旧实现已被 §3–9 替换，代码图规模和中间阶段“待删除”状态不再维护第二份当前账本。



### 2.1 当时的 Tushare 契约复核

当时复核的本地源文档为：

```text
docs/sources/tushare/ETF专题/0385_ETF基础信息.md
docs/sources/tushare/ETF专题/0387_ETF历史分钟行情.md
docs/sources/tushare/ETF专题/0407_ETF申赎清单.md
docs/sources/tushare/ETF专题/0471_ETF每日持仓组合(沪市）.md
docs/sources/tushare/ETF专题/0472_ETF每日持仓组合(深市）.md
docs/sources/tushare/ETF专题/0127_ETF日线行情.md
docs/sources/tushare/ETF专题/0199_基金复权因子.md
docs/sources/tushare/ETF专题/0408_ETF份额规模.md
docs/sources/tushare/ETF专题/0400_ETF实时日线.md
```

已确认：

1. `etf_basic` 支持 `limit/offset`，单页上限 5,000，当前 DatasetDefinition 的 14 个字段与源契约一致。
2. `etf_mins` 要求代码和频率，支持区间与 `limit/offset`；当前 `page_limit=8000`、每 unit 上限 24,000 行。
3. `fund_daily/fund_adj` 不传 `ts_code` 时是按交易日全市场请求，返回范围比 `etf_basic` 更宽。
4. `etf_share_size` 是按日期全市场接口；它的 raw 与业务使用口径相同。
5. `rt_etf_k` 当前固定通配符请求不需要 ETF 代码 fan-out。

当时还使用 Tushare MCP 对 `510300.SH` 显式请求 14 个 `etf_basic` 字段，返回当前 `L` 状态、`setup_date=20120504`、`list_date=20120528` 和 `exchange=SH`，验证了关键字段仍可由当前源端显式返回。行数快照不固化为永久代码门禁。

### 2.2 当时的 Alembic 基线

2026-08-28 LLD 编写时的只读检查结果：

```text
heads   = 20260828_000155
current = 20260828_000155
文件     = alembic/versions/20260828_000155_make_suspend_d_raw_view.py
```

P0 复核期间，当前分支合入了本需求范围外的 `20260828_000156_make_stk_auction_o_raw_view.py`，实际结果变为：

```text
heads   = 20260828_000156
current = 20260828_000155
000156 down_revision = 20260828_000155
```

P0 没有修改或执行该迁移。当时代码端仍是唯一 head，但连接数据库落后一个版本；`heads != current` 触发了开发停止门禁。

2026-08-28 P1 恢复前重新实测：

```text
heads   = 20260828_000156
current = 20260828_000156
```

唯一 head/current 已对齐，P1 停止门禁解除。P1 未新增 Alembic 迁移；之后 P8 的 drop migration 接到 000156，见 §12；新的迁移仍须重查实际 head。

### 2.3 当时的下游清理范围

2026-08-28 使用当前 Tushare ETF Basic 全量结果对 Prod 做了受控只读审计。当前源端共有 1,825 行 ETF Basic，其中按本设计在当日可请求的 `.SH/.SZ` ETF 为 1,647 个；另有 1 个未来上市的 `L` 和 8 个 `L + list_date 为空`，均不进入可请求集合。

| 对象 | 当前规模 | 非 `.SH/.SZ` | 不在当前源端 ETF Basic | 交易所身份冲突 | 已批准删除候选 |
|---|---:|---:|---:|---:|---:|
| `raw_tushare.etf_minute_bar` | 约 6,584 万行，1,395 个代码 | 0 | 0 | 0 | 0 |
| `raw_tushare.etf_sh_cons` | 5,675,323 行，803 个代码 | 0 | 0 | 0 | 0 |
| `raw_tushare.etf_sz_cons` | 11,567,504 行，720 个代码 | 0 | 0 | 0 | 0 |
| `core_serving.fund_daily_bar` | 1,180,869 行，1,395 个代码 | 0 | 0 | 0 | 0 |
| `ops.etf_realtime_monitor_pool` | 3 行 | - | 0 个无效配置 | - | 0 |
| `ops.etf_realtime_monitor_rule` | 0 条 ETF 规则 | - | 0 | - | 0 |

`core_serving.fund_daily_bar` 有 2,091 行、3 个代码的事实日期早于**当前** `list_date`：`159908.SZ` 624 行、`511220.SH` 805 行、`512990.SH` 662 行。它们符合“上市日后移或代码复用无法从当前态主数据判明”的保留边界，只报告、不删除。ETF 分钟表同类候选为 0。

因此本 LLD 不再设计通用事实清理实现。Basic 重建后只复跑相同只读统计；若明确旧 `.OF` 身份仍为 0，本阶段无操作结束。若意外非零，停止并另立精确一次性方案。


## 3. 工程设计决策

| 编号 | 已落定设计 | 原因 |
|---|---|---|
| E1 | `EtfBasicDAO` 提供统一主数据/当前可请求查询；所有消费者调用它 | 消灭各下游自行拼状态、后缀和日期条件 |
| E2 | 正式 `etf_basic maintain` 删除所有业务过滤输入 | 防止部分源结果覆盖完整快照 |
| E3 | 新增 `raw_etf_basic_snapshot_replace` 专用 write path | 通用 upsert 不具备删除缺失主键的快照语义 |
| E4 | 快照先完整拉取和校验，再在一个事务中替换 raw/serving | 源失败不触碰旧数据；raw/serving 不出现跨版本 |
| E5 | `fund_daily` 使用 `raw_then_serving` 两阶段提交策略 | raw 是源端事实，不能因 ETF serving 选择器失败而丢失 |
| E6 | `fund_daily/fund_adj/etf_share_size` 现有显式 `ts_code` 入口保留，但只视为对应源接口的人工探测/修复；Basic 不用它们扇出请求 | 保持现有单代码运维能力，同时避免把它误当成 ETF 自动同步主链 |
| E7 | `etf_mins/sh_cons/sz_cons` 保留现有 `universe_policy='pool'` 对象展开形状，只把 source 改为 `core_serving_etf_basic` | 避免新增无必要的共享 policy 或伪 resource；持久化激活池由 source 类型决定，不由这个通用字段名决定 |
| E8 | 上市日裁剪必须早于切窗；自动计划的空窗口不生成 unit，显式请求越界直接报结构化错误 | 不向源端发上市日之前的无效请求，不为无消费者的自动跳过数量扩展共享计划或 Ops 契约 |
| E9 | health 改名为 `eligible_etf_count/eligible_snapshot_count`，候选接口改为 `/eligible-etfs` | 表退场后不再传播“激活池”概念；不留旧字段别名 |
| E10 | 不新增通用下游事实清理 CLI、service、删除 manifest 或 apply；旧 `fund_daily` cleanup 与 CLI 直接删除 | 当前已批准删除候选为 0，避免为零规模问题建设长期删除系统 |
| E11 | 激活池 migration 的 downgrade 明确不可逆 | 不允许降级时重建一个无事实依据的空池或旧池 |
| E12 | 分钟全量对齐只生成正式 TaskRun，不直接调用 connector 或 writer | 保留正式分页、限流、归一化、幂等和观测链 |
| E13 | P9A Preview 保留为只读覆盖审计；执行使用普通手动任务 | 先证明真实代码和请求量，再复用正式数据集主链，不建设一次性写入口 |
| E14 | `etf_mins.ts_code` 支持多值，但多代码解析只放宽 ETF 分钟 planner | 满足一次 TaskRun 扇开多个代码，同时保护沪深申赎清单的单代码契约和共享运行时 |

### 3.1 没有新增配置项

本设计不新增 env、Settings、数据库配置或运营页面开关：

| 事项 | 来源 | 生效方式 | 消费者 |
|---|---|---|---|
| ETF 分钟频率窗口 | 现有 `ETF_MINS_RANGE_WINDOW_MONTHS` | 代码发布 | unit planner、对齐预览 |
| `page_limit=8000`、unit 上限 24,000 | 现有 DatasetDefinition | 代码发布 | source client、额度预览 |
| 当前可请求日期 | 调用方在一次查询、规划或发布开始时显式计算中国时区自然日 | 对应调用生命周期内固定 | Basic DAO selector |
| P9A Prod 查询超时 | CLI handler 内的 `SET LOCAL statement_timeout='180s'`；不进入 env/Settings/数据库配置 | CLI 为本次事务设置单语句上限，超时则命令失败；service 不自行设置 | 只读 alignment preview |

P9A 的 180 秒是基于最大月分区只读试算得到的单语句 fail-closed 上限，不是业务参数，也不允许页面或 CLI 覆盖。它不表示整个 preview 只能运行 180 秒；每个自然月是一条独立受限语句。若实施阶段再提出其他阈值、自动周度回退、开关或持久化路径，必须另做配置项审计，不能把它偷偷写成页面常量或脚本常量。

---

## 4. ETF Basic 统一查询契约

### 4.1 值对象与统计口径

在 `src/foundation/dao/etf_basic_dao.py` 定义不可变值对象：

```python
@dataclass(frozen=True, slots=True)
class EtfRequestTarget:
    ts_code: str
    list_date: date
    exchange: Literal["SH", "SZ"]

@dataclass(frozen=True, slots=True)
class EtfRequestabilitySnapshot:
    as_of_date: date
    exchange: Literal["SH", "SZ"] | None
    targets: tuple[EtfRequestTarget, ...]
    serving_row_count: int
    requestable_count: int
    excluded_reason_counts: Mapping[str, int]
```

`EtfRequestTarget` 不携带 `list_status`，因为能返回该对象本身就表示已满足 `L`。`list_date` 和 `exchange` 均不可空，从类型层阻止调用方忘记上市日或再次猜交易所。

snapshot 的排除原因使用固定优先级，保证一行只能进入一个分类：

```text
NON_EXCHANGE_SUFFIX
-> EXCHANGE_MISMATCH
-> STATUS_NOT_LISTED
-> LIST_DATE_NULL
-> LIST_DATE_AFTER_AS_OF
-> REQUESTABLE
```

全市场 snapshot 对 serving 全表分类，因此生产重建前残留的 `.OF` 会进入 `NON_EXCHANGE_SUFFIX`，绝不能成为 target。传 `exchange='SH'/'SZ'` 时，统计作用域只包含该规范后缀；另一交易所不算排除项。

### 4.2 DAO 公共方法

删除语义错误且无运行时消费者的旧方法：

```python
get_active_etfs()
get_fund_daily_candidates()
```

新增且只新增：

```python
load_requestability_snapshot(
    *,
    as_of_date: date,
    exchange: Literal["SH", "SZ"] | None = None,
) -> EtfRequestabilitySnapshot

get_requestable_target(
    *,
    ts_code: str,
    as_of_date: date,
    exchange: Literal["SH", "SZ"] | None = None,
) -> EtfRequestTarget | None

requestable_targets_subquery(
    *,
    as_of_date: date,
    exchange: Literal["SH", "SZ"] | None = None,
)
```

不新增无实际消费者的 `list_master_rows()`。审计用 snapshot 统计或受控 SQL，不能为了“以后可能用”扩大 DAO 契约。

资格规则集中在 DAO，但不是三个方法都调用同一 SQL builder：

| 方法/辅助函数 | 实际职责 |
| --- | --- |
| `load_requestability_snapshot()` | 读取 scoped 主数据，用 `_classify_master_row()` 决定 targets 和互斥排除计数 |
| `get_requestable_target()`、`requestable_targets_subquery()` | 使用 `_requestable_predicates()` 生成 SQL 资格条件 |
| `_normalize_exchange()` | 规范化后只接受 None/SH/SZ，否则 ValueError |
| `_normalize_ts_code()` | 单 target 的代码 strip/upper 与后缀检查 |

内存分类和 SQL 筛选必须由 DAO 测试证明口径一致；不得声称 classifier 只做统计、不决定资格。

`requestable_targets_subquery()` 固定暴露以下列，供 Ops 分页 join：

```text
ts_code, list_date, exchange, csname, extname, cname, etf_type, list_status
```

其中 `list_status` 对返回行恒为 `L`，保留它只是避免当前监控候选 DTO 再次 join Basic。Ops 不得在 subquery 外复制状态、后缀或上市日条件。

当前 `DAOFactory` 已经暴露 `etf_basic`，P2 不修改该装配。`DAOFactory.etf_series_active` 在 P2 仍保留，直到 P3-P7 的所有消费者迁移并通过零引用门禁后，才在 P8 删除。

### 4.3 唯一资格条件

```text
list_status = 'L'
AND list_date IS NOT NULL
AND list_date <= :as_of_date
AND (
  (ts_code LIKE '%.SH' AND exchange = 'SH')
  OR
  (ts_code LIKE '%.SZ' AND exchange = 'SZ')
)
```

SQL 中后缀组合必须整体加括号。传 `exchange='SH'` 时只保留第一支，传 `exchange='SZ'` 时只保留第二支。结果按 `ts_code` 排序。raw 中的 `.OF` 不会通过该 DAO 进入下游。

### 4.4 读取时点与调用日期

固定一次 `as_of_date` 不等于所有消费者共用全局数据库快照；下表约束各自调用生命周期。

“动态读取当前可请求 ETF”不是每天生成一个新池，也不是每发一个 Tushare 请求都查询一次数据库。各消费者按一次业务生命周期固定资格结果：

| 消费者 | 读取时点 | 本次结果使用范围 |
|---|---|---|
| `etf_mins/etf_sh_cons/etf_sz_cons` 自动 planner | 一次 `DatasetUnitPlanner.plan()` 开始时 | 调用一次对应交易所作用域的 snapshot；同一次 plan 的代码、裁剪和切窗复用 targets |
| `etf_mins/etf_sh_cons/etf_sz_cons` 显式单代码 planner | 一次 `DatasetUnitPlanner.plan()` 开始时 | 只调用一次 `get_requestable_target()`；不为单代码请求加载全市场 snapshot |
| `etf_mins` 显式多代码 planner | 一次 `DatasetUnitPlanner.plan()` 开始时 | 调用一次全市场 snapshot，在内存中校验全部输入并复用 target map；不逐代码查询 |
| `fund_daily` serving 发布 | 一次 serving phase 开始时 | 调用一次 snapshot；本批全部行复用 `ts_code -> target` map |
| `etf_rt_daily` Health | 每次 Health API 查询开始时 | 调用一次 snapshot；本次响应复用 target codes |
| 实时监控候选列表 | 每次 `/eligible-etfs` API 请求开始时 | 固定一个 `as_of_date` 并构造一次 subquery；允许 count 与 page 两条 SQL |
| 实时监控运行时 | 每次 `run_after_etf_batch()` 开始时 | 调用一次 snapshot；本批规则和告警复用 target codes |
| ETF 分钟对齐 preview | 每次 preview 开始时 | 内部计算一次当前中国日期并调用一次全市场 snapshot；本次全量计划固定 targets |

“一次读取”指一次业务生命周期只解析一次资格口径，不是所有接口只能执行一条 SQL。禁止的是在逐代码、逐 unit、逐指标、逐规则或分页结果循环里重复查 Basic。

每个调用者只计算一次 `as_of_date = datetime.now(ZoneInfo("Asia/Shanghai")).date()` 并显式传给 DAO。长任务跨过自然日零点也不在中途换集合；下一次任务重新读取。

读取结果只按已有消费者需要输出，不再统一要求“写入诊断 JSON”：

1. planner 只在实际生成的 unit `progress_context` 中写当前 target 的 `eligibility_as_of/master_list_date/requested_start_date/effective_start_date`；不持久化全市场汇总统计，不扩展 `DatasetExecutionPlan`、TaskRun 或 Ops 契约。
2. `fund_daily` 因存在 raw 已提交、serving 失败的业务边界，只把第 7.4 节规定的分层持久化结果写入现有 ingestion diagnostics。
3. Health 只返回现有页面消费的 `eligible_etf_count/eligible_snapshot_count`，不写 TaskRun。
4. monitor runtime 只把本批处理结果返回 collector 日志；空资格集合用 `skipped` 与明确 message 表达，不新增计数字段或持久化诊断。

---

## 5. `etf_basic` 完整快照发布

### 5.1 DatasetDefinition 修改

文件：`src/foundation/datasets/definitions/reference_master.py`

目标值：

| 字段 | 目标 |
|---|---|
| `input_model.filters` | 空元组 |
| `request_builder_key` | `_etf_basic_snapshot_params` |
| `write_path` | `raw_etf_basic_snapshot_replace` |
| `reject_policy` | `fail_unit_on_any_rejection` |
| `batch_unique_key_fields` | `('ts_code',)` |
| `source_multiplicity_policy` | `reject` |
| `empty_result_policy` | `fail_unit` |
| `pre_write_validator_key` | `etf_basic_snapshot` |
| `page_processing_mode` | `buffer_all`，必须先拿到完整分页批次再开数据库事务 |
| `transaction.commit_policy` | `unit`，保持单业务事务 |
| `idempotent_write_required` | `True` |

`_etf_basic_snapshot_params()` 必须拒绝请求中残留的 `ts_code/index_code/exchange/mgr/list_status/list_date`，并始终返回空业务参数。旧 `_etf_basic_params()` 删除，不留探测型正式写入口。

如果以后确实需要源端筛选探测，应放在只读 probe 能力中，不能复用 Dataset maintain 和正式 writer。

### 5.2 发布前校验器

新增纯函数模块：

```text
src/foundation/ingestion/etf_basic_snapshot.py
```

职责仅包括：

1. 校验非空、主键唯一、源端行数等于归一化行数。
2. 校验 `list_status` 只出现 `L/P/D`。
3. 校验后缀只出现 `.SH/.SZ/.OF`。
4. 校验 `.SH -> exchange=SH`、`.SZ -> exchange=SZ`；`.OF` 不强制伪造交易所。
5. 统计各状态下 `list_date` 为空数量，但不因此拒绝 raw。
6. 以 14 个业务字段计算规范化 hash 和变更摘要。

规范化规则：

```text
按 ts_code 排序
日期转 YYYY-MM-DD 或 null
Decimal/数值转不含科学计数法的规范字符串或 null
字符串保留源端语义，只将数据库 null 统一为 JSON null
JSON 使用 UTF-8、固定字段顺序、无多余空白
SHA-256 计算内容 hash
```

不得把 `api_name/fetched_at/raw_payload/created_at/updated_at` 纳入 hash，否则相同业务快照每天都会产生伪变化。

### 5.3 writer 事务

`DatasetWriter.write()` 新增精确 dispatch：

```python
if definition.storage.write_path == "raw_etf_basic_snapshot_replace":
    return self._write_etf_basic_snapshot_replace(...)
```

事务内顺序：

```text
1. SELECT pg_advisory_xact_lock(稳定的 etf_basic snapshot lock key)
2. 读取旧 raw/serving 的业务字段，计算 before hash 与 diff
3. DELETE raw_tushare.etf_basic
4. INSERT 完整已校验 raw rows
5. DELETE core_serving.etf_basic
6. INSERT 本批次中仅 .SH/.SZ 的业务字段
7. flush
8. 对账 raw 主键集合 = 源批次主键集合
9. 对账 serving 主键集合 = 源批次中 .SH/.SZ 主键集合
10. 对账 raw 业务 hash = 完整源批次 hash，serving 业务 hash = 源批次 `.SH/.SZ` 子集 hash
11. 返回 WriteResult，由 executor 执行唯一一次 commit
```

DAO 只执行 SQL，不调用 commit。writer 内任一对账失败抛 `IngestionWriteError(error_code='etf_basic_snapshot_invalid')`，executor rollback 后旧 raw/serving 都恢复。

不使用 `TRUNCATE`，因为它不应脱离当前事务和表权限模型；不 drop/recreate 表；不触发任何下游级联删除。

### 5.4 并发门禁

两层门禁同时存在：

1. Ops 创建 `etf_basic` TaskRun 时拒绝第二个 `queued/running/canceling` 的同数据集 maintain 任务。
2. writer 使用 PostgreSQL transaction advisory lock 防止绕过 Ops 或多个 worker 同时替换。

advisory lock 是最终数据安全门禁；Ops 冲突检查用于提前给运营明确错误。两者都不能改成旧激活池或 seed fallback。

### 5.5 诊断扩展

在 `WriteResult` 新增：

```python
persistence_diagnostics: dict[str, Any] = field(default_factory=dict)
```

并经 `_RunState`、`IngestionExecutor._build_ingestion_diagnostics()` 和 `TaskRunIngestionContext` 的现有安全清洗器写入诊断 JSON。样本代码最多保留 20 个，避免 TaskRun JSON 无界增长。

快照诊断至少包含：

```text
source_rows
normalized_rows
raw_before_count / raw_after_count
serving_before_count / serving_after_count
source_snapshot_hash
raw_business_hash / serving_business_hash
added_count / removed_count / changed_count
status_changed_count / list_date_changed_count
bounded added/removed/changed samples
pagination page_count / terminal_offset / terminal_page_rows / observed_short_page
```

`rows_written` 继续表达正式 serving 写入数；raw 写入数放在 `persistence_diagnostics`，不改变所有数据集共享的顶层语义。

---

## 6. 代码驱动数据集规划

### 6.1 DatasetDefinition universe

`etf_mins/etf_sh_cons/etf_sz_cons` 的 planning 改为：

```python
universe_policy = "pool"
universe.sources = (
    DatasetUniverseSourceDefinition(
        type="core_serving_etf_basic",
    ),
)
```

`request_field='ts_code'` 和 `override_fields=('ts_code',)` 保持。旧 `ops_etf_series_active` resource 全部删除。

这里的 `pool` 只沿用当前 DatasetDefinition 的“按对象集合 fan-out”技术形状，不表示存在新的持久化池，也不允许继续访问 Ops 激活池。Basic source 不配置 `resource`；新增共用的 planner 私有 Definition 校验 helper，只负责确认 `pool + core_serving_etf_basic + resource is None` 形状，不读数据库。通过校验后按请求形状分流：

1. 自动计划调用一次 `EtfBasicDAO.load_requestability_snapshot()`；`etf_mins` 读全市场，`etf_sh_cons/etf_sz_cons` 分别读 `SH/SZ` 作用域。对应作用域 targets 为空时复用现有 `universe_empty` 并在错误详情中写 exchange。
2. 显式单代码计划不调用 snapshot，只走第 6.2 节的 `get_requestable_target()`。
3. 仅 `etf_mins` 的显式多代码计划调用一次全市场 snapshot；`etf_sh_cons/etf_sz_cons` 继续拒绝多个代码。

三个 builder 共用 Definition 校验和 P2 DAO 资格契约，不能分别实现 SQL，也不得回退旧池。

### 6.2 显式代码

显式 `ts_code` 的规则：

1. `etf_sh_cons/etf_sz_cons` 一次仍只允许一个代码；`etf_mins` 允许一个或多个代码。
2. 单代码必须命中 `get_requestable_target(ts_code, as_of_date)`。
3. `etf_mins` 多代码只加载一次 snapshot；输入统一去空格、转大写、去重和排序，任一代码未命中时整次抛 `etf_not_requestable`，details 带 `invalid_ts_codes`，不返回部分 targets。
4. `etf_sh_cons` 额外要求 `.SH`；`etf_sz_cons` 额外要求 `.SZ`。
5. 错误详情记录代码和 `as_of_date`，不泄露内部 SQL。
6. 不允许回退到 seed CSV、旧表或“只要是 `.SH/.SZ` 就放行”。

本需求使用的结构化错误码按阶段登记到 `src/foundation/ingestion/codebook.py`，P3 不提前实现 P4 错误：

| 错误码 | 错误阶段 | 实现阶段 | 含义 |
|---|---|---|---|
| `etf_not_requestable` | planner | P3 | 代码不满足当前 Basic 可请求条件 |
| `window_before_list_date` | planner | P3 | 显式请求窗口整体早于上市日 |
| `etf_basic_snapshot_invalid` | validator/writer | P1 已完成 | Basic 完整快照校验或对账失败 |
| `fund_daily_serving_publish_failed` | writer/executor | P4 | raw 已提交但 ETF serving 发布失败 |
| `universe_empty` | planner | 现有复用 | 本次作用域没有当前可请求 ETF，自动任务停止且不生成源请求 |

### 6.3 上市日裁剪顺序

对每个 `EtfRequestTarget`：

```python
effective_start = max(requested_start, target.list_date)
effective_end = requested_end
```

严格顺序：

```text
解析请求日期
-> 取得 EtfRequestTarget
-> 按 list_date 裁剪
-> 若空窗口则跳过/报错
-> 按频率自然月跨度切窗
-> 生成 PlanUnitSnapshot
```

不能先按全市场日期切窗再逐 unit 丢弃，否则计划量和额度预览仍包含上市前无效窗口。

自动全量计划中，整个请求窗口早于某只 ETF 上市日时，该 ETF 直接不生成 unit；不新增自动跳过原因计数，也不为此扩展 `DatasetExecutionPlan`、TaskRun 或 Ops 观测契约。任一显式代码的整个窗口为空时整次抛 `window_before_list_date`；point 请求要求每个代码都满足 `trade_date >= list_date`。

若自动计划中的全部 target 都因本次窗口早于各自上市日而被裁掉，planner 返回现有合法的 0-unit plan；当前 executor 会以 0 个单元正常完成且不调用源端。P3 只补回归测试固定这一既有语义，不新增 `skipped` 状态或汇总原因。

每个生成 unit 的 `progress_context` 增加：

```text
eligibility_as_of
master_list_date
requested_start_date
effective_start_date
```

源请求 builder 只接收已经裁剪后的日期，不能再次自行改日期。

P3 同时把当前仅由 `etf_mins` 使用的频率窗口选择和自然月切窗移到 ETF 专用纯函数模块：

```text
src/foundation/ingestion/etf_minute_windows.py
```

```python
build_etf_minute_windows(
    *, freq: str, start_date: date, end_date: date
) -> tuple[tuple[date, date], ...]
```

该模块同时保存五个频率对应的 2/12/36/72/120 月常量，原 `_split_calendar_month_span_windows()` 和 `ETF_MINS_RANGE_WINDOW_MONTHS` 不再在 `unit_planner.py` 保留第二份。planner 在完成 selector 与 `list_date` 裁剪后调用该函数；P9 alignment preview 也只调用该纯函数计算 unit，不得为每个 action 实例化一次完整 resolver。它是 ETF 分钟专用计算，不新增 `DatasetExecutionPlan` 字段、不进入共享 Ops 契约，也不泛化成其他数据集能力。

### 6.4 各数据集差异

| 数据集 | 对象集合 | 日期裁剪 | 原有切窗/分页 |
|---|---|---|---|
| `etf_mins` | 全部当前可请求 ETF | `DATE(trade_time) >= list_date` | 保留 5 个频率的现有自然月窗口、8,000 分页 |
| `etf_sh_cons` | 当前可请求 `.SH` | `trade_date >= list_date` | 保留 point/半年窗口和现有分页 |
| `etf_sz_cons` | 当前可请求 `.SZ` | `trade_date >= list_date` | 保留 point/月窗口和现有分页 |

`fund_daily` 不进入本节 fan-out；它仍由 generic planner 每个交易日生成一个全市场 unit。

---

## 7. `fund_daily` 两阶段落库

### 7.1 Definition 与请求边界

文件：`src/foundation/datasets/definitions/market_fund.py`

目标修改：

```text
write_path: raw_fund_daily_etf_serving_publish
transaction.commit_policy: raw_then_serving
```

以下保持不变：

1. 默认按 `trade_date` 一次请求源端全集并分页。
2. 不按 Basic ETF 数量拆成逐代码请求。
3. 显式 `ts_code` 仍是基金接口的人工探测/修复入口，不由 Basic 扇出，不改变 raw 边界。
4. raw 保存源端返回的所有场内基金代码。

### 7.2 writer/executor 职责

writer 新增两个只写不提交的方法：

```python
write_raw_phase(...)
write_serving_phase(..., eligibility_as_of: date)
```

executor 对 `commit_policy='raw_then_serving'` 执行：

```text
normalize once
-> raw phase upsert
-> COMMIT raw
-> 记录 raw_committed=true 与 raw_rows_committed
-> 读取当前可请求 ETF map(ts_code -> list_date)
-> serving phase filter + upsert
-> COMMIT serving
-> unit success
```

DAO 和 writer phase 均不得自己 commit；两个提交点只存在于 executor。普通 `commit_policy='unit'` 的其他数据集不受影响。

### 7.3 serving 过滤

对每个归一化 row：

```python
target = requestable_by_code.get(row["ts_code"])
publish = target is not None and row["trade_date"] >= target.list_date
```

未发布到 ETF serving 的行不是 normalizer reject，也不影响 raw 成功；按原因统计：

```text
CODE_NOT_REQUESTABLE_AT_PUBLISH
BEFORE_CURRENT_LIST_DATE
```

selector 返回空集合、数据库查询失败或 serving upsert 失败时：

1. rollback 当前 serving 事务。
2. 保留已提交 raw。
3. 抛 `fund_daily_serving_publish_failed`。
4. TaskRun unit 标记失败，不得标成功或 partial success。
5. 诊断必须明确 `raw_committed=true`、raw 行数、serving 行数和失败阶段。
6. 重试时 raw upsert 幂等，再尝试 serving 发布。

绝不允许 selector 失败后把全部 raw 行写入 ETF serving，也不允许退回旧激活池。

### 7.4 观测语义

顶层 `rows_written/rows_committed` 继续表达 serving 目标表，新增分层诊断：

```json
{
  "persistence": {
    "raw": {"rows_upserted": 0, "committed": true},
    "serving": {"eligible_rows": 0, "rows_upserted": 0, "committed": false},
    "eligibility_as_of": "2026-08-28",
    "excluded_reason_counts": {}
  }
}
```

如果 raw commit 后 observer 状态写入失败，不能反向影响 raw；这沿用业务事务与 TaskRun 观测事务隔离规则。

### 7.5 `fund_adj/etf_share_size` 显式入口

D17 中待 LLD 定位的另外两个显式单代码入口结论如下：

1. `fund_adj` 的显式 `ts_code` 保留，继续把源端返回写入 `raw_tushare.fund_adj` 和 `core.fund_adj_factor`，不接 Basic 过滤。
2. `etf_share_size` 的显式 `ts_code` 保留，继续写 `raw_tushare.etf_share_size`，现有 `core_serving.etf_share_size` view 自动直出，不接 Basic 过滤。
3. 两者都不得由 Basic 当前可请求列表自动 fan-out；日常任务继续按交易日一次拉源端全集。
4. 本次不修改它们的 write path、事务策略、物理表或 serving view；只增加回归测试证明这些边界没有被 ETF 主数据改造误伤。

---

## 8. ETF 实时链路替换

### 8.1 provider 不改

`src/foundation/realtime/etf_rt_daily.py` 的固定沪深通配符请求、Redis batch、snapshot 和 delta 发布全部保持。不得改成逐 ETF 请求。

### 8.2 health 契约改名

后端：

```text
active_pool_count     -> eligible_etf_count
active_snapshot_count -> eligible_snapshot_count
```

`eligible_etf_count` 来自 `EtfBasicDAO.load_requestability_snapshot(as_of_date)`；`eligible_snapshot_count` 是当前 Redis batch 中命中这些代码的数量。`source_snapshot_count` 等源端字段不改。

读取时点是**每次 `build_etf_rt_daily_health()` API 调用开始时一次**，不是 collector 的每个源请求，也不是每日预生成。两项只表达本次 Health 响应里的业务覆盖率，不改变 provider 请求，不作为 collector 是否发请求的门禁。

必须同步修改：

```text
src/ops/queries/realtime_feed_health_query_service.py
src/ops/schemas/realtime.py
frontend/src/shared/api/realtime-types.ts
frontend/src/pages/ops-realtime-monitor-page.tsx
对应后端与前端测试
```

不保留旧 JSON 字段、Pydantic alias 或前端 fallback。

selector 返回空集合时 Health 仍正常返回，`eligible_etf_count=0`、`eligible_snapshot_count=0`；这表示业务资格集合为空，不得改写成 Redis 不可用，也不得回退到 provider 全量 snapshot 当分母。

### 8.3 监控候选接口

当前 `/api/v1/ops/realtime/etf-monitor/active-etfs` 改为：

```text
GET /api/v1/ops/realtime/etf-monitor/eligible-etfs
```

服务和 DTO 同步改名：

```text
list_active_etfs                  -> list_eligible_etfs
EtfRealtimeMonitorActiveEtfItem  -> EtfRealtimeMonitorEligibleEtfItem
EtfRealtimeMonitorActiveEtfListResponse
                                  -> EtfRealtimeMonitorEligibleEtfListResponse
```

查询从 `requestable_targets_subquery(as_of_date)` 起表，再 outer join 最新 fund daily、最新 share size 和现有监控池。分页、关键词、规模排序逻辑保留。`RawEtfShareSize` 仍直接读取，这是直出存储设计，不是需要迁移的旁路。

读取时点是**每次候选分页 API 请求开始时一次**。服务先固定 `as_of_date`，再构造一次 subquery；总数与分页结果允许执行两条数据库 SQL，但两条 SQL 必须复用同一个 subquery 定义和日期。它决定这次页面可选哪些 ETF，不创建持久化 eligible pool，也不把所有 eligible ETF 自动加入运营监控池。当前可请求集合为空时正常返回 `total=0/items=[]`，不是 500，也不回退旧池。

### 8.4 监控配置与运行时

`ops.etf_realtime_monitor_pool` 保留，它表示运营重点关注对象，不是同步激活池。

目标行为：

1. 新增监控对象，以及把现有对象从 disabled 改为 enabled 时，用 `get_requestable_target()` 校验；保持 disabled 的备注/分组修改允许保存。
2. 新增或修改 ETF scope rule 时同时校验监控池成员和当前可请求资格；group scope rule 不逐代码固化资格。
3. `EtfRealtimeMonitorService.run_after_etf_batch()` 处理前将 enabled monitor pool 与当前可请求集合求交集。
4. 已失效配置即使仍保留在配置表中，也不得参与本批指标计算或产生新告警。
5. 历史 `etf_realtime_alert` 和分钟统计保留，不因主数据变化删除。

第 3 项的读取时点是**每次实时批次进入 `run_after_etf_batch()` 时一次**，本批监控计算期间固定；不是每条指标或每条规则重查 Basic。当前可请求集合为空时，本批次正常 no-op，不做指标计算、不发新告警；返回 `EtfRealtimeMonitorRunResult(status='skipped', evaluated_count=0, alert_count=0, message='eligible ETF set empty')` 供现有 collector 日志输出。不新增 `eligible_etf_count` 字段、TaskRun 记录或其他诊断持久化；provider 的抓取与 Redis 发布仍不受影响。

`run_after_etf_batch()` 当前只读取既有 `ops.etf_realtime_minute_stat` 作为历史基线并生成告警，本身不写分钟统计。独立手工入口 `EtfRealtimeMinuteArchiveService` / `ops-archive-etf-realtime-minute-stats` 已由《ETF 实时成交额异动监控 LLD v1》冻结并安排退场，不属于 P6，也不得为了本阶段继续扩展。仓库内没有该 CLI 的自动调用方；在其正式退场前，运营若手工执行，它仍按 enabled monitor pool 工作。这一已知边界不改变当前 Prod 审计中“不可请求监控配置为 0”的事实。

### 8.5 旧 review 页面删除

旧 ETF 激活池审查能力没有新的业务用途，直接删除：

```text
GET /api/v1/ops/review/etf/active
GET /api/v1/ops/review/etf/active/summary
ops-v21-review-etf-page.tsx
对应路由、导航、schema、共享类型和测试
```

不把它改造成 Basic 浏览页面；用户没有提出新的 Basic 管理 UI。

---

## 9. 下游只读复核门禁

### 9.1 不新增清理实现

本轮 Prod 审计的已批准删除候选为 0，因此明确不新增：

```text
etf_master_alignment_cleanup_service.py
ops-etf-master-alignment-cleanup CLI
audit/apply 模式
事实删除 manifest/候选 CSV
分批 DELETE、断点续跑或恢复逻辑
```

现有 `EtfFundDailyServingCleanupService` 和 `ops-cleanup-etf-fund-daily-serving` 在 P4 与 fund daily 旧门禁一起删除，不改名、不复用，也不保留兼容入口；P8 不再重复处理。

### 9.2 重建后的复核时点

`etf_basic` 完整快照重建并通过 raw/serving 集合验收后，以该次 `source_snapshot_hash` 为基准复跑一次受控只读统计。它是发布验收步骤，不是日常 schedule、产品 API 或可重复删除工具。

| 对象 | 复核项 | 当前结果 |
|---|---|---:|
| `raw_tushare.etf_minute_bar` | 非交易所后缀、交易所冲突、不在当前源端 Basic、早于当前上市日 | 明确删除候选 0；上市日前事实 0 |
| `raw_tushare.etf_sh_cons` | 非 `.SH`、交易所冲突、不在当前源端 Basic、早于当前上市日 | 全部 0 |
| `raw_tushare.etf_sz_cons` | 非 `.SZ`、交易所冲突、不在当前源端 Basic、早于当前上市日 | 全部 0 |
| `core_serving.fund_daily_bar` | 非交易所后缀、交易所冲突、不在当前源端 Basic | 全部 0 |
| `core_serving.fund_daily_bar` | 早于当前 `list_date` | 2,091 行、3 个代码，只报告 |
| `ops.etf_realtime_monitor_pool/rule` | 当前不可请求配置 | 0 |

### 9.3 分类与动作

| 分类 | 动作 |
|---|---|
| `NON_EXCHANGE_ETF_SUFFIX` | 当前为 0；重建后若非零，停止并另立精确一次性方案 |
| `CODE_NOT_IN_ETF_MASTER` | 只报告；代码可能从当前主数据消失，不自动删除历史 |
| `BEFORE_CURRENT_LIST_DATE` | 只报告；可能是上市日后移或代码复用，不自动删除历史 |
| `PENDING_ETF_HAS_FACT` | 只报告，不自动删除 |
| `LISTED_WITHOUT_LIST_DATE_HAS_FACT` | 只报告，不自动删除 |
| `MONITOR_CONFIG_NOT_REQUESTABLE` | 运行时资格门禁阻止继续生效；当前为 0，不建设清理程序 |

`ops.etf_series_active` 的整表 drop 属于激活池 schema 退场，不是本节下游事实清理。

### 9.4 明确保护

以下对象继续保持原边界，不进入 ETF Basic 差集删除：

```text
raw_tushare.fund_daily
raw_tushare.fund_adj
core.fund_adj_factor
raw_tushare.etf_share_size
core_serving.etf_share_size view
ETF index 数据
fund_basic/fund_manager/fund_share 等公募基金域
ops.etf_realtime_alert
ops.etf_realtime_minute_stat
```

复核结果仍为 0 时，本阶段无业务写入并直接结束。若明确旧 `.OF` 身份意外非零，必须停止、报告精确表/代码/主键/行数并等待新的授权；不能在实施时临时补回通用 CLI。

---


## 10. ETF 分钟 Preview 与执行入口

现行参数、按月 raw 覆盖查询、切窗、成功空结果覆盖、hash、代码数组和运行命令统一维护在 [ETF 分钟维护文档](/Users/congming/github/goldenshare/docs/datasets/etf-mins-dataset-development.md)。本 LLD 不再复制另一份 Preview/Submit 操作指南。

- `ops-preview-etf-minute-alignment` 只读：公开输入为起止日期，对象为当前可请求 ETF × 五个原生频率；上市日和 SSE 开市日裁剪后计算前后缀，不推断内部逐 bar 完整性。
- [CLI handler](/Users/congming/github/goldenshare/src/cli_parts/ops_handlers.py) 在调用 service 前设 REPEATABLE READ + READ ONLY 和每语句 180 秒 timeout，finally rollback，之后才输出/原子写计划文件。直接调用 service 不会自动获得这些事务保护。
- 月度统计超过门禁就停止，不自动回退周度、升 timeout 或加索引。180 秒不是全 Preview 总时长。
- target hash 只包含代码、上市日、交易所；计划/hash 是人工审计证据，不是当前自动 Submit 的验签或写入授权。
- 正式执行复用一个普通 `etf_mins` 手动 TaskRun，频率/代码由原 planner 展开。多代码只放宽 ETF 分钟，沪深申赎仍维持各自单代码边界。
- 旧 `ops-submit-etf-minute-alignment`、batch-size、alias、专用 payload 和旁路抓取器不恢复；新的区间与额度需新的明确生产授权。
- P12 首批、停止、纠偏及最终 10117 的实际证据保留在 §13，不能拿旧全历史 Preview 或旧队列继续执行。



## 11. 旧 ETF 激活池退场账本

### 11.1 机制起因与历史数量

旧 `ops.etf_series_active` 以 `(resource, ts_code)` 为主键，早期补足没有统一 ETF 资格入口的缺口，后形成需 seed/复核维护的第二套名单，无法自然跟随新上市与上市日起点，因此退出。它不是现在仍在用的业务监控池。

2026-08-29 drop 前只读审计：共 **5,708** 行，其中 fund_daily、etf_mins、etf_rt_daily 各 1,395，etf_sh_cons 为 803、etf_sz_cons 为 720；只有主键及两个索引，无外键、依赖 view、自定义触发器或函数依赖。这些不是当前全集/容量常量。

两份旧报告 `reports/etf_series_active_seed_1395_20260617.csv`、`reports/etf_series_active_fund_daily_accepted_gaps_31_20260617.csv` 在退场时已不存在，删除的是引用它们的旧实现与测试，不编造“删除 seed CSV”的事实。

### 11.2 已完成的逐文件退场

| 归属阶段 | 层 | 历史文件/对象 | 已完成处理 |
|---|---|---|---|
| P4 | Cleanup | `src/ops/services/etf_fund_daily_serving_cleanup_service.py` 与 `ops-cleanup-etf-fund-daily-serving` | 与 fund daily 旧门禁一起删除，不提供替代清理入口 |
| P7 | Review | `review_center_query_service.py`、`review_center.py`、`schemas/review_center.py`、`schemas/__init__.py` 中 ETF active 类型/方法/路由 | 只删除 ETF active 部分，保留 review center 其他能力 |
| P7 | Frontend review | `ops-v21-review-etf-page*`、router、shell、shared types 中旧页面/路由/导航/类型 | 删除 ETF active 部分 |
| P8 | Migration | `20260618_000117_add_etf_series_active.py` | 保留历史迁移文件；新增迁移 drop 当前表 |
| P8 | ORM | `src/ops/models/ops/etf_series_active.py` | 删除 |
| P8 | 注册 | `src/ops/models/ops/__init__.py`、`src/app/model_registry.py` | 删除 ETF model 注册 |
| P8 | DAO | `src/foundation/dao/etf_series_active_dao.py`、`src/foundation/dao/factory.py` 中的 ETF 属性 | 删除；必须晚于消费者迁移 |
| P8 | Contract | `src/foundation/kernel/contracts/etf_series_active_store.py` | 删除 |
| P8 | Adapter | `src/ops/etf_series_active_store_adapter.py` | 删除 |
| P8 | Seed | `src/ops/services/etf_series_active_seed_service.py` | 删除 |
| P8 | CLI | `src/cli.py`、`src/cli_parts/ops_handlers.py` 中 `ops-seed-etf-series-active` 及 handler/import | 删除 |
| 各消费阶段 + P8 | Tests | resolver/writer/Health/monitor 测试由各迁移阶段重写；model/DAO/seed/CLI 独立测试由 P8 删除 | 不把旧测试集中拖到最后才处理 |


历史实现只从 Git 追溯；上表不是当前待执行清单。旧池 model/DAO/store/adapter/seed 及装配已删除，Review 没有 Basic 替代页面。

### 11.3 当前消费者与保护范围

| 消费者 | 当前实现 |
| --- | --- |
| 三个代码驱动 planner | Basic selector + 上市日；SH/SZ 各自 scope；分钟支持多代码 |
| fund daily writer | Raw 先提交，再读取 Basic 发布 Serving |
| Health | Basic snapshot，eligible_etf_count/eligible_snapshot_count |
| monitor candidate | Basic requestable subquery 起表，count/page 复用 |
| monitor runtime | enabled monitor pool ∩ Basic 当前可请求集合；空集合复用 skipped，不新增诊断合同 |

完整保留 `ops.index_series_active` 及其 model/DAO/store/adapter/planner，`ops.etf_realtime_monitor_pool/rule/alert/minute_stat`，以及固定 provider 通配符请求。旧 Review 两个 GET 和旧 active-etfs 地址为 404；保留这些负向测试。

2026-08-29 曾指出 etf_rt_min、DG ETF 等其他方案需要各自重新基线；这是当时跨专项边界，不是永久冻结其他专项的当前状态。新工作应看它们自己的最新文档，不能从旧池历史恢复执行设计。

### 11.4 清零与防误删

- 生产代码/前端/配置不得恢复 ETF 专属旧 model、DAO、contract、adapter、seed、CLI；检查必须针对真实 ETF 标识。
- 测试不能恢复旧能力 fixture/import，仅允许退场负向字符串断言；[retirement 测试](/Users/congming/github/goldenshare/tests/test_etf_series_active_retirement.py) 同时保护指数池、DAOFactory、CLI 和 migrations。
- 历史 create/drop migration 及带日期文档可出现旧表名；不能把 `list_active_codes`、`active_pool_count` 等通用词全仓机械清零。
- 不新增 alias、fallback、双读、空实现、兼容页面或第二份持久化 ETF 池；不按固定 1,395/803/720 数量重建。

## 12. Alembic 与不可逆发布边界

保留历史 `20260618_000117_add_etf_series_active.py`。退场迁移为 `20260829_000157_drop_etf_series_active.py`，`down_revision=20260828_000156`；upgrade 精确 drop ops.etf_series_active，不用 CASCADE/IF EXISTS，不动下游事实；downgrade 抛 RuntimeError，不能自动重建/seed/迁移旧行。

实施计划要求先迁移全部消费者、完成候选回归，再在独立维护窗口停止旧进程、核对活动任务、部署/drop、Basic 重建对账，最后恢复服务与调度。**实际生产部署与 drop 早于 P11 的 Basic 维护窗口**，见 §13 P11；不能倒写成事前门禁全部按理想次序执行。

P8 当时只提交代码与 migration，没有执行生产 DDL；P11 记录确认 drop 已生效、旧表不存在、指数池仍有 6,014 行。该数量只对应 2026-08-29。迁移后不支持回到依赖旧池的版本，不恢复空池，只允许前向修复 Basic/消费者。新的发布仍须重新审计 head、活动进程与生产授权，不重跑历史施工步骤。



## 13. 历史开发与生产验收记录（2026-08-28/29）

以下按当时过程保留，包括已作废 Submit、失败/取消和部分提交；其中“当前”“下一步”“停止门禁”均指所在历史阶段，不是今日状态或继续执行授权。现行分钟操作看 §10；唯一未补足的历史消费者证据单列在本节末。

每一步都遵守“先完成当前阶段测试和差异审计，再进入下一阶段”。不得把删除表提前到消费者切换之前。

### P0：开发前复核与基线冻结

动作：

1. 同步 CodeGraph 并确认状态。
2. 重新跑本 LLD 第 11.4 节引用搜索，保存当前引用基线。
3. 重新确认 Alembic heads/current。
4. 只读记录 prod Basic、六类下游复核对象和保护对象的行数及分类统计。
5. 用 Tushare MCP 做一个最小 `etf_basic` 字段样本；除非源文档或行为变化，不重复全量耗额度。

停止条件：代码链、源字段、真实 migration head 或生产物理表与 LLD 不一致。

#### P0 执行记录（2026-08-28）

P0 严格限定为同步索引、静态搜索、迁移状态检查、Prod 白名单只读查询和一次最小源端抽样；没有修改运行时代码、数据库、Lake、配置或 schedule，也没有进入 P1。

**CodeGraph 与引用基线**

`codegraph sync/status` 完成并在 P0 收尾时复核后，索引为 2,798 个文件、49,327 个节点、125,393 条边。相较 LLD 编写时的数量变化来自当前工作区其他文件变化；对 `EtfSeriesActive`、`EtfSeriesActiveDAO`、`EtfSeriesActiveStore`、`EtfFundDailyServingCleanupService` 重新执行 impact 后，分别得到 18、13、10、14 个受影响符号，调用链仍落在本 LLD 已列出的 model、DAO、contract、adapter、seed、CLI、review、health、实时监控和测试范围，没有发现新的 ETF 池消费者。

旧 LLD 第 11.4 节八组旧引用（现行防误删规则见本版 §11.4）在 `src/**`、`frontend/src/**`、`tests/**` 和当前配置中的实施前基线为：

| 精确字符串 | 匹配数 | 文件数 |
|---|---:|---:|
| `EtfSeriesActive` | 121 | 19 |
| `etf_series_active` | 115 | 31 |
| `ops_etf_series_active` | 8 | 3 |
| `ops-seed-etf-series-active` | 10 | 3 |
| `/ops/review/etf/active` | 20 | 4 |
| `active_pool_count` | 7 | 6 |
| `active_snapshot_count` | 9 | 6 |
| `/active-etfs` | 8 | 4 |

当前配置文件的上述引用均为 0。该表是 P8 静态清零验收的对照基线，不代表 P0 已删除任何引用。

**Prod Basic 与旧激活池基线**

所有查询均限定在明确白名单内，以只读事务执行；未执行 DDL、DML 或数据导出。`raw_tushare.etf_basic` 与 `core_serving.etf_basic` 当前行数和以下分类统计一致：

| 指标 | 数量 |
|---|---:|
| 总行数 / distinct code | 3,405 / 3,405 |
| `.OF` | 1,585 |
| 未知后缀 | 0 |
| `L / P / D` | 3,089 / 62 / 254 |
| `list_date IS NULL` | 71 |
| 后缀与 `exchange` 冲突 | 0 |
| 截至当日当前可请求 `.SH/.SZ` | 1,647 |

按后缀和状态拆分：`.OF` 为 `L=1,437`（其中 5 个无上市日）、`P=23`（其中 22 个无上市日）、`D=125`；`.SH` 为 `L=924`（其中 3 个无上市日）、`P=23`（全部无上市日）、`D=82`；`.SZ` 为 `L=728`（其中 2 个无上市日）、`P=16`（全部无上市日）、`D=47`。

旧 `ops.etf_series_active` 共 5,708 行：`etf_mins=1,395`、`etf_rt_daily=1,395`、`etf_sh_cons=803`、`etf_sz_cons=720`、`fund_daily=1,395`，非交易所后缀均为 0。该结果只用于退场前对账，不改变“直接删除旧池、不迁移池内容”的既定方案。

**六类下游复核对象**

本次 P0 按当前 Prod Basic 重新分类；它不是源端完整快照重建后的最终验收，最终仍须按第 9.2 节在 Basic 重建后复跑。

| 对象 | 行数 | 代码数 | 非目标后缀/交易所冲突/不在当前 Prod Basic | 早于当前 `list_date` | 其他报告项 |
|---|---:|---:|---:|---:|---:|
| `raw_tushare.etf_minute_bar` | 67,423,145 | 1,395 | 0 / 0 / 0 | 0 | `P` 或 `L+空日期` 均为 0 |
| `raw_tushare.etf_sh_cons` | 5,675,323 | 803 | 0 / 0 / 0 | 0 | `P` 或 `L+空日期` 均为 0 |
| `raw_tushare.etf_sz_cons` | 11,567,504 | 720 | 0 / 0 / 0 | 0 | `P` 或 `L+空日期` 均为 0 |
| `core_serving.fund_daily_bar` | 1,180,869 | 1,395 | 0 / 0 / 0 | 2,091 行 / 3 个代码 | `P` 或 `L+空日期` 均为 0 |
| `ops.etf_realtime_monitor_pool` | 3 | 3 | 当前不可请求配置 0 | - | - |
| `ops.etf_realtime_monitor_rule` | 0 条 ETF 规则 | 0 | 无效规则 0 | - | - |

`fund_daily_bar` 的 2,091 行继续按已拍板口径只报告、不删除；其余明确删除候选仍为 0，因此不恢复通用清理 CLI/service 设计。

**保护对象基线**

| 保护对象 | 当前行数 |
|---|---:|
| `raw_tushare.fund_daily` | 2,608,675 |
| `raw_tushare.fund_adj` | 2,792,339 |
| `core.fund_adj_factor` | 2,792,339 |
| `raw_tushare.etf_share_size` | 234,042 |
| `core_serving.etf_share_size`（直出 view） | 234,042 |
| `raw_tushare.etf_index` | 1,524 |
| `core_serving.etf_index` | 1,524 |
| `core_serving.fund_basic_current` | 32,412 |
| `core_serving.fund_manager_current` | 84,357 |
| `core_serving.fund_share_current` | 2,572,451 |
| `ops.etf_realtime_alert` | 0 |
| `ops.etf_realtime_minute_stat` | 0 |

21 个白名单对象均存在，表/view 类型和主键与本 LLD 一致；`core_serving.etf_share_size` 仍是 raw 直出 view，没有发现需要新建 core 或迁移 view 的理由。

**最小源端抽样与 P0 结论**

仅对 `510300.SH` 发起一次 `etf_basic` 请求，并显式指定本 LLD 的 14 个字段。源端完整返回 14 个字段，其中 `list_status=L`、`setup_date=20120504`、`list_date=20120528`、`exchange=SH`，与第 2.1 节的历史字段契约一致；没有重复发起源端全量请求。

P0 五项动作均已完成。代码链、源字段和 Prod 物理对象没有发现与 LLD 冲突；P0 当时的唯一停止项是连接数据库落后于代码 head。该历史门禁已在 P1 开发前按第 2.2 节重新实测并解除。

### P1：ETF Basic 快照发布

编码：

1. 收口 DatasetDefinition 和 request builder。
2. 新增 snapshot 校验/hash/diff 纯函数。
3. 新增专用 writer dispatch 和事务内对账。
4. 扩展 `WriteResult` 与 ingestion diagnostics。
5. 在 Ops TaskRun 创建侧增加同数据集 open-run 冲突检查。

测试：完整 `.SH/.SZ/.OF` 批次、旧代码消失、未知状态、未知后缀、交易所不一致、重复主键、reject、空结果、事务中途失败、并发锁、幂等重跑。

完成门禁：任何失败都不能改变旧 raw/serving；成功后集合和 hash 不变量成立。

#### P1 执行记录（2026-08-28）

P1 严格限定在 ETF Basic 快照发布链路，未进入 P2 选择器、下游 planner、旧激活池删除、实时契约或前端改造。

**CodeGraph 与消费者审计**

P1 开发前 `codegraph status` 为 up to date，索引包含 2,798 个文件、49,327 个节点和 125,393 条边。本阶段对 `DatasetWriter` / `WriteResult` / `TaskRunCommandService` 执行 query/impact，影响面覆盖 writer 分派、executor 诊断、TaskRun API/手工任务/schedule/retry 共用创建入口和现有测试。`DatasetDefinition` 消费者还核对了 registry、manual actions、catalog、resolver/planner、schedule capability、freshness 与 dataset card；没有发现需要提前带入 P2 的契约。

**实现结果**

1. `etf_basic` Definition 已收口为无过滤、单并发、`buffer_all` 的 5,000 行分页快照；请求构造器固定返回空业务参数，并拒绝 6 个旧筛选参数残留。
2. 新增 14 业务字段的纯函数校验、规范化 SHA-256 hash 和 diff；校验状态、后缀、交易所、空上市日期统计与主键唯一性。
3. 新增 `raw_etf_basic_snapshot_replace` 专用 writer；PostgreSQL transaction advisory lock、raw 全量、serving 仅 `.SH/.SZ`、两表删除/写入/flush/集合/hash 对账均在 executor 的同一 unit 事务内完成，DAO 不 commit。
4. `WriteResult.persistence_diagnostics` 已打通现有 TaskRun JSON，代码样本最多 20 个，没有新增 TaskRun 列。
5. `TaskRunCommandService.stage_task_run()` 在全部共用创建入口前增加 `etf_basic` open-run 检查；第二个 `queued/running/canceling` maintain 任务会返回 409，PostgreSQL 创建侧也使用 transaction advisory lock。

**测试与真实只读验收**

P1 新增和直接 API 用例 34 个全部通过；Definition/registry、observed snapshot、executor progress、action catalog、manual actions、TaskRun、news concurrency 与 runtime guardrail 的扩展回归 170 个全部通过。测试覆盖固定 14 字段、无筛选请求、`.SH/.SZ/.OF`、旧代码消失、状态/后缀/交易所异常、重复主键、reject、空结果、事务中途失败、写后对账失败、两层并发锁、单次 commit、诊断上限和幂等重跑。

扩大到 `tests/`（排除当前无法收集的 `tests/lake_console`）后，结果为 2,279 passed、10 skipped、7 failed。7 个失败均不在 P1 改动链路：3 个是既有架构/文档门禁与当前并行改动不一致，1 个是既有 CLI reporter 行为，2 个是仓库缺少旧激活池历史 CSV，1 个仍硬编码旧 Alembic head `20260824_000150`；P1 新增及相关回归没有失败。全量测试直接收集还会被 `tests/lake_console` 的缺失旧模块和同名测试模块冲突阻断，P1 不越界修复这些问题。

Prod 只读输入严格限定为 `raw_tushare.etf_basic` 和 `core_serving.etf_basic` 的 14 个业务字段。当前两表均为 3,405 行，业务 hash 均为 `39957b8f493a81b9de4e43f14534191f519646678df2af83f702aa812b655d7b`，现有 raw 能通过新状态、后缀、交易所和主键校验。按新 serving 规则从当前 raw 投影得到 1,820 行；现有 serving 相比投影只多 1,585 个 `.OF`，没有 `.SH/.SZ` 缺失或内容差异。该数据仅是生产重建前基线；P1 未请求源端全量、未写生产表、未触发 schedule。

P1 完成门禁已满足：成功路径的 raw/serving 集合和 hash 不变量成立；空结果、拒绝行、校验失败、中途写失败与对账失败均不能改变事务前的旧快照。

### P2：统一 Basic selector（已完成）

前置门禁：用户已在 2026-08-28 明确要求按重新基线后的 LLD 推进 P2，本阶段授权成立。

范围只限 Foundation selector：

1. 在 `etf_basic_dao.py` 新增 `EtfRequestTarget`、`EtfRequestabilitySnapshot` 和第 4 节三个方法。
2. 用唯一 predicate builder 实现状态、上市日、后缀、exchange 规则；snapshot 分类为互斥计数。
3. 删除无运行时消费者的 `get_active_etfs()/get_fund_daily_candidates()`。
4. **不修改**已经存在的 `DAOFactory.etf_basic`。
5. **不删除** `DAOFactory.etf_series_active`、旧 DAO、model、contract、adapter 或表。

测试：L/P/D、空日期、未来上市、`.OF`、交易所冲突、SH/SZ scope、非法 exchange、代码规范化、排序、排除计数对账、subquery 列契约，以及同一 `as_of_date/exchange` 下 snapshot target codes 与 subquery codes 完全一致。

完成门禁：P2 可以在所有旧消费者仍正常工作的情况下独立合入；资格 SQL 只存在于 DAO；本阶段没有 planner/writer/Ops/frontend 行为变化。

**P2 执行记录**

1. `EtfBasicDAO` 新增不可变的 `EtfRequestTarget`、`EtfRequestabilitySnapshot`，以及 snapshot、单代码 target、可复用 subquery 三个公共方法；三个方法共同复用 exchange/代码规范化和唯一资格 predicate。
2. snapshot 只执行一次 Serving 查询，按规定优先级产生互斥排除计数；全市场统计包含 `.OF` 排除项，SH/SZ 统计只按对应代码后缀划定作用域。snapshot targets 和 subquery 在相同 `as_of_date/exchange` 下通过代码集合一致性测试。
3. 删除了没有运行时消费者且语义不明确的 `get_active_etfs()`、`get_fund_daily_candidates()`；`fund_daily` 现行测试中的同名 mock 只用于证明 writer 不会回退该旧方法，不是运行时消费者，留到 P4 随 writer 测试一起迁移。
4. 按阶段边界没有修改 `DAOFactory.etf_basic`，也没有删除 `DAOFactory.etf_series_active`、旧 DAO/model/contract/adapter/table；planner、writer、Ops、API 和前端均未改动。
5. 开发前 CodeGraph 索引为 up to date，包含 2,814 个文件、49,646 个节点和 126,123 条边。query/impact 与精确代码搜索覆盖 `EtfBasicDAO`、`DAOFactory`、旧方法、旧激活池消费者和相关测试；确认 P2 可独立完成，旧池运行时消费者必须留给 P3-P8 逐阶段迁移。
6. 新 selector 与 DAOFactory 定向测试 21 个全部通过；旧激活池 DAO、`fund_daily` 现行写入链和子系统依赖矩阵扩展回归 12 个全部通过；相关 Ruff 检查通过。测试覆盖 L/P/D、空/未来上市日期、`.OF`、交易所冲突、作用域、非法 exchange、规范化、排序、不可变性、排除计数对账、subquery 列契约和两条选择路径一致性。

P2 完成门禁已满足：统一资格 SQL 只在 `EtfBasicDAO`，旧消费者仍可运行。本阶段没有数据库、源端或生产写入，也没有开始 P3。

### P3：三个代码驱动 planner（已完成）

代码白名单：

```text
src/foundation/datasets/definitions/market_fund.py
src/foundation/ingestion/unit_planner.py
src/foundation/ingestion/etf_minute_windows.py
src/foundation/ingestion/codebook.py
tests/test_dataset_definition_registry.py
tests/test_dataset_action_resolver.py
tests/test_etf_mins_dataset.py
```

若实现发现必须修改白名单外的共享 resolver、execution plan、Ops、API 或 writer，立即停止并重新审计，不得顺手扩范围。

编码：

1. Definition 保留 `universe_policy='pool'`，只把 universe source 从 `ops_etf_series_active + resource` 改为无 resource 的 `core_serving_etf_basic`；不新增共享 policy 或伪资源名。
2. 三个 target resolver 改用 `EtfRequestTarget`。
3. 上市日裁剪移到切窗前。
4. 抽取 `etf_mins` 纯切窗函数，正式 planner 与后续 alignment preview 共用。
5. 只新增 `etf_not_requestable/window_before_list_date` 两个错误码并同步 codebook 版本；空集合复用现有 `universe_empty`。增加 unit 级进度上下文，不新增 plan/TaskRun 汇总诊断。
6. 自动请求每次 plan 只调用一次 snapshot；显式单代码每次 plan 只调用一次 `get_requestable_target()` 且不调用 snapshot。
7. 保护所有指数池 planner 不变。

测试：自动全集、自动全部被上市日裁剪后的 0-unit 正常完成且源请求为 0、显式单代码、SH/SZ 限制、P/D/L-null/未来上市、point 越界、range 部分重叠、range 全部早于上市日、每个频率的纯切窗边界、planner 与纯函数的窗口结果一致，以及“自动 snapshot 一次 / 显式 target 一次且 snapshot 零次”。

完成门禁：生成的每个源请求起点都不早于 `list_date`；旧 ETF resource 引用从 DatasetDefinition 与 Foundation planner 清零；`DAOFactory.etf_series_active` 仍可被尚未迁移的 writer/Ops 使用。

**P3 执行记录**

1. `etf_mins/etf_sh_cons/etf_sz_cons` 保留 `universe_policy='pool'` 的对象展开形状，universe source 统一改为无 `resource` 的 `core_serving_etf_basic`；私有 Definition helper 只校验该形状，不读数据库，没有新增共享 policy 或伪 resource。
2. 三个 builder 共用 P2 的 `EtfRequestTarget`：自动请求在一次 plan 内只加载一份 ALL/SH/SZ snapshot，显式单代码只查询一次 target 且不加载全市场 snapshot。空资格集合继续使用 `universe_empty`，未回退旧池、seed 或代码后缀放行。
3. 所有请求先计算 `effective_start=max(requested_start,list_date)`，再执行分钟自然月、沪市半年或深市自然月切窗。自动 target 的窗口全早于上市日时直接不生成 unit，全部被裁后沿用现有 0-unit 成功语义且源请求为 0；显式请求分别用 `etf_not_requestable` 和 `window_before_list_date` 报错。
4. 只有真实生成的 unit 增加 `eligibility_as_of/master_list_date/requested_start_date/effective_start_date`；没有新增跳过统计、plan/TaskRun 汇总诊断、Ops 契约或写入逻辑。
5. 新增 ETF 分钟专用纯函数模块，唯一保存 1/5/15/30/60 分钟对应的 2/12/36/72/120 个月规则；`unit_planner.py` 中的旧常量和旧函数已删除，指数 planner 未改动。
6. 开发前 CodeGraph 索引为 up to date，覆盖 2,815 个文件、49,687 个节点和 126,215 条边；查询与 impact 覆盖 `DatasetUnitPlanner`、`DatasetPlanningDefinition`、三个 ETF builder、DAO 选择器、resolver/dispatcher/manual action 和相关测试。实现后同步索引，最终为 2,816 个文件、49,716 个节点和 126,302 条边，状态仍为 up to date。
7. 本地 Tushare 文档复核了 ETF 历史分钟、沪市申赎清单和深市持仓组合的日期/分页/字段契约；同日使用 Tushare MCP 各执行一个最小只读样本请求，结果与现有 request builder 一致，因此 P3 没有修改源请求参数或字段契约。
8. 目标 Ruff 检查通过；Definition/planner/minute 定向测试 209 个全部通过；扩展至 Basic DAO、旧池 DAO、申赎模型、代码本、运行时注册表和子系统边界的 240 个测试全部通过，另外 20 个 Basic 快照 writer 与 `fund_daily` 旧池 writer 阶段边界测试全部通过，Definition lint 通过。扩展回归只有旧 SQLite date/datetime adapter 的 15 个弃用警告，无失败。

P3 完成门禁已满足：实际 unit 的请求起点不早于 `list_date`，DatasetDefinition 与 Foundation planner 对三个旧 ETF resource 的引用已清零，旧 `DAOFactory.etf_series_active` 及其他消费者仍保留给 P4-P8 逐阶段迁移。本阶段没有生产数据库、Tushare 业务数据或其他外部状态写入。

### P4：`fund_daily` 两阶段发布（已完成）

编码：

1. 新增 `raw_then_serving` commit policy 的 linter 白名单。
2. 拆 raw/serving writer phase。
3. executor 增加两个明确提交点，以及“Raw 已提交、Serving 未提交”的分层诊断；这不是 partial success。
4. serving 接统一 selector 与 `trade_date >= list_date`。
5. 删除旧 active-pool writer helper。
6. 在本阶段唯一一次删除旧 `EtfFundDailyServingCleanupService`、`ops-cleanup-etf-fund-daily-serving` 及其测试/导出；不在 P8 重复处理。

测试：全市场 raw、ETF serving、LOF/REIT 只进 raw、上市日前只进 raw、selector 空、selector 异常、serving upsert 异常、raw upsert 异常、重试幂等、显式 ts_code 不扇出。

完成门禁：selector/serving 失败时 raw 已提交且 TaskRun 失败；不得出现 raw 被回滚或 serving 假成功；`fund_daily` 与 cleanup 对旧池引用清零，其他未迁移消费者仍可运行。

#### P4 执行记录（2026-08-28）

1. `fund_daily` Definition 已改为 `raw_fund_daily_etf_serving_publish` 和 `raw_then_serving`；linter 只对白名单中的 `fund_daily` 专用 write path 放行，其他数据集不能复用该提交策略。
2. `DatasetWriter` 已拆出只写不提交的 `write_raw_phase()` 与 `write_serving_phase()`；Raw 保存源端完整返回，Serving 每个发布阶段只加载一次固定执行日的 Basic snapshot，并按 `trade_date >= list_date` 发布。未发布行只进入 `CODE_NOT_REQUESTABLE_AT_PUBLISH/BEFORE_CURRENT_LIST_DATE` 统计，不作为 normalizer reject。
3. `IngestionExecutor` 在每个任务开始时固定一次中国自然日；每个 unit 先提交 Raw，再执行 selector/Serving 并提交，分层行数与排除原因在多 unit 任务中按任务累计。selector 空、selector 查询异常、Serving upsert/commit 异常统一抛 `fund_daily_serving_publish_failed`，保留已提交 Raw，unit/TaskRun 失败，顶层 `rows_written/rows_committed` 仍只表示 Serving。
4. 已删除旧 active-pool writer helper、`EtfFundDailyServingCleanupService`、`ops-cleanup-etf-fund-daily-serving` CLI、handler 和两组专用测试；没有替代 cleanup service、CLI、删除 manifest 或兼容入口。P4 交付时 ETF review、Health、monitor 和旧池基础设施按 P5-P8 原边界保留；其中 Health 已在后续 P5 完成迁移。
5. request builder、分页、默认全市场请求和显式 `ts_code` 单代码探测入口未改；`fund_adj`、`etf_share_size`、实时链路、TaskRun schema、前端和数据库迁移均未修改。
6. CodeGraph 在开工前确认 `DatasetWriter` 影响 Foundation executor 与 writer 定向测试，旧 cleanup 的 14 个符号只落在 service 和专用测试；精确搜索确认删除后 `fund_daily` 与 cleanup 对旧池引用清零，指数池及其他未迁移 ETF 消费者仍在。
7. Definition/linter/resolver/writer/executor 与普通 executor、ETF Basic snapshot、ETF minutes、代码本、运行时注册、三组架构边界合计 279 个测试通过；剩余旧池 DAO/model/seed、CLI 和 review 消费者保护回归 64 个通过；本阶段修改的 Python 文件 Ruff 检查通过。失败注入覆盖 Raw upsert/commit、selector 空/异常、Serving upsert/commit，以及失败后 Raw 幂等重放和 Serving 再发布。
8. 本阶段没有请求 Tushare、写入生产数据库、执行事实删除或运行旧 cleanup；历史 Serving 事实未被回删，代码消失或 `list_date` 变晚仍只影响未来发布。

### P5：实时 Health 后端与页面切换（已完成）

编码：

1. `RealtimeFeedHealthQueryService` 改为一次加载 Basic snapshot。
2. 后端 schema 将 `active_pool_count/active_snapshot_count` 改为 `eligible_etf_count/eligible_snapshot_count`。
3. 同步 realtime frontend type、健康卡片文案和测试。
4. 保持 provider 通配符、Redis key、batch/snapshot/delta 逻辑完全不变。

完成门禁：provider 请求参数快照测试保持固定通配符；Health 链不再引用旧池；候选、monitor runtime 和 review 尚未在本阶段删除。

#### P5 执行记录（2026-08-28）

1. `RealtimeFeedHealthQueryService.build_etf_rt_daily_health()` 已删除 `EtfSeriesActiveDAO` 依赖；每次 API 调用固定当前中国自然日并只调用一次 `EtfBasicDAO.load_requestability_snapshot(as_of_date)`，随后用同一份 target codes 计算当前 Redis batch 命中数。
2. 后端响应、前端类型和页面消费已从 `active_pool_count/active_snapshot_count` 直接切换为 `eligible_etf_count/eligible_snapshot_count`；没有 Pydantic alias、旧 JSON 字段或前端 fallback。`/api/v1/ops/realtime/etf-rt-daily/health` 路径及其余源端、批次、状态和轮询字段未改。
3. selector 空集合时，源端批次仍照常读取，资格分母和命中数返回 `0/0`，不标记为 Redis 不可用，也不以源端全量回填分母；Redis 不可用时保留已加载的 Basic 分母，命中数返回 0。
4. 实时监控页只把旧“活跃池命中”卡片改为“可请求 ETF 覆盖”，继续复用现有 `SectionCard/StatCard`，没有调整布局、查询路径、轮询策略或其他实时对象页面状态。
5. provider、runtime config、collector、Redis key、batch/snapshot/delta 发布实现均未修改；现有请求参数快照测试继续固定 `5*.SH` 与 `1*.SZ` 两个源请求段。
6. P6 的 candidate/pool/rule/runtime、P7 的旧 ETF review，以及 P8 的 DAO/model/seed/CLI/table 均保持原边界；本阶段没有数据库迁移、生产写入、Tushare 请求或配置变化。
7. 开发前 CodeGraph 索引为 up to date，包含 2,814 个文件、49,728 个节点和 126,369 条边；query/impact 与精确搜索覆盖 Health query、Ops API/schema、前端类型/页面及后端和前端测试，未发现需要扩大 P5 的隐藏消费者。
8. ETF Basic DAO、Health API、实时 provider/state/config/collector 与三组架构边界共 68 个后端测试通过，相关 Ruff 检查通过；前端 typecheck、规则检查、149 个测试和生产构建全部通过。测试包含资格/非资格交集、单次 snapshot 调用、空资格、Redis 故障和旧字段缺失。

### P6：实时监控候选、配置和运行时切换（已完成）

编码：

1. candidate query 改由 Basic requestable subquery 起表；endpoint/DTO/method 从 `active` 改为 `eligible`。
2. count 与 page 查询固定同一 `as_of_date`/subquery；增加空集合正常返回测试。
3. 新增监控对象和 disabled -> enabled 更新用 `get_requestable_target()` 校验。
4. ETF scope rule 写入同时校验监控池成员与当前资格；group rule 不逐代码校验。
5. `run_after_etf_batch()` 每批加载一次 snapshot，并以 `enabled monitor pool ∩ requestable codes` 执行；空交集只返回现有 `skipped` 结果和 message，不新增计数或诊断持久化。
6. 同步监控配置前端 API、DTO、页面和测试。
7. 保留 `ops.etf_realtime_monitor_pool/rule/alert/minute_stat` 及历史数据。
8. 不修改独立旧分钟归档 service/CLI；它保持冻结并由专门的实时监控 LLD 后续退场。

完成门禁：candidate、pool add、ETF rule 与 runtime 对旧池引用清零；空 selector 时 candidate 返回空页、runtime no-op；review 页面仍可暂时读旧池，留给 P7 独立删除。

#### P6 执行记录（2026-08-28）

1. 候选 API、service method 和 DTO 已从 `active` 直接改名为 `eligible`；`GET /api/v1/ops/realtime/etf-monitor/eligible-etfs` 每次请求固定一次中国自然日并只构造一次 `EtfBasicDAO.requestable_targets_subquery(as_of_date)`，count/page 复用同一对象。查询仍关联最新 `fund_daily`、最新 `raw_tushare.etf_share_size` 和运营监控池，保留关键词、分页、规模降序与代码排序；旧 `/active-etfs` 无 alias，测试确认 404。
2. 候选资格的正反样本覆盖 `.SH/.SZ + L + 有效上市日`，以及 `P/D`、空上市日、未来上市日、`.OF` 和代码后缀/交易所冲突。旧激活池即使仍有对应记录也不会回退；Basic 空集合返回 `200 + total=0 + items=[]`。
3. 新增监控对象无论 `enabled` 取值均通过 `get_requestable_target()`；`disabled -> enabled` 重新校验，`disabled -> disabled`、`enabled -> enabled` 和 `enabled -> disabled` 保持既定行为。失败仍使用 `422 / invalid_etf`，且测试确认不会新增记录或把 disabled 状态误改为 enabled。
4. ETF 级规则创建和修改先校验监控池成员，再校验当前可请求资格，失败沿用 `422 / invalid_scope` 且不污染原规则；group 规则只校验分组存在，global 规则保持 `__GLOBAL__`。规则删除、窗口、比例、冲突和默认规则逻辑未改。
5. `run_after_etf_batch()` 在批次开始固定当前中国时间，读取 enabled monitor pool 后只加载一次 Basic requestability snapshot，并只对两者交集读取 Redis 指标、历史基线和创建告警。`trade_date` 仍只决定行情交易日；Basic 名称查询只提供展示元数据，不改变资格集合。
6. 空监控池、空 Basic 或无交集统一返回 `status='skipped'`、`evaluated_count=0`、`alert_count=0` 和 `message='eligible ETF set empty'`；此路径不读规则、不计算指标、不调用飞书、不产生告警。selector 异常不回退旧池并继续抛给 collector 既有失败隔离；原告警提交顺序、飞书失败隔离、单 ETF 失败隔离和冷却升级行为保持。
7. 前端类型、query key、状态/组件参数和请求路径均迁移为 `eligibleEtf*` / `EligibleEtf*` / `/eligible-etfs`；候选文案改为“从当前可请求 ETF 中选择”。每页 50 条、关键词搜索、规模展示、分组选择和逐行添加保持，页面布局、监控池管理、规则编辑与告警区域未改。
8. `EtfRealtimeMinuteArchiveService`、`ops-archive-etf-realtime-minute-stats`、provider、Redis contract、实时配置、review center、旧池 DAO/model/contract/adapter/seed/CLI/table 均未修改。旧归档回归测试继续通过；P7 仍负责 review，P8 仍负责旧池基础设施和数据库表。
9. 后端 P6/旧归档/collector CLI 定向测试 26 个通过，实时 API 与三组架构边界回归 33 个通过，修改 Python 文件 Ruff 通过。前端目标测试 3 个、全量测试 149 个、typecheck、规则检查和生产构建通过；构建只有既有大 chunk 警告。浏览器核验时发现本机 `5173` 正运行独立 `wealth` 前端，因此未接管或重启用户服务；P6 页面请求与文案由目标测试和全量构建验证。
10. 完成后 CodeGraph 索引为 up to date，包含 2,830 个文件、50,141 个节点和 127,564 条边；query/impact 与精确搜索复核 pool/rule/runtime/API/schema/frontend/tests，未发现新增消费者或依赖越界。P6 监控链对 `EtfSeriesActive`、`list_active_etfs`、`ActiveEtf` 和 `/active-etfs` 的生产引用已清零；旧 review 引用按 P7 边界保留。未执行生产写入、数据库迁移、Tushare 请求、旧分钟归档或历史数据清理。

### P7：旧 ETF 激活池 review 能力删除与消费者清零

编码：

1. 删除 `/api/v1/ops/review/etf/active` 与 summary 路由、query method、ETF active schema/export。
2. 删除 `ops-v21-review-etf-page*`、对应路由、导航、共享类型和测试。
3. 不新建 Basic 浏览页面。
4. 使用 CodeGraph impact + 精确字符串搜索证明运行时消费者已清零。

P7 的“消费者零引用”允许旧基础设施本体暂时存在：model、DAO、contract、adapter、seed、CLI、历史 migration 及其独立测试仍由 P8 处理。除此以外，planner、writer、cleanup、Health、monitor、review 均不得再引用旧池。

完成门禁：形成 P8 可核验的删除白名单；若发现未登记消费者，停止并修订 LLD，不进入 P8。

#### P7 执行记录（2026-08-29）

1. `GET /api/v1/ops/review/etf/active` 与 summary 路由已直接删除；`ReviewCenterQueryService` 的 ETF list/summary、三个 ETF 私有 helper、resource 常量和 ETF 专属 model/schema import 同步删除。指数 list/summary/candidate/mutation 和板块查询均保持原实现。
2. `ReviewActiveEtfItem/ListResponse/SummaryResponse` 及 schema export 已删除；测试用管理员身份确认两个旧 GET 地址均返回 404。旧 POST/DELETE“没有写入口”测试随整条能力退场，不再保留历史方法级契约。
3. `ops-v21-review-etf-page.tsx` 及其测试已删除，应用路由、route tree、审查中心导航和 `OpsReviewActiveEtf*` 共享类型同步清零。没有新建 Basic 页面、兼容路由、alias、重定向或占位页；共享的 `IconTopologyRing3` 因仍被三个数据源导航使用而保留。
4. 浏览器在本地构建与受控 mock auth 环境验证：管理员导航中不再出现 ETF review；旧 `/app/ops/v21/review/etf` 显示 `Not Found`，且服务端请求日志没有 `/api/v1/ops/review/etf/active*`；指数和板块路由仍正常挂载并请求各自接口，控制台无错误。
5. 后端 review API 15 个测试、三组架构护栏 16 个测试、Ruff 均通过；前端目标 5 个测试和全量 146 个测试通过，typecheck、规则检查和生产构建通过。构建只有既有大 chunk 警告；文档完整性与 `git diff --check` 通过。
6. CodeGraph 后置索引为 up to date，包含 2,835 个文件、50,143 个节点和 127,454 条边。`OpsV21ReviewEtfPage` 已无结果，`ReviewCenterQueryService` 的剩余影响面只包含指数和板块 review；生产代码/前端对 `ReviewActiveEtf*`、两个旧 method、旧 API、旧页面文件名和旧页面路由的精确搜索均为 0，测试只保留两个 404 URL。
7. `ops.etf_series_active` 表、model、DAO、contract、adapter、seed、CLI、历史 migration 和独立测试均未修改；本阶段没有数据库迁移、生产写入、Tushare 请求、事实清理或实时分钟代码开发。

#### P8 精确删除白名单

P8 只允许处理下表对象；若开工复核出现名单外的运行时消费者，必须停止并修订 LLD。

| 动作 | 文件/对象 |
|---|---|
| 删除旧基础设施文件 | `src/foundation/dao/etf_series_active_dao.py`、`src/foundation/kernel/contracts/etf_series_active_store.py`、`src/ops/etf_series_active_store_adapter.py`、`src/ops/models/ops/etf_series_active.py`、`src/ops/services/etf_series_active_seed_service.py` |
| 删除旧独立测试 | `tests/test_cli_ops_seed_etf_series_active.py`、`tests/test_etf_active_pool_seed_reports.py`、`tests/test_etf_series_active_dao.py`、`tests/test_etf_series_active_model.py`、`tests/test_etf_series_active_seed_service.py` |
| 清理装配/入口 | `src/app/model_registry.py`、`src/cli.py`、`src/cli_parts/ops_handlers.py`、`src/foundation/dao/factory.py`、`src/ops/models/ops/__init__.py` |
| 清理测试装配/反例 | `tests/web/conftest.py` 删除旧表创建；`tests/web/test_ops_etf_realtime_monitor_api.py` 删除旧池 ORM 反例并保留 Basic 不回退语义 |
| 保留负向门禁 | `tests/test_dataset_action_resolver.py` 的 `not hasattr(..., "etf_series_active")`；`tests/test_etf_sh_cons_model.py` 的旧表不得进入申赎清单 migration 断言；P7 的 review 404 断言 |
| migration 边界 | 保留历史 `20260618_000117_add_etf_series_active.py`；P8 重新确认真实 head 后新增 drop-table migration，不回写历史 migration |
| 新增退场门禁 | `tests/test_etf_series_active_retirement.py` 固定 model registry、DAOFactory、CLI、精确 drop 和不可逆 downgrade 的负向契约 |
| 全面校准当前数据集文档 | `etf-mins`、`etf-sh-cons`、`etf-sz-cons` 的方案与 LLD 改写为 Basic Serving 当前可请求口径；`etf-share-size` 方案与 LLD、`fund-factor-pro` 发现审计改写为全市场请求/历史证据口径 |
| 全面校准未来方案 | ETF 实时分钟方案/LLD/R0B、实时成交额监控方案/LLD、DG ETF 接入方案删除旧池可执行设计，保留实测事实并标记选择范围尚未重新基线、当前不可开工 |
| 历史文档与索引 | 两份 ETF Active Pool 文档改写为退场历史记录；主方案、主 LLD 和 `docs/README.md` 同步阶段状态 |

未登记为 P8 删除对象的 `index_series_active` model/DAO/service/API/页面/测试必须原样保留。ETF 实时分钟方案仍依赖旧池的历史设计已经在文首标为“选择池需重新基线”，P8 不顺带设计替代选择池。

P8 开工复核（2026-08-29）：CodeGraph 索引为 up to date，包含 2,835 个文件、50,143 个节点和 127,454 条边；精确搜索未发现上述白名单之外的旧池运行时消费者。Alembic 唯一 head 仍为 `20260828_000156`。生产只读审计确认旧表共有 5,708 行，只有自身主键和两个索引，没有外键、依赖视图、自定义触发器或函数依赖；这些行不备份、不迁移，本阶段也不执行生产 DDL。

### P8：激活池基础设施与 schema 退场

编码：

1. 按 P7 白名单删除 model、DAO、contract、adapter、seed service、seed CLI 和独立旧测试。
2. 从 `DAOFactory` 删除 `etf_series_active`，清理 model registry 与 ORM export。
3. **不再处理**已由 P4 删除的 cleanup 和已由 P7 删除的 review。
4. 同步 CodeGraph，执行全仓当前态字符串清零，精确保护 `index_series_active`。
5. 重新确认唯一 Alembic head 后新增不可逆 drop-table migration；历史建表 migration 保留。
6. 按上述文档白名单全面改写旧池相关文档；不能只在文首补 superseded 提示后继续保留可执行的旧设计。

完成门禁：运行时代码/前端/config 旧引用为 0；测试无旧能力 import/fixture/call，仅保留明确负向断言；指数池测试全部通过；migration 能从真实 head 升级。这里的“升级”只指候选/测试环境与离线 SQL 验证，不表示生产表已删除；生产物理 drop 留给 P11。

#### P8 执行记录（2026-08-29）

1. 删除旧池 ORM、DAO、Foundation contract、Ops adapter、seed service；同步清理 `DAOFactory.etf_series_active`、Ops ORM export、App model registry、主 CLI、Ops handler 和 `ops-seed-etf-series-active`。没有兼容 DAO、alias、fallback 或双读。
2. 删除五份只证明旧能力存在的 model/DAO/seed/CLI/report 测试；Web fixture 不再创建旧表。实时监控 candidate 的反例只使用 `P` 等 Basic 不可请求行，selector 异常直接传播，不再创建旧 ORM 行证明“不回退”。
3. 新增 `tests/test_etf_series_active_retirement.py`，固定旧 model registry/DAOFactory/CLI 退场、指数池保留、migration 精确目标、不可逆 downgrade 和历史 create migration 保留。
4. 新增 `20260829_000157_drop_etf_series_active.py`，真实 `down_revision` 为 `20260828_000156`。离线 SQL 只有 `DROP TABLE ops.etf_series_active` 和 Alembic 版本更新；没有 `CASCADE`、`IF EXISTS` 或其他 schema 对象操作。
5. 两份旧池文档已改为历史退场记录；`etf_mins/etf_sh_cons/etf_sz_cons` 方案与 LLD 已改写为当前 Basic selector 和上市日裁剪；`etf_share_size` 明确继续按交易日源端全集、raw 直出 serving；`fund_factor_pro` 不再建议 active resource。
6. 尚未实现的 ETF 实时分钟、实时成交额监控重构和 DG ETF 接入已删除旧池可执行设计，只保留源端/时序/路径/容量证据，并统一标记为范围重新基线前不可开工。ETF 实时日线方案和配置中心展示稿中遗漏的旧 Health 文案也已改为当前 `eligible_* + ETF Basic` 合同。
7. 后置 CodeGraph 为 2,827 个文件、50,045 个节点、126,727 条边；四个旧池生产符号均无结果。`IndexSeriesActive` 仍有 40 个影响符号，指数 review、完整性、修复与 source serviceability 链保持。
8. 重点业务回归 291 个测试通过；完整 Web 870 个通过、1 个跳过；架构护栏 22 个通过；前端实时监控目标 3 个通过；Ruff、唯一 Alembic head、离线 SQL、文档完整性和 `git diff --check` 均通过。全量 CLI 中 42 个通过，唯一失败是未改文件中的既有 `test_attach_cli_progress_reporter_emits_throttled_progress`：测试 fake 只有 `contract`，当前 helper 要求实例有 `definition`；该失败可独立复现，按既定范围不修改通用 CLI 进度逻辑。
9. 本阶段没有执行生产 migration、生产写入、Tushare 请求、Basic 重建、分钟补拉、旧分钟归档、事实删除、Dagster 或 Lake 写入。生产旧表仍包含退场前审计的 5,708 行，物理 drop 只属于 P11 独立维护窗口。

### P9：分钟对齐 preview 与受控 TaskRun 提交

子阶段 P9A 编码：

1. 实现第 10 节只读 alignment plan service 和 `ops-preview-etf-minute-alignment`。
2. preview 固定全部当前可请求 ETF 和五个原生频率，不暴露历史 `as_of_date`、代码子集或频率子集输入。
3. preview 复用 Basic selector 与 P3 纯切窗函数，对相同代码与日期区间的频率合并 action，输出 target hash、action/unit 数与请求上下界。
4. 不实现 submit，不新增数据库 plan/history 表、schedule 或任何业务写入。

P9A 测试：无 raw、只有前缀、只有尾部、已有全区间、指定开始日前与当前上市日前的旧历史不算本轮覆盖、开始日为休市日时推进到首个开市日、上市日在开始日之后时继续按上市日推进、月度边界裁到 desired interval、源端成功空区间由显式成功 TaskRun 覆盖、多频率 TaskRun 覆盖还原、内部 gap 不生成请求、相同范围频率 action 合并、开始日晚于截止日、交易日历缺失/截止日非开市日/截止日晚于最近开市日、指定区间改变 plan hash 但不改变 target hash、新增/移除 target 或 `list_date` 变化会改 target hash、raw 月度查询次数只由指定区间和最早 effective start 决定且不随 ETF/频率数量增长、每月 SQL 只带该月半开区间、TaskRun 查询恒定一次，以及 1-call/4-call 请求边界。

P9A 完成门禁：preview 零 Tushare 源端请求、零业务写；真实只读规模报告已展示给用户；仓库中仍不存在 submit 或事实清理入口。

#### P9A 执行记录（2026-08-29）

1. 新增 `EtfMinuteHistoryAlignmentPlanService` 和唯一只读 CLI `ops-preview-etf-minute-alignment`。公开输入只有必填 `alignment_start_date/alignment_end_date` 与可选 JSON 输出路径；没有 `as_of_date/ts_code/freq/batch-size/submit/apply`，也没有 API、页面、schedule 或 plan 表。
2. 第一版跨 349 个分区的 target/frequency `LATERAL MIN/MAX` 虽未出现 raw 顺序扫描，但真实查询未通过原 60 秒门禁，已从代码和可执行方案中删除。最终实现按自然月执行 raw-only `COUNT/MIN/MAX`，每条 SQL 使用半开月区间且不关联 Basic；服务在内存中与同一次 Basic snapshot 求交，并按指定开始日、`list_date` 和 SSE 开市日裁剪。没有周度 fallback、重试、索引或 schema 变更。
3. CLI 固定 `REPEATABLE READ + READ ONLY`、每条语句 180 秒 timeout，并始终 rollback；计划仅在事务结束后打印或原子写入文件。实现不 import 或调用 connector、writer、`TaskRunCommandService`，仓库中不存在 submit 命令。
4. 原先未提供开始日、默认追溯每只 ETF 上市日的 Prod Preview 生成 44,793 个 unit；用户明确不在本阶段补 2026 年以前数据后，该计划及其 JSON/CSV 已作废，禁止作为 P9B 输入。审计同时确认 2026-01-01 至 2026-01-04 全部为 SSE 休市日，原计划把它们视为 1,210 个代码的前缀缺口属于假阳性，已通过开市日起点裁剪修正。
5. 以本地未部署代码连接 Prod 执行 `2026-01-01` 至 `2026-08-28` 的只读 Preview，资格日期固定为 `2026-08-29`。命令约 32 秒完成，未触发任何单月 180 秒门禁；没有请求 Tushare、创建 TaskRun、提交数据库事务或部署服务。
6. 真实计划包含 1,647 个 requestable/alignment target，晚于截止日对象为 0；raw 覆盖为 6,975 个 target/frequency，即五个频率各 1,395 个 ETF。成功 TaskRun-only 覆盖为 0；只有 252 个 ETF、1,260 个 target/frequency 缺少指定区间前缀，suffix 缺口为 0。其余 1,395 个 ETF 在当前首尾口径下不需要补 2026 年数据；内部逐日缺口仍明确不审计。
7. 最终生成 252 个 action、1,774 个 unit，源请求下界 1,774、按现有最多 4 页规则计算的分页请求上界 7,096。五频率 unit 分别为：`1min=766`，其余四个频率各 252。252 个 action 均包含五频率；其中 167 个从 2026 年首个开市日 `2026-01-05` 开始，85 个按各自更晚的上市日开始；代码分布为 `.SZ=134`、`.SH=118`。
8. 完整 JSON 为 66,655 bytes，审阅 CSV 为 19,046 bytes；action 实际数量与 `planned_action_count` 一致，逐 action unit 求和与 `planned_unit_count` 一致，`page_request_upper_bound = planned_unit_count * 4`，plan content hash 复算一致。计划明确保留 `interior_gap_not_audited=true`。
9. P9A service/CLI、ETF Basic DAO、ETF 分钟 Dataset/resolver/unit planner、四组架构护栏合计 240 个测试通过。全量 CLI 52 个通过，唯一失败仍是 P8 已记录且不在本阶段范围内的 `test_attach_cli_progress_reporter_emits_throttled_progress`；Ruff、文档完整性、`git diff --check` 和后置 CodeGraph 通过。P9A Preview 契约仍是当前有效基线。

#### P9B 旧分批 Submit 实现记录（2026-08-29，已作废）

以下内容只记录当时实现和验证事实，不再是当前可执行契约。旧实现的 `--batch-size` 与每 action 创建一个 TaskRun 已由第 10 节的普通手动任务多代码契约取代。

1. 用户已审阅 P9A 的 252 个 action、1,774 个 unit 和 1,774–7,096 次源请求边界，并确认 P9B 开发；首次实际生产批次选择 10 个 action。CLI 仍要求显式 `--batch-size`，10 不进入 Settings、数据库或代码默认值。
2. 新增 `EtfMinuteHistoryAlignmentSubmitService` 和唯一写入口 `ops-submit-etf-minute-alignment`。公开参数严格为 `--plan/--confirm-plan-hash/--batch-size`；没有日期、代码、频率、apply、DELETE、API、页面、schedule 或 plan 表入口。
3. JSON 在打开数据库会话前校验固定 P9A schema、人工确认 hash、复算内容 hash、五频率顺序、action 稳定顺序、日期边界以及复用当前 `build_etf_minute_windows()` 得到的 unit 数。2026 年 Prod 只读 Preview 文件已通过该解析器，仍为 252 个 action，hash 为 `d4d44e16624417492315e08c2e75477049c951ee896bdd0a6b557ac257318f58`。
4. submit 使用一个 `REPEATABLE READ` 事务和每语句 180 秒门禁，在 PostgreSQL 先取得专用 transaction advisory lock；持锁后和 stage 前各检查一次 `queued/running/canceling` 的 `etf_mins` TaskRun。该专用串行化没有修改共享 `TaskRunCommandService`。
5. 每次 submit 固定一次 UTC/中国日期，只加载一次 Basic requestability snapshot，复算 target hash 并用内存 map 校验所有 action 和 `list_date`。随后把同一 snapshot 交给 P9A plan service，复用 SSE 日历、月度 raw 覆盖和成功显式 TaskRun 覆盖查询，不逐 action 查 Basic，也不复制分钟覆盖算法。
6. 当前完全覆盖的原 action 幂等跳过；仍缺失的代码、频率和日期范围必须与已确认 plan 精确一致。出现部分频率、部分日期或新缺口变化时整批返回 `plan_coverage_changed`，要求重新 Preview，不用旧范围重复请求，也不由 submit 擅自缩改范围。
7. 每个选中 action 只调用 `TaskRunCommandService.stage_task_run()`，创建现有 `dataset_action + etf_mins + maintain + range` 意图；filters 为单代码和原 action 五频率/频率子集。整批 stage 后只 commit 一次，任一失败统一 rollback。request payload 仅附带 plan id、content hash 和 action 序号用于 TaskRun 审计，不改变 resolver、planner、request builder、worker、分页或 writer。
8. P9A/P9B service 与 CLI 目标测试 68 个通过，其中包含使用真实 `TaskRunCommandService` 和 SQLite TaskRun 表验证正式任务契约；ETF Basic DAO/snapshot writer、DatasetActionResolver、ETF 分钟 dataset、TaskRun API 和 P9A/P9B 合计 267 个测试通过；三组子系统依赖/legacy guardrail 16 个通过；Ruff 通过。全量 CLI 59 个通过，唯一失败仍是此前已记录且不在本阶段范围内的 progress reporter 旧问题。另有两个未修改文件导致的既有 dataset-maintenance guardrail 失败，P9B 未越界修复。
9. 该开发阶段没有执行 submit 命令，没有连接 Prod 做写事务，没有创建 TaskRun、请求 Tushare、运行 worker、修改业务数据或部署。后续生产使用与停止结果见 P12；旧实现现已禁止再次提交。

### P10：候选环境总回归与发布门禁

1. 执行全部后端目标测试、架构边界测试、前端 typecheck/rules/test/build。
2. 在临时 PostgreSQL 从旧 schema 升级并验证新进程启动。
3. 跑一次 Basic 小型完整快照 fixture。
4. 跑一次 fund daily raw 成功/serving 故障注入。
5. 验证 Health、eligible candidate、pool/rule/runtime 和 review 404。
6. 按第 9 节受控 SQL复核下游统计，并运行分钟 preview；禁止事实删除、生产 TaskRun 和真实补拉。
7. 复核 Alembic head/current、旧引用 0、`index_series_active` 正常。

完成门禁：D1-D20 测试矩阵全部有证据，不能只以“测试总数通过”代替口径对账。

#### P10 执行记录（2026-08-29）

1. 在 `/private/tmp` 创建一次性 PostgreSQL 18 候选环境，从旧 Alembic head `20260828_000156` 完整升级到 `20260829_000157`。历史迁移需要的 `lake_raw_writer` 角色只在该候选库中按真实前置条件创建；升级后 `ops.etf_series_active` 已不存在，`ops.index_series_active` 及其样本仍存在，Alembic current 与唯一 head 一致。候选环境已停止，未连接或修改 Prod。
2. 候选环境暴露出一个既有迁移历史事实：从空库回放的历史迁移只创建旧 `raw.etf_basic/core.etf_basic` 与 `raw.fund_daily/core.fund_daily_bar` 形态，不能自然得到当前 `raw_tushare/core_serving` 形态。P10 没有伪造迁移历史或扩大 migration 范围，而是在一次性候选库中显式创建当前四个模型表用于业务逻辑 fixture；这不影响本次旧池 drop migration 的真实性，但 P11 只能在已具备当前 schema 的正式环境执行，不得把空库回放当作当前 schema 的构建方式。
3. 新代码启动的候选 Web 进程中 `/api/health` 与 `/api/docs` 均返回 200。Basic 小型完整快照验证 raw 保留 `100000.OF/159919.SZ/510300.SH`，serving 只发布两条 `.SH/.SZ`，重复执行幂等；注入 serving 发布失败时，同一 snapshot 事务完整回滚并保留上一版 raw/serving。
4. fund daily 故障注入验证 raw 三行先独立提交；serving 发布失败返回结构化 `fund_daily_serving_publish_failed`，不回滚 raw、不伪造 serving 成功；重试后 raw 仍为三行，serving 只发布当前合格的 `510300.SH`。
5. D1-D20 目标回归 412 个测试通过；完整 Web 为 870 passed、1 skipped；架构测试 95 个通过；CLI 为 56 passed、1 deselected。被排除的是此前已由用户确认后续单独修复的 progress reporter 旧测试，本阶段没有修改。Ruff、Alembic 单 head、文档完整性和 `git diff --check` 均通过。
6. 前端完整测试 39 个文件、146 个用例通过，typecheck、规则检查和生产构建通过；构建仅保留已有的大 chunk warning。使用项目要求的 Python 3.13 环境执行 `scripts/release-preflight.sh`，Python 编译、Web 冒烟、16 个最小回归、165 个 Web 关键测试、5 个架构测试和前端生产构建全部通过。
7. 生产只读 runbook 使用 `REPEATABLE READ + READ ONLY`、180 秒 statement timeout 和 5 秒 lock timeout，约 80 秒完成并明确 `ROLLBACK`。四个 ETF 下游只有总量行，没有 `NON_EXCHANGE_ETF_SUFFIX`、`CODE_NOT_IN_ETF_MASTER`、`EXCHANGE_MISMATCH`、`PENDING_ETF_HAS_FACT` 或 `LISTED_WITHOUT_LIST_DATE_HAS_FACT`；实时监控 pool/rule 也没有不可请求代码。
8. 同一审计仅发现 `core_serving.fund_daily_bar` 有 3 个代码、2,091 行早于当前 `list_date`。这属于 D7 已明确的“当前 list_date 变晚不追溯删除”边界，因此删除候选仍为 0。受保护身份校验记录 `raw_tushare.fund_daily` 的 1 条 `.OF` 事实和 `raw_tushare.etf_share_size` 的 234,042 行/1,643 个代码；历史 realtime alert/minute stat 均为 0 行，没有执行删除。
9. 使用生产只读连接重新生成 `2026-01-01` 至 `2026-08-28` Preview：当前可请求/参与对齐 ETF 均为 1,647，raw 已覆盖 6,975 个 target/frequency，缺少前缀 1,260 个 target/frequency、尾部 0；最终为 252 个代码、252 个 action、1,774 个 unit，请求边界 1,774–7,096。最早 action 起点为 2026-01-05，最晚为 2026-08-28；`request_target_hash=8972736114ecbd14d3245e6c59d80c63b463752a15db5b8bfe7ee5ca7ebd31c3`。结果与 P9A 规模一致，未调用 submit。
10. P10 后置 CodeGraph 为 2,834 个文件、50,276 个节点和 127,383 条边。`EtfSeriesActive` 无结果，旧 endpoint/CLI/type 只存在于明确退场负向测试；`IndexSeriesActive` 仍有 40 个影响符号；alignment plan/submit 没有 API、schedule、runtime 或前端消费者，只有显式 CLI 入口。P10 没有执行生产 DDL、Basic 重建、TaskRun 创建、Tushare 请求、worker 或分钟补拉。

P10 完成后，当前代码和迁移具备进入 P11 生产维护窗口的条件。这个结论只表示发布门禁通过，不构成生产执行授权，也不包含 P12 的首批 10-action 分钟补拉授权。

### P11：生产切换、Basic 重建与只读审计

本阶段已获得用户单独授权并完成。授权范围只包含新版本切换、`ops.etf_series_active` drop、`etf_basic` 正式快照重建和下游只读验收，不包含分钟补拉或下游事实删除。

原计划顺序：

```text
维护窗口与零运行任务
-> 无兼容版本发布和 drop 激活池表
-> etf_basic 完整快照重建
-> raw/serving 验收
-> 下游只读复核
-> 确认已批准删除候选为 0
-> Health/eligible candidate/monitor 冒烟
-> 恢复相关进程与 schedule
```

若 Basic 重建失败，P1 的快照事务保留上一版 raw/serving；新 selector 会过滤旧 serving 中的 `.OF`，但相关 schedule 保持暂停，必须前向修复并重新验收。若复核意外出现明确非交易所身份，停止并另行评审，不执行事实删除。

#### P11 执行记录（2026-08-29）

1. 用户先完成了正常发布；生产代码为 `6b07ae96c9dab353f801c80c9d77006e12ecc404`，Alembic current/head 均为 `20260829_000157`，`ops.etf_series_active` 已不存在，`ops.index_series_active` 仍有 6,014 行。这意味着实际部署和 drop 早于本次 Basic 维护窗口；文档如实保留该顺序，不把后续验收倒写成迁移前门禁。开工时已再确认旧池无代码消费者、相关开放 TaskRun 为 0，因此没有重跑 migration 或制造补证据。
2. 精确暂停 schedule `1` (`reference_data_refresh`)、`39` (`etf_mins.maintain`)、`40` (`etf_sz_cons.maintain`)，暂停后再次确认 `etf_basic/etf_mins/etf_sz_cons` 开放 TaskRun 为 0。暂停和恢复均调用正式 `OpsScheduleCommandService`，没有直接改 schedule 表。
3. 通过正式 `ManualActionCommandService -> TaskRunCommandService` 仅创建一个 `etf_basic.maintain` TaskRun `9837`。该任务于 11:26:15 开始、11:26:17 结束，状态 `success`，`unit_total/done/failed=1/1/0`，`rows_fetched/saved/rejected=1829/1826/0`。没有二次 Tushare 请求。
4. 完整 snapshot diagnostics 保存在 TaskRun node `15730`，而非 TaskRun 汇总行：`source_rows=1829`、`raw_rows_written=1829`、`raw_before/after=3410/1829`、`serving_before/after=3410/1826`、`added/removed/changed=4/1585/4`。源端 hash 与重建后 raw hash 均为 `0419160d0e213575a3f1ae26d0e53b2b5b574d89d3bf53e1b35e6f80c011c061`，serving hash 为 `256ad66925266b54c25234c66acde45c9ffbf9e83ebc539a632c1625a52d9166`。
5. 物理对账确认 raw 1,829 行（`.OF/.SH/.SZ=3/1033/793`）、serving 1,826 行（`0/1033/793`）；raw `.SH/.SZ` 与 serving 的 14 个业务字段双向差集均为 0。当前可请求 ETF 为 1,647 个。
6. 在同一个 `REPEATABLE READ + READ ONLY` 事务中复跑下游 runbook，明确删除候选仍为 0。`fund_daily_bar`、`etf_minute_bar`、`etf_sh_cons`、`etf_sz_cons` 总行数分别为 1,182,264、67,870,940、5,675,323、11,646,418；仅 `fund_daily_bar` 保留已拍板不删的 3 个代码、2,091 行“早于当前 `list_date`”历史。受保护的 `raw_tushare.fund_daily` 1 条和 `raw_tushare.etf_share_size` 234,042 行/1,643 代码保持；历史 alert/stat 均为 0 行。
7. 生产只读服务冒烟返回 eligible ETF 1,647 个，候选前 50 个全部满足 `L + 有上市日 + SH/SZ 后缀与 exchange 一致`；实时 Health 为 `idle/market_closed`，Redis 连通、collector 正在运行，`source_snapshot_count=2332`、`eligible_snapshot_count=1647`。监控池 3 个且全部 enabled，3 条 global 规则全部 enabled。
8. schedule `1/39/40` 已按原计划恢复为 active，下次执行分别为 2026-08-31 20:00、20:35、20:40；相关开放 TaskRun 仍为 0。Web、Ops worker、Task completion worker、scheduler 和 realtime collector 均为 active，`/api/health` 与 `/api/v1/health` 均返回 `ok/prod`。
9. P11 没有执行下游 DELETE、分钟 alignment submit、分钟补拉、第二个 Basic TaskRun 或其他数据集任务。

### P12：分钟全量补拉与最终对账

本阶段的旧分批方案已停止，并已按第 10 节改用普通手动任务多代码契约完成开发、部署、生产执行和对账：

1. 保留已成功和已完成 unit 的业务数据，不回滚、不删除。
2. 后续范围只由新 Preview 根据 raw 覆盖计算，不依赖已取消 TaskRun 的零值汇总。
3. 普通 `etf_mins` 手动动作接收多个显式代码，一次只创建一个 TaskRun，由现有 planner 展开 unit。
4. 一个 TaskRun 仍按 unit 独立提交；失败、取消、进度和 retry 全部沿用现有语义，不增加 alignment 特例。
5. 代码能力通过、新代码部署且再次取得生产授权后，确认没有 open 任务并避开 schedule 39；预计重叠时才暂停 schedule。
6. 最终以 raw 覆盖和只读 Preview 对账，确认 prefix/suffix 缺口归零或有明确失败原因；如曾暂停 schedule 39，再恢复它。

P12 不执行下游 DELETE，也不能用“P11 已授权”代替额度确认。

#### P12 Preview 执行记录（2026-08-29）

1. 开工前确认生产 `core_serving.etf_basic=1826`、当前可请求 ETF 1,647 个、开放 `etf_mins` TaskRun 为 0、成功历史 TaskRun 为 10。输出路径不存在，没有覆盖旧计划。
2. 在已部署的生产 CLI 上仅运行一次 `ops-preview-etf-minute-alignment --alignment-start-date 2026-01-01 --alignment-end-date 2026-08-28`。CLI 使用 `REPEATABLE READ + READ ONLY`、每语句 180 秒 timeout 并在写 JSON 前 rollback；约 32 秒完成，没有月度查询超时。
3. 新计划 `plan_id=etf-minute-alignment-d9667f342dc64a33ac154917b923a618`，`plan_content_hash=d31ac369d8c115b905735f1c0c92adb0cbca4004818494c36ef644c4568dfe80`，`request_target_hash=8972736114ecbd14d3245e6c59d80c63b463752a15db5b8bfe7ee5ca7ebd31c3`。完整 JSON 的 canonical content hash 和远端/本机文件 SHA-256 均已校验。
4. 可请求/参与对齐 ETF 均为 1,647，`list_date` 晚于截止日的对象为 0。raw 已覆盖 6,975 个 target/frequency，缺少前缀 1,260 个 target/frequency、尾部 0，成功 TaskRun-only 覆盖为 0；V1 仍不审计内部缺口。
5. 最终计划为 252 个代码、252 个 action、1,774 个 unit，源请求下界 1,774、分页上界 7,096。每个 action 都合并五个频率；167 个 action 从 2026-01-05 开始，其余 85 个按各自的 2026 年上市日后首个 SSE 开市日开始，全部截止到 2026-08-28。
6. 重建前后 `request_target_hash` 和 252 个 action 完全相同；只有排除统计从 `NON_EXCHANGE_SUFFIX=1585 / LIST_DATE_NULL=8 / LIST_DATE_AFTER_AS_OF=1` 变为 `NON_EXCHANGE_SUFFIX=0 / LIST_DATE_NULL=7 / LIST_DATE_AFTER_AS_OF=3`，与 Basic 重建结果一致。
7. Preview 当时拟采用已拍板的 `batch-size=10`，首批是 `158000.SZ`、`158001.SZ`、`158003.SZ`、`158005.SZ`、`158006.SZ`、`158008.SZ`、`158009.SZ`、`158010.SZ`、`158012.SZ`、`158017.SZ`，共 50 个 unit、50–200 次源请求；该次只读操作没有 submit。
8. Preview 后只读回查仍为成功 `etf_mins` TaskRun 10 个、开放 TaskRun 0，证明该次操作没有创建任务、请求 Tushare 或写入分钟表。计划 JSON 只保存在生产服务器和本机 `/private/tmp/p12-etf-minute-alignment-post-basic-20260829.json`，不纳入仓库。

#### P12 首批执行与对账记录（2026-08-29）

1. 用户明确授权使用 `plan_content_hash=d31ac369d8c115b905735f1c0c92adb0cbca4004818494c36ef644c4568dfe80` 和 `batch-size=10`。提交前再次确认计划文件 SHA-256 为 `e6e511a6216565aa2875c42afc6e0a8fd807e4ae845e5888ab7759653b31e6da`、当前可请求 ETF 1,647 个、开放 `etf_mins` TaskRun 0，Ops worker 与 Task completion worker 均为 active。
2. 正式 submit 命令只运行一次，原子创建 TaskRun `9842-9851`，精确对应原计划 action 1-10；`skipped_covered_action_count=0`，提交时返回剩余 action 242 个。没有重复提交、补建任务或运行第二批。
3. 10 个 TaskRun 全部为 `success`，50/50 unit 完成、失败 0；抓取 20,223 行、保存 20,223 行、拒绝 0、去重 0、TaskRun issue 0。首个任务开始时间为 12:01:01.916，最后任务结束时间为 12:01:23.352，批次墙钟 21.436 秒。
4. node source diagnostics 显示 50 个 unit 各请求 1 页，实际总页数 50、重试 0、分页 unit 0；因此首批真实请求数落在计划的 50–200 边界内，并取得了后续批次可参考的真实证据。
5. 对 10 个代码、五个频率和各自 action 日期范围做有界物理回查，行数合计正好为 20,223，与 TaskRun 抓取/保存数一致。50 个代码/频率组合均有数据，首尾交易日都精确覆盖各自 action 起止日；`raw_tushare.etf_minute_bar` 主键仍为 `(ts_code, freq, trade_time)`，数据库层禁止重复键。
6. 批后只读 Preview 生成新计划 `plan_id=etf-minute-alignment-0562237e7d524bd18fb2f9b1f9715c23`、`plan_content_hash=529603c834a5812bdbcaca742322387506475217df58e7b3bfaba9bcdb040d9f`；远端和本机 JSON 文件 SHA-256 均为 `7e0147287df2876fb5f362866915cefe08c46ce05902f02b90a7068dcdd6322f`。
7. 批后 `request_target_hash` 仍为 `8972736114ecbd14d3245e6c59d80c63b463752a15db5b8bfe7ee5ca7ebd31c3`，证明 Basic 请求身份没有漂移。原首批 10 个代码在新计划中出现数为 0；计划降为 242 个 action、1,724 个 unit，请求边界 1,724–6,896，尾部缺口仍为 0。
8. 首批授权至此已消费完毕。新计划只保存在生产服务器和本机 `/private/tmp/p12-etf-minute-alignment-after-batch1-20260829.json`，不纳入仓库；提交第二批前必须重新向用户展示范围并取得明确授权。

#### P12 后续队列停止与设计纠偏记录（2026-08-29）

1. 用户曾明确授权以批后 `plan_content_hash=529603c834a5812bdbcaca742322387506475217df58e7b3bfaba9bcdb040d9f` 和 `batch-size=242` 一次提交剩余 action。提交前计划文件、Basic 1,647 个当前可请求对象、开放任务 0 和 worker 状态均通过门禁；CLI 只运行一次并原子创建 TaskRun `9862-10103`，没有跳过 action。
2. 运行过程中用户指出“一代码一 TaskRun”造成大量任务记录，不符合“一次 alignment 作业、任务内展开全部代码”的运维目标，并明确要求停止。停止动作只使用现有 `TaskRunCommandService.request_cancel()`：61 个任务已成功，181 个任务已取消，当前 queued/running/canceling 均为 0；没有停止整个 Ops worker，也没有影响其他任务。
3. 61 个成功任务共完成 388 unit、保存 1,603,395 行，失败和拒绝均为 0。取消任务 `9923`（`159539.SZ`）在停止前已完成 3/8 unit；其 TaskRun 汇总行为 0 不代表业务 unit 未提交，因此必须依靠 raw 覆盖重新 Preview，禁止从 TaskRun 状态猜测剩余范围。
4. 当前 planner 的显式 `ts_code` 路径明确拒绝多个代码；不传 `ts_code` 则读取 ETF Basic Serving 全部当前可请求 ETF。因而现有代码不能通过“传代码数组”或“省略代码”正确实现目标：前者校验失败，后者会对已覆盖 ETF 产生大量重复请求。
5. 后续评审进一步收敛：不再冻结 alignment actions，也不新增专用执行 payload。普通 `dataset_action / etf_mins` TaskRun 保存多代码、统一日期和五频率，由 `DatasetActionResolver` 进入既有 planner；不得省略代码、不得绕过主链直接调用 connector/writer。
6. 影响面因此缩小为 DatasetDefinition、ETF 分钟 target 解析、普通手动契约测试和旧 Submit 删除；dispatcher、TaskRun 进度/取消/retry 和数据库 schema 均不修改。当前生产停止在安全终态，不得继续使用旧 242-action plan 或再次运行旧 Submit。

#### P12 停止后 Preview 记录（2026-08-29）

1. 在确认 open `etf_mins` TaskRun 为 0 后，只运行一次生产只读 Preview；事务、超时、rollback 和无 Tushare/无 TaskRun 口径与 P9A 相同。
2. 新计划 `plan_id=etf-minute-alignment-a5369660785243e480e88da042de98dc`，`plan_content_hash=86ff27cc39b24f843165c155126ec27950f80f2fe86a12e17738453da0e73d24`，`request_target_hash=8972736114ecbd14d3245e6c59d80c63b463752a15db5b8bfe7ee5ca7ebd31c3`。远端和本机文件 SHA-256 均为 `f76eafcf26b5cac385f4ce7369f96a2bb7ffcc4c99d40c1322b5ae6c5bfaeab5`。
3. 当前可请求/参与对齐 ETF 均为 1,647；待补 181 个代码、182 个 action、1,333 个 unit，源请求下界 1,333、分页上界 5,332。
4. `1min` 有 181 个 action、609 个 unit，前缀 180、尾部 1；其他四个频率各 181 个 action、181 个 unit，前缀各 181、尾部 0。
5. `159539.SZ` 的精确缺口分成两个 action：四个非 `1min` 频率为 `2026-01-05..2026-08-28`（4 unit），`1min` 为 `2026-07-01..2026-08-28`（1 unit）。普通手动任务采用统一起点后，会为其额外生成 2026 年上半年的三个 `1min` 窗口。
6. Preview JSON 继续只作为只读审计证据，不写入 TaskRun，也不再由 Submit service 消费。

#### P12 普通手动任务多代码扇开开发步骤

##### R0：安全停止与设计基线（已完成）

1. 停止旧队列，确认 61 个成功、181 个取消、open 任务 0。
2. 使用 raw 事实重跑 Preview，冻结上述 181 代码/182 action/1,333 unit 基线。
3. CodeGraph 已覆盖 Definition、manual action API/服务/前端、catalog、schedule contract、resolver/unit planner、Preview/Submit service 和相邻 ETF planner 消费者；确认现有手动主链已支持多值元数据和数组保存，只需把多代码能力限定到 `etf_mins`，不能放宽沪深申赎清单。Definition 的共享影响已明确：schedule 技术上可传数组，但现有 schedule 39 无 `ts_code`，本需求不修改其配置。

##### R1：Definition 与 ETF 分钟 planner（已完成）

目标文件：

```text
src/foundation/datasets/definitions/market_fund.py
src/foundation/ingestion/unit_planner.py
src/foundation/ingestion/etf_minute_windows.py（只复用，不修改）
```

开发任务：

1. 将 `etf_mins.ts_code` 改为 `multi_value=True`，描述明确逗号多代码和空值全量语义。
2. 一个代码继续只查一次 `get_requestable_target()`；两个及以上代码只加载一次 requestability snapshot。
3. 规范化、去重和排序输入；任一代码不合格时整次 `etf_not_requestable`，不生成部分 unit。
4. 按每个 target 的 `list_date` 独立裁剪，再按代码 × 频率 × 现有窗口函数稳定展开。
5. 明确保护无代码全量和单代码路径，并证明沪深申赎清单仍拒绝多代码。

##### R2：删除旧 Submit，复用普通手动动作（已完成）

删除文件：

```text
src/ops/services/etf_minute_history_alignment_submit_service.py
tests/test_etf_minute_history_alignment_submit_service.py
tests/test_cli_ops_submit_etf_minute_alignment.py
```

精确修改：

```text
src/ops/services/etf_minute_history_alignment_plan_service.py
src/cli.py
src/cli_parts/ops_handlers.py
```

开发任务：

1. 删除 `ops-submit-etf-minute-alignment` 的 service import、CLI 注册和 handler，不保留 alias。
2. 保留 `EtfMinuteHistoryAlignmentPlanService`、Preview CLI 及其测试；修改 `_parse_task_coverage()` 兼容历史单代码字符串和新多代码数组。
3. 不修改 `ManualActionCommandService`、`ManualActionTaskRunResolver` 和 API schema；它们现有多值契约直接承载本需求。

##### R3：契约、planner 与前端测试（已完成）

目标测试：

```text
tests/test_etf_mins_dataset.py
tests/test_dataset_action_resolver.py
tests/test_etf_minute_history_alignment_plan_service.py
tests/web/test_ops_manual_actions_api.py
tests/web/test_ops_catalog_api.py
frontend/src/pages/ops-v21-task-manual-tab.test.tsx
```

开发任务：

1. Definition、catalog、manual API 均暴露 `ts_code.multi_value=true`。
2. 逗号字符串最终保存为一个 TaskRun 的代码数组；planner 再做大写、去重和稳定排序，并且只创建一个 TaskRun。
3. 多代码只做一次 snapshot 查询，unit 按代码/频率/窗口稳定展开，request builder 每次只收到一个标量代码。
4. 任一未知、`.OF`、P/D、空/未来上市日或交易所冲突代码使整次计划失败；不得部分请求。
5. Preview 对成功 TaskRun 同时识别历史字符串代码和新数组代码，按代码 × 频率还原覆盖；空/非法数组和无代码任务继续忽略。
6. 上市日裁剪、无代码全量、单代码查询和沪深申赎单代码门禁全部回归。
7. schedule 39 的无代码全量计划保持不变；Definition 多值元数据不会替它写入显式代码。
8. 前端提交多代码数组；不新增页面布局、专用控件或 alignment 文案。

##### R4：静态清零与发布门禁（已完成）

1. Submit service、CLI、handler 和专属测试引用清零；Preview 保持可用。
2. 确认没有新增 alignment intent、payload marker、dispatcher 分支、TaskRun 生命周期特例、Settings、表、字段或 task type。
3. 运行 Ruff、目标后端测试、CLI 回归、前端目标测试/typecheck/rules/build、架构依赖矩阵、文档完整性和 `git diff --check`。
4. CodeGraph 后置复核只新增 Definition -> manual action -> ETF minute planner 的既有链路能力，没有影响相邻 ETF 数据集。
5. 不连接 Tushare，不写 Prod，不创建 TaskRun，不修改 migration。

##### R1-R4 实施记录（2026-08-29）

1. `market_fund.py` 已将 `etf_mins.ts_code` 改为可选多值字符串；manual action 和 catalog 继续从 Definition 投影契约，未新增 ETF 专用 API 字段或前端控件。Web 契约测试使用两条合格 Basic 样本证明：一次 POST 只创建一个普通 `dataset_action / etf_mins` TaskRun，`filters_json.ts_code` 为代码数组。
2. 共享 `_resolve_requestable_etf_targets()` 只增加由 `_resolve_etf_mins_targets()` 显式开启的 `allow_multiple_explicit` 分支。单代码仍只查一次 target；两个及以上代码只加载一次 snapshot，按规范化代码建 map，任一代码未命中时整次 `etf_not_requestable` 并返回稳定排序的 `invalid_ts_codes`。沪深申赎未开启该分支，仍在 Basic 查询前拒绝多代码。
3. planner 继续对每个 target 独立执行 `max(requested_start, list_date)`，再按代码、固定频率顺序和现有切窗顺序展开。测试确认每个 unit/request 只含一个标量 `ts_code`，多代码数量不放大 Basic 查询次数，显式代码中任一整体早于上市日期时整次拒绝。
4. 旧 `EtfMinuteHistoryAlignmentSubmitService`、两份专属测试、CLI handler 和 `ops-submit-etf-minute-alignment` 注册已删除，没有 alias 或 fallback。Preview service/CLI 保留；`_parse_task_coverage()` 同时识别历史单代码字符串与新的非空字符串数组，规范化后按代码 × 频率还原覆盖；空、混合类型或含空字符串的数组整条忽略。
5. 目标后端回归 247 项通过，包含 Definition、resolver/planner、Preview、manual API、catalog 和 Preview CLI；架构依赖/legacy 护栏 61 项通过；Ruff 通过。前端目标页 18 项与全量 147 项测试通过，typecheck、rules 和生产 build 通过。全量 CLI 回归为 52 通过、1 个已知失败：`test_attach_cli_progress_reporter_emits_throttled_progress`；该失败已在 P8-P10 记录，本轮未修改 `src/cli_parts/shared.py` 或其测试，按范围不越界修复。
6. 后置 CodeGraph sync 后索引为 2,833 个文件、50,254 个节点、127,286 条边。`_resolve_requestable_etf_targets` 的生产影响面仍只有沪市申赎、深市申赎和 ETF 分钟三条 planner 链；`_parse_task_coverage` 的生产消费者仍只有 Preview 内部加载链。静态搜索确认 Submit 类、service import、handler 与 CLI 注册在生产代码中为零，测试只保留旧命令不存在的负向断言。
7. R1-R4 开发阶段没有连接 Tushare、写入 Prod、创建 TaskRun、修改 schedule/Settings/dispatcher/TaskRun 生命周期或增加 migration。R5 后续在独立生产授权下执行，证据见下节。

##### R5：部署后的生产执行（已完成，2026-08-29）

```text
确认 open etf_mins TaskRun = 0
-> 避开 schedule 39；预计重叠时才暂停
-> 在手动维护页粘贴 181 个逗号分隔代码
-> 输入 2026-01-05..2026-08-28 和五个频率
-> 预检确认一个 TaskRun、预计 1,336 个 unit
-> 获得独立授权后提交一次
-> 按现有任务能力监控
-> 复核 raw 物理覆盖和最终 Preview
-> 如曾暂停则恢复 schedule 39
```

R5 执行记录：

1. 生产代码部署后，只读门禁确认旧 TaskRun `9862-10103` 仍为 61 个成功、181 个取消，开放 `etf_mins` TaskRun 为 0；schedule 39 下次触发为 2026-08-31 20:35，不与本轮重叠，未暂停计划。
2. 停止后 Preview 的 181 个去重代码全部仍满足 Basic 当前可请求条件；生产当前 planner 预检确认统一 `2026-01-05..2026-08-28` 和五频率输入展开 181 个代码、1,336 个 unit。
3. 获得独立执行授权后只创建一个普通 `dataset_action / etf_mins` TaskRun `10117`；`filters_json.ts_code` 精确保存上述 181 个代码，`filters_json.freq` 为五频率，与停止后清单的 SHA-256 比对一致。TaskRun `10103` 之后只有这一个新 `etf_mins` 任务。
4. TaskRun `10117` 于 17:04:07 开始、17:48:14 结束，状态 `success`，耗时 2,646.357 秒；`unit_total/done/failed=1336/1336/0`，`rows_fetched/saved=7606095/7606095`，拒绝、去重、primary issue 和 TaskRun issue 均为 0。
5. 补后使用相同 `2026-01-01..2026-08-28` 口径重跑只读 Preview，生成 `plan_id=etf-minute-alignment-ec27ce95c85b4c29aa4c5ab051e13f90`、`plan_content_hash=ec836cc7722f22b44ad13266eeace59a334ebd459d910c3c95207e1253b7ca72`；`request_target_hash` 仍为 `8972736114ecbd14d3245e6c59d80c63b463752a15db5b8bfe7ee5ca7ebd31c3`，请求身份集合未漂移。
6. 可请求/参与对齐 ETF 均为 1,647；8,235 个 target/frequency 组合全部由 raw 物理数据覆盖，TaskRun-only 覆盖为 0，prefix/suffix 缺口、action、unit 和请求边界均为 0。`interior_gap_not_audited=true` 仍是已拍板边界，不把该结论扩大为区间内每个分钟都已连续对账。
7. 最终开放 `etf_mins` TaskRun 为 0，未执行下游 DELETE、数据库迁移、schedule 修改或额外 TaskRun。至此 P12 的分钟补拉与对账范围关闭；整个需求仍须通过下文“旧激活池消费者生产补充验收”后才能正式关闭。

#### 旧激活池消费者补充验收：截至 2026-08-29 的证据状态

本轮文档治理未核实此后生产运行；以下待验不是断言今天仍未运行，也不因代码回归通过而自动关闭。

##### 1. 缺口依据与验收目标

2026-08-29 在关闭后复核中确认：迁移到 ETF Basic 的代码链已经完成自动化回归，但除 `etf_mins` 外，不能证明所有原激活池消费者都在新代码和重建后的 Basic 上真实运行过。当前证据如下：

| 消费者 | 自动化证据 | 切换后生产证据 | 当前结论 |
|---|---|---|---|
| `etf_mins` | planner、上市日裁剪、多代码和 writer 回归通过 | TaskRun `10117` 成功，补后 Preview 缺口为 0 | 已满足，不得重复请求 |
| `etf_sh_cons` | 自动/显式 planner、SH scope、上市日裁剪和 writer 回归通过 | 2026-08-29 全量只读计划与单代码 TaskRun `10126` 均通过 | 已满足，不得扩大为 921 个源请求 |
| `etf_sz_cons` | 自动/显式 planner、SZ scope、上市日裁剪和 writer 回归通过 | 最近成功 TaskRun `9769` 在切换前；schedule `40` 下一次自然运行尚未发生 | 待首次切换后自然调度验收 |
| `fund_daily` serving | raw/serving 两阶段、Basic 过滤和失败隔离回归通过 | 2026-08-29 单交易日 TaskRun `10127` 及 Raw/Serving 物理对账通过 | 已满足，不得重复请求同一日期 |
| ETF 实时 Health/候选/monitor | eligible candidate、pool/rule 门禁和 runtime 求交回归通过 | 休市只读冒烟已通过；没有开市自然批次的 monitor 证据 | 待开市自然批次验收 |
| ETF Review | 退场 API 404 和相邻指数/板块回归通过 | 已删除 | 不再要求运行 |

本轮重新执行 Basic、三个 planner、三个 writer/两阶段 executor、实时 Health/monitor 和 Review 退场相关定向测试，共 `256 passed`。这证明代码路径可运行，但不能替代下列生产验收。

##### 2. 总体执行约束

1. 每次操作开始时固定中国自然日和一份 `core_serving.etf_basic` 当前可请求快照；记录总数、SH/SZ 分市场数量和互斥排除统计。验收不得重新拼装状态条件，也不得读取已删除的 `ops.etf_series_active`。
2. 只选择已经完成交易且源端数据已就绪的最近 SSE 开市日。不得用未来日期、当日未完成数据或纯休市日期制造成功结果。
3. 每个数据集开始前确认相同 `resource_key` 没有 `queued/running/canceling` TaskRun，并复核相关 schedule 的上次/下次触发时间。存在自然调度时优先等待自然运行，禁止再建重复手工任务。
4. 任何手工生产任务都必须先用当前 resolver/planner 做只读预检，记录 TaskRun 数、unit 数、代码数、日期和预计源请求量；实际提交必须与预检完全一致，并在源请求前另获用户明确授权。
5. 每次只允许一个验收对象进入执行，上一项 TaskRun、物理数据和 TaskRun issue 尚未对账完成时不得开始下一项。不得合并为 workflow，也不得借验收扩大历史补拉范围。
6. 不修改 DatasetDefinition、request builder、writer、schedule、monitor pool/rule、Settings、数据库 schema 或源端限速；不执行 DELETE、清表、重建、迁移、假告警或额外 Basic 同步。
7. TaskRun 失败、selector 异常、unit 数与预检不一致、出现 `.OF`/交易所冲突/空或未来上市日、源端未就绪、额度不足或 schedule 重叠时立即停止。不得回退旧池、盲目 retry 或重复请求同一范围。
8. 验收证据必须来自当前生产代码、TaskRun/node/issue、限定范围的物理表只读对账和实时 collector 日志；页面成功提示、历史任务或单元测试不能单独作为生产通过证据。

##### 3. `etf_mins`：复用既有证据，不重复执行

1. 复用 TaskRun `10117` 的 `1336/1336/0` unit、`7,606,095/7,606,095/0` 抓取/保存/拒绝结果和无 issue 证据。
2. 复用补后 Preview：1,647 个当前可请求 ETF 的 8,235 个代码/频率组合均有 raw 首尾覆盖，prefix/suffix、action 和 unit 均为 0。
3. `request_target_hash` 必须与任务前保持一致；`interior_gap_not_audited=true` 继续是本需求边界。
4. 本项已经通过。不得为了统一流程再次创建分钟 TaskRun或请求 Tushare。

##### 4. `etf_sz_cons`：等待 schedule 40 的自然运行

1. 保持 schedule `40` active，不提前手工触发；以切换后第一次正常 `etf_sz_cons.maintain` TaskRun 为验收对象。
2. 调度生成的 point 计划必须无显式 `ts_code`，只加载一次 SZ scope Basic snapshot；`unit_total` 必须等于本次预检中 `list_date <= trade_date` 的当前可请求 `.SZ` ETF 数，每个 unit 只含一个 `.SZ` 标量代码，且 `trade_date >= list_date`。
3. TaskRun 必须 `success`、`unit_done=unit_total`、`unit_failed=0`、`rows_fetched>0`、`rows_saved>0`、`rows_rejected=0`，且没有 primary issue 或 TaskRun issue。
4. 物理对账限定本次交易日：raw 中不得出现非 `.SZ`、exchange 冲突、不在同次 Basic 快照或早于 `list_date` 的本轮新增身份；TaskRun/node 的代码集合必须与预检集合相同。
5. 如果自然调度没有创建任务、任务形状不同或失败，先审计 scheduler、resolver、源端和 writer 根因；不得立即补一个手工任务掩盖自然链路问题。

##### 5. `etf_sh_cons`：全量只读计划 + 单代码生产任务

1. 当前没有 `etf_sh_cons` schedule。选择一个最近且源端已就绪的 SSE 开市日，先用生产当前 resolver/planner 构建一次无显式 `ts_code` 的只读 point 计划；该步骤不得创建 TaskRun或请求 Tushare。
2. 全量只读计划必须只加载一次 SH scope Basic snapshot；`unit_count` 必须等于 `list_date <= trade_date` 的当前可请求 `.SH` ETF 数。全部 unit 只能包含一个 `.SH` 标量代码，`trade_date >= list_date`，代码集合与同次 Basic 快照裁剪结果完全一致。
3. 源请求和 writer 的生产验收只选择上述计划中的一个合格、已有稳定历史数据的 `.SH` ETF，以同一交易日提交一个普通 `etf_sh_cons.maintain` point TaskRun。单代码实际任务必须只调用一次 `get_requestable_target()`，计划只有一个 unit，源请求参数精确为该 `ts_code + trade_date`。
4. “全量只读计划”证明自动 snapshot 展开，“单代码生产任务”证明 Basic 门禁、request builder、Tushare connector、分页和 writer；两项与已通过的自动 planner 回归共同构成验收，不为验证 fan-out 消耗全部 SH ETF 的源请求额度。
5. 单代码 TaskRun 必须 `success`、`unit_total=unit_done=1`、`unit_failed=0`、`rows_fetched>0`、`rows_saved>0`、`rows_rejected=0`，且没有 primary issue 或 TaskRun issue。
6. 物理对账限定本次 `ts_code + trade_date`：raw 行数必须与 TaskRun 保存数一致，主键无重复，代码为 `.SH`，并且该代码在同次 Basic 快照中满足当前可请求且 `trade_date >= list_date`。

##### 6. `fund_daily`：一个交易日的全市场两阶段任务

1. 选择一个最近且源端已就绪、尚无同范围开放任务的交易日，使用普通 `fund_daily.maintain` point 动作，`filters` 保持空，不传 `ts_code`。这仍是一次全市场源请求，不按 ETF Basic 逐代码展开。
2. TaskRun 必须只有一个日期 unit 并最终 `success`、`unit_done=unit_total=1`、`unit_failed=0`、`rows_fetched>0`、`rows_rejected=0`，且没有 `fund_daily_serving_publish_failed`、primary issue 或 TaskRun issue。
3. raw 阶段必须完整保存该交易日源端返回，不因 Basic 过滤减少；serving 阶段只发布同次 Basic 当前可请求代码且 `trade_date >= list_date` 的行。`rows_saved` 按现行契约表示 serving，不要求与 `rows_fetched` 相等。
4. 在同一个只读快照中计算“该交易日 raw 规范行与 Basic 资格求交”的期望集合，与 `core_serving.fund_daily_bar` 做双向 `EXCEPT ALL`；两个方向差集都必须为 0。排除数量必须能按不在 Basic、早于上市日等现有 reason code 对账。
5. 如果 raw 已提交但 serving 失败，保留 raw，TaskRun 必须失败并停止验收；不得声称成功，也不得盲目重请求源端。先定位 selector/serving 根因并另行决定修复方式。

##### 6.1 2026-08-29 已完成生产验收记录

1. 开工预检在一个 `REPEATABLE READ + READ ONLY` 事务中固定中国自然日 `2026-08-29` 和最近 SSE 开市日 `2026-08-28`。同一次 `EtfBasicDAO.load_requestability_snapshot()` 得到当前可请求 ETF 1,647 个，其中 SH 921、SZ 726；互斥排除为 `LIST_DATE_AFTER_AS_OF=3`、`LIST_DATE_NULL=7`、`STATUS_NOT_LISTED=169`。相关数据集没有开放 TaskRun；仅 `etf_sz_cons.maintain` 存在 active schedule `40`，下一次自然运行是 2026-08-31，因此本日没有提前触发 SZ 任务。
2. `etf_sh_cons` 无代码 point 预检只构建只读计划 `etf_sh_cons:maintain:point_incremental:b99391449cb65b4e`，没有创建 TaskRun 或请求 Tushare。计划 921 个 unit 与同次 SH Basic snapshot 的 921 个代码逐项完全一致，证明生产 resolver 会按 Basic 自动全量展开；由于源接口的一个 unit 只携带一个标量 `ts_code`，若真实执行该计划会产生约 921 次代码级源请求，因此验收没有执行这个全量计划。
3. `etf_sh_cons` 只从上述集合选取 `510300.SH`，以同一交易日创建一个普通 point TaskRun `10126`。TaskRun 和 node `15839` 均为 `success`，计划键为 `etf_sh_cons:maintain:point_incremental:36c2482eeceb7775`，`unit_total/done/failed=1/1/0`，抓取/保存/拒绝/去重为 `300/300/0/0`，primary issue 和 TaskRun issue 均为 0。物理表限定 `510300.SH + 2026-08-28` 为 300 行、300 个不同成分代码，本轮 `fetched_at` 与 node 执行窗口一致，错误代码、错误日期和重复主键均为 0。该项以 1 次真实源请求完成自动展开、单对象 Basic 门禁、request builder、connector、分页和 writer 的组合验收，不再请求其余 920 个代码。
4. `fund_daily` 预检计划为 `fund_daily:maintain:point_incremental:b6e972635ee6fbab`，只有一个日期 unit，请求参数只含 `trade_date=20260828`，不会按 ETF 逐代码展开。普通 point TaskRun `10127` 和 node `15840` 均为 `success`，`unit_total/done/failed=1/1/0`，只发生 1 页源请求且没有 retry，抓取 2,112 行；Raw upsert 2,112 行并先独立提交，Serving upsert 1,647 行，拒绝和去重均为 0，primary issue 和 TaskRun issue 均为 0。Serving 诊断按 `CODE_NOT_REQUESTABLE_AT_PUBLISH` 排除 465 行，与抓取数和发布数精确相抵。
5. `fund_daily` 后置物理对账在新的 `REPEATABLE READ + READ ONLY` 事务中再次通过公共 Basic snapshot 取得 1,647 个当前可请求代码，而不是在审计 SQL 中另拼状态条件。`2026-08-28` 的 Raw 为 2,112 行/2,112 个代码，其中 465 个不在当前可请求集合、早于上市日为 0；期望 Serving 和实际 Serving 均为 1,647 行/1,647 个代码，缺失、额外和九个业务数值字段不一致均为 0。该项证明 Raw 保留源端全集、Serving 精确使用 Basic 资格发布。
6. 上述两个手工任务按顺序执行，上一项完成 TaskRun、issue 和物理对账后才开始下一项；没有修改 schedule、配置、schema 或代码，没有 DELETE、Basic 重建、历史补拉或重复的独立 Tushare 探测。`etf_sh_cons` 与 `fund_daily` 的补充生产门禁现已通过；后续只等待 schedule `40` 的首次切换后自然运行和一个 ETF 实时开市自然批次。

##### 7. ETF 实时链：等待开市自然批次

1. 不手工请求 Tushare、不修改实时配置、monitor pool、规则或阈值；等待现有 realtime collector 在开市时产生一个正常 `etf_rt_daily` batch。
2. 同一批次必须满足 collector `status=ok`、`batch_id` 非空、`fetched_rows>0`、`snapshot_count>0`、`invalid_count=0`；Health 的 `eligible_etf_count` 必须等于同一中国自然日 Basic snapshot 的 requestable count。
3. 候选接口返回 200，total 与同日 Basic requestable count 一致；抽查项全部满足 `L + 有效 list_date + .SH/.SZ 后缀与 exchange 一致`。旧 `/active-etfs` 继续为 404。
4. 对同一个 batch，collector 日志必须出现 `monitor_status=ok` 且 `failed=0`；enabled monitor pool 与 Basic requestable codes 的交集必须非空，Redis 中不合格 ETF 即使有快照也不得进入监控输入。
5. `evaluated` 和 `alerts` 可以因基线、数据质量、规则阈值或冷却为 0，不作为失败条件；不得通过降低阈值、伪造历史基线或制造告警来通过验收。

##### 8. 最终关闭条件与证据回填

只有以下条件全部满足，本需求才能再次标记“正式关闭”：

1. `etf_mins` 既有生产证据复核通过，没有重复请求。
2. `etf_sz_cons` 首次切换后自然 schedule TaskRun 通过全部计划、TaskRun 和物理对账条件。
3. `etf_sh_cons` 的无代码全量只读计划与一个单代码 point TaskRun 分别通过自动展开、端到端执行和物理对账条件。
4. `fund_daily` 一个交易日全市场 TaskRun 通过 raw/serving 两阶段和双向差集对账。
5. ETF 实时链一个开市自然批次通过 Basic eligibility、候选、Health 和 monitor 日志门禁。
6. 所有相关 `resource_key` 最终开放 TaskRun 为 0；没有新增未解释 issue、重复任务、schedule 漂移或旧激活池引用。
7. 将任务编号、日期、Basic 数量、unit、请求/保存/排除、物理差集、实时 batch 和日志证据回填本节；同步主方案和 `docs/README.md` 状态，再运行文档完整性检查。

任一项未满足时，已通过的其他项保留，不回滚业务事实；文档状态保持“补充生产验收待完成”，不得用“自动化测试全部通过”替代生产证据。

---


## 14. 测试与硬口径对账

| 方案决策 | 必须落到的代码/测试 |
|---|---|
| D1-D3 | Basic Definition、snapshot validator/writer；完整 raw、单事务替换、失败回滚 |
| D4 | 禁止 OF rename/merge；当前无旧 OF 下游候选；未来非零时停止并另立精确方案 |
| D5-D9 | Basic DAO + 三个 planner；状态、日期、后缀、切窗和无退市日上界测试 |
| D10-D11 | serving 后缀测试；公募基金保护表 checksum；3 条 OF 仅 raw fixture |
| D12 | 全量引用清零、drop-table migration、无 fallback 负向测试 |
| D13 | 不新增通用事实 cleanup service/CLI/删除 manifest/apply；旧 cleanup 在 P4 直接退场 |
| D14 | 无新历史表/字段；仅 `etf_basic` 正式快照 TaskRun 的现有 diagnostics 承载主数据 hash/摘要，不外推为所有 planner/monitor 的统一诊断 |
| D15 | 日常 Basic 变化测试只影响新计划，不调用事实 DELETE |
| D16 | CodeGraph + 字符串 + DB 六层清零、维护窗口发布顺序 |
| D17 | fund daily/fund adj/share size 默认全市场请求不扇出；显式入口定位测试 |
| D18 | raw/core/直出 view 零删除保护测试 |
| D19 | fund daily 两阶段 serving gate；fund_adj/share size 零改动回归 |
| D20 | realtime provider 固定通配符请求快照测试；只替换 health/候选 |

### 14.1 后端目标测试

维护时从以下现有测试按影响范围选择：

```text
tests/test_etf_basic_dao.py
tests/test_etf_basic_snapshot_writer.py
tests/test_dataset_definition_registry.py
tests/test_dataset_action_resolver.py
tests/test_etf_mins_dataset.py
tests/test_etf_sh_cons_model.py
tests/test_dataset_writer_fund_daily_master_gate.py
tests/test_ingestion_executor_fund_daily_two_phase.py
tests/test_etf_minute_history_alignment_plan_service.py
tests/test_cli_ops_preview_etf_minute_alignment.py
tests/test_etf_series_active_retirement.py
tests/test_dataset_unit_planner.py
tests/web/test_ops_task_run_api.py
tests/web/test_realtime_api.py
tests/web/test_ops_etf_realtime_monitor_api.py
tests/web/test_ops_review_center_api.py（含旧 ETF review 404 断言）
```

旧 active pool model/DAO/seed/CLI/固定 1,395 报告测试删除，不改写成新名字继续维护旧语义。

### 14.2 前端目标测试

至少覆盖：

```text
ops-realtime-monitor-page.test.tsx
ops-etf-realtime-monitor-config-page.test.tsx
router/navigation 相关测试
```

验证新 eligible 字段和 endpoint；旧 review 页面测试删除。

### 14.3 建议验证命令

代码变更按受影响范围选择下列验证，先确认现有环境和真实路径；不自动安装/同步依赖。纯文档只跑文档/引用/diff 检查，生产 Alembic current、真实数据库和源请求不混入默认命令：

```text
.venv/bin/python -m pytest -q <上述后端目标测试>
.venv/bin/python -m ruff check <本次修改的 Python 文件>
python3 scripts/check_docs_integrity.py
git diff --check

cd frontend
npm run typecheck
npm run check:rules
npm run test
npm run build
```

还必须运行仓库现有的架构/依赖边界测试；实施时先用文件搜索确认当前真实测试入口，不在 LLD 中猜一个可能过期的文件名。

---


## 15. 验收判据（实际历史结果见 §13）

### 15.1 Basic

```text
源端完整行数 = raw 行数
源端 ts_code 集合 = raw ts_code 集合
serving ts_code 集合 = raw 中 .SH/.SZ 集合
raw/serving 重复主键 = 0
serving .OF/未知后缀 = 0
TaskRun snapshot hash = 只读复算 hash
```

### 15.2 激活池退场

```text
src/frontend/current config 旧引用 = 0
tests 旧能力 import/fixture/call = 0（允许 retirement/migration 负向字符串断言）
旧 review routes = 404
旧 CLI = 不存在
ops.etf_series_active = 不存在
index_series_active 规划与测试 = 正常
```

### 15.3 下游只读复核

```text
NON_EXCHANGE_ETF_SUFFIX = 0
CODE_NOT_IN_ETF_MASTER = 只报告，不删除
BEFORE_CURRENT_LIST_DATE = 只报告，不删除
下游事实 DELETE 执行次数 = 0
保护表没有因本次改造发生历史删除
历史 alert/stat = 保留
```

### 15.4 分钟补拉

```text
每个实际请求 start_date >= 对应 list_date
计划 TaskRun/unit/request 上下界与实际可对账
已有 raw 观察区间不重复生成 prefix/suffix
成功的显式空结果 TaskRun 区间不重复请求
内部逐日/逐 bar 空洞明确标记为未审计
失败与源端空结果有代码和样本
重复执行不增加重复主键
```

V1 验收只能声明“当前可请求 ETF 与频率的区间请求前缀/尾部已按本次计划覆盖”，不能声明每个交易日或每个分钟 bar 均完整。

---

## 16. 维护与剩余边界

目标依赖保持 Foundation <- Ops/Biz <- App。Basic planner/writer 通过 Foundation DAO 取身份；不恢复 Foundation 对旧 Ops ETF store 的 contract，也不更改 QTF。文档合并不表示全仓依赖目标已全部落实。

今后改此链需同步：主方案 D1–D20、本 LLD 的当前实现及证据、受影响数据集文档和测试；分钟操作只维护 §10 链接的单一文档。Tushare 源资料仅在完成真实参数/字段核验后更新，不因内部文档整理重抓或改写源资料。

P12 已由普通多代码 TaskRun 10117 完成剩余 1,336 units，包括当时明确接受的 159539.SZ 三个 1min 幂等重请求 unit；不扩展成任意历史范围补拉授权。此前失败、取消、重试和共享生命周期仍沿现行 TaskRun，不建设 alignment 专用状态机或全局互斥。

截至 2026-08-29 的整体结案仍缺 SZ 自然调度与 ETF 实时开市批次证据；本轮保留该边界，不自动运行或据旧状态猜测今天生产。文档治理本身已按 [合并账本](/Users/congming/github/goldenshare/docs/governance/docs-information-architecture-v1.md#architecture-three-batches-20260910)校准，未删业务数据。
