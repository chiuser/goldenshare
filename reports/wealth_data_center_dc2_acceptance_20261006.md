# 数据中心 DC2 公告查询后端验收

日期：2026-10-06。依据：用户“提交吧。然后推进DC2”、数据中心技术方案和LLD §15。DC1已提交 `9ad6654c`；DC2完成开发及本阶段验收，代码尚未提交。只在当前dev-interface工作区推进，其他任务改动保留。

## 交付范围

本轮完成本地公告索引、名称/历史别名/首字母候选、公告筛选和分页、文件存在性状态、登录鉴权及环境能力控制。实现位于Foundation clients/config/DAO/contracts、Ops CatalogBuilder、Biz data_center API/query/service/schema及App装配；详细文件与指纹见[机器证据](wealth_data_center_dc2_acceptance_20261006.json)。

实际路由前缀为 `/api/v1/wealth/data-center`：`GET /modules`、`GET /announcements/context`、`POST /announcements/queries`、`GET /announcements/queries/{queryId}`、`GET /announcements/companies`。预览、下载任务控制/历史和前端页面属于DC3/DC4，尚未实现。

首页和公告API均通过App登录依赖装配。公告仅在dev/local且显式开关为true时开放；Prod首页返回空模块，公告API及直达页面404。本地拔盘保留入口，具体查询返回来源不可用或状态无法核验，不伪造零记录。

## 计划对账

| 硬口径 | 当前代码 | 验证 |
| --- | --- | --- |
| 六字段完整保留，记录/文件身份不变 | 原Source/core、CatalogBuilder投影、catalog_records | NULL/空串/无URL/无rec_time、不同记录同文件、重复记录拒绝；未恢复group合并 |
| 500条批写，完整日校验后发布 | Catalog日generation/builds、CatalogBuilder | 真实50k临时Parquet分100批；取消、重复、原位修改/原子替换、缺日与有效零行；未发布版本不入查询 |
| 不限定当前上市股票 | NameSnapshot/NameInitials/CompanyQuery | 全状态主表、历史namechange、范围公告代码及别名；退市、主表外代码、中文/代码/首字母、多音词表热更新 |
| 默认30自然日、50条、稳定顺序 | DataCenterPolicy/DTO/AnnouncementQuery | 上海日期、日期交集、同日排序、跨日及深页；标题%/_为字面文本；非法/多余/重复参数422 |
| 状态先全范围再分页 | ArchivePresence/query_presence | 500个key批次、后续页已下载、同文件多行、删除后新查询未下载；旧过滤查询409；unknown不当未下载；hash调用0 |
| 总数完整且同版本 | query_day_counts、query_snapshots、AnnouncementQuery | 日匹配数完整性与generation/revision校验；缺失计数409而非0；同时读取冻结日计数和页面keys |
| 准备异步、进度真实、可重新准备 | App生命周期线程、QueryService、CatalogPreparationPort | 202且total=NULL；日期/记录及检查/统计文案和业务更新时间；准备不消耗结果TTL；中断后清除旧presence重新检查 |
| 只读台账，原CLI行为保持 | ArchivePresence、Ledger可选读timeout | schema1/2/3只读、不升级、不改下载结果；CLI默认5秒保持；原CLI/归档/DG读者专项回归 |
| 认证、Prod禁用、可选依赖隔离 | Settings/capability、App/router/lifespan | 真正挂载路由401/404/200；Prod子进程不加载DuckDB/pypinyin；无反向依赖 |

查询准备串行持有索引writer锁；读取使用query_only，索引WAL/FULL和严格schema验证。来源身份变化后旧queryId明确409。名称原cnspell单独保留；公告六字段原值不因候选键占位改变。词表版本进入每个日版本，避免旧公告别名首字母未更新。

查询SQL预算4秒，单次API共享读预算5秒，连接/锁等待和多个SQL使用同一请求剩余时间；后台保持逐日/逐SQL预算。这个截止机制不宣称能强行中止操作系统阻塞的磁盘调用。结果ready后TTL为900秒，准备阶段不消耗TTL。

## 正式来源只读证据

读取正式 `/Volumes/datasource/data_lake/raw`，只建立 `/private/tmp` 下隔离索引。没有复制正式Lake目录，也没有打开正式归档台账。

| 样本 | 结果 |
| --- | --- |
| stock_basic full | 5911条；读取name/cnspell，不按上市状态裁剪 |
| namechange full | 14229条；用于历史别名 |
| 2026-09-05—2026-10-04 | 完整30自然日，29619条公告 |
| 临时索引冷构建/复用 | 30.624秒 / 0.290秒 |
| 首屏50条/历史别名候选 | 0.089秒 / 0.074秒 |
| 峰值RSS / SQLite空间 | 237928448字节（约227MiB）/44998656字节（约43MiB） |

实际SFZA样本包含深纺织A，以及当前名称平安银行、matchedAlias为深发展A。完整SHA/footer/逐日读取证据保存在机器报告。

**本轮读取时2026-10-05公告Raw分区缺失。** 跨该日查询必须报来源未就绪，不截短范围、填零或触发DG。本报告不代替DG连续日常更新验收，也未进行DG修复或写入。

## 容量门禁与优化

隔离SQLite实际生成800万条记录，160个日期、每日期50000条；不使用全量正式数据导出。最初全范围COUNT+OFFSET在历史/深页/标题查询超过4秒；仅增加覆盖排序索引仍未解决历史和标题瓶颈。失败结果保留在机器证据。

最终后台按日准备匹配数，完整后随query ready发布；无额外筛选时复用已验证日行数，有筛选时按日同WHERE计数。页面用日计数定位，只在相关日期做局部offset，取得50个keys后补名称。没有扩大SQL预算、缩短日期或弱化过滤。

| 800万容量场景 | 后台准备秒 | 最终页面读取秒 | 精确total |
| --- | --- | --- | --- |
| 默认30日 | 0.002 | 0.012 | 1500000 |
| 全历史首页 | 0.005 | 0.002 | 8000000 |
| 第159999页 | 0.002 | 0.017 | 8000000 |
| 标题字面contains | 67.193 | 0.002 | 8000000 |
| 公司筛选 | 11.152 | 0.002 | 80000 |
| 标题无匹配 | 39.945 | 0.0005 | 0 |
| 已下载筛选 | 79.638 | 0.041 | 8000000 |

上表页面数值为最终完整计数校验加入后的复核，后台准备为此前相同计数算法实测；准备时间不包含首次索引构建，也不包含800万真实文件存在性检查。状态容量场景使用隔离presence事实测试SQL规模。

构造800万记录约879.6秒；加入当前覆盖索引后数据库约7.60GiB。最终算法峰值RSS约114MiB，低于512MiB目标。容量脚本重用隔离库的物理记录/索引负载，不宣称整个最终schema做过正式迁移；全新schema严格校验、写入/失败回滚在集成测试验证。

真实隔离文件存在性样本另测：34188个成功文件0.746秒，50000个1.129秒；单个成功key一次安全stat，无hash/远程请求。文件为隔离占位样本，不代表PDF内容校验。

以上为点时样本，不是P95或全历史首次准备耗时承诺。长范围标题/状态统计通过202展示逐日准备进度，完成前没有部分total。索引按请求范围增量形成，不在Web启动时全历史预载。

## 回归、配置与架构

最终组合回归 **257 passed，39.77秒**：公告catalog、真实Web路由、原CLI/DG/ledger/archive-runtime以及三个架构门禁。测试使用临时Parquet/SQLite/卷替身与本地HTTP fixture，没有mock业务查询或服务。现有Starlette/httpx弃用警告1条，不为此安装或升级依赖。

最终compileall、文档完整性、相对链接/实现指纹、git diff --check均通过；CodeGraph sync/status显示索引最新。当前dev-interface，暂存区为空；DC2未提交，其他任务文件未纳入本阶段提交。

配置审计：唯一新增部署项 `WEALTH_LOCAL_ANNOUNCEMENTS_ENABLED` 默认false，由Settings读取，两个env示例同值；capability、modules/API/direct-page/lifespan消费者一致，修改后重启生效。本轮未修改实际运行env。内部参数集中DataCenterPolicy；词表路径/version/SHA由名称构建器核验，变化后重建对应名称和日版本，不由页面计算。

CodeGraph explore/impact覆盖Source/Ledger/Files、Settings、认证/router和新的查询准备调用链；源码/SQL及真实路由测试补核动态端口装配。App注入Foundation纯Protocol、Ops准备实现和Biz查询服务，Biz不反向import Ops/App，Foundation不依赖上层。依赖矩阵未改变；架构快照同步新的实际调用链。

## 未执行项与下一步

正式索引/台账初始化或迁移、实际Web启动/部署、PDF源站请求、DG/Prod/Lake写入、前端开发均为零。本轮没有新增安装、分支、worktree或推送。

本阶段停在DC2。下一阶段DC3实现日期预览、下载后台、进度、停止/继续、精确失败重试和历史API；DC4再接Figma页面，DC5完成获准隔离归档的真实运行验收。DG缺日与连续更新稳定性仍单独核验。各阶段状态不能由本报告提前宣称完成。
