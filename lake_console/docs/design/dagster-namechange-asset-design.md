# Dagster namechange 资产接入方案

状态：NC-1 至 NC-5 已落地；数据来源、去重、日更触发口径已确认；NC-0 已完成，silver 采用公告生效事件时间线 v2 口径；P2A 已将日常自动链路拆为 `raw_namechange_update_job` / `silver_namechange_update_job`；P2B 已将日常 sensor 改为 09:30 早盘与 17:00 晚盘两阶段触发，silver 触发前等待 raw namechange event/check ready 与 `stock_basic_ready_for_trade_date`，并要求 silver materialization 跟上 raw/stock_basic 最新 storage id。

更新时间：2026-05-30

## 1. 目标与边界

本方案只定义 Tushare `namechange`（股票曾用名 / 历史名称变更记录）接入 Dagster 的正式资产路线。

本次只关注 Dagster 资产接入：

- 新增 `raw_tushare_namechange`。
- 新增 `silver_namechange`。
- 新增对应 asset checks。
- 日常更新入口已拆为 `raw_namechange_update_job` 与 `silver_namechange_update_job`。
- 日更触发 sensor 已拆为 `raw_namechange_update_job_sensor` 与 `silver_namechange_update_job_sensor`。

本次明确不处理：

- 不从旧湖 bootstrap。
- 不生成旧 `manifest/security_reference/tushare_namechange.parquet`。
- 不改造任何下游服务或历史消费者。
- 不讨论 `stk_mins_clean_service`、身份映射、分钟线清洗等其它需求。
- 不引入 gold / serving / ClickHouse。
- 不把旧湖独有记录作为 correction 或人工补丁写入新湖；raw 始终接受 Tushare source mirror。2026-07-14 复测证明无筛选全量查询会漏行，正式取数应以公告日期自适应切窗的 source 并集为准，不能把无筛选 `limit/offset` 翻页单独视为完整事实。

## 2. 依据与已读门禁

开发前必须先读并遵守：

- `lake_console/orchestrator/AGENTS.md`
- `lake_console/orchestrator/CODING_STANDARDS.md`
- `lake_console/docs/design/dagster-asset-schema-contract-design.md`
- `lake_console/docs/templates/dagster-dataset-onboarding-template.html`
- `docs/sources/tushare/股票数据/基础数据/0100_股票曾用名.md`

已完成的调研动作：

- 使用 `tushare-data` skill 理解 `namechange` 属于股票基础数据 / 基础主数据类接口。
- 使用 `tushareMcp.namechange` 实测默认返回、显式 fields 返回、按公告日期范围返回。
- 只读审计旧湖 `raw_tushare/namechange/current/part-000.parquet` 与 manifest 文件。
- 审计当前 Dagster `adj_factor`、`stock_basic`、bootstrap、paths、schema contract、Tushare IO helper 的实现方式。

## 3. 业务说明卡

| 项目 | 结论 |
|---|---|
| 数据集名称 | 股票曾用名 |
| Tushare 接口 | `namechange` |
| 业务含义 | A 股股票名称历史变更区间事实，记录某只股票在某段时间使用过的证券名称及变更原因。 |
| 数据域 | `basic_data` |
| 层级 | raw / silver |
| 分区模型 | full snapshot，不设置 `partitions_def` |
| 更新方式 | 从 Tushare API 按公告日期自适应切窗读取完整 source 并集，exact distinct 后原子替换 full parquet |
| 旧湖用途 | 只作为调研证据，不作为本次集成数据来源 |
| 下游消费 | 本方案不设计下游消费；后续如有下游需求，单独设计依赖关系 |
| 日常 raw job | `raw_namechange_update_job` |
| 日常 silver job | `silver_namechange_update_job` |
| 日常 raw sensor | `raw_namechange_update_job_sensor`，跟随 `stock_current_trade_day_sensor` 注册出的当天交易日信号 |
| 日常 silver sensor | `silver_namechange_update_job_sensor`，按早盘/晚盘等待 raw namechange 和 stock_basic final ready，并确认 silver 跟上最新 upstream storage id |

## 4. Tushare 接口契约

本地文档：

```text
docs/sources/tushare/股票数据/基础数据/0100_股票曾用名.md
```

接口：

```text
namechange
```

输入参数：

| 参数 | 类型 | 必填 | 说明 | 本方案口径 |
|---|---|---:|---|---|
| `ts_code` | str | 否 | TS 股票代码 | full snapshot 不传；不把单代码请求当成日常生产入口 |
| `start_date` | str | 否 | 公告开始日期 | 由 namechange 专用 reader 内部生成闭区间，不向运营暴露 |
| `end_date` | str | 否 | 公告结束日期 | 由 namechange 专用 reader 内部生成闭区间，不向运营暴露 |
| `limit` | int | 否 | 分页长度 | 固定 6000；叶子窗口必须少于该值 |
| `offset` | int | 否 | 请求数据的开始位移量 | 固定为 0；叶子窗口禁止 offset 翻页，满页时改按公告日期二分 |

输出字段：

| 字段 | Tushare 类型 | 默认返回 | 说明 |
|---|---|---:|---|
| `ts_code` | str | 是 | 股票代码 |
| `name` | str | 是 | 证券名称 |
| `start_date` | str | 是 | 名称生效开始日期，`YYYYMMDD` |
| `end_date` | str | 是 | 名称生效结束日期，`YYYYMMDD` 或空 |
| `ann_date` | str | 是 | 公告日期，`YYYYMMDD` 或空 |
| `change_reason` | str | 是 | 变更原因 |

名称区间语义：

1. 如果一行只有 `start_date`，没有 `end_date`，表示从 `start_date` 开始，该股票使用这一行的 `name`。
2. 如果一行同时有 `start_date` 和 `end_date`，表示这一行的 `name` 使用到 `end_date`；`end_date` 之后的第一个交易日，应切换到后续名称记录。
3. 因此，Tushare 最新数据中出现“旧区间补上 `end_date` + 新区间新增 open interval”是正常更新形态，不是 raw 层冲突。
4. raw 层不能用 `ts_code + start_date` 作为唯一键阻断；raw 只做全字段完全一致去重。区间解释和异常观测放在 silver checks。

MCP 实测结论：

- `ts_code=000001.SZ` 默认返回字段与显式 fields 返回字段一致。
- Tushare 返回日期是 `YYYYMMDD` 字符串，不是 DATE。
- `start_date/end_date` 输入参数按公告日期过滤，不是按名称生效日期过滤。
- 源站会返回完全重复行。例如 `000001.SZ` 和 `688287.SH` 查询结果中存在所有字段完全一致的重复记录。

因此第一版 raw 写入必须：

- 显式请求字段 `ts_code,name,start_date,end_date,ann_date,change_reason`。
- 使用 full snapshot，不把 lake 文件按公告日期或生效日期分区；但 source 读取按公告日期窗口切分，以保证 source 完整性。
- 对所有字段完全一致的行做 `DISTINCT`。
- 在 materialization metadata 上报去重前后行数和 `duplicate_removed_count`。

## 5. 旧湖审计结论

旧湖文件：

```text
/Volumes/datasource/goldenshare-tushare-lake/raw_tushare/namechange/current/part-000.parquet
/Volumes/datasource/goldenshare-tushare-lake/manifest/security_reference/tushare_namechange.parquet
```

只读审计结果：

| 项目 | 结果 |
|---|---:|
| raw 文件数 | 1 |
| raw 行数 | 20,265 |
| 股票代码数 | 6,113 |
| raw 与 manifest 差异 | 0 |
| 完全重复行 | 0 |
| `ts_code` 空值 | 0 |
| `name` 空值 | 0 |
| `start_date` 空值 | 0 |
| `end_date` 空值 | 12,008 |
| `ann_date` 空值 | 15,295 |
| `change_reason` 空值 | 0 |
| `start_date` 范围 | 1990-12-01 至 2026-05-19 |
| `ann_date` 范围 | 2010-06-23 至 2026-05-15 |
| `end_date < start_date` | 0 |

旧湖字段类型：

| 字段 | 旧湖类型 |
|---|---|
| `ts_code` | `VARCHAR` |
| `name` | `VARCHAR` |
| `start_date` | `DATE` |
| `end_date` | `DATE` |
| `ann_date` | `DATE` |
| `change_reason` | `VARCHAR` |

本方案不使用旧湖 bootstrap 的原因：

1. `namechange` 是 full snapshot 类型，直接从 Tushare 拉取全集更符合正式口径。
2. 旧湖快照与 Tushare 最新 distinct 数据高度一致，但旧湖已落后于当前线上变化。
3. 旧湖日期列已被转成 DATE，而 raw 层正式契约应保持 Tushare `YYYYMMDD` 字符串。
4. 旧湖只作为历史对照和风险审计依据，不作为正式 bootstrap 来源。

### 5.1 Tushare 最新 vs 旧湖 distinct diff

2026-05-30 已完成一次事实 diff。临时 CSV / Markdown 报告仅用于当轮审计复核，长期结论以内嵌在本方案中的统计和口径为准。

diff 口径：

- 对旧湖与 Tushare 最新数据分别按 6 个源字段做全字段 distinct。
- 6 个字段为：`ts_code,name,start_date,end_date,ann_date,change_reason`。
- 两边共同记录必须 6 个字段逐字段完全一致。

结果：

| 指标 | 旧湖 curated | Tushare 最新 |
|---|---:|---:|
| 原始行数 | 20,265 | 34,528 |
| 全字段 distinct 行数 | 20,265 | 20,315 |
| 全字段重复行数 | 0 | 14,213 |
| 股票代码数 | 6,113 | 6,117 |

| Diff 指标 | 数量 |
|---|---:|
| 两边全字段共同 distinct 行 | 20,263 |
| 旧湖独有 distinct 行 | 2 |
| Tushare 最新独有 distinct 行 | 52 |

结论：

1. 旧湖与 Tushare 最新 distinct 数据主体一致，可以直接采用 Tushare 最新 full snapshot 作为正式来源。
2. Tushare 源站会返回大量全字段重复行，raw 入湖必须先做全字段 distinct。
3. 旧湖独有 2 行为 `003033.SZ 征和工业`、`601963.SH 重庆银行` 的 2020-12-22 初始名称记录；第一版不保留、不补写、不做 correction，完全接受 Tushare 最新 full snapshot。
4. Tushare-only 52 行主要是 2026 年 5 月之后发生或确认的名称、ST、退市变化；其中部分 `start_date` 早于 2026-05，是旧名称区间在新公告后补上 `end_date` 的正常区间闭合。
5. 因为 Tushare-only 主要是新近变化，第一版采用 Tushare full replace 比旧湖 bootstrap 更合理。

### 5.2 Tushare 最新区间异常预审计

开发前必须先做一次区间审计，不能靠“理论上应该没有矛盾”来写 checks。2026-05-30 已对 Tushare 最新数据完成 NC-0 只读审计。临时 CSV / Markdown 报告仅用于当轮复核，长期结论以内嵌在本方案中的统计和口径为准。

基础统计：

| 指标 | 数量 |
|---|---:|
| Tushare 最新原始行数 | 34,528 |
| Tushare 最新全字段 distinct 行数 | 20,315 |
| 全字段重复行数 | 14,213 |
| 股票代码数 | 6,117 |
| `end_date IS NULL` 行数 | 12,036 |
| 存在多条 open interval 的股票代码数 | 2,882 |
| open interval 之后还有更晚 `start_date` 行的股票代码数 | 2,879 |
| 同一 `ts_code + start_date` 存在多种 `name/end_date/ann_date/change_reason` 变体的 key 数 | 1,824 |
| 按原始 distinct 行直接判断的区间重叠 pair 数 | 13,375 |

候选策略审计结果：

| 策略 | 输出行数 | unresolved conflict | 结论 |
|---|---:|---:|---|
| `source_distinct_only` | 20,315 | 18,081 | 失败；只做 raw distinct 会保留大量多 open / overlap |
| `prefer_closed_same_event` | 18,541 | 9,308 | 失败；只在同一事件里优先闭合版本仍不足以解释时间线 |
| `timeline_candidate` | 14,474 | 23 | 失败；能消掉大部分冲突，但没有正确理解同一生效日的多次公告 |
| `latest_announcement_timeline` | 14,419 | 0 | 通过；作为 NC-3 silver 正式规则 |

说人话解释：

- `ann_date` 是公告日期，不是名称生效日期。
- `start_date` 才是变更生效日，表示这一行的 `name` 从哪天开始使用。
- 同一 `ts_code + start_date` 如果出现多条记录，不能简单当重复，也不能随便保留第一条；它可能表示同一个生效日之前发生了多次公告，后公告会修正前公告的“变更后简称”。
- 因此 raw 层仍只做全字段 distinct，保留源站事实；silver 层必须按公告语义整理成“某只股票在某段日期使用哪个名称”的唯一时间线。

已确认的 silver 规则：

1. raw 层只做全字段 distinct，不对多 open / overlap 做 blocking。
2. silver 采用 `latest_announcement_timeline_v3` 规则。
3. 同一 `ts_code + start_date` 下，优先选择 `ann_date` 最新的公告版本；`ann_date` 为空视为低优先级。
4. 如果同一 `ts_code + start_date + ann_date` 仍存在多行，优先保留带 `end_date` 的版本；若是同名候选，继续按 v2 同名裁决规则处理；如果仍无法唯一确定，则 `silver_namechange` 失败。
5. 选定每个生效日的有效公告后，按 `ts_code/start_date` 排序生成名称时间线。
6. 连续相同 `name` 的噪声记录需要合并为一个区间。
7. 如果当前段源 `end_date` 为空，或源 `end_date >= 下一段 start_date`，则用 `下一段 start_date - 1 day` 闭合当前段，避免 overlap。
8. 如果当前段源 `end_date < 下一段 start_date`，保留源 `end_date`，允许中间存在 gap。
9. 最后一段如果源 `end_date` 为空则保持 open；如果源端给了 `end_date`，则保留该结束日。
10. 最终表必须满足：同一股票同一时间点最多只能命中一个名称区间；同一股票最多只能有一个当前 open interval。
11. 如果归并逻辑无法解释某个股票的区间矛盾，`silver_namechange` 直接失败，并在 metadata / check metadata 中输出股票代码、样本区间和原因。
12. `latest_announcement_timeline_v3` 增加三个正式裁决规则：
   - `摘星` 与 `撤销*ST` 视为同义变更原因；同名同区间下，如果候选里同时存在 `其他` 和非 `其他` 原因，优先保留非 `其他` 的具体原因。
   - 对 `same_name_diff_end`，如果候选的 `ts_code/name/start_date/ann_date/归一后 change_reason` 都一致，只是 `end_date` 不同，则选择 `end_date` 距离现在更近的候选。
   - 对 `diff_name_same_start`，只有当候选行除了 `name` 之外其它字段完全一致时，才允许用 `silver_stock_basic.name` 对齐选择当前上市股票名称；如果其它字段也不同、stock basic 名称未命中或命中不唯一，继续阻断。
   - 对仍无法由通用规则解释的少量候选，按人工审计表中 `selected=Y` 的精确行登记 case-by-case override；override 必须精确到 `ts_code/name/start_date/end_date/ann_date/change_reason`，不得按股票代码或原因模糊匹配。

相邻区间 gap 前置审计：

- 按“保留源 `end_date`，只在会 overlap 时才向前闭合”的口径，全量只发现 1 个相邻 gap：`000022.SZ 深赤湾A` 源 `end_date=2018-12-24`，下一名称 `招商港口 start_date=2018-12-26`，中间缺 `2018-12-25`。
- 这类 gap 不阻断。它可能来自代码迁移、换股、上市主体变化、源站口径差异或停牌等历史边界；只要不 overlap，就不影响“某天最多命中一个名称”的标准事实。
- 全量审计结果：`adjacent_gap_count=1`，`adjacent_gap_code_count=1`，`adjacent_overlap_count=0`，`multi_open_code_count=0`，`invalid_date_order_count=0`。
- NC-3 实现时必须把这个 gap 作为已知例外登记，避免未来把 gap 误判成新增数据质量问题。

已知相邻 gap 登记：

| ts_code | current_name | current_start_date | current_end_date | next_name | next_start_date | gap_date | 处理口径 |
|---|---|---|---|---|---|---|---|
| `000022.SZ` | `深赤湾A` | `2006-10-09` | `2018-12-24` | `招商港口` | `2018-12-26` | `2018-12-25` | 已确认源数据边界；silver 不自动补齐，不阻断；metadata / WARN 样本中显式记录 |

后续如果 NC-3 开发时发现新的 gap，不能自动加入放行范围，必须先做样本审计并回到本文档登记。

皇台酒业示例：

| ts_code | name | start_date | end_date |
|---|---|---|---|
| `000995.SZ` | `*ST皇台` | `2018-05-03` | `2020-12-15` |
| `000995.SZ` | `皇台酒业` | `2020-12-16` | `2022-04-28` |
| `000995.SZ` | `*ST皇台` | `2022-04-29` | `2023-08-17` |
| `000995.SZ` | `皇台酒业` | `2023-08-18` | 空 |

这个口径是开发门禁：NC-3 必须实现 `latest_announcement_timeline_v3`，不得回退成 raw distinct，也不得把 unresolved conflict 临时降级为 WARN。

## 6. 资产设计

### 6.1 `raw_tushare_namechange`

| 项目 | 口径 |
|---|---|
| asset key | `raw_tushare_namechange` |
| group | `basic` |
| layer tag | `raw` |
| data domain tag | `basic_data` |
| source system | `TUSHARE` |
| source api | `namechange` |
| source doc | `docs/sources/tushare/股票数据/基础数据/0100_股票曾用名.md` |
| data contract | `source_mirror_deduplicated_full_snapshot` |
| partitions | 无 |
| path | `/Volumes/datasource/data_lake/raw/tushare/namechange/full/part-000.parquet` |

raw 字段契约：

| 字段 | 类型 | 说明 |
|---|---|---|
| `ts_code` | `VARCHAR` | 股票代码 |
| `name` | `VARCHAR` | 证券名称 |
| `start_date` | `VARCHAR` | 名称生效开始日期，Tushare 原始 `YYYYMMDD` 字符串 |
| `end_date` | `VARCHAR` | 名称生效结束日期，Tushare 原始 `YYYYMMDD` 字符串或空 |
| `ann_date` | `VARCHAR` | 公告日期，Tushare 原始 `YYYYMMDD` 字符串或空 |
| `change_reason` | `VARCHAR` | 变更原因 |

raw 写入规则：

1. 调用 `fetch_tushare_namechange_announcement_windows_to_raw(...)`；不得调用 generic full-file helper。
2. 参数不传 `ts_code`；reader 内部以 `1990-01-01` 到上海时区当日的公告日期闭区间递归二分。
3. 每个 source 请求显式传 `start_date/end_date`、`limit=6000`、`offset=0`；窗口恰好满页必须二分，单日满页直接失败。
4. 写入前对所有字段完全一致的行做 distinct。
5. 如果 distinct 后 0 行，直接失败。
6. 使用 `.tmp` + `os.replace` 原子替换。
7. 不写旧湖路径、source method、manifest 信息到 parquet 字段。

raw materialization metadata：

| metadata | 说明 |
|---|---|
| `dagster/uri` | raw parquet 路径 |
| `dagster/row_count` | distinct 后行数 |
| `goldenshare/observed_columns` | 本次输出字段 |
| `source_method` | `tushare_api` |
| `source_query_strategy` | `announcement_date_adaptive_bisection` |
| `api_name` | `namechange` |
| `announcement_start_date/end_date` | 本次完整 source 覆盖范围 |
| `source_query_count/accepted_window_count/split_window_count` | source 读取规模和切窗过程摘要 |
| `max_accepted_window_row_count` | 最大叶子窗口行数，必须小于 `limit` |
| `fields` | 显式请求字段 |
| `source_row_count` | 去重前行数 |
| `duplicate_removed_count` | 完全重复行去重数量 |

### 6.2 `silver_namechange`

| 项目 | 口径 |
|---|---|
| asset key | `silver_namechange` |
| group | `basic` |
| layer tag | `silver` |
| data domain tag | `basic_data` |
| source system | `DERIVED` |
| data contract | `standardized_namechange_event_timeline_full_snapshot` |
| partitions | 无 |
| deps | `raw_tushare_namechange`、`silver_stock_basic` |
| path | `/Volumes/datasource/data_lake/silver/basic/namechange/full/part-000.parquet` |

silver 字段契约：

| 字段 | 类型 | 说明 |
|---|---|---|
| `ts_code` | `VARCHAR` | 股票代码 |
| `name` | `VARCHAR` | 变更后证券简称，即该区间内实际使用的名称 |
| `start_date` | `DATE` | 名称变更生效日 |
| `end_date` | `DATE` | 该名称使用结束日；当前仍有效时为空 |
| `ann_date` | `DATE` | 选中这段名称变更事实的公告日期；源站为空时保留为空 |
| `change_reason` | `VARCHAR` | 变更原因 |

silver 转换规则：

1. 从 raw 读取。
2. `start_date/end_date/ann_date` 从 `YYYYMMDD` 字符串标准化为 DATE。
3. `ts_code/name/start_date/change_reason` 必须非空。
4. 只保留 `silver_stock_basic` 中当前仍上市股票；退市股票不进入 `silver_namechange`。
5. 不保留旧湖-only 记录，不做旧湖 correction。
6. 使用 `latest_announcement_timeline_v3` 生成标准名称时间线。
7. 同一 `ts_code + start_date` 下，选择 `ann_date` 最新的公告版本；`ann_date` 为空视为低优先级。
8. 同一 `ts_code + start_date + ann_date` 下仍有多行时，优先选择带 `end_date` 的版本；若同名候选只存在原因或结束日差异，则按 v2 同名裁决规则处理；若不同名候选只有 `name` 不同且其它字段完全一致，则按 `silver_stock_basic.name` 对齐选择；如果仍无法唯一确定，直接失败。
9. 按 `ts_code/start_date` 生成时间线，连续相同 `name` 的噪声记录合并为一个区间。
10. 如果当前段源 `end_date` 为空，或源 `end_date >= 下一段 start_date`，则用 `下一段 start_date - 1 day` 闭合当前段，避免 overlap。
11. 如果当前段源 `end_date < 下一段 start_date`，保留源 `end_date`，允许中间存在 gap。
12. 最后一段如果源 `end_date` 为空则保持 open；如果源端给了 `end_date`，则保留该结束日。
13. silver 最终输出必须是可解释的标准名称区间：同一股票同一时间点最多命中一个名称区间；同一股票最多只有一个当前 open interval。
14. 如果标准化归并后仍存在无法解释的多 open / overlap 矛盾，直接失败，不允许静默 WARN。
15. 完全重复行理论上已在 raw 去掉；silver 仍检查不存在完全重复行。

silver materialization metadata：

| metadata | 说明 |
|---|---|
| `dagster/uri` | silver parquet 路径 |
| `dagster/row_count` | silver 行数 |
| `goldenshare/observed_columns` | 本次输出字段 |
| `source_row_count` | 过滤当前上市股票后的 raw 行数 |
| `raw_source_row_count` | 过滤前 raw 行数 |
| `current_listed_stock_count` | 当前上市股票数量，来自 `silver_stock_basic` |
| `filtered_delisted_row_count` | 因退市股票过滤掉的 raw 行数 |
| `duplicate_removed_count` | silver 端发现并移除的完全重复行数，正常应为 0 |
| `open_interval_count` | `end_date IS NULL` 行数，仅观测 |
| `canonicalization_rule_version` | 固定为 `latest_announcement_timeline_v3` |
| `manual_selected_event_resolved_count` | v3 规则中按人工审计 `selected=Y` 精确登记的 case-by-case 裁决数量 |
| `diff_name_same_start_stock_basic_resolved_count` | v3 规则中“除名称外完全一致”的不同名称冲突按 `silver_stock_basic.name` 自动裁决的数量 |
| `same_name_same_end_reason_resolved_count` | v3 规则中同名同区间原因差异被自动裁决的数量 |
| `same_name_diff_end_resolved_count` | v3 规则中同名不同结束日被自动裁决的数量 |
| `unresolved_interval_conflict_count` | 归并后仍无法解释的区间矛盾数量；必须为 0 |
| `adjacent_gap_count` | 相邻名称区间之间存在日期 gap 的数量；只观测，不阻断 |
| `known_adjacent_gap_count` | 已登记的相邻 gap 数量，当前应为 1 |
| `unknown_adjacent_gap_count` | 未登记的相邻 gap 数量；当前应为 0，若大于 0 必须失败或停止开发确认 |
| `adjacent_gap_sample` | gap 样本，例如 `000022.SZ` 的 `2018-12-25` 空档 |

## 7. 路径函数

新增路径函数：

```python
def raw_namechange_path(root: Path) -> Path:
    return lake_path(root, RAW, "tushare", "namechange", "full", "part-000.parquet")

def silver_namechange_path(root: Path) -> Path:
    return lake_path(root, SILVER, "basic", "namechange", "full", "part-000.parquet")
```

路径约束：

- 不使用 `raw_tushare`。
- 不使用 `manifest`。
- 不使用旧湖路径。
- 不新增 `reference` 层级。

## 8. Schema Contract

在 `lake_console/orchestrator/src/orchestrator/defs/run_contracts/asset_column_schemas.py` 新增：

```text
RAW_TUSHARE_NAMECHANGE_SCHEMA
SILVER_NAMECHANGE_SCHEMA
```

并确保：

- asset definition metadata 通过 `build_asset_definition_metadata(..., column_schema=...)` 注册 `dagster/column_schema`。
- materialization metadata 不承载稳定字段契约。
- runtime 字段列表只使用 `observed_columns`。
- 新增 schema 后，同步更新 asset governance 测试中的资产清单。

## 9. 中文名映射

必须在 `defs/catalog/name_mapping.py` 登记：

| dataset_id | 中文名 |
|---|---|
| `namechange` | 股票曾用名 |

中文名只进入 definition metadata，不进入 asset tag。

## 10. Checks 设计

### 10.1 raw blocking checks

| check | 功能 | 失败含义 |
|---|---|---|
| `raw_namechange_file_exists` | raw parquet 必须存在 | raw 没有成功生成 |
| `raw_namechange_row_count_positive` | raw 行数必须大于 0 | Tushare 全量快照为空，不允许静默写入 |
| `raw_namechange_required_columns` | 字段必须等于 raw contract | 源字段缺失或写入列错误 |
| `raw_namechange_schema_matches_tushare_contract` | parquet 类型必须匹配 raw schema | 类型漂移或写入 helper 配置错误 |
| `raw_namechange_required_fields_non_null` | `ts_code/name/start_date/change_reason` 非空 | 源关键字段不可用 |
| `raw_namechange_date_string_format_valid` | 日期字符串必须为 `YYYYMMDD` 或空 | raw 日期格式不符合 Tushare 契约 |
| `raw_namechange_exact_duplicate_absent` | 所有字段完全一致的重复行必须不存在 | raw 去重逻辑失效 |

### 10.2 raw WARN checks

| check | 功能 | 说明 |
|---|---|---|
| `raw_namechange_multi_open_interval_observed` | 统计每个股票 `end_date IS NULL` 多行情况 | raw 是源镜像快照，只观测源站现实，不阻断 |
| `raw_namechange_overlap_interval_observed` | 统计按 raw 原始 distinct 行直接判断的区间重叠情况 | 用于 NC-0 / NC-3 归并设计，不阻断 raw 入湖 |
| `raw_namechange_reason_distribution_observed` | 输出 `change_reason` 分布 | 用于观测 ST / *ST / 改名 / 终止上市等结构 |

### 10.3 silver blocking checks

| check | 功能 | 失败含义 |
|---|---|---|
| `silver_namechange_file_exists` | silver parquet 必须存在 | silver 没有成功生成 |
| `silver_namechange_row_count_positive` | silver 行数必须大于 0 | 标准表为空 |
| `silver_namechange_required_columns` | 字段必须等于 silver contract | 输出列错误 |
| `silver_namechange_schema_matches_contract` | 类型必须匹配 silver schema | 日期未标准化或类型漂移 |
| `silver_namechange_required_fields_non_null` | `ts_code/name/start_date/change_reason` 非空 | 标准事实关键字段不可用 |
| `silver_namechange_date_order_valid` | `end_date` 非空时必须 `end_date >= start_date` | 区间日期非法 |
| `silver_namechange_exact_duplicate_absent` | 所有字段完全一致的重复行必须不存在 | 标准表重复 |
| `silver_namechange_current_open_interval_unique` | 同一股票最多只能有一个 `end_date IS NULL` 当前名称区间 | 标准表无法唯一判断当前名称 |
| `silver_namechange_interval_overlap_absent` | 同一股票任意两个名称区间不能重叠 | 标准表无法唯一判断历史日期名称 |
| `silver_namechange_unknown_adjacent_gap_absent` | 未登记的相邻区间 gap 必须为 0；当前仅允许已登记的 `000022.SZ` gap | 出现新的未审计 gap，需要先回到方案文档登记 |

### 10.4 silver WARN checks

第一版不把区间矛盾放到 silver WARN。原因很简单：`silver_namechange` 是标准事实表，如果同一股票同一天能命中多个名称，后续所有依赖都会被污染。

允许保留的 WARN 只做结构观测，例如 `change_reason` 分布、open interval 行数分布、相邻区间 gap 样本；但这些 WARN 不能替代 blocking 区间一致性检查。

所有 checks 必须：

- 使用 `@dg.asset_check(..., blocking=True/False)`。
- 使用 `build_check_metadata(...)`。
- 写清 `CheckScope`。
- 输出数量、样本、路径，不裸写旧 metadata key。

## 11. Job 设计

新增：

```text
lake_console/orchestrator/src/orchestrator/defs/jobs/namechange_update.py
```

jobs：

```text
raw_namechange_update_job
silver_namechange_update_job
```

selection：

```text
raw_namechange_update_job:
  raw_tushare_namechange
  checks_for_assets(raw_tushare_namechange)

silver_namechange_update_job:
  silver_namechange
  checks_for_assets(silver_namechange)
```

职责：

- 只作为对应 layer 的流程入口。
- 不调用 Tushare。
- 不写 DuckDB SQL。
- 不拼路径。
- 不做质量判断。
- 不把 raw 和 silver 混在同一个 active job 内。

UI description：

```text
raw_namechange_update_job: 更新股票曾用名 raw full snapshot。
silver_namechange_update_job: raw 曾用名 ready 后，更新股票曾用名 silver full snapshot。
```

## 12. Sensor / Automation 设计

P2A 后拆为 `raw_namechange_update_job_sensor` 与 `silver_namechange_update_job_sensor`。两者都不自己判断交易日历，不注册 partition。

触发关系：

```text
stock_current_trade_day_sensor
  -> 注册 cn_a_stock_current_trade_days[trade_date]
  -> raw_namechange_update_job_sensor 读取最新已注册 current trade day
  -> 触发 raw_namechange_update_job
  -> raw_tushare_namechange event/check ready
  -> silver_namechange_update_job_sensor 等待 stock_basic_ready_for_trade_date
  -> 触发 silver_namechange_update_job
```

这样设计的原因：

1. `namechange` 是基础数据 full snapshot，不适合按 `trade_date` 分区存储。
2. 但业务上希望日更，所以可以复用 `stock_current_trade_day_sensor` 注册出来的“今天是股票交易日”信号。
3. `stock_current_trade_day_sensor` 仍然只负责注册 `cn_a_stock_current_trade_days`，不触发数据生产；具体生产由 namechange 自己的 raw/silver sensors 负责。
4. `raw_namechange_update_job` 与 `silver_namechange_update_job` 仍是 unpartitioned job，因为它们每次覆盖 full snapshot 文件。

P2A 后的 namechange sensor 口径：

| 项目 | 口径 |
|---|---|
| 文件 | `defs/sensors/stock_namechange_sensor.py` |
| raw target job | `raw_namechange_update_job` |
| silver target job | `silver_namechange_update_job` |
| default status | `STOPPED` |
| minimum interval | 600 秒 |
| 触发来源 | `cn_a_stock_current_trade_days` 最新已注册且不晚于上海当天的 key |
| 触发窗口 | 09:30 后早盘阶段；17:00 后晚盘阶段 |
| raw run key | `raw_namechange_update:{trade_date}:{morning|evening}` |
| silver run key | `silver_namechange_update:{trade_date}:{morning|evening}` |
| partition_key | 无，namechange full snapshot jobs 不是 partitioned job |
| run config | 第一版无 |
| raw 重复触发 | 同一 `trade_date + stage` 只提交一次；失败后人工 retry，不做无限自动重试 |
| silver 门禁 | `raw_tushare_namechange` event/check ready + `stock_basic_ready_for_trade_date(trade_date)`；若 silver 已 ready，还必须确认 silver storage id 不早于 raw 与 stock_basic 最新 storage id |
| cursor | 只记录观测信息：target date、stage、是否已注册、是否已提交、skip reason |

禁止：

- namechange sensors 不调用 Tushare。
- namechange sensors 不读写 parquet。
- namechange sensors 不做区间审计。
- namechange sensors 不注册 dynamic partitions。
- 不新增 declarative automation；full snapshot 基础资产第一版走普通 sensor。

后续如果要把多个 basic full snapshot 合并成基础资产日更编排，必须另起设计；不能把其它数据集顺手塞进 namechange sensors。

## 13. Run Config

第一版不暴露运营 run config。

`raw_namechange_update_job` 与 `silver_namechange_update_job` 固定执行 full snapshot：

- 不要求运营填写日期。
- 不要求运营填写 `ts_code`。
- 不暴露 Tushare `start_date/end_date`。
- 不暴露分页参数。

如后续需要单股票 repair，应单独设计 typed config，不在第一版混入。

## 14. 历史迁移与旧湖边界

本次不使用 bootstrap。

| 模板检查项 | 本方案结论 |
|---|---|
| 是否需要旧湖迁移 | 不需要 |
| 旧湖路径是否进入 parquet | 不允许 |
| 是否新增 bootstrap spec | 不新增 |
| 是否更新 legacy links | 不需要，除非后续决定记录“未采用旧湖 bootstrap”的调研结论 |
| 是否清理旧湖或旧 manifest | 不处理 |

旧湖只作为调研依据：

- 证明该数据集历史形态是 full snapshot。
- 识别旧湖日期类型与 raw 正式契约不一致。
- 识别旧湖已落后于线上。

## 15. 开发文件清单

预计新增 / 修改文件：

| 文件 | 动作 |
|---|---|
| `defs/paths.py` | 新增 `raw_namechange_path`、`silver_namechange_path` |
| `defs/run_contracts/asset_column_schemas.py` | 新增 raw/silver schema |
| `defs/catalog/name_mapping.py` | 新增 `namechange -> 股票曾用名` |
| `defs/duckdb_sql.py` | 新增字段常量 |
| `defs/namechange_timeline.py` | 新增 `latest_announcement_timeline_v1` 纯转换规则 |
| `defs/tushare_api_io.py` | 新增 full snapshot exact distinct 写入 helper，不改变默认 full-file helper 语义 |
| `defs/assets/namechange.py` | 新增 raw/silver assets |
| `defs/checks/namechange_checks.py` | 新增 raw/silver checks |
| `defs/checks/__init__.py` | 如当前自动发现需要，加入导出 |
| `defs/jobs/namechange_update.py` | 定义 `raw_namechange_update_job` 与 `silver_namechange_update_job` |
| `defs/jobs/__init__.py` | 如当前自动发现需要，加入导出 |
| `defs/sensors/stock_namechange_sensor.py` | 定义 `raw_namechange_update_job_sensor` 与 `silver_namechange_update_job_sensor` |
| `defs/sensors/__init__.py` | 如当前自动发现需要，加入导出 |
| `tests/test_asset_governance_contracts.py` | 新增 asset schema contract 断言 |
| `tests/test_run_contract_static_gates.py` | 确认新增 asset/check/job 不破坏静态门禁 |
| `tests/test_namechange_contracts.py` | 新增 exact distinct 与名称时间线规则单测 |
| `docs/architecture/dagster-asset-job-topology.html` | 开发完成后同步 active asset/job/check 状态 |

不应修改：

- 旧湖文件。
- 旧 manifest 文件。
- 下游服务代码。
- ClickHouse。
- stock daily / adj factor / index daily 现有链路。

## 16. 开发切片 Roadmap

### NC-0：开发前源数据区间审计

状态：已完成。2026-05-31 审计确认 `latest_announcement_timeline_v3` 必须结合“当前上市过滤、同名原因归一、同名结束日裁决、stock basic 名称对齐和精确人工 override”才能继续收敛；未被规则覆盖的冲突必须继续阻断并由人工确认。

目标：

- 使用最新 Tushare full snapshot distinct 数据重新审计多 open、同 start 变体、区间重叠。
- 输出统计和样本。
- 明确 silver 区间归并规则是否足以把当前源数据标准化为唯一名称区间表。

禁止：

- 不写代码。
- 不把审计结果拍脑袋降级为 WARN。
- 不用旧湖数据修补 Tushare。

验收：

- 已完成 NC-0 只读审计，并将关键统计、失败策略和最终规则写入本方案。
- 已确认不能使用 `source_distinct_only`、`prefer_closed_same_event` 或旧 `timeline_candidate` 作为 silver 规则。
- 已确认 NC-3 必须实现 `latest_announcement_timeline_v3`，并让 unresolved conflict blocking checks 作为正式门禁。

### NC-1：契约与路径

状态：已完成。

目标：

- 新增路径函数。
- 新增 raw/silver schema contract。
- 新增中文名映射。
- 新增 DuckDB 字段常量和类型常量。

禁止：

- 不新增 asset。
- 不新增 job。
- 不请求 Tushare。
- 不写数据湖。

验收：

- `test_asset_governance_contracts` 中 schema 派生常量可通过。
- `git diff --check` 通过。

### NC-2：raw asset 与 raw checks

状态：已完成。

目标：

- 实现 `raw_tushare_namechange`。
- 接入 Tushare full snapshot 拉取。
- 实现 raw exact distinct。
- 实现 raw blocking/WARN checks。

禁止：

- 不生成 silver。
- 不新增 sensor。
- 不处理旧 manifest。

验收：

- 单次运行 raw 后，raw 文件字段为 Tushare raw contract。
- metadata 可见 `source_row_count`、`duplicate_removed_count`。
- raw blocking checks 通过。

### NC-3：silver asset 与 silver checks

状态：已完成。

目标：

- 实现 `silver_namechange`。
- 日期字段标准化为 DATE。
- 实现 `latest_announcement_timeline_v3` 区间归并和 blocking checks。

禁止：

- 只保留当前上市股票，不保留退市股票。
- 不保留旧湖-only 记录。
- 不静默保留无法解释的源站区间矛盾。
- 不新增下游 consumer。

验收：

- silver 文件字段类型符合 schema contract。
- `end_date < start_date` 为 0。
- 完全重复行为 0。
- `canonicalization_rule_version=latest_announcement_timeline_v3`。
- 归并后 `unresolved_interval_conflict_count=0`。
- `silver_namechange_current_open_interval_unique` 通过。
- `silver_namechange_interval_overlap_absent` 通过。
- `silver_namechange_unknown_adjacent_gap_absent` 通过。
- 已登记的 `000022.SZ` 相邻 gap 只作为 metadata / WARN 样本观测，不作为阻断。

### NC-4：job 与 UI 入口

状态：已完成。

目标：

- 新增 `raw_namechange_update_job` 与 `silver_namechange_update_job`。
- raw job selection 只包含 `raw_tushare_namechange` 和 raw checks。
- silver job selection 只包含 `silver_namechange` 和 silver checks。

禁止：

- job 文件不得包含 Tushare、DuckDB、路径拼接或质量逻辑。
- 不把 raw 和 silver 保留在同一个 active job 中。

验收：

- UI 能看到 job。
- job 描述为中文。
- raw run 只 materialize `raw_tushare_namechange`。
- silver run 只 materialize `silver_namechange`。

### NC-5：日更 sensor

状态：已完成。

目标：

- 新增 `raw_namechange_update_job_sensor` 与 `silver_namechange_update_job_sensor`。
- raw sensor 读取 `cn_a_stock_current_trade_days` 最新已注册交易日。
- raw sensor 触发 unpartitioned `raw_namechange_update_job`。
- silver sensor 等 `raw_tushare_namechange_ready_for_trade_date(target)` 与 `stock_basic_ready_for_trade_date(target)` 后，触发 unpartitioned `silver_namechange_update_job`。

禁止：

- 不在 sensor 中调用 Tushare。
- 不在 sensor 中做 DuckDB 区间审计。
- 不新增 partitioned namechange asset。

验收：

- sensor 默认 `STOPPED`。
- raw preview 只能看到 `raw_namechange_update_job` run request，不能触发其它 job。
- silver preview 只能看到 `silver_namechange_update_job` run request，不能触发其它 job。
- 同一交易日不会重复提交。

### NC-6：正式验收与文档同步

状态：代码侧 topology 文档已同步；正式 Dagster instance / UI 验收仍需用户单独批准后执行。

目标：

- 使用正式 Dagster instance 运行一次 `raw_namechange_update_job`。
- 在 raw event/check ready 后运行一次 `silver_namechange_update_job`。
- 验证 raw/silver materialization metadata。
- 验证 checks。
- 短窗口验证两个 namechange sensors，确认分别只提交对应 raw/silver job。
- 更新 topology 文档。

需要用户批准后才能执行：

```text
uv run dg check defs
UI 或正式 instance 中依次运行 raw_namechange_update_job、silver_namechange_update_job
```

禁止：

- 不做历史 backfill。
- 不改旧消费者。

## 17. 验收计划

### 静态验证

```text
uv run python -m unittest tests.test_metadata_contracts
uv run python -m unittest tests.test_asset_governance_contracts
uv run python -m unittest tests.test_run_contract_static_gates
uv run python -m unittest tests.test_namechange_contracts
python3 scripts/check_docs_integrity.py
git diff --check
git status --short
```

### Dagster definitions 验证

必须单独获得用户批准后执行：

```text
cd /Users/congming/github/goldenshare/lake_console/orchestrator
uv run dg check defs
```

### UI 单次运行验收

必须单独获得用户批准后执行：

1. 在 Dagster UI 运行 `raw_namechange_update_job`。
2. 确认只执行 `raw_tushare_namechange` 和 raw checks。
3. 在 raw event/check ready 后运行 `silver_namechange_update_job`。
4. 确认只执行 `silver_namechange` 和 silver checks。
5. 确认 raw materialization metadata 包含：
   - `dagster/uri`
   - `dagster/row_count`
   - `goldenshare/observed_columns`
   - `source_row_count`
   - `duplicate_removed_count`
   - `source_query_strategy`
   - `announcement_start_date` / `announcement_end_date`
   - `source_query_count`
   - `accepted_window_count` / `split_window_count`
   - `max_accepted_window_row_count`
6. 确认 silver materialization metadata 包含：
   - `dagster/uri`
   - `dagster/row_count`
   - `goldenshare/observed_columns`
   - `open_interval_count`
   - `canonicalization_rule_version`
   - `unresolved_interval_conflict_count`
7. 确认 blocking checks 全部通过。
8. 确认 raw WARN checks 可见且有统计 metadata。
9. 确认 `raw_namechange_update_job_sensor` 与 `silver_namechange_update_job_sensor` 默认 STOPPED；如短暂开启验证，必须只触发对应 layer job。

## 18. 接入模板 Checklist 对照

| 类别 | 模板要求 | 本方案结论 |
|---|---|---|
| 依据 | 当前代码、旧湖数据、本地 Tushare 文档、tushareMCP 实测都已核验 | 已完成 |
| 层级 | raw/silver/gold 分类清楚，没有 support/reference 新层级 | raw + silver |
| Asset tags | 使用 `build_asset_tags(...)`，layer/data_domain 为登记枚举 | `raw/silver` + `basic_data` |
| 中文名 | `dataset_id` 登记中文名 | 需新增 `namechange -> 股票曾用名` |
| 命名 | asset/job/check 文件名单一职责 | `namechange.py`、`namechange_checks.py`、`namechange_update.py`；active jobs 为 `raw_namechange_update_job` / `silver_namechange_update_job` |
| UI 文案 | description 中文简明 | 已列入开发要求 |
| 路径 | 新路径位于 data_lake raw/silver；path_template 由真实路径函数生成 | 已明确 |
| Definition metadata | 使用 `build_asset_definition_metadata(...)` | 已明确 |
| Materialization metadata | 使用 `build_materialization_metadata(...)` 和 `observed_columns` | 已明确 |
| 字段 | raw 源镜像，silver 日期标准化 | 已明确 |
| Tushare | 参数、字段、分页、空结果、样本行数已实测 | 已完成基础实测；开发前可补一次全量页数实测 |
| 请求范围 | 对象池/分页量/耗时评估 | full snapshot，不需要对象池；首次运行记录 `source_query_count`、`accepted_window_count`、`split_window_count` 和 `max_accepted_window_row_count` |
| checks | blocking/WARN 分清，metadata 有数量和样本 | 已列清 |
| deps | asset deps 表达真实输入 | `silver_namechange` 依赖 `raw_tushare_namechange` |
| job | job 只做 selection | raw/silver 分层 job 已明确 |
| run config | typed config / 业务动作字段 | 第一版无 run config |
| sensor | ready/run_key/cursor/tick 限制 | `raw_namechange_update_job_sensor` 跟随 `cn_a_stock_current_trade_days` 当前交易日信号，并按 `morning/evening` 两阶段提交；`silver_namechange_update_job_sensor` 等 raw namechange 与 stock_basic final ready，且 silver 必须跟上最新 upstream storage id |
| run tags | 不新增项目自定义 run tags | 已明确 |
| bootstrap | 如需旧湖迁移需 spec 和 legacy links | 不适用，不走 bootstrap |
| 验收 | 单次 UI run、checks、metadata、失败恢复 | 已列清 |
| 静态门禁 | unittest、文档检查、diff check | 已列清 |
| 文档同步 | topology / 相关设计同步 | NC-5 完成后同步 |

## 19. 风险与注意事项

1. Tushare 源站会返回完全重复行，raw 层必须 exact distinct，否则 row count 和 checks 会被污染。
2. `start_date/end_date` 请求参数是公告日期范围，不是名称生效日期范围；第一版不要暴露给运营。
3. 旧湖日期列是 DATE，但 raw 正式契约是 `YYYYMMDD` 字符串，不能按旧湖类型设计 raw schema。
4. `end_date IS NULL` 多行和区间重叠是源数据现实：raw 层只观测，silver 层必须归并；归并后仍无法解释的矛盾必须阻断。
5. full snapshot 并发运行可能造成重复请求和后写覆盖前写；`raw_namechange_update_job_sensor` 必须用 run key 和 cursor 避免同一交易日重复提交。
6. 本方案不处理旧 manifest 或其它消费者；如果未来有人需要消费 `namechange`，应依赖 `silver_namechange` 另起设计。

## 20. 2026-07-14 Source Drift 恢复 LLD

当前 Tushare source 可以在日常 raw 写入后补充或修订历史名称区间；2026-07-14 进一步确认，无筛选全量响应本身可能遗漏仍可被公告日期窗口取到的记录。因此，发现 silver 的未知相邻空档时，必须先实时核验 Tushare，再决定是按公告日期完整窗口重建 raw，还是另行设计人工校正机制。

`000040.SZ`、`000761.SZ`、`600381.SH` 的本次问题经实时 Tushare 核验后均属于 source drift：当前源站已有对应记录，本地 raw 缺失。正式恢复方案见 [Dagster 股票曾用名 Source Drift 恢复 LLD](dagster-namechange-source-drift-recovery-low-level-design.md)。

该专项明确：

1. 本次不新增人工校正 seed；raw 必须继续作为 Tushare source mirror。
2. namechange 专用公告日期自适应 reader 已完成代码与本地测试；`raw_namechange_update_job` 已于 2026-07-14 成功完成新的 R1，raw 三项 blocking checks 全绿，三条 source anchor 均已写入；`silver_namechange_update_job` 随后完成 R2，silver 三项 blocking checks 全绿，未知相邻空档和区间重叠均为零；`stock_identity_map_update_job` 已完成 R3，身份映射对 `2026-07-13` 为 ready。R4 随后完成：经管理员明确批准一次性直接注册该日分钟线 silver 分区，`stock_mins_silver_update_job`、`stock_mins_qfq_daily_update_job` 与 `stock_mins_qfq_factor_repair_job` 均成功。factor repair 修复了 33 个代码自 `2014-01-02` 起的 qfq 历史，并标记需要独立的 MACD/KDJ historical reconciliation；该 reconciliation 不属于本次 namechange 恢复。完整审计见 [Source Drift 恢复 LLD](dagster-namechange-source-drift-recovery-low-level-design.md)。
3. `unknown_adjacent_gap_count` 不能靠 `KNOWN_NAMECHANGE_ADJACENT_GAP_KEYS` 绕过。
4. 只有 Tushare 实时核验仍缺失、且人工证据充分时，才可以另起方案设计 silver-only 校正 seed。
