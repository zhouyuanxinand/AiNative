# 小航天气与平台对话

天气随现有 FastAPI 应用启动，无新增依赖或单独进程。默认涧西坐标 34.65878,112.3866（MET请求按4位小数），数据来自 MET Norway 全球模型预报，无需申请密钥。

- 天气读取：`GET /api/rd/assistant/weather`
- MCP Streamable HTTP：`POST /api/rd/assistant/weather/mcp`
- MCP 工具：`get_current_weather`，参数 `{}`，只读
- 全局平台问答：`POST /api/rd/assistant/chat`，`message` 与最多12条 `history`
- 持久会话：`GET/POST /api/rd/assistant/conversations`，详情`GET /{id}`，发送`POST /{id}/messages`，关闭`POST /{id}/close`；当前界面采用这组接口，写入要求Idempotency-Key，发送和关闭携带expected_version。

这些路径复用研发平台的身份、同源和会话边界；启用OA时，MCP客户端也需要有效平台身份，不提供绕过鉴权的公开入口。MCP支持初始化、工具发现、工具调用；GET SSE订阅不实现（405），采用无状态JSON响应。

天气10分钟缓存并合并并发读取，遵守上游Expires/Last-Modified；超时、错误或过期数据返回unavailable，不补造温度。MET采用过去3小时至未来1小时内的预报时间，Open-Meteo采用过去2小时至未来30分钟内的时间；缓存不会延长有效期。数据经中文归类、单位换算，前端展示来源和CC BY 4.0。参考 [MET服务约定](https://api.met.no/doc/TermsOfService)、[许可](https://api.met.no/doc/License)。

可选环境变量（均只在服务端）：

| 配置 | 用途 |
|---|---|
| `JTB_WEATHER_USER_AGENT` | 部署应用标识与真实联系URL；默认使用本仓库公开地址 |
| `JTB_WEATHER_MCP_URL` | 外部Open-Meteo兼容MCP服务的HTTP地址 |
| `JTB_WEATHER_MCP_API_KEY` | 外部MCP Bearer令牌 |
| `JTB_WEATHER_OPEN_METEO_API_KEY` | 改用Open-Meteo商业API |
| `JTB_WEATHER_DEMO=1` | 显式启用Open-Meteo非商业测试端点，非默认配置 |

外部MCP适配器对应 `cmer81/open-meteo-mcp` 的 `weather_forecast` 工具及Open-Meteo current结构，并非任意天气工具都可互换。配置外部MCP后失败会如实显示，不自动切换数据源。

配置可用时，平台问题、普通聊天与追问使用已确认的默认模型，支持连续对话；未配置时仍可提供标记为“操作指引”的常见问题回答。模型未配置或ID缺失时明确引导设置，调用失败时保留草稿并允许重试。导航/天气按钮由固定白名单控制，仅点击才执行；不自动创建项目或修改业务资料。

默认模型入口：系统管理 → 服务凭证设置 → 平台默认模型。GET/PUT `/api/settings/credentials/default-model`复用凭据设置访问边界；确认请求携带`provider/name/id`并由服务端核对真实目录。选择按当前凭据环境保存，不覆盖案例内明确指定的模型。当前本地环境经用户确认使用GPT-5.4；模型ID来自目录，不能复制到其他租户作为默认值。

鼠标悬停小人或键盘聚焦约500ms显示天气，移出约300ms收起；触屏通过聊天头部天气按钮访问。点击天气卡外或按Escape收起。来源与许可位于可展开的“天气来源”详情，保留预报时间，不把天气数据源失败显示成正常温度。

问候气泡按6秒展示/24秒隐藏循环；天气或交互优先。闲置人物增加失重漂浮、卫星绕行及连接器对接，沿用8–18秒静默和暂停规则。

全局会话关闭可选保留当前上下文与草稿，或结束后下次新开；已完成消息都会保存。历史预览可复制为新会话，原记录保持不变；服务端保存完整消息，模型读取最近12条。OA模式按账号保存，本地模式按当前浏览器身份cookie保存；清除该cookie会建立新本地身份。更新前仅存在页面内存中的旧聊天无法由服务端追溯恢复。
