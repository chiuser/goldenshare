# Dagster 股票分钟线 QFQ 计算测试与生产 Check 治理低层设计

更新时间：2026-07-15

状态：治理口径已确认；代码收敛尚未开始。不得启用或初始化已撤销的 as-of basis 方案。

## 1. 结论

QFQ 的计算公式正确性由受保护的测试金样本证明；生产 check 不重复计算 QFQ OHLC。check 只验证真实运行时可能偏离预期的输入、文件和状态事实。

这不是降低质量要求，而是把不同问题交给正确的机制：测试发现代码算法错误，check 发现本次生产的输入或文件错误，repair 状态检查防止历史文件已改而旧状态仍被误用。

## 2. 职责边界

| 机制 | 只负责 | 明确不负责 |
| --- | --- | --- |
| QFQ 公式金样本测试 | 日常公式、repair 公式、OHLC、五个 native 频度、90m/120m 派生、因子变动、空值和边界日期的预期输出 | 读取正式 Lake、判断当天上游是否齐备、写 Dagster event |
| production asset check | 上游当天缺代码/缺因子/重复行/空值/字段漂移；目标文件存在、schema、分区、唯一键、原子写入结果；repair 状态是否与实际改写范围一致 | 对完整分钟线重复执行 QFQ OHLC 公式；从已有 QFQ 结果反推分母；证明历史源端当年的业务判断正确 |
| lake readiness / sensor | 在最近 10 个交易日内复刻仍然 active 的生产 blocking checks，选择首个未 ready 日期 | 扫描历史 Dagster event 解释红色公式 check；运行全历史公式审计；把 check failed 改判为 ready |
| factor repair 状态账本 | 记录 repair 上游 batch、代码集合 hash、范围、七频度 completion；供下游 repair gate 判断是否需要或已经完成 | 为每个历史 QFQ 分区补普通 materialization/check event；替代 QFQ 文件契约检查 |

## 3. 公式测试契约

### 3.1 测试内容

QFQ 计算 helper 的测试必须覆盖：

1. 日常写入：`as_of_trade_date = target_trade_date`，OHLC 预期值与 silver 输入一致的边界。
2. factor repair：指定 repair 日期作为显式分母，历史每个交易日仍使用自己的同日因子作为分子。
3. 因子未变化时不产生 repair replacement；因子变化时只影响已选代码和日期范围。
4. 五个 native 频度的字段、行数、`trade_time` 对齐和 OHLC 输出；90m/120m 只从 native QFQ 派生。
5. 缺因子、零/非有限因子、重复键、空关键字段、日期错位和生命周期边界必须 fail closed。
6. repair 后的 MACD/KDJ scoped repair 输入范围与 QFQ repair metadata 一致。

### 3.2 金样本保护规则

1. 测试中的 expected OHLC 必须是人工确认的字面量；禁止调用被测 QFQ helper 生成 expected 值。
2. 公式、repair 或派生逻辑变更时，必须同时提交设计口径、fixture 输入、expected 输出和变更原因；只改断言让测试通过属于禁止行为。
3. 不得删除、跳过、缩小金样本来换取通过；静态门禁应保护核心 QFQ formula fixture 和测试文件仍被执行。
4. 测试只使用临时 DuckDB / 临时 Parquet fixture，不读取正式 Lake、Dagster instance 或生产数据库。

### 3.3 现有代码的后续收敛点

后续代码专项应把公式验证从 `defs/checks/stk_mins_checks.py` 和 `asset_guards/stk_mins_lake_readiness.py` 移至受保护测试。现有 `tests/test_stk_mins_qfq_m8b_checks.py`、`tests/test_stk_mins_qfq_m8c_history.py`、`tests/test_stk_mins_qfq_m9c_factor_repair.py` 的有效 formula fixture 应整理为稳定测试契约；不得丢弃已有反例。

## 4. QFQ production check 集合

native QFQ 正式 blocking checks 只保留以下生产事实：

| 类别 | 目标事实 | 失败含义 |
| --- | --- | --- |
| contract | 目标年份文件存在、schema、freq、路径和目标日期一致 | 分区选错、写半截、字段漂移或文件损坏 |
| key integrity | `ts_code + trade_time` 无空值、无重复，交易日与分区一致 | 输入或写入产生身份错误 |
| value domain | 价格、成交量、成交额等业务字段满足既有非公式 domain 约束 | 空值、非法数值或源端异常进入结果 |
| source coverage | 当天 silver 代码集合、同日 adj factor、目标 QFQ 代码集合和行覆盖关系完整 | 上游缺代码、缺因子、漏写或多写 |

`gold_stk_mins_qfq_formula_matches_silver_adj_factor` 不再作为正式 Dagster check，也不进入 catalog、job selection、readiness spec 或 sensor 判断。MACD/KDJ 的 `formula_sample` 同理退回测试金样本，production check 只保留文件/状态/来源覆盖事实。

## 5. Repair 状态与历史文件

1. factor repair 改写 QFQ 历史文件后，不补全历史普通 QFQ materialization/check event，避免大规模 Dagster DB 写入。
2. repair plan/status/completion 继续作为小规模状态账本，metadata 必须包含上游 batch 身份、代码数/hash、范围和频度；下游 scoped repair 只消费这一事实。
3. 日常 QFQ readiness 只判断最近 10 个交易日的正式 production checks，不读取 repair event 来覆盖一个失败 check。
4. 旧历史没有当时的 formula 生产依据时，不伪造绿色公式状态。历史文件未来被 repair 重写时，repair 状态自然记录其改写范围；这不等同于历史普通 QFQ event 回填。

## 6. 已撤销的 as-of basis 路线与代码影响

当前仓库中已提交但尚未获准启用的 as-of basis 实现，与本设计冲突。后续代码专项必须完整删除，而不是保留 dormant fallback：

1. `defs/stk_mins_qfq_as_of_basis.py`、`bootstrap/stk_mins_qfq_as_of_basis.py`、`bootstrap/stk_mins_qfq_as_of_basis_cli.py`、相关 paths/schema 和测试。
2. `defs/stk_mins_qfq.py` 中 `*_from_as_of_basis` SQL builder，以及 daily/repair/history 写入中的 basis upsert。
3. `defs/checks/stk_mins_checks.py` 中 native QFQ formula check 注册、catalog blocking check 清单和相应 check metadata。
4. `asset_guards/stk_mins_lake_readiness.py` 中年度 basis 文件读取、QFQ 公式重算和 basis validation；batch readiness 改为只复刻第 4 节的生产 check。
5. 三个 QFQ / MACD-KDJ sensor 中对 basis-ready 的假设，以及文档中将它描述为当前事实的文字。

旧 `effective_gold_qfq_readiness_for_trade_date(...)` repair-event 覆盖逻辑不恢复。目标是单一事实：production checks 失败就是未 ready；公式逻辑由测试保障，不在 readiness 中出现第二套例外。

## 7. 性能口径

1. 不执行全历史 QFQ 公式 bootstrap，不创建 `gold/quote/stk_mins_qfq_as_of_basis/**`，不增加 Lake 侧车文件。
2. QFQ sensor 热路径最多读取最近 10 个交易日对应的 QFQ/silver/adj factor 文件集合，并且只运行 production contract/key/value/coverage 聚合，不做 OHLC 重算。
3. check/readiness 不得将分钟行扩成 OHLC 四倍中间行，不得扫描全历史，不得使用 Dagster event history 解释公式差异。
4. 因子 repair 的 `freq/year` 批量计算性能方案保留；它是实际写入逻辑，不是 check 的重复验证。

## 8. 实施顺序与验收

1. 先按本文同步治理、性能和 QFQ 设计文档。
2. 单独审计并设计代码删除/收敛专项；不得在该专项之外顺手修改 QFQ 计算公式或 repair 范围。
3. 本地 fixture 测试必须证明公式金样本完整，production checks 不再执行 QFQ OHLC 重算，batch readiness 不再 import as-of basis。
4. `git diff --check`、相关 unit/static-gate 测试和文档完整性检查通过后，才可讨论 definitions reload 或正式实例只读验证。
5. 不运行 bootstrap plan/apply，不写 Lake、不写 Dagster instance、不启停 sensor；这些均不属于本治理文档实施阶段。
