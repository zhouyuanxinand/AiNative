# 流程切换、返回与首页检查

日期：2026-11-05。分支：`codex/rd-platform-rebuild-20261031`。本轮未提交代码。

## 修正

- 办理步骤、成果概览、项目流程、资料与依据、具体工作包进入地址状态，浏览器前进/后退与刷新可恢复。
- 辅助页返回最近编辑步骤；明确深链接优先。完成流程返回执行记录，避免概览自循环。
- 同案例切换保留挂载中的草稿；跨页面离开继续确认。修正刚输入立即后退的状态同步问题，取消后退不破坏前进历史。
- 项目列表返回保留筛选、分页及滚动位置；研发管理、知识管理各自保留搜索、范围与分页。
- 动作模板画布的固定版本、详情参数不再被应用入口清理；可连续刷新与跨模块返回。
- 删除重复标题和说明，统一“资料与依据”“返回办理”。首页沿用 Ant Design 与既有主题，桌面表格、窄屏记录布局，办理入口不依赖横滚。
- 首页关注排除旧执行和已完成流程，按当前流程去重；加载、失败、缺值与无记录分别展示。管理目录分页左对齐，避免默认助手遮挡。

## 定向验证

浏览器使用真实前端组件、隔离 API 响应；无真实项目写入或模型调用。没有运行无筛选全量。

| 完整测试文件 / 检查 | 结果 | 证据 |
| --- | --- | --- |
| `platformNavigation.test.mjs` | 4/4 通过 | URL 往返、无效步骤、路径入口、同案例判断 |
| `app-routes.test.mjs` | 7/7 通过 | 导航参数保留、认证参数清理、原管理/帮助/审阅入口 |
| `rd-navigation-history.browser.mjs` | 11 组通过 | [回执](../../../runtime/rd-navigation-history-final/receipt.json) |
| `rd-home-experience.browser.mjs` | 6 组通过 | [回执](../../../runtime/home-experience/after/receipt.json) |
| `rd-project-case-cards.browser.mjs` | 7 组通过 | [回执](../../../runtime/rd-project-cards-navigation/receipt.json) |
| `rd-management-return.browser.mjs` | 6 组通过 | [回执](../../../runtime/management-return/after/receipt.json) |
| `caseJourney.test.mjs` / `caseResume.test.mjs` | 复用本轮已通过的 40 条结果 | 后续未改这两个模块，未重复运行 |
| TypeScript / Vite 生产构建 | 通过 | 存在体积大于 500 kB 的原构建提示 |
| 修改区域 `git diff --check` | 通过 | 仅行尾转换提醒 |

运行方式：使用本机 Node 22 执行指定测试文件，`TEST_BASE_URL=http://127.0.0.1:18370`，`PLAYWRIGHT_MODULE` 指向已安装运行时。构建在 web 目录执行 `tsc`、`vite build`。

## 视觉复核

- [首页 1440px](../../../runtime/home-experience/after/01-home-1440.png)
- [首页 390px](../../../runtime/home-experience/after/02-home-390.png)，另验证 800px。
- [办理与返回 1440px](../../../runtime/rd-navigation-history-final/04-navigation-1440.png)
- [办理与返回 390px](../../../runtime/rd-navigation-history-final/04-navigation-390.png)
- [知识目录返回](../../../runtime/management-return/after/02-knowledge-return-1440.png)
- [窄屏分页点击](../../../runtime/management-return/after/04-pagination-390.png)
- [动作固定版本画布](../../../runtime/management-return/after/05-action-detail-return-1440.png)
- [返回动作目录](../../../runtime/management-return/after/06-action-directory-return-1440.png)

## 未通过项与边界

- 旧 `rd-case-journey.browser.mjs` 在初始字段数量断言失败：原期待 4 个，当前 2 个；封面阶段及归属已在此前按用户要求移至建项弹窗。保留该断言及超时，没有通过降低断言制造绿灯。该脚本还未覆盖新助手天气读取，未把整文件计为通过。[失败证据](../../../runtime/rd-case-journey-navigation/failure.json)。新增导航测试已独立覆盖本轮前进/后退、草稿与返回行为。
- 原项目卡测试仅因“资料与画像”改名而修改定位文本为“资料与依据”，其余断言与超时未改变，随后整个文件通过。
- Premium strict 静态扫描仍报告 25 项，主要位于其他旧页面、包装控件和原有滚动样式；本轮不把该扫描列为通过，也未扩大修改无关区域。[扫描结果](../../../runtime/navigation-premium-audit.json)。
- 未重新执行实际任务书生成、模型服务、OA 登录、后端全链写入或内网旧版浏览器。验证截图使用明确的隔离测试资料；不视作真实研发结果。
