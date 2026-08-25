# ETF 历史分钟行情数据集接入方案 v1

状态：M1-M8 已完成；生产部署、HDD 迁移、1,395 只 ETF 活跃池、最小同步、全池区间同步和自动任务均已验收通过。

创建日期：2026-08-24
最近更新：2026-08-25

关联文档：

- [新增数据集开发模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)
- [Tushare 0387 ETF 历史分钟行情](/Users/congming/github/goldenshare/docs/sources/tushare/ETF专题/0387_ETF历史分钟行情.md)
- [ETF 历史分钟行情 LLD](/Users/congming/github/goldenshare/docs/datasets/etf-mins-dataset-low-level-design-v1.md)
- [ETF 活跃池设计方案](/Users/congming/github/goldenshare/docs/architecture/etf-active-pool-design-plan-v1.md)

---

## 1. 最终目标

`etf_mins` 是生产环境中的标准 ETF 历史分钟行情数据集。所有分钟行情均直接调用 Tushare `etf_mins` 获取并写入唯一物理表：

```text
raw_tushare.etf_minute_bar
```

数据集支持 Tushare 原生的五种频率：

```text
1min / 5min / 15min / 30min / 60min
```

一次手动任务或一次自动任务都走标准数据集维护链路：

```text
运营提交手动任务 / 自动任务触发
  -> DatasetActionResolver
  -> DatasetExecutionPlan
  -> point 按 ETF 代码 × 已选源端频率生成当日 unit
  -> range 按 ETF 代码 × 已选源端频率 × 受控时间窗口生成 unit
  -> Tushare etf_mins 分页拉取
  -> normalize
  -> raw_tushare.etf_minute_bar 幂等写入
  -> 提交本 unit 事务
  -> 继续下一个 unit
```

交付范围固定为：一个 Tushare API、五种源端频率、一个 raw 物理表、手动维护和独立自动任务。频率交互复用股票历史分钟行情现有的通用多选控件，本数据集不加入 workflow。

---

## 2. 源接口事实

### 2.1 输入、输出和分页

| 维度 | 已确认事实 | 实现约束 |
| --- | --- | --- |
| API | `etf_mins` | 禁止误用 `stk_mins`。 |
| 必填参数 | `ts_code`、`freq` | planner 必须先确定 ETF 和频率。 |
| 可选时间参数 | `start_date`、`end_date` | 只能由 request builder 从计划 unit 映射。 |
| 支持频率 | `1min/5min/15min/30min/60min` | 页面、校验、planner 和请求参数必须一致。 |
| 单次返回上限 | 8,000 行 | 使用 `offset_limit` 分页，`page_limit=8000`。 |
| 历史范围 | 超过 10 年 | range 必须先按频率切成受控时间窗口，再在窗口内分页；禁止对完整历史区间做深 offset 分页。 |
| 返回顺序 | 实测为 `trade_time` 倒序 | 写入与幂等不能依赖源端顺序。 |
| 限速 | 500 次/分钟 | 建立 `etf_mins` 独立 endpoint 限速事实。 |

生产请求显式指定字段：

```text
ts_code,freq,trade_time,open,close,high,low,vol,amount,vwap,exchange
```

本地接口文档默认输出表只列出 `ts_code/trade_time/OHLC/vol/amount`；真实请求已确认显式请求时可返回身份字段 `freq` 以及 `vwap/exchange`。实现必须区分“文档默认字段”和“显式请求字段”，不能因为默认列表未展示就丢字段。

### 2.2 真实请求验证矩阵

| 请求形态 | 实测结果 | 结论 |
| --- | --- | --- |
| 不传 `ts_code/freq` | 接口拒绝；两者均为必填 | planner 必须先确定 ETF 和频率。 |
| 只传 `ts_code/freq`，不传时间 | `510300.SH + 1min` 返回 1,446 行，仅覆盖最近约 6 个交易日 | 不能把无时间请求当作全历史维护。 |
| 单日窗口 | `510300.SH + 1min + 2026-08-21 09:30:00~09:35:00` 返回 6 行 | point 可映射为同一天的起止时间。 |
| 两日区间 | 实测返回 482 行 | 日期范围过滤有效；长 range 仍必须由 planner 切窗，不能据此推断深分页稳定。 |
| 默认字段 | 返回文档列出的 8 个默认字段 | 默认结果缺少频率身份和扩展字段。 |
| 显式字段 | 显式请求 11 个字段时返回 `freq/vwap/exchange` | `source_fields` 固定为 11 个字段。 |
| 分页 | 同一 6 行窗口使用 `limit=3`，`offset=0/3/6` 返回 `3/3/0` | `limit/offset` 生效，短页或空页结束。 |
| 分页集合对账 | 分页合并后的唯一键集合与不分页结果完全一致 | 可使用主链 `offset_limit`。 |
| 早期历史 | `510050.SH` 在 2009-01-05、2009-12-31 和 2010-01-04 均返回 241 行 | 初始分区范围至少要覆盖 2009 年。 |

验证样本只证明当前接口行为。编码完成后仍须通过项目 connector 执行最小真实同步，不能用本次接口探测替代发布验收。

`limit=3` 的分页探测只用于证明源接口支持 `limit/offset` 和短页结束，不是生产分页策略。生产固定使用 `limit=8000`；固定切窗按一到两页测算，`max_source_rows_per_unit=24000` 额外允许第三个数据页作为安全余量。

### 2.3 源字段端到端对账

| 源字段 | 默认返回 | 显式返回 | `source_fields` | raw 列 | 必填 | 归一化 |
| --- | --- | --- | --- | --- | --- | --- |
| `ts_code` | 是 | 是 | 是 | `varchar(16)` | 是 | 去空格、转大写 |
| `freq` | 否 | 是 | 是 | `varchar(8)` | 是 | 保留源端字符串并核对请求频率 |
| `trade_time` | 是 | 是 | 是 | `timestamp` | 是 | 解析为无时区时间戳 |
| `open` | 是 | 是 | 是 | `double precision` | 否 | 转浮点，不裁剪小数位 |
| `close` | 是 | 是 | 是 | `double precision` | 否 | 转浮点，不裁剪小数位 |
| `high` | 是 | 是 | 是 | `double precision` | 否 | 转浮点，不裁剪小数位 |
| `low` | 是 | 是 | 是 | `double precision` | 否 | 转浮点，不裁剪小数位 |
| `vol` | 是 | 是 | 是 | `bigint` | 否 | 只接受可无损转换的整数值 |
| `amount` | 是 | 是 | 是 | `double precision` | 否 | 转浮点 |
| `vwap` | 否 | 是 | 是 | `double precision` | 否 | 转浮点 |
| `exchange` | 否 | 是 | 是 | `varchar(16)` | 否 | 去空格、转大写 |

本数据集没有 std/core/serving 物理列链路，字段对账终点就是 `raw_tushare.etf_minute_bar`。

### 2.4 配置项审计

| 配置事实 | 值 | 持久化位置 | 消费者 | 生效方式 | 运营可见性 | 测试门禁 |
| --- | --- | --- | --- | --- | --- | --- |
| 源站单页上限 | `8000` | `DatasetDefinition.planning.page_limit` | `DatasetSourceClient` | 代码部署 | 数据集详情 | offset/短页测试 |
| 单 unit 源端行数上限 | `24000` | `DatasetDefinition.planning.max_source_rows_per_unit` | `DatasetSourceClient` | 代码部署 | 数据集详情 | 最多接纳三个数据页；超过 24,000 行立即失败 |
| range 固定切窗 | `1min=2`、`5min=12`、`15min=36`、`30min=72`、`60min=120` 个自然月 | `unit_planner.py` 的 `ETF_MINS_RANGE_WINDOW_MONTHS` | ETF 分钟 unit builder | 代码部署 | 不开放运营编辑 | 五频率窗口边界与完整覆盖测试 |
| 源站 endpoint 限速 | `500/min` | `TushareClient._API_RATE_LIMITS` | Tushare limiter | 代码部署 | 暂无独立配置入口 | endpoint limiter 测试 |
| 拉取并发 | `2` | `DatasetDefinition.planning.fetch_concurrency` | ingestion executor | 代码部署 | 数据集详情 | plan/executor 测试 |
| 页面频率选项 | 五种源端频率 | `DatasetDefinition.input_model` | manual/auto API 与前端 | 代码部署 | 手动、自动任务页 | 契约与前端测试 |
| 对象池 resource | `etf_mins` | `DatasetDefinition.planning.universe` 与 `ops.etf_series_active` | unit planner | seed 后生效 | ETF 活跃池审查页 | resource 隔离测试 |
| HDD tablespace | `gs_raw_cold_hdd` | Alembic migration | PostgreSQL | 迁移执行 | 数据库元数据 | relation/index tablespace 检查 |

本轮不新增 env、Settings 或配置中心字段。上述事实不得再散落到前端常量或脚本参数中。

---

## 3. DatasetDefinition 设计

### 3.1 身份与领域

| 字段 | 值 |
| --- | --- |
| `dataset_key` | `etf_mins` |
| `display_name` | ETF 历史分钟行情 |
| `domain_key` | `index_fund` |
| `domain_display_name` | 指数 / ETF |
| `source.api_name` | `etf_mins` |
| `source.source_doc_id` | `tushare.etf_mins` |
| `source.request_builder_key` | `_etf_mins_params` |
| `action` | `maintain` |
| 数据源 | Tushare，单一来源 |
| 是否新增业务查询 API | 否；本轮只接入 Prod 数据维护能力 |
| 是否支持自动任务 | 是；独立 schedule，不进 workflow |
| 是否纳入日期完整性审计 | 否；分钟完整性需要交易时段网格，普通日期审计不适用 |
| Ops 展示分组 | `etf_fund / ETF基金`，顺序 `70` |
| Ops 展示目录 | `src/ops/catalog/dataset_catalog_views.py` |

Ops 展示目录归入现有 `etf_fund / ETF基金`，不改底层 domain，也不新增另一套分组事实。

### 3.2 三层时间语义

| 语义层 | 最终口径 |
| --- | --- |
| 时间输入 | 支持 `point` 和 `range`；不支持 `none`。 |
| 执行 unit | 一个 unit = 一个 ETF 代码 + 一个源端频率 + 一个受控时间窗口。point 是当日窗口；range 由 planner 按频率切成连续的多月窗口。 |
| freshness / audit | `audit_applicable=false`。数据仍支持日期输入，但分钟完整性不能套用普通“每日一行”连续性审计。 |

point 请求映射：

```text
trade_date=2026-08-21
  -> start_date=2026-08-21 09:00:00
  -> end_date=2026-08-21 19:00:00
```

range 请求映射：

```text
start_date=2026-08-01
end_date=2026-08-21
  -> planner 先按所选 freq 的窗口月数切割
  -> 每个窗口分别映射 09:00:00~19:00:00
```

range 仍然只提交一个 TaskRun，但 planner 必须把用户区间切成多个连续、不重叠、无遗漏的时间窗口。切窗不是让用户重复提交任务，也不是逐交易日展开；窗口容量按一到两页测算，第三页只作为小幅超量时的安全余量，避免超长 offset 链在末页失败后丢弃整个大 unit。

频率与窗口跨度固定为：

| 源端频率 | 每个 range unit 的最大自然月跨度 |
| --- | ---: |
| `1min` | 2 个月 |
| `5min` | 12 个月 |
| `15min` | 36 个月 |
| `30min` | 72 个月 |
| `60min` | 120 个月 |

窗口首尾按用户输入裁剪。例如 `1min + 2025-01-15~2025-05-10` 生成 `2025-01-15~2025-02-28`、`2025-03-01~2025-04-30`、`2025-05-01~2025-05-10`。跨年和闰年按自然月真实末日计算。

### 3.3 输入模型

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `trade_date` | date | point 模式必填 | 单个交易日。 |
| `start_date/end_date` | date | range 模式必填 | 整体历史区间。 |
| `ts_code` | string | 否 | 显式填写时只维护该 ETF；为空时使用 ETF 活跃池。 |
| `freq` | multi enum | 是 | 至少选择一个，允许 `1min/5min/15min/30min/60min`。 |

前端直接消费通用 input contract，不新增 ETF 专属控件或页面规则。

### 3.4 规划与能力

```text
universe_policy: pool
universe source: ops_etf_series_active / etf_mins
pagination_policy: offset_limit
page_limit: 8000
unit_builder_key: build_etf_mins_units
max_source_rows_per_unit: 24000
fetch_concurrency: 2
page_processing_mode: buffer_all
manual_enabled: true
schedule_enabled: true
supported_time_modes: point, range
workflow: none
```

---

## 4. ETF 活跃池

未显式传入 `ts_code` 时，planner 只读取：

```sql
ops.etf_series_active
WHERE resource = 'etf_mins'
```

规则保持已冻结的 ETF 活跃池策略：

- 初始代码池为 1,395 只 ETF。
- 只允许 `.SH/.SZ`，不含 `.OF`。
- `etf_mins` 是独立 resource，不借用 `fund_daily` 或 `etf_rt_daily`。
- 显式 `ts_code` 只影响本次任务，不修改活跃池，但该代码也必须属于 `resource='etf_mins'`；池外代码在 planner 阶段直接拒绝。
- seed 服务的 resource 白名单和 1,395 行期望映射必须同步增加 `etf_mins`。

---

## 5. 唯一物理表

### 5.1 表结构

唯一业务表：

```text
raw_tushare.etf_minute_bar
```

| 字段 | PostgreSQL 类型 | 可空 | 来源 / 说明 |
| --- | --- | --- | --- |
| `ts_code` | `varchar(16)` | 否 | Tushare ETF 代码。 |
| `freq` | `varchar(8)` | 否 | Tushare 原始频率字符串。 |
| `trade_time` | `timestamp without time zone` | 否 | 分钟时间。 |
| `open` | `double precision` | 是 | 开盘价。 |
| `close` | `double precision` | 是 | 收盘价。 |
| `high` | `double precision` | 是 | 最高价。 |
| `low` | `double precision` | 是 | 最低价。 |
| `vol` | `bigint` | 是 | 成交量。 |
| `amount` | `double precision` | 是 | 成交额。 |
| `vwap` | `double precision` | 是 | 源端显式返回的均价。 |
| `exchange` | `varchar(16)` | 是 | 源端显式返回的交易所。 |

主键固定为：

```text
(ts_code, freq, trade_time)
```

表内业务身份只由上述三个主键字段确定。

### 5.2 HDD 与分区硬约束

- 按 `trade_time` 做月分区。
- 首版迁移连续预建 `2009-01` 至 `2037-12` 的月分区，并建立同样位于 HDD 的默认分区。
- 父表、所有月分区、默认分区、主键索引和辅助索引必须全部位于 `gs_raw_cold_hdd`。
- 迁移执行时若 HDD tablespace 不存在，必须直接失败，不能静默落到 SSD。
- 不照搬现有 `stk_mins` 中“部分历史分区进 HDD、其余分区默认落盘”的旧迁移做法。
- PostgreSQL 并不要求同步前预建每个月份：默认分区可以接住超出预建范围的数据。但同步主链禁止运行时 DDL，而且默认分区已有目标月份数据后再拆出正式月分区，需要受控搬移数据并处理分区约束，风险和维护成本更高。因此首版迁移一次性预建已验证历史和可预见未来月份；默认分区只作为防止未覆盖月份写入失败的 HDD 安全网，不是 SSD 兜底。
- 超出 `2037-12` 前通过受控 Alembic 迁移继续创建 HDD 月分区，不允许同步任务边拉数据边建表。

### 5.3 Raw 直出

```text
delivery_mode: raw_collection
layer_plan: raw-only
raw_table: raw_tushare.etf_minute_bar
target_table: raw_tushare.etf_minute_bar
serving_table: null
write_path: raw_only_upsert
```

本数据集不建立物理 serving 副本。后续消费者如需读取 ETF 历史分钟行情，应直接通过该数据集的 raw DAO 读取唯一事实表，不得复制一份相同数据。

---

## 6. 执行、事务与质量

### 6.1 unit 与分页

planner 按稳定顺序生成：

```text
ETF 代码升序 × 频率固定顺序 × 时间窗口升序
```

频率固定顺序为：

```text
1min, 5min, 15min, 30min, 60min
```

point 只生成当日窗口。range 根据频率使用 `2/12/36/72/120` 个自然月切窗；首尾窗口按用户起止日期裁剪，窗口之间必须连续且不重叠。

每个 unit 内部使用 `limit=8000`。正常数据页 offset 为 `0`、必要时的 `8000`，以及作为安全余量的 `16000`。`max_source_rows_per_unit=24000` 的语义是：窗口仍按一到两页测算，但最多接纳三个数据页、24,000 行；任何第 24,001 行都会触发 `source_rows_exceeded`，不得写库。

当前通用分页器依靠短页判断结束，因此第三页恰好满 8,000 行时，会再请求一次 `offset=24000` 作为边界探测：返回空页表示该 unit 恰好 24,000 行，可以成功；返回任何数据表示源端总量超过 24,000 行，立即失败。该探测页不进入写入数据，不能被描述为第四个可接纳数据页。

分页不拆事务；该 unit 的一到三个数据页全部归一化完成后，统一幂等写入并提交一次。

执行器允许按 Definition 的 `fetch_concurrency` 并发拉取不同 unit，但数据库处理仍以完成拉取的单个 unit 为边界：全分页拉完、归一化、写入、提交，然后该 unit 才计为完成。任务不是全部 unit 拉完后一次性提交，也不允许逐页提交；当前 unit 失败只回滚当前 unit，之前已经提交的 unit 保留。

### 6.2 幂等与拒绝

- 冲突键为 `(ts_code, freq, trade_time)`。
- 同一批次中出现完全重复身份键或冲突内容时，本 unit 失败。
- 任意行因必填身份字段缺失、非法时间或其他 normalization 原因被拒绝时，本 unit 失败。
- 失败必须记录结构化 reason code 和样本；不得带着 reject 继续把 unit 标为成功。
- 已经成功提交的其他 unit 不因当前 unit 失败而回滚。

### 6.3 事务量评估

按 A 股常规交易日估算：

- `1min` 约 241 行 / ETF / 交易日。
- 5 个源端频率合计约 321 行 / ETF / 交易日。
- point 模式下默认全池 1,395 只 ETF、全选五种频率，共 6,975 个 unit。
- 在 500 次/分钟源站限速下，请求理论下限约 14 分钟，未计分页、网络和数据库写入。

range 模式不能继续把全历史压进一个 unit。以 2009 至 2026 年约 213 个自然月估算，单只 ETF、五种频率分别约生成 `107 + 18 + 6 + 3 + 2 = 136` 个时间窗口 unit。按正常每 unit 两页估算，全池约 37.9 万次基础分页请求，500 次/分钟下仅请求理论下限约 12.7 小时；按三个数据页的硬缓冲上限估算，约 56.9 万次基础分页请求、理论下限约 19.0 小时。两者均不包含同一页重试和第三个满页后的空边界探测；这里是容量规划估算，不是源站实测耗时，实际还受 ETF 上市日期、空窗口、网络和数据库写入影响。

切窗后单 unit 的源端行数不得超过 24,000，事务和内存不再随用户完整 range 无限增长。开发验收仍必须用真实样本核对五种频率各自的窗口行数、页数、内存和事务写入量；固定窗口应以一到两页为正常结果。第三页是允许的安全余量，但如果真实样本经常进入第三页，或触发超过 24,000 行的门禁，必须缩短对应频率的固定窗口并更新方案、测试和实现，不能继续放宽门禁。

当前通用手动任务和 ingestion validator 只校验起止日期完整且 `start_date <= end_date`，没有用户 range 最大跨度限制；本数据集也不设置 `max_units_per_execution`。用户可以提交长 range，但 planner 必须自动切成受控 unit，不能把完整 range 原样交给源接口。

---

## 7. 运营方式

### 7.1 手动任务

复用股票历史分钟行情的现有交互：

- 选择单日或区间。
- 可选填写单个 ETF 代码。
- 必须多选至少一个源端频率。
- 页面提交维护意图，不能直接拼 Tushare 参数。

### 7.2 自动任务

- 支持独立自动定时任务。
- 使用同一 `etf_mins.maintain` action 和同一输入契约。
- V1 不创建默认自动任务，由运营自行配置运行时间和频率。
- V1 不加入任何 workflow。

### 7.3 任务进度

任务详情复用标准 unit 进度：

```text
当前 ETF / 当前频率 / 当前时间范围 / 当前窗口序号 / 已完成 unit 数 / 总 unit 数 / 已提交行数 / 拒绝数
```

`总 unit 数` 必须是 planner 完成频率切窗后的真实 unit 总数。页面不得仍按“ETF × 频率”估算总数，否则长 range 会出现进度提前到 100% 或长时间不动。

---

## 8. 消费者影响面

| 消费方 | 当前代码位置 | 本轮设计影响 |
| --- | --- | --- |
| Definition registry | `src/foundation/datasets/registry.py`、`definitions/_builder.py` | `market_fund.py` 新增定义；runtime registry 自动收录。 |
| resolver / planner | `src/foundation/ingestion/resolver.py`、`unit_planner.py` | resolver 不改；新增 ETF 对象池 + 频率 unit builder。 |
| request builder / source | `request_builders.py`、`source_client.py` | 新增参数映射、分页和返回频率核对。 |
| Tushare limiter | `src/foundation/clients/tushare_client.py` | 新增 `etf_mins=500/min` endpoint 事实。 |
| normalizer / writer | `normalizer.py`、`row_transforms.py`、`writer.py` | 新增 transform；`raw_only_upsert` 执行 fail-any policy。 |
| manual actions | `src/ops/api/manual_actions.py`、`frontend/src/pages/ops-v21-task-manual-tab.tsx` | 自动获得 point/range、代码和频率字段。 |
| schedules | `schedule_automation_capability_resolver.py`、`task_run_dispatcher.py`、自动任务页 | 允许独立 schedule；未固定日期的 point 运行时解析最近开市日。 |
| source release / Probe | `dataset_release_target_service.py`、schedule runtime | V1 使用 `same_day` 发布口径，不新增 Probe；生产启用自动任务前必须在运营选定时点完成当日数据可用性验证。 |
| workflow | workflow registry | 不注册该数据集。 |
| freshness | `freshness_policies.py`、`freshness_query_service.py` | 注册 `continuous_open_day`，观测 `trade_time` 的最大日期。 |
| date completeness audit | `date_completeness_*` | `audit_applicable=false`、`scope=not_applicable`，页面明确显示不适用。 |
| dataset cards / source page | `dataset_definition_projection.py`、`operations_dataset_status_snapshot_service.py` | 展示 raw-only 表、最近成功和观测日期。 |
| Ops 展示目录 | `src/ops/catalog/dataset_catalog_views.py` | 加入 `etf_fund / ETF基金`，建议顺序 70。 |
| ETF active pool | `etf_series_active_seed_service.py`、`EtfSeriesActiveDAO` | 新增 `resource='etf_mins'` 白名单和 1,395 行校验。 |
| frontend | 手动任务页、自动任务页、数据源页、数据集审计页 | 只消费后端 Definition 契约，不自行维护数据集事实。 |

---

## 9. 验收门禁

1. Definition 只声明一个 raw 表和 `raw_only_upsert`。
2. API、页面、planner 和数据库只接受 `1min/5min/15min/30min/60min`。
3. 手动 point/range、自动任务均能生成正确 plan。
4. 未传代码时只使用 `etf_mins` 活跃池；显式代码能覆盖本次任务。
5. range 按五种频率的固定月跨度连续切窗，窗口无重叠、无遗漏，point 不切窗。
6. 每个 unit 最多接纳 `0/8000/16000` 三个 offset 对应的数据页；第三页恰好满页时允许一次 `offset=24000` 边界探测，探测返回任何数据必须以 `source_rows_exceeded` 失败且不写库。
7. 对一个 ETF、一个交易日、五种频率做真实最小同步，逐项对账 fetched、normalized、written、rejected 和表中行数。
8. 任意 reject 或批内重复键导致 unit 失败，并展示结构化错误。
9. 重复执行同一范围后主键行数不膨胀，数据可幂等更新。
10. PostgreSQL 元数据确认父表、全部分区和索引均在 `gs_raw_cold_hdd`。
11. 架构测试确认执行链只包含标准 `DatasetDefinition -> ExecutionPlan -> raw_only_upsert`。

---

## 10. 开发里程碑

1. **M1 Definition 与对象池（已完成）**：已新增 `etf_mins` Definition、Ops 展示目录、活跃池 resource 白名单和 seed 映射。
2. **M2 表与 DAO（已完成）**：已按真实 Alembic head 新增并执行 HDD 月分区 raw 表迁移，ORM 和 DAO 已注册；父表、349 个子表和 700 个索引均位于 `gs_raw_cold_hdd`。
3. **M3 ingestion 主链（已完成）**：已实现按频率切窗的 unit planner、正常一到两页与第三页安全余量、request builder、row transform、endpoint 限速和任意 reject 失败门禁，并接入 `raw_only_upsert`。
4. **M4 Ops 手动与自动任务（已完成）**：通用手动、自动任务契约已覆盖代码、频率和 point/range；工作流反向门禁确认未接入 workflow。
5. **M5 部署与最小生产验收（已完成）**：生产迁移和活跃池初始化完成；TaskRun `9334/9335/9336/9338` 分别验证单频 point 幂等、五频率 point 和切窗 range，均无失败、拒绝或重复膨胀。
6. **M6 全池区间验收（已完成）**：TaskRun `9340` 完成 `2026-07-01~2026-08-24`、1,395 只 ETF、五频率同步；`6,975/6,975` 个 unit 成功，读取和保存均为 `17,464,005` 行，拒绝、去重和 issue 均为 0。
7. **M7 自动任务验收（已完成）**：Schedule `39` 已启用；TaskRun `9384` 将无固定日期 point 正确解析为开市日 `2026-08-25`，`6,975/6,975` 个 unit 成功，读取和保存均为 `447,795` 行，拒绝、去重和 issue 均为 0。
8. **M8 文档与事实收口（已完成）**：接入方案、LLD 和主索引已按当前代码、生产表、TaskRun 与自动任务事实更新，不再保留“待部署/待验收”旧状态。

### 10.1 生产验收事实

| 阶段 | 生产证据 | 验收结果 |
| --- | --- | --- |
| 存储与对象池 | `raw_tushare.etf_minute_bar`；`ops.etf_series_active(resource='etf_mins')` | 活跃池 1,395 个 `.SH/.SZ` 代码，与 `fund_daily` 集合一致；默认分区 0 行；全部表和索引位于 HDD。 |
| 最小任务 | TaskRun `9334/9335/9336` | `510300.SH` 单日单频重复执行保持幂等；五频率单日共 321 行，无 reject。 |
| range 切窗 | TaskRun `9338` | `2025-01-15~2025-05-10` 的 `1min/5min` 生成 4 个 unit，读取和保存均为 21,170 行。 |
| 全池区间 | TaskRun `9340` | 39 个开市日内，五频率均完整覆盖 1,395 只 ETF；每个代码每日分别为 `241/49/17/9/5` 根，时间网格异常、池外数据和空行情字段均为 0。 |
| 自动任务 | Schedule `39`、TaskRun `9384` | 工作日 20:35 触发；`2026-08-25` 五频率全池共 447,795 行，行数严格等于 `1,395 × (241+49+17+9+5)`。 |

---

## 11. 已拍板结论

1. 只有 `raw_tushare.etf_minute_bar` 一张物理业务表。
2. 五种频率全部从 Tushare `etf_mins` 直接下载。
3. 平台只接受 `1min/5min/15min/30min/60min` 五种频率。
4. 手动和自动任务都支持，不进 workflow。
5. 频率交互学习生产 `stk_mins`：普通多选，至少选择一个。
6. 所有表、分区和索引必须位于 HDD。
7. 活跃池使用独立 `resource='etf_mins'`。
8. 一次 TaskRun 按 ETF × 频率 × 受控时间窗口 unit 执行标准 source、normalize、writer 流程。
9. range 按频率分别以 `2/12/36/72/120` 个自然月切窗；每个 unit 按一到两页测算，最多接纳三个数据页、24,000 行，禁止继续放大为深 offset 分页。

---

## 12. 发布与回退

以下发布顺序已全部执行完成：

1. 在开发环境完成 Definition、planner、source、normalizer、writer、ORM 和迁移测试。
2. 执行迁移，确认父表、月分区、默认分区和索引全部位于 `gs_raw_cold_hdd`。
3. 对 `resource='etf_mins'` 先 dry-run seed，人工核对 1,395 个代码后再 apply。
4. 使用一个 ETF、一个交易日、一个频率验证完整链路，再验证五频率任务。
5. 最小验收通过后才允许创建自动任务。

回退只回退应用代码和未执行的自动任务配置。若表中已经写入业务数据，不允许在回退中自动 drop、truncate 或重建；数据清理必须另行列清单并取得明确指令。

---

## 13. 已拍板实施口径

### D1：初始月分区范围

数据库层面可以只依赖默认分区后续再拆月分区，但这会把 DDL 和数据搬移风险留到同步之后。最终拍板：首版迁移连续预建 `2009-01` 至 `2037-12` 的月分区，并建立同样位于 HDD 的默认分区；运行时同步不创建分区。这样覆盖已验证历史和当前可预见未来，超出范围前再走受控 Alembic 迁移。

### D2：显式 ETF 代码是否必须属于 `etf_mins` 活跃池

最终拍板：显式代码也必须属于 `ops.etf_series_active(resource='etf_mins')`，页面搜索、显式单代码任务和全池执行使用同一事实源。池外代码在 planner 阶段直接失败；若需要维护新 ETF，应先更新活跃池，再提交分钟任务。
