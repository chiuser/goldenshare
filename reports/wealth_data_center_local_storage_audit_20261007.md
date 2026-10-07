# 数据中心公告本地存储与方案匹配审计

核实时间：2026-10-07 09:39 +0800。范围：当前配置/代码、本机PG系统目录、5份公告SQLite台账、正式Raw文件及有限范围直接查询。用户要求先核实；本轮不修改方案正文、业务代码、配置或正式数据，不安装、迁移、清理或启停服务。

结论：直接查询Parquet、复用搜索交互和统一PG的方向可行。现状不能直接套用主应用数据库连接；PG落点、跨归档隔离和来源版本协议必须先补齐。本文是只读审计证据，不是迁移授权或完整接口性能验收。

## 1. 证据与权限

CodeGraph explore覆盖App公告装配、ArchiveStore和台账调用链；前轮explore/impact覆盖搜索控制器、首页/交易助手及测试。本轮按当前源码补核Settings、stock-search SQL、来源/身份算法、预览与DG原子发布。使用已有根环境和orchestrator环境，没有同步依赖。

本机服务读取按工具要求提权；PG使用只读事务、连接/语句/锁超时，只查系统目录和表名，没有连接远程PG。SQLite使用mode=ro、query_only及读取事务；Parquet使用内存DuckDB、256MiB/单线程、禁spill和扩展自动安装。临时审计脚本位于 `/private/tmp`。

## 2. PG与连接配置

| 核实对象 | 实际结果 | 对方案的影响 |
| --- | --- | --- |
| 本机PG | PostgreSQL 18.4 Homebrew，localhost:5432监听IPv4/IPv6；只读会话验证通过 | 可复用现有实例，无须安装新的数据库服务 |
| `.env.web.local`与`.env` | DATABASE_URL均指向远程goldenshare；local文件启用公告模块 | 公告台账不能复用默认主应用engine/session；APP_ENV=local不等于数据库在本机 |
| `goldenshare_dagster` | public中22张表，约15.52GiB | 属于DG控制事实，不作为公告业务存储 |
| `goldenshare_lake_meta` | public中4张旧指数治理表，约8.36MiB | 存在但不是现成公告库；当前维护源码未找到连接该库的消费者，不据此推断仓库外服务状态 |
| `goldenshare_margin_detail_m3_20260803` | 历史M3验收库；有业务schema及anns_d相关表 | 文档确认其验收用途，不作为当前公告数据来源或迁移目标 |
| `postgres` | 无用户业务表 | 不借用默认维护库存业务台账 |
| 当前角色 | congming具备创建库能力 | 只证明权限具备，不表示已创建或授权创建 |
| 主仓库Alembic | 静态解析得到单head `20261002_000183`；env.py使用主应用DATABASE_URL | 不能运行默认upgrade来初始化公告本地存储；须定义明确本地迁移落点及版本管理 |

旧元数据库4张表为 `index_daily_active_pool`、`index_daily_active_pool_history`、`market_major_indices`、`market_major_indices_change_history`。架构文档将其列为遗留对象，当前DG不注册该resource。

建议优先复用现有 `goldenshare_lake_meta` 库，在独立 `announcement_archive` schema中承载归档事实；独立本地连接及版本管理，不改旧表、不恢复旧DG resource，也不改变主应用远程连接。此为待确认的具体落点建议，尚未修改配置或DDL。

依据：[Settings](../src/foundation/config/settings.py)、[主应用engine](../src/db.py)、[Alembic入口](../alembic/env.py)、[DG启动依赖](../lake_console/orchestrator/src/orchestrator/local_startup.py)、[当前数据体系架构](../lake_console/docs/architecture/dagster-data-system-architecture.html)。

## 3. 磁盘、台账与隔离

datasource当前挂载于 `/Volumes/datasource`，APFS、可写、可用约2732GiB；卷UUID `8C5A534D-EAE1-42A2-A7D5-D24DEB820E29` 与4份下载台账一致。本次没有写探测文件。

| 本功能SQLite | schema/内容 | 核实结果 |
| --- | --- | --- |
| catalog | 11张表，275.43MiB | 210602条公告、156个日版本、106871条公司来源、13个查询；还包含2个预览及其日期/文件关系 |
| 正式downloads | schema3，52.33MiB | 2个run、34188个artifacts/source_records、363成功/33825pending |
| dg-source-acceptance | schema2 | 3个run、5个artifacts、5个source_records |
| m3-interrupt-acceptance | schema2 | 5个run、5个artifacts、10个source_records |
| dc5-acceptance | schema3 | 3个run、5个artifacts、5个source_records、6个attempt、4个command receipt |

正式台账363个成功文件均在安全普通文件路径下存在：缺失0、发现的不安全路径0。只做lstat存在性检查，不宣称内容哈希验收。

四份下载台账两两共有相同的5个artifact_key。迁入同一PG后，artifact、path_fold、source_record和任务关联必须按归档身份隔离；不能把artifact_key当作跨归档全局唯一键。原volume UUID与卷内root组成的身份算法保留。schema2读取后按明确映射迁移，不提前升级或重写原SQLite。

catalog不仅是列表缓存：PreviewRuntime及supervisor范围复核依赖其预览/日版本。清理前必须一起迁移消费者或按批准的新合同使旧预览过期，不能直接删除catalog。

依据：[台账](../src/foundation/dao/announcement_archive/ledger.py)、[控制事务](../src/foundation/dao/announcement_archive/execution.py)、[catalog](../src/foundation/dao/announcement_archive/catalog.py)、[预览](../src/ops/runtime/announcement_archive/preview.py)、[supervisor](../src/ops/runtime/announcement_archive/supervisor.py)。

## 4. Raw与直接查询

物理文件清单共有2471个公告日分区，最早2020-01-01，最新2026-10-06；2026-05-04—10-07范围只缺10-07。清单核实不等于全历史六字段/源端完整性验收，也不能据文件存在宣称DG readiness。此前10-05/06缺失的记录只代表当时状态。

两份名称snapshot存在：stock_basic 5911行（L 5572、D 339），namechange 14229行。002245.SZ名称为蔚蓝锂芯，cnspell为WLLX。

155日窗口2026-05-04—10-05共有210602行、155文件、149个行组，总大小5738480字节（约5.47MiB），六列均为VARCHAR。002245.SZ匹配36条；标题包含“公告”匹配19条。该窗口有44个不同公告代码不在stock_basic中。

| 点测 | 结果 | 使用边界 |
| --- | --- | --- |
| 根Web环境DuckDB 1.5.5，count+简化排序首页 | 三次合计0.0512/0.0360/0.0360秒，36条；峰值RSS约115.67MiB | 可能暖缓存；简化排序不是完整产品分页合同 |
| 按原record_key排序的SQL首页 | 0.2855秒、36条 | SQL显式SHA256(JSON数组)与Python原身份算法逐条相等；仅验证36条样本，不替代全边界金样本 |
| 名称/目录日期样本 | 目标股票日期与分区不一致0条 | 不代表全历史质量审核 |
| 文件读取前后 | 155份公告与两份名称文件stat签名未变化 | 本次没有遇到DG并发原子替换；不能替代并发协议测试 |

orchestrator现有DuckDB为1.5.2，根Web环境为1.5.5，两者分开核实，未升级。以上均不含PG下载状态、名称完整搜索、源版本校验、网络/API及前端开销；没有清除系统缓存，不提供冷启动/P95保证。直接查询样本可行，但还不能宣称完整接口预算已通过。

DG使用 `os.replace(candidate,target)` 发布正式日文件；现有DayReader/NameSnapshot固定FD并复核内容。新多文件查询须设计总数/分页期间源替换的版本验证，不能只把SQLite SQL换成read_parquet就认为一致性问题解决。

## 5. 搜索复用与待补齐事项

现有首页和交易助手已共用 `useStockSearchController`，可复用防抖/取消/键盘/选择基础。当前stock-search API通过主应用session查询security_serving，只匹配symbol/ts_code/cnspell，name仅展示；只取当前上市CNY A股。其默认配置是远程连接，所以直接调用该API既不能满足公告候选范围，也不能达到本地读取目标。

公告保留本地候选加载器、中文名称/历史别名/退市/主表缺失代码；控制器需注入加载器并明确Enter选择差异。当前NameInitials及已安装pypinyin 0.55.0可复用，没有新增依赖需求。

在下一轮更新LLD前，需要冻结：

1. PG具体库/schema及独立本地连接配置、权限与迁移版本管理；确保不误用远程DATABASE_URL。
2. 全表按归档身份隔离的键、schema2/3映射及迁移读回/checkpoint；原控制/冷却/失败历史保留。
3. 来源版本、稳定record_key排序、状态筛选presence，以及旧投影DTO字段清退的唯一合同。
4. 名称候选加载器与共享控制器接入方式；真实完整API和停止—退出—续跑验收。

本轮仅新增本审计报告和临时审计脚本；既有方案修改/脏代码保持原样，没有提交。分层与依赖矩阵未改变。文档检查不能证明DDL/API/迁移正确，这些仍须后续独立验收。
