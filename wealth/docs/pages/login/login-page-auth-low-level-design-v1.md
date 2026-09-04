# 财势天下登录页视觉改版低层设计（LLD）v1

更新日期：2026-09-04

状态：**修订 v1.2，开发与本地自动化检查完成；包含用户批准的登录校验错误脱敏。未部署、未完成正式验收，由用户执行。**

上位方案：[登录页视觉改版与鉴权接入技术方案 v1](./login-page-auth-design-v1.md)。视觉基准：[Figma 默认登录页](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=1314-30317)。

用户最新决定为“就先这样”，本版沿用已经替换进 Figma 的 **1556 × 1011 PNG**，不再生成图片、不等待 4K 或屏幕原生像素版本。接受当前素材作为开发输入，不等于已经完成运行页面的清晰度验收。

2026-09-04 补充拍板：登录请求默认 **10 秒超时**；浏览器标签显示“财势天下”，favicon 使用指定新印章；错误提示仍 **2.6 秒自动消失**。以下实施口径已同步，原“不新增登录超时、不改标签名称/图标”不再有效。

## 1. 范围与依据

本次只改 `wealth` 登录页的视觉和必要的表单呈现：无字浅色山水、指定印章、简体“财势天下”、用户名、密码、单个金色登录按钮。当前 Figma 没有英文行；不恢复 `Wealth World`、外置可见标签、注册入口、角落状态、标语、装饰线或其他账户功能。

登录成功合同、会话存储 key、401 刷新、路由保护、后端权限、数据库、运行配置或行情页主题不变；不改运营后台 `frontend/`。经用户补充批准，仅扩展后端登录校验错误的安全呈现，详见 6.5。允许调整前端 Provider 的登录方法以落实 10 秒期限、取消和迟到响应防护。浏览器标签名称与 favicon 在 Wealth 共用 `index.html` 统一更新，登录后也保持“财势天下”和新印章；不扩展为其他页面正文、TopMarketBar 或运营后台改名。

### 1.1 开发前事实与目标设计（历史基线）

下表保留开工前审计结果，不再代表开发后的代码状态；当前完成项和剩余验收见第 10 节。

| 证据 | 2026-09-04 核验结果 | 本文用途 |
|---|---|---|
| Figma `1314:30317` 元数据 | 背景名为 Screen ratio / 1556x1011；内容区仍为 304/264、400×360；印章 72×72；两个输入框和一个按钮 | 冻结主画板结构，不重新设计 |
| 技术方案第 3～6 节 | 字体、颜色、变体、印章裁切及光学居中的已记录测量 | 复用视觉参数；浏览器结果另验 |
| `LoginPage.tsx/.css` | 仍引用旧 `cover.png`，显示外置标签、注册按钮和右下角状态；消息 2600ms 清除 | 本次待替换对象 |
| `LoginPage.test.tsx` | 只有注册占位、空值、成功存储回跳、未登录跳转四类测试 | 不能宣称已覆盖重复提交、刷新或视觉 |
| `authApi.ts`、`authTypes.ts`、后端 auth 路由/schema | 登录、刷新、退出及 TokenResponse 已存在 | 原合同复用，无新 DTO |
| `AuthProvider.tsx`、`authStorage.ts`、`wealthApiClient.ts`、路由 | 本地 session 初始化；业务 401 后刷新一次并重放一次 | 不借视觉改版重写认证 |
| `AuthProvider.login` 与 `authApi.login` | Provider 当前只接 body，未传 signal；API 函数已支持 signal；当前无登录超时 | 新增仅限登录的期限与取消；不改变 refresh/logout 请求策略 |
| `wealth/index.html`、Wealth 全量源码引用检索 | 标签标题为财势乾坤，唯一显式 favicon 为 `/wealth/favicon-wealth.png`；未发现页面动态设置 document.title | 在共用 HTML 入口更新，不给登录组件增加 head 修改/恢复副作用 |
| `main.tsx`、`design-tokens.css`、`global.css`、`vite.config.ts` | 全局深色，body 最小宽 1460；Vite base 为 `/wealth/`；未归档 Noto 字体 | 登录局部浅色；资源交给构建系统 |
| `tests/web/test_auth_api.py`、`tests/web/conftest.py` | 真实 auth 路由测试，使用隔离内存 SQLite 和真实用户密码校验；现有成功用例未断言全部 token 字段 | 补齐已有集成测试，不连接正式用户库 |

已使用 CodeGraph `codegraph_explore` 定位 LoginPage → AuthProvider → authApi 及路由/后端装配，再逐项核验源文件与测试。补充消费者审计确认：`auth.login` 只有 LoginPage 调用，`authApi.login` 只有 Provider 调用；`useAuth` 的另一个消费者 WealthRouter 只读认证状态；`saveAuthSession` 还被 wealthFetch 的刷新分支调用，所以不把登录超时写入通用 storage。影响面扩展至前端登录方法、登录策略常量和 Wealth HTML 标签元信息；不调整子系统边界或依赖矩阵。CodeGraph 未返回覆盖测试不等于测试不存在，测试结论以直接读取为准。

### 1.2 技术方案硬口径对账

以下均为后续实现约束，测试编号见第 8 节，当前不表示测试已经通过。

| 编号 | 必须 / 禁止 | 代码落点 | 正向及反向验证 |
|---|---|---|---|
| L01 | 只使用当前背景，不重新生成、不插值伪装高清 | 背景 import、素材 README | V01 原图 hash/尺寸；禁止旧图、重复请求及临时路径 |
| L02 | 指定印章原字形、裁切、位置不变 | `LoginBrand.tsx`、品牌 CSS | V02 裁切/顺序/72px；禁止换字、白边和变形 |
| L03 | 财势天下为文本，可见字形与印章居中 | `LoginBrand.tsx`、光学校准 token | U01、V02；禁止文字图片、仅测行高盒子 |
| L04 | 默认页只保留品牌、两输入、单按钮 | `LoginPage.tsx` | U01；断言无英文、注册、外置标签、角落文案 |
| L05 | 尺寸、间距、颜色、字体复现 Figma | 登录 CSS、局部 token、字体 CSS | V02～V04；禁用旧渐变、磨砂、阴影和控件整体缩放 |
| L06 | 默认/焦点/按下/提交/错误完整；不跳动 | 页面状态、表单 CSS | U02～U05、V03；禁止重复提交、错误遮挡按钮 |
| L07 | 原生表单、隐藏标签、密码掩码、键盘与 live region | `LoginPage.tsx` | U01～U05、V03；无标签或明文密码均失败 |
| L08 | trim、HTTP 字段、存储 key、回跳、刷新合同不变；扩展前端登录生命周期，登录校验 message 按 L15 收敛 | AuthProvider 登录方法与原 API/路由 | U06～U09、U11、A01～A03、R01～R04；禁止新增 `/me` 启动请求、接口别名或重试循环 |
| L09 | 登录浅色 token 不影响全站 | `.login-page` 作用域 | V04；行情页 computed style/截图不得变化 |
| L10 | 背景和字体失败不妨碍表单 | 装饰层、`font-display`、页面渲染 | V01、V05；禁止 await 图片/字体后才挂载表单 |
| L11 | 不新增运行配置、依赖、共享组件或旧版切换；登录超时常量集中管理 | 文件白名单、第 5 节配置审计 | U10；Provider 只改登录生命周期，不改 refresh/storage/router、全局主题或 source 开关 |
| L12 | 单测、真实 API、浏览器、文档分开验收 | 第 8～10 节 | 每项独立证据；mock 和文档检查不能替代真实页面 |
| L13 | 登录默认 10000ms；超时取消、恢复可操作，迟到响应不得落会话或回跳 | loginPolicy.ts、AuthProvider、LoginPage | U11、R04；9999/10000ms、解析拖延、忽略 abort 的迟到响应及卸载反例 |
| L14 | 标签名为财势天下，favicon 为新印章；不改变其他页面正文 | wealth/index.html、favicon 派生资源 | U12、V06；直达/刷新/登录后均一致，无旧图标竞争或错误路径 |
| L15 | 仅 POST 登录校验错误脱敏，禁止回传输入/凭证/调试详情；其他接口和业务错误不变 | exceptions/web.py、第 6.5 节 | U04/U08 安全消息；A02 真实无泄漏/无副作用及非登录反例 |

## 2. 文件与组件设计

下表为评审及补充批准后的实施白名单，实际对账见第 10 节。测试不借机修改其对应生产认证逻辑。

| 文件（仓库相对路径） | 处理与责任 |
|---|---|
| `wealth/src/features/auth/ui/LoginPage.tsx` | 原位替换结构；保留 props 和认证成功 effect；管理输入、尝试 ID/取消 signal、提交锁、超时反馈与卸载清理 |
| `wealth/src/features/auth/model/AuthProvider.tsx` | 仅修改 login 内部合同和生命周期：默认期限、取消、提交会话前检查；初始化/退出/失效事件语义不变 |
| `wealth/src/features/auth/model/loginPolicy.ts` | 新增 `DEFAULT_LOGIN_TIMEOUT_MS=10000`，唯一默认来源，不新建 env 或页面设置 |
| `wealth/src/features/auth/ui/LoginBrand.tsx` | 新增无业务状态的 auth 私有组件；只负责印章裁切与中文文本，无 API、无存储 |
| `wealth/src/features/auth/ui/LoginPage.css` | 完整替换本页旧视觉规则；所有选择器限制在登录域 |
| `wealth/src/features/auth/ui/login-fonts.css` | 新增自托管 `@font-face`，由 LoginPage 引入；不在全局设置新字体 |
| `wealth/src/styles/design-tokens.css` | 仅追加 `.login-page` 下的 `--cs-auth-*`；原 `:root` / dark 值不改 |
| `wealth/src/assets/auth/` | 引用现有背景；归档用户印章、字体、许可和来源 README |
| `wealth/index.html` | 原位改 title 和 favicon 链接；沿用 Vite 资源处理，不增加 head 运行库 |
| `wealth/src/assets/auth/wealth-world-seal-favicon-32.png`、`wealth-world-seal-favicon-64.png` | 从指定印章的同一有效窗口派生 32/64px 图标；不重新设计 |
| `wealth/src/features/auth/ui/LoginPage.test.tsx` | 替换注册存在断言，补 U01～U06 |
| `wealth/src/features/auth/model/AuthProvider.test.tsx`、`authStorage.test.ts` | 新增 U07/U11，会话、认证失效、超时和迟到结果回归 |
| `wealth/src/test/wealthDocumentMetadata.test.ts` | 新增 U12，读取真实 HTML 入口及图标资源，断言标题/链接/尺寸，非 jsdom 自带测试壳 |
| `wealth/src/features/auth/api/authApi.test.ts` | 新增 U08，请求和错误解析合同回归 |
| `wealth/src/shared/api/wealthApiClient.test.ts` | 新增 U09，Bearer、401 单次刷新及终止分支 |
| `wealth/src/app/routes/routerState.test.ts` | 补 U06 的 login/redirect 用例，不改路由实现 |
| `tests/web/test_auth_api.py` | 补 A01～A03 的真实路由字段/刷新断言，不 mock AuthService |
| `src/app/exceptions/web.py` | 仅对匹配 POST 登录路由的 RequestValidationError 输出安全消息；其他路由/异常处理不变 |
| 本 LLD、原技术方案、两级文档索引、素材 README | 同步阶段与验收证据 |

不拆出第二套 LoginForm/LoginMessage/ProtectedRoute，不上移为 shared，不加 UI 框架、状态库或 npm 依赖。`LoginBrand` 与表单留在当前 auth feature，不迁移页面目录。

旧文件处理：`cover.png` 开发前唯一运行引用是 LoginPage；切换后再次全仓审计，确认无运行消费者后已移除，可从 Git 历史恢复。`icon22.png` 和原 `wealth/public/favicon-wealth.png` 保留；HTML 已移除旧图标链接，新图标经构建生成带 hash URL，不保留竞争候选。旧 CSS 的 `--login-*`、`csq-*`、双按钮、角落状态与旧 media query 已从本页清零，不保留双版本皮肤。

### 2.1 DOM 与职责

```text
main.login-page  aria-label="财势天下登录页"
├─ div.login-background  aria-hidden="true"（纯装饰）
└─ section.login-cluster  aria-label="登录表单"
   ├─ LoginBrand / div.login-brand
   │  ├─ span.login-brand__seal（裁切窗口，aria-hidden）
   │  │  └─ img（指定原图，alt=""）
   │  └─ h1.login-brand__title（财势天下，真实文本）
   └─ form.login-form  noValidate
      ├─ div.login-field > label（视觉隐藏）+ input[name=username]
      ├─ div.login-field > label（视觉隐藏）+ input[name=password][type=password]
      ├─ div.login-action > button[type=submit]
      └─ div.login-feedback（固定 DOM，role=status、aria-live=polite）
```

`LoginPageProps` 继续为 `redirectPath: string`、`onAuthenticated: (path: string) => void`。不新增图片、主题或模式 props。品牌组件不接收外部可改品牌名，避免一页内部出现两份默认文案。

## 3. 布局与桌面适配

### 3.1 基准与缩放规则

只定位整个内容区；内部使用纵向布局，不为每个控件分别绝对定位。固定可见内容高 360px，反馈区在按钮之后自然延伸。

| 项目 | 1920×1080 基准 |
|---|---|
| 内容左上角 | x=304，y=264 |
| 品牌行 | 400×88；印章 72×72，左边对齐内容区；横向间距 24 |
| 中文 | 64px/88px、600、字距 10px；单行；光学中心同印章 |
| 品牌行 → 用户名 | 净间距 48px |
| 用户名 / 密码 | 各 400×56；起点 y=400 / 480；净间距 24px |
| 密码 → 登录按钮 | 净间距 32px，即表单 gap 24 + action 上内距 8 |
| 登录按钮 | 400×56；起点 y=568 |
| 反馈区 | 按钮下方 8px；最小行高 20px；允许多行向下增长 |

表单自身使用纵向布局、统一 gap 为 0；第二个字段的上间距为 24px，action 的上间距为 24px、上内距为 8px，反馈的上间距为 8px。不要把整个 form 设为 gap=24 后再用负 margin 抵消反馈间距。品牌与表单之间单独使用 section-gap=48。

目标桌面定位采用以下固定公式；数值集中于 token，不作为 JS resize 状态保存：

```text
W = 登录根节点宽度（100%，继承 body 最小宽度 1460px）
H = 浏览器内容视口高度（CSS vh，不是屏幕物理像素）
内容宽 F = 400px；安全边距 S = 24px
默认内容 + 一行反馈所需高度 B = 360 + 8 + 20 = 388px
left = clamp(S, W × 304 / 1920, W - F - S)
top  = max(S, min(H × 264 / 1080, H - B - S))
```

实现为登录根的左右/上下 padding 与正常文档流；根 `position:relative; width:100%; min-height:100vh`，下内距 24px。left 的比例项使用根宽百分比，top 使用视口单位；**禁止根 `width:100vw` 加 padding 造成额外横向溢出**。不设置固定内容高度或根 `overflow:hidden`。长反馈、低高度和浏览器放大时页面向下增长并可滚动，不动态上移品牌来追逐消息高度。

| CSS 视口 | 预期 left / top（约，px） | 验收口径 |
|---|---:|---|
| 1920×1080 | 304 / 264 | Figma 几何逐项复核 |
| 1512×982 | 239.4 / 240.0 | 当前屏幕逻辑尺寸参考；实际浏览器高度另记录 |
| 1512×850 | 239.4 / 207.8 | 当前电脑常见非全屏内容区检查 |
| 1460×768 | 231.2 / 187.7 | 全局桌面最小宽度检查 |
| 1460×500 | 231.2 / 88 | 不截断按钮；长错误向下滚动 |

以上非 1920 方案是本 LLD 提出的适配规则，待评审和实现验收，不声称已有对应 Figma 画板。DPR 2 不将控件放大两倍，也不以图片像素决定 CSS 宽度。低于 1460px 沿用全局桌面宽度和横向滚动，不新增移动版，不全局解除 min-width；200% 缩放允许滚动，但所有表单内容必须可达。

### 3.2 背景层

装饰层绝对铺满根节点，`background-size:cover; background-position:center; background-repeat:no-repeat; pointer-events:none`。根底色使用登录白纸 token。背景先出现在 DOM，内容容器 `position:relative` 后绘制在其上；品牌/内容祖先不另设 z-index、opacity 或 isolation 来隔离印章与背景混合。不加深色遮罩、滤镜、磨砂卡片、锐化或渐变。

背景在 1920×1080 上会裁掉上下部分，在当前电脑比例上裁切较少，这是 `cover` 的既定行为，不拉伸补齐。页面因短视口或长错误向下增长时，背景跟随根节点覆盖；不引入滚动视差或额外图层。

## 4. 品牌、素材与字体

### 4.1 素材合同

| 资源 | 落点与确定值 | 后续动作 |
|---|---|---|
| 背景 | `wealth/src/assets/auth/wealth-world-login-bg-screen.png`；1556×1011；1,549,096 bytes；SHA-256 `9fee6c58302760a29db77f28320bb6f15f6ca5f2c64fca460417dc070db67426` | 直接 import 原 PNG；首版不转换 WebP、不做多分辨率包 |
| 印章 | 已归档 `wealth/src/assets/auth/wealth-world-seal.png`；原图 1254×1254；1,214,330 bytes；SHA-256 `d45a218fef16c053f1d7119769b5e293b592e5112e529568077f999d51e05430` | 指定上传文件原样归档；未重新生成或透明化 |
| favicon | 已派生 `wealth-world-seal-favicon-32.png` / `wealth-world-seal-favicon-64.png`，分别 32×32 / 64×64，合计 9281 bytes | 原窗口等比例 LANCZOS 缩小，保留字形/金线/底色；hash 见素材 README |
| 字体与许可 | 已归档 `wealth/src/assets/auth/fonts/` | Serif 600、Sans 400/500 WOFF2 合计 36,068 bytes；官方固定版本、许可、覆盖及 hash 见素材 README |

印章原图顺序为左上“天”、右上“財”、左下“下”、右下“勢”。图中繁体不改，旁边文字用简体。运行资源只通过源码 import 或相对 `url()` 进入 Vite，不能引用用户临时上传目录、生成目录、外链或 Figma 临时下载地址。

### 4.2 印章裁切与光学对齐

印章以原图 `(154,150,948,948)` 方形窗口显示，窗口尺寸 72×72，overflow hidden；源图等比例缩小，不变形。固定比例为：

```text
源图展示边长 = 72 × 1254 / 948 = 95.240506px
源图相对窗口 left = -72 × 154 / 948 = -11.696203px
源图相对窗口 top  = -72 × 150 / 948 = -11.392405px
```

比例参数在 token 中统一定义。仅印章裁切层使用 `mix-blend-mode:multiply`；透明品牌/内容容器不增加隔离或不透明底，避免印章改为只与白色容器混合。背景和印章仍是两张不同资源。原图白底融入画面，不伪称透明或矢量。

中文用单个 `h1` 文本节点，固定品牌字形不换行、不描边。品牌行 flex 对齐仅作为初始布局；字距 10px 的尾随空白不得误计为第五个间距，四字布局占宽以 Figma 286px 为基准，可用固定文字容器控制，不能缩放字形或拆成四张图。

光学校准流程固定如下：

1. 锁定并加载 Noto Serif SC 600 的归档字体；记录字体版本与 hash。
2. 1920×1080、100% 缩放下测量印章可见区域中心和四字墨迹联合包围盒中心。不能以 DOM Range/元素盒子中心代替墨迹中心。
3. `--cs-auth-brand-optical-offset-y` 只承载这一次校准结果，偏移公式为 `印章中心Y − 未偏移中文字形中心Y`；字号和品牌行高不变。
4. 用同一个值在 Chromium 和用户当前浏览器、DPR 1/2 复验，偏差 ≤1 CSS px；记录截图裁剪坐标、墨迹边界、偏移值和字体 hash。
5. 不直接照抄 Figma 的 1.512px trim 补偿，不为每个 viewport 另写补丁，不在运行时循环测量文字或等待字体后才允许登录。

实现阶段已测得统一 token 为 **-3px**；Chromium/Chrome 的 DPR1/2 字形中心差分别 +0.5/-0.25 CSS px。版本、采样窗口、墨迹边界和字体 hash 已记录在[素材 README](../../../src/assets/auth/README.md)。这是隔离渲染校准，不代表用户当前窗口或 V02 正式验收完成。字体失败时允许回退并保持表单可用，但回退截图不作为高保真通过证据。

### 4.3 字体交付

- 标题：自托管 Noto Serif SC SemiBold 600，64/88；页面固定四字可生成四字 WOFF2 子集，不改变字形、字重和度量。
- 表单：自托管 Noto Sans SC 400、500，16/24；反馈 400、12/20。只载入实际使用字重，不引入整套字重资源。
- 首选官方 Noto / Google Fonts 的固定版本文件；归档时必须记录确切下载来源、版本/commit、原始 hash、派生方式、字符覆盖与随附可分发许可。来源/许可未经核验的文件不得进入构建。
- 表单若采用 Unicode 分包，固定 UI 文案、ASCII、掩码符号和已有错误文案必须命中相应 Noto 分包；任意合法用户名/服务端消息不能因为字体字符集而被过滤，缺字按系统 sans-serif 栈显示。
- `@font-face` 使用独立 family 名 `CS Auth Serif`、`CS Auth Sans` 和 `font-display:swap`；只在登录域引用，不覆盖全局 `--cs-font-family-base`。
- 禁止引用外部字体 CDN、用户机器安装路径或动态拉取许可不明的字体；不新增 npm 字体包。字体体积按第 7 节实测，超预算先报告，不自行改为另一种品牌字体。

### 4.4 浏览器标签合同

1. `wealth/index.html` 中唯一 `<title>` 为 `财势天下`；不加“登录”、英文或旧名称。
2. 替换原 favicon link，提供指向上述两个 PNG 的 `rel="icon"`、`type="image/png"`、`sizes="32x32" / "64x64"`。HTML 源引用采用 `/src/assets/auth/wealth-world-seal-favicon-32.png?no-inline` 及对应 64px 路径，强制独立资源，由 Vite 生成带 hash 的 `/wealth/assets/…` URL；不在生产 HTML 保留 `/src/`、内嵌大图或手拼构建 hash。已核验本地 Vite 的 `noInlineRE` / `shouldInline` 支持该规则，不修改全局 assetsInlineLimit。
3. 使用同一原印章有效裁切；favicon 无法依赖页面 CSS 的 multiply 混合，所以保留原图底色，不另做未确认的透明化。小尺寸以原印章轮廓可辨为准，不为强化可读性重新绘字。
4. 设置在 Wealth 共用 HTML，直接打开登录、刷新、登录后跳行情页都保持新标签；不增加逐路由设置/卸载恢复，避免登录后又变回旧名。
5. 图标解码/下载失败不影响登录。除正常缓存、图标资源路径检查外，不新增 PWA manifest、桌面快捷方式、Apple touch icon 或运营后台改动。

## 5. Design token 与配置审计

所有新增样式值位于 `design-tokens.css` 的 `.login-page` 作用域；以下表中名称均为 `--cs-auth-` 后缀。CSS 只消费 token，不复制第二份数值。已有 token 直接复用：品牌金 `--cs-color-brand`、placeholder `--cs-color-text-muted`、8/16/24 间距、`--cs-radius-card`。

| token 后缀 | 值 / 来源 | 唯一消费者范围 |
|---|---|---|
| `color-text-primary`、`color-border-focus` | #17324D，Figma Auth Ink | 品牌/输入/按钮、focus |
| `color-surface-field` | #FFFFFF，Figma Paper；同时为失败背景底色 | 输入框、登录根底色 |
| `color-border-default` | #8391A3 | 输入默认边框 |
| `color-error` | #B42318，系统错误；不是行情下跌色 | 反馈与本地无效字段边框 |
| `control-height`、`form-width`、`section-gap` | 56px、400px、48px | 表单与品牌间隔 |
| `border-width` | 1px | 输入/按钮；默认透明按钮边框占位 |
| `brand-height`、`seal-size`、`brand-title-width` | 88px、72px、286px | 品牌组件 |
| `brand-font-size`、`brand-line-height`、`brand-letter-spacing` | 64px、88px、10px | 中文标题 |
| `brand-font-weight` | 600 | 中文标题 |
| `brand-optical-offset-y` | `-3px`，按 4.2 真实字形采样校准 | 仅中文光学修正 |
| `font-family-brand`、`font-family-control` | `CS Auth Serif` + serif 回退；`CS Auth Sans` + 系统 sans-serif 回退 | 登录域 |
| `control-font-size`、`control-line-height`、`control-font-weight` | 16px、24px、400 | 输入框 |
| `button-font-weight`、`button-letter-spacing` | 500、3px | 登录按钮 |
| `feedback-font-size`、`feedback-line-height` | 12px、20px | 反馈区 |
| `form-gap`、`action-padding-top`、`feedback-gap`、`safe-inset` | 依次引用全局 24/8/8/24px | 表单/反馈/根 padding |
| `content-left`、`content-top` | 第 3.1 节公式的单一 CSS 定义 | 内容整体定位 |
| `content-base-height`、`content-feedback-height` | 360px、388px | top 限位；不用于截断内容 |
| `seal-source-size`、`seal-crop-size`、`seal-crop-x`、`seal-crop-y` | 无单位 1254、948、154、150 | 印章裁切计算 |
| `loading-opacity`、`disabled-opacity` | 0.72、0.4 | 按钮状态 |
| `interaction-duration` | 160ms，Figma 控件反馈 | color/background/border/opacity；不做位置动画 |
| `focus-ring-width`、`focus-ring-offset` | 2px、2px，键盘可见性补充 | 按钮 focus-visible；输入保留深蓝焦点边框 |

配置项审计结论：上述均为**构建时样式 token**，来源和持久化位置只有该 CSS 文件，消费者只限登录；依赖全局品牌金/基础间距/圆角，不反向覆盖全局。改动随前端构建发布生效，不需要数据库迁移、服务端重启或运营输入；检验由 computed style、截图和 U10 完成。

行为常量 `LOGIN_FEEDBACK_DURATION_MS=2600` 留在 LoginPage 模块内，只有反馈 effect 消费，与现行超时数值相同；它不是 HTTP timeout，也不暴露为 env 或策略中心配置。`QUOTE_API_AUTH_REQUIRED` 本次不增改、不因移除角落文案而改变；真实运行值须在另行执行真实环境验收时核验。

新增超时默认值的配置审计：

| 项目 | 冻结口径 |
|---|---|
| 名称 / 默认值 | `DEFAULT_LOGIN_TIMEOUT_MS = 10000`，单位毫秒；本版默认固定 10 秒，无每次提交覆盖参数 |
| 来源 / 持久化 | `wealth/src/features/auth/model/loginPolicy.ts`，构建时 TypeScript 常量；不是 env、Settings、数据库或运营配置 |
| 作用范围 / 消费者 | 仅 AuthProvider.login 的计时器与截止时刻检查；测试导入同一常量并断言其值为 10000 |
| 依赖与独立性 | 不依赖 2600ms 反馈计时；不影响 wealthFetch 的刷新、退出及行情 API 超时策略 |
| 生效 / 可见性 | 随前端构建发布；用户只看到提交态/超时反馈，无新配置入口；文档与测试提供运维追溯 |
| 验证 | U11 检查 9999/10000ms 边界、取消与迟到结果；R04 验证真实路由的受控网络拖延 |

## 6. 表单状态与鉴权复用

### 6.1 页面状态

继续使用受控 `username`、`password` 和 `submitting`；反馈改为单一可空对象 `{ id, message, invalidFields }`，其中 `invalidFields` 只表示本地 trim 后为空的字段。递增 `id` 保证重复出现同样文案时重新计时和播报，不创建第二个独立 toast。

增加页面内 `submitLockRef` 与当前 attempt ID/controller：先同步检查锁，空值校验通过后同步上锁，再设置 submitting，finally 仅允许当前 attempt 解锁。原生 disabled 控制视觉与交互，ref 阻断同一事件轮次的重复 submit；不是新增请求队列或共享认证锁。卸载时 abort 当前 attempt；旧 attempt 的 catch/finally 不得更新新尝试的反馈或按钮状态。

| 状态 / 事件 | UI | 行为 |
|---|---|---|
| 初始 / idle | 两个 placeholder；按钮可点击；反馈 DOM 空白 | 不自动提交、不调用 `/me`；Tab 从用户名开始，不抢 autofocus |
| 提交空值或纯空格 | 反馈“请输入用户名和密码”；空字段红边并关联反馈 | 两个值均按现有 trim；不发请求；焦点移到首个空字段 |
| 提交合法值 | “登录中…”、disabled、opacity 0.72、form aria-busy=true | 清旧反馈；一次 `auth.login({username,password})`；锁期间不重复提交 |
| 请求 pending | 品牌、输入框、按钮原地不动 | 最多等待本次 10 秒期限；无倒计时、自动重试或新增取消按钮；输入保持可编辑，本次请求使用提交瞬间值 |
| 达到 10 秒仍未完成 | 退出提交态，提示“登录超时，请重试”；2.6 秒后清除 | abort 请求并拒绝本次结果；保留输入，允许手动重试；迟到成功不得保存会话或跳转 |
| 成功 | 不增加成功卡片或中间页 | Provider 保存 session；已有认证 effect 执行 onAuthenticated；页面不二次存 token 或主动重复 navigate |
| 失败 | 同一表单下方显示已有 API message / fallback；按钮恢复 | 不清空输入，不标记“某字段密码错误”等后端没有给出的字段事实；不自动重试 |
| 再提交 / 卸载 / 反馈满 2600ms | 清理相应反馈 timer；反馈清空或被新反馈替换 | 反馈清空时移除 aria-invalid/describedby；卸载同时取消请求，由 Provider 清理请求 timer/监听器；不保留悬挂回调 |

非提交中不额外制造 disabled 原因；Figma Disabled 0.4 为独立视觉规格，不用于空输入。Loading 样式必须优先于 `:disabled` 通用规则，不能被 0.4 覆盖。

### 6.2 错误、焦点与无障碍

1. 保留 **2600ms 自动清除**；不新增永久错误条、toast 容器或错误关闭按钮。若后续需延长阅读时间，另行确认并同步方案，不在实现中擅改。
2. 所有消息只在按钮后一个反馈区展示。默认最小高度 20px、不显示文字；错误可换行、`overflow-wrap:anywhere`，不截断、不盖按钮。品牌、两输入和按钮坐标不受消息行数影响。
3. 只对本地空字段设置 `aria-invalid=true`、`aria-describedby=login-feedback`；API 的账户级错误只在 form 上关联同一反馈，不猜错在哪一个输入。反馈清除后移除关联。
4. 输入 `id` 与视觉隐藏 label 的 `htmlFor` 对应；保留 `name`、autocomplete 和 password 掩码。隐藏 label 不能 `display:none` 或 `aria-hidden`；禁止只用 placeholder 作名称。
5. 错误色优先于普通 focus 边框；错误输入的 focus-visible 使用已有 2px 深蓝外描边和 2px offset，以便两个空字段同时红边时仍能区分键盘焦点，不改变盒子尺寸。按钮预留透明 1px 边框，hover 切深蓝、pressed 深蓝底金字，不能改变尺寸或 translateY。尊重 reduced-motion，关闭非必要过渡。
6. Enter 走 form submit，Tab 顺序固定为用户名 → 密码 → 登录；不增加 tabIndex 干预。印章与背景不获得焦点、不重复播报品牌。
7. API 错误文本按现有 `AuthApiError.message` 展示为 React 文本，不解析 HTML；不显示 stack、请求体、password、token 或调试 JSON。不得把用户输入或 token 拼入反馈。
8. 登录根声明 `color-scheme:light`，原生控件和自动填充只在该作用域校验；不通过修改 html/body 主题实现浅色页。

### 6.3 HTTP 与存储合同不变，前端登录方法扩展

调用链仍为 `LoginPage → AuthProvider.login → authApi.login → POST /api/v1/auth/login → saveAuthSession → 认证 effect → 原路由`。

| 合同项 | 冻结值 / 消费者 |
|---|---|
| 登录输入 | username、password 字符串；两者提交前 trim；后端现有长度 1–64 / 1–256，本次不增加客户端 maxLength 或新校验文案 |
| 登录响应 | 必填 `token:string`、`username:string`、`is_admin:boolean`；`refresh_token`、`access_token_expires_at`、`display_name` 可空；前端类型允许后三项缺省 |
| 存储映射 | token → `wealth.auth.access-token`；refresh_token → `wealth.auth.refresh-token`；access_token_expires_at → `wealth.auth.expires-at`；username → `wealth.auth.username`；display_name → `wealth.auth.display-name` |
| 不持久化项 | 明文密码、is_admin 不新增持久化；不引入 cookie 或运营后台 key |
| 错误解析 | `AuthApiError` 沿用 code/message；非 JSON 沿用 `请求失败：<status>` / `HTTP_<status>`；页面非 Error fallback 为“登录失败，请检查用户名或密码” |
| 已有 session | 读到 access token 即 authenticated；不额外检查 expires-at、不新增 `/me` 恢复请求 |
| 业务 401 | `wealthFetch` 注入 Bearer；最多一次 refresh 和一次重放；缺 refresh、refresh 失败或重放 401 则清会话并发 `wealth-auth-required` |
| 路由 | `/wealth/login`，保留现有 `/login` 识别；缺省回跳 `/wealth/market/overview`；单 `/` 开头的 redirect 按现有逻辑接收，`//` 或非 `/` 回默认页 |
| 请求取消/超时 | 当前 authApi 已支持可选 signal；本次 Provider 传入请求 signal 并增加 10 秒期限，页面提供卸载取消 signal；不新增并发 refresh 去重 |

TokenResponse 中 token 是会话凭证，不是登录页可见字段；`username/display_name` 的核验使用测试账号，页面品牌不从账户字段替换。不新增 `ITI_*` 或其他登录专用异常码；ITI 属于成交额洞察，与本页无关。

### 6.4 十秒期限、取消与迟到响应

前端内部合同调整为 `AuthContextValue.login(body: LoginRequest, options: { signal: AbortSignal }): Promise<void>`。`options.signal` 必填，唯一调用方 LoginPage 同轮更新；不保留旧单参数分支。`authApi.login(body, signal?)` 的 HTTP 实现无需改动，继续复用现有 signal 通道。

Provider 的每次 login 独立执行以下流程：

1. 外部 signal 已取消时直接拒绝，不发送请求。否则用 `performance.now()` 记录起点及 `deadline = start + DEFAULT_LOGIN_TIMEOUT_MS`，创建内部 AbortController，连接外部取消事件。
2. 发起一次 `loginRequest(body, internalSignal)`；从发起前开始计时，期限覆盖连接等待、响应下载与 JSON 解析，不在收到响应头时提前停止。
3. 将请求 Promise 与“期限/外部取消”拒绝 Promise 竞速；必须同时实现真实 abort 和竞速，不能只做 `Promise.race` 而让请求及其副作用继续执行，也不能只依赖 fetch 遵守 abort。
4. 期限到达先标记该尝试的终态为 timeout，再 abort；对调用方统一拒绝为浏览器标准 `DOMException` 的 `TimeoutError`，避免被随后产生的 AbortError 覆盖。外部卸载取消使用 AbortError，不显示超时文案。它们是客户端控制结果，不新增后端错误 code 或模块异常注册。
5. 请求完成后，在 `saveAuthSession` / `setSession` 前同步复核外部/内部取消、竞速终态与 deadline；时刻 `>= deadline` 不接受成功。截止判定至会话提交之间不得再插入 await；同一尝试只可进入一个终态。
6. 只有有效成功分支写原五个 key 并设置 session；迟到 resolve/reject 均被消费但无副作用。不在请求 Promise 的独立 `.then` 中保存会话。超时后可立即手动发起新尝试，旧请求不得影响新尝试。
7. finally 清理该尝试的计时器、外部 signal 监听器及内部引用；页面卸载同样使竞速及时结束。不得遗留未处理 Promise rejection。

LoginPage 只将 TimeoutError 映射为“登录超时，请重试”，提示从超时发生时起显示 2600ms；字段不标密码错误。非取消的 API/网络错误继续使用现行反馈。页面已卸载/attempt 已失效时不再更新 UI。

10 秒是客户端截止规则，不是撤销服务端事务：请求取消时服务端可能已生成会话或记录审计，客户端只保证该迟到结果不被接收；本任务不新增服务端取消、幂等或回收 API，也不宣称服务端动作已回滚。浏览器后台节流或主线程阻塞可能推迟提示绘制；恢复执行时仍须用 deadline 拒绝过期结果，不能因 timer 回调晚执行而接受超时成功。

### 6.5 登录校验错误脱敏（用户补充批准）

当前源代码的 `str(exc.errors())` 会把校验失败的原始输入放进 message；以虚构超长密码调用真实 LoginRequest 和异常处理器，已证实 HTTP 422 包含完整输入。这与 6.2 禁止展示密码冲突，用户已明确批准最小扩展，不在前端遮盖泄漏，也不新增 maxLength 绕开后端问题。

- 唯一后端改动点为 `src/app/exceptions/web.py` 的 RequestValidationError 处理器；按服务端已匹配路由的完整 path `/api/v1/auth/login` 和 POST 方法判断，不使用前缀匹配。
- 该登录校验错误保持 HTTP **422**、`code=validation_error`、原 `request_id` 与三字段错误信封；message 固定为 **“登录参数校验失败，请检查用户名和密码”**。不得序列化 errors/input/ctx/body，不回传用户名、密码、token、请求体或调试详情。
- 覆盖缺字段、空值、超长、错误类型、非对象 body、非法 JSON；校验仍由原 schema 执行，不改 1–64/1–256 限制、成功响应、AuthService、认证权限、refresh/logout 或任何其他接口的错误文案。
- CodeGraph explore/impact 已覆盖异常装配、登录与页面调用链；全仓消费者检索补齐 Wealth authApi、运营前端 apiRequest/LoginPage、platform-check.js、测试调用。消费者只读取 code/message 或成功 token，没有解析登录校验 message 内部结构的生产逻辑。共享该登录接口的消费者都会收到安全文案，无需修改其代码；不宣称其他接口也已完成脱敏。
- U04/U08 增加安全 422 文案消费；A02 通过隔离数据库和真实登录路由验证响应严格只有安全三字段、无原始输入/凭证、无登录副作用、之后正确凭据可登录。增加同一处理器的非登录及 operator_forbidden 反例，证明未扩散修改。
- 本节是 L08/U10 与第 9 节“HTTP 合同不变”的唯一补充：成功字段、状态码和错误码不变，仅登录校验 message 收敛；不再使用“后端完全未改”的交付口径。

## 7. 加载、性能与失败边界

本轮不发起额外背景加工。下列是开发验收预算，不是已测得结果：

| 项目 | 预算 / 门禁 | 验证 |
|---|---|---|
| 背景 | 原 PNG 1,549,096 bytes，≤1.6MB（十进制）；仅 1 个请求 | 构建产物与浏览器 Network；不并行下载旧 cover |
| 印章 | 原 PNG 1,214,330 bytes，≤1.3MB；仅 1 个请求 | 同上；本版明确接受原图体积，不偷偷压缩换图 |
| favicon | 两张 32/64px PNG 合计 ≤32KiB；由浏览器选择，不承诺只请求一个 | 构建与 Network；不下载 1.2MB 原印章作为 favicon |
| 字体 | 默认空表单首屏实际请求的 WOFF2 合计 ≤1MB；只加载 400/500/600 所需资源 | 冷缓存请求体积、字体命中；超预算先报告原因 |
| 背景解码 | 原 RGBA 像素约 6.29MB，非整个浏览器/GPU 内存承诺 | 尺寸计算；禁止为“高清”生成超大插值位图 |
| 交互解耦 | 图片或字体故意延迟 10s/失败时，页面挂载后仍可立即输入和提交 | V05；不能等资源 Promise 才 render 表单 |
| 本地交互 | 静态首屏可操作 ≤2s；单次 submit 事件后 ≤100ms 显示提交态（未节流环境） | 至少 5 次冷缓存实测，记录环境/样本；不承诺公网耗时 |
| 认证请求 | 初始页 0 个 auth 请求；一次有效提交 1 个登录请求；视觉改版不新增请求 | U05/U08、R01 Network |

同时记录背景、印章、字体三者总传输量；两张当前 PNG 已合计 2,763,426 bytes，不能只报背景 1.55MB 作为整页负载。Vite 负责资源 URL 与 `/wealth/` base，不为本次加入动态 CDN、preload+CSS 双加载或服务端缓存配置。上线时检查实际 Cache-Control 与二次访问网络行为，但本次未验证服务器缓存策略。

认证 API 的端到端耗时与页面渲染耗时分别记录。本次登录默认 10 秒，按 6.4 完成取消、反馈与迟到结果保护；不是全站 HTTP timeout，也不能改成通用清单示例的 5 秒。原免超时例外 E02 已撤销。正常本地真实登录应在期限内成功；受控超时 case 则必须明确失败并可恢复。发生非预期失败先定位，不新增缓存、接口或自动重试。

## 8. 测试与验收设计

### 8.1 自动化测试清单（已实现，结果见第 10 节）

| 编号 | 文件 | 核心断言 |
|---|---|---|
| U01 | LoginPage.test.tsx | 中文 h1、指定印章 DOM、两个有名称的输入、单 submit；无英文/注册/角落状态；aria-label 改为财势天下；密码与 autocomplete 保留 |
| U02 | 同上 | 空用户名、空密码、全空、纯空格分别不请求；首空字段 focus；反馈和 aria-invalid 对应；正常输入不预先禁用按钮 |
| U03 | 同上 | 2599ms 仍有消息，2600ms 清除；同文案重复提交重新计时；旧 timer 不清新反馈；卸载清理；反馈清除后 aria 关联移除 |
| U04 | 同上 | JSON 401、非 JSON 5xx、网络 Error、非 Error 拒绝均退出 pending、有明确消息且不跳转；不注入 HTML、不输出 token/password；长消息结构仍在按钮之后 |
| U05 | 同上 | 挂起 Promise 时登录中、disabled、aria-busy；同一轮两次 submit 仅请求一次；结束后可重试；Enter 不走第二条处理链 |
| U06 | 同上 + routerState.test.ts | 请求体两项均 trim；成功保存原 key 并携带 query 回跳；未登录拦截；缺省/相对路径/`//` 回默认；合法单 `/` 路径保留；不误称新增白名单 |
| U07 | AuthProvider.test.tsx、authStorage.test.ts | 已有 access token 直接恢复且不请求 `/me`；所有 5 key 保存/删除映射；可空/缺省值不留旧字段；失效事件清 session；不保存密码或新增 key |
| U08 | authApi.test.ts | 登录/refresh/logout 原 URL、POST JSON、字段名、可选 signal 不变；code/message、HTTP fallback；无注册调用 |
| U09 | wealthApiClient.test.ts | 普通成功仅一次 fetch；401+refresh 成功重放一次且使用新 token；缺 refresh、刷新失败、重放 401 各自清会话并发事件；无重试循环；非 401 不刷新 |
| U10 | 范围 diff + 源码引用审计 | Provider 只修改 login 生命周期；后端仅 6.5 登录校验错误脱敏；API client/storage/router/refresh 原实现不变；无新依赖/runtime 配置/全局主题覆盖；HTML 只改 title/icon；旧登录 CSS 清零 |
| U11 | AuthProvider.test.tsx + LoginPage.test.tsx | 默认值为 10000；9999ms 尚 pending、10000ms 超时并 abort；JSON 解析耗尽期限；及时成功后 timer 不再触发；外部 signal 已取消不请求；卸载取消不落会话、不提示；忽略 abort 的迟到成功/失败不写 key/跳转/污染新尝试；到点与成功同轮按 deadline 判定；超时反馈 2600ms 清除且可手动重试，无自动重试/未处理拒绝 |
| U12 | wealthDocumentMetadata.test.ts | 真实 wealth/index.html 唯一 title 为财势天下，32/64 图标来自指定印章；源码资源存在且 PNG 尺寸匹配；无旧 favicon 候选或额外 head 修改；构建产物链接由 V06 检验 |
| A01 | tests/web/test_auth_api.py | 隔离账号走真实 POST login；断言全部 6 个 TokenResponse 字段、非空 token、可空 display_name 及成功 last_login_at；不 mock service |
| A02 | 同上 | 错误密码、停用账号原状态码/code/message；缺字段、越界、错误类型和非法 JSON 的安全 422 三字段；无输入/token 泄漏、无登录副作用；非登录/operator_forbidden 反例；后续正确凭据仍可登录 |
| A03 | 同上 | 真实 login → refresh 返回相同身份、新 refresh token 和有效 access token；不要求同秒签发的 access token 字符串必然不同；旧 refresh 重放失败；带当前 refresh token 的真实 logout 后该 refresh 不再有效；仅测试隔离库 |

U 类可以 stub HTTP 以复现异常和计时；它们是单元测试，**不是“真实 API 展示 smoke”**。现有 `tests/web/conftest.py` 用隔离内存数据库替换 DB 依赖，不替换 AuthService，A 类可在该既有测试边界补齐。不得把测试数据写入正式账户表，也不为本任务删除/重建任何既有数据库。

### 8.2 视觉与浏览器用例

| 编号 | 输入 / 操作 | 通过标准 |
|---|---|---|
| V01 | 冷缓存打开、检查资源请求与产物 hash | 本版原图正确，旧图不请求；无临时/外部路径；两张图和字体总量有记录 |
| V02 | 1920×1080 DPR1；用户电脑实际 viewport DPR2；字体加载完成 | 第 3 节位置/尺寸差 ≤1 CSS px；中文墨迹与印章中心差 ≤1 CSS px；无拉伸/额外文字/白边 |
| V03 | hover、pressed、键盘 focus、自动填充、pending、错误、重复错误 | 控件尺寸与位置不跳动；Loading opacity 0.72；焦点可见；输入/按钮不被反馈遮挡；键盘和读屏关联有效 |
| V04 | 1512×982/850、1460×768/500、200% 缩放；随后打开行情页 | 第 3 节公式一致、内容可滚动触达；当前电脑山体/云雾/水面人工确认；行情主题/全局字体/顶部栏不变 |
| V05 | 分别阻断背景、印章、字体；或人为延迟 10s | 表单持续可用、无未处理异常；允许视觉回退但不可将其计为高保真通过 |
| V06 | 浏览器直接打开登录/行情、刷新、登录后跳转；检查构建 HTML 与 Network | 标签名称始终财势天下；新印章图标实际显示、资源 200 且含正确 MIME；无 `/src/` 生产路径、旧 favicon link 或新旧缓存竞争；运营后台未变 |

无 Figma 完整错误画板的部分，由本 LLD 第 6 节冻结：一个反馈区、2600ms、不改前景坐标。Figma 母版的外置 Label 和错误 helper 高度不能原样套入默认页面。

### 8.3 核心真实 API + 展示 case

字段清单来源为既有合同和当前 Figma，不能为了测试添加 UI：

| 字段组 | 核心字段 | 核验位置 |
|---|---|---|
| 表单请求 | username、password | POST JSON 结构与 trim；证据不保存密码值 |
| 成功 | token、refresh_token、access_token_expires_at、username、is_admin、display_name | A01/A03 验证类型与可空；浏览器只记录 key 存在性/身份是否相符，不导出凭证 |
| 错误 | HTTP status、code、message | A02 + 页面可读 message；调试字段不直接显示 |
| 客户端超时 | TimeoutError、10000ms 期限、“登录超时，请重试” | U11/R04；不是后端响应字段，不伪造 HTTP 状态或 code |
| 页面/路由状态 | submitting、反馈、认证状态、redirect | R01～R04 的真实状态流与 URL；品牌/两输入/单按钮是固定 UI，不来自响应；标签元信息由 U12/V06 单独核验 |

真实浏览器使用本地已运行且指向获准测试环境的前后端与既有测试账号，禁止替换 fetch、拦截伪造 auth 响应、注入假 token 或走 mock adapter。执行前确认后端连接不是生产用户库；若只有生产环境或缺测试账号，停止并请求验收条件，不自行建用户、改密码或试探生产凭据。

- **R01 成功与回跳**：从未登录的受保护页面进入登录；输入有效测试凭据，观察原 login 请求、提交态、五个存储 key 的映射及原 redirect/query 回跳；初始登录页没有 `/me` 或注册请求。用同一请求在 A01 的字段断言对应核对。
- **R02 失败与恢复**：测试账号输入一次错误密码；真实 401 message 出现在反馈区，页面不跳转、不写成功会话；2600ms 后清除，改正后成功。不进行批量错误密码尝试。
- **R03 会话回归**：已有合法 session 刷新页面；用测试环境的真实会话过期/注销条件验证刷新成功与失败返回登录，不伪造成功响应。若业务请求依赖后端鉴权保护，先核验测试环境真实保护设置；未产生真实 401 不算通过。当前只有前端静态合同，不能据此声称已完成此项。
- **R04 受控网络超时与重试**：在获准测试环境使用网络代理延迟真实 login 响应超过 10 秒（也覆盖响应体延迟），不伪造响应、不替换 AuthService。验证超时反馈、请求取消、按钮可重试、2.6 秒清消息；继续等待迟到响应也不写会话/回跳。恢复正常网络后手动重试成功。代理仅作故障注入，不加入正式后端；记录服务端可能已提交而客户端拒绝接收的边界，不能用此 case 宣称正常登录性能通过。

不新增 browser runner 依赖或认证测试后门。可用当前浏览器自动化能力或人工执行 R/V 用例，记录准确页面入口、步骤、浏览器版本、viewport/DPR、耗时和脱敏截图；只有单元 HTTP stub 不满足本节。

### 8.4 执行入口与报告

后续实现完成后，在 `wealth/` 下执行：

```bash
npm run typecheck
npm run test
npm run build
```

在仓库根执行真实路由集成回归（使用项目已有 Python 环境）：

```bash
uv run pytest -q tests/web/test_auth_api.py tests/web/test_auth_registration_api.py tests/web/test_auth_services.py
```

真实浏览器入口：本地既有前后端运行后，打开 `/wealth/login?redirect=%2Fwealth%2Fmarket%2Foverview`，依次执行 R01～R04、V01～V06；开发前端可在 `wealth/` 执行 `npm run dev -- --host 127.0.0.1`，使用其输出端口，现有 `/api` 代理目标为 `127.0.0.1:8000`。这只是验收入口，不授权本轮启动/部署后端；后端未就绪不得把 Vite 页面当作真实链路通过。

合入前把每项结果写回本 LLD：命令、通过/失败/未执行及原因、核心字段断言、截图路径和测量值。保留 U/A/V/R 的证据分类，不把本地测试称为生产验收。

## 9. 编码门禁矩阵与例外白名单

依据：[模块交付通用清单](../../system/module-delivery-checklist-v1.md)。下表已作为用户批准后的编码依据；6.5 为补充批准的唯一后端变更。不适用项保留理由。

| 通用清单 | 适用性与本页落点 | 验证 |
|---|---|---|
| 2.1 交付事实链 | 适用；当前 Figma + 原技术方案 + 本 LLD；非基准适配/反馈由本文补足 | 三者评审；第 10 节 G0 |
| 2.2 后端事实归一 | 适用；认证身份和错误源自原 auth 合同，不造会话字段 | U06～U09、A01～A03 |
| 2.3 状态机 | 适用；idle/submitting/反馈/成功回跳；默认 10 秒超时与取消在 6.4 | U02～U05/U11、R01/R02/R04 |
| 2.4 显示语义 | 部分适用；错误为系统红，不借用行情色；无行情方向字段 | V03、局部 token；行情方向规则不适用 |
| 2.5 行为过程 | 适用；同轮重复提交、相同错误重计时、失败后恢复 | U02～U05、V03 |
| 2.6 文档同步 | 适用；原方案、LLD、两级索引、素材 README 同轮对账 | 文档检查、范围 diff |
| 2.7 渐进替换 | 单页范围/失败不伪装适用；mock→real/source 开关不适用，E03 | U10、R01、第 10 节发布边界 |
| 2.8 契约与消费者 | 适用；成功HTTP/storage合同不变，登录校验消息按6.5脱敏；6.4前端login唯一调用方同轮迁移 | U06～U09/U11、A/R 类 |
| 2.9 图表坐标/文案 | 坐标不适用，无图表；不增常驻说明适用 | U01、V02 |
| 2.10 统计/传输 | 无聚合/SQL 变更，SQL 下推不适用；加载与登录 10 秒期限适用 | 第 7 节、V01/V05、R01/R04 |
| 2.11 策略配置 | 不新增策略中心或 runtime 配置；构建 token/登录超时常量审计在第 5 节 | U10/U11、V04；无 moduleKey/market |
| 2.12 映射矩阵 | 适用；本表逐项映射，不能只写默认继承 | 文档逐项校验、G0 |
| 2.13 例外/语义断言 | 适用；有效例外 E01/E03/E04，E02 撤销；无累计值坐标，品牌/交互断言替代无关图表断言 | U/V 类、例外评审 |
| 2.14 图表参数优先级 | 不适用；无图表和 yMin/yMax/yTickValues | U10 无图表改动 |
| 2.15 并排图表对齐 | 不适用；本页无并排图表；品牌对齐另按 4.2 | V02 |
| 2.16 单行文案 | 适用到固定品牌/按钮单行；错误允许换行，禁止截断 | V02/V03 |
| 2.17 核心测试 | 适用；字段、真实路由和真实前端步骤/入口在 8.3～8.4 | A01～A03、R01～R04，mock 不能替代 |
| 2.18 跨模块八原则 | 全量映射见下表 | 每条均有范围与断言 |

### 9.1 八条原则对账

| 原则 | 本页处理 | 代码 / 验证 |
|---|---|---|
| 1 事实源单一 | 身份由原 auth API，页面不二次生成 token；仅 Provider 接受有效登录结果 | U06/U07/U11、A01/R01/R04 |
| 2 契约先行 | 6.3成功字段/存储不变；6.4内部signal同轮迁移；6.5安全422经用户批准后实施 | U08/U11、A01～A03 |
| 3 配置一致 | 第 5 节单一局部 token 与超时常量；无新运营配置，禁止双版本开关 | design-tokens.css、loginPolicy.ts、U10/U11/V04 |
| 4 默认显式 | 空值、pending、失败、缺省 redirect、资源失败均有规则 | U02～U09、V05 |
| 5 排序筛选确定 | 无数据排序/筛选，不适用该数据规则；键盘顺序和 trim 明确且不扩写 | U02/U06、V03 |
| 6 性能预算 | 第 7 节图片/图标/字体/请求量预算；登录期限 10 秒，不改服务端 | V01/V05/V06、R01/R04 耗时 |
| 7 异常标准化 | 复用 AuthApiError / 后端原 code，不新增 ITI 或模块异常注册，E04 | U04/U08、A02/R02 |
| 8 用户可见结果 | 不只看 JSON；品牌、反馈、提交态、回跳必须真实验证 | A/R/V 三类独立证据 |

### 9.2 例外白名单（仅本次登录视觉改版，随 LLD 评审）

| 编号 | 例外规则及理由 | 边界 |
|---|---|---|
| E01 | 用户指定浅色山水、无 TopMarketBar，与默认深色行情页不同 | 样式仅 `.login-page`；共用 HTML 标签名/图标按新拍板更新，不改全局主题或其他页面正文 |
| E03 | 已是真实认证链路，不存在 mock→real 切换，故不建 source 开关、不退回 mock | 单页原位替换；回退只能在另获授权后用已验收整包版本，不留兼容皮肤 |
| E04 | auth 位于已有应用认证域，沿用 AuthApiError 与原 API code，不接入市场模块异常码改造 | 后端反馈消费 message，登录校验错误按 6.5 脱敏；客户端 TimeoutError 映射固定超时提示，不伪造后端 code 或增加 debug 面板 |

原 E02“本次免新增超时”已按用户 10 秒拍板撤销，不再作为编码例外；保留该编号的撤销记录防止误用旧口径。

## 10. 实施阶段、门禁状态与闭环

| 门禁 | 要求 | 当前状态 |
|---|---|---|
| G0 设计评审 | 拍板记录、超时内部合同、配置审计、例外与测试完整 | 用户批准按 LLD 开发，并补充批准 6.5 登录错误脱敏 |
| G1 素材准备 | 当前 PNG 不变；原印章、favicon、Noto 与许可归档 | 完成，尺寸/hash/体积可核验 |
| G2 视觉实现 | 原位替换、局部 token、真实字体光学校准、旧 CSS 清零 | 开发完成，实际窗口视觉验收仍待用户执行 |
| G3 开发验证 | U/A、typecheck、全量 test/build、文档与边界检查 | 完成，结果见 10.1；不替代 V/R |
| G4 部署与正式验收 | 用户部署后执行 V01～V06、R01～R04 | 未执行，按用户最新指令不由 Codex 进行 |

本轮执行边界按用户最新指令调整为：G0 → 素材/字体 → UI、超时与获准的脱敏实现 → 自动化/光学校准 → 交付用户部署及 V/R 验收。未启动前后端服务，未使用真实账号，未执行发布。背景不再等待 4K。

发布失败条件包括真实登录/回跳回归、资源路径错误、当前电脑视觉不可接受或主题污染。先停止发布并定位；确需回退，另获授权后恢复上一已验收的完整前端制品，不清会话、不回滚数据库、不在代码里保留切换开关。本轮不执行任何发布动作。

### 10.1 开发结果与计划对账

| 硬口径 | 实现和开发证据 | 尚未执行的正式检查 |
|---|---|---|
| L01/L02/L05 | 原 PNG/印章、裁切/favicon、本地字体与局部 CSS；U12 校验原图 hash/尺寸、字体/图标预算；静态真实组件光学校准 | V01/V02/V04 当前窗口外观、清晰度、网络 |
| L03 | LoginBrand 单 h1；字体600、64/88、字距10、统一-3px；U01与墨迹测量 | V02 用户实际浏览器 |
| L04/L06/L07 | 单表单、隐藏 label、两输入、单按钮、同步提交锁、反馈 id/timer/aria；U01～U05 | V03 键盘、自动填充、交互与读屏 |
| L08 | auth.login 唯一消费者迁移 signal；原 API/storage/router/refresh 生产文件无 diff；U06～U09、A01/A03 | R01～R03 真实环境登录、回跳、刷新 |
| L09/L11 | token 只追加到 .login-page；无依赖/运行配置/全局样式/其他页面修改；U10 范围审计、16项架构边界测试 | V04 正式页面主题对照 |
| L10 | 装饰背景、独立字体 swap、页面无资源等待；U01 初始可操作 | V05 网络阻断/延迟和冷缓存速度 |
| L12 | 本表区分代码、隔离测试、校准和正式 V/R；不以单测结论替代用户验收 | 全部 V/R 由用户执行 |
| L13 | Provider竞速/abort/deadline/提交前复核，页面attempt隔离；U11含9999/10000ms、解析拖延、timer延迟、迟到resolve/reject与卸载 | R04 真实网络故障注入 |
| L14 | 共用HTML title/icon；U12及构建HTML为/wealth/assets/带hashPNG，无生产/src/路径和旧候选 | V06 实际标签、资源MIME与缓存 |
| L15 | exceptions/web.py仅匹配POST登录；安全422；U04/U08、A02真实路由无泄漏/副作用和非登录反例 | R02 正式错误反馈 |

- `npm run typecheck` 通过；`npm run test` **99文件/712测试通过**；`npm run build` 通过。登录相关7个测试文件共65项（其中路由文件含原有回归）。全量测试中带 real-api 名称的前端测试不等于生产真实验收。
- `.venv/bin/python -m pytest -q tests/web/test_auth_api.py tests/web/test_auth_registration_api.py tests/web/test_auth_services.py`：**30通过**，隔离内存SQLite，真实路由/schema/service；未连接正式数据库。
- 三项 `tests/architecture/test_*guardrails.py` / `test_subsystem_dependency_matrix.py`：**16通过**；依赖矩阵、子系统边界未改变。CodeGraph explore/impact 覆盖异常装配、认证与消费者；开发后 sync/status 已同步。
- 构建保留现有大于500kB chunk警告；后端测试存在框架弃用告警，本轮不扩展依赖升级或全站拆包。
- 背景与印章字节不变，字体36,068 bytes，favicon9,281 bytes；Serif内嵌CSS、Sans独立WOFF2。校准差≤0.5 CSS px；完整素材证据见 README。不将原始素材字节统计当作已测冷缓存加载耗时。
- `python3 scripts/check_docs_integrity.py` 三项检查和 `git diff --check` 通过；范围对账确认只涉及本页、获准异常处理、对应测试与文档。本轮没有部署、正式 V/R、生产写入、提交或推送。后续用户验收通过后再闭环 G4。

| 版本 | 日期 | 记录 |
|---|---|---|
| v1 | 2026-09-04 | 基于当前 Figma 与真实 auth 代码补齐 LLD、硬口径映射、编码门禁、例外及核心测试；待评审 |
| v1.1 | 2026-09-04 | 同步三项用户拍板：登录默认 10 秒及迟到结果保护、共用标签名/印章图标、保留 2.6 秒反馈；未编码 |
| v1.2 | 2026-09-04 | 用户批准登录校验错误脱敏；完成登录改版、10秒期限、资源与字体/光学校准、U/A及构建；部署与V/R交由用户 |
