---
version: alpha
name: "研发管理平台 · 工程工作台"
description: "统一项目、需求、任务、成果与审签工作区；任务书生成作为研发工具沿用受控生成能力。"
colors:
  primary: "#0071e3"
  background: "#f5f5f7"
  surface: "#ffffff"
  text: "#1d1d1f"
  muted: "#6e6e73"
  success: "#248a3d"
  warning: "#b25000"
  danger: "#d70015"
typography:
  sans:
    fontFamily: '-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif'
    fontSize: "15px"
  mono:
    fontFamily: '"SFMono-Regular",Consolas,"Liberation Mono",monospace'
    fontSize: "12px"
rounded:
  sm: "8px"
  control: "10px"
  card: "14px"
  dialog: "16px"
spacing:
  compact: "8px"
  field: "16px"
  section: "24px"
components:
  feedback-form:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.control}"
    padding: "{spacing.field}"
  feedback-admin-surface:
    backgroundColor: "{colors.background}"
    textColor: "{colors.text}"
  select:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.control}"
  dialog:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.dialog}"
    padding: "{spacing.section}"
  feedback-primary-button:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface}"
    rounded: "{rounded.control}"
  feedback-hint:
    textColor: "{colors.muted}"
  feedback-rating-good:
    textColor: "{colors.success}"
  feedback-rating-average:
    textColor: "{colors.warning}"
  feedback-rating-poor:
    textColor: "{colors.danger}"
---

# 研发管理平台设计约定

小航沿用平台蓝白令牌和系统中文字体。人物入口使用透明逐帧素材和 canvas 播放器，按脚底锚点与统一身高对齐，呈现眨眼、转桨和短暂挥手，不再对整张人物图旋转摇摆。入口完整占位，可鼠标/触屏拖动，松手停靠左右边缘；下方小牌提示“有事问小航”。点击后打开实际占据右侧空间的非模态工作栏，独立滚动，桌面通过边缘拖拽和键盘调整宽度，标题栏只保留收起按钮，业务页面保持挂载；收起恢复原位置的动效人物。390px 窄屏使用右侧全宽抽屉，`prefers-reduced-motion` 下人物保持静态。不显示模式切换，使用单一对话和自动意图识别。业务操作先展示固定草案、字段与影响，再复用 `FeedbackConfirmDialog` 确认；执行回执链接指向最新项目。帧图及锚点归属 `web/public/assets/xiaohang-idle-sprite.*`，原始 `xiaohang.png` 继续作为失败回退和头像；局部几何与播放器归属 `components/assistant/`，不引入新字体或全站主题。

原生任务书工作面沿用平台 slateblue 令牌与系统中文字体。`/rd/:pid/tasks/:tid` 以真实 ND13—ND15 阶段实例作为进度标记，输入、文档、WBS、审签和交接使用同页标签；非当前标签继续挂载，保留正文与安排。文档审阅器嵌入任务区，保留其目录、来源、正文独立滚动与窄屏切换。项目概览同页以上方流程、下方甘特共同读取 `project_plan.items`；蓝色表示计划，绿色标记实际记录，无结束记录时只标实际开工；工作条目的固定输入修订、接收状态和实际日期与排期同时可查。

本轮不新增颜色或字体来源。选择器继续归属 `StyledSelect`（包括文档修订），业务提交归属 `RdOperation`，离开、合并冲突、批准与发布确认归属 `FeedbackConfirmDialog`。私有草稿保存状态和错误常驻，不以成功状态代替批准或下发。演示预置文档明确标注“未调用模型”，独立生成工具放入辅助区并保留兼容 URL。

研发管理首版（2026-10-28）同样复用本文件的蓝白工程工作台、系统中文字体、等宽编号与 `web/src/app/styles.css` 运行时令牌。`/rd` 项目列表与项目工作区由 `web/src/features/rd/components/rd.css` 消费现有令牌，不另设主题值。当前基线以蓝色左线信息带常驻项目标题下方，表达当前工作的依据；状态文字同时区分自动检查与工程批准。工作区保持紧凑表格、自然增长的表单和统一项目页滚动，窄屏表格仅在自身横向滚动。标签页保留挂载以保留未保存输入，新增与编辑采用就地表单。选择器与确认动作分别复用 `StyledSelect` 和 `FeedbackConfirmDialog`，沿用既有焦点与语义色。

## Overview

2026-10-28 平台化改造后，主站统一为“研发管理平台”：总览 `/`、项目 `/rd`、需求中心 `/requirements`、任务 `/tasks`、成果 `/artifacts`、审签待办 `/approvals` 与任务书工具 `/taskbook` 共用 `PlatformShell`。主题面向连接器研发团队的桌面工程工作，首页以真实项目进度、需求基线、我的待办和最近操作为主体，不以生成工具的大幅宣传区作为首页。演示环境显式显示身份切换与“演示环境”标记，样例由后端持久化；界面不构造本地业务记录。

平台主题由 `web/src/app/layout/platform.css` 的 `.platform-shell` 局部覆盖既有语义令牌，范围内的 `StyledSelect`、按钮、项目表单及状态沿用同一来源；独立管理员页仍消费 `styles.css :root` 的基础主题。本文 frontmatter 保留基础主题值，平台作用域映射如下，不存在主题生成器或独立组件硬编码副本。

| 平台角色 | 运行时唯一来源 | 值 / 消费者 |
|---|---|---|
| 页面 / 工作面 | `.platform-shell --color-bg-page/--color-bg-surface` | `#f3f6fb` / `#ffffff`；总览、中心和项目页面 |
| 主操作 / 焦点 | `.platform-shell --color-action/--color-border-focus` | `#2563eb`；链接、按钮、当前导航及焦点 |
| 正文 / 次要文字 | `.platform-shell --color-text-primary/--color-text-secondary` | `#1e2d42` / `#63748b` |
| 分隔线 / 输入边框 | `.platform-shell --color-border/--color-border-strong` | `#e0e7f0` / `#cbd5e1` |
| 侧栏 | `--platform-sidebar-bg/text/active/line` | `#172a42` / `#aebdd0` / `#263f61` / `#2c405a` |
| 字体 / 状态语义色 | `styles.css :root` 的既有令牌 | 中文系统字体与等宽编号，成功/警告/错误继续共享 |

深蓝侧栏固定承载业务导航，白色顶栏与浅蓝灰内容区形成工作面；蓝色当前基线标记与项目推进表是识别线索。桌面侧栏 228px，780px 以下变为可收起的覆盖导航，内容区由 `.platform-content` 单独纵向滚动。表格保留语义列并在自身横向滚动，项目长表单保持自然高度；不将表格定高约束传播至其他标签页。首页标题 24px，表格正文 12px，次要信息 10–11px；项目详情继续保留可读的需求全文与修订依据。

本文件约束生成效果反馈表单、独立 `/admin` 管理员页面及其反馈详情、编辑和确认弹窗、运行日志，以及侧栏当前用户展示与统一登录设置。旧 `/feedback` 兼容跳转至管理员页面。它记录现有工程工作台中的设计选择，不声明全站已经迁移或通过审计。交互规则见 [UX-CONTRACT.md](UX-CONTRACT.md)。

服务对象是生成研制任务书的工程人员，以及核查意见的维护人员；界面的主要工作是填写评分、定位关联任务和维护处理结果。使用简体中文，桌面承担表格查询，手机可填写意见和读取记录。当前需求没有日本市场或日语界面范围。

视觉依据是已有任务结果卡和服务凭证设置：白色工作面、蓝色操作、细灰边框、适中的信息密度。反馈详情中标为“只读”的任务信息将意见与当时的参数、文件名对应起来；这一信息结构比装饰性图形更重要。

### Token ownership

`web/src/app/styles.css` 的 `:root` 是已有运行时令牌的唯一来源。本文件镜像其中的已采用值，`web/src/shared/styles/feedback.css` 通过 CSS 变量消费令牌；没有生成器、第二套主题或令牌迁移。

| 本文件角色 | 运行时来源 | 本轮消费者 |
|---|---|---|
| primary | `--color-action`，hover/selected/focus 取对应 action/border 令牌 | 主按钮、链接、选中评分、焦点 |
| background / surface | `--color-bg-page` / `--color-bg-surface` | 管理页、工作区、表单 |
| text / muted | `--color-text-primary` / `--color-text-secondary` | 标题、正文、帮助文案 |
| border | `--color-border`（`#dedee3`），输入取 `--color-border-strong` | 表格、卡片、输入 |
| success / warning / danger | `--color-success` / `--color-warning` / `--color-error` 及对应 bg/border | 评分、状态、错误、回执 |
| sans / mono | `--font-family-sans` / `--font-family-mono` | 中文控件与正文 / 任务及模型 ID |
| rounded / spacing | `--radius-*` / `--space-*`，局部几何见反馈 CSS | 卡片、控件、弹窗及间距 |

调整共享颜色、字体或圆角时，先核对运行时来源，再同步本文件；仅反馈布局的调整保留在反馈 CSS 中。

## Colors

浅灰页面承托白色卡片；蓝色用于主要动作与焦点。好评和已解决用成功色，一般和待处理用警告色，差评和错误用错误色。每个状态都有中文文字，颜色只提供辅助。当前只实现现有浅色主题。

## Typography

复用支持中文的系统无衬线字体，不引入字体下载。页面标题 20px，区域标题 16px，输入和正文 13–14px，时间与次要数据 12px。任务 ID 和模型 ID 使用等宽字体并允许断行；意见全文保留换行，表格摘要最多两行，全文从“查看”读取。统计数字使用等宽数字排版。

## Layout

结果卡反馈始终可见，位于下载操作上方；用户名、三档评分和选填意见保持紧凑，按卡片实际宽度自动换列。管理页最大宽度 1600px，筛选、统计和记录共用自然增长的页面，不把整页锁在固定高度里。

管理筛选在 1200px 以下换行，700px 以下使用两列，长关键词占整行；520px 以下反馈表单和详情字段使用单列。表格保留语义列结构，宽度不足时在自身区域横向滚动。详情弹窗最大宽度 860px，受视口高度约束并在内部滚动。具体几何以 `web/src/shared/styles/feedback.css` 为准。

统一管理员壳采用左侧“用户反馈 / 运行日志 / 管理员名单”菜单、右侧工作区；不在业务首页增加管理入口。桌面侧栏宽 216px，小桌面缩至 180px；700px 以下变为可展开的纵向管理菜单，选择后收起。顶部呈现管理员标题、当前账号、退出登录和仅主管理员可用的统一登录设置。反馈区仍自然增长，页面由浏览器滚动；日志列表仅在自己的深色阅读区域内滚动，不把反馈表单锁到固定视口高度。管理员壳样式归属 `web/src/features/admin/components/adminPage.css`，复用既有令牌，不引入新的颜色或字体来源。视图切换保留原有内容组件；选中项用蓝色底纹、图标、名称和 `aria-current` 共同标识。

管理员登录界面沿用 JONHON 标识、浅灰底和最大宽度 600px 的白色卡片，承载验证中、登录、拒绝访问和验证失败状态。管理员名单桌面为表格，700px 以下改为带字段名称的逐条记录；这是名单界面的局部布局，不改变反馈与日志表格的横向滚动规则。授权输入、回执和移除确认复用既有控件与语义色。

运行日志默认以“一次生成请求”为单位：白色表格呈现开始时间、用户、任务与文件、模型和结果；成功、失败、执行中使用已有语义色并始终附文字。请求详情先列身份、时间、文件及失败原因，再沿用深色过程日志阅读区，全文上下文不以省略号隐藏。页内“服务实时日志”作为次级入口，保留服务级即时诊断。表格在窄屏自身横向滚动，详情元数据降为两列，不给整个管理工作区新增固定高度。样式由 `requestLogs.css` 消费同一运行时令牌。

## Elevation & Depth

静态工作面由边框和底色分层；只有模态弹窗使用 `--shadow-dialog` 与背景遮罩。`StyledSelect` 负责其列表弹层，并在弹窗内使用已有 portal 行为。

## Shapes

采用运行时的 8px 输入、10px 控件、14px 卡片和16px 弹窗圆角。状态标签保留紧凑矩形，避免和可点击按钮混淆。小图标沿用现有的线性 SVG，操作保留中文名称。

## Components

所有选择控件复用 `StyledSelect`；日期筛选明确接受原生日期输入的键盘录入、平台日历、语言和弹出几何。此处不承诺自绘日历。

统一登录设置沿用服务凭证模态的白色工作面、字段间距和固定页脚。内网与外网预设使用并列的普通操作按钮，点击后在原字段中确认结果；自动/手动回跳使用 `StyledSelect`，手动地址仅在选择手动时呈现。自动模式用短文说明主站访问地址及端口随部署变化，不显示管理入口地址作为回跳。此调整不新增视觉令牌或改变其他设置表单。

反馈 textarea 使用 `.feedback-textarea.resize-none`：结果意见至少 70px，编辑意见 5 行，处理说明 3 行，长内容在输入框内部滚动。这样保持结果卡和弹窗操作布局稳定；已有 `indicator-review` 的纵向拖拽设置不属于本轮约定。

统一登录时，姓名以只读字段显示，账号可查看完整值；本地模式才显示可填写的用户名。侧栏和表单共用身份状态，加载、失败、未登录明确呈现，不能把读取失败显示为本地身份。管理页区分统一登录已验证、本地手填、历史未记录，原身份保持只读。

统一登录用户在侧栏账户信息下方看到“退出登录”，使用既有中性色普通按钮与线性图标；侧栏收起时保留图标和可访问名称。退出失败展开侧栏显示可重试的就地错误。未保存内容复用 `FeedbackConfirmDialog` 确认，退出请求期间以同一模态体系锁住交互；公开退出页沿用蓝白工作台、系统中文字体和圆角卡片，不依赖登录后的前端资源。

按钮有主要、普通和删除三种用途。提交期间禁用所属输入和动作，保留文字说明；成功回执与错误使用持久的就地反馈。弹窗采用原生 `dialog.showModal()`；删除和放弃编辑统一使用 `FeedbackConfirmDialog`。键盘焦点使用已有蓝色 outline。

表格滚动区域采用标准 `scrollbar-color`/`scrollbar-width` 和 WebKit fallback；这是表格几何的局部约定。其他输入与弹窗继续使用可见的系统滚动条。常规 hover 复用 150ms 令牌，减少动态效果偏好下取消反馈组件的 transition。

## Do's and Don'ts

审阅工作区保留固定可见的顶部操作区和桌面章节目录，长内容只在各自文档容器内滚动。为内网旧浏览器保留 `100vh` 回退；窄屏继续使用顶部“目录 / 来源 / 任务书”切换，定位后入口仍须可见。表格横向定位限定在表格内部，不将整个页面移出视口。管理员页面仍沿用自然整页滚动，两类页面的滚动边界不混用。

- 区分自动识别的登录身份与本地手填姓名，保留三档文字评分、只读任务信息和明确的动作名称。
- 使用真实筛选结果统计，全文通过详情访问，窄屏滚动限定在表格内。
- 全站共享令牌或其他历史页面的差异，记录为后续独立工作；本轮不改变其规范地位。

## Verification

2026-10-27 导航修复通过 `web/tests/browser/admin.browser.mjs` 与 `web/tests/browser/review-navigation.browser.mjs`：前者在禁用 `URLSearchParams.size` 的浏览器上下文中检查四个侧栏入口、前后退及筛选保留；后者检查长文档重复定位、待核对项、宽表格、双向来源定位、面板切回保留阅读位置和移动端目录入口。旧视口场景仅移除不受支持的 `100dvh` 声明，保留生产样式其余部分。桌面和 390px 截图已检查，位于 `runtime/navigation-fix/`；正文编辑/修订与版式编辑浏览器回归、TypeScript 和生产构建通过。以上兼容性测试在本机 Chrome 中模拟缺失能力，不等同于内网实际浏览器联调。严格静态审计仍为 21 条已记录历史 finding，本轮无新增命中。

`web/tests/browser/feedback.browser.mjs` 已通过模拟 API 的完整 CRUD、版本冲突保留、删除确认、日期边界、公开反馈验证和重试去重检查。已检查 1440×1000 与 390×844 的截图，产物位于 `runtime/feedback-browser/`。这不是完整的 WCAG 合规认证，也不代替真实后端测试。

`web/tests/browser/identity.browser.mjs` 覆盖真实/本地/失败身份状态和草稿保护；`web/tests/browser/auth-settings.browser.mjs` 覆盖未知部署地址、启用校验、独立保存、只读、错误恢复与子模态行为。已查看 `runtime/identity-browser/` 和 `runtime/auth-settings-browser/` 的桌面与手机截图。真实主站/管理服务的设置入口也已检查，应用 ID 为 `9192`、回跳为空、登录关闭；记录见 `basic-service/app/runtime/oa-migration/actual-login-settings.png`。

2026-10-21 自动回跳调整后，统一登录浏览器测试补充启用且回跳为空、内外网预设、历史固定地址保留、只读自动模式、手动校验和选择器键盘操作；截图已检查于 `runtime/auth-settings-auto-browser/`（桌面、手机及两种尺寸的选择菜单）。生产构建与反馈浏览器回归通过；DESIGN lint 为 0 errors / 0 warnings。全量静态审计仍为已记录的 21 条历史 finding，无新增文件命中。

2026-10-21 退出流程调整后，`web/tests/browser/logout.browser.mjs` 与共享身份浏览器回归通过；已检查 `runtime/logout-browser/` 的桌面、手机错误及未保存确认截图。键盘焦点、收起侧栏入口、失败重试、请求期间锁定、取消不提交和确认后单次导航均有浏览器验证；不将模拟 API 验证等同于真实 OA 联调。

2026-10-22 管理员页面合并后，`web/tests/browser/admin.browser.mjs` 覆盖左侧栏切换、深链接、前后退、反馈筛选与编辑草稿保留、日志轮询启停、失败/空态恢复及北京时间显示。桌面与 390px 手机截图保存于 `runtime/admin-browser/`。模拟 API 测试与部署服务联调分别记录；既有反馈 CRUD 和登录设置测试继续作为回归依据。严格静态审计仍为 21 条已记录历史 finding，本次变更文件无新增命中。

2026-10-22 完整请求归档界面通过 `web/tests/browser/request-logs.browser.mjs`：请求列表与结果标签、北京时间、状态/关键词及反馈 URL 参数隔离、全过程游标续读与去重、失败重试、记录过期、空态、执行中转成功、切走停止轮询、实时日志兼容。桌面与 390px 手机截图已查看，位于 `runtime/request-logs-browser/`；既有管理员壳和反馈 CRUD 浏览器测试也通过。此处是模拟 API 的真实浏览器证据，归档保存及自动清理由后端测试另行验证。静态审计仍为 21 条历史 finding，新请求日志文件无新增命中。


## 角色工作台与业务路线（2026-10-28）

主入口为“我的工作”和“项目空间”，需求、任务、成果、审签按职责归入跨项目查询，兼容原URL。首页以职责条、真实工作队列、路线阶段、阻断及办理留痕构成；同一人员的多项目职责可筛选，视角不改变项目权限。保留现有蓝白工程工作台、中文系统字体及platform.css令牌。

项目空间由RdProjectSurface统一组织三个主要区域：当前成果、项目流程、资料与画像。当前成果显示责任事项及固定版成果；项目流程汇合选型、交接、流程/甘特和项目任务；资料与画像包含需求/基线、项目上下文及来源、成员与办理历史。rdJourney.css只消费现有语义令牌，主签名为顶部四列项目上下文和三路线说明。所有分区继续挂载以保留草稿，窄屏四列改两列，路线说明改纵向。

任务书按当前责任打开输入、文档、策划、工程审签或发布与交接。历史批准包使用明确历史标签；当前效力同时核对采用修订、发布包、成果编号及输入影响。页面不因本轮角色或导航调整而改变原文精确复制与生成链。


角色边界修正：当前研发工作面仅区分项目负责人、工程师、独立评审和按需只读；以实际分派产生工作，不将全局参与者名单变成项目权限名单。首页职责仅在顶部说明一次，右侧聚焦实际推进阻断；成员设置按需展开，移除第二层视角选择器。
