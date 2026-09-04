# 登录页图片素材

## 当前屏幕比例背景

- 文件：[wealth-world-login-bg-screen.png](./wealth-world-login-bg-screen.png)
- 日期：2026-09-04。
- 来源：Codex 内置 image_gen，以此前已选定的无字浅色山水背景为编辑输入；素材生成阶段只生成一次，未使用独立 CLI/API 付费路径。LLD 补齐阶段未再次生成或编辑图片。
- 输入生成文件标识：exec-a986cccb-ca07-4117-8e99-5e86d30c6bc2.png；原 Figma image hash：`9eb61145003413703ec19e2e1dd4a4591ffdee67`。
- 输出生成文件标识：exec-7c9dde1d-6ea6-426b-9480-36f74be65ab6.png。
- 请求目标：3024 × 1964，匹配当前 Retina 屏幕；实际输出：**1556 × 1011**。
- 文件体积：**1,549,096 bytes**，约 1.55 MB；PNG。
- SHA-256：`9fee6c58302760a29db77f28320bb6f15f6ca5f2c64fca460417dc070db67426`。
- 当前 Figma image hash：`d16b6c5203d55bf37c683f0275925fd0142de187`。
- [Figma 默认登录页](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=1314-30317)：背景节点 `1314:30318` 已替换，前景未移动。
- 文件为生成工具原样输出，没有另行插值放大、超分辨率处理或格式转换。源图像素不满足 Retina 原生尺寸，不能标为原生 3K/4K。
- Figma 与 LoginPage 现已引用同一原 PNG；没有重新编码、放大或双版本开关。开发已完成，部署与正式验收由用户执行。
- 用户已暂停标准 4K；不因当前像素不足自动反复生成或切换付费工具。
- 2026-09-04 用户决定“就先这样”，本图作为本版开发输入；首版按原 PNG 引用，不新增 WebP 或多尺寸包。运行页面的实际清晰度与加载验收仍在开发后进行。

## 最终生成提示词

```text
Use case: style-transfer / screen-format adaptation.
Asset type: final text-free background bitmap for a Wealth World desktop login page.
Input image 1 is the exact existing approved background and the edit target. Preserve its pale silver-white sky, misty blue-gray Chinese mountain ranges on the right, very fine restrained pale-gold ridge accents, calm reflective water, atmosphere, colors, and spacious empty left side. Do not redesign the landscape.
Primary change: adapt the artwork to this user's MacBook Retina screen, target actual image dimensions 3024 pixels wide by 1964 pixels tall (landscape aspect 756:491, about 1.5397:1), not 16:9 and not 4K. Deliver the highest available native detail at that target size, not a picture of a screen and not a screenshot. Refine fine mountain textures and smooth sky gradients without sharpening halos.
Reframe/outpaint vertically to the target screen aspect while keeping the dominant mountains on the right and the left 43 percent quiet and mostly empty for a separately rendered login form. Preserve the original mood and relative positioning of the main peaks. Keep enough headroom and bottom water so it also works with modest centered cropping.
No text of any kind, no Chinese characters, no English, no logo, no seal, no form controls, no watermark, no new buildings, boats, people, sun disks, or graphic decorations. This is the background alone.
```

## 印章与浏览器图标

归档指定原图 [wealth-world-seal.png](./wealth-world-seal.png)，1254×1254、1,214,330 bytes，SHA-256 `d45a218fef16c053f1d7119769b5e293b592e5112e529568077f999d51e05430`。原字形左上天、右上財、左下下、右下勢，保持白底、金线及笔画，未重绘或透明化。

页面使用 72px 方窗和 CSS multiply，从原图 `(154,150,948,948)` 裁切。favicon 使用相同窗口，以 Pillow 11.3.0 `Image.Resampling.LANCZOS` 等比例缩小，PNG `optimize=True` 保存；裁切的右下排他坐标为 `(1102,1098)`。

| 文件 | 尺寸 | bytes | SHA-256 |
|---|---|---:|---|
| [32px 图标](./wealth-world-seal-favicon-32.png) | 32×32 | 2336 | `00432078af48e9e9f5e2e7fd0d20e024d330b113789a8d7be2108def00aaf5dc` |
| [64px 图标](./wealth-world-seal-favicon-64.png) | 64×64 | 6945 | `ce550ccdf0b373d97465b1e4be3d95f759bfb219be04106a5d2654ee523818f4` |

两图标合计 9281 bytes，小于 32KiB。HTML 使用 `?no-inline`，构建产生独立带 hash URL；不下载大印章当 favicon。全仓确认旧 `cover.png` 已无运行消费者后删除，该文件可从 Git 历史恢复；`icon22.png` 和原 `wealth/public/favicon-wealth.png` 保留，HTML 不再选择旧图标。

## 本地字体与许可

字体只由登录页的 `login-fonts.css` 使用，独立 family 为 `CS Auth Serif` / `CS Auth Sans`，均 `font-display:swap`；不修改全站字体，不使用字体 CDN、不新增 npm 依赖。

| 原始文件 | 固定来源版本 | 原始 SHA-256 |
|---|---|---|
| [NotoSerifSC wght TTF](https://raw.githubusercontent.com/google/fonts/8b0a1d0f5983c89bc2b93f1b5fb55f9e252744b5/ofl/notoserifsc/NotoSerifSC%5Bwght%5D.ttf) | Google Fonts commit `8b0a1d0f5983c89bc2b93f1b5fb55f9e252744b5`；Version 2.003-H1；25,125,512 bytes | `050080d9255a86808f2945bffac582b31ef32bc36411ce29563b4961670c66f9` |
| [NotoSansSC wght TTF](https://raw.githubusercontent.com/google/fonts/a85815a42757630ce188fdad368c2dfc444d4773/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf) | Google Fonts commit `a85815a42757630ce188fdad368c2dfc444d4773`；Version 2.004-H2；17,772,300 bytes | `a3041811a78c361b1de50f953c805e0244951c21c5bd412f7232ef0d899af0da` |

对应同 commit 的 OFL.txt 原样随附：[Serif 许可](./fonts/NotoSerifSC-OFL.txt)、[Sans 许可](./fonts/NotoSansSC-OFL.txt)，均 SIL OFL 1.1，允许随软件再分发。保留版权和许可证；派生字体已改 family/full/PostScript/subfamily 名称，不使用 Sans 许可中保留的 Source 名称。

制作环境：隔离临时 Python 3.13.5、fontTools 4.59.2、Brotli 1.2.0、zopfli 0.4.3；未改变项目依赖。流程：读取固定原 TTF → `fontTools.subset` 按下述 Unicode 集合取子集（保留所有 name ID/语言，关闭时间戳重算）→ `instantiateVariableFont` 固定 wght → name ID 1/2/4/6/16/17 改为上述独立 family 与对应字重 → `flavor=woff2` 保存。不修改轮廓、字号度量或字间距；字间距由页面 CSS 控制。

| 派生文件 | 字重 / 覆盖 | bytes | SHA-256 |
|---|---|---:|---|
| [Serif 600](./fonts/cs-auth-serif-600.woff2) | 600；财势天下四字 | 2016 | `dfa21a6f1a5ce56d42dae2f0d0de5a06d55fe561e5381b43ee16f83fafc9e477` |
| [Sans 400](./fonts/cs-auth-sans-400.woff2) | 400；155 个 Unicode | 16952 | `677a2aeef9d21a088a3943d5e2072976ea5674615f0839ba6e9e775aa4bc429b` |
| [Sans 500](./fonts/cs-auth-sans-500.woff2) | 500；同上 | 17100 | `d3681e918d3048cac4b484971c0564c9890fef9e448e3d0860439989b2505302` |

Sans 覆盖 ASCII U+0020–U+007E，另包含：

```text
•…●不中临为使停先入参号名和在失存完定密已录态成或户效数无时暂期查校检正求状用登码确空箱能证试请败账超输过邮重锁验，：
```

涵盖固定 UI、密码掩码、既有登录错误和新安全校验消息；任意用户名或其他服务端消息不因子集被过滤，未覆盖字形继续使用系统 sans-serif 回退。字体总量 36,068 bytes；背景、印章、三字体源文件合计 **2,799,494 bytes**，加两 favicon 为 **2,808,775 bytes**。实际构建 Serif 600 内嵌 CSS，Sans 两字重为独立 WOFF2；该统计是资源原始体积，不是假定浏览器冷缓存传输、压缩或加载耗时已验收。

## 中文光学中心的开发校准

使用真实 LoginPage/AuthProvider 组件的静态输出和真实 CSS/字体，在标准模式、1920×1080、100% 缩放下做隔离渲染；无服务启动、真实账号或认证请求。Chromium 151.0.7922.34、Chrome 152.0.7977.82，DPR 1/2。字体 hash 见上表，字体加载成功后才采样。此处只为得到固定样式值，**不代替用户 V/R 正式验收**。

截图采样窗口（CSS px）：中文 `(395,250)-(710,370)`；印章 `(302,264)-(378,352)`。墨迹阈值 `R<100、G<125、B<170、B>R+10`，联合包围盒取右/下排他边界。未偏移时，印章中心减中文中心分别为 DPR1 `-2.5px`、DPR2 `-3.25px`；按像素采样区间取统一 **-3px**，写入 `--cs-auth-brand-optical-offset-y`，未复制 Figma 的 trim 值。

| 引擎 / DPR | 偏移后中文字形 bbox | 印章 bbox | 印章中心减中文中心 |
|---|---|---|---:|
| Chromium / 1 | (402,278)-(684,338) | (304,273)-(376,344) | +0.5px |
| Chrome / 1 | 同上 | 同上 | +0.5px |
| Chromium / 2 | (402,278.5)-(684,338.5) | (304.5,273)-(376,343.5) | -0.25px |
| Chrome / 2 | 同上 | (304.5,272.5)-(376,344) | -0.25px |

四组均 ≤1 CSS px。基础内容区 `(304,264)`、400×388（含空反馈预留），输入 `(304,400)`、按钮 `(304,568)`，各400×56。校准时曾发现临时渲染壳缺 doctype，已更正为与真实 HTML 相同的标准模式后重新量测，没有据此修改页面布局。

素材与正式验收合同见[技术方案](../../../docs/pages/login/login-page-auth-design-v1.md)和[LLD](../../../docs/pages/login/login-page-auth-low-level-design-v1.md)。当前用户实际浏览器窗口、清晰度、自动填充、加载失败/速度和真实登录验收仍由用户执行。
