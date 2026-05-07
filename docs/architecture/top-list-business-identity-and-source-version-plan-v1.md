# `top_list` 业务身份与来源版本收口方案 V1

## 1. 背景

近期对 `tushare.top_list` 做真实源站审计后，已经确认下面两类问题同时存在：

1. 同一个 `ts_code + trade_date + 上榜原因`，源站会返回多个版本。
2. 多个版本之间，有时只是 `float_values=nan/None` 这样的伪空值漂移；有时会出现 `l_sell / l_amount / net_amount / net_rate / amount_rate` 等数值差异。

现状实现里：

- raw 层主键是 `(ts_code, trade_date, reason)`，见 [raw_top_list.py](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_top_list.py)
- serving 层唯一键是 `(ts_code, trade_date, reason_hash)`，见 [equity_top_list.py](/Users/congming/github/goldenshare/src/foundation/models/core/equity_top_list.py)
- writer/DAO 会先按冲突键在内存里折叠，再 upsert，见 [writer.py](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py) 与 [base_dao.py](/Users/congming/github/goldenshare/src/foundation/dao/base_dao.py)

这会带来两个问题：

1. raw 层无法保留“同一 `reason` 下的多个来源版本”。
2. serving 层把“业务身份”和“来源版本”混成了一件事，后续没法稳妥地做口径判定。

---

## 2. 本方案的核心结论

**不要把更多数值列直接并入 `reason_hash`。**

原因很直接：

- `reason_hash` 现在表达的是“这只股票在这一天，因某个上榜原因发生了一条龙虎榜事件”
- 如果把 `l_sell / net_amount / amount_rate / float_values` 等数值列也并进去，`reason_hash` 的含义就从“业务事件身份”变成了“某个来源版本的具体行”
- 这样会把“同一个龙虎榜事件的多个来源版本”错误拆成多条业务事件，语义会直接变脏

正确方向是：

1. 保留现有 `reason_hash` 作为 **业务身份键**
2. 新增 `payload_hash` 作为 **来源版本键**

一句话概括：

- `reason_hash` 回答：是不是同一个龙虎榜事件
- `payload_hash` 回答：这个事件是不是来了多个来源版本

---

## 3. 目标与非目标

### 3.1 目标

1. 让 raw 层尽可能保留 `top_list` 的不同来源版本，不再因为 raw 主键过窄而覆盖丢失。
2. 让 serving 层继续保持“一条业务事件一条事实”的模型，不因为版本保留而把业务身份打散。
3. 为后续的版本选择策略提供单一事实源，不再靠运行时猜测或临时补丁。

### 3.2 非目标

1. 本方案不把所有 `top_list` 数值冲突一次性定成最终业务规则。
2. 本方案不扩展到其它数据集。
3. 本方案不引入双写兼容或长期过渡层；按停机重建思路设计。

---

## 4. 当前问题分类

基于 `tests/integration/test_tushare_top_list_reason_audit.py` 的真实审计样本，目前至少存在三类情况：

### 4.1 展示字段漂移

- `reason` 标点差异
- `name` 文本差异

业务身份通常不变。

### 4.2 可空数值字段伪空值漂移

- 典型是 `float_values = nan / None / 空字符串`

这类通常不是“另一条业务数据”，而是同一版本的坏值变体。

### 4.3 数值口径冲突

- `l_sell`
- `l_amount`
- `net_amount`
- `net_rate`
- `amount_rate`

这类不能简单说“大值更对”或“小值更对”，必须保留版本后再做业务判定。

---

## 5. 目标模型

### 5.1 概念拆分

#### 业务身份（Business Identity）

表示“同一个龙虎榜事件”：

- `ts_code`
- `trade_date`
- `reason_hash`

#### 来源版本（Source Variant）

表示“源站对这个业务事件返回的某一个具体版本”：

- `payload_hash`

---

## 6. Hash 设计

### 6.1 `reason_hash`

保持现义不变：

- 输入：`normalize_top_list_reason(reason)`
- 目的：把同义原因文案的标点/空白波动收口成同一个业务身份

当前实现位置：

- [top_list_reason.py](/Users/congming/github/goldenshare/src/foundation/services/transform/top_list_reason.py)

### 6.2 `payload_hash`

新增字段，表示来源版本。

建议按“归一化后的来源 payload”计算，字段顺序固定为：

1. `ts_code`
2. `trade_date`
3. `reason`
4. `name`
5. `close`
6. `pct_change`
7. `turnover_rate`
8. `amount`
9. `l_sell`
10. `l_buy`
11. `l_amount`
12. `net_amount`
13. `net_rate`
14. `amount_rate`
15. `float_values`

### 6.3 `payload_hash` 的归一化规则

1. 日期统一转 ISO 文本
2. `Decimal` 统一转规范字符串
3. `None / "" / "nan" / "nat" / "none" / "null"` 统一视为 `null`
4. `reason` 保留原始文本，不走 `reason_hash` 的收口逻辑
5. `name` 保留原始文本

这样设计的目的：

1. 同一个原始 `reason` 下，只要数值不同，就能保留成两个版本
2. `float_values=nan` 与 `float_values=None` 这类伪空值不会被人为扩大成多个无意义版本
3. `reason` 标点差异仍会形成不同 `payload_hash`，因为它们确实是不同来源文本版本

---

## 7. 数据模型调整方案

### 7.1 raw 层

目标表：`raw_tushare.top_list`

### 现状

- 主键：`(ts_code, trade_date, reason)`

### 调整后

新增字段：

- `reason_hash`
- `payload_hash`

建议主键/唯一键收口为：

- `PRIMARY KEY (ts_code, trade_date, reason, payload_hash)`

补充索引：

- `INDEX (ts_code, trade_date, reason_hash)`
- `INDEX (trade_date)`

### 为什么不是只用 `payload_hash` 当主键

可以，但不建议。

原因：

1. 当前查询与排查天然会按 `ts_code / trade_date / reason_hash` 看问题
2. 复合主键更直观，便于人工审计
3. `payload_hash` 更适合作为“版本维度”，不必单独承担全部行身份语义

### 7.2 serving 层

目标表：`core_serving.equity_top_list`

### 现状

- 唯一键：`(ts_code, trade_date, reason_hash)`

### 调整后

继续保留一行一个业务事件的模型：

- `UNIQUE (ts_code, trade_date, reason_hash)`

新增溯源字段：

- `selected_payload_hash`
- `variant_count`
- `resolution_policy_version`

说明：

- `selected_payload_hash`：当前 serving 行来自哪个 raw 版本
- `variant_count`：这个业务身份下 raw 层一共有几个版本
- `resolution_policy_version`：便于以后切换选择规则时回溯

---

## 8. 写入与收口流程

```text
source row
  -> row_transform
  -> 计算 reason_hash（业务身份）
  -> 计算 payload_hash（来源版本）
  -> raw 写入：按 (ts_code, trade_date, reason, payload_hash) 保留版本
  -> 按 (ts_code, trade_date, reason_hash) 对 raw 版本分组
  -> resolution policy 选出一个版本
  -> serving 写入：1 个业务身份对应 1 行
```

---

## 9. Resolution Policy 设计

### 9.1 第一阶段必须明确的规则

### 规则 A：伪空值优先级

当同一业务身份下出现：

- 一条 `float_values` 为有效值
- 一条 `float_values` 为 `null`

则优先保留非空值版本。

这条已经在当前代码里作为止血规则落地，但只作用在 serving 批内冲突上，后续应迁移为正式版本选择策略。

### 9.2 第二阶段待业务判定的规则

对下面这类数值冲突，本方案不在 V1 里拍板：

- `l_sell`
- `l_amount`
- `net_amount`
- `net_rate`
- `amount_rate`

建议做法：

1. raw 保留全部版本
2. serving 先走明确规则，再保留溯源字段
3. 对仍无法判定的版本，允许输出 issue 或审计样本，而不是在 raw 层先丢数据

---

## 10. API / 下游影响

### 10.1 不变的部分

以下用户面语义不应改变：

- `top_list` 仍是一个数据集
- TaskRun / Ops / catalog / audit 仍按 `trade_date` 和数据集维度看它
- 对外业务读取仍从 `core_serving.equity_top_list` 取“单条业务事实”

### 10.2 新增的能力

后续若需要排查争议样本，可以支持：

- 按 `ts_code + trade_date + reason_hash` 查看所有 raw 版本
- 查看 serving 当前选中了哪个 `payload_hash`

---

## 11. 实施步骤

### M1. 引入双 hash 模型

1. 新增 `payload_hash` 计算函数
2. `top_list` row transform 产出 `payload_hash`
3. 补单元测试，覆盖：
   - 相同 `reason_hash`、不同 payload
   - 相同 payload、伪空值归一

### M2. 重建 raw 层模型

1. 调整 `raw_tushare.top_list` ORM 与 DDL
2. raw 写入改按 `(ts_code, trade_date, reason, payload_hash)`
3. 验证不会再因 raw 主键过窄而覆盖版本

### M3. 重建 serving 收口逻辑

1. 在 writer 或 dedicated resolver 中按 `reason_hash` 分组版本
2. 增加 `selected_payload_hash / variant_count / resolution_policy_version`
3. 先实现明确规则：
   - 非空 `float_values` 优先

### M4. 数据重建与验证

1. 停机重建 `top_list` raw 与 serving
2. 以真实日期窗口做抽样对账
3. 核验：
   - raw 版本保留数
   - serving 最终行数
   - variant_count 分布
   - 争议样本是否可追溯

---

## 12. 验证门禁

至少需要：

1. `payload_hash` 单测
2. raw 保留多版本写入测试
3. serving 版本选择测试
4. 真实样本对账：
   - `2017-03-29 新泉股份`
   - `2017-03-29 绝味食品`
   - 近期稳定窗口 `2026-01-01 ~ 2026-04-30`

---

## 13. 本方案的取舍

### 选这个方案的原因

1. 不会污染 `reason_hash` 的业务语义
2. 可以最大化保留源站版本信息
3. 后续即使业务判定规则升级，也不用再回头追“被覆盖掉的版本”

### 不选“直接把更多数值列并进 `reason_hash`”的原因

1. 会把“同一业务事件的多个来源版本”误拆成多条事件
2. 会污染下游对 `reason_hash` 的身份认知
3. 会让 `top_list` 的业务口径和别的数据集越来越不统一

---

## 14. 已确认点

### D1. serving 对“非 `float_values` 的数值冲突版本”，V1 先保守保留当前最后一条口径

已确认。

理由：

1. 当前最重要的是先把版本保留下来，避免 raw 层继续丢信息
2. 版本一旦保留下来，后续再调 resolution policy 就不会丢历史依据
3. 这次先不要在没有稳定业务规律前，强行定义“大值优先”或“小值优先”
