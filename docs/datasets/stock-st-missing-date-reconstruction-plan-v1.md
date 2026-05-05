# ST 股票列表历史缺失日期重建方案 v1（待评审）

## 0. 问题定义

`stock_st` 的日期完整性审计已经识别出一批历史缺失交易日。  
这些日期在当前 `core_serving.equity_stock_st` / `raw_tushare.stock_st` 中整日缺失，而用户已确认源站 `stock_st` 接口在这些日期也拿不到日快照，因此常规 `stock_st.maintain` 无法把数据补回来。

这次要解决的问题不是“重新跑一次同步”，而是：

1. 基于辅助事实源，重建指定缺失交易日的 ST 成员快照。
2. 让补出的数据有清晰证据链，后续可审查、可解释。
3. 不把一次性历史修复硬塞进 `stock_st` 日常维护主链。

---

## 1. 当前事实

### 1.1 `stock_st` 当前主链事实

- `DatasetDefinition`：
  - 数据集：`stock_st`
  - 中文名：`ST股票列表`
  - 日期模型：`trade_open_day / every_open_day`
  - 输入：`trade_date` 或 `start_date + end_date`
  - 写入：`raw_tushare.stock_st -> core_serving.equity_stock_st`
- 当前 Definition 位置：
  - [market_equity.py](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/market_equity.py)
- 当前请求参数 builder：
  - [request_builders.py](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)

### 1.2 当前表结构事实

- Raw 表：[raw_stock_st.py](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_stock_st.py)
  - 主键：`(ts_code, trade_date, type)`
  - 字段：`ts_code, trade_date, type, name, type_name, api_name, fetched_at, raw_payload`
- Serving 表：[equity_stock_st.py](/Users/congming/github/goldenshare/src/foundation/models/core/equity_stock_st.py)
  - 主键：`(ts_code, trade_date, type)`
  - 字段：`ts_code, trade_date, type, name, type_name`

### 1.3 已确认的数据事实

远端现状已经核对过：

1. `core_serving.equity_stock_st` 当前最早日期是 `2016-08-09`，最晚日期是 `2026-04-30`。
2. 当前 `type / type_name` 只有一组值：`ST / 风险警示板`。
3. 本批审计识别出 `25` 个缺失交易日，其中有一段连续两天缺失：`2020-08-03 ~ 2020-08-04`。
4. 这些缺失日相邻快照并不总是完全相同：
   - 有些日期前后 ST 数量一致，例如 `2016-08-10`：`72 -> 72`
   - 有些日期前后数量发生变化，例如 `2019-04-01`：`91 -> 89`
5. 因此前后复制不是可靠方案，必须识别缺失日当天的成员进入/退出边界。

### 1.4 当前已知缺失日期

```text
2016-08-10
2016-08-19
2016-09-22
2016-10-10
2016-12-05
2017-01-17
2017-06-23
2019-04-01
2019-10-24
2019-11-04
2019-11-28
2020-01-02
2020-02-20
2020-02-25
2020-03-16
2020-04-23
2020-06-18
2020-07-08
2020-07-20
2020-08-03
2020-08-04
2020-08-24
2020-11-20
2021-01-29
2021-03-16
```

### 1.5 辅助事实源前提

仓内已经有对应源文档与数据集方案：

- 源文档：
  - [0100_股票曾用名.md](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/基础数据/0100_股票曾用名.md)
  - [0423_ST风险警示板股票.md](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/基础数据/0423_ST风险警示板股票.md)
- 开发文档：
  - [namechange-dataset-development.md](/Users/congming/github/goldenshare/docs/datasets/namechange-dataset-development.md)
  - `st` 当前以后续正式数据集接入方案为准，本方案暂直接引用源站事实文档

结合当前决策，本方案后续实现默认以前置集成完成为条件，直接消费数据库中的辅助事实表，而不是在修复工具里再直连 Tushare：

1. `raw_tushare.namechange`
2. `raw_tushare.st`
3. 如后续有 `core_serving_light.namechange / st` 只作为查询便利层，不作为唯一事实源

结论：

1. `stock_st` 修复工具启动前，必须先完成 `namechange` 与 `st` 的数据落库。
2. 如果辅助事实表不存在，修复命令必须直接失败，不做网络回退，不做临时直连。

---

## 2. 方案边界

### 2.1 本次要做

1. 为 `stock_st` 提供一个专门的历史缺失日期重建工具。
2. 用 `namechange` 和 `st` 两个 Tushare 接口做证据链推断。
3. 支持预览、人工审查、再落库。
4. 仅覆盖“整日缺失”的历史补数。

### 2.2 本次不做

1. 不修改 `stock_st` 的 `DatasetDefinition.date_model`。
2. 不改 `stock_st.maintain` 正常维护主链。
3. 不先实现 `namechange` / `st` 正式数据集接入。
4. 不给 Ops / TaskRun 新增一个长期用户入口。
5. 不处理“某天存在部分行、但成员不完整”的部分缺失问题。

---

## 3. 关键判断

### 3.1 为什么不能只复制前一天

因为缺失日相邻快照并不总是相同。  
例如：

- `2019-04-01`：前一日 `91` 条，后一日 `89` 条
- `2020-01-02`：前一日 `138` 条，后一日 `137` 条
- `2021-03-16`：前一日 `215` 条，后一日 `214` 条

如果直接复制前一天，会把本该在缺失日退出的 ST 成员保留下来。

### 3.2 为什么 `namechange` 作为主事实，`st` 作为辅助事实

`stock_st` 最终只需要回答一件事：

`某只股票在某个交易日是否属于 ST 成员`

对这个问题：

1. `namechange` 更像“区间事实”
   - 它能表达某个名字从哪天开始、到哪天结束
   - 适合判断某日是否处于 `ST/*ST/SST/S*ST` 名称区间
2. `st` 更像“事件事实”
   - 它记录的是某次风险警示事件的发布日期、实施日期、类型、原因
   - 适合发现缺失窗口内发生的进入/退出边界

更重要的是，`st` 不能直接粗暴映射成“撤销=退出成员”。  
源文档样例里已经出现：

- `撤销叠加*ST`

这种事件说明某个叠加状态被撤销，但股票仍然可能保留 ST / *ST 身份。  
所以：

1. `namechange` 负责判断“这天是不是 ST 成员”
2. `st` 负责发现边界日期、补充解释、拦出冲突

### 3.3 为什么修复工具不直接连 Tushare

现在已经明确：

1. `namechange` 和 `st` 会作为正式数据表落库
2. 我们希望修复工具消费仓内单一事实源，而不是再开一条绕过数据库的临时抓取路径

所以本方案改为：

1. `stock_st` 修复工具只读库内辅助事实
2. 不直接调用 Tushare connector
3. 不允许“表没准备好就临时联网补救”

这样可以避免：

1. 同一个事实同时从 DB 和源接口两边读取
2. 线上重跑时受到 Tushare 限速、接口波动、令牌环境的额外影响
3. 未来排查时搞不清修复结果到底依据哪一份事实

---

## 4. 重建总体方案

### 4.1 实现形态

本次不放进日常 ingestion 主链，单独做成低频修复工具，且明确“实现目录”和“CLI 入口”分离。

建议结构：

1. 实现目录：
   - `src/foundation/services/migration/stock_st_missing_date_repair/`
2. CLI handler：
   - `src/cli_parts/stock_st_missing_date_repair_handlers.py`
3. CLI 注册：
   - `src/cli.py`

建议包内文件：

1. `models.py`
   - 预览结果、候选池、审查项、落库行模型
2. `candidate_loader.py`
   - 从 `stock_st / st` 装载候选代码池
3. `membership_resolver.py`
   - 用 `namechange` 判定某日是否属于 ST 成员
4. `evidence_resolver.py`
   - 汇总 `st` 事件证据、生成冲突说明
5. `writer.py`
   - 负责 preview 文件输出与 apply 落库
6. `service.py`
   - 编排整个修复流程

这样可以保持：

1. `stock_st.maintain` 仍然只负责正常拉 `stock_st` 源快照
2. 历史重建逻辑不污染长期维护主链
3. 工具实现和 CLI 入口解耦，后续也方便补测试

### 4.2 执行模式

工具必须有两个模式：

1. `preview`
   - 只生成重建结果与差异报告
   - 不写库
2. `apply`
   - 只对明确缺失、且通过校验的日期落库

### 4.3 CLI 命令设计

建议命令名：

```bash
goldenshare repair-stock-st-missing-dates
```

建议参数：

1. `--date YYYY-MM-DD`
   - 可重复，显式指定要修复的缺失日期
2. `--date-file <path>`
   - 一行一个日期，适合从审计结果导入
3. `--output-dir <path>`
   - 预览 CSV 输出目录
4. `--apply`
   - 不传时默认 preview
5. `--fail-on-review-items`
   - 若存在人工审查项则拒绝 apply

默认行为：

1. 不传 `--apply` 时，只做 preview
2. `apply` 前必须先通过 preview 校验
3. 同时传 `--date` 和 `--date-file` 时，合并后去重

### 4.4 输入来源

输入不是开放式日期区间，而是显式缺失日期清单：

1. 直接传入日期列表
2. 或从 `stock_st` 的审计 gap 结果导入日期列表

V1 建议只支持显式日期清单，避免工具被误用成“全历史 ST 生成器”。

---

## 5. 候选代码发现策略

### 5.1 本地库相邻快照候选池

先从现有 `stock_st` 表得到每个缺失日的：

1. 最近前一个有效交易日快照
2. 最近后一个有效交易日快照

当前这批缺失日期的相邻快照代码并集约为：

- `342` 个唯一 `ts_code`

这是第一个候选池。

### 5.2 用库内 `st` 的 `imp_date` 补齐“只存在于缺失窗口”的代码

只靠相邻快照还不够。  
例如 `2020-08-03 ~ 2020-08-04` 这种连续两天缺失，可能存在：

1. 某只股票 `08-03` 进入 ST
2. `08-04` 又退出
3. 因为前后快照都没出现，所以相邻快照并集抓不到它

因此第二个候选发现动作是：

1. 对每个缺失日期，从 `st` 表中过滤 `imp_date=缺失日期` 的事件
2. 把这些事件里的 `ts_code` 加入候选池

V1 只需要做 `imp_date=exact day` 查询，不做全市场大区间扫描。

### 5.3 最终候选池

对某个缺失日期 `D`，最终候选池是：

1. `prev_snapshot(D)` 的全部 `ts_code`
2. `next_snapshot(D)` 的全部 `ts_code`
3. `st(imp_date=D)` 返回的全部 `ts_code`

---

## 6. 名称归一化与 ST 识别规则

### 6.1 不能直接用简单前缀

当前真实 `stock_st.name` 里除了：

- `ST`
- `*ST`
- `SST`
- `S*ST`

还出现过：

- `XDST...`
- `XR*ST...`
- `DR*ST...`
- `NST...`

这些前缀不是正式曾用名本身，而是日级展示前缀与 ST 名称叠加后的结果。

### 6.2 V1 归一化规则

对用于“是否属于 ST 成员”的名字识别，采用如下规则：

1. 先去空白
2. 循环剥离前置展示前缀：`XR` / `XD` / `DR`
3. 若剩余字符串以 `NST` 开头，按 `N + ST` 处理
4. 最终按以下前缀识别为 ST-like：
   - `S*ST`
   - `SST`
   - `*ST`
   - `ST`

可表达为：

```text
^(?:XR|XD|DR)*(?:N)?(?:S\*ST|SST|\*ST|ST)
```

### 6.3 这批缺失日的额外事实

已核对这批缺失日相邻快照的真实名字，当前没有发现：

- `XD*`
- `XR*`
- `DR*`
- `NST`

出现在相邻日期的候选快照中。

这说明：

1. V1 仍然要实现通用归一化规则
2. 但本批缺失日期命中这类复杂展示前缀的风险较低

---

## 7. 单日重建算法

对某个缺失交易日 `D`：

### 7.1 拉取辅助事实

1. 取 `D` 的最终候选代码池
2. 从 `raw_tushare.namechange` 读取这些代码的历史名称区间
3. 从 `raw_tushare.st` 读取这些代码的 ST 事件
   - 这里只用于补充边界证据和人工审查，不作为主成员判断

### 7.2 用 `namechange` 判定 ST 成员

对每个候选 `ts_code`：

1. 解析库内 `namechange` 全历史
2. 取所有满足：
   - `start_date <= D`
   - `end_date is null or D <= end_date`
   - `name` 归一化后匹配 ST-like
3. 若存在这样的活动区间，则该 `ts_code` 在 `D` 视为 ST 成员

### 7.3 名称取值规则

写入 `stock_st.name` 时，优先级如下：

1. 若前后相邻快照都存在该 `ts_code`，且名字相同，则直接用这个稳定名字
2. 否则用 `namechange` 在 `D` 命中的活动名称
3. 若 `namechange` 无法给出活动名称，但 `st` 最近事件能给出名称，则用 `st.name`
4. 三者都拿不到时，进入人工审查，不自动写库

### 7.4 常量字段

当前真实库里 `stock_st` 只有一组类型值，因此重建写入固定为：

- `type = 'ST'`
- `type_name = '风险警示板'`

---

## 8. `st` 的使用方式

### 8.1 必须承担的角色

库内 `st` 在 V1 里承担两个角色：

1. 候选代码发现
2. 边界事件解释

### 8.2 不承担的角色

`st` 不直接承担“主成员状态机”角色。  
原因是 `st_tpye` 的语义不能简单二元化，例如：

- `撤销叠加*ST`
- `从ST变为*ST`
- `从*ST变为ST`

这些类型都不是简单的“进入 / 退出 ST 成员”。

### 8.3 冲突处理

当出现以下情况时，不自动写库，进入人工审查 CSV：

1. `namechange` 判定为非 ST，但 `st(imp_date=D)` 出现与该代码相关的 ST 事件
2. `namechange` 在 `D` 命中多个重叠 ST-like 区间
3. 相邻快照与 `namechange` 在边界上冲突，且 `st` 也无法给出单向解释

---

## 9. 落库策略

### 9.1 写入前门禁

对每个缺失日期 `D`，必须先确认：

1. `raw_tushare.stock_st` 当天当前为 `0` 行
2. `core_serving.equity_stock_st` 当天当前为 `0` 行

如果不是整日空桶，直接拒绝 `apply`。

### 9.2 为什么 V1 可以做 insert-only

当前问题是“整日缺失”，不是“已有部分错误数据”。  
因此 V1 不需要做 replace-by-trade-date，只做 insert-only 即可。

这和当前 `stock_st` 写入路径兼容：

- `write_path = raw_core_upsert`

因为目标日期本来为空，不存在“旧行要删”的问题。

### 9.3 Raw 层溯源要求

Raw 写入时：

1. `api_name` 不再写 `stock_st`
2. 统一写成：
   - `stock_st_repair`
3. `raw_payload` 存本行证据摘要 JSON，例如：

```json
{
  "reconstruction": true,
  "source_kind": "db_namechange_primary",
  "missing_date": "2020-04-23",
  "prev_trade_date": "2020-04-22",
  "next_trade_date": "2020-04-24",
  "namechange_interval": {
    "name": "*ST示例",
    "start_date": "20200115",
    "end_date": null
  },
  "st_event_imp_date_hit": false,
  "evidence_sources": {
    "namechange_table": "raw_tushare.namechange",
    "st_table": "raw_tushare.st"
  }
}
```

这样以后看到重建数据时，可以直接回溯“这行为什么会被补出来”。

---

## 10. 预览与审查产物

`preview` 模式至少输出三份文件：

1. `stock_st_missing_date_preview_summary.csv`
   - 每个缺失日期的重建数量
   - 前后相邻快照数量
   - 差异数量
2. `stock_st_missing_date_preview_rows.csv`
   - 每个缺失日期将要写入的全部成员行
3. `stock_st_missing_date_manual_review.csv`
   - 所有冲突代码、冲突原因、相关证据

---

## 11. 验证步骤

应用后必须做：

1. 检查每个缺失日期在 `raw_tushare.stock_st` 与 `core_serving.equity_stock_st` 都已有数据
2. 校验 `type / type_name` 仍然只有：
   - `ST / 风险警示板`
3. 重新执行 `stock_st` 日期完整性审计
4. 重点核对以下边界日期的重建结果：
   - `2019-04-01`
   - `2020-01-02`
   - `2020-04-23`
   - `2020-08-03`
   - `2020-08-04`
   - `2021-03-16`

---

## 12. 推荐实现文件

### 12.1 Service package

- `src/foundation/services/migration/stock_st_missing_date_repair/`

职责：

1. 读取缺失日期
2. 查询库内辅助事实
3. 生成预览结果
4. 执行 insert-only 落库

### 12.2 CLI handler

- `src/cli_parts/stock_st_missing_date_repair_handlers.py`

职责：

1. 解析 CLI 参数
2. 调用 repair service
3. 输出摘要、CSV 路径与 apply 结果

### 12.3 CLI command

- `src/cli.py`
- 命令：`repair-stock-st-missing-dates`

### 12.4 测试建议

至少补：

1. 名称归一化测试
2. `namechange` 区间命中测试
3. 连续两天缺失窗口的候选发现测试
4. “辅助事实表不存在则命令失败” 测试
5. `api_name=stock_st_repair` 和 `raw_payload` 溯源测试
6. “目标日期已有数据则拒绝 apply” 测试

---

## 13. 已确认决策

### D1（已确认）

本方案按以下口径固定：

1. `namechange` 是主成员判定事实
2. `st` 是候选发现与边界验证事实
3. 不让 `st_tpye` 充当主状态机

### D2（已确认）

本方案默认把它做成：

1. `foundation/services/migration/stock_st_missing_date_repair/` 里的低频修复工具
2. 不新增 Ops 页面入口
3. 不并入 `stock_st.maintain`
4. 通过独立 CLI 命令触发

### D3（已确认）

本方案默认 Raw 补数行写：

- `api_name = stock_st_repair`

而不是继续伪装成 `stock_st` 原始源数据。

---

## 14. 结论

这次 `stock_st` 问题的本质不是同步失败，而是源站历史快照本身存在空桶。  
因此正确做法不是继续重跑，而是：

1. 用 `namechange` 重建 ST 区间事实
2. 用 `st` 发现缺失窗口内的边界变化
3. 以低频修复工具的形式，把指定缺失交易日补成有证据链的快照

这个方案不改 `stock_st` 主链，不新增长期兼容逻辑，也不要求先把两个辅助接口完整接入成正式数据集，比较适合当前这批历史缺口的收口。
