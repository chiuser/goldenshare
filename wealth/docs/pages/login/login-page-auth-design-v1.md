# 财势天下登录页视觉改版与鉴权接入技术方案 v1

更新日期：2026-09-04

状态：LLD 修订至 v1.2，开发与本地自动化检查完成，包含用户批准的登录校验错误脱敏。沿用当前背景、登录默认 10 秒超时、标签显示财势天下与新印章图标、错误提示保留 2.6 秒。未部署，正式验收由用户执行；当前素材不能标为 Retina 原生像素或已完成浏览器视觉验收。

配套文档：[登录页视觉改版低层设计（LLD）v1](./login-page-auth-low-level-design-v1.md)，包含代码落点、桌面适配、token、反馈状态、核心测试和编码门禁。

范围：`wealth` 用户侧登录页、登录请求生命周期和 Wealth 共用浏览器标签名称/图标；不包含运营后台登录页、其他页面正文/顶部栏品牌替换或鉴权体系重构。

本文原为“财势乾坤登录页与鉴权接入方案 v1”，保留原文件路径并原位更新。原方案中的“无品牌区、注册与登录双按钮、旧 Showcase 布局”不再是本次开发依据；已有鉴权实现继续复用，不重新建设。

## 1. 目标与边界

将现有登录页更新为用户确认的浅色山水版本：

1. 使用已选定的无字山水背景，右侧保留山峦与水面，左侧承载登录内容。
2. 品牌区为“左侧方形印章 + 右侧可编辑中文名财势天下”，印章与四个字的**可见字形垂直居中**。
3. 品牌下方依次为用户名输入框、密码输入框、单个通栏登录按钮。
4. 保留用户名密码 HTTP 合同、会话存储、401 刷新与登录后回跳；仅为主动登录增加默认 10 秒期限、取消及迟到响应保护。
5. 复用品牌金、间距、圆角等全局 token；浅色登录专用 token 局部生效，不改变登录后的深色行情终端。
6. Wealth 浏览器标签统一显示“财势天下”，图标使用新印章；登录后保持，不改其他页面正文或运营后台。

本版不做：

- 注册、忘记密码、验证码、社交登录、记住我等新功能。
- 恢复旧稿的注册按钮、右下角状态文案、宣传标语或额外装饰线。
- 修改用户、角色、权限、token 模型、数据库或运行配置；后端只允许第 7 节补充批准的登录校验错误脱敏，不改其他接口；前端 Provider 的登录方法允许按 LLD 扩展取消合同，10 秒默认值集中为构建时常量。
- 修改运营后台 `frontend/` 或全站 TopMarketBar 品牌。
- 购买图片、继续生成或放大背景图、调用另行计费的图像 API、部署或正式验收。本轮按用户指令完成开发；favicon 从指定印章原图裁切缩小，不重新绘制。

**英文名口径**：早期需求包含 `Wealth World`，但用户指定的当前 Figma 主画板已无英文行。本方案按“这版”记录为只显示中文名，不自行恢复英文；Figma 品牌父层仍叫 `Brand / Bilingual`，该历史图层名不代表页面存在英文内容。

## 2. 依据与当前差异

### 2.1 设计依据

主稿：[Goldenshare Web — Login Desktop](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=1314-30317)。

2026-09-04 只读核验对象：

| 对象 | Figma 节点 |
|---|---|
| 页面 `17 Auth - Login Desktop` | `1314:30315` |
| 默认画板 `Login / Desktop / Default / 1920x1080` | `1314:30317` |
| 无字背景 | `1314:30318` |
| 内容区 / 品牌横排 | `1316:81` / `1325:88` |
| 用户指定印章 / 中文名 | `1325:89` / `1316:83` |
| 中文光学对齐容器 | `1330:88` |
| 表单 / 用户名 / 密码 / 登录按钮 | `1316:30302` / `1316:30303` / `1316:30307` / `1316:30312` |
| 组件页 `17.5 Auth - Foundations and Components` | `1314:30316` |
| 输入框 / 登录按钮组件集 | `1315:30313` / `1315:30324` |

系统依据：

- [设计系统基线](../../system/design-system-baseline.md)
- [组件规范基线](../../system/component-guidelines-baseline.md)
- [文档索引与优先级](../../README.md)

本页浅色山水、无 TopMarketBar 的入口形态，是用户本次明确指定的页面级设计边界；不推广为全站浅色主题，不改变现有行情页规范。旧 `wealth/docs/reference/showcase/login-page-v4.2.html` 仅用于追溯，不能覆盖新版 Figma。

### 2.2 开发前已核验的代码事实（历史基线）

本节与 2.3 保留开发前状态用于对比，当前实现及验证见第 9 节和 LLD 10.1，不再将旧背景、双按钮或缺少超时视作现状。

| 事实 | 当前代码 |
|---|---|
| 登录表单、提交、消息、旧品牌无障碍名称 | `wealth/src/features/auth/ui/LoginPage.tsx` |
| 旧背景、定位、输入框与双按钮样式 | `wealth/src/features/auth/ui/LoginPage.css` |
| 登录成功、空值拦截、注册占位、未登录跳转测试 | `wealth/src/features/auth/ui/LoginPage.test.tsx` |
| Provider、登录/退出和认证失效事件 | `wealth/src/features/auth/model/AuthProvider.tsx`、`authEvents.ts` |
| 会话持久化 | `wealth/src/features/auth/model/authStorage.ts` |
| 前端鉴权请求与类型 | `wealth/src/features/auth/api/authApi.ts`、`authTypes.ts` |
| 路由保护与回跳 | `wealth/src/app/routes/WealthRouter.tsx`、`routerState.ts` |
| 行情请求 Bearer 与 401 重试 | `wealth/src/shared/api/wealthApiClient.ts` |
| 全局 token、body 宽度与基础样式 | `wealth/src/styles/design-tokens.css`、`global.css` |
| 后端鉴权接口、schema、访问保护 | `src/app/auth/api/auth.py`、`src/app/auth/schemas/auth.py`、`src/app/auth/dependencies.py` |
| 浏览器标签名称与图标 | `wealth/index.html`、`wealth/public/favicon-wealth.png`；当前未发现 Wealth 页面动态改写 document.title |

本次使用 CodeGraph `codegraph_explore` 辅助定位调用链，并读取上述目标文件核验。检索中出现的运营后台同名 LoginPage/AuthProvider 不属于改动范围。当前仓库并不存在原方案设想的独立 ProtectedRoute、LoginForm、LoginMessage 文件；不要按旧目录树新建第二套实现。

超时变更的消费者审计：LoginPage 是 `auth.login` 唯一调用方，AuthProvider 是 `authApi.login` 唯一调用方；后者已支持 signal，Provider 当前未传。`saveAuthSession` 还服务于 wealthFetch 的刷新分支，所以登录超时不能塞进通用存储或刷新链。详细内部方法合同、竞速和测试见 LLD 第 6.4 节。

### 2.3 开发前实现与目标版

| 项目 | 当前代码 | 本次目标 |
|---|---|---|
| 背景 | `assets/auth/cover.png`，叠加旧渐变遮罩 | 当前 Figma 屏幕比例无字浅色山水；以用户当前电脑的清晰度验收为准 |
| 品牌 | 无独立品牌区；页面可访问名称仍为财势乾坤 | 指定印章 + 财势天下；同步登录页可访问名称 |
| 表单 | 左侧可见“用户名/密码”标签、小输入框 | 无外置可见标签，400 × 56 输入框；保留无障碍标签 |
| 按钮 | 注册 + 登录两列 | 单个 400 × 56 金色登录按钮 |
| 辅助信息 | 右下角“数据接入状态：登录保护已启用” | 移除该显示，不改变真实鉴权配置 |
| 定位 | 旧 `--login-left/top/width` clamp | 第 3 节的新版内容区与桌面定位 |
| 认证恢复 | 读取本地 access token 即视为已登录，后续业务 401 触发刷新 | 保持，不新增启动 `/me` 探测或恢复中状态 |
| 测试 | 仍断言注册按钮存在及旧页面名称 | 视觉改版时同步调整，保留鉴权回归 |
| 登录超时 | 页面/Provider 没有计时期限或取消，authApi 预留 signal | 默认 10 秒，包含响应体解析；超时恢复可操作且拒绝迟到结果 |
| 浏览器标签 | 共用 HTML 标题为财势乾坤，旧 favicon | 财势天下 + 新印章 32/64px 图标；登录与行情路由一致 |

上表是代码静态核验，不代表本次运行过浏览器、远程环境或生产验收。

## 3. 页面结构、尺寸与对齐

### 3.1 1920 × 1080 桌面基准

以下坐标均相对于画板左上角，**不包含 Figma 画布上的 (80, 80) 偏移**。

| 元素 | x / y | 宽 / 高 | 说明 |
|---|---:|---:|---|
| 背景 | 0 / 0 | 1920 / 1080 | 等比例铺满，居中裁切 |
| 登录内容区 | 304 / 264 | 400 / 360 | 透明容器，不加卡片底、边框或阴影 |
| 品牌行 | 304 / 264 | 400 / 88 | 水平排列，垂直居中，间距 24 |
| 印章可见区域 | 304 / 272 | 72 / 72 | 裁掉原图外围大留白，不拉伸 |
| 中文文字容器起点 | 400 / 约 283.744 | 286 / 约 48.512 | 实际字形中心按 3.2 验收 |
| 用户名输入框 | 304 / 400 | 400 / 56 | 品牌行底部至输入框间隔 48 |
| 密码输入框 | 304 / 480 | 400 / 56 | 两输入框之间净间距 24 |
| 登录按钮 | 304 / 568 | 400 / 56 | 密码框底部至按钮净间距 32（24 + 8） |

结构应由品牌横排、表单纵排表达，不分别为每个文字、输入框写页面绝对坐标。Figma 输入组件母版含外置 Label，但主画板实例不显示该层；不能直接照母版 86px 总高恢复标签。

### 3.2 印章与中文名的光学居中

用户要求的是四个字与印章**看起来居中**，不是仅让 88px 行高盒子的中心相同。

当前稿已核验：

- 印章显示为 72 × 72，画板内垂直中心为 `y=308`。
- 中文为 `Noto Serif SC / SemiBold / 600`，字号 64，样式行高 88，字距 10px。
- 中文节点采用 `leadingTrim=CAP_HEIGHT`，并通过专用光学容器校准；容器顶部内距约 1.512px。
- 中文实际渲染范围的垂直中心同为 `y=308`，与印章中心差为 0。中文仍为可编辑文字，不是截图或描边路径。

前端落地必须锁定相同字体后进行可见字形对齐。Figma 的 trim 与 1.512px 内距是设计测量证据，不能不经浏览器验证就照抄为 CSS 偏移。实现应把校准收敛到品牌组件/专用 token，不靠散落的负 margin；以默认桌面截图的可见字形中心偏差不超过 1 CSS px 为验收目标。

### 3.3 背景与桌面适配

1. 背景作为独立装饰层铺满登录页，等比例 `cover`、居中，不平铺、不变形；不把标题或表单烘焙进图片。
2. 移除旧登录页的深色遮罩、输入框磨砂与书法按钮风格。不要对已确认的浅色图片擅自调色。
3. 当前 Figma 只冻结了 1920 × 1080，其他尺寸不能声称已经设计验收。
4. 桌面适配按配套 LLD 第 3 节：保留 400px 内容宽度和 56px 控件高度，内容起点按根宽的 304/1920、视口高的 264/1080 推导，以 24px 安全边距和一行反馈所需高度限位；不整体缩放表单字号和控件。
5. 优先覆盖用户当前电脑：3024 × 1964 物理像素、1512 × 982 逻辑分辨率、DPR 2；浏览器内容区高度应以实际窗口测量为准。原 1920 × 1080 Figma 布局仍保留，其余桌面尺寸列为后续检查，不再以标准 4K 屏验收为本轮前置条件。当前全局 body 最小宽度为 1460px，旧登录根节点最小宽度 1200px 不代表页面已有 1200px 无横向滚动支持。
6. 小视口沿用桌面产品边界，不新增未评审移动版；放大文字或出现错误信息时须可滚动触达表单，不允许 `overflow:hidden` 截掉按钮。
7. 非基准尺寸的具体定位公式已在 LLD 提出，待评审和浏览器验收；不得沿用旧稿 `56vh` 的表单下沉位置，也不声称已有对应 Figma 画板。

## 4. Design token 与字体落地

### 4.1 复用与新增边界

Figma 当前登录专用集合为 `CSQ / Auth / Light / Design Proposal`（`VariableCollectionId:1314:81`，Light 模式）。它是设计值，不等于代码已拥有对应 token。

| 用途 | Figma 值 | 代码落点 |
|---|---|---|
| 登录按钮品牌色 | `Brand/Primary`，#F7C76B | 复用 `--cs-color-brand` |
| placeholder | `Text/Muted`，#64748B | 复用 `--cs-color-text-muted` |
| 间距 | 8 / 16 / 24px | 复用 `--cs-space-8/16/24` |
| 控件圆角 | `Radius/Card`，10px | 复用 `--cs-radius-card` |
| 中文、输入内容、按钮文字 | `Auth/Text/Primary`，#17324D | 已新增 `--cs-auth-color-text-primary` |
| 输入框底色 | `Auth/Surface/Field`，#FFFFFF | 已新增 `--cs-auth-color-surface-field` |
| 默认边框 | `Auth/Border/Default`，#8391A3 | 已新增 `--cs-auth-color-border-default` |
| focus 边框 | `Auth/Border/Focus`，#17324D | 已新增 `--cs-auth-color-border-focus` |
| 错误文字/边框 | `Auth/Text/Error`，#B42318 | 已新增 `--cs-auth-color-error`；不是行情下跌色 |
| 控件高 / 表单宽 / 分区间距 | 56 / 400 / 48px | 已新增 `--cs-auth-control-height`、`--cs-auth-form-width`、`--cs-auth-section-gap` |
| 边框宽 | `Border/DefaultWidth`，1px | 已新增 `--cs-auth-border-width` |

新增 token 已统一放在 `wealth/src/styles/design-tokens.css` 的登录专用作用域中，消费者限登录页及其专用组件；全局深色值未改。品牌光学校准值为 -3px，其他固定尺寸见 LLD 第 5 节。旧 `--login-*` / `--csq-*` 登录规则已清零。

这些是构建时样式值，不是新的 env、Settings、数据库或运营配置；生效方式是前端构建与发布。本次不新增运行开关、不改配置依赖。72px 印章、88px 品牌行、64px 字号、字距与光学校准值也应在 LLD 中统一映射为登录专用 token。

### 4.2 字体与控件

- 品牌中文：Noto Serif SC SemiBold，64px，600，字距 10px；字形居中按 3.2。
- 输入内容与 placeholder：Noto Sans SC Regular，16px / 24px，字距 0。
- 按钮：Noto Sans SC Medium，16px / 24px，字距 3px。
- 输入框白底、1px 边框、10px 圆角，左右内距 16px；不加旧金色描边和重阴影。
- 默认按钮金底深蓝字；不使用旧深蓝渐变按钮。

上述字体已按 Google Fonts 固定 commit 归档为独立 family 的 WOFF2 子集，并随附 SIL OFL 1.1 许可；三字体合计36,068 bytes。全站正文字体未修改。版本、hash、子集字符、派生方式和字形中心校准证据见[素材 README](../../../src/assets/auth/README.md)；不能用系统回退截图证明高保真通过。

## 5. 素材合同与当前屏幕清晰度验收

### 5.1 已选定素材

| 素材 | 当前真实状态 | 标识与使用要求 |
|---|---|---|
| 当前屏幕比例无字山水背景 | **1556 × 1011**，PNG 1,549,096 bytes（约 1.55 MB）；已替换 Figma，用户已决定沿用 | image hash `d16b6c5203d55bf37c683f0275925fd0142de187`；归档为 `wealth/src/assets/auth/wealth-world-login-bg-screen.png` |
| 原无字浅色山水背景（历史参考） | **1672 × 941**；不再是当前 Figma 背景 | 原 image hash `9eb61145003413703ec19e2e1dd4a4591ffdee67`；素材生成阶段以它为编辑参照保留风格 |
| 用户上传方形印章 | **1254 × 1254** 位图，含白底及外围留白 | image hash `9f6c3c930e4998f5c515d72e844d332ead6b586e`；以该上传图为准，不替换为其他生成稿 |

印章按用户指定的隶书印章造型保留原图：右上财、右下势、左上天、左下下；选定图片中的字形为“財 / 勢 / 天 / 下”，不得以统一简体为由重新生成或修改图中文字。旁边的品牌文字使用简体“财势天下”。

当前 Figma 的印章从原图 `x=154, y=150, width=948, height=948` 区域取方形裁切，展示为 72 × 72，并采用 `MULTIPLY` 混合融入浅色背景。该位图**不是透明 PNG，也不是矢量 Logo**。前端应复现相同有效裁切和融合效果；如改为透明加工稿，必须重新核验笔画、金线、边缘及与背景融合后的视觉一致性。

### 5.2 屏幕目标与生成结果

2026-09-04 用户明确暂停标准 4K，要求只匹配当前电脑并直接生成、替换。因此原 **3840 × 2160、16:9** 硬门禁不再适用，不再为追求 4K 反复生成或切换付费 API。

设备只读检测结果为 Apple M3 Max 内置 Retina 屏，物理像素 **3024 × 1964**，逻辑分辨率 **1512 × 982**。素材生成阶段向内置工具请求 3024 × 1964，实际只输出 **1556 × 1011**，比例与屏幕近似一致，但像素未达到请求值；满屏仍需约 1.94 倍放大。**匹配比例不等于满足 Retina 原生清晰度，不能将当前素材标成原生 3K 或无损清晰度已通过。**

已执行：使用一次内置图像编辑、替换 Figma 背景节点 `1314:30318`、保留画板 1920 × 1080 及所有前景元素位置。背景采用等比例 FILL；屏幕比例素材在该 16:9 画板上会裁切上下，未拉伸图片。印章、中文名、输入框、按钮未重排，中文与印章实际渲染中心差复核仍为 0。

用户随后明确“就先这样”，因此本素材现已选定为本版开发输入，不再等待更高像素输出。后续检查针对实际运行页面的显示和加载，不将当前像素不足作为再次生成的理由。

后续清晰度与加载验收：

1. 在用户实际浏览器窗口、100% 缩放和 DPR 2 下查看山脊、云雾渐变、水面；截图缩略图或 Figma 画布缩放不能替代此项。
2. 沿用当前素材推进已评审设计；实际页面仍需本地/用户验收。若运行效果不通过，报告尺寸限制并另获处理指令，不自动重试生成或购买服务。
3. 不做伪装成高清的简单尺寸放大。本轮没有超分辨率处理或额外插值导出，文件保留生成工具的实际输出。
4. 将资源来源、尺寸、体积和校验值归档；运行时不引用临时目录、`.codex/generated_images` 或 Figma 临时导出链接。
5. 首版直接引用当前 PNG，不新增 WebP、多分辨率资源或格式选择开关。后续如另行要求优化，再对同一源图实测压缩效果；表单不得等待背景下载完成才可使用。

素材落点：

- `wealth/src/assets/auth/wealth-world-login-bg-screen.png`：已归档，实际 1556 × 1011；Figma 与 LoginPage 已使用，原字节不变。
- `wealth/src/assets/auth/README.md`：已记录来源、尺寸、生成方式、完整提示词和校验值。
- `wealth/src/assets/auth/wealth-world-seal.png`：已原样归档的1254×1254印章，按 LLD 以 CSS 裁切，未加工字形。
- `wealth/src/assets/auth/wealth-world-seal-favicon-32.png`、`wealth-world-seal-favicon-64.png`：已从相同有效窗口派生32/64px图标；合计9281 bytes，不重绘、不加字。

旧 `cover.png` 在全仓确认无运行消费者后已移除，可从 Git 历史恢复。`icon22.png` 和旧 `favicon-wealth.png` 文件保留；HTML 已只引用新印章两图标，由 Vite 生成带 hash URL。没有双版本皮肤或开关。

## 6. 交互与可访问性

### 6.1 状态设计

| 状态 | 展示与行为 |
|---|---|
| 默认 | 两个 placeholder、单个登录按钮；无英文行、外置可见标签或错误文案 |
| 输入框 focus | 深蓝焦点边框；用户名与密码均可键盘进入 |
| 已输入 | 深蓝正文；密码保持掩码，不新增显示密码功能 |
| 输入错误 | 浅色主题错误色 + 明确文字；不只用颜色提示 |
| 按钮 hover | 金底保留、增加深蓝边界反馈，不改变按钮尺寸 |
| 按钮 pressed | 深蓝底、品牌金文字 |
| 提交中 | “登录中…”；使用现有提交状态禁止重复请求，不改变按钮位置 |
| 登录成功 | 由已有认证状态触发回跳，不新增成功中间页 |
| 登录失败 | 保持当前表单，显示可读错误；不显示密码、token 或原始技术堆栈 |
| 登录超时 | 发起主动登录后默认 10 秒仍未完成则取消并提示“登录超时，请重试”；恢复按钮，输入保留，允许手动重试 |

Figma 已有 Input 的 Default / Focused / Filled / Error 及 Button 的 Default / Hover / Pressed / Loading / Disabled 变体。Loading 不透明度约 0.72，Disabled 约 0.4。组件有 Disabled 变体不意味着空输入时必须禁用登录；当前空值点击后提示的行为保留。

错误版式在 LLD 第 6 节具体化：按钮下方 8px 的单一反馈区，默认不显示文字、预留 20px 行高，长消息向下换行；品牌、输入框与按钮起点不跳动。用户已确认沿用 2600ms 自动消失，包含超时提示；同样消息再次发生重新计时。本地空字段使用错误边框与无障碍关联；API 账户级错误和客户端超时不猜测具体错误字段。该布局由 LLD 补齐，不误写成 Figma 已有完整错误页面。

### 6.2 必须保留的可访问性

1. 使用真实 `form`、`input`、`button`，Enter 提交，Tab 顺序为用户名、密码、登录。
2. 外置标签虽然不可见，仍用视觉隐藏的 label 或 `aria-label` 提供“用户名”“密码”；placeholder 不是唯一可访问名称。
3. 保留 `autocomplete="username"` 与 `autocomplete="current-password"`。
4. 登录页可访问名称更新为“财势天下登录页”；可见中文名保持文本节点。印章与背景为装饰时避免屏幕阅读器重复读品牌。
5. 错误反馈保留可感知的 live region；字段错误通过 `aria-invalid` / `aria-describedby` 关联。键盘焦点不能被无条件去掉。
6. 登录页局部声明浅色控件语义，避免继承全局 dark color-scheme 导致原生输入/自动填充样式不一致；不得改变行情页主题。
7. 图片或字体加载失败不能阻止填写和登录；禁止以图片加载成功作为认证提交条件。

## 7. 复用鉴权 HTTP 合同，补齐登录期限

### 7.1 调用链与接口

`LoginPage → AuthProvider.login → authApi.login → /api/v1/auth/login → saveAuthSession → WealthRouter 回跳`。

| 接口 | 当前合同与用途 | 本次处理 |
|---|---|---|
| `POST /api/v1/auth/login` | JSON `username`（1–64）、`password`（1–256）；返回 TokenResponse | 原样复用 |
| `POST /api/v1/auth/refresh` | `refresh_token`（8–512）；返回 TokenResponse | 保留业务请求 401 后刷新 |
| `GET /api/v1/auth/me` | 前端已有调用函数；当前 AuthProvider 初始化不调用它 | 不新增启动请求 |
| `POST /api/v1/auth/logout` | 可选 `refresh_token`，当前退出先清本地再尝试服务端 | 保持 |
| 注册及找回密码接口 | 后端已有其他账户能力 | 本页不接入、不展示入口 |

TokenResponse 保持 `token`、可空 `refresh_token`、可空 `access_token_expires_at`、`username`、`is_admin`、可空 `display_name`。接口返回错误仍由 `AuthApiError` 读取 `code/message`，非 JSON 错误保留 HTTP fallback；不新增登录错误码或另造错误信封。

**补充批准的安全修正**：审计证实原校验错误 message 会包含超长密码等原始输入。用户批准仅对 POST `/api/v1/auth/login` 的 RequestValidationError 脱敏：保持 HTTP 422、`validation_error` 与原 request_id，消息固定为“登录参数校验失败，请检查用户名和密码”，不回传原始输入或调试结构。Wealth、运营登录页及 platform-check 共享该接口，都会得到安全消息，但其代码无需变化；不修改其他接口、成功登录、refresh/logout。实现白名单增加 `src/app/exceptions/web.py`；审计证据、严格路由范围和正反测试详见 LLD 6.5。本补充替代本文其余概括性“后端 HTTP 合同完全不变”表述中的登录校验消息部分。

当前提交前会对用户名和密码执行 trim，再做空值检查；本次视觉改版不顺带改变凭据归一化语义。

客户端超时使用浏览器标准 TimeoutError 映射“登录超时，请重试”，不是后端新错误码，不伪造 HTTP 状态，不新增 ITI 或其他业务异常注册。

### 7.2 存储、刷新与路由

- localStorage key 保持 `wealth.auth.access-token`、`wealth.auth.refresh-token`、`wealth.auth.expires-at`、`wealth.auth.username`、`wealth.auth.display-name`。不存明文密码，不复用运营后台存储命名。
- AuthProvider 从本地 session 初始化；access token 存在即进入前端 authenticated 状态，不是已向服务器验证 token 有效。
- `wealthFetch` 在 Authorization 注入 Bearer；收到 401 时，有 refresh token 则尝试一次刷新并重放一次。缺 refresh token、刷新失败或重放仍 401 时清会话并发认证失效事件；不引入循环重试。
- 入口仍为 `/wealth/login`，默认回跳 `/wealth/market/overview`。已有 `/login` 识别不在此任务增删范围。
- `readRedirectPath` 当前接受以单个 `/` 开头的值，缺省、非 `/` 开头或以 `//` 开头时回到默认页。本次不声称已有完整的 Wealth 路由白名单，也不扩展回跳规则。
- 行情端真实访问保护由后端 `require_quote_access` 和 `QUOTE_API_AUTH_REQUIRED` 决定，不以页面角落文案为依据。当前 Settings 默认 False；若环境要求登录后访问行情，必须单独核验运行值为 True。本次未核验生产运行值、不修改配置，也不新增 `quote.read` 权限检查。

### 7.3 用户拍板：主动登录默认 10 秒

1. 唯一默认值为 `wealth/src/features/auth/model/loginPolicy.ts` 的 `DEFAULT_LOGIN_TIMEOUT_MS=10000`。本版为构建时常量，无 env、Settings、数据库、运营输入或每次请求覆盖参数；配置来源、消费者、生效方式和测试已在 LLD 第 5 节列清。
2. AuthProvider.login 负责期限和会话提交，LoginPage 为每次提交提供取消 signal。计时包含 fetch 和响应体 JSON 解析；不是背景/字体加载计时，也不影响 refresh/logout/行情请求。
3. 达到期限时真正 abort，同时用竞速使调用及时失败；保存会话前再次检查截止时刻和取消状态，防止 timer 调度延迟或不遵守 abort 的迟到响应登录成功。
4. 超时后保留输入、恢复登录按钮，显示固定文案 2.6 秒，不自动重试。新尝试与旧尝试隔离；卸载取消不弹超时错误。
5. 超时不代表服务端事务回滚，服务端可能已签发会话；本次只阻止客户端接收迟到结果，不新增服务端撤销或回收接口。
6. 原“不新增登录超时”的例外 E02 撤销。10 秒、9999/10000ms 边界、取消、迟到成功和重试须有自动化与真实网络故障注入验收。

### 7.4 用户拍板：浏览器标签名称与印章图标

在 `wealth/index.html` 设置唯一 title 为“财势天下”，并引用新印章 32/64px PNG favicon。图标使用原印章同一有效裁切，保留字形/金线/底色，交给 Vite 生成带 hash 的资源 URL；不继续引用旧图标、不下载原始大印章作为 favicon。共用入口设置覆盖登录和登录后的 Wealth 页面，不增加路由切换时的 head 修改/恢复，不涉及运营后台、其他页面正文或 TopMarketBar 品牌。构建产物与实际浏览器图标均需检查。

## 8. 实施范围与分步交付

### 8.1 实施代码落点

| 文件或目录 | 后续工作 | 边界 |
|---|---|---|
| `wealth/src/features/auth/ui/LoginPage.tsx` | 品牌组合、单按钮、隐藏标签、取消 signal/尝试 ID 与超时反馈 | props 与回跳接口不变；同步更新内部 auth.login 调用 |
| `wealth/src/features/auth/model/AuthProvider.tsx`、`loginPolicy.ts` | 主动登录默认 10 秒、取消及提交会话前检查 | 不改 HTTP/storage/refresh/logout 合同，不增加运行配置 |
| `wealth/index.html`、`wealth/src/assets/auth/wealth-world-seal-favicon-*.png` | 标签 title 与新印章图标 | 共用标签元信息改变；其他页面正文与运营后台不变 |
| `wealth/src/features/auth/ui/LoginPage.css` | 替换旧布局、光学居中、浅色控件与桌面适配 | 清除本页旧视觉规则，不叠加第二套登录皮肤 |
| `wealth/src/styles/design-tokens.css` | 集中加入登录作用域 token | 不覆写深色行情主题，不更改全局字体 |
| `wealth/src/assets/auth/` | 背景、印章、字体及来源说明 | 不依赖临时绝对路径 |
| `wealth/src/features/auth/ui/LoginPage.test.tsx` | 新视觉结构断言、移除注册存在断言、保留鉴权测试 | 不把文档更新当成测试已修改 |
| `src/app/exceptions/web.py`、`tests/web/test_auth_api.py` | 登录校验错误脱敏及真实路由回归 | 仅获准的 POST 登录校验消息，不改其他接口 |
| 本方案、配套 LLD、两级文档索引、素材 README | 方案/索引与实际阶段对齐 | 同步开发证据，不虚报部署和正式验收 |

品牌组件放在 auth feature 内，不抽到 shared，不引入新 UI 框架。后端仅修改获准的登录校验错误呈现；数据库、依赖矩阵、Ops/TaskRun 均无改动。

### 8.2 阶段与后续步骤

素材、字体、登录 UI、10秒期限、标签资源、获准的安全422及自动化检查已完成。未改 Figma，未重新生成背景。按用户最新指令，本轮不启动服务、不部署、不进行正式验收；用户部署后执行 LLD V01～V06/R01～R04，重点核对当前屏幕清晰度、键盘/自动填充、真实登录/回跳、刷新和超时重试，再闭环状态。

### 8.3 跨模块八原则映射

通用清单 2.1～2.18 的完整编码门禁和例外在 LLD 第 9 节；本技术方案的八条原则落点如下，均不扩大本页业务范围。

| 原则 | 本方案口径 | 验证落点（LLD） |
|---|---|---|
| 事实源单一 | 认证复用原 API；视觉使用当前 Figma 与本版素材 | U06/U07、A01、R01 |
| 契约先行 | 第7节成功字段/存储/回跳不变；login增加必填signal；仅登录校验message按批准规则脱敏 | U08/U11、A01～A03 |
| 配置一致 | 第 4 节局部 token 与 7.3 的单一超时常量；无新增 runtime 配置 | U10/U11、V04 |
| 默认显式 | 第 6～7 节空值、pending、失败与回跳 | U02～U09、V05 |
| 排序筛选确定 | 无业务数据排序/筛选；输入 trim 与键盘顺序明确 | U02/U06、V03 |
| 性能预算前置 | 原背景 1.55MB；另核印章/favicon/字体；主动登录默认 10 秒，撤销 E02 | U11、V01/V05/V06、R01/R04 |
| 异常标准化 | 原 AuthApiError/code/message；无新 ITI 或其他模块码 | U04/U08、A02/R02；例外 E04 |
| 用户可见结果 | 单测不替代真实登录、反馈、回跳、当前电脑视觉 | A/R/V 三类独立证据 |

## 9. 验收清单与当前结果

### 9.1 开发完成时必须验证

- [ ] 1920 × 1080 布局符合第 3 节；透明内容区，无旧遮罩、卡片或双按钮残留。
- [ ] 指定印章未被替换，文字顺序与裁切正确；中文可选取，实际字形与印章中心偏差 ≤1 CSS px。
- [ ] 无 `Wealth World`、注册、角落状态或外置可见字段标签；无障碍 label 完整。
- [ ] 输入框/按钮各 400 × 56，字体、圆角、间距、默认/hover/pressed/focus 与 Figma 一致。
- [ ] 用户当前电脑上背景的山体、渐变和水面清晰度已确认；记录真实尺寸、来源、处理方式、体积、校验值，不将小图或简单放大图标成原生高分辨率。
- [ ] 目标桌面尺寸、DPR 1/2、浏览器缩放与自动填充检查通过；图片/字体加载失败不阻塞登录。
- [ ] 空值不发请求；成功保存原 key 并回跳；失败反馈可读；提交中不重复发送；密码继续掩码。
- [ ] 主动登录默认 10 秒，覆盖响应体解析；到点取消并提示“登录超时，请重试”2.6 秒；迟到成功不写会话、不回跳，不污染手动新尝试。
- [ ] 浏览器标签显示财势天下与指定印章图标；直达/刷新/登录后保持；构建 URL 正确、无旧图标候选。
- [ ] 未登录访问受保护页面可返回登录；已有 session 与 401 刷新、刷新失败行为不回归。
- [ ] 不发送注册请求，不新增 `/me` 启动请求，不把 token/密码放入 URL、日志或截图。
- [ ] token 只在登录域生效，登录后的行情页与运营后台外观不变。
- [ ] 单测、构建、真实浏览器检查分别留存证据，不能用单测通过替代视觉验收。

现有可执行前端命令（在 `wealth/` 下）：

```bash
npm run test -- src/features/auth/ui/LoginPage.test.tsx src/app/routes/routerState.test.ts
npm run build
```

自动化文件、断言和硬口径对账已补齐，见 LLD 第 8 节及 10.1；上述浏览器清单仍由用户正式验收，不以单测替代。

### 9.2 本次开发结果

| 检查 | 结果 |
|---|---|
| 原技术方案 | 已找到，原位更新，未新增重复方案 |
| Figma 主画板、控件变体、Auth Light token | 已只读核验 |
| 中文与印章光学中心 | 已按真实字体校准统一-3px；Chromium/Chrome DPR1/2隔离测量差≤0.5 CSS px；非正式V02验收 |
| 图片像素 | 当前背景 1556 × 1011，约 1.55 MB；印章 1254 × 1254；标准 4K 已按用户要求暂停 |
| 当前登录代码、存储、刷新、路由、后端 schema | 已静态核验并区分现状与目标 |
| 文档检查 | 原方案、LLD、两级索引、素材README同步；check_docs_integrity三项、git diff --check通过，不替代功能或视觉验收 |
| Figma 替换与预览检查 | 仅替换背景节点；已检查主画板截图、前景尺寸及品牌中心差为 0 |
| 开发验证 | 前端typecheck通过，99文件/712测试通过，build通过；后端认证30测试、架构边界16测试通过；均非生产验收 |
| LLD 对账 | v1.2含15条硬口径、U01～U12与A01～A03开发证据；V/R明确待用户执行 |
| 三项拍板 | 登录默认 10 秒、浏览器标签财势天下与新印章、错误提示 2.6 秒；旧免超时/不改标签口径已撤销 |
| 当前素材决定 | 用户已决定沿用现图，不再等待 4K；运行页面验收仍单独进行 |
| 安全修正 | 仅登录校验失败message脱敏，保留422/validation_error/request_id；其他接口和成功/刷新/注销不变 |
| 待完成 | 用户部署与正式V/R验收；本轮未提交、未推送、未发布 |

主要风险是把屏幕比例匹配误当作 Retina 原生清晰度通过、系统字体回退导致光学对齐漂移，以及直接套用组件母版而恢复外置标签。上述三项必须按本方案验收，不以“画板尺寸正确”或“盒子 align-items:center”代替实际验证。
