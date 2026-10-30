# 2026-10-29主要指数日线九转缺失原因审计

只读审计；不触发job、sensor evaluation或状态写入，不额外读取Parquet行情。

## 结论

Gold九转sensor将当日2026-10-30包含在最近10交易日窗口，并在发现任何未注册日期时立即退出。指数分区注册器按现行规则16:00才登记当日，故今日正常未登记被误用为阻止29日工作的条件。29日Gold和Prod任务均未创建，两个sensor实际均RUNNING。Prod只监听Gold更新job成功，Gold未执行导致Prod连带缺失。

29日上游主要指数行情已在2026-10-30 09:12完成，四项原检查全部通过并指向该次物化。28日九转原检查通过；最近四个已注册分区为29/28/27/26日。Gold sensor09:20、09:30及10:10/20/30均因30日未注册跳过。

## 当前代码依据

- `lake_console/orchestrator/src/orchestrator/defs/sensors/major_index_nineturn_sensor.py:129-169`：same_day_register_start=None、if not gap.ready整轮退出、尚未选择旧日期。
- `lake_console/orchestrator/src/orchestrator/defs/sensors/cn_a_trade_day_sensor.py:26,245-330`：16:00注册当日。
- `lake_console/orchestrator/src/orchestrator/defs/asset_guards/bounded_continuity.py:307-350,356-405`：当日窗口、注册缺口；已有内部缺口与末尾未注册区分。
- `lake_console/orchestrator/src/orchestrator/defs/sensors/index_daily_nineturn_prod_core_sensor.py:37-63`：仅监听Gold原job成功后再校验。
- `lake_console/orchestrator/src/orchestrator/defs/sensors/readiness.py:397-416,494-530`：上游检查按target materialization storage id关联；四项上游check partition为null不能据此认为缺失。

## 证据

- [验证摘要](verified-summary.json)
- [sensor、29日和近期job记录](preflight-response.json)
- [注册规则运行记录、最近分区与28日检查](gate-response.json)
- [29日上游四项检查及物化关联](upstream-check-response.json)

## 建议方向（未实施）

修正该sensor对窗口末尾尚未到注册时间的当前日的处理，让已经注册的较早日期继续被选择；窗口中间的真实漏注册仍须阻断，保留目标完整性、同日上游和前日连续性检查。然后按原job依次补29日Gold、校验、Prod发布及其原检查。未授权开发与补数，本轮未实施。
