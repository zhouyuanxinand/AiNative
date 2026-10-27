# 研制任务书受控生成服务 (agent-develop-task-doc-service)

由 FastAPI 后端 + React SPA 前端 + nginx 反向代理组成。容器内 nginx 主站监听 80 端口，
提供 `web/dist/` 构建产物，主站业务请求转发到 `127.0.0.1:18130`。
管理员页面统一提供用户反馈、运行日志、操作资料和管理员名单管理，内部使用独立进程
`127.0.0.1:18131`。nginx 在同一个 80 端口将 `/admin` 及管理 API 转发到该进程，
部署只需发布容器 80；访问主站地址后加 `/admin` 即可进入管理员页面。

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
│           ├── feedback_main.py  独立管理应用（反馈、日志、操作资料与管理员名单）
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

默认只映射 `127.0.0.1:18130:80`，仅本机访问。主页是 `http://127.0.0.1:18130/`，
管理员页面是 `http://127.0.0.1:18130/admin`。内网若分配主站外部端口 `31187`，
则访问 `http://内网IP:31187/admin`，无需额外映射容器 81 或 18131。
远程暴露须同时调整端口绑定、CORS、TLS 与认证。三个命名卷持久化数据、日志与运行期候选：

- `taskbook-data` → `app/data`
- `taskbook-logs` → `app/logs`
- `taskbook-runtime` → `app/runtime`

后端以非 root 用户 `agent-taskbook` 经 `gosu` 降权运行。
容器入口监督主后端、反馈管理后端和 nginx 三个进程；健康检查在容器内部访问 80 和 81，
同时验证两个后端。内部健康检查不要求对外发布 81。

发布镜像默认启用内网统一登录：应用 ID `127`、神州问学地址 `http://172.23.255.36`，
回跳地址留空，自动跟随主站访问地址与发布端口。Dockerfile 的四项 `JTB_AUTH_*` 环境变量
覆盖包内 `.env` 的鉴权值，因此本地外网测试配置不会成为纯镜像部署的默认登录配置。
Compose 的 `env_file: .env` 属于部署时环境注入，仍可覆盖镜像默认值；现场应使用对应环境的
配置文件。已在界面保存的登录配置优先于这些环境变量，升级镜像不会重置它。

源码直接启动时，管理员进程仍使用 `JTB_FEEDBACK_PORT`（默认 `18131`），监听地址使用
`JTB_FEEDBACK_HOST`（默认 `127.0.0.1`），访问 `http://127.0.0.1:18131/admin`。
容器内两个后端分别监听 `18130`、`18131`，外部统一通过 nginx 的 80 端口访问。
nginx 仍保留 81 兼容入口，已显式映射 81 的旧部署可以继续使用；新部署无需该映射。
原 `JTB_FEEDBACK_PUBLISHED_PORT` 不再改变默认 Compose 的端口配置。

Kubernetes 清单仅为容器 80 提供一个 NodePort Service（示例外部端口 `30130`），
主页与 `/admin` 共用它。通过本地转发访问同一入口：

```bash
kubectl -n agent-develop-task-doc port-forward service/agent-develop-task-doc 18130:80
```

## 访问地址

以下按默认 Compose 映射说明；内网以实际分配的主站地址替换 `http://127.0.0.1:18130`：

- 应用：`http://127.0.0.1:18130/`
- Swagger：`http://127.0.0.1:18130/docs`
- 健康检查：`http://127.0.0.1:18130/api/health`
- 管理员页面：`http://127.0.0.1:18130/admin`（默认显示用户反馈）
- 管理员运行日志：`http://127.0.0.1:18130/admin?view=logs`
- 管理员操作资料上传：`http://127.0.0.1:18130/admin?view=resources`
- 管理员名单：`http://127.0.0.1:18130/admin?view=admins`
- 主站操作视频：`http://127.0.0.1:18130/help/video`
- 主站操作手册：`http://127.0.0.1:18130/help/manual`
- 管理会话状态：`http://127.0.0.1:18130/api/admin/session`

同一入口的 `/api/health` 返回主站健康状态；独立管理服务的 `/api/health` 由容器内部
健康检查访问。管理接口始终经过独立管理员鉴权，不因与主站共享发布端口而开放。
源码直接启动或使用旧 81 映射时，管理端根路径和 `/feedback` 跳转至 `/admin`，保留反馈筛选参数；
管理端 `/log`、`/logs` 跳转至 `/admin?view=logs`。
管理员页面强制 OA 身份校验和管理员名单授权。

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
重启。主站统一登录设置始终只读，由 `wangxue` 从管理员页面的同名入口调整。

nginx 保留 Host 中的发布端口；有上游 HTTPS 网关时保留其明确的 `https` 协议标记，其余
请求使用 nginx 实际协议。网关必须覆盖客户端的协议转发头并保留完整 Host；应用不使用原始
`X-Forwarded-Host` 选择回跳地址。业务页面请求经过主后端，管理员页面和回跳经过管理后端，
访问日志省略回跳查询参数。
2026-10-21 已用真实外网应用 `9086` 完成浏览器自动登录、读取平台 `sn` 姓名、退出和重新登录联调；内网应用 `127` 与指定员工 OA 账号仍需现场验证。该次外网测试两次回传的 `uid` 不同、姓名相同，应用沿用平台回传账号，账号稳定性需结合现场登录策略确认。

管理员页面通过侧栏切换“用户反馈”“运行日志”“操作资料上传”和“管理员名单”。反馈支持查询、新建、修改、删除及处理状态维护。主服务只开放反馈提交接口
`POST /api/feedback`；`/api/feedback-admin`、`/api/admin`、`/api/logs`、
`/api/help-resources-admin` 等管理接口由 nginx 分流到独立管理服务，主站业务后端不注册这些管理接口。
管理页面与管理 API 同源，浏览器跨来源的修改请求会被拒绝。

管理员登录沿用 OA／问学账号密码，由问学完成登录及密码校验；本平台不收集或保存 OA 密码。
初始名单只有 `wangxue`。登录后，该账号可在“管理员名单”添加其他 **OA 登录账号**，也可移除授权；
`wangxue` 不可移除。其他管理员可处理反馈、查看日志和名单、维护操作资料，不能再授权其他人或修改统一登录设置。
名单每次请求都参与权限检查，移除账号后，其已有会话立即失效。

管理员使用独立登录回跳 `/admin/auth/callback` 与 `jtb_admin_session` 随机会话；不把主站姓名 Cookie
当作管理员身份。登录回跳 state 在服务端限时 5 分钟且只使用一次，OA 校验成功后才核对名单。
账号取问学校验响应中的明确登录名字段；没有登录名时只使用本次已校验的 `userid`，
不会将 `sn` 等显示姓名作为授权依据。平台未返回可匹配账号时拒绝进入，不自动放宽授权规则。

名单与会话存于 `runtime/admin_access.sqlite3`（`JTB_ADMIN_ACCESS_DB` 可覆盖），现有 runtime 卷会持久化。
会话只以摘要存储，默认 8 小时，绑定应用编号、问学地址及管理员入口 origin。退出只结束管理会话，
不退出 OA 或主站。即使主站关闭统一登录，管理员端仍要求登录。
管理员复用保存的 OA 应用编号和问学地址，默认自动回跳当前入口的
`/admin/auth/callback`。单端口部署会保留主站的外部 Host、端口和协议；旧独立端口入口
仍回跳它自身的 origin。两种入口均不会使用主站固定回跳地址替代管理员回跳。
如需固定管理入口，可配置独立的 `JTB_ADMIN_PUBLIC_URL`。其他访问主机仍须配置 `JTB_AUTH_CALLBACK_HOSTS`。
管理员右上角“返回主页”在单端口入口返回同一 origin 的 `/`，独立端口入口继续兼容主站地址配置。
由旧独立入口迁移到同一主站入口后，因管理员会话绑定 origin，需要重新完成一次管理员登录。

运行日志默认按一次完整的生成请求展示，包含提交校验、后台生成进度、模型调用诊断、质量门禁和最终结果。
每条记录关联用户名、任务编号、业务参数、模型及输入/输出文件名，可以按“成功 / 失败 / 执行中”及关键字筛选。
只有生成完成才标记成功；请求被拒绝、生成异常、质量阻断和用户终止均标记失败并保留原因。
主服务重启时将上次尚在执行的记录标记为中断失败。旧版本的零散日志不补造为完整请求。

归档保存在 `basic-service/app/runtime/request_logs.sqlite3`，可使用 `JTB_REQUEST_LOG_DB` 覆盖路径。
最多保留最近 **50 个已完成请求**，超出后自动删除最旧请求及其全部日志；执行中的请求单独保留。
主服务和管理服务必须使用同一数据库路径；默认位于现有 `taskbook-runtime` 持久卷中，重启不会丢失记录。
管理端提供 `GET /api/logs/requests?status=failed&q=关键词` 和
`GET /api/logs/requests/{request_id}?after=0&limit=500`，详情通过 `next_cursor` 分页读取全部事件。
接口需携带 `X-Log-Viewer: 1`，日志内容沿用凭据和原始模型内容脱敏规则。

页面中的“服务实时日志”继续使用 `GET /api/logs/latest`，显示主服务 `app.log` 的最新记录。
主服务和管理服务必须使用相同的日志目录配置；现有部署在同一容器内运行两个进程，管理端
直接读取共享文件，无需浏览器跨端口访问，管理进程自身日志也不会混入生成日志。

反馈保存在 `basic-service/app/runtime/feedback.sqlite3`，使用 `JTB_FEEDBACK_DB` 可指定
其他路径；两个进程必须使用同一数据库路径。Compose 的 `taskbook-runtime` 卷持久化该
文件。反馈库和请求日志库均可在停止两个服务后备份，或在运行期间使用 SQLite 的在线备份工具；
恢复时停止服务后替换文件并保留运行用户的读写权限。管理服务结构化日志位于
`basic-service/app/logs/feedback-admin/`，与主服务分开轮转。

统一页面沿用原 `src.feedback_main` 入口、`JTB_FEEDBACK_*` 端口变量和健康检查中的
`service: "feedback-admin"`。两个内部进程及共享数据路径保持兼容，对外默认仅发布主站端口。

## 操作视频与操作手册

所有已通过 OA 验证且在管理员名单内的账号，都可进入 `/admin?view=resources`，在侧栏
“操作资料上传”中添加、查看和删除资料。每次填写标题、选择“操作视频”或“操作手册”，
上传一个原文件或添加一个链接；每个分类可保存多份资料。列表支持按分类筛选、打开原文件或链接、
下载原件和删除确认。上传失败保留输入，上传过程中显示进度。

| 分类 | 支持上传的文件 | 单个文件上限 |
|---|---|---|
| 操作视频 | MP4、WebM、OGG | 500 MiB |
| 操作手册 | PDF、DOC、DOCX | 50 MiB |

这些是操作资料专用限制，不受任务生成上传配置 `JTB_MAX_UPLOAD_MB` 影响。

主站侧栏的“操作视频”和“操作手册”分别进入 `/help/video` 与 `/help/manual`，从服务端动态
读取已发布资料。管理员添加或删除后，用户重新打开对应页面或点击“刷新资料”即可看到最新列表，
无需重建前端或重启服务；已打开的页面不会自动轮询。

视频使用浏览器播放器，PDF 使用浏览器内嵌预览。上传的 Word 手册提供文字、表格和图片的内容预览，
同时保留“下载原文件”；内容预览不承诺复刻原始分页和排版。DOC 文件需要服务器可用的本地转换工具：
Windows 优先使用 Word COM，再尝试 LibreOffice；其他平台使用 `soffice` 或 `libreoffice`，
发布镜像已安装 `libreoffice-writer`。转换不可用或预览失败时仍可下载原件。

链接仅接受不含账号密码的完整 HTTP 或 HTTPS 地址，直接由用户浏览器访问，不由服务端抓取或转存。
根据 URL 路径扩展名，MP4、WebM、OGG 链接可尝试视频预览，PDF 链接可尝试文档内嵌预览；
其他链接通过“打开原链接”访问；外链 Word 文件不转换为本站内容预览。外部站点的访问权限、
媒体编码或嵌入限制仍可能影响播放和预览，页面始终保留原链接入口。

资料目录固定为 `basic-service/app/data/help_resources/`（运行时按 `logs_dir` 的父目录定位），
其中 `catalogue.sqlite3` 保存目录，`files/` 保存上传的原文件。主站和管理服务必须共享同一目录，
并让运行用户具有所需的读写权限。Compose 现有 `taskbook-data` 卷已覆盖此目录；独立部署时须一并
持久化和备份目录数据库与文件，升级时保留数据卷。删除文件资料会移除原文件；删除链接资料只移除入口，
不删除外部内容。

主站只注册资料读取接口；上传、添加链接和删除接口仅注册在管理员服务，并检查当前管理员会话与名单。
nginx 仅将管理端 `/api/help-resources-admin/upload` 的请求体上限设为 `501m`，为 500 MiB 文件及
multipart 开销留出空间，其他管理请求仍保持原限制。有额外反向代理时，上传路径也需允许相应大小。

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
