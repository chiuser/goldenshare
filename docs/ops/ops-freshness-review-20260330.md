# 运维系统新鲜度页检查记录（2026-03-30）

> 历史检查记录（归档）：本文为问题排查纪要，路径示例可能已过时。当前目录结构以 [current-architecture-baseline.md](/Users/congming/github/goldenshare/docs/architecture/current-architecture-baseline.md) 为准。

## 背景

本次检查聚焦运维系统前端中的“数据新鲜度”页面，重点验证以下问题：

- 页面是否会把已经恢复的问题继续显示为当前异常
- 异常信息是否可读，是否存在原始 SQL/堆栈直接暴露的问题
- 新鲜度判断是否过度依赖 `ops.sync_job_state`，从而和真实目标表状态产生偏差
- 前后端改动后，测试与构建是否仍然稳定

## 发现的问题

### 1. 历史失败会长期显示为当前异常

原实现直接读取某个 job 最近一次失败日志，并展示到新鲜度页。  
这会导致如下问题：

- 某个资源曾经失败过
- 但之后已经成功恢复
- 页面仍然持续显示红色失败信息

典型例子：

- `sync_dividend`
- 历史报错：`raw.dividend` 缺少 `row_key_hash`
- 当前实际状态：后续已经成功，同步已恢复

也就是说，页面展示的是“最近失败过”，而不是“当前仍失败”。

### 2. 异常信息直接显示原始 SQL 错误，过长且难以理解

原实现把 `ops.sync_run_log.message` 原样显示到页面。  
这会导致页面中出现超长 SQL 异常文本，例如：

- `column "row_key_hash" of relation "dividend" does not exist`
- 大段 `INSERT INTO ...` SQL

这类文本有两个问题：

- 信息噪声过高，影响页面可读性
- 用户很难快速判断问题本质

### 3. 某些数据集的新鲜度和真实表状态不一致

原实现主要依赖 `ops.sync_job_state.last_success_date` 作为最新业务日期。  
这在大部分资源上是够用的，但在部分资源上会出现偏差：

- 目标表实际已经更新到更近日期
- 但 `sync_job_state` 记录仍然偏旧
- 页面因此误判为更陈旧的状态

典型例子：

- `sync_block_trade`
- `core.equity_block_trade` 的真实最新 `trade_date` 更新得更近
- 但 `ops.sync_job_state.last_success_date` 仍是较旧日期

## 本次修复

### 1. 新鲜度页只展示“当前仍然有效”的失败

修复位置：

- [/Users/congming/github/goldenshare/src/ops/queries/freshness_query_service.py](/Users/congming/github/goldenshare/src/ops/queries/freshness_query_service.py)

修复方式：

- 引入 `FailureSnapshot`
- 增加失败可见性判断
- 仅当“最近失败时间晚于最近成功时间”时，才显示失败信息

修复后效果：

- 已恢复的历史错误不会继续占据页面
- 页面更接近“当前状态”而不是“历史事件”

### 2. 对异常信息做摘要化处理

修复位置：

- [/Users/congming/github/goldenshare/src/ops/queries/freshness_query_service.py](/Users/congming/github/goldenshare/src/ops/queries/freshness_query_service.py)
- [/Users/congming/github/goldenshare/src/ops/schemas/freshness.py](/Users/congming/github/goldenshare/src/ops/schemas/freshness.py)
- [/Users/congming/github/goldenshare/frontend/src/shared/api/types.ts](/Users/congming/github/goldenshare/frontend/src/shared/api/types.ts)
- [/Users/congming/github/goldenshare/frontend/src/pages/ops-freshness-page.tsx](/Users/congming/github/goldenshare/frontend/src/pages/ops-freshness-page.tsx)

修复方式：

- 后端新增 `recent_failure_summary`
- 对常见错误做摘要化归类，例如：
  - 数据库字段缺失
  - 非空约束错误
  - ON CONFLICT 约束缺失
  - Tushare 接口错误
- 前端默认显示摘要
- 原始错误保留在 tooltip 中，必要时可查看全文

修复后效果：

- 页面更易读
- 重要问题能快速判断
- 详细排障信息仍然保留

### 3. 新鲜度判断加入“真实目标表观察日期”

修复位置：

- [/Users/congming/github/goldenshare/src/operations/specs/dataset_freshness_spec.py](/Users/congming/github/goldenshare/src/operations/specs/dataset_freshness_spec.py)
- [/Users/congming/github/goldenshare/src/operations/specs/registry.py](/Users/congming/github/goldenshare/src/operations/specs/registry.py)
- [/Users/congming/github/goldenshare/src/ops/queries/freshness_query_service.py](/Users/congming/github/goldenshare/src/ops/queries/freshness_query_service.py)

修复方式：

- 为新鲜度 spec 增加 `observed_date_column`
- 对具备明确业务日期字段的目标表，读取真实表中的最大业务日期
- 新鲜度计算时，使用：
  - `max(sync_job_state.last_success_date, observed_table_max_date)`

修复后效果：

- 避免仅依赖状态表导致的保守误判
- 页面更贴近真实数据落库结果

### 4. 修复 SQLite 测试库下的日期类型兼容问题

修复位置：

- [/Users/congming/github/goldenshare/src/ops/queries/freshness_query_service.py](/Users/congming/github/goldenshare/src/ops/queries/freshness_query_service.py)

问题原因：

- 读取真实目标表最大日期时，SQLite 测试环境和 PostgreSQL 的类型行为不同
- 直接对 `func.max(...).cast(Date())` 做处理，会触发 `fromisoformat` 类型错误

修复方式：

- 去掉数据库侧强制 `cast(Date())`
- 改为在 Python 层统一规范化：
  - `datetime -> date`
  - `date -> date`
  - `str -> date.fromisoformat(...)`

修复后效果：

- 测试环境与正式环境都能稳定工作
- 新鲜度页后端逻辑不再被 SQLite 兼容性卡住

## 验证结果

### 后端定向回归

执行：

```bash
pytest tests/web/test_ops_freshness_api.py
```

结果：

- `5 passed`

### 前端类型与构建验证

执行：

```bash
cd frontend && npm run typecheck
cd frontend && npm run test
cd frontend && npm run build
```

结果：

- `typecheck` 通过
- `vitest` 通过
- `vite build` 通过

### 全量回归

执行：

```bash
pytest
```

结果：

- `137 passed`

## 当前效果

修复后，新鲜度页的异常展示口径变成：

- 优先表达当前状态
- 已恢复的历史错误不再继续红色展示
- 当前异常默认显示摘要
- 需要排障时仍可查看原始错误全文
- 某些数据集会参考真实目标表的最新业务日期，而不是只看 `sync_job_state`

## 本轮补充增强

在完成基础修复后，又补了一轮“可解释性”和“排障入口”增强。

### 1. 新增状态来源解释

页面现在会明确展示最新业务日的来源：

- `状态表`
- `真实表`
- `状态表 + 真实表`

同时会展示：

- `sync_job_state` 里的业务日期
- 真实目标表观测到的业务日期

并在必要时给出提示，例如：

- `已按真实目标表的业务日期修正，状态表记录偏旧。`

这样在看到某条数据“为什么是这个状态”时，不需要再靠猜。

### 2. 增加排障入口

每条数据集现在都增加了直接跳转：

- 去执行中心
- 看总览
- 看资源目录

其中“去执行中心”会尽量带上对应的主执行 spec 作为筛选条件，减少来回查找的成本。

### 3. 执行中心支持通过 URL 接收筛选条件

为了配合新鲜度页跳转，执行中心现在支持从 URL 中读取初始筛选条件，例如：

- `spec_key`
- `status`
- `trigger_source`

这样从新鲜度页跳过去时，可以更快落到相关 execution 上。

## 仍需后续关注的点

### 1. 并非所有数据集都已接入真实目标表观察字段

当前只给部分适合直接观察业务日期的资源补了 `observed_date_column`。  
后续可以继续扩展，让更多数据集的新鲜度判断更贴近真实目标表。

### 2. 页面仍是“运维摘要视图”，不是完整诊断台

当前新鲜度页已经更可信、更易读，但它仍然不是完整的诊断页。  
如果后面继续增强，可以考虑增加：

- “状态来源”说明
- “状态表日期 vs 真实表日期”对比
- 一键跳转到相关 execution / log

### 3. 错误摘要规则后续可继续完善

现在已经覆盖了常见的数据库结构错误和 Tushare 接口错误。  
后面随着运行样本变多，可以继续扩充摘要规则。

## 结论

本次检查的核心结论是：

- 新鲜度页原先存在“旧错误压过新状态”的问题
- 也存在“原始错误过长、页面难读”的问题
- 还存在“仅靠状态表判断，和真实表状态不完全一致”的问题

这些问题本次都已经完成修复，并通过了定向回归、前端构建回归和全量测试回归。
