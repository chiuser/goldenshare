# Ops 审查中心设计方案 v1（只读展示版）

## 1. 一期边界（按产品目标收敛）

V1 只做读取展示，不做任何写操作。

必须覆盖的页面与能力：

1. 审查中心-指数-激活指数  
2. 审查中心-板块-同花顺板块与成分股  
3. 审查中心-板块-东方财富板块与成分股  
4. 审查中心-板块-股票所属板块（聚合 THS + DC）

明确不做：

1. 不新增“维护/启停/导入/导出”操作。  
2. 不新增审查写表（如 `review_list/review_entry`）。  
3. 不改动现有同步执行逻辑（仅展示当前真实状态）。  
4. 不做融合策略中心、发布中心能力扩展。

---

## 2. 信息架构与路由

## 2.1 菜单结构

一级菜单：`审查中心`  
二级领域：`指数`、`板块`

## 2.2 页面路由建议

1. `/app/ops/v21/review/index`  
   - Tab：`激活指数`

2. `/app/ops/v21/review/board`  
   - Tab：`同花顺板块与成分股`  
   - Tab：`东方财富板块与成分股`  
   - Tab：`股票所属板块`

交互要求：

1. 先选领域，再在领域内切 Tab。  
2. Tab 切换不丢筛选条件（前端 URL query 持久化）。

---

## 3. 数据来源设计（V1 不新增业务写表）

V1 直接读取现有表，不新增写入链路。

## 3.1 指数领域

主表：

1. `ops.index_series_active`（激活指数池）  

关键字段：

1. `resource`
2. `ts_code`
3. `first_seen_date`
4. `last_seen_date`
5. `last_checked_at`

用途：

1. 展示“当前已纳入同步池的指数代码列表”。

## 3.2 板块领域（同花顺）

主表：

1. `core_serving.ths_index`（板块基本信息）  
2. `core_serving.ths_member`（板块成分）

关键字段：

1. `ths_index.ts_code`, `name`, `exchange`, `type`, `list_date`
2. `ths_member.ts_code`, `con_code`, `con_name`, `in_date`, `out_date`

V1 默认统计口径（用于“成分个数”）：

1. 仅统计当前有效成分：`out_date is null`。  
2. 成分个数：`count(distinct con_code)`。

## 3.3 板块领域（东方财富）

主表：

1. `core_serving.dc_index`（板块信息，按交易日快照）  
2. `core_serving.dc_member`（成分信息，按交易日快照）

关键字段：

1. `dc_index.trade_date`, `ts_code`, `name`, `idx_type`
2. `dc_member.trade_date`, `ts_code`, `con_code`, `name`

V1 默认统计口径：

1. 默认使用 `dc_index` 最新交易日（`max(trade_date)`）的快照。  
2. 支持运营手动切换 `trade_date` 查看历史快照。  
3. 成分个数：在同一 `trade_date` 下 `count(distinct con_code)`。

## 3.4 股票所属板块聚合

来源：

1. THS 当前有效成分（`ths_member.out_date is null`）  
2. DC 指定交易日成分（默认最新交易日）  
3. 股票名称优先取 `core_serving.security_serving.name`，缺失时回退成分表名称

输出维度：

1. 股票代码
2. 股票名称
3. 所属板块列表（THS + DC，去重后聚合）
4. 所属板块数量

---

## 4. API 设计（只读）

前缀统一：`/api/v1/ops/review`

## 4.1 指数-激活指数

`GET /api/v1/ops/review/index/active`

查询参数：

1. `resource`（默认 `index_daily`）
2. `keyword`（匹配 `ts_code`）
3. `page` / `page_size`

返回字段（建议）：

1. `resource`
2. `ts_code`
3. `first_seen_date`
4. `last_seen_date`
5. `last_checked_at`

## 4.2 同花顺板块与成分股

`GET /api/v1/ops/review/board/ths`

查询参数：

1. `keyword`（匹配板块代码/板块名称）
2. `min_constituent_count`（筛选成分个数大于等于 N）
3. `page` / `page_size`
4. `include_members`（默认 `true`）

返回字段（建议）：

1. `board_code`
2. `board_name`
3. `exchange`
4. `board_type`
5. `constituent_count`
6. `members[]`（`con_code`, `con_name`, `in_date`, `out_date`）

## 4.3 东方财富板块与成分股

`GET /api/v1/ops/review/board/dc`

查询参数：

1. `trade_date`（可空，默认最新交易日）
2. `idx_type`（可空）
3. `keyword`（匹配板块代码/板块名称）
4. `min_constituent_count`
5. `page` / `page_size`
6. `include_members`（默认 `true`）

返回字段（建议）：

1. `trade_date`
2. `board_code`
3. `board_name`
4. `idx_type`
5. `constituent_count`
6. `members[]`（`con_code`, `name`）

## 4.4 股票所属板块（聚合）

`GET /api/v1/ops/review/board/equity-membership`

查询参数：

1. `trade_date`（DC 快照日期，可空，默认最新）
2. `keyword`（匹配股票代码/股票名称）
3. `min_board_count`（所属板块数量下限）
4. `provider`（`all`/`ths`/`dc`，默认 `all`）
5. `page` / `page_size`

返回字段（建议）：

1. `ts_code`
2. `equity_name`
3. `board_count`
4. `boards[]`（`provider`, `board_code`, `board_name`）

---

## 5. 查询实现建议（后端）

## 5.1 查询服务组织

新增查询服务：

1. `src/ops/queries/review_center_query_service.py`

按领域拆函数：

1. `list_active_indexes(...)`
2. `list_ths_boards_with_members(...)`
3. `list_dc_boards_with_members(...)`
4. `list_equity_board_membership(...)`

## 5.2 SQL 口径要点

1. 所有“成分个数”都在 SQL 层聚合，避免前端二次计算。  
2. `min_constituent_count` 在 SQL `HAVING` 阶段处理。  
3. 股票所属板块聚合先做统一明细流（THS UNION DC），再按 `ts_code` 聚合。  
4. 分页在股票级别做，不在 `boards[]` 明细级别分页。

## 5.3 可选只读视图（非必需）

如果查询复杂度偏高，可加只读 SQL View（不落业务写数据）：

1. `ops_review.v_ths_board_member_current`
2. `ops_review.v_dc_board_member_latest`
3. `ops_review.v_equity_board_membership`

说明：V1 可以先不用视图，直接 Query Service 里写 SQL；性能不足再补视图。

---

## 6. 前端交互设计（V1）

## 6.1 审查中心-指数-激活指数

列表字段：

1. 指数代码
2. 首次观测日期
3. 最近观测日期
4. 最近检查时间

筛选区：

1. 资源（默认 `index_daily`）
2. 关键词（代码）

## 6.2 审查中心-板块-同花顺板块与成分股

筛选区：

1. 板块关键词
2. 成分个数 >= N

列表区：

1. 板块代码、板块名称、成分个数
2. 展开行查看成分股

## 6.3 审查中心-板块-东方财富板块与成分股

筛选区：

1. 交易日期（默认最新）
2. 板块类型（可选）
3. 板块关键词
4. 成分个数 >= N

列表区：

1. 板块代码、板块名称、成分个数
2. 展开行查看成分股

## 6.4 审查中心-板块-股票所属板块

筛选区：

1. 股票关键词（代码/名称）
2. 所属板块数 >= N
3. 来源（全部/THS/DC）
4. DC 快照交易日（默认最新）

列表区：

1. 股票代码、股票名称、所属板块数
2. 所属板块标签列表（展示来源标记 THS/DC）

---

## 7. 测试范围（V1）

后端：

1. 指数列表接口分页/筛选。  
2. 板块接口 `min_constituent_count` 筛选正确性。  
3. 东方财富 `trade_date` 默认最新逻辑。  
4. 股票所属板块聚合去重正确性。

前端：

1. 菜单与二级路由结构正确。  
2. 板块页面筛选联动正确。  
3. 三个 Tab 切换不丢筛选条件。  
4. 空态、错误态展示正确。

---

## 8. 交付清单（V1）

1. 文档：本设计文档。  
2. 后端：只读 API 4 组。  
3. 前端：审查中心 2 个领域 + 4 个页面能力。  
4. 测试：接口与页面基础回归用例。  

---

## 9. 结论

V1 以“领域化只读审查”为目标，不引入维护写操作，不改动同步链路。  

先让运营人员能稳定回答三件事：

1. 当前激活指数到底有哪些。  
2. 同花顺/东财板块及其成分当前是什么。  
3. 某只股票到底出现在哪些板块里。  

在这套只读能力稳定后，再进入 V2 的可维护改造。

