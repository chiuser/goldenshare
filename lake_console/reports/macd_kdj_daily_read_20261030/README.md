# MACD/KDJ日更读取修正：开发与隔离验收

2026-10-30。依据原方案第17节与原写入LLD第19节，设计`4a4a689e`及实现`5a0b13401`已提交。最新正式结果：获准后只恢复29日1m，run`63c25bed-bdc8-4fee-9af8-0321b5b13ac7`已SUCCESS，两物化/四检查通过，154.728秒，详见[最终对账](recovery_20261029_1m/final-verified.json)。其他六频未重跑，2股历史repair未执行，repair sensor按批准暂缓并保留原cursor。

- [总体结果](validation-summary.json)：315项测试、23项子测试通过，另完成实际新producer到原reader/API的双环境隔离文件交接。
- [新日更及发布测试](daily-and-publication.xml)：66项；[日志](daily-and-publication.log)。
- [原历史/repair回归](history-repair-regression.json)：121项及18子测试；[日志](history-repair-regression.log)。
- [原受保护门禁](static-gates-summary.json)：113项及5子测试、15批OS资源隔离。
- [原reader/API](consumer-existing.json)：15项；[实际生产者输出](handoff-producer.json)与[原消费者读回](handoff-consumer.json)。这里的生产者仅对人工临时文件执行，未读正式行情。
- [根AST对账](ast-compatibility.json)及[独立实现审计](independent-review.md)。
- 测试数据、staging和临时runner清理账见cleanup.json；保留的JSON/XML/log及py.txt为验收证据，不是正式运行入口。

上述validation-summary及测试/独立审查是正式恢复前的开发阶段证据：公式与前日state承接、非目标记录、共享state、原repair/history及真实下游按原合同验证。不重刷已完成历史是交付条件，不通过历史初始化或迁移适配新代码。该阶段没有触发/重载正式任务或修改sensor；其证据不预先证明实际4GB异常消除。随后正式1m恢复的实际成功结果单独记录，不篡改原开发阶段快照。

提交后又完成[独立实现审计](post_commit_audit_20261030.md)和[29日1m有界恢复预检及执行汇总](recovery_20261029_1m/summary.json)。管理员明确批准160/26/32GiB的1m范围及暂缓repair sensor后，按原job原root只续跑失败1m；原4GB报错的数据准备阶段本次实际通过。没有新增性能测试、全局审计或自动重跑；原方案17.10及LLD19.13—19.14记录批准与执行。

收尾publication有5,571份完成记录，候选目录已空；必要冻结输入及receipt保留，未删正式数据或续跑依据。原生结果/检查/开关读回见[final-response](recovery_20261029_1m/final-response.json)，没有额外行情内容读取。TODO：另核原job生成的2股历史repair预算并获准后执行，再恢复本次暂缓的sensor。

后续2股repair的[方案、metadata和预算](recovery_20261029_repair/README.md)已完成，两条独立审查未发现需要改代码的阻断；正常原job读20GiB、写10GiB、空间12GiB，具体历史读取正在申请，尚未执行。先按管理员要求提交已完成结果及可review的执行安排，后续修补和开关恢复结果另行追加提交，不将方案存在当作repair成功。
