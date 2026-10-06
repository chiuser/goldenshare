# DG 公告下载器最小真实归档验收（2026-10-05）

状态：本轮授权范围通过。下载器代码已提交 `9f8faacf`；本报告及方案状态回写在该提交之后形成。

## 范围与方法

用户授权提交代码并继续推进，按原[技术方案](../docs/datasets/anns-d-pdf-download-technical-plan-v1.md)和[LLD §9、§15](../docs/datasets/anns-d-pdf-download-low-level-design-v1.md)执行。读取正式 DG Raw 2026-07-26 完整自然日：5 条六字段记录、5 个唯一 URL，全部为 static.cninfo.com.cn。来源 SHA-256 `83562daeb1e87b11dd70ab4dd3985df818ce7c411ff1fbf67bb3a86788330104`，与之前只读验收一致。源数据、日期范围和四个 CLI 参数均未更改。

真实 CLI main 完成双卷检查、日读取/落账/指纹对账、封存、真实 HTTP、文件 fsync/原子提交和台账状态写入。临时观察脚本只附加请求起止/响应记录及请求白名单/数量上限，不替换真实网络或产品链路。父进程在读取首份成功输出后发送 OS SIGINT。每次请求结束后的间隔参数为 5 秒。

默认归档当前已有其他批次的 34,188 条文件记录、34,188 条来源映射和 2 次运行，本轮只读检查后保持 schema 1，未执行该批次。旧版升级验收改用原本保留的独立五文件归档，不删除或清空其他成果：

- 旧归档：`/Volumes/datasource/announcements/m3-interrupt-acceptance-20261003`。
- 新验收归档：`/Volumes/datasource/announcements/dg-source-acceptance-20261005`，执行前目录及派生台账不存在。
- 仍按 `ann_date/ts_code/title.pdf` 组织；文件名、大小和 SHA-256 与旧验收成果一致。
- 两个归档的 SQLite 路径及原始运行/请求证据见[机器可读报告](anns_d_download_dg_pdf_acceptance_20261005.json)。台账仍位于本机 Application Support，不在 Lake 中。

## 结果

| 运行 | 退出码 / 终态 | 成功 | 有效跳过 | GET | 秒 |
| --- | --- | ---: | ---: | ---: | ---: |
| 旧归档复用 | 0 / completed | 0 | 5 | 0 | 3.318 |
| 首份后 SIGINT | 130 / cancelled | 1 | 0 | 1 | 2.838 |
| 同命令续跑 | 0 / completed | 4 | 1 | 4 | 22.787 |
| 再次同命令 | 0 / completed | 0 | 5 | 0 | 3.263 |

旧真实 schema 1→2 事务升级通过：5 条 artifacts 的全部字段原样保留，5 条旧来源映射及 3 次旧运行的既有字段保留；旧运行标记 prod_postgres，新 DG 来源另存 5 条映射，共用同一文件身份。第一次复用命令已成功、5 跳过/0 GET，但临时观察断言把日终态 completed 写成 complete，导致观察程序退出。原始日志保留，修正观察脚本后重复零请求验收；未修改下载器、未重置台账或删除文件。

各有效运行均为 5 条源记录、5 个唯一任务；footer=落账行数=5、日 completed、范围 enumeration_sealed=1，来源 scope/hash 与只读预检一致。取消时已完成日输入不回退，成功文件保留；续跑重新枚举并只请求剩余四份。四轮进度最大报告间隔 4.636 秒，ETA 仍明确暂无法估算。

本轮真实 GET 总数 5，全部 200/application/pdf，无重试、重定向或额外探测。请求结束至下一请求开始最短 5.119 秒，包含取消后重启间隔。5 份新增 PDF 合计 925,599 字节，Content-Length 与接收字节一致。旧五份及新五份共 10 次物理 size/hash 读回全部匹配台账；两个台账 integrity_check 均为 ok。取消响应耗时 0.349 秒。

## 边界与下一步

本轮只新增独立归档的五份 PDF，并升级独立旧验收台账。未删除已有 PDF、修改默认归档台账、备份/重建表、写 Prod/Lake、触发 DG job/sensor/event、安装依赖或批量下载。没有改业务子系统、API、DG 合同及依赖矩阵。实现前 CodeGraph 已覆盖 CLI→Source/SourceVolume→Ledger→Files/HTTP 和测试消费者；本轮不改产品代码。

129 项专项/架构测试及 76,685 条正式只读验证为代码提交前证据，本轮未重复跑测试。报告和原方案回写后检查文档完整性与 git diff --check。删除后重下载只有隔离测试证据，本轮没有物理删除；现场拔盘、多域名、大文件、全历史容量/耗时和 DG 连续日常稳定性仍未验证。

下一步按原顺序单独设计台账查询/维护能力，再做数据中心设计稿、API 与页面。本验收不自动授权大范围下载；指定日期和间隔后仍需估算台账空间、请求量和 PDF 容量。
