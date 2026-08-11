# 环境切换说明

本服务支持 `development` / `testing` / `prod` 三种环境，配置文件位于
`basic-service/app/resources/`：

- `application.yml` — 基础配置（全环境默认值）
- `application-dev.yml` — 开发环境覆盖
- `application-test.yml` — 测试环境覆盖
- `application-prod.yml` — 生产环境覆盖

## 选择环境

通过环境变量控制：

```bash
APP_ENV=development   # 或 testing / prod
```

兼容旧约定 `SPRING_PROFILES_ACTIVE`（取值 `dev` / `test` / `prod`）。
当 `APP_ENV` 与 `SPRING_PROFILES_ACTIVE` 同时存在时，`APP_ENV` 优先；
若仅设置 `SPRING_PROFILES_ACTIVE`，则按其值加载对应 profile 文件。

## 加载优先级（从低到高覆盖）

1. `resources/application.yml`（基线）
2. `resources/application-{profile}.yml`（profile 覆盖，深度合并）
3. 进程环境变量（最高优先级，凭据必须走环境变量）

`.env` 文件由 `run_.sh` / `start.ps1` / Compose 导入进程环境后参与覆盖，
但**凭据永远应通过环境变量注入，不硬编码到 YAML**。

## 本地开发

```bash
APP_ENV=development ./run_.sh
```

`application-dev.yml` 默认端口 18130、日志 INFO。

## Docker 生产

`docker-compose.yml` 默认设置 `APP_ENV=prod`，端口映射 `127.0.0.1:18130:80`。
敏感凭据通过 Compose `.env` 或环境变量注入，不写入镜像。

## 关键环境变量速查

| 变量 | 说明 | 默认 |
| --- | --- | --- |
| `APP_ENV` | 运行环境 | development |
| `JTB_HOST` / `JTB_PORT` | 后端监听地址与端口 | 127.0.0.1 / 18130 |
| `CORS_ORIGINS` | 允许的前端来源 | `["*"]` |
| `JTB_MAX_UPLOAD_MB` | 上传体积上限 | 100 |
| `JTB_MAX_CONCURRENT_JOBS` | 最大并发生成任务 | 2 |
| `JTB_ALLOW_LOCAL_PATHS` | 本地路径接口开关（仅开发） | 0 |
| `MODEL_*` / `AI_*` / `JTB_LLM_*` / `AZURE_*` | LLM 凭据（四选一） | — |
