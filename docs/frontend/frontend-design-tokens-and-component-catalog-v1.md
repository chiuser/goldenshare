# 前端设计 Tokens 与组件目录 v1

> 角色说明：本文件是“前端设计 token 与组件目录专题文档”。  
> 当前前端强约束与统一门禁请以 [frontend-current-standards.md](/Users/congming/github/goldenshare/docs/frontend/frontend-current-standards.md) 为准。

## 1. 文档目的

本文用于把当前前端的视觉与交互标准收敛成一份可落地的标准库初稿。

本文不是纯设计稿，也不是完整设计系统官网；它服务于当前仓库的实际开发：

- 统一 token
- 统一布局
- 统一高频组件
- 指导新页面与重构页面逐步收敛

---

## 2. 依据来源

本稿综合以下来源整理而成：

1. `docs/architecture/design-principles.md`
2. `docs/frontend/frontend-application-phase1.md`
3. `docs/frontend/frontend-technology-and-component-selection.md`
4. 用户提供的 `design-system.md`
5. 当前前端已有实现与共享组件

说明：

- `design-system.md` 中大量内容可直接吸收，尤其是 token、表格、卡片、空状态、异步任务反馈。
- 对其中过于绝对、与当前实现冲突或仍需产品拍板的部分，本文改写为“默认规范 + 例外条件”。

---

## 3. 当前视觉方向

前端 v1 的默认气质应为：

- 稳重
- 严谨
- 专业
- 信息密度高但不拥挤
- 桌面优先

风格参考采用：

- Bloomberg / Wind 一类金融工作台的秩序感
- Linear / Notion 一类克制的现代信息界面

默认避免：

- 模板站式后台感
- 大面积渐变
- 玻璃拟态
- 紫白默认审美
- 过量装饰动画

---

## 4. 设计原则

### 4.1 信息层级优先于装饰

一屏先回答：

1. 这页最重要的三件事是什么
2. 用户下一步该做什么
3. 哪些异常需要优先处理

重要信息靠：

- 位置
- 字号
- 留白
- 对齐

而不是靠夸张颜色和动效。

### 4.2 先做骨架，再做细节

页面骨架优先级高于组件表皮。

先确定：

- AppShell
- PageHeader
- 筛选区
- 主信息区
- 次信息区
- 详情与反馈路径

### 4.3 一套 token，全局统一

颜色、圆角、间距、边框、阴影、动效都应通过 token 落地。

禁止在普通组件里反复写死：

- 十六进制颜色
- 自定义阴影
- 非标准间距
- 任意圆角

### 4.4 密度靠秩序，不靠堆元素

信息密度不等于视觉密度。

高密度页面依赖：

- 统一行高
- 明确分组
- 稳定对齐
- 克制的状态色

而不是：

- 小字号乱塞
- 多色同时竞争
- 卡片层层嵌套

### 4.5 动效只服务于反馈

只保留：

- hover 颜色过渡
- 抽屉 / Modal 进入退出
- 通知出现消失
- skeleton 节奏

默认不做：

- stagger 动画
- 卡片浮起
- 数字滚动
- 300ms 以上常规动画

---

## 5. Token 体系

## 5.1 色彩角色

色彩拆成 5 组：

1. `surface` / `neutral`
2. `brand`
3. `market-up`
4. `market-down`
5. `semantic`

### 5.1.1 中性灰阶

这是 80% 以上页面的主色体系。

建议亮色 token：

| Token | 建议值 | 用途 |
| --- | --- | --- |
| `neutral.0` | `#FFFFFF` | 卡片、Modal、面板 |
| `neutral.1` | `#F7F8FA` | 页面底色 |
| `neutral.2` | `#F0F2F5` | 表头、hover、次级区 |
| `neutral.3` | `#E5E7EB` | 默认边框 |
| `neutral.4` | `#D1D5DB` | hover 边框、禁用态 |
| `neutral.5` | `#9CA3AF` | placeholder、弱文本 |
| `neutral.6` | `#6B7280` | 次级文本 |
| `neutral.7` | `#4B5563` | 正文 |
| `neutral.8` | `#1F2937` | 标题 |
| `neutral.9` | `#0F172A` | 强对比数字 / 标题 |

默认规则：

- 页面底色不是纯白
- 面板靠背景差和边框分层
- 常规内容面板不依赖阴影抬层

### 5.1.2 品牌色

建议采用深海军蓝系，而不是当前偏紫风格。

建议：

| Token | 建议值 |
| --- | --- |
| `brand.0` | `#EAF1FA` |
| `brand.4` | `#3F73B8` |
| `brand.5` | `#1F5499` |
| `brand.6` | `#154173` |
| `brand.8` | `#0A2547` |

使用原则：

- 一屏内品牌色出现不超过 3 个高注意力位置
- 不给整条 Header 铺品牌色
- 不用品牌色做大面积渐变
- 品牌色主要用于主按钮、选中态、链接和焦点

### 5.1.3 市场涨跌色

默认采用 A 股语义：

- 红涨
- 绿跌

建议：

| Token | 建议值 | 用途 |
| --- | --- | --- |
| `up.0` | `#FDECEC` | 上涨底色 |
| `up.4` | `#E04848` | 上涨主色 |
| `up.6` | `#A82828` | 强上涨 |
| `down.0` | `#E6F4EE` | 下跌底色 |
| `down.4` | `#1F9D6A` | 下跌主色 |
| `down.6` | `#0B6E47` | 强下跌 |
| `flat` | `#6B7280` | 平盘 |

硬规则：

- 涨跌色只用于市场数据
- 不能替代 success / error 语义色

### 5.1.4 系统语义色

建议：

| Token | main | bg |
| --- | --- | --- |
| `info` | `#1F5499` | `#EAF1FA` |
| `success` | `#0F8A5F` | `#E4F4EC` |
| `warning` | `#B07B00` | `#FBEFCC` |
| `error` | `#B42626` | `#FBE9E9` |

### 5.1.5 当前禁用项

默认禁用：

- `violet` / `grape` / `pink` 作为主色
- 页面主视觉渐变
- `backdrop-filter: blur`
- 高饱和荧光色

## 5.2 字体与排版

### 5.2.1 字体栈

建议正文：

```css
-apple-system, BlinkMacSystemFont, "Segoe UI",
"PingFang SC", "Hiragino Sans GB",
"Microsoft YaHei UI", "Microsoft YaHei",
Roboto, "Helvetica Neue", Arial, sans-serif
```

建议等宽：

```css
"JetBrains Mono", "SF Mono", "Roboto Mono",
Menlo, Consolas, monospace
```

### 5.2.2 字号

建议阶梯：

| Token | px | 用途 |
| --- | --- | --- |
| `xs` | 11 | 极小辅助 |
| `sm` | 12 | 标签、说明、表头 |
| `md` | 13 | 表格正文、表单 label |
| `lg` | 14 | 默认正文、按钮 |
| `xl` | 16 | 卡片标题 |
| `h3` | 18 | 副标题 |
| `h2` | 22 | 页面主标题 |
| `h1` | 28 | 大 KPI |

字重规则：

- 默认优先 `400 / 500`
- `600` 只允许少量标题或极强强调
- 不鼓励在 13/14px 中文正文里滥用粗字

### 5.2.3 数字规则

- 默认启用 `tabular-nums`
- 数字列默认右对齐
- 涨跌额和涨跌幅带符号
- 空值统一 `—`
- 日期格式统一 `YYYY-MM-DD` / `YYYY-MM-DD HH:mm`

## 5.3 间距

采用 4px 网格。

建议：

| Token | px |
| --- | --- |
| `xs` | 4 |
| `sm` | 8 |
| `md` | 12 |
| `lg` | 16 |
| `xl` | 20 |
| `2xl` | 24 |
| `3xl` | 32 |

普通页面中出现 `18px`、`22px` 这类游离值，应视为异常。

## 5.4 圆角

建议：

| Token | px | 用途 |
| --- | --- | --- |
| `xs` | 2 | 极小徽标 |
| `sm` | 4 | 输入框、按钮 |
| `md` | 6 | 卡片、面板 |
| `lg` | 8 | 浮层 |

常规 UI 默认不使用 12px 以上大圆角。

## 5.5 阴影

默认策略：

- 普通卡片无阴影
- 浮层才用阴影

建议保留 3 个 token：

- `shadow-popover`
- `shadow-modal`
- `shadow-toast`

## 5.6 边框

建议：

- 默认：`1px solid neutral.3`
- hover：`1px solid neutral.4`
- focus：`brand.5` + 外环

---

## 6. 布局规则

## 6.1 AppShell

默认结构：

- Header：64-72px
- Sidebar：232-280px 展开，64px 折叠
- Content：24px padding

当前建议：

- Header 保留品牌信息，但整体保持克制
- Sidebar 与内容区都走浅色体系
- 内容区在超大屏时设最大宽度并居中

说明：

- 用户提供文档中对 Header 与 Sidebar 的约束很有价值
- 当前已确认：保留品牌头部结构，但不再继续放大装饰性品牌视觉

## 6.2 页面结构

每个正式页面默认包含：

1. `PageHeader`
2. 主操作区 / 筛选区
3. 主内容区
4. 次内容区或详情路径
5. 异常与反馈容器

## 6.3 响应式

当前建议：

- 桌面优先
- 1280 以上为主工作宽度
- 1024-1279 至少可完成主要操作
- 768-1023 允许只读或降级

`< 768` 不作为当前正式支持目标。

---

## 7. 高优先级共享组件目录

以下是 v1 应优先收敛的共享组件。

| 组件 | 级别 | 状态 | 说明 |
| --- | --- | --- | --- |
| `AppShell` | 基础 | 已有基础 | 需要统一 Header / Sidebar 结构 |
| `PageHeader` | 基础 | 已有 | 继续扩展副标题、说明、操作组 |
| `SectionCard` | 基础 | 已有 | 从 `glass-card` 收敛到标准 Panel |
| `StatusBadge` | 基础 | 已有 | 需补齐市场态与系统态分离 |
| `EmptyState` | 基础 | 已有 | 统一空图标、文案、动作 |
| `DateField` | 基础 | 已有 | 继续标准化时间交互 |
| `MonthField` | 基础 | 已有 | 与日期输入对齐 |
| `HelpTip` | 基础 | 已有 | 继续用于渐进式解释 |
| `FilterBar` | 高 | 需新增 | 统一筛选区布局、按钮和折叠策略 |
| `DataTable` / `TableShell` | 高 | 需新增 | 统一表格密度、空态、loading、toolbar |
| `StatCard` | 高 | 已有基础 | 需对齐新 token 和数字规范 |
| `ActionBar` | 中 | 需新增 | 页头 / 抽屉 / Modal 底部动作一致性 |
| `DetailDrawer` | 高 | 需新增 | 统一详情查看与复杂筛选抽屉 |
| `AsyncTaskFeedback` | 中 | 需新增 | 任务提交成功、查看进度、失败重试提示 |
| `Timeline` | 中 | 需新增 | 任务历史、事件追踪统一样式 |
| `TradeDateField` | 中 | 需新增 | A 股交易日输入专用控件 |

---

## 8. 组件级规范

## 8.1 Button

默认变体：

- `filled`：主操作
- `default`：次操作
- `subtle`：行内操作

默认不鼓励：

- 大面积 `light`
- 装饰性 `outline`
- 渐变按钮

说明：

- 用户文档对按钮使用场景的划分很清晰，可直接吸收
- 但 `light` 是否完全禁用，建议先作为“不推荐”，避免与 Mantine 生态过度冲突

## 8.2 Form

默认：

- Label 在上
- 输入控件统一高度
- 帮助文案与错误文案有固定位置
- 日期与时间优先用共享控件

## 8.3 Table

这是最优先收敛的核心组件。

默认规范：

- 提供 `dense / default / comfy` 三档密度
- 表头 sticky
- 数字列右对齐
- 行 hover 仅弱背景
- 状态列用 Badge
- 空值统一 `—`
- 行数大时考虑虚拟滚动

## 8.4 Card / Panel

默认：

- 白底
- 1px 边框
- 6px 圆角
- 无默认阴影

当前 `glass-card` 属于过渡遗留，不应作为未来主标准。

## 8.5 Badge

默认使用：

- 系统状态色
- 市场涨跌色
- 中性默认色

不建议：

- filled 实心 Badge 泛滥
- 同表内太多彩色标签竞争注意力

## 8.6 Empty / Loading / Notification

默认：

- Empty：线性图标 + 一句标题 + 一句说明 + 可选动作
- Loading：优先 skeleton，而非整页大转圈
- Notification：只用于真正需要反馈的用户动作

---

## 9. 数据后台专用呈现规则

## 9.1 市场数据

- 价格值默认中性，不染涨跌色
- 涨跌额与涨跌幅使用市场涨跌色
- 涨停 / 跌停可使用胶囊强调

## 9.2 任务与运行状态

- 主页面先讲“当前风险”和“下一步动作”
- 低层对象作为详情信息出现
- 长任务提交后给出“查看进度”的明确路径

## 9.3 文案

- 默认中文
- 避免 `execution`、`payload` 这类内部词直接上主界面
- 必要时使用“用户词 + 内部词注释”的组合

---

## 10. 从现有实现到新标准的迁移策略

当前已知旧风格包括：

- [frontend/src/app/theme.ts](/Users/congming/github/goldenshare/frontend/src/app/theme.ts) 中的紫色品牌梯度
- [frontend/src/styles.css](/Users/congming/github/goldenshare/frontend/src/styles.css) 中的大面积渐变背景
- `glass-card` 风格

迁移策略：

1. 不一次性大改全站
2. 新页面直接按新标准做
3. 被重做或大幅调整的页面顺手收敛
4. 纯 bugfix 页面不强制整页翻新

---

## 11. 已确认基线

以下事项已确认，可直接作为后续实现前提。

### D1. 视觉切换范围

- 结论：仅新页面和重构页面切入新视觉，旧页面渐进迁移
- 影响：允许边开发边收敛，不要求一次性全站翻新

### D2. 主题模式

- 结论：v1 仅正式支持亮色主题，暗色只保留 token 预留
- 影响：当前主题实现优先把亮色做稳，不在本阶段摊薄到双主题适配

### D3. 宽度策略

- 结论：`1280+` 为正式工作宽度，`1024-1279` 为降级可用区间
- 影响：页面结构优先以桌面宽屏为设计中心，但不能在 `1024-1279` 彻底失效

### D4. 涨跌色偏好

- 结论：平台固定采用红涨绿跌，不提供用户偏好切换
- 影响：市场类 token 与组件直接按 A 股语义落地即可

### D5. Shell 头部结构

- 结论：保留品牌头部结构，但整体风格改为克制化
- 影响：后续重构 Shell 时重点是减装饰、提秩序，而不是完全去品牌化

---

## 12. 下一步建议

文档定稿后，建议优先落地：

1. `theme.ts` 的新 token 结构
2. `SectionCard`、`StatusBadge`、`EmptyState` 的收敛
3. `FilterBar` 与 `TableShell` 两个高频共享组件
4. 选择一个任务中心相关页面做试点重构
