#!/usr/bin/env python3
"""제주교구 미사시간 어댑터.

지구별 통합 미사시간 페이지(mass_citywest/east/west/south)의 '성당' 표를 파싱.
각 표: [성당 | 월 화 수 목 금 토 일]. 토=특전(주일 전야), 일=주일.
전화번호는 표에 없어 본당명으로 조인.
"""
from __future__ import annotations

import requests

from base import MassAdapter, get_soup, normalize_mass

BASE = "https://www.diocesejeju.or.kr/"
SLUGS = ("mass_citywest", "mass_cityeast", "mass_west", "mass_south")


class JejuAdapter(MassAdapter):
    diocese = "제주교구"

    def collect(self, session: requests.Session) -> list[dict]:
        records: list[dict] = []
        seen: set[str] = set()
        for slug in SLUGS:
            url = BASE + slug
            soup = get_soup(session, url)
            for table in soup.find_all("table"):
                rows = table.find_all("tr")
                if not rows:
                    continue
                head = [c.get_text(strip=True)
                        for c in rows[0].find_all(["th", "td"])]
                if not head or head[0] != "성당":
                    continue  # '구분'(특별미사) 표 제외
                for tr in rows[2:]:  # 헤더 2행(성당|평일|주일 / 월~일) 건너뜀
                    cells = [c.get_text(" ", strip=True)
                             for c in tr.find_all(["th", "td"])]
                    if len(cells) < 8:
                        continue
                    name = " ".join(cells[0].split())  # 내부 공백 정규화
                    if not name or name in seen:
                        continue
                    seen.add(name)
                    days = cells[1:8]  # 월 화 수 목 금 토 일
                    mass = normalize_mass(
                        weekday_cells={"mon": days[0], "tue": days[1],
                                       "wed": days[2], "thu": days[3], "fri": days[4]},
                        saturday=days[5],
                        sunday=days[6],
                        raw=" | ".join(cells),
                    )
                    records.append({
                        "parish_name": name,
                        "diocese": self.diocese,
                        "phone": None,
                        "source_url": url,
                        "mass": mass,
                    })
        return records
