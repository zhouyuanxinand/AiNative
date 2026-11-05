# Ant Design 共享控件验收

日期：2026-11-03。范围：`StyledSelect`、`FeedbackDialog`、确认按钮及必要兼容样式；保留现有业务 props、状态和权限处理。

## 变更

- 下拉使用真实 Ant Design `Select`；保留外层 `.select-control` 和调用方 class，语义由按钮变为 `combobox`。没有隐藏原生 select；提供 `name` 时仅用隐藏 input 保留标准表单序列化。
- 兼容单项及分组、禁用、空项与占位、未知固定值、错误和辅助说明；禁用项明确提供 `aria-disabled`。
- 通用弹窗使用真实 `Modal`，确认按钮使用真实 `Button`。Ant Design 负责键盘和焦点锁定；调用方关闭即卸载组件时，由共享组件恢复触发点焦点，避免动画回调无法执行。
- 原生设置 dialog 内的下拉与嵌套弹窗进入该 dialog 的 top layer，防止被遮挡。保持遮罩关闭、未保存确认和忙碌保护。
- 长弹窗内容独立滚动，支持 390px 宽度。确认按钮加载时保持可访问名称。

## 已执行验证

| 验证 | 结果 |
| --- | --- |
| `antd-shared-controls.browser.mjs` | 5 组通过，0 业务 API 请求、0 页面错误 |
| Select 交互 | 键盘跳过禁用项；鼠标选择；分组；必填/错误/说明关联；未知值不清空；FormData；45 项列表滚动选择 |
| Modal 交互 | 内部空白、右键、从内容拖到遮罩不误关闭；仅关闭最上层；Tab 焦点锁定；Escape 先关闭下拉；关闭回到触发按钮 |
| 忙碌及旧页面兼容 | 忙碌确认不可取消；错误保留；原生 dialog 内的下拉和确认可点击；长内容可滚动 |
| 390px | 弹窗和下拉未超视口，无页面横向溢出，可访问最后一项 |
| `feedback.browser.mjs` | 管理页增删改查、409 保留输入、筛选、原身份保护、用户反馈重试等既有行为通过 |
| `dialog-dismissal.browser.mjs` | 凭证、嵌套登录、新建项目及确认、未保存与忙碌、焦点回退、移动端通过 |
| TypeScript `tsc --noEmit` | 通过 |

测试均在本地 Vite 18370 使用模拟接口或独立 React fixture，未修改真实凭证、项目、资料或反馈。旧反馈用例仅将两处下拉点击定位到 Ant Design 的真实可点击外壳，未放宽断言和超时。

截图和机器回执：`screenshots/2026-11-03-ant-design/shared-controls/`。长内容截图为明确构造的验收资料，不代表生成结果。上述浏览器验证使用本机 Playwright Chromium；不等同于已在内网 Chrome 104 实机验证。

## 集成约定

- 弹出下拉 class 为 `.platform-select-popup`，选择框内层为 `.platform-select.ant-select`。
- 弹窗是 body portal，包含 `.platform-feedback-modal.ant-modal.feedback-dialog`；原先依赖 `.rd-shell` 祖先的弹窗表单样式应同时覆盖 `.platform-feedback-modal`。
- 真实非搜索 Select 的 `combobox` input 被选中值覆盖是组件 DOM 设计。浏览器测试应以 combobox 定位实际 `.ant-select-selector` 点击，或用键盘打开；不使用 force、隐藏原生 select 或 `selectOption` 绕行。

## 集成修正后的最终复核

根代理修正 `danger-text` 到 Ant Design danger 映射、扩展弹窗表单作用域后，执行 `antd-integration-review.browser.mjs`，结果通过。

- 实际主页的新建项目弹窗：桌面项目名称/目标占满 572px 栏宽，客户/产品各占满 277px 栏宽；390×640 下全部文字输入占满 334px 栏宽。
- 窄屏弹窗边界为 `(12,12)–(378,628)`，内容高度 588px、可视高度 541px，实际滚动至底部操作区，无横向溢出。
- 空表单点遮罩直接关闭；已填写后出现放弃确认，选择继续填写保留原输入。最后通过关闭确认退出，未创建项目。
- 模拟管理员页面中的“删除反馈”“移除管理员”均有 `ant-btn-dangerous`，计算颜色均为 `rgb(255,77,79)`；仅查看按钮，未点击危险操作。
- 0 写请求、0 页面错误。截图和机器回执：`screenshots/2026-11-03-ant-design/integration-review/`，共 5 张截图。
