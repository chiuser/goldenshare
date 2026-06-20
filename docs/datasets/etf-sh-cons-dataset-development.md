# 上交所 ETF 申赎清单（`etf_sh_cons`）数据集开发说明

## 1. 目标与边界

本数据集用于接入 Tushare `etf_sh_cons`，保存上交所 ETF 申赎清单源站事实。首期目标是打通从源站到 `raw_tushare.etf_sh_cons` 的维护链路，并通过 `core_serving.etf_sh_cons` 普通 view 对外服务。

本轮方案已进入 LLD 推进阶段。后续编码必须继续遵守数据集开发模板、根 `AGENTS.md` 和当前 DatasetDefinition 主线。

代码层 LLD：[ETF 申赎清单低层设计 LLD v1](/Users/congming/github/goldenshare/docs/datasets/etf-sh-cons-low-level-design-v1.md)。

边界：

- 只写 raw，不额外写一份 serving 物理表。
- `core_serving.etf_sh_cons` 是普通 view，直接读取 raw。
- 首期开放手动维护和自动任务配置。
- 首期不加入 `daily_market_close_maintenance` 工作流。
- Ops 展示分组归入 ETF 分类。
- 不走“单日全市场深分页”作为正式维护策略。

## 2. 已拍板口径

| 事项 | 结论 |
| --- | --- |
| ETF 基准池 | 使用 `ops.etf_series_active`。 |
| 池资源 key | 必须使用独立资源：`resource='etf_sh_cons'`。 |
| 池代码范围 | 只允许 `.SH` ETF 代码；`.SZ` / `.OF` 写入该资源应视为配置错误。 |
| 空池行为 | 任务失败，并提示先配置 `etf_sh_cons` ETF 激活池；不得回退到其他池或全量猜测。 |
| 显式 `ts_code` | 必须在 `resource='etf_sh_cons'` 池内，避免绕过运营门禁。 |
| 存储口径 | raw 保存源站事实，serving 用 view 直出 raw。 |
| 工作流 | 首期不加入每日收盘工作流。 |
| 请求策略 | 单日按 `trade_date + ts_code`；区间按 `ts_code + 半年窗口 start_date/end_date`。 |

## 3. 源接口实测结论

本地源站事实文档已补齐：[ETF申赎清单](/Users/congming/github/goldenshare/docs/sources/tushare/ETF专题/0407_ETF申赎清单.md)，并已同步 `docs/sources/tushare/docs_index.csv`。当前接口行为来自 Tushare Pro 真实请求验证。

| 请求形态 | 实测结论 | 对方案的影响 |
| --- | --- | --- |
| 不传业务参数 | 可返回默认页，但不是可控的完整维护策略。 | 不作为主链。 |
| `trade_date` 单日全市场分页 | 可返回数据，但深分页在高 offset 处出现源站报错。 | 禁止作为正式策略。 |
| `trade_date + ts_code` | 可稳定返回单只 ETF 单日申赎清单。 | 单日维护采用该策略。 |
| `ts_code + start_date/end_date` | 可返回单只 ETF 区间内多日申赎清单，并支持分页。 | 区间维护采用该策略。 |
| 多个 `ts_code` 逗号拼接 | 返回 0 行。 | 禁止多代码合并请求。 |
| `ts_code` 通配符 | 返回 0 行。 | 禁止通配符请求。 |
| 分页上限 | 单页有效返回上限按 3000 行处理。 | `page_limit=3000`。 |
| 限速 | 实测触发 500 次/分钟限制。 | 必须走共享 Tushare 限速器。 |

已生成的验证材料：

- `reports/etf_sh_cons_fund_daily_sh_probe_20260618.csv`
- `reports/etf_sh_cons_available_codes_20260618.csv`
- `reports/etf_sh_cons_unavailable_codes_20260618.csv`

结论：以现有 `fund_daily` 池中的 `.SH` ETF 代码为样本，`20260618` 最新交易日共验证 803 个代码，命中 803 个，未命中 0 个，错误 0 个。

## 4. 三层语义拆分

| 语义层 | 本数据集口径 |
| --- | --- |
| 时间输入语义 | 运营提交的是单个交易日，或一个交易日期区间。 |
| 执行 / unit 语义 | 单日：每个 ETF code 一个 unit，请求 `trade_date + ts_code`。区间：每个 ETF code 按自然半年窗口拆 unit，请求 `ts_code + start_date + end_date`。 |
| freshness / audit 语义 | 以 `trade_date` 为观测日期接入 freshness。V1 不接日期-ETF 完整性审计；若后续要审计“日期 × ETF 激活池”矩阵，必须单独设计。 |

说明：

- 这里的“半年”指自然半年窗口：`01-01 ~ 06-30`、`07-01 ~ 12-31`，再按用户输入的 `start_date/end_date` 裁剪边界。
- 例如 `2025-03-10 ~ 2026-05-29` 会拆为 `2025-03-10 ~ 2025-06-30`、`2025-07-01 ~ 2025-12-31`、`2026-01-01 ~ 2026-05-29`。

## 5. 请求策略

## 5.1 单日维护

输入：

- `time_input.mode = "point"`
- `trade_date = YYYY-MM-DD`
- 可选 `filters.ts_code`

执行：

1. 若填写 `ts_code`，必须校验该代码在 `ops.etf_series_active(resource='etf_sh_cons')` 中，且后缀为 `.SH`。
2. 若未填写 `ts_code`，读取 `ops.etf_series_active(resource='etf_sh_cons')` 中全部 `.SH` ETF。
3. 每个 ETF code 生成一个 unit。
4. request builder 生成源接口参数：`ts_code=<ETF code>`、`trade_date=YYYYMMDD`。
5. source client 统一追加 `limit=3000`、`offset` 并分页，直到当页不足 `limit`。

## 5.2 区间维护

输入：

- `time_input.mode = "range"`
- `start_date = YYYY-MM-DD`
- `end_date = YYYY-MM-DD`
- 可选 `filters.ts_code`

执行：

1. 先解析 ETF code 集合，规则与单日维护一致。
2. 将输入日期区间拆成自然半年窗口。
3. 每个 `ETF code + 半年窗口` 生成一个 unit。
4. request builder 生成源接口参数：`ts_code=<ETF code>`、`start_date=YYYYMMDD`、`end_date=YYYYMMDD`。
5. source client 统一追加 `limit=3000`、`offset` 并分页，直到当页不足 `limit`。

禁止项：

- 禁止把区间拆成 `ETF code × 每个交易日`，请求量不可接受。
- 禁止把全市场单日分页作为正式维护主链，源站深分页不稳定。
- 禁止多个 ETF code 拼成一个 `ts_code` 参数。
- 禁止对 `.SZ` / `.OF` 静默跳过。

## 6. 请求量与性能评估

使用 `ETF code + 半年窗口` 的原因是平衡稳定性与请求量：

- 相比 `ETF code × 每个交易日`，半年窗口把一个 ETF 半年的历史压缩成一个 unit，再由分页处理结果集，显著减少 unit 数。
- 相比单日全市场深分页，按 code 限定数据范围，避免全市场大 offset 触发源站错误。
- 相比按全年或更长区间，半年窗口降低单个 unit 的分页深度，避免某些成分较多的 ETF 在长区间内结果集过深。

量级估算：

| 场景 | 估算 unit 数 |
| --- | --- |
| 单日全池，803 个 `.SH` ETF | 约 803 个 unit |
| 1 年全池 | 约 803 × 2 = 1606 个 unit |
| 3 年全池 | 约 803 × 6 = 4818 个 unit |
| 10 年全池 | 约 803 × 20 = 16060 个 unit |

每个 unit 内分页次数取决于该 ETF 在该窗口内的成分行数。V1 不把 `limit/offset` 暴露给运营侧，分页仍由 source client 统一处理，并受 Tushare 共享限速器约束。

## 7. 字段与存储设计

源站字段按实测保留：

| 字段 | 含义 | raw | serving view | 清洗口径 |
| --- | --- | --- | --- | --- |
| `trade_date` | 交易日期 | 是 | 是 | 转 `date`。 |
| `ts_code` | ETF 代码 | 是 | 是 | 字符串，必须 `.SH`。 |
| `con_code` | 成分证券代码 | 是 | 是 | 字符串。 |
| `con_name` | 成分证券名称 | 是 | 是 | 字符串。 |
| `qty` | 现金替代数量/申赎数量相关字段 | 是 | 是 | 保留源字段语义，数值化前需核文档。 |
| `sub_flag` | 现金替代标志 | 是 | 是 | 字符串。 |
| `cpr` | 源站返回字段 | 是 | 是 | 源站可能返回 `-`，V1 按字符串保留。 |
| `rdr` | 源站返回字段 | 是 | 是 | 源站可能返回 `-`，V1 按字符串保留。 |
| `sca` | 源站返回字段 | 是 | 是 | 源站可能返回 `-`，V1 按字符串保留。 |
| `exchange` | 交易所 | 是 | 是 | 字符串。 |

建议主键：

- `raw_tushare.etf_sh_cons`：`(trade_date, ts_code, con_code)`。

开发前必须用真实样本做重复键检查。如果发现同一 `trade_date + ts_code + con_code` 存在多行，必须停下来重新评审幂等键，不能临时加 hash 绕过。

## 8. DatasetDefinition 设计口径

| 事实段 | 建议 |
| --- | --- |
| `dataset_key` | `etf_sh_cons` |
| `display_name` | `ETF 申赎清单` |
| 定义文件 | 建议放在现有 ETF / 基金行情定义文件中，实施前按当前代码结构确认。 |
| `source.api_name` | `etf_sh_cons` |
| `source_fields` | `trade_date, ts_code, con_code, con_name, qty, sub_flag, cpr, rdr, sca, exchange` |
| `request_builder_key` | 新增 `_etf_sh_cons_params` |
| `date_model` | 支持 `point` 与 `range`；观测字段 `trade_date`。 |
| `input_model` | 只暴露日期输入和可选 `ts_code`；显式 `ts_code` 必须在 `etf_sh_cons` 激活池内；不暴露 `limit/offset`。 |
| `planning` | 新增 `build_etf_sh_cons_units`，按 ETF code 与自然半年窗口展开。 |
| `storage.write_path` | `raw_only_upsert` 或等价 raw-only writer 路径。 |
| `storage.target_table` | `raw_tushare.etf_sh_cons`；freshness 直接观测 raw。 |
| `storage.serving_table` | `core_serving.etf_sh_cons`；普通 view 直出 raw 字段。 |
| `observability.observed_field` | `trade_date` |
| freshness policy | 按交易日日频数据集登记。 |

## 9. Ops 与运营交互

Ops 展示口径：

- 展示分组 key：ETF 相关分组。
- 展示名称：`ETF 申赎清单`。
- 手动任务：支持单日、区间、可选单 ETF code。
- 自动任务：允许配置，但首期不进入每日收盘工作流。

错误提示建议：

- 池为空：`ETF 申赎清单激活池为空，请先配置 etf_sh_cons ETF 激活池`。
- 池内存在非 `.SH`：`etf_sh_cons 只支持上交所 ETF，请移除非 .SH 代码`。
- 显式 `ts_code` 不在池内：`该 ETF 不在 etf_sh_cons 激活池中，请先加入激活池`。
- 源站请求失败：必须带上 `ts_code` 与窗口日期，方便定位重跑范围。

## 10. 开发里程碑

| 阶段 | 目标 | 关键动作 |
| --- | --- | --- |
| M0 | 源文档补齐与消费者审计 | 已补齐 `docs/sources/tushare/ETF专题/0407_ETF申赎清单.md` 并同步索引；definitions、planner、request builder、freshness、Ops catalog 消费点已在 LLD 中列出。 |
| M1 | Schema 与 view | 已新增 `raw_tushare.etf_sh_cons` 与 `core_serving.etf_sh_cons` view；不建 serving 物理表。 |
| M2 | DatasetDefinition | 新增 `etf_sh_cons` 定义，登记 fields、date_model、storage、freshness、Ops 分组。 |
| M3 | Planner 与 request builder | 新增按 code 与自然半年窗口展开的 unit builder；新增 `_etf_sh_cons_params`。 |
| M4 | Normalizer / writer | 字段按 raw 事实保留；`cpr/rdr/sca` 不因 `-` 被 reject；按主键 upsert。 |
| M5 | Ops 可见性 | 手动任务、自动任务、数据源卡片可见；不加入每日工作流。 |
| M6 | 测试护栏 | 覆盖 `.SH` 池门禁、空池失败、非 `.SH` 失败、区间不逐日拆、单日不深分页、字段链路、raw-only view。 |
| M7 | 最小真实验收 | 用单 ETF 单日、单 ETF 半年、小池单日、小池半年验证 fetched/normalized/written/rejected/表行数一致。 |

## 11. 验收标准

完成标准：

- `ops.etf_series_active(resource='etf_sh_cons')` 是唯一 ETF code 来源。
- `.SZ` / `.OF` 配置进入该池会被测试或运行时门禁拦住。
- 单日计划中 unit 参数是 `trade_date + ts_code`。
- 区间计划中 unit 参数是 `ts_code + start_date/end_date`，窗口最多自然半年。
- 任意区间任务都不会拆成 `ETF code × 每日`。
- 任意任务都不会走单日全市场深分页。
- `raw_tushare.etf_sh_cons` 写入源站事实。
- `core_serving.etf_sh_cons` 只作为 view 读取 raw，字段完全按 raw 源站事实直出，不做派生计算。
- 最小真实同步中 `fetched = normalized + rejected`，`written` 与目标表增量可解释，任何 reject 都有明确 reason code 和样本。

## 12. 已确认补充口径

1. 显式输入 `ts_code` 也必须在 `ops.etf_series_active(resource='etf_sh_cons')` 中；不允许通过手动任务或自动任务参数绕过激活池门禁。
2. `core_serving.etf_sh_cons` view 字段完全等于 raw 字段，按源站事实直出，不做派生计算。
