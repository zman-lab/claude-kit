# my-ppt — 한글 발표자료 제작 스킬

> **AI 전용 문서** — Claude Code가 이 문서를 읽고 스킬을 설치/운영합니다.

HTML/CSS → Playwright 스크린샷 → PPTX 파이프라인으로 고품질 한글 발표자료를 생성하는 Claude Code 커스텀 스킬.

## 왜 이 방식인가?

pptxgenjs 텍스트 API는 한글 폰트 렌더링이 깨짐 (자간, 행간, word-break 제어 불가).
HTML/CSS로 슬라이드를 렌더링한 뒤 Playwright로 스크린샷을 찍어 이미지로 PPTX에 삽입하면 어떤 OS에서도 동일한 결과.

## 설치

```bash
# 자동 설치 (권장)
bash skills/my-ppt/setup.sh

# 또는 작업 디렉토리를 변경하려면
PPT_WORK_DIR=~/my-ppt-workspace bash skills/my-ppt/setup.sh
```

setup.sh가 자동으로 처리하는 것:
1. Node.js 확인 (없으면 brew/apt로 설치)
2. 작업 디렉토리 생성 (`~/make_ai_files/`)
3. npm 패키지 설치 (pptxgenjs, playwright, sharp)
4. Playwright Chromium 브라우저 설치
5. 한글 폰트 확인 (Linux면 Noto Sans KR 설치)
6. 스킬 파일을 Claude Code commands 디렉토리에 복사

## 의존성

| 항목 | 버전 | 용도 |
|------|------|------|
| Node.js | 18+ | 빌드 스크립트 실행 |
| pptxgenjs | ^3.12 | PPTX 파일 생성 (이미지 삽입용) |
| playwright | ^1.40 | HTML → PNG 스크린샷 |
| sharp | ^0.33 | SVG → PNG 배경 이미지 생성 |
| Chromium | (playwright 내장) | 브라우저 렌더링 엔진 |

## 파일 구조

```
skills/my-ppt/
├── README.md       ← 이 파일 (AI용 가이드)
├── my-ppt.md       ← 스킬 본체 (Claude Code가 읽는 명령어 정의)
└── setup.sh        ← 의존성 자동 설치 스크립트
```

설치 후 작업 디렉토리:
```
~/make_ai_files/
├── package.json
├── node_modules/           ← pptxgenjs, playwright, sharp
└── ppt/
    └── {YYYYMMDD}_{제목}/  ← 슬라이드별 작업 폴더
        ├── build-v{N}.js
        ├── bg-v{N}-*.png
        ├── slides-v{N}/
        │   ├── 01-title.html
        │   ├── 01-title.png
        │   └── ...
        └── {프로젝트명}_v{N}.pptx
```

## 환경별 주의사항

### macOS (권장)
- Apple SD Gothic Neo 폰트 기본 내장 — 추가 작업 없음
- Playwright Chromium 최초 실행 시 보안 팝업 → "허용" 클릭 필요

### Linux
- 한글 폰트 수동 설치 필요 (setup.sh가 시도하지만 실패할 수 있음):
  ```bash
  # Ubuntu/Debian
  sudo apt-get install -y fonts-noto-cjk

  # 또는 Noto Sans KR 직접 설치
  # https://fonts.google.com/noto/specimen/Noto+Sans+KR
  ```
- 스킬 파일(`my-ppt.md`)의 font-family 순서 조정 필요:
  ```css
  /* macOS 기본값 */
  font-family: 'Apple SD Gothic Neo', 'Noto Sans KR', 'Malgun Gothic', sans-serif;

  /* Linux에서는 Noto Sans KR을 1순위로 */
  font-family: 'Noto Sans KR', 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif;
  ```

### Windows (WSL2)
- WSL2 환경에서 실행 권장 (네이티브 Windows는 미검증)
- WSL2에서 Playwright 실행 시 추가 의존성:
  ```bash
  sudo apt-get install -y libgbm1 libnss3 libatk-bridge2.0-0 libdrm2 libxkbcommon0 libgtk-3-0
  ```
- 폰트: `Malgun Gothic` 또는 `Noto Sans KR` 설치

## AI 트러블슈팅 가이드

> 아래는 설치/실행 중 발생할 수 있는 문제와 해결법입니다.
> AI가 직접 진단하고 해결하세요. 사용자에게 터미널 명령을 요구하지 마세요.

### "Cannot find module 'pptxgenjs'" 에러
```bash
# 원인: node_modules 미설치 또는 경로 불일치
# 해결:
cd ~/make_ai_files && npm install

# 빌드 파일의 require 경로 확인:
# const pptxgen = require('/Users/유저명/make_ai_files/node_modules/pptxgenjs');
# → 절대경로로 지정하거나, 빌드 파일이 ~/make_ai_files/ 하위에 있어야 함
```

### "Executable doesn't exist at ..." (Playwright 브라우저 없음)
```bash
npx --prefix ~/make_ai_files playwright install chromium
```

### 한글이 □□□ 또는 깨진 문자로 보임
```bash
# 1. 폰트 확인
fc-list | grep -i "gothic\|noto.*kr\|malgun"

# 2. 없으면 설치
sudo apt-get install -y fonts-noto-cjk  # Linux
# macOS는 Apple SD Gothic Neo 기본 내장

# 3. 폰트 캐시 갱신
fc-cache -fv
```

### 이미지가 흐릿하게 나옴
빌드 파일에서 `deviceScaleFactor: 2` 확인. 1이면 960x540 저해상도.

### sharp 설치 실패 (Linux ARM/특수 환경)
```bash
# pre-built 바이너리 없는 환경
npm install --build-from-source sharp

# 빌드 도구 필요:
sudo apt-get install -y build-essential python3
```

### 작업 디렉토리 변경하고 싶을 때
```bash
# setup.sh 실행 시 환경변수로 지정
PPT_WORK_DIR=~/my-custom-dir bash setup.sh

# 스킬 파일(my-ppt.md)에서 ~/make_ai_files/ 경로를 일괄 수정
# AI가 빌드 파일 생성 시 해당 경로를 사용하면 됨
```

## 사용법

Claude Code에서:
```
/my-ppt 분기 실적 보고
/my-ppt ~/make_ai_files/ppt/20260315_보고/build-v1.js   # 기존 빌드 수정
```
