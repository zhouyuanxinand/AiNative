# 前序步骤返回与核对入口验证

日期：2026-11-06。分支：`codex/rd-platform-rebuild-20261031`。

## 变更

- 资料识别页面的“核对需求”从页尾移动至资料分析顶部，紧邻“重新分析资料”右侧；当前分析已采用且有效时提供入口。即使当前业务已推进到选型，返回资料识别也可继续核对需求。
- 平台导航统一识别返回前序步骤；提示修改前序资料可能影响下游结果，确认后才改变路由。取消不改变草稿或最近办理位置。
- 浏览器历史返回执行同一确认规则，保留前进记录。修复先打开步骤返回提示、再按浏览器后退时两种导航确认框叠加的问题。
- 不修改后端生成、采用、确认及失效规则。

## 实际验证

1. `web/tests/rd-navigation-history.browser.mjs` 完整文件通过，14 组检查。覆盖取消、Escape、历史前进/后退、同流程草稿、继续办理位置、辅助页面及 1440/390 像素布局。新增弹窗互斥回归先复现失败，定点修复后重跑完整文件通过；未放宽原断言和超时。
2. `web/tests/rd-source-analysis.browser.mjs` 完整文件通过。覆盖顶部入口唯一性、位置、窄屏换行、上传/模型草稿/等待限制及失败保留结果。使用隔离接口数据，无实际模型调用。
3. `npm run build` 通过 TypeScript 与 Vite 构建。保留现有产物体积提示。
4. 本地运行平台的 YLZJ 项目只读检查通过：64 条需求；返回资料识别时取消和确认均正确，顶部“核对需求”可回需求确认。检查前后项目版本均为 7，案例数据完全一致；无业务写入及模型调用，页面错误为零。
5. 前端严格静态审计仍有 25 项既有问题；与 `runtime/explicit-requirement-results/premium-audit.json` 按规则、文件、消息及等级对比，无新增或减少。本次不声明严格审计全绿。

## 证据

- `runtime/rd-backward-navigation-history/receipt.json` 及 8 张浏览器截图。
- `artifacts/20261106-source-continuation/receipt.json`；`adopted-analysis-continuation-desktop.png`、`adopted-analysis-continuation-narrow.png`。
- `runtime/backward-step-navigation/live-receipt.json`；`live-analysis-toolbar.png`、`live-return-warning.png`，已逐张检查真实项目截图。
- `runtime/backward-step-navigation/premium-audit.json`。

## 范围与限制

未运行无筛选全量、真实生成或 OA 登录验证。另尝试既有 `rd-case-journey.browser.mjs` 时，在本次导航检查之前被其旧的分析字段数断言阻断（预期 4，现有界面为 2）；该文件没有作为通过结果，原断言和超时保持不变，本次对它的临时修改已撤回。上述两个直接受影响文件与真实项目只读路径覆盖了本次修改。

当前工作树保留此前尚未提交的改动，本次未执行 Git 提交。
