"""초기 게시판 시드 데이터. 글로벌 게시판만 시드 (팀 게시판은 Team 생성 시 자동 생성)."""

from sqlalchemy.orm import Session
from app.models import Board, Post, Team


# 기본 글로벌 게시판 (팀별 게시판은 포함하지 않음)
BOARDS = [
    {
        "name": "공지게시판", "slug": "notice", "category": "global", "team": None,
        "icon": "📢", "sort_order": 90,
        "description": "전체 팀 공지사항",
    },
    {
        "name": "자유게시판", "slug": "free", "category": "global", "team": None,
        "icon": "🎉", "sort_order": 91,
        "description": "수다, 아이디어, 고민, 아무말 대잔치",
    },
    {
        "name": "요청 게시판", "slug": "request", "category": "global", "team": None,
        "icon": "📬", "sort_order": 92,
        "description": "기능추가, 아이디어, 버그제보, 개선요청을 자유롭게 남겨주세요",
        "allowed_tags": "기능추가,아이디어,버그제보,개선요청",
    },
]

FIRST_POSTS = {
    "notice": {
        "title": "공지게시판 이용 안내",
        "author": "system",
        "is_pinned": True,
        "prefix": "[전체]",
        "content": """이 게시판은 전체 팀에 영향을 미치는 **중요 소식**을 공유하는 공간입니다.

## 머릿말 종류
- **[전체]** — 모든 팀 공통 공지
- **[긴급]** — 긴급 공지

## 작성 규칙
- 긴급 공지는 제목에 [긴급] 추가
- 일정 공지는 시간/날짜 명확히
- 액션 아이템은 체크리스트로 정리

정보를 투명하게 공유해요!""",
    },
    "free": {
        "title": "자유게시판 오픈! 뭐든 환영입니다",
        "author": "system",
        "is_pinned": True,
        "content": """여러분 환영합니다!

업무와 상관없이 **자유롭게 이야기하는 공간**입니다.
기술 고민, 일상 이야기, 새로운 아이디어... 뭐든 좋아요!

## 게시판 문화
1. **존중**: 모든 의견을 존중합니다
2. **응원**: 격려 댓글 대환영
3. **유머**: 밈, 개그 OK
4. **솔직**: 고충 토로도 괜찮아요

아무말 대잔치 시작!""",
    },
    "request": {
        "title": "요청 게시판 오픈",
        "author": "system",
        "is_pinned": True,
        "content": """이 게시판은 **어느 팀에든 자유롭게 요청할 수 있는 공간**입니다.

## 어떻게 쓰나요?

1. **머릿말**: 어느 팀에 요청하는지 선택
2. **태그**: 요청 종류 선택 (기능추가, 아이디어, 버그제보, 개선요청)
3. **제목 + 내용** 작성

## 팀들이 확인하고 답변드립니다

요청이 들어오면 해당 팀이 댓글로 처리 여부와 일정을 알려드립니다.
부담 없이 올려주세요!""",
    },
}


def seed_data(db: Session):
    """멱등성 보장: slug 기준으로 이미 존재하면 스킵."""
    for board_data in BOARDS:
        existing = db.query(Board).filter(Board.slug == board_data["slug"]).first()
        if existing:
            continue
        board = Board(**board_data)
        db.add(board)
        db.flush()

        post_data = FIRST_POSTS.get(board_data["slug"])
        if post_data:
            post = Post(
                board_id=board.id,
                title=post_data["title"],
                content=post_data["content"],
                author=post_data["author"],
                is_pinned=post_data.get("is_pinned", False),
                prefix=post_data.get("prefix"),
            )
            db.add(post)

    db.commit()

    # 글로벌 게시판의 allowed_prefixes를 DB의 팀 목록 기반으로 업데이트
    from app.crud import _update_global_board_prefixes
    _update_global_board_prefixes(db)
