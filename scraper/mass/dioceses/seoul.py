#!/usr/bin/env python3
"""서울대교구 미사시간 어댑터.

본당 목록이 JS 로 로드되어 열거가 어려우나, 통합 미사시간 검색(/pro10314)이
지구코드(gubun2code)별로 결과 표를 서버 렌더링한다. 19개 지구를 순회.
표: [성당 | 미사시간 | 위치 | 전화번호]. 미사시간은 SUN/MON/.../SAT 요일코드 형식.
"""
from __future__ import annotations

import re

import requests

from base import MassAdapter, get_soup, normalize_mass

BASE = "http://aos.catholic.or.kr/"
# gubun2code (제1~제18 지구)
DISTRICTS = ("12", "13", "14", "15", "30", "18", "17", "16", "19", "20",
             "21", "22", "23", "24", "27", "25", "28", "26", "29")
DAYCODE = {"SUN": "sunday", "MON": "mon", "TUE": "tue", "WED": "wed",
           "THU": "thu", "FRI": "fri", "SAT": "saturday"}
_DAYSPLIT_RE = re.compile(r"\b(SUN|MON|TUE|WED|THU|FRI|SAT)\b")


def _split_by_daycode(text: str) -> dict:
    parts = _DAYSPLIT_RE.split(text)
    result: dict = {}
    for i in range(1, len(parts), 2):
        seg = parts[i + 1] if i + 1 < len(parts) else ""
        result[DAYCODE[parts[i]]] = seg.strip()
    return result


class SeoulAdapter(MassAdapter):
    diocese = "서울대교구"

    def collect(self, session: requests.Session) -> list[dict]:
        records: list[dict] = []
        seen: set[str] = set()
        for code in DISTRICTS:
            for page in range(1, 40):  # 지구별 curPage 순회(페이지당 3개)
                url = f"{BASE}pro10314?gubun2code={code}&curPage={page}"
                soup = get_soup(session, url)
                found = 0
                for table in soup.find_all("table"):
                    head = [c.get_text(strip=True) for c in table.find_all("th")]
                    if "미사시간" not in head:
                        continue
                    for tr in table.find_all("tr"):
                        cells = [c.get_text(" ", strip=True) for c in tr.find_all("td")]
                        if len(cells) < 2:
                            continue
                        name = re.sub(r"홈페이지\s*방문", "", cells[0]).strip()
                        mass_text = cells[1]
                        if not name or ":" not in mass_text:
                            continue
                        found += 1
                        if name in seen:
                            continue
                        seen.add(name)
                        days = _split_by_daycode(mass_text)
                        mass = normalize_mass(
                            weekday_cells={d: days.get(d, "") for d in
                                           ("mon", "tue", "wed", "thu", "fri")},
                            saturday=days.get("saturday", ""),
                            sunday=days.get("sunday", ""),
                            raw=mass_text,
                        )
                        records.append({
                            "parish_name": name, "diocese": self.diocese,
                            "phone": (cells[3] if len(cells) > 3 else None) or None,
                            "source_url": url, "mass": mass,
                        })
                if found == 0:
                    break
        return records
