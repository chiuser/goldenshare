# 公告首字母搜索与缺日隔离修复验收（2026-10-08）

依据：用户本轮报告、技术方案§16/§17和网页LLD§22.9/§27。目标是恢复小写首字母自动候选、隔离最新日期缺失与历史查询。本次提交仅包含本功能修复；其它任务脏文件保留，尚未部署。

## 根因、改动及范围

1. 共享useStockSearchController将输入转为大写，CompanySearch却把原始小写回传父状态；props同步误判外部改动，resetInput取消防抖。原测试只使用已经填好的PAYH及mock onText，没有覆盖真实父状态逐键输入。现在控制器返回已规范化keyword，公告组件回传同一值，不另做一套转换/状态机。
2. companies原来先等待整个日期区间公告查询准备；默认区间包含缺失的10-08时，主表中已有股票也无法选择。现在先用已有stock_basic/namechange查询常用候选并复核来源版本，无需公告日分区或查询控制写入。只有未匹配时才沿用完整区间准备，补足公告独有代码/名称；未知公告候选的缺日仍明确报错，未伪造空结果。快速结果hasMore只对应实际名称snapshot检索，不宣称全部公告历史名称已准备。
3. useAnnouncementQuery原来在改变任何日期时清空显式选择。现在日期更新保留完整代码，文本编辑/重置仍清空选择；未选候选观察仍随日期改变取消。列表只验证所请求区间，默认失败查询保持自身终态，独立历史query正常创建/读取。

代码为CompanySearch、useStockSearchController、useAnnouncementQuery、CompanySource和AnnouncementQueryService；测试补受控小写输入、日期保留选择、真实路由缺日后历史查询及公告独有候选负例，另提供自动关闭的浏览器测试/脚本。API字段、错误码、默认日期、配置、Figma、下载/DG及依赖矩阵不变；不建立新数据库或持久公告副本。

## 验证证据

- 修复前新增前端两例真实失败：小写payh零候选请求；日期改变后selected消失。真实路由新增例失败于主表股票候选为空。先复现再改代码。
- 前端相关68项通过；typecheck/build通过。全量首次1135通过/1项双动量导航超时，该文件独立15项通过，随后全量158文件/1136项全部通过。没有改双动量源码或测试。构建只有现有bundle大小提示。
- `PYTHONPATH=tests:. .venv/bin/python -m pytest -q tests/web/test_wealth_data_center_api.py tests/test_announcement_catalog.py tests/test_announcement_direct_query.py tests/architecture/test_subsystem_dependency_matrix.py`：67项通过。真实API测试只使用临时PG/Parquet及测试认证，覆盖缺日默认error→小写主表候选→新历史query成功、原失败终态保持；公告独有155162.SH仍202准备，正确区间可查、缺日区间仍报错。
- `ANNOUNCEMENT_QUERY_BROWSER=1 PYTHONPATH=tests:tests/web:. .venv/bin/python -m pytest -q tests/test_announcement_query_browser.py`：1项通过。使用已安装Playwright/Chromium、临时PG/Parquet和随机端口真实路由/页面；payh逐键输入自动弹框，鼠标选择、修改日期保留代码，历史六列返回2条；再次键盘选择正常，主动包含缺失10-08仍报错。pageerror/console error均0，公告API无HTTP错误，PDF请求0。证据：[浏览器](wealth_data_center_query_fix_browser_20261008/browser-evidence.json)、[真实路由请求](wealth_data_center_query_fix_browser_20261008/api-evidence.json)、[候选截图](wealth_data_center_query_fix_browser_20261008/lowercase-candidates.png)、[历史列表截图](wealth_data_center_query_fix_browser_20261008/historical-query.png)。初次脚本定位combobox同时命中select，已改为公司输入框精确名称后重跑。
- [正式Raw只读证据](wealth_data_center_query_fix_readonly_20261008.json)：Biz候选服务未提供PG controls，wllx仍返回蔚蓝锂芯002245.SZ；明确确认10-08缺失。直接DuckDB读取5-04—10-05共155日，股票匹配36条，总用时1.791秒、最大SQL0.158秒、公告FD峰值32。只读名称及历史文件，无正式PG、Raw、PDF写入/源站HTTP。该点测不冒充全部API或全历史性能验收。
- docs integrity、compileall、git diff check通过。CodeGraph query/impact覆盖CompanySearch、AnnouncementQueryService及共享控制器；源码另核对StockSearch、TradingAssistantStockPicker、API/DTO与PG/Raw调用边界，开发后sync/status索引当前。静态图不能单独证明动态注入和SQL，因此另外执行真实路由/浏览器/Raw验证。

## 服务与后续

临时Web和浏览器在finally正常关闭，报告serverStopped=true；PG夹具finally执行pg_ctl stop并清理临时实例。未启动正式Web8000或DG，没有遗留本轮后台服务，没有安装/升级依赖或修改本机env。

修复已完成，按用户指令纳入本次提交，部署review待执行。今日缺日的同步问题仍归DG独立流程；包含缺日的公告列表依然如实提示，已落地的历史区间可以查询。
