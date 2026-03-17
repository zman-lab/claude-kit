# sysmon

On-demand system resource monitor with actionable insights.

MCP 프로세스 폭발, RAM 압박 등을 감지하고 원클릭으로 정리할 수 있는 대시보드.

## 설치 (각자 로컬)

### 1. 레포 클론

```bash
# claude-kit 레포가 없으면 클론
git clone https://github.com/zman-lab/claude-kit.git ~/zman-lab/claude-kit
```

이미 있으면 pull:
```bash
git -C ~/zman-lab/claude-kit pull
```

### 2. 실행 확인

```bash
cd ~/zman-lab/claude-kit/sysmon
PYTHONPATH=. python3 -m sysmon
# → http://127.0.0.1:19090 열림
```

외부 의존성 없음 (Python 표준 라이브러리만 사용). Python 3.9+ 필요.

### 3. 자동 실행 등록 (launchd)

Mac 부팅/로그인 시 자동으로 Sysmon이 뜨도록 설정:

```bash
# plist 파일 생성 (경로를 자신의 환경에 맞게 수정!)
cat > ~/Library/LaunchAgents/com.claude-sysmon.plist << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.claude-sysmon</string>
    <key>ProgramArguments</key>
    <array>
        <string>/opt/homebrew/bin/python3</string>
        <string>-m</string>
        <string>sysmon</string>
        <string>--no-browser</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$HOME/zman-lab/claude-kit/sysmon</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONPATH</key>
        <string>$HOME/zman-lab/claude-kit/sysmon</string>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/sysmon.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/sysmon.log</string>
</dict>
</plist>
PLIST

# $HOME을 실제 경로로 치환
sed -i '' "s|\$HOME|$HOME|g" ~/Library/LaunchAgents/com.claude-sysmon.plist

# 등록 + 즉시 시작
launchctl load ~/Library/LaunchAgents/com.claude-sysmon.plist
```

확인:
```bash
curl -sf http://127.0.0.1:19090/ > /dev/null && echo "Sysmon OK" || echo "Sysmon FAIL"
```

해제:
```bash
launchctl unload ~/Library/LaunchAgents/com.claude-sysmon.plist
```

### 4. Board 사이드바에서 접근

Board 게시판(`http://localhost:8585`)의 좌측 사이드바에 **Sysmon** 링크가 있음.
클릭하면 `http://localhost:19090/` 으로 새 탭이 열림.

> Board와 Sysmon 모두 각자 로컬에서 실행되므로 localhost로 접근.

## CLI Options

```
sysmon                          # localhost:19090, 브라우저 자동 오픈
sysmon --port 9090              # 포트 변경
sysmon --no-browser             # 브라우저 안 열기
sysmon --token mysecret         # 토큰 인증 + 0.0.0.0 바인딩 (원격 접근)
sysmon --host 0.0.0.0           # 외부 접근 허용
```

## Features

### Overview
- **실시간 대시보드** — CPU/RAM 그래프 (5초 전체 갱신), 디스크, 로드, Docker, 프로세스
- **메모리 카테고리별 바 차트** — MCP/Claude/Chrome/보안SW/Docker 등

### Memory Analysis
- **트리맵 시각화** — RAM 전체 지도 (블록 크기 = 실제 비율)
- **MCP 서버별 분석** — 프로세스 수/메모리 per MCP
- **룰 기반 인사이트** — MCP 폭발, RAM 압박, 서브에이전트 과다 자동 감지
- **원클릭 액션** — MCP 전체 정리, 메모리 캐시 퍼지 (확인 팝업 + 결과 표시)

### Claude Sessions
- **메인/서브 트리 구조** — 메인 세션별 서브에이전트 매핑 (ppid 기반)
- **좀비 감지** — 부모 없는 서브에이전트 자동 탐지
- **팀/모델/시작시간** — cwd 기반 팀 감지, 모델명(opus/sonnet), 상대시간
- **개별 Kill** — 세션/서브에이전트/좀비 각각 종료 (확인 팝업)

### Docker
- **컨테이너 현황** — 이름, 이미지, 상태, 업타임, health, 메모리, CPU%, 포트
- **Stop / Start / Restart** — 컨테이너별 조작 (확인 팝업)
- **로그 뷰어 팝업** — 디버그 콘솔 스타일 (레벨 필터, 검색, 자동 스크롤, 3초 갱신)

### Claude Config
- **설정 파일 스캔** — CLAUDE.md, Skills, Memory, Settings 전체 탐색 (수동 Scan)
- **팀별 그룹핑** — Global → 프로젝트 상속 구조 표시
- **필터 태그** — 카테고리별/팀별 필터 + 실시간 검색
- **참조 카운트** — `in:N` (외부에서 참조됨) / `out:N` (내부에서 호출)
- **마크다운 팝업 뷰어** — 클릭하면 렌더링된 마크다운 팝업 (복사/닫기)
- **디펜던시 그래프** — SVG force-directed 시각화 (스킬 체인, 메모리 참조)

### 공통
- **크로스 플랫폼** — macOS (`sysctl`, `vm_stat`) + Linux (`/proc/*`) 자동 감지
- **외부 의존성 0** — Python 표준 라이브러리만 사용
- **5초 전체 갱신** — Overview/Memory/Claude Sessions/Docker 실시간 업데이트

## Embedding (FastAPI)

```python
from sysmon.router import create_router

app.include_router(create_router(), prefix="/sysmon")
# → /sysmon/ 에 대시보드, /sysmon/api/metrics 에 API
```

FastAPI optional dependency: `pip install claude-kit-sysmon[fastapi]`

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Dashboard HTML |
| GET | `/api/metrics` | Full metrics (5초 폴링 — CPU, RAM, Disk, MCP, Claude, Docker, Insights) |
| GET | `/api/quick` | Lightweight CPU+RAM only (<200ms) |
| POST | `/api/action/{id}` | Execute action (kill_all_mcp, kill_claude_{pid}, docker_stop_{name}, etc.) |
| GET | `/api/docker-logs/{name}` | Docker 컨테이너 로그 (tail, level, search 파라미터) |
| GET | `/docker-log?name=xxx` | Docker 로그 뷰어 HTML 페이지 |
| GET | `/api/claude-config` | Claude 설정 파일 전체 스캔 (on-demand) |
| GET | `/api/claude-file?path=xxx` | 파일 내용 읽기 (허용 경로만) |
| GET | `/api/claude-deps?path=xxx` | 파일 디펜던시 분석 (노드 + 엣지) |

## Architecture

```
sysmon/
├── collectors/         # OS별 메트릭 수집
│   ├── base.py         # ABC + 공통 로직 (MCP/Claude 분석)
│   ├── darwin.py       # macOS (sysctl, vm_stat, top)
│   └── linux.py        # Linux (/proc/meminfo, /proc/stat)
├── analyzer.py         # 룰 기반 인사이트 엔진
├── actions.py          # 액션 실행기
├── server.py           # 내장 HTTP 서버
├── router.py           # FastAPI Router (optional)
├── cli.py              # CLI entry point
└── static/index.html   # Dashboard UI (vanilla JS)
```

## Token Auth

원격 접근 시 `--token` 옵션 사용:

```bash
sysmon --token my-secret-key
# → http://host:19090?token=my-secret-key
```

또는 HTTP 헤더: `Authorization: Bearer my-secret-key`

## Troubleshooting

| 증상 | 원인 | 해결 |
|------|------|------|
| `curl` 실패 | 프로세스 안 떠있음 | `launchctl load` 재실행 |
| 포트 충돌 | 19090 이미 사용 중 | `lsof -i :19090` 확인 후 `--port` 변경 |
| `python3` not found | Homebrew Python 경로 다름 | plist의 `ProgramArguments` 경로를 `which python3` 결과로 수정 |
| launchd 등록 실패 | plist 문법 오류 | `plutil -lint ~/Library/LaunchAgents/com.claude-sysmon.plist` |
