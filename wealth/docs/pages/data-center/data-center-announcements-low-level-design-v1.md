# 数据中心与上市公司公告 LLD v1

日期：2026-10-06。状态：**编码级设计已获确认；DC1提交9ad6654c，DC2完成开发及本阶段验收、尚未提交；DC3—DC5待推进。** 依据[技术方案](data-center-announcements-implementation-design-v1.md)、[产品方案](../../../../docs/product/wealth-data-center-announcements-product-plan-v1.md) §5/§8.4 和 Figma R1。字段、SQL、状态、配置与测试以本文为网页目标合同；当前 CLI 行为仍以原 PDF LLD 为准。

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

`ArchiveExecutionPort` 只提供 `prepare_preview/create/stop/continue_run/retry/recheck` 与只读观察。`ArchiveCommand` 是本地文件归档命令，不是新的 DatasetDefinition 或 Prod ingestion action。元数据更新仍由既有 DG 管道负责，网页不操作 DG/Prod TaskRun。

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

schema1/2识别、写入口原子迁移到3；只读CLI仍可读取已支持的旧schema，不创建/升级/改变文件。迁移不清空/备份/改路径，不重新拉PDF；所有旧结果/来源/冷却保留。老run没有完整冻结/控制证据时`canContinue=false/canRetry=false`，原因“历史任务不支持精确恢复，可新建日期下载”；不可猜旧集合。schema2枚举已封存并具备完整run_artifacts者可经过校验接管；旧active仅在取得锁、证实无执行owner后记中断，不能触发HTTP。迁移必须在归档独占锁内，失败事务回滚，未知schema阻断。正式迁移另行授权。

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
| `DataCenterPolicy`（新增集中内部策略） |page50/history20/result50、候选limit20/keyword64、title200、SQL截止4秒、API读截止5秒、poll2秒、heartbeat5秒、失联提示15秒、preview/queryTTL900秒、catalog校验周期30秒、日期任务控制poll0.5秒、索引unit软预算60秒 |Biz/Ops共享明确子配置投影；不得env/page各放一份 |启动/创建；前端context读取展示默认/预算；超预算prepare或error，不截范围 |
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
| GET `/announcements/runs/{id}/files` |result=all/failed/pending/succeeded/reused，cursor?,limit≤50 |文件结果/失败原因/本批尝试；精确run集合 |
| POST `/announcements/runs/{id}/stop` |无 |202 stopping；终态/已请求返回当前状态；只能控制活动run |
| POST `/announcements/runs/{id}/continue` |Idempotency-Key |202原run恢复；只能sealed停止/阻断/中断且有pending，失败不包含 |
| POST `/announcements/runs/{id}/retries` |scope=allFailed或singleFailed、single时artifactKey；Idempotency-Key |202关联retry run；key必须原run失败且尚未解决，非任意URL/公告输入 |
| POST `/announcements/runs/{id}/recheck` |kind=volume/localSource/remoteSource |202检查；结果包含passed/blocked/unknown；通过不自动continue |

冲突409（活动run、preview过期/改变、query版本改变、不可恢复）；非法422；源/盘/DB不可用503；query preparing202是合法状态，不返回假成功空列表。不存在PDF内容/文件下载API或DG启动API。

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
|性能 |DC2完成30日/50k/800万/K存在性/深页点时样本 |查询已达本阶段预算；预览/下载性能仍待DC3 |
|真实API/前端/物理验收 |DC2查询真实路由完成；页面和真实归档未执行 |24画板与最小真实归档分别待DC4/DC5 |
|评审确认 |2026-10-06用户确认路线并授权DC1、DC2 |每阶段独立验收；产品已确认不重复拍板 |

## 12. 实施对账与文档关系

执行DC0—DC5顺序见方案§9。DC1先完成共享能力移位/台账/CLI回归，再DC2查询、DC3后台、DC4页面、DC5独立验收；不得先写页面mock当最终产品。每阶段记录R01—R19实际代码/测试/真实证据和未完成项。

原PDF文档新增网页扩展引用，不抹掉M0—M3/DG/维护历史证据；产品规则不改，只补技术文档入口；README索引与异常注册同轮更新。正式DG合同不变，consumer AST测试继续；若实际源/运行语义与本文冲突，先说明并修正文档，不使用兼容旁路或猜测补丁。

2026-10-06技术路线、DC1和本地依赖已获用户确认；DC1实现与隔离验收见§14。DC2已获后续授权，当前交付见§15；DC3—DC5未实施，不从schema3字段存在推断网页下载功能已经交付。

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

完整证据和未执行项见[DC2验收报告](../../../../reports/wealth_data_center_dc2_acceptance_20261006.md)及[机器证据](../../../../reports/wealth_data_center_dc2_acceptance_20261006.json)。DC2已完成但尚未提交；正式索引/台账、真实下载、实际Web启动、DG/Prod/Lake写入和前端均未执行，当前停在DC2。
