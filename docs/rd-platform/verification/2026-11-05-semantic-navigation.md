# 语义地址、网站图标与小航定位验证

## 本轮范围

浏览器图标、研发平台规范页面路径、目录筛选与返回状态、流程模板固定版本定位，以及小航结构化页面引用。研制任务书生成、审批规则及数据迁移不在本轮改动范围内。现有未提交的画像、证据定位、界面与品牌改动予以保留。

## 已完成验证

| 验证 | 结果 |
| --- | --- |
| `platformNavigation.test.mjs` | 8 项通过：路径、旧链接、当前目录筛选、引用校验 |
| `app-routes.test.mjs` | 7 项通过：研发入口与原有独立入口 |
| `assistant/nativeNavigation.test.mjs` | 4 项通过：旧目标兼容、结构化定位、跨案例拒绝、工作包定位 |
| 运营投影单元测试 | 11 项通过 |
| `test_navigation.py`、`test_assistant.py`、`test_spa_entry_routes.py` | 37 项通过：授权上下文、只读行为、助手兼容、SPA 深链入口 |
| `rd-navigation-history.browser.mjs` | 11 组通过：旧链接、前进后退、草稿、滚动与继续办理 |
| `rd-management-return.browser.mjs` | 6 组通过：目录独立筛选、返回、固定版本 |
| `rd-operations-dashboard.browser.mjs` | 6 组通过：投影与筛选、URL 刷新恢复、重置 |
| `rd-workflow-template-location.browser.mjs` | 通过：筛选、版本、历史页、刷新与无效目标 |
| `rd-workflow-template-lifecycle.browser.mjs` | 通过：既有生命周期、草稿、冲突、权限及窄屏行为 |
| 小航工作包浏览器专项 | 结构化工作包跳转、刷新及旧资料目标通过；无业务写入 |
| `npm run build` | TypeScript 与 Vite 生产构建通过；仍提示现有大体积 JS 分包建议 |

仅运行上述受影响文件，未执行无筛选全量测试。

## 本地真实项目只读复核

本地前端 `18370`、主后端 `18372`：

- 原冗长查询串进入后替换为 `/projects`，真实项目仍可见。
- 旧项目／流程／步骤链接进入同一资料页面。
- 后端目录全部 24 条页面契约与前端编解码路径一致。
- 当前用户可读取授权页面上下文，返回当前阶段、版本和资料数量。
- 资料、项目流程、依据、过程记录四种深链可直接打开并刷新。
- 主后端生产入口能够返回深层页面与新 favicon。
- 无浏览器 JS 异常、无业务写请求、项目版本未变化。

首次真实浏览器复核使用了本地历史记录中另一项目的 ID，被服务端正确拒绝；改为从当前账号项目列表取实际 ID 后，完整只读复核通过。未放宽授权检查或测试超时。

截图及运行收据：`runtime/semantic-navigation/live-01-projects.png`、`live-02-materials.png`、`live-smoke-receipt.json`。图标已复核 16、32、64 像素及明暗背景，预览在 `runtime/favicon-preview/favicon-sizes.png`。

## 未覆盖及现存提示

- 未在内网 OA 实际服务器或 Chrome 104 实机测试；保留原 OA 回跳链，构建目标仍为 Chrome 104。
- 未重新调用模型、生成任务书或执行业务确认，避免改变真实项目状态。
- 全项目静态 UI 扫描有 25 条存量提示，未宣称全站扫描通过。涉及旧页面、原生控件或事件展开写法；本轮涉及的小航按钮使用 `launcherEvents` 传入指针和键盘事件，扫描器将其误报为无操作。此次不扩展为无关页面重构。
- 本轮提供稳定位置、只读上下文与受控导航，尚未实现跨会话业务事实记忆库或自动业务审批。
