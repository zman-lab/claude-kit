#!/bin/bash
set -euo pipefail

INSTALL_DIR="${CLAUDE_KIT_DIR:-$HOME/claude-kit}"
BOARD_PORT="${BOARD_PORT:-8585}"
LOG_FILE="$INSTALL_DIR/install.log"

# 색상 출력
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[claude-kit]${NC} $1"; }
warn() { echo -e "${YELLOW}[경고]${NC} $1"; }
err() { echo -e "${RED}[오류]${NC} $1"; }

# 1. 환경 감지
detect_env() {
    if grep -qi microsoft /proc/version 2>/dev/null; then
        echo "wsl2"
    elif [[ "$(uname)" == "Darwin" ]]; then
        echo "macos"
    else
        echo "linux"
    fi
}

# 2. Docker 설치 확인 + 자동 설치
ensure_docker() {
    if command -v docker &>/dev/null; then
        log "Docker 감지됨: $(docker --version)"
        return 0
    fi

    local env=$(detect_env)
    log "Docker 미설치. 자동 설치 시작 ($env)..."

    case $env in
        wsl2|linux)
            sudo apt-get update
            sudo apt-get install -y docker.io docker-compose-plugin
            sudo usermod -aG docker "$USER"
            sudo service docker start
            # Docker 그룹 반영 확인
            if ! docker info &>/dev/null 2>&1; then
                if groups | grep -q docker; then
                    sudo service docker start
                else
                    log "Docker 그룹 반영을 위해 스크립트를 재실행합니다..."
                    exec sg docker -c "bash $0 $*"
                fi
            fi
            ;;
        macos)
            if command -v brew &>/dev/null; then
                brew install --cask docker
                open /Applications/Docker.app
                log "Docker Desktop 실행 대기중..."
                while ! docker info &>/dev/null; do sleep 2; done
            else
                err "Homebrew가 필요합니다. https://brew.sh 에서 설치해주세요."
                exit 1
            fi
            ;;
    esac
}

# 3. 포트 충돌 확인
check_port() {
    local in_use=false
    if command -v lsof &>/dev/null; then
        lsof -i :"$BOARD_PORT" &>/dev/null 2>&1 && in_use=true
    elif command -v ss &>/dev/null; then
        ss -tlnp 2>/dev/null | grep -q ":$BOARD_PORT " && in_use=true
    fi
    if $in_use; then
        warn "포트 $BOARD_PORT 이미 사용 중"
        BOARD_PORT=$((BOARD_PORT + 1))
        log "대체 포트 사용: $BOARD_PORT"
    fi
}

# 4. 프로젝트 설치 + 기동
install_board() {
    mkdir -p "$INSTALL_DIR/data"
    cd "$INSTALL_DIR" || { err "설치 경로 접근 실패: $INSTALL_DIR"; exit 1; }

    # docker-compose.yml 생성 (인라인)
    cat > docker-compose.yml << 'COMPOSE'
services:
  board:
    image: ghcr.io/zman-lab/claude-kit-board:latest
    ports:
      - "${BOARD_PORT:-8585}:8585"
    volumes:
      - ./data:/app/data
    restart: always
    environment:
      - DATABASE_URL=sqlite:///data/board.db
      - MCP_MODE=sse
COMPOSE

    BOARD_PORT=$BOARD_PORT docker compose pull
    BOARD_PORT=$BOARD_PORT docker compose up -d
}

# 5. 헬스체크
wait_healthy() {
    log "서버 기동 대기..."
    local max=30
    for i in $(seq 1 $max); do
        if curl -sf "http://localhost:$BOARD_PORT/api/setup/status" &>/dev/null; then
            log "서버 정상 기동! (${i}초)"
            return 0
        fi
        sleep 1
    done
    err "서버 기동 실패. 로그 확인:"
    docker compose logs --tail 20
    exit 1
}

# 6. Claude Code MCP 설정
setup_mcp() {
    local settings_dir="$HOME/.claude"
    local settings_file="$settings_dir/settings.json"

    mkdir -p "$settings_dir"

    if [ ! -f "$settings_file" ]; then
        echo '{}' > "$settings_file"
    fi

    local mcp_url="http://localhost:$BOARD_PORT/mcp/sse"

    if command -v jq &>/dev/null; then
        local tmp
        tmp=$(mktemp)
        jq --arg url "$mcp_url" '.mcpServers["claude-board"] = {"url": $url}' "$settings_file" > "$tmp"
        mv "$tmp" "$settings_file"
    elif command -v python3 &>/dev/null; then
        python3 -c "
import json
f = '$settings_file'
with open(f) as fh: d = json.load(fh)
d.setdefault('mcpServers', {})['claude-board'] = {'url': '$mcp_url'}
with open(f, 'w') as fh: json.dump(d, fh, indent=2)
"
    else
        warn "MCP 자동 설정 실패. 수동 설정 필요:"
        echo "  Claude Code 설정에 추가: claude-board → $mcp_url"
    fi
    log "Claude Code MCP 설정 완료"
}

# 7. 브라우저 오픈
open_browser() {
    local url="http://localhost:$BOARD_PORT"
    local env=$(detect_env)
    case $env in
        wsl2) cmd.exe /c start "$url" 2>/dev/null || wslview "$url" 2>/dev/null || true ;;
        macos) open "$url" ;;
        linux) xdg-open "$url" 2>/dev/null || true ;;
    esac
}

# 메인
main() {
    mkdir -p "$INSTALL_DIR"
    log "Claude Kit 설치 시작"
    log "설치 경로: $INSTALL_DIR"

    ensure_docker
    check_port
    install_board
    wait_healthy
    setup_mcp
    open_browser

    echo ""
    log "설치 완료!"
    log "게시판: http://localhost:$BOARD_PORT"
    log "MCP: http://localhost:$BOARD_PORT/mcp/sse"
    log ""
    log "처음이시면 브라우저에서 팀 설정을 진행해주세요."
}

main "$@" 2>&1 | tee -a "$LOG_FILE"
