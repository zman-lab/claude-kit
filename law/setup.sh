#!/bin/bash
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"
LAW_PORT="${LAW_PORT:-7999}"
LOG_FILE="$INSTALL_DIR/setup.log"

# 색상
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[law-kit]${NC} $1"; }
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

# 2. Docker 확인 + 자동 설치
ensure_docker() {
    if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
        log "Docker 감지됨: $(docker --version)"
        return 0
    fi

    local env
    env=$(detect_env)
    log "Docker 설치 중 ($env)..."

    case $env in
        wsl2|linux)
            sudo apt-get update -qq
            sudo apt-get install -y -qq docker.io docker-compose-plugin
            sudo usermod -aG docker "$USER"
            sudo service docker start
            if ! docker info &>/dev/null 2>&1; then
                log "Docker 그룹 반영을 위해 재실행..."
                exec sg docker -c "bash $0 $*"
            fi
            ;;
        macos)
            if command -v brew &>/dev/null; then
                brew install --cask docker
                open /Applications/Docker.app
                log "Docker Desktop 시작 대기..."
                while ! docker info &>/dev/null 2>&1; do sleep 2; done
            else
                err "Homebrew 필요: https://brew.sh"
                exit 1
            fi
            ;;
    esac
}

# 3. Claude 인증 확인
check_claude_auth() {
    local claude_home=""

    # 방법 1: CLAUDE_HOME 환경변수
    if [ -n "${CLAUDE_HOME:-}" ] && [ -d "$CLAUDE_HOME" ]; then
        claude_home="$CLAUDE_HOME"
    # 방법 2: 기본 경로
    elif [ -d "$HOME/.claude" ]; then
        claude_home="$HOME/.claude"
    fi

    if [ -z "$claude_home" ] || [ ! -f "$claude_home/.claude.json" ]; then
        warn "Claude Code 인증 정보를 찾을 수 없습니다."
        echo ""
        echo "  터미널에서 'claude' 를 실행하고 로그인해주세요."
        echo "  로그인 완료 후 이 스크립트를 다시 실행하세요."
        echo ""
        exit 1
    fi

    log "Claude 인증 확인됨: $claude_home"
    echo "$claude_home"
}

# 4. 포트 충돌 확인
check_port() {
    local in_use=false
    if command -v lsof &>/dev/null; then
        lsof -i :"$LAW_PORT" &>/dev/null 2>&1 && in_use=true
    elif command -v ss &>/dev/null; then
        ss -tlnp 2>/dev/null | grep -q ":$LAW_PORT " && in_use=true
    fi
    if $in_use; then
        warn "포트 $LAW_PORT 사용 중"
        LAW_PORT=$((LAW_PORT + 1))
        log "대체 포트: $LAW_PORT"
    fi
}

# 5. Docker 이미지 로드
load_images() {
    local img_dir="$INSTALL_DIR/images"
    if [ ! -d "$img_dir" ]; then
        err "images/ 폴더를 찾을 수 없습니다."
        exit 1
    fi

    local loaded=0
    for img in "$img_dir"/*.tar.gz; do
        if [ -f "$img" ]; then
            log "이미지 로드: $(basename "$img")..."
            docker load < "$img"
            loaded=$((loaded + 1))
        fi
    done

    if [ "$loaded" -eq 0 ]; then
        err "images/ 폴더에 .tar.gz 파일이 없습니다."
        exit 1
    fi
}

# 6. 환경 설정
setup_env() {
    local claude_home="$1"

    if [ ! -f "$INSTALL_DIR/.env" ]; then
        cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
    fi

    # CLAUDE_HOME 자동 설정
    sed -i "s|CLAUDE_HOME=.*|CLAUDE_HOME=$claude_home|" "$INSTALL_DIR/.env"
    sed -i "s|LAW_PORT=.*|LAW_PORT=$LAW_PORT|" "$INSTALL_DIR/.env"

    log "환경 설정 완료: .env"
}

# 7. 서비스 시작
start_services() {
    cd "$INSTALL_DIR"
    docker compose up -d
}

# 8. 헬스체크
wait_healthy() {
    log "서버 기동 대기..."
    local max=60
    for i in $(seq 1 $max); do
        if curl -sf "http://localhost:$LAW_PORT/law/" -o /dev/null 2>/dev/null; then
            log "서버 정상! (${i}초)"
            return 0
        fi
        sleep 1
    done
    warn "서버 기동 지연. 로그 확인:"
    docker compose logs --tail 10
}

# 9. 브라우저 오픈
open_browser() {
    local url="http://localhost:$LAW_PORT/law/"
    local env
    env=$(detect_env)
    case $env in
        wsl2) cmd.exe /c start "$url" 2>/dev/null || wslview "$url" 2>/dev/null || true ;;
        macos) open "$url" ;;
        linux) xdg-open "$url" 2>/dev/null || true ;;
    esac
}

# 메인
main() {
    echo ""
    log "=== Law 계약서 서비스 설치 ==="
    echo ""

    ensure_docker
    local claude_home
    claude_home=$(check_claude_auth)
    check_port
    load_images
    setup_env "$claude_home"
    start_services
    wait_healthy
    open_browser

    echo ""
    log "=============================="
    log "설치 완료!"
    log "접속: http://localhost:$LAW_PORT/law/"
    log "관리자 비밀번호: $(grep ADMIN_PASSWORD "$INSTALL_DIR/.env" | cut -d= -f2)"
    log "=============================="
    echo ""
}

main "$@" 2>&1 | tee -a "$LOG_FILE"
