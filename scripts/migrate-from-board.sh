#!/bin/bash
# 기존 board (zman-lab/board) → claude-kit 마이그레이션
# 기존 DB를 복사하되, 하드코딩된 팀 정보를 Team 테이블로 이전
set -euo pipefail

SOURCE_DB="${1:-}"
if [ -z "$SOURCE_DB" ]; then
    echo "사용법: ./migrate-from-board.sh <원본 board.db 경로>"
    echo "예시: ./migrate-from-board.sh /path/to/board/data/board.db"
    exit 1
fi
INSTALL_DIR="${CLAUDE_KIT_DIR:-$HOME/claude-kit}"
TARGET_DB="$INSTALL_DIR/data/board.db"

if [ ! -f "$SOURCE_DB" ]; then
    echo "원본 DB를 찾을 수 없습니다: $SOURCE_DB"
    exit 1
fi

# 1. 현재 DB 백업
if [ -f "$TARGET_DB" ]; then
    cp "$TARGET_DB" "${TARGET_DB}.pre-migration"
fi

# 2. 원본 복사
mkdir -p "$INSTALL_DIR/data"
cp "$SOURCE_DB" "$TARGET_DB"

# 3. Team 테이블 생성 + 기존 Board의 team 컬럼에서 마이그레이션
export TARGET_DB
python3 << 'PYEOF'
import sqlite3
import os

db_path = os.environ["TARGET_DB"]

conn = sqlite3.connect(db_path)
cur = conn.cursor()

# teams 테이블이 없으면 생성
cur.execute("""
CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(100) NOT NULL,
    slug VARCHAR(50) UNIQUE NOT NULL,
    icon VARCHAR(10) DEFAULT '📋',
    color VARCHAR(20) DEFAULT '#6366f1',
    color_dark VARCHAR(20),
    description TEXT DEFAULT '',
    sort_order INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")

# 기존 boards 테이블에서 team이 있는 것들 추출
cur.execute("SELECT DISTINCT team FROM boards WHERE team IS NOT NULL AND team != ''")
teams = [row[0] for row in cur.fetchall()]

# 기본 색상 매핑 (없으면 기본색)
default_colors = {
    'law': ('#7c3aed', '#a78bfa'),
    'airlock': ('#0891b2', '#22d3ee'),
    'elkhound': ('#ea580c', '#fb923c'),
    'board': ('#525252', '#a3a3a3'),
    'lawear': ('#059669', '#34d399'),
}

default_icons = {
    'law': '⚖️', 'airlock': '🔐', 'elkhound': '🐕',
    'board': '📋', 'lawear': '⚖️',
}

for i, team in enumerate(teams):
    color, color_dark = default_colors.get(team, ('#6366f1', '#818cf8'))
    icon = default_icons.get(team, '📋')
    try:
        cur.execute("""
            INSERT INTO teams (name, slug, icon, color, color_dark, sort_order)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (team, team, icon, color, color_dark, i + 1))
    except sqlite3.IntegrityError:
        pass  # 이미 존재

conn.commit()
conn.close()
print(f"마이그레이션 완료: {len(teams)}개 팀 이전")
PYEOF

# 4. 서버 재시작
docker compose -f "$INSTALL_DIR/docker-compose.yml" restart 2>/dev/null || true

echo "마이그레이션 완료!"
echo "기존 DB 백업: ${TARGET_DB}.pre-migration"
