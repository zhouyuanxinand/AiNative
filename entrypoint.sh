#!/bin/sh
# 容器入口：同时拉起 uvicorn（后端）与 nginx（SPA + 反代）。
# 任一子进程退出则终止另一个并带状态码退出（supervisor 模式）。
set -eu

APP_ROOT="/opt/local/agent-develop-task-doc/basic-service/app"
RUN_USER="agent-taskbook"

# 确保数据卷与日志卷可写（首次建卷时属主可能仍是 root）。
mkdir -p "$APP_ROOT/data/uploads" "$APP_ROOT/data/outputs" "$APP_ROOT/logs" \
         "$APP_ROOT/runtime/template_candidates" "$APP_ROOT/runtime/template_releases"
chown -R "$RUN_USER":"$RUN_USER" "$APP_ROOT/data" "$APP_ROOT/logs" "$APP_ROOT/runtime" 2>/dev/null || true

BACKEND_PID=""
NGINX_PID=""
EXIT_CODE=0

cleanup() {
    trap - INT TERM
    echo "[entrypoint] received stop signal, shutting down"
    if [ -n "$NGINX_PID" ]; then
        kill -TERM "$NGINX_PID" 2>/dev/null || true
    fi
    if [ -n "$BACKEND_PID" ]; then
        kill -TERM "$BACKEND_PID" 2>/dev/null || true
    fi
    wait "$NGINX_PID" 2>/dev/null || true
    wait "$BACKEND_PID" 2>/dev/null || true
    exit "$EXIT_CODE"
}
trap cleanup INT TERM

echo "[entrypoint] starting backend (uvicorn :18130)"
cd "$APP_ROOT"
gosu "$RUN_USER" python -m src.main &
BACKEND_PID=$!

echo "[entrypoint] starting nginx (:80)"
nginx -g 'daemon off;' &
NGINX_PID=$!

# 监督循环：任一子进程退出则整体退出。
while true; do
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        echo "[entrypoint] backend exited"
        EXIT_CODE=1
        break
    fi
    if ! kill -0 "$NGINX_PID" 2>/dev/null; then
        echo "[entrypoint] nginx exited"
        EXIT_CODE=1
        break
    fi
    sleep 1
done

cleanup
