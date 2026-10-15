# 整页调度、共享加载与读取优化

当前：**技术门禁已全部通过，页面待用户验收。** 最终产品385项后端回归、178＋4原预算及306次混合／双标签页请求通过，HTTP最大2.976秒。旧4.054秒503、投影候选4.015秒及初轮成绩均保留；最新完整对账见文末。未提交或部署。

用户授权先更新原技术方案和LLD，再落实这两项优化；日线及60／90／120分钟、原算法、数据校验及4秒预算保持，页面自行验收。本轮技术设计统一见[预测方案§20](../../wealth/docs/pages/index-detail/index-detail-xxm-key-point-forecast-implementation-plan-v0.1.md#20-整页请求调度与共享加载2026-10-15已授权实施)和[LLD§14.5](../../wealth/docs/pages/index-detail/index-detail-xxm-implementation-and-low-level-design-v0.1.md#145-整页调度与共享加载lld2026-10-15已授权)。未建设发布后预计算、持久化快照、后台任务或正式表。

## 原因和实际改动

优化前的36次诊断保存于before_mixed_36.json，其中7次因两个名额耗尽返回繁忙；18次整页突发保存于before_page_burst_18.json，两轮四个预测都在读源阶段超预算。它们是有界压力场景，不是线上自然失败率，也不是用户那次网络记录。前轮只测XXM两并发，不覆盖此整页读源争用。

- `wealth/src/features/index-detail/api/indexDetailRequestScheduler.ts`：标签页唯一队列，轻请求最多2个，全历史识别／预测独占；图表、九转、识别、预测按优先级及FIFO执行。排队取消不发网，发送后保留原5秒，释放名额等整个Promise结束。
- 两个分钟client、页面指数九转loader（抽到indexNineTurnLoader.ts）、XXM两个client同步接入；预测hook清除局部配额，保留每周期去重、隐藏／卸载取消、焦点／60000ms刷新及独立重试。股票共享hook与wealthFetch保持。
- `index_detail_xxm/shared_loads.py`及query_service：同key重叠请求共用一次加载和校验，等待者不占2个源名额；名额只在实际源工作期间持有，两个build使用已发布快照。每位请求的等待仍计入4秒；容量与失败处理有界，无TTL。
- XxmCache复用验证身份：每个独立分钟加载仍比较两路完整签名，日线仍读真实数值；源／完成上限／开市日历均不变才跳过已完成的连续性和体积遍历。追加及修订采用copy-on-write，旧请求持有的状态不被修改。
- forecast_query_service：当前来源和适用日历先核验，再按前缀指纹／两个Spec／expected／asOf／未来日历指纹复用完整响应，深拷贝返回。源和响应共用原64MiB／16项LRU，不增加第二个缓存预算。源晚到、历史修订、日历／Spec变更及20点切换均按原规则重新判断。

公开参数、DTO、异常码、MAIN_SPEC／FORECAST_SPEC、原算法与生命周期、完整历史范围、Foundation Reader及全部源校验、Figma／Card／图层样式保持。新增的是内部调度，不是新配置项；参数来源和消费者审计见方案§20.4。App→Biz→Foundation与Wealth经HTTP的方向保持。

## 隔离回归

相关后端317项通过，覆盖原来源／识别／预测／展示／业务日期／九转消费者和架构门禁，以及新增共享加载、失败传播、等待超时、容量、四周期复用／修订失效／只读快照、响应副本及LRU驱逐。初轮103项和专项16项均是最终相关回归的子集，不相加。原文见backend-initial.txt、backend-concurrency.txt、backend-regression.txt。

前端全量165文件／1172项通过（现有环境，maxWorkers=2），包含调度优先级／独占／FIFO／失败释放、排队取消、发送后5秒、独立标签页队列、四行状态／刷新／切换／旧响应隔离和真实响应展示。类型检查及build通过，见frontend-regression.txt、typecheck.txt、build.txt。Starlette/httpx弃用和Vite分包提示为既有提示，本轮未安装或升级依赖。

## 整页混合与双标签页技术验收

入口为`python -m scripts.research.index_market.xxm_page_request_audit --output <新目录>`；Python启动独立原路由／鉴权／DTO／query服务，显式正式源目录，仅只读PostgreSQL事务和正式Gold，不运行应用lifespan／后台任务。Node使用已有esbuild把产品TS调度器、实际API客户端、九转loader及adapter装入两个独立模块实例，模拟两个标签页各自的队列、共用同一后端。没有打开／自动操作浏览器，没有取用户登录凭据或关闭原鉴权。

实际混合包括所选周期图表、日线及五个分钟九转、对应XXM图层和日线／60／90／120四行预测。日线每页12请求、分钟每页13请求；四周期×单／双标签页×冷暖，共16组、306个HTTP请求。cold是新query cache，没有清OS缓存；warm沿用前一轮缓存。每个新冷轮都真正读三周期两路完整历史，不用预热通过门禁。

第一轮结果：306请求全部200且HTTP含正文传输均≤4秒，最大3.861秒；其中预测最大2.519秒，预测侧新增阶段最大134.59ms。双标签页每个分钟周期也各只完整读一遍bars及indicators；暖轮全部零完整重读，独立请求仍执行来源签名和适用日历检查。最大缓存约42.20MB、8项，低于原64MiB／16项；这是缓存计量，不是进程RSS。

96份四周期完整预测响应与前轮同10/14快照逐字段一致，见page_payload_comparison_final.json。原文、各请求与整页耗时见page_mix_final及page-mix-final-run.txt、mixed_summary.json。按本次机器实测，含UI排队的整页冷启动约9.90～15.13秒、暖轮约4.24～9.44秒；因此本轮证明单HTTP预算及结果稳定性，不宣称四行／整页4秒全部就绪。

首轮page_mix因验收脚本保存文件时遗漏局部变量而中断，12个产品HTTP均成功且最大2.77秒；修复脚本后完整重新跑16组，旧日志／目录保留。未因此修改产品逻辑、预算或数据范围。

## 第一轮收尾状态（读取扩围前的历史记录）

当前为“已实现、预算门禁未全部通过”，不是完成交付。原160次冷暖和前8组／16次两并发请求通过；最后一组90／120冷读并发中，90分钟HTTP503，build4.0095秒、HTTP4.0541秒，compute未开始，原保护生效。见real_api/failure.json及real-api-run.txt。该组未完整记录通过数据，后4次最新请求未执行，不能标为178＋4通过。8份已保存冷暖完整响应与原版一致，见budget_payload_comparison.json。

失败后只读定位3组／6次同代码冷读均2.78～3.88秒成功；首组90分钟签名0.506秒、完整读取／对齐2.674秒、缓存计量0.111秒，见source_timeout_diagnostic.json。阶段存在嵌套，不能重复求和。失败当次没有子阶段测量，不猜唯一根因，也不以这6次成功替换正式失败。计时期间未同时跑测试、构建或CodeGraph同步，没有改代码／阈值、删除校验／历史或停其他进程。

遵守根AGENTS开发执行链第7条，已暂停后续落码，向用户申请是否扩到现有分钟读取层做只读优化预检；完整历史、全部校验和4秒保留。已完成代码、317／1172项回归及306次混合结果均保留，等待范围确认后才能推进预算门禁。CodeGraph explore／impact及完成后的sync／status已覆盖共享加载、缓存、两个build和全部前端真实消费者；依赖矩阵不变。

本轮没有提交、推送、部署、安装、重启用户服务或正式数据写入。页面最终由用户验收；原预算／超载保护继续生效，不保证无限标签页或任意外部负载均达标。validation_summary.json明确保存各门禁通过／失败／未执行状态。


## 读取层扩围授权

用户已同意优化现有分钟读取层。当前执行状态为已授权预检：先以隔离候选证明完整历史、全部校验及4秒保持，达标后修改正式读取代码。上文暂停和失败为历史记录，继续保留。范围／代码／反例映射见预测方案§20.6与LLD§14.6，新增证据与原real_api失败分目录保存。


## 最终读取优化与交付对账

用户已批准扩围后，先修改方案§20.6／LLD§14.6，再只读预检，达标后落码。中间表过滤和单次聚合候选没有稳定收益，未采纳；只投影消费字段虽改善中位数，但有一次HTTP200耗时4.015秒（build3.981秒），未采纳为最终方案。该轮曾有本任务辅助文件名搜索并行，不能据此猜唯一瓶颈，也没有把这次超预算算通过。候选参数顺序／fixture工具错误日志同样保留，不算产品失败或通过证据。

最终候选为字段投影＋两路并行，各256MB／1个DuckDB线程，维持单请求原总512MB／2线程；原源请求名额仍2。候选178＋4全过后，才落实Foundation Reader的value_columns、read_complete_history_pair及共享私有完整读取实现，source迁移两处读取。公开分页及默认完整历史仍返回原字段；SQL全文件检查、schema、文件签名／符号链接、重复、两路完整键、有限值及连续性不变。pair各worker开始时扣除排队，原Timer／finally负责中断和关闭，两路完成清理后返回，保持bars错误优先。新资源策略／字段参数的默认、来源、消费者、生效及测试审计见方案§20.6；无外部／持久化配置。

正式产品门禁：

| 门禁 | 结果与原文 |
| --- | --- |
| 回归 | backend-reader-regression.txt：385项通过，含非目标／无目标错误、投影原字段白名单、默认完整返回、行数预算、配对真实连接资源／并发／异常清理／过期不读；reader-targeted-tests.txt的210项是子集 |
| 前端 | 原调度落码后的1172项全量、typecheck／build均通过，Reader扩围后未修改前端；最终Node重编译实际客户端走原API，无浏览器自动化 |
| 完整历史 | reader_product_parity/parity.json：三周期各17264／12948／8632根，每路4316文件，完整字段、投影及pair的计算用键／值完全一致，前后签名一致；截至10/14 |
| 正式原预算 | reader_product_api、reader-product-api-run.txt、reader_budget_summary.json：160冷暖＋18并发＋4最新全部通过，HTTP最大2.976054s、计算最大77.985ms、10779B，进程峰值RSS约1.076GB；512MB不是RSS承诺 |
| 正式混合／双标签页 | reader_product_page_mix、reader-product-page-mix-run.txt：16组306请求全200，最大2.859414s；预测最大2.463425s，计算最大136.718ms，缓存42199161B／8项。冷两标签页每周期各两路只完整读一次，暖轮零完整重读 |
| 响应一致 | reader_budget_payload_comparison.json：12份正式响应与已通过的候选全字段一致；reader_page_payload_comparison.json：96份正式响应与原版同10/14快照全字段一致 |
| 保护与边界 | reader_identity_comparison.json记录7个算法／Spec／文本及共享hook／fetch不变，Reader和source为已批准扩围；CodeGraph explore／impact及最终sync／status覆盖新旧入口／消费者，无依赖矩阵或公开HTTP／DTO变化 |
| 用户可见结果 | 四周期文案、Figma、图层不变，页面由用户验收；整页含队列冷8.29～12.93s、暖4.39～11.16s，4秒是单HTTP预算，不能说整页4秒完成 |

计划R1～R7及新增字段／资源／完整历史约束已在方案§20.7逐条映射代码、正反例与真实证据。最终代码没有以删历史、跳校验、暖机、增加总DuckDB预算或延长4秒通过门禁。没有在最终计时期间并行运行本任务测试、构建、文件清单搜索或CodeGraph同步。前次real_api失败仍是事实；只有修改后的独立候选和正式产品完整重验算当前通过。

可复现入口均在scripts/research/index_market/README.md：xxm_history_projection_audit、xxm_forecast_display_audit、xxm_page_request_audit；输出每次必须使用新目录。candidate_identity.json及候选.txt是当时预检输入快照，不被产品导入；当前唯一产品代码／文档清单为changed_files_final.json。未提交、推送、部署、安装、重启用户服务或写正式数据，隔离服务已停止。页面及任意其他外部负载／更多标签页尚不作本轮验收承诺；评分、软件公式独立验证和生产分钟发布仍后置。


## 提交记录口径

用户已授权将本轮代码、日期对齐及验收证据一并提交。上文“未提交”和validation_summary的committed=false记录的是技术验收当时状态；实际提交以Git历史为准。scripts/research/index_market/README.md仅提交本轮追加的XXM运行说明，已有P0市值研究段落保留在工作区，不进入本提交。commit_scope.json记录提交白名单和暂存内容哈希；不推送或部署。

提交格式检查仅归一化生成日志的行尾空白和多余尾部空行；两个报告目录各自的raw_log_bytes_before_commit.json保留原始字节（base64）及SHA256，可逐文件准确恢复。失败文本、测量值和响应JSON不作语义改写；产品代码哈希保持验收版本。
