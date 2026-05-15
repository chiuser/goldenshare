# Local Lake Console 架构方案 v1

- 版本：v1
- 状态：已部分落地；`stk_mins` 正式 clean 基准已切到 `clean_next`，derived/research 后续必须基于 clean_next 重建；Kopia 集成恢复管理待继续收口；后端模型/API 契约已补目标态，代码待按契约收口
- 更新时间：2026-05-13
- 适用范围：本地移动 SSD 上的 Tushare Parquet Lake 管理台
- 目录目标：`lake_console/`

---

## 1. 背景

当前 Goldenshare 生产主系统已经收敛为：

```text
src/foundation
src/ops
src/biz
src/app
```

生产运营后台依赖远程 Postgres、TaskRun、Ops API、调度和状态快照。  
本地移动 SSD 数据湖的目标不同：

1. 只管理移动 SSD 上的 Tushare Parquet 文件。
2. 主要供本地研究、DuckDB 查询和量化计算使用。
3. 不需要生产 Ops 调度、用户体系、远程数据库或状态快照。
4. 不允许影响远程生产环境编译、部署和运行。

因此，本方案选择新增一个仓库根目录独立工程：

```text
lake_console/
```

它不是 `src/ops` 的子模块，也不是生产 `frontend` 的页面分支。

---

## 2. 总目标

`lake_console` 的目标是：

```text
本地移动硬盘 Tushare Lake 管理台
```

它负责：

1. 管理 `GOLDENSHARE_LAKE_ROOT` 指向的本地 Parquet Lake。
2. 基于磁盘文件事实展示数据集、分区、文件、大小、schema 和风险。
3. 支持 DuckDB sample 查询。
4. 支持后续 Tushare 数据同步到 Parquet。
5. 支持后续对 `stk_mins` 生成 90/120 分钟派生 Parquet。

它不负责：

1. 不承载生产 Ops 页面。
2. 不接生产 `/api/v1/ops/**`。
3. 不读写 `ops.task_run`、`ops.dataset_status_snapshot` 或任何已退场的 Ops 观测表。
4. 不参与远程服务器生产部署。
5. 不参与生产前端 build。
6. 不挂到 `src/app/web`。
7. 不把主实现写回 `src/platform` 或 `src/operations`。

---

## 3. 总体目录结构

建议结构：

```text
goldenshare/
  src/                         # 生产后端主系统
  frontend/                    # 生产/运营后台前端
  lake_console/                # 本地 Lake 管理台，独立工程
    AGENTS.md
    README.md

    backend/
      pyproject.toml 或 requirements.txt
      app/
        main.py
        api/
          health.py
          lake_status.py
          datasets.py
          partitions.py
          validate.py
          query.py
        catalog/
          tushare_stk_mins.py
        services/
          lake_root_service.py
          filesystem_scanner.py
          parquet_metadata_service.py
          duckdb_query_service.py
          manifest_service.py
          tushare_stk_mins_sync_service.py
          stk_mins_derived_service.py
        schemas/
          lake_status.py
          dataset_summary.py
          partition_summary.py
          validation.py
          query.py
        settings.py

    frontend/
      package.json
      vite.config.ts
      tsconfig.json
      index.html
      src/
        main.tsx
        app/
        pages/
        components/
        services/
        styles/
        mocks/
```

说明：

1. 后端、前端都放在 `lake_console/` 下。
2. 第一版可以复制必要的设计 token 或基础组件，但不能直接 import `frontend/src/**`。
3. 第一版建议使用轻量 Lake catalog，不直接依赖生产 `src/foundation/datasets`，避免生产依赖牵入本地工具。

---

## 4. 隔离规则

必须写入 `lake_console/AGENTS.md` 的硬规则：

1. `lake_console` 可以读取 `docs/frontend/**` 的设计规范。
2. `lake_console` 不允许 import `frontend/src/**`。
3. `lake_console` 不允许 import `src/ops/**`。
4. `lake_console` 不允许 import `src/app/**` 的生产运行入口。
5. `lake_console` 不允许依赖 `ops.task_run`、`ops.schedule`、`ops.dataset_status_snapshot` 或任何已退场的 Ops 观测表。
6. `lake_console` 默认不允许对远程 `goldenshare-db` 做任何读写操作；当前仅允许两种只读例外：
   - `prod-raw-db`：从 `raw_tushare` 白名单表导出源站字段；
   - `prod-core-db`：当前仅允许 `index_daily` 从 `core_serving.index_daily_serving` 读取，并映射回 Tushare 字段口径。
   不得通过远程数据库补充文件事实、任务状态或数据集状态。
7. `lake_console` 第一版不复用生产 TaskRun，不接生产 scheduler/worker。
8. 生产部署脚本默认忽略 `lake_console`。
9. CI/预检默认不跑 `lake_console`，除非显式执行本地 Lake Console 检查。
10. `lake_console` 必须通过环境变量指定移动盘路径：

```bash
GOLDENSHARE_LAKE_ROOT=/Volumes/TushareData/goldenshare-tushare-lake
```

10. 没有 `GOLDENSHARE_LAKE_ROOT` 时，后端不得默认写入仓库目录或用户 home 下的隐式路径。

---

## 5. 分阶段路线

总路线：

```text
先搞框架 -> 再做读 -> 再做写
```

但因为移动 SSD 初始为空，第一阶段需要保留一个最小写入闭环，否则无法验证只读页面。因此第一期实际顺序是：

```text
M1 框架隔离
M2 Lake Root 与只读扫描
M3 stk_mins 单股票单日最小写入闭环
M4 只读页面展示
M5 全市场写入与进度
M6 派生与 research 重排
M7 Kopia 集成恢复管理与前端恢复页
```

### M1：框架隔离

目标：

1. 新增 `lake_console/`。
2. 新增 `lake_console/AGENTS.md` 和 `README.md`。
3. 建立 `backend/` 与 `frontend/` 两个独立工程骨架。
4. 不接入生产 app，不接入生产 frontend。

验收：

1. `src/app`、`src/ops`、`frontend/src` 无任何 import `lake_console`。
2. 生产部署脚本不包含 `lake_console`。
3. 本地可以单独启动 lake console 后端健康检查。

### M2：Lake Root 与只读扫描

目标：

1. 后端读取 `GOLDENSHARE_LAKE_ROOT`。
2. 检查路径存在、是否可读写、磁盘剩余空间。
3. 扫描 Lake 目录是否已初始化。
4. 扫描 `manifest/`、`raw_tushare/`、`derived/`、`research/`、`_tmp/`。

页面展示：

1. Lake Root 当前路径。
2. 磁盘容量、剩余空间。
3. 是否初始化。
4. 是否存在 `_tmp` 残留。

验收：

1. 空移动 SSD 能显示“未初始化”。
2. 初始化后的空 lake 能显示基础目录。
3. 不访问生产 Postgres。

### M3：`stk_mins` 最小写入闭环

目标：

1. 先支持从 Tushare 拉取 `stock_basic`，同时生成正式 `raw_tushare` 维表和本地股票池文件。
2. 再支持从 Tushare 同步一个股票、一个频度、一个交易日。
3. 写入 Parquet 到移动 SSD。
4. 使用 `_tmp -> 校验 -> 替换正式分区`。
5. 写入 `manifest/sync_runs.jsonl`。

正式数据集路径：

```text
raw_tushare/stock_basic/current/part-000.parquet
```

本地股票池路径：

```text
manifest/security_universe/tushare_stock_basic.parquet
```

说明：

1. `lake_console` 不允许读取远程 `goldenshare-db`。
2. 全市场 `stk_mins` 同步必须读取本地股票池文件。
3. 如果本地股票池不存在，`sync-stk-mins` 必须失败并提示先执行 `sync-stock-basic`。
4. `stock_basic` 数据量较小，更新策略采用全量替换。
5. `raw_tushare/stock_basic/current` 是研究查询和 DuckDB join 使用的正式维表。
6. `manifest/security_universe/tushare_stock_basic.parquet` 是 `stk_mins --all-market` 的执行股票池快照，不作为研究查询主入口。

示例：

```bash
lake-console sync-stock-basic \
  --lake-root /Volumes/TushareData/goldenshare-tushare-lake

lake-console sync-stk-mins \
  --ts-code 600000.SH \
  --freq 30 \
  --trade-date 2026-04-24 \
  --lake-root /Volumes/TushareData/goldenshare-tushare-lake
```

短命令入口：

```bash
export PATH="$PWD/lake_console/bin:$PATH"
lake-console --help
```

输出目录：

```text
raw_tushare/stk_mins_by_date/freq=30/trade_date=2026-04-24/
```

验收：

1. `raw_tushare/stock_basic/current/part-000.parquet` 生成。
2. `manifest/security_universe/tushare_stock_basic.parquet` 生成。
3. `stk_mins` by_date Parquet 文件生成。
4. DuckDB 能 `read_parquet`。
5. 只读扫描能看到正式 `stock_basic` 数据集和 `stk_mins` 分区。

### M4：只读页面展示

目标：

1. 独立前端页面显示 Lake 总览。
2. 显示 `stk_mins` 数据集卡片。
3. 显示 `freq/trade_date` 分区树。
4. 显示文件数量、总大小、最早/最新分区、schema 摘要。
5. 显示风险项：空文件、tmp 残留、schema 不一致。

验收：

1. 页面只基于文件事实和 manifest，不依赖 Ops 状态表。
2. 页面可在本地独立访问。
3. 生产前端不出现 Lake Console 入口。

后续页面能力扩展、信息架构、交互密度与管理台 roadmap 见：

- [Local Lake 管理台升级路线图 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-console-management-roadmap-v1.md)

### M5：全市场写入与进度

目标：

1. 支持全市场 `ts_code` 扇出。
2. 支持多频度。
3. 控制 part 文件大小，避免小文件爆炸。
4. 展示当前股票、当前频度、当前分区、累计行数。
5. 中断后不破坏正式分区。
6. `sync-stk-mins-range` 的窗口策略从“按自然月/31 天切”收口到“按 freq 定交易日窗”。
7. quota exceeded 时，以“可恢复停机”语义收口，而不是只抛原始异常。

验收：

1. 单日单频全市场能跑完。
2. 中断后只留下 `_tmp`，正式数据不被污染。
3. 重新执行可以覆盖该分区。
4. `plan-sync` 或等价预估能力必须能展示股票数、各 freq 窗口数、总 unit 数、预估请求次数与预计配额天数。
5. 2025 全年 `1/5/15/30/60` 任务的计划请求数应从月窗口径的约 `330660` 次下降到按 freq 定窗口径的约 `71643` 次。

当前代码现实补充：

1. `plan-sync stk_mins` 已能同时输出历史月窗口径与现行按 `freq` 定交易日窗口径。
2. `sync-stk-mins-range` 的真实执行已切到按 `freq` 定交易日窗。
3. 命中日配额时，任务会以 `quota_exhausted` 收口，并写入 checkpoint 与 sync run 记录。
4. 自动从 checkpoint 恢复尚未实现，当前恢复方式仍为次日重跑同一条命令。

### M6：派生与 research 重排

目标：

1. 从 `research/stk_mins_by_date_clean_next` 的 `30min` 生成 `90min`。
2. 从 `research/stk_mins_by_date_clean_next` 的 `60min` 生成 `120min`。
3. 写入 `derived/stk_mins_by_date`。
4. 从 `clean_next` 与 `derived` 重排生成 `research/stk_mins_by_symbol_month`。
5. 为 `index_mins` 增加 `research/index_mins_by_symbol_month`。
6. `index_mins` 的 `90/120min` derived 层已落地。

验收：

1. `90/120` 与 clean 分钟线字段一致。
2. DuckDB 可直接读取派生数据。
3. 单股长周期回测优先读 research 层。
4. `index_mins` research 只从正式 raw 层重排，不从远程源直接重建。

前端展示要求：

1. 增加 Lake 分层概览，明确 `raw_tushare`、`derived`、`research` 的语义、来源和推荐用途。
2. `raw_tushare` 展示为原始接口落盘层，适合单日全市场横截面查询。
3. `derived` 展示为本地派生周期层，适合 90/120 分钟线等本地计算结果。
4. `research` 展示为研究查询优化层，适合单股长周期回测和少数股票相似性分析。
5. 分区列表按 layer 分组展示，避免用户把三层数据混用。

同步中心专项补充：

1. `stk_mins` 从 raw 到 clean_next、90/120 派生、research by month 的维护链路不应做成黑盒一键命令。
2. 后续应在 Sync Center 中以 `stk_mins_sync` 专项 profile 展示为阶段化流水线。
3. 每个阶段必须由后端返回完整状态、结果、问题和下一步动作，前端只展示，不拼接事实字段。
4. clean_next 与 derived 完成后默认设置人工确认点，运营确认后再继续后续写入。
5. 详细方案见 [Local Lake 股票分钟线同步中心可视化流水线方案 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-stk-mins-sync-center-pipeline-plan-v1.md)。

### M7：Kopia 集成恢复管理与前端恢复页

目标：

1. 使用 Kopia 作为底层 snapshot / pin / restore 引擎。
2. 为 Lake 前端增加 Recovery / Write Safety 页面，能查看 repository、snapshot、pin 与 restore 命令。
3. Recovery 页第一期只做只读可视化与命令辅助，不做一键恢复。
4. 后续如需人工操作审计，只补轻量 action log，不重建自研 recovery 主账本。

详细方案见：

- [Local Lake Kopia 集成恢复管理方案 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-write-recovery-management-plan-v1.md)
- [Local Lake 管理台升级路线图 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-console-management-roadmap-v1.md)
- [Local Lake 页面演进边界卡 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-console-page-evolution-boundary-card-v1.md)
- [Local Lake Recovery / Write Safety 页面交互设计 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-console-recovery-write-safety-page-design-v1.md)
- [Local Lake Recovery 最小 API 设计 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-recovery-api-minimal-design-v1.md)

验收：

1. 前端能看到当前 Kopia repository 状态。
2. 前端能看到全湖 baseline snapshot 与 pin。
3. 前端能按 dataset/path/scope 查询 snapshots。
4. 详情抽屉能生成 restore 命令预览。

### M6 补充：什么是 research 重排

`research 重排` 是把已经写好的 by_date 数据，重新整理成更适合研究查询的 by_symbol_month 数据。

它不是重新向 Tushare 请求数据，也不是生成新的行情口径。

具体来说：

```text
输入：research/stk_mins_by_date_clean_next/freq=15/trade_date=2026-04-01..2026-04-30
输出：research/stk_mins_by_symbol_month/freq=15/trade_month=2026-04/bucket=00..31
```

重排前的数据适合：

1. 单日全市场扫描。
2. 按交易日补数。
3. 重跑某一天。

重排后的数据适合：

1. 单只股票长周期回测。
2. 几只股票跨月对比。
3. 相似性分析。

同一批行情数据会有两种物理组织方式：

```text
by_date          # 同步友好
by_symbol_month  # 研究查询友好
```

两者的数据内容应一致，只是文件分区和排序方式不同。

---

## 5.1 数据下载到写入的整体流程

`stk_mins` 的第一条写入链路先写 by_date 层。

流程：

```text
1. 用户选择 ts_code / freq / trade_date 或 date range
2. 单日命令按 ts_code x freq x trade_date 请求
3. 区间全市场命令先读取本地交易日历，再按 freq 对应的交易日窗切请求窗口
4. 按 ts_code x freq x request window 请求 Tushare
5. limit=8000, offset 递增分页
6. 将返回行按 trade_time 拆回 freq + trade_date 分区
7. 将返回行归一化为统一字段
8. 写入 by_date 临时分区
9. 校验临时分区 Parquet 可读、schema 正确、行数合理
10. 请求窗口完成后替换该窗口覆盖的正式 by_date 分区
11. 写 manifest/sync_runs.jsonl
12. 写 manifest/sync_checkpoints/stk_mins_range/run_id=*/checkpoint.jsonl
13. 后续按需从 by_date 生成 derived 和 research 层
```

关键约束：

```text
下载维度：ts_code x freq x request window
落盘维度：freq x trade_date
```

这样可以减少 Tushare 请求次数，同时不改变按交易日落盘和补数的文件事实模型。

旧的“每个交易日、每个频率、每个股票都请求一次”的方式只适合很小窗口；全市场长区间会把请求次数放大到：

```text
trade_date_count x freq_count x symbol_count
```

当前区间全市场命令改为：

```text
request_window_count x freq_count x symbol_count x page_count
```

历史实现里 `request_window_count` 默认约等于自然月数量；当前已收口为按 `freq` 定交易日窗，显著降低请求数。

### 5.1.1 `stk_mins` 下载窗口策略（已收口）

当前代码事实：

1. `sync-stk-mins-range` 已按本地交易日历构造 request window，不再强制按自然月或 `31` 天断窗。
2. request window 按 `freq` 对应的理论单日行数确定交易日跨度，目标是让单次请求行数接近但不超过 Tushare 分页阈值。
3. checkpoint 粒度仍为 `ts_code + freq + request window`，最终正式落盘仍是 `freq + trade_date` 分区。
4. `plan-sync stk_mins` 保留历史月窗口径与现行按 `freq` 定窗口径的对比，用于解释配额差异。

历史月窗口径在全年全市场 `1/5/15/30/60` 任务下，若股票池约为 `5511` 只，则 unit 数约为：

```text
12（月窗） x 5（freq） x 5511（股票） = 330660
```

该口径已在真实试跑中触发 `250000 次/天` 配额上限，说明月窗策略在 `stk_mins` 上不可持续。

已落地约束：

1. 去掉“按自然月强制断窗”。
2. 改为“按 freq 定交易日窗”。
3. 保持最终落盘仍是 `freq + trade_date` 分区。
4. 保持分页逻辑存在，但把分页降级为兜底，而不是常态。
5. 保持 checkpoint 粒度仍为 `ts_code + freq + request window`。

每交易日理论行数：

| freq | rows / trade_day |
|---|---:|
| `1min` | `241` |
| `5min` | `49` |
| `15min` | `17` |
| `30min` | `9` |
| `60min` | `5` |

目标窗口：

| freq | trade_days / window | rows / request（理论） |
|---|---:|---:|
| `1min` | `33` | `7953` |
| `5min` | `163` | `7987` |
| `15min` | `470` | `7990` |
| `30min` | `888` | `7992` |
| `60min` | `1600` | `8000` |

这样全年约 `245` 个交易日时，每只股票的请求数大约从：

```text
12（月） x 5（freq） = 60 次
```

下降为：

```text
8 + 2 + 1 + 1 + 1 = 13 次
```

全市场约：

```text
5511 x 13 = 71643 次
```

较月窗口径的 `330660` 次显著下降。

第一层正式写入路径：

```text
raw_tushare/stk_mins_by_date/freq=30/trade_date=2026-04-24/
```

也就是说，最先落盘的是：

```text
按 freq + trade_date 分区的 by_date Parquet
```

之后有两类后处理：

1. 派生周期：从 `clean_next` 的 `30min` by_date 生成 `90min` by_date，从 `clean_next` 的 `60min` by_date 生成 `120min` by_date。
2. research 重排：把 `clean_next` 与 `derived` by_date 数据按 `freq + trade_month + bucket` 重新组织，生成适合回测和相似性分析的 research 层。
3. `index_mins` 当前已进入第 2 类；`90/120min` 本地派生频率也已落地，但尚未进入 `research`。

最终形成：

```text
raw_tushare/stk_mins_by_date/            # Tushare 原始分钟线，按日组织
research/stk_mins_by_date_clean_next/    # 正式 clean 分钟线，按日组织
derived/stk_mins_by_date/                # 90/120 派生分钟线，按日组织
research/stk_mins_by_symbol_month/       # clean + 派生分钟线，按月和股票桶组织
research/index_mins_by_symbol_month/     # 指数分钟线研究层，按月和指数桶组织
```

注意：

1. `research` 层不是第二种文件格式，仍然是 Parquet。
2. 所谓“两种存储格式”更准确地说是“两种物理布局”：by_date 和 by_symbol_month。
3. by_date 负责同步、补数、单日全市场计算。
4. by_symbol_month 负责单股/少数股票的长周期研究查询。

---

## 6. Backend 设计

### 6.1 API

建议第一版 API：

| API | 方法 | 职责 |
|---|---|---|
| `/api/health` | GET | 本地后端健康检查 |
| `/api/lake/status` | GET | Lake Root、磁盘、初始化状态 |
| `/api/lake/datasets` | GET | 数据集文件事实列表 |
| `/api/lake/datasets/{dataset_key}` | GET | 数据集详情 |
| `/api/lake/partitions` | GET | 分区列表 |
| `/api/lake/validate` | POST | 扫描风险项 |
| `/api/lake/query/sample` | POST | DuckDB sample 查询 |

写入类 API 第一版可以先不暴露给前端，优先做 CLI 或后端命令：

| 命令/API | 职责 |
|---|---|
| `sync-stk-mins` | 同步单股票单日小窗口 |
| `sync-trade-cal` | 同步本地交易日历；支持全量分页快照或显式区间刷新，供区间分钟线同步使用 |
| `sync-stk-mins-range` | 基于本地交易日历按开市日循环同步分钟线 |
| `repair-index-mins-from-1m` | 用本地 `1 分钟` 正式分区修补 `index_mins` 的 `15/30/60` 分钟 source gap |
| `derive-index-mins` | 从正式 `30/60min` 分区派生 `index_mins` 的 `90/120min` |
| `derive-index-mins-range` | 按交易日历批量派生 `index_mins` 的 `90/120min` |
| `rebuild-stk-mins-research` | 重排 research 层 |
| `rebuild-index-mins-research` | 重排 `index_mins` research 层 |
| `derive-stk-mins` | 生成 90/120 |

### 6.2 Services

| 服务 | 职责 |
|---|---|
| `lake_root_service.py` | 解析和校验 `GOLDENSHARE_LAKE_ROOT` |
| `filesystem_scanner.py` | 扫描目录、文件、大小、mtime |
| `parquet_metadata_service.py` | 读取 Parquet schema、行数、row group 信息 |
| `duckdb_query_service.py` | 执行只读 sample 查询 |
| `manifest_service.py` | 读取/写入 manifest |
| `tushare_stock_basic_sync_service.py` | 从 Tushare 拉取 `stock_basic`，双写正式维表 `raw_tushare/stock_basic/current/part-000.parquet` 与执行股票池 `manifest/security_universe/tushare_stock_basic.parquet` |
| `tushare_stk_mins_sync_service.py` | `stk_mins` 到 by_date 的最小同步 |
| `index_mins_gap_repair_service.py` | 用本地 `1 分钟` 正式分区修补 `index_mins` 的 `15/30/60` 分钟 source gap |
| `stk_mins_derived_service.py` | 90/120 派生 |
| `index_mins_derived_service.py` | 从正式 `30/60min` 分区派生 `index_mins` 的 `90/120min` |
| `index_mins_research_service.py` | 只从正式 raw 层重排 `index_mins` research 月分区 |

### 6.3 Settings

必须显式配置：

```text
GOLDENSHARE_LAKE_ROOT
TUSHARE_TOKEN
```

可选配置：

```text
LAKE_CONSOLE_HOST=127.0.0.1
LAKE_CONSOLE_PORT=8010
LAKE_STK_MINS_BUCKET_COUNT=32
LAKE_STK_MINS_TARGET_PART_SIZE_MB=256
```

### 6.4 参数配置原则

#### `LAKE_STK_MINS_BUCKET_COUNT`

含义：`research/stk_mins_by_symbol_month` 重排时，按股票代码稳定哈希拆成多少个 bucket。

默认建议：

```text
32
```

配置考量：

| bucket 数 | 优点 | 缺点 | 适用情况 |
|---:|---|---|---|
| `16` | 文件更少，重排更简单 | 单个 bucket 更大，查少数股票时读入数据更多 | 数据量较小、频度较少 |
| `32` | 文件数量和查询裁剪比较均衡 | 比 16 多一倍目录 | 默认推荐 |
| `64` | 查少数股票时裁剪更细 | 文件/目录更多，小文件风险更高 | 10 年全频数据很大且主要做单股查询 |

第一版固定为 `32`。如果未来改为 `64`，必须提升 `layout_version`，不能在同一个 research 目录里混用不同 bucket 规则。

#### `LAKE_STK_MINS_TARGET_PART_SIZE_MB`

含义：写 Parquet 时希望每个 part 文件接近的目标大小。

默认建议：

```text
256
```

配置考量：

| 目标大小 | 优点 | 缺点 | 适用情况 |
|---:|---|---|---|
| `128MB` | 单文件较小，失败重写成本低 | 文件数量更多 | 移动盘较慢、希望更细粒度恢复 |
| `256MB` | 文件数量和读写效率比较均衡 | 默认推荐 | 通用场景 |
| `512MB` | 文件更少，扫描元数据更快 | 单文件写失败重试成本更高 | SSD 性能较好、数据量很大 |

本项目第一版默认 `256MB`。如果实际生成大量小文件，优先调大写入批次或 part size，而不是增加目录层级。

---

## 7. Frontend 设计

前端独立放在：

```text
lake_console/frontend/
```

原则：

1. 可以复制设计 token。
2. 不 import 生产 `frontend/src/**`。
3. 不使用生产 Ops 页面路由。
4. 页面文案明确“本地 Lake Console”，避免用户误以为是生产 Ops。

第一版页面：

1. Lake 总览页。
2. Dataset 列表页。
3. `stk_mins` 详情页。
4. 分区浏览抽屉。
5. 风险扫描结果区。
6. DuckDB sample 查询结果区。

---

## 8. 与 `stk_mins` Parquet 方案的关系

本架构文档定义 `lake_console` 工程边界和实施顺序。

`stk_mins` 的具体 Parquet 存储策略见：

- `docs/datasets/stk-mins-parquet-lake-plan-v1.md`

关系：

```text
local-lake-console-architecture-plan-v1.md  # 工程与边界
stk-mins-parquet-lake-plan-v1.md           # 数据集落盘策略
```

二者必须保持一致：

1. `lake_console` 的第一批写入目标是 `stk_mins`。
2. `stk_mins` 的 Lake 路径不进入生产 Ops。
3. 后续如新增其他数据集 Lake 支持，应先新增对应数据集 Lake policy，再接入 console。

---

## 9. 风险与防护

| 风险 | 防护 |
|---|---|
| 误接生产 Ops | `lake_console` 不 import `src/ops`，生产 app 不 import `lake_console` |
| 误写本机磁盘 | 没有 `GOLDENSHARE_LAKE_ROOT` 时禁止启动写入 |
| 写入中拔盘 | `_tmp` 临时目录 + 校验 + 替换正式分区 |
| 小文件过多 | 控制 part 文件大小，M5 全市场写入按 `part_rows` 分片 |
| `stk_mins` 月窗请求数过大 | 去掉自然月强制断窗，改为按 freq 定交易日窗，并提供配额预估 |
| manifest 与文件事实不一致 | 页面以文件事实为准，manifest 只做辅助 |
| DuckDB 查询误写 | sample 查询第一版只允许只读 SQL |
| 设计风格污染生产前端 | 复制 token，不 import 生产前端代码 |

---

## 9.1 `_tmp` 清理策略

`_tmp` 是写入安全机制的一部分，不是正式数据区。

清理规则：

1. 成功任务完成后，允许自动清理本次 `_tmp/{run_id}` 中已经被移动后的空目录和备份壳子。
2. 失败或中断任务的 `_tmp/{run_id}` 默认保留，用于排查当时写到哪个分区、写了多少文件。
3. 不允许在没有用户显式命令时删除非空历史 `_tmp/{run_id}`。
4. 提供命令：

```bash
lake-console clean-tmp --dry-run
lake-console clean-tmp --older-than-hours 24
```

命令语义：

1. `--dry-run` 只列出候选目录、大小和修改时间，不删除。
2. `--older-than-hours` 只删除超过指定小时数的 `_tmp/{run_id}`。
3. 不传 `--older-than-hours` 时禁止真实删除。
4. 清理范围只限 `GOLDENSHARE_LAKE_ROOT/_tmp` 下的一级 run 目录。

---

## 10. 开发门禁

每一阶段开始前必须确认：

1. 本轮是否只改 `lake_console/**` 和必要文档。
2. 是否没有改 `src/ops/**`、`src/app/**`、`frontend/src/**` 生产主链。
3. 是否没有修改生产部署脚本。
4. 是否没有把本地 Lake API 挂入生产 API。
5. 是否明确 `GOLDENSHARE_LAKE_ROOT`。

每一阶段完成后至少验证：

1. `python3 scripts/check_docs_integrity.py`，若改文档。
2. `lake_console` 自己的后端/前端最小测试，若已建立工程。
3. 生产代码无 import `lake_console`。

---

## 11. 后端模型/API 契约

本节是 `lake_console` 数据湖总览、数据集清单、节点详情和硬盘资产视图的正式技术契约。当前实现已切到 `/api/lake/overview`、`/api/lake/datasets`、`/api/lake/partitions`、`/api/lake/physical-assets`，旧的 `/api/datasets`、`/api/partitions`、`LakeLayerSummary`、`layer_summaries` 不再作为正式口径。

参考模型图：`docs/architecture/local-lake-console-data-model-map-v1.html`。

### 11.0 开发硬约束

| 规则 | 后端责任 | 前端责任 | 禁止行为 |
|---|---|---|---|
| 展示事实以后端为准 | 返回页面所需的完整事实字段、展示名、提示文案、排序权重和状态 | 按 response 直接展示 | 前端根据 `path/layer/layout` 猜业务含义 |
| 聚合计算在后端完成 | 计算全湖占用、已登记容量、漏账差异、节点覆盖范围、分区规模 | 展示后端聚合结果 | 前端把多个接口结果拼起来算总数或判断漏账 |
| 语义判断在后端完成 | 返回 `registered_state`、`asset_role`、`node_name`、`layer_name`、`partition_label` | 只根据语义字段控制布局和样式 | 前端通过目录名包含 `clean/derived/research` 判断资产类型 |
| 页面模型由 API 输出 | 为总览页、数据集列表、节点详情、硬盘资产列表提供稳定 response model | 不维护第二套事实模型 | 每个页面私下定义一套事实字段 |

### 11.1 目标对象关系

核心关系：

```text
Dataset 数据集
  -> Node 内容节点
    -> Partition 分区

PhysicalAsset 硬盘资产
  -> 可关联到 Dataset/Node，也可以是未登记资产或治理目录
```

`Layer` 只表示湖内大层级，例如 `raw_tushare`、`manifest`、`derived`、`research`。`Dataset` 与 `Layer` 不直接建模；它们通过 `Node` 间接关联。

### 11.2 Catalog 定义对象

#### `LakeLayerDefinition`

全局大层级定义，只保存层级本身，不保存路径和扫描规则。

| 字段 | 类型 | 含义 |
|---|---|---|
| `layer` | string | 稳定枚举，如 `raw_tushare/manifest/derived/research` |
| `layer_name` | string | 中文展示名，如 `原始层` |
| `layer_order` | integer | 展示排序 |
| `description` | string | 层级说明 |

#### `LakeNodeDefinition`

数据集下的具体内容节点定义。路径、扫描规则、血缘和分区维度必须落在节点上。

| 字段 | 类型 | 含义 |
|---|---|---|
| `node_key` | string | 数据集内唯一节点 key，如 `clean_next_by_date` |
| `node_name` | string | 中文展示名 |
| `layer` | string | 所属湖内大层级 |
| `path` | string | 相对 Lake Root 的节点根路径 |
| `scan_profile` | string | 扫描规则 |
| `asset_role` | string | 资产角色，如 `source_raw/clean_baseline/local_derived/query_projection` |
| `source_node_keys` | string[] | 来源内容节点 key，用于表达血缘 |
| `partition_dimensions` | string[] | 该节点解析出的分区维度 |
| `recommended_usage` | string | 推荐使用方式 |
| `sort_order` | integer | 节点展示排序 |

#### `LakeDatasetDefinition`

数据集定义是 Catalog 中的一条业务资产登记。数据集拥有节点，不直接拥有路径型 layer。

| 字段 | 类型 | 含义 |
|---|---|---|
| `dataset_key` | string | 数据集 key |
| `display_name` | string | 中文展示名 |
| `source` | string | 数据来源口径 |
| `api_name` | string 或 null | 源接口名 |
| `source_doc_id` | string 或 null | 源文档编号 |
| `description` | string 或 null | 数据集说明 |
| `dataset_role` | string | 数据集角色 |
| `group_key` | string | 页面分组 |
| `supported_freqs` | integer[] | 支持频率 |
| `raw_freqs` | integer[] | 原始层频率 |
| `derived_freqs` | integer[] | 派生层频率 |
| `nodes` | `LakeNodeDefinition[]` | 内容节点定义 |
| `command_examples` | `LakeCommandExample[]` | 命令示例 |

### 11.3 扫描规则

`scan_profile` 是后端 scanner 的规则名。前端不得理解或解析目录结构。

| scan_profile | 目录形态 | 分区维度 | 示例 |
|---|---|---|---|
| `current_file` | 单文件当前版本 | 无 | `raw_tushare/stock_basic/current/part-000.parquet` |
| `manifest_file` | 单文件辅助清单 | 无 | `manifest/security_universe/tushare_stock_basic.parquet` |
| `trade_date` | 按交易日 | `trade_date` | `raw_tushare/daily/trade_date=2026-05-08` |
| `freq_trade_date` | 频率 + 交易日 | `freq/trade_date` | `raw_tushare/stk_mins_by_date/freq=30/trade_date=2026-04-24` |
| `freq_trade_month_bucket` | 频率 + 月份 + 分桶 | `freq/trade_month/bucket` | `research/stk_mins_by_symbol_month/freq=30/trade_month=2026-04/bucket=12` |
| `indicator_params_freq_trade_date` | 指标 + 参数 + 频率 + 交易日 | `indicator/params_key/freq/trade_date` | `derived/stk_mins_indicators_by_date/indicator=macd/params_key=12_26_9/freq=30/trade_date=2026-04-24` |
| `indicator_params_freq_trade_month_bucket` | 指标 + 参数 + 频率 + 月份 + 分桶 | `indicator/params_key/freq/trade_month/bucket` | `research/stk_mins_indicators_by_symbol_month/indicator=macd/params_key=12_26_9/freq=30/trade_month=2026-04/bucket=12` |

### 11.4 API 输出对象

#### `LakeDatasetSummary`

| 字段 | 类型 | 含义 |
|---|---|---|
| `dataset_key` | string | 数据集 key |
| `display_name` | string | 中文展示名 |
| `group_key` | string | 分组 key |
| `group_label` | string | 分组展示名 |
| `group_order` | integer | 分组排序 |
| `source` | string | 来源 key |
| `source_label` | string | 来源展示名 |
| `description` | string 或 null | 说明 |
| `dataset_role` | string | 角色 key |
| `dataset_role_label` | string | 角色展示名 |
| `node_summaries` | `LakeNodeSummary[]` | 节点摘要 |
| `total_bytes` | integer | 节点合计大小 |
| `file_count` | integer | 节点合计文件数 |
| `partition_count` | integer | 节点合计分区数 |
| `coverage_label` | string | 后端生成的覆盖范围展示 |
| `latest_modified_at` | string 或 null | 最近修改时间 |
| `health_status` | string | `ok/warning/error/empty` |
| `health_label` | string | 展示文案 |
| `risks` | `LakeRiskItem[]` | 数据集风险 |
| `sort_order` | integer | 数据集排序 |

#### `LakeNodeSummary`

| 字段 | 类型 | 含义 |
|---|---|---|
| `dataset_key` | string | 所属数据集 |
| `node_key` | string | 节点 key |
| `node_name` | string | 节点中文名 |
| `layer` | string | 大层级 key |
| `layer_name` | string | 大层级中文名 |
| `path` | string | 相对 Lake Root 路径 |
| `scan_profile` | string | 扫描规则 |
| `asset_role` | string | 资产角色 key |
| `asset_role_label` | string | 资产角色展示名 |
| `source_node_keys` | string[] | 来源节点 |
| `partition_dimensions` | string[] | 分区维度 |
| `partition_count` | integer | 分区数 |
| `file_count` | integer | 文件数 |
| `total_bytes` | integer | 大小 |
| `freqs` | integer[] | 频率 |
| `coverage_label` | string | 覆盖范围展示 |
| `latest_modified_at` | string 或 null | 最近修改时间 |
| `recommended_usage` | string | 推荐使用方式 |
| `registered_state` | string | `registered/missing_on_disk` |
| `risks` | `LakeRiskItem[]` | 节点风险 |

#### `LakePartitionSummary`

| 字段 | 类型 | 含义 |
|---|---|---|
| `dataset_key` | string | 数据集 key |
| `node_key` | string | 节点 key |
| `partition_values` | object | 结构化分区字段 |
| `partition_locator` | string | 稳定定位符，如 `freq=30/trade_date=2026-04-24` |
| `partition_label` | string | 展示文案，如 `30min · 2026-04-24` |
| `path` | string | 相对 Lake Root 路径 |
| `file_count` | integer | 文件数 |
| `total_bytes` | integer | 大小 |
| `row_count` | integer 或 null | 行数 |
| `modified_at` | string 或 null | 最近修改时间 |
| `risks` | `LakeRiskItem[]` | 分区风险 |

#### `LakePhysicalAssetSummary`

| 字段 | 类型 | 含义 |
|---|---|---|
| `path` | string | 相对 Lake Root 的路径 |
| `asset_type` | string | `directory/file` |
| `registered_state` | string | `registered/registered_container/unregistered/governance/ignored` |
| `dataset_key` | string 或 null | 关联数据集 |
| `node_key` | string 或 null | 关联节点 |
| `display_name` | string | 后端生成展示名 |
| `total_bytes` | integer | 大小 |
| `file_count` | integer | 文件数 |
| `dir_count` | integer | 子目录数 |
| `latest_modified_at` | string 或 null | 最近修改时间 |
| `risk_level` | string | `none/info/warning/error` |
| `risk_label` | string | 风险展示文案 |

#### `LakeOverviewResponse`

总览页必须优先消费该对象，不再由前端自行拼装首页事实。

| 字段 | 类型 | 含义 |
|---|---|---|
| `generated_at` | string | 后端生成时间 |
| `lake_root` | string | Lake Root |
| `summary_metrics` | object[] | 首页指标卡，包含 `key/label/value/hint/tone/sort_order` |
| `layer_groups` | object[] | 湖内层级展示，后端完成聚合 |
| `sync_method_groups` | object[] | 来源与同步方式展示，后端完成聚合 |
| `dataset_rows` | object[] | 数据集清单行，后端给出展示字段 |
| `physical_assets` | `LakePhysicalAssetSummary[]` | 全湖硬盘资产摘要 |
| `risks` | `LakeRiskItem[]` | 总览风险 |

### 11.5 正式 API

#### `GET /api/lake/overview`

用途：数据湖总览页专用聚合接口。

输入：无。后端读取 `GOLDENSHARE_LAKE_ROOT` 和 Catalog。

输出：`LakeOverviewResponse`。

要求：

1. 返回首页所需全部展示信息。
2. 后端完成全湖登记资产与硬盘资产差异计算。
3. 前端不得再自行从 datasets、partitions、status 多接口拼首页。

#### `GET /api/lake/datasets`

用途：数据集列表与数据集详情的基础事实接口。

查询参数：

| 参数 | 类型 | 必填 | 含义 |
|---|---|---:|---|
| `dataset_key` | string | 否 | 过滤数据集 |
| `node_key` | string | 否 | 过滤内容节点 |
| `layer` | string | 否 | 过滤大层级 |
| `registered_state` | string | 否 | 过滤登记状态 |

输出：

```json
{
  "items": []
}
```

其中 `items` 为 `LakeDatasetSummary[]`。

#### `GET /api/lake/partitions`

用途：按数据集和节点列出分区。

查询参数：

| 参数 | 类型 | 必填 | 含义 |
|---|---|---:|---|
| `dataset_key` | string | 是 | 数据集 key |
| `node_key` | string | 是 | 内容节点 key |
| `freq` | integer | 否 | 频率 |
| `trade_date_from` | date | 否 | 起始交易日 |
| `trade_date_to` | date | 否 | 结束交易日 |
| `trade_month` | string | 否 | 月份 |
| `bucket` | integer | 否 | 分桶 |
| `indicator` | string | 否 | 指标名 |
| `params_key` | string | 否 | 指标参数 key |

输出：

```json
{
  "items": []
}
```

其中 `items` 为 `LakePartitionSummary[]`。返回对象必须包含 `partition_values`、`partition_locator` 和 `partition_label`，不能让前端用散字段拼分区文案。

#### `GET /api/lake/physical-assets`

用途：展示真实硬盘资产，包括已登记节点、已登记节点父目录、未登记资产和治理目录；系统噪声文件只在显式过滤时返回。

查询参数：

| 参数 | 类型 | 必填 | 含义 |
|---|---|---:|---|
| `registered_state` | string | 否 | `registered/registered_container/unregistered/governance/ignored` |
| `path_prefix` | string | 否 | 路径前缀 |
| `asset_type` | string | 否 | `directory/file` |
| `limit` | integer | 否 | 默认 200 |
| `offset` | integer | 否 | 默认 0 |

输出：

```json
{
  "items": [],
  "total": 0,
  "limit": 200,
  "offset": 0
}
```

其中 `items` 为 `LakePhysicalAssetSummary[]`。

### 11.6 后置 API

以下 API 不进入本轮模型/API 收口第一批，除非后续有单独方案：

| API | 后置原因 |
|---|---|
| `GET /api/lake/nodes` | 第一批可由 datasets 内嵌 `node_summaries` 覆盖 |
| `GET /api/lake/files` | 文件级 schema/row_count 需要额外读取 parquet metadata，成本更高 |
| `POST /api/lake/validate` | 需要先稳定 Node 与 PhysicalAsset 模型 |
| `POST /api/lake/query/sample` | DuckDB sample 查询需单独安全方案 |

### 11.7 旧口径清理要求

| 旧口径 | 处理 |
|---|---|
| `LakeLayerDefinition.path/layout/recommended_usage` | 移入 `LakeNodeDefinition` |
| `LakeLayerSummary.source_layer` | 删除，血缘改用 `source_node_keys` |
| `LakeDatasetSummary.layer_summaries` | 改为 `node_summaries` |
| `LakePartitionSummary.layer/layout/freq/trade_date/trade_month/bucket` 作为主字段 | 改为 `node_key` + `partition_values` + `partition_locator` + `partition_label` |
| `/api/datasets`、`/api/partitions` | 不作为正式契约；实现阶段应切到 `/api/lake/datasets`、`/api/lake/partitions` |
| 前端 `layerLabel/layoutLabel/sourceLabel` 等事实翻译 | 清零，改为后端返回展示字段 |
| 前端 `buildLayerAggregates` 这类事实聚合 | 清零，改为消费 `GET /api/lake/overview` |

### 11.8 开发落地状态

1. 已补 `LakeNodeDefinition`、`LakeNodeSummary`、`LakePhysicalAssetSummary`、`LakeOverviewResponse`。
2. 已把 Catalog 中的数据集路径型 layer 收口为 node，保留全局 `LakeLayerDefinition` 只做大层级字典。
3. 已按 node 扫描分区，并补全湖 physical asset 扫描。
4. 已实现 `/api/lake/overview`、`/api/lake/datasets`、`/api/lake/partitions`、`/api/lake/physical-assets`。
5. 已把 Recovery 之外的数据湖总览与详情前端切到后端展示字段，清掉页面事实推断。
6. 后续若新增 Storage / Cost 或 Health 页面，必须复用本节模型，不允许重新按页面自建一套事实字段。

### 11.9 开发门禁

进入代码开发前必须确认：

1. 本节契约和 `local-lake-console-data-model-map-v1.html` 口径一致。
2. 不新增与本节无关 API。
3. 不顺手开发 Storage / Cost 新页面。
4. 不保留新旧模型双主线。
5. 不改生产 `src/**`、生产 `frontend/**` 或生产 Ops/Web。

## 11-old. 旧版 API 契约草案（归档，不作为后续开发依据）

本节保留早期第一版 API 草案，仅用于说明当前代码历史来源。后续开发不得以本归档小节作为契约依据；正式依据是上方第 11 章目标态契约。

### 11.1 通用对象

#### `LakePathInfo`

| 字段 | 类型 | 含义 |
|---|---|---|
| `lake_root` | string | 当前 `GOLDENSHARE_LAKE_ROOT` 绝对路径 |
| `exists` | boolean | 路径是否存在 |
| `readable` | boolean | 是否可读 |
| `writable` | boolean | 是否可写 |
| `initialized` | boolean | 是否已初始化为 Goldenshare Lake |
| `layout_version` | integer 或 null | Lake layout 版本 |

#### `DiskUsageInfo`

| 字段 | 类型 | 含义 |
|---|---|---|
| `total_bytes` | integer | 磁盘总容量 |
| `used_bytes` | integer | 已用容量 |
| `free_bytes` | integer | 可用容量 |
| `usage_percent` | number | 使用率 |

#### `LakeRiskItem`

| 字段 | 类型 | 含义 |
|---|---|---|
| `severity` | string | `info/warning/error` |
| `code` | string | 风险码，如 `tmp_residue` |
| `message` | string | 给用户看的说明 |
| `path` | string 或 null | 相关路径 |
| `suggested_action` | string 或 null | 建议动作 |

### 11.2 `GET /api/health`

用途：本地后端健康检查。

输入：无。

输出：

| 字段 | 类型 | 含义 |
|---|---|---|
| `status` | string | 固定 `ok` |
| `service` | string | 固定 `lake_console` |
| `time` | string | ISO 时间 |

示例：

```json
{
  "status": "ok",
  "service": "lake_console",
  "time": "2026-04-29T10:00:00+08:00"
}
```

### 11.3 `GET /api/lake/status`

用途：读取 Lake Root 和磁盘状态。

输入：无。Lake Root 来自 `GOLDENSHARE_LAKE_ROOT`。

输出：

| 字段 | 类型 | 含义 |
|---|---|---|
| `path` | `LakePathInfo` | Lake 路径状态 |
| `disk` | `DiskUsageInfo` 或 null | 磁盘容量信息 |
| `risks` | `LakeRiskItem[]` | 当前风险 |

### 11.4 `GET /api/lake/datasets`

用途：扫描并列出 Lake 中的数据集文件事实。

查询参数：

| 参数 | 类型 | 必填 | 含义 |
|---|---|---:|---|
| `dataset_key` | string | 否 | 过滤单个数据集 |
| `layer` | string | 否 | `raw_tushare/derived/research` |

输出对象 `LakeDatasetSummary`：

| 字段 | 类型 | 含义 |
|---|---|---|
| `dataset_key` | string | 数据集 key，如 `stk_mins` |
| `display_name` | string | 展示名 |
| `layers` | string[] | 已存在的层 |
| `freqs` | integer[] | 已存在频度 |
| `partition_count` | integer | 分区数量 |
| `file_count` | integer | Parquet 文件数量 |
| `total_bytes` | integer | 总大小 |
| `earliest_trade_date` | string 或 null | 最早交易日 |
| `latest_trade_date` | string 或 null | 最新交易日 |
| `latest_modified_at` | string 或 null | 最近文件修改时间 |
| `risks` | `LakeRiskItem[]` | 数据集级风险 |

输出：

```json
{
  "items": [
    {
      "dataset_key": "stk_mins",
      "display_name": "股票历史分钟行情",
      "layers": ["raw_tushare"],
      "freqs": [30],
      "partition_count": 1,
      "file_count": 2,
      "total_bytes": 268435456,
      "earliest_trade_date": "2026-04-24",
      "latest_trade_date": "2026-04-24",
      "latest_modified_at": "2026-04-29T10:00:00+08:00",
      "risks": []
    }
  ]
}
```

### 11.5 `GET /api/lake/datasets/{dataset_key}`

用途：查看单数据集详情。

路径参数：

| 参数 | 类型 | 含义 |
|---|---|---|
| `dataset_key` | string | 目前第一批仅 `stk_mins` |

查询参数：

| 参数 | 类型 | 必填 | 含义 |
|---|---|---:|---|
| `layer` | string | 否 | `raw_tushare/derived/research` |
| `freq` | integer | 否 | 频度 |

输出：

| 字段 | 类型 | 含义 |
|---|---|---|
| `summary` | `LakeDatasetSummary` | 数据集摘要 |
| `partitions` | `LakePartitionSummary[]` | 分区摘要 |
| `schema` | `ParquetSchemaSummary` 或 null | schema 摘要 |

### 11.6 `GET /api/lake/partitions`

用途：按条件列出分区。

查询参数：

| 参数 | 类型 | 必填 | 含义 |
|---|---|---:|---|
| `dataset_key` | string | 是 | 数据集 key |
| `layout` | string | 否 | `by_date/by_symbol_month` |
| `layer` | string | 否 | `raw_tushare/derived/research` |
| `freq` | integer | 否 | 频度 |
| `trade_date_from` | date | 否 | 起始交易日 |
| `trade_date_to` | date | 否 | 结束交易日 |
| `trade_month` | string | 否 | 月份，如 `2026-04` |
| `bucket` | integer | 否 | bucket 编号 |

输出对象 `LakePartitionSummary`：

| 字段 | 类型 | 含义 |
|---|---|---|
| `dataset_key` | string | 数据集 key |
| `layer` | string | 所属层 |
| `layout` | string | 布局 |
| `freq` | integer | 频度 |
| `trade_date` | string 或 null | 交易日 |
| `trade_month` | string 或 null | 交易月 |
| `bucket` | integer 或 null | bucket |
| `path` | string | 分区路径 |
| `file_count` | integer | 文件数 |
| `total_bytes` | integer | 总大小 |
| `row_count` | integer 或 null | 行数，可能需要读取 metadata |
| `modified_at` | string 或 null | 最近修改时间 |
| `risks` | `LakeRiskItem[]` | 分区风险 |

### 11.7 `POST /api/lake/validate`

用途：执行文件事实校验。

输入：

| 字段 | 类型 | 必填 | 含义 |
|---|---|---:|---|
| `dataset_key` | string | 否 | 限定数据集 |
| `layer` | string | 否 | 限定层 |
| `check_schema` | boolean | 否 | 是否检查 schema |
| `check_empty_files` | boolean | 否 | 是否检查空文件 |
| `check_tmp_residue` | boolean | 否 | 是否检查临时文件残留 |

输出：

| 字段 | 类型 | 含义 |
|---|---|---|
| `status` | string | `ok/warning/error` |
| `checked_at` | string | 检查时间 |
| `risks` | `LakeRiskItem[]` | 风险列表 |

### 11.8 `POST /api/lake/query/sample`

用途：DuckDB 只读 sample 查询。

输入：

| 字段 | 类型 | 必填 | 含义 |
|---|---|---:|---|
| `dataset_key` | string | 是 | 数据集 key |
| `layer` | string | 是 | `raw_tushare/derived/research` |
| `layout` | string | 是 | `by_date/by_symbol_month` |
| `freq` | integer | 否 | 频度 |
| `trade_date` | date | 否 | 交易日 |
| `trade_month` | string | 否 | 交易月 |
| `ts_code` | string | 否 | 股票代码 |
| `limit` | integer | 否 | 默认 20，最大 200 |

输出：

| 字段 | 类型 | 含义 |
|---|---|---|
| `columns` | string[] | 列名 |
| `rows` | object[] | 查询结果 |
| `elapsed_ms` | integer | 查询耗时 |
| `scanned_path_count` | integer | 扫描路径数量 |

安全约束：

1. 不接受任意 SQL 字符串。
2. 后端根据结构化参数生成只读 DuckDB 查询。
3. 第一版只允许 `select` sample，不提供 delete/update/copy。

---

## 12. 命令行与进度输出

第一版写入可以先走命令行，但必须有持续进度输出。

### 12.1 `sync-stk-mins`

示例：

```bash
lake-console sync-stk-mins \
  --ts-code 600000.SH \
  --freq 30 \
  --trade-date 2026-04-24 \
  --lake-root /Volumes/TushareData/goldenshare-tushare-lake
```

进度输出必须至少包含：

| 字段 | 含义 |
|---|---|
| `dataset` | 固定 `stk_mins` |
| `ts_code` | 当前股票 |
| `freq` | 当前频度 |
| `trade_date` | 当前交易日 |
| `page` | 当前分页序号 |
| `fetched_rows` | 当前分页读取行数 |
| `written_rows` | 当前已写行数 |
| `total_symbols_done/total_symbols` | 全市场同步时的证券进度 |
| `current_partition` | 当前写入分区 |
| `elapsed` | 已耗时 |

示例输出：

```text
[stk_mins] start lake_root=/Volumes/TushareData/goldenshare-tushare-lake dataset=stk_mins trade_date=2026-04-24 freq=30 symbols=1
[stk_mins] 1/1 ts_code=600000.SH freq=30 page=1 fetched=9 written=9 partition=freq=30/trade_date=2026-04-24 elapsed=2.1s
[stk_mins] validate partition=freq=30/trade_date=2026-04-24 files=1 rows=9 status=ok
[stk_mins] done fetched=9 written=9 files=1 elapsed=2.4s
```

禁止：

1. 长时间无输出。
2. 只在结束时输出总数。
3. 输出与实际提交/写入不一致。

### 12.2 `sync-stock-basic`

用途：从 Tushare 拉取股票基础信息，写成本地股票池文件，供全市场 `stk_mins` 同步使用。

示例：

```bash
lake-console sync-stock-basic \
  --lake-root /Volumes/TushareData/goldenshare-tushare-lake
```

默认输出：

```text
raw_tushare/stock_basic/current/part-000.parquet
```

执行股票池输出：

```text
manifest/security_universe/tushare_stock_basic.parquet
```

写入策略：

1. `stock_basic` 数据量较小，每次全量请求并全量替换。
2. 先写 `_tmp/run_id/raw_tushare/stock_basic/current/part-000.parquet`。
3. 再写 `_tmp/run_id/manifest/security_universe/tushare_stock_basic.parquet`。
4. 校验可读、schema 正确、`ts_code` 非空。
5. 分别替换正式文件。
6. 写 `manifest/sync_runs.jsonl`。

字段建议：

| 字段 | 含义 |
|---|---|
| `ts_code` | 股票代码，必须有 |
| `symbol` | 股票代码数字部分 |
| `name` | 股票名称 |
| `area` | 地域 |
| `industry` | 行业 |
| `market` | 市场 |
| `list_status` | 上市状态 |
| `list_date` | 上市日期 |
| `delist_date` | 退市日期 |
| `is_hs` | 是否沪深港通 |

进度输出示例：

```text
[stock_basic] start lake_root=/Volumes/TushareData/goldenshare-tushare-lake
[stock_basic] fetched=5360 writing_raw=_tmp/20260429T100000Z/raw_tushare/stock_basic/current/part-000.parquet
[stock_basic] writing_universe=_tmp/20260429T100000Z/manifest/security_universe/tushare_stock_basic.parquet
[stock_basic] validate rows=5360 status=ok
[stock_basic] done raw_output=raw_tushare/stock_basic/current/part-000.parquet universe_output=manifest/security_universe/tushare_stock_basic.parquet elapsed=1.8s
```

`sync-stk-mins` 全市场模式读取执行股票池文件：

```text
manifest/security_universe/tushare_stock_basic.parquet
```

读取规则：

1. 默认使用 `ts_code` 列。
2. 默认包含 `L/P/D`，避免历史分钟线回补漏掉退市或暂停上市证券。
3. 如后续需要只跑上市股票，可新增显式参数，不在第一版默认过滤。

### 12.3 `rebuild-stk-mins-research`

示例：

```bash
lake-console rebuild-stk-mins-research \
  --freq 15 \
  --trade-month 2026-04 \
  --lake-root /Volumes/TushareData/goldenshare-tushare-lake
```

进度输出必须显示：

1. 当前读取的 by_date 分区数量。
2. 当前输出 bucket。
3. 已处理行数。
4. 已写文件数。
5. 当前临时目录和最终目录。

### 12.4 `derive-stk-mins`

示例：

```bash
lake-console derive-stk-mins \
  --trade-date 2026-04-24 \
  --targets 90,120 \
  --lake-root /Volumes/TushareData/goldenshare-tushare-lake
```

进度输出必须显示：

1. 输入分区。
2. 输出分区。
3. 当前股票或批次。
4. 输入行数。
5. 输出行数。
6. 缺失窗口数量。

---

## 13. 本地一键启动脚本

需要新增一个专门脚本：

```text
scripts/local-lake-console.sh
```

职责：

1. 检查 `GOLDENSHARE_LAKE_ROOT`。
2. 检查移动盘路径是否存在。
3. 启动 `lake_console/backend`。
4. 启动 `lake_console/frontend`。
5. 打印访问地址。

示例：

```bash
GOLDENSHARE_LAKE_ROOT=/Volumes/TushareData/goldenshare-tushare-lake \
bash scripts/local-lake-console.sh
```

输出示例：

```text
[lake-console] lake_root=/Volumes/TushareData/goldenshare-tushare-lake
[lake-console] backend=http://127.0.0.1:8010
[lake-console] frontend=http://127.0.0.1:5178
[lake-console] press Ctrl+C to stop
```

要求：

1. 该脚本只服务本地，不进入生产 systemd。
2. 不允许读取远程 DB。
3. 不允许启动生产 web/worker/scheduler。
4. 后续应在 `scripts/AGENTS.md` 中标明该脚本是本地 Lake Console 专用脚本。

---

## 14. research 重排耗时评估

research 重排会耗时，因为它需要读取一个月的 by_date Parquet，再按 `ts_code` 计算 bucket、排序并写出 by_symbol_month。

耗时取决于：

1. 频度：`1min` 明显大于 `15/30/60min`。
2. 时间范围：一个月比一天更重。
3. 移动 SSD 读写速度。
4. 是否排序。
5. part 文件大小和小文件数量。

但它不是每次查询都要做。它是离线整理动作：

```text
同步 by_date 后，按需重排某个 freq + trade_month
```

推荐执行节奏：

1. 日常先把 by_date 同步稳定。
2. 需要做回测的月份，再重排 research。
3. 对 15/30/60 这类常用频度优先重排。
4. `1min` 数据最大，优先小范围试跑后再全量。

第一版必须有进度输出，不能让用户长时间不知道是否还在运行。

---

## 15. 当前结论

推荐路线：

```text
先建立 lake_console 独立工程框架
再做 Lake Root 与文件事实只读扫描
再做 stk_mins 单股票单日最小写入闭环
再做页面展示
最后扩展全市场同步、90/120 派生、research 重排
并补上正式写入的持久备份、恢复账本与前端恢复管理
```

这条路线同时满足：

1. 生产环境安全。
2. 本地移动 SSD 可用。
3. DuckDB 可直接读。
4. 初始空盘也能通过最小写入闭环验证。
5. 后续可逐步扩展，不把本地研究工具污染到 Goldenshare 生产主系统。
