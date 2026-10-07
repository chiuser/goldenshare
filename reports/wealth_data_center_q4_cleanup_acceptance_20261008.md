# Q4 获准清理与收尾（2026-10-08）

用户明确指令：“提交代码，授权清理。”本轮先提交Q4代码、文档和既有验收证据（`fa08d45d`），再按网页LLD §22.10、§26执行清理。操作限于本机；不推送、不部署Prod、不运行DG任务。原[2026-10-07报告](wealth_data_center_q4_acceptance_20261007.md)保留当时未授权清理的历史状态，本记录为最新收尾事实。

## 执行与范围

- [重新PLAN](wealth_data_center_q4_cleanup_plan_20261008.jsonl)的7个精确路径、5源SHA和总大小与此前待授权清单一致。SHM读协调时间变化未改变业务源摘要。目标仍为既有本机PG `goldenshare_lake_meta.announcement_archive`；4归档ready、48个迁移checkpoint完成。
- [显式清理](wealth_data_center_q4_cleanup_20261008.jsonl)退出码0，进度单调1—7，终态`cleaned`，删除4份downloads.sqlite、1份catalog.sqlite及catalog的WAL/SHM，共343961600字节，约328.03MiB。未删除任何父目录。取得原锁、复核源摘要和关闭连接后逐文件unlink/fsync；没有备份、安装或卸载。
- [前置记录](wealth_data_center_q4_cleanup_before_20261008.json)与[清理后记录](wealth_data_center_q4_cleanup_after_20261008.json)证明7个旧文件均已不存在；4归档及每归档10张台账关联表计数一致、成功文件共378。默认归档仍为34188文件任务，其中363成功/33825待下载。
- 10个既有锁/归档绑定文件的物理身份与内容保留；正式公告Raw共2471个Parquet的路径、大小、mtime清单摘要一致，3个代表文件的SHA一致。共享Python SQLite、扩展库和CodeGraph数据库仍存在，未卸载。Raw清单一致性只覆盖本轮清理前后，不等于全历史数据完整性验收。

## 清理后独立读回

[正式维护CLI](wealth_data_center_q4_ledger_summary_20261008.json)从PG读取默认363个成功文件，无旧SQLite依赖。[378份PDF逐文件核验](wealth_data_center_q4_readback_20261008.json)全部大小与SHA匹配，且artifact/path/size/hash清单与清理前2026-10-07读回一致；只读外盘，零源站HTTP、零PDF/Raw写入。临时核验脚本最初误将物理状态断言写为succeeded，已停止该只读进程并按现有verify_one的matched语义重跑；正式代码与数据不受影响。

[Web检查](wealth_data_center_q4_web_health_20261008.json)：原PID90795继续监听127.0.0.1:8000，公告路由SPA壳GET返回200。该检查不等于真实登录页面验收；没有修改正式认证，也没有把无登录凭证的访问当作GUI验收。

## 代码、文档与边界

本轮代码提交包含ArchiveCleanup、迁移CLI显式互斥动作及专项测试；既有联合370项、迁移/清理61项和后续PG专项12项通过，详见前日报告。本轮提交后只执行获准工具及只读验收，不修改运行代码，不重复宣称新的全量回归。收尾同步原技术方案、PDF LLD、网页LLD/技术方案、产品进度和架构快照。

CodeGraph开发影响面已覆盖ArchiveMigration/ArchiveCleanup、迁移CLI及测试消费者；本轮sync/status确认索引当前。App/普通执行器无旧源依赖，子系统边界、依赖矩阵、API、Figma及DG/Prod数据集合同均不变。文件清理不写PG、不清空业务表，也不把旧源恢复为运行后端。

**Q1—Q4本机查询与PG统一存储改造完成。** 后续由用户review实际页面；DG日常稳定性、最新公告日期覆盖及全历史数据质量继续独立验收。本轮不改默认查询日期、不自动补齐DG或全量下载PDF。旧源已清理，原迁移/清理命令不再作为日常重复命令；正常运行及查询使用既有Web和两个CLI。
