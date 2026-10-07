# Q4 正式迁移、启用与独立验收

本文保留2026-10-07阶段证据；最新提交与获准清理完成状态见文末及[2026-10-08收尾报告](wealth_data_center_q4_cleanup_acceptance_20261008.md)。

依据：数据中心 LLD §22.5、22.10、22.11。Q3已提交b4c590fd。用户授权推进Q4；正式迁移/读回/统一启用及小范围验收在本阶段执行，旧SQLite清理按LLD另行批准。

## 硬口径与代码

- 仅MigrationInventory.local列出的4下载台账+1catalog：Q1迁移器/schema/只读来源完整映射，默认PLAN不写；500行短事务和checkpoint，源变化阻断，不备份、不升级SQLite。
- 停止公告Web/CLI写者：CLI require_writers_stopped；正常停止原Web8000，无强杀。既存本机PG角色congming、loopback:5432/goldenshare_lake_meta，独立announcement_archive；不触碰DG/主Alembic/旧public表。
- 读回全部字段/摘要，4归档隔离：正式APPLY后相同工具幂等重放，随后只读PG及378份成功PDF物理核验；原整数游标/序列保留。
- 统一启用：只在既有.env.web.local新增ANNOUNCEMENT_ARCHIVE_DATABASE_URL，保留远程DATABASE_URL及本地模块开关；Web/下载CLI/维护CLI共用。没有新增配置项、安装或卸载数据库。
- 清理：ArchiveCleanup + CLI互斥的--cleanup-plan/--cleanup；ready、完整checkpoint/source SHA/digest、冷源和关闭连接核验，取得原锁后只unlink精确文件；PG不写、保留binding/锁/PDF/Raw/共享库。正式--cleanup尚未执行。

## 运行前性能预算

| 范围 | 规模/预算 | 拒绝条件 |
| --- | --- | --- |
| 正式迁移 | 102692台账关联行，236个≤500行批次；目标空间保守165359616字节 | 单SQL>4秒、锁>500ms、源变更/活动run/冲突直接阻断；估算>5分钟先定位 |
| 同机校准 | 临时102026行、231批18.048秒；最大SQL1.3466秒、RSS227.75MiB、FD22 | 不外推清OS缓存或源站性能 |
| 真实来源API | 固定30日、155日002245.SZ、155日全公司/已下载/未下载；每场景独立进程，冷GET+5次暖GET | GET上界5秒、SQL4秒、RSS512MiB；只读Raw、有界FD≤32，不截短范围、不加全量副本 |
| 独立CLI小范围 | 2026-07-26、已有dc5验收根，实际5条/5文件；请求间隔3秒 | 不扩日期/公司范围；不自动全量下载 |

## 正式操作与读回

1. [只读PLAN](wealth_data_center_q4_plan_20261007.jsonl)：5精确来源、无目标schema/冲突，102692关联表行/236批，catalog只迁13查询+2预览控制结果。原Web8000正常SIGTERM停止，无强杀其它进程；本轮没有运行DG命令。
2. [正式APPLY](wealth_data_center_q4_apply_20261007.jsonl)成功；[相同工具幂等重放](wealth_data_center_q4_replay_20261007.jsonl)再次成功，逐批完整业务列比对、checkpoint完成与4归档ready，零源站HTTP。重放20.495秒，最大SQL0.0922秒，SQL1439次，进程FD29/RSS174.80MiB，见[指标](wealth_data_center_q4_replay_metrics_20261007.json)。不声称测量清OS缓存，也不把重放时间冒充首次APPLY耗时。
3. [PG/物理读回](wealth_data_center_q4_readback_20261007.json)：48个checkpoint；默认363 PDF、三个验收目录各5 PDF全部size/hash匹配，共378份，用时97.91秒；逐文件检查，不复制PDF。runs/source_records序列下一个值分别6/34189，大于导入最大值。SQLite主文件和WAL指纹保留，旧schema版本未升级；SHM是共享读协调文件，不作为业务摘要。
4. 配置只新增既有字段ANNOUNCEMENT_ARCHIVE_DATABASE_URL到ignored .env.web.local；没有改远程DATABASE_URL、DGenv或主默认配置。Web8000恢复，PID90795，日志/private/tmp/goldenshare_q4_web_20261007.log；登录页/static正常，真实认证继续生效，未取得真实登录凭证时不伪造用户登录验收。
5. [维护CLI概况](wealth_data_center_q4_ledger_summary_20261007.json)：默认34188文件任务中363 succeeded/33825 pending，storage为postgresql。 [独立CLI日期验收](wealth_data_center_q4_cli_smoke_20261007.jsonl)：已有dc5根，2026-07-26实际5条/5文件全部skipped复用、failed=0，PG中生成正常新run而不修改原SQLite；无新attempt/HTTP，不扩大主归档。前置静态只读尝试在受限环境无法取得diskutil卷信息；随后有完整权限的正常CLI完成源/卷校验。成功事实以实际CLI封存记录为准。

## 真实来源与已迁移状态的API验收

[五场景汇总](wealth_data_center_q4_api_profile_20261007.json)。每场景独立冷进程，首次完整GET+5次暖GET；P95保守用六次最大值，未清OS缓存。使用正式PG和原Raw，真实App组合/公告路由，只在独立测试进程覆盖认证依赖；真实Web认证和Prod账户不变。写入仅是短期查询/状态控制事实，未写Raw/PDF或访问PDF站点。

| 场景 | 返回总公告 | 准备秒 | 六次GET最大秒 | 公告FD峰值 | RSS峰值MiB |
| --- | ---: | ---: | ---: | ---: | ---: |
| 固定30日，截至2026-10-06 | 28566 | 2.348 | 1.286 | 30 | 380.48 |
| 155日，002245.SZ | 36 | 3.193 | 1.361 | 32 | 443.94 |
| 155日，全公司 | 210602 | 3.100 | 0.910 | 32 | 379.92 |
| 同范围，已下载 | 363 | 5.261 | 2.189 | 32 | 509.81 |
| 同范围，未下载 | 210239 | 5.795 | 1.100 | 32 | 358.69 |

155日为2026-05-04—10-05，共155文件/149行组/210602源行；30日为9-07—10-06，共30文件/24行组/28566源行。最大PG/DuckDB SQL合并约0.167秒。总进程FD峰值19—50包含服务/SQL/目录等；公告Parquet FD峰值30/32，不能混用两种定义。准备超5秒时始终202输出阶段/扫描进度；终态GET符合5秒目标。已下载场景RSS接近512MiB门槛，仍不能外推全历史性能。

**当前默认日期实际边界：** context归档/来源/台账均ready，observedAnnDate=2026-10-06；当前默认9-08—10-07包含尚未落地的10-07。 [当日默认负例](wealth_data_center_q4_current_default_20261007.json)真实进入HTTP200/pageState=error/DC_SOURCE_UNAVAILABLE终态，不继续轮询、不伪造缺日零行；没有擅改默认日期或截短查询。当前人工review可将截止日选10-06；DG更新/当日缺日属独立事项，本轮未触发补齐。

## 开发与回归

新增Ops ArchiveCleanup、CLI --cleanup-plan/--cleanup互斥入口，测试test_announcement_pg_cleanup；原生runtime import护栏同步允许显式迁移/清理工具独立读取Legacy，App/执行器仍禁止旧源import。正常容量回归报告现在写pytest临时目录，避免覆盖已提交Q3历史证据。

迁移/清理专项61项通过；最终联合370项通过（158.15秒），含运行—取消—退出—续跑、PG隔离/只读/观察失败、文件恢复、API和架构护栏；容量报告路径调整后PG专项12项再次通过。只有原有Starlette/httpx弃用提示；没有安装依赖。compileall、docs integrity、diff check通过。前端代码/产品/Figma不变，沿用Q3已通过的1134前端测试与GUI证据，本轮新增证据不冒充真实登录GUI验收。

CodeGraph query/impact覆盖ArchiveMigration、CLI、ArchiveCleanup及迁移/清理测试；sync/status为up to date。SQL字段/锁、Protocol动态装配及实际API另外按源码、隔离PG和正式有限窗口核验；依赖矩阵不变，DG/Prod数据集合同无修改。

## 旧文件清理待单独批准

[最新清理PLAN](wealth_data_center_q4_cleanup_plan_20261007.jsonl)核验PGready、完整迁移receipt、源SHA、schema/外盘、lsof无其它连接。5份数据库与2个伴随文件合计343961600字节，约328.03MiB：


- `/Users/congming/Library/Application Support/Goldenshare/announcement-download/6ae38d3a5436526b8e6a941086bda5ce366397699eea6d8d59fd598817d7f4f3/downloads.sqlite`（54870016字节）
- `/Users/congming/Library/Application Support/Goldenshare/announcement-download/ad609a131cad03f5d8de8e09cab84ded264842358993a512f2b289476bfc6c4c/downloads.sqlite`（65536字节）
- `/Users/congming/Library/Application Support/Goldenshare/announcement-download/bb28fc7eca37cbf2a513cc48295d82efad9a55fe023853902181bfeabb24bf9f/downloads.sqlite`（73728字节）
- `/Users/congming/Library/Application Support/Goldenshare/announcement-download/fe6ce589e8fe2f1d6ad0d572e7e194204edef2daa99bc7a555efec1d7f950013/downloads.sqlite`（110592字节）
- `/Users/congming/Library/Application Support/Goldenshare/announcement-catalog/e04b7c92bfa1082f05a370b0504bdfcb29f66fb352fbe82a904a71df1db7b79a/catalog.sqlite-shm`（32768字节）
- `/Users/congming/Library/Application Support/Goldenshare/announcement-catalog/e04b7c92bfa1082f05a370b0504bdfcb29f66fb352fbe82a904a71df1db7b79a/catalog.sqlite-wal`（0字节）
- `/Users/congming/Library/Application Support/Goldenshare/announcement-catalog/e04b7c92bfa1082f05a370b0504bdfcb29f66fb352fbe82a904a71df1db7b79a/catalog.sqlite`（288808960字节）

正式--cleanup尚未执行，没有删除业务表、旧文件、PDF或Raw，没有卸载共享SQLite。原本机/外盘锁、web-archive.json、共享Python/系统/CodeGraph SQLite以及其它数据库均不在白名单。执行前再次核验，任何不一致阻断；若删除失败，PG继续唯一运行存储，不回滚、不回退，不把部分完成标为全清理成功。

下一步仅是管理员单独批准这7个文件的清理。Q4代码/文档改动尚未提交，已启用本地服务；清理完成前不将整个Q4标为全部完成。DG日常稳定性、全历史数据质量及用户真实登录页面review继续按原独立验收边界推进。


## 2026-10-08 后续收尾

本报告正文保留2026-10-07当时的状态。此后用户明确授权“提交代码，授权清理”，Q4代码已提交fa08d45d，7个旧文件已按重核清单删除；4归档/378份PDF和PG台账均读回正常，本机Q4完成。[2026-10-08收尾报告](wealth_data_center_q4_cleanup_acceptance_20261008.md)为最新执行与验证依据。
