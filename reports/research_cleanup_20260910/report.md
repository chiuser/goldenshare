# 指数与个股缠论研究清理审计

日期：2026-09-10。用户要求研究暂停期间审计并清理废弃计算代码、中间报告。范围仅本任务的`scripts/research/index_market`、18个研究结果目录及其直接文档引用；不处理其他主题，不读取Lake，不重跑实验。**清理及验收已完成：移出3组无独立结论产物，保留15组有意义的报告及复核代码；研究继续暂停。**

## 保留原则与依据

保留可回答一个独立研究问题的结论，包括否定结论、样本不足结论、教学例子和当前数据缺口；保留支持这些结论的事件/价格/评分/来源校验以及计算和隔离测试。不能只留漂亮结果，或删除manifest依赖文件后声称仍可复核。目录名称“旧”“中间”不是删除依据。

已读取各报告结论、manifest、源码导入及固定报告引用，并核对实际文件；逐文件清单和清理前哈希见[inventory.json](inventory.json)。CodeGraph使用explore及StockChanPreflightSpec的impact；图谱仅返回局部符号，随后补源码AST导入和全仓文本引用核查，确认当前股票排名仍消费G0中的两个函数。没有产品/API/前端消费者或跨子系统依赖调整。

## 保留清单

| 报告目录（均在reports下） | 明确意义 | 对应代码 |
| --- | --- | --- |
| index_probability_backtest_v1_20260908_approved | 固定训练/测试切分后，量价模型未证明方向增益 | statistics/index_probability_backtest.py |
| index_condition_statistics_v1_20260908 | 交叉条件样本不足，不能发布高概率结论 | statistics/index_condition_statistics.py |
| index_single_condition_v1_20260908 | 单条件方向未通过；风险相对常数基线的内部线索 | statistics/index_single_condition_backtest.py |
| index_risk_baseline_v1_20260908 | 风险模型未证明优于动态基线，限定上一轮线索 | statistics/index_risk_baseline_backtest.py |
| chan_theory_csi300_teaching_20260908 | 教学图例、结构与源码版本；M0还读取其source.json | chan/build_cases.py |
| chan_m0_csi300_20260909 | 日线首次可知账本校验、3个三买样本不足 | chan/run_m0.py、verify_m0.py |
| chan_minute_5y_20260909 | 五年30/60分钟基准；A的认证输入 | chan/run_minute.py |
| chan_minute_variant_a_20260909 | 单变量三买定义、585事件与评分；后续主要事实源 | chan/minute_variant_a.py |
| chan_minute_diagnostics_20260909 | 收益对少数大涨日期集中，高位失败案例 | chan/minute_diagnostics.py |
| chan_minute_background_f1_20260909 | 背景过滤局部避险、无法证明普遍有效 | chan/minute_background.py |
| chan_minute_structure_s1_20260909 | 上层状态未确认，不能直接当趋势过滤器 | chan/minute_structure.py |
| chan_minute_comparison_c1_20260909 | 与简单形态的对照；C2认证依赖，不是可删旧成绩 | chan/minute_comparison.py、verify_comparison.py |
| chan_minute_nonoverlap_c2_20260910 | 改善样本数量后仍无稳定次日增益 | chan/minute_nonoverlap.py |
| chan_minute_roundtrip_b0_20260910 | 18组自然退出样本不足；当前个股研究的指数窗口来源 | chan/minute_roundtrip.py |
| stock_chan_shsz_r1_source5_20260910 | 8月排名/50对50样本及2月、4月缺口，恢复研究所需 | chan/stock_chan_rank.py |

上述模块依赖的价格读取、Spec、事件账本、评分、验证、来源认证模块及测试一并保留。2026-09-09迁移清单仍是历史来源校验依据，字节不改；其中对已删除初次暂停报告的哈希是历史记录，不再表示文件仍存在。

## 删除／精简清单

| 对象 | 依据、问题与影响 | 处理 |
| --- | --- | --- |
| reports/index_probability_backtest_v1_20260908 | 只有训练前暂停说明和manifest，无预测；三条前收差异及批准口径已在原方案和正式续跑结果记录 | 删除2文件，3,655字节；原方案改指向保留结论，不留死链 |
| reports/stock_chan_index_windows_r1_20260910 | G0误将研究限定为指数成员；该前提已撤销，区间在B0和新排名结果中都有 | 删除6文件，20,857字节；在原方案留简短失误记录，不保留可执行旧门禁 |
| reports/stock_chan_shsz_r1_20260910 | 错用Silver30对账Gold30，产生假差异；没有排名或有效性结论 | 删除9文件，1,621,376字节；保留错误原因与正确源频度测试，不留重复来源清单 |
| chan/stock_chan_preflight.py | 当前排名仍用authenticate/select_windows，但G0的成员、市值、目录扫描及CLI已无用途 | 将两个函数原样收敛到stock_chan_reference.py，保留6项B0窗口配置；删除G0入口、门禁和仅G0用的读取器/配置 |
| tests/test_stock_chan_preflight.py | 旧成员门禁、G0样本SQL/范围测试已不对应当前研究 | 改为test_stock_chan_reference.py保留窗口/哈希反例；有用的读取白名单测试移到现用rank连接上 |

按文档治理分类，G0旧活动入口为G1级过时规则风险；错误首次排名产物为G1级误读风险；初次训练暂停重复引用为G2级维护噪音。用户已明确授权本轮清理，无需额外确认。代码移动只改变组织和废弃入口，不改算法、排名、股票池、资源参数或来源认证强度；配置删除仅影响已撤销G0，B0窗口配置消费者仍是当前rank及隔离测试。

删除采用移入本机废纸篓的可恢复方式，不清空废纸篓；旧代码/测试清理前另保留同一恢复目录内副本。恢复目录：`/Users/congming/.Trash/goldenshare-research-cleanup-20260910-CShEmk`。其中三个同名子目录对应原reports目录，两个Python文件对应删除的G0源码与测试。未跟踪文件不假设可以从Git恢复；如需恢复，先核对inventory哈希及现有路径，不能覆盖后来新增的内容。

## 实际验收与未执行项

详细检查结果见[verification.json](verification.json)，清理前逐文件证据见[inventory.json](inventory.json)。

- 三组报告共17文件、1,645,888字节（约1.57MiB）移入废纸篓；移动前后精确文件集合、大小及SHA256一致。两个旧代码/测试副本也与清理前哈希一致。
- 保留15组、299个报告文件。其中298个文件字节不变，仅当前个股报告的人工说明替换失效链接；数值不变，该说明不属于计算manifest覆盖项。所有保留的计算manifest及其229项产物认证通过；无此manifest字段的教学/统计文件仍按清理前逐文件哈希核对。
- authenticate/select_windows函数AST完全一致，六个B0窗口默认值不变；stock_chan_rank.py可通过仅还原一处导入得到清理前的精确字节哈希。其他计算Python源码不变，旧迁移清单不变。
- 当前排名源码哈希因导入改名而改变，旧排名manifest仍保留运行当时的旧哈希。新旧哈希及等价检查结果记录于verification，不重签旧结果、不新增哈希豁免，也不声称当前文件与旧manifest逐字节相同。
- 用已有报告完成B0的22项认证、A的32项认证与585事件账本核对、原分钟基准的32项认证；三个窗口与已保存个股窗口逐字段一致。这里只复核仓库内保存证据，没有读取行情源或重跑缠论引擎。
- 285项研究及架构护栏测试通过（10.58秒）。比之前288项少3项废弃G0专属测试；有用的5项认证/选窗测试保留，读取白名单反例移到当前排名连接，未删除对应安全保障。
- 两个当前个股模块及两个测试文件Ruff通过；当前排名CLI帮助通过；375个Markdown文件链接存在；文档完整性检查、git diff --check通过。CodeGraph sync/status报告最新，未将其局部图谱当作全量依赖证明。

同步文档仅研究README、原概率方案、个股方案、当前个股报告说明和主索引的一条状态导航；没有改动其他任务的文档内容，没有架构边界、API、依赖矩阵或生产运行时变更。

不执行：行情读取、数据修复、源接口请求、Dagster操作、缠论回放或新回测；不安装、不提交、不部署。个股研究继续暂停，数据修复后需重新验证当前源文件，旧缺口报告是当时证据，不代表修复后的现状。
