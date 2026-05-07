# 财势乾坤行情系统前端

`wealth` 是财势乾坤行情系统的独立前端工程。

它与仓库内既有运营后台前端 `frontend/` 同仓，但属于不同项目：

- 独立目录
- 独立 `package.json`
- 独立构建
- 独立测试
- 独立设计体系
- 独立工程规则

首期目标是搭建工程基础，并在后续实现“乾坤行情 / 市场总览”页面。

## 当前阶段

当前只完成工程骨架和文档基线，不包含市场总览页面实现。

首期页面实现前必须先阅读：

- [wealth/docs/README.md](./docs/README.md)
- [wealth/AGENTS.md](./AGENTS.md)

## 技术栈

- React
- TypeScript
- Vite
- Vitest

## 常用命令

```bash
npm install
npm run dev
npm run typecheck
npm run test
npm run build
```

## 目录

```text
wealth/
  docs/
    system/
    pages/
  src/
    app/
    features/
    pages/
    shared/
    styles/
```
