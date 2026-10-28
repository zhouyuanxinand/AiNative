# 平台模型调用与配置迁移

2026-10-28，从 `D:/桌面/ai-zhonghang/zhonghang-service/agent-develop-task-doc-service` 迁入当前平台的模型部署配置。两项目的凭证管理、模型目录与连接探测实现原本一致，公共模型调用层沿用同一实现；内网模型应用默认号同步到来源项目的 `1000000033`，与 OA 登录应用分别配置。

先迁入来源主工作区的 15 项模型部署设置；再按用户指定，从 `codex/taskbook-expand-16-types` 的现有工作树读取私有 `.env` 和模型凭证历史，合并外网神州问学、DashScope 与原内网组合。配置只保存在本机仓库根目录 `.env` 及运行时凭证数据库，两者均被 Git 忽略。没有复制 OA 登录开关、登录回调或其他平台设置；现有本地身份放行策略不受影响。向量与重排端点按来源外网分支的做法跟随当前模型网关派生，避免切到外网后仍请求固定内网地址。

配置读取顺序为进程环境、仓库根 `.env`、打包的 `service/.env`、显式共享配置文件；仅允许模型配置白名单键，直接启动后端和通过启动脚本进入时使用同一凭证。模型请求和凭证历史共用现有 `service_credentials.sqlite3`，普通模型状态接口不返回密钥。

小航通过 `jonhon_taskbook.llm_client.chat` 复用神州问学、DashScope、Azure OpenAI、OpenAI 兼容调用。本机单独配置 `JTB_ASSISTANT_MODEL_PROVIDER=dashscope` 和 `JTB_ASSISTANT_MODEL=qwen-plus`，选择已实际连通的模型，不改变任务书已有供应方优先级或显式模型选择。可传 `timeout_seconds=60, retries=0`，仅对本次助手请求设置较短等待与一次尝试，不修改任务书的默认超时、重试或模型参数。Azure 缓存客户端也在每次请求上携带独立超时。任务书分类、路由、定值填充和正文组装规则未作修改。

迁移记录在本机 `basic-service/app/runtime/model-config-migration/proof.json`；连接探测证据在同目录的 `connectivity.json`、`external-connectivity.json` 和 `catalog-model-connectivity.json`。这些证据只记录键名、数量和结果，不含凭证。所有最小 `OK` 探测都没有提交项目材料：DashScope `qwen-plus` 已在约 0.47 秒返回真实 `OK`；内网网关在本机不可达。外网神州问学的模型目录可读，但来源旧默认模型及一次目录模型调用被其网关拒绝，因此小航默认采用已验证的 DashScope。

平台用户行的退出和设置入口复用来源项目的 `SidebarLogout` 与 `ServiceCredentialsSettings`。设置仅在用户主动开窗后按原同站协议读取，密钥仍使用原遮蔽输入；未将其注入用户身份、小航上下文或普通状态接口。保存/切换凭证后，就地刷新任务书模型目录，保留页面输入。统一登录配置的独立管理员权限沿用原组件。mock 退出会清除身份并设置已退出标志，业务 API 返回 401；打开退出页或刷新不会悄悄恢复负责人，只有点击“重新进入应用”或显式选择身份才创建新的本地会话。

验证：模型配置优先级、请求独立超时、文本/JSON 协议、服务凭证持久化、模型目录与连接探测相关测试共 106 项通过；mock 退出、原有 mock 身份与 OA 身份回归共 122 项通过。
