# Ops 审查中心使用与查询说明

- 状态：现行代码说明；不代表生产验收。
- 核对日期：2026-09-09。保留原文路径，合并旧只读 V1 与激活池升级章节；整理去向见[治理记录](/Users/congming/github/goldenshare/docs/governance/docs-information-architecture-v1.md#ops-review-reconcile-consolidation-20260909)。
- 范围：指数激活池、板块与成分审查及数据集审计导航；不是融合策略中心、发布中心或多源对账平台。

## 1. 页面入口与权限

页面面向运营；接口要求管理员权限。浏览器路径含 Router 的 `/app` 基路径，前端内部导航省略该前缀。

| 浏览器路径 | 现行能力 | 写入边界 |
|---|---|---|
| `/app/ops/v21/review/index` | 指数激活池查询、概览、候选搜索、加入与移出 | 只修改激活池配置，不同时同步或删除行情 |
| `/app/ops/v21/review/board` | THS 板块、DC 板块、股票所属板块三个 Tab | 只读 |
| `/app/ops/v21/review/dataset-audit` | 日期桶／日期对象矩阵审计 | 有独立审计运行和结果，不能称整座审查中心只读 |

数据集审计规则及其后处理边界归[日期完整性审计说明](/Users/congming/github/goldenshare/docs/ops/dataset-date-completeness-audit-design-v2.md)。本页文档不授权实际改池、发起审计或写数据。

## 2. 指数激活池

当前页面固定操作 `resource=index_daily`；主对象为 `ops.index_series_active`，键为 `resource/ts_code`。它是服务层放行池，不是 Raw 请求池、TaskRun 状态表或 freshness 结果。完整准入、供数状态、补漏和时间规则统一归[指数日线说明 §5](/Users/congming/github/goldenshare/docs/ops/ops-index-daily-completeness-reconciliation-plan-v2.md#5-审查中心与人工改池)，不在本文复制第二套规则。

页面展示：

- “激活池管理”卡片提供加入入口和问号说明；列表展示代码、名称、市场、发布方、行情状态、最近日／周／月日期、源站供数状态及移出操作。
- 搜索、行情状态、供数状态和分页通过 URL 参数传递；技术原因不在主列表展开。
- 概览统计指定资源池总体，不跟随列表关键词和状态筛选。日／周／月可用分别读取对应的 `core_serving.index_daily_serving/index_weekly_serving/index_monthly_serving`。
- `complete` 只表示上述三层各有记录；`pending_count` 是至少一层没有记录的指数数。它们不检查中间缺日、不证明已更新到应到日期，也不是源站供数状态。日期缺口应查看独立审计结果。

操作边界：

1. 候选来自 `core_serving.index_basic`，排除已在指定池的代码；加入时除检查代码存在、未重复，还需通过指数专题规定的 Raw 连续供数资格，不能仅凭基础信息存在就放行。
2. 加入只写池记录，不自动补历史行情；需要补数时走标准维护流程。移出只删对应池行，不删除 Raw 或 Serving 历史；不存在记录返回明确错误。
3. 页面加入／移出有确认步骤，需说明影响；不提供任意字段编辑、批量导入、批量移出或用户自定义多套池。API 支持资源参数不等于页面开放资源选择器。
4. 主列表不展示 `resource`、首次观测／检查时间或 TaskRun 技术状态；这些后端字段存在不等于应铺满页面。没有独立单指数详情抽屉。
5. 池配置写入不能影响业务数据事务。本文描述的是现行服务的单独池操作，不据此承诺所有并发维护均与池变更原子协调。

API 的分页、候选、写入响应及错误见 [API 参考 §8](/Users/congming/github/goldenshare/docs/ops/ops-api-reference-v1.md#8-review-center-接口)。

## 3. 板块事实与统计

实现入口为 [ReviewCenterQueryService](/Users/congming/github/goldenshare/src/ops/queries/review_center_query_service.py)，不另建 review_list/review_entry 写表。

| 查询 | 事实来源 | 日期与计数口径 |
|---|---|---|
| THS 板块／成分 | `core_serving.ths_index/ths_member` | 成分按 `out_date IS NULL` 取当前有效记录；按板块统计不同 `con_code` |
| DC 板块／成分 | `core_serving.dc_index/dc_member` | 不传日期时取 dc_index 的最大 trade_date；两表使用同一日期，成分计数为不同 con_code |
| 股票所属板块 | 上述 THS 当前成分＋DC 指定日成分 | 按股票分页，板块数按不同 `provider:board_code` 统计；不是把两源同名板块融合成一个 |

需保留的限制：

- THS 没有在此查询中重建历史成分；股票所属板块选择历史日期只影响 DC，不能把混合结果称为“两源同日历史快照”。
- DC 默认日期来自板块信息表，不证明成分表该日完整。指定日期没有数据可返回空结果，不自动回退其他日期。
- 股票名称优先证券基础表 `core_serving.security_serving.name`，缺失时回退成分名称。输入可按代码／名称搜索，当前还支持证券 symbol／拼音匹配及候选联想。
- 成分数量在 SQL 子查询聚合后过滤，不要求固定使用 HAVING；股票所属板块聚合使用 HAVING。板块列表默认按成分数降序，股票列表按板块数降序，再按代码排序。
- 板块计数是 distinct 数，成员数组按当前查询返回，不应把数组行数当作独立的去重计数来源。

板块 API 参数及响应归 [API 参考板块小节](/Users/congming/github/goldenshare/docs/ops/ops-api-reference-v1.md#review-board-apis)。返回的成员统一使用 `ts_code/name/in_date/out_date`，不是原数据库列名 `con_code/con_name`；DC 不提供的进出日期为空。

## 4. 板块页面交互

[页面实现](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-review-board-page.tsx)将已应用的筛选项存入 URL；Tab 切换保留各 Tab 筛选，重置页码。输入框尚未提交的文字不等于已保存的筛选。

- THS：类型、关键词和最小成分数；DC：日期、类型、关键词和最小成分数；股票：关键词／候选、来源、DC 日期和最小板块数。
- 成分列表先展示最多 5 个预览，更多内容打开抽屉，每页展示 20 个；股票所属板块先展示最多 8 个标签，更多内容打开详情。
- 当前成员抽屉对已取回数组做前端分页，不是按抽屉页码再次请求服务端；主列表分页也不等于成员数据总量有独立上限。
- 保留加载、空态和错误态；不把旧“展开行”草图当作现行交互，不因本文整理新增控件或改分页机制。

## 5. 验证入口与未实施设想

代码：[API](/Users/congming/github/goldenshare/src/ops/api/review_center.py)、[响应模型](/Users/congming/github/goldenshare/src/ops/schemas/review_center.py)、[池写入服务](/Users/congming/github/goldenshare/src/ops/services/review_center_service.py)、[指数页面](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-review-index-page.tsx)。

回归入口：[后端测试](/Users/congming/github/goldenshare/tests/web/test_ops_review_center_api.py)、[指数页面测试](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-review-index-page.test.tsx)、[板块页面测试](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-review-board-page.test.tsx)。重点为管理员权限、分页／筛选、池操作不改行情、候选资格、THS 有效成分、DC 默认日期、跨来源计数、URL 状态和抽屉。存在测试文件不等于本轮已完成运行或生产验收。

旧设计中的池备注／加入原因／操作人字段、单指数详情、可选 `ops_review` 查询视图仍只是备选，不能直接作为新增表或字段的依据。需实际需求和独立评审后才能实施。

本轮仅整理文档，保留有效操作边界与查询规则，删除重复分期施工单及过时状态；未修改代码、数据库、数据同步或部署。旧方案全文可从提交 `39d957f4` 追溯。
