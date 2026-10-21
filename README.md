# 研制任务书受控生成服务 (agent-develop-task-doc-service)

由 FastAPI 后端 + React SPA 前端 + nginx 反向代理组成。容器内 nginx 主站监听 80 端口，
提供 `web/dist/` 构建产物，并把 `/api` 请求转发到 `127.0.0.1:18130`。
反馈管理使用独立进程 `127.0.0.1:18131`，由 nginx 的 81 端口转发。

受控生成流水线：LLM 只做需求语义分类与原文定位（路由 JSON），正文由原文精确复制
装配；配合分段识别、覆盖率核验、QA 门禁与交付门禁，产出可追溯的研制任务书 DOCX。

2026-09-17 新增产品正式启用：15 类已可选择使用，加上原有 2 类共 17 类；1 类缺流体模板。状态、映射和验证范围见 [16 类产品接入记录](docs/product-template-intake-20260916.md)。

## 目录结构

```
agent-develop-task-doc-service/
├── basic-service/
│   ├── requirements.txt / requirements-dev.txt
│   └── app/                      ← 运行时根（uvicorn 的 cwd）
│       ├── resources/            application.yml + application-{dev,test,prod}.yml
│       ├── data/                 运行期数据卷（uploads / outputs / 种子资源）
│       ├── logs/                 运行期日志
│       ├── tests/                pytest 单测
│       └── src/
│           ├── main.py           FastAPI 应用工厂（lifespan + 中间件链）
│           ├── feedback_main.py  独立反馈管理应用（仅管理 API + 管理页面）
│           ├── pipeline_cli.py   流水线统一入口（CLI 与 Web 共用）
│           ├── controller/
│           │   └── taskbook_controller.py   全部 /api 路由
│           ├── common/           logger.py / request_context.py
│           ├── utils/            config_loader.py（AppConfig frozen dataclass）
│           └── service/
│               ├── config/       12 个受控业务规则 YAML
│               ├── prompts/      受控 LLM 提示词 .md
│               └── jonhon_taskbook/  核心业务包（40 模块）
├── web/                          单文件 SPA（index.html + assets/ + nginx/）
├── Dockerfile / docker-compose.yml / entrypoint.sh
├── build_.sh / run_.sh / start.ps1 / stop.ps1
└── .env.example
```

## 前置条件

- 生产镜像使用 Python 3.13；本地无 3.13 时可用 3.12 验证。
- Windows 使用 PowerShell 5.1+；Linux/macOS 使用 Bash。
- 容器运行需 Docker 与 Docker Compose v2。

## 环境配置

`.env.example` 是无密钥模板。按需另存为 `.env` 并填写凭据；仓库不提交真实密钥。
Compose 会读取同目录 `.env`，所有值仍可被环境变量覆盖。

常用变量：`APP_ENV`、`JTB_HOST`、`JTB_PORT`、`CORS_ORIGINS`、
`JTB_MAX_UPLOAD_MB`、`JTB_MAX_CONCURRENT_JOBS`、`JTB_ALLOW_LOCAL_PATHS`、
以及 LLM 凭据 `MODEL_*` / `AI_*` / `JTB_LLM_*` / `AZURE_*`（四选一）。

左侧栏底部的齿轮按钮打开“服务凭证设置”。模型设置支持神州问学的 Base URL、
App ID、API Key 和租户 ID，保存后立即刷新模型目录；密钥默认隐藏，可恢复部署默认凭证。
页面配置保存在 `basic-service/app/runtime/service_credentials.sqlite3`，重启后保留，
可用 `JTB_SERVICE_CREDENTIALS_DB` 指定保存位置。容器部署时持久化 runtime 目录。

页面保存的模型凭据优先于部署默认值。部署默认值仍按“进程环境 > 本项目 `.env` >
`JTB_SHARED_ENV_FILE` 指向的共享 `.env`”读取。其他模型供应方继续使用各自部署配置。
凭据不写入浏览器本地存储、公开模型目录、日志或生成文档。

语义分类与规划的 JSON 请求首轮输出额度为 16384 token，发生截断时提升到配置上限重试一次，
默认上限为 32768（包含模型推理用量）。神州问学用 `MODEL_MAX_TOKENS` 调整上限，
JTB、Azure 和通用 OpenAI 兼容配置用 `JTB_LLM_MAX_TOKENS`；显式配置的小额度仍会被遵守。
`/api/llm/status` 返回当前生效的 `max_tokens` 和 `json_initial_tokens`，便于部署后核对。

## Windows 本地启动

```powershell
.\start.ps1
```

构建虚拟环境、安装依赖，并在后台从 `basic-service\app` 启动主服务和反馈管理服务。
日志写入 `basic-service\app\logs\backend-startup.{stdout,stderr}.log` 和
`feedback-startup.{stdout,stderr}.log`。端口占用时启动失败，不停止其他程序。
`runtime/local-services.json` 保存两个进程的 PID，停止脚本同时校验虚拟环境与入口模块。
停止两个服务：

```powershell
.\stop.ps1
```

## Linux/macOS 本地启动

```bash
chmod +x run_.sh build_.sh entrypoint.sh
./run_.sh
```

`run_.sh` 会创建虚拟环境、装依赖并监督两个服务。`Ctrl+C` 停止两个进程；任一服务
退出也会停止另一个。也可在 `basic-service/app` 中单独运行 `python -m src.feedback_main`。

本地启动前先在 `web` 目录执行 `npm ci && npm run build`，两个服务均优先提供同一份
`web/dist` 构建产物。

## Docker 与 Compose

```bash
docker compose up --build -d
docker compose logs -f
docker compose down
```

默认端口映射 `127.0.0.1:18130:80` 与 `127.0.0.1:18131:81`，仅本机访问。远程暴露须同时调整端口绑定、
CORS、TLS 与认证。三个命名卷持久化数据、日志与运行期候选：

- `taskbook-data` → `app/data`
- `taskbook-logs` → `app/logs`
- `taskbook-runtime` → `app/runtime`

后端以非 root 用户 `agent-taskbook` 经 `gosu` 降权运行。
容器入口监督主后端、反馈管理后端和 nginx 三个进程；健康检查同时验证两个入口。

发布镜像默认启用内网统一登录：应用 ID `127`、神州问学地址 `http://172.23.255.36`，
回跳地址留空，自动跟随主站访问地址与发布端口。Dockerfile 的四项 `JTB_AUTH_*` 环境变量
覆盖包内 `.env` 的鉴权值，因此本地外网测试配置不会成为纯镜像部署的默认登录配置。
Compose 的 `env_file: .env` 属于部署时环境注入，仍可覆盖镜像默认值；现场应使用对应环境的
配置文件。已在界面保存的登录配置优先于这些环境变量，升级镜像不会重置它。

本地修改反馈管理端口使用 `JTB_FEEDBACK_PORT`（默认 `18131`），监听地址使用
`JTB_FEEDBACK_HOST`（默认 `127.0.0.1`）。Compose 修改对外端口使用
`JTB_FEEDBACK_PUBLISHED_PORT`，例如设为 `18141` 后访问 `http://127.0.0.1:18141/feedback`；
容器内管理后端固定监听 `18131`、nginx 固定监听 `81`。

Kubernetes 清单为管理入口提供独立 ClusterIP Service；本地访问可执行：

```bash
kubectl -n agent-develop-task-doc port-forward service/agent-develop-task-doc-feedback 18131:81
```

## 访问地址

- 应用：`http://127.0.0.1:18130/`
- Swagger：`http://127.0.0.1:18130/docs`
- 健康检查：`http://127.0.0.1:18130/api/health`
- 反馈管理：`http://127.0.0.1:18131/`（跳转至 `/feedback`）
- 管理健康检查：`http://127.0.0.1:18131/api/health`

## 用户反馈与管理

生成结果页可提交用户名、评价和补充说明；服务端自动保存提交时间、任务参数、模型、
原始文件名和生成状态快照。默认本地模式由提交者填写用户名，并标记为未验证。
配置神州问学统一登录后，侧栏与反馈表单自动显示平台验证的姓名、账号；公开提交时
服务端绑定身份，不信任客户端填写的姓名。管理页保留提交时的原身份，并支持按账号查找。

统一登录的参考实现对比、配置和验证范围见
[鉴权迁移与接入说明](docs/platform-auth-migration.md)。登录应用编号与模型服务的 App ID
分别配置。源码直接运行时默认关闭登录，并预填内网配置；发布镜像默认启用内网登录。
平台姓名优先取校验响应中的 `data.sn`，继续兼容原有姓名字段。登录参数、回跳和会话行为
已按 `agent-auto-input-audit-service.zip` 对齐：登录发送 `login_mode=auto`；平台带回
`userid`、`token` 后直接校验，不再要求额外的登录 state；校验请求不读取系统代理配置。
本应用的完整会话 Cookie 与应用编号匹配时直接放行，缺姓名时补查平台；不再定期校验已有会话。
Cookie 使用 `jtb_sv_*` 名称，与其他应用隔离，姓名按百分号编码保存；升级后旧登录需重新登录。
Cookie 为浏览器会话 Cookie。侧栏“退出登录”只清除本应用会话，不会退出问学／OA 统一登录。

`GET /api/auth/me` 兼容参考包的账号、姓名和角色标志响应；现有 `/api/current-user` 继续保留。
本项目没有迁移参考应用的角色管理，普通登录用户的 `is_admin`、`is_dev` 均为 `false`。
退出接口为 `POST /api/system/logout`，退出后显示 `/logged-out`，由用户主动选择重新登录。

侧栏齿轮 → **统一登录设置** 提供“使用内网配置”（`127`、`http://172.23.255.36`）和
“使用外网配置”（`9086`、`https://sv.dcsmartvision.com`）。预设会把回跳方式设为
“自动跟随访问地址”，保持启用开关不变。自动模式保留当前主站的 Host 和端口，重新部署后
无需填写新端口；默认仅允许对应问学平台主机和 loopback，其他主机可通过
`JTB_AUTH_CALLBACK_HOSTS` 配置。原有非空 `JTB_AUTH_PUBLIC_URL` 仍作为固定回跳 origin。

点击“保存登录配置”后重启平台生效，配置存于 `runtime/auth_settings.sqlite3`，优先于部署
环境变量。旧版本已保存固定地址的部署，需要在设置中切换一次“自动跟随访问地址”并保存、
重启。已启用登录的主站只读，运维从私有反馈管理页的同名入口调整。

nginx 保留 Host 中的发布端口；有上游 HTTPS 网关时保留其明确的 `https` 协议标记，其余
请求使用 nginx 实际协议。网关必须覆盖客户端的协议转发头并保留完整 Host；应用不使用原始
`X-Forwarded-Host` 选择回跳地址。页面请求经过主后端，访问日志省略回跳查询参数。
2026-10-21 已用真实外网应用 `9086` 完成浏览器自动登录、读取平台 `sn` 姓名、退出和重新登录联调；内网应用 `127` 与指定员工 OA 账号仍需现场验证。该次外网测试两次回传的 `uid` 不同、姓名相同，应用沿用平台回传账号，账号稳定性需结合现场登录策略确认。

独立管理页支持反馈查询、新建、修改、删除及处理状态维护。主服务只开放提交接口
`POST /api/feedback`；`/api/feedback-admin` 的查询与管理接口只在管理端口注册，管理端口
也不提供任务生成接口。管理页面与管理 API 同源，浏览器跨来源的修改请求会被拒绝。

反馈保存在 `basic-service/app/runtime/feedback.sqlite3`，使用 `JTB_FEEDBACK_DB` 可指定
其他路径；两个进程必须使用同一数据库路径。Compose 的 `taskbook-runtime` 卷持久化该
文件。备份时停止两个服务后复制数据库文件，或在运行期间使用 SQLite 的在线备份工具；
恢复时停止服务后替换文件并保留运行用户的读写权限。管理服务结构化日志位于
`basic-service/app/logs/feedback-admin/`，与主服务分开轮转。

## 命令行生成（CLI）

```bash
cd basic-service/app
python -m src.pipeline_cli --help
python -m src.pipeline_cli \
    --tech 技术要求.docx --spec 产品规范.docx --tpl 模板.docx \
    --profile <profile.yaml> --category-mapping <mapping.yaml> \
    --out 输出.docx
```

## 测试与检查

```powershell
cd basic-service\app
..\.venv\Scripts\python.exe -m pytest -q
..\.venv\Scripts\python.exe -m ruff check src tests
..\.venv\Scripts\python.exe -m compileall -q src tests
```

## 限制与安全

工作簿规则及本轮修复追踪见 [7-22 规则核对记录](docs/workbook-rules-audit-20260916.md)。

- 当前离线交付镜像按约定包含私有 `.env`，文件权限为 `0600`；镜像和导出包按含凭据制品保管。虚拟环境、日志或运行期产物不进入镜像。
- 默认端口只绑定 loopback；远程暴露必须同时评估 TLS、CORS 与认证。
- `JTB_ALLOW_LOCAL_PATHS=1` 仅用于开发，生产保持关闭。
