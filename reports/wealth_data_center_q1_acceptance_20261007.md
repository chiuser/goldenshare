# 公告查询与存储修订 Q1 验收

日期：2026-10-07。依据：用户“提交修改，然后开始推进Q1”和[LLD §22](../wealth/docs/pages/data-center/data-center-announcements-low-level-design-v1.md)。此前公告review修正、只读审计和修订文档已提交`66263bb3`。Q1开发与隔离验收完成，新增代码尚未提交；Q2—Q4未实施。

本次只使用现有解释器/PG18二进制，在`/private/tmp`建立独立临时PG实例与测试库，使用临时SQLite及模拟外盘。没有连接/写入正式metadata库、停止用户Web/DG、修改env、迁移/清理原台账、请求源站PDF或安装/卸载软件。原页面仍使用旧链路，列表速度改进属于Q2。

## 目标、范围与影响

Q1交付本地PG配置/独立连接、静态schema v1、归档DAO/短事务以及只读PLAN、显式APPLY、checkpoint/续跑工具。Foundation保存底层数据和合同，Ops组织迁移，`src/scripts`只解析命令和装配，不改变依赖矩阵。

CodeGraph使用`codegraph_explore`追踪Ledger/schema、App工厂、Catalog、维护查询及CLI整数游标消费者，`codegraph_impact Settings`核对配置影响；随后核验当前SQL、卷/锁、通用DAO及测试。BaseDAO的覆盖/忽略冲突语义不满足完整行对比，因此本次DAO使用明确复合键及全列读回。开发后`codegraph sync/status`已同步。现行App/API/前端尚未接入PG，正式集成边界由Q2/Q3验收，不把新迁移工具当作已经切换的运行链路。

改动文件：

- 配置：[Settings](../src/foundation/config/settings.py)、[ArchiveDatabasePolicy](../src/foundation/config/announcement_archive.py)；默认空DSN，沿用env-file优先级，连接预算集中管理。
- PG底座：[独立连接](../src/foundation/dao/announcement_archive/pg_database.py)、[结构检查](../src/foundation/dao/announcement_archive/pg_schema.py)、[归档DAO](../src/foundation/dao/announcement_archive/pg_archive.py)。
- 静态合同：[001_initial.sql](../src/foundation/dao/announcement_archive/pg_migrations/001_initial.sql)、[列合同](../src/foundation/dao/announcement_archive/pg_migrations/001_initial_contract.json)；[pyproject.toml](../pyproject.toml)仅增加package data，不增加依赖。
- 迁移：[只读源](../src/foundation/clients/announcement_archive/migration_source.py)、[运营协调器](../src/ops/runtime/announcement_archive/migration.py)、[CLI](../src/scripts/migrate_announcement_archive.py)。
- 测试：[Q1测试](../tests/test_announcement_pg_migration.py)、[子进程fixture](../tests/fixtures/announcement_pg_migration_runner.py)；技术方案/LLD、产品进度与Wealth索引同步。

## 硬口径对账

| 约束 | 落点 | 验收证据 |
| --- | --- | --- |
| 只用固定loopback/5432/metadata库；不回退主DATABASE_URL | guarded_url/独立engine/configured_archive_database | 空DSN、远程、错误库、端口、driver及query覆盖均在创建pool前拒绝；Prod/关闭模块零pool；文件配置优先级和repr脱敏 |
| 不自动建表、不跑根Alembic、不碰DG/旧public表 | 显式install_schema；只读PLAN | 未安装schema的PLAN不建schema；缺列/主键/索引/default/未知版本拒绝、不修复；4张同名旧public表逐表保持原值，零Alembic/旧表SQL |
| 每个归档独立保存状态 | archive_id复合PK/唯一键/FK和DAO | 四归档共用5个artifact键和相同run/command键，状态不同且各自读回；跨归档不会合并或覆盖 |
| schema2/3全部原值保存；原JSON/NULL/default和游标不变 | 静态DDL合同、LegacyLedger.map_row | 全列集合/类型/default/NULL比对；大整数、失败、未完成、冷却、owner/session/attempt、原JSON空白及可空关联读回；rowid→row_seq保留7/20等缺口，序列推进超旧最大值 |
| 全部4份台账迁移，catalog不复制公告/公司明细 | 精确Inventory；旧查询/预览映射 | 四份成功迁移；旧control ID/条件/统计保持且明确过期；catalog_records/company_sources无目标表，copied_metadata_rows=0 |
| 每批≤500、数据/checkpoint原子提交、完整行冲突拒绝 | copy_table/insert_identical/verify_identical | 1001行取消到500读回；checkpoint写失败当前批全部回滚、前序成果仍在；同值重放成功、业务/控制行冲突在PLAN拒绝并不覆盖 |
| 进程退出/取消保留已提交批，源变更拒绝续接 | WAL-aware fingerprint/持久checkpoint | 真子进程os._exit(77)、SIGINT(130)之后续跑到1001；完成量单调；主文件变更、热journal/缺WAL共享内存守卫；真实WAL新增标题进入PG且源版本/摘要不变 |
| 活动run/checking阻断；终态历史owner原样保存 | LegacyLedger验证、原双锁/卷检查 | schema1、非终态、活动slot、checking、request-in-flight均在DDL前拒绝；历史owner成功导入；PLAN不创建锁；APPLY原本机/外盘两把锁竞争均拒绝，换卷拒绝 |
| 短事务/预算/归档ready | ArchiveDatabasePolicy/DAO/收尾协议 | pool耗尽、500ms锁竞争、statement timeout、权限不足明确失败；importing不可读；收尾expiry中断可恢复，最终摘要/ready原子发布；本批事务异常不损坏已提交表行 |
| 不改变API/原CLI和下载行为；不执行正式清理 | 新独立工具，旧消费者未接线 | 既有公告联合回归通过；`--help`与非法DSN参数验证；没有`--cleanup`或启动自动迁移入口，不增加SQLite兼容连接壳 |

所有源/目标行按原rowid顺序、类型明确的规范对象流式形成SHA256链；metadata等TEXT原字符串参与摘要，不把JSON重新格式化。checkpoint保存已提交前缀摘要，源摘要覆盖主SQLite与存在的WAL，不主动checkpoint/升级源文件。NULL与空字符串不混同。源读取及目标核验均按500行，不把范围数据长期放内存。

临时控制结果的期限收尾也是每批500行；归档仍处importing时收尾崩溃可重置期限，业务历史行不重写。最终摘要与ready同事务发布。旧preview没有创建时间，使用schema安装记录的迁移时间明确补齐；其原ID/统计保留，关联缺失的原历史ID也不丢弃。正式控制GC由Q2承接。

## 验证结果

- Q1最终完整套件43项通过，包含双锁/卷身份、热journal、缺WAL共享文件和符号链接负例。日志：本机临时`/private/tmp/announcement_q1_test_results.txt`；摘要及实现文件指纹见[机器证据](wealth_data_center_q1_acceptance_20261007.json)。
- 公告联合回归334项通过（包含当时39项Q1）：archive runtime、下载CLI/DG读取适配、维护台账、Catalog、列表与下载API。日志：`/private/tmp/announcement_q1_regression_results.txt`。只有既有Starlette TestClient弃用警告，没有自动安装依赖。
- Foundation数据合同门禁170项通过，依赖/legacy护栏16项通过，`ingestion-lint-definitions`通过。
- 新Python模块compileall、CLI help、git diff检查通过；文档引用检查单独执行，不替代SQL/进程恢复验收。

性能为同机临时实例、全新目标库首次PLAN+APPLY，不清OS缓存。四归档各8500 source/file/run-file关系行，共102,026表行、231数据批；没有请求Tushare或PDF源站。最终Q1测试测量：

| 指标 | 结果 |
| --- | --- |
| 总耗时 | 18.500秒 |
| 最慢SQL | 1.3560秒 |
| SQL调用数 | 1082，含DDL/结构/读回/检查点/序列及控制收尾 |
| Q1测试进程RSS峰值 | 227.16MiB |
| 同进程FD峰值 | 23，包含SQLite/PG及测试输出FD；非Parquet读取FD |
| 源站请求 | 0 |

联合回归进程还加载API/下载模块，对同规模样本另测18.973秒、最慢SQL1.2594秒、RSS318.52MiB。两次均不代表已清文件缓存或真实公告页面API P95；Q2还须完成完整请求和来源一致性性能验收。

## 使用与后续边界

工具默认只读PLAN，DSN只来自`ANNOUNCEMENT_ARCHIVE_DATABASE_URL`，没有DSN命令行参数；显式`--apply`要求公告Web/CLI写者停止，检查原锁且保留原SQLite/PDF。失败返回3，SIGINT返回130并保留已提交批。该工具本轮未对正式资源运行。

Q2下一步替换Catalog列表/公司/预览/范围复核，直接读Raw，迁移sourceVersion/ledgerAvailability和共享搜索消费者，完成临时结果真实GC；Q3统一执行器/Web/维护CLI存储；Q4另行授权正式PLAN/APPLY和清理。`--cleanup`属于Q4，不在Q1提供或执行。正式迁移前仍需核对当时清单、锁、卷、空间和耗时；超过5分钟应重新定位瓶颈。本轮没有新增产品拍板项。
