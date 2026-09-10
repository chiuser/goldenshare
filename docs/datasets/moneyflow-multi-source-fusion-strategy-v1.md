# 资金流多源融合与对账说明

更新时间：2026-09-10。状态：现行代码说明；原策略草案已校准，未来质量建议与已实现能力分列。本文不证明生产当前策略配置或源端覆盖范围已重新验收。

## 1. 当前链路与职责

Tushare `moneyflow` 和 BIYING `biying_moneyflow` 都已接入 Raw → Std → Serving，不是“BIYING 仅写 Raw、等待融合开发”。

```text
两源各自的 maintain 请求 → DatasetDefinition / DatasetExecutionPlan
  → 各自 Raw → NormalizeMoneyflowService → core_multi.moneyflow_std
  → 本次受影响的 (ts_code, trade_date)
  → ServingPublishService → core_serving.equity_moneyflow
```

- 来源事实分别保存于 `raw_tushare.moneyflow`、`raw_biying.moneyflow`。
- Std 是已存在的物理模型，主键为 `(source_key, ts_code, trade_date)`；包含标准 18 个量额字段及时间戳。当前没有草案中的 `raw_row_hash/source_fetched_at/extra_json`。
- 发布会按受影响业务键读取各源 Std 候选，再选择、upsert Serving；不是每次同步重建整个 Serving，也不会因某来源只覆盖较短历史就主动截断既有历史。
- BIYING 请求对象、100 天窗口及 Raw 归一化详见 [BIYING 维护说明](/Users/congming/github/goldenshare/docs/datasets/biying-moneyflow-dataset-development.md)。通用配置职责见 [多源映射与发布规则](/Users/congming/github/goldenshare/docs/architecture/dataset-publish-governance-spec-v1.md)，不在本文重写一套。

依据：[Definition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/moneyflow.py)、[writer](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py)、[按键发布](/Users/congming/github/goldenshare/src/foundation/ingestion/moneyflow_publish.py)、[Std 模型](/Users/congming/github/goldenshare/src/foundation/models/core_multi/moneyflow_std.py)。

## 2. 已实现映射与不可忽略的口径差异

[NormalizeMoneyflowService](/Users/congming/github/goldenshare/src/foundation/services/transform/normalize_moneyflow_service.py)把 BIYING 主买/主卖字段映射如下；Tushare 保留同名标准字段。

| 标准档位 | 买入额 / 卖出额 | 买入量 / 卖出量 |
| --- | --- | --- |
| 小单 `sm` | `zmbxdcje / zmsxdcje` | `zmbxdcjl / zmsxdcjl` |
| 中单 `md` | `zmbzdcje / zmszdcje` | `zmbzdcjl / zmszdcjl` |
| 大单 `lg` | `zmbddcje / zmsddcje` | `zmbddcjl / zmsddcjl` |
| 特大单 `elg` | `zmbtdcje / zmstdcje` | `zmbtdcjl / zmstdcjl` |

目标名分别为 `buy_<档位>_amount/sell_<档位>_amount` 和 `buy_<档位>_vol/sell_<档位>_vol`。BIYING 净流入量/额由四档买入合计减四档卖出合计生成；Tushare 使用自身 `net_mf_vol/net_mf_amount`。当前求和跳过空值，全空的一侧在另一侧有值时按零参与相减；这不是“完整字段已通过质量门禁”的证明。量字段必须能表示为整数，金额转 Decimal。

字段名对齐不代表两源统计严格等价：

- [Tushare doc 170](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/资金流向数据/0170_个股资金流向.md)按主动买卖金额分档：小单 5 万以下、中单 5～20 万、大单 20～100 万、特大单不低于 100 万；量以手、额以万元计。
- 原方案引用的 BIYING 接口说明为：中单门槛 4 万或 200 手、大单 20 万或 1,000 手、特大单 100 万或 5,000 手，小单为其余成交。此处保留原口径依据，不作为本轮重新实测。
- 4～5 万的分档差异，以及 BIYING“金额或成交量”的并列条件，都可能产生差额。不得把字段映射成功或测试通过当成源端统计等价。
- BIYING `dddx/zddy/ddcf`、`bdm*`、总额/增量与计数字段继续留在 Raw，不自动扩展现有 Serving。

旧方案“BIYING 最近约一年、Tushare 十年以上”的覆盖描述仅是当时背景，不作为当前可请求日期范围或固定验收数量。

## 3. 主备选择：当前实现与设计边界

本数据集采用整行主备的设计口径，避免同一日买卖字段混用不同统计来源。Seed 从现行 Definition 优先级得到 `primary=tushare, fallback=[biying]`。

实际发布由 [ServingPublishService](/Users/congming/github/goldenshare/src/foundation/serving/publish_service.py)读取启用的数据库 policy；没有启用 policy 时使用代码默认策略（`mode=primary`，Tushare 主、BIYING 备）。因此不能只读本文或 Definition 就断言生产此刻的 policy 值。

[ResolutionPolicyEngine](/Users/congming/github/goldenshare/src/foundation/resolution/policy_engine.py)的优先级路径：

1. 按传入的活跃来源集合筛候选；当前调用链将空集合视为不限制来源，不能将“无 active 行”描述成可靠的全停发布开关。
2. 按主源、备源顺序选第一条存在的整行；主源行存在时，即使个别金额为空，也不因本文的质量建议自动回退。
3. 优先链均未命中但还有候选时，当前通用实现按来源键排序选首个候选。
4. 通用引擎还支持字段合并和新鲜度优先；这些能力存在不代表本数据集已获准改用它们。

发布链没有接入“关键字段完整才取主源”“异常阈值触发备用源”或“方向一致率达到 95% 才放行”。不得把这些旧建议写成现行保护，也不在文档治理中改变策略。

<a id="53-已落地的对账命令mvp"></a>

## 4. 现行只读对账 CLI

`goldenshare reconcile-moneyflow` 读取两源 Raw 做比较，不写业务表、不修改 policy，也不自动触发发布。实现见 [CLI](/Users/congming/github/goldenshare/src/cli.py)、[handler](/Users/congming/github/goldenshare/src/cli_parts/ops_handlers.py)、[MoneyflowReconcileService](/Users/congming/github/goldenshare/src/ops/services/operations_moneyflow_reconcile_service.py)。

| 参数 / 输出 | 实际含义 |
| --- | --- |
| `--start-date / --end-date` | ISO 日期闭区间；未填结束日取两源最大日期中的较晚者，两源均空才用本机当天 |
| `--range-days` | 未填起点时回看自然日，默认 5，CLI 范围 1～120；不是最近 5 个交易日或共同有数据日 |
| `--sample-limit` | 默认 20，范围 0～200；限制输出样例，不限制读取规模 |
| `--abs-tol / --rel-tol` | 默认 1.0 / 0.03，用于金额比较 |
| 差异输出 | `only_tushare/only_biying/comparable_diff/direction_mismatch`；比较八档买卖金额及净流入额，不是完整成交量对账 |
| `--threshold-only-tushare / --threshold-only-biying / --threshold-comparable-diff` | 默认 -1 不检查；配置非负数后，超过阈值退出码为 1 |

样例分为仅 Tushare、仅 BIYING、可比差异三类；`direction_mismatch` 是统计值，没有独立样例组或 CLI 阈值。该 CLI 的非零退出码只有被外部流程明确接入时才构成流程门禁。

## 5. Seed：会修改什么

`goldenshare ops-seed-moneyflow-multi-source` 默认 dry-run，展示预计新增/修改计数；`--apply` 才写库并 commit。它是有副作用的配置初始化/校准工具，不是同步或对账命令。

[MoneyflowMultiSourceSeedService](/Users/congming/github/goldenshare/src/ops/services/operations_moneyflow_multi_source_seed_service.py)读取 Definition 的逻辑分组、交付方式和优先级，得到来源顺序；不写 Definition，也不写旧模式配置表。

| 对象 | apply 行为 |
| --- | --- |
| `ops.std_mapping_rule` | 某来源无 active 规则才新增通配 identity 骨架；不重写已有 active 规则 |
| `ops.std_cleansing_rule` | 某来源无 active 规则才新增 builtin/pass-through 骨架 |
| `foundation.dataset_source_status` | 缺行才新增 active；已有 inactive 行保持不变 |
| `foundation.dataset_resolution_policy` | 缺失则建立启用的 `primary_fallback`；已有策略若模式、主备或 enabled 不同，校准这些字段并递增版本；保留已有 field rules |

规则骨架不是 §2 字段映射算法的替代品。重复运行不重复创建同类有效骨架，但可能覆盖人工调整的 policy；正式 apply 仍需明确授权。命令也不自动重发全历史 Serving。

## 6. 未实现建议与验证入口

原方案的分层抽样（不同规模、行业、换手率、波动日）、量纲/分档/净流入比较仍有分析价值。方向一致率 95%、P95/P99 动态阈值、异常自动回退和额外 Std 追溯字段保留为历史建议，尚未成为本数据集自动发布合同；后续采用须另行评审，不是本轮待开发项。

变更代码时至少核对：

- [映射测试](/Users/congming/github/goldenshare/tests/test_normalize_moneyflow_service.py)、[策略引擎测试](/Users/congming/github/goldenshare/tests/test_resolution_policy_engine.py)、[发布测试](/Users/congming/github/goldenshare/tests/test_serving_publish_service.py)。
- [对账 service 测试](/Users/congming/github/goldenshare/tests/test_moneyflow_reconcile_service.py)、[对账 CLI 测试](/Users/congming/github/goldenshare/tests/test_cli_reconcile_moneyflow.py)。
- [Seed service 测试](/Users/congming/github/goldenshare/tests/test_moneyflow_multi_source_seed_service.py)、[Seed CLI 测试](/Users/congming/github/goldenshare/tests/test_cli_ops_seed_moneyflow_multi_source.py)。

本次只纠正文档，不运行 Seed、同步、重发布、源端取样或生产对账。源端口径与运行配置需要时另做有界核验，不把静态检查作为实测。
