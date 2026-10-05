# 公告下载器 DG 来源迁移验收（2026-10-05）

方案提交：777d6901；依据为原公告 PDF 下载技术方案与 LLD 的 DG 修订。本轮完成迁移代码、隔离验收和正式 Raw 只读验收，代码尚未另行提交；DG 最小真实 PDF 下载待下一阶段。

## 已实现

- 原四个 CLI 参数不变；唯一来源是 DG 正式 Raw，移除 PG/Settings/id 游标和逐文件 has_artifact 查询，不访问 Tushare、PG、CH 或 DG 进程。
- 每日固定 fd，逐批 500 条、独立 DuckDB 连接、no-spill、两次指纹校验；正常原子替换可以继续旧版，原地修改或缺日/schema/分区/重复错误阻断；整个范围封存前零 HTTP。
- schema 1→2 事务升级，保留旧路径/hash/成功状态/冷却。六字段来源指纹与原 ISO 日期/代码/URL 的 PDF 身份分开；不重算旧 Prod 指纹，不清空账本，不增加备份。
- 源卷仅只读；输出门禁与既有 HTTP 控速、prepared/原子提升及恢复协议继续回归。

## 隔离验收

最终命令：

```bash
.venv/bin/python -B -m pytest tests/test_announcement_download_cli.py tests/test_announcement_download_dg.py \
  tests/architecture/test_subsystem_dependency_matrix.py \
  tests/architecture/test_platform_legacy_guardrails.py \
  tests/architecture/test_operations_legacy_guardrails.py -q
```

下载专项及架构回归共 129 项通过（113 项下载相关、16 项架构）；--help、compileall、文档完整性、26 个引用和 git diff --check 通过。覆盖原限速/文件协议、实际本机 HTTP redirect/retry 间隔、旧版五文件金样本升级后零请求、删除一份仅重下一份、升级中途回滚、旧程序拒绝 schema 2、早期 schema 1 缺可选计数列、未知版本/唯一约束缺失拒绝；独立进程枚举退出、prepared 两窗口、SIGINT 中断真实 DuckDB 查询和超时后线程回收。

隔离测试文件、台账与 PDF 都在临时目录。正式台账未打开/升级，用户已有 PDF 未删除；“旧文件复用”和“删除重下”当前只有隔离金样本证据，不能当作正式归档验收。

## 正式文件只读验收

使用真正 Source/DayReader 读取正式 Raw，完整落账只写 `/private/tmp` 的诊断 SQLite。基线来自 2026-10-04 冻结 bootstrap 计划；没有触发真实 CLI 下载、写入 Lake、补事件或改调度。[机器可读证据](anns_d_download_dg_reader_acceptance_20261005.json)保存实际文件 SHA、行数、请求/写入边界及实现文件 SHA。

| 日期 | 预期/实读行数 | 500 行批数 | 唯一文件任务 | 缺 URL | rec_time NULL | 读取与临时落账秒 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2026-09-26 | 0/0 | 0 | 0 | 0 | 0 | 1.116 |
| 2026-07-26 | 5/5 | 1 | 5 | 0 | 0 | 1.024 |
| 2023-06-09 | 7542/7542 | 16 | 4295 | 1 | 3221 | 4.732 |
| 2024-04-26 | 69138/69138 | 139 | 37732 | 0 | 26222 | 39.077 |

合计实读 76,685 条，schema/逐行日期/类型/六字段重复/版本前后 SHA/footers/台账数量/封存对账均通过。2023-06-09 的 155162.SH 两条记录，一条缺 URL、另一条有 URL，rec_time 均 NULL，全部保留来源映射；仅有 URL 的记录生成文件任务，符合当前完整 Raw 规则。

最大日量级为 69,138 条，实测 39.077 秒，其中台账 SQL 6.053 秒；单次 DuckDB 调用最大 0.006 秒，进度最大间隔 0.33 秒。全进程峰值 RSS 128.78 MiB，不等同于引擎 256 MiB 限制。合法空日、五条日、缺字段样本日和最大日均读回一致；这不是全历史重审或 DG 日常稳定性验收。

## 成本与下一步

临时台账 88,813,568 字节，约 1158.16 字节/源行，含来源映射、文件任务及索引。仅按本次样本粗推 12,064,773 行约需 13.0 GiB 台账空间；实际标题/URL 长度、唯一任务比例与保留轮次数会改变结果，不能据此承诺全范围成本。真实 CLI 还要核验输出卷，本次秒数不能直接当作 CLI 全历史耗时。

PDF 请求数/容量不是 Raw 行数；没有本轮网络传输样本，暂不估计全历史完成时间。下一阶段是最多五个唯一 URL 的 DG 来源真实归档、取消—续跑—零请求重放及 size/hash 读回，按阶段授权执行。先利用已有成功文件验证来源迁移复用，不能擅自删除正式成果。台账查询维护及数据中心页面继续后续独立设计。

边界/依赖矩阵未改变。CodeGraph explore/search、sync/status（up to date）及源码/SQL/测试消费者核验覆盖独立 CLI→Source→Ledger→Files/HTTP；没有更改 DatasetDefinition、DG 资产或前端/API。文档与差异检查不替代真实下载验收。
