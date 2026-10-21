# 反馈界面 UX Contract

## Scope and evidence

本约定仅适用于本轮 `web/src/components/feedback/`、`web/src/api/feedback.ts` 和 `web/src/feedback.css`，以及结果卡内的反馈入口。它不声明历史页面已经采用这些交互规则。视觉与令牌归属见 [DESIGN.md](DESIGN.md)。

用户需求是收集每次生成结果的好、一般、差评分和意见，并在独立 18131 管理入口查询、查看、增加、修改、删除和统计。主站接入神州问学统一登录后，用户名与账号来自后端验证；默认关闭的本地模式才允许手填姓名，并标记为未验证。侧栏与公开反馈共用 `CurrentUserProvider`，不能把请求失败降级为手填。

| Domain / scope | Authoritative source | Source type | Reviewed date |
|---|---|---|---|
| 公开提交与管理请求字段、错误和版本校验 | `basic-service/app/src/controller/feedback_controller.py` | 服务 API | 2026-10-15 |
| 持久化、快照、统计与去重 | `basic-service/app/src/service/jonhon_taskbook/feedback_store.py` | 领域实现及相应测试 | 2026-10-15 |
| 独立管理端口与部署边界 | `basic-service/app/src/feedback_main.py`、`README.md` | 服务入口及部署说明 | 2026-10-15 |
| 登录、可信身份及部署要求 | `basic-service/app/src/common/platform_auth.py`、`docs/platform-auth-migration.md` | 接入协议及实现 | 2026-10-15 |
| 统一登录配置及修改边界 | `basic-service/app/src/controller/auth_settings_controller.py`、`basic-service/app/src/common/auth_settings_store.py` | 版本化设置 API | 2026-10-15 |

## Canonical UI Map

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
|---|---|---|---|---|
| Select/Listbox | `web/src/components/ui/StyledSelect.tsx` | 已有 authored 下拉组件 | 筛选、评分与状态；隐藏原生 select 仅同步表单值，不打开平台菜单 | 浏览器选择评分和过滤条件；键盘与 portal 以共享组件行为为准 |
| Date | `FeedbackAdminPage` 的原生 `input[type=date]` | 本约定的原生所有权决策与 `web/src/api/feedback.ts` 边界转换 | 接受键盘日期录入及平台拥有的日历外观、语言和弹出几何 | 浏览器日期输入与北京时间请求边界断言；尚无完整平台日历矩阵 |
| Form | `GenerationFeedback`、`FeedbackRecordDialog` 及 `.feedback-textarea.resize-none` | 本约定与反馈 API | 公开提交、管理新增和编辑；textarea 固定布局及内部滚动 | 浏览器必填验证、输入保留、提交去重和保存流程 |
| Scrollbar | `web/src/feedback.css` 的表格局部样式与系统滚动条 | DESIGN.md 的表格几何决策 | 表格横向滚动；弹窗与长 textarea 保留系统滚动 | 390px 无页面溢出断言与截图；未声称已执行完整滚动条样式自动审计 |
| Toast | 反馈流程的 inline status/alert；不调用全站 Toast | 本约定的就地反馈决策 | 成功回执 `role=status`，错误 `role=alert`；不自动消失 | 浏览器成功回执和失败提示 |
| CRUD | `FeedbackAdminPage`、`FeedbackRecordDialog`、`FeedbackConfirmDialog` 与反馈 API | 反馈 API 版本契约 | 新增/编辑成功停留详情；删除回列表；查询保留 URL 状态 | `web/tests/feedback.browser.mjs` 完整流程 |

本轮没有表格多选和批量动作，因此 Table Selection 不适用。已有其他页面的原生 select 与纵向拖拽 textarea 不由本文件迁移。

## Flow and URL state

公开表单常驻生成结果卡，位于下载按钮之前；错误和取消任务也可关联任务提交意见，未生成的空状态不显示表单。提交不影响下载。统一登录模式的用户名和账号只读，后端据验证身份绑定；本地模式的手填用户名最多 80 字。评分必填，意见选填且最多 4000 字。成功显示服务端确认的回执；只有点击“再写一条反馈”才开启下一条。

管理入口为独立服务的 `/feedback`；公共提交和管理 API 按服务入口分开注册，前端所有请求使用相对路径。管理页自行设置文档标题。列表提供空状态、读取状态、错误与重试，详情从服务端重新读取，不只依赖列表摘要。

筛选草稿只有在“查询”后生效。已提交的 `q`、`rating`、`status`、`date_from`、`date_to`、`page`、`page_size` 写入 URL；默认值省略，浏览器前后退会恢复筛选。每页支持 10、20、50 条，默认 20；越界页回到最后有效页。详情和编辑是当前页弹窗，其未提交输入不进入 URL。统计来自服务端对全部匹配记录的汇总；`good_rate` 的 0–1 值转换为百分比。

所有绝对时间按 `Asia/Shanghai` 显示，页面明确标注北京时间。日期筛选表达北京时间自然日的闭区间，API 发送带 `+08:00` 的起止时间；服务端仍按 UTC 保存。日期值不与浏览器所在时区混用。

| Operation | Trigger / pending | Success | Failure / focus |
|---|---|---|---|
| 公开提交 | 提交反馈；所属输入禁用 | 就地回执，明确另写入口 | 保留输入及请求编号，错误在表单内；必填错误聚焦首个缺失控件 |
| 新增/编辑 | 新增反馈/保存反馈；所属表单禁用 | 返回该记录详情并刷新列表 | 保留草稿，错误聚焦至可见摘要 |
| 删除 | 带用户名、评分、编号的二次确认；确认期间禁用 | 刷新列表，焦点回记录标题 | 错误保留在确认弹窗；冲突要求重新查看最新记录 |
| 查询 | 查询/重置/分页；新请求取代旧请求 | 当前筛选记录及统计 | 错误在列表区域，提供重试 |
| 取消/关闭 | 关闭详情/取消编辑/Escape | 返回触发位置；原触发已移除则回列表标题 | 有未保存修改时需显式放弃；保存期间阻止关闭 |
| 退出登录 | 仅统一登录且已有身份时显示；有未保存内容先确认，处理中暂停退出 | POST 成功后同页导航 `/logged-out`，提供重新进入链接 | 错误就地保留并可重试；取消确认不发送请求，失败保留原草稿与离开保护 |

## Validation, async and conflicts

表单显式使用 `noValidate`，由组件做必填检查并展示中文错误；输入保留 `required`、类型和长度元数据。textarea 禁止拖拽改变布局，使用足够行高和内部滚动。评分与状态复用共享选择器。

写入采用服务端确认后更新界面的策略。认证公开提交只发送 `jid`、`rating`、`comment`、`request_id`；本地模式额外发送 `username`。相同草稿和账号的重试沿用请求编号，按钮和同步锁共同阻止重复点击；换账号后新建请求编号并提示确认。任务 ID 改变时重新挂载表单并中止旧请求。管理页查询切换中止旧请求；离开弹窗或页面也中止所属请求。20 秒超时会恢复可操作状态，操作结果未知时提示先核对。当前没有离线队列或自动保存草稿。

身份读取有加载、成功、未登录及错误状态，失败可重试；收到 401 后保留评分和意见并提示重新登录。统一登录在新标签页打开，完成后回原页重新读取身份，避免丢失草稿。客户端不读取登录 Cookie，也不从 URL、浏览器存储或用户请求体认定身份。

侧栏退出仅清除当前应用的登录 Cookie，不删除任务、文件或浏览器已保存选择，也不结束问学全局会话。`useApplicationLeaveGuard` 共享任务页、规则编辑、反馈草稿和指标澄清的离开状态；退出前通过既有确认弹窗说明未保存内容，点击“继续编辑”不发送退出请求。预检、生成、章节预览、规则处理、反馈提交和澄清创建期间暂停退出。POST 请求期间锁住页面交互并禁止关闭模态，避免退出请求发出后新增未保存内容；成功后才跳过共享 `beforeunload`，防止清除 Cookie 后再次取消导航。失败不清空输入、不关闭原离开保护；退出操作超时后可重试。本地模式和未登录状态不显示退出入口。

侧栏服务设置和私有反馈管理页复用 `PlatformAuthSettings`，它以独立模态表单保存登录开关、应用 ID、神州问学地址和回跳地址，不提交模型凭证。回跳为空时选择“自动跟随访问地址”，包括启用统一登录的情况，保存为 `public_url: null`；服务端按发起登录的主站请求确定回跳 origin，端口随部署访问地址变化。已有固定回跳保留“手动指定地址”；手动模式必填，只允许协议、主机及端口，拒绝路径、查询参数、片段和账号。界面不将私有管理页面的访问地址用作主站回跳预览。

内网和外网按钮使用设置 API 的 `presets` 填入应用 ID 与神州问学地址、将回跳改为自动，保留用户的启用选择；点击预设不直接保存。回跳方式复用 `StyledSelect` 的键盘、portal、焦点和禁用行为。配置保存只影响重启后的策略，提示明确说明生效时机；失败与 409 保留草稿，重新加载前确认放弃，关闭时保护未保存输入。已启用鉴权的主站只读，私有管理端可维护。该子模态通过 portal 与模型表单分离，取消和提交不冒泡至父表单。对应协议见 `auth_settings_controller.py`、`auth_settings_store.py` 和 `docs/platform-auth-migration.md`。

管理更新和删除携带 `expected_version`。HTTP 409 保留编辑输入，展示冲突及“读取最新版本”；重新读取会经过放弃修改确认，界面不会静默覆盖其他人的版本。关联任务快照、文件名及提交时的身份保持只读，前端不提交身份、快照、服务凭证或任务配置。管理员更正反馈展示名后，原账号、原姓名和来源仍保留；旧数据没有身份信息时不虚构验证状态。

## Accessibility and responsive behavior

字段有显式标签，必填错误设置 `aria-invalid` 并关联错误说明；状态同时使用文字。详情和确认采用原生模态 dialog 管理焦点与背景交互，支持 Escape；保存期间禁用退出。模态标题变化和保存错误移入可见焦点，关闭后恢复触发位置或有效列表标题。

宽度不足时表格保留语义列并在自身区域滚动，容器有可访问名称和键盘焦点；完整意见、参数和文件名可在详情读取。700px/520px 断点让筛选和详情逐步换为窄屏布局。减少动态效果偏好下停用反馈控件的 transition。以上是本轮的可访问性目标及已有行为，不声称完成全部 WCAG 2.2 AA 检查。

## Verification and legacy boundary

- `npm --prefix web run build`：TypeScript 与生产构建已通过。
- `web/tests/feedback.browser.mjs`：模拟 API 的新增、查看、编辑、版本冲突保留、删除确认、筛选 URL、北京时间边界、公开反馈必填、快速重复点击、重试去重和下载可用性已通过。通过 `PLAYWRIGHT_MODULE` 指向已有 Playwright，`PLAYWRIGHT_CHROMIUM_EXECUTABLE` 指向本机 Chrome，`TEST_BASE_URL` 指向启动中的 Vite；不新增依赖。
- `web/tests/identity.browser.mjs` 与 `web/tests/auth-settings.browser.mjs`：共享身份、只读姓名、401 草稿恢复、切换账号，以及独立登录配置的空地址、启用校验、409/503恢复、只读和未保存关闭保护已通过。原模型凭证及历史凭证浏览器回归已通过，登录配置保存不会提交或刷新模型凭证。
- 已查看 `runtime/feedback-browser/` 下桌面管理、手机管理、手机表单和回执截图（1440×1000、390×844）。这些验证使用模拟 API，真实持久化和隔离由 `basic-service/app/tests/test_feedback_*.py` 覆盖。
- 真实进程联调另以隔离的输出目录和 SQLite 运行主服务与管理服务（18132/18133），通过实际 SSE 显示测试任务并提交表单，验证跨进程读取、自动任务快照、查看/编辑/状态保存、筛选刷新恢复、删除和管理补录。未调用模型；测试数据不写入默认反馈库。脚本及截图位于 `basic-service/app/runtime/feedback-live-test/`。
- `premium-ui.json` 的静态审计覆盖 `web/src`，报告输出至 `basic-service/app/runtime/feedback-ui-audit.json`。审计不会执行浏览器测试；其历史页面 finding 独立报告，本轮只修复新增反馈代码的真实问题。执行命令为安装的 frontend-design-premium skill 中 `scripts/audit_project.py . --mode strict --output basic-service/app/runtime/feedback-ui-audit.json`。

2026-10-15 身份接入后的严格审计返回 21 条 finding（exit 1），未发现本轮反馈组件、API 或 CSS 的 finding；canonical map 无 unresolved。报告为 `runtime/identity-browser/ui-audit.json`。已移除侧栏无动作的假账户按钮，保留的范围外记录为：

| Rule | 数量 | 现有位置与判断 |
|---|---|---|
| `affordance.actionless-button` | 3 | 左右 resizer 用 pointer/double-click 处理，静态检查器未识别；ServiceCredentials 单项模型 tab 留待独立评估 |
| `form.novalidate-missing` | 5 | 故障库、管理面板、规则及模板等已有表单；本轮未改验证所有权 |
| `form.textarea-resize-missing` | 8 | 已有故障、规则、批注复核及上传输入；其中 indicator-review 纵向拖拽是既有行为 |
| `ownership.native-select-conflict` | 4 | 三个历史界面仍用原生 select；共享 StyledSelect 的隐藏原生值控件属于误报，实际菜单是 authored |
| `scrollbar.webkit-only` | 1 | 历史顶部导航的隐藏滚动条规则被通用主题检查命中；不是本轮表格滚动区域 |

这些记录使全量严格审计保持失败；本约定没有把历史差异改写为已修复或已迁移。

2026-10-21 自动回跳验证：`web/tests/auth-settings.browser.mjs` 通过启用时保存 `public_url: null`、API 内网/外网预设、不自动改变启用状态、历史应用 ID 与固定地址保留、手动地址校验、自动/手动只读、409/503 草稿保护、父表单隔离、未保存关闭及保存期间禁用退出。1440px/390px 视口验证了选择菜单宽度、键盘选择和 Escape 焦点恢复，窄屏字段及页脚可访问；同时通过生产构建和反馈浏览器回归。截图与审计报告位于 `runtime/auth-settings-auto-browser/`，审计仍为上述 21 条历史 finding（0 unresolved）。

2026-10-21 退出验证：`web/tests/logout.browser.mjs` 通过 OA/本地/未登录入口、重复点击单次 POST、成功跳转、存储保留、503/失败响应/网络失败恢复、收起与手机布局。真实规则编辑界面覆盖取消确认零请求、失败后保留草稿及离开保护、成功后不再弹原生确认；延迟预检覆盖请求完成前禁止退出、预检失败后恢复正常确认。共享身份浏览器回归和 TypeScript/Vite 构建通过；截图在 `runtime/logout-browser/`。

后续修改反馈行为时同步本约定、对应组件与验证证据；其他页面若需要采用这些选择，按独立任务评估，不据此宣布全站迁移。
