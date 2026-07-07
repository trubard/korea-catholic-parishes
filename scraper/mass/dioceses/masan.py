#!/usr/bin/env python3
"""마산교구 미사시간 어댑터 (큐레이션 맵 방식).

마산교구는 통합 본당 디렉토리가 없고 본당마다 독립 서브도메인({약칭}.cathms.kr)을
쓰며 미사 페이지 슬러그도 제각각이다. 따라서 아래 SITES 맵에 본당을 개별 등록해
구조화한다. 표(요일×시간대)가 있는 본당만 파싱하고, 미사시간을 이미지로 올린 본당은
표가 없어 자동 스킵된다. 새 본당은 SITES 에 (본당명: (서브도메인, 미사페이지경로))
한 줄을 추가하면 수집 대상이 된다.
"""
from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

from base import MassAdapter, normalize_mass

# 본당명: (서브도메인, 미사페이지 경로).  ※ 확인된 본당부터 점진적으로 확장.
SITES = {
    "거창": ("geo", "/xe/page_foxn59"),
    "명서동": ("ms", "/xe/churh9"),
    "회원동": ("hw", "/xe/page_MNku90"),   # 미사시간 이미지 → 표 없어 자동 스킵
}
_DAY = {"월": "mon", "화": "tue", "수": "wed", "목": "thu", "금": "fri",
        "토": "saturday", "주일": "sunday", "일": "sunday"}


def _get(session, url):
    r = session.get(url, timeout=15, verify=False)
    r.raise_for_status()
    for enc in ("utf-8", "euc-kr"):
        try:
            t = r.content.decode(enc)
            if "미사" in t or "요일" in t:
                return BeautifulSoup(t, "html.parser")
        except UnicodeDecodeError:
            pass
    return BeautifulSoup(r.content.decode("utf-8", "replace"), "html.parser")


class MasanAdapter(MassAdapter):
    diocese = "마산교구"

    def collect(self, session: requests.Session) -> list[dict]:
        records: list[dict] = []
        for name, (sub, path) in SITES.items():
            url = f"http://{sub}.cathms.kr{path}"
            try:
                soup = _get(session, url)
            except Exception:  # noqa: BLE001
                continue
            # 요일 헤더가 있는 미사표 찾기
            kmap: dict[str, str] = {}
            for table in soup.find_all("table"):
                if "요일" not in table.get_text():
                    continue
                for tr in table.find_all("tr"):
                    cells = [re.sub(r"\s+", " ", c.get_text(" ", strip=True))
                             for c in tr.find_all(["th", "td"])]
                    if not cells or cells[0] not in _DAY:
                        continue
                    times = " ".join(c for c in cells[1:]
                                     if re.search(r"\d{1,2}:\d{2}", c))
                    if times:
                        key = _DAY[cells[0]]
                        kmap[key] = (kmap.get(key, "") + " " + times).strip()
                if kmap:
                    break
            if not kmap:
                continue  # 표 없음(이미지 등) → 스킵
            mass = normalize_mass(
                weekday_cells={d: kmap.get(d, "") for d in
                               ("mon", "tue", "wed", "thu", "fri")},
                saturday=kmap.get("saturday", ""), sunday=kmap.get("sunday", ""),
                raw="; ".join(f"{k} {v}" for k, v in kmap.items()))
            records.append({
                "parish_name": name, "diocese": self.diocese,
                "phone": None, "source_url": url, "mass": mass})
        return records
