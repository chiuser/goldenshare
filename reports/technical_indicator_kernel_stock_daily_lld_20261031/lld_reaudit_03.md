# 股票日线接入方案与LLD复审

2026-10-31。本轮是文档与当前代码的只读复审，仅同步管理员已确认的三位小数对照标准，不开发业务代码或重跑正式行情样本。

## 范围与依据

- 原方案：`docs/architecture/technical-indicator-kernel-stock-daily-api-integration-plan-v1.html`。
- 专项LLD：`docs/architecture/technical-indicator-kernel-stock-daily-api-integration-low-level-design-v1.html`。
- 当前API/query/mapper、D4执行/发送、SourceReadContext、LakePriceLocator、输入会话、App生命周期、现有Web测试/fixture、股票页面及客户端。
- 使用CodeGraph explore核入口、调用与消费者，impact核StockDetailQueryService影响面；同名符号及动态装配未覆盖的部分，按完整路径查看当前代码。
- Context7官方DuckDB说明核对ROUND(value,3)与ROUND_EVEN的区别。计算与返回保持现有精度；三位规则仅用于数据库/Lake价格来源对照，不把算法独立参考标准改掉。

## 结论

**不建议立即开工。** 当前仍有4项会影响实际开发或验收的内容未关闭，其中第1项涉及修改已批准配置限制，需要管理员review。其他3项属于执行细节，应先补齐原方案/LLD再编码，不需要新增产品功能。

来源样本已核验通过的事实继续有效。已保存168项价格用三位小数规则对照仍全部一致；本轮不重新读Lake、不连接数据库，不覆盖原五位对照、失败或验收证据。

## 发现

### G0 / 1. 历史2000根请求与5000文件限制有确定冲突

- **文档位置：**LLD §01、05.3、13；原方案 §03、05、07。
- **证据：**`src/foundation/technical_indicators/sources/read_context.py::record_file`在第5001个唯一文件登记时抛ResourceLimitError；`technical_indicator_price_locator.py::_open_metadata`登记定位文件，`technical_indicator_price_source.py::_inspect/prepare_basis/prepare_factors`也登记价格、因子、基准文件。
- **原本应怎样：**原接口允许limit=2000，本次保留该合同；既有5000文件配置也被写成不变项。
- **具体问题：**普通长历史股票的历史截止请求，2000根输出＋默认500根预热，需要2500个日期价格文件与2500个当日因子文件。最新基准日期若在该历史范围外，还需1个文件，至少5001个；额外定位/寻找该股票基准的文件还可能增加。与读取批次是否小于8192无关。
- **影响：**仅用字面内核结果检查limit=2000会通过，但真实历史请求会被文件保护拒绝，不能据该测试宣称真实2000根路径正常。
- **建议：**保留API的1～2000及唯一文件统一计数；将既有max_source_files配置增加至能容纳5001和有限定位余量的值，建议首版6000。6000只是本次提出的建议，不是已批准配置，也不保证所有停牌/退市历史都一定成功；实际资源限制仍可明确失败。不得把基准文件排除计数、减预热、拆成多次calculate或降API上限回避问题。
- **需管理员确认：**是。当前方案明确“不修改既有初值”，本轮未改变Settings、KernelConfig或该现行设计值。确认后须同步原方案、内核方案/LLD及本专项配置审计。

### G1 / 2. 数据库部分初始化和清理失败的步骤还不能直接照写

- **文档位置：**LLD §10、12。
- **证据：**新open_stock_daily_read_session尚未实现；LLD目前只有顺序清单。现有src.db只提供工厂和简单Session关闭，不包含此次监听器、只读选项和时限逻辑。
- **具体问题：**Session创建后获取Connection失败时，Session仍须关闭；监听器未登记成功时不能直接remove。移除监听器失败也不能阻止Session.close继续执行；close/invalidate又失败时，需要保留最初业务或控制错误，同时记录各项清理失败。
- **影响：**开发者照“先remove再close”的直线步骤写，可能在第一项清理报错后漏关连接；只写统一finally不足以消除这种歧义。
- **建议：**写出contextmanager的完整伪代码：session/connection/listener_registered/primary_error分别登记，资源取得后才更新状态；每项清理独立尝试，按归属处理invalidate和关闭；最初业务/取消/到期错误优先，正常路径清理失败也失败。明确未创建、仅创建Session、已获取Connection、已登记监听四种状态；复用原有限异常诊断规则，不新增线程或重试。
- **需管理员确认：**不涉及新业务决策；属于补齐既有资源归属要求。

### G1 / 3. 隔离验收的数据库入口及参考数据没有交接完整

- **文档位置：**LLD §08.2、10、14.1～14.4。
- **证据：**work示例固定调用open_stock_daily_read_session，生产合同只允许PostgreSQL/psycopg；真实R01～R04与部分普通回归却使用SQLite。当前AppBackend构造只接收session_factory_provider，没有读取资源替换方法。原tests/web/conftest的app_client只替换get_db_session，不能控制新worker的Session。
- **具体问题：**“隔离测试显式注入专用读取资源”没有给出注入位置、接口和恢复方式；fresh FastAPI应用的原路由前缀、两个中间件、异常处理器及来源错误观察也未给出完整装配方法。另外，独立参考写“原价格”可能被理解成未复权10元，而R02真正的目标qfq是前10根5元、后11根10元；旧D3 KDJ参考硬写cents±100，不能原样用于这里前10根±50的高低价。
- **影响：**SQLite请求可能在到达真实内核前就被生产方言检查拒绝，或测试缺少实际middleware/错误处理；参考SQL若误用原价或旧窗口，会让正确实现与错误预期冲突。
- **建议：**生产入口保持PG限制。测试在本模块精确替换open_stock_daily_read_session为同签名的测试contextmanager，每个worker自己创建/关闭SQLite Session，仅在测试作用域生效；P01不使用此替身。定义唯一fresh App装配函数，保留/api/v1前缀、原两个middleware/handlers与真实本专项lifespan；R04以有限观察记录原错误类型后交原500处理。参考表写死seq/close_cents/high_cents/low_cents：前10根500/550/450，后11根1000/1100/900；计算21根且只准备一次，不调用产品复权helper或旧夹具全量prepare。
- **需管理员确认：**不涉及新业务决策；需要先写清测试内部合同，不以生产支持SQLite方式解决。

### G1 / 4. 开发步骤要求在新调用方尚未完成时删除旧入口

- **文档位置：**LLD §03、04、16；原方案 §06。
- **证据：**当前股票路由直接调用StockDetailQueryService.build_kline，该方法调用旧build_kline_bar。LLD步骤2已经要求删除旧build_kline、改变mapper并迁移所有调用方；步骤3才实现App backend/Response及新路由调用。
- **具体问题：**若把步骤2当作可独立验收的阶段，旧路由仍指向已删除方法；哪些文件必须一起完成、何时可运行API回归没有写清。contracts/mapper/query/service之间实际可无环组织，但LLD没有给出导入顺序。
- **影响：**可能出现阶段完成后原API不可用，开发者为跑通旧测试又临时保留旧指标路径，违背禁止双轨的要求。
- **建议：**先写清唯一依赖方向：contracts只依赖现有MarketPageContext及标准类型；calculations依赖contracts/Foundation；mapper依赖contracts/原DTO；query service依赖contracts/mapper/query；业务service依赖query service/calculations/mapper；App依赖Biz和纯D4，Biz不新增导入App。编码可按此顺序准备，但旧方法删除、mapper调用迁移、新路由/依赖及App装配须作为同一迁移单元完成后再验API，不保留旧回退。lifespan明确最后进入新上下文、最先退出，旧两个上下文相对顺序不变。
- **需管理员确认：**不涉及新业务决策；是阶段依赖和完成条件的补充。

## 已核对、没有作为缺陷提出的内容

- R04的坏价格文件是否会先被“缺基准因子”遮住：当前locator.describe先检查选中价格所需字段，再准备basis，故能在预期位置报缺列；不应为这个假设额外造因子文件和扩测试。
- R05历史日期能否驱动原页面：页面确实读取URL的tradeDate，传给page-init，再把返回日期作为kline.endDate；无需修改前端或拦截改写核心请求。
- 同一个D4编码器是否接受旧DTO转换后的字典：当前encode_response_utf8接受普通映射，_ContractJSONEncoder已有支持，不需要改Foundation或另造编码器。
- 七MA、BOLL、MACD、KDJ的10项/16字段和当前算法版本一致，hist→旧macd、J→旧j的映射方向正确。
- 原有成功空结果、原DTO、300默认、日期/meta、实际send完成后归还，以及不新增跨请求状态等原则没有冲突；本次问题在上述具体实现与验收细节。

## 检查与未执行项

本轮只做源码/文档对照、CodeGraph影响面、保存结果的三位小数汇总及文档完整性检查。没有连接正式数据库、读取Lake、调用完整calculate、创建真实Control、执行pytest/API/浏览器或改业务代码/配置。

三位精度条款已按明确指令同步原方案/LLD。四项问题及建议留作review，未把建议6000或未确认的实现伪代码写成已批准规则。原来源证据与旧失败记录保持原样。
