# top_list 业务身份与来源版本维护说明

状态：V1 已实施；后续数值冲突规则未决。更新时间：2026-09-11。
本文按当前定义、模型、normalizer 和 writer 校准；不代表本轮核验了源端或生产数据，不授权重新迁移或回补。

## 1. 两种身份不要混用

同一股票、日期、上榜原因可以收到不同数值版本。业务身份回答“是哪条上榜事件”，来源版本回答“收到了哪份内容”；不能把金额、涨幅、流通市值拼入 reason 来逃避冲突。

| 层 | 当前身份与作用 |
| --- | --- |
| Raw `raw_tushare.top_list` | 主键 `(ts_code, trade_date, reason, payload_hash)`，保留不同来源内容；`reason_hash` 非空 |
| Serving `core_serving.equity_top_list` | ORM/迁移主键仍为 `(ts_code, trade_date, reason)`；唯一约束及 writer 冲突列是 `(ts_code, trade_date, reason_hash)`，每个业务身份发布一行 |

模型目录名 `models/core` 不表示 SQL schema 是 `core`。Raw 不是抓取日志：相同 payload 重复抓取按同一身份 upsert，不为每次请求新增一个版本。

依据：[定义](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/market_equity.py)、[Raw 模型](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_top_list.py)、[Serving 模型](/Users/congming/github/goldenshare/src/foundation/models/core/equity_top_list.py)。

## 2. 两种 hash 的实际算法

### reason_hash：业务原因身份

[normalize_top_list_reason](/Users/congming/github/goldenshare/src/foundation/services/transform/top_list_reason.py) 先做 Unicode NFKC，再去首尾空白、把连续空白压成一个空格；空值/空字符串不生成 hash，其余按 UTF-8 SHA-256。

这只处理 Unicode 兼容形式与空白，不做原因同义匹配，也不承诺任意标点等价。业务字段不参与 reason hash，原 reason 不因生成 hash 而被改写成新业务描述。

### payload_hash：来源内容身份

[build_top_list_payload_hash](/Users/congming/github/goldenshare/src/foundation/services/transform/top_list_payload.py) 按以下固定顺序取值，用 `\x1f` 分隔后做 SHA-256：

`ts_code, trade_date, reason, name, close, pct_change, turnover_rate, amount, l_sell, l_buy, l_amount, net_amount, net_rate, amount_rate, float_values`。

- `pct_change` 键不存在时才取 `pct_chg` 别名；存在但为空不会回退。
- None、数值 NaN，以及去空白后大小写不敏感的空串/nan/nat/none/null，统一为文本 `null`。
- Decimal/float 以十进制文本去多余尾零，负零归零；普通数值字符串不保证获得同样的数值规范化。
- 日期用 ISO；trade_date 的 datetime 取日期。reason/name 文本保留原样，其他文本去首尾空白。
- 抓取时刻不参与内容 hash；这不是“最新抓取版本”的排序键。

[行转换](/Users/congming/github/goldenshare/src/foundation/ingestion/row_transforms.py) 先规范 float_values，再生成两个 hash。Raw/Serving 字段别名对应时应得到同一 payload hash。

## 3. 当前写入和版本选择

```text
当前 NormalizedBatch
  → 构造 Raw 行和 Serving 候选
  → 候选按 (ts_code, trade_date, reason_hash) 分组、按 payload_hash 去重
  → 按现行策略选择每组一行
  → Raw upsert → Serving upsert
```

定义选择 `raw_core_upsert` 和 `top_list_variant_resolution_v1`；算法见 [DatasetWriter](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py) 的 `_write_raw_and_core`、`_apply_serving_conflict_resolution`。

V1 已确认并实现的选择规则：

1. 有效非空 float_values 优先于空值；不是取最大 float_values。
2. 两者都非空或都为空时，以遍历中后到的候选为准。这是确定性去重策略，不证明该版本业务上更正确。
3. 同一 payload 重复出现会更新该 hash 对应的候选，但不会把它的首次出现顺序移到队尾。因此不能概括成“原始最后一行无条件获胜”。
4. 缺少分组键或 payload hash 的行在此函数中按单行透传并标记版本数 1；此函数不是完整合法性校验器，不能把它写成统一拒绝缺字段。

**候选范围只有本次 writer batch，不查询 Raw 历史再全局择优。** 后一批只有空 float_values 时，也不会在此处读回较早批次的非空值保护它。保留这个实现边界，不在文档治理中悄悄改变算法。

Serving 的追溯字段：

| 字段 | 当前含义 |
| --- | --- |
| `selected_payload_hash` | 本批选中的 payload hash |
| `variant_count` | 本批同业务身份的不同 payload 数，至少为 1；不是 Raw 历史累计数 |
| `resolution_policy_version` | `top_list_variant_resolution_v1` |

后续批次可更新这些字段，variant_count 不保证单调增长。数据库有追溯字段，也不等于页面/API 已提供版本切换或差异展示。

## 4. 已完成迁移，不是待执行步骤

[20260507_000099](/Users/congming/github/goldenshare/alembic/versions/20260507_000099_preserve_top_list_source_variants.py) 的 down_revision 是 `20260506_000098`；迁移仅适用于 PostgreSQL，重建 Raw/Serving 身份与追溯字段，并建立相应索引。

**该历史迁移包含删除表和数据，不可作为日常修复命令重跑。** 涉及：

- `core_serving.equity_top_list`
- `raw_tushare.top_list`
- `core.equity_top_list`
- `raw.top_list`

历史实施口径是不回填旧表，改按目标日期窗口重新同步；迁移本身不执行同步，也不等于完成历史数据回补。本轮只读代码，未核实生产迁移版本、表数量或回补完整性。downgrade 同样不是无损恢复手段。

## 5. 回归与尚未决策的内容

现有离线回归入口：

- [normalizer 测试](/Users/congming/github/goldenshare/tests/test_dataset_normalizer.py)：reason 兼容形式、空值和 Raw/Serving payload 一致。
- [writer 测试](/Users/congming/github/goldenshare/tests/test_dataset_writer_stock_basic.py)：Raw/Serving 分别使用的冲突键、非空优先、版本去重计数。
- [registry 测试](/Users/congming/github/goldenshare/tests/test_dataset_definition_registry.py)：定义合同与策略版本。

原方案列出的 `2017-03-29` 新泉股份/绝味食品及 `2026-01-01 ~ 2026-04-30` 是历史验收候选窗口，不是本文已证明的生产通过记录。

仍未决定的是多个非空数值（如 l_sell/l_amount/net_amount/net_rate/amount_rate）冲突时如何判断业务正确性，以及是否需要跨批历史择优、历史版本差异查询。争议可通过审计样本说明，但本文不宣称 writer 已自动生成 issue。V1 现行后到候选规则不因此自动失效；未来变更须先明确业务依据、全量消费者及回归，不能擅自选择 max/min、拼接原因或新增版本 UI。

保持用户面边界：top_list 仍是一个数据集，TaskRun/Ops/catalog/audit 仍按数据集与 trade_date 观测，对外业务读取仍取 Serving 的单条事实。本轮仅纠正文档，无新业务规则、表迁移或接口行为变更。
