# 2026-10-29 MACD/KDJ原因子repair补齐

原业务方案17.11、写入LLD19.15。仅使用现成job，不修改代码或新增计算入口。

**最终SUCCESS**：run`86d8b492-c056-412d-b9cc-551462e3188e`，09:39:15—09:43:56，281.185秒，原14项completion逐行scope一致，sensor已恢复RUNNING。见[最终对账](final-verified.json)。

实际产物：000878.SZ、688563.SH，2014-01-02至2026-10-29，全七频，batch=`qfq_factor_repair:2026-10-29:633a5dece517`，hash=`e53fc5c69277b27eb383eb4bc5eacae92b02dfe39bd779947d7779b5874af198`。名单由原job产物生成，本轮只承接，不增删。

- [文件metadata](metadata-budget-inputs.json)：QFQ119份约27.5MiB、原指标119份约62.8MiB、共享state21,812份约3.58GiB；无Parquet内容读取。
- [预算](budget-model.json)：正常一次原job含校验/摘要/临时读写/收尾，读20GiB、写10GiB、空间12GiB，失败停止、不自动重跑。该历史范围不属于此前1m批准。
- [原生预检](preflight-response.json)：无活动任务、pool=1空闲、repair sensor保持STOPPED，近4条repair没有本batch。

两条独立代码审计确认正常一次可直接执行。QFQ只读2股七列，旧共享state合并以保留其他股票；末尾14completion不是14遍全史读取。原repair每频独立operation，不承诺重启整个job自动续跑；失败应保留现场另核范围。成功按原14项共同scope验收后恢复原sensor，原sensor按同batch completion去重，cursor/lastRunKey保留。

启动前准备记录：方案/LLD及预算随`78a5ad31d`提交，管理员随后明确批准本次精确历史范围及20/10/12GiB预算。当时小查询确认14项completion均不存在、无重复任务、pool空闲、原scope及代码未变、sensor仍STOPPED，未预填repair成功；此后实际结果按事实追加到原LLD19.16及下文，未改业务代码。

获批后原job只执行一次。实际2股指标重算1,209,754行、119年度文件；共享state21,812文件/85,301,874行含保留的其他股票，不能称为全市场重算。七频每频3,133目标、合计21,931，完成记录同数、候选0；必要冻结输入66,943,799B及receipt保留。[publication metadata](publication-final-metadata.json)只核完成记录/路径，不追加行情读取。

[原始14completion](final-response.json)及[验收](completion-verified.json)证明全部成功、partition=29日、起止/七频/2股/hash/batch一致；completion-verified是恢复sensor前快照，当前状态以final-verified为准。随后[原生start响应](start-repair-sensor-response.json)严格保留原id/cursor/lastRunKey；[收尾](closeout-response.json)证明RUNNING、无活动run、pool空闲、同batch仅本次一条SUCCESS，最新tick跳过、无新run。后续cursor正常推进已识别，不误报丢失。

独立最终对账通过，见[审查记录](independent-final-review.md)；未改业务代码、没有性能样本或额外全局审计、没有自动重跑/人工中断。原方案17.11及LLD19.16同步结果，关闭本次sensor恢复TODO；实际执行记录随本次收尾提交，不push、不带入其他工作区改动。
