# Law 계약서 서비스 — AI 설치 가이드

> 이 문서는 **AI 어시스턴트(Claude Code)가 읽고 자동으로 설치/운영**하기 위한 가이드입니다.
> 사용자가 "법률 서비스 설치해줘"라고 하면, 이 가이드를 따라 처리하세요.
>
> **핵심 원칙**: 사용자는 컴퓨터 비전문가입니다. 기술 용어로 질문하지 말고, 모든 것을 직접 처리하세요.
> 실패 시 최소 3가지 방법을 시도한 후, 그래도 안 되면 사용자에게 단순한 말로 상황을 설명하세요.

---

## 서비스 소개

AI 기반 계약서 초안 생성 + 법률 검토 서비스입니다.

| 기능 | 설명 |
|------|------|
| 계약서 초안 생성 | 계약 유형(용역, SaaS, NDA 등) 선택 → AI가 초안 작성 |
| 계약서 검토 | PDF/DOCX 업로드 → 위험 조항 분석 + 법적 근거 제시 |
| 법무 채팅 | 4인 법무자문단(이사/변호사/팀장/연구원) 실시간 상담 |
| 보고서 다운로드 | 검토 결과를 PDF/DOCX로 내보내기 |

**접속 URL**: `http://localhost:7999/law/`

---

## 전제 조건

| 항목 | 필수 | 확인 방법 | 없으면 |
|------|------|----------|--------|
| WSL2 + Ubuntu 22.04+ | 필수 | `wsl --version` | Windows 설정에서 WSL2 활성화 |
| Docker | 필수 | `docker --version` | 아래 자동 설치 섹션 참조 |
| Claude Code Max | 필수 | `which claude` | claude.ai/download 에서 설치 후 한 번 실행(로그인) |

### Docker 자동 설치 (없을 경우)

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-plugin
sudo usermod -aG docker "$USER"
sudo service docker start
# 그룹 반영: 터미널을 닫고 다시 열거나
exec sg docker -c "bash"
```

### Claude Code 인증 확인

```bash
# 인증 파일 존재 여부
ls ~/.claude/.claude.json 2>/dev/null && echo "인증 OK" || echo "인증 필요"

# 인증 안 되어 있으면:
# 사용자에게 "터미널에 claude 라고 한 번만 치고 로그인해주세요" 안내
# 로그인 완료 후 다시 이 스크립트 실행
```

---

## 아키텍처

```
사용자 브라우저
    ↓
localhost:7999 (nginx)
    ├─ /law/          → Frontend (Next.js, standalone)
    ├─ /law/api/      → Backend (FastAPI, Cython 컴파일)
    │                      ├─ Claude CLI (--print 모드, 호스트 인증 사용)
    │                      ├─ 법제처 API (법령/판례 검색)
    │                      └─ PostgreSQL + Redis
    └─ /              → /law/ 리다이렉트
```

**코드 보호**: 백엔드는 Cython 컴파일(.so), 프론트엔드는 minified 번들. 소스코드 없음.

**Claude CLI 연동**: Docker 이미지에 Claude CLI가 내장되어 있고, 호스트의 `~/.claude/` 인증 토큰을 읽기전용으로 마운트. 별도 인증 불필요.

---

## 설치

### 방법 1: setup.sh (권장)

```bash
cd ~/claude-kit/law
./setup.sh
```

setup.sh가 자동으로:
1. Docker 설치 여부 확인 (없으면 설치)
2. Claude 인증 확인 (없으면 안내)
3. Docker 이미지 로드 (images/ 폴더에서)
4. .env 자동 생성 (Claude 경로 감지)
5. docker compose up -d
6. 헬스체크 후 브라우저 오픈

### 방법 2: 수동

```bash
cd ~/claude-kit/law

# 1. Docker 이미지 로드
docker load < images/law-backend.tar.gz
docker load < images/law-frontend.tar.gz
docker load < images/law-nginx.tar.gz

# 2. 환경 설정
cp .env.example .env
# .env 편집: CLAUDE_HOME 경로 확인 (보통 ~/.claude)

# 3. 실행
docker compose up -d

# 4. 확인
curl -sf http://localhost:7999/law/ -o /dev/null && echo "OK" || echo "FAIL"
```

---

## 환경 변수 (.env)

| 변수 | 설명 | 기본값 | 수정 필요? |
|------|------|--------|-----------|
| `CLAUDE_HOME` | Claude 인증 디렉토리 경로 | `~/.claude` | setup.sh가 자동 감지 |
| `LAW_PORT` | 외부 접속 포트 | `7999` | 포트 충돌 시만 변경 |
| `LAW_API_OC` | 법제처 API 인증키 | (사전 설정됨) | 변경 불필요 |
| `ADMIN_PASSWORD` | 관리자 비밀번호 | `7895` | 원하면 변경 |
| `AI_PROVIDER` | AI 모드 | `cli` | 변경 불필요 |
| `CLAUDE_MODEL` | 사용 AI 모델 | `claude-sonnet-4-20250514` | 변경 불필요 |

---

## Docker Compose 구조

```yaml
services:
  nginx:
    image: law-nginx:latest
    ports: ["${LAW_PORT:-7999}:80"]
    depends_on: [backend, frontend]

  backend:
    image: law-backend:latest
    environment:
      - CLAUDE_CONFIG_DIR=/root/.claude
      - DATABASE_URL=postgresql+asyncpg://law:law@postgres:5432/law
      - REDIS_URL=redis://redis:6379/0
      - AI_PROVIDER=cli
      - LAW_API_OC=${LAW_API_OC}
    volumes:
      - ${CLAUDE_HOME:-~/.claude}:/root/.claude:ro

  frontend:
    image: law-frontend:latest
    environment:
      - NEXT_PUBLIC_API_URL=

  postgres:
    image: postgres:16-alpine
    environment:
      - POSTGRES_DB=law
      - POSTGRES_USER=law
      - POSTGRES_PASSWORD=law
    volumes:
      - pgdata:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine

volumes:
  pgdata:
```

---

## 트러블슈팅

### 서버 접속 안 됨

```bash
# 1. 컨테이너 상태 확인
docker compose ps

# 2. 로그 확인
docker compose logs --tail 20

# 3. 재시작
docker compose restart

# 4. 전체 재생성
docker compose down && docker compose up -d

# 5. Docker 자체가 안 되면 (WSL2)
sudo service docker start
```

### Claude CLI 오류 (AI 응답 안 됨)

```bash
# 1. 컨테이너 안에서 claude 동작 확인
docker exec law-backend claude --version

# 2. 인증 마운트 확인
docker exec law-backend ls /root/.claude/.claude.json

# 3. 실제 AI 호출 테스트
docker exec law-backend claude --print "안녕하세요" --output-format json

# 4. 마운트 경로 확인
docker inspect law-backend | grep -A5 Mounts

# 해결 안 되면:
# → CLAUDE_HOME 경로가 호스트의 실제 인증 디렉토리와 일치하는지 확인
# → 사용자에게: "터미널에서 claude 라고 쳐서 작동하는지 확인해주세요"
```

### 포트 충돌

```bash
# 7999 포트 사용 중인 프로세스 확인
lsof -i :7999 2>/dev/null || ss -tlnp | grep 7999

# .env에서 포트 변경
sed -i 's/LAW_PORT=.*/LAW_PORT=8999/' .env
docker compose down && docker compose up -d
```

### DB 초기화 (데이터 리셋)

```bash
docker compose down -v   # 볼륨 포함 삭제
docker compose up -d     # 새 DB로 시작
# 초기 관리자 비밀번호: 7895
```

### WSL2 특이사항

```bash
# Docker 서비스 안 뜸
sudo service docker start

# Windows 브라우저에서 localhost 접속 안 됨
# 방법 1: .wslconfig 확인
cat /mnt/c/Users/$(cmd.exe /c "echo %USERNAME%" 2>/dev/null | tr -d '\r')/.wslconfig
# [wsl2] 아래 localhostForwarding=true 확인

# 방법 2: WSL IP로 직접 접속
ip addr show eth0 | grep "inet " | awk '{print $2}' | cut -d/ -f1
# 출력된 IP:7999 로 브라우저 접속
```

### 컴퓨터 재부팅 후

```bash
# Docker restart:always 정책으로 자동 시작되어야 함
# 안 되면:
sudo service docker start
# 20초 대기 후 자동 복구
sleep 20 && curl -sf http://localhost:7999/law/ -o /dev/null && echo "OK"
```

---

## 사용법 안내 (사용자에게 전달)

설치 완료 후 사용자에게 이렇게 안내하세요:

> **브라우저에서 http://localhost:7999/law/ 에 접속하시면 됩니다.**
>
> - 처음 접속하면 비밀번호 입력창이 뜹니다. 비밀번호: `7895`
> - "계약서 초안" 탭에서 계약 유형을 선택하고 요청사항을 입력하면 AI가 작성합니다
> - "계약서 검토" 탭에서 PDF/DOCX 파일을 업로드하면 AI가 분석합니다
> - "채팅" 탭에서 법률 관련 질문을 하면 법무자문단이 답변합니다

---

## 업데이트

새 버전 이미지를 받으면:

```bash
cd ~/claude-kit/law
docker load < images/law-backend-new.tar.gz
docker compose up -d
```

---

## 백업/복원

```bash
# 백업 (DB 데이터)
docker exec law-postgres pg_dump -U law law > backup_$(date +%Y%m%d).sql

# 복원
cat backup.sql | docker exec -i law-postgres psql -U law law
```

---

## 주의사항

- 이 서비스의 법률 자문은 AI가 생성한 것으로, **전문 법률 자문을 대체하지 않습니다**
- 계약서 초안/검토 결과는 반드시 전문가 검토 후 사용하세요
- 인터넷 연결 필요 (Claude API + 법제처 API)
- Claude Code Max 구독이 유지되어야 AI 기능 사용 가능
