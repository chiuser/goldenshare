# 股票月线 M10.D 开发验收

2026-10-05，Asia/Shanghai。M10.C已提交 `ac063248`，未推送；M10.D开发与隔离验收完成，尚未提交。没有操作正式数据湖、正式Dagster instance或源下载任务，sensor默认STOPPED。

依据[月线LLD](../lake_console/docs/design/dagster-stock-monthly-raw-onboarding-low-level-design-v1.md)及数据集模板§7A，新增两套月线Raw assets、6个blocking checks、2个asset+checks jobs、1个每日19:30月线sensor；注册catalog、中文名、精确Decimal schema、paths、动态月份分区定义及typed config。不修改Prod、weekly执行链、前端或src依赖矩阵。

| 硬口径 | 实现、验收 |
|---|---|
| 完整自然月/2020年2月28例外、源值原样 | run_contracts/stock_monthly、paths、io；周末月末/28-29/原身份/NULL/Decimal正反例 |
| 手动/自动只用两个主源，不暴露代码过滤或覆盖 | StockMonthlyRawConfig、assets/stock_monthly、统一config builder；额外输入/overwrite/备用拒绝 |
| 每日19:30、先最早欠账、两个主源串行 | monthly sensor及pure update；当前月/queued/同日去重/异值/缺证明不提交，基线需物理文件+绑定checks |
| 每页立即保存，请求预算可恢复 | stock_monthly_point；最多6000×4页/每页3次、最多10000行；满页到cap拒绝、空尾页闭合、跨页重复拒绝，真实退出/取消后不重取成功页 |
| 整月日线只作门禁、无行情合成 | source_readiness/stock_monthly；31文件/320000键，SQL身份join及末日聚合；22交易日绑定全部4 checks，缺历史/错目标/非blocking/失败/planned拒绝 |
| 合法历史NULL与新源截至证明分开 | bootstrap/stock_monthly_delivery读年度封存audit/receipt控制hash/逐月checkpoint；新源proof逐页全字段读回+个股最后实际日线，Raw不改代码 |
| 原子提升/幂等/观测隔离 | 共享source-month锁、下载全局互斥、同卷os.replace、checkpoint；同值复用、异值修订、上游改变和并发拒绝；观测失败文件保留 |
| UI事实与定义一致 | catalog/name/schema/path/partition/标准metadata；实际临时job各3个分区checks全部通过，治理及静态清单同步 |

本轮月线及相邻周线回归242项，新D测试75项；受保护静态113项、资产治理12项通过。整个code location离线隔离 `dg check defs --no-check-yaml --use-active-venv`通过，禁止网络/正式路径及依赖下载。新文件和主要修改文件Ruff通过；共享configs.py的11条既有诊断与HEAD一致，未新增。全src/tests致命错误基线通过，CodeGraph explore/impact及根sync/status、文档完整性通过。

CodeGraph/当前代码影响面覆盖路径bootstrap消费者、监督传输、事件目标绑定、configs/run requests/cursor/run key、catalog、资产/check/job/sensor和治理测试。仅复用已核实无频度的DuckDB、监督请求传输和目标事件绑定；不抽取/改变周线频度合同或组装器。新增MonthlyUpdatePolicy预算、日期及clock口径进入执行身份；无env/数据库/运营开关。正式Raw布局为raw/tushare/stk_period_bar[_adj]_month/month=YYYY-MM/data.parquet，正式根和staging根沿现行路径。

复用2026-10-04已捕获源响应的全市场5571行/源，源页→捕获→候选→临时提升0.391/0.410秒；与原响应全字段双向差集0，重放不重取。Raw文件177072/311668字节。日线/身份/事件全部替身，数据只是性能和传输验收，不证明真实日线覆盖。缓存源各有10只股票end_date早于月末，与按个股日线末日门禁一致；没有因此宣称它们是缺口。

独立SQL生成压力样本31文件、310000日线键、10000期望代码，参考聚合0.064秒，控制JSON517866字节。累计进程RSS峰值357.813MiB，采样spill峰值0，未强制spill；DuckDB buffer预算不等同RSS上限。正常单月每源1请求，最坏12次/源，两源最多24次；网络超时部分最坏480秒加间隔/本地校验。所测耗时不含网络，不作为正式ETA。

性能脚本最初因DuckDB多占位符绑定顺序将22份临时键文件写入工作目录，已按路径内容确认归属并迁至/private/tmp/stock-month-m10d-misbound-fixtures；脚本改为只有输出路径占位符后通过。正式业务COPY语句仅一个输出参数，未受影响。缺psutil未安装，RSS用现有resource.getrusage；没有新增依赖。其他任务的脏文件和受保护runner精确只读路径保留。

下一步M10.E为正式bootstrap入口/库存刷新/磁盘和维护窗口预检/分阶段数据与事件执行；M10.F源真实更新和启用另列。M9周线正式源验收仍等待管理员确认可交付版本。正式执行未经本轮授权，未执行；开发完成不代表月线已经上线。

证据：[样本](stock_month_m10d_sample_20261005.json)、[验证清单](stock_month_m10d_validation_20261005.json)。Dagster定义设计查阅[assets](https://docs.dagster.io/guides/build/assets)、[resources](https://docs.dagster.io/guides/build/external-resources)、[partitions](https://docs.dagster.io/guides/build/partitions-and-backfills)、[checks](https://docs.dagster.io/guides/test/asset-checks)及当前安装版本临时job；最终行为以实际测试为准。
