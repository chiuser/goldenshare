# Local Lake 命令示例页面技术方案 v1

- 版本：v1
- 状态：待评审
- 更新时间：2026-05-03
- 适用范围：`lake_console/backend`、`lake_console/frontend`
- 目标：为 Lake Console 增加一个只读的“命令示例 / 操作提示”页面，解决本地 Lake 命令越来越多、用户难以记忆和选择的问题。

---

## 1. 背景

Lake Console 已经逐步支持：

1. Lake Root 初始化与状态检查。
2. 本地数据集扫描。
3. `stock_basic`、`trade_cal`、`index_basic`、`daily`、`moneyflow` 等数据集同步。
4. `stk_mins` 单日、区间、派生、research 重排。
5. `_tmp` 清理。

命令数量已经开始增多，而且不同数据集的参数模型不同：

1. 快照类数据集不需要交易日。
2. 日频数据集支持单日或区间。
3. `stk_mins` 有单股票、全市场、freq、区间、派生、research 等多种场景。
4. 维护类命令如 `clean-tmp` 不属于某个 Tushare 数据集，但用户也需要知道。

如果继续让用户靠记忆或翻文档使用命令，会很容易出错。  
因此需要一个只读页面，把“这个数据集可以怎么同步、怎么预览、怎么维护”的命令集中展示出来。

---

## 2. 当前现状审计

### 2.1 文档已有规划

已有规划分散在：

1. [Local Lake 数据集同步扩展方案 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-dataset-sync-expansion-plan-v1.md) 第 8.4 节。
2. [Local Lake Console 数据集模型 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-console-dataset-model-v1.md) 第 13 节。
3. [Local Lake 数据集接入说明模板](/Users/congming/github/goldenshare/docs/templates/lake-dataset-development-template.md) 第 8.3 与 9.3 节。
4. 若干数据集开发文档中的“命令示例页”小节。

这些文档已经明确：

1. 页面只展示命令。
2. 页面不触发写入。
3. 页面不启动后台任务。
4. 前端不应硬编码 dataset_key 到命令的映射。
5. 命令示例应来自 Lake Dataset Catalog。

### 2.2 当前前端实现

当前 `lake_console/frontend/src/main.tsx` 里已经有早期雏形：

```text
Panel: 命令示例 / 操作提示
CommandHints(dataset)
commandExamples(dataset)
```

但当前实现存在两个问题：

1. 命令示例由前端 `commandExamples()` 硬编码。
2. `stk_mins` 示例里存在与当前 CLI 不一致的风险，例如旧示例 `rebuild-stk-mins-derived` 已不符合当前命令命名，当前真实派生命令是 `derive-stk-mins`。

这说明页面方向是对的，但数据来源还不符合规划。

### 2.3 当前后端实现

当前后端 Lake Dataset Catalog 位于：

```text
lake_console/backend/app/catalog/
```

核心定义为：

```text
LakeDatasetDefinition
LakeLayerDefinition
LakeViewGroup
```

当前 catalog 已包含数据集基础信息、分组、层级、写入策略等信息，但还没有标准化命令示例字段。

当前 API 主要面向数据集文件事实：

```text
GET /api/lake/datasets
GET /api/lake/partitions
```

还没有专门给命令示例页面使用的 API。

### 2.4 当前 CLI 实现

当前 CLI 已拆分到：

```text
lake_console/backend/app/cli/
```

当前真实命令包括：

| 命令 | 语义 |
|---|---|
| `init` | 初始化 Lake Root 目录结构 |
| `status` | 查看 Lake Root 状态 |
| `list-datasets` | 扫描本地 Lake 数据集 |
| `plan-sync` | 预览数据集同步计划 |
| `sync-dataset` | 按 Lake Dataset Catalog 同步单个普通数据集 |
| `sync-stock-basic` | 拉取 `stock_basic` 并写入本地股票池 |
| `sync-trade-cal` | 拉取交易日历并写入本地交易日历 |
| `clean-tmp` | 审计或清理 `_tmp` run 目录 |
| `sync-stk-mins` | 同步单股票单日分钟线 |
| `sync-stk-mins-range` | 同步区间分钟线 |
| `derive-stk-mins` | 从 30/60 分钟线派生 90/120 分钟线 |
| `rebuild-stk-mins-research` | 重排 research 层 |

命令示例页面必须以这些真实命令为准，不允许继续保留旧命令名。

---

## 3. 设计目标

### 3.1 要做

1. 建立命令示例的后端单一来源。
2. 让命令示例从 Lake Dataset Catalog 或 Lake Command Catalog 输出。
3. 前端页面只消费 API，不再硬编码命令。
4. 页面支持按分组、数据集、场景查看命令。
5. 命令示例必须与真实 CLI 参数保持一致。
6. 增加测试，防止后续命令示例再次漂移。

### 3.2 不做

1. 不在页面执行命令。
2. 不在页面启动后台任务。
3. 不接生产 Ops TaskRun。
4. 不接远程 `goldenshare-db`。
5. 不新增调度能力。
6. 不把生产前端组件 import 到 `lake_console`。
7. 不把命令示例写死在前端。

---

## 4. 用户视角交互

页面名称：

```text
命令示例 / 操作提示
```

页面定位：

```text
告诉用户“当前 Lake Console 能做什么、应该执行哪条 CLI 命令”。
```

页面布局：

1. 左侧或顶部选择展示分组。
2. 第二级选择数据集。
3. 主区域展示命令示例卡片。
4. 每条命令展示标题、说明、场景、命令文本。
5. 命令文本支持复制。
6. 页面明确提示：这里只展示命令，不执行写入。

典型场景：

| 场景 | 页面展示 |
|---|---|
| 用户想同步日线单日 | 选择 `A股行情 -> daily`，看到 `lake-console sync-dataset daily --trade-date ...` |
| 用户想同步资金流区间 | 选择 `资金流向 -> moneyflow`，看到区间命令 |
| 用户想同步分钟线全市场 | 选择 `A股行情 -> stk_mins`，看到 `sync-stk-mins-range` |
| 用户想生成 90/120 分钟线 | 选择 `stk_mins`，看到 `derive-stk-mins` |
| 用户想清理临时目录 | 选择维护分组，看到 `clean-tmp --dry-run` 与清理命令 |

---

## 5. 后端模型设计

### 5.1 新增命令示例对象

建议新增：

```text
lake_console/backend/app/catalog/commands.py
```

或放入 `catalog/models.py`。

数据对象：

```python
@dataclass(frozen=True)
class LakeCommandExample:
    example_key: str
    title: str
    scenario: str
    description: str
    argv: tuple[str, ...]
    prerequisites: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
```

字段说明：

| 字段 | 含义 | 约束 |
|---|---|---|
| `example_key` | 示例唯一 key | 同一个数据集内唯一 |
| `title` | 用户可读标题 | 必填 |
| `scenario` | 使用场景 | 必填，枚举见下文 |
| `description` | 命令用途说明 | 必填 |
| `argv` | 命令参数数组 | 必填，第一项固定为 `lake-console` |
| `prerequisites` | 执行前置条件 | 可空 |
| `notes` | 注意事项 | 可空 |

`command_text` 不建议作为人工维护字段。  
后端可以由 `argv` 统一渲染：

```text
lake-console sync-dataset daily --trade-date 2026-04-24
```

这样测试可以直接检查 `argv` 的命令名是否存在，避免命令文本和真实 CLI 漂移。

### 5.2 场景枚举

建议第一版场景：

| scenario | 含义 |
|---|---|
| `init` | 初始化 |
| `status` | 状态查看 |
| `plan` | 计划预览，不发请求、不写文件 |
| `sync_point` | 单点同步 |
| `sync_range` | 区间同步 |
| `sync_snapshot` | 快照刷新 |
| `derive` | 派生数据生成 |
| `research` | research 重排 |
| `maintenance` | 维护清理 |
| `diagnostic` | 诊断检查 |

### 5.3 命令示例归属

普通数据集命令示例应挂在 `LakeDatasetDefinition` 上：

```python
LakeDatasetDefinition(
    dataset_key="daily",
    ...
    command_examples=(...)
)
```

维护类命令不属于某个 Tushare 数据集，例如 `clean-tmp`，建议定义虚拟分组：

```text
group_key = "maintenance"
dataset_key = "__lake_maintenance__"
display_name = "Lake 维护命令"
```

这样前端仍然可以使用统一的“分组 -> 数据集 -> 命令”模型。

### 5.4 当前第一批需要补齐的命令示例

| 数据集 / 分组 | 必须包含的命令示例 |
|---|---|
| `stock_basic` | `sync-stock-basic` |
| `trade_cal` | `sync-trade-cal --start-date ... --end-date ...` |
| `index_basic` | `plan-sync index_basic`、`sync-dataset index_basic`、按 `market` 示例 |
| `daily` | 单日、区间、单股区间 |
| `moneyflow` | 单日、区间、单股区间 |
| `stk_mins` | 单股票单日、全市场区间、派生、research |
| `__lake_maintenance__` | `clean-tmp --dry-run`、`clean-tmp --older-than-hours 24` |

---

## 6. API 设计

### 6.1 新增只读 API

建议新增：

```text
GET /api/lake/command-examples
```

查询参数：

| 参数 | 类型 | 必填 | 含义 |
|---|---|---|---|
| `group_key` | string | 否 | 只返回某个展示分组 |
| `dataset_key` | string | 否 | 只返回某个数据集 |

返回对象：

```json
{
  "groups": [
    {
      "group_key": "equity_market",
      "group_label": "A股行情",
      "group_order": 2,
      "datasets": [
        {
          "dataset_key": "daily",
          "display_name": "股票日线行情",
          "examples": [
            {
              "example_key": "daily_sync_trade_date",
              "title": "同步单日全市场日线",
              "scenario": "sync_point",
              "description": "写入一个 trade_date 分区。",
              "command": "lake-console sync-dataset daily --trade-date 2026-04-24",
              "argv": ["lake-console", "sync-dataset", "daily", "--trade-date", "2026-04-24"],
              "prerequisites": ["已配置 GOLDENSHARE_LAKE_ROOT 和 TUSHARE_TOKEN"],
              "notes": []
            }
          ]
        }
      ]
    }
  ]
}
```

### 6.2 为什么不让前端自己拼

禁止前端根据 dataset_key 自己拼命令，原因是：

1. 每个数据集参数模型不同。
2. 特殊命令不都走 `sync-dataset`。
3. 命令名会随着 CLI 收口变更。
4. 前端拼命令会导致文档、CLI、页面三处漂移。

后端 API 是命令示例页面的唯一来源。

---

## 7. 前端设计

### 7.1 页面入口

当前前端已有“命令示例”入口，后续应改为真实页面区域或独立页面。

第一版可以继续在当前 Lake Console 单页里实现，不必引入复杂路由。

### 7.2 数据流

目标数据流：

```text
Lake catalog command examples
  -> GET /api/lake/command-examples
  -> frontend state
  -> group select
  -> dataset select
  -> command cards
```

前端不再保留：

```text
commandExamples(dataset)
```

### 7.3 展示字段

每个命令卡片展示：

1. 标题。
2. 场景标签。
3. 说明。
4. 命令文本。
5. 前置条件。
6. 注意事项。
7. 复制按钮。

页面顶部固定提示：

```text
本页只展示命令，不会执行写入。请在本地终端确认参数后执行。
```

### 7.4 空态与错误态

| 状态 | 展示 |
|---|---|
| API 加载中 | 展示 skeleton 或加载提示 |
| 无命令示例 | 提示“该数据集尚未配置命令示例，不能进入新增数据集验收” |
| API 失败 | 展示错误信息与重试按钮 |
| 分组为空 | 展示“当前分组无可展示命令” |

---

## 8. 测试与门禁

### 8.1 后端测试

建议新增：

```text
tests/lake_console/test_command_examples_catalog.py
tests/lake_console/test_command_examples_api.py
```

覆盖：

1. 每个 Lake dataset 至少有一个命令示例。
2. 每条命令示例 `argv[0] == "lake-console"`。
3. `argv[1]` 必须是当前 CLI 注册命令之一。
4. 不允许出现已废弃命令名，例如 `rebuild-stk-mins-derived`。
5. `GET /api/lake/command-examples` 返回分组、数据集和命令。
6. `dataset_key` 过滤有效。
7. `group_key` 过滤有效。

### 8.2 前端测试

建议增加或调整 smoke：

1. 页面可加载命令示例。
2. 分组切换后数据集列表变化。
3. 数据集切换后命令卡片变化。
4. 页面中不再依赖前端硬编码函数。
5. 复制按钮不会触发写入请求。

### 8.3 文档门禁

新增或修改文档后必须运行：

```bash
python3 scripts/check_docs_integrity.py
```

### 8.4 代码门禁

本需求实现完成后建议运行：

```bash
pytest -q tests/lake_console/test_command_examples_catalog.py
pytest -q tests/lake_console/test_command_examples_api.py
pytest -q tests/lake_console/test_sync_architecture_guardrails.py
python3 scripts/check_docs_integrity.py
```

如修改前端，再补：

```bash
cd lake_console/frontend
npm run build
```

---

## 9. Milestone

### M1：后端命令示例模型

目标：

1. 新增 `LakeCommandExample`。
2. 在 catalog 中为已接入数据集补齐命令示例。
3. 增加维护类虚拟分组。

验收：

1. 所有已接入 Lake 数据集均有命令示例。
2. 命令示例不再散落在前端。

### M2：命令示例 API

目标：

1. 新增 `GET /api/lake/command-examples`。
2. 定义 response schema。
3. 支持 `group_key` / `dataset_key` 过滤。

验收：

1. API 返回结构稳定。
2. API 不读取远程数据库。
3. API 不触发写入。

### M3：前端页面收口

目标：

1. 前端改为调用命令示例 API。
2. 删除前端硬编码 `commandExamples(dataset)`。
3. 支持分组、数据集、命令卡片展示。

验收：

1. 页面只展示 API 返回命令。
2. 命令示例可复制。
3. 页面不执行命令。

### M4：测试与防漂移门禁

目标：

1. 增加 catalog/API/前端 smoke 测试。
2. 防止旧命令名回流。
3. 防止前端重新硬编码命令。

验收：

1. 后端命令示例测试通过。
2. 文档校验通过。
3. 前端构建通过。

---

## 10. 风险与控制

| 风险 | 影响 | 控制方式 |
|---|---|---|
| 命令示例与真实 CLI 漂移 | 用户复制后执行失败 | 用 `argv` 结构化保存，并测试命令名 |
| 前端重新硬编码命令 | 后续继续漂移 | 增加 guardrail，禁止 `commandExamples(dataset)` 类映射 |
| 页面被误解为执行入口 | 用户以为点按钮会同步 | 页面文案明确“只展示，不执行” |
| 维护命令没有数据集归属 | 页面展示断层 | 使用 `__lake_maintenance__` 虚拟数据集 |
| 新增数据集忘记补命令示例 | 页面缺项 | dataset catalog 测试强制每个数据集有示例 |

---

## 11. 当前结论

命令示例页面应该作为 Lake Console 的只读辅助入口，由后端 Lake catalog 提供命令示例，前端只负责展示。

下一步建议先做 M1 + M2，把命令示例事实源和 API 稳住；再做 M3 前端收口。这样能避免命令继续扩散到页面硬编码里。
