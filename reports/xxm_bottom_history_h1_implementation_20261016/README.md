# B组 H1—S2—E1 内核升级交付

2026-10-16。依据用户确认的[LLD §17](../../wealth/docs/pages/index-detail/index-detail-xxm-implementation-and-low-level-design-v0.1.md#xxm-bottom-history-code-lld)，**唯一h1内核及全链消费者已完成，技术验收通过，页面待用户验收；未提交、推送或部署。** 当前分支dev-interface，未建分支／worktree。

原三处日线漏报——2024/7/23、8/5、8/22——已在正式新内核及真实路由的冻结数据验收中补齐；8/5、8/14两处120分钟映射亦对应。新增95条中5条有原软件映射，其余90条没有独立真值；这次交付不宣称完全还原原软件。

## 目标、范围与边界

仅上证000001.SH的日线、60／90／120分钟。沿用原普通检测及TOP历史，在同一内核增加独立底部历史；冻结原负段已知最低收盘及DIF参照，登记离段后严格破价仅触发一次。DIF参照突破、新底部DULL／STRUCTURE优先结束记录；无固定TTL。新Spec `xxm-direction-v0.1-h1`，hash `b2ebada1a7ef0f013cf2b9a447a6a9fee8c73ac660c3fee41a9be13e3ca290e5`。

快照原子校验恢复；查询账本保留原结构身份、隐藏未来离段／结束信息；严格DTO和TS关联、窗口及新版本合同同步。日线和分钟图共用原hook／primitive，新增底部详情及绿色“消失”，marker仍在DIF位置；原视觉不改。技术面预测只更新检测器身份和克隆底部状态，数学、v0.2合同及全文文案保持。

A组7/10同负柱段提前DULL／漏结构消失、重新激活和顶部疑报继续待后续评审。附加DIF门槛、精确零柱／OHLC依赖及软件寿命仍未证明。页面未由代理操作或代验。

## 文件与落点

| 范围 | 文件／函数 | 解决的问题 |
| --- | --- | --- |
| 内核 | services/.../index_detail_xxm/types.py、spec.py、calculator.py；step、_advance_bottom_history、_start_bottom_history、snapshot／restore | 原底部历史无记录，跨柱色后三漏；新身份隔离旧缓存；无研究工厂／双引擎 |
| 查询／DTO | queries/.../index_detail_xxm/query_service.py；SeriesEntry、_load_series、_response及两个底部helper；schemas/.../index_detail_xxm.py | 增量发布隔离、过去投影、窗口外原结构及双向关联；缺字段／错方向／悬空拒绝 |
| Wealth | xxm/types.ts、adapter.ts、XxmLayerUi.tsx、fixture及测试 | 新底部合同可被两个图表消费，详情“底部结构消失”、图上“消失”，低点／离段／结束可核对 |
| 测试 | calculator、forecast、识别API、预测API及Wealth adapter／hook测试 | 边界／优先级、普通和TOP不变、原子恢复、历史时点、预测与合同反例 |
| 验收 | xxm/acceptance.py、新bottom_history_acceptance.py、原xxm_page_request_audit.py/.mjs、研究README | 正式唯一内核、固定来源SHA和新差异；真实调度、统一上下文与实际chart adapter |
| 原方案 | V0.1、识别LLD、预测方案、研究记录 | 当前状态及代码／测试／验收对账，原研究记录保留，V0.1核心表仍在文末 |

详细现有文件清单见[范围与保护核对](scope_check.json)；新增runner及四份原文档列入最终manifest。未修改source.py、shared_loads.py、runtime.py、Reader、路由／App装配、预测数学／schema／adapter、调度器、Workspace／primitive／CSS。Biz→Foundation及Wealth→HTTP不变，无新配置、SQL、迁移或依赖。无DG调用或DB／Lake写入。

## 验证结果

| 门禁 | 成绩 | 证据 |
| --- | --- | --- |
| T01—T12 后端 | 209项通过；架构边界16项通过 | [后端日志](python-tests.log)、[汇总](validation_summary.json) |
| T13—T15 前端 | 全量1179项／165文件通过，类型和构建通过 | [前端日志](wealth-tests.log)、[类型](typecheck.log)、[构建](build.log) |
| 完整冻结 | 39747根普通／TOP点序列、事件、TOP历史保持（身份按结构锚点映射核对）；95条新事件、328记录与B1逐项相同；75个前缀／恢复 | [冻结结果](../xxm_bottom_history_h1_frozen_20261016_02/frozen_summary.json) |
| 预测 | 356组完整数学／日期／范围／display一致；18个既有日线校准失败保护保持；冻结模型最大83.290ms | [四周期完整结果](../xxm_bottom_history_h1_frozen_20261016_02/) |
| 实际路由fixture | 五处正观察＋四周期末端，共18份识别／预测响应；另16次401／403拒绝 | [API结果](../xxm_bottom_history_h1_api_20261016_02/result.json) |
| 正式冷暖 | 每周期20冷＋20暖，160轮预测＋160配对识别，另4次LATEST；HTTP最大2.622465s，模型保守包络94.498ms | [完整记录](../xxm_bottom_history_h1_budget_20261016_01/budget_records.json) |
| 整页／双标签 | 16组306业务请求全200，HTTP最大2.823452s；24份新识别响应＋24份真实adapter明细，96份预测；模型包络17.763ms；缓存最大42478077字节／8项 | [全部混合样本](../xxm_bottom_history_h1_page_20261016_02/page-mix.json) |

混合冷读取每周期价格／指标各一次（2次完整读），暖为0；4秒计单次HTTP和后端原deadline，不把整页含前端排队的耗时称为4秒内。模型计时为未来日历读取后到原build结束的保守包络，含缓存与序列化，并非修改了生产200ms门禁。冷指新应用缓存，未清OS／DB buffer。来源槽位2、1000根批次、2000根响应、1MiB／32KiB、64MiB／16项均保持。

## 正式只读范围与来源

通过正常应用get_db_session，连接152.136.106.251:5432／goldenshare；每会话先SET TRANSACTION READ ONLY，不保存连接字符串／密钥。识别与预测只读core_serving.trade_calendar（exchange、trade_date、is_open、pretrade_date，SSE，历史1990起及原未来20端点窗口）和index_factor_pro（ts_code、trade_date、close、macd_dif_bfq、macd_dea_bfq、macd_bfq，仅000001.SH，原1000分页及总行数上限）。正式Lake根/Volumes/datasource/data_lake，只读gold指数分钟价格／技术指标及九转。

混合原页面路由另外只读core_serving.index_basic的身份五字段、index_factor_pro的KLINE_COLUMNS显式OHLC／成交／MA／BOLL／MACD／KDJ投影、index_daily_serving的最新日期（MA暖机计数仍取index_factor_pro），以及index_nineturn_daily的close／up_count／down_count／nine_up_turn／nine_down_turn／formula_version；对象仍上证，K线300、分钟500、九转300／500。调用原页面query，不新增SQL。

正式源当前为日线914根、60分17268根、90分12951根、120分8634根，截至2026/10/15；冻结39747根重叠区全部逐值一致。新行允许追加，旧CSV未修改。LATEST四周期均READY，业务日期2026/10/15来自当前统一20点逻辑。保留正常require_quote_access；本机quoteAuthRequired=false，无浏览器令牌或他进程密钥，无账号／权限写入。fixture注入测试身份独立标明，不能冒充已验证登录保护服务；401／403另有明确反例。

## 失败尝试、限制及下一步

api_01误用验收脚本路由路径，page_01漏传客户端必填startDate，均保留原失败记录，不算通过；修正脚本后分别以新_02目录完整重跑。混合识别窗口改为1990-01-01起且limit仍500，以覆盖实际图表窗口；业务日期始终从真实context取，不再硬编码历史endDate。未改产品参数或放宽校验。

旧130份研究／预检／来源SHA全部保持；原普通TOP基线manifest未改；日期案例只存在测试／报告，不在生产分支。静态文档和边界核对见最终validation／manifest。现有构建大chunk提示、httpx测试弃用提示不影响本次通过，未为此扩改。

下一步由用户核看日线及60／90／120分钟：尤其2024/7/23、8/5、8/22日线的绿色“消失”及其原结构／低点详情。页面通过前不标为用户验收完成。A组及软件公式边界另开评审，不能由本次B组成绩替代。
