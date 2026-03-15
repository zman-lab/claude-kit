#!/bin/bash
# =============================================================================
# Law Kit 이미지 빌드 스크립트
#
# 실행 위치: ~/zman-lab/claude-kit/law/
# 빌드 컨텍스트: ~/zman-lab/law/ (소스코드)
#
# 사용법:
#   ./build.sh              # 전체 빌드 + 이미지 내보내기
#   ./build.sh --no-export  # 빌드만 (tar.gz 내보내기 생략)
#   ./build.sh backend      # 백엔드만 빌드
#   ./build.sh frontend     # 프론트엔드만 빌드
#   ./build.sh nginx        # nginx만 빌드
# =============================================================================

set -euo pipefail

# 경로 설정
KIT_DIR="$(cd "$(dirname "$0")" && pwd)"
DOCKER_DIR="$KIT_DIR/docker"
LAW_SRC="/Users/nhn/zman-lab/law"
IMAGES_DIR="$KIT_DIR/images"

# 인자 파싱
TARGET="${1:-all}"
NO_EXPORT="${2:-}"
if [ "$TARGET" = "--no-export" ]; then
    NO_EXPORT="--no-export"
    TARGET="all"
fi

# -------------------------
# 사전 확인
# -------------------------
echo "=== Law Kit 이미지 빌드 ==="
echo "소스: $LAW_SRC"
echo "출력: $IMAGES_DIR"
echo ""

# Docker 동작 확인
if ! docker info > /dev/null 2>&1; then
    echo "ERROR: Docker가 실행 중이지 않습니다."
    echo "  sudo service docker start  (WSL2)"
    echo "  또는 Docker Desktop 실행"
    exit 1
fi

# 소스 경로 확인
if [ ! -d "$LAW_SRC/backend" ]; then
    echo "ERROR: 소스 경로를 찾을 수 없습니다: $LAW_SRC"
    echo "  LAW_SRC 변수를 실제 경로로 수정하세요."
    exit 1
fi

# 이미지 디렉토리 생성
mkdir -p "$IMAGES_DIR"

# -------------------------
# 빌드 함수
# -------------------------
build_backend() {
    echo "[Backend] Cython 컴파일 포함 빌드..."
    echo "  (Python .py → .so 컴파일로 시간이 걸릴 수 있습니다)"
    docker build \
        --platform linux/amd64 \
        -t law-backend:latest \
        -f "$DOCKER_DIR/Dockerfile.backend" \
        "$LAW_SRC"
    echo "[Backend] 빌드 완료"
}

build_frontend() {
    echo "[Frontend] Next.js 빌드..."
    docker build \
        --platform linux/amd64 \
        -t law-frontend:latest \
        -f "$DOCKER_DIR/Dockerfile.frontend" \
        "$LAW_SRC"
    echo "[Frontend] 빌드 완료"
}

build_nginx() {
    echo "[Nginx] 이미지 빌드..."
    docker build \
        --platform linux/amd64 \
        -t law-nginx:latest \
        -f "$DOCKER_DIR/Dockerfile.nginx" \
        "$DOCKER_DIR"
    echo "[Nginx] 빌드 완료"
}

export_image() {
    local name="$1"
    local file="$IMAGES_DIR/${name}.tar.gz"
    echo "[Export] ${name}:latest → ${name}.tar.gz ..."
    docker save "${name}:latest" | gzip > "$file"
    local size
    size=$(du -sh "$file" | cut -f1)
    echo "  완료: $file ($size)"
}

# -------------------------
# 빌드 실행
# -------------------------
case "$TARGET" in
    backend)
        build_backend
        [ "$NO_EXPORT" != "--no-export" ] && export_image law-backend
        ;;
    frontend)
        build_frontend
        [ "$NO_EXPORT" != "--no-export" ] && export_image law-frontend
        ;;
    nginx)
        build_nginx
        [ "$NO_EXPORT" != "--no-export" ] && export_image law-nginx
        ;;
    all)
        echo "--- 1/3 Backend ---"
        build_backend

        echo ""
        echo "--- 2/3 Frontend ---"
        build_frontend

        echo ""
        echo "--- 3/3 Nginx ---"
        build_nginx

        if [ "$NO_EXPORT" != "--no-export" ]; then
            echo ""
            echo "--- 이미지 내보내기 ---"
            export_image law-backend
            export_image law-frontend
            export_image law-nginx
        fi
        ;;
    *)
        echo "알 수 없는 대상: $TARGET"
        echo "사용법: ./build.sh [backend|frontend|nginx|all] [--no-export]"
        exit 1
        ;;
esac

# -------------------------
# 완료 보고
# -------------------------
echo ""
echo "=== 빌드 완료 ==="

if [ "$NO_EXPORT" != "--no-export" ] && [ "$TARGET" = "all" ]; then
    echo ""
    echo "생성된 이미지:"
    ls -lh "$IMAGES_DIR/"*.tar.gz 2>/dev/null || echo "  (내보내기 없음)"

    echo ""
    echo "친구 환경에서 설치:"
    echo "  1. images/ 폴더를 통째로 전달 (또는 USB/네트워크)"
    echo "  2. cd ~/claude-kit/law && ./setup.sh"
fi

echo ""
echo "로컬 테스트:"
echo "  cd $KIT_DIR && docker compose up -d"
echo "  접속: http://localhost:7999/law/"
