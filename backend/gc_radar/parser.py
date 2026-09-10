"""Deterministic title parser for Grand Chase Classic run videos."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from html import unescape
import re
import unicodedata


def _plain(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", unescape(value).casefold())
    plain = []
    for character in normalized:
        decomposed = unicodedata.normalize("NFD", character)
        plain.append(decomposed[0] if decomposed[0].isascii() and decomposed[0].isalpha() else character)
    return " ".join("".join(plain).split())


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
    "엘리시스": "Elesis", "리르": "Lire", "아르메": "Arme", "라스": "Lass",
    "라이언": "Ryan", "로난": "Ronan", "에이미": "Amy", "진": "Jin",
    "지크하트": "Sieghart", "마리": "Mari", "디오": "Dio", "제로": "Zero",
    "레이": "Ley/Rey", "루퍼스": "Rufus/Lupus", "린": "Rin/Lin", "아신": "Asin",
    "라임": "Lime/Holy", "에델": "Edel", "베이가스": "Veigas", "우노": "Uno",
    "데카네": "Decanee", "칼리아": "Kallia", "아이": "Ai", "아이리스": "Iris",
    "에레브": "Ereb",
    "เอลิซิส": "Elesis", "ลีร์": "Lire", "อาร์เม": "Arme", "ลาส": "Lass",
    "ไรอัน": "Ryan", "โรแนน": "Ronan", "เอมี่": "Amy", "จิน": "Jin",
    "ซิกฮาร์ท": "Sieghart", "มารี": "Mari", "ดิโอ": "Dio", "ซีโร่": "Zero",
    "เลย์": "Ley/Rey", "ลูฟัส": "Rufus/Lupus", "ริน": "Rin/Lin", "อาซิน": "Asin",
    "ไลม์": "Lime/Holy", "เอเดล": "Edel", "เวกัส": "Veigas", "อูโน": "Uno",
    "เดคานี": "Decanee", "คัลเลีย": "Kallia", "ไอ": "Ai", "ไอริส": "Iris",
    "เอเรบ": "Ereb",
}

CATEGORY_ALIASES = {
    "void 1": "void_invasion", "vazio 1": "void_invasion",
    "void invasion": "void_invasion", "vazio invasao": "void_invasion",
    "void 2": "void_taint", "vazio 2": "void_taint",
    "void taint": "void_taint", "vazio contaminacao": "void_taint",
    "void 3": "void_nightmare", "vazio 3": "void_nightmare",
    "void nightmare": "void_nightmare", "vazio pesadelo": "void_nightmare",
    "void 4": "void_apocalypse", "vazio 4": "void_apocalypse",
    "void apocalypse": "void_apocalypse", "vazio apocalipse": "void_apocalypse",
    "tower of disappearance": "tower_of_disappearance",
    "torre do desaparecimento": "tower_of_disappearance",
    "infinity cloister stage 4": "duel_4",
    "duel 4": "duel_4", "duel lv 4": "duel_4", "duel lvl 4": "duel_4",
    "duelo 4": "duel_4", "duelo lv 4": "duel_4",
    "loj unlimited": "loj_unlimited", "land of judgment unlimited": "loj_unlimited",
    "terra do julgamento ilimitada": "loj_unlimited",
    "infinity cloister stage 3": "infinity_cloister_3",
    "land of judgement": "land_of_judgement", "land of judgment": "land_of_judgement",
    "renak s core champion": "renaks_core_champion",
    "great explosion of kounat": "great_explosion_of_kounat",
    "wizard s labyrinth stage 30": "wizards_labyrinth_30",
    "moonlight village": "moonlight_village", "temple of time": "temple_of_time",
    "sanctuary of divine beast master mode": "sanctuary_divine_beast_master",
    "sanctuary of divine beast master": "sanctuary_divine_beast_master",
    "hall of harmony master mode": "hall_of_harmony_master",
    "hall of harmony master": "hall_of_harmony_master",
    "chapel of eternity master": "chapel_of_eternity_master",
    "path shrouded in darkness master": "path_shrouded_darkness_master",
    "apocalypse vortex master": "apocalypse_vortex_master",
    "apocalypse vortex": "apocalypse_vortex_master",
    "berkas lair": "berkas_lair",
    "공허 침공": "void_invasion", "보이드 침공": "void_invasion",
    "공허 잠식": "void_taint", "보이드 잠식": "void_taint",
    "공허 악몽": "void_nightmare", "보이드 악몽": "void_nightmare",
    "공허 종말": "void_apocalypse", "보이드 아포칼립스": "void_apocalypse",
    "วอยด์ บุก": "void_invasion", "วอยด์ อินเวชัน": "void_invasion",
    "วอยด์ ปนเปื้อน": "void_taint", "วอยด์ เทนต์": "void_taint",
    "วอยด์ ฝันร้าย": "void_nightmare", "วอยด์ ไนต์แมร์": "void_nightmare",
    "วอยด์ วันสิ้นโลก": "void_apocalypse", "วอยด์ อะพอคคาลิปส์": "void_apocalypse",
}

NUMBERED_VOID_FLOORS = {
    "void 1": 3, "vazio 1": 3,
    "void 2": 3, "vazio 2": 3,
    "void 3": 4, "vazio 3": 4,
    "void 4": 3, "vazio 4": 3,
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
               if ((not alias.isascii() and alias in text)
                   or (alias.isascii() and re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text)))]
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
    seconds_only = re.search(r"(?<!\d)(\d{1,3})\s*s(?:ec(?:ond)?s?)?(?!\w)", title, re.I)
    if seconds_only:
        return int(seconds_only.group(1)) * 1000
    return None


def parse_title(title: str) -> ParsedRun:
    text = _plain(title)
    words = " ".join(re.sub(r"[^\w\u0E31-\u0E4E]+", " ", text).split())
    character = _match_alias(words, CHARACTER_ALIASES)
    category = _match_alias(words, CATEGORY_ALIASES)
    if "angry boss" in words and "archimedia" in words:
        category = "angry_boss_archimedia"
    elif "angry boss" in words and "alcubra" in words:
        category = "angry_boss_alcubra"
    floor_match = re.search(r"(?<!\d)([1-9])\s*(?:f|andar|층|ชั้น)(?!\w)", text)
    floor = int(floor_match.group(1)) if floor_match else None
    if floor is None:
        numbered_void = next((alias for alias in NUMBERED_VOID_FLOORS
                              if re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", words)), None)
        floor = NUMBERED_VOID_FLOORS.get(numbered_void) if numbered_void else None
    if floor is None and category in {
        "tower_of_disappearance", "duel_4", "loj_unlimited", "infinity_cloister_3",
        "land_of_judgement", "renaks_core_champion", "great_explosion_of_kounat",
        "wizards_labyrinth_30", "moonlight_village", "temple_of_time",
        "sanctuary_divine_beast_master", "hall_of_harmony_master",
        "chapel_of_eternity_master", "path_shrouded_darkness_master",
        "apocalypse_vortex_master", "berkas_lair", "angry_boss_archimedia",
        "angry_boss_alcubra",
    }:
        floor = 0
    time_ms = _extract_time(text)
    solo = True if re.search(r"(?<!\w)solo(?!\w)", text) else None
    no_potions = True if re.search(r"sem\s+pocoes|no\s+pot(?:ion)?s?", text) else None
    no_quotes = True if re.search(r"sem\s+citacoes|no\s+quotes?", text) else None

    required = {"character": character, "category": category, "floor": floor, "time": time_ms}
    missing = tuple(key for key, value in required.items() if value is None)
    score = sum((0.30 if character else 0, 0.30 if category else 0,
                 0.10 if floor is not None else 0, 0.25 if time_ms is not None else 0,
                 0.05 if any(flag is True for flag in (solo, no_potions, no_quotes)) else 0))
    if character and category and floor is not None and time_ms is not None:
        status = "ready_for_review"
    elif character and category and floor is not None:
        status = "time_required"
    else:
        status = "classification_required"
    return ParsedRun(title, character, category, floor, time_ms, solo, no_potions,
                     no_quotes, round(score, 2), status, missing)
