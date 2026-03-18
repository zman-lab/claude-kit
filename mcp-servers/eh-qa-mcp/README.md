# elkhound-qa MCP Server

ElkHound 웹서비스 QA 자동화 MCP 서버 (MVP — Phase 1)

## 도구 목록 (8개)

| 도구 | 설명 |
|------|------|
| `health_check` | API 헬스체크 (응답시간, 인덱스 수) |
| `run_pytest` | pytest 실행 + 결과 파싱 (pass/fail/error) |
| `run_curl_tc` | curl TC 1건 실행 (HTTP 메서드 + 경로 + 기대값) |
| `docker_build` | Docker compose build (--no-cache) |
| `docker_up` | compose up -d + 헬스체크 대기 |
| `docker_down` | compose down |
| `check_logs` | docker logs --tail N + grep 필터 |
| `pool_status` | DaemonPool 상태 조회 (/api/status) |
| `full_qa` | 통합: build → up → health → pytest → logs |

## 환경변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `EH_TARGET` | `local` | 대상 환경 (`local` / `alpha7`) |
| `EH_PROJECT_PATH` | `/Users/nhn/work/ideaworks/product/elkhound` | 프로젝트 경로 |
| `EH_DOCKER_COMPOSE` | (자동) | compose 파일 경로 (비어있으면 target에 따라 자동 선택) |

## settings.json 등록

```jsonc
// ~/.claude/settings.json → mcpServers
{
  "mcpServers": {
    "elkhound-qa": {
      "command": "uv",
      "args": [
        "--directory", "/Users/nhn/zman-lab/claude-kit/mcp-servers/elkhound-qa",
        "run", "elkhound-qa-mcp"
      ],
      "env": {
        "EH_TARGET": "local",
        "EH_PROJECT_PATH": "/Users/nhn/work/ideaworks/product/elkhound"
      }
    }
  }
}
```

## 로컬 실행 테스트

```bash
cd ~/zman-lab/claude-kit/mcp-servers/elkhound-qa
uv run elkhound-qa-mcp
```
