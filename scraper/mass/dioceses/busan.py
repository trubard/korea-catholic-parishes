#!/usr/bin/env python3
"""부산교구 미사시간 어댑터.

목록 /church/parish?page=N 에서 view 링크 수집 → 상세 /church/parish/view/{id}.
상세: 정보표(전화번호 포함) + 미사표([요일 | 시간]). 전화번호로 조인.
"""
from __future__ import annotations

import re

import requests

from base import MassAdapter, get_soup, normalize_mass

BASE = "http://www.catholicbusan.or.kr/"
KDAY = {"월": "mon", "화": "tue", "수": "wed", "목": "thu", "금": "fri"}
_VIEW_RE = re.compile(r"/church/parish/view/(\d+)")
_PHONE_RE = re.compile(r"0\d{1,2}[-)]\s?\d{3,4}-\d{4}")


class BusanAdapter(MassAdapter):
    diocese = "부산교구"

    def _list(self, session) -> list[dict]:
        """목록 카드에서 (id, 본당명, 전화)를 수집."""
        parishes: list[dict] = []
        seen: set[str] = set()
        for page in range(1, 25):
            soup = get_soup(session, f"{BASE}church/parish?page={page}")
            cards = soup.find_all("div", class_="church")
            if not cards:
                break
            found = 0
            for card in cards:
                a = card.find("a", href=_VIEW_RE)
                if not a:
                    continue
                pid = _VIEW_RE.search(a["href"]).group(1)
                if pid in seen:
                    continue
                h4 = card.find("h4")
                name = h4.get_text(strip=True) if h4 else ""
                m = _PHONE_RE.search(card.get_text(" ", strip=True))
                phone = m.group(0) if m else None
                seen.add(pid)
                parishes.append({"id": pid, "name": name, "phone": phone})
                found += 1
            if found == 0:
                break
        return parishes

    def collect(self, session: requests.Session) -> list[dict]:
        records: list[dict] = []
        for p in self._list(session):
            pid, name, phone = p["id"], p["name"], p["phone"]
            url = f"{BASE}church/parish/view/{pid}"
            try:
                soup = get_soup(session, url)
            except Exception:  # noqa: BLE001
                continue
            kmap: dict[str, str] = {}
            for tr in soup.find_all("tr"):
                cs = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
                if len(cs) != 2:
                    continue
                label, value = cs[0].strip(), cs[1].strip()
                if label == "전화번호" and not phone and value not in ("", "정보 없음"):
                    phone = value  # 카드에 전화 없을 때만 상세에서 보완
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
