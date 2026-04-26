# 资金流数据集（`moneyflow`）多源融合策略设计 V1

## 1. 目标与边界

- 目标：在不影响现有对上服务稳定性的前提下，为 `moneyflow` 建立可持续的多源融合策略（Tushare + BIYING）。
- 当前边界：
  - BIYING 已接入 `raw_biying.moneyflow`，本阶段先完成策略设计，不改业务代码。
  - Serving 口径继续保持现有 `core_serving.equity_moneyflow` 结构。
  - 暂不做字段级“拼接融合”（同一行来自多个源的混拼），先采用行级主备融合。

## 2. 两个数据源字段结构对比

## 2.1 Tushare（当前 serving 直系字段）

- 来源表：`raw_tushare.moneyflow`
- 对上目标表：`core_serving.equity_moneyflow`
- 核心字段：
  - 分档买卖成交量/成交额：`buy_sm/md/lg/elg_*`, `sell_sm/md/lg/elg_*`
  - 净流入：`net_mf_vol`, `net_mf_amount`

## 2.2 BIYING（当前 raw 全量落库）

- 来源表：`raw_biying.moneyflow`
- 特点：
  - 字段更丰富（主动/被动、成交额/成交量/占比及增量）
  - 命名体系与 Tushare 不一致（`zmb*`, `zms*`, `bdm*` 等）
  - 分档规则（接口说明）：
    - 特大单：成交额 `>=100万` 或成交量 `>=5000手`
    - 大单：成交额 `>=20万` 或成交量 `>=1000手`
    - 中单：成交额 `>=4万` 或成交量 `>=200手`
    - 小单：其余成交

## 2.3 可对齐字段（建议作为第一批标准融合字段）

以下映射为“候选标准映射”，上线前需做抽样校验确认口径一致：

| 标准语义 | Tushare 字段 | BIYING 候选字段 |
|---|---|---|
| 超大单买入额 | `buy_elg_amount` | `zmbtdcje` |
| 大单买入额 | `buy_lg_amount` | `zmbddcje` |
| 中单买入额 | `buy_md_amount` | `zmbzdcje` |
| 小单买入额 | `buy_sm_amount` | `zmbxdcje` |
| 超大单卖出额 | `sell_elg_amount` | `zmstdcje` |
| 大单卖出额 | `sell_lg_amount` | `zmsddcje` |
| 中单卖出额 | `sell_md_amount` | `zmszdcje` |
| 小单卖出额 | `sell_sm_amount` | `zmsxdcje` |
| 超大单买入量 | `buy_elg_vol` | `zmbtdcjl` |
| 大单买入量 | `buy_lg_vol` | `zmbddcjl` |
| 中单买入量 | `buy_md_vol` | `zmbzdcjl` |
| 小单买入量 | `buy_sm_vol` | `zmbxdcjl` |
| 超大单卖出量 | `sell_elg_vol` | `zmstdcjl` |
| 大单卖出量 | `sell_lg_vol` | `zmsddcjl` |
| 中单卖出量 | `sell_md_vol` | `zmszdcjl` |
| 小单卖出量 | `sell_sm_vol` | `zmsxdcjl` |

净流入建议：

- `net_mf_amount = (buy 四档金额合计) - (sell 四档金额合计)`
- `net_mf_vol = (buy 四档成交量合计) - (sell 四档成交量合计)`

## 2.5 分档口径一致性结论（基于当前信息）

Tushare 说明（你补充的口径）：

- 小单：`<5万`
- 中单：`5万~20万`
- 大单：`20万~100万`
- 特大单：`>=100万`
- 且数据基于主动买卖单统计

对比 BIYING 后的结论：

1. **大单 / 特大单金额阈值基本一致**
- `20万` 与 `100万` 两个关键边界一致，具备较高可比性。

2. **中单 / 小单边界不完全一致**
- BIYING 中单下限是 `4万`，Tushare 是 `5万`。
- 因此 `4万~5万` 区间会出现分档归类差异（BIYING 归中单，Tushare 归小单）。

3. **BIYING 多了“成交量阈值并列条件”**
- BIYING 使用“金额阈值 **或** 成交量阈值”判档。
- Tushare 当前口径描述主要是金额分档（且基于主动买卖）。
- 这会导致在“金额不达标但成交量达标”的样本上，两源分档结果可能不同。

4. **主动买卖统计语义整体接近，但仍需实证校验**
- 两源都体现主买/主卖方向统计，但具体成交归类实现细节可能不同。
- 结论是“可近似对齐”，但不是“严格等价口径”。

## 2.4 暂不纳入第一批 serving 融合的 BIYING 字段

- 趋势/动向类：`dddx`, `zddy`, `ddcf`
- 被动买卖全套：`bdm*`
- 成交总额与增量：`*cjzl`, `*cjzlv`
- 统计计数类：`zmbzds`, `zmszds`, `zmbzdszl`, `zmszdszl`, `cjbszl`

处理建议：先保留在 raw；后续如有业务需求，进入“扩展指标”数据集而不是直接挤进现有 `equity_moneyflow`。

## 3. 推荐融合策略（V1）

## 3.1 策略总览

1. `raw -> std`：做字段标准化映射（两源都映射到同一标准列）。
2. `std -> serving`：做“行级主备融合”。
3. 默认策略：`primary=tushare`, `fallback=biying`。

## 3.2 为什么先不用字段级混拼

- 两源口径存在潜在差异（主动/被动定义、量纲、阈值边界，尤其 `4万~5万` 与“金额或成交量”并列判档）。
- 同行混拼容易出现“同一日买卖金额来自不同源导致不自洽”。
- 行级主备可解释性更强，排障更简单，回滚成本低。

## 3.3 行级主备规则（建议）

键：`(ts_code, trade_date)`（BIYING 的 `dm` 需标准化为 `ts_code`）

- 已知现状：BIYING 资金流当前仅覆盖最近约一年历史；Tushare 覆盖十年以上。
- 因此 V1 必须固定为：`primary=tushare`、`fallback=biying`，避免 serving 历史被截断到一年窗口。
- 若主源（tushare）存在且关键字段完整：取主源整行。
- 若主源缺失：取备用源（biying）整行。
- 若主源存在但关键字段异常（可配置阈值）：允许回退备用源。

关键字段完整性判定建议（最小集合）：

- `buy_sm_amount`, `sell_sm_amount`, `buy_lg_amount`, `sell_lg_amount`, `net_mf_amount`

## 4. 标准层（std）建议字段模型

为避免 `equity_moneyflow` 被过早扩列，建议：

- `core_multi.moneyflow_std`（实体或逻辑层，按团队当前落地策略选择）
- 核心字段：
  - `source_key`, `ts_code`, `trade_date`
  - 标准 18 列（与 `core_serving.equity_moneyflow`一致）
  - `raw_row_hash`（可选，便于追溯）
  - `source_fetched_at`（可选）
- BIYING 额外字段先不入主 std，可放 `extra_json`（可选）。

## 5. 数据质量与对账策略

## 5.1 上线前抽样校验（必须）

按股票、日期分层抽样，至少覆盖：

- 大盘蓝筹 / 中小盘 / 高换手
- 平稳日 / 极端波动日
- 不同行业

校验项：

1. 量纲一致性：金额与成交量数量级是否匹配。
2. 分档一致性：四档买卖额占比结构是否同向。
3. 净流入一致性：方向（正负）与绝对值误差是否在阈值内。

## 5.2 误差阈值建议

- 方向一致率：>= 95%
- 绝对误差：按分位值设定动态阈值（P95/P99）
- 超阈值样本进入人工复核清单

## 5.3 已落地的对账命令（MVP）

已实现 CLI：`goldenshare reconcile-moneyflow`

- 默认行为：
  - 未传日期时，自动取双源最新日期并回看最近 `5` 天（可用 `--range-days` 调整）。
- 输出内容：
  - `only_tushare / only_biying / comparable_diff / direction_mismatch`
  - 每类差异可输出样例（`--sample-limit`）
- 门禁能力：
  - 支持 `--threshold-only-tushare / --threshold-only-biying / --threshold-comparable-diff`
  - 超阈值返回非 0，便于发版前卡口
- 容差参数：
  - `--abs-tol`（绝对误差阈值）
  - `--rel-tol`（相对误差阈值）

## 6. OPS 配置与发布建议

- 初始模式：`moneyflow` 维持单源（tushare）对外。
- 预演阶段：
  - BIYING 同步持续跑 raw。
  - 先做对账报告，不切 serving。
- 切换阶段：
  - 发布 `std mapping` + `resolution policy`。
  - 先灰度到“缺失回退”模式（仅主源缺失时启用备用源）。
  - 稳定后再评估是否开启“主源异常回退”。

## 6.1 已落地的配置骨架 Seed（当前阶段）

已新增命令：`goldenshare ops-seed-moneyflow-multi-source [--apply]`

- `dry-run`：仅展示将写入内容，不改库。
- `--apply`：写入/修正如下对象（可重复执行）：
  - DatasetDefinition 派生投影：`moneyflow -> multi_source_fusion`（`tushare,biying`），不再写旧数据集模式配置表
  - `ops.std_mapping_rule`：`moneyflow+tushare` 与 `moneyflow+biying` 默认映射骨架
  - `ops.std_cleansing_rule`：`moneyflow+tushare` 与 `moneyflow+biying` 默认清洗骨架
  - `foundation.dataset_source_status`：`moneyflow` 的 `tushare/biying` 均置为 active
  - `foundation.dataset_resolution_policy`：强制主备口径 `primary=tushare`, `fallback=[biying]`

## 7. 分阶段落地计划

### Phase A（已完成）

- BIYING 资金流向 raw 接入：`raw_biying.moneyflow`

### Phase B（已完成）

- 定义并落地 `moneyflow` 标准层实体：`core_multi.moneyflow_std`
- 两源同步链路已接入标准化写入：
  - `sync_moneyflow`（tushare）写入 `moneyflow_std`
  - `sync_biying_moneyflow`（biying）写入 `moneyflow_std`
- 对账脚本（按“可对齐字段”）已完成 MVP：`reconcile-moneyflow`

### Phase C（已完成首版）

- 已接入 `resolution -> serving` 发布链路，`moneyflow` 支持从 `std` 按策略发布到 `core_serving.equity_moneyflow`
- 已支持 `primary_fallback` 策略模式（`primary=tushare`，`fallback=biying`）
- 已新增骨架初始化命令：`ops-seed-moneyflow-multi-source`（可重复执行）

### Phase D（持续优化）

- 观测期保留快速回滚能力
- 根据线上对账结果迭代关键字段校验阈值与回退条件

## 8. 风险清单

- 口径定义风险：主动/被动、阈值分档可能与 Tushare 不完全等价（已确认存在 `4万~5万` 归档差异及“金额或成交量”并列判档差异）。
- 代码归一风险：BIYING `dm` 与系统 `ts_code` 归一失败会引发错配。
- 时间对齐风险：`quote_time` 到 `trade_date` 的边界需确认（时区/夜间更新）。

---

本设计遵循“先可解释、再精细化”的路线：先把可对齐字段稳定融合，再考虑扩展字段与更复杂的策略。
