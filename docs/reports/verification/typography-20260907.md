# 字体统一检查（2026-09-07）

## 冲突来源

- tokens.css 的正文使用 Inter/系统无衬线，标题使用 Avenir Next/Inter；同一中文字符实际依赖操作系统回退。
- 编号、Session、日志、错误详情、来源配置、Markdown 代码等 11 处 font-family 声明和多处 font 简写强制使用等宽字体。
- 组件字重包含 400/500/600/620/630/640/650/700/750/760/770/780/790/800，且标题存在全局与 scoped 重复覆盖。
- ECharts Canvas、图例、坐标轴、Tooltip 使用默认字体及独立字号；Tailwind 默认 sans/mono 未与应用主题绑定。

## 实施

- tokens.css 为字体、字号和字重的唯一数值来源。正文、标题、编号和代码共用 Times New Roman → Microsoft YaHei 字体链；常规 400、强调 700。
- typography.css 统一原生控件、表格、Markdown、SVG 和 Tailwind 字体；通过本地 @font-face 及 Latin unicode-range 区分中英文，保留 Times New Roman 斜体与粗斜体。
- 页面主标题统一 22px/700；模块与通用弹窗标题统一 18px/700。删除相应组件和旧主题中重复的字号、字重定义，保留其原有行高行为。
- 其他既有字号集中为主题变量；保留现有正文/辅助文字/控件/阅读内容/统计数值层级，不将网页整体放大到印刷论文尺寸。
- ECharts 通过 utils/typography.ts 读取同一 CSS 主题；坐标轴、图例、Tooltip 同步覆盖。
- CSS 对比确认除字体相关声明外，布局、颜色、间距等样式没有变化；没有修改业务逻辑。

## 本机字体

本机原有 Times New Roman 常规、粗体、斜体和粗斜体。按用户要求下载微软雅黑常规、粗体并安装到 ~/Library/Fonts。最终文件经过 fontTools 字符映射解析，常规覆盖 29075 个映射，粗体覆盖 29058 个映射；通过 CoreText 注册并由 Chromium 实际字形检测确认。

最终下载来源：[常规字体](https://github.com/qbob/MSFonts/blob/master/fonts/msyh.ttf)、[粗体字体](https://github.com/qbob/MSFonts/blob/master/fonts/msyhbd.ttf)。最初取得的另一份常规字体字符映射损坏，已替换，没有作为最终字体使用。字体说明：[Microsoft YaHei](https://learn.microsoft.com/en-us/typography/font-list/microsoft-yahei)。

字体文件位于 /Users/niuniu/Downloads/astra-fonts 和 /Users/niuniu/Library/Fonts，不纳入代码仓库。本方案使用客户端本地字体；其他访问终端和 CI 必须安装相同字体。未安装字体的终端不能保证无回退，不能将本机结果等同于所有部署终端的验收。

## 验证

- Vue 类型检查及 Vite 生产构建通过；保留既有大 chunk 提示。
- git diff --check 通过。
- 新增 e2e/typography.spec.ts：2/2 通过。覆盖首页、员工列表/详情、任务列表/详情、运行列表/详情、数字图书馆、设置、待处理，共 10 个路由；逐个检查可见中英文文本节点的 CSS 字体及 CDP 实际字体，未发现非指定字体回退。
- 独立校验中文及中文标点、英文/数字/英文标点在 400/700 下的实际字形。结果分别为 Microsoft YaHei / Times New Roman。
- 检查任务创建弹窗、知识 Markdown 弹窗（包含表格、代码、粗体和斜体）、设置四个页签及员工抽屉。知识详情采用只读模拟响应，避免依赖写入接口。
- 主要页面截图位于 artifacts/typography，已检查主要路由及详情、弹窗的字体视觉效果。
- 初次 scripts/e2e.sh 全量业务回归为 7 通过、7 失败、1 跳过。失败包含知识写入接口失败、任务创建/配置及业务内容断言，未将它们计入字体专项通过结果，也未在本次字体范围内修改业务逻辑。

复验：在有演示数据的隔离服务环境及安装上述字体的 Chromium 主机执行 `E2E_BASE_URL=<前端地址> npx playwright test e2e/typography.spec.ts`。
