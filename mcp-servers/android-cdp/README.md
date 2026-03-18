# Android CDP MCP Server

Android WebView 앱(Capacitor/Cordova 등)을 AI가 자동 테스트하기 위한 MCP 서버.

## 왜 필요한가

- `adb input tap`은 WebView에서 좌표 불일치로 **안 먹힘**
- **Chrome DevTools Protocol(CDP)**로 WebView 내부 JS를 실행해야 정확한 UI 제어 가능
- 이 MCP 서버는 adb + CDP를 도구로 래핑하여 Claude가 직접 호출

## 도구 목록

### ADB 도구
| 도구 | 설명 |
|------|------|
| `adb_devices` | 연결된 기기 목록 |
| `adb_connect` | 무선 디버깅 연결 (pair + connect) |
| `adb_install` | APK 설치 |
| `adb_uninstall` | 앱 제거 |
| `adb_start_app` | 앱 시작 |
| `adb_stop_app` | 앱 종료 |
| `adb_logcat_crash` | FATAL EXCEPTION 수집 |
| `adb_screenshot` | 전체 화면 스크린샷 (네이티브) |

### CDP 도구
| 도구 | 설명 |
|------|------|
| `cdp_connect` | WebView DevTools 연결 |
| `cdp_click` | 텍스트로 요소 찾아 클릭 |
| `cdp_eval` | JS 실행 + 결과 반환 |
| `cdp_screenshot` | WebView 내부 스크린샷 |
| `cdp_get_text` | 현재 화면 텍스트 요약 |

### 통합 도구
| 도구 | 설명 |
|------|------|
| `full_deploy` | 빌드 → 설치 → 실행 → CDP 연결 |
| `check_crash` | logcat + CDP 연결 상태로 크래시 감지 |

## 설치

```bash
cd mcp-servers/android-cdp
pip install -e .
```

## Claude Code 설정

```json
// settings.json
{
  "mcpServers": {
    "android-cdp": {
      "command": "python3",
      "args": ["-m", "src.server"],
      "cwd": "~/zman-lab/claude-kit/mcp-servers/android-cdp"
    }
  }
}
```

## 주의사항

- PC와 기기가 **같은 Wi-Fi** 필요 (무선 디버깅)
- CDP 연결 시 `suppress_origin=True` 필수 (Chrome 145+ WebView)
- 앱 재시작 시 PID 변경 → `cdp_connect` 다시 호출
- 화면 잠금 시 무선 디버깅 끊김 → "충전 중 화면 켜짐 유지" 설정 권장
