#!/bin/bash
# Claude Kit 제거
INSTALL_DIR="${CLAUDE_KIT_DIR:-$HOME/claude-kit}"

echo "Claude Kit을 제거합니다."
echo "데이터(게시글, 첨부파일)도 삭제됩니다."
read -p "계속하시겠습니까? (y/N) " confirm

if [[ "$confirm" != [yY] ]]; then
    echo "취소됨"
    exit 0
fi

# 컨테이너 중지 + 제거
docker compose -f "$INSTALL_DIR/docker-compose.yml" down 2>/dev/null

# MCP 설정 제거
python3 -c "
import json
f = '$HOME/.claude/settings.json'
try:
    with open(f) as fh: d = json.load(fh)
    if 'mcpServers' in d and 'claude-board' in d['mcpServers']:
        del d['mcpServers']['claude-board']
        with open(f, 'w') as fh: json.dump(d, fh, indent=2)
        print('MCP 설정 제거 완료')
except: pass
" 2>/dev/null

echo "제거 완료"
echo "데이터는 $INSTALL_DIR/data/ 에 남아있습니다."
echo "완전 삭제: rm -rf \"$INSTALL_DIR\""
