# 市场总览｜主要指数技术实施方案 v1（implementation-design）

> 用途：把“主要指数”需求文档转成可实施技术方案。  
> 阶段：编码前。  
> 产物性质：实现设计基线（不写业务代码）。

---

## 1. 文档目的

1. 对应需求文档：  
   [major-indices-benchmark-requirement-v1.md](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/major-indices-benchmark-requirement-v1.md)
2. 本文目标：冻结主要指数模块的配置、查询、状态、异常与返回契约。
3. 本文不做：不落业务代码，不修改前端视觉，不改其他模块语义。

关联门禁：  
[major-indices-m2-coding-gate-v1.md](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/major-indices-m2-coding-gate-v1.md)

---

## 2. 代码现状审计（必须基于真实代码）

1. 现有数据模型已固定指数行情口径为 `index_daily_serving`：  
   [market-overview-api-model-design-v1.md](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/market-overview-api-model-design-v1.md)
2. 市场总览布局已固定主要指数区为 `2x5`：  
   [market-overview-baseline.md](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/market-overview-baseline.md)
3. 当前冲突与风险：
   - 指数名单若硬编码在前端，后续替换成本高且易漂移。
   - 若只验最终渲染，不验真实源加载过程，容易遗漏 `loading/error` 语义缺失。
4. 结论：
   - 名单定义收敛到后端配置；
   - 接口层仅返回已排序 10 行数据；
   - 前端继续纯渲染，并明确 `loading/ready/error` 三态。

---

## 3. 分层架构与目录落点

### 3.1 接口范围

1. 模块接口路径：`GET /api/v1/wealth/market/major-indices`
2. 是否整页聚合接口：否（模块接口）
3. 模块返回范围：仅 `majorIndices` 模块对象与必要状态字段

### 3.2 代码目录模板（按模块拆分）

```text
src/biz/
  api/
    wealth/
      market/
        major_indices.py
  queries/
    wealth/
      market/
        major_indices/
          major_indices_query.py
          major_indices_query_service.py
  schemas/
    wealth/
      market/
        major_indices.py
  services/
    wealth/
      config/
        strategy_config_service.py
        strategy_config_registry.py
        strategy_config_models.py
        definitions/
          major_indices.cn_a.v1.json
      market/
        major_indices/
          major_indices_status_resolver.py
          major_indices_exception_builder.py
```

---

## 4. 数据流与执行链路

1. 请求入口：`api.wealth.market.major_indices`
2. 参数校验：`market/tradeDate/debug`
3. 配置装载：`strategy_config_service` 读取主要指数名单定义
4. 主查询：`major_indices_query_service` 在 `index_daily_serving` 查询 10 指数
5. 名称补齐：关联 `index_basic` 填充 `subjectName`
6. 状态归并：`major_indices_status_resolver` 产出模块状态
7. 异常组装：`major_indices_exception_builder` 仅使用注册表异常码
8. 响应输出：`schemas.wealth.market.major_indices` DTO
9. 前端渲染态（真实源）：
   - 返回前：`loading`
   - 返回成功：`ready`
   - 请求失败或超过 5 秒：`error`
   - 禁止 silent fallback 回填 mock。

### 4.1 指数名单配置（冻结）

1. 文件位置：  
   `src/biz/services/wealth/config/definitions/major_indices.cn_a.v1.json`
2. 配置职责：只定义“哪 10 个指数 + 顺序”，不定义 UI 样式
3. 配置约束：
   - `indexCodes` 长度必须是 `10`
   - `indexCodes` 不允许重复
   - `market` 固定 `CN_A`
4. 读取入口：
   - `strategy_config_service.get_payload(module_key="majorIndices", market="CN_A")`

示例：

```json
{
  "definitionKey": "CN_A_MAJOR_INDICES_V1",
  "version": "1.0.0",
  "market": "CN_A",
  "indexCodes": [
    "000001.SH",
    "399001.SZ",
    "399006.SZ",
    "000688.SH",
    "000300.SH",
    "000905.SH",
    "000852.SH",
    "899050.BJ",
    "000510.SH",
    "000016.SH"
  ]
}
```

---

## 5. 查询编排策略

1. 主查询：
   - 从 `index_daily_serving` 按 `trade_date` + `indexCodes[10]` 查询。
2. 补列查询：
   - `index_basic` 按 `ts_code` 左连接补名称。
3. 顺序策略：
   - 结果按配置名单顺序重排，不按涨跌幅排序。
4. 缺失处理：
   - 某 code 当日无行情：保留占位行（`subjectCode` 存在，值字段可空）。
5. 空数据处理：
   - 全部 10 code 无数据：模块 `EMPTY`，页面可 `PARTIAL/EMPTY`（按整页规则）。

---

## 6. 状态与异常落地

1. `pageStatus`：沿用整页状态聚合规则。
2. `moduleStatus`（debug）：
   - `moduleKey=majorIndices`
   - `expectedTradeDate/observedTradeDate/lagDays/status/note`
3. debug 输出：
   - 仅 `debug=1` 返回；
   - 生产环境禁用。
4. 异常码（拟定）：
   - `MI_CONFIG_MISSING`
   - `MI_CONFIG_INVALID`
   - `MI_SOURCE_DELAYED`
   - `MI_SOURCE_EMPTY`
   - `MI_QUERY_FAILED`

---

## 7. 性能与缓存策略

1. 性能预算：P95 < 150ms（10 指数、单日查询）。
2. 首版策略：无 Redis，依赖小结果集 + 索引查询。
3. 二期缓存（可选）：`wealth:major_indices:{market}:{tradeDate}:{definitionKey}`。
4. 一致性：按交易日与定义版本失效。

---

## 8. 安全与权限

1. 鉴权依赖：沿用 `quote.read`（本期固定）。
2. 权限点：已登录且具备行情读取权限可访问。
3. 防误用策略：
   - 禁止非法 market；
   - 禁止非法 date 格式；
   - debug 输出生产禁用。

---

## 9. 测试与验证计划

1. 单元测试：
   - 配置长度必须 10；
   - 配置 code 不重复；
   - 查询结果按配置顺序输出。
2. 集成测试：
   - 正常/延迟/空数据/异常场景。
3. 冒烟验证：
   - 返回结构稳定；
   - 10 卡固定；
   - 前端布局无变化；
   - 前端行为满足 `loading -> ready` 与 `timeout(5s) -> error`。
4. 失败回滚与观测：
   - 配置异常时模块降级并输出结构化异常；
   - 不影响其他模块响应。
5. 范围约束验证：
   - 本轮只允许 `majorIndices` 模块切到 `real`；
   - 其他模块 source 保持原值不变。

---

## 10. 分期里程碑

1. M1（方案冻结）：定义、查询、状态、异常冻结。
2. M2（后端实现）：接口 + 查询 + 配置驱动落地。
3. M3（前端接入）：按既有 UI 组件接入，不变更样式交互。
4. M4（回归发布）：联调、性能回归、灰度验收。

---

## 11. 风险与缓解

1. 风险：配置误改导致非 10 条或重复 code。  
   缓解：registry 强校验 + 启动失败告警。
2. 风险：单指数缺日数据导致卡片空洞。  
   缓解：保留占位 + 模块 delayed/partial 语义。
3. 风险：前端擅自重排指数。  
   缓解：后端返回顺序即展示顺序，前端不排序。
4. 风险：真实源失败后静默回填 mock，掩盖线上数据故障。  
   缓解：门禁中禁止 silent fallback，并补行为过程测试。

---

## 12. 已确认清零项

1. 指数数量固定 10，不做数量配置化。
2. 指数名单后端可配置，前端不持有名单逻辑。
3. UI 样式与交互保持现状，不做变更。
4. 本轮无未决拍板项。

---

## 13. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-08 | 首版：冻结主要指数模块配置与实现边界 | Codex |
