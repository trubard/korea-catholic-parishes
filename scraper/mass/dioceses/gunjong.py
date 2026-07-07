#!/usr/bin/env python3
"""군종교구 미사시간 어댑터.

목록 index.asp?ChurchMemberGrade={0..5} 의 fn_detail('org_cd') → 상세 detail-page.asp?org_cd=.
상세: 정보표(본당명·전화) + 미사표(요일 열, '10시30분'·'19:00' 혼용).
"""
from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

from base import MassAdapter, korean_to_hhmm, normalize_mass

BASE = "https://www.gunjong.or.kr/main-parish/"
_CD_RE = re.compile(r"fn_detail\('?(\d+)'?\)")
_DAY = {"월": "mon", "화": "tue", "수": "wed", "목": "thu", "금": "fri",
        "토": "saturday", "주일": "sunday", "일": "sunday"}
_PHONE_RE = re.compile(r"0\d{1,2}\)\s?\d{3,4}-\d{4}|0\d{1,2}-\d{3,4}-\d{4}")


def _get(session, url):
    r = session.get(url, timeout=40, verify=False)
    r.raise_for_status()
    return BeautifulSoup(r.content.decode("utf-8", "replace"), "html.parser")


class GunjongAdapter(MassAdapter):
    diocese = "군종교구"

    def collect(self, session: requests.Session) -> list[dict]:
        codes: list[str] = []
        for grade in range(0, 6):
            try:
                soup = _get(session, f"{BASE}index.asp?ChurchMemberGrade={grade}")
            except Exception:  # noqa: BLE001
                continue
            codes.extend(_CD_RE.findall(str(soup)))
        codes = list(dict.fromkeys(codes))

        records: list[dict] = []
        for cd in codes:
            url = f"{BASE}detail-page.asp?org_cd={cd}"
            try:
                s = _get(session, url)
            except Exception:  # noqa: BLE001
                continue
            # 정보표: 4셀(라벨|값|라벨|값) 행에서 본당명·전화
            name = phone = None
            for tr in s.find_all("tr"):
                cs = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
                for i in range(len(cs) - 1):
                    if "본당명" in cs[i] and not name:
                        name = cs[i + 1].strip()
                    elif cs[i].strip() in ("전화", "전화번호") and not phone:
                        m = _PHONE_RE.search(cs[i + 1])
                        phone = m.group(0) if m else (cs[i + 1].strip() or None)
            # 미사표: 요일 헤더 + 데이터행(위치 대응)
            kmap: dict[str, str] = {}
            for tb in s.find_all("table"):
                heads = [c.get_text(strip=True) for c in tb.find_all(["th", "td"])
                         if c.get_text(strip=True) in _DAY]
                rows = tb.find_all("tr")
                if len(rows) < 2 or "월" not in [h for h in heads]:
                    continue
                header = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
                for tr in rows[1:]:
                    cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
                    if not any(re.search(r"\d", c) for c in cells):
                        continue
                    for i, day in enumerate(header):
                        if day in _DAY and i < len(cells):
                            v = korean_to_hhmm(cells[i])
                            if re.search(r"\d{1,2}:\d{2}", v):
                                kmap.setdefault(_DAY[day], v)
                    break
                if kmap:
                    break
            if not name or not kmap:
                continue
            mass = normalize_mass(
                weekday_cells={d: kmap.get(d, "") for d in
                               ("mon", "tue", "wed", "thu", "fri")},
                saturday=kmap.get("saturday", ""), sunday=kmap.get("sunday", ""),
                raw="; ".join(f"{k} {v}" for k, v in kmap.items()))
            records.append({
                "parish_name": name, "diocese": self.diocese,
                "phone": phone, "source_url": url, "mass": mass})
        return records
