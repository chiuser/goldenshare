# 财势乾坤行情系统前端

`wealth` 是独立行情前端，与运营后台 `frontend/` 同仓，但不共用 Shell、路由或视觉体系；依赖、构建和测试分别维护。

## 当前实现与阅读入口

当前已存在市场总览、股票详情、指数详情、自选及板块分析等页面路由，不再是仅有工程骨架的阶段。入口见 [WealthRouter](/Users/congming/github/goldenshare/wealth/src/app/routes/WealthRouter.tsx)。页面存在不等于全部模块完成真实接入或生产验收，具体状态以对应方案、代码与验收证据为准。

- [工程规则](/Users/congming/github/goldenshare/wealth/AGENTS.md)：独立工程边界、按任务必读资料及验证要求。
- [文档索引](/Users/congming/github/goldenshare/wealth/docs/README.md)：定位当前系统基线、页面合同与历史资料。
- [package.json](/Users/congming/github/goldenshare/wealth/package.json)：React/TypeScript/Vite/Vitest 等依赖及实际命令，不另维护版本表。

## 开发与验证入口

先确认依赖、后端环境和启动授权；不覆盖已有配置或自动安装套件。在仓库根目录可执行：

```bash
npm --prefix wealth run dev
```

[Vite 配置](/Users/congming/github/goldenshare/wealth/vite.config.ts)使用 /wealth/ base，将 /api 代理到 http://127.0.0.1:8000；开发服务器实际端口看终端输出，不能与运营 frontend 的端口混为一谈。根目录 local-build-and-run.sh 不负责启动 Wealth。

有效代码改动按工程规则执行 typecheck、相关测试及 build；页面行为变化另补真实 API/浏览器验收。命令入口：

```bash
npm --prefix wealth run typecheck
npm --prefix wealth run test
npm --prefix wealth run build
```

仅改说明文档不代表已重跑上述业务验收。本 README 不承接页面方案的未决事项，也不将 mock 或历史设计升级为当前事实。

## 目录导航

- src/app：路由、Provider 和应用装配。
- src/pages、src/features：页面编排与领域模块。
- src/shared、src/styles：共享能力与样式。
- docs/system、docs/pages：当前基线及页面专题；docs/reference 为历史参考。

具体边界统一见工程规则，不在入口重复完整开发清单。
