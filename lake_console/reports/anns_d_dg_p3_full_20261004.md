# DG 公告 P3 全量文件验收

2026-10-04。用户“明白了，继续推进吧，授权同意”批准样本验收后列明的全量五阶段命令。依据原[方案](../docs/design/dagster-anns-d-onboarding-plan-v1.md)、[LLD](../docs/design/dagster-anns-d-onboarding-low-level-design-v1.md)、[正式样本及授权命令](anns_d_dg_p3_sample_20261004.md)。P3完整退出：历史文件初始化及源/目标全量对账完成；P4事件与日常验收尚未执行。

本轮同步公告业务元数据，不下载PDF。来源为Prod只读公告表，逐月同快照服务端游标按10,000行批次读取；六字段 `ann_date,ts_code,name,title,url,rec_time` 原值进入DG Raw，不新增业务字段或过滤股票池。只丢完全相同的六字段记录，本次Prod已无完全重复。

## 最终物理事实

| 项目 | 验收结果 |
|---|---:|
| 已批准范围 | 2020-01-01..2026-09-30 |
| 月数 / 自然日文件数 | 81 / 2,465 |
| 源行数 / 写入行数 | 12,064,049 / 12,064,049 |
| 完全重复 / 拒绝 / 六字段双向集合差 | 0 / 0 / 0 |
| 缺失或额外日期文件 | 0 |
| 合法空日文件 | 83 |
| URL缺值仍保留 | 15 |
| rec_time缺值仍保留 | 4,039,070 |
| 正式Parquet大小 | 200,709,132字节 |
| 源capture shards数量 / 大小 | 1,249 / 258,488,034字节 |
| 月checkpoint / 日交付checkpoint promoted | 81 / 2,465 |

正式根 `/Volumes/datasource/data_lake/raw/tushare/anns_d/ann_date=YYYY-MM-DD/part-000.parquet`。83空日仍有六VARCHAR schema，不要求每天有业务行。冻结计划逐日源量等于月checkpoint交付源量；最终月级formal audit重新扫描全部源页和正式文件，核验schema/footer、日期分区、六字段集合、重复、源/目标前后指纹；全部81月passed。计划目标集合与实际文件集合完全一致，不以文件数量或行数相同替代集合对账。

此前2023-06的30个文件大小/SHA在全量执行后保持一致，完整capture被复用，没有重拉。本轮新增2,435日期文件、11,916,097行。样本已经证明候选和正式提交的SIGINT取消—同计划续跑—重放；全量没有取消或失败，也没有删除、备份或清表动作。

## 实测性能

| 阶段 | 秒 | 最大观测RSS MiB | 退出码 |
|---|---:|---:|---:|
| full-capture | 1895.556 | 324.6 | 0 |
| full-build | 57.689 | 889.0 | 0 |
| full-audit | 19.199 | 1756.6 | 0 |
| full-promote | 58.944 | 1608.9 | 0 |
| full-formal-audit | 18.007 | 1628.9 | 0 |

五阶段合计2,049.396秒，约34.2分钟，不含阶段之间人工审计/命令启动间隔。读取是主要耗时；2024-04峰值月543,563行capture约81.189秒。最大观测进程RSS1,841,954,816字节（约1.72GiB），来自月级集合审计。RSS是约50ms的ps采样观测值，不是瞬时绝对最大值，也不等同DuckDB内部memory_limit；本轮DuckDB2GB/2线程/20GB spill、月份200万/1800秒、SQL60秒、空间35GiB硬门禁未触发拒绝。结束剩余空间2,928,872,964,096字节。

capture/build/audit/promote/formal audit每个独立月份都形成可读回checkpoint，正式提交按日原子替换；没有覆盖全历史长事务。capture后先完成所有候选和绿色月审计，再执行promote；promote重新核验同计划审计与指纹，最后formal audit独立读回。所有阶段日志、命令及采样在/private/tmp/anns-d-dg-p3-20261004/，持久证明如下。

## 证据与计划对账

- [聚合验收及实际命令](anns_d_dg_p3_full_20261004.json)：范围、行数、缺值、阶段耗时、观测RSS、路径/命令、终态和余量。
- [冻结执行计划](anns_d_dg_p3_frozen_plan_20261004.json)：逐日日期/源行数、月上界id、目标初始基线、policy与SHA；只保存聚合操作证据，没有导出业务payload。
- [正式文件月级审计](anns_d_dg_p3_formal_audit_20261004.json)：81月六字段集合结论、2,465文件大小/SHA、缺值/拒绝计数和审计SHA；原临时报告身份保持不变。

计划SHA `dc0a03a404d9bdbcd7cdd34bc4da0e045f9f01a7b03d478ce6d0e29ea2e40d9b`。原方案R01–R08的六字段、完全重复、缺值、自然日、只读/有界/持久化与恢复已由开发156项回归、正式样本及此次全量文件读回覆盖；R11文件批准已落实，事件及启用批准仍分开；R09首次衔接补拉和R10正式事件失败补报/日常观测继续属于P4，不能以文件验收代替。

本轮没有修改Python主实现、配置、CLI/API或依赖矩阵；CodeGraph入口/影响面沿用P3开发审计，无新业务调用链。更新方案、LLD和本组报告，保留P0–P3历史记录与其它未提交工作。本轮沿用156项开发回归，未重复无变更的测试；文档完整性和git diff --check另行核验。

## 剩余工作与限制

Prod未写入，Tushare请求0，PDF下载0；正式Dagster instance未打开，runless materialization/check事件未补，schedule仍未启用。物理文件已完成不表示Dagster readiness已经验收。

下一步P4：开发独立事件补报入口，先只读计划与获批样本，再全量登记2,465 materialization及4,930 blocking check事实；补齐2026-10-01至启用前一天的衔接日期；完成日更新取消/续跑和正式观测验收后再启用08:00七日调度。事件和调度按原方案另获精确阶段授权，不能沿用本次文件授权。PDF下载器迁移和数据中心页面仍在后续阶段。
