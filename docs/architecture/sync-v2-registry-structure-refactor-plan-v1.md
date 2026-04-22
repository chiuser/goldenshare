# Sync V2 Registry 结构化重构方案 v1（两阶段）

- 版本：v1
- 日期：2026-04-22
- 状态：评审稿（先文档，后编码）
- 适用范围：`src/foundation/services/sync_v2/registry_parts/contracts.py` 与 `src/cli.py`

---

## 1. 背景与问题定义

当前 `sync_v2` 已完成“功能可用”但仍存在“结构不可维护”问题：

1. `registry_parts/contracts.py` 单文件约 `2237` 行，常量、参数生成、行转换、合同定义、导出函数全部耦合。
2. 合同定义重复度高（`InputSchema/PlanningSpec/NormalizationSpec/WriteSpec` 重复模板多），新增数据集改动面过大。
3. `src/cli.py` 已开始薄入口化，但仍处于“迁移中间态”，需要按模块边界彻底收敛。

本方案目标是解决“结构与维护成本”本质问题，而不是继续平移文件。

---

## 2. 目标与边界

### 2.1 目标

1. 将 registry 拆成“可定位、可并行维护”的模块结构。
2. 保持现有外部行为不变（`get_sync_v2_contract` / `list_sync_v2_contracts` / CLI 命令语义不变）。
3. 为后续数据集迁移（R2+）提供可扩展结构，避免再次变成超大文件。

### 2.2 非目标

1. 本轮不做数据集语义调整（不改业务字段、表结构、写入策略）。
2. 本轮不改 CLI 参数契约与用户命令行为。
3. 本轮不改 Alembic、DB schema、ops/biz API 契约。

---

## 3. 约束（执行时必须满足）

1. 每次只做计划内任务，不夹带计划外代码改动。
2. 先做引用审计，再拆分代码。
3. 先保证行为等价，再做去重优化。
4. `foundation` 边界不变，不引入反向依赖。
5. 每个阶段都必须有独立回滚点（可单独回退）。

---

## 4. 阶段 A：结构拆分（零行为变化）

> 目标：先把“一个大文件”拆成“按职责分层的多文件”，不改合同语义。

### 4.1 目标目录结构

```text
src/foundation/services/sync_v2/
  registry.py                         # 对外稳定入口（保持现有 API）
  registry_parts/
    __init__.py
    assemble.py                       # 合同合并与重复 key 校验
    common/
      __init__.py
      constants.py                    # enum defaults /共享常量
      row_transforms.py               # 行转换函数
      param_policies.py               # 共用参数组装函数
    contracts/
      __init__.py
      market_equity.py                # 股票日频与交易行为
      market_fund.py                  # 基金行情
      index_series.py                 # 指数序列
      board_hotspot.py                # 板块与热榜
      moneyflow.py                    # 资金流向
      reference_master.py             # 主数据与基础资料
      low_frequency.py                # 低频事件（预留）
```

当前已迁移数据集（以 `SYNC_V2_CONTRACTS` 为准，共 38 个）的分组清单如下：

1. `market_equity.py`
`daily, adj_factor, daily_basic, stk_limit, suspend_d, cyq_perf, margin, limit_list_d, limit_list_ths, limit_step, limit_cpt_list, top_list, block_trade, stock_st, stk_nineturn, broker_recommend`
2. `market_fund.py`
`fund_daily, fund_adj`
3. `index_series.py`
`index_daily, index_daily_basic, index_basic, etf_index`
4. `board_hotspot.py`
`ths_index, dc_index, dc_member, kpl_list, kpl_concept_cons`
5. `moneyflow.py`
`moneyflow, moneyflow_ths, moneyflow_dc, moneyflow_cnt_ths, moneyflow_ind_ths, moneyflow_ind_dc, moneyflow_mkt_dc`
6. `reference_master.py`
`trade_cal, hk_basic, us_basic, etf_basic`
7. `low_frequency.py`
当前无已迁入数据集；预留：`dividend, stk_holdernumber`（后续迁入时落该文件）。

说明：`index_weight` 当前未在 `SYNC_V2_CONTRACTS` 中，后续迁入时归 `index_series.py`。

### 4.2.1 待迁移数据集（18 个）归属规则（必须遵守）

以下按 `SYNC_SERVICE_REGISTRY(56)` 与 `SYNC_V2_CONTRACTS(38)` 差集审计得到的 18 个待迁移数据集，已经预先指定到目标分组文件。后续迁移必须按此归属落位，不再临时决定。

1. `market_equity.py`
`stock_basic, biying_equity_daily, stk_factor_pro, stk_period_bar_week, stk_period_bar_month, stk_period_bar_adj_week, stk_period_bar_adj_month`
2. `market_fund.py`
无待迁移项
3. `index_series.py`
`index_weekly, index_monthly, index_weight`
4. `board_hotspot.py`
`ths_member, ths_daily, ths_hot, dc_daily, dc_hot`
5. `moneyflow.py`
`biying_moneyflow`
6. `reference_master.py`
无待迁移项
7. `low_frequency.py`
`dividend, stk_holdernumber`

### 4.2.2 迁移完成后的目标全量分组（56 个）

为避免后续迁移过程分组漂移，以下给出“迁移完成态”的全量分组（已迁移+待迁移）：

1. `market_equity.py`（23）
`daily, adj_factor, daily_basic, stk_limit, suspend_d, cyq_perf, margin, limit_list_d, limit_list_ths, limit_step, limit_cpt_list, top_list, block_trade, stock_st, stk_nineturn, broker_recommend, stock_basic, biying_equity_daily, stk_factor_pro, stk_period_bar_week, stk_period_bar_month, stk_period_bar_adj_week, stk_period_bar_adj_month`
2. `market_fund.py`（2）
`fund_daily, fund_adj`
3. `index_series.py`（7）
`index_daily, index_daily_basic, index_basic, etf_index, index_weekly, index_monthly, index_weight`
4. `board_hotspot.py`（10）
`ths_index, dc_index, dc_member, kpl_list, kpl_concept_cons, ths_member, ths_daily, ths_hot, dc_daily, dc_hot`
5. `moneyflow.py`（8）
`moneyflow, moneyflow_ths, moneyflow_dc, moneyflow_cnt_ths, moneyflow_ind_ths, moneyflow_ind_dc, moneyflow_mkt_dc, biying_moneyflow`
6. `reference_master.py`（4）
`trade_cal, hk_basic, us_basic, etf_basic`
7. `low_frequency.py`（2）
`dividend, stk_holdernumber`

### 4.2 责任划分

1. `common/constants.py`
   - 只放跨合同共享常量（如 `ALL_LIMIT_LIST_TYPES`）。
2. `common/param_policies.py`
   - 只放可复用参数构造函数（例如 `trade_date`、`start/end`、`month_key`）。
3. `common/row_transforms.py`
   - 只放可复用 `row_transform`。
4. `contracts/*.py`
   - 只定义本域数据集合同字典 `CONTRACTS: dict[str, DatasetSyncContract]`。
5. `assemble.py`
   - 负责合并各域 `CONTRACTS`、检测重复 key、生成只读导出。
6. `registry.py`
   - 只保留 `list_sync_v2_contracts/has_sync_v2_contract/get_sync_v2_contract`。

### 4.3 可执行任务包（A）

#### A1. 审计与分组清单冻结

1. 生成当前数据集 key 全量清单（作为拆分基线）。
2. 给每个 key 分配域文件（`contracts/*.py`）。
3. 冻结“拆分前行为快照”：
   - `list_sync_v2_contracts()` key 集合
   - 每个合同关键字段摘要（`job_name`、`run_profiles_supported`、`target_table`）。

#### A2. 新建骨架，不搬逻辑

1. 建立 `common/`、`contracts/`、`assemble.py` 空骨架。
2. `registry.py` 暂时保持旧实现可运行。

#### A3. 先搬 common，再搬 contracts

1. 先迁常量、共用参数函数、共用行转换函数到 `common/*`。
2. 再按域迁移合同定义到 `contracts/*.py`。
3. 每迁一域即跑等价检查（见 4.5）。

#### A4. 组装器接管

1. `assemble.py` 合并所有 `CONTRACTS`。
2. 加重复键校验（重复时报错，阻止静默覆盖）。
3. `registry.py` 改为从 `assemble.py` 读取最终映射。

#### A5. 清理旧大文件

1. 删除旧的“全集合同定义文件”。
2. 保留最小兼容导出（若存在引用），并标注 deprecated。

### 4.4 行为等价检查（A）

必须全部通过：

1. `sync-v2-lint-contracts` 通过。
2. `tests/test_sync_v2_registry_routing.py` 通过。
3. `tests/test_sync_v2_validator.py`、`tests/test_sync_v2_planner.py` 通过。
4. “拆分前/后合同快照”一致（key 数、关键字段一致）。

### 4.5 回滚策略（A）

1. 若任一域迁移失败，回退该域文件迁移提交，不影响其他域。
2. 若组装器接管失败，回退 `registry.py` 到旧入口实现。
3. 回滚后必须保证 `sync-v2-lint-contracts` 恢复通过。

---

## 5. 阶段 B：模板化去重（行为等价优化）

> 目标：在阶段 A 稳定后，消除重复定义，降低后续新增数据集维护成本。

### 5.1 设计原则

1. 模板只消除重复，不改变合同语义。
2. 模板化结果必须能“展开回原始合同”以便审计。
3. 所有模板必须支持局部覆盖（避免“一刀切”损失表达力）。

### 5.2 新增模块建议

```text
src/foundation/services/sync_v2/registry_parts/
  builders/
    __init__.py
    input_schema_builders.py         # 常用输入字段组合
    planning_builders.py             # anchor/window/universe/pagination 组合
    normalization_builders.py        # date/decimal/required 组合
    write_builders.py                # raw/core/target/conflict 模板
```

### 5.3 模板对象与约束

#### ContractBlueprint（建议）

1. 目标：把重复字段块提取为可复用构建参数。
2. 约束：最终必须输出标准 `DatasetSyncContract`，不改变现有调用方。

#### 字段约束级别

1. 硬约束：`dataset_key/job_name/run_profiles_supported/source_spec/write_spec`。
2. 软约束：`display_name/observe_spec/progress_label`。
3. 可空策略：`pagination_spec` 仅在需要分页时显式设置。

### 5.4 可执行任务包（B）

#### B1. 重复块识别与模板候选清单

1. 识别高重复模式（`trade_date+start/end`、`point_or_range`、`offset_limit` 等）。
2. 给出模板候选与“暂不模板化”清单。

#### B2. 先引入 builder，不替换合同

1. 新建 `builders/*`，仅提供构建函数。
2. 单测覆盖构建函数输出。

#### B3. 分域渐进替换

1. 每次只替换一个域（如先 `market_equity`）。
2. 替换后立即跑等价快照检查。
3. 通过后再替换下一域。

#### B4. 收口与文档更新

1. 固化“新增数据集合同编写规范”（先用模板，必要时覆盖）。
2. 更新 `dataset-sync-v2` 相关实施文档入口。

### 5.5 行为等价检查（B）

1. 阶段 A 全部回归继续保持通过。
2. 新增 builder 单测通过。
3. 合同快照等价（key/关键字段一致）。
4. 典型命令冒烟：
   - `goldenshare sync-v2-lint-contracts`
   - `goldenshare sync-history -r trade_cal ...`
   - `goldenshare sync-daily -r daily ...`

### 5.6 回滚策略（B）

1. 任何域替换失败，仅回退该域到“非模板写法”。
2. builder 保留，不影响未迁域。
3. 若出现定位困难，直接回退到“阶段 A 结束点”。

---

## 6. CLI 薄入口化联动（本方案内约束）

虽然本方案主线是 registry，但需保持与 CLI 治理一致：

1. `src/cli.py` 仅负责命令声明和参数绑定。
2. 具体命令实现继续下沉到 `src/cli_parts/*`。
3. 所有 CLI 行为必须保持兼容：
   - 命令名不变
   - 参数名不变
   - 输出关键语义不变

---

## 7. 测试与门禁清单（两阶段共用）

### 7.1 必跑测试

1. `tests/test_sync_v2_validator.py`
2. `tests/test_sync_v2_planner.py`
3. `tests/test_sync_v2_registry_routing.py`
4. `tests/test_sync_v2_linter.py`
5. `tests/test_cli_sync_v2_commands.py`
6. `tests/test_cli_sync_v2_param_filtering.py`
7. `tests/test_cli_sync_daily.py`
8. `tests/architecture/test_subsystem_dependency_matrix.py`

### 7.2 必跑冒烟

1. `python3 -m src.app.web.run --help`
2. `GOLDENSHARE_ENV_FILE=.env.web.local goldenshare sync-v2-lint-contracts`

---

## 8. 里程碑与交付

### M1（阶段 A 完成）

1. registry 完成模块化拆分。
2. 行为等价与门禁通过。
3. 可删除旧“巨型合同文件”主实现。

### M2（阶段 B 完成）

1. 模板化去重完成，重复块显著下降。
2. 新增数据集合同编写路径标准化。
3. 保持全量行为兼容。

---

## 9. 评审关注点（请重点拍板）

1. 合同分域策略是否按“业务域”还是“时间语义域”优先？
2. 阶段 B 的模板化深度：  
   - 仅做输入/规划模板，还是连 `write_spec/normalization` 一并模板化？
3. 合同快照门禁是否纳入 CI（建议纳入，避免后续无意漂移）。
