# Local Lake Console 模型/API 阻断项审计 v1

- 审计日期：2026-05-14
- 审计对象：`lake_console` 数据湖总览页、后端模型/API 契约、前端展示消费、相关测试门禁
- 主依据：`docs/architecture/local-lake-console-architecture-plan-v1.md` 第 11 章
- 当前目标：让数据湖总览、数据集清单、内容节点、分区和硬盘资产视图真实反映 Lake 事实；不把业务命令内部读写链路混入本轮模型/API 收口。

## 1. 分类规则

### B 类：阻断当前需求开发，需要纳入本轮计划

满足任一条件即为 B 类：

1. 影响 `Dataset -> Node -> Partition / PhysicalAsset` 模型契约正确表达。
2. 影响 `/api/lake/overview`、`/api/lake/datasets`、`/api/lake/partitions`、`/api/lake/physical-assets` 输出事实正确性。
3. 前端仍在自行翻译、拼接、猜测后端事实字段。
4. 当前模型/API 变更导致测试门禁无法稳定验证。
5. 数据模型变更直接导致既有命令不能运行或输入输出契约断裂。

### A 类：登记问题，不阻断当前需求开发

满足以下条件归为 A 类：

1. 只影响业务命令内部实现细节，不影响当前总览页和模型/API 契约。
2. 只是历史说明、配置说明或早期文档段落过期，且第 11 章正式契约已经给出清晰口径。
3. 未来页面或未来能力会需要，但当前总览页/模型/API 第一批不依赖。
4. 不是当前需求的可执行范围，贸然处理会扩大开发面。

## 2. 本轮发现的 B 类阻断项与处理状态

| 编号 | 阻断项 | 审计时代码证据 | 为什么阻断 | 本轮处理状态 |
|---|---|---|---|---|
| B-1 | 前端 `HealthBadge` 仍自行翻译健康状态文案 | `lake_console/frontend/src/components/HealthBadge.tsx` | 第 11 章要求后端返回 `health_label`，前端只展示；组件把 `ok/warning/error/empty` 映射成中文文案，属于前端事实翻译。 | 已处理：`HealthBadge` 改为接收并展示后端 `health_label`，只用 `health_status` 控制样式；状态筛选选项也改为从后端行数据生成。 |
| B-2 | 数据集详情页只加载第一个 node 的分区 | `lake_console/frontend/src/main.tsx` 中固定取第一个 `node_summaries[0]` | 多 node 数据集如 `stk_mins`、`stk_mins_indicators` 无法查看其他 node 的分区，不完整表达 `Dataset -> Node -> Partition`。 | 已处理：选择状态增加 `selectedNodeKey`，详情页可切换内容节点，并按当前 node 请求和展示分区样本。 |
| B-3 | `test_sync_planner.py` 测试 mock 已过期，导致测试门禁失败 | `tests/lake_console/test_sync_planner.py` monkeypatch `stk_mins_planner.read_parquet_rows` | 当前 planner 已经通过 `load_security_universe_for_range` 读取股票池；测试还 patch 旧入口，直接失败。虽然不是业务逻辑阻断，但阻断本轮回归验证。 | 已处理：测试改为 patch `security_universe_filter.read_parquet_rows`，并补齐股票池生命周期字段样本。 |
| B-4 | 两个 `test_filesystem_scanner.py` 同名会在同一次 pytest 收集中 import mismatch | `tests/lake_console/test_filesystem_scanner.py` 与 `lake_console/backend/tests/test_filesystem_scanner.py` | 单独运行都通过，但同一命令同时收集会失败，影响稳定回归。 | 已处理：后者重命名为 `lake_console/backend/tests/test_filesystem_scanner_index_mins.py`。 |

## 3. 当前 A 类登记项

| 编号 | 登记项 | 代码/文档证据 | 为什么不阻断当前需求 | 后续触发条件 |
|---|---|---|---|---|
| A-1 | `sync-stk-mins-range`、`plan-sync stk_mins` 的窗口策略、历史月窗口对比和配置说明仍有旧口径痕迹 | `lake_console/backend/app/settings.py` 的 `stk_mins_request_window_days`；`lake_console/config.local.example.toml`；`lake_console/README.md` | 当前总览页和模型/API 不依赖该配置；真实执行已按 `freq` 定交易日窗。 | 后续专门整理 CLI/plan-sync 或文档配置口径时处理。 |
| A-2 | `indicator_recalc_queue` 内部仍用 `layer` / `SOURCE_LAYERS` 描述来源事件 | `lake_console/backend/app/services/indicators/indicator_recalc_queue.py` | 当前不暴露为总览页事实模型，也不影响 `Catalog Node` 与 API 输出。 | 如果后续做指标维护、Activity、血缘事件页，再统一到 `source_node_key` 语义。 |
| A-3 | 架构文档第 6 章早期 API 表仍列 `datasets/{dataset_key}`、`validate`、`query/sample` 为第一版建议 | `docs/architecture/local-lake-console-architecture-plan-v1.md` 第 6 章 | 第 11 章已经明确正式 API 和后置 API；开发依据应以第 11 章为准。 | 后续做文档清扫时，把第 6 章改成“历史建议/已被第 11 章替代”。 |
| A-4 | `/api/lake/validate`、`/api/lake/query/sample`、文件级 metadata 还未实现 | 第 11.6 已列为后置 API | 当前模型/API 第一批不需要这些接口。 | 用户明确启动 Health、Validate、DuckDB sample 或文件级详情方案时再设计。 |
| A-5 | 前端存在展示兜底格式化，如 `formatDateOrMonthRange()` 在 `coverage_label` 为空时自行拼范围 | `lake_console/frontend/src/utils/format.ts` | 正常后端会返回 `coverage_label`；当前只是兜底展示，不会改变主事实。 | 若进入“前端零事实拼装”严格清扫，可移除或降级为异常兜底。 |
| A-6 | 业务命令内部读写、补数、派生、指标重算链路仍有可优化或需审计事项 | `sync-stk-mins-range`、`derive-stk-mins`、`rebuild-*research*`、indicator services | 这些属于数据生产链路，不是总览页模型/API 的当前开发范围。 | 只有当模型字段变更导致命令不可运行，或用户明确启动对应命令治理任务时，才转为 B 类。 |
| A-7 | `PhysicalAsset` 全量递归扫描仍后置 | `lake_console/backend/app/services/filesystem_scanner.py` 的 `_physical_assets()` | 当前不做递归扫描全湖每个目录/文件，避免拖慢总览页；但已把已登记节点父目录和系统文件从“未登记资产”误判中拆出。 | 后续如果要做 Storage / Cost 或真实硬盘资产治理页，再单独设计快速索引、缓存或离线统计方案。 |

## 4. 明确不纳入本轮的事项

本轮不主动处理以下内容，避免范围失控：

1. 分钟线同步命令如何请求 Tushare、如何分页、如何 checkpoint。
2. 补数命令、派生命令、research 重排命令的内部优化。
3. 指标计算、指标重算队列和指标状态存储内部语义重构。
4. Kopia 恢复命令执行能力；Recovery 页当前仍是只读查看和命令预览。
5. Storage / Cost / Health 新页面开发。

## 5. 本轮执行顺序与结果

1. 已先修 B-3、B-4，让模型/API 回归测试可以稳定运行。
2. 已修 B-1，清掉前端健康状态文案翻译，保证展示字段以后端为准。
3. 已修 B-2，让数据集详情能按 node 查看分区，完整承接多 node 模型。
4. A 类问题只登记，不在本轮自动开发；其中 `PhysicalAsset` 全量递归扫描已明确暂缓。

## 6. 当前已确认的非阻断事实

1. 正式 API 已切到 `/api/lake/overview`、`/api/lake/datasets`、`/api/lake/partitions`、`/api/lake/physical-assets`。
2. `LakeDatasetSummary` 已使用 `node_summaries`，未发现 `layer_summaries` 作为正式 API 输出。
3. `LakePartitionSummary` 已使用 `node_key`、`partition_values`、`partition_locator`、`partition_label`。
4. `stk_mins` 和 `stk_mins_indicators` 已登记为多 node 数据集。
5. Catalog 当前通过基础一致性检查：数据集有节点、节点 key 不重复、source node key 未发现断裂、命令示例已补齐。
