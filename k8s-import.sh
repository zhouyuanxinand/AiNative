#!/usr/bin/env bash
# K8s 内网镜像导入脚本——自动探测容器运行时（containerd / Docker）。
#
# 用法：
#   1. 将 tar 包和本脚本传到 K8s 节点
#   2. bash k8s-import.sh agent-develop-task-doc-service-1.0.1.tar
#   3. kubectl apply -f k8s-deploy.yaml
set -euo pipefail

TAR="${1:?用法: bash k8s-import.sh <image.tar>}"
IMAGE_NAME="agent-develop-task-doc-service:1.0.1"

if [ ! -f "$TAR" ]; then
    echo "✗ 镜像包不存在: $TAR" >&2
    exit 1
fi

command -v tar >/dev/null 2>&1 || {
    echo "✗ 缺少 tar 命令，无法校验镜像包。" >&2
    exit 1
}

# 在接触节点镜像仓库前先确认是目标 legacy Docker archive，且标签与部署清单一致。
if ! tar -tf "$TAR" | grep -Fx 'manifest.json' >/dev/null; then
    echo "✗ 镜像包顶层缺少 manifest.json: $TAR" >&2
    exit 1
fi
if ! tar -xOf "$TAR" manifest.json | grep -F "\"$IMAGE_NAME\"" >/dev/null; then
    echo "✗ 镜像包 RepoTags 与部署标签不一致，期望: $IMAGE_NAME" >&2
    exit 1
fi

echo "=== 导入镜像: $TAR ==="

# ── 探测容器运行时 ──────────────────────────────────────
RUNTIME=""

# 优先检查 containerd（K8s ≥ 1.24 默认）
if command -v ctr >/dev/null 2>&1; then
    echo "检测到 containerd (ctr)"
    echo "导入到 containerd k8s.io 命名空间..."
    ctr -n k8s.io images import "$TAR" --all-platforms
    RUNTIME="containerd"

# 其次检查 Docker（旧版 K8s 或 dockershim）
elif command -v docker >/dev/null 2>&1; then
    echo "检测到 Docker"
    echo "导入到 Docker daemon..."
    docker load -i "$TAR"
    RUNTIME="docker"

# crictl 能检查 CRI 镜像，但本身不支持导入 Docker archive。
elif command -v crictl >/dev/null 2>&1; then
    echo "检测到 crictl (CRI 接口)"
    echo "✗ crictl 不支持直接导入 Docker archive，且当前节点未找到 ctr。" >&2
    echo "  请使用该发行版提供的导入命令（如 k3s ctr images import），" >&2
    echo "  或安装/定位与 kubelet 同一 containerd 实例的 ctr 后重试。" >&2
    exit 1
else
    echo "✗ 未找到 ctr / docker / crictl，无法导入镜像" >&2
    echo "  请安装 containerd (ctr) 或 Docker 后重试" >&2
    exit 1
fi

echo ""
echo "=== 验证镜像 ==="
case "$RUNTIME" in
    containerd)
        if ! ctr -n k8s.io images list | grep -F "$IMAGE_NAME" >/dev/null; then
            echo "✗ containerd 中未找到精确镜像标签: $IMAGE_NAME" >&2
            echo "  请检查 tar 包的 manifest.json / RepoTags，并确认导入到 k8s.io 命名空间。" >&2
            exit 1
        fi
        ;;
    docker)
        if ! docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
            echo "✗ Docker 中未找到精确镜像标签: $IMAGE_NAME" >&2
            echo "  请检查 tar 包的 manifest.json / RepoTags。" >&2
            exit 1
        fi
        ;;
esac

echo ""
echo "✓ 导入完成"
echo ""
echo "下一步:"
echo "  kubectl apply -f k8s-deploy.yaml"
echo "  kubectl get pods -n agent-develop-task-doc -w"
echo ""
echo "如果 Pod 显示 ErrImageNeverPull / ImagePullBackOff，请确认:"
echo "  1. k8s-deploy.yaml 中 imagePullPolicy: Never"
echo "  2. 镜像已导入到 Pod 所在的节点（多节点集群需要每个节点都导入）"
echo "  3. 镜像名完全一致: $IMAGE_NAME"
