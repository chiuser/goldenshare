# 五项独立审计问题的修复与验收

2026-10-28，dev-interface。开发基线88de377ca，原审计和失败证据继续保留；本文件记录后续修正，不覆盖原411项结果。

## 授权与文档审计

管理员要求先将第1、2项补入原LLD，独立复核1—5项方案/LLD一致，再按文档开发并完成测试。正式部署、状态修复、补数、sensor/cursor操作不在本轮。

依据：[总方案§10.8](../../docs/design/dagster-stock-weekly-alternate-source-raw-backfill-plan-v1.md#period-delivery-recovery-followup-plan)、[共享LLD§12.16](../../docs/design/dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#period-delivery-recovery-followup-345)、[月线LLD§9.4](../../docs/design/dagster-stock-monthly-raw-onboarding-low-level-design-v1.md#monthly-delivery-recovery-followup)。具体实施口径唯一见共享LLD。

编码前由三个分工独立审查核当前源码与三文档，发现并解决：主动history与daily的history模式不能混同；漏登记原manifest用原开始时间排序；局部确认不能顺便登记未登记的整批history；history不要求daily consumed；新增控制字段不进入原身份摘要；基础集合SQL不等于历史场景全部SQL。闭合原历史、合法前像、新上市及bootstrap等正常反例保留。CodeGraph status/impact和源码动态回调补核、Context7官方checks依据、文档完整性与diff检查完成后开工。

## 五项对账

当前状态：五项开发、独立复核及隔离验收已完成；最终固定版本528通过、0失败，2项既有PG实验按原条件跳过。正式资源操作为0。

| 项 | 硬口径 | 实现/直接验收范围 | 当前结果 |
| --- | --- | --- | --- |
| 1 | 精确证明原候选已成为目标后补CP，不重下/重算/重写；未知文件仍拒绝 | history.recover_moved_candidate→原publish→validate_registered_targets | 真实replace后/CP前中断从run_period恢复；同价/行数/版本保持，1次摘要，0重复源/COPY/replace。坏目标/摘要/前像拒绝，多频多个异常间隙0摘要/CP；已有CP不再hash |
| 2 | history在请求前登记，共享待办不被越过；原ID原scope恢复、不改daily水位 | ensure_history_pending、frozen_history_work、ordered_pending_work、daily/handoff/deliver_asset、ack | 真实SDK history资产及原生三check、跨日冻结scope通过；不同history/daily/handoff在源/因子/COPY前拒绝。无manifest/无daily/文件完成但范围未登记/phase后pending前中断均有反例；仅整批确认精确移除history |
| 3 | 补报和原生检查日期/范围规则一致，元数据不合法不补绿 | materialization_scope/validate_materialization_scope、纯元数据比较、readiness、Silver CLI/执行器/原生checks | 两频缺asof、非法/错unit日期、同版行数冲突、坏版本、已有CP后的坏Mat均0新业务事件；正常周中/月中、2014首周、旧周期、新旧unit/父identity/前像/继承及旧bootstrap首更保持 |
| 4 | 允许频率完整可补其原回执，局部不关闭整批/删除待办 | confirm.allowed_events_complete、replay、ack证明核验及周线op | week-only不访问month，混合历史/当前只补合法当前缺项，局部后全频仍核month；空范围/伪造整批/CP漂移/晚失败拒绝。补全历史链、截点、绑定、原始JSON及版本内容核验；单/多后继、closed及中断正常 |
| 5 | 旧行情读取前先核明确目标；索引不可信停止，不自动扫描全频 | raw._old_range_paths/assemble、run_period缓存及_record_ranges | 坏hash/缺登记/区间中间缺口/未知选中目标均0定位SQL/旧行读取/COPY；有效索引下旧-only、新上市、换码清旧及未选股保持。2/100元数据样本无未选路径glob/stat；纯period不把坏索引重新标可信 |

直接新增回归集中在test_stock_period_followup_history.py、test_stock_period_followup_silver.py、test_stock_period_partial_delivery.py；原Raw/Silver集成、交付与恢复、两个Raw sensor及月线definitions共同验证入口，未只测新helper。生产文件10份和直接修改/新增测试15份的固定指纹见[版本及总结果](followup_fixed_version.json)。

## 文档与独立复核

三份原文档统一使用总方案§10.8↔共享LLD§12.16↔月线§9.4；复核不仅看新增小节，还直接修正早期仍有效的相反条款：范围索引失败自动扫描、闭合快路误要求未允许频率、未闭合有CP就不查最新检查、共享状态表漏history登记、Silver SQL未注明每频。旧sensor“待开发/待启用/下一次初始化cursor”标明对应历史阶段，并指向原真实接线结果，避免后续重新初始化。

开发后独立复核又发现两处漏项并按原LLD补齐：files_complete但ranges_recorded未落盘的原history须先登记再恢复范围；ack不能只看正整数事件编号，历史证明须含完整后继/截点并对到真实控制记录。后者先加7条坏证明，修复前7条均失败，修复后全部拒绝；独立只读复核确认合法单段/多段链及closed快路不被误拦，没有留下需另行拍板的设计分歧。

CodeGraph status/impact辅助核本链入口、调用方、直接测试；动态回调按当前源码补核，开发后sync/status。共享SQL模块、SDK重执行接口、Prod/API/前端消费者未改，无新增definition/配置/schema/源参数；无需更新架构快照。Context7官方checks依据与本地1.13.26 SDK合同复用。

## 测试证据与边界

使用本项目既有.venv解释器、隔离Lake/staging/SDK实例及明确小型生产者；不设PYTHONPATH、不安装依赖。先必要定向，固定代码后一次必要周/月回归；失败、修正及复验分开保留，不以重复次数或合成metadata证明实际大文件正确性。

第3项开发前两频缺asof的2项失败来自当时真实pytest工具输出（2 failed、1.79秒，未指定JUnit，因此无红例XML）；原审计的独立producer脚本/JSON继续保留在audit_evidence，不伪造或重跑旧版补造历史记录。其余问题复用来源及代码指纹明确的原隔离失败证据，并补真实入口回归。

| 本轮 | 实际结果与依据 |
| --- | --- |
| 第一次固定版本合并回归 | 520项：505通过、13失败、2个PG opt-in跳过，128.97秒；[原红XML压缩归档](followup-fixed-regression.xml.gz)保留原始字节，生产10文件指纹与运行前完全相同 |
| 13项诊断/夹具校准 | [13项通过、0跳过](followup-fixture-recheck.xml)，2.86秒。原输入缺双频/factor交接事实、未走真实bootstrap确认/handoff或直接history assemble缺可信range；补足真实合同及独立字面事实，未放宽生产规则，原业务预期保持；[详细依据](followup-fixture-corrections.json) |
| 第4项证明完整性补验 | [修复前7失败](followup-proof-before.xml)；固定修复后[19项通过](followup-proof-after.xml)，16.91秒，加[3项通过](followup-proof-controls.xml)，2.73秒；这是22个不同定向例的两轮，非一次pytest |
| 第3项定向收尾 | [70项通过、0跳过](followup-silver-recheck.xml)，7.31秒；范围及原始轮次见[记录](followup-silver-results.json) |
| 最终固定版本合并回归 | [530项：528通过、0失败、2个PG opt-in跳过](followup-final-regression.xml)，136.39秒；生产10份/直接测试15份指纹均与运行前一致，不合并以上重叠次数作为最终通过数 |

最终回归使用全部test_stock_period_*.py、两个Raw sensor测试及月线definitions。DG_PERIOD_PG_VERIFY未启用，现有两个隔离PG实验明确未执行；本轮不重复原PG18.4证明，不把SQLite验收称为本轮PG验收。原SQL排序与SDK重执行接口没有修改，原411项及其PG证据继续作为对应旧范围历史记录。

全src/tests致命错误Ruff基线和本次25个Python文件默认Ruff通过；文档新锚点、链接及本任务diff另核。未通过更改断言或新增skip隐藏失败；2个PG opt-in仍按既有条件跳过，本轮未安排或启用该实验。

## 读取、写入及成本对账

- 第1项真实小文件恢复正常只读缺CP目标的一次摘要，CP已存在0摘要；多个异常间隙不扩读。一次再中断仍按原LLD≤2B预算，正式目标B须另核，开发授权不包含正式年度读取。
- 第2项仅在原daily.json保存/核同一history待办，0 runs目录扫描，不伪造daily水位或消费；真实SDK入口证明不会重新读取今天scope替换原身份。
- 第3项新scope/元数据比较0 SQL/0 stat/0行情内容；每频集合证据2 SQL，首次两频预取4 SQL，实际新增物化后按涉及频率批量读回，0逐文件fetch。2/100容量样本明确为metadata替身。
- 第4项单频当前完整证明基础3 SQL、两频4 SQL；历史有限窗口/截点/中间后继另计，未冒称历史总查询恒定。ack增加证明核验不新增DG查询/行情读取；真实两频共享后继manifest读1次、complete读0次、各committed读1次，保留线性stat。局部0新业务事件，只写明确原CP；混合场景仅当前合法缺项沿原回调写。
- 第5项不再通过全频旧键扫描定位。坏索引或未知目标在旧行情SQL/COPY前拒绝；正常只读本次明确目标。候选缓存保持原数据/哈希/归属验证，不重算、不重建坏索引。
- 上述是隔离计数/代码约束，未将临时文件保留字节当作实际读取量或RSS/峰值，也未拿小样本推算正式全市场预算。未做新性能实验。

正式资源操作为0；本轮未读取Tushare/Prod或正式行情、未加载code location、未运行正式job/check/传感器、未改正式状态。指定测试临时Lake/staging/SQLite及工作文件结束按精确路径清理，小型结果及失败证据保留，见[清理记录](followup_temp_cleanup.json)。本轮修改及证据随本次提交保存，提交号以Git记录为准；未推送。

本轮交付停在代码/隔离验收及文档对账，不执行§12.11正式旧待办收尾或§12.12补数。后续真正恢复仍须先核明确原ID/控制事实及实际历史读写范围，沿既有job/原日期继续，不重置cursor、不删除pending或重做bootstrap。

提交前检查发现首轮红XML中pytest堆栈自带行尾空格，现以gzip无损归档，解压字节与原SHA完全一致；未改变错误正文、测试结果或原始指纹。其余报告保持原格式。
