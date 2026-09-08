"""Deterministic title parser for Grand Chase Classic run videos."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re
import unicodedata


def _plain(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return " ".join("".join(c for c in normalized if not unicodedata.combining(c)).split())


CHARACTER_ALIASES = {
    "elesis": "Elesis", "lire": "Lire", "arme": "Arme", "lass": "Lass",
    "ryan": "Ryan", "ronan": "Ronan", "amy": "Amy", "jin": "Jin",
    "sieghart": "Sieghart", "mari": "Mari", "dio": "Dio",
    "zero": "Zero", "ley": "Ley/Rey", "rey": "Ley/Rey",
    "rufus": "Rufus/Lupus", "lupus": "Rufus/Lupus",
    "rin": "Rin/Lin", "lin": "Rin/Lin", "asin": "Asin", "lime": "Lime/Holy",
    "holy": "Lime/Holy", "edel": "Edel", "veigas": "Veigas", "uno": "Uno",
    "decanee": "Decanee", "decane": "Decanee", "kallia": "Kallia", "ai": "Ai", "iris": "Iris",
    "azin": "Asin",
    "ereb": "Ereb",
}

CATEGORY_ALIASES = {
    "void invasion": "void_invasion", "vazio invasao": "void_invasion",
    "void taint": "void_taint", "vazio contaminacao": "void_taint",
    "void nightmare": "void_nightmare", "vazio pesadelo": "void_nightmare",
    "void apocalypse": "void_apocalypse", "vazio apocalipse": "void_apocalypse",
    "tower of disappearance": "tower_of_disappearance",
    "torre do desaparecimento": "tower_of_disappearance",
    "duel 4": "duel_4", "duelo 4": "duel_4",
    "loj unlimited": "loj_unlimited", "land of judgment unlimited": "loj_unlimited",
    "terra do julgamento ilimitada": "loj_unlimited",
}

TIME_PATTERNS = (
    re.compile(r"(?<!\d)(\d{1,2})\s*[':]\s*(\d{2})(?:[.,](\d{1,3}))?(?!\d)"),
    re.compile(r"(?<!\d)(\d{1,2})\s*m(?:in)?\s*(\d{1,2})\s*s(?:ec)?(?:\s*(\d{1,3})\s*ms)?", re.I),
)


@dataclass(frozen=True)
class ParsedRun:
    title: str
    character: str | None
    category: str | None
    floor: int | None
    time_ms: int | None
    solo: bool | None
    no_potions: bool | None
    no_quotes: bool | None
    confidence: float
    status: str
    missing_fields: tuple[str, ...]

    def to_dict(self) -> dict:
        value = asdict(self)
        value["missing_fields"] = list(self.missing_fields)
        return value


def _match_alias(text: str, aliases: dict[str, str]) -> str | None:
    matches = [(alias, canonical) for alias, canonical in aliases.items()
               if re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text)]
    if not matches:
        return None
    return max(matches, key=lambda item: len(item[0]))[1]


def _extract_time(title: str) -> int | None:
    for pattern in TIME_PATTERNS:
        match = pattern.search(title)
        if match:
            minutes, seconds = int(match.group(1)), int(match.group(2))
            fraction = match.group(3)
            if seconds >= 60:
                continue
            millis = 0 if not fraction else int(fraction.ljust(3, "0")[:3])
            return (minutes * 60 + seconds) * 1000 + millis
    return None


def parse_title(title: str) -> ParsedRun:
    text = _plain(title)
    words = " ".join(re.sub(r"[^\w]+", " ", text).split())
    character = _match_alias(words, CHARACTER_ALIASES)
    category = _match_alias(words, CATEGORY_ALIASES)
    floor_match = re.search(r"(?<!\d)([1-9])\s*(?:f|andar)(?!\w)", words)
    floor = int(floor_match.group(1)) if floor_match else None
    time_ms = _extract_time(text)
    solo = True if re.search(r"(?<!\w)solo(?!\w)", text) else None
    no_potions = True if re.search(r"sem\s+pocoes|no\s+pot(?:ion)?s?", text) else None
    no_quotes = True if re.search(r"sem\s+citacoes|no\s+quotes?", text) else None

    required = {"character": character, "category": category, "floor": floor, "time": time_ms}
    missing = tuple(key for key, value in required.items() if value is None)
    score = sum((0.30 if character else 0, 0.30 if category else 0,
                 0.10 if floor else 0, 0.25 if time_ms is not None else 0,
                 0.05 if any(flag is True for flag in (solo, no_potions, no_quotes)) else 0))
    if character and category and floor and time_ms is not None:
        status = "ready_for_review"
    elif character and category and floor:
        status = "time_required"
    else:
        status = "classification_required"
    return ParsedRun(title, character, category, floor, time_ms, solo, no_potions,
                     no_quotes, round(score, 2), status, missing)
