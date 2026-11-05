# 小航默认模型与设置、天气交互复核

## 模型故障与修复

原默认名称`openai/qwen3.6`不在目录中，ID为空。真实上游HTTP500业务code1003明确要求正数model_id；补齐Qwen3.6-35B目录身份后，另遇上游模型连接失败code1000。GPT-5.4同凭据、完整目录身份真实调用成功，用户明确选择GPT-5.4，已通过设置API持久化。

新增当前环境的默认模型设置，校验真实目录provider/name/id完整身份，按连接环境与优先次序保存。案例明确选择仍优先；无效ID停止调用并指引设置。普通聊天改为模型优先，保留平台只读权限、历史长度与身份边界。

真实API两轮聊天保留“蓝桥计划”上下文；最终实际浏览器两轮聊天均HTTP200且mode=model，正确记住“星桥”。日志确认azure/gpt-5.4实际调用成功；不是固定指引或模拟模型回包。当前使用服务为18370页面、18372后端；重启前检查无submitted/running任务，保留原环境与凭据。

## 交互与验证范围

- 后端4个受影响完整文件79项通过：`test_default_model_settings.py`、`test_service_credentials.py`、`test_maas_usage_identity.py`、`rd_platform/test_platform_chat.py`。覆盖实际HTTP请求体、ID有效性、目录错误、环境隔离/优先级、显式案例模型、匿名身份和连续对话。新用例先失败再修复；既有断言和超时保留。
- `xiaohang-companion.browser.mjs`通过：悬停500ms、移出延迟、键盘、来源详情、点击外部关闭、拖边隐藏、中文IME/重试、长回复、触屏、320/390px及短屏；无页面运行异常。
- `default-model-settings.browser.mjs`通过：完整ID、同名模型、失败重试、取消恢复、草稿/保存锁、凭据变更后重读、1024/390px。
- `settings-tools.browser.mjs`通过：模型连通测试、ID/手工输入、失败重试；统一登录自动/手动回跳、非法地址、独立保存、预设、嵌套草稿和手机页脚。
- `rd-system-settings.browser.mjs`通过：账号与登录、模型服务、管理员入口、能力与数据接入；导航/深链、保存重试、历史切换、目录错误。修正AntD选择器的交互定位，未放宽断言或超时。
- `npm run build`通过TypeScript及Vite构建；已有大于500kB分块警告仍存在。
- 最终真实页面天气与设置验收通过：点击天气卡外关闭、悬停小人显示真实预报、移出收起、设置显示已确认GPT-5.4，无页面异常。首次天气验收遇数据源短暂失败；独立公开MET请求及本地接口随后均返回有效预报，因此仅重跑天气/设置段，复用已通过的两轮真实模型结果，没有放宽断言或增加超时。

浏览器插件因缺失服务脚本无法启动，沿用项目Playwright Core与Chromium1248。截图位于`runtime/xiaohang-companion/`和`runtime/settings-model-browser/`。设置写入行为使用隔离API夹具，真实环境只保存用户确认的默认模型，不修改登录或其他凭据。

未运行无筛选全量；复用上一轮天气/动作测试结果。历史`model-connection.browser.mjs`和`auth-settings.browser.mjs`仍绑定旧自绘选择器DOM，本轮未运行；相应关键行为由新设置夹具验证。管理员内部CRUD、完整业务生成、真实OA登录与内网Chrome104不在本次覆盖范围。
