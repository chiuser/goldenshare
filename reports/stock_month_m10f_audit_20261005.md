# M10.F 月线更新与启用前审计

2026-10-05，Asia/Shanghai。结论：M10.E已提交 `ee325688`，未推送。M10.F在只读前置审计发现实现口径冲突；管理员选择“先保留现状，只完成审计”。本阶段没有修改Python代码、身份数据或Raw，没有执行更新job、注册分区、写事件、改cursor或启用sensor。M10.F未完成。

## 根因

`source_readiness/stock_monthly.py:61–75`读入整张身份表，对每一行的source_ts_code和latest_ts_code都附加六位数字+SH/SZ/BJ格式检查；一行不符就抛 `monthly_identity_invalid_or_over_budget`，尚未检查其是否被该月日线引用。

正式身份表6163行，无重复source_ts_code，未超10000上限。仅`T600018.SH → T600018.SH`违反月线新增的正则。该行来源为`stock_lifecycle`、confidence=confirmed，生命周期2000-07-19至2006-10-20，是身份资产从历史生命周期生成的自映射。身份资产自身要求代码非空、唯一、来源/置信度合法且生命周期可解释，并未强制全历史代码只有六位数字。它的正式blocking checks已通过。因此报错是月线消费者收窄了身份表代码域，不是上游身份检查失败，也不是9月股票身份无法识别。

只要全表保留这一行，当前校验会阻断新的整月更新意图，不局限于2026-09。Bootstrap保留Prod数据走另一条历史证明路径，所以M10.E文件/事件就绪不代表Tushare更新路径已验收。不得通过删除历史行或改写代码消除症状。

## 正式事实

| 项目 | 本轮只读结果 |
|---|---|
| 最新完整月 | 2026-09；当前2026-10尚未结束 |
| 本月日线 | 21文件、116588行、5571只股票 |
| 日线物理合同 | 21文件键字段类型正确，重复键0，日期/目录摆放错误0 |
| 本月身份覆盖 | 缺失、非confirmed或目标代码不合当前股票格式的代码0 |
| T600018.SH本月日线 | 0行；不是本月引用对象 |
| 上游事件 | 21日日线及身份blocking checks的准确目标绑定通过，证据保存在JSON |
| 已bootstrap的两源2026-09 | 现行monthly_period_status均ready；并非新的源更新job验收 |
| 正式code location | orchestrator / __repository__ 已加载月线sensor，GraphQL状态STOPPED |
| 月线sensor持久化 | 未启用；definition默认STOPPED |
| 备用源 | 未请求、未使用 |

源API各对000001.SZ/20260930/freq=month做默认字段、显式文档字段、关键身份/日期/freq字段三类MCP只读请求，共6次。两API各1行，13/21字段，trade_date/end_date均20260930；请求与样本符合本地doc336/365及当前request builder。MCP工具不提供limit/offset输入，因此本轮没有新的分页/全市场完成证明；已有M10.B分页证据保留，但不能把本轮单股结果宣称为全市场更新验收。

## 建议与当前决定

建议对齐正式身份表契约：保留全表hash、来源检查、非空/唯一和预算；格式与confirmed要求只用于本月实际引用的映射。源行情仍走原Raw字段/日期/主键合同，不改历史身份，不新增T600018特例，不清洗Raw，不使用备用源。

该建议尚未批准，没有落入代码或替换LLD规范。若后续确认，再先修订LLD、增加“无关历史T前缀不阻断”和“本月实际无效/未确认映射仍阻断”的正反测试，完成正式只读复核，再串行执行两源最新完整月asset+3checks job；两源更新及读回通过后才启用19:30 sensor。当前按管理员决定保持停止，不留下自动修复、自动启用或定时任务。

周线引用helper已额外做静态对照：它只要求全表代码非空/唯一，并未附加上述六位数字正则，不能把本次月线问题直接宣称为M9周线同一故障。未执行M9源更新验收。

## 依据、影响和验证

依据：原月线LLD的M10.F、根/目录AGENTS、性能治理规范、Dagster当前1.13.18本地dg launch/sensor help、source_readiness与identity当前代码、本地Tushare doc336/365和本轮实测。CodeGraph explore/impact覆盖freeze_month_references→point delivery→两asset/jobs、sensor和readiness消费者，以及身份资产的历史自映射。

仅新增审计报告/JSON，并在三份原方案/LLD追加审计状态；没有改任何运行合同、配置、分层依赖、Raw/Silver/Gold路径或Definitions。只读SQL向量化处理身份和21日日线，未执行全历史逐分区扫描。没有新开发，不用正式资源跑测试；文档完整性、差异检查及业务文件hash/停止状态读回用于本轮验证。新审计结果尚未提交。

证据：[前置校验](stock_month_m10f_preflight_20261005.json)、[身份差异](stock_month_m10f_identity_audit_20261005.json)、[最终审计](stock_month_m10f_audit_20261005.json)、[源字段探测](stock_month_m10f_source_probe_20261005.json)。
