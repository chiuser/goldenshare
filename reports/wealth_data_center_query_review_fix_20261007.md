# 公告查询页面 review 修正验收

2026-10-07，按用户“按照你的建议修正”执行，依据[LLD §21](../wealth/docs/pages/data-center/data-center-announcements-low-level-design-v1.md)。改动范围为缺日提示、已封存失败查询的读取语义与页面按钮状态；未改默认日期、来源完整性、下载控制或DG同步。

已封存失败查询使用现有DTO的pageState=error、HTTP200，total=NULL、items为空、下载状态不可核验；临时服务读取不可用仍503，未知query404、过期409保留。日期来自被核验的分区，名称快照缺失不误报公告日期。查询/重置/刷新只在主动POST期间置灰，分页保留GET互斥。

主要改动文件：`src/ops/runtime/announcement_archive/catalog_builder.py`、`src/biz/services/wealth/data_center/{errors,query_service}.py`、`wealth/src/features/data-center/model/useAnnouncementQuery.ts`及`ui/QueryPanel.tsx`；回归位于`tests/test_announcement_catalog.py`、`tests/web/test_wealth_data_center_api.py`、`ui/QueryPanel.test.tsx`、`model/useObserver.test.tsx`。产品方案、implementation design、LLD及异常码登记同步更新。

| 证据 | 结果 |
| --- | --- |
| 后端查询/真实路由/下载回归 | 93项通过；增加中间缺日反例后真实路由20项通过 |
| 前端 | 157文件、1130项通过；typecheck/build通过 |
| 分层与文档 | 依赖矩阵4项、docs integrity、diff检查通过 |
| 真实浏览器缺日 | 首次查询缺2026-10-07；GET返回终态后8秒无新增查询GET，查询按钮disabled属性变化0次 |
| 手动恢复 | 仅在临时Raw补齐零行缺日，点击重新读取创建新queryId；67条公告、首页50条、末页17条 |
| 空态与布局 | 完整零行日期显示empty；1460/1366宽无面板溢出，console/page/API错误0 |
| 隔离边界 | 实际API/Biz/DAO/runtime，临时Parquet/SQLite；仅隔离身份、磁盘检查与行情装饰，GET延迟1500ms只影响传输，不伪造公告响应；正式写入0、源站请求0、未启动下载 |

[浏览器证据](wealth_data_center_query_review_fix_20261007/browser-evidence.json)及[API请求记录](wealth_data_center_query_review_fix_20261007/api-evidence.json)使用隔离数据，不能作为正式DG补齐的证明。截图：[缺日提示](wealth_data_center_query_review_fix_20261007/missing-day.png)、[恢复后末页](wealth_data_center_query_review_fix_20261007/recovered-list.png)。

CodeGraph explore/impact审计查询服务、构建器及API/前端/测试消费者，sync/status完成；共用错误适配的下载路径通过回归。无依赖方向、配置或数据库结构改变，工作区其他修改未纳入本次。升级需同时部署后端与Wealth构建；正式缺日等待DG同步，用户可先查询完整历史范围。
