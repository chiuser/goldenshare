# 数据中心 DC5 本机验收记录

日期：2026-10-07。DC4 已提交 `b5534947`，未推送。本次按用户“提交修改，然后进入DC5”的授权执行 LLD 正式台账、索引和独立小范围下载验收。对应[LLD](../wealth/docs/pages/data-center/data-center-announcements-low-level-design-v1.md) §20；原始计数、时间、请求和文件摘要见[机器证据](wealth_data_center_dc5_acceptance_20261007.json)。

## 实际结果

| 验收项 | 结果 |
| --- | --- |
| 正式归档身份 | datasource UUID `8C5A534D-EAE1-42A2-A7D5-D24DEB820E29`；固定归档 `/Volumes/datasource/announcements` |
| 正式台账升级 | 取得本机/外盘独占锁后 schema 1→3；升级约0.46秒，integrity_check=ok；未清空、备份或重拉 |
| 原事实保留 | runs=2、artifacts=34188、source_records=34188、run_artifacts=34188、cooldown=1；所有原字段的逐表摘要一致。34188是文件记录数，其中363成功、33825待处理，不能当作已下载文件数 |
| 正式身份绑定 | 按实际卷和固定根创建本机 web-archive.json，原台账位置不变 |
| 正式索引 | Application Support 中按实际 source_scope 初始化 schema 2；9/5—10/4共30日29619条，另索引7/26的5条；按请求日期建立，未扫描全历史 |
| 公司搜索 | 代码000001、名称平安银行、首字母PAYH均得到000001.SZ；stock_basic=5911、namechange=14229条来源事实经校验 |
| 正式筛选/分页 | 真实API：标题“年度报告”98条；已下载306、未下载29313，相加29619；每页最多50，未下载第587页13条，末页读取约0.09秒 |
| 原历史展示 | 两个原run和文件列表可读；无保存策略的历史任务不提供继续、失败重试或重新检查 |
| 独立真实归档 | `/Volumes/datasource/announcements/dc5-acceptance-20261007`，只处理7/26的5条源记录、5个文件 |
| 停止→继续 | 原run `c1a7160f40e544b88b0b044c7e79462e`；停止时处理2/5（成功1、注入失败1）、剩余3；继续保持runId并只完成原剩余3项 |
| 原失败精确重试 | 关联run `394fce6348e64303ad22fc1640d26ddb`只包含1个原失败key，真实下载成功；原failed=1保留，unresolved=0 |
| 幂等重放 | run `e796922f687e48d59811698bb2e4d28f`复用5/5，新增远程请求0；预览请求0 |
| 物理对账 | 5个文件全为succeeded，实际size/SHA-256全部matched；按公告日期/代码/标题命名；总计925599字节 |
| 限速与来源 | 实际源站GET共5次，全部200，最短前一请求结束至下一请求开始5.153秒；原六字段和URL未改，7/26 Raw指纹未变；进程RSS峰值约325MiB |
| 部署门禁 | 本机 `.env.web.local` 已设既有开关true，APP_ENV=local；Prod即使flag=true也强制关闭。未新增配置项 |

## 验收隔离与修正

真实下载使用生产 Source、Volume、Ledger、Supervisor、Files、Downloader 和 DNS 固定连接传输；只将归档身份端口绑定到上述独立目录，产品网页仍只允许固定默认目录。临时进程在第一次请求前注入一次 `FileFailed`，用于可重复验证原失败集合与手工重试；它不是源站自然故障，也没有伪造PDF或修改Raw。其余5次传输及重试成功内容均来自原始源站URL。

正式API使用实际公告App生命周期、路由、Biz/DAO及正式资源；仅将登录身份替换为验收身份，未访问认证数据库；无身份请求401。不将其描述为实际账号登录验收。本轮没有再次运行浏览器，页面和Figma交互证据仍由[DC4记录](wealth_data_center_dc4_acceptance_20261007.md)承载。

实际旧schema升级后，历史阻断任务的source_policy为空；此前RunQuery仅按schema/phase给出canRecheck=true，而Supervisor明确拒绝无策略任务。修正资格读取与执行前提一致，既有字段/API不变。新增schema1/2升级后的真实路由负例；有策略当前任务的检查正例继续通过。CodeGraph explore/impact覆盖执行/查询/迁移和消费者，补查DownloadPanel与Supervisor当前代码；sync/status完成。没有改变依赖矩阵或增加兼容实现。

## 验证命令

```bash
PYTHONPATH=tests .venv/bin/python -B -m pytest tests/web/test_wealth_data_center_api.py tests/web/test_wealth_data_center_downloads.py tests/test_announcement_archive_runtime.py -q
.venv/bin/python -B -m pytest tests/architecture/test_subsystem_dependency_matrix.py -q
.venv/bin/python -B scripts/check_docs_integrity.py
git diff --check
```

后端103项通过、依赖矩阵4项通过。已有临时HTTP测试需要本机监听权限，使用获准提权执行；未安装或升级依赖。未改前端代码，不重复DC4全量前端构建。所有验收线程和临时App均已关闭，未留下常驻Web服务。

## 保留事项与下一步

DC5本机归档能力验收通过。DG日常连续稳定性仍独立验收：预检Raw分区最晚2026-10-04，2026-10-05—07缺失；默认9/8—10/7查询实际返回503/DC_SOURCE_UNAVAILABLE，未把缺分区视为零行，也未裁短默认范围。context的sourceAvailability=ready只说明来源根可读，不能替代指定范围完整性；observedAnnDate=10/4明确展示索引截止日期。

可先查询已有完整范围。下一步待DG补齐缺失日期后再验默认范围和连续更新；本次不触发DG job/sensor/materialize、修改Raw/Prod、迁移其它归档、删除既有PDF或启动全量下载。

本机启用配置将在以 `.env.web.local` 启动Web后生效，沿用 README 的现有入口：

```bash
GOLDENSHARE_ENV_FILE=.env.web.local .venv/bin/python -m src.app.web.run
```

登录后访问 `/wealth/data-center`。验收独立目录有自己的台账，不并入默认归档历史；默认页面仍展示原正式归档，验收目录与PDF保留供审阅。
