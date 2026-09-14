"""Relevance policy for automatically discovered run videos."""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
import unicodedata

from .parser import ParsedRun, find_character_mentions


EDITORIAL_PATTERNS = (
    r"\b(?:guide|tutorial|skill\s*tree|build|showcase|tier\s*list|review|reaction|tips?)\b",
    r"\b(?:guia|tutorial|arvore\s+de\s+habilidades|build|lista\s+de\s+tier|analise|dicas?)\b",
    r"(?:가이드|공략|스킬\s*트리|티어\s*리스트|리뷰)",
    r"(?:คู่มือ|แนะนำสกิล|สกิลทรี|จัดอันดับ|รีวิว)",
)
MULTI_CHARACTER_PATTERNS = (
    r"\b(?:all|every)\s+(?:the\s+)?characters?\b",
    r"\b(?:todos?|cada)\s+(?:os\s+)?personagens?\b",
    r"\b(?:compilation|compilacao|marathon|maratona)\b",
    r"\b(?:1[0-9]|2[0-9]|3[0-9])\s*(?:characters?|chars?|personagens?)\b",
    r"(?:모든\s*캐릭터|전\s*캐릭터|캐릭터\s*(?:1[0-9]|2[0-9]|3[0-9])명)",
    r"(?:ทุกตัวละคร|ตัวละครทั้งหมด|(?:1[0-9]|2[0-9]|3[0-9])\s*ตัวละคร)",
)
NON_RUN_PATTERNS = (
    r"\b(?:new\s+)?(?:4\s*mp|skills?)\s+(?:showcase|preview|test(?:ing)?)\b",
    r"\b(?:skill|damage|dps)\s+(?:showcase|preview|test(?:ing)?)\b",
    r"\b(?:showcase|preview|training|practice|leveling|farming|farmando|upando)\b",
    r"\b(?:live\s*stream|livestream|stream\s+archive)\b",
    r"(?:스킬\s*(?:쇼케이스|테스트)|데미지\s*테스트|라이브\s*방송|파밍)",
    r"(?:โชว์สกิล|ทดสอบดาเมจ|ไลฟ์สด|ฟาร์ม)",
)
COOPERATIVE_PATTERNS = (
    r"\b(?:duo|trio|co[ -]?op|multiplayer|party\s+run)\b",
    r"\b(?:with|w/)\s+(?:my\s+)?(?:friends?|team(?:mates?)?)\b",
    r"\b(?:dupla|trio|cooperativo|com\s+amigos?)\b",
    r"(?:듀오|트리오|협동|파티\s*플레이)",
    r"(?:ดูโอ|ทรีโอ|เล่นกับเพื่อน|ปาร์ตี้)",
)
RUN_PATTERNS = (
    r"\b(?:speed\s*run|record|world\s*record|time\s*attack|solo|clear|run)\b",
    r"\b(?:recorde|corrida|tempo|solo|sem\s+pocoes)\b",
    r"(?:스피드런|타임어택|기록|솔로|클리어)",
    r"(?:สปีดรัน|ทำเวลา|สถิติ|โซโล|เคลียร์)",
)
CHAPTER_PATTERN = re.compile(r"^\s*(?:\d{1,2}:)?\d{1,2}:\d{2}\b")


def _plain(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value.casefold())
    plain = []
    for character in normalized:
        decomposed = unicodedata.normalize("NFD", character)
        plain.append(decomposed[0] if decomposed[0].isascii()
                     and decomposed[0].isalpha() else character)
    return "".join(plain)


def _matches(patterns: tuple[str, ...], value: str) -> bool:
    return any(re.search(pattern, value, re.IGNORECASE) for pattern in patterns)


def description_from_metadata(metadata: dict | str | None) -> str:
    """Read a YouTube description from videos, search, or playlist metadata."""
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except (TypeError, json.JSONDecodeError):
            return ""
    if not isinstance(metadata, dict):
        return ""
    snippet = metadata.get("snippet")
    return snippet.get("description", "") if isinstance(snippet, dict) else ""


@dataclass(frozen=True)
class RelevanceDecision:
    accepted: bool
    score: int
    reasons: tuple[str, ...]
    hard_reject: bool = False


def evaluate_video_relevance(title: str, description: str,
                             parsed: ParsedRun) -> RelevanceDecision:
    """Decide whether an automatically discovered video looks like one run.

    Strong negative evidence is exposed through ``hard_reject`` so an existing
    queue can be cleaned conservatively without discarding merely ambiguous rows.
    """
    normalized_title = _plain(title)
    normalized_description = _plain(description)
    reasons: list[str] = []

    if _matches(MULTI_CHARACTER_PATTERNS, normalized_title):
        return RelevanceDecision(False, -100, ("multi_character_title",), True)
    if _matches(NON_RUN_PATTERNS, normalized_title):
        return RelevanceDecision(False, -100, ("non_run_title",), True)
    if _matches(COOPERATIVE_PATTERNS, normalized_title):
        return RelevanceDecision(False, -100, ("cooperative_title",), True)
    if _matches(EDITORIAL_PATTERNS, normalized_title):
        return RelevanceDecision(False, -100, ("editorial_title",), True)
    # A ranking row represents one character. Two explicit character names are
    # therefore strong evidence when the title also joins them explicitly. The
    # conjunction guard avoids substring ambiguity in unsegmented Thai text.
    joins_names = bool(re.search(
        r"(?:\b(?:and|e|y)\b|[,&+/]|(?:와|과|및)|และ)", normalized_title,
        re.IGNORECASE,
    ))
    if joins_names and len(find_character_mentions(title)) >= 2:
        return RelevanceDecision(False, -100, ("multiple_named_characters",), True)

    chapter_lines = [line for line in description.splitlines()
                     if CHAPTER_PATTERN.search(line)]
    chapter_characters = find_character_mentions("\n".join(chapter_lines))
    if len(chapter_lines) >= 3 and len(chapter_characters) >= 3:
        return RelevanceDecision(False, -100, ("multi_character_chapters",), True)

    description_intro = _plain("\n".join(description.splitlines()[:5]))[:500]
    if (_matches(NON_RUN_PATTERNS, description_intro)
            and not _matches(RUN_PATTERNS, normalized_title)
            and parsed.time_ms is None):
        return RelevanceDecision(False, -80, ("non_run_description",), True)
    if (_matches(COOPERATIVE_PATTERNS, description_intro)
            and parsed.solo is not True):
        return RelevanceDecision(False, -80, ("cooperative_description",), True)
    if (_matches(EDITORIAL_PATTERNS, description_intro)
            and not _matches(RUN_PATTERNS, normalized_title)
            and parsed.time_ms is None):
        return RelevanceDecision(False, -80, ("editorial_description",), True)

    score = 0
    if parsed.character:
        score += 3
        reasons.append("character")
    else:
        reasons.append("missing_character")
    if parsed.category:
        score += 3
        reasons.append("dungeon")
    else:
        reasons.append("missing_dungeon")
    if parsed.floor is not None:
        score += 1
    if parsed.time_ms is not None:
        score += 3
        reasons.append("time_in_title")
    if _matches(RUN_PATTERNS, normalized_title):
        score += 2
        reasons.append("run_language")

    first_segment = re.split(r"\s*(?:\||\s[-–—]\s)\s*", title, maxsplit=1)[0]
    structured_character = parsed.character in find_character_mentions(first_segment)
    if structured_character and re.search(r"\||\s[-–—]\s", title):
        score += 2
        reasons.append("individual_title_structure")

    # Descriptions help positively only when they state run intent; generic tags
    # and character dumps cannot rescue a weak title.
    if _matches(RUN_PATTERNS, normalized_description[:1000]):
        score += 1
        reasons.append("run_description")

    has_identity = parsed.character is not None and parsed.category is not None
    has_run_evidence = any(reason in reasons for reason in (
        "time_in_title", "run_language", "individual_title_structure",
    ))
    if not has_run_evidence:
        reasons.append("missing_run_context")
    return RelevanceDecision(has_identity and has_run_evidence and score >= 8,
                             score, tuple(reasons))
