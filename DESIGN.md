---
version: alpha
name: "研制任务书平台 · 反馈界面"
description: "沿用现有蓝白工程工作台，收集生成效果并维护可追溯的处理记录。"
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

# 反馈界面设计约定

## Overview

本文件约束生成效果反馈表单、独立 `/admin` 管理员页面及其反馈详情、编辑和确认弹窗、运行日志，以及侧栏当前用户展示与统一登录设置。旧 `/feedback` 兼容跳转至管理员页面。它记录现有工程工作台中的设计选择，不声明全站已经迁移或通过审计。交互规则见 [UX-CONTRACT.md](UX-CONTRACT.md)。

服务对象是生成研制任务书的工程人员，以及核查意见的维护人员；界面的主要工作是填写评分、定位关联任务和维护处理结果。使用简体中文，桌面承担表格查询，手机可填写意见和读取记录。当前需求没有日本市场或日语界面范围。

视觉依据是已有任务结果卡和服务凭证设置：白色工作面、蓝色操作、细灰边框、适中的信息密度。反馈详情中标为“只读”的任务信息将意见与当时的参数、文件名对应起来；这一信息结构比装饰性图形更重要。

### Token ownership

`web/src/styles.css` 的 `:root` 是已有运行时令牌的唯一来源。本文件镜像其中的已采用值，`web/src/feedback.css` 通过 CSS 变量消费令牌；没有生成器、第二套主题或令牌迁移。

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

管理筛选在 1200px 以下换行，700px 以下使用两列，长关键词占整行；520px 以下反馈表单和详情字段使用单列。表格保留语义列结构，宽度不足时在自身区域横向滚动。详情弹窗最大宽度 860px，受视口高度约束并在内部滚动。具体几何以 `web/src/feedback.css` 为准。

统一管理员壳采用左侧“用户反馈 / 运行日志 / 管理员名单”菜单、右侧工作区；不在业务首页增加管理入口。桌面侧栏宽 216px，小桌面缩至 180px；700px 以下变为可展开的纵向管理菜单，选择后收起。顶部呈现管理员标题、当前账号、退出登录和仅主管理员可用的统一登录设置。反馈区仍自然增长，页面由浏览器滚动；日志列表仅在自己的深色阅读区域内滚动，不把反馈表单锁到固定视口高度。管理员壳样式归属 `web/src/components/management/adminPage.css`，复用既有令牌，不引入新的颜色或字体来源。视图切换保留原有内容组件；选中项用蓝色底纹、图标、名称和 `aria-current` 共同标识。

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

- 区分自动识别的登录身份与本地手填姓名，保留三档文字评分、只读任务信息和明确的动作名称。
- 使用真实筛选结果统计，全文通过详情访问，窄屏滚动限定在表格内。
- 全站共享令牌或其他历史页面的差异，记录为后续独立工作；本轮不改变其规范地位。

## Verification

`web/tests/feedback.browser.mjs` 已通过模拟 API 的完整 CRUD、版本冲突保留、删除确认、日期边界、公开反馈验证和重试去重检查。已检查 1440×1000 与 390×844 的截图，产物位于 `runtime/feedback-browser/`。这不是完整的 WCAG 合规认证，也不代替真实后端测试。

`web/tests/identity.browser.mjs` 覆盖真实/本地/失败身份状态和草稿保护；`web/tests/auth-settings.browser.mjs` 覆盖未知部署地址、启用校验、独立保存、只读、错误恢复与子模态行为。已查看 `runtime/identity-browser/` 和 `runtime/auth-settings-browser/` 的桌面与手机截图。真实主站/管理服务的设置入口也已检查，应用 ID 为 `9192`、回跳为空、登录关闭；记录见 `basic-service/app/runtime/oa-migration/actual-login-settings.png`。

2026-10-21 自动回跳调整后，统一登录浏览器测试补充启用且回跳为空、内外网预设、历史固定地址保留、只读自动模式、手动校验和选择器键盘操作；截图已检查于 `runtime/auth-settings-auto-browser/`（桌面、手机及两种尺寸的选择菜单）。生产构建与反馈浏览器回归通过；DESIGN lint 为 0 errors / 0 warnings。全量静态审计仍为已记录的 21 条历史 finding，无新增文件命中。

2026-10-21 退出流程调整后，`web/tests/logout.browser.mjs` 与共享身份浏览器回归通过；已检查 `runtime/logout-browser/` 的桌面、手机错误及未保存确认截图。键盘焦点、收起侧栏入口、失败重试、请求期间锁定、取消不提交和确认后单次导航均有浏览器验证；不将模拟 API 验证等同于真实 OA 联调。

2026-10-22 管理员页面合并后，`web/tests/admin.browser.mjs` 覆盖左侧栏切换、深链接、前后退、反馈筛选与编辑草稿保留、日志轮询启停、失败/空态恢复及北京时间显示。桌面与 390px 手机截图保存于 `runtime/admin-browser/`。模拟 API 测试与部署服务联调分别记录；既有反馈 CRUD 和登录设置测试继续作为回归依据。严格静态审计仍为 21 条已记录历史 finding，本次变更文件无新增命中。

2026-10-22 完整请求归档界面通过 `web/tests/request-logs.browser.mjs`：请求列表与结果标签、北京时间、状态/关键词及反馈 URL 参数隔离、全过程游标续读与去重、失败重试、记录过期、空态、执行中转成功、切走停止轮询、实时日志兼容。桌面与 390px 手机截图已查看，位于 `runtime/request-logs-browser/`；既有管理员壳和反馈 CRUD 浏览器测试也通过。此处是模拟 API 的真实浏览器证据，归档保存及自动清理由后端测试另行验证。静态审计仍为 21 条历史 finding，新请求日志文件无新增命中。
