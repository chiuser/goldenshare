# a2获准重测结果与结果记录逻辑回归

结论：本轮未完成七频验收，已停止且未自动第三次读源。首轮result.json及其说明保留；本轮原始结果为result-retry.json。

## 实际执行

- 通过Python启动前TMPDIR/TEMP/TMP、默认临时文件创建/删除和publication构造预检。
- 固定12个正式文件各读取一次用于准备；分钟来源仍为241/49/9/5行（304行），因子1行，7年度副本仅在临时Lake。
- 1分钟真实writer完成，生成241条当日replacement，临时年度输出919587B；写入耗时0.161285秒。
- 1分钟原check evaluator完成SQL并返回，耗时0.109377秒；随后在转换结果metadata时退出，未完成原四项pass/name断言，故不能补记为四项通过。后六频未执行，0/7频率完成整体验收，不能声称28项通过。
- 年度候选实际SHA一次，919587B；冻结输入另一次SHA7265B；提升后没有再做正式目标SHA。均仅临时文件。

## 错误及修正

通用报告normalize先按tuple遍历、再取.value；Dagster 1.13.26的TextMetadataValue采用record结构且禁止迭代，触发Iteration is not allowed异常。系统temp问题已经解决；此次为另一个执行脚本记录结果的错误，不能归因前复权生产逻辑。

已核对官方MetadataValue资料及本机metadata_value.py的.value属性，完成不读取Lake、不创建instance的纯对象回归：原顺序准确复现本次异常；修正为优先按MetadataValue取.value，再处理普通dict/list/tuple，自身返回自身的未支持复杂值明确拒绝，不吞异常。

回归17项通过，覆盖9种真实metadata类型、真实AssetCheckResult成功/失败两例、JSON写出读回及排他创建保护；结果见reporter-offline-validation.json。该回归不等于真实28检查已通过，修正后的报告转换尚未用于第三轮真实样本。

## 本轮成本和清理

- 启动至退出0.989秒，仅包含准备与1分钟，不是七频耗时。
- SQL/复制按全文件计费加实际SHA字节34,141,934B；含4MiB Fr预留后38,336,238B（36.560MiB）。不是物理磁盘IO。
- 累计Parquet及观测元数据写入2,361,930B（2.253MiB）；观测到的临时文件峰值2,335,384B。均在64/16/32MiB额度内。
- 进程RSS高水位223.09MiB，只代表已执行阶段；无spill0B，4线程，未改原memory_limit。
- 正式写入0，无instance/job/sensor/event；12源前后5字段stat不变。
- a1、a2及纯对象回归的三个独占临时目录均已清除并独立核对不存在；runner已返回exit code 1，离线回归返回0。没有保留Parquet、candidate、receipt、profile、脚本或sandbox，只有小型结果文件。

## 下一步

按已批准执行卡12.1“此次仍失败，不自动第三次读源”，此次停在报告。若继续，需同12文件及一次64MiB读取/16MiB临时写/32MiB空间额度的明确批准；正式读内容前必须同时完成环境和结果记录预检（真实MetadataValue/AssetCheckResult、成功/失败JSON写出读回），再逐频原writer和28项检查。保留所有失败证据，不扩大到其他证券/年份或正式补数。
