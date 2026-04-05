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
4. 前端构建

可选开关（环境变量）：

- `RUN_WEB_TESTS=0`：跳过 Web 关键测试
- `RUN_FRONTEND_BUILD=0`：跳过前端构建
- `RUN_COMPILE_CHECK=0`：跳过 compileall
- `RUN_MINIMAL_TESTS=0`：跳过最小回归

说明：正式发版不建议关闭任何开关。

---

## 5. 服务器发版步骤（systemd）

使用已有脚本：

```bash
bash scripts/deploy-systemd.sh main
```

默认流程：

1. 拉取指定分支代码
2. 安装后端依赖
3. 构建前端
4. 执行数据库迁移（`goldenshare init-db`）
5. 重启 `web/worker/scheduler` 服务
6. 健康检查 `/api/health`

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
