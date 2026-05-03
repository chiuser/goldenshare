# AGENTS.md — `lake_console/` 本地 Lake 管理台规则

## 适用范围

本文件适用于 `lake_console/` 及其所有子目录。  
如果子目录后续新增更近的 `AGENTS.md`，以更近规则为准。

---

## 项目定位

`lake_console` 是 Goldenshare 仓库内的本地独立工程，用于管理本地移动存储设备上的 Tushare Parquet Lake。

它服务：

1. 本地移动 SSD / 移动硬盘上的 Tushare 数据资产。
2. DuckDB / Parquet 查询与研究场景。
3. `stk_mins` 等大体量行情数据的本地文件化管理。
4. 本地只读扫描、文件事实校验、后续同步与派生数据生成。

它不是：

1. 生产 Ops 运营后台。
2. 生产 Web app 的一部分。
3. 生产调度/任务系统的一部分。
4. 远程数据库管理工具。
5. `src/foundation` / `src/ops` / `src/biz` / `src/app` 的子系统。

---

## 当前目标

当前路线：

```text
先搞框架 -> 再做读 -> 再做写
```

因为移动盘初始为空，第一阶段允许保留最小写入闭环：

```text
sync-stock-basic -> 本地股票池 Parquet
sync-stk-mins 单股票单日 -> by_date Parquet
只读扫描页面 -> 文件事实展示
```

当前第一批重点：

1. 建立独立工程骨架。
2. 读取并校验 `GOLDENSHARE_LAKE_ROOT`。
3. 不碰远程 `goldenshare-db`。
4. 从 Tushare 拉取 `stock_basic`，写入本地股票池：

```text
manifest/security_universe/tushare_stock_basic.parquet
```

5. 后续 `stk_mins` 全市场同步只能读取本地股票池文件，不允许读远程数据库。

---

## 必读文档

动手前必须阅读：

1. 仓库根规则：`AGENTS.md`
2. 本地执行规则：`AGENTS.local.md`
3. Lake Console 架构方案：`docs/architecture/local-lake-console-architecture-plan-v1.md`
4. `stk_mins` Parquet Lake 方案：`docs/datasets/stk-mins-parquet-lake-plan-v1.md`
5. Tushare `stock_basic` 源文档（实现 `sync-stock-basic` 前）
6. Tushare `stk_mins` 源文档：`docs/sources/tushare/股票数据/行情数据/0370_股票历史分钟行情.md`

如涉及前端视觉：

1. `docs/frontend/frontend-biz_design_system_v13.md`
2. `docs/frontend/frontend-biz_component_catalog_v13.md`
3. `docs/frontend/frontend-biz_component_showcase_v13.html`

---

## 硬隔离规则

1. 不允许 import `src/ops/**`。
2. 不允许 import 生产 `src/app/**` 运行入口。
3. 不允许 import 生产 `frontend/src/**`。
4. 不允许挂入生产 `src/app/web`。
5. 不允许挂入生产 `/api/v1/ops/**`。
6. 不允许读取或写入远程 `goldenshare-db`。
7. 不允许通过远程数据库补充文件事实、任务状态、数据集状态或股票池。
8. 不允许使用生产 `ops.task_run`、`ops.schedule`、`ops.dataset_status_snapshot`、`ops.dataset_layer_snapshot_current`。
9. 不允许接入生产 scheduler/worker。
10. 不允许修改生产部署脚本来启动 `lake_console`。
11. 不允许默认把数据写入仓库目录、用户 home 或系统临时目录。
12. 没有明确 `GOLDENSHARE_LAKE_ROOT` 时，禁止执行写入。

---

## 允许依赖

允许：

1. 读取 `docs/**` 规范文档。
2. 使用 Tushare API。
3. 使用 DuckDB / PyArrow / Pandas 等本地数据处理依赖。
4. 使用本地移动盘路径 `GOLDENSHARE_LAKE_ROOT`。
5. 复制必要的设计 token 或基础组件到 `lake_console` 内部。
6. 第一版可维护独立轻量 dataset catalog，避免牵入生产依赖。

谨慎允许：

1. 只读参考 `src/foundation/datasets/**` 的字段口径，但第一版不直接依赖其运行代码。
2. 只读参考生产前端设计文档，但不能 import 生产前端源码。

禁止：

1. 手写远程 DB 连接串。
2. 调用 `bash scripts/psql-remote.sh` 作为 lake console 业务逻辑的一部分。
3. 让 lake console 页面依赖生产 Ops API。

---

## Lake Root 规则

`GOLDENSHARE_LAKE_ROOT` 是本项目的唯一数据根目录。

优先级：

```text
命令行 --lake-root
> 环境变量 GOLDENSHARE_LAKE_ROOT
> lake_console/config.local.toml
> 报错
```

禁止：

1. 静默使用默认目录。
2. 自动写到仓库目录。
3. 自动写到 `~/Downloads`、`~/Documents`、`/tmp`。

写入前必须检查：

1. 路径存在。
2. 可读。
3. 可写。
4. 剩余空间可读取。
5. 目标不在远程挂载异常状态。

---

## 数据写入规则

所有写入必须使用：

```text
_tmp -> 校验 -> 替换正式分区/文件
```

禁止直接覆盖正式文件。

写入 `stock_basic`：

```text
manifest/security_universe/tushare_stock_basic.parquet
```

策略：

1. 全量拉取。
2. 全量替换。
3. 校验 `ts_code` 非空。
4. 校验 Parquet 可读。
5. 写入 `manifest/sync_runs.jsonl`。

写入 `stk_mins`：

```text
raw_tushare/stk_mins_by_date/freq=*/trade_date=*/*.parquet
```

策略：

1. 先写 by_date。
2. 后续从 by_date 派生 `derived`。
3. 后续从 by_date / derived 重排 `research`。
4. 不把 `90/120` 写入 `raw_tushare`。

---

## 命令行进度规则

长任务必须持续输出进度。

禁止：

1. 长时间无输出。
2. 只在结束时输出总数。
3. 输出与实际写入不一致。

`sync-stock-basic` 至少输出：

```text
start / fetched / writing / validate / done
```

`sync-stk-mins` 至少输出：

```text
dataset
trade_date
freq
ts_code
page
fetched_rows
written_rows
current_partition
elapsed
```

全市场任务还必须输出：

```text
symbols_done / symbols_total
units_done / units_total
```

---

## API 设计规则

API 必须先定义输入参数和输出对象，再实现。

第一版 API 契约见：

```text
docs/architecture/local-lake-console-architecture-plan-v1.md
```

禁止：

1. 临时拼装未定义字段。
2. 让前端猜字段含义。
3. 接受任意 SQL 字符串做 DuckDB 查询。
4. 返回生产 Ops 状态字段。

DuckDB sample 查询只能接受结构化参数，由后端生成只读查询。

---

## 前端规则

前端必须放在：

```text
lake_console/frontend/
```

规则：

1. 独立 Vite/React 工程。
2. 不 import `frontend/src/**`。
3. 不注册到生产前端路由。
4. 可以复制设计 token 和基础组件。
5. 页面必须明确标识“本地 Lake Console”。
6. 页面数据必须来自 `lake_console/backend` API，不得直接拼磁盘路径规则。

---

## 后端规则

后端必须放在：

```text
lake_console/backend/
```

规则：

1. 独立本地服务。
2. 默认监听 `127.0.0.1`。
3. 不连接远程数据库。
4. 不启动生产 worker/scheduler。
5. 不复用生产 TaskRun。
6. 写入前必须检查 `GOLDENSHARE_LAKE_ROOT`。

---

## 脚本规则

本地启动脚本规划：

```text
scripts/local-lake-console.sh
```

职责：

1. 检查 `GOLDENSHARE_LAKE_ROOT`。
2. 检查后端依赖。
3. 检查前端依赖。
4. 启动本地后端。
5. 启动本地前端。
6. 打印访问地址。

禁止：

1. 启动生产 web。
2. 启动生产 worker。
3. 启动生产 scheduler。
4. 读取远程 DB。
5. 修改 systemd。

---

## 开发流程

每轮只做一个清晰目标。

Lake 数据集同步研发必须额外遵守：

1. Lake 命令优先面向文件事实和本地全量资产管理，不要先按生产 Ops/调度/状态系统的心智去设计。
2. 不盲目复用生产系统的默认时间语义；生产侧“无日期”“默认日期”“默认窗口”只能作为参考，不能直接当作 Lake 命令的最终行为。
3. 开发任何 Lake 数据集同步前，必须先回看生产系统当前是如何实现该数据集的请求、分页、时间参数和写入口径，再基于 Lake 的本地文件资产目标重新判断什么实现最合理。

推荐顺序：

1. 工程骨架。
2. Lake Root 检查。
3. `sync-stock-basic`。
4. 只读扫描 API。
5. `sync-stk-mins` 单股票单日。
6. 前端只读页面。
7. 全市场同步。
8. validate 风险扫描。
9. DuckDB sample 查询。
10. 90/120 派生。
11. research 重排。

每轮开始前：

1. 阅读本文件。
2. 阅读相关设计文档。
3. 明确本轮目标。
4. 审计影响面。

每轮结束前：

1. 跑本轮最小测试。
2. 若新增或修改任何文档，必须跑 `python3 scripts/check_docs_integrity.py` 并通过。
3. 确认没有生产代码 import `lake_console`。
4. 说明是否影响生产部署，答案通常必须是“不影响”。

---

## 提交说明要求

每次提交或汇报至少说明：

1. 本轮目标。
2. 改动文件。
3. 是否触及生产 `src/**` 或 `frontend/**`。
4. 是否读取/写入远程 `goldenshare-db`，答案必须是“否”。
5. 验证结果。
6. 下一步建议。

---

## 当前禁止事项

1. 不要一开始就做全市场 10 年分钟线同步。
2. 不要在没有 `sync-stock-basic` 的情况下实现全市场 `stk_mins`。
3. 不要把远程 Postgres 当股票池来源。
4. 不要把 Lake Console 页面挂到生产 Ops 左侧菜单。
5. 不要为了复用方便，把生产前端组件直接 import 进来。
6. 不要实现任意 SQL 执行入口。
