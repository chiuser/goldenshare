# D3 最终结果数量补验：独立只读建议

当前代码和原 LLD §14.5/19.10/19.29已核；CodeGraph explore定位 build_result→_read→read_result，再核实际服务、执行器和测试夹具。未执行pytest、SQL、项目导入或修改仓库。

## 最小可行设计

一个测试函数，内部固定3次真实calculate，使用现有3份日线字面文件：600000.SH，2026-01-05/06/07，价格10/12/11，stock/day/none，price一项，limit=3。显式控制替身 D3Control，只替代停止/时钟，不替代数据库执行器；不创建真实控制对象。

原read_result方法仍执行。测试包装该方法，仅step.name为select_result时临时将executor.connection替换为代理，finally恢复真实连接。代理.execute把原SQL和绑定交给实际连接，拿到真实游标及原description；仅fetchmany首次返回结果可按本例故意改变。其他SQL和COUNT完全不替代，源读取/Arrow/SQL/保留范围/异常检查/服务清理全部保留。

| 调用 | 注入 | 应有独立断言 |
| --- | --- | --- |
| 正常 | 首批原样3行，第二次真实空 | 返回3日期、公开6字段的10/12/11价格及100量/1000额；版本、默认参数和range/count3符合合同；COUNT真实为((3,),)；2次fetch。 |
| 少取 | 真实首批3行只向原read_result返回前2行；第二次真实空 | 原executor成功取完2行，collector COUNT3与len2不符，精确OutputContractError、reason=fetch_count_mismatch、stage=final_fetch、diagnostics={expected_count:3,actual_count:2}；不返回任何结果；2次fetch。 |
| 超限 | 真实首批3行追加末行的测试副本，向原read_result返回4行 | 原executor累计4>max_rows3即精确OutputContractError、相同reason/stage、diagnostics={expected_count:3,actual_count:4}；不返回成功或截断结果；1次fetch。 |

只断言这两个必要拒绝规则，不拓展COUNT本身变化、字段原因或参数矩阵。真实COUNT的结果应通过原read_result执行后记录，不得直接返回伪COUNT。禁止替换OutputCollector._read、build_result或输出JSON来制造预期异常。

## 能证明到达目标的位置

3次count_tail均真实返回((3,),)，最终select_result原SQL均实际执行；短取select_result统计output_rows=2、failed=False，随后collector抛错；超限统计output_rows=4、failed=True，证明分别经过不同的既定检查，而非更早append拒绝。输出错误的数量字段保存在caught.value.diagnostics中。

每次都核source_rows=3、batches=[3]、source_open_calls=1、_executing=False、live_tables/live_arrow空、cleanup_ready=True、resources_released_at非None；用捕获的真实连接进行SELECT 1并得到duckdb.ConnectionException/closed，证明实际关闭。两个预期错误没有清理附记。

## 量化预算依据

每次逻辑SQL38：stage3+target3+input_window3+inspect11+check3+merge3+retain3+rename3+count3+select3。负例发生在最终fetch阶段，已执行相同步骤，因此不能少计SQL。3调用114，加一次3份夹具COPY3及3次关闭探针3，共120。来源输入9，夹具3，新增真实控制对象0。保留原100000输入/5000000逻辑SQL/4真实控制/30秒单程序/300秒累计限制，新增精确上限与首错停止由主审写回原方案和LLD后执行；不自动重试，不重跑旧27项。

## 夹具和副作用

原d3_data固定上轮plan状态、唯一nodeid、基线、生命周期记录名，需按原恢复入口切换到本轮，不能直接选新测试绕过检查；保持root由TemporaryDirectory持有、session-finalizer立即登记、清理确认和原预算续接。新基线继承21139/1324859/Control4/fixture10055及完整程序18.977130916900933秒，不重建原长数据。只有当前owned3份文件进入源读取。

祖先路径未找到conftest.py；仓库仅tests/web、lake_console/orchestrator/tests有各自conftest，不支配本目录。pyproject仅pythonpath和testpaths，无新增插件/隐式安装动作。prepare_required_literals严格依照已经核过的DG日线11字段合同，三个COPY和footer检查，实际读取在calculate中计量。不得修改真实源或产品代码以迎合测试。

## 执行后独立证据核对（2026-10-26）

主审按批准唯一节点执行后，本分工仅读取原始stdout、execution、details、fixture生命周期及acceptance，并用标准库读取当前代码与JSON核指纹/前缀；没有再次执行pytest、SQL、项目导入或行情计算。

- 原始stdout为1 passed in 0.81s，无teardown错误；execution返回0、不超时、自动重试0，外层1.1433410830795765秒，累计完整程序20.12047199998051秒。
- normal：真实COUNT3，原游标3/0，交付3/0，返回成功；select_result output_rows3、failed=False。正常独立字面断言已在本函数内执行通过。
- short：真实COUNT3，原游标3/0，交付2/0，未返回；精确OutputContractError/fetch_count_mismatch/final_fetch，diagnostics为3对2、清理附记空；select_result output_rows2、failed=False。因此该次由Collector最终数量比较拒绝，未提前在append失败。
- over：真实COUNT3，原游标3，交付4，未返回；同类错误/原因/阶段，diagnostics为3对4、清理附记空；select_result output_rows4、failed=True。因此该次由原执行器max_rows判断拒绝，没有截断成功。
- 三次均真实final query仅一次、source_rows3/batches[3]/source_open_calls1/SQL38、connection_restored=True/_executing断言通过、live_tables/live_arrow空、cleanup_ready=True、resources_released_at有值。三次对捕获真实连接的探针均为ConnectionException且文本Connection already closed。
- 独立比较final_fetch_count_baseline与当前progress：executed_cases/queries/calls/template_reads四项历史列表前缀逐项相等；新增仅夹具case和本轮一个函数case，均passed。67份受保护文件SHA256无差异，独立参考SHA256一致；前轮execution_calculate_output_bytes记录未改。
- 实际新增9输入/120逻辑SQL/0真实Control/3夹具，累计21148/1324979/4/10058；与预算和预期一致。生命周期记录removed=True/errors=[]，独立检查本轮owned_root实际不存在。

据上述源码和运行证据，原D3最终fetch数量的两条反向验收缺口已补齐，未发现本补验新的问题。该结论不包含D4或正式API/页面验收。
