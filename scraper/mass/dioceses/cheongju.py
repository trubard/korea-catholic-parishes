#!/usr/bin/env python3
"""청주교구 미사시간 어댑터.

목록 /parish/parish 의 링크 → 상세 /parish/parish/view/{id}.
상세: '미사시간 ...(주간 날짜)' 헤더 뒤에 월~주일 시간(평문). 정보표에 전화.
"""
from __future__ import annotations

import re

import requests

from base import MassAdapter, get_soup, normalize_mass, split_day_labeled

BASE = "http://cdcj.or.kr/"
_VIEW_RE = re.compile(r"/parish/parish/view/(\d+)")


class CheongjuAdapter(MassAdapter):
    diocese = "청주교구"

    def collect(self, session: requests.Session) -> list[dict]:
        soup = get_soup(session, f"{BASE}parish/parish")
        ids: dict[str, str] = {}
        for a in soup.find_all("a", href=_VIEW_RE):
            pid = _VIEW_RE.search(a["href"]).group(1)
            name = " ".join(a.get_text(" ", strip=True).split())
            if pid not in ids:
                ids[pid] = name

        records: list[dict] = []
        for pid, name in ids.items():
            url = f"{BASE}parish/parish/view/{pid}"
            try:
                s = get_soup(session, url)
            except Exception:  # noqa: BLE001
                continue
            # 미사시간 블록
            block = None
            for el in s.find_all(string=re.compile("미사시간")):
                cont = el.find_parent(["div", "td", "section", "li"])
                if cont and split_day_labeled(cont.get_text(" ", strip=True)):
                    block = cont.get_text(" ", strip=True)
                    break
            days = split_day_labeled(block) if block else {}
            # 전화 (정보표 '전화' 행)
            phone = None
            for tr in s.find_all("tr"):
                cs = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
                if len(cs) == 2 and cs[0].strip() in ("전화", "전화번호"):
                    phone = cs[1].strip() or None
                    break
            if not days:
                # 미사시간 미기재 — 전화만이라도 있으면 빈 mass 로 남기지 않고 skip
                continue
            mass = normalize_mass(
                weekday_cells={d: days.get(d, "") for d in ("mon", "tue", "wed", "thu", "fri")},
                saturday=days.get("saturday", ""), sunday=days.get("sunday", ""),
                raw=" ".join(f"{k}:{v}" for k, v in days.items()),
            )
            records.append({
                "parish_name": name, "diocese": self.diocese,
                "phone": phone, "source_url": url, "mass": mass,
            })
        return records
