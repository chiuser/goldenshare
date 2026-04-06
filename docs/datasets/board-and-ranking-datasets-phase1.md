# 板块与榜单数据集一期设计

## 1. 背景

本期目标是在现有数据基座和运维系统之上，补齐板块相关与榜单相关数据集的统一接入模式。

设计遵循以下既定准则：

1. 数据相关能力归数据基座实现，Web 仅做交互、监控和控制。
2. 只要接口具备起止日期语义，就必须同时提供单日同步与历史回补能力。
3. 新增数据集时，必须同步接入运维系统，具备可监控、可同步、可查看健康度的能力。
4. 所有输出字段必须落库，`raw` 层保留来源字段原貌，`core` 层做最小规范化。

## 2. 用户本轮确认的修订

### 2.1 开盘啦榜单

- `kpl_list` 具备 `trade_date / start_date / end_date` 参数。
- 设计上必须明确支持按起止日期回补，不能只把它当成单日快照接口。
- 已按“单日 + 区间回补”完整模式接入。

### 2.2 同花顺热榜

- `market` 作为同步筛选项保留。
- `is_new` 不视为普通业务筛选项，而视为同步场景标签。
- 运维手动执行中仍保留 `is_new` 手动选择能力。
- 已按榜单快照类模式接入。

### 2.3 东方财富概念板块

- `dc_index` 接口中的 `name` 不作为同步筛选项。
- 同步与回补只暴露稳定筛选项：
  - `trade_date`
  - `start_date`
  - `end_date`
  - `ts_code`
  - `idx_type`

### 2.4 开盘啦题材成分

- `kpl_concept_cons` 已按标准模式接入（模型、同步、运维、数据状态）。
- 由于源站更新频率可能较低，健康度判断以最近业务日与最近同步时间共同展示。

## 3. 分批实施范围

### 3.1 第 1 批：板块主数据与板块行情

本批直接开发并打通运维系统：

1. `ths_index` 同花顺概念和行业指数
2. `ths_member` 同花顺概念板块成分
3. `ths_daily` 同花顺板块指数行情
4. `dc_index` 东方财富概念板块
5. `dc_member` 东方财富板块成分
6. `dc_daily` 东方财富板块行情

### 3.2 第 2 批：榜单快照类

本批已落地：

1. `kpl_list` 开盘啦榜单
2. `ths_hot` 同花顺热榜
3. `dc_hot` 东方财富热榜
4. `kpl_concept_cons` 开盘啦题材成分

## 4. 数据分类与同步策略

### 4.1 板块主数据类

资源：

- `ths_index`

策略：

- 以 `sync_history` 为主。
- 允许按代码/分类精确同步。
- 不暴露内部批处理参数。

### 4.2 板块成分类

资源：

- `ths_member`
- `dc_member`

策略：

- 成分同步不把源接口当作“可直接空参全量返回”的主入口。
- 必须先同步对应板块主数据，再使用板块代码逐个抓取成分。
- 关系如下：
  - `ths_index -> ths_member`
  - `dc_index -> dc_member`
- 当用户明确指定板块代码时，允许做定向同步。
- 当用户未指定板块代码时：
  - `ths_member` 先刷新 `ths_index`，再按全部板块 `ts_code` 逐个同步。
  - `dc_member` 先刷新指定交易日的 `dc_index`，再按该交易日全部板块 `ts_code` 逐个同步。
- 这条规则属于领域规则，后续新增“板块主数据 -> 板块成分”类数据时统一遵守。

### 4.3 板块日更快照类

资源：

- `ths_daily`
- `dc_index`
- `dc_member`
- `dc_daily`

策略：

- 必须提供单日同步能力。
- 对具备 `start_date / end_date` 的接口，额外提供直接区间回补能力。
- 对仅具备 `trade_date` 的接口，提供按交易日区间回补能力。

## 5. 数据集与筛选项

### 5.1 `ths_index`

输入参数：

- `ts_code`
- `exchange`
- `type`

保留筛选项：

- `ts_code`
- `exchange`
- `type`

### 5.2 `ths_member`

输入参数：

- `ts_code`
- `con_code`

保留筛选项：

- `ts_code`
- `con_code`

同步说明：

- 全量/历史同步时，先同步 `ths_index`，再按板块 `ts_code` 逐个同步成分。
- 定向同步时，允许直接传 `ts_code` 或 `con_code`。

### 5.3 `ths_daily`

输入参数：

- `ts_code`
- `trade_date`
- `start_date`
- `end_date`

保留筛选项：

- `trade_date`
- `start_date`
- `end_date`
- `ts_code`

### 5.4 `dc_index`

输入参数：

- `ts_code`
- `trade_date`
- `start_date`
- `end_date`
- `idx_type`

保留筛选项：

- `trade_date`
- `start_date`
- `end_date`
- `ts_code`
- `idx_type`

明确不保留：

- `name`

### 5.5 `dc_member`

输入参数：

- `trade_date`
- `ts_code`
- `con_code`

保留筛选项：

- `trade_date`
- `ts_code`
- `con_code`

同步说明：

- 单日与按交易日回补时，先同步同日 `dc_index`，再按板块 `ts_code` 逐个同步成分。
- 定向同步时，允许直接传 `ts_code` 或 `con_code`。

### 5.6 `dc_daily`

输入参数：

- `ts_code`
- `trade_date`
- `start_date`
- `end_date`
- `idx_type`

保留筛选项：

- `trade_date`
- `start_date`
- `end_date`
- `ts_code`
- `idx_type`

## 6. 落库原则

### 6.1 raw 层

每个接口单独建表，完整保留输出字段：

- `raw.ths_index`
- `raw.ths_member`
- `raw.ths_daily`
- `raw.dc_index`
- `raw.dc_member`
- `raw.dc_daily`

### 6.2 core 层

按来源和语义单独建表，不合并不同来源：

- `core.ths_index`
- `core.ths_member`
- `core.ths_daily`
- `core.dc_index`
- `core.dc_member`
- `core.dc_daily`

## 7. 运维系统接入要求

第 1 批数据集上线时必须同步具备：

1. `sync_history` / `sync_daily` / `backfill_*` 对应执行能力
2. 运维 catalog 可见
3. 手动同步页可选
4. 任务记录页可追踪
5. 数据状态页可查看健康度

## 8. 本期实施顺序

1. 先建 `raw/core` 模型与 migration
2. 再补同步服务和资源注册
3. 再补回补策略与 CLI 入口
4. 再补运维 registry、健康度和前端显示标签
5. 最后补测试并回归
