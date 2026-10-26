# D3 提交后第二轮独立只读审计：计算侧

审计基线：2026-10-26，分支 dev-interface，HEAD e591b7eca73a04e6ed5f730d6e06bd28eb6470a9。计算目录、discovery 与原两份 HTML 在本轮读取时没有未提交差异。未采用旧审计或完成报告作为实现正确依据。

结论：本分工范围内未发现可由当前代码证明的实现错误，也未发现原 D3 经 19.10、18.1 及后续确认修订后仍未实现的明确要求。这个结论是静态审计结论，不新增运行通过结论。

## 已核对的实现

| 对象 | 当前代码依据 | 核对结果及 LLD 依据 |
| --- | --- | --- |
| 参数与定义 | calculation/calculation.py:20-93；indicators 各 DEFINITION | 正整数拒绝 bool/非正数；倍率有限非负；fast<slow；默认值从定义补齐；未引入任意周期/倍率上限。对应 09.1。 |
| 历史及投影 | calculation/history.py:24-32；各 input_requirement；service.py:85-93 | 合并必需字段、最大有限前置根数和是否从源起点递推；KDJ 自身 window 与同请求最大窗口分开。对应 06/08/09。 |
| 注册、发现与依赖 | calculation/registry.py:26-80；dependencies.py:41-93；discovery/catalog.py:31-52；indicators/__init__.py:4-20 | 执行/发现使用同一 Definition；隐藏内部窗口；先校验全部公共实例，再按声明顺序展开；完整请求上下文、参数、版本及初始化组成复用键；请求局部去重；多个 instance_id 保留。对应 04/07.1/07.3。 |
| MA | indicators/moving_average.py:42-63,86-99；sql/rolling_mean.sql:1-8 | 使用 ROWS 的完整 N 根窗口，N-1 前为 NULL，N=1 为 close；MA 直接借用内部均值。对应 09.3/21.3。 |
| BOLL | indicators/bollinger_bands.py:34-58；sql/bollinger_bands.sql:1-15 | 同 period 的内部均值共享一次；总体 stddev_pop；不足 N 根各输出 NULL；倍率绑定；N=1 标准差 0。对应 09.1/09.3/21.3。 |
| MACD | indicators/macd.py:37-64,88-144；sql/macd_first.sql:1-2；sql/macd_segment.sql:1-24 | 首根保存 origin_price 和两 offset=0，输出三个字面 0；后续 close-origin_price 的等价 EMA；DEA 对本段 DIF 平滑；hist=2*(dif-dea)。只选 last_seq<seq<=next_end；首根/后续批/后续段均核进度；生成、追加数量核 S，UPDATE 核 1，段末仅更新一次。对应 09.3/21.1。 |
| KDJ | indicators/kdj.py:22-65,89-110,134-183；sql/kdj_window.sql:1-9；sql/kdj_segment.sql:1-17 | 独立 window 高低窗口，历史不足用已有行，平区间 RSV=50；prepare 初始 K=D=50；首根进入计算；K 平滑 RSV、D 平滑当前 K；单个 period=1 只短路本分量；每段只处理新编号并更新一次。对应 09.3/21.2。 |
| 安全分段及不可表示参数 | sql/smoothing_parameters.sql:1-14；macd.py:37-44；kdj.py:89-94；calculation.py:248-283 | SQL 求 alpha/beta/S；N=1 使用恒等分支；普通分量受 beta 与 S 上限约束；复合参数任一 safe_rows=NULL 显式传播 NULL，Session 转 RequestInvalidError，不能被 least 忽略。Python 只安排控制整数，不计算指标或系数。对应 07.4/09.2。 |
| 固定 SQL 与表归属 | sql_templates.py:13-92；engine.py:33-99；calculation.py:190-246 | 固定包/7 文件白名单；窗口替换只接受非负整数；类固定表角色生成 node 后缀；先登记再创建；借用表仅读，自有且已登记的表才可写删；两条控制 SELECT 独立调用。对应 07.3/07.4/21.6。 |
| 模板生命周期 | engine.py:16-26,77-96,171-202；sql_templates.py:32-66 | 每请求缓存未渲染文本；每个固定包/文件一次；节点只读映射；部分 prepare 失败可 close；close 的 finally 清空所有模板引用，清理失败可再次清理。对应 07.5/21.6。 |
| 当前批与释放顺序 | engine.py:102-168；service.py:115-125 | 每唯一节点每批执行一次；依赖/输出的新编号必须是当前批；上批未释放不能消费下一批；当前 PriceBatch.table_name 唯一交付；结果收集和输入历史保留后才反向释放计算批表。对应 07.3/08/21。 |

## 对现有测试文本的静态核对

仅读测试代码，没有运行：test_indicator_literals.py、test_history_and_paging.py、test_smoothing_boundaries.py、test_batch_lifecycle.py、test_registry_dependencies.py、test_d3_required_acceptance.py、test_d3_engine_extension.py。

- 字面例中有 MA/BOLL、首根 MACD、周期 1、合法大窗口、倍率 0/11 和重复 MA 身份。
- 10001/9001 正常分页测试文本核独立参考、8192/1809 与 8192/809、249 根历史不重复递推、MA20/BOLL20 每批共享均值、模板每请求一次。
- 2051 根测试文本同时请求默认与 9/65/9、10/69/10，使用独立参考，分开状态并共享来源。
- 已补的 3 根不对称 KDJ 文本使用 RSV=60/90/30 的独立字面预期，能区别错误首根 50 与 k_period/d_period=1 的错误整体短路；还覆盖新 Calculation 无引擎指标名分支、旧批输出拒绝。
- 单个不可表示 MACD 分量和模板缓存/取消/重复清理已有明确测试文本。

没有重新要求被 19.10/18.1 或后续修订替换的旧参数矩阵、旧分批组合；没有把 D4 的性能、并发或真实取消作为 D3 缺项。

## 方法与限制

先读根 AGENTS.md、src/AGENTS.md、src/foundation/AGENTS.md、子系统架构基线。使用 CodeGraph codegraph_explore 辅助定位计算、依赖、注册和 HistoryRequirement 的调用关系；判断依据是随后逐文件读取的当前源代码、7 份 SQL 文本及原组件设计/LLD 07/08/09/10/18/19/21。

本轮没有编码、测试执行、SQL 执行、项目导入、真实数据访问或仓库文件修改。未独立证明所有合法参数/任意源数值的浮点精度；LLD 本身只承诺既定有限验收。19.29 直接 calculate 字节修复、完整输出模块与 Executor 的专项审计由其它分工负责，不在本结论内。
