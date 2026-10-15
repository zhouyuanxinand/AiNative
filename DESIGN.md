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

本文件约束生成效果反馈表单、独立 `/feedback` 管理页及其详情、编辑和确认弹窗，以及侧栏当前用户展示与统一登录设置。它记录现有工程工作台中的设计选择，不声明全站已经迁移或通过审计。交互规则见 [UX-CONTRACT.md](UX-CONTRACT.md)。

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

## Elevation & Depth

静态工作面由边框和底色分层；只有模态弹窗使用 `--shadow-dialog` 与背景遮罩。`StyledSelect` 负责其列表弹层，并在弹窗内使用已有 portal 行为。

## Shapes

采用运行时的 8px 输入、10px 控件、14px 卡片和16px 弹窗圆角。状态标签保留紧凑矩形，避免和可点击按钮混淆。小图标沿用现有的线性 SVG，操作保留中文名称。

## Components

所有选择控件复用 `StyledSelect`；日期筛选明确接受原生日期输入的键盘录入、平台日历、语言和弹出几何。此处不承诺自绘日历。

反馈 textarea 使用 `.feedback-textarea.resize-none`：结果意见至少 70px，编辑意见 5 行，处理说明 3 行，长内容在输入框内部滚动。这样保持结果卡和弹窗操作布局稳定；已有 `indicator-review` 的纵向拖拽设置不属于本轮约定。

统一登录时，姓名以只读字段显示，账号可查看完整值；本地模式才显示可填写的用户名。侧栏和表单共用身份状态，加载、失败、未登录明确呈现，不能把读取失败显示为本地身份。管理页区分统一登录已验证、本地手填、历史未记录，原身份保持只读。

按钮有主要、普通和删除三种用途。提交期间禁用所属输入和动作，保留文字说明；成功回执与错误使用持久的就地反馈。弹窗采用原生 `dialog.showModal()`；删除和放弃编辑统一使用 `FeedbackConfirmDialog`。键盘焦点使用已有蓝色 outline。

表格滚动区域采用标准 `scrollbar-color`/`scrollbar-width` 和 WebKit fallback；这是表格几何的局部约定。其他输入与弹窗继续使用可见的系统滚动条。常规 hover 复用 150ms 令牌，减少动态效果偏好下取消反馈组件的 transition。

## Do's and Don'ts

- 区分自动识别的登录身份与本地手填姓名，保留三档文字评分、只读任务信息和明确的动作名称。
- 使用真实筛选结果统计，全文通过详情访问，窄屏滚动限定在表格内。
- 全站共享令牌或其他历史页面的差异，记录为后续独立工作；本轮不改变其规范地位。

## Verification

`web/tests/feedback.browser.mjs` 已通过模拟 API 的完整 CRUD、版本冲突保留、删除确认、日期边界、公开反馈验证和重试去重检查。已检查 1440×1000 与 390×844 的截图，产物位于 `runtime/feedback-browser/`。这不是完整的 WCAG 合规认证，也不代替真实后端测试。

`web/tests/identity.browser.mjs` 覆盖真实/本地/失败身份状态和草稿保护；`web/tests/auth-settings.browser.mjs` 覆盖未知部署地址、启用校验、独立保存、只读、错误恢复与子模态行为。已查看 `runtime/identity-browser/` 和 `runtime/auth-settings-browser/` 的桌面与手机截图。真实主站/管理服务的设置入口也已检查，应用 ID 为 `9192`、回跳为空、登录关闭；记录见 `basic-service/app/runtime/oa-migration/actual-login-settings.png`。
