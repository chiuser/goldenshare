# Q2 直接查询交付与验收

依据数据中心 LLD §22.6—22.11；Q1 已提交 d6cc3971。Q2 不启用正式 PG、不修改 env，不迁移或删除正式 SQLite/PDF/Raw。禁止全市场公告副本、SQLite 回退、源站请求和新依赖安装。

## 开发约束与验证映射

| 硬口径 | 实现落点 | 正反验收 |
| --- | --- | --- |
| 单 DuckDB、32 公告 FD、4 秒 SQL、256MiB | Foundation direct_source | 缺日/零行/schema/超时/FD上限 |
| 原身份、全范围过滤计数、稳定页 | direct_source + PG controls | Unicode/NULL/空白身份、深页、状态过滤 |
| 固定 FD、完整来源版本复核 | direct_source manifest | replace/原位修改/换卷/名称词表变化 |
| PG短事务、advisory领取、无metadata副本 | query controls + Ops source runtime | 退出重建、归档隔离、无 DDL/主库调用 |
| 查询/预览统一准备、真实进度、物理GC | source runtime | 终态停止、取消、GC分批和续跑 |
| 唯一DTO与错误合同 | Biz schema/service/API + Wealth contracts | 旧字段零消费者、路由校验 |
| 复用搜索控制器 | stock-search controller + CompanySearch | 默认首页/交易助手、公告显式选择和竞态 |
| 预览内容SHA、范围复核 | source runtime + supervisor | 无HTTP、源改变失效、封存字段不降级 |

配置沿用 LLD §22.5 审计：source_check_seconds=30 取代 catalog_check_seconds，移除 catalog_unit_seconds；file_batch_size=32、gc_seconds=60、gc_batch_size=500。均为内部 DataCenterPolicy，消费者仅来源读取、临时结果回收，不加环境变量或页面参数。

CodeGraph explore覆盖列表/API/App装配、预览和三搜索消费者；impact(Catalog)识别 query、preview、supervisor、迁移只读源及测试。迁移只读源保留历史 schema 读取，运行期目录消费者须清零。子系统依赖方向保持 Foundation←Ops/Biz←App。

状态：直接查询、API、共享搜索和预览迁移已实现并有限验收；旧源码清退受自动审批阻断，Q2尚未完整完成，不能独立部署。

## 交付文件与边界

- Foundation：新增clients/announcement_archive/direct_source.py、company_source.py、query_presence.py；新增dao/announcement_archive/query_controls.py；修改budget.py和config/announcement_archive.py。
- Ops/App：新增source_runtime.py；supervisor.py范围复核迁移PG来源事实；announcement_archive_lifespan.py统一组合来源runtime，不启动旧catalog/preview线程。下载执行和CLI尚待Q3接PG，本阶段App明确execution_not_ready，不能发布半成品。
- Biz：query_service.py、download_service.py、errors.py、announcements API及announcements/downloads schemas同轮迁移sourceVersion、ledgerAvailability和准备DTO。没有改Task/Files/History业务合同或新增本地PDF服务。
- Wealth：stock-search控制器新增可选候选加载/交互策略和互斥完整候选选择；CompanySearch薄展示层、companyCandidates适配、QueryPanel及useAnnouncementQuery、contracts/fixtures与测试迁移。无新搜索框架、持久化公司字典或外部开关。
- 测试：direct_query32项、改造catalog来源合同夹具/实际Web路由与下载回归、进程runner；新增只读profile与browser夹具、companyCandidates交互负例。
- 文档：原产品/技术方案/LLD、Wealth索引、错误码注册表、CodeGraph局部入口快照及本报告。

Foundation←Ops/Biz←App依赖方向不变；未修改DatasetDefinition、DG、Prod DB或Alembic。配置审计按LLD§22.5，仅内部策略迁移，无新env。

## 正反测试结果

1. 联合公告及数据合同/依赖护栏425项通过（127.96秒），包含迁移43项、真实注册查询路由、原下载的重试/冷却/封存/进程恢复。既有下载执行回归仍使用隔离SQLite，因为PG执行切换归Q3；这不表示新App已能执行下载。
2. 随后新增四项Q2负例，直接查询32项通过（9.16秒）：SQL实际中断后连接可复用；未封存名称改变不冻结错误版本；未登记PDF/NULL代码不冒充已下载；子进程os._exit(87)释放PG advisory锁、未封存presence清除后重建。其余覆盖NULL/Unicode/控制字符、29类URL空白身份、125行深分页、缺日/合法零行、源replace/原位修改/换卷/名称与词表变化、58已下载/27未下载全范围计数、删除/大小不符、未知/退市/历史名称、SHA预览取消及1200行GC中断续跑。
3. Wealth相关60文件368项通过；新增候选4项通过：300ms/显式Enter/完整字段一次选择、日期reset与blur取消、202观察、终态失败停止且人工恢复。默认股票搜索6项及首页/交易助手UI消费者回归通过。
4. 浏览器实际构建+API+临时PG验收：65条列表首页50、次页15；PFYH→浦发银行600000.SH；无显式选择Enter不提交，标题公告64返回1行；改日期清除公司选择；外链_blank/noopener noreferrer；缺10/1明确日期错误、终态只有一次完成GET；补临时合法零行后人工重新读取创建新ID恢复1行。console error/warn为空。市场context404为fixture未提供的顶部行情辅助接口，不冒充整站验收。
5. 夹具只覆盖本阶段查询；Q3下载执行及Prod部署不作浏览器完成声明。临时浏览器/PG已关闭，用户实际8000 Web和DG未改动。

## 真实来源完整API性能

每场景独立子进程，真实Raw/PDF/旧SQLite只读；成功363个文件事实只复制到临时PG作状态样本。每API场景1次冷GET+5次暖GET，P50取中位数，P95按六次最大值保守记录。没有清OS缓存，样本数量有限；不是生产并发或全部历史API保证。注册路由使用实际DTO/auth依赖测试装配，无源站HTTP。补充真实36条Python身份/标题/URL逐行对账后，最新复测66.51秒通过全部门禁。

| 场景 | 文件/源行数 | 准备秒 | GET P50秒 | GET P95秒 | RSS MiB |
| --- | --- | --- | --- | --- | --- |
| default30 | 30/28566 | 1.090 | 1.072 | 1.153 | 359.80 |
| stock155 | 155/210602 | 1.303 | 1.252 | 1.583 | 454.80 |
| all155 | 155/210602 | 1.408 | 1.124 | 1.526 | 391.59 |
| downloaded | 155/210602 | 3.101 | 1.173 | 1.579 | 459.88 |
| undownloaded | 155/210602 | 3.267 | 1.098 | 1.545 | 424.61 |

155日期2026-05-04—10-05：210602行、5738480字节、149 row groups；002245.SZ完整36行与原身份一致。已下载363行、未下载210239行，总数对齐。公告FD峰值32、单SQL最大约0.163秒、单unit小于1秒、RSS最高459.88MiB。全历史清单2471文件/12064773行/200734170字节/2383 row groups，用时0.739秒；仅footer与清单，不宣称全历史筛选GET或DG成功证据。

## 源码清退审批与剩余项

CodeGraph explore/impact/sync/status加当前import审计覆盖原Catalog59关联消费者、新query/API/App、preview/supervisor、显式LegacyCatalog读取及测试。迁移只读源仍需静态schema校验；新运行链未import五个旧模块。自动审批仍两次拒绝删除catalog_builder.py、preview.py、announcement_query.py、company_query.py、announcement_catalog.py并缩减catalog.py，理由是图中仍存在旧符号关联。删除命令未执行，没有绕过审批。已向用户请求精确源码授权；此项未落地，不能声称原catalog消费者已彻底清零。

下一步只处理清退授权和最小回归，完成Q2门禁后再由用户决定Q3。Q4才执行正式迁移/配置切换及精确SQLite文件清理；本轮未删任何正式SQLite、PDF或Raw，也未安装/卸载共享SQLite库。


## 收尾检查与证据范围

类型检查、生产构建、docs integrity、git diff --check及ingestion-lint通过（0 issues）。构建保留既有主包超过500KiB提示，没有安装依赖。CodeGraph sync/status显示索引当前；Q1提交d6cc3971可读回，其他任务提交未改写，本任务未提交Q2或推送。

1920×1080完整截图为query-1920.jpg；1440×900为query-1440.jpg。1440实际body宽1460，来自现有design-tokens.css的--cs-layout-content-min-width:1460px，会有横向滚动；Q2没有修改布局样式，不据此宣称1440无滚动。首轮恢复截图restored-query.jpg受当时窄视口滚动影响，保留作功能历史；正式桌面展示请看query-1920.jpg。console.json和console-desktop.json均无error/warn。第二轮桌面夹具覆盖了api-evidence.json，该文件仅记录第二轮请求，不当成首轮缺日/恢复完整网络日志。首轮交互结论来自当次Cua DOM和API计数工具输出，本文显式保留这一证据限制。

Q2剩余源码清退未获执行；停止在该门禁，未推进Q3、未切正式存储。本报告不是上线或正式迁移验收。
