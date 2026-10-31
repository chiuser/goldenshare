# 周／月线跨日恢复：修改、隔离验收及补数条件

日期：2026-10-31。对应原总方案§10.13、共享LLD§12.22及月线LLD§9.8。已按先补文档、复现旧错误、修改、隔离回归、源码对账的顺序完成；本轮未正式补数、未重载code location、未操作正式DG状态或重读正式行情。

## 结论及当前边界

本次日期冲突已修正，源码与LLD一致，未发现阻断本次29日恢复的代码遗漏。29日任务恢复收到30日来源时，Silver可按该文件的30日日期校验并完成；原任务身份和29日因子／日更进度保持原日，不冒记30日完成。已有成功源单元复用，28日已完成批次不用重跑；29/30日原job因复权变化确需更新的历史仍按原名单和范围处理，不能理解为禁止其必要历史刷新。

代码验收通过不等于已经正式启动。下步还需：提交／确认正式运行环境已加载本轮代码；仅核原29日pending和活动run；按原job实际范围核定Raw及自动通知两频Silver的历史读写预算并满足根AGENTS审批。应在触发Raw前确认预算，避免通知先启动未批准的历史读取。通过后恢复原29日月Raw `4d3edf1d-9958-44b0-bde1-8a9f0cce1965`，完成原检查及两频Silver，再推进30日原job。不能用被挡住的30日run代办29日，也不重放已完成日期或重做全局审计。

本报告的开发和隔离证据形成于提交前，现随本次修复提交保存，未推送、未安装依赖；验收JSON中git_committed_this_turn=false保留其当时状态。本报告不包含随后获准的重启、代码加载和预算核定，相关执行另记；不能据工作区修改推断已正式生效。启动前复用[既有定点证据](../recovery_20261031_preflight/README.md)，仅核实际变化，不重复扫描四项或全市场历史。

## 实际修改

只改两个运行文件中的四个函数：

- [Raw候选校验](../../../orchestrator/src/orchestrator/defs/io/stock_period_raw.py:886)在原candidate_facts查询里计算每文件max(end_date)，作为source_asof随原候选、提交CP和complete.files保存；原回执hash包含该值。原聚合已经读取end_date，本次不增加查询／COPY／摘要校验轮数。publish核对已有CP时同时核对source_asof，rename后CP失败仍沿原流程恢复。
- [Silver回执解析](../../../orchestrator/src/orchestrator/defs/stock_period_silver.py:380)保留原意图asof，对已校验的各文件日期分别计算执行范围；source_asof须规范且不晚于Raw原files_completed_at上海日期。完成时间只作上限，29意图／30来源／31完成不会误取31日。
- resolve_update_sources使用实际选中Raw交付文件的日期，进入原unit.asof、选行、原检查、物化及恢复；没有删除日期谓词。既有回执无新增字段时仍保留原上限，不读旧行情猜日期，不迁移旧回执或重算已完成Silver。

Parquet21列、类型、行值、复权算法、原SQL选行、Raw请求／续跑、job／sensor／check定义、日常水位、配置和Prod均未修改。[源码对账](source-reconciliation.json)核对四个实际改动函数，并以开始时指纹确认下载、daily水位、Silver合同与check模块未改。其他工作区已有改动保留，未纳入本轮修改或提交。

## 测试证据

- 修改前在真实临时文件和隔离Dagster链路上复现两项错误：候选缺少来源日期记录；29日原请求恢复得到30日数据后，真实Silver选行报silver_source_identity_date_or_partition_invalid。见[修复前XML压缩归档](old-regression.xml.gz)。压缩仅为保留pytest原始空白及回溯，不改XML内容；解压与原始字节一致，SHA256见验收清单。
- [相关回归](regression.xml)461项全部通过，165.559秒；最后源码复核补充旧通知选择较新Raw时的日期传递，[两项补测](successor-tests.xml)通过，2.379秒。合计463个不重复用例，其中本次新增28个；不重复累加中途14／26项运行。
- [实际执行命令](commands.json)保留工作目录、参数及结果；XML与指纹对应本次运行，没有把未执行的正式操作列为通过。
- Ruff本次三文件默认检查、src/tests致命错误基线均通过；新测试格式检查及文档完整性／差异检查通过。现有Dagster、Pydantic弃用／preview告警没有隐藏，不更改依赖。
- CodeGraph使用explore/callers核对read_completion、resolve_update_sources及update_inputs／recover_update_execution／evaluate_update_sensor；随后直接核对Raw生产者、选行、检查、物化、CP及恢复。结束执行codegraph sync和status，索引已更新。没有API／前端／Prod接口变更。

测试明确替代上游HTTP及来源时钟，实际使用Raw捕获、候选SQL、回执、临时Parquet、隔离事件存储、Silver两频job及原三检查；不是正式job或真实源再次验收。真实源合同与单股30日行为复用本日已保存证据，不重新调用Tushare。新测试阻止打开正式instance、HTTP和正式路径，结束核对没有被吞掉的禁止访问。

| LLD硬口径 | 本次证据 |
| --- | --- |
| 每文件来源日期来自实际候选、不加扫描轮次 | test_candidate_source_date_uses_one_existing_aggregate_and_survives_rename；原schema/facts两条查询不增加，CP失败后日期保留、冲突拒绝 |
| 原请求续跑，成功单元不重新下载 | test_cross_day_original_capture_then_two_silver_jobs；29日A成功、B空源，30日原ID恢复不再请求A周线，两个Silver实际job／检查通过，原基线回执及无关文件版本不变 |
| 不混用整批最大日或机器当天 | test_each_period_keeps_its_source_date_through_job_checks_and_resume周／月×正常／中断四项；三个周期分别29/29/30，31日完成仍按各周期日期，真实metadata和价格字面结果一致 |
| 真实错误继续拒绝 | 非法／未来来源日期六反例；Raw非法日历日期反例；无日期证明时两频真实select_period仍拒绝30来源／29上限；相关回归保留坏hash、路径、失败检查及错误绑定拒绝 |
| 较新Raw按实际文件日期 | test_old_notice_uses_the_selected_successor_file_source_date两频；29旧通知遇到30日任务的31日来源，选择实际新交付日期31，不取原29或新任务30 |
| 日常水位不冒进 | test_later_source_does_not_advance_daily_factor_or_refresh_to_later_day；实际源观察可为30，factor_through和last_refresh仍29；原daily回归通过 |
| 中断与已完成历史保持 | Raw rename后CP失败恢复；两频Silver部分提交后继续原execution，首文件版本／日期不变，完整后同通知ack不重写；原bootstrap、history、来源变化恢复及元数据容量回归通过 |

## 清理和未覆盖项

[验收清单](validation.json)记录已删除本轮5个精确测试目录，共31,373个普通文件、53,615,463字节（约51.13MiB）。该数为删除前留存，不是峰值／累计IO。保留必要XML、指纹和对账，不复制测试数据库或行情树，不删除正式成果、业务staging、共享依赖和历史证据。

本轮正式行情／数据库读取0、正式写入0、源请求0、正式job/check/sensor/cursor操作0。未做正式盘性能试跑，没有验证正式部署或完成29/30日数据恢复。历史实际范围和预算尚未执行前核定；这些是下一阶段操作前置，不是尚未修完的代码项。
