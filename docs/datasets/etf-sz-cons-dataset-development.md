# ETF 每日持仓组合（深市）（`etf_sz_cons`）数据集接入方案

状态：代码已实现，待运营部署、执行迁移、初始化对象池、同步与页面验收。

审计日期：2026-08-22  
上游接口：Tushare `etf_sz_cons`，文档 0472  
源站文档：[0472 ETF每日持仓组合（深市）](/Users/congming/github/goldenshare/docs/sources/tushare/ETF专题/0472_ETF每日持仓组合(深市）.md)

> 0472 源站文档已作为本轮开发输入保存在 Goldenshare。实现前已使用项目 connector 验证小 ETF 点日期与大 ETF 月窗口的字段、分页、重复键和短页终止；不能仅凭上游文档完成接入。

## 1. 结论

审计启动时，`etf_sz_cons` 尚未进入 Goldenshare 的 DatasetDefinition、ingestion、ORM/DAO、Ops 目录或生产表。本轮代码已完成接入；生产表仍待运营部署后执行迁移创建。

它与 `etf_share_size` 的关键区别是：一个交易日全市场请求直接触及源站单页上限 3,000 条，不能把“返回 3,000 条”当成完整结果。因此，不能采用“交易日 × 全市场深分页”的主链，也不能把宽区间直接交给源站。

首期固定采用：

- 以深市 ETF 代码为对象，按 `ts_code` 拆分请求。
- 单日维护：一个 `.SZ` ETF code 一个 unit，请求 `ts_code + trade_date`。
- 区间维护：一个 `.SZ` ETF code 一个自然月窗口，请求 `ts_code + start_date + end_date`，由 source client 统一分页。
- 写入 `raw_tushare.etf_sz_cons`，`core_serving.etf_sz_cons` 使用普通 view 直出 raw。
- 使用独立的 `ops.etf_series_active(resource='etf_sz_cons')` 作为深市 ETF 对象池；只纳入 `.SZ + list_status='L'` 的 726 个代码。池为空或存在非法后缀时直接失败，不静默跳过、不回退到全市场深分页。
- 首期不加入任何既有工作流，不做专用 probe；自动任务由运营按源端发布时点自行配置。

本方案只覆盖代码设计与实现。代码部署、生产数据库迁移、后续数据同步和页面审计由运营方执行，不作为本轮代码交付的自动动作。

## 2. 审计事实

### 2.1 当前接入状态

| 检查项 | 当前结果 |
| --- | --- |
| DatasetDefinition | 已登记 `etf_sz_cons` |
| request builder | 已实现 `_etf_sz_cons_params` |
| unit planner | 已实现 `build_etf_sz_cons_units`，区间按自然月拆窗 |
| raw ORM / DAO | 已新增 `raw_tushare.etf_sz_cons` 与 `raw_etf_sz_cons` |
| Ops catalog | 已投影到 `etf_fund`，排序紧随 `etf_share_size` |
| freshness policy | 已登记 `continuous_open_day` |
| 自动任务 / 工作流 | 普通自动任务可用；不加入 workflow、不支持专用 probe |
| 本地 Goldenshare 源站文档 | 已存在本地 0472 文档 |
| 上游 Tushare 文档索引 | 有 `472, ETF每日持仓组合(深市）, etf_sz_cons` |

现有同类实现 `etf_sh_cons` 位于 `market_fund.py`，使用独立 ETF active resource、按 ETF code 拆分、raw-only upsert + view。新数据集可以复用通用结构，但不能直接复制它的 `.SH` 校验和自然半年窗口，因为深市持仓组合的单 code 数据量更大。

### 2.2 源站文档事实

上游文档说明：

- 接口：`etf_sz_cons`。
- 描述：获取深交所场内所有 ETF 每日盘前披露的一篮子组合信息。
- 单次最大 3,000 条，可根据代码或日期循环提取。
- 输入参数：`ts_code`、`trade_date`、`con_code`、`start_date`、`end_date`。
- 输出字段：`trade_date`、`ts_code`、`con_code`、`con_name`、`qty`、`sub_flag`、`cpr`、`rdr`、`sub_cc`、`red_cc`、`exchange`。

### 2.3 `tushare-data` 家族结论

该接口属于 ETF 申赎/篮子组合事实，适合做 ETF 成分和申赎现金参数的日频观察；它不是 ETF 主数据，也不是单只成分股行情。具体请求和字段以源站文档、MCP 实测和项目 connector 验证为准。

### 2.4 `tushareMcp` 实测矩阵

实测日期为 `20260731`，对象样本为 `159051.SZ`、`159919.SZ`、`159001.SZ`。

| 请求形态 | 实际参数 | 返回情况 | 结论 |
| --- | --- | --- | --- |
| 不传业务参数 | `{}` | 3,000 条；首行 `20260625`，末行 `20260626` | 命中单页上限且日期混杂，不能作为全集 |
| 只传对象 | `ts_code=159919.SZ` | 3,000 条，日期跨 `20260615~20260626` | 对象历史宽结果触及上限，不能直接作为完整历史 |
| 只传时间点 | `trade_date=20260731` | 3,000 条，均为 `20260731` | 全市场单页触顶，不能作为完整日期结果 |
| 时间区间 + 对象 | `ts_code=159919.SZ, start_date=20260701, end_date=20260731` | 3,000 条，触及上限 | 区间必须拆短窗口并依赖项目 connector 分页 |
| 对象 + 时间点 | `ts_code=159051.SZ, trade_date=20260731` | 100 条 | 单 code 单日可控 |
| 对象 + 时间点 | `ts_code=159919.SZ, trade_date=20260731` | 301 条 | 单 code 单日返回量随 ETF 变化，但远低于 3,000 |
| 对象 + 时间点 | `ts_code=159001.SZ, trade_date=20260731` | 1 条 | 现金类 ETF 也应保留其源站行 |
| 成分对象 + 时间点 | `con_code=000001.SZ, trade_date=20260731` | 73 条，跨多个 ETF | `con_code` 只是查询过滤，不适合作为默认维护对象 |
| 显式字段 | 11 个文档字段全部请求 | 三个单 code 样本均返回字段，部分数值字段可为 `null` | 11 个字段全部进入 `source_fields`，不得因 null 丢列 |
| 分页 | MCP 工具未暴露 `limit/offset`；项目 connector 使用 `limit=100` | `159919.SZ + 20260731` 从 offset 0 到 300 共 4 页，合计 301 条，末页 1 条；`(trade_date,ts_code,con_code)` 无重复 | connector 分页、短页终止和业务键合并已完成开发前代表性验证；仍需在实现后用真实 Definition 和大样本 ETF 再跑一次 |

补充对象范围实测：`etf_basic(exchange='SZ')` 返回 788 条，其中 `.SZ` 786 条、`.OF` 2 条；进一步按 `list_status='L'` 查询返回 727 条，其中 `.SZ` 726 条、`.OF` 1 条（`158008.OF`）。因此，若采用严格 `.SZ + list_status='L'`，初始候选是 726 个代码，而不是 727 个。其余 `.SZ` 状态为 `P=14`、`D=46`。这组数据用于估算对象池规模，不代表已经拍板对象池生命周期口径。

## 3. 三层语义拆分

| 语义层 | 本方案口径 | 核验依据 |
| --- | --- | --- |
| 时间输入语义 | 运营提交一个交易日或一个日期区间；日期代表要获取的持仓组合业务日期 | 源文档参数；MCP 单 code 点/区间请求 |
| 执行 / unit 语义 | 单日：一个 ETF code 一个 unit；区间：一个 ETF code 一个自然月窗口 unit；窗口内分页拉完后一个事务提交 | 全市场点查询触及 3,000；单 code 点查询 100~301 |
| freshness / audit 语义 | V1 只接 freshness，不做日期 × ETF 完整性审计；是否应有行由独立 ETF 对象池和源站返回共同决定 | 当前没有稳定的深市 ETF 历史 subject/lifecycle 审计模型 |

`bucket_rule` 建议为 `every_open_day`，`date_axis` 为 `trade_open_day`，`input_shape` 为 `trade_date_or_start_end`。`audit_applicable=false` 不代表不支持日期输入，而是本期不把缺少某个 ETF 的某一天自动判为数据缺口。

## 4. 推荐的 DatasetDefinition

### 4.1 基本事实

| 字段 | 建议值 |
| --- | --- |
| `dataset_key` | `etf_sz_cons` |
| `display_name` | `ETF 每日持仓组合（深市）` |
| `domain` | `index_fund / 指数 / ETF`，与 `etf_sh_cons` 同组 |
| `source.api_name` | `etf_sz_cons` |
| `source_doc_id` | `tushare.etf_sz_cons` |
| `request_builder_key` | 新增 `_etf_sz_cons_params` |
| `planning.unit_builder_key` | 新增 `build_etf_sz_cons_units` |
| `planning.universe_policy` | `pool` |
| `universe source` | `ops_etf_series_active`, resource=`etf_sz_cons` |
| `planning.pagination_policy` | `offset_limit` |
| `planning.page_limit` | `3000` |

### 4.2 对象池门禁

必须建立独立资源：`ops.etf_series_active(resource='etf_sz_cons')`。

- 只允许 `.SZ` ETF 代码。
- 池为空直接失败，提示先配置深市 ETF 对象池。
- 池内出现 `.SH`、`.OF` 或其他后缀直接失败；不得静默跳过。
- 显式 `ts_code` 必须是单个 `.SZ` 且存在于该资源池。
- 不使用 `con_code` 作为默认对象池，也不接受逗号拼接多 ETF 代码。
- 不允许 planner 在池为空时调用 `etf_sz_cons` 或 `etf_basic` 做隐藏 fallback。

对象池口径已确认：当前 `etf_basic(exchange='SZ')` 实测有 786 个 `.SZ` 代码，其中 L=726、P=14、D=46。`exchange='SZ'` 不是 `.SZ` 后缀门禁，当前列表还包含 `.OF`；因此实现必须先按 `ts_code` 后缀过滤 `.SZ`，再只保留 `list_status='L'`，最终对象池固定为 726 个代码。不纳入 P/D。

### 4.3 输入字段

建议只暴露：

- 时间：`trade_date` 或 `start_date/end_date`。
- 可选修复过滤：单个 `ts_code`。

不暴露：

- `con_code`：它会让用户只拉某个成分，容易生成不完整 ETF 组合。
- `limit/offset`：由 source client 统一控制。

## 5. 请求与性能设计

### 5.1 单日维护

默认输入：`trade_date=YYYY-MM-DD`。

执行：

1. 读取 `ops.etf_series_active(resource='etf_sz_cons')`。
2. 校验池非空、全部 `.SZ`。
3. 每个 ETF code 生成一个 unit。
4. request builder 生成 `ts_code=<code>, trade_date=YYYYMMDD`。
5. source client 追加 `limit=3000, offset=...`，分页至短页结束。
6. 一个 code 的所有分页拉完、normalize 完成后，提交这个 unit。

按当前对象规模估算：

- `.SZ + list_status='L'` 固定为 726 个 code，单日约 726 个首次请求；
- 当前 Tushare 共享限速为 500 次/分钟，理论请求下限约 1.5 分钟，实际还要加网络和分页耗时。

### 5.2 区间维护

默认将输入区间拆成自然月窗口：

- `2026-01-01 ~ 2026-01-31`
- `2026-02-01 ~ 2026-02-28`
- 依此类推，边界按用户输入裁剪。

每个 `ETF code + 月窗口` 是一个 unit，请求 `ts_code + start_date + end_date`，由 source client 分页。选择月窗口而不是半年窗口的原因是：样本 `159919.SZ` 单日 301 行，半年宽区间很容易产生深分页；月窗口将单事务行数和分页深度控制在可复核范围内。

用户提交的 `start_date/end_date` 不设置总跨度上限；无论区间跨多少年，planner 都按自然月连续拆分为多个 unit。约束只作用于单个月窗口，不通过限制用户输入区间来控制任务规模。

请求量估算：

| 场景 | `.SZ + L` 726 code |
| --- | ---: | ---: |
| 单日 | 726 units |
| 1 年区间（月窗口） | 8,724 units |
| 3 年区间（月窗口） | 26,172 units |

以上是 unit 数，不是最终 HTTP 请求数；每个 unit 可能有多个分页。正式实现前必须用项目 connector 对代表性大 ETF 做月窗口行数、页数、耗时和事务大小测量。若单月仍频繁超过 3,000 行，应把窗口进一步缩短为半月，而不是恢复全市场深分页。

### 5.3 禁止的请求策略

- 禁止不传参数作为全量下载。
- 禁止只传 `trade_date` 后将 3,000 条当成完整日数据。
- 禁止把区间拆成 ETF code × 每个交易日，除非真实 connector 证明月窗口无法稳定工作并重新评审请求量。
- 禁止用 `con_code` 查询结果拼装 ETF 全量组合。
- 禁止在 planner 阶段调用外部 Tushare 补对象池。

## 6. 存储与字段设计

### 6.1 存储口径

首期建议：`raw_only_upsert + serving view`。

- raw 表：`raw_tushare.etf_sz_cons`。
- 对外 view：`core_serving.etf_sz_cons`。
- 不创建 serving 物理表，不做双写。

### 6.2 字段端到端对账表

| 源字段 | 文档 | MCP 真实返回 | raw ORM/迁移 | view | 建议类型 | 主键/必填 |
| --- | --- | --- | --- | --- | --- | --- |
| `trade_date` | 是 | 是 | `DATE` | 是 | 日期 | 必填；主键 |
| `ts_code` | 是 | 是 | `VARCHAR(16)` | 是 | 字符串 | 必填；主键 |
| `con_code` | 是 | 是 | `VARCHAR(16)` | 是 | 字符串 | 必填；主键 |
| `con_name` | 是 | 是 | `VARCHAR(128)` | 是 | 字符串 | 可空 |
| `qty` | 是 | 是 | `NUMERIC(24,6)` 或整数数值 | 是 | 数值 | 可空/按源样本核定 |
| `sub_flag` | 是 | 是 | `VARCHAR(16)` | 是 | 字符串 | 可空 |
| `cpr` | 是 | 是 | `NUMERIC(20,8)` | 是 | 数值 | 可空 |
| `rdr` | 是 | 是 | `NUMERIC(20,8)` | 是 | 数值 | 可空 |
| `sub_cc` | 是 | 是 | `NUMERIC(24,8)` | 是 | 数值 | 可空 |
| `red_cc` | 是 | 是 | `NUMERIC(24,8)` | 是 | 数值 | 可空 |
| `exchange` | 是 | 是 | `VARCHAR(16)` | 是 | 字符串 | 可空 |

建议主键：`(trade_date, ts_code, con_code)`。`exchange` 是成分证券交易所，不是 ETF 对象池市场，不能替代主键字段。实施前必须用项目 connector 对同一 ETF/日期做重复键检查；如存在同键多行，先停下来重新设计幂等键。

Goldenshare 内部字段 `api_name`、`fetched_at`、`raw_payload` 按现有 raw 表规范处理，不属于 `source_fields`。

## 7. DatasetDefinition、Ingestion 与 Ops 影响面

预计新增或修改：

- `src/foundation/datasets/definitions/market_fund.py`
- `src/foundation/ingestion/unit_planner.py`
- `src/foundation/ingestion/request_builders.py`
- `src/foundation/ingestion/row_transforms.py`
- raw ORM、DAO factory、model registry、Alembic migration
- `src/foundation/datasets/freshness_policies.py`
- `src/ops/services/etf_series_active_seed_service.py` 的 resource 白名单
- `src/ops/catalog/dataset_catalog_views.py`
- Definition、planner、request、normalizer、writer、model、catalog 和 active pool 测试

不改：

- `etf_sh_cons` 已有 `.SH` 门禁、半年窗口和生产数据。
- `etf_share_size` 的无池、按交易日全市场策略。
- `daily_market_close_maintenance` 现有步骤。
- foundation 到 ops 的依赖方向。

每个 unit 内所有分页完成后再 normalize/write/commit；状态和业务事务隔离。不能因为对象池或 TaskRun 状态写失败而回滚业务数据。

## 8. Freshness、自动任务与工作流

- Ops 展示分组：`etf_fund`，名称为“ETF 每日持仓组合（深市）”。
- 手动任务：支持 point/range，可选单个 ETF code。
- 自动任务：支持普通 schedule；单日任务应安排在深交所盘前组合发布完成后。V1 不新增 probe。
- freshness：建议 `continuous_open_day`，观测字段为 `trade_date`；V1 不做日期 × ETF 完整性审计。
- 工作流：首期不加入任何既有工作流；后续是否加入另行评估，不属于本期开发范围。

## 9. 开发里程碑

| 阶段 | 目标 | 关键动作 |
| --- | --- | --- |
| M0 | 源文档与 connector 门禁 | 已完成。使用本地 0472 文档，实施前确认迁移 head；项目 connector 已验证小 ETF 点日期与大 ETF 月窗口分页、字段、重复键和短页终止 |
| M1 | 对象池口径 | 已完成。`etf_sz_cons` resource 和 `.SZ` 后缀、空池、显式 code 门禁已落地；不做源站 fallback |
| M2 | Schema 与 view | 已完成。新增 raw ORM、DAO、迁移和 `core_serving.etf_sz_cons` view；不建 serving 物理表 |
| M3 | Definition 与 planner | 已完成。point 单 code 和 range 自然月窗口已落地；request builder 只生成源接口日期和 code 参数 |
| M4 | Normalizer / writer | 已完成。11 个源字段落 raw，数值/日期清洗，按 `(trade_date, ts_code, con_code)` 幂等 upsert |
| M5 | Ops 与 freshness | 已完成。ETF 分类目录、手动/普通自动任务能力、freshness 已登记；不加入既有工作流 |
| M6 | 本地测试与交接 | 已完成。代表小/大 ETF 的 connector 验证和定向测试通过；生产数据写入仍由运营方验收 |
| M7 | 运营方部署与验收 | 待运营方自行部署、迁移、初始化对象池、同步数据和验收页面；本轮不代执行这些动作 |
| M8 | 文档收口 | 已完成。开发文档与 LLD 已按实际代码和验证口径收口 |

## 10. 已确认口径

1. **深市对象池生命周期**：建立 `resource='etf_sz_cons'`，只放 `list_status='L'` 的 `.SZ` 代码，当前实测 726 个；不放 P/D，不做无池全市场分页。
2. **采用 raw-only + view**：该接口是源站明细事实，view 直出可以避免第二份物理存储。
3. **首期不加入任何工作流**：日请求量约 726 个，且源站是盘前披露，由运营配置普通自动任务。
4. **首期不做专用 probe**：不新增探测运行时契约。
5. **部署后的同步与回补由运营方负责**：本方案不设计单独回补流程，也不代执行部署、迁移或生产同步。

## 11. 验收标准

- 默认单日不会走全市场 3,000 条截断结果，而是对对象池中每个 `.SZ` ETF 逐 code 请求。
- 区间不会拆成 ETF code × 每个交易日；默认按自然月窗口，分页完整拉完后提交单个 unit。
- 池为空、存在非 `.SZ`、显式 code 不在池内均明确失败，不静默跳过、不 fallback。
- 11 个源字段全部进入 `source_fields`、raw ORM、迁移和 serving view；空值不丢列。
- raw 表与 view 字段一致，serving 不另建物理表。
- `fetched = normalized + rejected`，目标表唯一键增量可解释；任何 reject 都有 reason code 和样本。
- Ops/TaskRun/freshness 状态写入不影响业务数据提交。
