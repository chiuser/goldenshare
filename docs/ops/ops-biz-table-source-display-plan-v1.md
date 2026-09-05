# Ops Biz 表数据源展示方案 v1（一期已实现，历史基线）

> 当前说明：本文保留 2026-05-10 首次接入 `wealth_market_turnover_snapshot` 的一期设计与实现记录。Biz 数据集自动投影、14 张新增业务表和后续开发模板，统一以 [Ops Biz 数据集自动投影与 14 表展示技术方案 v1](/Users/congming/github/goldenshare/docs/ops/ops-biz-dataset-auto-projection-plan-v1.md) 为代码已实现、待部署验收的当前主案；本文的一期“只读、只纳入一张表”边界不再代表当前目标。本文后文出现的“财势乾坤”分组仅是一期历史记录，当前实现已将成交额分钟快照并入“数据集市”并删除该分组。

## 0. 背景

现在运营后台的数据源入口主要面向外部数据来源：

1. `Tushare`
2. `Biying`

随着财势乾坤业务系统推进，仓库内开始出现我们自己生产和维护的业务派生表，例如：

```text
core_serving.wealth_market_turnover_snapshot
```

这类表不是外部源站数据集，也不应该被包装成 Tushare/Biying 数据集；但它们对业务页面很关键，也需要在数据运营管理综合平台中被看见、被观察、被排障。

本方案目标是：把这类自建业务表作为一个新的数据源类别展示出来，页面上与 `Tushare`、`Biying` 平级，名称为 `Biz数据集`。

## 1. 一期目标

一期只做读和展示。

### 1.1 要做

1. 在运营后台数据源区域新增 `Biz数据集` 入口。
2. 复用现有数据源卡片视觉样式，展示 Biz 表状态。
3. 首批纳入：
   - `core_serving.wealth_market_turnover_snapshot`
4. 卡片展示至少包含：
   - 显示名
   - 表名
   - 当前状态
   - 最新业务日期
   - 时间范围
   - 最近构建/更新时间
   - 简短状态说明
5. 后端负责统一返回卡片事实，前端只负责展示。

### 1.2 不做

1. 不新增写入能力。
2. 不新增手动同步入口。
3. 不新增自动任务。
4. 不接入 TaskRun 创建链路。
5. 不把 Biz 表注册进 `DatasetDefinition`。
6. 不把 Biz 表伪装成 Tushare/Biying 数据集。
7. 不新增复杂配置后台。
8. 不做用户自定义分组。

## 2. 关键概念

### 2.1 Biz 表

Biz 表指由本系统自己生成、服务上层业务页面或业务 API 的派生表。

它的特征是：

1. 数据不是直接从外部源站拉取后原样存储。
2. 数据通常来自 raw/core/core_serving 中已有数据的聚合、物化、裁剪或业务快照。
3. 表的可用性直接影响业务页面。
4. 需要被运营后台观测，但一期不需要由运营后台发起写入。

### 2.2 与 DatasetDefinition 的关系

`DatasetDefinition` 是外部数据集和数据维护链路的事实源。

Biz 表不是外部数据集，不应强行塞进 `src/foundation/datasets/**`。否则会带来两个问题：

1. 误导运营后台以为它可以像 Tushare 数据集一样同步。
2. 让 foundation 承担上层业务派生表目录职责，破坏边界。

因此 Biz 表目录当前归属 `src/ops/catalog/**`，作为运营后台展示目录的一部分。

### 2.3 与现有数据源卡片的关系

Biz 表可以复用现有数据源卡片的展示风格，但不能复用“raw 数据源状态”的语义。

前端已把早期偏 raw 的数据源页文案从：

```text
仅展示数据源侧原始下载状态（raw）
```

调整为更通用的：

```text
展示当前来源下的数据资产状态。
```

这样 `Tushare/Biying` 仍展示 raw 数据源状态，`Biz数据集` 展示业务派生表状态。

## 3. 一期对象清单

| biz_table_key | 显示名 | 表名 | 所属业务 | 观测日期字段 | 最近更新时间字段 | 一期展示 |
|---|---|---|---|---|---|---|
| `wealth_market_turnover_snapshot` | 成交额分钟快照 | `core_serving.wealth_market_turnover_snapshot` | 财势乾坤 / 市场总览 / 成交额总览 | `trade_date` | `built_at` | 是 |

## 4. 当前后端结构

### 4.1 Biz 表目录配置

当前 Ops 层代码配置：

```text
src/ops/catalog/biz_table_catalog.py
```

职责：

1. 维护 Biz 表清单。
2. 定义每张 Biz 表的显示名、表名、所属分组、观测字段和状态规则。
3. 只用于运营后台展示，不驱动写入。

当前结构：

```python
@dataclass(frozen=True, slots=True)
class BizTableCatalogItem:
    table_key: str
    display_name: str
    table_name: str
    group_key: str
    group_label: str
    group_order: int
    item_order: int
    observed_date_column: str
    observed_at_column: str | None
    status_policy_key: str
```

一期配置：

```python
BizTableCatalogItem(
    table_key="wealth_market_turnover_snapshot",
    display_name="成交额分钟快照",
    table_name="core_serving.wealth_market_turnover_snapshot",
    group_key="wealth_market",
    group_label="财势乾坤",
    group_order=90,
    item_order=10,
    observed_date_column="trade_date",
    observed_at_column="built_at",
    status_policy_key="wealth_turnover_snapshot",
)
```

### 4.2 Biz 表卡片查询服务

当前实现：

```text
src/ops/queries/biz_table_card_query_service.py
```

职责：

1. 读取 Biz 表目录配置。
2. 对每张表执行只读观测查询。
3. 返回与数据源卡片兼容的卡片数据。
4. 不写任何状态表。
5. 不依赖 TaskRun。

### 4.3 与现有 DatasetCardQueryService 的集成方式

当前复用现有接口：

```text
GET /api/v1/ops/dataset-cards?source_key=biz_tableset
```

原因：

1. 前端数据源页已经围绕 `dataset-cards` 卡片响应渲染。
2. 一期目标是“展示平级数据源”，不是重做 Ops 卡片体系。
3. 可以用最小前后端改动接入。

但实现上必须注意：

1. `source_key=biz_tableset` 时走 Biz 表查询分支。
2. 不能把 Biz 表塞进 `DatasetDefinition`。
3. 不能让 Biz 表出现在手动任务、自动任务、数据集维护动作中。

后续如果 Biz 表持续增多，可单独抽象为：

```text
GET /api/v1/ops/data-asset-cards?source_key=biz_tableset
```

当前未新建 `data-asset-cards` API，避免前端重复实现一套卡片页。

## 5. 一期响应映射

为复用现有卡片组件，一期可继续返回 `DatasetCardItem` 形状，但字段语义要固定如下。

| 字段 | Biz 表一期口径 |
|---|---|
| `card_key` | `biz_table_key` |
| `dataset_key` | `biz_table_key`，仅用于卡片唯一键，不代表 DatasetDefinition |
| `detail_dataset_key` | 同 `biz_table_key`；一期不跳转数据集详情 |
| `resource_key` | 同 `biz_table_key`；一期不用于 TaskRun |
| `display_name` | Biz 表显示名 |
| `group_key/group_label` | Biz 表展示分组，例如 `wealth_market / 财势乾坤` |
| `domain_key/domain_display_name` | `biz_tableset / Biz数据集` |
| `status` | 后端按表观测结果计算 |
| `freshness_status` | 与 `status` 同步或更细粒度表达 |
| `delivery_mode` | `biz_table_snapshot` |
| `delivery_mode_label` | `业务派生表` |
| `delivery_mode_tone` | `info` |
| `layer_plan` | `biz_tableset` |
| `freshness_policy` | `continuous_open_day`，由服务端按 Biz 表状态策略设置；不返回 `cadence` |
| `raw_table/raw_table_label` | `null`；前端展示应使用 `target_table` |
| `target_table` | 真实表名 |
| `latest_business_date` | 最新可用业务日期 |
| `earliest_business_date` | 最早可用业务日期 |
| `latest_observed_at` | 最新观测时间，例如最新 `built_at` 或最新分钟点时间 |
| `earliest_observed_at` | 一期可为空 |
| `last_sync_date` | 一期可为空，避免误导为外部同步 |
| `latest_success_at` | 最新成功构建时间 |
| `expected_business_date` | 按状态规则推导的期望业务日期 |
| `lag_days` | `expected_business_date - latest_business_date` |
| `freshness_note` | 状态说明 |
| `primary_action_key` | `null` |
| `auto_schedule_*` | 全部为无自动任务状态 |
| `probe_*` | 一期全部为 0 |
| `std_mapping_configured/std_cleansing_configured/resolution_policy_configured` | 全部 false |
| 分层观测字段 | 已退场，不再返回 |

说明：

1. 这里复用 `DatasetCardItem` 是一期工程折中，不代表 Biz 表被纳入 DatasetDefinition。
2. 后续如果卡片体系扩展为 `DataAssetCardItem`，再把字段名从 dataset 语义中解耦。

## 6. `wealth_market_turnover_snapshot` 状态口径

### 6.1 构建与消费口径

`wealth_market_turnover_snapshot` 的生产和消费容易混淆，当前代码口径如下：

1. 构建命令 `wealth-build-turnover-snapshot` 不传 `--freq` 时，会分别构建 `1 / 5 / 15 / 30 / 60` 五套分钟快照。
2. 每套快照只读取同频率的 `raw_tushare.stk_mins`，筛选条件是 `freq + trade_time 当日窗口`。
3. 每套快照按 `trade_time` 聚合全市场 `amount / vol / security_count`，并以 `type + market + trade_date + freq` 写入 `core_serving.wealth_market_turnover_snapshot`。
4. 财势乾坤市场成交额页的盘中累计曲线默认读取 `freq=30` 的 READY 快照。
5. 成交额页的今日成交额、昨日成交额、5 日均值、20 日均值和历史走势来自 `core_serving.equity_daily_bar.amount` 聚合，不来自分钟快照表。
6. Biz 数据集卡片的 `latest_business_date` 只看 READY 快照中最大的 `trade_date`，不代表五个频率之外还有其他业务口径。

### 6.2 观测 SQL 口径

当前只读取 READY 快照：

```sql
select
  min(trade_date) as earliest_business_date,
  max(trade_date) as latest_business_date,
  max(built_at) as latest_success_at,
  max(latest_trade_time) as latest_observed_at,
  count(*) as row_count
from core_serving.wealth_market_turnover_snapshot
where type = 'stock'
  and market = 'CN_A'
  and build_status = 'READY';
```

说明：这里的 `row_count` 是快照行数。正常每个 `trade_date` 最多对应 `1 / 5 / 15 / 30 / 60` 五行，不是源分钟线行数，也不是股票数。

### 6.3 期望日期口径

当前沿用财势乾坤市场页的盘后静态数据口径：

1. 以 `core_serving.trade_calendar` 为交易日事实。
2. 当前日期是交易日，且未到盘后可用时间前，期望日期为前一个开市交易日。
3. 当前日期是交易日，且已到盘后可用时间后，期望日期为当前交易日。
4. 当前日期不是交易日，期望日期为最近一个开市交易日。
5. 盘后可用时间默认 `20:00`，后续可配置。

当前实现通过 `src.foundation.models.core.trade_calendar.TradeCalendar` 模型访问交易日历；该模型实际落库 schema 是 `core_serving`。

### 6.4 状态计算

| 条件 | `status` | `freshness_status` | 说明 |
|---|---|---|---|
| 无 READY 行 | `unknown` | `unknown` | 表存在但暂无可用快照 |
| `latest_business_date >= expected_business_date` | `healthy` | `fresh` | 数据可用 |
| `latest_business_date < expected_business_date` 且 `lag_days <= 1` | `warning` | `lagging` | 轻度滞后 |
| `latest_business_date < expected_business_date` 且 `lag_days > 1` | `stale` | `stale` | 严重滞后 |

`freshness_note` 示例：

```text
最新快照 2026-05-08，期望 2026-05-08，已就绪。
最新快照 2026-05-07，期望 2026-05-08，滞后 1 个交易日。
暂无 READY 快照。
```

## 7. 当前前端实现范围

### 7.1 新增 Biz 表入口

当前新增：

```text
frontend/src/pages/ops-v21-biz-table-page.tsx
```

内容：

```tsx
<OpsV21SourcePage sourceKey="biz_tableset" title="数据集 · Biz数据集" />
```

同时修改：

```text
frontend/src/app/router.tsx
frontend/src/app/shell.tsx
frontend/src/pages/ops-v21-source-page.tsx
frontend/src/shared/api/types.ts
```

### 7.2 SourcePage 文案调整

`OpsV21SourcePage` 早期文案偏 raw 数据源，后续已收口为数据资产健康度语义：

```text
仅展示数据源侧原始下载状态（raw）。这里不展示 std / serving。
```

当前已改为由调用方传入描述：

```tsx
<OpsV21SourcePage
  sourceKey="biz_tableset"
  title="数据集 · Biz数据集"
  description="展示本系统自建业务派生表的只读状态。暂不提供写入和调度入口。"
/>
```

Tushare/Biying 页面仍可传原说明。

### 7.3 卡片字段展示

Biz 表卡片上：

1. 表名显示 `target_table`，不显示 raw 表。
2. “最近同步”文案显示为“最近构建成功时间”。
3. `primary_action_key=null` 时不显示“去操作”按钮。
4. 不显示“未配置自动更新”作为负面状态，可改为“只读展示”。

说明：为了避免影响 Tushare/Biying，前端可以根据 `delivery_mode === "biz_table_snapshot"` 只对 Biz 表卡片切换文案。

## 8. 已落地代码

### 8.1 后端

已落地文件：

```text
src/ops/catalog/biz_table_catalog.py
src/ops/queries/biz_table_card_query_service.py
src/ops/queries/dataset_card_query_service.py
src/foundation/datasets/source_registry.py
tests/web/test_ops_biz_table_cards_api.py
```

改造说明：

1. `source_registry.py` 是否新增 `biz_tableset / Biz数据集` 需要谨慎。
   - 如果只用于 Ops source tab，可先由 Ops 层处理显示名，不进入 foundation source registry。
   - 如果现有 API 强依赖 `get_source_display_name()`，再最小补充 `biz_tableset`，但必须说明这是 Ops 展示来源，不是外部源站。
2. `DatasetCardQueryService.list_cards()` 在 `source_key == "biz_tableset"` 时委托 `BizTableCardQueryService`。
3. 非 `biz_tableset` 分支保持现有 DatasetDefinition 逻辑不变。
4. 测试必须证明 `source_key=biz_tableset` 不影响 `tushare/biying` 返回。

### 8.2 前端

已落地文件：

```text
frontend/src/pages/ops-v21-biz-table-page.tsx
frontend/src/pages/ops-v21-source-page.tsx
frontend/src/app/router.tsx
frontend/src/app/shell.tsx
frontend/src/shared/api/types.ts
frontend/src/pages/ops-v21-source-page.test.tsx
```

改造说明：

1. `SourceKey` 增加 `biz_tableset`。
2. 数据源左侧菜单增加 `Biz数据集`。
3. `OpsV21SourcePage` 支持自定义描述和 Biz 表文案。
4. 测试覆盖 Biz 表卡片无操作按钮、显示表名、显示状态。

## 9. 分阶段实施状态

### M1 后端只读卡片

状态：已实现。

目标：

1. 新增 Biz 表目录配置。
2. 新增 Biz 表只读查询服务。
3. `GET /api/v1/ops/dataset-cards?source_key=biz_tableset` 返回 `wealth_market_turnover_snapshot` 卡片。

验收：

1. API 返回 1 张卡片。
2. 不生成任何 TaskRun。
3. 不返回 `primary_action_key`。
4. 不影响 `source_key=tushare/biying`。

### M2 前端入口与卡片展示

状态：已实现。

目标：

1. 左侧数据源增加 `Biz数据集`。
2. 新增 Biz 表页面。
3. 卡片复用现有样式，但文案适配业务派生表。

验收：

1. 可以打开 Biz 表页面。
2. 能看到 `成交额分钟快照` 卡片。
3. 不出现“去操作”按钮。
4. 不出现误导性 raw-only 文案。

### M3 文档与门禁

状态：已实现。

目标：

1. 更新 Ops API 文档。
2. 更新数据源卡片接口说明。
3. 补充测试清单。

验收：

1. `docs/ops/ops-api-reference-v1.md` 描述 `source_key=biz_tableset`。
2. 新测试覆盖后端和前端入口。

## 10. 风险与约束

| 风险 | 影响 | 缓解 |
|---|---|---|
| 把 Biz 表误注册成 DatasetDefinition | 误导同步、调度、手动任务链路 | Biz 表目录放 Ops catalog，不进 foundation datasets |
| 复用 DatasetCardItem 造成字段命名不完全贴切 | 字段如 `dataset_key/raw_table` 语义偏旧 | 一期固定映射并在文档说明，后续可升级 DataAssetCard |
| 前端 raw-only 文案误导 | Biz 表不是 raw 源 | SourcePage 支持按来源传描述，Biz 表使用只读派生表文案 |
| 状态口径与市场页不一致 | 用户看到的延迟状态冲突 | `wealth_market_turnover_snapshot` 状态口径沿用市场页盘后静态数据口径 |
| 后续 Biz 表增多后配置分散 | 维护困难 | 所有 Biz 表先集中在 `biz_table_catalog.py` |

## 11. 已确认决策

1. `source_key` 使用 `biz_tableset`，页面展示名为 `Biz数据集`。
2. 一期只纳入 `core_serving.wealth_market_turnover_snapshot`。
3. `Biz数据集` 入口放在左侧“数据源”分组下，与 `Tushare`、`Biying` 同级。
4. `wealth_market_turnover_snapshot` 的期望日期沿用市场页 `20:00` 盘后可用口径。

## 12. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-10 | 首版：定义 Biz 表作为 Ops 数据源平级展示的一期读展示方案 | Codex |
| v1.1 | 2026-05-10 | 回填评审结论：确认 `source_key=biz_tableset`、展示名 `Biz数据集`、一期对象和状态日期口径 | Codex |
| v1.2 | 2026-06-24 | 按当前实现纠偏：补充多频率构建、页面默认消费 30 分钟快照、日度指标来源、`core_serving.trade_calendar` 与实施状态 | Codex |
| v1.3 | 2026-09-05 | 标记为一期历史基线；二期自动投影与 14 表扩展转入独立现行方案 | Codex |
