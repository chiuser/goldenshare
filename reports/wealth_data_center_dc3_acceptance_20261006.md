# 数据中心 DC3 下载管理后端验收

日期：2026-10-06。依据：用户“提交，然后继续推进DC3”、已确认产品与Figma R1、技术方案及LLD §16—17。DC2已提交 `a1b47713`；DC3完成本阶段后端开发与隔离验证，尚未提交。仅在dev-interface工作区推进，其他任务文件保留。

## 交付范围

完成日期预览、后台执行、进度、停止、原任务继续、精确失败重试、重新检查、历史和文件明细接口。日期及请求间隔是下载范围的全部输入，归档目录引用既有DownloadOptions默认；禁止公司、任意URL、单公告新建下载和浏览器传入路径。单项重试只用于原任务已失败文件。

App负责认证、生命周期和装配；Biz API/Service/RunQuery调用Foundation纯执行端口与本地DAO；Ops Supervisor/PreviewRuntime组织执行。CLI与Web共享execute_run、Files和Downloader，没有第二套物理下载循环、任务队列或Prod/DG下载任务。依赖矩阵未改变。

具体21个实现/测试文件及SHA见[机器证据](wealth_data_center_dc3_acceptance_20261006.json)。相关设计、产品状态和架构快照同步，历史DC1/DC2报告保留原交付时含义。

## 计划对账

| 口径 | 实现 | 验证 |
| --- | --- | --- |
| 日期/间隔、五项预览、零请求准备 | PreviewRequest、PreviewRuntime、Catalog | 真Parquet/路由：3公告→1文件+1无URL；rec_time缺失保留；零文件不建run，非有限/倒置/额外参数拒绝 |
| 版本固定、500批、完整后HTTP | Catalog preview_days、Source、enumerate_run | 预览过期/更换卷/来源变化拒绝；枚举期间改源阻断，已提交数据保留且HTTP为零；真实五万唯一文件预览 |
| 原子创建、单活动、不排队、幂等 | Catalog原子preview+私有snapshot、Supervisor、双锁、receipt/slot/session | 创建失败不留孤立快照；列表准备不误领preview；活动同key读回，变payload和其它命令409，CLI争锁拒绝 |
| 进度来自持久事实 | Ledger/WebControl/RunQuery | 准备total=NULL，完成量=成功+复用+失败；未知字节总数NULL，阶段/等待/业务更新时间/心跳分开；ETA=NULL |
| Stop/Continue只原集合 | 持久stop_requested、pending keyset | 准备中止保留500条但不能继续；sealed停止继续原3份，后来新增第4份不进入；已完成stop不改终态 |
| retry只原未解决失败 | ExecutionLedger固定失败key复制、根/父关联 | 全部10份失败→total10，单项→total1；不重取日期范围、不包含成功项；原404/标题原因保留，关联批次可分页 |
| 退出恢复不自动HTTP | ExecutionLock、recover_abandoned、会话与尝试终态 | 5个独立子进程os._exit窗口：枚举、prepared、rename、下一文件下载、receipt持久后；pending原集合继续，落盘窗口零HTTP恢复 |
| 物理文件不受结果写失败回滚 | 原fsync/hash/prepared/replace、结果读回 | 结果写失败保留完整PDF，已有原成功attempt补一次succeeded结果；新日期下载发现已删文件可重新下载 |
| 检查不自动继续/清冷却 | Downloader有限probe、原Limiter | volume/localSource零HTTP，volume不依赖Raw在线；remote单session/有限重定向/1024字节前缀；冷却中stop零额外请求，原冷却保留；403/验证码只在remoteSource检查通过后允许Continue，local检查不能替代，新阻断清除旧通过结果 |
| 历史可离线、明细有原错误 | ArchiveBinding/ArchiveStore/RunQuery | 既有身份绑定时盘离线仍读历史；错误返回安全中文说明/HTTP状态；20/50分页，旧schema只读不升级；未知绑定不可用 |
| 登录与部署能力、边界 | App认证、capability、Foundation Protocol | 401/Prod404、纯端口无反向依赖；原CLI/台账/Raw/registry与架构门禁通过 |

当前API前缀 `/api/v1/wealth/data-center/announcements`：previews创建/读取/停止；runs创建/历史/详情/files/related；run停止/continue/retries/recheck。创建/继续/重试必须带UUID Idempotency-Key；关联批次和文件明细使用keyset分页。只在后台拥有锁、资源和持久receipt后接纳执行，不在HTTP请求内跑完整下载。

## 配置、存储与安全

新增本机 `announcement-download/web-archive.json` 保存最近验证的卷UUID、卷内根和固定归档位置；它只定位本机台账，不证明盘在线或文件存在。来源、默认、消费者、生效和测试审计先行记录在LLD §16；0600文件/0700父目录、同目录replace，无卷不扫描其它归档猜身份。默认目录及间隔引用原DownloadOptions，不新增env项、用户路径配置或依赖安装。

Catalog schema2仅新增preview_artifacts去重标记表，按500记录读取、批量提交、新key只核验一次；已知schema1原子添加并保留原索引/查询，失败回滚、未知schema拒绝。预览快照和preview记录同事务创建，内部状态preview不被列表准备线程领取。正式索引没有初始化或升级。

台账保持schema3与DELETE/FULL，原物理提交协议不变。后台每0.5秒读取停止意图，默认5秒写心跳和字节观察，阶段变化立即观察；观察失败停止后续单元，不能删除已提交文件。Continue/retry沿用原run保存的Source/DownloadPolicy。旧schema1/2只读可展示，不因历史查询迁移；旧任务缺完整恢复合同时只允许新建日期任务。

## 容量证据

复用DC2 `/private/tmp` 中已有800万记录的隔离SQLite负载，不复制正式Raw，也不打开正式归档台账。

| 场景 | 公告记录 | 唯一合成文件key | 后台统计秒 |
| --- | --- | --- | --- |
| 默认30日 | 1500000 | 34188 | 10.513 |
| 全160日 | 8000000 | 34188 | 41.407 |

峰值RSS132923392字节（约127MiB），SQLite8186400768字节（约7.62GiB，包含既有索引）。内存随500批次相关，API返回202 preparing，不把长统计放请求中；完整统计完成前不返回部分五项总数。

该容量库是合成SQL投影，其文件key重复，不是800万真实唯一文件或正式Raw合同验证；没有成功台账，文件stat次数0。它证明800万记录扫描、持久去重及计数规模，不证明800万stat耗时。五万真实唯一artifact identity另通过临时Parquet、完整Source/CatalogBuilder和实际API验收；34188/50000安全文件stat的独立容量证据仍见DC2报告。这些是点时样本，不是P95，也不包括首次800万索引构建。

失败集合查询EXPLAIN最初显示对每条失败SCAN fixed，改为按家族run_id和artifact_key查现有索引，无schema变更。实际临时schema3台账110000结果行（原失败50000、关联成功10000、无关成功50000）在共享4秒SQL预算内准确返回40000未解决项；另用最小表结构测算法约0.053秒，属于微基准，不是正式台账P95。重试、任务计数和每文件资格共用同一SQL，不得把无关日期任务成功当关联重试解决。

## 验证结果

组合回归468项通过，64.27秒：公告catalog/Web/CLI/DG读者/ledger/archive-runtime、definition/resolver/runtime registry和三个分层护栏。最终默认值收敛后Web接口58项通过，33.55秒；随后Catalog/Web原子创建复核82项通过（41.83秒），源站检查资格和分层复核88项通过（46.67秒）；台账/CLI/DC3复核205项通过（33.00秒），随后失败集合优化后的DC3全部45项通过（25.80秒）；最终共享Ledger/CLI及全部DC3复核206项通过（32.65秒）。本阶段新增DC3测试45项，包括5个真实独立进程退出窗口；真实路由/DAO/Source/文件未mock，仅外部卷检查及远程HTTP使用可控替身，并补本机真实HTTP重定向/间隔验收。

实际本机HTTP从响应完成到后续请求开始间隔至少0.045秒（配置0.05秒），重复日期run为reused且请求数不增加。

ingestion-lint-definitions、compileall、文档完整性/相对链接、git diff --check和CodeGraph sync/status均已通过。CodeGraph explore/impact/query覆盖共享核心、CLI、锁/台账、Supervisor/WebControl及纯端口；同名噪声与动态注入另读App/Biz/Ops/SQL及真实路由验证。现有Starlette/httpx弃用警告1条，不为此升级依赖。

## 未执行项与下一步

本轮没有正式台账打开或迁移、正式catalog初始化、真实源站PDF请求、业务表/Lake/DG/Prod写入、部署、依赖安装、新分支/worktree或推送。测试文件都在临时目录，本机服务仅为HTTP fixture。

当前停在DC3。DC4落地数据中心首页和公告页、接真实API、核对Figma24状态、轮询/重试/异常交互及本地/Prod差异；DC5再按获准隔离范围执行真实来源运行—停止—继续—重试—物理hash对账。正式DG连续更新验收是独立任务。后端完成不能替代页面和正式下载验收。
