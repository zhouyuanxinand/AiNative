# 小航天气、气泡与对话验收 — 2026-11-04

后续修复：本文件记录首轮结果。默认模型500已在用户确认GPT-5.4后解决，并完成真实连续对话、默认模型设置及天气悬停/外部关闭验收，见[后续验证](2026-11-04-xiaohang-default-model.md)。

范围：当前 rd-platform-rebuild-20261031 工作树的 FloatingAssistant、人物动作、未选案例的对话、天气 HTTP/MCP 及有关接口。既有案例助手协议、业务写入、模型配置未更改；本轮没有运行无筛选全量测试。

## 已执行

- `python -m pytest tests/rd_platform/test_weather.py`：29项通过。真实预报、缓存合并与过期、异常数据、MCP初始化/调用/失败/身份边界；weather.py及controller的ruff通过。
- `python -m pytest tests/rd_platform/test_platform_chat.py`：19项通过。固定指引、模型上下文、白名单动作、错误与长度校验；“开始一项新任务”先复现失败后修复，再验证整个该文件。
- `node --test web/src/features/rd/assistant/launcherGeometry.test.mjs web/src/features/rd/assistant/xiaohangMotion.test.mjs`：7项通过。拖拽边界与持久化、8–18秒静默、动作选择/不重复、hover冷却与计时清理。
- `node tests/xiaohang-companion.browser.mjs`：隔离API夹具通过。中文输入法/发送/失败重试/关闭保留，输入天气后显式打开卡片，左右边缘拖拽收起、键盘/点击唤回、Home复位、刷新保持隐藏，天气气泡冷却、来源链接点击、减少动态效果、390×700及900×420视口，未观察到页面异常。问候气泡位于小人上方且可点击。
- `npm run build`：TypeScript及Vite生产构建通过，保留大于500kB分块的构建警告。
- 真实天气：MET Norway请求成功；外部Open-Meteo MCP客户端初始化/调用成功；官方MCP SDK连接本地内嵌服务完成初始化、发现get_current_weather及真实调用，临时服务均清理。
- 当前本地服务：确认研发数据库无submitted/running任务后，在原工作目录与环境重载18372后端；18370页面实测天气、操作问答和天气气泡均通过，页面无Runtime异常。截图与回执在 `runtime/xiaohang-companion/`。

浏览器插件因缺失其指定版本的browser-service.mjs无法引导，依照项目已有测试方式使用Playwright Core与Chromium headless shell 1248。未使用真实生产账号或执行业务写入。

## 实际限制

自由问答的真实请求已进入现有smartvision默认模型，日志记录上游HTTP500，平台返回可重试的503。常见操作指引和天气独立正常工作。没有擅自替换用户的模型、密钥或服务配置；不能将本轮模拟模型分支测试描述为真实模型答复通过。

严格UI静态审计仍报告24项：当前小航入口的1项是无法识别展开的launcherEvents点击事件的静态误报，已用真实点击/键盘验证；其余位于本次范围外的已有控件、样式或设计文档。不宣称全站静态审计通过。报告：`runtime/xiaohang-companion/ui-audit.json`。

未覆盖真实内网Chrome104、完整业务生成链、完整OA浏览器流程或所有历史页面；这次验证不能代替其验收。天气为模型预报且保留来源、时间与许可，不是气象站实况或预警。
