# 小航助手与能力扩展

小航默认在右下角提供逐帧人物入口，可使用鼠标、触屏或方向键移到屏幕两侧，Home恢复默认位置。逐帧素材按脚底锚点对齐，待机眨眼、转桨，指针经过时短暂挥手；拖动和页面隐藏时暂停，减少动效偏好下静态呈现。刷新保留非敏感的位置偏好。点击打开右侧工作栏，可以调整宽度或收起，收起后在原位置恢复动效人物。用户使用一个对话入口；小航自动识别业务问答、业务操作、导航和普通问题，确定业务意图后才读取有权访问的项目摘要。普通问题不额外附加项目资料。会话仅保留在当前页面，刷新或切换身份后清除。停止等待不会执行任何业务命令。

模型凭证与调用复用任务书服务的 `jonhon_taskbook.llm_client` 和服务凭证设置。外网配置来自 `codex/taskbook-expand-16-types` 对应工作区；小航通过 `JTB_ASSISTANT_MODEL_PROVIDER`、`JTB_ASSISTANT_MODEL` 选择已验证可用的 DashScope / qwen-plus，与任务书的用户选模相互隔离。内网配置保留在服务端凭证历史。配置路径和迁移结果见 [模型配置迁移](model-configuration-migration.md)，文档不记录密钥。

当前接入能力：保存需求、创建任务、重新分派任务、确认需求基线、工程审签、发布批准计划、登记选型、登记直接交接、开始任务。需求局部修改只需给出需求 ID 和变更字段，服务端保留未更改的完整正文、来源和验收要求，不用模型摘要覆盖原文。

自然语言操作链路为：问题与权限内摘要 → 模型提出已注册能力及参数 → 服务端调用现有领域逻辑预检 → 展示固定操作草案 → 用户确认 → 原领域命令执行 → 回执。草案不是批准，模型答复不是工程事实。确认之前只保存草案，不修改项目。缺少证据、参数不全、对象不明确或无权限时不能生成有效操作。

草案存放在项目 SQLite 的 `assistant_operation_proposals` 表，绑定当前用户、项目版本、能力定义和固定参数，十分钟有效。确认接口只接受草案 ID，不接收替换参数；执行时重查权限，使用固定请求键复用现有 CAS 与持久化幂等。审签仍要求指定独立评审和有效固定版本，发布仍要求负责人及有效批准包。现有业务表单有未保存输入时，浮窗阻止旁路执行。

HTTP 接口：

| 接口 | 用途 |
|---|---|
| `GET /api/assistant/context?project_id=...` | 权限内项目摘要、建议问题和可信快捷入口 |
| `POST /api/assistant/chat` | 默认自动识别意图；业务意图可返回待确认草案，兼容旧调用方显式模式 |
| `GET /api/assistant/capabilities?project_id=...` | 当前项目职责可用的能力、参数 schema 和确认要求 |
| `POST /api/assistant/operations/prepare` | 为指定 `project_id/action/payload` 预检并保存草案 |
| `POST /api/assistant/operations/{id}/confirm` | 显式确认固定草案，返回执行回执与项目链接 |

脚本与 skill 扩展点位于 `assistant_operations.py` 的 `OperationCapability` 与 `register_capability()`。注册项包含固定 ID、`kind=domain_command/script/skill`、中文说明、闭合参数 schema、允许的项目职责、只读预检处理器和执行处理器。扩展项由服务端代码登记，HTTP 与模型都不能注册任意程序或决定可执行文件路径。

实现新的脚本或 skill 时，在受控处理器中固定调用目标，并显式解析参数、设置执行超时、保存执行记录。`execute_handler(store, actor, project_id, payload, expected_version, request_key)` 接收稳定请求键，必须由脚本/skill 所属执行系统落实持久化去重后返回项目视图。修改能力含义时提升 `version`，旧草案自动失效。本轮提供注册和分发接口，未虚构其他三平台的远程 API 或安装未知 skill。

验证包括助手 HTTP 与操作专项测试、前端行为测试、`web/tests/browser/assistant.browser.py` 交互状态测试，以及 `tests/e2e/rd_assistant_browser_smoke.py` 的真实 HTTP + SQLite + 浏览器链路。浏览器隔离测试使用合成模型输出，不调用外部模型；真实模型连通单独以最小问候验证，不发送工程原始文件。

最终验证：本轮问答、自动意图、操作、模型配置与退出相关后端150项通过，前端55项通过，生产构建通过。浏览器实际验证单一会话自动分流、外网qwen-plus回复、设置密钥遮蔽、退出态保持和显式重新进入。自然语言新增需求已在临时合成项目完成“识别→草案→确认→领域写入”；当前生产项目未作测试性修改。完整检查范围与历史脚本限制见 `rd-platform-v1.md`。
