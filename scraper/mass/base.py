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
# 긴 것 우선(초중고 > 중고등부 > 학생 등 부분일치 충돌 방지)
_TYPE_KEYWORDS = (
    "교중", "새벽", "유아", "어린이", "초중고", "중고등부", "학생",
    "청소년", "대학생", "청년", "가족", "가정", "장년", "성시간",
    "특전", "신심", "군인", "외국인", "영어",
)


def parse_type(note: str | None) -> list[str] | None:
    """note 에서 미사 성격/대상을 분류. 예: '청년, 학생' -> ['청년','학생']."""
    if not note:
        return None
    found = [t for t in _TYPE_KEYWORDS if t in note]
    # 중복/포함 정리: 다른 키워드의 부분집합이면 제거(예: '학생'이 '초중고'와 함께면 유지 OK)
    return found or None


def get_soup(session: requests.Session, url: str, encoding: str = "utf-8",
             headers: dict | None = None) -> BeautifulSoup:
    r = session.get(url, timeout=40, headers=headers)
    r.raise_for_status()
    return BeautifulSoup(r.content.decode(encoding, errors="replace"), "html.parser")


def parse_time_cell(text: str) -> list[dict]:
    """'06:30 09:00 11:00 교중 18:00 청년' -> 시간별 {time, note} 목록.

    각 HH:MM 토큰이 하나의 미사가 되고, 그 뒤(다음 시간 전까지)의 텍스트가 note(대상/비고).
    시간이 하나도 없으면 빈 목록.
    """
    if not text:
        return []
    text = re.sub(r"\s+", " ", text).strip()
    matches = list(_TIME_RE.finditer(text))
    if not matches:
        return []
    entries = []
    for i, m in enumerate(matches):
        hh = int(m.group(1))
        time = f"{hh:02d}:{m.group(2)}"
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        note = text[start:end].strip(" ,/·") or None
        entry = {"time": time, "note": note}
        types = parse_type(note)
        if types:
            entry["type"] = types
        rec = parse_recurrence(note)
        if rec:
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
