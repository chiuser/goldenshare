# 新闻快讯冷热分层 LLD v1

状态：代码开发完成，待生产迁移授权
更新时间：2026-08-02
关联专项：[生产 PostgreSQL 存储空间优化治理专项 v1](/Users/congming/github/goldenshare/docs/governance/prod-postgresql-storage-space-optimization-program-v1.md)

## 1. 目标与边界

只改新闻快讯 `raw_tushare.news` 的物理存储模型：2022 至 2025 年数据与索引位于 `gs_raw_cold_hdd`，2026 年及以后位于 SSD 默认 tablespace。`core_serving_light.news`、财富端市场新闻/个股新闻 API、新闻维护请求参数、分页、来源扇出和 TaskRun 语义不变。

不处理 `major_news`、`cctv_news`、其他新闻数据集、Ops、Biz API、前端和数据源请求。

## 2. 已核实的实现事实

1. `raw_tushare.news` 当前是未分区表，写入冲突键为 `row_key_hash`。
2. `_news_row_transform` 的 hash 输入包含 `src`、`news_time`、标题、正文、频道和评分；同一条源记录重复拉取会得到同一 hash。
3. `row_key_hash` 是实际服务标识，`id` 没有代码、view、Biz 查询或外键消费者。
4. 当前发布脚本会执行 `goldenshare init-db`，其语义是 `alembic upgrade head`。因此任何大数据复制或表名切换都不能放进普通 Alembic `upgrade()`。
5. 新闻快讯每 30 分钟维护一次，最终切换只能在新闻快讯写入暂停后执行。

## 3. 最终数据模型

```sql
CREATE TABLE raw_tushare.news (
    src varchar(32) NOT NULL,
    news_time timestamptz NOT NULL,
    title text,
    content text,
    channels text,
    score text,
    row_key_hash varchar(64) NOT NULL,
    api_name varchar(32) NOT NULL DEFAULT 'news',
    fetched_at timestamptz NOT NULL DEFAULT now(),
    raw_payload text,
    CONSTRAINT pk_raw_tushare_news PRIMARY KEY (news_time, row_key_hash)
) PARTITION BY RANGE (news_time);
```

| 年份分区 | tablespace | 目的 |
| --- | --- | --- |
| `news_p2022` 至 `news_p2025` | `gs_raw_cold_hdd` | 冷历史 |
| `news_p2026` 至 `news_p2030` | `pg_default` | 当前与未来热数据，避免跨年出现无分区可写 |

每个叶分区必须有：主键 `(news_time, row_key_hash)`、`(news_time DESC)` 和 `(src, news_time DESC)`。历史叶分区的 heap 与全部索引必须位于 HDD。

`RawNews` 去掉 `id`，以 `(news_time, row_key_hash)` 表达实际行标识；`DatasetDefinition.storage.conflict_columns` 同步改为该顺序。`RawNewsDAO` 的现有通用 bulk upsert 继续负责 `ON CONFLICT`，不新增业务分支。

## 4. 实现设计

### 4.1 Alembic 只预建空目标

新增 revision 接当前真实 head `20260801_000120`，只做以下安全动作：

1. 创建 `raw_tushare.news_partitioned_stage` 分区父表和 2022 至 2030 年叶分区。
2. 为所有叶分区创建最终主键与两个查询索引；2022 至 2025 年的表和索引迁到 `gs_raw_cold_hdd`。
3. 不读取、不复制、不删除 `raw_tushare.news` 的任意行；不改 `core_serving_light.news`。

若目标 stage 已存在且结构不符合最终模型，migration 必须失败，不能静默复用错误结构。`downgrade()` 不删除 stage 或业务数据，直接拒绝执行，防止误删已复制的数据。

### 4.2 一次性迁移 CLI

新增 `goldenshare migrate-news-cold-storage`，实现放在 `src/foundation/services/migration/news_cold_storage/`，只用于本次迁移，不进入日常 ingestion 主链。

| 子命令 | 默认行为 | `--apply` 后行为 |
| --- | --- | --- |
| `prepare` | 展示 stage、分区、tablespace 与索引预检 | 校验 stage 已由 Alembic 正确创建 |
| `copy` | 展示源/目标按年行数与 copy 起点 | 将旧表全量 upsert 到 stage，并输出数据库时间 `copy_started_at` |
| `verify` | 展示源/目标总行数、按年行数、时间边界和缺失键数量 | 只读，无额外写入 |
| `cutover` | 展示最终切换门禁 | 在新闻写入暂停后锁表、复制 `fetched_at >= copy_started_at` 的尾部变化、验证、替换 view/表名并删除旧表 |

`cutover` 必须同时要求 `--apply`、`--copy-started-at` 和 `--drop-retired-table`。没有这三个显式参数时只能预览，禁止锁表、改名或删除。

复制语义固定为：

```sql
INSERT INTO raw_tushare.news_partitioned_stage (...)
SELECT ... FROM raw_tushare.news
ON CONFLICT (news_time, row_key_hash) DO UPDATE SET ...;
```

尾部复制使用 `fetched_at >= copy_started_at`。原因是当前 upsert 会刷新该字段；这样全量复制开始后新增或重新获取的新闻都会在最终锁表阶段覆盖到 stage，不需要双写或额外状态表。

### 4.3 最终切换事务

`cutover --apply` 在单一数据库事务中执行：

1. 设置 `lock_timeout='15s'`，对旧 `raw_tushare.news` 获取 `ACCESS EXCLUSIVE` 锁；拿不到锁立即失败，不等待、不杀会话。
2. 执行尾部复制。
3. 校验旧表和 stage 的总行数、逐年行数、最早/最晚 `news_time`，并做双向缺失 `(news_time, row_key_hash)` 检查；任一不一致即回滚。
4. 将旧表改名为 `news_retired`，将 stage 改名为 `news`。
5. `CREATE OR REPLACE VIEW core_serving_light.news` 指向新的 `raw_tushare.news`。
6. 删除 `news_retired`，提交事务。

切换后不存在旧表、双写或兼容 view。任何异常都会回滚整个事务，旧表和旧 view 保持不变。

## 5. 文件级改动

| 文件 | 改动 |
| --- | --- |
| `src/foundation/models/raw/raw_news.py` | 去掉代理 `id`，声明复合行标识；保留两个查询索引定义 |
| `src/foundation/datasets/definitions/news.py` | `news` conflict columns 改为 `(news_time, row_key_hash)` |
| `src/foundation/dao/news_dao.py` | 不改行为；仅通过测试证明复合冲突键不会更新键字段 |
| `src/foundation/services/migration/news_cold_storage/**` | stage 校验、全量复制、只读验证、受控最终切换 |
| `src/cli.py` | 注册显式迁移命令，不接入发布、worker 或 scheduler |
| `alembic/versions/20260802_000121_prepare_news_cold_storage.py` | 只预建空 stage 分区与索引 |
| `tests/test_news_dao.py` 等定向测试 | 验证模型、Definition、DAO、服务 SQL 和 CLI 参数门禁 |

## 6. 测试与验收

1. 模型测试：`RawNews` 不再有 `id`，主键顺序是 `news_time,row_key_hash`。
2. Definition/DAO 测试：news 写入使用复合冲突键；重复行更新非键字段，不更新两个键字段。
3. Alembic 静态测试：revision 接真实 head；只创建 stage；不包含 `INSERT INTO raw_tushare.news_partitioned_stage ... SELECT`、`DROP TABLE raw_tushare.news` 或 view 切换。
4. 迁移服务测试：没有 `--apply` 绝不执行写 SQL；cutover 缺任一显式确认参数必失败；15 秒锁超时、计数不一致或缺失键必回滚。
5. CLI 测试：子命令参数映射正确，默认 preview，不自动执行 copy/cutover。
6. 生产执行后：历史叶分区和索引都在 HDD；2026 至 2030 年分区都在 SSD；`news.maintain` 最小真实任务、`core_serving_light.news`、市场新闻 API、个股新闻 API 均正常。

## 7. 生产执行顺序

1. 完成并提交本 LLD 对应代码，但不自动发布。
2. 新维护窗口内暂停新闻快讯自动与人工写入，等待在途 TaskRun 清零。
3. 在新闻快讯自动与人工写入仍暂停、在途 TaskRun 已清零的前提下，使用标准部署脚本发布新代码；普通 Alembic 只预建空 stage。
4. 新 worker 可继续处理其他数据集工作；新闻快讯仍保持暂停。
5. 使用 CLI 依次执行 `prepare`、`copy --apply`、`verify`；全量复制可在更长的计划窗口内进行。
6. 最终短窗口执行 `cutover --apply --copy-started-at ... --drop-retired-table`，再通过部署脚本以 `--skip-migration` 重启服务，最后恢复 `news.maintain`。

新代码的复合冲突键对旧单表不存在可用约束，因此第 3 步的硬门禁是新闻快讯写入必须已暂停，且没有在途新闻 TaskRun。满足该门禁后可以使用标准部署脚本：新 worker 不会领取新闻快讯写入，其他数据集不受影响。

## 8. 删除门禁

生产切换验收结束后，必须删除本次专用 `news_cold_storage` CLI/service 及其测试，并把本文更新为最终运行结构；保留最终表模型、Definition 与运行文档。不得让一次性迁移工具长期成为系统能力。

## 9. 开发完成记录

本轮已完成模型、Definition、空 stage Alembic、受控迁移 CLI 与定向测试。已验证默认 CLI 路径不会执行复制、锁表、改名、view 切换或删除；普通 Alembic 只会创建空 stage。本机临时 PostgreSQL 空库已实际执行该 revision，确认 2022 至 2030 年分区、每叶三组索引、复合冲突写入与按年份落分区均正确；临时库已删除。

本轮未连接生产数据库执行迁移，也未执行 `copy --apply`、`cutover --apply`、停止任务或重启服务。生产迁移仍须按第 7 节逐项获得授权并在维护窗口执行。
