#!/bin/sh
# 容器入口：主服务、反馈管理服务与 nginx；任一进程退出则停止其余进程。
set -eu

APP_ROOT="/opt/local/agent-develop-task-doc/basic-service/app"
RUN_USER="agent-taskbook"

# 确保数据卷与日志卷可写（首次建卷时属主可能仍是 root）。
mkdir -p "$APP_ROOT/data/uploads" "$APP_ROOT/data/outputs" "$APP_ROOT/logs" \
         "$APP_ROOT/runtime/template_candidates" "$APP_ROOT/runtime/template_releases"
chown -R "$RUN_USER":"$RUN_USER" "$APP_ROOT/data" "$APP_ROOT/logs" "$APP_ROOT/runtime" 2>/dev/null || true

BACKEND_PID=""
FEEDBACK_PID=""
NGINX_PID=""
EXIT_CODE=0

cleanup() {
    trap - INT TERM EXIT
    echo "[entrypoint] received stop signal, shutting down"
    if [ -n "$NGINX_PID" ]; then
        kill -TERM "$NGINX_PID" 2>/dev/null || true
    fi
    if [ -n "$BACKEND_PID" ]; then
        kill -TERM "$BACKEND_PID" 2>/dev/null || true
    fi
    if [ -n "$FEEDBACK_PID" ]; then
        kill -TERM "$FEEDBACK_PID" 2>/dev/null || true
    fi
    for child in "$NGINX_PID" "$BACKEND_PID" "$FEEDBACK_PID"; do
        if [ -n "$child" ]; then wait "$child" 2>/dev/null || true; fi
    done
    exit "$EXIT_CODE"
}
trap cleanup INT TERM
trap cleanup EXIT

echo "[entrypoint] starting backend (uvicorn :18130)"
cd "$APP_ROOT"
gosu "$RUN_USER" python -m src.main &
BACKEND_PID=$!

echo "[entrypoint] starting feedback management (:18131)"
# nginx upstreams use stable internal ports, independent of the published host port.
JTB_FEEDBACK_HOST=127.0.0.1 JTB_FEEDBACK_PORT=18131 \
    gosu "$RUN_USER" python -m src.feedback_main &
FEEDBACK_PID=$!

echo "[entrypoint] starting nginx (:80, :81)"
# nginx 错误日志也可能附带原始回跳 URI，输出前统一脱敏并转发停机信号。
python -m src.common.nginx_logs &
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
    if ! kill -0 "$FEEDBACK_PID" 2>/dev/null; then
        echo "[entrypoint] feedback management exited"
        EXIT_CODE=1
        break
    fi
    sleep 1
done

cleanup
