# Dagster 股票曾用名 Source Drift 恢复 LLD

状态：R0、C0、新的 R1、R2、R3 与 R4 已完成。旧 R1 的 raw contract checks 虽然全绿，但 source semantic gate 失败；新的 R1 已使用公告日期自适应窗口 reader 成功重建 raw 并通过三条 source anchor 语义验收，R2 已重建 silver 名称时间线且未知相邻空档为零，R3 已重建身份映射并通过 `2026-07-13` readiness，R4 已补齐该日 silver minutes、gold qfq 和 factor repair。

更新时间：2026-07-14

## 1. 一句话结论

`silver_namechange` 的失败不是时间线算法需要打补丁，也不是需要人工伪造历史数据。

当前 Tushare `namechange` 已返回本地 raw 曾缺少的三条历史名称记录，但已证实 **无筛选的全量查询会漏掉这三条记录**。因此不能再把“无条件 `limit/offset` 翻页”称为完整 source snapshot。新的 raw、silver 名称时间线、身份映射及 `2026-07-13` 分钟线 silver / qfq 链路均已恢复；MACD/KDJ 历史 reconciliation 仍是独立后续事项。

## 2. 目标、边界与硬约束

### 2.1 目标

1. 让 raw 镜像重新与当前 Tushare `namechange` 的完整公告日期窗口并集一致。
2. 让 silver 名称时间线不再出现未知相邻日期空档。
3. 让身份映射满足 `2026-07-13` 的 freshness 门禁，从而解除股票分钟线 silver 分区注册的阻断。
4. 恢复中断的 `2026-07-13` 分钟线 silver 与 qfq 生产链路。

### 2.2 本轮不做

1. 不修改共享 `_fetch_all_pages(...)`、通用 full-file helper、SQL、asset/check/job/sensor 定义、动态分区规则或 cursor。唯一允许的代码改动是 namechange 专用 source reader、其 raw asset 接线和测试。
2. 不写 prod 数据库，不改 index daily，不改 stock daily，不改 raw/silver 分钟线的既有文件。
3. 不直接编辑任何 Parquet，不直接 SQL 修改 Dagster PostgreSQL。正常生产仍由 `stock_mins_silver_trade_day_sensor` 注册分区；但 2026-07-14 管理员明确批准后，R4 仅对 `cn_a_stock_mins_silver_trade_days=2026-07-13` 执行了一次受 preflight 约束的直接注册。该一次性执行例外不改变 sensor 或动态分区的长期口径。
4. 不新增或启用人工校正 seed。
5. 不执行 `gold_stk_mins_qfq_macd_kdj_repair`。此前 `2026-07-10` qfq 历史修复后的 MACD/KDJ reconciliation 仍是独立专项，不能借本次顺手执行。

### 2.3 既有正式链路

```text
Tushare namechange announcement-date complete snapshot
  -> raw_namechange_update_job
  -> raw_tushare_namechange + raw checks
  -> silver_namechange_update_job
  -> silver_namechange + silver checks
  -> stock_identity_map_update_job
  -> silver_stock_identity_map + checks
  -> stock_mins_silver_trade_day_sensor（正常生产在既有窗口内注册；本次 R4 经明确批准直接注册 2026-07-13）
  -> stock_mins_silver_update_job[2026-07-13]
  -> stock_mins_qfq_daily_update_job[2026-07-13]
  -> stock_mins_qfq_factor_repair_job[2026-07-13]（仅按既有逻辑判断是否需要历史重算）
```

任何一步 materialized 但 blocking checks 未全绿，立即停止；不让 sensor 自动重跑覆盖失败状态。

## 3. 已核验事实

### 3.1 证据来源和优先级

本次逐项核验了：

1. 本机 raw / silver Parquet 当前行。
2. 当前代码的 full-snapshot、时间线、checks、readiness、job 和 sensor 实现。
3. 本地 Tushare `namechange` 文档：`docs/sources/tushare/股票数据/基础数据/0100_股票曾用名.md`；其中明确 `start_date/end_date` 是公告日期范围。
4. `tushareMcp.namechange` 对三个代码的实时显式字段请求。

用户截图用于定位 `000040.SZ` 的历史名称问题；实际执行的精确日期和名称以当前 Tushare 实测结果为准。截图中部分日期与当前源站不一致，不能直接作为写入事实。

### 3.2 R1 前源站记录与本地缺口

| 代码 | 当前 raw 状态 | 当前 Tushare 实测记录 | 恢复后动作 |
|---|---|---|---|
| `000040.SZ` | R1 前缺失；R1 后 raw 已恢复 | `ST鸿基`，`2004-05-10` 至 `2005-05-25`，公告日 `2004-04-30`，`撤消*ST并实行ST` | R1 审计确认 raw 中恰好一行。R2 后仍不在 silver：它不在当前 `silver_stock_basic` 股票池，符合既有“只生成当前股票池名称时间线”的实现。 |
| `000761.SZ` | R1 前缺失；R1 后已恢复 | `本钢板材`，`2004-05-10` 至 `2006-03-14`，公告日 `2004-04-30`，`撤销ST` | R1 审计确认 raw 中恰好一行；R2 后 silver 有 5 条该代码时间线，连接 `ST板材` 与 `G本钢`。 |
| `600381.SH` | R1 前缺失；R1 后已恢复 | `青海春天`，`2015-06-12` 至 `2016-06-28`，公告日 `2015-04-24`，`其他` | R1 审计确认 raw 中恰好一行；R2 后 silver 有 15 条该代码时间线，连接 `贤成矿业` 与 `ST春天`。 |
| `002640.SZ` | raw 已有 `跨境通`，silver 缺失 | `跨境通`，`2015-06-12` 至 `2021-05-06` | 不做人工补数；重建 silver 后应自然纳入。 |

在内存中把前三条当前源站记录与最新 raw 合并后，时间线无 overlap、无多 open、无 unresolved conflict，且 `unknown_adjacent_gap_count=0`。

### 3.3 根因

1. 旧 `raw_tushare_namechange` 使用无筛选查询加 `offset=0/6000/12000`。2026-07-14 的同账号复测稳定返回 14,135 行、exact distinct 后 14,132 行；三条 anchor 都不在其中。
2. 用同一接口的 `start_date/end_date` 公告日期窗口读取 1990-2026 年，返回 14,135 行且 exact distinct 后仍为 14,135 行。它包含无筛选结果的全部 14,132 行，并额外包含恰好三条 anchor。问题是 Tushare 无筛选响应的完整性，不是本地 offset 提前停止。
3. 进一步实测递归二分公告日期窗口：5 次请求中只有 3 个叶子窗口被接受，且每个叶子窗口少于 6,000 行；并集为 14,135 行、无重复、三条 anchor 齐全。因此可以避免任何 offset 翻页。
4. `silver_namechange` 又落后于当前 raw，所以即使 raw 已有的 `002640.SZ / 跨境通` 也没有进入 silver。
5. `silver_namechange_interval_domain_check` 因未知相邻空档失败，导致 `silver_stock_identity_map` 无法满足 `2026-07-13` freshness，继而阻断 `stock_mins_silver_trade_day_sensor` 注册该日分区。

## 4. 为什么本次不需要校正 seed

**校正 seed** 是一个受版本控制的小型事实表。它只用于一个严格场景：源站经实时核验仍然缺少某段历史记录，但已有可靠人工证据可以确认该记录的名称和生效区间。

它不是 raw 的补丁，也不是临时脚本：

```text
raw：始终只镜像源站，不写人工行
silver：未来如确有必要，才把校正 seed 与 raw 一起交给时间线标准化
```

未来启用前必须另写设计并满足四个条件：

1. 对应代码的 Tushare 实时请求确实不返回该记录。
2. 记录有可审计的人工证据、日期边界和原因说明。
3. 合并后不会与 raw 记录重叠或产生同一开始日的未决冲突。
4. 测试覆盖 seed 格式、与 raw 的合并优先级、冲突失败和源站后来补齐时的退场策略。

本次三条记录均已由当前 Tushare 返回。若仍新增 seed，就会在同一业务事实旁维护第二份来源，既重复也可能在源站变更时造成冲突。因此本次 **禁止创建校正 seed**。

## 5. C0：namechange 专用 source reader 修正

### 5.1 改动边界

只新增 `fetch_tushare_namechange_announcement_windows_to_raw(...)`，放在 `defs/tushare_api_io.py`；只有 `raw_tushare_namechange` 调用它。

不得修改 `_fetch_all_pages(...)`、`fetch_tushare_full_file_to_raw(...)` 或 `fetch_tushare_full_file_distinct_to_raw(...)`。CodeGraph 证实共享 `_fetch_all_pages(...)` 还被 trade calendar、stock basic、index basic、suspend_d、stock daily、adj factor、stk_nineturn 等 raw asset 使用；本次 source anomaly 只在 `namechange` 上有证据，不能把未验证的语义扩散给其它数据集。

### 5.2 算法与失败语义

输入为公告历史起点 `1990-01-01`、上海时区当天作为 `as_of_date`、固定字段契约和 page limit `6000`。历史起点是 A 股 `namechange` 当前可观测事实的起点，不是迁移日期；`as_of_date` 必须运行时生成，禁止写死 `2026-07-14`。

1. 请求一个公告日期闭区间，显式传 `start_date`、`end_date`、`limit=6000`、`offset=0`。
2. 少于 6,000 行时接受该窗口，且不再对该窗口请求 offset 第二页。
3. 恰好 6,000 行时，按自然日中点拆为两个不重叠闭区间，递归重复第 1-2 步。
4. 单日仍恰好 6,000 行时直接失败。不能退回 offset 翻页，更不能静默截断。
5. 合并所有叶子窗口的行后，继续复用既有全字段 exact distinct、临时文件和 `os.replace` 原子替换。

这仍是一个 lake 的 full snapshot 文件；变化只在于“如何完整地读取同一个 Tushare source”，不是把 raw 改成按日期分区，也不是向 raw 注入人工记录。

### 5.3 可观测性和测试

raw materialization metadata 追加以下最小 source 证据：

- `source_query_strategy=announcement_date_adaptive_bisection`
- `announcement_start_date`、`announcement_end_date`
- `source_query_count`、`accepted_window_count`、`split_window_count`
- `max_accepted_window_row_count`
- 既有 `source_row_count`、`duplicate_removed_count`

`tests/test_namechange_contracts.py` 新增以下证明，不改既有 generic helper 的测试：

1. 根窗口返回 6,000 行时必须二分，所有 accepted 请求均显式带公告日期范围且 `offset=0`。
2. 两个或多个叶子窗口的完整行并集仍按全字段 distinct 写入；metadata 计数正确。
3. 单日窗口仍返回 6,000 行时 fail closed，正式目标文件不被替换。
4. 使用三条本次 anchor 的 fixture，证明无筛选全量缺行时，公告日期窗口并集仍保留三条记录。
5. `raw_tushare_namechange` 只接入新 helper；共享 `_fetch_all_pages(...)` 的调用方和语义不变。

当前实测性能基线：递归路径为 `19900101-20260714 -> 2 次 split -> 3 个 accepted leaf`，总请求数 5，最大 accepted leaf 为 5,652 行。旧逻辑为 3 页请求；新逻辑当前增加 2 次请求，换取不使用不完整 offset 页面的 source 完整性。

## 6. 执行前置与审批边界

本 LLD 不授权立即执行任何写操作。正式执行前需要逐阶段审批，并在每一阶段重新做只读 preflight。

| 阶段 | 读写范围 | 需要确认的事实 | 停止条件 |
|---|---|---|---|
| C0 implementation | 改 namechange 专用 Python、测试和文档；不写 lake / Dagster | 已完成：第 5 节的 source 行为与性能基线由本地测试和只读 Tushare probe 覆盖 | 发现必须修改共享 helper、或 source windows 不能稳定避免 offset。 |
| R0 preflight | 只读 Dagster、lake、Tushare | 三条源记录仍存在；无相关 active run；三个目标资产当前状态已记录 | 任一源记录改变、存在 active run、或当前 unknown gap 样本已变化。 |
| R1 source refresh | 写本地 raw Parquet 与 Dagster run/event | `raw_namechange_update_job` 仅选择 raw 与 raw checks，且 raw 必须通过三条 source anchor 语义验收 | raw checks 不全绿，或三条源记录没有全部写入 raw。 |
| R2 silver rebuild | 写本地 silver Parquet 与 Dagster run/event | `silver_namechange_update_job` 只读 raw 与 `silver_stock_basic` | silver checks 不全绿，尤其 `unknown_adjacent_gap_count != 0`。 |
| R3 identity rebuild | 写 identity-map Parquet 与 Dagster run/event | `stock_identity_map_update_job` 只选择 identity map 与 checks | map checks 不全绿，或 materialization 不满足 2026-07-13 freshness。 |
| R4 downstream recovery | 既有 job 写 minute/qfq Parquet；正常由既有 sensor 注册动态分区 | 7 月 13 日所有上游 readiness 全绿 | 任一上游未 ready 或分区/asset 已 materialized 但 checks 失败。2026-07-14 的一次性直接分区注册由管理员明确批准，并有 preflight 与回读审计。 |

执行期间，为避免日常 sensor 与人工恢复并发，应先只读记录并暂停以下定义；暂停与恢复都使用 DagsterInstance API，按当前 selector 解析，禁止写死历史 instigator id：

- `raw_namechange_update_job_sensor`
- `silver_namechange_update_job_sensor`
- `stock_mins_silver_trade_day_sensor`
- `stock_mins_silver_sensor`

暂停范围只覆盖恢复窗口。R3 验收通过后，先恢复前两个 namechange sensor；R4 结束后再恢复分钟线两个 sensor。2026-07-14 R4 完成后，这四个 sensor 均已恢复为 `RUNNING`，审计报告为 `/private/tmp/namechange_source_drift_recovery_r4_sensor_restore_20260714T075957Z.json`。

`stock_identity_map_sensor` 不在上述四个暂停对象中。R3 前它实际为 `RUNNING`；管理员明确裁定不暂停。执行前以只读查询确认 `stock_identity_map_update_job` 没有 active run，执行后审计再次确认没有并发 run。此处只记录本次 R3 的明确例外，不把“sensor 运行中也可随意手工重建”扩展为通用规则。

本次初始 R0 已完成，报告为 `/private/tmp/namechange_source_drift_recovery_preflight_20260714T135409.json`。四个相关 sensor 原先均为 `RUNNING`，已按本节暂停。原 R1 已运行 `raw_namechange_update_job`（run `15fdc9d4-e11b-4fff-8d52-2f264d894c2a`），raw checks 全绿但缺三条 anchor；它是失败的 source semantic validation，不得作为 R1 通过依据，也不得继续 R2。

新的 R1 前置只读 preflight 已于 2026-07-14 通过，报告为 `/private/tmp/namechange_source_drift_recovery_preflight_20260714T063532Z.json`：四个相关 sensor 均为 `STOPPED`，四个相关 job 均无 active run，Tushare 三条 anchor 均精确返回一次；当时 raw 与 silver 均尚未包含 anchor，符合重建前状态。

## 7. R0：只读 preflight

输出报告固定写入 `/private/tmp/namechange_source_drift_recovery_preflight_<timestamp>.json`，至少包括：

1. Tushare 实测的三条精确记录及请求字段。
2. raw/silver 中四个代码的相关时间线行。
3. raw / silver schema、行数、最新 materialization、blocking check 状态和失败规则名。
4. `silver_namechange` 的 `unknown_adjacent_gap_count` 与样本。
5. `silver_stock_identity_map` 的 materialization 日期和 checks。
6. `2026-07-13` 的 raw minutes、stock daily、suspend、identity map、silver minutes、gold qfq readiness。
7. 四个相关 sensor 的当前状态和相关 job 的 active run 列表。

R0 只读，不启停 sensor，不写 lake，不写 Dagster event。

## 8. R1-R3：基础事实恢复

### R1：用修正后的 source reader 刷新 raw full snapshot

在 C0 通过、代码部署并完成新的只读 R0 后，运行 `raw_namechange_update_job`。这是完整快照替换，不是对三条记录做局部插入。

验收：

1. raw contract、key integrity、date domain 等 blocking checks 全绿。
2. raw 中存在第 3.2 节的三条记录，字段值与当前 Tushare 实测相同。
3. raw 写入仍使用既有 `.tmp -> os.replace` 原子替换；不在恢复脚本中直接写 raw 文件。

执行结果（2026-07-14）：已运行 `raw_namechange_update_job`，run id 为 `6ef02fe6-2ab3-485e-a4e2-915727fd00d5`，状态 `SUCCESS`。作业输出 `source_query_count=5`、`accepted_window_count=3`、`source_row_count=14135`、`duplicate_removed_count=0`。只读审计报告为 `/private/tmp/namechange_source_drift_recovery_r1_raw_audit_20260714T064142Z.json`，确认：

1. `raw_tushare_namechange` 的三个 blocking checks 全绿，materialization storage id 为 `6668931`。
2. raw Parquet 为 14,135 行，distinct row count 也是 14,135；schema 仍是六个 raw `VARCHAR` 字段。
3. 第 3.2 节三条 anchor 在 raw 中均恰好一行，字段与 R1 preflight 的 Tushare 实测一致。

R1 至此完成；未自动启动 R2。

### R2：重建 silver 名称时间线

只在 R1 全绿后运行 `silver_namechange_update_job`。

验收：

1. 所有 silver blocking checks 全绿。
2. `unknown_adjacent_gap_count=0`。
3. 四个代码在 silver 中满足第 3.2 节的预期；`002640.SZ / 跨境通` 必须出现。
4. 不允许把 unknown gap 加入 `KNOWN_NAMECHANGE_ADJACENT_GAP_KEYS` 来绕过检查。

执行结果（2026-07-14）：已运行 `silver_namechange_update_job`，run id 为 `4ab240f4-5238-426c-b45e-d145e1157e51`，状态 `SUCCESS`。stdout 记录 raw source 14,135 行、silver 输出 12,155 行、当前股票池 5,530 只、选中事件 12,198 条。只读审计报告为 `/private/tmp/namechange_source_drift_recovery_r2_silver_audit_20260714T071431Z.json`，确认：

1. `silver_namechange` 的三个 blocking checks 全绿，materialization storage id 为 `6668977`。
2. silver Parquet schema 仍为六个既有字段，日期列保持 `DATE`，行数为 12,155。
3. `unknown_adjacent_gap_count=0`、`overlap_count=0`、`adjacent_gap_count=0`，没有通过 allowlist 掩盖空档。
4. `002640.SZ / 跨境通` 已存在，区间为 `2015-06-12` 至 `2021-05-06`。
5. R2 后不自动启动 R3。

### R3：重建股票身份映射

只在 R2 全绿并且 `silver_stock_lifecycle` 仍满足当日 freshness 后运行 `stock_identity_map_update_job`。

验收：

1. identity map 全部 blocking checks 全绿。
2. identity map materialization 日期不早于 `2026-07-13`。
3. `silver_stock_identity_map_ready_for_trade_date(..., "2026-07-13")` 为 ready。

执行结果（2026-07-14）：已运行 `stock_identity_map_update_job`，run id 为 `fd0620fa-b3d9-413f-94da-a8736b8db57b`，状态 `SUCCESS`。stdout 记录输出 6,116 行，其中 lifecycle 自映射 5,865 行、seed 映射 251 行。只读审计报告为 `/private/tmp/namechange_source_drift_recovery_r3_identity_audit_20260714T072521Z.json`，确认：

1. identity map 的三个 blocking checks 全绿，materialization storage id 为 `6669023`。
2. 6,116 个 `source_ts_code` 全部唯一，schema 为既有十个字段。
3. identity source 分布为 `stock_lifecycle=5865`、`bse_mapping=240`、`namechange=11`。
4. `silver_stock_identity_map_ready_for_trade_date(..., "2026-07-13")` 为 ready，materialization 日期为 `2026-07-14`。
5. `stock_identity_map_sensor` 保持 RUNNING，但执行前后 `stock_identity_map_update_job` 均无 active run；R3 后不自动启动 R4。

## 9. R4：恢复 2026-07-13 下游链路

R4 是独立批准的生产写入阶段。原定默认顺序如下：

1. 在 `stock_mins_silver_trade_day_sensor` 的既有注册窗口内恢复 sensor，由它注册最早缺失的 `cn_a_stock_mins_silver_trade_days` 分区。
2. 确认 `2026-07-13` 已注册且 raw minutes、stock daily、suspend、identity map 全部 ready。
3. 运行 `stock_mins_silver_update_job[2026-07-13]`，五个频度及 checks 全绿后才继续。
4. 运行 `stock_mins_qfq_daily_update_job[2026-07-13]`，七个频度及 checks 全绿后才继续。
5. 运行 `stock_mins_qfq_factor_repair_job`，配置只传 `trade_date=2026-07-13`。它按既有因子差异逻辑决定 no-op 或历史修复；本 LLD 不预先假设结果。

执行结果（2026-07-14）：管理员在 registration window 前明确要求直接注册并推进补数。因此，先运行只读 preflight（`/private/tmp/namechange_source_drift_recovery_r4_preflight_20260714T074349Z.json`），确认目标未注册、raw 五频、股票日线、停牌、身份映射均 ready，且相关 job 无 active run；随后仅写入 `cn_a_stock_mins_silver_trade_days=2026-07-13`，注册数由 3,043 变为 3,044，回读报告为 `/private/tmp/namechange_source_drift_recovery_r4_direct_registration_20260714T074459Z.json`。

后续严格按既有 job 顺序完成：

1. `stock_mins_silver_update_job[2026-07-13]` 成功，run id `bf45f30b-62a5-40b3-8447-2cd2b70c4c19`；五频 lake readiness 全绿，5 个文件、1,773,204 行、无 failed checks。
2. qfq preflight 按 qfq sensor 的最近 5 日真实 lake readiness 语义通过，报告为 `/private/tmp/namechange_source_drift_recovery_r4_qfq_preflight_20260714T074824Z.json`。
3. `stock_mins_qfq_daily_update_job[2026-07-13]` 成功，run id `6c48ee7a-5716-472e-a279-bfc20a19793d`；七频 lake readiness 全绿，38,668 个预期文件全部存在、1,800,824 行、无 failed checks。90 分钟与 120 分钟派生频度的 `incomplete_window_count` 均为零。
4. `stock_mins_qfq_factor_repair_job` 仅以 `trade_date=2026-07-13` 配置成功运行，run id `f94d67ee-288c-481f-a8dd-32922391cb47`。既有差异逻辑判定 33 个代码需要修复，已从 `2014-01-02` 回刷至 `2026-07-13`；它不是 no-op。
5. 最终审计 `/private/tmp/namechange_source_drift_recovery_r4_final_audit_20260714T080255Z.json` 证明目标分区已注册、silver/gold qfq/factor repair 全部 ready，三个 R4 job 无 active run。

factor repair 同时返回 `requires_derived_reconciliation=true`。本节不包括 MACD/KDJ 历史 reconciliation；该状态必须作为独立专项评估，不能因 R4 成功而把任何 MACD/KDJ repair 标记为完成。后续恢复、代码硬化、四个 daily state 缺口和正式 repair 的执行门禁已独立写入 `dagster-stk-mins-qfq-macd-kdj-reconciliation-recovery-r5-low-level-design.md`；R4 只作为其上游输入事实，不扩展 R4 的写入范围。

## 10. 性能、原子性与回退口径

| 项目 | 本次口径 |
|---|---|
| Tushare 请求 | 公告日期递归二分；当前 5 次请求、3 个 accepted leaf，任何 accepted leaf 均不使用 offset 翻页。不按三只代码拆成旁路生产写入。 |
| Lake 写入 | R1 写 1 个 raw full-snapshot Parquet；R2 写 1 个 silver full-snapshot Parquet；R3 写 1 个 identity-map full-snapshot Parquet；R4 写目标日 5 个 silver minutes、7 个 gold qfq 频度，并由既有 factor repair 计划决定必要的历史回刷。 |
| 计算模型 | 复用当前实现；不增加逐日循环、历史 backfill、runless event 或新的 Dagster 状态实体。 |
| 原子性 | 三个 full snapshot asset 均使用既有临时文件校验后替换正式文件；下游仅在上游 materialization 和 checks 均 green 后继续。 |
| 失败恢复 | 停在失败层，不向下游推进；重新从当前 Tushare 公告日期完整窗口并集恢复，不人工恢复旧的已知缺行 raw 快照。 |
| Dagster DB | 只产生正式 job/run/materialization/check 记录；不做 SQL 清理或 runless event 补录。R4 的一次性动态分区注册通过 DagsterInstance API 完成并回读，不直接 SQL 改库。 |

## 11. 最终验收与文档同步

本次整体审计由 R1、R2、R3 分层报告及 R4 最终报告 `/private/tmp/namechange_source_drift_recovery_r4_final_audit_20260714T080255Z.json` 组成；后续同类恢复可写入 `/private/tmp/namechange_source_drift_recovery_final_audit_<timestamp>.json`。最终审计至少证明：

1. R1-R3 每层的 run id、materialization、blocking checks 与三条源记录对账结果。
2. `silver_namechange` 未知相邻 gap 为 0；没有通过 allowlist 掩盖问题。
3. `silver_stock_identity_map` 对 `2026-07-13` ready。
4. 若执行 R4，逐项记录动态分区注册、silver minutes、gold qfq 和 factor repair 的结果。
5. 未修改 prod DB、未新增校正 seed、未直接编辑 Parquet、未直接 SQL 修改 Dagster DB。

C0 已完成但尚未提交：新增 `fetch_tushare_namechange_announcement_windows_to_raw(...)`，`raw_tushare_namechange` 已接入该 helper，测试覆盖切窗、exact distinct、三条 anchor、单日满页 fail closed 和 raw asset 接线。执行了 `ruff` 与 122 项关联单测/静态门禁。新的 R1-R4 均已按本文件记录写入正式 lake 与 Dagster run/check events；R4 的最终审计为 `/private/tmp/namechange_source_drift_recovery_r4_final_audit_20260714T080255Z.json`。未修改 prod DB、未新增校正 seed、未直接编辑 Parquet、未直接 SQL 修改 Dagster DB。

## 12. 代码级影响面审计

以下是 C0 和后续恢复必须遵守的代码边界：

| 文件 | 当前职责 | 本次处理方式 |
|---|---|---|
| `defs/tushare_api_io.py` | 通用分页、generic full-file helper 与新 namechange 专用 reader | 已新增专用 reader；共享 helper 未修改。 |
| `defs/assets/namechange.py` | raw full snapshot 写入、silver 时间线生成和原子替换 | raw 已改接专用 reader，并更新 source metadata/description；silver 逻辑未修改。 |
| `defs/namechange_timeline.py` | 选择源事件、闭合区间、统计 unknown gap | 复用，不把本次记录写进人工选择或 known-gap allowlist。 |
| `defs/checks/namechange_checks.py` | 以 `unknown_adjacent_gap_count` 阻断 silver | 复用，不降低 check 语义。 |
| `defs/jobs/namechange_update.py` | raw / silver 分层 job selection | 复用，不创建恢复专用 job。 |
| `defs/assets/stock_identity_map.py` | 消费 silver namechange 重建身份映射 | 复用，不把 namechange 历史直接塞入 identity seed。 |
| `defs/sensors/stock_mins_silver_trade_day_sensor.py` | 依赖 identity map freshness 注册分钟线 silver 分区 | 正常生产继续复用；本次 R4 的直接注册是管理员明确批准的一次性运维动作，未修改该 sensor 代码或长期规则。 |
| `tests/test_namechange_contracts.py` | namechange raw distinct 与时间线契约 | 已新增 source window split、单日 fail-closed、anchor fixture 与 raw asset 接线测试。 |

CodeGraph 已用于追踪 `raw_tushare_namechange -> silver_namechange -> silver_stock_identity_map -> stock_mins_silver_trade_day_sensor` 的调用链、raw/silver/identity/minutes/qfq job selection，以及共享 `_fetch_all_pages(...)` 的 8 个其它 raw asset 消费者。它证明本次修复必须限定在 namechange；需要人工确认的边界是 C0 代码评审和每个正式写阶段的审批与当时的 live preflight。
