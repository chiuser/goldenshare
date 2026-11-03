# 股票日线接入步骤3：实现及停止记录

2026-10-31，dev-interface，开工提交e760c9d3d。依据专项方案、LLD第03～16.3节及管理员本轮授权；未自动提交、部署或实施D的P/R节点。

## 已落实的代码

| 要求 | 实现位置及实际证据 |
| --- | --- |
| 原非指标来源及实际日期不变 | stock_detail_query.py固定KLINE_COLUMNS；query service的prepare_kline_input按原context→security→K线顺序，严格索引字段、复制为不可变对象。受控prepare/Decimal不提前舍入、缺列失败及快照独立性小例通过。 |
| 显式接入十项结果，不读取旧指标 | stock_daily_kline_service.py先检查日期、数量、实例、参数、版本、字段及长度，再调用新mapper；hist只映射为macd，J映射为j。合法NULL、EMPTY/DELAYED、debug和10位输出格式小例通过；四个规定反例通过。 |
| 原API及page-init内部迁移 | 原kline路由改用Biz协议和原不可变请求；原Query参数AST一致；旧build_kline和_to_context_dto已删除，page-init复用抽取的build_page_context。Web实际合同检查尚未运行成功，不能称原API已验收。 |
| 数据库早释放、单worker/Control/计算 | App专用后台严格按LLD固定work及资源函数实施；数据库关闭后才能calculate，原D4代码不改。受控Session、SQL时限、部分初始化和清理失败小例通过，真实PG留在P01。 |
| 实际发送及错误引用 | 两个既有中间件只为目标GET路径直接ASGI转发；最外层发送阻塞时仍占名额。取消后等待worker、唯一归还、编码字节L±1、Pydantic错误不保留输入等小例通过。 |
| 启动及关闭 | App仅安装提供者，lifespan按原顺序进入新上下文；部分初始化/正常关闭/主错误保留小例通过。非目标路径选择原中间件分支。全局应用导入验证受阻，不能扩大为真实Web启动通过。 |
| 测试隔离和未改范围 | 已同步共享Web fixture，原kline测试显式新后端及worker独立SQLite Session；未安装依赖或读写正式DB/Lake。A/B生产实现、Foundation算法/SQL、前端等受保护源码指纹未变；旧通过函数体未改。 |

开工前使用CodeGraph explore核原路由、query service与调用方，并按完整路径补核源码；Context7核对SQLAlchemy只读连接/事件、FastAPI Response、Starlette转发及Pydantic输入诊断。没有放宽纯D4或Foundation依赖方向。原股票同名指数/研究入口未修改。

## 实际执行

只执行固定表前两组，未重跑A/B：

- business_and_app：7个函数通过，16个控制替身，无真实Control、DuckDB计算、正式行情或PG。
- web：首个test_original_limits_and_openapi在app_client的全局应用导入阶段报错；测试体尚未执行。其余6个Web函数和4个依赖函数未执行。
- pytest累计约4.29秒；每程序小于30秒。本步48个控制替身额度剩32，60秒额度剩约55.71秒；专项普通检查累计使用25个，72个额度剩47。

日志、JUnit、原执行表、逐组费用和错误分别保存在本目录；普通测试只通过record_property交付费用。Pytest的xunit2属性兼容提示和既有httpx弃用提示不作为测试失败，未因此修改依赖或扩大范围。

## 停止原因与上下文

导入链：tests/web/conftest.py的app_client → src.app.web.app → 总路由 → index_detail_xxm_forecast → forecast_query_service.py第10行 → 从forecast.py导入inactive_result。

实际forecast.py没有这个名称，产生ImportError。原本应先成功创建应用，再开始股票日线请求；现在应用导入提前失败，股票后端和TestClient均未创建。两个XXM文件与本轮开工提交完全相同，不属于本步修改；证据及SHA保存在blocker.json。

按LLD停止后续节点，没有修XXM、屏蔽路由、换掉整个应用或自动重跑。通过的App小例已断言关闭runtime和归还名额；失败Web节点由pytest退出临时Session/Engine夹具，JUnit没有teardown错误，两个pytest子进程均已结束。不存在本轮启动而尚在工作的行情计算或PG连接。

## 建议及未验证项

先由XXM对应任务修正其既有导入合同，再获准续本次失败的Web函数及其余10个未执行函数，保留7项通过证据及累计费用。不重跑A/B或本步通过函数。原API/OpenAPI、实际SQLite查询及旧kline/page-init保护检查仍未通过；PG、真实Lake/API和浏览器P/R未执行，不能宣布步骤3完成或可上线。

本轮只完成错误收尾文档和证据保存，不继续开发、执行测试、提交或部署。
