# Goldenshare 正式发版流程（v1）

## 1. 适用范围

本流程用于 `goldenshare` 业务主系统与运维系统的正式发版。  
目标：让发版可重复、可回滚、可审计。

本流程覆盖：

- 代码合入前检查
- 发版前预检
- 服务器发版执行
- 发版后验收
- 回滚流程

---

## 2. 角色与职责

- 开发负责人：准备代码、补齐测试、输出变更说明。
- 发布执行人：在服务器执行发版脚本并记录结果。
- 验收人：按验收清单确认接口与页面行为。

---

## 3. 分支与提交规范

- 所有业务改动先在功能分支开发，合并到主干后发版。
- 每次发版必须有明确版本标识（Git commit SHA）。
- 不允许“未提交本地改动”直接上服务器。

---

## 4. 发版前必做清单（本地）

在仓库根目录执行：

```bash
bash scripts/release-preflight.sh
```

该脚本默认执行：

1. Python 编译检查
2. 最小回归：`tests/web/test_health_api.py` + `tests/web/test_quote_api.py`
3. Web 关键接口回归
4. 架构边界测试
5. 前端构建

可选开关（环境变量）：

- `RUN_WEB_TESTS=0`：跳过 Web 关键测试
- `RUN_FRONTEND_BUILD=0`：跳过前端构建
- `RUN_COMPILE_CHECK=0`：跳过 compileall
- `RUN_MINIMAL_TESTS=0`：跳过最小回归
- `RUN_ARCH_TESTS=0`：跳过架构边界测试

说明：正式发版不建议关闭任何开关。

---

## 5. 服务器发版步骤（systemd）

推荐使用分层脚本：

```bash
bash scripts/deploy-layered-systemd.sh main
```

默认流程：

1. 拉取指定分支代码
2. 安装后端依赖
3. 构建前端
4. 执行数据库迁移（`goldenshare init-db`）
5. 按层重启 `foundation(worker) / ops(scheduler) / platform(web)` 服务
6. 分层自检（foundation 资源列表 + ops 执行协调）
7. 健康检查 `/api/health` 与 `/api/v1/health`

分层开关（环境变量）：

- `DEPLOY_FOUNDATION=0`：跳过 worker 重启
- `DEPLOY_OPS=0`：跳过 scheduler 重启
- `DEPLOY_PLATFORM=0`：跳过 web 重启
- `RUN_DB_MIGRATION=0`：跳过数据库迁移
- `RUN_FRONTEND_BUILD=0`：跳过前端构建

需要在数据库维护窗口中“拉取代码、安装后端、执行 migration，但保持现有服务启停状态”时，使用统一入口：

```bash
bash scripts/deploy-systemd.sh dev-interface --maintenance-migration
```

该模式固定关闭前端/Wealth 构建、默认规则 seed、moneyflow seed、systemd unit 同步以及 Foundation、Ops、Platform、Realtime、QTF 服务重启，并强制执行 migration；迁移后只运行 Foundation 资源加载自检，不执行 Ops 状态协调、Web 健康检查或服务状态读取，确保服务保持调用前状态。它**不负责**暂停自动任务、停止服务或恢复服务；执行前仍必须由维护流程完成 schedule 暂停、worker/scheduler 停止、开放 TaskRun/锁/长事务检查，执行后再独立完成连接池回收、服务恢复和验收。禁止再用一长串临时环境变量手工拼出同一模式，也禁止把该模式当成完整发版或恢复服务命令。

维护模式的配置审计固定如下：

| 配置 | 默认值与来源 | 持久化/范围 | 消费者与依赖 | 生效与可见性 | 测试门禁 |
| --- | --- | --- | --- | --- | --- |
| `MAINTENANCE_MIGRATION_MODE` | 默认 `0`；只由 `deploy-systemd.sh --maintenance-migration` 在当前进程导出为 `1`，运营不直接维护该变量 | 不持久化，仅本次部署子进程 | `deploy-layered-systemd.sh`；依赖 wrapper 同时把所有 deploy/build/seed/unit 开关固定为安全值，且与 `--qtf-only` 互斥 | 立即生效；日志明确显示保持 systemd 状态并跳过 Ops/健康/状态步骤 | `tests/test_deploy_layered_systemd_script.py` 固化全部关闭项、migration 开启项、互斥关系和 layered 消费分支 |

关键前提：

- `/etc/goldenshare/web.env` 可读
- 具备受控 sudo/systemd 权限
- 服务由 systemd 托管（不使用手工前台进程）

---

## 6. 发版后验收清单

最少执行以下验收：

### 6.1 平台健康

- `GET /api/health` 返回 200
- `GET /api/v1/health` 返回 200

### 6.2 鉴权

- 登录流程可用
- 无 token 访问受保护接口时返回 401/403（按配置）

### 6.3 行情主系统接口

- `GET /api/v1/quote/detail/page-init`
- `GET /api/v1/quote/detail/kline`（day/week/month）
- `GET /api/v1/quote/detail/related-info`
- `GET /api/v1/quote/detail/announcements`（占位）
- `GET /api/v1/market/trade-calendar`

重点检查：

- 分钟线请求返回 `UNSUPPORTED_PERIOD`
- 指数/ETF 复权参数返回 `UNSUPPORTED_ADJUSTMENT`
- 响应不泄露内部异常栈

---

## 7. 回滚流程

触发条件（任一满足）：

- 健康检查连续失败
- 核心接口不可用
- 严重数据错误或权限风险

回滚步骤：

1. 记录当前失败版本 SHA
2. 切换到上一个稳定 SHA
3. 重新执行 `deploy-systemd.sh`
4. 重跑验收清单
5. 在问题单中补充根因与修复计划

---

## 8. 变更记录要求

每次发版记录至少包含：

- 发版时间
- 发布人
- 目标分支与 commit SHA
- 预检结果摘要
- 验收结果摘要
- 是否回滚
- 风险与后续行动项

建议将记录同步到团队发布日志或工单系统，保证可追溯。
