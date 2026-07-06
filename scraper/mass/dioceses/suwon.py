#!/usr/bin/env python3
"""수원교구 미사시간 어댑터.

목록 /parish/parish 의 링크(serial + church=본당명) → 상세 /parish/parish/2?serial=..&church=..
상세: '미사시간 안내 ( 날짜 ) 월 10:00 화 19:30 ... 주일 ...' 평문 div.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

import requests

from base import MassAdapter, get_soup, normalize_mass, split_day_labeled

BASE = "http://www.casuwon.or.kr/"
_PHONE_RE = re.compile(r"0\d{1,2}[-)]\s?\d{3,4}-\d{4}")


class SuwonAdapter(MassAdapter):
    diocese = "수원교구"

    def collect(self, session: requests.Session) -> list[dict]:
        soup = get_soup(session, f"{BASE}parish/parish")
        parishes = []
        seen = set()
        for a in soup.find_all("a", href=True):
            if "/parish/parish/2?" not in a["href"]:
                continue
            q = parse_qs(urlparse(a["href"]).query)
            serial = (q.get("serial") or [None])[0]
            church = (q.get("church") or [None])[0]
            if serial and serial not in seen:
                seen.add(serial)
                parishes.append((serial, church or a.get_text(strip=True)))

        records: list[dict] = []
        for serial, name in parishes:
            url = f"{BASE}parish/parish/2?serial={serial}&church={name}"
            try:
                s = get_soup(session, url)
            except Exception:  # noqa: BLE001
                continue
            # 미사시간 텍스트가 있는 요소 찾기
            block = None
            for el in s.find_all(string=re.compile("미사시간")):
                cont = el.find_parent(["div", "td", "section"])
                if cont and split_day_labeled(cont.get_text(" ", strip=True)):
                    block = cont.get_text(" ", strip=True)
                    break
            if not block:
                continue
            days = split_day_labeled(block)
            if not days:
                continue
            m = _PHONE_RE.search(s.get_text(" ", strip=True))
            mass = normalize_mass(
                weekday_cells={d: days.get(d, "") for d in ("mon", "tue", "wed", "thu", "fri")},
                saturday=days.get("saturday", ""), sunday=days.get("sunday", ""),
                raw=" ".join(f"{k}:{v}" for k, v in days.items()),
            )
            records.append({
                "parish_name": name, "diocese": self.diocese,
                "phone": m.group(0) if m else None, "source_url": url, "mass": mass,
            })
        return records
