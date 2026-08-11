#!/usr/bin/env bash
# 本地一键启动：创建虚拟环境、装依赖、前台运行后端。
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
echo "[run] 启动后端 http://127.0.0.1:${JTB_PORT:-18130}"
exec "$VENV/bin/python" -m uvicorn src.main:app \
    --host "${JTB_HOST:-127.0.0.1}" \
    --port "${JTB_PORT:-18130}"
