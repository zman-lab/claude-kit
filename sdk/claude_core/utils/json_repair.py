"""불완전 JSON 응답 복구 유틸리티.

AI 모델의 max_tokens 도달로 응답이 잘렸을 때
불완전한 JSON을 파싱 가능한 상태로 수리.

지원하는 복구:
  1. 닫히지 않은 문자열 → 따옴표 추가
  2. 닫히지 않은 배열/객체 → 대괄호/중괄호 추가
  3. 후행 쉼표 제거
  4. 코드 블록 래핑(```json ... ```) 제거
  5. 잘린 키-값 쌍 제거
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)


def repair_json(text: str) -> str | None:
    """불완전한 JSON 문자열을 수리하여 파싱 가능한 JSON 반환.

    Args:
        text: AI 응답 (JSON 또는 불완전 JSON)

    Returns:
        수리된 JSON 문자열. 수리 불가능하면 None.
    """
    if not text or not text.strip():
        return None

    # 1. 코드 블록 제거
    cleaned = _strip_code_block(text.strip())

    # 2. 이미 유효한 JSON인지 확인
    try:
        json.loads(cleaned)
        return cleaned
    except json.JSONDecodeError:
        pass

    # 3. 수리 시도
    repaired = _attempt_repair(cleaned)
    if repaired is not None:
        return repaired

    # 4. JSON 부분만 추출해서 재시도
    extracted = _extract_json_fragment(text)
    if extracted and extracted != cleaned:
        repaired = _attempt_repair(extracted)
        if repaired is not None:
            return repaired

    logger.debug("JSON 수리 실패: %s...", text[:100])
    return None


def parse_json_safe(text: str, default: object = None) -> object:
    """JSON 파싱 시도. 실패하면 repair 후 재시도. 그래도 실패하면 default 반환.

    Args:
        text: JSON 문자열
        default: 파싱 실패 시 반환값

    Returns:
        파싱된 객체 또는 default
    """
    if not text:
        return default

    # 직접 파싱
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass

    # 수리 후 파싱
    repaired = repair_json(text)
    if repaired is not None:
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass

    return default


def _strip_code_block(text: str) -> str:
    """마크다운 코드 블록 래핑 제거."""
    # ```json\n...\n``` 또는 ```\n...\n```
    m = re.match(r"^```(?:json)?\s*\n?(.*?)(?:\n?```)?$", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text


def _extract_json_fragment(text: str) -> str | None:
    """텍스트에서 JSON 객체/배열 시작점 찾기."""
    for i, ch in enumerate(text):
        if ch in "{[":
            return text[i:]
    return None


def _attempt_repair(text: str) -> str | None:
    """JSON 수리 시도."""
    working = text.rstrip()

    # 후행 쉼표 + 불완전한 키-값 제거
    working = _remove_trailing_incomplete(working)

    # 닫히지 않은 문자열 닫기
    working = _close_open_strings(working)

    # 후행 쉼표 정리
    working = _remove_trailing_commas(working)

    # 닫히지 않은 브래킷 닫기
    working = _close_brackets(working)

    try:
        json.loads(working)
        return working
    except json.JSONDecodeError:
        pass

    return None


def _close_open_strings(text: str) -> str:
    """닫히지 않은 문자열 리터럴 닫기."""
    in_string = False
    escape = False
    last_quote_pos = -1

    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            if in_string:
                in_string = False
            else:
                in_string = True
                last_quote_pos = i

    if in_string:
        # 마지막 열린 따옴표 이후 내용에서 줄바꿈 이전까지만 취하고 닫기
        after = text[last_quote_pos + 1 :]
        # 줄바꿈이 있으면 그 전까지만
        nl_pos = after.find("\n")
        if nl_pos >= 0:
            text = text[: last_quote_pos + 1 + nl_pos] + '"'
        else:
            text = text + '"'

    return text


def _remove_trailing_incomplete(text: str) -> str:
    """잘린 키-값 쌍 제거.

    예: '{"a": 1, "b": "val' → '{"a": 1'
        '{"a": 1, "b":' → '{"a": 1'
    """
    # 마지막 완전한 값 이후의 불완전한 부분 제거
    # 패턴: 쉼표 + 공백 + 불완전한 키 또는 값
    patterns = [
        # 쉼표 뒤에 키만 있고 값이 없는 경우
        r',\s*"[^"]*"\s*:\s*$',
        # 쉼표 뒤에 키 시작만 있는 경우
        r',\s*"[^"]*$',
        # 쉼표로 끝나는 경우
        r",\s*$",
    ]
    for pattern in patterns:
        text = re.sub(pattern, "", text)
    return text


def _remove_trailing_commas(text: str) -> str:
    """후행 쉼표 제거: [1, 2,] → [1, 2]"""
    # 객체/배열 닫기 직전의 쉼표
    text = re.sub(r",\s*([}\]])", r"\1", text)
    # 끝에 남은 쉼표
    text = re.sub(r",\s*$", "", text)
    return text


def _close_brackets(text: str) -> str:
    """닫히지 않은 브래킷 추가."""
    stack: list[str] = []
    in_string = False
    escape = False

    for ch in text:
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in "}]" and stack and stack[-1] == ch:
            stack.pop()

    # 역순으로 닫기
    return text + "".join(reversed(stack))
