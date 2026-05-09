# Local Lake 数据集接入模式分类与 Checklist v1

- 版本：v1
- 状态：现行
- 更新时间：2026-05-09
- 适用范围：`lake_console` 本地数据湖的数据集接入评审、方案设计与实现前检查
- 相关文档：
  - [Local Lake 数据集同步扩展方案 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-dataset-sync-expansion-plan-v1.md)
  - [Local Lake CLI / Planner / Engine 架构收口方案 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-cli-planner-engine-refactor-plan-v1.md)
  - [Local Lake 数据集接入说明模板](/Users/congming/github/goldenshare/docs/templates/lake-dataset-development-template.md)
  - [Local Lake prod-raw-db 导出接入规则与 Checklist](/Users/congming/github/goldenshare/docs/templates/lake-prod-raw-db-export-template.md)

---

## 1. 文档目的

这份文档只解决一个问题：

```text
一个数据集在接入 Local Lake 时，应该走哪一种读取模式。
```

当前 Lake 已经不是单一路线：

1. 有些数据集直接访问 Tushare。
2. 有些数据集从远程 `raw_tushare.*` 导出。
3. 有些数据集从远程 `core/core_serving` 导出。
4. 极少数数据集同时保留双模式。

因此，后续评审时不能只问“有没有接到 Lake”，还必须先问：

```text
它是怎么接的。
```

---

## 2. 当前事实快照（2026-05-09）

基于当前代码真实统计：

1. 生产侧总数据集：`66`
2. 其中 Tushare：`64`
3. 其中 BIYING：`2`
4. Lake 当前已接入数据集：`48`
5. Lake 已接入的 `48` 个全部落在 Tushare 主线
6. 当前 Tushare 剩余未接入 Lake：`16`

当前覆盖率：

```text
48 / 64 = 75%
```

说明：

1. 以上口径是按当前代码事实统计，不按文档印象统计。
2. “已接入”指 `lake_console` 已有 dataset catalog + planner/strategy/CLI 支持。
3. “未接入”只表示当前还没进入 Lake，不代表已经定好后续读取模式。

---

## 3. 当前 Lake 真实读取模式分类

### 3.1 仅 Tushare 直连

共 `4` 个：

- `stock_basic`
- `trade_cal`
- `index_basic`
- `stk_mins`

适用特征：

1. 本地需要直接维护 manifest / universe。
2. 远程生产 raw 表当前不作为 Lake 主事实来源。
3. 数据集本身存在专项下载/存储方案，如分钟线。

---

### 3.2 双模式：Tushare + prod-raw-db

共 `1` 个：

- `daily`

说明：

1. `daily` 当前同时支持：
   - `--from tushare`
   - `--from prod-raw-db`
2. 这是当前 Lake 唯一已经正式打通的双模式数据集。
3. 双模式不是默认口径，后续不得随意复制到其他数据集。

---

### 3.3 仅 prod-raw-db

共 `40` 个。

#### 3.3.1 current_file / snapshot 类

- `etf_basic`
- `etf_index`
- `ths_index`
- `ths_member`

#### 3.3.2 trade_date 分区类

- `adj_factor`
- `daily_basic`
- `margin`
- `stk_limit`
- `stock_st`
- `suspend_d`
- `fund_daily`
- `fund_adj`
- `index_daily_basic`
- `moneyflow`
- `moneyflow_ths`
- `moneyflow_dc`
- `moneyflow_cnt_ths`
- `moneyflow_ind_ths`
- `moneyflow_ind_dc`
- `moneyflow_mkt_dc`
- `cyq_perf`
- `dc_daily`
- `dc_member`
- `dc_index`
- `ths_daily`
- `dc_hot`
- `ths_hot`
- `kpl_list`
- `kpl_concept_cons`
- `limit_list_d`
- `limit_list_ths`
- `limit_step`
- `limit_cpt_list`
- `top_list`
- `stk_period_bar_week`
- `stk_period_bar_month`
- `stk_period_bar_adj_week`
- `stk_period_bar_adj_month`
- `stk_factor_pro`
- `stk_nineturn`

说明：

1. 这是当前 Lake 的主路线。
2. 默认优先复用远程生产 `raw_tushare.*` 已经落好的源站事实。
3. 这条路线要求：
   - 只读
   - 只允许白名单表
   - 只允许字段白名单投影
   - 禁止 `select *`
4. 但“默认优先 raw”不是绝对规则；若 serving/core 明显承载了更完整、更可靠的事实，允许经审计后选择 `prod-core-db`。

---

### 3.4 仅 prod-core-db

共 `3` 个：

- `index_daily`
- `index_weekly`
- `index_monthly`

说明：

1. `index_daily`、`index_weekly`、`index_monthly` 是当前正式批准的 `prod-core-db` 例外。
2. 它们不走 `prod-raw-db`。
3. 即使从 `core/core_serving` 读取，Lake 对外字段仍必须回到源站字段口径。

---

## 4. 还未接入 Lake 的 16 个数据集

当前未接入的 Tushare 数据集如下：

- `bak_basic`
- `block_trade`
- `broker_recommend`
- `bse_mapping`
- `cctv_news`
- `dividend`
- `hk_basic`
- `index_mins`
- `index_weight`
- `major_news`
- `namechange`
- `news`
- `st`
- `stk_holdernumber`
- `stock_company`
- `us_basic`

注意：

1. 这 `16` 个当前还不能按“主路线”直接拍脑袋分配模式。
2. 必须逐个审计后，才能决定它们应该走：
   - `tushare`
   - `prod-raw-db`
   - `prod-core-db`
   - 或者保留后置专项

禁止做法：

```text
因为现在大多数走 prod-raw-db，就默认剩余 16 个也走 prod-raw-db。
```

---

## 5. 新数据集接入时的模式判定 Checklist

后续每个未接入数据集，在出方案前都必须先完成下面这份判定。

### Step 1. 先确认是否存在可用的远程事实表

先定一条总原则：

```text
模式判定标准不是“谁更像源站”，而是“谁是当前最佳事实源”。
```

也就是说：

1. 如果 `raw_tushare.*` 已经完整、可信、没有额外修复需求，优先走 `prod-raw-db`。
2. 如果 `core/core_serving.*` 明确承载了更高质量的修复结果，且这些修复正是 Lake 需要保留的业务事实，则允许选择 `prod-core-db`。

必须逐项确认：

1. 远程生产是否已有对应业务表。
2. 表位于：
   - `raw_tushare.*`
   - 还是 `core/core_serving.*`
3. 表是否已经包含 Lake 需要的业务字段。
4. 表的历史范围是否可信。
5. 是否存在明显缺日、断档、非交易日污染、精确重复。

结论要求：

- 没确认远程真实表，不能直接判 `prod-raw-db` / `prod-core-db`。

---

### Step 2. 再确认字段事实源

必须逐项确认：

1. Tushare 源接口输出字段。
2. 生产 `DatasetDefinition.source_fields`。
3. 远程真实表业务字段。
4. 远程真实表系统字段。

必须明确：

1. 哪些字段是源站事实字段。
2. 哪些字段是 Goldenshare 系统字段，必须排除：
   - raw 常见：`api_name`、`fetched_at`、`raw_payload`
   - core 常见：`source`、`created_at`、`updated_at`
3. 是否存在“请求派生但必须升格为事实字段”的维度。
   - 例如：
     - `dc_hot.market`
     - `dc_hot.hot_type`
     - `dc_hot.is_new`
     - `ths_hot.market`
     - `ths_hot.is_new`

---

### Step 3. 判断是否必须保留 Tushare 直连

只有满足下面任一情况，才优先判定为 `tushare`：

1. 远程生产事实表尚未形成稳定事实源。
2. 本地 Lake 需要直接维护 manifest / universe，远程表不适合承担该角色。
3. 数据集存在专项下载/落盘方案，当前不能被远程导出链替代。
4. 远程表字段口径与 Lake 目标事实明显不一致，且短期内不适合通过导出做映射。

当前现实案例：

- `stock_basic`
- `trade_cal`
- `index_basic`
- `stk_mins`

---

### Step 4. 判断是否应走 prod-raw-db

优先判定为 `prod-raw-db` 的条件：

1. `raw_tushare.*` 里已经有稳定、可审计的事实表。
2. 远程 raw 表字段足够表达 Lake 所需事实。
3. 远程 raw 表的时间范围和数据质量可接受。
4. 导出时可以用字段白名单投影，避免带入系统字段。
5. 不需要依赖生产运行时状态写入或生产服务对象。

这是当前 Local Lake 的默认主路线。

---

### Step 5. 判断是否应走 prod-core-db

只有在下列情况同时成立时，才允许判为 `prod-core-db`：

1. 业务上明确要求使用 core 层事实，而不是 raw 层。
2. core 表的字段可以明确映射回源站字段口径。
3. 不会把 core 内部字段名、系统字段直接泄露到 Lake。
4. 已有明确专项评审，不是临时方便。

当前现实案例：

- `index_daily`

禁止做法：

```text
只因为 core 表查起来方便，就直接把数据集改走 prod-core-db。
```

---

### Step 6. 判断是否真的需要双模式

双模式不是默认能力，必须额外证明：

1. 两条链路都有长期价值。
2. 两条链路导出的事实字段口径一致。
3. 两条链路都能维持测试与命令面。
4. 不会因为双模式把实现复杂度和维护成本推高到失控。

当前现实案例：

- `daily`

如果没有明确理由，默认不要做双模式。

---

## 6. 进入实现前的强制检查项

在模式确定之后，进入实现前还必须完成：

1. 命令面确认：
   - 支持 `--trade-date`
   - 或支持 `--start-date --end-date`
   - 或 `current_file` / `snapshot` 单次全量
2. 写入布局确认：
   - `current_file`
   - `trade_date` 分区
   - 或专项布局
3. 正式分区规则确认：
   - `trade_open_day` 数据集必须按本地交易日历白名单生成正式分区
4. 查询上下文字段确认：
   - 是噪音字段要排除
   - 还是必须升格为事实字段
5. 最小真实同步验证：
   - 源端行数
   - 归一化行数
   - 写入行数
   - 目标 Parquet schema
   - 拒绝原因

---

## 7. 后续使用方式

后续每推进一个新批次，先做下面两件事：

1. 先用本 checklist 给候选数据集分“潜在模式”
2. 再进入对应专项方案文档

推荐顺序：

```text
模式先判定
事实再审计
方案再落文档
代码最后实现
```

不要倒过来。

---

## 8. 一句话口径

当前 Local Lake 不是“全都走一种下载方式”，而是：

```text
少量 Tushare 直连
极少量双模式
绝大多数 prod-raw-db
个别 prod-core-db 例外
```

后续任何新数据集接入前，都必须先回答：

```text
它该走哪一种模式，依据是什么。
```
