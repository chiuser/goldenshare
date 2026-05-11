# Local Lake Recovery 最小 API 设计 v1

- 版本：v1
- 状态：待评审
- 更新时间：2026-05-11
- 适用范围：`lake_console/backend` 第一期 `Recovery / Write Safety` 页面只读 API
- 关联文档：
  - [Local Lake Kopia 集成恢复管理方案 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-write-recovery-management-plan-v1.md)
  - [Local Lake 管理台升级路线图 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-console-management-roadmap-v1.md)
  - [Local Lake 页面演进边界卡 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-console-page-evolution-boundary-card-v1.md)
  - [Local Lake Recovery / Write Safety 页面交互设计 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-console-recovery-write-safety-page-design-v1.md)

---

## 1. 目标

本方案只定义 `Recovery / Write Safety` 页面第一批**Kopia 集成只读 API**。

本批只解决：

1. 页面能读取 repository 状态；
2. 页面能读取 snapshot 列表；
3. 页面能读取单条 snapshot 详情；
4. 页面能拿到 restore / pin 相关命令预览。

本批明确不解决：

1. restore apply
2. pin / unpin 执行
3. cleanup 执行
4. 自研 recovery log
5. `_recovery/**` 补录扫描

---

## 2. 设计依据

### 2.1 页面定位

第一页已经收口为：

```text
Kopia Snapshot Manager / Restore Assistant
```

所以 API 的主数据源也必须跟着收口到 Kopia，而不是自研 jsonl 账本。

### 2.2 backend 风格

继续沿用当前 `lake_console/backend/app/api` 风格：

1. `FastAPI APIRouter`
2. 简单 `GET`
3. `response_model`
4. 列表接口返回 `{ items, total, limit, offset }`

### 2.3 数据来源

第一期后端只调用：

1. `kopia repository status`
2. `kopia snapshot list --json`

必要时可补：

3. `kopia snapshot show`

---

## 3. API 设计原则

### 3.1 只读优先

第一期不做 destructive / externally visible 动作。

### 3.1.1 Kopia 非交互访问前提

backend 读取 snapshot inventory 时，不应依赖交互式密码输入。

第一期运行前提是：

1. `kopia` CLI 已安装；
2. backend 能定位到 `repository.config`；
3. 若 repository 密码未持久保存在 Keychain，则必须通过：
   - `KOPIA_PASSWORD`
   - 或 `lake_console/config.local.toml` 中的 `kopia_password`
   提供非交互密码。

### 3.2 后端负责归一化

前端不直接消费 Kopia 原始 JSON，不自己做：

1. baseline 判定；
2. dataset/path 映射；
3. retention 文本解析；
4. restore 命令拼装。

### 3.3 页面只拿够用字段

第一期只做：

1. summary
2. list
3. detail

---

## 4. 第一期 API 范围

只包含 3 个接口：

```text
GET /api/recovery/repository-summary
GET /api/recovery/snapshots
GET /api/recovery/snapshots/{snapshot_id}
```

本批不包含：

```text
POST /api/recovery/restore-apply
POST /api/recovery/pin
POST /api/recovery/unpin
POST /api/recovery/cleanup
```

---

## 5. 路由与返回模型

建议新增：

- `lake_console/backend/app/api/recovery.py`

建议新增 schema：

- `LakeRecoveryRepositorySummaryResponse`
- `LakeRecoverySnapshotListResponse`
- `LakeRecoverySnapshotSummary`
- `LakeRecoverySnapshotDetailResponse`
- `LakeRecoveryCommandHint`

仍统一放入：

- [lake.py](/Users/congming/github/goldenshare/lake_console/backend/app/schemas/lake.py)

---

## 6. `GET /api/recovery/repository-summary`

### 6.1 作用

供页面顶部指标条使用。

### 6.2 返回字段

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `connected` | `bool` | repository 是否已连接 |
| `repository_type` | `str \| null` | `filesystem` 等 |
| `repository_path` | `str \| null` | repository 根路径 |
| `lake_root` | `str` | 当前 Lake 根路径 |
| `snapshot_count` | `int` | 当前可见 snapshot 数量 |
| `pinned_snapshot_count` | `int` | 当前已 pin snapshot 数量 |
| `latest_snapshot_at` | `datetime \| null` | 最近快照时间 |
| `latest_baseline_at` | `datetime \| null` | 最近 baseline 时间 |

---

## 7. `GET /api/recovery/snapshots`

### 7.1 作用

供主表格使用。

### 7.2 查询参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `scope` | `str` | 否 | `whole_lake / manifest / raw / derived / research / indicators` |
| `dataset_key` | `str` | 否 | 按 dataset 筛选 |
| `pinned` | `bool` | 否 | 是否已 pin |
| `baseline_only` | `bool` | 否 | 仅看 baseline |
| `query` | `str` | 否 | 匹配 `snapshot_id / description / path / pin name` |
| `finished_from` | `str` | 否 | ISO datetime 起始 |
| `finished_to` | `str` | 否 | ISO datetime 结束 |
| `limit` | `int` | 否 | 默认 `100`，最大 `500` |
| `offset` | `int` | 否 | 默认 `0` |

### 7.3 返回字段

列表项建议包含：

| 字段 | 类型 | 说明 |
|---|---|---|
| `snapshot_id` | `str` | snapshot id |
| `description` | `str \| null` | snapshot description |
| `scope` | `str` | 归一化 scope |
| `dataset_key` | `str \| null` | 若能映射则返回 |
| `source_path` | `str` | 原始 path |
| `is_baseline` | `bool` | 是否 baseline |
| `pins` | `list[str]` | pin 名列表 |
| `retention_reasons` | `list[str]` | retention 信息 |
| `total_size` | `int` | 字节数 |
| `file_count` | `int` | 文件数 |
| `dir_count` | `int` | 目录数 |
| `started_at` | `datetime \| null` | 开始时间 |
| `finished_at` | `datetime \| null` | 完成时间 |

---

## 8. `GET /api/recovery/snapshots/{snapshot_id}`

### 8.1 作用

供右侧详情抽屉使用。

### 8.2 返回字段

在 summary 基础上补：

| 字段 | 类型 | 说明 |
|---|---|---|
| `repository_path` | `str \| null` | repository 根路径 |
| `host` | `str \| null` | source host |
| `user_name` | `str \| null` | source user |
| `command_hints` | `list[LakeRecoveryCommandHint]` | 建议命令 |

`command_hints` 第一批只需要：

1. restore whole target to temp dir
2. restore selected subpath to temp dir
3. pin command preview
4. unpin command preview

---

## 9. 基础归一化规则

后端需统一完成：

1. `scope` 映射
2. `dataset_key` 映射
3. `is_baseline` 判定
4. `pins` 提取
5. restore command 预组装

### 9.1 baseline 判定

第一期规则：

满足任一条件即可判为 baseline：

1. `source_path == lake_root` 且 `pins` 包含 `baseline`
2. `description` 包含 `baseline`

### 9.2 dataset 映射

例：

- `<lake_root>/raw_tushare/stk_mins_by_date` -> `dataset_key=stk_mins`
- `<lake_root>/raw_tushare/hk_basic` -> `dataset_key=hk_basic`
- `<lake_root>/manifest/security_universe` -> `dataset_key=null`

---

## 10. 第一期验收标准

完成后应满足：

1. 页面能看见 repository summary；
2. 页面能看见 baseline snapshot；
3. 页面能看见 pins；
4. 页面能按 dataset/path 筛选 snapshots；
5. 详情抽屉能展示 restore command preview；
6. 全链路不依赖 `write_recovery_log.jsonl`。
