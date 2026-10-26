# D3 最终确认：独立只读核对与补验结果复核

日期：2026-10-26。工作区：/Users/congming/github/goldenshare，dev-interface。

## 当前结论

补验前完整只读核对未发现除最终读取数量反验外的其他D3确切遗漏；补验后已独立核对新测试、原始stdout、execution、details、fixture及acceptance记录。**本轮已覆盖最后两条数量反验，原D3步骤5/6范围内未发现剩余确切实现错误或有效要求遗漏，可以确认D3按既定范围完成。** 此结论不包含D4、正式消费者迁移或DG退出。

## 独立复核范围

1. 重新读取根/src/foundation的AGENTS，使用CodeGraph explore定位service/engine，再读取当前service.py:74-192及图返回的engine.py全文。核对参数/计划和不可变说明先于I/O、唯一请求连接、真实输入准备、消费/收集/保留历史/释放/finish顺序、最后字节计量及统一清理出口。
2. 复核原LLD22的25项及原d3_final_audit.json逐项对应。保留D1/D2证据与D3步骤5/6的区别，没有把设计表“已写明”等同运行通过。19.25/27/29各阶段补项纳入当前要求，19.30补最终读取反验；没有恢复旧的人为长样本矩阵。
3. 静读当前tests/architecture/test_technical_indicator_dependencies.py，核固定7计算/3输出SQL集合与package-data、输出不依赖plan、无旧分页探测字段等断言；仅读文本，没有执行导入/子进程/测试。
4. 静读test_history_and_paging.py:23-86，核真实10001/9001、8192满批/尾批、独立MACD/KDJ/窗口参考、MA20/BOLL20共用均值14次、249根历史不重复递推、输出字段/参数/版本及分页边界断言。其余算法、输出、既定验收覆盖结合上一轮三个独立分报告，并以当前文件指纹确认未变化。
5. 用stdlib读取final_fetch_count_baseline_20261026.json并逐文件核SHA256：67份现有保护文件全部一致；独立参考指纹一致。未读取任何正式行情。
6. 审读19.30的固定三请求/代理最终fetch/真实COUNT/精确异常/统一清理/9输入及120预计逻辑行/单程序及总预算/一次执行停止规则。该计划对应既定缺口，没有新增产品需求。

## 对既有证据的使用

原27个不同pytest项各有通过记录，但本轮没有重跑，不能称新验证。上一轮输出字节修正保留真实calculate/SQL/关闭连接，仅时钟替身；保存1205字节及三阈值证据仍适用。新补验确实只在最终select_result的读取边界故意少交/多交，没有替换COUNT或Collector检查；实际结果的独立复核见下节。

当前保存基线：21139输入、1324859逻辑SQL、真实Control4、10055夹具，含历史失败完整程序累计18.977130916900933秒。4个真实Control均为正常完成服务，不将小故障替身称作完整真实取消性能验收。

## 收尾时要同步的状态

LLD22.1和页脚仍指19.28/原26项完成记录。待本轮有实际通过证据后，应与19.30及最终证据统一，不把旧完成表冒充已覆盖新补验。这是本轮原定文档收尾动作，不另列产品缺陷或新增拍板事项。

## 不在本轮结论内

D4的并发/等待装配、RSS/容量/OOM/完整真实取消及ASGI，正式API/页面/XXM迁移、DG退出、完整wheel构建安装不属于本次D3缺项。有限样本的数值与清理证据不保证任意参数/任意数据或整页性能。

本审计未执行pytest、SQL、项目导入或真实数据访问；未修改仓库，只有本/private/tmp报告。没有新增拍板建议。


## 补验后独立核验（同日）

仅读实际test_d3_final_fetch_count.py及以下原始证据，没有重跑或执行任何SQL：pytest_final_fetch_count_20261026.txt、execution_final_fetch_count_20261026.json、final_fetch_count_details_20261026.json、fixture_final_fetch_count_20261026.json、final_fetch_count_acceptance_20261026.json。

- 唯一pytest函数确实只执行一次：1 passed in 0.81s，外层returncode=0、未超时、自动重试0，完整程序1.1433410830795765秒，原18.977130916900933秒加本次=20.12047199998051秒。
- 一函数3次完整state.run→calculate：同一price/day/none/limit3；原COUNT原样返回((3,),)。代理真实execute原SQL，保留description，只修改首批fetchmany交付的行集合，read_result仍为原实现并在finally恢复原连接。正常3行后EOF；少取首批3变2后真实EOF；超限首批3变4。
- 正常对照逐项核独立三个日期、range.count、price身份/版本/空参数、六个价格/量额字段及msg。没有调用被测mapper生成expected。
- 少取反例：原SQL成功完整取出真实3行但故意只交2行，原Collector抛OutputContractError/fetch_count_mismatch/final_fetch，diagnostics3对2；未返回成功，无清理附记。select_result统计output_rows=2/failed=False，区别于早期append拒绝。
- 超限反例：原执行器在交付4行而max_rows=3时抛同类错误/reason/stage，diagnostics3对4；未返回成功，无清理附记。select_result统计output_rows=4/failed=True。即使Collector后续也会拦住4对3，本测试仍用failed=True证明先触发执行器上限检查，不能用后面的数量核对代替。
- 三次均真实COUNT/最终查询各一次、来源3根一批/open一次、SQL逻辑38、真实连接恢复，table/Arrow存活清单空、_executing=False、control.cleanup_ready=True且resources_released_at非None；均用捕获的真实连接执行关闭拒绝探针并实际得到ConnectionException/closed。
- 目录只由本次TemporaryDirectory拥有并清理，记录removed=True、errors=[]。d3_support.py当前diff严格只有状态/基线/生命周期文件三个名称替换，没有改恢复、合批或清理语义。
- 再用stdlib独立核67保护文件SHA256、独立参考及旧executed_cases/queries/calls/template_reads数组前缀，全部一致。新增calls恰3、真实控制0；新增9输入/120逻辑SQL/3夹具，与执行计划吻合。累计21148输入/1324979逻辑SQL/4真实控制/10058夹具，没有重跑原27项。

本次正常对照加两个真实目标错误拒绝已补齐§14.5/19.30要求。结合补验前有效D3条款及代码/证据逐项核查，未发现剩余明确D3缺项，没有新增需要管理员拍板的内容。原完成说明、22.1及页脚仍由主审按本轮收尾计划统一最新证据；无需再增加计算验证或性能矩阵。
