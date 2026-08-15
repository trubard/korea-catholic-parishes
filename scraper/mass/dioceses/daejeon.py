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


def parse_daejeon_mass(text: str) -> dict:
    """'미사시간 ▶평일 - 화/19, 수/10 ▶토요일 - 17 ▶주일 - 10:30' 파싱.

    구간(▶)만 나누고, 각 구간의 시각 문자열은 공통 parse_time_cell 에 위임한다
    (홑숫자·슬래시·괄호·한글시각·부정표현 처리는 base.py 가 담당).
    평일은 '요일/시각' 이 섞여 오므로 요일별로 갈라 담는다.
    """
    weekday = {v: "" for v in KDAY.values()}
    sat = sun = ""
    for seg in re.split(r"▶", text):
        seg = seg.strip()
        # 구간명 뒤 구분자(-, _, :, – 등)를 무엇이든 떼어낸다(§4).
        body = re.sub(r"^(?:평일|토요특전|토요일|토|주일)\s*[-_:–—]?\s*", "", seg)
        if seg.startswith("평일"):
            # '화/19, 수/10, 목/10, 금/19' → 요일별 시각
            for tok in body.split(","):
                m = re.match(r"\s*([월화수목금])\s*/\s*(.+)", tok)
                if m:
                    weekday[KDAY[m.group(1)]] += " " + m.group(2).strip()
        elif seg.startswith("토"):        # 토요일·토요특전 등 누적
            sat = (sat + " " + body).strip()
        elif seg.startswith("주일"):
            sun = (sun + " " + body).strip()
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
