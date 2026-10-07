# 数据中心与上市公司公告 LLD v1

日期：2026-10-07。状态：**编码级设计已获确认；DC1提交9ad6654c，DC2提交a1b47713，DC3提交83ffb83f，DC4提交b5534947；DC5本机正式归档验收完成，见§20；DG日常稳定性另行验收。** 依据[技术方案](data-center-announcements-implementation-design-v1.md)、[产品方案](../../../../docs/product/wealth-data-center-announcements-product-plan-v1.md) §5/§8.4 和 Figma R1。字段、SQL、状态、配置与测试以本文为网页目标合同；当前 CLI 行为仍以原 PDF LLD 为准。

**修订状态：** §22明确本地PG落点、表结构映射、迁移/续跑、直接查询一致性、API及共享搜索合同。Q1已提交d6cc3971，见§23；Q2主体已提交6dbb27e4；用户明确授权旧源码清退后已完成本阶段开发、清退及验收，见§24。Q3已提交b4c590fd，见§25；Q4正式迁移、读回和统一启用已执行，见§26；旧文件清理待单独批准。此前§3—8、§10—11中的SQLite实现、投影字段和相应测试属于既有实现基线，被§22替代；§13—21保留历史交付及review修正证据。R01—R24产品硬口径继续有效。正式写入、切换和清理仍按分期取得执行授权。

## 1. 硬口径、实现点与验收索引

测试编号是后续必须实现的用例，不表示本轮已通过。

| ID | 不可改变的要求 | 实现落点 | 正向/负向验收 |
| --- | --- | --- | --- |
| R01 | 登录即可访问；Prod 首页无公告卡，直达/API也不可用 | capability + App认证装配 | T01本地登录可用；匿名401/Prod404/同名目录不开启 |
| R02 | 本地拔盘不隐藏卡，未知不填0/未下载 | context/查询状态映射 | T02外盘阻断、缓存标旧、历史可读；不伪造空态 |
| R03 | 六字段全量元数据，六列公告列表，多记录同文件 | Source/projector/catalog/DTO | T03 NULL/空串/同标题不同字段保留；无URL仍有行 |
| R04 | 原站外链“公告详情”，新标签；无本地PDF服务 | sourceUrl + ExternalLink | T04已/未下载均可外跳；不显示原地址、不暴露local-path路由 |
| R05 | 名称/代码/首字母候选，完整代码选择，历史别名 | CompanyQuery/名称来源/词表 | T05 PAYH、中文、数字前缀、退市、未知名称；不套L-only池 |
| R06 | 默认30自然日/50条/稳定顺序，查询/重置/刷新交集 | QueryPolicy/query SQL/controller | T06上海跨日、同日ties、%/_字面；刷新不发DG/Tushare/PDF请求 |
| R07 | 两种下载状态；文件删除可重下；状态筛选先全范围后分页 | PresenceReader/query snapshot | T07删除即刷新未下载；不可先50条后过滤、不可逐行hash |
| R08 | 创建仅日期、空初值、5秒/非负0、固定灰路径 | CreateRequest/PreviewPanel | T08同日起止可用；公司/URL/路径/勾选extra字段422 |
| R09 | 预览五统计；无URL不失败；先准备封存再HTTP | preview/Source day facts/ledger.seal | T09 1028/1000/8/10/990；缺日/源变化/零文件不下载 |
| R10 | 同归档一活动执行、不排队、网页关闭不停 | supervisor+双锁+active slot | T10双用户/双webworker/CLI争锁；重复提交不重复执行 |
| R11 | 阶段/文件/字节/等待/更新/真实处理进度 | ProgressEvent/DTO/轮询 | T11 320/1000=32%；未知总量NULL；100%且失败不是success |
| R12 | 最多3次自动尝试；持久化间隔/退避/冷却 | Downloader/Limiter/attempt log | T12 zero不绕过冷却、重定向计间隔、重启保留429期限 |
| R13 | 单项/全部失败精确重试，旧结果保留 | retry关联run +冻结run_artifacts | T13 1或10keys；不纳同日同公司；成功项零请求 |
| R14 | 停止确认→stopping→stopped；准备停止不可执行 | stopRequested + control | T14每个批/文件/请求/等待检查；stop重复幂等、不领新unit |
| R15 | 继续只原未完成；后端中断人工恢复 | sealed run + owner恢复 | T15退出/重启/Raw更新均不扩大；失败另重试、不开自动HTTP |
| R16 | 文件命名/物理提交不损坏已有成果 | 唯一Files/Volume协议 | T16冲突/链接/同设备/磁盘满/prepared窗口、观察失败 |
| R17 | 全局阻断、有限重新检查、恢复后手动继续 | error map/recheck/limiter | T17拔盘/403/captcha停止领取；检查不清冷却、不全量探测 |
| R18 | 历史/文件结果/失败列表分页，关联批次和真实结果 | RunQuery/ResultPanel | T18历史数字不因修复改写；分页详情/重试后已解决数正确 |
| R19 | 来源/性能/事务/配置单一，保持DG/CLI边界 | Source contract/Policy/架构护栏 | T19无旧湖/Prod fallback/全量内存/隐式安装；原CLI回归 |

## 2. 目录、接口职责与影响面

目标目录在方案 §3.1，具体文件按职责设置，禁止为每个动作复制下载循环：

- Foundation `clients/announcement_archive/{core,source,volume,files,http}.py` 从现有实现移位；DAO 下 `ledger.py`、`catalog.py`、`maintenance.py`（仅查询）；单文件修复编排归Ops maintenance，文件核验归Files；kernel下端口与事件在对应运行阶段接线。保留 `source_projection` 原 JSON/SHA 算法和 DownloadOptions/DownloadPolicy。
- Ops `runtime/announcement_archive/{executor,maintenance,supervisor,catalog_builder}.py`：执行单循环、长读取准备、当前run控制；不用 Biz DTO 或 App auth。CatalogBuilder只复制经验证的来源投影/别名事实、计算确定首字母；名称优先级与搜索排序在 Biz。
- Biz `api/wealth/data_center/{home,announcements}.py`；schemas 同域 `announcements.py`；queries 同域 `{announcement_query,company_query,run_query}.py`；services 同域 `{query_service,download_service,policy}.py`。不建 flat `wealth_data_center_*.py`。
- App `announcement_archive_lifespan.py` 创建 supervisor、向 Biz 注入 Foundation 的 `ArchiveExecutionPort`，在 router 装配处加 `get_current_user` 登录依赖。Business API 不 import App/Ops；App传递 actorId只供审计、不新增权限规则。
- 两个 CLI 原路径保留为入口；移走 `src/scripts/announcement_download/` 的主实现并清零所有旧 import，不留兼容转发包。CLI仍接受现有参数/退出码；日期重放与网页continue是两个明确意图，共用执行循环的两种输入，不存在两套文件协议。

`ArchiveExecutionPort.submit(kind,payload,key,actor)` 只接纳 create/continue/retry/recheck 四类执行意图，返回已持久化runId；close由App生命周期调用。本地预览由PreviewRuntime准备，stop由ArchiveStore保存意图，只读观察由RunQuery读取，不通过执行端口读写混用。`ArchiveCommand` 是本地文件归档命令，不是新的 DatasetDefinition 或 Prod ingestion action。元数据更新仍由既有 DG 管道负责，网页不操作 DG/Prod TaskRun。

全部消费者：download CLI、ledger CLI、maintenance、Source/Files/HTTP、三个公告测试文件、schema1 fixture/process runner、架构测试；新增网页 API/运行器/查询。当前 StockSearch API及其 watchlist消费者行为不改，公告使用独立候选合同。导航必须审计所有现有 onNavigate→path映射，不只修改 DataCenter自身；当前未识别路由回 MarketOverview 的默认逻辑须增加明确匹配。

## 3. 数据合同与可重建查询索引

### 3.1 三类事实

| 事实 | 来源与允许的处理 |
| --- | --- |
| 公告原记录 | 固定六列 VARCHAR `ann_date,ts_code,name,title,url,rec_time`；原值入投影；日期规范列另外保存；Raw不写hash/groupkey/下载状态 |
| 公司名称/别名 | 正式Raw stock_basic全状态的ts_code/name/cnspell；正式Raw namechange的ts_code/name；所请求公告范围的name；不查远程、不调用当前A股池 |
| 文件/执行 | 原归档SQLite和实际普通文件；归档身份为输出卷UUID+卷内目录；source_scope为来源卷身份+六字段版本 |

来源路径固定为 `/Volumes/datasource/data_lake/raw/tushare/<dataset>/...`。公告按自然日 `ann_date=YYYY-MM-DD/part-000.parquet`；两份名称snapshot在 `full/part-000.parquet`。consumer 不 import orchestrator，AST合同测试核对fields/version/路径。只投影所需列，`hive_partitioning=false`，FD固定与两次指纹沿用现有DayReader。

身份保持：

```text
recordKey = identity(["dg-anns-d-v1", 六字段原值按合同顺序])
artifactKey = identity([ISO(ann_date), raw_ts_code, raw_url.strip()])
URL为NULL/trim后空：artifactKey=NULL
```

标题不进文件身份；name/rec_time/title改变仍是不同源记录、可关联原文件。新文件代表标题从关联记录按recordKey升序确定；已有 artifacts.title/path保留，不能因新名称/标题重命名。NULL标题/代码/非法URL来源记录保留，下载时作为独立文件错误；若同文件存在可用标题，选择稳定的可用代表并记录representativeRecordKey。

### 3.2 索引表（新增本地投影，不是Raw副本事实源）

存储路径：`~/Library/Application Support/Goldenshare/announcement-catalog/<sourceScope>/catalog.sqlite`；schemaVersion=1，WAL/FULL；不落外盘Lake或下载目录。单索引writer，读连接query_only；数据库不可用不退回Prod。磁盘缺失时不能把缓存当当前来源ready。

| 表/主键 | 字段与作用 |
| --- | --- |
| `catalog_days(ann_date)` | active_generation、源dev/ino/size/mtime_ns/sha256/footer_count、published_at、dictionary_version；完整零行日也有事实 |
| `catalog_records(ann_date,generation,record_key)` | 六字段原列（raw_ann_date另名）、artifact_key、download_url；NULL/空串原样；新版本只供发布后查询 |
| `catalog_builds(build_id)` | 所请求日期、state/current_day/days_scanned/records_scanned/reason/updated_at；无HTTP |
| `company_sources(source_kind,ts_code,name)` | raw_master/历史更名/公告别名、cnspell、initials、最新公告日期、所属日版本；名称缺失的代码仍纳候选 |
| `catalog_meta(singleton)` | schema版本、catalogRevision、名称版本、词表版本、名称快照指纹事实；ready与来源可用性分开 |
| `query_snapshots(query_id)` / `query_presence(query_id,artifact_key)` / `query_day_counts(query_id,ann_date)` | 规范条件、catalogRevision、archiveIdentity、checkedAt、expiresAt、成功且存在的文件keys；presence只为状态过滤；逐日匹配数用于完整统计和深页定位；updatedAt/preparationStage/datesCounted/artifactsChecked持久化准备业务进度，大查询准备不常驻内存 |
| `preview_artifacts(preview_id,artifact_key)` | schema2新增本地预览去重标记；500记录一批插入，只对首次出现文件检查存在性，重启重算前分批清除本预览标记 |
| `previews(preview_id)` / `preview_days(preview_id,ann_date)` | 日期/interval/来源/归档身份、状态/统计/有效期、逐日固定版本指纹；无全量候选JSON |

索引：另加按列表顺序的覆盖索引`(ann_date DESC,(ts_code IS NULL),ts_code,record_key,generation,artifact_key)`；records `(ann_date,generation,ts_code,record_key)`、`(ts_code,ann_date,generation,record_key)`、artifact_key；company `(ts_code)`、`(initials,ts_code)`。标题contains不假装能用普通BTree，需要日期/公司裁剪后参数化instr；不引入语义索引或PDF全文检索。

构建一个日版本：begin→读FD/校验schema→500行逐批写未发布generation→指纹/行数/六字段重复校验→短事务更新active_generation和revision。途中失败保留旧active，当前请求所需新版未就绪就返回preparing/error，不能把旧版当最新。新增版本存在性判别使用dev/ino/size/mtime；有变化才完整重建，缺文件撤销可用标记。相同inode原地修改阻断；DG正常os.replace不伤已固定的旧版本读取。

首次仅请求范围构建；company候选用stock_basic/namechange全量小snapshot，加当前查询日期范围公告代码/名称（包括主表外代码）。更宽日期查询先补该范围索引，再候选；不宣称未扫描全历史的公告别名已全部收集。历史更名snapshot可在最近日期查询时命中过去名称。旧未发布generation/query_presence仅是可重建缓存，可在无引用且过期后分批GC；不得删除原台账、PDF、历史run或正式Lake。

### 3.3 查询和存在性流程

1. 规范日期/条件→验证所请求每个自然日存在且索引版本当前；缺日返回source_not_ready，合法零行可参与查询。不默认裁剪未来/缺失日期。
2. 普通all查询：一个SQL读事务count+50行+稳定顺序；结束事务后对该页唯一artifactKey在台账查询succeeded/path，安全stat检查。无台账文件直接undownloaded。重挂载UUID不符/权限/IO错误是unknown，整页statusUnavailable，不把unknown行填undownloaded。
3. 状态筛选：SQL取匹配元数据的distinct artifactKey与succeeded台账交集，500一批；逐key安全存在性检查、落query_presence。无成功台账不需stat。完成后count和分页在SQL应用presence条件；扫描超4秒返回202/preparing，不输出半截结果/总数。
4. 结果以queryId绑定规范条件、catalogRevision、归档身份、presenceCheckedAt，结果ready后有效15分钟；准备中不消耗结果TTL，进程重启可继续本地准备。同版本翻页；catalogRevision/归档身份变化或页文件检查发现与presence不符返回409要求刷新。检查和展示存在时间差，DTO明确checkedAt，不承诺浏览器显示后文件不会被用户删除。
5. 不在SQLite读事务里stat/hash/网络；catalog+ledger不做跨DB写事务。ledger短快照读回本批后关闭，查询存在性结果不写artifacts.state或历史run。

SQL核心（`:downloadedKeys` 是临时/持久化presence关系，不是巨大IN参数）：

```sql
SELECT r.record_key,r.ann_date,r.ts_code,r.name,r.title,r.url,r.artifact_key
FROM catalog_records r JOIN catalog_days d
 ON d.ann_date=r.ann_date AND d.active_generation=r.generation
WHERE r.ann_date BETWEEN :startDate AND :endDate
 AND (:tsCode IS NULL OR r.ts_code=:tsCode)
 AND (:title='' OR instr(COALESCE(r.title,''),:title)>0)
 -- downloaded: EXISTS(query_presence key); undownloaded: NOT EXISTS(...)
ORDER BY r.ann_date DESC,(r.ts_code IS NULL),r.ts_code ASC,r.record_key ASC
-- 页面按逐日匹配数定位，只对相关日使用局部offset
LIMIT 50 OFFSET :dayOffset;
```

计数同WHERE、同revision；后台按每个已发布日短快照计算匹配数，完整后随query ready原子封存。API读事务同时取该revision的日匹配数与50行，不输出部分总数。无公司/标题/状态筛选时可直接使用已完整校验且与索引实际行数一致的日footer_count；有筛选时按日参数化COUNT，相同筛选不改变语义。每页50固定，正常上一/下一页携page序号；大页OFFSET必须进入容量样本，超4秒不输出错误空态。允许实现将queryId的页游标存储为日期/代码/recordKey keyset以优化，不改变页码/总数用户合同，不允许临时扩大返回list。

名称查询以代码 LEFT JOIN，不能用名称表 INNER JOIN 丢公告。显示优先master的非空name；否则所请求日期范围 `ann_date DESC,record_key ASC` 的非空公告名；否则代码，代码也缺失显示“—”。CompanyCandidate按代码去重；匹配排序固定为完整代码精确→六位代码精确→代码前缀→当前名称精确/包含→当前首字母前缀→历史名称/首字母，再按tsCode升序。名称contains使用instr，首字母uppercase前缀LIKE须escape；sourceName/cnspell原值不被搜索规范值覆盖。候选matchedAlias明确历史命中依据，显示name仍是当前主表名；不默选首项。

## 4. 台账 schema 3 与执行事务

保持原 `archive/artifacts/source_records/cooldown/run_source_days/run_artifacts/runs` 数据与身份。新增字段/表：

| 位置 | 增量字段/约束 |
| --- | --- |
| `runs` | batch_kind=date/retry、parent_run_id（根日期run）、retry_of_run_id、preview_id、created_at/started_at/finished_at、actor_id、owner_token、heartbeat_at、business_updated_at、stop_requested_at、resume_count、current_artifact_key、attempt_number、bytes_received、bytes_total可空、wait_kind/next_request_at、revision |
| `artifacts` | created_run_id、representative_record_key；仅新artifact封存时确定代表标题，旧title/path绝不重写 |
| `run_artifacts` | representative_record_key、claimed_owner、claimed_at；旧outcome/attempts保留；不以全局artifacts.attempts替代本批尝试 |
| `attempt_log(run_id,artifact_key,attempt_seq)` | session_seq、started/ended、outcome、reason、http_status、bytes；保留每次手工/自动尝试，单文件会有多session但本次自动最多3次 |
| `archive_execution(singleton)` | active_run_id、owner_token、heartbeat、revision；同归档一个活动slot，终态事务清空 |
| `run_sessions(run_id,session_seq)` | start/end、owner、stop/interrupted原因；continue保持原run/counters，记录恢复会话 |
| `command_receipts(key)` | kind、payload_hash、result_run_id、state、created_at；同命令幂等与响应丢失恢复 |
| `runs`检查观察 | check_state、check_kind、check_code、check_updated_at；检查不改原下载结果 |

台账继续DELETE journal、FULL；短read/write事务与query timeout；不因为查询索引采用WAL就更改台账journal。新DAO分别声明每个schema的准确允许列/索引，不能简单跳过原严格校验。

schema1/2识别、写入口原子迁移到3；只读CLI仍可读取已支持的旧schema，不创建/升级/改变文件。迁移不清空/备份/改路径，不重新拉PDF；所有旧结果/来源/冷却保留。老run没有完整冻结/控制证据时`canContinue=false/canRetry=false`，原因“历史任务不支持精确恢复，可新建日期下载”；不可猜旧集合。未保存source_policy的历史任务同时`canRecheck=false`，与执行器的检查接纳前提一致；有策略的当前阻断任务继续提供检查。schema2枚举已封存并具备完整run_artifacts者可经过校验接管；旧active仅在取得锁、证实无执行owner后记中断，不能触发HTTP。迁移必须在归档独占锁内，失败事务回滚，未知schema阻断。正式迁移另行授权。

| 事务unit | 原子事实 | 禁止夹带 |
| --- | --- | --- |
| create接纳 | 幂等键、预览校验、run枚举意图、active slot | 网络/整段文件读取 |
| 枚举批500 | 原source_records、唯一run_artifacts、记录/无URL/日committed计数 | 部分日封存、HTTP |
| 日封存/总封存 | 日校验事实；所有日完整后enumeration_sealed/total/phase | 猜空日、继续读新版增量 |
| 领取/尝试 | 单key owner、attempt_log起始、run current | 长网络事务 |
| prepared/成功 | 文件已fsync后size/hash prepared；原子rename+dir fsync后artifacts成功；run结果及counter幂等更新 | 为观察失败删除/回滚PDF |
| 失败/停止/阻断/中断 | 保留原结果，终态与slot释放一致；未完成claim释放 | 清空原任务/失败后重算全范围 |

`ledger.result`必须幂等。文件成功而run观察事务失败：停止领取，保留prepared/succeeded事实；恢复先按该key物理recover、补一次结果，不能重复下载/计数。字节观察写失败不回滚文件写入；持久控制/业务结果写失败后不得盲目领取新unit。心跳与业务完成写分离。

继续原run只查询outcome=NULL的冻结key，已failed不加入。关联retry run原日期/interval/来源身份继承，准备以原失败key的keyset分批`INSERT…SELECT`（每事务最多500keys），全部封存后开始；不能一次复制无界失败集合到长事务，也不能接受公司/date/title/URL参数。根run失败未解决集合：原失败key减去其关联重试已succeeded/skipped的keys；原failed结果不改。重复重试与原日期下载若已有有效文件，先recover后记reused，不发HTTP。原run显示历史结果及`unresolvedFailureCount`；retry显示本批总量、rootRunId与原无URL数量的范围背景。

## 5. 配置项、依赖与生效审计

| 配置/参数 | 默认、来源、持久化 | 消费者/依赖 | 生效/可见/门禁 |
| --- | --- | --- | --- |
| `wealth_local_announcements_enabled` / `WEALTH_LOCAL_ANNOUNCEMENTS_ENABLED`（新增） | false；Foundation Settings，env/env-file沿用现有读取优先级 | capability、router、supervisor、home；必须APP_ENV=dev/local | 重启；运营部署配置可见、用户只见模块；Prod强制关闭 |
| `APP_ENV`（既有） | dev；Settings | 同上；prod/其它环境均不提供公告 | 重启；不按host/浏览器/路径推断 |
| startDate/endDate | 下载必填空初值；查询缺省上海today-29/today；API→preview/runs | catalogue/Source；自然日闭区间 | 每次命令；同日/跨月/未来缺日/倒置负例 |
| intervalSeconds |5，有限非负小数；DownloadOptions→preview/runs |Limiter及全部HTTP；继承后不缩短cooldown | create；重试/continue继承不另暴露新间隔 |
| 归档/来源根 |固定GUI默认根、固定正式Lake；唯一core/source工厂 | Volume/Source/DAO；禁止Lake输出 | 启动；GUI不可编辑/不可API透传；CLI既有output-root保留 |
| 台账/索引路径 | UUID+相对根及sourceScope自动派生，见§3/4 |DAO/锁/reader；不提供用户文件选择 |启动；不同卷隔离、schema检测、文件0600/目录0700策略 |
| 基础DownloadPolicy（既有） |batch500、DuckDB256MiB/1线程/无spill、query15秒、chunk64KiB、max512MiB、reserve1GiB、connect10/read15/write15/pool5秒、transfer600秒、attempts3、redirects5、backoff30秒、filename200字节、progress5秒、waitSlice0.5秒 |Source/HTTP/Files；runs保存policy版本摘要 |每run；继承原PDF LLD §2，不再各处写默认常量 |
| `DataCenterPolicy`（新增集中内部策略） |page50/history20/result50、候选limit20/keyword64、title200、SQL截止4秒、API读截止5秒、poll2秒、heartbeat5秒、失联提示15秒、preview/queryTTL900秒、catalog校验周期30秒、日期任务控制poll0.5秒、索引unit软预算60秒 |Biz/Ops共享明确子配置投影；不得env/page各放一份 |启动/创建；前端context读取日期/间隔/分页/轮询；固定观察合同集中clientPolicy、跨端测试核对，超预算prepare或error，不截范围 |
| 首字母词表（新增） |版本化`config/wealth/announcement-name-initials.json`，仅名称→确定覆盖读音/首字母 |索引生成；源cnspell优先，词表只补历史/缺失 |后台准备重新读取词表，版本改变后重建所请求日期及名称索引；运营文件、无用户控件；同名跨公司可用tsCode限定 |

依赖：现有stdlib/httpx/DuckDB/React足够执行和页面；历史简称中文首字母需要新增本地可选依赖 `pypinyin`。其[官方说明](https://github.com/mozillazg/python-pinyin)提供FIRST_LETTER、单读音转换和词组支持，声明MIT及Python3.13支持；这些是选型依据，不能替代本机验证。仅在local-lake可选组声明并锁定获准版本，部署Prod不加载；2026-10-06用户已授权依赖准入及安装；版本固定pypinyin==0.55.0（[PyPI发布记录](https://pypi.org/project/pypinyin/0.55.0/)），只在根现有.venv安装该包，不同步其它依赖。根Python3.13.5已安装并验证平安银行/PAYH、招商银行/ZSYH、深发展A/SFZA、重庆银行/CQYH、ST平安银行/STPAYH五样本；只新增这一包，中文名称转换消费者和覆盖词表在DC2实现，禁止隐式pip/uv同步。转换函数统一对名称做NFC、中文取单读音首字母、英数保留、标点移除、输出upper；不穷举多音字组合。覆盖平安银行/PAYH、招商银行/ZSYH、深发展A/SFZA、重庆银行/CQYH及ST标记；源cnspell不被转换结果覆盖。词表版本变化产生新的名称索引版本，不修改Raw。

## 6. API 合同

所有路径前缀 `/api/v1/wealth/data-center`；这是新业务域，不能把写操作放入只读market模块或让Wealth调用Ops API。统一camelCase、UTC ISO时间戳、上海业务日期；请求extra=forbid。App认证先执行，未登录401；登录但公告不提供404 `DC_MODULE_UNAVAILABLE`。

### 6.1 路由

| 方法/相对路径 | 输入 | 输出/行为 |
| --- | --- | --- |
| GET `/modules` |无 |首页模块；Prod `modules:[]`，本地公告卡不受拔盘影响 |
| GET `/announcements/context` |无 |部署/盘/来源/index/当前run可用性、默认参数；无全盘统计 |
| POST `/announcements/queries` |startDate?,endDate?,tsCode?,titleKeyword?,downloadStatus=all |200 ready/empty或202 preparing，queryId与第一页；仅本地查询，无源站HTTP |
| GET `/announcements/queries/{queryId}` |page=1 |准备进度或同revision结果页；刷新新建query，不隐式改旧条件 |
| GET `/announcements/companies` |keyword,startDate?,endDate? |≤20候选及hasMore；scope未就绪202，输入空则items=[]；300ms前端防抖 |
| POST `/announcements/previews` |startDate,endDate,intervalSeconds |202 previewId；一份后台本地准备，不创建下载run |
| GET `/announcements/previews/{id}` |无 |preparing/ready/empty/error/cancelled，五统计及日扫描量 |
| POST `/announcements/previews/{id}/stop` |无 |幂等停止本地准备，零HTTP |
| POST `/announcements/runs` |previewId，`Idempotency-Key` header |202 runId；检查ready/TTL/参数/来源，claim成功才接纳 |
| GET `/announcements/runs` |cursor?,limit≤20 |currentRunId +最近执行页；无巨大全部历史数组 |
| GET `/announcements/runs/{id}` |无 |完整TaskDto +关联retry批次摘要分页入口 |
| GET `/announcements/runs/{id}/related` |cursor?,limit≤20 |同根日期run及关联retry历史，keyset分页，不返回巨大嵌套数组 |
| GET `/announcements/runs/{id}/files` |result=all/failed/pending/succeeded/reused，cursor?,limit≤50 |文件结果/失败原因/本批尝试；精确run集合 |
| POST `/announcements/runs/{id}/stop` |无 |202 stopping；终态/已请求返回当前状态；只能控制活动run |
| POST `/announcements/runs/{id}/continue` |Idempotency-Key |202原run恢复；只能sealed停止/阻断/中断且有pending，失败不包含 |
| POST `/announcements/runs/{id}/retries` |scope=allFailed或singleFailed、single时artifactKey；Idempotency-Key |202关联retry run；key必须原run失败且尚未解决，非任意URL/公告输入 |
| POST `/announcements/runs/{id}/recheck` |kind=volume/localSource/remoteSource |202检查；结果包含passed/blocked/unknown；通过不自动continue |

冲突409（活动run、preview过期/改变、query版本改变、不可恢复）；非法422；服务或读取依赖不可用503；query preparing202是合法状态，已封存的查询失败以HTTP200、pageState=error返回（见§21），不返回假成功空列表。不存在PDF内容/文件下载API或DG启动API。

### 6.2 核心 DTO（后端拥有业务事实）

```ts
type Availability = "ready" | "unavailable" | "preparing";
type RunPhase = "preparing" | "downloading" | "stopping" | "completed"
  | "partial_failed" | "stopped" | "blocked" | "interrupted" | "cancelled";
interface PageState { status: "preparing" | "ready" | "empty" | "error";
  code: string | null; message: string | null; asOfTime: string; }
interface AnnouncementRow {
  recordKey: string; annDate: string; tsCode: string | null;
  companyName: string; companyNameSource: "master" | "announcement" | "code";
  title: string | null; sourceUrl: string | null;
  downloadStatus: "downloaded" | "undownloaded" | null;
  statusCheckedAt: string | null;
}
interface QueryResult {
  queryId: string; pageState: PageState; catalogRevision: number | null;
  conditions: { startDate: string; endDate: string; tsCode: string | null;
    titleKeyword: string; downloadStatus: "all" | "downloaded" | "undownloaded"; };
  items: AnnouncementRow[]; total: number | null; page: number; pageSize: 50;
  hasPrevious: boolean; hasNext: boolean; downloadStatusAvailable: boolean;
  preparation: { datesScanned: number; datesTotal: number; recordsScanned: number; } | null;
}
interface CompanyCandidate {
  tsCode: string; name: string; initials: string | null;
  matchedAlias: string | null; nameSource: "master" | "announcement" | "code";
  matchKind: "exactCode" | "codePrefix" | "name" | "initials" | "alias";
}
interface PreviewDto {
  previewId: string; state: "preparing" | "ready" | "empty" | "error" | "cancelled";
  startDate: string; endDate: string; intervalSeconds: number;
  recordCount: number | null; artifactCount: number | null;
  missingUrlCount: number | null; reusableEstimate: number | null;
  downloadEstimate: number | null; canStart: boolean; expiresAt: string | null;
  preparation: { datesScanned: number; datesTotal: number; recordsScanned: number; };
  error: { code: string; message: string; } | null;
}
interface TaskDto {
  runId: string; rootRunId: string; retryOfRunId: string | null;
  batchKind: "date" | "retry"; phase: RunPhase; revision: number;
  startDate: string; endDate: string; intervalSeconds: number; archiveLocation: string;
  createdAt: string; startedAt: string | null; finishedAt: string | null;
  recordCount: number; missingUrlCount: number; // retry时为原范围背景，非本批失败数
  total: number | null; processed: number; succeeded: number; reused: number;
  failed: number; remaining: number | null; percent: number | null;
  unresolvedFailureCount: number;
  preparation: { datesScanned: number; datesTotal: number; currentDate: string | null; };
  current: { artifactKey: string; annDate: string; tsCode: string | null;
    companyName: string; title: string | null; attemptNumber: number; maxAttempts: 3;
    bytesReceived: number; bytesTotal: number | null; transferState: "receiving" | "verifying"; } | null;
  wait: { kind: "interval" | "backoff" | "cooldown"; until: string; } | null;
  businessUpdatedAt: string; heartbeatAt: string; etaSeconds: null;
  blockedReason: { code: string; message: string; } | null;
  actions: { canStop: boolean; canContinue: boolean; canRetryFailed: boolean;
    canCreateNew: boolean; canRecheck: boolean; reason: string | null; };
  check: { state: "checking" | "passed" | "blocked" | "unknown" | "cancelled";
    kind: "volume" | "localSource" | "remoteSource"; code: string | null;
    updatedAt: string; } | null;
}
```

Context明确：`moduleEnabled,archiveAvailability,sourceAvailability,indexAvailability,archiveLocation,currentRunId,queryDefaults,downloadDefaults,policy,observedAnnDate,lastIndexedAt,sourceUpdateSucceededAt`。后两种时间不能混写：lastIndexedAt是本地投影时间；没有正式DG成功证据时sourceUpdateSucceededAt=NULL，不以文件mtime/顶栏市场日替代。R1不新增同步监控卡，必要提示使用页面状态区域。

首页模块项只含`moduleKey/title/description/path/badge`，默认不带全量统计；moduleEnabled只按部署配置，与当前readiness无关。API context读取最近后台核验摘要及本次轻量mount/device判断，不在每次轮询同步执行最长10秒diskutil；严格卷信息由准备/执行/显式重新检查核验。history读本机台账，不依赖外盘在线或执行写探针。页面不能把来源/磁盘摘要缓存当作下载启动preflight通过。

Files DTO含`artifactKey,representativeRecordKey,annDate,tsCode,companyName,title,result,attempts,lastError:{code,message,httpStatus},canRetry`；source关联多行时详情可分页查看，不重复增加文件总量。结果为pending/processing/succeeded/reused/failed；停止/阻断的当前未完成文件回pending，保留attempt日志。错误详情只允许安全结构化原因，不暴露原始异常字符串。

### 6.3 样例与计数断言

```json
{"previewId":"p1","state":"ready","startDate":"2026-09-01","endDate":"2026-09-30","intervalSeconds":5,"recordCount":1028,"artifactCount":1000,"missingUrlCount":8,"reusableEstimate":10,"downloadEstimate":990,"canStart":true,"expiresAt":"2026-10-06T02:15:00Z","preparation":{"datesScanned":30,"datesTotal":30,"recordsScanned":1028},"error":null}
```

运行样例：total1000、processed320、succeeded300、reused10、failed10、remaining680、percent32。结束样例：processed1000/remaining0、980/10/10→partial_failed；990/10/0→completed。重试10项：total10、processed3、success3、remaining7、percent30；单项重试total1。原missingUrlCount8始终是背景，不加入retry分母。准备total/percent/remaining=NULL。合法无结果`pageState.empty/items[]/total0`；来源不可用`pageState.error/totalNULL`；外盘状态无法核验允许元数据页显示，但downloadStatus=NULL、显著提示且禁用状态筛选，不呈现第三种行状态文字。

## 7. 状态机、并发与幂等

### 7.1 执行状态

```text
预览 preparing → ready / empty / error / cancelled（不是下载run）
create → run.preparing → sealed.downloading → completed / partial_failed
preparing/downloading → stopping → stopped（未封存则cancelled）
活动阶段 → blocked / interrupted
sealed.stopped/blocked/interrupted + pending → continue → downloading（同run）
终态 + unresolved failed → retry run（固定子集合，关联根run）
```

准备停止：不生成sealed，不可Continue，重新预览才能建新日期任务。准备源码变化：blocked且canContinue=false，先重新预览；草稿行保留诊断，不参与下载。正常source os.replace不破坏已封存输入。

所有命令先后端判定actions，不信任UI disabled。终态被stop是幂等no-op，不能改成stopped覆盖completed。Continue已有活动执行409，重复同幂等键返回原结果。retry只接受终态的目标run与合法失败集合，拒绝正在执行run的失败项即时并行重试。

幂等键与命令payload hash、archive identity持久化于`command_receipts(key,kind,payload_hash,result_run_id,state,created_at)`；同key同payload返回同run，同key不同payload409。先做事务/锁接纳再返回202；不得响应成功后才发现无人执行。receipt提交后崩溃由owner恢复标interrupted，不重复创建。无任务队列；supervisor只处理已接纳的单active slot。

Idempotency-Key由客户端每次明确create/continue/retry意图生成UUID，网络响应丢失重发沿用原key，不能每次自动换key；重复点击按钮本身禁止，但不能只靠按钮防重复。请求日期严格YYYY-MM-DD、interval拒绝NaN/Infinity、title≤200字符、公司keyword≤64、fileKey为64hex，query/run/previewId为UUID；所有public path/id/枚举与额外字段由后端校验。

### 7.2 双锁与owner恢复

1. 本机 Application Support 的`execution.lock`每个archiveId只允许一个写执行owner，不受外盘掉线锁文件inode变化影响；只在实际执行/维护/迁移期间持有，不在Web空闲时永久选举owner。
2. PDF运行/维修/CLI继续使用原归档`.state/archive.lock`外盘独占锁。接纳命令的进程先取得本机执行锁，再取得外盘锁，任何冲突立即409；CLI也取得两把锁及active slot，不能只更新Web一侧。
3. schema迁移、create、continue、retry、repair按本机锁→外盘锁→短SQLite事务同一顺序。create持锁确认线程已经启动并拥有run/资源后才返回202；锁/连接由线程资源上下文接管，SQLite连接在线程内创建，不跨线程使用。空闲多Web进程均可尝试接纳，但只能一个成功。创建失败/崩溃保留receipt/run为阻断或中断，不遗留永远preparing的假任务。
4. 其它Web进程从SQLite观察，stop使用短控制事务CAS写stop_requested_at，不需要获得PDF执行锁；owner每0.5秒检查。非owner绝不start另一个线程接管active run；continue/retry仍须取得两锁。只读查询不取写锁。
5. owner_token随机进程实例标识，heartbeat5秒；线程只领取该token所属run。失联15秒仅提示观察失联；启动恢复只有取得锁、确认旧owner不再执行才将active事实标interrupted并释放slot，不能只凭心跳超时抢走慢请求。恢复不依赖外盘必须在线：本机执行锁证明旧执行已结束即可标中断；后续实际Continue必须重获外盘锁。
6. App关闭先禁止新接纳、请求安全停止，最长30秒等退出；结束标interrupted（用户stop则stopped），保留checkpoint。不可安全回收则进程退出释放锁，新实例核验恢复；新实例**不自动HTTP**。Ctrl+C/进程kill及多进程同时恢复均需独立进程测试。

不由请求生命周期/用户登出取消任务。所有登录用户共享可见与操作；actorId仅留审计记录，后端必须处理同时停止/继续/重试的冲突。

## 8. 下载物理协议、网络与观察

目录`YYYY-MM-DD/完整ts_code/清洗标题.pdf`，冲突追加稳定key后缀，NFC/casefold及字节预算沿用Files；不按名称重命名已有文件。prepared→part size/hash→同目录replace→dir fsync→succeeded唯一链，未知/损坏旧文件保留、新路径归档，禁止强制覆盖/清理证据。

文件存在性检查使用相同安全目录遍历、O_NOFOLLOW、普通文件、同设备、单硬链接约束；查询绝不触发Volume.open的mkdir/写探测。下载/复用仍执行完整hash，展示检查只stat。校验过程不可用导致unknown而不是未下载。

每个批/领取/HTTP前后/重定向/64KiB读取/指纹循环/0.5秒等待前后检查stop；同步网络调用最大read15秒，文件总deadline600秒；停下不领取新文件。已提升文件来不及观察提交时恢复补记，不回滚业务文件。Sources固定日与sourceScope校验，不每文件重新扫描Raw。

`ProgressEvent` 包含事件kind、currentkey、bytesReceived/total、attemptNumber、waitKind/until、business timestamp；Files.receive在接收字节改变时发出，校验阶段明确verifying。串行最新快照节流到≤5秒一次，文件完成/phase变化立即提交；不每chunk写SQLite。观察连接失联与执行失败独立。读取bytesTotal只接受校验过、identity编码、可靠Content-Length，未知/重定向中保持NULL，不用估算长度画比例。

正常请求结束→下一请求开始至少interval；retry等待=max(30×2^attempt,Retry-After,既有cooldown,interval)，每文件session最多3次；5重定向以内每跳单独过limiter。网络/408/429/5xx可自动重试；404/无效PDF/非法标题等单文件失败继续下份；403/captcha、卷/空间/来源、持久台账控制失败全局blocked。等候remainingTime由until减上海展示时钟得到，仅显示已知期限；ETA不由比例猜测。

网页不允许提交任意URL。Source里的非HTTP(S)、用户信息、控制字符、解析错误记文件invalid_url；合法公共目标在每跳解析校验，禁止localhost、loopback/linklocal/private/reserved/IP literal内部目的地；连接须绑定已验证解析结果并保留原Host/TLS名称，不能“DNS先查再普通httpx二次解析”留重绑定窗口。使用现有httpx transport扩展的单一受控连接实现、默认trust_env=False；不得为绕过引入代理/新下载实现。私网/不安全URL公告元数据仍保留，详情协议不安全则禁用链接并提示地址不可用。公共源站样本与解析/redirect/IPv6/rebinding负例是DC1门禁，不使用任意后端抓取API。

`recheck(volume/localSource)`只查本地，返回可继续条件但不触发同步/下载；`remoteSource`用于403/captcha阻断：取得共同锁，用原冻结阻断URL最多一次探测session（重定向≤5），同Limiter按interval/cooldown等待，读取最多1024字节前缀并关闭，不写PDF、不更改成功量；403/验证码仍blocked，2xx且非挑战才允许用户另点Continue，不保证后续每个文件成功。检查显示“检查中/等待冷却”，可停止；未到cooldown期限不发请求，不并行探测所有URLs，不把只读本地来源检查说成源站恢复。recheck状态记录在原run的独立check字段，不改下载phase/counters；`recheck` POST返回202后GET run得到checkState/checkKind/checkCode/checkUpdatedAt；stop在checking时取消该检查，恢复原blocked状态，绝不将检查当新文件处理。

## 9. 页面、交互与 Figma 对照

路由：`/wealth/data-center`；`/wealth/data-center/announcements?tab=query|downloads`。默认query，切tab保留筛选草稿/已应用条件，但不影响下载。历史详情用`runId`，不能让任意路径参数成为文件输入。返回/前进遵守现有routerState，登录redirect保留路径；未知tab纠正默认query，未知run显示不可获取/返回历史。

复用TopMarketBar、既有context行情条、面包屑、--cs-* token、Noto Sans SC/Roboto Mono；数据首页activeNav=data。卡片不放全历史文件统计；Prod不渲染占位公告卡。外盘/源/索引提示独立于顶栏市场session。

查询草稿与appliedConditions分开；公司选中后完整代码赋值，继续编辑文本即清除旧选择；非空未选候选点击查询显示“请先选择公司”，不能静默取第一项/查所有。候选上下键/Enter/Escape、失焦取消；请求300ms防抖、AbortController/sequence防过期响应。标题trim外部空白后原文包含，不大小写/语义扩写。Reset立即默认查询，Refresh保留appliedConditions，新queryId后回第一页；上一/下一只换页。不为日期操作新增复杂组件，使用已有日期输入/轻量原生日历，以设计token包裹；倒置/非法内联提示，禁用预览。

下载controller只持日期/interval/previewId/selectedRunId/观察状态。预览参数变化清除预览确认；空/错误日期禁用按钮。archive input `disabled`灰显，label只“归档位置”。创建区与当前/历史区状态按Task.actions渲染；正在运行压缩创建区，结束后新建恢复空日期。运行批次与原root详情分开，重试数字不能叠加到原分母。

停止弹窗可Escape/取消回继续运行；确认按钮单次提交，响应后stopping禁用；不采用Figma定时跳转。准备停止无HTTP，UI返回创建区并保留草稿诊断入口于历史（非可执行下载任务）。文件结果按all/failed等简单筛选+50分页，失败默认展开安全原因、长标题/原因可展开完整文本；无删除/核验按钮。历史20分页，查看最近任务选最近run，详情显示关联retry批次、各自结果和原错误。

轮询当前/所选run每2秒，任务历史只在打开/操作结果后刷新；最多一个poll请求，页面卸载停止观察而不stoprun。请求5秒超时→连接状态暂不可获取，显示最后业务更新时间；恢复重读，不改执行phase。终态停止高频轮询。无任务显示idle，不能将401/503映射idle。没有浏览器本地下载台账/任务事实。

| Figma节点（24个） | 实现状态/组件 | 关键验收 |
| --- | --- | --- |
| 1944:80 / 1944:81 |DataCenterPage本地/Prod |T01/T02卡片及空首页 |
| 1944:82 / 1944:83 / 1950:1612 |QueryPanel/List/CompanySearch |T03—T07六列、候选选择、交集 |
| 1944:84 / 1944:85 / 1950:1618 |CreateDownloadPanel空/有效/倒置 |T08灰路径、日期/间隔 |
| 1944:86 |PreviewPanel |T09五统计、调整/开始 |
| 1944:87 |PreparationProgress |T09/T11准备停止、不假百分比 |
| 1944:88 |TaskProgress |T11实际字节/处理分母 |
| 1944:89 / 1944:90 / 1950:1613 |RunResult/RetryProgress |T13失败10/全部10/单个1 |
| 1944:91 |StoppedResult |T14/T15只继续680 |
| 1944:92 / 1950:1617 |BlockedResult |T17外盘/403检查与手动继续 |
| 1944:93 / 1944:94 |QueryEmpty/QueryError |T02/T06/T07空0与unknownNULL |
| 1944:95 |CompletedResult |T11/T18 990+10，8无URL背景 |
| 1944:96 |已确认规则总览，非运行页面 |R01—R19对账，不做产品评审管理功能 |
| 1950:1614 / 1950:1615 / 1950:1616 |StopDialog/Stopping/Interrupted |T14/T15确认、安全停止、手动恢复 |

原型数字/文件、准备定时跳转不是运行事实。source拒绝画板的button内部节点name仍为“重新检查外盘”，可见文案是“重新检查来源”；实现依据可见文案/产品语义使用remoteSource，而非复制原型节点名调用外盘检查。完整分页/日历/错误展开/全部结果为上述实现细化，不扩大产品功能，不改变Figma共享组件；DC4须补对应交互截图供review。

## 10. 异常与性能

异常唯一注册位置为 [注册表](../../system/exception-code-registry.md)的数据中心章节。内部reason→注册码转换只在Biz响应/观察适配层，Ops保留安全reasoncode；HTTP非重试失败可作为`DC_FILE_FAILED`详情httpStatus，不为每个状态码建立新公共异常。

| 错误范围 | 行为 |
| --- | --- |
|来源/合同/索引 | error或preparing，不填zero/旧日期ready，不自动DG同步 |
|盘/状态不可核验 | 保留本地入口与历史；metadata可读时状态NULL/禁状态筛选，不能新增第三种业务状态 |
|命令冲突/过期 | 409并重读current/preview/query；无后台队列 |
|文件错误 | 记失败、本批最多3次，允许原失败retry；无URL单列非失败 |
|全局阻断 | 不领新unit、保留成果、解释恢复动作；检查通过仍手动continue |
|观察请求失败 | 客户端观察error，不把run改failed，不重启HTTP |

预算见方案§7。SQL期限4秒/客户端5秒；长本地准备202+进度，不让页面挂住。Source每阻塞调用15秒watchdog，catalog每日unit60秒软预算：达到后保留未发布checkpoint并中断连接/停止准备，返回明确超预算错误；不丢行/截断范围。索引写事务每500行，GC每500keys，SQLitebusy等待总计≤4秒。字节/心跳≤5秒持久化，不和文件提交同失败域。常驻RSS目标≤512MiB，SQLitecatalog/tables体积、所请求日期D/源行R/成功文件K/SQL次数/最慢调用都记录。

容量验收：默认30自然日、代表性大日（≥50k公告，若实际不存在用隔离样本）、多年约8m记录索引，成功台账K=34,188及更大模拟量，深页/contains/状态过滤/预览。全历史索引按需求增量形成，不在测试中把正式Lake复制到本机；正式读取只read-only profiling。记录耗时/内存/索引空间/扫描文件数，不用编造P95；超预算优化后重测，不加并发PDF下载或弱化校验。预览与准备HTTP次数0；实际请求量=首次未复用文件的请求+必要重定向/有限重试，不乘公告记录数。

## 11. 核心测试与编码门禁

### 11.1 真实合同和用户可见用例

核心字段：六列表字段/下载状态available/checkedAt、默认筛选/名称来源/候选alias、preview五统计、total/processed/success/reuse/fail/remaining/percent、currentbytes/attempt、waitkind/until、businessUpdatedAt/heartbeat、phase/actions、历史原批/重试批关系、所有错误状态。

T01—T19各需正向与禁止项反例，尤其：

1. 真实Web路由→Biz→DAO/执行器，使用临时Parquet/SQLite/外卷检查替身及本地HTTP fixture；**不mock查询/服务**。401、本地200、Prod404、只读首页/列表零源站请求。正式DB/Lake不作为测试写目标。
2. 两条同日期/代码/URL、不同name/title/rec_time的公告两行、一文件；URL=NULL/空串、rec_time=NULL可保存；重现同标题有URL/无URL两行均保留（最新“六字段完全相同才丢弃”规则），不恢复旧group合并。
3. 320/1000含10失败；停止/重启/观察失败/HTTP等待/文件提交之间每个窗口取消、退出、续跑、幂等重放、进度单调；业务成功不因观察写失败回滚。
4. 用源新版增加公告证明preview需重准备、sealed继续/失败retry绝不扩大；模拟失败10、单项1、all10；其它成功/同日新公告HTTP为0。
5. 状态筛选记录在第51页附近、重复artifact多行、删除成功文件、unknown/拔盘、页面前后版本变化；SQL总数/分页与物理检查一致，hash调用0。
6. CLI参数/输出/退出码/schema1/2readonly不变，升级3保留旧路径/历史/冷却；未知schema、迁移失败、双进程/CLI/Web锁竞争。
7. Wealth真实API展示smoke：登录→首页卡→搜索PAYH→查公司/标题→外链新标签→空日期→预览→准备/进度→停止确认→继续→原失败单项/全部→历史关联→Prod/拔盘/来源异常。禁用mock adapter，逐字段和网络次数断言，检查console/network及Figma1600×1080和常用窄桌面溢出。

计划测试文件：`tests/web/test_wealth_data_center_api.py`、`tests/test_announcement_archive_runtime.py`、`tests/test_announcement_catalog.py`，以及原三个公告专项；前端在feature/page同目录Vitest测试。命令在文件实现并确认隔离后执行，不在本轮运行不存在测试：

```bash
.venv/bin/python -B -m pytest -q tests/test_announcement_download_cli.py tests/test_announcement_download_dg.py tests/test_announcement_ledger.py tests/test_announcement_archive_runtime.py tests/test_announcement_catalog.py tests/web/test_wealth_data_center_api.py
.venv/bin/python -B -m pytest -q tests/architecture/test_subsystem_dependency_matrix.py
npm --prefix wealth run typecheck
npm --prefix wealth test -- src/features/data-center src/pages/data-center src/app/routes/routerState.test.ts
npm --prefix wealth run build
python3 scripts/check_docs_integrity.py
git diff --check
```

最小真实验收另获授权，使用独立归档/台账及已验收DG小日期：运行→停止→继续→原失败retry→零请求重放→size/hash读回；删除后恢复仅在获准隔离文件做，不删除用户既有PDF。正式DG连续日常检查仍是独立验收，页面通过不代替它。

### 11.2 Wealth通用清单映射（逐项）

| 清单条目 | 适用与本模块证据/门禁 |
| --- | --- |
|2.1事实链 |适用；产品/Figma→方案→本文；技术评审尚未完成，不预填开工通过 |
|2.2后端事实 |适用；§6 DTO和T03/T07/T11，无前端统计拼装 |
|2.3状态机 |适用；§7/9，loading/preparing/ready/empty/error/失联测试 |
|2.4显示语义 |适用；系统token与明确下载状态；不使用行情红绿猜结果 |
|2.5过程测试 |适用；§11.1停止/恢复/观察失败完整过程 |
|2.6同轮同步 |适用；§12交付对账、字段/样例/页面同步 |
|2.7渐进替换 |适用；只接新data-center，不动旧行情mock/real；部署开关可回退，不自动降级mock |
|2.8消费者合同 |适用；API/schema/CLI迁移与前端逐字段断言 |
|2.9图表坐标 |不适用；无市场图表，仅0—100处理进度，T11另验 |
|2.10SQL下推 |适用；count/filter/分页下推SQLite；标准SQL无需PG特有函数兼容 |
|2.11配置 |适用部署/词表；§5来源/重启/版本；不接策略中心新市场策略 |
|2.12门禁矩阵 |适用；本表、§1及§11.3，不默认继承 |
|2.13例外 |适用；§11.3登记本地异步准备/非market写API，无图表例外 |
|2.14显式坐标 |不适用；无行情图；percent由后端0—100/null驱动不重算 |
|2.15双图对齐 |不适用；无双图，页表长文本/窄宽布局另有smoke |
|2.16文案单行 |适用；灰路径、计数/按钮/等待标签，长标题与错误展开；浏览器截图断言 |
|2.17核心真实测试 |适用；§11.1字段、真实路由/浏览器和命令 |
|2.18八原则 |适用；方案§8、本文R矩阵与正负例逐条对应 |

### 11.3 模块例外与开工检查

例外范围仅此模块：①非market的data-center API承载本地维护命令，因为产品已批准下载操作；②4秒读预算内无法完成的大范围本地准备返回202，页面2秒poll，不伪装ready；③外盘不可核验时downloadStatus可空且单独banner，这不是第三种业务下载状态；④保留既有SQLite归档run事实，不新增Prod TaskRun/DG下载任务。均须技术评审，不修改统一架构矩阵。

| 门禁 | 当前设计状态 | 后续通过标准 |
| --- | --- | --- |
|参数/字段/样例/状态/异常/查询草案 |本文已定义 |评审无歧义，API逐字段实现 |
|配置审计与中文依赖 |DC1获准安装0.55.0；DC2词表/索引/开关及消费者验收完成 |当前见§15；页面context消费者仍待DC4 |
|schema消费者/分层 |DC1旧import清零、1/2/3只读；DC2纯端口装配及依赖门禁通过 |正式迁移另验，不将临时验证视为正式升级 |
|性能 |DC2查询容量；DC3五万单日及800万预览点时样本 |异步预览10.5/41.4秒、峰值127MiB；真实归档仍待DC5 |
|真实API/前端/物理验收 |DC2/DC3真实路由及本机HTTP fixture完成；页面和正式归档未执行 |24画板与最小真实归档分别待DC4/DC5 |
|评审确认 |2026-10-06用户确认路线并分阶段授权DC1、DC2、DC3 |每阶段独立验收；产品已确认不重复拍板 |

## 12. 实施对账与文档关系

执行DC0—DC5顺序见方案§9。DC1先完成共享能力移位/台账/CLI回归，再DC2查询、DC3后台、DC4页面、DC5独立验收；不得先写页面mock当最终产品。每阶段记录R01—R19实际代码/测试/真实证据和未完成项。

原PDF文档新增网页扩展引用，不抹掉M0—M3/DG/维护历史证据；产品规则不改，只补技术文档入口；README索引与异常注册同轮更新。正式DG合同不变，consumer AST测试继续；若实际源/运行语义与本文冲突，先说明并修正文档，不使用兼容旁路或猜测补丁。

2026-10-06技术路线、DC1和本地依赖已获用户确认；DC1实现与隔离验收见§14。DC2已获后续授权，当前交付见§15；DC3后端交付见§17；DC4—DC5尚未实施，后端完成不代表网页或正式归档验收完成。

## 13. DC1授权与执行约束（2026-10-06）

用户确认按本文进入DC1，并授权pypinyin本地可选依赖。DC1只迁移共享核心/CLI消费者、实现schema3及执行基础，隔离验证旧数据保留、幂等结果、进程退出、锁、冷却和安全HTTP。正式台账/索引、真实PDF、DG/Prod、页面/API不在本阶段执行范围。

| DC1硬约束 | 代码/验收落点 |
| --- | --- |
| 唯一核心，无旧包转发 | Foundation clients/DAO、Ops executor、两CLI及全部fixture；引用清零/架构测试 |
| 身份/路径/CLI行为保持 | source_projection、Files/Volume、parse_options；原专项回归 |
| schema1/2只读不升级，写入口原子到3 | Ledger/schema定义；临时SQLite字段/行/冷却对账、失败回滚、未知schema拒绝 |
| 一个执行，双锁/持久slot，退出不自动HTTP | 本机execution.lock→外盘archive.lock→短事务；双进程及退出fixture |
| 500批/日封存后HTTP，取消/恢复保留成果 | Ops executor/Source/DAO；原进程退出、prepared/rename故障测试 |
| 原历史和成功事实不因观察失败回滚 | Ledger.result/phase、Files；幂等计数与观察失败窗口 |
| 全部跳转公共目标且绑定已验证IP | HTTP transport、Limiter；DNS/IPv6/私网/redirect负例 |
| 仅获准依赖，本地可选且固定版本 | pyproject local-lake pypinyin==0.55.0；现有Python3.13样本，无Prod自动加载 |

## 14. DC1交付对账（2026-10-06）

[验收报告](../../../../reports/wealth_data_center_dc1_acceptance_20261006.md)及[机器证据](../../../../reports/wealth_data_center_dc1_acceptance_20261006.json)。单一核心/DAO/Ops执行循环与两CLI、三个原专项及fixture消费者迁移完成。DAO查询不编排文件；verify在Files，repair在Ops。旧主实现包删除，无转发兼容层；core/source逐字节保持原身份、Raw合同及读者。

schema1/2→3只在写入口、调用方取得本机/外盘双锁后、单事务完成；正式台账未升级。只读识别1/2/3；原字段、路径、结果、来源、尝试次数和冷却保留。新增attempt_open/session_open为未结束尝试/会话的partial index，避免孤儿恢复扫描全部已结束记录；创建表定义及严格验证见DAO schema/ledger。run结果重放幂等，不能把旧失败outcome改成功；新run另保存新结果。同一owner不得接纳两个活动run，显式新命令恢复旧owner中断事实，不自动HTTP。全局业务进度时间只随已提交批/日/文件结果改变，heartbeat不伪装完成。

单一HTTP transport使用现有httpx0.28.1/httpcore1.0.9，DNS全答案检查并绑定数字IP连接，保留Host/SNI，无连接复用/隐式代理；私网/特殊地址/重定向负例通过。新文件代表标题在封存前按可用标题+recordKey稳定选取，旧文件title/path保留；同文件多源记录仍分别保存。

完整387项通过；最终目录职责收敛后受影响217项复测通过，随后提交9ad6654c。原SIGINT/进程退出/续跑/prepared/rename/冷却、观察失败不回滚PDF、CLI/Raw/架构专项均通过；definition/resolver/runtime registry与ingestion lint通过。正式2026-07-26只读5条/footer5、指纹与原验收一致，零台账打开/远程PDF/来源写入。

R03身份/缺值、R12基础限速/尝试、R14CLI取消、R15中断事实、R16文件协议及R19架构基础已按DC1落地；R10双锁/slot基础、R11存储/计数基础通过。网页预览/精确继续与失败retry/线程管理、DTO/认证/capability、日期索引和搜索、页面/轮询仍按DC2—DC4开发；这不是R01—R19整体完成。正式迁移、索引及最小真实归档仍待阶段授权。

## 15. DC2授权、硬约束与当前实现（2026-10-06）

用户指令“提交吧。然后推进DC2”：DC1按相关路径白名单提交9ad6654c，随后执行本阶段。不开新分支，不提交其他任务的工作区文件。DC2当前代码尚未提交；正式索引/台账、真实下载与部署不在本阶段验证范围。

| DC2硬口径 | 真实落点与测试 |
| --- | --- |
| 正式Raw六字段、日期自然日、记录和文件身份不变 | 原Source/core逐字节保留；CatalogBuilder逐批source_projection；临时Parquet/空值/不同记录同文件/缺日和零行测试 |
| 可重建日版本，500批，校验后发布 | Foundation Catalog SQL、Ops CatalogBuilder；重复/失败/停止/重放/源replace及同inode改变负例；未发布版本不进入count |
| 名称优先级/别名/首字母，包含退市和主表外代码 | NameSnapshot固定Raw两snapshot，无上市状态过滤；NameInitials+版本词表；Biz CompanyQuery当前名/历史命中排序；实际SFZA历史命中证据 |
| 30自然日/50条、稳定顺序、字面标题 | DataCenterPolicy、请求DTO、AnnouncementQuery；上海跨日、ties/深页、%/_、额外参数/倒置日期422 |
| 状态先全范围再分页；删除/unknown不伪造 | ArchivePresence只读Ledger+安全stat、500keys query_presence；同文件多行/后续页/删除后409或刷新未下载/断盘NULL；不hash、不改台账 |
| 准备不阻塞API、不伪造部分总数 | App lifespan独立串行本地查询准备线程，Biz prepare_next，持久query_snapshots/builds；202 total=NULL，完成后短SQL读快照；不发HTTP |
| 登录访问、Prod首页无卡/API和直达404 | Foundation capability+Settings，App统一get_current_user装配，Biz独立API；真实App路由/401→404/同路径不开启/本地卡不受盘可用性影响 |
| 原CLI和分层边界保持 | 两CLI/旧schema只读回归；新CatalogPreparationPort/ArchivePresencePort由App注入，无Biz↔Ops直接import；CodeGraph/架构门禁 |

明确的实现细节：queryId为不透明的来源scope摘要加随机id；换卷后旧id明确409而不命中新来源。查询只读连接query_only；索引writer锁、WAL/FULL，未知schema不能清空重建。台账仍DELETE/FULL，查询不持有SQLite事务做stat；Ledger只读timeout允许调用方按4秒预算传入，原CLI默认5秒不变。名称原cnspell保留，检索首字母去标点并转upper；NULL/空名称在候选键中用空占位，公告六列原值仍保留在catalog_records，不据此丢行。

列表先取得50条稳定排序keys，再补公司名称；同一个SQL读快照读取已封存的逐日匹配数和页面keys。用日匹配数定位页起点，只在相关日做局部offset，不对8m范围先补名再OFFSET。匹配数的准备前后校验revision，状态筛选先完整准备presence；任何失败/变化不发布部分统计。源码用日期外层与日generation范围计数、列表覆盖索引，避免先为全历史行补名称再OFFSET。状态presence准备只写临时查询事实；all页可在归档状态无法核验时继续展示元数据并返回NULL状态；过滤页不可将unknown当未下载。query ready后开始的15分钟TTL和revision变化均触发409要求新查询。名称词表版本标在每个日版本，避免词表更新后只重建master却遗留公告别名旧首字母。

模块开关在两个env示例默认false，Settings统一读取。仅dev/local加true生效，Prod强制关闭；本轮不修改本机运行env或启动Web，不执行正式索引初始化。启动时来源身份核验在后台完成；尚未就绪时503，不同步阻塞API执行diskutil。后台30秒核验来源/卷，API只做轻量mount/device与所请求分区版本检查；首次准备和变化时完整读取校验。断盘后保留卡，恢复后可重新准备查询，不触发DG或PDF下载。

配置、SQL、DTO、公共异常沿用本文§5/6及异常注册表，未增加用户参数或第三种下载状态。R01/R03/R05/R06/R07和R19查询部分按本阶段验收；R04外链前端、R08—R18网页下载管理/预览/进度/恢复及页面仍待DC3/DC4，不能把只读API完成当成整个产品完成。

准备阶段持久化updated_at、preparation_stage、dates_counted、artifacts_checked。PageState.message分别显示索引准备、文件检查数量、匹配日期统计数量，asOfTime取真实业务更新时间；不增加第三种下载状态，也不把心跳当业务进展。preparation保留原datesScanned/datesTotal/recordsScanned字段；ready之前total和catalogRevision可为NULL。GET拒绝额外/重复参数，POST仅接受DTO字段，不接受浏览器路径、URL或其他创建下载参数。

所有API读操作进入共享5秒read_budget；Catalog和只读Ledger的连接/SQL超时取剩余时间与SQL4秒预算的最小值，避免每段独立耗时4秒叠加。该ContextVar在请求退出后还原，不污染后续请求或后台逐日准备。后台每个SQL仍4秒，每日索引60秒软预算；不宣称能强行中止内核磁盘IO。

最终组合257项通过（39.77秒），覆盖真实路由、50k日100批、日匹配数损坏/版本变化、旧presence重建、准备TTL、原CLI/DG/台账与架构。800万隔离记录最初全范围COUNT/OFFSET超预算，优化后全历史首屏0.002秒、第159999页0.017秒；标题/状态统计后台40—80秒，完成前202并逐日显示业务进度。实际30日29619条冷构建30.624秒、复用0.290秒、首屏0.089秒，存在性34188/50000个隔离文件分别0.746/1.129秒。点时数值不是P95，800万状态SQL样本不等于真实文件stat规模；正式10月5日Raw缺日如实阻断。

完整证据和未执行项见[DC2验收报告](../../../../reports/wealth_data_center_dc2_acceptance_20261006.md)及[机器证据](../../../../reports/wealth_data_center_dc2_acceptance_20261006.json)。本节为DC2提交前交付记录，随后提交a1b47713；正式索引/台账、真实下载、实际Web启动、DG/Prod/Lake写入和前端均未执行。当前DC3进展见§17。


## 16. DC3授权与开工约束（2026-10-06）

用户“提交，然后继续推进DC3”：DC2已提交a1b47713。当前只实现§5—8中日期预览、下载命令/后台、进度、停止、原任务继续、原失败精确重试、重新检查、历史及文件结果API；不写前端、不运行正式迁移或真实下载。保留原CLI入口/退出码及日期重放语义，下载循环抽为同一个执行实现。

| 必须口径 | 本轮代码/测试落点 |
| --- | --- |
| 只日期+非负有限间隔、固定默认目录 | DTO/DownloadService；额外公司/URL/路径、倒置/NaN/无日期拒绝 |
| 预览只本地读取，五统计完整、日版本固定 | PreviewRuntime+Catalog预览表；源/归档变化或TTL过期409，无URL不失败，零文件不建run |
| 先双锁/短事务接纳，线程拥有资源才202 | Supervisor+ExecutionLock/Volume+command_receipts；多进程/CLI争锁、同key同payload、变payload负例 |
| 500批、全部日封存后HTTP | 共享Executor+Ledger；中途取消/来源变化不发HTTP，已提交日/批保留 |
| 停止/退出保留成果；重启不自动HTTP | 持久stop_requested、owner恢复/session/slot；进程退出和原集合继续 |
| Continue只outcome=NULL，retry只尚未解决失败key | ExecutionDAO短事务及keyset500复制；新增同日公告、旧成功/失败不被Continue纳入，单项1/全部失败10 |
| processed=success+reuse+fail，观察不回滚文件 | WebControl/RunQuery/共享Files；字节/等待、业务时间与心跳分开，结果写失败物理证据保留 |
| 历史/文件分页、拔盘仍可读，所有登录用户共享 | RunQuery+只读本机Ledger；schema1/2只读，旧集合无完整证据不允许恢复；未知schema阻断 |
| recheck不自动继续、不清冷却 | 共享Downloader有限probe；volume/localSource零HTTP、remote最多单session/有限redirect/1024字节 |

配置审计补充（无新增env开关或用户参数）：本机`announcement-download/web-archive.json`仅为固定网页归档的最近已验证身份绑定，不是业务事实源。保存version=1、volumeUuid、rootRelativePath、固定archiveLocation；路径位于Application Support，以0600文件、0700父目录及同目录原子replace落地，只在核验归档身份后更新。消费者为Supervisor/RunQuery的本机台账定位和退出恢复，台账仍按原UUID+相对根算法定位；无卷时读取已有绑定，不扫描其它归档或猜测UUID。绑定非法/缺失只显示不可用，不创建/迁移台账。生效为本次启动/显式命令，运维可从文件和context观察固定位置；测试覆盖替换卷、非法绑定、拔盘历史与不写探针。该绑定不允许浏览器传入路径，Prod不开启消费者。

schema3既有字段/表继续使用；预览进度、错误和版本摘要放previews.statistics的小型对象，逐日事实放preview_days，不放候选JSON。准备进度来源为相应catalog_builds/逐批已提交事实。run/history仍以既有本机台账为事实源，不新增Prod TaskRun或下载队列。文件transferState从当前artifacts prepared事实和执行观察派生，未知length保持NULL，不伪造百分比。

接纳线程需在API读预算内完成资源交接；超时/失败返回明确错误并取消尚未接纳意图，已持久receipt的响应丢失仍依原key读回，不重复创建。SQL4秒、API共享5秒、预览TTL900秒、500批及下载原Policy保持；本轮性能验收包括已有800万隔离catalog上的预览统计，真实网络只用本地HTTP fixture，正式归档另行验收。


DC3预览容量审计补充：单日反复DISTINCT+key分页会重复扫描/排序50k行，不能用于800万容量。Catalog升级为schema2，仅增加可重建preview_artifacts(preview_id,artifact_key)临时去重事实。按日期和record_key读取500条，以该表INSERT OR IGNORE得到本批新文件key，存在性检查和统计都只做一次；完成后不保留全量候选JSON。已知schema1在catalog writer锁内单事务添加表、校验并更新版本，旧索引/查询事实保留；未知schema拒绝，不清空任何数据。所有Catalog构建/查询/预览消费者和旧schema升级/回滚测试同步，正式升级本轮不执行。预览中断后分500删除本预览临时key再重算估计，旧发布日索引继续复用。

当前文件的transferState通过WebControl写入既有wait_kind中的内部verifying阶段以及artifacts.prepared事实提供；对外wait仅映射interval/backoff/cooldown，验证不是等待。无新增台账schema字段；unknown bytesTotal仍NULL。CLI只使用原Control，不增加逐chunk日志。分配/URL/标题校验失败的安全reason保存在原run attempt_log诊断行，不伪造HTTP尝试次数，后续重试不会抹掉原错误。


## 17. DC3实现与验收对账（2026-10-06）

DC2已提交a1b47713；用户授权后完成DC3下载管理后端，代码尚未提交。实际入口为App include_data_center/lifespan → Biz downloads API/DownloadService/RunQuery → Foundation纯ArchiveExecutionPort与ArchiveStore；App装配Ops PreviewRuntime/ArchiveSupervisor/WebControl，CLI和Web共用execute_run及Files/Downloader。无需新增服务或下载队列，子系统依赖矩阵不变。

| 计划硬口径 | 实现及验收 |
| --- | --- |
| R08—R09日期范围、固定归档、预览五统计 | PreviewRequest/PreviewRuntime/Catalog；真实Parquet和路由证明3公告→1文件+1无URL，缺值保留；多余公司/URL/路径、逆日期和非有限间隔422；零文件不建run；来源/归档/TTL变化拒绝接纳 |
| R10单活动执行与接纳幂等 | Supervisor双锁+Ledger receipt/session/slot；活动重复key返回原run，变payload/其它命令409，CLI争锁拒绝；进程在receipt提交后退出可原key读回，不自动HTTP |
| R11冻结和进度 | 日指纹在枚举前后核验，500提交，全部日完整后seal；准备中total=NULL；processed=成功+复用+失败，字节未知长度NULL、验证阶段、间隔/退避/冷却和独立业务/心跳时间；ETA=NULL |
| R12自动尝试和失败明细 | 单共享Downloader、持久冷却；本机真实HTTP验证重定向也有请求完成后间隔；attempts按本批，错误来自原run不可变attempt_log，后续retry不抹掉原HTTP404/标题错误 |
| R13原失败精确retry | 500 keyset复制尚未解决失败，全部10份→新批total10、单项→total1；新增同日Raw公告不进入retry，成功/reused不进入；旧failed不改写，关联历史20/文件50分页 |
| R14—R15停止和退出恢复 | 准备时停止保留已提交500行但不HTTP、不允许Continue；sealed停止只继续原pending；5种子进程os._exit窗口验证准备/prepared/rename/下载中/receipt后退出，重启不自动HTTP，文件落盘窗口零请求恢复 |
| R16物理事实独立 | 沿用fsync/prepared/hash/replace协议；结果写失败不删PDF，原成功尝试可补一次succeeded结果；新日期任务发现已删文件重新下载，非依据旧历史结果永久跳过 |
| R17—R18检查、历史与本地能力 | volume/localSource检查零HTTP；volume检查无需Raw可读，remote有限session/prefix共享冷却且不自动continue；403/验证码必须remoteSource检查通过才能Continue，本地检查不能替代，新阻断清除旧通过记录；终态stop不覆盖结果；已有绑定可离线查本机历史；1/2只读不迁移，旧合同无证据不允许精确恢复 |
| R19边界与性能 | App纯端口注入、Prod禁用/认证沿用；源/六字段身份不变；8m隔离缓存按500读写及50k真实单日API验收；无正式迁移、源站PDF或DG/Prod/Lake写入 |

关联历史使用HistoryDto（currentRunId、最多20项items、nextCursor）；每项含runId/rootRunId/retryOfRunId、日期、phase和既存计数。文件明细companyName优先使用本次冻结代表记录的公告name，缺失回退代码/未知公司，因此离线历史不依赖DG名称表；公告默认列表仍遵守§3.3当前主表名称优先规则。失败明细只返回安全中文说明及HTTP状态，不泄露本地路径或原始网络异常。

配置消费者已核对：请求默认间隔和固定Binding目录引用原DownloadOptions；原Policy按run保存，继续/重试沿用该策略。WebControl每0.5秒短读停止意图、默认5秒写一次心跳，字节观察默认5秒及阶段变化时提交；文件完成仍独立提交。预览和内部query_snapshot同事务创建，失败原子回滚；query_snapshot使用preview状态，不被公告列表的preparing准备循环领取。Catalog schema2原子添加一张标记表，未改台账schema3或源合同。

失败集合的NOT EXISTS使用家族run_id列表加artifact_key索引定位，不逐失败扫描全部run_artifacts；实际临时schema3台账110000结果行在4秒预算内准确区分50000原失败、10000关联解决和50000无关成功，未解决40000。查询计数、文件资格及retry共用该SQL。

完整组合回归468项通过（64.27秒），涵盖公告七个专项/Web、定义/resolver/runtime registry和三个架构护栏；最终Catalog/Web原子创建复核82项（41.83秒）、检查资格和分层复核88项（46.67秒）通过，最终共享台账/CLI及全部45项DC3复核206项（32.65秒）通过。ingestion lint、compileall、文档完整性/链接、diff检查及CodeGraph同步均通过。800万隔离索引预览默认30日150万记录约10.5秒、全160日约41.4秒、峰值127MiB；这是已有索引上的点时统计，不含首次构建，也不代表800万唯一文件stat。该SQL容量样本有34188个合成共享文件key；真实五万唯一文件的日期/身份/批次语义由独立Parquet API测试证明。

[DC3验收报告](../../../../reports/wealth_data_center_dc3_acceptance_20261006.md)及[机器证据](../../../../reports/wealth_data_center_dc3_acceptance_20261006.json)记录逐项落点、容量和未执行项。预览/私有快照同事务创建与回滚已有负例；403和验证码的检查门禁两类负例均已通过。当前停在DC3；R01—R19的页面显示/交互、24个Figma状态、真实浏览器和正式归档运行仍待DC4/DC5，不能提前宣称整个数据中心上线。

## 18. DC4开工约束（2026-10-07）

用户授权“提交DC3，然后推进DC4”；DC3已提交 `83ffb83f`。本阶段只实现 §9 页面与真实 API 消费，不执行正式台账迁移、索引初始化或源站下载，DC5另行验收。

代码范围：`features/data-center/{api,model,ui}` 和 `pages/data-center`；路由装配新增两条已批准路径，统一导航解析器启用 data 入口。复用现有 TopMarketBar、PageBreadcrumb、市场上下文请求和 token，不修改其它模块数据合同。CodeGraph explore/impact 已覆盖路由、认证、请求 client、六类页面导航消费者；静态引用核验补齐索引没有解析的回调消费者。

R01—R07 对应首页 capability、候选选择、草稿/应用条件、查询快照和六列分页；R08—R10 对应日期创建/预览、幂等命令与单任务观察；R11—R18 对应后端进度 DTO、停止确认、继续、精确失败重试、检查和分页历史；R19 对应接口隔离、请求取消/超时与无新增依赖。测试必须包含未选择公司、未知状态、逆日期、0秒、查询不带入下载、100%含失败、源站检查资格、响应丢失原 key、切页不停止和分页边界反例。浏览器使用隔离的真实路由/服务及临时 Parquet/SQLite，正式资源不作为写目标；极端态展示样本须与真实 API 联调证据分别标注。

DC4列表每页50条仍由后端分页，页面表区上限494px并独立滚动（30px表头+8×58px行高），分页操作留在区块底部。表头随表区滚动固定；历史及文件结果复用同一滚动容器。24状态的罕见阻断/中断/停止中另以临时台账合成事实做视觉验收，证据与真实执行主流程严格分列，不能据此声称源站或正式磁盘已验收。

## 19. DC4当前交付与对账（2026-10-07）

页面实现位于`wealth/src/pages/data-center`，feature依次拆为`api`合同/调用、`model`查询和下载意图/串行观察、`ui`六列查询/日期预览/进度/停止弹窗/文件与历史。现有WealthRouter增加两条受登录壳保护的路径，routerState统一增加data顶栏与返回/前进识别；所有现有顶栏调用方保留原行为。Backend、CLI、DG和依赖矩阵不变。

观察器每次GET完成才安排下一次；超时/5xx保持最后事实并5秒后重读，明确4xx停止自动读取、等人工刷新。继续同一已停止run成功后显式重启观察，修复真实联调中后台已推进但页面仍停旧值的问题。命令结果未知保留同一UUID和payload，只允许人工使用原操作重试；新建/继续/失败重试不自动重发。历史最近按钮重取第一页后选当前最新run，不能选第二页缓存。

配置消费者对账：日期/间隔/轮询来自context；固定前端协议预算、字符串上限和history/result请求上限集中在`api/clientPolicy.ts`，非env/用户设置，不新增后端配置或合同字段。`clientPolicy.test.ts`核对Foundation DataCenterPolicy的API5秒、stale15秒、poll2秒、keyword64/title200、history20/result50；300ms候选防抖与5秒失败观察重读是本文§9的固定交互值。改合同必须同时更新两端和此测试，不允许各页面独立改变。

R01—R19实际代码、正负例、24画板及截图对应见[DC4验收记录](../../../../reports/wealth_data_center_dc4_acceptance_20261007.md)和[机器证据](../../../../reports/wealth_data_center_dc4_acceptance_20261007.json)。真实浏览器以实际API/Query/DAO/运行器执行：67条公告→64个文件+2无URL，原2失败经单项和剩余全部失败重试恢复，原failed=2保留、unresolved=0；原创建POST仅1次。查询公司/标题不进入日期下载payload，已下载筛选返回65条关联公告；拔盘状态NULL、来源503不是空结果；Prod首页无卡。返回/前进保留草稿，未知tab纠正，未知run明确不可获取。极端7状态是临时台账合成视觉样本，不当成执行故障验收。

Wealth全量、专项、typecheck/build、62项实际后端Web回归及4项分层检查均通过；完整数量、时长、控制台/网络、图片和哈希由验收记录给出。共享顶栏/面包屑优先于Figma示例的尺寸差异明确留档；未更改共享CSS。正式外盘、台账schema迁移、来源索引初始化和源站最小下载—停止—恢复—物理对账仍待DC5；本阶段未启用正式开关、未部署或下载真实PDF。


## 20. DC5正式资源与独立下载验收（2026-10-07）

用户“提交修改，然后进入DC5”，DC4已提交`b5534947`。本阶段执行§6旧台账迁移、§4请求范围索引和§12最小真实运行，证据见[DC5记录](../../../../reports/wealth_data_center_dc5_acceptance_20261007.md)及[机器证据](../../../../reports/wealth_data_center_dc5_acceptance_20261007.json)。

| 硬口径 | 实际落点与验收 |
| --- | --- |
| R01/R19本地部署、配置和边界 | `.env.web.local`启用§5既有开关；实际公告lifespan/API消费正式资源，未登录401；Prod强制关闭；不增加用户参数或修改CLI/DG合同 |
| R03/R05—R07来源、查询、状态 | 30个完整日29619条，另7/26的5条；名称/代码/PAYH、标题98条、已下载306与未下载29313、50条分页及第587页；缺10/5—07返回503而非空态 |
| R10/R11独占、迁移、持久化 | Volume双锁内正式schema1→3；原五张事实表全部原字段逐行摘要一致，integrity_check=ok；34188记录不等于34188已下载文件；仅迁移默认归档，旧历史保留 |
| R08/R12预览、日期范围、限速 | 独立目录7/26全部5条/5文件；无公司/标题限制；预览HTTP0，实际5个源站GET全部200，最短结束→开始5.153秒 |
| R13—R15停止、继续、精确重试 | 原run处理2/5后停止，继续剩余3；测试进程注入一次请求前文件失败，关联重试只有1key；原失败1保留，unresolved降至0；零请求重放复用5 |
| R16—R18物理成果、检查、历史 | 实际5个PDF size/hash全部matched，Raw指纹不变；正式旧历史API/文件分页可读；无source_policy的旧blocked任务关闭canRecheck，与Supervisor接纳前提一致 |

查询资格修正只改RunQuery的一个前提，真实路由测试覆盖schema1/2升级后的禁止项，既有当前阻断任务检查正例继续通过；后端103项、分层4项通过。CodeGraph explore/impact和实际消费者核验覆盖RunQuery、Supervisor、App装配与DownloadPanel；sync/status无滞后，依赖矩阵不变。

最小真实下载只替换归档身份端口以选择独立验收根；生产网页仍固定announcements。真实API仅隔离登录身份，不访问认证数据库；本轮未重跑浏览器，DC4视觉/交互记录仍有效。原成果、其他台账和验收PDF保留；无备份、删表、全量下载或DG/Prod写入。

DG最新日期和连续稳定性仍独立验收。10/5—07未落地前默认30日范围会正确显示来源未就绪；本阶段不自行补湖或弱化日期完整性。所有验收线程已关闭，本机开关在用`.env.web.local`启动Web后生效。

## 21. 查询失败与按钮状态修正（2026-10-07，用户已授权）

本次仅修正缺日提示与查询观察，不改默认日期、来源完整性、下载及DG行为。

- CatalogBuilder核验公告日文件缺失时，保存`source_day_missing:YYYY-MM-DD`，日期来自实际被核验的分区；名称快照等其它来源缺失保留通用错误，不推算公告日期。错误适配复用`DC_SOURCE_UNAVAILABLE`，文案说明缺失日期及调整范围/等待同步后刷新。
- 已持久化的query_snapshot.state=error通过现有QueryResult DTO返回HTTP200，pageState.status=error并带原公共code/message；items为空、total=NULL、状态不可核验，不能冒充empty/ready。GET取得查询失败事实与HTTP读取失败分开；临时服务不可用仍503，未知query404、版本过期409不变。前端观察仅对preparing继续轮询，终态error停止自动重读。人工重新读取创建新queryId；不重启旧失败查询。
- useAnnouncementQuery区分主动提交busy、列表首次读取/翻页loading及后台观察loading。查询/重置/刷新仅在主动提交期间置灰，准备和网络重读不反复改变按钮；分页保持读取锁，不能连续翻页。准备进度保留，错误态保留筛选与明确重新读取入口。
- 正负例必须覆盖缺日（首日及中间日）、名称来源缺失不误报日期、合法零行empty、来源合同不符/超预算终态error、读取超时/5xx保留事实继续重读、终态error无后续GET、手动新查询恢复、按钮后台读取期间稳定、翻页互斥。实际路由及浏览器验证使用隔离资源，不写正式DG/Raw/Prod或下载PDF。

该调整沿用现有字段与异常码，HTTP查询失败语义和全部服务/测试/前端消费者同步迁移，既有历史验收中的503仅记录当时行为。

### 21.1 实现与验收对账

| 约束 | 代码与自动测试 | 验收 |
| --- | --- | --- |
| 实际缺日日期；名称缺失不推算日期；零行不等于缺日 | CatalogBuilder.file_stat、mapped_error；test_announcement_catalog.py及真实路由test_wealth_data_center_api.py | 首日、中间日、末日与完整零行日期均覆盖；非法日期/私有路径不进入公共文案 |
| 失败查询终态、人工新查询恢复；真实读取故障仍重读 | AnnouncementQueryService.read、既有useObserver；QueryPanel.test.tsx、useObserver.test.tsx及真实路由测试 | 终态读取HTTP200、total=NULL；补齐后原查询不重跑，新queryId成功；临时503及网络错误仍有限间隔观察 |
| 主动提交才置灰；分页读取互斥 | useAnnouncementQuery、QueryPanel；QueryPanel.test.tsx | POST期间按钮置灰，后台GET期间查询/重置/刷新可用；翻页期间分页按钮禁用 |

后端首次回归93项通过；补充中间日反例后真实路由20项通过。前端157文件1130项通过，typecheck/build、分层4项、文档完整性及diff检查通过。真实浏览器使用实际API/Biz/DAO、临时Parquet/SQLite；GET仅延迟传输以验证观察中按钮稳定。缺2026-10-07明确提示，终态后8秒无后续GET、按钮disabled属性变化0次；手动新查询恢复67条、每页最多50，末页17条，完整零行显示empty。1366/1460宽无面板溢出，无console/page/API错误。所有临时服务关闭，正式数据和源站请求均为0。证据见[查询review修正验收](../../../../reports/wealth_data_center_query_review_fix_20261007.md)。

CodeGraph explore/impact覆盖QueryService、CatalogBuilder及API/测试/前端消费者，sync/status无滞后。共用错误适配的下载预览消费者同步回归，下载控制与通用观察器实现未改；依赖矩阵、配置项、表结构均不变。正式DG缺日仍须由既有同步完成，不能把提示修正当作数据补齐。

## 22. 直接查询、PG与搜索复用的实施合同（2026-10-07，Q1已提交，Q2实施与剩余项见§24）

本节对应[技术方案](data-center-announcements-implementation-design-v1.md) §16及[本地只读审计](../../../../reports/wealth_data_center_local_storage_audit_20261007.md)。用户在核实结果后要求补齐LLD，以下将PG落点、配置、SQL、DTO及迁移规则作为唯一修订目标；不再保留SQLite目录投影的新开发路径。

### 22.1 当前链路与拟替换范围

| 当前实现/消费者 | 修订边界与必须保留的语义 |
| --- | --- |
| `CatalogBuilder` → SQLite `catalog_records/catalog_days/company_sources` → `AnnouncementQuery/CompanyQuery` | 改为正式Parquet直接查询；六字段原值、NULL/空串、缺日/零行、名称优先级及全部候选范围保持；不落全市场记录副本 |
| `useStockSearchController` → `fetchStockSearch` → market stock-search API | 控制器接纳可注入的候选加载器；默认行为保持首页/交易助手原语义；公告适配器保留名称来源、别名、显式选择和原范围 |
| `CompanySearch` 当前独立防抖/请求/键盘状态 | 改为复用控制器的薄展示层，保留公告Figma布局；不能将首页“Enter提交首项”直接覆盖公告显式选择要求 |
| `PreviewRuntime`、`ArchiveSupervisor._validate_range` 与执行前source day复核 | 改用直接来源枚举及持久化预览/来源清单；范围数量、缺日拒绝、源变化过期、封存后才允许HTTP保持 |
| `Ledger`、`ArchiveStore`、CLI、maintenance、执行器及观察API | 统一迁至本地PG；保留命令幂等、关联run、原失败历史、封存文件集合、prepared物理窗口、冷却及状态观察失败域 |
| context/query DTO、前端contracts/adapters、观察器及页面 | 清零SQLite投影语义，迁移全部实现和消费者；不以伪造字段维持旧合同 |

既有行情后端只过滤symbol/ts_code/cnspell前缀，且只含当前上市A股；本次不扩大其范围，也不把它接成公告唯一来源。公告的中文名称、历史简称、主表缺失代码及退市候选继续由本地DG来源提供。共享控制器改造须回归首页、TradingAssistantStockPicker及CompanySearch，不能只验证新入口。

### 22.2 直接查询的硬口径

1. 按自然日起止日期定位 `/Volumes/datasource/data_lake/raw/tushare/anns_d/ann_date=YYYY-MM-DD/part-000.parquet`；`hive_partitioning=false`，源列日期与目录日期分开核验。来源路径不由浏览器传入。
2. 代码/标题/日期条件、计数和分页由DuckDB执行；只投影必要列，限制连接内存/线程及读回批量，不将全范围读入Python。Raw不新增索引列，不复制至PG业务表。
3. 原六字段record_key和文件artifact_key算法保持；SQL排序与页边界必须和已有稳定顺序一致，不能换用DuckDB默认hash或按标题合并。具体SQL及身份金样本见§22.7。
4. `downloadStatus=all`只对页内相关文件检查；状态过滤先建立整个匹配范围的真实presence，再计数分页。必要的presence/来源清单须有容量、有效期及物理清理策略，不永久保存所有公告。
5. 同一查询的总数、页和来源版本一致，固定FD、范围版本复核及过期规则见§22.7。快照保存条件和来源清单，不保存全市场行副本。
6. 保留缺日明确提示及终态停止轮询；普通列表读取不再显示全市场建目录进度。大范围状态检查/下载预览仍可202并展示真实业务进展；不通过截短范围或丢行满足时间预算。

### 22.3 PG迁移与合同门禁

PG仅保存文件归档与运行所需的关系事实。封存任务为退出续跑保留URL、命名代表记录等必要数据；“不复制全市场公告”不等于删除恢复必需的来源记录。

目标落点和配置见§22.5；表及迁移版本规则见§22.6；迁移checkpoint、事务和失败恢复见§22.10。不得借用Dagster instance库或主应用远程engine。无新增配置或依赖在本轮生效。

迁移对账包括正式及3份独立验收台账：run身份、source_records、artifacts、关联表、按日源事实、命令回执、attempt/进度、控制owner和cooldown，按实际schema逐项映射；不只复制成功文件。查询catalog中的预览、预览日期/文件及仍有效的控制事实需迁移或按明确合同过期，不遗漏预览消费者。读回通过后统一切换全部CLI/Web/maintenance消费者，不保留长期双写或旧实现兜底。

当前 `indexAvailability`、`lastIndexedAt`、`catalogRevision` 属于投影语义，直接查询后不能用文件mtime冒充“已索引”。唯一替代合同见§22.8，同轮迁移后端schema、Biz/查询服务、前端contracts和全部测试，不保留双轨口径。CLI输出迁移见§22.10，原PDF技术方案/LLD已增加本节引用。

清理对象为已审计的1份catalog、1份正式台账、3份验收台账及存在的SQLite伴随文件，先列实际路径并关闭所有旧连接，再验证无引用后执行。不得删除PDF、DG Raw或系统/Conda/Homebrew共享SQLite库；本轮不执行清理或数据库写入。

### 22.4 修订验收矩阵与下一步

| 修订目标 | 最小验证与反例 |
| --- | --- |
| 搜索复用且范围不缩减 | 中文/代码/首字母、历史别名、退市、主表缺失代码；取消/失焦/竞态及Enter显式选择；首页/交易助手行为回归 |
| 不复制全市场元数据 | 普通代码查询与公司候选均无catalog写入；PG无全市场anns_d镜像；查询刷新不访问DG/Tushare/PDF源站 |
| 直接查询性能 | 002245.SZ、2026-05-04—10-05与相同六字段只读来源逐项对账；分别测冷/暖、全市场、长日期及状态过滤完整API的P50/P95、RSS、文件数和读回行数 |
| 查询正确性与一致性 | NULL/空串、同文件多行、字面%/_、缺日/零行、源替换/换卷/翻页/过期及删除PDF后状态计数；不能先50条再筛状态 |
| 台账迁移与续跑 | 迁移前后字段/计数/摘要读回，故障中断/重放，停止—退出—继续、精确失败重试、冷却不丢及单执行锁；临时测试库不得指向正式库 |
| 安全清理 | CLI/API/预览/执行器无SQLite消费者；迁移验收后才删除本功能旧文件，共享库和Raw/PDF保持 |

既有读接口4秒SQL/5秒客户端预算继续作为目标，完整API需单独验收；只读点测0.3116秒不能替代该验证。若不达预算，先定位文件读取、名称检索或presence检查，再评估有界缓存；不默认回到全市场复制。

PG落点只读审计已完成，下文补齐实施合同。下一步按§22.11的分期进入代码开发和隔离验收；本轮不执行新代码测试、迁移、删除、安装、部署或提交。

### 22.5 本地PG落点、连接和配置审计

固定使用现有localhost:5432实例中的 `goldenshare_lake_meta.announcement_archive`，不新建数据库服务或业务库，不修改该库public下的4张旧表。此schema属于Foundation归档DAO，不注册DG resource，不连接 `goldenshare_dagster` 或历史验收库。主应用 `DATABASE_URL`、认证、行情API和主仓库Alembic保持原用途。

| 配置 | 默认值与来源/持久化 | 消费者、生效及验证 |
| --- | --- | --- |
| `announcement_archive_database_url` / `ANNOUNCEMENT_ARCHIVE_DATABASE_URL` | 新增Foundation Settings字段，默认空；沿用get_settings的env-file优先级。本机部署写入ignored `.env.web.local`；CLI使用现有 `GOLDENSHARE_ENV_FILE` 选择同文件，不增加DSN命令行参数 | App归档工厂、下载/维护CLI、迁移工具；重启生效。模块关闭不创建engine；启用而缺失时公告模块返回安全依赖错误，其他页面继续可用。不得回退DATABASE_URL |
| 本机连接值 | `postgresql+psycopg://congming@localhost:5432/goldenshare_lake_meta`；密码若需要仅由运营配置，不进文档/命令输出 | 只接受postgresql+psycopg、loopback、5432及固定库；拒绝URL query中host/service等覆盖。localhost规范为127.0.0.1，连接后核对peer为loopback/current_database正确 |
| engine连接预算 | 在Foundation `ArchiveDatabasePolicy` 集中定义：connect3秒、pool等待1秒、pool_size=4/max_overflow=0、lock_timeout=500毫秒、读statement_timeout=4秒 | Web/App注入、CLI同工厂；并发超时为公告依赖错误，不生成另一份连接池、不阻塞主应用事务。迁移同样每批≤4秒SQL |
| 来源/回收预算 | DataCenterPolicy新增file_batch_size=32、gc_seconds=60、gc_batch_size=500；原catalog_check_seconds更名source_check_seconds=30，catalog_unit_seconds退出 | 直接读取与元数据回收runtime；仅内部集中策略，不加env/页面控件。每次实际查询/翻页仍核验范围版本，不能等待周期刷新 |
| 既有查询/网络策略 | page50、候选20、keyword64、title200、TTL900秒、poll2秒、control poll0.5秒；Source batch500、DuckDB256MiB/1线程/禁止spill和扩展安装 | 继续唯一DataCenterPolicy/DownloadPolicy；HTTP间隔/退避/冷却及文件协议不变，不在新DAO再定义常量 |

这些是拟新增/修改配置的完整来源，不表示已写入本机env。迁移使用当前本机角色，应用仅需新schema的SELECT/INSERT/UPDATE/DELETE权限；不创建新角色、不改DG权限。schema所有SQL完全限定表名，schema名字不是用户参数。诊断只输出host/port/database/schema及错误码，禁止输出连接密码。

权限/配置负例：DSN空、远程host、URL覆盖host、错误库、缺schema、未知版本、无权限、PG离线、池耗尽；均不能调用主应用engine、初始化表或启动PDF请求。新的内部策略由跨端/工厂测试证明唯一来源，不要求安装额外包。

固定库/schema/端口的允许值与连接预算统一由ArchiveDatabasePolicy持有。隔离集成测试通过显式fixture工厂注入临时库/端口策略，仍限定loopback；该覆盖只存在测试构造，不提供env/CLI“关闭守卫”开关。不得为测试连接正式metadata库写探测行，临时库/实例创建按阶段授权，不隐式安装PG。

### 22.6 PG表结构、键与版本管理

PG归档schema独立版本从1开始，由 `schema_info(singleton SMALLINT PRIMARY KEY CHECK(singleton=1),version BIGINT NOT NULL,ddl_sha256 TEXT NOT NULL,installed_at TEXT NOT NULL)` 管理。使用Foundation DAO下 `pg_migrations/001_initial.sql` 的显式静态DDL及迁移工具；不新增主仓库Alembic revision，不执行主应用完整迁移链。已核实主仓库head为20261002_000183，它不是该本地schema的down_revision。

DDL只由显式迁移命令执行；运行时constructor/read/context均只核验schema/version，未知或不完整对象拒绝使用。初次DDL在一笔短事务中提交；重跑版本和DDL摘要一致则跳过，不以 `CREATE IF NOT EXISTS` 掩盖结构冲突。

归档身份为 `identity([volume_uuid,root_relative_path])`，原算法不变。根路径使用卷内相对值，不能按mountpoint字符串或source_scope替代。archives以archive_id为主键，其余归档/控制表必须有 `archive_id TEXT NOT NULL REFERENCES archives(archive_id)`；所有SQL包含archive_id，文件/来源/命令键均按归档隔离。HTTP不接受archive_id，Web由固定binding解析；CLI由已有output-root及卷验证解析。只读入口不创建归档；已核验卷身份的首次下载可在短事务中初始化空archives/cooldown/execution行（ready、source_schema_version=0表示原生PG），不执行DDL。

| 表 | 主键/唯一键 | 保留列与新增列 |
| --- | --- | --- |
| `archives` | PK archive_id；UNIQUE(volume_uuid,root_relative_path) | volume_uuid、root_relative_path、created_at保留；新增source_schema_version BIGINT、import_state TEXT（importing/ready）、import_completed_at TEXT；旧singleton/schema_version转为本schema版本和源版本，不混用 |
| `runs` | PK(archive_id,run_id)；UNIQUE(archive_id,row_seq) | 原schema3 SCHEMA.runs、RUN_ADDITIONS、RUN_FIELDS的全部列原名保留；新增row_seq BIGINT GENERATED BY DEFAULT AS IDENTITY |
| `artifacts` | PK(archive_id,artifact_key)；UNIQUE(archive_id,path_fold) | 原SCHEMA.artifacts及ADDITIONS.artifacts全部列保留 |
| `source_records` | PK(archive_id,source_scope,record_key)；UNIQUE(archive_id,row_seq) | source_scope、record_key、legacy_raw_id、metadata、artifact_key、first_seen_run、last_seen_run；新增row_seq identity |
| `run_artifacts` | PK(archive_id,run_id,artifact_key) | run_id、artifact_key、outcome、attempts、representative_record_key、claimed_owner、claimed_at |
| `run_source_days` | PK(archive_id,run_id,ann_date) | DAY_SCHEMA全部列：state、opened_dev/ino、size、sha256、footer_count、records_committed、reason、updated_at等 |
| `cooldown` | PK archive_id | last_request_finished_at、next_request_not_before、request_in_flight、reason；原singleton=1移入归档作用域 |
| `archive_execution` | PK archive_id | active_run_id、owner_token、heartbeat、revision；原singleton=1移入归档作用域 |
| `attempt_log` | PK(archive_id,run_id,artifact_key,attempt_seq) | TABLES.attempt_log全部原列 |
| `run_sessions` | PK(archive_id,run_id,session_seq) | TABLES.run_sessions全部原列 |
| `command_receipts` | PK(archive_id,key) | kind、payload_hash、result_run_id、state、created_at |

保留列的DDL基线为当前 [ledger.py](../../../../src/foundation/dao/announcement_archive/ledger.py) 的SCHEMA/DAY_SCHEMA/RUN_ADDITIONS和 [schema.py](../../../../src/foundation/dao/announcement_archive/schema.py) 的RUN_FIELDS/ADDITIONS/TABLES，不能只按REQUIRED最小集合建表。明确类型映射：TEXT仍TEXT（JSON及原UTC字符串不改字节格式）；INTEGER→BIGINT；REAL→DOUBLE PRECISION；原NULL和default保持，不擅自改成bool/JSONB/DATE。目标显式SQL的列集合/默认值须与这份映射做合同测试；运行时不解析SQLite schema生成PG表。

索引只服务实际台账场景：runs(archive_id,row_seq DESC)、artifacts(archive_id,ann_date,ts_code,artifact_key)、artifacts(archive_id,artifact_key) WHERE state='succeeded'、source_records(archive_id,artifact_key,row_seq)、run_artifacts(archive_id,run_id,outcome,artifact_key)、run_source_days(archive_id,run_id,state,ann_date)；attempt/session的原open部分索引加archive_id。不在PG建公告标题/公司名搜索索引。所有复合关联按同archive_id JOIN，不能仅按run_id或artifact_key JOIN。旧可空关联值原样保留，不通过加约束丢弃历史行。

短期控制表均包含archive_id、query_id或preview_id，使用同样作用域；字段的时间为UTC TEXT、数量/序号为BIGINT、期限/间隔为DOUBLE PRECISION、状态和标识为TEXT：

| 表/键 | 完整业务列（均不保存全市场公告行） |
| --- | --- |
| `query_snapshots` PK(archive_id,query_id) | source_scope、conditions TEXT、state、source_version（可空）、total（可空）、status_available BIGINT、created_at、updated_at、checked_at（可空）、expires_at（可空）、reason（可空）、preparation_stage、dates_total、dates_scanned、records_scanned、artifacts_checked、owner_token（可空） |
| `query_files` PK(archive_id,query_id,source_kind,partition) | relative_path、opened_dev、opened_ino、size、mtime_ns、footer_count；source_kind为anns_d/stock_basic/namechange，partition为ISO日或full |
| `query_day_counts` PK(archive_id,query_id,ann_date) | match_count；ready前必须覆盖完整日期范围，包括零行日 |
| `query_presence` PK(archive_id,query_id,artifact_key) | checked_at；仅成功且安全普通文件存在的key |
| `previews` PK(archive_id,preview_id) | start_date、end_date、interval_seconds、source_scope、source_version（可空）、state、statistics TEXT（可空）、created_at、updated_at、expires_at（可空）、reason（可空）、dates_total、dates_scanned、records_scanned、owner_token（可空） |
| `preview_days` PK(archive_id,preview_id,ann_date) | source_facts TEXT；含relative_path、dev/ino/size/mtime_ns、sha256、footer_count；沿用下载Source内容校验 |
| `preview_artifacts` PK(archive_id,preview_id,artifact_key) | 不复制公告metadata，只用于范围预览唯一文件数/存在性统计 |
| `migration_checkpoints` PK(archive_id,source_table) | source_path TEXT、source_sha256 TEXT、source_schema_version BIGINT、last_rowid BIGINT、rows_committed BIGINT、rows_total BIGINT、rows_digest TEXT、state TEXT、updated_at TEXT |

所有新字段未标可空者NOT NULL；进度计数默认0，owner/version/checked/expiry在准备中允许NULL；state/conditions/source_scope等由创建事务必填。控制表另建(archive_id,state,created_at)与expires_at索引，明细表的复合PK承担读取。DDL不对临时父记录加无界ON DELETE CASCADE，清理按§22.10分批。

### 22.7 DuckDB直接查询与来源一致性

普通请求不持有PG事务读取Parquet。POST查询先以短事务保存条件，返回202；客户端立即首次GET，尚准备中才每2秒观察。GET只读准备状态或现成页，不领取下载任务。后台每次认领一个query/preview，先在专用连接取得按(archive_id,对象kind,id)确定的PG session advisory lock，再短事务CAS写owner；锁随连接退出释放，不能仅按心跳接管。崩溃后只有取得该锁的新owner才清理未封存临时明细并重建；封存记录不重算。全过程不保持长事务，连接丢失立即停止该准备unit，绝不恢复HTTP下载。

App为直接查询、候选、预览和元数据GC组合一个本地来源读取runtime，不再同时运行独立catalog/preview两套扫描循环；每进程最多一个DuckDB来源读取连接，名称临时关系算入其256MiB预算。读页和后台unit共享这项资源，按4秒截止中断SQL并让出，不堆积多个全范围扫描。GC只处理PG小批数据。该runtime归Ops并由App注入，Biz不启动线程或import Ops；不是新的通用任务框架。

每次最多打开32个公告文件，另加最多2份名称snapshot。按所请求自然日逐批生成路径，用 `O_RDONLY|O_NOFOLLOW` 打开并fstat验证普通文件、来源设备和六列类型；DuckDB读取 `/dev/fd/N`，`hive_partitioning=false`，不能在校验后改读可被替换的普通路径。路径发现、批次编排及少量最终DTO在Python；过滤、计数、排序、唯一键及joins在SQL。

查询版本为来源scope、合同版本、确定首字母词表版本及按(source_kind,partition)排序的(dev,ino,size,mtime_ns)清单的SHA256；按小批流式计算，不能随单页改变。PG只存清单和逐日匹配数。这里的stat版本基于正式DG不可变候选+os.replace发布协议，不将其称为内容哈希或DG成功证据；外部同inode原位修改导致fstat改变也拒绝。下载预览/封存继续用原DayReader前后内容SHA256，而不是用stat降级其校验。

准备与翻页协议：

1. 名称snapshot固定FD读取，记录其清单及词表版本；公告按32文件unit读取，fstat开/关前后相同，将逐日匹配数与小型清单在一笔PG事务中提交，业务进度真实更新。
2. 全部unit完成后重新stat整个清单（每批32）并核验来源卷；缺日是具体日期错误，合法零行必须有六列footer合同且记count=0。任何变化终态error/`DC_QUERY_CONTEXT_CHANGED`，不封存混合版本，不自动循环重试。
3. 满足完整日覆盖才原子更新query为ready、total=sum(day counts)、source_version和TTL；准备中total/version可空，读取不伪造数量。
4. 读页前逐批复核全清单；按day counts找到页涉及的日期及日内offset，固定FD与原清单匹配后查询，再复核FD及全清单。任一日/名称/卷/词表变化，丢弃本次返回并409提示刷新。分页不能把新文件行与旧total拼接。
5. 正式DG原子替换可能发生在响应之后，页面保证本次检查时间点的一致性，不能承诺用户看到后文件永不变化。禁止为保证旧版本而复制Parquet或长期持有全范围FD。

日内SQL表达式（参数绑定，列来自固定FD；day与file列表均由后端确定）：

```sql
WITH projected AS (
  SELECT ann_date,ts_code,name,title,url,rec_time,
    sha256(to_json(list_value('dg-anns-d-v1',ann_date,ts_code,name,title,url,rec_time))) AS record_key,
    CASE WHEN length(trim(coalesce(url,''),?))=0 THEN NULL ELSE
      sha256(to_json(list_value(?,ts_code,trim(url,?)))) END AS artifact_key
  FROM read_parquet(?,hive_partitioning=false)
  WHERE (? IS NULL OR ts_code=?)
    AND (?='' OR contains(coalesce(title,''),?))
)
SELECT * FROM projected
ORDER BY ann_date DESC,ts_code ASC NULLS LAST,record_key ASC
LIMIT ? OFFSET ?;
```

day参数为ISO日期；源ann_date仍YYYYMMDD，SQL核验它与路径day一致后才转为DTO日期。trim的第二参数使用集中身份函数定义的Python str.isspace字符集合（当前29字符），与原url.strip()一致，不能用DuckDB默认trim替代：已用tab/换行/NBSP/全角空格等读回证明默认trim有差异。count用同一WHERE；状态筛选另加presence semi/anti join，不能只套本例LIMIT后过滤。NULL URL/空URL无artifact_key但公告行保留，URL展示按已有安全外链规则。Raw不去重、不规范化名称/标题；只有下载文件身份对URL strip。

显式SHA256(JSON数组)必须与Python identity逐字节一致。已读回36条真实样本相等；编码测试另覆盖中文、引号/反斜线/控制字符、NULL/空串/空白、URL空白、跨字段同标题及非BMP字符；任一不一致不得上线，也不得改成DuckDB默认hash。计数/排序的完整API验收不能用只读点测代替。

状态过滤：从PG按archive_id、日期及可选代码keyset分批读取成功文件（不按代表标题过滤），每500项检查安全路径存在/大小；将真实存在key写query_presence，然后逐unit在DuckDB临时关系中semi/anti join同一匹配条件。只传相关存在key，内存随受控批次和DuckDB预算；匹配代码/title仍SQL下推。all只对当前页成功关联检查。状态变动或页存在性与冻结集合不符返回409，卷不可读时all返回未知状态，状态过滤返回明确错误。查询不会修改artifacts.state、hash或历史run。

### 22.8 唯一API合同与前端迁移

路径、查询条件、日期下载参数、六列表项、Task/Files/History合同和登录/Prod边界保留。以下字段变更在同一交付中替换所有后端/前端消费者，旧字段移除，不返回两套版本或兼容空值：

| 当前字段/行为 | 新合同 |
| --- | --- |
| Context.indexAvailability、lastIndexedAt | 删除；新增 `ledgerAvailability: 'ready'|'unavailable'`，表示PG归档存储可读；原sourceAvailability继续表示本地来源可用 |
| QueryResult.catalogRevision | 删除；新增 `sourceVersion: string|null`，准备/终态失败可空，ready为64位hex版本 |
| QueryPreparation | 保留datesScanned/datesTotal/recordsScanned；新增 `stage: 'readingSource'|'checkingStatus'|'counting'`、`artifactsChecked: number`，按真实unit描述进度，不显示建索引文案 |
| Companies准备合同 | 保留Company、hasMore、pageState、preparation、queryId；候选计算使用同源版本及准备队列，不写company_sources；首次候选若需范围读取仍202可观察，后续按键不触发全市场目录复制 |
| observedAnnDate | 后台有界目录清单最大物理日期，不再来自catalog_days；不表示DG检查通过 |
| sourceUpdateSucceededAt | 没有正式成功证据继续NULL；不能拿mtime、sourceVersion或checkedAt填充 |

Context.moduleEnabled只取部署配置，PG不可读或外盘离线不隐藏本地卡；Prod不创建PG归档engine、DuckDB或加载pypinyin。缺省30自然日和缺日提示不变。读准备返回202，已确定失败查询返回HTTP200/pageState=error并停止轮询；版本/TTL变化409要求人工刷新；真实传输503重读规则保留。PG/config/schema/pool错误统一既有DC_LEDGER_FAILED(503)，缺日沿用DC_SOURCE_UNAVAILABLE，版本变化沿用DC_QUERY_CONTEXT_CHANGED，预览变化沿用DC_PREVIEW_STALE，非法条件沿用DC_REQUEST_INVALID。目录已退出，因此DC_INDEX_FAILED替换为DC_QUERY_FAILED（同503/终态pageState规则）；同轮迁移错误adapter、注册表及测试，不输出DSN/SQL异常。

消费者必须同步迁移：Biz DTO/schema、query/context/company service、API响应校验、前端contracts/api adapter/fixtures、useAnnouncementQuery/CompanySearch/QueryPanel、数据可用性提示及真实路由/浏览器测试。路由不让前端自行拼sourceVersion或推断ledger readiness。

### 22.9 共享搜索复用合同

改造既有 `useStockSearchController` 接纳可选候选加载器和交互策略，默认仍调用fetchStockSearch；不新建通用搜索框架或另一套状态机。加载器接收 `{keyword,signal}`，返回StockSearchOption的类型扩展数组；公告适配器保留Company字段。原首页/交易助手onSelect(tsCode)方式保留，新增互斥的onSelectOption(option)供公告接收完整候选；一次commit只调用其中一种。泛型默认StockSearchOption，控制器内部统一commit，不留双份键盘/竞态实现。

策略统一定义：默认仍debounce500ms、timeout2000ms、maxKeyword32、Enter可提交首项；公告debounce300ms、timeout5000ms、maxKeyword64、Enter只提交显式选中项，初始activeIndex=-1，ArrowDown选首项。原点击/Esc/失焦/中断规则保留；公告换日期或文本变化清空未匹配的选中项。来源准备202由公告加载器使用现有observer观察，终态停止；signal取消后不得覆盖新输入或触发选择。Announcement CompanySearch只承载Figma薄展示层和候选字段适配。

名称和候选SQL保留§4.1优先级/排序。master不限制list_status；历史namechange及请求范围公告补别名，未知代码不被JOIN排除。两份小名称snapshot可形成进程内DuckDB临时关系，按源清单/词表版本失效，不持久化或新建独立字典。名称转换仍使用NameInitials，不能逐按键重算全历史首字母。范围公告别名在DuckDB归并后才读回少量候选；最多20+1条用于hasMore。一次请求及缓存受256MiB/4秒预算，超预算明确准备/错误，不少返回退市/未知对象来提速。

暂不引入新的搜索结果缓存配置；已有query准备可复用同条件/同版本短期清单。正负测试覆盖三个消费者默认行为不漂移、中文/历史/退市/44类主表缺失代码、Enter未选择不提交、blur abort、输入/日期竞态、名称snapshot替换及后端失败后人工恢复。

### 22.10 迁移、事务、续跑与清理

新增运营工具入口 `python -m src.scripts.migrate_announcement_archive`，默认只读plan；`--apply`迁移、`--cleanup`清理为分开的显式操作，不在启动Web/下载命令时自动执行。目标DSN只取§22.5配置；源码SQL版本由工具明确调用，不能代理主仓库Alembic。plan列精确源文件、归档身份、版本、表数/行数、目标冲突、预计批次及磁盘需求，不以计划检查偷偷建schema。

精确源清单如下；现场plan再次核对schema/卷/摘要，不接受模糊glob覆盖其他SQLite。默认迁移全部4份下载台账；不能只复制363个成功文件或省略旧schema2。

```text
/Users/congming/Library/Application Support/Goldenshare/announcement-catalog/e04b7c92bfa1082f05a370b0504bdfcb29f66fb352fbe82a904a71df1db7b79a/catalog.sqlite
/Users/congming/Library/Application Support/Goldenshare/announcement-download/6ae38d3a5436526b8e6a941086bda5ce366397699eea6d8d59fd598817d7f4f3/downloads.sqlite
/Users/congming/Library/Application Support/Goldenshare/announcement-download/ad609a131cad03f5d8de8e09cab84ded264842358993a512f2b289476bfc6c4c/downloads.sqlite
/Users/congming/Library/Application Support/Goldenshare/announcement-download/bb28fc7eca37cbf2a513cc48295d82efad9a55fe023853902181bfeabb24bf9f/downloads.sqlite
/Users/congming/Library/Application Support/Goldenshare/announcement-download/fe6ce589e8fe2f1d6ad0d572e7e194204edef2daa99bc7a555efec1d7f950013/downloads.sqlite
```

现有4份台账约10.27万表行（同一文件在关联表中的行分别计入），约240个500行数据批；不是迁移全市场公告。现场plan按逐表实际行数给出精确批数。预计分钟级，正式执行前必须用隔离批次/读回样本测算总耗时；若预估超过5分钟，先查锁/写法/摘要开销，不自动增加批量或长事务。每批进度输出归档、当前表、rowsCommitted/rowsTotal、lastRowid、更新时间和checkpoint；SIGINT返回130并保留已提交批，plan/APPLY成功0、冲突/依赖失败3。

APPLY协议：

1. 先停止本机公告Web/CLI写者，DG继续运行；取得旧本机execution锁和每个归档外盘锁，校验源SQLite普通文件/schema/卷身份及有无未结束事务。保持源只读，不升级SQLite、不复制PDF或创建备份。迁移工具不能强杀其他进程来抢锁。
2. 记录源schema、每表row count及按原rowid排序的逐行规范摘要；source_sha256是主SQLite及存在的WAL内容SHA256清单的确定摘要，不能遗漏未checkpoint的WAL，也不能为迁移主动checkpoint/重写源。热journal或持续变化阻断。每批最多500行，从last_rowid向后读，目标短事务原子写入该批及checkpoint。每批前后检查取消，SQL≤4秒、锁等待≤500毫秒，超时回滚当前批，已提交批保留。
3. 源schema3所有列原值导入；schema2只补原schema3新增列的明确默认值/NULL。原runs/source_records rowid映射row_seq；源中的遗留id、source_policy、JSON原字符串、失败、未完成、size/hash、冷却和尝试均保留。存在活动slot/非终态run或正在checking时plan阻断并要求正常停止；终态历史owner字段原样保留，不因它曾记录owner而阻断。当前读回四份均无活动run。遇未审计schema1或未知schema明确阻断，不升级或丢弃。
4. 每批重放按复合业务键对比全部列，一致则跳过，不一致立即失败，不ON CONFLICT UPDATE覆盖已有业务事实。归档importing期间runtime拒绝读写该归档，不显示部分迁移为ready。暂停/进程退出后持相同锁验证源SHA仍相同，再从checkpoint续跑；源变更拒绝续接，不删目标重来。
5. 每个归档读回全部表的列集合、行数、规范摘要、关联键、冷却及路径事实；成功后短事务更新archives.import_state=ready。所有4份完成后设置两条row_seq identity序列下一个值大于已导入最大值，保留CLI旧整数游标。迁移控制表的failed状态不回滚已提交业务批。
6. catalog的旧查询/预览ID、条件/统计/创建时间保留为明确已过期控制结果；query变error/DC_QUERY_CONTEXT_CHANGED、preview变error/DC_PREVIEW_STALE，source_version=NULL，无明细，迁移完成后保留900秒供错误读取；被run引用的preview保留小型历史。原catalog无created_at的预览用迁移记录时间明确补齐，不伪造原创建时间。不迁移旧catalog_records/company_sources/query_presence/day counts，不冒充新版本ready；新查询/预览重新直接读Raw。已封存run的preview_id关联历史记录保留，不重枚举或扩大原run。

短事务/并发：领取run时 `SELECT ... FOR UPDATE` 锁同archive_execution行，单活动slot在提交中写owner；文件双锁仍保留，不能只靠PG心跳接管。stop短事务CAS写原stop意图，执行器0.5秒检查；PG不可写时停止领取新文件/发新请求，保留已完成普通文件，恢复后按原prepared/文件事实协议对账，不自动发HTTP。文件成果提交与节流观察进度分开事务；观察更新失败不回滚已提交成果。文件fsync/os.replace窗口、HTTP limiter/cooldown和原封存集合不变。

CLI保留日期/间隔/output-root和查询筛选/退出码，before-rowid/after-rowid仍为正整数，对应PG row_seq而非隐藏SQLite rowid。summary及所有维护JSON移除ledger_path，新增 `storage:{kind:'postgresql',database:'goldenshare_lake_meta',schema:'announcement_archive',archiveId:string,schemaVersion:1}`；旧schema_version移至storage，不伪造文件路径。CLI help/原PDF文档、样本及全部维护消费者同轮更新；移除运行期sqlite3异常/PRAGMA/路径依赖，不做兼容SQL连接壳。ArchiveBinding的web-archive.json和本机execution锁文件保留，仅保存卷/root身份，不是第二套关系数据库。

临时数据物理回收：query/preview ready后的TTL900秒，error/cancelled也从终态写入时设置900秒期限，准备中不耗结果TTL；每60秒处理已到期记录，先标过期，子表每批最多500行短事务删除，全部子表清空才删父表。每轮最多用4秒，再交还控制循环；不可一笔cascade删除无界presence。被run引用的preview仅保留小型条件/统计历史，不保留文件列表；下载runs/source_records/attempt/cooldown不自动GC。进程退出后下一轮继续回收，不只设置expires_at而不删除。

清理旧SQLite前需完成PG业务读回及所有消费者切换；再次plan显示这5份数据库及实际存在的-wal/-shm/-journal伴随文件，确认旧连接已关闭、源摘要与迁移一致、无未完成checkpoint。cleanup只unlink这份白名单，不删App Support锁/binding，不卸载共享SQLite，不删PDF/Raw/DG库或4张遗留表。无自动备份/Kopia，不在测试中清空正式表。若cleanup失败，PG继续是唯一运行存储，剩余旧文件只供明确清理，不作运行期兜底。

### 22.11 分期实现与编码验收门禁

每轮只交付一个阶段，阶段验收后再推进下一阶段；正式资源APPLY和cleanup独立授权：

| 阶段 | 交付/范围 | 必须验证 |
| --- | --- | --- |
| Q1 PG基础与迁移工具 | 配置/独立engine、显式DDL、归档DAO/事务、plan/apply/checkpoint；临时PG+SQLite | 4归档同5文件键互不串状态；schema2/3完整映射，重复/冲突/中断/取消/续跑；row_seq旧游标；DSN远程/错误库负例；根Alembic及DG旧表零调用 |
| Q2 直接查询与API/搜索迁移 | 所有catalog列表/公司/预览/范围复核替换，源版本协议，DTO和三搜索消费者同轮迁移 | R03—R09、缺日/零行、原子替换/原位修改/换卷、稳定页与status全范围计数、终态停轮询、GC实际删行；首页/交易助手行为；原catalog消费者清零 |
| Q3 执行/CLI切换与隔离验收 | Web/CLI/maintenance统一PG，保留文件/HTTP和原封存恢复；更新旧PDF文档 | 运行—停止—退出—续跑、精确重试、单执行、403/429冷却、prepared崩溃窗口、观察失败不回滚、PG离线时零新HTTP、完整GUI/CLI回归 |
| Q4 正式迁移/独立验收/清理 | 用户授权后plan→apply→读回→统一启用→独立小范围验收→另行cleanup | 当前363成功文件仍可查，4份台账计数/摘要一致、重放零请求、5旧SQLite清理白名单、Raw/PDF/共享库不变；不自动全量下载 |

Q1—Q3开发期间不启用正式新存储，不在用户实际Web保留双后端开关或长期兼容实现；临时工厂只用于隔离测试。版本切换一次完成，新代码上线前完成正式迁移，模块尚未就绪时明确不可用，不回退SQLite。若阶段代码尚未可用则不部署该半成品。

性能验收固定记录：日期/文件/行组/源字节、PG批次与返回行数、FD峰值、RSS、每次SQL与完整API时间、控制进度和源站请求数。代表范围为默认30日、155日/002245.SZ、同范围全公司、全部历史清单及已/未下载筛选；冷进程首次和暖请求分别测，不声称已清OS缓存。完整GET读目标P95≤5秒、单SQL≤4秒、RSS≤512MiB、同时公告FD≤32；准备长于一次读取预算时202展示真实阶段，每≤5秒更新业务进度，ETA未知保持NULL。若不达标必须定位瓶颈并重新评审，不加SQLite全市场副本、无界缓存或截短范围。

编码完成按R01—R24和本节逐条对账代码/正反测试/真实有限只读证据。源端同步、DG日常稳定性和全历史元数据质量仍是独立验收项，不能由界面或本次迁移测试代替。Q1—Q3交付见§23—25；Q4正式操作与清理边界见§26。有限窗口验收不能当作全部历史API性能结论。

## 23. Q1 PG基础与迁移工具交付（2026-10-07）

用户“提交修改，然后开始推进Q1”。此前公告review修正、只读审计和修订LLD已提交`66263bb3`；随后用户“提交，然后继续进行下一个阶段Q2”，Q1提交`d6cc3971`。完整文件、硬口径、测试及性能证据见[Q1验收报告](../../../../reports/wealth_data_center_q1_acceptance_20261007.md)。没有写入本机正式metadata库、修改env、迁移原SQLite或改动PDF/Raw，也没有安装/卸载软件。

落地文件：Foundation Settings和ArchiveDatabasePolicy、`pg_database.py`独立连接/预算、`pg_migrations/001_initial.sql`及静态列合同、`pg_schema.py`完整结构验证、`pg_archive.py`按archive_id隔离的DAO；只读旧源适配在`clients/announcement_archive/migration_source.py`；运营分批迁移在`ops/runtime/announcement_archive/migration.py`；CLI薄入口为`src.scripts.migrate_announcement_archive`。静态SQL/合同作为package data发布，不从运行期SQLite动态生成DDL。

迁移实现细节补充：

1. PLAN保持只读，核对每归档/每表行数、摘要和已有目标冲突；批数按归档分别向上取整，包括短期控制记录。目标空间以下载SQLite文件总大小的三倍做保守估计，并读取PG所在本机文件系统可用空间。正式执行耗时仍须在Q4按当时清单估算。
2. checkpoint的rows_digest是已提交前缀的确定摘要；源路径/主文件及WAL摘要/版本/总量任一变化拒绝续接。数据和checkpoint一笔短事务；对已提交前缀逐批读回，进度显示持久rowsCommitted，另外显示rowsVerified，不因复核前缀而倒退完成量。
3. 旧preview没有created_at，使用本次schema安装记录的迁移时间明确补齐。控制结果先以NULL期限导入；按每批最多500行写入完成时间+TTL，最后原子发布最终摘要及archive ready。若收尾中断，只重置未发布控制记录的期限后续跑，不修改已发布归档或历史业务字段。
4. 结构校验覆盖版本/DDL摘要、列/类型/NULL/default/identity、主键、唯一键、archive外键、CHECK及显式索引；缺失或未知结构均不自动修复。迁移领取采用原本机execution锁和外盘锁，runtime只读入口不建表、不创建归档；原生PG归档初始化独立于DDL。
5. Q1仅提供默认PLAN和显式`--apply`；`--cleanup`、Web/CLI正式接线、临时结果GC及直接查询仍按Q2—Q4实施。该工具本轮未对正式资源运行。原SQLite只在显式旧源适配和当前尚未切换的旧主链存在，不新增运行期SQL兼容壳或PG失败回退。

验收：Q1完整套件43项通过，公告联合回归334项通过；Foundation数据合同门禁170项、依赖/legacy护栏16项及ingestion-lint通过。临时PG真实进程退出/SIGINT—续跑、事务中断、WAL、四归档同5键、schema2/3完整字段、旧整数游标和失败拒绝均已读回。

代表样本102,026关联表行、231数据批；全新临时库首次PLAN+APPLY约18.50秒，最慢SQL1.36秒，Q1测试进程RSS峰值227.16MiB/FD峰值23，源站请求0。该测量是本机隔离迁移，没有清OS缓存，不是页面API/P95或正式迁移验收。下一阶段为Q2直接读取Raw、查询/API/共享搜索迁移。


## 24. Q2直接查询交付与有限验收（2026-10-07，已完成）

本阶段依据§22.6—22.11，产品/Figma不变。详细硬口径、文件与测试映射见[Q2报告](../../../../reports/wealth_data_center_q2_acceptance_20261007.md)，[真实来源性能证据](../../../../reports/wealth_data_center_q2_profile_20261007.json)和[浏览器截图](../../../../reports/wealth_data_center_q2_browser_20261007/restored-query.jpg)。

1. Foundation `DirectSource`固定FD直接查询Raw，单DuckDB/256MiB/32公告文件、4秒SQL中断；`CompanySource`复用NameInitials和小名称snapshot，范围别名只在DuckDB临时关系归并。不存在PG公告元数据副本。
2. `QueryControls`以archive_id隔离小型来源清单、逐日匹配数、短期presence/preview；短事务和session advisory lock领取，进程退出后未封存结果清理重建。`SourcePreparation`统一查询/预览准备、终态封存、内容SHA及取消；runtime统一来源检查和500行物理GC。固定FD与完整清单在准备终点及读页前后复核。
3. Biz/App/Wealth同轮迁移sourceVersion、ledgerAvailability、真实准备阶段和错误合同。公告公司搜索复用既有控制器，默认首页/交易助手行为保留，公告必须明确选择；候选202观察、取消和终态停止有独立测试。App不接旧SQLite；下载执行/CLI的PG装配留给Q3。因此本阶段代码不可独立部署，Q1—Q3完成、Q4正式迁移后才切换。
4. 联合回归425项通过；随后新增SQL实际超时、未封存名称变化、未登记PDF、真实os._exit(87)释放查询锁负例，直接查询套件32项通过。前端相关回归368项及新增搜索4项通过；浏览器使用真实构建、实际路由和临时PG验证65行分页、首字母候选、Enter显式选择、标题单行、缺日终态停止和人工刷新恢复。没有下载源站PDF。
5. 真实来源只读验收：155日期210602条记录，002245.SZ返回36条；五个API场景冷GET约1.15—1.58秒，准备约1.09—3.27秒，公告FD峰值32、SQL最大约0.163秒、RSS峰值459.88MiB。每场景独立进程，1次冷GET+5次暖GET，P95按六次最大值保守记录；未清OS缓存。全历史2471文件/12064773行只核验清单和footer，未做全历史完整GET，不能据此宣称全历史API性能或DG成功。

**清退授权与完成：** 此前自动审批两次拒绝旧源码删除，用户随后明确“提交，然后授权。完成Q2”。主体提交6dbb27e4后，已删除catalog_builder.py、preview.py、announcement_query.py、company_query.py和announcement_catalog.py；catalog.py仅保留静态旧schema与LegacyCatalogSchema只读结构校验，LegacyCatalog迁移入口已同步引用。旧运行期查询/写入/初始化/升级接口与catalog_path清零，不保留双轨或回退。没有删除任何正式SQLite、PDF或Lake数据。

收尾CodeGraph query/impact覆盖Catalog、CatalogBuilder、PreviewRuntime、CatalogPreparationPort及迁移/API/App/预览测试，实际源码AST核验五个旧模块import引用为0，sync/status显示索引当前。收尾联合回归334项通过；新增只读校验有效schema/丢失索引/错误scope三例通过，catalog来源合同套件9项通过。Q1迁移、Q2查询/预览、真实路由和依赖护栏均验证；ingestion-lint、docs integrity、diff check通过。静态schema校验在只读连接执行，读前读后文件SHA256一致；迁移历史事实和原字段不丢失。

Q2本阶段已完成；没有推进Q3、启用正式PG或执行正式迁移。下一阶段Q3负责执行器/Web/CLI统一PG存储，之后Q4负责正式迁移与切换；当前阶段代码仍不能独立部署。性能/浏览器记录沿用本节有限范围，源码清退未改查询算法、前端或来源数据，不重复声称新增全历史验收。


## 25. Q3 执行器、Web 与 CLI 统一 PG（2026-10-07）

**状态：已完成开发与隔离验收，尚未正式迁移或启用。** 本阶段依据§22.5、22.6、22.10、22.11实施；Q2提交6dbb27e4、60099811。公告列表继续直接查询DG Raw，PG只保存归档业务与小型查询控制事实，不新增全量公告目录副本。

### 25.1 实现合同对账

| 要求 | 当前实现 | 验收 |
| --- | --- | --- |
| 唯一PG运行存储，无SQLite SQL转译或回退 | Foundation Ledger/ExecutionLedger/LedgerQuery原生命名绑定SQL；所有读写按archive_id隔离 | 不自动DDL、缺失schema/归档阻断、两归档同文件键隔离、运行import护栏 |
| 本地专用DSN和共享有限池 | App lifespan组合一个归档pool，查询/下载共用；CLI沿用ANNOUNCEMENT_ARCHIVE_DATABASE_URL，不回落主DATABASE_URL | CLI独立DSN测试、真实Web路由和浏览器；本地开关/Prod合同不变 |
| 锁、接管、续跑和幂等 | 保留Volume和本机execution.lock；archive_execution行锁领取；取得本机锁后显式记中断，启动不发HTTP | PG并发唯一领取；枚举、下载、prepared、rename、结果提交的进程退出与恢复 |
| 停止、冻结集合、精确失败重试 | 每个业务检查点读取持久停止；继续只取pending；按原任务家族失败集合建立关联批次 | 停止/枚举取消、源追加不扩大继续/重试、原失败历史保留；110000关联行只认本家族成功 |
| 文件协议与风控间隔 | Files/Downloader共用；prepared校验和原子提升、HTTP前独立提交request_started；cooldown归档隔离 | 403/429/重定向/超时、跨进程cooldown、真实PG只读时零HTTP、已提交PDF保留 |
| 观测失败不阻断文件业务 | 进度/心跳5秒节流，心跳写失败退为只读owner/stop观察；业务读写失败仍阻断 | 单独注入observe失败仍完成PDF与结果提交；PG离线前后失败注入 |
| 台账查询和维护 | 有界分页、四秒SQL观察预算、Ctrl+C驱动cancel；哈希/修复不持有PG事务；修复仍取得磁盘和本地锁 | JSON概况/文件/历史、整数游标往返、取消/超时和零HTTP修复 |
| CLI输出迁移 | storage包含kind/database/schema/archiveId/schemaVersion；删除ledger_path和顶层schema_version；原rowid参数仍是整数，对应row_seq | 两CLI输出与历史游标回归；原PDF技术方案§14、LLD§19同步 |

运行时旧SQLite初始化/升级与未引用Presence实现已清退。旧schema静态校验移到legacy_schema，仅显式迁移源读取器使用；既存SQLite文件不修改、不删除，迁移43例仍保留历史事实校验。没有引入新配置、依赖、数据库安装或业务数据表清理。

### 25.2 隔离验收与正式边界

[Q3报告](../../../../reports/wealth_data_center_q3_acceptance_20261007.md)记录后端/架构352项、前端1134项、浏览器1项通过，typecheck/build、ingestion-lint、compileall、docs integrity和diff check通过；包含CodeGraph、临时PG容量与浏览器证据。浏览器使用真实公告路由、PG台账、临时Parquet和模拟PDF站点：6个日期匹配文件显示业务进度与请求等待；一份404后仅该失败文件重试；刷新列表后6条显示已下载。临时站点共7次PDF请求，其余文件没有重复请求。

[容量样本](../../../../reports/wealth_data_center_q3_profile_20261007.json)只证明500行事务、110000任务文件家族下的有界失败查询，不能外推全历史Lake/线上源站性能。DG更新、正式归档、主数据库与服务均未操作。前端未改动；当前代码必须完成Q4正式迁移、读回对账和环境切换后再部署启用。SQLite文件清理另按Q4批准范围执行，不将Q3开发授权当作数据删除授权。

开发前后CodeGraph query/impact覆盖Ledger、ArchiveStore、ArchiveSupervisor及执行链；sync/status确认索引当前。Protocol动态注入和SQL不能单靠图证明，已补读App→Ops执行器及Biz→Foundation查询消费者并用实际路由验收。依赖矩阵不变；仍需人工确认的边界是Q4正式数据数量/指纹、外盘身份和正式切换结果。


## 26. Q4 正式迁移、统一启用与清理边界（2026-10-07）

**状态：Q3提交b4c590fd；按用户授权已执行正式PLAN/APPLY、业务读回、幂等重放与PG配置切换。本机Web8000已恢复；旧文件清理尚未执行。** [Q4报告](../../../../reports/wealth_data_center_q4_acceptance_20261007.md)保存逐阶段证据，原SQLite不再被Web、下载和维护CLI运行链使用。

### 26.1 实际范围与配置

正式来源为§22.10精确5文件。四台账源版本3/2/2/3，关联表行数分别102568、33、49、42，合计102692；236个≤500行数据批。catalog只保留13查询和2预览的过期控制事实，copied_metadata_rows=0。目标为既存loopback:5432/goldenshare_lake_meta的独立announcement_archive；使用已有congming角色，不创建角色、数据库或主Alembic revision。

只在既有ignored `.env.web.local` 新增已设计的ANNOUNCEMENT_ARCHIVE_DATABASE_URL，本地模块开关仍true，APP_ENV仍local；远程DATABASE_URL不修改。Web以GOLDENSHARE_ENV_FILE=.env.web.local正常重启，两个CLI使用同一文件。没有改配置默认值、持久化位置或新增配置项。归档应用池仍独立有限4连接，Prod不启用该模块。

正式APPLY后、运行切换前，幂等重放逐批完整值比对，所有checkpoint完成且4归档ready。两条row_seq序列均超过导入最大值，旧CLI整数游标保留。默认363份成功PDF与三验收根各5份全部size/hash匹配，共378份；没有重新下载或复制。正式查询/CLI验收在切换后允许增加运行记录和短期查询控制事实，这不改变迁移完成时的原行摘要证据。

### 26.2 清理工具与批准步骤

Q4补齐运营工具的互斥动作：默认PLAN、--apply、--cleanup-plan、--cleanup。没有参数指定任意删除路径，CLI只用MigrationInventory.local白名单；--cleanup-plan验证源版本/卷、PGready及完整checkpoint/source SHA/规范摘要、热journal及实际开放连接，返回精确文件名、大小和物理身份，不unlink或更新PG。

--cleanup必须另获管理员批准。执行时重新取得原catalog、本机执行和外盘锁，保持旧源只读，关闭检查连接，再确认lsof无其它连接；所有源摘要和文件身份在首次删除前复核。按精确文件清单逐个unlink/fsync目录，不删任何父目录、execution.lock、archive.lock、web-archive.json、PDF、Raw或共享SQLite，不卸载系统/Python/CodeGraph共享库。

runtime可正常更新归档文件/任务、增加来源记录或GC旧控制结果。清理依据不可变迁移checkpoint和当时已完成的业务读回证据，不强求PG业务永久等于旧SQLite；不重跑严格迁移PLAN来覆盖当前业务状态。源SQLite变化、checkpoint未完成、业务行数低于已导入下界、未切换本地配置、开放连接或路径风险均阻断。

删除失败/取消不回滚PG，不回退SQLite。若已删除一部分，剩余文件保留供单独核查；不伪造全清理成功，不依据模糊glob继续删除。正式清理PLAN本次列5个主文件+catalog的零字节WAL/32768字节SHM，共343961600字节（约328.03MiB）；最终执行前再次核对，以当时清单为准。

### 26.3 验证与后续

临时PG/5源清理与迁移专项61项通过，覆盖仅白名单删除、保留共享文件/锁/PDF、未迁移/缺checkpoint/篡改/开放外部读者/热journal/符号链接/硬链接、取消和unlink失败；原生运行import护栏只将migration/cleanup作为显式运营入口，App/执行器不引用旧源。最终联合370项通过；容量报告改到临时目录后PG专项12项再次通过，compileall/docs integrity/diff check通过。五个真实来源API场景GET上界0.91—2.19秒，单SQL≤0.167秒、公告FD≤32、RSS≤509.82MiB；未清OS缓存。当前源最新10-06，当天默认区间包含10-07时已验证DC_SOURCE_UNAVAILABLE终态，未截短范围或触发DG补齐。详见Q4报告。

独立CLI使用既有dc5验收根、2026-07-26一天和3秒间隔，读5条/处理5文件，全部复用；默认summary返回postgresql storage及363已下载。没有自动全量下载，也没有改变正式Raw/PDF文件。真实Web登录页已恢复；无登录凭证时不绕过正式认证，API性能验收的认证覆盖仅限独立测试进程，详情见报告。

CodeGraph query/impact覆盖ArchiveMigration、CLI、ArchiveCleanup与测试消费者，sync/status核验当前索引；Q4不调整子系统依赖矩阵，不修改DG或Prod数据集合同。旧文件清理仍需独立授权，DG日常稳定性与全历史源数据质量继续单独验收。
