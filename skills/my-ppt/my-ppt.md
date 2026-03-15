# PPT 발표자료 제작 스킬

HTML/CSS → Playwright 스크린샷 → PPTX 파이프라인으로 고품질 한글 발표자료를 생성한다.

## 사전 준비 (자동)

스킬 실행 시 의존성을 자동 확인/설치한다:
```bash
[ -d ~/make_ai_files/node_modules ] || (cd ~/make_ai_files && npm install)
```
- 의존성 경로: `~/make_ai_files/node_modules/` (pptxgenjs, playwright, sharp)
- playwright 브라우저: `npx playwright install chromium` (최초 1회)
- package.json은 `~/make_ai_files/package.json`에 미리 정의됨

## 출력 파일 관리

- **기본 출력 경로**: `~/make_ai_files/ppt/{YYYYMMDD}_{제목}/`
- 예: `~/make_ai_files/ppt/20260309_분기보고/`
- PPT 파일, 중간 산출물(HTML, PNG, 배경 이미지) 모두 해당 폴더에 저장
- 완성된 PPTX는 `~/Downloads/`에도 복사
- **`/Users/nhn/work/`에 파일 생성 금지** (작업 디렉토리 오염 방지)

## 사용법

```
/my-ppt [주제 또는 기존 빌드파일 경로]
```

- 주제만 주면: 슬라이드 기획 → HTML → PPTX 전체 과정 진행
- 기존 빌드파일 경로: 해당 파일 수정/재빌드
- 아무 인자 없으면: 사용자에게 주제 질문

## 핵심 원칙

### 왜 이 방식인가?
- **pptxgenjs 텍스트 API**는 한글 폰트 렌더링이 깨짐 (자간, 행간, word-break 제어 불가)
- **HTML/CSS로 슬라이드를 렌더링**하면 한글 완벽 제어 가능
- **Playwright로 스크린샷**을 찍어 이미지로 PPTX에 삽입 → 어떤 OS에서도 동일한 결과
- pptxgenjs는 **이미지 삽입 + 메타데이터(노트)용**으로만 사용

### 한글 폰트 설정 (절대 변경 금지)
```css
font-family: 'Apple SD Gothic Neo', 'Noto Sans KR', 'Malgun Gothic', sans-serif;
-webkit-font-smoothing: antialiased;
letter-spacing: -0.01em;
word-break: keep-all;
line-height: 1.55;
```
- **Apple SD Gothic Neo**: macOS 기본 한글 폰트 (1순위)
- **Noto Sans KR**: Google 폰트 (2순위, CDN 불필요 — Playwright가 로컬 폰트 사용)
- **Malgun Gothic**: Windows 폴백 (3순위)

### 뷰포트 설정
```javascript
const page = await browser.newPage({
  viewport: { width: 960, height: 540 },
  deviceScaleFactor: 2  // → 실제 출력 1920x1080
});
```
- HTML은 **960x540** 기준으로 작성 (px 단위)
- `deviceScaleFactor: 2`로 **1920x1080 고해상도** 출력
- PPTX 슬라이드 크기: **10x5.625 인치** (16:9)

## 빌드 파일 구조

### 필수 의존성
```json
{
  "pptxgenjs": "^3.12",
  "playwright": "^1.40",
  "sharp": "^0.33"
}
```
- 작업 디렉토리에 `package.json` + `node_modules` 필요
- 없으면: `npm init -y && npm i pptxgenjs playwright sharp`

### 빌드 파일 (build-v{N}.js) 구조
```
1. createAssets()     — SVG → PNG 배경 이미지 생성 (sharp)
2. generateSlides()   — Playwright로 HTML → PNG 렌더링
3. generateScript()   — 발표 스크립트 MD 파일 생성
4. createPptx()       — PNG 이미지를 PPTX로 조립 (pptxgenjs)
5. main()             — 파이프라인 실행
```

### 디렉토리 레이아웃
```
~/make_ai_files/ppt/{YYYYMMDD}_{제목}/     # 작업 폴더
├── build-v{N}.js          # 빌드 스크립트
├── bg-v{N}-*.png          # 배경 이미지 (자동 생성)
├── slides-v{N}/           # HTML 슬라이드 + 스크린샷
│   ├── 01-title.html
│   ├── 01-title.png       # (자동 생성)
│   ├── 02-impact.html
│   └── ...
├── 발표스크립트_v{N}.md    # 발표 스크립트 (자동 생성)
└── {프로젝트명}_v{N}.pptx  # 최종 결과물
```
- 의존성은 `~/make_ai_files/node_modules/`를 참조 (빌드파일에서 `require()` 경로 지정)

## 슬라이드 HTML 작성 규칙

### 기본 CSS 구조 (모든 슬라이드 공통)
```css
* { box-sizing: border-box; margin: 0; padding: 0 }
html { background: #0D1B2A }
body {
  width: 960px; height: 540px; margin: 0; padding: 0; overflow: hidden;
  font-family: 'Apple SD Gothic Neo','Noto Sans KR','Malgun Gothic',sans-serif;
  display: flex; flex-direction: column;
  background-image: url('../bg-v{N}-content.png'); background-size: cover;
  -webkit-font-smoothing: antialiased;
}
p,h1,h2,h3,div,span,td,th {
  word-break: keep-all; line-height: 1.55; letter-spacing: -0.01em;
}
```

### 컬러 팔레트 (기본값 — 프로젝트에 따라 변경 가능)
```javascript
const BG  = '#0D1B2A';  // 배경 (다크 네이비)
const BG2 = '#132238';  // 카드 배경
const BG3 = '#1A3050';  // 강조 카드 배경
const TEAL  = '#00D4AA'; // 주요 강조색
const GOLD  = '#FFB800'; // 보조 강조색
const CORAL = '#FF6B6B'; // 경고/위험
const WHITE = '#FFFFFF';
const GRAY  = '#7B96B5'; // 비활성 텍스트
const LGRAY = '#A8C0D8'; // 본문 텍스트
```

### 슬라이드 타입별 패턴

**타이틀 슬라이드** (1장):
- 배경: gradient (bg-title.png)
- 프로젝트명 크게, 부제 작게, 발표자 정보

**임팩트 슬라이드** (KPI, 비용 비교 등):
- 배경: 중앙 원형 글로우 (bg-impact.png)
- 큰 숫자 강조 (font-size: 60px+, color: TEAL/GOLD)
- 3~4개 카드 레이아웃

**콘텐츠 슬라이드** (일반):
- 배경: 좌측 바 (bg-content.png)
- 2컬럼 레이아웃 (flex, gap)
- 카드형 정보 박스 (BG2 배경, border-radius: 8px)

**마무리 슬라이드** (감사합니다):
- 배경: reverse gradient (bg-end.png)
- 연락처, 프로젝트 정보

### 폰트 크기 가이드 (960x540 기준)
| 용도 | 크기 | 비고 |
|------|------|------|
| 슬라이드 제목 | 28-32px | bold, WHITE |
| 섹션 제목 | 14-16px | bold, TEAL |
| 카드 제목 | 13-14px | bold, WHITE |
| 본문 | 11-12px | LGRAY |
| 부가 설명 | 10px | GRAY |
| 큰 숫자 (임팩트) | 48-72px | bold, TEAL/GOLD |
| 코드/API | 9-10px | monospace |

## 발표자 노트 & 스크립트

### NOTES 객체 (빌드파일 내)
```javascript
const NOTES = {
  '01-title': '인사 후 주제 소개. "오늘 발표할 내용은..."',
  '02-impact': '핵심 숫자부터 강조. 청중의 관심을 끌기.',
  // ...
};
```

### 스크립트 MD 자동 생성
```javascript
function generateScript() {
  let md = '# 발표 스크립트\n\n';
  for (const [slide, note] of Object.entries(NOTES)) {
    const num = slide.split('-')[0];
    md += `## 슬라이드 ${num}\n${note}\n\n---\n\n`;
  }
  fs.writeFileSync(`${WS}/발표스크립트_v${N}.md`, md);
}
```

### PPTX 노트 삽입
```javascript
slide.addNotes(NOTES[slideName] || '');
```

## 배경 이미지 생성 (sharp)

### SVG → PNG 패턴
```javascript
async function createAssets() {
  const bg = (name, svg) =>
    sharp(Buffer.from(svg)).png().toFile(`${WS}/${name}`);

  // 타이틀: gradient + 글로우 서클
  await bg('bg-v3-title.png', `
    <svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080">
      <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stop-color="#0A1525"/>
        <stop offset="100%" stop-color="#0F2E3D"/>
      </linearGradient></defs>
      <rect width="100%" height="100%" fill="url(#g)"/>
      <circle cx="1500" cy="250" r="500" fill="${TEAL}" opacity="0.03"/>
    </svg>`);

  // 콘텐츠: 좌측 액센트 바
  await bg('bg-v3-content.png', `
    <svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080">
      <rect width="100%" height="100%" fill="${BG}"/>
      <rect x="0" y="0" width="6" height="1080" fill="${TEAL}" opacity="0.5"/>
    </svg>`);
}
```
- 배경 이미지는 **1920x1080** 크기로 생성 (deviceScaleFactor와 맞춤)
- `!fs.existsSync()` 체크로 이미 있으면 재생성 안 함

## Playwright 렌더링

### 슬라이드 스크린샷
```javascript
async function generateSlides() {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({
    viewport: { width: 960, height: 540 },
    deviceScaleFactor: 2
  });
  const page = await ctx.newPage();

  const files = fs.readdirSync(SD).filter(f => f.endsWith('.html')).sort();
  for (const f of files) {
    await page.goto(`file://${SD}/${f}`);
    await page.waitForTimeout(200); // 폰트 로딩 대기
    await page.screenshot({ path: `${SD}/${f.replace('.html','.png')}` });
    console.log(`  rendered: ${f}`);
  }
  await browser.close();
}
```
- `waitForTimeout(200)`: 폰트 렌더링 안정화 대기
- HTML 파일명 순서 = 슬라이드 순서 (01-, 02-, ...)

## PPTX 조립

### 이미지 슬라이드 생성
```javascript
async function createPptx() {
  const pptx = new pptxgen();
  pptx.defineLayout({ name: 'WIDE', width: 10, height: 5.625 });
  pptx.layout = 'WIDE';

  const pngs = fs.readdirSync(SD).filter(f => f.endsWith('.png')).sort();
  for (const png of pngs) {
    const slide = pptx.addSlide();
    slide.addImage({
      path: `${SD}/${png}`,
      x: 0, y: 0, w: 10, h: 5.625
    });
    // 발표자 노트 추가
    const name = png.replace('.png', '');
    slide.addNotes(NOTES[name] || '');
  }

  const outPath = `${WS}/output_v${N}.pptx`;
  await pptx.writeFile({ fileName: outPath });
  // Downloads 폴더에도 복사
  fs.copyFileSync(outPath, path.join(process.env.HOME, 'Downloads', path.basename(outPath)));
}
```

## 실행 순서

### Step 1: 작업 디렉토리 준비
- 출력 폴더 생성: `mkdir -p ~/make_ai_files/ppt/{YYYYMMDD}_{제목}/`
- 의존성 확인: `[ -d ~/make_ai_files/node_modules ] || (cd ~/make_ai_files && npm install)`
- 빌드파일의 `require()` 경로를 `~/make_ai_files/node_modules/`로 설정

### Step 2: 슬라이드 기획
- 사용자와 슬라이드 구성 논의 (목차, 순서, 강조점)
- 슬라이드 목록 테이블 제시 (번호, 제목, 카테고리)

### Step 3: 빌드 파일 작성
- `build-v{N}.js` 단일 파일에 **모든 로직** 포함:
  - 배경 이미지 생성 (createAssets)
  - HTML 슬라이드 생성 (writeSlide)
  - Playwright 렌더링 (generateSlides)
  - 발표 스크립트 생성 (generateScript)
  - PPTX 조립 (createPptx)
- **외부 HTML 파일 없음** — 빌드 스크립트가 HTML을 직접 생성

### Step 4: 빌드 실행
```bash
cd {workspace} && node build-v{N}.js
```

### Step 5: 결과 확인
- `~/Downloads/{파일명}.pptx` 복사 확인
- 발표 스크립트 MD 생성 확인
- 슬라이드 수 확인

### Step 6: 피드백 반영
- 사용자가 수정 요청 시 → 해당 슬라이드 HTML만 수정 후 재빌드
- 전체 재빌드도 빠름 (~10초)

## 참고: 성공 사례

| 프로젝트 | 파일 | 슬라이드 수 | 비고 |
|---------|------|-----------|------|
| AI ElkHound v3 | `ideaworks/product/elkhound/docs/ppt-workspace/build-v3.js` | 19장 | 기술+비즈니스 혼합, 사내AI 포함 |

## 트러블슈팅

### 한글이 깨질 때
- `font-family`에 `Apple SD Gothic Neo`가 1순위인지 확인
- `letter-spacing: -0.01em`, `word-break: keep-all` 확인
- Playwright가 로컬 폰트를 사용하므로 macOS에서 실행해야 함

### 이미지가 흐릴 때
- `deviceScaleFactor: 2` 확인 (1이면 960x540 저해상도)
- PPTX 슬라이드 사이즈가 10x5.625인치인지 확인

### Playwright 에러
- `npx playwright install chromium` 으로 브라우저 설치
- macOS 권한: 시스템 설정 > 개인정보 > 자동화에서 터미널 허용

### 빌드 시간이 오래 걸릴 때
- 배경 이미지가 이미 있으면 스킵하는 로직 확인 (`!fs.existsSync`)
- Playwright `waitForTimeout`을 200ms 이하로 유지
- 보통 19슬라이드 기준 5~10초

## 주의사항

- **pptxgenjs 텍스트 API 사용 금지** — 반드시 이미지 삽입 방식만 사용
- **슬라이드 HTML은 960x540px 고정** — 다른 크기 사용 금지
- **macOS에서만 테스트됨** — Linux/Windows에서는 폰트가 다를 수 있음
- **빌드파일은 단일 .js** — 여러 파일로 분리하지 않음 (한 파일에서 전체 파이프라인)
