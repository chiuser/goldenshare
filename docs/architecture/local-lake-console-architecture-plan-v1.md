# Local Lake Console 架构方案 v1

- 版本：v1
- 状态：待评审
- 更新时间：2026-04-29
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
3. 不读写 `ops.task_run`、`ops.dataset_status_snapshot`、`ops.dataset_layer_snapshot_current`。
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
5. `lake_console` 不允许依赖 `ops.task_run`、`ops.schedule`、`ops.dataset_status_snapshot`、`ops.dataset_layer_snapshot_current`。
6. `lake_console` 不允许对远程 `goldenshare-db` 做任何读写操作；不得通过远程数据库补充文件事实、任务状态或数据集状态。
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

### M5：全市场写入与进度

目标：

1. 支持全市场 `ts_code` 扇出。
2. 支持多频度。
3. 控制 part 文件大小，避免小文件爆炸。
4. 展示当前股票、当前频度、当前分区、累计行数。
5. 中断后不破坏正式分区。

验收：

1. 单日单频全市场能跑完。
2. 中断后只留下 `_tmp`，正式数据不被污染。
3. 重新执行可以覆盖该分区。

### M6：派生与 research 重排

目标：

1. 从 `30min` 生成 `90min`。
2. 从 `60min` 生成 `120min`。
3. 写入 `derived/stk_mins_by_date`。
4. 从 by_date 重排生成 `research/stk_mins_by_symbol_month`。
5. 支持 32 个稳定 hash bucket。

验收：

1. `90/120` 与原始分钟线字段一致。
2. DuckDB 可直接读取派生数据。
3. 单股长周期回测优先读 research 层。

前端展示要求：

1. 增加 Lake 分层概览，明确 `raw_tushare`、`derived`、`research` 的语义、来源和推荐用途。
2. `raw_tushare` 展示为原始接口落盘层，适合单日全市场横截面查询。
3. `derived` 展示为本地派生周期层，适合 90/120 分钟线等本地计算结果。
4. `research` 展示为研究查询优化层，适合单股长周期回测和少数股票相似性分析。
5. 分区列表按 layer 分组展示，避免用户把三层数据混用。

### M6 补充：什么是 research 重排

`research 重排` 是把已经写好的 by_date 数据，重新整理成更适合研究查询的 by_symbol_month 数据。

它不是重新向 Tushare 请求数据，也不是生成新的行情口径。

具体来说：

```text
输入：raw_tushare/stk_mins_by_date/freq=15/trade_date=2026-04-01..2026-04-30
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
3. 区间全市场命令按自然月或 stk_mins_request_window_days 切请求窗口
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

其中 `request_window_count` 默认约等于自然月数量。

第一层正式写入路径：

```text
raw_tushare/stk_mins_by_date/freq=30/trade_date=2026-04-24/
```

也就是说，最先落盘的是：

```text
按 freq + trade_date 分区的 by_date Parquet
```

之后有两类后处理：

1. 派生周期：从 `30min` by_date 生成 `90min` by_date，从 `60min` by_date 生成 `120min` by_date。
2. research 重排：把 by_date 数据按 `freq + trade_month + bucket` 重新组织，生成适合回测和相似性分析的 research 层。

最终形成：

```text
raw_tushare/stk_mins_by_date/            # Tushare 原始分钟线，按日组织
derived/stk_mins_by_date/                # 90/120 派生分钟线，按日组织
research/stk_mins_by_symbol_month/       # 原始 + 派生分钟线，按月和股票桶组织
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
| `sync-trade-cal` | 同步本地交易日历，供区间分钟线同步使用 |
| `sync-stk-mins-range` | 基于本地交易日历按开市日循环同步分钟线 |
| `rebuild-stk-mins-research` | 重排 research 层 |
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
| `stk_mins_derived_service.py` | 90/120 派生 |

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

## 11. API 契约草案

本节定义第一版 Lake Console 后端 API 的输入参数和输出对象。后续实现必须以这里为契约起点，不能只返回临时拼装字段。

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
[stk_mins] 1/1 ts_code=600000.SH freq=30 page=1 fetched=241 written=241 partition=freq=30/trade_date=2026-04-24 elapsed=2.1s
[stk_mins] validate partition=freq=30/trade_date=2026-04-24 files=1 rows=241 status=ok
[stk_mins] done fetched=241 written=241 files=1 elapsed=2.4s
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
```

这条路线同时满足：

1. 生产环境安全。
2. 本地移动 SSD 可用。
3. DuckDB 可直接读。
4. 初始空盘也能通过最小写入闭环验证。
5. 后续可逐步扩展，不把本地研究工具污染到 Goldenshare 生产主系统。
