# 研制任务书受控生成服务
# 多阶段构建：Stage 1 Node 构建前端 → Stage 2 Python+nginx 运行时
# 前端使用 React 18 + Vite + TypeScript，构建产物 dist/ 由 nginx 提供。

# ── Stage 1: 前端构建 ──────────────────────────────────
FROM node:20-bookworm-slim AS frontend
WORKDIR /build

# 先复制依赖文件以利用层缓存
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund

# 复制源码并构建
COPY web/ .
RUN npm run build  # 产出 dist/

# ── Stage 2: 运行时（Python 3.13 + nginx） ────────────
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENV=prod \
    API_HOST=127.0.0.1 \
    API_PORT=18130 \
    JTB_FEEDBACK_HOST=127.0.0.1 \
    JTB_FEEDBACK_PORT=18131 \
    JTB_AUTH_ENABLED=true \
    JTB_AUTH_APP_ID=127 \
    JTB_AUTH_PLATFORM_BASE_URL=http://172.23.255.36 \
    JTB_AUTH_PUBLIC_URL=""

# 发布镜像默认使用内网登录和自动回跳，不继承打包电脑 .env 的外网登录地址。
# 平台的已保存登录配置或部署环境变量仍可覆盖；本地源码运行默认不启用登录。

# gosu 用于降权运行后端；nginx 提供静态 SPA 与反代。
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gosu \
        nginx \
        curl \
        ca-certificates \
        libreoffice-writer \
        fonts-noto-cjk \
        fonts-liberation \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /etc/nginx/sites-enabled/default

# 非 root 运行身份。
RUN groupadd --system --gid 10001 agent-taskbook \
    && useradd --system --uid 10001 --gid agent-taskbook \
        --create-home --shell /sbin/nologin agent-taskbook

WORKDIR /opt/local/agent-develop-task-doc

# 先装依赖以利用层缓存。
COPY basic-service/requirements.txt /opt/local/agent-develop-task-doc/basic-service/requirements.txt
RUN pip install --no-cache-dir -r /opt/local/agent-develop-task-doc/basic-service/requirements.txt

# 后端源码与受控资源（src/service 下已含 config/、prompts/ 与 jonhon_taskbook/ 包，
# 含包内种子资源 templates/mappings）。
COPY basic-service/app/src /opt/local/agent-develop-task-doc/basic-service/app/src
COPY basic-service/app/resources /opt/local/agent-develop-task-doc/basic-service/app/resources
# 按交付要求将服务根 .env 固化进镜像。llm_client 会从该固定位置读取，
# 无需依赖容器编排平台额外注入；文件权限在后续 RUN 中收紧为 0600。
COPY .env /opt/local/agent-develop-task-doc/basic-service/app/src/service/.env
# 运行期数据目录由下方 RUN 与 entrypoint 创建，不要求工作区已有历史任务数据。

# 前端构建产物（从 Stage 1 复制 dist/）。
COPY --from=frontend /build/dist /opt/local/agent-develop-task-doc/basic-service/app/web/dist

# nginx 配置与入口脚本。
COPY web/nginx/nginx.conf /etc/nginx/conf.d/default.conf
COPY entrypoint.sh /usr/local/bin/entrypoint.sh

# 运行期目录与属主。
RUN mkdir -p \
        /opt/local/agent-develop-task-doc/basic-service/app/data/uploads \
        /opt/local/agent-develop-task-doc/basic-service/app/data/outputs \
        /opt/local/agent-develop-task-doc/basic-service/app/logs \
        /opt/local/agent-develop-task-doc/basic-service/app/runtime/template_candidates \
        /opt/local/agent-develop-task-doc/basic-service/app/runtime/template_releases \
    && chown -R agent-taskbook:agent-taskbook /opt/local/agent-develop-task-doc \
    && chmod 600 /opt/local/agent-develop-task-doc/basic-service/app/src/service/.env \
    && sed -i 's/\r$//' /usr/local/bin/entrypoint.sh \
    && chmod +x /usr/local/bin/entrypoint.sh \
    && find /opt/local/agent-develop-task-doc -type d -name __pycache__ -prune -exec rm -rf {} + \
    && nginx -t

EXPOSE 80 81

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://127.0.0.1:80/api/health && curl -fsS http://127.0.0.1:81/api/health || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
