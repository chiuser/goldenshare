# 2026-10-29 MACD/KDJ原因子repair补齐

原业务方案17.11、写入LLD19.15。仅使用现成job，不修改代码或新增计算入口。

实际产物：000878.SZ、688563.SH，2014-01-02至2026-10-29，全七频，batch=`qfq_factor_repair:2026-10-29:633a5dece517`，hash=`e53fc5c69277b27eb383eb4bc5eacae92b02dfe39bd779947d7779b5874af198`。名单由原job产物生成，本轮只承接，不增删。

- [文件metadata](metadata-budget-inputs.json)：QFQ119份约27.5MiB、原指标119份约62.8MiB、共享state21,812份约3.58GiB；无Parquet内容读取。
- [预算](budget-model.json)：正常一次原job含校验/摘要/临时读写/收尾，读20GiB、写10GiB、空间12GiB，失败停止、不自动重跑。该历史范围不属于此前1m批准。
- [原生预检](preflight-response.json)：无活动任务、pool=1空闲、repair sensor保持STOPPED，近4条repair没有本batch。

两条独立代码审计确认正常一次可直接执行。QFQ只读2股七列，旧共享state合并以保留其他股票；末尾14completion不是14遍全史读取。原repair每频独立operation，不承诺重启整个job自动续跑；失败应保留现场另核范围。成功按原14项共同scope验收后恢复原sensor，原sensor按同batch completion去重，cursor/lastRunKey保留。

当前状态：方案/LLD及预算已完成，等待具体历史读取批准；未执行repair、未恢复sensor、未改代码。执行与提交结果随后按真实事实追加。
