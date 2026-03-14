"""CLI 엔트리포인트 — argparse 기반."""
import argparse
from .server import serve


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="sysmon",
        description="On-demand system resource monitor with actionable insights.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind host (기본: 127.0.0.1, --token 지정 시 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=19090,
        help="Bind port (기본: 19090)",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="원격 접근용 인증 토큰 (지정 시 0.0.0.0 바인딩)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="브라우저 자동 열기 비활성화",
    )

    args = parser.parse_args()

    # 토큰 지정 시 외부 바인딩, 명시적 --host가 없으면 0.0.0.0
    host = args.host
    if args.token and args.host == "127.0.0.1":
        host = "0.0.0.0"

    serve(
        host=host,
        port=args.port,
        token=args.token,
        open_browser=not args.no_browser,
    )
