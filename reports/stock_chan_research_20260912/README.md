# 十股缠论研究：统一资料入口

2026-09-13补充：早期指数、共振和蔚蓝锂芯资料已另行[统一归档](../index_market_history_20260913/README.md)，下文“不在本次迁移范围”是9月12日的历史边界。这里的621项原始机器记录及代码迁移认证保持不变，本轮随研究代码和测试一并提交。

当前结论：有限的参数、买点类型和退出方式试验均未找到可靠模式。最新诊断中，134次到期退出有100次无任何账本卖点、34次被同类配对过滤；下一步应先核对无卖点的识别链，尚未启动。

## 只看这些结论即可

| 问题 | 保留结论 | 报告 |
|---|---|---|
| 最初的数据是否可用 | 5股通过、5股需核对；后来确认停牌/零成交语义 | [初次审计](initial.md)、[数据核对](initial-data_audit.md) |
| 十股买点有稳定优势吗 | 172次机会，10日等权0.65%，匹配超额-0.08个百分点 | [完整基线](calendar.md) |
| 调核心参数能改善吗 | 3个新参数均未通过预设筛查 | [参数试验](parameters.md) |
| 买点类型和滞后过滤有用吗 | 类型存在阶段反转，未找到稳定改善 | [类型与滞后](timing.md) |
| 卖点退出是否更好 | 163共同机会，卖点4.83%，固定60日4.85% | [退出对照](exits.md) |
| 为何卖点退出少 | 29正常退出、100无卖点到期、34不匹配到期，执行差异0 | [漏用诊断与六笔案例](sell_usage.md) |

这里是单次机会研究，不是股数分仓账户或实盘收益。固定原10只沪深存续股票、60分钟识别、30分钟观察，输入2021-09-09—2026-09-08，250交易日初始化；有小样本、重复探索、存续筛选及成交代理限制。

## 文件如何收敛

原六个目录的621个文件全部归入本目录。机器资料以SHA256去重，485个不同对象保存在单一evidence.zip，重复行情和事件仅存一份；原始字节可完整复核，不修改历史成绩或重新签名旧manifest。机器证据约80.9MiB压缩到5.6MiB。人读的七份报告只增加迁移说明和修改链接。

这次先解决散文件、重复存储和路径依赖；为了保留原认证链，没有把不同的历史检查证据全部删除。早期指数教学、蔚蓝锂芯和指数共振研究不在本次迁移范围。

catalog.json是逻辑键→内容哈希的目录；storage_receipt.json认证目录及压缩包；code_migration.json记录五个消费者的精确旧/新代码哈希和未变的计算函数；migration_inventory.json保存迁移前文件证据。它们不是另一个交易模型。

## 读取机器证据

代码统一使用StockResearchStore，直接读取压缩包内对象，不解压回旧路径，不从废纸篓取输入，也不回退旧目录。逻辑角色为initial、calendar、parameters、timing、exits、sell_usage。

例如查看四川美丰的30/60分钟输入和首次事件：

```python
from scripts.research.index_market.chan.stock_research_store import StockResearchStore
s = StockResearchStore()
bars30 = s.read('calendar/000731.SZ/input_30.json')
bars60 = s.read('calendar/000731.SZ/input_60.json')
events = s.read('calendar/000731.SZ/full_events.json')
cases = s.read('exits/000731.SZ/cases.json')
diagnostics = s.read('sell_usage/000731.SZ/diagnostics.json')
s.verify_unchanged()
```

其他重要键：initial/source.json保存日历与原筛选信息，calendar/status_10.json保存最终名单及状态，parameters/aggregate.json、timing/aggregate.json、exits/aggregate.json、sell_usage/aggregate.json保存逐轮汇总。完整键可查看catalog.json中的records，不凭历史目录名猜当前路径。

读取会校验包和记录的字节哈希、大小上限；来源核验仍可传入原manifest的期望哈希。历史哈希不能随意放宽，只有本次登记的精确代码迁移对可用于验证同一算法的存储迁移。

## 迁移验收与恢复

迁移前已确认621个记录逐字节读回一致、538项原artifact认证通过，所有纯计算函数AST不变；498项研究测试通过。旧目录移出后，真实复核时机132份、退出21份、卖点诊断21份结果，174份对象与封存数据完全相同，没有重新生成信号或搜索参数。详情见[migration_verification.json](migration_verification.json)。原目录及验证临时输出均移入废纸篓，恢复根为`/Users/congming/.Trash/goldenshare-stock-consolidation-20260912-yo29mia6`，见[移动回执](move_receipt.json)，不永久删除；恢复时不得覆盖已有文件。

本轮只改五个入口的读取和来源记录，原计算规则与CLI参数不变，不访问DG、Lake或网络，不执行新参数搜索，不提交。旧实验输出格式尚未统一改造，未来重跑仍应限定验收产物，不把本轮收敛误称为所有未来输出已自动精简。
