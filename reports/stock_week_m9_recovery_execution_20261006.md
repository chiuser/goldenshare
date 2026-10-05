# M9 周线正式交付恢复执行清单

2026-10-06，Asia/Shanghai。管理员要求提交异常分类修订，确认已重新加载代码，并要求继续。本轮先提交`ca46278c`，未推送；再恢复已批准的2026-10-02同周两主源正常交付。主动取消恢复和19:30调度启用继续分阶段，当前不执行。

## 每日意图及预算依据

10月5日旧run失败且第一页3次尝试耗尽，其原账本和失败事件保留。当前`weekly_update_intent`把真实`daily_intent_date`纳入unit identity，sensor对同一missing周在新一天也按实际日期构造新意图；`WeeklyUpdateExecution.reserve`限制各冻结意图的页尝试和总请求，而不是永久禁止同周。按本轮继续授权，使用真实10月6日每日意图，不修改旧账本、不人为伪造日期或提高上限。手动CLI执行现行更新逻辑不等于启用自动sensor；19:30仍只约束自动触发窗口。

## 已刷新预检

当前源码下两主源各两次真实SDK有界分页：limit6000，offset0各5565行、offset6000均0行；13/21列、完整字段hash与10月5日源预检一致。正式上游3日线/16677行/5565期望代码及身份blocking绑定满足，基线ready、两个新目标missing、无pending job。2026-10-02动态键已注册，本轮不再注册；sensor无启动state。两根同卷、空间充足，旧账本及正式基线指纹不变；10月6日两新assembly均不存在。预检7.373秒，无正式写入。详见[只读证据](stock_week_m9_recovery_preflight_20261006.json)。

## 精确执行范围与命令

cwd：`/Users/congming/github/goldenshare/lake_console/orchestrator`。
DAGSTER_HOME：`/Users/congming/.goldenshare/dagster_home`。
Lake：`/Volumes/datasource/data_lake`；staging：`/Volumes/datasource/data_lake_staging`。

串行执行，前项失败立即停止，不运行复权job；先独立只读验收前项，再执行后项：

```bash
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --attribute defs --job raw_stk_period_bar_week_update_job --partition 2026-10-02 --config /private/tmp/stock_week_m9_recovery_20261006/primary_unadjusted.yaml
```

```bash
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --attribute defs --job raw_stk_period_bar_adj_week_update_job --partition 2026-10-02 --config /private/tmp/stock_week_m9_recovery_20261006/primary_adjusted.yaml
```

配置仅为各对应asset的`automatic_intent_date: '2026-10-06'`，无代码过滤/force/备用源。精确新意图和assembly路径已在JSON冻结；执行前再核对上游/基线、并发、目标missing及日期，不能把成功预检自动延伸为跨日授权。

| 成本与写入 | 上界 |
| --- | --- |
| 对象/周/主源 | 5565期望代码、1周、2主源 |
| 正式请求/分页 | 正常每源1页；硬上限每源12次、每页3次，沿原策略 |
| 目标行/文件/成功事件 | 预计11130行、最多2文件/2物化/6blocking checks；真实run生命周期另计 |
| 参考扫描/内存/spill | 每源现行日历+身份+3日线；沿512MiB/2线程有界门禁，无扩大扫描 |
| 提升/续跑 | 完整候选校验，逐文件os.replace；保留页receipt/checkpoint与原意图账本 |

只创建本周缺失主源Raw，不写Prod/Silver/月线、不改历史文件、不启用sensor或调用备用源。验收独立读回类型/行数/主键/全字段hash及准确绑定的三个blocking checks，并核对旧账本、两历史基线、上游指纹不变。若再次失败，只保存新安全分类和状态，停止，不自动重试已耗尽意图或清理数据。

## 本轮执行结果

以下将在每个正式job及独立读回完成后记录；预检通过本身不是交付完成。

未复权job已成功：run `dd120254-9f0b-4ac5-9a7a-bb3547364566`，1份正式文件/5565行、1物化、3个blocking check evaluation全部通过并绑定当前物化。独立只读schema、主键和全字段hash与本轮源一致，period_status=ready；旧账本、两个历史基线和上游指纹未变。详见[未复权后置证据](stock_week_m9_recovery_primary_unadjusted_20261006.json)。随后才开始复权job。

复权job随后成功：run `f7f20061-871e-48ba-871f-8554d69dad64`，1份正式文件/5565行、1物化、3个blocking checks准确绑定且通过，独立schema/主键/全部源字段hash一致。后置查询确认两源均ready，旧账本/历史基线/上游指纹不变，sensor仍无启动state。详见[复权及最终状态](stock_week_m9_recovery_primary_adjusted_20261006.json)。

两份正式Raw合计11130行，本轮正式源请求各1次、合计2次，每源第一页只占用1次尝试；加恢复前只读分页4次，本轮一共6次源查询。没有补录runless事件、写Prod/Silver/月线、自动使用备用源、主动取消任务或启用19:30。10月5日失败原因仍无法追溯，不能把本轮成功称为原始网络/权限原因已确诊；本轮正式执行未再失败。

## 后续验收安排

1. **正常两源交付已通过**，当前2026-10-02单元完整封存。修订已提交ca46278c，管理员确认重新加载；本轮执行证据及最新状态尚未提交。
2. **幂等重放**可沿同一配置/意图验证：应零新增源请求、正式文件及audit指纹不变，再由真实job生成准确绑定的新观测事件。此为后续额外正式执行，应在清单中明确追加事件数量，不能把当前正常交付当作已执行重放。
3. **主动取消/续跑**应选一个真实未完成的更新意图，在已约定检查点请求取消，再用同一意图恢复，核对进程、计数、receipt/checkpoint及终态。当前已封存意图会直接复用audit，不能验证“运行中中断”；不删除receipt、清空预算、伪造日期或重写已交付行情来制造场景。优先安排下个真实完成周2026-10-09，在源及正式上游就绪后冻结精确命令、取消时点和恢复清单；时间/源未就绪不预报通过。
4. **19:30启用**在前项验收收口后单独执行，核对正式code location、唯一sensor状态、cursor和首次自动观察；本轮不启用。月线M10.F新增月份仍在10月结束且源/上游就绪后进行。

源审计、正常正式交付、幂等重放、主动取消恢复和持续自动运行分别记录，后两项未执行意味着M9整体仍未完成。根因排查诊断已投入本次正式代码路径，但这次没有失败异常可再分类。
