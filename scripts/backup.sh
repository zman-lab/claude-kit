#!/bin/bash
# Claude Kit DB 백업
set -euo pipefail

INSTALL_DIR="${CLAUDE_KIT_DIR:-$HOME/claude-kit}"
BACKUP_DIR="$INSTALL_DIR/backups"
mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
cp "$INSTALL_DIR/data/board.db" "$BACKUP_DIR/board_${TIMESTAMP}.db"

# 오래된 백업 정리 (30일 이상)
find "$BACKUP_DIR" -name "*.db" -mtime +30 -delete

echo "백업 완료: $BACKUP_DIR/board_${TIMESTAMP}.db"
