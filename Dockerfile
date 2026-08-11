# 研制任务书受控生成服务
# 单镜像：Python 3.13 后端 + nginx 提供单文件 SPA 并反代 /api
# 前端无构建阶段（templates/index.html 为内联 CSS/JS 的 SPA）。
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENV=prod \
    API_HOST=127.0.0.1 \
    API_PORT=18130

# gosu 用于降权运行后端；nginx 提供静态 SPA 与反代。
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gosu \
        nginx \
        curl \
        ca-certificates \
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
# 运行期数据目录（首次建卷时由 entrypoint 创建子目录）。
COPY basic-service/app/data /opt/local/agent-develop-task-doc/basic-service/app/data

# 前端单文件 SPA。
COPY web /opt/local/agent-develop-task-doc/basic-service/app/web

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
    && chmod +x /usr/local/bin/entrypoint.sh \
    && find /opt/local/agent-develop-task-doc -type d -name __pycache__ -prune -exec rm -rf {} + \
    && nginx -t

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:18130/api/health || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
