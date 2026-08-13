#!/usr/bin/env bash
# 构建 Docker 镜像。--save 导出 legacy 格式 tar（内网离线交付）。
# 与 agent_auto_input_audit_service 等服务保持一致的打包方式。
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_TAG="${IMAGE_TAG:-1.0.0}"
image_name="agent-develop-task-doc-service:${IMAGE_TAG}"
tar_path="$script_dir/agent-develop-task-doc-service-${IMAGE_TAG}.tar"
legacy_script="$script_dir/build_legacy_image.py"
save_image=false

usage() {
    printf 'Usage: %s [--save]\n' "$(basename -- "$0")"
    printf '  --save   构建后导出 legacy 格式 Docker 镜像压缩包\n'
    printf '           (顶层 manifest.json + repositories + <id>/layer.tar),\n'
    printf '           适用于 >= 1.11.2 的容器引擎。\n'
}

case "${1:-}" in
    "")
        ;;
    --save)
        save_image=true
        ;;
    -h|--help)
        usage
        exit 0
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac

command -v docker >/dev/null 2>&1 || {
    printf 'docker is required but was not found in PATH.\n' >&2
    exit 1
}

printf '[build] 构建 %s\n' "$image_name"
docker build --tag "$image_name" "$script_dir"

if [ "$save_image" = true ]; then
    if [ -e "$tar_path" ]; then
        rm -f "$tar_path"
    fi
    if [ ! -f "$legacy_script" ]; then
        printf 'Legacy converter not found: %s\n' "$legacy_script" >&2
        exit 1
    fi

    # 查找可用的 Python 3.7+ 解释器
    python_bin=""
    for candidate in python3 python py; do
        if command -v "$candidate" >/dev/null 2>&1; then
            ver="$("$candidate" --version 2>/dev/null | head -n1 || true)"
            case "$ver" in
                "Python 3."*)
                    if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 7) else 1)' >/dev/null 2>&1; then
                        python_bin="$candidate"
                        break
                    fi
                    ;;
            esac
        fi
    done
    if [ -z "$python_bin" ]; then
        printf 'Python 3.7+ is required to build the legacy archive but was not found in PATH.\n' >&2
        exit 1
    fi

    printf '[build] 导出 legacy 格式镜像: %s\n' "$tar_path"
    "$python_bin" "$legacy_script" "$image_name" "$tar_path"
    printf '[build] 完成: %s\n' "$tar_path"
fi
