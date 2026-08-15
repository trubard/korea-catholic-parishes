#!/usr/bin/env python3
"""미사시간 수집 공통 모듈 — 스키마, 시간 파싱, 교구 어댑터 인터페이스.

각 교구는 dioceses/ 아래에 MassAdapter 를 구현하고, collect(session) 에서
아래 형태의 본당 미사 레코드 리스트를 반환한다:

    {
      "parish_name": "노형 삼위일체",     # 소스에서 얻은 본당명(조인용)
      "diocese": "제주교구",
      "phone": "064-748-1004" 또는 None,   # 있으면 조인 1차 키
      "source_url": "https://...",
      "mass": {                            # normalize_mass() 참고
        "weekday": {"mon": [...], "tue": [...], ...},
        "saturday": [ {"time": "19:00", "note": "특전"} ],
        "sunday":   [ {"time": "11:00", "note": "교중"} ],
        "special":  [ ... ],
        "raw": "원문 텍스트"
      }
    }

미사 항목(time entry) 필드:
    time        "HH:MM"
    note        분류하지 못한 나머지 텍스트(있으면)
    audience[]  대상 — 어린이·청년·주일학교 …
    kind[]      전례 성격 — 교중·특전·신심·위령 …
    type[]      audience+kind 합친 하위호환 값
    feast       그날의 축일 이름. ⚠️ **수집일 한정 관측값**: 성당 홈페이지는
                축일 주간에만 안내를 띄우므로, 이 필드는 "수집일이 축일이었을 때
                그날 무슨 미사가 있었나" 만 담는다. "이 성당의 축일 미사가 언제인가"
                를 답하지 못한다(다음 해엔 비어 있을 수 있음). 소비 쪽은 축일 판정을
                이 필드에 의존하지 말 것. (docs/09 §1)
    seasonal    계절별 대안 시각. 예: {"winter": "07:00"} — 같은 미사의 다른 시각.
    place       공소(본당이 아닌 건물). 이름이면 "X공소", 이름 미상이면 true.
                좌표·주소는 본당 것이므로 이 값이 있으면 본당 미사로 표시하면 안 된다.
    recurrence  주기 조건 {weeks, weeks_exclude, months, season}
"""
from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri")
_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")

# --- 주기 조건(recurrence) 파싱 ---
_ORD = {"첫": 1, "둘": 2, "셋": 3, "넷": 4, "다섯": 5}
_ORD_RE = re.compile(r"(첫|둘|셋|넷|다섯)째?\s*주")
_WEEK_EXCLUDE_RE = re.compile(r"주\s*(?:에는\s*)?제외")
_MONTH_EX_RE = re.compile(r"([\d,\s·~\-]+)\s*월\s*(?:에는\s*)?제외")
_MONTH_RE = re.compile(r"([\d,\s·~\-]+)\s*월")


def _parse_months(seg: str) -> list[int]:
    months: set[int] = set()
    for part in re.split(r"[,\s·]+", seg.replace("·", ",").strip()):
        if not part:
            continue
        rng = re.match(r"(\d+)\s*[-~]\s*(\d+)$", part)
        if rng:
            months.update(range(int(rng.group(1)), int(rng.group(2)) + 1))
        elif part.isdigit():
            months.add(int(part))
    return sorted(m for m in months if 1 <= m <= 12)


def parse_recurrence(note: str | None) -> dict | None:
    """미사 note 에서 주기 조건을 추출. 조건 없으면 None(=매주 정규).

    weeks / weeks_exclude: 해당 주차에만 / 해당 주차 제외 (1=첫째, -1=마지막)
    months / months_exclude: 해당 월에만 / 해당 월 제외
    season: 'summer'(하절기) / 'winter'(동절기)
    """
    if not note:
        return None
    weeks: set = set()
    for m in _ORD_RE.finditer(note):
        weeks.add(_ORD[m.group(1)])
    if re.search(r"첫\s*주(?!\s*보)", note):  # '첫 주'(주보 제외)
        weeks.add(1)
    if re.search(r"첫\s*[월화수목금토일]요일", note):  # '매월 첫 목요일' 등
        weeks.add(1)
    if "홀수" in note:
        weeks.update({1, 3, 5})
    if "짝수" in note:
        weeks.update({2, 4})
    if re.search(r"(마지막|말)\s*주", note):
        weeks.add(-1)

    rec: dict = {}
    if weeks:
        key = "weeks_exclude" if _WEEK_EXCLUDE_RE.search(note) else "weeks"
        rec[key] = sorted(weeks)

    mex = _MONTH_EX_RE.search(note)
    if mex:
        months = _parse_months(mex.group(1))
        if months:
            rec["months_exclude"] = months
    else:
        mon = _MONTH_RE.search(note)
        if mon:
            months = _parse_months(mon.group(1))
            if months:
                rec["months"] = months

    if "하절기" in note or "여름" in note:
        rec["season"] = "summer"
    elif "동절기" in note or "겨울" in note:
        rec["season"] = "winter"

    if not rec:
        return None
    rec["raw"] = note
    return rec


# --- 미사 성격(type) 분류 ---
# 두 축으로 나뉜다: 대상(audience, 누가) / 전례성격(kind, 어떤 미사).
# 긴 것 우선(초중고 > 중고등부 > 학생 등 부분일치 충돌 방지).
_AUDIENCE = (
    "유아", "어린이", "초중고", "중고등부", "중고등", "중고생", "중고", "초등부",
    "유치부", "주일학교", "학생", "청소년", "대학생", "청년", "가족", "가정",
    "장년", "군인", "외국인", "영어", "베트남", "필리핀", "중국어", "수화", "장애",
)
_KIND = (
    "교중", "새벽", "성시간", "특전", "신심", "위령", "연도", "봉헌",
)
_TYPE_KEYWORDS = _AUDIENCE + _KIND   # type = audience + kind (하위호환)


def _dedupe_subset(found: list[str]) -> list[str]:
    """부분집합 제거: '중고등'이 '중고등부'와 함께면 '중고등' 버림."""
    return [t for t in found if not any(t != o and t in o for o in found)]


def parse_audience_kind(note: str | None) -> tuple[list[str], list[str]]:
    """note 를 (대상, 전례성격) 두 목록으로. 예: '어린이 교중' -> (['어린이'],['교중'])."""
    if not note:
        return [], []
    aud = _dedupe_subset([t for t in _AUDIENCE if t in note])
    kind = _dedupe_subset([t for t in _KIND if t in note])
    return aud, kind


def parse_type(note: str | None) -> list[str] | None:
    """note 에서 미사 성격/대상을 분류(대상+성격 합친 하위호환 값)."""
    if not note:
        return None
    aud, kind = parse_audience_kind(note)
    found = aud + kind
    return found or None


# --- 계절 대안시각(seasonal) ---
# '(동.7)' / '(하.19:30)' / '동절기 07:00' 등 — 같은 미사의 계절별 다른 시각.
_SEASON_TIME_RE = re.compile(r"(동절기|하절기|동|하|여름|겨울)\s*[.·]?\s*(\d{1,2}:\d{2})")


def parse_seasonal(note: str | None) -> dict | None:
    """note 에서 계절별 대안시각을 뽑는다. 예: '(동.07:00)' -> {'winter':'07:00'}."""
    if not note:
        return None
    out: dict = {}
    for m in _SEASON_TIME_RE.finditer(note):
        tag = m.group(1)
        key = "winter" if tag in ("동", "동절기", "겨울") else "summer"
        out.setdefault(key, m.group(2))
    return out or None


# --- 장소(place) — 공소 미사(본당이 아닌 건물)  ---
# '노송공소' · '임진강 공소' 등 이름을 뽑는다. 이름을 못 뽑아도 공소면 True.
_PLACE_RE = re.compile(r"([가-힣][가-힣0-9·]{0,8}(?:\s[가-힣0-9·]{1,6})?)\s*공소")


def parse_place(note: str | None):
    """note 에서 공소(비본당 장소)를 판별. 이름이면 'X공소', 이름없으면 True, 아니면 None."""
    if not note or "공소" not in note:
        return None
    m = _PLACE_RE.search(note)
    if m and m.group(1).strip():
        return re.sub(r"\s+", " ", m.group(0)).strip()
    return True   # 공소이나 이름 미상('공소미사'·'공소:넷째주일' 등)


# --- 축일(feast) 추출 ---
# '성모 승천 대축일', '주님 성탄 대축일' 등 '대축일'로 끝나는 어구. '성천'(오타) 허용.
_FEAST_RE = re.compile(r"([가-힣][가-힣\s·]{1,20}?(?:대축일|의 주일))")


def parse_feast(note: str | None) -> str | None:
    """note 에서 축일/대축일 이름을 뽑는다. 없으면 None."""
    if not note:
        return None
    m = _FEAST_RE.search(note)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    return None


# 고정일 축일 → 'MM-DD'. 이동축일(부활·성체성혈·성령강림)은 해마다 날짜가 달라 제외.
# 축일명은 표기가 흔들리므로(성모승천/성모 승천) 공백 제거 후 부분일치로 본다.
_FIXED_FEASTS = (
    ("성모승천", "08-15"), ("주님성탄", "12-25"), ("성탄", "12-25"),
    ("원죄없이", "12-08"), ("무염시태", "12-08"), ("모든성인", "11-01"),
    ("천주의성모", "01-01"), ("주님공현", "01-06"), ("주님봉헌", "02-02"),
    ("주님세례", None), ("김대건", "07-05"), ("베드로와바오로", "06-29"),
    ("성모의탄생", "09-08"), ("한국순교자", "09-20"), ("대천사", "09-29"),
)


def resolve_feast_date(feast: str | None) -> str | None:
    """축일명 -> 고정 'MM-DD'. 이동축일·미상은 None."""
    if not feast:
        return None
    key = re.sub(r"\s+", "", feast)
    for pat, date in _FIXED_FEASTS:
        if pat in key and date:
            return date
    return None


# --- 시각 토큰 파싱 ---
_HHMM_RE = re.compile(r"\d{1,2}:\d{2}")
# 시각으로 볼 홑숫자: 앞이 숫자/콜론/한글이 아니고, 뒤에 시각이 아닌 단위가 오지 않는 1~2자리.
_BARE_HOUR_RE = re.compile(
    r"(?<![:\d가-힣])(\d{1,2})(?!\s*[:\d시분월일주년명호원군세절]|\s*번|\s*구역|\s*가정)")
# 부정 표현(그 시각 미사가 없다는 안내) — 붙은 시각은 넣지 않는다.
_NEG_RE = re.compile(r"없[음다]|없습니다|쉽니다|안\s*합니다|중단|취소")


def _bare_hours_to_hhmm(text: str) -> str:
    """구분자 사이 홑숫자를 HH:MM 으로(0~24). '11월'·'2군단'·'18호' 등은 제외."""
    def repl(m):
        h = int(m.group(1))
        return f"{h:02d}:00" if 0 <= h <= 24 else m.group(0)
    return _BARE_HOUR_RE.sub(repl, text)


def _paren_depth(text: str) -> list[int]:
    """각 문자 위치의 괄호 깊이(여는 괄호 자리는 0, 그 안쪽은 1+)."""
    depth, out = 0, []
    for ch in text:
        if ch in "([{":
            out.append(depth)
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
            out.append(depth)
        else:
            out.append(depth)
    return out


def get_soup(session: requests.Session, url: str, encoding: str = "utf-8",
             headers: dict | None = None) -> BeautifulSoup:
    r = session.get(url, timeout=40, headers=headers)
    r.raise_for_status()
    return BeautifulSoup(r.content.decode(encoding, errors="replace"), "html.parser")


def parse_time_cell(text: str) -> list[dict]:
    """'6/8:30/10:30/17/19' 같은 구간 문자열 -> 시간별 {time, note, type?, feast?, recurrence?}.

    - 한글시각(10시·오후5시)·홑숫자(6·17)·HH:MM 을 모두 시각으로 인식한다.
    - 괄호/대괄호 안의 시각·쉼표는 하나의 note 로 묶고, 괄호 밖 시각만 미사로 만든다.
    - '없음/쉽니다' 등 부정 표현이 붙은 시각은 넣지 않는다(유령 미사 방지).
    각 시각의 note 는 다음 시각 전까지의 텍스트(대상/비고).
    """
    if not text:
        return []
    text = re.sub(r"\s+", " ", text).strip()
    text = korean_to_hhmm(text)          # 오후5시 -> 17:00, 10시30분 -> 10:30
    text = _bare_hours_to_hhmm(text)     # /17/ -> /17:00/
    cell_feast = parse_feast(text)       # 셀 전체 축일(시각 앞에 오는 경우 대비)
    depth = _paren_depth(text)
    # 괄호 밖(depth 0) HH:MM 만 미사 앵커로. 단 셀 전체가 괄호면(밖 앵커 0개)
    # 괄호 안 시각을 쓴다(예: '(성모승천대축일 09시 주일학교)').
    all_hhmm = list(_HHMM_RE.finditer(text))
    anchors = [m for m in all_hhmm if depth[m.start()] == 0] or all_hhmm
    if not anchors:
        return []
    entries = []
    for i, m in enumerate(anchors):
        hh = int(m.group(0).split(":")[0])
        if hh > 24:                      # 잘못 인식된 숫자(예: '25')
            continue
        time = f"{hh % 24:02d}:{m.group(0).split(':')[1]}"
        end = anchors[i + 1].start() if i + 1 < len(anchors) else len(text)
        note = text[m.end():end].strip(" ,/·-*")
        # 계절 조건 등 구간 전체 단서(*...)는 note 에서 떼어 recurrence 로만 반영.
        # 표시용 note 는 감싼 괄호를 정리.
        note_core = re.split(r"\*", note)[0].strip(" ,/·-()[]") or None
        if note and _NEG_RE.search(note):    # 그 시각 미사가 없다는 안내
            continue
        entry = {"time": time, "note": note_core}
        aud, kind = parse_audience_kind(note)
        if aud:
            entry["audience"] = aud
        if kind:
            entry["kind"] = kind
        if aud or kind:
            entry["type"] = aud + kind      # 하위호환(합친 값)
        feast = parse_feast(note) or cell_feast
        if feast:
            entry["feast"] = feast
        place = parse_place(note)
        if place:
            entry["place"] = place       # 공소(비본당) — 본당 미사로 오인 방지
        seasonal = parse_seasonal(note)
        if seasonal:
            entry["seasonal"] = seasonal
        rec = parse_recurrence(note)
        if rec:
            # 계절 대안시각(seasonal)이 잡혔으면 recurrence.season 중복 제거(이중화 정리).
            # seasonal 은 '시각이 바뀐다', recurrence.season 은 '그 계절에만' 이라 의미가 다르다.
            if seasonal and rec.get("season"):
                rec = {k: v for k, v in rec.items() if k != "season"}
            if len(rec) > 1:             # raw 외에 실제 조건이 남아 있을 때만
                entry["recurrence"] = rec
        entries.append(entry)
    return entries


_DAY_KEY = {"월": "mon", "화": "tue", "수": "wed", "목": "thu", "금": "fri",
            "토": "saturday", "주일": "sunday"}
_KTIME_RE = re.compile(r"(오전|오후)?\s*(\d{1,2})\s*시\s*(?:(\d{1,2})\s*분)?")


def korean_to_hhmm(text: str) -> str:
    """'오전 6시 30분', '오후 7시', '10시30분' 등 한글 시간을 'HH:MM' 으로 치환.

    오전/오후가 없으면 그대로(24시간 가정). 나머지 텍스트(비고/대상)는 보존.
    """
    if not text:
        return ""

    def _colon(m):  # '오후 7:30' 같은 오전/오후 + HH:MM
        ap, hh, mm = m.group(1), int(m.group(2)), m.group(3)
        if ap == "오후" and hh < 12:
            hh += 12
        elif ap == "오전" and hh == 12:
            hh = 0
        return f" {hh:02d}:{mm} "

    text = re.sub(r"(오전|오후)\s*(\d{1,2}):(\d{2})", _colon, text)

    def repl(m):  # '오전 6시 30분' 같은 N시 M분
        ap, hh, mm = m.group(1), int(m.group(2)), m.group(3)
        if ap == "오후" and hh < 12:
            hh += 12
        elif ap == "오전" and hh == 12:
            hh = 0
        return f" {hh:02d}:{mm or '00':0>2} "

    return _KTIME_RE.sub(repl, text)


def split_day_labeled(text: str) -> dict:
    """'월 10:00 화 19:30 ... 토 ... 주일 ...' 평문 -> {mon: '10:00', ...}.

    앞의 날짜 헤더('미사시간 안내 ( 2026년 07월 ... )')는 '요일+시간' 첫 위치부터
    잘라 무시한다. 시간이 없는 요일은 제외.
    """
    if not text:
        return {}
    text = re.sub(r"\s+", " ", text)
    m = re.search(r"(주일|[월화수목금토])\s*\d{1,2}:\d{2}", text)
    seg = text[m.start():] if m else text
    poss = []
    for lb in _DAY_KEY:
        poss.extend((mm.start(), lb) for mm in re.finditer(lb, seg))
    poss.sort()
    result: dict = {}
    for i, (pos, lb) in enumerate(poss):
        end = poss[i + 1][0] if i + 1 < len(poss) else len(seg)
        val = seg[pos + len(lb):end].strip(" :,")
        if _TIME_RE.search(val):
            result.setdefault(_DAY_KEY[lb], val)
    return result


def normalize_mass(weekday_cells: dict, saturday: str, sunday: str,
                   special: list | None = None, raw: str = "") -> dict:
    """요일별 셀 텍스트를 구조화된 mass 객체로. weekday_cells: {mon: text, ...}."""
    return {
        "weekday": {d: parse_time_cell(weekday_cells.get(d, "")) for d in WEEKDAYS},
        "saturday": parse_time_cell(saturday),
        "sunday": parse_time_cell(sunday),
        "special": special or [],
        "raw": raw.strip() or None,
    }


class MassAdapter:
    """교구별 미사시간 어댑터 베이스."""

    diocese: str = ""          # 예: "제주교구" — churches.json 의 diocese 와 일치해야 함

    def collect(self, session: requests.Session) -> list[dict]:
        raise NotImplementedError
