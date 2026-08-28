# ETF 基础信息重建与下游数据审计清理 LLD v1

状态：P0 已完成 / P1 因当前数据库迁移落后于代码 head 暂未开始 / 尚未编码与生产执行
创建日期：2026-08-28
依据方案：[ETF 基础信息重建与下游数据审计清理技术方案 v1](/Users/congming/github/goldenshare/docs/architecture/etf-basic-rebuild-and-downstream-data-audit-cleanup-plan-v1.md)
适用代码：`src/foundation/**`、`src/ops/**`、`src/app/**`、`frontend/**`、`alembic/**`
不适用范围：公募基金 `.OF` 主数据域、`fund_adj` 现有全市场事实链、`etf_share_size` raw 直出链、`etf_rt_daily` provider 请求段

---

## 1. 设计结果

本 LLD 已把上层方案 D1-D20 落成可编码的实现方案，核心结果如下：

1. `etf_basic` 改为无业务过滤的完整快照请求，新增专用快照替换 write path；raw 保存全部源端行，serving 只保存 `.SH/.SZ`。
2. `EtfBasicDAO` 成为 ETF 身份与可请求资格的唯一查询入口，统一返回代码与 `list_date`；下游不得自行拼 `list_status`、后缀和上市日条件。
3. `etf_mins/etf_sh_cons/etf_sz_cons` 改由 Basic serving 展开代码，并在切窗前按 `list_date` 裁剪。
4. `fund_daily` 保持按交易日拉源端全集，但写入改为“raw 先提交、serving 后发布”两阶段事务，Basic 选择器失败不能回滚已成功写入的 raw，也不能让 serving 假成功。
5. `etf_rt_daily` 的源请求不变；health、实时监控候选和监控运行时在各自一次查询/运行开始时读取当前可请求 ETF，旧 `active_*` 契约彻底改名为 `eligible_*`。
6. 删除 `ops.etf_series_active` 的全部运行时、运维和前端能力；`ops.index_series_active` 明确保留，禁止按同名 `list_active_codes` 误删。
7. Prod 只读审计已确认下游已批准删除候选为 0；不实现通用清理 CLI、service、manifest 或 apply，只在 Basic 重建后复跑同口径只读核验。
8. ETF 历史分钟全量对齐先计算“当前可请求 ETF × 上市日 × 已有覆盖”的差集和额度预览，再复用正式 `etf_mins` TaskRun 补拉，不新增旁路抓取器。
9. `fund_adj`、`etf_share_size` 的数据链不改；尤其不新建 `etf_share_size` 物理 core/serving，不迁移直出 view，不接入 Basic 过滤。

本 LLD 没有新增业务口径待拍板。编码期间如果实测与本设计的当前代码事实不一致，必须停在对应开发阶段重新审计，不能自行引入兼容读取或临时旁路。

---

## 2. 本轮代码审计结论

### 2.1 审计方法与边界

本轮先在仓库根使用 CodeGraph 检查索引状态、探索入口和调用链，并对 `EtfSeriesActive`、`EtfSeriesActiveDAO`、`EtfSeriesActiveStore`、`EtfFundDailyServingCleanupService` 执行 impact 分析；随后使用精确字符串搜索补足动态注册、write path、CLI 名、HTTP 路由、前端请求和 Alembic 迁移。

CodeGraph 审计时索引包含 2,787 个文件、49,059 个节点和 124,757 条边。审计范围覆盖：

1. DatasetDefinition -> validator -> resolver -> unit planner -> request builder -> source client -> normalizer -> writer -> executor。
2. `EtfBasic` raw/serving model、DAO、DAOFactory 与写入链。
3. `EtfSeriesActive` model、DAO、Foundation contract、Ops adapter、seed、CLI、review API/UI、实时健康和实时监控。
4. 相关 Web API、前端类型、路由、导航和测试。
5. Alembic 当前 head 与旧激活池建表迁移。

CodeGraph 的宽泛 `list_active_codes` 影响结果同时命中 ETF 池和指数池，因此本次删除必须按 ETF 的具体类型、表名和 resource 精确执行，不能按方法名批量替换。

### 2.2 当前主数据链

| 环节 | 当前实现 | 已确认问题 | 目标实现 |
|---|---|---|---|
| 定义 | `reference_master.py` 中 `etf_basic` 允许 6 个业务过滤字段 | 带过滤请求也可能走正式发布 | 正式 maintain 无业务过滤，只发布完整快照 |
| 分页 | `offset_limit`，`page_limit=5000`，短页终止 | 实现可复用 | 保留并将短页完整性纳入发布门禁 |
| 归一化 | 只要求 `ts_code`，reject 记录后可继续 | 快照允许部分行被丢弃 | 改为任何 reject 阻断整个 unit |
| 写入 | `raw_core_upsert` 同时 upsert raw/serving | 源端消失的旧主键不会删除 | 专用 raw/serving 同事务完整替换 |
| serving | 当前写入与 raw 同一批全部行 | `.OF` 也可进入 serving | 只发布 `.SH/.SZ`，状态不在发布层过滤 |
| 历史 | 两张表均为当前态物理表 | 无 SCD 或版本表 | 保持当前态，不新增历史表 |

当前 14 个业务字段为：

```text
ts_code, csname, extname, cname, index_code, index_name,
setup_date, list_date, list_status, exchange,
mgr_name, custod_name, mgt_fee, etf_type
```

raw 另有 `api_name/fetched_at/raw_payload`，serving 另有 `created_at/updated_at`。这些元数据字段不进入主数据内容 hash。

### 2.3 当前请求驱动链

| 数据集/能力 | 当前代码事实 | 目标替代 |
|---|---|---|
| `etf_mins` | unit planner 从 `resource='etf_mins'` 激活池读代码；未使用 `list_date` | 当前可请求 ETF + 上市日裁剪 |
| `etf_sh_cons` | 从 `.SH` resource 激活池读代码 | 当前可请求 ETF 中 `.SH` |
| `etf_sz_cons` | 从 `.SZ` resource 激活池读代码 | 当前可请求 ETF 中 `.SZ` |
| `fund_daily` | 源请求按日期全市场；writer 用 `resource='fund_daily'` 旧池过滤 serving | 源请求不变；serving 用当前可请求 ETF + 上市日 |
| `fund_adj` | 按日期全市场；不使用 ETF 激活池 | 完全不改 |
| `etf_share_size` | 按日期全市场；raw 单份存储、serving view 直出 | 完全不改 |
| `etf_rt_daily` | provider 固定请求 `5*.SH`、`1*.SZ`；旧池只用于 health/候选 | provider 不改；health/候选换 Basic |

`EtfBasicDAO.get_active_etfs()` 当前把 `L/P/D` 都称为 active，`get_fund_daily_candidates()` 也接受 `L/P/D`，且 ingestion 主链没有调用这两个方法。这两个方法不能复用，目标版本直接删除并替换为语义准确的新契约，不留别名。

### 2.4 当前事务问题

`IngestionExecutor._process_fetched_unit()` 当前顺序是：归一化、调用 writer、统一 `session.commit()`。`fund_daily` writer 在同一事务中先 upsert raw，再查询旧激活池并写 serving。因此选择器异常会让 raw 一起回滚，与上层方案确认的 raw/serving 边界不符。

`WriteResult` 当前只有统一行数和 reject 诊断，没有表达“raw 已提交、serving 未提交”的字段。LLD 因此要求扩展现有诊断 JSON，不新增 TaskRun 列。

### 2.5 Tushare 契约复核

本轮复核的本地源文档为：

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

本轮还使用 Tushare MCP 对 `510300.SH` 显式请求 14 个 `etf_basic` 字段，返回当前 `L` 状态、`setup_date=20120504`、`list_date=20120528` 和 `exchange=SH`，验证了关键字段仍可由当前源端显式返回。行数快照不固化为永久代码门禁。

### 2.6 Alembic 基线事实

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

P0 没有修改或执行该迁移。代码端仍是唯一 head，但当前连接数据库落后一个版本；`heads != current` 已触发开发停止门禁。在数据库迁移基线重新对齐并再次确认唯一 head/current 前，不进入 P1，更不能创建本方案的 drop-table migration。新迁移的 `down_revision` 只能接实施时再次确认的真实唯一 head。

### 2.7 Prod 下游清理范围实测

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

---

## 3. 工程设计决策

| 编号 | 已落定设计 | 原因 |
|---|---|---|
| E1 | `EtfBasicDAO` 提供统一主数据/当前可请求查询；所有消费者调用它 | 消灭各下游自行拼状态、后缀和日期条件 |
| E2 | 正式 `etf_basic maintain` 删除所有业务过滤输入 | 防止部分源结果覆盖完整快照 |
| E3 | 新增 `raw_etf_basic_snapshot_replace` 专用 write path | 通用 upsert 不具备删除缺失主键的快照语义 |
| E4 | 快照先完整拉取和校验，再在一个事务中替换 raw/serving | 源失败不触碰旧数据；raw/serving 不出现跨版本 |
| E5 | `fund_daily` 使用 `raw_then_serving` 两阶段提交策略 | raw 是源端事实，不能因 ETF serving 选择器失败而丢失 |
| E6 | `fund_daily/fund_adj/etf_share_size` 现有显式 `ts_code` 入口保留，但只视为对应源接口的人工探测/修复；Basic 不用它们扇出请求 | 保持现有单代码运维能力，同时避免把它误当成 ETF 自动同步主链 |
| E7 | `etf_mins/sh_cons/sz_cons` 的 `universe_policy` 改为 `master_data` | 彻底删除“pool”语义，不把 Basic 冒充成新激活池 |
| E8 | `WINDOW_BEFORE_LIST_DATE` 在切窗前计数；显式请求越界直接报结构化错误 | 不向源端发无效请求，同时保留可审计原因 |
| E9 | health 改名为 `eligible_etf_count/eligible_snapshot_count`，候选接口改为 `/eligible-etfs` | 表退场后不再传播“激活池”概念；不留旧字段别名 |
| E10 | 不新增通用下游清理 CLI、service、manifest 或 apply；旧 `fund_daily` cleanup 与 CLI 直接删除 | 当前已批准删除候选为 0，避免为零规模问题建设长期删除系统 |
| E11 | 激活池 migration 的 downgrade 明确不可逆 | 不允许降级时重建一个无事实依据的空池或旧池 |
| E12 | 分钟全量对齐只生成正式 TaskRun，不直接调用 connector 或 writer | 保留正式分页、限流、归一化、幂等和观测链 |

### 3.1 没有新增配置项

本设计不新增 env、Settings、数据库配置或运营页面开关：

| 事项 | 来源 | 生效方式 | 消费者 |
|---|---|---|---|
| ETF 分钟频率窗口 | 现有 `ETF_MINS_RANGE_WINDOW_MONTHS` | 代码发布 | unit planner、对齐预览 |
| `page_limit=8000`、unit 上限 24,000 | 现有 DatasetDefinition | 代码发布 | source client、额度预览 |
| 当前可请求日期 | 调用方在一次查询、规划或发布开始时显式计算中国时区自然日 | 对应调用生命周期内固定 | Basic DAO selector |

如果实施阶段提出新的阈值、开关或持久化路径，必须另做配置项审计，不能把它偷偷写成页面常量或脚本常量。

---

## 4. ETF Basic 统一查询契约

### 4.1 值对象

在 `src/foundation/dao/etf_basic_dao.py` 定义不可变值对象：

```python
@dataclass(frozen=True, slots=True)
class EtfRequestTarget:
    ts_code: str
    list_date: date
    exchange: str | None
```

`list_status` 不放入值对象，是因为能返回该对象本身就表示已满足 `L`。`list_date` 不允许为 `None`，从类型层阻止 planner 忘记上市日。

### 4.2 DAO 公共方法

删除：

```python
get_active_etfs()
get_fund_daily_candidates()
```

新增：

```python
list_master_rows() -> list[EtfBasic]
list_requestable_targets(*, as_of_date: date, exchange: str | None = None) -> list[EtfRequestTarget]
get_requestable_target(*, ts_code: str, as_of_date: date) -> EtfRequestTarget | None
requestable_targets_subquery(*, as_of_date: date, exchange: str | None = None)
```

其中 `requestable_targets_subquery()` 供 Ops 的分页 join 使用，避免 Ops 为监控候选自行复制资格条件。四个方法必须共同复用一个私有 statement builder。

### 4.3 唯一资格条件

```text
list_status = 'L'
AND list_date IS NOT NULL
AND list_date <= :as_of_date
AND (ts_code LIKE '%.SH' OR ts_code LIKE '%.SZ')
```

注意 SQL 中后缀条件必须整体加括号。传 `exchange='SH'` 时同时要求 `.SH`，传 `exchange='SZ'` 时同时要求 `.SZ`；不接受任意字符串。结果按 `ts_code` 排序。

`list_master_rows()` 返回 serving 中全部状态的 `.SH/.SZ` 行，用于审计当前主数据，不等价于可请求集合。raw 中的 `.OF` 不会通过该 DAO 进入下游。

### 4.4 读取时点与调用日期

“动态读取当前可请求 ETF”不是每天生成一个新池，也不是每发一个 Tushare 请求都查询一次数据库。各消费者按自己的调用生命周期读取一次，并在该次调用内固定结果：

| 消费者 | 读取时点 | 本次结果使用范围 |
|---|---|---|
| `etf_mins/etf_sh_cons/etf_sz_cons` planner | 一次 `DatasetUnitPlanner.plan()` 开始时 | 同一次 plan 的所有日期锚点、代码、切窗和分页请求共用同一份目标快照 |
| `fund_daily` serving 发布 | 一次 serving phase 开始时 | 本次发布的全部归一化行共用同一份资格 map |
| `etf_rt_daily` Health | 每次 Health API 查询开始时 | 本次 Health 响应的 `eligible_*` 统计共用同一份代码集合 |
| 实时监控候选列表 | 每次 `/eligible-etfs` API 请求开始时 | 本次分页查询使用同一个 `as_of_date` 和同一条 requestable subquery |
| 实时监控运行时 | 每次 `run_after_etf_batch()` 开始时 | 本批次监控计算、规则匹配和告警共用同一份资格集合 |

每个调用者只计算一次 `as_of_date = datetime.now(ZoneInfo("Asia/Shanghai")).date()`，并把它显式传给 DAO。planner 取得的 `EtfRequestTarget` 已携带 `list_date`，后续切窗和每个 Tushare 请求不再次查询主数据。长任务跨过自然日零点也不在中途换集合；下一次任务重新读取，避免同一 TaskRun 前后口径漂移。

日期和 selector 统计写入现有诊断 JSON：

```json
{
  "etf_eligibility": {
    "as_of_date": "2026-08-28",
    "master_count": 0,
    "requestable_count": 0,
    "excluded_status_count": 0,
    "excluded_list_date_null_count": 0,
    "excluded_future_list_date_count": 0
  }
}
```

这里的 0 是结构示例，不是永久预期数量。

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
universe_policy = "master_data"
universe.sources = (
    DatasetUniverseSourceDefinition(
        type="core_serving_etf_basic",
        resource="requestable_etf",
    ),
)
```

`request_field='ts_code'` 和 `override_fields=('ts_code',)` 保持。旧 `ops_etf_series_active` resource 全部删除。

新增一个 planner 私有 helper，校验上述 Definition 形状并调用 `EtfBasicDAO.list_requestable_targets()`。三个 builder 共用它，不能分别实现三套 SQL。

### 6.2 显式代码

显式 `ts_code` 的规则：

1. 一次仍只允许一个代码。
2. 必须命中 `get_requestable_target(ts_code, as_of_date)`。
3. `etf_sh_cons` 额外要求 `.SH`；`etf_sz_cons` 额外要求 `.SZ`。
4. 不命中时抛 `etf_not_requestable`，错误详情记录代码和 `as_of_date`，不泄露内部 SQL。
5. 不允许回退到 seed CSV、旧表或“只要是 `.SH/.SZ` 就放行”。

新增错误码并登记 `src/foundation/ingestion/codebook.py`：

| 错误码 | 阶段 | 含义 |
|---|---|---|
| `etf_not_requestable` | planner | 代码不满足当前 Basic 可请求条件 |
| `window_before_list_date` | planner | 显式请求窗口整体早于上市日 |
| `etf_basic_snapshot_invalid` | validator/writer | Basic 完整快照校验或对账失败 |
| `fund_daily_serving_publish_failed` | writer/executor | raw 已提交但 ETF serving 发布失败 |

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

自动全量计划中，空窗口只计入 `WINDOW_BEFORE_LIST_DATE`，不生成 unit；显式单代码请求的整个窗口为空时抛 `window_before_list_date`。point 请求要求 `trade_date >= list_date`。

每个生成 unit 的 `progress_context` 增加：

```text
eligibility_as_of
master_list_date
requested_start_date
effective_start_date
```

源请求 builder 只接收已经裁剪后的日期，不能再次自行改日期。

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

`eligible_etf_count` 来自 `EtfBasicDAO.list_requestable_targets(as_of_date)`；`eligible_snapshot_count` 是当前 Redis batch 中命中这些代码的数量。`source_snapshot_count` 等源端字段不改。

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

读取时点是**每次候选分页 API 请求开始时一次**。它决定这次页面可选哪些 ETF，不创建持久化 eligible pool，也不把所有 eligible ETF 自动加入运营监控池。

### 8.4 监控配置与运行时

`ops.etf_realtime_monitor_pool` 保留，它表示运营重点关注对象，不是同步激活池。

目标行为：

1. 新增监控对象时用 `get_requestable_target()` 校验。
2. 新增或修改 ETF scope rule 时同时校验监控池成员和当前可请求资格。
3. `EtfRealtimeMonitorService.run_after_etf_batch()` 处理前将 enabled monitor pool 与当前可请求集合求交集。
4. 已失效配置即使仍保留在配置表中，也不得产生新统计或告警。
5. 历史 `etf_realtime_alert` 和分钟统计保留，不因主数据变化删除。

第 3 项的读取时点是**每次实时批次进入 `run_after_etf_batch()` 时一次**，本批监控计算期间固定；不是每条指标或每条规则重查 Basic。

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
manifest/候选 CSV
分批 DELETE、断点续跑或恢复逻辑
```

现有 `EtfFundDailyServingCleanupService` 和 `ops-cleanup-etf-fund-daily-serving` 随旧激活池直接删除，不改名、不复用，也不保留兼容入口。

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

## 10. ETF 历史分钟全量对齐

### 10.1 目标能力

新增只负责规划的 Ops service：

```text
src/ops/services/etf_minute_history_alignment_plan_service.py
```

它不调用 Tushare、不直接写 raw、不复制 unit planner。职责是生成当前生产缺口清单和正式 DatasetAction 请求草案。

### 10.2 差集算法

输入：

```text
current requestable targets from core_serving.etf_basic
requested frequencies
alignment end date
raw_tushare.etf_minute_bar existing coverage
trade calendar open dates
```

逐 ETF、逐频率：

```text
candidate_open_dates = open dates in [list_date, alignment_end_date]
covered_dates = distinct DATE(trade_time) already present for ts_code + freq
missing_dates = candidate_open_dates - covered_dates
missing_ranges = 将连续交易日压缩为区间
```

再把每个缺失区间交给现有 `etf_mins` range planner，按既有频率自然月窗口生成 unit。对齐服务不能自行重新实现 2/12/36/72/120 月切窗。

V1 以“某 ETF/频率/交易日至少存在一条分钟记录”视为该日已有覆盖。这能避免重复请求整日数据，但不证明分钟网格完整；停牌日、半日数据和盘中缺条的细粒度完整性审计不在本 LLD 中，不得把 V1 报告宣称为分钟级逐 bar 完整。

### 10.3 额度预览

执行前 manifest 必须包含：

```text
requestable_etf_count
excluded status/null/future-list counts
frequency_count and per-frequency unit_count
candidate open-date count
covered date count
missing date/range count
planned TaskRun count
planned unit count
page request upper bound
```

当前 `page_limit=8000`、`max_source_rows_per_unit=24000`。因为分页必须看到短页才结束，一个正好返回 24,000 行的 unit 最多会发生 4 次调用：3 个满页加 1 个终止短页/空页。因此额度上界按每 unit 4 次计算，不能写成 3 次。

### 10.4 执行方式

1. 默认只生成 preview manifest，不创建 TaskRun。
2. 用户确认额度后，以 manifest 中的精确 `ts_code/freq/start_date/end_date` 创建正式 `etf_mins` range TaskRun。
3. 创建 TaskRun 前再次校验 Basic snapshot hash；变化则重新预览。
4. 已有日期不进入请求区间；不得统一从 2020 年或任意固定日期开始。
5. 源端空窗口记为 `SOURCE_NOT_READY`，不从 `.OF` 复制数据。
6. 重跑时重新读取 raw coverage，已成功日期自然退出差集。
7. 全量执行必须分批，并沿用现有限流、重试、分页和 TaskRun 观测。

该 service 可以有独立的只读 preview CLI，但不能附带任何下游事实删除能力，也不能增加新的抓取通道。

### 10.5 日常主数据变化

Basic snapshot writer 已经在替换前后计算新增、删除、状态变化和 `list_date` 变化。日常处理复用这份 TaskRun 诊断，不新增 Basic 历史表：

| 变化 | 日常动作 |
|---|---|
| 新增 `.SH/.SZ` 且已可请求 | 把该代码交给 minute alignment service 生成从 `list_date` 到当前日的缺口 preview |
| `P -> L` 或空 `list_date -> 有效日期` | 同上，只生成该代码的定向 preview |
| `L -> D` | 下次 selector 自动停止新请求；不删除历史 |
| 代码从当前 Basic 消失 | 下次 selector 自动停止新请求并报告；不删除历史 |
| `list_date` 变晚 | 后续新计划采用新下界；不追溯删除已验收事实 |

诊断中的代码样本必须有 `sample_truncated` 标识。只有变更代码列表完整时，才允许生成定向 preview；如果变更数超过诊断样本上限，自动定向处理停止，改为运行第 10.2 节的全量只读差集预览。无论哪种情况，都只生成 preview，不因 Basic 发布成功自动消耗 Tushare 额度。

---

## 11. 激活池退场全量清单

### 11.1 直接删除

| 层 | 当前文件/对象 | 动作 |
|---|---|---|
| Migration | `20260618_000117_add_etf_series_active.py` | 保留历史迁移文件；新增新迁移 drop 当前表 |
| ORM | `src/ops/models/ops/etf_series_active.py` | 删除 |
| 注册 | `src/ops/models/ops/__init__.py`、`src/app/model_registry.py` | 删除 ETF model 注册 |
| DAO | `src/foundation/dao/etf_series_active_dao.py`、`src/foundation/dao/factory.py` 中的 ETF 属性 | 删除 |
| Contract | `src/foundation/kernel/contracts/etf_series_active_store.py` | 删除 |
| Adapter | `src/ops/etf_series_active_store_adapter.py` | 删除 |
| Seed | `src/ops/services/etf_series_active_seed_service.py` | 删除 |
| CLI | `src/cli.py`、`src/cli_parts/ops_handlers.py` 中 `ops-seed-etf-series-active` 及 handler/import | 删除 |
| Cleanup | `src/ops/services/etf_fund_daily_serving_cleanup_service.py` 与 `ops-cleanup-etf-fund-daily-serving` | 直接删除，不提供替代清理入口 |
| Review | `review_center_query_service.py`、`review_center.py`、`schemas/review_center.py`、`schemas/__init__.py` 中 ETF active 类型/方法/路由 | 只删除 ETF active 部分，保留 review center 其他能力 |
| Frontend | `ops-v21-review-etf-page*`、`app/router.tsx`、`app/shell.tsx`、`shared/api/types.ts` 中旧页面/路由/导航/类型 | 删除 ETF active 部分 |
| Tests | model/DAO/seed/CLI/旧报告固定数量测试，以及 resolver/writer/Web/frontend 中的旧池断言 | 独立旧能力测试删除；消费者测试按新 selector 重写 |

历史 Alembic 文件保留是数据库迁移链要求，不算运行时兼容路径。历史设计文档保留作证据，但必须标注已被本方案和本 LLD 取代。

当前测试引用的 `reports/etf_series_active_seed_1395_20260617.csv` 和 `reports/etf_series_active_fund_daily_accepted_gaps_31_20260617.csv` 在本轮工作区中实际不存在；实施时只删除其测试和代码引用，不编造“已删除 seed 文件”的交付记录。

### 11.2 改写消费者

| 当前消费者 | 当前读法 | 目标读法 |
|---|---|---|
| `_resolve_etf_mins_targets` | `etf_mins` resource | Basic 当前可请求 + list_date |
| sh/sz cons target resolver | 各自 resource | Basic 当前可请求 + 交易所 |
| fund daily writer | `fund_daily` resource | Basic 当前可请求 map |
| realtime feed health | `etf_rt_daily` resource | Basic 当前可请求 codes |
| realtime monitor candidate | `EtfSeriesActive` 起表 | Basic requestable subquery 起表 |
| realtime monitor runtime | enabled monitor pool，不做 Basic 交集 | monitor pool ∩ 当前可请求 |

### 11.3 明确保留

以下名字或机制与 ETF 激活池不同，禁止误删：

```text
ops.index_series_active
IndexSeriesActiveDAO
指数 planner 的 list_active_codes
ETF 实时业务监控池 ops.etf_realtime_monitor_pool
ETF 实时 provider 固定通配符请求
```

`etf_rt_min` 当前不在资源白名单和已落地运行时消费者中，本次不虚构该 resource 的删除或迁移代码。

### 11.4 静态清零命令范围

实现完成后对当前运行时代码、测试、前端和配置执行精确零引用检查：

```text
EtfSeriesActive
etf_series_active
ops_etf_series_active
ops-seed-etf-series-active
/ops/review/etf/active
active_pool_count
active_snapshot_count
/active-etfs
```

历史 migration 和明确标注为历史的文档允许保留旧名；`src/**`、`frontend/src/**`、`tests/**` 和当前配置中必须为 0。数据库验收要求 `to_regclass('ops.etf_series_active') IS NULL`。

---

## 12. Alembic 与无兼容发布

### 12.1 迁移内容

实现时新建唯一迁移：

```text
upgrade:
  DROP TABLE ops.etf_series_active

downgrade:
  raise RuntimeError("ops.etf_series_active retirement is irreversible")
```

由 drop table 自动删除其索引。迁移不删除任何 ETF 下游事实，本方案也没有下游事实删除 CLI。迁移前重新确认真实 head，禁止把本 LLD 记录的 `20260828_000155` 直接复制为未来 `down_revision`。

### 12.2 发布顺序

本次不支持旧进程与新 schema 混跑，不做双读：

1. 完成新 selector、planner、writer、实时消费者、前端和测试。
2. 在候选环境完成静态清零与 migration upgrade 验证。
3. 生产维护窗口暂停相关 schedule、worker、ETF realtime collector 和 Web 进程。
4. 确认 `etf_basic/etf_mins/etf_sh_cons/etf_sz_cons/fund_daily` 没有 `queued/running/canceling` TaskRun。
5. 部署完整新代码，但进程保持停止。
6. 用新代码对应的 Alembic 执行 drop-table migration。
7. 验证表不存在、旧引用静态为 0、旧 Basic serving 仍可读。
8. 只启动执行 Basic TaskRun 所需的 Web/worker，realtime collector 与所有相关 schedule 继续暂停。
9. 立即执行 `etf_basic` 完整快照重建并完成 raw/serving 验收。
10. 启动 realtime 和其余 Web 进程，冒烟验证 planner、fund daily 两阶段写入、health、eligible candidates 和 monitor runtime。
11. 恢复 schedule。

任何旧进程尚未停止、引用清零失败或 migration head 不唯一，都必须停止发布。

### 12.3 回滚边界

代码与 drop-table migration 是不可逆退场：

1. migration 前可以停止发布并继续运行旧版本。
2. migration 后不支持回滚到依赖激活池的旧版本。
3. 不重建空的 `ops.etf_series_active`，也不从 seed CSV 恢复。
4. 出现问题只能前向修复新 Basic selector/消费者。

这与“不保留兼容路径”的已确认口径一致。

---

## 13. 逐步开发流程

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

第 11.4 节八组旧引用在 `src/**`、`frontend/src/**`、`tests/**` 和当前配置中的实施前基线为：

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

当前配置文件的上述引用均为 0。该表是 P6 静态清零验收的对照基线，不代表 P0 已删除任何引用。

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

仅对 `510300.SH` 发起一次 `etf_basic` 请求，并显式指定本 LLD 的 14 个字段。源端完整返回 14 个字段，其中 `list_status=L`、`setup_date=20120504`、`list_date=20120528`、`exchange=SH`，与第 2.5 节字段契约一致；没有重复发起源端全量请求。

P0 五项动作均已完成。代码链、源字段和 Prod 物理对象没有发现与 LLD 冲突；唯一停止项是第 2.6 节所述当前连接数据库仍落后于代码 head。P1 保持未开始，待迁移 head/current 重新对齐并复核后再推进。

### P1：ETF Basic 快照发布

编码：

1. 收口 DatasetDefinition 和 request builder。
2. 新增 snapshot 校验/hash/diff 纯函数。
3. 新增专用 writer dispatch 和事务内对账。
4. 扩展 `WriteResult` 与 ingestion diagnostics。
5. 在 Ops TaskRun 创建侧增加同数据集 open-run 冲突检查。

测试：完整 `.SH/.SZ/.OF` 批次、旧代码消失、未知状态、未知后缀、交易所不一致、重复主键、reject、空结果、事务中途失败、并发锁、幂等重跑。

完成门禁：任何失败都不能改变旧 raw/serving；成功后集合和 hash 不变量成立。

### P2：统一 Basic selector

编码：

1. 新增 `EtfRequestTarget` 和四个 DAO 方法。
2. 删除两个语义错误的旧 DAO 方法。
3. 更新 DAOFactory 暴露新 DAO；不再暴露 ETF series active DAO。
4. 增加状态、空日期、未来上市日、后缀和 exchange 过滤测试。
5. 增加调用生命周期测试：同一次 planner/发布/Health/候选请求/实时批次只读取一次资格结果，并在本次调用内复用。

完成门禁：所有资格条件只存在于 DAO 私有 statement builder；消费者测试不能自己 mock 一组 `active_codes` 绕过 `list_date`，也不能在同一次任务的逐代码或逐分页请求中重复查询 Basic。

### P3：三个代码驱动 planner

编码：

1. Definition universe 改为 `master_data`。
2. 三个 target resolver 改用 `EtfRequestTarget`。
3. 上市日裁剪移到切窗前。
4. 新增错误码、进度上下文和计划统计。
5. 保护所有指数池 planner 不变。

测试：自动全集、显式单代码、SH/SZ 限制、P/D/L-null/未来上市、point 越界、range 部分重叠、range 全部早于上市日、每个频率的切窗边界。

完成门禁：生成的每个源请求起点都不早于 `list_date`；旧 ETF resource 引用从 Foundation planner 清零。

### P4：`fund_daily` 两阶段发布

编码：

1. 新增 `raw_then_serving` commit policy 的 linter 白名单。
2. 拆 raw/serving writer phase。
3. executor 增加两提交点和 partial-business-commit 诊断。
4. serving 接统一 selector 与 `trade_date >= list_date`。
5. 删除旧 active-pool writer helper 和旧 cleanup service。

测试：全市场 raw、ETF serving、LOF/REIT 只进 raw、上市日前只进 raw、selector 空、selector 异常、serving upsert 异常、raw upsert 异常、重试幂等、显式 ts_code 不扇出。

完成门禁：selector/serving 失败时 raw 已提交且 TaskRun 失败；不得出现 raw 被回滚或 serving 假成功。

### P5：实时与前端切换

编码：

1. health 改 DAO 与字段名。
2. candidate query 改 Basic subquery 起表并改 endpoint/DTO。
3. monitor pool/rule 写入与 runtime 增加资格校验。
4. 删除旧 review API/UI。
5. 同步前端 types、页面、路由、导航和测试。

完成门禁：provider 请求参数快照测试保持固定通配符；前后端不再出现 `active_pool_count/active_snapshot_count/active-etfs`。

### P6：下游只读复核与分钟对齐预览

动作：

1. 不编写下游 cleanup service、CLI、manifest、CSV 或 apply 代码。
2. 把第 2.7/9 节的 Prod 只读统计作为发布 runbook 门禁，Basic 重建后复跑。
3. 实现分钟 alignment plan service、额度 preview 和 Basic 变更代码的定向 preview；诊断截断时回退为全量只读差集预览，不直接发源请求。

测试：删除旧 cleanup service/CLI 的零引用测试；代码消失和 `list_date` 变晚不触发事实 DELETE 的负向测试；分钟缺口压缩和 4-call 上界。

完成门禁：仓库没有通用下游事实清理入口；复核结果为 0 时不产生任何业务写入。

### P7：激活池代码与 schema 退场

编码：

1. 删除 model/DAO/contract/adapter/seed/CLI/review 页面和旧测试。
2. 清理 model registry、schema export、router 和 frontend import。
3. 重新跑 CodeGraph impact 与字符串清零。
4. 确认真实 head 后新增不可逆 drop-table migration。
5. 给历史激活池文档补充“已被取代”链接。

完成门禁：运行时/测试/前端/config 零引用；指数池测试全部通过；migration 能从真实 head 升级。

### P8：候选环境总回归

1. 执行全部后端目标测试、架构边界测试、前端 typecheck/rules/test/build。
2. 在临时 PostgreSQL 从旧 schema 升级并验证新进程启动。
3. 跑一次 Basic 小型完整快照 fixture。
4. 跑一次 fund daily raw 成功/serving 故障注入。
5. 按发布 runbook 复核下游统计，并运行分钟 preview；禁止事实删除和真实补拉。

完成门禁：D1-D20 测试矩阵全部有证据，不能只以“测试总数通过”代替口径对账。

### P9：生产执行

顺序固定：

```text
维护窗口与零运行任务
-> 无兼容版本发布和 drop 激活池表
-> etf_basic 完整快照重建
-> raw/serving 验收
-> 下游只读复核
-> 确认已批准删除候选为 0
-> 分钟 alignment preview
-> 用户确认额度
-> 分批正式 TaskRun 补拉
-> 最终对账与日常 schedule 恢复
```

生产删除旧激活池表和分钟全量补拉是两个不同授权动作。下游事实删除不在本 LLD 的生产步骤中；若复核意外非零，必须停止并另行评审。

---

## 14. 测试与硬口径对账

| 方案决策 | 必须落到的代码/测试 |
|---|---|
| D1-D3 | Basic Definition、snapshot validator/writer；完整 raw、单事务替换、失败回滚 |
| D4 | 禁止 OF rename/merge；当前无旧 OF 下游候选；未来非零时停止并另立精确方案 |
| D5-D9 | Basic DAO + 三个 planner；状态、日期、后缀、切窗和无退市日上界测试 |
| D10-D11 | serving 后缀测试；公募基金保护表 checksum；3 条 OF 仅 raw fixture |
| D12 | 全量引用清零、drop-table migration、无 fallback 负向测试 |
| D13 | 不新增通用 cleanup service/CLI/manifest/apply；旧 cleanup 直接退场 |
| D14 | 无新历史表/字段；现有 TaskRun diagnostics 承载 hash/摘要 |
| D15 | 日常 Basic 变化测试只影响新计划，不调用事实 DELETE |
| D16 | CodeGraph + 字符串 + DB 六层清零、维护窗口发布顺序 |
| D17 | fund daily/fund adj/share size 默认全市场请求不扇出；显式入口定位测试 |
| D18 | raw/core/直出 view 零删除保护测试 |
| D19 | fund daily 两阶段 serving gate；fund_adj/share size 零改动回归 |
| D20 | realtime provider 固定通配符请求快照测试；只替换 health/候选 |

### 14.1 后端目标测试

实现时至少覆盖：

```text
tests/test_etf_basic_dao.py
tests/test_etf_basic_dataset.py
tests/test_etf_basic_snapshot_writer.py
tests/test_dataset_definition_registry.py
tests/test_dataset_action_resolver.py
tests/test_etf_mins_dataset.py
tests/test_etf_sh_cons_model.py
tests/test_dataset_writer_fund_daily_master_gate.py
tests/test_ingestion_executor_fund_daily_two_phase.py
tests/test_etf_minute_history_alignment_plan_service.py
tests/web/test_realtime_api.py
tests/web/test_ops_etf_realtime_monitor_api.py
tests/web/test_ops_review_center_api.py 中删除旧 ETF review 用例
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

编码阶段按受影响范围逐步运行，最终至少包括：

```text
uv run pytest -q <上述后端目标测试>
uv run ruff check <本次修改的 Python 文件>
uv run alembic heads
uv run alembic current
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

## 15. 生产验收证据

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
src/frontend/tests/current config 旧引用 = 0
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
计划 TaskRun/unit/request 上界与实际可对账
已覆盖日期未重复进入初始差集计划
失败与 SOURCE_NOT_READY 有代码和样本
重复执行不增加重复主键
```

V1 验收只能声明“当前可请求 ETF、频率和交易日覆盖已对齐到本次差集口径”，不能声明每个交易日所有分钟 bar 均完整。

---

## 16. 边界、文档与未决项

### 16.1 子系统边界

目标依赖保持：

```text
foundation <- ops <- app
foundation <- biz <- app
```

Foundation planner/writer 只访问 Foundation 的 `core_serving.etf_basic` DAO；删除 Foundation 为读取 Ops ETF 激活池而设置的 contract。不存在 `foundation -> ops` ORM 依赖。`qtf` 不受影响。

依赖矩阵的方向没有新增变化；实际实现完成后，如果关键调用链已实质变化，应同步 `codegraph-architecture-snapshot.md`，但不能在尚未编码时把目标态写成已实现事实。

### 16.2 必须同步的文档

实现阶段至少更新：

1. 本 LLD 状态和里程碑完成证据。
2. 上层技术方案的实现状态。
3. 旧 ETF active pool 方案/LLD 的 superseded 状态。
4. `etf_mins` 数据集方案/LLD 中对象来源与上市日规则。
5. Tushare 本地源文档仅在真实参数/字段行为变化时更新。
6. 数据集目录/运营说明中删除旧 seed、review 页面和激活池初始化步骤。

### 16.3 未决项

没有业务口径待拍板。以下是实施期停止门禁，不是可由开发者自行选择的方案分支：

1. Alembic head 在编码时若已变化，必须接新的真实 head。
2. 生产复核对象或统计结果若与本 LLD 不一致，必须重新审计并修订 LLD。
3. Tushare 关键字段、分页或返回范围若与本轮实测不一致，必须先修本地源文档和设计。
4. `NON_EXCHANGE_ETF_SUFFIX` 若实际非零，必须停止并另立精确一次性方案；`PENDING_ETF_HAS_FACT` 只报告，不自动删除。
5. 分钟额度预览达到不可接受量级时，停止创建 TaskRun；只能调整执行批次，不能取消上市日和已有覆盖门禁。

---

## 17. LLD 完成定义

本 LLD 的“完成”表示：

1. 上层 D1-D20 均有明确代码点、事务语义、正反测试和生产证据。
2. 激活池所有已发现消费者都有删除或替代去向。
3. `etf_basic`、`fund_daily`、分钟补拉和下游只读复核的失败边界已落清。
4. 明确保护 `fund_adj`、`etf_share_size`、公募基金域、指数池和历史实时事实。
5. 开发顺序阻止了“先删表再找消费者”，并明确当前不建设下游事实清理系统。

它不代表代码已经开发，也不授权执行生产迁移、删除或全量补拉。下一步是在用户评审通过后，从 P0 开始按阶段编码。
