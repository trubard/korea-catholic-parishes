#!/usr/bin/env python3
"""인천교구 미사시간 어댑터.

통합 미사시간 페이지 church_misa.do?pageNo=N. 표가 2행 페어:
  (성당명 | 미사시간보기 | 사제 | 주소 | 전화)  +  (미사 평문 한 셀)
미사 평문: '월 오전 6시 30분 화 오후 7시 30분 ... 일 오전 10시 30분(교중) ... 비고 (...)'
"""
from __future__ import annotations

import re

import requests

from base import MassAdapter, get_soup, korean_to_hhmm, normalize_mass

BASE = "http://www.caincheon.or.kr/church/church_misa.do"
_DAY = {"월": "mon", "화": "tue", "수": "wed", "목": "thu", "금": "fri",
        "토": "saturday", "일": "sunday"}


def _split_incheon(text: str) -> dict:
    text = re.split(r"비고", text)[0]          # 비고/업데이트 이후 제거
    text = korean_to_hhmm(text)                # 한글시간 -> HH:MM
    text = re.sub(r"\s+", " ", text)
    poss = [(m.start(), m.group()) for m in re.finditer(r"[월화수목금토일]", text)]
    result: dict = {}
    for i, (pos, lb) in enumerate(poss):
        end = poss[i + 1][0] if i + 1 < len(poss) else len(text)
        val = text[pos + 1:end].strip(" :,")
        if re.search(r"\d{1,2}:\d{2}", val):
            result.setdefault(_DAY[lb], val)
    return result


class IncheonAdapter(MassAdapter):
    diocese = "인천교구"

    def collect(self, session: requests.Session) -> list[dict]:
        records: list[dict] = []
        seen: set[str] = set()
        for page in range(1, 20):
            soup = get_soup(session, f"{BASE}?pageSize=12&pageNo={page}")
            table = soup.find("table")
            if not table:
                break
            found = 0
            pending = None
            for tr in table.find_all("tr"):
                cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
                if cells and cells[0] == "성당명":  # 표 헤더행
                    continue
                if len(cells) >= 5:  # 성당 헤더 행(th)
                    name = re.sub(r"미사시간\s*보기.*", "", cells[0]).strip()
                    phone = cells[4].strip() if len(cells) > 4 else None
                    pending = (name, phone)
                elif len(cells) == 1 and pending:  # 미사 평문 행
                    name, phone = pending
                    pending = None
                    if not name or name in seen:
                        continue
                    days = _split_incheon(cells[0])
                    if not days:
                        continue
                    seen.add(name)
                    found += 1
                    mass = normalize_mass(
                        weekday_cells={d: days.get(d, "") for d in
                                       ("mon", "tue", "wed", "thu", "fri")},
                        saturday=days.get("saturday", ""), sunday=days.get("sunday", ""),
                        raw=cells[0].strip())
                    records.append({
                        "parish_name": name, "diocese": self.diocese,
                        "phone": phone, "source_url": f"{BASE}?pageNo={page}",
                        "mass": mass})
            if found == 0:
                break
        return records
