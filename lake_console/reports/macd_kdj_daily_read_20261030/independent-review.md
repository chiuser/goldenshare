# MACD/KDJ日更读取修正独立实现审计

基准：已批准文档提交 `4a4a689e` 的业务方案第17节、写入LLD第19.3—19.11节。只读核对当前生产主模块git diff及两个测试文件，不访问正式Lake、instance、数据库或网络，不重复业务测试。

结论：未发现必须先修的实现阻断。此结论不代表正式运行、市场规模性能或DuckDB内部4GB异常已被实际验收。

核对的主文件SHA256：`615fb452a137107e0cc330963d6216e0e5a3995877144cbc0926e604b272a76f`。

| 要求 | 当前实现及核验 |
| --- | --- |
| 公式、参数、分段及版本原样 | `_insert_macd_kdj_segment_rows`（445行）、`_populate_macd_kdj_indicator_work_rows`（603行）及公式常量与基准AST相同。来源七列、DATE/TIMESTAMP及生产者拒绝NULL业务键/重复键的测试层次明确，未新增daily业务guard。 |
| 原state直接承接 | 新daily在900—930行先读取完整前日state一次；原exact previous wrapper保留。660行抽出的结果/state SQL与基准相同，保留停牌股票及旧last_trade_time。D到D+1独立有理数样本及原reader/API交接另有真实隔离证据。 |
| 两年内每股至多8根 | 792行聚合current-year至多8根；986—1008行只对不足8的活动代码读取原previous-year文件；1014—1022行合并后再次Top8。仅目标日行参与递推，无Y-2读取、固定天数裁剪或不足8拒绝。 |
| 64股全覆盖 | 893—898行按原路径组织稳定代码序列；933行分批不截断总股票。work只在931行创建一次，后续批次只覆盖/释放批内表；原segment联接保留按ts_code/freq，不跨股取seed。65股计算和一次完整bind分别有实际隔离测试。 |
| 来源身份及停止位置 | 763行比较dev/inode/size/mtime_ns/ctime_ns，不含atime。前state读前/读后、批次实际文件读前/读后、1082行bind前及1534行传入的提升前回调均核对；不stat未读取的前一年文件。受管写入仍依赖原pool及执行前串行配置，无脱管writer前提未被误报成跨源文件锁。 |
| 一次完整发布 | 1503行进入publication锁后才准备；1290行共用publish保持完整输入/targets单次bind、原候选校验和逐文件提升。1409行回调在promote前；默认None，原public writer不传入，repair/history未增加来源检查。 |
| 原repair/history不改道 | 原公开签名、上下文、prepare调用、work DDL和replacement SQL均完成AST对账。原publish仅分组SQL字符串缩进变化及新增可选回调，无其他语义变化；空结果flags、target-exists flag及scoped state分支保留。 |
| 不要求重刷已完成历史 | 年度/state writer AST未改；只替换传入目标日，非目标日直接复制旧业务行，其他年份及旧state文件不写。旧publication摘要比较未放宽，冲突只阻止该次续跑；无清历史事件、重建state、增加repair名单或变更下游合同代码。 |
| 测试未绕过待验收边界 | 新daily测试保留真实SQL与publication，隔离连接只改资源设置；独立字面数值为主，旧prepare结果只作补充。publication测试使用真实QFQ生产者、历史字面标记及真实故障注入，覆盖候选失败、replace两侧、旧输入冲突、源/前state变化和不误拦正常读取。 |

静态AST对账原文：`core-ast-review.json`。原消费者15项及跨两个现有环境的实际文件交接见 `existing-consumer-tests.json`、`handoff-producer.json`、`handoff-consumer.json`；认证/数据库依赖已隔离，不属于该交接验收。全部本轮测试Lake/staging/temp夹具已删除，报告及脚本待根代理归档后精确清理。

本次只复核上述实现及已有隔离证据。正式补数、原运行恢复、全市场性能、真实运行态和正式数据完整性均未在本次实施。
