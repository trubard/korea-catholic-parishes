#!/usr/bin/env python3
"""대전교구 미사시간 어댑터 (EUC-KR).

지역별 통합 목록 church.php?area={지역} 한 페이지에 본당별 정보+미사시간이 들어있음.
미사시간 형식: '▶평일 - 화/19, 수/10 ▶토요일 - 17 ▶주일 - 10:30' (시 단위 표기).
쿼리/응답 모두 EUC-KR.
"""
from __future__ import annotations

import re
from urllib.parse import quote

import requests

from base import MassAdapter, normalize_mass

BASE = "http://www.djcatholic.or.kr/home/pages/church.php"
AREAS = ("대전광역시", "세종특별자치시", "충청남도")
KDAY = {"월": "mon", "화": "tue", "수": "wed", "목": "thu", "금": "fri"}


def _norm_time(t: str) -> str:
    t = t.strip()
    if ":" in t:
        h, m = t.split(":", 1)
        return f"{int(h):02d}:{m[:2]}"
    if t.isdigit():
        return f"{int(t):02d}:00"
    return ""


def _times(seg: str) -> str:
    """'17, 10:30 교중' 같은 구간의 시각들을 'HH:MM ...' 로."""
    parts = []
    for tok in re.split(r"[,]", seg):
        m = re.match(r"\s*(\d{1,2}(?::\d{2})?)", tok)
        if m:
            t = _norm_time(m.group(1))
            note = tok[m.end():].strip(" /")
            parts.append(f"{t} {note}".strip() if note else t)
    return " ".join(parts)


def parse_daejeon_mass(text: str) -> dict:
    """'미사시간 ▶평일 - 화/19, 수/10 ▶토요일 - 17 ▶주일 - 10:30' 파싱."""
    weekday = {v: "" for v in KDAY.values()}
    sat = sun = ""
    for seg in re.split(r"▶", text):
        seg = seg.strip()
        if seg.startswith("평일"):
            body = seg[seg.find("-") + 1:]
            for tok in body.split(","):
                m = re.match(r"\s*([월화수목금])\s*/\s*(\d{1,2}(?::\d{2})?)", tok)
                if m:
                    weekday[KDAY[m.group(1)]] += (" " + _norm_time(m.group(2)))
        elif seg.startswith("토"):
            sat = _times(seg[seg.find("-") + 1:])
        elif seg.startswith("주일"):
            sun = _times(seg[seg.find("-") + 1:])
    return normalize_mass(weekday_cells={k: v.strip() for k, v in weekday.items()},
                          saturday=sat, sunday=sun, raw=text.strip())


class DaejeonAdapter(MassAdapter):
    diocese = "대전교구"

    def collect(self, session: requests.Session) -> list[dict]:
        records: list[dict] = []
        seen: set[str] = set()
        for area in AREAS:
            url = f"{BASE}?area={quote(area, encoding='euc-kr')}"
            try:
                r = session.get(url, timeout=40)
                r.raise_for_status()
            except Exception:  # noqa: BLE001
                continue
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.content.decode("euc-kr", "replace"), "html.parser")
            for el in soup.find_all(string=re.compile("미사시간")):
                # 본당 블록: '본당전화/팩스' 를 포함하는 조상까지 상승
                block = el.parent
                for _ in range(6):
                    if block is None:
                        break
                    t = block.get_text(" ", strip=True)
                    if "본당전화" in t and "주임신부" in t:
                        break
                    block = block.parent
                if block is None:
                    continue
                bt = " ".join(block.get_text(" ", strip=True).split())
                nm = re.search(r"본당\s+(\S+)\s+주임신부", bt)
                ph = re.search(r"본당전화/팩스\s+([\d\-]+)", bt)
                mm = re.search(r"미사시간\s*(▶.*?)(?:관할구역|$)", bt)
                if not (nm and mm):
                    continue
                name = nm.group(1)
                if name in seen:
                    continue
                seen.add(name)
                records.append({
                    "parish_name": name, "diocese": self.diocese,
                    "phone": ph.group(1) if ph else None,
                    "source_url": url,
                    "mass": parse_daejeon_mass(mm.group(1)),
                })
        return records
