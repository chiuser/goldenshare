# Ops 数据集展示目录配置方案 v1（已落地）

## 0. 背景

落地前，数据源页、手动任务、自动任务都在展示“数据集分组”，但分组来源不一致：

1. Tushare / Biying 数据源卡片页使用 `DatasetDefinition.domain.domain_key / domain_display_name` 分组。
2. 今日运行 / 数据状态总览里的数据集卡片也使用同一套 card groups。
3. 手动任务页先读取 `DatasetDefinition.domain.domain_key`，再经过 `GROUP_CONFIG` 映射成另一套组名和顺序。
4. 自动任务页从 catalog API 读取 `domain_display_name`，再在前端聚合成筛选项。

这导致一个用户问题：同一个数据集在不同入口看到的分组可能不同，用户无法稳定建立“我要找的数据在哪里”的心智。

本方案目标是：保留 `DatasetDefinition.domain` 作为底层领域事实，新建 Ops 展示目录配置，统一数据源页、手动任务、自动任务等用户可见目录。

## 0.1 已确认口径

1. V1 只维护一个系统默认展示目录：`ops_dataset_default`。
2. 默认展示目录先接入数据源页、今日运行 / 数据状态总览、手动任务页、自动任务页。
3. 数据集日期完整性审计页也要接入默认展示目录，但优先级排在数据源和任务相关页面之后。
4. API 面向前端的展示目录字段统一使用 `group_*`，不再把 UI 分组字段命名为 `domain_*`。
5. `DatasetDefinition.domain` 保留为底层领域事实，不作为 UI 分组事实。
6. 删除或停止使用 `GROUP_CONFIG` 对 DatasetDefinition.domain 的二次映射。
7. 所有需要在 Ops 用户入口展示的数据集必须配置默认展示目录；缺配置直接测试失败。
8. V1 不实现用户自定义分组，只预留后续模型。
9. 第 10 节中的目标分组表作为默认目录配置的输入依据。

## 1. 设计原则

1. `DatasetDefinition.domain` 只表达数据集自身领域事实，不再承担运营后台页面目录职责。
2. 用户可见分组由 Ops 展示目录配置提供，属于 `src/ops`，不写入 `src/foundation`。
3. 前端不维护数据集分类表，只消费后端返回的展示目录结果。
4. 同一个默认展示目录应被数据源页、手动任务、自动任务复用，避免同一个数据集在不同入口“换位置”。
5. 新增数据集必须同时补齐 DatasetDefinition 和 Ops 展示目录配置，否则测试失败。
6. V1 只实现系统默认目录，不实现用户自定义目录。

## 2. 概念边界

| 概念 | 归属 | 作用 | 是否面向用户 |
| --- | --- | --- | --- |
| `DatasetDefinition.domain` | `src/foundation/datasets/**` | 数据集底层领域事实，用于治理、审计、架构分析 | 间接 |
| Ops 展示目录配置 | `src/ops/**` | 决定运营后台里数据集如何分组、排序、显示或隐藏 | 是 |
| 用户自定义目录 | 后续 `ops.*` 表 | 覆盖系统默认目录，支持个人视图 | 是 |

## 3. V1 范围

### 3.1 必收入口

| 页面 / 能力 | 当前分组来源 | V1 目标来源 |
| --- | --- | --- |
| Tushare 数据源页 | 落地前：dataset card API 的 domain groups | Ops 展示目录配置 |
| Biying 数据源页 | 落地前：dataset card API 的 domain groups | Ops 展示目录配置 |
| 今日运行 / 数据状态总览中的数据集卡片 | 落地前：dataset card API 的 domain groups | Ops 展示目录配置 |
| 手动任务页 | 落地前：`DatasetDefinition.domain` + `GROUP_CONFIG` | Ops 展示目录配置 |
| 自动任务页动作选择 | 落地前：catalog API `domain_display_name` | Ops 展示目录配置 |
| 数据集日期完整性审计页 | 落地前：审计规则 API 的 `domain_key/domain_display_name` | Ops 展示目录配置 |

### 3.2 分阶段接入顺序

| 阶段 | 范围 | 说明 |
| --- | --- | --- |
| P1 | 数据源页、今日运行 / 数据状态总览、手动任务页、自动任务页 | 先解决用户找数据和发起维护任务时的分组不一致 |
| P2 | 数据集日期完整性审计页 | 接入同一展示目录，避免审计入口和数据源 / 任务入口分组不一致 |

### 3.3 暂不改入口

| 页面 / 能力 | 保持原因 |
| --- | --- |
| freshness 内部计算 | 这是状态观测模型，不应被 UI 展示目录反向影响 |
| 日报 / 健康报告内部统计 | 先保持 domain 口径；若后续希望面向用户展示，再接展示目录 |

## 4. 数据模型设计

V1 先采用后端代码配置，不建数据库表。原因：

1. 现在核心目标是统一系统默认目录，不是立即支持个人自定义。
2. 代码配置可以被测试强约束，新增数据集遗漏配置时能在 CI 阶段发现。
3. 后续迁表时，代码配置可以作为默认 seed，不影响模型方向。

### 4.1 配置文件位置

```text
src/ops/catalog/dataset_catalog_views.py
```

如果当前 `src/ops/catalog` 目录不存在，则新增该目录和 `AGENTS.md`，说明这里归属 Ops 用户可见目录配置，不允许写入 foundation。

V1 中 `OPS_DATASET_DEFAULT_VIEW_KEY = "ops_dataset_default"` 与它对应的分组、数据集归属、排序信息都存放在这个代码配置文件中，不写数据库表。建议结构如下：

```python
OPS_DATASET_DEFAULT_VIEW_KEY = "ops_dataset_default"

OPS_DATASET_DEFAULT_VIEW = DatasetCatalogView(
    view_key=OPS_DATASET_DEFAULT_VIEW_KEY,
    groups=(...),
    items=(...),
)
```

`groups` 存储展示分组定义，`items` 存储 `dataset_key -> group_key` 的归属和组内顺序。

### 4.2 配置结构

```python
@dataclass(frozen=True, slots=True)
class DatasetCatalogGroup:
    group_key: str
    group_label: str
    group_order: int
    description: str = ""


@dataclass(frozen=True, slots=True)
class DatasetCatalogItem:
    dataset_key: str
    group_key: str
    item_order: int
    visible: bool = True


@dataclass(frozen=True, slots=True)
class DatasetCatalogView:
    view_key: str
    groups: tuple[DatasetCatalogGroup, ...]
    items: tuple[DatasetCatalogItem, ...]
```

### 4.3 默认 view

V1 建议只维护一个系统默认目录：

```python
OPS_DATASET_DEFAULT_VIEW_KEY = "ops_dataset_default"
```

所有数据集用户入口默认使用它：

1. 数据源页按 `source_key` 过滤可见数据集，再按默认目录分组。
2. 手动任务页按 manual-enabled dataset actions 过滤，再按默认目录分组。
3. 自动任务页按 schedule-enabled dataset actions 过滤，再按默认目录分组。

V1 不新增其它 view。后续如果确实需要某个页面有不同目录，可再评审新增：

```text
ops_dataset_source_page
ops_manual_task
ops_auto_task
```

当前阶段不拆多个 view，因为本轮目标是先把多入口口径统一。

## 5. API 与后端改造

### 5.1 内部解析器

新增 Ops 层解析器：

```text
src/ops/catalog/dataset_catalog_view_resolver.py
```

职责：

1. 读取 `DatasetDefinition` 注册表，校验所有可见数据集都有目录配置。
2. 根据 view 配置返回 `dataset_key -> group`、`group_key -> group_label/order`。
3. 支持按 `source_key`、`manual_enabled`、`schedule_enabled` 过滤。
4. 输出已经排序好的 group 和 item。

### 5.2 数据源卡片 API

当前 `DatasetCardQueryService` 已经把卡片分成 groups 返回。V1 修改方式：

1. card fact 仍然保留 `domain_key / domain_display_name`，用于治理和详情补充。
2. card response 的外层 `groups` 改为展示目录 group。
3. item 内新增或保留底层 domain 字段，供详情页或调试使用。

建议响应语义：

```json
{
  "groups": [
    {
      "group_key": "market_data",
      "group_label": "行情数据",
      "group_order": 20,
      "items": [
        {
          "dataset_key": "daily",
          "display_name": "股票日线",
          "group_key": "market_data",
          "group_label": "行情数据",
          "domain_key": "equity_market",
          "domain_display_name": "股票行情"
        }
      ]
    }
  ]
}
```

说明：API 面向前端的外层展示目录字段必须改为 `group_key/group_label/group_order`。item 内可以保留 `domain_key/domain_display_name` 作为底层领域事实，但不得再用 domain 字段表达 UI 分组。

### 5.3 手动任务 API

落地前，手动任务页分组来自 `ManualActionQueryService.GROUP_CONFIG`。

V1 调整：

1. dataset action 的分组来自 Ops 展示目录配置。
2. 删除或停止使用 `GROUP_CONFIG` 对 DatasetDefinition.domain 的二次映射；dataset action 不允许静默落入“其他”。
3. workflow 仍作为非数据集能力单独进入 `工作流` 或 `维护动作` 组。

响应继续可以是：

```json
{
  "groups": [
    {
      "group_key": "market_data",
      "group_label": "行情数据",
      "group_order": 20,
      "actions": []
    }
  ]
}
```

### 5.4 自动任务页

落地前，自动任务页从 catalog API 中读取 `domain_display_name` 生成筛选项。

V1 调整：

1. catalog API 的 dataset actions 增加展示目录字段：
   - `group_key`
   - `group_label`
   - `group_order`
   - `item_order`
2. 前端自动任务页按 `group_label` 筛选。
3. workflow 保持独立 group，不混进数据集目录。

## 6. 前端改造

### 6.1 数据源页

当前文件：

```text
frontend/src/pages/ops-v21-source-page.tsx
```

V1 调整：

1. 不再把 API 外层 group 当作 domain。
2. 用 `group_key/group_label` 渲染 SectionCard。
3. 卡片内部如需展示底层领域，可显示 `domain_display_name`，但不作为分组标题。

### 6.2 手动任务页

当前文件：

```text
frontend/src/pages/ops-v21-task-manual-tab.tsx
```

V1 调整：

1. 数据分组下拉使用后端返回的展示目录 groups。
2. 选择维护对象时，同一个数据集与数据源页保持同组。
3. 文案继续表达“数据分组 / 维护对象”，不暴露 domain。

### 6.3 自动任务页

当前文件：

```text
frontend/src/pages/ops-v21-task-auto-tab.tsx
```

V1 调整：

1. 动作筛选使用 catalog group，而不是 domain。
2. dataset action 与 manual action 的分组名称保持一致。
3. workflow 使用独立组名。

### 6.4 数据集日期完整性审计页

当前文件：

```text
frontend/src/pages/ops-v21-dataset-audit-page.tsx
```

V1 调整：

1. P2 阶段接入默认展示目录。
2. 审计规则列表按 `group_key/group_label` 过滤和展示。
3. item 内保留 `domain_key/domain_display_name`，用于说明底层领域事实。
4. 审计能力的 supported / unsupported 分组不变，目录分组只作为筛选维度。

## 7. 测试门禁

### 7.1 架构测试

新增测试：

1. 所有 manual-enabled dataset 都必须在默认展示目录中配置。
2. 所有 schedule-enabled dataset 都必须在默认展示目录中配置。
3. 所有 source page 可见 dataset 都必须在默认展示目录中配置。
4. 展示目录不能引用不存在的 dataset_key。
5. 展示目录 group_key 不允许重复但 label 不一致。
6. 展示目录 group_key 不允许重复但 group_order 不一致。
7. 前端数据源页、手动任务页、自动任务页、数据集审计页不得自行维护 dataset_key 到分组的映射。

### 7.2 API 测试

覆盖：

1. Tushare 数据源卡片按展示目录分组。
2. Biying 数据源卡片按展示目录分组。
3. 手动任务页按展示目录分组。
4. 自动任务 catalog 返回展示目录字段。
5. 数据集审计页规则返回展示目录字段。
6. 未配置展示目录的数据集应在测试中失败，不允许静默落到“其他”。

### 7.3 前端测试

覆盖：

1. 数据源页展示 `group_label`。
2. 手动任务页同一数据集出现在同一 `group_label`。
3. 自动任务页筛选项来自 catalog group。
4. 数据集审计页筛选项来自 catalog group。

## 8. 落地里程碑

| Milestone | 目标 | 主要改动 | 验收 |
| --- | --- | --- | --- |
| M1 | 固定目录模型 | 新增 Ops 展示目录配置 dataclass 与默认 view | 类型与单元测试通过 |
| M2 | 补齐默认目录 | 按本文件第 10 节评审后的目标分组填配置 | 所有 dataset_key 都有配置 |
| M3 | 数据源卡片接入 | `DatasetCardQueryService` 改按展示目录分组 | Tushare/Biying 页面分组一致 |
| M4 | 手动任务接入 | 移除 dataset action 对 `GROUP_CONFIG` 的依赖 | 手动任务与数据源页同组 |
| M5 | 自动任务接入 | catalog API 增加展示目录字段，前端改筛选 | 自动任务与手动任务同组 |
| M6 | 数据集审计页接入 | 审计规则 API 与前端筛选改用展示目录 | 审计页与数据源 / 任务入口同组 |
| M7 | 门禁收口 | 增加架构/API/前端测试 | CI 通过 |
| M8 | 文档收口 | 更新 Ops 当前契约和 API 文档 | 文档不再把 domain 当 UI 分组 |

当前实现状态：M1-M8 已按本方案落地。默认展示目录配置位于 `src/ops/catalog/dataset_catalog_views.py`，解析与校验位于 `src/ops/catalog/dataset_catalog_view_resolver.py`。

## 9. 未来用户自定义分组预留

V1 不实现用户自定义分组，也不建表。后续如要支持，可按以下方向评审迁移：

```text
ops.dataset_catalog_group
ops.dataset_catalog_item
ops.user_dataset_catalog_group
ops.user_dataset_catalog_item
```

建议未来语义：

1. 系统默认目录永远存在，作为用户未配置时的 fallback。
2. 用户自定义只影响当前用户的页面展示，不改变 DatasetDefinition。
3. 用户自定义不允许隐藏关键治理入口，只能影响数据集列表组织方式。

## 9.1 当前目标分组一致性检查

已根据第 10 节表格做初步检查，发现并处理以下问题：

| 问题 | 处理 |
| --- | --- |
| `equity_market` 同时出现 `A股行情` 和 `股票行情` | 统一为 `A股行情` |
| `broke_recommendation` 疑似拼写错误 | 统一为 `broker_recommendation` |
| `moneyflow_cnt_ths`、`moneyflow_ind_ths` 的目标 key 缺少反引号 | 统一表格格式 |
| `limit_board` 和 `leader_board` 曾同为顺序 4 | 已统一为 `leader_board=4`、`limit_board=5` |

V1 测试中应增加约束：同一个 `group_key` 必须对应唯一 `group_label` 和 `group_order`。

## 10. 当前分组清单与目标展示分组（已填写，待确认）

说明：

1. 本表按当前工作区 `DatasetDefinition` 注册表导出。
2. `当前 domain` 是底层领域事实。
3. `手动任务当前分组` 是落地前 `GROUP_CONFIG` 映射后的结果。
4. `目标展示分组 key`、`目标展示分组名称`、`目标顺序` 三列为当前拟采用的 Ops 默认展示目录。

| dataset_key | 中文名 | 数据源 | 当前 domain_key | 当前 domain_display_name | 手动任务当前分组 | 目标展示分组 key | 目标展示分组名称 | 目标顺序 | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `biying_equity_daily` | BIYING 股票日线 | `biying` | `equity_market` | 股票行情 | equity_market / 股票行情 | `equity_market` | A股行情 | 2 |  |
| `biying_moneyflow` | BIYING 资金流向 | `biying` | `moneyflow` | 资金流向 | moneyflow / 资金流向 | `moneyflow` | 资金流向 | 8 |  |
| `stock_basic` | 股票主数据 | `biying,tushare` | `reference_data` | 基础主数据 | reference_data / 基础主数据 | `reference_data` | A股基础数据 | 1 |  |
| `dc_index` | 东方财富板块列表 | `tushare` | `board_theme` | 板块 / 题材 | board_theme / 板块 / 题材 | `board_theme` | 板块 / 题材 | 3 |  |
| `dc_member` | 东方财富板块成分 | `tushare` | `board_theme` | 板块 / 题材 | board_theme / 板块 / 题材 | `board_theme` | 板块 / 题材 | 3 |  |
| `dc_daily` | 东方财富板块日线行情 | `tushare` | `board_theme` | 板块 / 题材 | board_theme / 板块 / 题材 | `board_theme` | 板块 / 题材 | 3 |  |
| `dc_hot` | 东方财富热榜 | `tushare` | `board_theme` | 板块 / 题材 | board_theme / 板块 / 题材 | `leader_board` | 榜单 | 4 |  |
| `ths_index` | 同花顺板块列表 | `tushare` | `board_theme` | 板块 / 题材 | board_theme / 板块 / 题材 | `board_theme` | 板块 / 题材 | 3 |  |
| `ths_member` | 同花顺板块成分 | `tushare` | `board_theme` | 板块 / 题材 | board_theme / 板块 / 题材 | `board_theme` | 板块 / 题材 | 3 |  |
| `ths_daily` | 同花顺板块日线行情 | `tushare` | `board_theme` | 板块 / 题材 | board_theme / 板块 / 题材 | `board_theme` | 板块 / 题材 | 3 |  |
| `ths_hot` | 同花顺热榜 | `tushare` | `board_theme` | 板块 / 题材 | board_theme / 板块 / 题材 | `leader_board` | 榜单 | 4 |  |
| `kpl_concept_cons` | 开盘啦板块成分 | `tushare` | `board_theme` | 板块 / 题材 | board_theme / 板块 / 题材 | `board_theme` | 板块 / 题材 | 3 |  |
| `kpl_list` | 开盘啦榜单 | `tushare` | `board_theme` | 板块 / 题材 | board_theme / 板块 / 题材 | `leader_board` | 榜单 | 4 |  |
| `stock_st` | ST股票列表 | `tushare` | `equity_market` | 股票行情 | equity_market / 股票行情 | `reference_data` | A股基础数据 | 1 |  |
| `broker_recommend` | 券商月度金股推荐 | `tushare` | `equity_market` | 股票行情 | equity_market / 股票行情 | `broker_recommendation` | 券商推荐 | 9 |  |
| `limit_list_ths` | 同花顺涨停名单 | `tushare` | `equity_market` | 股票行情 | equity_market / 股票行情 | `limit_board` | 涨跌停榜 | 5 |  |
| `adj_factor` | 复权因子 | `tushare` | `equity_market` | 股票行情 | equity_market / 股票行情 | `equity_market` | A股行情 | 2 |  |
| `block_trade` | 大宗交易 | `tushare` | `equity_market` | 股票行情 | equity_market / 股票行情 | `equity_market` | A股行情 | 2 |  |
| `suspend_d` | 每日停复牌信息 | `tushare` | `equity_market` | 股票行情 | equity_market / 股票行情 | `reference_data` | A股基础数据 | 1 |  |
| `daily_basic` | 每日指标 | `tushare` | `equity_market` | 股票行情 | equity_market / 股票行情 | `equity_market` | A股行情 | 2 |  |
| `stk_limit` | 每日涨跌停价格 | `tushare` | `equity_market` | 股票行情 | equity_market / 股票行情 | `reference_data` | A股基础数据 | 1 |  |
| `limit_list_d` | 每日涨跌停名单 | `tushare` | `equity_market` | 股票行情 | equity_market / 股票行情 | `limit_board` | 涨跌停榜 | 5 |  |
| `cyq_perf` | 每日筹码及胜率 | `tushare` | `equity_market` | 股票行情 | equity_market / 股票行情 | `technical_indicators` | 技术指标 | 13 |  |
| `limit_cpt_list` | 涨停概念列表 | `tushare` | `equity_market` | 股票行情 | equity_market / 股票行情 | `limit_board` | 涨跌停榜 | 5 |  |
| `stk_nineturn` | 神奇九转指标 | `tushare` | `equity_market` | 股票行情 | equity_market / 股票行情 | `technical_indicators` | 技术指标 | 13 |  |
| `stk_mins` | 股票历史分钟行情 | `tushare` | `equity_market` | 股票行情 | equity_market / 股票行情 | `equity_market` | A股行情 | 2 |  |
| `stk_period_bar_week` | 股票周线行情 | `tushare` | `equity_market` | 股票行情 | equity_market / 股票行情 | `equity_market` | A股行情 | 2 |  |
| `stk_period_bar_adj_week` | 股票周线行情（复权） | `tushare` | `equity_market` | 股票行情 | equity_market / 股票行情 | `equity_market` | A股行情 | 2 |  |
| `stk_factor_pro` | 股票技术面因子(专业版) | `tushare` | `equity_market` | 股票行情 | equity_market / 股票行情 | `technical_indicators` | 技术指标 | 13 |  |
| `daily` | 股票日线 | `tushare` | `equity_market` | 股票行情 | equity_market / 股票行情 | `equity_market` | A股行情 | 2 |  |
| `stk_period_bar_month` | 股票月线行情 | `tushare` | `equity_market` | 股票行情 | equity_market / 股票行情 | `equity_market` | A股行情 | 2 |  |
| `stk_period_bar_adj_month` | 股票月线行情（复权） | `tushare` | `equity_market` | 股票行情 | equity_market / 股票行情 | `equity_market` | A股行情 | 2 |  |
| `margin` | 融资融券汇总 | `tushare` | `equity_market` | 股票行情 | equity_market / 股票行情 | `equity_market` | A股行情 | 2 |  |
| `limit_step` | 连板梯队 | `tushare` | `equity_market` | 股票行情 | equity_market / 股票行情 | `limit_board` | 涨跌停榜 | 5 |  |
| `top_list` | 龙虎榜 | `tushare` | `equity_market` | 股票行情 | equity_market / 股票行情 | `equity_market` | A股行情 | 2 |  |
| `etf_index` | ETF 跟踪指数 | `tushare` | `index_fund` | 指数 / ETF | index_fund / 指数 / ETF | `etf_fund` | ETF基金 | 7 |  |
| `fund_adj` | 基金复权因子 | `tushare` | `index_fund` | 指数 / ETF | index_fund / 指数 / ETF | `etf_fund` | ETF基金 | 7 |  |
| `fund_daily` | 基金日线行情 | `tushare` | `index_fund` | 指数 / ETF | index_fund / 指数 / ETF | `etf_fund` | ETF基金 | 7 |  |
| `index_weekly` | 指数周线 | `tushare` | `index_fund` | 指数 / ETF | index_fund / 指数 / ETF | `index_market_data` | A股指数行情 | 6 |  |
| `index_basic` | 指数基础信息 | `tushare` | `index_fund` | 指数 / ETF | index_fund / 指数 / ETF | `reference_data` | A股基础数据 | 1 |  |
| `index_weight` | 指数成分权重 | `tushare` | `index_fund` | 指数 / ETF | index_fund / 指数 / ETF | `reference_data` | A股基础数据 | 1 |  |
| `index_daily` | 指数日线行情 | `tushare` | `index_fund` | 指数 / ETF | index_fund / 指数 / ETF | `index_market_data` | A股指数行情 | 6 |  |
| `index_monthly` | 指数月线 | `tushare` | `index_fund` | 指数 / ETF | index_fund / 指数 / ETF | `index_market_data` | A股指数行情 | 6 |  |
| `index_daily_basic` | 指数每日指标 | `tushare` | `index_fund` | 指数 / ETF | index_fund / 指数 / ETF | `index_market_data` | A股指数行情 | 6 |  |
| `dividend` | 分红送股 | `tushare` | `low_frequency` | 低频数据 | event_stats / 榜单 / 事件 | `reference_data` | A股基础数据 | 1 |  |
| `stk_holdernumber` | 股东户数 | `tushare` | `low_frequency` | 低频数据 | event_stats / 榜单 / 事件 | `reference_data` | A股基础数据 | 1 |  |
| `moneyflow` | 个股资金流向 | `tushare` | `moneyflow` | 资金流向 | moneyflow / 资金流向 | `moneyflow` | 资金流向 | 8 |  |
| `moneyflow_dc` | 个股资金流向(DC) | `tushare` | `moneyflow` | 资金流向 | moneyflow / 资金流向 | `moneyflow` | 资金流向 | 8 |  |
| `moneyflow_ths` | 个股资金流向(THS) | `tushare` | `moneyflow` | 资金流向 | moneyflow / 资金流向 | `moneyflow` | 资金流向 | 8 |  |
| `moneyflow_mkt_dc` | 市场资金流向(DC) | `tushare` | `moneyflow` | 资金流向 | moneyflow / 资金流向 | `moneyflow` | 资金流向 | 8 |  |
| `moneyflow_ind_dc` | 板块资金流向(DC) | `tushare` | `moneyflow` | 资金流向 | moneyflow / 资金流向 | `moneyflow` | 资金流向 | 8 |  |
| `moneyflow_cnt_ths` | 概念板块资金流向(THS) | `tushare` | `moneyflow` | 资金流向 | moneyflow / 资金流向 | `moneyflow` | 资金流向 | 8 |  |
| `moneyflow_ind_ths` | 行业资金流向(THS) | `tushare` | `moneyflow` | 资金流向 | moneyflow / 资金流向 | `moneyflow` | 资金流向 | 8 |  |
| `cctv_news` | 新闻联播文字稿 | `tushare` | `news` | 新闻资讯 | other / 其他 | `news` | 新闻资讯 | 10 |  |
| `etf_basic` | ETF 基础信息 | `tushare` | `reference_data` | 基础主数据 | reference_data / 基础主数据 | `reference_data` | A股基础数据 | 1 |  |
| `trade_cal` | 交易日历 | `tushare` | `reference_data` | 基础主数据 | reference_data / 基础主数据 | `reference_data` | A股基础数据 | 1 |  |
| `hk_basic` | 港股基础信息 | `tushare` | `reference_data` | 基础主数据 | reference_data / 基础主数据 | `hk_reference_data` | 港股基础数据 | 11 |  |
| `us_basic` | 美股基础信息 | `tushare` | `reference_data` | 基础主数据 | reference_data / 基础主数据 | `us_reference_data` | 美股基础数据 | 12 |  |

## 11. 拍板结论

| 编号 | 问题 | 结论 |
| --- | --- | --- |
| D1 | V1 是否只维护一个默认展示目录 | 是，只维护 `ops_dataset_default` |
| D2 | 数据集审计页是否也接展示目录 | 接入，但排在数据源和任务相关页面之后 |
| D3 | API 字段是否从 `domain_*` 改成 `group_*` | 是，用户可见展示目录字段统一用 `group_*` |
| D4 | 未配置展示目录的数据集如何处理 | 测试失败，不静默兜底 |
| D5 | 用户自定义分组是否本轮实现 | 不实现 |
