#!/bin/bash
# 백업 파일에서 복원
set -euo pipefail

if [ -z "${1:-}" ]; then
    echo "사용법: ./import.sh <백업파일경로>"
    exit 1
fi

INSTALL_DIR="${CLAUDE_KIT_DIR:-$HOME/claude-kit}"

# 현재 DB 백업
if [ -f "$INSTALL_DIR/data/board.db" ]; then
    cp "$INSTALL_DIR/data/board.db" "$INSTALL_DIR/data/board.db.before-import"
fi

# 임포트
cp "$1" "$INSTALL_DIR/data/board.db"

# 서버 재시작
if [ ! -f "$INSTALL_DIR/docker-compose.yml" ]; then
    echo "오류: docker-compose.yml을 찾을 수 없습니다: $INSTALL_DIR/docker-compose.yml"
    exit 1
fi
docker compose -f "$INSTALL_DIR/docker-compose.yml" restart

echo "임포트 완료. 이전 DB: $INSTALL_DIR/data/board.db.before-import"
