# 需求行内编辑验证

分支：`codex/rd-platform-rebuild-20261031`。本轮复用原有 `save_requirement` 接口，不调整后台生成逻辑。

## 已执行

- `npm run build`：通过 TypeScript 与 Vite 生产构建；保留既有大包体积提示。
- `web/tests/rd-requirement-inline-edit.browser.mjs`：通过原位编辑、取消、失败保留、重试、来源选择、修订与原文对照、实际结果不被自动赋值、只读和 390px 布局验证；同案例切到项目流程再返回仍保留当前编辑行与正文草稿，搜索不匹配时仍保留活动编辑行。
- `web/tests/rd-requirement-decisions.browser.mjs`：完整文件通过，覆盖采纳/不采纳/澄清、筛选、草稿、错误恢复、只读及窄屏。
- `web/tests/rd-requirement-confirmation-recovery.browser.mjs`：完整文件通过，覆盖编辑草稿阻止阶段确认、取消后保留已采用结果，以及确认失败后返回恢复。

## 失败与定点处理

- 首次构建发现输入版本为可选类型，改为直接引用领域模型 `ResearchCase['input_revision']` 后重新构建通过。
- 新浏览器用例原文定位同时匹配段落和引用，改为精确段落 locator 后完整文件通过。
- 原确认恢复用例的全局“需求内容”locator 同时匹配行内及底部新增表单，改为目标行限定后完整文件通过。保留原断言和超时。
- 补充搜索断言时测试 placeholder 文本写错，改为实际语义标签定位后完整文件通过；没有放宽业务断言。

## 证据与范围

- 截图及回执：`artifacts/requirement-inline-edit/`，桌面失败保留状态和窄屏编辑状态均已目视检查。
- 相关回执：`artifacts/inline-decisions/`、`artifacts/inline-recovery/`。
- 浏览器使用真实前端与隔离 API 数据，地址为本地 18375；没有调用模型、修改真实项目或执行无筛选全量测试。本轮不声称已验证实际后端保存与完整任务书生成。
