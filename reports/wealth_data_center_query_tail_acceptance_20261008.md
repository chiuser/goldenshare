# 公告查询尾部自动调整验收（2026-10-08）

依据用户最新指令、产品方案最新补充、技术方案§18和LLD§28：结束日期超过本地公告最新日时，正常展示已有公告并说明实际截止日。本轮开发完成，修复按用户指令纳入本次提交，尚未部署；不改下载日期规则，不触发DG同步。

代码落点：Foundation DirectSource.latest_date及原请求/实际范围转换；Ops SourcePreparation.query第一unit冻结实际截止日；Biz QueryResultDto/AnnouncementQueryService产生effectiveEndDate和信息文案；Wealth QueryResult/QueryPanel消费普通提示。对应修改tests/test_announcement_direct_query.py、tests/web/test_wealth_data_center_api.py、QueryPanel/useAnnouncementQuery样本，以及既有真实浏览器测试和脚本。产品/技术方案/LLD已同步。

- 原始conditions保留用户意图，实际截止日保存在现有JSON，不新增schema、数据库、索引、配置或依赖；effectiveEndDate仅作为查询结果输出，不能由用户请求指定。
- 最新合法零行分区也是已同步日；只缩短尾部，不扩大开始日。整个所选区间晚于最新日则empty/0条并提示更新日期。
- 有效区间中间或开头缺日、坏文件仍error/数量未知；范围外坏文件不阻断完整历史。公告独有候选、下载状态筛选、分页和来源版本均使用固定实际范围。刷新新建query重新确认截止日，既有分页不受新增日期影响。
- 下载预览继续验证显式全范围；新增反例证明查询尾部可以调整，但相同日期的下载预览仍因缺日失败，不悄悄缩小下载任务。

验证：

1. 相关前端70项、typecheck、build通过。全量默认并发两次分别在MarketOverviewPage异步resolver准备上失败；该文件单独31项通过，使用`npm --prefix wealth run test -- --maxWorkers=2`复核后158文件/1138项全通过。未修改市场总览或测试配置；build仅有既有bundle体积提示。
2. `PYTHONPATH=tests:. .venv/bin/python -m pytest -q tests/web/test_wealth_data_center_api.py tests/test_announcement_direct_query.py tests/test_announcement_catalog.py tests/architecture/test_subsystem_dependency_matrix.py tests/web/test_wealth_data_center_downloads.py`：114项通过。补入范围外坏文件/下载不缩短/禁止传effectiveEndDate后，最终查询与真实API两文件61项通过。第一次新增日期测试因测试helper重复endDate参数失败，已修正测试helper并重跑；未影响正式数据。
3. `ANNOUNCEMENT_QUERY_BROWSER=1 PYTHONPATH=tests:tests/web:. .venv/bin/python -m pytest -q tests/test_announcement_query_browser.py`：1项通过。一次性PG/临时Parquet、真实Biz路由和构建后的页面，非mock公告API；截图显示选择10-08仍展示2条历史公告和截至10-07的蓝色信息提示。小写候选、鼠标/键盘选择、改日期保留股票、刷新保留原始结束日、开头缺日反例通过。pageerror/console error和data-center HTTP错误均0，PDF请求0，serverStopped=true。见[浏览器证据](wealth_data_center_query_tail_browser_20261008/browser-evidence.json)、[API证据](wealth_data_center_query_tail_browser_20261008/api-evidence.json)及[页面截图](wealth_data_center_query_tail_browser_20261008/tail-adjusted-query.png)。
4. 正式Raw只读核查截图中的锦浪科技300763.SZ：请求2026-09-09—10-08，最新有效分区10-07，29个日期文件、6条匹配公告，1.849秒，SQL最长0.162秒，FD峰值29。没有PG/Raw/PDF写入或源站请求。这是DirectSource及名称服务核查，不宣称正式HTTP全过程耗时。见[只读证据](wealth_data_center_query_tail_readonly_20261008.json)。
5. docs integrity、diff check、compileall通过。CodeGraph explore/impact覆盖QueryResultDto、AnnouncementQueryService、SourcePreparation及范围转换；动态路由装配、JSONB意图匹配和TS消费者由当前源码和真实API补核。sync/status已更新，依赖矩阵不变，无待拍板的跨层边界。

本轮测试启动的Uvicorn、Chromium和一次性PG均已关闭；没有启动、重启或关闭用户自己的Web/DG进程。没有安装软件。前端构建已更新，本机运行中的无reload后端需由用户重启后生效；新旧API和页面应一起使用，随后刷新页面创建新query。DG每日完整性和数据同步仍独立验证。
