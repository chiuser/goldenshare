# Q3 下载与维护统一 PG：执行约束与验收

依据：数据中心 LLD §22.5、22.6、22.10、22.11。Q2 已提交 `6dbb27e4`、`60099811`。本阶段只改当前 dev-interface，正式数据库迁移、环境切换和 SQLite 文件清理属于 Q4。

CodeGraph query/impact 已覆盖 Ledger、ArchiveStore、ArchiveSupervisor；当前代码补充核验 CLI → executor → HTTP/Files → DAO，Web → download service/RunQuery → supervisor/store/control，App lifespan 装配和迁移源读取器。旧 SQLite 的 schema 校验仅留给显式迁移，运行时不再自动建表/升级。

| 硬约束 | 落地与验证位置 |
| --- | --- |
| PG 唯一运行存储、每条读写按 archive_id 隔离、短事务 | Ledger / ArchiveStore / ExecutionLedger / RunQuery / LedgerQuery；隔离 PG 测试 |
| archive_execution 行锁；磁盘和本地执行锁保留；不根据心跳抢占 | begin_run / claim / Volume / supervisor；并发与退出测试 |
| 停止、封存后续跑、失败精确集合重试 | supervisor / control / executor；实际路由测试 |
| cooldown、403/429、prepared 原子文件协议保留 | HTTP / Files；下载回归与故障注入 |
| 观测失败不回滚文件业务；PG 不可写禁止新 HTTP | control / Limiter.request_started；离线与失败注入 |
| CLI 不再输出 SQLite 路径/顶层 schema_version，storage 返回真实 PG 标识 | 两个 CLI / 原 PDF 文档；JSON 与游标测试 |
| rowid 参数继续整数，PG 查询使用 row_seq | LedgerQuery / RunQuery；分页测试 |
| 正式服务、数据和配置不写 | 仅 /private/tmp 的独立 PG 测试实例 |

配置审计：本阶段不新增或变更配置。沿用 `ANNOUNCEMENT_ARCHIVE_DATABASE_URL`（默认空，Settings 读取 env / GOLDENSHARE_ENV_FILE 指定文件），固定 loopback:5432/goldenshare_lake_meta/announcement_archive，独立 pool_size=4、无 overflow、连接3秒、锁500ms、SQL4秒。Web 使用既有本地公告开关；CLI 同样读取该 DSN，不回落主 DATABASE_URL。测试显式注入已有 Q1 隔离数据库策略。

## 改动与边界

- Foundation：Ledger、ExecutionLedger/ArchiveStore、LedgerQuery改原生PG短事务；Volume/Binding只定位本机execution.lock；静态legacy_schema由显式迁移读取器使用，旧未引用Presence删除。
- Ops：下载和维护CLI、supervisor/control统一同一PG事实源；业务写入和观察事务分开，owner/stop不能靠心跳抢占。
- App/Biz：lifespan共享单池，RunQuery迁原生PG；QueryService仅增加池归属控制，列表仍直接读取Raw。
- 测试：运行夹具改临时PG；保留旧schema显式迁移测试，移除与已批准合同冲突的SQLite运行自动升级测试；新增PG隔离/并发/只读/失败注入/CLI/容量和浏览器用例。
- 文档：原PDF方案/LLD、数据中心方案/LLD、产品状态与CodeGraph快照同步。未改配置、前端、依赖矩阵、DG数据集或Prod主链。

## 验证

最终Q1–Q3/架构联合回归352项通过（148.28秒），浏览器夹具另1项通过。前端158个文件、1134项测试通过；typecheck与生产build通过。ingestion-lint-definitions、compileall、docs integrity、git diff --check通过。build保留现有bundle大于500kB提示；已有Starlette/httpx弃用提示没有引入依赖安装。

真实隔离PG包含：并发claim仅一位成功；两个archive同artifact_key读写不交叉；实际ALTER临时数据库只读后读成功、业务写失败、HTTP为0；before-run/before-HTTP/首个PDF提交后离线均不产生后续请求；observe单独失败仍提交PDF和业务结果。五个进程退出窗口和CLI退出/恢复覆盖真实os._exit，启动恢复不自动下载。

停止回归中曾发现节流持久读取会在停止后继续枚举并被状态校验阻断。最终每个业务检查点均读取stop/owner，后台观察0.5秒；观察写节流只作用于进度/心跳。针对性3例通过后重新执行联合回归。

[PG容量证据](wealth_data_center_q3_profile_20261007.json)：500行一批，110000任务文件家族中40000未解决失败；SQL走既有PG索引，查询受4秒预算约束。RSS/FD/SQL时间来自该进程，sourceBytes/rowGroups=0是受控夹具，无正式Lake容量推论。最终计时以JSON为准。

## 浏览器验收

独立临时Uvicorn服务、PG、Parquet和模拟PDF传输，实际Wealth页面和后端路由；模拟登录不接触正式认证数据。

- 公告列表查询6条，按2026-09-30日期范围预览6个文件。
- 请求间隔3秒，页面显示5/6、83.33%和请求间隔等待。
- 一个模拟404，其余5份成功；重试全部失败项只创建1个文件的关联任务，成功后原失败历史保留。
- 刷新列表后6条均为已下载；源站模拟HTTP共7次，仅2.pdf请求两次，其他各一次。浏览器无console错误。
- fixture未实现公共市场context，顶栏该请求404；公告相关API正常，不能将夹具的市场404认定为正式行情验收。

[请求证据](wealth_data_center_q3_browser_20261007/api-evidence.json)；[失败及进度](wealth_data_center_q3_browser_20261007/task-partial-failed.jpg)、[精确重试](wealth_data_center_q3_browser_20261007/retry-completed.jpg)、[刷新后列表](wealth_data_center_q3_browser_20261007/list-downloaded.jpg)。历史表手动刷新之前截图可保留原缓存结果，当前任务详情和最终列表由真实API验证。浏览器夹具测试1项通过，退出后服务与临时PG全部关闭。

## 交付状态

Q3开发与隔离验收完成，尚未提交。本轮不重复提交已提交的Q2。CodeGraph query/impact分析Ledger、ArchiveStore、ArchiveSupervisor，sync/status为up to date；Protocol动态注入与SQL另做源码和真实路由核验。仍需人工确认的边界只在后续Q4正式迁移、数量/指纹读回、外盘身份和切换结果。

没有正式DB/Lake/PDF写入，没有改.env或启用PG存储，没有重启现有Web/DG、安装或卸载SQLite、删除旧台账。下一阶段Q4先正式PLAN，再在该阶段批准范围内APPLY、读回和切换；清理旧文件独立按批准清单进行。当前Q3代码不可在正式迁移前直接部署启用。
