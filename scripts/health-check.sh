#!/bin/bash
# 헬스체크
set -euo pipefail

INSTALL_DIR="${CLAUDE_KIT_DIR:-$HOME/claude-kit}"
PORT="${BOARD_PORT:-8585}"

echo "=== Claude Kit 상태 ==="

# Docker
if docker compose -f "$INSTALL_DIR/docker-compose.yml" ps 2>/dev/null | grep -q "running"; then
    echo "  Docker 컨테이너: 실행 중"
else
    echo "  Docker 컨테이너: 중지됨"
fi

# API
if curl -sf "http://localhost:$PORT/api/boards" > /dev/null 2>&1; then
    echo "  API: 정상"
else
    echo "  API: 응답 없음"
fi

# MCP
if curl -sf "http://localhost:$PORT/mcp/sse" > /dev/null 2>&1; then
    echo "  MCP: 정상"
else
    echo "  MCP: 확인 필요"
fi

# DB
if [ -f "$INSTALL_DIR/data/board.db" ]; then
    SIZE=$(du -h "$INSTALL_DIR/data/board.db" | cut -f1)
    echo "  DB: $SIZE"
else
    echo "  DB: 파일 없음"
fi

# 디스크
DISK=$(df -h "$INSTALL_DIR/data/" 2>/dev/null | tail -1 | awk '{print $5}') || true
if [ -n "$DISK" ]; then
    echo "  디스크: $DISK 사용"
fi
