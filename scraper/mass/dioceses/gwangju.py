#!/usr/bin/env python3
"""광주대교구 미사시간 어댑터.

목록 /church/parish 의 링크(텍스트=본당명) → 상세 /church/parish/view/{id}.
상세: 정보표(전화번호) + 미사표([요일 | 시간]). 부산교구와 동일 구조.
"""
from __future__ import annotations

import re

import requests

from base import MassAdapter, get_soup, normalize_mass

BASE = "https://www.gjcatholic.or.kr/"
KDAY = {"월": "mon", "화": "tue", "수": "wed", "목": "thu", "금": "fri"}
_VIEW_RE = re.compile(r"/church/parish/view/(\d+)")


class GwangjuAdapter(MassAdapter):
    diocese = "광주대교구"

    def collect(self, session: requests.Session) -> list[dict]:
        soup = get_soup(session, f"{BASE}church/parish")
        parishes: dict[str, str] = {}
        for a in soup.find_all("a", href=_VIEW_RE):
            pid = _VIEW_RE.search(a["href"]).group(1)
            name = " ".join(a.get_text(" ", strip=True).split())
            if name and pid not in parishes:
                parishes[pid] = name

        records: list[dict] = []
        for pid, name in parishes.items():
            url = f"{BASE}church/parish/view/{pid}"
            try:
                s = get_soup(session, url)
            except Exception:  # noqa: BLE001
                continue
            phone = None
            kmap: dict[str, str] = {}
            for tr in s.find_all("tr"):
                cs = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
                if len(cs) != 2:
                    continue
                label, value = cs[0].strip(), cs[1].strip()
                if label == "전화번호" and value not in ("", "-"):
                    phone = value
                elif label in ("월", "화", "수", "목", "금", "토", "주일"):
                    kmap[label] = value
            if not kmap:
                continue
            mass = normalize_mass(
                weekday_cells={KDAY[k]: kmap.get(k, "") for k in KDAY},
                saturday=kmap.get("토", ""), sunday=kmap.get("주일", ""),
                raw="; ".join(f"{k} {v}" for k, v in kmap.items()),
            )
            records.append({
                "parish_name": name, "diocese": self.diocese,
                "phone": phone, "source_url": url, "mass": mass,
            })
        return records
