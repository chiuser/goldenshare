# 股票技术因子接入：第二批开发与验收

日期：2026-10-26。依据：[方案§13.4](../../docs/design/dagster-stock-technical-factor-onboarding-plan-v1.md)、[LLD§15](../../docs/design/dagster-stock-technical-factor-onboarding-low-level-design-v1.md)。第一批已限定提交为`0daf0b5e`，没有push，`paths.py`中其他任务的指数日线改动未混入。

当前结论：**独立审计发现的路径遗漏已修复，针对性23项及第二批离线回归113项通过，再次独立复核未发现新的确证问题，第二批具备申请第三批条件。**详见[独立审计收尾](independent-audit.md)。下文保留此前开发验收的实际证据；最新修复结果另见[path-fix-results.json](path-fix-results.json)。本批未实现历史回刷、bootstrap、PG结果读取和正式资产/job/sensor/catalog装配；整个数据集尚未接入完成。第三批未开始，正式执行未开展。

## 实现和计划逐项核实

路径均位于`orchestrator/src/orchestrator/defs`。

| 已批准要求 | 实现位置 | 验收依据 |
| --- | --- | --- |
| 当前日唯一完整unit、正常退出后验证summary | `io/stk_factor_pro_download.py` | 单T BY_POINT、实际planner唯一unit及当前契约身份；第二unit、缺unit、关闭1304、STOPPED/CANCELLED/FAILED、错task/行数/单位数、bool冒充计数、终点不完整均拒绝，Raw候选0次。 |
| 只在本次内存处理、最后释放 | 同上及`io/stk_factor_pro_candidates.py` | 原UnitResult/tuple在会话关闭后可用；DataFrame按列转成独立临时U，解除注册后仍可读。当前合同/scope/内容摘要核对，U改变不能发布；正常/异常/取消均清表，两轮正常处理后unit引用数回到基线，不写日源副本/manifest/source-complete。释放由调用方try/finally明确负责，不以RSS下降冒充释放。 |
| 严格日期/类型和完整字段 | `io/stk_factor_pro_candidates.py` | 独立doc328字段顺序；每记录自己的fields映射，换序正常，缺/多/重名/错宽拒绝。HTTP int/Decimal、Prod float及NULL严格分开；非法日期、bool、字符串、非有限/溢出/下溢拒绝；负指标和NULL保留。错误定位到代码/日期/字段，不打印完整源行。 |
| B−K+U及Silver来自最终Raw | 候选模块 | 先将旧B物化到当前连接，不留指向将被替换目标的view；旧未返回行保留、新键补入、交集更新。Silver只从已读回Raw转换日期。独立字面样本证明最终两层都有3只股票及正确指标值。 |
| 两项完整校验及读回复用 | `checks/stk_factor_pro.py` | schema、键、日期、有限值先核；FULL JOIN一次聚合双向主键及259数值差异，NULL采用IS DISTINCT FROM，无epsilon。候选完整校验后，发布读回实际字节SHA/schema/行数一致才复用校验结果，不重复259列JOIN。没有注册正式check。 |
| 逐文件当前run发布 | `io/stk_factor_pro_publication.py`、`run_contracts/stk_factor_pro.py` | 当前候选→intent→prior/候选/取消/设备/空间复核→replace/fsync→读回→complete。日记录闭合字段、日期/上海时区/层/run路径与固定候选位置明确校验；错误记录不放行。Raw结果先yield，Silver失败不抹Raw；已替换文件不回滚。 |
| 失败后重新下载、无旧候选续跑 | 发布模块及源模块 | 当前正式文件保留；新run重新调用下载。旧10、后轮正式11、新源12时最终为12。已有当前run日候选/日发布记录拒绝续跑，但允许更早步骤已经写好的history-plan文件。真实子进程在Raw发布后os._exit(17)，另一进程新下载完成Silver=12。 |
| 进度与取消职责 | 下载模块、沿用组件契约 | 公开load→本机HTTP替身→503重试→成功日适配真实经过组件代码；三类标准通知出现，普通PAGE通知异常被隔离，summary记录1次通知错误。1秒状态复用、强制边界刷新、取消保持、读错/身份错/不允许运行状态拒绝，未下沉线程/IPC/锁。 |
| 纯覆盖集合供后批共用 | `asset_guards/stk_factor_pro_readiness.py` | 只用当前连接四个已验证关系；三侧按有效期统一身份，不改业务行。A/B应有、A/C实际仍为matched1/missing1/extra1；全天停牌扣除、盘中仍应有。别名去重、缺失/过期/歧义未知，未知分支清理上次差集。无instance、文件读取或写入。 |

首次合法0源且没有旧文件时，本批返回无文件事实，不制造check，也不在底层提前抛Failure绕过记录。第五批按LLD§4.0.1保存缺失/统计及waiting后执行约定业务Failure；本报告不宣称该job编排已实现。旧Raw有效而新源0保留旧实际数据，部分数据可正常发布。覆盖evaluator、完整缺失清单持久化、PG阶段观察及历史资格在对应后批落地，不以空函数占位。

## 实际测试结果

| 组别 | 实际结果 |
| --- | --- |
| 第一批/组件及第二批合并 | **373 passed，18 warnings，28.71秒**；其中本批新增92项。见[输出](targeted-tests.log)及[JUnit](targeted-tests.xml)。18项为既有Dagster预览/弃用警告，未屏蔽。 |
| 资产治理 | 12项主测试、513项子测试通过；现有受保护runner、2个隔离批次。 |
| 运行合同静态门禁 | 113项主测试、5项子测试通过；原runner、15个隔离批次。 |
| metadata/ETF路径/指数因子 | 34 passed，0.52秒。 |
| 当前Definitions加载 | 1 passed，1.77秒；真实load及validate_loadable，无本数据集提前装配、连接0、7项原生隔离反例通过。见[资源证据](definitions-resource-result.json)。1项既有Pydantic弃用警告未屏蔽。 |

总计**533项主测试、518项子测试通过**，组别汇总见[regressions-summary.json](regressions-summary.json)。修改Python文件默认Ruff、全src/tests致命错误门禁、文档完整性及空白检查通过。治理完整日志位于`/private/tmp/stk-factor-batch2-20261026/{governance,static-gates}.log`，没有重复执行正式资源审计。

## 有界真实样本和成本

复用第一批已验证的五日响应，按T筛出`000001.SZ/2026-10-16`这一行完整261字段；不将五个日期混入一个单日unit。原始证据是只读保存数据，当前源请求0。正常首次发布和同日等价更新各一次，全部261业务值逐项核对；Silver仅日期转DATE。该结果证明隔离业务链路，不证明全市场耗时、内存峰值、真实复权历史或正式PG。

| 样本 | 耗时 | SQL语句 | 含Parquet读取的SQL | 字节SHA读取次数/量 | 原子文件操作 | 正式目标替换 |
| --- | --- | --- | --- | --- | --- | --- |
| 首次正常日发布 | 0.5210秒 | 52 | 7 | 17次/519,627字节 | 6次/74,501字节 | 2 |
| 同日新下载、内容等价 | 0.9202秒 | 70 | 10 | 27次/864,196字节 | 4次/5,860字节 | 0 |

两轮各创建2份发布候选，共68,889字节/轮，各形成2份complete记录；当前两份正式Parquet合计68,889字节。无日下载缓存、无预先日源COPY，只有必要Raw/Silver候选。SHA字节数是应用层校验读取量，Parquet读取SQL数不等于底层物理磁盘读取次数；不把它写成精确磁盘IO或全市场预算。计时包含下载替身、转换、候选、发布/读回及清理；详见[原始成本记录](bounded-performance.json)。

全市场日结果150～220MiB、阶段峰值0.5～1GiB仍为已确认估算；没有跑内存压测。16GB/4线程生产连接默认、组件2GiB unit/64MiB响应限制未改。测试连接只用临时目录和256MB/1线程以约束隔离规模；没有新增运行配置。正常、同日更新、失败完整重做及最后读回均覆盖，不计旧缓存节约。

新增适配集成另有2次本机HTTP替身请求，使用假token；不是Tushare请求。第一批组件既有HTTP回归也仅连接其本机替身。正式Tushare、DG instance/PG、Lake、Prod、动态分区、历史事件及自动化本轮均未操作。

## 审查中修正与后续交接

实现复核修正了run目录的衔接：允许前序历史名单占用同run目录，只禁止已有日候选或日发布记录续跑；并补正负回归。发布后以相同已验字节/schema/行数复用候选审计，避免重做整套字段JOIN；日U变更、记录路径/时区、挂载保护均有针对性测试。这些落实原已定规则，没有新增业务决策或要求扩大范围。

CodeGraph已用于核VerifiedDaySource和现行moneyflow发布消费者/影响面，确认不能直接带入其续跑或锁规则；本批直接阅读新函数及消费者补核，收尾sync/status为up to date。依赖保持在DG内部，无Prod import、公共下载器改造、前端/API迁移或已有数据集入口替换。

第三批可使用当前日源、候选/校验、逐层发布结果及纯覆盖函数；扩展历史范围、历史源落盘和history发布记录时仍按原方案独立确认开工。第五批负责在完整job内串名单/授权、日结果事件、0行业务失败及必要历史，不能跳过这些未实现步骤直接启用自动化。
