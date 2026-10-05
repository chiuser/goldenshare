# 月线历史事件补录执行清单

2026-10-05，Asia/Shanghai。管理员本轮“提交吧，然后进行事件补录”授权本阶段；先提交全量文件证据3892ad31，未推送。

工作目录 `/Users/congming/github/goldenshare/lake_console/orchestrator`；正式 `DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home`，复用现有本机PostgreSQL，禁止自动建表/升级。正式Lake只读 `/Volumes/datasource/data_lake`；staging只读封存证明及独占 `stock_monthly_event_writer.lock`，不写Raw/候选业务文件。

Dry-run：两源34年度集合校验/742SQL/4.838秒，402文件1414335行通过；正式月键0，物化0，checks0，历史失败/阻塞0。冻结缺项402物化+1206blocking checks和201月键，源范围2010-01至2026-09。

冻结事件计划：`stock_month_m10e_events_20261005_plan.json`，外部文件SHA256 `de2de5cf099b5fc353707dddde026ca98f6f124ec35dc89321b4259e803fee6a`；逻辑plan_hash `a06384c99aa49580e7c093d0852cf3b9ed3a641dfed5d77e49d126b26ab90550`。完整逐条命令在同目录 `stock_month_m10e_events_commands_20261005.txt`。

先执行命令1–3，注册2010-01/2020-02/2026-05三个样本月键；命令4补录两源六个完整资产分区24事件。仅只读复核六个样本文件及绑定checks，全部ready才执行命令5–7补齐剩余198月键。其后17批，每批最多25资产分区/100事件；已完成样本按实际event跳过。最后命令做34年度物理集合、latest物化/check索引与正文集合审计，少量实际文件readiness。

影响：新增runless事件和动态月键；不触发job/sensor，不安装依赖，不修改Prod或Tushare，不启用调度。取消/退出保留已提交事件；同一冻结计划和SHA重放从数据库缺项续跑，checkpoint仅作进度。事件不可数据库删除回滚；若发现错误或外部漂移，停止并单列更正方案，不补绿掩盖失败。M9正式更新验收及M10.F启用不在本阶段。

## 执行结果

- 样本：注册3月键，6物化+18检查，六个文件及target绑定全部通过。
- 全量：追加198月键，17批共1584事件；按实际event跳过24个样本事件。单批最多100事件，21条全量/最终audit命令计时100.106秒。
- 最终：201月键、402物化、1206检查，缺项/阻塞/失败0。每源201物化，每种check每源201。
- 文件：34年度集合/742SQL/4.255秒，402文件和1414335行完全匹配冻结hash，无Raw变化。2020-02仅28日，排除7364条29日版本，历史NULL不清洗。
- 独立聚合事件审计：34物化页+34检查索引+34正文页=102查询，返回2814记录（含重复表示同一check的索引和正文）；未逐check深扫。
- 代表样本：2010-01、2020-02、2026-05、2026-09两源，八个物理/check样本和现行monthly_period_status入口均ready。
- 月线sensor无持久化启用状态，definition默认STOPPED。没有Prod/Tushare请求、job执行、Raw写入、安装或推送。正式RSS/spill未测。

代码与隔离验收：新增stock_monthly_events.py/CLI、test_stock_monthly_events.py及受保护启动器两条精确源码路径；三份原方案/LLD同步，不改变共享合同/定义或src依赖矩阵。27个事件测试+24个历史入口测试共51项；受保护静态113、治理12、离线定义加载、Ruff、文档完整性及CodeGraph同步通过。实际隔离进程第5事件提交后退出，续跑追加11、再重放0，证明checkpoint落后不重复；正式执行没有故意取消。

M10.E文件/事件阶段完成。事件代码与本轮结果尚未提交；M10.F更新验收/启用和M9周线延期验收另行推进。

证据：[初始dry-run](stock_month_m10e_events_20261005_dryrun.json)、[冻结计划](stock_month_m10e_events_20261005_plan.json)、[样本审计](stock_month_m10e_events_sample_audit_20261005.json)、[全量逐命令日志](stock_month_m10e_events_full_execution_20261005.json)、[最终文件/事件集合](stock_month_m10e_events_final_audit_20261005.json)、[独立消费者与聚合计数](stock_month_m10e_events_consumer_audit_20261005.json)。
