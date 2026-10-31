# 10月28日原月线任务恢复完成

本轮在10月29日执行，业务日期保持10月28日。管理员已明确批准原任务收尾及154个月/658周Silver、必要参考读取，含中断余项和收尾预算读2GiB、写1GiB、额外空间1GiB；未增加运行限制或改代码。

| 步骤 | 实际run | 结果 |
| --- | --- | --- |
| 原月Raw FROM_FAILURE | 08b25eaf-c4c7-491f-9f71-77455d9fda11 | 00:20:07—00:21:51，SUCCESS |
| 原events收尾入口 | 原业务执行ecd358…da7ae | 执行一次成功，events_complete、pending清零 |
| 原通知周Silver | de5acd12-5a5e-4fc1-834a-a1c3050fdaca | 00:22:24—00:24:11，658周期、2519597行、1974项检查完成 |
| 原通知月Silver | 5a20903d-1bf0-4e52-ad9b-0c52a0709800 | 00:24:50—00:25:22，154周期、595228行、462项检查完成 |

合计812份Silver、3114825行、2436项原检查通过；原两条通知均已被原sensor确认消费，两个cursor无pending。原1254份Raw属于28日19:31已生成批次，本轮复用，不重新下载/生成/替换。旧104911a4仍保留CANCELED，新恢复run的parent/root指向它。

当前2026-10月：Raw及Silver均5575个唯一代码，最新end_date=20261028、其中3364行end_date为28日；Silver来源版本等于Raw实际版本，两个最新物化均绑定本层当前文件，原三项检查各绑定相应新物化。原源端较早end_date的2211行保留，不能据此宣称每股都截至28日。月线本轮交付完成不代表29日新数据，也不代表28日独立周Raw日更已完成；daily.last_refresh.week仍27、month为28，factor_through为28，闭合周23日/月9月不提前改动。

Raw原检查在asset返回后才完成，因此原通知Silver自然启动与随后原events控制收尾可相邻发生；后者只确认原检查/补回执，不重算数据。四sensor状态仍RUNNING，未重置游标、调并发、加资源标签或重启服务。最终验收复用原生产者/原检查回执及逐文件stat，不读历史Parquet正文；只对当前月两小文件做一次收尾计数/日期统计。没有性能测试、包安装或全局审计。预算为设计/批准值，未把磁盘文件体积说成实测总IO。

独立只读复核通过。三份本轮辅助脚本已逐字归档为.py.txt后精确删除，正式文件、源、CP、receipt及业务staging保留。最终证据：[执行汇总](execution-result.json)、[完整回执对账](final-verified.json)、[当前月最终核验](current-month-final.json)、[原job最终状态](watch-05.json)、[精确清理](cleanup-result.json)。
