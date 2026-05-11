# Local Lake 持久备份与恢复管理方案 v1

- 版本：v1
- 状态：待评审
- 更新时间：2026-05-11
- 适用范围：`lake_console/` 本地 Parquet Lake 的正式写入、备份、恢复与前端管理

---

## 1. 背景与问题

`RISK-2026-05-11-007` 已确认：

1. 旧 `lake-console sync-stk-mins-range --ts-code ...` 路径曾对正式 `raw_tushare/stk_mins_by_date/freq=*/trade_date=*` 执行整分区替换。
2. 替换结果是单股票数据，而不是全市场数据，导致 `freq=1` 大面积分区、`freq=5` 局部分区被污染。
3. 当前虽然已有 `audit-stk-mins-raw-integrity`、`recover-stk-mins-raw-from-research --dry-run/--apply`，但它们仍是 `stk_mins` 专项恢复能力。
4. 当前 Lake 公共写盘层只提供“短暂 backup + 原子替换”，成功后会立即删除 backup，不形成持久回滚点。

也就是说，当前真实短板不是“没有规则”，而是：

1. **正式写入缺少持久备份。**
2. **恢复信息没有收敛成统一账本。**
3. **Lake 管理台前端看不到真实的备份/恢复状态。**
4. **危险写入范围没有被公共写盘层硬编码拦截。**

---

## 2. 目标与边界

本方案的目标是把 Local Lake 的正式写入从“尽量别写坏”升级为：

```text
正式写入前必有可回滚备份
写入后必有可查询账本
事故后必有可执行恢复路径
前端管理台必能看见和管理这些事实
```

目标：

1. 对所有正式替换写入建立持久备份，不再只保留 `_tmp/_backup` 瞬时文件。
2. 统一记录正式写入前后的关键事实，形成 `manifest/write_recovery_log.jsonl`。
3. 为 Lake 管理台提供恢复总览、备份明细、恢复计划、保留策略和手工管理能力。
4. 把“部分范围写入不得直接替换正式全量目标”做成公共门禁，而不是只靠开发约束。
5. 先以 `stk_mins` 为 P0 首批落地对象，再推广到其他 `raw/derived/research/manifest` 正式目标。

不做：

1. 不做远程生产数据库备份。
2. 不做整盘镜像级备份；本方案只做 Lake 目标级、分区级、current-file 级备份。
3. 不把恢复系统接入生产 `TaskRun` / `ops.task_run`。
4. 不在第一期就把所有恢复动作都开放到前端一键执行。

---

## 3. 当前实现事实与缺口

### 3.1 当前已存在的好处

1. `parquet_writer.py` 已实现 `_tmp -> replace` 的原子替换。
2. `stk_mins_raw_recovery_service.py` 已具备：
   - raw 完整性审计
   - dry-run 恢复预案
   - `research + raw patch` 的专项 apply 恢复
3. `lake_console/frontend` 已经有：
   - `datasets`
   - `datasetDetail`
   - `commands`
   - `risks`
   页面骨架，说明前端可承接新的治理页。

### 3.2 当前明确缺口

1. `replace_file_atomically()` / `replace_directory_atomically()` 会在替换成功后删除 backup。
2. 当前没有统一的“正式写入账本”，只能靠：
   - `sync_runs.jsonl`
   - `_recovery/`
   - 局部专项输出
   分散追溯。
3. `stk_mins` 的恢复 apply 已经开始沉淀，但还没有升格为 Lake 公共能力。
4. 前端看不到：
   - 哪个正式目标最近被覆盖过
   - 覆盖前后行数变化
   - 当前还有哪些可回滚版本
   - 哪些 backup 已过期/被 pin/待清理

---

## 4. 设计原则

### 4.1 机制优先于规则

对于正式写入，必须把“先备份再替换”做成默认机制，而不是依赖开发者记忆。

### 4.2 备份必须持久，不得成功即删

只要是正式目标被覆盖，就必须留下 before image，直到：

1. 过了保留期且未被 pin；
2. 符合清理条件；
3. 经显式清理动作删除。

### 4.3 账本必须可重建

`manifest/write_recovery_log.jsonl` 是前端和运维读取的主索引，但**不能成为单点真相**。
真正的保底事实还必须包含：

1. `_recovery/backups/**/metadata.json`
2. `_recovery/restore_runs/**/metadata.json`

这样即便 jsonl 索引损坏，仍可扫描目录重建。

### 4.4 危险写入必须 fail-closed

如果一个写入目标被判定为：

1. 正式 canonical 分区或 current 文件
2. 但本次写入 scope 只是局部 patch / 单股票 / 子集

则公共写盘层必须直接拒绝，而不是继续写。

### 4.5 可视化必须围绕真实文件事实

前端页面不直接推断恢复状态，也不依赖远程状态表。
它只消费本地 Lake 的真实事实：

1. `manifest/write_recovery_log.jsonl`
2. `_recovery/backups/**`
3. `_recovery/restore_runs/**`
4. 当前正式目标路径本身

---

## 5. 需要保护的正式目标

第一期受保护对象：

1. `raw_tushare/*/current/part-000.parquet`
2. `manifest/security_*/*.parquet`
3. `raw_tushare/*/trade_date=YYYY-MM-DD/*.parquet`
4. `raw_tushare/*/freq=*/trade_date=YYYY-MM-DD/*.parquet`
5. `derived/**/*`
6. `research/**/*`
7. `indicators/**/*`

不纳入正式恢复账本的对象：

1. `_tmp/**/*`
2. debug 导出目录
3. dry-run 输出
4. 临时检查文件

---

## 6. 核心模型

### 6.1 目标类型

```text
current_file
manifest_file
date_partition
freq_date_partition
month_bucket_partition
indicator_partition
```

### 6.2 写入范围（write_scope）

```text
full_snapshot
full_partition
merge_patch
repair_from_source
repair_from_local
derived_rebuild
research_rebuild
restore_apply
```

### 6.3 保护等级（protection_level）

```text
critical    # stk_mins raw / research / derived / indicator
standard    # 日频正式分区、重要 current file
light       # 小型 manifest / reference current
```

### 6.4 恢复记录状态（record_status）

```text
prepared
committed
failed_before_replace
committed_index_pending
restore_applied
cleanup_deleted
```

---

## 7. 持久备份布局

### 7.1 目录布局

```text
<LAKE_ROOT>/
  manifest/
    write_recovery_log.jsonl
    restore_action_log.jsonl

  _recovery/
    backups/
      dataset=<dataset_key>/
        layer=<layer>/
          target_kind=<target_kind>/
            key=<normalized_key>/
              version=<run_id>/
                metadata.json
                before/
                  ...

    restore_runs/
      run_id=<run_id>/
        metadata.json
        inputs/
          ...
        tmp_output/
          ...
        backups/
          ...
```

### 7.2 key 规范

示例：

```text
key=current
key=trade_date=2026-05-08
key=freq=1__trade_date=2026-05-08
key=freq=15__trade_month=2026-05__bucket=07
```

要求：

1. key 必须稳定、可反解。
2. 前端可以直接据此做筛选和展示。
3. 不能依赖临时命令参数字符串拼接。

---

## 8. `manifest/write_recovery_log.jsonl` 设计

### 8.1 定位

它是 Lake 管理台与恢复管理的**主索引文件**。

前端不会直接读取磁盘文件；
而是由 `lake_console/backend` 解析后提供 API。
但数据语义必须以这个 jsonl 为准。

### 8.2 单条记录字段

建议最小字段集合：

| 字段 | 说明 |
|---|---|
| `record_id` | 全局唯一记录 ID |
| `run_id` | 本次写入 run_id |
| `dataset_key` | 数据集 |
| `layer` | `raw_tushare / derived / research / manifest / indicators` |
| `target_kind` | `current_file / freq_date_partition / ...` |
| `target_path` | 正式目标路径 |
| `partition_key` | 结构化 key |
| `write_scope` | 本次写入范围 |
| `protection_level` | `critical / standard / light` |
| `command` | 原始命令文本 |
| `source_mode` | `tushare / prod-raw-db / prod-core-db / local-research / local-1m` 等 |
| `writer_name` | 使用的 service / writer |
| `before_exists` | 替换前目标是否存在 |
| `before_file_count` | 替换前文件数 |
| `before_row_count` | 替换前行数 |
| `before_bytes` | 替换前体积 |
| `before_schema_hash` | 替换前 schema/hash |
| `after_file_count` | 替换后文件数 |
| `after_row_count` | 替换后行数 |
| `after_bytes` | 替换后体积 |
| `after_schema_hash` | 替换后 schema/hash |
| `backup_path` | 持久备份路径 |
| `metadata_path` | `_recovery` 下 metadata.json 路径 |
| `record_status` | 当前状态 |
| `restorable` | 当前是否允许回滚 |
| `retention_tier` | 保留级别 |
| `retention_expires_at` | 预计可清理时间 |
| `pinned` | 是否手工 pin |
| `created_at` | 创建时间 |
| `finished_at` | 完成时间 |
| `error_message` | 失败原因（如有） |

### 8.3 账本可重建要求

如果：

1. 备份目录与 `metadata.json` 已写成
2. 但 `write_recovery_log.jsonl` 追加失败

则不能回滚正式写入。
此时系统应：

1. 保留 backup；
2. 在 Lake 风险扫描中标记 `recovery_log_out_of_sync`；
3. 允许执行：

```bash
lake-console reconcile-write-recovery-log
```

该命令扫描 `_recovery/backups/**/metadata.json`，补写缺失索引。

---

## 9. 公共写盘流程改造

### 9.1 当前问题

当前公共写盘函数是：

1. `replace_file_atomically()`
2. `replace_directory_atomically()`

它们的 backup 只存在于 `_tmp/.../_backup`，替换成功后立即删除。

### 9.2 目标流程

正式写入统一改成：

```text
生成 tmp 输出
-> 校验 tmp 行数 / schema / key
-> 判定写入范围是否合法
-> 复制或移动旧正式目标到 _recovery/backups/.../before
-> 写 metadata.json
-> 追加 prepared 记录到 write_recovery_log.jsonl
-> 原子替换正式目标
-> 追加 committed 记录 / 更新状态
```

### 9.3 fail-closed 规则

对于受保护目标：

1. 旧目标备份失败 -> 拒绝写入
2. `metadata.json` 写失败 -> 拒绝写入
3. 写入范围判定为危险 -> 拒绝写入
4. 预写入校验失败 -> 拒绝写入

只有一个例外：

- 正式目标已替换完成，但 `write_recovery_log.jsonl` 追加失败
  这时不能回滚正式数据，必须保留 backup，并抛出可修复风险。

### 9.4 写入范围门禁

公共写盘层必须识别：

1. 目标是不是 canonical 全量目标
2. 当前写入是不是局部 patch / 单股票 / 子集

如果答案是“全量目标 + 局部写入”，则必须：

1. 拒绝直接 replace
2. 提示改走：
   - merge writer
   - patch layer
   - dataset-specific repair path

这条门禁是本次事故的根因级防线。

---

## 10. 恢复能力设计

### 10.1 两类恢复

#### A. 物理回滚

适用场景：

1. 一次正式替换整体错误
2. before image 完整可用

动作：

1. 选择某条 `write_recovery_log` 记录
2. 取其 `backup_path`
3. 回写到正式目标
4. 生成新的 restore run 和 action log

#### B. 逻辑恢复

适用场景：

1. 像 `stk_mins` 一样，需要 `research + patch rows` 合并恢复
2. 不是简单回滚旧版本

动作：

1. 仍然要纳入统一 restore run 目录
2. 仍然要写 `restore_action_log.jsonl`
3. 仍然要把恢复前当前分区备份

也就是说：

- `stk_mins_raw_recovery_service` 不会被废掉
- 但它的 apply 路径要升级为：
  - 受统一账本管理
  - 受统一 backup 策略管理
  - 前端可见

### 10.2 命令面

第一期 CLI：

```bash
lake-console list-write-recovery-records --dataset stk_mins --layer raw_tushare
lake-console restore-lake-target --record-id <id> --dry-run
lake-console restore-lake-target --record-id <id> --apply
lake-console reconcile-write-recovery-log
lake-console list-recovery-backups --dataset stk_mins
```

第二期保留：

```bash
lake-console pin-recovery-backup --record-id <id>
lake-console unpin-recovery-backup --record-id <id>
lake-console cleanup-recovery-backups --dry-run
lake-console cleanup-recovery-backups --apply
```

---

## 11. 前端可视化与管理方案

### 11.1 页面定位

在 `lake_console/frontend` 中新增一个治理页：

```text
Recovery / Write Safety
```

它不是纯“风险文案页”，而是一个真正能管理 Lake 备份与恢复的页面。

### 11.2 页面目标

前端必须能回答这些问题：

1. 最近哪些正式目标被覆盖过？
2. 覆盖前后行数变化是否异常？
3. 当前还有哪些可回滚版本？
4. 哪些备份已经过期、哪些被 pin、哪些待清理？
5. 哪些正式写入没有索引成功，需要执行 reconcile？
6. 某个风险事件对应的恢复命令是什么？

### 11.3 页面结构

#### A. 概览区

卡片指标：

1. 最近 24h 正式替换次数
2. `critical` 级别覆盖次数
3. 当前可恢复版本数量
4. 已 pin 版本数量
5. 备份总占用字节
6. `recovery_log_out_of_sync` 风险数

#### B. 写入恢复账本表

主表按 `write_recovery_log.jsonl` 展示，支持筛选：

1. `dataset_key`
2. `layer`
3. `target_kind`
4. `write_scope`
5. `record_status`
6. `protection_level`
7. 日期范围
8. 是否 pinned

表列建议：

1. 时间
2. 数据集
3. Layer
4. 目标 key
5. 写入范围
6. 前行数
7. 后行数
8. 差异百分比
9. 是否可恢复
10. retention
11. 状态
12. 操作

#### C. 记录详情抽屉

点开一条记录后展示：

1. 完整目标路径
2. backup 路径
3. 原命令
4. writer/service
5. before/after 行数、bytes、schema hash
6. 风险提示
7. 推荐 restore 命令
8. pin/unpin 状态

#### D. Restore 预案区

用于展示：

1. 物理回滚 dry-run 结果
2. `stk_mins` 这种逻辑恢复 dry-run 结果
3. 预计恢复分区数
4. 预计写入行数
5. 阻塞原因

#### E. 保留与清理区

展示：

1. 不同 dataset/layer 当前占用
2. 即将到期的 backup
3. 已 pin backup
4. cleanup dry-run 预估释放空间

### 11.4 前端交互边界

第一期前端只做：

1. 读账本
2. 看明细
3. 生成 restore / cleanup 建议命令
4. 发起 dry-run API

第二期才开放：

1. pin / unpin
2. restore apply
3. cleanup apply

这样可以先把“看得见”做扎实，再逐步开放真正的 destructive 操作。

---

## 12. 后端 API 设计

第一期 API：

```text
GET  /api/recovery/summary
GET  /api/recovery/records
GET  /api/recovery/records/{record_id}
GET  /api/recovery/storage
POST /api/recovery/restore-preview
POST /api/recovery/reconcile-log
```

第二期 API：

```text
POST /api/recovery/pin
POST /api/recovery/unpin
POST /api/recovery/restore-apply
POST /api/recovery/cleanup-preview
POST /api/recovery/cleanup-apply
```

注意：

1. 前端不直接读 `manifest/write_recovery_log.jsonl`。
2. 前端只通过 backend API 读取，backend 负责解析 jsonl 和 fallback 扫描 `_recovery`。
3. 任何 apply 类 API 都必须要求显式参数，禁止模糊默认行为。

---

## 13. 保留策略

### 13.1 保留分层

建议：

#### critical

适用：

1. `stk_mins` raw / derived / research
2. 研究层指标正式分区

规则：

1. 至少保留最近 `3` 个 committed 版本
2. 且至少保留 `30` 天
3. 打开 incident 或被 pin 的 backup 不得自动清理

#### standard

适用：

1. 一般 `trade_date` 分区数据集
2. `index_mins`、`daily` 等正式分区

规则：

1. 至少保留最近 `2` 个 committed 版本
2. 且至少保留 `14` 天

#### light

适用：

1. 小体量 `current_file`
2. `manifest/security_reference`

规则：

1. 至少保留最近 `10` 个 committed 版本
2. 且至少保留 `90` 天

### 13.2 清理原则

1. 清理必须先 dry-run。
2. 不能清理 pinned 版本。
3. 不能清理当前 open incident 涉及版本。
4. 清理动作也必须记入 `restore_action_log.jsonl`。

---

## 14. 与现有 `stk_mins` 专项恢复的关系

当前已有：

1. `audit-stk-mins-raw-integrity`
2. `recover-stk-mins-raw-from-research --dry-run`
3. `recover-stk-mins-raw-from-research --apply`

本方案不是推翻它，而是要求它在下一轮收敛成：

1. 使用统一 backup registry
2. 使用统一 `write_recovery_log.jsonl`
3. 使用统一 restore action log
4. 在前端可见
5. 能与其他数据集共用恢复管理台

`stk_mins` 是这套机制的**首个 P0 落地对象**，不是永久特殊分支。

---

## 15. 分阶段落地

### Phase 1：公共持久备份

目标：

1. 改造 `parquet_writer.py`
2. 所有正式 replace 写入都留下持久 backup
3. 生成 `metadata.json`
4. 写入 `manifest/write_recovery_log.jsonl`

门禁：

1. 受保护目标写入后 backup 不会被立刻删除
2. 能按记录找到 before image

### Phase 2：CLI 恢复与账本重建

目标：

1. `list-write-recovery-records`
2. `restore-lake-target`
3. `reconcile-write-recovery-log`

门禁：

1. 账本损坏时可重建
2. 样本 current file / partition 可成功回滚

### Phase 3：前端只读恢复管理页

目标：

1. 展示账本表
2. 展示明细
3. 展示 backup 占用
4. 支持 restore dry-run 预览

门禁：

1. 前端能准确展示 `write_recovery_log.jsonl` 主索引
2. 能看到 log out-of-sync 风险

### Phase 4：`stk_mins` 专项并轨

目标：

1. `stk_mins` 的恢复 apply 改走统一 recovery registry
2. `stk_mins` 页面可直接看到损坏分区、恢复计划、备份版本

门禁：

1. `RISK-2026-05-11-007` 的恢复流程有统一入口
2. 样本恢复后可在前端看到全过程

### Phase 5：前端管理动作

目标：

1. pin/unpin
2. restore apply
3. cleanup dry-run/apply

门禁：

1. destructive UI 操作都有 dry-run 和二次确认
2. 所有动作都留下 action log

---

## 16. 验收标准

后端：

1. 任意正式 replace 写入后，都能在 `_recovery/backups` 找到 before image。
2. `manifest/write_recovery_log.jsonl` 能稳定记录写入前后事实。
3. 危险 partial write 命中 canonical target 时，公共写盘层直接拒绝。
4. `reconcile-write-recovery-log` 能从 `_recovery/**/metadata.json` 重建缺失索引。
5. `stk_mins` 样本恢复能留下统一恢复账本和备份记录。

前端：

1. 能按 dataset/layer/status/date range 查询 recovery 记录。
2. 能看清楚 before/after 行数差异。
3. 能区分 committed、failed、index_pending、restore_applied。
4. 能显示 pinned / expiring / cleanup 候选。
5. 能触发 restore dry-run 并展示预案。

治理：

1. `RISK-2026-05-11-007` 的长期规避方案不再只依赖文档提醒。
2. 正式写入都有后悔药。
3. 风险关闭时可给出恢复记录、恢复分区数、前后行数和剩余风险。

---

## 17. 当前结论

这次 P0 事故的长期解法，不应该停在：

```text
禁止这样写
以后注意
补更多测试
```

而应该升级为：

```text
公共写盘层强制持久备份
统一恢复账本
统一 restore 能力
Lake 管理台前端可视化与管理
```

只有这样，后面再出现类似事故时，我们才不是“靠记忆找证据”，而是：

1. 立刻知道谁写了什么；
2. 立刻知道旧版本在哪；
3. 立刻能做 dry-run；
4. 必要时能在 UI 或 CLI 上执行恢复。
