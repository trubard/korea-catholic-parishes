#!/usr/bin/env python3
"""춘천교구 미사시간 어댑터.

/parish/missa 한 페이지에 지구별 표가 모여 있음.
각 표: [요일 본당 | 월 화 수 목 금 토 주일]. 토=특전, 주일=주일. 전화 없음 → 본당명 조인.
"""
from __future__ import annotations

import requests

from base import MassAdapter, get_soup, normalize_mass

URL = "http://www.cccatholic.or.kr/parish/missa"


class ChuncheonAdapter(MassAdapter):
    diocese = "춘천교구"

    def collect(self, session: requests.Session) -> list[dict]:
        soup = get_soup(session, URL)
        records: list[dict] = []
        seen: set[str] = set()
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if not rows:
                continue
            head = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
            if not head or "본당" not in head[0]:
                continue
            for tr in rows[1:]:
                cells = [c.get_text(" ", strip=True)
                         for c in tr.find_all(["th", "td"])]
                if len(cells) < 8:
                    continue
                name = " ".join(cells[0].split())
                if not name or name in seen:
                    continue
                seen.add(name)
                days = cells[1:8]  # 월 화 수 목 금 토 주일
                mass = normalize_mass(
                    weekday_cells={"mon": days[0], "tue": days[1], "wed": days[2],
                                   "thu": days[3], "fri": days[4]},
                    saturday=days[5], sunday=days[6],
                    raw=" | ".join(cells),
                )
                records.append({
                    "parish_name": name, "diocese": self.diocese,
                    "phone": None, "source_url": URL, "mass": mass,
                })
        return records
