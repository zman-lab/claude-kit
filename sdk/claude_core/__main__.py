"""claude-core CLI 가이드 — python3 -m claude_core --help"""

GUIDE = """
=== claude-core SDK 가이드 ===

버전: 0.2.0
용도: Claude CLI 데몬 관리 + 메모리 시스템
의존성: aiosqlite>=0.19.0, pydantic>=2.0.0

━━━ 필수 환경 ━━━

1. Claude CLI 설치: npm install -g @anthropic-ai/claude-code
2. CLI 경로 확인: which claude (보통 /Users/nhn/.local/bin/claude)
3. CLI 로그인: claude auth login (최초 1회)

━━━ Quick Start ━━━

  from claude_core import (
      ClaudeDaemon, DaemonManager, DaemonPool,
      create_claude_config,
  )

  # Settings 객체 (DaemonSettings Protocol 준수)
  class MySettings:
      CLAUDE_CLI_PATH = "/Users/nhn/.local/bin/claude"
      CLAUDE_MODEL = "claude-sonnet-4-20250514"
      CLAUDE_MAX_TURNS = 0      # 0 = 무제한 (1이면 1턴 후 종료!)
      MCP_CONFIG_PATH = ""
      DAEMON_POOL_SIZE = 3

  settings = MySettings()
  config = create_claude_config(settings)

  manager = DaemonManager(max_instances=5)
  pool = DaemonPool(manager=manager, daemon_type="claude", pool_size=3)
  daemon = ClaudeDaemon(
      config=config, settings=settings, manager=manager, pool=pool
  )

  # 질문
  async for event in daemon.ask_stream("안녕하세요"):
      if event["type"] == "text":
          print(event["content"], end="")
      elif event["type"] == "done":
          break

  # 종료
  await pool.shutdown()
  await manager.shutdown_all()

━━━ ask_stream 이벤트 타입 ━━━

  text         — content: 텍스트 청크
  tool_use     — name, input: 도구 호출
  tool_result  — content: 도구 결과
  done         — total_cost, model: 완료
  error        — message: 에러

━━━ DaemonPool 상태 전이 ━━━

  IDLE -> (acquire) -> BUSY -> (release) -> CLEARING -> (/clear) -> IDLE
                        |                      |
                      (crash)              (timeout)
                        v                      v
                       DEAD  <--------------  DEAD
                        |
                    (replace)
                        v
                       IDLE

━━━ 에러 핸들링 ━━━

  from claude_core import DaemonError, DaemonTimeoutError, DaemonProcessError

  try:
      async for event in daemon.ask_stream("질문"):
          ...
  except DaemonTimeoutError:
      pass  # CLI 응답 타임아웃
  except DaemonProcessError:
      pass  # CLI 프로세스 crash (exit code, stderr 포함)
  except DaemonError:
      pass  # 기타 데몬 에러
  except RuntimeError as e:
      if "All pool slots are dead" in str(e):
          pass  # Pool 전체 슬롯 사망

━━━ 주요 export 목록 ━━━

  # Daemon
  ClaudeDaemon, DaemonManager, DaemonPool
  create_claude_config, create_memory_daemon_config, create_tool_daemon_config

  # Memory
  MemoryService, MemoryConfig, MemoryStorage

  # AI Provider
  AIProvider, DaemonProvider, DualAIProvider, CostTracker

  # Errors
  ClaudeCoreError, DaemonError, DaemonTimeoutError, DaemonProcessError
  AIProviderError, MemoryError

  # Utils
  repair_json, parse_json_safe

━━━ 트러블슈팅 ━━━

  "All pool slots are dead"
    1. which claude 로 CLI 경로 확인
    2. claude --version 으로 CLI 동작 확인
    3. CLAUDE_MAX_TURNS=0 확인 (1이면 1턴 후 종료)
    4. ~/.claude/settings.json 의 alwaysThinkingEnabled: true 면
       --verbose 플래그 필요 (create_claude_config에 자동 포함됨)

  "No module named 'claude_core'"
    pip3 install claude_core-*.whl --break-system-packages --force-reinstall
"""


def main():
    import sys
    if "--help" in sys.argv or "-h" in sys.argv or len(sys.argv) <= 1:
        print(GUIDE)
    else:
        print(f"알 수 없는 인자: {sys.argv[1:]}")
        print("사용법: python3 -m claude_core --help")


if __name__ == "__main__":
    main()
