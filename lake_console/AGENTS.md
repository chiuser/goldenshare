# AGENTS.md — `lake_console/` 本地 Lake 管理台规则

> 整合说明：本版保留原有本地 Lake 管理台规则，并新增“前端 UI 重设计与设计资料优先级”。
> 目标是让 Codex 默认知道：旧设计文档是 legacy baseline，外部 taste skills 是辅助审美工具，lake_console/AGENTS 与 frontend/AGENTS 才是最高约束。

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
3. 默认不碰远程 `goldenshare-db`；仅在开发 `prod-raw-db` 或已明确批准的数据集专项 `prod-core-db` 只读导出能力时允许按下方白名单规则访问。
4. 从 Tushare 拉取 `stock_basic`，写入本地股票池：

```text
manifest/security_universe/tushare_stock_basic.parquet
```

5. 后续 `stk_mins` 全市场同步默认只能读取本地股票池文件；除 `prod-raw-db` 与 `index_daily` 专用 `prod-core-db` 只读导出能力外，不允许读远程数据库。

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

## 前端 UI 重设计与设计资料优先级

本节用于避免 Codex 在旧设计文档、外部 skills、当前工程实现之间来回摇摆。

### 规则优先级

涉及 `lake_console/frontend` 的页面、组件、样式、交互、视觉优化任务时，优先级从高到低为：

```text
1. lake_console/AGENTS.md
2. lake_console/frontend/AGENTS.md
3. lake_console/frontend/.skills/lake-console-design-system/SKILL.md
4. lake_console/frontend/.skills/lake-console-frontend-architecture/SKILL.md
5. lake_console/frontend/.skills/lake-console-ui-review/SKILL.md
6. lake_console/frontend 当前真实代码结构
7. 外部 skills：
   - .agents/skills/design-taste-frontend/SKILL.md
   - .agents/skills/minimalist-ui/SKILL.md
   - .agents/skills/redesign-existing-projects/SKILL.md
8. 旧设计文档：
   - docs/frontend/frontend-design-tokens-and-component-catalog-v1.md
   - docs/frontend/frontend-component-showcase-v1.html
   - docs/frontend/frontend-biz_design_system_v13.md
   - docs/frontend/frontend-biz_component_catalog_v13.md
   - docs/frontend/frontend-biz_component_showcase_v13.html
```

含义：

```text
AGENTS 管边界
lake_console 本地 skills 管方法
当前真实代码管可落地性
taste-skill 管审美和 redesign 方法
旧设计文档管 token、组件清单、历史视觉基线
```

### 旧设计文档定位

旧设计文档不是本轮 lake console UI 优化的最高约束。

旧设计文档只作为：

1. token 参考。
2. 组件命名参考。
3. 历史视觉基线。
4. 已有设计资产库。
5. 哪些方向过去曾经尝试过的参考。

允许偏离旧 showcase 的具体布局、CSS 类名、页面排版和局部视觉样式，以便重新优化 `lake_console/frontend` 的 UI 质量。

禁止：

1. 像素级复刻旧 showcase。
2. 为了遵守旧 showcase 而保留明显丑、旧、乱、重的实现。
3. 直接照搬旧 showcase 的 CSS 类名，除非当前工程已经采用。
4. 因旧设计文档要求而突破 lake console 的本地独立工程边界。
5. 因旧设计文档要求而引入第二套主 UI 框架。

### 外部 skills 定位

已安装的外部 skills 只用于辅助提升 UI 质量，不得覆盖本文件规则。

外部 skills 允许用于：

1. 审查已有页面为什么丑。
2. 改善视觉层级、间距、卡片、表格、状态展示。
3. 指导已有页面小步 redesign。
4. 提升整体现代感、专业感和一致性。
5. 减少默认组件拼装感。

外部 skills 禁止导致：

1. 引入 Ant Design、MUI、shadcn/ui、Tailwind、Chakra 或其他第二套 UI 框架。
2. 改变 API 语义。
3. 改变后端业务逻辑。
4. 在前端页面层推断后端事实。
5. 做炫酷大屏、营销页、霓虹、重度玻璃拟态。
6. 一次性全站重构。

### 当前 UI 优化目标

`lake_console/frontend` 后续 UI 优化应按“v2 重设计”理解，而不是继续严格复刻旧 v1 设计。

目标是：

1. 更专业。
2. 更克制。
3. 更现代。
4. 更统一。
5. 更适合本地数据管理台。
6. 中高信息密度，但不拥挤。
7. 页面结构清晰，组件边界稳定。
8. 允许重新整理卡片、表格、状态、筛选区、页面头部和空状态。

不得把“更美观”理解为：

1. 大面积渐变。
2. 强装饰背景。
3. 炫酷大屏风。
4. 营销官网风。
5. 过量动效。
6. 无意义玻璃拟态。
7. 过度留白。

---

## 硬隔离规则

1. 不允许 import `src/ops/**`。
2. 不允许 import 生产 `src/app/**` 运行入口。
3. 不允许 import 生产 `frontend/src/**`。
4. 不允许挂入生产 `src/app/web`。
5. 不允许挂入生产 `/api/v1/ops/**`。
6. 默认不允许读取或写入远程 `goldenshare-db`。
7. 远程数据库只读导出目前只允许两种模式：
   - `prod-raw-db`：从生产 `raw_tushare` 白名单表只读导出为本地 Parquet；
   - `prod-core-db`：当前仅允许 `index_daily` 从 `core_serving.index_daily_serving` 只读导出，并映射回 Tushare `index_daily` 字段口径。
8. 使用 `prod-raw-db` 或 `prod-core-db` 访问远程 `goldenshare-db` 时，只允许只读，不允许任何写入、DDL、锁表或状态更新。
9. 使用 `prod-raw-db` 访问远程 `goldenshare-db` 时，只允许访问 `raw_tushare` schema 下的白名单数据集表。
10. 使用 `prod-core-db` 访问远程 `goldenshare-db` 时，当前只允许访问 `core_serving.index_daily_serving`，不得泛化到其他 `core` / `core_serving` 表。
11. 使用 `prod-raw-db` 或 `prod-core-db` 导出数据时，禁止 `select *`；必须按数据集字段白名单显式投影。`prod-raw-db` 不得导出 `api_name`、`fetched_at`、`raw_payload`，`prod-core-db` 不得导出 `source`、`created_at`、`updated_at`。
12. Lake raw 层只允许保留源站输出字段白名单；无论后续数据来自 `raw_tushare` 还是 `core/core_serving`，`api_name`、`fetched_at`、`raw_payload`、`source`、`created_at`、`updated_at` 等 Goldenshare 自增系统字段一律禁止带入，字段名若与源站文档不一致必须先映射回源站口径。
13. 除 `prod-raw-db` 与已批准的 `prod-core-db` 只读导出源站数据外，不允许通过远程数据库补充文件事实、任务状态、数据集状态或股票池。
14. 不允许使用生产 `ops.task_run`、`ops.schedule`、`ops.dataset_status_snapshot`、`ops.dataset_layer_snapshot_current`。
15. 不允许接入生产 scheduler/worker。
16. 不允许修改生产部署脚本来启动 `lake_console`。
17. 不允许默认把数据写入仓库目录、用户 home 或系统临时目录。
18. 没有明确 `GOLDENSHARE_LAKE_ROOT` 时，禁止执行写入。

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

### 前端 UI v2 重设计规则

`lake_console/frontend` 当前进入 UI v2 优化阶段。

如果任务涉及前端视觉、页面设计、组件抽取或样式重构，必须遵守：

1. 先阅读 `lake_console/frontend/AGENTS.md`。
2. 先阅读 `lake_console/frontend/.skills/lake-console-design-system/SKILL.md`。
3. 先阅读 `lake_console/frontend/.skills/lake-console-frontend-architecture/SKILL.md`。
4. 先阅读 `lake_console/frontend/.skills/lake-console-ui-review/SKILL.md`。
5. 再参考外部 taste skills。
6. 最后参考旧设计文档。

前端 UI 改造每轮只选择一个代表性页面或一组强相关组件，不允许一次性“全站美化”。

推荐工作方式：

```text
审查现状
-> 选择一个低风险页面
-> 列出 5 条以内主要 UI 问题
-> 抽取 1~2 个轻量可复用组件
-> 小范围 redesign
-> 保持 API 和业务行为不变
-> 跑验证命令
```

优先沉淀或复用：

```text
PageHeader
PageSection
SectionCard
MetricCard
StatusBadge
DenseToolbar
FilterPanel
DataTableCard
EmptyStateBlock
ErrorStateBlock
LoadingBlock
DetailKVGrid
TimelineCard
```

禁止：

1. 全站一次性改版。
2. UI 改造和后端写入逻辑混在一轮。
3. UI 改造和远程数据库访问能力混在一轮。
4. UI 改造时修改 `goldenshare/frontend`。
5. UI 改造时修改生产 `src/**`。
6. 为了美观而在页面层猜后端事实。
7. 为了美观而新增第二套 UI 框架。

---

## 后端规则

后端必须放在：

```text
lake_console/backend/
```

规则：

1. 独立本地服务。
2. 默认监听 `127.0.0.1`。
3. 默认不连接远程数据库；仅开发 `prod-raw-db` 或 `index_daily` 专用 `prod-core-db` 只读导出能力时，允许按“硬隔离规则”中的白名单约束访问远程 `goldenshare-db`。
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
4. 是否读取/写入远程 `goldenshare-db`；默认必须是“否”，若为 `prod-raw-db` 或 `prod-core-db` 开发轮次，必须说明只读、允许访问的 schema/表、字段投影和禁止 `select *` 的执行结果。
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
