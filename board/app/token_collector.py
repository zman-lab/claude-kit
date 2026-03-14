"""Claude 토큰 사용량 수집기. ccusage CLI로 계정별 데이터를 수집하여 DB에 저장.

팀 매핑을 하드코딩하지 않고 환경변수 또는 DB에서 동적으로 조회한다.
"""

import json
import os
import subprocess
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import TokenUsage


def _get_team_keywords_from_db() -> list[tuple[str, str]]:
    """DB에서 활성 팀 목록을 조회하여 (keyword, team) 매핑 생성."""
    try:
        from app.database import SessionLocal
        from app.models import Team
        db = SessionLocal()
        try:
            teams = db.query(Team).filter(Team.is_active == True).order_by(Team.slug.desc()).all()
            # slug가 긴 순서대로 정렬 (긴 키워드 우선 매칭)
            return [(t.slug, t.slug) for t in teams]
        finally:
            db.close()
    except Exception:
        return []


def get_accounts() -> dict[str, str]:
    """계정 목록 반환. 환경변수 > 자동감지."""
    env = os.getenv("BOARD_CLAUDE_ACCOUNTS")
    if env:
        accounts = {}
        for item in env.split(","):
            parts = item.strip().split(":", 1)
            if len(parts) == 2:
                name, path = parts
                expanded = os.path.expanduser(path.strip())
                if os.path.isdir(expanded):
                    accounts[name.strip()] = expanded
        return accounts

    home = Path.home()
    defaults = {
        "1st": home / ".claude",
        "2nd": home / ".claude-2nd",
        "3rd": home / ".claude-3rd",
        "4th": home / ".claude-4th",
    }
    return {k: str(v) for k, v in defaults.items() if v.exists()}


def get_team_mapping() -> list[tuple[str, str]]:
    """팀 매핑 규칙. 환경변수 > DB > 빈 목록."""
    env = os.getenv("BOARD_TEAM_MAPPING")
    if env:
        mapping = []
        for item in env.split(","):
            parts = item.strip().split(":", 1)
            if len(parts) == 2:
                team, keyword = parts
                mapping.append((keyword.strip(), team.strip()))
        return mapping
    return _get_team_keywords_from_db()


def map_project_to_team(project_key: str, mapping: list[tuple[str, str]] | None = None) -> str:
    """프로젝트 키를 팀으로 매핑. 미매칭 시 'other'."""
    if mapping is None:
        mapping = get_team_mapping()
    for keyword, team in mapping:
        if keyword in project_key:
            return team
    return "other"


def collect_account(config_dir: str, since: str | None = None) -> dict | None:
    """ccusage 실행하여 특정 계정 데이터 수집."""
    cmd = ["ccusage", "daily", "-j", "-b", "-i"]
    if since:
        cmd.extend(["--since", since])
    env = os.environ.copy()
    # launchd 등 제한된 환경에서 PATH 보충
    path = env.get("PATH", "")
    for extra in ["/opt/homebrew/bin", "/usr/local/bin"]:
        if extra not in path:
            path = extra + ":" + path
    env["PATH"] = path
    default_claude = str(Path.home() / ".claude")
    if os.path.normpath(config_dir) != os.path.normpath(default_claude):
        env["CLAUDE_CONFIG_DIR"] = config_dir
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        return None


def upsert_usage(db: Session, account: str, project: str,
                 team: str, day: date, model: dict):
    """토큰 사용량 upsert."""
    from datetime import datetime
    day_dt = datetime(day.year, day.month, day.day)

    existing = db.query(TokenUsage).filter(
        TokenUsage.account == account,
        TokenUsage.date == day_dt,
        TokenUsage.project == project,
        TokenUsage.model_name == model["modelName"],
    ).first()

    vals = dict(
        input_tokens=model.get("inputTokens", 0),
        output_tokens=model.get("outputTokens", 0),
        cache_creation_tokens=model.get("cacheCreationTokens", 0),
        cache_read_tokens=model.get("cacheReadTokens", 0),
        total_tokens=sum(model.get(k, 0) for k in
                         ["inputTokens", "outputTokens",
                          "cacheCreationTokens", "cacheReadTokens"]),
        cost=model.get("cost", 0.0),
    )

    if existing:
        for k, v in vals.items():
            setattr(existing, k, v)
    else:
        db.add(TokenUsage(
            account=account, date=day_dt, project=project,
            team=team, model_name=model["modelName"], **vals
        ))


def collect_all(db: Session, since: str | None = None) -> dict:
    """전 계정 수집 + DB 저장. 결과 요약 반환."""
    if since is None:
        since = (date.today() - timedelta(days=7)).strftime("%Y%m%d")

    accounts = get_accounts()
    mapping = get_team_mapping()
    summary = {}

    for name, path in accounts.items():
        data = collect_account(path, since)
        if not data or "projects" not in data:
            summary[name] = {"status": "error", "records": 0}
            continue

        count = 0
        for proj_key, days in data["projects"].items():
            team = map_project_to_team(proj_key, mapping)
            for day_data in days:
                d = date.fromisoformat(day_data["date"])
                for model in day_data.get("modelBreakdowns", []):
                    upsert_usage(db, name, proj_key, team, d, model)
                    count += 1

        summary[name] = {"status": "ok", "records": count}

    db.commit()
    return summary
