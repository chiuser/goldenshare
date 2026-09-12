# 前端质量门禁与截图回归流程

更新时间：2026-09-12；合并旧质量矩阵和 smoke 说明。适用 frontend，不替代 Wealth 自身规则。
本文依据当前脚本、配置和测试做静态校准，不宣称已重跑 CI 或浏览器。视觉/组件约束见[前端基线](/Users/congming/github/goldenshare/docs/frontend/frontend-current-standards.md)。

## 1. 命令与执行边界

命令在 frontend 目录执行，事实源为 [package.json](/Users/congming/github/goldenshare/frontend/package.json)。

| 命令 | 当前作用 |
| --- | --- |
| npm run typecheck | tsc --noEmit |
| npm run check:rules | 静态规则扫描 |
| npm run test | vitest run |
| npm run build | tsc -b，再 vite build |
| npm run test:smoke | build 后执行 test:smoke:ci |
| npm run test:smoke:ci | 直接运行 Playwright，不替你 build |
| npm run test:smoke:update | build 后更新截图；只在 §3 的前提满足时使用 |

本机复用已有依赖和浏览器；缺少套件先申请安装，不能把 CI 的安装步骤当成本机授权。网络/端口权限按当前工具模式及根 AGENTS 判断，不能默认请求不支持的提权。

## 2. 改动类型与最小验证

| 改动类型 | 最小验证 |
| --- | --- |
| 文档 / AGENTS 仅变更 | `python3 scripts/check_docs_integrity.py` |
| 前端 workflow / 门禁脚本 / `package.json` 脚本 | `npm run typecheck` + `npm run check:rules` + `npm run test` + `npm run build` + 对应 smoke 命令 |
| `shared/ui/**` 普通组件 | `npm run typecheck` + `npm run test` + `npm run build` |
| `shared/ui/**` 高可见组件 | `npm run typecheck` + `npm run check:rules` + `npm run test` + `npm run build` + `npm run test:smoke` |
| `pages/**` 非关键流程小改动 | `npm run typecheck` + `npm run test` + `npm run build` |
| 任务中心试点页 / 高可见页面 | `npm run typecheck` + `npm run check:rules` + `npm run test` + `npm run build` + `npm run test:smoke` |
| `features/trade-calendar/**` 或影响试点页的 `shared/api/**` | `npm run typecheck` + `npm run test` + `npm run build` + `npm run test:smoke` |
| smoke / visual gate 本身变更 | `npm run typecheck` + `npm run check:rules` + `npm run test` + `npm run build` + `npm run test:smoke`；仅满足下文更新条件时执行 update 后再跑 smoke |

高可见组件包括 PageHeader、SectionCard、StatCard、StatusBadge、AlertBar、DetailDrawer、TableShell、DataTable、TradeDateField、ActivityTimeline。任务中心包括记录、手动维护、自动任务、详情和默认入口/tab 切换；多类改动取更高档位。先确认 loading/empty/error/loaded/提交成败，不只验证有数据主路径。

普通组件也须验证 props 消费者；高可见组件额外评估组件目录、Showcase 和受影响截图。相邻页面若无现成 smoke，明确页测与定向验证缺口，不把“没有基线”当免验理由。CI 命令不证明实际覆盖所有分支。

## 3. 截图更新纪律

只允许有意的视觉、结构、覆盖场景或固定 mock 基线变化触发更新。功能断言失败、元素未加载、随机时间/后端噪音、非预期副作用，都不能靠刷新截图让 CI 通过。

操作顺序：先解释差异与预期，再更新必要基线，最后重新执行普通 test:smoke。门禁脚本本身变化不自动授权刷新截图。交付需写明更新理由、页面/状态、共享组件/壳影响、实际命令及未覆盖项。

## 4. 当前 smoke 配置和覆盖

[Playwright 配置](/Users/congming/github/goldenshare/frontend/playwright.config.ts)：e2e 目录、1440×1200、亮色、zh-CN、Asia/Shanghai；截图关闭动画、隐藏光标、CSS scale，maxDiffPixelRatio=0.01。CI 禁止 only、失败重试 1 次，本地不重试；首次重试记录 trace，失败保留截图/视频。preview 使用 127.0.0.1:4173 和 strictPort，健康检查 /app/login；本地可复用现存服务，CI 不复用，需防止本地误用旧构建。

[spec](/Users/congming/github/goldenshare/frontend/e2e/smoke-visual.spec.ts)当前静态声明 13 个测试，其中 11 处 toHaveScreenshot；测试条数、截图断言数、页面数不是同一指标：

- 登录、Overview、任务记录、默认入口/tab 切换、手动引导和提交。
- 自动任务列表/详情/编辑及 margin-detail 来源就绪合同。
- 任务详情与分页季度进度轮询、审查指数与板块页。
- SW2021 手动动作的快照/日期合同。

使用固定 mock 隔离后端波动，截图不证明生产 API、真实数据或全部边界状态正确。平台检查、用户概览、账号、数据源/数据集详情不在这份 spec 的直接覆盖清单中；新增覆盖按风险选稳定代表模式，不平均铺满全站。

原矩阵的 32/34 个测试文件、67 个用例、11 基线/9 页面是历史盘点，不能作为当前覆盖承诺。task-auto 已有独立[页测](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-task-auto-tab.test.tsx)。SectionCard、StatCard、EmptyState 未发现同名独立测试，不能等同于完全无间接测试；PriceText/ChangeText 有单测也不能写成已获截图双层保护。

## 5. 自动规则与人工 review

[check-rules.mjs](/Users/congming/github/goldenshare/frontend/scripts/check-rules.mjs)扫描 src 下 ts/tsx/css，排除 .test.ts/.test.tsx，当前六类规则：

1. week_friday：同一行或上一行允许 WEEK_FRIDAY_NATURAL_ANCHOR_OK 注释说明。
2. pages 中 glass-card；白名单仍为 Overview、source、user-overview。
3. violet/grape/pink/magenta；白名单仍为 review-board。
4. 页面合成 freshness 健康状态的指定旧符号。
5. 页面自行拼装 Raw 表名的指定旧符号。
6. 页面推断卡片来源、canonical key 或合并旧快照的指定旧符号。

白名单是按文件放行，不限制该文件新增命中数量；规则是指定文本匹配，不是全面语义分析。当前 Overview/user/source 不直接写 glass-card，不能因白名单尚在而宣称残留尚在。规则失败已有独立 CI step，旧“尚未自动化、无细分反馈”不再适用。

数字列对齐/tabular-nums、完整状态矩阵、共享组件是否需要加 smoke、截图更新理由仍需人工判断；通过文本规则不能替代这些审计。

## 6. CI 与失败排查

[Frontend Quality Gate](/Users/congming/github/goldenshare/.github/workflows/frontend-quality-gate.yml)在命中 frontend/** 或自身文件的 PR、main/dev-interface push，以及手动触发时运行；纯 docs 改动不自动触发。macos-latest、Node20，先 npm ci 和 Chromium 安装，再 typecheck → check:rules → test → build → smoke:ci，最后无论成败上传 playwright-report/test-results。

CI 使用 PLAYWRIGHT_BROWSERS_PATH=0，本地脚本未设置时默认 .playwright；不能把两者缓存路径混用。

失败按上述次序复现：类型/引用 → 规则命中（不先扩白名单）→ 组件契约或页面断言 → 构建 → smoke 断言/截图/preview。先确保依赖与浏览器可用，不擅自安装或放宽容差，不用更新截图掩盖逻辑错误。

## 7. 交付与扩面

交付说明包含改动类型、执行命令、测试/浏览器结果、截图是否更新及原因、未覆盖风险。未执行的检查明确标注，不凭旧 Phase5/6 验收宣称当前通过。

后续优先关键流程的空态/错误态和高频组件缺口；测试存在不等于用例全面，smoke 不替代专项验收。旧门禁矩阵和 smoke 文档已并入本文，不另立重复命令表或旧阶段待办。
