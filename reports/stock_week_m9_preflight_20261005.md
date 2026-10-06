# 股票周线 M9：正式更新前只读预检

2026-10-07纠偏说明：本报告保留历史结论；搬运/审计中间数据文件已按管理员要求清理，不再是正式检查或调度依赖。现行口径为 bootstrap 完整对账一次即结束、日常只检查当前新增周期。详见[清理记录](stock_period_reports_cleanup_20261003.md#2026-10-07运行依赖纠偏及清理)。

2026-10-05 23:08—23:10，Asia/Shanghai。依据周线方案及LLD§34，检查2026-10-02一个已结束周。结论：源完整响应、当前正式上游、目标不存在及并发任务检查通过，可以进入独立审批的正式交付阶段；M9尚未完成。本轮没有启动job、执行sensor/check、注册分区、写正式Lake/event/cursor或启用调度。

## 当前事实

| 检查 | 未复权主源 | 复权主源 |
|---|---:|---:|
| MCP显式全部字段 | 13列，5565行 | 21列，5565行 |
| SDK limit=6000 / offset=0 | 5565行 | 5565行 |
| SDK limit=6000 / offset=6000 | 0行，字段仍完整 | 0行，字段仍完整 |
| MCP与SDK全字段类型归一后hash | 一致 | 一致 |
| 期望代码缺失 / 多余 | 0 / 0 | 0 / 0 |
| 个股end_date与日线最后日期不一致 | 0 | 0 |
| 全部源字段NULL | 0 | 0 |
| 主键 / 类型 / Decimal精度 | 通过 | 通过 |
| 正式2026-09-25交付基线 | ready | ready |
| 正式2026-10-02交付状态 | missing | missing |
| 排队或运行中的该主源job | 0 | 0 |

日历实际开市日为9月28、29、30日。读取3个日线文件、16677行、期望5565代码、6163身份键；现行身份及日线上游blocking checks通过，按目标materialization绑定核验。两源end_date均为20260930的5561行、20260929的3行、20260928的1行，全部与个股日线截止日匹配。周线trade_date仍为20261002，不能因为周五休市改成20260930。

两份10月2日正式目标均不存在，该周动态分区尚未注册。weekly sensor没有持久化instigator state；当前定义默认STOPPED，本轮未启用。没有独立确认长期运行code location的加载版本；后续拟用本项目当前源码及显式module/attribute执行，调度启用前另核实正式加载版本。

正式Lake与staging均在获准路径，同文件系统，datasource已挂载，剩余约2.93TB。两份源CSV合计约1.65MB。预检DuckDB为512MiB、2线程、现有/private/tmp、禁止spill和扩展自动安装；正式只读文件/事件核验约0.602秒。MCP两次完整字段请求；SDK串行四次分页请求，每次不超过6000行、20秒受监督超时，不重试。SDK实测每次约1.6—3.6秒，不能作为正式更新总耗时承诺。

所有正式上游指纹及两个历史基线指纹在只读检查前后不变，新目标前后均不存在。完整参数、行数、hash、耗时及文件路径见JSON证据（历史中间文件已清理）。完整响应捕获位于/private/tmp，供本次核验，不是正式Lake或bootstrap事实源。

## 下一阶段执行清单：尚未执行，待管理员批准

范围仅为2026-10-02两个主源完整市场周线，串行执行未复权后复权，每个job只选择自己的Raw资产及三个blocking checks。沿用automatic_intent_date配置，通过手动CLI执行现行自动更新交付逻辑，不启用sensor。只注册1个周分区、最多创建2份正式文件，预估每源5565行、合计11130行；正常源请求2次，两源总硬上限24次（含技术重试）。成功交付最多2个materializations和6个checks，另有真实run生命周期事件；不使用runless补录。

工作目录：/Users/congming/github/goldenshare/lake_console/orchestrator。
目标DAGSTER_HOME：/Users/congming/.goldenshare/dagster_home。
执行入口和配置已准备在/private/tmp/stock_week_m9_preflight_20261005，尚未运行。dagster-expert的dg launch参考与现有`.venv/bin/dg launch --help`已核对：当前版本使用`--config`；显式module/attribute避免进入DgContext项目依赖管理分支，不调用uv或安装。

按顺序单独执行，前一个失败立即停止：

```bash
.venv/bin/python3 -B /private/tmp/stock_week_m9_preflight_20261005/register_partition.py
```

```bash
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --attribute defs --job raw_stk_period_bar_week_update_job --partition 2026-10-02 --config /private/tmp/stock_week_m9_preflight_20261005/primary_unadjusted.yaml
```

```bash
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --attribute defs --job raw_stk_period_bar_adj_week_update_job --partition 2026-10-02 --config /private/tmp/stock_week_m9_preflight_20261005/primary_adjusted.yaml
```

配置分别只含对应asset的`automatic_intent_date: '2026-10-05'`，不传股票过滤；跨天执行须先重核执行日期并更新清单，不能把审批范围自动延伸。注册入口再次核对instance配置身份、上游/基线hash、目标missing及并发任务。正式job使用既有worker、checkpoint、原子提升及三个检查，写后再只读核对数量/schema/全字段hash/交付证明、事件准确绑定、两个基线未变及period_status=ready。source新响应与本次审计样本如有差异，必须解释后再宣布验收通过。

候选、分页receipt、请求账本和恢复证据仅进入/Volumes/datasource/data_lake_staging；每文件完整校验后os.replace提升，不覆盖异值历史、不快照、不删数据，不写Prod/Silver/月线，也不调用备用源。已完成文件和事件保留；失败停止并基于原意图checkpoint处理，不清表或删事件“回滚”。这批正常交付批准不等于批准主动取消/杀进程或启用调度。

首次正式两源交付通过后，按原M9门禁另列取消/恢复及幂等读回清单，再完成19:30启用审批和自动执行观察；不提前把M9标为完成。月线M10.F新分区验收仍等10月结束和源/上游就绪，Silver需求继续单列。

## 交付范围

本轮只新增本报告和JSON审计证据，同步周线原方案及LLD的最新执行状态；未修改Python源码、asset/resource/check/partition/sensor合同或src依赖矩阵。只读通过不替代正式交付、取消恢复或调度验收。报告与文档尚未提交或推送。
