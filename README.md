# 研制任务书受控生成服务 (agent-develop-task-doc-service)

由 FastAPI 后端 + 单文件 SPA 前端 + nginx 反向代理组成。容器内 nginx 监听 80 端口，
提供 `web/` 下的单文件 SPA，并把 `/api` 请求转发到 `127.0.0.1:18130` 的后端进程。

受控生成流水线：LLM 只做需求语义分类与原文定位（路由 JSON），正文由原文精确复制
装配；配合分段识别、覆盖率核验、QA 门禁与交付门禁，产出可追溯的研制任务书 DOCX。

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

凭据只从进程环境、本机 `.env` 或 `JTB_SHARED_ENV_FILE` 指向的共享 `.env` 读取，
优先级为：进程环境 > 本项目 `.env` > 共享 `.env`。不写入模型目录接口、日志或生成文档。

## Windows 本地启动

```powershell
.\start.ps1
```

构建虚拟环境、安装依赖，并在后台从 `basic-service\app` 启动 `uvicorn src.main:app`。
日志写入 `basic-service\app\logs\backend-startup.{stdout,stderr}.log`。停止服务：

```powershell
.\stop.ps1
```

## Linux/macOS 本地启动

```bash
chmod +x run_.sh build_.sh entrypoint.sh
./run_.sh
```

`run_.sh` 会创建虚拟环境、装依赖并前台运行后端。`Ctrl+C` 停止。

## Docker 与 Compose

```bash
docker compose up --build -d
docker compose logs -f
docker compose down
```

默认端口映射 `127.0.0.1:18130:80`，仅本机访问。远程暴露须同时调整端口绑定、
CORS、TLS 与认证。三个命名卷持久化数据、日志与运行期候选：

- `taskbook-data` → `app/data`
- `taskbook-logs` → `app/logs`
- `taskbook-runtime` → `app/runtime`

后端以非 root 用户 `agent-taskbook` 经 `gosu` 降权运行。

## 访问地址

- 应用：`http://127.0.0.1:18130/`
- Swagger：`http://127.0.0.1:18130/docs`
- 健康检查：`http://127.0.0.1:18130/api/health`

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

- 不把 `.env`、真实密钥、虚拟环境、日志或运行期产物复制进镜像。
- 默认端口只绑定 loopback；远程暴露必须同时评估 TLS、CORS 与认证。
- `JTB_ALLOW_LOCAL_PATHS=1` 仅用于开发，生产保持关闭。
