# sysmon

On-demand system resource monitor with actionable insights.

MCP 프로세스 폭발, RAM 압박 등을 감지하고 원클릭으로 정리할 수 있는 대시보드.

## Quick Start

```bash
cd sysmon
PYTHONPATH=. python3 -m sysmon
# → http://127.0.0.1:19090 열림
```

PyPI 배포 후:
```bash
pip install claude-kit-sysmon
sysmon
```

## CLI Options

```
sysmon                          # localhost:19090, 브라우저 자동 오픈
sysmon --port 9090              # 포트 변경
sysmon --no-browser             # 브라우저 안 열기
sysmon --token mysecret         # 토큰 인증 + 0.0.0.0 바인딩 (원격 접근)
sysmon --host 0.0.0.0           # 외부 접근 허용
```

## Features

- **실시간 대시보드** — CPU/RAM 그래프 (5초 경량 폴링), 디스크, 로드, Docker 현황
- **메모리 분석** — 트리맵 시각화, MCP/Claude/앱별 분류
- **룰 기반 인사이트** — MCP 폭발, RAM 압박, 서브에이전트 과다 자동 감지
- **원클릭 액션** — MCP 프로세스 정리, 메모리 캐시 퍼지 (확인 팝업 + 결과 표시)
- **크로스 플랫폼** — macOS (`sysctl`, `vm_stat`) + Linux (`/proc/*`) 자동 감지
- **외부 의존성 0** — Python 표준 라이브러리만 사용

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
| GET | `/api/metrics` | Full metrics (CPU, RAM, Disk, MCP, Claude, Docker, Insights) |
| GET | `/api/quick` | Lightweight CPU+RAM only (<200ms) |
| POST | `/api/action/{id}` | Execute action (kill_all_mcp, purge_cache, etc.) |

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
