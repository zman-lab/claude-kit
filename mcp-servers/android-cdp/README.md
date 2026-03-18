# Android CDP MCP Server

Android WebView 앱(Capacitor/Cordova 등)을 AI가 자동 테스트하기 위한 MCP 서버.

## 왜 필요한가

네이티브 앱은 `adb input tap`으로 UI 제어가 가능하지만, **WebView 앱에서는 안 먹힌다.** 이유:
- WebView 내부 좌표와 adb 좌표가 불일치 (상태바, DPR, 스크롤 오프셋)
- 동적 레이아웃/모달에서 좌표가 계속 변함
- React synthetic event가 adb 터치를 인식 안 하는 경우 있음

**Chrome DevTools Protocol(CDP)**로 WebView 내부 JS를 직접 실행하면 정확한 UI 제어가 가능하다. 이 MCP 서버는 adb + CDP를 도구로 래핑하여 Claude가 직접 호출한다.

## 삽질 방지 가이드 (반드시 읽을 것)

### 1. adb input tap 쓰지 마라

```
❌ adb shell input tap 360 400   → WebView에서 엉뚱한 곳 클릭되거나 무반응
✅ cdp_click("민사소송법")         → 텍스트로 정확히 찾아서 클릭
```

### 2. CDP WebSocket 연결 시 suppress_origin 필수

Chrome 145+ WebView가 Origin 헤더를 검증함. 없으면 **403 Forbidden**.

```python
# ❌ 이러면 403
ws = websocket.create_connection(ws_url)

# ✅ 이래야 됨
ws = websocket.create_connection(ws_url, suppress_origin=True)
```

### 3. CDP 연결 순서 (이 순서 안 지키면 안 됨)

```
1. WebView DevTools 소켓 찾기
   adb shell cat /proc/net/unix | grep webview_devtools_remote_
   → "webview_devtools_remote_12345" 형태

2. 포트 포워딩
   adb forward tcp:9222 localabstract:webview_devtools_remote_12345

3. 페이지 URL 가져오기
   curl http://localhost:9222/json
   → webSocketDebuggerUrl 추출

4. WebSocket 연결 (suppress_origin!)
   ws = websocket.create_connection(ws_url, suppress_origin=True)

5. JS 실행
   ws.send({"method": "Runtime.evaluate", "params": {"expression": "..."}})
```

### 4. React 앱 클릭 방법 (우선순위)

```javascript
// 방법 A: el.click() — 대부분 이것만으로 충분 (React 18 검증됨)
document.querySelectorAll('button').forEach(el => {
  if (el.textContent.includes('재생')) el.click();
});

// 방법 B: React __reactProps$ 직접 호출 (el.click() 안 먹힐 때)
const propsKey = Object.keys(el).find(k => k.startsWith('__reactProps$'));
el[propsKey].onClick({
  preventDefault: () => {}, stopPropagation: () => {},
  nativeEvent: new Event('click'), target: el, currentTarget: el
});

// 방법 C: Touch+Click 풀 시퀀스 (터치 전용 이벤트에 반응하는 경우)
el.dispatchEvent(new TouchEvent('touchstart', {bubbles: true, ...}));
el.dispatchEvent(new TouchEvent('touchend', {bubbles: true, ...}));
el.click();
```

### 5. 앱 재시작 시 PID 변경

앱을 force-stop → 재시작하면 WebView PID가 바뀜. `cdp_connect()`를 다시 호출해야 함. 자동으로 새 소켓을 찾아서 연결한다.

### 6. 무선 디버깅 끊김 방지

- 화면 잠금 → Wi-Fi 절전 → 연결 끊김
- **개발자 옵션 → "충전 중 화면 켜짐 유지" ON** 또는 충전기 연결
- 페어링 포트 ≠ 연결 포트 (매번 다름, 사용자에게 둘 다 물어야 함)

### 7. 프로덕션 빌드에서 console.log 안 나옴

Vite 프로덕션 빌드에서 `import.meta.env.DEV === false` → console 출력 안 됨. 대안:

```javascript
// CDP로 console 후킹 주입
window.__LOGS__ = [];
const orig = console.log;
console.log = function(...args) {
  window.__LOGS__.push(args.map(String).join(' '));
  orig.apply(console, args);
};

// 나중에 수집
JSON.stringify(window.__LOGS__)
```

## 도구 목록

### ADB 도구
| 도구 | 설명 |
|------|------|
| `adb_devices` | 연결된 기기 목록 |
| `adb_connect` | 무선 디버깅 연결 (pair + connect 한 번에) |
| `adb_install` | APK 설치 (clean 옵션으로 레거시 제거) |
| `adb_uninstall` | 앱 제거 |
| `adb_start_app` | 앱 시작 |
| `adb_stop_app` | 앱 강제 종료 |
| `adb_logcat_crash` | FATAL EXCEPTION 자동 수집 |
| `adb_screenshot` | 전체 화면 스크린샷 (네이티브) |
| `adb_clear_logcat` | logcat 클리어 |

### CDP 도구
| 도구 | 설명 |
|------|------|
| `cdp_connect` | WebView DevTools 자동 탐지 + 연결 |
| `cdp_click` | **텍스트로 요소 찾아 클릭** (좌표 불필요) |
| `cdp_eval` | JS 실행 + 결과 반환 |
| `cdp_screenshot` | WebView 내부 스크린샷 |
| `cdp_get_text` | 현재 화면 텍스트 요약 |

### 통합 도구
| 도구 | 설명 |
|------|------|
| `full_deploy` | 제거 → 설치 → 시작 → CDP 연결 원스텝 |
| `check_crash` | logcat + CDP 연결 상태로 크래시 감지 |

## 사용 시나리오 예시

### 크래시 디버깅

```
1. adb_connect(ip_port="10.77.76.239:39363")
2. full_deploy(apk_path="/path/to/app.apk")
3. cdp_click("민사소송법")        → 과목 선택
4. cdp_click("Case 01")           → 케이스 선택
5. cdp_screenshot()               → 화면 확인
6. check_crash()                  → 크래시 여부
7. adb_logcat_crash()             → Java 스택트레이스 수집
```

### 기능 테스트

```
1. full_deploy(apk_path="...")
2. cdp_click("민사소송법")
3. cdp_click("Case 01")
4. cdp_click("재생")              → TTS 재생
5. cdp_eval("document.querySelector('button').textContent")  → 상태 확인
6. cdp_click("2.0x")              → 배속 변경
7. cdp_screenshot()               → UI 확인
8. check_crash()
```

## 설정

### Claude Code .mcp.json

```json
{
  "mcpServers": {
    "android-cdp": {
      "command": "python3",
      "args": ["-m", "src.server"],
      "cwd": "/Users/nhn/zman-lab/claude-kit/mcp-servers/android-cdp",
      "env": {
        "ADB_DEVICE": "",
        "APP_PACKAGE": "com.your.app",
        "APP_ACTIVITY": "com.your.app/.MainActivity"
      }
    }
  }
}
```

### 환경변수

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `ADB_DEVICE` | 기기 주소 (빈 값이면 기본 기기) | `""` |
| `APP_PACKAGE` | 앱 패키지명 | `com.zmanlab.lawear` |
| `APP_ACTIVITY` | 앱 액티비티 | `{패키지명}/.MainActivity` |

### 의존성

```
mcp[cli] >= 1.0.0
websocket-client >= 1.6.0
```

둘 다 `pip install mcp[cli] websocket-client`로 설치. 시스템에 이미 있으면 별도 설치 불필요.
