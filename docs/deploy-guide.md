# Claude Kit 배포 가이드

## 친구에게 전달하는 방법

### 방법 1: 원클릭 설치 (추천)
친구에게 아래 메시지를 보내세요:
---
야 이거 Claude Code 켜고 아래 명령어 실행해봐:

```bash
curl -sSL https://raw.githubusercontent.com/zman-lab/claude-kit/main/install.sh | bash
```

그러면 알아서 설치되고 브라우저 뜰거야.
첫 화면에서 비밀번호 설정하고 팀 이름 넣으면 끝.

뭔가 에러나면 에러 메시지 Claude Code에 복붙해.
걔가 알아서 고쳐줄거야.
---

### 방법 2: 수동 설치
```bash
git clone https://github.com/zman-lab/claude-kit.git ~/claude-kit
cd ~/claude-kit
./install.sh
```

### 방법 3: Docker Compose 직접
```bash
git clone https://github.com/zman-lab/claude-kit.git ~/claude-kit
cd ~/claude-kit/board
docker compose up -d
# 브라우저에서 http://localhost:8585 접속
```

## 설치 후 할 일

1. **브라우저에서 접속**: http://localhost:8585
2. **셋업 위자드**: 관리자 비밀번호 설정 → 첫 팀 생성
3. **Admin 페이지**: 추가 팀 생성, 테마 커스텀, 백업 설정
4. **MCP 연결**: install.sh가 자동 설정. 수동은:
   ```json
   // ~/.claude/settings.json
   {
     "mcpServers": {
       "claude-board": {
         "url": "http://localhost:8585/mcp/sse"
       }
     }
   }
   ```

## 컴퓨터 바꿀 때

1. Admin > 백업 탭 > 백업 다운로드
2. 새 컴퓨터에서 install.sh 실행
3. Admin > 백업 탭 > 백업 임포트
4. 끝

## 기존 board 데이터 마이그레이션

```bash
./scripts/migrate-from-board.sh /path/to/board/data/board.db
```

## 문제 해결

에러 메시지를 Claude Code에 복붙하면 CLAUDE.md를 참고하여 자동으로 해결합니다.

### 자주 묻는 문제

| 문제 | 해결 |
|------|------|
| 서버 안 뜸 | `docker compose restart` |
| 비밀번호 잊음 | `sqlite3 data/board.db "SELECT password_plain FROM access_passwords WHERE is_active=1"` |
| 포트 충돌 | `BOARD_PORT=8586 docker compose up -d` |
| DB 날아감 | data/ 폴더 확인 → 백업에서 복구 |
