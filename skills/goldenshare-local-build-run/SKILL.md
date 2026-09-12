---
name: "本地部署技能"
description: "Use when the user asks to compile and start Goldenshare locally (Web + frontend dev), or debug local startup flow."
---

# 本地 Web 与运营前端启动

仅用于 Web + 运营 frontend，不是 Wealth 或 DG 启动流程。

## 执行前

阅读仓库根 AGENTS、AGENTS.local.md、scripts/AGENTS.md，以及：
- [本地/生产边界](/Users/congming/github/goldenshare/docs/release/local-prod-operation-boundary-v1.md)
- [启动脚本](/Users/congming/github/goldenshare/scripts/local-build-and-run.sh)

确认用户要启动还是仅检查；只读排查不得启动服务。确认既有 Python/npm 环境、环境文件、数据库目标、端口与已有进程，不输出连接串或凭据。

**启动授权不包含安装授权。** 执行前核对安装参数及 INSTALL_PY_DEPS/INSTALL_FE_DEPS 环境变量；需要 frontend 时还须确认 frontend/node_modules 已存在。缺少目录会隐式 npm install，即使使用 --skip-frontend-build 也可能触发。未获安装授权就停止并报告缺项，不通过运行脚本试探。

## 获准启动

在仓库根目录执行，按用户范围选择：

| 范围 | 命令 |
| --- | --- |
| Web + frontend | `bash scripts/local-build-and-run.sh` |
| 仅 Web | `bash scripts/local-build-and-run.sh --web-only` |
| 仅 frontend | `bash scripts/local-build-and-run.sh --frontend-only` |
| 额外预检 | 在获准范围中添加 `--with-preflight`，先核对测试环境隔离 |

默认包含后端 compileall、frontend 构建和两侧启动；单侧模式按脚本分支裁剪。详细参数只在操作边界维护。不得顺手迁移、创建账号、修改配置、提交维护任务或启动生产 worker/scheduler。

## 验证与交付

按实际启动范围检查，不为单侧验证额外启动另一侧：
- Web 默认 `http://127.0.0.1:8000/api/health`、`/api/docs`。
- frontend 默认 `http://127.0.0.1:5173/app/`，实际端口以启动输出为准。
- 页面可达不证明所有 API 或数据维护链路通过。

报告实际命令、启动的进程与访问地址、检查结果和未验证项。遇到权限、连接或依赖错误，先诊断，不自行安装、改配置或终止无关进程。
