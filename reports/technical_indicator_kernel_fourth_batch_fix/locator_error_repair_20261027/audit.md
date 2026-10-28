# 定位读取异常分类：修复及一次授权续跑完成

范围以原方案与LLD19.34为准。产品改动仍仅为两个来源文件中的原始读取/内存/关闭错误分类，不改计算公式、读取范围、复权、配置或API。本轮依据暂停证据先补原两文，再修测试夹具显式AS及_State计数恢复；没有扩展产品改动。

原3项未执行节点一次续跑3 passed（pytest 0.91秒，外层程序1.1647008331492543秒），真实calculate七次，含正常一项和原定六项错误路径。ArrowInvalid为SourceReadError；ArrowMemoryError及_inspect的MemoryError为ResourceLimitError；元数据和键Reader的关闭失败为ResourceCleanupError。六项均保留原始cause且没有成功结果；两个关闭失败在服务统一出口完成真实关闭。五项已有错误/取消/到期/KeyboardInterrupt/普通ValueError保持原对象。

资源断言核验每次调用的Reader、Arrow注册、临时表、输入流和唯一连接；七次关闭连接探针均被拒绝，准备连接由finally关闭，拥有的临时目录已删除。真实Parquet/Arrow/DuckDB保留，仅替代计时/停止及指定原始故障边界；不代表正式Lake或D4并发/内存/原生中断验收。

首次失败1输入/0定位/1SQL保存在failed_setup_01和原execution/日志，未重写。当前累计7输入/10定位/59SQL/真实Control0；全第四批累计22637/29063/399536，剩余12363/10937/600464。本地保护剩5/14/69；全程无自动重试、无旧通过组重跑、无长参考重建。

执行前已使用CodeGraph检查LakePriceLocator及来源元数据检查位置，并结合当前服务测试明确影响仅Foundation来源与对应测试；无App/Biz/API消费者合同变化。独立只读复核确认续跑guard、费用继承、错误cause和清理断言；原12份第四批证据、49份D3证据指纹未变。

D4固定执行表已统一两处文字：LLD18只沿17.1建议表安排，不新增正式来源或大容量运行；三个HTTP故障分别是独立单请求节点，汇总行不能作为三请求整体续跑。正常总量19000输入/80000定位/811150SQL；含一次明确授权的失败节点续跑及必要来源重建，上限26000/96000/979780，真实Control12、120秒。算术与两文/JSON一致，仍待review，未执行D4。

静态检查和最新程序累计耗时见acceptance.json及resume_final_static_checks_01.json。不安装、不升级、不接正式数据、不提交、不部署；保留无关工作区改动。
