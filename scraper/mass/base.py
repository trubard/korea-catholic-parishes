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
        note = text[start:end].strip(" ,/·")
        entries.append({"time": time, "note": note or None})
    return entries


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
