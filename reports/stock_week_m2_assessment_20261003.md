# 股票周线 M2 开发验收

2026-10-07纠偏说明：本报告保留历史结论；搬运/审计中间数据文件已按管理员要求清理，不再是正式检查或调度依赖。现行口径为 bootstrap 完整对账一次即结束、日常只检查当前新增周期。详见[清理记录](stock_period_reports_cleanup_20261003.md#2026-10-07运行依赖纠偏及清理)。

日期：2026-10-03。M0/M1 已提交 `114a15c6`，未推送。本轮完成 M2 capture 实现和隔离验收，M2 修改保留工作区。依据[原方案](../lake_console/docs/design/dagster-stock-weekly-alternate-source-raw-backfill-plan-v1.md)、[LLD §20–21](../lake_console/docs/design/dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md)、DG 接入模板 §7A 及性能治理规范。

## 实现与硬口径对账

| 改动（相对 orchestrator） | 实现／验证 |
|---|---|
| `src/orchestrator/defs/prod_db/stock_weekly.py` | 固定两表、显式业务投影、numeric 文本、源日期自然年半开窗口；单unit readonly repeatable-read快照，count与named cursor同连接，fetchmany≤10000、unit≤30000、SQL≤30秒／unit≤45秒；watchdog取消阻塞查询，异常rollback |
| `src/orchestrator/defs/stock_weekly_source.py` | 备用一代码年度窗口、显式11列、最多54行；spawn子进程监督，20秒截止及取消后终止并确认退出；成功空与零列／失败区分；token与源异常原文不进入receipt或日志 |
| `src/orchestrator/defs/bootstrap/stock_weekly_capture.py` | 受控根、路径／symlink拒绝、plan/unit/schema身份及外部文件hash；OS单writer锁；有界DataFrame→显式CAST/COPY，Decimal无损校验，Parquet读回双向EXCEPT ALL；chunk hash、atomic JSON/fsync、receipt先封存再checkpoint；阶段请求ledger在调用前持久化 |
| `src/orchestrator/defs/bootstrap/stock_weekly_history.py` | 按冻结unit捕获及续跑；完成单元不重拉，receipt缺checkpoint可恢复，未知或篡改证据拒绝；取消后不领取新unit；进度显示当前范围、完成量、百分比、更新时间，ETA暂无法估算 |
| `tests/test_stock_weekly_prod_source.py` | SQL禁止项、snapshot与批次、源计数差异、阶段剩余行数超限在fetch前拒绝、阻塞取消／rollback |
| `tests/test_stock_weekly_capture.py` | 精度／日期／代码／freq／NULL负例、跨chunk重复、hash篡改、外源manifest、路径／lock／文件／请求预算 |
| `tests/test_stock_weekly_source.py` | 真实隔离子进程超时／取消、成功空、错误脱敏、重试和重启后预算不重置 |
| `tests/test_stock_weekly_history.py`、`stock_weekly_capture_test_support.py` | 只读替身、完成单元取消／续跑／幂等、进度单调、实际进程exit17后恢复、外部输入篡改阻断 |

同时回写原方案、LLD和文档索引，新增本报告及测量JSON（历史中间文件已清理）。未改变现有API／CLI、shared resources、活跃资产、catalog、jobs或sensors；业务子系统依赖矩阵不变。预算沿用M1冻结合同，不新增env／数据库／页面配置项。

失败或取消的attempt目录保留。完成单元复用前重新校验Parquet物理schema、key、源范围、count、file hash及receipt hash；不存在通过删除坏文件或静默截断继续的方法。未完成单元在下一attempt重取，既有请求次数不归零。备用查空不能当作复权已补齐，capture成功也不能代替M3的历史expected-key覆盖对账。

## 测量与范围

样本JSON（历史中间文件已清理）使用M0真实只读源数据，在 `/private/tmp` 回放到实际M2 adapter/capture。PG网络连接替换为有界cursor replay；备用响应经过实际监督子进程。没有使用正式token、instance或正式Lake作为测试资源。

| 样本 | 源行／capture读回 | 批次及续跑 | 内存／限制 |
|---|---|---|---|
| 主源未复权 | 15346／15346 | 2chunk；再次执行源调用0 | DuckDB512MiB、2线程、2GiB spill上限 |
| 主源复权 | 15346／15346 | 2chunk；再次执行源调用0 | 同上，21列Decimal合同 |
| 备用周线 | 51／51 | 1受监督请求；源日期保持原样 | 年窗口≤54行 |
| 合成容量（含非周五源日期） | 30000／30000 | 3chunk、4次fetchmany含终空批 | 累计进程峰值RSS305.547MiB；没有发生spill |

每个chunk的值差集为零；坏精度、重复键、超限、源count不符均拒绝，不封存完成receipt。耗时只含离线回放和本机capture，不含生产数据库／Tushare传输，不能据此提供正式同步ETA。RSS是测试进程累计峰值，DuckDB内存额度不是整进程硬上限；未证明强制spill场景或全历史正式写入性能。

## 验证

在 orchestrator 现有 `.venv` 中执行：

```bash
.venv/bin/python -B -m pytest -q tests/test_stock_weekly_contract.py tests/test_stock_weekly_planner.py tests/test_stock_weekly_prod_source.py tests/test_stock_weekly_capture.py tests/test_stock_weekly_source.py tests/test_stock_weekly_history.py tests/test_etf_mins_prod_db.py tests/test_index_mins_prod_db.py
.venv/bin/python -B tests/stock_suspend_confirmed_test_runner.py --scope regression --suite test_duckdb_connection.py
```

- 定向及相邻回归：87 passed，4条既有Pydantic警告。
- DuckDB OS隔离回归：三个batch分别6、8、13项，合计27项通过；没有修改隔离启动器或放宽权限。
- 本轮9个Python文件默认Ruff检查通过，全项目致命错误基线通过；文档完整性和diff检查通过。

最初普通pytest收集受保护的DuckDB suite失败，随后改用既有OS隔离启动器并通过，没有绕过fixture。测试中实际exit17退出后，已封存unit保留、锁释放，续跑只捕获剩余unit。

CodeGraph explore核验现有Prod readonly resource、Tushare调用和DuckDB连接；impact审计 `connect_readonly_transaction`。新增实现只追加消费者，不修改共享helper；开发后 `codegraph sync/status` 正常。新入口尚未接入正式定义；其impact未显示生产调用方，另以当前imports及catalog确认没有活跃消费者，不能把该结果当正式运行验收。

## 后续边界

M2开发及隔离验收完成；生产网络transport、正式staging捕获与源修订的实际运行验收仍须在M5/M6批准范围完成。现有真实源行为依据M0证据，不把离线replay称为新一次在线源调用。后续M3开发年度候选构建、完整merge／audit、同文件系统原子提升和中断恢复；M4才注册正式定义。

本轮没有正式Lake／staging、Prod或Dagster instance写入，没有安装套件，没有提交M2或推送；其他任务文件保留。
