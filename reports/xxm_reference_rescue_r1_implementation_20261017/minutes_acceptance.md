# R1分钟线技术验收

2026-10-17。用户确认日线历史仍在下载，要求先验收60／90／120分钟。依据预测方案§30／31.1和代码级LLD§24／25.1；本报告只覆盖分钟范围，不宣称日线或完整四周期页面通过。页面由用户验收。

## 结果

| 周期 | 完整源根数 | 冷20次最大HTTP | 真暖20次最大HTTP | 模型包络最大 |
| --- | ---: | ---: | ---: | ---: |
| 60分钟 | 17272 | 1.998秒 | 0.477秒 | 25.177ms |
| 90分钟 | 12954 | 2.145秒 | 0.833秒 | 34.861ms |
| 120分钟 | 8636 | 1.977秒 | 0.537秒 | 16.508ms |

三周期完整加载至2026-10-16 15:00；M0冻结重叠17260／12945／8630根逐值相同，无修订。每一冷轮确实完整读源，每一暖轮无完整重读；仍检查源签名，不以跳校验换速度。冷热各20轮预测及配对识别、3次LATEST和3组识别／预测并发共249业务请求全部通过。LATEST均READY，并发返回的computedThrough及sourceInputId配对相同。

实际TS客户端／调度器完成3个选中分钟周期×单／双标签×冷暖共12组、216业务请求，包含三行分钟预测、当前分钟图与指标、日线及15／30／60／90／120分钟九转、识别层。54份完整预测与同批独立LATEST逐字段相同，严格adapter及图层事实消费通过。双标签冷轮每周期行情／指标各只完整读取一次，暖轮无完整重读；无业务日切换、串周期或契约拒绝。

另外13个既有分钟历史场景，每例空缓存、正式源和真实路由共26请求通过；完整数学域／display和明确状态与已保存的`api_02`冻结语义一致，包括7/10等待、7/13再钝化、12/15—16 R1结果域及2023/9/21真正取消。该对照证明正式输入接线和既有语义一致，不是新增原软件真值。

当前主验收三批次共491业务请求（不含管理探针和旧轮次），均200且≤4秒。最大HTTP3.291秒、记录的模型包络最大34.861ms；预测预算记录最大12666B（沿用原工具JSON编码计量），≤32KiB；混合轮次缓存最大48910335B／6项，≤64MiB／16项。缓存计数覆盖冷暖配对、历史场景和每个混合轮次，LATEST-only阶段未单独记录缓存计数，产品缓存限制始终生效，不把混合轮次最大值冒称为全部瞬时峰值。混合预测HTTP最大2.081秒。含调度队列的整组冷加载8.83—13.05秒、暖加载4.33—9.62秒，4秒指单次HTTP，不是整组完成时间。

## 原始证据与保留的旧轮次

- [机器汇总](minutes_acceptance_summary.json)：范围、数量、逐周期最大值及未验项。
- [严格预算](minutes_budget_02/result.json)、[执行身份](minutes_budget_02/run.json)：20真冷／20真暖、LATEST、并发、冻结重叠及阶段计时。
- [实际客户端混合](minutes_page_mix_01/page-mix.json)、[服务关闭记录](minutes_page_mix_01/server.json)：12组216请求、逐请求路径／周期／字节／时长，以及54份原响应、图层与view-model原件。
- [历史场景](minutes_replay_budget_02/result.json)：13组26请求及每组原始识别／预测响应。
- [补充核对](minutes_evidence_checks.json)：13份正式识别事件语义与冻结原件相同，2023/9/21 10:30的BOTTOM CANCEL字面核对，以及旧暖首轮读源、新暖首轮不读源的实际反例；[源码身份](minutes_source_code_manifest.json)保存工具、产品与消费者哈希。
- `minutes_budget_01`的时间预算通过，但旧工具每个暖组首轮又冷加载，不能算20次纯暖；原件保留，严格分组以02为准。修正只删除验收工具暖组清缓存，并新增冷／暖是否完整读源的断言，产品不变。
- `minutes_replay_budget_01/run.json`保留验收工具会话注入AttributeError。FastAPI需yield会话依赖，不能直接返回contextmanager；修正工具、增加进入／关闭回归后，在新02目录重验。该轮在首个有效计时请求前退出，不计为产品超时。

## 只读范围与真实性

连接沿用应用配置的PostgreSQL，通过`get_db_session`并执行`SET TRANSACTION READ ONLY`；分钟预算白名单为`core_serving.trade_calendar`的日期／is_open／pretrade_date、SSE过滤与有限未来日历。混合附带的日线九转只读取`000001.SH`近期300条及分页探测行：`core_serving.index_factor_pro`代码／日期作锚，左联`core_serving.index_nineturn_daily`收盘／计数／标签／版本；未请求日线预测或其完整指标历史。不改账号、配置或权限，不打印连接密钥。

正式分钟源为`/Volumes/datasource/data_lake`下指数Gold行情、技术指标和九转。XXM读取`000001.SH`三个分钟周期完整已发布历史，原20000行／5000文件／1000根批次、文件安全／schema／键集合／重复／有限值／端点连续性、源签名及全部资源预算保持。混合图表和分钟九转依原接口各500条有界分页；不裁剪XXM完整历史。

原鉴权依赖保留，当前配置为`QUOTE_API_AUTH_REQUIRED=false`；未读取其他进程密钥，未声称已测试开启登录的部署。预算与历史场景为FastAPI真实路由、查询、DTO和正式只读源的隔离TestClient；混合为自动关闭的隔离uvicorn HTTP服务加现有esbuild编译的实际TS客户端，每标签独立调度器。没有mock读取器、浏览器自动操作、产品服务重启、依赖安装、数据库／Lake写入或DG事件。

## 工具、测试与复现

本轮只修改验收工具`bottom_history_acceptance.py`／`reference_rescue_acceptance.py`、`xxm_page_request_audit.py`／`.mjs`及新增`test_xxm_acceptance_scope.py`；同步四份原方案／LLD／研究文档、主题README和本报告。产品算法、API合同、TS业务客户端、读取器、运行预算及依赖矩阵没有本轮改动。

新增`--periods`仅选择验收用例，不传仍四周期；重复、空、未知或在冻结/API模式缩小范围会拒绝。13项隔离回归通过，覆盖这些边界和只读会话进入／关闭；Node语法、文档完整性及本轮范围diff格式检查通过。CodeGraph explore已核验验收入口和加载链，完成后sync／status正常（4162文件，无待同步项），整体产品CodeGraph影响面沿用前轮记录，无新增架构方向。

仅使用现有环境，从仓库根运行，每次必须换新输出目录：

```bash
.venv/bin/python -B -m scripts.research.index_market.xxm.bottom_history_acceptance --mode budget --formal-source --source reports/xxm_source_audit_20261013_213852 --output reports/<新分钟预算目录> --periods m60 m90 m120
.venv/bin/python -B -m scripts.research.index_market.xxm_page_request_audit --output reports/<新分钟混合目录> --periods m60 m90 m120
.venv/bin/python -B -m scripts.research.index_market.xxm.bottom_history_acceptance --mode replay-budget --formal-source --source reports/xxm_source_audit_20261013_213852 --output reports/<新历史补验目录> --periods m60 m90 m120
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -B -m pytest -q -p no:cacheprovider scripts/research/index_market/tests/test_xxm_acceptance_scope.py
node --check scripts/research/index_market/xxm_page_request_audit.mjs
```

## 尚未完成

日线及原四周期完整整页门禁待用户通知下载完成后恢复，先验证日期连续性与必需指标完整，再验预算。Figma文字同步及工作树研究原型清退仍按原交付清单保留；页面由用户验收。本轮不代表R1整体交付或原软件唯一公式已确认，没有提交、推送或部署。
