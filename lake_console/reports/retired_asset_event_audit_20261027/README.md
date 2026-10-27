# DG已退役资产历史记录物理清退审计

状态：已完成。2026-10-27 16:13:53按管理员授权，完成执行方案／LLD、恢复副本、隔离验证后，一次事务物理清退六项历史。目录183→180，现行180项保留；结果见第8节。THS补数仍暂停。

## 1. 结论与范围

**六项已退役资产的专属历史已按精确清单物理删除。** 删除前确认当前定义、生产代码和正式依赖图不再使用它们，其他资产的检查、物化溯源及最近物化缓存没有指向待删事件。四表一起处理，未用原生wipe代替物理删除。

正式实例为 `/Users/congming/.goldenshare/dagster_home`，数据库为本机 `goldenshare_dagster`，安装版Dagster为1.13.26。第二轮证据时间为2026-10-27 15:01—15:10（Asia/Shanghai）；事件清单冻结上界为storage id **7,735,139**。删除前重读目录183项、当前定义180项，六个旧key无定义、无下游引用；删除后目录为180项，见第8节。

| 已处理表 | 已删除数量 | 处理对象 |
| --- | ---: | --- |
| `event_logs` | **7,537** | 六项自己的物化、计划、检查、freshness和旧wipe事件 |
| `asset_check_executions` | **5,601** | 六项自己的检查记录，含独立保存的检查正文副本 |
| `asset_event_tags` | **8** | 属于六项且指向上述事件的标签 |
| `asset_keys` | **6** | 六项索引及最近物化副本、隐藏标记和缓存 |
| 合计 | **13,152行** | 四表不同记录，不是13,152条原始事件 |

审计和本次清退仅涉及DG元数据，没有读写行情、Lake、staging或源端业务数据。按六个精确key、明确事件类型和事件ID处理，没有导出全库日志；只有四表13,152行完整副本留在本机持久恢复目录。

## 2. 逐项清退列表

| 旧asset key | 直接索引事件 | 原始检查事件 | 原始事件合计 | 检查记录 | 标签 | 资产索引 | 结论 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `raw_tushare_stk_period_bar_month` | 206 | 615 | **821** | 609 | 2 | 1 | 已删除 |
| `raw_tushare_stk_period_bar_week` | 865 | 2,592 | **3,457** | 2,583 | 3 | 1 | 已删除 |
| `raw_tushare_weekly` | 804 | 2,409 | **3,213** | 2,409 | 0 | 1 | 已删除 |
| `silver_index_daily_active_pool` | 2 | 0 | **2** | 0 | 0 | 1 | 已删除 |
| `gold_market_major_indices` | 8 | 34 | **42** | 0 | 3 | 1 | 已删除 |
| `raw_tushare_index_daily` | 2 | 0 | **2** | 0 | 0 | 1 | 已删除 |
| 合计 | **1,887** | **5,650** | **7,537** | **5,601** | **8** | **6** | 已完成 |

### 2.1 退役与替代依据

- 周/月三项于2026-10-15移除asset/job/check/catalog/source/path及旧目录，提交82e5c225、收尾2783789c；原清退保留DG历史，本次删除历史须另获授权。现行Silver周/月读取 `raw_tushare_stk_period_bar_adj_week/month`、生命周期及身份映射。
- `silver_index_daily_active_pool` 是旧指数代码池，2026-05-25由e5d1156ec删除旧链。当前集合来自 `cn_a_index_ts_codes`；它不是 `silver_index_daily` 行情表的旧名字。
- `gold_market_major_indices` 是旧rank/代码/名称名单。c7bb7606d于5月26日改用版本化CSV seed，并另建seed＋Silver行情生成的 `gold_market_major_indices_daily`，合同不同。
- `raw_tushare_index_daily` 是旧有效池驱动的Tushare链，先转by-code链，再由b61e052cc迁入当前Prod按日 `raw_index_daily`，不是简单改名。

### 2.2 为什么这次数量比第一次完整

第一次1,887行只是 `event_logs.asset_key` 直接索引事件。检查事件的这个SQL字段通常为NULL，不能靠它判断归属。

本次按真实JSON字段 `dagster_event.event_specific_data.asset_key.path` 精确识别，核出5,650条原始检查事件：5,615条结果、35条计划。周/月三项有5,616条；旧主要指数另留34条，虽然该资产的检查记录早已被wipe删掉。

检查结果生成后，检查记录会更新事件指针，早先计划事件仍在。因此原始检查事件与检查记录不是一一对应，不能把1,887与5,601相加作为原始事件总数。已核两种检查事件存量JSON均有明确资产路径。

## 3. 关联核验结果

| 核验项 | 结果 | 对删除的意义 |
| --- | --- | --- |
| 当前生产代码精确引用、正式图下游 | 0 | 日更、readiness、repair及周/月续跑均不使用六项 |
| 非目标检查记录引用拟删事件ID | 0 | 不删其他资产检查所需事件 |
| 非目标原始检查结果指向拟删物化 | 0 | 也覆盖检查记录已清过的情况 |
| 物化正文中六个精确 `dagster/input_event_pointer/<旧key>` 标签 | 0 | 保留物化未以这些标签引用旧事件 |
| 非目标最近物化缓存指向拟删ID | 0 | 不会留下其他资产最近缓存指向已删事件 |
| 非目标标签指向拟删事件 | 0 | 八条目标标签均属于六项 |
| 六key自动化评估、含精确旧key的instigator状态／backfill | 0 | 未发现待继续的自动化或回填依赖 |
| 新于冻结上界的六key事件 | 0 | 核验期间没有新增目标事件 |
| 核验时活动／排队run | 0 | 九次关联旧运行均已结束 |

字符串包含不能替代精确key。一条保留缓存初筛命中旧主要指数名字前缀，实际标签为 `dagster/input_event_pointer/gold_market_major_indices_daily`，指向当前事件7,732,120；不是旧key，必须保留。日志正文名字初筛次数也不是候选数，最终仅按JSON完整资产路径计入。

### 3.1 标签和正文分别核验

安装版 `asset_event_tags` 仅索引data-version及多维分区标签，不索引全部 `input_event_pointer`。本次同时核标签表及物化正文中的六个精确标签，没有只凭标签表零命中判断无引用。

### 3.2 资产索引保存独立副本

六条 `asset_keys.last_materialization` 都非空。两个副本引用的原始事件1,173,161、1,412,675已经不在 `event_logs`，分别属于旧代码池和旧指数Raw，不是本次删除造成。已另核非目标检查记录及原始检查对这两个ID的引用，均为0。

所以只删日志还不够，六条索引中的副本也应一起删。目录已隐藏不代表旧记录已物理清完。

### 3.3 正式库没有事件关联外键

正式PG全部约束已核：仅有 `runs→snapshots`、`run_tags→runs` 两种外键，没有标签或检查记录到事件的外键。安装包历史迁移与当前schema写法不同，本结论以正式库为准。

不能依赖数据库自动级联清理，也不能只删事件、留下检查正文和资产缓存。普通数据库索引自动维护；`secondary_indexes` 是迁移记录，不是待删事件明细，必须保留。

## 4. 保留范围与实际影响

必须保留：

- 当前180个资产及历史，包括两个现行adj Raw、股票周/月Silver、当前Raw/Silver指数日线和 `gold_market_major_indices_daily`。
- 九条关联run、23条run tags、五个被这些run引用的快照，以及这些run内319条非目标普通事件。快照未查到这九条之外的run引用，仍服务保留运行记录，不能单独删。
- sensor/schedule开关、cursor、tick、动态分区、并发控制、daemon状态、迁移记录、业务Lake/staging、receipt/checkpoint、报告及THS失败证据。

九条run中八条成功、一条失败，均为旧周/月或主要指数任务；403条运行内事件中84条属于本次目标、319条保留。按asset_key索引没有其他资产，不等于可以删整次run。空run_id还承载其他资产runless事件，禁止按空run_id删除。

删除后的实际影响：

1. 六项专属历史、检查记录及缓存被物理删除，当前仍可见的三个旧周/月条目消失，当前180项保留。
2. 九次旧运行仍显示终态和普通日志，但旧资产物化、检查详情及相关统计减少。这是清退历史的预期结果，不能声称旧运行页面完全不变。
3. 不改变当前数据文件、计算、日更、repair或开关／cursor，不重跑生产job验收。
4. 已删除事件详情不能再从DG查询。报告和ID清单用于说明清退，不是正文备份。

“可安全删除”限定为本报告专属事件及三种关联记录，以执行前状态未变化为前提。没有扩大为任意旧job、整次run、其他资产历史、仓库外工具或历史文件清理授权。

## 5. 第二轮审计时形成的物理清退边界

本节记录第二轮审计结束时的方案边界；实施细节与本次授权见第7节，不再把本节未完成项视为尚未获得业务授权。**不采用原生wipe冒充物理删除，也不先wipe破坏关联证据。**

### 5.1 输入与写入边界

[physical-deletion-manifest.json](physical-deletion-manifest.json)冻结四表ID、所属资产、事件类型／关联ID及校验摘要，预期数量为7,537、5,601、8、6行。

后续只能按这些主键及已核身份处理，逐类校验数量；禁止按名字前缀、LIKE、日期、step_key、整run或空run_id删除。候选增减、身份变化、定义恢复或出现非目标引用，停止并重新核定范围。

### 5.2 执行前与事务顺序

1. 核实例／数据库、清单摘要、现行180项及六key仍无定义／下游，确认没有新目标事件或活动旧任务。仅核变化，不重审业务数据。
2. 补齐正式命令、必要恢复安排、隔离验证结果及最终预算，完成管理员review和正式写入授权。当前没有删除工具，也没有可恢复的完整正文副本，ID清单不是备份。
3. 建议单个短事务：核目标ID及关联 → 删除八条标签 → 删除5,601条检查记录 → 删除7,537条事件 → 最后删除六条资产索引。每步断言影响行数，不符则整笔rollback。
4. 三个旧wipe事件和三个隐藏索引只在同一事务中、目标底层事件全部清除后一起清掉。禁止先删隐藏标记、留下旧正文；不让旧历史重新暴露。
5. 提交前核四表目标残留为0、保留资产／run及普通事件未被本事务删除。提交后再做一次必要计数与目录核验：目录183→180，资产索引186→180；不启动生产job。

### 5.3 失败、中断和继续

- 提交前失败／中断：四表同一事务回滚，不做部分提交后逐资产拼接清理。
- 提交结果不明确：在同一只读一致快照或一条聚合查询中核四表全部冻结ID，全部存在表示未完成、全部消失表示完成；部分存在则停止调查，不自动重跑。不能用四次可能跨越提交时刻的独立查询判断“部分删除”。
- 提交后：删除历史是预期行为，不能靠运行当前job重造旧记录；正式安排须明确是否保留删除前完整副本及期限。
- 不停其他数据集、不切sensor、不删run、不清空迁移标记、不重置序列、不安装依赖、不运行Kopia，不执行数据库收缩或 `VACUUM FULL`。

### 5.4 数量和验证预算

7,537条事件正文合计12,577,340字节（约12.00MiB），检查记录独立正文8,324,367字节（约7.94MiB）；另有少量标签、行头、缓存及索引。约19.93MiB是两类正文长度，**不是删除后必然释放的磁盘大小**。PG删除通常先形成可复用空间，不承诺立即缩小数据库文件。

后续涉及13,152行，正常单事务一次，提交后必要验收一次；中断确认仅重读本次ID。实际WAL、锁等待、恢复副本和最终耗时预算由正式工具／隔离验证补齐，不能把未测值写成通过。“关联核验通过”不等于“删除程序已开发验收”。

## 6. 依据与验证边界

- [精确清单](physical-deletion-manifest.json)、[逐项结论](retirement-candidates.json)、[关联核验汇总](physical-association-summary.json)。
- [正式schema／约束](phase1-metadata.json)、[真实payload样本](phase2-ownership-counts.json)、[事件归属与反向检查索引](phase3-exact-relations.json)、[正文指针、标签及run](phase4-reverse-references.json)、[缓存核验](phase5-cache-and-run-details.json)、[缓存ID及快照](phase6-final-association-counts.json)、[最终正式依赖图](final-live-inventory.json)。
- [第一轮审计](initial-candidate-audit.md)保留为历史；其直接索引数量不能当全部待删事件。原始 [目录](inventory.json)、[索引计数](history-metadata-counts.json)、[隐藏资产计数](hidden-history-counts.json)仅代表首次审计时点。
- [周/月退役记录](../../docs/design/dagster-stock-weekly-alternate-source-raw-backfill-plan-v1.md#8-已完成与后续任务)、[指数迁移LLD](../../docs/design/dagster-index-daily-raw-by-date-prod-db-migration-low-level-design.md)。

当前实现依据：`tests/test_stock_period_retirement.py:40`、`assets/stock_weekly.py:69`、`assets/stock_monthly.py:71`、`asset_guards/stock_period_silver_readiness.py:57`、`sensors/readiness.py:358`起。现行readiness明确按当前资产及相同事件ID查询，不使用六项旧记录。

框架依据相对 `.venv/lib/python3.13/site-packages/dagster/_core/`：`storage/event_log/schema.py:72–89,157–183`、`storage/event_log/base.py:626–632`、`definitions/data_version.py:157–160,189,208`、`storage/event_log/sql_event_log.py:312–320,1306–1315,1913–1947,3216–3237`、`storage/runs/schema.py:8–47,66–92`。Context7已查官方源码文档日志清理说明，本机1.13.26代码及正式PG约束决定具体行为。

两位独立审计核对现行生产引用及安装版关联机制，未发现现行业务依赖阻断。成功SQL查询记录合计约56.3秒，不含两条失败只读查询和人工核验时间；两条查询分别因列名、历史JSON null形态失败，事务回滚后只续查未完成项，未重复整轮审计。

前两轮只读审计不扫描普通日志正文里的任意数字；运行日志、历史配置、报告可能仍出现旧名称／ID，全部保留。未声称仓库外手工工具已审计。后续开发、隔离验证及正式删除已按第7节完成，真实结果见第8节；不能把早期只读证据当作本次执行凭据。

文档、数量和链接检查见 [validation.json](validation.json)。

## 7. 本次执行方案与LLD

### 7.1 目标、授权、代码位置及边界

管理员本轮明确指令：按六项清单推进，先完善执行方案／LLD、完成隔离验证及恢复安排，再正式删除。因此本节覆盖的备份、隔离集群、正式四表删除和必要验收已有业务授权；工具权限仍按实际命令申请。正式恢复不自动执行，发生需要恢复的情形先停止并报告。

唯一输入仍是 `physical-deletion-manifest.json`，canonical payload SHA-256为 `7bbe2a485f3ea2e7d719a8b44186d8c23983d1d689bc67071c85882a2b7896a0`；四表行数固定7,537／5,601／8／6。实现不改Dagster definitions、catalog、job、sensor、现行API／CLI或业务库。

新增独立维护模块 `orchestrator/maintenance/retired_asset_history.py`，从本项目现有解释器以 `python -m` 调用；不放入 `defs`，不由webserver／daemon导入。测试放 `tests/test_retired_asset_history.py`，只连临时PG。既有 `historical_materialization_reconciliation.py` 只追加缺物化事件，不提供四表精确清退或恢复，不能拿它替代本次操作。原生wipe也不满足物理删除要求。

CodeGraph已核索引状态和 `LAKE_ASSET_CATALOG` 位置，结合上一轮当前代码、SDK、正式依赖图审计。新增模块没有业务消费者，不改变跨子系统依赖；运行时只用已有psycopg2、PyYAML和标准库，不初始化Dagster instance。

### 7.2 配置／输入审计

| 输入／运行约束 | 来源、持久化及默认 | 消费者／生效方式 | 限制与测试 |
| --- | --- | --- | --- |
| manifest | 显式CLI路径，内容及摘要固定 | loader、backup、status、apply、restore | 校验摘要、六key、四表数量、ID唯一／归属；篡改拒绝 |
| 正式连接 | 固定 `/Users/congming/.goldenshare/dagster_home/dagster.yaml` 的既有storage URL | 维护CLI建连接时读取，不新增env／Settings项 | 只允许本机5432、数据库 `goldenshare_dagster`，先断言连接身份；不输出密码 |
| 恢复副本 | `/Users/congming/.goldenshare/dagster_backups/retired_assets_20261027_7bbe2a48/rows.json.gz` | backup写、其余模式只读 | 目录0700、文件0600；正式Lake之外；同名已有副本不覆盖 |
| 隔离连接 | 测试显式指定 `/private/tmp` 下独占Unix socket、55439、`dg_retired_verify` | 仅隔离测试传给库函数；正式CLI没有任意DSN开关 | 实际data_directory在临时目录、listen_addresses为空、inet_server_addr为NULL |
| statement／transaction时限 | 维护工具内固定单SQL15秒、写事务45秒 | 只约束本次维护连接；PG18原生超时兜底 | 超时整笔回滚，不改日常job限制 |
| 写入保护 | 四表 `SHARE ROW EXCLUSIVE NOWAIT` | apply／restore事务先拿锁 | 已有写入占用则立即停止；普通SELECT继续，新DML短暂等待 |
| 验证报告 | report目录显式文件；含工具／manifest／backup摘要 | apply入口读取隔离验证成功凭据 | 任一摘要不匹配或验证未通过禁止正式apply |

不新增产品配置、数据库配置表或后台开关。操作参数、固定默认、所有消费者及生效方式均在此表，没有独立散落的环境配置。

### 7.3 备份与恢复安排

1. `backup` 在正式PG只读REPEATABLE READ事务，按冻结ID读取四表**全列原行**。使用真实 `to_jsonb(row)` 保留原文、NULL、整数及时间微秒；不取整个event_logs，不读行情或Lake。补取四表的小型schema：实际列顺序／format_type／NULL／默认值／serial归属、约束、索引及触发器／rule信息。
   写副本前用这些已读取行逐项核原清单投影：run／事件类型／正文真实资产归属、检查名／状态／关联ID、标签和值、最近物化ID／时间及wipe身份。SQL owner未变但正文改成现行资产也拒绝，不能把变化后的行直接备份再删除。
2. 四表正文和schema组成完整副本，逐表canonical SHA-256绑定内容、列和ID；外层绑定manifest摘要。gzip写临时文件、flush／fsync、同目录原子更名，再完整解压读回校验摘要、行数和ID；最后保存压缩文件SHA-256及小型receipt。只在这个本机持久目录保存正文，不提交Git、不自动删除，保留到管理员确认无需恢复。
3. 恢复副本还记录九run／23 run tags／五snapshots／319普通事件的ID及服务端内容摘要，用于验收保留事实；不导出这些保留对象的完整正文。
4. 正式apply拿锁后，再按冻结ID读取四表全行，逐表摘要必须等于已验证副本。ID相同而正文／缓存／状态变化也拒绝，不只比较行数或长度。
5. `restore_backup_rows` 只在四表目标ID全部缺失时，按原列、原ID单事务插入；全部已存在且内容相同则识别已恢复；部分存在或同ID内容不同则拒绝，不做UPSERT、覆盖、ignore、TRUNCATE或sequence reset。隔离验证必须真实执行该恢复方法并逐列读回一致。
6. 正式恢复命令保留在工具中，但只有另行明确恢复指令才执行；本次正式成功后只保留副本，不往回插旧历史。提交前异常靠PG rollback恢复，提交结果不明确先用只读一致快照确认，不自动重跑或恢复。

### 7.4 正式删除的事务与并发

采用一次短事务处理13,152行。仅锁冻结行不足以阻止并发插入新引用，正式库又没有关联外键，因此四表写入保护不可省略。备份压缩、隔离集群与报告写盘均在锁外进行。

1. 正式apply前校验维护工具代码摘要、通过的隔离报告和完整副本；读正式GraphQL query，核180个现行定义及无六key依赖，并核当前registry。两种依据有冲突则停止，不reload或启动job。
2. 建READ COMMITTED写事务，首段断言正式库身份、无活动／排队run；四表固定顺序获得 `SHARE ROW EXCLUSIVE NOWAIT`。只锁四张DG元数据表，不锁业务库／Lake。普通读继续；若有写入者已经占用，不排队，不终止其他事务。
3. 锁后核全列副本、按六key列出的四表ID集合完整等于清单。原始检查按实际JSON资产路径取归属，不能漏NULL SQL asset_key。检查全部非目标检查索引、标签、最近物化缓存反向引用；物化正文的六个精确上游标签及原始检查target ID按聚合重新核。复用已核JSON合同，不重新审计市场数据。
4. 核保留180条资产索引和九run等保护对象的ID／内容摘要。依次DELETE标签8、检查5,601、事件7,537、资产索引6，只用固定表名及参数绑定的冻结ID；逐表RETURNING ID集合必须精确相等。无数据库非内部触发器、rule、事件相关FK和schema变化方可执行。
5. 再核六key四表目标残留为0、保留对象摘要不变、无新活动run，提交。三个旧wipe事件在同一事务内随专属事件删除，最后删索引；事务外看不到“标记已删、旧正文还在”的中间状态。
6. 任意失败或45秒事务超时均rollback。工具只执行一次，不自动重试。首尾检查发现新增活动run则回滚退出；最后一次检查之后仍可能有新任务开始，其四表元数据写入短暂等待锁释放后继续。不能承诺两次查询捕获整个事务期间的每一次启动，也不为此加锁runs或关闭sensor。
7. 事务结束立即以单个只读REPEATABLE READ快照确认四表冻结ID状态；全在且内容匹配＝未删除、全无＝已删除、其余＝停止调查。最后GraphQL目录应为180、资产索引180，现行定义集合不变。若日常写入导致保留资产内容正常变化，不凭此误报数据损坏；事务内不变和写入白名单是“不误删”的依据。

提交前先落盘执行意图，commit返回后先落盘提交事实，再做status／GraphQL；提交不明也先保存原错误。收尾查询失败另记confirmation_error，保留已提交事实，不用自动重试或恢复掩盖问题。归属为NULL的反向检查／原始检查按“非目标或不明归属”计入阻断，不能被SQL三值逻辑漏过。报告路径不得覆盖manifest、副本、隔离证据或备份receipt；正式DSN不接受可覆盖地址／库名的query参数。

锁内预计10—25秒（上轮两个正文引用计数合计约12.6秒）；45秒是失败回滚界限，不是日常任务限制。新元数据写入可能短暂等待，这一影响已明确；已有写入／活动任务时退出，不宣称“完全无锁”。

### 7.5 隔离验证及夹具依据

使用已有 `/opt/homebrew/opt/postgresql@18/bin` 的18.4版本，`initdb` 创建 `/private/tmp/dg-retired-pg.*` 独占data／socket，禁TCP，仅本机用户可读写。测试结束只关闭此临时集群并删除该独占目录；绝不对正式数据库跑测试或初始化instance。

测试输入以真实四表schema及本次完整副本为依据；独立字面断言四表7,537／5,601／8／6，以及表2各项数量，不调用待测函数生成expected。正常现行名称使用 `gold_market_major_indices_daily` 等前缀相近资产，控制行含共享空run_id、NULL、带微秒时间。合成控制行只证明范围保护，不声称模拟完整日常DG系统。

| 硬口径 | 代码落点 | 正向／反向验收 |
| --- | --- | --- |
| 只处理精确六key／四表ID | `load_manifest`、`assert_owned_scope` | 真清单通过；改key、ID、摘要、数量拒绝 |
| 恢复副本真实完整且不覆盖 | `create_backup`、`load_backup` | gzip读回、全列还原通过；损坏、副本不符拒绝 |
| 当前资产不被删 | `protected_state`、`delete_frozen_rows` | 范围外四表控制行、相近名称和空run_id保留 |
| 新反向引用拒绝；正常变化不误拦 | `assert_references_clear` | 注入其他资产检查／tag／正文指针拒绝；无旧指针的新正常事件和当前名称通过 |
| 单事务及NOWAIT保护 | `apply_backup` | 正常精确删除；每张表删除后抛异常、客户端断开均完整rollback；锁被占用立即拒绝 |
| 全列内容绑定 | `assert_rows_match_backup` | 同ID改正文或NULL／日期／缓存拒绝 |
| 不确定提交安全确认 | `classify_state` | 全在／全无／部分／内容改变分别识别；同一只读快照 |
| 原ID恢复且不覆盖／重置序列 | `restore_backup_rows` | 真实备份删除后恢复、全列一致、重复恢复识别；部分／冲突拒绝、序列不回退 |
| 仅本地指定实例、测试不会误连正式 | `connect_formal`、测试连接前置检查 | 正式身份正确；错误库／主机／测试datadir拒绝 |

隔离成功凭据记录 `status=passed`、manifest SHA、backup SHA和执行模块SHA，正式apply必须同时匹配。隔离测试运行一次完整备份恢复→删除→恢复，边界用小型真实合同控制行及事务回滚，避免反复复制全库或读取行情。

### 7.6 读写预算与命令

| 阶段 | 范围／预计开销 |
| --- | --- |
| 正式备份 | 13,152全列行一次，正文约19.93MiB，含schema／结构／缓存预算64MiB读取、64MiB未压缩文件；内存预算256MiB |
| 正式写入 | 13,152 DELETE一次；锁内全列复核一次＋必要反向引用计数，后者是DG元数据聚合，预计沿用已知约12.6秒；WAL预算256MiB，事务上限45秒 |
| 提交后验收／不确定提交确认 | 精确四表ID一次一致快照，最多13,152行；提交后为空，不需要重读所有日志 |
| 必要正式恢复（仅经指令） | 原13,152行INSERT一次、读回一次，预计正文读／写各约20MiB＋索引／WAL256MiB；不重置序列 |
| 隔离测试 | 独占PG额外空间1GiB，真实备份导入／删／还原及必要反例，预算5分钟；完成后清理临时cluster |
| 保留副本 | 只保留压缩恢复文件、receipt、schema／校验摘要，目录预算128MiB；不备份正式Lake或整数据库 |

以上是本次执行设计预算，实际结果写第8节；没有把全文事件扫描、行情审计或自动重跑作为成本项。

工作目录固定 `/Users/congming/github/goldenshare/lake_console/orchestrator`，命令均使用 `.venv/bin/python3 -B`：

```text
-m orchestrator.maintenance.retired_asset_history backup --manifest <本报告manifest绝对路径> --backup <上述rows.json.gz> --report <本报告backup-receipt.json>
-m pytest -q tests/test_retired_asset_history.py
-m orchestrator.maintenance.retired_asset_history apply --manifest <同一manifest> --backup <同一副本> --evidence <本报告isolation-validation.json> --confirm-manifest 7bbe2a485f3ea2e7d719a8b44186d8c23983d1d689bc67071c85882a2b7896a0 --report <本报告execution-result.json>
异常提交结果确认才另用：-m orchestrator.maintenance.retired_asset_history status --manifest <同一manifest> --backup <同一副本> --report <本报告post-delete-verification.json>
```

正常apply内部调用同一status实现一次提交后确认，并写入execution-result，不再单独重复查询四表。

### 7.7 本步审计及开始条件

正式写入前必须：文档／LLD完整；模块及测试通过独立审计；真实备份落盘并读回；隔离PG删／恢复通过；代码／副本／manifest摘要相同；正式当前定义、ID、引用、schema和无活动run均通过。任一未完成不能进入apply。用户本轮授权不被解释为可跳过这些条件。

## 8. 执行记录与最终结果

2026-10-27 16:03:52，限定范围只读备份一次完成并读回一致，正式数据仍未删除。恢复副本位于第7.2节指定持久目录，未压缩26,822,791字节，gzip 556,379字节；压缩SHA-256为 `1d297b37ab652e7f50c5be2bb5a8a310deeef222b086725e5fe02eb7e805b14e`。四表13,152行、保留180资产索引／9run／23run tags／5snapshots／319普通事件数量均与计划一致。实际PG为18.4，已补全真实schema。见 [backup-receipt.json](backup-receipt.json)。

隔离验证完成：18项测试全部通过，19.56秒；真实PG综合验证调用17.16秒。验证使用上述真实副本和完整四表schema，覆盖12类反向引用／前置条件拒绝、四表每一步删除故障、客户端断开、NOWAIT占用拒绝、一致快照、部分／冲突恢复拒绝、正常删除和原ID全列恢复、重复恢复识别与序列保持。两次拒绝恢复后均独立核非目标控制行没有变化。临时cluster已停止并删除；[isolation-validation.json](isolation-validation.json)绑定manifest／副本／代码／测试／receipt摘要。另补DSN query参数和fragment拒绝检查，见 [pre-apply-validator-checks.json](pre-apply-validator-checks.json)，不重新运行完整隔离集群。

正式apply前只读检查无活动任务，131个instigator开关摘要已记录在 [execution-preflight.json](execution-preflight.json)。代码Ruff默认规则通过，独立源码／测试审计问题已修正并由实际隔离验证覆盖。

2026-10-27 16:13:28开始正式apply，16:13:53提交并确认完成。一次事务24.411秒，未失败、重跑或恢复；反向检查索引、标签、缓存、原始检查target、物化上游指针计数均为0。实际删除事件7,537、检查5,601、标签8、资产索引6，严格等于原清单。见 [execution-result.json](execution-result.json)。

提交后同一只读快照确认四表冻结ID全部消失，九条run／23条run tags／五snapshots／319条普通事件与备份中的摘要相同；事务内180条现行资产索引内容摘要也未变，提交后其名称集合与180项当前定义相同。必要目录验收实际183→180，六个旧key不再出现，见 [post-delete-inventory.json](post-delete-inventory.json)。

16:15:48收尾核131个调度开关，与执行前摘要完全相同；无活动任务，六个旧资产索引为0，见 [post-cleanup-runtime.json](post-cleanup-runtime.json)。本工具没有写cursor、启停sensor、启动job、修改业务数据或Lake文件；没有做市场数据全局审计、数据库收缩或序列重置。

当前只保留必要恢复副本（gzip约0.53MiB）、receipt、执行及验证证据；隔离PG临时集群已清理，未留下运行中的测试数据库。副本未自动删除，后续需管理员确认后再清理；不在Dagster目录中展示。最终机器汇总见 [completion-summary.json](completion-summary.json)。本次任务完成，代码、测试与执行证据随文档收尾一起提交；未部署其他服务。

## 9. 文档收尾、临时文件清理与提交

管理员已要求收尾、清理战场并提交本轮修改。本步只整理本报告、清理已无运行用途的本轮临时文件，再按明确文件清单提交；不再访问正式数据库，不重跑删除、恢复、job或大范围审计。

清理对象与判断依据：

- `/private/tmp/dg-retired-assets-review-20261027`：6个首次审计临时文件，其中5个与本报告归档逐字一致，`inventory.literal`解析后与归档JSON相同。
- `/private/tmp/dg-retired-assets-relations-20261027`：7个第二轮审计临时JSON，均与本报告归档逐字一致。
- `/private/tmp/dg_retired_events_relations_20261027.py`、`/private/tmp/dg_retired_relations_phase2_20261027.py`至`phase6_20261027.py`：6个一次性只读采集脚本，已被归档证据和维护工具覆盖，没有现行调用方。

保留完整报告目录、固定manifest、隔离验证及正式执行凭据、维护模块和测试。持久恢复副本仍为第7.2节的 `rows.json.gz`，不纳入Git、不删除；本步只检查文件存在、权限及压缩摘要，不解压重读历史正文。

删除前核路径不是symlink、目录内没有新增对象、归档副本一致；任一不符则停止，不扩大范围。只删除上述19个文件及两个清空后的临时目录，不清理其他任务目录、共享缓存、正式服务或数据。清理中断后依据实际剩余文件继续，已删除文件不需恢复；必要证据均已归档。文件总量不足10MiB，验证仅为本机文件哈希和小型文档检查。

提交范围固定为 `orchestrator/maintenance/__init__.py`、`orchestrator/maintenance/retired_asset_history.py`、`tests/test_retired_asset_history.py`（均相对本工程），以及本报告目录逐文件列出的文档和证据。暂存前后对照清单，禁止纳入其他工作区修改；只在当前 `dev-interface` 提交，不推送或部署。源代码和测试摘要仍绑定已通过的18项验证，本步只复用既有结果并补文档／Ruff／暂存差异检查，不重复启动隔离PG。

实际清理结果、保留文件及提交清单见 [cleanup-receipt.json](cleanup-receipt.json)。
