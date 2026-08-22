# Local Lake Kopia 集成恢复管理方案 v1

- 版本：v1
- 状态：历史/冻结（旧 `lake_console/backend` 文档；原阶段状态仅代表文档记录时点）
- 更新时间：2026-05-11
- 适用范围：`lake_console/` 本地 Parquet Lake 的备份可视化、快照定位与恢复辅助

> **当前边界声明**：本文保留旧 Local Lake Console Kopia 集成恢复方案证据。文中的 Kopia、旧 Lake Root 和旧恢复主线不得作为当前 Dagster Lake 或新开发、迁移、历史补录、bootstrap、修复、写湖依据。当前正式 Lake 路径和安全规则以根目录 `AGENTS.md` 与 `lake_console/orchestrator/src/orchestrator/defs/paths.py` 为准；禁止新增或调用 Kopia。

---

## 1. 背景与结论

`RISK-2026-05-11-007` 已确认：

1. 旧 `stk_mins` 补数路径曾把正式分区替换成局部错误结果。
2. Lake 后续必须具备“能回退到正确历史版本”的能力。

在评估后，方案已经明确收口为：

```text
Kopia 负责底层备份与恢复
Lake 管理台只做轻量 GUI 整合
```

因此，后续不再沿“自研 recovery 主链”推进，不再自己实现：

1. 自建长期备份仓库；
2. 自建物理恢复内容管理；
3. 以 `write_recovery_log.jsonl` 为核心的恢复主账本；
4. 替代 Kopia 的 restore 引擎。

---

## 2. 目标与边界

本方案目标是把 Lake 管理台的 `Recovery / Write Safety` 页面收敛成：

```text
Kopia Snapshot Manager + Restore Assistant
```

第一期目标：

1. 展示当前 Kopia repository 状态。
2. 展示 Lake 相关 snapshots 列表。
3. 展示 pin 状态与 baseline 标记。
4. 支持按数据集路径、时间、pin 状态筛选。
5. 为用户生成可直接执行的 restore 命令。
6. 允许后续补一层轻量操作审计，但不把它升级成新的恢复主系统。

第一期不做：

1. 不做一键 restore apply。
2. 不做自己的 backup 内容存储。
3. 不做自己的 retention engine。
4. 不做自己的 pin/unpin 事实源。
5. 不要求把每次 Lake 写入动作都同步落成自研 recovery 账本。

---

## 3. 核心原则

### 3.1 备份真相只认 Kopia

关于“有哪些历史版本、哪些已 pin、哪些可 restore”的底层事实，统一以 Kopia 为准。

### 3.2 管理台只做薄整合

Lake 管理台的职责是：

1. 读取 Kopia 输出；
2. 做 dataset/path 映射；
3. 做列表、筛选、详情、命令预览；
4. 可选记录人工操作历史。

不是：

1. 自己保存备份内容；
2. 自己维护版本树；
3. 自己实现 restore 引擎。

### 3.3 页面优先服务真实运维动作

Recovery 页要解决的是：

1. 现在有没有 baseline；
2. 某个数据集最近有哪些快照；
3. 哪些快照被 pin；
4. 要恢复某个目标时该执行什么命令。

而不是展示复杂概念解释。

---

## 4. 数据来源

第一期页面与 API 只读取以下来源：

1. `kopia repository status`
2. `kopia snapshot list <lake_root> --json`
3. `kopia snapshot list <lake_root>/<subpath> --json`（按需）
4. 可选：
   - `kopia snapshot show <snapshot_id>`
   - `kopia snapshot verify <snapshot_id>` 的结果摘要

第一期运行前提：

1. backend 所在环境已安装 `kopia` CLI；
2. backend 能定位到 `repository.config`；
3. 若 repository 密码未持久保存在 Keychain，则 backend 必须通过：
   - `KOPIA_PASSWORD`
   - 或 `lake_console/config.local.toml` 中的 `kopia_password`
   提供非交互密码。

第一期不读取：

1. `manifest/write_recovery_log.jsonl`
2. `_recovery/backups/**`
3. `_recovery/restore_runs/**`

这些路径在当前路线下不再作为恢复主事实源。

---

## 5. 页面定位

Recovery 页的正确定位是：

```text
展示 Kopia 快照清单
定位当前 baseline
筛选与查看某个数据集的保护状态
生成 restore 命令
```

不是：

```text
展示每次正式写盘 before/after 账本
```

后者属于自研 recovery 主链，已经不再采用。

---

## 6. 第一期功能范围

### 6.1 Repository Summary

显示：

1. repository 是否已连接；
2. repository 类型（filesystem）；
3. repository 路径；
4. 当前 Lake 根路径；
5. 最新 baseline snapshot 时间；
6. pinned snapshot 数量。

### 6.2 Snapshot Inventory

显示：

1. snapshot 时间；
2. snapshot id；
3. description；
4. pins；
5. retention reasons；
6. source path；
7. 文件数、目录数、大小。

### 6.3 Scope / Dataset Mapping

后端把 Lake 路径映射成更可读的 scope：

1. `whole_lake`
2. `manifest`
3. `raw_tushare/<dataset>`
4. `derived/<dataset>`
5. `research/<dataset>`
6. `indicators/<dataset>`

这样前端可以按 dataset 或 layer 筛选，而不是只显示原始长路径。

### 6.4 Baseline Recognition

第一期只做轻量规则：

若 snapshot：

1. source path 等于整个 Lake 根目录；
2. description 或 pin 名包含 `baseline`；

则前端标记为 `Baseline`。

### 6.5 Restore Command Preview

第一期不执行恢复，只展示建议命令，例如：

1. 整湖 restore 到临时目录；
2. 单数据集 restore 到临时目录；
3. 单分区 restore 到临时目录；
4. pin / unpin 命令预览。

---

## 7. 可选的轻量审计层

如果后续确实需要“谁执行过恢复操作”的管理记录，可以补一层很薄的本地审计：

```text
manifest/recovery_action_log.jsonl
```

但这层只记录：

1. 查看了哪条快照；
2. 复制了哪条 restore 命令；
3. 谁发起了 restore preview；
4. 谁确认执行了 restore。

它不是：

1. 备份内容仓库；
2. snapshot 主索引；
3. pin 主索引；
4. restore 真相源。

这层在第一期不是必做项。

---

## 8. 后端职责

`lake_console/backend` 在这条线上只做：

1. 调用 Kopia CLI；
2. 解析 JSON 输出；
3. 归一化成前端可用模型；
4. 提供筛选、详情和命令建议。

不做：

1. 自己维护 `_recovery/**` 主目录体系；
2. 自己构建恢复账本；
3. 自己重放 restore；
4. 自己判定底层 retention。

---

## 9. 前端职责

前端只做：

1. repository summary 展示；
2. snapshot list 表格；
3. filter bar；
4. right drawer 详情；
5. restore command copy / preview。

前端不做：

1. 直接调用本地文件系统；
2. 自己解析 Kopia JSON 原始输出；
3. 自己判断 baseline；
4. 自己做恢复事实推断。

---

## 10. 第一期建议 API 方向

第一期建议 API 收敛为：

1. `GET /api/recovery/repository-summary`
2. `GET /api/recovery/snapshots`
3. `GET /api/recovery/snapshots/{snapshot_id}`

必要时可补：

4. `GET /api/recovery/command-preview`

但不建议第一期就做：

1. `POST /api/recovery/restore-apply`
2. `POST /api/recovery/pin`
3. `POST /api/recovery/unpin`

这些动作仍建议以命令行执行为主，前端先做辅助，不做真正执行入口。

---

## 11. 一期验收标准

第一期完成后，应满足：

1. 能在管理台看到当前 Kopia repository 已连接状态；
2. 能看到全湖 baseline snapshot；
3. 能看到 pin 名和 retention 信息；
4. 能按 dataset/path 筛选 snapshot；
5. 能打开详情抽屉查看 snapshot 元信息；
6. 能拿到针对选中对象的 restore 命令建议。

不要求：

1. 一键恢复；
2. 自研恢复账本；
3. 历史 `_recovery` 目录补录；
4. 自动 reconcile。

---

## 12. 下一步

下一步应严格按以下顺序推进：

1. 先把 `Recovery` 方案、页面设计、最小 API 设计全部改成 Kopia 集成口径；
2. 评审第一页主要功能点；
3. 再决定是否保留当前错误方向的代码，或重做为 Kopia-backed 只读页；
4. 在你确认前，不继续写任何 recovery 相关代码。
