#!/usr/bin/env bash
# 构建 Docker 镜像。--save 可导出为 tar（内网离线交付）。
set -eu

IMAGE_NAME="agent-develop-task-doc-service"
IMAGE_TAG="${IMAGE_TAG:-latest}"
SAVE_TAR=0

for arg in "$@"; do
    case "$arg" in
        --save) SAVE_TAR=1 ;;
        *) echo "未知参数: $arg"; exit 2 ;;
    esac
done

echo "[build] 构建 ${IMAGE_NAME}:${IMAGE_TAG}"
docker build -t "${IMAGE_NAME}:${IMAGE_TAG}" .

if [ "$SAVE_TAR" -eq 1 ]; then
    TAR="${IMAGE_NAME}-${IMAGE_TAG}.tar"
    if [ -f "$TAR" ]; then
        echo "[build] 拒绝覆盖已存在的 $TAR" >&2
        exit 1
    fi
    echo "[build] 导出镜像到 $TAR"
    docker save -o "$TAR" "${IMAGE_NAME}:${IMAGE_TAG}"
fi

echo "[build] 完成"
