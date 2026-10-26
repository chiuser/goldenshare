# D3计算层独立只读审计

日期：2026-10-26。工作区：`/Users/congming/github/goldenshare`，分支`dev-interface`，HEAD `ffaf701e9`。本次没有修改仓库文件；没有执行SQL、pytest、项目导入或正式数据库/Lake读取。

结论：在本次负责的计算对象、依赖展开、SQL公式、历史窗口、数值安全分段、状态接续及表归属范围内，**没有发现可以从当前源码和原设计明确证明的D3缺陷**。这是静态审计结论，不等于重新执行了数值或性能验收，也不覆盖完整D3服务/输出、D4或正式消费者。

## 依据与方法

- 已读根`AGENTS.md`、`src/AGENTS.md`、`src/foundation/AGENTS.md`、子系统边界方案及`goldenshare-dev-intake`技能。目标子目录没有更近的AGENTS。
- 原组件设计的计算、复用、防误用、SQL固定清单条款，以及原LLD第07、08、09、10、18、19、21、22节。历史阶段的“通过/完成”文字不作为本次算法正确性的依据；19.10/18.1/19.25用于确认本阶段已经批准的具体范围。
- 使用`codegraph_explore`核当前计算链；进一步直接读取源文件、七份SQL和相关测试。CodeGraph用于结构核对，不作为运行验证。
- 独立核对了`d3_reference.py`参考算法的构成：原始价格HUGEINT逐根递推，不调用产品的offset、幂展开、参数SQL或计算helper；MA/BOLL参考以整数分/平方和构造。没有运行或重新生成参考。

## 逐项核对

| 要求 | 当前代码及静态判断 | 已读测试及限制 |
| --- | --- | --- |
| 五公开计算、两内部窗口，同一注册表负责执行/发现 | `calculation/indicators/__init__.py:4-20`注册price、MA、BOLL、MACD、KDJ及两个内部依赖；`registry.py:47-67`区分公开/内部解析并固定依赖版本。 | `test_contracts.py`与`test_registry_dependencies.py`。没有执行。 |
| 参数补默认、拒绝bool冒充整数、参数关系及BOLL有限非负 | `calculation.py:26-41,83-93`；未知参数拒绝，参数按定义顺序归一。MACD定义固定fast<slow。没有任意周期/倍率业务上限。 | `test_contracts.py`、`test_indicator_literals.py:17-52`、`test_d3_required_acceptance.py:26-55`。超出SQL类型/系数表示能力时允许失败，与LLD09一致。 |
| 依赖复用键完整、每请求隔离、稳定顺序 | `dependencies.py:45-93`包含证券、周期、目标复权、ID、版本、完整实际参数、初始化；活动路径先查循环，再查完成节点；节点按声明依赖顺序拓扑生成。 | `test_registry_dependencies.py:173-313`直接检查默认/显式参数、共享与不共享、未知/错误版本、循环及请求间隔离。 |
| price只借用目标价格，不重新读取/复权/删除 | `indicators/price.py:26-51`没有SQL、表角色或资源释放；输出为当批`table_name`及新seq范围。 | 字面测试与价格输出对照；正式输入合同/来源由其他审计范围负责。 |
| MA完整N根才有值，N=1为close，窗口先含历史后筛新行 | `moving_average.py:42-63`与`sql/rolling_mean.sql:1-8`使用ROWS、count(*)、avg；外层才按新seq筛选。`MovingAverageCalculation.consume`只借用均值，不重复计算。 | `test_indicator_literals.py:33-35`，`test_history_and_paging.py:43-44,68-70`及`test_batch_lifecycle.py:19-35`。 |
| BOLL使用同窗均值与总体标准差，不足N三个NULL | `bollinger_bands.py:34-58`仅声明同period均值依赖；`sql/bollinger_bands.sql:1-15`只增加stddev_pop并按seq关联新行，倍率安全绑定，不重复avg。 | `test_indicator_literals.py:36-42`独立字面区分总体/样本、倍率0/11与N=1；长参考用整数方差公式。 |
| MACD首根严格0，后续从第二根递推 | `macd.py:88-144`先prepare空state；`macd_first.sql:1-2`按唯一绑定new_first_seq初始化；独立首输出步骤成功后才置initialized。 | 字面测试`test_indicator_literals.py:43-48`；首根两EMA相等、DEA0及hist0符合LLD09/21。 |
| MACD数值表示与公式 | `sql/macd_segment.sql:2-24`对close减固定origin_price，分别平滑fast/slow offset，相减为DIF，再按同段DIF平滑DEA，hist=2*(DIF-DEA)。恒等分量使用1作为负幂底，避免N=1中间窗口求值触及0负幂。 | `d3_reference.py:23-40`用原价逐根整数递推；`test_history_and_paging.py:23-45`与`test_smoothing_boundaries.py:14-42`比较既定有限样本。未重新验证数值误差。 |
| KDJ按自身window、窗口不足用已有行、平区间RSV50 | `kdj.py:45-65`、`sql/kdj_window.sql:1-9`，即使共同历史由MA250拉长，ROWS窗口仍按自身window−1，不把最大公共窗口套入KDJ。 | 10001组合/翻页参考、字面平区间、19.25的RSV60/90/30非对称字面预期。 |
| KDJ初值50/50，首根仍更新，k_period/d_period=1各自恒等 | `kdj.py:89-110,134-150`初始化一行(0,50,50)；`sql/kdj_segment.sql:1-17`先算K，再算D，J=3K−2D，两个恒等条件独立。 | `test_d3_engine_extension.py:172-207`明确区分首根更新及k1/d1；预期为独立字面数。 |
| 段长由SQL计算，任一无效分量整次拒绝 | `sql/smoothing_parameters.sql:1-14`为BIGINT先转DOUBLE后加1；N=1单独1024，其他按floor(256/−lnβ)与1024限制。`macd.py:37-44`及`kdj.py:89-94`先显式传递任一NULL，不让least忽略；`calculation.py:267-280`拒绝无效段长。 | `test_d3_required_acceptance.py:26-55`检查slow单分量无法表示、尚未读价格/建state即失败；未扩展成额外参数矩阵。 |
| 只递推新seq，不重复历史；跨8192和数学段接续；每段更新一次 | `macd.py:110-143`与`kdj.py:160-182`固定控制读取→段计算→追加→一次UPDATE→drop work。SQL范围均为seq>state.last_seq且≤next_end。初次/后续批及每段expected_last均核对。状态表请求级，output/work批级。 | `test_history_and_paging.py:60-83`使用8192+1809及8192+809，检查第二批MACD段计量P+2=2060并与原始价格独立参考对照；源码未出现额外状态更新。没有D4运行证据主张。 |
| 计算只使用PriceBatch公开表，不读ti_price_new | 所有built-in SQL的price角色都来自当前`batch.table_name`；`engine.py:113-132`只给当前输入与声明依赖可读权；MACD首根/段SQL均只映射该名称。 | `test_d3_output_failures.py`归属反例拒绝ti_price_new输入；静态检查实际模板，没有把SqlStep清单当作任意SQL正文验证。 |
| 借用表不可写/删，自有表先登记再创建 | `engine.py:33-75`按代码TABLE_ROLES与node_index生成独占名称；`calculation.py:200-246`写删同时核生成名与已登记清单。把借用表误加batch_tables也不能取得所有权。正常释放反向拓扑，父对象只借用依赖。 | `test_d3_output_failures.py`实际反例误加借用清单后drop仍拒绝；仅对内置可信固定SQL防误用，不主张任意不可信SQL隔离。 |
| 固定模板、每请求每文件一次、无跨请求渲染缓存 | `sql_templates.py:13-66`在查缓存前核完整固定包/文件清单，返回只读映射；`engine.py:81-96,168-202`保存session再加载，close无论SQL清理失败与否均释放文本；指标对象没有构造/consume文件I/O。七份数学模板与类声明一致。 | `test_history_and_paging.py:67,83-86`、`test_smoothing_boundaries.py:38-42`、`test_d3_engine_extension.py:245-351`核文本一次、取消、只读和重复清理。新增对象不改engine分支的既定借用输出检查见同文件首个测试。 |

## 结论边界

- 没有从旧验收报告的“通过”字样推出算法正确；本次逐项比较的是当前实现、原公式和当前测试断言。
- 没有执行数值SQL，所以不能把本次静态核对写成新的精度、取消时延、实际扫描量或内存测量。相关已有运行证据是否匹配提交文件，应由总审计核对。
- 19.10已把正常数值验收固定为10001/9001/2051及既定小样本。本次没有把额外EMA2长矩阵、全参数组合或D4压力/并发/正式API、页面、XXM、DG退出列为D3缺陷。
- 本报告只覆盖计算层和为核计算要求所需的相关测试；完整输出、服务、来源和执行控制的整体结论由其他独立审计合并。
