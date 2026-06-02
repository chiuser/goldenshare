# Dagster 股票涨跌停资产接入方案

状态：调研结论已形成；SL-0 关键口径已拍板；尚未进入代码开发。

更新时间：2026-06-02

## 1. 目标

把股票涨跌停相关 Tushare 数据集接入 Dagster 新湖，先完成 raw / silver 两层资产设计：

| 业务数据集 | 计划 raw 资产 | Tushare 接口 | 旧湖目录 |
|---|---|---|---|
| 每日涨跌停价格 | `raw_tushare_stk_limit` | `stk_limit` | `raw_tushare/stk_limit` |
| 连板天梯 | `raw_tushare_limit_step` | `limit_step` | `raw_tushare/limit_step` |
| 涨跌停列表（新） | `raw_tushare_limit_list_d` | `limit_list_d` | `raw_tushare/limit_list_d` |
| 涨跌停榜单（同花顺） | `raw_tushare_limit_list_ths` | `limit_list_ths` | `raw_tushare/limit_list_ths` |
| 最强板块统计 | `raw_tushare_limit_cpt_list` | `limit_cpt_list` | `raw_tushare/limit_cpt_list` |
| 开盘啦榜单 | `raw_tushare_kpl_list` | `kpl_list` | `raw_tushare/kpl_list` |

本方案只定义资产接入路线和关键口径，不实现代码、不注册 Dagster Definitions、不写新湖、不触发 job/sensor/backfill。

核心目标：

1. 历史数据先从旧湖 bootstrap 到 `2026-05-15`。
2. `2026-05-16` 至最新日期用 prod DB 补齐，之后日常默认从 prod DB 更新到新湖 raw。
3. Tushare API 保留为人工备用和受控修复入口，不作为日常默认来源。
4. raw 层保持 Tushare 源字段契约，不做业务过滤。
5. silver 层负责日期标准化、类型标准化、去重和业务质量 checks。
6. 不把旧湖路径、bootstrap 来源、source method 写入 parquet 字段；这些只进入 materialization metadata。

## 2. 依据

### 2.1 代码与规范依据

已阅读并对齐：

| 文件 | 结论 |
---|---|
| `AGENTS.md` | 新增数据集必须先做源接口真实行为验证；禁止猜测式编码。 |
| `lake_console/orchestrator/AGENTS.md` | Dagster 设计必须先确认方案；正式资产必须走长期命名、schema contract、checks、job/sensor 边界。 |
| `lake_console/orchestrator/CODING_STANDARDS.md` | 正式 asset 必须注册 definition column schema；materialization metadata 只记录 observed columns。 |
| `lake_console/docs/design/dagster-asset-schema-contract-design.md` | 新增 raw/silver asset 必须在 `asset_column_schemas.py` 注册字段契约。 |
| `lake_console/docs/templates/dagster-dataset-onboarding-template.html` | 新数据集接入需要先完成旧湖审计、Tushare 文档与 MCP 实测、分区/路径/checks/job/sensor 设计。 |

当前代码审计结论：

1. `lake_console/orchestrator/src/orchestrator/defs/assets/**` 中尚无上述 6 个涨跌停相关 Dagster asset。
2. 已有通用能力可复用：
   - old lake bootstrap：`defs/bootstrap/**`
   - Tushare 分页拉取写 raw：`defs/tushare_api_io.py`
   - prod DB 只读资源：`ProdPostgresResource`
   - schema contract：`defs/run_contracts/asset_column_schemas.py`
   - asset/check/job/sensor 分层组织。
3. 分钟线 `stk_mins` 已实现“双来源写同一套 raw asset”的长期模式：默认日常从 prod DB 只读抽取，Tushare 作为人工备用；涨跌停资产族可以复用这个模式，但不能新建 `*_from_prod` 平行资产。

### 2.2 Prod DB 生产代码审计依据

已按当前代码审计旧 prod DB 生产链路，后续 Dagster 接入必须完全参考这些事实，不允许重新猜 fanout、分页或去重策略：

| 数据集 | DatasetDefinition | request builder | fanout / 参数来源 | page limit | 旧 prod 去重主键 |
|---|---|---|---|---:|---|
| `stk_limit` | `src/foundation/datasets/definitions/market_equity.py` | `_stk_limit_params` | `trade_date`，可选 `ts_code` | 5800 | `(ts_code, trade_date)` |
| `limit_step` | `src/foundation/datasets/definitions/market_equity.py` | `_limit_step_params` | `trade_date`，可选 `ts_code/nums` | 2000 | `(ts_code, trade_date, nums)` |
| `limit_list_d` | `src/foundation/datasets/definitions/market_equity.py` | `_limit_list_params` | `limit_type in ('U','D','Z')`，`exchange in ('SH','SZ','BJ')` | 2500 | `(ts_code, trade_date, limit)` |
| `limit_list_ths` | `src/foundation/datasets/definitions/market_equity.py` | `_limit_list_ths_params` | `limit_type in ('涨停池','连板池','冲刺涨停','炸板池','跌停池')`，`market in ('HS','GEM','STAR')` | 4000 | `(trade_date, ts_code, query_limit_type, query_market)` |
| `limit_cpt_list` | `src/foundation/datasets/definitions/market_equity.py` | `_limit_cpt_list_params` | `trade_date`，可选 `ts_code` | 2000 | `(ts_code, trade_date)` |
| `kpl_list` | `src/foundation/datasets/definitions/board_hotspot.py` | `_kpl_list_params` | `tag in ('涨停','炸板','跌停','自然涨停','竞价')` | 8000 | `(ts_code, trade_date, tag)` |

旧 prod 去重事实：

1. 旧系统写入使用 `raw_core_upsert`。
2. DAO 在入库前按 conflict key 去重，`deduped_by_key[key] = row`，同一 key 后到行覆盖先到行。
3. 未显式配置 `conflict_columns` 时，conflict key 来自 SQLAlchemy model primary key。
4. PostgreSQL 最终使用 `ON CONFLICT DO UPDATE`，所以旧 prod DB 中保留的是每个主键的最终版本。
5. 新湖实现不得改成凭空设计的“全字段 distinct 作为主去重策略”；应按上表主键复刻旧 prod upsert 语义，再用 exact duplicate check 防止投影或 fanout 合并后产生完全重复行。

### 2.3 计算与审计门禁

本资产族涉及历史分区、日常分区、fanout 合并和字段校验，所有耗时计算必须走 SQL 引擎：

1. parquet 文件校验、字段校验、行数统计、分区日期校验、去重审计、样本差异统计必须用 DuckDB SQL。
2. prod DB 表结构、行数、日期范围、字段投影、重复审计必须用 PostgreSQL SQL。
3. Python 只做编排、参数校验、路径拼接、SQL 结果汇总和 Dagster metadata 组装。
4. 禁止在正式链路里用 Python 对大体量明细行做循环计算、逐行校验、逐行合并或逐行写 parquet。

### 2.4 本地 Tushare 文档依据

| 接口 | 本地文档 |
---|---|
| `stk_limit` | `docs/sources/tushare/股票数据/行情数据/0183_每日涨跌停价格.md` |
| `limit_list_d` | `docs/sources/tushare/股票数据/打板专题数据/0298_涨跌停列表（新）.md` |
| `limit_list_ths` | `docs/sources/tushare/股票数据/打板专题数据/0355_涨跌停榜单（同花顺）.md` |
| `limit_step` | `docs/sources/tushare/股票数据/打板专题数据/0356_连板天梯.md` |
| `limit_cpt_list` | `docs/sources/tushare/股票数据/打板专题数据/0357_最强板块统计.md` |
| `kpl_list` | `docs/sources/tushare/股票数据/打板专题数据/0347_开盘啦榜单数据.md` |

### 2.5 Tushare MCP 实测依据

已用 `tushareMcp` 做样本核验：

| 接口 | 样本参数 | 实测结论 |
---|---|---|
| `stk_limit` | `trade_date=20260515, ts_code=000001.SZ`，显式请求 `trade_date/ts_code/pre_close/up_limit/down_limit` | 字段与旧湖匹配；`pre_close` 必须显式请求。 |
| `limit_step` | `trade_date=20260515, ts_code=000669.SZ` | 字段与旧湖匹配。 |
| `limit_list_d` | `trade_date=20260515, ts_code=000695.SZ`，显式请求旧湖全字段 | 字段与旧湖匹配；接口响应较慢。 |
| `limit_list_ths` | `trade_date=20260515, ts_code=000010.SZ, limit_type=炸板池, market=HS` | 字段与旧湖匹配；默认不传 `limit_type/market` 会漏类别。 |
| `limit_cpt_list` | `trade_date=20260515, ts_code=881109.TI` | 字段与旧湖匹配；`cons_nums/rank` 的返回类型与旧湖 parquet 类型存在差异，需要设计时统一。 |
| `kpl_list` | `trade_date=20260515, ts_code=000010.SZ, tag=炸板` | 字段与旧湖匹配；必须按 `tag` 枚举拉取。 |

## 3. 旧湖数据现状

旧湖根路径：

```text
/Volumes/datasource/goldenshare-tushare-lake/raw_tushare
```

只读审计结果：

| 数据集 | 旧湖目录 | 起始日 | 最新日 | 分区数 | 行数 | 旧湖字段 |
|---|---|---:|---:|---:|---:|---|
| `stk_limit` | `stk_limit` | 2024-01-02 | 2026-05-15 | 570 | 4,039,398 | `trade_date, ts_code, pre_close, up_limit, down_limit` |
| `limit_step` | `limit_step` | 2023-11-13 | 2026-05-15 | 605 | 12,426 | `trade_date, ts_code, name, nums` |
| `limit_list_d` | `limit_list_d` | 2020-01-02 | 2026-05-15 | 1540 | 153,214 | `trade_date, ts_code, industry, name, close, pct_chg, amount, limit_amount, float_mv, total_mv, turnover_ratio, fd_amount, first_time, last_time, open_times, up_stat, limit_times, limit` |
| `limit_list_ths` | `limit_list_ths` | 2023-11-01 | 2026-05-15 | 613 | 95,835 | `trade_date, ts_code, name, price, pct_chg, open_num, lu_desc, limit_type, tag, status, first_lu_time, last_lu_time, first_ld_time, last_ld_time, limit_order, limit_amount, turnover_rate, free_float, lu_limit_order, limit_up_suc_rate, turnover, rise_rate, sum_float, market_type` |
| `limit_cpt_list` | `limit_cpt_list` | 2023-11-13 | 2026-05-15 | 605 | 12,133 | `trade_date, ts_code, name, days, up_stat, cons_nums, up_nums, pct_chg, rank` |
| `kpl_list` | `kpl_list` | 2025-01-02 | 2026-05-15 | 328 | 117,203 | `trade_date, ts_code, name, lu_time, ld_time, open_time, last_time, lu_desc, tag, theme, net_change, bid_amount, status, bid_change, bid_turnover, lu_bid_vol, pct_chg, bid_pct_chg, rt_pct_chg, limit_order, amount, turnover_rate, free_float, lu_limit_order` |

唯一性观察：

| 数据集 | `trade_date + ts_code` 是否应唯一 | 旧湖观察 |
---|---|---|
| `stk_limit` | 是 | 无重复。 |
| `limit_step` | 是 | 无重复。 |
| `limit_list_d` | 是 | 无重复。 |
| `limit_list_ths` | 否 | 同一股票同日可同时落入不同榜单类别，旧湖存在多行是正常业务事实。 |
| `limit_cpt_list` | 是 | 无重复。 |
| `kpl_list` | 否 | 同一股票同日可对应不同标签或状态，旧湖存在多行是正常业务事实。 |

## 4. Prod DB 数据现状

prod DB 只读审计确认，6 张目标表都存在于 `raw_tushare` schema：

| 数据集 | prod 表 | 起始日 | 最新日 | 行数 | 结论 |
|---|---|---:|---:|---:|---|
| `stk_limit` | `raw_tushare.stk_limit` | 2024-01-02 | 2026-06-01 | 4,123,166 | 可作为日常来源。 |
| `limit_step` | `raw_tushare.limit_step` | 2023-11-13 | 2026-06-01 | 12,622 | 可作为日常来源。 |
| `limit_list_d` | prod DB 既有只读来源表 | 2020-01-02 | 2026-06-01 | 154,603 | 可作为日常来源；prod 物理表名不进入本方案命名口径，新湖 asset/path/API/check/job/sensor 一律使用 `limit_list_d`。 |
| `limit_list_ths` | `raw_tushare.limit_list_ths` | 2023-11-01 | 2026-06-01 | 97,937 | 可作为日常来源。 |
| `limit_cpt_list` | `raw_tushare.limit_cpt_list` | 2023-11-13 | 2026-06-01 | 12,353 | 可作为日常来源。 |
| `kpl_list` | `raw_tushare.kpl_list` | 2025-01-02 | 2026-06-01 | 122,489 | 可作为日常来源；prod DB 已更新到 2026-06-01，更新时间与其它表不同，按接口文档单独设置触发窗口。 |

2026-05-15 样本行数与旧湖对应分区一致：

| 数据集 | 旧湖 2026-05-15 行数 | prod DB 2026-05-15 行数 |
|---|---:|---:|
| `stk_limit` | 7,599 | 7,599 |
| `limit_step` | 13 | 13 |
| `limit_list_d` | 107 | 107 |
| `limit_list_ths` | 185 | 185 |
| `limit_cpt_list` | 20 | 20 |
| `kpl_list` | 426 | 426 |

prod DB 与新湖 raw 的边界：

1. prod DB 表包含系统字段 `api_name/fetched_at/raw_payload`，这些字段不得进入新湖 raw parquet。
2. `limit_list_ths` prod 表包含 `query_limit_type/query_market`，它们不是 Tushare 输出字段，只是 prod DB 为记录 fanout 请求参数保存的查询维度；不得进入新湖 raw parquet。
3. Tushare `limit_list_ths` 输出字段中有 `limit_type` 和 `market_type`，这两个才是源接口业务字段。
4. prod DB 投影到新湖目标字段后，本轮审计未发现 exact duplicate。
5. prod DB 的 `trade_date` 是 `DATE`；新湖 raw 如果保持 Tushare 源镜像，写入 parquet 前必须 cast 成 `YYYYMMDD` 字符串。

## 5. 固定命名口径

### 5.1 `limit_list_d`

已拍板：新湖 asset、路径、字段契约和文档统一使用 `limit_list_d`。旧湖和本地文档事实是：

```text
旧湖物理目录：raw_tushare/limit_list_d
Tushare 接口：limit_list_d
本地文档：0298_涨跌停列表（新）
```

设计要求：

1. 正式 asset 使用 `raw_tushare_limit_list_d` / `silver_limit_list_d`。
2. 正式路径使用 `limit_list_d`。
3. Tushare source API 使用 `limit_list_d`。
4. prod DB 现有物理表名只作为只读来源映射事实，不进入新湖 asset/path/check/job/sensor 命名。
5. 除了只读来源映射事实，不再使用其它名称指代本数据集。

## 6. Tushare 接口拉取口径

正式实现必须完全参考旧 prod DB 的 request builder 和 fanout 方式：

1. 参数生成以 `src/foundation/ingestion/request_builders.py` 的对应函数为准。
2. fanout 枚举以 `src/foundation/ingestion/constants.py` 和 `DatasetDefinition.planning.enum_fanout_defaults` 为准。
3. page limit 以旧 `DatasetDefinition.planning.page_limit` 为准。
4. Tushare 备用入口只允许复刻旧 prod 请求方式，不允许重新发明“无 fanout 拉全集”“只拉部分市场”等新策略。

### 6.1 单接口请求形态

| 接口 | 日常主参数 | 分页 | 特殊要求 |
---|---|---|---|
| `stk_limit` | `_stk_limit_params` 生成 `trade_date=YYYYMMDD`，可选 `ts_code` | `limit/offset`，`limit=5800` | 显式请求 `pre_close`。 |
| `limit_step` | `_limit_step_params` 生成 `trade_date=YYYYMMDD`，可选 `ts_code/nums` | `limit/offset`，`limit=2000` | 无枚举 fanout。 |
| `limit_list_d` | `_limit_list_params` 生成 `trade_date/limit_type/exchange`，可选 `ts_code` | `limit/offset`，`limit=2500` | 按旧 prod 口径固定 fanout，不再重新评估是否 fanout。 |
| `limit_list_ths` | `_limit_list_ths_params` 生成 `trade_date/limit_type/market`，可选 `ts_code` | `limit/offset`，`limit=4000` | 必须按 `limit_type` 与 `market` fanout。 |
| `limit_cpt_list` | `_limit_cpt_list_params` 生成 `trade_date=YYYYMMDD`，可选 `ts_code` | `limit/offset`，`limit=2000` | 响应较慢，日更任务需考虑超时与重试。 |
| `kpl_list` | `_kpl_list_params` 生成 `trade_date/tag`，可选 `ts_code` | `limit/offset`，`limit=8000` | 必须按 `tag` fanout。 |

### 6.2 需要保留的 fanout 口径

从旧 prod `DatasetDefinition` 审计到的历史 fanout 口径，已作为新湖 Tushare 备用入口的正式口径：

| 接口 | fanout 参数 |
---|---|
| `limit_list_d` | `limit_type in ('U','D','Z')`，`exchange in ('SH','SZ','BJ')` |
| `limit_list_ths` | `limit_type in ('涨停池','连板池','冲刺涨停','炸板池','跌停池')`，`market in ('HS','GEM','STAR')` |
| `kpl_list` | `tag in ('涨停','炸板','跌停','自然涨停','竞价')` |

设计结论：

1. 需要 fanout 的接口，raw asset 内部必须显式遍历全部枚举并合并结果。
2. fanout 参数是请求过程信息，不应写入 parquet 字段，除非 Tushare 输出字段本身包含对应业务字段。
3. 对 prod DB 来源，fanout 查询维度只允许作为抽取过程统计，不允许作为 raw parquet 正式字段。
4. `limit_list_ths` 的 `query_limit_type/query_market` 可在内部 staging 中用于复刻旧 prod 主键语义，但最终 raw/silver parquet 必须丢弃这两个查询字段。
5. `limit_list_d` 不再保留“是否需要 fanout”的待确认项，正式按旧 prod `limit_type × exchange` fanout 实现。

fanout 合并后不应产生完全重复行，指的是同一条源业务记录不应因为多组请求参数被重复写入。例如 `limit_list_d` 按 `exchange=SH/SZ/BJ` 扇出时，请求 `exchange=SH` 和请求 `exchange=SZ` 不应该同时返回完全相同的 `000001.SZ, 20260601, U, ...` 行。正式写入时先按旧 prod 主键 upsert 语义取每个 key 的最终版本，再用 exact duplicate check 防止投影后出现完全相同的重复行。这个 check 防的是“多路请求合并造成重复写入”，不是禁止 `limit_list_ths/kpl_list` 的同股同日多类别业务事实。

### 6.3 源站 ready 时间差异

| 接口 | 文档/观察到的更新时间口径 | 对 sensor 的影响 |
---|---|---|
| `stk_limit` | 文档写每日约 8:40 更新当日涨跌停价格。 | 可早于收盘更新；不应和收盘后榜单强绑。 |
| `limit_list_ths` | 文档写每日约 16:00 更新。 | 适合收盘后 readiness 探测。 |
| `kpl_list` | 文档写次日约 8:30 更新。 | 不能要求当日收盘后一定 ready。 |
| `limit_step` | 本轮未确认精确更新时间。 | 开发前需要单独 readiness 样本验证。 |
| `limit_list_d` | 本轮未确认精确更新时间。 | 开发前需要单独 readiness 样本验证。 |
| `limit_cpt_list` | 本轮未确认精确更新时间。 | 开发前需要单独 readiness 样本验证，且响应较慢。 |

设计结论：

1. 这 6 个接口不应默认绑定到同一个 sensor 触发窗口。
2. 第一版可以先做手动 job / UI backfill；sensor 在字段和历史迁移稳定后再设计。
3. 若要日更自动化，应该按接口 readiness 分组，而不是简单“一个涨跌停 sensor 跑全部”。

## 7. Raw 层设计口径

### 7.1 路径

建议路径：

```text
raw/tushare/stk_limit/trade_date=YYYY-MM-DD/part-000.parquet
raw/tushare/limit_step/trade_date=YYYY-MM-DD/part-000.parquet
raw/tushare/limit_list_d/trade_date=YYYY-MM-DD/part-000.parquet
raw/tushare/limit_list_ths/trade_date=YYYY-MM-DD/part-000.parquet
raw/tushare/limit_cpt_list/trade_date=YYYY-MM-DD/part-000.parquet
raw/tushare/kpl_list/trade_date=YYYY-MM-DD/part-000.parquet
```


### 7.2 字段类型

raw 层原则：

1. Tushare 日期字段保留 `YYYYMMDD` 字符串。
2. raw 字段名保持源字段名，不把 `change` 一类字段改成 silver 名。
3. 旧湖 bootstrap 时必须把旧湖 parquet 类型归一到新 raw schema contract，不能直接把旧湖物理类型当新湖长期契约。

当前特殊风险：

```text
limit_cpt_list
```

旧湖 parquet：

```text
cons_nums BIGINT
rank VARCHAR
```

MCP 样本：

```text
cons_nums 可能返回字符串 "1"
rank 可能返回数字 20
```

设计要求：

1. `limit_cpt_list.cons_nums` 按整型注册和写入。
2. `limit_cpt_list.rank` 按整型注册和写入。
3. bootstrap、prod DB、Tushare API 三条写入路径必须使用同一 schema contract。
4. 若来源返回类型不稳定，raw 写入 helper 应按字段契约显式 cast，避免同一 asset 不同分区 parquet schema 漂移。

### 7.3 Prod DB 字段白名单和 cast 规则

prod DB 字段白名单的含义：

1. 只从 prod DB 读取新湖 raw 需要的 Tushare 业务字段。
2. 不读取、不写入、不暴露 prod DB 系统字段。
3. 不使用 `SELECT *`。
4. 每个 prod DB helper 必须像 `prod_db/stk_mins.py` 一样定义固定 `SOURCE_COLUMNS` 和固定 SQL。

明确禁止进入新湖 raw parquet 的字段：

```text
api_name
fetched_at
raw_payload
query_limit_type
query_market
```

说明：

1. `api_name/fetched_at/raw_payload` 是 prod DB 采集系统字段。
2. `query_limit_type/query_market` 是 `limit_list_ths` prod 表记录请求参数的查询维度，不是 Tushare 输出字段。
3. `limit_list_ths` 的 Tushare 输出字段是 `limit_type/market_type`，它们应保留。

cast 规则：

| prod DB 类型 | 新湖 raw 写入规则 |
|---|---|
| `DATE trade_date` | cast 为 `YYYYMMDD` 字符串。 |
| `numeric` | 按 schema contract cast 为 `DOUBLE` 或约定整数类型。 |
| `integer` | 按 schema contract cast 为 `INTEGER` / `BIGINT` / `VARCHAR`，不得让不同来源产生 parquet schema 漂移。 |
| `varchar/text` | cast 为 `VARCHAR`。 |
| null | 保持 null，不用哨兵值。 |

### 7.4 Raw checks

建议 raw blocking checks：

| check | 说明 |
---|---|
| file exists | 目标分区文件必须存在。 |
| required columns and types | 字段和 raw schema contract 一致。 |
| partition date matches | 文件内 `trade_date` 必须等于分区日期。 |
| row count positive | `stk_limit` 在开市日必须非空；榜单类数据集也不允许 0 行。 |
| prod key uniqueness / upsert result | 按旧 prod 主键语义确认同一 key 只保留最终版本。 |
| exact duplicate absent | 多路请求或 prod DB 投影后不应产生完全重复行。 |

对 `limit_list_ths` 和 `kpl_list`：

1. 不允许用 `trade_date + ts_code` 做唯一性 blocking check。
2. `limit_list_ths` 的旧 prod 主键包含 `query_limit_type/query_market`，这两个字段只能在 staging/dedup 中使用，不进入最终 parquet。
3. `kpl_list` 的旧 prod 主键是 `ts_code + trade_date + tag`。

各数据集 raw 去重 / key 门禁：

| 数据集 | 去重 / key 口径 |
|---|---|
| `stk_limit` | `(ts_code, trade_date)` |
| `limit_step` | `(ts_code, trade_date, nums)` |
| `limit_list_d` | `(ts_code, trade_date, limit)` |
| `limit_list_ths` | staging 中按 `(trade_date, ts_code, query_limit_type, query_market)` 复刻旧 prod 语义；最终 parquet 丢弃 query 字段后检查 exact duplicate absent。 |
| `limit_cpt_list` | `(ts_code, trade_date)` |
| `kpl_list` | `(ts_code, trade_date, tag)` |

## 8. Checks 定义口径

checks 必须按职责分层，不允许把所有问题塞进一个大 check：

### 8.1 Raw blocking checks

raw blocking checks 用来证明“本分区源数据可以进入标准化”：

| check 类型 | 说明 |
|---|---|
| 文件存在 | 目标 parquet 文件必须存在。 |
| 行数策略 | `stk_limit` 开市日必须非空；榜单类数据集也不允许 0 行。 |
| 字段和类型 | 文件 schema 必须等于 raw schema contract。 |
| 分区日期 | 文件内 `trade_date` 必须等于 Dagster partition key。 |
| exact duplicate | 投影到新湖 raw 字段后不允许完全重复行。 |
| prod key uniqueness / upsert result | 按旧 prod 主键语义确认同一 key 只保留最终版本；`limit_list_ths` 的 query key 只在 staging 中参与，不进入 parquet。 |
prod DB 字段白名单不单独设计为 runtime asset check。它属于 helper 的静态 SQL 合同和单元测试门禁：SQL 只能列出业务字段，禁止 `SELECT *`，禁止出现 `api_name/fetched_at/raw_payload/query_limit_type/query_market`。如果代码真的把这些字段写进 parquet，`字段和类型` raw blocking check 会因为 schema 不等于 raw contract 而失败。因此不再额外设计“prod 投影字段匹配契约”这类独立 check，避免重复检查同一件事。

### 8.2 Silver blocking checks

silver blocking checks 用来证明“标准事实表可被下游消费”：

| check 类型 | 说明 |
|---|---|
| 文件存在 | 目标 silver parquet 必须存在。 |
| 字段和类型 | 文件 schema 必须等于 silver schema contract。 |
| 分区日期 | `trade_date` 必须等于 partition key。 |
| exact duplicate | 标准化后不允许完全重复行。 |
| 业务键唯一性 | 只对业务上应唯一的数据集启用。 |
| 数值 sanity | 价格、成交额、换手率、封单等数值按字段语义校验。 |
| 枚举合法性 | 对 `limit/tag/limit_type/market_type/status` 等字段做合法性检查。 |

### 8.3 WARN checks

第一版不设计 WARN checks。只保留能阻断错误数据入湖的 checks；不会改变生产决策的观测项暂不进入 Dagster checks。

## 9. Silver 层设计口径

### 9.1 通用原则

silver 层负责标准化，不负责改变源站业务含义：

1. `trade_date` 转为 `DATE`。
2. 数值字段统一为稳定数值类型。
3. 时间字段保持字符串，除非明确需要计算。
4. 空值保持真实空值，不用哨兵值。
5. 不过滤当前上市股票，保留源站榜单事实。
6. 不因为股票已退市、未上市或不在当前 `stock_basic` 中就丢弃源榜单记录。

### 9.2 建议 silver 资产

| raw asset | silver asset | 分区 | 主要处理 |
---|---|---|---|
| `raw_tushare_stk_limit` | `silver_stk_limit` | `cn_a_stock_trade_days` | 日期转 DATE，价格字段数值化，唯一性。 |
| `raw_tushare_limit_step` | `silver_limit_step` | `cn_a_stock_trade_days` | 日期转 DATE，`nums` 类型归一。 |
| `raw_tushare_limit_list_d` | `silver_limit_list_d` | `cn_a_stock_trade_days` | 日期转 DATE，数值字段归一，涨/跌/炸板类型保留。 |
| `raw_tushare_limit_list_ths` | `silver_limit_list_ths` | `cn_a_stock_trade_days` | 日期转 DATE，保留榜单类别、市场类型，允许同股同日多行。 |
| `raw_tushare_limit_cpt_list` | `silver_limit_cpt_list` | `cn_a_stock_trade_days` | 日期转 DATE，`cons_nums/rank` 转整型，板块统计字段数值化。 |
| `raw_tushare_kpl_list` | `silver_kpl_list` | `cn_a_stock_trade_days` | 日期转 DATE，保留标签、主题、竞价/封单字段。 |

分区定义已拍板：6 个数据集 raw/silver 全部使用 `cn_a_stock_trade_days`。即使 `kpl_list` 是次日才更新前一交易日数据，分区仍是数据所属 `trade_date`，不是运行自然日。

### 9.3 Silver checks

建议 silver blocking checks：

| check | 说明 |
---|---|
| file exists | silver 分区文件存在。 |
| row count positive | 6 个数据集在开市日都不允许 0 行。 |
| required columns and types | 字段与 silver schema contract 一致。 |
| partition date matches | `trade_date` 等于分区日期。 |
| exact duplicate absent | 禁止完全重复行。 |
| key uniqueness | 只对业务上应唯一的数据集启用。 |
| numeric sanity | 价格、成交额、换手率等字段按接口语义做非负或合理范围检查。 |
| enum value valid | 对 `limit/tag/limit_type/market_type/status` 等枚举字段做合法性 blocking 校验。 |

## 10. Bootstrap 初始化方案

### 10.1 可行性结论

旧湖初始化可行。

依据：

1. 旧湖存在 6 个目标数据集的真实 parquet 分区。
2. 旧湖字段与 Tushare MCP 显式字段整体匹配。
3. 现有 Dagster 已有 old lake bootstrap 引擎，支持按 `trade_date` 分区复制到新湖 raw。
4. prod DB 已有同名 raw 表且比旧湖更新，可作为日常默认来源。
5. Tushare API 能按 `trade_date` 拉取目标接口，可作为人工备用和受控修复来源。

### 10.2 不可直接忽略的风险

| 风险 | 影响 | 处理策略 |
---|---|---|
| `limit_list_d` 只读来源映射 | prod DB 现有物理表名与新湖正式命名不同。 | asset、path、check、job、sensor 统一使用 `limit_list_d`；prod 物理表名只在 prod DB helper 中作为只读来源映射。 |
| `limit_cpt_list` 类型漂移 | 历史分区和 API 新分区 schema 可能不一致。 | raw 写入显式 cast 到 schema contract。 |
| 多路请求合并重复 | 多组请求参数可能返回同一条源业务记录。 | raw helper 做完整字段 exact duplicate 处理或阻断，不做额外观测型 check。 |
| 不同接口 ready 时间不同 | 一个 sensor 跑全部会出现部分接口未 ready。 | 第一版先手动 job；自动化分组设计。 |
| `limit_list_ths/kpl_list` 主键复杂 | 错用 `trade_date+ts_code` 会误报重复。 | 只做 exact duplicate，或设计包含类别字段的业务键。 |
| prod DB 系统字段污染 raw | 把 `api_name/fetched_at/raw_payload/query_*` 写进 parquet 会破坏 Tushare 源镜像。 | prod DB helper 必须字段白名单 + schema cast。 |

### 10.3 Bootstrap 验收

初始化边界已拍板：

1. 旧湖 bootstrap 只负责迁移到 `2026-05-15`。
2. `2026-05-16` 至 prod DB 最新日期由 prod DB 补齐。
3. 后续日常默认继续从 prod DB 更新。
4. Tushare API 只作为人工备用或受控修复入口。

每个数据集 bootstrap 前必须先做旧湖预检：

1. 源路径存在。
2. 分区范围和行数与本方案表格一致，或差异有记录。
3. 字段名与 schema contract 一致。
4. 分区目录日期与文件内 `trade_date` 一致。
5. 旧湖数据是否存在完全重复行。

Bootstrap 后验收：

1. 新湖 raw 分区数等于目标交易日分区数。
2. 新湖 raw 字段只包含 Tushare raw contract 字段。
3. materialization metadata 记录 `source_method=old_lake_bootstrap`、`bootstrap_spec`、`partition_key`、`row_count`、`observed_columns`。
4. parquet 字段中不得出现旧湖路径、source method、bootstrap metadata。

## 11. 日常 prod DB 默认更新方案

已拍板口径：

1. 日常默认从 prod DB 更新到新湖 raw。
2. Tushare API 不作为日常默认入口，只保留为人工备用或受控修复入口。
3. prod DB 来源和 Tushare 来源写同一套 raw asset、同一路径、同一组 checks。
4. 不新增 `raw_tushare_xxx_from_prod` 平行资产。
5. 同一次 run 只能选择一个来源，禁止 prod DB 与 Tushare 混用。
6. prod DB 抽取必须参考旧 prod 生产代码的请求/fanout/去重语义，不允许自己猜。

### 11.1 Job 入口

job 已拍板为独立入口：

```text
stk_limit_update_job
limit_step_update_job
limit_list_d_update_job
limit_list_ths_update_job
limit_cpt_list_update_job
kpl_list_update_job
```

设计要求：

1. 每个数据资产一个独立 job。
2. 第一版不做组合 job。
3. job 只做 asset selection，不写请求逻辑、不写 SQL、不做 fanout。
4. 默认来源为 prod DB。
5. Tushare 备用修复能力不通过组合 job 暴露；后续如需要专门 repair 入口，单独设计。

### 11.2 Sensor / readiness

sensor 先不做，后续再讨论。

后续如果设计 sensor，必须按接口文档中的数据更新时间设置触发窗口，不能一刀切。

prod DB 日常 sensor 不直接探测 Tushare，而是检查 prod DB 是否已经出现目标 `trade_date` 数据。

建议后续按数据集独立 readiness：

| 数据集 | readiness 口径 |
|---|---|
| `stk_limit` | prod DB 有目标 `trade_date` 行后触发。 |
| `limit_step` | prod DB 有目标 `trade_date` 行后触发。 |
| `limit_list_d` | prod DB 只读来源表有目标 `trade_date` 行后触发；asset/path 仍统一叫 `limit_list_d`。 |
| `limit_list_ths` | prod DB 有目标 `trade_date` 行后触发；`query_limit_type/query_market` 只允许作为抽取过程统计，不进入 parquet。 |
| `limit_cpt_list` | prod DB 有目标 `trade_date` 行后触发。 |
| `kpl_list` | 独立判断；由于更新时间不同，prod DB 未出现目标日时只 skip，不拖累其它数据集。 |

所有 sensor 必须默认 `STOPPED`，上线前先 preview / 小范围验证。

### 11.3 Tushare 备用入口

Tushare 备用入口仍需保留：

1. 源站字段实测仍以 Tushare MCP 为准。
2. Tushare helper 负责 fanout 和分页。
3. Tushare 与 prod DB 写入相同 raw schema。
4. 受控修复必须明确日期、接口、来源和覆盖/替换策略。
5. Tushare 请求方式必须复刻旧 prod request builder 和 fanout 口径。

## 12. 开发切片建议

### SL-0：设计确认与命名拍板

目标：

1. `limit_list_d` 命名口径已拍板：asset/path/API 统一使用 `limit_list_d`。
2. raw/silver 分区已拍板：6 个数据集全部使用 `cn_a_stock_trade_days`。
3. silver 股票池口径已拍板：不过滤当前上市股票，保留源站榜单事实。
4. `limit_cpt_list.cons_nums/rank` 已拍板：按整型注册和写入。
5. 历史初始化边界已拍板：旧湖到 `2026-05-15`，prod DB 补 `2026-05-16` 至最新。
6. job 口径已拍板：每个数据资产一个独立 job，不做组合 job。
7. sensor 已拍板：第一版不做。

### SL-1：字段契约、路径、bootstrap specs

目标：

1. 新增 raw/silver schema contract。
2. 新增 paths。
3. 新增 bootstrap specs。
4. 不新增 asset/job/sensor。

### SL-2：raw assets 与 raw checks

目标：

1. 实现 prod DB 默认拉取 helper。
2. 实现 Tushare 备用拉取 helper。
3. 实现 raw checks。
4. 实现 fanout helper 和 prod DB 字段白名单校验。
5. 实现按旧 prod 主键语义的 dedup/upsert 结果写入。
6. 单日验证每个接口。

### SL-3：historical bootstrap

目标：

1. 从旧湖迁移 `<= 2026-05-15` 的历史 raw。
2. 用 prod DB 补齐 `2026-05-16` 至 prod DB 最新日期。
3. 补 Dagster materialization/check events。
4. 不生成 silver。

### SL-4：silver assets 与 silver checks

目标：

1. 从 raw 生成 silver。
2. 标准化日期和类型。
3. 完成 silver checks。

### SL-5：jobs

目标：

1. 新增 6 个独立 update jobs。
2. 每个 job 只 selection 对应数据资产和自身 checks。
3. 不新增组合 job。
4. job 只做 selection。

### SL-6：sensor / automation

目标：

1. 第一版不实现 sensor。
2. 后续根据接口文档中的接口数据更新时间设计 sensor 更新时机。
3. 所有 sensor 默认 `STOPPED`。
4. 不在 sensor 里做重 IO 或大量历史扫描。

## 13. 待拍板问题

当前关键业务口径已拍板。后续进入开发前仍需按门禁完成两类技术确认：

| 技术确认项 | 说明 |
|---|---|
| Tushare 备用入口实测 | 虽然请求方式参考旧 prod 代码，但真正实现前仍需用 `tushareMcp` 对显式字段、分页、fanout 样本再次做最小实测。 |
| prod DB helper SQL | 每个 helper 必须只读字段白名单，不得 `SELECT *`，不得把系统字段和查询字段写入 parquet。 |
| `limit_list_ths` staging key | `query_limit_type/query_market` 只用于内部 staging/dedup，不进入 parquet；开发时需用单测锁住。 |
| sensor 更新时间 | 第一版不做；后续根据接口文档更新时间再单独拍板。 |

## 14. 结论

本轮调研结论：

1. 6 个数据集都具备接入 Dagster raw/silver 的条件。
2. 旧湖 bootstrap 到 `2026-05-15` 可行。
3. prod DB 补 `2026-05-16` 至最新并作为日常默认来源可行。
4. Tushare API 备用更新可行，但必须复刻旧 prod request/fanout 方式。
5. 主要风险不是“能不能拉到数据”，而是 fanout 漏数、类型漂移、主键误判、prod DB 系统字段污染和 readiness 时间不一致。
6. `limit_list_d` 命名已收紧；`limit_list_ths/kpl_list` 的正常多行不能被误判成重复数据。
