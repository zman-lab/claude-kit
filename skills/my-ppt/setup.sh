#!/bin/bash
set -euo pipefail

# my-ppt 스킬 의존성 설치 스크립트
# AI가 자동으로 실행하거나, 사용자가 수동 실행 가능

WORK_DIR="${PPT_WORK_DIR:-$HOME/make_ai_files}"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[my-ppt]${NC} $1"; }
warn() { echo -e "${YELLOW}[경고]${NC} $1"; }
err() { echo -e "${RED}[오류]${NC} $1"; }

# 1. Node.js 확인
check_node() {
    if ! command -v node &>/dev/null; then
        err "Node.js가 설치되지 않았습니다."

        if [[ "$(uname)" == "Darwin" ]]; then
            if command -v brew &>/dev/null; then
                log "Homebrew로 Node.js 설치 중..."
                brew install node
            else
                err "brew가 없습니다. https://nodejs.org 에서 Node.js를 설치하세요."
                exit 1
            fi
        elif command -v apt-get &>/dev/null; then
            log "apt로 Node.js 설치 중..."
            sudo apt-get update && sudo apt-get install -y nodejs npm
        else
            err "https://nodejs.org 에서 Node.js를 설치하세요."
            exit 1
        fi
    fi
    log "Node.js: $(node --version)"
}

# 2. 작업 디렉토리 + npm 패키지 설치
setup_workspace() {
    mkdir -p "$WORK_DIR/ppt"

    if [ ! -f "$WORK_DIR/package.json" ]; then
        log "package.json 생성 중..."
        cat > "$WORK_DIR/package.json" << 'PKGJSON'
{
  "name": "my-ppt-workspace",
  "private": true,
  "dependencies": {
    "pptxgenjs": "^3.12",
    "playwright": "^1.40",
    "sharp": "^0.33"
  }
}
PKGJSON
    fi

    if [ ! -d "$WORK_DIR/node_modules" ]; then
        log "npm 패키지 설치 중..."
        (cd "$WORK_DIR" && npm install)
    else
        log "npm 패키지 이미 설치됨"
    fi
}

# 3. Playwright 브라우저 설치
setup_playwright() {
    if ! npx --prefix "$WORK_DIR" playwright install --dry-run chromium &>/dev/null 2>&1; then
        log "Playwright Chromium 브라우저 설치 중..."
        npx --prefix "$WORK_DIR" playwright install chromium
    else
        # dry-run이 성공해도 실제 브라우저가 없을 수 있으므로 설치 시도
        log "Playwright Chromium 브라우저 확인/설치 중..."
        npx --prefix "$WORK_DIR" playwright install chromium
    fi
}

# 4. 한글 폰트 확인
check_fonts() {
    if [[ "$(uname)" == "Darwin" ]]; then
        # macOS: Apple SD Gothic Neo 기본 내장
        log "macOS 감지 — Apple SD Gothic Neo 기본 내장"
    elif [[ "$(uname)" == "Linux" ]]; then
        if fc-list 2>/dev/null | grep -qi "noto sans kr\|malgun"; then
            log "한글 폰트 감지됨"
        else
            warn "한글 폰트 미설치. Noto Sans KR 설치 중..."
            if command -v apt-get &>/dev/null; then
                sudo apt-get install -y fonts-noto-cjk 2>/dev/null || true
            else
                warn "수동으로 Noto Sans KR 폰트를 설치하세요: https://fonts.google.com/noto/specimen/Noto+Sans+KR"
            fi
        fi
    fi
}

# 5. 스킬 파일 설치 (Claude Code commands 디렉토리로 복사)
install_skill() {
    local skill_src
    skill_src="$(cd "$(dirname "$0")" && pwd)/my-ppt.md"

    if [ ! -f "$skill_src" ]; then
        warn "스킬 파일(my-ppt.md)을 찾을 수 없습니다. 수동으로 복사하세요."
        return
    fi

    # Claude Code 커스텀 명령어 디렉토리
    local cmd_dirs=(
        "$HOME/.claude/commands"
        "$HOME/init/claude/commands"
    )

    local installed=false
    for dir in "${cmd_dirs[@]}"; do
        if [ -d "$dir" ]; then
            cp "$skill_src" "$dir/my-ppt.md"
            log "스킬 설치됨: $dir/my-ppt.md"
            installed=true
            break
        fi
    done

    if ! $installed; then
        mkdir -p "$HOME/.claude/commands"
        cp "$skill_src" "$HOME/.claude/commands/my-ppt.md"
        log "스킬 설치됨: $HOME/.claude/commands/my-ppt.md"
    fi
}

main() {
    log "my-ppt 스킬 설치 시작"
    log "작업 디렉토리: $WORK_DIR"
    echo ""

    check_node
    setup_workspace
    setup_playwright
    check_fonts
    install_skill

    echo ""
    log "설치 완료!"
    log "사용법: Claude Code에서 /my-ppt 입력"
    log "작업 디렉토리: $WORK_DIR/ppt/"
}

main "$@"
