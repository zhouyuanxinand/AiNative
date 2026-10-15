#!/usr/bin/env bash
# 本地一键启动：创建虚拟环境、装依赖、监督主服务与反馈管理服务。
# Ctrl+C 停止。默认 development；已有 .env 或环境变量会覆盖。
set -eu

ROOT="$(cd "$(dirname "$0")" && pwd)"
BASIC="$ROOT/basic-service"
VENV="$BASIC/.venv"

if [ -z "${APP_ENV:-}" ]; then
    export APP_ENV=development
fi

# 若存在 .env 则导入进程环境（凭据注入）。
if [ -f "$ROOT/.env" ]; then
    set -a
    . "$ROOT/.env"
    set +a
fi

echo "[run] APP_ENV=$APP_ENV"

if [ ! -d "$VENV" ]; then
    echo "[run] 创建虚拟环境 $VENV"
    python -m venv "$VENV"
fi

echo "[run] 安装依赖"
"$VENV/bin/python" -m pip install -q -r "$BASIC/requirements.txt"

cd "$BASIC/app"
export JTB_HOST="${JTB_HOST:-127.0.0.1}"
export JTB_FEEDBACK_HOST="${JTB_FEEDBACK_HOST:-127.0.0.1}"
export JTB_FEEDBACK_PORT="${JTB_FEEDBACK_PORT:-18131}"
if [ "${JTB_PORT:-18130}" = "$JTB_FEEDBACK_PORT" ]; then
    echo "[run] 主服务与反馈管理端口不能相同" >&2
    exit 1
fi

BACKEND_PID=""
FEEDBACK_PID=""
cleanup() {
    trap - EXIT INT TERM
    for child in "$BACKEND_PID" "$FEEDBACK_PID"; do
        if [ -n "$child" ]; then kill -TERM "$child" 2>/dev/null || true; fi
    done
    for child in "$BACKEND_PID" "$FEEDBACK_PID"; do
        if [ -n "$child" ]; then wait "$child" 2>/dev/null || true; fi
    done
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo "[run] 启动后端 http://$JTB_HOST:${JTB_PORT:-18130}"
"$VENV/bin/python" -m src.main &
BACKEND_PID=$!
echo "[run] 启动反馈管理 http://$JTB_FEEDBACK_HOST:$JTB_FEEDBACK_PORT/feedback"
"$VENV/bin/python" -m src.feedback_main &
FEEDBACK_PID=$!

while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FEEDBACK_PID" 2>/dev/null; do
    sleep 1
done
echo "[run] 服务进程已退出，停止其余进程" >&2
exit 1
