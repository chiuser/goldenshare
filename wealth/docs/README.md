# wealth 文档索引

`wealth/docs` 是财势乾坤行情系统前端工程的本地文档基线。

外部 Drive 文档已经按类别归档到 `reference/`。实际编码必须优先读取本目录中的本地资料，避免依赖聊天记录或远程文档记忆。

## 目录分层

```text
docs/
  reference/              # Drive 原始资料本地拷贝与索引
  system/                 # 系统级：工程、设计、组件、开发原则
  templates/              # 模块开发模板（需求/实施/门禁）
  pages/                  # 页面级：页面需求、API contract、实现提示词
    market-overview/
```

## Drive 原始资料

- [Drive 原始资料索引](./reference/README.md)
- [市场总览 V1.1 Showcase 原型](./reference/showcase/market-overview-v1.1.html)
- [Design Token 原始文档](./reference/design/03-design-tokens.md)
- [组件规范原始文档](./reference/design/04-component-guidelines.md)
- [Codex 实现提示词原始文档](./reference/codex/market-overview-codex-prompt-v1.md)
- [Review v2 原始文档](./reference/review/market-overview-html-review-v2.md)

`reference/` 保存从 Drive 拷贝到本地的原始资料，包括历史版本、review、Logo、HTML Showcase、设计文档、API 与数据字典。它用于防止后续开发只依赖聊天记录或远程 Drive 记忆。

编码前的优先级：

1. 用户最新指令。
2. `reference/` 中的 Drive 原始资料，尤其是 Showcase、Design Token、组件规范和 review 变更单。
3. `system/` 与 `pages/` 中的工程化基线摘要。

如果 `reference/` 与 baseline 摘要冲突，先停下说明冲突，不要擅自选择一个继续写代码。

## 系统级文档

- [系统定位基线](./system/wealth-system-baseline.md)
- [工程架构规范](./system/engineering-architecture.md)
- [设计系统基线](./system/design-system-baseline.md)
- [组件规范基线](./system/component-guidelines-baseline.md)
- [异常码注册表（统一管理）](./system/exception-code-registry.md)

## 页面级文档

- [市场总览页面基线](./pages/market-overview/market-overview-baseline.md)
- [市场总览 API 契约基线](./pages/market-overview/api-contract-baseline.md)
- [市场总览 API 与数据模型设计 v1](./pages/market-overview/market-overview-api-model-design-v1.md)
- [榜单标杆需求（前后端贯通）v1](./pages/market-overview/leaderboard-benchmark-requirement-v1.md)
- [榜单标杆技术实施方案 v1（仅方案）](./pages/market-overview/leaderboard-implementation-design-v1.md)
- [榜单 M2 编码前门禁 v1](./pages/market-overview/leaderboard-m2-coding-gate-v1.md)
- [市场总览 Codex 实现提示词基线](./pages/market-overview/implementation-prompt-baseline.md)
- [市场总览 homepage 代码架构设计](./pages/market-overview/implementation-architecture-v1.md)

## 模块开发模板

- [标杆需求模板](./templates/benchmark-requirement-template.md)
- [技术实施方案模板](./templates/implementation-design-template.md)
- [编码前门禁模板](./templates/coding-gate-template.md)

## 维护规则

1. 系统级规则写入 `system/`。
2. 单页面需求、API、验收写入 `pages/<page-key>/`。
3. 不要把系统级规则和页面级细节混在同一个文档。
4. Drive 文档更新后，必须同步更新本地基线，不允许代码实现与本地文档脱节。
5. 本目录文档只服务 `wealth` 工程，不替代仓库根 `docs/` 的数据基座与 ops 文档。
6. 新模块开发必须先按 templates 产出三件套文档（benchmark requirement / implementation design / coding gate），评审通过后才能进入编码。
