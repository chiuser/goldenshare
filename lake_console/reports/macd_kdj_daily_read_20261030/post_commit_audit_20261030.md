# MACD/KDJ日更读取修正：提交后独立审计

2026-10-30，审计提交`5a0b13401`及当前代码。依据原业务方案17.2/17.9/17.10和原写入LLD19.2—19.13。本轮只读审计，不重复正式行情或全套测试。

结论：在本次日更修正范围内，未发现实现错误、阻断或必须重刷历史才能接入的遗漏。正式恢复仍需具体年度读取批准；测试通过不代表已完成补数或实际4GB异常已验收。

## 独立审查结果

| 审查 | 当前代码与证据 | 结论 |
| --- | --- | --- |
| 取数及计算 | 新prepare逐股/逐批读取Y/Y-1；当前年Top8、上一年按需补足；先窗口后筛目标日；前日完整state和原1024分段；8项原函数AST及3个公开签名再次比对 | 仅修改取数组织，原公式/状态承接保持；1/64/65股未截断，无重刷历史要求 |
| 发布与续跑 | wrapper准备前持锁，全部结果后完整bind一次；原年度/state writer和publication状态机；五项身份读后、bind前、promote前核对 | 候选失败不提前写正式；中断按原receipt继续；旧摘要冲突不触发历史重刷 |
| repair/history与下游 | 原repair/history仍调用原公共writer和原prepare；提升前回调默认None；原12列、路径、版本、参数、分页合同和真实临时交接 | 单日repair不会误进新daily，无新增repair名单或范围，下游无需迁移 |
| 测试真实性 | 新daily35、完整staging31、原历史/repair121、原门禁113、原reader/API15；独立字面expected，真实SQL/文件交接，XML无失败或跳过 | 315项及23子测试证据成立，当前生产模块SHA与报告一致；本轮未重跑 |

非阻断的测试增强建议：`tests/test_stk_mins_qfq_macd_kdj_daily_read.py:400`的多股已有状态相同，不能单靠该例证明两只已有股票互换状态时必失败。旧repair测试有不同股票不同EMA，新daily有新股与休眠股状态不混用的例子；当前原公式在`stk_mins_qfq_macd_kdj.py:480—481/498—499`按`ts_code/freq`关联且AST未变，没有发现串用代码。可增设第1/65股不同K/D的独立字面例子，不据此扩大业务修改或历史重刷。

CodeGraph已核查日更wrapper、原job/sensor、因子repair状态到MACD repair自动触发链，并补读索引未展示的原生GraphQL实现。Dagster官方文档与本机1.13.26源码共同核对原生FROM_FAILURE及run group语义，不使用本地in-process `dg launch`代替正式服务续跑。

## 运行条件及本次读取范围

证据见[1m恢复预检](recovery_20261029_1m/)。只查询原失败run、四条链job各最近4条、最多40条活动run、原run步骤、一个既有pool、三个sensor和单个因子repair run最多180条事件（实际22条、7checks）；只对1m年度文件做stat，无Parquet内容读取，无全局完整性审计。

- 原29日run仅1m资产失败；六频资产及24项检查成功，1m目标state不存在、原operation空，无候选/冻结/receipt需要接管。
- 原29日QFQ和原因子repair成功，7项因子repair检查通过；28日1m state存在。原writer pool为1且空闲，无活动run，未发现脱管股票分钟写入进程。
- 正式Lake/staging同设备、实际用户可写，空闲约2.64TiB。工具隔离环境里的`os.access=False`没有当成正式服务权限错误；另以同用户实际权限只读确认可写，没有创建测试文件。
- location仍是29日08:15加载的旧实例，正式恢复前需要reload；当前没有执行reload。
- MACD repair sensor为RUNNING；原因子repair已生成2股、2014-01-02至2026-10-29的历史任务条件。日更成功会有自动历史读取的可能，不能在仅核定1m预算时忽略该后续动作。

原方案17.10和LLD19.13已记录恢复顺序：取得1m年度读取批准→暂缓该repair sensor并保留原cursor→reload→原job FROM_FAILURE只补1m及四项检查→按原结果收尾。预计读160GiB、写26GiB、空间32GiB，包含原检查及临时读写估算；失败停止、不自动重跑。后续历史repair另核实际名单/预算后按原job衔接并恢复sensor。当前没有停sensor、触发任务或正式补数。

未覆盖：正式全市场运行、原4GB异常真实消除、历史repair性能及其他日期完整性。本轮没有修改生产代码、重跑旧补数、访问行情明细、初始化instance、安装依赖或写正式数据库/Lake。

恢复安排写完后另由发布/repair审查者复核17.10、19.13及本报告，确认FROM_FAILURE与原root实际可衔接、六频保留、年度读取批准、sensor暂缓及历史repair恢复TODO一致，未发现阻断或文档矛盾。文档完整性、相对链接、改动空白及当前代码SHA检查通过；已提出具体读取申请，等待管理员答复，尚未进行任何正式状态写入。

以上为批准前审计时点的记录。管理员随后明确批准该1m范围及暂缓repair sensor，已按原job执行一次，run`63c25bed-bdc8-4fee-9af8-0321b5b13ac7`SUCCESS、两项物化及四检查通过，154.728秒；原错误的prepare阶段实际通过。执行事实见[最终对账](recovery_20261029_1m/final-verified.json)和原LLD19.14，不用本次成功扩大历史repair或其他日期的验收范围。
