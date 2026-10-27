> 历史记录：第一轮名单审计，当前结论已由README.md中的第二轮关联审计替代。

# DG已退役资产历史记录清退审计与候选名单

状态：2026-10-27只读审计完成；名单及清退方式待管理员review，未执行任何删除。THS补数仍暂停。

## 1. 本轮结论与范围

当前正式DG目录183项，其中180项有当前定义，3项是已退役但仍可见的历史资产。正式PG资产索引186项，比当前资产图多6项；另3项已于5月执行过wipe、页面已不显示，但仍有底层旧事件/清除标记。检查执行索引共181种asset key，额外旧key恰为可见周/月三项，没有新增的无定义检查资产。两份枚举均未达到数量边界，当前索引范围完整覆盖。

建议先review以下6个旧资产作为清退对象范围。它们均无当前定义、不在现行180项registry、当前依赖图无下游，生产目录精确引用为0，并有退役/替代依据。**这仅是对象名单，不是可直接执行的物理删除SQL。** 原生wipe与真正删除日志不是同一动作，见第4节。

本轮未读Lake/源端数据，未启动job、改cursor/开关或执行wipe；没有按年龄、失败状态或旧job名批量删除日志。未全扫描原始event_logs正文，因此不声称所有无索引旧日志都已逐条判定。

## 2. 清退对象名单

| 序号 | 旧asset key | 含义及退役依据 | 页面当前状态 | 按asset_key直接索引的事件行 | 检查执行索引行 |
| --- | --- | --- | --- | ---: | ---: |
| 1 | `raw_tushare_stk_period_bar_month` | 旧独立未复权月线；2026-10-15退役，82e5c225/2783789c | 仍可见，无定义 | 206 | 609 |
| 2 | `raw_tushare_stk_period_bar_week` | 旧独立未复权周线；2026-10-15退役，82e5c225/2783789c | 仍可见，无定义 | 865 | 2,583 |
| 3 | `raw_tushare_weekly` | 旧备用周线；2026-10-15退役，82e5c225/2783789c | 仍可见，无定义 | 804 | 2,409 |
| 4 | `silver_index_daily_active_pool` | 旧指数采集代码池；2026-05-25删除旧链，e5d1156ec；同日已wipe | 5月已wipe，当前不显示 | 2 | 0 |
| 5 | `gold_market_major_indices` | 旧主要指数展示名单；2026-05-26替换旧实现，c7bb7606d；同日已wipe | 5月已wipe，当前不显示 | 8 | 0 |
| 6 | `raw_tushare_index_daily` | 旧有效池驱动的Tushare指数日线；2026-05-25删除旧链，e5d1156ec；同日已wipe | 5月已wipe，当前不显示 | 2 | 0 |

**数量不能混算。** 前三项直接索引事件1,875行，检查执行索引5,601行；后三项直接索引事件共12行、检查执行索引0行。它们不是“待删全部事件总数”：检查索引与原始检查事件不是一一对应，且原始检查事件的SQL asset_key通常为NULL。不能把1,887+5,601相加当作全部待删日志。

### 2.1 周/月三项

三项已于10月15日移除asset/job/check/catalog/source/path及旧数据目录，原代码提交82e5c225、收尾2783789c。当前退役测试明确排除这三key，仅保留两个adj Raw。现行Silver周/月依赖adj Raw、生命周期和身份映射，不读取这三项历史。原任务有保留DG历史的边界，因此本次清历史须以本次名单review后的授权为准，不能沿用旧删除目录的授权。

### 2.2 另外三个旧指数资产

- `silver_index_daily_active_pool`：现行指数代码集合来自cn_a_index_ts_codes；它不是silver_index_daily行情表的旧名字。
- `gold_market_major_indices`：原rank/代码/名称名单改为版本化CSV seed；gold_market_major_indices_daily另由seed+Silver行情生成。
- `raw_tushare_index_daily`：先转by-code链，后由b61e052cc迁入Prod按日raw_index_daily，不是简单改名。

旧指数迁移LLD曾将旧Raw/active-pool历史列为二级候选，要求单独确认调试用途。它们在现行生产中没有用途，但已wipe的索引行还保存“旧事件已清除”的标记，不能把标记与无用事件一起随手删除。若未来选择物理清理，先保持标记，待底层事件范围和重建行为验证完成后再决定是否删该索引行。

## 3. 已核影响与保留对象

- 当前180个资产全部保留；没有把完整快照、健康资产、不可执行定义、周/月周期数据或检查失败资产当作废弃资产。
- 现行两个adj Raw、silver_stock_weekly/monthly、raw_index_daily、silver_index_daily、gold_market_major_indices_daily及其历史保留。
- 当前依赖图没有资产指向6个旧key；当前生产代码精确查找未命中6key。现存其他资产检查执行索引没有引用上述旧物化的materialization_event_storage_id。此结论不替代第5节待核的原始payload指针。
- 前三项涉及6个非空历史run，其按asset_key索引的资产事件没有发现其他key；这不代表可以删除整run。原始检查事件和普通日志归属不同，且runless事件共用空run_id，必须保留所有非目标行。
- job/run、step日志、sensor/tick/cursor、动态分区、业务Lake/staging、receipt/checkpoint和当前THS失败证据不作为本轮直接清退对象。

## 4. review时必须区分的两种清退方式

### A. 只清理资产目录与资产侧历史（范围较小）

使用本机Dagster1.13.26原生整资产wipe，仅对前三项操作。框架写wipe时间，清空最近物化/run指针和状态缓存，物理删除对应asset_check_executions记录，并追加ASSET_WIPED事件。旧event_logs正文及run记录仍保留，按run仍能查看。后3项早已wipe，不应为清目录重复wipe。此方式能解决页面旧条目问题，但**不满足物理删掉全部旧事件的目标，也不能宣称释放数据库文件空间**。

### B. 真正删除旧资产专属事件（按管理员“无用历史删除”意图列候选）

对象范围为第2节6key。仅删除确认属于它们的资产事件、原始检查事件及关联检查/标签记录；保留共享run、普通执行日志、非目标资产和所有业务数据。**尚未完成事件级关联清单，当前不得执行。** 本机原生wipe不提供这项物理删除，不能用它冒充实现。是否选择该范围及是否保留旧运行调试信息由本次review决定，之后先完成正式方案/LLD和下面门槛。

## 5. 正式删除前仍需完成的门槛

1. 冻结已批准6key（或较小范围）、具体事件ID/类型/表名及数量上界，不能按整个run、run_id为空、日期或SQL LIKE删除。
2. 补齐SQL asset_key为NULL的ASSET_CHECK_EVALUATION/PLANNED真实归属。仅靠检查摘要evaluation_event_storage_id会漏掉早期计划事件，已wipe3key的检查摘要也不能用来证明原始检查事件已删除。
3. 核非目标检查/原始payload对拟删storage id的引用，以及其他资产的dagster/input_event_pointer旧key元数据，避免破坏保留历史的溯源。
4. 明确asset_event_tags等无自动级联的关联记录；处理资产索引、wipe标记、缓存与候选ID的一致性。
5. 写清正式执行命令/实例、事务与分批、中断后只继续未完成部分、可恢复性和最后验收预算；批准前不编写或执行删除程序。数据库收缩/整表VACUUM FULL不在本轮范围。
6. 执行前再次只读核definition/依赖/活动run和输入身份未变，按本次授权范围处理。验收候选清除、180项现行资产/索引仍在、其他检查和运行记录不变；不重跑生产数据job作验收。

## 6. 依据与验证边界

- [运行中DG目录与依赖](inventory.json)、[完整枚举汇总](inventory-summary.json)。
- [资产及检查索引与三项事件计数](history-metadata-counts.json)、[已隐藏三项底层计数](hidden-history-counts.json)、[可review名单JSON](retirement-candidates.json)。
- 当前代码：tests/test_stock_period_retirement.py:40、assets/stock_weekly.py:69、assets/stock_monthly.py:71、assets/index_daily.py、assets/market_major_indices.py。历史提交：82e5c225/2783789c、e5d1156ec、c7bb7606d、b61e052cc。
- [周/月退役事实](../../docs/design/dagster-stock-weekly-alternate-source-raw-backfill-plan-v1.md#8-已完成与后续任务)、[指数迁移旧历史候选](../../docs/design/dagster-index-daily-raw-by-date-prod-db-migration-low-level-design.md)。
- 原生清理实现以本机SDK sql_event_log.py:1913—1952、asset_methods.py:684及GraphQL执行实现为准；[官方CLI说明](https://dagster.io/docs/api/clis/cli)也说明wipe用于移除asset key索引。

本次执行只读查询、代码/历史文档核对和元数据计数。一次报告保存因datetime格式失败后已修正，仅重取同范围元数据，没有读取行情/事件正文或写库。没有运行测试、扩大清退、删除任何数据。CodeGraph符号核验结合当前生产目录精确引用及正式依赖图完成；归档脚本/未知仓库外消费者不在当前代码审计范围，不将其自动视作安全。

最终文档/相对链接及清单一致性结果见validation.json。
